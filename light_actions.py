"""
light_actions.py — Commandes lumière de haut niveau, partagées.

Un seul endroit pour « allumer en rouge », « noir », « effet rapide »… quel
que soit le pupitre distant qui le demande : l'API locale (Stream Deck,
assistant IA via MCP) et l'assistant intégré (onglet à côté du Journal).
Tout s'exécute dans le thread Qt, sur la fenêtre principale `w`.

Les couleurs et niveaux passent par `_apply_tablet_event` : même rendu que la
tablette, lyres à roue de couleurs comprises.
"""

# Appareils qui ne sont pas « des lumières » : exclus d'un « allume tout ».
_NOT_A_LIGHT = ("fum", "brouill", "smoke", "fog", "haze", "machine",
                "etincel", "étincel", "flamme", "confetti")

# Lettres affichées dans MyStrow (cf. GROUP_LETTERS de main_window).
GROUP_LETTERS = {
    "face": "A", "lat": "B", "contre": "C",
    "douche1": "D", "douche2": "E", "douche3": "F",
    "groupe_g": "G", "groupe_h": "H",
    "public": "Public", "fumee": "Fumée", "lyre": "Lyres", "barre": "Barres", "strobe": "Strobos",
}

# Familles d'appareils reconnues par l'assistant → test sur groupe/type.
_KINDS = {
    "lyre":   lambda p: p.group == "lyre" or "moving" in _ftype(p) or "lyre" in _ftype(p),
    "par":    lambda p: "par" in _ftype(p),
    "barre":  lambda p: p.group == "barre" or "barre" in _ftype(p) or "bar" in _ftype(p),
    "strobe": lambda p: p.group == "strobe" or "strob" in _ftype(p),
    "laser":  lambda p: "laser" in _ftype(p),
    "douche": lambda p: p.group.startswith("douche"),
    "fumee":  lambda p: not is_light(p),
    "etincelle": lambda p: any(k in _ftype(p) for k in ("etincel", "étincel", "spark", "flamme", "confetti")),
}


def _ftype(p) -> str:
    return str(getattr(p, "fixture_type", "") or "").lower()


def is_light(p) -> bool:
    t = _ftype(p)
    return not any(k in t for k in _NOT_A_LIGHT)


def group_letter(key: str) -> str:
    if key in GROUP_LETTERS:
        return GROUP_LETTERS[key]
    if key.startswith("groupe_") and len(key) == 8:
        return key[-1].upper()
    return key


def resolve(w, group: str = None, kind: str = None, idxs=None) -> list:
    """Indices des projecteurs visés. Sans critère : toutes les lumières."""
    projs = list(w.projectors)
    if idxs is not None:
        return [i for i in idxs if 0 <= i < len(projs)]
    if group:
        g = group.lower()
        return [i for i, p in enumerate(projs)
                if p.group.lower() == g or group_letter(p.group).lower() == g]
    if kind:
        test = _KINDS.get(kind)
        return [i for i, p in enumerate(projs) if test and test(p)]
    return [i for i, p in enumerate(projs) if is_light(p)]


def groups_present(w) -> list:
    seen = []
    for p in w.projectors:
        g = group_letter(p.group)
        if g not in seen:
            seen.append(g)
    return seen


def set_color(w, idxs: list, hex_color: str, level: int = 100):
    _cancel_fades(idxs)
    w._apply_tablet_event({"type": "proj_color", "idxs": idxs, "color": hex_color})
    w._apply_tablet_event({"type": "proj_level", "idxs": idxs, "value": int(level)})


def set_level(w, idxs: list, level: int):
    _cancel_fades(idxs)
    w._apply_tablet_event({"type": "proj_level", "idxs": idxs, "value": int(level)})


# ── Fondus (« allume progressivement », « éteins en 10 secondes ») ───────────
# Un seul minuteur pour tous les fondus en cours : {idx: (départ, arrivée, t0, durée)}.
_FADE_STEP_MS = 40
_fades = {}
_fade_timer = None


def _cancel_fades(idxs=None):
    if idxs is None:
        _fades.clear()
    else:
        for i in idxs:
            _fades.pop(i, None)


