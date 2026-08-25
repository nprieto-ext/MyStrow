"""
controller_share — Partage communautaire des profils de contrôleurs MIDI.

Quand un utilisateur mappe son contrôleur avec l'assistant, il peut verser son
profil à la bibliothèque commune. Le trajet remplace l'ancien `mailto:` de
`MidiMappingWizard._share_profile`, qui collait le JSON dans le corps d'un mail :
au-delà d'une petite grille le profil dépassait les ~2 000 caractères admis par
un `mailto:` sous Windows et arrivait tronqué, sans que personne ne le voie.

Ce qui distingue ce partage de celui des fixtures (`fixture_share.py`) :

  * Pas de déclaration de provenance ni de filtre par licence. Une fixture est
    presque toujours extraite d'une base tierce (QLC+, OFL, GDTF Share) — d'où
    l'attestation et le quota anti-dump de la directive 96/9/CE. Un profil sorti
    de l'assistant est fabriqué par l'utilisateur en appuyant sur ses propres
    pads : il n'y a pas de base à recopier.

  * Une entrée canonique par MODÈLE de contrôleur, pas par variante. Trente
    personnes vont mapper le même Launchpad, chacune à sa façon, et aucune n'a
    tort — mais l'intérêt d'une bibliothèque commune est « je branche, ça
    marche », pas « choisis parmi douze mappings ». L'empreinte porte donc sur
    les mots-clés de détection et la géométrie, jamais sur le contenu du
    mapping : le premier profil approuvé pour un modèle tient la place.

Rien n'est publié directement : la soumission atterrit dans la collection
Firestore `controller_submissions` au statut "pending", et seule l'approbation
d'un administrateur écrit dans `controller_profiles`.

Le serveur (Cloud Function `controller_submit`) revalide TOUT — l'empreinte, la
structure du profil et le quota. Les contrôles de ce module sont là pour le
confort d'usage, pas pour la sécurité.
"""

import hashlib
import json

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox,
)

from controller_profile import (
    validate_profile, install_community_profile, installed_community_version,
    conflicting_local_profiles,
)
from i18n import tr

# Champs conservés lors de la soumission. Tout le reste (chemin du fichier
# local, drapeaux d'UI, restes d'une édition) est écarté : on ne transmet que la
# description du mapping.
_PAYLOAD_FIELDS = (
    "id", "name", "version", "keywords",
    "grid_rows", "grid_cols", "fader_count", "effect_count",
    "pad_map", "mute_map", "fader_map", "effect_map",
    "led_velocity_map", "led_colors", "led_dim_velocity",
)

# Garde-fou de taille, revérifié côté serveur. Un profil 8x8 complet pèse
# ~6 Ko ; au-delà de 64 Ko ce n'est plus un mapping.
MAX_PROFILE_BYTES = 64 * 1024


def controller_fingerprint(profile: dict) -> str:
    """
    Empreinte déterministe d'un MODÈLE de contrôleur : mots-clés de détection
    (normalisés) + géométrie. Sert d'ID de document Firestore, donc deux
    utilisateurs qui mappent le même appareil retombent sur le même document et
    le second est écarté comme doublon.

    Volontairement aveugle au contenu du mapping : deux mappings différents du
    même Launchpad DOIVENT entrer en collision, sinon la bibliothèque se
    remplit de variantes entre lesquelles personne ne peut trancher.

    Doit rester identique à `_controller_fingerprint` de la Cloud Function.
    """
    kws = sorted({
        str(k).strip().upper()
        for k in (profile.get("keywords") or [])
        if str(k).strip()
    })

    def _int(field):
        try:
            return int(profile.get(field) or 0)
        except (TypeError, ValueError):
            return 0

    geom = "{}x{}:{}:{}".format(
        _int("grid_rows"), _int("grid_cols"),
        _int("fader_count"), _int("effect_count"),
    )
    key = ("|".join(kws) + "::" + geom).encode("utf-8", "replace")
    return hashlib.sha1(key).hexdigest()[:32]


def build_submission_payload(profile: dict) -> dict:
    """Réduit un profil local à la description normalisée envoyée au serveur."""
    out = {k: profile[k] for k in _PAYLOAD_FIELDS if profile.get(k) is not None}
    out["name"] = str(profile.get("name", "")).strip()
    out["keywords"] = [
        str(k).strip() for k in (profile.get("keywords") or []) if str(k).strip()
    ]
    return out


def local_check(profile: dict) -> tuple[bool, str]:
    """(ok, raison) — refus prévisibles, dits avant l'aller-retour réseau.

    Même validation que pour un profil importé d'un tiers : un profil qu'on
    envoie à la communauté mérite au moins la sévérité de celui qu'on accepte
    d'elle.
    """
    ok, reason = validate_profile(profile)
    if not ok:
        return False, reason
    size = len(json.dumps(build_submission_payload(profile)).encode("utf-8"))
    if size > MAX_PROFILE_BYTES:
        return False, f"profil trop volumineux ({size // 1024} Ko)"
    return True, ""


