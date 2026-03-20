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
    "Dimmer":      "Dim",
    "Dim":         "Dim",
    "Intensity":   "Dim",
    "Shutter":     "Strobe",
    "Strobe":      "Strobe",
    "Red":         "R",
    "Green":       "G",
    "Blue":        "B",
    "White":       "W",
    "Warm White":  "W",
    "Cold White":  "W",
    "Amber":       "Ambre",
    "Ambre":       "Ambre",
    "UV":          "UV",
    "Pan":         "Pan",
    "Pan fine":    "PanFine",
    "Pan Fine":    "PanFine",
    "Tilt":        "Tilt",
    "Tilt fine":   "TiltFine",
    "Tilt Fine":   "TiltFine",
    "Zoom":        "Zoom",
    "Focus":       "Focus",
    "Iris":        "Iris",
    "Gobo 1":      "Gobo1",
    "Gobo1":       "Gobo1",
    "Gobo 2":      "Gobo2",
    "Gobo2":       "Gobo2",
    "Prism":       "Prism",
    "Color Wheel": "ColorWheel",
    "Color":       "ColorWheel",
    "CTO":         "ColorWheel",
    "Speed":       "Speed",
    "Mode":        "Mode",
    "Control":     "Mode",
    "Function":    "Mode",
    "Macro":       "Mode",
}


# ---------------------------------------------------------------------------
# Mapping GrandMA3 ChannelType/@attribute -> type de canal MyStrow (MA3)
# ---------------------------------------------------------------------------
_MA3_ATTR_MAP = {
    # RGB
    "COLORRGB1":     "R",
    "COLORRGB2":     "G",
    "COLORRGB3":     "B",
    # RGBW
    "COLORRGB4":     "W",
    # Dimmer
    "DIM":           "Dim",
    "DIMMER":        "Dim",
    "INTENSITY":     "Dim",
    # Strobe / Shutter
    "STROBE_RATIO":  "Strobe",
    "STROBE":        "Strobe",
    "SHUTTER":       "Strobe",
    # Amber / UV
    "COLORRGB5":     "Ambre",
    "COLORRGB6":     "UV",
    "COLORAMBER":    "Ambre",
    "COLORUV":       "UV",
    # Pan / Tilt
    "PAN":           "Pan",
    "PANROTATE":     "Pan",
    "TILT":          "Tilt",
    "TILTROTATE":    "Tilt",
    # Gobo / Prism
    "GOBO1":         "Gobo1",
    "GOBO2":         "Gobo2",
    "PRISM":         "Prism",
    # Zoom / Focus / Iris
    "ZOOM":          "Zoom",
    "FOCUS":         "Focus",
    "IRIS":          "Iris",
    # Color wheel / misc
    "COLORWHEEL":    "ColorWheel",
    "CTOMIXER":      "ColorWheel",
    "SPEED":         "Speed",
    "CONTROL":       "Mode",
    "FUNCTION":      "Mode",
    "MACRO":         "Mode",
}


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

    # Chercher récursivement le nom/mfr si pas trouvé à la racine
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

    # Chercher les modes / channels
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
        "name":         name or "Fixture importée",
        "manufacturer": manufacturer,
        "fixture_type": ftype,
        "source":       "generic",
        "uuid":         "",
        "modes":        modes,
    }


def _strip_namespaces(data: bytes) -> bytes:
    """Supprime les déclarations de namespace XML pour simplifier le parsing."""
    import re
    text = data.decode("utf-8", errors="replace")
    # Supprimer xmlns="..." et xmlns:prefix="..."
    text = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', text)
    # Supprimer les préfixes d'attributs (ex: xsi:schemaLocation -> schemaLocation)
    text = re.sub(r'(\s)\w+:(\w+)=', r'\1\2=', text)
    # Supprimer les préfixes de tag (ex: ma:Fixture -> Fixture)
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
        # Fallback : essayer sans strip namespaces
        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            raise ValueError(f"XML invalide : {e}")

    fixture_el = _find_fixture_element(root)
    if fixture_el is None:
        # Tentative de parsing générique avant d'abandonner
        result = _try_generic_xml(root)
        if result:
            return result
        raise ValueError("Structure XML non reconnue (MA2/MA3 attendu)")

    name         = (fixture_el.get("name") or fixture_el.get("Name")
                    or fixture_el.get("fixture") or "")
    # MA3 stores manufacturer as child text element, MA2 stores it as attribute
    _mfr_el = fixture_el.find("manufacturer")
    if _mfr_el is None:
        _mfr_el = fixture_el.find("Manufacturer")
    manufacturer = (
        (_mfr_el.text.strip() if _mfr_el is not None and _mfr_el.text else "")
        or fixture_el.get("manufacturer") or fixture_el.get("Manufacturer") or ""
    )
    source       = _detect_ma_version(root)

    modes = _parse_ma_modes(fixture_el)
    if not modes:
        modes = [{"name": "Mode 1", "channelCount": 0, "profile": []}]

    first_profile = modes[0]["profile"] if modes else []
    ftype = _detect_fixture_type(first_profile)

    return {
        "name":         name,
        "manufacturer": manufacturer,
        "fixture_type": ftype,
        "source":       source,
        "uuid":         "",
        "modes":        modes,
    }


