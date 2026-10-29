"""
Créer une fixture avec l'IA de son choix (ChatGPT, Gemini, Claude…).

MyStrow n'appelle AUCUNE IA : il fournit un prompt que l'utilisateur colle dans
son assistant habituel avec le tableau DMX du manuel, puis il recolle ici la
réponse. L'ancienne voie (analyse en ligne d'un texte libre) dépendait d'un
service et d'une clé, et se trompait sur tout ce qui sortait du RGB.

L'IA écrit le format natif MyStrow (le JSON de `.mystrow`), pas un XML QLC+ :
le XML ramène zoom/frost/iris, rotations gobo et prisme, couronne LED, presets
et fumée à quelques groupes génériques, et tout le reste tombe en « Mode ».
Ici chaque canal reçoit directement son vrai type MyStrow.

La réponse d'une IA n'est jamais propre : texte avant/après, balises ```json,
virgules en trop, types inventés (« Dimmer », « Red »). `parse_ai_response`
absorbe tout ça et ramène le résultat à une entrée de bibliothèque valide.
"""
import json
import math
import re

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QFrame, QApplication, QMessageBox, QWidget,
)
from PySide6.QtCore import Qt, QTimer, QElapsedTimer, QRectF, QPointF
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QPolygonF

from i18n import tr, get_language


# ── Types de canaux expliqués à l'IA ──────────────────────────────────────────
# Ordre = ordre de lecture du prompt. Chaque description dit QUAND choisir le
# type, pas ce que fait le moteur : c'est la confusion entre voisins (Strobe /
# Shutter, Mode / Preset, Gobo / Anim) qui produisait les fixtures fausses.
_TYPE_DOC = [
    ("Dim", "master dimmer / intensity"),
    ("Dim2", "second, independent dimmer (e.g. a separate LED zone)"),
    ("DimCurve", "dimmer curve / dimmer speed mode"),
    ("R", "red"), ("G", "green"), ("B", "blue"), ("W", "white (warm, cold or neutral)"),
    ("Ambre", "amber"), ("UV", "UV / violet"), ("Orange", "orange"), ("Lime", "lime"),
    ("C", "cyan (CMY colour mixing)"), ("M", "magenta (CMY)"), ("Y", "yellow (CMY)"),
    ("CTO", "colour temperature correction towards warm (CTO)"),
    ("CTB", "colour temperature correction towards cold (CTB)"),
    ("ColorWheel", "colour wheel (fixed colour positions)"),
    ("ColorWheel2", "second colour wheel"),
    ("Strobe", "DEDICATED strobe channel (strobe speed only)"),
    ("Shutter", "shutter channel that mixes closed / open / strobe ranges"),
    ("Pan", "pan, coarse (8-bit MSB)"), ("PanFine", "pan fine (16-bit LSB)"),
    ("Tilt", "tilt, coarse"), ("TiltFine", "tilt fine"),
    ("Speed", "pan/tilt movement speed (or the speed of a built-in effect "
              "on spark/flame machines)"),
    ("Gobo1", "gobo wheel (or the pattern selection of a laser)"),
    ("Gobo1Rot", "gobo wheel rotation / indexing (or laser pattern rotation)"),
    ("Gobo2", "second gobo wheel"), ("Gobo2Rot", "second gobo wheel rotation"),
    ("Prism", "prism insertion"), ("PrismRot", "prism rotation"),
    ("Anim", "animation wheel (NOT a gobo)"), ("AnimRot", "animation wheel rotation"),
    ("Zoom", "zoom (or laser pattern size)"), ("Focus", "focus"), ("Iris", "iris"),
    ("Frost", "frost / diffusion filter"),
    ("RingDim", "LED ring (secondary light source) dimmer"),
    ("RingR", "LED ring red"), ("RingG", "LED ring green"), ("RingB", "LED ring blue"),
    ("RingW", "LED ring white"), ("RingStrobe", "LED ring strobe"),
    ("RingFX", "LED ring built-in programs"), ("RingSpeed", "LED ring program speed"),
    ("Smoke", "smoke / haze output of a fog or haze machine"),
    ("Fan", "fan speed of a fog/haze machine"),
    ("Spark", "output of a cold-spark machine"),
    ("Flame", "output of a flame machine"),
    ("Sound", "built-in microphone sensitivity"),
    ("Preset1", "channel whose values select NAMED functions or programs "
                "(off / DMX mode / auto / sound, macros, built-in shows…). "
                "Use Preset2, Preset3, Preset4 for the 2nd, 3rd, 4th such channel"),
    ("Preset2", "see Preset1"), ("Preset3", "see Preset1"), ("Preset4", "see Preset1"),
    ("Effects", "built-in effect intensity / effect selection with no named ranges"),
    ("Mode", "maintenance or generic control channel left at 0 by default "
             "(lamp on/off, calibration, display…)"),
    ("Reset", "dedicated reset channel"),
    ("Unused", "anything else, reserved, or not understood: it is output at 0 "
               "and keeps the following channels at the right address"),
]

