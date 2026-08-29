"""
test_ext_flash_couleur.py — FLASH d'un pad couleur de la fenetre EXT.

Scenario reel (signale le 28/08/2026) : les groupes A B C D sont montes et
tiennent le BLANC (4 pads couleur allumes). Un pad ROUGE cible le seul groupe D
et il est en « mode flash (momentane) ».

Ce qui doit se passer, a l'appui puis au relache :

  * appui   — le rouge part sur D, le pad ROUGE s'allume, le pad BLANC de D
              s'eteint ; les pads BLANC de A, B et C ne bougent pas (leurs
              projecteurs non plus) ;
  * relache — D redevient EXACTEMENT ce qu'il etait : couleur, niveau, mais
              aussi les canaux hors RVB (UV, ambre, roue de couleurs) ; le pad
              BLANC de D se rallume et le pad ROUGE s'eteint.

Le retour « au bit pres » est le coeur du test : restaurer base_color/color/
level ne suffisait pas — clear_special_blocks avait eteint l'UV et la roue
restait sur le slot du flash, la lampe sortait encore rouge sur le fil DMX.

    python test_ext_flash_couleur.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main_window as mw
import ext_window as ew

_app = QApplication.instance() or QApplication(sys.argv)


class FauxProjecteur:
    def __init__(self, group, profile=("R", "G", "B", "UV")):
        self.group = group
        self.dmx_profile = list(profile)
        self.level = 0
        self.base_color = QColor("black")
        self.color = QColor("black")
        self.uv = 0
        self.white_boost = 0
        self.amber_boost = 0
        self.orange_boost = 0
        self.strobe_speed = 0
        self.color_wheel = 0
        self.color_wheel_slots = []


class FauxPlan:
    selected_lamps = []

    def refresh(self):
        pass


class FauxWin:
    """MainWindow reduite aux chemins couleur de la fenetre EXT."""

    _GENERIC_WHEEL_SLOTS    = mw.MainWindow._GENERIC_WHEEL_SLOTS
    _EXT_SNAP_CHANNELS      = mw.MainWindow._EXT_SNAP_CHANNELS
    _update_color_wheel     = mw.MainWindow._update_color_wheel
    _apply_color_to_groups  = mw.MainWindow._apply_color_to_groups
    _ext_targets_for_groups = mw.MainWindow._ext_targets_for_groups
    _ext_snapshot_groups    = mw.MainWindow._ext_snapshot_groups
    _ext_restore_snapshot   = mw.MainWindow._ext_restore_snapshot

    def __init__(self, projectors):
        self.projectors = projectors
        self.dmx = None
        self.plan_de_feu = FauxPlan()


class FauxBloc:
    """Bloc EXT reduit a ce dont le dispatch a besoin."""

    def __init__(self, label, rgb, groups, flash=False):
        self.spec = {"label": label, "color": "#ffffff", "flash": flash,
                     "action": {"type": "color", "rgb": list(rgb), "groups": groups}}
        self.active = False
        self._flash_snap = None
        self._flash_latches = None

    def _set_active(self, on):
        self.active = bool(on)


class FauxCanvas:
    def __init__(self, blocks):
        self.blocks = blocks


class FauxExt:
    """ExtWindow reduite au dispatch des blocs couleur."""

    _color_block_target    = ew.ExtWindow._color_block_target
    _color_targets_overlap = ew.ExtWindow._color_targets_overlap
    _color_latches_on      = ew.ExtWindow._color_latches_on
    _latch_color           = ew.ExtWindow._latch_color
    _dispatch_flash_on     = ew.ExtWindow._dispatch_flash_on
    _dispatch_flash_off    = ew.ExtWindow._dispatch_flash_off

    def __init__(self, owner, blocks):
        self._owner = owner
        self.canvas = FauxCanvas(blocks)
        self.statuts = []

    def _flash_status(self, txt):
        self.statuts.append(txt)


def _monter_scene():
    """4 groupes montes en blanc + les 4 pads BLANC allumes + 1 pad ROUGE flash."""
    projos = [FauxProjecteur(g) for g in ("face", "douche1", "douche2", "lat")]
    win = FauxWin(projos)
    blancs = {}
    for g in ("face", "douche1", "douche2", "lat"):
        b = FauxBloc("BLANC", (255, 255, 255), [g])
        b.active = True
        blancs[g] = b
    rouge = FauxBloc("ROUGE", (255, 0, 0), ["lat"], flash=True)
    ext = FauxExt(win, list(blancs.values()) + [rouge])
    for p in projos:
        win._apply_color_to_groups(QColor(255, 255, 255), [p.group])
    return win, ext, projos, blancs, rouge


class TestFlashCouleurExt(unittest.TestCase):

    def test_appui_envoie_le_rouge_sur_le_seul_groupe_cible(self):
        win, ext, projos, blancs, rouge = _monter_scene()
        ext._dispatch_flash_on(rouge.spec["action"], rouge)
        cible = projos[3]                      # groupe « lat »
        self.assertEqual(cible.color.getRgb()[:3], (255, 0, 0))
        for p in projos[:3]:
            self.assertEqual(p.color.getRgb()[:3], (255, 255, 255),
                             "le flash a deborde sur les autres groupes")

    def test_relache_rend_la_couleur_le_niveau_et_les_canaux_dedies(self):
        win, ext, projos, blancs, rouge = _monter_scene()
        cible = projos[3]
        cible.uv = 200                          # UV pose a la main avant le flash
        cible.level = 62
        cible.color_wheel = 17
        avant = (QColor(cible.color), QColor(cible.base_color), cible.level,
                 cible.uv, cible.color_wheel)

        ext._dispatch_flash_on(rouge.spec["action"], rouge)
        self.assertEqual(cible.uv, 0, "le flash aurait du couper l'UV pendant l'appui")

        ext._dispatch_flash_off(rouge.spec["action"], rouge)
        apres = (QColor(cible.color), QColor(cible.base_color), cible.level,
                 cible.uv, cible.color_wheel)
        self.assertEqual(avant[0].getRgb(), apres[0].getRgb())
        self.assertEqual(avant[1].getRgb(), apres[1].getRgb())
        self.assertEqual(avant[2:], apres[2:])

    def test_le_pad_blanc_du_groupe_flashe_s_eteint_puis_revient(self):
        win, ext, projos, blancs, rouge = _monter_scene()
        ext._dispatch_flash_on(rouge.spec["action"], rouge)
        self.assertTrue(rouge.active, "le pad ROUGE doit s'allumer pendant l'appui")
        self.assertFalse(blancs["lat"].active,
                         "le pad BLANC du groupe flashe doit s'eteindre")
        for g in ("face", "douche1", "douche2"):
            self.assertTrue(blancs[g].active,
                            "les pads BLANC des autres groupes ne bougent pas")

        ext._dispatch_flash_off(rouge.spec["action"], rouge)
        self.assertFalse(rouge.active, "le pad ROUGE doit se couper au relache")
        self.assertTrue(blancs["lat"].active,
                        "le pad BLANC doit se reactiver au relache")
        for g in ("face", "douche1", "douche2"):
            self.assertTrue(blancs[g].active)

    def test_le_flash_sur_tous_les_groupes_eteint_puis_rend_tous_les_pads(self):
        win, ext, projos, blancs, rouge = _monter_scene()
        rouge.spec["action"]["groups"] = "all"
        ext._dispatch_flash_on(rouge.spec["action"], rouge)
        self.assertFalse(any(b.active for b in blancs.values()))
        ext._dispatch_flash_off(rouge.spec["action"], rouge)
        self.assertTrue(all(b.active for b in blancs.values()))


class TestLatchParGroupe(unittest.TestCase):
    """Le latch normal (hors flash) est exclusif PAR GROUPE, pas globalement."""

    def test_deux_groupes_peuvent_rester_allumes_en_meme_temps(self):
        win, ext, projos, blancs, rouge = _monter_scene()
        for b in blancs.values():
            b.active = False
        ext._latch_color(blancs["face"])
        ext._latch_color(blancs["douche1"])
        self.assertTrue(blancs["face"].active,
                        "poser une couleur sur B ne doit pas eteindre le pad de A")
        self.assertTrue(blancs["douche1"].active)

    def test_deux_couleurs_sur_le_meme_groupe_restent_exclusives(self):
        win, ext, projos, blancs, rouge = _monter_scene()
        autre = FauxBloc("BLEU", (0, 60, 255), ["lat"])
        ext.canvas.blocks.append(autre)
        ext._latch_color(autre)
        self.assertTrue(autre.active)
        self.assertFalse(blancs["lat"].active,
                         "deux couleurs sur le meme groupe ne peuvent pas tenir ensemble")


if __name__ == "__main__":
    unittest.main(verbosity=2)
