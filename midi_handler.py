"""
Gestionnaire MIDI multi-contrôleur
Supporte: AKAI APC40, AKAI APC20, AKAI APC Mini, Novation Launchpad Mini MK1/MK2/MK3, AKAI MIDImix
"""
import sys
import platform
import threading
from PySide6.QtCore import QObject, Signal, QTimer

from core import MIDI_AVAILABLE
from controller_profile import find_profile_for_port, build_reverse_maps

# Sur Apple Silicon (M1/M2/M3/M4/M5), les messages 0x96 (Note On ch7 = LED bright)
# ne sont pas transmis correctement par CoreMIDI/USB → LEDs toujours en mode dim (0x90).
_APPLE_SILICON = sys.platform == 'darwin' and platform.machine() == 'arm64'

rtmidi = None
_USING_RTMIDI2 = False
if MIDI_AVAILABLE:
    try:
        import rtmidi
    except ImportError:
        try:
            import rtmidi2 as rtmidi
            _USING_RTMIDI2 = True
        except ImportError:
            pass

# ─── Contrôleurs supportés (ordre de priorité) ───────────────────────────────
SUPPORTED_CONTROLLERS = [
    {
        'id': 'apc40_mk2',
        'name': 'AKAI APC40 MkII',
        # MkII avant MK1 — 'MKII' est plus spécifique que 'APC40' seul
        'keywords': ['APC40 MKII', 'APC40 MK2', 'APC 40 MKII', 'APC 40 MK2'],
        'has_faders': True,
        'has_pads': True,
    },
    {
        'id': 'apc40',
        'name': 'AKAI APC40',
        # 'APC40' doit passer avant 'APC' pour éviter que l'APC Mini ne match en fallback
        'keywords': ['APC40', 'APC 40'],
        'has_faders': True,
        'has_pads': True,
    },
    {
        'id': 'apc20',
        'name': 'AKAI APC20',
        # APC20 avant APC Mini : 'APC' matcherait 'APC20' sinon
        'keywords': ['APC20', 'APC 20'],
        'has_faders': True,
        'has_pads': True,
    },
    {
        'id': 'apc_mini',
        'name': 'AKAI APC Mini',
        'keywords': ['APC MINI', 'APC'],
        'has_faders': True,
        'has_pads': True,
    },
    {
        'id': 'launchpad_mini_mk3',
        'name': 'Novation Launchpad Mini MK3',
        # MK3 avant MK2/MK1 : 'LAUNCHPAD MINI' matcherait sinon en fallback.
        # Sur Windows le port s'appelle 'LPMiniMK3', sur Mac 'Launchpad Mini MK3'.
        'keywords': ['LAUNCHPAD MINI MK3', 'LPMINIMK3', 'MINI MK3'],
        # Le MK3 communique (pads ET LED, en Programmer mode) via le PORT DAW,
        # pas le premier port MIDI. Sur Windows = MIDIIN2/MIDIOUT2, sur Mac = "DAW".
        'prefer_keywords': ['MIDIIN2', 'MIDIOUT2', 'DAW'],
        'has_faders': False,
        'has_pads': True,
    },
    {
        'id': 'launchpad_mk2',
        'name': 'Novation Launchpad MK2',
        'keywords': ['LAUNCHPAD MK2', 'LAUNCHPAD MK 2'],
        'has_faders': False,
        'has_pads': True,
    },
    {
        'id': 'launchpad_mini_mk2',
        'name': 'Novation Launchpad Mini MK2',
        'keywords': ['LAUNCHPAD MINI MK2'],
        'has_faders': False,
        'has_pads': True,
    },
    {
        'id': 'launchpad_mini_mk1',
        'name': 'Novation Launchpad Mini',
        'keywords': ['LAUNCHPAD MINI', 'LAUNCHPAD'],
        'has_faders': False,
        'has_pads': True,
    },
    {
        'id': 'midimix',
        'name': 'AKAI MIDImix',
        'keywords': ['MIDIMIX', 'MIDI MIX'],
        'has_faders': True,
        'has_pads': False,
    },
]

# ─── APC40: notes et CCs ─────────────────────────────────────────────────────
# Grille clip slots : channel = track (0-7), note = 53 + row (rows 0-4)
_APC40_CLIP_BASE_NOTE   = 53   # 5 lignes de clips : notes 53-57
# Boutons Scene Launch (équiv. colonne 8) : channel 0, note = 82 + row
_APC40_SCENE_BASE_NOTE  = 82   # notes 82-86
# Faders de piste : CC 7, channel = track (0-7)
_APC40_TRACK_VOL_CC     = 7
# Fader master : CC 14, channel 0  → index fader 8
_APC40_MASTER_VOL_CC    = 14
# Bouton Activator/Mute par piste : Note 50, channel = track (0-7)
_APC40_ACTIVATOR_NOTE   = 50
# Tap Tempo : Note 99 (bouton dédié), channel 0
_APC40_TAP_TEMPO_NOTE   = 99

# ─── APC20: même layout que APC40 MK1, tap tempo sur note 98 (Shift) ────────
_APC20_TAP_TEMPO_NOTE = 98

# ─── MIDImix: CCs faders et notes boutons ────────────────────────────────────
# Fader index 0-7 = ch1-8, index 8 = master
_MIDIMIX_FADER_CC = {19: 0, 23: 1, 27: 2, 31: 3, 49: 4, 53: 5, 57: 6, 61: 7, 62: 8}
# Mute buttons notes → fader index 0-7
_MIDIMIX_MUTE_NOTE = {1: 0, 4: 1, 7: 2, 10: 3, 13: 4, 16: 5, 19: 6, 22: 7}
# REC ARM button notes (pour feedback LED) → fader index 0-7
_MIDIMIX_REC_NOTE  = {0: 0, 3: 1, 6: 2, 9: 3, 12: 4, 15: 5, 18: 6, 21: 7}
_MIDIMIX_BANK_LEFT  = 25  # → tap tempo
_MIDIMIX_BANK_RIGHT = 26

