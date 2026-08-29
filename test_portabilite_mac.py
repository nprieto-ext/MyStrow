"""Portabilite macOS de la detection et de la connexion au boitier.

Le Mac n'a ni ipconfig ni PowerShell : tout ce qui repose sur eux doit avoir
une voie de secours, et les commandes partagees doivent utiliser la bonne
syntaxe. `ping -W` notamment s'exprime en MILLISECONDES sur macOS et en
SECONDES sur Linux.
"""
import os
import subprocess
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import node_connection as N


class TestPingMac(unittest.TestCase):

    def setUp(self):
        self._sys, self._run = N.platform.system, subprocess.run
        self.cmd = []
        N.platform.system = lambda: "Darwin"
        subprocess.run = lambda a, **k: (self.cmd.append(a),
                                         type("R", (), {"returncode": 0})())[1]

    def tearDown(self):
        N.platform.system, subprocess.run = self._sys, self._run

    def test_delai_en_millisecondes(self):
        N._ping("2.0.0.15", timeout_ms=1500)
        a = self.cmd[0]
        self.assertEqual(a[:3], ["ping", "-c", "1"])
        self.assertEqual(a[a.index("-W") + 1], "1500",
                         "macOS attend des millisecondes ; convertir en secondes "
                         "donnait un delai de 1 ms et faisait echouer tout ping")
        self.assertNotIn("creationflags", str(a), "pas de drapeau Windows sur Mac")


class TestDetectionMac(unittest.TestCase):

    def setUp(self):
        self._sys = N.platform.system
        self._mac = N._get_ethernet_adapters_mac
        self._sock = N._get_adapters_via_socket
        N.platform.system = lambda: "Darwin"

    def tearDown(self):
        N.platform.system = self._sys
        N._get_ethernet_adapters_mac = self._mac
        N._get_adapters_via_socket = self._sock

    def test_repli_socket_actif_sur_mac(self):
        N._get_ethernet_adapters_mac = lambda: []
        N._get_adapters_via_socket = lambda: [("Carte 2.0.0.1", "2.0.0.1", "", True)]
        cartes = N._get_ethernet_adapters()
        self.assertEqual(len(cartes), 1,
                         "sans ifconfig exploitable, le Mac doit aussi retomber "
                         "sur la detection par socket")
        self.assertEqual(cartes[0][1], "2.0.0.1")

    def test_ifconfig_prioritaire_sur_mac(self):
        N._get_ethernet_adapters_mac = lambda: [("en5", "2.0.0.1", "Ethernet", True)]
        appele = []
        N._get_adapters_via_socket = lambda: appele.append(1) or []
        cartes = N._get_ethernet_adapters()
        self.assertEqual(cartes[0][0], "en5")
        self.assertFalse(appele, "pas de repli inutile quand ifconfig repond")


class TestPortabiliteSockets(unittest.TestCase):
    """La decouverte Art-Net n'utilise que des sockets : rien a porter."""

    def test_pas_de_commande_windows_dans_la_decouverte(self):
        import inspect
        for fn in (N._artpoll_sur, N._artpoll_discover,
                   N._ips_locales_pour_emettre, N._get_adapters_via_socket,
                   N._ip_node_a_viser, N._pointer_mystrow_sur):
            src = inspect.getsource(fn)
            for interdit in ("powershell", "ipconfig", "netsh", "CREATE_NO_WINDOW"):
                self.assertNotIn(interdit, src,
                                 f"{fn.__name__} depend de {interdit}, non portable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
