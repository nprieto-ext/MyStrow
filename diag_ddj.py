"""
Diagnostic MIDI brut — DDJ-400 (ou n'importe quel contrôleur).

But : savoir si Windows laisse MyStrow ouvrir le port du contrôleur, et voir
ce que les pads envoient réellement (canal / note / vélocité).

Usage :
    python diag_ddj.py            → liste les ports, ouvre TOUS ceux qu'il peut
    python diag_ddj.py 2          → n'ouvre que le port n°2

À faire DEUX fois :
    1) VirtualDJ FERMÉ   → doit s'ouvrir et afficher les appuis
    2) VirtualDJ OUVERT  → si "ECHEC d'ouverture", le port est monopolisé
"""
import sys
import time

try:
    import rtmidi
except ImportError:
    import rtmidi2 as rtmidi

NOTE_NAMES = {0x80: "NoteOff", 0x90: "NoteOn", 0xA0: "AfterT", 0xB0: "CC    ",
              0xC0: "PgmChg", 0xD0: "ChanAT", 0xE0: "PitchB"}


def show(port_name):
    def cb(event, data=None):
        msg, _dt = event
        if not msg:
            return
        status = msg[0]
        kind = NOTE_NAMES.get(status & 0xF0, f"0x{status:02X}")
        ch = (status & 0x0F) + 1
        d1 = msg[1] if len(msg) > 1 else 0
        d2 = msg[2] if len(msg) > 2 else 0
        raw = " ".join(f"{b:02X}" for b in msg)
        print(f"[{port_name:<28}] {kind} ch{ch:<2} d1={d1:<3} d2={d2:<3}   brut: {raw}")
    return cb


def main():
    probe = rtmidi.MidiIn()
    ports = probe.get_ports()

    print("=" * 78)
    print("PORTS MIDI D'ENTREE VUS PAR WINDOWS")
    print("=" * 78)
    if not ports:
        print("  (aucun) — le contrôleur n'est pas branché, ou son pilote n'est pas installé.")
        return
    for i, p in enumerate(ports):
        print(f"  [{i}] {p}")
    print()

    wanted = None
    if len(sys.argv) > 1:
        wanted = int(sys.argv[1])

    opened = []
    for i, p in enumerate(ports):
        if wanted is not None and i != wanted:
            continue
        try:
            m = rtmidi.MidiIn()
            m.open_port(i)
            m.set_callback(show(p))
            m.ignore_types(sysex=False, timing=True, active_sense=True)
            opened.append((p, m))
            print(f"  OK      port [{i}] ouvert  : {p}")
        except Exception as e:
            print(f"  ECHEC   port [{i}] refusé  : {p}")
            print(f"          -> {type(e).__name__}: {e}")
            print("          (typiquement : une autre application le tient — VirtualDJ, rekordbox…)")

    if not opened:
        print("\nAucun port ouvert. Fermez le logiciel DJ et relancez ce script.")
        return

    print("\n" + "=" * 78)
    print("APPUYEZ SUR LES PADS / BOUGEZ LES FADERS — 40 s d'écoute (Ctrl+C pour arrêter)")
    print("=" * 78)
    try:
        time.sleep(40)
    except KeyboardInterrupt:
        pass
    finally:
        for _p, m in opened:
            try:
                m.close_port()
            except Exception:
                pass
    print("\nFin.")


if __name__ == "__main__":
    main()
