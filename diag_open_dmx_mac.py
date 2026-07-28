#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostic interactif « boîtier Open DMX muet » — macOS (et Windows/Linux).

Cherche POURQUOI un boîtier USB/DMX passif (ENTTEC Open DMX USB, USB Opto…)
n'allume rien alors que le PC envoie ses trames sans la moindre erreur.

Le script balaye, une par une, les variables qui peuvent tuer la sortie sans
produire d'erreur, et vous demande à chaque fois si les projecteurs ont réagi :

  A. Lignes de contrôle RTS / DTR   (4 combinaisons)
     → sur un boîtier passif, la broche Driver Enable du transceiver RS485 peut
       être câblée dessus ; pyserial les ASSERTE à l'ouverture du port.
  B. Durée du signal Break          (100 µs / 200 µs / 400 µs)
     → DMX512-A impose ≥ 92 µs au transmetteur ; 100 µs est juste au-dessus.
  C. Méthode de génération du Break (baud-rate trick / send_break / break_condition)
     → sur macOS send_break réussit sans lever d'exception mais ne produit
       aucun break électrique valide.
  D. Cadence d'envoi                (25 fps / 40 fps / 10 fps)

Le motif envoyé CLIGNOTE (1 s plein feu / 0,5 s noir) : impossible de confondre
avec des projecteurs déjà allumés.

AUCUNE dépendance à MyStrow : le fichier peut être copié seul sur le Mac.

    ⚠  FERMEZ MyStrow AVANT DE LANCER (deux logiciels sur le même port FTDI =
       résultats faux et port refermé en pleine séquence).

Usage :
    python3 diag_open_dmx_mac.py               # choix du port interactif
    python3 diag_open_dmx_mac.py /dev/cu.usbserial-XXXX
