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


def blackout(w):
    _cancel_fades()
    w.full_blackout()


def all_effects() -> list:
    from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
    return list(BUILTIN_EFFECTS) + _load_custom_effects()


def fire_effect(w, name: str) -> bool:
    cfg = next((e for e in all_effects() if e.get("name") == name), None)
    if cfg is None:
        return False
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
