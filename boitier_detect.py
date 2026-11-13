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
import os
import threading
import time
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication

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
    except ImportError:
        if not getattr(_usb_ids, "_warned", False):
            _usb_ids._warned = True
            print("[BOITIER] pyserial absent : détection des boîtiers impossible")
        return set()
    try:
        return {(p.serial_number or "").upper()
                for p in list_ports.comports()
                if p.vid == _VID and p.pid == _PID and p.serial_number}
    except Exception:
        return set()


# Boîtiers pour lesquels l'utilisateur a dit « Ne plus me le proposer »
# (prêté, branché chez un ami…). Propre à ce PC, par identifiant USB.
_DISMISS_PATH = os.path.join(os.path.expanduser("~"), ".mystrow_boitiers_ignores.json")


def _load_dismissed() -> set[str]:
    try:
        with open(_DISMISS_PATH, encoding="utf-8") as f:
            return {str(u).upper() for u in json.load(f)}
    except Exception:
        return set()


def _save_dismissed(ids: set[str]) -> None:
    try:
        with open(_DISMISS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(ids), f)
    except Exception as e:
        print(f"[BOITIER] choix « ne plus proposer » non enregistré : {e}")


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
    _nothing = Signal(str)      # vérification à la demande sans boîtier libre

    def __init__(self, window):
        super().__init__(window)
        self._win = window
        self._seen: set[str] = set()
        self._retry_at: dict[str, float] = {}
        self._pending: list[dict] = []
        self._busy = False
        self._dismissed = _load_dismissed()
        # « J'ai déjà un boîtier » (menu À propos) : on ignore le « ne plus
        # proposer » le temps de la session.
        self._want_any = False
        self._found.connect(self._on_found)
        self._nothing.connect(self._on_nothing)
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

    def check_now(self):
        """Bouton « Activer le boîtier branché » de la fenêtre licence : on
        réinterroge le serveur pour tout boîtier branché, même déjà vu ou
        écarté par « Ne plus me le proposer »."""
        if self._busy:
            QTimer.singleShot(500, self.check_now)
            return
        self._busy = True
        threading.Thread(target=self._work, args=(True,), daemon=True).start()

    def want_any(self):
        self._want_any = True

    def _license_active(self) -> bool:
        from license_manager import LicenseState
        lic = getattr(self._win, "_license", None)
        return getattr(lic, "state", None) == LicenseState.LICENSE_ACTIVE

    def _work(self, force: bool = False):
        try:
            now = time.time()
            ids = _usb_ids()
            if force:
                new = sorted(ids)
                if not new:
                    self._nothing.emit("none")
                    return
            else:
                # « Ne plus me le proposer » ne tient que tant que le compte a
                # une licence active : sans licence, l'activer est dans son
                # intérêt, la carte revient.
                skip = (self._dismissed
                        if self._license_active() and not self._want_any
                        else set())
                new = [u for u in ids
                       if u not in self._seen and u not in skip
                       and self._retry_at.get(u, 0) <= now]
            if not new:
                return
            from license_manager import get_current_id_token
            token = get_current_id_token()
            statuses, found = [], False
            for usb_id in new:
                try:
                    rep = _post(_DETECT_URL, {"usb_id": usb_id}, token)
                except Exception as e:
                    print(f"[BOITIER] {usb_id} : serveur injoignable ({e})")
                    self._retry_at[usb_id] = now + _RETRY_S
                    statuses.append("network")
                    continue
                if not rep.get("ok"):
                    print(f"[BOITIER] {usb_id} : {rep.get('error')}")
                    self._retry_at[usb_id] = now + _RETRY_S
                    statuses.append("network")
                    continue
                self._seen.add(usb_id)
                rep["usb_id"] = usb_id
                if rep.get("known") and rep.get("status") == "yours":
                    # Son boîtier : lève la limite de jours hors-ligne.
                    from license_manager import remember_boitier_usb
                    remember_boitier_usb(usb_id)
                rep["forced"] = force
                print(f"[BOITIER] {usb_id} : {rep}")
                if (rep.get("known") and rep.get("status") == "free"
                        and int(rep.get("months") or 0) > 0 and rep.get("serial")):
                    self._found.emit(rep)
                    found = True
                else:
                    statuses.append(rep.get("status") if rep.get("known") else "unknown")
            if force and not found:
                # Le plus parlant d'abord : « déjà à vous » > à vie > autre.
                for st in ("yours", "lifetime", "other", "network"):
                    if st in statuses:
                        self._nothing.emit(st)
                        break
                else:
                    self._nothing.emit("none")
        finally:
            self._busy = False

    # ------------------------------------------------------------ thread GUI
    def _on_found(self, rep: dict):
        self._pending.append(rep)
        self._show_pending()

    def _on_nothing(self, status: str):
        from PySide6.QtWidgets import QMessageBox
        key = {"yours": "bx_already_yours", "lifetime": "bx_err_lifetime",
               "other": "bx_err_used", "network": "bx_err_generic"}.get(
                   status, "bx_none_free")
        QMessageBox.information(self._win, tr("bx_title"), tr(key))

    def _show_pending(self):
        # Jamais par-dessus une autre fenêtre modale (licence, assistant…) :
        # la proposition attend le scan suivant.
        if not self._pending or QApplication.activeModalWidget() is not None:
            return
        self._propose(self._pending.pop(0))

    def _propose(self, rep: dict):
        """Carte « Boîtier détecté » posée SUR la fenêtre MyStrow (même écran,
        modale : rien d'autre n'est cliquable tant qu'on n'a pas répondu).
        Toute l'activation s'y déroule : question → « Activation… » → résultat."""
        from boitier_card import BoitierCard
        serial, months = rep["serial"], int(rep["months"])
        email = _account_email()
        logged = bool(email)

        card = BoitierCard(self._win, serial, months,
                           ask=tr("bx_ask_logged", email=email) if logged
                           else tr("bx_ask_email"),
                           email_field=not logged,
                           # Demandée à la main : pas de « ne plus proposer ».
                           can_dismiss=not rep.get("forced"))

        def on_activate(entered: str):
            mail = email if logged else entered.strip().lower()
            if not logged and not ("@" in mail and "." in mail.rsplit("@", 1)[-1]):
                card.show_error(tr("bx_bad_email"))
                return
            card.show_busy(tr("bx_activating"))
            threading.Thread(target=lambda: card.done.emit(
                self._call_activate(serial, mail)), daemon=True).start()
            card._mail = mail

        result = {}

        def on_done(rep_act: dict):
            result["rep"] = rep_act
            ok, msg = self._outcome(rep_act, logged, card._mail)
            if ok or (msg is None and rep_act.get("error") == "already_yours"):
                # Licence OK : la sortie DMX part aussitôt sur ce boîtier,
                # plus besoin de passer par la fenêtre Sortie DMX.
                port = self._connecter_dmx(rep["usb_id"])
                if ok and port:
                    msg += "

