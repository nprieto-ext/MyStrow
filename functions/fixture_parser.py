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

import gzip
import json
import os
import xml.etree.ElementTree as ET

# Format marker pour les fichiers .mystrow
MYSTROW_FORMAT = "mystrow-fixture"
MYSTROW_VERSION = "1"

# ---------------------------------------------------------------------------
# Mapping GrandMA Channel/@name -> type de canal MyStrow
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


def _detect_fixture_type(profile: list) -> str:
    """Deduit le type de fixture depuis son profil de canaux."""
    if "Pan" in profile or "Tilt" in profile:
        return "Moving Head"
    return "PAR LED"


# ---------------------------------------------------------------------------
# Parseur GrandMA (MA2 / MA3)
# ---------------------------------------------------------------------------

def parse_ma_xml(data: bytes) -> dict:
    """
    Parse un fichier XML GrandMA2 ou GrandMA3 depuis des bytes.
    Retourne le dict fixture standardise.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"XML invalide : {e}")

    fixture_el = _find_fixture_element(root)
    if fixture_el is None:
        raise ValueError("Structure XML non reconnue (MA2/MA3 attendu)")

    name         = (fixture_el.get("name") or fixture_el.get("Name")
                    or fixture_el.get("fixture") or "")
    manufacturer = (fixture_el.get("manufacturer") or fixture_el.get("Manufacturer") or "")
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
    if "ma3" in tag or root.get("Version", "").startswith("3"):
        return "ma3"
    return "ma2"


def _find_fixture_element(root):
    for tag in ("Fixture", "FixtureType", "fixture", "fixturetype"):
        el = root.find(tag)
        if el is not None:
            return el
    if root.tag.lower() in ("fixture", "fixturetype"):
        return root
    for child in root:
        found = _find_fixture_element(child)
        if found is not None:
            return found
    return None


def _parse_ma_modes(fixture_el) -> list:
    modes = []
    modes_container = fixture_el.find("Modes") or fixture_el
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
# Parseur XMLP (GrandMA2 — XML gzippé avec header "MA DATA?")
# ---------------------------------------------------------------------------

def parse_xmlp(data: bytes) -> dict:
    """
    Parse un fichier .xmlp GrandMA2.
    Format : header optionnel + données gzip + XML avec préfixe "MA DATA?".
    """
    # Localise le magic gzip \x1f\x8b dans le fichier
    idx = data.find(b'\x1f\x8b')
    if idx == -1:
        # Certains XMLP GrandMA3 sont chiffrés (pas de magic gzip)
        raise ValueError("LOCKED_XMLP")
    try:
        xml_data = gzip.decompress(data[idx:])
    except Exception as e:
        raise ValueError(f"Décompression XMLP échouée : {e}")

    # Supprime le préfixe "MA DATA?" s'il est présent après décompression
    if xml_data.startswith(b'MA DATA?'):
        xml_data = xml_data[8:]
    # Supprime le BOM UTF-8 éventuel
    if xml_data.startswith(b'\xef\xbb\xbf'):
        xml_data = xml_data[3:]

    return parse_ma_xml(xml_data)


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
    elif ext == ".xmlp":
        return parse_xmlp(data)
    elif ext == ".xml":
        return parse_ma_xml(data)
    else:
        # Essayer JSON d'abord (mystrow sans extension)
        try:
            return parse_mystrow(data)
        except ValueError:
            return parse_ma_xml(data)
