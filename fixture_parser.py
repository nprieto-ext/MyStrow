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
    "Gobo 2 Rotation": "Gobo2Rot",
    "Prism":           "Prism",
    "Prism Rotation":  "PrismRot",
    "Frost":           "Frost",
    "Animation":       "Anim",
    "Animation Wheel": "Anim",
    "Animation Rotation": "AnimRot",
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
    # Frost / roue d'animation. Ces attributs existent en toutes lettres dans
    # les fichiers constructeur (l'ACME PIXEL LINE porte FROST sur son CH5) et
    # tombaient sur « Unused » faute de type d'accueil — donc muets à jamais.
    "FROST":              "Frost",
    "FROST1":             "Frost",
    "ANIMATIONWHEEL":     "Anim",
    "ANIMATIONINDEXROTATE": "AnimRot",
    "ANIMATIONWHEELPOS":  "AnimRot",
    "GOBO2_POS":          "Gobo2Rot",
    "GOBO2INDEXROTATE":   "Gobo2Rot",
    # Color wheel
    "COLOR1":             "ColorWheel",
    # ⚠️ COLOR2 reste sur ColorWheel et NON sur ColorWheel2 : les fixtures déjà
    # importées le pilotent par `proj.color_wheel`, le basculer sur un canal
    # manuel rendrait leur deuxième roue muette. ColorWheel2 est là pour qui le
    # choisit dans l'éditeur.
    "COLOR2":             "ColorWheel",
    "COLORWHEEL":         "ColorWheel",
    "CTOMIXER":           "CTO",
    "CTO":                "CTO",
    "CTB":                "CTB",
    "CTBMIXER":           "CTB",
    # Speed / control
    "POSITIONMSPEED":     "Speed",
    "SPEED":              "Speed",
    # Vitesse de déplacement pan/tilt : exactement ce que pilote « Speed » chez
    # MyStrow. Aucun préfixe de la table ne l'attrape (« SPEED » n'est pas au
    # début), d'où l'entrée explicite.
    "PT_SPEED":           "Speed",
    "PTSPEED":            "Speed",
    "CONTROL":            "Mode",
    "FUNCTION":           "Mode",
    "MACRO":              "Mode",
    "RESET":              "Reset",
    "FIXTURERESET":       "Reset",
    "FIXTUREGLOBALRESET": "Reset",
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
    """'White' / 'W1' / 'Warm White' / 'R-A' -> 'W' / 'W' / 'W' / 'R'.

    None si non reconnu.

    Le suffixe de SECTION est retiré en dernier recours : « R-A », « G-A »,
    « B-Ring » désignent le même émetteur sur une AUTRE zone du projecteur
    (couronne, halo, déco). Sans ça, la ring light RGB d'un wash n'était
    reconnue comme aucune couleur et tombait dans le repli du parseur.

    ⚠️ On ne retire ce suffixe QUE si ce qui reste est un nom d'émetteur connu :
    couper aveuglément le dernier mot ferait de « warm white » un « warm »
    inconnu, alors qu'il se résout très bien tel quel.
    """
    txt = re.sub(r"[\s_\-]+", " ", (raw or "").strip().lower())
    txt = re.sub(r"\s*\d+$", "", txt)          # « W1 », « White 2 » -> « w », « white »
    mapped = _EMITTER_NAMES.get(txt)
    if mapped:
        return mapped
    morceaux = txt.split()
    if len(morceaux) > 1:
        return _EMITTER_NAMES.get(" ".join(morceaux[:-1]))
    return None


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


# Noms « utilisateur » trop vagues pour servir de libellé : sur un laser, quatre
# canaux différents s'appellent « Select » et trois « Speed ». Quand on tombe
# dessus, l'attribut MA (LASERPATTERNSIZE…) est bien plus parlant.
_NOMS_VAGUES = {"select", "speed", "time", "value", "no feature", "dummy",
                "control", "function", "macro", "mode", "index", "", "-"}