VALID_TYPES = [t for t, _ in _TYPE_DOC]

# Types de fixture de la bibliothèque (cf. fixture_editor.FIXTURE_TYPES).
_FIXTURE_TYPES = ["PAR LED", "Moving Head", "Laser", "Barre LED", "Stroboscope",
                  "Machine a fumee", "Machine a brouillard",
                  "Machine a etincelles", "Lance-flamme", "Gradateur"]
_FIXTURE_TYPE_DOC = {
    "PAR LED":              "LED PAR, wash or any static fixture without pan/tilt",
    "Moving Head":          "moving head (spot, wash, beam) or scanner",
    "Laser":                "laser",
    "Barre LED":            "LED bar / batten",
    "Stroboscope":          "strobe",
    "Machine a fumee":      "fog / smoke machine",
    "Machine a brouillard": "hazer",
    "Machine a etincelles": "cold-spark machine",
    "Lance-flamme":         "flame machine",
    "Gradateur":            "dimmer pack / conventional dimmer",
}

# Ce que les IA écrivent quand elles n'ont pas suivi la liste. Clés en
# minuscules, sans espaces ni tirets (cf. `_norm`).
_TYPE_ALIASES = {
    "dimmer": "Dim", "intensity": "Dim", "master": "Dim", "masterdimmer": "Dim",
    "red": "R", "green": "G", "blue": "B", "white": "W",
    "warmwhite": "W", "coldwhite": "W", "coolwhite": "W",
    "amber": "Ambre", "violet": "UV", "ultraviolet": "UV",
    "cyan": "C", "magenta": "M", "yellow": "Y",
    "color": "ColorWheel", "colour": "ColorWheel", "colorwheel1": "ColorWheel",
    "colourwheel": "ColorWheel",
    "gobo": "Gobo1", "gobowheel": "Gobo1", "goborotation": "Gobo1Rot",
    "gobo1rotation": "Gobo1Rot", "gobo2rotation": "Gobo2Rot",
    "prismrotation": "PrismRot", "animation": "Anim", "animationwheel": "Anim",
    "panfine16bit": "PanFine", "tiltfine16bit": "TiltFine",
    "pan16bit": "PanFine", "tilt16bit": "TiltFine",
    "pantiltspeed": "Speed", "movementspeed": "Speed",
    "fog": "Smoke", "haze": "Smoke", "output": "Smoke",
    "macro": "Preset1", "program": "Preset1", "programs": "Preset1",
    "function": "Preset1", "auto": "Preset1",
    "effect": "Effects", "fx": "Effects",
    "control": "Mode", "nothing": "Unused", "none": "Unused",
    "reserved": "Unused", "blank": "Unused", "empty": "Unused",
}

_FIXTURE_TYPE_ALIASES = {
    "par": "PAR LED", "parled": "PAR LED", "wash": "PAR LED",
    "movinghead": "Moving Head", "lyre": "Moving Head", "spot": "Moving Head",
    "beam": "Moving Head", "scanner": "Moving Head",
    "ledbar": "Barre LED", "bar": "Barre LED", "batten": "Barre LED",
    "strobe": "Stroboscope",
    "fogmachine": "Machine a fumee", "smokemachine": "Machine a fumee",
    "fog": "Machine a fumee", "smoke": "Machine a fumee",
    "hazer": "Machine a brouillard", "haze": "Machine a brouillard",
    "sparkmachine": "Machine a etincelles", "spark": "Machine a etincelles",
    "coldspark": "Machine a etincelles",
    "flame": "Lance-flamme", "flamemachine": "Lance-flamme",
    "dimmer": "Gradateur",
}

_LANG_NAMES = {"fr": "French", "en": "English", "es": "Spanish",
               "de": "German", "pt": "Portuguese", "ja": "Japanese"}

# Types dont les valeurs sont des POSITIONS (slots nommés) : seuls ceux-là
# acceptent une liste de slots dans `preset_slots`.
_PRESET_TYPES = ("Preset1", "Preset2", "Preset3", "Preset4")


def _norm(s) -> str:
    return re.sub(r"[\s_\-/.()]+", "", str(s or "")).lower()


_TYPE_BY_NORM = {_norm(t): t for t in VALID_TYPES}
_FTYPE_BY_NORM = {_norm(t): t for t in _FIXTURE_TYPES}


# ── Prompt ────────────────────────────────────────────────────────────────────

