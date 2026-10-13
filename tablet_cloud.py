"""Config du PC → compte MyStrow → app tablette (mode sans PC).

La tablette ne sait pas lire les fichiers du PC : on lui envoie une version
DÉJÀ INTERPRÉTÉE de la config (règle anti-divergence de l'app : toute
interprétation reste sur le PC, la tablette ne fait que le rendu).

Ce qui part :
  - le patch (`~/.maestro_dmx_patch.json`, univers 0 seulement : la tablette
    n'a qu'une sortie) ;
  - les pages AKAI, mémoires, pads FX, positions (`~/.maestro_akai_config.json`) ;
  - les effets de l'éditeur (`~/.mystrow_custom_effects.json`), ceux de la
    bibliothèque modifiés (`~/.mystrow_effect_library.json`) et ceux des 8
    boutons de droite (`~/.mystrow_effect_assignments.json`).
La playlist (.tui) ne part PAS : la tablette sans PC n'a pas de lecteur.

Stockage : Firestore `user_configs/{uid}`, un seul document, le tout en JSON
dans le champ `payload` (lu par mobile/src/account.js). Règle : chacun ne lit
et n'écrit que le sien (firestore.rules).
"""

import json
import time
import urllib.error
from pathlib import Path

# Même table que main_window.AKAI_GROUP_MAP (lettre AKAI → nom interne du
# groupe) : la tablette ne connaît que les lettres A-H.
_GROUP_LETTER = {
    "face": "A", "lat": "B", "contre": "C", "douche1": "D",
    "douche2": "E", "douche3": "F", "groupe_g": "G", "groupe_h": "H",
}
_LETTERS = "ABCDEFGH"

# Champs du patch PC que le moteur de la tablette lit tels quels (engine.js,
# port de _update_from_projectors_locked).
_FIXTURE_KEYS = (
    "fixture_type", "manufacturer", "color_wheel_slots", "gobo_wheel_slots",
    "channel_defaults", "shutter_inverted", "shutter_strobe_min",
    "shutter_strobe_max", "ring_follow", "preset_slots",
    "pan_min", "pan_max", "tilt_min", "tilt_max", "pan_invert", "tilt_invert",
    "pan_tilt_swap", "pan_range", "tilt_range",
)

_POS_COL_MAX = 5
_MEM_COL_MAX = 99
_FX_COL_MAX = 8
_PAYLOAD_MAX = 900_000   # un document Firestore plafonne à 1 Mio

_HOME = Path.home()
PATCH_FILE = _HOME / ".maestro_dmx_patch.json"
AKAI_FILE = _HOME / ".maestro_akai_config.json"
CUSTOM_FX_FILE = _HOME / ".mystrow_custom_effects.json"
LIBRARY_FX_FILE = _HOME / ".mystrow_effect_library.json"
ASSIGN_FX_FILE = _HOME / ".mystrow_effect_assignments.json"


def _letter(group) -> str:
    if group in _GROUP_LETTER:
        return _GROUP_LETTER[group]
    g = str(group or "").strip().upper()
    return g if len(g) == 1 and g in _LETTERS else "A"


def _is_lyre(fx: dict) -> bool:
    return fx.get("fixture_type") in ("Moving Head", "Lyre") or "Pan" in (fx.get("profile") or [])


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[TABLETTE] lecture impossible {path.name} : {e}")
    return default


# ── Conversion ────────────────────────────────────────────────────────────────

