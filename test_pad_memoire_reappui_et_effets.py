"""
test_pad_memoire_reappui_et_effets.py — Retour client du 23/09/2026 :
« quand on lance une mémoire ça coupe tout, après les effets ne marchent plus,
et on ne peut plus les arrêter (en réappuyant sur le pad) ».

1. Une mémoire ne coupe plus un effet qu'elle n'a pas lancé. Avant, poser une
   mémoire SANS effet — ou juste bouger un fader mémoire — arrêtait l'effet du
   bouton en laissant le bouton allumé ; en superposition la pile restait
   pleine sans minuterie et plus aucun effet ne repartait.
2. Réappuyer sur un pad mémoire à UN cue l'éteint (appui direct seulement).
   Multi-cue : toujours « cue suivant ». Déclencheurs externes : inchangés.

    python test_pad_memoire_reappui_et_effets.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main_window as mw
import test_pad_memoire_comportement as base


class Bouton:
    def __init__(self, nom):
        self.current_effect = nom
        self.active = False

    def update_style(self):
        pass


class Win(base.FauxWin):
    toggle_effect        = mw.MainWindow.toggle_effect
    stop_effect          = mw.MainWindow.stop_effect
    start_effect         = mw.MainWindow.start_effect
    _stop_button_effects = mw.MainWindow._stop_button_effects
    _mem_drive_effect    = mw.MainWindow._mem_drive_effect
    trigger_memory       = mw.MainWindow.trigger_memory

    def __init__(self, superposition=False):
        super().__init__()
        self.effect_superposition = superposition
        self.effect_buttons = [Bouton("Chase"), Bouton("Rainbow")]
        self._button_effect_configs = {}
        self._stacked_effects = []
        self._prev_effect_state = None
        self._mem_effect = None
        self.active_fx_pads = {}
        self.effect_timer = base._TimerMuet()
        self.midi_handler = type("M", (), {"midi_out": None})()
        # MEM 1.2 porte un effet à couches ; MEM 1.3 a deux cues.
        cue_fx = base._cue(3, {2: 100}, "#00ff00")
        cue_fx["effect"] = {"name": "Vague mem", "layers": [{}]}
        self.memories[0][1] = {"cues": [cue_fx], "loop": True}
        self.memories[0][2] = {"cues": [base._cue(3, {0: 100}), base._cue(3, {1: 100})],
                               "loop": True}

    def _snapshot_effect_state(self):
        pass

    def _return_lyres_after_effect(self, aims=None):
        pass

    def _warn_effect_no_targets(self, cfg):
        pass

    def tourne(self):
        return self.effect_timer.isActive()


class MemoireNeCoupePlusLesEffetsBoutons(unittest.TestCase):

    def _scenario(self, superposition):
        w = Win(superposition)
        w.toggle_effect(0)
        self.assertTrue(w.tourne())
        w.poser(0)                                  # mémoire SANS effet
        self.assertTrue(w.tourne(), "poser une mémoire a coupé l'effet du bouton")
        self.assertEqual(w.active_effect, "Chase")
        w.faders[0].value = 40
        w._recompute_memory_mix()                   # geste de fader
        self.assertTrue(w.tourne(), "bouger un fader a coupé l'effet du bouton")
        w.toggle_effect(1)
        self.assertTrue(w.tourne(), "un 2e effet ne repart plus")

    def test_exclusif(self):
        self._scenario(False)

    def test_superposition(self):
        self._scenario(True)


class EffetPorteParLaMemoire(unittest.TestCase):

    def test_memoire_lance_et_rend_son_effet(self):
        w = Win()
        w.poser(0, 1)
        self.assertEqual(w.active_effect, "Vague mem")
        self.assertTrue(w.tourne())
        w.poser(0, 0)                               # autre pad de la colonne
        self.assertIsNone(w.active_effect)
        self.assertFalse(w.tourne())
        w.toggle_effect(0)                          # les boutons remarchent
        self.assertTrue(w.tourne())

    def test_memoire_a_effet_prend_la_main_proprement(self):
        w = Win(superposition=True)
        w.toggle_effect(0)
        w.poser(0, 1)
        self.assertEqual(w.active_effect, "Vague mem")
        self.assertFalse(w.effect_buttons[0].active, "bouton resté allumé dans le vide")
        self.assertEqual(w._stacked_effects, [])

    def test_bouton_par_dessus_une_memoire_a_effet(self):
        w = Win()
        w.poser(0, 1)
        w.toggle_effect(0)
        w._recompute_memory_mix()                   # un fader bouge
        self.assertEqual(w.active_effect, "Chase", "la mémoire a repris l'effet du bouton")


class ReappuiEteint(unittest.TestCase):

    def test_un_seul_cue(self):
        w = Win()
        w.poser(0)
        self.assertEqual(w.active_memory_pads.get(0), 0)
        w.poser(0)
        self.assertNotIn(0, w.active_memory_pads)
        self.assertEqual(w.niveaux()[0], 0)

    def test_multi_cue_avance_toujours(self):
        w = Win()
        w.poser(0, 2)
        w.poser(0, 2)
        self.assertEqual(w.active_memory_pads.get(0), 2)
        self.assertEqual(w._mem_cue_idx[(0, 2)], 1)

    def test_declencheur_externe_ne_coupe_pas(self):
        w = Win()
        w.trigger_memory(0, 0)
        w.trigger_memory(0, 0)
        self.assertEqual(w.active_memory_pads.get(0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
