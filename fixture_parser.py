"""
Parseur de fichiers fixture pour MyStrow.

Formats supportes :
  - GrandMA2/3 XML (.xml)
  - MyStrow fixture (.mystrow) — JSON natif

Usage :
    from fixture_parser import parse_file, export_mystrow
    fixture = parse_file("fixture.xml")
    # -> {"name": ..., "uuid": ..., "manufacturer": ..., "modes": [...], ...}
    export_mystrow(fixture, "fixture.mystrow")
"""

import json
import os
import xml.etree.ElementTree as ET

# Format marker pour les fichiers .mystrow
MYSTROW_FORMAT = "mystrow-fixture"
MYSTROW_VERSION = "1"

# ---------------------------------------------------------------------------
# Mapping GrandMA Channel/@name -> type de canal MyStrow (MA2)
# ---------------------------------------------------------------------------
_MA_MAP = {
    "Dimmer":          "Dim",
    "Dim":             "Dim",
    "Intensity":       "Dim",
    "Shutter":         "Strobe",
    "Strobe":          "Strobe",
    "Red":             "R",
    "Green":           "G",
    "Blue":            "B",
    "White":           "W",
    "Warm White":      "W",
    "Cold White":      "W",
    "Amber":           "Ambre",
    "Ambre":           "Ambre",
    "UV":              "UV",
    "Pan":             "Pan",
    "Pan fine":        "PanFine",
    "Pan Fine":        "PanFine",
    "Tilt":            "Tilt",
    "Tilt fine":       "TiltFine",
    "Tilt Fine":       "TiltFine",
    "Zoom":            "Zoom",
    "Focus":           "Focus",
    "Iris":            "Iris",
    "Gobo 1":          "Gobo1",
    "Gobo1":           "Gobo1",
    "Gobo 1 Rotation": "Gobo1Rot",
    "Gobo Rotation":   "Gobo1Rot",
    "Gobo 2":          "Gobo2",
    "Gobo2":           "Gobo2",
    "Prism":           "Prism",
    "Prism Rotation":  "PrismRot",
    "Color Wheel":     "ColorWheel",
    "Color":           "ColorWheel",
    "CTO":             "ColorWheel",
    "Speed":           "Speed",
    "Mode":            "Mode",
    "Control":         "Mode",
    "Function":        "Mode",
    "Macro":           "Mode",
}


# ---------------------------------------------------------------------------
# Mapping GrandMA3 ChannelType/@attribute -> type de canal MyStrow (MA3)
# ---------------------------------------------------------------------------
_MA3_ATTR_MAP = {
    # RGB
    "COLORRGB1":          "R",
    "COLORRGB2":          "G",
    "COLORRGB3":          "B",
    # RGBW
    "COLORRGB4":          "W",
    # Dimmer
    "DIM":                "Dim",
    "DIMMER":             "Dim",
    "INTENSITY":          "Dim",
    # Strobe / Shutter
    "STROBE_RATIO":       "Strobe",
    "STROBE":             "Strobe",
    "SHUTTER":            "Strobe",
    # Amber / UV
    "COLORRGB5":          "Ambre",
    "COLORRGB6":          "UV",
    "COLORAMBER":         "Ambre",
    "COLORUV":            "UV",
    # Pan / Tilt
    "PAN":                "Pan",
    "PANROTATE":          "Pan",
    "TILT":               "Tilt",
    "TILTROTATE":         "Tilt",
    # Gobo
    "GOBO1":              "Gobo1",
    "GOBO1_POS":          "Gobo1Rot",
    "GOBO1INDEXROTATE":   "Gobo1Rot",
    "GOBO2":              "Gobo2",
    # Prism / Effect wheel
    "PRISM":              "Prism",
    "PRISMROTATION":      "PrismRot",
    "EFFECTWHEEL":        "Prism",
    "EFFECTINDEXROTATE":  "PrismRot",
    # Zoom / Focus / Iris
    "ZOOM":               "Zoom",
    "FOCUS":              "Focus",
    "IRIS":               "Iris",
    # Color wheel
    "COLOR1":             "ColorWheel",
    "COLOR2":             "ColorWheel",
    "COLORWHEEL":         "ColorWheel",
    "CTOMIXER":           "ColorWheel",
    # Speed / control
    "POSITIONMSPEED":     "Speed",
    "SPEED":              "Speed",
    "CONTROL":            "Mode",
    "FUNCTION":           "Mode",
    "MACRO":              "Mode",
}