# ─── Launchpad Mini MK1/MK2 LED color map ────────────────────────────────────
# LP Mini bicolor: velocity = 16*G + R  (G, R ∈ 0-3)
# Traduit les velocities APC Mini (0-127) vers LP bicolor (0-63 valide)
def _to_lp_mini_vel(apc_vel: int) -> int:
    """Convertit une velocity APC/générique vers LP Mini bicolor."""
    if apc_vel == 0:
        return 0
    if apc_vel <= 5:    # rouge dim
        return 1
    if apc_vel <= 15:   # rouge
        return 3
    if apc_vel <= 25:   # vert dim
        return 16
    if apc_vel <= 40:   # orange
        return 35
    if apc_vel <= 60:   # vert moyen
        return 32
    if apc_vel <= 80:   # vert bright
        return 48
    if apc_vel <= 100:  # amber
        return 51
    return 48           # vert bright par défaut


# ─── Launchpad Mini MK3 : velocity APC → RGB réel (pour le SysEx RGB) ─────────
# Le MK3 pilote ses LED en RGB (0-127/canal) via SysEx, ce qui permet la couleur
# exacte ET la luminosité (pads inactifs atténués). On reconvertit la velocity
# APC vers la vraie couleur source (cf. HEX_COLOR_MAP de core.py).
_LP_MK3_VEL_TO_RGB = {
    1:  (255, 255, 255),   # blanc
    3:  (255, 255, 255),   # blanc
    5:  (255, 0,   0),     # rouge
    9:  (255, 136, 0),     # orange
    13: (255, 221, 0),     # jaune
    21: (0,   255, 0),     # vert
    37: (0,   221, 221),   # cyan
    45: (0,   0,   255),   # bleu
    53: (255, 0,   255),   # magenta
}


def _to_apc40_vel(apc_vel: int) -> int:
    """Convertit une velocity APC Mini vers APC40 (palette limitée : vert/jaune/rouge)."""
    # APC40: 0=off 1=green blink 2=green 3=red blink 4=red 5=yellow blink 6=yellow
    if apc_vel == 0:
        return 0
    if apc_vel <= 10:   # rouge
        return 4
    if apc_vel <= 20:   # orange/jaune
        return 6
    return 2            # vert (vert, cyan, bleu, violet → vert par défaut)


def _port_matches(ctrl: dict, port_name: str, require_prefer: bool = True) -> bool:
    """True si le port correspond au contrôleur.

    avoid_keywords  : rejette les ports contenant un de ces mots.
    prefer_keywords : (si require_prefer) impose qu'un de ces mots soit présent —
                      ex: le Launchpad Mini MK3 ne communique que via son port DAW.
    """
    up = port_name.upper()
    for avoid in ctrl.get('avoid_keywords', ()):
        if avoid in up:
            return False
    if require_prefer and ctrl.get('prefer_keywords'):
        if not any(p in up for p in ctrl['prefer_keywords']):
            return False
    return any(kw in up for kw in ctrl['keywords'])


def _detect_controller(ports: list):
    """Retourne (ctrl_dict, port_name) pour le premier contrôleur trouvé, selon priorité.

    Passe 1 : respecte prefer_keywords (port DAW pour le MK3).
    Passe 2 : fallback sans la préférence si aucun port préféré trouvé.
    """
    for require_prefer in (True, False):
        for ctrl in SUPPORTED_CONTROLLERS:
            for port_name in ports:
                if _port_matches(ctrl, port_name, require_prefer):
                    return ctrl, port_name
    return None, None


def _find_out_port(ctrl: dict, out_ports: list):
    """Trouve le port de sortie correspondant au contrôleur donné (préférence d'abord)."""
    for require_prefer in (True, False):
        for port_name in out_ports:
            if _port_matches(ctrl, port_name, require_prefer):
                return port_name
    return None


