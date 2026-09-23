"""
test_patch_snapshot_3d.py — Fenetre Patch : Ctrl+Z / « Ignorer » effacaient le
placement 3D.

`_restore_snap` recree les Projector de zero. Il restaurait la zone pan/tilt et
la matrice, pas le placement 3D : H repartait a 7 m, RX/RY/RZ a 0. Signale par
un client (23/09/2026) apres avoir ferme la fenetre Patch sans enregistrer.
"""

import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main_window as mw
from projector import Projector

_ICI = os.path.dirname(os.path.abspath(__file__))


class TestAllerRetour(unittest.TestCase):

    def _lyre(self):
        p = Projector("A", name="LYRE-1", fixture_type="Moving Head")
        p.pos_3d_x, p.pos_3d_z, p.fixture_height = 218.0, -271.0, 233.0
        p.body_rotation, p.rot3d_x, p.rot3d_z = 180.0, 0.0, 0.0
        p.beam_angle, p.fixture_scale = 80.0, 120.0
        p._pos3d_src = None           # placement manuel
        return p

    def test_placement_restaure(self):
        src = self._lyre()
        neuve = Projector("A", name="LYRE-1", fixture_type="Moving Head")
        mw._apply_scene3d_meta(neuve, mw._scene3d_meta(src))
        for f in mw._SCENE3D_META_FIELDS:
            self.assertEqual(getattr(neuve, f), getattr(src, f), f)
        self.assertTrue(hasattr(neuve, "_pos3d_src"))
        self.assertIsNone(neuve._pos3d_src)

    def test_provenance_absente_reste_absente(self):
        src = Projector("A", name="PAR", fixture_type="PAR LED")
        if hasattr(src, "_pos3d_src"):
            del src._pos3d_src
        neuve = Projector("A", name="PAR", fixture_type="PAR LED")
        mw._apply_scene3d_meta(neuve, mw._scene3d_meta(src))
        self.assertFalse(hasattr(neuve, "_pos3d_src"))

    def test_champs_alignes_sur_la_sauvegarde(self):
        """Tout champ 3D du fichier patch doit etre dans le snapshot."""
        src = open(os.path.join(_ICI, "main_window.py"), encoding="utf-8").read()
        corps = src[src.index("def _fixture_to_config"):
                    src.index("def _projector_from_config")]
        for f in ("pos_3d_x", "pos_3d_z", "fixture_height", "body_rotation",
                  "rot3d_x", "rot3d_z", "beam_gain", "beam_angle", "fixture_scale"):
            self.assertIn(f"'{f}'", corps)
            self.assertIn(f, mw._SCENE3D_META_FIELDS)

    def test_restore_snap_branche(self):
        src = open(os.path.join(_ICI, "main_window.py"), encoding="utf-8").read()
        corps = src[src.index("def _restore_snap(snap):"):src.index("def _undo():")]
        self.assertIn("_apply_scene3d_meta(p, fd_s.get('_3d'))", corps)
        self.assertEqual(len(re.findall(r"entry\['_3d'\] = _scene3d_meta\(p\)", src)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