def fade_to(w, idxs: list, level: int, seconds: float, hex_color: str = None):
    """Amène les projecteurs à `level` en `seconds` ; la couleur, s'il y en a
    une, est posée tout de suite (sans saut de niveau)."""
    import time
    starts = {i: int(w.projectors[i].level) for i in idxs}
    if hex_color:
        _cancel_fades(idxs)
        w._apply_tablet_event({"type": "proj_color", "idxs": idxs, "color": hex_color})
        # Poser une couleur rallume à 100 % un projecteur à 0 : on le remet à son niveau de départ.
        for i, v in starts.items():
            w._apply_tablet_event({"type": "proj_level", "idxs": [i], "value": v})
    t0 = time.monotonic()
    for i, v in starts.items():
        _fades[i] = (v, int(level), t0, max(0.1, float(seconds)))
    _ensure_fade_timer(w)


def _ensure_fade_timer(w):
    import time
    from PySide6.QtCore import QTimer
    global _fade_timer
    if _fade_timer is None:
        _fade_timer = QTimer()
        _fade_timer.setInterval(_FADE_STEP_MS)

        def tick():
            now = time.monotonic()
            by_value = {}
            for i, (a, b, start, dur) in list(_fades.items()):
                k = min(1.0, (now - start) / dur)
                by_value.setdefault(round(a + (b - a) * k), []).append(i)
                if k >= 1.0:
                    del _fades[i]
            for v, ids in by_value.items():
                projs = [i for i in ids if isinstance(i, int)]
                if projs:
                    w._apply_tablet_event({"type": "proj_level", "idxs": projs, "value": v})
                for key in ids:
                    if not isinstance(key, int):      # ("fader", n)
                        _set_fader(w, key[1], v)
            if not _fades:
                _fade_timer.stop()
        _fade_timer.timeout.connect(tick)
    if not _fade_timer.isActive():
        _fade_timer.start()


def adjust_level(w, idxs: list, delta: int) -> int:
    """Monte ou baisse l'intensité ; rend le niveau moyen obtenu."""
    out = []
    for i in idxs:
        v = max(0, min(100, int(w.projectors[i].level) + delta))
        set_level(w, [i], v)
        out.append(v)
    return round(sum(out) / len(out)) if out else 0


def fader_value(w, n: int) -> int:
    """Valeur (0-100) du fader n (0 = premier ; 8 = vitesse des effets)."""
    f = getattr(w, "faders", {}).get(n)
    return int(getattr(f, "value", 0) or 0)


def _set_fader(w, n: int, value: int):
    """Bouge le fader n à l'écran et applique son effet, comme le fader physique."""
    value = max(0, min(100, int(value)))
    if n == 8:
        set_speed(w, value)
        return
    if n in w.faders:
        w.faders[n].value = value
        w.faders[n].update()
    w.set_proj_level(n, value)
    try:
        import tablet_server as _ts
        if _ts.is_running():
            _ts.push_fader(n, value)
    except Exception:
        pass


def set_faders(w, nums: list, value: int, seconds: float = 0):
    """Faders 0-8 à `value`, d'un coup ou en fondu."""
    import time
    keys = [("fader", n) for n in nums]
    _cancel_fades(keys)
    if not seconds:
        for n in nums:
            _set_fader(w, n, value)
        return
    t0 = time.monotonic()
    for n, key in zip(nums, keys):
        _fades[key] = (fader_value(w, n), int(value), t0, max(0.1, float(seconds)))
    _ensure_fade_timer(w)


def gradient(w, idxs: list, hexes: list, level: int = 100):
    """Dégradé de la 1re à la dernière couleur, de gauche à droite de la scène
    (position sur le plan de feu, sinon ordre du patch)."""
    from PySide6.QtGui import QColor
    _cancel_fades(idxs)
    order = sorted(idxs, key=lambda i: (getattr(w.projectors[i], "canvas_x", None) is None,
                                        getattr(w.projectors[i], "canvas_x", None) or 0, i))
    stops = [QColor(h) for h in hexes]
    n = len(order)
    for k, i in enumerate(order):
        pos = k / (n - 1) if n > 1 else 0.0
        seg = min(len(stops) - 2, int(pos * (len(stops) - 1))) if len(stops) > 1 else 0
        a, b = stops[seg], stops[min(seg + 1, len(stops) - 1)]
        f = pos * (len(stops) - 1) - seg if len(stops) > 1 else 0.0
        c = QColor(round(a.red() + (b.red() - a.red()) * f), round(a.green() + (b.green() - a.green()) * f),
                   round(a.blue() + (b.blue() - a.blue()) * f))
        w._apply_tablet_event({"type": "proj_color", "idxs": [i], "color": c.name()})
    w._apply_tablet_event({"type": "proj_level", "idxs": order, "value": int(level)})


