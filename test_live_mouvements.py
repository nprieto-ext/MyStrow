"""
test_live_mouvements.py — mouvements de lyres calés sur le tempo + tuile AUTO.

Retour client (20/10/2026, location « plug and play » sans contrôleur) : « les
motifs de lyres se répètent trop vite et ne se calent pas sur le beat ».
Causes : rotation en tours/seconde sans lecture du BPM, et réserve par défaut
réduite à `cercle`. Cf. `live_mouvements.py`.

    python test_live_mouvements.py
"""

import bisect
import math
import os
import random
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import live_mouvements as lm
import main_window as mw
from audio_ai import AudioColorAI
from ia_settings import IASettings

_app = QApplication.instance() or QApplication(sys.argv)


# ── Calcul pur ────────────────────────────────────────────────────────────────

class TestCalcul(unittest.TestCase):

    def test_bpm_median_resiste_au_beat_manque(self):
        beats = [i * 500 for i in range(10)]
        beats.pop(5)                       # un beat manqué → un intervalle double
        self.assertAlmostEqual(lm.bpm_depuis_beats(beats, len(beats) - 1), 120.0)

    def test_bpm_inconnu(self):
        self.assertEqual(lm.bpm_depuis_beats([], -1), 0.0)
        self.assertEqual(lm.bpm_depuis_beats([0, 500], 1), 0.0)

    def test_vitesse_puissances_de_2(self):
        self.assertEqual(lm.multiplicateur_vitesse(0), 0.0)
        self.assertEqual(lm.multiplicateur_vitesse(50), 1.0)
        self.assertEqual(lm.multiplicateur_vitesse(75), 2.0)
        self.assertEqual(lm.multiplicateur_vitesse(25), 0.5)
        self.assertEqual(lm.multiplicateur_vitesse(100), 4.0)

    def test_phrase_toujours_entiere(self):
        for d in range(0, 101):
            self.assertIn(lm.temps_par_phrase(d), (8, 16, 32, 64))
        self.assertEqual(lm.temps_par_phrase(40), 16)

    def test_cycle_couplet_120bpm_dure_4_mesures(self):
        # 16 temps à 120 BPM = 8 s → 0,125 tour/s
        self.assertAlmostEqual(lm.vitesse_tours_s(120, 'verse', 1.0), 0.125)
        self.assertAlmostEqual(lm.vitesse_tours_s(120, 'drop', 1.0), 0.5)

    def test_recalage_converge_sur_la_grille(self):
        pas = 2 * math.pi / lm.cycle_temps('verse')
        ph = 3 * pas + 0.4 * pas           # en retard/avance de 40 % d'un temps
        for _ in range(8):
            ph = lm.recaler_phase(ph, 'verse', 1.0)
        self.assertAlmostEqual(ph, 3 * pas, delta=0.02 * pas)

    def test_auto_ne_rejoue_jamais_le_meme(self):
        rnd = random.Random(1)
        cur = 'cercle'
        for section in ['verse', 'build', 'drop', 'quiet'] * 20:
            nxt = lm.motif_suivant(['auto'], cur, section, rnd)
            self.assertNotEqual(nxt, cur)
            self.assertIn(nxt, lm.MOTIFS)
            cur = nxt

    def test_reserve_manuelle_dans_l_ordre(self):
        rnd = random.Random(1)
        self.assertEqual(lm.motif_suivant(['vague', 'cercle'], 'vague', 'drop', rnd), 'cercle')
        self.assertEqual(lm.motif_suivant(['vague', 'cercle'], 'cercle', 'drop', rnd), 'vague')

    def test_changement_de_section_tenu(self):
        self.assertFalse(lm.doit_changer(3, 'drop', 'verse', 16))
        self.assertTrue(lm.doit_changer(8, 'drop', 'verse', 16))
        self.assertTrue(lm.doit_changer(16, 'verse', 'verse', 16))

    def test_random_saute_sur_le_temps(self):
        a = lm.motif_xy('random', 0.0, temps=10, frac=1.0)
        b = lm.motif_xy('random', 2.0, temps=10, frac=1.0)
        self.assertEqual(a, b, "random dépend du temps, pas de la phase")
        self.assertNotEqual(a, lm.motif_xy('random', 0.0, temps=11, frac=1.0))
        # Début de temps : on part du point précédent (fondu, pas de saut)
        self.assertEqual(lm.motif_xy('random', 0.0, temps=11, frac=0.0), a)


# ── Moteur réel (`_apply_live_state_inner`) ──────────────────────────────────

class FauxLyre:
    def __init__(self):
        self.group = 'lyre'
        self.fixture_type = "Moving Head"
        self.dmx_profile = ["PAN", "TILT", "DIM", "R", "G", "B"]
        self.level = 0
        self.base_color = QColor("black")
        self.color = QColor("black")
        self.pan = self.tilt = 32768
        self.gobo = 0
        self.gobo_rotation = 0
        self.gobo_wheel_slots = []


class FauxFxSrc:
    ia_mode          = 'musical'
    active_special   = None
    nervosity        = 50
    live_palette     = []
    allowed_effects  = set()
    allowed_groups   = set()
    color_tile_pool  = []
    current_color_tile = 'rouge'
    color_max        = 4
    color_restrict   = False
    color_cycle      = True
    color_duration   = 40
    gobo_pool        = [0]
    current_gobo     = 0
    gobo_duration    = 40
    gobo_rotation    = False
    gobo_rot_speed   = 50
    strob_fast       = False
    strob_slow       = False
    strob_none       = True
    movement_speed    = 50
    movement_size     = 70
    movement_duration = 40
    lyre_presets      = []
    dimmer_values     = {}

    def __init__(self, reserve):
        self.movement_patterns = list(reserve)
        self.movement_pattern  = 'cercle'
        self.joues = []

    def set_current_movement(self, key):
        self.movement_pattern = key
        self.joues.append(key)

    def get_color_data(self, key):
        return (None, None)

    def is_tile_active(self, key):
        return False


