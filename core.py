"""
Configuration globale et constantes pour MyStrow - Controleur Lumiere DMX
"""
import sys
import os
import json
import random
import socket
import struct
import wave
import array
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QFrame, QPushButton, QToolButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QSplitter, QSlider, QScrollArea, QStyle, QMenu, QWidgetAction,
    QMessageBox, QHeaderView, QComboBox, QDialog, QTabWidget
)
from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QPoint, QRect, QObject, Signal
from PySide6.QtGui import (
    QColor, QPainter, QBrush, QIcon, QPixmap, QCloseEvent, QFont,
    QPen, QPolygon, QCursor, QPalette, QLinearGradient
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

# === FILTRE FICHIERS MEDIA ===
MEDIA_EXTENSIONS_FILTER = "Medias (*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma *.aiff *.mp4 *.mov *.avi *.mkv *.wmv *.flv *.webm *.m4v *.mpg *.mpeg *.png *.jpg *.jpeg *.gif *.bmp *.svg *.webp *.tiff)"

# === CONFIGURATION GLOBALE ===
APP_NAME = "MyStrow"
VERSION = "3.0.13"

# === FIREBASE (cles dans firebase_config.py, non versionne) ===
try:
    from firebase_config import FIREBASE_API_KEY, FIREBASE_PROJECT_ID
except ImportError:
    FIREBASE_API_KEY    = ""
    FIREBASE_PROJECT_ID = ""

# === MIDI SUPPORT ===
# Détection via find_spec (sans importer le module — évite le scan MIDI au démarrage)
import importlib.util as _iutil
MIDI_AVAILABLE = False
midi_lib = None
if _iutil.find_spec("rtmidi") is not None:
    MIDI_AVAILABLE = True
    midi_lib = "rtmidi"
elif _iutil.find_spec("rtmidi2") is not None:
    MIDI_AVAILABLE = True
    midi_lib = "rtmidi2"

# === MAPPING COULEURS AKAI ===
AKAI_COLOR_MAP = {
    "white": 5,      # Jaune vif (le plus proche du blanc)
    "red": 3,        # Rouge vif
    "orange": 9,     # Orange vif
    "yellow": 13,    # Jaune-vert vif
    "green": 25,     # Vert lime vif
    "cyan": 37,      # Cyan
    "blue": 45,      # Bleu
    "violet": 53,    # Violet vif
    "magenta": 49,   # Rose/Magenta vif
}

# Mapping hex exact des couleurs du simulateur
HEX_COLOR_MAP = {
    "#ffffff": 3,   # Blanc -> Rouge vif (interverti avec ligne 2)
    "#ff0000": 5,   # Rouge -> Jaune (interverti avec ligne 1)
    "#ff8800": 9,   # Orange -> Orange vif (9)
    "#ffdd00": 13,  # Jaune -> Jaune vif (13)
    "#00ff00": 21,  # Vert -> Vert vif (21)
    "#00dddd": 37,  # Cyan -> Cyan (37)
    "#0000ff": 45,  # Bleu -> Bleu (45)
    "#ff00ff": 53,  # Magenta/Violet -> Violet (53)
}


def rgb_to_akai_velocity(qcolor):
    """Convertit une QColor RGB en velocite AKAI (approximation)"""
    r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()

    # Detection par couleur HTML (plus precis)
    hex_color = qcolor.name().lower()

    # Chercher la couleur exacte
    if hex_color in HEX_COLOR_MAP:
        return HEX_COLOR_MAP[hex_color]

    # Sinon, approximation par dominante
    # Blanc (toutes composantes elevees)
    if r > 200 and g > 200 and b > 200:
        return 5  # Jaune vif (proche du blanc)

    # Rouge dominant
    if r > 150 and g < 150 and b < 150:
        return 3  # Rouge pur

    # Orange (rouge + vert moyen)
    if r > 200 and g > 100 and g < 200 and b < 100:
        return 9  # Orange

    # Jaune (rouge + vert)
    if r > 200 and g > 200 and b < 100:
        return 13  # Jaune

    # Vert dominant
    if g > 150 and r < 150 and b < 150:
        return 21  # Vert

    # Cyan (vert + bleu)
    if g > 150 and b > 150 and r < 100:
        return 37  # Cyan

    # Bleu dominant
    if b > 150 and r < 150 and g < 150:
        return 45  # Bleu

    # Magenta (rouge + bleu)
    if r > 150 and b > 150 and g < 100:
        return 53  # Violet/Magenta

    # Par defaut
    return 5


def resource_path(filename):
    """Retourne le chemin absolu d'une ressource embarquee.
    Compatible mode dev et PyInstaller --onefile (sys._MEIPASS)."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def fmt_time(ms):
    """Formate un temps en millisecondes en MM:SS"""
    if ms <= 0:
        return "00:00"
    s = ms // 1000
    return f"{s//60:02d}:{s%60:02d}"


def media_icon(path):
    """Retourne un emoji selon le type de fichier media"""
    ext = Path(path).suffix.lower()
    if ext in [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".aiff"]:
        return "audio"
    if ext in [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"]:
        return "video"
    if ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tiff"]:
        return "image"
    return "file"


def create_icon(icon_type, color="#ffffff"):
    """Cree des icones elegantes type console pro"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    if icon_type == "play":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        points = [QPoint(18, 12), QPoint(18, 52), QPoint(52, 32)]
        painter.drawPolygon(QPolygon(points))
    elif icon_type == "pause":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(18, 12, 10, 40, 2, 2)
        painter.drawRoundedRect(36, 12, 10, 40, 2, 2)
    elif icon_type == "prev":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(16, 18, 4, 28, 2, 2)
        points = [QPoint(48, 18), QPoint(48, 46), QPoint(22, 32)]
        painter.drawPolygon(QPolygon(points))
    elif icon_type == "next":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(44, 18, 4, 28, 2, 2)
        points = [QPoint(16, 18), QPoint(16, 46), QPoint(42, 32)]
        painter.drawPolygon(QPolygon(points))

    painter.end()
    return QIcon(pixmap)