def change_gobo(w, idxs: list, open_: bool = False) -> int:
    """Gobo suivant sur les appareils qui en ont (« change les gobos »), ou gobo
    ouvert. Rend le nombre d'appareils touchés."""
    from core import fixture_projects_gobo, gobo_slot_index, gobo_slot_dmx, GOBO_SLOT_COUNT
    done = 0
    for i in idxs:
        p = w.projectors[i]
        if not fixture_projects_gobo(p):
            continue
        if open_:
            val = 0
        else:
            slots = sorted(int(s["dmx"]) for s in (getattr(p, "gobo_wheel_slots", None) or [])
                           if isinstance(s, dict) and str(s.get("dmx", "")).isdigit())
            cur = int(getattr(p, "gobo", 0) or 0)
            if slots:       # vraie roue calibrée : cran suivant, en boucle
                val = next((d for d in slots if d > cur), slots[0])
            else:
                val = gobo_slot_dmx((gobo_slot_index(cur) + 1) % GOBO_SLOT_COUNT)
        w._apply_tablet_event({"type": "proj_gobo", "idxs": [i], "value": val})
        done += 1
    return done


# ── Position des lyres (« les lyres en l'air », « au sol », « vers le public ») ─
# Directions dans le repère du plan 3D : Y vers le haut, public du côté des Z
# NÉGATIFS (la caméra de salle regarde vers les Z croissants).
AIM_DIRS = {"up": (0.0, 1.0, 0.0), "down": (0.0, -1.0, 0.0), "public": (0.0, -0.25, -1.0)}

# Mots d'un nom de position enregistrée (REC position) qui disent la même chose :
# la position calée par l'utilisateur sur ses vraies lyres passe avant le calcul.
_AIM_PRESET_WORDS = {
    "up": "plafond ciel air haut up ceiling sky techo cielo arriba decke himmel oben luft teto ceu cima",
    "down": "sol terre bas floor ground down suelo piso abajo boden unten chao baixo",
    "public": "public salle audience crowd publico publikum plateia face front",
    "center": "centre center repos neutre home centro mitte neutral",
}


def is_movable(p) -> bool:
    return _KINDS["lyre"](p)


def beam_dir(p, pan: int, tilt: int):
    """Direction du faisceau (x, y, z) pour ces pan/tilt : même chaîne que
    `beamFloor()` du plan 3D (débattement, accroche RX/RY/RZ), pour que la lyre
    vise là où la 3D la montre."""
    import math
    from core import pan_tilt_ranges
    pan_deg, tilt_deg = pan_tilt_ranges(p)
    a_pan = -(pan - 32768) / 32768.0 * math.radians(pan_deg / 2.0)
    theta = (32768 - tilt) / 32768.0 * math.radians(tilt_deg / 2.0)
    rx = math.radians(float(getattr(p, "rot3d_x", 0.0) or 0.0))
    ry = math.radians(float(getattr(p, "body_rotation", 0.0) or 0.0))
    rz = math.radians(float(getattr(p, "rot3d_z", 0.0) or 0.0))
    x, y, z = 0.0, -math.cos(theta), math.sin(theta)
    x1, z1 = x * math.cos(a_pan) + z * math.sin(a_pan), -x * math.sin(a_pan) + z * math.cos(a_pan)
    x2, y2 = x1 * math.cos(rz) - y * math.sin(rz), x1 * math.sin(rz) + y * math.cos(rz)
    x3, z3 = x2 * math.cos(ry) + z1 * math.sin(ry), -x2 * math.sin(ry) + z1 * math.cos(ry)
    return x3, y2 * math.cos(rx) - z3 * math.sin(rx), y2 * math.sin(rx) + z3 * math.cos(rx)