def build_prompt(lang: str | None = None) -> str:
    """Prompt à coller dans l'IA, suivi par l'utilisateur du tableau du manuel.

    Rédigé en anglais pour toutes les langues : c'est là que les trois IA
    suivent le plus fidèlement un format imposé. Seuls les noms de canaux sont
    demandés dans la langue de l'utilisateur, puisqu'il les lira dans le patch.
    """
    lang_name = _LANG_NAMES.get(lang or get_language(), "English")
    types = "\n".join(f"- {t}: {d}" for t, d in _TYPE_DOC)
    ftypes = "\n".join(f'- "{t}": {d}' for t, d in _FIXTURE_TYPE_DOC.items())
    return f"""You are a DMX lighting expert. Convert the DMX channel chart of a lighting fixture, pasted at the end of this message, into a fixture file for the MyStrow lighting software.

Reply with ONE JSON code block and nothing else: no explanation before or after it.

FORMAT
{{
  "format": "mystrow-fixture",
  "version": "1",
  "name": "<model name>",
  "manufacturer": "<brand, or \\"Générique\\" if unknown>",
  "fixture_type": "<one of the fixture types below>",
  "modes": [
    {{
      "name": "<mode name, e.g. \\"12CH\\">",
      "profile": ["<channel type of channel 1>", "<channel type of channel 2>", "..."],
      "labels": ["<short readable name of channel 1>", "..."]
    }}
  ],
  "color_wheel_slots": [{{"name": "Red", "color": "#ff0000", "dmx": 20}}],
  "gobo_wheel_slots": [{{"name": "Gobo 1", "color": "#888888", "dmx": 12}}],
  "preset_slots": {{"Preset1": [{{"name": "Sound", "color": "#00cc99", "dmx": 220}}]}},
  "channel_ranges": {{"Pan": [0, 127]}}
}}

FIXTURE TYPES (exact spelling, keep the French words as they are)
{ftypes}

CHANNEL TYPES (exact spelling, case-sensitive; never invent another one)
{types}

RULES
1. One entry in "profile" per DMX channel, in channel order, with no gap: a fixture with 12 channels has exactly 12 entries. "labels" has exactly the same length.
2. One object in "modes" per DMX mode / personality listed in the chart, the most complete mode first.
3. Never use the same channel type twice in a mode, except "Unused" (channels of the same type are driven together). For a second dimmer use Dim2, for a second gobo wheel Gobo2, for a second named-function channel Preset2, and so on. If you still have a duplicate, use "Unused" for the less useful one.
4. 16-bit pan/tilt: coarse channel = Pan / Tilt, fine channel = PanFine / TiltFine.
5. Strobe: a channel that ONLY sets the strobe speed is "Strobe". A channel that mixes closed, open and strobe ranges is "Shutter".
6. A channel whose value ranges select named functions (off / auto / sound / DMX mode, macros, built-in programs) is a Preset channel. List each range in "preset_slots" with "dmx" = the MIDDLE of the range.
7. Colour wheel: list every fixed colour in "color_wheel_slots", with "dmx" = the middle of its range and "color" = an approximate #rrggbb hex value. Skip rotation / rainbow / scroll ranges. Same for gobos in "gobo_wheel_slots" ("color": "#888888"). Leave these lists empty if the chart does not give the ranges.
8. "channel_ranges" (optional): when only part of a channel's travel is usable and the rest triggers an automatic program (e.g. pan 0-127 = position, 128-255 = auto movement), give the usable range [min, max]. Omit the field otherwise.
9. Labels: short, written in {lang_name}, e.g. "Dimmer", "Red", "Pan fine", "Gobo rotation".
10. Pixel bars: list every channel in order and name them "Pixel 1 Red", "Pixel 1 Green"… Use R/G/B/W for the first pixel only and "Unused" for the other pixels (MyStrow splits pixels afterwards).
11. If something is ambiguous, choose the safest type ("Unused" rather than a guess) and keep going: never ask a question, never answer with anything but the JSON block.

FIXTURE DMX CHART (copied from the manual):
"""


# ── Lecture de la réponse ────────────────────────────────────────────────────

def _extract_json(text: str):
    """Premier objet JSON lisible dans la réponse brute d'une IA."""
    text = (text or "").strip()
    if not text:
        raise ValueError(tr("fai_err_empty"))
    candidates = []
    # Bloc ```json … ``` : le cas normal.
    for m in re.finditer(r"```(?:json|JSON)?\s*(.*?)```", text, re.S):
        candidates.append(m.group(1))
    # Sinon de la première accolade à la dernière (texte autour, bloc tronqué).
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        candidates.append(text[i:j + 1])
    candidates.append(text)
    for c in candidates:
        for variant in (c, _relax_json(c)):
            try:
                obj = json.loads(variant)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                obj = obj[0]
            if isinstance(obj, dict):
                return obj
    raise ValueError(tr("fai_err_no_json"))


def _relax_json(s: str) -> str:
    """Défauts habituels des IA : guillemets typographiques, virgules finales,
    commentaires // en bout de ligne."""
    s = (s.replace("“", '"').replace("”", '"')
          .replace("‘", "'").replace("’", "'"))
    s = re.sub(r"(?m)^\s*//.*$", "", s)
    s = re.sub(r",\s*([\]}])", r"\1", s)
    return s


def _channel_type(raw) -> str:
    """Type MyStrow exact, ou « Unused » : un type inconnu ne doit JAMAIS
    piloter quoi que ce soit, mais il garde sa place pour les adresses."""
    n = _norm(raw)
    return _TYPE_BY_NORM.get(n) or _TYPE_ALIASES.get(n) or "Unused"


