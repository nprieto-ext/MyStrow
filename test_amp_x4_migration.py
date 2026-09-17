"""
test_amp_x4_migration.py — Outil « Amplitudes 3.1.91 » (amp_migration.py).

Contexte (17/09/2026) : un client a réglé beaucoup d'effets sous la 3.1.91
(AMP 100 = ±32768). Depuis la 3.1.92 (±8192) ils bougent 4 fois moins, et il
devait repasser chaque AMP de 70 à 280 à la main, dans l'éditeur ET dans chaque
clip des REC Lumière. L'outil fait la conversion par NOM d'effet, partout.

Ce que ces tests verrouillent :
  1. seules les couches Pan / Tilt / Pan-Tilt entre 1 et 100 sont converties,
     plafond 400, et seulement pour les effets cochés ;
  2. jamais deux fois : marque `amp_x4`, qui survit à EffectLayer (éditeur) ;
  3. jamais × 16 : une liste de couches PARTAGÉE entre deux entrepôts (mémoire
     copiée d'un bouton, bouton pointant sur BUILTIN_EFFECTS) est remplacée par
     des copies, pas modifiée sur place ;
  4. les clips de REC Lumière (`effect_layers` / `effect_name`) sont convertis ;
  5. un fichier n'est réécrit que s'il change, avec une copie de l'original
     qui n'est jamais écrasée par une seconde passe.
"""

import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import amp_migration as am
from effect_editor import EffectLayer

_app = QApplication.instance() or QApplication(sys.argv)


def _c(attr, size, **extra):
    d = {"attribute": attr, "forme": "Sinus", "size": size}
    d.update(extra)
    return d


class TestConversion(unittest.TestCase):

    def test_seules_les_couches_de_mouvement_sont_multipliees(self):
        cfg = {"name": "Vague", "layers": [
            _c("Pan", 70), _c("Tilt", 25), _c("Pan/Tilt", 100),
            _c("Dimmer", 80), _c("Pan", 280), _c("Tilt", 0)]}
        n = am.convertir(cfg, ["Vague"])
        tailles = [c["size"] for c in cfg["layers"]]
        self.assertEqual(tailles, [280, 100, 400, 80, 280, 0])
        self.assertEqual(n, 3)
        self.assertTrue(cfg["layers"][0].get("amp_x4"))
        self.assertNotIn("amp_x4", cfg["layers"][3])   # Dimmer
        self.assertNotIn("amp_x4", cfg["layers"][4])   # déjà > 100

    def test_effet_non_coche_intact(self):
        cfg = {"name": "Ancien", "layers": [_c("Pan", 70)]}
        self.assertEqual(am.convertir(cfg, ["Vague"]), 0)
        self.assertEqual(cfg["layers"][0]["size"], 70)

    def test_cle_amplitude_historique(self):
        cfg = {"name": "Vieux", "layers": [{"attribute": "Tilt", "amplitude": 50}]}
        am.convertir(cfg, ["Vieux"])
        self.assertEqual(cfg["layers"][0]["size"], 200)
        self.assertNotIn("amplitude", cfg["layers"][0])

    def test_deux_passes_ne_multiplient_pas_deux_fois(self):
        cfg = {"name": "Vague", "layers": [_c("Pan", 20)]}
        am.convertir(cfg, ["Vague"])
        self.assertEqual(am.convertir(cfg, ["Vague"]), 0)
        self.assertEqual(cfg["layers"][0]["size"], 80)

    def test_marque_survit_a_l_editeur(self):
        cfg = {"name": "Vague", "layers": [_c("Pan", 20)]}
        am.convertir(cfg, ["Vague"])
        # L'éditeur relit puis réécrit les couches à la fermeture.
        cfg["layers"] = [EffectLayer.from_dict(d).to_dict() for d in cfg["layers"]]
        self.assertTrue(cfg["layers"][0].get("amp_x4"))
        self.assertEqual(am.convertir(cfg, ["Vague"]), 0)
        self.assertEqual(cfg["layers"][0]["size"], 80)

    def test_couche_neuve_sans_marque_dans_le_json(self):
        # Pas de clé ajoutée partout : seules les couches converties la portent.
        self.assertNotIn("amp_x4", EffectLayer().to_dict())

    def test_liste_partagee_convertie_une_fois_par_entrepot(self):
        partagees = [_c("Pan", 70)]
        bouton  = {"name": "Vague", "layers": partagees}
        memoire = {"effect": dict(bouton)}          # comme _assign_effect_to_memory
        racine  = {"boutons": {0: bouton}, "memories": [[memoire]]}
        am.convertir(racine, ["Vague"])
        self.assertEqual(bouton["layers"][0]["size"], 280)
        self.assertEqual(memoire["effect"]["layers"][0]["size"], 280)
        # La liste d'origine (qui peut être celle de BUILTIN_EFFECTS) est intacte.
        self.assertEqual(partagees[0]["size"], 70)
        self.assertNotIn("amp_x4", partagees[0])

    def test_meme_config_referencee_deux_fois(self):
        cfg = {"name": "Vague", "layers": [_c("Pan", 70)]}
        racine = {"fx_pads": [[cfg]], "active": cfg}
        self.assertEqual(am.convertir(racine, ["Vague"]), 1)
        self.assertEqual(cfg["layers"][0]["size"], 280)

    def test_clips_rec_lumiere(self):
        tui = {"sequence": [{"type": "media", "sequence": {"duration": 1000, "clips": [
            {"effect_name": "Vague", "effect_layers": [_c("Tilt", 70)]},
            {"effect_name": "Autre", "effect_layers": [_c("Tilt", 70)]},
            {"effect_name": "", "effect_layers": []},
        ]}}]}
        self.assertEqual(am.convertir(tui, ["Vague"]), 1)
        clips = tui["sequence"][0]["sequence"]["clips"]
        self.assertEqual(clips[0]["effect_layers"][0]["size"], 280)
        self.assertEqual(clips[1]["effect_layers"][0]["size"], 70)

    def test_recenser(self):
        partagees = [_c("Pan", 70), _c("Tilt", 50)]
        racines = [
            {0: {"name": "Vague", "layers": partagees}},
            [{"effect_name": "Vague", "effect_layers": partagees},     # même liste
             {"effect_name": "Vague", "effect_layers": [_c("Pan", 30)]},
             {"effect_name": "Fait", "effect_layers": [_c("Pan", 280)]},
             {"name": "Flash", "layers": [_c("Dimmer", 50)]}],
        ]
        bilan = am.recenser(racines)
        self.assertEqual(set(bilan), {"Vague"})
        self.assertEqual(bilan["Vague"]["amps"], {30, 50, 70})
        self.assertEqual(bilan["Vague"]["n"], 2)


