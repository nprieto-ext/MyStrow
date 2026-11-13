"""Onglet « Apps tablette » de l'admin : lance et suit les builds Codemagic.

Deux workflows (codemagic.yaml) :
  - android-play  : AAB signé → Google Play, PRODUCTION 100 % (plus de brouillon) ;
  - ios-appstore  : IPA → App Store Connect, soumis tout seul à l'examen Apple
                    puis publié dès la validation.
Ils partent de `main` tel qu'il est sur GitHub : ce qui n'est pas poussé n'y est pas.
Le plan gratuit ne fait qu'un build à la fois : le second attend « En file ».

API REST Codemagic (https://api.codemagic.io, en-tête `x-auth-token`) :
  GET  /apps                → trouve l'appli MyStrow (son identifiant, gardé en cache)
  POST /builds              → {appId, workflowId, branch} → {buildId}
  GET  /builds?appId=…      → historique
  GET  /builds/{id}         → état + étapes
  POST /builds/{id}/cancel

Le JETON n'est JAMAIS dans le dépôt : `~/.mystrow-android/codemagic_token.txt`
(Codemagic › Account settings › API token › Show), à côté de la clé
d'envoi Android. Tout le réseau se fait dans des threads ; l'interface ne
bloque jamais.
"""

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

API = "https://api.codemagic.io"
CONF_DIR = Path.home() / ".mystrow-android"
TOKEN_FILE = CONF_DIR / "codemagic_token.txt"
CACHE_FILE = CONF_DIR / "codemagic.json"
BRANCH = "main"

WORKFLOWS = {
    "android-play": ("Android", "Google Play · production 100 %"),
    "ios-appstore": ("iOS", "App Store · examen Apple puis publication"),
}

# Statuts Codemagic → (libellé, couleur, en cours ?)
STATUS = {
    "queued":     ("En file",      "#c47f17", True),
    "waiting":    ("En attente",   "#c47f17", True),   # attend une machine (plan gratuit : 1 à la fois)
    "preparing":  ("Préparation",  "#00d4ff", True),
    "fetching":   ("Récupération", "#00d4ff", True),
    "building":   ("Compilation",  "#00d4ff", True),
    "testing":    ("Tests",        "#00d4ff", True),
    "finishing":  ("Finalisation", "#00d4ff", True),
    "publishing": ("Envoi store",  "#00d4ff", True),
    "finished":   ("Réussi ✓",     "#3fbf5a", False),
    "warning":    ("Réussi (avert.)", "#c4b517", False),
    "failed":     ("Échec ✗",      "#e05252", False),
    "canceled":   ("Annulé",       "#888888", False),
    "timeout":    ("Trop long ✗",  "#e05252", False),
    "skipped":    ("Ignoré",       "#888888", False),
}

# Thème (mêmes valeurs qu'admin_panel.py)
BG_MAIN, BG_PANEL, BG_INPUT = "#1a1a1a", "#111111", "#2a2a2a"
ACCENT, TEXT, TEXT_DIM = "#00d4ff", "#ffffff", "#aaaaaa"
_BTN = ("QPushButton { background:#2a2a2a; color:#ffffff; border:1px solid #3a3a3a;"
        " border-radius:5px; padding:0 12px; font-size:12px; }"
        "QPushButton:hover { border-color:#00d4ff; } QPushButton:disabled { color:#666; }")
_BTN_GO = ("QPushButton { background:#00d4ff; color:#000; border:none; border-radius:5px;"
           " padding:0 14px; font-size:12px; font-weight:bold; }"
           "QPushButton:hover { background:#33ddff; } QPushButton:disabled { background:#2a4a52; color:#666; }")


# ── Réseau (threads) ──────────────────────────────────────────────────────────

class CodemagicError(Exception):
    pass


