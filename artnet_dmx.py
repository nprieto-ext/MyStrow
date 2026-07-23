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
    "R", "G", "B", "W", "Dim", "Strobe", "UV", "Ambre", "Orange", "Zoom", "Iris",
    "Smoke", "Fan",
    "Pan", "PanFine", "Tilt", "TiltFine", "Gobo1", "Gobo1Rot", "Gobo2",
    "Prism", "PrismRot", "Focus", "ColorWheel", "Shutter", "Speed", "Mode", "Effects",
]

# Noms courts pour l'affichage dans les combos
CHANNEL_DISPLAY = {
    "R": "R", "G": "G", "B": "B", "W": "W",
    "Dim": "Dim", "Strobe": "Strob", "UV": "UV",
    "Ambre": "Ambre", "Orange": "Orange", "Zoom": "Zoom", "Iris": "Iris",
    "Smoke": "Smoke", "Fan": "Fan",
    "Pan": "Pan", "PanFine": "PanF", "Tilt": "Tilt", "TiltFine": "TiltF",
    "Gobo1": "Gobo1", "Gobo1Rot": "GoboR", "Gobo2": "Gobo2",
    "Prism": "Prism", "PrismRot": "PrsmR", "Focus": "Focus",
    "ColorWheel": "CWheel", "Shutter": "Shut", "Speed": "Speed", "Mode": "Mode",
    "Effects": "FX",
}


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
        self.universe = 0             # Univers Art-Net sortie 1 (0-based)
        self.universe2 = 1            # Univers Art-Net sortie 2 (miroir)
        self.mirror_output = True     # Envoyer sur les 2 sorties du NODE (miroir par defaut)
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
                self.pro_baud      = int(cfg.get("pro_baud", 250000))
        except Exception:
            pass

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
                    "pro_baud":      getattr(self, "pro_baud", 250000),
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
        if target != TRANSPORT_ENTTEC:
            self._enttec_stop = True   # désactive aussi la reconnexion auto du thread
            if self._serial and self._serial.is_open:
                try: self._serial.close()
                except Exception: pass
            self._serial = None
        if target != TRANSPORT_ENTTEC_D2XX:
            self._stop_d2xx_thread()
        if target != TRANSPORT_ENTTEC_PRO:
            self._pro_stop = True
            if self._pro_serial and self._pro_serial.is_open:
                try: self._pro_serial.close()
                except Exception: pass
            self._pro_serial = None
        if target != TRANSPORT_ARTNET and self._socket:
            try: self._socket.close()
            except Exception: pass
            self._socket = None

    def disconnect(self):
        """Ferme toutes les connexions ouvertes"""
        self._enttec_stop = True
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None
        self._stop_d2xx_thread()
        self._pro_stop = True
        if self._pro_serial and self._pro_serial.is_open:
            self._pro_serial.close()
        self._pro_serial = None
        if self._socket:
            self._socket.close()
        self._socket = None
        self.connected = False

    # ------------------------------------------------------------------
    # Transport ENTTEC Open DMX USB
    # ------------------------------------------------------------------

    def _connect_enttec(self):
        if not SERIAL_AVAILABLE:
            print("pyserial non disponible — pip install pyserial")
            self.connected = False
            return False

        if not self.com_port:
            print("Aucun port COM configure pour l'ENTTEC")
            self.connected = False
            return False

        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._serial = serial.Serial(
                port=self.com_port,
                baudrate=250000,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_TWO,
                timeout=0.1,
            )
            self.connected = True
            print(f"ENTTEC Open DMX USB connecte sur {self.com_port}")
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

    def _start_enttec_thread(self):
        import threading
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
                        # Méthode 2 : baud-rate trick — break généré par un 0x00 @ 100 kbaud
                        # (10 bits × 10 µs = 100 µs de LOW = break valide)
                        ser.baudrate = 100000
                        ser.reset_output_buffer()
                        ser.write(b'\x00')
                        ser.flush()
                        time.sleep(0.0015)     # 1.5 ms — marge pour latence USB macOS
                        ser.reset_output_buffer()
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
                    self._serial = serial.Serial(
                        port=self.com_port,
                        baudrate=250000,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_TWO,
                        timeout=0.1,
                    )
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
        try:
            if self._pro_serial and self._pro_serial.is_open:
                self._pro_serial.close()
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
        data_universe: indice dans self.dmx_data (0-3) dont les donnees sont utilisees
        """
        sub_uni = universe & 0xFF
        net     = (universe >> 8) & 0x7F
        return (
            b'Art-Net\x00'
            + b'\x00\x50'
            + b'\x00\x0e'
            + bytes([seq])
            + b'\x00'
            + bytes([sub_uni, net])
            + b'\x02\x00'
            + bytes(self.dmx_data[max(0, min(3, data_universe))][:512])
        )

    def _send_artnet(self):
        """Protocole Art-Net ArtDMX (OpCode 0x5000) — envoie les 4 univers."""
        if not self._socket or not self.target_ip:
            return False
        try:
            self._artnet_seq = (self._artnet_seq + 1) % 256
            for uni_idx in range(4):
                art_uni = self.universe + uni_idx  # univers Art-Net = base + offset
                pkt = self._build_artnet_packet(art_uni, self._artnet_seq, data_universe=uni_idx)
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
                for ch in channels:
                    if ch > 0:
                        self.set_channel(ch, 0, universe)
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

            # Pan/Tilt effectifs : swap puis inversion, puis limites
            _raw_pan  = getattr(proj, 'pan',  32768)
            _raw_tilt = getattr(proj, 'tilt', 32768)
            if getattr(proj, 'pan_tilt_swap', False):
                _raw_pan, _raw_tilt = _raw_tilt, _raw_pan
            if getattr(proj, 'pan_invert',  False):
                _raw_pan  = 65535 - _raw_pan
            if getattr(proj, 'tilt_invert', False):
                _raw_tilt = 65535 - _raw_tilt
            _eff_pan  = max(getattr(proj, 'pan_min',  0),
                            min(getattr(proj, 'pan_max',  65535), _raw_pan))
            _eff_tilt = max(getattr(proj, 'tilt_min', 0),
                            min(getattr(proj, 'tilt_max', 65535), _raw_tilt))

            # Pour les fixtures RGBW : extraire W = min(R,G,B) et le soustraire
            # des canaux RGB pour éviter la contamination blanche (double envoi)
            _has_rgb   = "R" in profile and "G" in profile and "B" in profile
            _has_white = "W" in profile
            _w_extract = min(r, g, b) if (_has_rgb and _has_white) else 0

            for idx, ch_type in enumerate(profile):
                if idx >= len(channels):
                    break
                ch = channels[idx]
                if ch <= 0:
                    continue

                # Contrôle brut prioritaire (curseurs avancés du menu contextuel)
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
                elif ch_type in ("Gobo2", "Focus", "Speed", "Mode"):
                    ch_val = 0
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
