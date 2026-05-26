"""
LiveAudioEngine — Capture audio temps réel + beat detection + détection de section
Sources supportées : Loopback système, Micro/Line In, MIDI Clock, Virtual DJ HTTP
"""
import math
import subprocess
import sys
import time
import urllib.request
from collections import deque

try:
    import numpy as _np
    HAS_NP = True
except ImportError:
    HAS_NP = False

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor

from audio_ai import AudioColorAI

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False

# Import rtmidi (même pattern que midi_handler.py)
_rtmidi = None
try:
    import rtmidi as _rtmidi
except ImportError:
    try:
        import rtmidi2 as _rtmidi
    except ImportError:
        pass

_LOOPBACK_KEYWORDS = (
    'loopback', 'stereo mix', 'mixage st', 'what u hear', 'wave out',
    'mix output', 'sum',
)

# Ports MIDI à exclure (contrôleurs scène déjà pris par MIDIHandler)
_MIDI_EXCLUDE = ('APC', 'LAUNCHPAD', 'MIDIMIX', 'GS WAVETABLE', 'MICROSOFT')


class LiveAudioEngine(QObject):
    """
    Moteur audio/MIDI temps réel pour le mode LIVE.

    Flux de données (audio) :
      sounddevice callback (thread audio)  → _process_chunk()
      QTimer 40 ms (thread Qt)             → _emit_state()

    Flux de données (MIDI Clock) :
      rtmidi callback (thread C++)          → _pending_beat_energy = 1.0
      QTimer 50 ms (thread Qt)              → _midi_beat_tick() → _process_chunk()

    Flux de données (Virtual DJ HTTP) :
      QTimer 200 ms  → _vdj_poll() : lecture BPM
      QTimer 50 ms   → _vdj_tick() → _process_chunk()
    """

    device_info       = Signal(str)         # nom du device/port actif
    connection_status = Signal(str)         # 'off' | 'waiting' | 'connected'
    energy_updated    = Signal(float)       # niveau 0–100 pour le VU mètre
    status_updated    = Signal(float, str)  # (bpm, section)
    state_ready       = Signal(object)      # dict état lumière → projecteurs
    transient_hit     = Signal(str)         # 'kick' | 'snare' | 'hihat'
    beat_detected     = Signal()            # flash indicateur beat

    def __init__(self, parent=None):
        super().__init__(parent)

        self.audio_ai = AudioColorAI()
        self.audio_ai.analyzed = True

        self._running        = False
        self._stream         = None
        self._fallback_tmr   = None
        self._vdj_poll_tmr   = None
        self._midi_clock_in  = None
        self._source_key     = "loopback"
        self._nervosity      = 0.5
        self._sensitivity    = 0.7

        # Historiques (~4 s = 80 chunks × 50 ms)
        self._rms_history    = deque(maxlen=80)
        self._norm_history   = deque(maxlen=80)  # valeurs normalisées

        # Beat tracking
        self._beat_times     = deque(maxlen=16)
        self._last_beat_ts   = 0.0
        self._bpm            = 0.0
        self._elapsed_ms     = 0

        # Section (détection temps réel)
        self._section_state  = 'verse'
        self._section_votes  = deque(maxlen=6)   # 6 × 50 ms = 300 ms

        # MIDI Clock
        self._clock_ticks    = 0
        self._last_clock_ts  = 0.0
        self._clock_intervals = deque(maxlen=48)  # 2 beats de marge
        self._pending_beat_energy = 0.2

        # Virtual DJ HTTP
        self._vdj_beat_phase = 0.0
        self._vdj_last_bpm   = 0.0

        # FFT frequency bands (numpy)
        self._band_sr        = 44100
        self._band_short     = {k: deque(maxlen=6)  for k in ('sub', 'bass', 'mids', 'highs')}
        self._band_long      = {k: deque(maxlen=80) for k in ('sub', 'bass', 'mids', 'highs')}
        self._band_norm      = {'sub': 0.0, 'bass': 0.0, 'mids': 0.0, 'highs': 0.0}

        # Transient detection
        self._last_transient     = {'kick': 0.0, 'snare': 0.0, 'hihat': 0.0}
        self._pending_transients: list = []

        # Beat pending flag (thread-safe via Qt timer)
        self._beat_pending = False
        self._manual_bpm   = False

        # Timer Qt émetteur d'état lumière (40 ms)
        self._state_timer = QTimer(self)
        self._state_timer.timeout.connect(self._emit_state)

    # ── Contrôle public ────────────────────────────────────────────────────

    def start(self, source_key: str, dominant_color: QColor,
              nervosity: int, sensitivity: int):
        self._source_key  = source_key
        self._nervosity   = nervosity  / 100.0
        self._sensitivity = sensitivity / 100.0

        self.audio_ai.reset()
        self.audio_ai.analyzed   = True
        self.audio_ai.energy_map = []
        self.audio_ai.beats      = []
        self.audio_ai.sections   = []
        self.audio_ai.drops      = []
        self.audio_ai.set_dominant_color(dominant_color)

        self._elapsed_ms          = 0
        self._manual_bpm          = False
        self._last_beat_ts        = time.monotonic()
        self._last_clock_ts       = 0.0
        self._clock_ticks         = 0
        self._pending_beat_energy = 0.2
        self._vdj_beat_phase      = 0.0
        self._vdj_last_bpm        = 0.0
        self._bpm                 = 0.0
        self._section_state       = 'verse'
        self._beat_times.clear()
        self._rms_history.clear()
        self._norm_history.clear()
        self._clock_intervals.clear()
        self._section_votes.clear()
        for dq in self._band_short.values():
            dq.clear()
        for dq in self._band_long.values():
            dq.clear()
        self._band_norm        = {'sub': 0.0, 'bass': 0.0, 'mids': 0.0, 'highs': 0.0}
        self._last_transient   = {'kick': 0.0, 'snare': 0.0, 'hihat': 0.0}
        self._pending_transients = []
        self._running = True

        self._open_stream()
        self._state_timer.start(40)

    def stop(self):
        self._running = False
        self._state_timer.stop()

        if self._fallback_tmr:
            self._fallback_tmr.stop()
            self._fallback_tmr = None
        if self._vdj_poll_tmr:
            self._vdj_poll_tmr.stop()
            self._vdj_poll_tmr = None
        if self._midi_clock_in:
            try:
                self._midi_clock_in.close_port()
                del self._midi_clock_in
            except Exception:
                pass
            self._midi_clock_in = None
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def update_color(self, color: QColor):
        self.audio_ai.set_dominant_color(color)

    def update_nervosity(self, value_0_100: int):
        self._nervosity = value_0_100 / 100.0

    def update_sensitivity(self, value_0_100: int):
        self._sensitivity = value_0_100 / 100.0

    def set_manual_bpm(self, bpm: float):
        """Active le BPM manuel et remplace la détection automatique."""
        self._manual_bpm = True
        self._bpm = max(40.0, min(220.0, bpm))

    def release_manual_bpm(self):
        """Repasse en mode détection BPM automatique."""
        self._manual_bpm = False

    # ── Routage source ─────────────────────────────────────────────────────

    def _open_stream(self):
        if self._source_key == "midi_clock":
            self._open_midi_clock()
        elif self._source_key == "rekordbox":
            self._open_midi_clock(hint="Rekordbox")
        elif self._source_key == "virtualdj":
            self._open_vdj_http()
        else:
            self._open_audio()

    # ── Sources audio (Loopback / Micro) ───────────────────────────────────

    def _open_audio(self):
        if not HAS_SD:
            self.device_info.emit("Simulateur (sounddevice manquant)")
            self._start_audio_fallback()
            return
        try:
            stream = (self._try_loopback()
                      if self._source_key == "loopback"
                      else self._try_input())
            if stream:
                stream.start()
                self._stream = stream
                return
        except Exception as e:
            print(f"LiveAudio: erreur stream ({e})")
        self.device_info.emit("Simulateur (erreur ouverture audio)")
        self._start_audio_fallback()

    def _try_loopback(self):
        for i, dev in enumerate(sd.query_devices()):
            if dev.get('max_input_channels', 0) < 1:
                continue
            name = dev.get('name', '').lower()
            if any(k in name for k in _LOOPBACK_KEYWORDS):
                sr = int(dev.get('default_samplerate', 44100))
                ch = max(1, min(2, int(dev.get('max_input_channels', 2))))
                self._band_sr = sr
                self.device_info.emit(f"Loopback : {dev['name']}")
                self.connection_status.emit('connected')
                print(f"LiveAudio: loopback → {dev['name']}")
                return sd.InputStream(
                    device=i, channels=ch, samplerate=sr,
                    blocksize=int(sr * 0.05),
                    callback=self._audio_cb,
                )
        try:
            out = sd.query_devices(kind='output')
            sr  = int(out.get('default_samplerate', 44100))
            ch  = max(1, min(2, int(out.get('max_output_channels', 2))))
            idx = out.get('index', sd.default.device[1])
            self._band_sr = sr
            self.device_info.emit(f"Loopback WASAPI : {out['name']}")
            self.connection_status.emit('connected')
            print(f"LiveAudio: WasapiSettings loopback → {out['name']}")
            return sd.InputStream(
                device=idx, channels=ch, samplerate=sr,
                blocksize=int(sr * 0.05),
                extra_settings=sd.WasapiSettings(loopback=True),
                callback=self._audio_cb,
            )
        except Exception as e:
            print(f"LiveAudio: loopback WASAPI échoué ({e})")
        return None

    def _try_input(self):
        try:
            dev = sd.query_devices(kind='input')
            sr  = int(dev.get('default_samplerate', 44100))
            ch  = max(1, min(2, int(dev.get('max_input_channels', 2))))
            self._band_sr = sr
            self.device_info.emit(f"Micro : {dev['name']}")
            self.connection_status.emit('connected')
            print(f"LiveAudio: micro → {dev['name']}")
            return sd.InputStream(
                channels=ch, samplerate=sr,
                blocksize=int(sr * 0.05),
                callback=self._audio_cb,
            )
        except Exception as e:
            print(f"LiveAudio: micro erreur ({e})")
            return None

    def _start_audio_fallback(self):
        self._fallback_tmr = QTimer(self)
        self._fallback_tmr.timeout.connect(self._fallback_tick)
        self._fallback_tmr.start(50)

    def _fallback_tick(self):
        if not self._running:
            return
        self._process_chunk(0.0)  # aucun device = silence, pas de faux signal

    # ── Source MIDI Clock ──────────────────────────────────────────────────

    def _open_midi_clock(self, hint: str = ""):
        if _rtmidi is None:
            self.device_info.emit("MIDI Clock : rtmidi manquant")
            self._start_beat_timer()
            return
        try:
            self._midi_clock_in = _rtmidi.MidiIn()
            ports = self._midi_clock_in.get_ports()

            if not ports:
                self.device_info.emit("MIDI Clock : aucun port MIDI trouvé")
                self._start_beat_timer()
                return

            # Cherche un port correspondant au hint (ex: "Rekordbox")
            target_idx, target_name = None, None
            if hint:
                for i, name in enumerate(ports):
                    if hint.lower() in name.lower():
                        target_idx, target_name = i, name
                        break

            # Sinon premier port non-contrôleur
            if target_idx is None:
                for i, name in enumerate(ports):
                    up = name.upper()
                    if not any(ex in up for ex in _MIDI_EXCLUDE):
                        target_idx, target_name = i, name
                        break

            # Fallback : premier port disponible
            if target_idx is None:
                target_idx, target_name = 0, ports[0]

            self._midi_clock_in.open_port(target_idx)
            # timing=False = recevoir les 0xF8 (MIDI Clock)
            self._midi_clock_in.ignore_types(sysex=True, timing=False, active_sense=True)
            self._midi_clock_in.set_callback(self._midi_clock_cb)

            label = f"{'Rekordbox' if hint else 'MIDI Clock'} : {target_name}"
            self.device_info.emit(label)
            self.connection_status.emit('waiting')
            self._midi_ever_beat = False
            print(f"LiveAudio: {label}")

        except Exception as e:
            self.device_info.emit(f"MIDI Clock : erreur ({e})")
            print(f"LiveAudio: MIDI Clock erreur ({e})")

        # Timer 50ms pour faire avancer le temps entre les beats MIDI
        self._start_beat_timer()

    def _start_beat_timer(self):
        """Timer 50ms pour avancer _elapsed_ms et le VU mètre (MIDI Clock / VDJ)."""
        self._fallback_tmr = QTimer(self)
        self._fallback_tmr.timeout.connect(self._midi_beat_tick)
        self._fallback_tmr.start(50)

    def _midi_clock_cb(self, event, data=None):
        """Callback rtmidi — 0xF8 = timing clock (24 messages par beat)."""
        if not self._running:
            return
        msg, dt = event
        if not msg or msg[0] != 0xF8:
            return

        now = time.monotonic()
        if self._last_clock_ts > 0:
            interval = now - self._last_clock_ts
            if 0.001 < interval < 0.5:
                self._clock_intervals.append(interval)
                if len(self._clock_intervals) >= 6:
                    avg = sum(self._clock_intervals) / len(self._clock_intervals)
                    self._bpm = 60.0 / (24.0 * avg) if avg > 0 else 0.0
        self._last_clock_ts = now

        self._clock_ticks += 1
        if self._clock_ticks >= 24:
            self._clock_ticks = 0
            now2 = time.monotonic()
            self.audio_ai.beats.append(self._elapsed_ms)
            self._beat_times.append(now2)
            self._last_beat_ts = now2
            self._pending_beat_energy = 1.0
            self._beat_pending = True
            if not getattr(self, '_midi_ever_beat', True):
                self._midi_ever_beat = True
                self.connection_status.emit('connected')

    def _midi_beat_tick(self):
        """Tick 50ms pour MIDI Clock et VDJ (avance le temps, décroît l'énergie)."""
        if not self._running:
            return
        rms = self._pending_beat_energy
        self._pending_beat_energy = max(0.12, self._pending_beat_energy * 0.78)

        # Simulateur pur si pas de MIDI connecté (fallback)
        if self._midi_clock_in is None and self._source_key in ('midi_clock', 'rekordbox'):
            t = time.monotonic()
            phase = (t % 0.5) / 0.5
            rms = 0.45 + 0.45 * max(0.0, math.sin(phase * 2 * math.pi))
            if phase < 0.04 and self._bpm == 0.0:
                self._bpm = 120.0

        self._process_chunk(rms)

    # ── Source Virtual DJ HTTP ─────────────────────────────────────────────

    # Port du plugin Network Control de VirtualDJ (Config → Extensions → Network Control)
    VDJ_HTTP_PORT = 80

    def _open_vdj_http(self):
        self._vdj_beat_phase = 0.0
        self._vdj_last_bpm   = 0.0
        self._vdj_ever_connected = False
        self._pending_beat_energy = 0.2
        self.device_info.emit(
            f"Virtual DJ : Network Control port {self.VDJ_HTTP_PORT}…")
        self.connection_status.emit('waiting')

        # Timer 50ms → tick énergie + génération beats depuis BPM connu
        self._fallback_tmr = QTimer(self)
        self._fallback_tmr.timeout.connect(self._vdj_tick)
        self._fallback_tmr.start(50)

        # Timer 200ms → polling HTTP BPM
        self._vdj_poll_tmr = QTimer(self)
        self._vdj_poll_tmr.timeout.connect(self._vdj_poll)
        self._vdj_poll_tmr.start(200)

    def _vdj_poll(self):
        """Lit le BPM depuis le plugin Network Control de VirtualDJ.

        Requiert VDJ 2023+, licence Pro, plugin 'Network Control' installé et actif.
        URL : http://127.0.0.1:<port>/query?script=<vdj_script>
        """
        base = f'http://127.0.0.1:{self.VDJ_HTTP_PORT}/query?script='
        # Essayer deck 1, deck 2, puis master clock
        for script_enc in ('deck%201%20currentBPM', 'deck%202%20currentBPM', 'masterBPM'):
            try:
                with urllib.request.urlopen(base + script_enc, timeout=0.15) as resp:
                    text = resp.read().decode('utf-8').strip()
                    bpm  = float(text)
                    if 40.0 <= bpm <= 220.0:
                        self._bpm          = bpm
                        self._vdj_last_bpm = bpm
                        self.device_info.emit(f"Virtual DJ : {bpm:.1f} BPM")
                        if not self._vdj_ever_connected:
                            self._vdj_ever_connected = True
                            self.connection_status.emit('connected')
                        return
            except Exception:
                pass

        if self._vdj_last_bpm == 0.0:
            self.device_info.emit(
                f"VDJ Network Control : en attente (port {self.VDJ_HTTP_PORT})")
            self.connection_status.emit('waiting')

    def _vdj_tick(self):
        """Tick 50ms pour VDJ : génère les beats depuis le BPM HTTP."""
        if not self._running:
            return
        dt = 0.05
        if self._bpm > 0:
            beat_len = 60.0 / self._bpm
            self._vdj_beat_phase += dt / beat_len
            if self._vdj_beat_phase >= 1.0:
                self._vdj_beat_phase -= 1.0
                now = time.monotonic()
                self.audio_ai.beats.append(self._elapsed_ms)
                self._beat_times.append(now)
                self._last_beat_ts = now
                self._pending_beat_energy = 1.0
                self._beat_pending = True

        rms = self._pending_beat_energy
        self._pending_beat_energy = max(0.12, self._pending_beat_energy * 0.78)
        self._process_chunk(rms)

    # ── Callback audio ─────────────────────────────────────────────────────

    def _audio_cb(self, indata, frames, time_info, status):
        """Callback sounddevice — thread audio (GIL protège les list.append)."""
        if not self._running:
            return
        mono = (indata[:, 0] + indata[:, 1]) * 0.5 if indata.shape[1] >= 2 else indata[:, 0]
        rms  = float(((mono * mono).mean()) ** 0.5)
        if HAS_NP:
            self._update_bands(mono)
        self._process_chunk(rms)

    def _update_bands(self, mono):
        """Analyse FFT des bandes fréquentielles depuis le chunk audio brut."""
        n = len(mono)
        if n < 64:
            return
        window = _np.hanning(n)
        spec   = _np.abs(_np.fft.rfft(mono * window))
        freqs  = _np.fft.rfftfreq(n, d=1.0 / self._band_sr)

        def _band_rms(lo, hi):
            mask = (freqs >= lo) & (freqs < hi)
            if not mask.any():
                return 0.0
            return float(_np.sqrt((spec[mask] ** 2).mean())) / max(n * 0.5, 1.0)

        raws = {
            'sub':   _band_rms(20,    80),
            'bass':  _band_rms(80,   300),
            'mids':  _band_rms(300,  3000),
            'highs': _band_rms(3000, 16000),
        }
        for k, v in raws.items():
            self._band_short[k].append(v)
            self._band_long[k].append(v)

        for k in raws:
            long_max = max(self._band_long[k]) if self._band_long[k] else 0.0
            cur      = self._band_short[k][-1] if self._band_short[k] else 0.0
            self._band_norm[k] = min(1.0, cur / max(long_max, 1e-9))

        self._detect_transients()

    def _detect_transients(self):
        """Détecte kick/snare/hihat depuis les spikes de bandes FFT."""
        now = time.monotonic()

        def _spike(band_key, hit_key, threshold, refract):
            if not self._band_long[band_key] or not self._band_short[band_key]:
                return False
            long_avg = sum(self._band_long[band_key]) / len(self._band_long[band_key])
            cur      = self._band_short[band_key][-1]
            if long_avg < 1e-9:
                return False
            return (cur > long_avg * threshold
                    and now - self._last_transient[hit_key] > refract)

        if _spike('sub',   'kick',  threshold=1.9, refract=0.25):
            self._last_transient['kick'] = now
            self._pending_transients.append('kick')

        if _spike('mids',  'snare', threshold=1.7, refract=0.15):
            self._last_transient['snare'] = now
            self._pending_transients.append('snare')

        if _spike('highs', 'hihat', threshold=1.5, refract=0.08):
            self._last_transient['hihat'] = now
            self._pending_transients.append('hihat')

    # ── Traitement signal (commun à toutes les sources) ────────────────────

    _MAX_ENERGY_FRAMES = 18000   # 15 min à 50 ms/chunk
    _TRIM_TO           = 9000    # garder 7.5 min après trim

    def _trim_if_needed(self):
        """Borne energy_map et beats pour éviter une croissance infinie."""
        em = self.audio_ai.energy_map
        n  = len(em)
        if n <= self._MAX_ENERGY_FRAMES:
            return
        trim_n  = n - self._TRIM_TO
        trim_ms = trim_n * 50
        del em[:trim_n]
        self.audio_ai.beats = [b - trim_ms for b in self.audio_ai.beats if b >= trim_ms]
        self._elapsed_ms   -= trim_ms
        # Soft reset des indices de beat (transition ~1 bar)
        self.audio_ai._last_beat_idx   = len(self.audio_ai.beats) - 1
        self.audio_ai._beat_group_count = max(0, self.audio_ai._beat_group_count - trim_n)
        print(f"LiveAudio: trim {trim_n} frames ({trim_ms//1000}s) — {len(em)} restants")

    def _process_chunk(self, rms: float):
        """Met à jour energy_map, détecte beats, section, avance le temps."""
        self._rms_history.append(rms)

        # Floor à 0.003 (0.3 % du plein signal) — évite d'amplifier le silence
        local_max = max(max(self._rms_history) if self._rms_history else 0.01, 0.003)
        norm      = min(1.0, rms / local_max)

        self._norm_history.append(norm)
        self.audio_ai.energy_map.append(norm)
        self._elapsed_ms += 50

        # Trim tous les 1000 chunks (~50 s)
        if len(self.audio_ai.energy_map) % 1000 == 0:
            self._trim_if_needed()

        self.energy_updated.emit(min(100.0, norm * 100.0))

        # ── Mise à jour section (machine d'états avec vote) ───────────────
        self._section_votes.append(self._detect_section_live())
        if len(self._section_votes) >= 4:
            counts = {}
            for s in self._section_votes:
                counts[s] = counts.get(s, 0) + 1
            dominant = max(counts, key=counts.get)
            if counts[dominant] >= 4:
                self._section_state = dominant

        # ── Détection de beat (audio seulement — MIDI/VDJ ont leur propre) ─
        if self._source_key in ("loopback", "mic") and len(self._rms_history) >= 12:
            avg       = sum(self._rms_history) / len(self._rms_history)
            # Seuil élevé : le chunk doit être nettement au-dessus de la moyenne
            threshold = avg * (1.55 + self._sensitivity * 0.35)
            # gap min 320–450 ms → max ~188 BPM, réduit les faux positifs hautes fréq
            min_gap   = 0.45 - self._nervosity * 0.13

            now = time.monotonic()
            # norm > 0.35 : ignorer les beats fantômes en quasi-silence
            if norm > threshold and norm > 0.35 and (now - self._last_beat_ts) > min_gap:
                self._last_beat_ts = now
                self.audio_ai.beats.append(self._elapsed_ms)
                self._beat_times.append(now)
                self._beat_pending = True
                self._update_bpm()

    def _detect_section_live(self) -> str:
        """Détecte la section musicale depuis l'historique d'énergie normalisée."""
        h = self._norm_history
        n = len(h)
        if n < 10:
            return 'quiet'

        # Gate de silence absolu : si le signal brut moyen est quasi nul → silence
        if self._rms_history:
            recent_raw = list(self._rms_history)[-20:]
            if sum(recent_raw) / len(recent_raw) < 0.01:
                return 'quiet'

        curr = sum(list(h)[-10:]) / 10          # 500 ms courant
        long = sum(h) / n                        # ~4 s moyen
        past = sum(list(h)[-40:-20]) / 20 if n >= 40 else long  # 2 s passés

        jump  = curr - long    # saut d'énergie vs moyenne longue
        trend = curr - past    # tendance récente

        if jump > 0.26 and curr > 0.55:
            return 'drop'
        if curr > 0.55 and long > 0.48:
            return 'high'
        if trend > 0.11 and curr > 0.30:
            return 'build'
        if curr < 0.18:
            return 'quiet'
        return 'verse'

    def _update_bpm(self):
        if self._manual_bpm:
            return
        if len(self._beat_times) < 4:
            return
        intervals = sorted([
            self._beat_times[i + 1] - self._beat_times[i]
            for i in range(len(self._beat_times) - 1)
        ])
        # Filtrer les intervalles hors plage DJ (60–185 BPM = 0.32–1.0 s)
        valid = [iv for iv in intervals if 0.32 < iv < 1.0]
        if len(valid) < 3:
            return
        # Médiane pour ignorer les outliers (false positives, double beats)
        mid = len(valid) // 2
        median_iv = valid[mid]
        new_bpm = 60.0 / median_iv
        # Lissage : évite les sauts brusques
        if self._bpm > 0:
            self._bpm = self._bpm * 0.65 + new_bpm * 0.35
        else:
            self._bpm = new_bpm

    # ── Émission état lumière (thread Qt, 40 ms) ───────────────────────────

    def _emit_state(self):
        if not self._running or self._elapsed_ms == 0:
            return
        state = self.audio_ai.get_state_at(self._elapsed_ms, 0)
        state['section'] = self._section_state
        state['bands']   = dict(self._band_norm)
        self.state_ready.emit(state)
        self.status_updated.emit(self._bpm, self._section_state)
        if self._beat_pending:
            self._beat_pending = False
            self.beat_detected.emit()
        # Émettre et vider les transitoires accumulés (thread Qt → thread-safe)
        for t in self._pending_transients:
            self.transient_hit.emit(t)
        self._pending_transients.clear()


