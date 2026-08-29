"""
test_vider_la_piste.py — « Vider la piste » au clic droit (REC Lumiere).

Demande apres le bug de la generation IA : une piste remplie par erreur ne se
vidait qu'au lasso + Suppr, geste qui rate tout ce qui est hors de l'ecran.

L'action est posee par `LightTrack._add_clear_track_action`, branchee sur les
menus de zone vide de toutes les pistes + le menu de l'en-tete (le seul
accessible quand la piste est pleine de bout en bout). Elle ne s'affiche jamais
sur une piste vide (faux bouton) ni verrouillee (le cadenas garde deja tous les
autres chemins d'ecriture), et `clear_all_clips` demande confirmation.

    python test_vider_la_piste.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

_app = QApplication.instance() or QApplication(sys.argv)

import light_timeline as lt
from i18n import tr


class FauxEditeur:
    def __init__(self):
        self.etats = 0

    def save_state(self):
        self.etats += 1


class FaussePiste:
    """LightTrack reduite a ce que touchent les deux methodes en jeu."""

    _add_clear_track_action = lt.LightTrack._add_clear_track_action
    clear_all_clips         = lt.LightTrack.clear_all_clips
    _EFFECT_MENU_STYLE      = ""

    def __init__(self, n_clips=3, locked=False):
        self.clips          = [object() for _ in range(n_clips)]
        self.selected_clips = list(self.clips)
        self.locked         = locked
        self.parent_editor  = FauxEditeur()
        self.repeints       = 0

    def display_name(self):
        return "Effet"

    def update(self):
        self.repeints += 1


class ActionViderLaPiste(unittest.TestCase):

    def _libelles(self, menu):
        return [a.text() for a in menu.actions() if not a.isSeparator()]

    def test_absente_si_piste_vide(self):
        """Pas de faux bouton sur une piste qui n'a rien a vider."""
        piste, menu = FaussePiste(n_clips=0), QMenu()
        self.assertFalse(piste._add_clear_track_action(menu))
        self.assertEqual(menu.actions(), [])

    def test_absente_si_piste_verrouillee(self):
        piste, menu = FaussePiste(locked=True), QMenu()
        self.assertFalse(piste._add_clear_track_action(menu))
        self.assertEqual(menu.actions(), [])

    def test_ajoutee_avec_le_nombre_de_blocs(self):
        piste, menu = FaussePiste(n_clips=7), QMenu()
        self.assertTrue(piste._add_clear_track_action(menu))
        self.assertIn("7", self._libelles(menu)[-1])

    def test_en_tete_des_menus_de_selection(self):
        """top=True : dans un menu de 60 effets, l'action serait injoignable en bas."""
        piste, menu = FaussePiste(), QMenu()
        for nom in ("Strobe", "Chenillard", "Sinus"):
            menu.addAction(nom)
        piste._add_clear_track_action(menu, top=True)
        # Libellé comparé via tr() : le test ne doit dépendre d'aucune langue
        # (la config réelle de l'utilisateur décide, et on n'y touche pas).
        self.assertEqual(self._libelles(menu)[0], tr("lt_f_clear_track", n=3))
        self.assertTrue(menu.actions()[1].isSeparator())

    def test_separateur_avant_les_actions_existantes(self):
        piste, menu = FaussePiste(), QMenu()
        menu.addAction("Créer un bloc")
        piste._add_clear_track_action(menu)
        self.assertTrue(menu.actions()[1].isSeparator())


class ViderEffectivement(unittest.TestCase):

    def setUp(self):
        self._question = QMessageBox.question

    def tearDown(self):
        QMessageBox.question = self._question

    def test_confirme_vide_la_piste_et_empile_l_undo(self):
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        piste = FaussePiste(n_clips=5)
        piste.clear_all_clips()
        self.assertEqual(piste.clips, [])
        self.assertEqual(piste.selected_clips, [])
        # save_state APRES coup (convention de delete_clip) → Ctrl+Z ramene tout
        self.assertEqual(piste.parent_editor.etats, 1)

    def test_annule_ne_touche_a_rien(self):
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Cancel)
        piste = FaussePiste(n_clips=5)
        piste.clear_all_clips()
        self.assertEqual(len(piste.clips), 5)
        self.assertEqual(piste.parent_editor.etats, 0)

    def test_piste_verrouillee_intouchable(self):
        """Meme appelee de force (raccourci, menu perime) : le cadenas prime."""
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        piste = FaussePiste(n_clips=5, locked=True)
        piste.clear_all_clips()
        self.assertEqual(len(piste.clips), 5)
        self.assertEqual(piste.parent_editor.etats, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
