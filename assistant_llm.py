"""
assistant_llm.py — Compréhension par un petit modèle local (option, bêta).

Un modèle Qwen3-0.6B entraîné sur les commandes MyStrow (~400 Mo, GGUF) lit la
phrase et rend des commandes JSON, que l'on traduit ici dans le format
d'assistant_nlu (mêmes actions, même exécution par assistant_panel).

Optionnel : sans llama_cpp ou sans le fichier du modèle, `available()` le dit
et l'assistant reste sur ses règles (assistant_nlu).
"""

import atexit
import json
import re
import threading
from pathlib import Path

import assistant_nlu as nlu

MODEL_DIR = Path.home() / ".mystrow_llm"
MODEL_FILE = "mystrow-assistant-q4_k_m.gguf"
SYSTEM = "MyStrow : traduis la demande en commandes JSON."

_COLORS = ["red", "blue", "green", "yellow", "white", "warm", "cold", "orange", "purple", "pink", "cyan", "magenta", "amber"]
_WHO = ["all", "front", "side", "back", "top", "moving_heads", "pars", "bars", "strobes", "lasers", "numbers", "odd", "even",
        "sparks", "smoke"]
_WINDOWS = ["patch", "effects", "3d", "rec", "output", "tester", "monitor", "tablet", "ia", "controller",
            "shortcuts", "obs", "vmix", "gamepad", "tutorials"]
# Même schéma qu'à l'entraînement : le modèle ne peut rien écrire d'autre.
SCHEMA = {
    "type": "object",
    "properties": {"actions": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
        "type": "object",
        "properties": {
            "do": {"enum": ["light", "fader", "blackout", "effect", "stop_effects", "speed", "memory", "playback", "open",
                            "connect_dmx", "create_fixture", "help", "status", "question", "diagnose",
                            "patch_add", "rec_generate", "chat", "gradient", "gobo", "live"]},
            "who": {"enum": _WHO},
            "numbers": {"type": "array", "items": {"type": "integer"}},
            "except_numbers": {"type": "array", "items": {"type": "integer"}},
            "except_who": {"enum": ["none", "front", "side", "back", "top", "moving_heads"]},
            "colors": {"type": "array", "items": {"enum": _COLORS}},
            "level": {"type": "integer"},
            "change": {"enum": ["none", "up", "down"]},
            "faders": {"type": "array", "items": {"type": "integer"}},
            "style": {"enum": ["any", "fast", "slow"]},
            "effect_kind": {"enum": ["any", "strobe", "chase", "rainbow", "pulse", "wave", "flash", "fire", "movement"]},
            "value": {"type": "integer"},
            "memory": {"type": "string"},
            "query": {"type": "string"},           # patch_add : marque / modèle recherchés
            "playback": {"enum": ["none", "play_pause", "next", "previous", "go", "go_back"]},
            "window": {"enum": _WINDOWS},
            "topic": {"enum": ["tablet", "controller", "dmx", "live", "other"]},
            "fade_seconds": {"type": "number"},
            "switch": {"enum": ["on", "off"]},            # live
            "gobo": {"enum": ["next", "open"]},
        },
        "required": ["do"],
    }}},
    "required": ["actions"],
}

# Cible du modèle → cible d'assistant_nlu (groupes A/B/C, familles d'appareils).
_TARGET = {"all": {"all": True}, "front": {"group": "A"}, "side": {"group": "B"}, "back": {"group": "C"},
           "top": {"kind": "douche"}, "moving_heads": {"kind": "lyre"}, "pars": {"kind": "par"},
           "bars": {"kind": "barre"}, "strobes": {"kind": "strobe"}, "lasers": {"kind": "laser"},
           "sparks": {"kind": "etincelle"}, "smoke": {"kind": "fumee"}}

_llm = None
_grammar = None
_lock = threading.Lock()


def model_path() -> Path:
    return MODEL_DIR / MODEL_FILE


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("llama_cpp") is not None and model_path().exists()


def _load():
    global _llm, _grammar
    if _llm is None:
        from llama_cpp import Llama, LlamaGrammar
        _llm = Llama(model_path=str(model_path()), n_ctx=512, n_threads=4, verbose=False)
        _grammar = LlamaGrammar.from_json_schema(json.dumps(SCHEMA), verbose=False)
        # Libéré avant l'arrêt de Python : sinon Llama.__del__ tourne quand llama_cpp
        # est déjà démonté et lève « 'NoneType' object is not callable ».
        atexit.register(unload)
    return _llm


