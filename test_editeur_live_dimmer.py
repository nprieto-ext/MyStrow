"""
Sortie live de l'éditeur d'effets : une couche DIMMER doit agir sur les lampes.

Remonté par FuraxX (Discord, 15/11/2026) : « l'effet dimmer n'agit sur rien »
alors que le plan de feu pulse et que le fader de l'APC mini gradue bien les
mêmes fixtures.

Cause : l'éditeur produit `level` en 0..1 et `_apply_editor_live_overrides` le
posait tel quel dans `proj.level` (0..100). artnet_dmx y voyait un « effet
couleur » (couleur pleine, niveau ~0) et sortait le canal Dim à 255 en
permanence. Une lyre à roue n'a que ce canal pour sa luminosité : elle ne
pulsait pas du tout.

Ces tests regardent les OCTETS émis sur le canal Dim, pas l'état du modèle.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

from projector import Projector
from artnet_dmx import ArtNetDMX
from main_window import MainWindow

_app = QApplication.instance() or QApplication([])

LYRE_ROUE = ["Pan", "Tilt", "Dim", "ColorWheel", "Gobo1"]
PAR_RGBD  = ["R", "G", "B", "Dim"]


class FauxMW:
    _GENERIC_WHEEL_SLOTS = MainWindow._GENERIC_WHEEL_SLOTS
    _update_color_wheel = MainWindow._update_color_wheel
    _apply_editor_live_overrides = MainWindow._apply_editor_live_overrides
    _restore_editor_live_overrides = staticmethod(
        MainWindow._restore_editor_live_overrides)


class TestDimmerSortieLive(unittest.TestCase):

    def _setup(self, profile, ftype):
        p = Projector("contre", "fixture", ftype)
        p.dmx_profile = list(profile)
        p.level = 100
        p.base_color = QColor(255, 0, 0)
        p.color = QColor(255, 0, 0)
        dmx = ArtNetDMX()
        dmx.set_projector_patch("contre_0", list(range(1, len(profile) + 1)),
                                0, profile)
        mw = FauxMW()
        mw.projectors = [p]
        mw._editor_live_channels = None
        return p, dmx, mw

    def _dim_emis(self, p, dmx, mw, entry, profile):
        mw._editor_live_overrides = {id(p): entry}
        saved = mw._apply_editor_live_overrides()
        try:
            dmx.update_from_projectors([p])
        finally:
            mw._restore_editor_live_overrides(saved)
        trame = [dmx.get_channel(i) for i in range(1, len(profile) + 1)]
        return trame, trame[profile.index("Dim")]

    def test_lyre_roue_le_dim_suit_la_couche(self):
        p, dmx, mw = self._setup(LYRE_ROUE, "Moving Head")
        emis = []
        for bv in (1.0, 0.5, 0.0):
            _, d = self._dim_emis(p, dmx, mw,
                                  (bv, QColor(255, 0, 0), None, None, bv),
                                  LYRE_ROUE)
            emis.append(d)
        self.assertEqual(emis[0], 255)
        self.assertAlmostEqual(emis[1], 127, delta=2)
        self.assertEqual(emis[2], 0, "au creux de la pulsation, la lyre doit être noire")

    def test_par_rgbd_teinte_pure_et_dim_gradue(self):
        p, dmx, mw = self._setup(PAR_RGBD, "PAR LED")
        trame, d = self._dim_emis(p, dmx, mw,
                                  (0.25, QColor(255, 0, 0), None, None, 0.25),
                                  PAR_RGBD)
        self.assertEqual(trame[:3], [255, 0, 0], "teinte pure sur R/G/B")
        self.assertAlmostEqual(d, 63, delta=2)

    def test_etat_restaure_apres_la_trame(self):
        p, dmx, mw = self._setup(LYRE_ROUE, "Moving Head")
        avant = (p.level, p.color.name(), p.base_color.name(), p.color_wheel)
        self._dim_emis(p, dmx, mw, (0.3, QColor(255, 0, 0), None, None, 0.3),
                       LYRE_ROUE)
        self.assertEqual((p.level, p.color.name(), p.base_color.name(),
                          p.color_wheel), avant)

    def test_couche_couleur_sans_dimmer_inchangee(self):
        """Pas de 5e élément (ou None) : ancien chemin, octet pour octet."""
        p, dmx, mw = self._setup(PAR_RGBD, "PAR LED")
        t4, _ = self._dim_emis(p, dmx, mw, (0.5, QColor(127, 0, 0), None, None),
                               PAR_RGBD)
        t5, _ = self._dim_emis(p, dmx, mw,
                               (0.5, QColor(127, 0, 0), None, None, None),
                               PAR_RGBD)
        self.assertEqual(t4, t5)


if __name__ == "__main__":
    unittest.main()
