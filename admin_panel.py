"""
Panneau d'administration MyStrow — interface graphique autonome.
Lancer avec : python admin_panel.py
"""

import os
import sys
import json
import secrets
import string
import urllib.request
from datetime import datetime, timezone
import subprocess
import shutil
import time
import zipfile
import webbrowser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QDialog, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QAbstractItemView, QFrame, QMessageBox, QTextEdit,
    QProgressBar, QFileDialog, QSizePolicy, QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QColor

import firebase_client as fc
from core import FIREBASE_PROJECT_ID
import email_sender

try:
    from gdtf_config import GDTF_SYNC_SECRET as _GDTF_SYNC_SECRET
except ImportError:
    _GDTF_SYNC_SECRET = ""


_GDTF_UPLOAD_URL = (
    f"https://us-central1-{FIREBASE_PROJECT_ID}.cloudfunctions.net/gdtf_upload"
)

try:
    from release import (
        get_current_version, bump_version, update_version,
        generate_sig_file, GITHUB_REPO,
        BASE_DIR as _RELEASE_DIR,
        _gh_api as _release_gh_api,
    )
    _RELEASE_OK = True
except Exception:
    _RELEASE_OK = False

# Firebase Admin SDK (suppression compte Auth)
try:
    import firebase_admin
    from firebase_admin import credentials as fa_credentials
    from firebase_admin import auth as fa_auth
    _ADMIN_SDK_AVAILABLE = True
except ImportError:
    _ADMIN_SDK_AVAILABLE = False

# En mode exe frozen, chercher service_account.json à côté de l'exe
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_PATH = os.path.join(_BASE_DIR, "service_account.json")
_fa_app = None


def _init_firebase_admin() -> bool:
    """Initialise le SDK Admin Firebase (une seule fois). Retourne True si OK."""
    global _fa_app
    if _fa_app is not None:
        return True
    if not _ADMIN_SDK_AVAILABLE or not os.path.exists(SERVICE_ACCOUNT_PATH):
        return False
    try:
        try:
            _fa_app = firebase_admin.get_app()
        except ValueError:
            cred   = fa_credentials.Certificate(SERVICE_ACCOUNT_PATH)
            _fa_app = firebase_admin.initialize_app(cred)
        return True
    except Exception as e:
        print(f"[Firebase Admin] ERREUR init : {e}")
        return False


def _delete_auth_user(uid: str) -> bool:
    """Supprime un compte Firebase Auth via le SDK Admin."""
    if not _init_firebase_admin():
        raise Exception(
            f"SDK Admin non disponible.\n"
            f"Chemin : {SERVICE_ACCOUNT_PATH}\n"
            f"Fichier présent : {os.path.exists(SERVICE_ACCOUNT_PATH)}"
        )
    fa_auth.delete_user(uid)
    return True

# ---------------------------------------------------------------
# Constantes / Palette
# ---------------------------------------------------------------

ADMIN_CACHE = os.path.join(os.path.expanduser("~"), ".maestro_admin.json")

_FS_BASE = (
    f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
    f"/databases/(default)/documents"
)

BG_MAIN  = "#1a1a1a"
BG_PANEL = "#111111"
BG_INPUT = "#2a2a2a"
ACCENT   = "#00d4ff"
GREEN    = "#2d7a3a"
ORANGE   = "#c47f17"
RED      = "#a83232"
TEXT     = "#ffffff"
TEXT_DIM = "#aaaaaa"

STYLE_APP = f"""
    QMainWindow, QDialog {{ background: {BG_MAIN}; }}
    QWidget {{ background: {BG_MAIN}; color: {TEXT}; font-family: 'Segoe UI', sans-serif; }}
    QLabel {{ color: {TEXT}; border: none; background: transparent; }}
    QLineEdit {{
        background: {BG_INPUT}; color: {TEXT};
        border: 1px solid #3a3a3a; border-radius: 4px;
        padding: 8px; font-size: 12px;
    }}
    QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox {{
        background: {BG_INPUT}; color: {TEXT};
        border: 1px solid #3a3a3a; border-radius: 4px;
        padding: 6px 8px; font-size: 12px; min-width: 120px;
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background: {BG_INPUT}; color: {TEXT};
        selection-background-color: {ACCENT}; selection-color: #000;
    }}
    QTableWidget {{
        background: {BG_INPUT}; color: {TEXT};
        gridline-color: #333; border: none; font-size: 12px;
        alternate-background-color: #222222;
    }}
    QTableWidget::item {{ padding: 6px; }}
    QTableWidget::item:selected {{ background: #2a4a5a; color: {TEXT}; }}
    QHeaderView::section {{
        background: {BG_PANEL}; color: {TEXT_DIM};
        border: none; border-bottom: 1px solid #333;
        padding: 6px; font-size: 11px; font-weight: bold;
    }}
    QScrollBar:vertical {{
        background: {BG_INPUT}; width: 8px; border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: #444; border-radius: 4px; min-height: 20px;
    }}
    QMessageBox {{ background: {BG_MAIN}; }}
"""

_BTN_PRIMARY = f"""
    QPushButton {{
        background: {ACCENT}; color: #000; border: none;
        border-radius: 4px; font-weight: bold; font-size: 12px; padding: 8px 16px;
    }}
    QPushButton:hover {{ background: #33e0ff; }}
    QPushButton:disabled {{ background: #555; color: #888; }}
"""
_BTN_GREEN = f"""
    QPushButton {{
        background: {GREEN}; color: white; border: none;
        border-radius: 4px; font-weight: bold; font-size: 12px; padding: 8px 16px;
    }}
    QPushButton:hover {{ background: #3a9a4a; }}
    QPushButton:disabled {{ background: #555; color: #888; }}
"""
_BTN_SECONDARY = f"""
    QPushButton {{
        background: {BG_INPUT}; color: {TEXT_DIM}; border: 1px solid #444;
        border-radius: 4px; font-size: 11px; padding: 8px 14px;
    }}
    QPushButton:hover {{ background: #3a3a3a; color: white; }}
    QPushButton:disabled {{ color: #555; }}
"""
_BTN_RED = f"""
    QPushButton {{
        background: {RED}; color: white; border: none;
        border-radius: 4px; font-size: 11px; padding: 5px 10px;
    }}
    QPushButton:hover {{ background: #cc3333; }}
    QPushButton:disabled {{ background: #555; color: #888; }}
"""
_BTN_ORANGE = f"""
    QPushButton {{
        background: {ORANGE}; color: white; border: none;
        border-radius: 4px; font-weight: bold; font-size: 12px; padding: 8px 16px;
    }}
    QPushButton:hover {{ background: #d4901e; }}
    QPushButton:disabled {{ background: #555; color: #888; }}
"""


# ---------------------------------------------------------------
# Helpers (portés depuis create_client.py)
# ---------------------------------------------------------------

def _generate_temp_password(length: int = 20) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(chars) for _ in range(length))


def _fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")


def _expiry_from_months(months: int, base: float = None) -> float:
    if base is None:
        base = datetime.now(timezone.utc).timestamp()
    return base + months * 30 * 86400


def _delete_firestore_doc(path: str, id_token: str) -> bool:
    url = f"{_FS_BASE}/{path}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {id_token}"},
        method="DELETE",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
    return True