def read_token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _call(method: str, path: str, token: str, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "x-auth-token": token, "Content-Type": "application/json",
        "User-Agent": "mystrow-admin"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        txt = ""
        try:
            txt = e.read().decode()[:300]
        except Exception:
            pass
        if e.code in (401, 403):
            raise CodemagicError("Jeton Codemagic refusé : recopiez-le depuis Account settings › API token.")
        raise CodemagicError(f"Codemagic a répondu {e.code} {txt}")
    except Exception as e:
        raise CodemagicError(f"Codemagic injoignable ({e})")


def find_app_id(token: str) -> str:
    """Identifiant de l'appli MyStrow sur Codemagic (cache local)."""
    try:
        c = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if c.get("app_id"):
            return c["app_id"]
    except Exception:
        pass
    apps = _call("GET", "/apps", token).get("applications") or []
    def score(a):
        txt = json.dumps(a).lower()
        return ("ios-appstore" in txt) * 4 + ("android-play" in txt) * 4 + ("mystrow" in txt) * 2
    apps = sorted(apps, key=score, reverse=True)
    if not apps or score(apps[0]) == 0:
        raise CodemagicError("Aucune appli MyStrow trouvée sur ce compte Codemagic.")
    app_id = apps[0].get("_id") or apps[0].get("id")
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps({"app_id": app_id, "name": apps[0].get("appName", "")}), encoding="utf-8")
    return app_id


def wf(b) -> str:
    """Workflow du build : `fileWorkflowId` pour un codemagic.yaml (workflowId vaut alors None)."""
    return b.get("fileWorkflowId") or b.get("workflowId") or ""