# Découpage des attributs MA collés en majuscules. Les jetons sont essayés du
# plus long au plus court : sans ça « LASERPATTERNSIZE » donnerait
# « LASER PATTERN SIZE » seulement si SIZE passe après PATTERNSIZE.
_JETONS_MA = [
    "LASER", "PATTERN", "POSITION", "APERTURE", "APERTRURE", "GRADUAL",
    "DRAWING", "ROTATE", "EFFECT", "COLORMIX", "COLOR", "GROUP", "SPEED",
    "SIZE", "WAVES", "MACRO", "RATE", "MIXER", "SELECT", "AUX", "GOBO",
    "PRISM", "FOCUS", "ZOOM", "IRIS", "SHUTTER", "STROBE", "DIM", "PAN",
    "TILT", "FIXTURE", "GLOBAL", "RESET", "BACKGROUND", "COLOUR", "MAIN",
]


def _joli_attribut(attr: str) -> str:
    """« LASERPATTERNSIZE » -> « Laser Pattern Size ». Rend '' si illisible.

    Les attributs MA de matériel exotique (lasers surtout) sont écrits collés en
    majuscules. Recomposés en mots, ils font de très bons libellés — bien
    meilleurs que le type MyStrow, qui vaut « Unused » pour la moitié d'entre eux.
    """
    reste = (attr or "").upper().strip()
    if not reste:
        return ""
    mots, garde = [], 0
    while reste and garde < 12:
        garde += 1
        for jeton in sorted(_JETONS_MA, key=len, reverse=True):
            if reste.startswith(jeton):
                mots.append(jeton.capitalize())
                reste = reste[len(jeton):]
                break
        else:
            # Reliquat non reconnu : un axe (X/Y/Z), un numéro, ou un mot
            # inconnu. On le garde tel quel plutôt que de perdre l'information.
            mots.append(reste.capitalize() if len(reste) > 1 else reste)
            reste = ""
    return " ".join(m for m in mots if m)


def _libelle_canal(ct, attr: str) -> str:
    """Nom lisible d'un canal, depuis ce que le fichier constructeur porte.

    Priorité au nom écrit par l'auteur du fichier (`subattribute_user_name` et
    consorts) — c'est lui qui parle la langue de la fiche technique. On ne
    retombe sur l'attribut recomposé que lorsque ce nom est un mot passe-partout.
    """
    for src in (ct, *ct.findall("ChannelFunction")):
        for cle in ("subattribute_user_name", "attribute_user_name", "name"):
            v = (src.get(cle) or "").strip()
            if v and v.lower() not in _NOMS_VAGUES:
                return v
    return _joli_attribut(attr)


# ---------------------------------------------------------------------------
# Repli par LIBELLÉ — quand l'attribut du fichier ne dit rien
# ---------------------------------------------------------------------------
# Les tables ci-dessus traduisent l'ATTRIBUT du fichier constructeur. Quand le
# fabricant sort du vocabulaire GrandMA — ce que font tous les chinois sur leur
# couronne LED — l'attribut n'est mappé nulle part et le canal tombe en
# « Unused », donc muet à jamais. Le NOM du canal, lui, dit tout : sur un
# BETOPPER LM120, les dix canaux inconnus s'appellent « Light strip »,
# « Light strip strobe », « Light reddish », « Strip Speed »… c'est la couronne
# en toutes lettres, et MyStrow a les types qu'il faut depuis `RingDim` & co.
#
# Ce repli n'intervient QU'APRÈS l'attribut : il ne peut donc jamais dégrader un
# canal correctement typé, seulement rattraper un « Unused ».
_MOTS_RING    = ("strip", "ring", "halo", "aura", "corona", "couronne", "crown")
_MOTS_VITESSE = ("speed", "rate", "vitesse")
_MOTS_STROBE  = ("strobe", "strob", "flash")
_MOTS_EFFET   = ("effect", "effects", "effet", "fx", "program", "programme",
                 "prog", "auto", "macro", "show")
_MOTS_DIM     = ("dimmer", "dim", "intensity", "intensite", "brightness",
                 "master", "luminosite")