# ──────────────────────────────────────────────────────────────────────────────
# Envoi (thread)
# ──────────────────────────────────────────────────────────────────────────────

class _SubmitWorker(QObject):
    done  = Signal(dict)
    error = Signal(str)

    def __init__(self, profile: dict):
        super().__init__()
        self._profile = profile

    def run(self):
        try:
            from license_manager import _get_fresh_token
            import firebase_client as fc

            token = _get_fresh_token()
            if not token:
                self.error.emit(
                    "Connectez-vous à votre compte MyStrow pour partager un profil.")
                return
            payload = build_submission_payload(self._profile)
            result = fc.submit_controller_profile(
                controller_fingerprint(self._profile), payload, token)
            self.done.emit(result or {})
        except Exception as e:
            self.error.emit(str(e))


class ProfileSubmitter(QObject):
    """Envoi asynchrone d'un profil, avec le thread tenu en vie le temps qu'il faut.

    Une classe plutôt qu'une fonction : sans référence forte au QThread et au
    worker, le ramasse-miettes de Python les détruit en vol et l'envoi meurt
    sans message.
    """

    done  = Signal(dict)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None

    def busy(self) -> bool:
        return self._thread is not None

    def submit(self, profile: dict):
        if self.busy():
            return
        ok, reason = local_check(profile)
        if not ok:
            self.error.emit(f"Profil incomplet : {reason}")
            return
        thread = QThread(self)
        worker = _SubmitWorker(profile)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.error.connect(self._on_error)
        self._thread = thread
        self._worker = worker
        thread.start()

    def stop(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    def _on_done(self, result: dict):
        self.stop()
        self.done.emit(result)

    def _on_error(self, msg: str):
        self.stop()
        self.error.emit(msg)


# ──────────────────────────────────────────────────────────────────────────────
# Descente : bibliothèque communautaire
# ──────────────────────────────────────────────────────────────────────────────

def parse_published(doc: dict) -> dict | None:
    """Reconstruit le profil d'un document `controller_profiles`.

    Le mapping voyage dans un unique champ texte `profile_json` plutôt qu'en
    map Firestore imbriquée : les clés de `pad_map` sont des « r,c » et un
    profil complet fait 200 entrées. Une chaîne se relit sans conversion et
    échappe aux règles de nommage des champs Firestore.
    """
    raw = doc.get("profile_json")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    ok, _ = validate_profile(data)
    return data if ok else None


def match_port(profiles: list, port_name: str) -> list:
    """Profils communautaires dont un mot-clé apparaît dans ce nom de port.

    Même règle que `controller_profile.find_profile_for_port`, mais appliquée à
    la bibliothèque distante — c'est ce qui permet de proposer un profil pour un
    contrôleur que l'utilisateur vient de brancher et que MyStrow ne connaît pas.
    """
    upper = (port_name or "").upper()
    if not upper:
        return []
    out = []
    for entry in profiles:
        for kw in entry.get("keywords") or []:
            if kw and str(kw).upper() in upper:
                out.append(entry)
                break
    return out


class _FetchWorker(QObject):
    done  = Signal(list)
    error = Signal(str)

    def run(self):
        try:
            import firebase_client as fc
            try:
                from license_manager import _get_fresh_token
                token = _get_fresh_token()
            except Exception:
                token = None
            self.done.emit(fc.fetch_controller_profiles(token) or [])
        except Exception as e:
            self.error.emit(str(e))


class LibraryFetcher(QObject):
    """Chargement asynchrone de la bibliothèque communautaire."""

    done  = Signal(list)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None

    def busy(self) -> bool:
        return self._thread is not None

    def fetch(self):
        if self.busy():
            return
        thread = QThread(self)
        worker = _FetchWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.error.connect(self._on_error)
        self._thread = thread
        self._worker = worker
        thread.start()

    def stop(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    def _on_done(self, rows: list):
        self.stop()
        self.done.emit(rows)

    def _on_error(self, msg: str):
        self.stop()
        self.error.emit(msg)


# ──────────────────────────────────────────────────────────────────────────────
# Fenêtre « Bibliothèque communautaire »
# ──────────────────────────────────────────────────────────────────────────────

_SS = """
QDialog { background: #0c0c0c; color: #ddd; font-family: 'Segoe UI'; font-size: 10pt; }
QLabel  { color: #bbb; background: transparent; }
QListWidget {
    background: #141414; color: #ddd;
    border: 1px solid #262626; border-radius: 6px; font-size: 11pt;
}
QListWidget::item { padding: 7px 10px; border-bottom: 1px solid #1c1c1c; }
QListWidget::item:selected { background: #002b3d; color: #7fe9ff; }
QPushButton {
    background: #1e1e1e; color: #ccc; border: 1px solid #3a3a3a;
    border-radius: 6px; padding: 7px 16px; font-size: 10pt;
}
QPushButton:hover { border-color: #00d4ff; color: #fff; }
QPushButton:disabled { color: #555; border-color: #262626; }
"""


class CommunityControllerDialog(QDialog):
    """Liste les profils partagés et en installe un.

    Le nom du port MIDI branché, quand on l'a, remonte en tête les profils qui
    le reconnaissent : c'est la seule chose que l'utilisateur cherche en
    ouvrant cette fenêtre, et il n'a aucun moyen de savoir lequel des vingt
    profils correspond à son boîtier.
    """

    def __init__(self, parent=None, port_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("cs_lib_title"))
        self.setMinimumSize(560, 440)
        self.setStyleSheet(_SS)
        self._port_name = port_name or ""
        self._rows = []
        self.installed_path = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel(tr("cs_lib_header"))
        title.setStyleSheet("color:#00aaff; font-size:13pt; font-weight:bold;")
        lay.addWidget(title)

        self._sub = QLabel(tr("cs_lib_loading"))
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet("color:#888; font-size:9pt;")
        lay.addWidget(self._sub)

        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._on_selection)
        self._list.itemDoubleClicked.connect(lambda *_: self._install())
        lay.addWidget(self._list, 1)

        warn = QLabel(tr("cs_lib_warning"))
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#c8a24a; font-size:9pt;")
        lay.addWidget(warn)

        row = QHBoxLayout()
        row.addStretch()
        self._btn_install = QPushButton(tr("cs_lib_install"))
        self._btn_install.setEnabled(False)
        self._btn_install.clicked.connect(self._install)
        row.addWidget(self._btn_install)
        btn_close = QPushButton(tr("cs_lib_close"))
        btn_close.clicked.connect(self.reject)
        row.addWidget(btn_close)
        lay.addLayout(row)

        self._fetcher = LibraryFetcher(self)
        self._fetcher.done.connect(self._on_loaded)
        self._fetcher.error.connect(self._on_error)
        self._fetcher.fetch()

    # ── Chargement ────────────────────────────────────────────────────────

    def _on_loaded(self, rows: list):
        matches = {id(r) for r in match_port(rows, self._port_name)}
        # Les profils qui reconnaissent le port branché d'abord, le reste ensuite.
        rows = sorted(rows, key=lambda r: (0 if id(r) in matches else 1,
                                           str(r.get("name", "")).lower()))
        self._rows = rows

        if not rows:
            self._sub.setText(tr("cs_lib_empty"))
            return
        if matches:
            self._sub.setText(tr("cs_lib_match", n=len(matches), port=self._port_name))
            self._sub.setStyleSheet("color:#5fd18a; font-size:9pt;")
        else:
            self._sub.setText(tr("cs_lib_count", n=len(rows)))

        for r in rows:
            name = r.get("name", "?")
            kws  = ", ".join(r.get("keywords") or [])
            geom = f"{r.get('grid_rows', 0)}×{r.get('grid_cols', 0)} pads"
            if r.get("fader_count"):
                geom += f", {r.get('fader_count')} faders"
            label = f"{name}\n    {geom}   ·   {kws}"
            if id(r) in matches:
                label = f"✓  {label}"
            local = installed_community_version(r.get("fingerprint", ""))
            remote = int(r.get("version", 0) or 0)
            if local and local >= remote:
                label += "   ·   " + tr("cs_lib_installed")
            elif local:
                label += "   ·   " + tr("cs_lib_update")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r)
            self._list.addItem(item)

    def _on_error(self, msg: str):
        self._sub.setText(tr("cs_lib_error", e=msg))
        self._sub.setStyleSheet("color:#ee6666; font-size:9pt;")

    # ── Installation ──────────────────────────────────────────────────────

    def _on_selection(self):
        self._btn_install.setEnabled(bool(self._list.selectedItems()))

    def _install(self):
        items = self._list.selectedItems()
        if not items:
            return
        row = items[0].data(Qt.UserRole) or {}
        profile = parse_published(row)
        if profile is None:
            QMessageBox.warning(self, tr("cs_lib_title"), tr("cs_lib_corrupt"))
            return

        # Deux profils qui répondent au même mot-clé se disputent la détection,
        # et c'est l'ordre alphabétique des fichiers qui tranche. Le dire avant.
        clash = conflicting_local_profiles(profile.get("keywords"),
                                           row.get("fingerprint", ""))
        if clash and QMessageBox.question(
            self, tr("cs_lib_title"),
            tr("cs_lib_clash", names="\n  · ".join(clash)),
        ) != QMessageBox.Yes:
            return

        try:
            path, updated = install_community_profile(
                profile, row.get("fingerprint", ""), int(row.get("version", 0) or 0))
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, tr("cs_lib_title"), tr("cs_lib_failed", e=str(e)))
            return
        self.installed_path = path
        QMessageBox.information(
            self, tr("cs_lib_title"),
            tr("cs_lib_updated" if updated else "cs_lib_ok", name=profile.get("name", "")))
        self.accept()

    def reject(self):
        self._fetcher.stop()
        super().reject()

    def closeEvent(self, event):
        self._fetcher.stop()
        super().closeEvent(event)
