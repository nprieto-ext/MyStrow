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
import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

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
    # CTO/CTB : canaux propres, PAS la roue de couleurs. Les confondre les
    # gangait avec elle — un correcteur de temperature faisait tourner la roue.
    "CTO":             "CTO",
    "CTB":             "CTB",
    "CTC":             "CTB",
    "Speed":           "Speed",
    "Mode":            "Mode",
    "Control":         "Mode",
    "Function":        "Mode",
    "Macro":           "Mode",
    "Reset":           "Reset",
    "Fixture Reset":   "Reset",
    "Lamp Reset":      "Reset",
}


# ---------------------------------------------------------------------------
# Mappings QLC+ -> MyStrow
# ---------------------------------------------------------------------------
_QLC_COLOUR_MAP = {
    "Red": "R", "Green": "G", "Blue": "B",
    "White": "W", "Warm White": "W", "Cold White": "W", "Neutral White": "W",
    "Amber": "Ambre", "UV": "UV", "UV Violet": "UV", "Indigo": "UV",
    "Orange": "Orange", "Pink": "R",
    # Trichromie et lime : canaux propres depuis qu'ils existent. Les rabattre
    # sur R/G/Orange envoyait carrement la mauvaise valeur — l'intensite du VERT
    # partait sur le drapeau cyan d'un spot CMY. Le moteur distingue ensuite
    # additif et soustractif selon la presence de R/G/B dans le profil.
    "Cyan": "C", "Magenta": "M", "Yellow": "Y", "Lime": "Lime",
}
_QLC_GROUP_MAP = {
    "Pan": "Pan", "Tilt": "Tilt",
    "Speed": "Speed", "Shutter": "Strobe",
    "Gobo": "Gobo1", "Colour": "ColorWheel",
    "Prism": "Prism", "Beam": "Zoom", "Iris": "Iris", "Focus": "Focus",
    "Effect": "Mode", "Maintenance": "Reset", "Nothing": "Mode",
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
    "CTOMIXER":           "CTO",
    "CTO":                "CTO",
    "CTB":                "CTB",
    "CTBMIXER":           "CTB",
    # Speed / control
    "POSITIONMSPEED":     "Speed",
    "SPEED":              "Speed",
    "CONTROL":            "Mode",
    "FUNCTION":           "Mode",
    "MACRO":              "Mode",
    "RESET":              "Reset",
    "FIXTURERESET":       "Reset",
    "LAMPRESET":          "Reset",
}

# ---------------------------------------------------------------------------
# Résolution des LED de couleur (« emitters ») MA2/MA3
#
# ⚠️ COLORRGB<n> n'est PAS un code couleur : c'est le n-ième emitter de la
# fixture. Les bibliothèques MA numérotent librement — la Contest irLED64 SIX
# déclare son BLANC en COLORRGB5 et son AMBRE en COLORRGB4, l'inverse de
# _MA3_ATTR_MAP. La vraie couleur est portée par l'attribut color="ffffff" du
# ChannelType et/ou par subattribute_user_name="White". On s'en sert d'abord,
# et on ne retombe sur la numérotation que sans aucun indice.
# ---------------------------------------------------------------------------
_EMITTER_NAMES = {
    "r": "R", "red": "R", "rouge": "R",
    "g": "G", "green": "G", "vert": "G", "lime": "G",
    "b": "B", "blue": "B", "bleu": "B",
    "w": "W", "white": "W", "blanc": "W", "wht": "W",
    "ww": "W", "warm white": "W", "warmwhite": "W",
    "cw": "W", "cold white": "W", "cool white": "W", "neutral white": "W",
    "amber": "Ambre", "ambre": "Ambre",
    "uv": "UV", "ultraviolet": "UV",
    "orange": "Orange",
}
# NB : ni « yellow » ni « cyan »/« magenta » ici — sur un spot ce sont les
# drapeaux CMY (soustractifs, 0 = ouvert), pas des LED. Les traiter comme des
# emitters mettait le jaune d'une CMY sur le canal Orange de MyStrow.

# Couleurs de référence des emitters -> canal MyStrow (plus proche en RGB)
_EMITTER_HEX = [
    ((255,   0,   0), "R"),      # rouge
    ((255,   0, 255), "R"),      # magenta
    ((  0, 255,   0), "G"),      # vert
    ((  0, 255, 255), "G"),      # cyan
    ((204, 255,   0), "G"),      # lime
    ((  0,   0, 255), "B"),      # bleu
    ((255, 255, 255), "W"),      # blanc
    ((255, 204, 136), "W"),      # blanc chaud
    ((255, 191,   0), "Ambre"),
    ((255, 136,   0), "Orange"),
    ((255, 221,   0), "Orange"),  # jaune
    ((147,   0, 255), "UV"),
    ((102,   0, 204), "UV"),
    (( 51,   0, 255), "UV"),      # violet profond : la Contest SIX code son UV ainsi
    (( 75,   0, 130), "UV"),      # indigo
]


