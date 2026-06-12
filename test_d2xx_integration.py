"""
Test d'INTÉGRATION : pilote le boîtier via la vraie classe ArtNetDMX de MyStrow
en transport D2XX (exactement comme l'app). Valide le thread, le break, l'envoi.

Usage :
    python test_d2xx_integration.py          # COM4, 6 s à fond puis blackout
    python test_d2xx_integration.py COM4 6

Ferme MyStrow et QLC+ avant (la puce ne s'ouvre qu'une fois).
"""
import sys
import time
from artnet_dmx import ArtNetDMX, TRANSPORT_ENTTEC_D2XX

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM4"
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0

dmx = ArtNetDMX()
print(f"Connexion D2XX (port {PORT})...")
ok = dmx.connect(transport=TRANSPORT_ENTTEC_D2XX, com_port=PORT, ftdi_serial=None)
print("  connect() ->", ok, "| connected =", dmx.connected)
if not ok or not dmx.connected:
    print("ÉCHEC : la connexion D2XX n'a pas abouti (puce occupée ? fermez QLC+)")
    sys.exit(1)

# Le thread interne envoie dmx_data[0] en continu à ~40 fps.
print(f"CH1-4 = 255 pendant {DURATION:.0f}s — le projo doit s'allumer à fond...")
for ch in (1, 2, 3, 4):
    dmx.set_channel(ch, 255)
time.sleep(DURATION)

print("Blackout...")
dmx.blackout()
time.sleep(1.0)

dmx.disconnect()
print("Terminé. Le projecteur a-t-il réagi (allumé puis éteint) ?")
