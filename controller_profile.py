"""
Gestion des profils de contrôleurs MIDI personnalisés.
Format JSON — stockés dans %APPDATA%/MyStrow/controllers/ (Windows) ou ~/.mystrow/controllers/.
"""
import json
import os
from pathlib import Path


def get_profiles_dir() -> Path:
    # Utilise AppData/Roaming sur Windows, ~/.mystrow ailleurs
    # Évite d'écrire dans le dossier d'installation (Program Files = accès refusé)
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = Path(appdata) / "MyStrow" / "controllers"
    else:
        d = Path.home() / ".mystrow" / "controllers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_profiles() -> list:
    """Retourne tous les profils utilisateur (dossier controllers/)."""
    result = []
    for f in sorted(get_profiles_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({"file": str(f), "data": data})
        except Exception:
            pass
    return result


def load_profile(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_profile(data: dict, path: str = None) -> str:
    if not path:
        safe = "".join(
            c if c.isalnum() or c == "_" else "_"
            for c in data.get("name", "custom").lower()
        ).strip("_")
        path = str(get_profiles_dir() / f"{safe}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def find_profile_for_port(port_name: str) -> dict | None:
    """Cherche un profil dont les keywords matchent le nom du port MIDI."""
    upper = port_name.upper()
    for entry in list_profiles():
        data = entry["data"]
        for kw in data.get("keywords", []):
            if kw.upper() in upper:
                return data
    return None


def build_reverse_maps(profile: dict) -> dict:
    """
    Construit des tables de lookup inversées pour dispatch O(1).
    Retourne un dict avec _rev_pad, _rev_mute, _rev_fader, _rev_effect, _rev_led.
    """
    rev_pad    = {}   # (channel, note) -> (row, col)
    rev_mute   = {}   # (channel, note) -> fader_idx
    rev_effect = {}   # (channel, note) -> effect_idx
    rev_fader  = {}   # (channel, cc)   -> fader_idx
    rev_led    = {}   # (row, col)       -> {'channel': c, 'note': n}

    for key, entry in profile.get("pad_map", {}).items():
        try:
            row, col = map(int, key.split(","))
            k = (entry.get("channel", 0), entry["note"])
            rev_pad[k]  = (row, col)
            rev_led[(row, col)] = {"channel": entry.get("channel", 0), "note": entry["note"]}
        except Exception:
            pass

    for idx_str, entry in profile.get("mute_map", {}).items():
        k = (entry.get("channel", 0), entry["note"])
        rev_mute[k] = int(idx_str)

    for idx_str, entry in profile.get("effect_map", {}).items():
        k = (entry.get("channel", 0), entry["note"])
        rev_effect[k] = int(idx_str)

    for idx_str, entry in profile.get("fader_map", {}).items():
        k = (entry.get("channel", 0), entry["cc"])
        rev_fader[k] = int(idx_str)

    # Remap velocities AKAI standard → velocités du contrôleur personnalisé
    _AKAI_TO_COLOR = {
        0: "Éteint", 3: "Rouge", 5: "Blanc", 9: "Orange", 13: "Jaune",
        21: "Vert", 25: "Vert", 37: "Cyan", 45: "Bleu", 49: "Magenta", 53: "Violet",
    }
    led_colors = profile.get("led_colors", {})
    vel_remap = {}
    for akai_vel, color_name in _AKAI_TO_COLOR.items():
        if color_name in led_colors:
            vel_remap[akai_vel] = led_colors[color_name]

    return {
        "rev_pad":    rev_pad,
        "rev_mute":   rev_mute,
        "rev_effect": rev_effect,
        "rev_fader":  rev_fader,
        "rev_led":    rev_led,
        "vel_remap":  vel_remap,
    }
