"""
test_canal_preset.py — Le canal « Preset », et la section qui va avec.

MyStrow n'offrait des presets nommes que sur DEUX types de canaux, `Gobo1` et
`ColorWheel`, et tous deux ont une signification VISUELLE. Qui voulait des
presets sur un canal de programme (« Auto 1 », « Sound active ») declarait donc
son canal en « Gobo » puis le renommait — et son PAR LED se couvrait de motifs
de gobo dans les plans 2D et 3D.

Ce qui est verrouille ici :

  * quatre canaux `Preset1..4` et NON un seul : les canaux de meme type sont
    ganges, un « Preset » unique redonnerait la meme valeur a tous les canaux
    de programme d'un laser (le piege du « Mode fourre-tout ») ;
  * un canal de preset sort sa valeur, independamment de ses voisins ;
  * 0 au repos — un canal de macro ne doit JAMAIS prendre une valeur tout seul,
    sinon l'appareil lance un programme que personne n'a demande ;
  * la section « PRESETS » du clic droit s'affiche sur un PAR LED. C'est le
    coeur du sujet : la section roue/gobo, elle, est enfermee dans le bloc
    `if proj.fixture_type == "Moving Head"` et reste donc inatteignable sur les
    appareils qui ont justement des canaux de programme ;
  * un seul curseur par canal — pas de doublon avec « Canaux avances », sinon
    deux writers pour le meme canal DMX ;
  * le curseur ecrit l'ATTRIBUT dedie (`proj.preset1`), pas `channel_extras` ;
  * aucun effet sur le rendu : declarer un Preset ne fait pas projeter de gobo.

    python test_canal_preset.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (QApplication, QLabel, QWidgetAction, QSlider,
                               QPushButton)

_app = QApplication.instance() or QApplication(sys.argv)

import plan_de_feu
from plan_de_feu import PlanDeFeu
from projector import Projector
from artnet_dmx import ArtNetDMX, PRESET_TYPES
from core import fixture_projects_gobo


# Le PAR LED du client : RGB + dimmer, et DEUX canaux de programme distincts
# (le programme lui-meme et sa vitesse) — c'est ce qui exige plus d'un type.
PAR_CLIENT = ["R", "G", "B", "Dim", "Preset1", "Preset2"]


def _walk(menu):
    """Le menu, a plat : ('label', titre) et ('row', etiquette, curseur)."""
    out = []
    for act in menu.actions():
        if not isinstance(act, QWidgetAction):
            continue
        w = act.defaultWidget()
        if w is None:
            continue
        if isinstance(w, QLabel):
            out.append(("label", w.text()))
            continue
        if isinstance(w, QPushButton) and w.text().startswith(("▸", "▾")):
            txt = w.text().lstrip("▸▾ ").split("·")[0].strip()
            out.append(("label", txt))
            continue
        lbls = w.findChildren(QLabel)
        slis = w.findChildren(QSlider)
        if lbls and slis:
            out.append(("row", lbls[0].text(), slis[0]))
    return out


class _MenuHarness(unittest.TestCase):
    """Ouvre le menu contextuel sans le rendre modal."""

    PROFILE = PAR_CLIENT
    FTYPE   = "PAR LED"
    LABELS  = None

    def setUp(self):
        self.proj = Projector("face", "PAR client", self.FTYPE)
        self.proj.dmx_profile = list(self.PROFILE)
        self.proj.channel_labels = list(
            self.LABELS or [f"CH{n}" for n in range(1, len(self.PROFILE) + 1)])
        self.pdf = PlanDeFeu([self.proj], main_window=None, show_toolbar=False)

        self.menu = None
        _vrai_exec = plan_de_feu._PersistentMenu.exec

        def _capture(menu_self, *a, **k):
            self.menu = menu_self
            return None

        plan_de_feu._PersistentMenu.exec = _capture
        self.addCleanup(setattr, plan_de_feu._PersistentMenu, "exec", _vrai_exec)

    def _items(self):
        self.pdf._show_fixture_context_menu(QPoint(0, 0), 0)
        self.assertIsNotNone(self.menu, "le menu contextuel ne s'est pas construit")
        return _walk(self.menu)


class TestSectionPresetSurParLed(_MenuHarness):
    """La section doit exister LA OU sont les canaux de programme."""

    def test_la_section_presets_apparait_sur_un_par_led(self):
        items = self._items()
        self.assertIn(("label", "PRESETS"), items,
                      "la section PRESETS manque sur un PAR LED — c'est tout "
                      "l'objet du canal : elle ne doit PAS etre enfermee dans "
                      "le bloc Moving Head comme l'est la roue de couleurs")

    def test_un_curseur_par_canal_de_preset(self):
        rows = [it for it in self._items() if it[0] == "row"]
        # Les libelles constructeur sont « CH5 » / « CH6 » pour ce profil.
        noms = [r[1] for r in rows]
        self.assertIn("CH5", noms, f"pas de curseur pour Preset1 (vus : {noms})")
        self.assertIn("CH6", noms, f"pas de curseur pour Preset2 (vus : {noms})")

    def test_pas_de_doublon_avec_canaux_avances(self):
        """Deux curseurs sur le meme canal = deux writers, donc derive."""
        rows = [it for it in self._items() if it[0] == "row"]
        for nom in ("CH5", "CH6"):
            n = sum(1 for r in rows if r[1] == nom)
            self.assertEqual(n, 1, f"{n} curseurs pour le canal {nom}, attendu 1")

    def test_le_curseur_ecrit_l_attribut_dedie(self):
        rows = {r[1]: r[2] for r in self._items() if r[0] == "row"}
        rows["CH5"].setValue(137)
        self.assertEqual(self.proj.preset1, 137,
                         "le curseur doit ecrire proj.preset1")
        self.assertEqual(getattr(self.proj, 'channel_extras', {}), {},
                         "il ne doit PAS passer par channel_extras : le canal a "
                         "un etat dedie, sinon deux chemins ecrivent le canal")

    def _blocs(self, w):
        """Boutons de bloc d'une section (le bouton « Éditer » n'en est pas)."""
        return [b for b in w.findChildren(QPushButton)
                if b.property("pst_val") is not None]

    def test_cliquer_un_bloc_deplace_le_curseur(self):
        """Le menu doit montrer ce que la fixture reçoit, pas autre chose."""
        self.proj.preset_slots = {
            "Preset1": [{"name": "Programme 1", "dmx": 137},
                        {"name": "Programme 2", "dmx": 200}],
        }
        self.pdf._show_fixture_context_menu(QPoint(0, 0), 0)
        sli = {r[1]: r[2] for r in _walk(self.menu) if r[0] == "row"}["CH5"]

        blocs = []
        for act in self.menu.actions():
            if isinstance(act, QWidgetAction) and act.defaultWidget() is not None:
                blocs += self._blocs(act.defaultWidget())
        self.assertEqual(len(blocs), 2, f"2 blocs attendus, vus {len(blocs)}")

        blocs[0].click()
        self.assertEqual(self.proj.preset1, 137, "le bloc n'a pas ecrit la valeur")
        self.assertEqual(sli.value(), 137,
                         "le curseur doit suivre le bloc cliqué — sinon le menu "
                         "affiche une valeur, la fixture en reçoit une autre")

        blocs[1].click()
        self.assertEqual(self.proj.preset1, 200)
        self.assertEqual(sli.value(), 200, "curseur desynchronisé au 2e bloc")

    def test_le_bloc_atteint_s_allume_en_tirant_le_curseur(self):
        self.proj.preset_slots = {
            "Preset1": [{"name": "Programme 1", "dmx": 137}],
        }
        self.pdf._show_fixture_context_menu(QPoint(0, 0), 0)
        items = _walk(self.menu)
        sli = {r[1]: r[2] for r in items if r[0] == "row"}["CH5"]
        blocs = []
        for act in self.menu.actions():
            if isinstance(act, QWidgetAction) and act.defaultWidget() is not None:
                blocs += self._blocs(act.defaultWidget())

        sli.setValue(137)
        self.assertIn("#00cc99", blocs[0].styleSheet().lower(),
                      "atteindre la valeur d'un bloc au curseur doit l'allumer")
        sli.setValue(20)
        self.assertNotIn("#00cc99", blocs[0].styleSheet().lower(),
                         "le bloc doit s'eteindre quand on quitte sa valeur")

    def test_pas_de_section_sans_canal_de_preset(self):
        self.proj.dmx_profile = ["R", "G", "B", "Dim"]
        self.proj.channel_labels = ["R", "G", "B", "Dim"]
        items = self._items()
        self.assertNotIn(("label", "PRESETS"), items,
                         "section PRESETS affichee sans aucun canal de preset")


class TestNomConstructeur(_MenuHarness):
    """Sur plusieurs canaux de programme, « Preset 2 » ne dit pas lequel."""

    LABELS = ["Rouge", "Vert", "Bleu", "Dimmer", "Programme", "Vitesse prog"]

    def test_l_etiquette_reprend_le_nom_constructeur(self):
        noms = [r[1] for r in self._items() if r[0] == "row"]
        self.assertIn("Programme", noms, f"vus : {noms}")
        self.assertIn("Vitesse prog", noms, f"vus : {noms}")


class TestLibellesDesalignes(_MenuHarness):
    """Une liste de libelles mal alignee designe le MAUVAIS canal."""

    LABELS = ["Rouge", "Vert"]          # 2 libelles pour 6 canaux

    def test_repli_sur_preset_n_si_libelles_desalignes(self):
        noms = [r[1] for r in self._items() if r[0] == "row"]
        self.assertIn("Preset 1", noms,
                      "libelles desalignes : il faut retomber sur « Preset N » "
                      f"plutot que de nommer un canal au hasard (vus : {noms})")


class TestSortieDMX(unittest.TestCase):
    """Ce que la fixture recoit reellement."""

    def setUp(self):
        from PySide6.QtGui import QColor
        self.p = Projector("face", "PAR client", "PAR LED")
        self.p.dmx_profile = list(PAR_CLIENT)
        self.p.level = 100
        self.p.base_color = QColor(255, 0, 0)
        self.p.color      = QColor(255, 0, 0)
        self.dmx = ArtNetDMX()
        self.dmx.set_projector_patch("face_0", list(range(1, 7)), 0, PAR_CLIENT)

    def _trame(self):
        self.dmx.update_from_projectors([self.p])
        return [self.dmx.get_channel(i) for i in range(1, 7)]

    def test_zero_au_repos(self):
        self.assertEqual(self._trame()[4:], [0, 0],
                         "un canal de macro qui prend une valeur tout seul "
                         "lance un programme que personne n'a demande")

    def test_les_canaux_ne_sont_pas_ganges(self):
        self.p.preset1, self.p.preset2 = 137, 42
        self.assertEqual(self._trame()[4:], [137, 42],
                         "les deux canaux de programme doivent etre "
                         "independants — c'est la raison d'etre des 4 types")

    def test_aucun_effet_sur_le_rendu(self):
        self.p.preset1 = 200
        self.assertFalse(fixture_projects_gobo(self.p),
                         "un canal de preset ne doit rien faire projeter")


class TestBlocsEtCurseurSurLyre(unittest.TestCase):
    """Le meme defaut existait sur le gobo et la roue : le clic sur un bloc
    ecrivait la lyre sans deplacer le curseur — le menu affichait une valeur,
    la fixture en recevait une autre."""

    def setUp(self):
        self.lyre = Projector("contre", "Spot", "Moving Head")
        self.lyre.dmx_profile = ["Pan", "Tilt", "Dim", "Gobo1", "ColorWheel"]
        self.lyre.channel_labels = ["Pan", "Tilt", "Dim", "Gobo", "Roue"]
        self.pdf = PlanDeFeu([self.lyre], main_window=None, show_toolbar=False)
        self.menu = None
        _vrai = plan_de_feu._PersistentMenu.exec
        plan_de_feu._PersistentMenu.exec = (
            lambda s, *a, **k: setattr(self, "menu", s))
        self.addCleanup(setattr, plan_de_feu._PersistentMenu, "exec", _vrai)
        self.pdf._show_fixture_context_menu(QPoint(0, 0), 0)

    def _widgets(self):
        rows, btns = {}, []
        for act in self.menu.actions():
            if not isinstance(act, QWidgetAction):
                continue
            w = act.defaultWidget()
            if w is None:
                continue
            ls, ss = w.findChildren(QLabel), w.findChildren(QSlider)
            if ls and ss:
                rows[ls[0].text()] = ss[0]
            btns += [b for b in w.findChildren(QPushButton)
                     if b.property("gobo_val") is not None]
        return rows, btns

    def test_le_curseur_gobo_suit_le_bloc_clique(self):
        rows, btns = self._widgets()
        self.assertIn("Gobo", rows, f"pas de ligne Gobo (vues : {list(rows)})")
        self.assertTrue(btns, "aucun bouton de gobo")
        cible = btns[2]
        val = cible.property("gobo_val")
        cible.click()
        self.assertEqual(self.lyre.gobo, val)
        self.assertEqual(rows["Gobo"].value(), val,
                         "le curseur Gobo doit suivre le bloc cliqué")

    def test_le_gobo_atteint_s_allume_en_tirant_le_curseur(self):
        """Un gobo occupe une PLAGE : au milieu, c'est lui qui tourne."""
        rows, btns = self._widgets()
        vals = sorted(b.property("gobo_val") for b in btns)
        # Entre le 2e et le 3e bloc : c'est le 2e qui doit etre allume.
        milieu = vals[1] + (vals[2] - vals[1]) // 2
        rows["Gobo"].setValue(milieu)
        allumes = [b.property("gobo_val") for b in btns
                   if "#00d4ff" in b.styleSheet().lower()]
        self.assertEqual(allumes, [vals[1]],
                         f"a DMX {milieu}, le bloc {vals[1]} doit etre allume "
                         f"(allumes : {allumes})")

    def test_rien_d_allume_en_deca_du_premier_bloc(self):
        rows, btns = self._widgets()
        vals = sorted(b.property("gobo_val") for b in btns)
        if vals[0] == 0:
            self.skipTest("le premier bloc est a 0, pas de « en deca »")
        rows["Gobo"].setValue(vals[0] - 1)
        allumes = [b.property("gobo_val") for b in btns
                   if "#00d4ff" in b.styleSheet().lower()]
        self.assertEqual(allumes, [], "annonce un programme non atteint")


