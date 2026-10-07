# -*- coding: utf-8 -*-
"""Option de show « Lumière entre deux médias » : Clear / Enchaîné.

- Clear    : le CLEAR du plan de feu 2D à chaque changement de média (niveau,
             couleur, gobo, prisme, lyres au centre, prises en main libérées),
             mais l'APC n'est pas touché : faders + pads restent, et le groupe
             tenu à la main est reposé aussitôt.
- Enchaîné : d'un REC Lumière à un autre, aucun noir — seul l'effet du REC
             sortant est coupé.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow\App")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QMediaPlayer
app = QApplication.instance() or QApplication([])

from projector import Projector
from main_window import MainWindow
from plan_de_feu import PlanDeFeu


class FauxFader:
    def __init__(self, value): self.value = value
    def update(self): pass


class FauxPdf:
    """Juste ce que `_clear_all_projectors` touche sur le plan."""
    _clear_all_projectors = PlanDeFeu._clear_all_projectors
    def __init__(self, projs):
        self.projectors = projs
        self._effects, self._led_effects = {}, {}
        self.selected_lamps = set()
    def refresh(self): pass


class Stub:
    playlist_clear      = MainWindow.playlist_clear
    restore_manual_look = MainWindow.restore_manual_look
    _slot_groups        = staticmethod(MainWindow._slot_groups)
    set_proj_level      = MainWindow.set_proj_level
    def send_dmx_update(self): self.sent = True
    def _update_color_wheel(self, p, color): pass

    def __init__(self):
        self.projectors = [Projector(i, f"P{i}", 1 + i * 10) for i in range(3)]
        for p in self.projectors:            # look laissé par le média précédent
            p.level = 90
            p.base_color = p.color = QColor("#ff0000")
            p.gobo, p.prism, p.zoom, p.pan = 40, 128, 200, 1000
            p._manual_color = True           # prise en main depuis le plan 2D
        self.plan_de_feu = FauxPdf(self.projectors)
        self._fader_map = [{"type": "memory", "mem_col": i, "label": ""} for i in range(8)]
        self._muted_faders = set()
        self.faders = {i: FauxFader(0) for i in range(9)}
        self.faders[4].value = 75            # ambiance tenue sur l'APC
        self.active_pads = {4: object()}
        self.sent = False


# ── Clear ────────────────────────────────────────────────────────────────────
s = Stub()
MainWindow.playlist_clear(s)
for p in s.projectors:
    assert p.level == 0 and p.color == QColor(0, 0, 0), "niveau/couleur non remis"
    assert (p.gobo, p.prism, p.zoom) == (0, 0, 0), "faisceau resté collé"
    assert p.pan == 32768, "lyre pas recentrée"
    assert not p._manual_color, "prise en main pas libérée"
assert s.faders[4].value == 75 and 4 in s.active_pads, "Clear a touché l'APC"
assert s.sent, "DMX non envoyé"
print("OK Clear : rig au repos, APC intact")

# ── Enchaîné : REC Lumière → REC Lumière = pas de noir ───────────────────────
def fin_de_media(transition, next_mode, next_has_seq=True):
    appels = []

    class Seq:
        current_row = 0
        recording = False
        timeline_playback_timer = None
        sequences = {1: {"clips": []}} if next_has_seq else {}
        timeline_tracks_data = {}
        table = type("T", (), {"rowCount": lambda self: 2})()
        def is_row_loop(self, r): return False
        def next_step_row(self, r): return r + 1
        def get_dmx_mode(self, r): return "Play Lumiere" if r == 0 else next_mode
        def _stop_timeline_effect(self): appels.append("stop_fx")
        def play_row(self, r): appels.append(("play", r))

    class W:
        playlist_transition = transition
        seq = Seq()
        _media_source_row = 0
        player = type("P", (), {"position": lambda s: 10000,
                                 "duration": lambda s: 10000})()
        def transition_blackout(self): appels.append("noir")

    MainWindow.on_media_status_changed(W(), QMediaPlayer.EndOfMedia)
    return appels

assert fin_de_media("enchaine", "Play Lumiere") == ["stop_fx"]
assert fin_de_media("enchaine", "Manuel") == ["noir"]
assert fin_de_media("enchaine", "Play Lumiere", next_has_seq=False) == ["noir"]
assert fin_de_media("clear", "Play Lumiere") == ["noir"]
print("OK Enchaîné : pas de noir entre deux REC Lumière, noir conservé sinon")