def _detect_ma_version(root) -> str:
    tag = root.tag.lower()
    major = root.get("major_vers") or root.get("Major_vers") or ""
    if "ma3" in tag or major.startswith("3") or root.get("Version", "").startswith("3"):
        return "ma3"
    return "ma2"


def _find_fixture_element(root):
    # Tags reconnus : MA2/MA3 + formats alternatifs (Capture, ETC, Chamsys...)
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
    # Recherche récursive
    for child in root:
        found = _find_fixture_element(child)
        if found is not None:
            return found
    return None


def _parse_ma_modes(fixture_el) -> list:
    modes = []

    # --- MA3 path : <ChannelType attribute="..." coarse="..."> anywhere inside ---
    channel_types = fixture_el.findall(".//ChannelType")
    if channel_types:
        mode_name = (fixture_el.get("mode") or fixture_el.get("Mode") or "Mode 1")
        profile = _parse_ma3_channels(channel_types)
        if profile:
            modes.append({
                "name":         mode_name,
                "channelCount": len(profile),
                "profile":      profile,
            })
        return modes

    # --- MA2 path : <Modes><Mode><Channel ...> ---
    _found_modes = fixture_el.find("Modes")
    modes_container = _found_modes if _found_modes is not None else fixture_el
    mode_elements = modes_container.findall("Mode")
    if not mode_elements:
        mode_elements = fixture_el.findall(".//Mode")

    for mode_el in mode_elements:
        mode_name = (mode_el.get("name") or mode_el.get("Name")
                     or f"Mode {len(modes)+1}")
        profile   = _parse_ma_channels(mode_el)
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
    return modes


def _parse_ma3_channels(channel_type_elements) -> list:
    """Parse MA3 <ChannelType attribute='...' coarse='...'> elements into profile list."""
    items = []
    for ct in channel_type_elements:
        attr  = (ct.get("attribute") or ct.get("Attribute") or "").upper().strip()
        coarse = ct.get("coarse") or ct.get("Coarse") or "0"
        try:
            ch_index = int(coarse)
        except ValueError:
            ch_index = 0
        mapped = _MA3_ATTR_MAP.get(attr)
        if mapped is None:
            # Fallback: try prefix match (e.g. "COLORRGB1" already in map, else "Mode")
            for key, val in _MA3_ATTR_MAP.items():
                if attr.startswith(key):
                    mapped = val
                    break
        items.append((ch_index, mapped if mapped else "Mode"))

    # Sort by DMX coarse address (1-based)
    items.sort(key=lambda x: x[0])
    return [ch for _, ch in items]


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

    # Normaliser les modes si necessaire (channelCount auto-calcule)
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
        "name":         name,
        "manufacturer": obj.get("manufacturer", ""),
        "fixture_type": ftype,
        "source":       obj.get("source", "custom"),
        "uuid":         obj.get("uuid", ""),
        "modes":        normalized,
    }


# ---------------------------------------------------------------------------
# Export .mystrow
# ---------------------------------------------------------------------------

def export_mystrow(fixture: dict, path: str) -> None:
    """
    Exporte un dict fixture au format .mystrow (JSON).
    """
    data = {
        "format":       MYSTROW_FORMAT,
        "version":      MYSTROW_VERSION,
        "name":         fixture.get("name", ""),
        "manufacturer": fixture.get("manufacturer", ""),
        "fixture_type": fixture.get("fixture_type", "PAR LED"),
        "source":       fixture.get("source", "custom"),
        "uuid":         fixture.get("uuid", ""),
        "modes":        fixture.get("modes", []),
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
        # Essayer JSON d'abord (mystrow sans extension)
        try:
            return parse_mystrow(data)
        except ValueError:
            return parse_ma_xml(data)
