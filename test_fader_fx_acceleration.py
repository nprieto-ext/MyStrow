"""
Fader FX (VITESSE) : à fond, un effet à couches doit pouvoir aller PLUS VITE que
sa vitesse d'origine. Avant, le fader ne faisait que ralentir (×1 au sommet) :
« même en vitesse à fond l'effet reste relativement lent » (FuraxX, 15/11/2026).

Garanties :
- jusqu'à 80 (valeur par défaut), la courbe est IDENTIQUE à l'ancienne ;
- au-delà, elle monte de façon continue jusqu'à ×2,5 ;
- la tablette (mobile/src/engine.js, fxFaderMult) suit la même courbe.
"""
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import fx_fader_mult, FX_FADER_MAX_MULT

ENGINE_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "mobile", "src", "engine.js")


class TestCourbe(unittest.TestCase):

    def test_inchange_jusqu_au_coude(self):
        for v in range(1, 81):
            self.assertAlmostEqual(fx_fader_mult(v), max(0.01, v / 100.0), places=9)

    def test_zero_garde_le_plancher(self):
        self.assertEqual(fx_fader_mult(0), 0.01)

    def test_a_fond_plus_rapide_que_l_origine(self):
        self.assertAlmostEqual(fx_fader_mult(100), FX_FADER_MAX_MULT)
        self.assertGreater(fx_fader_mult(100), 1.0)

    def test_continue_et_croissante(self):
        prev = fx_fader_mult(0)
        for v in range(1, 101):
            cur = fx_fader_mult(v)
            self.assertGreaterEqual(cur, prev)
            self.assertLess(cur - prev, 0.1, f"saut a {v}")
            prev = cur

    def test_bornes(self):
        self.assertEqual(fx_fader_mult(150), fx_fader_mult(100))
        self.assertEqual(fx_fader_mult(-5), fx_fader_mult(0))
        self.assertEqual(fx_fader_mult(None), fx_fader_mult(0))


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestPariteTablette(unittest.TestCase):

    def test_meme_courbe_que_le_pc(self):
        vals = list(range(0, 101, 5)) + [81, 99]
        script = (f"const E=require({ENGINE_JS!r});"
                  f"console.log(JSON.stringify({vals}.map(E.fxFaderMult)))")
        out = subprocess.run(["node", "-e", script], capture_output=True,
                             text=True, check=True).stdout
        import json
        for v, js in zip(vals, json.loads(out)):
            self.assertAlmostEqual(js, fx_fader_mult(v), places=9, msg=f"fader {v}")


if __name__ == "__main__":
    unittest.main()
