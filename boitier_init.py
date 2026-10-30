# -*- coding: utf-8 -*-
"""Initialisation des boitiers maison a la chaine -- moteur commun.

Utilise par l'onglet « Boitiers » d'admin_panel.py et par la ligne de
commande tools/initialiser_boitier.py. Pour chaque boitier branche :
  1. flashe le firmware de build (puce vierge -> bootloader d'usine ;
     boitier deja flashe -> bascule en mise a jour par le label 0xB0) ;
  2. verifie qu'il repond en ENTTEC (label 10 serie, label 3 version) ;
  3. lui CREE son numero (MS-DMY-XXXX-XXXX, tire au sort) -- rien a taper,
     rien a graver ni a coller : la licence est dans la puce ;
  4. ecrit `boitiers/{numero}` : offre, lot, identifiant USB, et SUIVI.

Le client n'a aucun numero a saisir : l'app reconnait le boitier au
branchement (fonction `boitier_detect`, module boitier_detect.py). Le numero
sert au SAV et a l'admin (« Retour boitier »).

Suivi : chaque flash / initialisation / mise a jour est date a la seconde
dans l'historique du boitier (`history` : evenement, heure, firmware,
empreinte du binaire, poste) et dans le journal local
Medias/Boitier/suivi_boitiers.csv, qui s'ouvre dans Excel.

L'identifiant USB est le numero de serie que publie le firmware (12 chiffres
hexadecimaux derives de l'UID de la puce, firmware/usb_desc.c). Fixe en
usine, il survit aux mises a jour du firmware : rien n'est ecrit dans la puce.

L'OFFRE reste dans Firestore et nulle part ailleurs : un peripherique USB peut
declarer n'importe quoi, l'app ne le croit jamais sur parole.
"""
from __future__ import annotations

import csv
import hashlib
import re
import secrets
import socket
import subprocess
import threading
import time
from pathlib import Path

import serial
from serial.tools import list_ports

BOITIER = Path.home() / "Desktop" / "MyStrow" / "Medias" / "Boitier"
WCHISP = BOITIER / "chaine" / "wchisp" / "wchisp-win-x64" / "wchisp.exe"
FIRMWARE = BOITIER / "firmware" / "build" / "mystrow_dmx.bin"
# Double local de l'historique Firestore : lisible sans connexion, dans Excel.
JOURNAL = BOITIER / "suivi_boitiers.csv"

VID, PID = 0x1A86, 0x5740
ORDRE_BOOT = bytes([0x7E, 0xB0, 4, 0]) + b"BOOT" + bytes([0xE7])
USB_ID_RE = re.compile(r"^[0-9A-F]{12}$")
# Meme alphabet que _DMY_ALPHABET dans functions/main.py (ni I, ni O, ni 0).
DMY_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
# Offres proposees au lancement : libelle -> mois.
OFFRES = {"2 mois": 2, "1 an": 12}


class Arret(Exception):
    """L'operateur a demande l'arret (bouton de l'admin, Ctrl+C)."""


def nouveau_numero() -> str:
    """MS-DMY-XXXX-XXXX tire au sort : 33^8 possibilites, le numero seul
    active la licence (activate_code), il ne doit pas se deviner."""
    c = "".join(secrets.choice(DMY_ALPHABET) for _ in range(8))
    return f"MS-DMY-{c[:4]}-{c[4:]}"


def libelle_offre(months: int) -> str:
    return "1 an" if months == 12 else f"{months} mois"


def heure(utc: float) -> str:
    return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(utc))


def ports_mystrow() -> list:
    return [p for p in list_ports.comports() if p.vid == VID and p.pid == PID]