def _fixture_type(raw, profile, name) -> str:
    n = _norm(raw)
    ft = _FTYPE_BY_NORM.get(n) or _FIXTURE_TYPE_ALIASES.get(n)
    if ft:
        return ft
    from fixture_parser import _detect_fixture_type
    return _detect_fixture_type(profile, name)


def _dedupe(profile: list) -> list:
    """Deux canaux du même type sont gangés par le moteur : le second ressort
    les mêmes valeurs que le premier. Le doublon passe en « Unused »."""
    seen, out = set(), []
    for t in profile:
        if t != "Unused" and t in seen:
            out.append("Unused")
        else:
            seen.add(t)
            out.append(t)
    return out


def _slots(raw, coloured: bool) -> list:
    out = []
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        try:
            dmx = max(0, min(255, int(round(float(s.get("dmx", 0))))))
        except (TypeError, ValueError):
            continue
        col = str(s.get("color") or "")
        if not coloured or not re.fullmatch(r"#[0-9a-fA-F]{6}", col):
            col = "#888888"
        out.append({"name": str(s.get("name") or f"{len(out) + 1}"),
                    "color": col.lower(), "dmx": dmx})
    return out


def parse_ai_response(text: str) -> dict:
    """Réponse de l'IA → entrée de bibliothèque prête à enregistrer.

    La racine décrit le premier mode (c'est ce que lit le patch), les autres
    restent dans `modes` pour le sélecteur de la bibliothèque. Lève ValueError
    avec un message lisible par l'utilisateur.
    """
    obj = _extract_json(text)

    raw_modes = obj.get("modes")
    if not isinstance(raw_modes, list) or not raw_modes:
        # Fixture à plat (« profile » à la racine) : un seul mode.
        raw_modes = [{"name": obj.get("mode_name") or "", "profile": obj.get("profile"),
                      "labels": obj.get("labels")}]

    modes = []
    for m in raw_modes:
        if not isinstance(m, dict) or not isinstance(m.get("profile"), list):
            continue
        profile = _dedupe([_channel_type(t) for t in m["profile"]])
        if not profile or all(t == "Unused" for t in profile):
            continue
        labels = m.get("labels")
        labels = ([str(x or "") for x in labels]
                  if isinstance(labels, list) and len(labels) == len(profile) else [])
        entry = {"name": str(m.get("name") or f"{len(profile)}CH"),
                 "channelCount": len(profile), "profile": profile}
        if any(labels):
            entry["labels"] = labels
        modes.append(entry)
    if not modes:
        raise ValueError(tr("fai_err_no_channels"))

    name = str(obj.get("name") or "").strip() or tr("fai_default_name")
    first = modes[0]
    ftype = _fixture_type(obj.get("fixture_type"), first["profile"], name)

    # Machine à effet sans canal de sortie reconnu : son débit serait mort.
    from core import fix_machine_profile
    for m in modes:
        m["profile"] = fix_machine_profile(ftype, m["profile"], m.get("labels"))

    all_types = {t for m in modes for t in m["profile"]}
    preset_slots = {}
    raw_ps = obj.get("preset_slots")
    for k, v in (raw_ps.items() if isinstance(raw_ps, dict) else []):
        k = _channel_type(k)
        if k in _PRESET_TYPES and k in all_types:
            sl = _slots(v, coloured=True)
            if sl:
                preset_slots[k] = sl

    from core import normalize_channel_ranges
    raw_rg = obj.get("channel_ranges")
    ranges = normalize_channel_ranges(
        {_channel_type(k): v for k, v in raw_rg.items()}
        if isinstance(raw_rg, dict) else {})
    ranges = {k: v for k, v in ranges.items() if k in all_types and k != "Unused"}

    fx = {
        "name":              name,
        "manufacturer":      str(obj.get("manufacturer") or "").strip() or "Générique",
        "fixture_type":      ftype,
        "mode_name":         first["name"],
        "max_channels":      512,
        # Groupe A, comme toute fixture qui arrive : cf. fixture_editor._do_import.
        "group":             "face",
        "profile":           list(first["profile"]),
        "color_wheel_slots": (_slots(obj.get("color_wheel_slots"), coloured=True)
                              if "ColorWheel" in all_types else []),
        "gobo_wheel_slots":  (_slots(obj.get("gobo_wheel_slots"), coloured=False)
                              if "Gobo1" in all_types else []),
        "source":            "user",
        "origin_source":     "ai",
        "modes":             modes,
    }
    if first.get("labels"):
        fx["labels"] = list(first["labels"])
    if preset_slots:
        fx["preset_slots"] = preset_slots
    if ranges:
        fx["channel_ranges"] = ranges
    return fx


