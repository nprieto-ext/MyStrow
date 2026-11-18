"""Effets Pan/Tilt : la zone réglée dans le patch garde le motif intact (FuraxX 16/11/2026)."""
from types import SimpleNamespace as NS
from main_window import MainWindow as MW


def _amp(vals):
    return max(vals) - min(vals)


def test_sans_zone_calcul_historique():
    p = NS(pan_min=0, pan_max=65535, tilt_min=0, tilt_max=65535)
    for n in (-1, -0.3, 0, 0.7, 1):
        assert MW._fx_pantilt(p, 'tilt', 60000, n, 8192) == int(max(0, min(65535, 60000 + n * 8192)))


def test_centre_hors_zone_ne_colle_plus():
    # Lyre restée à 32768, zone tilt 40000-55000 : avant, tilt plaqué à 40000.
    p = NS(pan_min=0, pan_max=65535, tilt_min=40000, tilt_max=55000)
    vals = [MW._fx_pantilt(p, 'tilt', 32768, n / 10, 6000) for n in range(-10, 11)]
    assert min(vals) >= 40000 and max(vals) <= 55000
    assert _amp(vals) == 12000          # motif complet, plus d'écrêtage


def test_amplitude_plafonnee_a_la_zone():
    p = NS(pan_min=20000, pan_max=30000, tilt_min=0, tilt_max=65535)
    vals = [MW._fx_pantilt(p, 'pan', 25000, n / 10, 32768) for n in range(-10, 11)]
    assert min(vals) >= 20000 and max(vals) <= 30000 and _amp(vals) >= 9998


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_"):
            _f(); print("OK", _n)
