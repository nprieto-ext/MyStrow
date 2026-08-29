"""Le parcours doit aboutir quand le boitier est a son adresse d'usine.

Constat materiel (28/08/2026) : le boitier repond en 2.0.0.1, MyStrow cherchait
2.0.0.15, et un envoi direct vers 2.0.0.1 allume les projecteurs. Chercher
UNIQUEMENT TARGET_IP condamnait donc un boitier parfaitement fonctionnel.

Et une enumeration de cartes en echec (WinError 50 sur ipconfig ET PowerShell,
observe en production) ne doit plus rien condamner du tout.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import node_connection as N


class TestRechercheNode(unittest.TestCase):

    def setUp(self):
        self._sauv = {n: getattr(N, n) for n in
                      ("_get_ethernet_adapters", "_artpoll_probe",
                       "_artpoll_discover", "_ping")}
        N._ping = lambda ip, timeout_ms=1000: False
        N._artpoll_probe = lambda ip, timeout=1.5: False
        N._artpoll_discover = lambda timeout=1.5: ([], True)
        N._get_ethernet_adapters = lambda: [("Ethernet 4", "2.0.0.2", "", True)]

    def tearDown(self):
        for n, v in self._sauv.items():
            setattr(N, n, v)

    def _chercher(self):
        """Execute la logique du thread, sans thread."""
        t = N._NodeSearcher.__new__(N._NodeSearcher)
        resultats = []
        t.finished = type("S", (), {"emit": lambda _s, v: resultats.append(v)})()
        N._NodeSearcher.run.__wrapped__(t) if hasattr(N._NodeSearcher.run, "__wrapped__") \
            else N._NodeSearcher.run(t)
        return resultats[0], getattr(t, "found_ip", "")

    def test_boitier_a_son_adresse_usine_est_trouve(self):
        N._artpoll_discover = lambda timeout=1.5: (
            [{"ip": "2.0.0.1", "court": "USB NODE", "long": "Electroconcept USB NODE"}], True)
        trouve, ip = self._chercher()
        self.assertTrue(trouve, "un boitier en 2.0.0.1 doit conclure le parcours")
        self.assertEqual(ip, "2.0.0.1")

    def test_enumeration_en_echec_ne_condamne_rien(self):
        N._get_ethernet_adapters = lambda: []       # WinError 50 sur tout
        N._artpoll_discover = lambda timeout=1.5: (
            [{"ip": "2.0.0.1", "court": "", "long": ""}], True)
        trouve, ip = self._chercher()
        self.assertTrue(trouve)
        self.assertEqual(ip, "2.0.0.1")

    def test_adresse_attendue_prioritaire(self):
        N._artpoll_probe = lambda ip, timeout=1.5: ip == N.TARGET_IP
        N._artpoll_discover = lambda timeout=1.5: (
            [{"ip": "2.0.0.9", "court": "", "long": ""}], True)
        trouve, ip = self._chercher()
        self.assertTrue(trouve)
        self.assertEqual(ip, N.TARGET_IP, "pas de bascule inutile si l'adresse visee repond")

    def test_aucun_boitier(self):
        trouve, ip = self._chercher()
        self.assertFalse(trouve)
        self.assertEqual(ip, "")

    def test_cartes_connues_sans_2x_coupe_court(self):
        N._get_ethernet_adapters = lambda: [("Wi-Fi", "192.168.1.10", "", True)]
        N._artpoll_discover = lambda timeout=1.5: (
            [{"ip": "2.0.0.1", "court": "", "long": ""}], True)
        trouve, _ip = self._chercher()
        self.assertFalse(trouve, "aucune route vers le 2.x : inutile d'attendre")


if __name__ == "__main__":
    unittest.main(verbosity=2)
