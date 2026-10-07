# -*- coding: utf-8 -*-
"""Ligne « IA » de la playlist relancée par Play + barre d'espace.

- Play sur un média IA déjà chargé (après la fin du morceau, qui fait
  `audio_ai.reset()`) rejouait le son sans lumière : seul le double-clic
  (`play_row`) rechargeait la pré-analyse. `ensure_light_playback_armed` la
  recharge maintenant — sans la recharger à chaque reprise après pause, et en
  remplaçant celle d'une AUTRE ligne restée en mémoire.
- La barre d'espace n'atteignait jamais `MainWindow.keyPressEvent` : la
  playlist ou le dernier bouton cliqué la mangeaient.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow\App")

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QTableWidget, QPushButton, QLineEdit)
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
app = QApplication.instance() or QApplication([])

from sequencer import Sequencer
from audio_ai import AudioColorAI

ANALYSE = {"energy_map": [0.5] * 200,
           "beats": [i * 500 for i in range(40)]}
AUTRE = {"energy_map": [0.9] * 200,
         "beats": [i * 250 for i in range(80)]}


class FauxSeq:
    _ensure_ia_analysis_loaded = Sequencer._ensure_ia_analysis_loaded
    ensure_light_playback_armed = Sequencer.ensure_light_playback_armed

    def __init__(self):
        self.player_ui = type("P", (), {})()
        self.player_ui.audio_ai = AudioColorAI()
        self.current_row = 2
        self.sequences = {}
        self.ia_colors = {}
        self.ia_analysis = {2: ANALYSE, 5: AUTRE}
        self.modes = {2: "IA Lumiere", 5: "IA Lumiere"}

    def get_dmx_mode(self, row):
        return self.modes.get(row, "Manuel")


def test_play_apres_fin_de_morceau_recharge_l_analyse():
    s = FauxSeq()
    s.player_ui.audio_ai.reset()          # fin du morceau IA
    s.ensure_light_playback_armed()
    assert s.player_ui.audio_ai.analyzed
    assert s.player_ui.audio_ai.beats == ANALYSE["beats"]


def test_media_precharge_par_une_ligne_pause():
    """Ligne PAUSE : current_row = morceau suivant, sans play_row. Play = lumière."""
    s = FauxSeq()
    lache = []
    s.player_ui._release_manual_grabs = lambda: lache.append(1)
    s.player_ui.audio_ai.load_analysis(AUTRE)   # morceau IA d'avant la PAUSE
    s._ia_loaded_row = 5
    s.ensure_light_playback_armed()             # bras du Play en pause_mode
    assert s.player_ui.audio_ai.beats == ANALYSE["beats"] and lache == [1]


def test_reprise_apres_pause_ne_recharge_pas():
    s = FauxSeq()
    s.ensure_light_playback_armed()
    s.player_ui.audio_ai.beats = ["marque"]   # état vivant du moteur
    s.ensure_light_playback_armed()
    assert s.player_ui.audio_ai.beats == ["marque"]


def test_analyse_d_une_autre_ligne_remplacee():
    s = FauxSeq()
    s.player_ui.audio_ai.load_analysis(AUTRE)
    s._ia_loaded_row = 5                  # ligne 5 passée en IA entre-temps
    s.ensure_light_playback_armed()
    assert s.player_ui.audio_ai.beats == ANALYSE["beats"]


def test_ligne_manuel_intouchee():
    s = FauxSeq()
    s.modes[2] = "Manuel"
    s.player_ui.audio_ai.reset()
    s.ensure_light_playback_armed()
    assert not s.player_ui.audio_ai.analyzed


def test_espace_atteint_play_quel_que_soit_le_focus():
    """Même câblage que MainWindow (_play_sc) : QShortcut de fenêtre."""
    w = QMainWindow(); c = QWidget(); lay = QVBoxLayout(c)
    table, bouton, champ = QTableWidget(3, 2), QPushButton("x"), QLineEdit()
    for x in (table, bouton, champ):
        lay.addWidget(x)
    w.setCentralWidget(c)
    joue, clics = [], []
    sc = QShortcut(QKeySequence(Qt.Key_Space), w)
    sc.setContext(Qt.WindowShortcut)
    sc.activated.connect(lambda: joue.append(1))
    bouton.clicked.connect(lambda: clics.append(1))
    w.show(); app.processEvents()
    for x in (table, bouton):
        x.setFocus(); QTest.keyClick(x, Qt.Key_Space)
    assert len(joue) == 2 and not clics   # le bouton ne se re-clique plus
    champ.setFocus(); QTest.keyClick(champ, Qt.Key_Space)
    assert len(joue) == 2 and champ.text() == " "   # la saisie garde l'espace
    w.close()


def test_mainwindow_cable_l_espace():
    src = open(os.path.join(os.path.dirname(__file__), "main_window.py"),
               encoding="utf-8").read()
    assert "_play_sc.activated.connect(self.toggle_play)" in src


if __name__ == "__main__":
    for nom, f in list(globals().items()):
        if nom.startswith("test_"):
            f(); print("OK", nom)
