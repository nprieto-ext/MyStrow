# -*- coding: utf-8 -*-
"""« 🎯 Définir le centre » d'une lyre (client Alan, 27/11/2026).

BoomTone accrochées écrans face au public : le centre de MyStrow les faisait
regarder à 90° sur la droite. Le centre calibré est un décalage ajouté EN
SORTIE, donc tout le reste de l'appli (pointeur, presets, 3D, effets, LIVE)
continue de raisonner avec 32768 = centre.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from artnet_dmx import ArtNetDMX
from projector import Projector
from core import pantilt_offset
from plan_de_feu import _ecrire_canal_modele
from pantilt_center_dialog import CentreDialog, axe_modele

PROFIL = ['Pan', 'PanFine', 'Tilt', 'TiltFine', 'Dim']
QUART = 10923                                    # 90° sur une 540°


def rig():
    dmx = ArtNetDMX()
    p = Projector('lyre', "Maxi Spot 60", "Moving Head")
    p.dmx_profile = list(PROFIL)
    p.level = 100
    p.color = p.base_color = QColor("#ffffff")
    chans = list(range(1, 1 + len(PROFIL)))
    dmx.set_projector_patch("lyre_0", chans, 0, profile=PROFIL)
    return dmx, p


def sortie(dmx, axe):
    d = dmx.dmx_data[0]
    i = 0 if axe == "pan" else 2
    return (d[i] << 8) | d[i + 1]


def test_defaut_inchange():
    dmx, p = rig()
    p.pan, p.tilt = 40000, 30000
    dmx.update_from_projectors([p])
    assert (sortie(dmx, "pan"), sortie(dmx, "tilt")) == (40000, 30000)
    p.pan_offset = None                          # patch ancien / bidouillé
    assert pantilt_offset(p, "pan") == 0


def test_centre_decale_en_sortie():
    dmx, p = rig()
    p.pan_offset = -QUART
    p.pan, p.tilt = 32768, 32768                 # « Centre » de l'appli
    dmx.update_from_projectors([p])
    assert sortie(dmx, "pan") == 32768 - QUART
    assert sortie(dmx, "tilt") == 32768
    p.pan = 0                                    # bornes DMX respectées
    dmx.update_from_projectors([p])
    assert sortie(dmx, "pan") == 0


def test_decalage_avant_inversion():
    dmx, p = rig()
    p.pan_offset = 1000
    p.pan_invert = True
    p.pan = 32768
    dmx.update_from_projectors([p])
    assert sortie(dmx, "pan") == 65535 - 33768


def test_curseur_brut_tient_compte_du_decalage():
    dmx, p = rig()
    p.pan_offset = -QUART
    p.pan = 32768
    # Le curseur brut « Pan » à la valeur qui sort déjà : la position ne bouge pas.
    _ecrire_canal_modele(p, "Pan", (32768 - QUART) >> 8)
    dmx.update_from_projectors([p])
    assert sortie(dmx, "pan") >> 8 == (32768 - QUART) >> 8
    assert abs(p.pan - 32768) < 256


def test_calibrage_valider():
    _dmx, p = rig()
    frere = Projector('lyre', "Maxi Spot 60", "Moving Head")
    p.pan = 32768
    dlg = CentreDialog(p, "Pan", [frere])
    assert p.pan_offset == 0
    dlg._sli.setValue(32768 - QUART)             # on tourne la vraie lyre
    assert p.pan == 32768 - QUART                # elle bouge en direct
    dlg._valider()
    assert p.pan_offset == -QUART and p.pan == 32768
    assert frere.pan_offset == -QUART            # « appliquer aux autres » coché


def test_calibrage_annuler_restaure():
    _dmx, p = rig()
    p.pan_offset, p.pan = 500, 20000
    dlg = CentreDialog(p, "Pan")
    dlg._sli.setValue(1234)
    dlg.reject()
    assert (p.pan_offset, p.pan) == (500, 20000)


def test_axe_avec_swap():
    p = Projector('lyre', "x", "Moving Head")
    assert axe_modele(p, "Pan") == "pan"
    p.pan_tilt_swap = True
    assert axe_modele(p, "Pan") == "tilt" and axe_modele(p, "TiltFine") == "pan"


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_"):
            _f(); print("OK", _n)
