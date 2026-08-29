"""
test_effet_changement_vitesse.py — Changer la vitesse ne doit pas faire SAUTER l'effet.

Symptome (28/08/2026) : « quand je change la vitesse de l'effet via mon AKAI, ca a
tendance a bouger tres vite, pour se caler a la bonne vitesse ».

La position dans le cycle valait `freq x temps ecoule`, la vitesse generale etant
enfermee dans `freq` (`layer_frequency(..., fader_mult=...)`). Bouger le fader FX
changeait donc `freq` sous un `t` deja grand : la phase sautait de `Δfreq x t` d'un
coup — plusieurs tours entiers apres quelques dizaines de secondes. En balayant le
fader, une salve de sauts, d'ou l'impression d'emballement avant de se caler.

Fix : une HORLOGE DE PHASE. On accumule le temps DEFORME par la vitesse
(`dt x fader_mult`) et `freq` n'en depend plus. A vitesse constante c'est
exactement l'ancien calcul (parite avec l'apercu de l'editeur), mais la phase
reste CONTINUE quand la vitesse bouge : seule sa derivee change.

    python test_effet_changement_vitesse.py
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from core import layer_frequency
import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)


class FauxProj:
    def __init__(self):
        self.group = "face"
        self.fixture_type = "PAR LED"
        self.dmx_profile = ["R", "G", "B", "Dim"]
        self.base_color = QColor("#ffffff")
        self.color = QColor("#ffffff")
        self.level = 100
        self.pan = self.tilt = 32768
        self.white_boost = self.amber_boost = self.uv = 0
        self.color_wheel = self.gobo = self.zoom = 0
        self.color_wheel_slots = []


class FauxWin:
    """MainWindow reduite au moteur d'effets a couches."""

    _update_effect_from_layers = mw.MainWindow._update_effect_from_layers
    _update_color_wheel        = mw.MainWindow._update_color_wheel
    _GENERIC_WHEEL_SLOTS       = mw.MainWindow._GENERIC_WHEEL_SLOTS

    def __init__(self, speed=100):
        self.projectors = [FauxProj()]
        self.effect_speed = speed
        self.effect_t0 = 0.0
        self.effect_saved_colors = {}
        self._effect_clock = 0.0
        self._effect_clock_ts = None
        self.position_presets = []


# Une couche Dimmer en dent de scie : `level` lit directement la phase.
CFG = {"layers": [{"attribute": "Dimmer", "forme": "Montée", "speed": 50,
                   "size": 100, "spread": 0, "phase": 0, "fade": 0,
                   "direction": 1, "target_preset": "Tous", "target_groups": []}]}


def _frames(w, horloge, cfg=CFG):
    """Joue une frame par horodatage (monotonic simule) et rend les phases."""
    phases = []
    for ts in horloge:
        with mock.patch("time.monotonic", return_value=ts):
            w._update_effect_from_layers(cfg)
        phases.append(w._effect_clock)
    return phases


class TestHorlogeDePhase(unittest.TestCase):

    def test_a_vitesse_constante_c_est_l_ancien_calcul(self):
        """Parite : horloge deformee x freq == ancien freq(fader) x temps reel."""
        for fader in (20, 50, 100):
            w = FauxWin(speed=fader)
            horloge = [i * 0.04 for i in range(1, 251)]   # 10 s a 25 fps
            _frames(w, horloge)
            t_reel = horloge[-1] - horloge[0]             # 1re frame : dt = 0
            ancienne = layer_frequency(50, fader_mult=fader / 100.0) * t_reel
            nouvelle = layer_frequency(50) * w._effect_clock
            self.assertAlmostEqual(nouvelle, ancienne, places=6,
                                   msg=f"vitesse {fader} : la cadence a change")

    def test_changer_la_vitesse_ne_fait_pas_sauter_la_phase(self):
        w = FauxWin(speed=20)
        horloge = [i * 0.04 for i in range(1, 751)]       # 30 s a 20 %
        _frames(w, horloge)
        avant = layer_frequency(50) * w._effect_clock

        w.effect_speed = 80                                # coup de fader
        _frames(w, [30.04])
        apres = layer_frequency(50) * w._effect_clock

        saut = apres - avant
        # A 80 %, une frame de 40 ms avance de 0,04 x 0,8 x 3,55 Hz ≈ 0,11 cycle.
        self.assertLess(saut, 0.2, "la phase a saute : l'effet part en avant")
        self.assertGreater(saut, 0.0)

    def test_l_ancien_calcul_lui_sautait_bien(self):
        """Temoin : le calcul d'origine sautait de plusieurs TOURS. """
        t = 30.0
        avant = layer_frequency(50, fader_mult=0.2) * t
        apres = layer_frequency(50, fader_mult=0.8) * t
        self.assertGreater(apres - avant, 3.0,
                           "sans saut a reproduire, ce test ne prouve rien")

    def test_la_vitesse_agit_bien_sur_la_cadence(self):
        """Continuite ne veut pas dire immobilite : 80 % avance 4x plus que 20 %."""
        lent, rapide = FauxWin(speed=20), FauxWin(speed=80)
        horloge = [i * 0.04 for i in range(1, 51)]
        _frames(lent, horloge)
        _frames(rapide, horloge)
        self.assertAlmostEqual(rapide._effect_clock / lent._effect_clock, 4.0, places=3)

    def test_une_frame_en_retard_ne_propulse_pas_l_effet(self):
        """dt plafonne : un freeze de 3 s ne doit pas avancer l'effet de 3 s."""
        w = FauxWin(speed=100)
        _frames(w, [0.04, 3.5])       # 3,46 s d'ecart entre deux frames
        self.assertLessEqual(w._effect_clock, 0.25)

    def test_l_horloge_repart_de_zero_a_chaque_effet(self):
        w = FauxWin(speed=100)
        _frames(w, [i * 0.04 for i in range(1, 51)])
        self.assertGreater(w._effect_clock, 0)
        w._effect_clock, w._effect_clock_ts = 0.0, None   # ce que fait start_effect
        _frames(w, [100.0, 100.04])
        self.assertAlmostEqual(w._effect_clock, 0.04, places=6)


class TestPariteApercu(unittest.TestCase):
    """L'apercu de l'editeur doit lire la MEME horloge que le show."""

    def test_l_apercu_lit_l_horloge_du_show_quand_l_effet_tourne(self):
        import inspect
        import effect_editor
        src = inspect.getsource(effect_editor.EffectEditorDialog._preview_tick)
        self.assertIn("_effect_clock", src,
                      "l'apercu est reste sur le temps reel : il derive du DMX")

    def test_l_apercu_ne_multiplie_plus_la_frequence_par_le_fader(self):
        import inspect
        import effect_editor
        src = inspect.getsource(effect_editor.EffectEditorDialog._compute_preview)
        self.assertNotIn("fader_mult", src,
                         "la vitesse serait comptee deux fois (horloge + frequence)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
