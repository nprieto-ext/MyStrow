"""Parité du moteur tablette sur TOUTE la bibliothèque de fixtures.

Chaque mode de chaque fixture de mobile/src/library.js (natives, OFL, Firestore,
QLC+) passe dans le VRAI moteur du PC (ArtNetDMX._update_from_projectors_locked,
MainWindow._update_color_wheel, MainWindow._update_effect_from_layers) et dans
engine.js, sous plusieurs états et quelques effets. Les 512 octets doivent être
identiques : une fixture patchée sur la tablette s'allume comme sur le PC.

    python mobile/tools/test_library_parity.py      (Node.js requis, ~1 min)

À relancer après toute modification d'engine.js, d'artnet_dmx.py, du moteur
d'effets ou de la bibliothèque (export_library.py).
"""
import json
import os
import subprocess
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

from PySide6.QtGui import QColor  # noqa: E402

import artnet_dmx  # noqa: E402
from artnet_dmx import ArtNetDMX  # noqa: E402
from main_window import MainWindow  # noqa: E402
from projector import Projector  # noqa: E402

NOW = 1_000_000.37           # horloge figée : strobe artificiel des gradateurs
PHASE_T = 1.23               # instant de phase des effets

# États d'un projecteur (couleur PURE, niveau, strobe, visée, mute).
STATES = [
    {"color": "#ff0000", "level": 100, "strobe": 0, "pan": 32768, "tilt": 32768, "muted": False},
    {"color": "#ffffff", "level": 50, "strobe": 50, "pan": 20000, "tilt": 50000, "muted": False},
    {"color": "#0000ff", "level": 37, "strobe": 0, "pan": 65535, "tilt": 0, "muted": False},
    {"color": "#ff8800", "level": 100, "strobe": 100, "pan": 1234, "tilt": 40000, "muted": False},
    {"color": "#000000", "level": 0, "strobe": 0, "pan": 32768, "tilt": 32768, "muted": False},
    {"color": "#00ff00", "level": 80, "strobe": 30, "pan": 32768, "tilt": 32768, "muted": True},
]
EFFECTS = ["Strobe Classique", "Chase Doux", "Rainbow", "Pulse Doux", "Lyre Cercle", "Lyre Papillon"]


def load_js(name):
    t = open(os.path.join(REPO, "mobile", "src", name), encoding="utf-8").read()
    return json.loads(t[t.index("const api = ") + 12:t.rindex(";\n  if (typeof")])


def batches(cases):
    """Paquets de cas qui tiennent dans 512 canaux, chacun à sa propre adresse."""
    out, cur, addr = [], [], 1
    for c in cases:
        n = len(c["profile"])
        if addr + n - 1 > 512:
            out.append(cur)
            cur, addr = [], 1
        cur.append(dict(c, address=addr))
        addr += n
    if cur:
        out.append(cur)
    return out


def pc_frame(batch, effect):
    dmx = ArtNetDMX()
    projs = []
    fake = types.SimpleNamespace(_GENERIC_WHEEL_SLOTS=MainWindow._GENERIC_WHEEL_SLOTS)
    for i, c in enumerate(batch):
        p = Projector("face", name=f"P{i}", fixture_type=c["fixture_type"])
        p.dmx_profile = list(c["profile"])
        p.color_wheel_slots = list(c.get("cw") or [])
        p.set_color(QColor(c["color"]), c["level"])
        p.strobe_speed = c["strobe"]
        p.pan, p.tilt, p.muted = c["pan"], c["tilt"], c["muted"]
        p.canvas_x = (i + 1) / (len(batch) + 1)
        MainWindow._update_color_wheel(fake, p, QColor(c["color"]))
        projs.append(p)
        dmx.set_projector_patch(f"face_{i}", list(range(c["address"], c["address"] + len(c["profile"]))),
                                profile=list(c["profile"]))
    if effect:
        eff = types.SimpleNamespace(
            projectors=projs, effect_speed=100, effect_t0=0.0, position_presets=[],
            effect_saved_colors={id(p): MainWindow._effect_state_tuple(p) for p in projs},
            _effect_clock=PHASE_T, _effect_clock_ts=1000.0, _GENERIC_WHEEL_SLOTS=MainWindow._GENERIC_WHEEL_SLOTS)
        eff._update_color_wheel = lambda p, col: MainWindow._update_color_wheel(eff, p, col)
        real = time.monotonic
        time.monotonic = lambda: 1000.0
        try:
            MainWindow._update_effect_from_layers(eff, {"name": effect["name"], "layers": effect["layers"],
                                                        "no_color": effect["no_color"]})
        finally:
            time.monotonic = real
    real_t = artnet_dmx.time.time
    artnet_dmx.time.time = lambda: NOW
    try:
        dmx.update_from_projectors(projs)
    finally:
        artnet_dmx.time.time = real_t
    return list(dmx.dmx_data[0][:512])


