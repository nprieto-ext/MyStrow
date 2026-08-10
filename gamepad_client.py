"""
gamepad_client.py — Lecture d'une manette de jeu (PlayStation, Xbox…).

Sert a piloter le PAN/TILT des lyres au stick, comme la trackball d'une console
d'eclairage. C'est le geste juste pour pointer un projecteur : bien plus fin
qu'un cliquer-glisser a la souris dans un pave 2D.

POURQUOI PYGAME, ALORS QUE LE RESTE DU PROJET EVITE LES DEPENDANCES
-------------------------------------------------------------------
Qt6 n'offre rien : le module QtGamepad de Qt5 a ete supprime, PySide6 n'expose
aucune API manette. Il faut donc lire le peripherique nous-memes.

Contrairement au WebSocket d'OBS, l'ecrire a la main ne ferait economiser
AUCUNE dependance : lire du HID brut demande `hidapi`, qui est aussi une
extension C. Et la surface serait bien plus grande — DualShock 4 et DualSense
ont des formats de rapport differents, eux-memes differents en USB et en
Bluetooth, soit quatre variantes a valider avec le materiel en main. SDL (que
pygame embarque) gere deja tout cela, sur Windows comme sur macOS.

ON N'INITIALISE QUE LE STRICT MINIMUM
-------------------------------------
`pygame.init()` demarrerait aussi le mixer audio de SDL, qui entrerait en
concurrence avec la pile audio de MyStrow (sounddevice / miniaudio /
PyAudioWPatch). On se limite donc a `controller.init()` : verifie, cela
n'initialise ni l'affichage ni l'audio. En prime, `controller.update()`
fonctionne sans systeme video, ce qui evite le pilote « dummy » et tout
contexte graphique parasite.

L'API GameController DE SDL, ET PAS LES AXES BRUTS
--------------------------------------------------
`controller.Controller` expose LEFTX / LEFTY / RIGHTX / RIGHTY quel que soit le
modele. Les index d'axes bruts d'un `Joystick`, eux, changent entre DualShock 4,
DualSense et Xbox, et entre Windows et macOS : s'appuyer dessus donnerait un
tilt sur le stick droit chez l'un et un pan chez l'autre.

Le sondage tourne sur un QTimer DANS LE THREAD Qt, sans thread reseau : SDL
demande que son etat soit rafraichi depuis le thread principal sur macOS, et la
lecture est purement locale — aucune attente, donc rien qui puisse voler des
images a la trame DMX.
"""

from PySide6.QtCore import QObject, QTimer, Signal

# Sondage a 50 Hz : deux fois la trame DMX (25 fps), pour que le mouvement
# paraisse continu sans multiplier les envois inutiles.
POLL_MS = 20

# Plage renvoyee par SDL pour un axe (entier 16 bits signe).
_AXE_MAX = 32767.0


class GamepadClient(QObject):
    """Sonde la premiere manette branchee et publie ses axes normalises."""

    # (connecte, nom du peripherique)
    connection_changed = Signal(bool, str)
    # Manette reconnue mais qui n'emettra jamais rien (cf. `avertissement_pour`)
    avertissement      = Signal(str)
    # lx, ly, rx, ry — normalises entre -1.0 et 1.0, bruts (sans zone morte)
    axes_changed       = Signal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctrl = None
        self._nom = ""
        self._connecte = False
        self._sdl_pret = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._sonder)

    # ── cycle de vie ────────────────────────────────────────────────────────

    def start(self):
        if not self._init_sdl():
            return
        if not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._timer.stop()
        self._detacher()
        if self._sdl_pret:
            try:
                from pygame._sdl2 import controller
                controller.quit()
            except Exception:
                pass
            self._sdl_pret = False

    def is_connected(self) -> bool:
        return self._connecte

    def name(self) -> str:
        return self._nom

    def _init_sdl(self) -> bool:
        """Import et init differes : personne ne paie pygame s'il n'utilise pas
        de manette, et une installation sans pygame ne doit pas empecher
        MyStrow de demarrer."""
        if self._sdl_pret:
            return True
        try:
            from pygame._sdl2 import controller
            controller.init()
            # On INTERROGE l'etat, on n'ecoute pas d'evenements : sans ca SDL
            # remplit une file d'evenements que personne ne vide, qui grossit
            # pendant tout le show.
            try:
                controller.set_eventstate(False)
            except Exception:
                pass
            self._sdl_pret = True
            return True
        except Exception as exc:
            self.connection_changed.emit(False, f"pygame indisponible : {exc}")
            return False

    # ── sondage ─────────────────────────────────────────────────────────────

    def _sonder(self):
        """Appele 50x/s. Enveloppe try/except : une exception non rattrapee
        dans un callback QTimer fait tomber tout le processus sous PySide6, et
        debrancher une manette en plein show ne doit pas emporter la console."""
        try:
            self._do_sonder()
        except Exception as exc:
            print(f"[Manette] sondage ignore : {exc}")
            self._detacher()

    def _do_sonder(self):
        from pygame._sdl2 import controller
        controller.update()

        if self._ctrl is None:
            self._tenter_attache(controller)
            if self._ctrl is None:
                return

        # `attached()` est le seul moyen fiable de voir un debranchement quand
        # on n'ecoute pas les evenements SDL.
        if not self._ctrl.attached():
            self._detacher()
            return

        import pygame
        lx = self._ctrl.get_axis(pygame.CONTROLLER_AXIS_LEFTX)  / _AXE_MAX
        ly = self._ctrl.get_axis(pygame.CONTROLLER_AXIS_LEFTY)  / _AXE_MAX
        rx = self._ctrl.get_axis(pygame.CONTROLLER_AXIS_RIGHTX) / _AXE_MAX
        ry = self._ctrl.get_axis(pygame.CONTROLLER_AXIS_RIGHTY) / _AXE_MAX
        # -32768 depasse legerement -1.0 une fois divise par 32767.
        f = lambda v: max(-1.0, min(1.0, v))
        self.axes_changed.emit(f(lx), f(ly), f(rx), f(ry))

    def _tenter_attache(self, controller):
        for i in range(controller.get_count()):
            if not controller.is_controller(i):
                continue
            self._ctrl = controller.Controller(i)
            self._nom = controller.name_forindex(i) or "Manette"
            self._connecte = True
            self.connection_changed.emit(True, self._nom)
            avert = avertissement_pour(i)
            if avert:
                print(f"[Manette] {avert}")
                self.avertissement.emit(avert)
            return

    def _detacher(self):
        c, self._ctrl = self._ctrl, None
        if c is not None:
            try:
                c.quit()
            except Exception:
                pass
        if self._connecte:
            self._connecte = False
            self.connection_changed.emit(False, "Manette debranchee")