" + tr("bx_dmx_connected")
            if ok:
                card.show_success(msg)
            elif msg is None:          # already_yours : rien à refaire
                card.close_animated()
            else:
                card.show_error(msg, final=True)

        card.activate.connect(on_activate)
        card.done.connect(on_done)
        card.exec()

        if card.dismissed:
            self._dismissed.add(rep["usb_id"])
            _save_dismissed(self._dismissed)
            print(f"[BOITIER] {rep['usb_id']} : ne plus proposer (sur ce PC)")
        elif rep["usb_id"] in self._dismissed and result.get("rep", {}).get("ok"):
            self._dismissed.discard(rep["usb_id"])
            _save_dismissed(self._dismissed)

        rep_act = result.get("rep")
        if not rep_act:
            return
        if not rep_act.get("ok"):
            if rep_act.get("error") in ("network", "server", "throttled"):
                # Le boîtier reste libre : le reproposer au prochain scan utile.
                self._seen.discard(rep["usb_id"])
            return
        if logged:
            self._win._on_activation_success(silent=True)
        else:
            self._win._open_activation_dialog()

    def _connecter_dmx(self, usb_id: str):
        try:
            from node_connection import connecter_boitier_maison
            port = connecter_boitier_maison(getattr(self._win, "dmx", None), usb_id)
            if port:
                print(f"[BOITIER] sortie DMX branchée sur {port}")
                if hasattr(self._win, "_refresh_dmx_menu_title"):
                    self._win._refresh_dmx_menu_title()
            return port
        except Exception as e:
            print(f"[BOITIER] sortie DMX non branchée : {e}")
            return None

    @staticmethod
    def _call_activate(serial: str, email: str) -> dict:
        try:
            return _post(_ACTIVATE_URL, {"email": email, "serial": serial,
                                         "lang": get_language()})
        except Exception as e:
            print(f"[BOITIER] activation {serial} : serveur injoignable ({e})")
            return {"ok": False, "error": "network"}

    @staticmethod
    def _outcome(rep: dict, logged: bool, email: str):
        """→ (succès, message à afficher ; None = fermer sans rien dire)."""
        if rep.get("ok"):
            date = rep.get("expiry_label") or ""
            print(f"[BOITIER] {rep.get('serial', '')} activé sur {email} jusqu'au {date}")
            msg = (tr("bx_ok", date=date) if logged
                   else tr("bx_ok_login", email=email, date=date))
            if rep.get("billing_resumes_label"):
                # Abonné Stripe : ses prélèvements reprennent à la fin de
                # l'année offerte, pas avant (cf. _boitier_suspendre_abo).
                msg += "\n\n" + tr("bx_billing_resumes",
                                     date=rep["billing_resumes_label"])
            return True, msg
        err = rep.get("error")
        print(f"[BOITIER] activation refusée : {err} {rep.get('message', '')}")
        if err == "already_yours":
            return False, None
        return False, {"serial_used": tr("bx_err_used"),
                       "already_lifetime": tr("bx_err_lifetime")}.get(
                           err, tr("bx_err_generic"))