def _ts(s):
    """Date ISO de Codemagic → epoch (None si absente)."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ── Onglet ────────────────────────────────────────────────────────────────────

class _Bridge(QObject):
    builds = Signal(object)        # liste des builds, ou CodemagicError
    started = Signal(object)       # (workflow, buildId) ou CodemagicError
    info = Signal(str)
    refresh_req = Signal()


class CodemagicPanel(QWidget):
    """Page de l'admin. Appeler `on_show()` quand l'onglet devient visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG_MAIN};")
        self._bridge = _Bridge()
        self._bridge.builds.connect(self._on_builds)
        self._bridge.started.connect(self._on_started)
        self._bridge.info.connect(lambda t: self._status.setText(t))
        self._bridge.refresh_req.connect(self.refresh)
        self._app_id = None
        self._builds = []
        self._busy = False
        self._visible = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._build_ui()

    # ── Interface ──
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet(f"background:{BG_PANEL}; border-bottom:1px solid #1e1e1e;")
        h = QHBoxLayout(hdr)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(10)
        t = QLabel("Apps tablette")
        t.setFont(QFont("Segoe UI", 12, QFont.Bold))
        t.setStyleSheet(f"color:{TEXT}; background:transparent;")
        h.addWidget(t)
        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px; background:transparent;")
        h.addWidget(self._status, 1)
        self._btn_android = QPushButton("▶  Android")
        self._btn_ios = QPushButton("▶  iOS")
        self._btn_both = QPushButton("▶  Les deux")
        for b, wfs in ((self._btn_android, ["android-play"]), (self._btn_ios, ["ios-appstore"]),
                       (self._btn_both, ["ios-appstore", "android-play"])):
            b.setFixedHeight(28)
            b.setStyleSheet(_BTN_GO)
            b.clicked.connect(lambda _=False, w=wfs: self._launch(w))
            h.addWidget(b)
        self._btn_cancel = QPushButton("■  Annuler")
        self._btn_cancel.setFixedHeight(28)
        self._btn_cancel.setStyleSheet(_BTN)
        self._btn_cancel.setToolTip("Annule le build sélectionné (s'il est en file ou en cours)")
        self._btn_cancel.clicked.connect(self._cancel)
        h.addWidget(self._btn_cancel)
        btn_ref = QPushButton("↺  Actualiser")
        btn_ref.setFixedHeight(28)
        btn_ref.setStyleSheet(_BTN)
        btn_ref.clicked.connect(self.refresh)
        h.addWidget(btn_ref)
        root.addWidget(hdr)

        # Jeton absent : mode d'emploi à la place du tableau.
        self._setup = QFrame()
        self._setup.setStyleSheet(f"background:{BG_MAIN};")
        s = QVBoxLayout(self._setup)
        s.setContentsMargins(40, 30, 40, 30)
        s.setSpacing(12)
        lbl = QLabel(
            "<b>Connecter l'admin à Codemagic (une seule fois)</b><br><br>"
            "1. Sur <b>codemagic.io</b> : menu de votre compte › <b>Account settings › API token › Show</b>, copiez le jeton.<br>"
            "2. Cliquez « Ouvrir le fichier du jeton », collez-le, enregistrez.<br>"
            "3. Cliquez « Vérifier ».<br><br>"
            f"<span style='color:{TEXT_DIM}'>Le jeton reste sur ce PC ({TOKEN_FILE}), jamais dans le dépôt.</span>")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        lbl.setStyleSheet(f"color:{TEXT}; font-size:13px; background:transparent;")
        s.addWidget(lbl)
        row = QHBoxLayout()
        b1 = QPushButton("Ouvrir le fichier du jeton")
        b1.setFixedHeight(32)
        b1.setStyleSheet(_BTN)
        b1.clicked.connect(self._open_token_file)
        b2 = QPushButton("Vérifier")
        b2.setFixedHeight(32)
        b2.setStyleSheet(_BTN_GO)
        b2.clicked.connect(self.refresh)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch()
        s.addLayout(row)
        s.addStretch()
        root.addWidget(self._setup)

        split = QSplitter(Qt.Vertical)
        split.setStyleSheet("QSplitter::handle { background:#1e1e1e; }")
        cols = ["N°", "Plateforme", "Statut", "Étape", "Version", "Commit", "Lancé", "Durée"]
        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self._table.horizontalHeader()
        for c in range(len(cols)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.setStyleSheet(
            f"QTableWidget {{ background:{BG_MAIN}; color:{TEXT}; border:none; gridline-color:#222; font-size:12px; }}"
            f"QHeaderView::section {{ background:{BG_PANEL}; color:{TEXT_DIM}; border:none; padding:6px; }}"
            f"QTableWidget::item:selected {{ background:#0d3a45; }}")
        self._table.itemSelectionChanged.connect(self._show_detail)
        self._table.cellDoubleClicked.connect(lambda r, c: self._open_build(r))
        split.addWidget(self._table)

        det = QWidget()
        d = QVBoxLayout(det)
        d.setContentsMargins(20, 10, 20, 10)
        d.setSpacing(6)
        drow = QHBoxLayout()
        self._det_title = QLabel("Sélectionnez un build")
        self._det_title.setStyleSheet(f"color:{TEXT}; font-weight:bold; background:transparent;")
        drow.addWidget(self._det_title, 1)
        b_open = QPushButton("Ouvrir sur Codemagic ↗")
        b_open.setFixedHeight(26)
        b_open.setStyleSheet(_BTN)
        b_open.clicked.connect(lambda: self._open_build(self._table.currentRow()))
        b_copy = QPushButton("⧉  Copier pour Claude")
        b_copy.setFixedHeight(26)
        b_copy.setStyleSheet(_BTN)
        b_copy.setToolTip("Copie l'état du build (et l'étape en échec) à coller dans Claude")
        b_copy.clicked.connect(self._copy_detail)
        drow.addWidget(b_open)
        drow.addWidget(b_copy)
        d.addLayout(drow)
        self._det = QTextEdit()
        self._det.setReadOnly(True)
        self._det.setStyleSheet(f"QTextEdit {{ background:{BG_PANEL}; color:{TEXT}; border:1px solid #222;"
                                f" font-family:Consolas,monospace; font-size:12px; }}")
        d.addWidget(self._det)
        split.addWidget(det)
        split.setSizes([360, 220])
        self._split = split
        root.addWidget(split, 1)
        self._sync_setup()

    def _sync_setup(self):
        has = bool(read_token())
        self._setup.setVisible(not has)
        self._split.setVisible(has)
        for b in (self._btn_android, self._btn_ios, self._btn_both, self._btn_cancel):
            b.setEnabled(has)

    # ── Cycle de vie ──
    def on_show(self):
        self._visible = True
        self.refresh()

    def _tick(self):
        if self._visible and self.isVisible():
            self.refresh()
        else:
            self._timer.stop()

    def hideEvent(self, e):
        self._visible = False
        super().hideEvent(e)

    def _schedule(self):
        # Rafraîchi souvent tant qu'un build tourne, rarement sinon ; jamais
        # quand l'onglet n'est pas affiché.
        active = any(STATUS.get(b.get("status"), ("", "", False))[2] for b in self._builds)
        if self._visible:
            self._timer.start(15000 if active else 60000)
        else:
            self._timer.stop()

    # ── Actions ──
    def refresh(self):
        self._sync_setup()
        token = read_token()
        if not token or self._busy:
            return
        self._busy = True
        self._status.setText("Lecture de Codemagic…")

        def run():
            try:
                if not self._app_id:
                    self._app_id = find_app_id(token)
                r = _call("GET", f"/builds?appId={self._app_id}", token)
                builds = [b for b in (r.get("builds") or []) if wf(b) in WORKFLOWS]
                self._bridge.builds.emit(builds[:30])
            except CodemagicError as e:
                self._bridge.builds.emit(e)
            except Exception as e:
                self._bridge.builds.emit(CodemagicError(str(e)))
        threading.Thread(target=run, daemon=True, name="codemagic-list").start()

    def _launch(self, workflows):
        token = read_token()
        if not token:
            return
        noms = " puis ".join(WORKFLOWS[w][0] for w in workflows)
        effets = "\n".join("• " + WORKFLOWS[w][0] + " : " + WORKFLOWS[w][1] for w in workflows)
        warn = self._unpushed_warning()
        rep = QMessageBox.question(
            self, "Lancer un build",
            f"Lancer le build {noms} sur « {BRANCH} » (état GitHub) ?\n\n{effets}\n\n"
            "Pensez à monter la version et à mettre à jour mobile/release_notes.json avant."
            + (f"\n\n⚠ {warn}" if warn else ""),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if rep != QMessageBox.Yes:
            return
        self._status.setText("Lancement…")

        def run():
            try:
                if not self._app_id:
                    self._app_id = find_app_id(token)
                for w in workflows:
                    r = _call("POST", "/builds", token, {"appId": self._app_id, "workflowId": w, "branch": BRANCH})
                    self._bridge.started.emit((w, r.get("buildId")))
                    time.sleep(1)
            except CodemagicError as e:
                self._bridge.started.emit(e)
        threading.Thread(target=run, daemon=True, name="codemagic-start").start()

    def _cancel(self):
        b = self._selected()
        if not b or not STATUS.get(b.get("status"), ("", "", False))[2]:
            QMessageBox.information(self, "Annuler", "Sélectionnez un build en file ou en cours.")
            return
        if QMessageBox.question(self, "Annuler", f"Annuler le build n°{b.get('index', '?')} ({WORKFLOWS.get(wf(b), ('?',))[0]}) ?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        token, bid = read_token(), b.get("_id")

        def run():
            try:
                _call("POST", f"/builds/{bid}/cancel", token)
                self._bridge.info.emit("Build annulé.")
            except CodemagicError as e:
                self._bridge.info.emit(str(e))
            time.sleep(2)
            self._bridge.refresh_req.emit()
        threading.Thread(target=run, daemon=True, name="codemagic-cancel").start()

    @staticmethod
    def _unpushed_warning() -> str:
        """Commits de mobile/ pas encore sur GitHub (Codemagic ne les verrait pas)."""
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            out = subprocess.run(["git", "log", "--oneline", "origin/main..HEAD", "--", "mobile", "codemagic.yaml"],
                                 cwd=here, capture_output=True, text=True, timeout=5,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
            dirty = subprocess.run(["git", "status", "--porcelain", "--", "mobile", "codemagic.yaml"],
                                   cwd=here, capture_output=True, text=True, timeout=5,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        except Exception:
            return ""
        msgs = []
        if out:
            msgs.append(f"{len(out.splitlines())} commit(s) de l'app tablette pas encore poussé(s) sur GitHub")
        if dirty:
            msgs.append("des modifications de l'app tablette ne sont pas commitées")
        return " ; ".join(msgs) + (" : elles ne seront PAS dans ce build." if msgs else "")

    # ── Résultats ──
    def _on_started(self, res):
        if isinstance(res, Exception):
            self._status.setText(str(res))
            QMessageBox.warning(self, "Codemagic", str(res))
            return
        w, bid = res
        self._status.setText(f"Build {WORKFLOWS[w][0]} lancé ({bid}).")
        QTimer.singleShot(1500, self.refresh)

    def _on_builds(self, res):
        self._busy = False
        if isinstance(res, Exception):
            self._status.setText(str(res))
            self._schedule()
            return
        sel = (self._selected() or {}).get("_id")
        self._builds = res
        self._fill()
        if sel:
            for r, b in enumerate(self._builds):
                if b.get("_id") == sel:
                    self._table.selectRow(r)
        elif self._builds:
            self._table.selectRow(0)
        n_act = sum(1 for b in res if STATUS.get(b.get("status"), ("", "", False))[2])
        self._status.setText((f"{n_act} build(s) en cours · " if n_act else "")
                             + "mis à jour " + datetime.now().strftime("%H:%M:%S"))
        self._schedule()

    @staticmethod
    def _step(b) -> str:
        """Étape en cours (commencée, pas finie) ; sinon celle qui a échoué."""
        acts = b.get("buildActions") or []
        if STATUS.get(b.get("status"), ("", "", False))[2]:
            for a in acts:
                if a.get("startedAt") and not a.get("finishedAt"):
                    return a.get("name") or ""
        for a in acts:
            if a.get("status") in ("failed", "timeout"):
                return "✗ " + (a.get("name") or "")
        return ""

    @staticmethod
    def _duration(b) -> str:
        t0 = _ts(b.get("startedAt"))
        if not t0:
            return ""
        t1 = _ts(b.get("finishedAt")) or time.time()
        s = int(t1 - t0)
        return f"{s // 60} min {s % 60:02d}"

    def _fill(self):
        self._table.setRowCount(len(self._builds))
        for r, b in enumerate(self._builds):
            lab, col, _ = STATUS.get(b.get("status"), (b.get("status") or "?", TEXT_DIM, False))
            commit = b.get("commit") or {}
            t0 = _ts(b.get("startedAt") or b.get("createdAt"))
            vals = [str(b.get("index", "")), WORKFLOWS.get(wf(b), ("?",))[0], lab, self._step(b),
                    str(b.get("version") or ""),
                    ((commit.get("hash") or "")[:7] + "  " + (commit.get("commitMessage") or "").splitlines()[0][:80]
                     if commit else ""),
                    datetime.fromtimestamp(t0).strftime("%d/%m %H:%M") if t0 else "",
                    self._duration(b)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setForeground(QColor(col))
                    f = it.font(); f.setBold(True); it.setFont(f)
                self._table.setItem(r, c, it)
        self._show_detail()

    def _selected(self):
        r = self._table.currentRow()
        return self._builds[r] if 0 <= r < len(self._builds) else None

    def _detail_text(self, b) -> str:
        lab = STATUS.get(b.get("status"), (b.get("status"), "", False))[0]
        lines = [f"Build n°{b.get('index', '?')} · {wf(b)} · {lab}",
                 f"Branche {b.get('branch', '')} · commit {(b.get('commit') or {}).get('hash', '')[:10]}",
                 f"Durée {self._duration(b)}", ""]
        for a in b.get("buildActions") or []:
            st = a.get("status") or ("en cours" if a.get("startedAt") and not a.get("finishedAt") else "à venir")
            mark = {"success": "✓", "finished": "✓", "failed": "✗", "timeout": "✗", "skipped": "–",
                    "canceled": "–"}.get(st, "…")
            lines.append(f" {mark} {a.get('name', '')}  ({st})")
        if b.get("message"):
            lines += ["", "Message : " + str(b["message"])]
        return "\n".join(lines)

    def _show_detail(self):
        b = self._selected()
        if not b:
            self._det_title.setText("Sélectionnez un build")
            self._det.clear()
            return
        self._det_title.setText(f"Build n°{b.get('index', '?')} — {WORKFLOWS.get(wf(b), ('?',))[0]}")
        self._det.setPlainText(self._detail_text(b))

    def _copy_detail(self):
        b = self._selected()
        if b:
            QApplication.clipboard().setText(f"Build Codemagic {b.get('_id')}\n" + self._detail_text(b))
            self._status.setText("Copié.")

    def _open_build(self, row):
        if 0 <= row < len(self._builds) and self._app_id:
            webbrowser.open(f"https://codemagic.io/app/{self._app_id}/build/{self._builds[row].get('_id')}")

    def _open_token_file(self):
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        if not TOKEN_FILE.exists():
            TOKEN_FILE.write_text("", encoding="utf-8")
        try:
            os.startfile(str(TOKEN_FILE))          # Windows : Bloc-notes
        except Exception:
            webbrowser.open(TOKEN_FILE.as_uri())