def aim_values(p, where: str):
    """(pan, tilt) qui pointent la lyre `where` (up/down/public/center), dans ses
    limites. Centre = milieu de course ; sinon recherche sur une grille, le pan
    le plus près du centre à visée égale (pas de demi-tour inutile)."""
    pmin, pmax = int(getattr(p, "pan_min", 0)), int(getattr(p, "pan_max", 65535))
    tmin, tmax = int(getattr(p, "tilt_min", 0)), int(getattr(p, "tilt_max", 65535))
    if where == "center":
        return max(pmin, min(pmax, 32768)), max(tmin, min(tmax, 32768))
    gx, gy, gz = AIM_DIRS[where]
    norm = (gx * gx + gy * gy + gz * gz) ** 0.5
    gx, gy, gz = gx / norm, gy / norm, gz / norm
    pans = sorted(set([max(pmin, min(pmax, 32768))] + list(range(pmin, pmax + 1, 2048)) + [pmax]))
    tilts = sorted(set([max(tmin, min(tmax, 32768))] + list(range(tmin, tmax + 1, 512)) + [tmax]))
    best, best_key = None, None
    for pan in pans:
        pan_cost = 0.05 * abs(pan - 32768) / 32768.0      # un demi-tour de pan pour presque rien : non
        for tilt in tilts:
            dx, dy, dz = beam_dir(p, pan, tilt)
            # Visée d'abord ; à visée égale, le moins de mouvement ; puis, entre les
            # deux butées d'une lyre accrochée qui monte, le côté scène (+Z) plutôt
            # que dans les yeux du public.
            key = (round(pan_cost - (dx * gx + dy * gy + dz * gz), 3), round(abs(tilt - 32767.5)), round(-dz, 3))
            if best_key is None or key < best_key:
                best, best_key = (pan, tilt), key
    return best


def _aim_preset(w, where: str):
    """Position enregistrée dont le nom dit `where` (« Sol », « Plafond »…), ou None."""
    import re
    words = set(_AIM_PRESET_WORDS[where].split())
    for preset in getattr(w, "position_presets", None) or []:
        name = re.sub(r"[^a-z]+", " ", _strip_accents(str(preset.get("name", "")).lower())).split()
        if words & set(name):
            return preset
    return None


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def aim(w, idxs: list, where: str, ms: int = 800):
    """Oriente les lyres parmi `idxs`. Rend (nombre de lyres, nom de la position
    enregistrée utilisée ou None). Pris en main comme depuis la tablette : la
    restitution d'une mémoire ne les ramène pas ailleurs jusqu'au CLEAR."""
    from core import position_preset_values
    lyres = [w.projectors[i] for i in idxs if is_movable(w.projectors[i])]
    preset = _aim_preset(w, where)
    cibles = {}
    if preset:
        tout = [p for p in w.projectors if getattr(p, "fixture_type", "") in ("Moving Head", "Lyre", "Laser")]
        cibles = position_preset_values(preset, tout)
    used = False
    for p in lyres:
        pt = cibles.get(id(p))
        used = used or bool(pt)
        pan, tilt = pt if pt else aim_values(p, where)
        p._manual_move = True
        w._start_pan_tilt_transition(p, int(pan), int(tilt), ms)
    return len(lyres), (preset.get("name") if preset and used else None)


def set_live(w, on: bool) -> bool:
    """Mode LIVE (les lumières suivent le son de la carte son / du micro)."""
    btn = getattr(getattr(w, "seq", None), "live_btn", None)
    if btn is None:
        return False
    if btn.isChecked() != on:
        btn.setChecked(on)
    return True


def blackout(w):
    _cancel_fades()
    w.full_blackout()


def all_effects() -> list:
    from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
    return list(BUILTIN_EFFECTS) + _load_custom_effects()


def fire_effect(w, name: str, everywhere: bool = False) -> bool:
    """`everywhere` : toutes les couches visent tous les projecteurs (« que ça prenne
    sur tous les projos »), sur une copie : l'effet enregistré ne change pas."""
    cfg = next((e for e in all_effects() if e.get("name") == name), None)
    if cfg is None:
        return False
    if everywhere:
        import copy
        cfg = copy.deepcopy(cfg)
        for layer in cfg.get("layers") or []:
            if isinstance(layer, dict):
                layer["target_preset"] = "Tous"
    w.active_effect = name
    w.active_effect_config = cfg
    w.start_effect(name)
    return True


def stop_effects(w):
    """Coupe les boutons d'effet actifs par leur propre bascule, puis un effet
    lancé par son nom (sans bouton) s'il en reste un."""
    for i, btn in enumerate(w.effect_buttons):
        if btn.active:
            w.toggle_effect(i)
    if w.active_effect is not None:
        w.stop_effect()
        w.active_effect = None


def set_speed(w, value: int):
    value = max(0, min(100, int(value)))
    w._fader8_dispatch(8, value)
    if 8 in w.faders:
        w.faders[8].value = value
        w.faders[8].update()
    return value
