"""La decouverte doit atteindre le node quelle que soit la carte qui y mene.

Deux regressions croisees, constatees sur materiel :

1. Sous Windows, un broadcast emis depuis un socket lie a INADDR_ANY ne sort
   que par la carte de la route par defaut. Sur un PC qui a aussi une carte
   Internet, le node du spectacle ne recevait jamais l'ArtPoll.
2. Le USB NODE ignore l'ArtPoll unicast ; le NODE RJ45, lui, n'etait joint que
   par l'unicast (qui suit la table de routage). Ne garder QUE le broadcast a
   repare le premier en cassant le second.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import node_connection as N


class TestDecouverteMultiInterface(unittest.TestCase):

    def setUp(self):
        self._sur = N._artpoll_sur
        self._ips = N._ips_locales_pour_emettre
        self.appels = []

    def tearDown(self):
        N._artpoll_sur = self._sur
        N._ips_locales_pour_emettre = self._ips

    def _brancher(self, reponses):
        """reponses : {ip_source: [nodes]}"""
        def faux(source, timeout, cibles):
            self.appels.append((source, tuple(cibles)))
            return list(reponses.get(source, [])), True
        N._artpoll_sur = faux

    def test_emet_depuis_la_carte_du_node_pas_seulement_inaddr_any(self):
        N._ips_locales_pour_emettre = lambda: ["2.0.0.1", "192.168.1.242", ""]
        self._brancher({"2.0.0.1": [{"ip": "2.0.0.15", "court": "", "long": "Node 2"}]})
        nodes, fiable = N._artpoll_discover(timeout=1.5)
        self.assertTrue(fiable)
        self.assertEqual([n["ip"] for n in nodes], ["2.0.0.15"])
        self.assertEqual(self.appels[0][0], "2.0.0.1",
                         "la carte du reseau du boitier doit etre essayee EN PREMIER")

    def test_unicast_et_broadcast_sont_tous_deux_emis(self):
        N._ips_locales_pour_emettre = lambda: [""]
        self._brancher({})
        N._artpoll_discover(timeout=1.0)
        cibles = self.appels[0][1]
        self.assertIn("255.255.255.255", cibles, "le USB NODE n'entend que le broadcast")
        self.assertIn(N.TARGET_IP, cibles, "le NODE RJ45 n'etait joint que par l'unicast")

    def test_candidats_supplementaires_ajoutes(self):
        N._ips_locales_pour_emettre = lambda: [""]
        self._brancher({})
        N._artpoll_discover(timeout=1.0, candidats=("2.0.0.42",))
        self.assertIn("2.0.0.42", self.appels[0][1])

    def test_arret_des_qu_un_node_est_vu_sur_le_reseau_2x(self):
        N._ips_locales_pour_emettre = lambda: ["2.0.0.1", "192.168.1.242", ""]
        self._brancher({"2.0.0.1": [{"ip": "2.0.0.15", "court": "", "long": ""}]})
        N._artpoll_discover(timeout=1.5)
        self.assertEqual(len(self.appels), 1,
                         "inutile de balayer les autres cartes une fois trouve")

    def test_poursuit_si_la_premiere_carte_ne_donne_rien(self):
        N._ips_locales_pour_emettre = lambda: ["2.0.0.1", ""]
        self._brancher({"": [{"ip": "10.0.0.9", "court": "", "long": ""}]})
        nodes, _f = N._artpoll_discover(timeout=1.5)
        self.assertEqual([n["ip"] for n in nodes], ["10.0.0.9"])
        self.assertEqual(len(self.appels), 2)

    def test_doublons_fusionnes(self):
        N._ips_locales_pour_emettre = lambda: ["192.168.1.242", ""]
        meme = [{"ip": "10.0.0.9", "court": "", "long": ""}]
        self._brancher({"192.168.1.242": meme, "": meme})
        nodes, _f = N._artpoll_discover(timeout=1.5)
        self.assertEqual(len(nodes), 1, "un meme node vu deux fois ne compte qu'une fois")


if __name__ == "__main__":
    unittest.main(verbosity=2)