def save_to_library(fx: dict) -> str:
    """Ajoute la fixture à la bibliothèque locale, renommée « Nom (2) » si le
    nom est déjà pris. Rend le nom final. Partagé par le menu « Créer votre
    fixture via IA » et l'API locale (assistant IA via MCP)."""
    from fixture_editor import FIXTURE_FILE
    fx["source"] = "user"
    existing = []
    if FIXTURE_FILE.exists():
        data = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            existing = data
    existing_names = {f.get("name") for f in existing}
    name = fx["name"]
    if name in existing_names:
        c = 2
        while f"{name} ({c})" in existing_names:
            c += 1
        fx["name"] = f"{name} ({c})"
    existing.append(fx)
    FIXTURE_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return fx["name"]


# ── Fenêtre ──────────────────────────────────────────────────────────────────

class _FlowAnimation(QWidget):
    """Mini-scène en boucle : ce que l'utilisateur va faire dans son IA.

    Une fenêtre de discussion générique (aucune marque) : le curseur colle le
    prompt, glisse le tableau DMX du manuel dans la conversation, envoie ;
    l'IA répond par un bloc de code, on le copie et il part vers MyStrow.
    Le tableau est l'étape qu'on oublie — l'IA invente alors la fixture — d'où
    sa couleur dorée, la même que la consigne en gras sous l'animation.
    """

    _LOOP_MS = 9000

    # Repères de la boucle (fraction de 0 à 1).
    _T_PASTE, _T_PASTED = 0.07, 0.17          # Ctrl+V, le prompt se remplit
    _T_GRAB, _T_DROP = 0.24, 0.36             # glisser-déposer du tableau
    _T_SEND = 0.46                            # clic sur Envoyer
    _T_TYPING, _T_ANSWER = 0.56, 0.66         # « … » puis bloc de code
    _T_COPY, _T_ARRIVE = 0.82, 0.92           # clic Copier, arrivée MyStrow
    _T_FADE = 0.95

    def __init__(self, accent, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._gold = QColor("#ffc233")
        self._green = QColor("#44cc66")
        self._t = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(40)            # 25 fps, comme le reste de l'app
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(206)
        self._captions = [tr("fai_anim_s1"), tr("fai_anim_s2"),
                          tr("fai_anim_s3"), tr("fai_anim_s4")]

    def showEvent(self, e):
        self._clock.start()
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _tick(self):
        self._t = (self._clock.elapsed() % self._LOOP_MS) / self._LOOP_MS
        self.update()

    # ── Outils ──
    @staticmethod
    def _ramp(t, a, b):
        """0 avant a, 1 après b, adouci entre les deux."""
        if t <= a:
            return 0.0
        if t >= b:
            return 1.0
        u = (t - a) / (b - a)
        return u * u * (3 - 2 * u)

    def _path(self, t, keys):
        """Position interpolée le long de repères [(t, QPointF), …]."""
        if t <= keys[0][0]:
            return QPointF(keys[0][1])
        for (ta, pa), (tb, pb) in zip(keys, keys[1:]):
            if t <= tb:
                u = self._ramp(t, ta, tb)
                return QPointF(pa.x() + (pb.x() - pa.x()) * u,
                               pa.y() + (pb.y() - pa.y()) * u)
        return QPointF(keys[-1][1])

    @staticmethod
    def _lines(p, x, y, widths, colour, step=7, thick=3):
        p.setPen(Qt.NoPen)
        p.setBrush(colour)
        for i, wl in enumerate(widths):
            if wl > 0:
                p.drawRoundedRect(QRectF(x, y + i * step, wl, thick), 1.5, 1.5)

    def _chip(self, p, r, glow=0.0):
        """Pièce jointe « Tableau DMX »."""
        if glow > 0:
            g = QColor(self._gold)
            g.setAlphaF(0.35 * glow)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r.adjusted(-4, -4, 4, 4), 8, 8)
        p.setPen(QPen(self._gold, 1.5))
        p.setBrush(QColor("#3a2f12"))
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor("#ffe7a8"))
        p.setFont(QFont("Segoe UI Emoji", 9))
        p.drawText(QRectF(r.left() + 4, r.top(), 18, r.height()), Qt.AlignCenter, "📄")
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.drawText(QRectF(r.left() + 22, r.top(), r.width() - 24, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, tr("fai_anim_file"))

    def _cursor(self, p, pos, pressed):
        poly = QPolygonF([QPointF(0, 0), QPointF(0, 15), QPointF(4, 11.5),
                          QPointF(7, 17.5), QPointF(9.5, 16.5), QPointF(6.5, 10.5),
                          QPointF(11.5, 10.5)])
        poly.translate(pos)
        p.setPen(QPen(QColor("#000000"), 1.2))
        p.setBrush(QColor("#d8d8d8") if pressed else QColor("#ffffff"))
        p.drawPolygon(poly)

    def _ripple(self, p, pos, t, t0):
        if t0 <= t < t0 + 0.05:
            u = (t - t0) / 0.05
            c = QColor(self._accent)
            c.setAlphaF(1 - u)
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(pos, 4 + 14 * u, 4 + 14 * u)

    # ── Dessin ──
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._t
        w, h = self.width(), self.height()
        fade = 1.0 - self._ramp(t, self._T_FADE, 1.0)

        # Légende de l'étape en cours.
        step = (0 if t < self._T_GRAB - 0.04 else 1 if t < self._T_SEND - 0.04
                else 2 if t < self._T_ANSWER + 0.06 else 3)
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.setPen(self._gold if step == 1 else QColor("#ffffff"))
        p.drawText(QRectF(4, 0, w - 8, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{step + 1} / 4  ·  {self._captions[step]}")

        # Fenêtre de l'IA (générique).
        chat = QRectF(4, 26, w * 0.66, h - 30)
        p.setPen(QPen(QColor("#3a3a3a"), 1))
        p.setBrush(QColor("#151515"))
        p.drawRoundedRect(chat, 8, 8)
        head = QRectF(chat.left(), chat.top(), chat.width(), 22)
        for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c))
            p.drawEllipse(QPointF(head.left() + 12 + i * 11, head.center().y()), 3.5, 3.5)
        p.setPen(QColor("#9a9a9a"))
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.drawText(head, Qt.AlignCenter, "✦  " + tr("fai_anim_ai"))
        p.setPen(QPen(QColor("#2a2a2a"), 1))
        p.drawLine(QPointF(chat.left(), head.bottom()), QPointF(chat.right(), head.bottom()))

        inp = QRectF(chat.left() + 8, chat.bottom() - 38, chat.width() - 16, 30)
        send = QPointF(inp.right() - 15, inp.center().y())

        # Colonne de droite : le fichier du manuel, puis MyStrow.
        col_x = chat.right() + 18
        col_w = w - 4 - col_x
        file0 = QRectF(col_x + (col_w - 96) / 2, chat.top() + 10, 96, 22)
        mys = QRectF(col_x, chat.bottom() - 70, col_w, 70)

        # Bulles de la conversation.
        conv_top = head.bottom() + 8
        ub = QRectF(chat.right() - 8 - chat.width() * 0.56, conv_top,
                    chat.width() * 0.56, 40)
        ab = QRectF(chat.left() + 8, ub.bottom() + 8, chat.width() * 0.62, 44)
        copy_btn = QRectF(ab.right() - 44, ab.top() + 5, 38, 14)

        # Curseur.
        rest = QPointF(chat.right() + 10, chat.bottom() - 90)
        in_pt = QPointF(inp.left() + 40, inp.center().y())
        chip_pt = QPointF(inp.left() + 150, inp.center().y())
        keys = [(0.00, rest), (self._T_PASTE - 0.01, in_pt), (self._T_PASTED, in_pt),
                (self._T_GRAB, file0.center()), (self._T_DROP, chip_pt),
                (self._T_DROP + 0.03, chip_pt), (self._T_SEND - 0.01, send),
                (self._T_SEND + 0.04, send), (self._T_COPY - 0.06, copy_btn.center()),
                (self._T_COPY + 0.02, copy_btn.center()), (self._T_FADE, rest), (1.0, rest)]
        cur = self._path(t, keys)

        p.setOpacity(fade)

        # Zone de saisie.
        p.setPen(QPen(self._accent if self._T_PASTE <= t < self._T_SEND
                      else QColor("#333333"), 1))
        p.setBrush(QColor("#202020"))
        p.drawRoundedRect(inp, 15, 15)
        p.setPen(Qt.NoPen)
        p.setBrush(self._accent if t < self._T_SEND else QColor("#3a3a3a"))
        p.drawEllipse(send, 10, 10)
        p.setPen(QPen(QColor("#000000"), 2))
        p.drawLine(QPointF(send.x(), send.y() + 5), QPointF(send.x(), send.y() - 5))
        p.drawLine(QPointF(send.x(), send.y() - 5), QPointF(send.x() - 4, send.y() - 1))
        p.drawLine(QPointF(send.x(), send.y() - 5), QPointF(send.x() + 4, send.y() - 1))
        if self._T_PASTE <= t < self._T_SEND:
            g = self._ramp(t, self._T_PASTE, self._T_PASTED)
            self._lines(p, inp.left() + 14, inp.top() + 9,
                        [80 * g, 60 * g], QColor("#8a8a8a"))
        if self._T_DROP <= t < self._T_SEND:
            pulse = 0.5 + 0.5 * math.sin(self._clock.elapsed() / 160.0)
            self._chip(p, QRectF(inp.left() + 106, inp.top() + 5, 96, 20), pulse)
        elif not (self._T_DROP <= t):
            p.setPen(QColor("#5a5a5a"))
            p.setFont(QFont("Segoe UI", 8))
            if t < self._T_PASTE:
                p.drawText(inp.adjusted(14, 0, -30, 0), Qt.AlignVCenter, "…")

        # Badge Ctrl+V.
        if self._T_PASTE - 0.01 <= t < self._T_PASTED + 0.03:
            b = QRectF(cur.x() + 14, cur.y() - 22, 46, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(self._accent)
            p.drawRoundedRect(b, 4, 4)
            p.setPen(QColor("#000000"))
            p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            p.drawText(b, Qt.AlignCenter, "Ctrl+V")

        # Bulle de l'utilisateur : monte depuis la zone de saisie.
        if t >= self._T_SEND:
            u = self._ramp(t, self._T_SEND, self._T_SEND + 0.08)
            r = QRectF(ub)
            r.moveTop(inp.top() + (ub.top() - inp.top()) * u)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#1d3a44"))
            p.drawRoundedRect(r, 9, 9)
            self._lines(p, r.left() + 10, r.top() + 9, [r.width() * 0.45, r.width() * 0.32],
                        QColor("#8fb8c4"))
            self._chip(p, QRectF(r.right() - 104, r.top() + 10, 96, 20))

        # Réponse de l'IA : « … » puis bloc de code avec son bouton Copier.
        if t >= self._T_TYPING:
            p.setPen(QPen(QColor("#2e2e2e"), 1))
            p.setBrush(QColor("#1f1f1f"))
            if t < self._T_ANSWER:
                r = QRectF(ab.left(), ab.top(), 52, 24)
                p.drawRoundedRect(r, 9, 9)
                p.setPen(Qt.NoPen)
                for i in range(3):
                    a = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(
                        self._clock.elapsed() / 120.0 - i * 0.9))
                    c = QColor("#bbbbbb")
                    c.setAlphaF(a)
                    p.setBrush(c)
                    p.drawEllipse(QPointF(r.left() + 15 + i * 11, r.center().y()), 3, 3)
            else:
                g = self._ramp(t, self._T_ANSWER, self._T_ANSWER + 0.06)
                p.drawRoundedRect(ab, 9, 9)
                code = ab.adjusted(6, 6, -6, -6)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#0c0c0c"))
                p.drawRoundedRect(code, 5, 5)
                p.setPen(QColor("#e8b04a"))
                p.setFont(QFont("Consolas", 9, QFont.Bold))
                p.drawText(QRectF(code.left() + 7, code.top(), 20, code.height()),
                           Qt.AlignVCenter, "{ }")
                self._lines(p, code.left() + 30, code.top() + 8,
                            [code.width() * 0.42 * g, code.width() * 0.30 * g,
                             code.width() * 0.36 * g], QColor("#5fae7a"), step=6, thick=2.5)
                copied = t >= self._T_COPY
                p.setPen(QPen(self._green if copied else QColor("#555555"), 1))
                p.setBrush(QColor("#1a2e1e") if copied else QColor("#262626"))
                p.drawRoundedRect(copy_btn, 3, 3)
                p.setPen(self._green if copied else QColor("#cccccc"))
                p.setFont(QFont("Segoe UI", 7, QFont.Bold))
                p.drawText(copy_btn, Qt.AlignCenter, "✓" if copied else tr("fai_anim_copy"))

        # MyStrow : s'allume à l'arrivée de la réponse.
        lit = self._ramp(t, self._T_ARRIVE - 0.02, self._T_ARRIVE + 0.02)
        p.setOpacity(1.0)
        p.setPen(QPen(self._mix(QColor("#333333"), self._green, lit * fade), 1.5))
        bg = self._mix(QColor("#1a1a1a"), QColor("#1a3320"), lit * fade)
        p.setBrush(bg)
        p.drawRoundedRect(mys, 9, 9)
        p.setPen(self._mix(QColor("#888888"), QColor("#ffffff"), lit * fade))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(mys.adjusted(4, 4, -4, -4), Qt.AlignCenter | Qt.TextWordWrap,
                   ("✓  " if lit * fade > 0.5 else "") + tr("fai_anim_mystrow"))

        # Fichier du manuel : posé dans la colonne, puis traîné par le curseur.
        if t < self._T_DROP or t >= self._T_FADE:
            fr = QRectF(file0)
            if self._T_GRAB <= t < self._T_DROP:
                fr.moveCenter(cur + QPointF(-6, -4))
            p.setOpacity(1.0 if t < self._T_FADE else self._ramp(t, self._T_FADE, 1.0))
            pulse = 0.5 + 0.5 * math.sin(self._clock.elapsed() / 260.0)
            self._chip(p, fr, pulse)
            p.setOpacity(1.0)

        # Réponse copiée qui file vers MyStrow, en arc.
        if self._T_COPY <= t < self._T_ARRIVE:
            u = self._ramp(t, self._T_COPY, self._T_ARRIVE)
            a, b = copy_btn.center(), mys.center()
            pos = QPointF(a.x() + (b.x() - a.x()) * u,
                          a.y() + (b.y() - a.y()) * u - 30 * math.sin(math.pi * u))
            r = QRectF(0, 0, 30, 18)
            r.moveCenter(pos)
            p.setPen(QPen(self._green, 1.2))
            p.setBrush(QColor("#0c0c0c"))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("#e8b04a"))
            p.setFont(QFont("Consolas", 8, QFont.Bold))
            p.drawText(r, Qt.AlignCenter, "{ }")

        # Clics, puis le curseur par-dessus tout.
        self._ripple(p, send, t, self._T_SEND)
        self._ripple(p, copy_btn.center(), t, self._T_COPY)
        pressed = (abs(t - self._T_SEND) < 0.012 or abs(t - self._T_COPY) < 0.012
                   or self._T_GRAB <= t < self._T_DROP)
        self._cursor(p, cur, pressed)
        p.end()

    @staticmethod
    def _mix(a: QColor, b: QColor, k: float) -> QColor:
        k = max(0.0, min(1.0, k))
        return QColor(int(a.red() + (b.red() - a.red()) * k),
                      int(a.green() + (b.green() - a.green()) * k),
                      int(a.blue() + (b.blue() - a.blue()) * k))


