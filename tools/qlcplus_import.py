"""
Parse tous les fichiers .qxf du repo QLC+ et produit fixtures_qlcplus.json
dans le dossier MyStrow.

Usage:
    python tools/qlcplus_import.py [--qlcpath C:/path/to/qlcplus_tmp]
"""
import os, sys, json, re, argparse
import xml.etree.ElementTree as ET

# ── Mapping QLC+ → MyStrow ────────────────────────────────────────────────────

_PRESET_MAP = {
    "IntensityRed":          "R",
    "IntensityGreen":        "G",
    "IntensityBlue":         "B",
    "IntensityWhite":        "W",
    "IntensityAmber":        "A",
    "IntensityUV":           "UV",
    "IntensityLime":         "Lime",
    "IntensityIndigo":       "UV",
    "IntensityCyan":         "C",
    "IntensityMagenta":      "M",
    "IntensityYellow":       "Y",
    "IntensityMasterDimmer": "Dim",
    "IntensityDimmer":       "Dim",
    "ShutterStrobeSlowFast": "Strobe",
    "ShutterOpen":           "Strobe",
    "ShutterClose":          "Strobe",
    "PositionPan":           "Pan",
    "PositionPanFine":       "PanFine",
    "PositionTilt":          "Tilt",
    "PositionTiltFine":      "TiltFine",
    "ColorMacro":            "ColorWheel",
    "GoboWheel":             "Gobo1",
    "GoboIndex":             "GoboRot",
    "GoboIndexFine":         "GoboRot",
    "GoboShakeFastSlow":     "GoboRot",
    "PrismRotationFastSlow": "PrismRot",
    "SpeedPanTiltFastSlow":  "Speed",
    "BeamFocusNearFar":      "Focus",
    "BeamZoomSmallBig":      "Zoom",
    "BeamIrisFastSlow":      "Iris",
    "NoFunction":            "Mode",
}

_GROUP_MAP = {
    "Red":         "R",
    "Green":       "G",
    "Blue":        "B",
    "White":       "W",
    "Amber":       "A",
    "UV":          "UV",
    "Cyan":        "C",
    "Magenta":     "M",
    "Yellow":      "Y",
    "Lime":        "Lime",
    "Intensity":   "Dim",
    "Shutter":     "Strobe",
    "Pan":         "Pan",
    "Tilt":        "Tilt",
    "Colour":      "ColorWheel",
    "Gobo":        "Gobo1",
    "Speed":       "Speed",
    "Prism":       "Prism",
    "Effect":      "Effect",
    "Focus":       "Focus",
    "Zoom":        "Zoom",
    "Iris":        "Iris",
    "Maintenance": "Mode",
    "Nothing":     "Mode",
    "Fan":         "Fan",
}

_TYPE_MAP = {
    "Moving Head":    "Moving Head",
    "Scanner":        "Moving Head",
    "Color Changer":  "PAR LED",
    "LED Bar (Beams)":"Barre LED",
    "LED Bar (Pixels)":"Barre LED",
    "Strobe":         "Stroboscope",
    "Smoke":          "Machine a fumee",
    "Hazer":          "Machine a fumee",
    "Dimmer":         "Gradateur",
    "Flower":         "Effet",
    "Effect":         "Effet",
    "Laser":          "Laser",
    "Other":          "PAR LED",
}


def _ch_name_to_mystrow(ch_name: str, preset: str, group: str, byte: str) -> str:
    """Convertit un canal QLC+ en nom MyStrow."""
    if byte == "1":          # canal fin (16-bit fine)
        return None          # on saute les canaux fins pour simplifier

    # 1. Preset explicite
    if preset and preset in _PRESET_MAP:
        return _PRESET_MAP[preset]

    # 2. Groupe XML
    if group and group in _GROUP_MAP:
        mapped = _GROUP_MAP[group]
        # Si groupe = Intensity sans preset, regarder le nom pour R/G/B
        if mapped == "Dim":
            n = ch_name.lower()
            if "red"    in n: return "R"
            if "green"  in n: return "G"
            if "blue"   in n: return "B"
            if "white"  in n: return "W"
            if "amber"  in n: return "A"
            if "uv"     in n or "ultra" in n: return "UV"
        return mapped

    # 3. Heuristique sur le nom
    n = ch_name.lower()
    for kw, val in [("red","R"),("green","G"),("blue","B"),("white","W"),
                    ("amber","A"),("uv","UV"),("dim","Dim"),("master","Dim"),
                    ("intensity","Dim"),("strobe","Strobe"),("shutter","Strobe"),
                    ("pan","Pan"),("tilt","Tilt"),("gobo","Gobo1"),
                    ("colour","ColorWheel"),("color","ColorWheel"),
                    ("speed","Speed"),("prism","Prism"),("zoom","Zoom"),
                    ("focus","Focus"),("iris","Iris"),("effect","Effect")]:
        if kw in n:
            return val

    return "Mode"   # canal de maintenance/mode sans intérêt direct


