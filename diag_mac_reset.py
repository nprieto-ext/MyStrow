import sys, time, serial
from serial.tools.list_ports import comports

L = [p.device for p in comports() if 'usbserial' in p.device]
if not L:
    sys.exit("Aucune interface USB detectee.")
P = L[0]
T = b'\x00' + bytes([255, 255, 255, 255, 0] * 2 + [0] * 502)

def go(a, b):
    s = serial.Serial(P, 250000, 8, 'N', 2, timeout=1)
    n = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 8:
        s.baudrate = 90000
        if a: s.reset_output_buffer()
        s.write(b'\x00'); s.flush()
        time.sleep(0.0015)
        if b: s.reset_output_buffer()
        s.baudrate = 250000
        time.sleep(0.0001)
        s.write(T); s.flush()
        n += 1
        time.sleep(0.036)
    s.close()
    print("  %d trames envoyees" % n)

print("Interface : " + P)
for nom, a, b in (("A  MyStrow exact (2 reset)", 1, 1),
                  ("B  sans le 2e reset", 1, 0),
                  ("C  sans aucun reset", 0, 0)):
    input("\n>>> " + nom + "   [Entree] ")
    go(a, b)
    print("  ?? Allumes ?")