# Fine channels associés à leur canal coarse
_FINE_MAP = {
    "Pan":  "PanFine",
    "Tilt": "TiltFine",
}

# Types de canaux valides pour les fine channels
_VALID_FINE_TYPES = {"PanFine", "TiltFine"}


def _detect_fixture_type(profile: list) -> str:
    """Deduit le type de fixture depuis son profil de canaux."""
    if "Pan" in profile or "Tilt" in profile:
        return "Moving Head"
    return "PAR LED"


# ---------------------------------------------------------------------------
# Parseur GrandMA (MA2 / MA3)
# ---------------------------------------------------------------------------

def _try_generic_xml(root) -> dict | None:
    """
    Tentative de parsing générique pour formats inconnus (Capture, ETC, etc.).
    Cherche n'importe quel nœud contenant des éléments Channel/channel.
    """
    name = (root.get("name") or root.get("Name") or root.get("fixture")
            or root.get("Fixture") or "")
    manufacturer = (root.get("manufacturer") or root.get("Manufacturer")
                    or root.get("mfr") or "")

    if not name:
        for el in root.iter():
            v = el.get("name") or el.get("Name") or el.text
            if v and v.strip() and el.tag.lower() in ("name", "fixture", "fixturename"):
                name = v.strip()
                break
    if not manufacturer:
        for el in root.iter():
            v = el.get("manufacturer") or el.get("Manufacturer") or el.text
            if v and v.strip() and el.tag.lower() in ("manufacturer", "make", "brand"):
                manufacturer = v.strip()
                break

    all_channels = []
    mode_elements = []
    for el in root.iter():
        tag = el.tag.lower()
        if tag in ("mode", "modedef", "channelset"):
            mode_elements.append(el)
        elif tag in ("channel", "channeldef", "attribute") and not mode_elements:
            all_channels.append(el)

    modes = []
    if mode_elements:
        for mode_el in mode_elements:
            mode_name = (mode_el.get("name") or mode_el.get("Name")
                         or f"Mode {len(modes)+1}")
            profile = []
            for ch in mode_el.iter():
                tag = ch.tag.lower()
                if tag in ("channel", "channeldef", "attribute", "channeltype"):
                    ch_name = (ch.get("name") or ch.get("Name")
                               or ch.get("attribute") or ch.get("Attribute") or "")
                    mapped = _MA_MAP.get(ch_name) or _MA_MAP.get(ch_name.title())
                    if mapped is None:
                        for k, v in _MA_MAP.items():
                            if k.lower() == ch_name.lower():
                                mapped = v
                                break
                    profile.append(mapped or "Mode")
            if profile:
                modes.append({"name": mode_name,
                               "channelCount": len(profile), "profile": profile})
    elif all_channels:
        profile = []
        for ch in all_channels:
            ch_name = (ch.get("name") or ch.get("Name")
                       or ch.get("attribute") or ch.get("Attribute") or "")
            mapped = _MA_MAP.get(ch_name)
            if mapped is None:
                for k, v in _MA_MAP.items():
                    if k.lower() == ch_name.lower():
                        mapped = v
                        break
            profile.append(mapped or "Mode")
        if profile:
            modes.append({"name": "Mode 1", "channelCount": len(profile),
                          "profile": profile})

    if not modes:
        return None

    first_profile = modes[0]["profile"]
    ftype = _detect_fixture_type(first_profile)
    return {
        "name":              name or "Fixture importée",
        "manufacturer":      manufacturer,
        "fixture_type":      ftype,
        "source":            "generic",
        "uuid":              "",
        "modes":             modes,
        "color_wheel_slots": [],
        "gobo_wheel_slots":  [],
        "channel_defaults":  {},
    }


def _strip_namespaces(data: bytes) -> bytes:
    """Supprime les déclarations de namespace XML pour simplifier le parsing."""
    import re
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', text)
    text = re.sub(r'(\s)\w+:(\w+)=', r'\1\2=', text)
    text = re.sub(r'<(/?)(\w+):(\w)', r'<\1\3', text)
    return text.encode("utf-8")


