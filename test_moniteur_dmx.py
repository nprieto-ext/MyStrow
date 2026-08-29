"""
test_moniteur_dmx.py — Moniteur DMX (dmx_monitor.py).

Le moniteur n'a qu'un contrat, mais il est strict : montrer le tampon
`ArtNetDMX.dmx_data` tel quel, et NE JAMAIS y toucher. Une fenêtre de lecture
qui écrirait un seul octet serait pire qu'inutile — on l'ouvrirait en plein
spectacle pour comprendre un problème, et on en créerait un autre.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from artnet_dmx import ArtNetDMX, TRANSPORT_ARTNET, TRANSPORT_ENTTEC, OUTPUT_INPUT
from projector import Projector
from i18n import tr
from dmx_monitor import DmxMonitorWindow

_app = QApplication.instance() or QApplication(sys.argv)


def faux_dmx(transport=TRANSPORT_ARTNET, output_map=(0, 1, 2, 3), connected=True):
    """Moteur DMX complet, mais jamais connecté à quoi que ce soit.

    `ArtNetDMX()` relit ~/.mystrow_dmx.json : on écrase donc explicitement tout
    ce dont le test parle, sinon le résultat dépendrait de la machine.
    """
    dmx = ArtNetDMX()
    dmx.transport = transport
    dmx.connected = connected
    dmx.universe = 0
    dmx.target_ip = "2.0.0.15"
    dmx.output_map = list(output_map)
    dmx.clear_patch()
    dmx.blackout()
    return dmx


class TestMoniteurDmx(unittest.TestCase):

    def _fenetre(self, dmx, projecteurs=()):
        win = DmxMonitorWindow(dmx, lambda: list(projecteurs))
        self.addCleanup(win.deleteLater)
        return win

    # ── Lecture ──────────────────────────────────────────────────────────────

    def test_affiche_les_valeurs_du_tampon(self):
        dmx = faux_dmx()
        dmx.set_channel(12, 200, 0)
        win = self._fenetre(dmx)
        win._tick()
        self.assertEqual(win._grids[0]._values[11], 200)

    def test_ne_touche_jamais_au_tampon(self):
        """La garantie centrale : ouvrir, rafraîchir, fermer ne change rien."""
        dmx = faux_dmx()
        for ch, val in ((1, 255), (2, 64), (300, 7)):
            dmx.set_channel(ch, val, 0)
        avant = [list(u) for u in dmx.dmx_data]
        win = self._fenetre(dmx)
        for _ in range(3):
            win._tick()
        win.close()
        self.assertEqual([list(u) for u in dmx.dmx_data], avant)

    # ── Univers affichés ─────────────────────────────────────────────────────

    def test_univers_1_toujours_present(self):
        """Une fenêtre vide n'apprend rien : le premier univers reste affiché."""
        win = self._fenetre(faux_dmx())
        win._tick()
        self.assertEqual(win._shown, [0])

    def test_un_univers_qui_s_allume_apparait(self):
        dmx = faux_dmx()
        win = self._fenetre(dmx)
        win._tick()
        self.assertNotIn(2, win._shown)
        dmx.set_channel(5, 128, 2)
        win._tick()
        self.assertIn(2, win._shown)
        self.assertEqual(win._grids[2]._values[4], 128)

    def test_univers_patche_affiche_meme_a_zero(self):
        dmx = faux_dmx()
        dmx.set_projector_patch("lat_0", [1, 2, 3], universe=1, profile=["Dim", "Pan", "Tilt"])
        win = self._fenetre(dmx)
        win._tick()
        self.assertIn(1, win._shown)

    # ── Ce que devient l'univers en sortie ───────────────────────────────────

    def test_note_sortie_artnet(self):
        win = self._fenetre(faux_dmx(output_map=(3, 1, 2, 0)))
        # L'univers 1 (index 0) part par la QUATRIEME sortie du boitier.
        self.assertIn("4", win._sortie_note(0))

    def test_univers_non_cable_est_signale(self):
        """Les quatre sorties sur l'univers 1 : les trois autres ne partent pas."""
        win = self._fenetre(faux_dmx(output_map=(0, 0, 0, 0)))
        self.assertEqual(win._sortie_note(2), tr("dmxmon_not_sent"))
        self.assertEqual(win._sortie_note(3), tr("dmxmon_not_sent"))

    def test_port_en_entree_ne_compte_pas_comme_sortie(self):
        """Un port basculé en entrée n'émet rien : son univers n'est pas 'sorti'."""
        win = self._fenetre(faux_dmx(output_map=(OUTPUT_INPUT, 1, 2, 3)))
        self.assertEqual(win._sortie_note(0), tr("dmxmon_not_sent"))
        self.assertNotEqual(win._sortie_note(1), tr("dmxmon_not_sent"))

    def test_usb_ne_transporte_que_le_premier_univers(self):
        win = self._fenetre(faux_dmx(transport=TRANSPORT_ENTTEC))
        self.assertEqual(win._sortie_note(0), "")
        self.assertTrue(win._sortie_note(1))

    # ── Patch ────────────────────────────────────────────────────────────────

    def test_survol_nomme_le_projecteur_et_le_canal(self):
        dmx = faux_dmx()
        proj = Projector("lat", "Lyre SL")
        dmx.set_projector_patch("lat_0", [21, 22, 23], universe=0,
                                profile=["Pan", "Tilt", "Dim"])
        win = self._fenetre(dmx, [proj])
        win._tick()
        self.assertEqual(win._lookup(0, 22), ("Lyre SL", "Tilt"))
        self.assertIsNone(win._lookup(0, 30))

    def test_canaux_patches_marques_dans_la_grille(self):
        dmx = faux_dmx()
        proj = Projector("face", "Face 1")
        dmx.set_projector_patch("face_0", [1, 2, 3, 4, 5], universe=0,
                                profile=["Dim", "R", "G", "B", "Strobe"])
        win = self._fenetre(dmx, [proj])
        win._tick()
        self.assertEqual(win._grids[0]._patched, {1, 2, 3, 4, 5})


if __name__ == "__main__":
    unittest.main(verbosity=2)
