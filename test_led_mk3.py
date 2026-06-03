"""
Test LED direct — Novation Launchpad Mini MK3
Lance ce script APRES avoir fermé MyStrow (le port MIDI est exclusif sous Windows).

    python test_led_mk3.py

Si 5 pads s'allument en couleur pendant 4 secondes, le protocole MK3 est bon.
"""
import time

try:
    import rtmidi
    mo = rtmidi.MidiOut()
except ImportError:
    import rtmidi2 as rtmidi
    mo = rtmidi.MidiOut()

outs = mo.get_ports()
print("Ports OUT detectes :", outs)

# Trouver le port MIDI du Launchpad (PAS le port DAW = MIDIOUT2)
idx = None
for i, p in enumerate(outs):
    up = p.upper()
    if 'LPMINIMK3' in up and 'MIDIOUT2' not in up and 'DAW' not in up:
        idx = i
        break

if idx is None:
    print("\n❌ Port MIDI du Launchpad introuvable.")
    print("   -> Le Launchpad est-il branché ? MyStrow est-il bien fermé ?")
    raise SystemExit(1)

print(f"Port choisi : {outs[idx]}")
try:
    mo.open_port(idx)
except Exception as e:
    print(f"\n❌ Impossible d'ouvrir le port : {e}")
    print("   -> Une autre app tient le port. Ferme MyStrow (et toute instance fantôme).")
    raise SystemExit(1)

# 1) Passage en Programmer mode (indispensable pour piloter les LED par note)
mo.send_message([0xF0, 0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x01, 0xF7])
time.sleep(0.1)

# 2) Allumer 5 pads (note = ligne*10 + colonne, velocity = index palette Novation)
tests = [(11, 5), (18, 21), (81, 3), (88, 72), (45, 13)]
for note, vel in tests:
    mo.send_message([0x90, note, vel])
    print(f"  pad note {note} -> velocity {vel}")

print("\n>>> Regarde le Launchpad : 5 pads colorés pendant 4 secondes...")
time.sleep(4)

# 3) Tout éteindre
for row in range(1, 9):
    for col in range(1, 9):
        mo.send_message([0x90, row * 10 + col, 0])

print("Pads éteints. Test terminé ✅")
mo.close_port()