"""
import json
import os
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("pyserial manquant.  →  python3 -m pip install pyserial")
    sys.exit(1)


# ── Constantes DMX ────────────────────────────────────────────────────────────
DMX_BAUD = 250000
# Le break est généré par un octet 0x00 émis à un débit plus lent : 9 bits à
# LOW (start + 8 zéros). La durée du break découle donc du débit choisi.
BREAKS = {
    90000: "100 µs (réglage actuel de MyStrow)",
    45000: "200 µs",
    22000: "409 µs",
}
LIGNES = {
    "clear":  (False, False),
    "legacy": (True,  True),
    "rts":    (True,  False),
    "dtr":    (False, True),
}
LIGNES_LABEL = {
    "clear":  "RTS ✗ / DTR ✗   (méthode QLC+ / OLA)",
    "legacy": "RTS ✓ / DTR ✓   (défaut pyserial = MyStrow ≤ 3.1.76)",
    "rts":    "RTS ✓ / DTR ✗",
    "dtr":    "RTS ✗ / DTR ✓",
}
CONFIG_MYSTROW = os.path.expanduser("~/.mystrow_dmx.json")
RAPPORT = os.path.expanduser("~/diag_open_dmx.txt")

_journal = []


# ── Affichage ─────────────────────────────────────────────────────────────────
_COUL = {"ok": "\033[92m", "err": "\033[91m", "warn": "\033[93m",
         "cyan": "\033[96m", "dim": "\033[90m", "gras": "\033[1m", "": ""}


def log(texte="", couleur=""):
    _journal.append(texte)
    if couleur and sys.stdout.isatty():
        print(f"{_COUL.get(couleur, '')}{texte}\033[0m")
    else:
        print(texte)


def titre(texte):
    log("")
    log("═" * 66, "cyan")
    log(f"  {texte}", "cyan")
    log("═" * 66, "cyan")


def demander(question, choix="onrq"):
    """Pose une question et renvoie la lettre choisie (o/n/r/q)."""
    libelle = {"o": "oui", "n": "non", "r": "rejouer", "q": "quitter"}
    menu = " / ".join(f"[{c}]{libelle[c][1:]}" for c in choix)
    while True:
        try:
            rep = input(f"\n  {question}  {menu} : ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "q"
        if rep[:1] in choix:
            return rep[:1]
        print("     Réponse attendue : " + ", ".join(choix))


# ── Ports ─────────────────────────────────────────────────────────────────────
def lister_ports():
    ports = list(serial.tools.list_ports.comports())
    if sys.platform == "darwin":
        # /dev/tty.* bloque en attente du DCD à l'ouverture — toujours /dev/cu.*
        ports = [p for p in ports if "/dev/tty." not in p.device]
    return ports


def est_ftdi(p):
    return (p.vid, p.pid) == (0x0403, 0x6001) or "FTDI" in (p.manufacturer or "")


def choisir_port(argv):
    titre("1. PORTS SÉRIE")
    ports = lister_ports()
    if not ports:
        log("  ✗  Aucun port série détecté — rebranchez le boîtier USB.", "err")
        return None
    for i, p in enumerate(ports):
        etoile = "★" if est_ftdi(p) else " "
        vid = f"VID:{p.vid:04X} PID:{p.pid:04X}" if p.vid else "VID:???? PID:????"
        log(f"  {etoile} [{i}] {p.device}", "ok" if est_ftdi(p) else "dim")
        log(f"        {p.description or 'n/a'}  [{vid}]  série={p.serial_number or '?'}", "dim")

    if len(argv) > 1:
        return argv[1]

    ftdi = [p for p in ports if est_ftdi(p)]
    if len(ftdi) == 1:
        log("")
        log(f"  →  Un seul boîtier FTDI : {ftdi[0].device}", "ok")
        return ftdi[0].device
    try:
        n = input("\n  Numéro du port à tester : ").strip()
        return ports[int(n)].device
    except (ValueError, IndexError, EOFError, KeyboardInterrupt):
        log("  ✗  Choix invalide.", "err")
        return None


# ── Émission DMX ──────────────────────────────────────────────────────────────
class Sortie:
    """Émetteur DMX brut sur port série — reproduit exactement la sortie live."""

    def __init__(self, ser):
        self.ser = ser
        self.erreurs = 0
        self.derniere_erreur = ""

    def lignes(self, mode):
        rts, dtr = LIGNES[mode]
        detail = []
        for nom, valeur in (("rts", rts), ("dtr", dtr)):
            try:
                setattr(self.ser, nom, valeur)
            except Exception as e:
                detail.append(f"{nom.upper()} non pilotable ({e})")
        return detail

    def trame(self, frame, break_baud=90000, methode="baud"):
        ser = self.ser
        if methode == "baud":
            ser.baudrate = break_baud
            ser.write(b"\x00")
            ser.flush()
            time.sleep(0.0015)
            ser.baudrate = DMX_BAUD
            time.sleep(0.0001)          # MAB ≥ 8 µs
        elif methode == "send_break":
            ser.send_break(duration=0.001)
        else:                            # break_condition
            ser.break_condition = True
            time.sleep(0.0002)
            ser.break_condition = False
        ser.write(frame)
        ser.flush()

    def sequence(self, secondes=6.0, break_baud=90000, methode="baud", fps=25):
        """Envoie un motif clignotant (1 s plein feu / 0,5 s noir).
        Renvoie (trames_envoyées, erreurs, fps_réels)."""
        plein = b"\x00" + bytes([255] * 512)
        noir = b"\x00" + bytes(512)
        periode = 1.0 / fps
        t0 = time.monotonic()
        envoyees = 0
        erreurs = 0
        while True:
            debut = time.monotonic()
            ecoule = debut - t0
            if ecoule >= secondes:
                break
            frame = noir if (ecoule % 1.5) >= 1.0 else plein
            try:
                self.trame(frame, break_baud, methode)
                envoyees += 1
            except Exception as e:
                erreurs += 1
                self.derniere_erreur = str(e)
                if erreurs > 15:
                    break
                time.sleep(0.01)
            reste = periode - (time.monotonic() - debut)
            if reste > 0.0005:
                time.sleep(reste)
        duree = max(time.monotonic() - t0, 0.001)
        return envoyees, erreurs, envoyees / duree

    def noir(self):
        """Éteint le parc avant de rendre la main."""
        try:
            for _ in range(15):
                self.trame(b"\x00" + bytes(512))
                time.sleep(0.02)
        except Exception:
            pass


# ── Déroulé d'un test ─────────────────────────────────────────────────────────
def jouer(sortie, intitule, secondes=6.0, **kw):
    """Joue une séquence clignotante et demande le verdict.
    Renvoie True (allumé), False (rien) ou None (abandon)."""
    while True:
        log("")
        log(f"  ▶  {intitule}", "gras")
        log(f"     {secondes:.0f} s — plein feu clignotant, REGARDEZ LES PROJECTEURS…", "dim")
        envoyees, erreurs, fps = sortie.sequence(secondes=secondes, **kw)
        detail = f"     {envoyees} trames à {fps:.0f} fps"
        if erreurs:
            log(detail + f", {erreurs} ERREURS ({sortie.derniere_erreur[:50]})", "err")
        else:
            log(detail + ", aucune erreur", "dim")
        if fps < 15:
            log("     ⚠  Cadence trop basse : un projecteur DMX coupe après ~1 s "
                "sans trame valide.", "warn")

        rep = demander("Les projecteurs ont-ils CLIGNOTÉ ?")
        if rep == "r":
            continue
        if rep == "q":
            return None
        resultat = (rep == "o")
        log(f"     → {'OUI, ça marche' if resultat else 'non'}",
            "ok" if resultat else "dim")
        return resultat


# ── Écriture du réglage dans la config MyStrow ────────────────────────────────
def enregistrer_reglage(mode_lignes):
    if not os.path.exists(CONFIG_MYSTROW):
        log(f"  ⚠  {CONFIG_MYSTROW} introuvable : configurez d'abord la sortie "
            "USB dans MyStrow, le réglage sera à refaire ici.", "warn")
        return
    try:
        with open(CONFIG_MYSTROW, "r") as f:
            cfg = json.load(f)
        cfg["serial_lines"] = mode_lignes
        tmp = CONFIG_MYSTROW + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_MYSTROW)      # écriture atomique
        log(f"  ✓  \"serial_lines\": \"{mode_lignes}\" enregistré dans {CONFIG_MYSTROW}", "ok")
    except Exception as e:
        log(f"  ✗  Écriture impossible ({e}) — ajoutez à la main dans "
            f"{CONFIG_MYSTROW} :  \"serial_lines\": \"{mode_lignes}\"", "err")


# ── Programme principal ───────────────────────────────────────────────────────
def main():
    titre("DIAGNOSTIC « BOÎTIER OPEN DMX MUET »")
    log(f"  Python {sys.version.split()[0]} · pyserial {serial.__version__} · {sys.platform}")
    # Le driver FTDI direct (méthode QLC+) est la solution de repli si aucun
    # réglage série ne marche : autant savoir tout de suite s'il est utilisable.
    try:
        import ftd2xx
        log(f"  Driver D2XX : disponible ({len(ftd2xx.listDevices() or [])} puce(s) vue(s))", "ok")
    except Exception as e:
        log(f"  Driver D2XX : indisponible ({type(e).__name__}) — repli série VCP obligatoire", "dim")
    log("")
    log("  ⚠  MyStrow doit être FERMÉ (deux writers sur la même puce FTDI", "warn")
    log("     faussent tous les résultats).", "warn")
    log("  ⚠  Un seul boîtier branché, câble XLR relié aux projecteurs,", "warn")
    log("     projecteurs en mode DMX (pas en automatique/son).", "warn")
    if demander("Prêt à commencer ?", "oq") == "q":
        return

    port = choisir_port(sys.argv)
    if not port:
        return

    log("")
    boitier = input("  Quel boîtier est branché ? (nom libre, ex: ENTTEC Open DMX USB) : ").strip()
    _journal.append(f"BOÎTIER TESTÉ : {boitier}")

    # ── Ouverture ────────────────────────────────────────────────────────────
    titre("2. OUVERTURE DU PORT")
    try:
        ser = serial.Serial(port=port, baudrate=DMX_BAUD,
                            bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                            stopbits=serial.STOPBITS_TWO, timeout=0.1)
    except Exception as e:
        log(f"  ✗  Échec : {e}", "err")
        msg = str(e).lower()
        if "resource busy" in msg or "access" in msg or "permission" in msg:
            log("  →  Le port est tenu par une autre application : fermez MyStrow "
                "(et QLC+ le cas échéant).", "warn")
        return
    log(f"  ✓  {port} ouvert à {DMX_BAUD} bauds, 8N2", "ok")

    sortie = Sortie(ser)
    resultats = {}
    gagnant_lignes = None
    try:
        # ── A. Lignes RTS / DTR ──────────────────────────────────────────────
        titre("3. TEST A — LIGNES DE CONTRÔLE RTS / DTR")
        log("  Sur un boîtier passif, la broche Driver Enable du transceiver", "dim")
        log("  RS485 peut être pilotée par RTS ou DTR. pyserial les asserte à", "dim")
        log("  l'ouverture : si le câblage attend l'inverse, l'émetteur est", "dim")
        log("  inhibé et RIEN ne sort, sans la moindre erreur côté Mac.", "dim")

        for mode in ("clear", "legacy", "rts", "dtr"):
            soucis = sortie.lignes(mode)
            for s in soucis:
                log(f"     ⚠  {s}", "warn")
            r = jouer(sortie, f"Lignes {LIGNES_LABEL[mode]}")
            if r is None:
                return
            resultats[f"lignes:{mode}"] = r
            if r:
                gagnant_lignes = mode
                break

        if gagnant_lignes:
            titre("RÉSULTAT")
            log(f"  ✓  TROUVÉ : {LIGNES_LABEL[gagnant_lignes]}", "ok")
            log("     C'était bien un problème de lignes de contrôle.", "ok")
            if demander("Enregistrer ce réglage dans la config MyStrow ?", "onq") == "o":
                enregistrer_reglage(gagnant_lignes)
            return

        log("")
        log("  ✗  Aucune combinaison RTS/DTR n'a réveillé le parc.", "warn")
        log("     → on continue avec le timing du signal.", "dim")
        sortie.lignes("clear")

        # ── B. Durée du break ────────────────────────────────────────────────
        titre("4. TEST B — DURÉE DU SIGNAL BREAK")
        log("  DMX512-A impose au transmetteur un break ≥ 92 µs. MyStrow émet", "dim")
        log("  100 µs : conforme, mais sans marge face à la gigue USB.", "dim")
        for baud, label in BREAKS.items():
            r = jouer(sortie, f"Break {label}", break_baud=baud)
            if r is None:
                return
            resultats[f"break:{label}"] = r
            if r:
                titre("RÉSULTAT")
                log(f"  ✓  TROUVÉ : le boîtier exige un break de {label}.", "ok")
                log("     → à répercuter dans BREAK_BAUD (artnet_dmx.py) : "
                    f"BREAK_BAUD = {baud}", "ok")
                return

        # ── C. Méthode de break ──────────────────────────────────────────────
        titre("5. TEST C — MÉTHODE DE GÉNÉRATION DU BREAK")
        for methode, label in (("send_break", "send_break(1 ms)"),
                               ("break_condition", "break_condition (200 µs)")):
            try:
                r = jouer(sortie, f"Break par {label}", methode=methode)
            except Exception as e:
                log(f"     ✗  {label} indisponible : {e}", "err")
                continue
            if r is None:
                return
            resultats[f"methode:{methode}"] = r
            if r:
                titre("RÉSULTAT")
                log(f"  ✓  TROUVÉ : ce boîtier veut {label}.", "ok")
                return

        # ── D. Cadence ───────────────────────────────────────────────────────
        titre("6. TEST D — CADENCE D'ENVOI")
        for fps in (40, 10):
            r = jouer(sortie, f"Envoi à {fps} fps", fps=fps)
            if r is None:
                return
            resultats[f"fps:{fps}"] = r
            if r:
                titre("RÉSULTAT")
                log(f"  ✓  TROUVÉ : le boîtier veut {fps} fps.", "ok")
                return

        # ── Rien n'a marché ──────────────────────────────────────────────────
        titre("RÉSULTAT")
        log("  ✗  Aucun réglage logiciel ne réveille ce boîtier.", "err")
        log("")
        log("  Le problème n'est donc PAS dans la façon dont MyStrow parle au", "warn")
        log("  port série. Restent, par ordre de probabilité :", "warn")
        log("   1. Câble XLR / adresse DMX / mode du projecteur — vérifiez en", "dim")
        log("      rebranchant le boîtier qui fonctionne SANS rien changer d'autre.", "dim")
        log("   2. Le boîtier exige le driver FTDI D2XX (méthode QLC+), que le", "dim")
        log("      pilote Apple ne laisse pas prendre la main sur macOS.", "dim")
        log("   3. Boîtier ou fusible/transceiver HS — testez-le sur un PC Windows.", "dim")

    except KeyboardInterrupt:
        log("\n  Interrompu.", "warn")
    finally:
        try:
            sortie.noir()
            ser.close()
        except Exception:
            pass
        log("")
        log("  Port refermé, parc éteint.", "dim")
        try:
            with open(RAPPORT, "w") as f:
                f.write("\n".join(_journal) + "\n")
            log(f"  Rapport écrit dans {RAPPORT}", "dim")
        except Exception:
            pass


if __name__ == "__main__":
    main()