def _patch_firestore(path: str, fields: dict, id_token: str, mask: list = None):
    url = f"{_FS_BASE}/{path}"
    if mask:
        url += "?" + "&".join(f"updateMask.fieldPaths={f}" for f in mask)
    payload = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {id_token}",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _query_all_licenses(id_token: str) -> list:
    url = f"{_FS_BASE}/licenses"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {id_token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    docs = data.get("documents", [])
    results = []
    for doc in docs:
        uid = doc["name"].split("/")[-1]
        fields = {k: fc._from_firestore(v) for k, v in doc.get("fields", {}).items()}
        fields["_uid"] = uid
        results.append(fields)
    return results


def _query_all_fixtures(id_token: str) -> list:
    """Charge tous les documents de la collection 'fixtures' dans Firestore."""
    results = []
    page_token = None
    while True:
        url = f"{_FS_BASE}/gdtf_fixtures?pageSize=300"
        if page_token:
            url += f"&pageToken={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {id_token}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        docs = data.get("documents", [])
        for doc in docs:
            doc_id = doc["name"].split("/")[-1]
            fields = {k: fc._from_firestore(v) for k, v in doc.get("fields", {}).items()}
            fields["_doc_id"] = doc_id
            results.append(fields)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return results


def _delete_fixture_doc(doc_id: str, id_token: str) -> bool:
    return _delete_firestore_doc(f"gdtf_fixtures/{doc_id}", id_token)


def _fetch_license_doc(uid: str, id_token: str) -> dict:
    url = f"{_FS_BASE}/licenses/{uid}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {id_token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        doc = json.loads(resp.read().decode())
    fields = {k: fc._from_firestore(v) for k, v in doc.get("fields", {}).items()}
    fields["_uid"] = uid
    return fields


# ---------------------------------------------------------------
# Cache admin
# ---------------------------------------------------------------

def _load_admin_cache() -> dict:
    if os.path.exists(ADMIN_CACHE):
        try:
            with open(ADMIN_CACHE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_admin_cache(email: str, refresh_token: str):
    try:
        with open(ADMIN_CACHE, "w") as f:
            json.dump({"email": email, "refresh_token": refresh_token}, f)
    except Exception:
        pass


def _clear_admin_cache():
    try:
        os.remove(ADMIN_CACHE)
    except Exception:
        pass


# ---------------------------------------------------------------
# Worker thread générique
# ---------------------------------------------------------------

class _Worker(QObject):
    success = Signal(object)
    error   = Signal(str)

    def __init__(self, fn, args, kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.success.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


def _run_async(parent, fn, *args, on_success=None, on_error=None, **kwargs):
    """Lance fn(*args) dans un QThread séparé pour ne pas bloquer l'UI."""
    thread = QThread()  # Pas de parent Qt — évite le warning cross-thread
    worker = _Worker(fn, args, kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    if on_success:
        worker.success.connect(on_success)
    if on_error:
        worker.error.connect(on_error)
    worker.success.connect(thread.quit)
    worker.error.connect(thread.quit)
    if not hasattr(parent, "_async_threads"):
        parent._async_threads = []
    parent._async_threads.append((thread, worker))
    thread.finished.connect(lambda: _gc_thread(parent, thread))
    thread.start()


def _gc_thread(parent, thread):
    if hasattr(parent, "_async_threads"):
        parent._async_threads = [(t, w) for t, w in parent._async_threads if t is not thread]


# ---------------------------------------------------------------
# LoginDialog
# ---------------------------------------------------------------

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MyStrow Admin — Connexion")
        self.setFixedSize(360, 290)
        self.id_token      = None
        self.refresh_token = None
        self.email         = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.setSpacing(14)

        title = QLabel("MyStrow — Admin")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT};")
        lay.addWidget(title)

        sub = QLabel("Connexion administrateur")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        lay.addWidget(sub)
        lay.addSpacing(4)

        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("Email admin")
        self.email_edit.setMinimumHeight(38)
        lay.addWidget(self.email_edit)

        self.pwd_edit = QLineEdit()
        self.pwd_edit.setPlaceholderText("Mot de passe")
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.pwd_edit.setMinimumHeight(38)
        self.pwd_edit.returnPressed.connect(self._on_login)
        lay.addWidget(self.pwd_edit)

        self.err_label = QLabel("")
        self.err_label.setStyleSheet(f"color: {RED}; font-size: 11px;")
        self.err_label.setAlignment(Qt.AlignCenter)
        self.err_label.setWordWrap(True)
        self.err_label.setMinimumHeight(16)
        lay.addWidget(self.err_label)

        self.btn_login = QPushButton("Se connecter")
        self.btn_login.setMinimumHeight(40)
        self.btn_login.setStyleSheet(_BTN_PRIMARY)
        self.btn_login.clicked.connect(self._on_login)
        lay.addWidget(self.btn_login)

        self.btn_forgot = QPushButton("Mot de passe oublié ?")
        self.btn_forgot.setFlat(True)
        self.btn_forgot.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; border: none; background: transparent;")
        self.btn_forgot.setCursor(Qt.PointingHandCursor)
        self.btn_forgot.clicked.connect(self._on_forgot)
        lay.addWidget(self.btn_forgot, alignment=Qt.AlignCenter)

    def _on_forgot(self):
        email = self.email_edit.text().strip()
        if not email:
            self.err_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            self.err_label.setText("Entrez votre email ci-dessus puis cliquez à nouveau.")
            return
        self.btn_forgot.setEnabled(False)
        self.err_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self.err_label.setText("Envoi en cours…")
        _run_async(
            self, fc.send_password_reset, email,
            on_success=lambda _: self._on_reset_sent(email),
            on_error=self._on_reset_err,
        )

    def _on_reset_sent(self, email: str):
        self.btn_forgot.setEnabled(True)
        self.err_label.setStyleSheet(f"color: #4CAF50; font-size: 11px;")
        self.err_label.setText(f"Email de réinitialisation envoyé à {email}")

    def _on_reset_err(self, msg: str):
        self.btn_forgot.setEnabled(True)
        self.err_label.setStyleSheet(f"color: {RED}; font-size: 11px;")
        self.err_label.setText(msg)

    def _on_login(self):
        email = self.email_edit.text().strip()
        pwd   = self.pwd_edit.text()
        if not email or not pwd:
            self.err_label.setText("Veuillez remplir tous les champs.")
            return
        self.btn_login.setEnabled(False)
        self.btn_login.setText("Connexion…")
        self.err_label.setText("")
        _run_async(
            self, fc.sign_in, email, pwd,
            on_success=self._on_ok,
            on_error=self._on_err,
        )

    def _on_ok(self, auth):
        _save_admin_cache(auth["email"], auth["refresh_token"])
        self.id_token      = auth["id_token"]
        self.refresh_token = auth["refresh_token"]
        self.email         = auth["email"]
        self.accept()

    def _on_err(self, msg):
        self.err_label.setStyleSheet(f"color: {RED}; font-size: 11px;")
        self.err_label.setText(msg)
        self.btn_login.setEnabled(True)
        self.btn_login.setText("Se connecter")


# ---------------------------------------------------------------
# CreateClientDialog
# ---------------------------------------------------------------

class CreateClientDialog(QDialog):
    client_created = Signal()

    def __init__(self, id_token: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau client")
        self.setFixedSize(420, 310)
        self._id_token = id_token
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(14)

        title = QLabel("Créer un nouveau client")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lay.addWidget(title)

        lay.addWidget(QLabel("Email du client :"))
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("client@example.com")
        self.email_edit.setMinimumHeight(36)
        self.email_edit.textChanged.connect(self._update_summary)
        lay.addWidget(self.email_edit)

        dur_lay = QHBoxLayout()
        dur_lay.addWidget(QLabel("Durée de la licence :"))
        self.months_combo = QComboBox()
        for months, label in [(1, "1 mois"), (3, "3 mois"), (6, "6 mois (défaut)"), (12, "12 mois")]:
            self.months_combo.addItem(label, months)
        self.months_combo.setCurrentIndex(2)
        self.months_combo.currentIndexChanged.connect(self._update_summary)
        dur_lay.addWidget(self.months_combo)
        lay.addLayout(dur_lay)

        self.summary_lbl = QLabel("")
        self.summary_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self.summary_lbl.setWordWrap(True)
        lay.addWidget(self.summary_lbl)
        self._update_summary()

        self.err_label = QLabel("")
        self.err_label.setStyleSheet(f"color: {RED}; font-size: 11px;")
        self.err_label.setWordWrap(True)
        self.err_label.setMinimumHeight(16)
        lay.addWidget(self.err_label)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.setStyleSheet(_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Créer le client")
        self.btn_ok.setStyleSheet(_BTN_PRIMARY)
        self.btn_ok.clicked.connect(self._on_create)
        btns.addWidget(btn_cancel)
        btns.addWidget(self.btn_ok)
        lay.addLayout(btns)

    def _update_summary(self):
        months = self.months_combo.currentData()
        expiry = _expiry_from_months(months)
        self.summary_lbl.setText(
            f"Licence {months} mois — expire le {_fmt_date(expiry)}\n"
            "Un email de définition de mot de passe sera envoyé automatiquement."
        )

    def _on_create(self):
        email  = self.email_edit.text().strip()
        months = self.months_combo.currentData()
        if not email or "@" not in email:
            self.err_label.setText("Adresse email invalide.")
            return
        self.btn_ok.setEnabled(False)
        self.btn_ok.setText("Création en cours…")
        self.err_label.setText("")
        _run_async(
            self, self._do_create, email, months,
            on_success=self._on_ok,
            on_error=self._on_err,
        )

    def _do_create(self, email: str, months: int) -> str:
        expiry   = _expiry_from_months(months)
        temp_pwd = _generate_temp_password()
        auth     = fc.sign_up(email, temp_pwd)
        uid      = auth["uid"]
        fields   = {k: fc._to_firestore(v) for k, v in {
            "email":       email,
            "plan":        "license",
            "expiry_utc":  expiry,
            "created_utc": datetime.now(timezone.utc).timestamp(),
            "machines":    [],
        }.items()}
        _patch_firestore(f"licenses/{uid}", fields, self._id_token)  # token admin
        email_sender.send_welcome(email, expiry, temp_pwd)
        return email

    def _on_ok(self, email: str):
        self.client_created.emit()
        QMessageBox.information(
            self, "Client créé",
            f"Compte créé pour {email}.\n"
            "Un email de définition de mot de passe a été envoyé."
        )
        self.accept()

    def _on_err(self, msg: str):
        self.err_label.setText(msg)
        self.btn_ok.setEnabled(True)
        self.btn_ok.setText("Créer le client")


# ---------------------------------------------------------------
# RenewDialog
# ---------------------------------------------------------------

class RenewDialog(QDialog):
    renewed = Signal()

    def __init__(self, client: dict, id_token: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Renouveler la licence")
        self.setFixedSize(420, 280)
        self._client   = client
        self._id_token = id_token
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(14)

        title = QLabel("Renouveler la licence")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lay.addWidget(title)

        email       = self._client.get("email", "?")
        current_exp = self._client.get("expiry_utc", 0)
        now         = datetime.now(timezone.utc).timestamp()
        if current_exp > now:
            days_left = int((current_exp - now) / 86400)
            exp_str   = f"{_fmt_date(current_exp)} ({days_left}j restants)"
        else:
            exp_str   = f"{_fmt_date(current_exp)} (EXPIRÉ)"

        info = QLabel(f"Client : <b>{email}</b><br>Expiration actuelle : {exp_str}")
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet(f"color: {TEXT_DIM};")
        lay.addWidget(info)

        dur_lay = QHBoxLayout()
        dur_lay.addWidget(QLabel("Prolonger de :"))
        self.months_combo = QComboBox()
        for months, label in [(1, "1 mois"), (3, "3 mois"), (6, "6 mois"), (12, "12 mois")]:
            self.months_combo.addItem(label, months)
        self.months_combo.setCurrentIndex(2)
        self.months_combo.currentIndexChanged.connect(self._update_summary)
        dur_lay.addWidget(self.months_combo)
        dur_lay.addStretch()
        lay.addLayout(dur_lay)

        self.summary_lbl = QLabel("")
        self.summary_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        lay.addWidget(self.summary_lbl)
        self._update_summary()

        self.err_label = QLabel("")
        self.err_label.setStyleSheet(f"color: {RED}; font-size: 11px;")
        self.err_label.setMinimumHeight(16)
        lay.addWidget(self.err_label)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.setStyleSheet(_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Renouveler")
        self.btn_ok.setStyleSheet(_BTN_GREEN)
        self.btn_ok.clicked.connect(self._on_renew)
        btns.addWidget(btn_cancel)
        btns.addWidget(self.btn_ok)
        lay.addLayout(btns)

    def _update_summary(self):
        months      = self.months_combo.currentData()
        current_exp = self._client.get("expiry_utc", 0)
        now         = datetime.now(timezone.utc).timestamp()
        base        = max(current_exp, now)
        new_expiry  = _expiry_from_months(months, base)
        self.summary_lbl.setText(f"Nouvelle expiration : {_fmt_date(new_expiry)}")

    def _on_renew(self):
        months = self.months_combo.currentData()
        self.btn_ok.setEnabled(False)
        self.btn_ok.setText("Renouvellement…")
        self.err_label.setText("")
        _run_async(
            self, self._do_renew, months,
            on_success=self._on_ok,
            on_error=self._on_err,
        )

    def _do_renew(self, months: int) -> float:
        uid         = self._client["_uid"]
        current_exp = self._client.get("expiry_utc", 0)
        now         = datetime.now(timezone.utc).timestamp()
        base        = max(current_exp, now)
        expiry      = _expiry_from_months(months, base)
        fields = {
            "plan":       fc._to_firestore("license"),
            "expiry_utc": fc._to_firestore(expiry),
        }
        _patch_firestore(
            f"licenses/{uid}", fields, self._id_token,
            mask=["plan", "expiry_utc"],
        )
        return expiry

    def _on_ok(self, expiry: float):
        self.renewed.emit()
        try:
            email_sender.send_renewal(self._client.get("email", ""), expiry)
        except Exception:
            pass
        QMessageBox.information(
            self, "Renouvellement effectué",
            f"Licence renouvelée jusqu'au {_fmt_date(expiry)}."
        )
        self.accept()

    def _on_err(self, msg: str):
        self.err_label.setText(msg)
        self.btn_ok.setEnabled(True)
        self.btn_ok.setText("Renouveler")


# ---------------------------------------------------------------
# MachinesDialog
# ---------------------------------------------------------------

class MachinesDialog(QDialog):
    revoked = Signal()

    def __init__(self, client: dict, id_token: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Machines enregistrées")
        self.setFixedSize(500, 300)
        self._client   = client
        self._id_token = id_token
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)

        email = self._client.get("email", "?")
        title = QLabel(f"Machines — {email}")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lay.addWidget(title)

        self.err_label = QLabel("")
        self.err_label.setStyleSheet(f"color: {RED}; font-size: 11px;")
        self.err_label.setMinimumHeight(16)
        lay.addWidget(self.err_label)

        self.machines_container = QWidget()
        self.machines_lay = QVBoxLayout(self.machines_container)
        self.machines_lay.setContentsMargins(0, 0, 0, 0)
        self.machines_lay.setSpacing(8)
        lay.addWidget(self.machines_container)

        lay.addStretch()

        btn_close = QPushButton("Fermer")
        btn_close.setStyleSheet(_BTN_SECONDARY)
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close, alignment=Qt.AlignRight)

        self._populate_machines()

    def _populate_machines(self):
        # Clear existing widgets
        while self.machines_lay.count():
            item = self.machines_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            else:
                # Layout item — clean up sub-widgets
                pass

        machines = self._client.get("machines", [])
        if not machines:
            no_mach = QLabel("Aucune machine enregistrée.")
            no_mach.setStyleSheet(f"color: {TEXT_DIM};")
            self.machines_lay.addWidget(no_mach)
            return

        for m in machines:
            if not isinstance(m, dict):
                continue
            mid      = m.get("id", "?")
            act_at   = m.get("activated_at", 0)
            act_str  = _fmt_date(act_at) if act_at else "?"
            short_id = mid[:8] + "…"

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            lbl = QLabel(f"<b>{short_id}</b>&nbsp;&nbsp;—&nbsp;&nbsp;activée le {act_str}")
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet(f"color: {TEXT_DIM};")
            row_layout.addWidget(lbl)
            row_layout.addStretch()

            btn_rev = QPushButton("Révoquer")
            btn_rev.setStyleSheet(_BTN_RED)
            btn_rev.setFixedWidth(90)
            btn_rev.clicked.connect(lambda checked, machine_id=mid: self._on_revoke(machine_id))
            row_layout.addWidget(btn_rev)

            self.machines_lay.addWidget(row_widget)

    def _on_revoke(self, machine_id: str):
        reply = QMessageBox.question(
            self, "Confirmer la révocation",
            f"Révoquer la machine {machine_id[:8]}… ?\n\n"
            "L'utilisateur devra se reconnecter sur cet appareil.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.err_label.setText("")
        _run_async(
            self, fc.remove_machine,
            self._client["_uid"], self._id_token, machine_id,
            on_success=lambda _: self._after_revoke(),
            on_error=self._on_revoke_err,
        )

    def _after_revoke(self):
        self.revoked.emit()
        _run_async(
            self, _fetch_license_doc,
            self._client["_uid"], self._id_token,
            on_success=self._on_client_refreshed,
            on_error=lambda e: self.err_label.setText(f"Rafraîchissement impossible : {e}"),
        )

    def _on_client_refreshed(self, updated_client: dict):
        self._client = updated_client
        self._populate_machines()

    def _on_revoke_err(self, msg: str):
        self.err_label.setText(f"Erreur : {msg}")


# ---------------------------------------------------------------
# OflSyncWorker + OflSyncDialog
# ---------------------------------------------------------------

_OFL_ZIP_URL = (
    "https://github.com/OpenLightingProject/open-fixture-library"
    "/archive/refs/heads/master.zip"
)
_OFL_BATCH = 50


class OflSyncWorker(QObject):
    """
    Télécharge le ZIP GitHub d'Open Fixture Library (~50 Mo),
    parse toutes les fixtures JSON via ofl_parser, uploade par lots
    via la CF gdtf_upload. Tourne dans un QThread séparé.
    """
    progress = Signal(int, int, str)   # (done, total, message)
    finished = Signal(dict)
    error    = Signal(str)

    def __init__(self):
        super().__init__()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            result = self._do_sync()
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))

    def _do_sync(self) -> dict:
        import io as _io
        import zipfile as _zf
        import ofl_parser

        # ── 0. Vérifier que le secret est configuré ────────────────────────
        if not _GDTF_SYNC_SECRET:
            raise Exception(
                "GDTF_SYNC_SECRET manquant.\n\n"
                "Créez le fichier gdtf_config.py à côté de admin_panel.py :\n"
                "  GDTF_SYNC_SECRET = 'votre_secret'\n\n"
                "Ce secret doit correspondre à la variable Firebase :\n"
                "  firebase functions:secrets:set GDTF_SYNC_SECRET"
            )

        # ── 1. Téléchargement du ZIP OFL (~50 Mo) ─────────────────────────
        self.progress.emit(0, 0, "Téléchargement du ZIP Open Fixture Library…")
        req = urllib.request.Request(
            _OFL_ZIP_URL,
            headers={"User-Agent": "MyStrow-Admin/1.0"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            zip_bytes = resp.read()
        self.progress.emit(0, 0, f"ZIP téléchargé ({len(zip_bytes) // 1024} Ko) — extraction…")

        zf = _zf.ZipFile(_io.BytesIO(zip_bytes))

        # ── 2. Lire manufacturers.json ─────────────────────────────────────
        mfr_names: dict = {}
        for name in zf.namelist():
            if name.endswith("fixtures/manufacturers.json"):
                raw_mfr = json.loads(zf.read(name).decode("utf-8"))
                # {"robe": {"name": "Robe", ...}, ...}
                for key, val in raw_mfr.items():
                    if isinstance(val, dict):
                        mfr_names[key] = val.get("name", key)
                break

        # ── 3. Collecter tous les fichiers fixture JSON ────────────────────
        fixture_entries = []
        for member in zf.namelist():
            # open-fixture-library-master/fixtures/{mfr}/{fixture}.json
            parts = member.replace("\\", "/").split("/")
            if (len(parts) == 4
                    and parts[1] == "fixtures"
                    and not parts[2].startswith("$")
                    and member.endswith(".json")
                    and parts[3] != ""):
                fixture_entries.append((parts[2], parts[3][:-5], member))

        total = len(fixture_entries)
        self.progress.emit(0, total, f"{total} fixtures trouvées — parsing…")

        done   = 0
        errors = []
        upload_batch = []

        def _flush_batch():
            if not upload_batch:
                return
            payload = json.dumps({"fixtures": upload_batch}).encode("utf-8")
            r_req = urllib.request.Request(
                _GDTF_UPLOAD_URL,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Sync-Secret": _GDTF_SYNC_SECRET,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(r_req, timeout=120) as r_resp:
                    r = json.loads(r_resp.read().decode())
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")
                    err_data = json.loads(body)
                    body = err_data.get("error", body)
                except Exception:
                    pass
                if e.code == 403:
                    raise Exception(
                        f"Accès refusé (403) — {body or 'Secret invalide ou non configuré'}\n\n"
                        f"Vérifiez que GDTF_SYNC_SECRET est identique dans gdtf_config.py "
                        f"et dans Firebase (firebase functions:secrets:set GDTF_SYNC_SECRET)."
                    )
                raise Exception(f"HTTP {e.code} — {body or e.reason}")
            if not r.get("ok"):
                raise Exception(r.get("error", "Upload batch échoué"))
            upload_batch.clear()

        for mfr_key, fix_key, member in fixture_entries:
            if self._stop:
                break
            try:
                raw = zf.read(member)
                mfr_name = mfr_names.get(mfr_key, mfr_key)
                parsed = ofl_parser.parse_ofl_json(raw, mfr_key, fix_key, mfr_name)
                upload_batch.append(parsed)
                done += 1
                self.progress.emit(done, total, f"✅ {mfr_name} — {parsed['name']}")
                if len(upload_batch) >= _OFL_BATCH:
                    _flush_batch()
            except Exception as exc:
                err_msg = f"{mfr_key}/{fix_key}: {exc}"
                errors.append(err_msg)
                self.progress.emit(done, total, f"⚠ {err_msg}")

        if not self._stop:
            try:
                _flush_batch()
            except Exception as exc:
                errors.append(f"Erreur upload final : {exc}")

        return {"done": done, "total": total, "stopped": self._stop, "errors": errors}


class OflSyncDialog(QDialog):
    """
    Télécharge le ZIP GitHub OFL, parse toutes les fixtures et
    uploade les profils complets dans Firestore via gdtf_upload CF.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Open Fixture Library — Sync Firestore")
        self.setMinimumSize(640, 520)
        self._thread = None
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        title = QLabel("Sync Open Fixture Library → Firestore")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT};")
        lay.addWidget(title)

        sub = QLabel(
            "Télécharge le ZIP GitHub d'Open Fixture Library (~50 Mo), parse ~5 000 fixtures "
            "JSON et uploade les profils complets dans Firestore. "
            "Durée estimée : 5–15 minutes selon la connexion."
        )
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet(
            f"QProgressBar {{ border:none; background:#2a2a2a; border-radius:3px; }}"
            f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:3px; }}"
        )
        lay.addWidget(self.progress)

        self.status_lbl = QLabel("Prêt.")
        self.status_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        lay.addWidget(self.status_lbl)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setStyleSheet(
            f"background: {BG_PANEL}; color: {TEXT_DIM}; border: 1px solid #2a2a2a; border-radius:4px;"
        )
        lay.addWidget(self.log)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_start = QPushButton("▶  Lancer la sync OFL")
        self.btn_start.setStyleSheet(_BTN_PRIMARY)
        self.btn_start.setFixedHeight(34)
        self.btn_start.clicked.connect(self._start)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹  Arrêter")
        self.btn_stop.setStyleSheet(_BTN_SECONDARY)
        self.btn_stop.setFixedHeight(34)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        btn_row.addWidget(self.btn_stop)

        btn_row.addStretch()

        btn_close = QPushButton("Fermer")
        btn_close.setStyleSheet(_BTN_SECONDARY)
        btn_close.setFixedHeight(34)
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)

        lay.addLayout(btn_row)

    def _append_log(self, msg: str, color: str = None):
        if color:
            self.log.append(f'<span style="color:{color};">{msg}</span>')
        else:
            self.log.append(msg)

    def _start(self):
        if not _GDTF_SYNC_SECRET:
            self._append_log("❌ GDTF_SYNC_SECRET non configuré (gdtf_config.py).", RED)
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.status_lbl.setText("Démarrage…")
        self._append_log("▶ Démarrage de la sync OFL…")

        self._worker = OflSyncWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _stop(self):
        if self._worker:
            self._worker.stop()
        self.btn_stop.setEnabled(False)
        self._append_log("⏸ Arrêt demandé…", "#e67e22")

    def _on_progress(self, done: int, total: int, msg: str):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.status_lbl.setText(f"{done} / {total}" if total > 0 else msg[:60])
        color = RED if "⚠" in msg else "#2ecc71" if "✅" in msg else TEXT_DIM
        self._append_log(msg, color)

    def _on_done(self, result: dict):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        done    = result["done"]
        total   = result["total"]
        errors  = result["errors"]
        stopped = result.get("stopped", False)
        label   = "Interrompu" if stopped else "Terminé"
        self.status_lbl.setText(f"{label} — {done}/{total} fixtures uploadées")
        self._append_log(
            f"{'⏸' if stopped else '✅'} {label} — {done}/{total} fixtures uploadées",
            "#e67e22" if stopped else "#2ecc71",
        )
        if errors:
            self._append_log(f"⚠ {len(errors)} erreur(s) :", "#e67e22")
            for e in errors[:20]:
                self._append_log(f"  {e}", "#e67e22")

    def _on_error(self, msg: str):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        self.status_lbl.setText("Erreur.")
        self._append_log(f"❌ Erreur : {msg}", RED)


# GdtfSyncDialog
# ---------------------------------------------------------------

class GdtfUploadDialog(QDialog):
    """
    Dialog d'import de fichiers .gdtf / .mystrow vers Firestore.
    Parse les fichiers localement puis les envoie via la CF gdtf_upload.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importer fixtures vers Firestore")
        self.setMinimumSize(680, 500)
        self._parsed: list = []   # liste de dicts fixture parsés
        self._thread = None
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        title = QLabel("Importer fixtures vers Firestore")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT};")
        lay.addWidget(title)

        sub = QLabel(
            "Formats acceptés : .xml (GrandMA2/3) · .mystrow — "
            "parsés localement puis uploadés dans Firestore avec profil complet."
        )
        sub.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # Boutons choisir fichiers / dossier
        pick_row = QHBoxLayout()
        pick_row.setSpacing(6)

        btn_pick = QPushButton("📂  Fichiers…")
        btn_pick.setStyleSheet(_BTN_PRIMARY)
        btn_pick.setFixedHeight(32)
        btn_pick.setToolTip("Sélectionner des fichiers .xml / .mystrow")
        btn_pick.clicked.connect(self._on_pick_files)
        pick_row.addWidget(btn_pick)

        btn_folder = QPushButton("📁  Dossier…")
        btn_folder.setStyleSheet(_BTN_SECONDARY)
        btn_folder.setFixedHeight(32)
        btn_folder.setToolTip("Charger tous les .xml / .mystrow d'un dossier")
        btn_folder.clicked.connect(self._on_pick_folder)
        pick_row.addWidget(btn_folder)

        self.lbl_count = QLabel("Aucun fichier sélectionné")
        self.lbl_count.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        pick_row.addWidget(self.lbl_count)
        pick_row.addStretch()

        btn_clear = QPushButton("✕  Vider")
        btn_clear.setStyleSheet(_BTN_SECONDARY)
        btn_clear.setFixedHeight(28)
        btn_clear.clicked.connect(self._on_clear)
        pick_row.addWidget(btn_clear)
        lay.addLayout(pick_row)

        # Table des fixtures parsées
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Statut", "Nom", "Fabricant", "Modes"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(160)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMaximumHeight(120)
        self.log.setStyleSheet(
            f"background: {BG_PANEL}; color: {TEXT_DIM}; border: 1px solid #2a2a2a; border-radius:4px;"
        )
        lay.addWidget(self.log)

        # Progress + status
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.setStyleSheet(
            f"QProgressBar {{ border:none; background:#2a2a2a; border-radius:2px; }}"
            f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:2px; }}"
        )
        lay.addWidget(self.progress)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        lay.addWidget(self.status_lbl)

        # Boutons bas
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_upload = QPushButton("📤  Uploader vers Firestore")
        self.btn_upload.setStyleSheet(_BTN_PRIMARY)
        self.btn_upload.setFixedHeight(34)
        self.btn_upload.setEnabled(False)
        self.btn_upload.clicked.connect(self._on_upload)
        btn_row.addWidget(self.btn_upload)

        btn_row.addStretch()

        btn_close = QPushButton("Fermer")
        btn_close.setStyleSheet(_BTN_SECONDARY)
        btn_close.setFixedHeight(34)
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

    # ------------------------------------------------------------------

    def _append_log(self, msg: str, color: str = None):
        if color:
            self.log.append(f'<span style="color:{color};">{msg}</span>')
        else:
            self.log.append(msg)

    def _set_busy(self, busy: bool):
        self.btn_upload.setEnabled(not busy and bool(self._parsed))
        self.progress.setVisible(busy)

    def _on_clear(self):
        self._parsed.clear()
        self.table.setRowCount(0)
        self.lbl_count.setText("Aucun fichier sélectionné")
        self.btn_upload.setEnabled(False)
        self.log.clear()

    _FIXTURE_EXTS = {".mystrow", ".xml"}

    def _on_pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choisir des fichiers fixture", "",
            "Fixtures (*.xml *.mystrow);;Tous les fichiers (*)"
        )
        if paths:
            self._process_paths(paths)

    def _on_pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier de fixtures")
        if not folder:
            return
        paths = []
        for root, _dirs, files in os.walk(folder):
            for fname in sorted(files):
                if os.path.splitext(fname)[1].lower() in self._FIXTURE_EXTS:
                    paths.append(os.path.join(root, fname))
        if not paths:
            self._append_log(f"⚠ Aucun fichier .xml / .mystrow trouvé dans {folder}", "#e67e22")
            return
        self._append_log(f"📁 {len(paths)} fichier(s) trouvé(s) dans {folder}")
        self._process_paths(paths)

    def _process_paths(self, paths: list):
        from fixture_parser import parse_file
        ok = 0
        for path in paths:
            fname = os.path.basename(path)
            try:
                fx = parse_file(path)
                fx["_source_file"] = fname
                self._parsed.append(fx)
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem("✅"))
                self.table.item(row, 0).setForeground(QColor("#2ecc71"))
                self.table.setItem(row, 1, QTableWidgetItem(fx.get("name", "")))
                self.table.setItem(row, 2, QTableWidgetItem(fx.get("manufacturer", "")))
                modes_info = ", ".join(
                    f"{m['name']} ({m.get('channelCount', 0)}ch)"
                    for m in fx.get("modes", [])
                )
                self.table.setItem(row, 3, QTableWidgetItem(modes_info))
                self._append_log(
                    f"✅ {fname}  →  {fx.get('name')} "
                    f"[{fx.get('source','?').upper()}]  "
                    f"({len(fx.get('modes', []))} mode(s))",
                    "#2ecc71",
                )
                ok += 1
            except Exception as e:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem("❌"))
                self.table.item(row, 0).setForeground(QColor(RED))
                self.table.setItem(row, 1, QTableWidgetItem(fname))
                self.table.setItem(row, 2, QTableWidgetItem(""))
                self.table.setItem(row, 3, QTableWidgetItem(str(e)))
                self._append_log(f"❌ {fname}  :  {e}", RED)

        total = len(self._parsed)
        self.lbl_count.setText(
            f"{total} fixture{'s' if total > 1 else ''} "
            f"({ok}/{len(paths)} parsée{'s' if ok > 1 else ''})"
        )
        self.btn_upload.setEnabled(total > 0)

    def _on_upload(self):
        if not self._parsed:
            return
        if not _GDTF_SYNC_SECRET:
            self._append_log("❌ GDTF_SYNC_SECRET non configuré (gdtf_config.py manquant).", RED)
            return

        n = len(self._parsed)
        self._append_log(f"▶ Upload de {n} fixture(s) vers Firestore…")
        self._set_busy(True)
        self.status_lbl.setText("Upload en cours…")
        self.progress.setRange(0, 0)

        _run_async(
            self,
            self._do_upload,
            on_success=self._on_upload_ok,
            on_error=self._on_upload_err,
        )

    def _do_upload(self) -> dict:
        # Nettoyer les clés internes avant envoi
        fixtures_to_send = []
        for fx in self._parsed:
            clean = {k: v for k, v in fx.items() if not k.startswith("_")}
            fixtures_to_send.append(clean)

        payload = json.dumps({"fixtures": fixtures_to_send}).encode("utf-8")
        req = urllib.request.Request(
            _GDTF_UPLOAD_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Sync-Secret": _GDTF_SYNC_SECRET,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()
            except Exception:
                pass
            raise Exception(f"HTTP {e.code}: {body or str(e)}")

    def _on_upload_ok(self, result: dict):
        self._set_busy(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        written = result.get("written", 0)
        errors  = result.get("errors", [])
        ver     = result.get("newVersion", "?")
        self.status_lbl.setText(f"{written} fixture(s) écrite(s) — v{ver}")
        self._append_log(
            f"✅ Upload OK — {written} fixture(s) dans Firestore (v{ver})"
            + (f" | {len(errors)} erreur(s)" if errors else ""),
            "#2ecc71",
        )
        for err in errors:
            self._append_log(f"  ⚠ {err}", "#e67e22")

    def _on_upload_err(self, msg: str):
        self._set_busy(False)
        self.status_lbl.setText("Erreur upload.")
        self._append_log(f"❌ Erreur : {msg}", RED)


def _do_upload_fixture_async(fixture_data: dict, id_token: str):
    """Upload d'une fixture vers Firestore via gdtf_upload (appelé dans un QThread)."""
    payload = json.dumps({"fixtures": [fixture_data]}).encode("utf-8")
    req = urllib.request.Request(
        _GDTF_UPLOAD_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Sync-Secret": _GDTF_SYNC_SECRET,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            r = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = json.loads(e.read().decode()).get("error", "")
        except Exception:
            pass
        raise Exception(f"HTTP {e.code} — {body or e.reason}")
    if not r.get("ok"):
        raise Exception(r.get("error", "Upload échoué"))


# ---------------------------------------------------------------
# FixtureEditDialog — formulaire ajout / édition d'une fixture
# ---------------------------------------------------------------

class _FixtureEditDialog(QDialog):
    """Formulaire simple pour créer ou modifier une fixture."""

    def __init__(self, parent=None, fixture: dict = None):
        super().__init__(parent)
        self._fixture = fixture or {}
        self._is_new  = not bool(fixture)
        self.setWindowTitle("Nouvelle fixture" if self._is_new else "Modifier la fixture")
        self.setMinimumWidth(560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(12)

        title = QLabel("Nouvelle fixture" if self._is_new else "Modifier la fixture")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT};")
        lay.addWidget(title)

        form_grid = QHBoxLayout()
        col1 = QVBoxLayout(); col1.setSpacing(6)
        col2 = QVBoxLayout(); col2.setSpacing(6)

        def _field(label, key, placeholder=""):
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
            edit = QLineEdit(str(self._fixture.get(key, "")))
            edit.setPlaceholderText(placeholder)
            edit.setFixedHeight(32)
            return lbl, edit

        lbl_name, self._e_name = _field("Nom *", "name", "ex : Par 64 LED RGB")
        lbl_mfr,  self._e_mfr  = _field("Fabricant *", "manufacturer", "ex : Eurolite")
        lbl_type, self._e_type = _field("Type", "fixture_type", "ex : LED")
        lbl_src,  self._e_src  = _field("Source", "source", "ex : OFL")

        lbl_uuid, self._e_uuid = _field("UUID", "uuid", "(généré automatiquement si vide)")
        if self._is_new:
            import uuid as _uuid
            self._e_uuid.setText(str(_uuid.uuid4()))

        col1.addWidget(lbl_name); col1.addWidget(self._e_name)
        col1.addWidget(lbl_mfr);  col1.addWidget(self._e_mfr)
        col2.addWidget(lbl_type); col2.addWidget(self._e_type)
        col2.addWidget(lbl_src);  col2.addWidget(self._e_src)
        form_grid.addLayout(col1, 1); form_grid.addSpacing(12); form_grid.addLayout(col2, 1)
        lay.addLayout(form_grid)

        lay.addWidget(lbl_uuid); lay.addWidget(self._e_uuid)

        # ── Modes ─────────────────────────────────────────────────────────────
        modes_lbl = QLabel("Modes DMX")
        modes_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; margin-top: 6px;")
        lay.addWidget(modes_lbl)

        self._modes_table = QTableWidget()
        self._modes_table.setColumnCount(2)
        self._modes_table.setHorizontalHeaderLabels(["Nom du mode", "Nb canaux"])
        self._modes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._modes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._modes_table.setColumnWidth(1, 90)
        self._modes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._modes_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._modes_table.verticalHeader().setVisible(False)
        self._modes_table.setMinimumHeight(120)
        self._modes_table.setMaximumHeight(200)
        for mode in self._fixture.get("modes", []):
            self._add_mode_row(mode.get("name", ""), mode.get("channelCount", 0))
        lay.addWidget(self._modes_table)

        modes_btn_row = QHBoxLayout()
        btn_add_mode = QPushButton("+ Mode")
        btn_add_mode.setFixedHeight(26)
        btn_add_mode.setStyleSheet(_BTN_SECONDARY)
        btn_add_mode.clicked.connect(lambda: self._add_mode_row("Mode 1", 1))
        btn_del_mode = QPushButton("– Retirer")
        btn_del_mode.setFixedHeight(26)
        btn_del_mode.setStyleSheet(_BTN_SECONDARY)
        btn_del_mode.clicked.connect(self._del_mode_row)
        modes_btn_row.addWidget(btn_add_mode)
        modes_btn_row.addWidget(btn_del_mode)
        modes_btn_row.addStretch()
        lay.addLayout(modes_btn_row)

        # ── Boutons ────────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #2a2a2a; margin-top: 4px;")
        lay.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.setFixedHeight(34)
        btn_cancel.setStyleSheet(_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)

        self._btn_save = QPushButton("Enregistrer")
        self._btn_save.setFixedHeight(34)
        self._btn_save.setStyleSheet(_BTN_PRIMARY)
        self._btn_save.clicked.connect(self._on_save)

        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_save)
        lay.addLayout(btn_row)

    def _add_mode_row(self, name="", ch=1):
        row = self._modes_table.rowCount()
        self._modes_table.insertRow(row)
        self._modes_table.setItem(row, 0, QTableWidgetItem(str(name)))
        self._modes_table.setItem(row, 1, QTableWidgetItem(str(ch)))

    def _del_mode_row(self):
        row = self._modes_table.currentRow()
        if row >= 0:
            self._modes_table.removeRow(row)

    def _on_save(self):
        name = self._e_name.text().strip()
        mfr  = self._e_mfr.text().strip()
        if not name or not mfr:
            QMessageBox.warning(self, "Champs requis", "Le nom et le fabricant sont obligatoires.")
            return

        modes = []
        for r in range(self._modes_table.rowCount()):
            mode_name = (self._modes_table.item(r, 0) or QTableWidgetItem("")).text().strip()
            try:
                ch = int((self._modes_table.item(r, 1) or QTableWidgetItem("1")).text())
            except ValueError:
                ch = 1
            if mode_name:
                modes.append({"name": mode_name, "channelCount": ch, "profile": []})

        self._result = {
            "name":         name,
            "manufacturer": mfr,
            "fixture_type": self._e_type.text().strip(),
            "source":       self._e_src.text().strip(),
            "uuid":         self._e_uuid.text().strip(),
            "modes":        modes,
        }
        self.accept()

    def get_result(self) -> dict | None:
        return getattr(self, "_result", None)


# ---------------------------------------------------------------
# AdminPanel — fenêtre principale
# ---------------------------------------------------------------

class AdminPanel(QMainWindow):
    def __init__(self, id_token: str, refresh_token: str, admin_email: str):
        super().__init__()
        self._id_token          = id_token
        self._refresh_token     = refresh_token
        self._admin_email       = admin_email
        self._clients: list     = []
        self._filtered_clients: list = []

        self.setWindowTitle("MyStrow — Admin")
        self.setMinimumSize(900, 580)
        self._build_ui()
        self._load_clients()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # ── Header ── titre + outils admin ───────────────────────────────────
        header = QFrame()
        header.setFixedHeight(52)
        header.setStyleSheet(f"background: {BG_PANEL}; border-bottom: 1px solid #2a2a2a;")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 0, 16, 0)
        h_lay.setSpacing(8)

        title_lbl = QLabel("MyStrow  ·  Admin")
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title_lbl.setStyleSheet(f"color: {ACCENT}; background: transparent;")
        h_lay.addWidget(title_lbl)

        h_lay.addStretch()


        self.status_lbl = QLabel(self._admin_email)
        self.status_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px; background: transparent;")
        h_lay.addWidget(self.status_lbl)

        h_lay.addSpacing(10)

        btn_logout = QPushButton("Déconnexion")
        btn_logout.setStyleSheet(_BTN_RED)
        btn_logout.setFixedHeight(32)
        btn_logout.clicked.connect(self._on_logout)
        h_lay.addWidget(btn_logout)

        main_lay.addWidget(header)

        # ── Navigation Licences / Fixtures ────────────────────────────────────
        nav_bar = QFrame()
        nav_bar.setFixedHeight(38)
        nav_bar.setStyleSheet(f"background: {BG_PANEL}; border-bottom: 1px solid #1e1e1e;")
        nav_lay = QHBoxLayout(nav_bar)
        nav_lay.setContentsMargins(16, 0, 16, 0)
        nav_lay.setSpacing(4)

        _nav_active = (f"QPushButton {{ background: transparent; color: {ACCENT};"
                       f" border: none; border-bottom: 2px solid {ACCENT};"
                       f" border-radius: 0; font-size: 12px; font-weight: bold; padding: 0 14px; }}")
        _nav_idle   = (f"QPushButton {{ background: transparent; color: {TEXT_DIM};"
                       f" border: none; border-bottom: 2px solid transparent;"
                       f" border-radius: 0; font-size: 12px; padding: 0 14px; }}"
                       f"QPushButton:hover {{ color: {TEXT}; }}")

        self._btn_nav_lic = QPushButton("Licences")
        self._btn_nav_lic.setFixedHeight(38)
        self._btn_nav_lic.setStyleSheet(_nav_active)
        self._btn_nav_lic.clicked.connect(lambda: self._switch_view(0))
        nav_lay.addWidget(self._btn_nav_lic)

        self._btn_nav_fix = QPushButton("Fixtures")
        self._btn_nav_fix.setFixedHeight(38)
        self._btn_nav_fix.setStyleSheet(_nav_idle)
        self._btn_nav_fix.clicked.connect(lambda: self._switch_view(1))
        nav_lay.addWidget(self._btn_nav_fix)

        self._btn_nav_packs = QPushButton("Packs")
        self._btn_nav_packs.setFixedHeight(38)
        self._btn_nav_packs.setStyleSheet(_nav_idle)
        self._btn_nav_packs.clicked.connect(lambda: self._switch_view(2))
        nav_lay.addWidget(self._btn_nav_packs)

        self._btn_nav_release = QPushButton("Release")
        self._btn_nav_release.setFixedHeight(38)
        self._btn_nav_release.setStyleSheet(_nav_idle)
        self._btn_nav_release.clicked.connect(lambda: self._switch_view(3))
        nav_lay.addWidget(self._btn_nav_release)

        nav_lay.addStretch()
        main_lay.addWidget(nav_bar)

        # ── Stacked content ───────────────────────────────────────────────────
        self._content_stack = QStackedWidget()
        main_lay.addWidget(self._content_stack, 1)

        # ── Page 0 : Licences ─────────────────────────────────────────────────
        lic_page = QWidget()
        lic_lay = QVBoxLayout(lic_page)
        lic_lay.setContentsMargins(0, 0, 0, 0)
        lic_lay.setSpacing(0)
        self._content_stack.addWidget(lic_page)

        # ── Barre recherche + compteur ────────────────────────────────────────
        search_bar = QFrame()
        search_bar.setFixedHeight(46)
        search_bar.setStyleSheet(f"background: {BG_MAIN}; border-bottom: 1px solid #242424;")
        s_lay = QHBoxLayout(search_bar)
        s_lay.setContentsMargins(20, 0, 20, 0)
        s_lay.setSpacing(10)

        search_icon = QLabel("🔍")
        search_icon.setStyleSheet("background: transparent; font-size: 13px;")
        s_lay.addWidget(search_icon)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Rechercher par email, plan, statut, source…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedHeight(30)
        self.search_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_INPUT}; color: {TEXT};
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 0 10px; font-size: 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
        """)
        self.search_edit.textChanged.connect(self._on_search)
        s_lay.addWidget(self.search_edit)

        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 11px; background: transparent; min-width: 90px;"
        )
        self.count_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s_lay.addWidget(self.count_lbl)

        lic_lay.addWidget(search_bar)

        # ── Indicateur de chargement ──────────────────────────────────────────
        self.loading_lbl = QLabel("Chargement…")
        self.loading_lbl.setAlignment(Qt.AlignCenter)
        self.loading_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 13px; padding: 20px;")
        self.loading_lbl.hide()
        lic_lay.addWidget(self.loading_lbl)

        # ── Tableau ───────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Email", "Plan", "Forfait", "Source", "Expiration", "Statut", "Machines"]
        )
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 7):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        lic_lay.addWidget(self.table)

        # ── Barre d'actions client ────────────────────────────────────────────
        action_bar = QFrame()
        action_bar.setFixedHeight(56)
        action_bar.setStyleSheet(f"background: {BG_PANEL}; border-top: 1px solid #2a2a2a;")
        a_lay = QHBoxLayout(action_bar)
        a_lay.setContentsMargins(20, 0, 20, 0)
        a_lay.setSpacing(8)

        # Créer nouveau client — toujours actif
        self.btn_new = QPushButton("＋  Nouveau client")
        self.btn_new.setStyleSheet(_BTN_PRIMARY)
        self.btn_new.setFixedHeight(36)
        self.btn_new.clicked.connect(self._on_new_client)
        a_lay.addWidget(self.btn_new)

        a_lay.addSpacing(12)
        sep1 = QFrame(); sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("QFrame { color: #333; max-height: 28px; }")
        a_lay.addWidget(sep1)
        a_lay.addSpacing(8)

        # Actions sur le client sélectionné
        self.btn_renew = QPushButton("Renouveler")
        self.btn_renew.setStyleSheet(_BTN_GREEN)
        self.btn_renew.setFixedHeight(36)
        self.btn_renew.setEnabled(False)
        self.btn_renew.clicked.connect(self._on_renew)
        a_lay.addWidget(self.btn_renew)

        self.btn_machines = QPushButton("Machines")
        self.btn_machines.setStyleSheet(_BTN_SECONDARY)
        self.btn_machines.setFixedHeight(36)
        self.btn_machines.setEnabled(False)
        self.btn_machines.clicked.connect(self._on_machines)
        a_lay.addWidget(self.btn_machines)

        self.btn_stripe_open = QPushButton("Stripe ↗")
        self.btn_stripe_open.setStyleSheet("""
            QPushButton { background:#635bff; color:white; border:none;
                          border-radius:4px; font-size:12px; font-weight:bold;
                          padding: 0 14px; }
            QPushButton:hover { background:#7a73ff; }
            QPushButton:disabled { background:#252525; color:#444; border:1px solid #333; }
        """)
        self.btn_stripe_open.setFixedHeight(36)
        self.btn_stripe_open.setEnabled(False)
        self.btn_stripe_open.clicked.connect(self._on_stripe_open)
        a_lay.addWidget(self.btn_stripe_open)

        self.btn_cancel_sub = QPushButton("Annuler abo.")
        self.btn_cancel_sub.setStyleSheet("""
            QPushButton { background:transparent; color:#9c27b0; border:1px solid #7b1fa2;
                          border-radius:4px; font-size:12px; font-weight:bold;
                          padding: 0 12px; }
            QPushButton:hover { background:#7b1fa2; color:white; }
            QPushButton:disabled { color:#444; border-color:#333; }
        """)
        self.btn_cancel_sub.setFixedHeight(36)
        self.btn_cancel_sub.setEnabled(False)
        self.btn_cancel_sub.clicked.connect(self._on_cancel_subscription)
        a_lay.addWidget(self.btn_cancel_sub)

        a_lay.addStretch()

        # Supprimer — danger, isolé à droite
        self.btn_delete = QPushButton("🗑  Supprimer")
        self.btn_delete.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{RED}; border:1px solid #6a2020;
                          border-radius:4px; font-size:11px; padding: 0 12px; }}
            QPushButton:hover {{ background:{RED}; color:white; }}
            QPushButton:disabled {{ color:#444; border-color:#333; }}
        """)
        self.btn_delete.setFixedHeight(36)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._on_delete)
        a_lay.addWidget(self.btn_delete)

        lic_lay.addWidget(action_bar)

        # ── Page 1 : Fixtures ─────────────────────────────────────────────────
        self._build_fixtures_panel()

        # ── Page 2 : Packs ────────────────────────────────────────────────────
        self._build_packs_panel()

        # ── Page 3 : Release ──────────────────────────────────────────────────
        self._build_release_panel()

    # ------------------------------------------------------------------

    def _switch_view(self, idx: int):
        _active = (f"QPushButton {{ background: transparent; color: {ACCENT};"
                   f" border: none; border-bottom: 2px solid {ACCENT};"
                   f" border-radius: 0; font-size: 12px; font-weight: bold; padding: 0 14px; }}")
        _idle   = (f"QPushButton {{ background: transparent; color: {TEXT_DIM};"
                   f" border: none; border-bottom: 2px solid transparent;"
                   f" border-radius: 0; font-size: 12px; padding: 0 14px; }}"
                   f"QPushButton:hover {{ color: {TEXT}; }}")
        self._btn_nav_lic.setStyleSheet(_active if idx == 0 else _idle)
        self._btn_nav_fix.setStyleSheet(_active if idx == 1 else _idle)
        self._btn_nav_packs.setStyleSheet(_active if idx == 2 else _idle)
        self._btn_nav_release.setStyleSheet(_active if idx == 3 else _idle)
        self._content_stack.setCurrentIndex(idx)
        if idx == 1 and not self._fixtures_loaded:
            self._load_fixtures()

    def _build_fixtures_panel(self):
        fix_page = QWidget()
        fix_lay = QVBoxLayout(fix_page)
        fix_lay.setContentsMargins(0, 0, 0, 0)
        fix_lay.setSpacing(0)

        # Barre outils fixtures
        fix_toolbar = QFrame()
        fix_toolbar.setFixedHeight(46)
        fix_toolbar.setStyleSheet(f"background: {BG_MAIN}; border-bottom: 1px solid #242424;")
        ft_lay = QHBoxLayout(fix_toolbar)
        ft_lay.setContentsMargins(16, 0, 16, 0)
        ft_lay.setSpacing(8)

        self._fix_search = QLineEdit()
        self._fix_search.setPlaceholderText("Rechercher par nom, fabricant, type…")
        self._fix_search.setClearButtonEnabled(True)
        self._fix_search.setFixedHeight(30)
        self._fix_search.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_INPUT}; color: {TEXT};
                border: 1px solid #3a3a3a; border-radius: 5px;
                padding: 0 10px; font-size: 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
        """)
        self._fix_search.textChanged.connect(self._on_fix_search)
        ft_lay.addWidget(self._fix_search)

        self._fix_count_lbl = QLabel("")
        self._fix_count_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 11px; background: transparent; min-width: 90px;"
        )
        self._fix_count_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ft_lay.addWidget(self._fix_count_lbl)

        btn_fix_refresh = QPushButton("↻  Actualiser")
        btn_fix_refresh.setStyleSheet(_BTN_SECONDARY)
        btn_fix_refresh.setFixedHeight(30)
        btn_fix_refresh.clicked.connect(self._load_fixtures)
        ft_lay.addWidget(btn_fix_refresh)

        btn_add_fix = QPushButton("➕  Ajouter")
        btn_add_fix.setStyleSheet(_BTN_PRIMARY)
        btn_add_fix.setFixedHeight(30)
        btn_add_fix.clicked.connect(self._on_add_fixture)
        ft_lay.addWidget(btn_add_fix)

        btn_fix_import = QPushButton("📥  Importer…")
        btn_fix_import.setStyleSheet(_BTN_SECONDARY)
        btn_fix_import.setFixedHeight(30)
        btn_fix_import.setToolTip("Importer des fichiers .xml / .mystrow vers Firestore")
        btn_fix_import.clicked.connect(self._on_gdtf_upload)
        ft_lay.addWidget(btn_fix_import)

        fix_lay.addWidget(fix_toolbar)

        # Indicateur de chargement fixtures
        self._fix_loading = QLabel("Chargement des fixtures…")
        self._fix_loading.setAlignment(Qt.AlignCenter)
        self._fix_loading.setStyleSheet(f"color: {TEXT_DIM}; font-size: 13px; padding: 20px;")
        self._fix_loading.hide()
        fix_lay.addWidget(self._fix_loading)

        # Tableau fixtures
        self._fix_table = QTableWidget()
        self._fix_table.setColumnCount(6)
        self._fix_table.setHorizontalHeaderLabels(
            ["Nom", "Fabricant", "Type", "Modes", "Source", "UUID"]
        )
        fhdr = self._fix_table.horizontalHeader()
        fhdr.setSectionResizeMode(0, QHeaderView.Stretch)
        fhdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        fhdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        fhdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        fhdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        fhdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._fix_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._fix_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._fix_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._fix_table.setAlternatingRowColors(True)
        self._fix_table.verticalHeader().setVisible(False)
        self._fix_table.setShowGrid(False)
        self._fix_table.selectionModel().selectionChanged.connect(self._on_fix_selection_changed)
        self._fix_table.cellDoubleClicked.connect(self._on_fixture_double_clicked)
        self._fix_table.horizontalHeader().sectionClicked.connect(self._on_sort_column)
        self._fix_table.horizontalHeader().setSectionsClickable(True)
        fix_lay.addWidget(self._fix_table)

        # Barre d'actions fixtures
        fix_action_bar = QFrame()
        fix_action_bar.setFixedHeight(48)
        fix_action_bar.setStyleSheet(f"background: {BG_PANEL}; border-top: 1px solid #2a2a2a;")
        fa_lay = QHBoxLayout(fix_action_bar)
        fa_lay.setContentsMargins(16, 0, 16, 0)
        fa_lay.setSpacing(8)

        fa_lay.addStretch()

        self._btn_edit_fix = QPushButton("✏️  Éditer")
        self._btn_edit_fix.setStyleSheet(_BTN_SECONDARY)
        self._btn_edit_fix.setFixedHeight(32)
        self._btn_edit_fix.setEnabled(False)
        self._btn_edit_fix.clicked.connect(self._on_edit_fixture)
        fa_lay.addWidget(self._btn_edit_fix)

        self._btn_del_fix = QPushButton("🗑  Supprimer")
        self._btn_del_fix.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{RED}; border:1px solid #6a2020;
                          border-radius:4px; font-size:11px; padding: 0 12px; }}
            QPushButton:hover {{ background:{RED}; color:white; }}
            QPushButton:disabled {{ color:#444; border-color:#333; }}
        """)
        self._btn_del_fix.setFixedHeight(32)
        self._btn_del_fix.setEnabled(False)
        self._btn_del_fix.clicked.connect(self._on_delete_fixture)
        fa_lay.addWidget(self._btn_del_fix)

        fix_lay.addWidget(fix_action_bar)
        self._content_stack.addWidget(fix_page)

        # State
        self._fixtures_loaded = False
        self._all_fixtures: list = []
        self._filtered_fixtures: list = []
        self._fix_sort_col = 0
        self._fix_sort_asc = True

    def _open_fixture_editor(self):
        """Ouvre l'éditeur de fixtures MyStrow en fenêtre autonome."""
        from fixture_editor import FixtureEditorDialog
        dlg = FixtureEditorDialog(self)
        dlg.show()

    def _build_packs_panel(self):
        """Page 2 : Éditeur de packs de fixtures."""
        from admin_pack_editor import AdminPackEditorWidget
        self._pack_editor = AdminPackEditorWidget(self._id_token)
        self._content_stack.addWidget(self._pack_editor)

    def _build_release_panel(self):
        """Page 3 : Release pipeline + Backup, intégrés directement dans l'onglet."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(14)

        # ── Titre ────────────────────────────────────────────────────────────
        title = QLabel("Release MyStrow")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT};")
        lay.addWidget(title)

        # ── Version ──────────────────────────────────────────────────────────
        v_row = QHBoxLayout()
        v_row.setSpacing(16)
        if _RELEASE_OK:
            current = get_current_version() or "?"
            bumped  = bump_version(current) if current != "?" else ""
        else:
            current, bumped = "—", ""

        v_row.addWidget(QLabel(
            f"Version actuelle :  <b>{current}</b>", textFormat=Qt.RichText
        ))
        v_row.addSpacing(8)
        v_row.addWidget(QLabel("Nouvelle version :"))
        self._rel_version_edit = QLineEdit(bumped)
        self._rel_version_edit.setFixedWidth(120)
        self._rel_version_edit.setFixedHeight(34)
        self._rel_version_edit.setEnabled(_RELEASE_OK)
        v_row.addWidget(self._rel_version_edit)
        v_row.addStretch()
        lay.addLayout(v_row)

        # ── Action + bouton Lancer ────────────────────────────────────────────
        a_row = QHBoxLayout()
        a_row.setSpacing(10)
        a_row.addWidget(QLabel("Action :"))
        self._rel_action_combo = QComboBox()
        self._rel_action_combo.addItem("Push GitHub", "github")
        self._rel_action_combo.addItem("Installer local (Bureau)", "local")
        self._rel_action_combo.addItem("Les deux", "both")
        self._rel_action_combo.setMinimumWidth(280)
        self._rel_action_combo.setFixedHeight(34)
        self._rel_action_combo.setEnabled(_RELEASE_OK)
        self._rel_action_combo.currentIndexChanged.connect(self._on_rel_action_changed)
        a_row.addWidget(self._rel_action_combo)

        self._btn_rel_start = QPushButton("▶  Lancer la release")
        self._btn_rel_start.setFixedHeight(34)
        self._btn_rel_start.setEnabled(_RELEASE_OK)
        self._btn_rel_start.setStyleSheet(_BTN_PRIMARY)
        self._btn_rel_start.clicked.connect(self._on_rel_start)
        a_row.addWidget(self._btn_rel_start)

        if _RELEASE_OK:
            btn_gh = QPushButton("GitHub Actions →")
            btn_gh.setFixedHeight(34)
            btn_gh.setStyleSheet(_BTN_SECONDARY)
            btn_gh.clicked.connect(
                lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}/actions")
            )
            a_row.addWidget(btn_gh)

        a_row.addStretch()
        lay.addLayout(a_row)

        self._rel_mac_note = QLabel(
            "ℹ️  Mode 'local' : build Windows uniquement — le Mac est géré par GitHub CI."
        )
        self._rel_mac_note.setStyleSheet(f"color: #555; font-size: 10px;")
        self._rel_mac_note.setVisible(False)
        lay.addWidget(self._rel_mac_note)

        # ── Barre de progression ──────────────────────────────────────────────
        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)
        self._rel_progress = QProgressBar()
        self._rel_progress.setRange(0, 100)
        self._rel_progress.setValue(0)
        self._rel_progress.setFixedHeight(10)
        self._rel_progress.setTextVisible(False)
        self._rel_progress.setStyleSheet(f"""
            QProgressBar {{
                background: #222; border: none; border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {ACCENT}, stop:1 #0088aa);
                border-radius: 5px;
            }}
        """)
        self._rel_pct_lbl = QLabel("0 %")
        self._rel_pct_lbl.setFixedWidth(36)
        self._rel_pct_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._rel_pct_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px;")
        prog_row.addWidget(self._rel_progress)
        prog_row.addWidget(self._rel_pct_lbl)
        lay.addLayout(prog_row)

        self._rel_step_lbl = QLabel("")
        self._rel_step_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px;")
        lay.addWidget(self._rel_step_lbl)

        # ── Console log ───────────────────────────────────────────────────────
        self._rel_log = QTextEdit()
        self._rel_log.setReadOnly(True)
        self._rel_log.setFont(QFont("Consolas", 9))
        self._rel_log.setStyleSheet(
            f"QTextEdit {{ background:#0d0d0d; color:#cccccc;"
            f" border:1px solid #2a2a2a; border-radius:5px; }}"
        )
        lay.addWidget(self._rel_log, 1)

        # ── Séparateur + Backup ───────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { color: #2a2a2a; }")
        lay.addWidget(sep)

        bk_row = QHBoxLayout()
        bk_row.setSpacing(8)
        bk_lbl = QLabel("Backup :")
        bk_lbl.setFixedWidth(48)
        bk_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px;")
        bk_row.addWidget(bk_lbl)

        self._backup_dest_edit = QLineEdit()
        self._backup_dest_edit.setPlaceholderText("Dossier de destination (Bureau par défaut)")
        self._backup_dest_edit.setFixedHeight(30)
        self._backup_dest_edit.setStyleSheet(
            f"QLineEdit {{ background:#1e1e1e; color:#ccc; border:1px solid #333;"
            f" border-radius:4px; padding:0 8px; font-size:11px; }}"
            f"QLineEdit:focus {{ border-color:{ACCENT}; }}"
        )
        # Charger le chemin sauvegardé
        _saved = _backup_dest_load()
        if _saved:
            self._backup_dest_edit.setText(str(_saved))
        self._backup_dest_edit.textChanged.connect(lambda t: _backup_dest_save(t))
        bk_row.addWidget(self._backup_dest_edit, 1)

        btn_browse = QPushButton("📂")
        btn_browse.setFixedSize(30, 30)
        btn_browse.setToolTip("Choisir le dossier de destination")
        btn_browse.setStyleSheet(
            f"QPushButton {{ background:#2a2a2a; color:#aaa; border:1px solid #444;"
            f" border-radius:4px; font-size:14px; }}"
            f"QPushButton:hover {{ background:#3a3a3a; color:#fff; }}"
        )
        btn_browse.clicked.connect(self._browse_backup_dest)
        bk_row.addWidget(btn_browse)

        self.btn_backup = btn_bk = QPushButton("💾  Sauvegarder")
        btn_bk.setFixedHeight(30)
        btn_bk.setStyleSheet(_BTN_SECONDARY)
        btn_bk.setEnabled(_RELEASE_OK)
        btn_bk.setToolTip("Sauvegarde le projet en .zip dans le dossier choisi")
        btn_bk.clicked.connect(self._on_backup)
        bk_row.addWidget(btn_bk)
        lay.addLayout(bk_row)

        self._content_stack.addWidget(page)

        # Workers
        self._rel_thread = None
        self._rel_worker = None

    # ── Handlers Release panel ─────────────────────────────────────────────

    def _on_rel_action_changed(self, index):
        action = self._rel_action_combo.itemData(index)
        self._rel_mac_note.setVisible(action == "local")

    def _on_rel_start(self):
        version = self._rel_version_edit.text().strip()
        if not version:
            QMessageBox.warning(self, "Version manquante", "Saisissez un numéro de version.")
            return
        action = self._rel_action_combo.currentData()
        self._btn_rel_start.setEnabled(False)
        self._btn_rel_start.setText("En cours…")
        self._rel_log.clear()
        self._rel_progress.setValue(0)
        self._rel_pct_lbl.setText("0 %")
        self._rel_step_lbl.setText("")
        self._rel_step_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px;")

        self._rel_thread = QThread(self)
        self._rel_worker = ReleaseWorker(version, action)
        self._rel_worker.moveToThread(self._rel_thread)
        self._rel_thread.started.connect(self._rel_worker.run)
        self._rel_worker.log.connect(self._rel_append_log)
        self._rel_worker.progress.connect(self._rel_on_progress)
        self._rel_worker.step.connect(self._rel_step_lbl.setText)
        self._rel_worker.finished.connect(self._rel_on_finished)
        self._rel_worker.finished.connect(self._rel_thread.quit)
        self._rel_thread.finished.connect(self._rel_thread.deleteLater)
        self._rel_thread.start()

    def _rel_on_progress(self, pct: int):
        self._rel_progress.setValue(pct)
        self._rel_pct_lbl.setText(f"{pct} %")

    def _rel_append_log(self, text: str):
        self._rel_log.append(text)
        self._rel_log.verticalScrollBar().setValue(
            self._rel_log.verticalScrollBar().maximum()
        )

    def _rel_on_finished(self, success: bool, msg: str):
        self._btn_rel_start.setEnabled(True)
        self._btn_rel_start.setText("▶  Lancer la release")
        if success:
            self._rel_on_progress(100)
            self._rel_step_lbl.setText("Terminé ✓")
            self._rel_step_lbl.setStyleSheet("color:#4CAF50; font-size:10px;")
            self._rel_append_log(f"\n{msg}")
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        else:
            self._rel_step_lbl.setText("Erreur")
            self._rel_step_lbl.setStyleSheet(f"color:{RED}; font-size:10px;")
            self._rel_append_log(f"\nERREUR : {msg}")
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONHAND)
            except Exception:
                pass
            QMessageBox.critical(self, "Erreur release", msg)

    # ------------------------------------------------------------------

    def _on_selection_changed(self):
        has_sel = self.table.currentRow() >= 0
        self.btn_renew.setEnabled(has_sel)
        self.btn_machines.setEnabled(has_sel)
        self.btn_delete.setEnabled(has_sel)
        # Boutons Stripe : seulement si le client a un stripe_customer_id
        client = self._get_selected_client()
        is_stripe = bool(client and client.get("stripe_customer_id", ""))
        self.btn_stripe_open.setEnabled(is_stripe)
        has_sub = bool(client and client.get("stripe_subscription_id", ""))
        self.btn_cancel_sub.setEnabled(has_sub)

    def _get_selected_client(self) -> dict | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._filtered_clients):
            return self._filtered_clients[row]
        return None

    # ------------------------------------------------------------------

    def _load_clients(self):
        self.loading_lbl.setText("Chargement…")
        self.loading_lbl.show()
        self.table.hide()
        _run_async(
            self, _query_all_licenses, self._id_token,
            on_success=self._on_clients_loaded,
            on_error=self._on_load_error,
        )

    def _on_clients_loaded(self, clients: list):
        clients.sort(key=lambda d: d.get("expiry_utc", 0), reverse=True)
        self._clients = clients
        self.search_edit.clear()  # réinitialise la recherche à chaque refresh
        self._populate_table(clients)
        self.loading_lbl.hide()
        self.table.show()

    def _on_load_error(self, msg: str):
        self.loading_lbl.setText(f"Erreur de chargement : {msg}")
        self.table.show()

    def _on_search(self, text: str):
        """Filtre le tableau en temps réel selon le texte saisi."""
        q = text.strip().lower()
        if not q:
            self._populate_table(self._clients)
            return
        filtered = []
        now = datetime.now(timezone.utc).timestamp()
        _forfait_labels = {"monthly": "mensuel", "annual": "annuel", "lifetime": "à vie"}
        for c in self._clients:
            email     = c.get("email", "").lower()
            plan      = c.get("plan", "").lower()
            forfait   = _forfait_labels.get(c.get("plan_type", ""), "")
            source    = "stripe" if c.get("stripe_customer_id") else "manuel"
            expiry    = c.get("expiry_utc", 0)
            days_left = int((expiry - now) / 86400) if expiry else -1
            if days_left > 30:
                statut = "actif"
            elif days_left >= 0:
                statut = f"expire {days_left}j"
            else:
                statut = "expiré"
            haystack = f"{email} {plan} {forfait} {source} {statut}"
            if q in haystack:
                filtered.append(c)
        self._populate_table(filtered)

    def _populate_table(self, clients: list):
        self._filtered_clients = clients
        now = datetime.now(timezone.utc).timestamp()
        self.table.setRowCount(len(clients))

        _forfait_labels = {
            "monthly":  "Mensuel",
            "annual":   "Annuel",
            "lifetime": "À vie",
        }

        for row, c in enumerate(clients):
            email       = c.get("email", "?")
            plan        = c.get("plan", "?")
            forfait     = _forfait_labels.get(c.get("plan_type", ""), "—")
            is_stripe   = bool(c.get("stripe_customer_id", ""))
            source_str  = "🟣 Stripe" if is_stripe else "✏️ Manuel"
            expiry      = c.get("expiry_utc", 0)
            machines    = c.get("machines", [])

            exp_str   = _fmt_date(expiry) if expiry else "?"
            mach_str  = f"{len(machines)}/2"
            days_left = int((expiry - now) / 86400) if expiry else -1

            if days_left > 30:
                statut_str   = f"Actif ({days_left}j)"
                statut_color = GREEN
            elif days_left >= 0:
                statut_str   = f"Expire dans {days_left}j"
                statut_color = ORANGE
            else:
                statut_str   = "EXPIRÉ"
                statut_color = RED

            items = [
                QTableWidgetItem(email),
                QTableWidgetItem(plan),
                QTableWidgetItem(forfait),
                QTableWidgetItem(source_str),
                QTableWidgetItem(exp_str),
                QTableWidgetItem(statut_str),
                QTableWidgetItem(mach_str),
            ]
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                if col == 5:
                    item.setForeground(QColor(statut_color))
                if col == 3:
                    item.setForeground(QColor("#635bff" if is_stripe else "#888888"))
                self.table.setItem(row, col, item)

        self.table.resizeRowsToContents()

        # Compteur filtré / total
        total = len(self._clients)
        shown = len(clients)
        if shown == total:
            self.count_lbl.setText(f"{total} compte(s)")
        else:
            self.count_lbl.setText(f"{shown} / {total} compte(s)")

    # ------------------------------------------------------------------

    def _on_stripe_open(self):
        """Ouvre la fiche client dans Stripe Dashboard."""
        client = self._get_selected_client()
        if not client:
            return
        customer_id = client.get("stripe_customer_id", "")
        if customer_id:
            import webbrowser
            webbrowser.open(f"https://dashboard.stripe.com/customers/{customer_id}")

    def _on_cancel_subscription(self):
        """Annule l'abonnement Stripe du client sélectionné."""
        client = self._get_selected_client()
        if not client:
            return
        sub_id = client.get("stripe_subscription_id", "")
        email  = client.get("email", "?")
        if not sub_id:
            QMessageBox.information(self, "Annulation", "Ce client n'a pas d'abonnement Stripe actif.")
            return

        confirm = QMessageBox.question(
            self, "Confirmer l'annulation",
            f"Annuler l'abonnement Stripe de :\n{email}\n\n"
            "L'abonnement sera résilié en fin de période en cours.\n"
            "La licence sera révoquée automatiquement par le webhook.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            import base64, urllib.request, urllib.parse, json as _json
            try:
                from stripe_config import STRIPE_SECRET_KEY as _sk
            except ImportError:
                QMessageBox.critical(self, "Erreur",
                    "stripe_config.py introuvable.\n"
                    "Créez ce fichier avec STRIPE_SECRET_KEY = 'rk_live_...'")
                return

            url  = f"https://api.stripe.com/v1/subscriptions/{sub_id}"
            tok  = base64.b64encode(f"{_sk}:".encode()).decode()
            data = urllib.parse.urlencode({"cancel_at_period_end": "true"}).encode()
            req  = urllib.request.Request(url, data=data, method="POST",
                                          headers={"Authorization": f"Basic {tok}",
                                                   "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = _json.loads(resp.read().decode())

            if result.get("cancel_at_period_end"):
                QMessageBox.information(self, "Abonnement annulé",
                    f"L'abonnement de {email} sera résilié en fin de période.\n"
                    "La licence sera révoquée automatiquement.")
                self._load_clients()
            else:
                QMessageBox.warning(self, "Attention", "Réponse inattendue de Stripe.")

        except Exception as e:
            QMessageBox.critical(self, "Erreur Stripe", str(e))

    def _on_new_client(self):
        dlg = CreateClientDialog(self._id_token, self)
        dlg.client_created.connect(self._load_clients)
        dlg.exec()

    def _on_renew(self):
        client = self._get_selected_client()
        if client is None:
            return
        dlg = RenewDialog(client, self._id_token, self)
        dlg.renewed.connect(self._load_clients)
        dlg.exec()

    def _on_machines(self):
        client = self._get_selected_client()
        if client is None:
            return
        dlg = MachinesDialog(client, self._id_token, self)
        dlg.revoked.connect(self._load_clients)
        dlg.exec()

    def _on_delete(self):
        client = self._get_selected_client()
        if client is None:
            return
        email    = client.get("email", "?")
        uid      = client.get("_uid", "")
        has_sdk  = _init_firebase_admin()
        auth_msg = "Le compte Auth Firebase sera également supprimé." if has_sdk else (
            "⚠️ service_account.json absent — le compte Auth Firebase devra être "
            "supprimé manuellement depuis la console Firebase."
        )
        reply = QMessageBox.warning(
            self, "Supprimer le client",
            f"Supprimer définitivement <b>{email}</b> ?<br><br>{auth_msg}",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        self.btn_delete.setEnabled(False)
        _run_async(
            self, self._do_delete, uid,
            on_success=lambda _: self._on_deleted(email, uid),
            on_error=self._on_delete_error,
        )

    def _do_delete(self, uid: str):
        """Supprime le doc Firestore puis le compte Auth (si SDK disponible)."""
        _delete_firestore_doc(f"licenses/{uid}", self._id_token)
        if _init_firebase_admin():
            _delete_auth_user(uid)

    def _on_deleted(self, email: str, uid: str):
        self._load_clients()
        QMessageBox.information(
            self, "Compte supprimé",
            f"{email} a été supprimé (licence + compte Auth)."
        )

    def _on_delete_error(self, msg: str):
        self.btn_delete.setEnabled(True)
        QMessageBox.critical(self, "Erreur suppression", msg)

    # ── Fixtures panel ─────────────────────────────────────────────────────────

    def _load_fixtures(self):
        self._fix_loading.show()
        self._fix_table.hide()
        self._fixtures_loaded = False
        _run_async(
            self, _query_all_fixtures, self._id_token,
            on_success=self._on_fixtures_loaded,
            on_error=self._on_fixtures_load_error,
        )

    def _on_fixtures_loaded(self, fixtures: list):
        fixtures.sort(key=lambda f: f.get("name", "").lower())
        self._all_fixtures = fixtures
        self._fixtures_loaded = True
        self._fix_sort_col = 0
        self._fix_sort_asc = True
        self._fix_search.clear()
        self._populate_fixtures(fixtures)
        self._fix_loading.hide()
        self._fix_table.show()

    def _on_fixtures_load_error(self, msg: str):
        self._fix_loading.setText(f"Erreur : {msg}")
        self._fix_table.show()

    def _on_fix_search(self, text: str):
        q = text.strip().lower()
        if not q:
            self._populate_fixtures(self._all_fixtures)
            return
        filtered = [
            f for f in self._all_fixtures
            if q in f.get("name", "").lower()
            or q in f.get("manufacturer", "").lower()
            or q in f.get("fixture_type", "").lower()
            or q in f.get("source", "").lower()
        ]
        self._populate_fixtures(filtered)

    def _populate_fixtures(self, fixtures: list):
        self._filtered_fixtures = fixtures
        self._fix_table.setRowCount(0)
        for fx in fixtures:
            row = self._fix_table.rowCount()
            self._fix_table.insertRow(row)
            modes = fx.get("modes", [])
            if isinstance(modes, list):
                modes_str = str(len(modes))
            else:
                modes_str = "?"
            cells = [
                fx.get("name", ""),
                fx.get("manufacturer", ""),
                fx.get("fixture_type", ""),
                modes_str,
                fx.get("source", ""),
                fx.get("uuid", fx.get("_doc_id", "")),
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                self._fix_table.setItem(row, col, item)
        total = len(fixtures)
        self._fix_count_lbl.setText(f"{total} fixture{'s' if total != 1 else ''}")
        self._btn_del_fix.setEnabled(False)

    def _on_fix_selection_changed(self):
        has_sel = self._fix_table.currentRow() >= 0
        self._btn_del_fix.setEnabled(has_sel)
        self._btn_edit_fix.setEnabled(has_sel)

    def _on_sort_column(self, col: int):
        if self._fix_sort_col == col:
            self._fix_sort_asc = not self._fix_sort_asc
        else:
            self._fix_sort_col = col
            self._fix_sort_asc = True
        _keys = ["name", "manufacturer", "fixture_type", None, "source", "uuid"]

        def _sort_key(fx):
            if col == 3:  # nb modes
                return len(fx.get("modes", []) or [])
            k = _keys[col] if col < len(_keys) else None
            return (fx.get(k, "") or "").lower() if k else ""

        self._all_fixtures.sort(key=_sort_key, reverse=not self._fix_sort_asc)
        self._on_fix_search(self._fix_search.text())

    def _on_fixture_double_clicked(self, row: int, col: int):
        self._on_edit_fixture()

    def _on_edit_fixture(self):
        row = self._fix_table.currentRow()
        if row < 0 or row >= len(self._filtered_fixtures):
            return
        fx = self._filtered_fixtures[row]
        dlg = _FixtureEditDialog(self, fixture=dict(fx))
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                self._upload_fixture(result)

    def _on_add_fixture(self):
        dlg = _FixtureEditDialog(self)
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                self._upload_fixture(result)

    def _upload_fixture(self, fixture_data: dict):
        self._pending_fixture_name = fixture_data.get("name", "")
        _run_async(
            self, _do_upload_fixture_async, fixture_data, self._id_token,
            on_success=self._on_fixture_saved,
            on_error=self._on_fixture_save_error,
        )

    def _on_fixture_saved(self, _):
        self._load_fixtures()
        QMessageBox.information(self, "Fixture enregistrée",
                                f"« {self._pending_fixture_name} » a été sauvegardée.")

    def _on_fixture_save_error(self, msg: str):
        QMessageBox.critical(self, "Erreur sauvegarde", msg)

    def _on_delete_fixture(self):
        row = self._fix_table.currentRow()
        if row < 0 or row >= len(self._filtered_fixtures):
            return
        fx = self._filtered_fixtures[row]
        name = fx.get("name", "?")
        doc_id = fx.get("_doc_id", "")
        if not doc_id:
            QMessageBox.warning(self, "Erreur", "ID de document introuvable — suppression impossible.")
            return
        rep = QMessageBox.question(
            self, "Supprimer la fixture",
            f"Supprimer « {name} » de Firestore ?\nCette action est irréversible.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if rep != QMessageBox.Yes:
            return
        self._btn_del_fix.setEnabled(False)
        _run_async(
            self, _delete_fixture_doc, doc_id, self._id_token,
            on_success=lambda _: self._on_fixture_deleted(name),
            on_error=self._on_fixture_delete_error,
        )

    def _on_fixture_deleted(self, name: str):
        self._load_fixtures()
        QMessageBox.information(self, "Fixture supprimée", f"« {name} » a été supprimée de Firestore.")

    def _on_fixture_delete_error(self, msg: str):
        self._btn_del_fix.setEnabled(True)
        QMessageBox.critical(self, "Erreur suppression", msg)

    # ── General ────────────────────────────────────────────────────────────────

    def _on_restart(self):
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _on_logout(self):
        _clear_admin_cache()
        self.close()
        _show_login_then_panel()

    def _on_release(self):
        dlg = ReleaseDialog(self)
        dlg.exec()

    def _on_gdtf_enrich(self):
        dlg = OflSyncDialog(self)
        dlg.exec()

    def _on_gdtf_upload(self):
        dlg = GdtfUploadDialog(self)
        dlg.exec()

    def _browse_backup_dest(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination du backup",
            self._backup_dest_edit.text() or str(Path.home() / "Desktop"),
        )
        if folder:
            self._backup_dest_edit.setText(folder)

    def _on_backup(self):
        """Lance la sauvegarde du projet en .zip dans le dossier choisi."""
        if not _RELEASE_OK:
            QMessageBox.warning(self, "Backup", "release.py introuvable — impossible de localiser le dossier projet.")
            return

        src  = _RELEASE_DIR
        dest = Path.home() / "Desktop"

        # Dossier personnalisé saisi dans le champ
        custom = self._backup_dest_edit.text().strip()
        extra  = Path(custom) if custom else None
        if extra and not extra.exists():
            QMessageBox.warning(self, "Backup", f"Dossier de destination introuvable :\n{extra}")
            return

        dest_info = f"\nBureau : {dest}"
        if extra:
            dest_info += f"\n+ Copie dans : {extra}"

        reply = QMessageBox.question(
            self, "Backup projet",
            f"Sauvegarder le projet en .zip ?\n\nSource : {src}{dest_info}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_backup.setEnabled(False)
        self.btn_backup.setText("⏳  Backup…")

        self._backup_thread = QThread(self)
        self._backup_worker = BackupWorker(src, dest, extra)
        self._backup_worker.moveToThread(self._backup_thread)
        self._backup_thread.started.connect(self._backup_worker.run)
        self._backup_worker.progress.connect(lambda msg: self.status_lbl.setText(msg))
        self._backup_worker.finished.connect(self._on_backup_done)
        self._backup_worker.finished.connect(self._backup_thread.quit)
        self._backup_thread.finished.connect(self._backup_thread.deleteLater)
        self._backup_thread.start()

    def _on_backup_done(self, success: bool, msg: str):
        self.btn_backup.setEnabled(True)
        self.btn_backup.setText("💾  Backup…")
        self.status_lbl.setText(f"Connecté : {self._admin_email}")
        if success:
            QMessageBox.information(self, "Backup terminé", msg)
        else:
            QMessageBox.critical(self, "Erreur backup", msg)


# ---------------------------------------------------------------
# Release Worker & Dialog
# ---------------------------------------------------------------

class ReleaseWorker(QObject):
    """Exécute le pipeline de release dans un QThread séparé."""
    log      = Signal(str)
    progress = Signal(int)    # 0-100
    step     = Signal(str)    # libellé étape courante
    finished = Signal(bool, str)

    def __init__(self, version: str, action: str, parent=None):
        super().__init__(parent)
        self._version = version
        self._action  = action   # "local" | "github" | "both"
        self._m: dict = {}

    def _p(self, msg: str):
        self.log.emit(msg)

    def _prog(self, pct: int):
        self.progress.emit(pct)

    def _step(self, label: str):
        self.step.emit(label)

    def _run_cmd(self, cmd: str, allow_fail: bool = False, cwd=None) -> int:
        self._p(f">>> {cmd}")
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            cwd=str(cwd or _RELEASE_DIR),
        )
        for line in iter(proc.stdout.readline, ""):
            stripped = line.rstrip()
            if stripped:
                self._p(stripped)
        proc.wait()
        if proc.returncode != 0 and not allow_fail:
            raise RuntimeError(f"Commande échouée (code {proc.returncode}) : {cmd}")
        return proc.returncode

    def run(self):
        try:
            v = self._version
            a = self._action
            self._p(f"=== RELEASE MYSTROW v{v} ===\n")

            # Jalons de progression selon l'action
            if a == "local":
                self._m = {
                    "ver": 5, "clean": 8, "pyinst": 65,
                    "sig": 68, "inno": 92, "copy": 100,
                }
            elif a == "github":
                self._m = {
                    "ver": 5, "git_add": 15, "git_commit": 25,
                    "git_tag": 30, "git_push1": 55, "git_push2": 70,
                    "ci_start": 70, "ci_done": 100,
                }
            else:  # both
                self._m = {
                    "ver": 2, "clean": 4, "pyinst": 42,
                    "sig": 44, "inno": 56, "copy": 58,
                    "git_add": 63, "git_commit": 68, "git_tag": 71,
                    "git_push1": 80, "git_push2": 87,
                    "ci_start": 87, "ci_done": 100,
                }

            self._step("Mise à jour des versions...")
            self._p("Mise à jour des fichiers de version...")
            update_version(v)
            self._p(f"  core.py + maestro.iss → v{v}\n")
            self._prog(self._m["ver"])

            if a in ("local", "both"):
                self._build_local(v)

            if a in ("github", "both"):
                self._push_github(v)
                self._watch_actions(v)

            self._prog(100)
            self.finished.emit(True, f"Release v{v} terminée avec succès !")
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def _build_local(self, version: str):
        m = self._m
        self._p("\n========== BUILD INSTALLEUR LOCAL ==========")
        dist_exe      = _RELEASE_DIR / "dist" / "MyStrow.exe"
        installer_out = _RELEASE_DIR / "installer" / "installer_output" / "MyStrow_Setup.exe"

        # Nettoyage
        self._step("Nettoyage...")
        self._p("Nettoyage dist/ et build/...")
        for d in ("dist", "build"):
            p = _RELEASE_DIR / d
            if p.exists():
                shutil.rmtree(p)
        self._prog(m["clean"])

        # PyInstaller via .bat (contourne MINGW)
        self._step("PyInstaller (peut prendre ~2 min)...")
        self._p("\n--- PyInstaller ---")
        python_win = sys.executable.replace("/", "\\")
        base_win   = str(_RELEASE_DIR).replace("/", "\\")
        bat_path   = _RELEASE_DIR / "_build_tmp.bat"
        bat_path.write_text(
            f"@echo off\r\n"
            f"cd /d \"{base_win}\"\r\n"
            f"\"{python_win}\" -m PyInstaller "
            f"--onefile --windowed "
            f"--icon=mystrow.ico "
            f"--add-data \"logo.png;.\" "
            f"--add-data \"mystrow.ico;.\" "
            f"--hidden-import=rtmidi "
            f"--hidden-import=rtmidi._rtmidi "
            f"--collect-all rtmidi "
            f"--hidden-import=miniaudio "
            f"--name=MyStrow "
            f"--paths=\"{base_win}\" "
            f"--noconfirm main.py\r\n",
            encoding="utf-8",
        )
        bat_win = str(bat_path).replace("/", "\\")
        try:
            self._run_cmd(f'cmd.exe /c "{bat_win}"', cwd=_RELEASE_DIR)
        finally:
            bat_path.unlink(missing_ok=True)

        if not dist_exe.exists():
            raise RuntimeError("MyStrow.exe introuvable après PyInstaller.")
        self._prog(m["pyinst"])

        # Signature
        self._step("Génération .sig...")
        self._p("\nGénération du fichier .sig...")
        generate_sig_file(dist_exe)
        self._prog(m["sig"])

        # Inno Setup
        self._step("Inno Setup — packaging installeur...")
        self._p("\n--- Inno Setup ---")
        iscc_candidates = [
            Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
            Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
            Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
        ]
        iscc = next((p for p in iscc_candidates if p.exists()), None)
        if iscc is None:
            raise RuntimeError("Inno Setup (ISCC.exe) introuvable.")
        self._run_cmd(f'"{iscc}" installer\\maestro.iss', cwd=_RELEASE_DIR)
        if not installer_out.exists():
            raise RuntimeError("MyStrow_Setup.exe introuvable après Inno Setup.")
        self._prog(m["inno"])

        # Copie Bureau
        self._step("Copie sur le Bureau...")
        desktop = Path.home() / "Desktop"
        dest    = desktop / f"MyStrow_Setup_{version}.exe"
        shutil.copy2(installer_out, dest)
        self._p(f"\nInstalleur copié sur le bureau : {dest}")
        self._prog(m["copy"])

    def _push_github(self, version: str):
        m = self._m
        self._p("\n========== PUSH GITHUB ==========")

        self._step("git add...")
        self._run_cmd("git add -A", cwd=_RELEASE_DIR)
        self._prog(m["git_add"])

        self._step("git commit...")
        self._run_cmd(f'git commit -m "Release {version}"', allow_fail=True, cwd=_RELEASE_DIR)
        self._prog(m["git_commit"])

        self._step("git tag...")
        self._run_cmd(f"git tag v{version}", cwd=_RELEASE_DIR)
        self._prog(m["git_tag"])

        self._step("git push origin main...")
        self._run_cmd("git push origin main", cwd=_RELEASE_DIR)
        self._prog(m["git_push1"])

        self._step(f"git push tag v{version}...")
        self._run_cmd(f"git push origin v{version}", cwd=_RELEASE_DIR)
        self._prog(m["git_push2"])
        self._p(f"\n=== TAG v{version} POUSSÉ ===")

    def _watch_actions(self, version: str):
        from datetime import datetime as _dt
        m        = self._m
        ci_start = m["ci_start"]
        ci_done  = m["ci_done"]

        self._step("GitHub Actions — attente démarrage...")
        self._p("\nSuivi GitHub Actions (attente démarrage)...")
        run_id = None
        for _ in range(30):
            time.sleep(2)
            data = _release_gh_api("/actions/runs?event=push&per_page=10")
            if data:
                for wr in data.get("workflow_runs", []):
                    if (wr.get("name") == "Build & Release" and
                            version in wr.get("head_commit", {}).get("message", "")):
                        run_id = wr["id"]
                        break
                if not run_id:
                    for wr in data.get("workflow_runs", []):
                        if (wr.get("name") == "Build & Release" and
                                wr.get("status") in ("queued", "in_progress")):
                            run_id = wr["id"]
                            break
            if run_id:
                break
            self._p("  ...")

        if not run_id:
            self._p(f"⚠️  Workflow introuvable. Suivi manuel :\n  https://github.com/{GITHUB_REPO}/actions")
            return

        self._p(f"  Workflow : https://github.com/{GITHUB_REPO}/actions/runs/{run_id}")
        last_state: dict = {}
        ICONS   = {"queued": "⏳", "in_progress": "↻"}
        C_ICONS = {"success": "✅", "failure": "❌", "cancelled": "⚠️", "skipped": "⏭️", None: "↻"}

        while True:
            time.sleep(5)
            run_data = _release_gh_api(f"/actions/runs/{run_id}")
            if not run_data:
                continue
            status     = run_data.get("status", "")
            conclusion = run_data.get("conclusion")
            jobs_data  = _release_gh_api(f"/actions/runs/{run_id}/jobs")
            jobs       = (jobs_data or {}).get("jobs", [])
            cur_state  = {j["name"]: (j["status"], j.get("conclusion")) for j in jobs}

            if cur_state != last_state:
                done_count = sum(1 for j in jobs if j["status"] == "completed")
                total      = max(len(jobs), 1)
                ci_pct     = ci_start + int((ci_done - ci_start) * done_count / total)
                self._prog(ci_pct)
                self._step(f"GitHub Actions — {done_count}/{total} jobs terminés")
                lines = []
                for job in jobs:
                    js   = job["status"]
                    jc   = job.get("conclusion")
                    icon = C_ICONS.get(jc, "❓") if js == "completed" else ICONS.get(js, "⏳")
                    dur  = ""
                    if js == "completed" and job.get("started_at") and job.get("completed_at"):
                        t1   = _dt.fromisoformat(job["started_at"].replace("Z", "+00:00"))
                        t2   = _dt.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
                        secs = int((t2 - t1).total_seconds())
                        dur  = f"  ({secs // 60}m{secs % 60:02d}s)"
                    lines.append(f"  {icon}  {job['name']}{dur}")
                self._p("\n".join(lines))
                last_state = cur_state

            if status == "completed":
                if conclusion == "success":
                    self._p(f"\n✅  Release v{version} créée !")
                    self._p(f"    https://github.com/{GITHUB_REPO}/releases/tag/v{version}")
                else:
                    self._p(f"\n❌  Build échoué ({conclusion})")
                    self._p(f"    https://github.com/{GITHUB_REPO}/actions/runs/{run_id}")
                break


# ---------------------------------------------------------------
# Backup helpers
# ---------------------------------------------------------------

_BACKUP_EXCLUDE = {"dist", "build", "__pycache__", ".git", ".mypy_cache", ".pytest_cache"}


_BACKUP_PREFS = Path.home() / ".mystrow_backup_prefs.json"

def _backup_dest_load() -> Path | None:
    """Charge le dossier de backup personnalisé sauvegardé."""
    try:
        import json
        data = json.loads(_BACKUP_PREFS.read_text())
        p = Path(data.get("backup_dest", ""))
        return p if p and p.exists() else None
    except Exception:
        return None

def _backup_dest_save(path_str: str):
    """Persiste le dossier de backup choisi."""
    try:
        import json
        _BACKUP_PREFS.write_text(json.dumps({"backup_dest": path_str}))
    except Exception:
        pass


def _find_google_drive() -> Path | None:
    """
    Cherche le dossier Google Drive sur Windows.
    1. Registre HKCU\\Software\\Google\\DriveFS  (Google Drive for Desktop)
    2. Scan de toutes les lettres de lecteur pour 'Mon Drive' / 'My Drive'
    3. Chemins classiques dans le dossier utilisateur
    """
    import string

    # ── 1. Registre Google Drive for Desktop ────────────────────────────────
    try:
        import winreg
        key_path = r"Software\Google\DriveFS\PerAccountPreferences"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            i = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, sub_name) as sub:
                        mount, _ = winreg.QueryValueEx(sub, "mount_point_path")
                        p = Path(mount)
                        if p.exists():
                            return p
                except OSError:
                    break
                i += 1
    except Exception:
        pass

    # ── 2. Scan de toutes les lettres de lecteur ─────────────────────────────
    for letter in string.ascii_uppercase:
        for sub in ("Mon Drive", "My Drive", ""):
            p = Path(f"{letter}:\\") / sub if sub else Path(f"{letter}:\\")
            try:
                # Vérifier que c'est bien un lecteur Google Drive (présence metadata)
                marker = Path(f"{letter}:\\") / ".metadata_never_index"
                drive_root = Path(f"{letter}:\\")
                if drive_root.exists():
                    # Google Drive for Desktop laisse souvent un dossier "Mon Drive" ou "My Drive"
                    for name in ("Mon Drive", "My Drive"):
                        candidate = drive_root / name
                        if candidate.exists() and candidate.is_dir():
                            return candidate
            except Exception:
                pass

    # ── 3. Chemins classiques utilisateur ────────────────────────────────────
    for p in [
        Path.home() / "Google Drive" / "Mon Drive",
        Path.home() / "Google Drive" / "My Drive",
        Path.home() / "Google Drive",
        Path.home() / "Mon Drive",
        Path.home() / "My Drive",
    ]:
        if p.exists() and p.is_dir():
            return p

    return None


class BackupWorker(QObject):
    finished = Signal(bool, str)   # success, message
    progress = Signal(str)         # step message

    def __init__(self, src_dir: Path, dest_dir: Path, gdrive_dir: Path | None = None):
        super().__init__()
        self._src = src_dir
        self._dest = dest_dir
        self._gdrive = gdrive_dir

    def run(self):
        try:
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
            zip_name = f"MyStrow_Backup_{ts}.zip"
            zip_path = self._dest / zip_name

            self.progress.emit(f"Création du zip : {zip_name} …")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for item in self._src.rglob("*"):
                    # Exclure les dossiers inutiles
                    parts = set(item.relative_to(self._src).parts)
                    if parts & _BACKUP_EXCLUDE:
                        continue
                    if item.is_file():
                        zf.write(item, item.relative_to(self._src))

            size_mb = zip_path.stat().st_size / (1024 * 1024)
            msg = f"Backup créé : {zip_path}\n({size_mb:.1f} Mo)"

            if self._gdrive:
                self.progress.emit("Copie vers Google Drive …")
                gdrive_path = self._gdrive / zip_name
                shutil.copy2(zip_path, gdrive_path)
                msg += f"\n\nCopié dans Google Drive :\n{gdrive_path}"

            self.finished.emit(True, msg)
        except Exception as e:
            self.finished.emit(False, str(e))


class ReleaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Release MyStrow")
        self.setMinimumSize(720, 580)
        self._thread = None
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(10)

        title = QLabel("Release MyStrow")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT};")
        lay.addWidget(title)

        # Version
        v_lay = QHBoxLayout()
        current = get_current_version() or "?"
        v_lay.addWidget(QLabel(f"Version actuelle :  <b>{current}</b>", textFormat=Qt.RichText))
        v_lay.addSpacing(24)
        v_lay.addWidget(QLabel("Nouvelle version :"))
        self.version_edit = QLineEdit(bump_version(current) if current != "?" else "")
        self.version_edit.setFixedWidth(110)
        self.version_edit.setMinimumHeight(32)
        v_lay.addWidget(self.version_edit)
        v_lay.addStretch()
        lay.addLayout(v_lay)

        # Action
        a_lay = QHBoxLayout()
        a_lay.addWidget(QLabel("Action :"))
        self.action_combo = QComboBox()
        self.action_combo.addItem("Push GitHub", "github")
        self.action_combo.addItem("Version Install Bureau", "local")
        self.action_combo.addItem("Les 2", "both")
        self.action_combo.setMinimumWidth(340)
        a_lay.addWidget(self.action_combo)
        a_lay.addStretch()
        lay.addLayout(a_lay)

        self._mac_note = QLabel("ℹ️  Mac : uniquement buildé par GitHub CI — impossible depuis Windows.")
        self._mac_note.setStyleSheet("color: #555; font-size: 10px; padding-left: 2px;")
        self._mac_note.setVisible(False)
        lay.addWidget(self._mac_note)
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)

        # Boutons
        btns = QHBoxLayout()
        self.btn_start = QPushButton("Lancer la release")
        self.btn_start.setStyleSheet(_BTN_PRIMARY)
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._on_start)
        btns.addWidget(self.btn_start)
        self.btn_close = QPushButton("Fermer")
        self.btn_close.setStyleSheet(_BTN_SECONDARY)
        self.btn_close.setFixedHeight(36)
        self.btn_close.clicked.connect(self.accept)
        btns.addWidget(self.btn_close)
        btns.addStretch()
        btn_gh = QPushButton("GitHub Actions →")
        btn_gh.setStyleSheet(_BTN_SECONDARY)
        btn_gh.setFixedHeight(36)
        btn_gh.setToolTip("Ouvre GitHub Actions dans le navigateur")
        btn_gh.clicked.connect(lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}/actions"))
        btns.addWidget(btn_gh)
        lay.addLayout(btns)

        # Barre de progression
        prog_lay = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: #222;
                border: none;
                border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT}, stop:1 #0088aa
                );
                border-radius: 5px;
            }}
        """)
        self.pct_label = QLabel("0 %")
        self.pct_label.setFixedWidth(38)
        self.pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pct_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        prog_lay.addWidget(self.progress_bar)
        prog_lay.addSpacing(6)
        prog_lay.addWidget(self.pct_label)
        lay.addLayout(prog_lay)

        # Étape courante
        self.step_label = QLabel("")
        self.step_label.setFont(QFont("Segoe UI", 9))
        self.step_label.setStyleSheet(f"color: {TEXT_DIM};")
        lay.addWidget(self.step_label)

        # Log
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 9))
        self.log_edit.setStyleSheet(
            "QTextEdit {"
            f"  background: #0d0d0d; color: #cccccc;"
            f"  border: 1px solid #333; border-radius: 4px;"
            "}"
        )
        lay.addWidget(self.log_edit)

    def _on_action_changed(self, index):
        action = self.action_combo.itemData(index)
        self._mac_note.setVisible(action == "local")

    def _on_start(self):
        version = self.version_edit.text().strip()
        if not version:
            QMessageBox.warning(self, "Version manquante", "Veuillez saisir un numéro de version.")
            return
        action = self.action_combo.currentData()
        self.btn_start.setEnabled(False)
        self.btn_start.setText("En cours…")
        self.log_edit.clear()
        self.progress_bar.setValue(0)
        self.pct_label.setText("0 %")
        self.step_label.setText("")

        self._thread = QThread(self)
        self._worker = ReleaseWorker(version, action)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.step.connect(self.step_label.setText)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_progress(self, pct: int):
        self.progress_bar.setValue(pct)
        self.pct_label.setText(f"{pct} %")

    def _append_log(self, text: str):
        self.log_edit.append(text)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, success: bool, msg: str):
        self.btn_start.setEnabled(True)
        self.btn_start.setText("Lancer la release")
        if success:
            self._on_progress(100)
            self.step_label.setText("Terminé !")
            self.step_label.setStyleSheet("color: #4CAF50; font-size: 9px;")
            self._append_log(f"\n{msg}")
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        else:
            self.step_label.setText("Erreur")
            self.step_label.setStyleSheet(f"color: {RED}; font-size: 9px;")
            self._append_log(f"\nERREUR : {msg}")
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONHAND)
            except Exception:
                pass
            QMessageBox.critical(self, "Erreur release", msg)


# ---------------------------------------------------------------
# Démarrage / login flow
# ---------------------------------------------------------------

def _show_login_then_panel():
    """Affiche LoginDialog puis AdminPanel. Quitte si annulé."""
    app = QApplication.instance()
    if app:
        app.setQuitOnLastWindowClosed(False)

    dlg = LoginDialog()
    result = dlg.exec()

    if app:
        app.setQuitOnLastWindowClosed(True)

    if result != QDialog.Accepted:
        if app:
            app.quit()
        return

    panel = AdminPanel(dlg.id_token, dlg.refresh_token, dlg.email)
    panel.show()
    if app:
        app._admin_panel = panel  # Prevent garbage collection


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("MyStrow Admin")
    app.setStyleSheet(STYLE_APP)

    # Tenter de restaurer la session depuis le cache
    id_token = refresh_token = admin_email = None
    cache = _load_admin_cache()
    if cache.get("refresh_token"):
        try:
            tok          = fc.refresh_id_token(cache["refresh_token"])
            id_token     = tok["id_token"]
            refresh_token = tok.get("refresh_token", cache["refresh_token"])
            admin_email  = cache.get("email", "")
            _save_admin_cache(admin_email, refresh_token)
        except Exception:
            pass

    if id_token:
        panel = AdminPanel(id_token, refresh_token, admin_email)
        panel.show()
        app._admin_panel = panel
    else:
        _show_login_then_panel()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