def _emitter_from_hex(raw: str):
    """'ffffff' / '#ffbf00' -> 'W' / 'Ambre'. None si illisible."""
    txt = (raw or "").strip().lstrip("#")
    if len(txt) != 6:
        return None
    try:
        r, g, b = (int(txt[i:i+2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    best, best_d = None, None
    for (cr, cg, cb), ch_type in _EMITTER_HEX:
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if best_d is None or d < best_d:
            best, best_d = ch_type, d
    return best


def _emitter_from_name(raw: str):
    """'White' / 'W1' / 'Warm White' -> 'W'. None si non reconnu."""
    txt = re.sub(r"[\s_\-]+", " ", (raw or "").strip().lower())
    txt = re.sub(r"\s*\d+$", "", txt)          # « W1 », « White 2 » -> « w », « white »
    return _EMITTER_NAMES.get(txt)


def _resolve_emitter(ct) -> str | None:
    """Type de canal d'un emitter depuis sa couleur déclarée, sinon son nom."""
    mapped = _emitter_from_hex(ct.get("color") or ct.get("Color") or "")
    if mapped:
        return mapped
    for src in (ct, *ct.findall("ChannelFunction")):
        for key in ("subattribute_user_name", "attribute_user_name", "name"):
            mapped = _emitter_from_name(src.get(key) or "")
            if mapped:
                return mapped
    return None


def _is_emitter_attr(attr: str, ct) -> bool:
    """Le canal pilote-t-il une LED de couleur (mélange additif) ?"""
    if attr.startswith(("COLORRGB", "COLORADD")):
        return True
    if attr in ("COLORAMBER", "COLORUV", "COLORWHITE", "COLORLIME"):
        return True
    # Bibliothèques « maison » : attribute libre (R1, G1, W1...) mais preset COLOR
    if attr not in _MA3_ATTR_MAP:
        preset  = (ct.get("preset") or "").upper()
        feature = (ct.get("feature") or "").upper()
        if preset == "COLOR" or feature.startswith("COLOR"):
            return True
    return False


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

        # Résolution du type de canal — la couleur déclarée prime sur le
        # numéro d'emitter (cf. _resolve_emitter)
        mapped = _resolve_emitter(ct) if _is_emitter_attr(attr, ct) else None
        if mapped is None:
            mapped = _MA3_ATTR_MAP.get(attr)
        if mapped is None:
            # Repli par préfixe, sans avaler un numéro d'emitter voisin :
            # COLORRGB15 ne doit PAS être reconnu comme COLORRGB1 (rouge).
            for key, val in _MA3_ATTR_MAP.items():
                if attr.startswith(key) and not attr[len(key):len(key)+1].isdigit():
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

# Noms de couleurs rencontrés dans les <Capability> QLC+ anciens, qui ne
# portent pas encore l'attribut Color. Sert de repli pour teinter le slot.
_QLC_CAP_COLOURS = {
    "white": "#ffffff", "blanc": "#ffffff",
    "red": "#ff0000", "rouge": "#ff0000",
    "orange": "#ff8800",
    "amber": "#ffbf00", "ambre": "#ffbf00",
    "yellow": "#ffdd00", "jaune": "#ffdd00",
    "green": "#00ff00", "vert": "#00ff00",
    "cyan": "#00dddd",
    "blue": "#0000ff", "bleu": "#0000ff",
    "lavender": "#b57edc", "lavande": "#b57edc",
    "magenta": "#ff00ff", "pink": "#ff69b4", "rose": "#ff69b4",
    "purple": "#8000ff", "violet": "#8000ff",
    "uv": "#6600cc",
    "congo": "#1a1aff", "ctb": "#aaccff", "cto": "#ffcc88",
}

# Capacités qui ne désignent PAS une position fixe de roue : les retenir
# comme slots ferait choisir « défilement arc-en-ciel » quand on demande du
# rouge, puisque la sélection se fait par proximité de couleur.
_QLC_CAP_SKIP = ("rotation", "rotate", "scroll", "rainbow", "spin",
                 "cw", "ccw", "sound", "reset", "index", "continuous")


def _qlc_capability_slots(ch_el, coloured: bool) -> list:
    """[{name, color, dmx}] depuis les <Capability> d'un canal QLC+.

    `dmx` = MILIEU de la plage : les bornes tombent souvent pile à la frontière
    avec la capacité voisine, et un arrondi suffit alors à sélectionner le
    mauvais gobo ou la mauvaise couleur.
    """
    slots = []
    for cap in ch_el.findall("Capability"):
        nom = (cap.text or "").strip()
        if not nom:
            continue
        bas = nom.lower()
        if any(k in bas for k in _QLC_CAP_SKIP):
            continue
        try:
            mn = int(cap.get("Min", "0"))
            mx = int(cap.get("Max", mn))
        except ValueError:
            continue
        dmx = (mn + mx) // 2

        if coloured:
            couleur = cap.get("Color") or ""
            if not couleur:
                for mot, hexa in _QLC_CAP_COLOURS.items():
                    if mot in bas:
                        couleur = hexa
                        break
            couleur = couleur or "#888888"
        else:
            couleur = "#888888"
        slots.append({"name": nom, "color": couleur, "dmx": dmx})
    return slots


def parse_qlcplus_xml(data: bytes) -> dict:
    """
    Parse un fichier XML QLC+ (FixtureDefinition) depuis des bytes.
    Format : <FixtureDefinition xmlns="http://www.qlcplus.org/...">
    """
    try:
        root = ET.fromstring(_strip_namespaces(data))
    except ET.ParseError as e:
        raise ValueError(f"XML QLC+ invalide : {e}")

    # Nom du fabricant et modèle
    mfr_el  = root.find("Manufacturer")
    model_el = root.find("Model")
    type_el  = root.find("Type")
    manufacturer = (mfr_el.text.strip()  if mfr_el  is not None and mfr_el.text  else "")
    model        = (model_el.text.strip() if model_el is not None and model_el.text else "")
    qlc_type     = (type_el.text.strip()  if type_el  is not None and type_el.text  else "")

    # Mapping type QLC+ -> fixture_type MyStrow
    # ⚠️ "Moving Head" et NON "Lyre" : c'est le libellé utilisé partout ailleurs
    # (builtin_fixtures, _detect_fixture_type, admin). Avec "Lyre", une lyre
    # importée de QLC+ n'était reconnue comme lyre nulle part — ni par le
    # curseur de couleur (_is_cw_only), ni par la proposition de calibration,
    # ni par la piste Position du séquenceur.
    _TYPE_MAP = {
        "Moving Head":    "Moving Head",
        "Scanner":        "Moving Head",
        "Dimmer":         "Dimmer",
        "Smoke":          "Machine a fumee",
        "Hazer":          "Machine a fumee",
        "Strobe":         "Strobe",
        "LED Bar (Beams)": "Barre LED",
        "LED Bar (Pixels)": "Barre LED",
        "Fan":            "Ventilateur",
    }
    fixture_type = _TYPE_MAP.get(qlc_type, "PAR LED")

    # Construire la table canal_name -> type_mystrow
    channel_table = {}
    cw_slots, gobo_slots = [], []
    for ch_el in root.findall("Channel"):
        ch_name = ch_el.get("Name") or ""
        group_el  = ch_el.find("Group")
        colour_el = ch_el.find("Colour")
        group  = (group_el.text.strip()  if group_el  is not None and group_el.text  else "")
        colour = (colour_el.text.strip() if colour_el is not None and colour_el.text else "")

        if group == "Intensity":
            # <Colour> absent sur les définitions anciennes/faites main : sans
            # repli sur le nom, un canal « White » devenait un second Dimmer.
            ch_type = (_QLC_COLOUR_MAP.get(colour)
                       or _emitter_from_name(ch_name)
                       or "Dim")
        elif group in _QLC_GROUP_MAP:
            ch_type = _QLC_GROUP_MAP[group]
            # Pan Fine / Tilt Fine via attribut Byte="1"
            byte_attr = group_el.get("Byte", "0") if group_el is not None else "0"
            if byte_attr == "1":
                ch_type = "PanFine" if group == "Pan" else ("TiltFine" if group == "Tilt" else ch_type)
        else:
            ch_type = "Mode"
        channel_table[ch_name] = ch_type

        # Roues : les positions sont décrites par les <Capability> du canal.
        # Sans ça la fixture arrivait avec des roues VIDES et MyStrow retombait
        # sur une table générique teinte → DMX, sans rapport avec le matériel.
        if ch_type == "ColorWheel" and not cw_slots:
            cw_slots = _qlc_capability_slots(ch_el, coloured=True)
        elif ch_type in ("Gobo1", "Gobo2") and not gobo_slots:
            gobo_slots = _qlc_capability_slots(ch_el, coloured=False)

    # Parser les modes
    modes = []
    for mode_el in root.findall("Mode"):
        mode_name = mode_el.get("Name") or f"Mode {len(modes)+1}"
        # Trier les canaux par numéro
        ch_entries = []
        for ch_ref in mode_el.findall("Channel"):
            try:
                num = int(ch_ref.get("Number", "0"))
            except ValueError:
                num = len(ch_entries)
            ch_name = ch_ref.text or ""
            ch_type = channel_table.get(ch_name, "Mode")
            ch_entries.append((num, ch_type))
        ch_entries.sort(key=lambda x: x[0])
        profile = [ct for _, ct in ch_entries]
        if profile:
            modes.append({"name": mode_name, "channelCount": len(profile), "profile": profile})

    if not modes and channel_table:
        # Pas de mode déclaré : utiliser tous les canaux dans l'ordre de déclaration
        profile = list(channel_table.values())
        modes = [{"name": "Mode 1", "channelCount": len(profile), "profile": profile}]

    if not modes:
        raise ValueError("Aucun canal DMX trouvé dans le fichier QLC+.")

    first_profile = modes[0]["profile"]
    ftype = _detect_fixture_type(first_profile) if fixture_type == "PAR LED" else fixture_type

    return {
        "name":              model,
        "manufacturer":      manufacturer,
        "fixture_type":      ftype,
        "source":            "qlcplus",
        "uuid":              "",
        "modes":             modes,
        "color_wheel_slots": cw_slots,
        "gobo_wheel_slots":  gobo_slots,
        "channel_defaults":  {},
    }


def _is_qlcplus_xml(data: bytes) -> bool:
    """Détecte si les bytes correspondent à un fichier QLC+ (FixtureDefinition)."""
    try:
        header = data[:512].decode("utf-8", errors="ignore")
        return "qlcplus.org" in header or "FixtureDefinition" in header
    except Exception:
        return False


def _decompress_xmlp(data: bytes) -> bytes:
    """Décompresse un fichier .xmlp (ZIP, zlib, Qt qCompress ou gzip contenant du XML)."""
    # Signature ZIP (PK)
    if data[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
                xml_names = [n for n in names if n.lower().endswith(('.xml', '.qxf', '.qxl'))]
                target = xml_names[0] if xml_names else names[0]
                return zf.read(target)
        except Exception:
            pass
    # zlib standard (header 0x78 0x9C / 0x78 0xDA / 0x78 0x01)
    if data[:1] == b'\x78':
        try:
            return zlib.decompress(data)
        except zlib.error:
            pass
    # Qt qCompress : 4 octets taille big-endian + flux zlib (utilisé par QLC+)
    if len(data) > 4 and data[4:5] == b'\x78':
        try:
            return zlib.decompress(data[4:])
        except zlib.error:
            pass
    # gzip au début (header 0x1F 0x8B)
    if data[:2] == b'\x1f\x8b':
        try:
            return gzip.decompress(data)
        except Exception:
            pass
    # gzip avec header propriétaire devant (MA3 / MA2) — cherche le magic n'importe où
    idx = data.find(b'\x1f\x8b')
    if idx > 0:
        try:
            decompressed = gzip.decompress(data[idx:])
            # Supprime le préfixe "MA DATA?" éventuel après décompression
            if decompressed.startswith(b'MA DATA?'):
                decompressed = decompressed[8:]
            if decompressed.startswith(b'\xef\xbb\xbf'):
                decompressed = decompressed[3:]
            return decompressed
        except Exception:
            pass
    # deflate raw (sans header)
    try:
        return zlib.decompress(data, -15)
    except zlib.error:
        pass
    # Déjà du XML brut (ou format inconnu)
    return data


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
    elif ext in (".xml", ".xmlp"):
        if ext == ".xmlp":
            decompressed = _decompress_xmlp(data)
            if decompressed is data:
                raise ValueError("LOCKED_XMLP")
            # Supprime le préfixe "MA DATA?" présent après décompression des XMLP GrandMA2
            if decompressed.startswith(b'MA DATA?'):
                decompressed = decompressed[8:]
            # Supprime le BOM UTF-8 éventuel
            if decompressed.startswith(b'\xef\xbb\xbf'):
                decompressed = decompressed[3:]
            data = decompressed
        if _is_qlcplus_xml(data):
            return parse_qlcplus_xml(data)
        return parse_ma_xml(data)
    else:
        try:
            return parse_mystrow(data)
        except ValueError:
            if _is_qlcplus_xml(data):
                return parse_qlcplus_xml(data)
            return parse_ma_xml(data)