def unload():
    """Libère le modèle (fichier ouvert en mémoire) : nécessaire avant de le
    remplacer par une mise à jour, Windows refusant d'écraser un fichier ouvert."""
    global _llm
    with _lock:
        if _llm is not None:
            try:
                _llm.close()
            except Exception:
                pass
            _llm = None


def ask(text: str) -> list:
    """Actions brutes du modèle (format SCHEMA). Appel bloquant (~0,5-1 s) : hors du thread Qt."""
    with _lock:
        llm = _load()
        prompt = (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n"
                  f"<|im_start|>assistant\n")
        out = llm.create_completion(prompt, grammar=_grammar, temperature=0, max_tokens=160, stop=["<|im_end|>"])
    return json.loads(out["choices"][0]["text"])["actions"]


def _target(a) -> dict:
    who = a.get("who") or "all"
    if who == "numbers" and a.get("numbers"):
        tgt = {"nums": [n for n in a["numbers"] if n >= 1]}
    elif who in ("odd", "even"):
        tgt = {"all": True, "parity": who}
    else:
        tgt = dict(_TARGET.get(who, {"all": True}))
    if a.get("except_numbers"):
        tgt["except"] = {"nums": a["except_numbers"]}
    elif a.get("except_who") not in (None, "none"):
        tgt["except"] = dict(_TARGET[a["except_who"]])
    return tgt


# Types d'appareil sans marque ni modèle : une recherche réduite à ça ne vaut pas la marque dite.
_GENERIC_GEAR = set("""moving head heads lyre lyres par pars wash beam spot barre barres led bar bars laser lasers
strobe strobes projecteur projecteurs fixture light lights""".split())