class TestFichiers(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _ecrire(self, nom, data):
        chemin = os.path.join(self.dossier, nom)
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return chemin

    def test_fichier_converti_avec_copie_de_l_original(self):
        show = {"fx_pads": [[{"name": "Été", "layers": [_c("Pan", 70)]}]]}
        chemin = self._ecrire("show.tui", show)
        self.assertEqual(am.convertir_fichier(chemin, ["Été"]), 1)
        self.assertEqual(am.lire_json(chemin)["fx_pads"][0][0]["layers"][0]["size"], 280)
        copie = chemin + am.SUFFIXE_SAUVEGARDE
        self.assertEqual(am.lire_json(copie)["fx_pads"][0][0]["layers"][0]["size"], 70)
        # .tui en ASCII échappé, comme save_show : relu sans encodage explicite.
        with open(chemin, "rb") as f:
            f.read().decode("ascii")

    def test_seconde_passe_n_ecrase_pas_la_copie(self):
        chemin = self._ecrire("rec.lrec", {"clips": [
            {"effect_name": "A", "effect_layers": [_c("Pan", 70)]},
            {"effect_name": "B", "effect_layers": [_c("Pan", 10)]}]})
        am.convertir_fichier(chemin, ["A"])
        am.convertir_fichier(chemin, ["B"])
        copie = am.lire_json(chemin + am.SUFFIXE_SAUVEGARDE)
        self.assertEqual([c["effect_layers"][0]["size"] for c in copie["clips"]], [70, 10])
        self.assertEqual([c["effect_layers"][0]["size"]
                          for c in am.lire_json(chemin)["clips"]], [280, 40])

    def test_fichier_sans_changement_non_reecrit(self):
        chemin = self._ecrire("show.tui", {"fx_pads": []})
        self.assertEqual(am.convertir_fichier(chemin, ["A"]), 0)
        self.assertFalse(os.path.exists(chemin + am.SUFFIXE_SAUVEGARDE))

    def test_chercher_shows(self):
        os.makedirs(os.path.join(self.dossier, "sous"))
        self._ecrire("a.tui", {})
        self._ecrire(os.path.join("sous", "b.lrec"), {})
        self._ecrire("c.json", {})
        trouves = [os.path.basename(p) for p in am.chercher_shows(self.dossier)]
        self.assertEqual(sorted(trouves), ["a.tui", "b.lrec"])


class _Seq:
    def __init__(self):
        self.sequences = {0: {"duration": 1, "clips": [
            {"effect_name": "Vague", "effect_layers": [_c("Pan", 70)]}]}}
        self.is_dirty = False


class _FausseFenetre:
    """Le strict nécessaire de MainWindow pour la fenêtre de l'outil."""
    def __init__(self):
        cfg = {"name": "Vague", "layers": [_c("Pan", 70), _c("Dimmer", 60)]}
        self._button_effect_configs = {0: cfg}
        self._effect_library_configs = {"Ancien": {"name": "Ancien", "layers": [_c("Tilt", 40)]}}
        self.fx_pads = [[None] * 8]
        self.memories = [[{"effect": dict(cfg)}] + [None] * 7]
        self.active_effect_config = cfg
        self.seq = _Seq()
        self.current_show_path = None
        self.sauvegardes = []

    def _save_effect_assignments(self): self.sauvegardes.append("boutons")
    def _save_effect_library(self):     self.sauvegardes.append("biblio")
    def _save_akai_config_auto(self):   self.sauvegardes.append("akai")


class TestFenetre(unittest.TestCase):

    def test_conversion_depuis_la_fenetre(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox, QWidget
        import effect_editor

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        custom = os.path.join(tmp.name, "custom.json")
        with open(custom, "w", encoding="utf-8") as f:
            json.dump([{"name": "Vague", "layers": [_c("Pan", 70)]}], f)

        anciens = (effect_editor._CUSTOM_EFFECTS_FILE, QMessageBox.question,
                   QMessageBox.information, os.path.expanduser)
        effect_editor._CUSTOM_EFFECTS_FILE = custom
        QMessageBox.question    = staticmethod(lambda *a, **k: QMessageBox.Yes)
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        os.path.expanduser = lambda p: tmp.name if p == "~" else p

        def _restaurer():
            (effect_editor._CUSTOM_EFFECTS_FILE, QMessageBox.question,
             QMessageBox.information, os.path.expanduser) = anciens
        self.addCleanup(_restaurer)

        fenetre = _FausseFenetre()
        dlg = am.AmpX4Dialog.__new__(am.AmpX4Dialog)
        # Parent Qt réel exigé par QDialog : la fausse fenêtre n'en est pas un.
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        am.AmpX4Dialog.__init__(dlg, parent)
        dlg._mw = fenetre
        dlg._recenser()

        noms = {dlg._liste_effets.item(i).data(Qt.UserRole): dlg._liste_effets.item(i)
                for i in range(dlg._liste_effets.count())}
        self.assertEqual(set(noms), {"Vague", "Ancien"})
        noms["Vague"].setCheckState(Qt.Checked)
        dlg._convertir()

        self.assertEqual(fenetre._button_effect_configs[0]["layers"][0]["size"], 280)
        self.assertEqual(fenetre._button_effect_configs[0]["layers"][1]["size"], 60)
        self.assertEqual(fenetre.memories[0][0]["effect"]["layers"][0]["size"], 280)
        self.assertEqual(fenetre.seq.sequences[0]["clips"][0]["effect_layers"][0]["size"], 280)
        self.assertEqual(fenetre._effect_library_configs["Ancien"]["layers"][0]["size"], 40)
        self.assertTrue(fenetre.seq.is_dirty)
        self.assertEqual(fenetre.sauvegardes, ["boutons", "biblio", "akai"])
        self.assertEqual(am.lire_json(custom)[0]["layers"][0]["size"], 280)
        # Relu : plus rien à proposer pour « Vague ».
        restants = {dlg._liste_effets.item(i).data(Qt.UserRole)
                    for i in range(dlg._liste_effets.count())}
        self.assertEqual(restants, {"Ancien"})


class TestDeclencheurCache(unittest.TestCase):
    """Ctrl + clic long sur le ⚙ AKAI ouvre l'outil — aucune entrée de menu."""

    def setUp(self):
        from PySide6.QtWidgets import QPushButton
        self.ancienne_duree = am.DUREE_CLIC_LONG_MS
        am.DUREE_CLIC_LONG_MS = 60
        self.addCleanup(setattr, am, "DUREE_CLIC_LONG_MS", self.ancienne_duree)
        self.bouton = QPushButton("⚙")
        self.bouton.resize(26, 26)
        self.bouton.show()
        self.addCleanup(self.bouton.deleteLater)
        self.actions, self.clics = [], []
        self.bouton.clicked.connect(lambda: self.clics.append(True))
        am.armer_declencheur_cache(self.bouton, lambda: self.actions.append(True))

    def _clic(self, ctrl, tenu_ms):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        mods = Qt.ControlModifier if ctrl else Qt.NoModifier
        QTest.mousePress(self.bouton, Qt.LeftButton, mods)
        QTest.qWait(tenu_ms)
        QTest.mouseRelease(self.bouton, Qt.LeftButton, mods)
        QTest.qWait(20)

    def test_ctrl_clic_long_ouvre_l_outil_sans_les_parametres(self):
        self._clic(ctrl=True, tenu_ms=200)
        self.assertEqual(len(self.actions), 1)
        self.assertEqual(self.clics, [])        # pas de paramètres AKAI derrière

    def test_ctrl_clic_court_reste_un_clic(self):
        self._clic(ctrl=True, tenu_ms=0)
        self.assertEqual(self.actions, [])
        self.assertEqual(len(self.clics), 1)

    def test_clic_long_sans_ctrl_reste_un_clic(self):
        self._clic(ctrl=False, tenu_ms=200)
        self.assertEqual(self.actions, [])
        self.assertEqual(len(self.clics), 1)

    def test_branche_sur_le_bouton_akai_et_pas_dans_le_menu(self):
        import inspect
        import main_window
        self.assertNotIn("_open_amp_x4_tool", inspect.getsource(main_window.MainWindow._create_menu))
        src = inspect.getsource(main_window)
        self.assertIn("armer_declencheur_cache(edit_layout_btn, self._open_amp_x4_tool)", src)


if __name__ == "__main__":
    unittest.main()
