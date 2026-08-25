"""
test_effect_position_pdf.py — Positions du plan de feu dans l'editeur d'effets.

Les positions de lyre vivent dans DEUX fichiers, jamais fusionnes :

    positions AKAI     ~/.maestro_akai_config.json   → `position_presets`
    presets Plan de Feu ~/.mystrow_moving_presets.json → liste racine

Le menu POSITION d'une couche Pan/Tilt ne listait que le premier : une position
tout juste creee depuis le plan de feu 2D etait introuvable dans l'editeur
d'effets, alors qu'elle existait bel et bien.

Rien n'est ecrit sur le disque ici : les faux objets remplacent
`_save_akai_config_auto` et `_load_pdf_presets`.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from main_window import MainWindow
from effect_editor import LayerRow


class FausseLyre:
    fixture_type = "Moving Head"

    def __init__(self, nom, adresse, pan=32768, tilt=32768, groupe="lyre"):
        self.name = nom
        self.start_address = adresse
        self.pan = pan
        self.tilt = tilt
        self.group = groupe


def pdf_preset(nom, par_adresse=None):
    """Preset au format Plan de Feu : per_proj indexe par str(start_address)."""
    return {"name": nom, "pan": 32768, "tilt": 32768,
            "per_proj": {str(a): {"pan": pt[0], "tilt": pt[1]}
                         for a, pt in (par_adresse or {}).items()}}


class FauxMW:
    """La fenetre principale reduite a ce que la conversion manipule."""

    _pdf_preset_to_akai        = MainWindow._pdf_preset_to_akai
    pdf_position_to_akai_index = MainWindow.pdf_position_to_akai_index
    sync_pdf_positions_into_akai = MainWindow.sync_pdf_positions_into_akai
    _load_pdf_presets          = MainWindow._load_pdf_presets

    def __init__(self, akai=None, pdf=None, lyres=None):
        self.position_presets = akai if akai is not None else []
        self.projectors = lyres if lyres is not None else [
            FausseLyre("Lyre 1", 1), FausseLyre("Lyre 2", 21)]
        self._pdf = pdf if pdf is not None else []
        self.sauvegardes = 0

    def _save_akai_config_auto(self):
        self.sauvegardes += 1

    def _load_pdf_presets(self):          # noqa: F811 — remplace la vraie lecture disque
        return list(self._pdf)


class FausseLigne:
    """La ligne de couche reduite au menu POSITION."""

    _find_main_window     = None          # injecte par le test
    _position_presets     = LayerRow._position_presets
    _pdf_position_presets = LayerRow._pdf_position_presets
    _set_pos_from_pdf     = LayerRow._set_pos_from_pdf

    def __init__(self, mw):
        self._mw = mw
        self.poses = []
        self._find_main_window = lambda: mw

    def _set_pos(self, idx, nom):
        self.poses.append((idx, nom))


class TestConversionPlanDeFeuVersAkai(unittest.TestCase):

    def test_position_inconnue_est_ajoutee(self):
        mw = FauxMW()
        idx = mw.pdf_position_to_akai_index(
            pdf_preset("Public", {1: (1000, 2000), 21: (3000, 4000)}))
        self.assertEqual(idx, 0)
        self.assertEqual(mw.position_presets[0]["name"], "Public")
        self.assertEqual(mw.sauvegardes, 1)

    def test_les_deux_lyres_sont_reprises(self):
        mw = FauxMW()
        mw.pdf_position_to_akai_index(
            pdf_preset("Public", {1: (1000, 2000), 21: (3000, 4000)}))
        snap = mw.position_presets[0]["projectors"]
        self.assertEqual([(p["pan"], p["tilt"]) for p in snap],
                         [(1000, 2000), (3000, 4000)])

    def test_copie_existante_rafraichie_et_non_dupliquee(self):
        """Le plan de feu fait foi pour un nom donne : une copie qui date est
        remplacee, pas doublee."""
        mw = FauxMW(akai=[{"name": "Public", "projectors": [{"pan": 0, "tilt": 0}]}])
        idx = mw.pdf_position_to_akai_index(
            pdf_preset("Public", {1: (1000, 2000), 21: (3000, 4000)}))
        self.assertEqual(idx, 0)
        self.assertEqual(len(mw.position_presets), 1)
        self.assertEqual(mw.position_presets[0]["projectors"][0]["pan"], 1000)

    def test_lyre_ajoutee_au_rig_depuis(self):
        """Le cas qui avait motive le rafraichissement : une 3e lyre patchee
        apres coup doit apparaitre dans la copie."""
        mw = FauxMW(akai=[{"name": "Public", "projectors": []}],
                    lyres=[FausseLyre("Lyre 1", 1), FausseLyre("Lyre 2", 21),
                           FausseLyre("Lyre 3", 41)])
        mw.pdf_position_to_akai_index(
            pdf_preset("Public", {1: (1000, 2000), 21: (3000, 4000),
                                    41: (5000, 6000)}))
        self.assertEqual(len(mw.position_presets[0]["projectors"]), 3)

    def test_lyre_absente_du_preset_retombe_sur_le_global(self):
        mw = FauxMW()
        mw.pdf_position_to_akai_index(pdf_preset("Public", {1: (1000, 2000)}))
        snap = mw.position_presets[0]["projectors"]
        self.assertEqual((snap[1]["pan"], snap[1]["tilt"]), (32768, 32768))

    def test_preset_vide_rend_none(self):
        mw = FauxMW()
        self.assertIsNone(mw.pdf_position_to_akai_index(None))
        self.assertEqual(mw.sauvegardes, 0)


class TestMenuPosition(unittest.TestCase):

    def test_les_positions_du_plan_de_feu_sont_listees(self):
        """Le bug rapporte : la position creee juste avant sur le plan 2D."""
        mw = FauxMW(akai=[{"name": "Centre", "projectors": []}],
                    pdf=[pdf_preset("Ma nouvelle pos", {1: (900, 800)})])
        ligne = FausseLigne(mw)
        noms_akai = {p["name"] for p in ligne._position_presets()}
        self.assertEqual(noms_akai, {"Centre"})
        depuis_pdf = ligne._pdf_position_presets(mw, noms_akai)
        self.assertEqual([p["name"] for p in depuis_pdf], ["Ma nouvelle pos"])

    def test_pas_de_doublon_quand_les_deux_ont_le_nom(self):
        """Rapprochement par NOM : la copie AKAI est affichee, celle du plan de
        feu est masquee."""
        mw = FauxMW(akai=[{"name": "Public", "projectors": []}],
                    pdf=[pdf_preset("Public", {1: (900, 800)}),
                         pdf_preset("Sol",    {1: (100, 200)})])
        ligne = FausseLigne(mw)
        noms = {p["name"] for p in ligne._position_presets()}
        self.assertEqual([p["name"] for p in ligne._pdf_position_presets(mw, noms)],
                         ["Sol"])

    def test_ouvrir_le_menu_ne_recopie_rien(self):
        """Convertir a l'AFFICHAGE gonflerait la config AKAI de tous les presets
        du plan de feu a chaque ouverture du menu."""
        mw = FauxMW(pdf=[pdf_preset("A", {1: (1, 2)}),
                         pdf_preset("B", {1: (3, 4)})])
        ligne = FausseLigne(mw)
        ligne._pdf_position_presets(mw, set())
        self.assertEqual(mw.position_presets, [])
        self.assertEqual(mw.sauvegardes, 0)

    def test_choisir_une_position_du_plan_de_feu(self):
        """La couche vise un INDEX dans position_presets : la copie doit etre
        fabriquee au moment du choix."""
        mw = FauxMW(akai=[{"name": "Centre", "projectors": []}],
                    pdf=[pdf_preset("Ma nouvelle pos", {1: (900, 800)})])
        ligne = FausseLigne(mw)
        ligne._set_pos_from_pdf(mw._pdf[0])
        self.assertEqual(ligne.poses, [(1, "Ma nouvelle pos")])
        self.assertEqual(mw.position_presets[1]["name"], "Ma nouvelle pos")

    def test_position_retrouvable_apres_choix(self):
        """`_refresh_pos_btn` et le moteur cherchent par (index, nom) : les deux
        doivent concorder, sinon le bouton affiche « ⚠ »."""
        from core import find_position_preset
        mw = FauxMW(pdf=[pdf_preset("Ma nouvelle pos", {1: (900, 800)})])
        ligne = FausseLigne(mw)
        ligne._set_pos_from_pdf(mw._pdf[0])
        idx, nom = ligne.poses[0]
        self.assertIsNotNone(
            find_position_preset(mw.position_presets, idx, nom))

    def test_sans_fenetre_principale(self):
        ligne = FausseLigne(None)
        self.assertEqual(ligne._position_presets(), [])
        self.assertEqual(ligne._pdf_position_presets(None, set()), [])
        ligne._set_pos_from_pdf(pdf_preset("X"))
        self.assertEqual(ligne.poses, [])


class TestTraductions(unittest.TestCase):

    def test_cle_du_titre_de_section(self):
        from i18n import TRANSLATIONS
        self.assertIn("fx_pos_from_pdf", TRANSLATIONS)
        for lang in ("en", "fr", "es", "de", "pt"):
            self.assertTrue(TRANSLATIONS["fx_pos_from_pdf"].get(lang), lang)


if __name__ == "__main__":
    unittest.main(verbosity=2)
