"""
test_colorwheel_affichage.py — Couleur AFFICHEE d'une lyre a roue de couleurs.

Le bug : une lyre a roue (profil sans R/G/B) posee sur ROUGE depuis le plan de
feu 2D, puis modulee par un effet « Dimmer seul » (papillon Pan/Tilt + Dimmer),
s'affichait BLANCHE en 3D alors que la 2D montrait bien le rouge.

Cause : `core.effect_dim_base_color` repeint `proj.color` en blanc sur ces
profils — c'est volontaire (le RVB y est une fiction, la teinte vient de la
roue). La 2D avait sa branche « roue », pas la 3D, qui lisait `proj.color`.

On teste ici le point UNIQUE (`core.color_wheel_display_color`) et la parite
2D / 3D qui en decoule.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from core import (color_wheel_display_color, cw_slot_for_color,
                  effect_dim_base_color, cw_slot_at, CW_DEFAULT_SLOTS)

_app = QApplication.instance() or QApplication(sys.argv)

SLOTS = [
    {"dmx": 0,   "color": "#ffffff", "name": "Open"},
    {"dmx": 20,  "color": "#ff3300", "name": "Rouge"},
    {"dmx": 85,  "color": "#00cc44", "name": "Vert"},
]


class FausseLyre:
    """Lyre a roue : un Dim, une roue, un gobo, Pan/Tilt. Aucun canal R/G/B."""

    def __init__(self, slots=SLOTS):
        self.dmx_profile = ["Dim", "ColorWheel", "Gobo", "Pan", "Tilt"]
        self.color_wheel_slots = list(slots) if slots is not None else []
        self.color_wheel = 0
        self.color = QColor(0, 0, 0)
        self.base_color = QColor(0, 0, 0)
        self.level = 100
        self.pan = 32768
        self.tilt = 32768
        self.muted = False

    def poser_couleur(self, couleur):
        """Ce que fait le plan de feu 2D : couleur du modele + position de roue."""
        self.color = QColor(couleur)
        self.base_color = QColor(couleur)
        slot = cw_slot_for_color(self.color_wheel_slots, QColor(couleur))
        if slot is not None:
            self.color_wheel = slot["dmx"]

    def tick_effet_dimmer(self, bv):
        """Une frame du moteur d'effets, couche Dimmer SEULE (cf.
        `_update_effect_from_layers`) : la couleur part au blanc x dimmer."""
        stable = effect_dim_base_color(self, self.base_color)
        self.level = int(bv * 100)
        self.color = QColor(int(stable.red() * bv),
                            int(stable.green() * bv),
                            int(stable.blue() * bv))


class FausseLED:
    """PAR LED RVB : la roue ne la concerne pas, elle garde son modele."""

    def __init__(self):
        self.dmx_profile = ["Dim", "R", "G", "B"]
        self.color_wheel_slots = []
        self.color_wheel = 0
        self.color = QColor(255, 0, 0)
        self.base_color = QColor(255, 0, 0)
        self.level = 100
        self.pan = 32768
        self.tilt = 32768
        self.muted = False


class TestRoueCouleurAffichage(unittest.TestCase):

    def test_effet_dimmer_ne_blanchit_plus_la_lyre(self):
        """Le bug rapporte : rouge pose en 2D, effet Dimmer -> reste rouge."""
        p = FausseLyre()
        p.poser_couleur("#ff0000")
        self.assertEqual(p.color_wheel, 20)      # la roue est bien sur le rouge

        p.tick_effet_dimmer(0.5)
        # Le modele suit desormais la roue (rouge x 0,5) et non plus le blanc
        # en dur (#7f7f7f) que lisait la 3D.
        self.assertEqual(p.color.name(), "#7f1900")

        # Et l'affichage, lui, part directement de la ROUE, quoi qu'ait ecrit
        # le moteur dans `proj.color` : c'est la ceinture et les bretelles.
        self.assertEqual(color_wheel_display_color(p).name(), "#ff3300")

    def test_parite_2d_3d(self):
        """Meme teinte des deux cotes ; seule l'intensite differe (la 3D recoit
        le niveau a part, dans `level`)."""
        p = FausseLyre()
        p.poser_couleur("#ff0000")
        p.tick_effet_dimmer(0.5)

        c3d = color_wheel_display_color(p)                    # 3D : teinte pure
        c2d = color_wheel_display_color(p, p.level / 100.0)   # 2D : x niveau
        # Tolerance de 1 degre : l'arrondi entier du produit x niveau.
        self.assertLessEqual(abs(c3d.hue() - c2d.hue()), 1)
        self.assertEqual(c2d.name(), "#7f1900")

    def test_niveau_zero_eteint_en_2d(self):
        p = FausseLyre()
        p.poser_couleur("#ff0000")
        p.tick_effet_dimmer(0.0)
        self.assertEqual(color_wheel_display_color(p, 0.0).name(), "#000000")

    def test_led_rvb_non_concernee(self):
        """Un profil R/G/B garde son modele : le helper se retire."""
        self.assertIsNone(color_wheel_display_color(FausseLED()))

    def test_profil_sans_roue_non_concerne(self):
        p = FausseLyre()
        p.dmx_profile = ["Dim", "Pan", "Tilt"]
        self.assertIsNone(color_wheel_display_color(p))

    def test_profil_vide_non_concerne(self):
        """Fixture non patchee : on ne sait rien d'elle, on ne repeint pas."""
        p = FausseLyre()
        p.dmx_profile = []
        self.assertIsNone(color_wheel_display_color(p))

    def test_roue_non_calibree_repli_generique(self):
        """Bibliotheque integree : canal ColorWheel, pas de table de slots."""
        p = FausseLyre(slots=[])
        p.color_wheel = 20      # « Rouge » de la roue generique
        self.assertEqual(color_wheel_display_color(p).name(), "#ff3300")

    def test_slot_franchi_et_non_le_plus_proche(self):
        """Une roue occupe des plages contigues : on garde le dernier slot
        franchi tant que la position suivante n'est pas atteinte."""
        p = FausseLyre()
        p.color_wheel = 80      # entre Rouge (20) et Vert (85)
        self.assertEqual(color_wheel_display_color(p).name(), "#ff3300")
        p.color_wheel = 85
        self.assertEqual(color_wheel_display_color(p).name(), "#00cc44")

    def test_slot_at_repli_sur_la_table_generique(self):
        self.assertEqual(cw_slot_at(None, 0), CW_DEFAULT_SLOTS[0])