class MIDIHandler(QObject):
    """Gestionnaire MIDI multi-contrôleur (APC40, APC20, APC Mini, Launchpad Mini, MIDImix)."""

    fader_changed = Signal(int, int)  # (fader_index 0-8, value 0-127)
    pad_pressed   = Signal(int, int)  # (row 0-7, col 0-8)
    pad_released  = Signal(int, int)  # (row 0-7, col 0-8)

    def __init__(self):
        super().__init__()
        self.midi_in  = None
        self.midi_out = None
        self.running  = False
        self.connection_check_timer = None
        self.owner_window = None
        self.debug_mode   = False
        self._midi_queue  = []
        self._midi_lock   = threading.Lock()
        # Callback optionnel pour observer les changements LED (ex: tablette)
        # Signature : led_observer(row, col, color_velocity, brightness_percent)
        self.led_observer = None

        self.controller_type = None   # 'apc_mini' | 'launchpad_mini_mk1/mk2' | 'midimix' | 'custom'
        self.controller_name = ""
        self._raw_capture    = None   # callable(msg) — mode capture brute pour le wizard
        self._custom_profile = None
        self._rev_pad    = {}
        self._rev_mute   = {}
        self._rev_effect = {}
        self._rev_fader  = {}
        self._rev_led    = {}
        self._custom_vel_remap = {}
        # Sur Apple Silicon, 0x96 (LED bright) ne fonctionne pas via CoreMIDI/USB.
        # False = compatibilité (0x90 uniquement, dim mode), True = pleine luminosité (0x96).
        self._apc_bright_mode = not _APPLE_SILICON

        # Contrôleur épinglé par l'utilisateur (id natif, 'custom:<nom>', ou None=Auto).
        # Quand défini, la détection auto ne bascule plus sur un autre contrôleur.
        self.pinned_id = None

        if MIDI_AVAILABLE and rtmidi:
            self.connect_controller()
            if self.midi_in:
                self.midi_timer = QTimer()
                self.midi_timer.timeout.connect(self.poll_midi)
                self.midi_timer.start(10)

            self.connection_check_timer = QTimer()
            self.connection_check_timer.timeout.connect(self.check_connection)
            self.connection_check_timer.start(2000)

    # ─── Connexion ───────────────────────────────────────────────────────────

    def _select_custom(self, in_ports):
        """(profile, in_name) du profil custom à connecter selon l'épinglage."""
        pin = self.pinned_id
        if pin and not str(pin).startswith('custom:'):
            return None, None   # épinglé sur un contrôleur natif → pas de custom
        target = str(pin)[7:] if (pin and str(pin).startswith('custom:')) else None
        try:
            for port_name in in_ports:
                profile = find_profile_for_port(port_name)
                if profile and (target is None or profile.get('name', 'Custom') == target):
                    return profile, port_name
        except Exception as e:
            print(f"⚠️  Lecture profils custom ignorée: {e}")
        return None, None

    def _select_native(self, in_ports):
        """(ctrl, in_name) du contrôleur natif à connecter selon l'épinglage."""
        pin = self.pinned_id
        if pin and str(pin).startswith('custom:'):
            return None, None   # épinglé sur un custom → pas de natif
        if pin:
            ctrl = next((c for c in SUPPORTED_CONTROLLERS if c['id'] == pin), None)
            if ctrl is None:
                return None, None
            for require_prefer in (True, False):
                for p in in_ports:
                    if _port_matches(ctrl, p, require_prefer):
                        return ctrl, p
            return None, None
        return _detect_controller(in_ports)   # Auto

    def _target_present(self, ports):
        """True si le contrôleur cible (épinglé ou auto) est branché."""
        prof, _ = self._select_custom(ports)
        if prof:
            return True
        if self.pinned_id and str(self.pinned_id).startswith('custom:'):
            return False
        ctrl, _ = self._select_native(ports)
        return ctrl is not None

    def list_available_controllers(self):
        """Liste les contrôleurs supportés actuellement branchés.

        Retourne [{'id', 'name', 'port'}] — profils custom puis natifs.
        Sert à peupler le sélecteur de l'UI (menu connexion).
        """
        out = []
        if not rtmidi:
            return out
        try:
            probe = rtmidi.MidiIn()
            ports = probe.get_ports()
            try: probe.close_port()
            except Exception: pass
        except Exception:
            return out
        seen = set()
        for p in ports:
            try:
                prof = find_profile_for_port(p)
            except Exception:
                prof = None
            if prof:
                cid = 'custom:' + prof.get('name', 'Custom')
                if cid not in seen:
                    seen.add(cid)
                    out.append({'id': cid, 'name': prof.get('name', 'Custom'), 'port': p})
        for ctrl in SUPPORTED_CONTROLLERS:
            for p in ports:
                if _port_matches(ctrl, p):
                    if ctrl['id'] not in seen:
                        seen.add(ctrl['id'])
                        out.append({'id': ctrl['id'], 'name': ctrl['name'], 'port': p})
                    break
        return out

    def set_pinned_controller(self, controller_id):
        """Épingle un contrôleur (id natif ou 'custom:<nom>') ; None = Auto.
        Reconnecte immédiatement sur le contrôleur choisi."""
        self.pinned_id = controller_id or None
        self.connect_controller()

    def connect_controller(self):
        """Connecte le contrôleur épinglé, ou le premier supporté (Auto)."""
        if not rtmidi:
            return
        try:
            if self.midi_in:
                try: self.midi_in.close_port()
                except Exception: pass
            if self.midi_out:
                try: self.midi_out.close_port()
                except Exception: pass

            self.midi_in  = rtmidi.MidiIn()
            self.midi_out = rtmidi.MidiOut()

            in_ports  = self.midi_in.get_ports()
            out_ports = self.midi_out.get_ports()

            print(f"[MIDI] Ports IN:  {in_ports}")
            print(f"[MIDI] Ports OUT: {out_ports}")

            # Profil custom (selon l'épinglage ; en Auto, prioritaire sur le natif)
            custom_profile, custom_in_name = self._select_custom(in_ports)

            if custom_profile:
                self.controller_type = 'custom'
                self.controller_name = custom_profile.get('name', 'Custom')
                self._load_custom_profile_data(custom_profile)
                in_idx = in_ports.index(custom_in_name)
                self.midi_in.open_port(in_idx)
                with self._midi_lock:
                    self._midi_queue.clear()
                self.midi_in.set_callback(self._midi_callback)
                self.midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
                print(f"✅ {self.controller_name} connecté (profil custom): {custom_in_name}")
                out_name = None
                for p in out_ports:
                    up = p.upper()
                    for kw in custom_profile.get('keywords', []):
                        if kw.upper() in up:
                            out_name = p
                            break
                    if out_name:
                        break
                if out_name:
                    self.midi_out.open_port(out_ports.index(out_name))
                    print(f"✅ {self.controller_name} output: {out_name}")
                    self.initialize_leds()
                else:
                    self.midi_out = None
                if self.midi_in:
                    if not hasattr(self, 'midi_timer') or not self.midi_timer.isActive():
                        self.midi_timer = QTimer()
                        self.midi_timer.timeout.connect(self.poll_midi)
                        self.midi_timer.start(10)
                return

            ctrl, in_name = self._select_native(in_ports)
            if ctrl is None:
                print("⚠️  Aucun contrôleur MIDI supporté détecté")
                self.midi_in  = None
                self.midi_out = None
                self.controller_type = None
                self.controller_name = ""
                return

            self.controller_type = ctrl['id']
            self.controller_name = ctrl['name']

            in_idx = in_ports.index(in_name)
            self.midi_in.open_port(in_idx)
            with self._midi_lock:
                self._midi_queue.clear()
            self.midi_in.set_callback(self._midi_callback)
            self.midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
            print(f"✅ {ctrl['name']} connecté (input): {in_name}")

            out_name = _find_out_port(ctrl, out_ports)
            if out_name:
                out_idx = out_ports.index(out_name)
                self.midi_out.open_port(out_idx)
                print(f"✅ {ctrl['name']} connecté (output): {out_name}")
                self.initialize_leds()
            else:
                print(f"⚠️  {ctrl['name']} : pas de port de sortie")
                self.midi_out = None

            if self.midi_in:
                if not hasattr(self, 'midi_timer') or not self.midi_timer.isActive():
                    self.midi_timer = QTimer()
                    self.midi_timer.timeout.connect(self.poll_midi)
                    self.midi_timer.start(10)

        except Exception as e:
            print(f"❌ Erreur connexion contrôleur: {e}")
            self.midi_in  = None
            self.midi_out = None
            self.controller_type = None

    # Alias rétrocompatibilité
    def connect_akai(self):
        self.connect_controller()

    def check_connection(self):
        """Vérifie et reconnecte automatiquement si le contrôleur est rebranché."""
        if not rtmidi:
            return
        try:
            probe = rtmidi.MidiIn()
            ports = probe.get_ports()
            try: probe.close_port()
            except Exception: pass
            # Présence du contrôleur CIBLE (épinglé ou auto) — ne rebascule pas
            # sur un autre contrôleur quand l'utilisateur en a épinglé un.
            device_present = self._target_present(ports)
        except Exception:
            return

        if not device_present:
            if self.midi_in or self.midi_out:
                try:
                    if self.midi_in: self.midi_in.close_port()
                except Exception: pass
                try:
                    if self.midi_out: self.midi_out.close_port()
                except Exception: pass
                self.midi_in  = None
                self.midi_out = None
                self.controller_type = None
            return

        # Device présent — déjà connecté ?
        # midi_out peut être None si le contrôleur n'a pas de port output
        if self.midi_in:
            try:
                if self.midi_in.is_port_open():
                    if self.midi_out is None or self.midi_out.is_port_open():
                        return
            except Exception:
                pass
            self.midi_in  = None
            self.midi_out = None

        # Reconnexion silencieuse
        self.connect_controller()
        if self.midi_in and self.midi_out and self.owner_window:
            QTimer.singleShot(200, self.owner_window.activate_default_white_pads)
            QTimer.singleShot(300, self.owner_window.turn_off_all_effects)
            QTimer.singleShot(400, self.owner_window._sync_faders_to_projectors)

    # ─── Réception MIDI ──────────────────────────────────────────────────────

    def _midi_callback(self, event, data=None):
        msg, _dt = event
        with self._midi_lock:
            self._midi_queue.append(list(msg))

    def set_raw_capture(self, callback):
        """Route tous les messages MIDI bruts vers callback(msg) — pour le wizard de mapping."""
        self._raw_capture = callback

    def clear_raw_capture(self):
        self._raw_capture = None

    def load_custom_profile(self, profile_data: dict):
        """Charge un profil custom après enregistrement depuis le wizard."""
        self._load_custom_profile_data(profile_data)
        self.controller_type = 'custom'
        self.controller_name = profile_data.get('name', 'Custom')

    def _load_custom_profile_data(self, profile_data: dict):
        self._custom_profile = profile_data
        maps = build_reverse_maps(profile_data)
        self._rev_pad          = maps["rev_pad"]
        self._rev_mute         = maps["rev_mute"]
        self._rev_effect       = maps["rev_effect"]
        self._rev_fader        = maps["rev_fader"]
        self._rev_led          = maps["rev_led"]
        self._custom_vel_remap = maps.get("vel_remap", {})

    def _custom_vel(self, akai_vel: int) -> int:
        """Remap une velocité AKAI standard vers la velocité du contrôleur custom."""
        if akai_vel == 0:
            return 0
        return self._custom_vel_remap.get(akai_vel, akai_vel)

    def poll_midi(self):
        """Vide la queue MIDI (thread Qt, 10 ms) avec coalescing des faders."""
        if not self.midi_in:
            return
        try:
            with self._midi_lock:
                messages = list(self._midi_queue)
                self._midi_queue.clear()

            # Mode capture brute (wizard de mapping)
            if self._raw_capture:
                for msg in messages:
                    try:
                        self._raw_capture(msg)
                    except Exception:
                        pass
                return

            fader_latest  = {}
            other_messages = []

            for msg in messages:
                fi = self._fader_index(msg)
                if fi is not None:
                    fader_latest[fi] = msg[2] if len(msg) > 2 else 0
                else:
                    other_messages.append(msg)

            for fi, val in fader_latest.items():
                self.fader_changed.emit(fi, val)

            for msg in other_messages:
                self.handle_midi_message(msg)

        except Exception as e:
            print(f"❌ Erreur lecture MIDI: {e}")

    def _fader_index(self, msg):
        """Retourne l'index fader (0-8) si le message est un fader, sinon None."""
        if len(msg) < 2:
            return None
        status, data1 = msg[0], msg[1]

        if self.controller_type == 'apc_mini':
            if status == 0xB0 and 48 <= data1 <= 56:
                return data1 - 48

        elif self.controller_type in ('apc40', 'apc40_mk2', 'apc20'):
            # CC messages encodés sur canal 0-7 (0xB0-0xB7)
            if (status & 0xF0) == 0xB0:
                channel = status & 0x0F
                if data1 == _APC40_TRACK_VOL_CC and 0 <= channel <= 7:
                    return channel  # fader piste 0-7
                if channel == 0 and data1 == _APC40_MASTER_VOL_CC:
                    return 8        # fader master

        elif self.controller_type == 'midimix':
            if status == 0xB0 and data1 in _MIDIMIX_FADER_CC:
                return _MIDIMIX_FADER_CC[data1]

        elif self.controller_type == 'custom':
            if (status & 0xF0) == 0xB0:
                channel = status & 0x0F
                k = (channel, data1)
                if k in self._rev_fader:
                    return self._rev_fader[k]

        return None

    def handle_midi_message(self, message):
        try:
            if len(message) < 2:
                return
            ct = self.controller_type
            if ct == 'apc_mini':
                self._handle_apc_mini(message)
            elif ct in ('apc40', 'apc40_mk2'):
                self._handle_apc40(message)
            elif ct == 'apc20':
                self._handle_apc20(message)
            elif ct == 'launchpad_mini_mk3':
                self._handle_launchpad_mini_mk3(message)
            elif ct == 'launchpad_mk2':
                self._handle_launchpad_mk2(message)
            elif ct in ('launchpad_mini_mk1', 'launchpad_mini_mk2'):
                self._handle_launchpad_mini(message)
            elif ct == 'midimix':
                self._handle_midimix(message)
            elif ct == 'custom':
                self._handle_custom(message)
        except Exception as e:
            print(f"❌ Erreur traitement MIDI: {e}")

    # ─── Handlers par contrôleur ─────────────────────────────────────────────

    def _handle_apc_mini(self, message):
        """Messages AKAI APC Mini — comportement original inchangé."""
        status = message[0]
        data1  = message[1]
        data2  = message[2] if len(message) > 2 else 0

        if self.debug_mode:
            print(f"🔍 APC: status={hex(status)} d1={data1} d2={data2}")

        # Faders déjà traités dans _fader_index
        if status == 0xB0:
            return

        # Note Off — boutons EFFETS uniquement (colonne 8, notes 112-119)
        if status == 0x80 or (status == 0x90 and data2 == 0):
            if 112 <= data1 <= 119:
                self.pad_released.emit(data1 - 112, 8)
            return

        if status != 0x90 or data2 == 0:
            return

        note = data1

        if 112 <= note <= 119:
            # Carrés rouges droite (EFFETS)
            self.pad_pressed.emit(note - 112, 8)

        elif 100 <= note <= 107:
            # Carrés MUTE au-dessus des faders
            if self.owner_window:
                self.owner_window.toggle_fader_mute_from_midi(note - 100)

        elif note == 122:
            # TAP TEMPO
            if self.owner_window:
                self.owner_window._tap_tempo()
            if self.midi_out:
                try:
                    self.midi_out.send_message([0x90, 122, 3])
                    QTimer.singleShot(150, lambda: self.midi_out.send_message([0x90, 122, 0])
                                      if self.midi_out else None)
                except Exception:
                    pass

        elif 0 <= note <= 63:
            # Grille 8×8
            row = 7 - (note // 8)
            col = note % 8
            self.pad_pressed.emit(row, col)

        elif self.debug_mode:
            print(f"   ⚠️  Note {note} non mappée (APC)")

    def _handle_apc40(self, message):
        """Messages AKAI APC40.

        L'APC40 utilise canal MIDI = piste (0-7).
        Clip slots  : Note On/Off ch=track, note=53+row (rows 0-4) → pad(row, col=track)
        Scene launch: Note On/Off ch=0, note=82+row              → pad(row, col=8)
        Activator   : Note 50 ch=track                            → toggle mute
        Tap Tempo   : Note 99 ch=0
        Faders déjà traités dans _fader_index (CC 7 / CC 14).
        """
        status = message[0]
        data1  = message[1]
        data2  = message[2] if len(message) > 2 else 0

        status_type = status & 0xF0
        channel     = status & 0x0F

        if self.debug_mode:
            print(f"🔍 APC40: type={hex(status_type)} ch={channel} note={data1} vel={data2}")

        # CC déjà filtré dans _fader_index
        if status_type == 0xB0:
            return

        # Note Off → relâcher scène (colonne 8)
        if status_type == 0x80 or (status_type == 0x90 and data2 == 0):
            if channel == 0 and _APC40_SCENE_BASE_NOTE <= data1 <= _APC40_SCENE_BASE_NOTE + 4:
                self.pad_released.emit(data1 - _APC40_SCENE_BASE_NOTE, 8)
            return

        if status_type != 0x90 or data2 == 0:
            return

        note = data1

        # Clip slots (grille 5×8)
        if _APC40_CLIP_BASE_NOTE <= note <= _APC40_CLIP_BASE_NOTE + 4 and 0 <= channel <= 7:
            row = note - _APC40_CLIP_BASE_NOTE
            self.pad_pressed.emit(row, channel)

        # Scene Launch → colonne 8
        elif channel == 0 and _APC40_SCENE_BASE_NOTE <= note <= _APC40_SCENE_BASE_NOTE + 4:
            row = note - _APC40_SCENE_BASE_NOTE
            self.pad_pressed.emit(row, 8)

        # Activator (Mute piste)
        elif note == _APC40_ACTIVATOR_NOTE and 0 <= channel <= 7:
            if self.owner_window:
                self.owner_window.toggle_fader_mute_from_midi(channel)

        # Tap Tempo
        elif channel == 0 and note == _APC40_TAP_TEMPO_NOTE:
            if self.owner_window:
                self.owner_window._tap_tempo()
            if self.midi_out:
                try:
                    self.midi_out.send_message([0x90, _APC40_TAP_TEMPO_NOTE, 2])
                    QTimer.singleShot(150, lambda: self.midi_out.send_message(
                        [0x90, _APC40_TAP_TEMPO_NOTE, 0]) if self.midi_out else None)
                except Exception:
                    pass

        elif self.debug_mode:
            print(f"   ⚠️  ch={channel} note={note} non mappé (APC40)")

    def _handle_apc20(self, message):
        """Messages AKAI APC20.

        Même layout que l'APC40 MK1 : clips ch=track note=53+row, scenes ch=0 note=82+row,
        faders CC7/CC14 (déjà traités dans _fader_index).
        Tap Tempo : note 98 (bouton Shift), ch=0.
        """
        status = message[0]
        data1  = message[1]
        data2  = message[2] if len(message) > 2 else 0

        status_type = status & 0xF0
        channel     = status & 0x0F

        if self.debug_mode:
            print(f"🔍 APC20: type={hex(status_type)} ch={channel} note={data1} vel={data2}")

        if status_type == 0xB0:
            return

        if status_type == 0x80 or (status_type == 0x90 and data2 == 0):
            if channel == 0 and _APC40_SCENE_BASE_NOTE <= data1 <= _APC40_SCENE_BASE_NOTE + 4:
                self.pad_released.emit(data1 - _APC40_SCENE_BASE_NOTE, 8)
            return

        if status_type != 0x90 or data2 == 0:
            return

        note = data1

        if _APC40_CLIP_BASE_NOTE <= note <= _APC40_CLIP_BASE_NOTE + 4 and 0 <= channel <= 7:
            self.pad_pressed.emit(note - _APC40_CLIP_BASE_NOTE, channel)

        elif channel == 0 and _APC40_SCENE_BASE_NOTE <= note <= _APC40_SCENE_BASE_NOTE + 4:
            self.pad_pressed.emit(note - _APC40_SCENE_BASE_NOTE, 8)

        elif note == _APC40_ACTIVATOR_NOTE and 0 <= channel <= 7:
            if self.owner_window:
                self.owner_window.toggle_fader_mute_from_midi(channel)

        elif channel == 0 and note == _APC20_TAP_TEMPO_NOTE:
            if self.owner_window:
                self.owner_window._tap_tempo()
            if self.midi_out:
                try:
                    self.midi_out.send_message([0x90, _APC20_TAP_TEMPO_NOTE, 2])
                    QTimer.singleShot(150, lambda: self.midi_out.send_message(
                        [0x90, _APC20_TAP_TEMPO_NOTE, 0]) if self.midi_out else None)
                except Exception:
                    pass

        elif self.debug_mode:
            print(f"   ⚠️  ch={channel} note={note} non mappé (APC20)")

    def _handle_launchpad_mini(self, message):
        """Messages Novation Launchpad Mini MK1/MK2.

        Layout: note = 16 * lp_row + lp_col
          lp_row ∈ 0-7  (0 = bottom, 7 = top)
          lp_col ∈ 0-7  (grille), 8 = boutons scene (droite)
        Top row automap: CC 104-111 → mute faders 0-7
        """
        status = message[0]
        data1  = message[1]
        data2  = message[2] if len(message) > 2 else 0

        if self.debug_mode:
            print(f"🔍 LP Mini: status={hex(status)} d1={data1} d2={data2}")

        # Top row (boutons Automap/Live) : CC 104-111 → mute
        if status == 0xB0 and 104 <= data1 <= 111:
            if data2 > 0 and self.owner_window:
                self.owner_window.toggle_fader_mute_from_midi(data1 - 104)
            return

        if status not in (0x90, 0x80):
            return

        note    = data1
        lp_row  = note // 16   # 0 = bottom, 7 = top
        lp_col  = note % 16    # 0-7 grille, 8 = scene

        if lp_row > 7 or lp_col > 8:
            return

        # Conversion vers coordonnées internes MyStrow (ms_row 0 = haut)
        ms_row = 7 - lp_row
        ms_col = lp_col

        if status == 0x90 and data2 > 0:
            self.pad_pressed.emit(ms_row, ms_col)
        elif (status == 0x80 or (status == 0x90 and data2 == 0)) and ms_col == 8:
            self.pad_released.emit(ms_row, ms_col)

    def _handle_launchpad_mini_mk3(self, message):
        """Messages Novation Launchpad Mini MK3 (Programmer mode).

        En Programmer mode, layout note = lp_row1 * 10 + lp_col1 :
          lp_row1 ∈ 1-8  (1 = bas, 8 = haut)
          lp_col1 ∈ 1-8  (grille), 9 = boutons scène (colonne droite)
        Top row (boutons ronds) : CC 91-98 → mute faders 0-7
        Logo : CC 99 (ignoré)
        """
        status = message[0]
        data1  = message[1]
        data2  = message[2] if len(message) > 2 else 0

        if self.debug_mode:
            print(f"🔍 LP Mini MK3: status={hex(status)} d1={data1} d2={data2}")

        # Top row CC 91-98 → monte le fader de la colonne (25/50/75/100/0)
        # data1 91 = colonne 0 (gauche) … 98 = colonne 7 (droite)
        if status == 0xB0 and 91 <= data1 <= 98:
            if data2 > 0 and self.owner_window:
                self.owner_window.cycle_fader_level_from_midi(data1 - 91)
            return

        # Colonne de droite (scène) → EFFETS (colonne 8).
        # Le MK3 envoie ces boutons en CC 19,29,…,89 (et NON en Note On).
        # CC 89 = haut → effet 0 ; CC 19 = bas → effet 7.
        if status == 0xB0 and data1 % 10 == 9 and 1 <= data1 // 10 <= 8:
            ms_row = 8 - (data1 // 10)
            if data2 > 0:
                self.pad_pressed.emit(ms_row, 8)
            else:
                self.pad_released.emit(ms_row, 8)
            return

        if status not in (0x90, 0x80):
            return

        note    = data1
        lp_row1 = note // 10   # 1=bas, 8=haut
        lp_col1 = note % 10    # 1-8 grille, 9=side

        if lp_row1 < 1 or lp_row1 > 8 or lp_col1 < 1 or lp_col1 > 9:
            return

        ms_row = 8 - lp_row1       # 0=haut, 7=bas
        ms_col = lp_col1 - 1       # 0-7 grille, 8=side

        if status == 0x90 and data2 > 0:
            self.pad_pressed.emit(ms_row, ms_col)
        elif (status == 0x80 or (status == 0x90 and data2 == 0)) and ms_col == 8:
            self.pad_released.emit(ms_row, ms_col)

    def _handle_launchpad_mk2(self, message):
        """Messages Novation Launchpad MK2 (non-mini).

        Layout note : note = lp_row1 * 10 + lp_col1
          lp_row1 ∈ 1-8  (1=bas, 8=haut)
          lp_col1 ∈ 1-8  (grille), 9=boutons droite
        Top row automap: CC 104-111 → mute faders 0-7
        """
        status = message[0]
        data1  = message[1]
        data2  = message[2] if len(message) > 2 else 0

        if self.debug_mode:
            print(f"🔍 LP MK2: status={hex(status)} d1={data1} d2={data2}")

        # Top row CC 104-111 → mute
        if status == 0xB0 and 104 <= data1 <= 111:
            if data2 > 0 and self.owner_window:
                self.owner_window.toggle_fader_mute_from_midi(data1 - 104)
            return

        if status not in (0x90, 0x80):
            return

        note        = data1
        lp_row1     = note // 10   # 1=bas, 8=haut
        lp_col1     = note % 10    # 1-8 grille, 9=side

        if lp_row1 < 1 or lp_row1 > 8 or lp_col1 < 1 or lp_col1 > 9:
            return

        ms_row = 8 - lp_row1       # 0=haut, 7=bas
        ms_col = lp_col1 - 1       # 0-7 grille, 8=side

        if status == 0x90 and data2 > 0:
            self.pad_pressed.emit(ms_row, ms_col)
        elif (status == 0x80 or (status == 0x90 and data2 == 0)) and ms_col == 8:
            self.pad_released.emit(ms_row, ms_col)

    def _handle_midimix(self, message):
        """Messages AKAI MIDImix.

        Faders: CC 19/23/27/31/49/53/57/61 (ch1-8), CC 62 (master)
        Mute:   Note On 1/4/7/10/13/16/19/22 → toggle_fader_mute
        Bank L: Note 25 → tap tempo
        """
        status = message[0]
        data1  = message[1]
        data2  = message[2] if len(message) > 2 else 0

        if self.debug_mode:
            print(f"🔍 MIDImix: status={hex(status)} d1={data1} d2={data2}")

        # Faders déjà traités dans _fader_index
        if status == 0xB0:
            return

        if status == 0x90 and data2 > 0:
            if data1 in _MIDIMIX_MUTE_NOTE:
                ch_idx = _MIDIMIX_MUTE_NOTE[data1]
                if self.owner_window:
                    self.owner_window.toggle_fader_mute_from_midi(ch_idx)
                # Feedback LED via bouton REC ARM correspondant
                rec_note = ch_idx * 3  # notes 0, 3, 6, 9...
                if self.midi_out:
                    try:
                        self.midi_out.send_message([0x90, rec_note, 127])
                        QTimer.singleShot(120, lambda n=rec_note:
                            self.midi_out.send_message([0x90, n, 0]) if self.midi_out else None)
                    except Exception:
                        pass

            elif data1 == _MIDIMIX_BANK_LEFT:
                if self.owner_window:
                    self.owner_window._tap_tempo()

    def _handle_custom(self, message):
        """Dispatch pour contrôleurs chargés depuis un profil JSON custom."""
        if len(message) < 2:
            return
        status = message[0]
        data1  = message[1]
        data2  = message[2] if len(message) > 2 else 0
        channel     = status & 0x0F
        status_type = status & 0xF0

        if status_type == 0x90 and data2 > 0:
            k = (channel, data1)
            if k in self._rev_pad:
                row, col = self._rev_pad[k]
                self.pad_pressed.emit(row, col)
            elif k in self._rev_mute:
                if self.owner_window:
                    self.owner_window.toggle_fader_mute_from_midi(self._rev_mute[k])
            elif k in self._rev_effect:
                self.pad_pressed.emit(self._rev_effect[k], 8)

        elif status_type == 0x80 or (status_type == 0x90 and data2 == 0):
            k = (channel, data1)
            if k in self._rev_effect:
                self.pad_released.emit(self._rev_effect[k], 8)

    # ─── LEDs ────────────────────────────────────────────────────────────────

    def initialize_leds(self):
        """Éteint toutes les LEDs selon le contrôleur actif."""
        if not self.midi_out:
            return
        try:
            ct = self.controller_type

            if ct == 'apc_mini':
                for note in range(64):
                    self.midi_out.send_message([0x90, note, 0])

            elif ct in ('apc40', 'apc40_mk2'):
                # SysEx d'init obligatoire pour activer le mode LED Ableton
                # MK1 : product ID 0x27 — MkII : product ID 0x29
                product_id = 0x29 if ct == 'apc40_mk2' else 0x27
                self.midi_out.send_message([
                    0xF0, 0x47, 0x7F, product_id,
                    0x60, 0x00, 0x04,
                    0x41, 0x00, 0x00, 0x00,
                    0xF7
                ])
                import time as _t; _t.sleep(0.05)

                # Éteindre les 5 lignes × 8 pistes de clips + 5 scènes
                for track in range(8):
                    for row in range(5):
                        self.midi_out.send_message([0x90 | track, _APC40_CLIP_BASE_NOTE + row, 0])
                for row in range(5):
                    self.midi_out.send_message([0x90, _APC40_SCENE_BASE_NOTE + row, 0])

            elif ct == 'apc20':
                # L'APC20 répond directement aux Note On sans SysEx
                for track in range(8):
                    for row in range(5):
                        self.midi_out.send_message([0x90 | track, _APC40_CLIP_BASE_NOTE + row, 0])
                for row in range(5):
                    self.midi_out.send_message([0x90, _APC40_SCENE_BASE_NOTE + row, 0])

            elif ct == 'launchpad_mini_mk3':
                # Passage en Programmer mode (sinon le MK3 ignore les LED note 11-88)
                # SysEx Novation : 00 20 29 02 0D (header) 0E 01 = Programmer mode ON
                self.midi_out.send_message(
                    [0xF0, 0x00, 0x20, 0x29, 0x02, 0x0D, 0x0E, 0x01, 0xF7])
                import time as _t; _t.sleep(0.05)
                # Éteindre la grille 11-88 + colonne scène (col 9) + top row CC 91-98
                for row1 in range(1, 9):
                    for col1 in range(1, 10):
                        self.midi_out.send_message([0x90, row1 * 10 + col1, 0])
                for cc in range(91, 99):
                    self.midi_out.send_message([0xB0, cc, 0])

            elif ct == 'launchpad_mk2':
                # Reset — éteint toutes les LEDs
                self.midi_out.send_message([0xB0, 0x00, 0x00])

            elif ct in ('launchpad_mini_mk1', 'launchpad_mini_mk2'):
                # Reset via CC 0 value 0 (mode normal, all LEDs off)
                self.midi_out.send_message([0xB0, 0x00, 0x00])

            elif ct == 'midimix':
                # Éteindre les LEDs REC ARM
                for note in _MIDIMIX_REC_NOTE:
                    self.midi_out.send_message([0x90, note, 0])

            elif ct == 'custom':
                for (row, col), entry in self._rev_led.items():
                    self.midi_out.send_message([0x90 | entry['channel'], entry['note'], 0])

        except Exception as e:
            print(f"❌ Erreur init LEDs: {e}")

    def set_pad_led(self, row, col, color_velocity, brightness_percent=100):
        """Allume un pad sur le contrôleur actif.

        color_velocity : velocity AKAI (couleur/intensité)
        brightness_percent : 20 (dim) ou 100 (full) — utilisé par APC Mini seulement
        """
        try:
            ct = self.controller_type
            if ct == 'apc_mini':
                self._set_led_apc(row, col, color_velocity, brightness_percent)
            elif ct in ('apc40', 'apc40_mk2'):
                self._set_led_apc40(row, col, color_velocity)
            elif ct == 'apc20':
                self._set_led_apc20(row, col, color_velocity)
            elif ct == 'launchpad_mini_mk3':
                self._set_led_lp_mk3(row, col, color_velocity, brightness_percent)
            elif ct == 'launchpad_mk2':
                self._set_led_lp_mk2(row, col, color_velocity)
            elif ct in ('launchpad_mini_mk1', 'launchpad_mini_mk2'):
                self._set_led_lp_mini(row, col, color_velocity)
            elif ct == 'custom':
                self._set_led_custom(row, col, color_velocity)
            # MIDImix : pas de matrice de pads LEDs
        except Exception as e:
            print(f"❌ Erreur set LED: {e}")

        if self.led_observer:
            try:
                self.led_observer(row, col, color_velocity, brightness_percent)
            except Exception:
                pass

    def set_apc_bright_mode(self, enabled: bool):
        """Active/désactive le mode pleine luminosité (0x96) de l'APC Mini.
        Désactivé par défaut sur Apple Silicon où 0x96 n'est pas transmis correctement.
        """
        self._apc_bright_mode = bool(enabled)

    def _set_led_apc(self, row, col, color_velocity, brightness_percent):
        if not self.midi_out:
            return
        if col == 8:
            note = 112 + row
            vel  = 3 if color_velocity > 0 else 0
            self.midi_out.send_message([0x90, note, vel])
        else:
            # 0x96 = Note On ch7 (bright), 0x90 = Note On ch1 (dim).
            # Sur Apple Silicon, 0x96 n'est pas reçu par l'APC Mini → on utilise 0x90.
            ch   = 0x96 if (brightness_percent >= 80 and self._apc_bright_mode) else 0x90
            note = (7 - row) * 8 + col
            self.midi_out.send_message([ch, note, color_velocity])

    def _set_led_lp_mini(self, row, col, color_velocity):
        """LED Launchpad Mini — bicolor velocity = 16*G + R (G, R ∈ 0-3)."""
        if not self.midi_out:
            return
        lp_vel = _to_lp_mini_vel(color_velocity)
        # Calcul note LP Mini : (7-ms_row)*16 + ms_col
        note = (7 - row) * 16 + col
        self.midi_out.send_message([0x90, note, lp_vel])

    def _set_led_lp_mk3(self, row, col, color_velocity, brightness_percent=100):
        """LED Launchpad Mini MK3 (Programmer mode) — pilotage RGB via SysEx.

        note = lp_row1*10 + lp_col1. On envoie la couleur en RGB exact (0-127/canal)
        modulée par brightness_percent → les pads inactifs (20%) sont atténués.
        SysEx RGB : F0 00 20 29 02 0D 03  03 <note> R G B  F7
        """
        if not self.midi_out:
            return
        lp_row1 = 8 - row           # ms_row 0(haut)→8, ms_row 7(bas)→1
        lp_col1 = (9 if col == 8 else col + 1)
        note = lp_row1 * 10 + lp_col1

        if color_velocity <= 0:
            self.midi_out.send_message([0x90, note, 0])   # éteindre
            return

        r, g, b = _LP_MK3_VEL_TO_RGB.get(color_velocity, (255, 255, 255))
        f = max(0.0, min(1.0, brightness_percent / 100.0))
        r7 = int(r / 255.0 * 127 * f)
        g7 = int(g / 255.0 * 127 * f)
        b7 = int(b / 255.0 * 127 * f)
        self.midi_out.send_message([0xF0, 0x00, 0x20, 0x29, 0x02, 0x0D, 0x03,
                                    0x03, note, r7, g7, b7, 0xF7])

    def _set_led_lp_mk2(self, row, col, color_velocity):
        """LED Launchpad MK2 — note = lp_row1*10 + lp_col1, velocity = index couleur 0-127."""
        if not self.midi_out:
            return
        lp_row1 = 8 - row           # ms_row 0(haut)→8, ms_row 7(bas)→1
        lp_col1 = (9 if col == 8 else col + 1)
        note = lp_row1 * 10 + lp_col1
        self.midi_out.send_message([0x90, note, color_velocity])

    def _set_led_apc40(self, row, col, color_velocity):
        """LED AKAI APC40 / APC40 MkII.

        MK1 : palette 3 couleurs (velocity 0-6 : off/vert/rouge/jaune).
        MK2 : palette 128 couleurs — même indexation que l'APC Mini, velocity passée directement.
        """
        if not self.midi_out:
            return
        if self.controller_type == 'apc40_mk2':
            vel = color_velocity  # palette 128 couleurs compatible APC Mini
        else:
            vel = _to_apc40_vel(color_velocity)
        if col < 8:
            # Clip slot : channel = track, note = base + row
            if row > 4:
                return  # APC40 n'a que 5 lignes de clips
            self.midi_out.send_message([0x90 | col, _APC40_CLIP_BASE_NOTE + row, vel])
        elif col == 8:
            # Scene launch (colonne droite)
            if row > 4:
                return
            self.midi_out.send_message([0x90, _APC40_SCENE_BASE_NOTE + row, vel])

    def _set_led_apc20(self, row, col, color_velocity):
        """LED AKAI APC20 — palette 3 couleurs identique à l'APC40 MK1."""
        if not self.midi_out:
            return
        if row > 4:
            return  # APC20 : 5 lignes max (rows 0-4)
        vel = _to_apc40_vel(color_velocity)
        if col < 8:
            self.midi_out.send_message([0x90 | col, _APC40_CLIP_BASE_NOTE + row, vel])
        elif col == 8:
            self.midi_out.send_message([0x90, _APC40_SCENE_BASE_NOTE + row, vel])

    # ─── Divers ──────────────────────────────────────────────────────────────

    def _set_led_custom(self, row, col, color_velocity):
        """LED pour contrôleur custom — Note On sur le note mappé."""
        if not self.midi_out:
            return
        entry = self._rev_led.get((row, col))
        if not entry:
            return
        vel = self._custom_vel(color_velocity)
        self.midi_out.send_message([0x90 | entry['channel'], entry['note'], vel])

    def set_fader(self, fader_idx, value):
        """Placeholder — faders physiques non motorisés."""
        pass

    def close(self):
        if hasattr(self, 'midi_timer'):
            self.midi_timer.stop()
        if hasattr(self, 'connection_check_timer') and self.connection_check_timer:
            self.connection_check_timer.stop()
        if self.midi_in:
            try: self.midi_in.close_port()
            except Exception: pass
        if self.midi_out:
            try: self.midi_out.close_port()
            except Exception: pass