def journaliser(evt, serial_no, usb_id, fw, fw_sha, batch, months, mode, utc):
    neuf = not JOURNAL.exists()
    # utf-8-sig + « ; » : Excel francais l'ouvre tel quel, accents compris.
    with open(JOURNAL, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if neuf:
            w.writerow(["date_heure", "evenement", "numero", "carte_usb",
                        "firmware", "firmware_sha", "lot", "mois", "mode", "poste"])
        w.writerow([heure(utc), evt, serial_no, usb_id, fw, fw_sha, batch,
                    months, mode, socket.gethostname()])


def interroger(port: str) -> tuple[str, str]:
    """(serie ENTTEC, version firmware) -- prouve que le boitier repond."""
    with serial.Serial(port, 115200, timeout=1) as s:
        s.write(bytes([0x7E, 10, 0, 0, 0xE7]))
        r = s.read(9)
        serie = "%02X%02X%02X%02X" % (r[7], r[6], r[5], r[4]) if len(r) == 9 else ""
        s.write(bytes([0x7E, 3, 0, 0, 0xE7]))
        r = s.read(10)
        fw = f"{r[5]}.{r[4]}" if len(r) == 10 else ""
    return serie, fw


class Initialiseur:
    """Boucle d'initialisation. `log(texte)` recoit chaque etape ; `arreter()`
    peut etre appele depuis un autre thread et fait sortir `run()` proprement.

    db : client Firestore (firebase_admin.firestore.client()).
    push=False : essai -- flashe et teste, mais n'ecrit rien dans Firestore.
    """

    def __init__(self, db, months: int, batch: str = "", push: bool = True,
                 flash: bool = True, log=print, on_boitier=None):
        if months <= 0:
            raise ValueError("offre invalide")
        self.db = db
        self.months = months
        self.batch = batch or f"DMY-{months}M"
        self.push = push
        self.flash = flash
        self.log = log
        # Appele apres chaque boitier enregistre (l'admin rafraichit sa liste).
        self.on_boitier = on_boitier or (lambda serial_no: None)
        self.duree = libelle_offre(months)
        self.n = 0
        self._stop = threading.Event()
        self.fw_sha = (hashlib.sha256(FIRMWARE.read_bytes()).hexdigest()[:12]
                       if FIRMWARE.exists() else "")

    # ------------------------------------------------------------ outils
    def arreter(self):
        self._stop.set()

    def _attendre(self, cond, delai: float | None = None) -> bool:
        fin = time.time() + delai if delai else None
        while not cond():
            if self._stop.is_set():
                raise Arret()
            if fin and time.time() > fin:
                return False
            time.sleep(0.3)
        return True

    def _debrancher(self):
        self.log("  -> debrancher, brancher le suivant\n")
        self._attendre(lambda: not ports_mystrow())

    def _tracer(self, evt, serial_no, usb_id, fw, utc, ref=None, champs=None):
        """Une ligne au journal local ; avec push, l'evenement rejoint
        l'historique du boitier (`history`, le plus ancien en tete)."""
        from firebase_admin import firestore
        journaliser(evt, serial_no, usb_id, fw, self.fw_sha, self.batch,
                    self.months, "push" if self.push else "essai", utc)
        if self.push and ref is not None:
            e = {"evt": evt, "utc": utc, "usb_id": usb_id, "firmware": fw,
                 "firmware_sha": self.fw_sha, "poste": socket.gethostname()}
            ref.set({**(champs or {}), "history": firestore.ArrayUnion([e])},
                    merge=True)

    def _wchisp(self) -> str | None:
        """Un essai de flashage. None = pas de bootloader en vue."""
        r = subprocess.run([str(WCHISP), "flash", str(FIRMWARE)],
                           capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or ""))
        if r.returncode == 0:
            return out
        # « failed to open » : la puce vient d'apparaitre et Windows n'a pas
        # encore lie WinUSB -- course passagere (vu le 07/10/2026).
        if re.search(r"device not found|failed to open", out, re.I):
            return None
        raise RuntimeError(out)

    def _flasher(self) -> bool:
        """Attend un boitier, le flashe. Vierge : il est deja dans le
        bootloader. Deja flashe : il apparait en COM, on le bascule (0xB0)."""
        fin_bascule = 0.0
        while True:
            if self._stop.is_set():
                raise Arret()
            out = self._wchisp()
            if out is not None:
                if "Verify OK" not in out:
                    self.log("  ⚠ flashe, mais pas de « Verify OK » :\n" + out)
                    return False
                self.log("  firmware flashe, Verify OK")
                return True
            ports = ports_mystrow()
            if ports and not fin_bascule:
                if len(ports) > 1:
                    self.log("  ⚠ plusieurs boitiers branches : n'en laisser qu'un.")
                    self._attendre(lambda: len(ports_mystrow()) <= 1)
                    continue
                self.log(f"  firmware deja present ({ports[0].device}), mise a jour...")
                try:
                    with serial.Serial(ports[0].device, 115200, timeout=1) as s:
                        s.write(ORDRE_BOOT)
                        s.flush()
                except serial.SerialException as e:
                    self.log(f"  ⚠ port inaccessible (MyStrow l'utilise ?) : {e}")
                    return False
                fin_bascule = time.time() + 20
            if fin_bascule and time.time() > fin_bascule:
                self.log("  ⚠ bootloader jamais vu apres la bascule.")
                return False

    # ------------------------------------------------------------ boucle
    def run(self):
        if self.flash and not (WCHISP.exists() and FIRMWARE.exists()):
            raise FileNotFoundError(WCHISP if not WCHISP.exists() else FIRMWARE)
        self.log(f"=== Serie {self.duree.upper()} (lot {self.batch}) ==="
                 + ("" if self.push else "  (ESSAI : rien ne sera ecrit dans Firestore)"))
        self.log(f"Journal local : {JOURNAL}\n")
        try:
            while True:
                self._un_boitier()
        except Arret:
            self.log(f"Arret. {self.n} boitier(s) initialise(s) cette session.")

    def _un_boitier(self):
        boitiers = self.db.collection("boitiers")
        self.log("Brancher un boitier...")

        # ---------------------------------------------------- 1. firmware
        flash_utc = 0.0
        if self.flash:
            if not self._flasher():
                self._debrancher()
                return
            flash_utc = time.time()
        if not self._attendre(lambda: len(ports_mystrow()) == 1,
                              10 if self.flash else None):
            self.log("  ⚠ le boitier n'apparait pas en port COM.\n")
            return
        time.sleep(0.5)
        port = ports_mystrow()[0]

        # ---------------------------------------------------- 2. il repond ?
        usb_id = (port.serial_number or "").upper()
        try:
            serie, fw = interroger(port.device)
        except serial.SerialException as e:
            serie, fw = "", ""
            self.log(f"  ⚠ port inaccessible : {e}")
        if not USB_ID_RE.match(usb_id) or not serie:
            self.log(f"  ⚠ boitier KO (usb {usb_id!r}, serie {serie!r}) : a ecarter.")
            self._tracer("KO", "", usb_id, fw, time.time())
            self._debrancher()
            return
        self.log(f"  carte {usb_id} sur {port.device}, firmware {fw or '?'}, repond OK")

        flash_champs = ({"flashed_utc": flash_utc, "firmware": fw,
                         "firmware_sha": self.fw_sha} if flash_utc else {})

        deja = boitiers.where("usb_id", "==", usb_id).limit(1).get()
        if deja:
            d = deja[0].to_dict() or {}
            self.log(f"  deja initialise : {deja[0].id}, "
                     f"{libelle_offre(int(d.get('months') or 0))}"
                     + (f", le {heure(d['initialized_utc'])}"
                        if d.get("initialized_utc") else ""))
            if flash_utc:
                self._tracer("maj firmware", deja[0].id, usb_id, fw, flash_utc,
                             deja[0].reference, flash_champs)
                self.log(f"  firmware {fw} remis le {heure(flash_utc)} (trace)")
            self._debrancher()
            return

        # ---------------------------------------------------- 3. numero
        serial_no = nouveau_numero()
        while boitiers.document(serial_no).get().exists:
            serial_no = nouveau_numero()

        # ---------------------------------------------------- 4. Firestore
        now = time.time()
        doc = {"serial": serial_no, "batch": self.batch, "months": self.months,
               "usb_id": usb_id, "usb_id_utc": now, "initialized_utc": now,
               "created_utc": now, "firmware": fw, **flash_champs}
        ref = boitiers.document(serial_no)
        if flash_utc:
            self._tracer("flash", serial_no, usb_id, fw, flash_utc, ref)
        self._tracer(f"init {self.duree}", serial_no, usb_id, fw, now, ref, doc)
        if self.push:
            self.n += 1
            self.log(f"  ✅ {serial_no} : {self.duree}, carte {usb_id}, "
                     f"flashe le {heure(flash_utc or now)}  ({self.n} cette session)")
            self.on_boitier(serial_no)
        else:
            self.log(f"  (essai) {serial_no} : {self.duree}, carte {usb_id}")
        self._debrancher()
