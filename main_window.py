"""
Fenetre principale de l'application - MainWindow
Module extrait de maestro.py pour une meilleure organisation
"""
import sys
import os
import json
import random
import ctypes
import platform as _platform
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSplitter, QScrollArea, QSlider,
    QToolButton, QMenu, QMenuBar, QFileDialog, QMessageBox, QDialog,
    QComboBox, QTableWidget, QTableWidgetItem, QWidgetAction, QSpinBox,
    QTabWidget, QProgressBar, QApplication, QLineEdit, QStackedWidget,
    QHeaderView, QCheckBox, QTextEdit, QToolTip
)
from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QPoint, QDateTime, QEvent, Signal
import datetime as _dt
try:
    import psutil as _psutil
except ImportError:
    _psutil = None
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QPixmap, QIcon, QFont,
    QPalette, QPolygon, QAction, QDesktopServices
)
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
except ImportError:
    # Stubs pour Mac sans backend multimedia — l'app démarre sans lecture audio/vidéo
    class QMediaPlayer:  # type: ignore
        PlayingState = 1; StoppedState = 0; PausedState = 2; EndOfMedia = 7
        def __init__(self): self._src = None
        def setAudioOutput(self, *a): pass
        def setVideoOutput(self, *a): pass
        def setSource(self, *a): pass
        def play(self): pass
        def pause(self): pass
        def stop(self): pass
        def position(self): return 0
        def duration(self): return 0
        def setPosition(self, *a): pass
        def setPlaybackRate(self, *a): pass
        def playbackState(self): return QMediaPlayer.StoppedState
        def mediaStatus(self): return 0
        def source(self): return None
        playbackStateChanged = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
        mediaStatusChanged   = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
        positionChanged      = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
        durationChanged      = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
        errorOccurred        = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
    class QAudioOutput:  # type: ignore
        def __init__(self): pass
        def setVolume(self, *a): pass
        def setDevice(self, *a): pass
    class QMediaDevices:  # type: ignore
        @staticmethod
        def audioOutputs(): return []
        audioOutputsChanged = type('S', (), {'connect': lambda *a: None})()

try:
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    QVideoWidget = None

from core import (
    APP_NAME, VERSION, MIDI_AVAILABLE,
    rgb_to_akai_velocity, fmt_time, create_icon, media_icon, resource_path
)
from i18n import get_language, set_language, tr
from projector import Projector
from artnet_dmx import ArtNetDMX, DMX_PROFILES, CHANNEL_TYPES, profile_for_mode, profile_name, profile_display_text
from audio_ai import AudioColorAI
from midi_handler import MIDIHandler
from ui_components import DualColorButton, EffectButton, FaderButton, ApcFader, CartoucheButton
from plan_de_feu import PlanDeFeu, ColorPickerBlock, _PatchCanvasProxy, _find_free_canvas_pos
from plan_3d import Plan3DWindow
from recording_waveform import RecordingWaveform
from sequencer import Sequencer
from timeline_editor import LightTimelineEditor
from updater import UpdateBar, UpdateChecker, download_update, AboutDialog
from license_manager import LicenseState, LicenseResult, verify_license
from license_ui import LicenseBanner, ActivationDialog, LicenseWarningDialog, LoginSuccessDialog


# Mapping lettre AKAI -> nom interne du groupe projecteur
AKAI_GROUP_MAP = {
    "A": "face",
    "B": "lat",
    "C": "contre",
    "D": "douche1",
    "E": "douche2",
    "F": "douche3",
}
# Reverse map pour migration des anciens fichiers
_AKAI_GROUP_REVERSE = {v: k for k, v in AKAI_GROUP_MAP.items()}

AKAI_BANK_PRESETS = [
    {
        "label": "A B C D  |  MEM 1-4",
        "slots": [
            {"type": "group",  "group": "A", "label": "A"},
            {"type": "group",  "group": "B", "label": "B"},
            {"type": "group",  "group": "C", "label": "C"},
            {"type": "group",  "group": "D", "label": "D"},
            {"type": "memory", "mem_col": 0, "label": "MEM 1"},
            {"type": "memory", "mem_col": 1, "label": "MEM 2"},
            {"type": "memory", "mem_col": 2, "label": "MEM 3"},
            {"type": "memory", "mem_col": 3, "label": "MEM 4"},
        ]
    },
    {
        "label": "A B C D E F  |  MEM 1-2",
        "slots": [
            {"type": "group",  "group": "A", "label": "A"},
            {"type": "group",  "group": "B", "label": "B"},
            {"type": "group",  "group": "C", "label": "C"},
            {"type": "group",  "group": "D", "label": "D"},
            {"type": "group",  "group": "E", "label": "E"},
            {"type": "group",  "group": "F", "label": "F"},
            {"type": "memory", "mem_col": 0, "label": "MEM 1"},
            {"type": "memory", "mem_col": 1, "label": "MEM 2"},
        ]
    },
    {
        "label": "MEM 1-4  |  A B C D",
        "slots": [
            {"type": "memory", "mem_col": 0, "label": "MEM 1"},
            {"type": "memory", "mem_col": 1, "label": "MEM 2"},
            {"type": "memory", "mem_col": 2, "label": "MEM 3"},
            {"type": "memory", "mem_col": 3, "label": "MEM 4"},
            {"type": "group",  "group": "A", "label": "A"},
            {"type": "group",  "group": "B", "label": "B"},
            {"type": "group",  "group": "C", "label": "C"},
            {"type": "group",  "group": "D", "label": "D"},
        ]
    },
    {
        "label": "MEM 1-4  |  MEM 5-8",
        "slots": [
            {"type": "memory", "mem_col": 0, "label": "MEM 1"},
            {"type": "memory", "mem_col": 1, "label": "MEM 2"},
            {"type": "memory", "mem_col": 2, "label": "MEM 3"},
            {"type": "memory", "mem_col": 3, "label": "MEM 4"},
            {"type": "memory", "mem_col": 4, "label": "MEM 5"},
            {"type": "memory", "mem_col": 5, "label": "MEM 6"},
            {"type": "memory", "mem_col": 6, "label": "MEM 7"},
            {"type": "memory", "mem_col": 7, "label": "MEM 8"},
        ]
    },
]


# ---------------------------------------------------------------------------
# Journal des actions AKAI (remplace les toasts)
# ---------------------------------------------------------------------------

class MessageLogWidget(QWidget):
    """Boîte de journal sous les slots AKAI — accumule les messages d'action.
    Vide à chaque fermeture de l'application."""

    _LEVELS = {
        "rec":     ("#00cc66", "●"),  # vert  : enregistrement mémoire
        "mem":     ("#55aaff", "→"),  # bleu  : activation mémoire
        "go":      ("#00bbdd", "▶"),  # cyan  : avance GO
        "effect":  ("#aa77ff", "⚡"), # violet: effet allumé/éteint
        "bpm":     ("#ffcc00", "♩"),  # jaune : TAP BPM
        "success": ("#00cc66", "✔"),  # vert  : succès générique
        "error":   ("#ff4444", "✖"),  # rouge : erreur
        "warn":    ("#ff9900", "⚠"),  # orange: avertissement
        "info":    ("#555555", "·"),  # gris  : info
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(3)

        # ── En-tête ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(2, 0, 2, 0)

        title = QLabel("Journal")
        title.setStyleSheet(
            "color:#555; font-size:9px; font-weight:bold; "
            "background:transparent; border:none;"
        )
        hdr.addWidget(title)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            "color:#3a3a3a; font-size:9px; background:transparent; border:none;"
        )
        hdr.addWidget(self._count_lbl)
        hdr.addStretch()

        clear_btn = QPushButton("✕ Vider")
        clear_btn.setFixedHeight(13)
        clear_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#3a3a3a; font-size:8px; "
            "border:none; padding:0 4px; } "
            "QPushButton:hover { color:#888; }"
        )
        clear_btn.clicked.connect(self.clear)
        hdr.addWidget(clear_btn)
        root.addLayout(hdr)

        # ── Zone texte ──────────────────────────────────────────────────────
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.NoWrap)
        self._text.setMinimumHeight(60)
        self._text.setStyleSheet(
            "QTextEdit { background:#0c0c0c; color:#555; "
            "border:1px solid #1e1e1e; border-radius:4px; "
            "font-size:10px; font-family:'Consolas','Courier New',monospace; "
            "padding:3px 6px; } "
            "QScrollBar:vertical { background:#111; width:5px; border:none; } "
            "QScrollBar::handle:vertical { background:#2a2a2a; border-radius:2px; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
        )
        root.addWidget(self._text)

    def append_message(self, text: str, level: str = "info"):
        """Ajoute une ligne horodatée dans le journal."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        color, bullet = self._LEVELS.get(level, ("#555555", "·"))
        # Texte en gris atténué pour les infos, couleur complète pour les autres
        text_color = color if level != "info" else "#666"
        html = (
            f'<span style="color:#2e2e2e;">[{ts}]</span>'
            f'&nbsp;<span style="color:{color};font-weight:bold;">{bullet}</span>'
            f'&nbsp;<span style="color:{text_color};">{text}</span>'
        )
        self._text.append(html)
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._count += 1
        self._count_lbl.setText(f"({self._count})")

    def clear(self):
        """Vide le journal."""
        self._text.clear()
        self._count = 0
        self._count_lbl.setText("")


# ---------------------------------------------------------------------------
# Editeur de layout AKAI APC mini
# ---------------------------------------------------------------------------

# Options disponibles dans le dropdown par colonne
_MEM_COL_MAX = 99
_FX_COL_MAX  = 8
_AKAI_SLOT_OPTIONS = (
    ["A", "B", "C", "D", "E", "F"]
    + [f"MEM {i}" for i in range(1, _MEM_COL_MAX + 1)]
    + [f"FX {i}"  for i in range(1, _FX_COL_MAX + 1)]
)


class AkaiDiagnosticDialog(QDialog):
    """Fenêtre de diagnostic contrôleur MIDI : statut ports, activité en direct."""

    def __init__(self, midi_handler, parent=None):
        super().__init__(parent)
        ctrl_name = getattr(midi_handler, 'controller_name', '') or "Contrôleur MIDI"
        self.setWindowTitle(f"Diagnostic — {ctrl_name}")
        self.setFixedSize(440, 360)
        self.setModal(True)
        self._midi = midi_handler
        self._activity_count = 0

        self.setStyleSheet("""
            QDialog  { background: #111; color: #ddd; }
            QLabel   { background: transparent; border: none; color: #ddd; }
            QFrame   { border: none; }
            QPushButton {
                background: #1e1e1e; color: #ccc;
                border: 1px solid #333; border-radius: 6px;
                font-size: 10px; padding: 6px 14px;
            }
            QPushButton:hover { background: #2a2a2a; color: #fff; border-color: #555; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        # ── Titre ──────────────────────────────────────────────────────────
        title = QLabel(f"🎹  {ctrl_name}")
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setStyleSheet("color:#fff;")
        root.addWidget(title)

        # Sous-titre : contrôleurs supportés
        supported_lbl = QLabel("Supportés : AKAI APC Mini · Launchpad Mini MK1/MK2 · AKAI MIDImix")
        supported_lbl.setStyleSheet("color:#555; font-size:9px;")
        root.addWidget(supported_lbl)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#222; max-height:1px;")
        root.addWidget(sep)

        # ── Statut ports ───────────────────────────────────────────────────
        def _port_row(label, ok):
            row = QHBoxLayout()
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{'#4CAF50' if ok else '#f44336'}; font-size:11px;")
            row.addWidget(dot)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{'#ccc' if ok else '#888'}; font-size:10px;")
            row.addWidget(lbl)
            row.addStretch()
            status = QLabel("Connecté" if ok else "Non détecté")
            status.setStyleSheet(f"color:{'#4CAF50' if ok else '#f44336'}; font-size:10px; font-weight:bold;")
            row.addWidget(status)
            return row

        try:
            in_ok  = bool(midi_handler.midi_in  and midi_handler.midi_in.is_port_open())
            out_ok = bool(midi_handler.midi_out and midi_handler.midi_out.is_port_open())
        except Exception:
            in_ok = out_ok = False

        root.addLayout(_port_row("Entrée MIDI  (contrôleur → logiciel)", in_ok))
        root.addLayout(_port_row("Sortie MIDI  (logiciel → LEDs contrôleur)", out_ok))

        # ── Ports disponibles ──────────────────────────────────────────────
        try:
            import rtmidi2 as _rm
            ports = _rm.get_in_ports()
        except Exception:
            try:
                import rtmidi as _rm2
                _tmp = _rm2.MidiIn()
                ports = [_tmp.get_port_name(i) for i in range(_tmp.get_port_count())]
            except Exception:
                ports = []

        ports_lbl = QLabel("Ports MIDI détectés : " + (", ".join(ports) if ports else "aucun"))
        ports_lbl.setStyleSheet("color:#555; font-size:9px;")
        ports_lbl.setWordWrap(True)
        root.addWidget(ports_lbl)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background:#222; max-height:1px;")
        root.addWidget(sep2)

        # ── Activité MIDI en direct ────────────────────────────────────────
        act_row = QHBoxLayout()
        act_lbl = QLabel("Activité MIDI :")
        act_lbl.setStyleSheet("color:#777; font-size:10px;")
        act_row.addWidget(act_lbl)
        self._act_dot = QLabel("●")
        self._act_dot.setStyleSheet("color:#333; font-size:14px;")
        act_row.addWidget(self._act_dot)
        self._act_info = QLabel("En attente…")
        self._act_info.setStyleSheet("color:#555; font-size:9px;")
        act_row.addWidget(self._act_info)
        act_row.addStretch()
        root.addLayout(act_row)

        # Timer pour faire clignoter le dot (on_midi_pad/fader notifie via signal)
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._dim_activity)
        self._blink_timer.start(300)

        # On écoute les signaux MIDI du handler
        midi_handler.pad_pressed.connect(self._on_midi_activity)
        midi_handler.fader_changed.connect(self._on_midi_activity)

        root.addStretch()

        # ── Boutons ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        reconnect_btn = QPushButton("🔄  Reconnecter")
        reconnect_btn.setStyleSheet(
            "QPushButton { background:#0a3a5a; color:white; border:none; "
            "border-radius:6px; font-size:10px; font-weight:bold; padding:6px 16px; } "
            "QPushButton:hover { background:#0d4e7a; }"
        )
        reconnect_btn.clicked.connect(self._do_reconnect)
        btn_row.addWidget(reconnect_btn)
        btn_row.addSpacing(8)

        close_btn = QPushButton("Fermer")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _on_midi_activity(self, *args):
        self._act_dot.setStyleSheet("color:#FFE000; font-size:14px;")
        self._act_info.setStyleSheet("color:#ccc; font-size:9px;")
        self._act_info.setText("Signal reçu")
        self._activity_count = 6  # durée du flash

    def _dim_activity(self):
        if self._activity_count > 0:
            self._activity_count -= 1
            if self._activity_count == 0:
                self._act_dot.setStyleSheet("color:#333; font-size:14px;")
                self._act_info.setText("En attente…")
                self._act_info.setStyleSheet("color:#555; font-size:9px;")

    def _do_reconnect(self):
        self._midi.connect_akai()
        self.accept()

    def closeEvent(self, e):
        try:
            self._midi.pad_pressed.disconnect(self._on_midi_activity)
            self._midi.fader_changed.disconnect(self._on_midi_activity)
        except Exception:
            pass
        super().closeEvent(e)


class _FaderPreview(QWidget):
    """Mini fader AKAI : 8 pads + fader identique à ApcFader (vertical=False)."""
    _TYPE_COLORS = {
        "group":  QColor("#e0e0e0"),
        "memory": QColor("#00aaff"),
        "fx":     QColor("#44dd44"),
    }
    _PAD_H  = 5
    _PAD_GAP = 2
    _FADER_H = 38   # hauteur réservée au fader sous les pads

    def __init__(self, slot_type="group", parent=None):
        super().__init__(parent)
        total = 8 * self._PAD_H + 7 * self._PAD_GAP + 6 + self._FADER_H
        self.setFixedSize(36, total)
        self._slot_type = slot_type

    def set_slot_type(self, slot_type):
        self._slot_type = slot_type
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w = self.width()
        base = self._TYPE_COLORS.get(self._slot_type, QColor("#555"))

        # ── 8 pads ──────────────────────────────────────────────────────────
        x0, pad_w = 3, w - 6
        for row in range(8):
            y = row * (self._PAD_H + self._PAD_GAP)
            bright = 1.0 if row == 0 else 0.18
            c = QColor(int(base.red()*bright), int(base.green()*bright), int(base.blue()*bright))
            p.setBrush(c)
            p.drawRoundedRect(x0, y, pad_w, self._PAD_H, 1, 1)

        # ── Fader (style ApcFader vertical=False) ───────────────────────────
        fy0 = 8 * (self._PAD_H + self._PAD_GAP) + 4   # y de départ du fader
        fh  = self._FADER_H
        # piste centrale
        track_x = w // 2 - 2
        p.setBrush(QColor("#333"))
        p.drawRoundedRect(track_x, fy0 + 4, 4, fh - 8, 2, 2)
        # curseur blanc à 50 %
        knob_y = fy0 + fh // 2 - 5
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(3, knob_y, w - 6, 10, 3, 3)

        p.end()


class _SlotPickerPopup(QFrame):
    """Popup de sélection avec recherche + grille multi-colonnes."""
    selected = Signal(str)

    _GROUP_COLOR = "#1a3a5c"
    _MEM_COLOR   = "#1a3a1a"
    _FX_COLOR    = "#3a2a1a"

    def __init__(self, options, current, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet(
            "QFrame { background:#1a1a1a; border:1px solid #3a3a3a; border-radius:6px; }"
            "QLineEdit { background:#111; color:#ddd; border:1px solid #333; border-radius:4px;"
            "            padding:3px 6px; font-size:10px; }"
            "QPushButton { border-radius:3px; font-size:9px; padding:2px 4px; }"
            "QLabel { color:#666; font-size:9px; background:transparent; border:none; }"
            "QScrollArea { border:none; background:transparent; }"
        )
        self._options = options
        self._all_btns = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # Champ recherche
        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher… (A, MEM 5, FX 2)")
        self._search.setFixedHeight(26)
        self._search.textChanged.connect(self._filter)
        lay.addWidget(self._search)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedSize(520, 320)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        self._inner_lay = QVBoxLayout(inner)
        self._inner_lay.setContentsMargins(2, 2, 2, 2)
        self._inner_lay.setSpacing(6)
        scroll.setWidget(inner)
        lay.addWidget(scroll)

        self._build_grid(current)
        self._search.setFocus()

    def _btn_style(self, color, active=False):
        bg     = color if not active else QColor(color).lighter(160).name()
        border = "#ffffff" if active else QColor(color).lighter(140).name()
        return (f"QPushButton {{ background:{bg}; color:#ddd; border:1px solid {border}; }}"
                f"QPushButton:hover {{ background:{QColor(color).lighter(150).name()}; color:#fff; }}")

    def _build_grid(self, current):
        groups = ["A", "B", "C", "D", "E", "F"]
        fx     = [f"FX {i}" for i in range(1, _FX_COL_MAX + 1)]
        mems   = [f"MEM {i}" for i in range(1, _MEM_COL_MAX + 1)]

        # Groupes
        self._add_section("Groupes", groups, self._GROUP_COLOR, current)
        # FX
        self._add_section("FX", fx, self._FX_COLOR, current)
        # MEM — grille 10 colonnes
        self._add_section("Mémoires", mems, self._MEM_COLOR, current, cols=10)

        self._inner_lay.addStretch()

    def _add_section(self, title, items, color, current, cols=6):
        lbl = QLabel(title.upper())
        lbl.setStyleSheet("color:#555; font-size:8px; letter-spacing:1px; background:transparent; border:none;")
        self._inner_lay.addWidget(lbl)

        grid_w = QWidget()
        grid_w.setStyleSheet("background:transparent;")
        grid    = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)

        for i, item in enumerate(items):
            btn = QPushButton(item)
            btn.setFixedSize(44, 22)
            active = (item == current)
            btn.setStyleSheet(self._btn_style(color, active))
            btn.clicked.connect(lambda _, v=item: self._pick(v))
            grid.addWidget(btn, i // cols, i % cols)
            self._all_btns.append((item, btn, lbl))

        self._inner_lay.addWidget(grid_w)

    def _pick(self, value):
        self.selected.emit(value)
        self.close()

    def _filter(self, text):
        text = text.lower().strip()
        for item, btn, section_lbl in self._all_btns:
            btn.setVisible(not text or text in item.lower())


class _SlotPickerButton(QPushButton):
    """Bouton qui remplace QComboBox — ouvre _SlotPickerPopup au clic."""
    currentTextChanged = Signal(str)

    def __init__(self, options, current, parent=None):
        super().__init__(parent)
        self._options = options
        self._current = current
        self._update_label()
        self.setFixedWidth(68)
        self.setFixedHeight(14)
        self.setStyleSheet(
            "QPushButton { color:#666; font-size:9px; background:transparent; border:none; padding:0; }"
            "QPushButton:hover { color:#aaa; text-decoration:underline; }"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._open_popup)

    def _update_label(self):
        self.setText(self._current)

    def currentText(self):
        return self._current

    def setCurrentText(self, text):
        if text != self._current and text in self._options:
            self._current = text
            self._update_label()
            self.currentTextChanged.emit(text)

    def _open_popup(self):
        popup = _SlotPickerPopup(self._options, self._current, self.window())
        popup.selected.connect(self.setCurrentText)
        pos = self.mapToGlobal(self.rect().bottomLeft())
        popup.move(pos)
        popup.show()
        popup.adjustSize()


class AkaiLayoutEditorDialog(QDialog):
    """Fenetre d'edition des 8 colonnes AKAI — représentation visuelle du contrôleur."""

    # ── Couleurs par type d'assignation ──────────────────────────────────────
    _GROUP_COLORS = {
        "A": "#cc4400", "B": "#4488cc", "C": "#44aa44",
        "D": "#aaaa00", "E": "#aa44aa", "F": "#00aaaa",
    }
    _MEM_COLOR   = "#1a6688"
    _FX_COLOR    = "#7722aa"
    _EMPTY_COLOR = "#2a2a2a"

    def __init__(self, slots, last_fader_mode="FX", superposition=False, go_mode=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("akai_cfg_title"))
        self.setFixedSize(700, 340)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog  { background: #111; color: #ddd; }
            QLabel   { background: transparent; border: none; color: #ddd; }
            QComboBox {
                background: #1a1a1a; color: #ddd;
                border: 1px solid #2a2a2a; border-radius: 5px;
                padding: 3px 6px; font-size: 9px; font-family: 'Segoe UI';
            }
            QComboBox::drop-down { border: none; width: 14px; }
            QComboBox QAbstractItemView {
                background: #1a1a1a; color: #ddd;
                selection-background-color: #0077bb;
            }
            QCheckBox { color: #bbb; font-size: 10px; spacing: 8px; }
            QCheckBox::indicator {
                width: 15px; height: 15px; border: 1px solid #444;
                border-radius: 4px; background: #1a1a1a;
            }
            QCheckBox::indicator:checked { background: #0077bb; border-color: #0099dd; }
            QCheckBox:hover { color: #fff; }
        """)

        self._combos = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ── Header ─────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("🎹  " + tr("akai_cfg_title"))
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setStyleSheet("color:#fff;")
        hdr.addWidget(title)
        hdr.addStretch()
        preset_btn = QPushButton(tr("btn_preset"))
        preset_btn.setFixedSize(80, 28)
        preset_btn.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #aaa; border: 1px solid #333; "
            "border-radius: 6px; font-size: 10px; } "
            "QPushButton:hover { background: #2a2a2a; color: #fff; border-color: #555; }"
        )
        preset_btn.clicked.connect(self._load_preset)
        hdr.addWidget(preset_btn)
        root.addLayout(hdr)

        # ── Grille des 8 faders ───────────────────────────────────────────────
        # Carte conteneur
        card = QFrame()
        card.setStyleSheet("QFrame { background: #1a1a1a; border: 1px solid #252525; border-radius: 8px; }")
        card_lay = QHBoxLayout(card)
        card_lay.setContentsMargins(16, 14, 16, 14)
        card_lay.setSpacing(10)

        for col in range(8):
            slot = slots[col] if col < len(slots) else {"type": "group", "group": "A"}
            current_val = self._slot_to_option(slot)

            col_w = QWidget()
            col_w.setStyleSheet("background: transparent; border: none;")
            col_l = QVBoxLayout(col_w)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(5)
            col_l.setAlignment(Qt.AlignHCenter)

            # Numéro du fader
            num_lbl = QLabel(str(col + 1))
            num_lbl.setAlignment(Qt.AlignCenter)
            num_lbl.setStyleSheet("color:#555; font-size:9px; font-weight:bold;")
            col_l.addWidget(num_lbl)

            # Picker d'assignation
            combo = _SlotPickerButton(_AKAI_SLOT_OPTIONS, current_val)
            combo.currentTextChanged.connect(lambda txt, c=col: self._on_col_changed(c, txt))
            self._combos.append(combo)
            col_l.addWidget(combo)

            card_lay.addWidget(col_w)
            self._on_col_changed(col, current_val)

        # Séparateur + fader 9
        sep9 = QFrame()
        sep9.setFrameShape(QFrame.VLine)
        sep9.setStyleSheet("background:#2a2a2a; border:none; max-width:1px;")
        card_lay.addWidget(sep9)

        f9_w = QWidget()
        f9_w.setStyleSheet("background: transparent; border: none;")
        f9_l = QVBoxLayout(f9_w)
        f9_l.setContentsMargins(0, 0, 0, 0)
        f9_l.setSpacing(5)
        f9_l.setAlignment(Qt.AlignHCenter)
        num9 = QLabel("9")
        num9.setAlignment(Qt.AlignCenter)
        num9.setStyleSheet("color:#0088cc; font-size:9px; font-weight:bold;")
        f9_l.addWidget(num9)
        lbl9 = QLabel(tr("akai_amp_fx_label"))
        lbl9.setAlignment(Qt.AlignCenter)
        lbl9.setWordWrap(True)
        lbl9.setFixedWidth(68)
        lbl9.setStyleSheet("color:#0088cc; font-size:8px;")
        f9_l.addWidget(lbl9)
        card_lay.addWidget(f9_w)

        root.addWidget(card)

        # ── Options ───────────────────────────────────────────────────────────
        opts_row = QHBoxLayout()
        opts_row.setSpacing(24)

        self._superposition_check = QCheckBox(tr("fx_superposition_lbl"))
        self._superposition_check.setChecked(superposition)
        self._superposition_check.setToolTip(tr("fx_superposition_tip"))
        opts_row.addWidget(self._superposition_check)

        self._go_mode_check = QCheckBox(tr("go_mode_lbl"))
        self._go_mode_check.setChecked(go_mode)
        self._go_mode_check.setToolTip(tr("go_mode_tip"))
        opts_row.addWidget(self._go_mode_check)

        opts_row.addStretch()
        root.addLayout(opts_row)

        root.addStretch()

        # ── Boutons ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton(tr("btn_annuler"))
        cancel_btn.setFixedSize(90, 32)
        cancel_btn.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #aaa; border: 1px solid #333; "
            "border-radius: 6px; font-size: 10px; } "
            "QPushButton:hover { background: #2a2a2a; color: #fff; }"
        )
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(tr("btn_apply"))
        ok_btn.setFixedSize(110, 32)
        ok_btn.setStyleSheet(
            "QPushButton { background: #0077bb; color: white; border: none; "
            "border-radius: 6px; font-size: 10px; font-weight: bold; } "
            "QPushButton:hover { background: #0099dd; }"
        )
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    # ── Mise à jour couleur colonne ───────────────────────────────────────────
    def _col_color(self, option):
        if option in self._GROUP_COLORS:
            return self._GROUP_COLORS[option]
        if option.startswith("MEM "):
            return self._MEM_COLOR
        if option.startswith("FX "):
            return self._FX_COLOR
        return self._EMPTY_COLOR

    def _on_col_changed(self, col, option):
        """Colore le combo selon le type d'assignation."""
        color = self._col_color(option)
        if col < len(self._combos):
            self._combos[col].setStyleSheet(
                f"QPushButton {{ color:{color}; font-size:9px; background:transparent; border:none; padding:0; }}"
                f"QPushButton:hover {{ color:{QColor(color).lighter(140).name()}; text-decoration:underline; }}"
            )


    # ── Preset ────────────────────────────────────────────────────────────────
    _USER_PRESETS_PATH = str(Path.home() / ".maestro_akai_user_presets.json")

    @classmethod
    def _read_user_presets(cls):
        try:
            with open(cls._USER_PRESETS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    @classmethod
    def _write_user_presets(cls, presets):
        with open(cls._USER_PRESETS_PATH, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)

    def _apply_slots(self, slots):
        for i, combo in enumerate(self._combos):
            slot = slots[i] if i < len(slots) else {"type": "group", "group": "A"}
            combo.setCurrentText(self._slot_to_option(slot))

    def _load_preset(self):
        _MENU_SS = (
            "QMenu { background:#1a1a1a; color:#ccc; border:1px solid #3a3a3a; } "
            "QMenu::item { padding:5px 18px; } "
            "QMenu::item:selected { background:#0077bb; } "
            "QMenu::separator { height:1px; background:#2a2a2a; margin:4px 0; }"
        )
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_SS)

        # ── Presets intégrés ──
        lbl_builtin = QAction("— Presets intégrés —", menu)
        lbl_builtin.setEnabled(False)
        menu.addAction(lbl_builtin)
        for preset in AKAI_BANK_PRESETS:
            a = menu.addAction(preset["label"])
            a.setData(("load", preset["slots"]))

        # ── Presets utilisateur ──
        user_presets = self._read_user_presets()
        if user_presets:
            menu.addSeparator()
            lbl_user = QAction("— Mes presets —", menu)
            lbl_user.setEnabled(False)
            menu.addAction(lbl_user)
            for up in user_presets:
                sub = menu.addMenu(up["label"])
                sub.setStyleSheet(_MENU_SS)
                load_a = sub.addAction("✅  Charger")
                load_a.setData(("load", up["slots"]))
                del_a  = sub.addAction("🗑  Supprimer")
                del_a.setData(("delete", up["label"]))

        # ── Sauvegarder ──
        menu.addSeparator()
        save_a = menu.addAction("💾  Sauvegarder le layout actuel…")
        save_a.setData(("save", None))

        btn = self.sender()
        chosen = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if not chosen or chosen.data() is None:
            return
        action, payload = chosen.data()

        if action == "load":
            self._apply_slots(payload)

        elif action == "save":
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "Sauvegarder preset", "Nom du preset :")
            if not ok or not name.strip():
                return
            name = name.strip()
            current_slots = self.get_slots()
            presets = self._read_user_presets()
            # Remplacer si même nom
            presets = [p for p in presets if p["label"] != name]
            presets.append({"label": name, "slots": current_slots})
            self._write_user_presets(presets)

        elif action == "delete":
            presets = self._read_user_presets()
            presets = [p for p in presets if p["label"] != payload]
            self._write_user_presets(presets)

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _slot_to_option(slot):
        if slot.get("type") == "memory":
            return f"MEM {slot.get('mem_col', 0) + 1}"
        if slot.get("type") == "fx":
            return f"FX {slot.get('fx_col', 0) + 1}"
        return slot.get("group", slot.get("label", "A"))

    # ── Résultat ─────────────────────────────────────────────────────────────
    def get_superposition(self):
        return self._superposition_check.isChecked()

    def get_go_mode(self):
        return self._go_mode_check.isChecked()

    def get_slots(self):
        slots = []
        for combo in self._combos:
            val = combo.currentText()
            if val.startswith("MEM "):
                mem_col = int(val.split()[1]) - 1
                slots.append({"type": "memory", "mem_col": mem_col, "label": val})
            elif val.startswith("FX "):
                fx_col = int(val.split()[1]) - 1
                slots.append({"type": "fx", "fx_col": fx_col, "label": val})
            else:
                slots.append({"type": "group", "group": val, "label": val})
        return slots

    def get_last_fader_mode(self):
        return "FX"


class VideoOutputWindow(QWidget):
    """Fenetre de sortie video plein ecran sur un second moniteur"""

    PAGE_VIDEO = 0
    PAGE_BLACK = 1
    PAGE_IMAGE = 2

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(tr("video_output_title"))
        self.setStyleSheet("background: black;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Page 0 : Video
        if QVideoWidget is not None:
            self.video_widget = QVideoWidget()
            self.video_widget.setStyleSheet("background: black;")
            self.stack.addWidget(self.video_widget)
        else:
            self.video_widget = None
            _placeholder = QWidget()
            _placeholder.setStyleSheet("background: black;")
            self.stack.addWidget(_placeholder)

        # Page 1 : Ecran noir
        self.black_label = QLabel()
        self.black_label.setStyleSheet("background: black;")
        self.stack.addWidget(self.black_label)

        # Page 2 : Image
        self.image_label = QLabel()
        self.image_label.setStyleSheet("background: black;")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.image_label)

        self.stack.setCurrentIndex(self.PAGE_BLACK)

        # Watermark overlay (licence)
        self._watermark = None

    def set_watermark(self, visible):
        """Affiche ou masque le watermark de licence"""
        if visible and not self._watermark:
            self._watermark = QLabel(self)
            self._watermark.setAlignment(Qt.AlignCenter)
            self._watermark.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._create_watermark_pixmap()
            self._watermark.show()
            self._watermark.raise_()
        elif not visible and self._watermark:
            self._watermark.hide()
            self._watermark.deleteLater()
            self._watermark = None

    def _create_watermark_pixmap(self):
        """Cree le pixmap du watermark"""
        if not self._watermark:
            return
        import os
        base = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base, "Mystrow_blanc.png")
        if os.path.exists(logo_path):
            px = QPixmap(logo_path)
            # 30% de la taille de la fenetre
            target_w = max(200, int(self.width() * 0.3))
            scaled = px.scaledToWidth(target_w, Qt.SmoothTransformation)
            # Appliquer opacite 40%
            result = QPixmap(scaled.size())
            result.fill(Qt.transparent)
            painter = QPainter(result)
            painter.setOpacity(0.4)
            painter.drawPixmap(0, 0, scaled)
            painter.end()
            self._watermark.setPixmap(result)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._watermark:
            self._create_watermark_pixmap()
            # Centrer le watermark
            wm_size = self._watermark.sizeHint()
            x = (self.width() - wm_size.width()) // 2
            y = (self.height() - wm_size.height()) // 2
            self._watermark.setGeometry(x, y, wm_size.width(), wm_size.height())

    def show_black(self):
        """Affiche un ecran noir"""
        self.stack.setCurrentIndex(self.PAGE_BLACK)

    def show_video(self):
        """Affiche la video"""
        self.stack.setCurrentIndex(self.PAGE_VIDEO)

    def show_image(self, pixmap):
        """Affiche une image"""
        scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.stack.setCurrentIndex(self.PAGE_IMAGE)

    def closeEvent(self, event):
        """Cacher au lieu de detruire"""
        self.hide()
        event.ignore()


def _mk_sep(style):
    lbl = QLabel("|")
    lbl.setStyleSheet(style)
    return lbl


class _MasterMeter(QWidget):
    """Affichage du niveau audio sous forme de blocs avec peak-hold."""
    _SEG = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.0     # 0.0-1.0
        self._peak  = 0.0     # peak-hold
        self._peak_hold = 0   # compteur de frames restantes
        self.setFixedSize(self._SEG * 5 + (self._SEG - 1) * 2, 8)

    def set_level(self, v: float):
        """v : float 0.0-1.0"""
        v = max(0.0, min(1.0, v))
        self._level = v
        if v >= self._peak:
            self._peak = v
            self._peak_hold = 30          # ~1.2 s à 25 FPS
        else:
            if self._peak_hold > 0:
                self._peak_hold -= 1
            else:
                self._peak = max(0.0, self._peak - 0.03)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        lit  = round(self._level * self._SEG)
        peak = round(self._peak  * self._SEG)
        seg_w, h, gap = 5, 8, 2
        for i in range(self._SEG):
            x = i * (seg_w + gap)
            if i < lit:
                if i < self._SEG * 0.70:
                    c = QColor(45, 185, 70)
                elif i < self._SEG * 0.88:
                    c = QColor(210, 140, 15)
                else:
                    c = QColor(210, 45, 35)
            elif i == peak and peak > 0:
                # Segment peak-hold en blanc
                c = QColor(220, 220, 220)
            else:
                c = QColor(35, 35, 35)
            p.fillRect(x, 0, seg_w, h, c)


class _StatusCornerWidget(QWidget):
    """Widget coin de la menubar : audio meter · CPU · Horloge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 12, 0)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignVCenter)

        _lbl = "color:#777; font-size:9px; font-weight:bold;"
        _sep = "color:#333; font-size:9px; font-weight:bold;"
        _val = "color:#ccc; font-size:9px; font-weight:bold;"

        # ── MASTER ───────────────────────────────────────────
        lbl_m = QLabel("MASTER")
        lbl_m.setStyleSheet(_lbl)
        lay.addWidget(lbl_m, alignment=Qt.AlignVCenter)

        self._meter = _MasterMeter()
        lay.addWidget(self._meter, alignment=Qt.AlignVCenter)

        # Rond indicateur (joue = vert, muet = gris)
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#333; font-size:8pt;")
        lay.addWidget(self._dot, alignment=Qt.AlignVCenter)

        # ── Séparateur ───────────────────────────────────────
        lay.addWidget(_mk_sep(_sep), alignment=Qt.AlignVCenter)

        # ── CPU ──────────────────────────────────────────────
        lbl_cpu = QLabel("CPU")
        lbl_cpu.setStyleSheet(_lbl)
        lay.addWidget(lbl_cpu, alignment=Qt.AlignVCenter)

        self._cpu_val = QLabel("--")
        self._cpu_val.setStyleSheet(_val)
        self._cpu_val.setFixedWidth(34)
        lay.addWidget(self._cpu_val, alignment=Qt.AlignVCenter)

        # ── Séparateur ───────────────────────────────────────
        lay.addWidget(_mk_sep(_sep), alignment=Qt.AlignVCenter)

        # ── Horloge ──────────────────────────────────────────
        self._clock = QLabel("--:--:--")
        self._clock.setStyleSheet(_val)
        self._clock.setFixedWidth(54)
        lay.addWidget(self._clock, alignment=Qt.AlignVCenter)

        # Timer horloge
        self._tick_clock = QTimer(self)
        self._tick_clock.timeout.connect(self._update_clock)
        self._tick_clock.start(1000)
        self._update_clock()

        # Timer CPU (toutes les 1.5 s)
        if _psutil is not None:
            _psutil.cpu_percent(interval=None)
            self._tick_cpu = QTimer(self)
            self._tick_cpu.timeout.connect(self._update_cpu)
            self._tick_cpu.start(1500)
            QTimer.singleShot(800, self._update_cpu)

    def set_audio(self, level: float, playing: bool):
        """level : 0.0-1.0. Appelé à 25 FPS."""
        self._meter.set_level(level)
        self._dot.setStyleSheet(
            "color:#2a9a45; font-size:8pt;" if playing
            else "color:#333; font-size:8pt;"
        )

    def _update_clock(self):
        self._clock.setText(_dt.datetime.now().strftime("%H:%M:%S"))

    def _update_cpu(self):
        if _psutil is None:
            return
        pct = _psutil.cpu_percent(interval=None)
        self._cpu_val.setText(f"{pct:.0f}%")
        if pct > 80:
            col = "#cc4444"
        elif pct > 50:
            col = "#d4a020"
        else:
            col = "#ccc"
        self._cpu_val.setStyleSheet(f"color:{col}; font-size:9px; font-weight:bold;")


class MainWindow(QMainWindow):
    """Fenetre principale de l'application"""

    def __init__(self, license_result=None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1800, 1000)

        # Licence (resultat cache pour toute la session)
        self._license = license_result or LicenseResult(
            state=LicenseState.NOT_ACTIVATED,
            dmx_allowed=False, watermark_required=True,
            message=tr("lic_fallback_msg"), action_label=tr("lic_fallback_action")
        )

        # Icone de l'application
        self._create_window_icon()

        # Creation des projecteurs (fixtures)
        self._load_default_fixtures()

        # Variables d'etat
        self.active_pads = {}  # {col_idx: QPushButton} - un pad actif par colonne
        self._mem_rec_mode = False   # mode REC memoire en attente de clic pad
        self._rec_mem_btn = None     # reference au bouton REC
        self._tap_times = []         # timestamps des taps pour calcul BPM
        self._tap_btn = None         # reference au bouton tap tempo
        self.active_dual_pad = None
        self.audio_ai = AudioColorAI()
        self._ia_fadeout_timer = None
        self._ia_fadeout_levels = {}
        self._ia_fadeout_steps = 0
        self._ia_fadeout_total = 30   # 30 × 50 ms = 1.5 s
        self._ia_fadeout_callback = None
        self.fader_buttons = []
        self._muted_faders: set = set()
        self.faders = {}
        self.pads = {}
        self.effect_buttons = []
        self.active_effect = None
        self.effect_superposition = False   # True = plusieurs effets simultanés
        self._stacked_effects = []          # liste de dicts d'état par effet (mode superposition)
        self.go_mode = False                # True = bouton TAP devient GO (avance mémoires)
        self._go_col = -1                   # colonne mémoire courante en mode GO (-1 = pas démarré)
        self._go_row = -1                   # rangée mémoire courante en mode GO
        self.effect_speed = 0
        self.effect_amplitude = 100   # amplitude globale effets (fader 9), 0-100
        self.effect_state = 0
        self.effect_saved_colors = {}
        self._button_effect_configs = self._load_effect_assignments()  # {btn_idx: config_dict from editor}
        self._effect_library_configs = self._load_effect_library()    # {effect_name: config_dict}
        self.active_effect_config = {}     # config en cours d'exécution
        self.blink_timer = None
        self.pause_mode = False

        # Layout AKAI personnalisable (8 slots, éditables via AkaiLayoutEditorDialog)
        self._custom_bank_slots = [dict(s) for s in AKAI_BANK_PRESETS[0]["slots"]]
        self.memories = [[None]*8 for _ in range(_MEM_COL_MAX)]
        self.memory_custom_colors = [[None]*8 for _ in range(_MEM_COL_MAX)]
        self.active_memory_pads = {}  # {fader_idx: row} pad actif par colonne memoire
        self._mem_cue_idx = {}        # {(col, row): int} index cue courant par pad

        # — Fade entre cues (interpolation DMX 40 fps)
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(25)
        self._fade_timer.timeout.connect(self._fade_tick)
        self._fade_from: list = []
        self._fade_to:   list = []
        self._fade_start  = 0.0
        self._fade_dur    = 0.0

        # — Durée auto-avance
        self._dur_timer = QTimer(self)
        self._dur_timer.setSingleShot(True)
        self._dur_timer.timeout.connect(self._on_duration_elapsed)
        self._dur_mem_col = -1
        self._dur_row     = -1
        self._dur_start   = 0.0
        self._dur_secs    = 0.0

        # — Mise à jour barre de progression (10 fps)
        self._dur_progress_timer = QTimer(self)
        self._dur_progress_timer.setInterval(100)
        self._dur_progress_timer.timeout.connect(self._update_cue_progress)
        self.fx_pads = [[None]*8 for _ in range(_FX_COL_MAX)]
        self.active_fx_pads = {}       # {(fx_col, row): True}
        self.fx_amplitudes = [100] * _FX_COL_MAX

        # Configuration AKAI
        self.akai_active_brightness = 100
        self.akai_inactive_brightness = 20
        self.blackout_active = False
        self._last_fader_mode = "FX"   # "FX" ou "MASTER" pour le fader 9
        self.master_level = 100        # 0-100, appliqué en sortie DMX

        # DMX Art-Net Handler
        self.dmx = ArtNetDMX()
        self._saved_custom_profiles = {}
        self.auto_patch_at_startup()

        self.dmx_send_timer = QTimer()
        self.dmx_send_timer.timeout.connect(self.send_dmx_update)
        self.dmx_send_timer.timeout.connect(self._update_status_corner)
        self.dmx_send_timer.start(40)  # 25 FPS

        # Timer pour drainer les events venant de la tablette (50 ms)
        self._tablet_event_timer = QTimer()
        self._tablet_event_timer.timeout.connect(self._drain_tablet_events)
        self._tablet_event_timer.start(50)

        # MIDI Handler
        self.midi_handler = MIDIHandler()
        self.midi_handler.owner_window = self
        self.midi_handler.fader_changed.connect(self.on_midi_fader)
        self.midi_handler.pad_pressed.connect(self.on_midi_pad)

        # Dimmers max IA Lumiere par groupe
        self.ia_max_dimmers = {
            'face': 50, 'lat': 100, 'contre': 100,
            'douche1': 100, 'douche2': 100, 'douche3': 100,
            'public': 80, 'groupe_e': 100, 'groupe_f': 100,
        }
        # Paramètres avancés IA Lumiere
        self.ia_params = {
            'nervosity':   50,            # 0-100 : réactivité générale
            'drop_effect': 'flash_blanc', # type d'effet sur les drops
        }
        self.load_ia_lumiere_config()

        # Fichiers recents
        self.recent_files = self.load_recent_files()
        self.current_show_path = None  # Chemin du show actuellement ouvert

        # Creation du menu
        self._create_menu()

        # Creation du panneau AKAI
        self.akai = self.create_akai_panel()

        # Player
        self.audio = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio)
        self.player_ui = type('obj', (object,), {
            'player': self.player,
            'audio': self.audio,
            'play': self.play_path,
            'trigger_pause': self.trigger_pause_mode
        })

        # Video frame
        self._create_video_frame()

        # Cartoucheur - player dedie
        self.cart_audio = QAudioOutput()
        self.cart_player = QMediaPlayer()
        self.cart_player.setAudioOutput(self.cart_audio)
        self.cart_player.mediaStatusChanged.connect(self.on_cart_media_status)
        self.cart_playing_index = -1

        # Sequenceur
        self.seq = Sequencer(self)
        self.seq.table.cellDoubleClicked.connect(self.seq.play_row)
        self.seq.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._autosave_lbl = self.seq.autosave_lbl   # référence pour _autosave()

        # Transport
        self.transport = self.create_transport_panel()

        # Timer IA
        self.ai_timer = QTimer(self)
        self.ai_timer.timeout.connect(self.update_audio_ai)
        self.ai_timer.start(100)

        self.player.mediaStatusChanged.connect(self.on_media_status_changed)

        # Layout principal
        self._create_main_layout()

        self.player.playbackStateChanged.connect(self.update_play_icon)
        self.apply_styles()

        # Charger la configuration AKAI sauvegardee automatiquement
        self._load_akai_config_auto()

        # Plein ecran gere par maestro_new.py (apres splash)

        # Bloquer la mise en veille Windows
        self._prevent_sleep()

        # Suivi des modifications non sauvegardees (titre avec *)
        self._last_dirty_state = False
        self._dirty_timer = QTimer(self)
        self._dirty_timer.timeout.connect(self._update_dirty_title)
        self._dirty_timer.start(500)

        # Initialisation au demarrage
        QTimer.singleShot(100, self.activate_default_white_pads)
        QTimer.singleShot(200, self.turn_off_all_effects)
        QTimer.singleShot(300, self._init_default_fx_speed)
        QTimer.singleShot(1000, self.test_dmx_on_startup)
        QTimer.singleShot(1500, self._log_startup_status)

    def _prevent_sleep(self):
        """Empeche Windows de se mettre en veille tant que l'application tourne"""
        try:
            if _platform.system() == "Windows":
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ES_DISPLAY_REQUIRED = 0x00000002
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                )
                print("Anti-veille active")
        except Exception as e:
            print(f"Anti-veille: {e}")

    def _allow_sleep(self):
        """Restaure le comportement de veille normal"""
        try:
            if _platform.system() == "Windows":
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:
            pass

    def _update_dirty_title(self):
        """Met a jour le titre avec * si modifications non sauvegardees"""
        is_dirty = self.seq.is_dirty
        if is_dirty == self._last_dirty_state:
            return
        self._last_dirty_state = is_dirty

        if self.current_show_path:
            base = f"{APP_NAME} - {os.path.basename(self.current_show_path)}"
        else:
            base = APP_NAME

        if is_dirty:
            self.setWindowTitle(f"{base} *")
        else:
            self.setWindowTitle(base)

    def _create_window_icon(self):
        """Charge l'icone de la fenetre depuis mystrow.ico"""
        ico_path = resource_path("mystrow.ico")
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))

    # Mapping nom de groupe -> nom d'affichage dans la timeline
    GROUP_DISPLAY = {
        "face":    "A",
        "lat":     "B",
        "contre":  "C",
        "douche1": "D",
        "douche2": "E",
        "douche3": "F",
        "public":  "Public",
        "fumee":   "Fumee",
        "lyre":    "Lyres",
        "barre":   "Barres",
        "strobe":  "Strobos",
    }

    # Fixtures par defaut (nom, type, groupe interne)
    _DEFAULT_FIXTURES = [
        ("Face 1",   "PAR LED", "face"),
        ("Face 2",   "PAR LED", "face"),
        ("Face 3",   "PAR LED", "face"),
        ("Face 4",   "PAR LED", "face"),
        ("Douche 1", "PAR LED", "douche1"),
        ("Douche 2", "PAR LED", "douche2"),
        ("Douche 3", "PAR LED", "douche3"),
        ("Lat 1",    "PAR LED", "lat"),
        ("Lat 2",    "PAR LED", "lat"),
        ("Contre 1", "PAR LED", "contre"),
        ("Contre 2", "PAR LED", "contre"),
        ("Contre 3", "PAR LED", "contre"),
        ("Contre 4", "PAR LED", "contre"),
        ("Contre 5", "PAR LED", "contre"),
        ("Contre 6", "PAR LED", "contre"),
    ]

    # Canaux par type (pour adressage compact)
    _FIXTURE_CH = {
        "PAR LED": 5, "Moving Head": 8, "Barre LED": 5,
        "Stroboscope": 2, "Machine a fumee": 2,
    }

    def _load_default_fixtures(self):
        """Cree les fixtures par defaut avec adressage compact"""
        self.projectors = []
        addr = 1
        for name, ftype, group in self._DEFAULT_FIXTURES:
            p = Projector(group, name=name, fixture_type=ftype)
            p.start_address = addr
            addr += self._FIXTURE_CH.get(ftype, 5)
            self.projectors.append(p)

    def get_track_to_indices(self):
        """Retourne le mapping nom_affichage_groupe -> [indices projecteurs]"""
        mapping = {}
        for i, proj in enumerate(self.projectors):
            group_name = self.GROUP_DISPLAY.get(proj.group, proj.group.capitalize())
            mapping.setdefault(group_name, []).append(i)
        return mapping

    def _create_menu(self):
        """Cree la barre de menu"""
        bar = self.menuBar()

        file_menu = bar.addMenu(tr("menu_file"))
        new_action = file_menu.addAction(tr("menu_new_show"), self.new_show)
        new_action.setShortcut("Ctrl+N")
        file_menu.addSeparator()
        open_action = file_menu.addAction(tr("menu_open_show"), self.load_show)
        open_action.setShortcut("Ctrl+O")
        save_action = file_menu.addAction(tr("menu_save_show"), self.save_show)
        save_action.setShortcut("Ctrl+S")
        save_as_action = file_menu.addAction(tr("menu_save_as"), self.save_show_as)
        save_as_action.setShortcut("Ctrl+Shift+S")
        file_menu.addSeparator()
        self.recent_menu = file_menu.addMenu(tr("menu_recent"))
        self.update_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction(tr("menu_import_cfg"), self.import_akai_config)
        file_menu.addAction(tr("menu_export_cfg"), self.export_akai_config)
        file_menu.addSeparator()
        file_menu.addAction(tr("menu_load_mem_default"), self.load_default_presets)
        file_menu.addAction(tr("menu_load_fx_default"),  self.load_default_effects)
        file_menu.addAction(tr("menu_clear_all_mem"),    self.clear_all_memories)
        file_menu.addSeparator()
        file_menu.addAction(tr("menu_quit"), self.close)

        edit_menu = bar.addMenu(tr("menu_edit"))
        edit_menu.addAction(tr("menu_dmx_patch"), self.show_dmx_patch_config)
        edit_menu.addAction(tr("menu_dmx_tester"), self.open_dmx_tester)
        edit_menu.addSeparator()
        edit_menu.addAction(tr("menu_effect_editor"), self.open_effect_editor)
        edit_menu.addSeparator()
        edit_menu.addAction(tr("menu_ia_lumiere"), self.show_ia_lumiere_config)

        conn_menu = bar.addMenu(tr("menu_connection"))

        ctrl_menu = conn_menu.addMenu(tr("menu_control"))

        akai_menu = ctrl_menu.addMenu(tr("menu_akai_mini"))
        akai_menu.addAction("🔍  Diagnostic", self._open_akai_diagnostic)
        akai_menu.addAction("🔄  Reconnecter", self.test_akai_connection)
        akai_menu.addSeparator()
        akai_menu.addAction("⚙️  Paramètres", self._open_akai_layout_editor)

        ctrl_menu.addAction(tr("menu_streamdeck"), self._start_streamdeck_dialog)
        ctrl_menu.addAction(tr("menu_external_input"), self._start_tablet_server)

        conn_menu.addSeparator()

        self.node_menu = conn_menu.addMenu(tr("menu_dmx_output"))
        self.node_menu.addAction(tr("menu_config_output"), self.open_node_connection)
        self._refresh_dmx_menu_title()

        audio_menu = conn_menu.addMenu(tr("menu_audio_output"))
        audio_menu.addAction(tr("menu_test_sound"), self.play_test_sound)
        self.audio_output_menu = audio_menu.addMenu(tr("menu_audio_out_sub"))
        self.audio_output_menu.aboutToShow.connect(self._populate_audio_output_menu)

        video_menu = conn_menu.addMenu(tr("menu_video_output"))
        self.video_test_action = video_menu.addAction(tr("menu_test_logo"), self.show_test_logo)
        self.video_screen_menu = video_menu.addMenu(tr("menu_broadcast_on"))
        self.video_screen_menu.aboutToShow.connect(self._populate_screen_menu)
        self.video_target_screen = 1  # Ecran cible par defaut (second ecran)

        conn_menu.addSeparator()
        conn_menu.addAction("⌨️  Raccourci Clavier", self.show_shortcuts_dialog)

        about_menu = bar.addMenu(tr("menu_about"))
        about_menu.addAction(tr("menu_about_updates"), self.show_about)
        about_menu.addSeparator()
        about_menu.addAction(tr("menu_license"), self._open_activation_dialog)
        about_menu.addSeparator()
        about_menu.addAction(tr("menu_contact"), self._show_contact_dialog)
        about_menu.addAction(tr("menu_submit_idea"), self._show_idea_dialog)
        if get_language() == "fr":
            about_menu.addAction("📺 Tutoriels", self._show_tutorials_dialog)
        about_menu.addSeparator()
        social_menu = about_menu.addMenu("🌐  Suivez-nous sur les réseaux")
        social_menu.addAction("📸  Instagram", lambda: QDesktopServices.openUrl(QUrl("https://www.instagram.com/niko_mystrow_dmx/")))
        social_menu.addAction("▶️  TikTok",    lambda: QDesktopServices.openUrl(QUrl("https://www.tiktok.com/@niko_mystrow")))
        social_menu.addAction("▶️  YouTube",   lambda: QDesktopServices.openUrl(QUrl("https://www.youtube.com/@MyStrow-x7t")))
        about_menu.addSeparator()
        lang_menu = about_menu.addMenu(tr("menu_language"))
        act_fr = lang_menu.addAction(tr("menu_lang_fr"))
        act_en = lang_menu.addAction(tr("menu_lang_en"))
        act_fr.setCheckable(True)
        act_en.setCheckable(True)
        act_fr.setChecked(get_language() == "fr")
        act_en.setChecked(get_language() == "en")
        act_fr.triggered.connect(lambda: self._change_language("fr"))
        act_en.triggered.connect(lambda: self._change_language("en"))
        about_menu.addSeparator()
        about_menu.addAction(tr("menu_restart"), self.restart_application)

        # ── Corner widget : Master meter / CPU / Horloge ──────────────────────
        self._status_corner = _StatusCornerWidget()
        bar.setCornerWidget(self._status_corner, Qt.TopRightCorner)

        # ── Logo MYSTROW centré dans la menubar ───────────────────────────────
        self._menubar_logo = QLabel(
            '<span style="color:#ffffff; font-family:\'Bebas Neue\'; font-size:17px; letter-spacing:1px;">MY</span>'
            '<span style="color:#FFE000; font-family:\'Bebas Neue\'; font-size:17px; letter-spacing:1px;">STROW</span>',
            bar
        )
        self._menubar_logo.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._menubar_logo.adjustSize()
        self._menubar_logo.show()
        bar.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.menuBar() and event.type() == QEvent.Resize:
            lbl = getattr(self, '_menubar_logo', None)
            if lbl:
                lbl.adjustSize()
                x = (obj.width() - lbl.width()) // 2
                y = (obj.height() - lbl.height()) // 2
                lbl.move(x, y)
        return super().eventFilter(obj, event)

    def _create_video_frame(self):
        """Cree le frame video avec overlay image"""
        self.video_frame = QFrame()
        vv = QVBoxLayout(self.video_frame)
        vv.setContentsMargins(10, 10, 10, 10)

        # Bouton toggle sortie video
        title_layout = QHBoxLayout()
        title_layout.addStretch()

        self.video_output_btn = QPushButton("OFF")
        self.video_output_btn.setCheckable(True)
        self.video_output_btn.setFixedSize(44, 26)
        self.video_output_btn.setToolTip(tr("tooltip_video_output"))
        self.video_output_btn.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #cc3333; "
            "border-radius: 4px; font-size: 10px; font-weight: bold; } "
            "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #ff4444; } "
            "QPushButton:pressed { background: #333; }"
        )
        self.video_output_btn.clicked.connect(self.toggle_video_output)
        title_layout.addWidget(self.video_output_btn)

        vv.addLayout(title_layout)

        # Fenetre de sortie video (creee a la demande)
        self.video_output_window = None

        # QStackedWidget pour basculer entre video et image
        self.video_stack = QStackedWidget()
        self.video_stack.setStyleSheet("background: #000; border: 1px solid #2a2a2a; border-radius: 6px;")

        # Page 0 : QVideoWidget
        if QVideoWidget is not None:
            self.video_widget = QVideoWidget()
            self.video_widget.setStyleSheet("background: #000;")
            self.player.setVideoOutput(self.video_widget)
        else:
            self.video_widget = QWidget()
            self.video_widget.setStyleSheet("background: #000;")
        self.video_stack.addWidget(self.video_widget)

        # Page 1 : QLabel pour afficher les images
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background: #000;")
        self.video_stack.addWidget(self.image_label)

        self.video_stack.setCurrentIndex(0)
        vv.addWidget(self.video_stack)

    def _enforce_video_ratio(self):
        """Ajuste la hauteur video pour maintenir un ratio 16:9"""
        w = self.video_frame.width()
        if w > 0:
            target_h = int(w * 9 / 16) + 40  # +40 pour la barre titre
            sizes = self._right_splitter.sizes()
            if len(sizes) == 3:
                total = sum(sizes)
                sizes[2] = target_h
                sizes[0] = total - sizes[1] - sizes[2]
                if sizes[0] > 50:
                    self._right_splitter.setSizes(sizes)

    def show_image(self, path):
        """Affiche une image dans le preview integre"""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return

        target_size = self.video_stack.size()
        if target_size.width() > 0 and target_size.height() > 0:
            scaled = pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            scaled = pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self.image_label.setPixmap(scaled)
        self.video_stack.setCurrentIndex(1)

    def hide_image(self):
        """Revient a l'affichage video dans le preview integre"""
        self.video_stack.setCurrentIndex(0)

    def show_black_preview(self):
        """Affiche le noir dans le preview (masque la 1re frame d'un media precharge)"""
        self.image_label.clear()
        self.video_stack.setCurrentIndex(1)
        if self.video_output_window and self.video_output_window.isVisible():
            self.video_output_window.show_black()

    def toggle_video_output(self):
        """Active/desactive la sortie video externe"""
        _SS_ON  = ("QPushButton { background: #1e1e1e; color: #00cc66; border: 1px solid #00cc66; "
                   "border-radius: 4px; font-size: 10px; font-weight: bold; } "
                   "QPushButton:hover { background: #2a2a2a; color: #00ff88; border-color: #00ff88; } "
                   "QPushButton:pressed { background: #333; }")
        _SS_OFF = ("QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #cc3333; "
                   "border-radius: 4px; font-size: 10px; font-weight: bold; } "
                   "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #ff4444; } "
                   "QPushButton:pressed { background: #333; }")
        if self.video_output_btn.isChecked():
            # ON - creer/montrer la fenetre
            self.video_output_btn.setText("ON")
            self.video_output_btn.setStyleSheet(_SS_ON)
            self._log_message("Sortie vidéo activée", "success")
            if not self.video_output_window:
                self.video_output_window = VideoOutputWindow()
                # Appliquer watermark si licence non active
                self.video_output_window.set_watermark(self._license.watermark_required)

            # Placer sur l'ecran cible choisi
            screens = QApplication.screens()
            target = self.video_target_screen
            if target < len(screens):
                screen = screens[target]
                self.video_output_window.setGeometry(screen.geometry())
                self.video_output_window.showFullScreen()
            else:
                self.video_output_window.resize(960, 540)
                self.video_output_window.show()

            # Forwarder les frames video vers la fenetre externe via le sink
            sink = self.video_widget.videoSink() if QVideoWidget is not None else None
            if sink:
                sink.videoFrameChanged.connect(self._forward_video_frame)
            self._update_video_output_state()
        else:
            # OFF - cacher la fenetre
            self.video_output_btn.setText("OFF")
            self.video_output_btn.setStyleSheet(_SS_OFF)
            # Deconnecter le forward de frames
            sink = self.video_widget.videoSink() if QVideoWidget is not None else None
            if sink:
                try:
                    sink.videoFrameChanged.disconnect(self._forward_video_frame)
                except:
                    pass
            if self.video_output_window:
                self.video_output_window.hide()
            self._log_message("Sortie vidéo désactivée", "info")

    def _forward_video_frame(self, frame):
        """Forward une frame video vers la fenetre de sortie externe"""
        if self.video_output_window and self.video_output_window.isVisible():
            ext_sink = self.video_output_window.video_widget.videoSink()
            if ext_sink:
                ext_sink.setVideoFrame(frame)

    def _update_video_output_state(self):
        """Met a jour l'affichage de la fenetre video externe selon le media courant"""
        if not self.video_output_window or not self.video_output_window.isVisible():
            return

        # Determiner le type de media en cours
        row = self.seq.current_row
        if row < 0:
            self.video_output_window.show_black()
            return

        item = self.seq.table.item(row, 1)
        if not item:
            self.video_output_window.show_black()
            return

        path = item.data(Qt.UserRole)
        if not path:
            # C'est une PAUSE ou TEMPO
            self.video_output_window.show_black()
            return

        media_type = media_icon(path)
        if media_type == "video":
            self.video_output_window.show_video()
        elif media_type == "image":
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.video_output_window.show_image(pixmap)
            else:
                self.video_output_window.show_black()
        else:
            # Audio ou autre -> ecran noir
            self.video_output_window.show_black()

    def _create_main_layout(self):
        """Cree le layout principal"""
        # — Colonne centrale : séquenceur + transport
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        mv.addWidget(self.seq)
        mv.addWidget(self.transport)

        plan_scroll = QScrollArea()
        plan_scroll.setWidgetResizable(True)
        self.plan_de_feu = PlanDeFeu(self.projectors, self)
        if not self._license.dmx_allowed:
            self.plan_de_feu.set_dmx_blocked()
        plan_scroll.setWidget(self.plan_de_feu)
        self._plan3d = Plan3DWindow(self)
        plan_scroll.setStyleSheet("QScrollArea { border: none; }")


        self.color_picker_block = ColorPickerBlock(self.plan_de_feu)

        right = QSplitter(Qt.Vertical)
        right.setHandleWidth(2)
        right.setMinimumWidth(240)
        right.addWidget(plan_scroll)
        right.addWidget(self.color_picker_block)
        right.addWidget(self.video_frame)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 0)
        right.setStretchFactor(2, 3)
        right.setCollapsible(0, False)
        right.setCollapsible(1, False)
        right.setCollapsible(2, False)

        # Forcer ratio 16:9 sur la video
        self._right_splitter = right
        self._right_splitter_initialized = False
        right.splitterMoved.connect(self._enforce_video_ratio)

        self.akai.setMinimumWidth(320)

        main_split = QSplitter(Qt.Horizontal)
        main_split.setHandleWidth(2)
        main_split.addWidget(self.akai)
        main_split.addWidget(mid)
        main_split.addWidget(right)
        main_split.setStretchFactor(0, 0)  # AKAI = taille fixe
        main_split.setStretchFactor(1, 5)  # Sequenceur = priorite
        main_split.setStretchFactor(2, 2)
        main_split.setCollapsible(0, False)
        main_split.setCollapsible(1, False)
        main_split.setCollapsible(2, False)
        self._main_split = main_split

        # Barre de mise a jour — placee sous les cartoucheurs dans le panneau AKAI
        self.update_bar = UpdateBar()
        self.update_bar.hide()
        self.update_bar.later_clicked.connect(self._on_update_later)
        self.update_bar.update_clicked.connect(self._on_update_now)
        # Inserer avant le stretch (avant le dernier item du layout AKAI)
        stretch_idx = self._akai_layout.count() - 1
        self._akai_layout.insertWidget(stretch_idx, self.update_bar)

        self.setCentralWidget(main_split)

        # ── Autosave toutes les 5 minutes ────────────────────────────────────
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(5 * 60 * 1000)   # 5 min
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

        # Watermark sur le preview video integre
        self._setup_video_watermark()

        # Serveur HTTP pour le plugin StreamDeck (optionnel — ne bloque pas le démarrage)
        try:
            from streamdeck_api import StreamDeckAPIServer
            self._streamdeck_server = StreamDeckAPIServer(self)
            self._streamdeck_server.start()
        except Exception as _e:
            print(f"[StreamDeck API] Non disponible : {_e}")
            self._streamdeck_server = None

    def showEvent(self, event):
        """Au premier affichage, fixer les tailles du splitter droit (ratio 16:9 video)"""
        super().showEvent(event)
        if not self._right_splitter_initialized:
            self._right_splitter_initialized = True
            QTimer.singleShot(0, self._init_right_splitter_sizes)

    def _init_right_splitter_sizes(self):
        """Calcule et applique les tailles initiales des splitters"""
        # Splitter horizontal : AKAI (fixe 370) | Centre | Droite
        total_w = self._main_split.width()
        if total_w > 0:
            akai_w = 370
            right_w = max(260, int(total_w * 0.22))
            mid_w = total_w - akai_w - right_w
            if mid_w < 200:
                mid_w = 200
                right_w = total_w - akai_w - mid_w
            self._main_split.setSizes([akai_w, mid_w, right_w])

        # Splitter vertical droit : Plan de feu | Color Picker | Video 16:9
        total = self._right_splitter.height()
        if total <= 0:
            return
        video_w = self.video_frame.width()
        if video_w <= 0:
            video_w = 400
        video_h = int(video_w * 9 / 16) + 40  # +40 pour la barre titre
        picker_h = self.color_picker_block.sizeHint().height()
        plan_h = total - video_h - picker_h
        if plan_h < 100:
            plan_h = 100
            video_h = total - plan_h - picker_h
        self._right_splitter.setSizes([plan_h, picker_h, video_h])

    # ─────────────────────────────────────────────────────────────────────────
    # Bank preset helpers
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def _fader_map(self):
        """Returns the 8 slot descriptors for the current custom layout."""
        return self._custom_bank_slots

    def _mem_col_to_fader(self, mem_col):
        """Returns the first fader index that controls this memory column, or fallback."""
        for i, slot in enumerate(self._fader_map):
            if slot["type"] == "memory" and slot.get("mem_col") == mem_col:
                return i
        return 4 + min(mem_col, 3)  # fallback

    def _mem_col_to_faders(self, mem_col):
        """Returns ALL fader indices mapped to this memory column (plusieurs colonnes possibles)."""
        result = [i for i, slot in enumerate(self._fader_map)
                  if slot.get("type") == "memory" and slot.get("mem_col") == mem_col]
        return result if result else [4 + min(mem_col, 3)]

    def _fader_to_mem_col(self, fader_idx):
        """Retourne le mem_col contrôlé par ce fader, ou None."""
        slot = self._fader_map[fader_idx] if fader_idx < len(self._fader_map) else {}
        if slot.get("type") == "memory":
            return slot.get("mem_col")
        return None

    def _bank_memory_slots(self):
        """Returns list of (fader_idx, mem_col) for all memory slots in current bank."""
        return [(i, s["mem_col"]) for i, s in enumerate(self._fader_map) if s["type"] == "memory"]

    @staticmethod
    def _slot_groups(slot):
        """Retourne la liste des noms internes de groupes pour un slot de type 'group'.
        Gère les deux formats : nouveau {"group": "A"} et ancien {"groups": ["face"]}."""
        if slot.get("type") != "group":
            return []
        if "group" in slot:
            internal = AKAI_GROUP_MAP.get(slot["group"], slot["group"])
            return [internal]
        return slot.get("groups", [])

    def create_akai_panel(self):
        """Cree le panneau AKAI avec 8 colonnes + colonne effets"""
        frame = QFrame()
        frame.setMinimumWidth(320)
        layout = QVBoxLayout(frame)
        layout.setAlignment(Qt.AlignTop)
        layout.setContentsMargins(10, 10, 10, 10)

        _PARAM_BTN_SS = (
            "QPushButton { background: #1e1e1e; color: #aaa; border: 1px solid #3a3a3a; "
            "border-radius: 4px; font-size: 13px; } "
            "QPushButton:hover { background: #2a2a2a; color: #fff; border-color: #0077bb; }"
        )

        title_row = QHBoxLayout()

        # ⚙ Paramètres AKAI — à gauche
        edit_layout_btn = QPushButton("⚙")
        edit_layout_btn.setFixedSize(26, 26)
        edit_layout_btn.setToolTip(tr("tooltip_akai_layout"))
        edit_layout_btn.setStyleSheet(_PARAM_BTN_SS)
        edit_layout_btn.clicked.connect(self._open_akai_layout_editor)
        title_row.addWidget(edit_layout_btn)

        title_row.addStretch()

        rec_btn = QPushButton("🔴")
        rec_btn.setFixedSize(26, 26)
        rec_btn.setToolTip(tr("tooltip_rec_mem"))
        rec_btn.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #3a3a3a; "
            "border-radius: 4px; font-size: 13px; } "
            "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #cc3333; }"
        )
        rec_btn.clicked.connect(self._toggle_mem_rec_mode)
        self._rec_mem_btn = rec_btn
        title_row.addWidget(rec_btn)
        title_row.addSpacing(2)

        clr_btn = QPushButton("CLEAR")
        clr_btn.setFixedSize(46, 26)
        clr_btn.setToolTip(tr("tooltip_clear_akai"))
        clr_btn.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #888; border: 1px solid #3a3a3a; "
            "border-radius: 4px; font-size: 9px; font-weight: bold; } "
            "QPushButton:hover { background: #2a2a2a; color: #fff; border-color: #555; } "
            "QPushButton:pressed { background: #333; }"
        )
        clr_btn.clicked.connect(self._clear_akai_state)
        title_row.addWidget(clr_btn)

        # ── Zone unifiée pads + faders dans un widget de largeur fixe ──────────
        # PAD_W=28, PAD_GAP_H=7, PAD_GAP_V=4 → 8 colonnes = 8×28 + 7×7 = 273px
        # FX_GAP=6 → séparateur avant colonne effet
        _PAD_W = 28
        _PAD_GAP_H = 7   # espace horizontal entre colonnes
        _PAD_GAP_V = 4   # espace vertical entre rangées
        _PAD_GAP = _PAD_GAP_V  # compatibilité
        _FX_GAP = 6
        _PADS_W = 8 * _PAD_W + 7 * _PAD_GAP_H   # 273 px

        # Widget enveloppe qui force la même largeur pour les deux rangées
        akai_zone = QWidget()
        akai_zone.setContentsMargins(0, 0, 0, 0)
        akai_zone_layout = QVBoxLayout(akai_zone)
        akai_zone_layout.setContentsMargins(0, 0, 0, 0)
        akai_zone_layout.setSpacing(12)
        layout.addWidget(akai_zone, 0, Qt.AlignHCenter)

        # Titre centré dans la zone AKAI
        akai_zone_layout.addLayout(title_row)

        # ── Rangée 1 : pads 8×8 + boutons effet ─────────────────────────────
        pads_and_effects = QHBoxLayout()
        pads_and_effects.setSpacing(_FX_GAP)
        pads_and_effects.setContentsMargins(0, 0, 0, 0)

        self._pads_container = QWidget()
        self._pads_container.setFixedWidth(_PADS_W)   # empêche tout étirement
        self._pads_grid = QGridLayout(self._pads_container)
        self._pads_grid.setHorizontalSpacing(_PAD_GAP_H)
        self._pads_grid.setVerticalSpacing(_PAD_GAP_V)
        self._pads_grid.setContentsMargins(0, 0, 0, 0)
        pads_and_effects.addWidget(self._pads_container, 0, Qt.AlignLeft)

        effects_col = QVBoxLayout()
        effects_col.setSpacing(_PAD_GAP)
        effects_col.setContentsMargins(0, 0, 0, 0)
        for r in range(8):
            effect_btn = EffectButton(r)
            effect_btn.clicked.connect(lambda _, idx=r: self.toggle_effect(idx))
            effect_btn.effect_config_selected.connect(self._on_effect_assigned)
            effect_btn.open_editor_requested.connect(lambda idx: self._open_effect_editor_for_btn(idx))
            self.effect_buttons.append(effect_btn)
            effects_col.addWidget(effect_btn)
        pads_and_effects.addLayout(effects_col)
        pads_and_effects.addStretch()

        akai_zone_layout.addLayout(pads_and_effects)

        # Build initial pads
        self._rebuild_akai_pads()

        # ── Rangée 2 : faders alignés colonne par colonne ────────────────────
        fader_container = QHBoxLayout()
        fader_container.setSpacing(0)
        fader_container.setContentsMargins(0, 0, 0, 0)

        self._fader_label_widgets = []
        for i in range(8):
            col_widget = QWidget()
            col_widget.setFixedWidth(_PAD_W)
            col_layout = QVBoxLayout(col_widget)
            col_layout.setSpacing(2)
            col_layout.setContentsMargins(0, 0, 0, 0)

            btn = FaderButton(i, self.toggle_mute)
            self.fader_buttons.append(btn)
            col_layout.addWidget(btn, alignment=Qt.AlignCenter)

            fader = ApcFader(i, self.set_proj_level, vertical=False)
            self.faders[i] = fader
            col_layout.addWidget(fader, alignment=Qt.AlignHCenter)

            lbl_letter = QPushButton(self._fader_map[i]["label"])
            lbl_letter.setFixedHeight(14)
            lbl_letter.setStyleSheet(
                "QPushButton { color:#666; font-size:9px; background:transparent; border:none; padding:0; }"
                "QPushButton:hover { color:#aaa; text-decoration:underline; }"
            )
            lbl_letter.setCursor(Qt.PointingHandCursor)
            lbl_letter.clicked.connect(lambda _, idx=i: self._open_fader_slot_picker(idx))
            col_layout.addWidget(lbl_letter)
            self._fader_label_widgets.append(lbl_letter)

            fader_container.addWidget(col_widget)
            if i < 7:
                fader_container.addSpacing(_PAD_GAP_H)

        # Colonne effet (alignée avec effects_col ci-dessus)
        fader_container.addSpacing(_FX_GAP)
        effect_col = QVBoxLayout()
        effect_col.setSpacing(2)
        effect_col.setContentsMargins(0, 0, 0, 0)

        tap_btn = QToolButton()
        tap_btn.setFixedSize(16, 16)
        tap_btn.setToolTip(tr("tooltip_tap_tempo"))
        tap_btn.setStyleSheet("""
            QToolButton {
                background: #4a4a4a;
                border: 2px solid #6a6a6a;
                border-radius: 8px;
            }
            QToolButton:hover {
                background: #5a5a5a;
                border: 2px solid #aaa;
            }
            QToolButton:pressed {
                background: #333;
                border: 2px solid #fff;
            }
        """)
        tap_btn.clicked.connect(self._tap_tempo)
        self._tap_btn = tap_btn
        effect_col.addWidget(tap_btn, alignment=Qt.AlignCenter)

        # Restaurer les noms d'effets assignés depuis le fichier sauvegardé
        for _i, _btn in enumerate(self.effect_buttons):
            _cfg = self._button_effect_configs.get(_i, {})
            if _cfg.get("name"):
                _btn.current_effect = _cfg["name"]
                _btn.setToolTip(_cfg["name"])

        effect_fader = ApcFader(8, self._fader8_dispatch, vertical=False)
        effect_fader.set_value(100)
        self.faders[8] = effect_fader
        effect_col.addWidget(effect_fader)

        self._lbl_fader8 = QLabel(tr("akai_amp_fx_label"))
        self._lbl_fader8.setFixedHeight(12)
        self._lbl_fader8.setAlignment(Qt.AlignCenter)
        self._lbl_fader8.setStyleSheet("color:#666;font-size:9px;")
        effect_col.addWidget(self._lbl_fader8)

        fader_container.addLayout(effect_col)
        fader_container.addStretch()

        akai_zone_layout.addLayout(fader_container)

        # ── Séparateur ────────────────────────────────────────────────────────
        sep_cart = QFrame()
        sep_cart.setFrameShape(QFrame.HLine)
        sep_cart.setFixedHeight(1)
        sep_cart.setStyleSheet("background:#222; border:none;")
        akai_zone_layout.addSpacing(6)
        akai_zone_layout.addWidget(sep_cart)
        akai_zone_layout.addSpacing(6)

        # ── Banniere de licence ───────────────────────────────────────────────
        self._license_banner = LicenseBanner()
        self._license_banner.dismissed.connect(self._on_license_banner_dismissed)
        self._license_banner.activate_clicked.connect(self._on_banner_clicked)
        self._apply_license_banner()
        akai_zone_layout.addWidget(self._license_banner)

        # ── Cue panel standalone (popup flottant) ────────────────────────────
        from cue_list import CueListPanel
        self._cue_panel = CueListPanel()
        self._cue_panel.cues_changed.connect(self._on_cue_panel_changed)
        self._cue_panel.cue_activated.connect(self._on_cue_activated)
        self._cue_panel.effect_pick_requested.connect(self._on_cue_effect_pick)
        self._cue_float = None

        # ── Cartoucheurs 2×2 ─────────────────────────────────────────────────
        self.cartouches = []
        cart_grid = QGridLayout()
        cart_grid.setSpacing(6)
        cart_grid.setContentsMargins(0, 0, 0, 0)
        cart_grid.setColumnStretch(0, 1)
        cart_grid.setColumnStretch(1, 1)
        for i in range(4):
            cart = CartoucheButton(i, self.on_cartouche_clicked)
            cart.customContextMenuRequested.connect(
                lambda pos, idx=i: self.load_cartouche_media(idx)
            )
            cart_grid.addWidget(cart, i // 2, i % 2)
            self.cartouches.append(cart)
        akai_zone_layout.addLayout(cart_grid)

        # ── Journal des actions ───────────────────────────────────────────────
        self._msg_log = MessageLogWidget()
        self._msg_log.setStyleSheet("""
            MessageLogWidget {
                background: #0d0d0d;
                border: 1px solid #1e1e1e;
                border-radius: 6px;
            }
        """)
        akai_zone_layout.addSpacing(4)
        akai_zone_layout.addWidget(self._msg_log, 1)

        # Emplacement reserve pour la barre de mise a jour (ajoutee apres init)
        self._akai_layout = layout

        layout.addStretch()

        return frame

    def _rebuild_akai_pads(self):
        """Rebuilds the 8x8 pad grid based on current bank preset."""
        base_colors = [
            QColor("white"), QColor("#ff0000"), QColor("#ff8800"), QColor("#ffdd00"),
            QColor("#00ff00"), QColor("#00dddd"), QColor("#0000ff"), QColor("#ff00ff")
        ]

        # Clear existing pads
        self.pads.clear()
        while self._pads_grid.count():
            item = self._pads_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for r in range(8):
            for c in range(8):
                slot = self._fader_map[c]
                if slot["type"] == "group":
                    col = base_colors[r]
                    b = QPushButton()
                    b.setFixedSize(28, 28)
                    dim_color = QColor(int(col.red() * 0.5), int(col.green() * 0.5), int(col.blue() * 0.5))
                    b.setStyleSheet(f"QPushButton {{ background: {dim_color.name()}; border: 1px solid #2a2a2a; border-radius: 4px; }}")
                    b.setProperty("base_color", col)
                    b.setProperty("color2", None)
                    b.setProperty("dim_color", dim_color)
                    b.clicked.connect(lambda _, btn=b, fc=c: self.activate_pad(btn, fc))
                elif slot["type"] == "fx":
                    fx_col = slot.get("fx_col", 0)
                    b = QPushButton()
                    b.setFixedSize(28, 28)
                    cfg = self.fx_pads[fx_col][r] if fx_col < _FX_COL_MAX else None
                    active = self.active_fx_pads.get((fx_col, r))
                    if active and cfg:
                        b.setStyleSheet("QPushButton { background: #33ff33; border: 2px solid #ffffff; border-radius: 4px; }")
                    elif cfg:
                        b.setStyleSheet("QPushButton { background: #116611; border: 1px solid #114411; border-radius: 4px; }")
                        b.setToolTip(cfg.get("name", ""))
                    else:
                        b.setStyleSheet("QPushButton { background: #0a1a0a; border: 1px solid #1a2a1a; border-radius: 4px; }")
                    b.setProperty("base_color", QColor("#33ff33"))
                    b.setProperty("color2", None)
                    b.setProperty("fx_col", fx_col)
                    b.setProperty("fx_row", r)
                    b.clicked.connect(lambda _, fc=fx_col, fr=r: self._toggle_fx_pad(fc, fr))
                    b.setContextMenuPolicy(Qt.CustomContextMenu)
                    b.customContextMenuRequested.connect(
                        lambda pos, fc=fx_col, fr=r, btn=b: self._show_fx_context_menu(pos, fc, fr, btn)
                    )
                else:  # memory
                    mem_col = slot["mem_col"]
                    b = QPushButton()
                    b.setFixedSize(28, 28)
                    b.setStyleSheet("QPushButton { background: #1a1a1a; border: 1px solid #1a1a1a; border-radius: 4px; }")
                    b.setProperty("base_color", QColor("black"))
                    b.setProperty("color2", None)
                    b.setProperty("memory_col", mem_col)
                    b.setProperty("memory_row", r)
                    b.clicked.connect(lambda _, btn=b, mc=mem_col, mr=r, ca=c: self._activate_memory_pad(btn, mc, mr, col_akai=ca))
                    b.setContextMenuPolicy(Qt.CustomContextMenu)
                    b.customContextMenuRequested.connect(
                        lambda pos, mc=mem_col, mr=r, btn=b: self._show_memory_context_menu(pos, mc, mr, btn)
                    )

                self._pads_grid.addWidget(b, r, c)
                self.pads[(r, c)] = b

        # Refresh memory pad styles
        for fi, mc in self._bank_memory_slots():
            for mr in range(8):
                self._style_memory_pad(mc, mr, active=self.active_memory_pads.get(fi) == mr)

        # Refresh active color pads
        for col_idx, btn in list(self.active_pads.items()):
            slot = self._fader_map[col_idx] if col_idx < len(self._fader_map) else None
            if slot and slot["type"] == "group":
                new_btn = self.pads.get((
                    next((r for r in range(8) if self.pads.get((r, col_idx)) and
                          self.pads.get((r, col_idx)).property("base_color") == btn.property("base_color")), 0),
                    col_idx
                ))
                if new_btn:
                    color = new_btn.property("base_color")
                    new_btn.setStyleSheet(f"QPushButton {{ background: {color.name()}; border: 2px solid {color.lighter(130).name()}; border-radius: 4px; }}")
                    self.active_pads[col_idx] = new_btn

    def _open_fader_slot_picker(self, fader_idx):
        """Ouvre le picker d'assignation directement depuis l'étiquette du fader."""
        current = self._custom_bank_slots[fader_idx]["label"]
        picker = _SlotPickerPopup(_AKAI_SLOT_OPTIONS, current, self)

        def _on_selected(value):
            # Reconstruire le slot
            if value.startswith("MEM "):
                mem_col = int(value.split()[1]) - 1
                self._custom_bank_slots[fader_idx] = {"type": "memory", "mem_col": mem_col, "label": value}
            elif value.startswith("FX "):
                fx_col = int(value.split()[1]) - 1
                self._custom_bank_slots[fader_idx] = {"type": "fx", "fx_col": fx_col, "label": value}
            else:
                self._custom_bank_slots[fader_idx] = {"type": "group", "group": value, "label": value}
            # Mettre à jour l'étiquette
            if fader_idx < len(self._fader_label_widgets):
                self._fader_label_widgets[fader_idx].setText(value)
            # Reconstruire les pads et syncer
            self.active_pads.clear()
            self.active_memory_pads.clear()
            self._rebuild_akai_pads()
            self.activate_default_white_pads()
            self._save_akai_config_auto()

        picker.selected.connect(_on_selected)
        btn = self._fader_label_widgets[fader_idx]
        pos = btn.mapToGlobal(btn.rect().topLeft())
        picker.move(pos.x(), pos.y() - 360)
        picker.show()
        picker.adjustSize()

    def _open_akai_diagnostic(self):
        """Ouvre la fenêtre de diagnostic AKAI."""
        dlg = AkaiDiagnosticDialog(self.midi_handler, self)
        dlg.exec()

    def _open_akai_layout_editor(self):
        """Ouvre l'éditeur de layout AKAI APC mini."""
        dlg = AkaiLayoutEditorDialog(
            self._custom_bank_slots,
            last_fader_mode=getattr(self, '_last_fader_mode', 'FX'),
            superposition=self.effect_superposition,
            go_mode=self.go_mode,
            parent=self
        )
        if dlg.exec() != QDialog.Accepted:
            return
        self._custom_bank_slots = dlg.get_slots()
        self.effect_superposition = dlg.get_superposition()
        self.go_mode = dlg.get_go_mode()
        self._update_tap_go_btn_style()
        self.active_pads.clear()
        self.active_memory_pads.clear()
        self._rebuild_akai_pads()
        try:
            import tablet_server as _ts
            if _ts.is_running():
                _ts.push_layout(self._custom_bank_slots)
        except Exception:
            pass
        if hasattr(self, '_fader_label_widgets'):
            for i, lbl in enumerate(self._fader_label_widgets):
                if i < len(self._fader_map):
                    lbl.setText(self._fader_map[i]["label"])
        self.activate_default_white_pads()
        self._save_akai_config_auto()

    def create_transport_panel(self):
        """Cree le panneau transport avec timeline"""
        frame = QFrame()
        frame.setFixedHeight(150)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)

        # Timeline
        timeline_container = QHBoxLayout()

        self.time_label = QLabel("00:00")
        self.time_label.setStyleSheet("color: #00d4ff; font-weight: bold; font-size: 12px;")
        self.time_label.setFixedWidth(50)
        timeline_container.addWidget(self.time_label)

        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.setFixedHeight(30)
        self.timeline.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #ffffff;
                height: 12px;
                border-radius: 6px;
                border: 1px solid #00d4ff;
            }
            QSlider::handle:horizontal {
                background: #00d4ff;
                width: 24px;
                height: 24px;
                margin: -6px 0;
                border-radius: 12px;
                border: 3px solid #ffffff;
            }
        """)
        self.player.durationChanged.connect(self.timeline.setMaximum)
        self.player.positionChanged.connect(self.on_timeline_update)
        self.timeline.sliderMoved.connect(self.player.setPosition)
        timeline_container.addWidget(self.timeline)

        self.remaining_label = QLabel("-00:00")
        self.remaining_label.setStyleSheet("color: #ff8800; font-weight: bold; font-size: 12px;")
        self.remaining_label.setFixedWidth(60)
        self.remaining_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        timeline_container.addWidget(self.remaining_label)

        layout.addLayout(timeline_container)

        # Waveform
        self.recording_waveform = RecordingWaveform()
        self.recording_waveform.setFixedHeight(30)
        self.recording_waveform.hide()
        layout.addWidget(self.recording_waveform)

        layout.addSpacing(8)

        # Boutons transport
        btns = QHBoxLayout()
        btns.setSpacing(10)

        side_style = """
            QToolButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3a3a3a, stop:1 #222222);
                border: 1px solid #555555;
                border-radius: 22px;
                padding: 10px;
            }
            QToolButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #444444, stop:1 #2a2a2a);
                border: 1px solid #00d4ff;
            }
            QToolButton:pressed {
                background: #1a1a1a;
                border: 1px solid #00aacc;
            }
        """

        play_style = """
            QToolButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #006680, stop:1 #003344);
                border: 2px solid #00d4ff;
                border-radius: 32px;
                padding: 14px;
            }
            QToolButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #008aaa, stop:1 #004455);
                border: 2px solid #33eeff;
            }
            QToolButton:pressed {
                background: #002233;
                border: 2px solid #0099bb;
            }
        """

        prev = QToolButton()
        prev.setIcon(create_icon("prev", "#cccccc"))
        prev.setIconSize(QSize(28, 28))
        prev.setFixedSize(52, 52)
        prev.setStyleSheet(side_style)
        prev.setToolTip("Média précédent")
        prev.clicked.connect(lambda: self.seq.play_row(self.seq.current_row - 1))

        self.play_btn = QToolButton()
        self.play_btn.setIcon(create_icon("play", "#ffffff"))
        self.play_btn.setIconSize(QSize(36, 36))
        self.play_btn.setFixedSize(72, 72)
        self.play_btn.setStyleSheet(play_style)
        self.play_btn.setToolTip("Play / Pause")
        self.play_btn.clicked.connect(self.toggle_play)

        nxt = QToolButton()
        nxt.setIcon(create_icon("next", "#cccccc"))
        nxt.setIconSize(QSize(28, 28))
        nxt.setFixedSize(52, 52)
        nxt.setStyleSheet(side_style)
        nxt.setToolTip("Média suivant")
        nxt.clicked.connect(lambda: self.seq.play_row(self.seq.current_row + 1))

        btns.addStretch()
        btns.addWidget(prev)
        btns.addSpacing(4)
        btns.addWidget(self.play_btn)
        btns.addSpacing(4)
        btns.addWidget(nxt)
        btns.addStretch()
        layout.addLayout(btns)

        return frame

    def trigger_pause_mode(self):
        """Active le mode pause sans clignotement"""
        self.pause_mode = True
        self.player.pause()
        if self.blink_timer:
            self.blink_timer.stop()
            self.blink_timer = None

    def toggle_play(self):
        """Toggle play/pause - gere aussi les TEMPO"""
        # Pause d'un TEMPO en cours
        if self.seq.tempo_running:
            self.seq.tempo_running = False
            self.seq.tempo_paused = True
            self.seq.tempo_timer.stop()
            if self.seq.timeline_playback_timer and self.seq.timeline_playback_timer.isActive():
                self.seq.timeline_playback_timer.stop()
            self.play_btn.setIcon(create_icon("play", "#ffffff"))
            return

        # Reprise d'un TEMPO en pause
        if self.seq.tempo_paused:
            self.seq.tempo_running = True
            self.seq.tempo_paused = False
            self.seq.tempo_timer.start(100)
            if hasattr(self.seq, 'timeline_playback_row') and self.seq.timeline_playback_timer:
                self.seq.timeline_playback_timer.start(50)
            self.play_btn.setIcon(create_icon("pause", "#ffffff"))
            return

        # Lecture normale
        if self.pause_mode:
            if self.blink_timer:
                self.blink_timer.stop()
            self.pause_mode = False
            # Arrêt défensif du timeline si le media courant est en mode Manuel
            current_mode = self.seq.get_dmx_mode(self.seq.current_row)
            if current_mode == "Manuel":
                self.seq.stop_sequence_playback()
            # Repasser sur le widget video (peut être masqué si pause après PAUSE + precharge)
            self.hide_image()
            self.player.play()
            self._update_video_output_state()
        elif self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_play_icon(self, s):
        """Met a jour l'icone play/pause"""
        if s == QMediaPlayer.PlayingState:
            self.play_btn.setIcon(create_icon("pause", "#ffffff"))
        else:
            self.play_btn.setIcon(create_icon("play", "#ffffff"))

    def on_timeline_update(self, position):
        """Met a jour la timeline"""
        try:
            duration = self.player.duration()
            if duration > 0 and self.timeline.maximum() != duration:
                self.timeline.setMaximum(duration)
            if duration > 0:
                position = min(position, duration)
            self.timeline.setValue(position)
            self.time_label.setText(fmt_time(position))
            if duration > 0:
                remaining = duration - position
                self.remaining_label.setText(f"-{fmt_time(remaining)}")
            if self.seq.recording and self.recording_waveform.isVisible():
                self.recording_waveform.set_position(position, duration)
        except:
            pass

    def on_media_status_changed(self, status):
        """Passe automatiquement au suivant ou gere les pauses"""
        if status == QMediaPlayer.EndOfMedia:
            # Verifier que c'est bien le media courant qui est termine
            # (evite qu'un EndOfMedia retarde d'un ancien media avance au mauvais rang)
            source_row = getattr(self, '_media_source_row', self.seq.current_row)
            if source_row != self.seq.current_row:
                # EndOfMedia d'un ancien media: ignorer
                return

            if hasattr(self.seq, 'timeline_playback_timer') and self.seq.timeline_playback_timer and self.seq.timeline_playback_timer.isActive():
                self.seq.timeline_playback_timer.stop()
            if hasattr(self.seq, 'timeline_playback_row'):
                del self.seq.timeline_playback_row
            self.seq.timeline_tracks_data = {}

            if self.seq.recording:
                self.stop_recording()
                return

            current_mode = self.seq.get_dmx_mode(self.seq.current_row)
            next_row = self.seq.current_row + 1

            # IA Lumière : fade-out puis transition
            if current_mode == "IA Lumiere":
                self.audio_ai.reset()
                # Réinitialiser l'état interne des lyres + sections + effets aléatoires
                for attr in ('_ia_lyre_e', '_ia_lyre_phase', '_ia_lyre_last_pos',
                             '_ia_sec', '_ia_rnd_fx'):
                    self.__dict__.pop(attr, None)

                def _after_ia_fade():
                    if next_row < self.seq.table.rowCount():
                        self.seq.play_row(next_row)
                    else:
                        print("Fin de la sequence")
                        self.update_play_icon(QMediaPlayer.StoppedState)
                        self._update_video_output_state()

                self._ia_start_fadeout(_after_ia_fade)
                return

            if next_row < self.seq.table.rowCount():
                next_mode = self.seq.get_dmx_mode(next_row)
                if current_mode == "Play Lumiere":
                    self.full_blackout()
                elif current_mode == "Programme" and next_mode == "Manuel":
                    self.full_blackout()

                self.seq.play_row(next_row)
            else:
                if current_mode == "Play Lumiere":
                    self.full_blackout()
                print("Fin de la sequence")
                self.update_play_icon(QMediaPlayer.StoppedState)
                self._update_video_output_state()

    def dmx_blackout(self):
        """Blackout DMX uniquement (projecteurs) - conserve l'eclairage AKAI"""
        for idx in range(9):
            if idx in self.faders:
                self.faders[idx].value = 0
                self.faders[idx].update()

        for p in self.projectors:
            p.level = 0
            p.color = QColor("black")
            p.base_color = QColor("black")

    def full_blackout(self):
        """Blackout complet"""
        # Vider les overrides HTP
        if hasattr(self, 'plan_de_feu'):
            self.plan_de_feu.set_htp_overrides(None)

        for idx in range(9):
            if idx in self.faders:
                self.faders[idx].value = 0
                self.faders[idx].update()

        for p in self.projectors:
            p.level = 0
            p.color = QColor("black")
            p.base_color = QColor("black")

        for col, pad in self.active_pads.items():
            if pad:
                old_color = pad.property("base_color")
                dim_color = QColor(int(old_color.red() * 0.5), int(old_color.green() * 0.5), int(old_color.blue() * 0.5))
                pad.setStyleSheet(f"QPushButton {{ background: {dim_color.name()}; border: 1px solid #2a2a2a; border-radius: 4px; }}")
        self.active_pads = {}

        for btn in self.effect_buttons:
            if btn.active:
                btn.active = False
                btn.update_style()

        if self.active_effect is not None:
            self.stop_effect()
            self.active_effect = None

        if MIDI_AVAILABLE and self.midi_handler.midi_out:
            for row in range(8):
                for col in range(8):
                    self.midi_handler.set_pad_led(row, col, 0, 0)

    def activate_pad(self, btn, col_idx):
        """Active un pad dans sa colonne (independant par colonne)"""
        color = btn.property("base_color")
        if col_idx >= len(self._fader_map):
            return
        slot = self._fader_map[col_idx]
        if slot["type"] != "group":
            return

        # Mode REC actif : impossible d'enregistrer sur un pad groupe (A/B/C/D/E/F)
        if self._mem_rec_mode:
            self._mem_rec_mode = False
            if self._rec_mem_btn:
                self._rec_mem_btn.setStyleSheet(
                    "QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #3a3a3a; "
                    "border-radius: 4px; font-size: 13px; } "
                    "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #cc3333; }"
                )
                self._rec_mem_btn.setToolTip("REC Mémoire — cliquez pour activer, puis cliquez sur un pad")
            self._show_error_toast("✖ Impossible d'enregistrer sur un Groupe — Sélectionnez une mémoire")
            return
        target_groups = self._slot_groups(slot)

        # Desactiver l'ancien pad de CETTE colonne uniquement
        prev = self.active_pads.get(col_idx)
        if prev and prev != btn:
            old_color = prev.property("base_color")
            dim_color = QColor(int(old_color.red() * 0.5), int(old_color.green() * 0.5), int(old_color.blue() * 0.5))
            prev.setStyleSheet(f"QPushButton {{ background: {dim_color.name()}; border: 1px solid #2a2a2a; border-radius: 4px; }}")

        btn.setStyleSheet(f"QPushButton {{ background: {color.name()}; border: 2px solid {color.lighter(130).name()}; border-radius: 4px; }}")
        self.active_pads[col_idx] = btn

        # Appliquer la couleur seulement si le fader de cette colonne est leve
        fader_value = self.faders[col_idx].value if col_idx in self.faders else 0
        for p in self.projectors:
            if p.group in target_groups:
                p.base_color = color
                if fader_value > 0:
                    brightness = fader_value / 100.0
                    p.color = QColor(
                        int(color.red() * brightness),
                        int(color.green() * brightness),
                        int(color.blue() * brightness)
                    )

        # Envoi DMX immediat sans attendre le prochain tick
        self.send_dmx_update()

    def activate_pad_dual(self, btn, col_idx):
        """Active un pad bicolore"""
        color1 = btn.property("base_color")
        color2 = btn.property("color2")

        if self.active_dual_pad and self.active_dual_pad != btn:
            self.active_dual_pad.active = False
            self.active_dual_pad.brightness = 0.3
            self.active_dual_pad.update()

        btn.active = not btn.active
        if btn.active:
            btn.brightness = 1.0
            self.active_dual_pad = btn
        else:
            btn.brightness = 0.3
            self.active_dual_pad = None
        btn.update()

        if btn.active:
            patterns = {
                "lat": [color1, color1],
                "contre": [color2, color1, color2, color2, color1, color2]
            }

            for group, pattern in patterns.items():
                projs = [p for p in self.projectors if p.group == group]
                for i, p in enumerate(projs):
                    if i < len(pattern):
                        p.base_color = pattern[i]
                        if p.level > 0:
                            brightness = p.level / 100.0
                            p.color = QColor(
                                int(pattern[i].red() * brightness),
                                int(pattern[i].green() * brightness),
                                int(pattern[i].blue() * brightness)
                            )

    def _toggle_mem_rec_mode(self):
        """Active/desactive le mode REC memoire."""
        self._mem_rec_mode = not self._mem_rec_mode
        if self._rec_mem_btn is None:
            return
        if self._mem_rec_mode:
            self._rec_mem_btn.setStyleSheet(
                "QPushButton { background: #cc3333; color: white; border: 2px solid #ff6666; "
                "border-radius: 4px; font-size: 13px; }"
            )
            self._rec_mem_btn.setToolTip("REC actif — cliquez sur un pad mémoire pour enregistrer")
        else:
            self._rec_mem_btn.setStyleSheet(
                "QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #3a3a3a; "
                "border-radius: 4px; font-size: 13px; } "
                "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #cc3333; }"
            )
            self._rec_mem_btn.setToolTip("REC Mémoire — cliquez pour activer, puis cliquez sur un pad")
        # Mettre à jour les tooltips des pads non-mémoire
        self._update_non_mem_pad_tooltips()
        try:
            import tablet_server as _ts
            if _ts.is_running():
                _ts.push_rec_state(self._mem_rec_mode)
        except Exception:
            pass

    def _update_non_mem_pad_tooltips(self):
        """En mode REC, affiche 🚫 sur les pads groupe et FX (non enregistrables)."""
        tip = "🚫" if self._mem_rec_mode else ""
        for (row, col), pad in self.pads.items():
            if col >= len(self._fader_map):
                continue
            slot = self._fader_map[col]
            if slot["type"] in ("group", "fx"):
                pad.setToolTip(tip)
                pad.setToolTipDuration(800 if self._mem_rec_mode else -1)

    def _log_message(self, text: str, level: str = "info"):
        """Envoie un message dans le journal AKAI."""
        log = getattr(self, '_msg_log', None)
        if log is not None:
            log.append_message(text, level)

    def _show_mem_toast(self, text):
        """Log un message de succès dans le journal."""
        self._log_message(text, "success")

    def _show_error_toast(self, text):
        """Log un message d'erreur dans le journal."""
        self._log_message(text, "error")

    def _show_bpm_toast(self, bpm: int):
        """Log le BPM détecté dans le journal."""
        self._log_message(f"TAP tempo : {bpm} BPM", "bpm")

    def _activate_memory_pad(self, btn, mem_col, row, col_akai=None):
        """Active un pad memoire - independant par colonne.
        Chaque colonne memoire est independante : activer un pad dans la colonne 2
        ne desactive pas le pad actif dans la colonne 1.
        Cliquer sur le pad deja actif ne fait rien."""

        # Mode REC : enregistrer l'etat courant sur ce pad
        if self._mem_rec_mode:
            self._record_memory(mem_col, row)
            self._mem_rec_mode = False
            if self._rec_mem_btn:
                self._rec_mem_btn.setStyleSheet(
                    "QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #3a3a3a; "
                    "border-radius: 4px; font-size: 13px; } "
                    "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #cc3333; }"
                )
                self._rec_mem_btn.setToolTip("REC Mémoire — cliquez pour activer, puis cliquez sur un pad")
            self._log_message(f"Rec MEM {mem_col + 1}.{row + 1} OK", "rec")
            self._blink_memory_pad(mem_col, row)
            return

        if col_akai is None:
            col_akai = self._mem_col_to_fader(mem_col)

        # Clic sur le pad déjà actif → avancer au cue suivant si multi-cue
        if self.active_memory_pads.get(col_akai) == row:
            mem = self.memories[mem_col][row]
            if mem:
                self._mem_ensure_cues(mem)
                if len(mem.get("cues", [])) > 1:
                    self._mem_advance_cue(mem_col, row)
                    fader_val = self.faders[col_akai].value if col_akai in self.faders else 0
                    self._apply_memory_to_projectors(mem_col, row, fader_value=fader_val)
                    cue_idx = self._mem_cue_idx.get((mem_col, row), 0)
                    n_cues = len(mem["cues"])
                    cue_lbl = mem["cues"][cue_idx].get("label", f"Cue {cue_idx + 1}")
                    self._log_message(f"MEM {mem_col+1}.{row+1} → {cue_lbl} ({cue_idx+1}/{n_cues})", "mem")
                    self._style_memory_pad(mem_col, row, active=True)
                    # Rafraîchir le panel Cues si ouvert sur ce pad
                    if hasattr(self, '_cue_panel') and self._cue_panel.mem_col == mem_col and self._cue_panel.row == row:
                        self._cue_panel.highlight_cue(cue_idx)
            return

        # Activation impossible si aucune memoire stockee
        if self.memories[mem_col][row] is None:
            return

        # Desactiver le pad precedent DANS CETTE COLONNE SEULEMENT
        prev_row = self.active_memory_pads.pop(col_akai, None)
        if prev_row is not None:
            self._clear_memory_from_projectors(mem_col, prev_row)
            self._style_memory_pad(mem_col, prev_row, active=False)
            self._update_memory_pad_led(mem_col, prev_row, active=False)
            self._mem_cue_idx.pop((mem_col, prev_row), None)  # reset cue index
            prev_mem = self.memories[mem_col][prev_row]
            if prev_mem:
                self._mem_ensure_cues(prev_mem)
                prev_eff_name = (prev_mem["cues"][0].get("effect") or {}).get("name") if prev_mem.get("cues") else None
            else:
                prev_eff_name = None
            if prev_eff_name:
                if hasattr(self, 'effect_timer'):
                    self.effect_timer.stop()
                self.active_effect = None
                self.active_effect_config = {}
                self.effect_saved_colors = {}

        # Activer le nouveau pad (cue 0 par défaut)
        self._mem_cue_idx[(mem_col, row)] = 0
        self.active_memory_pads[col_akai] = row
        self._style_memory_pad(mem_col, row, active=True)
        self._update_memory_pad_led(mem_col, row, active=True)
        fader_val = self.faders[col_akai].value if col_akai in self.faders else 0
        self._apply_memory_to_projectors(mem_col, row, fader_value=fader_val)

        mem = self.memories[mem_col][row]
        self._mem_ensure_cues(mem)
        n_cues = len(mem.get("cues", []))
        if n_cues > 1:
            self._log_message(f"MEM {mem_col+1}.{row+1}  [1/{n_cues}]", "mem")
        else:
            self._log_message(f"MEM {mem_col + 1}.{row + 1}", "mem")
        if fader_val == 0:
            self._log_message(f"MEM {mem_col + 1} — fader à 0, rien n'est envoyé", "warn")

        # Démarrer le timer de durée si le cue actif en a une
        self._start_cue_duration(mem_col, row)

        # Réinitialiser la position GO sur le pad activé manuellement
        if self.go_mode:
            self._go_col = mem_col
            self._go_row = row

        self._save_akai_config_auto()
        # Envoi DMX immediat sans attendre le prochain tick
        self.send_dmx_update()

    def trigger_memory(self, mem_col: int, row: int):
        """Slot public — déclenche un pad mémoire depuis le Stream Deck ou un signal externe."""
        if not (0 <= mem_col <= 7 and 0 <= row <= 7):
            return
        if self.memories[mem_col][row] is None:
            return
        self._activate_memory_pad(None, mem_col, row)

    # ── Helpers cues ─────────────────────────────────────────────────────────

    def _mem_ensure_cues(self, mem: dict):
        """Migre l'ancien format {projectors, effect} vers {cues:[...], loop:True}."""
        if mem is None or "cues" in mem:
            return
        cue0 = {
            "label": "Cue 1",
            "projectors": mem.pop("projectors", []),
            "effect": mem.pop("effect", {}),
            "duration": 0,
        }
        mem["cues"] = [cue0]
        mem.setdefault("loop", True)

    def _mem_active_cue(self, mem_col: int, row: int) -> dict:
        """Retourne le cue actuellement actif pour ce pad (dict vide si aucun)."""
        mem = self.memories[mem_col][row]
        if not mem:
            return {}
        self._mem_ensure_cues(mem)
        cues = mem["cues"]
        idx = self._mem_cue_idx.get((mem_col, row), 0)
        if not cues:
            return {}
        return cues[max(0, min(idx, len(cues) - 1))]

    def _mem_advance_cue(self, mem_col: int, row: int) -> bool:
        """Avance au cue suivant. Retourne False si on reste au même (boucle désactivée + fin)."""
        mem = self.memories[mem_col][row]
        if not mem:
            return False
        self._mem_ensure_cues(mem)
        cues = mem["cues"]
        if len(cues) <= 1:
            return False
        idx = self._mem_cue_idx.get((mem_col, row), 0)
        next_idx = idx + 1
        if next_idx >= len(cues):
            if mem.get("loop", True):
                next_idx = 0
            else:
                return False
        self._mem_cue_idx[(mem_col, row)] = next_idx
        return True

    def _mem_go_back_cue(self, mem_col: int, row: int) -> bool:
        """Recule au cue précédent. Retourne False si impossible."""
        mem = self.memories[mem_col][row]
        if not mem:
            return False
        self._mem_ensure_cues(mem)
        cues = mem["cues"]
        if len(cues) <= 1:
            return False
        idx = self._mem_cue_idx.get((mem_col, row), 0)
        prev_idx = idx - 1
        if prev_idx < 0:
            if mem.get("loop", True):
                prev_idx = len(cues) - 1
            else:
                return False
        self._mem_cue_idx[(mem_col, row)] = prev_idx
        return True

    def _open_cue_editor(self, mem_col: int, row: int):
        """Ouvre le panel Cues dans un panneau flottant positionné près du pad."""
        mem = self.memories[mem_col][row]
        if not mem:
            return
        self._mem_ensure_cues(mem)

        # Créer le wrapper flottant une seule fois
        if self._cue_float is None:
            w = QWidget(self, Qt.Tool | Qt.FramelessWindowHint)
            w.setAttribute(Qt.WA_TranslucentBackground)
            w.setFixedSize(650, 580)
            outer = QVBoxLayout(w)
            outer.setContentsMargins(0, 0, 0, 0)

            container = QWidget(w)
            container.setObjectName("cue_float")
            container.setStyleSheet("""
                QWidget#cue_float {
                    background: #0f0f0f;
                    border: 1px solid #2a2a2a;
                    border-radius: 10px;
                }
            """)
            inner = QVBoxLayout(container)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(0)

            # Barre titre avec bouton fermeture
            title_bar = QWidget()
            title_bar.setStyleSheet("background: #141414; border-radius: 10px 10px 0 0;")
            title_bar.setFixedHeight(32)
            tb_lay = QHBoxLayout(title_bar)
            tb_lay.setContentsMargins(12, 0, 8, 0)
            tb_lay.setSpacing(0)
            self._cue_float_lbl = QLabel("Cues")
            self._cue_float_lbl.setStyleSheet("color:#00d4ff; font-size:11px; font-weight:bold; background:transparent;")
            tb_lay.addWidget(self._cue_float_lbl)
            tb_lay.addStretch()
            close_btn = QPushButton("✕")
            close_btn.setFixedSize(20, 20)
            close_btn.setStyleSheet("""
                QPushButton { background:#2a2a2a; border:none; border-radius:4px;
                              color:#888; font-size:10px; font-weight:bold; }
                QPushButton:hover { background:#3a3a3a; color:#fff; }
            """)
            close_btn.clicked.connect(w.hide)
            tb_lay.addWidget(close_btn)
            inner.addWidget(title_bar)
            inner.addWidget(self._cue_panel)
            outer.addWidget(container)
            self._cue_float = w

        self._cue_panel.load(mem_col, row, mem)
        self._cue_panel.highlight_cue(self._mem_cue_idx.get((mem_col, row), 0))
        self._cue_float_lbl.setText(f"Cues — MEM {mem_col+1}.{row+1}")

        # Positionner près du pad
        anchor = None
        for col_akai in self._mem_col_to_faders(mem_col):
            pad = self.pads.get((row, col_akai))
            if pad:
                anchor = pad.mapToGlobal(pad.rect().topRight())
                break
        if anchor is None:
            anchor = self.mapToGlobal(self.rect().center())

        sg = self.screen().availableGeometry()
        fw, fh = self._cue_float.width(), self._cue_float.height()
        x = anchor.x() + 12
        y = anchor.y()
        if x + fw > sg.right():
            x = anchor.x() - fw - 12
        if y + fh > sg.bottom():
            y = sg.bottom() - fh - 8

        self._cue_float.move(x, y)
        self._cue_float.show()
        self._cue_float.raise_()

    def _on_cue_panel_changed(self):
        """Appelé quand le panel Cues modifie la mémoire."""
        mc, r = self._cue_panel.mem_col, self._cue_panel.row
        if mc >= 0:
            active = self.active_memory_pads.get(self._mem_col_to_fader(mc)) == r
            self._style_memory_pad(mc, r, active)
        self._save_akai_config_auto()

    def _on_cue_activated(self, cue_idx: int):
        """Clic/flèche sur le panel Cues → applique ce cue avec fade."""
        mc, r = self._cue_panel.mem_col, self._cue_panel.row
        if mc < 0 or self.memories[mc][r] is None:
            return
        self._mem_cue_idx[(mc, r)] = cue_idx
        col_akai = self._mem_col_to_fader(mc)
        fader_val = self.faders[col_akai].value if col_akai in self.faders else 100
        self._apply_cue_with_fade(mc, r, fader_val)
        mem = self.memories[mc][r]
        cue_lbl = mem["cues"][cue_idx].get("label", f"Cue {cue_idx+1}")
        n = len(mem["cues"])
        self._log_message(f"MEM {mc+1}.{r+1} → {cue_lbl} ({cue_idx+1}/{n})", "mem")
        self._style_memory_pad(mc, r, active=True)
        self._cue_panel.highlight_cue(cue_idx)
        self._start_cue_duration(mc, r)

    # ── Fade entre cues ───────────────────────────────────────────────────────

    def _on_cue_effect_pick(self, cue_row: int):
        """Ouvre un menu pour assigner/retirer un effet sur un cue."""
        mc, r = self._cue_panel.mem_col, self._cue_panel.row
        if mc < 0 or self.memories[mc][r] is None:
            return
        mem = self.memories[mc][r]
        self._mem_ensure_cues(mem)
        if not (0 <= cue_row < len(mem["cues"])):
            return
        cue = mem["cues"][cue_row]
        current_eff = (cue.get("effect") or {}).get("name", "")

        all_effects = []
        try:
            from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
            all_effects = list(BUILTIN_EFFECTS) + _load_custom_effects()
        except Exception:
            pass

        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#1a1a1a; border:1px solid #333; border-radius:6px; color:#e0e0e0; }
            QMenu::item { padding:6px 20px; font-size:12px; }
            QMenu::item:selected { background:#1e3a4a; color:#00d4ff; }
            QMenu::item:disabled { color:#444; }
            QMenu::separator { height:1px; background:#2a2a2a; margin:4px 0; }
        """)

        def _set(eff_or_none):
            cue["effect"] = eff_or_none or {}
            name = (eff_or_none or {}).get("name", "")
            self._cue_panel.set_cue_effect(cue_row, name)
            self._save_akai_config_auto()

        act_none = menu.addAction("⭕  Aucun effet")
        act_none.setCheckable(True)
        act_none.setChecked(not current_eff)
        act_none.triggered.connect(lambda: _set(None))
        menu.addSeparator()

        CATS = ["Strobe / Flash", "Mouvement", "Ambiance", "Couleur", "Permut", "Spécial", "Lyre", "Personnalisés", "Mes Effets"]
        for cat in CATS:
            cat_effs = [e for e in all_effects if e.get("category") == cat]
            if not cat_effs:
                continue
            hdr = menu.addAction(f"  {cat.upper()}")
            hdr.setEnabled(False)
            for eff in cat_effs:
                name_eff = eff.get("name", "")
                emoji = eff.get("emoji", "⚡")
                act = menu.addAction(f"  {emoji} {name_eff}")
                act.setCheckable(True)
                act.setChecked(name_eff == current_eff)
                act.triggered.connect(lambda checked=False, e=dict(eff): _set(e))

        # Positionner sur la cellule Effet
        table = self._cue_panel._table
        item  = table.item(cue_row, 4)
        if item:
            rect = table.visualItemRect(item)
            pos  = table.viewport().mapToGlobal(rect.bottomLeft())
        else:
            pos = self._cue_panel.mapToGlobal(self._cue_panel.rect().center())
        menu.exec(pos)

    def _apply_cue_with_fade(self, mem_col: int, row: int, fader_val: int):
        """Applique le cue actif avec fondu si fade > 0."""
        cue = self._mem_active_cue(mem_col, row)
        fade_secs = float(cue.get("fade", 0))
        if fade_secs <= 0:
            self._apply_memory_to_projectors(mem_col, row, fader_value=fader_val)
            return
        # Snapshot de l'état courant
        self._fade_from = [(p.level, QColor(p.base_color)) for p in self.projectors]
        # Calcul de l'état cible
        brightness = fader_val / 100.0
        to_state = []
        for ps in cue.get("projectors", []):
            if ps["level"] <= 0:
                to_state.append((0, QColor("black")))
            else:
                to_state.append((int(ps["level"] * brightness), QColor(ps["base_color"])))
        while len(to_state) < len(self.projectors):
            to_state.append((0, QColor("black")))
        self._fade_to    = to_state
        self._fade_start = time.time()
        self._fade_dur   = fade_secs
        self._fade_timer.start()
        # Déclencher/arrêter l'effet du cue
        eff_cfg = cue.get("effect") or {}
        new_eff = eff_cfg.get("name", "") if eff_cfg.get("layers") else ""
        cur_eff = getattr(self, "active_effect", None) or ""
        if new_eff != cur_eff:
            if cur_eff:
                self.stop_effect()
                self.active_effect = None
                self.active_effect_config = {}
            if new_eff:
                self.active_effect = new_eff
                self.active_effect_config = eff_cfg
                self.start_effect(new_eff)

    def _fade_tick(self):
        elapsed = time.time() - self._fade_start
        ratio = min(1.0, elapsed / max(0.01, self._fade_dur))
        for i, p in enumerate(self.projectors):
            if i >= len(self._fade_to):
                break
            fl, fc = (self._fade_from[i] if i < len(self._fade_from)
                      else (0, QColor("black")))
            tl, tc = self._fade_to[i]
            level = int(fl + (tl - fl) * ratio)
            rv = int(fc.red()   + (tc.red()   - fc.red())   * ratio)
            gv = int(fc.green() + (tc.green() - fc.green()) * ratio)
            bv = int(fc.blue()  + (tc.blue()  - fc.blue())  * ratio)
            p.level = level
            p.color = QColor(max(0,min(255,rv)), max(0,min(255,gv)), max(0,min(255,bv)))
            if ratio >= 1.0:
                p.base_color = tc
        if ratio >= 1.0:
            self._fade_timer.stop()

    # ── Durée auto-avance ─────────────────────────────────────────────────────

    def _start_cue_duration(self, mem_col: int, row: int):
        """Démarre le timer de durée pour le cue actif (si duration > 0)."""
        self._dur_timer.stop()
        self._dur_progress_timer.stop()
        if hasattr(self, "_cue_panel"):
            self._cue_panel.set_progress(-1)
        cue = self._mem_active_cue(mem_col, row)
        dur = float(cue.get("duration", 0))
        if dur <= 0:
            return
        self._dur_mem_col = mem_col
        self._dur_row     = row
        self._dur_start   = time.time()
        self._dur_secs    = dur
        self._dur_timer.start(int(dur * 1000))
        self._dur_progress_timer.start()

    def _update_cue_progress(self):
        if self._dur_secs <= 0:
            return
        ratio = min(1.0, (time.time() - self._dur_start) / self._dur_secs)
        if hasattr(self, "_cue_panel"):
            self._cue_panel.set_progress(ratio)

    def _on_duration_elapsed(self):
        self._dur_progress_timer.stop()
        mc, r = self._dur_mem_col, self._dur_row
        if mc < 0 or self.memories[mc][r] is None:
            return
        mem = self.memories[mc][r]
        self._mem_ensure_cues(mem)
        if not self._mem_advance_cue(mc, r):
            if hasattr(self, "_cue_panel"):
                self._cue_panel.set_progress(-1)
            return
        cue_idx = self._mem_cue_idx.get((mc, r), 0)
        col_akai = self._mem_col_to_fader(mc)
        fader_val = self.faders[col_akai].value if col_akai in self.faders else 100
        self._apply_cue_with_fade(mc, r, fader_val)
        n = len(mem["cues"])
        lbl = mem["cues"][cue_idx].get("label", f"Cue {cue_idx+1}")
        self._log_message(f"MEM {mc+1}.{r+1} → {lbl} ({cue_idx+1}/{n})", "mem")
        self._style_memory_pad(mc, r, active=True)
        if hasattr(self, "_cue_panel") and self._cue_panel.mem_col == mc and self._cue_panel.row == r:
            self._cue_panel.highlight_cue(cue_idx)
        self._start_cue_duration(mc, r)

    def _clear_memory_from_projectors(self, mem_col, row):
        """Remet à zéro les projecteurs actifs du cue courant de cette mémoire."""
        cue = self._mem_active_cue(mem_col, row)
        for i, proj_state in enumerate(cue.get("projectors", [])):
            if i >= len(self.projectors):
                break
            if proj_state["level"] > 0 or any(proj_state.get(k, 0) > 0 for k in ("uv", "amber_boost", "white_boost", "orange_boost")):
                p = self.projectors[i]
                p.level = 0
                p.base_color = QColor("black")
                p.color = QColor("black")
                p.uv           = 0
                p.amber_boost  = 0
                p.white_boost  = 0
                p.orange_boost = 0

    def _apply_memory_to_projectors(self, mem_col, row, fader_value=None, trigger_effect=True):
        """Applique le cue courant de la mémoire sur les projecteurs."""
        mem = self.memories[mem_col][row]
        if not mem:
            return
        col_akai = self._mem_col_to_fader(mem_col)
        if col_akai in self._muted_faders:
            return
        self._mem_ensure_cues(mem)
        if fader_value is None:
            col_akai = self._mem_col_to_fader(mem_col)
            fader_value = self.faders[col_akai].value if col_akai in self.faders else 100
        brightness = fader_value / 100.0

        cue = self._mem_active_cue(mem_col, row)
        for i, proj_state in enumerate(cue.get("projectors", [])):
            if i >= len(self.projectors):
                break
            p = self.projectors[i]
            if "pan"  in proj_state:
                v = proj_state["pan"];  p.pan  = v * 256 if v <= 255 else v
            if "tilt" in proj_state:
                v = proj_state["tilt"]; p.tilt = v * 256 if v <= 255 else v
            # Canaux spéciaux toujours restaurés (même si level == 0)
            p.uv           = int(proj_state.get("uv",           0) * brightness)
            p.amber_boost  = int(proj_state.get("amber_boost",  0) * brightness)
            p.white_boost  = int(proj_state.get("white_boost",  0) * brightness)
            p.orange_boost = int(proj_state.get("orange_boost", 0) * brightness)
            if proj_state["level"] <= 0:
                p.level = 0
                p.base_color = QColor("black")
                p.color = QColor("black")
                continue
            level = int(proj_state["level"] * brightness)
            base_color = QColor(proj_state["base_color"])
            p.level = level
            p.base_color = base_color
            p.color = QColor(
                int(base_color.red()   * level / 100.0),
                int(base_color.green() * level / 100.0),
                int(base_color.blue()  * level / 100.0)
            )

        # Déclencher/arrêter l'effet du cue courant
        if trigger_effect:
            eff_cfg = cue.get("effect") or {}
            new_eff = eff_cfg.get("name", "") if (eff_cfg.get("layers") and fader_value > 0) else ""
            cur_eff = getattr(self, "active_effect", None) or ""
            if new_eff != cur_eff:
                if cur_eff:
                    self.stop_effect()
                    self.active_effect = None
                    self.active_effect_config = {}
                if new_eff:
                    self.active_effect = new_eff
                    self.active_effect_config = eff_cfg
                    self.start_effect(new_eff)

    def _style_memory_pad(self, mem_col, row, active):
        """Style visuel d'un pad mémoire — met à jour toutes les colonnes mappées sur ce MEM."""
        for col_akai in self._mem_col_to_faders(mem_col):
            self._style_memory_pad_col(mem_col, row, active, col_akai)

    def _style_memory_pad_col(self, mem_col, row, active, col_akai):
        """Style visuel d'un pad mémoire pour une colonne AKAI donnée."""
        pad = self.pads.get((row, col_akai))
        if not pad:
            return

        color = self._get_memory_pad_color(mem_col, row)
        mem_d = self.memories[mem_col][row] or {}
        # Cues : afficher n/N si multi-cue et actif
        self._mem_ensure_cues(mem_d) if mem_d else None
        n_cues = len(mem_d.get("cues", [])) if mem_d else 0
        cue_idx = self._mem_cue_idx.get((mem_col, row), 0)
        cur_cue = mem_d["cues"][min(cue_idx, n_cues-1)] if n_cues > 0 else {}
        has_effect = bool(cur_cue.get("effect") or mem_d.get("effect") if mem_d else False)

        if n_cues > 1:
            pad.setText(f"{cue_idx+1}/{n_cues}")
        elif has_effect:
            pad.setText("⚡")
        else:
            pad.setText("")
        if color == QColor("black") or self.memories[mem_col][row] is None:
            pad.setProperty("base_color", QColor("black"))
            pad.setStyleSheet("""
                QPushButton {
                    background: #1a1a1a;
                    border: 1px solid #1a1a1a;
                    border-radius: 4px;
                    color: rgba(255,255,255,0.5);
                    font-size: 8px;
                }
            """)
        elif active:
            pad.setProperty("base_color", color)
            pad.setStyleSheet(f"""
                QPushButton {{
                    background: {color.name()};
                    border: 2px solid {color.lighter(130).name()};
                    border-radius: 4px;
                    color: rgba(255,255,255,0.8);
                    font-size: 8px;
                }}
            """)
        else:
            dim_color = QColor(int(color.red() * 0.5), int(color.green() * 0.5), int(color.blue() * 0.5))
            pad.setProperty("base_color", color)
            pad.setStyleSheet(f"""
                QPushButton {{
                    background: {dim_color.name()};
                    border: 1px solid #2a2a2a;
                    border-radius: 4px;
                    color: rgba(255,255,255,0.6);
                    font-size: 8px;
                }}
            """)
        pad.setToolTip(self._build_memory_tooltip(mem_col, row))

    def _build_memory_tooltip(self, mem_col, row):
        """Construit le tooltip HTML d'un pad mémoire."""
        label = f"MEM {mem_col + 1}.{row + 1}"
        mem = self.memories[mem_col][row]
        if not mem:
            return f"<b>{label}</b><br><small style='color:#888'>Vide</small>"
        lines = [f"<b>{label}</b>"]
        group_info = {}
        for i, ps in enumerate(mem.get("projectors", [])):
            if ps.get("level", 0) > 0 and i < len(self.projectors):
                g = self.projectors[i].group
                gname = self.GROUP_DISPLAY.get(g, g.capitalize())
                color_hex = ps.get("base_color", "#ffffff")
                lvl = ps.get("level", 0)
                if gname not in group_info:
                    group_info[gname] = (color_hex, lvl)
        return f"<b>{label}</b>"

    def _get_memory_pad_color(self, mem_col, row):
        """Retourne la couleur custom ou dominante du snapshot"""
        custom = self.memory_custom_colors[mem_col][row]
        if custom:
            return custom

        mem = self.memories[mem_col][row]
        if not mem:
            return QColor("black")
        self._mem_ensure_cues(mem)
        projectors = (mem["cues"][0].get("projectors", []) if mem.get("cues") else
                      mem.get("projectors", []))
        color_counts = {}
        for ms in projectors:
            if ms["level"] > 0:
                c = ms["base_color"]
                color_counts[c] = color_counts.get(c, 0) + 1
        if not color_counts:
            return QColor("black")
        dominant = max(color_counts, key=color_counts.get)
        return QColor(dominant)

    def _update_memory_pad_led(self, mem_col, row, active):
        """Envoie LED MIDI pour un pad memoire — met à jour toutes les colonnes mappées sur ce MEM."""
        if not (MIDI_AVAILABLE and hasattr(self, 'midi_handler')):
            return
        color = self._get_memory_pad_color(mem_col, row)
        for col_akai in self._mem_col_to_faders(mem_col):
            if self.memories[mem_col][row] is None or color == QColor("black"):
                self.midi_handler.set_pad_led(row, col_akai, 0, 0)
            else:
                velocity = rgb_to_akai_velocity(color)
                brightness = 100 if active else 20
                self.midi_handler.set_pad_led(row, col_akai, velocity, brightness)

    def _blink_memory_pad(self, mem_col, row, n_blinks=6):
        """Fait clignoter un pad mémoire n_blinks fois après enregistrement."""
        col_akai = self._mem_col_to_fader(mem_col)
        pad = self.pads.get((row, col_akai))
        if not pad:
            return

        blink_state = [0]
        total_ticks = n_blinks * 2  # ON + OFF par blink

        def _tick():
            blink_state[0] += 1
            if blink_state[0] > total_ticks:
                # Restaurer le style normal
                is_active = self.active_memory_pads.get(col_akai) == row
                self._style_memory_pad(mem_col, row, active=is_active)
                self._update_memory_pad_led(mem_col, row, active=is_active)
                return

            on = (blink_state[0] % 2 == 1)
            if on:
                pad.setStyleSheet(
                    "QPushButton { background: #ffffff; border: 2px solid #cccccc; border-radius: 4px; }"
                )
                if MIDI_AVAILABLE and hasattr(self, 'midi_handler') and self.midi_handler.midi_out:
                    self.midi_handler.set_pad_led(row, col_akai, 3, brightness_percent=100)
            else:
                pad.setStyleSheet(
                    "QPushButton { background: #111111; border: 1px solid #333333; border-radius: 4px; }"
                )
                if MIDI_AVAILABLE and hasattr(self, 'midi_handler') and self.midi_handler.midi_out:
                    self.midi_handler.set_pad_led(row, col_akai, 0)

            QTimer.singleShot(200, _tick)

        _tick()

    def _set_memory_custom_color(self, mem_col, row, color):
        """Definit une couleur personnalisee pour un pad memoire"""
        self.memory_custom_colors[mem_col][row] = color
        col_akai = self._mem_col_to_fader(mem_col)
        is_active = self.active_memory_pads.get(col_akai) == row
        self._style_memory_pad(mem_col, row, active=is_active)
        self._update_memory_pad_led(mem_col, row, active=is_active)
        # Sauvegarde auto immediate
        self._save_akai_config_auto()

    def _build_snapshot(self) -> dict:
        """Construit un cue snapshot depuis l'état courant des projecteurs."""
        snapshot = []
        for p in self.projectors:
            snapshot.append({
                "group":        p.group,
                "base_color":   p.base_color.name() if p.level > 0 else "#000000",
                "level":        p.level,
                "pan":          getattr(p, 'pan',          32768),
                "tilt":         getattr(p, 'tilt',         32768),
                "uv":           getattr(p, 'uv',           0),
                "amber_boost":  getattr(p, 'amber_boost',  0),
                "white_boost":  getattr(p, 'white_boost',  0),
                "orange_boost": getattr(p, 'orange_boost', 0),
            })
        return {"projectors": snapshot, "effect": {}, "duration": 0}

    def _record_memory(self, mem_col, row):
        """Capture l'état courant. Si la mémoire existe, propose Remplacer / Ajouter cue."""
        cue = self._build_snapshot()
        mem = self.memories[mem_col][row]

        if mem is not None:
            self._mem_ensure_cues(mem)
            n = len(mem["cues"])
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox(self)
            msg.setWindowTitle(f"MEM {mem_col + 1}.{row + 1}")
            msg.setText(f"Cette mémoire contient déjà {n} cue{'s' if n > 1 else ''}.")
            msg.setStyleSheet("background:#1e1e1e; color:white;")
            btn_replace = msg.addButton("Remplacer le cue actuel", QMessageBox.AcceptRole)
            btn_add     = msg.addButton(f"Ajouter cue {n + 1}", QMessageBox.ActionRole)
            msg.addButton("Annuler", QMessageBox.RejectRole)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == btn_replace:
                idx = self._mem_cue_idx.get((mem_col, row), 0)
                idx = max(0, min(idx, n - 1))
                cue["label"] = mem["cues"][idx].get("label", f"Cue {idx + 1}")
                mem["cues"][idx] = cue
            elif clicked == btn_add:
                cue["label"] = f"Cue {n + 1}"
                mem["cues"].append(cue)
                if hasattr(self, '_cue_panel') and self._cue_panel.mem_col == mem_col \
                        and self._cue_panel.row == row:
                    self._cue_panel._refresh()
            else:
                return
        else:
            cue["label"] = "Cue 1"
            self.memories[mem_col][row] = {"cues": [cue], "loop": True}

        col_akai = self._mem_col_to_fader(mem_col)
        is_active = self.active_memory_pads.get(col_akai) == row
        self._style_memory_pad(mem_col, row, active=is_active)
        self._update_memory_pad_led(mem_col, row, active=is_active)
        self._save_akai_config_auto()

    def _show_memory_context_menu(self, pos, mem_col, row, btn):
        """Menu contextuel sur un pad memoire"""
        menu_style = """
            QMenu {
                background: #1e1e1e; color: white;
                border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px;
            }
            QMenu::item { padding: 6px 20px; }
            QMenu::item:selected { background: #3a3a3a; }
        """
        menu = QMenu(self)
        menu.setStyleSheet(menu_style)

        # Header : nom de la mémoire
        label = f"MEM {mem_col + 1}.{row + 1}"
        from PySide6.QtWidgets import QWidgetAction, QLabel
        header_label = QLabel(f"  {label}  ")
        header_label.setStyleSheet("""
            QLabel {
                color: #aaa;
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
                padding: 4px 12px 4px 12px;
                border-bottom: 1px solid #333;
                background: transparent;
            }
        """)
        header_wa = QWidgetAction(menu)
        header_wa.setDefaultWidget(header_label)
        menu.addAction(header_wa)
        menu.addSeparator()

        def _record_and_feedback():
            self._record_memory(mem_col, row)
            self._log_message(f"Rec MEM {mem_col + 1}.{row + 1} OK", "rec")
            self._blink_memory_pad(mem_col, row)

        if self.memories[mem_col][row] is None:
            save_action = menu.addAction("💾  Sauvegarder")
            save_action.triggered.connect(_record_and_feedback)
        else:
            replace_action = menu.addAction("🔄  Remplacer")
            replace_action.triggered.connect(_record_and_feedback)
            clear_action = menu.addAction("🗑  Effacer")
            clear_action.triggered.connect(lambda: self._clear_memory(mem_col, row))

            mem_tmp = self.memories[mem_col][row]
            self._mem_ensure_cues(mem_tmp)
            n_cues = len(mem_tmp.get("cues", []))
            cues_lbl = f"📋  Cues  ({n_cues})" if n_cues > 1 else "📋  Cues"
            cues_action = menu.addAction(cues_lbl)
            cues_action.triggered.connect(lambda: self._open_cue_editor(mem_col, row))

            menu.addSeparator()

            # Sous-menu couleur du pad
            color_menu = menu.addMenu("🎨  Couleur du pad")
            color_menu.setStyleSheet(menu_style)

            auto_action = color_menu.addAction("Auto (dominante)")
            auto_action.triggered.connect(lambda: self._set_memory_custom_color(mem_col, row, None))

            pad_colors = [
                ("Blanc", QColor(255, 255, 255)),
                ("Rouge", QColor(255, 0, 0)),
                ("Orange", QColor(255, 136, 0)),
                ("Jaune", QColor(255, 221, 0)),
                ("Vert", QColor(0, 255, 0)),
                ("Cyan", QColor(0, 221, 221)),
                ("Bleu", QColor(0, 0, 255)),
                ("Magenta", QColor(255, 0, 255)),
            ]
            for name, col in pad_colors:
                px = QPixmap(16, 16)
                px.fill(col)
                action = color_menu.addAction(QIcon(px), name)
                action.triggered.connect(lambda _, c=col: self._set_memory_custom_color(mem_col, row, c))

            # Sous-menu effet
            menu.addSeparator()
            mem_data = self.memories[mem_col][row]
            current_effect = (mem_data or {}).get("effect", {}).get("name") if mem_data else None
            eff_label = f"⚡  Effet : {current_effect}" if current_effect else "⚡  Ajouter un effet"
            effect_menu = menu.addMenu(eff_label)
            effect_menu.setStyleSheet(menu_style)

            all_effects = []
            try:
                from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
                all_effects = list(BUILTIN_EFFECTS) + _load_custom_effects()
            except Exception:
                pass

            def _apply_effect(eff_or_none, mc=mem_col, r=row):
                self._set_memory_effect(mc, r, eff_or_none)
                col_akai = self._mem_col_to_fader(mc)
                self._style_memory_pad(mc, r, self.active_memory_pads.get(col_akai) == r)

            act_none = effect_menu.addAction("⭕  Aucun")
            act_none.setCheckable(True)
            act_none.setChecked(not current_effect)
            act_none.triggered.connect(lambda: _apply_effect(None))
            effect_menu.addSeparator()

            CATS = ["Strobe / Flash", "Mouvement", "Ambiance", "Couleur", "Spécial", "Personnalisés", "Mes Effets"]
            for cat in CATS:
                cat_effs = [e for e in all_effects if e.get("category") == cat]
                if not cat_effs:
                    continue
                hdr = effect_menu.addAction(f"  {cat.upper()}")
                hdr.setEnabled(False)
                for eff in cat_effs:
                    name_eff = eff.get("name", "")
                    act = effect_menu.addAction(f"  {name_eff}")
                    act.setCheckable(True)
                    act.setChecked(name_eff == current_effect)
                    act.triggered.connect(lambda checked=False, e=dict(eff): _apply_effect(e))

        menu.exec(btn.mapToGlobal(pos))

    def _set_memory_effect(self, mem_col, row, eff_dict_or_none):
        """Associe (ou retire) un effet à une mémoire."""
        mem = self.memories[mem_col][row]
        if mem is None:
            return
        if eff_dict_or_none is None:
            mem.pop("effect", None)
        else:
            name = eff_dict_or_none.get("name", "")
            # Chercher config complète (layers, play_mode, duration) dans les sources sauvegardées
            full_cfg = {}
            for cfg in getattr(self, '_button_effect_configs', {}).values():
                if isinstance(cfg, dict) and cfg.get("name") == name:
                    full_cfg = cfg
                    break
            if not full_cfg:
                full_cfg = getattr(self, '_effect_library_configs', {}).get(name, {})
            if full_cfg:
                mem["effect"] = dict(full_cfg)
            else:
                from effect_editor import EffectLayer
                layers = EffectLayer.layers_from_builtin(eff_dict_or_none)
                mem["effect"] = {
                    "name": name,
                    "type": eff_dict_or_none.get("type", ""),
                    "layers": [l.to_dict() for l in layers],
                    "play_mode": "loop",
                    "duration": 0,
                }
        self._save_akai_config_auto()

    def _clear_memory(self, mem_col, row):
        """Efface une memoire individuelle"""
        self.memories[mem_col][row] = None
        self.memory_custom_colors[mem_col][row] = None
        col_akai = self._mem_col_to_fader(mem_col)
        if self.active_memory_pads.get(col_akai) == row:
            del self.active_memory_pads[col_akai]
        self._style_memory_pad(mem_col, row, active=False)
        self._update_memory_pad_led(mem_col, row, active=False)
        # Sauvegarde auto immediate
        self._save_akai_config_auto()

    def set_proj_level(self, index, value):
        """Gere les faders - chaque fader est independant"""
        if index >= len(self._fader_map):
            return
        slot = self._fader_map[index]

        if slot["type"] == "memory":
            mem_col = slot["mem_col"]
            active_row = self.active_memory_pads.get(index)
            # Auto-activation pad du haut si aucun pad actif dans cette colonne MEM
            if active_row is None and value > 0 and self.memories[mem_col][0] is not None:
                self.active_memory_pads[index] = 0
                self._style_memory_pad(mem_col, 0, active=True)
                active_row = 0
            if active_row is not None and self.memories[mem_col][active_row]:
                if value == 0:
                    # Fader à zéro : zeroing projecteurs + couper l'effet si c'est le sien
                    self._apply_memory_to_projectors(mem_col, active_row, fader_value=0, trigger_effect=False)
                    mem_eff_name = (self.memories[mem_col][active_row].get("effect") or {}).get("name")
                    if mem_eff_name and getattr(self, 'active_effect', None) == mem_eff_name:
                        self.stop_effect()
                        self.active_effect = None
                        self.active_effect_config = {}
                else:
                    mem_eff_name = (self.memories[mem_col][active_row].get("effect") or {}).get("name")
                    if mem_eff_name and getattr(self, 'active_effect', None) == mem_eff_name:
                        # Effet actif : ne pas écraser ses couleurs à chaque tick de fader
                        pass
                    else:
                        # Appliquer avec value directement (evite le lag MIDI de fader.value)
                        self._apply_memory_to_projectors(mem_col, active_row, fader_value=value)
            self.send_dmx_update()
            return

        if slot["type"] == "fx":
            if index in self._muted_faders:
                return
            fx_col = slot.get("fx_col", 0)
            if 0 <= fx_col < _FX_COL_MAX:
                prev_amp = self.fx_amplitudes[fx_col]
                self.fx_amplitudes[fx_col] = value
                # Fader FX descend à 0 : éteindre les projecteurs une fois pour
                # libérer la main aux colonnes MEM (sinon update_effect écrase tout)
                if value == 0 and prev_amp > 0:
                    for p in self.projectors:
                        p.color = QColor("black")
                    self.send_dmx_update()
            return

        if index in self._muted_faders:
            return

        groups = self._slot_groups(slot)
        if not groups:
            return

        # Auto-activation pad blanc si aucun pad actif dans CETTE colonne
        if index not in self.active_pads and value > 0:
            white_pad = self.pads.get((0, index))
            if white_pad:
                color = white_pad.property("base_color")
                white_pad.setStyleSheet(f"QPushButton {{ background: {color.name()}; border: 2px solid {color.lighter(130).name()}; border-radius: 4px; }}")
                self.active_pads[index] = white_pad
                for p in self.projectors:
                    if p.group in groups:
                        p.base_color = color
        elif index in self.active_pads and value > 0:
            # Resync base_color sur tous les projecteurs du groupe avec la couleur du pad actif
            # (une mémoire HTP peut avoir changé base_color d'un projecteur individuellement)
            active_color = self.active_pads[index].property("base_color")
            for p in self.projectors:
                if p.group in groups:
                    p.base_color = active_color

        brightness = value / 100.0 if value > 0 else 0
        for p in self.projectors:
            if p.group in groups:
                p.level = value
                if value > 0:
                    p.color = QColor(
                        int(p.base_color.red() * brightness),
                        int(p.base_color.green() * brightness),
                        int(p.base_color.blue() * brightness))
                else:
                    p.color = QColor("black")

        # Envoi DMX immediat sans attendre le prochain tick
        self.send_dmx_update()

    def toggle_mute(self, index, active):
        """Gere les mutes - chaque fader est independant"""
        if index >= len(self._fader_map):
            return
        slot = self._fader_map[index]

        if active:
            self._muted_faders.add(index)
        else:
            self._muted_faders.discard(index)

        if slot["type"] == "memory":
            self.send_dmx_update()
            return

        if slot["type"] == "fx":
            self.send_dmx_update()
            return

        # Groupe : zéroter les projecteurs du groupe immédiatement
        groups = self._slot_groups(slot)
        for p in self.projectors:
            if p.group in groups:
                if active:
                    p.level = 0
                    p.color = QColor("black")
                else:
                    # Restaurer depuis la valeur du fader
                    fader_val = self.faders[index].value if index in self.faders else 0
                    brightness = fader_val / 100.0
                    p.level = fader_val
                    p.color = QColor(
                        int(p.base_color.red() * brightness),
                        int(p.base_color.green() * brightness),
                        int(p.base_color.blue() * brightness))
        self.send_dmx_update()

    def toggle_effect(self, effect_idx):
        """Active/desactive un effet"""
        btn = self.effect_buttons[effect_idx]

        # Bascule = one-shot sur chaque appui (pas de toggle on/off)
        if btn.current_effect == "Bascule":
            self._bascule()
            btn.active = False
            btn.update_style()
            return

        # ── Mode superposition : plusieurs effets simultanés ─────────────────
        if self.effect_superposition:
            btn.active = not btn.active
            if btn.active:
                effect_name = btn.current_effect
                if not effect_name:
                    btn.active = False
                    btn.update_style()
                    return
                import time as _time
                eff_state = {
                    'idx': effect_idx,
                    'name': effect_name,
                    'config': self._button_effect_configs.get(effect_idx, {}),
                    'state': 0, 'hue': 0, 'brightness': 0, 'direction': 1,
                    't0': _time.monotonic(),
                }
                if not self._stacked_effects:
                    # Premier effet : sauvegarder les couleurs et démarrer le timer
                    self.effect_saved_colors = {}
                    for p in self.projectors:
                        self.effect_saved_colors[id(p)] = (
                            p.base_color, p.color, p.level,
                            getattr(p, 'pan', 32768), getattr(p, 'tilt', 32768)
                        )
                    if not hasattr(self, 'effect_timer'):
                        self.effect_timer = QTimer()
                        self.effect_timer.timeout.connect(self.update_effect)
                    self.effect_timer.start(40)
                self._stacked_effects.append(eff_state)
                self.active_effect = effect_name
                self.active_effect_config = eff_state['config']
                self._log_message(f"Effet ON : {effect_name}", "effect")
            else:
                # Retirer cet effet de la pile
                old_name = next((e['name'] for e in self._stacked_effects if e['idx'] == effect_idx), btn.current_effect or "")
                self._stacked_effects = [e for e in self._stacked_effects if e['idx'] != effect_idx]
                self._log_message(f"Effet OFF : {old_name}", "effect")
                if not self._stacked_effects:
                    # Dernier effet : arrêter le timer et restaurer les couleurs
                    if hasattr(self, 'effect_timer'):
                        self.effect_timer.stop()
                    for p in self.projectors:
                        if id(p) in self.effect_saved_colors:
                            saved = self.effect_saved_colors[id(p)]
                            p.base_color, p.color, p.level = saved[0], saved[1], saved[2]
                            if len(saved) > 3:
                                p.pan = saved[3]; p.tilt = saved[4]
                    self.active_effect = None
                    self.active_effect_config = {}
                else:
                    self.active_effect = self._stacked_effects[-1]['name']
                    self.active_effect_config = self._stacked_effects[-1]['config']
            btn.update_style()
            if MIDI_AVAILABLE and self.midi_handler.midi_out and effect_idx < 8:
                velocity = 1 if btn.active else 0
                self.midi_handler.set_pad_led(effect_idx, 8, velocity, brightness_percent=100)
            return

        # ── Mode exclusif (par défaut) : un seul effet à la fois ─────────────
        btn.active = not btn.active
        if btn.active:
            effect_name = btn.current_effect
            if not effect_name:
                btn.active = False
                btn.update_style()
                return

            # Sauvegarder l'état précédent — uniquement si l'effet vient d'un FX pad,
            # pas d'un autre bouton d'effet (sinon désactiver B relancerait A)
            self._prev_effect_state = {
                "effect":  self.active_effect if self.active_fx_pads else None,
                "config":  dict(self.active_effect_config) if (self.active_effect_config and self.active_fx_pads) else {},
                "fx_pads": dict(self.active_fx_pads),
            }
            # Désactiver visuellement les pads FX actifs sans stopper l'effet
            # (stop_effect sera appelé par start_effect)
            for k in list(self.active_fx_pads.keys()):
                self.active_fx_pads.pop(k)
                self._style_fx_pad(k[0], k[1])

            self.active_effect = effect_name
            self.active_effect_config = self._button_effect_configs.get(effect_idx, {})
            self.start_effect(effect_name)
            self._log_message(f"Effet ON : {effect_name}", "effect")
            for j, other_btn in enumerate(self.effect_buttons):
                if j != effect_idx and other_btn.active:
                    other_btn.active = False
                    other_btn.update_style()
                    if MIDI_AVAILABLE and self.midi_handler.midi_out:
                        self.midi_handler.set_pad_led(j, 8, 0)
        else:
            # Restaurer l'état précédent s'il existait
            self._log_message(f"Effet OFF : {btn.current_effect}", "effect")
            prev = getattr(self, '_prev_effect_state', None)
            self._prev_effect_state = None
            self.stop_effect()

            restored = False
            if prev:
                # Restaurer les pads FX actifs
                for (fc, fr) in prev.get("fx_pads", {}).keys():
                    cfg = self.fx_pads[fc][fr] if fc < 4 else None
                    if cfg:
                        self.active_fx_pads[(fc, fr)] = True
                        self._style_fx_pad(fc, fr)
                        self.active_effect = cfg.get("name", "")
                        self.active_effect_config = cfg
                        self.start_effect(self.active_effect)
                        restored = True
                        break  # un seul FX actif à la fois
                # Restaurer un effet non-FX s'il n'y avait pas de pad FX
                if not restored and prev.get("effect"):
                    self.active_effect = prev["effect"]
                    self.active_effect_config = prev["config"]
                    self.start_effect(self.active_effect)
                    restored = True

            if not restored:
                self.active_effect = None
                self.active_effect_config = {}

        btn.update_style()
        # Mise a jour LED AKAI (utile quand l'effet est toggle depuis l'UI)
        if MIDI_AVAILABLE and self.midi_handler.midi_out and effect_idx < 8:
            velocity = 1 if btn.active else 0
            self.midi_handler.set_pad_led(effect_idx, 8, velocity, brightness_percent=100)

    # ── FX pad columns (standalone, right of AKAI) ───────────────────────────

    def _style_fx_pad(self, fx_col, row):
        """Rafraîchit le style des pads AKAI mappés sur ce slot FX."""
        cfg = self.fx_pads[fx_col][row] if fx_col < _FX_COL_MAX else None
        active = self.active_fx_pads.get((fx_col, row))
        for col_idx, slot in enumerate(self._fader_map):
            if slot.get("type") == "fx" and slot.get("fx_col") == fx_col:
                pad = self.pads.get((row, col_idx))
                if not pad:
                    continue
                if active and cfg:
                    pad.setStyleSheet("QPushButton { background: #33ff33; border: 2px solid #ffffff; border-radius: 4px; }")
                    pad.setToolTip(cfg.get("name", ""))
                elif cfg:
                    pad.setStyleSheet("QPushButton { background: #116611; border: 1px solid #114411; border-radius: 4px; }")
                    pad.setToolTip(cfg.get("name", ""))
                else:
                    pad.setStyleSheet("QPushButton { background: #0a1a0a; border: 1px solid #1a2a1a; border-radius: 4px; }")
                    pad.setToolTip("")

    def _update_fx_pad_led(self, fx_col, row):
        """Envoie la LED MIDI physique pour un pad FX sur toutes les colonnes mappées."""
        if not (MIDI_AVAILABLE and hasattr(self, 'midi_handler') and self.midi_handler.midi_out):
            return
        cfg = self.fx_pads[fx_col][row] if fx_col < _FX_COL_MAX else None
        is_active = self.active_fx_pads.get((fx_col, row))
        for col_idx, slot in enumerate(self._fader_map):
            if slot.get("type") == "fx" and slot.get("fx_col") == fx_col:
                if is_active and cfg:
                    self.midi_handler.set_pad_led(row, col_idx, 21, brightness_percent=100)
                elif cfg:
                    self.midi_handler.set_pad_led(row, col_idx, 21, brightness_percent=20)
                else:
                    self.midi_handler.set_pad_led(row, col_idx, 0, brightness_percent=0)

    def _open_effect_editor_for_fx_pad(self, fx_col, row):
        """Ouvre l'éditeur d'effets pour un pad FX."""
        from effect_editor import EffectEditorDialog
        current = self.fx_pads[fx_col][row]
        initial = current.get("name") if current else None
        dlg = EffectEditorDialog(clips=[], main_window=self, parent=self, initial_effect=initial)
        dlg.exec()

    def _toggle_fx_pad(self, fx_col, row):
        """Toggle an FX pad on/off."""
        # Mode REC actif : impossible d'enregistrer sur un pad FX
        if self._mem_rec_mode:
            self._mem_rec_mode = False
            if self._rec_mem_btn:
                self._rec_mem_btn.setStyleSheet(
                    "QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #3a3a3a; "
                    "border-radius: 4px; font-size: 13px; } "
                    "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #cc3333; }"
                )
                self._rec_mem_btn.setToolTip("REC Mémoire — cliquez pour activer, puis cliquez sur un pad")
            self._update_non_mem_pad_tooltips()
            self._show_error_toast("✖ Impossible d'enregistrer sur un FX — Pour ajouter un effet, cliquez droit sur le pad")
            return
        cfg = self.fx_pads[fx_col][row] if fx_col < _FX_COL_MAX else None
        if not cfg:
            return
        key = (fx_col, row)
        if self.active_fx_pads.get(key):
            # Turn off
            self.active_fx_pads.pop(key, None)
            self.active_effect = None
            self.active_effect_config = {}
            self.stop_effect()
        else:
            # Deactivate all other FX pads
            for k in list(self.active_fx_pads.keys()):
                self.active_fx_pads.pop(k, None)
                self._style_fx_pad(k[0], k[1])
            # Deactivate EffectButton column too
            for btn in self.effect_buttons:
                if btn.active:
                    btn.active = False
                    btn.update_style()
            # Turn on
            self.active_fx_pads[key] = True
            eff_name = cfg.get("name", "")
            self.active_effect = eff_name
            self.active_effect_config = cfg
            self.start_effect(eff_name)
        # Rafraîchir tous les pads FX (visuel + LEDs physiques)
        for fc in range(_FX_COL_MAX):
            for r in range(8):
                self._style_fx_pad(fc, r)
                self._update_fx_pad_led(fc, r)

    def _show_fx_context_menu(self, pos, fx_col, row, btn):
        """Menu clic droit sur un pad FX — identique aux petits carrés verts."""
        from PySide6.QtWidgets import (QMenu, QWidgetAction, QLineEdit,
                                        QDoubleSpinBox, QHBoxLayout, QLabel)
        from pathlib import Path as _Path

        # Charger tous les effets : builtin + custom
        all_effects = []
        try:
            from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
            all_effects = list(BUILTIN_EFFECTS) + _load_custom_effects()
        except Exception:
            pass

        current_cfg = self.fx_pads[fx_col][row] if fx_col < _FX_COL_MAX else None
        cur = current_cfg.get("name") if current_cfg else None
        trigger_mode = (current_cfg or {}).get("trigger_mode", "toggle")
        trigger_duration = (current_cfg or {}).get("trigger_duration", 2000)

        menu = QMenu(btn)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item { padding: 6px 16px; border-radius: 3px; color: #e0e0e0; }
            QMenu::item:selected { background: #2a3a3a; color: #fff; }
            QMenu::item:disabled { color: #555; font-size: 10px; letter-spacing: 1px; }
            QMenu::separator { background: #333; height: 1px; margin: 3px 8px; }
        """)

        # ── Barre de recherche ────────────────────────────────────────────────
        search_container = QWidget()
        search_container.setStyleSheet("background: transparent;")
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(6, 4, 6, 4)
        search_input = QLineEdit()
        search_input.setPlaceholderText("  Rechercher un effet…")
        search_input.setClearButtonEnabled(True)
        search_input.setStyleSheet("""
            QLineEdit {
                background: #111; color: #e0e0e0;
                border: 1px solid #444; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #00d4ff; }
        """)
        def _search_key(event):
            if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter):
                event.accept(); return
            QLineEdit.keyPressEvent(search_input, event)
        search_input.keyPressEvent = _search_key
        search_layout.addWidget(search_input)
        search_wa = QWidgetAction(menu)
        search_wa.setDefaultWidget(search_container)
        menu.addAction(search_wa)
        menu.addSeparator()

        name_is_full_match = cur and any(e.get("name") == cur for e in all_effects)
        def _is_checked(eff):
            name = eff.get("name", "")
            if name == cur: return True
            if not name_is_full_match and cur and eff.get("type") == cur:
                first = next((e for e in all_effects if e.get("type") == cur), None)
                return first is not None and first.get("name") == name
            return False

        def _select(cfg_or_none):
            if cfg_or_none is None:
                self.fx_pads[fx_col][row] = None
                self.active_fx_pads.pop((fx_col, row), None)
                # Stopper l'effet si c'est lui qui tourne actuellement
                if cur and self.active_effect == cur:
                    self.active_effect = None
                    self.active_effect_config = {}
                    self.stop_effect()
                    for btn in self.effect_buttons:
                        if btn.active and btn.current_effect == cur:
                            btn.active = False
                            btn.update_style()
            else:
                entry = dict(cfg_or_none)
                entry["trigger_mode"] = trigger_mode
                entry["trigger_duration"] = trigger_duration
                self.fx_pads[fx_col][row] = entry
            self._style_fx_pad(fx_col, row)
            self._save_akai_config_auto()

        act_none = menu.addAction("⭕  Aucun")
        act_none.setCheckable(True)
        act_none.setChecked(not cur)
        act_none.triggered.connect(lambda: _select(None))
        sep_top = menu.addSeparator()

        CATS = ["Strobe / Flash", "Mouvement", "Ambiance", "Couleur", "Spécial", "Personnalisés", "Mes Effets"]
        cat_groups = []
        for cat in CATS:
            cat_effs = [e for e in all_effects if e.get("category") == cat]
            if not cat_effs: continue
            hdr = menu.addAction(f"  {cat.upper()}")
            hdr.setEnabled(False)
            eff_actions = []
            for eff in cat_effs:
                name = eff.get("name", "")
                act = menu.addAction(f"  {name}")
                act.setCheckable(True)
                act.setChecked(_is_checked(eff))
                act.triggered.connect(lambda checked=False, e=dict(eff): _select(e))
                eff_actions.append((act, name))
            cat_groups.append((hdr, eff_actions))

        other = [e for e in all_effects if e.get("category", "") not in CATS]
        if other:
            sep_other = menu.addSeparator()
            other_actions = []
            for eff in other:
                name = eff.get("name", "")
                act = menu.addAction(f"  {name}")
                act.setCheckable(True)
                act.setChecked(_is_checked(eff))
                act.triggered.connect(lambda checked=False, e=dict(eff): _select(e))
                other_actions.append((act, name))
            cat_groups.append((sep_other, other_actions))

        def _apply_filter(text):
            q = text.strip().lower()
            act_none.setVisible(not q)
            sep_top.setVisible(not q)
            for hdr_act, eff_acts in cat_groups:
                any_vis = False
                for act, name in eff_acts:
                    v = not q or q in name.lower()
                    act.setVisible(v)
                    if v: any_vis = True
                hdr_act.setVisible(any_vis)
        search_input.textChanged.connect(_apply_filter)
        QTimer.singleShot(0, search_input.setFocus)

        # ── Mode de déclenchement ─────────────────────────────────────────────
        menu.addSeparator()
        trig_menu = menu.addMenu("  ⏱  Mode de déclenchement")
        trig_menu.setStyleSheet(menu.styleSheet())

        def _set_trig(mode):
            nonlocal trigger_mode
            trigger_mode = mode
            if self.fx_pads[fx_col][row]:
                self.fx_pads[fx_col][row]["trigger_mode"] = mode

        act_tog = trig_menu.addAction("↕  Toggle (appui/relâche)")
        act_tog.setCheckable(True); act_tog.setChecked(trigger_mode == "toggle")
        act_tog.triggered.connect(lambda: _set_trig("toggle"))
        act_fla = trig_menu.addAction("⚡  Flash (maintenir enfoncé)")
        act_fla.setCheckable(True); act_fla.setChecked(trigger_mode == "flash")
        act_fla.triggered.connect(lambda: _set_trig("flash"))
        act_tim = trig_menu.addAction("⏳  Timer (durée automatique)")
        act_tim.setCheckable(True); act_tim.setChecked(trigger_mode == "timer")
        act_tim.triggered.connect(lambda: _set_trig("timer"))

        trig_menu.addSeparator()
        dur_widget = QWidget()
        dur_layout = QHBoxLayout(dur_widget)
        dur_layout.setContentsMargins(16, 4, 16, 4); dur_layout.setSpacing(6)
        dur_lbl = QLabel("Durée :")
        dur_lbl.setStyleSheet("color:#aaa; font-size:11px; background:transparent;")
        dur_spin = QDoubleSpinBox()
        dur_spin.setRange(0.1, 60.0); dur_spin.setSingleStep(0.5)
        dur_spin.setValue(trigger_duration / 1000.0); dur_spin.setSuffix(" s")
        dur_spin.setFixedWidth(80)
        dur_spin.setStyleSheet(
            "QDoubleSpinBox { background:#222; color:#fff; border:1px solid #444;"
            " border-radius:3px; padding:2px 4px; font-size:11px; }"
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width:16px; background:#333; border:none; }"
        )
        def _set_dur(v):
            nonlocal trigger_duration
            trigger_duration = int(v * 1000)
            if self.fx_pads[fx_col][row]:
                self.fx_pads[fx_col][row]["trigger_duration"] = trigger_duration
        dur_spin.valueChanged.connect(_set_dur)
        dur_layout.addWidget(dur_lbl); dur_layout.addWidget(dur_spin); dur_layout.addStretch()
        dur_wa = QWidgetAction(trig_menu)
        dur_wa.setDefaultWidget(dur_widget)
        trig_menu.addAction(dur_wa)

        menu.addSeparator()
        act_editor = menu.addAction("🎨  Éditeur d'effets")
        act_editor.triggered.connect(lambda: self._open_effect_editor_for_fx_pad(fx_col, row))

        menu.exec(btn.mapToGlobal(pos))

    def start_effect(self, effect_name):
        """Demarre l'effet selectionne par nom"""
        self.effect_state = 0
        self.effect_saved_colors = {}

        for p in self.projectors:
            self.effect_saved_colors[id(p)] = (p.base_color, p.color, p.level,
                                               getattr(p, 'pan', 32768), getattr(p, 'tilt', 32768))

        if not hasattr(self, 'effect_timer'):
            self.effect_timer = QTimer()
            self.effect_timer.timeout.connect(self.update_effect)

        if effect_name == "Bascule":
            self._bascule()
            return  # one-shot, pas de timer

        # Si un config éditeur est actif, initialiser selon son type
        cfg = self.active_effect_config
        etype = cfg.get("type", effect_name) if cfg else effect_name
        speed_raw = cfg.get("speed", 50) if cfg else 50
        sf = max(0.05, 1.0 - speed_raw / 100.0 * 0.95)

        if cfg and cfg.get("layers"):
            import time as _time
            self.effect_t0 = _time.monotonic()
            self.effect_timer.start(40)  # 25 fps pour les effets à couches
            return

        if cfg:
            init_intervals = {
                "Strobe": max(25, int(500 - speed_raw / 100.0 * 475)),
                "Flash":  max(25, int(500 - speed_raw / 100.0 * 475)),
                "Pulse": 30, "Wave": int(50 * sf),
                "Chase": max(40, int(400 * sf)), "Comete": max(30, int(300 * sf)),
                "Etoile Filante": max(25, int(70 * sf)),
                "Rainbow": 50, "Fire": int(60 * sf),
            }
            self.effect_timer.start(init_intervals.get(etype, 80))
        else:
            intervals = {
                "Strobe": 100, "Flash": 100, "Pulse": 30,
                "Wave": 50, "Comete": 80, "Rainbow": 50,
                "Etoile Filante": 60, "Fire": 60, "Chase": 200,
            }
            self.effect_timer.start(intervals.get(effect_name, 100))

        if etype in ("Rainbow", "Wave"):
            self.effect_hue = 0
        if etype == "Pulse":
            self.effect_brightness = 0
            self.effect_direction = 1

    def _stop_once_effect(self):
        """Arrête un effet lancé en mode 'une fois' et désactive le bouton correspondant."""
        self.stop_effect()
        # Désactiver le bouton AKAI actif
        for i, btn in enumerate(self.effect_buttons):
            if btn.active:
                btn.active = False
                btn.update_style()
                if MIDI_AVAILABLE and self.midi_handler.midi_out and i < 8:
                    self.midi_handler.set_pad_led(i, 8, 0)
        self.active_effect = None
        self.active_effect_config = {}

    def stop_effect(self):
        """Arrete l'effet en cours"""
        if hasattr(self, 'effect_timer'):
            self.effect_timer.stop()

        for p in self.projectors:
            p.dmx_mode = "Manuel"

        for p in self.projectors:
            if id(p) in self.effect_saved_colors:
                saved = self.effect_saved_colors[id(p)]
                p.base_color, p.color, p.level = saved[0], saved[1], saved[2]
                if len(saved) > 3:
                    p.pan  = saved[3]
                    p.tilt = saved[4]

    def _bascule(self):
        """Effet Bascule : echange les couleurs entre les deux groupes ou alterne un/deux."""
        from collections import Counter

        active = [p for p in self.projectors if p.group != "fumee" and p.level > 0]
        if not active:
            return

        def _bucket(c):
            return (c.red() // 35, c.green() // 35, c.blue() // 35)

        counts = Counter(_bucket(p.base_color) for p in active)

        def _apply(p, col):
            brightness = p.level / 100.0
            p.base_color = QColor(col)
            p.color = QColor(
                int(col.red()   * brightness),
                int(col.green() * brightness),
                int(col.blue()  * brightness),
            )

        if len(counts) >= 2:
            # Bicolore : échanger les deux couleurs dominantes
            top2 = [k for k, _ in counts.most_common(2)]
            group_a = [p for p in active if _bucket(p.base_color) == top2[0]]
            group_b = [p for p in active if _bucket(p.base_color) == top2[1]]
            col_a = QColor(group_a[0].base_color)
            col_b = QColor(group_b[0].base_color)
            for p in group_a:
                _apply(p, col_b)
            for p in group_b:
                _apply(p, col_a)
        else:
            # Monochrome : un projecteur sur deux passe en blanc, puis inversion
            phase = getattr(self, '_bascule_phase', 0) % 2
            white = QColor(255, 255, 255)
            for i, p in enumerate(active):
                if i % 2 == phase:
                    _apply(p, white)
                else:
                    _apply(p, p.base_color)
            self._bascule_phase = phase + 1

    def _apply_fx_amplitude(self):
        """Applique l'amplitude globale (fader 9) × amplitude colonne FX sur les couleurs."""
        global_amp = self.effect_amplitude / 100.0

        # Amplitude de la colonne FX active (si un pad FX déclenche l'effet)
        col_amp = 1.0
        if self.active_fx_pads:
            fx_col = next(iter(self.active_fx_pads))[0]
            col_amp = self.fx_amplitudes[fx_col] / 100.0 if 0 <= fx_col < _FX_COL_MAX else 1.0

        amp = global_amp * col_amp
        if amp >= 1.0:
            return
        for p in self.projectors:
            p.color = QColor(
                int(p.color.red()   * amp),
                int(p.color.green() * amp),
                int(p.color.blue()  * amp),
            )

    def update_effect(self):
        """Met a jour l'effet en cours"""
        # Si amplitude totale = 0, ne pas toucher aux projecteurs pour laisser
        # les colonnes MEM (ou autres sources) agir librement.
        global_amp = self.effect_amplitude / 100.0
        col_amp = 1.0
        if self.active_fx_pads:
            fx_col = next(iter(self.active_fx_pads))[0]
            col_amp = self.fx_amplitudes[fx_col] / 100.0 if 0 <= fx_col < _FX_COL_MAX else 1.0
        if global_amp * col_amp == 0:
            return

        # ── Mode superposition : applique chaque effet empilé en séquence ──
        if self.effect_superposition and self._stacked_effects:
            for eff_data in self._stacked_effects:
                self._apply_one_stacked_effect(eff_data)
            self._apply_fx_amplitude()
            return

        if self.active_effect is None:
            return

        # Config-driven path (depuis l'éditeur d'effets)
        cfg = self.active_effect_config
        if cfg:
            if cfg.get("layers"):
                self._update_effect_from_layers(cfg)
            else:
                self._update_effect_from_config(cfg)
            self._apply_fx_amplitude()
            return

        self._run_named_effect()
        self._apply_fx_amplitude()

    def _run_named_effect(self):
        """Applique un tick de l'effet nommé (lit/écrit les variables d'instance)."""
        # speed_factor : fader 0 = lent (1.0), fader 100 = rapide (0.05)
        speed_factor = max(0.05, 1.0 - (self.effect_speed / 100.0 * 0.95))

        eff = self.active_effect

        if eff == "Strobe":
            # Alternance blanc/noir — intervalle 500 ms (lent) → 25 ms (rapide)
            interval = max(25, int(500 - (self.effect_speed / 100.0) * 475))
            self.effect_timer.setInterval(interval)
            for p in self.projectors:
                if p.group == "fumee":
                    continue
                if p.level > 0:
                    p.color = QColor(255, 255, 255) if self.effect_state % 2 == 0 else QColor("black")
            self.effect_state += 1

        elif eff == "Flash":
            # Alternance couleur/noir — même mapping vitesse que Strobe
            interval = max(25, int(500 - (self.effect_speed / 100.0) * 475))
            self.effect_timer.setInterval(interval)
            for p in self.projectors:
                if p.group == "fumee":
                    continue
                if p.level > 0:
                    if self.effect_state % 2 == 0:
                        brightness = p.level / 100.0
                        p.color = QColor(
                            int(p.base_color.red() * brightness),
                            int(p.base_color.green() * brightness),
                            int(p.base_color.blue() * brightness)
                        )
                    else:
                        p.color = QColor("black")
            self.effect_state += 1

        elif eff == "Pulse":
            # Respiration douce (fade in/out)
            for p in self.projectors:
                if p.group == "fumee":
                    continue
                if p.level > 0:
                    brightness = (p.level / 127.0) * (self.effect_brightness / 100.0)
                    p.color = QColor(
                        int(p.base_color.red() * brightness),
                        int(p.base_color.green() * brightness),
                        int(p.base_color.blue() * brightness)
                    )
            speed = 2 + int(self.effect_speed / 20)
            self.effect_brightness += self.effect_direction * speed
            if self.effect_brightness >= 100:
                self.effect_brightness = 100
                self.effect_direction = -1
            elif self.effect_brightness <= 0:
                self.effect_brightness = 0
                self.effect_direction = 1

        elif eff == "Wave":
            # Vague de couleur qui se deplace d'un projo a l'autre
            self.effect_timer.setInterval(int(50 * speed_factor))
            for i, p in enumerate(self.projectors):
                if p.group == "fumee":
                    continue
                if p.level > 0:
                    phase = (self.effect_state + i * 15) % 100
                    brightness = (p.level / 100.0) * (abs(50 - phase) / 50.0)
                    p.color = QColor(
                        int(p.base_color.red() * brightness),
                        int(p.base_color.green() * brightness),
                        int(p.base_color.blue() * brightness)
                    )
            self.effect_state += 3 + int(self.effect_speed / 25)

        elif eff == "Comete":
            # Comète : tête blanche vive + traînée qui fondue vers la couleur de base
            self.effect_timer.setInterval(max(30, int(300 * speed_factor)))
            active = [p for p in self.projectors if p.group != "fumee" and p.level > 0]
            n = len(active)
            if n == 0:
                return
            TAIL = 4
            pos = self.effect_state % (n + TAIL)
            for i, p in enumerate(active):
                dist = pos - i
                brightness = p.level / 100.0
                if dist == 0:
                    p.color = QColor(255, 255, 255)
                elif 1 <= dist <= TAIL:
                    blend = (1.0 - dist / (TAIL + 1)) * 0.9
                    base_r = int(p.base_color.red()   * brightness)
                    base_g = int(p.base_color.green() * brightness)
                    base_b = int(p.base_color.blue()  * brightness)
                    p.color = QColor(
                        min(255, int(base_r + (255 - base_r) * blend)),
                        min(255, int(base_g + (255 - base_g) * blend)),
                        min(255, int(base_b + (255 - base_b) * blend)),
                    )
                else:
                    p.color = QColor(
                        int(p.base_color.red()   * brightness),
                        int(p.base_color.green() * brightness),
                        int(p.base_color.blue()  * brightness),
                    )
            self.effect_state += 1

        elif eff == "Rainbow":
            # Rotation arc-en-ciel sur tous les projos
            for i, p in enumerate(self.projectors):
                if p.group == "fumee":
                    continue
                if p.level > 0:
                    hue = (self.effect_hue + i * 30) % 360
                    color = QColor.fromHsv(hue, 255, 255)
                    brightness = p.level / 100.0
                    p.color = QColor(
                        int(color.red() * brightness),
                        int(color.green() * brightness),
                        int(color.blue() * brightness)
                    )
            self.effect_hue += int(5 * (1 + self.effect_speed / 30))

        elif eff == "Etoile Filante":
            # Etoile filante : passage sinusoïdal au blanc avec traînée
            import math
            self.effect_timer.setInterval(max(25, int(70 * speed_factor)))
            active = [p for p in self.projectors if p.group != "fumee" and p.level > 0]
            n = len(active)
            if n == 0:
                return
            TAIL = 6
            total = n + TAIL + 4   # pause noire en fin de cycle
            pos = self.effect_state % total
            for i, p in enumerate(active):
                dist = pos - i
                brightness = p.level / 100.0
                if dist == 0:
                    # Tête : blanc pur
                    p.color = QColor(255, 255, 255)
                elif 1 <= dist <= TAIL:
                    # Traînée sinusoïdale
                    t = dist / TAIL
                    white_blend = (math.sin((1.0 - t) * math.pi / 2)) ** 1.5
                    base_r = int(p.base_color.red()   * brightness)
                    base_g = int(p.base_color.green() * brightness)
                    base_b = int(p.base_color.blue()  * brightness)
                    p.color = QColor(
                        min(255, int(base_r + (255 - base_r) * white_blend)),
                        min(255, int(base_g + (255 - base_g) * white_blend)),
                        min(255, int(base_b + (255 - base_b) * white_blend)),
                    )
                else:
                    p.color = QColor(
                        int(p.base_color.red()   * brightness),
                        int(p.base_color.green() * brightness),
                        int(p.base_color.blue()  * brightness),
                    )
            self.effect_state += 1

        elif eff == "Chase":
            # Passage au blanc : chaque projecteur passe au blanc un par un
            self.effect_timer.setInterval(max(40, int(400 * speed_factor)))
            active = [p for p in self.projectors if p.group != "fumee" and p.level > 0]
            n = len(active)
            if n == 0:
                return
            current = self.effect_state % n
            for i, p in enumerate(active):
                brightness = p.level / 100.0
                if i == current:
                    p.color = QColor(255, 255, 255)
                else:
                    p.color = QColor(
                        int(p.base_color.red()   * brightness),
                        int(p.base_color.green() * brightness),
                        int(p.base_color.blue()  * brightness),
                    )
            self.effect_state += 1

        elif eff == "Fire":
            # Effet feu (rouge/orange/jaune aleatoire)
            self.effect_timer.setInterval(int(60 * speed_factor))
            fire_colors = [
                QColor(255, 50, 0), QColor(255, 100, 0), QColor(255, 150, 0),
                QColor(255, 200, 0), QColor(200, 30, 0), QColor(255, 80, 0),
            ]
            for p in self.projectors:
                if p.group == "fumee":
                    continue
                if p.level > 0:
                    base = random.choice(fire_colors)
                    brightness = p.level / 100.0
                    p.color = QColor(
                        int(base.red() * brightness),
                        int(base.green() * brightness),
                        int(base.blue() * brightness)
                    )
        # (l'amplitude FX est appliquée par l'appelant)

    def _apply_one_stacked_effect(self, eff_data):
        """Applique un tick d'un effet empilé (mode superposition).
        Sauvegarde/restaure les variables d'instance autour de l'appel."""
        # ── Sauvegarder l'état actuel ─────────────────────────────────────
        saved_eff  = self.active_effect
        saved_cfg  = self.active_effect_config
        saved_st   = self.effect_state
        saved_hue  = getattr(self, 'effect_hue', 0)
        saved_bri  = getattr(self, 'effect_brightness', 0)
        saved_dir  = getattr(self, 'effect_direction', 1)
        saved_t0   = getattr(self, 'effect_t0', 0)

        # ── Charger l'état de cet effet ──────────────────────────────────
        self.active_effect        = eff_data['name']
        self.active_effect_config = eff_data.get('config', {})
        self.effect_state         = eff_data.get('state', 0)
        self.effect_hue           = eff_data.get('hue', 0)
        self.effect_brightness    = eff_data.get('brightness', 0)
        self.effect_direction     = eff_data.get('direction', 1)
        self.effect_t0            = eff_data.get('t0', 0)

        # ── Exécuter un tick ─────────────────────────────────────────────
        cfg = self.active_effect_config
        if cfg:
            if cfg.get("layers"):
                self._update_effect_from_layers(cfg)
            else:
                self._update_effect_from_config(cfg)
        else:
            self._run_named_effect()

        # ── Sauvegarder le nouvel état dans le dict ───────────────────────
        eff_data['state']     = self.effect_state
        eff_data['hue']       = self.effect_hue
        eff_data['brightness']= self.effect_brightness
        eff_data['direction'] = self.effect_direction
        eff_data['t0']        = self.effect_t0

        # ── Restaurer les variables d'instance ────────────────────────────
        self.active_effect        = saved_eff
        self.active_effect_config = saved_cfg
        self.effect_state         = saved_st
        self.effect_hue           = saved_hue
        self.effect_brightness    = saved_bri
        self.effect_direction     = saved_dir
        self.effect_t0            = saved_t0

    # ------------------------------------------------------------------ #
    #  EDITEUR D'EFFETS                                                    #
    # ------------------------------------------------------------------ #

    def open_effect_editor(self):
        """Ouvre l'editeur d'effets (menu Edition)"""
        from effect_editor import EffectEditorDialog
        # Préférer le nom complet dans active_effect_config (ex: "Flash Simple")
        # plutôt que active_effect qui peut être un type legacy (ex: "Flash")
        cfg = getattr(self, 'active_effect_config', {}) or {}
        active_name = cfg.get('name') or getattr(self, 'active_effect', None)
        dlg = EffectEditorDialog(clips=[], main_window=self, parent=self, initial_effect=active_name)
        dlg.exec()

    def _open_effect_editor_for_btn(self, btn_idx: int):
        """Ouvre l'éditeur d'effets pré-sélectionné sur l'effet du bouton btn_idx."""
        from effect_editor import EffectEditorDialog
        cfg = self._button_effect_configs.get(btn_idx, {})
        initial_name = cfg.get('name')
        if not initial_name and btn_idx < len(self.effect_buttons):
            initial_name = self.effect_buttons[btn_idx].current_effect
        dlg = EffectEditorDialog(clips=[], main_window=self, parent=self, initial_effect=initial_name)
        dlg.exec()

    _EFFECT_ASSIGNMENTS_FILE = Path.home() / ".mystrow_effect_assignments.json"
    _EFFECT_LIBRARY_FILE     = Path.home() / ".mystrow_effect_library.json"

    def _load_effect_library(self) -> dict:
        """Charge les configs d'effets non assignés (édités mais pas sur un bouton)."""
        try:
            if self._EFFECT_LIBRARY_FILE.exists():
                return json.loads(self._EFFECT_LIBRARY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_effect_library(self):
        """Sauvegarde les configs d'effets non assignés."""
        try:
            self._EFFECT_LIBRARY_FILE.write_text(
                json.dumps(self._effect_library_configs, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass
        self._refresh_active_effect_config()

    def _load_effect_assignments(self) -> dict:
        """Charge les assignations bouton→effet depuis le disque."""
        try:
            if self._EFFECT_ASSIGNMENTS_FILE.exists():
                data = json.loads(self._EFFECT_ASSIGNMENTS_FILE.read_text(encoding="utf-8"))
                return {int(k): v for k, v in data.items()}
        except Exception:
            pass
        return {}

    def _save_effect_assignments(self):
        """Sauvegarde les assignations bouton→effet sur le disque."""
        try:
            self._EFFECT_ASSIGNMENTS_FILE.write_text(
                json.dumps({str(k): v for k, v in self._button_effect_configs.items()},
                           indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass
        # Si l'effet actif fait partie des configs mises à jour, relancer immédiatement
        self._refresh_active_effect_config()

    def _refresh_active_effect_config(self):
        """Recharge la config de l'effet actif depuis les sources à jour et le relance."""
        active_name = self.active_effect
        if not active_name:
            return

        # Vérifier qu'un bouton OU un pad FX est vraiment actif — pas juste un effet fantôme
        btn_is_active = any(
            btn.active and btn.current_effect == active_name
            for btn in self.effect_buttons
        )
        fx_is_active = bool(self.active_fx_pads)

        def _find_new_cfg():
            """Cherche la config mise à jour dans : boutons → pads FX → bibliothèque."""
            for cfg in self._button_effect_configs.values():
                if isinstance(cfg, dict) and cfg.get("name") == active_name:
                    return cfg
            for col in self.fx_pads:
                for cfg in col:
                    if isinstance(cfg, dict) and cfg.get("name") == active_name:
                        return cfg
            return self._effect_library_configs.get(active_name)

        if not btn_is_active and not fx_is_active:
            # Juste mettre à jour la config en mémoire, sans relancer
            new_cfg = _find_new_cfg()
            if new_cfg:
                self.active_effect_config = new_cfg
            return

        # Chercher la nouvelle config et relancer l'effet
        new_cfg = _find_new_cfg()
        if new_cfg:
            self.active_effect_config = new_cfg
            self.start_effect(active_name)
            # Mettre à jour _prev_effect_state si il référence le même effet
            prev = getattr(self, '_prev_effect_state', None)
            if prev and prev.get("effect") == active_name:
                prev["config"] = new_cfg

    def _on_effect_assigned(self, btn_idx: int, cfg: dict):
        """Reçoit l'assignation depuis l'éditeur ou le menu clic-droit et met à jour le bouton"""
        if cfg:
            self._button_effect_configs[btn_idx] = cfg
        else:
            self._button_effect_configs.pop(btn_idx, None)
        self._save_effect_assignments()
        if btn_idx < len(self.effect_buttons):
            name = cfg.get("name", "") if cfg else ""
            self.effect_buttons[btn_idx].setToolTip(name or "Aucun effet")
            self.effect_buttons[btn_idx].current_effect = name or None

        # Si cet effet est actuellement actif, appliquer la nouvelle config immédiatement
        if cfg and self.effect_buttons[btn_idx].active:
            self.active_effect_config = cfg
            self.active_effect = cfg.get("name", self.active_effect)
            self.start_effect(self.active_effect)

    def _update_effect_from_layers(self, cfg: dict):
        """Exécute un effet défini par ses couches (format nouvel éditeur)."""
        import math as _math
        import time as _time

        layers_dicts = cfg.get("layers", [])
        if not layers_dicts:
            return

        t = _time.monotonic() - getattr(self, 'effect_t0', 0)

        # Mode "une fois" : stoppe l'effet après la durée configurée
        play_mode = cfg.get("play_mode", "loop")
        if play_mode == "once":
            duration = cfg.get("duration", 0)
            if duration <= 0:
                duration = 2.0  # durée par défaut d'un cycle : 2 secondes
            if t >= duration:
                QTimer.singleShot(0, self._stop_once_effect)
                return
        _LETTER_TO_GROUP = {"A": "face", "B": "lat", "C": "contre",
                            "D": "douche1", "E": "douche2", "F": "douche3"}
        target_letters = cfg.get("target_groups", [])
        allowed_groups = {_LETTER_TO_GROUP[l] for l in target_letters if l in _LETTER_TO_GROUP}
        projectors = [p for p in self.projectors
                      if p.group != "fumee" and (not allowed_groups or p.group in allowed_groups)]
        n = len(projectors)
        if n == 0:
            return

        _LETTER_TO_GROUP = {
            "A": "face", "B": "lat", "C": "contre",
            "D": "douche1", "E": "douche2", "F": "douche3",
        }

        def _wave(forme, x):
            if forme == "Sinus":      return (_math.sin(2 * _math.pi * x) + 1) / 2
            elif forme == "Flash":    return 1.0 if x < 0.5 else 0.0
            elif forme == "Triangle": return 1.0 - abs(2 * x - 1)
            elif forme == "Montée":   return x
            elif forme == "Descente": return 1.0 - x
            elif forme == "Fixe":     return 1.0
            return 0.0

        # En mode rec lumière, l'effet ne s'applique qu'aux projecteurs allumés par les clips
        _timeline_mode = hasattr(getattr(self, 'seq', None), 'timeline_playback_row')

        for i, proj in enumerate(projectors):
            _base_level = proj.level   # niveau posé par les clips, avant l'effet
            dim = 0.0; r = 0.0; g = 0.0; b = 0.0
            has_dim = False; has_rgb_layer = False
            _explicitly_targeted = False  # ciblage explicite par groupe/pair/impair

            for ld in layers_dicts:
                preset = ld.get("target_preset", "Tous")
                groups = ld.get("target_groups", [])
                if preset == "Pair"   and i % 2 != 0: continue
                if preset == "Impair" and i % 2 != 1: continue
                if preset in _LETTER_TO_GROUP and getattr(proj, 'group', '') != _LETTER_TO_GROUP[preset]: continue
                if groups and getattr(proj, 'group', '') not in [_LETTER_TO_GROUP.get(g, g) for g in groups]: continue
                # Ciblage explicite → l'effet peut allumer ce projo même s'il est éteint
                if preset != "Tous" or groups:
                    _explicitly_targeted = True

                speed     = ld.get("speed", 50)
                size      = ld.get("size", 100)
                spread    = ld.get("spread", 0)
                phase     = ld.get("phase", 0) / 100.0
                fade      = ld.get("fade", 0) / 100.0
                direction = ld.get("direction", 1)
                forme     = ld.get("forme", "Sinus")
                attr      = ld.get("attribute", "Dimmer")

                effective_speed = cfg.get("speed_override", self.effect_speed)
                fader_mult = max(0.05, effective_speed / 100.0)
                freq = (0.3 + speed / 100.0 * 3.5) * fader_mult
                sp   = spread / 100.0
                if direction == 0:
                    t_osc = abs(2 * ((freq * t) % 1.0) - 1)
                    x = (t_osc + i / max(n, 1) * sp + phase) % 1.0
                elif direction == -1:
                    x = (freq * t - i / max(n, 1) * sp + phase) % 1.0
                else:
                    x = (freq * t + i / max(n, 1) * sp + phase) % 1.0

                if forme == "Audio":
                    import random as _rand
                    raw = _rand.random()
                else:
                    raw = _wave(forme, x)
                if fade > 0:
                    sin_val = (_math.sin(2 * _math.pi * x) + 1) / 2
                    raw = raw * (1 - fade) + sin_val * fade
                scaled = raw * size / 100.0

                if attr in ("Dimmer", "Strobe"):
                    dim += scaled; has_dim = True
                elif attr == "R": r += scaled; has_rgb_layer = True
                elif attr == "V": g += scaled; has_rgb_layer = True
                elif attr == "B": b += scaled; has_rgb_layer = True
                elif attr == "RGB":
                    has_rgb_layer = True
                    c1 = QColor(ld.get("color1", "#ffffff"))
                    r += c1.redF() * scaled
                    g += c1.greenF() * scaled
                    b += c1.blueF() * scaled
                elif attr == "Permut":
                    has_rgb_layer = True
                    c1 = QColor(ld.get("color1", "#ff0000"))
                    c2 = QColor(ld.get("color2", "#0000ff"))
                    r2 = 1.0 - raw
                    amp = size / 100.0
                    r += (c1.redF()   * raw + c2.redF()   * r2) * amp
                    g += (c1.greenF() * raw + c2.greenF() * r2) * amp
                    b += (c1.blueF()  * raw + c2.blueF()  * r2) * amp
                elif attr in ("Pan", "Tilt"):
                    saved = self.effect_saved_colors.get(id(proj))
                    if attr == "Pan":
                        center = saved[3] if saved and len(saved) > 3 else getattr(proj, 'pan', 32768)
                        amplitude = (size / 100.0) * 32768
                        proj.pan = int(max(0, min(65535, center + (scaled - 0.5) * 2 * amplitude)))
                    else:
                        center = saved[4] if saved and len(saved) > 4 else getattr(proj, 'tilt', 32768)
                        amplitude = (size / 100.0) * 32768
                        proj.tilt = int(max(0, min(65535, center + (scaled - 0.5) * 2 * amplitude)))

                elif attr == "Pan/Tilt":
                    # Forme de trajectoire couplée Pan+Tilt
                    try:
                        from effect_editor import PAN_TILT_SHAPES
                    except ImportError:
                        PAN_TILT_SHAPES = {}
                    shape_id  = ld.get("mouvement_shape", "libre")
                    shape_def = PAN_TILT_SHAPES.get(shape_id, PAN_TILT_SHAPES.get("libre", {}))
                    pan_cfg   = shape_def.get("pan",  ("Sinus",    0, 1.0))
                    tilt_cfg  = shape_def.get("tilt", ("Sinus",   25, 1.0))
                    pan_forme,  pan_phase_pct,  pan_mult  = pan_cfg
                    tilt_forme, tilt_phase_pct, tilt_mult = tilt_cfg
                    amplitude = (size / 100.0) * 128
                    saved = self.effect_saved_colors.get(id(proj))

                    # Pan
                    if pan_forme and pan_forme != "Fixe":
                        pan_freq = (0.3 + speed * pan_mult / 100.0 * 3.5) * fader_mult
                        pan_x = (pan_freq * t + i / max(n, 1) * sp + phase + pan_phase_pct / 100.0) % 1.0
                        pan_raw = _wave(pan_forme, pan_x)
                        c_pan = saved[3] if saved and len(saved) > 3 else getattr(proj, 'pan', 32768)
                        proj.pan = int(max(0, min(65535, c_pan + (pan_raw - 0.5) * 2 * amplitude)))

                    # Tilt
                    if tilt_forme and tilt_forme != "Fixe":
                        tilt_freq = (0.3 + speed * tilt_mult / 100.0 * 3.5) * fader_mult
                        tilt_x = (tilt_freq * t + i / max(n, 1) * sp + phase + tilt_phase_pct / 100.0) % 1.0
                        tilt_raw = _wave(tilt_forme, tilt_x)
                        c_tilt = saved[4] if saved and len(saved) > 4 else getattr(proj, 'tilt', 32768)
                        proj.tilt = int(max(0, min(65535, c_tilt + (tilt_raw - 0.5) * 2 * amplitude)))

                elif attr == "Zoom":
                    proj.zoom = int(max(0, min(255, scaled * 255)))
                elif attr == "Gobo":
                    n_gobos = 8
                    proj.gobo = int(scaled * (n_gobos - 1)) * 32

            # En mode rec lumière, ignorer les projos éteints sauf ciblage explicite
            if _timeline_mode and _base_level == 0 and not _explicitly_targeted:
                continue

            level = min(1.0, dim) if has_dim else 1.0
            # L'effet contrôle la luminosité indépendamment du fader :
            # on force proj.level=100 et on encode toute la brillance dans proj.color
            bv = level

            has_color_val = r > 0 or g > 0 or b > 0
            if has_dim or has_color_val or has_rgb_layer:
                proj.level = 100  # ouvre le dimmer DMX pour laisser passer l'effet
            if has_color_val:
                cr = min(255, int(r * 255))
                cg = min(255, int(g * 255))
                cb = min(255, int(b * 255))
                proj.color = QColor(int(cr * bv), int(cg * bv), int(cb * bv))
            elif has_rgb_layer:
                proj.color = QColor(0, 0, 0)
            elif has_dim:
                # Pas de couche couleur : flash blanc (identique au preview de l'éditeur)
                proj.color = QColor(int(255 * bv), int(255 * bv), int(255 * bv))

    def _update_effect_from_config(self, cfg: dict):
        """Exécute l'algorithme paramétré depuis une config éditeur."""
        import math as _math

        etype      = cfg.get("type", "Pulse")
        # Fader FX : contrôle direct de la vitesse (0=lent, 100=rapide)
        fader = self.effect_speed  # 0-100
        # sf : 0 = lent (sf=1.0) → 100 = rapide (sf=0.05), identique à update_effect
        sf_fader = max(0.05, 1.0 - (fader / 100.0) * 0.95)
        speed_raw  = cfg.get("speed", 50)
        target     = cfg.get("target", "all")
        color_mode = cfg.get("color_mode", "base")
        custom_hex = cfg.get("custom_color", "#ffffff")

        sf = sf_fader  # vitesse contrôlée par le fader FX

        def resolve(p, idx):
            if color_mode == "white":  return QColor(255, 255, 255)
            if color_mode == "black":  return QColor(0, 0, 0)
            if color_mode == "custom": return QColor(custom_hex)
            if color_mode == "fire":
                return random.choice([QColor(255,50,0), QColor(255,100,0),
                                      QColor(255,150,0), QColor(255,200,0)])
            if color_mode == "rainbow":
                return QColor.fromHsv((getattr(self,"effect_hue",0) + idx*30)%360, 255, 255)
            return p.base_color  # "base"

        base_all = [p for p in self.projectors if p.group != "fumee" and p.level > 0]
        if target == "even":
            active = [p for i, p in enumerate(base_all) if i % 2 == 0]
        elif target == "odd":
            active = [p for i, p in enumerate(base_all) if i % 2 == 1]
        elif target == "rl":
            active = list(reversed(base_all))
        else:
            active = base_all

        black = QColor(0, 0, 0)

        if etype in ("Strobe", "Flash"):
            interval = max(25, int(500 - (fader / 100.0) * 475))
            self.effect_timer.setInterval(interval)
            if target == "alternate":
                phase = self.effect_state % 2
                for i, p in enumerate(base_all):
                    c = resolve(p, i)
                    bv = p.level / 100.0
                    if i % 2 == phase:
                        p.color = QColor(int(c.red()*bv), int(c.green()*bv), int(c.blue()*bv))
                    else:
                        p.color = black
            else:
                on = self.effect_state % 2 == 0
                for i, p in enumerate(active):
                    c = resolve(p, i)
                    bv = p.level / 100.0
                    p.color = QColor(int(c.red()*bv), int(c.green()*bv), int(c.blue()*bv)) if on else black
            self.effect_state += 1

        elif etype == "Pulse":
            for i, p in enumerate(active):
                if target == "alternate":
                    b = (self.effect_brightness if i % 2 == 0 else 100 - self.effect_brightness) / 100.0
                else:
                    b = self.effect_brightness / 100.0
                c = resolve(p, i)
                bv = (p.level / 100.0) * b
                p.color = QColor(int(c.red()*bv), int(c.green()*bv), int(c.blue()*bv))
            step = 2 + int(fader / 20)
            self.effect_brightness += self.effect_direction * step
            if self.effect_brightness >= 100: self.effect_brightness, self.effect_direction = 100, -1
            if self.effect_brightness <= 0:   self.effect_brightness, self.effect_direction = 0, 1

        elif etype == "Wave":
            self.effect_timer.setInterval(int(50 * sf))
            for i, p in enumerate(active):
                phase = (self.effect_state + i * 15) % 100
                b = (p.level / 100.0) * (abs(50 - phase) / 50.0)
                c = resolve(p, i)
                p.color = QColor(int(c.red()*b), int(c.green()*b), int(c.blue()*b))
            self.effect_state += 3 + int(fader / 25)

        elif etype == "Chase":
            self.effect_timer.setInterval(max(40, int(400 * sf)))
            n = len(active)
            if n == 0: return
            pos = self.effect_state % n
            for i, p in enumerate(active):
                bv = p.level / 100.0
                c = resolve(p, i)
                if i == pos:
                    p.color = QColor(int(c.red()*bv), int(c.green()*bv), int(c.blue()*bv))
                else:
                    base_c = p.base_color
                    p.color = QColor(int(base_c.red()*bv), int(base_c.green()*bv), int(base_c.blue()*bv))
            self.effect_state += 1

        elif etype == "Comete":
            self.effect_timer.setInterval(max(30, int(300 * sf)))
            n = len(active)
            if n == 0: return
            TAIL = 4
            pos = self.effect_state % (n + TAIL)
            for i, p in enumerate(active):
                dist, bv = pos - i, p.level / 100.0
                c = resolve(p, i)
                if dist == 0:
                    p.color = QColor(255, 255, 255)
                elif 1 <= dist <= TAIL:
                    blend = (1.0 - dist / (TAIL+1)) * 0.9
                    p.color = QColor(
                        min(255, int(c.red()*bv   + (255-c.red()*bv)  *blend)),
                        min(255, int(c.green()*bv + (255-c.green()*bv)*blend)),
                        min(255, int(c.blue()*bv  + (255-c.blue()*bv) *blend)),
                    )
                else:
                    p.color = QColor(int(c.red()*bv), int(c.green()*bv), int(c.blue()*bv))
            self.effect_state += 1

        elif etype == "Etoile Filante":
            self.effect_timer.setInterval(max(25, int(70 * sf)))
            n = len(active)
            if n == 0: return
            TAIL, total = 6, n + 10
            pos = self.effect_state % total
            for i, p in enumerate(active):
                dist, bv = pos - i, p.level / 100.0
                c = resolve(p, i)
                if dist == 0:
                    p.color = QColor(255, 255, 255)
                elif 1 <= dist <= TAIL:
                    t = dist / TAIL
                    blend = (_math.sin((1.0 - t) * _math.pi / 2)) ** 1.5
                    p.color = QColor(
                        min(255, int(c.red()*bv   + (255-c.red()*bv)  *blend)),
                        min(255, int(c.green()*bv + (255-c.green()*bv)*blend)),
                        min(255, int(c.blue()*bv  + (255-c.blue()*bv) *blend)),
                    )
                else:
                    p.color = QColor(int(c.red()*bv), int(c.green()*bv), int(c.blue()*bv))
            self.effect_state += 1

        elif etype == "Rainbow":
            for i, p in enumerate(active):
                hue = (self.effect_hue + i * 30) % 360
                col = QColor.fromHsv(hue, 255, 255)
                bv = p.level / 100.0
                p.color = QColor(int(col.red()*bv), int(col.green()*bv), int(col.blue()*bv))
            self.effect_hue = (getattr(self,"effect_hue",0) + int(5*(1+speed_raw/30))) % 360

        elif etype == "Fire":
            self.effect_timer.setInterval(int(60 * sf))
            fire_colors = [QColor(255,50,0), QColor(255,100,0),
                           QColor(255,150,0), QColor(255,200,0)]
            for p in active:
                base = random.choice(fire_colors)
                bv = p.level / 100.0
                p.color = QColor(int(base.red()*bv), int(base.green()*bv), int(base.blue()*bv))

        elif etype == "Bascule":
            self._bascule()
            self.active_effect_config = {}  # one-shot

    def _fader8_dispatch(self, index, value):
        """Fader 9 : contrôle de la vitesse des effets."""
        self.effect_speed = value

    def set_effect_speed(self, index, value):
        """Definit la vitesse de l'effet (conservé pour compatibilité)"""
        self.effect_speed = value

    def _update_tap_go_btn_style(self):
        """Met à jour l'apparence du bouton TAP/GO selon le mode actif."""
        btn = getattr(self, '_tap_btn', None)
        if btn is None:
            return
        if self.go_mode:
            btn.setText("▶")
            btn.setFont(QFont("Segoe UI", 7, QFont.Bold))
            btn.setToolTip("GO — avance à la mémoire suivante")
            btn.setStyleSheet("""
                QToolButton {
                    background: #006633;
                    border: 2px solid #00aa55;
                    border-radius: 8px;
                    color: #00ff88;
                    font-size: 8px;
                    font-weight: bold;
                }
                QToolButton:hover {
                    background: #008844;
                    border: 2px solid #00ff88;
                }
                QToolButton:pressed {
                    background: #004422;
                    border: 2px solid #00ff88;
                }
            """)
        else:
            btn.setText("")
            btn.setToolTip(tr("tooltip_tap_tempo"))
            btn.setStyleSheet("""
                QToolButton {
                    background: #4a4a4a;
                    border: 2px solid #6a6a6a;
                    border-radius: 8px;
                }
                QToolButton:hover {
                    background: #5a5a5a;
                    border: 2px solid #aaa;
                }
                QToolButton:pressed {
                    background: #333;
                    border: 2px solid #fff;
                }
            """)

    def _go_advance(self):
        """Mode GO : avance au cue suivant si multi-cue, sinon à la prochaine mémoire."""
        # Si un pad actif multi-cue → avancer son cue
        for col_akai, row in self.active_memory_pads.items():
            mem_col = self._fader_to_mem_col(col_akai)
            mem = self.memories[mem_col][row] if mem_col is not None else None
            if mem:
                self._mem_ensure_cues(mem)
                if len(mem.get("cues", [])) > 1:
                    self._mem_advance_cue(mem_col, row)
                    fader_val = self.faders[col_akai].value if col_akai in self.faders else 0
                    self._apply_memory_to_projectors(mem_col, row, fader_value=fader_val)
                    cue_idx = self._mem_cue_idx.get((mem_col, row), 0)
                    n = len(mem["cues"])
                    lbl = mem["cues"][cue_idx].get("label", f"Cue {cue_idx+1}")
                    self._log_message(f"▶  {lbl}  ({cue_idx+1}/{n})", "mem")
                    self._style_memory_pad(mem_col, row, active=True)
                    return
        if self._go_col == -1:
            next_col, next_row = 0, 0
        else:
            next_row = self._go_row + 1
            next_col = self._go_col
            if next_row > 7:
                next_row = 0
                next_col = self._go_col + 1
            if next_col > 7:
                next_col, next_row = 0, 0

        if self.memories[next_col][next_row] is None:
            msg = tr("go_empty_mem").format(col=next_col + 1, row=next_row + 1)
            self._show_error_toast(msg)
            return

        self.trigger_memory(next_col, next_row)
        self._go_col = next_col
        self._go_row = next_row

        btn = getattr(self, '_tap_btn', None)
        if btn:
            btn.setStyleSheet("""
                QToolButton {
                    background: #00aa55;
                    border: 2px solid #00ff88;
                    border-radius: 8px;
                    color: #fff;
                    font-size: 8px;
                    font-weight: bold;
                }
            """)
            QTimer.singleShot(150, self._update_tap_go_btn_style)

        self._show_mem_toast(f"▶  MEM {next_col + 1}.{next_row + 1}")

    def _go_back(self):
        """Mode GO : recule au cue précédent si multi-cue, sinon à la mémoire précédente."""
        for col_akai, row in self.active_memory_pads.items():
            mem_col = self._fader_to_mem_col(col_akai)
            mem = self.memories[mem_col][row] if mem_col is not None else None
            if mem:
                self._mem_ensure_cues(mem)
                if len(mem.get("cues", [])) > 1:
                    self._mem_go_back_cue(mem_col, row)
                    fader_val = self.faders[col_akai].value if col_akai in self.faders else 0
                    self._apply_memory_to_projectors(mem_col, row, fader_value=fader_val)
                    cue_idx = self._mem_cue_idx.get((mem_col, row), 0)
                    n = len(mem["cues"])
                    lbl = mem["cues"][cue_idx].get("label", f"Cue {cue_idx+1}")
                    self._log_message(f"◀  {lbl}  ({cue_idx+1}/{n})", "mem")
                    self._style_memory_pad(mem_col, row, active=True)
                    return
        if self._go_col == -1:
            # Pas encore démarré → aller à la dernière mémoire disponible
            next_col, next_row = 7, 7
            while next_col >= 0 and self.memories[next_col][next_row] is None:
                next_row -= 1
                if next_row < 0:
                    next_row = 7
                    next_col -= 1
            if next_col < 0:
                return
        else:
            next_row = self._go_row - 1
            next_col = self._go_col
            if next_row < 0:
                next_row = 7
                next_col = self._go_col - 1
            if next_col < 0:
                # Début → retour à la fin
                next_col, next_row = 7, 7

        if self.memories[next_col][next_row] is None:
            msg = tr("go_empty_mem").format(col=next_col + 1, row=next_row + 1)
            self._show_error_toast(msg)
            return

        self.trigger_memory(next_col, next_row)
        self._go_col = next_col
        self._go_row = next_row

        self._show_mem_toast(f"◀  MEM {next_col + 1}.{next_row + 1}")

    def _tap_tempo(self):
        """Calcule le BPM à partir des taps et règle le fader vitesse FX."""
        if self.go_mode:
            self._go_advance()
            return

        now = time.monotonic()
        # Supprimer les taps trop anciens (> 3 secondes sans tap = reset)
        self._tap_times = [t for t in self._tap_times if now - t < 3.0]
        self._tap_times.append(now)

        # Feedback visuel rapide sur le bouton
        if self._tap_btn:
            self._tap_btn.setStyleSheet(
                "QPushButton { background: #555; color: #fff; border: 1px solid #aaa; "
                "border-radius: 3px; font-size: 8px; font-weight: bold; }"
            )
            QTimer.singleShot(120, lambda: self._tap_btn.setStyleSheet(
                "QPushButton { background: #1e1e1e; color: #888; border: 1px solid #3a3a3a; "
                "border-radius: 3px; font-size: 8px; font-weight: bold; } "
                "QPushButton:pressed { background: #333; color: #fff; border-color: #aaa; }"
            ) if self._tap_btn else None)

        # Besoin d'au moins 2 taps pour calculer
        if len(self._tap_times) < 2:
            return

        # Moyenne des intervalles sur les 4 derniers taps maximum
        taps = self._tap_times[-5:]
        intervals = [taps[i+1] - taps[i] for i in range(len(taps) - 1)]
        avg_interval_s = sum(intervals) / len(intervals)
        bpm = 60.0 / avg_interval_s

        # BPM → fader 0-100 (60 BPM = 0, 300 BPM = 100)
        speed = int(max(0, min(100, (bpm - 60) / (300 - 60) * 100)))
        self.effect_speed = speed
        if 8 in self.faders:
            self.faders[8].set_value(speed)

        # Afficher le BPM détecté via un toast éphémère
        self._show_bpm_toast(int(bpm))

    def set_master_level(self, index, value):
        """Définit le niveau master général (0-100) et recompute les couleurs de sortie."""
        self.master_level = value
        factor = value / 100.0
        for p in self.projectors:
            if p.level > 0:
                lvl = p.level / 100.0
                p.color = QColor(
                    int(p.base_color.red()   * lvl * factor),
                    int(p.base_color.green() * lvl * factor),
                    int(p.base_color.blue()  * lvl * factor),
                )
            else:
                p.color = QColor("black")
        self.send_dmx_update()

    def _update_status_corner(self):
        """Rafraîchit le corner widget audio meter à chaque tick DMX (40 ms)."""
        if not hasattr(self, '_status_corner'):
            return
        try:
            import math, random as _rnd
            main_playing = self.player.playbackState()      == QMediaPlayer.PlayingState
            cart_playing = self.cart_player.playbackState() == QMediaPlayer.PlayingState
            playing = main_playing or cart_playing

            if not playing or getattr(self, 'blackout_active', False):
                self._status_corner.set_audio(0.0, False)
                return

            if main_playing:
                position = self.player.position()
                analyzed = self.audio_ai.analyzed and self.player.duration() > 0
            else:
                position = self.cart_player.position()
                analyzed = False

            if analyzed:
                level = float(self.audio_ai.get_energy_at(position))
            else:
                # Simulation punchy : basses + mids + transitoires aléatoires
                t = position / 1000.0
                bass  = 0.45 * abs(math.sin(t * 1.9))
                mid   = 0.25 * abs(math.sin(t * 4.7 + 0.8))
                hi    = 0.15 * abs(math.sin(t * 13.1 + 2.3))
                noise = _rnd.uniform(0.0, 0.15)
                level = min(0.97, bass + mid + hi + noise)

            # Pondéré par le fader master DMX
            level *= self.master_level / 100.0
            self._status_corner.set_audio(level, playing)
        except Exception:
            pass

    def activate_default_white_pads(self):
        """Active les pads blancs au demarrage pour les colonnes groupe - un par colonne"""
        for col, slot in enumerate(self._fader_map):
            if slot["type"] == "group":
                white_pad = self.pads.get((0, col))
                if white_pad:
                    color = white_pad.property("base_color")
                    white_pad.setStyleSheet(f"QPushButton {{ background: {color.name()}; border: 2px solid {color.lighter(130).name()}; border-radius: 4px; }}")
                    self.active_pads[col] = white_pad

        if MIDI_AVAILABLE and hasattr(self, 'midi_handler') and self.midi_handler.midi_out:
            for row in range(8):
                for col in range(8):
                    pad = self.pads.get((row, col))
                    if pad:
                        slot = self._fader_map[col]
                        note = (7 - row) * 8 + col
                        if slot["type"] == "group":
                            base_color = pad.property("base_color")
                            velocity = rgb_to_akai_velocity(base_color)
                            brightness = 100 if row == 0 else 20
                            channel = 0x96 if brightness >= 80 else 0x90
                            self.midi_handler.midi_out.send_message([channel, note, velocity])
                        elif slot.get("type") == "fx":
                            fx_col = slot.get("fx_col", 0)
                            cfg = self.fx_pads[fx_col][row] if 0 <= fx_col < _FX_COL_MAX else None
                            is_active = self.active_fx_pads.get((fx_col, row))
                            if is_active and cfg:
                                self.midi_handler.set_pad_led(row, col, 21, brightness_percent=100)
                            elif cfg:
                                self.midi_handler.set_pad_led(row, col, 21, brightness_percent=20)
                            else:
                                self.midi_handler.set_pad_led(row, col, 0, brightness_percent=0)
                        elif slot.get("type") == "memory":
                            mem_col = slot.get("mem_col", 0)
                            is_active = self.active_memory_pads.get(col) == row
                            self._update_memory_pad_led(mem_col, row, active=is_active)

    def _clear_akai_state(self):
        """Remet l'AKAI à zéro : faders 0-7 à 0 + pads blancs activés."""
        # Faders à 0
        for idx in range(8):
            if idx in self.faders:
                self.faders[idx].value = 0
                self.faders[idx].update()
            self.set_proj_level(idx, 0)

        # MIDI faders à 0
        if MIDI_AVAILABLE and hasattr(self, 'midi_handler') and self.midi_handler.midi_out:
            for idx in range(8):
                self.midi_handler.midi_out.send_message([0xB0, idx, 0])

        # Désactiver les pads actifs sur les colonnes groupe
        for col, pad in list(self.active_pads.items()):
            slot = self._fader_map[col] if col < len(self._fader_map) else None
            if slot and slot["type"] == "group":
                old_color = pad.property("base_color")
                dim_color = QColor(int(old_color.red() * 0.5), int(old_color.green() * 0.5), int(old_color.blue() * 0.5))
                pad.setStyleSheet(f"QPushButton {{ background: {dim_color.name()}; border: 1px solid #2a2a2a; border-radius: 4px; }}")
        self.active_pads.clear()

        # Activer les pads blancs (row 0)
        self.activate_default_white_pads()

        # Couper l'effet en cours s'il y en a un
        if getattr(self, 'active_effect', None) or getattr(self, 'active_effect_config', {}):
            self.stop_effect()
            self.active_effect = None
            self.active_effect_config = {}
            for btn in self.effect_buttons:
                if btn.active:
                    btn.active = False
                    btn.update_style()

        # Désactiver tous les pads FX actifs + mettre à jour visuel et LEDs physiques
        self.active_fx_pads.clear()
        mapped_fx_cols = {slot.get("fx_col") for slot in self._fader_map if slot.get("type") == "fx"}
        for fc in mapped_fx_cols:
            for r in range(8):
                self._style_fx_pad(fc, r)
                self._update_fx_pad_led(fc, r)

        # Remettre à zéro les canaux spéciaux et moving head
        for p in self.projectors:
            p.uv           = 0
            p.white_boost  = 0
            p.amber_boost  = 0
            p.orange_boost = 0
            p.pan          = 32768
            p.tilt         = 32768
            p.gobo         = 0
            p.zoom         = 0
            p.shutter      = 255
            p.color_wheel  = 0
            p.prism        = 0

        # Remettre tous les mutes à zéro + éteindre LEDs physiques
        for idx in list(self._muted_faders):
            if 0 <= idx < len(self.fader_buttons):
                self.fader_buttons[idx].active = False
                self.fader_buttons[idx].update_style()
            if MIDI_AVAILABLE and hasattr(self, 'midi_handler') and self.midi_handler.midi_out:
                self.midi_handler.midi_out.send_message([0x90, 100 + idx, 0])
        self._muted_faders.clear()

        # Remettre tous les cues actifs au premier cue
        for (mc, r) in list(self._mem_cue_idx.keys()):
            self._mem_cue_idx[(mc, r)] = 0
        self._dur_timer.stop()
        self._dur_progress_timer.stop()
        if hasattr(self, "_cue_panel"):
            self._cue_panel.set_progress(-1)
            mc, r = self._cue_panel.mem_col, self._cue_panel.row
            if mc >= 0:
                self._cue_panel.highlight_cue(0)

        self._log_message("CLEAR — AKAI remis à zéro", "info")

    def _init_default_fx_speed(self):
        """Initialise le fader FX à 80% au démarrage."""
        self.effect_speed = 80
        if 8 in self.faders:
            self.faders[8].set_value(80)

    def turn_off_all_effects(self):
        """Eteint tous les effets au demarrage"""
        for btn in self.effect_buttons:
            btn.active = False
            btn.update_style()

        # Vider la pile de superposition et arrêter le timer
        self._stacked_effects = []
        if hasattr(self, 'effect_timer'):
            self.effect_timer.stop()
        self.active_effect = None
        self.active_effect_config = {}

        # Désactiver les pads FX + LEDs physiques
        self.active_fx_pads.clear()
        mapped_fx_cols = {slot.get("fx_col") for slot in self._fader_map if slot.get("type") == "fx"}
        for fc in mapped_fx_cols:
            for r in range(8):
                self._style_fx_pad(fc, r)
                self._update_fx_pad_led(fc, r)

        if MIDI_AVAILABLE and hasattr(self, 'midi_handler') and self.midi_handler.midi_out:
            for i in range(8):
                note = 112 + i
                self.midi_handler.midi_out.send_message([0x90, note, 0])

    def show_ia_color_dialog(self):
        """Dialogue de selection de couleur dominante pour IA Lumiere"""
        dialog = QDialog(self)
        dialog.setWindowTitle("IA Lumiere")
        dialog.setFixedSize(420, 220)
        dialog.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel { color: white; border: none; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        title = QLabel("Choisissez la couleur dominante")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        colors_layout = QGridLayout()
        colors_layout.setSpacing(8)

        colors = [
            ("Rouge", QColor("#ff0000")),
            ("Bleu", QColor("#0066ff")),
            ("Vert", QColor("#00ff00")),
            ("Jaune", QColor("#ffdd00")),
            ("Violet", QColor("#aa00ff")),
            ("Orange", QColor("#ff8800")),
            ("Cyan", QColor("#00ddff")),
            ("Rose", QColor("#ff00aa")),
        ]

        selected_color = [None]

        for i, (name, color) in enumerate(colors):
            btn = QPushButton(name)
            btn.setFixedSize(90, 50)
            text_color = "black" if color.lightness() > 128 else "white"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color.name()};
                    color: {text_color};
                    border: 2px solid #3a3a3a;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 12px;
                }}
                QPushButton:hover {{ border: 3px solid white; }}
            """)
            btn.clicked.connect(lambda _, c=color: (selected_color.__setitem__(0, c), dialog.accept()))
            colors_layout.addWidget(btn, i // 4, i % 4)

        layout.addLayout(colors_layout)

        cancel_btn = QPushButton("Annuler")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a; color: white; border: none;
                border-radius: 6px; padding: 8px 20px;
            }
            QPushButton:hover { background: #4a4a4a; }
        """)
        cancel_btn.clicked.connect(dialog.reject)
        layout.addWidget(cancel_btn, alignment=Qt.AlignCenter)

        if dialog.exec() == QDialog.Accepted:
            return selected_color[0]
        return None

    def update_audio_ai(self):
        """IA Lumiere - Met a jour les projecteurs selon l'analyse audio avec effets creatifs"""
        try:
            # Ne pas interférer avec un effet en cours — l'effet a la priorité
            if getattr(self, 'active_effect', None) is not None:
                return
            # Ne pas interférer avec le fade-out de fin de média
            if self._ia_fadeout_timer and self._ia_fadeout_timer.isActive():
                return
            if self.seq.current_row < 0:
                return
            dmx_mode = self.seq.get_dmx_mode(self.seq.current_row)
            if dmx_mode != "IA Lumiere":
                return
            if self.player.playbackState() != QMediaPlayer.PlayingState:
                return
            if not self.audio_ai.analyzed:
                return

            import math

            position = self.player.position()
            duration = self.player.duration()

            state = self.audio_ai.get_state_at(position, duration, max_dimmers=self.ia_max_dimmers)

            section     = state.get('section', 'verse')
            energy      = state.get('energy', 0.5)
            global_fade = state.get('global_fade', 1.0)

            contre_alt    = state.get('contre_alt')
            lat_alt       = state.get('lat_alt')
            contre_effect = state.get('contre_effect')
            lat_effect    = state.get('lat_effect')

            # Paramètres nervosité (0.0 → 1.0)
            nerv = max(0.0, min(1.0, self.ia_params.get('nervosity', 50) / 100.0))

            # ── 1. Appliquer l'état de base (couleurs + levels depuis l'IA) ──
            contre_idx = 0
            lat_idx    = 0

            for p in self.projectors:
                if p.group not in state:
                    continue
                color, level = state[p.group]

                if p.group == 'contre':
                    if contre_alt and contre_idx % 2 == 1:
                        color = contre_alt
                    contre_idx += 1
                elif p.group == 'lat':
                    if lat_alt and lat_idx % 2 == 1:
                        color = lat_alt
                    if lat_effect == "strobe":
                        # Nervosité → strobe plus rapide
                        strobe_ms = int(80 - nerv * 45)   # 80ms calm → 35ms nerveux
                        strobe_on = (int(position / strobe_ms) % 2) == 0
                        if not strobe_on:
                            level = 0
                    lat_idx += 1

                p.level = level
                p.base_color = color
                if level > 0:
                    brightness = level / 100.0
                    p.color = QColor(
                        int(color.red()   * brightness),
                        int(color.green() * brightness),
                        int(color.blue()  * brightness)
                    )
                else:
                    p.color = QColor("black")

            # ── 2. Overrides par section ──────────────────────────────────────

            def _set_proj(p, color, level):
                """Applique couleur+level à un projecteur (évite le code dupliqué)."""
                p.level = max(0, min(100, level))
                p.base_color = color
                if p.level > 0:
                    f = p.level / 100.0
                    p.color = QColor(int(color.red()*f), int(color.green()*f), int(color.blue()*f))
                else:
                    p.color = QColor("black")

            # Initialiser l'état de section persistant
            if not hasattr(self, '_ia_sec'):
                self._ia_sec = {'last': None, 'drop_start': -1, 'build_p': 0.0}
            ss = self._ia_sec

            # ── DROP : effet choisi par l'utilisateur ────────────────────────
            if section == 'drop':
                DROP_MS = 1200.0
                if ss['last'] != 'drop':
                    ss['drop_start'] = position
                drop_p = min(1.0, (position - ss['drop_start']) / DROP_MS)
                drop_fx = self.ia_params.get('drop_effect', 'flash_blanc')

                # Fréquences de strobe adaptées à la nervosité
                strobe_ms_fast   = int(38 - nerv * 13)   # 38ms calm → 25ms nerveux
                strobe_ms_medium = int(55 - nerv * 20)   # 55ms → 35ms
                strobe_ms_slow   = int(75 - nerv * 25)   # 75ms → 50ms

                white = QColor(255, 255, 255)
                pal   = self.audio_ai.palette if self.audio_ai.palette else [white]

                # ── Flash Blanc ──────────────────────────────────────────────
                if drop_fx == 'flash_blanc':
                    if drop_p < 0.30:
                        punch = 1.0 - drop_p / 0.30
                        for p in self.projectors:
                            if getattr(p, 'fixture_type', '') == "Machine a fumee": continue
                            boost = int(100 * punch * global_fade)
                            if boost > p.level:
                                _set_proj(p, white, boost)
                    strobe_on = (int(position / strobe_ms_fast) % 2) == 0
                    for p in self.projectors:
                        if p.group in ('lat', 'contre') and not strobe_on:
                            p.level = 0; p.color = QColor("black")

                # ── Color Explosion ──────────────────────────────────────────
                elif drop_fx == 'color_explosion':
                    strobe_on = (int(position / strobe_ms_fast) % 2) == 0
                    for i, p in enumerate(self.projectors):
                        if getattr(p, 'fixture_type', '') == "Machine a fumee": continue
                        if strobe_on:
                            col = pal[i % len(pal)]
                            _set_proj(p, col, int(100 * global_fade))
                        else:
                            p.level = 0; p.color = QColor("black")

                # ── Blackout Punch ───────────────────────────────────────────
                elif drop_fx == 'blackout_punch':
                    if drop_p < 0.12:
                        # Coupure noire
                        for p in self.projectors:
                            if getattr(p, 'fixture_type', '') == "Machine a fumee": continue
                            p.level = 0; p.color = QColor("black")
                    else:
                        # Bang blanc puis décroissance
                        punch = max(0.0, 1.0 - (drop_p - 0.12) / 0.35)
                        for p in self.projectors:
                            if getattr(p, 'fixture_type', '') == "Machine a fumee": continue
                            _set_proj(p, white, int(100 * punch * global_fade))
                        # Strobe sur tout après le bang initial
                        if drop_p > 0.20:
                            strobe_on = (int(position / strobe_ms_medium) % 2) == 0
                            if not strobe_on:
                                for p in self.projectors:
                                    if getattr(p, 'fixture_type', '') != "Machine a fumee":
                                        p.level = 0; p.color = QColor("black")

                # ── Stroboscope Total ────────────────────────────────────────
                elif drop_fx == 'stroboscope':
                    strobe_ms = int(45 - nerv * 20)   # 45ms → 25ms
                    strobe_on = (int(position / strobe_ms) % 2) == 0
                    for p in self.projectors:
                        if getattr(p, 'fixture_type', '') == "Machine a fumee": continue
                        if strobe_on:
                            _set_proj(p, white, int(100 * global_fade))
                        else:
                            p.level = 0; p.color = QColor("black")

                # ── Laser Scan ───────────────────────────────────────────────
                elif drop_fx == 'laser_scan':
                    # Projecteurs fixes : punch blanc initial + strobe léger sur lat
                    if drop_p < 0.20:
                        punch = 1.0 - drop_p / 0.20
                        for p in self.projectors:
                            if getattr(p, 'fixture_type', '') == "Machine a fumee": continue
                            if getattr(p, 'fixture_type', '') != "Moving Head":
                                _set_proj(p, white, int(100 * punch * global_fade))
                    strobe_on = (int(position / strobe_ms_slow) % 2) == 0
                    for p in self.projectors:
                        if p.group == 'lat' and not strobe_on:
                            p.level = 0; p.color = QColor("black")
                    # Les lyres tourneront en turbo (géré dans le bloc lyres)

                ss['last'] = 'drop'

            # ── BUILD : montée en puissance + pulse + réchauffement ───────────
            elif section == 'build':
                # Progression vers le prochain drop (0=loin, 1=au drop)
                next_drop = next((d for d in self.audio_ai.drops if d > position), None)
                BUILD_MS = 3500.0
                build_p = max(0.0, min(1.0, 1.0 - (next_drop - position) / BUILD_MS)) \
                          if next_drop else 0.0
                ss['build_p'] = build_p

                # Pulse qui s'accélère sur les contres
                pulse_hz  = 2.5 + build_p * 10.0
                pulse_mod = math.sin(position / 1000.0 * pulse_hz * 2.0 * math.pi) * 0.5 + 0.5

                for p in self.projectors:
                    if getattr(p, 'fixture_type', '') == "Machine a fumee":
                        continue
                    if p.group == 'contre':
                        # Couleur qui se réchauffe vers le rouge/blanc
                        r = min(255, int(p.base_color.red() + build_p * (255 - p.base_color.red()) * 0.7))
                        g = int(p.base_color.green() * (1.0 - build_p * 0.5))
                        b = int(p.base_color.blue()  * (1.0 - build_p * 0.6))
                        warm = QColor(r, g, b)
                        lvl  = min(100, int(p.level * (1.0 + build_p * 0.35) * (0.35 + 0.65 * pulse_mod)))
                        _set_proj(p, warm, lvl)
                    elif p.group == 'face':
                        # Face : monte progressivement
                        lvl = min(100, int(p.level * (1.0 + build_p * 0.2)))
                        _set_proj(p, p.base_color, lvl)

                ss['last'] = 'build'

            # ── HIGH : énergie soutenue, tout amplifié ────────────────────────
            elif section == 'high':
                for p in self.projectors:
                    if getattr(p, 'fixture_type', '') == "Machine a fumee":
                        continue
                    lvl = min(100, int(p.level * 1.15))
                    _set_proj(p, p.base_color, lvl)
                ss['last'] = 'high'

            # ── QUIET : intro/outro/pont, tout réduit ─────────────────────────
            elif section == 'quiet':
                for p in self.projectors:
                    if getattr(p, 'fixture_type', '') == "Machine a fumee":
                        continue
                    cap = int(45 * global_fade)
                    if p.group in ('contre', 'lat'):
                        cap = int(20 * global_fade)
                    lvl = min(p.level, cap)
                    _set_proj(p, p.base_color, lvl)
                ss['last'] = 'quiet'

            else:  # verse
                ss['last'] = 'verse'

            # ── 2b. Effets aléatoires : chases, rainbow, wave… ───────────────
            # Se déclenchent entre les sections (pas pendant un drop)
            if not hasattr(self, '_ia_rnd_fx'):
                self._ia_rnd_fx = {
                    'active':     None,
                    'start_beat': -1,
                    'duration':   0,
                    'last_beat':  -1,
                    'trigger_at': 10,    # premier effet après 10 beats
                    'color_idx':  0,
                }
            rfx = self._ia_rnd_fx

            beat_count = getattr(self.audio_ai, '_beat_group_count', 0)
            beat_idx   = getattr(self.audio_ai, '_last_beat_idx', -1)

            # Progression dans le beat courant (0.0 → 1.0) pour les transitions smooth
            beat_prog = 0.0
            if 0 <= beat_idx < len(self.audio_ai.beats) - 1:
                t0 = self.audio_ai.beats[beat_idx]
                t1 = self.audio_ai.beats[beat_idx + 1]
                beat_prog = max(0.0, min(1.0, (position - t0) / max(1, t1 - t0)))

            # Suspendre l'effet pendant un drop
            if section == 'drop' and rfx['active']:
                rfx['active'] = None

            # Déclenchement d'un nouvel effet (nouveau beat + hors drop/quiet)
            new_beat = (beat_count != rfx['last_beat'])
            if (rfx['active'] is None
                    and new_beat
                    and section not in ('drop', 'quiet')
                    and beat_count >= rfx['trigger_at']):
                import random as _rnd
                # Effets disponibles selon la section
                pool = ['chase_fwd', 'chase_bwd', 'rainbow', 'spotlight', 'wave', 'color_snap']
                if section == 'high':
                    pool += ['chase_fwd', 'rainbow', 'wave']   # plus fréquents
                rfx['active']     = _rnd.choice(pool)
                rfx['start_beat'] = beat_count
                rfx['duration']   = _rnd.randint(4, 8)
                rfx['color_idx']  = getattr(self.audio_ai, '_contre_color_idx', 0)
                # Prochain déclenchement : nervosité réduit l'intervalle
                lo = max(4, int(14 - nerv * 8))
                hi = max(6, int(20 - nerv * 10))
                rfx['trigger_at'] = beat_count + rfx['duration'] + _rnd.randint(lo, hi)

            rfx['last_beat'] = beat_count

            # Fin de l'effet
            if rfx['active'] and beat_count >= rfx['start_beat'] + rfx['duration']:
                rfx['active'] = None

            # Application de l'effet actif (ne pas toucher aux machines à fumée)
            if rfx['active'] and section != 'drop':
                pal_fx   = self.audio_ai.palette if self.audio_ai.palette else [QColor("#ffffff")]
                GRP_ORD  = ['face', 'lat', 'contre', 'douche1', 'douche2', 'douche3']
                n_grps   = len(GRP_ORD)
                beats_el = max(0, beat_count - rfx['start_beat'])
                fx_name  = rfx['active']
                t_s      = position / 1000.0

                # Regrouper les projecteurs par groupe (hors fumée)
                by_grp = {}
                for p in self.projectors:
                    if getattr(p, 'fixture_type', '') != "Machine a fumee":
                        by_grp.setdefault(p.group, []).append(p)

                # ── Chase avant / arrière ──────────────────────────────────
                if fx_name in ('chase_fwd', 'chase_bwd'):
                    order = GRP_ORD if fx_name == 'chase_fwd' else list(reversed(GRP_ORD))
                    active_gi = beats_el % n_grps
                    # Transition smooth : active_gi → next_gi avec beat_prog
                    next_gi   = (active_gi + 1) % n_grps
                    for gi, grp in enumerate(order):
                        if grp not in by_grp:
                            continue
                        chase_col = pal_fx[(rfx['color_idx'] + beats_el) % len(pal_fx)]
                        if gi == active_gi:
                            # Descend avec beat_prog
                            lvl = int((100 - beat_prog * 65) * global_fade)
                        elif gi == next_gi:
                            # Monte avec beat_prog (anticipation)
                            lvl = int(beat_prog * 100 * global_fade)
                        else:
                            lvl = int(15 * global_fade)
                        for p in by_grp[grp]:
                            _set_proj(p, chase_col, lvl)

                # ── Rainbow wash ───────────────────────────────────────────
                elif fx_name == 'rainbow':
                    spd = 40.0 + nerv * 40.0   # 40°/s → 80°/s
                    for gi, grp in enumerate(GRP_ORD):
                        if grp not in by_grp:
                            continue
                        hue = int((t_s * spd + gi * (360.0 / n_grps)) % 360)
                        col = QColor.fromHsv(hue, 240, 255)
                        lvl = int((65 + energy * 30) * global_fade)
                        for p in by_grp[grp]:
                            _set_proj(p, col, lvl)

                # ── Spotlight ──────────────────────────────────────────────
                elif fx_name == 'spotlight':
                    spot_grp = GRP_ORD[beats_el % n_grps]
                    # Transition : le spot entrant monte, le sortant descend
                    prev_grp = GRP_ORD[(beats_el - 1) % n_grps]
                    spot_col = pal_fx[(rfx['color_idx'] + beats_el) % len(pal_fx)]
                    for grp, projs in by_grp.items():
                        if grp == spot_grp:
                            lvl = int((beat_prog * 100) * global_fade)
                        elif grp == prev_grp:
                            lvl = int(((1.0 - beat_prog) * 100) * global_fade)
                        else:
                            lvl = int(12 * global_fade)
                        for p in projs:
                            _set_proj(p, spot_col if grp in (spot_grp, prev_grp) else p.base_color, lvl)

                # ── Wave de luminosité ─────────────────────────────────────
                elif fx_name == 'wave':
                    wave_spd = 1.2 + nerv * 1.8   # 1.2 → 3 Hz
                    for gi, grp in enumerate(GRP_ORD):
                        if grp not in by_grp:
                            continue
                        phase = gi / n_grps * 2.0 * math.pi
                        val   = math.sin(t_s * wave_spd * 2.0 * math.pi + phase)
                        lvl   = int((45 + val * 50) * global_fade)
                        col   = pal_fx[(rfx['color_idx'] + gi) % len(pal_fx)]
                        for p in by_grp[grp]:
                            _set_proj(p, col, max(0, lvl))

                # ── Color Snap (snap de couleur au beat) ───────────────────
                elif fx_name == 'color_snap':
                    snap_col = pal_fx[(rfx['color_idx'] + beats_el) % len(pal_fx)]
                    # Fondu rapide entre l'ancienne couleur et la nouvelle
                    mix = min(1.0, beat_prog * 3.0)   # atteint 1.0 en 1/3 de beat
                    for grp, projs in by_grp.items():
                        for p in projs:
                            r = int(p.base_color.red()   * (1-mix) + snap_col.red()   * mix)
                            g_c = int(p.base_color.green() * (1-mix) + snap_col.green() * mix)
                            b_c = int(p.base_color.blue()  * (1-mix) + snap_col.blue()  * mix)
                            blended = QColor(r, g_c, b_c)
                            lvl = int((70 + energy * 30) * global_fade)
                            _set_proj(p, blended, lvl)

            # ── 3. Mouvement + couleur lyres (Moving Head) ───────────────────
            moving_heads = [p for p in self.projectors
                            if getattr(p, 'fixture_type', '') == "Moving Head"]
            if moving_heads:
                energy_raw = energy

                # Lissage EWMA
                if not hasattr(self, '_ia_lyre_e'):
                    self._ia_lyre_e        = energy_raw
                    self._ia_lyre_phase    = 0.0
                    self._ia_lyre_last_pos = position
                alpha = 0.07
                self._ia_lyre_e = alpha * energy_raw + (1.0 - alpha) * self._ia_lyre_e
                e = self._ia_lyre_e

                # Phase accumulée (fluide)
                dt = max(0.0, (position - self._ia_lyre_last_pos) / 1000.0)
                self._ia_lyre_last_pos = position

                # Vitesse adaptée à la section
                if section == 'drop':
                    drop_fx_now = self.ia_params.get('drop_effect', 'flash_blanc')
                    spd_mult = 5.0 if drop_fx_now == 'laser_scan' else (3.0 + nerv * 2.0)
                elif section == 'build':
                    spd_mult = 1.0 + ss.get('build_p', 0.0) * 2.0   # 1x → 3x
                elif section == 'high':
                    spd_mult = 1.6
                elif section == 'quiet':
                    spd_mult = 0.4
                else:
                    spd_mult = 1.0

                # Nervosité augmente la vitesse de base des lyres
                base_speed = (0.12 + nerv * 0.20) + e * (0.15 + nerv * 0.20)
                # calm(nerv=0): 0.12–0.27 Hz  |  nerveux(nerv=1): 0.32–0.67 Hz
                self._ia_lyre_phase += dt * base_speed * spd_mult * 2.0 * math.pi
                ph = self._ia_lyre_phase

                # Amplitude adaptée à la section
                if section == 'drop':
                    amp = 90.0
                elif section == 'quiet':
                    amp = 20.0 + e * 20.0
                else:
                    amp = 28.0 + e * 62.0

                # Couleur lyre = palette IA (suit les contres)
                pal     = self.audio_ai.palette if self.audio_ai.palette else [QColor("#ffffff")]
                c_idx   = getattr(self.audio_ai, '_contre_color_idx', 0)
                lyre_color = pal[c_idx % len(pal)]

                # En drop : lyres en blanc
                if section == 'drop':
                    drop_p_now = min(1.0, (position - ss.get('drop_start', position)) / 1200.0)
                    if drop_p_now < 0.35:
                        lyre_color = QColor(255, 255, 255)

                lyre_level = int(60 + e * 40)
                if section == 'drop':
                    lyre_level = 100
                elif section == 'quiet':
                    lyre_level = int(30 + e * 20)

                for i, p in enumerate(moving_heads):
                    phi = i * (2.0 * math.pi / max(len(moving_heads), 1))

                    # Strobe shutter sur lyres pendant le drop
                    if section == 'drop':
                        strobe_on = (int(position / 55) % 2) == 0
                        p.shutter = 255 if strobe_on else 0
                    else:
                        p.shutter = 255

                    # Figure 8 lissajous
                    pan_val  = 32768 + int(amp * 256 * math.sin(ph + phi))
                    tilt_val = 32768 + int(amp * 128 * math.sin(2.0 * (ph + phi)))
                    p.pan  = max(0, min(65535, pan_val))
                    p.tilt = max(0, min(65535, tilt_val))

                    # Couleur (seulement si groupe absent de state)
                    if p.group not in state:
                        p.level = max(0, min(100, lyre_level))
                        p.base_color = lyre_color
                        brightness = p.level / 100.0
                        p.color = QColor(
                            int(lyre_color.red()   * brightness),
                            int(lyre_color.green() * brightness),
                            int(lyre_color.blue()  * brightness),
                        )
                        # ColorWheel (MOVING_8CH)
                        profile = getattr(p, 'dmx_profile', [])
                        if 'ColorWheel' in profile and 'R' not in profile:
                            slots = getattr(p, 'color_wheel_slots', [])
                            if slots:
                                def _dist(s):
                                    sc = QColor(s.get('color', '#ffffff'))
                                    dr = sc.red()   - lyre_color.red()
                                    dg = sc.green() - lyre_color.green()
                                    db = sc.blue()  - lyre_color.blue()
                                    return dr*dr + dg*dg + db*db
                                p.color_wheel = min(slots, key=_dist).get('dmx', 0)
                            else:
                                h = lyre_color.hsvHue()
                                if h < 0:                  p.color_wheel = 0
                                elif h < 30 or h >= 330:   p.color_wheel = 21
                                elif h < 75:               p.color_wheel = 85
                                elif h < 150:              p.color_wheel = 42
                                elif h < 195:              p.color_wheel = 106
                                elif h < 270:              p.color_wheel = 64
                                else:                      p.color_wheel = 128

            if hasattr(self, 'plan_de_feu'):
                self.plan_de_feu.update()

        except Exception as e:
            print(f"Erreur IA Lumiere: {e}")

    def _ia_start_fadeout(self, callback=None):
        """Démarre un fade-out IA (~1.5 s) puis appelle callback."""
        # Arrêter tout fade en cours
        if self._ia_fadeout_timer and self._ia_fadeout_timer.isActive():
            self._ia_fadeout_timer.stop()

        self._ia_fadeout_levels = {id(p): p.level for p in self.projectors}
        self._ia_fadeout_steps = 0
        self._ia_fadeout_callback = callback

        if self._ia_fadeout_timer is None:
            self._ia_fadeout_timer = QTimer(self)
            self._ia_fadeout_timer.timeout.connect(self._ia_fadeout_tick)
        self._ia_fadeout_timer.start(50)

    def _ia_fadeout_tick(self):
        """Tick du fade-out IA : réduit les niveaux progressivement."""
        self._ia_fadeout_steps += 1
        progress = self._ia_fadeout_steps / self._ia_fadeout_total
        for p in self.projectors:
            orig = self._ia_fadeout_levels.get(id(p), 0)
            p.level = max(0, int(orig * (1.0 - progress)))
            if p.level <= 0:
                p.color = QColor("black")
            else:
                factor = p.level / 100.0
                p.color = QColor(
                    int(p.base_color.red() * factor),
                    int(p.base_color.green() * factor),
                    int(p.base_color.blue() * factor),
                )
        self.send_dmx_update()
        if hasattr(self, 'plan_de_feu'):
            self.plan_de_feu.update()

        if self._ia_fadeout_steps >= self._ia_fadeout_total:
            self._ia_fadeout_timer.stop()
            for p in self.projectors:
                p.level = 0
                p.color = QColor("black")
            self.send_dmx_update()
            if self._ia_fadeout_callback:
                cb = self._ia_fadeout_callback
                self._ia_fadeout_callback = None
                cb()

    def play_path(self, path):
        """Joue un fichier media"""
        self._stop_all_cartouches()
        try:
            self.player.setSource(QUrl.fromLocalFile(path))
            try:
                self.player.durationChanged.disconnect()
            except:
                pass
            row = self.seq.current_row
            self.player.durationChanged.connect(lambda d: self.update_duration_display(d, row))
            self.player.play()
            self._update_video_output_state()
        except Exception as e:
            print(f"Erreur play: {e}")

    def update_duration_display(self, duration_ms, row):
        """Met a jour l'affichage de la duree"""
        if row >= 0 and duration_ms > 0:
            minutes = duration_ms // 60000
            seconds = (duration_ms % 60000) // 1000
            dur_text = f"{minutes:02d}:{seconds:02d}"
            dur_item = self.seq.table.item(row, 2)
            if dur_item:
                dur_item.setText(dur_text)

    def on_midi_fader(self, fader_idx, value):
        """Reception d'un mouvement de fader MIDI"""
        converted_value = int((value / 127.0) * 100)

        if fader_idx == 8:
            self._fader8_dispatch(fader_idx, converted_value)
            if fader_idx in self.faders:
                self.faders[fader_idx].value = converted_value
                self.faders[fader_idx].update()
        elif 0 <= fader_idx <= 7:
            if fader_idx in self.faders:
                self.faders[fader_idx].value = converted_value
                self.faders[fader_idx].update()
            self.set_proj_level(fader_idx, converted_value)

        # Push tablette
        import tablet_server as _ts
        if _ts.is_running():
            _ts.push_fader(fader_idx, converted_value)

    def on_midi_pad(self, row, col):
        """Reception d'un appui de pad MIDI"""
        if col == 8:
            self.toggle_effect(row)
            if MIDI_AVAILABLE and self.midi_handler.midi_out:
                velocity = 1 if self.effect_buttons[row].active else 0
                self.midi_handler.set_pad_led(row, col, velocity, brightness_percent=100)
            return

        pad = self.pads.get((row, col))
        if pad:
            if col < len(self._fader_map):
                slot = self._fader_map[col]
                if slot["type"] == "group":
                    # Pads couleur standard
                    for r in range(8):
                        if r != row:
                            other_pad = self.pads.get((r, col))
                            if other_pad:
                                other_color = other_pad.property("base_color")
                                other_velocity = rgb_to_akai_velocity(other_color)
                                self.midi_handler.set_pad_led(r, col, other_velocity, brightness_percent=20)

                    self.activate_pad(pad, col)
                    if MIDI_AVAILABLE and self.midi_handler.midi_out:
                        base_color = pad.property("base_color")
                        velocity = rgb_to_akai_velocity(base_color)
                        self.midi_handler.set_pad_led(row, col, velocity, brightness_percent=100)
                elif slot["type"] == "fx":
                    # Pads FX — toggle l'effet mappé sur ce pad
                    fx_col = slot.get("fx_col", 0)
                    self._toggle_fx_pad(fx_col, row)  # met à jour visuel + LEDs physiques
                else:
                    # Memory pads individuels
                    mem_col = slot["mem_col"]
                    if self._mem_rec_mode or self.memories[mem_col][row] is not None:
                        self._activate_memory_pad(pad, mem_col, row, col_akai=col)
                        # Update LEDs de toute la colonne
                        for r in range(8):
                            is_active = self.active_memory_pads.get(col) == r
                            self._update_memory_pad_led(mem_col, r, active=is_active)

    def new_show(self):
        """Cree un nouveau show"""
        self.clear_sequence()

    def clear_sequence(self):
        """Vide le sequenceur"""
        # Couper le son si un media est en cours
        try:
            self.player.stop()
            self.cart_player.stop()
            self.pause_mode = False
            if hasattr(self.seq, 'tempo_timer') and self.seq.tempo_timer and self.seq.tempo_timer.isActive():
                self.seq.tempo_timer.stop()
            if hasattr(self.seq, 'timeline_playback_timer') and self.seq.timeline_playback_timer and self.seq.timeline_playback_timer.isActive():
                self.seq.timeline_playback_timer.stop()
        except Exception:
            pass

        if self.seq.table.rowCount() == 0:
            QMessageBox.information(self, tr("seq_empty_title"), tr("seq_empty_msg"))
            return

        if self.seq.is_dirty:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle(tr("seq_clear_title"))
            msg.setText(tr("seq_save_before_clear"))
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            res = msg.exec()

            if res == QMessageBox.Yes:
                if not self.save_show():
                    return
            elif res == QMessageBox.Cancel:
                return
        else:
            res = QMessageBox.question(self, tr("seq_clear_title"),
                tr("seq_confirm_delete"),
                QMessageBox.Yes | QMessageBox.No)
            if res == QMessageBox.No:
                return

        self.seq.clear_sequence()
        self.current_show_path = None
        self.setWindowTitle(APP_NAME)

    def save_show(self):
        """Sauvegarde le show (ecrase si deja ouvert, sinon demande le chemin)"""
        # Utiliser le chemin existant ou demander un nouveau
        if self.current_show_path:
            path = self.current_show_path
        else:
            path, _ = QFileDialog.getSaveFileName(self, tr("dlg_save_show"), "", tr("tui_filter"))
            if not path:
                return False

        save_data = self._build_save_data()

        # Avertissement si des clips lumière sont orphelins (row supprimé ou séquence vide)
        row_count = self.seq.table.rowCount()
        all_clip_rows = set(self.seq.sequences.keys()) if hasattr(self.seq, 'sequences') else set()
        orphan_clips = len([r for r in all_clip_rows if r >= row_count])
        if orphan_clips > 0:
            from PySide6.QtWidgets import QMessageBox
            ret = QMessageBox.warning(
                self, tr("rec_light_warn_title"),
                tr("rec_light_warn_msg", n=orphan_clips),
                QMessageBox.Save | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            if ret == QMessageBox.Cancel:
                return False

        try:
            with open(path, 'w') as f:
                json.dump(save_data, f, indent=2)
            self.seq.is_dirty = False
            self.current_show_path = path
            self.add_recent_file(path)
            self.setWindowTitle(f"{APP_NAME} - {os.path.basename(path)}")
            self.plan_de_feu.refresh()
            return True
        except Exception as e:
            QMessageBox.critical(self, tr("err_save_title"), tr("err_save_msg", e=e))
            return False

    def save_show_as(self):
        """Sauvegarde le show sous un nouveau nom"""
        old_path = self.current_show_path
        self.current_show_path = None  # Force le dialogue
        if not self.save_show():
            self.current_show_path = old_path  # Restaurer si annule
            return False
        return True

    def _build_save_data(self) -> dict:
        """Sérialise l'état complet du show en dict JSON-compatible (thread principal)."""
        data = []
        for r in range(self.seq.table.rowCount()):
            path_item = self.seq.table.item(r, 1)
            vol_item  = self.seq.table.item(r, 3)
            user_data = str(path_item.data(Qt.UserRole)) if path_item else ""

            if user_data == "PAUSE":
                entry = {'type': 'pause', 'd': self.seq.get_dmx_mode(r)}
                if r in self.seq.sequences and 'clips' in self.seq.sequences[r]:
                    seq = self.seq.sequences[r]
                    entry['sequence'] = {'clips': seq['clips'], 'duration': seq['duration']}
                data.append(entry)
            elif user_data.startswith("PAUSE:"):
                seconds = int(user_data.split(":")[1])
                entry = {'type': 'pause', 'duration': seconds, 'd': self.seq.get_dmx_mode(r)}
                if r in self.seq.sequences and 'clips' in self.seq.sequences[r]:
                    seq = self.seq.sequences[r]
                    entry['sequence'] = {'clips': seq['clips'], 'duration': seq['duration']}
                data.append(entry)
            else:
                dmx_mode = self.seq.get_dmx_mode(r)
                if path_item and vol_item:
                    row_data = {
                        'type': 'media',
                        'p':    path_item.data(Qt.UserRole),
                        'v':    vol_item.text(),
                        'd':    dmx_mode,
                    }
                    if dmx_mode == "IA Lumiere" and r in self.seq.ia_colors:
                        row_data['ia_color'] = self.seq.ia_colors[r].name()
                    if r in self.seq.ia_analysis:
                        row_data['ia_analysis'] = self.seq.ia_analysis[r]
                    if r in self.seq.sequences:
                        seq = self.seq.sequences[r]
                        if 'clips' in seq:
                            row_data['sequence'] = {'clips': seq['clips'], 'duration': seq['duration']}
                        elif 'keyframes' in seq:
                            row_data['sequence'] = {'keyframes': seq['keyframes'], 'duration': seq['duration']}
                    if r in self.seq.image_durations:
                        row_data['image_duration'] = self.seq.image_durations[r]
                    data.append(row_data)

        cart_data = [{"path": c.media_path, "volume": c.volume} for c in self.cartouches]

        custom_colors_serial = [
            [self.memory_custom_colors[mc][mr].name() if self.memory_custom_colors[mc][mr] else None
             for mr in range(8)]
            for mc in range(_MEM_COL_MAX)
        ]

        active_pads_serial = {str(k): v for k, v in self.active_memory_pads.items()}

        overrides = self._compute_htp_overrides()
        plan_de_feu_state = []
        for proj in self.projectors:
            if overrides and id(proj) in overrides:
                level, color, base = overrides[id(proj)]
                plan_de_feu_state.append({"group": proj.group, "level": level,
                                           "base_color": base.name(), "muted": proj.muted})
            else:
                plan_de_feu_state.append({"group": proj.group, "level": proj.level,
                                           "base_color": proj.base_color.name(), "muted": proj.muted})

        faders_state     = {str(idx): fader.value for idx, fader in self.faders.items()}
        active_color_pads = {}
        for col_idx, btn in self.active_pads.items():
            bc = btn.property("base_color")
            if bc:
                active_color_pads[str(col_idx)] = bc.name()

        return {
            "version": 5,
            "sequence": data,
            "cartouches": cart_data,
            "memories": self.memories,
            "memory_custom_colors": custom_colors_serial,
            "active_memory_pads": active_pads_serial,
            "plan_de_feu": plan_de_feu_state,
            "faders": faders_state,
            "active_color_pads": active_color_pads,
        }

    def _autosave(self):
        """Autosave silencieux toutes les 5 min — écriture disque en thread background."""
        if not self.seq.is_dirty or self.seq.table.rowCount() == 0:
            return

        import tempfile, datetime, threading, json as _json

        autosave_path = (
            self.current_show_path + ".autosave"
            if self.current_show_path
            else os.path.join(tempfile.gettempdir(), "mystrow_autosave.tui")
        )

        # Sérialisation sur le thread principal (accès aux widgets Qt)
        try:
            save_data = self._build_save_data()
        except Exception as e:
            print(f"[Autosave] Erreur sérialisation : {e}")
            return

        # Écriture disque en background → zéro impact sur le live
        def _write(data=save_data, path=autosave_path):
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    _json.dump(data, f, indent=2)
            except Exception as e:
                print(f"[Autosave] Erreur écriture : {e}")

        threading.Thread(target=_write, daemon=True, name="autosave").start()

        # Notification discrète 3 secondes
        ts = datetime.datetime.now().strftime("%H:%M")
        lbl = getattr(self, "_autosave_lbl", None)
        if lbl:
            lbl.setText(f"💾 {ts}")
            lbl.show()
            QTimer.singleShot(3000, lbl.hide)

    def load_show(self, path=None):
        """Charge un show"""
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("dlg_open_show"), "", tr("tui_filter"))
        if not path:
            return

        # Stopper la lecture en cours avant de charger
        try:
            self.player.stop()
            self.cart_player.stop()
            self.pause_mode = False
            if hasattr(self.seq, 'tempo_timer') and self.seq.tempo_timer.isActive():
                self.seq.tempo_timer.stop()
            if hasattr(self.seq, 'timeline_playback_timer') and self.seq.timeline_playback_timer.isActive():
                self.seq.timeline_playback_timer.stop()
        except Exception:
            pass

        try:
            with open(path, 'r') as f:
                raw = json.load(f)

            # Retrocompatibilite: ancien format = tableau, nouveau = objet
            if isinstance(raw, list):
                data = raw
                cart_data = []
                mem_data = None
                custom_colors_data = None
                active_pads_data = None
            else:
                data = raw.get("sequence", [])
                cart_data = raw.get("cartouches", [])
                mem_data = raw.get("memories")
                custom_colors_data = raw.get("memory_custom_colors")
                active_pads_data = raw.get("active_memory_pads")

            self.seq.table.setRowCount(0)
            self.seq.sequences = {}
            self.seq.ia_colors = {}
            self.seq.ia_analysis = {}
            self.seq.image_durations = {}
            self.seq._loading = True

            try:
                for item in data:
                    item_type = item.get('type')

                    # PAUSE (indefinie ou temporisee) + retrocompat TEMPO
                    if item_type in ('pause', 'tempo'):
                        self.seq.add_pause()
                        row = self.seq.table.rowCount() - 1

                        # Determiner la duree
                        duration_val = item.get('duration')
                        if duration_val is not None:
                            pause_seconds = int(duration_val)
                            pause_item = self.seq.table.item(row, 1)
                            if pause_item:
                                pause_item.setData(Qt.UserRole, f"PAUSE:{pause_seconds}")
                                minutes = pause_seconds // 60
                                seconds = pause_seconds % 60
                                pause_item.setText(f"Pause ({minutes}m {seconds}s)" if minutes > 0 else f"Pause ({pause_seconds}s)")
                            dur_item = self.seq.table.item(row, 2)
                            if dur_item:
                                minutes = pause_seconds // 60
                                seconds = pause_seconds % 60
                                dur_item.setText(f"{minutes:02d}:{seconds:02d}")

                        # Charger le mode DMX
                        if 'd' in item:
                            combo = self.seq._get_dmx_combo(row)
                            if combo:
                                if item['d'] == "Play Lumiere" and combo.findText("Play Lumiere") == -1:
                                    combo.addItem("Play Lumiere")
                                combo.setCurrentText(item['d'])

                        # Charger la sequence lumiere
                        if 'sequence' in item:
                            seq_data = item['sequence']
                            if 'clips' in seq_data:
                                self.seq.sequences[row] = {
                                    'clips': seq_data['clips'],
                                    'duration': seq_data['duration']
                                }

                    else:
                        self.seq.add_files([item['p']])
                        row = self.seq.table.rowCount() - 1
                        vol_item = self.seq.table.item(row, 3)
                        if vol_item and vol_item.text() != "--":
                            vol_item.setText(item.get('v', '100'))
                        if 'd' in item:
                            # Restaurer la couleur IA avant d'appliquer le mode
                            if 'ia_color' in item:
                                self.seq.ia_colors[row] = QColor(item['ia_color'])
                            if 'ia_analysis' in item:
                                self.seq.ia_analysis[row] = item['ia_analysis']
                            combo = self.seq._get_dmx_combo(row)
                            if combo:
                                if item['d'] == "Play Lumiere" and combo.findText("Play Lumiere") == -1:
                                    combo.addItem("Play Lumiere")
                                combo.setCurrentText(item['d'])
                                self.seq.on_dmx_changed(row, item['d'])
                        if 'sequence' in item:
                            seq_data = item['sequence']
                            # Gerer les deux formats: 'clips' et 'keyframes'
                            if 'clips' in seq_data:
                                self.seq.sequences[row] = {
                                    'clips': seq_data['clips'],
                                    'duration': seq_data['duration']
                                }
                            elif 'keyframes' in seq_data:
                                self.seq.sequences[row] = {
                                    'keyframes': seq_data['keyframes'],
                                    'duration': seq_data['duration']
                                }
                        if 'image_duration' in item:
                            self.seq.image_durations[row] = int(item['image_duration'])
            finally:
                self.seq._loading = False

            # Restaurer les cartouches
            for i, cd in enumerate(cart_data):
                if i < len(self.cartouches):
                    self.cartouches[i].volume = cd.get("volume", 100)
                    if cd.get("path"):
                        p = cd["path"]
                        self.cartouches[i].media_path = p
                        self.cartouches[i].media_title = Path(p).stem
                        ext = Path(p).suffix.lower()
                        if ext in CartoucheButton.VIDEO_EXTS:
                            self.cartouches[i].media_icon = "\U0001f3ac"
                        elif ext in CartoucheButton.AUDIO_EXTS:
                            self.cartouches[i].media_icon = "\U0001f3b5"
                        else:
                            self.cartouches[i].media_icon = ""
                    self.cartouches[i].set_idle()

            # Restaurer les memoires depuis le .tui uniquement si pas de fichier config AKAI
            # (le fichier config AKAI est la source de vérité depuis qu'il existe)
            if not os.path.exists(self._AKAI_CONFIG_PATH):
                self.memories = [[None]*8 for _ in range(_MEM_COL_MAX)]
                self.memory_custom_colors = [[None]*8 for _ in range(_MEM_COL_MAX)]
                self.active_memory_pads = {}

                if mem_data:
                    if isinstance(mem_data, list) and len(mem_data) >= 1:
                        if isinstance(mem_data[0], list):
                            for mc in range(min(_MEM_COL_MAX, len(mem_data))):
                                for mr in range(min(8, len(mem_data[mc]))):
                                    self.memories[mc][mr] = mem_data[mc][mr]
                        else:
                            for mc in range(min(_MEM_COL_MAX, len(mem_data))):
                                if mem_data[mc]:
                                    self.memories[mc][0] = mem_data[mc]

                if custom_colors_data and isinstance(custom_colors_data, list):
                    for mc in range(min(_MEM_COL_MAX, len(custom_colors_data))):
                        for mr in range(min(8, len(custom_colors_data[mc]))):
                            c = custom_colors_data[mc][mr]
                            self.memory_custom_colors[mc][mr] = QColor(c) if c else None

                if active_pads_data and isinstance(active_pads_data, dict):
                    for k, v in active_pads_data.items():
                        self.active_memory_pads[int(k)] = v

            # Mettre a jour l'affichage des pads memoire
            for fi, mc in self._bank_memory_slots():
                for mr in range(8):
                    is_active = self.active_memory_pads.get(fi) == mr
                    self._style_memory_pad(mc, mr, active=is_active)

            # Restaurer l'etat du plan de feu (v5+)
            if isinstance(raw, dict):
                plan_de_feu_data = raw.get("plan_de_feu")
                faders_data = raw.get("faders")
                active_color_pads_data = raw.get("active_color_pads")

                # Restaurer les faders
                if faders_data and isinstance(faders_data, dict):
                    for idx_str, value in faders_data.items():
                        idx = int(idx_str)
                        if idx in self.faders:
                            self.faders[idx].value = int(value)
                            self.faders[idx].update()

                # Restaurer les pads couleur actifs (colonnes 0-3)
                if active_color_pads_data and isinstance(active_color_pads_data, dict):
                    for col_str, color_name in active_color_pads_data.items():
                        col_idx = int(col_str)
                        target_color = QColor(color_name)
                        # Chercher le pad qui correspond a cette couleur
                        for row in range(8):
                            pad = self.pads.get((row, col_idx))
                            if pad:
                                pad_color = pad.property("base_color")
                                if pad_color and pad_color.name() == target_color.name():
                                    self.activate_pad(pad, col_idx)
                                    break

                # Restaurer l'etat des projecteurs
                if plan_de_feu_data and isinstance(plan_de_feu_data, list):
                    for i, pstate in enumerate(plan_de_feu_data):
                        if i < len(self.projectors):
                            proj = self.projectors[i]
                            proj.level = pstate.get("level", 0)
                            proj.base_color = QColor(pstate.get("base_color", "#000000"))
                            proj.muted = pstate.get("muted", False)
                            if proj.level > 0:
                                brt = proj.level / 100.0
                                proj.color = QColor(
                                    int(proj.base_color.red() * brt),
                                    int(proj.base_color.green() * brt),
                                    int(proj.base_color.blue() * brt))
                            else:
                                proj.color = QColor(0, 0, 0)

                self.plan_de_feu.refresh()

            self.seq.is_dirty = False
            self.current_show_path = path
            self.add_recent_file(path)
            self.setWindowTitle(f"{APP_NAME} - {os.path.basename(path)}")

            # Verification des fichiers medias
            self._check_missing_media()

        except Exception as e:
            self.seq._loading = False
            QMessageBox.critical(self, tr("err_save_title"), tr("err_load_msg", e=e))

    def _check_missing_media(self):
        """Verifie que tous les fichiers medias du show existent"""
        missing = []
        for row in range(self.seq.table.rowCount()):
            title_item = self.seq.table.item(row, 1)
            if not title_item:
                continue
            path = title_item.data(Qt.UserRole)
            if not path or str(path) == "PAUSE" or str(path).startswith("PAUSE:"):
                continue
            if not os.path.isfile(path):
                missing.append((row, Path(path).name, path))
                # Emoji erreur dans la colonne icone
                icon_item = self.seq.table.item(row, 0)
                if icon_item:
                    icon_item.setText("\u26a0\ufe0f")
                    icon_item.setData(Qt.UserRole, "\u26a0\ufe0f")
                # Marquer visuellement la ligne en rouge
                for col in range(self.seq.table.columnCount()):
                    item = self.seq.table.item(row, col)
                    if item:
                        item.setForeground(QColor("#ff4444"))

        if missing:
            details = "\n".join(
                tr("missing_file_line", row=r + 1, name=name) for r, name, _ in missing
            )
            QMessageBox.warning(self, tr("missing_files_title"),
                tr("missing_files_msg", n=len(missing), details=details))

    # ==================== CONFIG AKAI (sauvegarde/chargement memoires) ====================

    _AKAI_CONFIG_PATH = str(Path.home() / '.maestro_akai_config.json')

    def _serialize_akai_config(self):
        """Serialise les memoires AKAI en dict JSON"""
        custom_colors_serial = []
        for mc in range(_MEM_COL_MAX):
            col_colors = []
            for mr in range(8):
                c = self.memory_custom_colors[mc][mr]
                col_colors.append(c.name() if c else None)
            custom_colors_serial.append(col_colors)

        active_pads_serial = {str(k): v for k, v in self.active_memory_pads.items()}

        return {
            "memories": self.memories,
            "memory_custom_colors": custom_colors_serial,
            "active_memory_pads": active_pads_serial,
            "custom_bank_slots": [dict(s) for s in self._custom_bank_slots],
            "last_fader_mode": "FX",
            "fx_pads": self.fx_pads,
            "effect_superposition": self.effect_superposition,
            "go_mode": self.go_mode,
        }

    def _apply_akai_config(self, config):
        """Applique une config AKAI (memoires) depuis un dict"""
        mem_data = config.get("memories")
        custom_colors_data = config.get("memory_custom_colors")
        active_pads_data = config.get("active_memory_pads")

        self.memories = [[None]*8 for _ in range(_MEM_COL_MAX)]
        self.memory_custom_colors = [[None]*8 for _ in range(_MEM_COL_MAX)]
        self.active_memory_pads = {}

        # Restore custom layout (ou compat ascendante avec bank_preset_idx)
        custom_slots = config.get("custom_bank_slots")
        if custom_slots and isinstance(custom_slots, list) and len(custom_slots) == 8:
            # Migration: convertir les anciens slots "groups": ["face"] → "group": "A"
            migrated = []
            for s in custom_slots:
                if s.get("type") == "group" and "groups" in s and "group" not in s:
                    old_groups = s["groups"]
                    letter = _AKAI_GROUP_REVERSE.get(old_groups[0], "A") if old_groups else "A"
                    migrated.append({"type": "group", "group": letter, "label": s.get("label", letter)})
                else:
                    migrated.append(s)
            self._custom_bank_slots = migrated
        else:
            # Ancien format : bank_preset_idx
            old_idx = config.get("bank_preset_idx", 0)
            if 0 <= old_idx < len(AKAI_BANK_PRESETS):
                self._custom_bank_slots = [dict(s) for s in AKAI_BANK_PRESETS[old_idx]["slots"]]

        if mem_data and isinstance(mem_data, list):
            if len(mem_data) >= 1 and isinstance(mem_data[0], list):
                for mc in range(min(_MEM_COL_MAX, len(mem_data))):
                    for mr in range(min(8, len(mem_data[mc]))):
                        self.memories[mc][mr] = mem_data[mc][mr]

        if custom_colors_data and isinstance(custom_colors_data, list):
            for mc in range(min(_MEM_COL_MAX, len(custom_colors_data))):
                for mr in range(min(8, len(custom_colors_data[mc]))):
                    c = custom_colors_data[mc][mr]
                    self.memory_custom_colors[mc][mr] = QColor(c) if c else None

        # Restore FX pads assignments
        fx_pads_data = config.get("fx_pads")
        if fx_pads_data and isinstance(fx_pads_data, list):
            for fc in range(min(_FX_COL_MAX, len(fx_pads_data))):
                if isinstance(fx_pads_data[fc], list):
                    for fr in range(min(8, len(fx_pads_data[fc]))):
                        self.fx_pads[fc][fr] = fx_pads_data[fc][fr]

        # Fader 9 toujours en mode FX
        self._last_fader_mode = "FX"

        # Superposition d'effets
        self.effect_superposition = config.get("effect_superposition", False)

        # Mode GO
        self.go_mode = config.get("go_mode", False)
        self._update_tap_go_btn_style()

        # active_memory_pads non restaure : toujours demarrer sans pad actif
        # (evite le pad du haut "toujours enclenche" au demarrage)

        # Rafraichir l'affichage des pads memoire
        for fi, mc in self._bank_memory_slots():
            for mr in range(8):
                is_active = self.active_memory_pads.get(fi) == mr
                self._style_memory_pad(mc, mr, active=is_active)

        # Les pads FX seront rafraîchis lors du prochain _rebuild_akai_pads()

    def _save_akai_config_auto(self):
        """Sauvegarde automatique de la config AKAI a la fermeture"""
        try:
            config = self._serialize_akai_config()
            with open(self._AKAI_CONFIG_PATH, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Erreur sauvegarde config AKAI: {e}")

    def _load_akai_config_auto(self):
        """Charge automatique de la config AKAI au demarrage.
        Premier lancement (pas de fichier) : applique les presets par defaut."""
        try:
            if not os.path.exists(self._AKAI_CONFIG_PATH):
                # Premier lancement : charger les presets par defaut
                print("Premier lancement : application des presets AKAI par defaut")
                self._apply_akai_config(self._build_default_akai_presets())
                self._save_akai_config_auto()
            else:
                with open(self._AKAI_CONFIG_PATH, 'r') as f:
                    config = json.load(f)
                self._apply_akai_config(config)
                # Migrer uniquement si le fichier n'a pas de section memories explicite
                # (vieux fichier de config sans memories) — évite d'écraser un effacement volontaire
                if "memories" not in config:
                    self._migrate_missing_pad_colors()
            # Reconstruire les pads/faders avec le layout restauré
            if hasattr(self, '_pads_container'):
                self._rebuild_akai_pads()
                if hasattr(self, '_fader_label_widgets'):
                    for i, lbl in enumerate(self._fader_label_widgets):
                        if i < len(self._fader_map):
                            lbl.setText(self._fader_map[i]["label"])
            # Toujours activer le pad du haut de chaque colonne memoire au demarrage
            self._activate_top_pads_default()
        except Exception as e:
            print(f"Erreur chargement config AKAI: {e}")

    # Couleurs de rangee par defaut (meme ordre que la grille AKAI cols 0-3)
    _DEFAULT_PAD_ROW_COLORS = [
        "#ffffff", "#ff0000", "#ff8800", "#ffdd00",
        "#00ff00", "#00dddd", "#0000ff", "#ff00ff",
    ]

    def _migrate_missing_pad_colors(self):
        """Migration : pour toute colonne memoire sans couleurs ou sans memoires,
        applique les presets par defaut (couleurs de rangee + snapshots DMX).
        S'execute une seule fois apres chargement d'un ancien fichier de config."""
        needs_save = False
        _presets = None  # charge les presets une seule fois si necessaire

        for mc in range(8):
            has_colors   = any(self.memory_custom_colors[mc][mr] is not None for mr in range(8))
            has_memories = any(self.memories[mc][mr] is not None for mr in range(8))

            if not has_colors or not has_memories:
                if _presets is None:
                    _presets = self._build_default_akai_presets()

                if not has_memories and mc < len(_presets["memories"]):
                    for mr in range(8):
                        self.memories[mc][mr] = _presets["memories"][mc][mr]

                if not has_colors:
                    for mr in range(8):
                        self.memory_custom_colors[mc][mr] = QColor(self._DEFAULT_PAD_ROW_COLORS[mr])

                col_akai = self._mem_col_to_fader(mc)
                for mr in range(8):
                    is_active = self.active_memory_pads.get(col_akai) == mr
                    self._style_memory_pad(mc, mr, active=is_active)

                needs_save = True
                print(f"Migration : colonne memoire {mc + 1} mise a jour")

        if needs_save:
            self._save_akai_config_auto()

    def _activate_top_pads_default(self):
        """Active le pad du haut (rangee 0) de chaque colonne memoire.
        Appele au demarrage. Les LEDs physiques AKAI sont envoyees par
        activate_default_white_pads() qui se declenche 100ms apres l'init."""
        for fi, mc in self._bank_memory_slots():
            if self.memories[mc][0] is not None:
                self.active_memory_pads[fi] = 0
                self._style_memory_pad(mc, 0, active=True)
                self._apply_memory_to_projectors(mc, 0)

    def _build_default_akai_presets(self) -> dict:
        """
        Construit les presets par défaut pour les 8 colonnes MEM (mc 0-7).

        Chaque LIGNE correspond à une couleur :
          Row 0 : Blanc   #ffffff
          Row 1 : Rouge   #ff0000
          Row 2 : Orange  #ff8800
          Row 3 : Jaune   #ffdd00
          Row 4 : Vert    #00ff00
          Row 5 : Cyan    #00dddd
          Row 6 : Bleu    #0000ff
          Row 7 : Magenta #ff00ff

        Chaque COLONNE correspond à une combinaison de groupes :
          MEM 1 (mc=0) : Tous les groupes
          MEM 2 (mc=1) : Face
          MEM 3 (mc=2) : Contre
          MEM 4 (mc=3) : LAT
          MEM 5 (mc=4) : Douches (douche1+2+3)
          MEM 6 (mc=5) : Face + LAT
          MEM 7 (mc=6) : Face + Contre
          MEM 8 (mc=7) : LAT + Contre
        """

        ROW_COLORS = [
            "#ffffff",  # Row 0 : Blanc
            "#ff0000",  # Row 1 : Rouge
            "#ff8800",  # Row 2 : Orange
            "#ffdd00",  # Row 3 : Jaune
            "#00ff00",  # Row 4 : Vert
            "#00dddd",  # Row 5 : Cyan
            "#0000ff",  # Row 6 : Bleu
            "#ff00ff",  # Row 7 : Magenta
        ]

        COL_GROUPS = [
            {"face", "douche1", "douche2", "douche3", "lat", "contre"},  # MEM 1 : Tous
            {"face"},                                                      # MEM 2 : Face
            {"contre"},                                                    # MEM 3 : Contre
            {"lat"},                                                       # MEM 4 : LAT
            {"douche1", "douche2", "douche3"},                            # MEM 5 : Douches
            {"face", "lat"},                                               # MEM 6 : Face + LAT
            {"face", "contre"},                                            # MEM 7 : Face + Contre
            {"lat", "contre"},                                             # MEM 8 : LAT + Contre
        ]

        def make_snapshot(color, active_groups):
            snapshot = []
            for fixture in self.projectors:
                grp = fixture.group
                if grp in active_groups:
                    snapshot.append({"group": grp, "base_color": color, "level": 100})
                else:
                    snapshot.append({"group": grp, "base_color": "#000000", "level": 0})
            return {"projectors": snapshot}

        memories      = [[None] * 8 for _ in range(8)]
        custom_colors = [[None] * 8 for _ in range(8)]

        for mc, groups in enumerate(COL_GROUPS):
            for row, color in enumerate(ROW_COLORS):
                memories[mc][row]      = make_snapshot(color, groups)
                custom_colors[mc][row] = color

        return {
            "memories": memories,
            "memory_custom_colors": custom_colors,
            "active_memory_pads": {},
        }

    def load_default_presets(self):
        """Charge (ou restaure) les 8 colonnes MEM par défaut."""
        reply = QMessageBox.question(
            self,
            tr("load_mem_title"),
            tr("load_mem_question"),
            QMessageBox.Yes | QMessageBox.Cancel
        )
        if reply != QMessageBox.Yes:
            return

        presets = self._build_default_akai_presets()

        # Stocker les données pour les 8 colonnes
        for mc in range(8):
            for mr in range(8):
                self.memories[mc][mr] = presets["memories"][mc][mr]
                c = presets["memory_custom_colors"][mc][mr]
                self.memory_custom_colors[mc][mr] = QColor(c) if c else None

        # Reconstruire l'affichage complet (rafraîchit MEM 5-8 quelle que soit la banque active)
        if hasattr(self, '_pads_container'):
            self._rebuild_akai_pads()
        self._activate_top_pads_default()
        # Synchroniser les LEDs physiques AKAI
        self.activate_default_white_pads()
        self._save_akai_config_auto()
        QMessageBox.information(
            self, tr("load_mem_success_title"),
            tr("load_mem_success_msg")
        )

    def clear_all_memories(self):
        """Efface toutes les mémoires des colonnes MEM1–MEM99."""
        reply = QMessageBox.warning(
            self,
            "Effacer toutes les mémoires",
            "Cette action est irréversible.\n\nToutes les mémoires (MEM 1 à 99) seront définitivement supprimées.\n\nContinuer ?",
            QMessageBox.Yes | QMessageBox.Cancel
        )
        if reply != QMessageBox.Yes:
            return

        for mc in range(_MEM_COL_MAX):
            for mr in range(8):
                self.memories[mc][mr] = None
                self.memory_custom_colors[mc][mr] = None

        self.active_memory_pads.clear()
        self._rebuild_akai_pads()

        # Éteindre les LEDs physiques de tous les pads mémoire sur l'AKAI
        if MIDI_AVAILABLE and hasattr(self, 'midi_handler') and self.midi_handler.midi_out:
            for fi, mc in self._bank_memory_slots():
                for mr in range(8):
                    note = (7 - mr) * 8 + fi
                    self.midi_handler.midi_out.send_message([0x90, note, 0])

        self._save_akai_config_auto()
        self._show_mem_toast("🗑️ Mémoires effacées")

    def load_default_effects(self):
        """Charge les effets par défaut sur les boutons E1-E9."""
        reply = QMessageBox.question(
            self,
            tr("load_fx_title"),
            tr("load_fx_question"),
            QMessageBox.Yes | QMessageBox.Cancel
        )
        if reply != QMessageBox.Yes:
            return

        from effect_editor import BUILTIN_EFFECTS

        # 9 effets bien différents les uns des autres
        DEFAULT_EFFECTS = [
            "Strobe Classique",  # E1 : stroboscopique pur
            "Chase Doux",        # E2 : chase fluide avec fade
            "Pulse Doux",        # E3 : respiration lente
            "Rainbow",           # E4 : arc-en-ciel décalé
            "Comète",            # E5 : comète avec trainée
            "Bascule",           # E6 : bascule pair/impair
            "Ping Pong",         # E7 : aller-retour bounce
            "Police",            # E8 : rouge/bleu alternance
            "Spectre",           # E9 : rainbow large et lent
        ]

        effects_by_name = {e["name"]: e for e in BUILTIN_EFFECTS}
        assigned = []
        for i, name in enumerate(DEFAULT_EFFECTS):
            eff = effects_by_name.get(name)
            if not eff:
                continue
            cfg = {
                "name":   name,
                "type":   eff.get("type", ""),
                "layers": eff["layers"],
            }
            self._on_effect_assigned(i, cfg)
            assigned.append(f"E{i+1} : {name}")

        self._save_effect_assignments()
        QMessageBox.information(
            self, tr("load_fx_success_title"),
            tr("load_fx_success_msg", list="\n".join(assigned))
        )

    def export_akai_config(self):
        """Exporte la configuration AKAI dans un fichier"""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export_akai_title"), "",
            tr("akai_cfg_filter"))
        if not path:
            return
        if not path.endswith('.akai.json'):
            path += '.akai.json'
        try:
            config = self._serialize_akai_config()
            with open(path, 'w') as f:
                json.dump(config, f, indent=2)
            QMessageBox.information(self, tr("export_ok_title"), tr("export_ok_msg"))
        except Exception as e:
            QMessageBox.critical(self, tr("err_save_title"), tr("export_err_msg", e=e))

    def import_akai_config(self):
        """Importe une configuration AKAI depuis un fichier"""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("import_akai_title"), "",
            tr("akai_cfg_filter"))
        if not path:
            return
        try:
            with open(path, 'r') as f:
                config = json.load(f)
            self._apply_akai_config(config)
            QMessageBox.information(self, tr("import_ok_title"), tr("import_ok_msg"))
        except Exception as e:
            QMessageBox.critical(self, tr("err_save_title"), tr("import_err_msg", e=e))

    # ==================== FIN CONFIG AKAI ====================

    def load_recent_files(self):
        """Charge la liste des fichiers recents"""
        try:
            recent_path = os.path.join(os.path.expanduser("~"), ".maestro_recent.json")
            if os.path.exists(recent_path):
                with open(recent_path, 'r') as f:
                    return json.load(f)
        except:
            pass
        return []

    def save_recent_files(self):
        """Sauvegarde la liste des fichiers recents"""
        try:
            recent_path = os.path.join(os.path.expanduser("~"), ".maestro_recent.json")
            with open(recent_path, 'w') as f:
                json.dump(self.recent_files, f)
        except:
            pass

    def add_recent_file(self, filepath):
        """Ajoute un fichier a la liste des recents"""
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
        self.recent_files.insert(0, filepath)
        self.recent_files = self.recent_files[:10]
        self.save_recent_files()
        self.update_recent_menu()

    def update_recent_menu(self):
        """Met a jour le menu des fichiers recents"""
        self.recent_menu.clear()
        if not self.recent_files:
            action = self.recent_menu.addAction(tr("menu_no_recent"))
            action.setEnabled(False)
            return
        for filepath in self.recent_files:
            if os.path.exists(filepath):
                filename = os.path.basename(filepath)
                action = self.recent_menu.addAction(filename)
                action.setData(filepath)
                action.triggered.connect(self.load_recent_file)

    def load_recent_file(self):
        """Charge un fichier depuis le menu recent"""
        action = self.sender()
        if action:
            filepath = action.data()
            self.load_show(filepath)

    def reconnect_midi(self):
        """Force la reconnexion MIDI"""
        if not MIDI_AVAILABLE:
            QMessageBox.information(self, tr("midi_unavail_title"), tr("midi_unavail_msg"))
            return

        try:
            self.midi_handler.connect_akai()
            if self.midi_handler.midi_in and self.midi_handler.midi_out:
                QTimer.singleShot(200, self.activate_default_white_pads)
                QTimer.singleShot(300, self.turn_off_all_effects)
                QTimer.singleShot(400, self._sync_faders_to_projectors)
                QMessageBox.information(self, tr("midi_reconnect_title"), tr("midi_reconnect_msg"))
        except Exception as e:
            QMessageBox.critical(self, tr("err_save_title"), tr("midi_err_msg", e=e))

    def open_light_editor(self, row=None):
        """Ouvre l'editeur de sequence lumiere"""
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()

        if row is not None:
            current_row = row
        else:
            current_row = self.seq.table.currentRow()

        if current_row < 0:
            QMessageBox.warning(self, tr("no_media_title"), tr("no_media_msg"))
            return

        item = self.seq.table.item(current_row, 1)
        if not item or not item.data(Qt.UserRole):
            return

        path = item.data(Qt.UserRole)

        # Bloquer si pause indefinie
        if path == "PAUSE":
            QMessageBox.warning(self, tr("rec_light_title"), tr("rec_light_need_dur"))
            return

        # Bloquer si image sans duree definie
        if media_icon(path) == "image":
            if current_row not in self.seq.image_durations:
                QMessageBox.warning(self, tr("rec_light_title"), tr("rec_light_need_dur2"))
                return

        editor = LightTimelineEditor(self, current_row)
        editor.exec()

    def _edit_current_volume(self):
        """Edite le volume du media selectionne (audio/video uniquement)"""
        row = self.seq.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, tr("no_media2_title"), tr("no_media2_msg"))
            return
        title_item = self.seq.table.item(row, 1)
        if not title_item:
            return
        path = title_item.data(Qt.UserRole)
        if path and media_icon(path) in ("audio", "video"):
            self.seq.edit_media_volume(row)
        else:
            QMessageBox.warning(self, tr("not_applicable_title"), tr("vol_not_applicable"))

    def _edit_current_duration(self):
        """Edite la duree de l'image ou de la pause selectionnee"""
        row = self.seq.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, tr("no_media2_title"), tr("no_elem_msg"))
            return
        title_item = self.seq.table.item(row, 1)
        if not title_item:
            return
        data = str(title_item.data(Qt.UserRole) or "")
        if data == "PAUSE" or data.startswith("PAUSE:"):
            self.seq.edit_pause_duration(row)
        elif media_icon(data) == "image":
            self.seq.edit_image_duration(row)
        else:
            QMessageBox.warning(self, tr("not_applicable_title"), tr("dur_not_applicable"))

    def _show_contact_dialog(self):
        self._show_mail_dialog(
            title=tr("contact_title"),
            icon="✉️",
            intro=tr("contact_intro"),
            email="nicolas@mystrow.fr",
            subject="Contact MyStrow",
            body="Bonjour,\n\n",
            btn_label=tr("contact_btn_label"),
        )

    def _show_idea_dialog(self):
        import urllib.request, urllib.parse, threading
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                                       QPushButton, QHBoxLayout, QLineEdit,
                                       QTextEdit, QFrame)
        from i18n import get_language

        FORMSPREE_FR = "https://formspree.io/f/xkopngjp"
        FORMSPREE_EN = "https://formspree.io/f/xdkooqka"
        endpoint = FORMSPREE_EN if get_language() == "en" else FORMSPREE_FR

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("idea_title"))
        dlg.setFixedWidth(420)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setStyleSheet("""
            QDialog   { background: #111; color: #e0e0e0; }
            QLabel    { background: transparent; }
            QLineEdit, QTextEdit {
                background: #1a1a1a; color: #e0e0e0;
                border: 1px solid #2a2a2a; border-radius: 6px;
                padding: 6px 10px; font-size: 12px;
            }
            QLineEdit:focus, QTextEdit:focus { border-color: #00d4ff55; }
        """)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(0)

        lbl_icon = QLabel("💡")
        lbl_icon.setAlignment(Qt.AlignCenter)
        lbl_icon.setStyleSheet("font-size: 34px; padding-bottom: 8px;")
        root.addWidget(lbl_icon)

        lbl_title = QLabel(tr("idea_title"))
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff; padding-bottom: 6px;")
        root.addWidget(lbl_title)

        lbl_intro = QLabel(tr("idea_intro"))
        lbl_intro.setAlignment(Qt.AlignCenter)
        lbl_intro.setWordWrap(True)
        lbl_intro.setStyleSheet("color: #888; font-size: 11px; padding-bottom: 16px;")
        root.addWidget(lbl_intro)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #222; max-height: 1px; margin-bottom: 14px;")
        root.addWidget(sep)

        field_name = QLineEdit()
        field_name.setPlaceholderText(tr("idea_field_name"))
        field_name.setFixedHeight(34)
        root.addWidget(field_name)
        root.addSpacing(8)

        field_email = QLineEdit()
        field_email.setPlaceholderText(tr("idea_field_email"))
        field_email.setFixedHeight(34)
        root.addWidget(field_email)
        root.addSpacing(8)

        field_msg = QTextEdit()
        field_msg.setPlaceholderText(tr("idea_field_message"))
        field_msg.setFixedHeight(100)
        root.addWidget(field_msg)
        root.addSpacing(6)

        # Remettre la bordure normale dès que l'utilisateur retape
        field_name.textChanged.connect(lambda: field_name.setStyleSheet(""))
        field_email.textChanged.connect(lambda: field_email.setStyleSheet(""))
        field_msg.textChanged.connect(lambda: field_msg.setStyleSheet(""))

        lbl_status = QLabel("")
        lbl_status.setAlignment(Qt.AlignCenter)
        lbl_status.setWordWrap(True)
        lbl_status.setStyleSheet("font-size: 11px; color: #888; padding: 4px 0;")
        root.addWidget(lbl_status)
        root.addSpacing(10)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_send = QPushButton(tr("idea_btn_label"))
        btn_send.setFixedHeight(38)
        btn_send.setCursor(Qt.PointingHandCursor)
        btn_send.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #0099bb, stop:1 #00d4ff);
                color: #000; font-weight: bold; font-size: 12px;
                border: none; border-radius: 8px; padding: 0 20px;
            }
            QPushButton:hover  { background: #00d4ff; }
            QPushButton:disabled { background: #333; color: #666; }
        """)

        btn_close = QPushButton(tr("btn_close"))
        btn_close.setFixedHeight(38)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: #1a1a1a; color: #666; font-size: 12px;
                border: 1px solid #2a2a2a; border-radius: 8px; padding: 0 20px;
            }
            QPushButton:hover { background: #222; color: #aaa; border-color: #444; }
        """)
        btn_close.clicked.connect(dlg.accept)

        _ERR_BORDER = "background:#1a1a1a; color:#e0e0e0; border:1px solid #ff4444; border-radius:6px; padding:6px 10px; font-size:12px;"
        _OK_BORDER  = "background:#1a1a1a; color:#e0e0e0; border:1px solid #2a2a2a; border-radius:6px; padding:6px 10px; font-size:12px;"

        def _mark(widget, error):
            widget.setStyleSheet(_ERR_BORDER if error else _OK_BORDER)

        def _send():
            import re
            name    = field_name.text().strip()
            email   = field_email.text().strip()
            message = field_msg.toPlainText().strip()

            _mark(field_name,  not name)
            _mark(field_email, not email)
            _mark(field_msg,   not message)

            if not name:
                lbl_status.setStyleSheet("font-size: 11px; color: #ff6666; padding: 4px 0;")
                lbl_status.setText(tr("idea_error_name"))
                field_name.setFocus()
                return
            if not email:
                lbl_status.setStyleSheet("font-size: 11px; color: #ff6666; padding: 4px 0;")
                lbl_status.setText(tr("idea_error_email_empty"))
                field_email.setFocus()
                return
            if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', email):
                _mark(field_email, True)
                lbl_status.setStyleSheet("font-size: 11px; color: #ff6666; padding: 4px 0;")
                lbl_status.setText(tr("idea_error_email"))
                field_email.setFocus()
                return
            if not message:
                lbl_status.setStyleSheet("font-size: 11px; color: #ff6666; padding: 4px 0;")
                lbl_status.setText(tr("idea_error_message"))
                field_msg.setFocus()
                return
            btn_send.setEnabled(False)
            lbl_status.setStyleSheet("font-size: 11px; color: #888; padding: 4px 0;")
            lbl_status.setText(tr("idea_sending"))

            from core import VERSION
            payload = urllib.parse.urlencode({
                "name": name,
                "email": email,
                "sujet": "Idée MyStrow",
                "version": VERSION,
                "message": message,
            }).encode()

            from PySide6.QtCore import QObject, Signal as _Signal

            class _Notifier(QObject):
                result = _Signal(bool)

            notifier = _Notifier()
            dlg._notifier = notifier   # empêche le GC de collecter notifier avant la fin du thread

            _err_detail = [""]

            def _on_result(ok):
                if ok:
                    lbl_status.setStyleSheet("font-size: 11px; color: #00d4ff; padding: 4px 0;")
                    lbl_status.setText(tr("idea_success"))
                    btn_send.setEnabled(False)
                else:
                    detail = f"  ({_err_detail[0]})" if _err_detail[0] else ""
                    lbl_status.setStyleSheet("font-size: 11px; color: #ff6666; padding: 4px 0;")
                    lbl_status.setText(tr("idea_error_send") + detail)
                    btn_send.setEnabled(True)

            notifier.result.connect(_on_result)

            def _do_request():
                try:
                    req = urllib.request.Request(
                        endpoint,
                        data=payload,
                        headers={"Accept": "application/json",
                                 "Content-Type": "application/x-www-form-urlencoded",
                                 "User-Agent": "MyStrow"},
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        ok = 200 <= resp.status < 300
                except Exception as e:
                    ok = False
                    _err_detail[0] = str(e)
                    print(f"[IdeaForm] erreur envoi : {e}")
                try:
                    notifier.result.emit(ok)
                except Exception:
                    pass

            threading.Thread(target=_do_request, daemon=True).start()

        btn_send.clicked.connect(_send)
        btn_row.addWidget(btn_send)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        dlg.exec()

    def _show_mail_dialog(self, title, icon, intro, email, subject, body, btn_label):
        import urllib.parse, webbrowser
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setFixedWidth(380)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setStyleSheet("""
            QDialog { background: #111; color: #e0e0e0; }
            QLabel  { background: transparent; }
        """)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(30, 28, 30, 24)
        root.setSpacing(0)

        # Icône + titre
        lbl_icon = QLabel(icon)
        lbl_icon.setAlignment(Qt.AlignCenter)
        lbl_icon.setStyleSheet("font-size: 38px; padding-bottom: 10px;")
        root.addWidget(lbl_icon)

        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff; padding-bottom: 16px;")
        root.addWidget(lbl_title)

        # Séparateur
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #222; max-height: 1px; margin-bottom: 18px;")
        root.addWidget(sep)

        # Texte d'intro
        lbl_intro = QLabel(intro)
        lbl_intro.setAlignment(Qt.AlignCenter)
        lbl_intro.setWordWrap(True)
        lbl_intro.setStyleSheet("color: #aaa; font-size: 12px; line-height: 1.5; padding-bottom: 18px;")
        root.addWidget(lbl_intro)

        # Adresse email
        lbl_email = QLabel(email)
        lbl_email.setAlignment(Qt.AlignCenter)
        lbl_email.setStyleSheet(
            "color: #00d4ff; font-size: 14px; font-weight: bold;"
            " padding: 10px 16px; background: #0a1820;"
            " border: 1px solid #00d4ff33; border-radius: 8px; margin-bottom: 22px;"
        )
        root.addWidget(lbl_email)

        # Boutons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_write = QPushButton(btn_label)
        btn_write.setFixedHeight(38)
        btn_write.setCursor(Qt.PointingHandCursor)
        btn_write.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #0099bb, stop:1 #00d4ff);
                color: #000; font-weight: bold; font-size: 12px;
                border: none; border-radius: 8px; padding: 0 20px;
            }
            QPushButton:hover { background: #00d4ff; }
        """)
        def _open_mail():
            params = urllib.parse.urlencode({"subject": subject, "body": body})
            webbrowser.open(f"mailto:{email}?{params}")
        btn_write.clicked.connect(_open_mail)

        btn_close = QPushButton(tr("btn_close"))
        btn_close.setFixedHeight(38)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: #1a1a1a; color: #666; font-size: 12px;
                border: 1px solid #2a2a2a; border-radius: 8px; padding: 0 20px;
            }
            QPushButton:hover { background: #222; color: #aaa; border-color: #444; }
        """)
        btn_close.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_write)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        dlg.exec()

    # ── Contrôleur Tablette ───────────────────────────────────────────────────

    def _start_tablet_server(self):
        """Ouvre le dialog contrôleur tablette (on/off + QR code)."""
        import tablet_server as _ts
        # Le dialog se reconstruit à chaque ouverture selon l'état courant
        self._open_tablet_dialog(_ts)

    def _open_tablet_dialog(self, _ts):
        """Construit et affiche le dialog tablette selon l'état courant."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                       QLabel, QPushButton)
        from PySide6.QtGui import QPixmap

        running = _ts.is_running()

        # ── Générer le QR code avec Qt (sans PIL) ────────────────────────────
        qr_pixmap = None
        qr_error  = ""
        url = ""
        if running:
            ip  = _ts.get_local_ip()
            url = f"http://{ip}:{_ts.TABLET_PORT}"
            print(f"[Tablet] IP={ip}  URL={url}")
            try:
                try:
                    import qrcode as _qr
                except ImportError:
                    print("[Tablet] qrcode absent — installation...")
                    import subprocess, sys
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", "--quiet", "qrcode"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    import qrcode as _qr
                print(f"[Tablet] qrcode ok")
                from PySide6.QtGui import QPainter, QColor as _QColor
                qr = _qr.QRCode(error_correction=_qr.constants.ERROR_CORRECT_L,
                                 box_size=1, border=4)
                qr.add_data(url)
                qr.make(fit=True)
                matrix = qr.modules
                n = len(matrix)
                print(f"[Tablet] QR matrix size: {n}x{n}")
                SZ = 220
                cell = max(1, SZ // n)
                img_sz = cell * n
                pix = QPixmap(img_sz, img_sz)
                pix.fill(_QColor("white"))
                painter = QPainter(pix)
                painter.setPen(Qt.NoPen)
                painter.setBrush(_QColor("black"))
                for r, row in enumerate(matrix):
                    for c, val in enumerate(row):
                        if val:
                            painter.drawRect(c * cell, r * cell, cell, cell)
                painter.end()
                qr_pixmap = pix.scaled(220, 220, Qt.KeepAspectRatio,
                                       Qt.FastTransformation)
                print(f"[Tablet] QR pixmap ok, isNull={qr_pixmap.isNull()}")
            except Exception as e:
                import traceback
                qr_error = str(e)
                print(f"[Tablet] QR error: {e}")
                traceback.print_exc()

        # ── Dialog ────────────────────────────────────────────────────────────
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("tablet_title"))
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setStyleSheet("background:#111;")

        root = QVBoxLayout(dlg)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        # Titre
        t = QLabel("📱  " + tr("tablet_title"))
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size:15px;font-weight:bold;color:#fff;background:transparent;")
        root.addWidget(t)

        # Statut
        s = QLabel("● ACTIF" if running else "● INACTIF")
        s.setAlignment(Qt.AlignCenter)
        s.setStyleSheet("font-size:11px;letter-spacing:2px;background:transparent;"
                        f"color:{'#00d4ff' if running else '#555'};")
        root.addWidget(s)

        if running:
            # QR code — QLabel avec pixmap PNG chargé depuis mémoire
            lbl_qr = QLabel()
            lbl_qr.setAlignment(Qt.AlignCenter)
            lbl_qr.setStyleSheet("background:#ffffff; border-radius:8px; padding:6px;")
            if qr_pixmap:
                lbl_qr.setPixmap(qr_pixmap)
                lbl_qr.setFixedSize(qr_pixmap.width() + 16, qr_pixmap.height() + 16)
            else:
                lbl_qr.setText(f"QR indisponible\n{qr_error}" if qr_error else "QR indisponible")
                lbl_qr.setWordWrap(True)
                lbl_qr.setStyleSheet("color:#ff6644; background:#1a0a0a; padding:8px; font-size:9px;")
            h = QHBoxLayout()
            h.addStretch(); h.addWidget(lbl_qr); h.addStretch()
            root.addLayout(h)

            # URL
            u = QLabel(url)
            u.setAlignment(Qt.AlignCenter)
            u.setStyleSheet("color:#00d4ff;font-size:13px;font-weight:bold;"
                            "padding:8px;background:#0a1820;"
                            "border:1px solid #00d4ff44;border-radius:7px;")
            root.addWidget(u)

            # Avertissement réseau
            w = QLabel(tr("tablet_same_network"))
            w.setAlignment(Qt.AlignCenter)
            w.setWordWrap(True)
            w.setStyleSheet("color:#aa7700;font-size:10px;padding:7px;"
                            "background:#1a1400;border:1px solid #3a2e00;border-radius:6px;")
            root.addWidget(w)

            # Copier
            btn_copy = QPushButton(tr("tablet_copy"))
            btn_copy.setFixedHeight(34)
            btn_copy.setCursor(Qt.PointingHandCursor)
            btn_copy.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                                   "stop:0 #0099bb,stop:1 #00d4ff);color:#000;font-weight:bold;"
                                   "font-size:11px;border:none;border-radius:7px;}"
                                   "QPushButton:hover{background:#00d4ff;}")
            def _copy():
                QApplication.clipboard().setText(url)
                btn_copy.setText(tr("tablet_copied"))
                QTimer.singleShot(1500, lambda: btn_copy.setText(tr("tablet_copy")))
            btn_copy.clicked.connect(_copy)
            root.addWidget(btn_copy)

        # Bouton toggle
        if running:
            btn_tog = QPushButton("⏹  Désactiver")
            btn_tog.setStyleSheet("QPushButton{background:#2a0a0a;color:#ff5555;"
                                  "font-weight:bold;font-size:13px;"
                                  "border:1px solid #ff555533;border-radius:8px;}"
                                  "QPushButton:hover{background:#3a1010;}")
        else:
            btn_tog = QPushButton("▶  Activer")
            btn_tog.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                                  "stop:0 #005566,stop:1 #007799);color:#fff;"
                                  "font-weight:bold;font-size:13px;border:none;border-radius:8px;}"
                                  "QPushButton:hover{background:#0099bb;}")
        btn_tog.setFixedHeight(44)
        btn_tog.setCursor(Qt.PointingHandCursor)
        root.addWidget(btn_tog)

        # Fermer
        btn_close = QPushButton(tr("btn_close"))
        btn_close.setFixedHeight(34)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("QPushButton{background:#1a1a1a;color:#666;font-size:11px;"
                                "border:1px solid #2a2a2a;border-radius:7px;}"
                                "QPushButton:hover{background:#222;color:#aaa;border-color:#444;}")
        btn_close.clicked.connect(dlg.accept)
        root.addWidget(btn_close)

        def _toggle():
            if _ts.is_running():
                _ts._running = False
                self.midi_handler.led_observer = None
            else:
                if not _ts.is_available():
                    from PySide6.QtWidgets import QProgressDialog
                    import threading as _thr
                    prog = QProgressDialog(tr("tablet_installing"), None, 0, 0, dlg)
                    prog.setWindowTitle(tr("tablet_title"))
                    prog.setWindowModality(Qt.WindowModal)
                    prog.setMinimumDuration(0)
                    prog.setValue(0)
                    prog.show()
                    _result = [None]
                    _t = _thr.Thread(
                        target=lambda: _result.__setitem__(0, _ts._auto_install()),
                        daemon=True,
                    )
                    _t.start()
                    while _t.is_alive():
                        QApplication.processEvents()
                        _t.join(timeout=0.05)
                    prog.close()
                    if not _result[0]:
                        QMessageBox.warning(dlg, tr("tablet_title"), tr("tablet_error_pkg"))
                        return
                try:
                    _ts.start()
                except Exception as e:
                    QMessageBox.critical(dlg, tr("tablet_title"), str(e))
                    return
                self._setup_tablet_led_observer()
                self._push_initial_tablet_state()
            # Fermer et rouvrir le dialog avec le nouvel état
            dlg.accept()
            self._open_tablet_dialog(_ts)

        btn_tog.clicked.connect(_toggle)
        dlg.exec()

    def _setup_tablet_led_observer(self):
        """Installe le callback qui pousse les changements LED vers la tablette."""
        import tablet_server as _ts

        def _on_led(row, col, vel, bright):
            if not _ts.is_running():
                return
            if col == 8:
                # Boutons d'effet : rouge si actif, noir sinon
                color = "#cc2200" if vel > 0 else "#000000"
                _ts.push_effect(row, vel > 0)
            else:
                pad = self.pads.get((row, col))
                if pad:
                    qc = pad.property("base_color")
                    color = qc.name() if (qc and isinstance(qc, QColor)) else "#000000"
                else:
                    color = "#000000"
                _ts.push_pad(row, col, color, bright)

        self.midi_handler.led_observer = _on_led

    def _push_initial_tablet_state(self):
        """Pousse l'état courant complet (pads, faders, séquenceur, cartouches) vers la tablette."""
        import tablet_server as _ts
        # Faders
        for idx, fader in self.faders.items():
            _ts.push_fader(idx, fader.value)
        # Pads
        for (row, col), pad in self.pads.items():
            qc = pad.property("base_color")
            color = qc.name() if (qc and isinstance(qc, QColor)) else "#000000"
            bright = pad.property("bright_pct") or 100
            _ts.push_pad(row, col, color, bright)
        # Effets
        for row, btn in enumerate(self.effect_buttons):
            _ts.push_effect(row, getattr(btn, 'active', False))
        # Séquenceur
        self._push_seq_state_to_tablet(_ts)
        # Cartouches
        self._push_cart_state_to_tablet(_ts)
        # Projecteurs
        _ts.push_projectors(self._proj_snapshot())
        # Layout colonnes AKAI + état REC
        _ts.push_layout(self._custom_bank_slots)
        _ts.push_rec_state(self._mem_rec_mode)

    def _push_seq_state_to_tablet(self, _ts=None):
        """Pousse la liste complète du séquenceur et la ligne courante."""
        if _ts is None:
            import tablet_server as _ts
        if not _ts.is_running():
            return
        items = []
        for r in range(self.seq.table.rowCount()):
            title_item = self.seq.table.item(r, 1)
            title = title_item.text() if title_item else ""
            dtype = str(title_item.data(Qt.UserRole) or "") if title_item else ""
            if dtype.startswith("PAUSE"):
                itype = "pause"
            elif dtype.startswith("TEMPO:"):
                itype = "tempo"
            else:
                itype = "media"
            items.append({"title": title, "type": itype})
        try:
            from PySide6.QtMultimedia import QMediaPlayer as _QMP
            playing = self.player.playbackState() == _QMP.PlaybackState.Playing
        except Exception:
            playing = False
        _ts.push_seq(self.seq.current_row, items, playing)

    def _push_cart_state_to_tablet(self, _ts=None):
        """Pousse l'état des 4 cartouches."""
        if _ts is None:
            import tablet_server as _ts
        if not _ts.is_running():
            return
        for i, cart in enumerate(self.cartouches):
            _ts.push_cart(i, cart.media_title or "", cart.state)

    def _proj_snapshot(self) -> list:
        """Retourne la liste des projecteurs sérialisable pour la tablette."""
        from plan_de_feu import _DEFAULT_POSITIONS
        # Compter les projecteurs par groupe pour le calcul de position par défaut
        group_lists: dict = {}
        for i, p in enumerate(self.projectors):
            group_lists.setdefault(p.group, []).append(i)
        out = []
        for i, p in enumerate(self.projectors):
            if p.canvas_x is not None and p.canvas_y is not None:
                dx, dy = p.canvas_x, p.canvas_y
            else:
                g_list = group_lists[p.group]
                li = g_list.index(i)
                n  = len(g_list)
                pos_fn = _DEFAULT_POSITIONS.get(p.group, lambda li, n: (0.5, 0.5))
                dx, dy = pos_fn(li, n)
            out.append({
                "name":       p.name,
                "group":      p.group,
                "color":      p.color.name() if p.color else "#000000",
                "base_color": p.base_color.name() if p.base_color else "#ffffff",
                "level":      p.level,
                "muted":      p.muted,
                "strobe":     getattr(p, 'strobe_speed', 0),
                "x":          dx,
                "y":          dy,
            })
        return out

    def _drain_tablet_events(self):
        """Appelé toutes les 50 ms — traite les events envoyés par la tablette."""
        import tablet_server as _ts
        if not _ts.is_running():
            return
        try:
            while True:
                ev = _ts.event_queue.get_nowait()
                etype = ev["type"]
                if etype == "pad":
                    self.on_midi_pad(ev["row"], ev["col"])
                elif etype == "fader":
                    # La tablette envoie 0-100, on_midi_fader attend 0-127
                    raw = int(ev["value"] / 100.0 * 127)
                    self.on_midi_fader(ev["idx"], raw)
                elif etype == "effect":
                    # Col 8 = boutons effets
                    self.on_midi_pad(ev["row"], 8)
                elif etype == "transport":
                    action = ev.get("action", "")
                    if action == "play_pause":
                        self.toggle_play()
                    elif action == "next":
                        self.seq.play_row(self.seq.current_row + 1)
                    elif action == "prev":
                        self.seq.play_row(self.seq.current_row - 1)
                elif etype == "cartouche":
                    idx = ev.get("idx", -1)
                    if 0 <= idx < len(self.cartouches):
                        self.on_cartouche_clicked(idx)
                elif etype == "seq_row":
                    row = ev.get("row", -1)
                    if row >= 0:
                        self.seq.play_row(row)
                elif etype == "proj_level":
                    idx = ev.get("idx", -1)
                    val = int(ev.get("value", 0))
                    if 0 <= idx < len(self.projectors) and hasattr(self, 'plan_de_feu'):
                        self.plan_de_feu.set_projector_dimmer(self.projectors[idx], val)
                    elif 0 <= idx < len(self.projectors):
                        self.projectors[idx].set_level(val)
                        self.send_dmx_update()
                elif etype == "proj_color":
                    idx = ev.get("idx", -1)
                    hex_color = ev.get("color", "#ffffff")
                    if 0 <= idx < len(self.projectors) and hasattr(self, 'plan_de_feu'):
                        proj = self.projectors[idx]
                        from plan_de_feu import _DEFAULT_POSITIONS
                        group_lists: dict = {}
                        for j, q in enumerate(self.projectors):
                            group_lists.setdefault(q.group, []).append(j)
                        g_list = group_lists[proj.group]
                        li = g_list.index(idx)
                        targets = [(proj, proj.group, li)]
                        self.plan_de_feu._apply_color_to_targets(targets, QColor(hex_color))
                        self.plan_de_feu.mark_dirty()
                elif etype == "proj_strobe":
                    idx = ev.get("idx", -1)
                    val = int(ev.get("value", 0))
                    if 0 <= idx < len(self.projectors):
                        self.projectors[idx].strobe_speed = val
                        self.send_dmx_update()
                        if hasattr(self, 'plan_de_feu'):
                            self.plan_de_feu.mark_dirty()
                elif etype == "proj_mute":
                    idx = ev.get("idx", -1)
                    if 0 <= idx < len(self.projectors):
                        self.projectors[idx].muted = ev.get("muted", False)
                        self.send_dmx_update()
                        if hasattr(self, 'plan_de_feu'):
                            self.plan_de_feu.mark_dirty()
                elif etype == "scene_clear":
                    if hasattr(self, 'plan_de_feu'):
                        self.plan_de_feu._clear_plan_de_feu()
                elif etype == "scene_select_all":
                    if hasattr(self, 'plan_de_feu'):
                        self.plan_de_feu._select_all()
                elif etype == "clear":
                    self._clear_akai_state()
                elif etype == "rec_toggle":
                    self._toggle_mem_rec_mode()
                elif etype == "open_params":
                    self._open_akai_layout_editor()
        except Exception:
            pass

        # ── Surveillance des changements séquenceur/cartouches ────────────────
        try:
            seq_count = self.seq.table.rowCount()
            # Hash léger du contenu : (count, tuple des titres)
            _titles = tuple(
                (self.seq.table.item(r, 1).text() if self.seq.table.item(r, 1) else "")
                for r in range(seq_count)
            )
            seq_sig = (seq_count, _titles)
            if getattr(self, '_tablet_last_seq_sig', None) != seq_sig:
                self._tablet_last_seq_sig = seq_sig
                self._push_seq_state_to_tablet(_ts)

            try:
                from PySide6.QtMultimedia import QMediaPlayer as _QMP
                playing = self.player.playbackState() == _QMP.PlaybackState.Playing
            except Exception:
                playing = False
            seq_row = self.seq.current_row
            if (getattr(self, '_tablet_last_seq_row', -99) != seq_row
                    or getattr(self, '_tablet_last_seq_playing', None) != playing):
                self._tablet_last_seq_row = seq_row
                self._tablet_last_seq_playing = playing
                _ts.push_seq_row(seq_row, playing)

            if not hasattr(self, '_tablet_last_carts'):
                self._tablet_last_carts = {}
            for i, cart in enumerate(self.cartouches):
                key = (cart.media_title or "", cart.state)
                if self._tablet_last_carts.get(i) != key:
                    self._tablet_last_carts[i] = key
                    _ts.push_cart(i, cart.media_title or "", cart.state)

            # Projecteurs — mise à jour couleurs/niveaux
            snap = self._proj_snapshot()
            colors_only = [{"color": p["color"], "base_color": p.get("base_color","#ffffff"),
                            "level": p["level"], "muted": p["muted"],
                            "strobe": p.get("strobe", 0)} for p in snap]
            if getattr(self, '_tablet_last_proj_colors', None) != colors_only:
                self._tablet_last_proj_colors = colors_only
                _ts.push_projectors_colors(snap)
        except Exception:
            pass

    # ── Fin contrôleur tablette ───────────────────────────────────────────────

    # ── Contrôleur Stream Deck ────────────────────────────────────────────────
    #
    # Fonctionnement général :
    #   1. MyStrow démarre un serveur HTTP local (StreamDeckAPIServer, port 8765)
    #      qui expose une API REST : /api/play, /api/next, /api/state, etc.
    #
    #   2. Le plugin Stream Deck (streamdeck_plugin/com.mystrow.streamdeck.sdPlugin)
    #      tourne en arrière-plan dans le logiciel Elgato Stream Deck (Node.js).
    #      Il se connecte à l'API MyStrow toutes les 2 secondes pour lire l'état
    #      (lecture en cours, niveaux faders, effets actifs…) et met à jour
    #      l'affichage des boutons physiques.
    #
    #   3. Quand l'utilisateur appuie sur un bouton du Stream Deck, le plugin
    #      envoie une requête POST à l'API MyStrow (ex. POST /api/play).
    #      StreamDeckAPIServer reçoit la requête et appelle la méthode Qt correspondante
    #      sur MainWindow (on_midi_pad, set_proj_level, etc.).
    #
    #   4. Installation du plugin :
    #      - Menu Connexion > Stream Deck > "Installer le plugin"
    #      - Copie le dossier com.mystrow.streamdeck.sdPlugin dans
    #        %APPDATA%/Elgato/StreamDeck/Plugins/
    #      - Redémarrer le logiciel Elgato Stream Deck pour que les actions apparaissent.
    #
    #   Actions disponibles : Play/Pause, Suivant, Précédent, Blackout,
    #                         Effet lumière, Niveau fader, Mute, Scène mémoire.

    def _start_streamdeck_dialog(self):
        """Ouvre le dialog Stream Deck : statut API + installation plugin."""
        import shutil
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                       QLabel, QPushButton, QFrame)
        from streamdeck_api import STREAMDECK_API_PORT

        base_dir = Path(__file__).parent
        plugin_src = base_dir / "streamdeck_plugin" / "com.mystrow.streamdeck.sdPlugin"
        appdata = Path(os.environ.get("APPDATA", ""))
        plugin_dst = appdata / "Elgato" / "StreamDeck" / "Plugins" / "com.mystrow.streamdeck.sdPlugin"

        is_installed = plugin_dst.exists()
        src_available = plugin_src.exists()
        server_running = (hasattr(self, '_streamdeck_server')
                          and self._streamdeck_server is not None
                          and self._streamdeck_server._server is not None)

        dlg = QDialog(self)
        dlg.setWindowTitle("Stream Deck")
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setStyleSheet("background:#111;")
        dlg.setFixedWidth(340)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(20, 22, 20, 20)
        root.setSpacing(12)

        # ── Titre ──────────────────────────────────────────────────────────────
        t = QLabel("Stream Deck")
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size:17px;font-weight:bold;color:#fff;background:transparent;"
                        "letter-spacing:1px;")
        root.addWidget(t)

        # ── Indicateurs de statut ─────────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(10)

        def _pill(label, active, color_on="#00cc66", color_off="#2a2a2a", text_off=None):
            c = color_on if active else color_off
            tc = "#fff" if active else "#666"
            lbl = QLabel(label if active else (text_off or label))
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedHeight(28)
            lbl.setStyleSheet(
                f"background:{c};color:{tc};border-radius:14px;"
                f"font-size:10px;font-weight:bold;padding:0 10px;"
                f"letter-spacing:1px;"
            )
            return lbl

        api_pill  = _pill("● CONNECTÉ", server_running, "#00cc66", "#1a1a1a", "● HORS LIGNE")
        plug_pill = _pill("● INSTALLÉ",  is_installed,  "#0099dd", "#1a1a1a", "● NON INSTALLÉ")
        row.addWidget(api_pill)
        row.addWidget(plug_pill)
        root.addLayout(row)

        # ── Séparateur ────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2a2a2a;")
        root.addWidget(sep)

        # ── Bouton installer / réinstaller ────────────────────────────────────
        if src_available:
            btn_label = ("↺  Réinstaller" if is_installed else "  Installer le plugin")
            btn_install = QPushButton(btn_label)
            btn_install.setFixedHeight(40)
            btn_install.setCursor(Qt.PointingHandCursor)
            if is_installed:
                btn_install.setStyleSheet(
                    "QPushButton{background:#1e2a35;color:#00aadd;border:1px solid #00aadd44;"
                    "border-radius:8px;font-size:12px;font-weight:bold;}"
                    "QPushButton:hover{background:#253545;color:#00ccff;border-color:#00ccff88;}")
            else:
                btn_install.setStyleSheet(
                    "QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                    "stop:0 #005588,stop:1 #0077bb);color:#fff;border:none;"
                    "border-radius:8px;font-size:13px;font-weight:bold;}"
                    "QPushButton:hover{background:#0088cc;}")

            def _do_install():
                try:
                    if plugin_dst.exists():
                        shutil.rmtree(plugin_dst)
                    shutil.copytree(str(plugin_src), str(plugin_dst))
                    QMessageBox.information(dlg, "Stream Deck", tr("sd_install_ok"))
                    dlg.accept()
                    self._start_streamdeck_dialog()
                except Exception as exc:
                    QMessageBox.critical(dlg, "Stream Deck",
                                         tr("sd_install_err").format(err=str(exc)))

            btn_install.clicked.connect(_do_install)
            root.addWidget(btn_install)

        # ── Note de fonctionnement ────────────────────────────────────────────
        if is_installed:
            info_text = (
                "Le plugin est installé.\n\n"
                "Ouvrez le logiciel Elgato Stream Deck\n"
                "et recherchez MyStrow dans la liste\n"
                "de la colonne de droite."
            )
        else:
            info_text = (
                "Il vous faudra le logiciel StreamDeck installé.\n\n"
                "Installez le plugin, réouvrez StreamDeck,\n"
                "puis recherchez MyStrow dans la liste\n"
                "de la colonne de droite."
            )
        info = QLabel(info_text)
        info.setAlignment(Qt.AlignCenter)
        info.setWordWrap(True)
        info.setStyleSheet(
            "color:#555;font-size:9px;line-height:1.4;"
            "padding:8px 4px 2px 4px;background:transparent;"
        )
        root.addWidget(info)

        # ── Note redémarrage (uniquement si plugin déjà installé) ─────────────
        if is_installed:
            note = QLabel(tr("sd_restart_note"))
            note.setAlignment(Qt.AlignCenter)
            note.setWordWrap(True)
            note.setStyleSheet("color:#444;font-size:9px;padding:2px;background:transparent;")
            root.addWidget(note)

        btn_close = QPushButton("Fermer")
        btn_close.setFixedHeight(34)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            "QPushButton{background:#1a1a1a;color:#666;font-size:11px;"
            "border:1px solid #2a2a2a;border-radius:7px;}"
            "QPushButton:hover{background:#222;color:#aaa;border-color:#444;}")
        btn_close.clicked.connect(dlg.accept)
        root.addWidget(btn_close)

        dlg.exec()

    # ── Fin contrôleur Stream Deck ────────────────────────────────────────────

    def show_about(self):
        """Ouvre le dialogue A propos / mises à jour"""
        AboutDialog(self).exec()

    def _show_tutorials_dialog(self):
        from tutorials_dialog import TutorialsDialog
        TutorialsDialog(self).exec()

    def _change_language(self, lang: str):
        set_language(lang)
        label = "Français" if lang == "fr" else "English"
        QMessageBox.information(self, tr("lang_changed_title"), tr("lang_changed_msg", label=label))

    def on_update_available(self, version, exe_url, hash_url, sig_url=""):
        """Signal du checker async - montre la barre verte"""
        self.update_bar.set_info(version, exe_url, hash_url, sig_url)
        self.update_bar.show()

    def _on_update_later(self):
        """Bouton Plus tard - reminder 24h"""
        UpdateChecker.save_reminder(self.update_bar.version)
        self.update_bar.hide()

    def _on_update_now(self):
        """Bouton Mettre a jour - telechargement"""
        download_update(self,
            self.update_bar.version,
            self.update_bar.exe_url,
            self.update_bar.hash_url,
            self.update_bar.sig_url)

    # ==================== LICENCE ====================

    def _setup_video_watermark(self):
        """Ajoute un watermark flottant sur le preview video integre"""
        if self._license.watermark_required:
            self._video_watermark = QLabel(self.video_stack)
            self._video_watermark.setAlignment(Qt.AlignCenter)
            self._video_watermark.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._update_video_watermark()
            self._video_watermark.show()
            self._video_watermark.raise_()
        else:
            self._video_watermark = None

    def _update_video_watermark(self):
        """Met a jour le pixmap du watermark video"""
        if not hasattr(self, '_video_watermark') or not self._video_watermark:
            return
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Mystrow_blanc.png")
        if os.path.exists(logo_path):
            px = QPixmap(logo_path)
            target_w = max(150, int(self.video_stack.width() * 0.3))
            scaled = px.scaledToWidth(target_w, Qt.SmoothTransformation)
            result = QPixmap(scaled.size())
            result.fill(Qt.transparent)
            painter = QPainter(result)
            painter.setOpacity(0.4)
            painter.drawPixmap(0, 0, scaled)
            painter.end()
            self._video_watermark.setPixmap(result)
            # Centrer
            x = (self.video_stack.width() - scaled.width()) // 2
            y = (self.video_stack.height() - scaled.height()) // 2
            self._video_watermark.setGeometry(x, y, scaled.width(), scaled.height())

    def _apply_license_banner(self):
        """Affiche ou cache la banniere selon l'etat et la dismissal."""
        import json, os, time
        state = self._license.state
        days  = self._license.days_remaining
        expired = state in (LicenseState.TRIAL_EXPIRED, LicenseState.LICENSE_EXPIRED,
                            LicenseState.INVALID, LicenseState.NOT_ACTIVATED)

        # Licence active sans alerte → cacher
        if state == LicenseState.LICENSE_ACTIVE and not self._license.show_warning:
            self._license_banner.hide()
            return

        # Essai : toujours afficher a chaque demarrage
        is_trial = state == LicenseState.TRIAL_ACTIVE

        # Verifier si l'utilisateur a deja ferme la banniere (licence payante uniquement)
        if not expired and not is_trial:
            dismiss_file = os.path.join(os.path.expanduser("~"), ".mystrow_banner_dismiss.json")
            try:
                with open(dismiss_file) as f:
                    data = json.load(f)
                dismissed_until = data.get("until", 0)
                # Respecter le dismiss sauf si on est a J-3 ou moins
                if time.time() < dismissed_until and days > 3:
                    self._license_banner.hide()
                    return
            except Exception:
                pass

        self._license_banner.apply_license(self._license, dismissible=not expired)
        self._license_banner.show()

    def _on_license_banner_dismissed(self):
        """Sauvegarde le dismiss et cache la banniere."""
        import json, os, time
        dismiss_file = os.path.join(os.path.expanduser("~"), ".mystrow_banner_dismiss.json")
        # Re-afficher dans 30 jours (sera court-circuite par J-3 de toute facon)
        until = time.time() + 30 * 86400
        try:
            with open(dismiss_file, "w") as f:
                json.dump({"until": until}, f)
        except Exception:
            pass
        self._license_banner.hide()

    def _on_banner_clicked(self):
        """Gere le clic sur le bouton de la banniere licence."""
        start_purchase = self._license.action_label in ("Renouveler",)
        dlg = ActivationDialog(self, license_result=self._license, start_purchase=start_purchase)
        dlg.activation_success.connect(self._on_activation_success)
        dlg.exec()

    def _open_activation_dialog(self):
        """Ouvre le dialogue d'activation de licence"""
        dlg = ActivationDialog(self, license_result=self._license)
        dlg.activation_success.connect(self._on_activation_success)
        dlg.exec()

    def _on_activation_success(self):
        """Appele apres une activation reussie - re-verifie et applique"""
        from license_manager import pop_login_result
        new_result = pop_login_result()
        if new_result is None:
            # Fallback : re-vérification Firebase si le résultat de login n'est pas disponible
            new_result = verify_license()
        print(f"[ACTIVATION] résultat licence: {new_result}")
        self._license = new_result

        # Rafraîchir la bannière
        self._apply_license_banner()

        # Activer/desactiver DMX
        if self._license.dmx_allowed:
            if not self.dmx.connected:
                dlg = LoginSuccessDialog(dmx_allowed=True, parent=self)
                if dlg.exec() == LoginSuccessDialog.ACTIVATE_DMX:
                    self.test_dmx_on_startup()
            else:
                LoginSuccessDialog(dmx_allowed=False, parent=self).exec()
        else:
            self.dmx.connected = False
            self.plan_de_feu.set_dmx_blocked()
            LoginSuccessDialog(dmx_allowed=False, parent=self).exec()

        # Activer/desactiver menu Node
        if hasattr(self, 'node_menu'):
            self.node_menu.setEnabled(self._license.dmx_allowed)

        # Watermark video integre
        if not self._license.watermark_required:
            if hasattr(self, '_video_watermark') and self._video_watermark:
                self._video_watermark.hide()
                self._video_watermark.deleteLater()
                self._video_watermark = None
        else:
            if not hasattr(self, '_video_watermark') or not self._video_watermark:
                self._setup_video_watermark()

        # Watermark fenetre de sortie video
        if self.video_output_window:
            self.video_output_window.set_watermark(self._license.watermark_required)

    def show_license_warning_if_needed(self):
        """Affiche le dialogue d'avertissement si necessaire (appele apres show)"""
        if not self._license.show_warning:
            return
        result = LicenseWarningDialog(self._license, self).exec()
        if result == 2:  # Bouton "Activer"
            self._open_activation_dialog()

    def restart_application(self):
        """Redemarre l'application"""
        reply = QMessageBox.question(self, "Redemarrer",
            "Voulez-vous redemarrer l'application ?",
            QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            if hasattr(self, 'midi_handler') and self.midi_handler:
                try:
                    if self.midi_handler.midi_in:
                        self.midi_handler.midi_in.close_port()
                    if self.midi_handler.midi_out:
                        self.midi_handler.midi_out.close_port()
                except:
                    pass
            python = sys.executable
            os.execv(python, [python] + sys.argv)

    def toggle_blackout_from_midi(self):
        """Toggle le blackout depuis le bouton 9 de l'AKAI"""
        self.blackout_active = not self.blackout_active

        if self.blackout_active:
            for proj in self.projectors:
                proj.color = QColor("black")
                proj.level = 0

            if MIDI_AVAILABLE and self.midi_handler.midi_out:
                self.midi_handler.midi_out.send_message([0x90, 122, 3])
        else:
            for i, fader in self.faders.items():
                if i < 8:
                    self.set_proj_level(i, fader.value)

            if MIDI_AVAILABLE and self.midi_handler.midi_out:
                self.midi_handler.midi_out.send_message([0x90, 122, 0])

    def toggle_fader_mute_from_midi(self, fader_idx):
        """Toggle le mute d'un fader depuis l'AKAI physique - tous independants"""
        if fader_idx == 8:
            return  # Pas de mute pour le fader FX

        if 0 <= fader_idx < len(self.fader_buttons):
            btn = self.fader_buttons[fader_idx]
            btn.active = not btn.active
            btn.update_style()
            self.toggle_mute(fader_idx, btn.active)

            if MIDI_AVAILABLE and self.midi_handler.midi_out:
                note = 100 + fader_idx
                velocity = 3 if btn.active else 0
                self.midi_handler.midi_out.send_message([0x90, note, velocity])

    # Mapping raccourcis clavier -> couleurs
    COLOR_SHORTCUTS = {
        Qt.Key_R: QColor(255, 0, 0),
        Qt.Key_G: QColor(0, 255, 0),
        Qt.Key_B: QColor(0, 0, 255),
        Qt.Key_C: QColor(0, 255, 255),
        Qt.Key_M: QColor(255, 0, 255),
        Qt.Key_Y: QColor(255, 255, 0),
        Qt.Key_W: QColor(255, 255, 255),
        Qt.Key_K: QColor(0, 0, 0),
        Qt.Key_O: QColor(255, 128, 0),
        Qt.Key_P: QColor(255, 105, 180),
    }

    def keyPressEvent(self, event):
        """Gere les raccourcis clavier"""
        key = event.key()

        if key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.toggle_play()
            event.accept()
        elif key == Qt.Key_PageDown:
            self.next_media()
            event.accept()
        elif key == Qt.Key_PageUp:
            self.previous_media()
            event.accept()
        elif key == Qt.Key_Right and self.go_mode:
            self._go_advance()
            event.accept()
        elif key == Qt.Key_Left and self.go_mode:
            self._go_back()
            event.accept()
        elif key in (Qt.Key_F1, Qt.Key_F2, Qt.Key_F3, Qt.Key_F4):
            cart_index = key - Qt.Key_F1  # F1=0, F2=1, F3=2, F4=3
            if cart_index < len(self.cartouches):
                self.on_cartouche_clicked(cart_index)
            event.accept()
        elif key in self.COLOR_SHORTCUTS:
            self._apply_color_shortcut(self.COLOR_SHORTCUTS[key])
            event.accept()
        else:
            super().keyPressEvent(event)

    def _apply_color_shortcut(self, color):
        """Applique une couleur raccourci aux projecteurs selectionnes"""
        if not self.plan_de_feu.selected_lamps:
            return
        targets = []
        for g, i in self.plan_de_feu.selected_lamps:
            projs = [p for p in self.projectors if p.group == g]
            if i < len(projs):
                targets.append(projs[i])
        for proj in targets:
            proj.base_color = color
            proj.level = 100
            proj.color = QColor(color.red(), color.green(), color.blue())
        if self.dmx:
            self.dmx.update_from_projectors(self.projectors)
        self.plan_de_feu.refresh()

    def show_shortcuts_dialog(self):
        """Affiche le dialog listant tous les raccourcis clavier"""
        dlg = QDialog(self)
        dlg.setWindowTitle("Raccourcis clavier")
        dlg.setMinimumSize(700, 620)
        dlg.setStyleSheet("""
            QDialog { background: #1a1a1a; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QScrollArea { border: none; background: #1a1a1a; }
            QWidget#shortcut_content { background: #1a1a1a; }
        """)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Raccourcis clavier")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #ffffff; padding-bottom: 4px;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_content.setObjectName("shortcut_content")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(4)

        # Donnees : (groupe, [(touche, description), ...])
        shortcut_groups = [
            ("LECTURE", [
                ("Espace / Entree", "Play / Pause"),
                ("Page Down", "Media suivant"),
                ("Page Up", "Media precedent"),
                ("F1", "Cartouche 1"),
                ("F2", "Cartouche 2"),
                ("F3", "Cartouche 3"),
                ("F4", "Cartouche 4"),
            ]),
            ("FICHIERS", [
                ("Ctrl + N", "Nouveau show"),
                ("Ctrl + O", "Ouvrir show"),
                ("Ctrl + S", "Enregistrer show"),
                ("Ctrl + Shift + S", "Enregistrer sous"),
            ]),
            ("COULEURS RAPIDES", [
                ("W", "Blanc"),
                ("R", "Rouge"),
                ("O", "Orange"),
                ("Y", "Jaune"),
                ("G", "Vert"),
                ("C", "Cyan"),
                ("B", "Bleu"),
                ("M", "Magenta"),
                ("P", "Rose"),
                ("K", "Noir (eteindre)"),
            ]),
            ("PLAN DE FEU  -  Selection", [
                ("Ctrl + A", "Tout selectionner"),
                ("Escape", "Deselectionner tout"),
                ("Escape x3", "Eteindre tous les projecteurs"),
                ("F", "Selectionner les Faces"),
                ("1", "Contre + Lat pairs"),
                ("2", "Contre + Lat impairs"),
                ("3", "Tous Contre + Lat"),
                ("4", "Douche 1"),
                ("5", "Douche 2"),
                ("6", "Douche 3"),
            ]),
            ("EDITEUR TIMELINE", [
                ("Espace", "Play / Pause"),
                ("Ctrl + Z", "Annuler"),
                ("Ctrl + Y", "Retablir"),
                ("Suppr", "Supprimer les clips selectionnes"),
                ("Ctrl + A", "Selectionner tous les clips"),
                ("Ctrl + C", "Copier les clips"),
                ("Ctrl + X", "Couper les clips"),
                ("Ctrl + V", "Coller les clips"),
                ("C", "Activer / desactiver mode CUT"),
                ("Escape", "Quitter mode CUT / deselectionner"),
            ]),
        ]

        for group_name, shortcuts in shortcut_groups:
            # En-tete de groupe
            group_label = QLabel(f"  {group_name}")
            group_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
            group_label.setStyleSheet("color: #00d4ff; padding: 8px 0 2px 0;")
            scroll_layout.addWidget(group_label)

            for key, desc in shortcuts:
                row_frame = QFrame()
                row_frame.setStyleSheet("""
                    QFrame {
                        background: #222222; border-radius: 6px;
                        padding: 6px 12px; margin: 1px 0;
                    }
                    QFrame:hover { background: #2a2a2a; }
                """)
                row_layout = QHBoxLayout(row_frame)
                row_layout.setContentsMargins(8, 4, 8, 4)

                # Touche avec style "keycap"
                key_label = QLabel(key)
                key_label.setMinimumWidth(180)
                key_label.setStyleSheet("""
                    color: #ffffff; font-weight: bold; font-size: 13px;
                    font-family: 'Consolas';
                """)
                row_layout.addWidget(key_label)

                row_layout.addStretch()

                desc_label = QLabel(desc)
                desc_label.setMinimumWidth(300)
                desc_label.setStyleSheet("color: #aaaaaa; font-size: 13px;")
                row_layout.addWidget(desc_label)

                scroll_layout.addWidget(row_frame)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        close_btn = QPushButton("Fermer")
        close_btn.setStyleSheet("""
            QPushButton {
                background: #333333; color: #aaaaaa;
                padding: 10px 30px; border-radius: 6px; font-size: 13px;
                border: 1px solid #4a4a4a;
            }
            QPushButton:hover { background: #3a3a3a; color: #ffffff; }
        """)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        dlg.exec()

    def next_media(self):
        """Passe au media suivant"""
        if self.seq.current_row + 1 < self.seq.table.rowCount():
            self.seq.play_row(self.seq.current_row + 1)

    def previous_media(self):
        """Revient au media precedent"""
        if self.seq.current_row > 0:
            self.seq.play_row(self.seq.current_row - 1)

    # ==================== CARTOUCHEUR ====================

    def on_cartouche_clicked(self, index):
        """Gere le clic sur une cartouche (3 etats)"""
        cart = self.cartouches[index]
        if not cart.media_path:
            self._load_cartouche_file(index)
            return
        if cart.state == CartoucheButton.PLAYING:
            self._stop_cartouche(index)
        else:
            self._play_cartouche(index)

    def _play_cartouche(self, index):
        """Lance la lecture d'une cartouche"""
        cart = self.cartouches[index]
        if not cart.media_path:
            return

        # Stopper toute autre cartouche active
        for i, c in enumerate(self.cartouches):
            if i != index and c.state == CartoucheButton.PLAYING:
                c.set_idle()

        # Stopper le player principal si en lecture
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.stop()

        # Video: rediriger vers le video_widget
        ext = os.path.splitext(cart.media_path)[1].lower()
        video_exts = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'}
        if ext in video_exts and QVideoWidget is not None:
            self.cart_player.setVideoOutput(self.video_widget)
        else:
            self.cart_player.setVideoOutput(None)

        self.cart_audio.setVolume(cart.volume / 100.0)
        self.cart_player.setSource(QUrl.fromLocalFile(cart.media_path))
        self.cart_player.play()
        cart.set_playing()
        self.cart_playing_index = index

    def _stop_cartouche(self, index):
        """Arrete la cartouche en cours"""
        self.cart_player.stop()
        self.cartouches[index].set_stopped()
        self.cart_playing_index = -1
        # Restaurer le video output du player principal
        self.player.setVideoOutput(self.video_widget if QVideoWidget is not None else None)

    def _stop_all_cartouches(self):
        """Arrete toutes les cartouches et restaure l'etat"""
        if self.cart_playing_index >= 0:
            self.cart_player.stop()
            self.cart_playing_index = -1
        for cart in self.cartouches:
            cart.set_idle()
        self.player.setVideoOutput(self.video_widget if QVideoWidget is not None else None)

    def on_cart_media_status(self, status):
        """Gere la fin de lecture d'une cartouche"""
        if status == QMediaPlayer.EndOfMedia:
            if 0 <= self.cart_playing_index < len(self.cartouches):
                self.cartouches[self.cart_playing_index].set_stopped()
                self.cart_playing_index = -1

    def load_cartouche_media(self, index):
        """Menu contextuel sur une cartouche (clic droit)"""
        from PySide6.QtWidgets import QWidgetAction, QSlider
        cart = self.cartouches[index]
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
                color: white;
            }
            QMenu::item:selected {
                background: #2a4a5a;
            }
            QMenu::separator {
                height: 1px;
                background: #3a3a3a;
                margin: 4px 8px;
            }
        """)

        # Volume slider
        vol_widget = QWidget()
        vol_layout = QHBoxLayout(vol_widget)
        vol_layout.setContentsMargins(12, 6, 12, 6)
        vol_layout.setSpacing(8)

        vol_icon = QLabel("Vol")
        vol_icon.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        vol_layout.addWidget(vol_icon)

        vol_slider = QSlider(Qt.Horizontal)
        vol_slider.setRange(0, 100)
        vol_slider.setValue(cart.volume)
        vol_slider.setFixedWidth(130)
        vol_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333; height: 6px; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #00d4ff; width: 14px; height: 14px;
                margin: -4px 0; border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #005577, stop:1 #00d4ff);
                border-radius: 3px;
            }
        """)
        vol_layout.addWidget(vol_slider)

        vol_label = QLabel(f"{cart.volume}%")
        vol_label.setStyleSheet("color: #ddd; font-size: 11px; font-weight: bold; min-width: 32px;")
        vol_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        vol_layout.addWidget(vol_label)

        def on_vol_changed(v):
            vol_label.setText(f"{v}%")
            cart.volume = v
            cart._update_style()
            # Appliquer en temps reel si en lecture
            if self.cart_playing_index == index:
                self.cart_audio.setVolume(v / 100.0)

        vol_slider.valueChanged.connect(on_vol_changed)

        vol_action = QWidgetAction(menu)
        vol_action.setDefaultWidget(vol_widget)
        menu.addAction(vol_action)

        menu.addSeparator()

        load_action = menu.addAction("Charger un media")
        clear_action = None
        if cart.media_path:
            clear_action = menu.addAction("Vider la cartouche")

        action = menu.exec(cart.mapToGlobal(cart.rect().bottomLeft()))

        if action == load_action:
            self._load_cartouche_file(index)
        elif action == clear_action:
            self._clear_cartouche(index)

    def _load_cartouche_file(self, index):
        """Charge un fichier dans une cartouche"""
        path, _ = QFileDialog.getOpenFileName(
            self, f"Charger Cartouche {index + 1}", "",
            "Medias (*.mp3 *.wav *.ogg *.flac *.aac *.wma *.mp4 *.avi *.mkv *.mov *.wmv *.webm)"
        )
        if not path:
            return

        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            if size_mb > 300:
                QMessageBox.warning(self, "Fichier trop volumineux",
                    f"Le fichier fait {size_mb:.0f} Mo.\nLimite: 300 Mo pour les cartouches.")
                return
        except OSError:
            pass

        cart = self.cartouches[index]
        cart.media_path = path
        cart.media_title = Path(path).stem
        ext = Path(path).suffix.lower()
        if ext in CartoucheButton.VIDEO_EXTS:
            cart.media_icon = "\U0001f3ac"
            kind = "vidéo"
        elif ext in CartoucheButton.AUDIO_EXTS:
            cart.media_icon = "\U0001f3b5"
            kind = "audio"
        else:
            cart.media_icon = ""
            kind = "média"
        cart.set_idle()
        self._log_message(f"Cartouche {index + 1} — {kind} : {cart.media_title}", "info")

    def _clear_cartouche(self, index):
        """Vide une cartouche"""
        if self.cart_playing_index == index:
            self.cart_player.stop()
            self.cart_playing_index = -1
            self.player.setVideoOutput(self.video_widget if QVideoWidget is not None else None)
        cart = self.cartouches[index]
        cart.media_path = None
        cart.media_title = None
        cart.media_icon = ""
        cart.set_idle()
        self._log_message(f"Cartouche {index + 1} vidée", "info")

    # ==================== FIN CARTOUCHEUR ====================

    def closeEvent(self, e):
        """Gere la fermeture de la fenetre"""
        # Sauvegarder automatiquement la config AKAI
        self._save_akai_config_auto()

        # Fermer la fenetre de sortie video
        if self.video_output_window:
            self.video_output_window.close()
            self.video_output_window = None

        if hasattr(self, 'midi_handler'):
            self.midi_handler.close()

        if hasattr(self, '_streamdeck_server'):
            self._streamdeck_server.stop()

        if self.seq.is_dirty:
            res = QMessageBox.question(self, "Quitter",
                "Sauvegarder avant de quitter ?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if res == QMessageBox.Yes:
                if self.save_show():
                    self._allow_sleep()
                    e.accept()
                else:
                    e.ignore()
            elif res == QMessageBox.Cancel:
                e.ignore()
            else:
                self._allow_sleep()
                e.accept()
        else:
            self._allow_sleep()
            e.accept()

    def apply_styles(self):
        """Applique les styles CSS"""
        self.setStyleSheet("""
            QMainWindow { background: #050505; }
            QWidget { color: #ddd; font-family: 'Segoe UI'; font-size: 10pt; }
            QFrame { background: #0f0f0f; border: 1px solid #1a1a1a; border-radius: 8px; }
            QMenuBar { background: #1a1a1a; border-bottom: 1px solid #2a2a2a; padding: 4px; }
            QMenuBar::item { padding: 6px 12px; background: transparent; border-radius: 4px; }
            QMenuBar::item:selected { background: #2a2a2a; }
            QMenu { background: #1a1a1a; border: 1px solid #2a2a2a; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background: #2a2a2a; }
            QSplitter::handle { background: #1a1a1a; }
            QMessageBox { background: #1a1a1a; }
            QMessageBox QLabel { color: white; }
            QMessageBox QPushButton {
                color: black;
                background: #cccccc;
                border: 1px solid #999999;
                border-radius: 4px;
                padding: 6px 20px;
                font-weight: bold;
            }
            QMessageBox QPushButton:hover { background: #00d4ff; }
        """)

    # ==================== DMX PATCH ====================

    def auto_patch_at_startup(self):
        """Patch automatique au demarrage"""
        if self.load_dmx_patch_config():
            return

        # Appliquer le patch depuis start_address de chaque fixture
        for i, proj in enumerate(self.projectors):
            proj_key = f"{proj.group}_{i}"
            if proj.group == "fumee" or proj.fixture_type == "Machine a fumee":
                profile = list(DMX_PROFILES["2CH_FUMEE"])
            elif proj.fixture_type == "Moving Head":
                profile = list(DMX_PROFILES["MOVING_8CH"])
            elif proj.fixture_type == "Barre LED":
                profile = list(DMX_PROFILES["LED_BAR_RGB"])
            elif proj.fixture_type == "Stroboscope":
                profile = list(DMX_PROFILES["STROBE_2CH"])
            else:
                profile = list(DMX_PROFILES["RGBDS"])

            nb_ch = len(profile)
            channels = [proj.start_address + c for c in range(nb_ch)]
            self.dmx.set_projector_patch(proj_key, channels,
                                         universe=getattr(proj, 'universe', 0),
                                         profile=profile)

    def toggle_3d_window(self):
        """Affiche ou cache la fenêtre 3D du plan de feu."""
        if self._plan3d.isVisible():
            self._plan3d.hide()
            if hasattr(self.plan_de_feu, 'btn_3d'):
                self.plan_de_feu.btn_3d.setChecked(False)
        else:
            self._plan3d.init_scene(self.projectors)
            self._plan3d.show()
            self._plan3d.raise_()
            if hasattr(self.plan_de_feu, 'btn_3d'):
                self.plan_de_feu.btn_3d.setChecked(True)

    def show_dmx_patch_config(self, select_idx=None):
        """Interface de configuration DMX — master-detail + Plan de feu"""
        from plan_de_feu import FixtureCanvas, NewPlanWizard

        # ── Dialog ────────────────────────────────────────────────────────
        dialog = QDialog(self)
        dialog.setWindowTitle("Patch DMX")
        dialog.setWindowFlags(Qt.Window | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)

        _SS = """
            QDialog { background:#0f0f0f; color:#e0e0e0; }
            QTabWidget::pane { border:none; background:#0f0f0f; }
            QTabBar::tab { background:#181818; color:#444; padding:10px 26px;
                border:none; border-bottom:2px solid transparent; font-size:12px; }
            QTabBar::tab:selected { color:#fff; border-bottom:2px solid #00d4ff; background:#0f0f0f; }
            QTabBar::tab:hover { color:#aaa; background:#1c1c1c; }
            QScrollArea { border:none; background:transparent; }
            QScrollBar:vertical { background:#0a0a0a; width:5px; border-radius:2px; }
            QScrollBar::handle:vertical { background:#252525; border-radius:2px; min-height:20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
            QLineEdit { background:#171717; color:#fff; border:1px solid #242424;
                border-radius:7px; padding:7px 13px; font-size:13px; }
            QLineEdit:focus { border:1px solid #00d4ff44; background:#14141c; }
            QComboBox { background:#171717; color:#ddd; border:1px solid #242424;
                border-radius:7px; padding:7px 12px; font-size:12px; }
            QComboBox:focus { border-color:#00d4ff44; }
            QComboBox::drop-down { border:none; width:18px; }
            QComboBox QAbstractItemView { background:#1e1e1e; color:#e0e0e0;
                border:1px solid #333; selection-background-color:#00d4ff22;
                selection-color:#00d4ff; outline:none; padding:4px; }
            QComboBox QAbstractItemView::item { padding:6px 12px; border-radius:4px; }
            QSpinBox { background:#171717; color:#00d4ff; border:1px solid #242424;
                border-radius:7px; padding:6px 10px; font-size:17px; font-weight:bold; }
            QSpinBox:focus { border-color:#00d4ff44; }
            QSpinBox::up-button, QSpinBox::down-button { width:0; height:0; }
            QPushButton { background:#181818; color:#888; border:1px solid #242424;
                border-radius:6px; padding:6px 16px; font-size:12px; }
            QPushButton:hover { border-color:#00d4ff33; color:#ddd; background:#1e1e28; }
            QPushButton:pressed { background:#00d4ff11; }
            QLabel { color:#e0e0e0; }
            QFrame[frameShape="4"] { color:#1e1e1e; }
            QFrame[frameShape="5"] { color:#1e1e1e; }
        """
        dialog.setStyleSheet(_SS)

        _GC = {
            "face": "#ff8844", "contre": "#4488ff",
            "douche1": "#44cc88", "douche2": "#ffcc44", "douche3": "#ff4488",
            "lat": "#aa55ff", "lyre": "#ff44cc", "barre": "#44aaff",
            "strobe": "#ffee44", "fumee": "#88aaaa", "public": "#ff6655",
        }
        GROUP_LETTERS = {
            "face": "A", "lat": "B", "contre": "C",
            "douche1": "D", "douche2": "E", "douche3": "F",
            "public": "Public",
            "fumee": "Fumée", "lyre": "Lyres", "barre": "Barres", "strobe": "Strobos",
        }
        FIXTURE_TYPES = ["PAR LED", "Moving Head", "Barre LED", "Stroboscope", "Machine a fumee"]
        CH_COLORS = {
            "R":          "#cc1111",
            "G":          "#22aa33",
            "B":          "#1155dd",
            "W":          "#cccccc",
            "Dim":        "#cc9900",
            "Strobe":     "#bb33cc",
            "UV":         "#6611dd",
            "Ambre":      "#cc6600",
            "Orange":     "#dd4400",
            "Pan":        "#1199cc",
            "Tilt":       "#11ccaa",
            "Smoke":      "#5588aa",
            "Fan":        "#336677",
            "Gobo1":      "#993355",
            "Gobo2":      "#774455",
            "Shutter":    "#999911",
            "Speed":      "#557722",
            "Mode":       "#445566",
            "ColorWheel": "#aa2299",
            "Prism":      "#2266aa",
            "Focus":      "#776622",
            "PanFine":    "#0077bb",
            "TiltFine":   "#00aa88",
        }

        root = QVBoxLayout(dialog)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Menu bar ──────────────────────────────────────────────────────
        menubar = QMenuBar(dialog)
        menubar.setStyleSheet("""
            QMenuBar {
                background: #090909;
                color: #888;
                border-bottom: 1px solid #181818;
                padding: 2px 8px;
                font-size: 12px;
            }
            QMenuBar::item { padding: 5px 14px; background: transparent; border-radius: 4px; }
            QMenuBar::item:selected { background: #1a1a1a; color: #ddd; }
            QMenu {
                background: #111111;
                color: #cccccc;
                border: 1px solid #2a2a2a;
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item { padding: 7px 28px; border-radius: 3px; }
            QMenu::item:selected { background: #00d4ff22; color: #00d4ff; }
            QMenu::separator { background: #1e1e1e; height: 1px; margin: 3px 8px; }
        """)
        m_file = menubar.addMenu("📁  Fichier")
        act_new  = m_file.addAction("✨  Nouveau Patch")
        act_save = m_file.addAction("💾  Enregistrer Patch")
        m_file.addSeparator()
        act_dflt = m_file.addAction("🏠  Patch par défaut")
        m_file.addSeparator()
        act_import = m_file.addAction("📂  Importer le patch...")
        act_export = m_file.addAction("📤  Exporter le patch...")

        m_edit = menubar.addMenu("✏️  Edition")
        act_undo = m_edit.addAction("↩  Annuler\tCtrl+Z")
        act_redo = m_edit.addAction("↪  Rétablir\tCtrl+Y")
        m_edit.addSeparator()
        act_auto = m_edit.addAction("⚡  Auto Adresse")

        # Bouton Editeur de fixture dans un QHBoxLayout juste après Edition
        _menu_row = QHBoxLayout()
        _menu_row.setContentsMargins(0, 0, 0, 0)
        _menu_row.setSpacing(0)
        _menu_row.addWidget(menubar, 0)

        btn_fixture_editor = QPushButton("🛠  Créer votre fixture")
        btn_fixture_editor.setAutoDefault(False)
        btn_fixture_editor.setFixedHeight(28)
        btn_fixture_editor.setStyleSheet(
            "QPushButton { background:transparent; color:#aaaaaa; border:none;"
            " padding:1px 10px; font-size:12px; border-radius:3px; }"
            "QPushButton:hover { background:#1e1e1e; color:#ffffff; }"
        )
        _menu_row.addWidget(btn_fixture_editor, 0)
        _menu_row.addStretch(1)

        root.addLayout(_menu_row)

        # ── Toolbar ───────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(56)
        toolbar.setStyleSheet("background:#090909; border-bottom:1px solid #181818;")
        th = QHBoxLayout(toolbar)
        th.setContentsMargins(20, 0, 20, 0)
        th.setSpacing(8)
        lbl_ttl = QLabel("Patch DMX")
        lbl_ttl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        lbl_ttl.setStyleSheet("color:white; padding-right:16px;")
        th.addWidget(lbl_ttl)

        def _tbar_btn(text, color):
            b = QPushButton(text)
            b.setFixedHeight(34)
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{color}; border:1px solid {color}33;"
                f" border-radius:6px; padding:6px 16px; font-size:12px; }}"
                f"QPushButton:hover {{ background:{color}18; border-color:{color}66; }}"
            )
            return b

        btn_add = _tbar_btn("➕  Ajouter", "#55cc77")
        btn_add.setAutoDefault(False)
        th.addWidget(btn_add)
        th.addStretch()
        btn_save = QPushButton("💾  Sauvegarder")
        btn_save.setFixedHeight(34)
        btn_save.setEnabled(False)
        btn_save.setStyleSheet(
            "QPushButton { background:#0d1a0d; color:#336633; border:1px solid #1a2e1a;"
            " border-radius:6px; padding:6px 18px; font-size:12px; }"
            "QPushButton:enabled { background:#0d2010; color:#44bb44; border-color:#1e4020; }"
            "QPushButton:enabled:hover { background:#143018; color:#66dd66; border-color:#2a6030; }"
            "QPushButton:disabled { color:#333; border-color:#1a1a1a; background:#0d0d0d; }"
        )
        th.addWidget(btn_save)
        th.addSpacing(8)
        close_btn = QPushButton("✕  Fermer")
        close_btn.setFixedHeight(34)
        close_btn.setStyleSheet(
            "QPushButton { background:#2a0a0a; color:#cc4444; border:1px solid #4a1a1a;"
            " border-radius:6px; padding:6px 22px; font-size:12px; }"
            "QPushButton:hover { background:#3d1010; color:#ff6666; border-color:#883333; }"
            "QPushButton:pressed { background:#1a0505; }"
        )
        close_btn.setAutoDefault(False)
        btn_save.setAutoDefault(False)
        close_btn.clicked.connect(dialog.accept)
        th.addWidget(close_btn)
        root.addWidget(toolbar)

        # Bloquer Enter/Espace au niveau du dialog pour éviter l'activation accidentelle de boutons
        def _dialog_key(event):
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                event.accept()
                return
            from PySide6.QtWidgets import QDialog as _QD
            _QD.keyPressEvent(dialog, event)
        dialog.keyPressEvent = _dialog_key

        # ── Bandeau conflits ──────────────────────────────────────────────
        conflict_banner = QLabel()
        conflict_banner.setFixedHeight(30)
        conflict_banner.setStyleSheet(
            "background:#1a0d00; color:#ffaa44; padding:0 20px; font-size:11px;"
            " border-bottom:1px solid #2e1800;"
        )
        conflict_banner.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        conflict_banner.setVisible(False)
        root.addWidget(conflict_banner)

        # ── Tabs ──────────────────────────────────────────────────────────
        tabs = QTabWidget()
        root.addWidget(tabs)

        # ════════════════════════════════════════════════════════════════
        # TAB 0 — FIXTURES  (master-detail)
        # ════════════════════════════════════════════════════════════════
        tab_fx = QWidget()
        tab_fx.setStyleSheet("background:#0f0f0f;")
        fx_root = QVBoxLayout(tab_fx)
        fx_root.setContentsMargins(0, 0, 0, 0)
        fx_root.setSpacing(0)

        spl = QSplitter(Qt.Horizontal)
        spl.setHandleWidth(1)
        spl.setStyleSheet("QSplitter::handle{background:#181818;}")

        # ── Panneau gauche : cards ────────────────────────────────────────
        left_w = QWidget()
        left_w.setMinimumWidth(240)
        left_w.setMaximumWidth(320)
        left_w.setStyleSheet("background:#090909;")
        lv = QVBoxLayout(left_w)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        filter_bar = QLineEdit()
        filter_bar.setPlaceholderText("  🔍  Filtrer...")
        filter_bar.setFixedHeight(36)
        filter_bar.setStyleSheet(
            "QLineEdit { background:#0e0e0e; color:#777; border:none;"
            " border-bottom:1px solid #181818; border-radius:0; padding:0 16px; font-size:12px; }"
            "QLineEdit:focus { color:#fff; border-bottom:1px solid #00d4ff33; }"
        )
        lv.addWidget(filter_bar)

        sort_bar = QWidget()
        sort_bar.setFixedHeight(30)
        sort_bar.setStyleSheet("background:#0a0a0a; border-bottom:1px solid #141414;")
        sort_hl = QHBoxLayout(sort_bar)
        sort_hl.setContentsMargins(8, 0, 8, 0)
        sort_hl.setSpacing(2)
        _sort_mode = ["dmx"]
        def _sort_btn(label):
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setCheckable(True)
            b.setStyleSheet(
                "QPushButton { background:transparent; color:#333; border:none;"
                " font-size:10px; padding:0 8px; border-radius:3px; }"
                "QPushButton:hover { color:#777; background:#141414; }"
                "QPushButton:checked { color:#00d4ff; background:#00d4ff18; }"
            )
            return b
        lbl_sort = QLabel("Trier :")
        lbl_sort.setStyleSheet("color:#252525; font-size:10px; border:none;")
        sort_hl.addWidget(lbl_sort)
        btn_sort_dmx  = _sort_btn("Adresse")
        btn_sort_name = _sort_btn("Nom")
        btn_sort_grp  = _sort_btn("Groupe")
        btn_sort_dmx.setChecked(True)
        sort_hl.addWidget(btn_sort_dmx)
        sort_hl.addWidget(btn_sort_name)
        sort_hl.addWidget(btn_sort_grp)
        sort_hl.addStretch()
        lv.addWidget(sort_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_w = QWidget()
        scroll_w.setStyleSheet("background:#090909;")
        card_vl = QVBoxLayout(scroll_w)
        card_vl.setContentsMargins(0, 4, 0, 4)
        card_vl.setSpacing(1)
        card_vl.addStretch()
        scroll.setWidget(scroll_w)
        lv.addWidget(scroll, 1)

        bstrip = QWidget()
        bstrip.setFixedHeight(40)
        bstrip.setStyleSheet("background:#060606; border-top:1px solid #141414;")
        bsv = QHBoxLayout(bstrip)
        bsv.setContentsMargins(8, 0, 8, 0)
        bsv.setSpacing(4)

        lbl_cnt = QLabel("")
        lbl_cnt.setStyleSheet("color:#333333; font-size:10px; padding-left:8px;")
        bsv.addWidget(lbl_cnt)
        bsv.addStretch()

        btn_rename_multi = QPushButton("✏  Renommer")
        btn_rename_multi.setFixedHeight(26)
        btn_rename_multi.setVisible(False)
        btn_rename_multi.setStyleSheet(
            "QPushButton { background:#0d1820; color:#4488bb; border:1px solid #1a3040;"
            " border-radius:5px; font-size:11px; padding:0 12px; }"
            "QPushButton:hover { background:#132535; color:#66aadd; border-color:#2a5070; }"
        )
        bsv.addWidget(btn_rename_multi)

        btn_group_multi = QPushButton("⬡  Groupe")
        btn_group_multi.setFixedHeight(26)
        btn_group_multi.setVisible(False)
        btn_group_multi.setStyleSheet(
            "QPushButton { background:#0d180d; color:#44aa44; border:1px solid #1a3a1a;"
            " border-radius:5px; font-size:11px; padding:0 12px; }"
            "QPushButton:hover { background:#132513; color:#66cc66; border-color:#2a502a; }"
        )
        bsv.addWidget(btn_group_multi)

        btn_del_multi = QPushButton("🗑  Supprimer")
        btn_del_multi.setFixedHeight(26)
        btn_del_multi.setVisible(False)
        btn_del_multi.setStyleSheet(
            "QPushButton { background:#1e0a0a; color:#cc4444; border:1px solid #3a1a1a;"
            " border-radius:5px; font-size:11px; padding:0 12px; }"
            "QPushButton:hover { background:#2a0e0e; color:#ee6666; border-color:#662222; }"
        )
        bsv.addWidget(btn_del_multi)

        btn_desel_multi = QPushButton("✕")
        btn_desel_multi.setFixedSize(26, 26)
        btn_desel_multi.setVisible(False)
        btn_desel_multi.setToolTip("Désélectionner tout")
        btn_desel_multi.setStyleSheet(
            "QPushButton { background:#1a1a1a; color:#666; border:1px solid #333;"
            " border-radius:5px; font-size:12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a2a2a; color:#aaa; border-color:#555; }"
        )
        bsv.addWidget(btn_desel_multi)
        lv.addWidget(bstrip)
        spl.addWidget(left_w)

        # ── Panneau droit : formulaire d'édition ──────────────────────────
        right_w = QWidget()
        right_w.setStyleSheet("background:#0f0f0f;")
        rv = QVBoxLayout(right_w)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        no_sel_w = QWidget()
        no_sel_w.setStyleSheet("background:#0f0f0f;")
        nsl = QVBoxLayout(no_sel_w)
        nsl.setAlignment(Qt.AlignCenter)
        lbl_nosel = QLabel("← Sélectionnez une fixture\npour la modifier")
        lbl_nosel.setAlignment(Qt.AlignCenter)
        lbl_nosel.setStyleSheet("color:#1e1e1e; font-size:16px;")
        nsl.addWidget(lbl_nosel)

        detail_w = QWidget()
        detail_w.setStyleSheet("background:#0f0f0f;")

        det_hbar = QWidget()
        det_hbar.setFixedHeight(54)
        det_hbar.setStyleSheet("background:#090909; border-bottom:1px solid #181818;")
        dth = QHBoxLayout(det_hbar)
        dth.setContentsMargins(28, 0, 20, 0)
        dth.setSpacing(8)
        lbl_det_name = QLabel()
        lbl_det_name.setFont(QFont("Segoe UI", 14, QFont.Bold))
        lbl_det_name.setStyleSheet("color:#fff; border:none; background:transparent;")
        lbl_det_group = QLabel()
        lbl_det_group.setStyleSheet("font-size:12px; border:none; background:transparent;")
        dth.addWidget(lbl_det_name)
        dth.addWidget(lbl_det_group)
        dth.addStretch()
        btn_det_locate = QPushButton("🎯  Localiser")
        btn_det_locate.setFixedHeight(30)
        btn_det_locate.setToolTip("Sélectionner cette fixture dans le Plan de feu")
        btn_det_locate.setStyleSheet(
            "QPushButton { background:#0a1020; color:#4488cc; border:1px solid #1a3050;"
            " border-radius:6px; padding:4px 14px; font-size:11px; }"
            "QPushButton:hover { background:#0f1a30; color:#66aaee; border-color:#2a5080; }"
        )
        dth.addWidget(btn_det_locate)

        btn_det_replace = QPushButton("🔄  Remplacer")
        btn_det_replace.setFixedHeight(30)
        btn_det_replace.setToolTip("Remplacer par une autre fixture de la bibliothèque")
        btn_det_replace.setStyleSheet(
            "QPushButton { background:#0a1a10; color:#44bb77; border:1px solid #1a3a20;"
            " border-radius:6px; padding:4px 14px; font-size:11px; }"
            "QPushButton:hover { background:#0e2a18; color:#66dd99; border-color:#2a6040; }"
        )
        dth.addWidget(btn_det_replace)

        btn_det_del = QPushButton("🗑  Supprimer")
        btn_det_del.setFixedHeight(30)
        btn_det_del.setStyleSheet(
            "QPushButton { background:#1e0a0a; color:#cc4444; border:1px solid #3a1a1a;"
            " border-radius:6px; padding:4px 14px; font-size:11px; }"
            "QPushButton:hover { background:#2a0e0e; color:#ee6666; border-color:#662222; }"
        )
        dth.addWidget(btn_det_del)

        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        form_w = QWidget()
        form_w.setStyleSheet("background:#0f0f0f;")
        fv = QVBoxLayout(form_w)
        fv.setContentsMargins(28, 22, 28, 22)
        fv.setSpacing(5)
        form_scroll.setWidget(form_w)

        def _sec(txt):
            l = QLabel(txt.upper())
            l.setStyleSheet(
                "color:#252525; font-size:9px; font-weight:bold; letter-spacing:2px;"
                " padding:10px 0 3px 0; border:none; background:transparent;"
            )
            return l

        def _hdiv():
            f = QFrame()
            f.setFrameShape(QFrame.HLine)
            f.setStyleSheet("color:#181818; max-height:1px; margin:8px 0;")
            return f

        fv.addWidget(_sec("Identité"))
        det_name_e = QLineEdit()
        det_name_e.setPlaceholderText("Nom de la fixture")
        det_name_e.setFixedHeight(44)
        det_name_e.setFont(QFont("Segoe UI", 14, QFont.Bold))
        det_name_e.setStyleSheet(
            "QLineEdit { background:#141414; color:#fff; border:1px solid #202020;"
            " border-radius:8px; padding:8px 16px; font-size:14px; }"
            "QLineEdit:focus { border:1px solid #00d4ff33; background:#14141c; }"
        )
        fv.addWidget(det_name_e)
        fv.addSpacing(6)

        GROUP_BLOCKS = [
            ("face",    "A", "Face",    "#ff8844"),
            ("lat",     "B", "LAT",     "#aa55ff"),
            ("contre",  "C", "Contre",  "#4488ff"),
            ("douche1", "D", "Dch 1",   "#44cc88"),
            ("douche2", "E", "Dch 2",   "#ffcc44"),
            ("douche3", "F", "Dch 3",   "#ff4488"),
        ]

        TYPE_PROFILES = {
            "PAR LED":          ["DIM", "RGB", "RGBD", "RGBDS", "RGBSD", "DRGB", "DRGBS",
                                  "RGBW", "RGBWD", "RGBWDS", "RGBWZ", "RGBWA", "RGBWAD", "RGBWOUV"],
            "Moving Head":      ["MOVING_5CH", "MOVING_8CH", "MOVING_RGB", "MOVING_RGBW"],
            "Barre LED":        ["LED_BAR_RGB", "RGB", "RGBD", "RGBDS"],
            "Stroboscope":      ["STROBE_2CH"],
            "Machine a fumee":  ["2CH_FUMEE"],
        }
        _selected_group = [None]

        _GRP_W = 46
        _UNI_W = 62

        def _col_header(text, tip, width):
            """Label + badge '?' dans un conteneur de largeur fixe, aligné sur le widget du dessous."""
            w = QWidget()
            w.setFixedWidth(width)
            w.setStyleSheet("background:transparent;")
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(3)
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            lbl.setStyleSheet("color:#555; font-size:11px; border:none; background:transparent;")
            hint = QPushButton("?")
            hint.setFixedSize(15, 15)
            hint.setCursor(Qt.WhatsThisCursor)
            hint.setFlat(True)
            hint.setStyleSheet(
                "QPushButton { color:#2a5060; font-size:8px; font-weight:bold;"
                " background:#0f1e28; border:1px solid #1e3040; border-radius:6px; padding:0; }"
                "QPushButton:hover { color:#00d4ff; background:#152030; border-color:#00d4ff55; }"
            )
            hint.clicked.connect(lambda _=False, t=tip, btn=hint:
                QToolTip.showText(btn.mapToGlobal(btn.rect().bottomLeft()), t, btn)
            )
            hl.addStretch()
            hl.addWidget(lbl)
            hl.addWidget(hint)
            hl.addStretch()
            return w

        _TIP_GROUPE = (
            "Groupe logique — les fixtures du même groupe sont\n"
            "contrôlées ensemble par le même fader AKAI.\n\n"
            "  A = Face        B = LAT         C = Contre\n"
            "  D = Douche 1    E = Douche 2    F = Douche 3\n\n"
            "Exemple : tous les PAR du groupe A (Face) montent\n"
            "et descendent ensemble quand vous bougez le fader A."
        )
        _TIP_UNIVERS = (
            "Univers DMX — chaque univers dispose de 512 adresses.\n\n"
            "💡 Conseil : si vous avez peu de projecteurs, gardez\n"
            "tout sur U1. Inutile de changer d'univers tant que\n"
            "vous ne dépassez pas l'adresse 512.\n\n"
            "Exemple : 20 PAR en 5 canaux = 100 canaux → U1 suffit.\n"
            "C'est seulement au-delà de 512 canaux occupés qu'on\n"
            "passe à U2, puis U3, etc."
        )

        tg_lbl_row = QHBoxLayout()
        tg_lbl_row.setSpacing(8)
        lbl_type_title = QLabel("Type")
        lbl_type_title.setStyleSheet("color:#555; font-size:11px; border:none; background:transparent;")
        tg_lbl_row.addWidget(lbl_type_title, 1)
        tg_lbl_row.addWidget(_col_header("Groupe",  _TIP_GROUPE,  _GRP_W))
        tg_lbl_row.addWidget(_col_header("Univers", _TIP_UNIVERS, _UNI_W))
        fv.addLayout(tg_lbl_row)

        tg_row = QHBoxLayout()
        tg_row.setSpacing(8)
        det_type_cb = QComboBox()
        det_type_cb.setFixedHeight(38)
        for ft in FIXTURE_TYPES:
            det_type_cb.addItem(ft)

        btn_group = QPushButton("—")
        btn_group.setFixedSize(_GRP_W, 38)
        btn_group.setStyleSheet(
            "QPushButton { background:#1a1a1a; color:#fff; border:1px solid #2a2a2a;"
            " border-radius:7px; font-size:16px; font-weight:bold; }"
            "QPushButton:hover { border-color:#444; }"
        )

        uni_cb_top = QComboBox()
        uni_cb_top.setFixedSize(_UNI_W, 38)
        uni_cb_top.setStyleSheet(
            "QComboBox { background:#1a1a1a; color:#fff; border:1px solid #2a2a2a;"
            " border-radius:7px; padding:0 6px; font-size:14px; font-weight:bold; }"
            "QComboBox:hover { border-color:#444; }"
            "QComboBox::drop-down { border:none; width:0px; }"
            "QComboBox QAbstractItemView { background:#1e1e1e; color:#e0e0e0;"
            " border:1px solid #333; selection-background-color:#00d4ff22; selection-color:#00d4ff; }"
        )
        for _ui, _ul in enumerate(["U1", "U2", "U3", "U4"]):
            uni_cb_top.addItem(_ul, _ui)

        tg_row.addWidget(det_type_cb, 1)
        tg_row.addWidget(btn_group)
        tg_row.addWidget(uni_cb_top)
        fv.addLayout(tg_row)
        det_group_cb = None  # remplacé par btn_group + menu
        fv.addWidget(_hdiv())

        uni_cb = uni_cb_top   # alias — l'univers est maintenant dans la ligne Groupe/Type

        fv.addWidget(_sec("Patch DMX"))

        addr_row = QHBoxLayout()
        addr_row.setSpacing(6)
        btn_am = QPushButton("−")
        btn_am.setFixedSize(36, 36)
        btn_am.setStyleSheet(
            "QPushButton { background:#141414; color:#555; border:1px solid #202020;"
            " border-radius:7px; font-size:19px; font-weight:bold; padding:0; }"
            "QPushButton:hover { color:#ccc; border-color:#3a3a3a; background:#1a1a1a; }"
        )
        addr_sb = QSpinBox()
        addr_sb.setRange(1, 512)
        addr_sb.setFixedHeight(36)
        addr_sb.setAlignment(Qt.AlignCenter)
        addr_sb.setFixedWidth(72)
        btn_ap = QPushButton("+")
        btn_ap.setFixedSize(36, 36)
        btn_ap.setStyleSheet(btn_am.styleSheet())
        lbl_addr_range = QLabel()
        lbl_addr_range.setStyleSheet("color:#2a2a2a; font-size:12px; padding-left:6px; border:none;")
        addr_row.addWidget(btn_am)
        addr_row.addWidget(addr_sb)
        addr_row.addWidget(btn_ap)
        addr_row.addWidget(lbl_addr_range)
        addr_row.addStretch()
        fv.addLayout(addr_row)
        lbl_conflict_det = QLabel()
        lbl_conflict_det.setStyleSheet("color:#ff6644; font-size:11px; padding:2px 0; border:none;")
        lbl_conflict_det.setVisible(False)
        fv.addWidget(lbl_conflict_det)
        fv.addWidget(_hdiv())

        fv.addWidget(_sec("Visualisation 3D"))
        height_row = QHBoxLayout()
        height_row.setSpacing(8)
        lbl_height = QLabel("Hauteur de suspension")
        lbl_height.setStyleSheet("color:#888; font-size:11px; border:none; background:transparent;")
        from PySide6.QtWidgets import QDoubleSpinBox as _DSB
        height_sb = _DSB()
        height_sb.setRange(0.0, 20.0)
        height_sb.setSingleStep(0.5)
        height_sb.setValue(7.0)
        height_sb.setSuffix(" m")
        height_sb.setFixedWidth(90)
        height_sb.setFixedHeight(32)
        height_sb.setStyleSheet(
            "QDoubleSpinBox { background:#171717; color:#00d4ff; border:1px solid #242424;"
            " border-radius:7px; padding:4px 8px; font-size:13px; font-weight:bold; }"
            "QDoubleSpinBox:focus { border-color:#00d4ff44; }"
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width:0; }"
        )
        lbl_height_hint = QLabel("(hauteur en scène pour la 3D)")
        lbl_height_hint.setStyleSheet("color:#444; font-size:10px; border:none; background:transparent;")
        height_row.addWidget(lbl_height)
        height_row.addWidget(height_sb)
        height_row.addWidget(lbl_height_hint)
        height_row.addStretch()
        fv.addLayout(height_row)

        rot_row = QHBoxLayout()
        rot_row.setSpacing(8)
        lbl_rot = QLabel("Rotation corps")
        lbl_rot.setStyleSheet("color:#888; font-size:11px; border:none; background:transparent;")
        from PySide6.QtWidgets import QSpinBox as _SB2
        body_rot_sb = _SB2()
        body_rot_sb.setRange(0, 359)
        body_rot_sb.setSuffix("°")
        body_rot_sb.setWrapping(True)
        body_rot_sb.setValue(0)
        body_rot_sb.setFixedWidth(90)
        body_rot_sb.setFixedHeight(32)
        body_rot_sb.setStyleSheet(
            "QSpinBox { background:#171717; color:#00d4ff; border:1px solid #242424;"
            " border-radius:7px; padding:4px 8px; font-size:13px; font-weight:bold; }"
            "QSpinBox:focus { border-color:#00d4ff44; }"
            "QSpinBox::up-button, QSpinBox::down-button { width:0; }"
        )
        lbl_rot_hint = QLabel("(orientation sur la truss)")
        lbl_rot_hint.setStyleSheet("color:#444; font-size:10px; border:none; background:transparent;")
        rot_row.addWidget(lbl_rot)
        rot_row.addWidget(body_rot_sb)
        rot_row.addWidget(lbl_rot_hint)
        rot_row.addStretch()
        fv.addLayout(rot_row)
        fv.addWidget(_hdiv())

        fv.addWidget(_sec("Profil DMX"))

        fv.addSpacing(6)

        chips_w = QWidget()
        chips_w.setStyleSheet("background:transparent;")
        chips_vl = QVBoxLayout(chips_w)
        chips_vl.setContentsMargins(0, 0, 0, 8)
        chips_vl.setSpacing(4)
        fv.addWidget(chips_w)

        fv.addStretch()

        dv_outer = QVBoxLayout(detail_w)
        dv_outer.setContentsMargins(0, 0, 0, 0)
        dv_outer.setSpacing(0)
        dv_outer.addWidget(det_hbar)
        dv_outer.addWidget(form_scroll, 1)

        det_stack = QStackedWidget()
        det_stack.addWidget(no_sel_w)
        det_stack.addWidget(detail_w)
        det_stack.setCurrentIndex(0)
        rv.addWidget(det_stack, 1)

        spl.addWidget(right_w)
        spl.setSizes([280, 900])
        fx_root.addWidget(spl)

        tabs.addTab(tab_fx, "📋  Fixtures")

        # ── Onglet 2 : Plan de feu ─────────────────────────────────────
        tab_canvas = QWidget()
        tab_canvas.setStyleSheet("background: #0a0a0a;")
        vl_canvas = QVBoxLayout(tab_canvas)
        vl_canvas.setContentsMargins(0, 0, 0, 0)
        vl_canvas.setSpacing(0)

        # ── Barre d'édition inline ────────────────────────────────
        _ES = (  # Selection buttons style — neutral
            "QPushButton { background:#111111; color:#4a4a4a; border:1px solid #1c1c1c;"
            " border-radius:5px; padding:3px 12px; font-size:11px; }"
            "QPushButton:hover { background:#1a1a1a; color:#888888; border-color:#2a2a2a; }"
            "QPushButton:pressed { background:#0e0e0e; }"
        )
        _EA = (  # Action buttons — blue tint
            "QPushButton { background:#0d1520; color:#4488bb; border:1px solid #1a2d40;"
            " border-radius:5px; padding:3px 14px; font-size:11px; }"
            "QPushButton:hover { background:#142030; color:#66aadd; border-color:#2a5070; }"
            "QPushButton:pressed { background:#090e18; }"
        )
        _ED = (  # Destructive button style — red
            "QPushButton { background:#130606; color:#663333; border:1px solid #220d0d;"
            " border-radius:5px; padding:3px 12px; font-size:11px; }"
            "QPushButton:hover { background:#1c0808; color:#dd4444; border-color:#551111; }"
            "QPushButton:pressed { background:#0e0404; }"
        )

        edit_strip = QWidget()
        edit_strip.setFixedHeight(42)
        edit_strip.setStyleSheet("background:#0c0c0c; border-bottom:1px solid #161616;")
        es = QHBoxLayout(edit_strip)
        es.setContentsMargins(10, 0, 10, 0)
        es.setSpacing(6)

        def _vsep():
            s = QFrame()
            s.setFrameShape(QFrame.VLine)
            s.setStyleSheet("QFrame{color:#1a1a1a;max-width:1px;margin:8px 4px;}")
            return s

        # ── Alignement ────────────────────────────────────────────────
        btn_align_row  = QPushButton("⟶  Aligner")
        btn_align_row.setToolTip("Aligner les fixtures sélectionnées sur la même ligne horizontale")
        btn_distribute = QPushButton("⟺  Centrer")
        btn_distribute.setToolTip("Centrer et répartir à espacement égal les fixtures sélectionnées")
        for b in [btn_align_row, btn_distribute]:
            b.setStyleSheet(_EA)
            b.setFixedHeight(28)
            es.addWidget(b)

        es.addWidget(_vsep())

        # ── Sélection ─────────────────────────────────────────────────
        btn_sel_all_c = QPushButton("Tout sél.")
        btn_desel_c   = QPushButton("Désél.")
        btn_groups_c  = QPushButton("Groupes  ▾")
        for b in [btn_sel_all_c, btn_desel_c, btn_groups_c]:
            b.setStyleSheet(_ES)
            b.setFixedHeight(28)
            es.addWidget(b)

        es.addStretch()

        # ── Réinitialiser positions ───────────────────────────────────
        btn_reset_pos_c = QPushButton("↺  Positions auto")
        btn_reset_pos_c.setToolTip("Remettre toutes les fixtures à leur position par défaut")
        btn_reset_pos_c.setStyleSheet(_ES)
        btn_reset_pos_c.setFixedHeight(28)
        es.addWidget(btn_reset_pos_c)

        vl_canvas.addWidget(edit_strip)

        proxy = _PatchCanvasProxy(self.projectors, self)
        canvas = FixtureCanvas(proxy)
        proxy.canvas_widget = canvas
        vl_canvas.addWidget(canvas)

        canvas_timer = QTimer(dialog)
        canvas_timer.timeout.connect(canvas.update)
        canvas_timer.start(80)

        tabs.addTab(tab_canvas, "🎭  Plan de feu")

        # ════════════════════════════════════════════════════════════════
        # DONNÉES + HELPERS
        # ════════════════════════════════════════════════════════════════
        fixture_data = []
        _sel        = [None]
        _cards      = []
        _history    = []
        _redo_stack = []

        def _rebuild_fd():
            fixture_data.clear()
            for i, proj in enumerate(self.projectors):
                fixture_data.append({
                    'name':          proj.name or proj.group,
                    'fixture_type':  getattr(proj, 'fixture_type', 'PAR LED'),
                    'group':         proj.group,
                    'universe':      getattr(proj, 'universe', 0),
                    'start_address': proj.start_address,
                    'profile':       list(self.dmx._get_profile(f"{proj.group}_{i}")),
                    'channel_defaults':   dict(getattr(proj, 'channel_defaults', {})),
                    'color_wheel_slots':  list(getattr(proj, 'color_wheel_slots', [])),
                    'gobo_wheel_slots':   list(getattr(proj, 'gobo_wheel_slots', [])),
                })

        _rebuild_fd()

        def _apply_fd_to_dmx():
            """Applique fixture_data au DMX en respectant les profils choisis par l'utilisateur."""
            self.dmx.clear_patch()
            for i, fd in enumerate(fixture_data):
                if i >= len(self.projectors):
                    continue
                proj = self.projectors[i]
                proj_key = f"{proj.group}_{i}"
                profile = fd.get('profile') or list(DMX_PROFILES['RGBDS'])
                if isinstance(profile, list) and profile:
                    proj.dmx_profile = list(profile)
                proj.channel_defaults  = dict(fd.get('channel_defaults', {}))
                proj.color_wheel_slots = list(fd.get('color_wheel_slots', []))
                proj.gobo_wheel_slots  = list(fd.get('gobo_wheel_slots', []))
                uni = fd.get('universe', 0)
                proj.universe = uni
                channels = [fd['start_address'] + c for c in range(len(profile))]
                self.dmx.set_projector_patch(proj_key, channels, universe=uni, profile=profile)

        def _push_history():
            snap = []
            for i, fd in enumerate(fixture_data):
                entry = dict(fd)
                if i < len(self.projectors):
                    p = self.projectors[i]
                    entry['canvas_x'] = getattr(p, 'canvas_x', None)
                    entry['canvas_y'] = getattr(p, 'canvas_y', None)
                snap.append(entry)
            _history.append(snap)
            _redo_stack.clear()
            if len(_history) > 40:
                _history.pop(0)

        def _snapshot_current():
            snap = []
            for i, fd in enumerate(fixture_data):
                entry = dict(fd)
                if i < len(self.projectors):
                    p = self.projectors[i]
                    entry['canvas_x'] = getattr(p, 'canvas_x', None)
                    entry['canvas_y'] = getattr(p, 'canvas_y', None)
                snap.append(entry)
            return snap

        # Snapshot à l'ouverture — utilisé pour "Ignorer les modifications"
        _initial_snap = _snapshot_current()

        def _restore_snap(snap):
            del self.projectors[:]
            fixture_data.clear()
            for fd_s in snap:
                p = Projector(fd_s['group'], name=fd_s['name'], fixture_type=fd_s['fixture_type'])
                p.universe      = fd_s.get('universe', 0)
                p.start_address = fd_s['start_address']
                p.canvas_x = fd_s.get('canvas_x')
                p.canvas_y = fd_s.get('canvas_y')
                if p.fixture_type == "Machine a fumee":
                    p.fan_speed = 0
                self.projectors.append(p)
                fixture_data.append({
                    'name':          fd_s['name'],
                    'fixture_type':  fd_s['fixture_type'],
                    'group':         fd_s['group'],
                    'start_address': fd_s['start_address'],
                    'profile':       fd_s.get('profile', []),
                })
            self._rebuild_dmx_patch()
            _build_cards(filter_bar.text())
            _sel[0] = None
            det_stack.setCurrentIndex(0)
            proxy.selected_lamps.clear()
            canvas.update()

        def _undo():
            if not _history: return
            _redo_stack.append(_snapshot_current())
            _restore_snap(_history.pop())

        def _redo():
            if not _redo_stack: return
            _history.append(_snapshot_current())
            _restore_snap(_redo_stack.pop())

        def _get_conflicts():
            occ = {}
            for i, fd in enumerate(fixture_data):
                uni = fd.get('universe', 0)
                for c in range(fd['start_address'], fd['start_address'] + len(fd['profile'])):
                    occ.setdefault((uni, c), []).append(i)
            return {i for lst in occ.values() if len(lst) > 1 for i in lst}

        def _update_conflict_banner(conflicts):
            if conflicts and tabs.currentIndex() == 0:
                n = len(conflicts)
                conflict_banner.setText(
                    f"  ⚠  {n} fixture{'s' if n > 1 else ''} avec des canaux DMX qui se chevauchent"
                    "  —  utilisez ⚡ Auto-addr. pour corriger"
                )
                conflict_banner.setVisible(True)
            else:
                conflict_banner.setVisible(False)

        tabs.currentChanged.connect(lambda _: _update_conflict_banner(_get_conflicts()))
        def _update_chips(profile):
            while chips_vl.count():
                item = chips_vl.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            if not profile:
                return

            cur_idx = _sel[0]
            fd_cur = fixture_data[cur_idx] if cur_idx is not None and cur_idx < len(fixture_data) else {}
            ch_defs = fd_cur.get('channel_defaults', {})

            def _set_default(ch_type, pct, snap_idx):
                """Applique une valeur par défaut (0-100%) et rafraîchit l'affichage."""
                dmx_val = int(round(pct / 100.0 * 255))
                if snap_idx is not None and snap_idx < len(fixture_data):
                    fixture_data[snap_idx].setdefault('channel_defaults', {})[ch_type] = dmx_val
                    if snap_idx < len(self.projectors):
                        self.projectors[snap_idx].channel_defaults[ch_type] = dmx_val
                    _mark_dirty()

            def _show_default_popup(chip_lbl, ch_type, snap_idx, col):
                """Menu clic droit : curseur 0-100% pour régler la valeur par défaut."""
                from PySide6.QtWidgets import QMenu, QWidgetAction, QSlider, QLabel as _QL
                pct_cur = int(round(ch_defs.get(ch_type, 0) / 255.0 * 100))

                m = QMenu(chip_lbl)
                m.setStyleSheet(
                    "QMenu { background:#0e0e0e; border:1px solid #2a2a2a; border-radius:8px; padding:4px; }"
                    "QMenu::item { padding:0; background:transparent; }"
                )
                wa = QWidgetAction(m)
                w = QWidget()
                w.setStyleSheet("background:#0e0e0e; border-radius:6px;")
                wl = QVBoxLayout(w)
                wl.setContentsMargins(12, 10, 12, 10)
                wl.setSpacing(8)

                title = _QL(f"Défaut  {ch_type}")
                title.setStyleSheet(
                    f"color:{col}; font-size:10px; font-weight:bold;"
                    f" background:transparent; border:none; letter-spacing:1px;"
                )
                title.setAlignment(Qt.AlignCenter)
                wl.addWidget(title)

                val_lbl = _QL(f"{pct_cur}%")
                val_lbl.setAlignment(Qt.AlignCenter)
                val_lbl.setStyleSheet(
                    f"color:#ffffff; font-size:20px; font-weight:bold;"
                    f" background:transparent; border:none;"
                )
                wl.addWidget(val_lbl)

                sli = QSlider(Qt.Horizontal)
                sli.setRange(0, 100)
                sli.setValue(pct_cur)
                sli.setFixedWidth(200)
                sli.setFixedHeight(28)
                sli.setStyleSheet(
                    f"QSlider {{ background:transparent; }}"
                    f"QSlider::groove:horizontal {{"
                    f"  background:#1e1e1e; height:6px; border-radius:3px;"
                    f"  border:1px solid #2a2a2a;"
                    f"}}"
                    f"QSlider::handle:horizontal {{"
                    f"  background:{col}; width:18px; height:18px;"
                    f"  margin:-6px 0; border-radius:9px;"
                    f"  border:2px solid #0e0e0e;"
                    f"}}"
                    f"QSlider::handle:horizontal:hover {{"
                    f"  background:#ffffff;"
                    f"}}"
                    f"QSlider::sub-page:horizontal {{"
                    f"  background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                    f"  stop:0 {col}66, stop:1 {col});"
                    f"  border-radius:3px;"
                    f"}}"
                    f"QSlider::add-page:horizontal {{"
                    f"  background:#1e1e1e; border-radius:3px;"
                    f"}}"
                )

                def _on_slide(v):
                    val_lbl.setText(f"{v}%")
                    _set_default(ch_type, v, snap_idx)
                    ch_defs[ch_type] = int(round(v / 100.0 * 255))
                    pct_txt = f"{v}%" if v > 0 else ""
                    chip_lbl.setToolTip(
                        f"Canal {ch_type} — clic droit pour régler le défaut\nDéfaut actuel : {v}%"
                    )
                    # Mettre à jour le petit label %
                    chip_lbl.setProperty("def_pct", v)
                    chip_lbl.update()

                sli.valueChanged.connect(_on_slide)
                wl.addWidget(sli, 0, Qt.AlignHCenter)

                wa.setDefaultWidget(w)
                m.addAction(wa)
                m.exec(chip_lbl.mapToGlobal(chip_lbl.rect().bottomLeft()))

            row_p = QWidget(); row_p.setStyleSheet("background:transparent;")
            rp = QHBoxLayout(row_p); rp.setContentsMargins(0, 0, 0, 0); rp.setSpacing(4)
            row_n = QWidget(); row_n.setStyleSheet("background:transparent;")
            rn = QHBoxLayout(row_n); rn.setContentsMargins(0, 0, 0, 0); rn.setSpacing(4)
            row_u = QWidget(); row_u.setStyleSheet("background:transparent;")
            ru = QHBoxLayout(row_u); ru.setContentsMargins(0, 0, 0, 0); ru.setSpacing(4)

            for ci, ch in enumerate(profile):
                col = CH_COLORS.get(ch, "#444455")
                cw = max(36, len(ch) * 7 + 14)
                _r = int(col[1:3], 16); _g = int(col[3:5], 16); _b = int(col[5:7], 16)
                text_col = "#ffffff" if (_r * 0.299 + _g * 0.587 + _b * 0.114) < 145 else "#111111"

                # Petit label % au-dessus
                pct_val = int(round(ch_defs.get(ch, 0) / 255.0 * 100))
                pct_lbl = QLabel(f"{pct_val}%" if pct_val > 0 else "")
                pct_lbl.setFixedWidth(cw)
                pct_lbl.setAlignment(Qt.AlignCenter)
                pct_lbl.setStyleSheet(
                    f"color:{col}; font-size:8px; background:transparent; border:none;"
                )

                chip = QLabel(ch)
                chip.setFixedSize(cw, 24)
                chip.setAlignment(Qt.AlignCenter)
                chip.setStyleSheet(
                    f"background:{col}; color:{text_col}; border:none;"
                    f" border-radius:5px; font-size:10px; font-weight:bold;"
                )
                chip.setToolTip(
                    f"Canal {ci + 1}: {ch}"
                    + (f"\nDéfaut : {pct_val}%" if pct_val > 0 else "\nClic droit → régler valeur par défaut")
                )
                chip.setCursor(Qt.PointingHandCursor)

                num = QLabel(str(ci + 1))
                num.setFixedWidth(cw)
                num.setAlignment(Qt.AlignCenter)
                num.setStyleSheet(f"color:{col}; font-size:9px; font-weight:bold; border:none; background:transparent;")

                # Clic droit → popup curseur
                def _make_ctx(c=chip, ch_type=ch, si=cur_idx, color=col, pl=pct_lbl):
                    def _ctx(event):
                        if event.button() == Qt.RightButton:
                            _show_default_popup(c, ch_type, si, color)
                            # Rafraîchir le % après fermeture du menu
                            new_pct = int(round(
                                fixture_data[si].get('channel_defaults', {}).get(ch_type, 0) / 255.0 * 100
                            )) if si is not None and si < len(fixture_data) else 0
                            pl.setText(f"{new_pct}%" if new_pct > 0 else "")
                    return _ctx
                chip.mousePressEvent = _make_ctx()

                rp.addWidget(pct_lbl)
                rn.addWidget(chip)
                ru.addWidget(num)

            rp.addStretch(); rn.addStretch(); ru.addStretch()
            chips_vl.addWidget(row_p)
            chips_vl.addWidget(row_n)
            chips_vl.addWidget(row_u)


        _dirty = [False]
        _checked = set()

        def _mark_dirty():
            if not _dirty[0]:
                _dirty[0] = True
                btn_save.setEnabled(True)

        def _do_save():
            _apply_fd_to_dmx()
            self.save_dmx_patch_config()
            _dirty[0] = False
            btn_save.setEnabled(False)

        def _refresh_group_blocks(current_group=None):
            if current_group is not None:
                _selected_group[0] = current_group
            cg = _selected_group[0]
            info = next(((g, l, n, c) for g, l, n, c in GROUP_BLOCKS if g == cg), None)
            if info:
                _, letter, name, color = info
                btn_group.setText(letter)
                btn_group.setToolTip(name)
                btn_group.setStyleSheet(
                    f"QPushButton {{ background:{color}; color:#ffffff; border:none;"
                    f" border-radius:7px; font-size:16px; font-weight:bold; }}"
                    f"QPushButton:hover {{ background:{color}cc; }}"
                )
            else:
                btn_group.setText("—")
                btn_group.setToolTip("")
                btn_group.setStyleSheet(
                    "QPushButton { background:#1a1a1a; color:#fff; border:1px solid #2a2a2a;"
                    " border-radius:7px; font-size:15px; font-weight:bold; }"
                    "QPushButton:hover { border-color:#444; }"
                )

        def _show_group_menu():
            _MNS = (
                "QMenu { background:#141414; border:1px solid #2a2a2a; border-radius:6px; padding:4px; }"
                "QMenu::item { padding:8px 24px 8px 12px; border-radius:4px; color:#bbb; font-size:14px; font-weight:bold; }"
                "QMenu::item:selected { background:#1e1e1e; color:#fff; }"
            )
            m = QMenu(btn_group)
            m.setStyleSheet(_MNS)
            # Dédupliquer par lettre : une seule entrée par lettre
            seen_letters = {}
            for g, letter, name, color in GROUP_BLOCKS:
                if letter not in seen_letters:
                    seen_letters[letter] = (g, letter, color)
            current_letter = next(
                (l for g, l, n, c in GROUP_BLOCKS if g == _selected_group[0]), None
            )
            for letter, (g, _, color) in seen_letters.items():
                act = m.addAction(letter)
                act.setData(letter)
                px = QPixmap(14, 14)
                px.fill(QColor(color))
                act.setIcon(QIcon(px))
                if letter == current_letter:
                    font = act.font()
                    font.setBold(True)
                    act.setFont(font)
            chosen = m.exec(btn_group.mapToGlobal(QPoint(0, btn_group.height() + 2)))
            if chosen:
                chosen_letter = chosen.data()
                # Garder le groupe interne si on est déjà dans cette lettre
                groups_for_letter = [g for g, l, n, c in GROUP_BLOCKS if l == chosen_letter]
                if _selected_group[0] not in groups_for_letter:
                    _selected_group[0] = groups_for_letter[0]
                _refresh_group_blocks()
                _commit()

        btn_group.clicked.connect(_show_group_menu)

        def _update_addr_range():
            if _sel[0] is None or _sel[0] >= len(fixture_data):
                return
            fd  = fixture_data[_sel[0]]
            n   = len(fd['profile'])
            end = addr_sb.value() + n - 1
            if end > 512:
                lbl_addr_range.setText(f"→ CH {end}  ⚠ dépasse 512 !")
                lbl_addr_range.setStyleSheet("color:#ff6644; font-size:12px; padding-left:6px; border:none;")
            else:
                lbl_addr_range.setText(f"→ CH {end}   ({n} canal{'x' if n > 1 else ''})")
                lbl_addr_range.setStyleSheet("color:#2a2a2a; font-size:12px; padding-left:6px; border:none;")
        def _make_card(idx):
            fd    = fixture_data[idx]
            group = fd['group']
            gc    = _GC.get(group, "#666666")
            end_ch   = fd['start_address'] + len(fd['profile']) - 1
            uni_lbl  = f"U{fd.get('universe', 0) + 1} "
            gname    = self.GROUP_DISPLAY.get(group, group)

            from PySide6.QtWidgets import QCheckBox
            card = QFrame()
            card.setFixedHeight(60)
            card.setCursor(Qt.PointingHandCursor)

            def _upd(selected, conflict):
                _gc = card._gc
                checked = idx in _checked
                bg = "#10102a" if selected else ("#0f0f18" if checked else "#0b0b0b")
                card.setStyleSheet(
                    f"QFrame {{ background:{bg}; border-left:4px solid {_gc};"
                    f" border-top:1px solid {'#1e1e3a' if selected else '#141414'};"
                    f" border-bottom:1px solid #141414; border-right:none; border-radius:0; }}"
                )
                if hasattr(card, '_chlbl'):
                    card._chlbl.setStyleSheet(
                        f"color:{'#ff6644' if conflict else '#33ddff' if selected else '#00d4ff'};"
                        f" font-size:11px; font-weight:bold; border:none; background:transparent;"
                    )

            card._gc  = gc
            card._upd = _upd
            card._upd(False, False)

            hl = QHBoxLayout(card)
            hl.setContentsMargins(6, 0, 14, 0)
            hl.setSpacing(6)

            chk = QCheckBox()
            chk.setChecked(idx in _checked)
            chk.setStyleSheet(
                "QCheckBox { border:none; background:transparent; }"
                "QCheckBox::indicator { width:14px; height:14px; border:1px solid #2a2a2a;"
                " border-radius:3px; background:#111; }"
                "QCheckBox::indicator:checked { background:#00d4ff; border-color:#00d4ff; }"
            )
            card._chk = chk
            hl.addWidget(chk)

            dot = QLabel("●")
            dot.setFixedWidth(13)
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet("color:#1c1c1c; font-size:13px; border:none; background:transparent;")
            card._dot = dot
            hl.addWidget(dot)

            tv = QVBoxLayout()
            tv.setSpacing(2)
            tv.setContentsMargins(0, 0, 0, 0)
            nm = QLabel(fd['name'] or self.GROUP_DISPLAY.get(fd['group'], fd['group']))
            nm.setFont(QFont("Segoe UI", 11, QFont.Bold))
            nm.setStyleSheet("color:#ddd; font-size:12px; font-weight:bold; border:none; background:transparent;")
            card._namelbl = nm
            sub = QLabel(f"{fd['fixture_type']}  ·  Groupe {gname}")
            _sub_col = "#{:02x}{:02x}{:02x}".format(
                (int(gc[1:3], 16) + 0x44) // 2,
                (int(gc[3:5], 16) + 0x44) // 2,
                (int(gc[5:7], 16) + 0x44) // 2,
            ) if len(gc) == 7 else "#545454"
            sub.setStyleSheet(f"color:{_sub_col}; font-size:10px; border:none; background:transparent;")
            card._sublbl_color = _sub_col
            card._sublbl = sub
            tv.addWidget(nm); tv.addWidget(sub)
            hl.addLayout(tv)
            hl.addStretch()

            _uni_n = fd.get('universe', 0) + 1
            chl = QLabel(f'<span style="color:#2a6670">U{_uni_n}</span>'
                         f'<span style="color:#00d4ff">  ·  CH {fd["start_address"]}–{end_ch}</span>')
            chl.setTextFormat(Qt.RichText)
            chl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            chl.setStyleSheet("font-size:11px; font-weight:bold; border:none; background:transparent;")
            card._chlbl = chl
            hl.addWidget(chl)

            def _on_check(state, i=idx):
                if state:
                    _checked.add(i)
                else:
                    _checked.discard(i)
                n_chk = len(_checked)
                _show = n_chk > 0
                btn_del_multi.setVisible(_show)
                btn_del_multi.setText(f"🗑  Supprimer ({n_chk})" if n_chk > 1 else "🗑  Supprimer")
                btn_rename_multi.setVisible(_show)
                btn_rename_multi.setText(f"✏  Renommer ({n_chk})" if n_chk > 1 else "✏  Renommer")
                btn_group_multi.setVisible(_show)
                btn_desel_multi.setVisible(_show)
                if i < len(_cards) and _cards[i] is not None:
                    _cards[i]._upd(i == _sel[0], i in _get_conflicts())
            chk.stateChanged.connect(_on_check)

            def _on_card_click(e, i=idx):
                if e.button() != Qt.LeftButton:
                    return
                mods = e.modifiers()
                if mods & Qt.ControlModifier:
                    # Ctrl+clic : bascule la checkbox de multi-sélection
                    if i < len(_cards) and _cards[i] is not None:
                        chk = _cards[i]._chk
                        chk.setChecked(not chk.isChecked())
                elif mods & Qt.ShiftModifier:
                    # Shift+clic : sélection de plage depuis la dernière carte active
                    anchor = _sel[0] if _sel[0] is not None else i
                    for j in range(min(anchor, i), max(anchor, i) + 1):
                        if j < len(_cards) and _cards[j] is not None:
                            _cards[j]._chk.setChecked(True)
                else:
                    _select_card(i)
            card.mousePressEvent = _on_card_click
            return card
        def _build_cards(filter_text=""):
            while card_vl.count() > 1:
                item = card_vl.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            _cards.clear()
            ft = filter_text.strip().lower()
            conflicts = _get_conflicts()
            # Créer toutes les cartes indexées par fixture_idx
            for idx, fd in enumerate(fixture_data):
                if ft:
                    hay = (fd['name'] + fd['fixture_type'] +
                           self.GROUP_DISPLAY.get(fd['group'], fd['group'])).lower()
                    if ft not in hay:
                        _cards.append(None)
                        continue
                card = _make_card(idx)
                card._upd(idx == _sel[0], idx in conflicts)
                _cards.append(card)
            # Insérer dans l'ordre de tri
            visible = [i for i, c in enumerate(_cards) if c is not None]
            sm = _sort_mode[0]
            if sm == "name":
                visible.sort(key=lambda i: fixture_data[i]['name'].lower())
            elif sm == "group":
                visible.sort(key=lambda i: (
                    self.GROUP_DISPLAY.get(fixture_data[i]['group'], fixture_data[i]['group']),
                    fixture_data[i]['name'].lower()
                ))
            else:  # dmx (défaut)
                visible.sort(key=lambda i: (fixture_data[i].get('universe', 0), fixture_data[i]['start_address']))
            for i in visible:
                card_vl.insertWidget(card_vl.count() - 1, _cards[i])
            n = len(fixture_data)
            lbl_cnt.setText(f"{n} fixture{'s' if n != 1 else ''}")
            _update_conflict_banner(conflicts)
        def _select_card(idx):
            if _sel[0] is not None and _sel[0] < len(_cards):
                old = _cards[_sel[0]]
                if old is not None:
                    old._upd(False, _sel[0] in _get_conflicts())
            _sel[0] = idx
            if idx is None:
                det_stack.setCurrentIndex(0)
                return
            conflicts = _get_conflicts()
            if idx < len(_cards) and _cards[idx] is not None:
                _cards[idx]._upd(True, idx in conflicts)
            det_stack.setCurrentIndex(1)
            fd = fixture_data[idx]
            gc = _GC.get(fd['group'], "#888")
            lbl_det_name.setText(fd['name'] or fd['group'])
            lbl_det_group.setText(f"  {self.GROUP_DISPLAY.get(fd['group'], fd['group'])}")
            lbl_det_group.setStyleSheet(f"color:{gc}; font-size:12px; border:none; background:transparent;")
            det_name_e.blockSignals(True);  det_name_e.setText(fd['name']);  det_name_e.blockSignals(False)
            det_type_cb.blockSignals(True)
            if fd['fixture_type'] in FIXTURE_TYPES:
                det_type_cb.setCurrentIndex(FIXTURE_TYPES.index(fd['fixture_type']))
            det_type_cb.blockSignals(False)
            _refresh_group_blocks(fd['group'])
            uni_cb.blockSignals(True);   uni_cb.setCurrentIndex(fd.get('universe', 0));  uni_cb.blockSignals(False)
            addr_sb.blockSignals(True);  addr_sb.setValue(fd['start_address']);           addr_sb.blockSignals(False)
            _update_addr_range()
            _update_chips(fd['profile'])
            proj_fh = getattr(self.projectors[idx], 'fixture_height', None)
            height_sb.blockSignals(True)
            height_sb.setValue(proj_fh if proj_fh is not None else 7.0)
            height_sb.blockSignals(False)
            proj_br = getattr(self.projectors[idx], 'body_rotation', 0.0)
            body_rot_sb.blockSignals(True)
            body_rot_sb.setValue(int(proj_br))
            body_rot_sb.blockSignals(False)
            if idx in conflicts:
                others = []
                for j, fd2 in enumerate(fixture_data):
                    if j == idx: continue
                    if fd2.get('universe', 0) != fd.get('universe', 0): continue
                    s1, e1 = fd['start_address'], fd['start_address'] + len(fd['profile']) - 1
                    s2, e2 = fd2['start_address'], fd2['start_address'] + len(fd2['profile']) - 1
                    if s1 <= e2 and s2 <= e1:
                        others.append(fd2['name'] or fd2['group'])
                lbl_conflict_det.setText(f"⚠  Chevauchement avec : {', '.join(others)}")
                lbl_conflict_det.setVisible(True)
            else:
                lbl_conflict_det.setVisible(False)
            if idx < len(_cards) and _cards[idx] is not None:
                scroll.ensureWidgetVisible(_cards[idx])
        def _commit():
            idx = _sel[0]
            if idx is None or idx >= len(fixture_data): return
            _push_history()
            fd   = fixture_data[idx]
            proj = self.projectors[idx]
            fd['name']          = det_name_e.text().strip() or fd['group']
            fd['fixture_type']  = det_type_cb.currentText()
            fd['group']         = _selected_group[0] or fd['group']
            fd['universe']      = uni_cb.currentData()
            fd['start_address'] = addr_sb.value()
            proj.name           = fd['name']
            proj.fixture_type    = fd['fixture_type']
            proj.group           = fd['group']
            proj.universe        = fd['universe']
            proj.start_address   = fd['start_address']
            proj.fixture_height  = height_sb.value()
            proj.body_rotation   = float(body_rot_sb.value())
            if fd.get('profile'):
                proj.dmx_profile = fd['profile']
            _apply_fd_to_dmx()
            _mark_dirty()
            conflicts = _get_conflicts()
            _update_conflict_banner(conflicts)
            # Mettre à jour TOUTES les cartes affectées (sélectionnée + celles en conflit)
            for ci, c2 in enumerate(_cards):
                if c2 is not None and ci != idx:
                    c2._upd(False, ci in conflicts)
            if idx < len(_cards) and _cards[idx] is not None:
                card = _cards[idx]
                # Mettre a jour la couleur de groupe (bordure + sous-titre)
                new_gc = _GC.get(fd['group'], "#666666")
                card._gc = new_gc
                _sub_col = "#{:02x}{:02x}{:02x}".format(
                    (int(new_gc[1:3], 16) + 0x44) // 2,
                    (int(new_gc[3:5], 16) + 0x44) // 2,
                    (int(new_gc[5:7], 16) + 0x44) // 2,
                ) if len(new_gc) == 7 else "#545454"
                card._namelbl.setText(fd['name'] or self.GROUP_DISPLAY.get(fd['group'], fd['group']))
                card._sublbl.setText(
                    f"{fd['fixture_type']}  ·  Groupe {self.GROUP_DISPLAY.get(fd['group'], fd['group'])}"
                )
                card._sublbl.setStyleSheet(
                    f"color:{_sub_col}; font-size:10px; border:none; background:transparent;"
                )
                end_ch = fd['start_address'] + len(fd['profile']) - 1
                _u = fd.get('universe', 0) + 1
                _e = fd['start_address'] + len(fd['profile']) - 1
                card._chlbl.setText(
                    f'<span style="color:#2a6670">U{_u}</span>'
                    f'<span style="color:#00d4ff">  ·  CH {fd["start_address"]}–{_e}</span>'
                )
                card._upd(True, idx in conflicts)
            lbl_det_name.setText(fd['name'])
            gc = _GC.get(fd['group'], "#888")
            lbl_det_group.setText(f"  {self.GROUP_DISPLAY.get(fd['group'], fd['group'])}")
            lbl_det_group.setStyleSheet(f"color:{gc}; font-size:12px; border:none; background:transparent;")
            _update_addr_range()
            if idx in conflicts:
                others = []
                for j, fd2 in enumerate(fixture_data):
                    if j == idx: continue
                    if fd2.get('universe', 0) != fd.get('universe', 0): continue
                    s1, e1 = fd['start_address'], fd['start_address'] + len(fd['profile']) - 1
                    s2, e2 = fd2['start_address'], fd2['start_address'] + len(fd2['profile']) - 1
                    if s1 <= e2 and s2 <= e1:
                        others.append(fd2['name'] or fd2['group'])
                lbl_conflict_det.setText(f"⚠  Chevauchement avec : {', '.join(others)}")
                lbl_conflict_det.setVisible(True)
            else:
                lbl_conflict_det.setVisible(False)
        _name_tmr = QTimer(dialog)
        _name_tmr.setSingleShot(True)
        _name_tmr.setInterval(500)
        _name_tmr.timeout.connect(_commit)
        det_name_e.textChanged.connect(lambda _: _name_tmr.start())

        def _on_type_changed():
            """Quand le type change : mettre à jour les chips et sauvegarder."""
            idx = _sel[0]
            if idx is None or idx >= len(fixture_data):
                return
            _update_chips(fixture_data[idx].get('profile', []))
            _commit()

        det_type_cb.currentIndexChanged.connect(lambda _: _on_type_changed())

        uni_cb.currentIndexChanged.connect(lambda _: _commit())
        addr_sb.valueChanged.connect(lambda _: (_update_addr_range(), _commit()))
        btn_am.clicked.connect(lambda: addr_sb.setValue(max(1, addr_sb.value() - 1)))
        btn_ap.clicked.connect(lambda: addr_sb.setValue(min(512, addr_sb.value() + 1)))

        def _del_selected():
            idx = _sel[0]
            if idx is None or idx >= len(fixture_data): return
            fname = fixture_data[idx]['name']
            if QMessageBox.question(
                dialog, "Supprimer", f"Supprimer « {fname} » ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes: return
            _push_history()
            fixture_data.pop(idx)
            if 0 <= idx < len(self.projectors):
                self.projectors.pop(idx)
            _sel[0] = None
            _checked.discard(idx)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _build_cards(filter_bar.text())
            det_stack.setCurrentIndex(0)
            _mark_dirty()

        btn_det_del.clicked.connect(_del_selected)

        def _locate_selected():
            """Bascule sur l'onglet Plan de feu et sélectionne la fixture courante."""
            idx = _sel[0]
            if idx is None or idx >= len(self.projectors):
                return
            proj = self.projectors[idx]
            # Calculer le local_idx dans son groupe
            g_cnt = {}
            local_idx = 0
            for i, p in enumerate(self.projectors):
                li = g_cnt.get(p.group, 0)
                g_cnt[p.group] = li + 1
                if i == idx:
                    local_idx = li
                    break
            proxy.selected_lamps.clear()
            proxy.selected_lamps.add((proj.group, local_idx))
            canvas.update()
            tabs.setCurrentIndex(1)

        btn_det_locate.clicked.connect(_locate_selected)

        def _replace_selected():
            idx = _sel[0]
            if idx is None or idx >= len(fixture_data):
                return
            import json as _json
            from builtin_fixtures import BUILTIN_FIXTURES as _BF

            # Charger toutes les fixtures disponibles
            _user_fx = []
            try:
                _fx_file = Path.home() / ".mystrow_fixtures.json"
                if _fx_file.exists():
                    _raw = _json.loads(_fx_file.read_text(encoding="utf-8"))
                    if isinstance(_raw, list):
                        for _f in _raw:
                            if not isinstance(_f, dict) or _f.get("builtin"):
                                continue
                            if not _f.get("profile") and _f.get("modes"):
                                _f["profile"] = _f["modes"][0].get("profile", [])
                            _user_fx.append(_f)
            except Exception:
                pass
            _custom_fx = []
            try:
                from fixture_editor import _load_custom_bundle as _lcb2
                _seen2 = {(f["name"], f.get("manufacturer", "")) for f in list(_BF) + _user_fx}
                for _cf in _lcb2():
                    if not isinstance(_cf, dict) or not _cf.get("name"):
                        continue
                    _k = (_cf["name"], _cf.get("manufacturer", ""))
                    if _k in _seen2:
                        continue
                    if not _cf.get("profile") and _cf.get("modes"):
                        _cf = dict(_cf)
                        _cf["profile"] = _cf["modes"][0].get("profile", [])
                    _custom_fx.append(_cf)
                    _seen2.add(_k)
            except Exception:
                pass
            _all = list(_BF) + _user_fx + _custom_fx

            # ── Picker ───────────────────────────────────────────────────────
            from PySide6.QtWidgets import QListWidget as _QListWidget, QListWidgetItem as _QLWI
            _SS2 = (
                "QDialog{background:#141414;color:#e0e0e0;}"
                "QListWidget{background:#1e1e1e;color:#e0e0e0;border:1px solid #333;"
                "border-radius:6px;font-size:12px;outline:none;}"
                "QListWidget::item{padding:6px 12px;}"
                "QListWidget::item:selected{background:#00d4ff;color:#000;font-weight:bold;}"
                "QListWidget::item:hover:!selected{background:#2a2a2a;}"
                "QLineEdit{background:#1e1e1e;color:#fff;border:1px solid #444;"
                "border-radius:6px;padding:6px 12px;font-size:13px;}"
                "QLineEdit:focus{border-color:#00d4ff88;}"
                "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #444;"
                "border-radius:6px;padding:6px 16px;font-size:12px;}"
                "QPushButton:hover{border-color:#00d4ff;color:#fff;}"
            )
            pick = QDialog(dialog)
            pick.setWindowTitle("Remplacer par…")
            pick.resize(600, 480)
            pick.setStyleSheet(_SS2)
            pv = QVBoxLayout(pick)
            pv.setContentsMargins(16, 14, 16, 14)
            pv.setSpacing(10)

            srch = QLineEdit()
            srch.setPlaceholderText("🔍  Rechercher…")
            srch.setFixedHeight(36)
            pv.addWidget(srch)

            plst = _QListWidget()
            pv.addWidget(plst, 1)

            pbr = QHBoxLayout()
            pok = QPushButton("Remplacer")
            pok.setFixedHeight(36)
            pok.setStyleSheet(
                "QPushButton{background:#00d4ff;color:#000;font-weight:bold;"
                "border:none;border-radius:6px;padding:6px 24px;font-size:13px;}"
                "QPushButton:hover{background:#33ddff;}"
            )
            pcancel = QPushButton("Annuler")
            pcancel.setFixedHeight(36)
            pcancel.clicked.connect(pick.reject)
            pbr.addStretch()
            pbr.addWidget(pcancel)
            pbr.addWidget(pok)
            pv.addLayout(pbr)

            def _pfill(q=""):
                plst.clear()
                q = q.strip().lower()
                for _fx in _all:
                    if q and q not in _fx.get("name", "").lower() \
                           and q not in _fx.get("fixture_type", "").lower() \
                           and q not in _fx.get("manufacturer", "").lower():
                        continue
                    _n   = _fx.get("name", "?")
                    _mfr = _fx.get("manufacturer", "")
                    _nch = len(_fx.get("profile", []))
                    _lbl = f"{_n}  ({_nch}ch)"
                    if _mfr:
                        _lbl += f"   — {_mfr}"
                    _item = _QLWI(_lbl)
                    _item.setData(Qt.UserRole, _fx)
                    plst.addItem(_item)
                if plst.count():
                    plst.setCurrentRow(0)

            srch.textChanged.connect(_pfill)
            _pfill()
            srch.setFocus()

            _pick_result = [None]

            def _paccept():
                _it = plst.currentItem()
                if not _it:
                    return
                _pick_result[0] = _it.data(Qt.UserRole)
                pick.accept()

            pok.clicked.connect(_paccept)
            plst.itemDoubleClicked.connect(lambda _: _paccept())

            pick.exec()
            new_fx = _pick_result[0]
            if not new_fx:
                return

            # ── Appliquer le remplacement ─────────────────────────────────
            _push_history()
            fd  = fixture_data[idx]
            proj = self.projectors[idx]

            fd['name']         = new_fx.get("name", fd['name'])
            fd['fixture_type'] = new_fx.get("fixture_type", fd['fixture_type'])
            fd['profile']      = list(new_fx.get("profile", fd['profile']))
            # start_address et group sont conservés

            proj.name         = fd['name']
            proj.fixture_type = fd['fixture_type']
            proj.dmx_profile  = fd['profile']

            _apply_fd_to_dmx()
            _mark_dirty()

            # Rafraîchir le panneau de détail
            _sel[0] = None
            _build_cards(filter_bar.text())
            _select_card(idx)

        btn_det_replace.clicked.connect(_replace_selected)

        def _del_checked():
            if not _checked: return
            n = len(_checked)
            names = [fixture_data[i]['name'] for i in sorted(_checked) if i < len(fixture_data)]
            msg = f"Supprimer {n} fixture{'s' if n > 1 else ''} ?\n" + "\n".join(f"  • {nm}" for nm in names[:8])
            if QMessageBox.question(dialog, "Supprimer", msg,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            _push_history()
            for i in sorted(_checked, reverse=True):
                if i < len(fixture_data): fixture_data.pop(i)
                if i < len(self.projectors): self.projectors.pop(i)
            _checked.clear()
            _sel[0] = None
            btn_del_multi.setVisible(False)
            btn_rename_multi.setVisible(False)
            btn_group_multi.setVisible(False)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _build_cards(filter_bar.text())
            det_stack.setCurrentIndex(0)
            _mark_dirty()

        btn_del_multi.clicked.connect(_del_checked)

        def _update_dots():
            for i, card in enumerate(_cards):
                if card is None or i >= len(self.projectors): continue
                proj = self.projectors[i]
                if proj.muted or proj.level == 0:
                    col = "#1c1c1c"
                else:
                    col = proj.color.name() if hasattr(proj, 'color') and proj.color.isValid() else card._gc
                card._dot.setStyleSheet(
                    f"color:{col}; font-size:13px; border:none; background:transparent;"
                )
        def _add_fixture(norm_x=0.5, norm_y=0.5):
            res = self._show_fixture_library_dialog()
            if not res: return
            preset, qty, custom_name = res
            _push_history()
            _CH = {"PAR LED": 5, "Moving Head": 8, "Barre LED": 5,
                   "Stroboscope": 2, "Machine a fumee": 2}
            base_name = custom_name or preset.get('name', 'Fixture')

            # Calculer les positions canvas pour le batch
            if qty > 1:
                # Trouver un axe Y libre sur le plan de feu
                existing_ys = [p.canvas_y for p in self.projectors
                               if p.canvas_x is not None and p.canvas_y is not None]
                candidate_y = None
                for y_try in [0.85, 0.70, 0.55, 0.40, 0.25, 0.10]:
                    if not any(abs(ey - y_try) < 0.12 for ey in existing_ys):
                        candidate_y = y_try
                        break
                if candidate_y is None:
                    candidate_y = 0.5
                # Espacer uniformément en X : marges 5% de chaque côté
                canvas_positions = [((n + 1) / (qty + 1), candidate_y) for n in range(qty)]
            else:
                # Placer près du clic droit, en évitant les superpositions
                fx, fy = _find_free_canvas_pos(self.projectors, norm_x, norm_y)
                canvas_positions = [(fx, fy)]

            _preset_profile = preset.get('profile')
            if not (isinstance(_preset_profile, list) and _preset_profile):
                _preset_profile = None
            for n in range(qty):
                if self.projectors:
                    last = max(self.projectors, key=lambda p: p.start_address)
                    last_idx = self.projectors.index(last)
                    last_profile = getattr(last, 'dmx_profile', None)
                    if not (isinstance(last_profile, list) and last_profile):
                        last_profile = list(self.dmx._get_profile(f"{last.group}_{last_idx}"))
                    next_addr = last.start_address + len(last_profile)
                else:
                    next_addr = 1
                name = f"{base_name} {n + 1}" if qty > 1 else base_name
                p = Projector(
                    preset.get('group', 'face'),
                    name=name,
                    fixture_type=preset.get('fixture_type', 'PAR LED')
                )
                p.universe = preset.get('universe', 0)
                p.start_address = next_addr
                if _preset_profile:
                    p.dmx_profile = list(_preset_profile)
                p.canvas_x, p.canvas_y = canvas_positions[n]
                if p.fixture_type == "Machine a fumee":
                    p.fan_speed = 0
                # Copier les slots roue couleur/gobo depuis le preset OFL
                p.color_wheel_slots = list(preset.get('color_wheel_slots', []))
                p.gobo_wheel_slots  = list(preset.get('gobo_wheel_slots', []))
                self.projectors.append(p)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            new_idx = len(fixture_data) - 1
            _build_cards(filter_bar.text())
            _select_card(new_idx)
            _mark_dirty()
        def _auto_address():
            if QMessageBox.question(
                dialog, "Auto-adresser",
                "Recalculer automatiquement toutes les adresses DMX ?\n"
                "Les adresses seront réassignées de façon continue, sans espaces.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes: return
            _push_history()
            addr = 1
            uni  = 0
            for fd in fixture_data:
                if addr + len(fd['profile']) - 1 > 512:
                    uni  = min(uni + 1, 3)
                    addr = 1
                fd['universe']      = uni
                fd['start_address'] = addr
                addr += len(fd['profile'])
            for proj, fd in zip(self.projectors, fixture_data):
                proj.universe      = fd['universe']
                proj.start_address = fd['start_address']
            self._rebuild_dmx_patch()
            _mark_dirty()
            cur = _sel[0]
            _build_cards(filter_bar.text())
            if cur is not None: _select_card(cur)
        def _reset_defaults():
            if QMessageBox.question(
                dialog, "Réinitialiser",
                "Réinitialiser les fixtures par défaut ?\nToutes les modifications seront perdues.",
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes: return
            _push_history()
            self.projectors.clear()
            addr = 1
            uni  = 0
            for name, ftype, group in self._DEFAULT_FIXTURES:
                p = Projector(group, name=name, fixture_type=ftype)
                profile = list(DMX_PROFILES["2CH_FUMEE"] if group == "fumee" else DMX_PROFILES["RGBDS"])
                if addr + len(profile) - 1 > 512:
                    uni = min(uni + 1, 3)
                    addr = 1
                p.universe      = uni
                p.start_address = addr
                addr += len(profile)
                self.projectors.append(p)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _sel[0] = None
            _build_cards()
            det_stack.setCurrentIndex(0)
            _mark_dirty()
        def _open_wizard():
            # ── Choix : Assistant ou Patch vide ───────────────────────────
            choice_dlg = QDialog(dialog)
            choice_dlg.setWindowTitle("Nouveau Patch")
            choice_dlg.setFixedSize(360, 200)
            choice_dlg.setStyleSheet(
                "QDialog { background:#111; color:#ddd; }"
                "QLabel { background:transparent; }"
            )
            cl = QVBoxLayout(choice_dlg)
            cl.setContentsMargins(24, 20, 24, 20)
            cl.setSpacing(12)
            lbl = QLabel("Comment voulez-vous créer votre patch ?")
            lbl.setStyleSheet("font-size:13px; color:#eee;")
            lbl.setWordWrap(True)
            cl.addWidget(lbl)
            cl.addSpacing(4)
            btn_row = QHBoxLayout()
            btn_row.setSpacing(10)

            def _btn(text, desc, color):
                b = QPushButton()
                b.setFixedHeight(58)
                inner = QVBoxLayout(b)
                inner.setContentsMargins(10, 6, 10, 6)
                inner.setSpacing(2)
                t = QLabel(text)
                t.setStyleSheet(f"font-size:13px; font-weight:bold; color:{color}; background:transparent;")
                t.setAlignment(Qt.AlignCenter)
                d = QLabel(desc)
                d.setStyleSheet("font-size:10px; color:#666; background:transparent;")
                d.setAlignment(Qt.AlignCenter)
                inner.addWidget(t)
                inner.addWidget(d)
                b.setStyleSheet(
                    f"QPushButton {{ background:#1a1a1a; border:1px solid {color}33;"
                    f" border-radius:8px; }} "
                    f"QPushButton:hover {{ background:#222; border-color:{color}77; }}"
                )
                return b

            btn_wizard = _btn("🧙  Assistant", "Guidé étape par étape", "#00d4ff")
            btn_empty  = _btn("📄  Patch vide", "Partir d'un patch vierge", "#888888")
            btn_row.addWidget(btn_wizard)
            btn_row.addWidget(btn_empty)
            cl.addLayout(btn_row)

            _choice = [None]
            btn_wizard.clicked.connect(lambda: (_choice.__setitem__(0, "wizard"), choice_dlg.accept()))
            btn_empty.clicked.connect(lambda: (_choice.__setitem__(0, "empty"),  choice_dlg.accept()))

            if choice_dlg.exec() != QDialog.Accepted or _choice[0] is None:
                return

            # ── Vérification si patch existant ────────────────────────────
            if self.projectors:
                label = "l'assistant" if _choice[0] == "wizard" else "un patch vide"
                if QMessageBox.question(
                    dialog, "Nouveau Patch",
                    f"Cette action remplacera les {len(self.projectors)} fixture(s) existante(s).\n"
                    f"Continuer vers {label} ?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                ) != QMessageBox.Yes:
                    return

            # ── Patch vide ────────────────────────────────────────────────
            if _choice[0] == "empty":
                _push_history()
                self.projectors.clear()
                self._rebuild_dmx_patch()
                _rebuild_fd()
                _sel[0] = None
                _build_cards()
                det_stack.setCurrentIndex(0)
                return

            # ── Assistant ─────────────────────────────────────────────────
            wiz = NewPlanWizard(dialog)
            wiz.fixture_selector_cb = self._show_fixture_library_dialog  # FIX: câbler le sélecteur
            if wiz.exec() != QDialog.Accepted: return
            fixtures = wiz.get_result()
            if not fixtures: return
            _push_history()
            self.projectors.clear()
            for fdd in fixtures:
                p = Projector(fdd['group'], name=fdd['name'], fixture_type=fdd['fixture_type'])
                p.start_address = fdd['start_address']
                p.canvas_x = None; p.canvas_y = None
                _fdd_profile = fdd.get('profile')
                if isinstance(_fdd_profile, list) and _fdd_profile:
                    p.dmx_profile = list(_fdd_profile)
                if fdd['fixture_type'] == "Machine a fumee":
                    p.fan_speed = 0
                self.projectors.append(p)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _sel[0] = None
            _build_cards()
            det_stack.setCurrentIndex(0)

        # ── Renommer la sélection ─────────────────────────────────────────────
        def _rename_checked():
            if not _checked:
                return
            from PySide6.QtWidgets import QInputDialog
            indices = sorted(_checked)
            n = len(indices)
            if n == 1:
                idx = indices[0]
                old = fixture_data[idx]['name']
                new_name, ok = QInputDialog.getText(dialog, "Renommer", "Nouveau nom :", text=old)
                if not ok or not new_name.strip():
                    return
                _push_history()
                fixture_data[idx]['name'] = new_name.strip()
                self.projectors[idx].name = new_name.strip()
            else:
                base, ok = QInputDialog.getText(
                    dialog, "Renommer en série",
                    f"Nom de base pour les {n} fixtures sélectionnées :\n"
                    "(Ex: « PAR Face » donnera « PAR Face 1 », « PAR Face 2 »...)"
                )
                if not ok or not base.strip():
                    return
                _push_history()
                base = base.strip()
                for seq, idx in enumerate(indices, 1):
                    if idx < len(fixture_data):
                        new_name = f"{base} {seq}"
                        fixture_data[idx]['name'] = new_name
                        self.projectors[idx].name = new_name
            _checked.clear()
            btn_del_multi.setVisible(False)
            btn_rename_multi.setVisible(False)
            btn_group_multi.setVisible(False)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _build_cards(filter_bar.text())
            if _sel[0] is not None:
                _select_card(_sel[0])
            _mark_dirty()

        # ── Assigner un groupe à la sélection ─────────────────────────────────
        def _assign_group_checked():
            if not _checked:
                return
            _MNS = (
                "QMenu { background:#141414; border:1px solid #2a2a2a; border-radius:6px; padding:4px; }"
                "QMenu::item { padding:8px 28px 8px 12px; border-radius:4px; color:#bbb;"
                " font-size:13px; font-weight:bold; }"
                "QMenu::item:selected { background:#1e1e1e; color:#fff; }"
            )
            m = QMenu(btn_group_multi)
            m.setStyleSheet(_MNS)
            for g, letter, gname, color in GROUP_BLOCKS:
                act = m.addAction(letter)
                act.setData(g)
                px = QPixmap(12, 12)
                px.fill(QColor(color))
                act.setIcon(QIcon(px))
            chosen = m.exec(btn_group_multi.mapToGlobal(QPoint(0, btn_group_multi.height() + 2)))
            if not chosen or not chosen.data():
                return
            new_group = chosen.data()
            _push_history()
            for idx in sorted(_checked):
                if idx < len(fixture_data):
                    fixture_data[idx]['group'] = new_group
                    self.projectors[idx].group = new_group
            _checked.clear()
            btn_del_multi.setVisible(False)
            btn_rename_multi.setVisible(False)
            btn_group_multi.setVisible(False)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _build_cards(filter_bar.text())
            if _sel[0] is not None:
                _select_card(_sel[0])
            _mark_dirty()

        # ── Importer le patch ─────────────────────────────────────────────────
        def _import_patch():
            path, _ = QFileDialog.getOpenFileName(
                dialog, "Importer le patch", "",
                "Patch MyStrow (*.msp);;JSON (*.json);;Tous les fichiers (*)"
            )
            if not path:
                return
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                if 'fixtures' not in config:
                    QMessageBox.warning(dialog, "Format invalide",
                        "Ce fichier ne contient pas de données de patch valides.")
                    return
                n_fx = len(config['fixtures'])
                if QMessageBox.question(
                    dialog, "Importer le patch",
                    f"Charger ce patch ({n_fx} fixture{'s' if n_fx > 1 else ''}) ?\n"
                    "Le patch actuel sera remplacé.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                ) != QMessageBox.Yes:
                    return
                _push_history()
                self.projectors.clear()
                for i, fd in enumerate(config['fixtures']):
                    p = Projector(fd['group'], name=fd.get('name', ''),
                                  fixture_type=fd.get('fixture_type', 'PAR LED'))
                    p.start_address = fd.get('start_address', (i * 10) + 1)
                    p.canvas_x = fd.get('pos_x', None)
                    p.canvas_y = fd.get('pos_y', None)
                    _imp_profile = fd.get('profile')
                    if isinstance(_imp_profile, list) and _imp_profile:
                        p.dmx_profile = list(_imp_profile)
                    if fd.get('fixture_type') == "Machine a fumee":
                        p.fan_speed = 0
                    self.projectors.append(p)
                if 'custom_profiles' in config:
                    self._saved_custom_profiles = config['custom_profiles']
                self._rebuild_dmx_patch()
                _rebuild_fd()
                _sel[0] = None
                _build_cards()
                det_stack.setCurrentIndex(0)
                _mark_dirty()
                QMessageBox.information(dialog, "Import réussi",
                    f"{n_fx} fixture{'s' if n_fx > 1 else ''} importée{'s' if n_fx > 1 else ''}.")
            except Exception as e:
                QMessageBox.critical(dialog, "Erreur d'import",
                    f"Impossible de lire le fichier :\n{e}")

        # ── Exporter le patch ─────────────────────────────────────────────────
        def _export_patch():
            path, _ = QFileDialog.getSaveFileName(
                dialog, "Exporter le patch", "patch_dmx.msp",
                "Patch MyStrow (*.msp);;JSON (*.json)"
            )
            if not path:
                return
            try:
                fixtures_list = []
                for i, proj in enumerate(self.projectors):
                    proj_key = f"{proj.group}_{i}"
                    fixtures_list.append({
                        'name': proj.name,
                        'fixture_type': proj.fixture_type,
                        'group': proj.group,
                        'start_address': proj.start_address,
                        'profile': self.dmx._get_profile(proj_key),
                        'pos_x': getattr(proj, 'canvas_x', None),
                        'pos_y': getattr(proj, 'canvas_y', None),
                    })
                config = {
                    'fixtures': fixtures_list,
                    'custom_profiles': getattr(self, '_saved_custom_profiles', {}),
                }
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                QMessageBox.information(dialog, "Export réussi",
                    f"Patch exporté :\n{path}")
            except Exception as e:
                QMessageBox.critical(dialog, "Erreur d'export",
                    f"Impossible d'exporter le patch :\n{e}")

        def _open_fixture_editor():
            from fixture_editor import FixtureEditorDialog
            editor = FixtureEditorDialog(dialog)

            editor.fixture_added.connect(lambda _: None)
            editor.showMaximized()
            editor.exec()

        act_new.triggered.connect(_open_wizard)
        act_save.triggered.connect(_do_save)
        act_dflt.triggered.connect(_reset_defaults)
        act_undo.triggered.connect(_undo)
        act_redo.triggered.connect(_redo)
        act_auto.triggered.connect(_auto_address)
        btn_fixture_editor.clicked.connect(_open_fixture_editor)
        act_import.triggered.connect(_import_patch)
        act_export.triggered.connect(_export_patch)
        btn_rename_multi.clicked.connect(_rename_checked)
        btn_group_multi.clicked.connect(_assign_group_checked)

        def _deselect_all():
            for card in _cards:
                if card is not None and hasattr(card, '_chk'):
                    card._chk.setChecked(False)
        btn_desel_multi.clicked.connect(_deselect_all)
        btn_add.clicked.connect(_add_fixture)
        btn_save.clicked.connect(_do_save)
        filter_bar.textChanged.connect(lambda txt: _build_cards(txt))

        def _set_sort(mode, btn):
            _sort_mode[0] = mode
            for b in [btn_sort_dmx, btn_sort_name, btn_sort_grp]:
                b.setChecked(b is btn)
            _build_cards(filter_bar.text())
        btn_sort_dmx.clicked.connect(lambda: _set_sort("dmx", btn_sort_dmx))
        btn_sort_name.clicked.connect(lambda: _set_sort("name", btn_sort_name))
        btn_sort_grp.clicked.connect(lambda: _set_sort("group", btn_sort_grp))
        def _get_selected_projs():
            if not proxy.selected_lamps:
                return list(self.projectors)
            g_cnt = {}; result = []
            for proj in self.projectors:
                li = g_cnt.get(proj.group, 0)
                if (proj.group, li) in proxy.selected_lamps:
                    result.append(proj)
                g_cnt[proj.group] = li + 1
            return result if result else list(self.projectors)

        def _align_row():
            """Aligner toutes les fixtures sélectionnées sur la même ligne horizontale (Y moyen)"""
            projs = _get_selected_projs()
            if not projs: return
            avg_y = sum(getattr(p, 'canvas_y', 0.5) or 0.5 for p in projs) / len(projs)
            for p in projs: p.canvas_y = avg_y
            canvas.update(); _mark_dirty()

        def _distribute():
            """Centrer le groupe sur le canvas et répartir à espacement égal"""
            projs = _get_selected_projs(); n = len(projs)
            if not n: return
            if n == 1:
                projs[0].canvas_x = 0.5
            else:
                sorted_p = sorted(projs, key=lambda p: getattr(p, 'canvas_x', 0.5) or 0.5)
                mg = 0.15  # 15% de marge de chaque cote -> etalement centré sur 0.5
                for i, p in enumerate(sorted_p):
                    p.canvas_x = max(0.07, min(0.93, mg + i * (1.0 - 2 * mg) / (n - 1)))
            canvas.update(); _mark_dirty()

        btn_align_row.clicked.connect(_align_row)
        btn_distribute.clicked.connect(_distribute)
        def _select_all_canvas():
            g_cnt = {}
            for p in self.projectors:
                li = g_cnt.get(p.group, 0)
                proxy.selected_lamps.add((p.group, li)); g_cnt[p.group] = li + 1
            canvas.update()

        def _deselect_canvas():
            proxy.selected_lamps.clear(); canvas.update()

        def _show_groups_popup():
            _MS = ("QMenu{background:#1e1e1e;border:1px solid #3a3a3a;border-radius:6px;"
                   "padding:6px;color:white;font-size:11px;}"
                   "QMenu::item{padding:6px 20px;border-radius:3px;}"
                   "QMenu::item:selected{background:#333;}")
            m = QMenu(btn_groups_c); m.setStyleSheet(_MS)
            seen = []
            for p in self.projectors:
                if p.group not in seen: seen.append(p.group)
            if not seen: return
            for g in seen:
                act = m.addAction(self.GROUP_DISPLAY.get(g, g))
                act.triggered.connect(lambda checked, grp=g: _sel_group_canvas(grp))
            m.exec(btn_groups_c.mapToGlobal(QPoint(0, btn_groups_c.height())))

        def _sel_group_canvas(grp):
            proxy.selected_lamps.clear()
            g_cnt = {}
            for p in self.projectors:
                li = g_cnt.get(p.group, 0)
                if p.group == grp: proxy.selected_lamps.add((p.group, li))
                g_cnt[p.group] = li + 1
            canvas.update()
        def _delete_canvas_selection():
            n = len(proxy.selected_lamps)
            if not n: return
            if QMessageBox.question(
                dialog, "Supprimer",
                f"Supprimer {n} fixture{'s' if n > 1 else ''} sélectionnée{'s' if n > 1 else ''} ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes: return
            _push_history()
            g_cnt = {}; to_rm = set()
            for i, proj in enumerate(self.projectors):
                li = g_cnt.get(proj.group, 0)
                if (proj.group, li) in proxy.selected_lamps: to_rm.add(i)
                g_cnt[proj.group] = li + 1
            for i in sorted(to_rm, reverse=True): self.projectors.pop(i)
            proxy.selected_lamps.clear()
            self._rebuild_dmx_patch(); _rebuild_fd()
            _build_cards(filter_bar.text()); canvas.update()

        def _reset_canvas_positions():
            if QMessageBox.question(
                dialog, "Réinitialiser les positions",
                "Remettre toutes les fixtures à leur position automatique ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes: return
            _push_history()
            for proj in self.projectors: proj.canvas_x = None; proj.canvas_y = None
            _mark_dirty(); canvas.update()
        btn_sel_all_c.clicked.connect(_select_all_canvas)
        btn_desel_c.clicked.connect(_deselect_canvas)
        btn_groups_c.clicked.connect(_show_groups_popup)
        btn_reset_pos_c.clicked.connect(_reset_canvas_positions)

        proxy._add_cb             = _add_fixture
        proxy._wizard_cb          = _open_wizard
        proxy._align_row_cb       = _align_row
        proxy._distribute_cb      = _distribute
        proxy._select_fixture_cb  = lambda idx: (tabs.setCurrentIndex(0), _select_card(idx))
        proxy._refresh_cb         = lambda: (_rebuild_fd(), _build_cards(filter_bar.text()), _mark_dirty())

        canvas_timer = QTimer(dialog)

        def _timer_tick():
            canvas.update()
            _update_dots()

        canvas_timer.timeout.connect(_timer_tick)
        canvas_timer.start(80)

        # Ctrl+Z sur le dialog
        def _dialog_key(event):
            if event.key() == Qt.Key_Z and (event.modifiers() & Qt.ControlModifier):
                _undo()
            elif event.key() == Qt.Key_Y and (event.modifiers() & Qt.ControlModifier):
                _redo()
            else:
                type(dialog).keyPressEvent(dialog, event)
        dialog.keyPressEvent = _dialog_key

        def _on_close_event(event):
            if _dirty[0]:
                mb = QMessageBox(dialog)
                mb.setWindowTitle("Modifications non sauvegardées")
                mb.setText("Vous avez des modifications non sauvegardées.\nVoulez-vous les sauvegarder avant de quitter ?")
                mb.setIcon(QMessageBox.Warning)
                btn_sauv    = mb.addButton("Sauvegarder",  QMessageBox.AcceptRole)
                btn_ignorer = mb.addButton("Ignorer",       QMessageBox.DestructiveRole)
                btn_annuler = mb.addButton("Annuler",       QMessageBox.RejectRole)
                mb.setDefaultButton(btn_sauv)
                mb.exec()
                clicked = mb.clickedButton()
                if clicked == btn_sauv:
                    _do_save()
                    event.accept()
                elif clicked == btn_ignorer:
                    # Restaurer l'état d'ouverture du dialog (annule renommages, groupes, etc.)
                    _restore_snap(_initial_snap)
                    self._rebuild_dmx_patch()
                    event.accept()
                else:
                    event.ignore()
            else:
                event.accept()
        dialog.closeEvent = _on_close_event

        close_btn.clicked.disconnect()
        close_btn.clicked.connect(dialog.close)

        _build_cards()
        if select_idx is not None and 0 <= select_idx < len(fixture_data):
            _select_card(select_idx)
        elif fixture_data:
            _select_card(0)

        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, dialog.showMaximized)
        dialog.exec()
        canvas_timer.stop()

    def _show_fixture_library_dialog(self):
        """Dialog bibliotheque de fixtures. Retourne (preset, qty, custom_name) ou None."""
        from PySide6.QtWidgets import QListWidget, QSplitter, QListWidgetItem
        from builtin_fixtures import BUILTIN_FIXTURES
        import json as _json

        # ── Chargement des fixtures ────────────────────────────────────────────
        _user_fixtures = []
        try:
            _fx_file = Path.home() / ".mystrow_fixtures.json"
            if _fx_file.exists():
                _data = _json.loads(_fx_file.read_text(encoding="utf-8"))
                if isinstance(_data, list):
                    for _f in _data:
                        if not isinstance(_f, dict) or _f.get("builtin"):
                            continue
                        # Normaliser les fixtures admin panel (modes sans profile racine)
                        if not _f.get("profile") and _f.get("modes"):
                            _f["profile"] = _f["modes"][0].get("profile", [])
                        _user_fixtures.append(_f)
        except Exception:
            pass

        # Fixtures du bundle custom (admin panel → embarquées dans l'exe)
        _custom_fixtures = []
        try:
            from fixture_editor import _load_custom_bundle as _lcb
            _seen_names = {
                (f["name"], f.get("manufacturer", ""))
                for f in list(BUILTIN_FIXTURES) + _user_fixtures
            }
            for _cf in _lcb():
                if not isinstance(_cf, dict) or not _cf.get("name"):
                    continue
                key = (_cf["name"], _cf.get("manufacturer", ""))
                if key in _seen_names:
                    continue
                if not _cf.get("profile") and _cf.get("modes"):
                    _cf = dict(_cf)
                    _cf["profile"] = _cf["modes"][0].get("profile", [])
                _custom_fixtures.append(_cf)
                _seen_names.add(key)
        except Exception:
            pass

        ALL_FIXTURES = list(BUILTIN_FIXTURES) + _user_fixtures + _custom_fixtures

        # Intégration QLC+ (1710 fixtures, une entrée par mode)
        try:
            from plan_de_feu import _load_qlc_fixtures as _load_qlc
            _qlc_seen = {(f.get("name", ""), f.get("manufacturer", "")) for f in ALL_FIXTURES}
            for _qfx in _load_qlc():
                _mfr   = _qfx.get("manufacturer", "")
                _model = _qfx.get("model", "")
                _ftype = _qfx.get("fixture_type", "PAR LED")
                _modes = _qfx.get("modes", [])
                for _m in _modes:
                    _entry_name = _model if len(_modes) == 1 else f"{_model} — {_m['name']}"
                    _key = (_entry_name, _mfr)
                    if _key in _qlc_seen:
                        continue
                    _qlc_seen.add(_key)
                    ALL_FIXTURES.append({
                        "name":         _entry_name,
                        "manufacturer": _mfr,
                        "fixture_type": _ftype,
                        "group":        "face",
                        "profile":      list(_m["channels"]),
                        "source":       "qlcplus",
                    })
        except Exception:
            pass

        FIXTURE_LIBRARY = {}
        for _fx in ALL_FIXTURES:
            _cat = _fx.get("manufacturer", "Générique")
            FIXTURE_LIBRARY.setdefault(_cat, []).append(_fx)
        _sorted = {}
        if "Générique" in FIXTURE_LIBRARY:
            _sorted["Générique"] = FIXTURE_LIBRARY.pop("Générique")
        for _k in sorted(FIXTURE_LIBRARY):
            _sorted[_k] = FIXTURE_LIBRARY[_k]
        FIXTURE_LIBRARY = _sorted
        _TOTAL_FIXTURES = len(ALL_FIXTURES)

        # ── Dialog ────────────────────────────────────────────────────────────
        _SS = """
            QDialog { background: #141414; color: #e0e0e0; }
            QListWidget {
                background: #1e1e1e; color: #e0e0e0;
                border: 1px solid #333; border-radius: 6px;
                font-size: 12px;
            }
            QListWidget::item { padding: 5px 10px; }
            QListWidget::item:selected { background: #00d4ff; color: #000; font-weight: bold; }
            QListWidget::item:hover:!selected { background: #2a2a2a; }
            QLineEdit {
                background: #1e1e1e; color: #fff;
                border: 1px solid #444; border-radius: 6px;
                padding: 6px 12px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #00d4ff88; }
            QPushButton {
                background: #2a2a2a; color: #ccc;
                border: 1px solid #4a4a4a; border-radius: 6px;
                padding: 6px 16px; font-size: 12px;
            }
            QPushButton:hover { border-color: #00d4ff; color: #fff; }
            QLabel { color: #aaa; font-size: 12px; }
            QSplitter::handle { background: #2a2a2a; width: 4px; }
        """

        dialog = QDialog(self)
        dialog.setWindowTitle("Bibliothèque de fixtures")
        dialog.resize(780, 540)
        dialog.setMinimumSize(600, 420)
        dialog.setStyleSheet(_SS)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # ── Onglets ───────────────────────────────────────────────────────────
        from PySide6.QtWidgets import QTabWidget as _QTabWidget
        tab_widget = _QTabWidget()
        tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #333; background: #1e1e1e; }"
            "QTabBar::tab { background: #2a2a2a; color: #aaa; padding: 6px 16px; margin-right: 2px; }"
            "QTabBar::tab:selected { background: #1e1e1e; color: #fff;"
            " border-bottom: 2px solid #00d4ff; }"
        )

        # ── Tab 1 : Bibliothèque de fixtures ──────────────────────────────────
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setContentsMargins(8, 8, 8, 8)
        tab1_layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_edit = QLineEdit()
        search_edit.setFixedHeight(36)
        search_edit.setPlaceholderText("🔍  Rechercher une fixture ou un fabricant...")
        btn_import = QPushButton("📥  Importer")
        btn_import.setFixedHeight(36)
        btn_import.setToolTip("Importer des fixtures depuis un fichier (.mft, .json, .xml)")
        btn_import.setStyleSheet(
            "QPushButton { background:#1a3a2a; color:#44cc88; border:1px solid #44cc8844;"
            " border-radius:6px; padding:6px 16px; font-size:12px; font-weight:bold; }"
            "QPushButton:hover { border-color:#44cc88; color:#66ee99; }"
        )
        btn_refresh = QPushButton("🔄  Actualiser")
        btn_refresh.setFixedHeight(36)
        btn_refresh.setStyleSheet(
            "QPushButton { background:#1a2a3a; color:#44aaee; border:1px solid #44aaee44;"
            " border-radius:6px; padding:6px 16px; font-size:12px; font-weight:bold; }"
            "QPushButton:hover { border-color:#44aaee; color:#66ccff; }"
        )
        search_row.addWidget(search_edit, 1)
        search_row.addWidget(btn_import)
        search_row.addWidget(btn_refresh)
        tab1_layout.addLayout(search_row)

        xml_hint = QLabel("💡  Vous pouvez importer n'importe quelle fixture au format <b>XML</b> (GrandMA, QLC+…) via le bouton Importer.")
        xml_hint.setWordWrap(True)
        xml_hint.setStyleSheet(
            "color:#888; font-size:11px; background:#161f16; border:1px solid #2a3a2a;"
            " border-radius:5px; padding:5px 10px;"
        )
        tab1_layout.addWidget(xml_hint)

        # ── Splitter fabricant / fixture ──────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        cat_list = QListWidget()
        cat_list.setMaximumWidth(200)
        cat_list.setMinimumWidth(140)
        for cat in FIXTURE_LIBRARY.keys():
            cat_list.addItem(cat)
        splitter.addWidget(cat_list)

        preset_list = QListWidget()
        splitter.addWidget(preset_list)
        splitter.setStretchFactor(1, 1)

        tab1_layout.addWidget(splitter, 1)

        # ── Compteur résultats ────────────────────────────────────────────────
        count_lbl = QLabel("")
        count_lbl.setAlignment(Qt.AlignRight)
        tab1_layout.addWidget(count_lbl)

        tab_widget.addTab(tab1, "Bibliothèque de fixtures")

        # ── Tab 2 : Mes projecteurs ────────────────────────────────────────────
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setContentsMargins(8, 8, 8, 8)
        tab2_layout.setSpacing(8)

        _my_fixtures = [
            f for f in _user_fixtures
            if f.get("source", "user") not in ("firestore", "ofl")
        ]
        my_list = QListWidget()
        if _my_fixtures:
            for _fx in _my_fixtures:
                _n = _fx.get("name", "?")
                _nch = len(_fx.get("profile", []))
                _ftype = _fx.get("fixture_type", "")
                _lbl = f"{_n}  ({_nch}ch)"
                if _ftype:
                    _lbl += f"   — {_ftype}"
                _item = QListWidgetItem(_lbl)
                _item.setData(Qt.UserRole, _fx)
                my_list.addItem(_item)
        else:
            _empty_item = QListWidgetItem(
                "Aucun projecteur enregistré — créez-en un dans l'éditeur de fixtures."
            )
            _empty_item.setFlags(_empty_item.flags() & ~Qt.ItemIsEnabled)
            my_list.addItem(_empty_item)
        tab2_layout.addWidget(my_list, 1)

        tab_widget.addTab(tab2, "Mes projecteurs")

        layout.addWidget(tab_widget, 1)

        result = [None]

        # ── Helpers ───────────────────────────────────────────────────────────
        def _fill_preset_list(fixtures):
            preset_list.clear()
            for preset in fixtures:
                name  = preset.get("name", "?")
                mfr   = preset.get("manufacturer", "")
                n_ch  = len(preset.get("profile", []))
                ftype = preset.get("fixture_type", "")
                parts = [f"{name}  ({n_ch}ch)"]
                if mfr and mfr != cat_list.currentItem().text() if cat_list.currentItem() else True:
                    parts.append(f"— {mfr}")
                label = "  ".join(parts)
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, preset)
                preset_list.addItem(item)
            n = preset_list.count()
            count_lbl.setText(f"{n} fixture{'s' if n > 1 else ''}  —  {_TOTAL_FIXTURES} au total")

        def on_cat_changed():
            if search_edit.text().strip():
                return
            cat = cat_list.currentItem()
            if not cat:
                return
            _fill_preset_list(FIXTURE_LIBRARY.get(cat.text(), []))

        def on_search(text):
            q = text.strip().lower()
            if not q:
                # Retour au mode fabricant normal
                cat_list.setEnabled(True)
                cat_list.show()
                on_cat_changed()
                return
            cat_list.setEnabled(False)
            matches = [
                fx for fx in ALL_FIXTURES
                if q in fx.get("name", "").lower()
                or q in fx.get("manufacturer", "").lower()
                or q in fx.get("fixture_type", "").lower()
            ]
            preset_list.clear()
            for preset in matches:
                name  = preset.get("name", "?")
                mfr   = preset.get("manufacturer", "")
                n_ch  = len(preset.get("profile", []))
                label = f"{name}  ({n_ch}ch)"
                if mfr:
                    label += f"   — {mfr}"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, preset)
                preset_list.addItem(item)
            n = preset_list.count()
            count_lbl.setText(f"{n} résultat{'s' if n > 1 else ''}  —  {_TOTAL_FIXTURES} au total")
            if n > 0:
                preset_list.setCurrentRow(0)

        def _do_import():
            from fixture_parser import parse_file as _parse_file
            from PySide6.QtWidgets import QInputDialog
            paths, _ = QFileDialog.getOpenFileNames(
                dialog, "Importer des fixtures", str(Path.home()),
                "Tous les formats supportés (*.mft *.json *.xml *.xmlp *.mystrow);;"
                "Fixture MyStrow (*.mft *.json *.mystrow);;"
                "XML / XML compressé (*.xml *.xmlp)"
            )
            if not paths:
                return
            _GROUP = {"Moving Head": "lyre", "Barre LED": "barre",
                      "Stroboscope": "strobe", "Machine a fumee": "fumee"}
            _fx_file = Path.home() / ".mystrow_fixtures.json"
            try:
                existing_user = _json.loads(_fx_file.read_text(encoding="utf-8")) if _fx_file.exists() else []
                if not isinstance(existing_user, list):
                    existing_user = []
            except Exception:
                existing_user = []
            existing_names = {f["name"] for f in existing_user if isinstance(f, dict)}
            imported = 0
            errors = []
            for path in paths:
                ext = Path(path).suffix.lower()
                try:
                    raw = Path(path).read_bytes()
                    if ext in (".xml", ".xmlp"):
                        ofl_fx = _parse_file(path)
                        modes = [m for m in (ofl_fx.get("modes") or [])
                                 if isinstance(m, dict) and m.get("profile")]
                        if not modes:
                            raise ValueError("Aucun canal DMX trouvé dans ce fichier XML.")
                        ftype = ofl_fx.get("fixture_type", "PAR LED")
                        candidates = [{
                            "name":         ofl_fx.get("name", Path(path).stem)
                                            + (f" — {m['name']}" if len(modes) > 1 else ""),
                            "manufacturer": ofl_fx.get("manufacturer", ""),
                            "fixture_type": ftype,
                            "group":        _GROUP.get(ftype, "face"),
                            "profile":      m["profile"],
                            "source":       ofl_fx.get("source", "ma"),
                        } for m in modes]
                        if len(candidates) > 1:
                            mode_names = [c["name"] for c in candidates]
                            choice, ok = QInputDialog.getItem(
                                dialog, "Choisir un mode",
                                f"{ofl_fx.get('name')} — {len(candidates)} modes.\nMode à importer :",
                                mode_names, 0, False
                            )
                            if not ok:
                                continue
                            to_add = [candidates[mode_names.index(choice)]]
                        else:
                            to_add = candidates
                    else:
                        parsed = _json.loads(raw.decode("utf-8"))
                        to_add = [parsed] if isinstance(parsed, dict) else parsed
                        if not isinstance(to_add, list):
                            raise ValueError("Format invalide (liste de fixtures attendue).")
                        to_add = [f for f in to_add if isinstance(f, dict)]
                    for fx in to_add:
                        if not fx.get("name") or not fx.get("profile"):
                            continue
                        fx.pop("builtin", None)
                        name = fx["name"]
                        if name in existing_names:
                            c = 2
                            while f"{name} ({c})" in existing_names:
                                c += 1
                            fx["name"] = f"{name} ({c})"
                        existing_user.append(fx)
                        existing_names.add(fx["name"])
                        imported += 1
                except Exception as e:
                    if "LOCKED_XMLP" in str(e):
                        errors.append(f"• {Path(path).name} : 🔒 Fichier protégé — format propriétaire chiffré (GrandMA3). Utilisez le fichier .xml non chiffré.")
                    else:
                        errors.append(f"• {Path(path).name} : {e}")
            if imported == 0:
                msg = "Aucune fixture importée."
                if errors:
                    msg += "\n\n" + "\n".join(errors)
                QMessageBox.warning(dialog, "Import échoué", msg)
                return
            _fx_file.write_text(_json.dumps(existing_user, ensure_ascii=False, indent=2), encoding="utf-8")
            # Rafraîchir la bibliothèque en place
            new_user = [f for f in existing_user if not f.get("builtin")]
            ALL_FIXTURES.clear()
            ALL_FIXTURES.extend(list(BUILTIN_FIXTURES) + new_user)
            FIXTURE_LIBRARY.clear()
            for _fx in ALL_FIXTURES:
                FIXTURE_LIBRARY.setdefault(_fx.get("manufacturer", "Générique"), []).append(_fx)
            _sorted2 = {}
            if "Générique" in FIXTURE_LIBRARY:
                _sorted2["Générique"] = FIXTURE_LIBRARY.pop("Générique")
            for _k in sorted(FIXTURE_LIBRARY):
                _sorted2[_k] = FIXTURE_LIBRARY[_k]
            FIXTURE_LIBRARY.clear()
            FIXTURE_LIBRARY.update(_sorted2)
            cat_list.clear()
            for cat in FIXTURE_LIBRARY.keys():
                cat_list.addItem(cat)
            if cat_list.count():
                cat_list.setCurrentRow(0)
            msg = f"{imported} fixture{'s' if imported > 1 else ''} importée{'s' if imported > 1 else ''}."
            if errors:
                msg += f"\n\n{len(errors)} fichier(s) ignoré(s) :\n" + "\n".join(errors)
                QMessageBox.warning(dialog, "Import partiel", msg)
            else:
                QMessageBox.information(dialog, "Import réussi", msg)

        def _rebuild_library_ui(new_user_fixtures: list):
            """Reconstruit ALL_FIXTURES / FIXTURE_LIBRARY et rafraîchit cat_list."""
            new_custom = []
            try:
                from fixture_editor import _load_custom_bundle as _lcb2
                _seen2 = {
                    (f["name"], f.get("manufacturer", ""))
                    for f in list(BUILTIN_FIXTURES) + new_user_fixtures
                }
                for _cf2 in _lcb2():
                    if not isinstance(_cf2, dict) or not _cf2.get("name"):
                        continue
                    _k2 = (_cf2["name"], _cf2.get("manufacturer", ""))
                    if _k2 in _seen2:
                        continue
                    if not _cf2.get("profile") and _cf2.get("modes"):
                        _cf2 = dict(_cf2)
                        _cf2["profile"] = _cf2["modes"][0].get("profile", [])
                    new_custom.append(_cf2)
                    _seen2.add(_k2)
            except Exception:
                pass
            ALL_FIXTURES.clear()
            ALL_FIXTURES.extend(list(BUILTIN_FIXTURES) + new_user_fixtures + new_custom)
            FIXTURE_LIBRARY.clear()
            for _fx in ALL_FIXTURES:
                FIXTURE_LIBRARY.setdefault(_fx.get("manufacturer", "Générique"), []).append(_fx)
            _sorted3 = {}
            if "Générique" in FIXTURE_LIBRARY:
                _sorted3["Générique"] = FIXTURE_LIBRARY.pop("Générique")
            for _k3 in sorted(FIXTURE_LIBRARY):
                _sorted3[_k3] = FIXTURE_LIBRARY[_k3]
            FIXTURE_LIBRARY.clear()
            FIXTURE_LIBRARY.update(_sorted3)
            prev_cat = cat_list.currentItem().text() if cat_list.currentItem() else None
            cat_list.clear()
            for cat in FIXTURE_LIBRARY.keys():
                cat_list.addItem(cat)
            if prev_cat:
                for i in range(cat_list.count()):
                    if cat_list.item(i).text() == prev_cat:
                        cat_list.setCurrentRow(i)
                        break
            elif cat_list.count():
                cat_list.setCurrentRow(0)

        def _do_refresh():
            from PySide6.QtCore import QObject as _QObject, Signal as _Signal, QThread as _QThread

            from license_manager import _get_fresh_token

            id_token = _get_fresh_token()
            if not id_token:
                QMessageBox.warning(
                    dialog, "Non connecté",
                    "Impossible de récupérer les fixtures Firestore.\n"
                    "Veuillez vous connecter à votre compte MyStrow."
                )
                return

            btn_refresh.setEnabled(False)
            btn_refresh.setText("⏳  Chargement...")
            count_lbl.setText("Connexion à Firestore...")

            class _FetchWorker(_QObject):
                done  = _Signal(list)
                error = _Signal(str)

                def __init__(self, token):
                    super().__init__()
                    self._token = token

                def run(self):
                    try:
                        import firebase_client as _fc
                        fixtures = _fc.fetch_all_gdtf_fixtures(self._token)
                        self.done.emit(fixtures)
                    except Exception as e:
                        self.error.emit(str(e))

            thread = _QThread(dialog)
            worker = _FetchWorker(id_token)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            # Garder des refs fortes pour éviter le GC Python avant la fin du thread
            dialog._refresh_thread = thread
            dialog._refresh_worker = worker

            def _on_done(remote_fixtures: list):
                thread.quit()
                dialog._refresh_thread = None
                dialog._refresh_worker = None
                # Normaliser les modes
                for _f in remote_fixtures:
                    if not _f.get("profile") and _f.get("modes"):
                        _f["profile"] = _f["modes"][0].get("profile", [])
                    _f.setdefault("source", "firestore")
                # Fusionner : conserver les fixtures user locales, remplacer les firestore
                _fx_file2 = Path.home() / ".mystrow_fixtures.json"
                try:
                    existing = _json.loads(_fx_file2.read_text(encoding="utf-8")) if _fx_file2.exists() else []
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []
                local_only = [f for f in existing if f.get("source", "user") not in ("firestore", "ofl")]
                merged = local_only + remote_fixtures
                try:
                    _fx_file2.write_text(_json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
                _rebuild_library_ui(merged)
                n = len(remote_fixtures)
                count_lbl.setText(f"Firestore — {n} fixture{'s' if n > 1 else ''} chargée{'s' if n > 1 else ''}  —  {_TOTAL_FIXTURES} au total")
                btn_refresh.setEnabled(True)
                btn_refresh.setText("🔄  Actualiser")

            def _on_error(msg: str):
                thread.quit()
                dialog._refresh_thread = None
                dialog._refresh_worker = None
                count_lbl.setText("Erreur Firestore")
                QMessageBox.warning(dialog, "Erreur Firestore", f"Impossible de charger les fixtures :\n{msg}")
                btn_refresh.setEnabled(True)
                btn_refresh.setText("🔄  Actualiser")

            worker.done.connect(_on_done)
            worker.error.connect(_on_error)
            thread.start()

        btn_import.clicked.connect(_do_import)
        btn_refresh.clicked.connect(_do_refresh)
        cat_list.currentItemChanged.connect(on_cat_changed)
        search_edit.textChanged.connect(on_search)

        if FIXTURE_LIBRARY:
            cat_list.setCurrentRow(0)

        # ── Accept ────────────────────────────────────────────────────────────
        def accept():
            if tab_widget.currentIndex() == 1:
                item = my_list.currentItem()
            else:
                item = preset_list.currentItem()
            if not item:
                return
            preset = item.data(Qt.UserRole)
            if preset:
                result[0] = preset
                dialog.accept()

        preset_list.itemDoubleClicked.connect(lambda _: accept())
        my_list.itemDoubleClicked.connect(lambda _: accept())

        # ── Bas de dialog : nom + quantité ────────────────────────────────────
        qty_row = QHBoxLayout()
        qty_row.setSpacing(10)

        lbl_name = QLabel("Nom :")
        name_edit = QLineEdit()
        name_edit.setFixedHeight(32)
        name_edit.setPlaceholderText("Nom personnalisé (optionnel)")

        lbl_qty = QLabel("Quantité :")
        qty_spin = QComboBox()
        for _q in range(1, 21):
            qty_spin.addItem(str(_q))
        qty_spin.setFixedWidth(70)
        qty_spin.setFixedHeight(32)
        qty_spin.setStyleSheet(
            "QComboBox { background:#1e1e1e; color:#fff; border:1px solid #444;"
            " border-radius:6px; padding:4px 8px; font-size:13px; font-weight:bold; }"
            "QComboBox::drop-down { border:none; width:20px; }"
            "QComboBox QAbstractItemView { background:#1e1e1e; color:#fff;"
            " selection-background-color:#00d4ff; selection-color:#000; border:1px solid #444; }"
        )

        def _on_preset_selected():
            item = preset_list.currentItem()
            if item and not name_edit.text().strip():
                preset = item.data(Qt.UserRole)
                if preset:
                    name_edit.setPlaceholderText(preset.get("name", ""))
        preset_list.currentItemChanged.connect(lambda *_: _on_preset_selected())

        qty_row.addWidget(lbl_name)
        qty_row.addWidget(name_edit, 1)
        qty_row.addWidget(lbl_qty)
        qty_row.addWidget(qty_spin)
        layout.addLayout(qty_row)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Ajouter")
        ok_btn.setFixedHeight(36)
        ok_btn.setStyleSheet(
            "QPushButton { background:#00d4ff; color:#000; font-weight:bold;"
            " border:none; border-radius:6px; padding:8px 28px; font-size:13px; }"
            "QPushButton:hover { background:#33ddff; }"
        )
        cancel_b = QPushButton("Annuler")
        cancel_b.setFixedHeight(36)
        ok_btn.clicked.connect(accept)
        cancel_b.clicked.connect(dialog.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_b)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        search_edit.setFocus()
        dialog.exec()
        if result[0] is None:
            return None
        custom_name = name_edit.text().strip() or None
        return (result[0], int(qty_spin.currentText()), custom_name)

    def _show_custom_profile_dialog(self, initial=None):
        """Dialog pour composer un profil DMX custom. Retourne la liste ou None si annule."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Profil DMX Custom")
        dialog.setFixedSize(400, 420)
        dialog.setStyleSheet("""
            QDialog { background: #1a1a1a; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QPushButton {
                background: #2a2a2a; color: #ffffff; border: 1px solid #4a4a4a;
                border-radius: 4px; padding: 6px 12px; font-size: 12px;
            }
            QPushButton:hover { border: 1px solid #00d4ff; background: #333; }
            QListWidget {
                background: #222; color: #fff; border: 1px solid #4a4a4a;
                border-radius: 4px; font-size: 13px; font-family: 'Consolas';
            }
            QListWidget::item:selected { background: #00d4ff; color: #000; }
            QComboBox {
                background: #2a2a2a; color: #ffffff;
                border: 1px solid #4a4a4a; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }
            QComboBox QAbstractItemView {
                background: #2a2a2a; color: #ffffff;
                border: 1px solid #4a4a4a; selection-background-color: #00d4ff;
                selection-color: #000000;
            }
        """)

        from PySide6.QtWidgets import QListWidget

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Composer le profil")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Liste des canaux du profil
        list_widget = QListWidget()
        if initial:
            for ch in initial:
                list_widget.addItem(ch)
        layout.addWidget(list_widget)

        # Ajout d'un type de canal
        add_row = QHBoxLayout()
        type_combo = QComboBox()
        for ct in CHANNEL_TYPES:
            type_combo.addItem(ct)
        add_row.addWidget(type_combo)

        add_btn = QPushButton("Ajouter")
        add_btn.setStyleSheet("QPushButton { background: #00d4ff; color: #000; font-weight: bold; } QPushButton:hover { background: #33ddff; }")

        def add_channel():
            ch = type_combo.currentText()
            existing = [list_widget.item(r).text() for r in range(list_widget.count())]
            if ch in existing:
                QMessageBox.warning(dialog, "Doublon", f"Le canal '{ch}' est deja dans le profil.")
                return
            list_widget.addItem(ch)

        add_btn.clicked.connect(add_channel)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        # Boutons monter / descendre / supprimer
        action_row = QHBoxLayout()
        up_btn = QPushButton("Monter")
        down_btn = QPushButton("Descendre")
        del_btn = QPushButton("Supprimer")
        del_btn.setStyleSheet("QPushButton { background: #662222; color: #ff8888; border: 1px solid #883333; } QPushButton:hover { background: #883333; }")

        def move_item(direction):
            row = list_widget.currentRow()
            if row < 0:
                return
            new_row = row + direction
            if 0 <= new_row < list_widget.count():
                item = list_widget.takeItem(row)
                list_widget.insertItem(new_row, item)
                list_widget.setCurrentRow(new_row)

        up_btn.clicked.connect(lambda: move_item(-1))
        down_btn.clicked.connect(lambda: move_item(1))
        del_btn.clicked.connect(lambda: list_widget.takeItem(list_widget.currentRow()) if list_widget.currentRow() >= 0 else None)

        action_row.addWidget(up_btn)
        action_row.addWidget(down_btn)
        action_row.addWidget(del_btn)
        layout.addLayout(action_row)

        # Preview
        preview_label = QLabel("")
        preview_label.setAlignment(Qt.AlignCenter)
        preview_label.setStyleSheet("color: #888; font-family: 'Consolas'; font-size: 12px; padding: 6px;")
        layout.addWidget(preview_label)

        def update_preview():
            items = [list_widget.item(r).text() for r in range(list_widget.count())]
            preview_label.setText("  ".join(items) if items else "(vide)")

        list_widget.model().rowsInserted.connect(update_preview)
        list_widget.model().rowsRemoved.connect(update_preview)
        list_widget.model().rowsMoved.connect(update_preview)
        update_preview()

        # OK / Annuler
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet("QPushButton { background: #00d4ff; color: #000; font-weight: bold; padding: 8px 24px; } QPushButton:hover { background: #33ddff; }")
        cancel_btn = QPushButton("Annuler")
        cancel_btn.setStyleSheet("QPushButton { padding: 8px 24px; }")

        result = [None]

        def accept():
            items = [list_widget.item(r).text() for r in range(list_widget.count())]
            if not items:
                QMessageBox.warning(dialog, "Profil vide", "Le profil doit contenir au moins 1 canal.")
                return
            result[0] = items
            dialog.accept()

        ok_btn.clicked.connect(accept)
        cancel_btn.clicked.connect(dialog.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        dialog.exec()
        return result[0]

    def _ask_custom_profile_name(self):
        """Demande un nom court (max 8 car.) pour un profil custom. Retourne le nom ou None."""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Nom du profil",
            "Nom du profil (8 caracteres max) :",
        )
        if ok and name:
            name = name.strip()[:8]
            if name:
                return name
        return None

    def apply_dmx_modes(self, dialog, fixture_data):
        """Applique les fixtures configurees"""
        if not fixture_data:
            QMessageBox.warning(dialog, "Aucune fixture", "La liste de fixtures est vide.")
            return

        # Reconstruire self.projectors depuis fixture_data
        self.projectors = []
        for fd in fixture_data:
            p = Projector(fd['group'], name=fd['name'], fixture_type=fd['fixture_type'])
            p.start_address = fd['start_address']
            if fd['fixture_type'] == "Machine a fumee":
                p.fan_speed = 0
            self.projectors.append(p)

        # Mettre a jour le patch DMX
        self.dmx.clear_patch()
        for i, (proj, fd) in enumerate(zip(self.projectors, fixture_data)):
            proj_key = f"{proj.group}_{i}"
            profile = fd['profile']
            nb_ch = len(profile)
            channels = [proj.start_address + c for c in range(nb_ch)]
            self.dmx.set_projector_patch(proj_key, channels, profile=profile)

        self.save_dmx_patch_config()
        QMessageBox.information(dialog, "Patch applique",
            "Fixtures DMX appliquees avec succes !")
        dialog.accept()

    def _rebuild_dmx_patch(self):
        """Reconstruit le patch DMX depuis self.projectors et sauvegarde"""
        self.dmx.clear_patch()
        for i, proj in enumerate(self.projectors):
            proj_key = f"{proj.group}_{i}"
            # Respecter le profil explicite si défini sur le projecteur
            explicit = getattr(proj, 'dmx_profile', None)
            if isinstance(explicit, list) and explicit:
                profile = explicit
            else:
                ftype = getattr(proj, 'fixture_type', 'PAR LED')
                if ftype == "Machine a fumee" or proj.group == "fumee":
                    profile = list(DMX_PROFILES["2CH_FUMEE"])
                elif ftype == "Moving Head":
                    profile = list(DMX_PROFILES["MOVING_8CH"])
                elif ftype == "Barre LED":
                    profile = list(DMX_PROFILES["LED_BAR_RGB"])
                elif ftype == "Stroboscope":
                    profile = list(DMX_PROFILES["STROBE_2CH"])
                else:
                    profile = list(DMX_PROFILES["RGBDS"])
            channels = [proj.start_address + c for c in range(len(profile))]
            self.dmx.set_projector_patch(proj_key, channels,
                                         universe=getattr(proj, 'universe', 0),
                                         profile=profile)
        self.save_dmx_patch_config()

    def save_dmx_patch_config(self):
        """Sauvegarde la configuration du patch DMX (nouveau format avec fixtures)"""
        fixtures_list = []
        for i, proj in enumerate(self.projectors):
            proj_key = f"{proj.group}_{i}"
            fixtures_list.append({
                'name': proj.name,
                'fixture_type': proj.fixture_type,
                'group': proj.group,
                'universe':      getattr(proj, 'universe', 0),
                'start_address': proj.start_address,
                'profile': self.dmx._get_profile(proj_key),
                'pos_x': getattr(proj, 'canvas_x', None),
                'pos_y': getattr(proj, 'canvas_y', None),
                'pos_3d_x': getattr(proj, 'pos_3d_x', None),
                'pos_3d_z': getattr(proj, 'pos_3d_z', None),
                'fixture_height':  getattr(proj, 'fixture_height', None),
                'body_rotation':   getattr(proj, 'body_rotation', 0.0),
                'channel_defaults':   dict(getattr(proj, 'channel_defaults', {})),
                'color_wheel_slots':  list(getattr(proj, 'color_wheel_slots', [])),
                'gobo_wheel_slots':   list(getattr(proj, 'gobo_wheel_slots', [])),
            })
        config = {
            'fixtures': fixtures_list,
            'custom_profiles': getattr(self, '_saved_custom_profiles', {}),
        }
        try:
            config_path = Path.home() / '.maestro_dmx_patch.json'
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Erreur sauvegarde patch: {e}")
        if hasattr(self, '_plan3d') and self._plan3d.isVisible():
            self._plan3d.refresh(self.projectors)

    def load_dmx_patch_config(self):
        """Charge la configuration du patch DMX"""
        try:
            config_path = Path.home() / '.maestro_dmx_patch.json'
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)

                # Nouveau format avec liste de fixtures
                if 'fixtures' in config:
                    self.projectors = []
                    for i, fd in enumerate(config['fixtures']):
                        p = Projector(
                            fd['group'],
                            name=fd.get('name', ''),
                            fixture_type=fd.get('fixture_type', 'PAR LED')
                        )
                        p.universe      = fd.get('universe', 0)
                        p.start_address = fd.get('start_address', (i * 10) + 1)
                        p.canvas_x = fd.get('pos_x', None)
                        p.canvas_y = fd.get('pos_y', None)
                        p3x = fd.get('pos_3d_x')
                        p3z = fd.get('pos_3d_z')
                        if p3x is not None: p.pos_3d_x = float(p3x)
                        if p3z is not None: p.pos_3d_z = float(p3z)
                        fh = fd.get('fixture_height')
                        if fh is not None:
                            p.fixture_height = float(fh)
                        p.body_rotation = float(fd.get('body_rotation', 0.0))
                        if fd.get('fixture_type') == "Machine a fumee":
                            p.fan_speed = 0
                        profile = fd.get('profile', list(DMX_PROFILES['RGBDS']))
                        if isinstance(profile, list) and profile:
                            p.dmx_profile = list(profile)
                        p.channel_defaults  = dict(fd.get('channel_defaults', {}))
                        p.color_wheel_slots = list(fd.get('color_wheel_slots', []))
                        p.gobo_wheel_slots  = list(fd.get('gobo_wheel_slots', []))
                        self.projectors.append(p)
                        proj_key = f"{p.group}_{i}"
                        nb_ch = len(profile)
                        channels = [p.start_address + c for c in range(nb_ch)]
                        self.dmx.set_projector_patch(proj_key, channels,
                                                     universe=p.universe,
                                                     profile=profile)
                    self._saved_custom_profiles = config.get('custom_profiles', {})
                    return True

                # Retro-compat : ancien format (channels/modes/profiles)
                self.dmx.projector_channels = config.get('channels', {})
                self.dmx.projector_modes = config.get('modes', {})
                self._saved_custom_profiles = config.get('custom_profiles', {})
                if 'profiles' in config:
                    self.dmx.projector_profiles = config['profiles']
                else:
                    for key, mode in self.dmx.projector_modes.items():
                        self.dmx.projector_profiles[key] = profile_for_mode(mode)
                return True
        except Exception as e:
            print(f"Erreur chargement patch: {e}")
        return False

    def show_ia_lumiere_config(self):
        """Configuration avancée IA Lumiere : niveaux, nervosité, effet drop"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Paramètres IA Lumière")
        dialog.setFixedSize(560, 640)
        dialog.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel { color: white; border: none; }
            QSlider::groove:horizontal {
                background: #2a2a2a; height: 8px; border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00d4ff; width: 18px; height: 18px;
                margin: -5px 0; border-radius: 9px;
            }
            QSlider::sub-page:horizontal { background: #00d4ff; border-radius: 4px; }
            QComboBox {
                background: #2a2a2a; color: white; border: 1px solid #444;
                border-radius: 6px; padding: 6px 12px; font-size: 12px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background: #2a2a2a; color: white;
                selection-background-color: #005599; }
            QFrame[frameShape="4"], QFrame[frameShape="5"] { color: #333; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(0)

        def _section_title(text, color="#00d4ff"):
            lbl = QLabel(text)
            lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color:{color};"
                              f"padding: 10px 0 4px 0;")
            return lbl

        def _sep():
            f = QFrame(); f.setFrameShape(QFrame.HLine)
            f.setStyleSheet("color:#333; margin: 4px 0;")
            return f

        def _slider_row(label_text, key, store, lo=0, hi=100, suffix="%"):
            row = QHBoxLayout(); row.setSpacing(10)
            lbl = QLabel(label_text); lbl.setMinimumWidth(160)
            lbl.setStyleSheet("font-size:12px;")
            row.addWidget(lbl)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi); sl.setValue(store.get(key, (lo+hi)//2))
            row.addWidget(sl)
            val_lbl = QLabel(f"{sl.value()}{suffix}")
            val_lbl.setMinimumWidth(42)
            val_lbl.setStyleSheet("font-size:12px; font-weight:bold; color:#00d4ff;")
            sl.valueChanged.connect(lambda v, l=val_lbl: l.setText(f"{v}{suffix}"))
            row.addWidget(val_lbl)
            return row, sl

        # ── Titre ────────────────────────────────────────────────────────────
        title = QLabel("IA Lumière — Paramètres avancés")
        title.setStyleSheet("font-size:15px; font-weight:bold; padding-bottom:8px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(_sep())

        # ── Nervosité ─────────────────────────────────────────────────────────
        layout.addWidget(_section_title("⚡  Nervosité"))
        nerv_row, nerv_sl = _slider_row(
            "Nervosité générale", 'nervosity', self.ia_params, 0, 100, "%"
        )
        nerv_info = QLabel("Contrôle la réactivité : vitesse des strobes, lyres, fréquence des effets.")
        nerv_info.setStyleSheet("color:#666; font-size:11px; padding-left:4px;")
        nerv_info.setWordWrap(True)
        layout.addLayout(nerv_row)
        layout.addWidget(nerv_info)
        layout.addSpacing(6)
        layout.addWidget(_sep())

        # ── Effet DROP ────────────────────────────────────────────────────────
        layout.addWidget(_section_title("💥  Effet DROP"))

        DROP_EFFECTS = {
            'flash_blanc':       "Flash Blanc      — punch blanc immédiat + strobe lat/contre",
            'color_explosion':   "Color Explosion  — chaque groupe explose dans une couleur, strobe total",
            'blackout_punch':    "Blackout Punch   — 150ms noir total → BANG blanc + strobe",
            'stroboscope':       "Stroboscope      — strobe blanc intégral sur tous les projecteurs",
            'laser_scan':        "Laser Scan       — lyres en turbo, projecteurs flash + strobe lat",
        }
        drop_combo = QComboBox()
        drop_combo.setFixedHeight(34)
        for key, label in DROP_EFFECTS.items():
            drop_combo.addItem(label, key)
        current_drop = self.ia_params.get('drop_effect', 'flash_blanc')
        for i in range(drop_combo.count()):
            if drop_combo.itemData(i) == current_drop:
                drop_combo.setCurrentIndex(i)
                break
        layout.addWidget(drop_combo)
        layout.addSpacing(6)
        layout.addWidget(_sep())

        # ── Niveaux max par groupe ────────────────────────────────────────────
        layout.addWidget(_section_title("🎚  Niveaux maximum par groupe"))
        dim_info = QLabel("Plafonnent le dimmer de chaque groupe en mode IA Lumière.")
        dim_info.setStyleSheet("color:#666; font-size:11px; padding-left:4px;")
        layout.addWidget(dim_info)
        layout.addSpacing(4)

        sliders = {}
        groups = [
            ("Face",              "face"),
            ("Latéraux & Contres","lat"),
            ("Douche 1",          "douche1"),
            ("Douche 2",          "douche2"),
            ("Douche 3",          "douche3"),
        ]
        for label_text, key in groups:
            row, sl = _slider_row(label_text, key, self.ia_max_dimmers)
            sliders[key] = sl
            layout.addLayout(row)

        layout.addStretch(1)
        layout.addWidget(_sep())

        # ── Boutons ───────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        apply_btn = QPushButton("✅ Appliquer")
        apply_btn.setStyleSheet("""
            QPushButton { background: #2a5a2a; color: white; border: none;
                border-radius: 6px; padding: 10px 25px; font-weight: bold; font-size: 13px; }
            QPushButton:hover { background: #3a7a3a; }
        """)
        apply_btn.clicked.connect(
            lambda: self._apply_ia_config(dialog, sliders, nerv_sl, drop_combo)
        )
        btn_layout.addWidget(apply_btn)

        cancel_btn = QPushButton("❌ Annuler")
        cancel_btn.setStyleSheet("""
            QPushButton { background: #3a3a3a; color: white; border: none;
                border-radius: 6px; padding: 10px 25px; font-weight: bold; font-size: 13px; }
            QPushButton:hover { background: #4a4a4a; }
        """)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        dialog.exec()

    def _apply_ia_config(self, dialog, sliders, nerv_sl=None, drop_combo=None):
        """Applique la config IA Lumiere"""
        for key, slider in sliders.items():
            self.ia_max_dimmers[key] = slider.value()
        self.ia_max_dimmers['contre'] = self.ia_max_dimmers['lat']
        if nerv_sl is not None:
            self.ia_params['nervosity'] = nerv_sl.value()
        if drop_combo is not None:
            self.ia_params['drop_effect'] = drop_combo.currentData()
        self.save_ia_lumiere_config()
        dialog.accept()

    def save_ia_lumiere_config(self):
        """Sauvegarde la configuration IA Lumiere"""
        try:
            config_path = Path.home() / '.maestro_ia_lumiere.json'
            data = {
                'max_dimmers': self.ia_max_dimmers,
                'params':      self.ia_params,
            }
            with open(config_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Erreur sauvegarde IA config: {e}")

    def load_ia_lumiere_config(self):
        """Charge la configuration IA Lumiere"""
        try:
            config_path = Path.home() / '.maestro_ia_lumiere.json'
            if config_path.exists():
                with open(config_path, 'r') as f:
                    data = json.load(f)
                # Compatibilité ancien format (dict plat)
                if 'max_dimmers' in data:
                    self.ia_max_dimmers.update(data['max_dimmers'])
                    self.ia_params.update(data.get('params', {}))
                else:
                    self.ia_max_dimmers.update(data)
        except Exception as e:
            print(f"Erreur chargement IA config: {e}")

    def test_dmx_on_startup(self):
        """Test automatique de la connexion DMX au demarrage"""
        # Bloquer DMX si licence non autorisee
        if not self._license.dmx_allowed:
            self.dmx.connected = False
            print("DMX bloque par la licence")
            return

        # Creer le socket UDP inconditionnellement (Art-Net = UDP sans confirmation,
        # pas besoin de ping pour ouvrir le socket)
        if self.dmx.connect():
            # Réactiver le toggle plan de feu si la licence vient d'être reconnectée
            if hasattr(self, 'plan_de_feu') and not self.plan_de_feu.is_dmx_enabled():
                self.plan_de_feu.set_dmx_unblocked()
            self.update_connection_indicators()

    def _log_startup_status(self):
        """Rapport d'état initial des sorties au démarrage."""
        # Sortie DMX
        dmx_on = self._license.dmx_allowed and getattr(self.dmx, 'connected', False)
        if dmx_on:
            self._log_message("Sortie DMX : activée", "success")
        else:
            self._log_message("Sortie DMX : désactivée", "info")

        # Sortie vidéo (toujours off au démarrage)
        self._log_message("Sortie vidéo : désactivée", "info")


    def update_connection_indicators(self):
        """Met a jour les indicateurs de connexion"""
        akai_connected = False
        if MIDI_AVAILABLE and self.midi_handler.midi_in and self.midi_handler.midi_out:
            try:
                akai_connected = self.midi_handler.midi_in.is_port_open() and self.midi_handler.midi_out.is_port_open()
            except:
                pass

        if akai_connected:
            print("AKAI: Connecte")
        else:
            print("AKAI: Deconnecte")

        if self.dmx.connected:
            print(f"Boitier DMX: Connecte ({self.dmx.target_ip})")
        else:
            print("Boitier DMX: Deconnecte")

    # ==================== MENU CONNEXION ====================

    def test_akai_connection(self):
        """Teste la connexion AKAI. Si OK : message de confirmation. Sinon : diagnostic complet."""
        if not MIDI_AVAILABLE:
            self.show_midi_diagnostic()
            return

        # Vérifier si déjà connecté
        connected = False
        if self.midi_handler.midi_in and self.midi_handler.midi_out:
            try:
                connected = (self.midi_handler.midi_in.is_port_open() and
                             self.midi_handler.midi_out.is_port_open())
            except Exception:
                pass

        if connected:
            _dlg = QDialog(self)
            _dlg.setWindowTitle("AKAI APC Mini MK2")
            _dlg.setFixedSize(320, 170)
            _dlg.setStyleSheet("QDialog,QWidget{background:#1a1a1a;color:#e0e0e0;}"
                               "QLabel{background:transparent;}")
            _lay = QVBoxLayout(_dlg)
            _lay.setContentsMargins(24, 20, 24, 20)
            _lay.setSpacing(12)
            _ico = QLabel("🎹")
            _ico.setAlignment(Qt.AlignCenter)
            _ico.setStyleSheet("font-size:32px;")
            _lay.addWidget(_ico)
            _msg = QLabel("AKAI APC mini connecté et opérationnel")
            _msg.setAlignment(Qt.AlignCenter)
            _msg.setStyleSheet("font-size:13px;font-weight:bold;color:#4CAF50;")
            _lay.addWidget(_msg)
            _btn_row = QHBoxLayout()
            _btn_reconnect = QPushButton("🔄  Actualiser")
            _btn_reconnect.setFixedHeight(32)
            _btn_reconnect.setStyleSheet("QPushButton{background:#1a3a5a;color:white;border:none;"
                                         "border-radius:5px;font-size:12px;}"
                                         "QPushButton:hover{background:#1e4a7a;}")
            _btn_reconnect.clicked.connect(lambda: (_dlg.accept(), self.reset_akai()))
            _btn_row.addWidget(_btn_reconnect)
            _btn = QPushButton("OK")
            _btn.setFixedHeight(32)
            _btn.setStyleSheet("QPushButton{background:#2a5a2a;color:white;border:none;"
                               "border-radius:5px;font-size:12px;}"
                               "QPushButton:hover{background:#3a7a3a;}")
            _btn.clicked.connect(_dlg.accept)
            _btn_row.addWidget(_btn)
            _lay.addLayout(_btn_row)
            _dlg.exec()
            return

        # Pas connecté — tenter reconnexion automatique d'abord
        self.midi_handler.connect_akai()
        reconnected = False
        if self.midi_handler.midi_in and self.midi_handler.midi_out:
            try:
                reconnected = (self.midi_handler.midi_in.is_port_open() and
                               self.midi_handler.midi_out.is_port_open())
            except Exception:
                pass

        if reconnected:
            QTimer.singleShot(200, self.activate_default_white_pads)
            QTimer.singleShot(300, self.turn_off_all_effects)
            QTimer.singleShot(400, self._sync_faders_to_projectors)
            _dlg = QDialog(self)
            _dlg.setWindowTitle("AKAI APC Mini MK2")
            _dlg.setFixedSize(320, 140)
            _dlg.setStyleSheet("QDialog,QWidget{background:#1a1a1a;color:#e0e0e0;}"
                               "QLabel{background:transparent;}")
            _lay = QVBoxLayout(_dlg)
            _lay.setContentsMargins(24, 20, 24, 20)
            _lay.setSpacing(12)
            _ico = QLabel("🎹")
            _ico.setAlignment(Qt.AlignCenter)
            _ico.setStyleSheet("font-size:32px;")
            _lay.addWidget(_ico)
            _msg = QLabel("AKAI APC mini reconnecté avec succès !")
            _msg.setAlignment(Qt.AlignCenter)
            _msg.setStyleSheet("font-size:13px;font-weight:bold;color:#4CAF50;")
            _lay.addWidget(_msg)
            _btn = QPushButton("OK")
            _btn.setFixedHeight(32)
            _btn.setStyleSheet("QPushButton{background:#2a5a2a;color:white;border:none;"
                               "border-radius:5px;font-size:12px;}"
                               "QPushButton:hover{background:#3a7a3a;}")
            _btn.clicked.connect(_dlg.accept)
            _lay.addWidget(_btn)
            _dlg.exec()
        else:
            # Échec — dialog intermédiaire avec bouton "Ouvrir le diagnostic"
            import sys as _sys
            import subprocess as _sub
            _dlg = QDialog(self)
            _dlg.setWindowTitle("AKAI APC Mini MK2")
            _dlg.setFixedSize(360, 190)
            _dlg.setStyleSheet("QDialog,QWidget{background:#1a1a1a;color:#e0e0e0;}"
                               "QLabel{background:transparent;}")
            _lay = QVBoxLayout(_dlg)
            _lay.setContentsMargins(24, 20, 24, 20)
            _lay.setSpacing(10)
            _ico = QLabel("⚠️")
            _ico.setAlignment(Qt.AlignCenter)
            _ico.setStyleSheet("font-size:28px;")
            _lay.addWidget(_ico)
            _msg = QLabel("Connexion échouée — AKAI non détecté")
            _msg.setAlignment(Qt.AlignCenter)
            _msg.setStyleSheet("font-size:13px;font-weight:bold;color:#f44336;")
            _lay.addWidget(_msg)
            # Bouton Audio MIDI Setup (Mac uniquement)
            if _sys.platform == "darwin":
                _btn_midi_setup = QPushButton("🎹  Ouvrir Audio MIDI Setup")
                _btn_midi_setup.setFixedHeight(34)
                _btn_midi_setup.setStyleSheet(
                    "QPushButton{background:#3a2a5a;color:white;border:none;border-radius:5px;font-size:12px;font-weight:bold;}"
                    "QPushButton:hover{background:#4a3a7a;}")
                _btn_midi_setup.setToolTip("Vérifier que l'APC mini est bien visible dans Audio MIDI Setup")
                _btn_midi_setup.clicked.connect(lambda: _sub.Popen(["open", "-a", "Audio MIDI Setup"]))
                _lay.addWidget(_btn_midi_setup)
            _btn_row = QHBoxLayout()
            _btn_refresh = QPushButton("🔄  Actualiser")
            _btn_refresh.setFixedHeight(32)
            _btn_refresh.setStyleSheet("QPushButton{background:#2a5a2a;color:white;border:none;border-radius:5px;font-size:12px;}"
                                       "QPushButton:hover{background:#3a7a3a;}")
            _btn_refresh.clicked.connect(lambda: (_dlg.accept(), self.test_akai_connection()))
            _btn_row.addWidget(_btn_refresh)
            _btn_diag = QPushButton("Diagnostic")
            _btn_diag.setFixedHeight(32)
            _btn_diag.setStyleSheet("QPushButton{background:#1a3a5a;color:white;border:none;border-radius:5px;font-size:12px;}"
                                    "QPushButton:hover{background:#1e4a7a;}")
            _btn_diag.clicked.connect(lambda: (_dlg.accept(), self.show_midi_diagnostic()))
            _btn_row.addWidget(_btn_diag)
            _btn_close2 = QPushButton("Fermer")
            _btn_close2.setFixedHeight(32)
            _btn_close2.setStyleSheet("QPushButton{background:#2a2a2a;color:#aaa;border:1px solid #3a3a3a;border-radius:5px;font-size:12px;}"
                                      "QPushButton:hover{background:#333;color:#ddd;}")
            _btn_close2.clicked.connect(_dlg.accept)
            _btn_row.addWidget(_btn_close2)
            _lay.addLayout(_btn_row)
            _dlg.exec()

    def reset_akai(self):
        """Reinitialise la connexion, les LEDs et les faders de l'AKAI"""
        if not MIDI_AVAILABLE:
            QMessageBox.warning(self, "AKAI", "Module MIDI non installe.")
            return

        try:
            self.midi_handler.connect_akai()
            if self.midi_handler.midi_in and self.midi_handler.midi_out:
                # Éteindre les LEDs mute sur l'AKAI physique
                for idx in range(8):
                    self.midi_handler.midi_out.send_message([0x90, 100 + idx, 0])
                self._muted_faders.clear()
                for btn in self.fader_buttons:
                    btn.active = False
                    btn.update_style()
                QTimer.singleShot(200, self.activate_default_white_pads)
                QTimer.singleShot(300, self.turn_off_all_effects)
                # Synchroniser les faders UI avec les niveaux actuels des projecteurs
                QTimer.singleShot(400, self._sync_faders_to_projectors)
                QMessageBox.information(self, "AKAI", "AKAI reinitialise avec succes !")
            else:
                QMessageBox.warning(self, "AKAI",
                    "AKAI APC mini non detecte.\n\n"
                    "Verifiez que le controleur est branche en USB.")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Erreur reinitialisation AKAI: {e}")

    def show_midi_diagnostic(self):
        """Affiche tous les ports MIDI disponibles pour diagnostiquer la detection AKAI."""
        import sys
        import subprocess
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit

        is_mac = sys.platform == "darwin"
        is_win = sys.platform == "win32"

        # ── Construire le rapport texte ────────────────────────────────────
        lines = []

        def _is_akai(name):
            return 'APC' in name.upper() or 'AKAI' in name.upper()

        # Infos système
        lines.append(f"Plateforme : {'macOS' if is_mac else 'Windows' if is_win else sys.platform}")
        lines.append(f"Python : {sys.version.split()[0]}")
        lines.append("")

        if not MIDI_AVAILABLE:
            lines.append("ERREUR : Module MIDI non installe.")
            if is_mac:
                lines.append("Installez avec : pip install python-rtmidi")
            else:
                lines.append("Installez avec : pip install rtmidi2")
        else:
            try:
                try:
                    import rtmidi as _rt
                    lib_name = "python-rtmidi"
                except ImportError:
                    import rtmidi2 as _rt
                    lib_name = "rtmidi2"

                lines.append(f"Librairie MIDI : {lib_name}")
                lines.append("")

                mi = _rt.MidiIn()
                in_ports = mi.get_ports()
                try:
                    mi.close_port()
                except Exception:
                    pass

                mo = _rt.MidiOut()
                out_ports = mo.get_ports()
                try:
                    mo.close_port()
                except Exception:
                    pass

                lines.append("── Ports ENTREE (IN) ──────────────────")
                if in_ports:
                    for i, name in enumerate(in_ports):
                        marker = " ✅ AKAI detecte" if _is_akai(name) else ""
                        lines.append(f"  [{i}]  {name}{marker}")
                else:
                    lines.append("  (aucun port detecte)")

                lines.append("")
                lines.append("── Ports SORTIE (OUT) ─────────────────")
                if out_ports:
                    for i, name in enumerate(out_ports):
                        marker = " ✅ AKAI detecte" if _is_akai(name) else ""
                        lines.append(f"  [{i}]  {name}{marker}")
                else:
                    lines.append("  (aucun port detecte)")

                lines.append("")
                lines.append("── Statut connexion actuelle ───────────")
                akai_connected = (self.midi_handler.midi_in is not None and
                                  self.midi_handler.midi_out is not None)
                lines.append(f"  AKAI APC mini : {'Connecte ✅' if akai_connected else 'Non connecte ❌'}")

                if not any(_is_akai(p) for p in in_ports + out_ports):
                    lines.append("")
                    lines.append("⚠ Aucun port AKAI/APC detecte.")
                    lines.append("  • Verifiez le cable USB")
                    lines.append("  • Essayez un autre port USB")
                    if is_mac:
                        lines.append("  • Mac : ouvrez Configuration MIDI Audio")
                        lines.append("    (Finder > Applications > Utilitaires)")
                        lines.append("    Verifiez que APC mini est visible dans la liste")
                        lines.append("  • Essayez de debrancher/rebrancher l'AKAI")
                        lines.append("  • Si le port apparait en gris : cliquez sur la fleche")
                        lines.append("    pour activer le peripherique")
                    else:
                        lines.append("  • Windows : Gestionnaire de peripheriques")
                        lines.append("    > Controleurs audio, video et jeu")

            except Exception as e:
                lines.append(f"Erreur lors de l'enumeration MIDI :")
                lines.append(f"  {e}")

        report = "\n".join(lines)

        # ── Dialogue ───────────────────────────────────────────────────────
        dlg = QDialog(self)
        dlg.setWindowTitle("Diagnostique AKAI")
        dlg.setFixedSize(520, 420)
        dlg.setStyleSheet("QDialog, QWidget { background: #1a1a1a; color: #e0e0e0; }"
                          "QLabel { background: transparent; }")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Diagnostique AKAI APC mini")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #00d4ff;")
        layout.addWidget(title)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(report)
        txt.setFont(QFont("Consolas", 10))
        txt.setStyleSheet(
            "QTextEdit { background: #111; color: #ddd; border: 1px solid #333;"
            " border-radius: 4px; padding: 8px; }"
            "QScrollBar:vertical { background:#1a1a1a; width:8px; border-radius:4px; }"
            "QScrollBar::handle:vertical { background:#444; border-radius:4px; }"
        )
        layout.addWidget(txt)

        btn_row = QHBoxLayout()

        btn_copy = QPushButton("Copier le rapport")
        btn_copy.setFixedHeight(34)
        btn_copy.setStyleSheet("QPushButton{background:#1a3a5a;color:white;border:none;border-radius:5px;font-size:12px;}"
                               "QPushButton:hover{background:#1e4a7a;}")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(report))
        btn_row.addWidget(btn_copy)

        # Bouton système selon la plateforme
        if is_mac:
            btn_sys = QPushButton("🎹 Configuration MIDI Audio")
            btn_sys.setFixedHeight(34)
            btn_sys.setStyleSheet("QPushButton{background:#3a2a5a;color:white;border:none;border-radius:5px;font-size:12px;}"
                                  "QPushButton:hover{background:#4a3a7a;}")
            btn_sys.clicked.connect(lambda: subprocess.Popen(["open", "-a", "Audio MIDI Setup"]))
            btn_row.addWidget(btn_sys)
        elif is_win:
            btn_sys = QPushButton("⚙️ Gestionnaire périphériques")
            btn_sys.setFixedHeight(34)
            btn_sys.setStyleSheet("QPushButton{background:#3a2a5a;color:white;border:none;border-radius:5px;font-size:12px;}"
                                  "QPushButton:hover{background:#4a3a7a;}")
            btn_sys.clicked.connect(lambda: subprocess.Popen(["devmgmt.msc"], shell=True))
            btn_row.addWidget(btn_sys)

        btn_reconnect = QPushButton("Reconnexion")
        btn_reconnect.setFixedHeight(34)
        btn_reconnect.setStyleSheet("QPushButton{background:#2a5a2a;color:white;border:none;border-radius:5px;font-size:12px;}"
                                    "QPushButton:hover{background:#3a7a3a;}")
        btn_reconnect.clicked.connect(lambda: (dlg.accept(), self.test_akai_connection()))
        btn_row.addWidget(btn_reconnect)

        btn_close = QPushButton("Fermer")
        btn_close.setFixedHeight(34)
        btn_close.setStyleSheet("QPushButton{background:#2a2a2a;color:#aaa;border:1px solid #3a3a3a;border-radius:5px;font-size:12px;}"
                                "QPushButton:hover{background:#333;color:#ddd;}")
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

        # ── Bouton redémarrage ────────────────────────────────────────────
        def _restart_app():
            import subprocess as _sp
            _sp.Popen([sys.executable] + sys.argv)
            QApplication.quit()

        restart_hint = QLabel("Si l'AKAI n'est toujours pas détecté, un redémarrage résout souvent le problème.")
        restart_hint.setWordWrap(True)
        restart_hint.setAlignment(Qt.AlignCenter)
        restart_hint.setStyleSheet("color: #888; font-size: 10px; background: transparent;")
        layout.addWidget(restart_hint)

        btn_restart = QPushButton("⟳  Redémarrer MyStrow")
        btn_restart.setFixedHeight(38)
        btn_restart.setCursor(Qt.PointingHandCursor)
        btn_restart.setStyleSheet(
            "QPushButton{background:#7a4a00;color:white;border:none;border-radius:5px;"
            "font-size:13px;font-weight:bold;}"
            "QPushButton:hover{background:#a86200;}"
        )
        btn_restart.clicked.connect(_restart_app)
        layout.addWidget(btn_restart)

        dlg.exec()

    def _sync_faders_to_projectors(self):
        """Synchronise les faders UI avec les niveaux actuels des projecteurs"""
        for col_idx, slot in enumerate(self._fader_map):
            if slot["type"] != "group":
                continue
            groups = self._slot_groups(slot)
            for p in self.projectors:
                if p.group in groups:
                    if col_idx in self.faders:
                        self.faders[col_idx].set_value(p.level)
                    break

    def open_dmx_tester(self):
        """Ouvre l'outil de diagnostic DMX canal par canal."""
        from dmx_tester import DmxTesterDialog
        self.dmx_send_timer.stop()
        try:
            dlg = DmxTesterDialog(self.dmx, self)
            dlg.exec()
        finally:
            self.dmx_send_timer.start(40)

    def open_node_connection(self):
        """Ouvre le dialogue de paramétrage de la sortie DMX (Node ou USB)."""
        from node_connection import DmxOutputDialog
        dlg = DmxOutputDialog(self)
        dlg.exec()
        self._refresh_dmx_menu_title()

    def open_node_wizard_at_ip_manual(self, adapter_name: str):
        """Ouvre directement le wizard Node à la page de configuration IP manuelle.
        Utilisé après un redémarrage en mode administrateur."""
        from node_connection import NodeSetupWizard
        dlg = NodeSetupWizard(self)
        dlg.jump_to_ip_manual(adapter_name)
        dlg.exec()
        self._refresh_dmx_menu_title()

    def _refresh_dmx_menu_title(self):
        """Met à jour le titre du menu Sortie selon le transport actif."""
        if not hasattr(self, 'node_menu'):
            return
        try:
            from artnet_dmx import TRANSPORT_ENTTEC
            if self.dmx.transport == TRANSPORT_ENTTEC:
                self.node_menu.setTitle("🔌 Sortie DMX USB")
            else:
                self.node_menu.setTitle("🌐 Sortie DMX")
        except Exception:
            pass

    def open_brad_diagnostic(self):
        """Ouvre l'assistant BRAD — diagnostic complet DMX/réseau."""
        from brad_diagnostic import BradDiagnosticDialog
        dlg = BradDiagnosticDialog(self)
        dlg.exec()

    def test_node_connection(self):
        """Diagnostic Node DMX : carte reseau + node"""
        if not self._license.dmx_allowed:
            QMessageBox.warning(self, "Sortie DMX",
                "Votre periode d'essai est terminee ou le logiciel n'est pas active.\nActivez une licence pour utiliser la sortie Art-Net.")
            return

        import socket as _socket
        from node_connection import _get_ethernet_adapters, _artpoll_packet, TARGET_IP, TARGET_PORT

        dlg = QDialog(self)
        dlg.setWindowTitle("Diagnostic Node DMX")
        dlg.setFixedSize(460, 260)
        dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        dlg.setStyleSheet(
            "QDialog { background: #1a1a1a; }"
            "QLabel { color: #cccccc; border: none; background: transparent; }"
        )

        root = QVBoxLayout(dlg)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(16)

        title = QLabel("Diagnostic de la sortie Node DMX")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title.setStyleSheet("color: #00d4ff;")
        root.addWidget(title)

        def _make_check_row(label_text):
            row = QHBoxLayout()
            row.setSpacing(14)
            icon = QLabel("…")
            icon.setFont(QFont("Segoe UI", 16))
            icon.setFixedWidth(26)
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet("color: #555555;")
            row.addWidget(icon)
            col = QVBoxLayout()
            col.setSpacing(1)
            lbl = QLabel(label_text)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
            col.addWidget(lbl)
            detail = QLabel("Vérification en cours...")
            detail.setFont(QFont("Segoe UI", 9))
            detail.setStyleSheet("color: #555555;")
            detail.setWordWrap(True)
            col.addWidget(detail)
            row.addLayout(col, 1)
            root.addLayout(row)
            return icon, detail

        icon_net, detail_net = _make_check_row("Carte réseau")
        icon_node, detail_node = _make_check_row("Node DMX")

        root.addStretch()

        import sys as _sys
        import subprocess as _sub
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_config = QPushButton("Ouvrir l'assistant de connexion")
        btn_config.setFixedHeight(30)
        btn_config.setStyleSheet(
            "QPushButton { background: #1e3a4a; color: #00d4ff; border: 1px solid #00d4ff;"
            " border-radius: 4px; padding: 0 14px; font-size: 10px; }"
            "QPushButton:hover { background: #254a5a; }"
        )
        btn_config.hide()
        btn_config.clicked.connect(lambda: (dlg.accept(), self.open_node_connection()))
        btn_row.addWidget(btn_config)
        # Bouton connexions réseau selon la plateforme
        if _sys.platform == "darwin":
            btn_net = QPushButton("🌐  Préférences Réseau")
            btn_net.setFixedHeight(30)
            btn_net.setStyleSheet(
                "QPushButton { background: #2a2a3a; color: #aaaacc; border: 1px solid #44448888;"
                " border-radius: 4px; padding: 0 14px; font-size: 10px; }"
                "QPushButton:hover { background: #333355; color: #ccccee; }"
            )
            btn_net.setToolTip("Ouvrir les Préférences Réseau macOS pour configurer l'IP")
            btn_net.clicked.connect(lambda: _sub.Popen(
                ["open", "x-apple.systempreferences:com.apple.preference.network"]))
        else:
            btn_net = QPushButton("🌐  Connexions réseau")
            btn_net.setFixedHeight(30)
            btn_net.setStyleSheet(
                "QPushButton { background: #2a2a3a; color: #aaaacc; border: 1px solid #44448888;"
                " border-radius: 4px; padding: 0 14px; font-size: 10px; }"
                "QPushButton:hover { background: #333355; color: #ccccee; }"
            )
            btn_net.setToolTip("Ouvrir les connexions réseau Windows")
            from node_connection import _open_network_connections
            btn_net.clicked.connect(_open_network_connections)
        btn_row.addWidget(btn_net)
        btn_close = QPushButton("Fermer")
        btn_close.setFixedHeight(30)
        btn_close.setStyleSheet(
            "QPushButton { background: #2a2a2a; color: #aaaaaa; border: 1px solid #3a3a3a;"
            " border-radius: 4px; padding: 0 14px; font-size: 10px; }"
            "QPushButton:hover { background: #333333; color: white; }"
        )
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        dlg.show()
        QApplication.processEvents()

        # --- Vérification 1 : carte réseau ---
        adapters = _get_ethernet_adapters()
        ok_adapters = [(n, ip) for n, ip, *_ in adapters if ip.startswith("2.0.0.")]

        if ok_adapters:
            name, ip = ok_adapters[0]
            icon_net.setText("✓")
            icon_net.setStyleSheet("color: #4CAF50;")
            detail_net.setText(f"{name}  —  IP : {ip}")
            detail_net.setStyleSheet("color: #4CAF50;")
            net_ok = True
        elif adapters:
            name, ip = adapters[0][0], adapters[0][1]
            ip_display = ip if ip else "non configurée"
            icon_net.setText("⚠")
            icon_net.setStyleSheet("color: #ff9800;")
            detail_net.setText(f"{name}  —  IP : {ip_display}  (attendu : 2.0.0.x)")
            detail_net.setStyleSheet("color: #ff9800;")
            net_ok = False
        else:
            icon_net.setText("✗")
            icon_net.setStyleSheet("color: #f44336;")
            detail_net.setText("Aucune carte Ethernet détectée — vérifiez le câble RJ45")
            detail_net.setStyleSheet("color: #f44336;")
            net_ok = False

        QApplication.processEvents()

        # --- Vérification 2 : node ArtPoll (broadcast + IP cible) ---
        node_ok = False
        found_ip = None
        # Adresses à sonder : broadcast Art-Net d'abord, puis IP cible fixe
        _ARTNET_PORT = 6454
        _probe_ips = ["2.255.255.255", "255.255.255.255", TARGET_IP]
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.setsockopt(_socket.SOL_SOCKET, _socket.SO_BROADCAST, 1)
            s.settimeout(1.5)
            s.bind(("", _ARTNET_PORT))
            for _ip in _probe_ips:
                try:
                    s.sendto(_artpoll_packet(), (_ip, _ARTNET_PORT))
                except Exception:
                    pass
            # Écouter toutes les réponses pendant la fenêtre de timeout
            import time as _time
            _deadline = _time.time() + 1.5
            while _time.time() < _deadline:
                try:
                    s.settimeout(max(0.05, _deadline - _time.time()))
                    data, (sender_ip, _) = s.recvfrom(512)
                    if data[:8] == b'Art-Net\x00':
                        node_ok = True
                        found_ip = sender_ip
                        break
                except _socket.timeout:
                    break
                except Exception:
                    break
            s.close()
        except Exception:
            node_ok = False

        if node_ok:
            icon_node.setText("✓")
            icon_node.setStyleSheet("color: #4CAF50;")
            if found_ip != self.dmx.target_ip:
                detail_node.setText(
                    f"Répond sur {found_ip}  —  Art-Net opérationnel\n"
                    f"IP cible mise à jour ({self.dmx.target_ip} → {found_ip})"
                )
                self.dmx.connect(target_ip=found_ip)
            else:
                detail_node.setText(f"Répond sur {found_ip}  —  Art-Net opérationnel")
                if not self.dmx.connected:
                    self.dmx.connect()
            detail_node.setStyleSheet("color: #4CAF50;")
        else:
            icon_node.setText("✗")
            icon_node.setStyleSheet("color: #f44336;")
            if net_ok:
                detail_node.setText(
                    f"Aucun boîtier Art-Net détecté sur le réseau 2.x.x.x\n"
                    f"Vérifiez que le boîtier est allumé et le câble RJ45 branché"
                )
            else:
                detail_node.setText("Configurez d'abord la carte réseau (2.0.0.1 / 255.0.0.0)")
            detail_node.setStyleSheet("color: #f44336;")

        if not net_ok or not node_ok:
            btn_config.show()

        QApplication.processEvents()
        dlg.exec()

    def configure_node(self):
        """Configure les parametres du Node DMX"""
        if not self._license.dmx_allowed:
            QMessageBox.warning(self, "Sortie DMX",
                "Votre periode d'essai est terminee ou le logiciel n'est pas active.\nActivez une licence pour utiliser la sortie Art-Net.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Parametres NODE DMX")
        dialog.setFixedSize(350, 310)
        dialog.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel { color: white; border: none; }
            QLineEdit {
                background: #2a2a2a; color: white; border: 1px solid #3a3a3a;
                border-radius: 4px; padding: 6px; font-size: 12px;
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(10)

        title = QLabel("Configuration du Node DMX")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # IP
        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("Adresse IP:"))
        ip_edit = QLineEdit(self.dmx.target_ip)
        ip_layout.addWidget(ip_edit)
        layout.addLayout(ip_layout)

        # Port
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port:"))
        port_edit = QLineEdit(str(self.dmx.target_port))
        port_layout.addWidget(port_edit)
        layout.addLayout(port_layout)

        # Univers
        univers_layout = QHBoxLayout()
        univers_layout.addWidget(QLabel("Univers:"))
        univers_edit = QLineEdit(str(self.dmx.universe))
        univers_layout.addWidget(univers_edit)
        layout.addLayout(univers_layout)

        # Miroir sortie 2
        from PySide6.QtWidgets import QCheckBox
        mirror_chk = QCheckBox("Miroir sur sortie 2  (univers suivant)")
        mirror_chk.setChecked(self.dmx.mirror_output)
        mirror_chk.setStyleSheet("color: white;")
        layout.addWidget(mirror_chk)

        univers2_layout = QHBoxLayout()
        univers2_label = QLabel("  Univers sortie 2:")
        univers2_edit  = QLineEdit(str(self.dmx.universe2))
        univers2_layout.addWidget(univers2_label)
        univers2_layout.addWidget(univers2_edit)
        layout.addLayout(univers2_layout)

        def _toggle_univers2(checked):
            univers2_label.setEnabled(checked)
            univers2_edit.setEnabled(checked)
        _toggle_univers2(mirror_chk.isChecked())
        mirror_chk.toggled.connect(_toggle_univers2)

        # Boutons
        btn_layout = QHBoxLayout()
        apply_btn = QPushButton("Appliquer")
        apply_btn.setStyleSheet("""
            QPushButton { background: #2a5a2a; color: white; border: none;
                border-radius: 6px; padding: 8px 20px; font-weight: bold; }
            QPushButton:hover { background: #3a7a3a; }
        """)

        def apply_config():
            new_ip = ip_edit.text().strip()
            try:
                new_port = int(port_edit.text().strip())
            except ValueError:
                new_port = self.dmx.target_port
            try:
                new_universe = int(univers_edit.text().strip())
            except ValueError:
                new_universe = self.dmx.universe
            try:
                new_universe2 = int(univers2_edit.text().strip())
            except ValueError:
                new_universe2 = new_universe + 1
            new_mirror = mirror_chk.isChecked()
            # Force transport artnet (le dialog "Configure NODE" est toujours Art-Net)
            from artnet_dmx import TRANSPORT_ARTNET
            self.dmx.connected = False
            self.dmx.connect(
                transport=TRANSPORT_ARTNET,
                target_ip=new_ip,
                target_port=new_port,
                universe=new_universe,
                universe2=new_universe2,
                mirror_output=new_mirror,
            )
            dialog.accept()
            mirror_info = f"\nMiroir sortie 2: univers {self.dmx.universe2}" if new_mirror else ""
            QMessageBox.information(self, "NODE",
                f"Configuration appliquee:\n"
                f"IP: {self.dmx.target_ip}\n"
                f"Port: {self.dmx.target_port}\n"
                f"Univers: {self.dmx.universe}"
                f"{mirror_info}")

        apply_btn.clicked.connect(apply_config)
        btn_layout.addWidget(apply_btn)

        cancel_btn = QPushButton("Annuler")
        cancel_btn.setStyleSheet("""
            QPushButton { background: #3a3a3a; color: white; border: none;
                border-radius: 6px; padding: 8px 20px; font-weight: bold; }
            QPushButton:hover { background: #4a4a4a; }
        """)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        dialog.exec()

    def play_test_sound(self):
        """Genere et joue un son de test 440Hz"""
        import wave
        import struct
        import tempfile

        # Generer un WAV 440Hz d'une seconde
        sample_rate = 44100
        duration = 1.0
        frequency = 440.0
        amplitude = 0.5

        filepath = os.path.join(tempfile.gettempdir(), "maestro_test_440hz.wav")
        try:
            with wave.open(filepath, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                num_samples = int(sample_rate * duration)
                import math
                for i in range(num_samples):
                    sample = amplitude * math.sin(2.0 * math.pi * frequency * i / sample_rate)
                    wf.writeframes(struct.pack('<h', int(sample * 32767)))

            self.cart_player.setSource(QUrl.fromLocalFile(filepath))
            self.cart_player.play()
            QMessageBox.information(self, "AUDIO", "Son de test envoyé !")
        except Exception as e:
            QMessageBox.warning(self, "AUDIO", f"Erreur generation son: {e}")

    def _populate_audio_output_menu(self):
        """Remplit dynamiquement le sous-menu Sortie Audio avec les peripheriques"""
        self.audio_output_menu.clear()
        devices = QMediaDevices.audioOutputs()
        current_device = self.audio.device()

        for dev in devices:
            action = self.audio_output_menu.addAction(dev.description())
            action.setCheckable(True)
            action.setChecked(dev.id() == current_device.id())
            action.triggered.connect(lambda checked, d=dev: self._set_audio_output(d))

    def _set_audio_output(self, device):
        """Change le peripherique de sortie audio"""
        self.audio.setDevice(device)
        self.cart_audio.setDevice(device)

    def _populate_screen_menu(self):
        """Remplit dynamiquement le sous-menu de choix d'ecran"""
        self.video_screen_menu.clear()
        screens = QApplication.screens()
        for i, screen in enumerate(screens):
            geo = screen.geometry()
            label = f"Ecran {i + 1} ({screen.name()} - {geo.width()}x{geo.height()})"
            action = self.video_screen_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(i == self.video_target_screen)
            action.triggered.connect(lambda checked, idx=i: self._set_video_screen(idx))

    def _set_video_screen(self, screen_index):
        """Change l'ecran cible pour la sortie video"""
        self.video_target_screen = screen_index
        # Si la fenetre est deja ouverte, la deplacer
        if self.video_output_window and self.video_output_window.isVisible():
            screens = QApplication.screens()
            if screen_index < len(screens):
                screen = screens[screen_index]
                self.video_output_window.setGeometry(screen.geometry())
                self.video_output_window.showFullScreen()

    def show_test_logo(self):
        """Affiche le logo de test pendant 3 secondes (preview + externe si active)"""
        from core import resource_path
        logo_path = resource_path("logo.png")
        if not os.path.exists(logo_path):
            QMessageBox.warning(self, "VIDEO", "Fichier logo.png introuvable.")
            return

        # Afficher dans le preview local (toujours)
        self.show_image(logo_path)

        # Afficher aussi dans la fenetre externe si elle est active
        if self.video_output_window and self.video_output_window.isVisible():
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                self.video_output_window.show_image(pixmap)

        # Masquer apres 3 secondes
        QTimer.singleShot(3000, self._hide_test_logo)

    def _hide_test_logo(self):
        """Cache le logo de test"""
        self.hide_image()
        if self.video_output_window and self.video_output_window.isVisible():
            self._update_video_output_state()

    def toggle_video_output_from_menu(self):
        """Active/desactive la sortie video depuis le menu"""
        self.video_output_btn.setChecked(not self.video_output_btn.isChecked())
        self.toggle_video_output()
        # Mettre a jour le texte du menu
        if self.video_output_btn.isChecked():
            self.video_menu_toggle.setText("🟢 Desactiver sortie video")
        else:
            self.video_menu_toggle.setText("🔴 Activer sortie video")

    def _compute_htp_overrides(self):
        """Calcule les valeurs HTP des memoires SANS modifier les projecteurs.
        Retourne un dict {id(proj): (level, QColor_display, QColor_base)} pour l'affichage."""
        overrides = {}

        for fi, mem_col in self._bank_memory_slots():
            col_akai = fi
            if col_akai in self._muted_faders:
                continue
            fv = self.faders[col_akai].value if col_akai in self.faders else 0
            active_row = self.active_memory_pads.get(col_akai)
            if fv > 0 and active_row is not None and self.memories[mem_col][active_row]:
                mem = self.memories[mem_col][active_row]
                self._mem_ensure_cues(mem)
                cue_idx = self._mem_cue_idx.get((mem_col, active_row), 0)
                cues = mem.get("cues", [])
                cue = cues[min(cue_idx, len(cues)-1)] if cues else {}
                mem_projs = cue.get("projectors", [])
                for i, proj in enumerate(self.projectors):
                    if i < len(mem_projs):
                        ms = mem_projs[i]
                        mem_level = int(ms["level"] * fv / 100.0)
                        # HTP: comparer avec le niveau actuel du projecteur ou override precedent
                        current_level = overrides[id(proj)][0] if id(proj) in overrides else proj.level
                        if mem_level > current_level:
                            base = QColor(ms["base_color"])
                            brt = mem_level / 100.0
                            color = QColor(
                                int(base.red() * brt),
                                int(base.green() * brt),
                                int(base.blue() * brt))
                            overrides[id(proj)] = (mem_level, color, base)

        return overrides

    def _apply_htp_to_projectors(self, overrides):
        """Applique temporairement les overrides HTP sur les projecteurs pour envoi DMX.
        Retourne la liste des etats sauvegardes pour restauration."""
        saved = []
        for proj in self.projectors:
            saved.append((proj.level, QColor(proj.color), QColor(proj.base_color)))
            if id(proj) in overrides:
                level, color, base = overrides[id(proj)]
                proj.level = level
                proj.color = color
                proj.base_color = base
        return saved

    def _apply_pad_overrides_htp(self):
        """Applique les pads AKAI actifs en HTP par-dessus l'etat courant des projecteurs.
        Retourne la liste des etats sauvegardes pour restauration apres envoi DMX."""
        saved = []
        for col_idx, btn in self.active_pads.items():
            if btn is None:
                continue
            if col_idx in self._muted_faders:
                continue
            color = btn.property("base_color")
            if color is None:
                continue
            fader_value = self.faders[col_idx].value if col_idx in self.faders else 0
            if fader_value <= 0:
                continue
            brightness = fader_value / 100.0
            pad_color = QColor(
                int(color.red() * brightness),
                int(color.green() * brightness),
                int(color.blue() * brightness),
            )
            # Get target groups from current fader map
            if col_idx < len(self._fader_map):
                slot = self._fader_map[col_idx]
                target_groups = self._slot_groups(slot)
            else:
                target_groups = []
            for i, proj in enumerate(self.projectors):
                if proj.group in target_groups and fader_value > proj.level:
                    saved.append((i, proj.level, proj.color, proj.base_color))
                    proj.level = fader_value
                    proj.color = pad_color
                    proj.base_color = color
        return saved

    def send_dmx_update(self):
        """Envoie les donnees DMX avec HTP memoires + pads AKAI + refresh plan de feu"""
        # Appliquer l'effet en cours — sauf si la timeline gère les projecteurs
        # (en mode Play Lumière, apply_timeline_to_dmx appelle update_effect() lui-même)
        _seq = getattr(self, 'seq', None)
        _timeline_active = hasattr(_seq, 'timeline_playback_row') if _seq else False
        if not _timeline_active and getattr(self, 'active_effect', None) is not None:
            self.update_effect()

        # Zéroter temporairement les projecteurs des mémoires mutées (enforcement du mute)
        muted_saved = {}
        for fi, mem_col in self._bank_memory_slots():
            if fi not in self._muted_faders:
                continue
            active_row = self.active_memory_pads.get(fi)
            if active_row is None:
                continue
            mem = self.memories[mem_col][active_row]
            if not mem:
                continue
            self._mem_ensure_cues(mem)
            cue_idx = self._mem_cue_idx.get((mem_col, active_row), 0)
            cues = mem.get("cues", [])
            cue = cues[min(cue_idx, len(cues) - 1)] if cues else {}
            for i, ps in enumerate(cue.get("projectors", [])):
                if i < len(self.projectors) and ps.get("level", 0) > 0 and i not in muted_saved:
                    p = self.projectors[i]
                    muted_saved[i] = (p.level, QColor(p.color), QColor(p.base_color))
                    p.level = 0
                    p.color = QColor("black")
                    p.base_color = QColor("black")

        # Calculer les overrides HTP sans modifier les projecteurs
        overrides = self._compute_htp_overrides()

        # Stocker les overrides sur le plan de feu
        self.plan_de_feu.set_htp_overrides(overrides if overrides else None)

        if self.plan_de_feu.is_dmx_enabled() and self.dmx.connected:
            # Appliquer temporairement HTP memoires
            if overrides:
                saved_htp = self._apply_htp_to_projectors(overrides)

            # Appliquer temporairement les pads AKAI en HTP (fonctionne dans TOUS les modes)
            saved_pads = self._apply_pad_overrides_htp()

            # Envoyer DMX
            self.dmx.update_from_projectors(self.projectors, self.effect_speed)
            self.dmx.send_dmx()

            # Restaurer etat pads
            for i, level, color, base_color in saved_pads:
                self.projectors[i].level = level
                self.projectors[i].color = color
                self.projectors[i].base_color = base_color

            # Restaurer etat HTP memoires
            if overrides:
                for i, proj in enumerate(self.projectors):
                    proj.level, proj.color, proj.base_color = saved_htp[i]
        elif self.dmx.connected and getattr(self.dmx, 'transport', '') == 'enttec':
            # ENTTEC : envoyer des frames nulles pour garder le lien actif (évite le timeout)
            self.dmx.send_dmx()

        # Restaurer les projecteurs des mémoires mutées
        for i, (level, color, base) in muted_saved.items():
            p = self.projectors[i]
            p.level = level
            p.color = color
            p.base_color = base

        # Rafraichir le plan de feu a chaque tick (25fps)
        self.plan_de_feu.mark_dirty()
        self.plan_de_feu.refresh()

        # Rafraichir la fenêtre 3D si visible
        if hasattr(self, '_plan3d') and self._plan3d.isVisible():
            self._plan3d.refresh(self.projectors)

    def stop_recording(self):
        """Arrete l'enregistrement"""
        if not self.seq.recording:
            return
        self.seq.recording = False
        if self.seq.recording_timer:
            self.seq.recording_timer.stop()
