"""Le panneau « Sortie DMX » doit refleter la REALITE, pas la constante.

Le boitier repond en 2.0.0.1 et pilote le spectacle, mais le panneau affichait
« boitier non connecte » parce qu'il ne sondait que TARGET_IP (2.0.0.15).
Et il montrait « Carte 2.0.0.2 » sans dire que c'est l'adresse du PC, juste
a cote de celle du node : deux 2.x qu'on confond au premier coup d'oeil.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import node_connection as N
from i18n import tr


class _Dmx:
    def __init__(self, ip):
        self.target_ip = ip


def _run_sync(det):
    """Execute la logique du QThread sans demarrer de thread."""
    recu = []
    det.finished = type("S", (), {"emit": lambda _s, v: recu.append(v)})()
    N._QuickDetector.run(det)
    return recu[0], det.found_ip


class TestDetectionRapide(unittest.TestCase):

    def setUp(self):
        self._probe, self._disc, self._ping = (
            N._artpoll_probe, N._artpoll_discover, N._ping)
        N._ping = lambda ip, timeout_ms=1000: False
        N._artpoll_probe = lambda ip, timeout=1.0: False
        N._artpoll_discover = lambda timeout=1.0: ([], True)

    def tearDown(self):
        N._artpoll_probe, N._artpoll_discover, N._ping = (
            self._probe, self._disc, self._ping)

    def _det(self, dmx):
        d = N._QuickDetector.__new__(N._QuickDetector)
        d._dmx = dmx
        d.found_ip = ""
        return d

    def test_boitier_a_son_adresse_usine_est_vu_connecte(self):
        N._artpoll_discover = lambda timeout=1.0: (
            [{"ip": "2.0.0.1", "court": "", "long": ""}], True)
        ok, ip = _run_sync(self._det(_Dmx("2.0.0.15")))
        self.assertTrue(ok, "un boitier qui pilote le show ne doit pas etre dit absent")
        self.assertEqual(ip, "2.0.0.1")

    def test_adresse_visee_prioritaire(self):
        N._artpoll_probe = lambda ip, timeout=1.0: ip == "2.0.0.1"
        N._artpoll_discover = lambda timeout=1.0: (
            [{"ip": "2.0.0.9", "court": "", "long": ""}], True)
        ok, ip = _run_sync(self._det(_Dmx("2.0.0.1")))
        self.assertTrue(ok)
        self.assertEqual(ip, "2.0.0.1", "pas de bascule quand l'adresse en cours repond")

    def test_aucun_boitier(self):
        ok, ip = _run_sync(self._det(_Dmx("2.0.0.15")))
        self.assertFalse(ok)
        self.assertEqual(ip, "")

    def test_sans_dmx_retombe_sur_le_defaut(self):
        N._artpoll_probe = lambda ip, timeout=1.0: ip == N.TARGET_IP
        ok, ip = _run_sync(self._det(None))
        self.assertTrue(ok)
        self.assertEqual(ip, N.TARGET_IP)


class TestLibelleCarte(unittest.TestCase):

    def test_l_ip_du_pc_est_identifiee(self):
        txt = tr("nc_adapter_this_pc").format(carte="2.0.0.2")
        self.assertIn("2.0.0.2", txt)
        self.assertNotEqual(txt, "2.0.0.2",
                            "l'IP seule se confond avec celle du boitier")


if __name__ == "__main__":
    unittest.main(verbosity=2)
