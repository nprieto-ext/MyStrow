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


_PIXEL_TOKEN = "$pixelKey"


def _matrix_pixel_keys(matrix: dict) -> tuple:
    """
    Liste ordonnée des pixel keys d'une matrice OFL + géométrie (cols, rows).

    Deux formes possibles côté OFL :
    - "pixelKeys": tableau 3D [z][y][x] de noms (trous = null)
    - "pixelCount": [x, y, z] → clés auto "1".."N" en 1D
    """
    if not isinstance(matrix, dict):
        return [], (0, 0)

    keys = matrix.get("pixelKeys")
    if isinstance(keys, list) and keys:
        out, rows, cols = [], 0, 0
        for z_layer in keys:
            if not isinstance(z_layer, list):
                continue
            for y_row in z_layer:
                if not isinstance(y_row, list):
                    continue
                rows += 1
                cols = max(cols, len(y_row))
                out.extend(k for k in y_row if k)
        return out, (cols, rows)

    pc = matrix.get("pixelCount")
    if isinstance(pc, list) and len(pc) == 3:
        try:
            x, y, z = (max(1, int(v)) for v in pc)
        except (TypeError, ValueError):
            return [], (0, 0)
        out = []
        for zz in range(1, z + 1):
            for yy in range(1, y + 1):
                for xx in range(1, x + 1):
                    # 1D → clés "1".."N" ; sinon coordonnées façon OFL
                    out.append(str(len(out) + 1) if (y == 1 and z == 1)
                               else f"({xx}, {yy}, {zz})")
        return out, (x, y * z)

    return [], (0, 0)


def _template_lookup(templates: dict) -> list:
    """
    Prépare la résolution des noms dérivés d'un templateChannel.

    Un mode peut référencer "Red Master" ou "Red 3" : ces canaux n'existent pas
    dans availableChannels, ils sont générés depuis le template "Red $pixelKey".
    On retourne des couples (prefixe, suffixe, nom_template, data) pour matcher
    n'importe quelle pixel key sans avoir à la deviner.
    """
    out = []
    for tpl_name, tpl_data in (templates or {}).items():
        if _PIXEL_TOKEN not in tpl_name:
            continue
        prefix, _, suffix = tpl_name.partition(_PIXEL_TOKEN)
        out.append((prefix, suffix, tpl_name, tpl_data))
    # Les préfixes longs d'abord : "Red Fine $pixelKey" avant "Red $pixelKey"
    out.sort(key=lambda t: len(t[0]) + len(t[1]), reverse=True)
    return out


def _resolve_template(ch_name: str, lookup: list):
    """Retrouve (nom_template, data) pour un canal dérivé, sinon (None, None)."""
    for prefix, suffix, tpl_name, tpl_data in lookup:
        if len(ch_name) <= len(prefix) + len(suffix):
            continue
        if ch_name.startswith(prefix) and ch_name.endswith(suffix):
            return tpl_name, tpl_data
    return None, None


def _map_channels(available: dict, mode_channels: list,
                  templates: dict = None, matrix: dict = None) -> tuple:
    """
    Construit le profil de canaux MyStrow pour un mode OFL.

    Gère :
    - Fine channels (fineChannelAliases sur le canal parent)
    - Gobo1 / Gobo2 selon l'ordre d'apparition
    - Canaux null (trou DMX) → "Mode"
    - Canaux dérivés d'un templateChannel ("Red Master" ← "Red $pixelKey")
    - Références matricielles (insert: matrixChannels) → développées en canaux
      pixel réels, et géométrie remontée en métadonnée

    Retourne (profile, matrix_meta) ; matrix_meta vaut None si le mode n'a
    aucun canal pixel.
    """
    templates = templates or {}
    tpl_lookup = _template_lookup(templates)
    pixel_keys, (mx_cols, mx_rows) = _matrix_pixel_keys(matrix or {})
    pixel_groups = list((matrix or {}).get("pixelGroups", {}).keys())

    # Pré-calcul : mapping fine_alias_name -> (parent_name, parent_mystrow)
    fine_aliases: dict[str, str] = {}  # alias_name -> parent_channel_name
    for ch_name, ch_data in available.items():
        for alias in ch_data.get("fineChannelAliases", []):
            fine_aliases[alias] = ch_name

    gobo_count = 0
    profile = []
    matrix_meta = None

    def _type_of(ch_name):
        """Type MyStrow d'un canal, qu'il soit direct ou dérivé d'un template."""
        if ch_name in fine_aliases:
            parent = fine_aliases[ch_name]
            parent_type = _get_channel_type(parent, available.get(parent, {}))
            return parent_type + "Fine" if parent_type in ("Pan", "Tilt") else "Mode"
        if ch_name in available:
            return _get_channel_type(ch_name, available[ch_name])
        # Pas dans availableChannels : canal généré depuis un templateChannel
        tpl_name, tpl_data = _resolve_template(ch_name, tpl_lookup)
        if tpl_data is not None:
            return _get_channel_type(tpl_name, tpl_data)
        return "Mode"

    def _emit(mtype):
        nonlocal gobo_count
        if mtype == "Gobo":
            gobo_count += 1
            profile.append("Gobo1" if gobo_count <= 1 else "Gobo2")
        else:
            profile.append(mtype)

    for ref in mode_channels:
        if ref is None:
            profile.append("Mode")
            continue

        if isinstance(ref, dict):
            if ref.get("insert") != "matrixChannels":
                continue  # construction inconnue → on saute
            tpl_names = ref.get("templateChannels") or []
            cell = [_get_channel_type(t, templates.get(t, {})) for t in tpl_names]

            repeat = ref.get("repeatFor")
            if isinstance(repeat, list):
                targets = list(repeat)
            elif repeat == "eachPixelGroup":
                targets = pixel_groups
            else:  # eachPixelXYZ / eachPixelXZY / ... → tous les pixels
                targets = pixel_keys
            n = len(targets)
            if n == 0 or not cell:
                continue

            start = len(profile)
            per_pixel = ref.get("channelOrder", "perPixel") != "perChannel"
            if per_pixel:
                for _ in range(n):
                    for t in cell:
                        _emit(t)
            else:
                for t in cell:
                    for _ in range(n):
                        _emit(t)

            # Une seule géométrie retenue par mode (le plus gros bloc pixel)
            if matrix_meta is None or n * len(cell) > matrix_meta["pixel_count"] * len(matrix_meta["pixel_channels"]):
                cols = mx_cols if targets is pixel_keys and mx_cols else n
                rows = mx_rows if targets is pixel_keys and mx_rows else 1
                if cols * rows != n:      # groupes / sous-ensemble → traiter en 1D
                    cols, rows = n, 1
                matrix_meta = {
                    "rows":           rows,
                    "cols":           cols,
                    "pixel_count":    n,
                    "pixel_channels": list(cell),
                    "head":           list(profile[:start]),
                    "offset":         start,
                    "order":          "perPixel" if per_pixel else "perChannel",
                }
            continue

        _emit(_type_of(str(ref)))

    if matrix_meta is not None:
        matrix_meta["tail"] = list(profile[matrix_meta["offset"]
                                           + matrix_meta["pixel_count"]
                                           * len(matrix_meta["pixel_channels"]):])

    return profile, matrix_meta


