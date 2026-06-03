"""
Moniteur MIDI interactif — Novation Launchpad Mini MK3
Ferme MyStrow avant de lancer (port MIDI exclusif sous Windows) :

    python lp_mk3_monitor.py

Appuie sur les pads : chaque message est décodé en direct.
Le script renvoie aussi une LED verte sur le pad pressé (test sortie simultané).
Ctrl+C pour quitter.
"""
import sys
import time

# Forcer UTF-8 pour éviter les plantages d'encodage console Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import rtmidi
    USING2 = False
except ImportError:
    import rtmidi2 as rtmidi
    USING2 = True

mi = rtmidi.MidiIn()
mo = rtmidi.MidiOut()


def pick(ports):
    for i, p in enumerate(ports):
        up = p.upper()
        if "LPMINIMK3" in up and "MIDIIN2" not in up and "MIDIOUT2" not in up and "DAW" not in up:
            return i, p
    return None, None


in_ports = mi.get_ports()
out_ports = mo.get_ports()
print("Ports IN :", in_ports)
print("Ports OUT:", out_ports)

in_idx, in_name = pick(in_ports)
out_idx, out_name = pick(out_ports)
if in_idx is None:
    print("\n[X] Port IN du Launchpad introuvable (branche-le / ferme MyStrow).")
    raise SystemExit(1)

mi.open_port(in_idx)
print(f"\nIN  ouvert : {in_name}")
if out_idx is not None:
    mo.open_port(out_idx)
    print(f"OUT ouvert : {out_name}")
    # Programmer mode ON
    mo.send_message([0xF0, 0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x01, 0xF7])
    print("SysEx Programmer mode envoyé.")
else:
    print("OUT introuvable : pas de retour LED (analyse entrée seulement).")

print("\n--- Appuie sur les pads (Ctrl+C pour quitter) ---")
print("    En Programmer mode, la grille = notes 11..88 (ligne*10 + colonne).\n")


def decode(msg):
    if not msg:
        return
    status = msg[0]
    d1 = msg[1] if len(msg) > 1 else 0
    d2 = msg[2] if len(msg) > 2 else 0
    stype = status & 0xF0
    chan = status & 0x0F
    raw = " ".join(f"{b:02X}" for b in msg)

    if stype == 0x90 and d2 > 0:
        kind = "NOTE ON "
    elif stype == 0x80 or (stype == 0x90 and d2 == 0):
        kind = "NOTE OFF"
    elif stype == 0xB0:
        kind = "CC      "
    else:
        kind = f"0x{status:02X}  "

    # Interprétation Programmer mode
    row = d1 // 10
    col = d1 % 10
    prog = ""
    if stype in (0x80, 0x90):
        if 1 <= row <= 8 and 1 <= col <= 9:
            zone = "grille" if col <= 8 else "scène (droite)"
            prog = f"  -> Programmer: ligne {row}, col {col} ({zone})"
        else:
            prog = "  -> hors grille programmer (note inattendue)"
    elif stype == 0xB0:
        if 91 <= d1 <= 98:
            prog = f"  -> top row bouton {d1 - 90}"
        elif d1 == 99:
            prog = "  -> logo"

    print(f"[{kind}] ch{chan:<2} data1={d1:<3} data2={d2:<3}  (raw {raw}){prog}")

    # Retour LED : allume le pad pressé en vert, éteint au relâché
    if out_idx is not None and stype in (0x80, 0x90) and 1 <= row <= 8 and 1 <= col <= 9:
        vel = 21 if (stype == 0x90 and d2 > 0) else 0
        try:
            mo.send_message([0x90, d1, vel])
        except Exception:
            pass


try:
    while True:
        if USING2:
            # rtmidi2 : callback-based ; fallback simple via get_message si dispo
            msg = mi.get_message() if hasattr(mi, "get_message") else None
            if msg:
                decode(list(msg))
            else:
                time.sleep(0.005)
        else:
            ev = mi.get_message()  # (message, deltatime) ou None
            if ev:
                decode(ev[0])
            else:
                time.sleep(0.005)
except KeyboardInterrupt:
    print("\nArrêt.")
finally:
    try:
        mi.close_port()
    except Exception:
        pass
    try:
        mo.close_port()
    except Exception:
        pass