class FauxMoteur:
    _elapsed_ms = 0
    _bpm        = 120.0
    midi_paused = False
    _rms_history = None


class FauxWin:
    _apply_live_state_inner = mw.MainWindow._apply_live_state_inner
    _pantilt_in_limits      = staticmethod(mw.MainWindow._pantilt_in_limits)
    _IA_BASE_COLOR_GROUPS   = mw.MainWindow._IA_BASE_COLOR_GROUPS

    def __init__(self, reserve, bpm=120.0, section='verse'):
        self.projectors     = [FauxLyre() for _ in range(4)]
        self._fx_src        = FauxFxSrc(reserve)
        self.live_engine    = FauxMoteur()
        self.ia_max_dimmers = {}
        self.ia_params      = {}
        self._ia_audio_ai   = AudioColorAI()
        self._ia_audio_ai.set_dominant_color(QColor("#ff0000"))
        self._periode = 60000.0 / bpm
        self._ia_audio_ai.beats = [int(i * self._periode) for i in range(400)]
        self.seq            = type('S', (), {'live_mode_active': False})()
        self.section        = section

    def _ia_engine_running(self):
        return True

    def _live_set_hw_strobe(self, rate, skip=None):
        pass

    def _live_hw_strobe_ids(self, skip=None):
        return set()

    def _update_color_wheel(self, p, c):
        pass

    def _log_live_error(self, *a):
        raise AssertionError(a)

    def jouer(self, de_ms, a_ms, pas=25):
        for t in range(de_ms, a_ms, pas):
            idx = bisect.bisect_right(self._ia_audio_ai.beats, t) - 1
            self._apply_live_state_inner({
                'face': (QColor("#ff0000"), 80), 'contre': (QColor("#ff0000"), 80),
                'lat': (QColor("#ff0000"), 80), 'face_alt': None, 'contre_alt': None,
                'lat_alt': None, 'lat_effect': None,
                'section': self.section, 'energy': 0.6,
                '_ia_position': t, '_ia_beat_idx': idx,
            })


class TestMoteur(unittest.TestCase):

    def test_cycle_retombe_sur_la_mesure(self):
        """Couplet à 120 BPM : la phase revient au départ tous les 16 temps."""
        w = FauxWin(['cercle'])
        w.jouer(0, 40000)                    # 80 temps : vitesse lissée et calée
        pas = 2 * math.pi / lm.cycle_temps('verse')
        ph = w._live_lyre_phase
        ecart = abs(ph / pas - round(ph / pas))
        self.assertLess(ecart, 0.15, f"phase hors grille : {ecart:.2f} temps d'écart")
        self.assertAlmostEqual(w._live_lyre_speed, 0.125, places=2)

    def test_auto_change_de_motif_par_phrase(self):
        """AUTO, couplet : un nouveau motif toutes les 16 temps, jamais le même."""
        w = FauxWin(['auto'])
        w.jouer(0, 34 * 500)                 # 34 temps → 2 changements
        joues = w._fx_src.joues
        self.assertEqual(len(joues), 2, joues)
        for a, b in zip(['cercle'] + joues, joues):
            self.assertNotEqual(a, b)
        for m in joues:
            self.assertIn(m, lm.FAMILLES_AUTO['verse'])

    def test_motif_seul_ne_change_pas(self):
        w = FauxWin(['huit'])
        w._fx_src.movement_pattern = 'huit'
        w.jouer(0, 20000)
        self.assertEqual(w._fx_src.joues, [])

    def test_les_lyres_bougent(self):
        w = FauxWin(['auto'])
        w.jouer(0, 1000)
        avant = [(p.pan, p.tilt) for p in w.projectors]
        w.jouer(1000, 3000)
        self.assertNotEqual(avant, [(p.pan, p.tilt) for p in w.projectors])


# ── Réglages : défaut AUTO et migration ──────────────────────────────────────

class TestMigration(unittest.TestCase):

    def test_defaut_auto(self):
        self.assertEqual(IASettings()._movement_patterns, {'auto'})

    def test_ancien_show_cercle_passe_en_auto(self):
        s = IASettings.from_dict({'mov_pool': ['cercle'], 'mov_current': 'cercle'})
        self.assertEqual(s._movement_patterns, {'auto'})

    def test_cercle_recoche_apres_migration_reste(self):
        s = IASettings.from_dict({'mov_pool': ['cercle'], 'mov_v': 2})
        self.assertEqual(s._movement_patterns, {'cercle'})

    def test_reserve_choisie_conservee(self):
        s = IASettings.from_dict({'mov_pool': ['huit', 'vague']})
        self.assertEqual(s._movement_patterns, {'huit', 'vague'})

    def test_aller_retour(self):
        s = IASettings()
        s2 = IASettings.from_dict(s.to_dict())
        self.assertEqual(s2._movement_patterns, {'auto'})
        self.assertIn(s2._current_movement, lm.MOTIFS)

    def test_auto_accepte_tout_motif_concret(self):
        s = IASettings()
        s.set_current_movement('spirale')
        self.assertEqual(s.movement_pattern, 'spirale')


if __name__ == "__main__":
    unittest.main(verbosity=2)