def parse_qxf(path: str) -> dict | None:
    """Retourne un dict fixture ou None si le fichier est invalide."""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        ns = {"q": "http://www.qlcplus.org/FixtureDefinition"}

        def find(tag):
            el = root.find(f"q:{tag}", ns)
            return el.text.strip() if el is not None and el.text else ""

        manufacturer = find("Manufacturer")
        model        = find("Model")
        qtype        = find("Type")
        if not manufacturer or not model:
            return None

        fixture_type = _TYPE_MAP.get(qtype, "PAR LED")

        # ── Canaux : nom → nom MyStrow ────────────────────────────────────
        ch_map = {}  # ch_name → mystrow_name
        for ch_el in root.findall("q:Channel", ns):
            ch_name = ch_el.get("Name", "")
            preset  = ch_el.get("Preset", "")
            grp_el  = ch_el.find("q:Group", ns)
            group   = grp_el.text.strip() if grp_el is not None and grp_el.text else ""
            byte    = grp_el.get("Byte", "0") if grp_el is not None else "0"
            mystrow = _ch_name_to_mystrow(ch_name, preset, group, byte)
            if mystrow is not None:
                ch_map[ch_name] = mystrow

            # Color wheel slots
            # (on collecte dans le premier mode qui a un ColorWheel)

        # ── Modes ──────────────────────────────────────────────────────────
        modes = []
        for mode_el in root.findall("q:Mode", ns):
            mode_name = mode_el.get("Name", "")
            channels = []
            for c_el in mode_el.findall("q:Channel", ns):
                cname = c_el.text.strip() if c_el.text else ""
                channels.append(ch_map.get(cname, "Mode"))
            if channels:
                modes.append({
                    "name":         mode_name,
                    "channels":     channels,
                    "num_channels": len(channels),
                })

        if not modes:
            return None

        # Données physiques (pan/tilt range pour moving heads)
        phys = root.find("q:Physical", ns)
        pan_max = tilt_max = 0
        if phys is not None:
            focus = phys.find("q:Focus", ns)
            if focus is not None:
                pan_max  = int(focus.get("PanMax",  0) or 0)
                tilt_max = int(focus.get("TiltMax", 0) or 0)

        out = {
            "manufacturer": manufacturer,
            "model":        model,
            "fixture_type": fixture_type,
            "modes":        modes,
        }
        if pan_max:  out["pan_max"]  = pan_max
        if tilt_max: out["tilt_max"] = tilt_max
        return out

    except Exception:
        return None


def run(qlc_path: str, out_path: str):
    fixtures_dir = os.path.join(qlc_path, "resources", "fixtures")
    if not os.path.isdir(fixtures_dir):
        print(f"Dossier introuvable : {fixtures_dir}")
        sys.exit(1)

    qxf_files = []
    for root_dir, _, files in os.walk(fixtures_dir):
        for f in files:
            if f.endswith(".qxf"):
                qxf_files.append(os.path.join(root_dir, f))

    print(f"Parsing {len(qxf_files)} fichiers QXF...")
    results = []
    errors  = 0
    for path in sorted(qxf_files):
        fx = parse_qxf(path)
        if fx:
            results.append(fx)
        else:
            errors += 1

    # Tri : par manufacturer + model
    results.sort(key=lambda x: (x["manufacturer"].lower(), x["model"].lower()))

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, separators=(",", ":"))

    print(f"OK : {len(results)} fixtures -> {out_path}  ({errors} skipped)")
    size_kb = os.path.getsize(out_path) // 1024
    print(f"Taille fichier : {size_kb} KB")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--qlcpath", default="C:/Users/nikop/Desktop/qlcplus_tmp")
    p.add_argument("--out",     default=os.path.join(os.path.dirname(__file__), "..", "fixtures_qlcplus.json"))
    args = p.parse_args()
    run(args.qlcpath, os.path.abspath(args.out))
