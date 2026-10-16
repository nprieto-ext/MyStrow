"""
test_channel_ranges.py — Plage utile par canal (« brider » un canal).

Beaucoup d'appareils d'entree de gamme rangent un programme AUTO dans le haut de
la course d'un canal : sur le laser generique 10 canaux, Pan/Tilt valent
« position » sur 0-127 et « mouvement auto » au-dela. `channel_ranges` borne ce
que le moteur envoie.

Ce qui est verrouille ici :

  * un canal continu (Dim, Zoom…) est MIS A L'ECHELLE : fader a fond = max de
    la plage, toute la course reste utile ;
  * Pan/Tilt sont etires d'un bloc en 16 bits (canal fin compris) et APRES
    l'inversion : la plage decrit le canal physique ;
  * une valeur EXACTE (slot de roue, preset) n'est que BORNEE, jamais etiree —
    sinon le slot « Rouge » tomberait sur le jaune ;
  * les valeurs brutes (curseur par numero, couche d'effet, channel_defaults)
    sont bornees, pas etirees ;
  * sans plage, la trame est identique a l'octet pres ;
  * la fixture laser de la bibliotheque arrive bridee, et la plage survit a
    l'aller-retour disque.

    python test_channel_ranges.py
"""

import json
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from projector import Projector
from artnet_dmx import ArtNetDMX
from core import (channel_range, normalize_channel_ranges, scale_to_range,
                  scale16_to_range)
import builtin_fixtures


def _trame(proj):
    nb = len(proj.dmx_profile)
    dmx = ArtNetDMX()
    dmx.set_projector_patch("face_0", list(range(1, nb + 1)), 0, proj.dmx_profile)
    dmx.update_from_projectors([proj])
    return [dmx.get_channel(i) for i in range(1, nb + 1)]


def _proj(profile, ftype="Laser"):
    p = Projector("face", name="t", fixture_type=ftype)
    p.dmx_profile = list(profile)
    return p


class Helpers(unittest.TestCase):

    def test_plage_pleine_ou_absente_ne_bride_rien(self):
        self.assertIsNone(channel_range({}, "Pan"))
        self.assertIsNone(channel_range({"Pan": [0, 255]}, "Pan"))
        self.assertIsNone(channel_range({"Pan": "n'importe quoi"}, "Pan"))

    def test_bornes_inversees_et_hors_limites(self):
        self.assertEqual(channel_range({"Pan": [300, 64]}, "Pan"), (64, 255))
        self.assertEqual(normalize_channel_ranges({"Zoom": [63, 0], "Dim": [0, 255]}),
                         {"Zoom": [0, 63]})

    def test_mise_a_l_echelle(self):
        self.assertEqual(scale_to_range(0,   (0, 127)), 0)
        self.assertEqual(scale_to_range(255, (0, 127)), 127)
        self.assertEqual(scale16_to_range(65535, (0, 127)), 127 * 256 + 255)
        self.assertEqual(scale16_to_range(0, (64, 127)), 64 * 256)


class Moteur(unittest.TestCase):

    def test_dim_mis_a_l_echelle(self):
        p = _proj(["Dim", "R", "G", "B"], "PAR LED")
        p.set_level(100)
        p.channel_ranges = {"Dim": [0, 127]}
        self.assertEqual(_trame(p)[0], 127,
                         "fader a fond = haut de la plage, pas le strobe au-dessus")

    def test_pan_tilt_16_bits_d_un_bloc(self):
        p = _proj(["Pan", "PanFine", "Tilt", "TiltFine"])
        p.pan, p.tilt = 65535, 32768
        p.channel_ranges = {"Pan": [0, 127], "Tilt": [0, 127]}
        t = _trame(p)
        self.assertEqual(t[0:2], [127, 255], "pan a fond = 127/255, jamais 128+")
        self.assertIn(t[2], (63, 64), "tilt au centre = milieu de 0-127")

    def test_bride_apres_inversion(self):
        p = _proj(["Pan", "Tilt"])
        p.pan, p.tilt = 0, 0
        p.pan_invert = True
        p.channel_ranges = {"Pan": [0, 127]}
        self.assertEqual(_trame(p)[0], 127,
                         "pan inverse a 0 = haut de la plage, pas 255")

    def test_roue_bornee_pas_etiree(self):
        p = _proj(["ColorWheel"])
        p.color_wheel = 95
        p.channel_ranges = {"ColorWheel": [0, 191]}
        self.assertEqual(_trame(p), [95], "un slot calibre sort sa valeur exacte")
        p.color_wheel = 230
        self.assertEqual(_trame(p), [191], "au-dela de la plage : borne")

    def test_valeurs_brutes_bornees(self):
        p = _proj(["Pan", "Tilt", "Zoom"])
        p.channel_ranges = {"Pan": [0, 127], "Zoom": [0, 63]}
        p.channel_extras = {1: 100, "Zoom": 200}
        t = _trame(p)
        self.assertEqual(t[0], 100, "curseur brut dans la plage : tel quel")
        self.assertEqual(t[2], 63, "curseur brut hors plage : borne")
        p.channel_extras = {}
        p.effect_channels = {1: 250}
        self.assertEqual(_trame(p)[0], 127, "couche d'effet bornee aussi")

    def test_sans_plage_trame_inchangee(self):
        p = _proj(["Dim", "Pan", "PanFine", "ColorWheel", "Zoom"], "Moving Head")
        p.set_level(100)
        p.pan, p.color_wheel, p.zoom = 65535, 230, 255
        avant = _trame(p)
        p.channel_ranges = {}
        self.assertEqual(_trame(p), avant)
        self.assertEqual(avant[1:3], [255, 255])


