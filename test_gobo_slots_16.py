# -*- coding: utf-8 -*-
"""Roue de gobos symbolique : 16 slots, et les 8 anciens gardent leur DMX.

La roue est passee de 8 a 16 motifs (ajout de la barre, du logo MyStrow et de
six motifs classiques). Le piege de cet elargissement est la COMPATIBILITE : les
shows enregistres portent des valeurs DMX, les prereglages LIVE portent des
INDICES, et les deux devaient continuer a montrer le meme motif qu'avant.

On verifie aussi que les deux dessins — QPainter en 2D, canvas en 3D — couvrent
bien les seize memes slots : ils ont deja diverge une fois.
"""
import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core
from core import (GOBO_SLOT_NAMES, GOBO_SLOT_ICONS, GOBO_SLOT_COUNT,
                  GOBO_SLOT_STEP, gobo_slot_index, gobo_slot_dmx)

_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "plan_3d_web.html")


class TestTableCanonique(unittest.TestCase):

    def test_seize_slots_nommes_et_illustres(self):
        self.assertEqual(GOBO_SLOT_COUNT, 16)
        self.assertEqual(GOBO_SLOT_STEP, 16)
        self.assertEqual(len(GOBO_SLOT_ICONS), GOBO_SLOT_COUNT)
        self.assertEqual(len(set(GOBO_SLOT_NAMES)), GOBO_SLOT_COUNT)

    def test_les_nouveaux_motifs_demandes(self):
        self.assertIn("Barre", GOBO_SLOT_NAMES)
        self.assertIn("Logo MyStrow", GOBO_SLOT_NAMES)

    def test_index_et_dmx_sont_reciproques(self):
        for i in range(GOBO_SLOT_COUNT):
            self.assertEqual(gobo_slot_index(gobo_slot_dmx(i)), i)

    def test_bornes_et_valeurs_absurdes(self):
        self.assertEqual(gobo_slot_index(0), 0)
        self.assertEqual(gobo_slot_index(255), GOBO_SLOT_COUNT - 1)
        self.assertEqual(gobo_slot_index(999), GOBO_SLOT_COUNT - 1)
        self.assertEqual(gobo_slot_index(-5), 0)
        self.assertEqual(gobo_slot_index(None), 0)
        self.assertEqual(gobo_slot_dmx(99), 240)


class TestCompatibiliteAscendante(unittest.TestCase):
    """Le coeur de l'affaire : ne pas changer ce que montrent les vieux shows."""

    # Ce que la roue a 8 slots affichait, dans l'ordre de ses valeurs DMX.
    ANCIENS = ("Ouvert", "Anneau", "Étoile 4 branches", "Trois cercles",
               "Trois palmes", "Breakup", "Six rayons", "Bull's-eye")

    def test_une_vieille_valeur_dmx_montre_toujours_le_meme_motif(self):
        for ancien_idx, nom in enumerate(self.ANCIENS):
            dmx = ancien_idx * 32           # ce qu'un show d'avant a enregistre
            self.assertEqual(GOBO_SLOT_NAMES[gobo_slot_index(dmx)], nom,
                             f"DMX {dmx} a change de motif")

    def test_les_nouveaux_sont_aux_index_impairs(self):
        for i in range(1, GOBO_SLOT_COUNT, 2):
            self.assertNotIn(GOBO_SLOT_NAMES[i], self.ANCIENS)


class TestMigrationDesPools(unittest.TestCase):
    """Les pools LIVE / IA sont des INDICES : ils doivent etre doubles."""

    def test_pool_ia_ancien_format(self):
        from ia_settings import IASettings
        # Pas de temoin `gobo_slots` => prereglage ecrit du temps des 8 slots.
        s = IASettings.from_dict({'gobo_pool': [0, 2, 7]})
        self.assertEqual(sorted(s.gobo_pool), [0, 4, 14])
        # …et les motifs vises sont bien ceux d'avant.
        self.assertEqual([GOBO_SLOT_NAMES[i] for i in sorted(s.gobo_pool)],
                         ["Ouvert", "Étoile 4 branches", "Bull's-eye"])

    def test_pool_ia_nouveau_format_intact(self):
        from ia_settings import IASettings
        s = IASettings.from_dict({'gobo_pool': [0, 1, 3], 'gobo_slots': 16})
        self.assertEqual(sorted(s.gobo_pool), [0, 1, 3])

    def test_aller_retour_stable(self):
        from ia_settings import IASettings
        s1 = IASettings.from_dict({'gobo_pool': [0, 3, 5], 'gobo_slots': 16})
        s2 = IASettings.from_dict(s1.to_dict())
        self.assertEqual(sorted(s1.gobo_pool), sorted(s2.gobo_pool))