class TestEffetDimmerSeul(unittest.TestCase):
    """`effect_dim_base_color` — la couleur que module un Dimmer seul.

    Point UNIQUE du moteur du show ET de l'apercu de l'editeur : elle rendait
    du BLANC en dur sur les profils sans R/G/B, donc une lyre a roue posee sur
    le rouge s'affichait blanche partout.
    """

    def test_lyre_a_roue_rend_la_couleur_de_la_roue(self):
        p = FausseLyre()
        p.poser_couleur("#ff0000")
        self.assertEqual(effect_dim_base_color(p, p.base_color).name(), "#ff3300")

    def test_roue_sur_open_reste_blanche(self):
        """Le cas qui avait impose le blanc : rien n'a ete pose a la main. La
        position 0 d'une roue est « Open » — blanc, jamais noir."""
        p = FausseLyre()
        self.assertEqual(effect_dim_base_color(p, QColor(0, 0, 0)).name(), "#ffffff")

    def test_profil_sans_rvb_ni_roue_reste_blanc(self):
        """Barre UV, gradateur… : pas de roue a interroger, le blanc demeure."""
        p = FausseLyre()
        p.dmx_profile = ["Dim", "UV"]
        self.assertEqual(effect_dim_base_color(p, QColor(0, 0, 0)).name(), "#ffffff")

    def test_led_rvb_inchangee(self):
        p = FausseLED()
        self.assertEqual(effect_dim_base_color(p, QColor("#00ff00")).name(), "#00ff00")

    def test_profil_vide_inchange(self):
        p = FausseLyre()
        p.dmx_profile = []
        self.assertEqual(effect_dim_base_color(p, QColor("#123456")).name(), "#123456")

    def test_pas_de_boucle_de_retroaction(self):
        """La couleur est lue sur la ROUE, pas sur `proj.color` : rejouer des
        frames ne doit pas faire deriver la lyre vers le noir."""
        p = FausseLyre()
        p.poser_couleur("#ff0000")
        for _ in range(50):
            p.tick_effet_dimmer(0.5)
        self.assertEqual(effect_dim_base_color(p, p.base_color).name(), "#ff3300")
        self.assertEqual(p.color_wheel, 20)


