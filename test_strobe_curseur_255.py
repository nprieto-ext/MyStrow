# -*- coding: utf-8 -*-
"""Le curseur brut « Strobe » réglé à 255 doit sortir 255, pas 250.

Remontée utilisateur (04/10/2026) : « je le réglais à 255, il redescendait à
250 ». Cause : la vue Curseurs écrivait `strobe_speed` (0-100) que le moteur
réétale sur 16-250 ; le suivi live relisait 250 et ramenait le curseur.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from artnet_dmx import ArtNetDMX
from projector import Projector
from plan_de_feu import _ecrire_canal_modele

PAR = ['Dim', 'R', 'G', 'B', 'Strobe']
dmx = ArtNetDMX()
p = Projector('face', "par", "PAR LED")
p.dmx_profile = list(PAR)
p.level = 100
p.base_color = QColor("#ffffff"); p.color = QColor("#ffffff")
p.muted = False
chans = list(range(1, 1 + len(PAR)))
dmx.set_projector_patch("face_0", chans, 0, profile=PAR)

def sortie():
    dmx.update_from_projectors([p])
    return dmx.dmx_data[0][chans[PAR.index('Strobe')] - 1]

# 1) Valeurs brutes : elles ressortent EXACTEMENT (255 compris)
for v in (18, 100, 137, 249, 250, 251, 255):
    _ecrire_canal_modele(p, "Strobe", v)
    assert sortie() == v, f"curseur {v} -> sortie {sortie()}"

# 2) Sous 16 : strobe éteint, comme avant
_ecrire_canal_modele(p, "Strobe", 10)
assert sortie() == 0

# 3) Un pad / effet qui change la vitesse reprend la main
_ecrire_canal_modele(p, "Strobe", 255)
p.strobe_speed = 50
assert sortie() == int(16 + 0.5 * (250 - 16)), sortie()
p.strobe_speed = 0
assert sortie() == 0
print("OK - le curseur Strobe tient 255.")
