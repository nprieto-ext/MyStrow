"""
Boîtier MyStrow maison reconnu au branchement → proposition d'activer sa licence.

Le firmware publie comme numéro de série USB un identifiant de 12 chiffres
hexadécimaux dérivé de l'UID de la puce (firmware/usb_desc.c). On le lit dans
la liste des ports, sans ouvrir le port : la sortie DMX peut le tenir.
tools/initialiser_boitier.py a associé cet identifiant au numéro gravé du boîtier.

Seule l'IDENTITÉ vient du boîtier : la durée offerte et l'état d'activation sont
demandés au serveur (`boitier_detect`). Un périphérique USB peut déclarer
n'importe quoi, l'app ne le croit jamais sur parole.

On ne propose QUE ce que l'utilisateur confirme : un boîtier prêté et branché
chez un ami ne doit pas activer sa licence sur le compte de l'ami (un boîtier
MS-DMY ne s'active qu'une fois).
"""

import json
import threading
import time
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import (QApplication, QMessageBox, QInputDialog,
                               QLineEdit)

from core import FIREBASE_PROJECT_ID, make_ssl_context
from i18n import tr, get_language

_VID, _PID = 0x1A86, 0x5740
_FN_BASE = f"https://us-central1-{FIREBASE_PROJECT_ID}.cloudfunctions.net"
_DETECT_URL = f"{_FN_BASE}/boitier_detect"
_ACTIVATE_URL = f"{_FN_BASE}/activate_code"
_SCAN_MS = 10_000
# Serveur injoignable : on retente, mais pas à chaque scan — la limite de débit
# de boitier_detect est partagée avec la page /activate (8 essais / 15 min).
_RETRY_S = 300

_SSL_CTX = make_ssl_context()


def _post(url: str, payload: dict, token: str | None = None,
          timeout: int = 15) -> dict:
    """POST JSON → dict. Une réponse d'erreur HTTP est rendue telle quelle
    (le serveur y met `error`) ; seul un serveur muet lève une exception."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "error": f"http_{e.code}"}


def _usb_ids() -> set[str]:
    try:
        from serial.tools import list_ports
        return {(p.serial_number or "").upper()
                for p in list_ports.comports()
                if p.vid == _VID and p.pid == _PID and p.serial_number}
    except Exception:
        return set()


def _account_email() -> str:
    from license_manager import get_license_info
    email = get_license_info().get("email") or ""
    return email if "@" in email else ""


class BoitierDetector(QObject):
    """Scanne les ports toutes les 10 s ; un boîtier libre → une proposition.

    Chaque identifiant n'est soumis au serveur qu'une fois par session (sauf
    échec réseau) : « Plus tard » ne repropose qu'au prochain lancement.
    """

    _found = Signal(dict)

    def __init__(self, window):
        super().__init__(window)
        self._win = window
        self._seen: set[str] = set()
        self._retry_at: dict[str, float] = {}
        self._pending: list[dict] = []
        self._busy = False
        self._found.connect(self._on_found)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        QTimer.singleShot(4000, self._tick)
        self._timer.start(_SCAN_MS)

    # ------------------------------------------------------------ thread de fond
    def _tick(self):
        self._show_pending()
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            now = time.time()
            new = [u for u in _usb_ids()
                   if u not in self._seen and self._retry_at.get(u, 0) <= now]
            if not new:
                return
            from license_manager import get_current_id_token
            token = get_current_id_token()
            for usb_id in new:
                try:
                    rep = _post(_DETECT_URL, {"usb_id": usb_id}, token)
                except Exception as e:
                    print(f"[BOITIER] {usb_id} : serveur injoignable ({e})")
                    self._retry_at[usb_id] = now + _RETRY_S
                    continue
                if not rep.get("ok"):
                    print(f"[BOITIER] {usb_id} : {rep.get('error')}")
                    self._retry_at[usb_id] = now + _RETRY_S
                    continue
                self._seen.add(usb_id)
                rep["usb_id"] = usb_id
                print(f"[BOITIER] {usb_id} : {rep}")
                if (rep.get("known") and rep.get("status") == "free"
                        and int(rep.get("months") or 0) > 0 and rep.get("serial")):
                    self._found.emit(rep)
        finally:
            self._busy = False

    # ------------------------------------------------------------ thread GUI
    def _on_found(self, rep: dict):
        self._pending.append(rep)
        self._show_pending()

    def _show_pending(self):
        # Jamais par-dessus une autre fenêtre modale (licence, assistant…) :
        # la proposition attend le scan suivant.
        if not self._pending or QApplication.activeModalWidget() is not None:
            return
        self._propose(self._pending.pop(0))

    def _propose(self, rep: dict):
        serial, months = rep["serial"], int(rep["months"])
        offer = tr("bx_offer", serial=serial, months=months)
        email = _account_email()
        logged = bool(email)

        if logged:
            box = QMessageBox(self._win)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle(tr("bx_title"))
            box.setText(offer)
            box.setInformativeText(tr("bx_ask_logged", email=email))
            btn_ok = box.addButton(tr("bx_btn_activate"), QMessageBox.AcceptRole)
            box.addButton(tr("bx_btn_later"), QMessageBox.RejectRole)
            box.setDefaultButton(btn_ok)
            box.exec()
            if box.clickedButton() is not btn_ok:
                return
        else:
            while True:
                email, ok = QInputDialog.getText(
                    self._win, tr("bx_title"),
                    offer + "\n\n" + tr("bx_ask_email"),
                    QLineEdit.Normal, email)
                if not ok:
                    return
                email = email.strip().lower()
                if "@" in email and "." in email.rsplit("@", 1)[-1]:
                    break
                QMessageBox.warning(self._win, tr("bx_title"), tr("bx_bad_email"))

        self._activate(rep["usb_id"], serial, email, logged)

    def _activate(self, usb_id: str, serial: str, email: str, logged: bool):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rep = _post(_ACTIVATE_URL, {"email": email, "serial": serial,
                                        "lang": get_language()})
        except Exception as e:
            print(f"[BOITIER] activation {serial} : serveur injoignable ({e})")
            rep = {"ok": False, "error": "network"}
        finally:
            QApplication.restoreOverrideCursor()

        if not rep.get("ok"):
            err = rep.get("error")
            print(f"[BOITIER] activation {serial} refusée : {err} {rep.get('message', '')}")
            msg = {"serial_used": tr("bx_err_used"),
                   "already_lifetime": tr("bx_err_lifetime")}.get(err, tr("bx_err_generic"))
            if err == "already_yours":
                msg = None          # rien à refaire : la licence est en place
            if msg:
                QMessageBox.warning(self._win, tr("bx_title"), msg)
            if err in ("network", "server", "throttled"):
                # Le boîtier reste libre : le reproposer au prochain scan utile.
                self._seen.discard(usb_id)
            return

        date = rep.get("expiry_label") or ""
        print(f"[BOITIER] {serial} activé sur {email} jusqu'au {date}")
        if logged:
            QMessageBox.information(self._win, tr("bx_title"), tr("bx_ok", date=date))
            self._win._on_activation_success(silent=True)
        else:
            QMessageBox.information(self._win, tr("bx_title"),
                                    tr("bx_ok_login", email=email, date=date))
            self._win._open_activation_dialog()