class TestVocabulaire(unittest.TestCase):
    """Les listes de types de canaux derivent — cf. l'audit du projet."""

    def test_les_quatre_listes_sont_alignees(self):
        from artnet_dmx import CHANNEL_TYPES, CHANNEL_DISPLAY, _MANUAL_ONLY
        from fixture_editor import ALL_CHANNEL_TYPES, CHANNEL_COLORS
        for t in PRESET_TYPES:
            self.assertIn(t, CHANNEL_TYPES)
            self.assertIn(t, CHANNEL_DISPLAY)
            self.assertIn(t, ALL_CHANNEL_TYPES)
            self.assertIn(t, CHANNEL_COLORS)
            self.assertIn(t, plan_de_feu._CANAL_ATTR_SIMPLE)
            self.assertNotIn(t, _MANUAL_ONLY,
                             f"{t} a un etat dedie : le mettre dans "
                             "_MANUAL_ONLY le sortirait toujours a 0")

    def test_la_vue_curseurs_ecrit_le_meme_attribut(self):
        """Un seul writer : la vue Curseurs et la section Presets s'accordent."""
        for t in PRESET_TYPES:
            self.assertEqual(plan_de_feu._CANAL_ATTR_SIMPLE[t],
                             f"preset{t[-1]}")


class TestMemoiresEtRepos(unittest.TestCase):
    """Une memoire qui perd le preset rappelle un look incomplet."""

    def test_captures_dans_le_snapshot(self):
        import inspect
        from main_window import MainWindow
        src = inspect.getsource(MainWindow._build_snapshot)
        for i in (1, 2, 3, 4):
            self.assertIn(f'"preset{i}"', src,
                          f"preset{i} absent de _build_snapshot")

    def test_ramenes_au_repos_en_fin_de_bloc(self):
        from light_timeline import _REPOS_FAISCEAU, reset_beam_channels
        p = Projector("face", "PAR", "PAR LED")
        p.preset1, p.preset2 = 137, 42
        for i in (1, 2, 3, 4):
            self.assertIn(f"preset{i}", _REPOS_FAISCEAU)
        reset_beam_channels([p])
        self.assertEqual((p.preset1, p.preset2), (0, 0),
                         "un programme laisse colle tourne par-dessus la suite "
                         "du show")

    def test_partages_avec_la_fixture(self):
        from fixture_share import _PAYLOAD_FIELDS
        self.assertIn("preset_slots", _PAYLOAD_FIELDS,
                      "sans les blocs, celui qui recoit la fixture retrouve un "
                      "canal nu et doit tout recalibrer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
