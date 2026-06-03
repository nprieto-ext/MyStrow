"""
LiveAudioEngine — Capture audio temps réel + beat detection + détection de section
Sources supportées : Loopback système, Micro/Line In, MIDI Clock, Virtual DJ HTTP
"""
import math
import subprocess
import sys
import threading
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
    _SD_ERR = ""
except Exception as _e:
    sd = None
    HAS_SD = False
    _SD_ERR = f"{type(_e).__name__}: {_e}"
    print(f"[LiveAudio] sounddevice indisponible au démarrage : {_SD_ERR}")

# pyaudiowpatch — WASAPI loopback natif sur Windows (Spotify, YouTube, etc.)
try:
    import pyaudiowpatch as _pyaudio_w
    HAS_PYAUDIOWPATCH = True
except ImportError:
    _pyaudio_w = None
    HAS_PYAUDIOWPATCH = False

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
    'loopback',
    'stereo mix',       # Windows EN
    'mixage stéréo',    # Windows FR (Realtek Stereo Mix)
    'mixage stereo',    # variante sans accent
    'what u hear',      # Creative
    'wave out',
    'mix output',
    'output mix',
    'sum',              # ASIO4ALL
)

# Ports MIDI à exclure (contrôleurs scène déjà pris par MIDIHandler)
_MIDI_EXCLUDE = ('APC', 'LAUNCHPAD', 'MIDIMIX', 'GS WAVETABLE', 'MICROSOFT')


_DEV_EXCLUDE_KEYWORDS = (
    'mappeur de sons', 'microsoft sound mapper',
    'pilote de capture', 'capture driver',
    'périphérique audio principal', 'primary sound',
    '@system32', 'bthhfenum',
    'ksproxy', 'ksthunk',
    'loopmidi', 'loop midi',   # port MIDI virtuel — pas une carte son
    'midi mapper', 'midi through',
    'iac driver',              # Mac MIDI virtuel — pas une carte son
)

def get_audio_devices() -> list:
    """Retourne les périphériques audio WASAPI uniquement, dédoublonnés par nom.
    Format : [{'label': str, 'key': str, 'type': 'input'|'output'}]
    """
    devices = []
    if not HAS_SD:
        return devices
    try:
        all_devs   = sd.query_devices()
        host_apis  = sd.query_hostapis()

        # Trouver l'index de l'API WASAPI
        wasapi_idx = None
        for i, api in enumerate(host_apis):
            if 'wasapi' in api.get('name', '').lower():
                wasapi_idx = i
                break

        seen_names_in  = set()
        seen_names_out = set()

        for idx, dev in enumerate(all_devs):
            name = dev.get('name', '').strip()

            # Ignorer vide, noms système, chemins système
            if not name:
                continue
            nl = name.lower()
            if any(kw in nl for kw in _DEV_EXCLUDE_KEYWORDS):
                continue
            # Ignorer les noms trop courts ou parenthèses vides
            if name in ('()', '( )', ''):
                continue

            # Si WASAPI disponible, ne garder que les devices WASAPI
            if wasapi_idx is not None:
                if dev.get('hostapi') != wasapi_idx:
                    continue

            in_ch  = dev.get('max_input_channels', 0)
            out_ch = dev.get('max_output_channels', 0)

            if in_ch > 0 and name not in seen_names_in:
                seen_names_in.add(name)
                is_lb = any(kw in nl for kw in _LOOPBACK_KEYWORDS)
                devices.append({
                    'label': f"🎤  {name}",
                    'key':   f"dev_in:{idx}",
                    'type':  'loopback' if is_lb else 'input',
                    'name':  name, 'idx': idx,
                })
            elif out_ch > 0 and in_ch == 0 and name not in seen_names_out:
                seen_names_out.add(name)
                devices.append({
                    'label': f"🔊  {name}",
                    'key':   f"dev_out:{idx}",
                    'type':  'output',
                    'name':  name, 'idx': idx,
                })

    except Exception as e:
        print(f"[LiveAudio] get_audio_devices: {e}")
    return devices


