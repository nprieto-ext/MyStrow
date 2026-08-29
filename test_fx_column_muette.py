"""
test_fx_column_muette.py — Une colonne de pads typee FX etait muette.

Le fader d'une colonne FX n'est pas un niveau de projecteur : c'est l'AMPLITUDE
de l'effet, et `update_effect` sort en tete quand elle vaut 0. Or deux remises a
zero le traitaient comme une colonne de groupe :

  * `_startup_faders_down()` — 650 ms apres le lancement, « pour que rien ne soit
    allume au demarrage » ;
  * `_clear_akai_state()` — le bouton CLEAR.

Resultat : le pad FX s'allumait, le timer d'effet tournait, mais plus rien
n'atteignait les projecteurs — ni sur le fil DMX, ni dans la 3D — jusqu'a ce que
l'utilisateur remonte lui-meme le fader. Et il n'y avait rien a eteindre en
echange : un effet ne tourne que si un pad l'arme.

    python test_fx_column_muette.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)


class FauxFader:
    def __init__(self, value=0):
        self.value = value

    def update(self):
        pass


class _TimerMuet:
    def stop(self):
        pass


class FauxWin:
    """MainWindow reduite aux trois methodes en jeu."""

    set_proj_level       = mw.MainWindow.set_proj_level
    _sync_fx_fader       = mw.MainWindow._sync_fx_fader
    _startup_faders_down = mw.MainWindow._startup_faders_down
    _clear_akai_state    = mw.MainWindow._clear_akai_state
    update_effect        = mw.MainWindow.update_effect
    _run_effect_frame    = mw.MainWindow._run_effect_frame
    _sync_effect_baseline = mw.MainWindow._sync_effect_baseline
    _record_effect_frame = mw.MainWindow._record_effect_frame
    _effect_state_tuple  = mw.MainWindow._effect_state_tuple
    _effect_state_key    = mw.MainWindow._effect_state_key

    def __init__(self):
        # Le layout de l'utilisateur : colonne 0 typee « FX 1 », le reste en groupes.
        self._fader_map = [{"type": "fx", "fx_col": 0, "label": "FX 1"}] + \
                          [{"type": "group", "group": g, "label": g} for g in "BCDEFGH"]
        self.faders = {i: FauxFader(0) for i in range(8)}
        self.fx_amplitudes = [100] * mw._FX_COL_MAX
        self.effect_amplitude = 100
        self.projectors = []
        self._muted_faders = set()
        self.active_pads = {}
        self.active_memory_pads = {}
        self.active_fx_pads = {}
        self.active_effect = None
        self.active_effect_config = {}
        self.effect_superposition = False
        self._stacked_effects = []
        self.fx_pads = [[None] * 8 for _ in range(mw._FX_COL_MAX)]
        self.effect_buttons = []
        self.fader_buttons = []
        self._mem_cue_idx = {}
        self.effect_saved_colors = {}
        self._effect_engine_frame = None
        self._dur_timer = self._dur_progress_timer = _TimerMuet()
        self.sorties = []

    # ── Ce que update_effect appellerait s'il allait au bout ────────────────
    def _update_effect_from_layers(self, cfg):
        self.sorties.append("layers")

    def _update_effect_from_config(self, cfg):
        self.sorties.append("config")

    def _run_named_effect(self):
        self.sorties.append("named")

    def _apply_fx_amplitude(self):
        pass

    # ── Le reste du decor, neutralise ───────────────────────────────────────
    def _slot_groups(self, slot):
        return []

    def send_dmx_update(self):
        pass

    def activate_default_white_pads(self, group_rows=None):
        pass

    def set_video_fx(self, fx):
        """CLEAR desarme aussi l'effet video (colonne VIDEO)."""
        pass

    def _style_fx_pad(self, fx_col, row):
        pass

    def _update_fx_pad_led(self, fx_col, row):
        pass

    def _auto_blink_stop(self):
        pass

    def _sync_cue_play_button(self):
        pass

    def _log_message(self, texte, niveau="info"):
        pass

    def _armer_pad_fx(self, fx_col=0, row=0):
        """Equivalent de _toggle_fx_pad : le pad arme l'effet."""
        self.active_fx_pads[(fx_col, row)] = True
        self.active_effect = "Papillon"
        self.active_effect_config = {"name": "Papillon",
                                     "layers": [{"target_groups": ["A"]}]}


class TestColonneFX(unittest.TestCase):

    def test_demarrage_ne_coupe_pas_l_amplitude_fx(self):
        w = FauxWin()
        w._startup_faders_down()
        self.assertEqual(w.fx_amplitudes[0], 100,
                         "le demarrage a remis l'amplitude de la colonne FX a 0")

    def test_effet_sort_apres_le_demarrage(self):
        w = FauxWin()
        w._startup_faders_down()
        w._armer_pad_fx()
        w.update_effect()
        self.assertEqual(w.sorties, ["layers"],
                         "l'effet du pad FX n'atteint pas les projecteurs")

    def test_fader_fx_affiche_l_amplitude_et_non_zero(self):
        w = FauxWin()
        w._startup_faders_down()
        self.assertEqual(w.faders[0].value, 100,
                         "le fader FX affiche 0 alors que l'amplitude vaut 100")

    def test_colonnes_de_groupe_toujours_baissees_au_demarrage(self):
        """La garantie d'origine tient : rien d'allume au lancement."""
        w = FauxWin()
        for i in range(1, 8):
            w.faders[i].value = 80
        w._startup_faders_down()
        for i in range(1, 8):
            self.assertEqual(w.faders[i].value, 0,
                             f"la colonne de groupe {i} n'a pas ete baissee")

    def test_clear_ne_rend_pas_la_colonne_fx_muette(self):
        w = FauxWin()
        w._clear_akai_state()
        self.assertEqual(w.fx_amplitudes[0], 100,
                         "CLEAR a remis l'amplitude de la colonne FX a 0")
        w._armer_pad_fx()
        w.update_effect()
        self.assertEqual(w.sorties, ["layers"],
                         "apres CLEAR, un pad FX ne sort plus rien")

    def test_amplitude_reglee_a_la_main_est_respectee(self):
        """Baisser le fader FX doit toujours faire taire l'effet."""
        w = FauxWin()
        w.set_proj_level(0, 0)
        self.assertEqual(w.fx_amplitudes[0], 0)
        w._armer_pad_fx()
        w.update_effect()
        self.assertEqual(w.sorties, [],
                         "fader FX a 0 : l'effet devrait rester muet")


if __name__ == "__main__":
    unittest.main(verbosity=2)
