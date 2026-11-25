"""Barre LED à Tilt motorisé : la 3D doit la faire basculer.

Retour Hypno Mat (Discord, 20/11/2026) : « dommage que les barres LED ne
bougent toujours pas sur la 3D ». Les vraies barres bougent (LIVE, via
`core.fixture_motor_only`), mais la 3D les dessinait fixes : `_barQuat` ne
lisait que le RX réglé dans le plan. `_to_data` envoie désormais `motor_tilt`
(degrés), porté par le master d'une barre à pixels et recopié sur toute la
barre ; `plan_3d_web.html` l'ajoute au RX.
"""
import types

from PySide6.QtWidgets import QApplication

import plan_3d_webwindow as w
from projector import Projector

_app = QApplication.instance() or QApplication([])


def _cls():
    return next(c for c in vars(w).values()
                if isinstance(c, type) and '_to_data' in vars(c))


def _to_data(projs):
    cls = _cls()
    fake = types.SimpleNamespace(mw=None, _mw=None, _fx_overrides={})
    for n in dir(cls):
        if n.startswith('_') and not n.startswith('__') and callable(getattr(cls, n)):
            setattr(fake, n, types.MethodType(getattr(cls, n), fake))
    return cls._to_data(fake, projs)


def _mk(kind, prof, mid=None, role=None, tilt=32768, idx=None):
    p = Projector('face', kind)
    p.fixture_type = kind
    p.dmx_profile = prof
    p.matrix_id, p.matrix_role = mid, role
    p.tilt, p.level = tilt, 100
    if idx is not None:
        p.pixel_index = idx
    return p


def test_barre_pixels_tilt_du_master_sur_toute_la_barre():
    projs = [_mk('Barre LED', ['Tilt', 'Speed'], 'B1', 'master', tilt=0)]
    projs += [_mk('Barre LED', ['R', 'G', 'B', 'W'], 'B1', 'pixel', idx=k)
              for k in range(4)]
    out = _to_data(projs)
    angles = {e['motor_tilt'] for e in out}
    assert len(angles) == 1 and next(iter(angles)) > 0


def test_barre_simple_et_centre():
    out = _to_data([_mk('Barre LED', ['Tilt', 'R', 'G', 'B'], tilt=65535),
                    _mk('Barre LED', ['Tilt', 'R', 'G', 'B'], tilt=32768)])
    assert out[0]['motor_tilt'] < 0
    assert out[1]['motor_tilt'] == 0


def test_sans_moteur_rien_ne_change():
    out = _to_data([_mk('Barre LED', ['R', 'G', 'B']),
                    _mk('PAR LED', ['R', 'G', 'B']),
                    _mk('Moving Head', ['Pan', 'Tilt', 'Dim'])])
    assert [e['motor_tilt'] for e in out] == [None, None, None]
