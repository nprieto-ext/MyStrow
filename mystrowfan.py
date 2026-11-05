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
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox,
                               QFrame, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget, QAbstractItemView)

import boitier_init as bi

VERSION = "1.0.0"
PROJECT_ID = "mystrow-907be"
API_URL = f"https://us-central1-{PROJECT_ID}.cloudfunctions.net/boitier_enregistrer"

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
    """Puce WCH en bootloader (4348:55E0) branchee, pilote ou pas."""
    try:
        cfg = ctypes.windll.cfgmgr32
        flags = 0x1 | 0x100      # FILTER_ENUMERATOR | FILTER_PRESENT
        n = ctypes.c_ulong()
        if cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(n), "USB", flags):
            return False
        buf = ctypes.create_unicode_buffer(n.value)
        if cfg.CM_Get_Device_ID_List_W("USB", buf, n, flags):
            return False
        return "VID_4348&PID_55E0" in ctypes.wstring_at(buf, n.value).upper()
    except Exception:
        return False


# --------------------------------------------------------------- serveur
class Api:
    def __init__(self, cle: str):
        self.cle = cle

    def appel(self, action: str, **champs) -> dict:
        req = urllib.request.Request(
            API_URL, method="POST",
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
            self.ui.ligne.emit("—", bi.libelle_offre(self.months), "écarté (DMX)", ROUGE)
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
                        f"{bi.heure(flash_utc) if flash_utc else '—'} · débranche-le",
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
        if not self.cfg.get("cle"):
            self._demander_cle()
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
            "1. Laisse le boîtier branché.\n"
            "2. Dans la liste, choisis l'appareil « USB Module » (ID 4348 55E0).\n"
            "   S'il n'apparaît pas : menu Options → List All Devices.\n"
            "3. À droite de la flèche, garde « WinUSB ».\n"
            "4. Clique « Install Driver » (ou « Replace Driver »), attends la fin.\n"
            "5. Ferme Zadig, débranche et rebranche le boîtier.")
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