class SoftwareDetector(QObject):
    """Détecte en temps réel les logiciels DJ/audio tournant sur le système.

    Interroge la liste des processus toutes les 2 secondes via tasklist (Windows).
    Émet software_changed(display_name, source_key) quand l'état change.
    display_name/source_key sont vides ("", "") quand aucun logiciel n'est détecté.
    """

    software_changed = Signal(str, str)  # (display_name, source_key)

    # (mot-clé dans le nom de l'exe, nom affiché, clé source LiveModePanel, priorité)
    # Tous mappés sur loopback : capture l'audio en sortie sans config requise.
    # Les sources "Virtual DJ" (HTTP) et "Rekordbox" (MIDI) restent dispo manuellement.
    _KNOWN = [
        ("virtualdj",   "Virtual DJ",    "loopback",    10),
        ("rekordbox",   "Rekordbox",     "loopback",     9),
        ("traktor",     "Traktor",       "loopback",     8),
        ("serato",      "Serato DJ",     "loopback",     7),
        ("ableton",     "Ableton Live",  "loopback",     6),
        ("mixxx",       "Mixxx",         "loopback",     5),
        ("fl64",        "FL Studio",     "loopback",     4),
        ("spotify",     "Spotify",       "loopback",     3),
        ("deezer",      "Deezer",        "loopback",     2),
        ("vlc",         "VLC",           "loopback",     1),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_name   = ""
        self._current_src    = ""
        self._timer          = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(2000)
        self._poll()

    @property
    def detected_name(self) -> str:
        return self._current_name

    @property
    def detected_source(self) -> str:
        return self._current_src

    def _poll(self):
        name, src = self._scan()
        if (name, src) != (self._current_name, self._current_src):
            self._current_name = name
            self._current_src  = src
            self.software_changed.emit(name, src)

    def _scan(self):
        """Retourne (display_name, source_key) du logiciel prioritaire détecté."""
        if sys.platform != "win32":
            return ("", "")
        try:
            result = subprocess.run(
                ["tasklist", "/fo", "CSV", "/nh"],
                capture_output=True, text=True, timeout=2,
                creationflags=0x08000000,   # CREATE_NO_WINDOW
            )
            if result.returncode != 0:
                return ("", "")

            running_exes = set()
            for line in result.stdout.splitlines():
                if line.startswith('"'):
                    parts = line.split('"')
                    if len(parts) > 1:
                        running_exes.add(parts[1].lower())

            best_name, best_src, best_prio = "", "", -1
            for keyword, name, src, prio in self._KNOWN:
                if any(keyword in exe for exe in running_exes) and prio > best_prio:
                    best_name, best_src, best_prio = name, src, prio

            return (best_name, best_src)
        except Exception:
            return ("", "")

    def force_check(self):
        """Forcer un check immédiat (utile au démarrage du mode LIVE)."""
        self._poll()

    def stop(self):
        self._timer.stop()
