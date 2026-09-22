"""Parité du moteur DMX tablette (mobile/src/engine.js) avec celui du PC.

Fait tourner le VRAI moteur (ArtNetDMX._update_from_projectors_locked) et
engine.js sur les mêmes projecteurs, et compare les 512 octets. Un écart =
la tablette n'éclaire pas comme le PC.

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
            "RGBWA", "RGBWAD", "DIM", "STROBE_2CH", "MOVING_RGB", "MOVING_RGBW"]
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
        n = len(DMX_PROFILES[f["profile"]])
        dmx.set_projector_patch(f"A_{i}", list(range(f["address"], f["address"] + n)),
                                profile=list(DMX_PROFILES[f["profile"]]))
    dmx.update_from_projectors(projs)
    return list(dmx.dmx_data[0][:512])


def main():
    cases = scenarios()
    failures, total = 0, 0
    # Par paquets qui tiennent dans 512 canaux (≤ 9 canaux par projecteur).
    for start in range(0, len(cases), 50):
        batch = cases[start:start + 50]
        addr = 1
        for f in batch:
            f["address"] = addr
            addr += 10
        expected = python_frame(batch)
        got = json.loads(subprocess.run(
            ["node", "-e",
             "const e=require(process.argv[1]);const f=JSON.parse(require('fs').readFileSync(0,'utf8'));"
             "process.stdout.write(JSON.stringify(Array.from(e.render(f))))",
             os.path.join(REPO, "mobile", "src", "engine.js")],
            input=json.dumps(batch), capture_output=True, text=True, check=True).stdout)
        for f in batch:
            total += 1
            n = len(DMX_PROFILES[f["profile"]])
            a = f["address"] - 1
            if expected[a:a + n] != got[a:a + n]:
                failures += 1
                if failures <= 15:
                    print(f"ÉCART {f['profile']} {f['color']} niv {f['level']} strobe {f['strobe']}"
                          f"{' MUTE' if f['muted'] else ''} : PC {expected[a:a + n]} ≠ tablette {got[a:a + n]}")
    print(f"{total - failures}/{total} projecteurs identiques au PC")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
