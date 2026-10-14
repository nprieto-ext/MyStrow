# -*- coding: utf-8 -*-
"""Mode hybride : la REC Lumiere ne prend QUE ce que ses blocs pilotent.

Remontee 14/10/2026 : « je monte au fader, ca s'allume une demi-seconde puis
ca se coupe, comme si le REC prenait le lead ». `apply_timeline_to_dmx`
remettait TOUT le parc au noir a chaque image, meme entre deux blocs.

Rejoue le vrai `Sequencer.apply_timeline_to_dmx`, image par image :
  1. avant le bloc      -> le look manuel (Face + Contre) reste intact ;
  2. bloc rouge sur Face -> la Face passe au rouge, le Contre ne bouge pas ;
  3. bloc noir sur Face  -> la Face noircit (un bloc noir est un ordre) ;
  4. apres le bloc      -> la Face retrouve son look manuel ;
  5. bloc Position      -> la lyre bouge mais GARDE sa couleur manuelle ;
  6. arret de la REC    -> on rend tout, gobo/canaux bruts compris.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
app = QApplication.instance() or QApplication([])

from projector import Projector
from sequencer import Sequencer


class FauxMainWindow:
    memories = []
    position_presets = []
    active_effect = None

    def __init__(self, projs):
        self.projectors = projs

    def get_track_to_indices(self):
        return {"Face": [0], "Contres": [1], "Lyres": [2]}


class FauxSeq:
    """Juste ce que lit apply_timeline_to_dmx."""
    _clear_timeline_leftovers = Sequencer._clear_timeline_leftovers

    def __init__(self, mw):
        self.player_ui = mw
        self._timeline_tick = 0


face = Projector("face", "Face 1", 1)
contre = Projector("contre", "Contre 1", 11)
lyre = Projector("lat", "Lyre 1", 21)
projs = [face, contre, lyre]
mw = FauxMainWindow(projs)
seq = FauxSeq(mw)


def image(clips):
    Sequencer.apply_timeline_to_dmx(seq, clips)


def bloc(couleur, intensite=100):
    return {"color": QColor(couleur), "color2": None, "intensity": intensite,
            "effect": None, "effect_speed": 50}


def manuel(p, couleur, niveau):
    p.base_color = QColor(couleur)
    p.level = niveau
    p.color = QColor(couleur).darker(100)


# Look monte a la main (fader / plan 2D) : Face et Contre en bleu a 80 %,
# lyre en vert avec un gobo et un canal brut.
manuel(face, "#0000ff", 80)
manuel(contre, "#0000ff", 80)
manuel(lyre, "#00ff00", 60)
lyre.pan, lyre.tilt = 10000, 20000
face.gobo = 0

# 1. Avant le premier bloc
for _ in range(3):
    image({})
assert face.level == 80 and face.base_color == QColor("#0000ff"), \
    f"1. look manuel efface hors bloc : {face.level} {face.base_color.name()}"
assert contre.level == 80 and lyre.level == 60
print("1. hors bloc : look manuel intact")

# 2. Bloc rouge sur la Face
for _ in range(3):
    image({"Face": bloc("#ff0000")})
assert face.base_color == QColor("#ff0000") and face.level == 100
assert contre.level == 80 and contre.base_color == QColor("#0000ff"), \
    "2. le Contre a ete pris alors qu'aucun bloc ne le vise"
print("2. bloc Face : Face rouge, Contre manuel intact")

# 3. Bloc noir sur la Face : il doit noircir, pas laisser passer le manuel
image({"Face": bloc("#000000")})
assert face.color == QColor(0, 0, 0),     f"3. un bloc noir doit noircir (couleur={face.color.name()})"
print("3. bloc noir : Face noire")

# 4. Apres le bloc : la main revient
image({})
assert face.level == 80 and face.base_color == QColor("#0000ff"), \
    f"4. look manuel pas rendu : {face.level} {face.base_color.name()}"
print("4. fin de bloc : Face rendue en bleu 80 %")

# 5. Bloc Position : la lyre bouge, garde sa couleur manuelle
pos = {"color": QColor("#000000"), "color2": None, "intensity": 100,
       "effect": None, "move_effect": None, "pan_start": 30000,
       "tilt_start": 30000, "pan_end": 30000, "tilt_end": 30000,
       "move_progress": 0.0, "move_elapsed": 0.0}
for _ in range(4):
    image({"Position": pos})
assert lyre.level == 60 and lyre.base_color == QColor("#00ff00"), \
    f"5. le bloc Position a eteint la lyre : {lyre.level} {lyre.base_color.name()}"
assert (lyre.pan, lyre.tilt) != (10000, 20000), "5. la lyre n'a pas bouge"
print(f"5. bloc Position : lyre deplacee ({lyre.pan},{lyre.tilt}), couleur gardee")

# 6. Un bloc pose un gobo + canal brut, puis la REC s'arrete en plein bloc
lyre_clip = bloc("#ffffff")
image({"Face": lyre_clip})
face.gobo = 0
mem = {"level": 100, "base_color": "#ffffff", "gobo": 40,
       "channel_extras": {5: 210}}
mw.memories = [[{"cues": [{"projectors": [mem, {"level": 0, "base_color": "#000000"}]}],
                 "name": "M"}]]
image({"Sequence": dict(bloc("#000000"), memory_ref=(0, 0), cue_index=0,
                        seq_intensity=100)})
assert face.gobo == 40 and face.channel_extras == {5: 210}
seq._clear_timeline_leftovers(blackout=True)
assert face.gobo == 0 and face.channel_extras == {}, \
    f"6. gobo / canal brut colles apres l'arret : {face.gobo} {face.channel_extras}"
assert face.level == 80 and face.base_color == QColor("#0000ff")
assert (lyre.pan, lyre.tilt) == (10000, 20000), "6. position manuelle pas rendue"
assert seq._hyb_tenus == {}
print("6. arret : gobo et canal brut retombes, look manuel rendu")

print("\nOK - mode hybride : la REC ne prend que ce que ses blocs pilotent.")