class TestRoueGenerique(unittest.TestCase):

    def test_seize_slots_nommes_comme_les_motifs(self):
        from color_wheel_editor import _GENERIC_GOBO_SLOTS
        self.assertEqual(len(_GENERIC_GOBO_SLOTS), GOBO_SLOT_COUNT)
        self.assertEqual([s["name"] for s in _GENERIC_GOBO_SLOTS],
                         list(GOBO_SLOT_NAMES))
        self.assertEqual([s["dmx"] for s in _GENERIC_GOBO_SLOTS],
                         [i * GOBO_SLOT_STEP for i in range(GOBO_SLOT_COUNT)])


class TestLesDeuxDessins(unittest.TestCase):
    """⚠️ Les motifs sont traces DEUX fois, au QPainter et au canvas."""

    def test_le_canvas_3d_couvre_les_seize_slots(self):
        with open(_HTML, encoding="utf-8") as f:
            html = f.read()
        i = html.index("function _createGoboTexture(slot) {")
        j = html.index("const _goboTextures", i)
        cases = set(int(m) for m in re.findall(r"case (\d+):", html[i:j]))
        self.assertEqual(cases, set(range(GOBO_SLOT_COUNT)))

    def test_le_3d_decoupe_le_canal_comme_core(self):
        """Les deux plans doivent tomber sur le MEME slot pour un DMX donne.

        C'est la divergence qui avait deja frappe une fois : il suffit qu'un des
        deux cotes garde un 8 en dur pour que le meme show ne se lise plus
        pareil selon la fenetre ouverte.
        """
        with open(_HTML, encoding="utf-8") as f:
            html = f.read()
        m = re.search(r"Math\.min\((\w+) - 1,\s*"
                      r"Math\.floor\(\(\(p\.gobo \|\| 0\) / 256\) \* (\w+)\)\)", html)
        self.assertIsNotNone(m, "formule de slot 3D introuvable ou reecrite")
        self.assertEqual(m.group(1), "GOBO_SLOT_COUNT")
        self.assertEqual(m.group(2), "GOBO_SLOT_COUNT")

        n = int(re.search(r"const GOBO_SLOT_COUNT = (\d+);", html).group(1))
        self.assertEqual(n, GOBO_SLOT_COUNT)
        for v in range(256):
            js = min(n - 1, int((v / 256) * n))
            self.assertEqual(js, gobo_slot_index(v), f"DMX {v}")

    def test_le_2d_dessine_quelque_chose_pour_chaque_slot(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPixmap, QPainter, QColor
        from PySide6.QtCore import QPoint, Qt
        from plan_de_feu import _draw_gobo_pattern

        app = QApplication.instance() or QApplication([])
        for slot in range(GOBO_SLOT_COUNT):
            pm = QPixmap(160, 70)
            pm.fill(QColor("#000000"))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            _draw_gobo_pattern(p, slot, 80, 35, 70, 24, QColor("#ffffff"))
            p.end()
            img = pm.toImage()
            allume = sum(1 for y in range(0, 70, 2) for x in range(0, 160, 2)
                         if img.pixelColor(x, y).lightness() > 40)
            if slot == 0:
                self.assertEqual(allume, 0, "le slot Ouvert ne dessine rien")
            else:
                self.assertGreater(
                    allume, 0, f"le slot {slot} ({GOBO_SLOT_NAMES[slot]}) "
                               f"ne trace rien dans la tache")

    def test_le_2d_ne_deborde_pas_de_la_tache(self):
        """Le motif est decoupe a l'ellipse, comme le `destination-in` de la 3D."""
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPixmap, QPainter, QColor
        from plan_de_feu import _draw_gobo_pattern

        app = QApplication.instance() or QApplication([])
        ox, oy, iw, ih = 80, 35, 60, 20
        for slot in range(1, GOBO_SLOT_COUNT):
            pm = QPixmap(160, 70)
            pm.fill(QColor("#000000"))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            _draw_gobo_pattern(p, slot, ox, oy, iw, ih, QColor("#ffffff"))
            p.end()
            img = pm.toImage()
            for y in range(70):
                for x in range(160):
                    if img.pixelColor(x, y).lightness() <= 40:
                        continue
                    # Marge d'un pixel : l'antialiasing deborde d'un demi-pixel.
                    d = ((x - ox) / (iw + 1.5)) ** 2 + ((y - oy) / (ih + 1.5)) ** 2
                    self.assertLessEqual(
                        d, 1.0,
                        f"slot {slot} ({GOBO_SLOT_NAMES[slot]}) : pixel "
                        f"({x},{y}) hors de la tache")


if __name__ == "__main__":
    unittest.main(verbosity=2)
