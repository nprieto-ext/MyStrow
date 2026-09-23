"""
test_pad_flash_fader_zero.py — Option « pad couleur sur fader baissé = flash ».

Demandé le 22/09/2026 : quand le fader d'un groupe n'est pas levé, appuyer sur
un de ses pads couleur doit faire un flash. C'est une OPTION, désactivée par
défaut, parce qu'elle interdit de préparer une couleur à l'aveugle (fader en
bas, on choisit la couleur, puis on monte le fader).

Option active, fader < 5 % :
  * à l'appui   — le groupe monte à 100 % dans la couleur du pad (modèle ET
                  fil DMX), le fader n'est jamais déplacé ;
  * au relâché  — la colonne rend son état d'avant : niveau, couleurs, roue,
                  pad latché.
Fader levé pendant l'appui → le fader reprend la main et la couleur reste.
Fader muté → rien ne sort. Fader levé à l'appui → latch normal.

    python test_pad_flash_fader_zero.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor

import main_window as mw
from test_pads_couleur_momentanes import FauxWin as _FauxWinPads, BLANC, ROUGE


class FauxWin(_FauxWinPads):
    set_proj_level            = mw.MainWindow.set_proj_level
    _flash_level              = mw.MainWindow._flash_level
    _apply_pad_overrides_htp  = mw.MainWindow._apply_pad_overrides_htp
    _PAD_BUMP_THRESHOLD       = mw.MainWindow._PAD_BUMP_THRESHOLD
    _pad_bump_applies         = mw.MainWindow._pad_bump_applies
    _pad_bump_end             = mw.MainWindow._pad_bump_end
    _pad_bump_end_all         = mw.MainWindow._pad_bump_end_all

    def __init__(self, option=True):
        super().__init__()
        self.pad_bump_on_zero = option
        self._pad_bump_cols = {}
        self._muted_faders = set()


def _scene(option=True):
    """Colonnes A B C montées en BLANC ; colonne D (3) fader à ZÉRO, pad BLANC latché."""
    w = FauxWin(option)
    for c in range(4):
        w.activate_pad(w.pads[(BLANC, c)], c)
        w.set_proj_level(c, 100)
    w.faders[3].value = 0
    w.set_proj_level(3, 0)
    return w


def _rgb(c):
    return c.getRgb()[:3]


class TestFlashFaderZero(unittest.TestCase):

    def test_option_inactive_rien_ne_change(self):
        w = _scene(option=False)
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertEqual(w.projectors[3].level, 0, "sans l'option, fader baissé = noir")
        w._on_color_pad_released(3)
        self.assertEqual(_rgb(w.projectors[3].base_color), (255, 0, 0),
                         "sans l'option, la couleur se prépare à l'aveugle")
        self.assertIs(w.active_pads[3], w.pads[(ROUGE, 3)])

    def test_appui_allume_a_100_dans_la_couleur(self):
        w = _scene()
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        p = w.projectors[3]
        self.assertEqual(p.level, 100)
        self.assertEqual(_rgb(p.color), (255, 0, 0))
        self.assertEqual(w.faders[3].value, 0, "le fader ne doit jamais bouger")
        for i in range(3):
            self.assertEqual(_rgb(w.projectors[i].color), (255, 255, 255),
                             "le flash a débordé sur un autre groupe")

    def test_couche_dmx_par_frame_tient_le_flash(self):
        w = _scene()
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        # Un recalcul (mix mémoire…) remet le modèle à zéro : la couche HTP par
        # frame doit quand même sortir le flash.
        w.projectors[3].level = 0
        w.projectors[3].color = QColor("black")
        saved = w._apply_pad_overrides_htp()
        self.assertEqual(w.projectors[3].level, 100)
        self.assertEqual(_rgb(w.projectors[3].color), (255, 0, 0))
        self.assertTrue(any(i == 3 for i, *_ in saved))

    def test_relache_rend_l_etat_d_avant(self):
        w = _scene()
        p = w.projectors[3]
        p.color_wheel = 42
        avant = (p.level, _rgb(p.base_color), _rgb(p.color), p.color_wheel)
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w._on_color_pad_released(3)
        self.assertEqual((p.level, _rgb(p.base_color), _rgb(p.color), p.color_wheel), avant)
        self.assertIs(w.active_pads[3], w.pads[(BLANC, 3)], "le pad BLANC doit revenir")
        self.assertEqual(w._pad_bump_cols, {})
        w._apply_pad_overrides_htp()
        self.assertEqual(p.level, 0, "plus rien ne doit sortir après le relâché")

    def test_fader_bouge_pendant_l_appui_reste_a_100(self):
        w = _scene()
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w.faders[3].value = 2
        w.set_proj_level(3, 2)
        self.assertEqual(w.projectors[3].level, 100)

    def test_fader_leve_pendant_l_appui_garde_la_couleur(self):
        w = _scene()
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w.faders[3].value = 60
        w.set_proj_level(3, 60)
        w._on_color_pad_released(3)
        p = w.projectors[3]
        self.assertEqual(p.level, 60, "le fader reprend la main")
        self.assertEqual(_rgb(p.base_color), (255, 0, 0))
        self.assertIs(w.active_pads[3], w.pads[(ROUGE, 3)])

    def test_fader_leve_latch_normal(self):
        w = _scene()
        w._on_color_pad_pressed(w.pads[(ROUGE, 0)], 0)
        w._on_color_pad_released(0)
        self.assertEqual(_rgb(w.projectors[0].base_color), (255, 0, 0))
        self.assertIs(w.active_pads[0], w.pads[(ROUGE, 0)])
        self.assertEqual(w._pad_bump_cols, {})

    def test_seuil_fader_presque_baisse(self):
        w = _scene()
        w.faders[3].value = 3
        self.assertTrue(w._pad_bump_applies(3))
        w.faders[3].value = 5
        self.assertFalse(w._pad_bump_applies(3))

    def test_fader_mute_reste_muet(self):
        w = _scene()
        w._muted_faders.add(3)
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertEqual(w.projectors[3].level, 0)
        self.assertEqual(w._pad_bump_cols, {})

    def test_sous_flash_tenu_le_bouton_garde_la_main(self):
        w = _scene()
        w._flash_kind = "full"
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertEqual(w._pad_bump_cols, {})
        self.assertIn(3, w._pad_flash_snaps)

    def test_end_all_rend_tout(self):
        w = _scene()
        w.faders[2].value = 0
        w.set_proj_level(2, 0)
        w._on_color_pad_pressed(w.pads[(ROUGE, 2)], 2)
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w._pad_bump_end_all()
        self.assertEqual(w._pad_bump_cols, {})
        self.assertEqual(w.projectors[2].level, 0)
        self.assertEqual(w.projectors[3].level, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
