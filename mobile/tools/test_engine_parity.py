"""Parité du moteur DMX tablette (mobile/src/engine.js) avec celui du PC.

Fait tourner le VRAI moteur (ArtNetDMX._update_from_projectors_locked) et
engine.js sur les mêmes projecteurs, et compare les 512 octets. Un écart =
la tablette n'éclaire pas comme le PC.

Même chose pour les effets : chaque effet de mobile/src/effects.js passe par
le vrai MainWindow._update_effect_from_layers, à plusieurs instants de phase.

    python mobile/tools/test_engine_parity.py      (Node.js requis)
"""
import itertools
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

from PySide6.QtGui import QColor  # noqa: E402

from artnet_dmx import ArtNetDMX, DMX_PROFILES  # noqa: E402
from projector import Projector  # noqa: E402

PROFILES = ["RGB", "RGBD", "RGBDS", "RGBSD", "DRGB", "DRGBS", "RGBW", "RGBWD", "RGBWDS",
            "RGBWA", "RGBWAD", "DIM", "STROBE_2CH", "MOVING_RGB", "MOVING_RGBW", "MACMAH_IZY715Z"]
# Profils de fixtures précises : absents de DMX_PROFILES, recopiés de la bibliothèque.
PROFILE_DEFS = {**DMX_PROFILES,
                "MACMAH_IZY715Z": ["Pan", "Tilt", "Speed", "Dim", "Strobe", "R", "G", "B", "W",
                                   "Zoom", "Mode", "Mode", "Speed", "Reset"]}
COLORS = ["#ffffff", "#ff0000", "#ff8800", "#ffdd00", "#00ff00", "#00dddd", "#0000ff", "#ff00ff", "#000000", "#7f3a11"]
LEVELS = [0, 1, 37, 50, 99, 100]
STROBES = [0, 1, 50, 100]


def scenarios():
    """Un projecteur par cas, chacun à sa propre adresse (pas de chevauchement)."""
    cases = []
    for prof, color, level, strobe in itertools.product(PROFILES, COLORS, LEVELS, STROBES):
        cases.append({"profile": prof, "color": color, "level": level, "strobe": strobe, "muted": False})
    for prof in PROFILES:
        cases.append({"profile": prof, "color": "#ff0000", "level": 100, "strobe": 0, "muted": True})
    return cases


def python_frame(fixtures):
    dmx = ArtNetDMX()
    projs = []
    for i, f in enumerate(fixtures):
        p = Projector("A", name=f"P{i}")
        p.set_color(QColor(f["color"]), f["level"])
        p.muted = f["muted"]
        p.strobe_speed = f["strobe"]
        projs.append(p)
        n = len(PROFILE_DEFS[f["profile"]])
        dmx.set_projector_patch(f"A_{i}", list(range(f["address"], f["address"] + n)),
                                profile=list(PROFILE_DEFS[f["profile"]]))
    dmx.update_from_projectors(projs)
    return list(dmx.dmx_data[0][:512])


def run_node(script, payload):
    return json.loads(subprocess.run(
        ["node", "-e", script, os.path.join(REPO, "mobile", "src", "engine.js")],
        input=json.dumps(payload), capture_output=True, text=True, check=True,
        encoding="utf-8").stdout)


# ── Effets ──────────────────────────────────────────────────────────────────
GROUP_NAMES = {"A": "face", "B": "lat", "C": "contre", "D": "douche1",
               "E": "douche2", "F": "douche3", "G": "groupe_g", "H": "groupe_h"}
# Un rig varié : profils avec et sans Dim, niveaux et couleurs différents,
# projecteurs éteints (niveau 0, couleur noire) — l'effet les rallume.
RIG = [("RGBDS", "A", "#ff0000", 100), ("RGBDS", "A", "#ff0000", 100),
       ("RGB", "A", "#0000ff", 60), ("DRGB", "B", "#ffdd00", 37),
       ("RGBW", "B", "#ffffff", 100), ("RGBWD", "C", "#00dddd", 0),
       ("RGBWA", "C", "#000000", 0), ("DIM", "D", "#ffffff", 80),
       ("STROBE_2CH", "D", "#ff00ff", 50), ("MOVING_RGB", "E", "#ff8800", 99),
       ("MOVING_RGBW", "E", "#7f3a11", 100), ("MACMAH_IZY715Z", "F", "#00ff00", 70),
       ("MACMAH_IZY715Z", "F", "#ffffff", 100)]
# Visée des lyres avant l'effet (centre du mouvement) et position x sur le plan (SYM).
AIM = {9: (20000, 41000), 10: (32768, 32768), 11: (60000, 9000), 12: (1000, 64000)}
XPOS = {9: 0.2, 10: 0.8, 11: 0.35, 12: 0.65}
LYRE_PROFILES = {"MOVING_RGB", "MOVING_RGBW", "MACMAH_IZY715Z"}
TIMES = [0.0, 0.137, 0.5, 1.23, 3.7, 10.01, 57.3]


