"""LIVE / IA : les motifs de lyres tournent autour de la position où on les a
laissées (client FuraxX, 13/11/2026), toujours dans leur zone autorisée.

- lyre jamais touchée (32768) : comportement d'avant au bit près ;
- lyre visée sur la piste : le motif tourne autour de ce point ;
- lyre re-visée pendant le LIVE : le centre suit ;
- près d'une butée : le motif est décalé vers l'intérieur, sans être écrasé.
"""
import sys, math, unittest
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
import main_window as mw

M = mw.MainWindow


class P:
    def __init__(s, pan=32768, tilt=32768):
        s.pan, s.tilt = pan, tilt
        s.pan_min, s.pan_max, s.tilt_min, s.tilt_max = 0, 65535, 0, 65535


class Win:
    _pantilt_in_limits = staticmethod(M._pantilt_in_limits)
    _live_anchor = M._live_anchor
    _live_set_pantilt = M._live_set_pantilt

    def __init__(s):
        s.logs = []

    def _log_message(s, t, k=None):
        s.logs.append(t)


def tour(w, p, amp=8000, n=36):
    """Un tour de cercle ; renvoie (min, max) du tilt."""
    tilts = []
    for k in range(n):
        ph = 2 * math.pi * k / n
        w._live_set_pantilt(p, math.sin(ph), math.cos(ph), amp, amp)
        tilts.append(p.tilt)
    return min(tilts), max(tilts)


class T(unittest.TestCase):
    def test_lyre_jamais_touchee_comme_avant(self):
        w, p = Win(), P()
        for norm in (-1.0, -0.3, 0.0, 0.7, 1.0):
            w._live_set_pantilt(p, norm, norm, 8000, 6000)
            self.assertEqual(p.pan, 32768 + int(norm * 8000))
            self.assertEqual(p.tilt, 32768 + int(norm * 6000))

    def test_tourne_autour_de_la_piste(self):
        w, p = Win(), P(tilt=54000)
        lo, hi = tour(w, p)
        self.assertAlmostEqual((lo + hi) / 2, 54000, delta=300)
        self.assertEqual(len(w.logs), 1)          # un seul message au journal

    def test_revisee_pendant_le_live(self):
        w, p = Win(), P(tilt=40000)
        tour(w, p)
        p.tilt = 56000                             # ciblage / pad / faisceau
        lo, hi = tour(w, p)
        self.assertAlmostEqual((lo + hi) / 2, 56000, delta=300)

    def test_ses_propres_ecritures_ne_deplacent_pas_le_centre(self):
        w, p = Win(), P(tilt=50000)
        for _ in range(5):
            lo, hi = tour(w, p, n=37)              # s'arrête en plein motif
        self.assertAlmostEqual((lo + hi) / 2, 50000, delta=300)

    def test_pres_de_la_butee_forme_gardee(self):
        w, p = Win(), P(tilt=64000)
        p.tilt_min, p.tilt_max = 40000, 65535
        lo, hi = tour(w, p, amp=8000)
        self.assertLessEqual(hi, 65535)
        self.assertAlmostEqual(hi - lo, 16000, delta=200)   # pas écrasé

    def test_zone_respectee(self):
        w, p = Win(), P(tilt=20000)                 # visée hors zone
        p.tilt_min, p.tilt_max = 45000, 60000
        lo, hi = tour(w, p)
        self.assertGreaterEqual(lo, 45000)
        self.assertLessEqual(hi, 60000)


if __name__ == "__main__":
    unittest.main()
