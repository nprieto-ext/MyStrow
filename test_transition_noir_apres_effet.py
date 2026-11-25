"""Fin de média avec un effet en cours : le rig doit rester NOIR.

Remontée de Nico (20/11/2026) : « l'effet, ça passe au blanc, ça a envoyé du
blanc entre deux médias dans la séquence ».

`transition_blackout` mettait les projecteurs au noir PUIS appelait
`stop_effect`, qui repose l'état capturé avant l'effet (couleur, niveau) :
le noir était aussitôt annulé et le rig se rallumait, souvent en blanc,
jusqu'au média suivant.

    python -m unittest test_transition_noir_apres_effet
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)
M = mw.MainWindow


class Proj:
    def __init__(self):
        self.group = "face"
        self.fixture_type = "PAR LED"
        self.base_color = QColor("#ff0000")
        self.color = QColor("#ff0000")
        self.level = 80
        self.strobe_speed = 0
        self.dmx_mode = "Manuel"


class FauxWin:
    transition_blackout = M.transition_blackout
    stop_effect = M.stop_effect
    _restore_effect_state = M._restore_effect_state
    _apply_effect_capture = M._apply_effect_capture

    def __init__(self):
        self.projectors = [Proj(), Proj()]
        self.effect_buttons = []
        self.active_effect = "Rainbow"
        # Capture d'avant-effet : blanc plein (cas typique)
        blanc = QColor("#ffffff")
        self.effect_saved_colors = {id(p): (QColor(blanc), QColor(blanc), 100)
                                    for p in self.projectors}

    def _return_lyres_after_effect(self, aims):
        pass

    def restore_manual_look(self):
        pass   # rien n'est tenu à la main dans ce scénario


class T(unittest.TestCase):
    def test_le_noir_n_est_pas_annule_par_l_arret_de_l_effet(self):
        w = FauxWin()
        w.transition_blackout()
        for p in w.projectors:
            self.assertEqual(p.level, 0)
            self.assertEqual(p.color.name(), "#000000")
            self.assertEqual(p.base_color.name(), "#000000")
        self.assertIsNone(w.active_effect)
        self.assertEqual(w.effect_saved_colors, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
