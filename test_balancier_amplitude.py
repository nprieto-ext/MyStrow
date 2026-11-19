"""Balancier (pan seul) : pas de réduction par le ratio angulaire.

Retour utilisateur 19/11/2026 : « le balancier ne fait que des minuscules
mouvements ». `pan_angular_ratio` (0,5 sur une 540/270) ne sert qu'à garder
un cercle rond ; une forme à un seul axe ne doit pas le subir.
"""
import io
import os
import unittest
from types import SimpleNamespace

from core import pt_shape_pan_ratio, pan_angular_ratio

ICI = os.path.dirname(os.path.abspath(__file__))


def _lyre(pan=540, tilt=270):
    return SimpleNamespace(pan_range=pan, tilt_range=tilt)


class TestBalancier(unittest.TestCase):
    def test_pan_seul_pas_reduit(self):
        p = _lyre()
        self.assertEqual(pt_shape_pan_ratio(p, None), 1.0)
        self.assertEqual(pt_shape_pan_ratio(p, "Fixe"), 1.0)

    def test_cercle_garde_le_ratio(self):
        p = _lyre()
        self.assertEqual(pt_shape_pan_ratio(p, "Sinus"), pan_angular_ratio(p))

    def test_formes_balancier_pendule(self):
        from effect_editor import PAN_TILT_SHAPES
        self.assertIsNone(PAN_TILT_SHAPES["balancier"]["tilt"][0])

    def test_parite_tablette(self):
        js = io.open(os.path.join(ICI, "mobile", "src", "engine.js"), encoding="utf-8").read()
        self.assertIn('(!tiltForme || tiltForme === "Fixe") ? 1.0 : panRatio', js)
        self.assertIn("amplitude * ptPanRatio", js)


if __name__ == "__main__":
    unittest.main()