def convert(patch: dict, akai: dict, custom_fx: list, library_fx: dict, assign_fx: dict) -> dict:
    """Config PC → config de la tablette (format lu par mobile/src/account.js).

    Fonction pure (pas de fichier, pas de réseau) : c'est elle qu'on teste.
    """
    pc_fixtures = list((patch or {}).get("fixtures") or [])
    akai = akai or {}
    warnings = []

    # Patch. `pc_to_tab` : rang PC → rang tablette (les fixtures hors univers 0
    # sautent, les mémoires et positions doivent suivre).
    fixtures, pc_to_tab = [], {}
    for i, f in enumerate(pc_fixtures):
        if int(f.get("universe", 0) or 0) != 0:
            warnings.append(f"{f.get('name', '?')} : univers {f.get('universe')} (la tablette ne sort que l'univers 1)")
            continue
        profile = f.get("profile")
        if not isinstance(profile, list) or not profile:
            warnings.append(f"{f.get('name', '?')} : profil illisible")
            continue
        t = {"name": f.get("name", f"Projecteur {i + 1}"), "group": _letter(f.get("group")),
             "address": int(f.get("start_address", 1) or 1), "profile": list(profile),
             "model": f.get("name", ""), "from_pc": True}
        for k in _FIXTURE_KEYS:
            if k in f and f[k] is not None:
                t[k] = f[k]
        if t.get("fixture_type") is None and "Pan" in profile:
            t["fixture_type"] = "Moving Head"
        pc_to_tab[i] = len(fixtures)
        fixtures.append(t)

    # (groupe interne, rang dans le groupe) → rang tablette : convention des
    # cibles « Sélection » des effets (même repère que le plan de feu).
    by_group_rank, seen = {}, {}
    for i, f in enumerate(pc_fixtures):
        g = f.get("group")
        r = seen.get(g, 0)
        seen[g] = r + 1
        if i in pc_to_tab:
            by_group_rank[(g, r)] = pc_to_tab[i]

    def conv_layer(ld: dict) -> dict:
        ld = dict(ld)
        ld["target_groups"] = [_letter(g) for g in (ld.get("target_groups") or [])]
        if ld.get("group_amp"):
            ld["group_amp"] = {_letter(g): v for g, v in ld["group_amp"].items()}
        if ld.get("target_preset") == "Selection":
            ld["target_idx"] = [by_group_rank[(g, int(r))] for g, r in (ld.get("target_selection") or [])
                                if (g, int(r)) in by_group_rank]
        ld.pop("target_selection", None)
        return ld

    def conv_effect(cfg: dict, name: str = None):
        if not isinstance(cfg, dict) or not cfg.get("layers"):
            return None
        return {"name": name or cfg.get("name") or "Effet", "category": "Mes effets", "custom": True,
                "from_pc": True, "no_color": bool(cfg.get("no_color")),
                "layers": [conv_layer(ld) for ld in cfg["layers"] if isinstance(ld, dict)]}

    # Effets : bibliothèque modifiée < effets perso < boutons < pads FX (le
    # dernier mot à ce qui est réellement posé sous les doigts).
    effects = {}

    def add_effect(cfg, name=None):
        e = conv_effect(cfg, name)
        if e:
            effects[e["name"]] = e
            return e["name"]
        return None

    for name, cfg in (library_fx or {}).items():
        add_effect(cfg, name)
    for cfg in (custom_fx or []):
        add_effect(cfg)
    buttons = [None] * 8
    for k, cfg in (assign_fx or {}).items():
        try:
            row = int(k)
        except (TypeError, ValueError):
            continue
        if 0 <= row < 8:
            buttons[row] = add_effect(cfg) or (cfg.get("name") if isinstance(cfg, dict) else None)
    fx_pads = {}
    for f, col in enumerate((akai.get("fx_pads") or [])[:_FX_COL_MAX]):
        names = [add_effect(cfg) if cfg else None for cfg in (col or [])[:8]]
        if any(names):
            fx_pads[str(f)] = names + [None] * (8 - len(names))

    # Mémoires : premier cue (la tablette ne joue pas les enchaînements de cues).
    memories, multi_cues = {}, 0
    for m, col in enumerate((akai.get("memories") or [])[:_MEM_COL_MAX]):
        for row, mem in enumerate((col or [])[:8]):
            if not mem:
                continue
            cues = mem.get("cues")
            cue = cues[0] if cues else {"projectors": mem.get("projectors", []), "effect": mem.get("effect", {})}
            if cues and len(cues) > 1:
                multi_cues += 1
            states = cue.get("projectors") or []
            projs = []
            for i, _f in enumerate(pc_fixtures):
                if i not in pc_to_tab:
                    continue
                st = states[i] if i < len(states) and isinstance(states[i], dict) else {}
                lyre = _is_lyre(pc_fixtures[i])
                projs.append({"color": st.get("base_color", "#000000"), "level": int(st.get("level", 0) or 0),
                              "strobe": int(st.get("strobe_speed", 0) or 0),
                              "pan": st.get("pan") if lyre else None, "tilt": st.get("tilt") if lyre else None,
                              "gobo": int(st.get("gobo", 0) or 0)})
            eff = conv_effect(cue.get("effect") or mem.get("effect") or {})
            memories[f"{row}_{m}"] = {"v": 2, "projectors": projs,
                                      "effect": {"name": eff["name"], "layers": eff["layers"]} if eff else None,
                                      "qfx": {}, "label": mem.get("label") or ""}
    if multi_cues:
        warnings.append(f"{multi_cues} mémoire(s) à plusieurs cues : seul le cue 1 est repris")

    # Positions des lyres : appariement par adresse DMX, puis par nom.
    presets = akai.get("position_presets") or []
    lyres = [(pc_to_tab[i], f) for i, f in enumerate(pc_fixtures) if i in pc_to_tab and _is_lyre(f)]

    def conv_position(pr: dict) -> dict:
        snap = pr.get("projectors") or []
        pos = {}
        for tab_i, f in lyres:
            s = next((x for x in snap if str(x.get("start_address", "")) == str(f.get("start_address"))), None) \
                or next((x for x in snap if x.get("name") == f.get("name")), None)
            if s:
                pos[str(tab_i)] = [int(s.get("pan", 32768)), int(s.get("tilt", 32768))]
        return {"name": pr.get("name", "Position"), "pos": pos}

    pos_presets = {}
    for pc, col in enumerate((akai.get("position_pads") or [])[:_POS_COL_MAX]):
        out = [conv_position(presets[i]) if isinstance(i, int) and 0 <= i < len(presets) else None
               for i in (col or [])[:8]]
        if any(out):
            pos_presets[str(pc)] = out + [None] * (8 - len(out))

    # Pages : colonnes PLAY / VIDÉO / VFX sans équivalent → colonne vide.
    def conv_slot(s: dict) -> dict:
        t = (s or {}).get("type")
        if t == "group" and str(s.get("group", "")).upper() in _LETTERS:
            return {"type": "group", "group": str(s["group"]).upper()}
        if t == "memory" and 0 <= int(s.get("mem_col", -1)) < _MEM_COL_MAX:
            return {"type": "memory", "mem_col": int(s["mem_col"])}
        if t == "fx" and 0 <= int(s.get("fx_col", -1)) < _FX_COL_MAX:
            return {"type": "fx", "fx_col": int(s["fx_col"])}
        if t == "pos" and 0 <= int(s.get("pos_col", -1)) < _POS_COL_MAX:
            return {"type": "pos", "pos_col": int(s["pos_col"])}
        return {"type": "none"}

    pages = [[conv_slot(s) for s in (pg or [])[:8]] for pg in (akai.get("bank_pages") or [])]
    if not pages and akai.get("custom_bank_slots"):
        pages = [[conv_slot(s) for s in akai["custom_bank_slots"][:8]]]

    return {
        "v": 1,
        "fixtures": fixtures,
        "pages": pages,
        "pageIdx": int(akai.get("bank_page_idx", 0) or 0),
        "memories": memories,
        "fxPads": fx_pads,
        "buttons": buttons,
        "effects": list(effects.values()),
        "posPresets": pos_presets,
        "superpose": bool(akai.get("effect_superposition", False)),
        "warnings": warnings,
    }