def parse_ma_xml(data: bytes) -> dict:
    """
    Parse un fichier XML GrandMA2/3 ou format générique depuis des bytes.
    Retourne le dict fixture standardise.
    """
    try:
        root = ET.fromstring(_strip_namespaces(data))
    except ET.ParseError:
        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            raise ValueError(f"XML invalide : {e}")

    fixture_el = _find_fixture_element(root)
    if fixture_el is None:
        result = _try_generic_xml(root)
        if result:
            return result
        raise ValueError("Structure XML non reconnue (MA2/MA3 attendu)")

    name = (fixture_el.get("name") or fixture_el.get("Name")
            or fixture_el.get("fixture") or "")
    _mfr_el = fixture_el.find("manufacturer")
    if _mfr_el is None:
        _mfr_el = fixture_el.find("Manufacturer")
    manufacturer = (
        (_mfr_el.text.strip() if _mfr_el is not None and _mfr_el.text else "")
        or fixture_el.get("manufacturer") or fixture_el.get("Manufacturer") or ""
    )
    source = _detect_ma_version(root)

    modes, channel_defaults = _parse_ma_modes(fixture_el)
    if not modes:
        modes = [{"name": "Mode 1", "channelCount": 0, "profile": []}]

    first_profile = modes[0]["profile"] if modes else []
    ftype = _detect_fixture_type(first_profile)

    # Extraction des roues couleur et gobo
    wheels = _extract_ma3_wheels(fixture_el)

    return {
        "name":              name,
        "manufacturer":      manufacturer,
        "fixture_type":      ftype,
        "source":            source,
        "uuid":              "",
        "modes":             modes,
        "color_wheel_slots": wheels["color_wheel_slots"],
        "gobo_wheel_slots":  wheels["gobo_wheel_slots"],
        "channel_defaults":  channel_defaults,
    }


def _detect_ma_version(root) -> str:
    tag = root.tag.lower()
    major = root.get("major_vers") or root.get("Major_vers") or ""
    if "ma3" in tag or major.startswith("3") or root.get("Version", "").startswith("3"):
        return "ma3"
    return "ma2"


def _find_fixture_element(root):
    known_tags = {
        "fixture", "fixturetype", "gdtf", "capturefixture",
        "fixturedefinition", "fixturetype", "device",
    }
    if root.tag.lower() in known_tags:
        return root
    for tag in ("Fixture", "FixtureType", "fixture", "fixturetype",
                "GDTFFixture", "CaptureFixture", "FixtureDefinition",
                "Device", "device"):
        el = root.find(tag)
        if el is not None:
            return el
    for child in root:
        found = _find_fixture_element(child)
        if found is not None:
            return found
    return None


def _parse_ma_modes(fixture_el) -> tuple:
    """Retourne (modes_list, channel_defaults_dict)."""
    modes = []
    channel_defaults = {}

    # --- MA3 path : <ChannelType attribute="..." coarse="..."> ---
    channel_types = fixture_el.findall(".//ChannelType")
    if channel_types:
        mode_name = (fixture_el.get("mode") or fixture_el.get("Mode") or "Mode 1")
        profile, channel_defaults = _parse_ma3_channels(channel_types)
        if profile:
            modes.append({
                "name":         mode_name,
                "channelCount": len(profile),
                "profile":      profile,
            })
        return modes, channel_defaults

    # --- MA2 path : <Modes><Mode><Channel ...> ---
    _found_modes = fixture_el.find("Modes")
    modes_container = _found_modes if _found_modes is not None else fixture_el
    mode_elements = modes_container.findall("Mode")
    if not mode_elements:
        mode_elements = fixture_el.findall(".//Mode")

    for mode_el in mode_elements:
        mode_name = (mode_el.get("name") or mode_el.get("Name")
                     or f"Mode {len(modes)+1}")
        profile = _parse_ma_channels(mode_el)
        modes.append({
            "name":         mode_name,
            "channelCount": len(profile),
            "profile":      profile,
        })

    if not modes:
        profile = _parse_ma_channels(fixture_el)
        if profile:
            modes.append({
                "name":         "Mode 1",
                "channelCount": len(profile),
                "profile":      profile,
            })
    return modes, channel_defaults


