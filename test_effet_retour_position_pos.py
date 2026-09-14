# -*- coding: utf-8 -*-
"""Fin d'effet : la lyre revient sur le preset POS rappele, pas au centre.

Bug live AKAI : une colonne POS envoie un preset de position aux lyres, puis on
lance un effet (meme un effet de COULEUR, qui ne touche pas au pan/tilt). A la
coupure, `stop_effect` restituait bien le pan/tilt d'avant... puis une boucle
renvoyait toutes les Moving Head au centre de leur zone juste apres. Les deux
ecritures se contredisaient, la derniere gagnait : « les lyres reprennent leur
position de base et non le preset ».
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)

CENTRE = 32768


class FauxProjecteur:
    def __init__(self, fixture_type='Moving Head', pan=CENTRE, tilt=CENTRE):
        self.fixture_type = fixture_type
        self.name = fixture_type
        self.base_color = QColor("blue")
        self.color = QColor("blue")
        self.level = 100
        self.pan, self.tilt = pan, tilt
        self.white_boost = self.amber_boost = self.uv = 0
        self.color_wheel = self.gobo = self.zoom = 0
        self.dmx_mode = "Manuel"


class FauxTimer:
    def __init__(self):
        self.running = False

    def stop(self):
        self.running = False

    def isActive(self):
        return self.running


class FauxWin:
    """MainWindow reduite au chemin « fin d'effet → ou revient la lyre »."""

    stop_effect                = mw.MainWindow.stop_effect
    _restore_effect_state      = mw.MainWindow._restore_effect_state
    _snapshot_effect_state     = mw.MainWindow._snapshot_effect_state
    _return_lyres_after_effect = mw.MainWindow._return_lyres_after_effect
    _effect_state_tuple        = staticmethod(mw.MainWindow._effect_state_tuple)

    def __init__(self, projos):
        self.projectors = projos
        self.effect_buttons = []
        self.effect_saved_colors = {}
        self._effect_engine_frame = None
        self.effect_timer = FauxTimer()
        self._pan_tilt_transitions = {}
        self.vises = {}          # id(projo) → (pan, tilt) demande a la transition

    def _start_pan_tilt_transition(self, proj, pan, tilt, duree=500):
        self.vises[id(proj)] = (pan, tilt)

    def _pantilt_in_limits(self, p, axe, norm, defaut):
        # Zone volontairement decentree : un vrai centre de zone ne vaut pas 32768.
        return 20000 if axe == 'pan' else 25000


def _lyre_apres_effet(win, lyre):
    """La visee demandee a la lyre, a defaut la valeur ecrite en direct."""
    return win.vises.get(id(lyre), (lyre.pan, lyre.tilt))


class RetourApresEffet(unittest.TestCase):

    def test_la_lyre_revient_sur_le_preset_pos(self):
        """Le coeur du bug : pad POS, puis effet, puis coupure."""
        lyre = FauxProjecteur(pan=50000, tilt=12000)   # preset POS rappele
        win = FauxWin([lyre])
        win._snapshot_effect_state()                   # start_effect
        lyre.color = QColor("red")                     # l'effet de couleur tourne
        win.stop_effect()
        self.assertEqual(_lyre_apres_effet(win, lyre), (50000, 12000))

    def test_le_clip_position_de_la_timeline_prime(self):
        lyre = FauxProjecteur(pan=50000, tilt=12000)
        win = FauxWin([lyre])
        win._snapshot_effect_state()
        win._timeline_pos_centers = {id(lyre): (7777, 8888)}
        win.stop_effect()
        self.assertEqual(_lyre_apres_effet(win, lyre), (7777, 8888))

    def test_sans_capture_on_retombe_sur_le_centre_de_zone(self):
        """Coupure a vide (double stop, demarrage) : le dernier recours tient."""
        lyre = FauxProjecteur(pan=50000, tilt=12000)
        win = FauxWin([lyre])
        win.stop_effect()                              # aucune capture
        self.assertEqual(_lyre_apres_effet(win, lyre), (20000, 25000))

    def test_une_transition_en_vol_n_est_pas_ecrasee(self):
        """Pad POS rappele 200 ms avant la coupure : l'animation vise plus juste."""
        lyre = FauxProjecteur(pan=40000, tilt=20000)
        win = FauxWin([lyre])
        win._snapshot_effect_state()
        win._pan_tilt_transitions[id(lyre)] = {'p1': 60000, 't1': 5000}
        win.stop_effect()
        self.assertNotIn(id(lyre), win.vises)

    def test_les_projos_sans_moteur_sont_ignores(self):
        par = FauxProjecteur(fixture_type='PAR LED', pan=0, tilt=0)
        win = FauxWin([par])
        win._snapshot_effect_state()
        win.stop_effect()
        self.assertNotIn(id(par), win.vises)

    def test_une_lyre_absente_de_la_capture_va_au_centre(self):
        """Lyre patchee pendant l'effet : rien a lui rendre, centre de zone."""
        lyre_a = FauxProjecteur(pan=50000, tilt=12000)
        win = FauxWin([lyre_a])
        win._snapshot_effect_state()
        lyre_b = FauxProjecteur(pan=1111, tilt=2222)
        win.projectors.append(lyre_b)
        win.stop_effect()
        self.assertEqual(_lyre_apres_effet(win, lyre_a), (50000, 12000))
        self.assertEqual(_lyre_apres_effet(win, lyre_b), (20000, 25000))


class SourceDuCorrectif(unittest.TestCase):

    def test_les_deux_chemins_passent_par_le_meme_helper(self):
        """Mode exclusif ET mode superposition : une seule regle de retour."""
        import inspect
        src = inspect.getsource(mw.MainWindow.stop_effect)
        self.assertIn("_return_lyres_after_effect", src)
        src_toggle = inspect.getsource(mw.MainWindow.toggle_effect)
        self.assertIn("_return_lyres_after_effect", src_toggle)
        self.assertNotIn("_pantilt_in_limits", src_toggle)


if __name__ == '__main__':
    unittest.main(verbosity=2)
