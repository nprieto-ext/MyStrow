"""Une enumeration de cartes en echec ne doit pas paralyser la recherche du node.

Sur la machine de test, `_get_ethernet_adapters()` rendait [] depuis le processus
MyStrow alors que la carte existait. Le garde « aucune carte en 2.x » repondait
alors False AVANT tout ArtPoll : tout le parcours d'installation etait bloque par
un detail d'enumeration, alors que trouver le node prouve que la carte est la.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import node_connection as N


class TestProbeSansCarte(unittest.TestCase):

    def setUp(self):
        self._ada = N._get_ethernet_adapters
        self._disc = N._artpoll_discover
        self._ping = N._ping
        N._artpoll_discover = lambda timeout=1.5: (
            [{"ip": "2.0.0.1", "court": "USB NODE", "long": "Electroconcept USB NODE"}], True)
        N._ping = lambda ip, timeout_ms=1000: False

    def tearDown(self):
        N._get_ethernet_adapters = self._ada
        N._artpoll_discover = self._disc
        N._ping = self._ping

    def test_enumeration_en_echec_cherche_quand_meme(self):
        N._get_ethernet_adapters = lambda: []
        self.assertTrue(N._artpoll_probe("2.0.0.1"),
                        "liste vide = « on n'a pas su regarder », pas « rien »")

    def test_cartes_connues_mais_aucune_en_2x_coupe_court(self):
        N._get_ethernet_adapters = lambda: [("Wi-Fi", "192.168.1.10", "", True)]
        self.assertFalse(N._artpoll_probe("2.0.0.1"),
                         "le raccourci reste valable quand l'enumeration a reussi")

    def test_carte_en_2x_cherche(self):
        N._get_ethernet_adapters = lambda: [("Ethernet 4", "2.0.0.2", "", True)]
        self.assertTrue(N._artpoll_probe("2.0.0.1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
