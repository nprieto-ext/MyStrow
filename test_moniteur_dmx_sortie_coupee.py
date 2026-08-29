"""Le moniteur DMX doit afficher les valeurs meme sortie coupee.

`send_dmx_update()` ne remplit `dmx.dmx_data` que si la sortie est connectee ET
le bouton DMX du plan de feu enclenche. Hors de ce cas le tampon reste a zero
pour toujours : sans recalcul, la fenetre montrait un parc eteint alors que la
lyre etait bien en blanc a l'ecran. Elle refait donc le calcul dans un tampon
fantome — et surtout PAS dans le vrai, que la trame de maintien ENTTEC relit.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from artnet_dmx import ArtNetDMX, TRANSPORT_ARTNET
from dmx_monitor import DmxMonitorWindow
from projector import Projector


class TestMoniteurSortieCoupee(unittest.TestCase):

    def setUp(self):
        from PySide6.QtGui import QColor
        self.dmx = ArtNetDMX()
        self.dmx.transport = TRANSPORT_ARTNET
        self.dmx.connected = False
        self.proj = Projector("face", 0)
        self.proj.level = 100
        self.proj.color = QColor(255, 255, 255)
        self.proj.base_color = QColor(255, 255, 255)
        self.dmx.set_projector_patch("face_0", [1, 2, 3, 4, 5], universe=0, mode="5CH")

    def _fenetre(self, sortie_active):
        return DmxMonitorWindow(self.dmx, lambda: [self.proj],
                                lambda: sortie_active, lambda: 0)

    def test_sortie_coupee_affiche_quand_meme_les_valeurs(self):
        win = self._fenetre(False)
        win._tick()
        self.assertFalse(win._live)
        self.assertTrue(any(win._vals[0]),
                        "univers 1 tout noir alors que la lyre est a 100 % en blanc")
        # ... et le vrai tampon n'a pas ete touche : rien ne doit pouvoir partir.
        self.assertEqual(sum(self.dmx.dmx_data[0]), 0,
                         "le moniteur a ecrit dans le tampon reellement emis")

    def test_sortie_active_lit_le_tampon_reel(self):
        self.dmx.connected = True
        self.dmx.dmx_data[0][0] = 77
        win = self._fenetre(True)
        win._tick()
        self.assertTrue(win._live)
        self.assertEqual(win._vals[0][0], 77,
                         "sortie active : c'est le tampon emis qui doit etre lu, tel quel")

    def test_grille_recoit_les_valeurs(self):
        win = self._fenetre(False)
        win._tick()
        grille = win._grids[0]
        self.assertEqual(grille._values[:5], win._vals[0][:5])


if __name__ == "__main__":
    unittest.main(verbosity=2)