_MOTS_COULEUR = (
    (("red", "reddish", "rouge"), "R"),
    (("green", "vert"),           "G"),
    (("blue", "bleu"),            "B"),
    (("white", "blanc"),          "W"),
)
_RING_EQUIV = {
    "R": "RingR", "G": "RingG", "B": "RingB", "W": "RingW",
    "Dim": "RingDim", "Strobe": "RingStrobe", "Speed": "RingSpeed",
    "Effects": "RingFX", "ColorWheel": "RingFX",
}


def _type_depuis_libelle(libelle: str, deja: set) -> str | None:
    """Type de canal déduit du NOM du canal. `None` = on ne devine rien.

    `deja` : les types déjà posés dans ce mode. Il sert au seul cas ambigu —
    un mot de couleur sans mot de couronne (« Light reddish ») — pour trancher
    entre le faisceau et la deuxième source.

    Règle de conduite : dans le doute, rendre `None`. Un canal « Unused » ne
    sort que des zéros et se voit dans l'éditeur ; un canal MAL typé, lui, part
    en sortie et fait n'importe quoi sans qu'on sache pourquoi.
    """
    jeu = set(re.sub(r"[^a-z0-9]+", " ", (libelle or "").lower()).split())
    if not jeu:
        return None
    a = lambda *cles: any(c in jeu for c in cles)

    ring = a(*_MOTS_RING)

    # Ordre imposé par les noms composés : « Effect Speed » est une VITESSE,
    # « Light strip strobe » un STROBE. Le mot le plus spécifique gagne, sinon
    # le premier mot du libellé déciderait de tout.
    if a(*_MOTS_VITESSE):
        base = "Speed"
    elif a(*_MOTS_STROBE):
        base = "Strobe"
    elif not ring and a("macro") and a("colour", "color", "couleur"):
        base = "ColorWheel"      # « Colour Macro » = roue/macro de couleurs
    elif a(*_MOTS_EFFET):
        base = "Effects"
    else:
        base = None
        for cles, t in _MOTS_COULEUR:
            if a(*cles):
                base = t
                break
        if base is None and a(*_MOTS_DIM):
            base = "Dim"

    if ring:
        # « Light strip » tout court = le dimmer de la couronne.
        return _RING_EQUIV.get(base) or "RingDim"

    if base in ("R", "G", "B", "W"):
        # Couleur SANS mot de couronne. On ne l'accepte que si le faisceau a
        # déjà sa couleur (donc celle-ci est une AUTRE source) ET qu'un canal de
        # couronne a déjà été reconnu dans ce mode. Sans ces deux garde-fous on
        # écrirait un rouge de faisceau par-dessus un canal quelconque.
        if base in deja and any(t.startswith("Ring") for t in deja):
            return _RING_EQUIV[base]
        return None

    if base in deja:
        # Ce type est déjà pris dans ce mode. Le moteur GANGE les canaux de même
        # type sur un scalaire unique (`proj.speed`, `proj.mode_value`…) : poser
        # un second « Speed » ferait bouger la vitesse des effets en réglant
        # celle du pan/tilt. On laisse « Unused » — le libellé, lui, est
        # conservé, et le canal reste joignable par son NUMÉRO dans les canaux
        # avancés. Une déduction n'est pas assez sûre pour valoir un gangage.
        return None

    return base


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
        profile, channel_defaults, labels = _parse_ma3_channels(channel_types)
        sections = detect_sections({
            "modules":  fixture_el.findall(".//Module"),
            "channels": channel_types,
        })
        if profile:
            modes.append({
                "name":         mode_name,
                "channelCount": len(profile),
                "profile":      profile,
                # Sections de couleur détectées (couronne, LED déco, cellules).
                # Absente quand l'appareil n'en a qu'une — c'est le cas courant,
                # et une fixture à section unique ne doit surtout pas être
                # dépliée en projecteurs enfants.
                **({"sections": sections} if sections else {}),
                # Noms lisibles portés par le fichier constructeur. C'est la
                # seule information qui distingue deux canaux du même type — et
                # sur un laser, la seule qui distingue tout court, la moitié des
                # canaux n'ayant pas de type connu.
                "labels":       labels,
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
        profile, labels = _parse_ma_channels(mode_el)
        modes.append({
            "name":         mode_name,
            "channelCount": len(profile),
            "profile":      profile,
            "labels":       labels,
        })

    if not modes:
        profile, labels = _parse_ma_channels(fixture_el)
        if profile:
            modes.append({
                "name":         "Mode 1",
                "channelCount": len(profile),
                "profile":      profile,
                "labels":       labels,
            })
    return modes, channel_defaults


def _parse_ma3_channels(channel_type_elements) -> tuple:
    """
    Parse MA3 <ChannelType attribute='...' coarse='...'> elements.
    Retourne (profile_list, channel_defaults_dict).
    Gère les canaux fine (PanFine/TiltFine).

    Le dict de défauts est TOUJOURS vide — voir la note dans la boucle. Il reste
    au retour parce que les appelants le propagent, et qu'il est alimenté
    ailleurs par des chemins où la notion a un sens.
    """
    items = []       # [(ch_index, ch_type, libelle)]
    defaults = {}    # {ch_type: dmx_8bit} — voir la note plus bas
    # Types déjà posés dans ce mode — lu par le repli sur le libellé, qui a
    # besoin de savoir si le faisceau a déjà sa couleur pour trancher entre
    # « le rouge du projecteur » et « le rouge de la couronne ».
    deja_poses = set()

    for ct in channel_type_elements:
        attr   = (ct.get("attribute") or ct.get("Attribute") or "").upper().strip()
        coarse = ct.get("coarse") or ct.get("Coarse")
        fine   = ct.get("fine")   or ct.get("Fine")
        libelle = _libelle_canal(ct, attr)

        # ⚠️ Un ChannelType SANS `coarse` ne correspond à aucun canal DMX de ce
        # mode : il est écarté, pas rangé au canal 0.
        #
        # Les fichiers de barres pixel déclarent un module par cellule et y
        # laissent des ChannelType sans offset. Sur l'ACME PIXEL LINE IP
        # (49 modules), 48 des 165 ChannelType sont dans ce cas : tous
        # atterrissaient à l'index 0, s'entassaient en tête du profil et
        # DÉCALAIENT les 117 vrais canaux. La fixture sortait à 165 canaux au
        # lieu des 117 annoncés par son propre mode — donc un patch qui mord sur
        # la fixture suivante et des sorties fausses d'un bout à l'autre.
        if coarse is None:
            continue
        try:
            ch_index = int(coarse)
        except ValueError:
            continue

        # Résolution du type de canal — la couleur déclarée prime sur le
        # numéro d'emitter (cf. _resolve_emitter)
        mapped = _resolve_emitter(ct) if _is_emitter_attr(attr, ct) else None
        if mapped is None:
            mapped = _MA3_ATTR_MAP.get(attr)
        if mapped is None:
            # Repli par préfixe.
            #
            # ⚠️ Le chiffre qui suit le préfixe ne veut pas dire la même chose
            # partout, et c'est tout l'enjeu :
            #   - sur un ÉMETTEUR, il EST l'identité — COLORRGB15 est le 15e
            #     émetteur, surtout pas COLORRGB1 (rouge). Il doit bloquer.
            #   - partout ailleurs, c'est un simple numéro de section :
            #     SHUTTER1/SHUTTER2 sont deux obturateurs, SPEED1 une vitesse.
            #     Les bloquer les envoyait en « Unused », donc sans automatisme,
            #     alors que leur fonction ne fait aucun doute.
            # Le garde-fou est donc réservé aux familles d'émetteurs.
            for key, val in _MA3_ATTR_MAP.items():
                if not attr.startswith(key):
                    continue
                suite = attr[len(key):len(key) + 1]
                if suite.isdigit() and key.startswith(("COLORRGB", "COLORADD")):
                    continue
                mapped = val
                break
        # Dernière chance avant l'abandon : le NOM du canal. Voir
        # `_type_depuis_libelle` — c'est ce qui récupère les couronnes LED, dont
        # l'attribut ne ressemble à rien mais dont le nom dit « Light strip ».
        if mapped is None:
            mapped = _type_depuis_libelle(libelle, deja_poses)

        # ⚠️ Repli NEUTRE, surtout pas « Mode ». Un attribut inconnu tombait
        # jusqu'ici sur « Mode », qui est tout sauf inoffensif : le moteur gange
        # les canaux de même type sur `proj.mode_value`, et sur beaucoup de
        # lyres ce canal porte les PROGRAMMES INTERNES. Une seule valeur de Mode
        # non nulle lançait donc le programme automatique de l'appareil — vécu
        # sur un Betopper LM1915R, dont la ring light RGB non reconnue se
        # retrouvait mappée en Mode aux côtés de ses canaux MODEL / MODEL-A.
        # « Unused » sort 0 en toutes circonstances, et se voit dans l'éditeur.
        ch_type = mapped if mapped else "Unused"
        deja_poses.add(ch_type)

        items.append((ch_index, ch_type, libelle))

        # Canal fine (PanFine / TiltFine)
        if fine is not None:
            fine_type = _FINE_MAP.get(ch_type)
            if fine_type:
                try:
                    fine_idx = int(fine)
                    items.append((fine_idx, fine_type,
                                  f"{libelle} (fin)" if libelle else ""))
                except ValueError:
                    pass

        # ⚠️ Le `default=` du fichier constructeur n'est PAS moissonné, et c'est
        # volontaire : les deux notions n'ont rien à voir.
        #
        #   - côté MA, `default=` est la valeur de REPOS de l'appareil, celle
        #     qu'il prend à l'allumage ;
        #   - côté MyStrow, `channel_defaults` est un PLANCHER, appliqué par le
        #     moteur chaque fois que le canal sortirait 0
        #     (`if ch_val == 0 and ch_type in _ch_defaults`).
        #
        # Confondre les deux cassait la couleur : le fichier Betopper porte
        # `default="255"` sur R1/G1/B1, ce qui produisait
        # {"R":255,"G":255,"B":255} — donc tout canal rouge/vert/bleu qui
        # devait sortir 0 était remonté à 255. Un rouge pur virait au blanc et
        # le noir devenait blanc plein : la fixture ne pouvait plus s'éteindre.
        #
        # Le dict est en plus indexé par TYPE et non par canal : une valeur lue
        # sur R1 s'appliquerait de toute façon à R2, R3 et à la ring.
        #
        # `channel_defaults` reste alimenté explicitement là où il a un sens
        # (éditeur de roue de couleurs, réglage manuel dans le patch).

    items.sort(key=lambda x: x[0])
    return [ch for _, ch, _lb in items], defaults, [lb for _, _, lb in items]


def _parse_ma_channels(parent_el) -> tuple:
    """Canaux d'un mode MA2. Retourne (profile, labels).

    Les `labels` sont les noms écrits par le constructeur. C'est la seule chose
    qui distingue deux canaux du même type, et la seule qui reste quand on n'a
    pas su typer : sans eux, l'utilisateur voit une colonne de « Unused » muets
    et ne peut même pas les corriger à la main. Le chemin MA3 les portait déjà.
    """
    profile, labels = [], []
    deja_poses = set()
    for ch_el in parent_el.findall("Channel"):
        ch_name = (ch_el.get("name") or ch_el.get("Name") or "")
        mapped  = _MA_MAP.get(ch_name)
        if mapped is None:
            ch_lower = ch_name.lower()
            for key, val in _MA_MAP.items():
                if key.lower() == ch_lower:
                    mapped = val
                    break
        if mapped is None:
            mapped = _type_depuis_libelle(ch_name, deja_poses)
        # Repli « Unused » et non « Mode », pour la raison expliquée dans
        # `_parse_ma3_channels` : « Mode » porte les PROGRAMMES INTERNES de
        # l'appareil, et tous les canaux inconnus se retrouvaient gangés dessus.
        # Un LM120-23CH sortait ainsi avec seize canaux « Mode » d'affilée.
        mapped = mapped or "Unused"
        deja_poses.add(mapped)
        profile.append(mapped)
        labels.append(ch_name)
    return profile, labels


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
        entree = {
            "name":         m.get("name", f"Mode {len(normalized)+1}"),
            "channelCount": m.get("channelCount", len(profile)),
            "profile":      profile,
        }
        # Libellés : recopiés tels quels, et seulement s'ils cadrent avec le
        # profil. Une liste plus courte ou plus longue décalerait les noms d'un
        # canal sur l'autre, ce qui est pire que pas de nom du tout.
        lb = m.get("labels")
        if isinstance(lb, list) and len(lb) == len(profile):
            entree["labels"] = list(lb)
        normalized.append(entree)

    first_profile = normalized[0]["profile"] if normalized else []
    ftype = obj.get("fixture_type") or _detect_fixture_type(first_profile)

    # Libellés posés à la racine par l'éditeur (ils décrivent le premier mode) :
    # les redescendre dans ce mode s'il n'en portait pas, sinon un .mystrow écrit
    # par l'éditeur reviendrait sans noms.
    if normalized and not normalized[0].get("labels"):
        _rl = obj.get("labels")
        if isinstance(_rl, list) and len(_rl) == len(first_profile):
            normalized[0]["labels"] = list(_rl)

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
        "labels":            (obj.get("labels")
                              if isinstance(obj.get("labels"), list)
                              and len(obj["labels"]) == len(first_profile) else []),
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
        # Noms de canaux du premier mode, recopiés à la racine : c'est ce que
        # lit le patch quand la fixture vient de la bibliothèque.
        "labels":            (fixture.get("labels")
                              or (fixture.get("modes") or [{}])[0].get("labels")
                              or []),
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
            # Le <Channel> QLC+ porte déjà un nom écrit pour un humain
            # (« Pattern Group », « Laser Rotation »…) : on le garde comme
            # libellé. C'est souvent la seule chose qui distingue deux canaux
            # que MyStrow ramène au même type.
            ch_entries.append((num, ch_type, ch_name))
        ch_entries.sort(key=lambda x: x[0])
        profile = [ct for _, ct, _n in ch_entries]
        if profile:
            modes.append({"name": mode_name, "channelCount": len(profile),
                          "profile": profile,
                          "labels": [n for _, _t, n in ch_entries]})

    if not modes and channel_table:
        # Pas de mode déclaré : utiliser tous les canaux dans l'ordre de déclaration
        profile = list(channel_table.values())
        modes = [{"name": "Mode 1", "channelCount": len(profile), "profile": profile,
                  "labels": list(channel_table.keys())}]

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


# ---------------------------------------------------------------------------
# Détection des SECTIONS d'un projecteur
# ---------------------------------------------------------------------------
#
# Un appareil moderne n'a plus une seule couleur : couronne (« ring »), LED de
# déco, cellules d'une barre pixel. Les fichiers constructeur le disent déjà,
# de deux façons — relevées sur quatre fichiers réels :
#
#   A) attributs NUMÉROTÉS sur un module unique
#      MX 19-rs      : RED, RED1, RED2, RED3…      (25 sections)
#      Betopper LM1915R : R1 R2 R3 puis R-A        (3 sections + la ring)
#   B) un MODULE par section, répétant les mêmes attributs
#      ACME PIXEL LINE : 49 modules, chacun COLORRGB1/2/3   (48 cellules)
#
# ⚠️ Le chiffre de `COLORRGB<n>` n'est PAS un numéro de section : c'est le n-ième
# ÉMETTEUR (1=R, 2=G, 3=B…). Confondre les deux ferait de R/G/B trois sections
# d'une seule couleur. C'est exactement la distinction déjà appliquée au repli
# par préfixe de `_parse_ma3_channels`.

_BASES_COULEUR = {"RED", "GREEN", "BLUE", "WHITE", "AMBER", "AMBRE", "UV",
                  "LIME", "CYAN", "MAGENTA", "YELLOW", "R", "G", "B", "W"}


def _base_et_section(attr: str):
    """« RED2 » → ('RED','2') ; « R-A » → ('R','A') ; « RED » → ('RED','').

    Rend (None, None) si l'attribut ne désigne pas un émetteur de couleur, ou
    s'il appartient à la famille COLORRGB — dont le suffixe est l'émetteur.
    """
    a = (attr or "").upper().strip()
    if not a or a.startswith(("COLORRGB", "COLORADD")):
        return None, None
    # Bases essayées de la PLUS LONGUE à la plus courte : sans cet ordre,
    # « RED » se ferait découper en « R » + « ED », et « WHITE1 » en « W » +
    # « HITE1 ». Une regex non gourmande fait la même erreur à l'envers
    # (« RED » → « RE » + « D »).
    for base in sorted(_BASES_COULEUR, key=len, reverse=True):
        if a == base:
            return base, ""
        if a.startswith(base):
            m = re.fullmatch(r"[\-_ ]?(\d+|[A-Z])", a[len(base):])
            if m:
                return base, m.group(1)
    return None, None


def detect_sections(channel_type_elements) -> list:
    """Sections de couleur déduites d'un fichier MA.

    Retourne une liste de dicts `{"name": str, "channels": [n° de canal]}`,
    triée par premier canal. Liste VIDE quand il n'y a qu'une section — le cas
    de l'immense majorité des projecteurs, qu'il ne faut surtout pas déplier.

    Deux indices, dans cet ordre :
      1. le MODULE d'appartenance, dès qu'il y en a plusieurs à porter de la
         couleur (école B) ;
      2. sinon le SUFFIXE de l'attribut (école A).
    """
    # ── Indice 1 : les modules ────────────────────────────────────────────────
    par_module = {}
    for mod in channel_type_elements.get("modules", []):
        nom = mod.get("name") or "?"
        for ct in mod.iter("ChannelType"):
            a = (ct.get("attribute") or "").upper()
            co = ct.get("coarse")
            if not co:
                continue
            if a.startswith(("COLORRGB", "COLORADD")) or _base_et_section(a)[0]:
                par_module.setdefault(nom, []).append(int(co))
    if len(par_module) > 1:
        return sorted(
            ({"name": n, "channels": sorted(c)} for n, c in par_module.items()),
            key=lambda s: s["channels"][0])

    # ── Indice 2 : le suffixe de l'attribut ───────────────────────────────────
    par_suffixe = {}
    for ct in channel_type_elements.get("channels", []):
        a = (ct.get("attribute") or "").upper()
        co = ct.get("coarse")
        if not co:
            continue
        base, suf = _base_et_section(a)
        if base is None:
            continue
        par_suffixe.setdefault(suf, []).append(int(co))
    if len(par_suffixe) > 1:
        sections = sorted(
            ({"name": f"Section {s or '1'}", "channels": sorted(c)}
             for s, c in par_suffixe.items()),
            key=lambda s: s["channels"][0])
        # ⚠️ Une section doit être un BLOC D'ADRESSES CONTIGU : c'est ce qu'un
        # projecteur enfant occupe. Sur la MX 19-rs, les blancs sont numérotés
        # indépendamment des RGB (WHITE1 est au canal 34, loin de RED1/GREEN1/
        # BLUE1 en 18-20) — le suffixe les regroupe donc à tort. Plutôt que de
        # découper de travers, on renonce : mieux vaut une fixture non découpée
        # qu'un découpage faux, que l'utilisateur ne pourrait pas deviner.
        for s in sections:
            ch = s["channels"]
            if ch[-1] - ch[0] + 1 != len(ch):
                return []
        return sections

    return []


def _remonter_labels(fx: dict) -> dict:
    """Recopie à la racine les noms de canaux du premier mode.

    Le patch lit la fixture à plat (`profile`, et maintenant `labels`) quand on
    l'ajoute depuis la bibliothèque, alors que les parseurs les rangent dans
    `modes`. Point unique, appliqué en sortie de tous les formats : sans lui, une
    fixture importée gardait ses noms dans son fichier mais arrivait anonyme
    dans le patch.
    """
    if not isinstance(fx, dict) or fx.get("labels"):
        return fx
    for m in (fx.get("modes") or []):
        lb = m.get("labels")
        if isinstance(lb, list) and lb and len(lb) == len(m.get("profile") or []):
            fx["labels"] = list(lb)
            break
    return fx


def parse_file(path: str) -> dict:
    """
    Parse automatiquement un fichier fixture selon son extension.
    Supporte : .xml, .mystrow
    Retourne le dict fixture standardise.
    """
    return _remonter_labels(_parse_file_brut(path))


def _parse_file_brut(path: str) -> dict:
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
