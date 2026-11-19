# -*- coding: utf-8 -*-
"""Canal « Dimmer + Strobe » et repère « face scène » (Discord, 18/11/2026).

1) BoomTone Wash 7x12 / Lytor wash 7 LED : dimmer et strobe sur UN canal
   (0-134 luminosité qui scintille, 135-240 strobe, 241-255 plein feu).
2) RaykeN / Tutur : une lyre qui vise le centre de la scène se dessinait de
   travers en 2D/3D, le plan supposant que Pan 32768 = face scène.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from artnet_dmx import ArtNetDMX
from projector import Projector
from core import pan_front_offset, pan_from_front, pan_to_front
from plan_de_feu import beam_geometry

WASH = ['Pan', 'Tilt', 'Speed', 'R', 'G', 'B', 'W', 'DimStrobe']


def rig():
    dmx = ArtNetDMX()
    p = Projector('lyre', "Wash 7x12", "Moving Head")
    p.dmx_profile = list(WASH)
    p.level = 100
    p.base_color = QColor("#ff0000")
    p.color = QColor("#ff0000")
    p.muted = False
    chans = list(range(1, 1 + len(WASH)))
    dmx.set_projector_patch("lyre_0", chans, 0, profile=WASH)
    return dmx, p, chans


def val(dmx, chans, t):
    return dmx.dmx_data[0][chans[WASH.index(t)] - 1]


def test_dimstrobe_plein_feu_au_repos():
    dmx, p, ch = rig()
    dmx.update_from_projectors([p])
    assert val(dmx, ch, 'DimStrobe') == 255      # plage « plein feu », pas de scintillement
    assert val(dmx, ch, 'R') == 255


def test_dimstrobe_niveau_par_les_couleurs():
    dmx, p, ch = rig()
    p.level = 50
    p.color = QColor(127, 0, 0)                   # Projector applique le niveau à color
    dmx.update_from_projectors([p])
    assert val(dmx, ch, 'DimStrobe') == 255
    assert 120 <= val(dmx, ch, 'R') <= 130


def test_dimstrobe_bande_strobe():
    dmx, p, ch = rig()
    p.shutter_strobe_min, p.shutter_strobe_max = 135, 240
    sorties = []
    for spd in (1, 50, 100):
        p.strobe_speed = spd
        dmx.update_from_projectors([p])
        sorties.append(val(dmx, ch, 'DimStrobe'))
    assert all(135 <= v <= 240 for v in sorties), sorties
    assert sorties == sorted(sorties) and sorties[-1] == 240


def test_dimstrobe_noir():
    dmx, p, ch = rig()
    p.level = 0
    p.color = QColor(0, 0, 0)
    dmx.update_from_projectors([p])
    assert val(dmx, ch, 'DimStrobe') == 0
    dmx, p, ch = rig()
    p.muted = True
    dmx.update_from_projectors([p])
    assert val(dmx, ch, 'DimStrobe') == 0


def test_face_scene_defaut_inchange():
    p = Projector('lyre', "x", "Moving Head")
    assert pan_front_offset(p) == 0
    assert pan_from_front(p, 40000) == 40000 and pan_to_front(p, 40000) == 40000


def test_face_scene_calibree():
    p = Projector('lyre', "x", "Moving Head")
    p.pan_front = 21845                          # lyre 540° accrochée de biais
    # Centre du pad → la lyre va sur son face scène
    assert pan_from_front(p, 32768) == 21845
    # Et elle se dessine droite (angle 0) quand elle y est
    angle, _l, _w = beam_geometry(pan_to_front(p, 21845), 40000, 13)
    assert abs(angle) < 1e-6
    # Bornes DMX respectées
    assert pan_from_front(p, 0) == 0
    p.pan_front = None                           # patch ancien / bidouillé
    assert pan_front_offset(p) == 0


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_"):
            _f(); print("OK", _n)
