#!/usr/bin/env python3
"""Diagnostic ENTTEC sur macOS — isole la sortie DMX de l'interface graphique.

But : savoir si le crash « je clique Connecter, ça charge en boucle et ça
plante » vient bien de DEUX threads writers sur le même port série.

    python3 diag_enttec_mac.py                 # liste les ports
    python3 diag_enttec_mac.py --port /dev/cu.usbserial-XXXX
    python3 diag_enttec_mac.py --port ... --force-bug

Phase 1 rejoue le scénario réel (connexion au démarrage + clic « Connecter »)
et vérifie qu'il ne reste qu'un seul thread.
Phase 2 (--force-bug) démarre DÉLIBÉRÉMENT un 2e thread pour reproduire l'état
d'avant correctif sur le vrai matériel : c'est l'expérience qui dit si ce
doublon suffit à figer le port.

⚠️  Ce script envoie du vrai DMX : les projecteurs branchés vont réagir.
Fichier temporaire de diagnostic — supprimable une fois le sujet clos.
"""
import argparse
import platform
import sys
import threading
import time

try:
    import serial.tools.list_ports
except ImportError:
    print("pyserial manquant :  pip3 install pyserial")
    sys.exit(1)

from artnet_dmx import ArtNetDMX, TRANSPORT_ENTTEC, TRANSPORT_ENTTEC_PRO


def writer_threads():
    return [t for t in threading.enumerate()
            if t.is_alive() and t.name in ("EnttecDMX", "EnttecProDMX")]


def show_threads(label):
    ts = writer_threads()
    names = [f"{t.name}#{t.ident}" for t in ts]
    print(f"    {label:38s} -> {len(ts)} thread(s) {names}")
    return len(ts)


def list_ports():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("Aucun port série détecté. Le boîtier est-il branché ?")
        print("Sur macOS, un Open DMX USB apparaît en /dev/cu.usbserial-…")
        return
    print("Ports série détectés :\n")
    for p in ports:
        vid = f"{p.vid:04X}" if p.vid else "----"
        pid = f"{p.pid:04X}" if p.pid else "----"
        ftdi = "  <- puce FTDI" if p.vid == 0x0403 else ""
        print(f"  {p.device}")
        print(f"      {p.description}")
        print(f"      VID:PID = {vid}:{pid}   SN={p.serial_number}{ftdi}")
    print("\nRelancez avec :  python3 diag_enttec_mac.py --port <chemin>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="ex. /dev/cu.usbserial-AB12CD34")
    ap.add_argument("--pro", action="store_true",
                    help="boîtier ENTTEC DMX USB Pro (et non Open DMX USB)")
    ap.add_argument("--force-bug", action="store_true",
                    help="démarre volontairement un 2e thread (état d'avant correctif)")
    ap.add_argument("--seconds", type=int, default=20,
                    help="durée d'observation de la phase 2 (défaut 20 s)")
    ap.add_argument("--save-config", action="store_true",
                    help="autoriser l'écriture de ~/.mystrow_dmx.json "
                         "(désactivé par défaut : ne rien laisser sur une "
                         "machine empruntée)")
    args = ap.parse_args()

    print("=" * 68)
    print(f"  Python {sys.version.split()[0]} · {platform.platform()}")
    print(f"  sys.platform = {sys.platform!r}", end="")
    print("   (baud-rate trick actif)" if sys.platform == "darwin" else "")
    try:
        from artnet_dmx import FTD2XX_AVAILABLE
        print(f"  FTD2XX_AVAILABLE = {FTD2XX_AVAILABLE}", end="")
        print("   -> Open DMX piloté en série VCP" if not FTD2XX_AVAILABLE else "")
    except Exception:
        pass
    print("=" * 68)

    if not args.port:
        list_ports()
        return

    transport = TRANSPORT_ENTTEC_PRO if args.pro else TRANSPORT_ENTTEC
    dmx = ArtNetDMX()

    # connect() persiste le transport dans ~/.mystrow_dmx.json. Sur une machine
    # qui n'est pas la vôtre, on neutralise l'écriture par défaut.
    if not args.save_config:
        dmx._save_config = lambda *a, **k: None
        print("\n(config non persistée — aucun fichier créé ; "
              "--save-config pour l'autoriser)")

    # Un canal à fond pour voir quelque chose sortir.
    try:
        dmx.dmx_data[0][0] = 255
    except Exception:
        pass

    print(f"\n--- PHASE 1 : scénario réel sur {args.port} ---")
    print("  (a) connexion au démarrage de l'app")
    ok1 = dmx.connect(transport=transport, com_port=args.port)
    print(f"      connect() -> {ok1}")
    time.sleep(1.0)
    n1 = show_threads("après la connexion de démarrage")

    print("  (b) clic sur « Connecter » dans l'assistant")
    ok2 = dmx.connect(transport=transport, com_port=args.port)
    print(f"      connect() -> {ok2}")
    time.sleep(1.0)
    n2 = show_threads("après le clic Connecter")

    if n2 > 1:
        print("\n  >>> BUG PRÉSENT : plusieurs writers. Ce code n'a pas le correctif.")
    else:
        print("\n  >>> OK : un seul writer. Le correctif est actif.")

    if args.force_bug:
        print(f"\n--- PHASE 2 : on force un 2e thread pendant {args.seconds} s ---")
        print("  Objectif : voir si le doublon suffit à figer le port / planter.")
        print("  Surveillez les projecteurs (strobe, saccades) et les erreurs ci-dessous.\n")
        dmx._start_enttec_thread() if not args.pro else dmx._start_pro_thread()
        time.sleep(0.5)
        show_threads("après le 2e démarrage forcé")

        t0 = time.time()
        last = 0
        while time.time() - t0 < args.seconds:
            time.sleep(2.0)
            el = int(time.time() - t0)
            if el != last:
                last = el
                alive = len(writer_threads())
                print(f"    t+{el:3d}s  writers={alive}  connected={dmx.connected}")
        print("\n  Phase 2 terminée sans plantage du script.")
        print("  (un plantage NATIF tuerait le processus : pas de trace Python)")

    print("\n--- Fermeture ---")
    dmx.disconnect()
    time.sleep(0.5)
    show_threads("après disconnect()")
    print("\nTerminé.")


if __name__ == "__main__":
    main()
