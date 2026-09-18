"""
test_memoire_parametres_seuls.py — une memoire n'impose que ce qu'elle porte.

Remontee 18/09/2026 : « je fais un clear, mes projos sont en noir, je monte
juste le strob, je l'enregistre et la il me dit qu'il y a rien dedans », puis
« l'idee c'est que je puisse enregistrer n'importe quel parametre ».

Regle : chaque memoire levee n'impose que ses parametres HORS REPOS ; les
autres viennent des memoires levees avec elle (fader le plus haut d'abord).
Meme regle en live (pads) et en lecture REC Lumiere (clips Sequence).

    python test_memoire_parametres_seuls.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import light_timeline as lt
import test_flash_kill_reel as base

_app = QApplication.instance() or QApplication(sys.argv)


def _etat(**kw):
    e = {"level": 0, "base_color": "#000000", "pan": 32768, "tilt": 32768,
         "shutter": 255, "strobe_speed": 0, "gobo": 0, "uv": 0,
         "channel_extras": {}}
    e.update(kw)
    return e


def _cue(n, **kw):
    return {"label": "Cue 1", "effect": {}, "duration": 0,
            "projectors": [_etat(**kw) for _ in range(n)]}


class Composition(unittest.TestCase):
    def test_repos_non_impose(self):
        self.assertEqual(lt.compose_memory_params([_etat()]), ({}, {}))

    def test_chacun_ses_parametres(self):
        params, _ = lt.compose_memory_params(
            [_etat(strobe_speed=60), _etat(pan=1000, gobo=64)])
        self.assertEqual(params["strobe_speed"], (60, 0))
        self.assertEqual(params["pan"], (1000, 1))
        self.assertEqual(params["gobo"], (64, 1))
        self.assertNotIn("tilt", params)

    def test_le_plus_prioritaire_gagne(self):
        params, _ = lt.compose_memory_params([_etat(gobo=10), _etat(gobo=64)])
        self.assertEqual(params["gobo"], (10, 0))

    def test_canaux_bruts_fusionnes(self):
        _, extras = lt.compose_memory_params(
            [_etat(channel_extras={5: 200}), _etat(channel_extras={5: 1, 7: 9})])
        self.assertEqual(extras, {5: 200, 7: 9})


class Fenetre(base.FauxWin):
    """Look (MEM 1, fader 80) + memoire a un seul parametre (MEM 2, fader 100)."""

    def __init__(self, **seul):
        super().__init__(n_proj=2)
        self._fader_map.append({"type": "memory", "mem_col": 1, "label": "MEM 2"})
        self.faders[2] = base.FauxFader(100)
        look = self.memories[0][0]["cues"][0]
        for st in look["projectors"]:
            st.update(pan=10000, tilt=50000, gobo=64, uv=0, shutter=255)
        look["effect"] = {"name": "Vague", "layers": [{"x": 1}]}
        self.memories[1][0] = {"cues": [_cue(2, **seul)], "loop": True}


class Live(unittest.TestCase):
    def _mix(self, w, pads):
        w.active_memory_pads = pads
        w._recompute_memory_mix()
        return w.projectors

    def test_strobe_sur_look(self):
        w = Fenetre(strobe_speed=60)
        for p in self._mix(w, {0: 0, 2: 0}):
            self.assertEqual(p.strobe_speed, 60)
            self.assertGreater(p.level, 0, "le look reste allume")
            self.assertEqual((p.pan, p.tilt), (10000, 50000), "lyres pas recentrees")
            self.assertEqual(p.gobo, 64, "gobo du look garde")
        self.assertEqual(w.active_effect, "Vague", "l'effet du look tourne")

    def test_gobo_seul_sur_look(self):
        w = Fenetre(gobo=128)
        for p in self._mix(w, {0: 0, 2: 0}):
            self.assertEqual(p.gobo, 128)
            self.assertEqual((p.pan, p.tilt), (10000, 50000))
            self.assertGreater(p.level, 0)

    def test_position_seule_sur_look(self):
        w = Fenetre(tilt=20000)
        for p in self._mix(w, {0: 0, 2: 0}):
            self.assertEqual(p.tilt, 20000)
            self.assertEqual(p.pan, 10000, "pan du look garde (par axe)")
            self.assertEqual(p.gobo, 64)

    def test_uv_seul_scale_par_son_fader(self):
        w = Fenetre(uv=200)
        w.faders[2].value = 50
        for p in self._mix(w, {0: 0, 2: 0}):
            self.assertEqual(p.uv, 100)

    def test_baisser_la_surcouche_rend_le_look(self):
        w = Fenetre(strobe_speed=60, gobo=128)
        self._mix(w, {0: 0, 2: 0})
        w.faders[2].value = 0
        for p in self._mix(w, {0: 0, 2: 0}):
            self.assertEqual(p.strobe_speed, 0)
            self.assertEqual(p.gobo, 64)

    def test_seule_elle_n_allume_rien(self):
        w = Fenetre(strobe_speed=60)
        for p in self._mix(w, {2: 0}):
            self.assertEqual(p.level, 0)
            self.assertEqual(p.strobe_speed, 60)

    def test_look_seul_inchange(self):
        w = Fenetre(strobe_speed=60)
        for p in self._mix(w, {0: 0}):
            self.assertEqual(p.strobe_speed, 0)
            self.assertEqual(p.gobo, 64)
            self.assertEqual((p.pan, p.tilt), (10000, 50000))


class Proj:
    def __init__(self):
        self.level = 0
        self.base_color = self.color = QColor("black")
        self.pan = self.tilt = 32768
        self.strobe_speed = 0
        self.gobo = 0
        self.channel_extras = {}


class FauxMain:
    _fx_clip_ids = None


class RecLumiere(unittest.TestCase):
    def _jouer(self, *refs):
        mems = {"look": [_etat(level=100, base_color="#ff0000", pan=1000)],
                "strb": [_etat(strobe_speed=60)]}
        projs = [Proj()]
        vrai = lt.resolve_memory_projectors
        lt.resolve_memory_projectors = lambda ref, ci, m: m[ref]
        try:
            lt.apply_seq_memories_htp(
                [{"memory_ref": r, "brightness": 1.0} for r in refs],
                mems, projs, FauxMain())
        finally:
            lt.resolve_memory_projectors = vrai
        return projs[0]

    def test_strobe_seul_sur_look(self):
        p = self._jouer("look", "strb")
        self.assertEqual(p.strobe_speed, 60)
        self.assertEqual(p.level, 100)
        self.assertEqual(p.pan, 1000)

    def test_look_seul_strobe_eteint(self):
        p = self._jouer("look")
        p.strobe_speed = 99
        p = self._jouer("look")
        self.assertEqual(p.strobe_speed, 0)


if __name__ == "__main__":
    unittest.main()
