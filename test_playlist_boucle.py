# -*- coding: utf-8 -*-
"""Playlist en boucle : à la fin du dernier média, on repart du 1er.

- boucle playlist OFF : fin du show, rien n'est relancé ;
- boucle playlist ON  : la ligne 0 est relancée (différée, singleShot) ;
- un média en boucle prime : c'est LUI qui est rejoué, pas la ligne 0.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow\App")

from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
app = QApplication.instance() or QApplication([])

from main_window import MainWindow


def fin_du_dernier(playlist_loop, media_loop=False):
    appels = []

    class Seq:
        current_row = 2
        recording = False
        timeline_playback_timer = None
        sequences = {}
        timeline_tracks_data = {}
        table = type("T", (), {"rowCount": lambda self: 3})()
        def is_row_loop(self, r): return media_loop
        def next_step_row(self, r): return r + 1
        def get_dmx_mode(self, r): return "Manuel"
        def play_row(self, r): appels.append(("play", r))

    class W:
        playlist_transition = "enchaine"
        playlist_first_row = MainWindow.playlist_first_row
        seq = Seq()
        _media_source_row = 2
        player = type("P", (), {"position": lambda s: 10000,
                                 "duration": lambda s: 10000})()
        def transition_blackout(self): appels.append("noir")
        def update_play_icon(self, s): appels.append("stop")
        def _update_video_output_state(self): pass

    w = W()
    w.playlist_loop = playlist_loop
    MainWindow.on_media_status_changed(w, QMediaPlayer.EndOfMedia)
    app.processEvents()             # exécute les singleShot(0)
    return appels


assert fin_du_dernier(False) == ["stop"], fin_du_dernier(False)
print("OK sans boucle : fin du show")
assert fin_du_dernier(True) == [("play", 0)], fin_du_dernier(True)
print("OK playlist en boucle : repart du 1er média")
assert fin_du_dernier(True, media_loop=True) == [("play", 2)]
print("OK média en boucle prioritaire sur la playlist")
print("\nTout est vert.")
