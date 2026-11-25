# -*- coding: utf-8 -*-
"""MyStrowFan -- poste de preparation des boitiers USB-DMX MyStrow.

Pour la personne qui prepare les colis : on choisit l'offre (2 mois, 1 an,
sans licence), on branche les boitiers un par un. Pour chacun :
  1. flash du firmware (puce vierge : bootloader d'usine) ;
  2. verification qu'il repond en ENTTEC ;
  3. test DMX sur le MiniCube (mode C05, adresse 1 : R V B Dim Strobe) :
     dimmer a fond, bleu, blanc, rouge, puis violet qui baisse ; strobe a 0 ;
  4. « le projo a bien fait ca ? » Oui -> enregistrement : numero MS-DMY cree
     par le serveur, offre, date de flash. Non -> ecarte (journal local).

Aucun acces direct a la base : tout passe par la function
`boitier_enregistrer` avec une cle de poste (tools/creer_poste_boitiers.py).
Le moteur de flash est celui de l'admin (boitier_init.py).
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import serial
from PySide6.QtCore import QObject, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QFrame, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget, QAbstractItemView)

import boitier_init as bi

VERSION = "1.1.4"
PROJECT_ID = "mystrow-907be"
API_URL = f"https://us-central1-{PROJECT_ID}.cloudfunctions.net/boitier_enregistrer"
EXPE_URL = f"https://us-central1-{PROJECT_ID}.cloudfunctions.net/boitier_expeditions"

# --------------------------------------------------------------- chemins
if getattr(sys, "frozen", False):
    RES = Path(sys._MEIPASS)
else:
    RES = Path(__file__).resolve().parent

DATA = Path(os.environ.get("APPDATA", Path.home())) / "MyStrowFan"
DATA.mkdir(parents=True, exist_ok=True)
CONFIG = DATA / "config.json"
DOCS = Path.home() / "Documents" / "MyStrowFan"
DOCS.mkdir(parents=True, exist_ok=True)

if getattr(sys, "frozen", False):
    bi.WCHISP = RES / "outils" / "wchisp.exe"
    bi.FIRMWARE = RES / "outils" / "mystrow_dmx.bin"
    ZADIG = RES / "outils" / "zadig.exe"
    LOGO = RES / "logo.png"
else:
    ZADIG = bi.BOITIER / "chaine" / "zadig-2.9.exe"
    LOGO = RES / "logo.png"
bi.JOURNAL = DOCS / "suivi_boitiers.csv"

# --------------------------------------------------------------- couleurs
JAUNE = "#FFE600"
NOIR = "#1d1d1b"
FOND = "#121211"
CARTE = "#232321"
GRIS = "#8c8c86"
VERT = "#3ddc84"
ROUGE = "#ff4d4d"

OFFRES = [("2 MOIS", 2), ("1 AN", 12), ("SANS LICENCE", 0)]

# --------------------------------------------------------------- test DMX
# MiniCube mode C05 a l'adresse 1 : 1 R, 2 V, 3 B, 4 Dim, 5 Strobe.
ADRESSE = 1
SEQUENCE = [  # (nom, (r, v, b), duree s, fondu du dimmer)
    ("Bleu", (0, 0, 255), 1.2, False),
    ("Blanc", (255, 255, 255), 1.2, False),
    ("Rouge", (255, 0, 0), 1.2, False),
    ("Violet", (170, 0, 255), 1.2, False),
    ("Violet qui baisse", (170, 0, 255), 2.0, True),
]


def trame(r: int, v: int, b: int, dim: int) -> bytes:
    """Paquet ENTTEC Pro label 6 : start code 0 + 512 canaux."""
    data = bytearray(513)
    a = ADRESSE
    data[a:a + 5] = bytes([r, v, b, dim, 0])   # strobe a 0 : pas de strobe
    n = len(data)
    return bytes([0x7E, 6, n & 0xFF, n >> 8]) + bytes(data) + bytes([0xE7])


def jouer_test(port: str, on_couleur, stop: threading.Event) -> None:
    """Joue la sequence bleu-blanc-rouge-violet a 25 trames/s."""
    with serial.Serial(port, 115200, timeout=1, write_timeout=1) as s:
        for nom, (r, v, b), duree, fondu in SEQUENCE:
            t0 = time.time()
            on_couleur(nom, (r, v, b), 255)
            while (t := time.time() - t0) < duree:
                if stop.is_set():
                    break
                dim = int(255 * (1 - t / duree)) if fondu else 255
                if fondu:
                    on_couleur(nom, (r, v, b), dim)
                s.write(trame(r, v, b, dim))
                time.sleep(0.04)
        for _ in range(12):                    # noir franc a la fin
            s.write(trame(0, 0, 0, 0))
            time.sleep(0.04)
    on_couleur("", (0, 0, 0), 0)


# --------------------------------------------------------------- pilote
def bootloader_present() -> bool:
    """Puce WCH en bootloader (1A86:55E0 ou 4348:55E0) branchee, pilote ou pas."""
    try:
        cfg = ctypes.windll.cfgmgr32
        flags = 0x1 | 0x100      # FILTER_ENUMERATOR | FILTER_PRESENT
        n = ctypes.c_ulong()
        if cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(n), "USB", flags):
            return False
        buf = ctypes.create_unicode_buffer(n.value)
        if cfg.CM_Get_Device_ID_List_W("USB", buf, n, flags):
            return False
        ids = ctypes.wstring_at(buf, n.value).upper()
        return "VID_1A86&PID_55E0" in ids or "VID_4348&PID_55E0" in ids
    except Exception:
        return False


# --------------------------------------------------------------- serveur
class Api:
    def __init__(self, cle: str):
        self.cle = cle

    def appel(self, action: str, url: str = API_URL, **champs) -> dict:
        req = urllib.request.Request(
            url, method="POST",
            data=json.dumps({"action": action, **champs}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Poste-Key": self.cle})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode())
            except Exception:
                return {"ok": False, "error": f"http_{e.code}"}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return {"ok": False, "error": "reseau", "detail": str(e)}


# --------------------------------------------------------------- moteur
class Moteur(bi.Initialiseur):
    """Le moteur de l'admin, mais l'enregistrement passe par le serveur et
    chaque boitier attend la reponse de l'operatrice au test DMX."""

    def __init__(self, api: Api, ui: "Pont", months: int, flash: bool):
        super().__init__(None, months, push=True, flash=flash,
                         log=lambda t: ui.log.emit(t.strip()))
        self.api = api
        self.ui = ui
        self.reponse = None                   # "ok" / "ko" / "rejouer" / "reessayer"
        self._rep_evt = threading.Event()
        self._test_stop = threading.Event()
        self._sans_boot = 0

    # ---- interactions avec l'interface
    def repondre(self, r: str):
        self.reponse = r
        self._rep_evt.set()

    def _attendre_reponse(self, permis: set, port: str | None = None) -> str:
        """Bloque jusqu'a une reponse permise ; le debranchement vaut « parti »."""
        self._rep_evt.clear()
        while True:
            if self._stop.is_set():
                raise bi.Arret()
            if port and not bi.ports_mystrow():
                return "parti"
            if self._rep_evt.wait(0.3):
                self._rep_evt.clear()
                if self.reponse in permis:
                    return self.reponse

    def _etat(self, cle, titre, detail="", **extra):
        self.ui.etat.emit({"cle": cle, "titre": titre, "detail": detail, **extra})

    def _fixer(self, cle, titre, detail="", **extra):
        """Etat a reafficher apres un « rejouer le test »."""
        self._dernier = {"cle": cle, "titre": titre, "detail": detail, **extra}
        self.ui.etat.emit(self._dernier)

    def _wchisp(self):
        out = super()._wchisp()
        if out is None and bootloader_present():
            self._sans_boot += 1
            if self._sans_boot == 4:          # ~4 essais : ce n'est pas une course
                self._etat("pilote", "Pilote USB manquant",
                           "Le boîtier est bien branché mais Windows ne le laisse "
                           "pas flasher. Clique « Installer le pilote » (une seule "
                           "fois sur ce PC).")
        else:
            self._sans_boot = 0
        time.sleep(0.4)
        return out

    def _jouer(self, port: str):
        self._test_stop.clear()
        try:
            jouer_test(port, lambda n, c, d: self.ui.couleur.emit(n, list(c), d),
                       self._test_stop)
            return True
        except serial.SerialException as e:
            self.log(f"⚠ test DMX impossible : {e}")
            return False

    def _attendre_debranchement(self, port: str):
        while bi.ports_mystrow():
            r = self._attendre_reponse({"rejouer"}, port)
            if r == "parti":
                break
            self._etat("rejoue", "Test DMX…", "Regarde le projecteur.")
            self._jouer(port)
            self.ui.etat.emit(self._dernier)
        self._etat("attente", "Branche un boîtier", self._offre_txt())

    def _offre_txt(self):
        return f"Offre : {bi.libelle_offre(self.months)}"

    # ---- boucle
    def run(self):
        if self.flash and not (bi.WCHISP.exists() and bi.FIRMWARE.exists()):
            raise FileNotFoundError(bi.WCHISP if not bi.WCHISP.exists() else bi.FIRMWARE)
        try:
            while True:
                self._un_boitier()
        except bi.Arret:
            pass

    def _un_boitier(self):
        self._etat("attente", "Branche un boîtier", self._offre_txt())

        flash_utc = 0.0
        if self.flash:
            if not self._flasher():
                self._etat("ko", "Flash raté", "Débranche-le et mets-le de côté.")
                self._attendre(lambda: not bi.ports_mystrow() and not bootloader_present())
                return
            flash_utc = time.time()
            self._etat("travail", "Firmware flashé", "Démarrage du boîtier…")
        if not self._attendre(lambda: len(bi.ports_mystrow()) == 1,
                              12 if self.flash else None):
            self._etat("ko", "Le boîtier ne démarre pas",
                       "Il n'apparaît pas après le flash. Débranche-le, mets-le de côté.")
            bi.journaliser("KO demarrage", "", "", "", self.fw_sha, self.batch,
                           self.months, "fan", time.time())
            self._attendre(lambda: not bi.ports_mystrow() and not bootloader_present())
            return
        time.sleep(0.5)
        p = bi.ports_mystrow()[0]
        usb_id = (p.serial_number or "").upper()
        try:
            serie, fw = bi.interroger(p.device)
        except serial.SerialException as e:
            serie, fw = "", ""
            self.log(f"⚠ port inaccessible : {e}")
        if not bi.USB_ID_RE.match(usb_id) or not serie:
            bi.journaliser("KO", "", usb_id, fw, self.fw_sha, self.batch,
                           self.months, "fan", time.time())
            self._fixer("ko", "Boîtier KO", "Il ne répond pas correctement. Mets-le de côté.")
            self._attendre_debranchement(p.device)
            return
        self.log(f"carte {usb_id} sur {p.device}, firmware {fw}")

        # Deja connu ?
        rep = self._serveur("lookup", usb_id=usb_id)
        if rep is None:
            return
        if rep.get("known"):
            if flash_utc:
                self._serveur("event", usb_id=usb_id, evt="maj firmware",
                              firmware=fw, firmware_sha=self.fw_sha,
                              flashed_utc=flash_utc)
            etat = ("vendu" if rep.get("activated") else
                    "dans la nature" if rep.get("seen") else "en stock")
            detail = (f"{bi.libelle_offre(rep['months'])} · enregistré le "
                      f"{bi.heure(rep['initialized_utc'])} · {etat}"
                      + (" · firmware remis" if flash_utc else ""))
            self._fixer("info", "Déjà enregistré", detail, numero=rep["serial"])
            self.ui.ligne.emit(rep["serial"], bi.libelle_offre(rep["months"]),
                               "déjà enregistré", GRIS)
            self._jouer(p.device)
            self._attendre_debranchement(p.device)
            return

        # Test DMX puis question
        while True:
            self._etat("test", "Test DMX…", "Regarde le projecteur.")
            if not self._jouer(p.device):
                self._fixer("ko", "Test DMX impossible",
                            "Le port est occupé (MyStrow est ouvert ?). Ferme-le puis débranche/rebranche.")
                self._attendre_debranchement(p.device)
                return
            self._etat("question", "Le projecteur a fait bleu, blanc, rouge, puis violet qui baisse ?",
                       "")
            r = self._attendre_reponse({"ok", "ko", "rejouer"}, p.device)
            if r == "parti":
                self.log("débranché avant la réponse : rien enregistré")
                return
            if r != "rejouer":
                break

        if r == "ko":
            bi.journaliser("KO test dmx", "", usb_id, fw, self.fw_sha, self.batch,
                           self.months, "fan", time.time())
            self.ui.ligne.emit("-", bi.libelle_offre(self.months), "écarté (DMX)", ROUGE)
            self._fixer("ko", "Boîtier écarté", "Mets-le de côté, débranche-le.")
            self._attendre_debranchement(p.device)
            return

        # Enregistrement (offre lue au dernier moment : elle peut avoir change)
        months = self.months
        rep = self._serveur("register", usb_id=usb_id, months=months, firmware=fw,
                            firmware_sha=self.fw_sha, flashed_utc=flash_utc, test="ok")
        if rep is None:
            return
        numero = rep["serial"]
        bi.journaliser(f"init {bi.libelle_offre(rep['months'])}", numero, usb_id, fw,
                       self.fw_sha, f"DMY-{rep['months']}M", rep["months"], "fan",
                       time.time())
        self.n += 1
        if rep.get("created"):
            self._fixer("ok", "Enregistré !",
                        f"{bi.libelle_offre(rep['months'])} · flashé le "
                        f"{bi.heure(flash_utc) if flash_utc else '-'} · débranche-le",
                        numero=numero)
            self.ui.ligne.emit(numero, bi.libelle_offre(rep["months"]), "enregistré", VERT)
        else:
            self._fixer("info", "Déjà enregistré", "", numero=numero)
        self._attendre_debranchement(p.device)

    def _serveur(self, action, **champs):
        """Appel au serveur ; en cas d'echec, l'operatrice reessaie ou debranche."""
        while True:
            try:
                rep = self.api.appel(action, **champs)
            except Exception as e:
                rep = {"ok": False, "error": f"réseau ({e.__class__.__name__})"}
            if rep.get("ok"):
                return rep
            err = rep.get("error")
            msg = {"bad_key": "Clé du poste refusée : demande une nouvelle clé à Nicolas.",
                   "daily_cap": "Limite du jour atteinte (300 boîtiers).",
                   }.get(err, f"Le serveur ne répond pas ({err}). Vérifie Internet.")
            self.log(f"⚠ {action} : {err}")
            self._etat("erreur", "Problème de connexion", msg)
            r = self._attendre_reponse({"reessayer"}, "x")
            if r == "parti":
                self._etat("attente", "Branche un boîtier", self._offre_txt())
                return None


