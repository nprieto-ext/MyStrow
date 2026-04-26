"""
Gestionnaire MIDI multi-contrôleur
Supporte: AKAI APC Mini, Novation Launchpad Mini MK1/MK2, AKAI MIDImix
"""
import threading
from PySide6.QtCore import QObject, Signal, QTimer

from core import MIDI_AVAILABLE

rtmidi = None
if MIDI_AVAILABLE:
    try:
        import rtmidi
    except ImportError:
        try:
            import rtmidi2 as rtmidi
        except ImportError:
            pass

# ─── Contrôleurs supportés (ordre de priorité) ───────────────────────────────
SUPPORTED_CONTROLLERS = [
    {
        'id': 'apc_mini',
        'name': 'AKAI APC Mini',
        'keywords': ['APC MINI', 'APC'],
        'has_faders': True,
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


def _detect_controller(ports: list):
    """Retourne (ctrl_dict, port_name) pour le premier contrôleur trouvé, selon priorité."""
    for ctrl in SUPPORTED_CONTROLLERS:
        for port_name in ports:
            up = port_name.upper()
            for kw in ctrl['keywords']:
                if kw in up:
                    return ctrl, port_name
    return None, None


def _find_out_port(ctrl: dict, out_ports: list):
    """Trouve le port de sortie correspondant au contrôleur donné."""
    for port_name in out_ports:
        up = port_name.upper()
        for kw in ctrl['keywords']:
            if kw in up:
                return port_name
    return None


class MIDIHandler(QObject):
    """Gestionnaire MIDI multi-contrôleur (APC Mini, Launchpad Mini, MIDImix)."""

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

        self.controller_type = None   # 'apc_mini' | 'launchpad_mini_mk1/mk2' | 'midimix'
        self.controller_name = ""

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

    def connect_controller(self):
        """Détecte et connecte le premier contrôleur supporté disponible."""
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

            ctrl, in_name = _detect_controller(in_ports)
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
            ctrl, _ = _detect_controller(ports)
            device_present = (ctrl is not None)
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
        if self.midi_in and self.midi_out:
            try:
                if self.midi_in.is_port_open() and self.midi_out.is_port_open():
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

    def poll_midi(self):
        """Vide la queue MIDI (thread Qt, 10 ms) avec coalescing des faders."""
        if not self.midi_in:
            return
        try:
            with self._midi_lock:
                messages = list(self._midi_queue)
                self._midi_queue.clear()

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

        elif self.controller_type == 'midimix':
            if status == 0xB0 and data1 in _MIDIMIX_FADER_CC:
                return _MIDIMIX_FADER_CC[data1]

        return None

    def handle_midi_message(self, message):
        try:
            if len(message) < 2:
                return
            ct = self.controller_type
            if ct == 'apc_mini':
                self._handle_apc_mini(message)
            elif ct in ('launchpad_mini_mk1', 'launchpad_mini_mk2'):
                self._handle_launchpad_mini(message)
            elif ct == 'midimix':
                self._handle_midimix(message)
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

            elif ct in ('launchpad_mini_mk1', 'launchpad_mini_mk2'):
                # Reset via CC 0 value 0 (mode normal, all LEDs off)
                self.midi_out.send_message([0xB0, 0x00, 0x00])

            elif ct == 'midimix':
                # Éteindre les LEDs REC ARM
                for note in _MIDIMIX_REC_NOTE:
                    self.midi_out.send_message([0x90, note, 0])

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
            elif ct in ('launchpad_mini_mk1', 'launchpad_mini_mk2'):
                self._set_led_lp_mini(row, col, color_velocity)
            # MIDImix : pas de matrice de pads LEDs
        except Exception as e:
            print(f"❌ Erreur set LED: {e}")

        if self.led_observer:
            try:
                self.led_observer(row, col, color_velocity, brightness_percent)
            except Exception:
                pass

    def _set_led_apc(self, row, col, color_velocity, brightness_percent):
        if not self.midi_out:
            return
        if col == 8:
            note = 112 + row
            vel  = 3 if color_velocity > 0 else 0
            self.midi_out.send_message([0x90, note, vel])
        else:
            ch   = 0x96 if brightness_percent >= 80 else 0x90
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

    # ─── Divers ──────────────────────────────────────────────────────────────

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