class FixtureLaser(unittest.TestCase):

    def _laser(self):
        return next(f for f in builtin_fixtures.BUILTIN_FIXTURES
                    if f["name"] == "Laser Show System · Laser 10ch")

    def test_bibliotheque_bridee(self):
        fx = self._laser()
        self.assertEqual(fx["channel_ranges"]["Pan"], [0, 127])
        self.assertEqual(fx["channel_ranges"]["Tilt"], [0, 127])
        p = _proj(fx["profile"])
        p.channel_ranges = normalize_channel_ranges(fx["channel_ranges"])
        p.pan = p.tilt = 65535
        p.zoom = 255
        t = _trame(p)
        self.assertLessEqual(t[5], 127, "Pan ne doit jamais lancer le mouvement auto")
        self.assertLessEqual(t[6], 127, "Tilt non plus")
        self.assertLessEqual(t[7], 63, "le zoom reste en taille fixe")
        self.assertEqual(t[0], 0, "repos = laser eteint")

    def test_aller_retour_json(self):
        r = normalize_channel_ranges(self._laser()["channel_ranges"])
        self.assertEqual(normalize_channel_ranges(json.loads(json.dumps(r))), r)


class DebattementLaser(unittest.TestCase):
    """Un laser n'est pas une lyre 540/270 : meme angle sur les deux axes."""

    def test_cercle_rond(self):
        import core
        p = _proj(["Pan", "Tilt"], "Laser")
        self.assertEqual(core.pan_tilt_ranges(p),
                         (core.LASER_SCAN_DEFAULT, core.LASER_SCAN_DEFAULT))
        self.assertEqual(core.pan_angular_ratio(p), 1.0,
                         "a 0,5 le cercle sortait en ovale deux fois plus etroit")

    def test_lyre_inchangee(self):
        import core
        p = _proj(["Pan", "Tilt"], "Moving Head")
        self.assertEqual(core.pan_tilt_ranges(p), (540.0, 270.0))

    def test_valeur_saisie_respectee(self):
        import core
        p = _proj(["Pan", "Tilt"], "Laser")
        p.pan_range, p.tilt_range = 40.0, 30.0
        self.assertEqual(core.pan_tilt_ranges(p), (40.0, 30.0))


class PanneauLaser(unittest.TestCase):
    """Logique pure du menu laser (motif N / total, noms courts)."""

    def test_nombre_de_motifs_lu_dans_le_nom(self):
        from core import laser_pattern_count
        fx = next(f for f in builtin_fixtures.BUILTIN_FIXTURES
                  if f["name"] == "Laser Show System · Laser 10ch")
        self.assertEqual(laser_pattern_count(fx["channel_labels"], fx["profile"]), 51)
        self.assertIsNone(laser_pattern_count(["Motif"], ["Gobo1"]))
        self.assertIsNone(laser_pattern_count([], ["Gobo1"]))

    def test_aller_retour_motif_dmx(self):
        from core import laser_pattern_index, laser_pattern_dmx
        for n in (2, 16, 51, 128):
            for i in range(n):
                self.assertEqual(laser_pattern_index(laser_pattern_dmx(i, n), n), i)
        # Les fleches bouclent : avant le premier = le dernier.
        self.assertEqual(laser_pattern_index(laser_pattern_dmx(-1, 51), 51), 50)
        self.assertEqual(laser_pattern_index(laser_pattern_dmx(51, 51), 51), 0)

    def test_nom_court(self):
        from core import short_channel_label
        self.assertEqual(short_channel_label("Position X (0-127 ; 128+ = auto)"),
                         "Position X")
        self.assertEqual(short_channel_label("Couleur"), "Couleur")


if __name__ == "__main__":
    unittest.main(verbosity=2)
