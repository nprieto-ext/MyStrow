"""
Gestion de l'envoi DMX :
  - ENTTEC Open DMX USB (port serie 250000 bauds)
  - Boitier reseau Art-Net (ElectroConcept, MA Lighting, etc.)
"""
import os
import sys
import json
import socket
import struct
import time
import threading

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# Permettre à ftd2xx de trouver la DLL D2XX EMBARQUÉE dans le build, même si
# le driver FTDI n'est PAS installé sur la machine cible. Sans ça, l'import
# lève OSError sur un poste sans driver → FTD2XX_AVAILABLE=False → repli
# silencieux sur la série VCP, dont le Latency Timer corrompt le break DMX
# (clignotements / lyres qui bougent seules). QLC+ marche justement parce
# qu'il embarque sa propre FTD2XX.dll : on fait pareil.
# _ftd2xx.py lit FTD2XX_DLL_DIR et l'ajoute au chemin de recherche des DLL.
if getattr(sys, "frozen", False):
    _bundle_dir = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    if _bundle_dir and os.path.exists(os.path.join(_bundle_dir, "ftd2xx.dll")):
        os.environ.setdefault("FTD2XX_DLL_DIR", _bundle_dir)

try:
    import ftd2xx
    import ftd2xx.defines as _ftd
    FTD2XX_AVAILABLE = True
except Exception:
    # ImportError (package absent) ou OSError (DLL FTDI absente sur la machine)
    FTD2XX_AVAILABLE = False

# Profils DMX pre-definis : nom -> liste ordonnee de types de canaux
DMX_PROFILES = {
    "DIM":         ["Dim"],
    "RGB":         ["R", "G", "B"],
    "RGBD":        ["R", "G", "B", "Dim"],
    "RGBDS":       ["R", "G", "B", "Dim", "Strobe"],
    "RGBSD":       ["R", "G", "B", "Strobe", "Dim"],
    "DRGB":        ["Dim", "R", "G", "B"],
    "DRGBS":       ["Dim", "R", "G", "B", "Strobe"],
    "RGBW":        ["R", "G", "B", "W"],
    "RGBWD":       ["R", "G", "B", "W", "Dim"],
    "RGBWDS":      ["R", "G", "B", "W", "Dim", "Strobe"],
    "RGBWZ":       ["R", "G", "B", "W", "Zoom"],
    "RGBWA":       ["R", "G", "B", "W", "Ambre"],
    "RGBWAD":      ["R", "G", "B", "W", "Ambre", "Dim"],
    "RGBWOUV":     ["R", "G", "B", "W", "Orange", "UV"],
    "2CH_FUMEE":   ["Smoke", "Fan"],
    # Moving Head
    "MOVING_5CH":  ["Shutter", "Dim", "ColorWheel", "Gobo1", "Speed"],
    "MOVING_8CH":  ["Pan", "Tilt", "Shutter", "Dim", "ColorWheel", "Gobo1", "Speed", "Mode"],
    "MOVING_RGB":  ["Pan", "Tilt", "R", "G", "B", "Dim", "Shutter", "Speed"],
    "MOVING_RGBW": ["Pan", "Tilt", "R", "G", "B", "W", "Dim", "Shutter", "Speed"],
    # Barre LED
    "LED_BAR_RGB": ["R", "G", "B", "Dim", "Strobe"],
    # Stroboscope
    "STROBE_2CH":  ["Shutter", "Dim"],
}

# Types de canaux disponibles pour les profils custom
CHANNEL_TYPES = [
    # Dim2 et Reset sont pilotes par le moteur depuis longtemps mais manquaient
    # ici : l'ecart n'a jamais gene (cette liste n'a aucun lecteur aujourd'hui),
    # il fausse en revanche l'audit qui compare les trois listes entre elles.
    "R", "G", "B", "W", "Dim", "Dim2", "Strobe", "UV", "Ambre", "Orange", "Zoom", "Iris",
    "Smoke", "Fan",
    "Pan", "PanFine", "Tilt", "TiltFine", "Gobo1", "Gobo1Rot", "Gobo2",
    "Prism", "PrismRot", "Focus", "ColorWheel", "Shutter", "Speed", "Mode", "Effects",
    # Correcteurs de temperature de couleur. Ce sont des canaux a part entiere :
    # ils etaient jusqu'ici rabattus sur « ColorWheel » par le parser, donc
    # confondus avec la vraie roue de couleurs de l'appareil.
    "CTO", "CTB",
    # Trichromie. ATTENTION : « C » ne veut pas dire la meme chose partout —
    # soustractif sur un spot a drapeaux (227 modes de la base), additif sur une
    # LED a emetteurs cyan/magenta/jaune (25 modes : ETC Lustr, ADJ Starburst).
    # Le moteur tranche sur la presence de R/G/B dans le profil.
    "C", "M", "Y", "Lime",
    # Couronne LED (« ring »), optique et controle. Canaux MANUELS : ils sortent
    # 0 au repos et ne prennent une valeur que par channel_extras (curseur des
    # « canaux avances ») ou channel_defaults. Sans eux, ces canaux tombaient sur
    # « Mode » ou « Unused » a la creation de la fixture — donc muets pour de bon.
    "RingDim", "RingR", "RingG", "RingB", "RingW", "RingStrobe",
    "RingFX", "RingSpeed",
    "Frost", "Anim", "AnimRot", "Gobo2Rot", "ColorWheel2",
    "DimCurve", "Sound",
    "Reset",
    # Canal du protocole que MyStrow ne pilote pas : sort 0 et garde sa place
    # dans la numérotation. Repli des attributs inconnus à l'import.
    "Unused",
]

# Noms courts pour l'affichage dans les combos
CHANNEL_DISPLAY = {
    "R": "R", "G": "G", "B": "B", "W": "W",
    "Dim": "Dim", "Dim2": "Dim2", "Strobe": "Strob", "UV": "UV",
    "Ambre": "Ambre", "Orange": "Orange", "Zoom": "Zoom", "Iris": "Iris",
    "Smoke": "Smoke", "Fan": "Fan",
    "Pan": "Pan", "PanFine": "PanF", "Tilt": "Tilt", "TiltFine": "TiltF",
    "Gobo1": "Gobo1", "Gobo1Rot": "GoboR", "Gobo2": "Gobo2",
    "Prism": "Prism", "PrismRot": "PrsmR", "Focus": "Focus",
    "ColorWheel": "CWheel", "Shutter": "Shut", "Speed": "Speed", "Mode": "Mode",
    "Effects": "FX", "CTO": "CTO", "CTB": "CTB",
    "C": "C", "M": "M", "Y": "Y", "Lime": "Lime",
    "RingDim": "RngD", "RingR": "RngR", "RingG": "RngG", "RingB": "RngB",
    "RingW": "RngW", "RingStrobe": "RngS", "RingFX": "RngFX",
    "RingSpeed": "RngSp",
    "Frost": "Frost", "Anim": "Anim", "AnimRot": "AnimR",
    "Gobo2Rot": "Gob2R", "ColorWheel2": "CWhl2",
    "DimCurve": "Curve", "Sound": "Son",
    "Unused": "—", "Reset": "Reset",
}


# Canaux sans etat dans Projector : pilotes uniquement a la main (curseur des
# « canaux avances ») ou par la valeur fixe du mode. Sortis d'une liste plutot
# que d'un long `elif ch_type in (...)` : c'est la meme regle pour les quinze.
_MANUAL_ONLY = frozenset({
    "RingDim", "RingR", "RingG", "RingB", "RingW", "RingStrobe",
    "RingFX", "RingSpeed",
    "Frost", "Anim", "AnimRot", "Gobo2Rot", "ColorWheel2",
    "DimCurve", "Sound",
})

# Couronne LED : les canaux que le show sait alimenter tout seul quand
# `proj.ring_follow` est vrai — couleur, niveau, strobe. Ils restent dans
# `_MANUAL_ONLY` : c'est ce qui les ramene a 0 des que la couronne repasse en
# manuel, sans autre test.
#
# RingFX et RingSpeed n'y sont PAS, volontairement : ce sont les programmes
# internes de la couronne (chenillards, arc-en-ciel, sound-active). Les piloter
# depuis le show lancerait un automatisme de l'appareil par-dessus le rendu,
# exactement le piege du canal « Mode ». Ils restent au curseur.
_RING_DRIVEN = frozenset({
    "RingDim", "RingR", "RingG", "RingB", "RingW", "RingStrobe",
})


def profile_display_text(channels):
    """Formate une liste de canaux en texte lisible (R G B Dim Strob)"""
    return " ".join(CHANNEL_DISPLAY.get(ch, ch) for ch in channels)

# Retro-compatibilite : anciens modes -> nom de profil
_LEGACY_MODE_MAP = {
    "3CH": "RGB",
    "4CH": "RGBD",
    "5CH": "RGBDS",
    "6CH": "RGBDS",
    "2CH_FUMEE": "2CH_FUMEE",
}