class Pont(QObject):
    etat = Signal(dict)
    couleur = Signal(str, list, int)
    ligne = Signal(str, str, str, str)
    log = Signal(str)
    fini = Signal(str)
    expe = Signal(str, dict)          # (action, réponse du serveur)
    maj = Signal(str)                 # progression / fin de la mise à jour


# --------------------------------------------------------------- interface
STYLE = f"""
QWidget {{ background:{FOND}; color:white; font-family:'Segoe UI'; font-size:14px; }}
QLabel {{ background:transparent; }}
QPushButton {{ background:{CARTE}; color:white; border:1px solid #333; border-radius:10px;
              padding:10px 18px; font-weight:600; }}
QPushButton:hover {{ border-color:{JAUNE}; }}
QPushButton:disabled {{ color:#555; border-color:#2a2a2a; }}
QPushButton#offre {{ font-size:18px; font-weight:800; padding:18px; border:2px solid #333; }}
QPushButton#offre:checked {{ background:{JAUNE}; color:{NOIR}; border-color:{JAUNE}; }}
QPushButton#oui {{ background:{VERT}; color:{NOIR}; font-size:17px; border:none; }}
QPushButton#non {{ background:{ROUGE}; color:white; font-size:17px; border:none; }}
QPushButton#jaune {{ background:{JAUNE}; color:{NOIR}; border:none; font-size:16px; }}
QTableWidget {{ background:{CARTE}; border:none; border-radius:10px; gridline-color:#2c2c2a; }}
QHeaderView::section {{ background:{CARTE}; color:{GRIS}; border:none; padding:6px; }}
QCheckBox {{ color:{GRIS}; }}
QTabWidget::pane {{ border:none; }}
QTabBar::tab {{ background:transparent; color:{GRIS}; padding:8px 18px; font-size:15px;
               font-weight:700; border-bottom:3px solid transparent; }}
QTabBar::tab:selected {{ color:white; border-bottom-color:{JAUNE}; }}
QComboBox, QLineEdit {{ background:#1a1a19; border:1px solid #3a3a37; border-radius:8px;
                        padding:8px 10px; font-size:15px; }}
QLineEdit:focus, QComboBox:focus {{ border-color:{JAUNE}; }}
QScrollArea {{ border:none; }}
QFrame#cmd {{ background:{CARTE}; border-radius:14px; }}
QFrame#cmd_ok {{ background:{CARTE}; border-radius:10px; }}
"""


