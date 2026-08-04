"""
Système de packs de fixtures distants — MyStrow.

Vérifie, télécharge et intègre des packs de fixtures publiés depuis l'admin
panel vers Firestore, puis fusionnés dans la bibliothèque locale de l'utilisateur.

Flux :
  1. FixturePackCheckWorker  → interroge Firestore, compare les versions locales
  2. FixturePackBanner       → bannière dans l'éditeur si mise à jour disponible
  3. FixturePackDownloadDialog → téléchargement avec progression + compteur
"""

import json
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QDialog, QProgressBar, QListWidget, QListWidgetItem, QApplication,
)
from PySide6.QtCore import Qt, Signal, QThread, QObject, QTimer
from PySide6.QtGui import QColor, QFont

# Fichiers locaux
PACKS_STATE_FILE = Path.home() / ".mystrow_fixture_packs.json"
FIXTURE_FILE     = Path.home() / ".mystrow_fixtures.json"

# Throttle : ne pas revérifier avant N secondes (1 heure)
_CHECK_INTERVAL = 3600


# ──────────────────────────────────────────────────────────────────────────────
# Gestion de l'état local
# ──────────────────────────────────────────────────────────────────────────────

def load_packs_state() -> dict:
    """
    Charge l'état local des packs téléchargés.
    Retourne : {"packs": {pack_id: {"version": int, "downloaded_at": int, "name": str}},
                "last_check": int}
    """
    try:
        if PACKS_STATE_FILE.exists():
            return json.loads(PACKS_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"packs": {}, "last_check": 0}


def save_packs_state(state: dict):
    try:
        PACKS_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def should_check_now(state: dict) -> bool:
    """Retourne True si le throttle est expiré (1h depuis la dernière vérification)."""
    return time.time() - state.get("last_check", 0) >= _CHECK_INTERVAL


# ──────────────────────────────────────────────────────────────────────────────
# Fusion des fixtures dans la bibliothèque locale
# ──────────────────────────────────────────────────────────────────────────────