def python_effect_frame(effect, t):
    import time
    import types
    from main_window import MainWindow
    projs, dmx = [], ArtNetDMX()
    for i, (prof, grp, color, level) in enumerate(RIG):
        p = Projector(GROUP_NAMES[grp], name=f"P{i}")
        p.set_color(QColor(color), level)
        p.dmx_profile = list(PROFILE_DEFS[prof])
        if prof in LYRE_PROFILES:
            p.fixture_type = "Moving Head"
        p.pan, p.tilt = AIM.get(i, (32768, 32768))
        p.canvas_x = XPOS.get(i, 0.5)
        projs.append(p)
        dmx.set_projector_patch(f"{p.group}_{i}", list(range(1 + 16 * i, 1 + 16 * i + len(p.dmx_profile))),
                                profile=list(p.dmx_profile))
    fake = types.SimpleNamespace(
        projectors=projs, effect_speed=100, effect_t0=0.0, position_presets=[],
        effect_saved_colors={id(p): MainWindow._effect_state_tuple(p) for p in projs},
        _effect_clock=t, _effect_clock_ts=1000.0,
        _update_color_wheel=lambda p, c: None)
    real = time.monotonic
    time.monotonic = lambda: 1000.0          # dt = 0 : l'horloge de phase reste à t
    try:
        MainWindow._update_effect_from_layers(fake, {"name": effect["name"], "layers": effect["layers"],
                                                     "no_color": effect["no_color"]})
    finally:
        time.monotonic = real
    dmx.update_from_projectors(projs)
    return list(dmx.dmx_data[0][:512])


def js_effect_frames(effects, shapes):
    fixtures = [{"address": 1 + 16 * i, "profile": prof, "group": grp, "color": color, "level": level,
                 "pan": AIM.get(i, (32768, 32768))[0], "tilt": AIM.get(i, (32768, 32768))[1],
                 "x": XPOS.get(i, 0.5)}
                for i, (prof, grp, color, level) in enumerate(RIG)]
    return run_node(
        "const e=require(process.argv[1]);const {effects,fixtures,times,shapes}=JSON.parse(require('fs').readFileSync(0,'utf8'));"
        "const out=effects.map(fx=>times.map(t=>{const fs=fixtures.map(f=>({...f}));e.effectFrame(fx,fs,t,shapes);"
        "return Array.from(e.render(fs));}));process.stdout.write(JSON.stringify(out))",
        {"effects": effects, "fixtures": fixtures, "times": TIMES, "shapes": shapes})


def check_effects():
    lib = json.loads(subprocess.run(
        ["node", "-e", "process.stdout.write(JSON.stringify(require(process.argv[1])))",
         os.path.join(REPO, "mobile", "src", "effects.js")],
        capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    effects = lib["effects"]
    got = js_effect_frames(effects, lib["shapes"])
    failures = 0
    for fx, frames in zip(effects, got):
        for t, js in zip(TIMES, frames):
            pc = python_effect_frame(fx, t)
            if pc != js:
                failures += 1
                if failures <= 15:
                    diff = [(c + 1, pc[c], js[c]) for c in range(512) if pc[c] != js[c]]
                    print(f"ÉCART effet « {fx['name']} » t={t} : (canal, PC, tablette) {diff[:6]}")
    total = len(effects) * len(TIMES)
    print(f"{total - failures}/{total} trames d'effet identiques au PC ({len(effects)} effets × {len(TIMES)} instants)")
    return failures


def main():
    cases = scenarios()
    failures, total = 0, 0
    # Par paquets qui tiennent dans 512 canaux (≤ 16 canaux par projecteur).
    for start in range(0, len(cases), 32):
        batch = cases[start:start + 32]
        addr = 1
        for f in batch:
            f["address"] = addr
            addr += 16
        expected = python_frame(batch)
        got = json.loads(subprocess.run(
            ["node", "-e",
             "const e=require(process.argv[1]);const f=JSON.parse(require('fs').readFileSync(0,'utf8'));"
             "process.stdout.write(JSON.stringify(Array.from(e.render(f))))",
             os.path.join(REPO, "mobile", "src", "engine.js")],
            input=json.dumps(batch), capture_output=True, text=True, check=True).stdout)
        for f in batch:
            total += 1
            n = len(PROFILE_DEFS[f["profile"]])
            a = f["address"] - 1
            if expected[a:a + n] != got[a:a + n]:
                failures += 1
                if failures <= 15:
                    print(f"ÉCART {f['profile']} {f['color']} niv {f['level']} strobe {f['strobe']}"
                          f"{' MUTE' if f['muted'] else ''} : PC {expected[a:a + n]} ≠ tablette {got[a:a + n]}")
    print(f"{total - failures}/{total} projecteurs identiques au PC")
    failures += check_effects()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
