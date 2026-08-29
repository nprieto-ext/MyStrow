"""Le scan de cartes doit attendre l'apparition du boitier USB.

Windows enumere le peripherique, charge le pilote NCM, puis le bail DHCP arrive
(c'est le boitier qui sert l'adresse) : plus de cinq secondes en pratique.
Scanner une seule fois faisait annoncer « aucune carte » sur un boitier
parfaitement branche.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

import node_connection as N


class _FauxLayout:
    """Le scan insere des boutons ; on ne teste pas leur rendu."""
    def count(self): return 1
    def takeAt(self, _i): return None
    def insertWidget(self, *_a): pass


class _WizardFactice:
    """Juste ce que le scan touche, sans construire tout l'assistant."""
    _SCAN_ESSAIS = N.NodeSetupWizard._SCAN_ESSAIS
    _SCAN_PAUSE_MS = N.NodeSetupWizard._SCAN_PAUSE_MS
    _on_adapters_scanned = N.NodeSetupWizard._on_adapters_scanned
    _select_adapter = lambda self, nom, ip: setattr(self, "choisi", (nom, ip))

    def __init__(self, trouvailles):
        self._trouvailles = list(trouvailles)
        self._cable_variant = "usb"
        self._adapters_hint = None
        self._adapters_layout = _FauxLayout()
        self._adapter_buttons = []
        self._scan_tries = 0
        self.choisi = None
        self.pages = []

    def _set_working(self, statut, detail=""): pass
    def _stop_spinner(self): pass
    def _go_to(self, page): self.pages.append(page)

    @property
    def _btn_net_suivant(self):
        class _B:
            def setEnabled(self, _v): pass
        return _B()

    def _scan(self, *_a, retry=False):
        """Remplace le QThread : rend la trouvaille suivante, tout de suite."""
        rendu = self._trouvailles.pop(0) if self._trouvailles else []
        self._on_adapters_scanned(rendu)

    _start_adapter_scan = _scan


class TestScanPatient(unittest.TestCase):

    def setUp(self):
        self._timer = N.QTimer.singleShot
        # Le re-essai est immediat dans le test : on verifie la LOGIQUE de
        # patience, pas l'horloge.
        N.QTimer.singleShot = lambda _ms, cb: cb()

    def tearDown(self):
        N.QTimer.singleShot = self._timer

    def test_carte_qui_arrive_au_bout_de_trois_scans(self):
        carte = [("Ethernet 4", "2.0.0.2", "Electroconcept USB Node", True)]
        w = _WizardFactice([[], [], carte])
        w._scan()
        self.assertEqual(w._scan_tries, 2,
                         "il a fallu deux re-essais avant de voir la carte")
        self.assertFalse(w._trouvailles, "les trois scans ont ete consommes")

    def test_abandon_apres_le_quota(self):
        w = _WizardFactice([[]] * 20)
        w._scan()
        self.assertEqual(w._scan_tries, N.NodeSetupWizard._SCAN_ESSAIS,
                         "on ne boucle pas indefiniment : le verdict finit par tomber")

    def test_carte_presente_du_premier_coup_ne_retente_pas(self):
        carte = [("Ethernet 4", "2.0.0.2", "Electroconcept USB Node", True)]
        w = _WizardFactice([carte, []])
        w._scan()
        self.assertEqual(w._scan_tries, 0, "aucune attente inutile")


if __name__ == "__main__":
    unittest.main(verbosity=2)
