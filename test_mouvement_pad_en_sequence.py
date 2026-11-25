"""Mouvement enregistré sur un pad, rejoué en séquence (artifice81, 20/11/2026).

« Quand j'enregistre un mouvement [...] dès que je le mets dans Effet, le
mouvement ne s'exécute pas ou bug (il ne balaie pas comme prévu). »

Cause : REC → pad FX jetait le centre autour duquel tournaient les lyres. Sur
le pad, l'effet tourne autour de l'endroit où elles sont déjà ; en REC Lumière
(et dans l'éditeur), autour d'une autre position — le repos. Le centre est
maintenant gardé DANS la couche (`centers`) et lu par les moteurs
(`core.layer_rec_centers`). Le look (couleur, gobo) suit l'effet en séquence.

    python -m unittest test_mouvement_pad_en_sequence
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from core import layer_rec_centers
import main_window as mw
import effect_editor

_app = QApplication.instance() or QApplication(sys.argv)
M = mw.MainWindow


class Lyre:
    def __init__(self, g):
        self.group = g
        self.fixture_type = "Moving Head"
        self.dmx_profile = ["Pan", "Tilt", "Dim", "R", "G", "B"]
        self.base_color = QColor("#ffffff")
        self.color = QColor("#ffffff")
        self.level = 100
        self.pan = self.tilt = 32768
        self.white_boost = self.amber_boost = self.uv = 0
        self.color_wheel = self.gobo = self.zoom = 0
        self.color_wheel_slots = []


class FauxWin:
    _update_effect_from_layers = M._update_effect_from_layers
    _note_fx_move_center = M._note_fx_move_center
    _update_color_wheel = M._update_color_wheel
    _GENERIC_WHEEL_SLOTS = M._GENERIC_WHEEL_SLOTS
    _fx_pantilt = M._fx_pantilt
    _pantilt_in_limits = M._pantilt_in_limits

    def __init__(self, projs):
        self.projectors = projs
        self.effect_speed = 100
        self.effect_t0 = 0.0
        self.effect_saved_colors = {}
        self._effect_clock = 0.0
        self._effect_clock_ts = None
        self.position_presets = []
        self._timeline_pos_centers = {}


def _couche(centres=None):
    lay = {"attribute": "Pan/Tilt", "forme": "Sinus", "speed": 50, "size": 10,
           "spread": 0, "phase": 0, "fade": 0, "direction": 1,
           "mouvement_shape": "cercle",
           "target_preset": "Selection",
           "target_selection": [["lat", 0], ["lat", 1]], "target_groups": []}
    if centres:
        lay["centers"] = centres
    return lay


def _trajet(w, cfg, n=40):
    """Pan/tilt de chaque lyre sur un tour (horloge simulée)."""
    pts = {id(p): [] for p in w.projectors}
    for k in range(n):
        with mock.patch("time.monotonic", return_value=k * 0.05):
            w._update_effect_from_layers(cfg)
        for p in w.projectors:
            pts[id(p)].append((p.pan, p.tilt))
    return pts


def _milieu(pts):
    pans = [a for a, _ in pts]
    tilts = [b for _, b in pts]
    return ((max(pans) + min(pans)) / 2, (max(tilts) + min(tilts)) / 2)


class T(unittest.TestCase):
    def test_helper_cle_groupe_index(self):
        projs = [Lyre("lat"), Lyre("lat"), Lyre("contre")]
        c = layer_rec_centers({"centers": {"lat|1": [20000, 40000]}}, projs)
        self.assertEqual(c, {id(projs[1]): (20000, 40000)})
        self.assertEqual(layer_rec_centers({}, projs), {})

    def test_le_mouvement_tourne_autour_du_centre_enregistre(self):
        projs = [Lyre("lat"), Lyre("lat")]
        w = FauxWin(projs)
        cfg = {"layers": [_couche({"lat|0": [20000, 40000],
                                   "lat|1": [45000, 28000]})]}
        pts = _trajet(w, cfg)
        for p, attendu in zip(projs, [(20000, 40000), (45000, 28000)]):
            cx, cy = _milieu(pts[id(p)])
            self.assertAlmostEqual(cx, attendu[0], delta=1500)
            self.assertAlmostEqual(cy, attendu[1], delta=1500)

    def test_sans_centre_comportement_inchange(self):
        projs = [Lyre("lat"), Lyre("lat")]
        a = _trajet(FauxWin(projs), {"layers": [_couche()]})
        projs2 = [Lyre("lat"), Lyre("lat")]
        b = _trajet(FauxWin(projs2), {"layers": [_couche()]})
        self.assertEqual(list(a.values()), list(b.values()))

    def test_editeur_garde_le_centre(self):
        d = _couche({"lat|0": [20000, 40000]})
        lay = effect_editor.EffectLayer.from_dict(d)
        self.assertEqual(lay.to_dict()["centers"], {"lat|0": [20000, 40000]})
        self.assertNotIn("centers", effect_editor.EffectLayer.from_dict(_couche()).to_dict())


if __name__ == "__main__":
    unittest.main(verbosity=2)