class _PyAudioLoopbackStream:
    """
    Wrapper pyaudiowpatch en mode BLOCKING + thread Python.

    WASAPI loopback bloque stream.read() quand aucun audio ne joue sur le device.
    Pour éviter de bloquer l'engine, un thread watchdog émet du silence toutes les
    50 ms quand aucun chunk n'est reçu depuis plus de 150 ms.
    """
    _SILENCE_GAP = 0.15   # s sans chunk → émettre silence (WASAPI loopback inactif)

    def __init__(self, pa_instance, pa_stream, process_chunk_fn,
                 update_bands_fn, chunk_size: int, channels: int, has_np: bool):
        self._pa             = pa_instance
        self._stream         = pa_stream
        self._process_chunk  = process_chunk_fn
        self._update_bands   = update_bands_fn
        self._chunk_size     = chunk_size
        self._channels       = channels
        self._has_np         = has_np
        self._running        = False
        self._last_chunk_ts  = 0.0
        self._reader_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None

    def start(self):
        self._running       = True
        self._last_chunk_ts = time.monotonic()
        self._reader_thread   = threading.Thread(
            target=self._reader, daemon=True, name='PyAudioReader')
        self._watchdog_thread = threading.Thread(
            target=self._watchdog, daemon=True, name='PyAudioWatchdog')
        self._reader_thread.start()
        self._watchdog_thread.start()

    def stop(self):
        self._running = False

    def close(self):
        self._running = False
        # Le reader peut bloquer sur stream.read() → on ferme le stream pour le débloquer
        try:
            self._stream.close()
        except Exception:
            pass
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=0.5)
        try:
            self._pa.terminate()
        except Exception:
            pass

    def _watchdog(self):
        """Émet du silence si stream.read() bloque (WASAPI inactif = pas d'audio)."""
        while self._running:
            time.sleep(0.05)
            if not self._running:
                break
            if time.monotonic() - self._last_chunk_ts > self._SILENCE_GAP:
                self._process_chunk(0.0)
                self._last_chunk_ts = time.monotonic()

    def _reader(self):
        """Thread de lecture bloquante — stream.read() peut bloquer sans audio WASAPI."""
        import struct as _st
        ch   = self._channels
        size = self._chunk_size

        while self._running:
            try:
                raw_bytes = self._stream.read(size, exception_on_overflow=False)
            except OSError:
                # -9999 / -9981 : device inactif ou overflow → le watchdog gère le silence
                time.sleep(0.04)
                continue
            except Exception:
                time.sleep(0.05)
                continue

            if not self._running:
                break

            n = len(raw_bytes) // 4
            if n == 0:
                self._last_chunk_ts = time.monotonic()
                self._process_chunk(0.0)
                continue

            if self._has_np:
                import numpy as _np
                audio   = _np.frombuffer(raw_bytes, dtype=_np.float32).reshape(-1, ch)
                mono    = ((audio[:, 0] + audio[:, 1]) * 0.5
                           if ch >= 2 else audio[:, 0])
                raw_rms = float(((mono * mono).mean()) ** 0.5)
                rms     = raw_rms * 3.0 if raw_rms > 0.0003 else 0.0
                self._update_bands(mono)
            else:
                s       = _st.unpack(f'{n}f', raw_bytes)
                ms      = ([(s[i] + s[i+1]) * 0.5 for i in range(0, n - 1, 2)]
                           if ch == 2 else list(s))
                raw_rms = (sum(x * x for x in ms) / len(ms)) ** 0.5 if ms else 0.0
                rms     = raw_rms * 3.0 if raw_rms > 0.0003 else 0.0

            self._last_chunk_ts = time.monotonic()
            self._process_chunk(rms)


