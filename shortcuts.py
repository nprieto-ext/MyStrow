"""Raccourcis clavier personnalisables de la fenêtre principale.

Chaque action a un identifiant stable, une touche par défaut et un libellé.
Le fichier `~/.mystrow_shortcuts.json` ne garde que les ÉCARTS au défaut :
une action ajoutée plus tard arrive avec sa touche par défaut, sans migration.
Une chaîne vide = action sans raccourci (effacée par l'utilisateur).

    {"keys":    {"save_show": "Ctrl+Alt+S", "strobe": ""},
     "presets": {"Concert": {"color_red": "1", ...}}}

Les séquences sont toujours stockées au format `QKeySequence.PortableText`
(« Ctrl+Shift+S », « PgDown », « Space »), indépendant de la langue.
"""

import json
from pathlib import Path

from PySide6.QtGui import QKeySequence

_FILE = Path.home() / ".mystrow_shortcuts.json"

# (id, touche par défaut, clé i18n du libellé, clé i18n du groupe)
ACTIONS = [
    ("play_pause",     "Space",             "sc_play",       "mwy_052"),
    ("play_pause_alt", "Return",            "sc_play_alt",       "mwy_052"),
    ("next_media",     "PgDown",            "mwy_056",           "mwy_052"),
    ("prev_media",     "PgUp",              "mwy_058",           "mwy_052"),
    ("next_page",      "Ctrl+PgDown",       "sc_next_page",      "mwy_052"),
    ("prev_page",      "Ctrl+PgUp",         "sc_prev_page",      "mwy_052"),
    ("go_next",        "Right",             "sc_go_next",        "mwy_052"),
    ("go_prev",        "Left",              "sc_go_prev",        "mwy_052"),
    ("cart_1",         "F1",                "mwy_060",           "mwy_052"),
    ("cart_2",         "F2",                "mwy_062",           "mwy_052"),
    ("cart_3",         "F3",                "mwy_064",           "mwy_052"),
    ("cart_4",         "F4",                "mwy_066",           "mwy_052"),
    ("new_show",       "Ctrl+N",            "mwy_069",           "mwy_067"),
    ("open_show",      "Ctrl+O",            "mwy_071",           "mwy_067"),
    ("save_show",      "Ctrl+S",            "mwy_073",           "mwy_067"),
    ("save_show_as",   "Ctrl+Shift+S",      "mwy_075",           "mwy_067"),
    ("undo_plan",      "Ctrl+Z",            "sc_undo_plan",      "mwy_067"),
    ("color_white",    "W",                 "mwy_078",           "mwy_076"),
    ("color_red",      "R",                 "mwy_080",           "mwy_076"),
    ("color_orange",   "O",                 "mwy_082",           "mwy_076"),
    ("color_yellow",   "Y",                 "mwy_084",           "mwy_076"),
    ("color_green",    "G",                 "mwy_086",           "mwy_076"),
    ("color_cyan",     "C",                 "mwy_088",           "mwy_076"),
    ("color_blue",     "B",                 "mwy_090",           "mwy_076"),
    ("color_magenta",  "M",                 "mwy_092",           "mwy_076"),
    ("color_pink",     "P",                 "mwy_094",           "mwy_076"),
    ("color_black",    "K",                 "mwy_096",           "mwy_076"),
    ("strobe",         "S",                 "mwy_098",           "mwy_076"),
    ("flash",          "F",                 "sc_flash",          "mwy_076"),
] + [
    (f"fx_{i + 1}", f"F{i + 5}", f"mwy_{101 + 2 * i:03d}", "mwy_099") for i in range(8)
]

DEFAULTS = {a[0]: a[1] for a in ACTIONS}

# Touches gérées ailleurs (plan de feu, éditeur timeline) : signalées en
# conflit pour ne pas créer de double emploi silencieux.
RESERVED = ("Ctrl+A", "Ctrl+Y", "Esc", "Del")


def normalize(seq) -> str:
    """Séquence (str ou QKeySequence) → texte portable canonique ('' si vide)."""
    if not isinstance(seq, QKeySequence):
        seq = QKeySequence(seq or "", QKeySequence.PortableText)
    return seq.toString(QKeySequence.PortableText)


def _read() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge(overrides: dict) -> dict:
    keys = dict(DEFAULTS)
    for aid, seq in (overrides or {}).items():
        if aid in keys and isinstance(seq, str):
            keys[aid] = normalize(seq)
    return keys


def _diff(keys: dict) -> dict:
    return {aid: normalize(seq) for aid, seq in keys.items()
            if aid in DEFAULTS and normalize(seq) != normalize(DEFAULTS[aid])}


def load() -> dict:
    """Carte complète {id: séquence} : défauts + réglages de l'utilisateur."""
    return _merge(_read().get("keys"))


def save(keys: dict) -> None:
    data = _read()
    data["keys"] = _diff(keys)
    _write(data)


def conflicts(keys: dict) -> dict:
    """{id: id_ou_touche_en_conflit} pour chaque action dont la touche est déjà prise."""
    owner, out = {}, {}
    reserved = {normalize(r) for r in RESERVED}
    for aid, _d, _l, _g in ACTIONS:
        seq = normalize(keys.get(aid, ""))
        if not seq:
            continue
        if seq in reserved:
            out[aid] = seq
        elif seq in owner:
            out[aid] = owner[seq]
            out.setdefault(owner[seq], aid)
        else:
            owner[seq] = aid
    return out


def presets() -> dict:
    p = _read().get("presets")
    return p if isinstance(p, dict) else {}


def preset_keys(name: str) -> dict:
    return _merge(presets().get(name))


def save_preset(name: str, keys: dict) -> None:
    data = _read()
    data.setdefault("presets", {})[name] = _diff(keys)
    _write(data)


def delete_preset(name: str) -> None:
    data = _read()
    if name in data.get("presets", {}):
        del data["presets"][name]
        _write(data)
