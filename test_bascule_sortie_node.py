"""Trouver le boitier ne suffit pas : encore faut-il lui PARLER.

L'assistant annoncait « Connexion etablie » sans jamais basculer la sortie DMX :
MyStrow continuait d'emettre sur le dongle USB (COM4) pendant que l'ecran
affichait un succes. Voyant DMX du node eteint, projecteurs muets.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import node_connection as N
from artnet_dmx import TRANSPORT_ARTNET


class _FauxDmx:
    def __init__(self, ouvre=True):
        self._ouvre = ouvre
        self.connected = False
        self.appels = []

    def connect(self, **kw):
        self.appels.append(kw)
        self.connected = self._ouvre


class TestBasculeSortie(unittest.TestCase):

    def test_instance_explicite_est_utilisee(self):
        dmx = _FauxDmx()
        self.assertTrue(N._pointer_mystrow_sur("2.0.0.1", dmx))
        self.assertEqual(len(dmx.appels), 1)
        self.assertEqual(dmx.appels[0]["target_ip"], "2.0.0.1")
        self.assertEqual(dmx.appels[0]["transport"], TRANSPORT_ARTNET)

    def test_sans_instance_et_sans_hook_echoue_franchement(self):
        # Cas reel de l'assistant : personne n'avait injecte _dmx_instance.
        import artnet_dmx as adm
        avait = hasattr(adm, "_dmx_instance")
        ancien = getattr(adm, "_dmx_instance", None)
        if avait:
            del adm._dmx_instance
        try:
            self.assertFalse(N._pointer_mystrow_sur("2.0.0.1"),
                             "sans moteur joignable, on ne peut pas pretendre avoir bascule")
        finally:
            if avait:
                adm._dmx_instance = ancien

    def test_connexion_qui_echoue_nest_pas_un_succes(self):
        # `connect()` peut ne rien lever et pourtant ne rien ouvrir : c'est
        # `connected` qui fait foi, pas l'absence d'exception.
        dmx = _FauxDmx(ouvre=False)
        self.assertFalse(N._pointer_mystrow_sur("2.0.0.1", dmx))

    def test_exception_est_un_echec(self):
        class _Casse:
            connected = False
            def connect(self, **kw):
                raise OSError(50, "Cette demande n'est pas prise en charge")
        self.assertFalse(N._pointer_mystrow_sur("2.0.0.1", _Casse()))

    def test_messages_dedies_existent(self):
        from i18n import tr
        for cle in ("nc_found_but_not_switched", "nc_switch_steps"):
            self.assertNotEqual(tr(cle), cle, f"cle i18n manquante : {cle}")
        self.assertIn("2.0.0.1", tr("nc_switch_steps").format(ip="2.0.0.1"))



class TestIpNodeDecouverte(unittest.TestCase):
    """L'IP du node ne doit jamais etre supposee : l'UI n'offre aucun champ
    pour la corriger, donc une constante fausse enferme l'utilisateur."""

    def setUp(self):
        self._disc = N._artpoll_discover
        self._ping = N._ping
        N._ping = lambda ip, timeout_ms=1000: False

    def tearDown(self):
        N._artpoll_discover = self._disc
        N._ping = self._ping

    def test_node_decouvert_gagne_sur_la_constante(self):
        N._artpoll_discover = lambda t=1.2: (
            [{"ip": "2.0.0.1", "court": "", "long": ""}], True)
        class D: target_ip = "2.0.0.15"
        self.assertEqual(N._ip_node_a_viser(D()), "2.0.0.1")

    def test_adresse_retenue_conservee_si_elle_repond(self):
        N._artpoll_discover = lambda t=1.2: ([], True)
        N._ping = lambda ip, timeout_ms=1000: ip == "2.0.0.7"
        class D: target_ip = "2.0.0.7"
        self.assertEqual(N._ip_node_a_viser(D()), "2.0.0.7")

    def test_repli_sur_le_defaut(self):
        N._artpoll_discover = lambda t=1.2: ([], True)
        class D: target_ip = ""
        self.assertEqual(N._ip_node_a_viser(D()), N.TARGET_IP)

    def test_adresse_hors_reseau_node_ignoree(self):
        N._artpoll_discover = lambda t=1.2: ([], True)
        N._ping = lambda ip, timeout_ms=1000: True
        class D: target_ip = "192.168.1.50"
        self.assertEqual(N._ip_node_a_viser(D()), N.TARGET_IP)
if __name__ == "__main__":
    unittest.main(verbosity=2)