class _SilentStream:
    """Stream muet placeholder — utilisé pendant le retry pyaudiowpatch (3 s)."""
    def start(self):  pass
    def stop(self):   pass
    def close(self):  pass


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
        self._max_dimmers    = {}            # {groupe: 0–100} plafond de niveau par groupe

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
        self.midi_paused          = False

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

        # Timer Qt émetteur d'état lumière (25 ms = 40 fps, aligné sur le DMX)
        # 40 fps évite les paliers visibles sur le mouvement des lyres en mode live.
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
        self._state_timer.start(25)   # 40 fps (aligné DMX) — mouvement lyres plus fluide

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

    def update_dimmers(self, dimmers: dict):
        """Plafond de niveau par groupe (0–100) appliqué en temps réel au mode LIVE."""
        self._max_dimmers = dict(dimmers or {})

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
        global sd, HAS_SD, _SD_ERR
        # Tentative d'import tardif (peut réussir si installé après démarrage)
        if not HAS_SD:
            try:
                import sounddevice as _sd_late
                sd = _sd_late
                HAS_SD = True
                _SD_ERR = ""
            except Exception:
                pass
        if not HAS_SD:
            import sys
            if getattr(sys, 'frozen', False):
                # EXE PyInstaller : sounddevice absent du bundle → rebuild nécessaire
                self.device_info.emit("Capture audio indisponible (build incomplet)")
            else:
                self.device_info.emit("sounddevice manquant — pip install sounddevice")
            self.connection_status.emit('off')
            self._start_audio_fallback()
            return
        try:
            if self._source_key == "loopback":
                stream = self._try_loopback()
            elif self._source_key == "virtualdj":
                self._open_vdj_http()
                return
            elif self._source_key.startswith("dev_in:"):
                stream = self._try_input_device(int(self._source_key.split(":")[1]))
            elif self._source_key.startswith("dev_out:"):
                stream = self._try_loopback_device(int(self._source_key.split(":")[1]))
            else:
                stream = self._try_input()
            if stream:
                stream.start()
                self._stream = stream
                return
        except Exception as e:
            print(f"LiveAudio: erreur stream ({e})")
            self.device_info.emit(f"Erreur audio : {e}")
            self.connection_status.emit('off')
            self._start_audio_fallback()
            return
        # stream is None
        if self._source_key.startswith("dev_out:"):
            self.device_info.emit(
                "Aucun signal capté — voir le guide de configuration ( ? )")
        elif self._source_key == "loopback":
            self.device_info.emit(
                "Aucune capture audio — voir le guide de configuration ( ? )")
        else:
            self.device_info.emit("Aucun micro / entrée ligne détecté")
        self.connection_status.emit('off')
        self._start_audio_fallback()

    def _try_loopback(self):
        # ── 1. pyaudiowpatch WASAPI loopback (Windows — capture n'importe quel device) ──
        if HAS_PYAUDIOWPATCH:
            stream = self._try_loopback_pyaudio()
            if stream:
                return stream
            # pyaudiowpatch a échoué — programmer un retry dans 3 s
            # (device USB/HDMI pas encore prêt juste après le démarrage Windows)
            if self._fallback_tmr is None:  # pas déjà en fallback
                print("LiveAudio: pyaudiowpatch échoué — retry dans 3 s")
                self.device_info.emit("Loopback WASAPI : initialisation… (retry dans 3 s)")
                self.connection_status.emit('waiting')
                self._loopback_retry_count = getattr(self, '_loopback_retry_count', 0) + 1
                if self._loopback_retry_count <= 3:
                    QTimer.singleShot(3000, self._retry_loopback_pyaudio)
                    return _SilentStream()  # stream muet, évite le fallback Stéréo Mix

        # ── 2. sounddevice — devices loopback nommés (Stereo Mix, Wave Out…) ──
        # ⚠ Ces devices ne capturent QUE la sortie de leur propre carte son.
        # Si la sortie par défaut Windows est sur un autre périphérique (USB, HDMI),
        # le signal sera vide. Dans ce cas, pyaudiowpatch est la seule vraie solution.
        if HAS_SD:
            # Identifier la carte du device de sortie par défaut Windows
            default_out_hint = ""
            try:
                default_out = sd.query_devices(kind='output')
                default_out_hint = default_out.get('name', '').lower()
            except Exception:
                pass

            try:
                all_devs = sd.query_devices()
            except Exception:
                all_devs = []
            for i, dev in enumerate(all_devs):
                if dev.get('max_input_channels', 0) < 1:
                    continue
                name = dev.get('name', '').lower()
                if any(k in name for k in _LOOPBACK_KEYWORDS):
                    sr = int(dev.get('default_samplerate', 44100))
                    ch = max(1, min(2, int(dev.get('max_input_channels', 2))))
                    self._band_sr = sr
                    try:
                        stream = sd.InputStream(
                            device=i, channels=ch, samplerate=sr,
                            blocksize=int(sr * 0.05),
                            callback=self._audio_cb,
                        )
                        # Vérifier si la carte Stéréo Mix correspond à la sortie par défaut.
                        # Ex: sortie=USB PnP + Stéréo Mix=Realtek → signal vide.
                        # On considère OK seulement si le mot-clé de la carte de sortie
                        # est explicitement dans le nom du device loopback (hors mots génériques).
                        _GENERIC = {'audio', 'sound', 'device', 'input', 'output',
                                    'hd', 'driver', 'display', 'microsoft', 'for'}
                        out_words = {
                            w for w in default_out_hint.replace('(', ' ').replace(')', ' ').split()
                            if len(w) > 3 and w not in _GENERIC
                        }
                        dev_name_lower = dev['name'].lower()
                        # Externe si sortie est USB, HDMI, Bluetooth — Stéréo Mix ne les capture pas
                        out_is_external = any(k in default_out_hint for k in ('usb', 'hdmi', 'bluetooth', 'bt'))
                        same_card = (not out_is_external) and bool(
                            out_words and any(w in dev_name_lower for w in out_words)
                        )
                        if not same_card and out_is_external:
                            warn = " ⚠ pas de signal (sortie USB/HDMI, utilisez WASAPI)"
                        elif not same_card:
                            warn = " ⚠ sortie défaut sur une autre carte"
                        else:
                            warn = ""
                        self.device_info.emit(f"Loopback : {dev['name']}{warn}")
                        self.connection_status.emit('connected' if same_card else 'waiting')
                        print(f"LiveAudio: loopback nommé → {dev['name']}{warn}")
                        return stream
                    except Exception:
                        continue
        return None

    def _retry_loopback_pyaudio(self):
        """Retry pyaudiowpatch après délai (device USB pas encore prêt au boot)."""
        if not self._running:
            return
        n = getattr(self, '_loopback_retry_count', 1)
        print(f"LiveAudio: retry pyaudiowpatch loopback #{n}…")
        self._log_audio(f"retry pyaudiowpatch #{n}")
        stream = self._try_loopback_pyaudio()
        if stream:
            # Remplacer le stream muet par le vrai stream
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
            stream.start()
            self._stream = stream
            self._loopback_retry_count = 0
            self._log_audio("retry pyaudiowpatch OK")
        elif n < 3:
            self._loopback_retry_count = n + 1
            QTimer.singleShot(3000, self._retry_loopback_pyaudio)
        else:
            # Tous les retries épuisés → fallback sounddevice Stéréo Mix
            self._log_audio("retry pyaudiowpatch épuisé → fallback sounddevice")
            print("LiveAudio: retries pyaudiowpatch épuisés → fallback sounddevice")
            self.device_info.emit(
                "WASAPI indisponible — vérifiez votre périphérique audio par défaut")
            self.connection_status.emit('off')
            self._loopback_retry_count = 0

    @staticmethod
    def _log_audio(msg: str):
        """Log dans un fichier texte — visible même depuis l'EXE PyInstaller."""
        try:
            import os, datetime
            log_path = os.path.join(os.path.expanduser('~'), 'mystrow_audio_debug.log')
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n")
        except Exception:
            pass

    def _try_loopback_pyaudio(self):
        """
        Capture WASAPI loopback via pyaudiowpatch (mode blocking + thread).

        Stratégie : essayer le device loopback par défaut en premier, puis
        tous les autres devices loopback disponibles.  Un "sondage" rapide
        (200 ms) distingue :
          - -9999 immédiat → device ne supporte pas WASAPI loopback (skip)
          - timeout (blocage) → WASAPI OK, pas encore d'audio  (utiliser !)
          - données reçues  → fonctionne parfaitement            (utiliser !)
        """
        try:
            p = _pyaudio_w.PyAudio()
        except Exception as e:
            self._log_audio(f"PyAudio() échoué: {e}")
            return None

        # ── Collecter tous les devices loopback ────────────────────────────
        loopback_devices = []
        try:
            default = p.get_default_wasapi_loopback()
            loopback_devices.append(default)
        except Exception:
            pass
        try:
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if d.get('isLoopbackDevice') and d not in loopback_devices:
                    loopback_devices.append(d)
        except Exception:
            pass

        if not loopback_devices:
            p.terminate()
            self._log_audio("pyaudiowpatch: aucun device loopback trouvé")
            return None

        # ── Sonder chaque device (timeout 200 ms pour détecter les -9999) ─
        for dev_info in loopback_devices:
            sr   = int(dev_info.get('defaultSampleRate', 48000))
            ch   = min(2, max(1, dev_info.get('maxInputChannels', 2)))
            idx  = dev_info['index']
            name = dev_info.get('name', 'inconnu')
            chunk_size = int(sr * 0.05)

            self._log_audio(f"sonde [{idx}] {name}")

            try:
                pa_stream = p.open(
                    format=_pyaudio_w.paFloat32,
                    channels=ch, rate=sr,
                    frames_per_buffer=chunk_size,
                    input=True,
                    input_device_index=idx,
                )
            except Exception as e:
                self._log_audio(f"  p.open() échoué: {type(e).__name__}: {e}")
                continue

            # Sondage rapide : lit 1 chunk avec timeout 200 ms
            probe_result = [None]  # None=timeout, bytes=OK, Exception=erreur
            probe_done   = threading.Event()

            def _probe(s=pa_stream, r=probe_result, ev=probe_done):
                try:
                    r[0] = s.read(chunk_size, exception_on_overflow=False)
                except Exception as ex:
                    r[0] = ex
                ev.set()

            threading.Thread(target=_probe, daemon=True, name='PAProbe').start()
            got_data = probe_done.wait(timeout=0.20)

            if got_data and isinstance(probe_result[0], Exception):
                # -9999 ou autre erreur immédiate → device inopérant
                err = probe_result[0]
                self._log_audio(f"  skip {name}: {err}")
                print(f"LiveAudio: skip [{idx}] {name}: {err}")
                try:
                    pa_stream.close()
                except Exception:
                    pass
                continue  # Essayer le suivant

            # Timeout (WASAPI attend audio) OU données reçues → device valide !
            status = "données reçues" if got_data else "WASAPI en attente (OK)"
            self._log_audio(f"  → {name}: {status}")
            print(f"LiveAudio: pyaudiowpatch loopback [{idx}] {name} ({status})")

            self._band_sr = sr
            self.device_info.emit(f"Loopback WASAPI : {name}")
            self.connection_status.emit('connected')
            return _PyAudioLoopbackStream(
                p, pa_stream,
                process_chunk_fn=self._process_chunk,
                update_bands_fn=self._update_bands,
                chunk_size=chunk_size,
                channels=ch,
                has_np=HAS_NP,
            )

        # Tous les devices loopback ont échoué
        p.terminate()
        self._log_audio("pyaudiowpatch: tous les devices loopback ont échoué")
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

    def _try_input_device(self, dev_idx: int):
        """Ouvre un périphérique d'entrée spécifique par son index sounddevice."""
        try:
            dev = sd.query_devices(dev_idx)
            name = dev.get('name', '').lower()
            # Rejeter les ports MIDI qui se glissent dans la liste audio
            if any(kw in name for kw in ('loopmidi', 'loop midi', 'midi', 'iac driver')):
                self.device_info.emit(f"'{dev['name']}' est un port MIDI, pas une carte son")
                self.connection_status.emit('off')
                self._start_audio_fallback()
                return None
            sr  = int(dev.get('default_samplerate', 44100))
            ch  = max(1, min(2, int(dev.get('max_input_channels', 1))))
            self._band_sr = sr
            self.device_info.emit(f"Entrée : {dev['name']}")
            self.connection_status.emit('connected')
            print(f"LiveAudio: entrée → {dev['name']} (idx {dev_idx})")
            return sd.InputStream(
                device=dev_idx, channels=ch, samplerate=sr,
                blocksize=int(sr * 0.05),
                callback=self._audio_cb,
            )
        except Exception as e:
            print(f"LiveAudio: entrée {dev_idx} erreur ({e})")
            return None

    def _try_loopback_device(self, dev_idx: int):
        """Loopback WASAPI sur un périphérique de sortie spécifique (par nom)."""
        # Récupérer le nom du device depuis sounddevice
        sd_name = ""
        if HAS_SD:
            try:
                sd_name = sd.query_devices(dev_idx).get('name', '').strip()
            except Exception:
                pass

        # Méthode 1 : pyaudiowpatch — matcher le loopback par nom
        if HAS_PYAUDIOWPATCH:
            try:
                pa = _pyaudio_w.PyAudio()
                # Collecter tous les devices loopback disponibles
                loopback_devices = []
                for i in range(pa.get_device_count()):
                    d = pa.get_device_info_by_index(i)
                    if d.get('isLoopbackDevice'):
                        loopback_devices.append((i, d))

                # Chercher le loopback correspondant au device sélectionné (matching partiel)
                loopback_idx = None
                lb_name_found = ""
                if sd_name:
                    # Mots-clés du nom du device (ex: "DDJ-400" → ['DDJ', '400'])
                    keywords = [w for w in sd_name.replace('-', ' ').split() if len(w) >= 3]
                    for lb_idx, lb_info in loopback_devices:
                        lb_n = lb_info.get('name', '')
                        if any(kw.lower() in lb_n.lower() for kw in keywords):
                            loopback_idx = lb_idx
                            lb_name_found = lb_n
                            break

                # Fallback : premier loopback dispo
                if loopback_idx is None and loopback_devices:
                    loopback_idx, lb_d = loopback_devices[0]
                    lb_name_found = lb_d.get('name', '')

                if loopback_idx is not None:
                    lb_info    = pa.get_device_info_by_index(loopback_idx)
                    sr         = int(lb_info.get('defaultSampleRate', 48000))
                    ch         = max(1, min(2, int(lb_info.get('maxInputChannels', 2))))
                    chunk_size = int(sr * 0.05)
                    try:
                        pa_stream = pa.open(
                            format=_pyaudio_w.paFloat32,
                            channels=ch, rate=sr,
                            frames_per_buffer=chunk_size,
                            input=True,
                            input_device_index=loopback_idx,
                        )
                    except Exception as oe:
                        print(f"LiveAudio: p.open loopback erreur ({oe})")
                        pa.terminate()
                        raise
                    self._band_sr = sr
                    display = sd_name or lb_name_found
                    self.device_info.emit(f"Loopback : {display}")
                    self.connection_status.emit('connected')
                    print(f"LiveAudio: loopback → {lb_name_found} (idx {loopback_idx})")
                    return _PyAudioLoopbackStream(
                        pa, pa_stream,
                        process_chunk_fn=self._process_chunk,
                        update_bands_fn=self._update_bands,
                        chunk_size=chunk_size,
                        channels=ch,
                        has_np=HAS_NP,
                    )
                pa.terminate()
            except Exception as e:
                print(f"LiveAudio: loopback pyaudio erreur ({e})")

        # Méthode 2 : sounddevice — tenter capture directe si le device a des canaux entrée
        if HAS_SD and dev_idx >= 0:
            try:
                dev = sd.query_devices(dev_idx)
                sr  = int(dev.get('default_samplerate', 44100))
                ch  = max(1, min(2, int(dev.get('max_input_channels', 0))))
                if ch > 0:
                    self._band_sr = sr
                    self.device_info.emit(f"Capture : {sd_name}")
                    self.connection_status.emit('connected')
                    return sd.InputStream(
                        device=dev_idx, channels=ch, samplerate=sr,
                        blocksize=int(sr * 0.05),
                        callback=self._audio_cb,
                    )
            except Exception as e:
                print(f"LiveAudio: capture sd erreur ({e})")

        self.device_info.emit(f"Loopback introuvable pour : {sd_name}")
        self.connection_status.emit('off')
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
        self._midi_clock_logged = False
        try:
            self._midi_clock_in = _rtmidi.MidiIn()
            ports = self._midi_clock_in.get_ports()
            self._log_audio(f"MIDI Clock : ports détectés = {ports}")

            if not ports:
                self.device_info.emit("MIDI Clock : aucun port MIDI trouvé")
                self._log_audio("MIDI Clock : AUCUN port MIDI (IAC en ligne ?)")
                self._start_beat_timer()
                return

            # Priorité 1 : port nommé "MyStrow" (loopMIDI dédié)
            target_idx, target_name = None, None
            for i, name in enumerate(ports):
                if 'mystrow' in name.lower():
                    target_idx, target_name = i, name
                    break

            # Priorité 2 : port correspondant au hint (ex: "Rekordbox")
            if target_idx is None and hint:
                for i, name in enumerate(ports):
                    if hint.lower() in name.lower():
                        target_idx, target_name = i, name
                        break

            # Priorité 3 : premier port loopMIDI (contient "loopmidi" ou "loop")
            if target_idx is None:
                for i, name in enumerate(ports):
                    if 'loop' in name.lower():
                        target_idx, target_name = i, name
                        break

            # Priorité 4 : premier port non-contrôleur
            if target_idx is None:
                for i, name in enumerate(ports):
                    up = name.upper()
                    if not any(ex in up for ex in _MIDI_EXCLUDE):
                        target_idx, target_name = i, name
                        break

            # Fallback : premier port disponible
            if target_idx is None:
                target_idx, target_name = 0, ports[0]

            # Retry x3 : le port loopMIDI peut prendre un instant à s'initialiser
            last_err = None
            for _attempt in range(3):
                try:
                    self._midi_clock_in.open_port(target_idx)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(0.4)
                    # Recréer l'objet MidiIn entre chaque tentative
                    try:
                        del self._midi_clock_in
                    except Exception:
                        pass
                    self._midi_clock_in = _rtmidi.MidiIn()
                    ports = self._midi_clock_in.get_ports()
                    if target_idx >= len(ports):
                        break
            if last_err:
                self.device_info.emit(
                    f"MIDI Clock : port « {target_name} » indisponible — "
                    "voir le guide de configuration ( ? )")
                self._start_beat_timer()
                return
            # timing=False = recevoir les 0xF8 (MIDI Clock)
            self._midi_clock_in.ignore_types(sysex=True, timing=False, active_sense=True)
            self._midi_clock_in.set_callback(self._midi_clock_cb)

            label = f"{'Rekordbox' if hint else 'MIDI Clock'} : {target_name}"
            self.device_info.emit(label)
            self.connection_status.emit('waiting')
            self._midi_ever_beat = False
            self._log_audio(f"MIDI Clock : port ouvert → « {target_name} » (en attente d'horloge…)")
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
        if not msg:
            return

        if msg[0] != 0xF8:
            return

        # Diagnostic : confirme (une fois) que l'horloge arrive bien du logiciel DJ
        if not getattr(self, '_midi_clock_logged', False):
            self._midi_clock_logged = True
            self._log_audio("MIDI Clock : premier 0xF8 reçu ✓ (l'émetteur envoie bien)")

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

        # Si aucun beat MIDI reçu depuis > 2 s → platine en pause
        if self._source_key in ('midi_clock', 'rekordbox') and self._last_beat_ts > 0:
            since_beat = time.monotonic() - self._last_beat_ts
            if since_beat > 2.0:
                self._pending_beat_energy = 0.0
                self.midi_paused = True
                self.energy_updated.emit(0.0)
                return
        self.midi_paused = False

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
        raw  = float(((mono * mono).mean()) ** 0.5)
        rms  = raw * 3.0 if raw > 0.0003 else 0.0
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

        # Kick drum : 20-80 Hz sub-bass — marqueur de beat le plus fiable en EDM/house.
        # refract=0.35 s → max 171 BPM, évite le double-kick (deux spikes rapprochés).
        # En source audio (loopback / mic) : le kick pilote directement le BPM,
        # bien plus précis que la détection RMS full-spectre (snare/hihat polluent).
        if _spike('sub',   'kick',  threshold=1.9, refract=0.35):
            self._last_transient['kick'] = now
            self._pending_transients.append('kick')
            if self._source_key in ('loopback', 'mic') and not self._manual_bpm:
                self._last_beat_ts = now
                self.audio_ai.beats.append(self._elapsed_ms)
                self._beat_times.append(now)
                self._beat_pending = True
                self._update_bpm()

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

        # Floor à 0.001 — laisse la normalisation adapter les signaux loopback faibles
        local_max = max(max(self._rms_history) if self._rms_history else 0.01, 0.001)
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
            now = time.monotonic()
            # Si numpy dispo, le kick FFT (_detect_transients) pilote le BPM.
            # La détection RMS full-spectre (snare/hihat/voix) reste en fallback
            # uniquement si aucun kick n'a été détecté depuis 4 s (musique sans kick).
            _kick_recent = HAS_NP and (now - self._last_transient['kick']) < 4.0
            if not _kick_recent:
                avg       = sum(self._rms_history) / len(self._rms_history)
                # Seuil plus élevé qu'avant pour réduire les faux positifs (snare / hihat)
                # Base 2.0 ± sensibilité (1.7 à 2.35)
                threshold = avg * (2.0 + (self._sensitivity - 0.5) * 0.7)
                # gap min 340–430 ms → max ~176 BPM ; évite détection en double-temps
                min_gap   = 0.43 - self._nervosity * 0.09
                # norm > 0.20 : ignorer les beats fantômes en quasi-silence
                if norm > threshold and norm > 0.20 and (now - self._last_beat_ts) > min_gap:
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

        # Intervalles bruts entre les derniers beats (fenêtre 8 derniers)
        recent = list(self._beat_times)[-8:]
        raw_ivs = [recent[i+1] - recent[i] for i in range(len(recent)-1)]

        # Plage DJ : 60–185 BPM = 0.32–1.0 s
        valid = [iv for iv in raw_ivs if 0.32 < iv < 1.0]
        if len(valid) < 3:
            return

        # ── Clustering : trouver l'intervalle dominant ────────────────────
        # On cherche le cluster le plus dense dans ±15 % autour de chaque valeur.
        # Évite que quelques faux positifs à 0.4 s tirent la médiane vers 149 BPM
        # quand le vrai beat est à 0.49 s (122 BPM).
        best_center, best_count = valid[0], 0
        for candidate in valid:
            count = sum(1 for iv in valid if abs(iv - candidate) / candidate < 0.15)
            if count > best_count:
                best_count, best_center = count, candidate

        # Moyenne des intervalles dans ce cluster
        cluster = [iv for iv in valid if abs(iv - best_center) / best_center < 0.15]
        median_iv = sum(cluster) / len(cluster)

        new_bpm = 60.0 / median_iv

        # Correction octave : si new_bpm est ~2× ou ~0.5× le BPM courant, recadrer
        if self._bpm > 0:
            ratio = new_bpm / self._bpm
            if 1.8 < ratio < 2.2:
                new_bpm /= 2.0   # double détection → diviser par 2
            elif 0.45 < ratio < 0.56:
                new_bpm *= 2.0   # demi détection → multiplier par 2

        # Lissage adaptatif : plus lent si la différence est grande (stabilise l'affichage)
        if self._bpm > 0:
            diff_pct = abs(new_bpm - self._bpm) / self._bpm
            alpha    = 0.25 if diff_pct < 0.08 else 0.12   # conservateur si grand écart
            self._bpm = self._bpm * (1.0 - alpha) + new_bpm * alpha
        else:
            self._bpm = new_bpm

    # ── Émission état lumière (thread Qt, 40 ms) ───────────────────────────

    def _emit_state(self):
        if not self._running or self._elapsed_ms == 0:
            return
        state = self.audio_ai.get_state_at(self._elapsed_ms, 0, max_dimmers=self._max_dimmers)
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