def _physical_dims(obj: dict, mode: dict = None) -> dict:
    """
    Dimensions physiques (mm) d'une fixture OFL : {"w":…, "h":…, "d":…}.

    Sert à dessiner une barre à sa vraie échelle sur le plan de feu (une barre
    d'1 m et un wash de 20 cm ne doivent pas avoir la même taille). Un mode peut
    redéfinir le physique (ex : version longue/courte du même modèle).
    """
    dims = None
    if isinstance(mode, dict):
        dims = (mode.get("physical") or {}).get("dimensions")
    if not dims:
        dims = (obj.get("physical") or {}).get("dimensions")
    if not (isinstance(dims, list) and len(dims) >= 2):
        return {}
    try:
        w, h = float(dims[0]), float(dims[1])
        d = float(dims[2]) if len(dims) > 2 else 0.0
    except (TypeError, ValueError):
        return {}
    if w <= 0 or h <= 0:
        return {}
    return {"w": w, "h": h, "d": d}


def _detect_fixture_type(profile: list, matrix_meta: dict = None) -> str:
    """Déduit le type de fixture depuis son profil."""
    if "Pan" in profile or "Tilt" in profile:
        return "Moving Head"
    if matrix_meta:
        return "Barre LED" if matrix_meta.get("rows", 1) <= 1 else "Matrice LED"
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
    templates = obj.get("templateChannels", {})
    matrix    = obj.get("matrix", {})
    raw_modes  = obj.get("modes", [])

    modes = []
    for m in raw_modes:
        mode_name     = m.get("name") or m.get("shortName", f"Mode {len(modes)+1}")
        mode_channels = m.get("channels", [])
        profile, mx   = _map_channels(available, mode_channels, templates, matrix)
        entry = {
            "name":         mode_name,
            "channelCount": len(profile),
            "profile":      profile,
        }
        if mx:
            entry["matrix"] = mx
        _mph = _physical_dims(obj, m)
        if _mph:
            entry["physical"] = _mph
        modes.append(entry)

    if not modes:
        modes = [{"name": "Mode 1", "channelCount": 0, "profile": []}]

    first_profile = modes[0]["profile"] if modes else []
    # Le type suit le mode le plus riche : une barre reste une barre même si son
    # premier mode est le 3 canaux "Master".
    _mx_any = next((m.get("matrix") for m in modes if m.get("matrix")), None)
    ftype = _detect_fixture_type(first_profile, _mx_any)

    wheel_slots = _extract_wheel_slots(obj, available)

    result = {
        "name":         name,
        "manufacturer": manufacturer,
        "fixture_type": ftype,
        "source":       "ofl",
        "uuid":         f"ofl:{manufacturer_key}/{fixture_key}" if manufacturer_key else "",
        "modes":        modes,
    }
    _phys = _physical_dims(obj)
    if _phys:
        result["physical"] = _phys

    if wheel_slots["color_wheel_slots"]:
        result["color_wheel_slots"] = wheel_slots["color_wheel_slots"]
    if wheel_slots["gobo_wheel_slots"]:
        result["gobo_wheel_slots"] = wheel_slots["gobo_wheel_slots"]

    return result