class TestSortieLiveEditeur(unittest.TestCase):
    """Sortie live de l'editeur d'effets : sur une lyre a roue, le fil ne porte
    QUE `color_wheel`. Sans mappage, une couche couleur faisait defiler les
    couleurs a l'ecran pendant que la vraie lyre restait sur son slot d'avant.
    """

    def _faux_mw(self, projecteurs, overrides):
        from main_window import MainWindow

        class FauxMW:
            _GENERIC_WHEEL_SLOTS = MainWindow._GENERIC_WHEEL_SLOTS
            _update_color_wheel = MainWindow._update_color_wheel
            _apply_editor_live_overrides = MainWindow._apply_editor_live_overrides
            _restore_editor_live_overrides = staticmethod(
                MainWindow._restore_editor_live_overrides)

        mw = FauxMW()
        mw.projectors = projecteurs
        mw._editor_live_overrides = overrides
        return mw

    def test_couche_couleur_bouge_la_roue(self):
        p = FausseLyre()
        p.poser_couleur("#ff0000")          # roue sur Rouge (20)
        # Une frame d'effet qui demande du VERT sur cette lyre
        mw = self._faux_mw([p], {id(p): (1.0, QColor("#00ff00"), None, None)})

        saved = mw._apply_editor_live_overrides()
        self.assertEqual(p.color_wheel, 85)          # la roue a suivi → Vert
        mw._restore_editor_live_overrides(saved)
        self.assertEqual(p.color_wheel, 20)          # …et elle est rendue

    def test_roue_restauree_avec_le_reste(self):
        """Les overrides ne durent qu'une frame : une roue laissee sur la
        derniere image resterait figee en quittant l'editeur."""
        p = FausseLyre()
        p.poser_couleur("#ff0000")
        avant = (p.level, p.color.name(), p.base_color.name(), p.color_wheel)

        mw = self._faux_mw([p], {id(p): (0.5, QColor("#00ff00"), 1000, 2000)})
        saved = mw._apply_editor_live_overrides()
        mw._restore_editor_live_overrides(saved)

        self.assertEqual((p.level, p.color.name(), p.base_color.name(),
                          p.color_wheel), avant)

    def test_frame_noire_laisse_la_roue_en_place(self):
        """Phase off d'un strobe : le noir n'a pas de teinte, une roue physique
        n'a rien a faire tourner pendant un noir."""
        p = FausseLyre()
        p.poser_couleur("#ff0000")
        mw = self._faux_mw([p], {id(p): (0.0, QColor(0, 0, 0), None, None)})
        mw._apply_editor_live_overrides()
        self.assertEqual(p.color_wheel, 20)

    def test_led_rvb_non_touchee(self):
        p = FausseLED()
        mw = self._faux_mw([p], {id(p): (1.0, QColor("#00ff00"), None, None)})
        mw._apply_editor_live_overrides()
        self.assertEqual(p.color_wheel, 0)


class TestPlanDeFeu2D(unittest.TestCase):
    """La 2D passe bien par le point unique (non-regression de son propre cas)."""

    def test_get_fill_color_suit_la_roue(self):
        from plan_de_feu import FixtureCanvas
        p = FausseLyre()
        p.poser_couleur("#ff0000")
        p.tick_effet_dimmer(1.0)
        p.muted = False

        class _PDF:
            _htp_overrides = None

        canvas = FixtureCanvas.__new__(FixtureCanvas)
        canvas.pdf = _PDF()
        self.assertEqual(FixtureCanvas._get_fill_color(canvas, p).name(),
                         "#ff3300")


if __name__ == "__main__":
    unittest.main(verbosity=2)
