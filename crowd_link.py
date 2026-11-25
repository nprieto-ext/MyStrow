"""crowd_link.py — MyStrow Up : les téléphones du public deviennent des projecteurs.

L'utilisateur ajoute dans son patch DMX la fixture « MyStrow Up · Téléphones du
public » (fabricant MyStrow Up, cf. builtin_fixtures.py), dans le groupe de son
choix, comme un PAR. Chaque MyStrow Up du patch est une ZONE de la salle : les
téléphones sont répartis équitablement entre les zones. On lit la couleur
EFFECTIVE de chaque fixture (`proj.color` : niveau, pads, effets, mémoires…) et
son strobe : le public suit son groupe comme n'importe quel projecteur. La
fixture est virtuelle : rien ne sort en DMX (artnet_dmx la saute).

Transport : WebSocket vers le relais (crowd/relay_server.py). Le relais horodate
chaque état et le rediffuse ; les téléphones l'appliquent tous à la même heure.

Textes de l'appli : i18n.py (clés up_*). Page des téléphones : crowd/phone.html,
dans la langue du téléphone de chaque spectateur.
"""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtGui import QImage, QPixmap, QColor, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QWidget)

from i18n import tr

# Nom interne du groupe → lettre AKAI (même table que main_window.AKAI_GROUP_MAP),
# pour dire à l'utilisateur dans quels groupes sont ses MyStrow Up.
LETTRE_GROUPE = {"face": "A", "lat": "B", "contre": "C", "douche1": "D",
                 "douche2": "E", "douche3": "F", "groupe_g": "G", "groupe_h": "H"}
MYSTROW_UP_FABRICANT = "MyStrow Up"   # fixture du patch (builtin_fixtures.py)


def est_mystrow_up(proj) -> bool:
    """Projecteur « MyStrow Up » du patch (virtuel : téléphones du public)."""
    return getattr(proj, "manufacturer", "") == MYSTROW_UP_FABRICANT


FPS = 25
KEEPALIVE_S = 1.0
SERVEUR_PROD = "https://live.mystrow.fr"   # Hetzner CPX02 Helsinki (37.27.153.144)
URL_TICKET = "https://us-central1-mystrow-907be.cloudfunctions.net/up_ticket"
CAP_ESSAI, CAP_LICENCE = 1, 50   # essai = aperçu sur 1 téléphone (25/11/2026)   # rappel affiché ; c'est le SERVEUR qui fait foi


FICHIER_UP = Path.home() / ".mystrow_up.json"   # code du QR permanent (licence)


def sid_fixe_memorise() -> str:
    try:
        return str(json.loads(FICHIER_UP.read_text(encoding="utf-8")).get("sid_fixe") or "")
    except (OSError, ValueError):
        return ""


def _memoriser_sid_fixe(sid: str):
    try:
        FICHIER_UP.write_text(json.dumps({"sid_fixe": sid}), encoding="utf-8")
    except OSError:
        pass


REFUS_COMPTE, REFUS_LICENCE, REFUS_RESEAU = "compte", "licence", "reseau"
_CLES_REFUS = {REFUS_COMPTE: "up_refus_compte", REFUS_LICENCE: "up_refus_licence",
               REFUS_RESEAU: "up_refus_reseau"}


def message_refus(refus: str) -> str:
    return tr(_CLES_REFUS.get(refus, "up_refus_reseau"))