class Fenetre(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"MyStrowFan {VERSION}")
        if LOGO.exists():
            self.setWindowIcon(QIcon(str(LOGO)))
        self.resize(760, 820)
        self.cfg = self._lire_cfg()
        self.pont = Pont()
        self.pont.etat.connect(self._sur_etat)
        self.pont.couleur.connect(self._sur_couleur)
        self.pont.ligne.connect(self._sur_ligne)
        self.pont.log.connect(lambda t: print(t))
        self.pont.fini.connect(self._sur_fini)
        self.moteur = None
        self.n_session = 0

        w = QWidget()
        self.setCentralWidget(w)
        root = QVBoxLayout(w)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)

        # En-tete
        hd = QHBoxLayout()
        logo = QLabel()
        if LOGO.exists():
            logo.setPixmap(QPixmap(str(LOGO)).scaled(54, 54, Qt.KeepAspectRatio,
                                                     Qt.SmoothTransformation))
        hd.addWidget(logo)
        tt = QVBoxLayout()
        t1 = QLabel("MyStrow<span style='color:%s'>Fan</span>" % JAUNE)
        t1.setFont(QFont("Segoe UI", 22, QFont.Black))
        t2 = QLabel("Préparation des boîtiers USB-DMX")
        t2.setStyleSheet(f"color:{GRIS};")
        tt.addWidget(t1)
        tt.addWidget(t2)
        hd.addLayout(tt)
        hd.addStretch()
        self.lbl_compteur = QLabel("0 aujourd'hui")
        self.lbl_compteur.setStyleSheet(f"color:{JAUNE}; font-size:16px; font-weight:700;")
        hd.addWidget(self.lbl_compteur)
        root.addLayout(hd)

        # Bandeau de mise à jour (caché tant que le serveur n'annonce rien de plus récent).
        self.b_maj = QPushButton("")
        self.b_maj.setCursor(Qt.PointingHandCursor)
        self.b_maj.setStyleSheet(
            f"background:{JAUNE}; color:{NOIR}; font-weight:700; font-size:14px;"
            " padding:10px; border-radius:8px;")
        self.b_maj.clicked.connect(self._maj_installer)
        self.b_maj.setVisible(False)
        self._maj = None
        root.addWidget(self.b_maj)

        # Onglets : l'écran de préparation (inchangé) et les expéditions.
        entete = root
        self.tabs = QTabWidget()
        page_prep = QWidget()
        root = QVBoxLayout(page_prep)
        root.setContentsMargins(0, 14, 0, 0)
        root.setSpacing(16)

        # 1. Offre
        root.addWidget(self._titre("1 · Quelle offre pour les boîtiers ?"))
        ofl = QHBoxLayout()
        self.grp = QButtonGroup(self)
        for i, (nom, m) in enumerate(OFFRES):
            b = QPushButton(nom)
            b.setObjectName("offre")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.grp.addButton(b, m)
            ofl.addWidget(b)
        self.grp.idClicked.connect(self._sur_offre)
        root.addLayout(ofl)

        # 2. Carte d'etat
        root.addWidget(self._titre("2 · Branche les boîtiers un par un"))
        self.carte = QFrame()
        self.carte.setStyleSheet(f"QFrame {{ background:{CARTE}; border-radius:16px; }}")
        cl = QVBoxLayout(self.carte)
        cl.setContentsMargins(24, 22, 24, 22)
        cl.setSpacing(10)
        self.lbl_etat = QLabel("Choisis une offre pour commencer")
        self.lbl_etat.setFont(QFont("Segoe UI", 19, QFont.Bold))
        self.lbl_etat.setWordWrap(True)
        self.lbl_etat.setAlignment(Qt.AlignCenter)
        self.lbl_numero = QLabel("")
        self.lbl_numero.setAlignment(Qt.AlignCenter)
        self.lbl_numero.setStyleSheet(f"color:{JAUNE}; font-size:28px; font-weight:800;"
                                      " font-family:Consolas;")
        self.lbl_detail = QLabel("")
        self.lbl_detail.setAlignment(Qt.AlignCenter)
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet(f"color:{GRIS};")
        self.pastille = QLabel()
        self.pastille.setFixedSize(120, 120)
        self.pastille.setAlignment(Qt.AlignCenter)
        self._pastille((40, 40, 38), "")
        pl = QHBoxLayout()
        pl.addStretch()
        pl.addWidget(self.pastille)
        pl.addStretch()
        cl.addLayout(pl)
        cl.addWidget(self.lbl_etat)
        cl.addWidget(self.lbl_numero)
        cl.addWidget(self.lbl_detail)

        bl = QHBoxLayout()
        self.b_oui = QPushButton("✔  Oui, c'est bon")
        self.b_oui.setObjectName("oui")
        self.b_non = QPushButton("✖  Non")
        self.b_non.setObjectName("non")
        self.b_rejouer = QPushButton("↻  Rejouer le test")
        self.b_reessayer = QPushButton("↻  Réessayer")
        self.b_reessayer.setObjectName("jaune")
        self.b_pilote = QPushButton("Installer le pilote")
        self.b_pilote.setObjectName("jaune")
        for b in (self.b_oui, self.b_non, self.b_rejouer, self.b_reessayer, self.b_pilote):
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(52)
            bl.addWidget(b)
        cl.addLayout(bl)
        self.b_oui.clicked.connect(lambda: self._rep("ok"))
        self.b_non.clicked.connect(lambda: self._rep("ko"))
        self.b_rejouer.clicked.connect(lambda: self._rep("rejouer"))
        self.b_reessayer.clicked.connect(lambda: self._rep("reessayer"))
        self.b_pilote.clicked.connect(self._pilote)
        root.addWidget(self.carte, 1)

        # 3. Session
        root.addWidget(self._titre("Boîtiers de la session"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Heure", "Numéro", "Offre", "Statut"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFixedHeight(190)
        root.addWidget(self.table)

        bas = QHBoxLayout()
        self.cb_flash = QCheckBox("Flasher le firmware")
        self.cb_flash.setChecked(self.cfg.get("flash", True))
        self.cb_flash.toggled.connect(self._sur_flash)
        bas.addWidget(self.cb_flash)
        bas.addStretch()
        b_j = QPushButton("Ouvrir le journal")
        b_j.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DOCS))))
        b_k = QPushButton("Clé du poste")
        b_k.clicked.connect(self._demander_cle)
        bas.addWidget(b_j)
        bas.addWidget(b_k)
        root.addLayout(bas)

        self.tabs.addTab(page_prep, "Préparation")
        self.tabs.addTab(self._page_expeditions(), "Expéditions")
        self.tabs.currentChanged.connect(
            lambda i: self._expe_charger() if i == 1 else None)
        entete.addWidget(self.tabs, 1)
        self.pont.expe.connect(self._expe_reponse)
        self.pont.maj.connect(self._maj_etape)
        self._expe_timer = QTimer(self)
        self._expe_timer.timeout.connect(self._expe_charger)
        self._expe_timer.start(5 * 60 * 1000)     # badge à jour même sur l'autre onglet

        self.setStyleSheet(STYLE)
        self._boutons(set())
        QTimer.singleShot(200, self._demarrage)

    # ---------------------------------------------------------------- outils
    def _titre(self, t):
        l = QLabel(t)
        l.setStyleSheet(f"color:{GRIS}; font-size:12px; font-weight:700; letter-spacing:1px;")
        return l

    def _lire_cfg(self):
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _ecrire_cfg(self):
        CONFIG.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")

    def _pastille(self, rgb, texte, dim=255):
        r, v, b = (int(c * dim / 255) for c in rgb)
        bord = JAUNE if texte else "#333"
        self.pastille.setStyleSheet(
            f"background:rgb({r},{v},{b}); border-radius:60px; border:3px solid {bord};"
            f" color:{'#000' if (r + v + b) > 400 else '#fff'}; font-weight:700;")
        self.pastille.setText(texte)

    def _boutons(self, visibles: set):
        for nom, b in (("oui", self.b_oui), ("non", self.b_non),
                       ("rejouer", self.b_rejouer), ("reessayer", self.b_reessayer),
                       ("pilote", self.b_pilote)):
            b.setVisible(nom in visibles)

    def _rep(self, r):
        if self.moteur:
            self.moteur.repondre(r)

    # ---------------------------------------------------------------- démarrage
    def _demarrage(self):
        if getattr(sys, "frozen", False):          # reste d'une mise à jour
            try:
                Path(sys.executable).with_name(
                    Path(sys.executable).stem + ".ancien.exe").unlink(missing_ok=True)
            except OSError:
                pass
        if not self.cfg.get("cle"):
            self._demander_cle()
        self._expe_charger()                   # badge « Expéditions (n) » dès l'ouverture
        if "offre" in self.cfg:
            b = self.grp.button(int(self.cfg["offre"]))
            if b:
                b.setChecked(True)
                self._sur_offre(int(self.cfg["offre"]))

    def _demander_cle(self):
        cle, ok = QInputDialog.getText(
            self, "Clé du poste",
            "Colle la clé que Nicolas t'a envoyée (une seule fois) :",
            QLineEdit.Normal, "")
        if ok and cle.strip():
            self.cfg["cle"] = cle.strip()
            self._ecrire_cfg()
            if self.moteur:
                self.moteur.api.cle = self.cfg["cle"]
            if hasattr(self, "tabs"):
                self._expe_charger()

    def _sur_flash(self, on):
        self.cfg["flash"] = on
        self._ecrire_cfg()
        if self.moteur:
            self.moteur.flash = on

    def _sur_offre(self, months):
        self.cfg["offre"] = months
        self._ecrire_cfg()
        if self.moteur:
            self.moteur.months = months        # prise en compte au prochain boîtier
            self.moteur.batch = f"DMY-{months}M"
            if self.lbl_etat.text() == "Branche un boîtier":
                self.lbl_detail.setText(f"Offre : {bi.libelle_offre(months)}")
            return
        if not self.cfg.get("cle"):
            QMessageBox.warning(self, "MyStrowFan", "Il manque la clé du poste.")
            self._demander_cle()
            if not self.cfg.get("cle"):
                return
        self.moteur = Moteur(Api(self.cfg["cle"]), self.pont, months,
                             self.cb_flash.isChecked())

        def _run():
            try:
                self.moteur.run()
                self.pont.fini.emit("")
            except Exception as e:
                self.pont.fini.emit(str(e))

        threading.Thread(target=_run, daemon=True).start()

    # ---------------------------------------------------------------- expéditions
    def _page_expeditions(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(12)
        haut = QHBoxLayout()
        self.lbl_expe = QLabel("…")
        self.lbl_expe.setStyleSheet("font-size:17px; font-weight:700;")
        haut.addWidget(self.lbl_expe)
        haut.addStretch()
        self.lbl_stock = QLabel("")
        self.lbl_stock.setStyleSheet(f"color:{GRIS};")
        haut.addWidget(self.lbl_stock)
        self._stocks = None
        self._remu = None
        self.b_actu = QPushButton("↻  Actualiser")
        self.b_actu.setCursor(Qt.PointingHandCursor)
        self.b_actu.clicked.connect(self._expe_charger)
        haut.addWidget(self.b_actu)
        lay.addLayout(haut)
        self.cartes_stock = QHBoxLayout()
        self.cartes_stock.setSpacing(10)
        lay.addLayout(self.cartes_stock)

        zone = QScrollArea()
        zone.setWidgetResizable(True)
        self.expe_contenu = QWidget()
        self.expe_liste = QVBoxLayout(self.expe_contenu)
        self.expe_liste.setContentsMargins(0, 0, 6, 0)
        self.expe_liste.setSpacing(12)
        self.expe_liste.addStretch()
        zone.setWidget(self.expe_contenu)
        lay.addWidget(zone, 1)
        self.transporteurs = [["colissimo", "Colissimo"]]
        self._expe_en_cours = False
        return page

    def _expe_appel(self, action: str, **champs):
        """Appel serveur dans un thread ; la réponse revient par self.pont.expe."""
        cle = self.cfg.get("cle", "")

        def _run():
            try:
                rep = Api(cle).appel(action, url=EXPE_URL, **champs)
            except Exception as e:
                rep = {"ok": False, "error": "reseau", "detail": str(e)}
            self.pont.expe.emit(action, rep)

        threading.Thread(target=_run, daemon=True).start()

    def _expe_charger(self):
        if not self.cfg.get("cle"):
            self.lbl_expe.setText("Il manque la clé du poste")
            return
        if self._expe_en_cours:
            return
        self._expe_en_cours = True
        self.b_actu.setEnabled(False)
        self.b_actu.setText("Chargement…")
        self._expe_appel("liste")

    def _expe_erreur(self, rep) -> str:
        return {"bad_key": "Clé du poste refusée : demande une nouvelle clé à Nicolas.",
                "bad_tracking": "Numéro de suivi invalide (lettres et chiffres, 6 minimum).",
                "already_shipped": "Cette commande est déjà marquée expédiée.",
                "not_found": "Commande introuvable.",
                "reseau": "Pas de connexion au serveur. Vérifie Internet.",
                }.get(rep.get("error"), f"Erreur du serveur ({rep.get('error')}).")

    def _expe_reponse(self, action, rep):
        if action == "liste":
            self._expe_en_cours = False
            self.b_actu.setEnabled(True)
            self.b_actu.setText("↻  Actualiser")
            if not rep.get("ok"):
                self.lbl_expe.setText(self._expe_erreur(rep))
                self.lbl_expe.setStyleSheet(f"color:{ROUGE}; font-size:15px; font-weight:700;")
                return
            self.transporteurs = rep.get("transporteurs") or self.transporteurs
            self._expe_afficher(rep.get("commandes") or [], rep.get("stock"))
            self._remu_afficher(rep.get("remu"))
            self._stock_afficher(rep.get("stocks"))
            self._maj_verifier(rep.get("maj"))
        elif action == "stock":
            if rep.get("ok"):
                self._stock_afficher(rep.get("stocks"))
            else:
                QMessageBox.warning(self, "Stock", self._expe_erreur(rep))
        elif action == "expedier":
            if rep.get("ok") or rep.get("error") == "already_shipped":
                if not rep.get("ok"):
                    QMessageBox.information(self, "Expédition", self._expe_erreur(rep))
                self._expe_charger()
            else:
                QMessageBox.warning(self, "Expédition", self._expe_erreur(rep))
                for b in self.findChildren(QPushButton, "envoyer"):
                    b.setEnabled(True)
                    b.setText("✔  Expédié → envoyer le suivi")

    # ---------------------------------------------------------------- cartes
    _STYLE_STOCK = {  # clé → (icône, couleur d'accent)
        "boitier_2":  ("📦", "#4da3ff"),
        "boitier_12": ("📦", JAUNE),
        "boitier":    ("🔌", VERT),
        "cartes":     ("🛠", "#c08cff"),
    }

    @staticmethod
    def _eur(x) -> str:
        return f"{float(x or 0):.2f}".replace(".00", "").replace(".", ",") + " €"

    def _carte_stat(self, titre, valeur, acc, sous="", sous_coul=None, clic=None, aide=""):
        """Une carte cliquable : petit titre, gros chiffre, ligne d'info."""
        carte = QFrame()
        carte.setObjectName("stat")
        carte.setStyleSheet(
            f"QFrame#stat {{ background:{CARTE}; border-radius:12px; border-top:4px solid {acc}; }}"
            f"QFrame#stat:hover {{ background:#2c2c29; }}")
        carte.setCursor(Qt.PointingHandCursor)
        carte.setToolTip(aide)
        if clic:
            carte.mousePressEvent = lambda _e: clic()
        v = QVBoxLayout(carte)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(2)
        t = QLabel(titre)
        t.setWordWrap(True)
        t.setStyleSheet(f"color:{GRIS}; font-size:12px; font-weight:700; background:transparent;")
        nb = QLabel(str(valeur))
        nb.setStyleSheet(f"color:{acc}; font-size:32px; font-weight:800; background:transparent;")
        v.addWidget(t)
        v.addWidget(nb)
        a = QLabel(sous)
        a.setWordWrap(True)
        a.setStyleSheet(f"color:{sous_coul or GRIS}; font-size:11px; background:transparent;")
        v.addWidget(a)
        v.addStretch()
        return carte

    def _cartes_afficher(self):
        """5 cartes : les 4 piles du stock (clic = corriger) + le montant dû (clic = historique)."""
        while self.cartes_stock.count():
            it = self.cartes_stock.takeAt(0)
            if it.widget():
                it.widget().hide()          # sinon elle reste peinte jusqu'à sa destruction
                it.widget().deleteLater()
        for s in self._stocks or []:
            icone, acc = self._STYLE_STOCK.get(s["cle"], ("•", GRIS))
            n = int(s["n"])
            bas = s["cle"] != "cartes" and n <= 3
            self.cartes_stock.addWidget(self._carte_stat(
                f"{icone}  {s['nom']}", n, ROUGE if bas else acc,
                "stock bas · clic pour corriger" if bas else "clic pour corriger",
                ROUGE if bas else None,
                clic=lambda s=s: self._stock_modifier(s),
                aide="Clique pour corriger ce nombre"), 1)
        r = self._remu
        if r:
            du = float(r.get("du") or 0)
            self.cartes_stock.addWidget(self._carte_stat(
                "💶  Montant dû", self._eur(du), JAUNE if du > 0 else VERT,
                f"{r.get('nb_colis', 0)} colis × {self._eur(r.get('tarif', 15))} · clic = historique",
                clic=self._remu_historique,
                aide="Ce que Nicolas te doit (15 € par colis expédié)"), 1)

    def _stock_afficher(self, stocks):
        self._stocks = stocks
        if stocks:
            self.lbl_stock.setVisible(False)          # remplacé par les cartes
        self._cartes_afficher()

    def _stock_modifier(self, s):
        from PySide6.QtWidgets import QDialog, QSpinBox, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle(s["nom"])
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"Combien de « {s['nom']} » as-tu chez toi ?"))
        sp = QSpinBox()
        sp.setRange(0, 9999)
        sp.setValue(int(s["n"]))
        sp.setStyleSheet("font-size:22px; padding:6px;")
        lay.addWidget(sp)
        info = QLabel("Ça bouge aussi tout seul :\n"
                      "• carte flashée → −1 carte à monter, +1 dans la pile de l'offre choisie ;\n"
                      "• interface vierge préparée en 1 an / 2 mois → −1 interface, +1 boîtier ;\n"
                      "• interface vierge expédiée à un client → −1 interface.")
        info.setStyleSheet(f"color:{GRIS}; font-size:12px;")
        lay.addWidget(info)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Enregistrer")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        sp.setFocus()
        sp.selectAll()
        if dlg.exec() != QDialog.Accepted or sp.value() == int(s["n"]):
            return
        self._expe_appel("stock", stocks={s["cle"]: sp.value()})

    def _remu_historique(self):
        r = self._remu or {}
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Mes colis et paiements")
        dlg.resize(620, 480)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            f"<b>{r.get('nb_colis', 0)} colis</b> × {self._eur(r.get('tarif', 15))} = "
            f"{self._eur(r.get('gagne'))}   ·   déjà payé : {self._eur(r.get('paye'))}   ·   "
            f"<b style='color:{JAUNE}'>reste : {self._eur(r.get('du'))}</b>"))
        lignes = [(c.get("utc"), "📦 Colis", f"{c.get('ref', '')}  {c.get('nom', '')}",
                   "+" + self._eur(c.get("montant"))) for c in r.get("colis") or []]
        lignes += [(v.get("utc"), "💶 Paiement reçu", "", "−" + self._eur(v.get("montant")))
                   for v in r.get("versements") or []]
        lignes.sort(key=lambda l: -float(l[0] or 0))
        tab = QTableWidget(len(lignes), 4)
        tab.setHorizontalHeaderLabels(["Date", "Quoi", "Détail", "Montant"])
        tab.verticalHeader().setVisible(False)
        tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tab.setSelectionMode(QAbstractItemView.NoSelection)
        for i, (utc, quoi, detail, montant) in enumerate(lignes):
            date = time.strftime("%d/%m/%Y", time.localtime(float(utc))) if utc else "-"
            for j, txt in enumerate((date, quoi, detail, montant)):
                it = QTableWidgetItem(txt)
                if j == 3:
                    it.setForeground(QColor(VERT if txt.startswith("+") else JAUNE))
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                tab.setItem(i, j, it)
        hh = tab.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        lay.addWidget(tab, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Fermer")
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()

    # ---------------------------------------------------------------- mise à jour
    @staticmethod
    def _v(txt) -> tuple:
        try:
            return tuple(int(x) for x in str(txt).split("."))
        except ValueError:
            return (0,)

    def _maj_verifier(self, maj):
        if (not maj or not maj.get("url") or not getattr(sys, "frozen", False)
                or self._v(maj.get("version")) <= self._v(VERSION)):
            self.b_maj.setVisible(False)
            return
        self._maj = maj
        if self.b_maj.isEnabled():
            self.b_maj.setText(f"⬇  Nouvelle version {maj['version']} disponible - "
                               "clique ici pour l'installer")
        self.b_maj.setVisible(True)

    def _maj_installer(self):
        maj = self._maj
        if not maj:
            return
        # Le moteur tourne dès qu'une offre est choisie (même en simple attente) :
        # on ne bloque que si un boîtier est réellement branché.
        if self.moteur and (bi.ports_mystrow() or bootloader_present()):
            QMessageBox.information(self, "Mise à jour",
                                    "Débranche d'abord le boîtier en cours, puis reclique.")
            return
        notes = f"\n\nNouveautés :\n{maj['notes']}" if maj.get("notes") else ""
        if QMessageBox.question(
                self, "Mise à jour",
                f"Installer MyStrowFan {maj['version']} ?\n"
                f"MyStrowFan va se fermer et se rouvrir tout seul.{notes}") != QMessageBox.Yes:
            return
        self.b_maj.setEnabled(False)
        self.b_maj.setText("Téléchargement… 0 %")
        exe = Path(sys.executable)
        neuf = exe.with_name(exe.stem + ".nouveau.exe")

        def _run():
            import hashlib
            try:
                h = hashlib.sha256()
                req = urllib.request.Request(maj["url"], headers={"User-Agent": "MyStrowFan"})
                with urllib.request.urlopen(req, timeout=60) as r, open(neuf, "wb") as f:
                    total = int(maj.get("taille") or r.headers.get("Content-Length") or 0)
                    lu = 0
                    while True:
                        bloc = r.read(256 * 1024)
                        if not bloc:
                            break
                        f.write(bloc)
                        h.update(bloc)
                        lu += len(bloc)
                        if total:
                            self.pont.maj.emit(f"Téléchargement… {lu * 100 // total} %")
                if maj.get("sha256") and h.hexdigest() != maj["sha256"]:
                    raise ValueError("fichier abîmé (empreinte différente), réessaie")
                self.pont.maj.emit("OK")
            except Exception as e:
                try:
                    neuf.unlink()
                except OSError:
                    pass
                self.pont.maj.emit(f"ERREUR {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _maj_etape(self, msg: str):
        if msg.startswith("ERREUR"):
            self.b_maj.setEnabled(True)
            self.b_maj.setText("⬇  Mise à jour ratée - clique pour réessayer")
            QMessageBox.warning(self, "Mise à jour", msg[7:])
            return
        if msg != "OK":
            self.b_maj.setText(msg)
            return
        # Windows laisse RENOMMER un exe en cours d'exécution (pas l'effacer) :
        # l'actuel devient .ancien.exe (effacé au prochain démarrage), le neuf
        # prend sa place, on le lance et on ferme.
        exe = Path(sys.executable)
        neuf = exe.with_name(exe.stem + ".nouveau.exe")
        ancien = exe.with_name(exe.stem + ".ancien.exe")
        try:
            if ancien.exists():
                ancien.unlink()
            exe.rename(ancien)
            neuf.rename(exe)
        except OSError as e:
            if not exe.exists() and ancien.exists():
                ancien.rename(exe)
            self.b_maj.setEnabled(True)
            self.b_maj.setText("⬇  Mise à jour ratée - clique pour réessayer")
            QMessageBox.warning(self, "Mise à jour",
                                f"Impossible de remplacer le programme : {e}\n"
                                "Demande à Nicolas de te renvoyer le fichier.")
            return
        import subprocess
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        env.pop("_MEIPASS2", None)
        subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent),
                         creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_GROUP
        QApplication.quit()

    def _remu_afficher(self, r):
        """Montant dû par Nicolas (15 € par colis) : 5e carte."""
        self._remu = r
        self._cartes_afficher()

    def _expe_afficher(self, commandes, stock):
        while self.expe_liste.count() > 1:           # garde le stretch final
            it = self.expe_liste.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        a_faire = [c for c in commandes if c["status"] != "shipped"]
        faites = sorted((c for c in commandes if c["status"] == "shipped"),
                        key=lambda c: -c["shipped_utc"])
        n = len(a_faire)
        self.lbl_expe.setText(f"{n} colis à expédier" if n else "Rien à expédier 👍")
        self.lbl_expe.setStyleSheet(
            f"color:{JAUNE if n else VERT}; font-size:17px; font-weight:700;")
        self.tabs.setTabText(1, f"Expéditions ({n})" if n else "Expéditions")
        self.lbl_stock.setText(f"Stock : {stock} boîtiers" if stock is not None else "")
        self.lbl_stock.setStyleSheet(
            f"color:{ROUGE}; font-weight:700;" if stock is not None and stock <= 5
            else f"color:{GRIS};")

        pos = 0
        for c in a_faire:
            self.expe_liste.insertWidget(pos, self._carte_commande(c))
            pos += 1
        if faites:
            self.expe_liste.insertWidget(pos, self._titre("EXPÉDIÉES - 30 DERNIERS JOURS"))
            pos += 1
            for c in faites:
                self.expe_liste.insertWidget(pos, self._ligne_expediee(c))
                pos += 1

    @staticmethod
    def _adresse_txt(a: dict) -> str:
        lignes = [a.get("name"), a.get("line1"), a.get("line2"),
                  f"{a.get('postal_code', '')} {a.get('city', '')}".strip(),
                  a.get("country") if a.get("country") not in ("", "FR") else ""]
        return "\n".join(l for l in lignes if l)

    def _carte_commande(self, c):
        f = QFrame()
        f.setObjectName("cmd")
        l = QVBoxLayout(f)
        l.setContentsMargins(20, 16, 20, 16)
        l.setSpacing(10)
        t = QHBoxLayout()
        # « libelle » : la CF le renvoie depuis que Fanny expédie aussi des packs
        # quand le stock Amazon est épuisé (25/11/2026).
        quoi = c.get("libelle") or "interface"
        titre = QLabel(f"📦  {c['quantity']} × "
                       + ("interface USB-DMX" if quoi == "interface" else quoi.upper()))
        titre.setStyleSheet("font-size:17px; font-weight:800;")
        t.addWidget(titre)
        t.addStretch()
        quand = time.strftime("%d/%m à %H:%M", time.localtime(c["created_utc"]))
        info = QLabel(f"Réf. {c['ref']} · commandé le {quand}")
        info.setStyleSheet(f"color:{GRIS};")
        t.addWidget(info)
        l.addLayout(t)

        a = c["address"]
        txt = self._adresse_txt(a)
        esc = lambda x: (x.replace("&", "&amp;").replace("<", "&lt;")
                         .replace(">", "&gt;"))
        mail = c.get("email") or ""
        adr = QLabel(esc(txt).replace("\n", "<br>") +
                     (f"<br><span style='color:{GRIS}'>Tél. {esc(a['phone'])}</span>"
                      if a.get("phone") else "") +
                     (f"<br><span style='color:{GRIS}'>E-mail : {esc(mail)}</span>"
                      if mail else ""))
        adr.setTextFormat(Qt.RichText)
        adr.setTextInteractionFlags(Qt.TextSelectableByMouse)
        adr.setStyleSheet("font-size:16px; background:#1a1a19; border-radius:8px; padding:10px;")
        l.addWidget(adr)
        b_copie = QPushButton("Copier l'adresse")
        b_copie.setCursor(Qt.PointingHandCursor)

        def _copier():
            QApplication.clipboard().setText(
                txt + (f"\nTél. {a['phone']}" if a.get("phone") else ""))
            b_copie.setText("✔ Copiée")
            QTimer.singleShot(1500, lambda: b_copie.setText("Copier l'adresse"))
        b_copie.clicked.connect(_copier)
        rc = QHBoxLayout()
        rc.addWidget(b_copie)
        if mail:
            # Champ « e-mail du destinataire » de l'étiquette Colissimo : c'est
            # là que partent les avis « disponible en point relais ».
            b_mail = QPushButton("Copier l'e-mail")
            b_mail.setCursor(Qt.PointingHandCursor)

            def _copier_mail():
                QApplication.clipboard().setText(mail)
                b_mail.setText("✔ Copié")
                QTimer.singleShot(1500, lambda: b_mail.setText("Copier l'e-mail"))
            b_mail.clicked.connect(_copier_mail)
            rc.addWidget(b_mail)
        rc.addStretch()
        l.addLayout(rc)
        if mail:
            aide = QLabel("👉 Sur l'étiquette Colissimo, colle cet e-mail dans le champ "
                          "« e-mail du destinataire » : sinon le client n'est pas prévenu "
                          "quand le colis arrive en point relais.")
            aide.setWordWrap(True)
            aide.setStyleSheet(f"color:{GRIS}; font-size:12px;")
            l.addWidget(aide)

        l.addWidget(self._titre("UNE FOIS LE COLIS DÉPOSÉ"))
        r = QHBoxLayout()
        cb = QComboBox()
        for k, nom in self.transporteurs:
            cb.addItem(nom, k)
        cb.setCurrentIndex(max(0, cb.findData(self.cfg.get("transporteur", "colissimo"))))
        r.addWidget(cb)
        num = QLineEdit()
        num.setPlaceholderText("N° de suivi")
        r.addWidget(num, 1)
        l.addLayout(r)
        b = QPushButton("✔  Expédié → envoyer le suivi")
        b.setObjectName("envoyer")
        b.setStyleSheet(f"background:{VERT}; color:{NOIR}; border:none; font-size:16px;")
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(46)
        l.addWidget(b)

        def _envoyer():
            if not b.isEnabled():
                return
            code = "".join(num.text().split()).upper()
            if not code.isalnum() or not 6 <= len(code) <= 40:
                QMessageBox.warning(self, "Expédition",
                                    "Vérifie le numéro de suivi (lettres et chiffres).")
                return
            dest = a.get("name") or "le client"
            if QMessageBox.question(
                    self, "Envoyer le suivi ?",
                    f"{cb.currentText()} : {code}\n\nLe client ({dest}) va recevoir "
                    "ce numéro par mail. On envoie ?") != QMessageBox.Yes:
                return
            self.cfg["transporteur"] = cb.currentData()
            self._ecrire_cfg()
            b.setEnabled(False)
            b.setText("Envoi…")
            self._expe_appel("expedier", order_id=c["id"],
                             transporteur=cb.currentData(), suivi=code)
        b.clicked.connect(_envoyer)
        num.returnPressed.connect(_envoyer)
        return f

    def _ligne_expediee(self, c):
        f = QFrame()
        f.setObjectName("cmd_ok")
        l = QHBoxLayout(f)
        l.setContentsMargins(14, 8, 14, 8)
        quand = time.strftime("%d/%m", time.localtime(c["shipped_utc"] or c["created_utc"]))
        a = c["address"]
        g = QLabel(f"✔  {quand} · {a.get('name', '')} - "
                   f"{a.get('postal_code', '')} {a.get('city', '')}")
        g.setTextFormat(Qt.PlainText)
        l.addWidget(g, 1)
        p = (c.get("packages") or [{}])[0]
        if p.get("tracking"):
            if p.get("url"):
                lien = QLabel(f"{p.get('carrier', '')} : <a href='{p['url']}' "
                              f"style='color:{JAUNE}'>{p['tracking']}</a>")
                lien.setOpenExternalLinks(True)
                lien.setTextInteractionFlags(Qt.TextBrowserInteraction)
            else:
                lien = QLabel(f"{p.get('carrier', '')} : {p['tracking']}")
            l.addWidget(lien)
        return f

    def _sur_fini(self, err):
        self.moteur = None
        if err:
            self._sur_etat({"cle": "ko", "titre": "Erreur", "detail": err})

    def _pilote(self):
        if not ZADIG.exists():
            QMessageBox.warning(self, "Pilote", f"Zadig introuvable : {ZADIG}")
            return
        QMessageBox.information(
            self, "Installer le pilote (une seule fois)",
            "Une fenêtre « Zadig » va s'ouvrir (accepte la demande de Windows) :\n\n"
            "Pas besoin de brancher le boîtier : il ne reste visible que\n"
            "quelques secondes, on déclare donc l'appareil à la main.\n\n"
            "1. Menu Device → Create New Device.\n"
            "2. Dans le champ du nom, tape : WCH ISP\n"
            "3. Dans les cases USB ID, tape 1A86 puis 55E0\n"
            "   (laisse la 3e case vide).\n"
            "4. À droite de la flèche, garde « WinUSB ».\n"
            "5. Clique « Install Driver », attends la fin (1 à 2 min).\n"
            "6. Ferme Zadig, relance la préparation, puis branche le boîtier.")
        try:
            os.startfile(str(ZADIG))
        except OSError as e:
            QMessageBox.warning(self, "Pilote", str(e))

    # ---------------------------------------------------------------- signaux
    def _sur_etat(self, e):
        cle = e["cle"]
        self.lbl_etat.setText(e["titre"])
        self.lbl_detail.setText(e.get("detail", ""))
        self.lbl_numero.setText(e.get("numero", ""))
        couleurs = {"ok": VERT, "ko": ROUGE, "erreur": ROUGE, "pilote": ROUGE,
                    "question": JAUNE}
        self.lbl_etat.setStyleSheet(f"color:{couleurs.get(cle, 'white')};")
        self._boutons({"question": {"oui", "non", "rejouer"},
                       "ok": {"rejouer"}, "info": {"rejouer"},
                       "erreur": {"reessayer"}, "pilote": {"pilote"}}.get(cle, set()))
        if cle == "attente":
            self._pastille((40, 40, 38), "")
        elif cle == "ok":
            self._pastille((61, 220, 132), "✔")
        elif cle in ("ko", "erreur", "pilote"):
            self._pastille((255, 77, 77), "✖")

    def _sur_couleur(self, nom, rgb, dim):
        self._pastille(tuple(rgb) if nom else (40, 40, 38), nom, dim if nom else 255)

    def _sur_ligne(self, numero, offre, statut, coul):
        t = self.table
        t.insertRow(0)
        for c, v in enumerate([time.strftime("%H:%M"), numero, offre, statut]):
            it = QTableWidgetItem(v)
            if c == 3:
                it.setForeground(QColor(coul))
            t.setItem(0, c, it)
        if statut == "enregistré":
            self.n_session += 1
            self.lbl_compteur.setText(f"{self.n_session} aujourd'hui")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("MyStrowFan")
    f = Fenetre()
    f.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
