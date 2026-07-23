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
try:
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    # Fallback si le backend multimedia n'est pas disponible (ex: Mac sans dylibs)
    QVideoWidget = None

# === FILTRE FICHIERS MEDIA ===
MEDIA_EXTENSIONS_FILTER = "Medias (*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma *.aiff *.mp4 *.mov *.avi *.mkv *.wmv *.flv *.webm *.m4v *.mpg *.mpeg *.png *.jpg *.jpeg *.gif *.bmp *.svg *.webp *.tiff)"

# === CONFIGURATION GLOBALE ===
APP_NAME = "MyStrow"
VERSION = "3.1.71"

# === FIREBASE (clé publique Web — identique à compte.html) ===
FIREBASE_API_KEY    = "AIzaSyAQjGJXGCSWzOE-wvKXh6sbZy6JDhL8tqA"
FIREBASE_PROJECT_ID = "mystrow-907be"

# === BREVO (email marketing + transactionnel) ===
# Récupérer la clé API dans Brevo > SMTP & API > API Keys
BREVO_API_KEY      = ""  # Clé stockée dans brevo_config.py (ignoré par git)
BREVO_SENDER_EMAIL = "hello@mystrow.io"  # Domaine à vérifier dans Brevo
BREVO_SENDER_NAME  = "MyStrow"
BREVO_LIST_ID      = 3                  # ID de la liste newsletter (entier, 0 = sans liste)
try:
    # Surcharge locale optionnelle (dev only) — ignorée si la clé est vide
    import firebase_config as _fc
    if getattr(_fc, "FIREBASE_API_KEY", ""):
        FIREBASE_API_KEY = _fc.FIREBASE_API_KEY
    if getattr(_fc, "FIREBASE_PROJECT_ID", ""):
        FIREBASE_PROJECT_ID = _fc.FIREBASE_PROJECT_ID
except ImportError:
    pass
try:
    import brevo_config as _bc
    if getattr(_bc, "BREVO_API_KEY", ""):
        BREVO_API_KEY = _bc.BREVO_API_KEY
except ImportError:
    pass

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
    """Formate un temps en ms : MM:SS, ou H:MM:SS au-delà d'une heure."""
    if ms <= 0:
        return "00:00"
    s = ms // 1000
    h = s // 3600
    if h > 0:
        return f"{h}:{(s % 3600) // 60:02d}:{s % 60:02d}"
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
    elif icon_type == "tap":
        # Cercle plein centré — représente un tap/impulsion
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(16, 16, 32, 32)
    elif icon_type == "to_start":
        # |◀  aller au début
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(14, 16, 5, 32, 2, 2)
        points = [QPoint(48, 16), QPoint(48, 48), QPoint(21, 32)]
        painter.drawPolygon(QPolygon(points))
    elif icon_type == "to_end":
        # ▶|  aller à la fin
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        points = [QPoint(16, 16), QPoint(16, 48), QPoint(43, 32)]
        painter.drawPolygon(QPolygon(points))
        painter.drawRoundedRect(45, 16, 5, 32, 2, 2)

    painter.end()
    return QIcon(pixmap)


# ─── Répartition des effets entre fixtures ────────────────────────────────────
# Partagé par le moteur (main_window) et l'éditeur d'effets : une seule source
# de vérité, sinon les deux divergeraient et l'aperçu mentirait sur le rendu.

SPREAD_MODES = [
    ("lineaire",    "Linéaire",         "1, 2, 3, 4… — chenillard classique"),
    ("miroir",      "Miroir (centre)",  "Part du centre vers les extrémités"),
    ("miroir_in",   "Miroir (bords)",   "1&8, puis 2&7, puis 3&6 — paires symétriques"),
    ("pair_impair", "Pair / impair",    "Une fixture sur deux, en alternance"),
    ("aleatoire",   "Aléatoire",        "Ordre dispersé, mais reproductible"),
]


def spread_rank(i, n, mode="lineaire"):
    """
    Rang normalisé (0..1) d'une fixture pour la répartition d'un effet.

    C'est ce rang que le « Décalage » transforme en déphasage. En linéaire il
    suit l'ordre de patch (1, 2, 3…), d'où le chenillard classique. Les autres
    modes rendent le même rang à plusieurs fixtures, qui s'allument alors
    ensemble — « miroir (bords) » donne 1&8, puis 2&7, puis 3&6.

    Vaut pour des projecteurs classiques comme pour les pixels d'une barre :
    un pixel est une fixture parmi les autres.
    """
    n = max(1, int(n))
    if n == 1:
        return 0.0
    # Distance au centre, 0 au milieu → 1 aux extrémités.
    # Rang le plus BAS = fixture qui passe en premier.
    dist = abs(i - (n - 1) / 2.0) / ((n - 1) / 2.0)
    if mode == "miroir":
        return dist            # centre d'abord, puis vers les bords
    if mode == "miroir_in":
        return 1.0 - dist      # bords d'abord : 1&8, puis 2&7, puis 3&6
    if mode == "pair_impair":
        return 0.0 if i % 2 == 0 else 0.5
    if mode == "aleatoire":
        # Déterministe : un show rejoué doit donner exactement la même figure.
        # Mélange type Knuth : un simple i*K % M reste monotone sur de petits
        # index et ne disperserait rien du tout.
        h = (i + 1) * 2654435761 % 4294967296
        h ^= h >> 13
        h = (h * 1274126177) % 4294967296
        h ^= h >> 16
        return (h % 10000) / 10000.0
    return i / n


# ─── Libellés courts de canaux ────────────────────────────────────────────────
# Le TYPE stocké reste inchangé (« Ambre ») : seul l'affichage est raccourci,
# pour tenir dans les pastilles et les blocs de profil.
CH_SHORT = {
    "Ambre": "A",
}


def channel_label(ch):
    """Libellé d'affichage d'un type de canal."""
    return CH_SHORT.get(ch, ch)
