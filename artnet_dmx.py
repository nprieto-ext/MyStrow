"""
Gestion de l'envoi DMX :
  - ENTTEC Open DMX USB (port serie 250000 bauds)
  - Boitier reseau Art-Net (ElectroConcept, MA Lighting, etc.)
"""
import os
import json
import socket
import struct
import time

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

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
    "Pan", "PanFine", "Tilt", "TiltFine", "Gobo1", "Gobo2",
    "Prism", "Focus", "ColorWheel", "Shutter", "Speed", "Mode",
]

# Noms courts pour l'affichage dans les combos
CHANNEL_DISPLAY = {
    "R": "R", "G": "G", "B": "B", "W": "W",
    "Dim": "Dim", "Strobe": "Strob", "UV": "UV",
    "Ambre": "Ambre", "Orange": "Orange", "Zoom": "Zoom", "Iris": "Iris",
    "Smoke": "Smoke", "Fan": "Fan",
    "Pan": "Pan", "PanFine": "PanF", "Tilt": "Tilt", "TiltFine": "TiltF",
    "Gobo1": "Gobo1", "Gobo2": "Gobo2", "Prism": "Prism", "Focus": "Focus",
    "ColorWheel": "CWheel", "Shutter": "Shut", "Speed": "Speed", "Mode": "Mode",
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
TRANSPORT_ENTTEC = "enttec"   # ENTTEC Open DMX USB (serie)
TRANSPORT_ARTNET = "artnet"   # Boitier reseau Art-Net (ElectroConcept...)


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

        # --- ENTTEC Open DMX USB ---
        self.com_port = None
        self._serial = None

        # --- Art-Net reseau ---
        self.target_ip = "2.0.0.15"
        self.target_port = 6454       # Port Art-Net standard
        self.universe = 0             # Univers Art-Net (0-based)
        self._artnet_seq = 0
        self._socket = None

        # --- Etat commun ---
        self.connected = False
        self.dmx_data = [0] * 512

        # --- Patch projecteurs ---
        self.projector_channels = {}
        self.projector_profiles = {}
        self.projector_modes = {}     # Retro-compat

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
                _stored_ip = cfg.get("target_ip", "2.0.0.15")
                # Corriger une éventuelle IP non-Art-Net stockée par erreur
                self.target_ip = _stored_ip if _stored_ip.startswith("2.") else "2.0.0.15"
                self.target_port  = int(cfg.get("target_port", 6454))
                self.universe     = int(cfg.get("universe", 0))
        except Exception:
            pass

    def _save_config(self):
        try:
            with open(self.CONFIG_FILE, "w") as f:
                json.dump({
                    "transport":    self.transport,
                    "product_id":   self.product_id,
                    "product_name": self.product_name,
                    "com_port":     self.com_port,
                    "target_ip":    self.target_ip,
                    "target_port":  self.target_port,
                    "universe":     self.universe,
                }, f, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Connexion (route vers le bon transport)
    # ------------------------------------------------------------------

    def connect(self, com_port=None, target_ip=None, target_port=None,
                universe=None, transport=None, product_id=None, product_name=None):
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
        if target_ip is not None:
            self.target_ip = target_ip
        if target_port is not None:
            self.target_port = int(target_port)
        if universe is not None:
            self.universe = int(universe)

        self._save_config()

        if self.transport == TRANSPORT_ENTTEC:
            return self._connect_enttec()
        else:
            return self._connect_artnet()

    def disconnect(self):
        """Ferme toutes les connexions ouvertes"""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None
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
            return True
        except Exception as e:
            print(f"Erreur connexion ENTTEC ({self.com_port}): {e}")
            self._serial = None
            self.connected = False
            return False

    def _send_enttec(self):
        """Protocole ENTTEC Open DMX USB : Break + MAB + 0x00 + 512 canaux"""
        if not self._serial or not self._serial.is_open:
            return False
        try:
            self._serial.send_break(duration=0.001)
            self._serial.write(b'\x00' + bytes(self.dmx_data[:512]))
            return True
        except Exception as e:
            print(f"Erreur envoi ENTTEC: {e}")
            self.connected = False
            return False

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

    def _send_artnet(self):
        """Protocole Art-Net ArtDMX (OpCode 0x5000)"""
        if not self._socket or not self.target_ip:
            return False
        try:
            self._artnet_seq = (self._artnet_seq + 1) % 256
            sub_uni = self.universe & 0xFF
            net     = (self.universe >> 8) & 0x7F
            packet = (
                b'Art-Net\x00'                           # ID
                + b'\x00\x50'                            # OpCode ArtDMX (LE)
                + b'\x00\x0e'                            # ProtVer 14
                + bytes([self._artnet_seq])              # Sequence
                + b'\x00'                                # Physical
                + bytes([sub_uni, net])                  # SubUni / Net
                + b'\x02\x00'                            # Length = 512 (BE)
                + bytes(self.dmx_data[:512])
            )
            self._socket.sendto(packet, (self.target_ip, self.target_port))
            self._last_artnet_error = None   # Effacer l'erreur précédente si succès
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
        else:
            return self._send_artnet()

    def set_channel(self, channel, value):
        if 1 <= channel <= 512:
            self.dmx_data[channel - 1] = max(0, min(255, value))

    def get_channel(self, channel):
        if 1 <= channel <= 512:
            return self.dmx_data[channel - 1]
        return 0

    def set_rgb(self, start_channel, r, g, b):
        self.set_channel(start_channel, r)
        self.set_channel(start_channel + 1, g)
        self.set_channel(start_channel + 2, b)

    def blackout(self):
        self.dmx_data = [0] * 512

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
        for i, proj in enumerate(projectors):
            proj_key = f"{proj.group}_{i}"
            if proj_key not in self.projector_channels:
                continue

            channels = self.projector_channels[proj_key]
            profile  = self._get_profile(proj_key)

            # Fumee
            if "Smoke" in profile:
                is_muted  = hasattr(proj, 'muted') and proj.muted
                smoke_idx = self._channel_index(profile, "Smoke")
                fan_idx   = self._channel_index(profile, "Fan")
                if smoke_idx >= 0 and smoke_idx < len(channels):
                    smoke = int((proj.level / 100.0) * 255) if not is_muted else 0
                    self.set_channel(channels[smoke_idx], smoke)
                if fan_idx >= 0 and fan_idx < len(channels):
                    fan = getattr(proj, 'fan_speed', 0) if not is_muted else 0
                    self.set_channel(channels[fan_idx], fan)
                continue

            # Mute
            if hasattr(proj, 'muted') and proj.muted:
                for ch in channels:
                    if ch > 0:
                        self.set_channel(ch, 0)
                continue

            level  = proj.level if hasattr(proj, 'level') else 0
            dimmer = int((level / 100.0) * 255)

            dim_idx    = self._channel_index(profile, "Dim")
            has_dimmer = dim_idx >= 0 and dim_idx < len(channels)

            if has_dimmer:
                # Canal Dim gere la luminosite : RGB = couleur pure (base_color)
                bc = getattr(proj, 'base_color', None) or getattr(proj, 'color', None)
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

            for idx, ch_type in enumerate(profile):
                if idx >= len(channels):
                    break
                ch = channels[idx]
                if ch <= 0:
                    continue

                if ch_type == "R":
                    self.set_channel(ch, r)
                elif ch_type == "G":
                    self.set_channel(ch, g)
                elif ch_type == "B":
                    self.set_channel(ch, b)
                elif ch_type == "W":
                    self.set_channel(ch, min(r, g, b))
                elif ch_type == "Ambre":
                    ambre = int(min(r, g * 0.5) * 0.8) if r > 0 else 0
                    self.set_channel(ch, ambre)
                elif ch_type == "Orange":
                    orange = int(min(r, g * 0.6) * 0.9) if r > 0 else 0
                    self.set_channel(ch, orange)
                elif ch_type == "UV":
                    self.set_channel(ch, 0)
                elif ch_type == "Zoom":
                    self.set_channel(ch, getattr(proj, 'zoom', 0))
                elif ch_type == "Iris":
                    self.set_channel(ch, getattr(proj, 'iris', 0))
                elif ch_type == "Dim":
                    self.set_channel(ch, dimmer)
                elif ch_type == "Strobe":
                    spd = getattr(proj, 'strobe_speed', 0)
                    if spd > 0:
                        strobe_value = int(16 + (spd / 100.0) * (250 - 16))
                    elif hasattr(proj, 'dmx_mode') and proj.dmx_mode == "Strobe":
                        strobe_value = int(16 + (effect_speed / 100.0) * (250 - 16)) if effect_speed > 0 else 100
                    else:
                        strobe_value = 0
                    self.set_channel(ch, strobe_value)
                elif ch_type == "Pan":
                    self.set_channel(ch, getattr(proj, 'pan', 128))
                elif ch_type == "PanFine":
                    self.set_channel(ch, (getattr(proj, 'pan', 128) * 256) % 256)
                elif ch_type == "Tilt":
                    self.set_channel(ch, getattr(proj, 'tilt', 128))
                elif ch_type == "TiltFine":
                    self.set_channel(ch, (getattr(proj, 'tilt', 128) * 256) % 256)
                elif ch_type == "Gobo1":
                    self.set_channel(ch, getattr(proj, 'gobo', 0))
                elif ch_type == "ColorWheel":
                    self.set_channel(ch, getattr(proj, 'color_wheel', 0))
                elif ch_type == "Shutter":
                    shutter = getattr(proj, 'shutter', 255)
                    self.set_channel(ch, shutter if not proj.muted else 0)
                elif ch_type in ("Gobo2", "Prism", "Focus", "Speed", "Mode"):
                    self.set_channel(ch, 0)

    def set_projector_patch(self, proj_key, channels, profile=None, mode=None):
        self.projector_channels[proj_key] = channels
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
