"""
test_plan2d_override_htp.py — Le plan 2D peignait NOIR une memoire levee.

Signale le 20/09/2026 : « quand je monte progressivement ma memoire 98.1, ca
fait strobber les projecteurs et ca les eteint — seulement dans le plan 2D,
la 3D et le DMX vont bien ».

`_compute_htp_overrides` stocke `(niveau, couleur EMISE, couleur de base)`, ou
la couleur emise vaut deja `base x niveau / 100`. `_get_fill_color` la
remultipliait par `niveau` (0-100, pas 0-1) : hors de 0-255, QColor rend une
couleur INVALIDE, c'est-a-dire noire.

Il fallait juste qu'un override existe — et il en apparait un des que la
memoire depasse le modele d'un cran. Ca arrive tout le temps : le mix additif
reconstruit `proj.level` depuis les couleurs et y perd un point d'arrondi. Sur
la memoire reelle du signalement (3 PAR RVB magenta a 83 %), environ une
position de fader sur cinq tombait dans ce cas, 100 % comprise.

    python test_plan2d_override_htp.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import plan_de_feu as pdf_mod

_app = QApplication.instance() or QApplication(sys.argv)


class FauxProj:
    def __init__(self, level=0, color="#000000", group="face"):
        self.group = group
        self.level = level
        self.color = QColor(color)
        self.base_color = QColor(color)
        self.muted = False
        self.fixture_type = "PAR LED"
        self.strobe_speed = 0
        self.effect_channels = {}
        self.dmx_profile = ["R", "G", "B"]


class FauxPdf:
    def __init__(self, overrides=None, kill=None):
        self._htp_overrides = overrides
        self._kill_display = kill


class FauxCanvas:
    """FixtureCanvas reduit au calcul de couleur."""
    _get_fill_color = pdf_mod.FixtureCanvas._get_fill_color

    def __init__(self, pdf):
        self.pdf = pdf


def _override(base_hex, niveau):
    """Ce que fabrique `_compute_htp_overrides` : (niveau, emise, base)."""
    base = QColor(base_hex)
    brt = niveau / 100.0
    emise = QColor(int(base.red() * brt), int(base.green() * brt), int(base.blue() * brt))
    return (niveau, emise, base)


class CouleurDeLoverride(unittest.TestCase):

    def test_la_couleur_emise_est_rendue_telle_quelle(self):
        p = FauxProj(level=82, color="#d300d3")
        ov = _override("#ff00ff", 83)
        c = FauxCanvas(FauxPdf({id(p): ov}))._get_fill_color(p)
        self.assertTrue(c.isValid())
        self.assertEqual(c.name(), ov[1].name())

    def test_jamais_noir_quand_la_memoire_est_levee(self):
        """Le symptome : un fader monte, des fixtures qui s'eteignent a l'ecran."""
        p = FauxProj(level=82, color="#d300d3")
        canvas = FauxCanvas(FauxPdf())
        noirs = []
        for niveau in range(1, 101):
            canvas.pdf._htp_overrides = {id(p): _override("#ff00ff", niveau)}
            c = canvas._get_fill_color(p)
            self.assertTrue(c.isValid(), f"couleur invalide a {niveau} %")
            if c.name() == "#000000":
                noirs.append(niveau)
        self.assertEqual(noirs, [], "une memoire levee ne doit jamais peindre noir")

    def test_le_niveau_se_lit_dans_la_couleur(self):
        """Monter le fader doit eclaircir, pas sauter."""
        canvas = FauxCanvas(FauxPdf())
        p = FauxProj(level=10, color="#220022")
        rouges = []
        for niveau in (10, 30, 60, 100):
            canvas.pdf._htp_overrides = {id(p): _override("#ff0000", niveau)}
            rouges.append(canvas._get_fill_color(p).red())
        self.assertEqual(rouges, sorted(rouges))
        self.assertGreater(rouges[-1], rouges[0])

    def test_un_override_a_zero_reste_eteint(self):
        p = FauxProj(level=50, color="#00ff00")
        c = FauxCanvas(FauxPdf({id(p): _override("#ff00ff", 0)}))._get_fill_color(p)
        self.assertEqual(c.name(), "#1a1a1a")

    def test_le_mute_gagne_sur_loverride(self):
        p = FauxProj(level=82, color="#d300d3")
        p.muted = True
        c = FauxCanvas(FauxPdf({id(p): _override("#ff00ff", 83)}))._get_fill_color(p)
        self.assertEqual(c.name(), "#1a1a1a")

    def test_le_solo_flash_kill_gagne_aussi(self):
        p = FauxProj(level=82, color="#d300d3", group="face")
        c = FauxCanvas(FauxPdf({id(p): _override("#ff00ff", 83)},
                               kill={"contre"}))._get_fill_color(p)
        self.assertEqual(c.name(), "#1a1a1a")

    def test_sans_override_le_modele_decide(self):
        p = FauxProj(level=60, color="#00aa00")
        c = FauxCanvas(FauxPdf(None))._get_fill_color(p)
        self.assertEqual(c.name(), "#00aa00")


class MonteeDeFader(unittest.TestCase):
    """Le scenario signale, de bout en bout : mix + overrides + peinture."""

    def _monde(self):
        import main_window as mw

        class F:
            def __init__(s, v=0): s.value = v

        class T:
            def __init__(s): s.on = False
            def start(s, *a): s.on = True
            def stop(s): s.on = False
            def isActive(s): return s.on

        class P(FauxProj):
            def __init__(s):
                super().__init__()
                s.pan = s.tilt = 32768
                s.uv = s.amber_boost = s.white_boost = s.orange_boost = 0
                s.gobo = s.zoom = 0
                s.channel_extras = {}
                s._manual_color = False

        class W:
            _recompute_memory_mix  = mw.MainWindow._recompute_memory_mix
            _mem_drive_effect      = mw.MainWindow._mem_drive_effect
            _compute_htp_overrides = mw.MainWindow._compute_htp_overrides
            _mem_ensure_cues       = mw.MainWindow._mem_ensure_cues
            _mem_active_cue        = mw.MainWindow._mem_active_cue
            _flash_level           = mw.MainWindow._flash_level

            _mem_flash_level       = mw.MainWindow._mem_flash_level
            def __init__(s):
                s._fader_map = [{"type": "memory", "mem_col": 0, "label": "MEM 1"}] + \
                               [{"type": "group", "group": g, "label": g} for g in "BCDEFGH"]
                s.faders = {i: F(0) for i in range(9)}
                s._muted_faders = set(); s._mem_ext_levels = {}
                s._mem_rows = {}; s._mem_cue_idx = {}
                s._mem_flash = None; s._flash_kind = None
                s._fade_timer = T()
                s.projectors = [P() for _ in range(3)]
                s.active_effect = None; s.active_effect_config = {}
                # La memoire du signalement : 3 PAR magenta, 83 / 83 / 79 %.
                s.memories = [[None] * 8 for _ in range(8)]
                s.memories[0][0] = {"cues": [{
                    "label": "Cue 1",
                    "projectors": [{"level": lv, "base_color": "#ff00ff",
                                    "pan": 32768, "tilt": 32768}
                                   for lv in (83, 83, 79)],
                    "effect": {}, "duration": 0}], "loop": True}
                s.active_memory_pads = {0: 0}

            def _fader_to_mem_col(s, i):
                sl = s._fader_map[i] if i < len(s._fader_map) else {}
                return sl.get("mem_col") if sl.get("type") == "memory" else None

            def _bank_memory_slots(s):
                return [(i, sl["mem_col"]) for i, sl in enumerate(s._fader_map)
                        if sl["type"] == "memory"]

            def _update_color_wheel(s, p, c): pass
            def stop_effect(s): pass
            def start_effect(s, n): pass

        return W()

    # Le balayage part de 2 % : a 1 %, 83 % x 1 % arrondit a 0: les projecteurs
    # sont alors VRAIMENT eteints, modele et sortie DMX compris. Rien a voir
    # avec le symptome, qui eteignait des fixtures a 100 % de fader.
    def test_aucune_position_de_fader_n_eteint_le_plan(self):
        w = self._monde()
        canvas = FauxCanvas(FauxPdf())
        eteints = []
        for fv in range(2, 101):
            w.faders[0].value = fv
            w._recompute_memory_mix()
            canvas.pdf._htp_overrides = w._compute_htp_overrides() or None
            for p in w.projectors:
                c = canvas._get_fill_color(p)
                self.assertTrue(c.isValid(), f"couleur invalide a {fv} %")
                if c.name() in ("#000000", "#1a1a1a"):
                    eteints.append((fv, p.level))
        self.assertEqual(eteints, [],
                         "le plan 2D doit rester allume sur toute la course du fader")

    def test_la_montee_reste_monotone(self):
        """Pas de saut en arriere : c'est ce qui se voyait comme un strobe."""
        w = self._monde()
        canvas = FauxCanvas(FauxPdf())
        suite = []
        for fv in range(2, 101):
            w.faders[0].value = fv
            w._recompute_memory_mix()
            canvas.pdf._htp_overrides = w._compute_htp_overrides() or None
            suite.append(canvas._get_fill_color(w.projectors[0]).red())
        self.assertEqual(suite, sorted(suite), "la montee doit etre monotone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
