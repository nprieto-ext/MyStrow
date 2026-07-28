"""
Test ENTTEC isole — compare les 3 methodes de break sur le port FTDI.
Usage :
    python test_enttec.py sendbreak   # methode live actuelle  : send_break(1 ms)
    python test_enttec.py breakcond   # methode diag actuelle  : break_condition 176 us
    python test_enttec.py baudtrick   # fallback macOS         : baud-rate trick
    python test_enttec.py pro         # protocole ENTTEC PRO   : paquet 0x7E..0xE7
    python test_enttec.py off         # blackout (tous canaux a 0)

Optionnel : port et duree
    python test_enttec.py sendbreak COM4 5
"""
import sys
import time
import serial

PORT = sys.argv[2] if len(sys.argv) > 2 else "COM4"
DURATION = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
METHOD = sys.argv[1] if len(sys.argv) > 1 else "sendbreak"

# Frame : CH1-4 = 255 (full), sauf "off" = tout a 0
val = 0 if METHOD == "off" else 255
data = bytearray(512)
if METHOD != "off":
    data[0] = data[1] = data[2] = data[3] = 255
frame = b'\x00' + bytes(data)

print(f"Port    : {PORT}")
print(f"Methode : {METHOD}")
print(f"Duree   : {DURATION:.0f} s   (CH1-4 = {val})")
print("Ouverture...", end=" ", flush=True)

# Le PRO utilise un baudrate/format different (USB-CDC, paquet firmware)
if METHOD == "pro":
    pro_data = bytes(data)
    size = len(pro_data) + 1   # start code + 512
    pro_packet = bytes([0x7E, 6, size & 0xFF, (size >> 8) & 0xFF, 0x00]) + pro_data + bytes([0xE7])
    ser = serial.Serial(
        port=PORT, baudrate=57600,
        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE, timeout=0.1,
    )
else:
    ser = serial.Serial(
        port=PORT, baudrate=250000,
        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_TWO, timeout=0.1,
    )
print("OK")
print("Envoi 25 fps... (Ctrl+C pour arreter)")

sent = 0
errors = 0
t_end = time.monotonic() + DURATION
try:
    while time.monotonic() < t_end:
        t0 = time.monotonic()
        try:
            if METHOD == "pro":
                ser.write(pro_packet); ser.flush()
            elif METHOD == "breakcond":
                ser.break_condition = True
                time.sleep(0.000176)        # 176 us (ancien diag)
                ser.break_condition = False
                ser.write(frame); ser.flush()
            elif METHOD == "baudtrick":
                # Pas de reset_output_buffer() : ~1 s par appel sur macOS, ce
                # qui écroulerait la mesure de débit de ce banc de test.
                ser.baudrate = 100000
                ser.write(b'\x00'); ser.flush()
                time.sleep(0.0015)
                ser.baudrate = 250000
                time.sleep(0.0001)
                ser.write(frame); ser.flush()
            else:  # sendbreak / off
                ser.send_break(duration=0.001)   # 1 ms (live actuel)
                ser.write(frame); ser.flush()
            sent += 1
        except Exception as e:
            errors += 1
            print(f"  ERREUR frame {sent}: {e}")
            if errors > 5:
                print("  >5 erreurs — arret")
                break
        elapsed = time.monotonic() - t0
        if elapsed < 0.040:
            time.sleep(0.040 - elapsed)
finally:
    try:
        ser.close()
    except Exception:
        pass

print(f"\nResultat : {sent} frames envoyees, {errors} erreurs")
print("-> Les projecteurs ont-ils reagi ?")