def profile_for_mode(mode):
    """Convertit un ancien mode (3CH, 5CH...) en liste de types de canaux (profil)"""
    name = _LEGACY_MODE_MAP.get(mode, mode)
    if name in DMX_PROFILES:
        return list(DMX_PROFILES[name])
    if isinstance(mode, list):
        return mode
    return list(DMX_PROFILES["RGBDS"])


def profile_name(profile):
    """Retrouve le nom d'un profil a partir de sa liste de canaux, ou None si custom"""
    for name, channels in DMX_PROFILES.items():
        if channels == profile:
            return name
    return None


# ------------------------------------------------------------------
# Constantes de transport
# ------------------------------------------------------------------
TRANSPORT_ENTTEC      = "enttec"       # ENTTEC Open DMX USB (serie VCP, break + data brut)
TRANSPORT_ENTTEC_D2XX = "enttec_d2xx"  # ENTTEC Open DMX USB via driver FTDI D2XX (comme QLC+)
TRANSPORT_ENTTEC_PRO  = "enttec_pro"   # ENTTEC DMX USB Pro (paquet 7E/E7, DMXKing, etc.)
TRANSPORT_ARTNET      = "artnet"       # Boitier reseau Art-Net (ElectroConcept...)

# Valeur d'`ArtNetDMX.output_map` marquant une sortie du Node desactivee.
# On EMET quand meme, avec 512 zeros : cesser d'emettre laisserait la plupart
# des nodes rejouer la derniere trame recue — projecteurs figes allumes.
OUTPUT_OFF = -1

# Port du Node bascule en ENTREE (DMX -> Art-Net), pour y brancher un pupitre.
# Ici, au contraire d'OUTPUT_OFF, il faut se TAIRE completement : ce port n'est
# plus un consommateur mais une SOURCE. Continuer a lui envoyer nos 512 zeros
# mettrait deux emetteurs sur le meme univers — selon le boitier, il merge, il
# ignore, ou il alterne entre les deux trames. C'est toute la difference entre
# « cette sortie n'eclaire rien » et « cette sortie ne m'appartient pas ».
OUTPUT_INPUT = -2

# Break DMX genere par « baud-rate trick » : un octet 0x00 emis a BREAK_BAUD
# tient la ligne a LOW pendant 1 bit de start + 8 bits de donnees = 9 bits.
# C'est le repli quand send_break n'est pas exploitable — cas de macOS, ou il
# reussit sans lever d'exception mais ne produit aucun break electrique valide.
# 100 000 bauds ne donnaient que 90 us, SOUS le minimum de 92 us impose au
# transmetteur par DMX512-A : un break limite, que des fixtures peuvent rejeter
# sans le moindre message d'erreur.
BREAK_BAUD = 90000
BREAK_US   = 9 * 1_000_000 / BREAK_BAUD   # ~100 us

# Etat des lignes de controle modem (RTS / DTR) sur le transport serie brut.
#
# POURQUOI CA COMPTE : un boitier « Open DMX » est passif — la puce FTDI attaque
# directement l'emetteur RS485 (75176 & co). Sur l'ENTTEC Open DMX USB, la
# broche DE (Driver Enable) de cet emetteur est cablee sur RTS et non tiree en
# dur a VCC. Or pyserial ASSERTE RTS et DTR a l'ouverture du port : l'emetteur
# reste alors muet — le PC envoie ses trames sans la moindre erreur, le
# diagnostic est tout vert, et rien ne sort du XLR. C'est exactement ce que
# QLC+ et OLA evitent en appelant clearRts() sur ce materiel.
#
# MESURE (28/07/2026, ENTTEC Open DMX USB, FTDI BG04EMMJ, macOS 24.2, 4 x 6 s
# de plein feu clignotant a 25 fps) :
#     RTS ✗ / DTR ✗ -> ALLUME      RTS ✓ / DTR ✓ -> muet
#     RTS ✗ / DTR ✓ -> ALLUME      RTS ✓ / DTR ✗ -> muet
# Seul RTS discrimine ; DTR n'a aucun effet. C'est bien RTS qui porte le DE.
# Un boitier dont le DE est cable en dur (cas de l'USB Opto ElectroConcept, qui
# fonctionne deja) ignore completement ces lignes : desasserter est sans risque.
# Le mode est surchargeable via ~/.mystrow_dmx.json (cle "serial_lines") pour
# couvrir un cablage exotique sans rebuild — cf. assistant, « Test RTS/DTR ».
SERIAL_LINES_MODES = {
    "clear":  (False, False),   # defaut : RTS et DTR desassertes (QLC+ / OLA)
    "legacy": (True,  True),    # comportement < 3.1.77 (defaut pyserial)
    "rts":    (True,  False),
    "dtr":    (False, True),
}
SERIAL_LINES_LABELS = {
    "clear":  "RTS ✗ / DTR ✗ (défaut)",
    "legacy": "RTS ✓ / DTR ✓ (ancien)",
    "rts":    "RTS ✓ / DTR ✗",
    "dtr":    "RTS ✗ / DTR ✓",
}


