# -*- coding: utf-8 -*-
"""Lyre à ROUE : une couleur demandée NOIRE ferme le Dim, même si base_color
est noire. Symptôme (05/11/2026) : effet « Bloc Rouge/Noir » lancé depuis un
plateau au noir → les images noires restaient rouge plein (Dim 255)."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow\App")
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from artnet_dmx import ArtNetDMX
from projector import Projector

LYRE = ['Pan', 'PanFine', 'Tilt', 'TiltFine', 'Speed', 'ColorWheel',
        'Gobo1', 'Gobo1Rot', 'Prism', 'Shutter', 'Dim', 'Focus', 'Mode']
PAR = ['Dim', 'R', 'G', 'B', 'Strobe']


def dim_out(profile, base, col, level=100):
    dmx = ArtNetDMX()
    p = Projector('face', 't', 'Moving Head')
    p.dmx_profile = list(profile)
    p.level = level; p.muted = False
    p.base_color = QColor(base); p.color = QColor(*col)
    ch = list(range(1, len(profile) + 1))
    dmx.set_projector_patch("face_0", ch, 0, profile=profile)
    dmx.update_from_projectors([p])
    return dmx.dmx_data[0][ch[profile.index('Dim')] - 1]


for base in ("#000000", "#ffffff", "#ff3300"):
    assert dim_out(LYRE, base, (0, 0, 0)) == 0, f"noir non fermé (base {base})"
    assert dim_out(LYRE, base, (255, 51, 0)) == 255
    assert dim_out(LYRE, base, (128, 25, 0)) == 128
# Comportement inchangé hors lyre à roue
assert dim_out(PAR, "#000000", (0, 0, 0)) == 255
assert dim_out(PAR, "#ff0000", (255, 0, 0)) == 255
print("OK")

# Affichage 2D/3D : même règle (core.emitted_brightness)
import core
p = Projector('face', 't', 'Moving Head'); p.dmx_profile = list(LYRE)
p.level = 100; p.base_color = QColor('#000000'); p.color = QColor(0, 0, 0)
assert core.emitted_brightness(p) == 0.0, "3D : noir affiché allumé"
p.color = QColor(255, 51, 0)
assert core.emitted_brightness(p) == 1.0
print("OK affichage")
