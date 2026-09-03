"""
test_face_alt_bicolore.py — la face doit alterner ses couleurs comme les contres.

`audio_ai.get_state_at` calcule `face_alt` (mode bicolore, tous les ~6 beats)
et l'emet dans l'etat a chaque image depuis toujours. Personne ne le lisait :
`_apply_live_state_inner` consommait `contre_alt` et `lat_alt`, jamais
`face_alt`. Contres et lateraux alternaient donc une couleur sur deux, la face
restait d'un seul bloc.

Ca ne se voyait pas tant que la face comptait deux ou trois projecteurs. Sur
une facade de 8 PAR — tous dans le groupe A, ce qui est le cas par defaut
depuis que toute fixture importee y atterrit — la rampe entiere tenait UNE
seule teinte : « les Par LED ne changeaient pas enormement de couleurs »
(retour client, 02/09/2026).

    python test_face_alt_bicolore.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main_window as mw
from audio_ai import AudioColorAI

_app = QApplication.instance() or QApplication(sys.argv)


class FauxProjecteur:
    def __init__(self, group):
        self.group = group
        self.fixture_type = "PAR LED"
        self.dmx_profile = ["R", "G", "B"]
        self.level = 0
        self.base_color = QColor("black")
        self.color = QColor("black")
        self.pan = self.tilt = 32768


class FauxFxSrc:
    """Panneau LIVE reduit : IA musicale, aucun filtre, palette auto."""

    ia_mode          = 'musical'
    active_special   = None
    nervosity        = 50
    live_palette     = []
    allowed_effects  = set()
    allowed_groups   = set()
    color_tile_pool  = []          # vide => pas de remapping vers le pool
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
    movement_patterns = ['cercle']
    movement_pattern  = 'cercle'
    movement_speed    = 50
    movement_size     = 70
    movement_duration = 40
    lyre_presets      = []
    dimmer_values     = {}

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
    """MainWindow reduite au moteur d'etat live."""

    _apply_live_state_inner = mw.MainWindow._apply_live_state_inner
    _pantilt_in_limits      = staticmethod(mw.MainWindow._pantilt_in_limits)

    def __init__(self, groupes):
        self.projectors     = [FauxProjecteur(g) for g in groupes]
        self._fx_src        = FauxFxSrc()
        self.live_engine    = FauxMoteur()
        self.ia_max_dimmers = {}
        self.ia_params      = {}
        self._ia_audio_ai   = AudioColorAI()
        self._ia_audio_ai.set_dominant_color(QColor("#ff0000"))
        self.seq            = type('S', (), {'live_mode_active': False})()
        self._hw_strobe_calls = []

    def _ia_engine_running(self):
        return True

    def _live_set_hw_strobe(self, rate, skip=None):
        self._hw_strobe_calls.append(rate)

    def _live_hw_strobe_ids(self, skip=None):
        return set()

    def _log_live_error(self, *a):
        raise AssertionError(a)

    def couleurs(self, groupe):
        return [(p.base_color.red(), p.base_color.green(), p.base_color.blue())
                for p in self.projectors if p.group == groupe]


def _etat(face, face_alt, contre, contre_alt):
    return {
        'face':    (face, 80),
        'contre':  (contre, 80),
        'lat':     (contre, 80),
        'face_alt':   face_alt,
        'contre_alt': contre_alt,
        'lat_alt':    None,
        'lat_effect': None,
        'section': 'verse',
        'energy':  0.5,
        '_ia_position': 1000,
    }


class TestFaceAlt(unittest.TestCase):

    def test_le_producteur_emet_bien_face_alt(self):
        """Garde-fou sur `audio_ai` : `face_alt` existe et differe de la face."""
        ai = AudioColorAI()
        ai.set_dominant_color(QColor("#ff0000"))
        ai.beats = [i * 500 for i in range(64)]
        ai.energy_map = [0.8] * 400
        ai.analyzed = True
        vus = set()
        for t in range(0, 30000, 250):
            st = ai.get_state_at(t, 60000)
            if st['face_alt'] is not None:
                vus.add((st['face'][0].name(), st['face_alt'].name()))
        self.assertTrue(vus, "aucun etat bicolore emis sur 30 s")
        for face, alt in vus:
            self.assertNotEqual(face, alt,
                                "face_alt identique a la face : rien a alterner")

    def test_la_face_alterne_une_couleur_sur_deux(self):
        """8 PAR en groupe A : les pairs prennent `face`, les impairs `face_alt`."""
        w = FauxWin(['face'] * 8)
        rouge, bleu = QColor("#ff0000"), QColor("#0000ff")
        w._apply_live_state_inner(_etat(rouge, bleu, rouge, None))
        couleurs = w.couleurs('face')
        self.assertEqual(couleurs[0::2], [(255, 0, 0)] * 4)
        self.assertEqual(couleurs[1::2], [(0, 0, 255)] * 4,
                         "la face ne consomme pas face_alt : rampe monochrome")

    def test_sans_bicolore_la_face_reste_unie(self):
        """`face_alt` a None (hors mode bicolore) : comportement d'avant."""
        w = FauxWin(['face'] * 8)
        rouge = QColor("#ff0000")
        w._apply_live_state_inner(_etat(rouge, None, rouge, None))
        self.assertEqual(w.couleurs('face'), [(255, 0, 0)] * 8)

    def test_les_contres_alternent_toujours(self):
        """Non-regression : l'alternance des contres n'a pas bouge."""
        w = FauxWin(['contre'] * 4)
        rouge, vert = QColor("#ff0000"), QColor("#00ff00")
        w._apply_live_state_inner(_etat(rouge, None, rouge, vert))
        couleurs = w.couleurs('contre')
        self.assertEqual(couleurs[0::2], [(255, 0, 0)] * 2)
        self.assertEqual(couleurs[1::2], [(0, 255, 0)] * 2)

    def test_le_compteur_de_face_est_independant(self):
        """Plan mixte : l'index d'alternance de la face ne suit pas les contres."""
        w = FauxWin(['contre', 'face', 'contre', 'face'])
        rouge, bleu = QColor("#ff0000"), QColor("#0000ff")
        w._apply_live_state_inner(_etat(rouge, bleu, rouge, None))
        # Les deux faces sont en position 0 et 1 de LEUR groupe, pas 1 et 3.
        self.assertEqual(w.couleurs('face'), [(255, 0, 0), (0, 0, 255)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
