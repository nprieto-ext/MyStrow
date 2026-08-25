"""
test_effect_editor_ux.py — Editeur d'effets : deux pieges de la colonne de gauche.

1. Cliquer sur une autre carte pour la REGARDER jetait toutes les couches
   editees de l'effet precedent : `_apply_preset` vide `self._layers`, et rien
   ne gardait le travail en cours. La machinerie existait pourtant, complete,
   mais n'etait branchee que sur la fermeture (`_autosave_on_close`).

2. Le ✕ de la carte fait 14 px, colle au ✎ de renommage : un clic de travers
   effacait un effet definitivement, sans confirmation ni retour possible.

Aucun de ces tests ne touche au fichier custom_effects reel : `_save_custom_effects`
est remplace par un mouchard.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

import effect_editor as fx
from effect_editor import EffectEditorDialog

_app = QApplication.instance() or QApplication(sys.argv)


class FauxEditeur:
    """L'editeur reduit a ce que les deux methodes testees manipulent."""

    _switch_to_effect     = EffectEditorDialog._switch_to_effect
    _delete_custom_effect = EffectEditorDialog._delete_custom_effect

    def __init__(self, selected="Papillon", customs=None):
        self._selected_card   = selected
        self._custom_effects  = customs if customs is not None else []
        self.autosaves        = 0
        self.applied          = []
        self.rebuilds         = 0

    def _autosave_on_close(self):
        self.autosaves += 1

    def _apply_preset(self, eff):
        self.applied.append(eff.get("name", ""))
        self._selected_card = eff.get("name", "")

    def _rebuild_library(self):
        self.rebuilds += 1


class _Patch:
    """Remplace `_save_custom_effects` et `QMessageBox.question` le temps d'un test."""

    def __init__(self, reponse):
        self.reponse   = reponse
        self.sauvegardes = []
        self.questions   = []

    def __enter__(self):
        self._vrai_save = fx._save_custom_effects
        self._vraie_q   = QMessageBox.question
        fx._save_custom_effects = lambda effets: self.sauvegardes.append(list(effets))
        QMessageBox.question = staticmethod(
            lambda *a, **k: (self.questions.append(a), self.reponse)[1])
        return self

    def __exit__(self, *exc):
        fx._save_custom_effects = self._vrai_save
        QMessageBox.question    = self._vraie_q
        return False


EFFETS = [{"name": "Papillon", "layers": []},
          {"name": "Vague",    "layers": []}]


class TestChangementDEffet(unittest.TestCase):

    def test_le_travail_en_cours_est_garde(self):
        """Le bug rapporte : cliquer sur une autre carte ne doit plus rien jeter."""
        ed = FauxEditeur(selected="Papillon")
        ed._switch_to_effect({"name": "Vague"})
        self.assertEqual(ed.autosaves, 1)
        self.assertEqual(ed.applied, ["Vague"])

    def test_recliquer_sur_la_meme_carte_ne_sauvegarde_pas(self):
        """Aucun changement d'effet → rien a garder, on ne reecrit pas les
        fichiers de config a chaque clic."""
        ed = FauxEditeur(selected="Papillon")
        ed._switch_to_effect({"name": "Papillon"})
        self.assertEqual(ed.autosaves, 0)
        self.assertEqual(ed.applied, ["Papillon"])

    def test_premiere_selection_de_la_session(self):
        """Rien n'est encore charge : pas d'autosave a faire, mais l'effet
        demande doit bien s'ouvrir."""
        ed = FauxEditeur(selected=None)
        ed._switch_to_effect({"name": "Vague"})
        self.assertEqual(ed.applied, ["Vague"])

    def test_sauvegarde_avant_le_chargement(self):
        """L'ordre compte : `_apply_preset` vide `self._layers`, autosaver
        apres ne garderait plus rien."""
        ordre = []
        ed = FauxEditeur(selected="Papillon")
        ed._autosave_on_close = lambda: ordre.append("save")
        ed._apply_preset      = lambda e: ordre.append("load")
        ed._switch_to_effect({"name": "Vague"})
        self.assertEqual(ordre, ["save", "load"])


class TestSuppressionConfirmee(unittest.TestCase):

    def test_annuler_ne_supprime_rien(self):
        ed = FauxEditeur(customs=list(EFFETS))
        with _Patch(QMessageBox.Cancel) as p:
            ed._delete_custom_effect(EFFETS[0])
        self.assertEqual([e["name"] for e in ed._custom_effects],
                         ["Papillon", "Vague"])
        self.assertEqual(p.sauvegardes, [])      # rien ecrit sur le disque
        self.assertEqual(ed.rebuilds, 0)
        self.assertEqual(len(p.questions), 1)    # …mais la question a ete posee

    def test_confirmer_supprime(self):
        ed = FauxEditeur(customs=list(EFFETS))
        with _Patch(QMessageBox.Yes) as p:
            ed._delete_custom_effect(EFFETS[0])
        self.assertEqual([e["name"] for e in ed._custom_effects], ["Vague"])
        self.assertEqual(len(p.sauvegardes), 1)
        self.assertEqual(ed.rebuilds, 1)

    def test_la_carte_selectionnee_est_liberee(self):
        ed = FauxEditeur(selected="Papillon", customs=list(EFFETS))
        with _Patch(QMessageBox.Yes):
            ed._delete_custom_effect(EFFETS[0])
        self.assertIsNone(ed._selected_card)

    def test_supprimer_un_autre_effet_ne_deselectionne_pas(self):
        ed = FauxEditeur(selected="Papillon", customs=list(EFFETS))
        with _Patch(QMessageBox.Yes):
            ed._delete_custom_effect(EFFETS[1])
        self.assertEqual(ed._selected_card, "Papillon")

    def test_le_nom_est_dans_la_question(self):
        """Le ✕ est minuscule : le message doit dire LEQUEL part."""
        ed = FauxEditeur(customs=list(EFFETS))
        with _Patch(QMessageBox.Cancel) as p:
            ed._delete_custom_effect(EFFETS[0])
        texte = " ".join(str(a) for a in p.questions[0])
        self.assertIn("Papillon", texte)


class TestTraductions(unittest.TestCase):
    """Les cles doivent exister dans les 5 langues, sinon tr() rend la cle."""

    def test_cles_completes(self):
        from i18n import TRANSLATIONS
        for cle in ("fx_delete_title", "fx_f_delete_confirm"):
            self.assertIn(cle, TRANSLATIONS)
            for lang in ("en", "fr", "es", "de", "pt"):
                self.assertTrue(TRANSLATIONS[cle].get(lang), f"{cle}/{lang}")

    def test_le_message_accepte_le_nom(self):
        from i18n import TRANSLATIONS
        for lang, txt in TRANSLATIONS["fx_f_delete_confirm"].items():
            self.assertIn("{name}", txt, lang)


if __name__ == "__main__":
    unittest.main(verbosity=2)