class ArtNetDMX:
    """Envoi DMX via ENTTEC Open DMX USB ou boitier reseau Art-Net.
    Le mode de transport est selectionnable et persiste dans ~/.mystrow_dmx.json."""

    CONFIG_FILE = os.path.expanduser("~/.mystrow_dmx.json")

    def __init__(self):
        # --- Transport actif ---
        self.transport = TRANSPORT_ARTNET

        # --- Produit selectionne ---
        self.product_id   = "artnet"
        self.product_name = "Art-Net (réseau)"

        # Verrou partagé : protège dmx_data contre les race conditions
        # entre le thread Qt (écriture via update_from_projectors) et les
        # threads ENTTEC (lecture snapshot avant envoi série).
        self._dmx_lock = threading.Lock()

        # --- ENTTEC Open DMX USB ---
        self.com_port = None
        self._serial = None
        self._enttec_stop = False
        self._enttec_thread = None
        # Suspend l'envoi du thread sans fermer le port (ex: pendant le
        # Test 100% du diagnostic, pour éviter deux threads écrivant
        # simultanément sur le même port FTDI).
        self._enttec_pause = False
        # Acquittement de pause : passe à True quand le thread a réellement
        # atteint sa branche pause (et donc lâché le port). Un writer
        # concurrent (Test 100%) doit attendre cet ack avant d'écrire.
        self._enttec_paused = False
        # Compteur d'erreurs d'écriture CONSÉCUTIVES : on ne ferme/rouvre le
        # port qu'après plusieurs erreurs d'affilée (un hoquet USB isolé ne
        # doit pas réinitialiser la ligne FTDI → flash + trou DMX).
        self._enttec_err_count = 0
        # Etat RTS/DTR applique a l'ouverture du port serie (cf. SERIAL_LINES_MODES)
        self.serial_lines = "clear"

        # --- ENTTEC Open DMX USB via D2XX (driver FTDI direct, comme QLC+) ---
        # Le boitier passif (FT232R) est piloté de façon fiable par le driver
        # D2XX plutôt que par le port COM/VCP (dont le Latency Timer corrompt
        # le timing du break DMX). On identifie la puce par son numéro de série
        # FTDI (ex: "BG04EMMJ") plutôt que par un port COM.
        self.ftdi_serial = None
        self._d2xx = None
        self._d2xx_stop = False
        self._d2xx_thread = None
        self._d2xx_pause = False
        self._d2xx_paused = False
        self._d2xx_err_count = 0   # erreurs d'écriture consécutives (cf. _enttec_err_count)

        # Debug sortie DMX : MYSTROW_DMX_DEBUG=1 → log des trous de flux (>150 ms)
        # et de la cadence réelle (fps) quand elle chute. Off par défaut.
        self._dmx_debug = bool(os.environ.get("MYSTROW_DMX_DEBUG"))

        # --- ENTTEC DMX USB Pro ---
        self._pro_serial = None
        self._pro_stop = False
        self._pro_thread = None
        # Pause coopérative, comme _enttec_pause / _d2xx_pause. Elle manquait ici :
        # le diagnostic ouvrait un SECOND handle sur le même tty pendant que
        # _pro_loop y écrivait à 25 fps. Deux writers sur le même port série =
        # crash natif du driver (l'appli se ferme), puis sortie DMX morte parce
        # que le handle live a été refermé au passage.
        self._pro_pause = False
        self._pro_paused = False
        # Débit série puce↔MCU. Ignoré par un vrai ENTTEC (FT245), mais doit
        # correspondre au firmware sur les clones FT232R (Eurolite PRO MK2…).
        # 250000 = valeur des clones FTDI ; surchargeable via ~/.mystrow_dmx.json.
        self.pro_baud = 250000

        # --- Art-Net reseau ---
        self.target_ip = "2.0.0.15"
        self.target_port = 6454       # Port Art-Net standard
        self.universe = 0             # Univers Art-Net de la sortie 1 du Node (0-based)
        self.universe2 = 1            # OBSOLETE — remplace par output_map, garde pour la relecture des vieux .json
        self.mirror_output = True     # OBSOLETE — idem (voir output_map)
        # Correspondance sortie physique du Node -> univers interne MyStrow.
        # output_map[n] = index (0-3) du tampon dmx_data emis sur la sortie n du
        # Node, c'est-a-dire sur l'univers Art-Net (self.universe + n).
        # Par defaut chaque sortie recoit son univers homonyme : 1->1, 2->2...
        # Deux sorties peuvent pointer le MEME univers : c'est le miroir, en plus
        # souple que l'ancien booleen `mirror_output` — lequel n'etait de toute
        # facon jamais lu par _send_artnet.
        # OUTPUT_OFF (-1) = sortie desactivee. On continue d'EMETTRE, avec tous
        # les canaux a zero : couper l'emission laisserait la plupart des nodes
        # rejouer indefiniment la derniere trame recue, donc des projecteurs
        # figes allumes en scene.
        self.output_map = [0, 1, 2, 3]
        self._artnet_seq = 0
        self._socket = None

        # --- Etat commun ---
        self.connected = False
        self.dmx_data = [[0] * 512 for _ in range(4)]  # 4 univers × 512 canaux

        # --- Patch projecteurs ---
        self.projector_channels = {}
        self.projector_profiles = {}
        self.projector_modes = {}       # Retro-compat
        self.projector_universes = {}   # proj_key -> univers (0-3)

        self._load_config()

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self):
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                self.transport    = cfg.get("transport", TRANSPORT_ARTNET)
                self.product_id   = cfg.get("product_id", "artnet")
                self.product_name = cfg.get("product_name", "Art-Net (réseau)")
                self.com_port     = cfg.get("com_port")
                self.ftdi_serial  = cfg.get("ftdi_serial")
                _stored_ip = cfg.get("target_ip", "2.0.0.15")
                # Corriger une éventuelle IP non-Art-Net stockée par erreur
                self.target_ip = _stored_ip if _stored_ip.startswith("2.") else "2.0.0.15"
                self.target_port  = int(cfg.get("target_port", 6454))
                self.universe     = int(cfg.get("universe", 0))
                self.universe2    = int(cfg.get("universe2", 1))
                self.mirror_output = bool(cfg.get("mirror_output", True))
                self.set_output_map(cfg.get("output_map"))
                self.pro_baud      = int(cfg.get("pro_baud", 250000))
                _lines = str(cfg.get("serial_lines", "clear"))
                self.serial_lines = _lines if _lines in SERIAL_LINES_MODES else "clear"
        except Exception:
            pass

    def set_output_map(self, mapping):
        """Fixe la correspondance sortie du Node -> univers interne.

        Valeurs acceptees : 0-3 (index d'univers), OUTPUT_OFF pour desactiver
        (on emet des zeros), ou OUTPUT_INPUT si ce port du Node est bascule en
        entree DMX (on n'emet rien du tout — cf. la constante).

        Tolerant a dessein : une config absente, tronquee ou corrompue ne doit
        jamais empecher la sortie DMX de fonctionner. Toute entree invalide
        retombe sur l'identite (sortie n -> univers n), qui est le cablage
        attendu par defaut. Une entree illisible ne desactive JAMAIS une sortie :
        se retrouver dans le noir a cause d'un fichier abime serait pire que de
        diffuser le mauvais univers.
        """
        if not isinstance(mapping, (list, tuple)):
            self.output_map = [0, 1, 2, 3]
            return
        out = []
        for n in range(4):
            try:
                v = int(mapping[n])
            except Exception:
                out.append(n)
                continue
            if v in (OUTPUT_OFF, OUTPUT_INPUT):
                out.append(v)
            else:
                out.append(max(0, min(3, v)))
        self.output_map = out

    def input_universes(self):
        """Univers Art-Net des ports du Node bascules en ENTREE.

        Sert a l'entree DMX (dmx_in_link.py) : c'est sur ces univers-la que le
        pupitre branche sur le boitier va emettre, et donc ceux qu'il faut
        ecouter. Evite a l'utilisateur de deviner le numero.
        """
        return [self.universe + n for n, v in enumerate(self.output_map)
                if v == OUTPUT_INPUT]

    def _save_config(self):
        try:
            with open(self.CONFIG_FILE, "w") as f:
                json.dump({
                    "transport":     self.transport,
                    "product_id":    self.product_id,
                    "product_name":  self.product_name,
                    "com_port":      self.com_port,
                    "ftdi_serial":   self.ftdi_serial,
                    "target_ip":     self.target_ip,
                    "target_port":   self.target_port,
                    "universe":      self.universe,
                    "universe2":     self.universe2,
                    "mirror_output": self.mirror_output,
                    "output_map":    list(self.output_map),
                    "pro_baud":      getattr(self, "pro_baud", 250000),
                    "serial_lines":  getattr(self, "serial_lines", "clear"),
                }, f, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Connexion (route vers le bon transport)
    # ------------------------------------------------------------------

    def connect(self, com_port=None, target_ip=None, target_port=None,
                universe=None, universe2=None, mirror_output=None,
                transport=None, product_id=None, product_name=None,
                ftdi_serial=None):
        """Ouvre la connexion DMX selon le transport configure.
        Les parametres optionnels ecrasent la config et la sauvegardent."""
        if transport is not None:
            self.transport = transport
        if product_id is not None:
            self.product_id = product_id
        if product_name is not None:
            self.product_name = product_name
        if com_port is not None:
            self.com_port = com_port
        if ftdi_serial is not None:
            self.ftdi_serial = ftdi_serial
        if target_ip is not None:
            self.target_ip = target_ip
        if target_port is not None:
            self.target_port = int(target_port)
        if universe is not None:
            self.universe = int(universe)
        if universe2 is not None:
            self.universe2 = int(universe2)
        if mirror_output is not None:
            self.mirror_output = bool(mirror_output)

        self._save_config()

        # Changement de transport à chaud : arrêter proprement les AUTRES
        # transports avant d'ouvrir le nouveau. Sinon (ex. série → D2XX sur la
        # même puce FTDI) l'ancien thread continue d'écrire sur la même puce →
        # conflit « deux writers » → strobe / clignotements.
        self._stop_other_transports(self.transport)

        if self.transport == TRANSPORT_ENTTEC:
            return self._connect_enttec()
        elif self.transport == TRANSPORT_ENTTEC_D2XX:
            return self._connect_enttec_d2xx()
        elif self.transport == TRANSPORT_ENTTEC_PRO:
            return self._connect_enttec_pro()
        else:
            return self._connect_artnet()

    def _stop_other_transports(self, target):
        """Arrête threads/ports de tous les transports SAUF `target`.
        Garantit un seul writer DMX actif lors d'un changement de transport."""
        # On JOINT les threads (et pas seulement fermer le port) : fermer le
        # handle sans attendre laissait l'ancien thread tourner une fraction de
        # seconde de plus et rouvrir/écrire par-dessus le nouveau transport.
        if target != TRANSPORT_ENTTEC:
            self._stop_enttec_thread()
        if target != TRANSPORT_ENTTEC_D2XX:
            self._stop_d2xx_thread()
        if target != TRANSPORT_ENTTEC_PRO:
            self._stop_pro_thread()
        if target != TRANSPORT_ARTNET and self._socket:
            try: self._socket.close()
            except Exception: pass
            self._socket = None

    def disconnect(self):
        """Ferme toutes les connexions ouvertes"""
        self._stop_enttec_thread()
        self._stop_d2xx_thread()
        self._stop_pro_thread()
        if self._socket:
            self._socket.close()
        self._socket = None
        self.connected = False

    # ------------------------------------------------------------------
    # Transport ENTTEC Open DMX USB
    # ------------------------------------------------------------------

    def apply_serial_lines(self, ser, mode=None):
        """Positionne RTS/DTR sur un port serie DMX brut (cf. SERIAL_LINES_MODES).

        Appele apres CHAQUE ouverture (connexion initiale ET reconnexion auto) :
        pyserial asserte les deux lignes a l'ouverture, ce qui peut inhiber
        l'emetteur RS485 d'un boitier Open DMX passif — sortie muette sans
        aucune erreur. Volontairement public : l'assistant s'en sert pour
        balayer les 4 combinaisons sur le port live."""
        rts, dtr = SERIAL_LINES_MODES.get(mode or getattr(self, "serial_lines", "clear"),
                                          SERIAL_LINES_MODES["clear"])
        try:
            ser.rts = rts
        except Exception as e:
            print(f"ENTTEC: RTS non pilotable ({e})")
        try:
            ser.dtr = dtr
        except Exception as e:
            print(f"ENTTEC: DTR non pilotable ({e})")

    def _open_enttec_serial(self):
        """Ouvre le port serie DMX brut (250 kbauds, 8N2) lignes RTS/DTR reglees."""
        ser = serial.Serial(
            port=self.com_port,
            baudrate=250000,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_TWO,
            timeout=0.1,
        )
        self.apply_serial_lines(ser)
        return ser

    def _connect_enttec(self):
        if not SERIAL_AVAILABLE:
            print("pyserial non disponible — pip install pyserial")
            self.connected = False
            return False

        if not self.com_port:
            print("Aucun port COM configure pour l'ENTTEC")
            self.connected = False
            return False

        # Reconnexion sur un transport DÉJÀ actif : arrêter le thread en place
        # AVANT d'ouvrir le nouveau port, sinon l'ancien thread récupère le
        # nouveau handle et on se retrouve à deux writers sur la même puce.
        self._stop_enttec_thread()

        try:
            self._serial = self._open_enttec_serial()
            self.connected = True
            print(f"ENTTEC Open DMX USB connecte sur {self.com_port} "
                  f"(lignes {getattr(self, 'serial_lines', 'clear')})")
            self._start_enttec_thread()
            return True
        except Exception as e:
            err = str(e)
            if "13" in err or "permission" in err.lower() or "access" in err.lower():
                print(f"ENTTEC ({self.com_port}): port déjà utilisé par une autre application")
            else:
                print(f"Erreur connexion ENTTEC ({self.com_port}): {e}")
            self._serial = None
            self.connected = False
            return False

    def _stop_enttec_thread(self):
        """Arrête proprement le thread ENTTEC série et ferme le port.

        Symétrique de _stop_d2xx_thread, et tout aussi CRUCIAL : sans ça, un
        2e connect() sur le MÊME transport laissait le thread précédent en vie
        (`_start_enttec_thread` remet `_enttec_stop` à False, donc l'ancien ne
        sort jamais de sa boucle) → deux threads écrivant break/baudrate/frame
        sur le même handle série, sans verrou. Cas réel : l'app se connecte au
        démarrage depuis ~/.mystrow_dmx.json, puis l'utilisateur clique
        « Connecter » dans l'assistant → 2 writers. Très destructeur sur macOS
        où chaque trame reconfigure le baudrate (tcsetattr + ioctl)."""
        self._enttec_stop = True
        t = self._enttec_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)
        self._enttec_thread = None
        # Une pause restée armée bloquerait le prochain thread dès son départ.
        self._enttec_pause = False
        self._enttec_paused = False
        self._enttec_err_count = 0
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def _stop_pro_thread(self):
        """Arrête proprement le thread ENTTEC Pro et ferme le port.
        Même raison que _stop_enttec_thread : `_start_pro_thread` réarme
        `_pro_stop` à False, donc sans join l'ancien thread survit."""
        self._pro_stop = True
        t = self._pro_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)
        self._pro_thread = None
        self._pro_pause = False
        self._pro_paused = False
        if self._pro_serial is not None:
            try:
                self._pro_serial.close()
            except Exception:
                pass
        self._pro_serial = None

    def _start_enttec_thread(self):
        self._enttec_stop = False
        t = threading.Thread(target=self._enttec_loop, daemon=True, name="EnttecDMX")
        t.start()
        self._enttec_thread = t

    def _enttec_bump_error(self, ser, e):
        """Gère une erreur d'écriture série dans _enttec_loop.

        Retourne True si l'erreur est traitée comme un hoquet transitoire (frame
        sautée, port gardé ouvert → l'appelant doit faire `continue`), False si le
        port a été fermé après trop d'erreurs CONSÉCUTIVES (l'appelant laisse la
        boucle poursuivre, la branche de reconnexion prendra le relais).

        But : un hoquet USB isolé ne doit PAS fermer/rouvrir le port (ce qui
        crée un trou DMX d'~1 s + réinitialise la ligne FTDI → clignotement)."""
        self._enttec_err_count += 1
        if self._enttec_err_count < 5:
            time.sleep(0.005)
            return True
        print(f"ENTTEC thread: {self._enttec_err_count} erreurs consécutives — fermeture ({e})")
        try:
            ser.close()
        except Exception:
            pass
        self._serial = None
        self.connected = False
        self._enttec_err_count = 0
        return False

    def _enttec_loop(self):
        """Thread dédié ENTTEC : envoie les frames à ~25 fps sans bloquer le thread Qt.

        Méthode de break :
          1. send_break(1 ms) (SetCommBreak/ClearCommBreak) — standard FTDI/pyserial,
             éprouvé et fiable sur Windows/Linux.
          2. Baud-rate trick (100 kbaud → 0x00 → 250 kbaud) — fallback universel,
             fonctionne même si SetCommBreak n'est pas supporté (CH340, FTDI clones,
             certains drivers Windows 11) et plus fiable sur macOS.
        """
        # Sur macOS, send_break FTDI VCP peut réussir sans lever d'exception mais
        # ne génère pas de break électrique valide → les fixtures ignorent tous les frames.
        # Le baud-rate trick est plus fiable sur macOS (et reste valide sur Windows/Linux).
        _use_baud_trick = (sys.platform == 'darwin')
        while not self._enttec_stop:
            t0 = time.monotonic()
            ser = self._serial
            # Pause : on garde le port ouvert mais on n'écrit pas (un autre
            # writer — ex: Test 100% — détient temporairement le port).
            # On acquitte la pause (_enttec_paused) APRÈS toute écriture en
            # cours : le writer concurrent attend cet ack avant d'écrire, ce
            # qui garantit qu'on ne touche plus le port FTDI en parallèle
            # (sinon collision → fermeture du port → "port that is not open").
            if self._enttec_pause:
                self._enttec_paused = True
                time.sleep(0.02)
                continue
            self._enttec_paused = False
            if ser and ser.is_open:
                try:
                    with self._dmx_lock:
                        frame = b'\x00' + bytes(self.dmx_data[0][:512])
                    if not _use_baud_trick:
                        # Méthode 1 : send_break (SetCommBreak/ClearCommBreak).
                        # Break de 1 ms — valeur éprouvée et fiable sur Windows
                        # (regression 3.1.28 : le toggle break_condition à 176 µs
                        # était trop court — avec la gigue de latence USB FTDI le
                        # break tombait sous le seuil DMX512 et les projecteurs
                        # ignoraient toutes les frames, sans aucune erreur visible).
                        ser.send_break(duration=0.001)
                        ser.write(frame)
                        ser.flush()
                    else:
                        # Méthode 2 : baud-rate trick — break généré par un 0x00
                        # (9 bits LOW à BREAK_BAUD ≈ 100 µs, cf. constante)
                        #
                        # SURTOUT PAS de reset_output_buffer() ici. Sur macOS
                        # (FTDI VCP) chaque appel BLOQUE près d'une seconde :
                        # mesuré sur MacBook M1, 2 appels par trame font tomber
                        # la sortie à 8 trames en 8 s — 1 fps. Un projecteur
                        # DMX512 coupe après ~1 s sans trame valide, donc plus
                        # rien ne s'allume, sans la moindre erreur pour le dire.
                        # Sans ces appels : 154 trames en 8 s (19 fps) et les
                        # projecteurs répondent.
                        # Ils étaient de toute façon inutiles : `flush()`
                        # (tcdrain) a déjà vidé la sortie — il ne reste rien à
                        # jeter, et jeter APRÈS le flush ne peut que supprimer
                        # le break qu'on vient d'émettre.
                        ser.baudrate = BREAK_BAUD
                        ser.write(b'\x00')
                        ser.flush()
                        time.sleep(0.0015)     # 1.5 ms — marge pour latence USB macOS
                        ser.baudrate = 250000
                        time.sleep(0.0001)     # MAB explicite ≥ 8 µs requis DMX512
                        ser.write(frame)
                        ser.flush()
                    self.connected = True
                    self._enttec_err_count = 0
                except (AttributeError, OSError) as e:
                    if not _use_baud_trick:
                        # send_break non supporté → bascule silencieuse (feature-test
                        # one-shot, pas une erreur transitoire : pas de compteur).
                        print(f"ENTTEC: send_break échoué ({e}), basculement sur baud-rate trick")
                        _use_baud_trick = True
                    elif self._enttec_bump_error(ser, e):
                        continue
                except Exception as e:
                    if self._enttec_bump_error(ser, e):
                        continue
            elif self.com_port and not self._enttec_stop:
                # Reconnexion automatique
                try:
                    self._serial = self._open_enttec_serial()
                    self.connected = True
                    print(f"ENTTEC: reconnexion sur {self.com_port}")
                except Exception:
                    time.sleep(1.0)
                    continue
            else:
                time.sleep(0.040)
                continue

            # Pause pour atteindre 25 fps (40 ms par cycle)
            elapsed = time.monotonic() - t0
            remaining = 0.040 - elapsed
            if remaining > 0.001:
                time.sleep(remaining)

    def _send_enttec(self):
        """Maintenu pour compatibilité — le thread dédié gère l'envoi réel."""
        return True

    # ------------------------------------------------------------------
    # Transport ENTTEC Open DMX USB via D2XX (driver FTDI direct)
    # ------------------------------------------------------------------
    # Le boitier ENTTEC Open DMX USB est un adaptateur PASSIF : la puce FTDI
    # FT232R bit-bang directement le DMX, tout le timing repose sur le PC.
    # Via le port COM/VCP, le Latency Timer du driver (16 ms par defaut)
    # regroupe les ecritures et casse le timing du break -> les projecteurs
    # ignorent toutes les trames sans aucune erreur visible.
    # Le driver D2XX (utilise par QLC+) parle directement a la puce, regle le
    # Latency Timer a 1 ms et genere un break propre via FT_SetBreakOn/Off.
    # C'est la methode fiable pour ce materiel.

    def _resolve_d2xx_index(self):
        """Trouve l'index D2XX du boitier a ouvrir.
        Match sur self.ftdi_serial (numero de serie FTDI, ex "BG04EMMJ").
        pyserial rapporte parfois ce SN avec un suffixe d'interface (ex "...A"),
        donc on tolere un match par prefixe. Fallback : premier device (0)."""
        try:
            devices = ftd2xx.listDevices() or []
        except Exception:
            devices = []
        target = (self.ftdi_serial or "").strip()
        if target and devices:
            for i, sn in enumerate(devices):
                sn_s = sn.decode(errors="ignore") if isinstance(sn, bytes) else str(sn)
                sn_s = sn_s.strip()
                if not sn_s:
                    continue
                # Egalite stricte, ou l'un prefixe de l'autre (suffixe d'interface FTDI)
                if sn_s == target or target.startswith(sn_s) or sn_s.startswith(target):
                    return i
        return 0

    def _stop_d2xx_thread(self):
        """Arrête proprement le thread D2XX et libère la puce FTDI.
        CRUCIAL : sans ça, un nouveau connect() démarrerait un 2e thread sur le
        même handle FTDI (anti-pattern « deux writers ») → DEVICE_NOT_OPENED."""
        self._d2xx_stop = True
        t = self._d2xx_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)
        self._d2xx_thread = None
        if self._d2xx is not None:
            try:
                self._d2xx.setBreakOff()
            except Exception:
                pass
            try:
                self._d2xx.close()
            except Exception:
                pass
        self._d2xx = None
        self._d2xx_pause = False
        self._d2xx_paused = False

    def _connect_enttec_d2xx(self):
        if not FTD2XX_AVAILABLE:
            print("ftd2xx non disponible — pip install ftd2xx (et driver FTDI installé)")
            self.connected = False
            return False
        # Toujours arrêter un éventuel thread D2XX précédent AVANT de rouvrir,
        # sinon deux threads se battent pour le même handle FTDI.
        self._stop_d2xx_thread()
        try:

            index = self._resolve_d2xx_index()
            dev = ftd2xx.open(index)
            # Configuration DMX512 : 250 kbaud, 8 bits, 2 stop, sans parité
            dev.setBaudRate(250000)
            dev.setDataCharacteristics(_ftd.BITS_8, _ftd.STOP_BITS_2, _ftd.PARITY_NONE)
            dev.setFlowControl(_ftd.FLOW_NONE, 0, 0)
            dev.setLatencyTimer(1)      # 1 ms — le réglage clé que le VCP ne fait pas
            dev.setTimeouts(100, 100)
            # RTS désassertée, comme QLC+ : mesuré sur ENTTEC Open DMX USB, la
            # broche Driver Enable du transceiver RS485 y est câblée — RTS
            # assertée = sortie totalement muette (et aucune erreur). C'est
            # déjà l'état par défaut de FT_Open (d'où le fonctionnement en
            # D2XX sous Windows), on l'écrit explicitement pour ne pas
            # dépendre d'un défaut de driver.
            try:
                dev.clrRts()
                dev.clrDtr()
            except Exception as e:
                print(f"ENTTEC D2XX : RTS/DTR non pilotables ({e})")
            dev.purge(_ftd.PURGE_TX | _ftd.PURGE_RX)
            self._d2xx = dev
            self.connected = True
            try:
                sn = dev.getDeviceInfo().get("serial", b"")
                sn = sn.decode(errors="ignore") if isinstance(sn, bytes) else str(sn)
            except Exception:
                sn = "?"
            print(f"ENTTEC Open DMX USB (D2XX) connecté — FTDI {sn}")
            self._start_d2xx_thread()
            return True
        except Exception as e:
            err = str(e)
            if "DEVICE_NOT_OPENED" in err or "BUSY" in err.upper() or "ACCESS" in err.upper():
                print(f"ENTTEC D2XX : puce FTDI déjà utilisée (fermez QLC+/autre logiciel DMX)")
            else:
                print(f"Erreur connexion ENTTEC D2XX : {e}")
            self._d2xx = None
            self.connected = False
            return False

    def _start_d2xx_thread(self):
        import threading
        self._d2xx_stop = False
        t = threading.Thread(target=self._d2xx_loop, daemon=True, name="EnttecD2XX")
        t.start()
        self._d2xx_thread = t

    def _d2xx_loop(self):
        """Thread dédié D2XX : break + frame à ~40 fps directement sur la puce FTDI."""
        _dbg = self._dmx_debug
        _last_ok = time.monotonic()
        _fps_t0 = _last_ok
        _fps_n = 0
        while not self._d2xx_stop:
            t0 = time.monotonic()
            dev = self._d2xx
            # Pause coopérative (Test 100% / diagnostic) : on garde la puce
            # ouverte mais on n'écrit plus, et on acquitte via _d2xx_paused.
            if self._d2xx_pause:
                self._d2xx_paused = True
                time.sleep(0.02)
                continue
            self._d2xx_paused = False
            if dev is not None:
                try:
                    with self._dmx_lock:
                        frame = b'\x00' + bytes(self.dmx_data[0][:512])
                    # BREAK ≥ 88 µs puis MAB ≥ 8 µs, générés sur la puce
                    dev.setBreakOn()
                    time.sleep(0.0001)
                    dev.setBreakOff()
                    time.sleep(0.000012)
                    dev.write(frame)
                    self.connected = True
                    self._d2xx_err_count = 0
                    if _dbg:
                        _now = time.monotonic()
                        _gap = _now - _last_ok
                        if _gap > 0.15:
                            print(f"[DMX] trou {_gap*1000:.0f} ms dans le flux (pause={self._d2xx_pause})")
                        _last_ok = _now
                        _fps_n += 1
                        if _now - _fps_t0 >= 1.0:
                            _fps = _fps_n / (_now - _fps_t0)
                            if _fps < 28:
                                print(f"[DMX] cadence {_fps:.0f} fps (cible ~36)")
                            _fps_t0 = _now
                            _fps_n = 0
                    # CRUCIAL : dev.write() (D2XX) ne bloque PAS — la trame (513
                    # octets @ 250 kbaud ≈ 22,6 ms) part en arrière-plan. Il faut
                    # attendre qu'elle soit ENTIÈREMENT transmise avant le break
                    # suivant, sinon le break tronque la fin de trame → le
                    # récepteur perd la synchro → strobe intermittent (en série,
                    # ser.flush() faisait cette attente ; pas dev.write()).
                    # time.sleep ne rend jamais la main avant le délai demandé,
                    # donc ~26 ms garantit la transmission complète + marge.
                    time.sleep(0.026)
                    continue
                except Exception as e:
                    # Hoquet USB transitoire : on saute juste cette frame et on
                    # réessaie au cycle suivant. On ne ferme/rouvre la puce
                    # (ce qui réinitialise la ligne FTDI → flash visible + trou
                    # DMX d'~1 s) qu'après plusieurs erreurs CONSÉCUTIVES.
                    self._d2xx_err_count += 1
                    if self._d2xx_err_count >= 5:
                        print(f"ENTTEC D2XX thread: {self._d2xx_err_count} erreurs consécutives — réouverture ({e})")
                        try:
                            dev.close()
                        except Exception:
                            pass
                        self._d2xx = None
                        self.connected = False
                        self._d2xx_err_count = 0
                    else:
                        time.sleep(0.005)
                        continue
            elif not self._d2xx_stop:
                # Reconnexion automatique (boitier rebranché)
                try:
                    index = self._resolve_d2xx_index()
                    dev = ftd2xx.open(index)
                    dev.setBaudRate(250000)
                    dev.setDataCharacteristics(_ftd.BITS_8, _ftd.STOP_BITS_2, _ftd.PARITY_NONE)
                    dev.setFlowControl(_ftd.FLOW_NONE, 0, 0)
                    dev.setLatencyTimer(1)
                    dev.setTimeouts(100, 100)
                    dev.purge(_ftd.PURGE_TX | _ftd.PURGE_RX)
                    self._d2xx = dev
                    self.connected = True
                    print("ENTTEC D2XX : reconnexion")
                except Exception:
                    time.sleep(1.0)
                    continue
            else:
                time.sleep(0.025)
                continue

            elapsed = time.monotonic() - t0
            remaining = 0.025 - elapsed   # ~40 fps
            if remaining > 0.001:
                time.sleep(remaining)

    def _send_enttec_d2xx(self):
        """Maintenu pour compatibilité — le thread dédié gère l'envoi réel."""
        return True

    # ------------------------------------------------------------------
    # Transport ENTTEC DMX USB Pro  (protocole paquet 0x7E / 0xE7)
    # Compatible : ENTTEC Pro, DMXKing, Eurolite USB-DMX512 PRO…
    # Spec publique : https://www.enttec.com/products/controls/dmx-usb/
    # ------------------------------------------------------------------

    @staticmethod
    def _build_pro_packet(dmx_universe):
        """Construit le paquet ENTTEC Pro : SOM + label 6 + size + start_code + data + EOM."""
        data = bytes(dmx_universe[:512])
        size = len(data) + 1          # start code (0x00) + données
        return (
            bytes([0x7E, 6, size & 0xFF, (size >> 8) & 0xFF, 0x00])
            + data
            + bytes([0xE7])
        )

    def _connect_enttec_pro(self):
        if not SERIAL_AVAILABLE:
            print("pyserial non disponible — pip install pyserial")
            self.connected = False
            return False
        if not self.com_port:
            print("Aucun port COM configuré pour l'ENTTEC Pro")
            self.connected = False
            return False
        # Idem transport série : couper le thread en place avant de rouvrir.
        self._stop_pro_thread()

        try:
            self._pro_serial = serial.Serial(
                port=self.com_port,
                baudrate=getattr(self, "pro_baud", 250000),
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
            )
            self.connected = True
            print(f"ENTTEC Pro connecté sur {self.com_port} @ {getattr(self, 'pro_baud', 250000)} bauds")
            self._start_pro_thread()
            return True
        except Exception as e:
            err = str(e)
            if "13" in err or "permission" in err.lower() or "access" in err.lower():
                print(f"ENTTEC Pro ({self.com_port}): port déjà utilisé par une autre application")
            else:
                print(f"Erreur connexion ENTTEC Pro ({self.com_port}): {e}")
            self._pro_serial = None
            self.connected = False
            return False

    def _start_pro_thread(self):
        import threading
        self._pro_stop = False
        self._pro_pause = False
        self._pro_paused = False
        t = threading.Thread(target=self._pro_loop, daemon=True, name="EnttecProDMX")
        t.start()
        self._pro_thread = t

    def _pro_loop(self):
        """Thread ENTTEC Pro : envoie des paquets 7E/E7 à ~25 fps."""
        while not self._pro_stop:
            t0 = time.monotonic()
            ser = self._pro_serial
            # Pause : on garde le port ouvert mais on n'écrit plus, et on
            # acquitte via _pro_paused. Le writer concurrent (diagnostic) attend
            # cet ack avant de toucher au port — sans quoi les deux écrivent sur
            # le même tty et le driver USB série tombe (crash de l'appli).
            if self._pro_pause:
                self._pro_paused = True
                time.sleep(0.02)
                continue
            self._pro_paused = False
            if ser and ser.is_open:
                try:
                    with self._dmx_lock:
                        pkt = self._build_pro_packet(self.dmx_data[0])
                    ser.write(pkt)
                    ser.flush()
                except Exception as e:
                    print(f"ENTTEC Pro thread: {e}")
                    try:
                        ser.close()
                    except Exception:
                        pass
                    self._pro_serial = None
            elif self.com_port and not self._pro_stop:
                try:
                    self._pro_serial = serial.Serial(
                        port=self.com_port, baudrate=getattr(self, "pro_baud", 250000),
                        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE, timeout=0.1,
                    )
                    print(f"ENTTEC Pro: reconnexion sur {self.com_port}")
                except Exception:
                    time.sleep(1.0)
                    continue
            else:
                time.sleep(0.040)
                continue
            elapsed = time.monotonic() - t0
            remaining = 0.040 - elapsed
            if remaining > 0.001:
                time.sleep(remaining)

    def _send_enttec_pro(self):
        """Maintenu pour compatibilité — le thread dédié gère l'envoi réel."""
        return True

    # ------------------------------------------------------------------
    # Transport Art-Net (boitier reseau ElectroConcept, MA, etc.)
    # ------------------------------------------------------------------

    def _connect_artnet(self):
        try:
            if self._socket:
                self._socket.close()
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.connected = True
            print(f"Art-Net connecte vers {self.target_ip}:{self.target_port} (univers {self.universe})")
            return True
        except Exception as e:
            print(f"Erreur connexion Art-Net: {e}")
            self._socket = None
            self.connected = False
            return False

    def _build_artnet_packet(self, universe, seq, data_universe=0):
        """Construit un paquet ArtDMX pour l'univers donne.
        universe     : numero Art-Net envoye dans le paquet
        data_universe: indice dans self.dmx_data (0-3), ou OUTPUT_OFF pour une
                       trame de 512 zeros (sortie desactivee)
        """
        sub_uni = universe & 0xFF
        net     = (universe >> 8) & 0x7F
        if data_universe == OUTPUT_OFF:
            payload = bytes(512)
        else:
            payload = bytes(self.dmx_data[max(0, min(3, data_universe))][:512])
        return (
            b'Art-Net\x00'
            + b'\x00\x50'
            + b'\x00\x0e'
            + bytes([seq])
            + b'\x00'
            + bytes([sub_uni, net])
            + b'\x02\x00'
            + payload
        )

    def _send_artnet(self):
        """Protocole Art-Net ArtDMX (OpCode 0x5000) — envoie les 4 univers."""
        if not self._socket or not self.target_ip:
            return False
        try:
            self._artnet_seq = (self._artnet_seq + 1) % 256
            for sortie in range(4):
                # L'univers Art-Net reste base + n : c'est le cablage physique du
                # Node, qu'on ne change pas. Ce qui est reglable, c'est QUELLES
                # donnees partent sur cette sortie.
                src = self.output_map[sortie] if sortie < len(self.output_map) else sortie
                if src == OUTPUT_INPUT:
                    # Ce port est une ENTREE : on se tait. Emettre ici mettrait
                    # deux sources sur le meme univers (cf. OUTPUT_INPUT).
                    continue
                art_uni = self.universe + sortie
                pkt = self._build_artnet_packet(art_uni, self._artnet_seq, data_universe=src)
                self._socket.sendto(pkt, (self.target_ip, self.target_port))
            self._last_artnet_error = None
            return True
        except Exception as e:
            err = str(e)
            if getattr(self, '_last_artnet_error', None) != err:
                print(f"Erreur Art-Net: {e}")
                self._last_artnet_error = err
            # Recréer le socket si invalide
            try:
                self._socket.close()
            except Exception:
                pass
            try:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except Exception:
                self._socket = None
                self.connected = False
            return False

    # ------------------------------------------------------------------
    # API publique DMX
    # ------------------------------------------------------------------

    def send_dmx(self):
        """Envoie les donnees DMX via le transport actif"""
        if not self.connected:
            return False
        if self.transport == TRANSPORT_ENTTEC:
            return self._send_enttec()
        elif self.transport == TRANSPORT_ENTTEC_D2XX:
            return self._send_enttec_d2xx()
        elif self.transport == TRANSPORT_ENTTEC_PRO:
            return self._send_enttec_pro()
        else:
            return self._send_artnet()

    def set_channel(self, channel, value, universe=0):
        uni = max(0, min(3, int(universe)))
        if 1 <= channel <= 512:
            self.dmx_data[uni][channel - 1] = max(0, min(255, value))

    def get_channel(self, channel, universe=0):
        uni = max(0, min(3, int(universe)))
        if 1 <= channel <= 512:
            return self.dmx_data[uni][channel - 1]
        return 0

    def set_rgb(self, start_channel, r, g, b, universe=0):
        self.set_channel(start_channel,     r, universe)
        self.set_channel(start_channel + 1, g, universe)
        self.set_channel(start_channel + 2, b, universe)

    def blackout(self):
        self.dmx_data = [[0] * 512 for _ in range(4)]

    # ------------------------------------------------------------------
    # Patch projecteurs (inchange)
    # ------------------------------------------------------------------

    def _get_profile(self, proj_key):
        if proj_key in self.projector_profiles:
            return self.projector_profiles[proj_key]
        mode = self.projector_modes.get(proj_key, "5CH")
        return profile_for_mode(mode)

    def _channel_index(self, profile, channel_type):
        try:
            return profile.index(channel_type)
        except ValueError:
            return -1

    def update_from_projectors(self, projectors, effect_speed=0):
        """Met a jour les canaux DMX depuis la liste des projecteurs"""
        with self._dmx_lock:
            self._update_from_projectors_locked(projectors, effect_speed)

    def _update_from_projectors_locked(self, projectors, effect_speed=0):
        """Mise à jour interne — doit être appelée sous _dmx_lock."""
        for i, proj in enumerate(projectors):
            proj_key = f"{proj.group}_{i}"
            if proj_key not in self.projector_channels:
                continue

            channels = self.projector_channels[proj_key]
            profile  = self._get_profile(proj_key)
            universe = self.projector_universes.get(proj_key, 0)

            # Fumee
            if "Smoke" in profile:
                is_muted  = hasattr(proj, 'muted') and proj.muted
                smoke_idx = self._channel_index(profile, "Smoke")
                fan_idx   = self._channel_index(profile, "Fan")
                if smoke_idx >= 0 and smoke_idx < len(channels):
                    smoke = int((proj.level / 100.0) * 255) if not is_muted else 0
                    self.set_channel(channels[smoke_idx], smoke, universe)
                if fan_idx >= 0 and fan_idx < len(channels):
                    fan = getattr(proj, 'fan_speed', 0) if not is_muted else 0
                    self.set_channel(channels[fan_idx], fan, universe)
                continue

            # Mute
            if hasattr(proj, 'muted') and proj.muted:
                # « Tout a zero » n'eteint PAS un spot a trichromie soustractive :
                # zero, c'est le filtre grand ouvert. Le noir se fait au
                # contraire en fermant les trois. Sans canal Dim pour couper le
                # faisceau, une lyre mutee serait restee blanche.
                _mute_sub_cmy = not ({"R", "G", "B"} <= set(profile))
                for _i, ch in enumerate(channels):
                    if ch <= 0:
                        continue
                    _t = profile[_i] if _i < len(profile) else None
                    self.set_channel(
                        ch, 255 if (_mute_sub_cmy and _t in ("C", "M", "Y")) else 0,
                        universe)
                continue

            level  = proj.level if hasattr(proj, 'level') else 0
            dimmer = int((level / 100.0) * 255)

            dim_idx    = self._channel_index(profile, "Dim")
            has_dimmer = dim_idx >= 0 and dim_idx < len(channels)

            if has_dimmer:
                bc = getattr(proj, 'base_color', None) or getattr(proj, 'color', None)
                ec = getattr(proj, 'color', None)
                # Détecter si un effet a modifié proj.color par rapport à base_color*level
                effect_active = False
                if bc and ec and level > 0:
                    exp_r = int(bc.red()   * level / 100)
                    exp_g = int(bc.green() * level / 100)
                    exp_b = int(bc.blue()  * level / 100)
                    effect_active = (abs(ec.red()   - exp_r) > 4 or
                                     abs(ec.green() - exp_g) > 4 or
                                     abs(ec.blue()  - exp_b) > 4)
                elif ec and level == 0 and (ec.red() or ec.green() or ec.blue()):
                    # level=0 mais color non noire → effet actif (ex: strobe ON)
                    effect_active = True

                if effect_active and ec:
                    # Effet actif : extraire couleur pure + luminosité depuis proj.color
                    max_c = max(ec.red(), ec.green(), ec.blue())
                    if max_c > 0:
                        scale = 255.0 / max_c
                        r = min(255, int(ec.red()   * scale))
                        g = min(255, int(ec.green() * scale))
                        b = min(255, int(ec.blue()  * scale))
                        dimmer = max_c  # luminosité effective (0-255)
                    else:
                        r, g, b = 0, 0, 0
                        dimmer = 0
                else:
                    # Mode normal : RGB = couleur pure (base_color), Dim = level
                    r = bc.red()   if bc else 0
                    g = bc.green() if bc else 0
                    b = bc.blue()  if bc else 0
            else:
                # Pas de canal Dim : proj.color a deja level applique, ne pas rediviser
                r = proj.color.red()   if hasattr(proj, 'color') else 0
                g = proj.color.green() if hasattr(proj, 'color') else 0
                b = proj.color.blue()  if hasattr(proj, 'color') else 0

            strobe_idx = self._channel_index(profile, "Strobe")
            has_strobe = strobe_idx >= 0 and strobe_idx < len(channels)
            if not has_strobe and hasattr(proj, 'dmx_mode') and proj.dmx_mode == "Strobe":
                if int(time.time() * 10) % 2 == 0:
                    r, g, b = 0, 0, 0

            _ch_defaults = getattr(proj, 'channel_defaults', {})
            _ch_extras   = getattr(proj, 'channel_extras',   {})

            # Pan/Tilt effectifs : LIMITES d'abord, puis swap et inversion.
            #
            # L'ordre n'est pas cosmetique. Les limites sont exprimees dans le
            # repere de l'APPLICATION — c'est celui du carre de reglage, du
            # point jaune, des positions memorisees et des faders POS. Swap et
            # inversion, eux, ne corrigent que le cablage/l'accrochage en bout
            # de chaine. Clamper apres l'inversion appliquait donc la zone en
            # MIROIR : l'utilisateur tirait la limite droite et la lyre se
            # bloquait a gauche, en continuant d'aller du cote qu'il voulait
            # justement interdire (remonte utilisateur, 28/07/2026).
            _eff_pan  = max(getattr(proj, 'pan_min',  0),
                            min(getattr(proj, 'pan_max',  65535),
                                getattr(proj, 'pan',  32768)))
            _eff_tilt = max(getattr(proj, 'tilt_min', 0),
                            min(getattr(proj, 'tilt_max', 65535),
                                getattr(proj, 'tilt', 32768)))
            if getattr(proj, 'pan_tilt_swap', False):
                _eff_pan, _eff_tilt = _eff_tilt, _eff_pan
            if getattr(proj, 'pan_invert',  False):
                _eff_pan  = 65535 - _eff_pan
            if getattr(proj, 'tilt_invert', False):
                _eff_tilt = 65535 - _eff_tilt

            # Pour les fixtures RGBW : extraire W = min(R,G,B) et le soustraire
            # des canaux RGB pour éviter la contamination blanche (double envoi)
            _has_rgb   = "R" in profile and "G" in profile and "B" in profile
            _has_white = "W" in profile
            _w_extract = min(r, g, b) if (_has_rgb and _has_white) else 0

            # ── Couronne LED : la deuxieme source vit dans le show ───────────
            # Elle sortait 0 en toutes circonstances : sur une lyre a couronne,
            # la moitie de l'appareil restait noire pendant que la tete jouait,
            # et il fallait pousser un curseur a la main pour chaque projecteur.
            # Elle prend maintenant la couleur, le niveau et le strobe du
            # faisceau — la lyre s'allume d'un bloc.
            #
            # `_ring_vals` vide (pas de couronne, ou couronne repassee en
            # manuel) = comportement d'avant, a l'octet pres : les types
            # tombent alors dans `_MANUAL_ONLY` et sortent 0.
            _ring_types = _RING_DRIVEN.intersection(profile)
            _ring_vals  = {}
            if _ring_types and getattr(proj, 'ring_follow', True):
                # Ramener le faisceau a un couple (teinte PURE, intensite),
                # quelle que soit la facon dont il les porte : avec un canal Dim
                # r/g/b sont deja purs, sans lui ils portent deja le niveau.
                if has_dimmer:
                    _rc, _rint = [r, g, b], dimmer
                else:
                    _m = max(r, g, b)
                    _rc = ([int(r * 255 / _m), int(g * 255 / _m), int(b * 255 / _m)]
                           if _m else [0, 0, 0])
                    _rint = _m
                if "RingDim" not in _ring_types:
                    # Pas de gradateur de couronne : le niveau doit passer dans
                    # la couleur, sinon la couronne resterait a fond quoi qu'il
                    # arrive au reste de la lyre.
                    _rc = [int(c * _rint / 255) for c in _rc]
                _r_has_rgb = {"RingR", "RingG", "RingB"} <= _ring_types
                # Meme extraction du blanc que sur le faisceau : sans elle, une
                # couronne RGBW recoit deux fois la composante commune et vire
                # au blanc laiteux.
                _r_w = min(_rc) if (_r_has_rgb and "RingW" in _ring_types) else 0
                _ring_vals = {
                    "RingDim": _rint,
                    "RingR":   max(0, _rc[0] - _r_w),
                    "RingG":   max(0, _rc[1] - _r_w),
                    "RingB":   max(0, _rc[2] - _r_w),
                    # Couronne blanche seule : pas de couleur a rendre, on lui
                    # donne la luminance de la teinte du faisceau.
                    "RingW":   _r_w if _r_has_rgb else
                               min(255, int(_rc[0] * 0.30 + _rc[1] * 0.59 + _rc[2] * 0.11)),
                    "RingStrobe": (int(16 + (getattr(proj, 'strobe_speed', 0) / 100.0) * (250 - 16))
                                   if getattr(proj, 'strobe_speed', 0) > 0 else 0),
                }

            for idx, ch_type in enumerate(profile):
                if idx >= len(channels):
                    break
                ch = channels[idx]
                if ch <= 0:
                    continue

                # Contrôle brut par NUMÉRO DE CANAL, prioritaire sur tout le
                # reste — y compris sur le contrôle par type juste en dessous.
                #
                # C'est la seule façon d'atteindre un canal que MyStrow ne sait
                # pas nommer. Le modèle « une valeur par TYPE » suffit pour une
                # lyre, pas pour un laser : sur un UKing ZQ02622 (28 canaux),
                # 18 canaux ne correspondent à aucun type et sortaient 0, et il
                # n'existait aucun moyen de leur donner une valeur — deux canaux
                # posés sur « Mode » auraient de toute façon reçu la MÊME.
                #
                # Le numéro est celui du canal DANS la fixture (1 = son premier
                # canal), pas l'adresse DMX absolue : un profil reste valable
                # quelle que soit l'adresse de patch.
                #
                # ⚠️ Les deux formes de clé sont acceptées : un aller-retour par
                # le JSON d'un show transforme les clés entières en chaînes.
                _raw = _ch_extras.get(idx + 1)
                if _raw is None:
                    _raw = _ch_extras.get(str(idx + 1))
                if _raw is not None:
                    self.set_channel(ch, max(0, min(255, int(_raw))), universe)
                    continue

                # Contrôle brut par TYPE (curseurs avancés du menu contextuel)
                if ch_type in _ch_extras:
                    self.set_channel(ch, _ch_extras[ch_type], universe)
                    continue

                if ch_type == "R":
                    ch_val = max(0, r - _w_extract)
                elif ch_type == "G":
                    ch_val = max(0, g - _w_extract)
                elif ch_type == "B":
                    ch_val = max(0, b - _w_extract)
                elif ch_type == "W":
                    # Fixture RGBW : W = composante commune extraite + boost manuel
                    # Fixture sans RGB : luminance standard
                    if _has_rgb:
                        ch_val = min(255, _w_extract + getattr(proj, 'white_boost', 0))
                    else:
                        ch_val = min(255, int(r * 0.30 + g * 0.59 + b * 0.11)
                                     + getattr(proj, 'white_boost', 0))
                elif ch_type == "Ambre":
                    # Ambre piloté UNIQUEMENT par le curseur avancé (amber_boost)
                    # ou le contrôle brut (_ch_extras, géré plus haut). Pas de
                    # dérivation auto depuis le RGB : sinon un rouge pur allumait
                    # aussi la LED ambre (r*0.75) → sortie orange au lieu de rouge.
                    ch_val = min(255, getattr(proj, 'amber_boost', 0))
                elif ch_type == "Orange":
                    # Orange : idem, piloté uniquement par orange_boost.
                    ch_val = min(255, getattr(proj, 'orange_boost', 0))
                elif ch_type == "UV":
                    ch_val = getattr(proj, 'uv', 0)
                elif ch_type == "Zoom":
                    ch_val = getattr(proj, 'zoom', 0)
                elif ch_type == "Iris":
                    ch_val = getattr(proj, 'iris', 0)
                elif ch_type in ("Dim", "Dim2"):
                    ch_val = dimmer
                    # Strobe artificiel pour gradateurs 1 canal (pas de canal Strobe hardware)
                    _spd = getattr(proj, 'strobe_speed', 0)
                    if _spd > 0 and not has_strobe and getattr(proj, 'fixture_type', '') == 'Gradateur':
                        _freq = 0.5 + (_spd / 100.0) * 14.5  # 0.5 Hz → 15 Hz
                        if int(time.time() * _freq * 2) % 2 == 1:
                            ch_val = 0
                elif ch_type == "Reset":
                    ch_val = 0  # repos : ne pas déclencher le reset
                elif ch_type == "Unused":
                    # Canal présent dans le protocole mais que MyStrow ne pilote
                    # pas : il occupe sa place pour que les canaux suivants
                    # gardent leur numéro, et sort 0. Branche explicite plutôt
                    # que de compter sur le `else` final : c'est le repli des
                    # canaux inconnus à l'import, on veut que ce soit lisible.
                    ch_val = 0
                elif ch_type == "Strobe":
                    spd = getattr(proj, 'strobe_speed', 0)
                    if spd > 0:
                        ch_val = int(16 + (spd / 100.0) * (250 - 16))
                    elif hasattr(proj, 'dmx_mode') and proj.dmx_mode == "Strobe":
                        ch_val = int(16 + (effect_speed / 100.0) * (250 - 16)) if effect_speed > 0 else 100
                    else:
                        ch_val = 0
                elif ch_type == "Pan":
                    ch_val = _eff_pan >> 8
                elif ch_type == "PanFine":
                    ch_val = _eff_pan & 0xFF
                elif ch_type == "Tilt":
                    ch_val = _eff_tilt >> 8
                elif ch_type == "TiltFine":
                    ch_val = _eff_tilt & 0xFF
                elif ch_type == "Gobo1":
                    ch_val = getattr(proj, 'gobo', 0)
                elif ch_type == "Gobo1Rot":
                    ch_val = getattr(proj, 'gobo_rotation', 0)
                elif ch_type == "ColorWheel":
                    ch_val = getattr(proj, 'color_wheel', 0)
                elif ch_type == "Shutter":
                    shutter = getattr(proj, 'shutter', 255)
                    raw = shutter if not proj.muted else 0
                    ch_val = (255 - raw) if getattr(proj, 'shutter_inverted', False) else raw
                elif ch_type == "Prism":
                    ch_val = getattr(proj, 'prism', 0)
                elif ch_type == "PrismRot":
                    ch_val = getattr(proj, 'prism_rotation', 0)
                elif ch_type == "Effects":
                    ch_val = getattr(proj, 'effects', 0)
                elif ch_type in ("C", "M", "Y"):
                    if _has_rgb:
                        # LED a emetteurs cyan/magenta/jaune : ADDITIF. Comme
                        # l'ambre et l'orange, jamais derive du RGB — sinon un
                        # rouge pur allumerait le magenta et virerait rose. Se
                        # pousse au curseur brut.
                        ch_val = 0
                    else:
                        # Spot a drapeaux : SOUSTRACTIF. 0 = filtre ouvert,
                        # 255 = couleur pleine. Le Dim porte deja le niveau, ces
                        # canaux ne portent que la teinte — d'ou l'usage de la
                        # couleur PURE (r/g/b sont deja la teinte des qu'il y a
                        # un Dim). Sur les rares fixtures sans Dim, r/g/b sont
                        # attenues et la formule ferme les filtres a mesure : le
                        # noir se fait alors correctement par soustraction.
                        ch_val = 255 - (r if ch_type == "C" else
                                        g if ch_type == "M" else b)
                elif ch_type == "Lime":
                    # Emetteur additif supplementaire, manuel uniquement (meme
                    # regle que Ambre/Orange).
                    ch_val = 0
                elif ch_type in _ring_vals:
                    # Couronne qui suit le show (cf. bloc « Couronne LED »).
                    ch_val = max(0, min(255, int(_ring_vals[ch_type])))
                elif ch_type in _MANUAL_ONLY:
                    # Couronne repassee en manuel, frost, roue d'animation,
                    # courbe, micro… Aucun
                    # etat dans Projector : leur valeur vient du curseur des
                    # « canaux avances » (channel_extras, traite plus haut) ou
                    # de la valeur fixe du mode. 0 au repos, et c'est voulu —
                    # une couronne ne doit pas s'allumer toute seule.
                    #
                    # Branche explicite plutot que de laisser faire le `else`
                    # final : elle documente que ces canaux sont pilotables, a
                    # la difference d'« Unused » qui, lui, ne l'est pas.
                    ch_val = 0
                elif ch_type in ("CTO", "CTB"):
                    # 0 = aucune correction, et c'est le repos voulu : une lyre
                    # ne doit pas partir avec un filtre pose. La valeur se donne
                    # au curseur brut (channel_extras), traite plus haut, ou par
                    # `channel_defaults` juste en dessous.
                    ch_val = 0
                elif ch_type == "Focus":
                    ch_val = getattr(proj, 'focus', 0)
                elif ch_type == "Gobo2":
                    ch_val = getattr(proj, 'gobo2', 0)
                elif ch_type == "Speed":
                    # 0 = deplacement le plus rapide sur la quasi-totalite des
                    # lyres : c'est bien le repos attendu, pas une lyre bridee.
                    ch_val = getattr(proj, 'speed', 0)
                elif ch_type == "Mode":
                    # Jamais derive de quoi que ce soit : les plages de ce canal
                    # declenchent reset, extinction de lampe, calibration. Il ne
                    # bouge que si l'utilisateur le demande explicitement.
                    ch_val = getattr(proj, 'mode_value', 0)
                else:
                    ch_val = 0

                # Valeur par défaut : appliquée quand le canal sortirait 0
                if ch_val == 0 and ch_type in _ch_defaults:
                    ch_val = _ch_defaults[ch_type]

                self.set_channel(ch, ch_val, universe)

    def set_projector_patch(self, proj_key, channels, universe=0, profile=None, mode=None):
        self.projector_channels[proj_key] = channels
        self.projector_universes[proj_key] = max(0, min(3, int(universe)))
        if profile is not None:
            # Le moteur garde SA copie du profil et ne relit pas `proj.dmx_profile`
            # ensuite : canonicaliser ici aussi, sinon un patch restaure depuis la
            # config disque rentrerait avec l'ancien vocabulaire et court-circuiterait
            # la propriete de Projector.
            from core import canonical_profile
            profile = canonical_profile(profile)
            self.projector_profiles[proj_key] = profile
            name = profile_name(profile)
            self.projector_modes[proj_key] = name if name else "CUSTOM"
        elif mode is not None:
            self.projector_modes[proj_key] = mode
            self.projector_profiles[proj_key] = profile_for_mode(mode)

    def clear_patch(self):
        self.projector_channels.clear()
        self.projector_modes.clear()
        self.projector_profiles.clear()
        self.projector_universes.clear()
