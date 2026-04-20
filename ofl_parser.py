"""
Parseur Open Fixture Library (OFL) pour MyStrow.

Formate les fixtures JSON du projet open-fixture-library en profils MyStrow.
API : parse_ofl_json(data, manufacturer_key, fixture_key, manufacturer_name) -> dict

Format OFL source :
  https://github.com/OpenLightingProject/open-fixture-library
"""

import json

# ---------------------------------------------------------------------------
# Mapping type de capability OFL -> type canal MyStrow
# ---------------------------------------------------------------------------

# Types simples (pas de propriété supplémentaire requise)
_SIMPLE_MAP = {
    "Intensity":        "Dim",
    "Pan":              "Pan",
    "PanContinuous":    "Pan",
    "Tilt":             "Tilt",
    "TiltContinuous":   "Tilt",
    "Zoom":             "Zoom",
    "Focus":            "Focus",
    "Iris":             "Iris",
    "Prism":            "Prism",
    "PrismRotation":    "PrismRot",
    "WheelRotation":    "Gobo1Rot",
    "WheelSlotRotation": "Gobo1Rot",
    "ShutterStrobe":    "Strobe",
    "StrobeSpeed":      "Strobe",
    "StrobeDuration":   "Strobe",
    "Speed":            "Speed",
    "EffectSpeed":      "Speed",
    "EffectDuration":   "Speed",
    "Rotation":         "Mode",
    "BeamAngle":        "Zoom",
    "BeamPosition":     "Mode",
    "Effect":           "Mode",
    "EffectParameter":  "Mode",
    "Fog":              "Mode",
    "FogOutput":        "Mode",
    "FogType":          "Mode",
    "Maintenance":      "Mode",
    "NoFunction":       "Mode",
    "Generic":          "Mode",
}

# ColorIntensity : dépend de la propriété "color"
_COLOR_MAP = {
    "Red":         "R",
    "Green":       "G",
    "Blue":        "B",
    "White":       "W",
    "WarmWhite":   "W",
    "ColdWhite":   "W",
    "Warm White":  "W",
    "Cold White":  "W",
    "Amber":       "Ambre",
    "UV":          "UV",
    "Cyan":        "Mode",
    "Magenta":     "Mode",
    "Yellow":      "Mode",
    "Lime":        "Mode",
    "Indigo":      "Mode",
}


def _get_channel_type(channel_name: str, channel_data: dict) -> str:
    """
    Déduit le type MyStrow pour un canal OFL.
    Utilise capability (singulier) ou le premier item de capabilities.
    """
    # capability singulier (un seul comportement)
    cap = channel_data.get("capability")
    if cap is None:
        caps = channel_data.get("capabilities", [])
        cap = caps[0] if caps else None

    if cap is None:
        return "Mode"

    cap_type = cap.get("type", "")

    if cap_type == "ColorIntensity":
        color = cap.get("color", "")
        return _COLOR_MAP.get(color, "Mode")

    if cap_type == "WheelSlot":
        # Roue couleur ou gobo selon le nom du canal
        name_lower = channel_name.lower()
        if "color" in name_lower or "colour" in name_lower or "cto" in name_lower:
            return "ColorWheel"
        # Par défaut gobo (Gobo1 / Gobo2 décidé plus haut selon l'index)
        return "Gobo"  # placeholder; résolu dans _map_channels

    return _SIMPLE_MAP.get(cap_type, "Mode")