def to_nlu(actions: list, text: str, effects) -> list:
    """Actions du modèle → actions d'assistant_nlu (exécutées par assistant_panel)."""
    out = []
    t = nlu.normalize(text)
    for a in actions:
        do = a.get("do")
        fade = a.get("fade_seconds") or None
        act = None
        if do == "light":
            tgt, colors = _target(a), [c for c in a.get("colors") or [] if c in nlu.COLOR_HEX]
            level = a.get("level")
            if len(colors) >= 2:
                act = {"do": "pattern", "target": tgt, "level": level,
                       "slots": [{"hex": nlu.COLOR_HEX[c], "color": c} for c in colors]}
            elif colors:
                act = {"do": "color", "hex": nlu.COLOR_HEX[colors[0]], "color": colors[0], "target": tgt,
                       "level": 100 if level is None else level}
            elif level is None and a.get("change") in ("up", "down"):
                act = {"do": "level_rel", "target": tgt, "delta": 20 if a["change"] == "up" else -20}
            else:           # « baisse tout à 30 » : le niveau dit l'emporte sur « baisse »
                act = {"do": "level", "target": tgt, "level": 100 if level is None else level}
        elif do == "fader":
            nums = [n for n in a.get("faders") or [] if 1 <= n <= 9] or list(range(1, 9))
            act = {"do": "fader", "faders": nums, "level": 100 if a.get("level") is None else a["level"]}
        elif do == "blackout":
            act = {"do": "blackout"}
        elif do == "effect":
            style = a.get("style") if a.get("style") in ("fast", "slow") else None
            kind = a.get("effect_kind") if a.get("effect_kind") not in (None, "any") else None
            # « strobe un sur deux » : l'alternance se lit dans la phrase, comme pour les règles.
            alt = bool(nlu._ONE_IN_N_RE.search(t) or nlu._W["alternate"].find(t) or nlu._V["parity"].find(t))
            lyre = a.get("who") == "moving_heads"
            name = nlu._pick_effect(effects, t, style, kind, None, lyre, alt) if effects else None
            act = {"do": "effect", "name": name} if name else {"do": "no_effect"}
            if name and style:
                act["speed"] = 85 if style == "fast" else 25
        elif do == "stop_effects":
            act = {"do": "stop_effects"}
        elif do == "speed":
            if a.get("change") in ("up", "down"):
                act = {"do": "speed_rel", "delta": 20 if a["change"] == "up" else -20}
            else:
                act = {"do": "speed", "value": max(0, min(100, int(a.get("value") or 50)))}
        elif do == "memory":
            parts = str(a.get("memory", "")).replace(",", ".").replace(" ", ".").split(".")
            if len(parts) == 2 and all(p.isdigit() and 1 <= int(p) <= 8 for p in parts):
                act = {"do": "memory", "id": f"{int(parts[0])}.{int(parts[1])}"}
        elif do == "playback" and a.get("playback") not in (None, "none"):
            act = {"do": "playback", "what": {"previous": "prev"}.get(a["playback"], a["playback"])}
        elif do == "open" and a.get("window"):
            act = {"do": "open", "window": {"controller": "akai"}.get(a["window"], a["window"])}
        elif do == "connect_dmx":
            act = {"do": "connect"}
        elif do == "create_fixture":
            act = {"do": "fixture"}
        elif do == "patch_add":
            act = {"do": "patch_add", "query": nlu.normalize(a.get("query") or ""),
                   "qty": max(1, min(20, int(a.get("value") or 1)))}
            # « ma lyre sheilds » → le modèle répond « moving head » : la marque dite l'emporte.
            ruled = nlu._patch_add(nlu.normalize(t), nlu._Votes())
            if ruled and ruled["query"] and set(act["query"].split()) <= _GENERIC_GEAR                     and not set(ruled["query"].split()) <= _GENERIC_GEAR:
                act["query"] = ruled["query"]
        elif do == "rec_generate" and nlu._PROG_RE.search(t):
            # Garde-fou : « chanson d'après » parle d'une chanson sans rien programmer.
            colors = [c for c in a.get("colors") or [] if c in nlu.COLOR_HEX]
            if len(colors) >= 2 or nlu._RAINBOW_RE.search(t) or a.get("effect_kind") == "rainbow":
                color = "rainbow"
            else:
                color = colors[0] if colors else None
            act = {"do": "rec_generate", "color": color}
        elif do == "chat":
            act = {"do": "chat"}
        elif do == "gradient":
            colors = [c for c in a.get("colors") or [] if c in nlu.COLOR_HEX]
            if len(colors) < 2 or nlu._RAINBOW_RE.search(t):
                colors = colors[:1] + [c for c in nlu.RAINBOW_COLORS if c not in colors[:1]]
            act = {"do": "gradient", "colors": colors, "target": _target(a), "level": a.get("level")}
        elif do == "gobo":
            act = {"do": "gobo", "open": a.get("gobo") == "open", "target": _target(a)}
        elif do == "live" and nlu._LIVE_RE.search(t):
            # Garde-fou : « morceau suivant » parle de musique sans demander le mode LIVE.
            act = {"do": "live", "on": a.get("switch") != "off"}
        elif do == "diagnose" and (nlu._W["trouble"].find(t) or nlu._HOW_RE.match(t)):
            # Garde-fou : « … tu me suis ? » n'est pas une panne.
            act = {"do": "diagnose"}
        elif do in ("help", "status"):
            act = {"do": do}
        elif do == "question":
            topic = a.get("topic") or "other"
            act = {"do": "answer", "topic": "generic" if topic == "other" else topic, "text": text}
            if topic == "tablet":
                out.append(act)
                act = {"do": "open", "window": "tablet"}
            elif topic == "live":           # « … au son de ma carte son ? » : réponse, puis « je l'active ? »
                out.append(act)
                act = {"do": "live", "on": True}
        if act is None:
            continue
        if fade and act["do"] in ("color", "level", "level_rel", "pattern", "fader"):
            act["fade"] = float(fade)
        out.append(act)
    if _dim_mood(t) or nlu.warm_mood(t):
        # « ambiance tamisée » : le modèle sortait un magenta à 60 % → la règle dédiée l'emporte.
        return nlu.parse(text, effects).actions
    # « baisse un peu, c'est trop fort » : « fort » ajoutait un niveau à 100 % après la baisse.
    rel = [a["target"] for a in out if a.get("do") == "level_rel"]
    if rel and not re.search(r"\d", t):
        out = [a for a in out if not (a.get("do") == "level" and a.get("level") == 100 and a.get("target") in rel)]
    said = {k for k, _ in nlu._V["color"].find_all(t)}
    for act in out:
        # « ambiance froide » : le modèle répond bleu franc, la phrase dit blanc froid.
        if act.get("do") == "color" and act.get("color") == "blue" and "cold" in said and "blue" not in said:
            act.update(color="cold", hex=nlu.COLOR_HEX["cold"])
    return out or [{"do": "unknown", "text": text}]


def _dim_mood(t):
    return bool(nlu._DIM_RE.search(t)) and not nlu._V["theme"].find(t)
