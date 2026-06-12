"""
Test ENTTEC Open DMX USB via le driver D2XX (comme QLC+).
Contourne le port COM/VCP : parle directement a la puce FT232R.

Usage :
    python test_d2xx.py            # CH1-4 = 255 pendant 8 s, device index 0
    python test_d2xx.py 0 8        # index 0, 8 secondes
    python test_d2xx.py off        # blackout

Ferme MyStrow ET QLC+ avant (la puce ne peut etre ouverte qu'une fois).
"""
import sys
import time
import ftd2xx
import ftd2xx.defines as d

ARG = sys.argv[1] if len(sys.argv) > 1 else "0"
OFF = (ARG == "off")
INDEX = 0 if OFF else int(ARG)
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0

print("Devices D2XX :", ftd2xx.listDevices())
print(f"Ouverture index {INDEX}...", end=" ", flush=True)
dev = ftd2xx.open(INDEX)
print("OK")

info = dev.getDeviceInfo()
print("Device :", info)

# Configuration DMX512 : 250 kbaud, 8 bits, 2 stop, sans parite
dev.setBaudRate(250000)
dev.setDataCharacteristics(d.BITS_8, d.STOP_BITS_2, d.PARITY_NONE)
dev.setFlowControl(d.FLOW_NONE, 0, 0)
dev.setLatencyTimer(1)          # 1 ms — le reglage cle que le VCP ne fait pas
dev.setTimeouts(100, 100)
dev.purge(d.PURGE_TX | d.PURGE_RX)

# Trame : start code 0x00 + 512 canaux
data = bytearray(512)
if not OFF:
    data[0] = data[1] = data[2] = data[3] = 255
frame = b'\x00' + bytes(data)

print(f"Envoi {DURATION:.0f}s  (CH1-4 = {0 if OFF else 255})  Ctrl+C pour arreter")
sent = 0
t_end = time.monotonic() + DURATION
try:
    while time.monotonic() < t_end:
        t0 = time.monotonic()
        # BREAK >= 88 us puis MAB >= 8 us, genere directement sur la puce
        dev.setBreakOn()
        time.sleep(0.0001)      # ~100 us de break
        dev.setBreakOff()
        time.sleep(0.000012)    # MAB
        dev.write(frame)
        sent += 1
        elapsed = time.monotonic() - t0
        if elapsed < 0.025:
            time.sleep(0.025 - elapsed)   # ~40 fps
finally:
    dev.setBreakOff()
    dev.close()

print(f"\n{sent} frames envoyees.")
print("-> Le projecteur a-t-il reagi ?")