def _map_channels(available: dict, mode_channels: list) -> list:
    """
    Construit le profil de canaux MyStrow pour un mode OFL.

    Gère :
    - Fine channels (fineChannelAliases sur le canal parent)
    - Gobo1 / Gobo2 selon l'ordre d'apparition
    - Canaux null (trou DMX) → "Mode"
    - Références matricielles (dict) → ignorées
    """
    # Pré-calcul : mapping fine_alias_name -> (parent_name, parent_mystrow)
    fine_aliases: dict[str, str] = {}  # alias_name -> parent_channel_name
    for ch_name, ch_data in available.items():
        for alias in ch_data.get("fineChannelAliases", []):
            fine_aliases[alias] = ch_name

    gobo_count = 0
    profile = []

    for ref in mode_channels:
        if ref is None:
            profile.append("Mode")
            continue
        if isinstance(ref, dict):
            # matrixChannels ou autre construction complexe → ignorer
            continue
        ch_name = str(ref)

        # Est-ce un alias fin ?
        if ch_name in fine_aliases:
            parent = fine_aliases[ch_name]
            parent_type = _get_channel_type(parent, available.get(parent, {}))
            if parent_type in ("Pan", "Tilt"):
                profile.append(parent_type + "Fine")
            else:
                profile.append("Mode")
            continue

        ch_data = available.get(ch_name, {})
        mtype = _get_channel_type(ch_name, ch_data)

        if mtype == "Gobo":
            gobo_count += 1
            profile.append("Gobo1" if gobo_count <= 1 else "Gobo2")
        else:
            profile.append(mtype)

    return profile


def _detect_fixture_type(profile: list) -> str:
    """Déduit le type de fixture depuis son profil."""
    if "Pan" in profile or "Tilt" in profile:
        return "Moving Head"
    return "PAR LED"


# ---------------------------------------------------------------------------
# Extraction des roues de couleur / gobos OFL
# ---------------------------------------------------------------------------

# Couleur de fallback pour les types de slot non-colorés
_SLOT_TYPE_COLORS = {
    "Open":   "#ffffff",
    "Closed": "#000000",
    "Gobo":   "#888888",
    "Iris":   "#888888",
    "Frost":  "#ccccff",
    "Prism":  "#aaddff",
    "Effect": "#ffcc44",
}


def _hex_blend(colors: list) -> str:
    """Mélange plusieurs couleurs hex en une moyenne RGB."""
    if not colors:
        return "#888888"
    rs, gs, bs = [], [], []
    for c in colors:
        c = c.lstrip("#")
        if len(c) == 6:
            rs.append(int(c[0:2], 16))
            gs.append(int(c[2:4], 16))
            bs.append(int(c[4:6], 16))
    if not rs:
        return "#888888"
    r = sum(rs) // len(rs)
    g = sum(gs) // len(gs)
    b = sum(bs) // len(bs)
    return f"#{r:02x}{g:02x}{b:02x}"


