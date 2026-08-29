"""Detection de la carte reseau du boitier, et message adapte au branchement.

Un USB NODE n'a PAS de prise RJ45 : la carte reseau, c'est le boitier lui-meme.
Reclamer un cable RJ45 quand le client vient de repondre « une seule prise USB »
l'envoie chercher une panne qui n'existe pas.
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


class TestDetectionCarte(unittest.TestCase):

    def setUp(self):
        self._win = N._get_ethernet_adapters_windows
        self._drv = N._get_adapters_via_driver
        self._sys = N.platform.system

    def tearDown(self):
        N._get_ethernet_adapters_windows = self._win
        N._get_adapters_via_driver = self._drv
        N.platform.system = self._sys

    def test_repli_pilote_quand_ipconfig_ne_voit_rien(self):
        # TCP/IPv4 decoche, ou carte fraichement enumeree : absente d'ipconfig,
        # mais bien presente au niveau pilote.
        N.platform.system = lambda: "Windows"
        N._get_ethernet_adapters_windows = lambda: []
        N._get_adapters_via_driver = lambda: [
            ("Ethernet 4", "", "Electroconcept USB Node", True)]
        cartes = N._get_ethernet_adapters()
        self.assertEqual(len(cartes), 1,
                         "la carte vue par le pilote doit remonter")
        self.assertEqual(cartes[0][0], "Ethernet 4")
        self.assertEqual(cartes[0][1], "", "sans pile IP, l'adresse reste vide")

    def test_ipconfig_prioritaire(self):
        N.platform.system = lambda: "Windows"
        N._get_ethernet_adapters_windows = lambda: [
            ("Ethernet 4", "2.0.0.2", "UsbNcm", True)]
        appele = []
        N._get_adapters_via_driver = lambda: appele.append(1) or []
        cartes = N._get_ethernet_adapters()
        self.assertEqual(cartes[0][1], "2.0.0.2")
        self.assertFalse(appele, "le repli ne doit pas couter un PowerShell pour rien")

    def test_repli_ignore_le_wifi(self):
        # _SKIP_ADAPTERS doit filtrer aussi dans le repli, sinon la Wi-Fi
        # revient polluer la liste par la porte de derriere.
        self.assertNotIn(
            "wi-fi",
            [n.lower() for n, _ip, _d, _c in N._get_adapters_via_driver()])

    def test_message_usb_ne_parle_pas_de_rj45(self):
        msg = tr("nc_no_ethernet_usb")
        self.assertNotIn("RJ45", msg.upper())
        self.assertIn("USB", msg.upper())
        self.assertIn("RJ45", tr("nc_no_ethernet").upper(),
                      "la variante reseau, elle, doit bien parler du RJ45")


if __name__ == "__main__":
    unittest.main(verbosity=2)