def _parse_ma3_channels(channel_type_elements) -> tuple:
    """
    Parse MA3 <ChannelType attribute='...' coarse='...'> elements.
    Retourne (profile_list, channel_defaults_dict).
    Gère les canaux fine (PanFine/TiltFine) et les valeurs par défaut.
    """
    items = []       # [(ch_index, ch_type)]
    defaults = {}    # {ch_type: dmx_8bit}

    for ct in channel_type_elements:
        attr   = (ct.get("attribute") or ct.get("Attribute") or "").upper().strip()
        coarse = ct.get("coarse") or ct.get("Coarse") or "0"
        fine   = ct.get("fine")   or ct.get("Fine")
        default_str = ct.get("default") or ct.get("Default")

        try:
            ch_index = int(coarse)
        except ValueError:
            ch_index = 0

        # Résolution du type de canal
        mapped = _MA3_ATTR_MAP.get(attr)
        if mapped is None:
            for key, val in _MA3_ATTR_MAP.items():
                if attr.startswith(key):
                    mapped = val
                    break
        ch_type = mapped if mapped else "Mode"

        items.append((ch_index, ch_type))

        # Canal fine (PanFine / TiltFine)
        if fine is not None:
            fine_type = _FINE_MAP.get(ch_type)
            if fine_type:
                try:
                    fine_idx = int(fine)
                    items.append((fine_idx, fine_type))
                except ValueError:
                    pass

        # Valeur par défaut du canal
        if default_str is not None:
            try:
                default_val = float(default_str)
                # Channels avec fine = 16-bit (0-65535) → coarse 8-bit = val/256
                # Channels sans fine = 8-bit (0-255) → utiliser directement
                if fine is not None:
                    dmx_8bit = min(255, max(0, int(round(default_val / 256))))
                else:
                    dmx_8bit = min(255, max(0, int(round(default_val))))
                if dmx_8bit > 0:
                    defaults[ch_type] = dmx_8bit
            except ValueError:
                pass

    items.sort(key=lambda x: x[0])
    return [ch for _, ch in items], defaults


def _parse_ma_channels(parent_el) -> list:
    profile = []
    for ch_el in parent_el.findall("Channel"):
        ch_name = (ch_el.get("name") or ch_el.get("Name") or "")
        mapped  = _MA_MAP.get(ch_name)
        if mapped is None:
            ch_lower = ch_name.lower()
            for key, val in _MA_MAP.items():
                if key.lower() == ch_lower:
                    mapped = val
                    break
        profile.append(mapped if mapped else "Mode")
    return profile


# ---------------------------------------------------------------------------
# Extraction des roues couleur / gobo depuis <Wheels>
# ---------------------------------------------------------------------------

def _extract_ma3_wheels(fixture_el) -> dict:
    """
    Extrait color_wheel_slots et gobo_wheel_slots depuis le bloc <Wheels>.
    Associe les DMX réels depuis les ChannelSets des ChannelFunctions correspondants.
    """
    result = {"color_wheel_slots": [], "gobo_wheel_slots": []}

    wheels_el = fixture_el.find("Wheels")
    if wheels_el is None:
        return result

    # Construction du mapping slot_index → from_dmx pour chaque attribut
    # en lisant les ChannelFunctions des ChannelTypes
    slot_dmx = {}  # {attr_upper: {slot_index: from_dmx}}
    for ct in fixture_el.findall(".//ChannelType"):
        attr = (ct.get("attribute") or "").upper()
        if not attr:
            continue
        slot_dmx.setdefault(attr, {})
        for cf in ct.findall("ChannelFunction"):
            sub = (cf.get("subattribute") or "").upper()
            # Ignorer les fonctions de rotation/spin — ne prendre que la sélection statique
            if any(k in sub for k in ("SPIN", "ROT", "INDEX")):
                continue
            for cs in cf.findall("ChannelSet"):
                si = cs.get("slot_index")
                fd = cs.get("from_dmx")
                if si is not None and fd is not None:
                    try:
                        slot_dmx[attr][int(si)] = int(fd)
                    except ValueError:
                        pass

    for wheel_el in wheels_el.findall("Wheel"):
        sub  = (wheel_el.get("subattribute") or "").upper()
        attr = (wheel_el.get("attribute") or sub).upper()

        is_color = "COLOR" in attr
        is_gobo  = "GOBO" in attr

        if not is_color and not is_gobo:
            continue

        dmx_map = slot_dmx.get(attr, {})
        slots = []

        for slot_el in wheel_el.findall("Slot"):
            raw_idx = slot_el.get("index", str(len(slots)))
            try:
                slot_i = int(raw_idx)
            except ValueError:
                slot_i = len(slots)

            name = slot_el.get("media_name") or f"Slot {slot_i}"

            # DMX : depuis le mapping ChannelSet, sinon fallback slot_i * 32
            dmx_val = dmx_map.get(slot_i, slot_i * 32)

            if is_color:
                # Attributs r/g/b — absent = 255 (canal plein)
                r = int(slot_el.get("r", 255))
                g = int(slot_el.get("g", 255))
                b = int(slot_el.get("b", 255))
                hex_color = f"#{r:02x}{g:02x}{b:02x}"
                slots.append({"name": name, "color": hex_color, "dmx": dmx_val})
            else:
                slots.append({"name": name, "color": "#888888", "dmx": dmx_val})

        if slots:
            if is_color:
                result["color_wheel_slots"] = slots
            else:
                result["gobo_wheel_slots"] = slots

    return result