def _load_user_fixtures() -> list:
    try:
        if FIXTURE_FILE.exists():
            data = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_user_fixtures(fixtures: list):
    FIXTURE_FILE.write_text(
        json.dumps(fixtures, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def merge_pack_fixtures(pack_fixtures: list, pack_id: str) -> int:
    """
    Fusionne les fixtures d'un pack dans ~/.mystrow_fixtures.json.
    Les doublons (même nom + fabricant) sont ignorés.
    Retourne le nombre de nouvelles fixtures effectivement ajoutées.
    """
    existing = _load_user_fixtures()
    existing_keys = {
        (f.get("name", "").strip(), f.get("manufacturer", "").strip())
        for f in existing
    }

    added = 0
    for fx in pack_fixtures:
        key = (fx.get("name", "").strip(), fx.get("manufacturer", "").strip())
        if key in existing_keys:
            continue
        fx_copy = {k: v for k, v in fx.items() if k != "builtin"}
        fx_copy["_pack_id"] = pack_id
        existing.append(fx_copy)
        existing_keys.add(key)
        added += 1

    if added > 0:
        _save_user_fixtures(existing)
    return added


# ──────────────────────────────────────────────────────────────────────────────
# Worker : vérification des packs disponibles (QThread)
# ──────────────────────────────────────────────────────────────────────────────

class FixturePackCheckWorker(QObject):
    """
    Interroge Firestore pour comparer les versions des packs distants
    avec les versions locales. Émet 'found' si des mises à jour sont disponibles.
    """
    found     = Signal(list)   # liste des packs à télécharger
    no_update = Signal()
    error     = Signal(str)

    def __init__(self, id_token: str = None):
        super().__init__()
        self._id_token = id_token

    def run(self):
        try:
            import firebase_client as fc

            # Vérification de connectivité rapide
            if not fc.has_internet():
                self.no_update.emit()
                return

            remote_packs = fc.fetch_fixture_packs_index(self._id_token)
        except Exception as e:
            self.error.emit(str(e))
            return

        state      = load_packs_state()
        local_info = state.get("packs", {})

        to_update = [
            p for p in remote_packs
            if p.get("version", 0) > local_info.get(p.get("id", ""), {}).get("version", -1)
        ]

        # Mettre à jour le timestamp de dernière vérification
        state["last_check"] = int(time.time())
        save_packs_state(state)

        if to_update:
            self.found.emit(to_update)
        else:
            self.no_update.emit()


# ──────────────────────────────────────────────────────────────────────────────
# Worker : téléchargement et fusion des packs (QThread)
# ──────────────────────────────────────────────────────────────────────────────

class FixturePackDownloadWorker(QObject):
    """
    Télécharge les packs un par un et fusionne leurs fixtures.
    Signaux de progression émis pour chaque étape.
    """
    pack_started     = Signal(str, int)   # (pack_name, pack_index)
    pack_done        = Signal(str, int)   # (pack_name, added_count)
    fixture_progress = Signal(int, int)   # (done, total) pour la barre courante
    all_done         = Signal(int, int)   # (total_new_fixtures, total_packs)
    error            = Signal(str)

    def __init__(self, packs: list, id_token: str = None):
        super().__init__()
        self._packs     = packs
        self._id_token  = id_token

    def run(self):
        try:
            import firebase_client as fc
            state      = load_packs_state()
            local_info = state.setdefault("packs", {})
            total_new  = 0

            for idx, meta in enumerate(self._packs):
                pack_id   = meta.get("id", "")
                pack_name = meta.get("name", pack_id)
                self.pack_started.emit(pack_name, idx)

                try:
                    full_pack = fc.fetch_fixture_pack(pack_id, self._id_token)
                except Exception as e:
                    self.error.emit(f"Pack « {pack_name} » : {e}")
                    continue

                fixtures = full_pack.get("fixtures", [])
                total_fx = len(fixtures)
                self.fixture_progress.emit(0, max(total_fx, 1))

                added = merge_pack_fixtures(fixtures, pack_id)
                self.fixture_progress.emit(total_fx, max(total_fx, 1))

                local_info[pack_id] = {
                    "version":       full_pack.get("version", 1),
                    "downloaded_at": int(time.time()),
                    "name":          pack_name,
                }
                total_new += added
                self.pack_done.emit(pack_name, added)

            save_packs_state(state)
            self.all_done.emit(total_new, len(self._packs))

        except Exception as e:
            self.error.emit(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Widget : bannière "Packs disponibles"
# ──────────────────────────────────────────────────────────────────────────────

class FixturePackBanner(QWidget):
    """
    Bannière compacte affichée en haut de l'éditeur de fixtures quand des
    packs distants sont disponibles ou mis à jour.
    """
    download_clicked = Signal(list)   # émet la liste des packs à télécharger

    def __init__(self, parent=None):
        super().__init__(parent)
        self._packs = []
        self.setFixedHeight(40)
        self.setStyleSheet(
            "QWidget { background:#0a1f28; border-bottom:1px solid #00d4ff33; }"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(10)

        icon = QLabel("⬇")
        icon.setStyleSheet(
            "color:#00d4ff; font-size:14px; background:transparent; border:none;"
        )
        lay.addWidget(icon)

        self._lbl = QLabel()
        self._lbl.setStyleSheet(
            "color:#00d4ff; font-size:12px; background:transparent; border:none;"
        )
        lay.addWidget(self._lbl, 1)

        self._btn_dl = QPushButton("Télécharger")
        self._btn_dl.setFixedHeight(26)
        self._btn_dl.setCursor(Qt.PointingHandCursor)
        self._btn_dl.setStyleSheet(
            "QPushButton { background:#00d4ff22; color:#00d4ff;"
            "  border:1px solid #00d4ff55; border-radius:4px;"
            "  font-size:11px; font-weight:bold; padding:0 12px; }"
            "QPushButton:hover { background:#00d4ff44; border-color:#00d4ff; }"
        )
        self._btn_dl.clicked.connect(lambda: self.download_clicked.emit(self._packs))
        lay.addWidget(self._btn_dl)

        btn_x = QPushButton("✕")
        btn_x.setFixedSize(22, 22)
        btn_x.setCursor(Qt.PointingHandCursor)
        btn_x.setStyleSheet(
            "QPushButton { background:transparent; color:#444; border:none; font-size:13px; }"
            "QPushButton:hover { color:#aaa; }"
        )
        btn_x.clicked.connect(self.hide)
        lay.addWidget(btn_x)

        self.hide()

    def set_packs(self, packs: list):
        self._packs    = packs
        total_fx       = sum(p.get("fixture_count", 0) for p in packs)
        n              = len(packs)
        if n == 1:
            txt = (
                f"Nouveau pack disponible : <b>{packs[0].get('name', '?')}</b>"
                f" — {total_fx} fixture(s)"
            )
        else:
            txt = (
                f"{n} packs de fixtures disponibles"
                f" — {total_fx} fixture(s) au total"
            )
        self._lbl.setText(txt)
        self.show()


# ──────────────────────────────────────────────────────────────────────────────
# Dialog : téléchargement avec progression
# ──────────────────────────────────────────────────────────────────────────────

class FixturePackDownloadDialog(QDialog):
    """
    Dialogue de téléchargement des packs avec :
      - Liste des packs (en attente / en cours / terminé)
      - Barre de progression par pack
      - Barre de progression globale
      - Compteur « X nouveaux fixtures téléchargés sur Y »
    """
    download_complete = Signal(int)   # total de nouvelles fixtures

    _STYLE = """
        QDialog     { background:#141414; color:#e0e0e0; }
        QLabel      { color:#e0e0e0; background:transparent; border:none; }
        QListWidget { background:#1a1a1a; border:1px solid #2a2a2a;
                      border-radius:6px; color:#ccc; font-size:12px; outline:none; }
        QListWidget::item { padding:6px 12px; border-radius:3px; }
        QProgressBar { background:#1a1a1a; border:1px solid #2a2a2a;
                       border-radius:4px; text-align:center; }
        QProgressBar::chunk { background:#00d4ff; border-radius:4px; }
        QPushButton { background:#2a2a2a; color:#ccc; border:1px solid #3a3a3a;
                      border-radius:5px; padding:6px 18px; font-size:12px; }
        QPushButton:hover    { border-color:#00d4ff; color:#fff; }
        QPushButton:disabled { background:#1a1a1a; color:#333; border-color:#2a2a2a; }
    """

    def __init__(self, packs: list, id_token: str = None, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Téléchargement des packs de fixtures — MyStrow")
        self.setFixedSize(520, 440)
        self.setStyleSheet(self._STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._packs     = packs
        self._id_token  = id_token
        self._total_new = 0
        self._thread    = None
        self._worker    = None

        self._build_ui()
        QTimer.singleShot(120, self._start_download)

    # ── Construction UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        # Titre
        title = QLabel("Mise à jour des packs de fixtures")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet("color:#00d4ff;")
        lay.addWidget(title)

        n   = len(self._packs)
        sub = QLabel(f"Téléchargement de {n} pack(s) depuis MyStrow Cloud…")
        sub.setStyleSheet("color:#666; font-size:11px;")
        lay.addWidget(sub)

        # Liste des packs
        self._pack_list = QListWidget()
        self._pack_list.setFixedHeight(130)
        self._pack_list.setSelectionMode(QListWidget.NoSelection)
        for p in self._packs:
            fx_count = p.get("fixture_count", 0)
            item = QListWidgetItem(
                f"  ○  {p.get('name', p.get('id', '?'))}   ({fx_count} fixture(s))"
            )
            item.setForeground(QColor("#555"))
            self._pack_list.addItem(item)
        lay.addWidget(self._pack_list)

        # Pack courant
        self._cur_label = QLabel("Préparation…")
        self._cur_label.setStyleSheet("font-size:11px; color:#888;")
        lay.addWidget(self._cur_label)

        self._fx_bar = QProgressBar()
        self._fx_bar.setRange(0, 100)
        self._fx_bar.setValue(0)
        self._fx_bar.setFixedHeight(6)
        self._fx_bar.setTextVisible(False)
        lay.addWidget(self._fx_bar)

        # Séparateur visuel
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#2a2a2a;")
        lay.addWidget(sep)

        # Compteur global (centré, bien visible)
        self._counter_lbl = QLabel("0 nouveau(x) fixture(s) téléchargé(s)")
        self._counter_lbl.setFont(QFont("Segoe UI", 12))
        self._counter_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._counter_lbl)

        # Barre + texte progression globale
        self._global_bar = QProgressBar()
        self._global_bar.setRange(0, max(n, 1))
        self._global_bar.setValue(0)
        self._global_bar.setFixedHeight(10)
        self._global_bar.setTextVisible(False)
        lay.addWidget(self._global_bar)

        self._global_lbl = QLabel(f"0 / {n} pack(s)")
        self._global_lbl.setStyleSheet("font-size:11px; color:#555;")
        self._global_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._global_lbl)

        lay.addStretch()

        self._btn_close = QPushButton("Fermer")
        self._btn_close.setEnabled(False)
        self._btn_close.clicked.connect(self.accept)
        lay.addWidget(self._btn_close, alignment=Qt.AlignRight)

    # ── Lancement du téléchargement ─────────────────────────────────────────

    def _start_download(self):
        self._worker = FixturePackDownloadWorker(self._packs, self._id_token)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.pack_started.connect(self._on_pack_started)
        self._worker.fixture_progress.connect(self._on_fixture_progress)
        self._worker.pack_done.connect(self._on_pack_done)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.error.connect(self._on_error)
        self._worker.all_done.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        self._thread.start()

    # ── Slots de progression ────────────────────────────────────────────────

    def _on_pack_started(self, pack_name: str, idx: int):
        n = len(self._packs)
        self._cur_label.setText(f"Téléchargement : {pack_name}…")
        self._fx_bar.setValue(0)
        self._global_bar.setValue(idx)
        self._global_lbl.setText(f"{idx + 1} / {n} pack(s)")

        item = self._pack_list.item(idx)
        if item:
            item.setText(item.text().replace("○", "⟳"))
            item.setForeground(QColor("#00d4ff"))

    def _on_fixture_progress(self, done: int, total: int):
        if total > 0:
            self._fx_bar.setValue(int(done * 100 / total))

    def _on_pack_done(self, pack_name: str, added: int):
        self._total_new += added
        self._counter_lbl.setText(
            f"{self._total_new} nouveau(x) fixture(s) téléchargé(s)"
        )
        # Trouver le bon item dans la liste et le cocher
        for i in range(self._pack_list.count()):
            item = self._pack_list.item(i)
            if item and pack_name in item.text():
                item.setText(item.text().replace("⟳", "✓"))
                item.setForeground(QColor("#4CAF50"))
                break

    def _on_all_done(self, total_new: int, total_packs: int):
        n = len(self._packs)
        self._global_bar.setValue(n)
        self._global_lbl.setText(f"{n} / {n} pack(s)")
        self._fx_bar.setValue(100)
        self._cur_label.setText("Téléchargement terminé  ✓")
        self._cur_label.setStyleSheet("font-size:11px; color:#4CAF50;")

        if total_new > 0:
            self._counter_lbl.setText(
                f"{total_new} nouveau(x) fixture(s) ajouté(s) à votre bibliothèque"
            )
            self._counter_lbl.setStyleSheet(
                "font-size:13px; color:#4CAF50; font-weight:bold;"
            )
        else:
            self._counter_lbl.setText("Bibliothèque déjà à jour — aucun doublon ajouté")
            self._counter_lbl.setStyleSheet("font-size:12px; color:#888;")

        self._btn_close.setEnabled(True)
        self.download_complete.emit(total_new)

    def _on_error(self, msg: str):
        self._cur_label.setText(f"Erreur : {msg}")
        self._cur_label.setStyleSheet("font-size:11px; color:#f44336;")
        self._btn_close.setEnabled(True)
