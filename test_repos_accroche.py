"""Repos des lyres selon l'accroche (RX du plan 3D / « Accroche » du patch).

Retour utilisateur 19/11/2026 : le balancier « en regardant le plafond ».
Le repos 32768/32768 vise dans l'axe du socle : le plafond pour une lyre
posée au sol. `core.rest_pantilt` le déduit de l'accroche.
"""
import unittest
from types import SimpleNamespace

from core import rest_pantilt, mount_is_hung
from light_actions import beam_dir


def _lyre(rx=0.0, **kw):
    d = dict(rot3d_x=rx, body_rotation=0.0, rot3d_z=0.0, pan_range=540, tilt_range=270,
             pan_min=0, pan_max=65535, tilt_min=0, tilt_max=65535,
             fixture_type='Moving Head', pan=32768, tilt=32768)
    d.update(kw)
    return SimpleNamespace(**d)


class TestRepos(unittest.TestCase):
    def test_accrochee_repos_historique(self):
        for rx in (0.0, None, 30.0, -20.0, 360.0):
            self.assertEqual(rest_pantilt(_lyre(rx)), (32768, 32768), rx)

    def test_posee_ne_vise_plus_le_plafond(self):
        p = _lyre(180.0)
        self.assertFalse(mount_is_hung(p))
        pan, tilt = rest_pantilt(p)
        dx, dy, dz = beam_dir(p, pan, tilt)
        self.assertLess(dy, 0.8)      # pas à la verticale
        self.assertGreater(dy, 0.0)   # au-dessus de l'horizontale
        self.assertLess(dz, 0.0)      # côté public (Z négatifs)

    def test_repos_dans_la_zone(self):
        p = _lyre(180.0, tilt_min=30000, tilt_max=40000)
        _pan, tilt = rest_pantilt(p)
        self.assertTrue(30000 <= tilt <= 40000)


class _FauxMW:
    from main_window import MainWindow as _MW
    _sync_rest_positions = _MW._sync_rest_positions

    def __init__(self, projs):
        self.projectors = projs


class TestSynchro(unittest.TestCase):
    def test_lyre_jamais_touchee_suit_l_accroche(self):
        p = _lyre(180.0)
        mw = _FauxMW([p])
        mw._sync_rest_positions()
        self.assertEqual((p.pan, p.tilt), rest_pantilt(p))
        # Retour à « accrochée » : elle revient au repos historique.
        p.rot3d_x = 0.0
        mw._sync_rest_positions()
        self.assertEqual((p.pan, p.tilt), (32768, 32768))

    def test_lyre_positionnee_jamais_deplacee(self):
        p = _lyre(0.0, pan=12000, tilt=45000)
        mw = _FauxMW([p])
        mw._sync_rest_positions()
        p.rot3d_x = 180.0
        mw._sync_rest_positions()
        self.assertEqual((p.pan, p.tilt), (12000, 45000))

    def test_accrochee_aucun_changement(self):
        p = _lyre(0.0)
        _FauxMW([p])._sync_rest_positions()
        self.assertEqual((p.pan, p.tilt), (32768, 32768))


if __name__ == "__main__":
    unittest.main()