def build_payload() -> dict:
    """Lit la config du PC sur le disque et la convertit."""
    custom = _read_json(CUSTOM_FX_FILE, [])
    if isinstance(custom, dict):          # ancien format éventuel {nom: cfg}
        custom = [dict(v, name=k) for k, v in custom.items() if isinstance(v, dict)]
    return convert(_read_json(PATCH_FILE, {}), _read_json(AKAI_FILE, {}),
                   custom, _read_json(LIBRARY_FX_FILE, {}), _read_json(ASSIGN_FX_FILE, {}))


def summary(payload: dict) -> dict:
    return {"fixtures": len(payload.get("fixtures", [])), "memories": len(payload.get("memories", {})),
            "effects": len(payload.get("effects", [])),
            "positions": sum(1 for col in payload.get("posPresets", {}).values() for p in col if p)}


# ── Envoi ─────────────────────────────────────────────────────────────────────

def upload(label: str = "") -> dict:
    """Envoie la config du PC dans le compte connecté. Retourne le résumé.

    Lève une Exception au message lisible (pas connecté, réseau, trop gros).
    """
    import firebase_client as fc
    import license_manager as lm

    account = lm._load_account(lm.get_machine_id())
    if not account or not account.get("uid"):
        raise Exception("Connectez-vous d'abord à votre compte MyStrow (menu À propos › Mon compte).")
    token = lm.get_current_id_token()
    if not token:
        raise Exception("Impossible de joindre le compte MyStrow (Internet ?). Réessayez.")

    payload = build_payload()
    payload["created_utc"] = time.time()
    payload["label"] = label
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > _PAYLOAD_MAX:
        raise Exception("Config trop grosse pour le compte (plus de 900 Ko).")
    resume = summary(payload)

    url = f"{fc._FS_BASE}/user_configs/{account['uid']}"
    body = {"fields": fc._dict_to_fields({
        "payload": text, "updated_utc": time.time(), "label": label, "summary": resume})}
    try:
        fc._patch_json(url, body, token)
    except urllib.error.HTTPError as e:
        raise Exception(f"Envoi refusé par le compte : {fc._firebase_error(e)}")
    except Exception as e:
        raise Exception(fc._net_error_msg(e) if hasattr(fc, "_net_error_msg") else str(e))
    resume["warnings"] = payload.get("warnings", [])
    return resume
