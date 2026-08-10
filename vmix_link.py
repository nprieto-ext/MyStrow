"""
vmix_link.py — Ce que MyStrow FAIT des evenements vMix, et son reglage.

vmix_client.py parle le protocole ; ce module decide de l'effet. La separation
n'est pas cosmetique : le client ne connait ni MainWindow ni les memoires, on
peut donc le tester (et le rejouer) sans lancer l'application.

Le gros du travail — vocabulaire d'actions, execution, persistance, dialogue —
vit dans video_link.py, partage avec OBS. Il ne reste ici que ce qui est propre
a vMix : le declencheur est une ENTREE (numero entier) qui passe au PROGRAMME.
"""

from vmix_client import VmixClient, VMIX_TCP_PORT, query_inputs
from video_link import VideoLink, VideoDialog
from i18n import tr


def _normaliser(entrees) -> list:
    """[{'number', 'title'}] du client → [{'key', 'label'}] du dialogue."""
    return [{"key": int(e["number"]), "label": f"{e['number']} — {e['title']}"}
            for e in (entrees or [])]


class VmixLink(VideoLink):
    """Correspondance entree vMix → action lumiere."""

    DEFAULT_PORT = VMIX_TCP_PORT
    KEY_TYPE = int

    def __init__(self, window):
        super().__init__(window, VmixClient(window))
        self.client.program_entered.connect(self._on_trigger)

    def _demarrer_client(self):
        self.client.start(self.host, self.port)


class VmixDialog(VideoDialog):
    """Connexion vMix + correspondance entree → action lumiere."""

    CLE_TITRE   = "vmix_title"
    CLE_ENTETE  = "vmix_header"
    CLE_INTRO   = "vmix_intro"
    CLE_ASTUCE  = "vmix_test_hint"
    CLE_ACTIVER = "vmix_enable"
    CLE_TEASER  = "vmix_guide_teaser"

    def __init__(self, window, link: VmixLink):
        self.COL_DECLENCHEUR = tr("vmix_col_input")
        super().__init__(window, link)

    def _declencheurs_du_client(self) -> list:
        return _normaliser(self._link.client.inputs())

    def _connecter_declencheurs(self):
        self._link.client.inputs_changed.connect(
            lambda entrees: self._peupler(_normaliser(entrees)))

    def _fabriquer_sonde(self):
        # Valeurs lues MAINTENANT, dans le thread Qt : la fermeture, elle,
        # tournera dans un thread reseau ou toucher un widget serait un acces
        # concurrent a l'interface.
        hote = self._hote.text().strip() or "127.0.0.1"
        port = self._port.value()
        return lambda: _normaliser(query_inputs(hote, port))
