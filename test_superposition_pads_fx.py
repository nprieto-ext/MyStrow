"""
test_superposition_pads_fx.py — Les pads FX ignoraient « Superposition d'effets ».

Avec la case cochee, les boutons d'effet (colonne de droite de l'AKAI)
s'empilaient, mais `_toggle_fx_pad` restait exclusif : appuyer sur un pad FX
eteignait les autres pads ET les boutons d'effet. Le client ne pouvait donc pas
superposer deux effets depuis la grille.

En superposition, un pad FX doit s'ajouter a la meme pile `_stacked_effects`
que les boutons ; son reappui le retire seul ; le dernier retire restitue
l'etat d'avant-effet.

    python test_superposition_pads_fx.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)


class FauxBouton:
    def __init__(self, nom):
        self.current_effect = nom
        self.active = False

    def update_style(self):
        pass


class FauxTimer:
    def __init__(self):
        self.running = False

    def start(self, _ms=None):
        self.running = True

    def stop(self):
        self.running = False


class FauxProjecteur:
    def __init__(self):
        self.fixture_type = "PAR LED"
        self.group = "face"
        self.dmx_mode = "Manuel"
        self.base_color = QColor("blue")
        self.color = QColor("blue")
        self.level = 40
        self.pan = self.tilt = 0


class FauxWin:
    toggle_effect            = mw.MainWindow.toggle_effect
    stop_effect              = mw.MainWindow.stop_effect
    _toggle_fx_pad           = mw.MainWindow._toggle_fx_pad
    _toggle_fx_pad_stacked   = mw.MainWindow._toggle_fx_pad_stacked
    _unstack_fx_pad          = mw.MainWindow._unstack_fx_pad
    _fx_col_amp              = mw.MainWindow._fx_col_amp
    _finish_stacked_once     = mw.MainWindow._finish_stacked_once
    _stop_button_effects     = mw.MainWindow._stop_button_effects
    _restore_effect_state    = mw.MainWindow._restore_effect_state
    _return_lyres_after_effect = mw.MainWindow._return_lyres_after_effect

    def __init__(self):
        self.effect_superposition = True
        self._mem_rec_mode = False
        self._stacked_effects = []
        self.effect_buttons = [FauxBouton("Chenillard")]
        self._button_effect_configs = {0: {"name": "Chenillard"}}
        self.fx_pads = [[None] * 8 for _ in range(mw._FX_COL_MAX)]
        self.fx_pads[0][0] = {"name": "Strobe"}
        self.fx_pads[0][1] = {"name": "Rainbow"}
        self.fx_pads[1][0] = {"name": "Wave"}
        self.active_fx_pads = {}
        self.fx_amplitudes = [100] * mw._FX_COL_MAX
        self.active_effect = None
        self.active_effect_config = {}
        self._prev_effect_state = None
        self.effect_saved_colors = {}
        self._effect_engine_frame = None
        self.effect_timer = FauxTimer()
        self.projectors = [FauxProjecteur()]
        self._pan_tilt_transitions = {}
        self.midi_handler = self
        self.started = []

    midi_out = True

    def set_pad_led(self, *a, **k):
        pass

    def _style_fx_pad(self, fc, r):
        pass

    def _update_fx_pad_led(self, fc, r):
        pass

    def start_effect(self, name):
        self.started.append(name)
        self.effect_timer.start()

    def _snapshot_effect_state(self):
        for p in self.projectors:
            self.effect_saved_colors[id(p)] = (QColor(p.base_color), QColor(p.color), p.level)

    def _log_message(self, msg, kind=""):
        pass

    def _warn_effect_no_targets(self, cfg):
        pass

    def _start_pan_tilt_transition(self, *a):
        pass

    def _pantilt_in_limits(self, p, axe, norm, defaut):
        return defaut

    def _bascule(self):
        pass


def noms(win):
    return [e['name'] for e in win._stacked_effects]


class PadsFxSuperposes(unittest.TestCase):

    def test_deux_pads_s_empilent(self):
        win = FauxWin()
        win._toggle_fx_pad(0, 0)
        win._toggle_fx_pad(0, 1)
        self.assertEqual(noms(win), ["Strobe", "Rainbow"])
        self.assertEqual(set(win.active_fx_pads), {(0, 0), (0, 1)})
        self.assertTrue(win.effect_timer.running)
        self.assertEqual(win.started, [], "pas de start_effect exclusif en superposition")

    def test_pad_et_bouton_ensemble(self):
        win = FauxWin()
        win.toggle_effect(0)
        win._toggle_fx_pad(1, 0)
        self.assertEqual(noms(win), ["Chenillard", "Wave"])
        self.assertTrue(win.effect_buttons[0].active, "le pad ne doit plus eteindre le bouton")
        # Retirer le bouton laisse le pad
        win.toggle_effect(0)
        self.assertEqual(noms(win), ["Wave"])
        self.assertTrue(win.active_fx_pads.get((1, 0)))

    def test_reappui_retire_seulement_ce_pad(self):
        win = FauxWin()
        win._toggle_fx_pad(0, 0)
        win._toggle_fx_pad(0, 1)
        win._toggle_fx_pad(0, 0)
        self.assertEqual(noms(win), ["Rainbow"])
        self.assertNotIn((0, 0), win.active_fx_pads)
        self.assertTrue(win.effect_timer.running)

    def test_dernier_retire_restitue(self):
        win = FauxWin()
        p = win.projectors[0]
        win._toggle_fx_pad(0, 0)
        p.base_color, p.color, p.level = QColor("white"), QColor("white"), 100
        win._toggle_fx_pad(0, 0)
        self.assertEqual(win._stacked_effects, [])
        self.assertFalse(win.effect_timer.running)
        self.assertEqual(p.base_color.name(), QColor("blue").name())
        self.assertEqual(p.level, 40)
        self.assertIsNone(win.active_effect)

    def test_une_fois_termine_retire_le_pad(self):
        win = FauxWin()
        win._toggle_fx_pad(0, 0)
        win._toggle_fx_pad(1, 0)
        win._finish_stacked_once(None, (0, 0))
        self.assertEqual(noms(win), ["Wave"])
        self.assertNotIn((0, 0), win.active_fx_pads)

    def test_amplitude_colonne_ne_coupe_pas_les_autres(self):
        win = FauxWin()
        win.fx_amplitudes[0] = 0
        win._toggle_fx_pad(0, 0)
        self.assertEqual(win._fx_col_amp(), 0.0)
        win._toggle_fx_pad(1, 0)
        self.assertEqual(win._fx_col_amp(), 1.0)

    def test_changer_de_mode_coupe_les_pads_empiles(self):
        win = FauxWin()
        win._toggle_fx_pad(0, 0)
        win.toggle_effect(0)
        win.effect_superposition = False
        win._stop_button_effects()
        self.assertEqual(win._stacked_effects, [])
        self.assertEqual(win.active_fx_pads, {})
        self.assertFalse(win.effect_timer.running)

    def test_mode_exclusif_inchange(self):
        win = FauxWin()
        win.effect_superposition = False
        win._toggle_fx_pad(0, 0)
        win._toggle_fx_pad(0, 1)
        self.assertEqual(set(win.active_fx_pads), {(0, 1)})
        self.assertEqual(win.started, ["Strobe", "Rainbow"])
        self.assertEqual(win._stacked_effects, [])

    def test_pad_exclusif_orphelin_coupe_au_premier_empilage(self):
        win = FauxWin()
        win.effect_superposition = False
        win._toggle_fx_pad(0, 0)
        win.effect_superposition = True
        win._toggle_fx_pad(0, 1)
        self.assertEqual(set(win.active_fx_pads), {(0, 1)})
        self.assertEqual(noms(win), ["Rainbow"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