class AIFixtureDialog(QDialog):
    """Étape 1 : copier le prompt. Étape 2 : coller la réponse de l'IA."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from admin_pack_editor import _STYLE_EDITOR, ACCENT, TEXT_DIM
        self._accent, self._dim = ACCENT, TEXT_DIM
        self._fixture = None
        self.setWindowTitle(tr("fai_title"))
        self.setMinimumSize(640, 620)
        self.setStyleSheet(_STYLE_EDITOR)
        self._build_ui()

    def _step_title(self, text):
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl.setStyleSheet(f"color:{self._accent};")
        return lbl

    def _hint(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        # Texte riche : la consigne du tableau DMX est en <b>, dorée comme sa
        # carte dans l'animation, pour trancher sur le gris du reste.
        lbl.setTextFormat(Qt.RichText)
        lbl.setStyleSheet(f"color:{self._dim}; font-size:11px;")
        return lbl

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        lay.addWidget(_FlowAnimation(self._accent, self))

        # ── Étape 1 ──
        lay.addWidget(self._step_title(tr("fai_step1")))
        lay.addWidget(self._hint(tr("fai_step1_hint").replace(
            "<b>", "<b style='color:#ffc233; font-size:12px;'>")))
        row = QHBoxLayout()
        self._btn_copy = QPushButton(tr("fai_copy"))
        self._btn_copy.setFixedHeight(36)
        self._btn_copy.setStyleSheet(
            f"QPushButton {{ background:{self._accent}; color:#000; border:none;"
            f" border-radius:4px; font-weight:bold; font-size:12px; padding:0 20px; }}"
            f"QPushButton:hover {{ background:#33e0ff; }}")
        self._btn_copy.clicked.connect(self._copy_prompt)
        row.addWidget(self._btn_copy)
        row.addStretch()
        lay.addLayout(row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2a2a2a; max-height:1px; margin:6px 0;")
        lay.addWidget(sep)

        # ── Étape 2 ──
        lay.addWidget(self._step_title(tr("fai_step2")))
        self._paste = QTextEdit()
        self._paste.setAcceptRichText(False)
        self._paste.setFont(QFont("Consolas", 10))
        self._paste.setPlaceholderText(tr("fai_paste_placeholder"))
        self._paste.textChanged.connect(lambda: self._status.setText(""))
        lay.addWidget(self._paste, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#ff6666; font-size:11px;")
        lay.addWidget(self._status)

        bot = QHBoxLayout()
        bot.addStretch()
        btn_cancel = QPushButton(tr("fai_cancel"))
        btn_cancel.setFixedHeight(34)
        btn_cancel.clicked.connect(self.reject)
        bot.addWidget(btn_cancel)
        btn_ok = QPushButton(tr("fai_create"))
        btn_ok.setFixedHeight(34)
        btn_ok.setStyleSheet(
            "QPushButton { background:#2d7a3a; color:#fff; border:none; border-radius:4px;"
            " font-weight:bold; font-size:12px; padding:0 20px; }"
            "QPushButton:hover { background:#379147; }")
        btn_ok.clicked.connect(self._create)
        bot.addWidget(btn_ok)
        lay.addLayout(bot)

    def _copy_prompt(self):
        QApplication.clipboard().setText(build_prompt())
        orig = tr("fai_copy")
        self._btn_copy.setText(tr("fai_copied"))
        QTimer.singleShot(2000, lambda: self._btn_copy.setText(orig))

    def _create(self):
        try:
            fx = parse_ai_response(self._paste.toPlainText())
        except ValueError as e:
            self._status.setText(str(e))
            return
        n_unused = fx["profile"].count("Unused")
        msg = tr("fai_summary", name=fx["name"], n=len(fx["profile"]),
                 modes=len(fx["modes"]))
        if n_unused:
            msg += "\n\n" + tr("fai_summary_unused", n=n_unused)
        if QMessageBox.question(self, tr("fai_title"), msg,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes) != QMessageBox.Yes:
            return
        self._fixture = fx
        self.accept()

    def result_fixture(self) -> dict:
        return dict(self._fixture or {})
