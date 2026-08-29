"""Etat de la dalle 3D selon le media courant et l'etat du lecteur."""
import os, sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, r'C:\Users\nikop\Desktop\MyStrow')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QMediaPlayer
app = QApplication.instance() or QApplication([])
import plan_3d_webwindow as P
W = P.Plan3DWebWindow

class FauxItem:
    def __init__(self, p): self.p = p
    def data(self, role): return self.p
class FauxTable:
    def __init__(self, p): self.p = p
    def item(self, row, col): return FauxItem(self.p)
class FauxSeq:
    def __init__(self, p): self.current_row = 0; self.table = FauxTable(p)
class FauxPlayer:
    def __init__(self, st): self.st = st
    def playbackState(self): return self.st
class FauxMW:
    def __init__(self, p, st): self.seq = FauxSeq(p); self.player = FauxPlayer(st)

class Faux:
    VIDEO_WIDTH = W.VIDEO_WIDTH; VIDEO_QUALITY = W.VIDEO_QUALITY
    _ready = True
    def __init__(self, path, etat):
        self._parent_mw = FauxMW(path, etat)
        self._video_still = None
        self.js = []
    def isVisible(self): return True
    def _js(self, code): self.js.append(code)
    _tick_video_still  = W._tick_video_still
    _player_state      = W._player_state
    _current_media_path= W._current_media_path
    _push_video_image  = W._push_video_image

def etat_dalle(f):
    if not f.js: return "inchangee"
    c = f.js[-1]
    if 'setVideoFrame("")' in c: return "NOIRE"
    if 'base64' in c: return "image posee"
    return c[:40]

VID = r'C:\clip.mp4'
cas = [
    ("video en lecture",  VID, QMediaPlayer.PlayingState, "inchangee"),
    ("video en PAUSE",    VID, QMediaPlayer.PausedState,  "inchangee"),
    ("video TERMINEE",    VID, QMediaPlayer.StoppedState, "NOIRE"),
    ("piste audio",  r'C:\son.mp3', QMediaPlayer.PlayingState, "NOIRE"),
    ("PAUSE playlist",       '',    QMediaPlayer.StoppedState, "NOIRE"),
]
ok = True
for nom, path, etat, attendu in cas:
    f = Faux(path, etat); f._tick_video_still()
    got = etat_dalle(f)
    marque = "OK " if got == attendu else "KO "
    if got != attendu: ok = False
    print(f"  {marque} {nom:22s} -> dalle {got}  (attendu {attendu})")

# La dalle ne doit etre noircie QU'UNE FOIS, pas a chaque tick
f = Faux(r'C:\son.mp3', QMediaPlayer.PlayingState)
for _ in range(5): f._tick_video_still()
print(f"  {'OK ' if len(f.js)==1 else 'KO '} 5 ticks sur de l'audio -> {len(f.js)} appel(s) JS (attendu 1)")
if len(f.js) != 1: ok = False

# Etat illisible : on ne noircit pas
class Sourd(Faux):
    def _player_state(self): return None
f = Sourd(VID, None); f._tick_video_still()
print(f"  {'OK ' if not f.js else 'KO '} etat lecteur illisible -> dalle {etat_dalle(f)} (attendu inchangee)")
if f.js: ok = False
print("TOUT OK" if ok else "ECHECS")
sys.exit(0 if ok else 1)