def _extract_wheel_slots(obj: dict, available: dict) -> dict:
    """
    Extrait les slots de toutes les roues (couleur + gobo) d'une fixture OFL.

    Retourne un dict:
      {
        "color_wheel_slots": [{"name": str, "color": "#rrggbb", "dmx": int}, ...],
        "gobo_wheel_slots":  [{"name": str, "color": "#rrggbb", "dmx": int}, ...],
      }

    Chaque entrée utilise le milieu du dmxRange comme valeur DMX de référence.
    Les transitions (rotation) sont ignorées.
    """
    wheels_raw = obj.get("wheels", {})

    # Identifier les noms de canaux ColorWheel et Gobo dans availableChannels
    color_wheel_channels = {}   # channel_name -> wheel_name
    gobo_wheel_channels  = {}   # channel_name -> wheel_name

    for ch_name, ch_data in available.items():
        caps = ch_data.get("capabilities") or []
        if isinstance(ch_data.get("capability"), dict):
            caps = [ch_data["capability"]]
        for cap in caps:
            if cap.get("type") == "WheelSlot":
                wheel_name = cap.get("wheel", "")
                ch_lower = ch_name.lower()
                if "color" in ch_lower or "colour" in ch_lower:
                    color_wheel_channels[ch_name] = wheel_name
                elif "gobo" in ch_lower:
                    gobo_wheel_channels[ch_name] = wheel_name
                break  # on a ce qu'on veut pour ce canal

    def _build_slots(ch_map: dict) -> list:
        """Construit la liste de slots à partir du mapping canal->roue."""
        # Chercher le premier canal avec des capabilities WheelSlot
        for ch_name, default_wheel in ch_map.items():
            ch_data = available.get(ch_name, {})
            caps = ch_data.get("capabilities") or []
            if isinstance(ch_data.get("capability"), dict):
                caps = [ch_data["capability"]]

            slots_out = []
            for cap in caps:
                if cap.get("type") != "WheelSlot":
                    continue
                dmx_range = cap.get("dmxRange", [0, 255])
                slot_num  = cap.get("slotNumber", 1)
                wheel_name = cap.get("wheel", default_wheel)

                # Ignorer les transitions (slot_num non entier)
                if isinstance(slot_num, float) and slot_num != int(slot_num):
                    continue
                slot_idx = int(slot_num) - 1  # 0-based

                wheel_obj = wheels_raw.get(wheel_name, {})
                wslots = wheel_obj.get("slots", [])
                if 0 <= slot_idx < len(wslots):
                    wslot = wslots[slot_idx]
                    stype  = wslot.get("type", "")
                    sname  = wslot.get("name") or stype
                    colors = wslot.get("colors", [])
                    color  = _hex_blend(colors) if colors else _SLOT_TYPE_COLORS.get(stype, "#888888")
                else:
                    sname = f"Slot {slot_num}"
                    color = "#888888"

                dmx_center = (dmx_range[0] + dmx_range[1]) // 2
                slots_out.append({"name": sname, "color": color, "dmx": dmx_center})

            if slots_out:
                return slots_out
        return []

    return {
        "color_wheel_slots": _build_slots(color_wheel_channels),
        "gobo_wheel_slots":  _build_slots(gobo_wheel_channels),
    }


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def parse_ofl_json(
    data: bytes,
    manufacturer_key: str = "",
    fixture_key: str = "",
    manufacturer_name: str = "",
) -> dict:
    """
    Parse un fichier fixture OFL (bytes JSON) et retourne un dict MyStrow.

    Args:
        data:             Contenu brut du fichier JSON OFL
        manufacturer_key: Clé fabricant dans l'URL OFL (ex: "robe")
        fixture_key:      Clé fixture dans l'URL OFL (ex: "robin-600e-spot")
        manufacturer_name: Nom lisible du fabricant (ex: "Robe")

    Retourne:
        {
          "name": str,
          "manufacturer": str,
          "fixture_type": str,
          "source": "ofl",
          "uuid": str,
          "modes": [{"name": str, "channelCount": int, "profile": [str]}],
          "color_wheel_slots": [{"name": str, "color": "#rrggbb", "dmx": int}, ...],
          "gobo_wheel_slots":  [{"name": str, "color": "#rrggbb", "dmx": int}, ...],
        }
    """
    try:
        obj = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"JSON OFL invalide : {e}")

    name         = obj.get("name", fixture_key)
    # OFL n'a pas de clé manufacturer dans le JSON, on utilise le paramètre
    manufacturer = manufacturer_name or manufacturer_key

    available = obj.get("availableChannels", {})
    raw_modes  = obj.get("modes", [])

    modes = []
    for m in raw_modes:
        mode_name     = m.get("name") or m.get("shortName", f"Mode {len(modes)+1}")
        mode_channels = m.get("channels", [])
        profile       = _map_channels(available, mode_channels)
        modes.append({
            "name":         mode_name,
            "channelCount": len(profile),
            "profile":      profile,
        })

    if not modes:
        modes = [{"name": "Mode 1", "channelCount": 0, "profile": []}]

    first_profile = modes[0]["profile"] if modes else []
    ftype = _detect_fixture_type(first_profile)

    wheel_slots = _extract_wheel_slots(obj, available)

    result = {
        "name":         name,
        "manufacturer": manufacturer,
        "fixture_type": ftype,
        "source":       "ofl",
        "uuid":         f"ofl:{manufacturer_key}/{fixture_key}" if manufacturer_key else "",
        "modes":        modes,
    }
    if wheel_slots["color_wheel_slots"]:
        result["color_wheel_slots"] = wheel_slots["color_wheel_slots"]
    if wheel_slots["gobo_wheel_slots"]:
        result["gobo_wheel_slots"] = wheel_slots["gobo_wheel_slots"]

    return result