# ---------------------------------------------------------------------------
# Parseur .mystrow
# ---------------------------------------------------------------------------

def parse_mystrow(data: bytes) -> dict:
    """
    Parse un fichier .mystrow (JSON MyStrow) depuis des bytes.
    Valide la structure minimale et retourne le dict fixture standardise.
    """
    try:
        obj = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Fichier .mystrow invalide (JSON attendu) : {e}")

    if not isinstance(obj, dict):
        raise ValueError("Fichier .mystrow invalide : objet JSON attendu")

    name  = obj.get("name", "")
    modes = obj.get("modes", [])
    if not name:
        raise ValueError("Champ 'name' manquant dans le fichier .mystrow")

    normalized = []
    for m in modes:
        if not isinstance(m, dict):
            continue
        profile = m.get("profile", [])
        normalized.append({
            "name":         m.get("name", f"Mode {len(normalized)+1}"),
            "channelCount": m.get("channelCount", len(profile)),
            "profile":      profile,
        })

    first_profile = normalized[0]["profile"] if normalized else []
    ftype = obj.get("fixture_type") or _detect_fixture_type(first_profile)

    return {
        "name":              name,
        "manufacturer":      obj.get("manufacturer", ""),
        "fixture_type":      ftype,
        "source":            obj.get("source", "custom"),
        "uuid":              obj.get("uuid", ""),
        "modes":             normalized,
        "color_wheel_slots": obj.get("color_wheel_slots", []),
        "gobo_wheel_slots":  obj.get("gobo_wheel_slots", []),
        "channel_defaults":  obj.get("channel_defaults", {}),
    }


# ---------------------------------------------------------------------------
# Export .mystrow
# ---------------------------------------------------------------------------

def export_mystrow(fixture: dict, path: str) -> None:
    """
    Exporte un dict fixture au format .mystrow (JSON).
    """
    data = {
        "format":            MYSTROW_FORMAT,
        "version":           MYSTROW_VERSION,
        "name":              fixture.get("name", ""),
        "manufacturer":      fixture.get("manufacturer", ""),
        "fixture_type":      fixture.get("fixture_type", "PAR LED"),
        "source":            fixture.get("source", "custom"),
        "uuid":              fixture.get("uuid", ""),
        "modes":             fixture.get("modes", []),
        "color_wheel_slots": fixture.get("color_wheel_slots", []),
        "gobo_wheel_slots":  fixture.get("gobo_wheel_slots", []),
        "channel_defaults":  fixture.get("channel_defaults", {}),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def parse_file(path: str) -> dict:
    """
    Parse automatiquement un fichier fixture selon son extension.
    Supporte : .xml, .mystrow
    Retourne le dict fixture standardise.
    """
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        data = f.read()

    if ext == ".mystrow":
        return parse_mystrow(data)
    elif ext == ".xml":
        return parse_ma_xml(data)
    else:
        try:
            return parse_mystrow(data)
        except ValueError:
            return parse_ma_xml(data)
