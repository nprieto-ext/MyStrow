#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostic AKAI APC20 — mapping des boutons et pilotage des LEDs.

Autonome : n'importe RIEN de MyStrow, pour qu'un souci de l'application ne
fausse pas le resultat. ⚠ FERMER MyStrow avant de lancer ce script : sous
Windows un port MIDI ne peut etre ouvert que par UNE application a la fois.

Deux choses a verifier :

1. LED — a la mise sous tension l'APC20 demarre en « Generic Mode » (0x40) ou
   il allume SES PROPRES LEDs et ignore les Note On de l'hote. Le SysEx
   d'introduction (product ID 0x7B, mode 0x41 « Ableton Live Mode ») rend la
   main a l'hote. Le test allume la grille AVANT puis APRES ce SysEx : si
   seule la 2e phase allume les pads de clips, le diagnostic est confirme.

2. ENTREE — le script affiche chaque message recu, decode selon le layout
   APC20 (ligne/colonne MyStrow). Appuyer sur les boutons qui « ne repondent
   pas » dit exactement ce qu'ils envoient — ou s'ils n'envoient rien.

Usage (remplacer `python3` par `python` sous Windows) :

    python3 diag_apc20.py            # test LED complet puis ecoute
    python3 diag_apc20.py --ecoute   # ecoute seule (aucun SysEx envoye)
    python3 diag_apc20.py --generic  # remet le boitier en Generic Mode et sort
