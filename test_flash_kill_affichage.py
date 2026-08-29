"""
test_flash_kill_affichage.py — FLASH KILL doit se VOIR sur le plan de feu.

Le KILL ne modifie aucun etat du show : c'est une porte posee et defaite le
temps d'une frame, juste avant l'envoi DMX (cf. test_flash_kill_reel.py). Le
modele reste donc allume, et comme le repaint du plan 2D est differe, il ne
voyait jamais la coupure : les lampes etaient noires, l'ecran restait allume,
et le KILL avait l'air de ne rien faire.

D'ou un drapeau d'AFFICHAGE, `PlanDeFeu.set_kill_display`, pilote a chaque
frame par `send_dmx_update`. Ce test verifie les deux bouts : le drapeau eteint
bien le rendu, et il suit bien `_flash_kind`.

    python test_flash_kill_affichage.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import plan_de_feu as pdf_mod

_app = QApplication.instance() or QApplication(sys.argv)

ETEINT = "#1a1a1a"


class FauxProjecteur:
    def __init__(self, group="face"):
        self.group = group
        self.dmx_profile = ["R", "G", "B"]
        self.level = 100
        self.base_color = QColor(255, 255, 255)
        self.color = QColor(255, 255, 255)
        self.muted = False
        self.strobe_speed = 0
        self.fixture_type = "PAR LED"


class FauxPdf:
    def __init__(self):
        self._htp_overrides = None
        self._kill_display = None


class FauxCanvas:
    """FixtureCanvas reduit au calcul de la couleur de remplissage."""

    _get_fill_color = pdf_mod.FixtureCanvas._get_fill_color

    def __init__(self):
        self.pdf = FauxPdf()


class TestRenduSousKill(unittest.TestCase):

    def test_sans_kill_la_lampe_s_affiche_allumee(self):
        c, p = FauxCanvas(), FauxProjecteur()
        self.assertNotEqual(c._get_fill_color(p).name().lower(), ETEINT)

    def test_le_groupe_solote_reste_allume(self):
        c, p = FauxCanvas(), FauxProjecteur("lat")
        c.pdf._kill_display = {"lat"}
        self.assertNotEqual(c._get_fill_color(p).name().lower(), ETEINT,
                            "le groupe du pad tenu doit rester allume")

    def test_hors_du_groupe_solote_tout_s_affiche_eteint(self):
        c, p = FauxCanvas(), FauxProjecteur()
        c.pdf._kill_display = {"lat"}          # solo ailleurs : « face » est coupe
        self.assertEqual(c._get_fill_color(p).name().lower(), ETEINT,
                         "le solo doit se voir sur le plan de feu")

    def test_le_kill_l_emporte_sur_un_override_htp(self):
        """Une memoire en HTP ne doit pas rallumer l'ecran sous KILL."""
        c, p = FauxCanvas(), FauxProjecteur()
        c.pdf._htp_overrides = {id(p): (1.0, QColor(255, 0, 0))}
        c.pdf._kill_display = {"lat"}
        self.assertEqual(c._get_fill_color(p).name().lower(), ETEINT)

    def test_le_relache_rallume_l_affichage(self):
        c, p = FauxCanvas(), FauxProjecteur()
        c.pdf._kill_display = {"lat"}
        c.pdf._kill_display = None
        self.assertNotEqual(c._get_fill_color(p).name().lower(), ETEINT)


class TestDrapeauSuitLeFlash(unittest.TestCase):
    """`set_kill_display` ne bascule que sur KILL, et marque le repaint."""

    def _pdf(self):
        obj = pdf_mod.PlanDeFeu.__new__(pdf_mod.PlanDeFeu)
        obj._kill_display = None
        obj._dirty = False
        return obj

    def test_armer_marque_le_repaint(self):
        o = self._pdf()
        pdf_mod.PlanDeFeu.set_kill_display(o, {"lat"})
        self.assertEqual(o._kill_display, {"lat"})
        self.assertTrue(o._dirty, "sans _dirty, l'ecran ne se redessine pas")

    def test_reposer_la_meme_valeur_ne_salit_pas(self):
        o = self._pdf()
        pdf_mod.PlanDeFeu.set_kill_display(o, None)
        self.assertFalse(o._dirty,
                         "40 repaints par seconde pour rien sinon")

    def test_hors_solo_rien_n_est_eteint(self):
        """Le bouton KILL tenu seul ne passe aucun groupe : None = tout allume."""
        o = self._pdf()
        pdf_mod.PlanDeFeu.set_kill_display(o, None)
        self.assertIsNone(o._kill_display)


if __name__ == "__main__":
    unittest.main(verbosity=2)
