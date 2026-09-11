"""
test_amp_plafond_mouvement.py — Plafond de la colonne AMP sur les canaux de
mouvement (Pan, Tilt, Pan/Tilt).

Contexte (retour Christo, 11/09/2026) : « tu peux mettre a 100, ca va pas plus
que je dirai 30 40 ». Mesure juste. Le moteur convertit AMP 100 en +/-8192, soit
12,5 % de la course DMX : sur une lyre 540 deg, AMP 100 ne balaie que 67,5 deg.
La 3.1.91 avait porte le facteur a 32768 et quadruple le mouvement de TOUS les
shows existants ; la 3.1.92 a du l'annuler. La reponse retenue est de laisser le
facteur tranquille et de monter le PLAFOND de la colonne a 400 sur ces canaux
seulement : les couches deja enregistrees gardent leur rendu exact, et AMP 400
reproduit a l'identique ce que la 3.1.91 donnait a AMP 100.

Ce que ces tests verrouillent :
  1. le plafond vaut 400 sur Pan / Tilt / Pan/Tilt, 100 ailleurs ;
  2. une couche relue a 400 garde 400 (deux pieges d'ORDRE : la cellule naissait
     bornee a 100, et `refresh()` reposait les valeurs avant le plafond) ;
  3. changer le canal pour un canal d'intensite rabat la valeur — un `size` de
     400 laisse sur un Dimmer multiplierait l'intensite par quatre ;
  4. les 5 sites de rendu portent toujours `* 8192`, a l'identique de part et
     d'autre (apercu de l'editeur ET moteur du show).
"""

import io
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from effect_editor import EffectLayer, LayerRow

_app = QApplication.instance() or QApplication(sys.argv)


def _ligne(attribute="Dimmer", size=100):
    layer           = EffectLayer()
    layer.attribute = attribute
    layer.size      = size
    return LayerRow(layer), layer


class TestPlafondSelonLeCanal(unittest.TestCase):

    def test_canaux_de_mouvement_montent_a_400(self):
        for attr in ("Pan", "Tilt", "Pan/Tilt"):
            with self.subTest(attr=attr):
                row, _ = _ligne(attr)
                self.assertEqual(row._cells["amp"].maximum(), 400)

    def test_canaux_d_intensite_restent_a_100(self):
        for attr in ("Dimmer", "R", "RGB", "Zoom", "Strobe"):
            with self.subTest(attr=attr):
                row, _ = _ligne(attr)
                self.assertEqual(row._cells["amp"].maximum(), 100)

    def test_les_autres_colonnes_ne_bougent_pas(self):
        """Seule AMP change de plafond : VIT, MIN, MAX, DEC gardent le leur."""
        row, _ = _ligne("Pan/Tilt")
        self.assertEqual(row._cells["vit"].maximum(), 100)
        self.assertEqual(row._cells["min"].maximum(), 100)
        self.assertEqual(row._cells["max"].maximum(), 100)
        self.assertEqual(row._cells["dec"].maximum(), 360)


class TestUneCoucheA400SurvitALaRelecture(unittest.TestCase):
    """Les deux pieges d'ordre : la cellule ne doit jamais rabattre le modele."""

    def test_construction_ne_rabat_pas_a_100(self):
        # La cellule naissait bornee a 100 et rabattait AMP 400 AVANT que
        # `_sync_amp_ceiling` n'ait pu relever la borne.
        row, layer = _ligne("Pan/Tilt", size=400)
        self.assertEqual(row._cells["amp"].value(), 400)
        self.assertEqual(layer.size, 400)

    def test_refresh_ne_rabat_pas_a_100(self):
        # `refresh()` (edition par colonne) reposait les valeurs depuis le
        # modele : il lui faut le plafond d'abord.
        row, layer = _ligne("Pan/Tilt", size=400)
        row.refresh()
        self.assertEqual(row._cells["amp"].value(), 400)
        self.assertEqual(layer.size, 400)

    def test_aller_retour_par_le_dictionnaire(self):
        """400 traverse to_dict/from_dict : c'est ce qui va dans les .lrec."""
        layer      = EffectLayer()
        layer.attribute = "Pan"
        layer.size      = 400
        relu = EffectLayer.from_dict(layer.to_dict())
        self.assertEqual(relu.size, 400)
        self.assertEqual(LayerRow(relu)._cells["amp"].value(), 400)


class TestChangementDeCanal(unittest.TestCase):

    def test_mouvement_vers_intensite_rabat_la_valeur(self):
        """Un `size` de 400 laisse sur un Dimmer quadruplerait l'intensite.

        La sortie d'un canal d'intensite vaut
        `(min + forme x (max - min)) x size / 100` : 400 y est un facteur 4, pas
        une amplitude.
        """
        row, layer = _ligne("Pan/Tilt", size=400)
        row._attr_cb.setCurrentText("Dimmer")
        self.assertEqual(layer.attribute, "Dimmer")
        self.assertEqual(layer.size, 100)
        self.assertEqual(row._cells["amp"].maximum(), 100)
        self.assertEqual(row._cells["amp"].value(), 100)

    def test_intensite_vers_mouvement_ouvre_le_plafond(self):
        row, layer = _ligne("Dimmer", size=100)
        row._attr_cb.setCurrentText("Pan")
        self.assertEqual(row._cells["amp"].maximum(), 400)
        # La valeur, elle, ne bouge pas : on ouvre une possibilite, on ne
        # decide pas a la place de l'utilisateur.
        self.assertEqual(layer.size, 100)

    def test_une_couche_sous_le_plafond_traverse_intacte(self):
        row, layer = _ligne("Pan", size=60)
        row._attr_cb.setCurrentText("Dimmer")
        self.assertEqual(layer.size, 60)
        row._attr_cb.setCurrentText("Tilt")
        self.assertEqual(layer.size, 60)

    def test_pas_de_recursion_a_la_saisie(self):
        """`valueChanged` -> `_sync_enabled_state` -> plafond ne doit pas boucler.

        `set_maximum` n'emet rien, par construction : sinon le plafond
        re-declencherait le signal qui l'a appele.
        """
        row, layer = _ligne("Pan/Tilt", size=100)
        vus = []
        row.changed.connect(lambda: vus.append(layer.size))
        row._cells["amp"].set_value(400)
        self.assertEqual(layer.size, 400)
        self.assertEqual(len(vus), 1)


class TestLeFacteurDeRenduNeBougePas(unittest.TestCase):
    """Le plafond monte, le facteur 8192 reste : c'est tout l'interet du choix.

    Un seul des 5 sites qui partirait a 32768 re-quadruplerait les shows
    existants, et le faire d'un seul cote (apercu OU show) ferait mentir
    l'apercu sur le rendu reel.
    """

    _SITES = {'effect_editor.py': 3, 'main_window.py': 2}

    @staticmethod
    def _lignes_de_code(fichier, motif):
        """Lignes de code portant `motif`, commentaires exclus.

        Les commentaires citent le facteur abondamment — c'est voulu, ils
        expliquent pourquoi il ne bouge pas — et les compter rendrait ce test
        faux a la premiere phrase ajoutee.
        """
        with io.open(fichier, encoding='utf-8') as f:
            return [l for l in f
                    if motif in l and not l.lstrip().startswith('#')]

    def test_les_cinq_sites_portent_8192(self):
        for fichier, attendu in self._SITES.items():
            with self.subTest(fichier=fichier):
                self.assertEqual(len(self._lignes_de_code(fichier, '* 8192')),
                                 attendu)
                self.assertEqual(self._lignes_de_code(fichier, '* 32768'), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
