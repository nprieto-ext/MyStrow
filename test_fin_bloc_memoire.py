# -*- coding: utf-8 -*-
"""Un bloc memoire qui pose gobo/prisme/zoom doit tout relacher A SA FIN.

Reproduit le flux par frame de la restitution :
    reset -> apply_seq_memories_htp(clips actifs)
Frame 1 : le bloc est actif  -> le gobo/prisme/zoom sont poses.
Frame 2 : le bloc est fini   -> ils doivent etre retombes au repos.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from projector import Projector
from light_timeline import (reset_beam_channels, apply_seq_memories_htp,
                            _REPOS_FAISCEAU)


class FauxMainWindow:
    _fx_clip_ids = set()


def frame(projs, entries, main_win):
    """Une image de restitution, exactement comme apply_timeline_to_dmx."""
    reset_beam_channels(projs, blackout=True)
    apply_seq_memories_htp(entries, MEMOIRES, projs, main_win)


projs = [Projector(i, f"P{i}", 1 + i * 10) for i in range(2)]
mw = FauxMainWindow()

# Une memoire qui allume P0 en bleu avec un gobo, un prisme et un zoom.
snapshot = {
    "level": 80, "base_color": "#0000ff",
    "gobo": 40, "gobo_rotation": 120, "prism": 200,
    "zoom": 90, "focus": 55, "shutter": 255,
    "effects": 77, "mode_value": 33,
    "channel_extras": {5: 210},
    "strobe_speed": 0, "pan": 32768, "tilt": 32768,
}
eteint = {"level": 0, "base_color": "#000000"}
MEMOIRES = [[{"cues": [{"projectors": [snapshot, eteint]}], "name": "REC 1"}]]

CANAUX = ("gobo", "gobo_rotation", "prism", "zoom", "focus",
          "effects", "mode_value")

# ── Frame 1 : bloc actif ──────────────────────────────────────────────────
frame(projs, [{"memory_ref": (0, 0), "cue_index": 0, "brightness": 1.0}], mw)
p = projs[0]
poses = {a: getattr(p, a) for a in CANAUX}
print("frame 1 (bloc actif)   :", poses, "| channel_extras =", p.channel_extras)
assert p.gobo == 40 and p.prism == 200 and p.zoom == 90, "la memoire ne pose plus rien !"
assert p.channel_extras == {5: 210}

# ── Frame 2 : plus aucun bloc actif (fin du bloc memoire) ─────────────────
frame(projs, [], mw)
p = projs[0]
restes = {a: getattr(p, a) for a in CANAUX if getattr(p, a) != _REPOS_FAISCEAU[a]}
print("frame 2 (bloc termine) :", {a: getattr(p, a) for a in CANAUX},
      "| channel_extras =", p.channel_extras, "| level =", p.level)

assert not restes, f"CANAUX COLLES APRES LA FIN DU BLOC : {restes}"
assert p.channel_extras == {}, f"canaux bruts colles : {p.channel_extras}"
assert p.level == 0
assert p.shutter == 255, "le shutter doit revenir OUVERT au repos"
print("\nOK - le bloc memoire se nettoie tout seul a sa fin.")