"""
import sys
import time

# ── Import rtmidi (meme strategie que midi_handler.py) ───────────────────────
rtmidi = None
try:
    import rtmidi
except ImportError:
    try:
        import rtmidi2 as rtmidi
    except ImportError:
        print("Ni python-rtmidi ni rtmidi2 n'est installe.")
        print("   -> pip3 install python-rtmidi")
        sys.exit(1)

MOTS_CLES = ("APC20", "APC 20")

# SysEx d'introduction Akai : F0 47 7F <product> 60 00 04 <mode> <ver> F7
#   product APC20 = 0x7B   ·   0x40 = Generic, 0x41 = Ableton Live Mode
SYSEX_ABLETON = [0xF0, 0x47, 0x7F, 0x7B, 0x60, 0x00, 0x04, 0x41, 0x00, 0x00, 0x00, 0xF7]
SYSEX_GENERIC = [0xF0, 0x47, 0x7F, 0x7B, 0x60, 0x00, 0x04, 0x40, 0x00, 0x00, 0x00, 0xF7]

CLIP_BASE   = 53          # notes 53-57 = lignes 0-4 (53 = ligne du HAUT)
SCENE_BASE  = 82          # notes 82-86 = colonne 8 (effets), 5 boutons
STOP_ALL    = 81          # STOP ALL CLIPS, sous les 5 scene launch
SHIFT       = 98
ROW_NOTES   = {52: 5, 50: 6, 49: 7}   # CLIP STOP / ACTIVATOR / SOLO
MUTE_NOTE   = 48                      # REC ARM, rangee collee aux faders


def concerne(nom: str) -> bool:
    return any(k in nom.upper() for k in MOTS_CLES)


def decrire(msg):
    """Traduit un message APC20 en position MyStrow."""
    if not msg:
        return ""
    st = msg[0]
    if st == 0xF0:
        return "SysEx (reponse du boitier)"
    if len(msg) < 3:
        return f"status {hex(st)}"
    type_, canal = st & 0xF0, st & 0x0F
    d1, d2 = msg[1], msg[2]

    if type_ == 0xB0:
        if d1 == 7 and canal <= 7:
            return f"CC7 = {d2} (canal {canal})   -> FADER piste {canal + 1}"
        if d1 == 14 and canal == 0:
            return f"CC14 = {d2}   -> FADER MASTER"
        return f"CC {d1} = {d2} (canal {canal})   -> ? non mappe"

    if type_ not in (0x90, 0x80):
        return f"status {hex(st)}"

    nom = "Note ON " if (type_ == 0x90 and d2 > 0) else "Note OFF"
    txt = f"{nom} note {d1:3d} vel {d2:3d} (canal {canal})"

    if canal <= 7 and CLIP_BASE <= d1 <= CLIP_BASE + 4:
        return txt + f"   -> GRILLE ligne {d1 - CLIP_BASE}, colonne {canal} (clip launch)"
    if canal <= 7 and d1 in ROW_NOTES:
        etiq = {52: "CLIP STOP", 50: "ACTIVATOR", 49: "SOLO/CUE"}[d1]
        return txt + f"   -> GRILLE ligne {ROW_NOTES[d1]}, colonne {canal} ({etiq})"
    if canal <= 7 and d1 == MUTE_NOTE:
        return txt + f"   -> MUTE fader {canal + 1} (REC ARM)"
    if canal == 0 and SCENE_BASE <= d1 <= SCENE_BASE + 4:
        return txt + f"   -> EFFET ligne {d1 - SCENE_BASE} (scene launch {d1 - SCENE_BASE + 1})"
    if canal == 0 and d1 == STOP_ALL:
        return txt + "   -> STOP ALL CLIPS   (NON MAPPE dans MyStrow)"
    if canal == 0 and d1 == SHIFT:
        return txt + "   -> SHIFT   (TAP TEMPO / GO / FLASH)"
    return txt + "   -> ?? NON MAPPE"


def ouvrir(port_cls, filtre=True):
    """Ouvre le premier port APC20 trouve. Retourne (objet, nom) ou (None, None)."""
    probe = port_cls()
    ports = probe.get_ports()
    for i, p in enumerate(ports):
        if not filtre or concerne(p):
            obj = port_cls()
            try:
                obj.open_port(i)
                return obj, p
            except Exception as e:
                print(f"   impossible d'ouvrir [{i}] {p} : {e}")
                print("   -> MyStrow (ou une autre appli) tient-il deja le port ?")
                return None, None
    return None, None


def allumer_tout(mo, vel_clip, vel_piste):
    """Allume la grille (clips + 3 rangees de boutons de piste) et les scenes."""
    for track in range(8):
        for row in range(5):
            mo.send_message([0x90 | track, CLIP_BASE + row, vel_clip])
        for note in ROW_NOTES:
            mo.send_message([0x90 | track, note, vel_piste])
    for row in range(5):
        mo.send_message([0x90, SCENE_BASE + row, vel_piste])


def eteindre_tout(mo):
    allumer_tout(mo, 0, 0)
    for track in range(8):
        mo.send_message([0x90 | track, MUTE_NOTE, 0])


def main():
    ecoute_seule = "--ecoute" in sys.argv
    retour_generic = "--generic" in sys.argv

    print("=" * 72)
    print("  DIAGNOSTIC AKAI APC20")
    print("=" * 72)
    print(f"  Python {sys.version.split()[0]}  ·  plateforme {sys.platform}")
    print(f"  backend rtmidi : {getattr(rtmidi, '__name__', '?')}")
    print()

    probe_in, probe_out = rtmidi.MidiIn(), rtmidi.MidiOut()
    print("-- PORTS D'ENTREE (controleur -> ordinateur) " + "-" * 26)
    for i, p in enumerate(probe_in.get_ports()):
        print(f"   [{i}] {p}" + ("  <-- retenu" if concerne(p) else ""))
    print("-- PORTS DE SORTIE (ordinateur -> controleur) " + "-" * 25)
    for i, p in enumerate(probe_out.get_ports()):
        print(f"   [{i}] {p}" + ("  <-- retenu" if concerne(p) else ""))
    print()

    mo, nom_out = ouvrir(rtmidi.MidiOut)
    if mo is None:
        print("Aucun port de SORTIE APC20 : impossible de tester les LEDs.")
    mi, nom_in = ouvrir(rtmidi.MidiIn)
    if mi is None:
        print("Aucun port d'ENTREE APC20 : le boitier est-il branche ?")
        return

    if retour_generic:
        if mo:
            eteindre_tout(mo)
            mo.send_message(SYSEX_GENERIC)
            print("Generic Mode (0x40) renvoye au boitier. Fin.")
        return

    # ── 1. Test LED ──────────────────────────────────────────────────────────
    if mo and not ecoute_seule:
        print("=" * 72)
        print("  TEST LED — REGARDER LE BOITIER")
        print("=" * 72)
        # On force l'etat de mise sous tension, sinon un 2e passage du script
        # heriterait du mode Ableton laisse par le 1er et la phase 1 mentirait.
        mo.send_message(SYSEX_GENERIC)
        time.sleep(0.05)
        eteindre_tout(mo)
        time.sleep(0.3)

        print("\nPHASE 1 (8 s) — SANS SysEx, tel que le boitier demarre.")
        print("  On demande : grille de clips en VERT + boutons de piste allumes.")
        allumer_tout(mo, 1, 1)
        for s in range(8, 0, -1):
            print(f"    ...{s} ", end="\r", flush=True)
            time.sleep(1)
        print("  -> Les 5 lignes de CLIP LAUNCH se sont-elles allumees ?        ")

        eteindre_tout(mo)
        time.sleep(0.3)

        print("\nPHASE 2 (8 s) — APRES le SysEx d'introduction (mode 0x41).")
        mo.send_message(SYSEX_ABLETON)
        time.sleep(0.05)
        print("  On demande : grille de clips en ROUGE + boutons de piste allumes.")
        allumer_tout(mo, 3, 1)
        for s in range(8, 0, -1):
            print(f"    ...{s} ", end="\r", flush=True)
            time.sleep(1)
        print("  -> Si la grille est ROUGE maintenant alors qu'elle etait       ")
        print("     eteinte en phase 1 : c'etait bien le Generic Mode.")
        eteindre_tout(mo)
        print()

    # ── 2. Ecoute ────────────────────────────────────────────────────────────
    print("=" * 72)
    print("  ECOUTE — APPUYER SUR LES BOUTONS")
    print("=" * 72)
    print(f"  Port : {nom_in}")
    print("  Appuyer en particulier sur les boutons qui NE REPONDENT PAS")
    print("  dans MyStrow (colonne d'effets a droite, lignes du bas...).")
    print("  Ctrl+C pour arreter et afficher le recapitulatif.\n")

    vus = {}
    try:
        while True:
            res = mi.get_message()
            if res:
                msg, _dt = res
                cle = (msg[0] & 0xF0, msg[0] & 0x0F, msg[1] if len(msg) > 1 else -1)
                vus[cle] = vus.get(cle, 0) + 1
                print("   " + decrire(msg))
            else:
                time.sleep(0.001)
    except KeyboardInterrupt:
        pass

    print("\n" + "=" * 72)
    print("  RECAPITULATIF — messages distincts recus")
    print("=" * 72)
    if not vus:
        print("   AUCUN message recu : le boitier n'emet rien sur ce port.")
    for (type_, canal, d1), n in sorted(vus.items()):
        print(f"   type {hex(type_)} canal {canal} data1 {d1:3d}   x{n}")
    print()


if __name__ == "__main__":
    main()
