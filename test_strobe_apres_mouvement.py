"""
test_strobe_apres_mouvement.py - FuraxX, 25/11/2026.

1. Un effet mouvement tourne (centre imposé : POSITION ou mouvement enregistré
   depuis le plan 2D). On lance un strobe : la lyre partait au PLAFOND (sa
   visée d'avant l'effet, le repos 32768 d'une lyre posée), puis revenait au
   relâché. Elle doit rester sur le centre du mouvement.
2. Le strobe matériel posé à la main (touche S, bloc Strobe EXT) était figé à
   100 % : il doit suivre le fader 9 (vitesse des effets), en direct.

    python test_strobe_apres_mouvement.py
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


class FauxTimer:
    def __init__(self, actif=True):
        self.actif = actif

    def isActive(self):
        return self.actif

    def start(self, _ms=None):
        self.actif = True

    def stop(self):
        self.actif = False


class FauxLyre:
    def __init__(self):
        self.fixture_type = "Moving Head"
        self.group = "lyre"
        self.pan = self.tilt = 32768
        self.strobe_speed = 0


class FauxWin:
    _note_fx_move_center   = M._note_fx_move_center
    _effect_moves_lyres    = staticmethod(M._effect_moves_lyres)
    _hold_lyres_on_centers = M._hold_lyres_on_centers
    _manual_strobe_rate    = M._manual_strobe_rate
    _track_manual_strobe   = M._track_manual_strobe
    _sync_manual_strobe_speed = M._sync_manual_strobe_speed
    _fader8_dispatch       = M._fader8_dispatch

    def __init__(self):
        self.lyre = FauxLyre()
        self.projectors = [self.lyre]
        self._pan_tilt_transitions = {}
        self.effect_speed = 80

    def stop_effect(self):
        # Comme le vrai : visée d'avant l'effet (plafond) + transition vers elle.
        self.lyre.pan = self.lyre.tilt = 32768
        self._pan_tilt_transitions[id(self.lyre)] = {"p1": 32768}


def changer_effet(win, cfg_nouveau):
    """Le début de `start_effect`, recopié à l'identique."""
    win.active_effect_config = cfg_nouveau
    if win.effect_timer.isActive():
        _centres = {}
        if not win._effect_moves_lyres(win.active_effect_config):
            _centres = dict(getattr(win, '_fx_move_centers', None) or {})
        win.stop_effect()
        win._hold_lyres_on_centers(_centres)
    win._fx_move_centers = {}


STROBE = {"name": "Strobe Classique", "layers": [{"attribute": "RGB", "forme": "Flash"}]}
CERCLE = {"name": "Cercle", "layers": [{"attribute": "Pan/Tilt"}]}


class TestStrobeApresMouvement(unittest.TestCase):
    def test_code_identique_a_start_effect(self):
        import inspect
        src = inspect.getsource(M.start_effect)
        self.assertIn("_hold_lyres_on_centers(_centres)", src)
        self.assertIn("self._fx_move_centers = {}", src)

    def test_strobe_garde_le_centre_du_mouvement(self):
        w = FauxWin()
        w.effect_timer = FauxTimer(True)
        w._note_fx_move_center(w.lyre, (20000, 45000))   # centre du cercle
        changer_effet(w, STROBE)
        self.assertEqual((w.lyre.pan, w.lyre.tilt), (20000, 45000))
        self.assertNotIn(id(w.lyre), w._pan_tilt_transitions)

    def test_mouvement_vers_mouvement_inchange(self):
        w = FauxWin()
        w.effect_timer = FauxTimer(True)
        w._note_fx_move_center(w.lyre, (20000, 45000))
        changer_effet(w, CERCLE)
        self.assertEqual((w.lyre.pan, w.lyre.tilt), (32768, 32768))

    def test_sans_centre_impose_inchange(self):
        w = FauxWin()
        w.effect_timer = FauxTimer(True)
        changer_effet(w, STROBE)
        self.assertEqual((w.lyre.pan, w.lyre.tilt), (32768, 32768))

    def test_couche_pan_seule_ne_touche_pas_le_tilt(self):
        w = FauxWin()
        w.effect_timer = FauxTimer(True)
        w._note_fx_move_center(w.lyre, (20000, 45000), pan=True, tilt=False)
        changer_effet(w, STROBE)
        self.assertEqual((w.lyre.pan, w.lyre.tilt), (20000, 32768))

    def test_strobe_manuel_suit_le_fader_9(self):
        w = FauxWin()
        w.effect_speed = 30
        v = w._manual_strobe_rate()
        w.lyre.strobe_speed = v
        w._track_manual_strobe(w.lyre, v)
        self.assertEqual(w.lyre.strobe_speed, 30)
        w._fader8_dispatch(8, 95)
        self.assertEqual(w.lyre.strobe_speed, 95)
        w._fader8_dispatch(8, 0)
        self.assertEqual(w.lyre.strobe_speed, 1)   # reste allumé

    def test_strobe_coupe_ailleurs_sort_du_registre(self):
        w = FauxWin()
        w.lyre.strobe_speed = 80
        w._track_manual_strobe(w.lyre, 80)
        w.lyre.strobe_speed = 0                    # CLEAR
        w._fader8_dispatch(8, 50)
        self.assertEqual(w.lyre.strobe_speed, 0)   # ne se rallume pas

    def test_code_raccourci_et_ext(self):
        import inspect
        for f in (M._apply_strobe_shortcut, M._ext_set_strobe):
            src = inspect.getsource(f)
            self.assertIn("_manual_strobe_rate()", src)
            self.assertNotIn("100 if on", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