JS = r"""
const E = require(process.argv[1]);
const { jobs, effects, shapes, now, t } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = jobs.map(([batch, effName]) => {
  const states = batch.map((c, i) => ({ address: c.address, profile: c.profile, fixture_type: c.fixture_type,
    color_wheel_slots: c.cw || [], color: c.color, level: c.level, strobe: c.strobe,
    pan: c.pan, tilt: c.tilt, muted: c.muted, x: (i + 1) / (batch.length + 1) }));
  states.forEach((s) => E.updateColorWheel(s, E.hexToRgb(s.color)));
  if (effName) E.effectFrame(effects[effName], states, t, shapes);
  return Array.from(E.render(states, null, now));
});
process.stdout.write(JSON.stringify(out));
"""


def main():
    lib = load_js("library.js")
    fxlib = load_js("effects.js")
    effects = {e["name"]: e for e in fxlib["effects"]}
    base = []
    for fx in lib["fixtures"]:
        for mode_name, profile in fx["modes"]:
            base.append({"name": f'{fx["m"]} · {fx["n"]} · {mode_name}', "profile": profile,
                         "fixture_type": fx["t"], "cw": fx.get("cw")})
    jobs = []
    for k, st in enumerate(STATES):
        cases = [dict(c, **st) for c in base]
        # Effets : sur l'état n° 1 et n° 2 seulement (ça suffit à couvrir
        # couleur, dimmer, roue et mouvement sur chaque profil).
        jobs += [(b, None) for b in batches(cases)]
        if k < 2:
            for name in EFFECTS:
                jobs += [(b, name) for b in batches(cases)]
    print(f"{len(base)} modes · {len(STATES)} états · {len(EFFECTS)} effets → {len(jobs)} trames…", flush=True)

    got = json.loads(subprocess.run(
        ["node", "-e", JS, os.path.join(REPO, "mobile", "src", "engine.js")],
        input=json.dumps({"jobs": jobs, "effects": effects, "shapes": fxlib["shapes"], "now": NOW, "t": PHASE_T}),
        capture_output=True, text=True, check=True, encoding="utf-8").stdout)

    fails, checked, bad_modes = 0, 0, {}
    for (batch, eff_name), js in zip(jobs, got):
        pc = pc_frame(batch, effects[eff_name] if eff_name else None)
        for c in batch:
            a, n = c["address"] - 1, len(c["profile"])
            checked += 1
            if pc[a:a + n] != js[a:a + n]:
                fails += 1
                key = c["name"]
                if key not in bad_modes:
                    bad_modes[key] = (eff_name, c["color"], c["level"], c["strobe"], c["muted"],
                                      c["profile"], pc[a:a + n], js[a:a + n])
    for name, (eff, col, lvl, spd, mut, prof, p, j) in list(bad_modes.items())[:12]:
        print(f"ÉCART {name} [{eff or 'sans effet'} {col} niv {lvl} strobe {spd}{' MUTE' if mut else ''}]")
        diff = [(prof[i], p[i], j[i]) for i in range(len(prof)) if p[i] != j[i]]
        print(f"   (canal, PC, tablette) : {diff[:6]}")
    print(f"{checked - fails}/{checked} projecteurs identiques au PC "
          f"({len(bad_modes)} mode(s) en écart sur {len(base)})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