def obtenir_ticket() -> tuple[str, int, str]:
    """Ticket signé par la Cloud Function up_ticket (licence vérifiée dans
    Firestore) → (ticket, plafond, refus). Licence payée → 50 + code du QR
    PERMANENT (mémorisé pour télécharger le QR sans session ni réseau) ;
    compte en essai → 1 (aperçu). Sans compte, essai expiré ou erreur : pas de ticket,
    et le relais refuse toute session sans ticket. `refus` dit pourquoi."""
    try:
        import firebase_client as fc
        import license_manager as lm
        compte = lm._load_account(lm.get_machine_id()) or {}
        if not compte.get("refresh_token"):
            _memoriser_sid_fixe("")
            return "", 0, REFUS_COMPTE
        jeton = fc.refresh_id_token(compte["refresh_token"])["id_token"]
        # Jeton dans le corps : l'en-tête Authorization n'arrive pas intact à la
        # fonction (Cloud Run), comme pour create_portal_session.
        req = urllib.request.Request(URL_TICKET, method="POST",
                                     data=json.dumps({"id_token": jeton}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            rep = json.loads(r.read().decode())
        _memoriser_sid_fixe(str(rep.get("sid") or ""))
        return rep.get("ticket", ""), int(rep.get("cap", CAP_ESSAI)), ""
    except urllib.error.HTTPError as e:
        print(f"[Up] ticket refusé (HTTP {e.code})")
        if e.code == 403:
            _memoriser_sid_fixe("")
            return "", 0, REFUS_LICENCE
        return "", 0, REFUS_COMPTE if e.code == 401 else REFUS_RESEAU
    except Exception as e:
        print(f"[Up] ticket non obtenu ({e})")
        return "", 0, REFUS_RESEAU


def droit_refuse(window) -> str:
    """Message si la licence interdit MyStrow Up (essai ou licence expirés),
    sinon "". Contrôle côté PC ; le serveur, lui, refuse toute session sans ticket."""
    try:
        from license_manager import LicenseState
        etat = getattr(getattr(window, "_license", None), "state", None)
        if etat in (LicenseState.TRIAL_EXPIRED, LicenseState.LICENSE_EXPIRED,
                    LicenseState.INVALID, LicenseState.NOT_ACTIVATED,
                    LicenseState.FRAUD_CLOCK):
            return tr("up_droit")
    except Exception:
        pass
    return ""


def ip_locale() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def qr_image(texte: str, taille: int) -> QImage:
    """QR code dessiné depuis la matrice (pas besoin de Pillow), logo MyStrow
    au centre. Correction d'erreur H (30 %) : le logo masque ~5 % des modules,
    le QR reste lisible même abîmé ou filmé de loin."""
    import qrcode
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_H)
    q.add_data(texte)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    petit = QImage(n, n, QImage.Format_RGB32)
    noir, blanc = QColor(0, 0, 0).rgb(), QColor(255, 255, 255).rgb()
    for y, ligne in enumerate(m):
        for x, v in enumerate(ligne):
            petit.setPixel(x, y, noir if v else blanc)
    # Taille multiple du nombre de modules : des carrés nets, sans flou.
    cote = max(n, (taille // n) * n)
    img = petit.scaled(cote, cote, Qt.KeepAspectRatio, Qt.FastTransformation)

    try:
        from core import resource_path
        logo = QImage(resource_path("logo.png"))
    except Exception:
        logo = QImage()
    if not logo.isNull():
        from PySide6.QtGui import QPainter
        from PySide6.QtCore import QRectF
        cl = int(cote * 0.22)                   # cadre blanc ≈ 22 % du QR
        x0 = y0 = (cote - cl) / 2
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawRoundedRect(QRectF(x0, y0, cl, cl), cl * 0.18, cl * 0.18)
        marge = cl * 0.10
        p.drawImage(QRectF(x0 + marge, y0 + marge, cl - 2 * marge, cl - 2 * marge), logo)
        p.end()
    return img


def qr_pixmap(texte: str, taille: int) -> QPixmap:
    return QPixmap.fromImage(qr_image(texte, taille))


class CrowdLink(QObject):
    session_prete = Signal(str)        # sid
    qr_connu = Signal()                # code du QR permanent récupéré
    refuse = Signal(str)               # session impossible (message)
    compte = Signal(int, int)          # connectés, plafond
    statut = Signal(str)
    _ticket_recu = Signal(int, str, int, str)   # gen, ticket, plafond, refus (depuis le fil)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        # Pas modifiable par l'utilisateur. Tests en local seulement :
        # variable d'environnement MYSTROW_UP_SERVEUR=http://<ip du PC>:8765
        self.serveur = os.environ.get("MYSTROW_UP_SERVEUR", "").strip() or SERVEUR_PROD
        self.sid = ""
        self._ctok = ""        # jeton pour reprendre la session après une coupure
        self.cap = CAP_ESSAI
        self.refus = ""        # "" = inconnu ou OK ; sinon REFUS_COMPTE / LICENCE / RESEAU
        self._gen = 0          # n° de la session en cours (signaux des anciennes ignorés)
        self.refuse.connect(self._sur_refus)
        self._fenetre_qr = None
        self._n_journal = 0
        self._dernier_statut = ""
        self.session_prete.connect(self._sur_session)
        self.compte.connect(self._sur_compte)
        self.statut.connect(self._sur_statut)
        self._ws = None        # QWebSocket de la session en cours
        self._ticket = ""
        self._essais = 0
        self._ticket_recu.connect(self._sur_ticket)
        self._actif = False
        self._dernier = None
        self._dernier_envoi = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._tick)

    # ── Config ──────────────────────────────────────────────────────────────
    def to_config(self) -> dict:
        return {}

    def from_config(self, cfg: dict):
        pass

    def url_public(self) -> str:
        return f"{self.serveur.rstrip('/')}/live/{self.sid}" if self.sid else ""

    def url_qr(self) -> str:
        """QR à montrer / télécharger : celui de la session en cours, sinon le
        QR PERMANENT de la licence (connu même sans session)."""
        sid = self.sid or sid_fixe_memorise()
        return f"{self.serveur.rstrip('/')}/live/{sid}" if sid else ""

    def qr_permanent(self) -> bool:
        fixe = sid_fixe_memorise()
        return bool(fixe) and (not self.sid or self.sid == fixe)

    @property
    def actif(self) -> bool:
        return self._actif

    # ── Zones = fixtures « MyStrow Up » du patch ────────────────────────────
    def fixtures_up(self) -> list:
        return [p for p in (getattr(self.window, "projectors", []) or []) if est_mystrow_up(p)]

    def groupes_up(self) -> str:
        """« G » ou « A, G » : groupes qui contiennent des MyStrow Up."""
        vus = []
        for p in self.fixtures_up():
            g = LETTRE_GROUPE.get(getattr(p, "group", ""), str(getattr(p, "group", "?")))
            if g not in vus:
                vus.append(g)
        return ", ".join(vus)

    def zones(self) -> list:
        out = []
        for p in self.fixtures_up():
            if getattr(p, "muted", False):
                out.append([0, 0, 0, 255, 0])
            else:
                c = p.color
                out.append([c.red(), c.green(), c.blue(), 255, self._strobe(p)])
        return out[:8]

    @staticmethod
    def _strobe(p) -> int:
        """Valeur du canal Strobe (0 = pas de strobe, 16-250 = lent → rapide),
        calculée comme artnet_dmx. Le « strobe simple » ne touche PAS à la
        couleur : il passe par ce canal, que le projecteur exécute lui-même.
        Le téléphone fait pareil (clignotement local calé sur l'horloge du
        serveur)."""
        spd = getattr(p, "strobe_speed", 0) or 0
        if spd > 0:
            return int(16 + (min(100, spd) / 100.0) * (250 - 16))
        if getattr(p, "dmx_mode", "") == "Strobe":
            return 100            # même valeur par défaut que la sortie DMX
        return 0

    def _tick(self):
        z = self.zones() or [[0, 0, 0, 255, 0]]
        t = time.monotonic()
        if z == self._dernier and t - self._dernier_envoi < KEEPALIVE_S:
            return
        self._dernier, self._dernier_envoi = z, t
        self._poster({"t": "s", "z": z})

    def _poster(self, msg: dict):
        from PySide6.QtNetwork import QAbstractSocket
        ws = self._ws
        if ws is not None and ws.state() == QAbstractSocket.ConnectedState:
            ws.sendTextMessage(json.dumps(msg, separators=(",", ":")))

    # ── Journal de MyStrow ──────────────────────────────────────────────────
    def _journal(self, texte: str, niveau: str = "info"):
        log = getattr(self.window, "_log_message", None)
        if log:
            try:
                log(f"📱 MyStrow Up : {texte}", niveau)
            except Exception:
                pass

    def _liens_journal(self) -> str:
        """Liens cliquables du journal (cf. MessageLogWidget.add_action)."""
        log = getattr(self.window, "_msg_log", None)
        if log is None or not hasattr(log, "add_action"):
            return ""
        log.add_action("up-stop", self.stop)
        log.add_action("up-qr", self.ouvrir_qr)
        lien = 'color:#00d4ff;text-decoration:underline'
        return (f' — <a href="mystrow:up-stop" style="{lien}">{tr("up_lien_stop")}</a>'
                f' · <a href="mystrow:up-qr" style="{lien}">{tr("up_lien_qr")}</a>')

    def _sur_session(self, sid: str):
        self._journal(tr("up_session_prete", cap=self.cap, url=self.url_public())
                      + self._liens_journal(), "success")
        self.ouvrir_qr()

    def _sur_compte(self, n: int, cap: int):
        # Pas une ligne par téléphone : le premier, puis chaque dizaine, puis « complet ».
        if n > self._n_journal and (n == 1 or n % 10 == 0 or n >= cap):
            texte = tr("up_complet", n=n, cap=cap) if n >= cap else tr("up_connectes", n=n)
            self._journal(texte + self._liens_journal(), "info")
            self._n_journal = n
        elif n < self._n_journal:
            self._n_journal = n - n % 10

    def _sur_refus(self, message: str):
        """Le fil réseau n'a pas eu de ticket : on arrête tout et on explique."""
        self._timer.stop()
        self._actif = False
        self.sid = ""
        log = getattr(self.window, "_msg_log", None)
        lien = ""
        if log is not None and hasattr(log, "add_action"):
            if self.refus == REFUS_COMPTE and hasattr(self.window, "_open_activation_dialog"):
                log.add_action("up-compte", self.window._open_activation_dialog)
                lien = f' — <a href="mystrow:up-compte" style="color:#00d4ff">{tr("up_lien_compte")}</a>'
            elif self.refus == REFUS_LICENCE and hasattr(self.window, "_open_purchase_dialog"):
                log.add_action("up-plan", self.window._open_purchase_dialog)
                lien = f' — <a href="mystrow:up-plan" style="color:#00d4ff">{tr("up_lien_plan")}</a>'
        self._journal(message + lien, "error")
        self.statut.emit(message)

    def _sur_statut(self, texte: str):
        self._dernier_statut = texte

    def _statut_erreur(self, texte: str):
        """Statut d'erreur réseau : aussi dans le journal (une fois de suite)."""
        if texte != self._dernier_statut:
            self._journal(texte, "error")
        self.statut.emit(texte)

    def precharger_qr(self):
        """Récupère (en tâche de fond) le code du QR permanent de la licence,
        pour pouvoir le télécharger avant toute session."""
        def fil():
            _, _, self.refus = obtenir_ticket()
            self.qr_connu.emit()
        threading.Thread(target=fil, name="crowd-qr", daemon=True).start()

    # ── Fenêtre QR (appartient à la liaison : survit au dialogue de réglage) ─
    def ouvrir_qr(self):
        url = self.url_qr()
        if not url:
            return
        if self._fenetre_qr is None or self._fenetre_qr.url != url:
            if self._fenetre_qr is not None:
                self._fenetre_qr.close()
            self._fenetre_qr = QrPleinEcran(url)
        self._fenetre_qr.show()
        self._fenetre_qr.raise_()
        self._fenetre_qr.activateWindow()

    # ── Démarrage / arrêt ───────────────────────────────────────────────────
    def start(self):
        if self._actif:
            return
        self._gen += 1                      # les signaux d'une ancienne session sont ignorés
        self._fermer_ws()
        self._actif = True
        self._n_journal = 0
        self._essais = 0
        self._journal(tr("up_demarrage"))
        self.statut.emit(tr("up_verif_licence"))
        gen = self._gen
        # Seule la demande de ticket (HTTP bloquant) part dans un fil ; tout le
        # reste (WebSocket) vit dans la boucle Qt : QtWebSockets est livré avec
        # PySide6, aucune dépendance en plus (la lib « websockets » manquait
        # dans le Python de MyStrow → ModuleNotFoundError).
        threading.Thread(target=lambda: self._ticket_recu.emit(gen, *obtenir_ticket()),
                         name="crowd-ticket", daemon=True).start()
        self._timer.start()
        # Filet : si rien n'est prêt au bout de 20 s, on le dit au lieu de rester muet.
        QTimer.singleShot(20000, lambda: self._verifier_demarrage(gen))

    def _verifier_demarrage(self, gen: int):
        if self._actif and gen == self._gen and not self.sid:
            self._journal(tr("up_pas_prete", why=self._dernier_statut or tr("up_aucune_reponse"))
                          + self._liens_journal(),
                          "error")

    def stop(self, terminer=True):
        if not self._actif:
            return
        self._timer.stop()
        if terminer:
            self._poster({"t": "stop"})
        ws = self._ws
        self._ws = None
        self._gen += 1                      # plus aucune reconnexion pour cette session
        if ws is not None:
            QTimer.singleShot(300, ws.close)    # laisse partir le « stop »
            QTimer.singleShot(2000, ws.deleteLater)
        self._actif = False
        self.sid = ""
        if self._fenetre_qr is not None:
            self._fenetre_qr.close()
            self._fenetre_qr = None
        self.statut.emit(tr("up_terminee_statut"))
        self._journal(tr("up_terminee"))

    def _vivante(self, gen: int) -> bool:
        """Cette session est-elle encore celle en cours ?"""
        return self._actif and gen == self._gen

    def _sur_ticket(self, gen: int, ticket: str, cap: int, refus: str):
        if not self._vivante(gen):
            return
        self.refus = refus
        if not ticket:
            # Pas de compte / essai expiré / pas de réseau : le relais refuserait.
            self.refuse.emit(message_refus(refus))
            return
        self._ticket, self.cap = ticket, cap
        self.statut.emit(tr("up_cap_licence", cap=cap) if cap > CAP_ESSAI
                         else tr("up_cap_essai", cap=cap, lic=CAP_LICENCE))
        self._connecter(gen)

    def _connecter(self, gen: int):
        if not self._vivante(gen):
            return
        from PySide6.QtWebSockets import QWebSocket
        from PySide6.QtCore import QUrl
        base = self.serveur.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
        params = {"ticket": self._ticket}
        if self.sid:
            params["sid"], params["ctok"] = self.sid, self._ctok
        self._fermer_ws()
        ws = QWebSocket()
        ws.textMessageReceived.connect(lambda m, g=gen: self._sur_message(g, m))
        ws.connected.connect(lambda g=gen: self._sur_connecte(g))
        ws.disconnected.connect(lambda g=gen, w=ws: self._sur_deconnecte(g, w))
        self._ws = ws
        ws.open(QUrl(f"{base}/ws/ctl?{urllib.parse.urlencode(params)}"))

    def _fermer_ws(self):
        ws, self._ws = self._ws, None
        if ws is not None:
            ws.abort()
            ws.deleteLater()

    def _sur_connecte(self, gen: int):
        if self._vivante(gen):
            self._essais = 0
            self._dernier = None            # renvoie l'état complet tout de suite
            self.statut.emit(tr("up_connecte_srv"))

    def _sur_deconnecte(self, gen: int, ws):
        if not self._vivante(gen) or ws is not self._ws:
            return
        raison = ws.errorString() or tr("up_connexion_fermee")
        self._essais += 1
        if "403" in raison:
            self.refus = REFUS_LICENCE
            self.refuse.emit(message_refus(REFUS_LICENCE))
            return
        if "429" in raison:
            self._statut_erreur(tr("up_trop_sessions"))
        else:
            self._statut_erreur(tr("up_injoignable", why=raison))
        delai = int(min(10, 0.5 * 2 ** self._essais) * 1000)
        QTimer.singleShot(delai, lambda: self._connecter(gen))

    def _sur_message(self, gen: int, brut: str):
        if not self._vivante(gen):
            return            # message d'une session déjà remplacée
        try:
            m = json.loads(brut)
        except ValueError:
            return
        if m.get("t") == "session":
            nouveau = m["sid"] != self.sid
            self.sid = m["sid"]
            self._ctok = m.get("ctok", "")
            if nouveau:
                self.session_prete.emit(self.sid)
        elif m.get("t") == "n":
            self.compte.emit(int(m.get("n", 0)), int(m.get("cap", 0)))


class QrPleinEcran(QWidget):
    """QR géant à glisser sur l'écran de la salle (Échap ou double-clic pour fermer)."""

    def __init__(self, url: str):
        super().__init__(None, Qt.Window)
        self.url = url
        self.setWindowTitle(tr("up_qr_titre_fen"))
        self.setStyleSheet("background:#000;color:#fff")
        lay = QVBoxLayout(self)
        titre = QLabel(tr("up_qr_titre"), alignment=Qt.AlignCenter)
        titre.setWordWrap(True)
        f = QFont(); f.setPointSize(26); f.setBold(True)
        titre.setFont(f)
        self.qr = QLabel(alignment=Qt.AlignCenter)
        aide = QLabel(tr("up_qr_aide"), alignment=Qt.AlignCenter)
        aide.setStyleSheet("color:#555;font-size:12px")
        lay.addWidget(titre)
        lay.addWidget(self.qr, 1)
        lay.addWidget(aide)
        self._cote = 0
        self.resize(800, 860)

    def resizeEvent(self, e):
        cote = max(200, min(self.width(), self.height() - 200))
        if abs(cote - self._cote) > 8:          # pas de recalcul à chaque pixel
            self._cote = cote
            self.qr.setPixmap(qr_pixmap(self.url, cote))
        super().resizeEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() == Qt.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def mouseDoubleClickEvent(self, e):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()


class CrowdDialog(QDialog):
    def __init__(self, window, link: CrowdLink):
        super().__init__(window)
        self.link = link
        self.setWindowTitle(tr("up_dlg_titre"))
        self.setMinimumWidth(440)
        # Même thème sombre que les dialogues OBS / vMix / manette : sans lui, la
        # feuille de style de la fenêtre principale laisse un dialogue gris illisible.
        from video_link import STYLE_DIALOGUE
        # STYLE_DIALOGUE n'a pas d'état désactivé : un bouton bleu reste bleu
        # même inactif, et on ne voit pas qu'il est grisé.
        self.setStyleSheet(STYLE_DIALOGUE + """
QPushButton:disabled, QPushButton#primary:disabled {
    background: #161616; color: #4a4a4a; border: 1px solid #222;
}""")
        lay = QVBoxLayout(self)

        intro = QLabel(tr("up_intro"))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.zones = QLabel()
        self.zones.setWordWrap(True)
        lay.addWidget(self.zones)
        self.btn_patch = QPushButton(tr("up_ajout_patch"))
        self.btn_patch.clicked.connect(self._ajouter_au_patch)
        lay.addWidget(self.btn_patch)

        self.qr = QLabel(alignment=Qt.AlignCenter)
        self.qr.setMinimumHeight(260)
        lay.addWidget(self.qr)
        self.url = QLabel(alignment=Qt.AlignCenter)
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.url)
        self.info_qr = QLabel(alignment=Qt.AlignCenter)
        self.info_qr.setWordWrap(True)
        lay.addWidget(self.info_qr)
        self.nb = QLabel(alignment=Qt.AlignCenter)
        f = QFont(); f.setPointSize(16); f.setBold(True)
        self.nb.setFont(f)
        lay.addWidget(self.nb)
        self.etat = QLabel(alignment=Qt.AlignCenter)
        self.etat.setStyleSheet("color:#888")
        lay.addWidget(self.etat)

        boutons = QHBoxLayout()
        self.btn = QPushButton()
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self._basculer)
        self.btn_qr = QPushButton(tr("up_btn_qr"))
        self.btn_qr.clicked.connect(self._qr_grand)
        self.btn_png = QPushButton(tr("up_btn_png"))
        self.btn_png.clicked.connect(self._telecharger)
        boutons.addWidget(self.btn, 2)
        boutons.addWidget(self.btn_qr, 1)
        boutons.addWidget(self.btn_png, 1)
        lay.addLayout(boutons)
        # Sans compte / essai expiré : on renvoie vers le bon écran de licence.
        self.btn_compte = QPushButton()
        self.btn_compte.setObjectName("primary")
        self.btn_compte.clicked.connect(self._ouvrir_compte)
        self.btn_compte.hide()
        lay.addWidget(self.btn_compte)

        # Méthodes liées (pas de lambda) : Qt les déconnecte tout seul quand le
        # dialogue est détruit. Une lambda resterait branchée sur des QLabel
        # détruits et lèverait une erreur au téléphone suivant.
        link.session_prete.connect(self._maj)
        link.qr_connu.connect(self._maj)
        link.compte.connect(self._compte)
        link.statut.connect(self._statut)
        self._zones_maj()
        self._maj()
        if not link.actif:
            link.precharger_qr()     # licence ou essai ? (met à jour le QR permanent)

    def _compte(self, n, cap):
        self.nb.setText(tr("up_telephones", n=n, cap=cap))

    def _statut(self, texte):
        self.etat.setText(texte)

    def _zones_maj(self):
        n = len(self.link.fixtures_up())
        if n:
            self.zones.setText(tr("up_zones_ok", n=n, g=self.link.groupes_up(), z=min(n, 8)))
            self.zones.setStyleSheet("color:#00cc66")
            self.btn_patch.setText(tr("up_ajout_zone"))
        else:
            self.zones.setText(tr("up_zones_aucune"))
            self.zones.setStyleSheet("color:#ffb347")
            self.btn_patch.setText(tr("up_ajout_patch"))

    def _ajouter_au_patch(self):
        """Ouvre le patch DMX directement sur l'ajout de la fixture MyStrow Up."""
        w = self.link.window
        self.accept()
        if hasattr(w, "show_dmx_patch_config"):
            w.show_dmx_patch_config(add_search="MyStrow Up")

    def _maj(self, *_):
        actif = self.link.actif
        self.btn.setText(tr("up_btn_stop") if actif else tr("up_btn_start"))
        # Groupe vide = rien à envoyer aux téléphones ; pas de compte / essai
        # expiré = le serveur refuserait : on ne démarre pas.
        refus = "" if actif else self.link.refus
        bloque = refus in (REFUS_COMPTE, REFUS_LICENCE)
        self.btn.setEnabled(actif or (bool(self.link.zones()) and not bloque))
        self.btn_compte.setVisible(bloque)
        if refus == REFUS_COMPTE:
            self.btn_compte.setText(tr("up_btn_compte"))
        elif refus == REFUS_LICENCE:
            self.btn_compte.setText(tr("up_lien_plan"))
        self.btn_patch.setEnabled(not actif)
        url = self.link.url_qr()
        self.btn_qr.setEnabled(bool(url))
        self.btn_png.setEnabled(bool(url))
        if url:
            self.qr.setPixmap(qr_pixmap(url, 240))
            self.qr.show()
            self.url.setText(url)
        else:
            self.qr.clear()
            self.qr.hide()
            self.url.setText("")
        if not actif:
            self.nb.setText("")
        if refus in _CLES_REFUS:
            self.info_qr.setText("⚠ " + message_refus(refus))
            self.info_qr.setStyleSheet("color:#ff6b6b")
        elif self.link.qr_permanent():
            self.info_qr.setText(tr("up_qr_permanent"))
            self.info_qr.setStyleSheet("color:#00cc66")
        elif url:
            self.info_qr.setText(tr("up_qr_essai"))
            self.info_qr.setStyleSheet("color:#ffb347")
        else:
            self.info_qr.setText(tr("up_qr_essai_vide"))
            self.info_qr.setStyleSheet("color:#888")
        self.adjustSize()

    def _basculer(self):
        if self.link.actif:
            self.link.stop()
            self._maj()
            return
        refus = droit_refuse(self.link.window)
        if refus:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "MyStrow Up", refus)
            return
        self.link.refus = ""     # revérifié par le serveur au démarrage
        self.link.start()
        # « Démarrer » = c'est parti : on ferme. La suite s'affiche dans le
        # journal, et le QR s'ouvre tout seul dès que la session est prête.
        self.accept()

    def _qr_grand(self):
        self.accept()
        self.link.ouvrir_qr()

    def _ouvrir_compte(self):
        w = self.link.window
        ouvrir = (getattr(w, "_open_purchase_dialog", None) if self.link.refus == REFUS_LICENCE
                  else getattr(w, "_open_activation_dialog", None))
        self.accept()
        if ouvrir:
            ouvrir()

    def _telecharger(self):
        url = self.link.url_qr()
        if not url:
            return
        from PySide6.QtWidgets import QFileDialog
        nom = str(Path.home() / "Desktop" / f"MyStrow-Up-QR-{url.rsplit('/', 1)[-1]}.png")
        chemin, _ = QFileDialog.getSaveFileName(self, tr("up_dlg_png"), nom, tr("up_png_filtre"))
        if chemin:
            # 1200 px : assez pour une affiche A4 ou un écran 4K.
            ok = qr_image(url, 1200).save(chemin, "PNG")
            self.etat.setText(tr("up_png_ok") if ok else tr("up_png_ko"))