# ---------------------------------------------------------------------------
# Detection ponctuelle (dialogue de configuration)
# ---------------------------------------------------------------------------

def _vid_pid(guid: str) -> tuple:
    """(vendeur, produit) lus dans le GUID SDL d'un joystick.

    Le GUID SDL range ses champs en petit-boutiste : `0300f9d24c05000068020…`
    porte le vendeur en positions 8..11 (`4c05` → 0x054C) et le produit en
    16..19 (`6802` → 0x0268).
    """
    try:
        v = int(guid[10:12] + guid[8:10], 16)
        p = int(guid[18:20] + guid[16:18], 16)
        return v, p
    except Exception:
        return 0, 0


# Sony DualShock 3 / Sixaxis.
_VID_SONY, _PID_DS3 = 0x054C, 0x0268


def avertissement_pour(index: int) -> str:
    """Message a afficher quand la manette ne pourra JAMAIS rien envoyer.

    Le cas verifie ici est le DualShock 3 sous Windows avec le pilote HID
    d'origine : il s'enumere normalement, SDL le reconnait meme comme
    « PS3 Controller » avec un mapping complet — et il n'emet aucun rapport,
    parce que personne ne lui a ecrit son rapport de fonctionnalite 0xF4.
    Mesure faite avec la manette en main : tous les axes figes, aucun bouton, et
    `HidD_SetFeature` refuse par Windows (erreur 87) meme a la taille exacte que
    le peripherique declare. C'est ce que corrigent les pilotes tiers.

    Sans ce message, l'utilisateur voit « manette connectee » en vert et rien ne
    bouge : rien dans l'interface ne lui dit ou chercher.
    """
    import sys
    if not sys.platform.startswith("win"):
        return ""
    try:
        import pygame
        pygame.joystick.init()
        if index >= pygame.joystick.get_count():
            return ""
        j = pygame.joystick.Joystick(index)
        j.init()
        v, p = _vid_pid(j.get_guid())
        # Un DS3 passe par un pilote tiers (DsHidMini, ScpToolkit) se presente
        # en XInput/DS4 avec 6 axes : la manette marche, on ne dit rien.
        if (v, p) == (_VID_SONY, _PID_DS3) and j.get_numaxes() < 6:
            from i18n import tr
            return tr("gp_ds3_mute")
    except Exception:
        pass
    return ""


def avertissement_aucune() -> str:
    """Message quand Windows voit un peripherique de jeu, mais pas SDL.

    `lister_manettes()` ne garde que ce que SDL reconnait comme GameController.
    Une manette generique sans mapping dans la base SDL disparait donc de la
    liste, et l'interface affiche « aucune manette detectee » alors qu'il y en a
    une de branchee : le pire message possible, il envoie chercher du cote du
    cable. On nomme le peripherique pour lever le doute.
    """
    try:
        import pygame
        pygame.joystick.init()
        noms = []
        for i in range(pygame.joystick.get_count()):
            j = pygame.joystick.Joystick(i)
            j.init()
            noms.append(j.get_name())
        if noms:
            from i18n import tr
            return tr("gp_unmapped", nom=", ".join(noms))
    except Exception:
        pass
    return ""


def lister_manettes() -> list:
    """[(index, nom)] des manettes reconnues. Leve une exception explicite si
    pygame n'est pas installe."""
    from pygame._sdl2 import controller
    controller.init()
    try:
        controller.update()
    except Exception:
        pass
    return [(i, controller.name_forindex(i) or f"Manette {i}")
            for i in range(controller.get_count()) if controller.is_controller(i)]
