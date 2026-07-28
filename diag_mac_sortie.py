#!/usr/bin/env python3
"""Test de sortie DMX macOS — trouve QUEL chemin allume vraiment les projecteurs.

À lancer MyStrow FERMÉ (l'app garde le port série ouvert).
    python3 diag_mac_sortie.py [IP_DU_NODE]

Chaque test MAINTIENT la sortie 8 s : c'est ce que les diagnostics existants
ratent (10 trames = 0,4 s, invisible à l'œil).
"""
import socket, sys, time

DUREE, FPS = 8.0, 25
IP = sys.argv[1] if len(sys.argv) > 1 else "2.0.0.15"


def trame():
    """2 MiniCube 5 canaux [R,G,B,Dim,Strobe] aux adresses 1 et 6, blanc plein.
    Strobe à 0 : un « tout à 255 » ferait clignoter ou resterait noir."""
    d = bytearray(512)
    for b in (0, 5):
        d[b:b + 5] = bytes([255, 255, 255, 255, 0])
    return bytes(d)


def pause(titre):
    print(f"\n>>> {titre}")
    try:
        input("    [Entrée] pour lancer... ")
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)


def t_artnet(ip):
    pkt_hdr = b'Art-Net\x00\x00\x50\x00\x0e'
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    d, n, seq, t0 = trame(), 0, 0, time.monotonic()
    try:
        while time.monotonic() - t0 < DUREE:
            seq = (seq + 1) % 256
            s.sendto(pkt_hdr + bytes([seq]) + b'\x00\x00\x00\x02\x00' + d, (ip, 6454))
            n += 1
            time.sleep(1 / FPS)
        print(f"  ✓ {n} paquets envoyés vers {ip}:6454")
    except Exception as e:
        print(f"  ✗ {e}")
    finally:
        s.close()


def ouvrir(port):
    import serial
    return serial.Serial(port=port, baudrate=250000, bytesize=8,
                         parity='N', stopbits=2, timeout=1)


def t_serie(port, methode):
    tr = b'\x00' + trame()
    try:
        ser = ouvrir(port)
    except Exception as e:
        print(f"  ✗ ouverture impossible : {e}\n    (MyStrow est-il fermé ?)")
        return
    n, err, t0 = 0, 0, time.monotonic()
    try:
        while time.monotonic() - t0 < DUREE:
            try:
                if methode == 'break':
                    ser.send_break(duration=0.001)
                    ser.write(tr); ser.flush()
                else:
                    ser.baudrate = 90000          # 0x00 = 9 bits bas ≈ 100 µs
                    ser.write(b'\x00'); ser.flush()
                    time.sleep(0.0015)
                    ser.baudrate = 250000
                    time.sleep(0.0001)            # MAB
                    ser.write(tr); ser.flush()
                n += 1
            except Exception as e:
                err += 1
                if err <= 2:
                    print(f"    erreur : {e}")
            time.sleep(max(0, 1 / FPS - 0.004))
        print(f"  ✓ {n} trames envoyées, {err} erreur(s)")
    finally:
        try: ser.close()
        except Exception: pass


def t_pro(port):
    charge = b'\x00' + trame()
    pkt = b'\x7e\x06' + bytes([len(charge) & 255, len(charge) >> 8]) + charge + b'\xe7'
    try:
        ser = ouvrir(port)
    except Exception as e:
        print(f"  ✗ ouverture impossible : {e}")
        return
    n, t0 = 0, time.monotonic()
    try:
        while time.monotonic() - t0 < DUREE:
            ser.write(pkt); ser.flush(); n += 1
            time.sleep(1 / FPS)
        print(f"  ✓ {n} paquets ENTTEC Pro envoyés")
    finally:
        try: ser.close()
        except Exception: pass


print("=" * 60)
print("TEST DE SORTIE DMX — macOS   (MyStrow doit être FERMÉ)")
print("=" * 60)
print("La trame allume les 2 MiniCube en BLANC PLEIN (adresses 1 et 6).")

pause(f"TEST 1/4 — Art-Net vers {IP}")
t_artnet(IP)
print("  ?? Les projecteurs se sont-ils allumés ?")

try:
    from serial.tools import list_ports
    dispo = [p.device for p in list_ports.comports()
             if 'usbserial' in p.device or 'usbmodem' in p.device]
except ImportError:
    print("\n✗ pyserial absent : pip3 install pyserial")
    sys.exit(1)

if not dispo:
    print("\nAucune interface USB détectée — tests série sautés.")
    sys.exit(0)

print("\nInterfaces USB :")
for i, p in enumerate(dispo):
    print(f"  [{i}] {p}")
port = dispo[int(input("Laquelle ? [0] : ").strip() or 0)]

pause(f"TEST 2/4 — Open DMX, break « baud-rate trick » (méthode macOS de MyStrow)")
t_serie(port, 'baud')
print("  ?? Allumés ?")

pause(f"TEST 3/4 — Open DMX, break « send_break » (méthode Windows de MyStrow)")
t_serie(port, 'break')
print("  ?? Allumés ?")

pause(f"TEST 4/4 — protocole ENTTEC Pro")
t_pro(port)
print("  ?? Allumés ?")

print("\n" + "=" * 60)
print("Dis-moi quel(s) test(s) ont allumé les projecteurs.")
print("=" * 60)
