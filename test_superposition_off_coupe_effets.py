"""
test_superposition_off_coupe_effets.py — Decocher « Superposition d'effets »
laissait les effets enclenches.

La case ne faisait que basculer le drapeau `effect_superposition`. Or
`update_effect` ne lit la pile `_stacked_effects` QUE si ce drapeau est vrai :
en le baissant, les effets empiles n'etaient plus animes par personne, mais
restaient armes — pads allumes sur l'APC, boutons actifs dans l'UI, projecteurs
figes sur la derniere image de l'effet.

Changer de mode doit donc couper les effets lances depuis les boutons d'effet :
pile videe, timer arrete, etat d'avant l'effet restitue, LEDs eteintes.

    python test_superposition_off_coupe_effets.py
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
        self.styles = 0

    def update_style(self):
        self.styles += 1


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
        self.base_color = QColor("red")
        self.color = QColor("red")
        self.level = 100
        self.pan = self.tilt = 0


class FauxWin:
    """MainWindow reduite au strict necessaire pour la bascule de mode."""

    toggle_effect         = mw.MainWindow.toggle_effect
    stop_effect           = mw.MainWindow.stop_effect
    _restore_effect_state = mw.MainWindow._restore_effect_state
    _stop_button_effects  = mw.MainWindow._stop_button_effects

    def __init__(self):
        self.effect_superposition = True
        self._stacked_effects = []
        self.effect_buttons = [FauxBouton("Chenillard"), FauxBouton("Strobe")]
        self._button_effect_configs = {0: {"n": 0}, 1: {"n": 1}}
        self.active_effect = None
        self.active_effect_config = {}
        self._prev_effect_state = None
        self.effect_saved_colors = {}
        self._effect_engine_frame = None
        self.effect_timer = FauxTimer()
        self.projectors = [FauxProjecteur()]
        self.leds = []
        self.logs = []
        self.midi_handler = self

    # ── Decor neutralise ────────────────────────────────────────────────────
    midi_out = True

    def set_pad_led(self, col, row, velocity, brightness_percent=100):
        self.leds.append((col, row, velocity))

    def _snapshot_effect_state(self):
        for p in self.projectors:
            self.effect_saved_colors[id(p)] = (QColor(p.base_color), QColor(p.color), p.level)

    def _log_message(self, msg, kind=""):
        self.logs.append(msg)

    def _warn_effect_no_targets(self, cfg):
        pass

    def _start_pan_tilt_transition(self, *a):
        pass

    def _pantilt_in_limits(self, p, axe, norm, defaut):
        return defaut

    def _bascule(self):
        pass


class SuperpositionOff(unittest.TestCase):

    def _deux_effets_en_route(self):
        win = FauxWin()
        win.toggle_effect(0)
        win.toggle_effect(1)
        self.assertEqual(len(win._stacked_effects), 2, "les deux effets doivent etre empiles")
        self.assertTrue(win.effect_timer.running)
        return win

    def test_decocher_vide_la_pile_et_desarme_les_boutons(self):
        win = self._deux_effets_en_route()
        win.leds.clear()

        win.effect_superposition = False
        win._stop_button_effects("bascule")

        self.assertEqual(win._stacked_effects, [], "la pile doit etre videe")
        self.assertFalse(any(b.active for b in win.effect_buttons),
                         "aucun bouton d'effet ne doit rester arme")
        self.assertFalse(win.effect_timer.running, "le timer d'effet doit etre arrete")
        self.assertIsNone(win.active_effect)
        self.assertEqual(win.active_effect_config, {})

    def test_les_leds_de_l_akai_s_eteignent(self):
        win = self._deux_effets_en_route()
        win.leds.clear()

        win._stop_button_effects()

        eteintes = {col for (col, row, vel) in win.leds if row == 8 and vel == 0}
        self.assertEqual(eteintes, {0, 1},
                         "les pads d'effet 1 et 2 doivent recevoir une velocite 0")

    def test_l_etat_d_avant_l_effet_est_restitue(self):
        win = FauxWin()
        p = win.projectors[0]
        p.base_color = QColor("blue")
        p.color = QColor("blue")
        p.level = 40

        win.toggle_effect(0)
        # L'effet a barbouille le projecteur en blanc plein feu
        p.base_color, p.color, p.level = QColor("white"), QColor("white"), 100

        win._stop_button_effects()

        self.assertEqual(p.base_color.name(), QColor("blue").name())
        self.assertEqual(p.level, 40, "le niveau d'avant l'effet doit revenir")
        self.assertEqual(win.effect_saved_colors, {}, "la capture doit etre videe")

    def test_sans_effet_en_cours_c_est_un_non_evenement(self):
        win = FauxWin()
        win._stop_button_effects("bascule")
        self.assertEqual(win.logs, [], "rien a couper : pas de trace, pas de restitution")
        self.assertEqual(win.leds, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
