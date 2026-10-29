"""
assistant_voice.py — Dictée vocale de l'assistant, hors ligne.

Micro (sounddevice, 16 kHz mono) → faster-whisper sur le processeur → texte.
Le modèle (~145 Mo pour « base ») est téléchargé au premier usage dans
~/.mystrow_voice, puis tout fonctionne sans Internet.

Optionnel : si faster-whisper ou le micro manquent, `available()` le dit et
l'assistant reste utilisable au clavier.
"""

import re
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

SAMPLE_RATE = 16000
MODEL_DIR = Path.home() / ".mystrow_voice"
DEFAULT_MODEL = "base"
# Langues comprises par l'assistant : une détection hors de cette liste (ou peu
# sûre) est refaite dans la langue du logiciel.
_KNOWN = ("fr", "en", "es", "de", "pt", "ja")

_model = None
_model_name = None
_model_lock = threading.Lock()


def available() -> str:
    """'' si la dictée est possible, sinon la raison (texte court).

    Appelé à la construction de l'interface : on vérifie la présence du
    paquet sans l'importer (ctranslate2 coûte une à deux secondes)."""
    import importlib.util
    if importlib.util.find_spec("faster_whisper") is None:
        return "faster-whisper"
    try:
        import sounddevice as sd
        sd.query_devices(kind="input")
    except Exception:
        return "micro"
    return ""


def model_ready(name: str = DEFAULT_MODEL) -> bool:
    return any(MODEL_DIR.glob(f"models--Systran--faster-whisper-{name}/snapshots/*/model.bin"))


def _get_model(name: str):
    global _model, _model_name
    with _model_lock:
        if _model is None or _model_name != name:
            from faster_whisper import WhisperModel
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            _model = WhisperModel(name, device="cpu", compute_type="int8",
                                  download_root=str(MODEL_DIR))
            _model_name = name
        return _model


# Vocabulaire du métier soufflé à Whisper : il écrit « MyStrow », « lyres »… au lieu
# de « mistro », « lire ».
_PROMPT = ("Ok MyStrow, allume les lyres, la face, le contre, les douches, strobe, faders, patch DMX, "
           "REC Lumière, s'il te plaît.")
# « stp » / « s'te plaît » en fin de phrase, que Whisper entend « je te paie ».
_PLEASE_RE = re.compile(r"[,\s]*\b(?:je te (?:paie|paye|pay|pais|plais)|ce te plait|ste plait|s te pl[eé])\s*([.!?]*)\s*$",
                        re.IGNORECASE)
# Ce que Whisper fait encore du nom quand le prompt ne suffit pas.
_NAME_RE = re.compile(r"\b(?:my|mi|maï|maille|mail?)[\s-]?str?[oô]+w?s?\b|\bmy\s?strow\b|\bmystro\w*|\bmistro\w*|\bmaestro\b",
                      re.IGNORECASE)


def fix_name(text: str) -> str:
    """« ok mistro » → « ok MyStrow » ; « …, je te paie » → « …, s'il te plaît »."""
    return _PLEASE_RE.sub(r" s'il te plaît\1", _NAME_RE.sub("MyStrow", text or ""))


def transcribe(audio, lang_hint: str, model_name: str = DEFAULT_MODEL) -> tuple:
    """(texte, langue) pour un tableau float32 16 kHz mono."""
    model = _get_model(model_name)

    def run(language):
        segs, info = model.transcribe(audio, language=language, beam_size=1, initial_prompt=_PROMPT,
                                      condition_on_previous_text=False, vad_filter=False)
        return " ".join(s.text.strip() for s in segs).strip(), info

    text, info = run(None)
    if info.language not in _KNOWN or info.language_probability < 0.5:
        text, info = run(lang_hint if lang_hint in _KNOWN else None)
    return fix_name(text), info.language


class Recorder:
    """Enregistre tant que `stop()` n'est pas appelé."""

    def __init__(self):
        self._chunks = []
        self._stream = None
        self.level = 0.0        # niveau (RMS) du dernier bloc : forme d'onde à l'écran
        self.peak = 0.0         # plus fort niveau entendu : « je n'ai rien entendu »

    def start(self):
        import numpy as np
        import sounddevice as sd
        self._chunks = []
        self.level = self.peak = 0.0

        def on_audio(data, *_):
            self._chunks.append(data.copy())
            self.level = float(np.sqrt(np.mean(data * data)))
            self.peak = max(self.peak, self.level)

        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=on_audio)
        self._stream.start()

    def stop(self):
        import numpy as np
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        if not self._chunks:
            return np.zeros(0, dtype="float32")
        return np.concatenate(self._chunks)[:, 0]


class TranscribeWorker(QThread):
    """Transcription hors du thread Qt. `done(texte, langue)` ou `failed(msg)`."""

    done = Signal(str, str)
    failed = Signal(str)

    def __init__(self, audio, lang_hint: str, model_name: str = DEFAULT_MODEL, parent=None):
        super().__init__(parent)
        self._audio, self._lang, self._model = audio, lang_hint, model_name

    def run(self):
        try:
            text, lang = transcribe(self._audio, self._lang, self._model)
            self.done.emit(text, lang)
        except Exception as exc:
            self.failed.emit(str(exc))
