#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostic Launchpad Mini MK3 — « les LED s'allument mais rien ne rentre ».

Fonctionne sur Windows, macOS et Linux. Autonome : n'importe RIEN de MyStrow,
pour qu'un souci de l'application ne fausse pas le résultat. Ouvre TOUTES les
entrées MIDI du contrôleur en même temps et affiche, pour chaque message reçu,
LE PORT qui l'a émis — c'est la seule façon de savoir si les pads parlent sur
le port DAW, sur le port MIDI, ou sur aucun des deux.

Usage (remplacer `python3` par `python` sous Windows) :

    python3 diag_launchpad.py                # écoute (mode actuel du boîtier)
    python3 diag_launchpad.py --programmer   # bascule en Programmer mode d'abord
    python3 diag_launchpad.py --live         # bascule en Live mode d'abord
    python3 diag_launchpad.py --leds         # test LED puis écoute
    python3 diag_launchpad.py --all          # écoute TOUS les ports MIDI de la machine

Appuyer sur des pads, puis Ctrl+C : un récapitulatif indique quel port a parlé.

Le lancer sur la machine où ça MARCHE est tout aussi utile : la trace obtenue
sert de référence à comparer avec celle de la machine où ça ne marche pas.
"""
import sys
import time

# ── Import rtmidi (même stratégie que midi_handler.py) ───────────────────────
rtmidi = None
try:
    import rtmidi
except ImportError:
    try:
        import rtmidi2 as rtmidi
    except ImportError:
        print("❌ Ni python-rtmidi ni rtmidi2 n'est installé.")
        print("   → pip3 install python-rtmidi")
        sys.exit(1)

MOTS_CLES = ("LAUNCHPAD", "LPMINI", "MINI MK3")

# Programmer mode ON / Live mode — SysEx Novation Launchpad Mini MK3
SYSEX_PROGRAMMER = [0xF0, 0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x01, 0xF7]
SYSEX_LIVE       = [0xF0, 0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x00, 0xF7]
# Identity Request universel : si le boîtier répond, la liaison est bidirectionnelle
SYSEX_IDENTITY   = [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]


def concerne(nom: str, tout: bool) -> bool:
    return True if tout else any(k in nom.upper() for k in MOTS_CLES)


def decrire(msg):
    """Traduit un message MIDI en clair, avec la position Programmer mode."""
    if not msg:
        return ""
    st = msg[0]
    if st == 0xF0:
        return "SysEx (réponse du boîtier)"
    if len(msg) < 3:
        return ""
    canal = (st & 0x0F) + 1
    d1, d2 = msg[1], msg[2]
    type_ = st & 0xF0

    if type_ == 0xB0:
        txt = f"CC {d1} = {d2}  (canal {canal})"
        if 91 <= d1 <= 98:
            txt += f"   → rangée du haut, bouton {d1 - 90}"
        elif d1 % 10 == 9 and 1 <= d1 // 10 <= 8:
            txt += f"   → colonne droite (scène), ligne {9 - d1 // 10} en partant du haut"
        return txt

    if type_ in (0x90, 0x80):
        nom = "Note ON " if (type_ == 0x90 and d2 > 0) else "Note OFF"
        txt = f"{nom} note {d1} vel {d2}  (canal {canal})"
        ligne, col = divmod(d1, 10)
        if 1 <= ligne <= 8 and 1 <= col <= 9:
            txt += f"   → PROGRAMMER MODE : ligne {9 - ligne} (haut=1), colonne {col}"
        else:
            txt += "   → ⚠ HORS grille Programmer mode (le boîtier est probablement en Live mode)"
        return txt

    return f"status {hex(st)}"


def main():
    tout       = "--all" in sys.argv
    programmer = "--programmer" in sys.argv
    live       = "--live" in sys.argv
    leds       = "--leds" in sys.argv

    print("=" * 72)
    print("  DIAGNOSTIC LAUNCHPAD MINI MK3")
    print("=" * 72)
    print(f"  Python {sys.version.split()[0]}  ·  plateforme {sys.platform}")
    print(f"  backend rtmidi : {getattr(rtmidi, '__name__', '?')}")
    print()

    # ── Inventaire ───────────────────────────────────────────────────────────
    probe_in  = rtmidi.MidiIn()
    probe_out = rtmidi.MidiOut()
    ports_in  = probe_in.get_ports()
    ports_out = probe_out.get_ports()

    print("── PORTS D'ENTRÉE (contrôleur → ordinateur) " + "─" * 27)
    if not ports_in:
        print("   (aucun)")
    for i, p in enumerate(ports_in):
        marque = "  ←── retenu" if concerne(p, tout) else ""
        print(f"   [{i}] {p}{marque}")
    print()
    print("── PORTS DE SORTIE (ordinateur → contrôleur) " + "─" * 26)
    if not ports_out:
        print("   (aucun)")
    for i, p in enumerate(ports_out):
        marque = "  ←── retenu" if concerne(p, tout) else ""
        print(f"   [{i}] {p}{marque}")
    print()

    cibles_in  = [(i, p) for i, p in enumerate(ports_in)  if concerne(p, tout)]
    cibles_out = [(i, p) for i, p in enumerate(ports_out) if concerne(p, tout)]

    if not cibles_in:
        print("❌ Aucun port d'entrée ne correspond au Launchpad.")
        print("   Le boîtier est-il branché et reconnu par le système ?")
        if sys.platform == "darwin":
            print("   → Applications ▸ Utilitaires ▸ Configuration audio et MIDI")
        elif sys.platform == "win32":
            print("   → Gestionnaire de périphériques ▸ Contrôleurs audio, vidéo et jeu")
        print("   Relancer avec --all pour écouter tous les ports de la machine.")
        return

    # ── Sorties : mode + LED ─────────────────────────────────────────────────
    sorties = []
    for idx, nom in cibles_out:
        try:
            mo = rtmidi.MidiOut()
            mo.open_port(idx)
            sorties.append((nom, mo))
        except Exception as e:
            print(f"⚠  Sortie non ouvrable [{idx}] {nom} : {e}")

    if programmer or live:
        sysex = SYSEX_PROGRAMMER if programmer else SYSEX_LIVE
        libelle = "Programmer mode" if programmer else "Live mode"
        print(f"── Bascule en {libelle} " + "─" * (49 - len(libelle)))
        for nom, mo in sorties:
            try:
                mo.send_message(sysex)
                print(f"   ✔ SysEx envoyé sur : {nom}")
            except Exception as e:
                print(f"   ✖ Échec sur {nom} : {e}")
        time.sleep(0.2)
        print()

    if leds:
        print("── Test LED " + "─" * 60)
        print("   Une diagonale doit s'allumer sur la grille.")
        for nom, mo in sorties:
            try:
                for n in range(1, 9):
                    mo.send_message([0x90, n * 10 + n, 5 + n * 6])
                    time.sleep(0.05)
                print(f"   ✔ LED envoyées sur : {nom}")
            except Exception as e:
                print(f"   ✖ Échec LED sur {nom} : {e}")
        print()

    # Identity request : prouve que le boîtier répond
    for nom, mo in sorties:
        try:
            mo.send_message(SYSEX_IDENTITY)
        except Exception:
            pass

    # ── Entrées : on ouvre TOUT ce qui correspond ────────────────────────────
    compteurs = {}
    entrees   = []

    def fabrique_callback(nom_port):
        def cb(event, data=None):
            msg, _dt = event
            msg = list(msg)
            compteurs[nom_port] = compteurs.get(nom_port, 0) + 1
            horo = time.strftime("%H:%M:%S")
            hexa = " ".join(f"{b:02X}" for b in msg)
            print(f"[{horo}] {nom_port}")
            print(f"          {hexa:<28} {decrire(msg)}")
        return cb

    print("── Ouverture des entrées " + "─" * 47)
    for idx, nom in cibles_in:
        try:
            mi = rtmidi.MidiIn()
            mi.open_port(idx)
            # On NE filtre PAS le SysEx : la réponse d'identité est un indice utile.
            try:
                mi.ignore_types(sysex=False, timing=True, active_sense=True)
            except Exception:
                pass
            mi.set_callback(fabrique_callback(nom))
            entrees.append((nom, mi))
            compteurs[nom] = 0
            print(f"   ✔ {nom}")
        except Exception as e:
            print(f"   ✖ {nom} : {e}")

    if not entrees:
        print("\n❌ Aucune entrée n'a pu être ouverte.")
        print("   Une autre application retient probablement le Launchpad")
        print("   (Ableton, Novation Components, MyStrow déjà lancé…). Fermez-la et réessayez.")
        return

    print()
    print("=" * 72)
    print("  APPUYEZ SUR DES PADS  —  Ctrl+C pour le récapitulatif")
    print("=" * 72)
    print()

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass

    # ── Récapitulatif ────────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  RÉCAPITULATIF")
    print("=" * 72)
    total = 0
    for nom, n in compteurs.items():
        print(f"   {n:5} message(s)   {nom}")
        total += n

    print()
    if total == 0:
        print("  ❌ AUCUN message reçu, sur aucun port.")
        print()
        print("  Le problème est en amont de MyStrow. À vérifier, dans l'ordre :")
        print("   1. Une autre app tient le Launchpad (Ableton, Novation Components,")
        print("      MyStrow déjà lancé…). Fermez-la et relancez.")
        print("   2. Changer de câble et de port USB — beaucoup de câbles sont")
        print("      charge seule et ne transportent aucune donnée.")
        if sys.platform == "darwin":
            print("   3. Configuration audio et MIDI ▸ Fenêtre ▸ Studio MIDI :")
            print("      le Launchpad y apparaît-il ?")
            print("   4. Un profil MDM d'entreprise peut bloquer les périphériques USB.")
        elif sys.platform == "win32":
            print("   3. Gestionnaire de périphériques : le Launchpad apparaît-il")
            print("      sans point d'exclamation jaune ?")
    else:
        parle = [n for n, c in compteurs.items() if c]
        print(f"  ✅ {total} message(s) reçu(s), sur : {', '.join(parle)}")
        print()
        print("  → Envoyez-moi ce récapitulatif ET quelques lignes de messages")
        print("    ci-dessus : le port qui parle et le layout des notes me disent")
        print("    exactement quoi corriger dans MyStrow.")
    print()

    for _, mi in entrees:
        try: mi.close_port()
        except Exception: pass
    for _, mo in sorties:
        try: mo.close_port()
        except Exception: pass


if __name__ == "__main__":
    main()
