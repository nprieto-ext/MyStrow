"""
obs_link.py — Ce que MyStrow FAIT des evenements OBS, et son reglage.

obs_client.py parle le protocole ; ce module decide de l'effet. Comme pour
vMix, tout le commun vit dans video_link.py : il ne reste ici que ce qui est
propre a OBS, c'est-a-dire un declencheur qui est une SCENE (nom, donc une
chaine) devenue active.

UNE CLEF QUI EST UN NOM, ET NON UN NUMERO
-----------------------------------------
C'est la seule vraie difference avec vMix, et elle a une consequence pratique :
renommer une scene dans OBS casse la correspondance, alors que reordonner les
scenes ne casse rien — exactement l'inverse d'un patch par numero. C'est le bon
compromis ici : on deplace ses scenes bien plus souvent qu'on ne les renomme, et
un nom reste lisible dans le fichier de configuration.
"""

from PySide6.QtWidgets import QLabel, QLineEdit

from obs_client import ObsClient, OBS_WS_PORT, query_scenes
from video_link import VideoLink, VideoDialog
from i18n import tr


def _normaliser(scenes) -> list:
    """[{'name', 'index'}] du client → [{'key', 'label'}] du dialogue."""
    return [{"key": str(s["name"]), "label": str(s["name"])}
            for s in (scenes or [])]


class ObsLink(VideoLink):
    """Correspondance scene OBS → action lumiere."""

    DEFAULT_PORT = OBS_WS_PORT
    KEY_TYPE = str

    def __init__(self, window):
        super().__init__(window, ObsClient(window))
        self.password = ""
        self.client.program_scene.connect(self._on_trigger)

    # Le mot de passe est range en clair dans ~/.maestro_akai_config.json, au
    # meme titre que le reste de la configuration. C'est un secret de reseau
    # local, qui ne protege que l'acces a OBS depuis la meme machine ; le
    # chiffrer ici donnerait surtout l'illusion d'une protection, puisque la
    # clef devrait voyager avec le fichier.
    def _extra_to_config(self) -> dict:
        return {"password": self.password}

    def _extra_from_config(self, cfg: dict):
        self.password = str(cfg.get("password", "") or "")

    def _demarrer_client(self):
        self.client.start(self.host, self.port, self.password)


class ObsDialog(VideoDialog):
    """Connexion OBS + correspondance scene → action lumiere."""

    CLE_TITRE   = "obs_title"
    CLE_ENTETE  = "obs_header"
    CLE_INTRO   = "obs_intro"
    CLE_ASTUCE  = "obs_test_hint"
    CLE_ACTIVER = "obs_enable"

    def __init__(self, window, link: ObsLink):
        self.COL_DECLENCHEUR = tr("obs_col_scene")
        super().__init__(window, link)

    def _champs_supplementaires(self, ligne):
        ligne.addWidget(QLabel(tr("obs_password")))
        self._mdp = QLineEdit(self._link.password)
        self._mdp.setEchoMode(QLineEdit.Password)
        self._mdp.setFixedWidth(130)
        # Le mot de passe est facultatif : OBS peut tourner authentification
        # desactivee, auquel cas le champ reste vide.
        self._mdp.setPlaceholderText(tr("obs_password_hint"))
        ligne.addWidget(self._mdp)

    def _declencheurs_du_client(self) -> list:
        return _normaliser(self._link.client.scenes())

    def _connecter_declencheurs(self):
        self._link.client.scenes_changed.connect(
            lambda scenes: self._peupler(_normaliser(scenes)))

    def _fabriquer_sonde(self):
        # Valeurs lues MAINTENANT, dans le thread Qt : la fermeture, elle,
        # tournera dans un thread reseau ou toucher un widget serait un acces
        # concurrent a l'interface.
        hote = self._hote.text().strip() or "127.0.0.1"
        port = self._port.value()
        mdp = self._mdp.text()
        return lambda: _normaliser(query_scenes(hote, port, mdp))

    def _enregistrer_extras(self):
        self._link.password = self._mdp.text()
