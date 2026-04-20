"""
Composants de timeline lumiere : LightClip, ColorPalette, LightTrack
Version complete avec toutes les fonctionnalites:
- Bicolores draggables
- Anti-collision (pas de chevauchement)
- Fades etirables
- Forme d'onde audio style Virtual DJ PRO
- Curseur rouge sur toutes les pistes
- Mode cut (coupe ou on clique)
- Selection multiple multi-pistes avec drag groupe
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMenu, QComboBox, QDialog, QMessageBox, QInputDialog, QSlider, QApplication,
    QGridLayout, QCheckBox, QTabWidget, QSpinBox, QFrame, QSizePolicy, QToolTip,
    QLineEdit, QWidgetAction, QScrollArea
)
from PySide6.QtCore import Qt, QPoint, QSize, QRect, QMimeData, QTimer

from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QPolygon, QCursor,
    QPixmap, QIcon, QLinearGradient, QDrag, QPainterPath, QFont, QFontMetrics
)

import wave
import array
import random
import math
import struct
import time
from pathlib import Path

from i18n import tr

# Map FR colour name → i18n key (used for both ColorPalette and PalettePanel)
_COLOR_KEYS = {
    "Rouge":          "color_rouge",
    "Rouge vif":      "color_rouge_vif",
    "Orange":         "color_orange",
    "Jaune":          "color_jaune",
    "Lime":           "color_lime",
    "Vert":           "color_vert",
    "Turquoise":      "color_turquoise",
    "Cyan":           "color_cyan",
    "Bleu ciel":      "color_bleu_ciel",
    "Bleu":           "color_bleu",
    "Bleu marine":    "color_bleu_marine",
    "Violet":         "color_violet",
    "Indigo":         "color_indigo",
    "Magenta":        "color_magenta",
    "Rose":           "color_rose",
    "Blanc":          "color_blanc",
    "Blanc chaud":    "color_blanc_chaud",
    "Ambre":          "color_ambre",
    "Black Light":    "color_black_light",
}

def _cn(name_fr: str) -> str:
    """Return *name_fr* translated to the current language."""
    key = _COLOR_KEYS.get(name_fr)
    return tr(key) if key else name_fr

def _bicolor_name(a: str, b: str) -> str:
    return f"{_cn(a)} + {_cn(b)}"

try:
    import miniaudio
    HAS_MINIAUDIO = True
except ImportError:
    HAS_MINIAUDIO = False

try:
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
    from PySide6.QtCore import QUrl, QCoreApplication, QEventLoop
    HAS_QAUDIO_DECODER = True
except ImportError:
    HAS_QAUDIO_DECODER = False


# Cache pour BUILTIN_EFFECTS — évite l'import répété dans le paintEvent
_builtin_effects_cache = None

def _get_builtin_effects():
    global _builtin_effects_cache
    if _builtin_effects_cache is None:
        try:
            from effect_editor import BUILTIN_EFFECTS
            _builtin_effects_cache = BUILTIN_EFFECTS
        except Exception:
            _builtin_effects_cache = []
    return _builtin_effects_cache


class LightClip:
    """Un clip de lumiere sur la timeline avec effets et bicolore"""

    def __init__(self, start_time, duration, color, intensity, parent_track):
        self.start_time = start_time  # ms
        self.duration = duration  # ms
        self.color = color  # QColor
        self.color2 = None  # QColor pour bicolore
        self.intensity = intensity  # 0-100
        self.parent_track = parent_track

        # Effets (ancien système)
        self.effect = None
        self.effect_speed = 50
        # Nouveau système : couches d'effets structurées (list[dict])
        self.effect_layers    = []
        self.effect_play_mode = "loop"   # "loop" | "once"
        self.effect_duration  = 0        # secondes (0 = pas de minuteur)
        self.effect_name        = ""       # nom du preset sélectionné dans l'éditeur
        self.effect_target_groups = []  # [] = Tous, sinon liste de lettres ex: ["A","C","F"]

        # Fades
        self.fade_in_duration = 0
        self.fade_out_duration = 0

        # Mouvement Pan/Tilt (Moving Head uniquement)
        self.pan_start    = 128   # 0-255
        self.tilt_start   = 128
        self.pan_end      = 128
        self.tilt_end     = 128
        self.move_effect  = None  # None | "cercle" | "figure8" | "balayage_h" | "balayage_v" | "aleatoire"
        self.move_speed   = 0.5   # Hz
        self.move_amplitude = 60

        # Position stockee pour interactions souris
        self.x_pos = 0
        self.width_val = 0

        # Clip de séquence (mémoire AKAI)
        self.memory_ref = None    # (mem_col, row) ou None
        self.memory_label = ""    # ex: "A1", "B3"


class _ColorSwatch(QPushButton):
    """Bouton couleur avec rendu premium — gradient + shine."""

    S = 46   # taille en px

    def __init__(self, color1, color2=None, label="", parent=None):
        super().__init__(parent)
        self.c1 = color1
        self.c2 = color2   # None = couleur simple, sinon bicolore
        self.setFixedSize(self.S, self.S)
        self.setToolTip(label)
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self._hovered = False
        self.setStyleSheet("QPushButton { border: none; background: transparent; padding: 0px; }")

    def enterEvent(self, e):
        self._hovered = True;  self.update()

    def leaveEvent(self, e):
        self._hovered = False; self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        S = self.S
        r = 9    # rayon coins

        path = QPainterPath()
        path.addRoundedRect(0, 0, S, S, r, r)
        p.setClipPath(path)

        # Fond (couleur ou bicolore)
        if self.c2:
            p.fillRect(0, 0, S // 2, S, self.c1)
            p.fillRect(S // 2, 0, S - S // 2, S, self.c2)
            # Ligne séparatrice subtile
            p.setPen(QPen(QColor(0, 0, 0, 80), 1))
            p.drawLine(S // 2, 0, S // 2, S)
        else:
            p.fillRect(0, 0, S, S, self.c1)

        # Dégradé brillance (haut → bas)
        grad = QLinearGradient(0.0, 0.0, 0.0, float(S))
        grad.setColorAt(0.0,  QColor(255, 255, 255, 70))
        grad.setColorAt(0.45, QColor(255, 255, 255, 0))
        grad.setColorAt(1.0,  QColor(0,   0,   0,  55))
        p.fillRect(0, 0, S, S, QBrush(grad))

        # Shine coin haut-gauche
        shine = QLinearGradient(0.0, 0.0, float(S) * 0.65, float(S) * 0.45)
        shine.setColorAt(0.0, QColor(255, 255, 255, 80))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, int(S * 0.7), int(S * 0.5), QBrush(shine))

        # Bord intérieur
        p.setClipRect(self.rect())
        if self._hovered:
            p.setPen(QPen(QColor(255, 255, 255, 220), 2))
        else:
            p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(1, 1, S - 2, S - 2, r - 1, r - 1)

        # Glow hover (halo extérieur)
        if self._hovered:
            glow_c = QColor(self.c1)
            glow_c.setAlpha(120)
            p.setPen(QPen(glow_c, 3))
            p.drawRoundedRect(0, 0, S, S, r, r)

        p.end()


class ColorPalette(QWidget):
    """Palette de couleurs draggable — flow layout auto-wrap selon la largeur fenetre."""

    _SPACING = 5
    _MARGIN  = 6

    def __init__(self, parent_editor):
        super().__init__()
        self.parent_editor = parent_editor
        self.setStyleSheet("background: #111111; border-top: 1px solid #252525;")

        # ── Couleurs simples ─────────────────────────────────────────
        self.colors = [
            (_cn("Rouge"),         QColor(255,  45,  45)),
            (_cn("Rouge vif"),     QColor(255,   0,   0)),
            (_cn("Orange"),        QColor(255, 140,  20)),
            (_cn("Jaune"),         QColor(255, 230,   0)),
            (_cn("Lime"),          QColor(140, 255,   0)),
            (_cn("Vert"),          QColor( 30, 210,  60)),
            (_cn("Turquoise"),     QColor(  0, 200, 140)),
            (_cn("Cyan"),          QColor(  0, 220, 255)),
            (_cn("Bleu ciel"),     QColor( 80, 170, 255)),
            (_cn("Bleu"),          QColor( 50, 110, 255)),
            (_cn("Bleu marine"),   QColor( 20,  50, 200)),
            (_cn("Violet"),        QColor(160,  30, 255)),
            (_cn("Indigo"),        QColor( 90,   0, 200)),
            (_cn("Magenta"),       QColor(255,  20, 210)),
            (_cn("Rose"),          QColor(255,  80, 160)),
            (_cn("Blanc"),         QColor(255, 255, 255)),
            (_cn("Blanc chaud"),   QColor(255, 220, 160)),
            (_cn("Ambre"),         QColor(255, 180,  30)),
            (_cn("Black Light"),   QColor(100,   0, 255)),
        ]

        # ── Bicolores ────────────────────────────────────────────────
        self.bicolors = [
            (_bicolor_name("Rouge","Bleu"),         QColor(255,  45,  45), QColor( 50, 110, 255)),
            (_bicolor_name("Rouge","Cyan"),         QColor(255,  45,  45), QColor(  0, 220, 255)),
            (_bicolor_name("Rouge","Violet"),       QColor(255,  45,  45), QColor(160,  30, 255)),
            (_bicolor_name("Rouge","Orange"),       QColor(255,  45,  45), QColor(255, 140,  20)),
            (_bicolor_name("Rouge","Rose"),         QColor(255,  45,  45), QColor(255,  80, 160)),
            (_bicolor_name("Rouge","Blanc"),        QColor(255,  45,  45), QColor(255, 255, 255)),
            (_bicolor_name("Orange","Bleu"),        QColor(255, 140,  20), QColor( 50, 110, 255)),
            (_bicolor_name("Orange","Violet"),      QColor(255, 140,  20), QColor(160,  30, 255)),
            (_bicolor_name("Jaune","Violet"),       QColor(255, 230,   0), QColor(160,  30, 255)),
            (_bicolor_name("Jaune","Bleu"),         QColor(255, 230,   0), QColor( 50, 110, 255)),
            (_bicolor_name("Vert","Rouge"),         QColor( 30, 210,  60), QColor(255,  45,  45)),
            (_bicolor_name("Vert","Jaune"),         QColor( 30, 210,  60), QColor(255, 230,   0)),
            (_bicolor_name("Vert","Violet"),        QColor( 30, 210,  60), QColor(160,  30, 255)),
            (_bicolor_name("Vert","Orange"),        QColor( 30, 210,  60), QColor(255, 140,  20)),
            (_bicolor_name("Cyan","Magenta"),       QColor(  0, 220, 255), QColor(255,  20, 210)),
            (_bicolor_name("Cyan","Rouge"),         QColor(  0, 220, 255), QColor(255,  45,  45)),
            (_bicolor_name("Cyan","Violet"),        QColor(  0, 220, 255), QColor(160,  30, 255)),
            (_bicolor_name("Bleu","Violet"),        QColor( 50, 110, 255), QColor(160,  30, 255)),
            (_bicolor_name("Bleu","Cyan"),          QColor( 50, 110, 255), QColor(  0, 220, 255)),
            (_bicolor_name("Bleu","Rose"),          QColor( 50, 110, 255), QColor(255,  80, 160)),
            (_bicolor_name("Violet","Rose"),        QColor(160,  30, 255), QColor(255,  80, 160)),
            (_bicolor_name("Magenta","Jaune"),      QColor(255,  20, 210), QColor(255, 230,   0)),
            (_bicolor_name("Magenta","Cyan"),       QColor(255,  20, 210), QColor(  0, 220, 255)),
            (_bicolor_name("Rose","Blanc"),         QColor(255,  80, 160), QColor(255, 255, 255)),
            (_bicolor_name("Blanc","Bleu"),         QColor(255, 255, 255), QColor( 50, 110, 255)),
            (_bicolor_name("Blanc chaud","Bleu"),   QColor(255, 220, 160), QColor( 50, 110, 255)),
        ]

        # ── Creer toutes les swatches comme enfants directs ──────────
        self._swatches = []      # swatches simples
        self._bi_swatches = []   # swatches bicolores
        # index de la 1ere swatch bicolore dans la liste complete
        self._bicolor_start = len(self.colors)

        for name, color in self.colors:
            btn = _ColorSwatch(color, label=name)
            btn.setParent(self)
            btn.mousePressEvent = lambda e, c=color: self.start_drag(e, c)
            self._swatches.append(btn)

        for name, col1, col2 in self.bicolors:
            btn = _ColorSwatch(col1, col2, label=name)
            btn.setParent(self)
            btn.mousePressEvent = lambda e, c1=col1, c2=col2: self.start_bicolor_drag(e, c1, c2)
            self._bi_swatches.append(btn)

        self._all_swatches = self._swatches + self._bi_swatches
        self._update_height(1)  # hauteur initiale = 1 ligne

    # ── Layout flow ──────────────────────────────────────────────────

    def _update_height(self, n_rows):
        S    = _ColorSwatch.S
        step = S + self._SPACING
        h    = self._MARGIN * 2 + n_rows * step - self._SPACING
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)
        self.updateGeometry()  # notifie le parent layout du changement de taille

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout()

    def _relayout(self):
        S      = _ColorSwatch.S
        step   = S + self._SPACING
        m      = self._MARGIN
        avail  = max(step, self.width() - 2 * m)
        cols   = max(1, avail // step)

        col = row = 0
        for i, btn in enumerate(self._all_swatches):
            # Petit gap visuel entre simples et bicolores quand ils sont sur la meme ligne
            if i == self._bicolor_start and col > 0:
                col += 1  # un espace vide de separation
                if col >= cols:
                    col = 0; row += 1

            x = m + col * step
            y = m + row * step
            btn.move(x, y)
            btn.show()
            col += 1
            if col >= cols:
                col = 0; row += 1

        n_rows = row + (1 if col > 0 else 0)
        self._update_height(max(1, n_rows))

    def start_drag(self, event, color):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(color.name())
        drag.setMimeData(mime)
        pix = QPixmap(46, 46)
        pix.fill(color)
        drag.setPixmap(pix)
        drag.exec(Qt.CopyAction)

    def start_bicolor_drag(self, event, color1, color2):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(f"{color1.name()}#{color2.name()}")
        drag.setMimeData(mime)
        pix = QPixmap(46, 46)
        p = QPainter(pix)
        p.fillRect(0, 0, 23, 46, color1)
        p.fillRect(23, 0, 23, 46, color2)
        p.end()
        drag.setPixmap(pix)
        drag.exec(Qt.CopyAction)


class MemoryDragButton(QPushButton):
    """Bouton draggable représentant une mémoire AKAI enregistrée."""

    def __init__(self, label, color, mem_col, row, parent=None):
        super().__init__(label, parent)
        self.mem_col = mem_col
        self.mem_row = row
        self.mem_color = color
        self.setFixedSize(50, 46)
        lum = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
        txt = "#000" if lum > 140 else "#fff"
        bg = color.name()
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {txt};
                border: 2px solid #333;
                border-radius: 5px;
                font-size: 9px;
                font-weight: bold;
            }}
            QPushButton:hover {{ border-color: #00d4ff; border-width: 2px; }}
        """)
        self.setToolTip(tr("lt_sequence_tooltip", label=label))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            drag = QDrag(self)
            mime = QMimeData()
            data = f"{self.mem_col},{self.mem_row},{self.text()},{self.mem_color.name()}"
            mime.setData('application/x-sequence', data.encode())
            drag.setMimeData(mime)
            pix = QPixmap(50, 46)
            pix.fill(self.mem_color)
            p = QPainter(pix)
            lum = self.mem_color.red() * 0.299 + self.mem_color.green() * 0.587 + self.mem_color.blue() * 0.114
            p.setPen(QColor("#000" if lum > 140 else "#fff"))
            p.drawText(pix.rect(), Qt.AlignCenter, self.text())
            p.end()
            drag.setPixmap(pix)
            drag.setHotSpot(QPoint(25, 23))
            drag.exec(Qt.CopyAction)


class _EffectChip(QWidget):
    """Chip draggable représentant un effet — pour la ligne Effets de la palette."""

    H = 46

    def __init__(self, eff_dict, parent=None):
        super().__init__(parent)
        self._eff = eff_dict
        name  = eff_dict.get("name", "")
        emoji = eff_dict.get("emoji", "✨")
        self._label = f"{emoji}  {name}"
        self.setFixedHeight(self.H)
        fm = QFontMetrics(QFont())
        w  = max(80, fm.horizontalAdvance(self._label) + 28)
        self.setFixedWidth(w)
        self.setToolTip(name)
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self._hovered = False

    def enterEvent(self, e):  self._hovered = True;  self.update()
    def leaveEvent(self, e):  self._hovered = False; self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.H
        r = 7
        path = QPainterPath()
        path.addRoundedRect(0, 0, W, H, r, r)
        bg = QColor("#3a1060") if self._hovered else QColor("#22083a")
        p.fillPath(path, QBrush(bg))
        # Accent line top
        p.setPen(QPen(QColor("#cc44ff"), 2))
        p.drawLine(r, 1, W - r, 1)
        # Text
        p.setPen(QColor("#d09aff"))
        f = p.font(); f.setPixelSize(11); f.setBold(True); p.setFont(f)
        p.drawText(QRect(0, 0, W, H), Qt.AlignCenter, self._label)
        # Border
        border = QColor("#aa33ee") if self._hovered else QColor("#3d1266")
        p.setPen(QPen(border, 1)); p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            import json as _json
            drag = QDrag(self)
            mime = QMimeData()
            data = {
                "name":   self._eff.get("name", ""),
                "type":   self._eff.get("type", ""),
                "layers": self._eff.get("layers", []),
            }
            mime.setData('application/x-effect', _json.dumps(data).encode())
            drag.setMimeData(mime)
            pix = QPixmap(self.width(), self.H)
            pix.fill(QColor("#22083a"))
            drag.setPixmap(pix)
            drag.setHotSpot(QPoint(self.width() // 2, self.H // 2))
            drag.exec(Qt.CopyAction)


# ══════════════════════════════════════════════════════════════════════════════
#  LIBRARY PANEL  —  panneau bibliothèque latéral (nouveau layout éditeur)
# ══════════════════════════════════════════════════════════════════════════════

class _LibraryItem(QWidget):
    """Ligne draggable de base dans la bibliothèque. Supporte la sélection multiple."""
    H  = 28
    SW = 14   # taille swatch

    def __init__(self, name, panel=None, parent=None):
        super().__init__(parent)
        self._name     = name
        self._panel    = panel
        self._selected = False
        self._hovered  = False
        self.setFixedHeight(self.H)
        self.setCursor(QCursor(Qt.OpenHandCursor))

        if panel:
            panel._register(self)

        h = QHBoxLayout(self)
        h.setContentsMargins(22, 0, 10, 0)
        h.setSpacing(8)

        self._sw = QWidget()
        self._sw.setFixedSize(self.SW, self.SW)
        self._sw.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._sw.paintEvent = self._swatch_paint
        h.addWidget(self._sw)

        lbl = QLabel(name)
        lbl.setStyleSheet(
            "color: #999; font-size: 11px; background: transparent; border: none;"
        )
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(lbl, 1)

    # ── Swatch (override) ────────────────────────────────────────────────────

    def _swatch_paint(self, event):
        pass

    # ── Visuel ───────────────────────────────────────────────────────────────

    def enterEvent(self, e):
        self._hovered = True;  self.update()

    def leaveEvent(self, e):
        self._hovered = False; self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if self._selected:
            p.fillRect(self.rect(), QColor(0, 212, 255, 40))
            p.setPen(QPen(QColor(0, 212, 255, 160), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        elif self._hovered:
            p.fillRect(self.rect(), QColor(255, 255, 255, 12))
        p.end()

    # ── Sélection + Drag ─────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            if self._panel:
                ctrl = bool(event.modifiers() & Qt.ControlModifier)
                self._panel._toggle_selection(self, ctrl)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            # Multi-drag si plusieurs items sélectionnés et cet item en fait partie
            if (self._panel
                    and len(self._panel._selection) > 1
                    and self in self._panel._selection):
                self._panel._do_multi_drag(self)
            else:
                self._do_single_drag()
        super().mouseMoveEvent(event)

    def _do_single_drag(self):
        pass  # override dans sous-classes


class _LibraryColorItem(_LibraryItem):
    def __init__(self, name, color, panel=None, parent=None):
        self._color = color
        super().__init__(name, panel, parent)

    def _swatch_paint(self, event):
        p = QPainter(self._sw)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.SW, self.SW, 3, 3)
        p.fillPath(path, QBrush(self._color))
        p.end()

    def _do_single_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self._color.name())
        drag.setMimeData(mime)
        pix = QPixmap(46, 46); pix.fill(self._color)
        drag.setPixmap(pix); drag.setHotSpot(QPoint(23, 23))
        drag.exec(Qt.CopyAction)


class _LibraryBicolorItem(_LibraryItem):
    def __init__(self, name, c1, c2, panel=None, parent=None):
        self._c1 = c1
        self._c2 = c2
        super().__init__(name, panel, parent)

    def _swatch_paint(self, event):
        p = QPainter(self._sw)
        S = self.SW
        path = QPainterPath()
        path.addRoundedRect(0, 0, S, S, 3, 3)
        p.setClipPath(path)
        p.fillRect(0, 0, S // 2, S, self._c1)
        p.fillRect(S // 2, 0, S - S // 2, S, self._c2)
        p.end()

    def _do_single_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(f"{self._c1.name()}#{self._c2.name()}")
        drag.setMimeData(mime)
        pix = QPixmap(46, 46)
        p = QPainter(pix)
        p.fillRect(0, 0, 23, 46, self._c1)
        p.fillRect(23, 0, 23, 46, self._c2)
        p.end()
        drag.setPixmap(pix); drag.setHotSpot(QPoint(23, 23))
        drag.exec(Qt.CopyAction)


class _LibraryMemItem(_LibraryItem):
    def __init__(self, label, color, mem_col, row, panel=None, parent=None):
        self._mem_color = color
        self._mem_col   = mem_col
        self._mem_row   = row
        super().__init__(label, panel, parent)

    def _swatch_paint(self, event):
        p = QPainter(self._sw)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.SW, self.SW, 3, 3)
        p.fillPath(path, QBrush(self._mem_color))
        p.end()

    def _do_single_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        data = f"{self._mem_col},{self._mem_row},{self._name},{self._mem_color.name()}"
        mime.setData('application/x-sequence', data.encode())
        drag.setMimeData(mime)
        pix = QPixmap(50, 46); pix.fill(self._mem_color)
        p = QPainter(pix)
        lum = (self._mem_color.red()   * 0.299
             + self._mem_color.green() * 0.587
             + self._mem_color.blue()  * 0.114)
        p.setPen(QColor("#000" if lum > 140 else "#fff"))
        p.drawText(pix.rect(), Qt.AlignCenter, self._name)
        p.end()
        drag.setPixmap(pix); drag.setHotSpot(QPoint(25, 23))
        drag.exec(Qt.CopyAction)


class _LibraryEffectItem(_LibraryItem):
    def __init__(self, eff_dict, panel=None, parent=None):
        self._eff = eff_dict
        emoji = eff_dict.get("emoji", "✨")
        name  = eff_dict.get("name", "")
        super().__init__(f"{emoji}  {name}", panel, parent)

    def _swatch_paint(self, event):
        p = QPainter(self._sw)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.SW, self.SW, 3, 3)
        p.fillPath(path, QBrush(QColor("#22083a")))
        p.end()

    def _do_single_drag(self):
        import json as _json
        drag = QDrag(self)
        mime = QMimeData()
        data = {
            "name":   self._eff.get("name",   ""),
            "type":   self._eff.get("type",   ""),
            "layers": self._eff.get("layers", []),
        }
        mime.setData('application/x-effect', _json.dumps(data).encode())
        drag.setMimeData(mime)
        pix = QPixmap(80, 46); pix.fill(QColor("#22083a"))
        drag.setPixmap(pix); drag.setHotSpot(QPoint(40, 23))
        drag.exec(Qt.CopyAction)


class _LibrarySection(QWidget):
    """Section repliable dans la bibliothèque (▼/▶ + liste d'items)."""

    _HDR_SS = (
        "QPushButton { background: #141414; color: #555; font-size: 8px; font-weight: bold; "
        "letter-spacing: 1px; text-align: left; border: none; "
        "border-bottom: 1px solid #1c1c1c; padding: 6px 10px; } "
        "QPushButton:hover { color: #bbb; background: #1a1a1a; }"
    )

    def __init__(self, title, parent_layout):
        super().__init__()
        self.setStyleSheet("background: #0f0f0f;")
        self._title_text = title
        self._expanded   = True

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._hdr = QPushButton(f"▼  {title}")
        self._hdr.setStyleSheet(self._HDR_SS)
        self._hdr.clicked.connect(self._toggle)
        v.addWidget(self._hdr)

        self._body = QWidget()
        self._body.setStyleSheet("background: transparent;")
        self._bv = QVBoxLayout(self._body)
        self._bv.setContentsMargins(0, 0, 0, 0)
        self._bv.setSpacing(0)
        v.addWidget(self._body)

        parent_layout.addWidget(self)

    def add_item(self, widget):
        self._bv.addWidget(widget)

    def clear_items(self):
        """Vide la section et retourne les widgets retirés."""
        removed = []
        while self._bv.count():
            item = self._bv.takeAt(0)
            w = item.widget()
            if w:
                removed.append(w)
                w.deleteLater()
        return removed

    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        arrow = "▼" if self._expanded else "▶"
        self._hdr.setText(f"{arrow}  {self._title_text}")


class LibraryPanel(QScrollArea):
    """Panneau bibliothèque à droite : COULEUR / BICOULEUR / MÉMOIRE / EFFETS.
    Supporte la sélection multiple (Ctrl+clic) et le drag multi-items."""

    def __init__(self, parent_editor):
        super().__init__()
        self.parent_editor = parent_editor
        self._selection: set  = set()   # items actuellement sélectionnés
        self._all_items: list = []      # tous les _LibraryItem enregistrés

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(190)
        self.setMaximumWidth(280)
        self.setStyleSheet(
            "QScrollArea { background: #0f0f0f; border: none; border-right: 1px solid #1c1c1c; }"
            "QScrollBar:vertical { background: #0a0a0a; width: 6px; margin: 0; }"
            "QScrollBar::handle:vertical { background: #252525; border-radius: 3px; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        content = QWidget()
        content.setStyleSheet("background: #0f0f0f;")
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Titre + compteur sélection
        hdr_row = QWidget(); hdr_row.setStyleSheet("background: #0a0a0a;")
        hdr_h = QHBoxLayout(hdr_row); hdr_h.setContentsMargins(0, 0, 0, 0)
        title = QLabel("  BIBLIOTHÈQUE")
        title.setFixedHeight(24)
        title.setStyleSheet(
            "color: #383838; font-size: 8px; font-weight: bold; letter-spacing: 2px; "
            "background: transparent; border-bottom: 1px solid #161616;"
        )
        hdr_h.addWidget(title, 1)
        self._sel_lbl = QLabel("")
        self._sel_lbl.setFixedHeight(24)
        self._sel_lbl.setStyleSheet(
            "color: #00d4ff; font-size: 9px; font-weight: bold; "
            "background: transparent; border-bottom: 1px solid #161616; padding-right: 8px;"
        )
        self._sel_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hdr_h.addWidget(self._sel_lbl)
        v.addWidget(hdr_row)

        self._sec_color      = _LibrarySection("COULEUR", v)
        self._sec_bi         = _LibrarySection("BICOULEUR", v)
        self._sec_mem        = _LibrarySection("MÉMOIRE", v)
        self._sec_eff        = _LibrarySection("EFFETS", v)
        self._sec_custom_eff = _LibrarySection("MES EFFETS", v)

        v.addStretch()
        self.setWidget(content)

        self._populate_static()
        self.refresh()

    # ── Gestion du registre d'items ───────────────────────────────────────────

    def _register(self, item):
        self._all_items.append(item)

    def _deregister_list(self, items):
        for w in items:
            if w in self._all_items:
                self._all_items.remove(w)
            self._selection.discard(w)

    # ── Sélection ─────────────────────────────────────────────────────────────

    def _toggle_selection(self, item, ctrl: bool):
        if ctrl:
            # Ctrl+clic : ajouter/retirer de la sélection
            if item in self._selection:
                self._selection.discard(item)
                item._selected = False
                item.update()
            else:
                self._selection.add(item)
                item._selected = True
                item.update()
        else:
            # Clic simple : désélectionner tout, sélectionner cet item
            for other in list(self._selection):
                other._selected = False
                other.update()
            self._selection.clear()
            self._selection.add(item)
            item._selected = True
            item.update()

        # Mettre à jour le compteur dans le titre
        n = len(self._selection)
        self._sel_lbl.setText(f"{n} sélect." if n > 1 else "")

    def _clear_selection(self):
        for item in list(self._selection):
            item._selected = False
            item.update()
        self._selection.clear()
        self._sel_lbl.setText("")

    # ── Drag multi-items ──────────────────────────────────────────────────────

    def _do_multi_drag(self, source):
        import json as _json

        items_data = []
        types_set  = set()

        for item in self._selection:
            if isinstance(item, _LibraryColorItem):
                items_data.append({"type": "color",   "value": item._color.name()})
                types_set.add("color")
            elif isinstance(item, _LibraryBicolorItem):
                items_data.append({"type": "bicolor",
                                   "value": f"{item._c1.name()}#{item._c2.name()}"})
                types_set.add("bicolor")
            elif isinstance(item, _LibraryMemItem):
                items_data.append({"type": "memory",
                                   "value": f"{item._mem_col},{item._mem_row},"
                                            f"{item._name},{item._mem_color.name()}"})
                types_set.add("memory")
            elif isinstance(item, _LibraryEffectItem):
                items_data.append({"type": "effect",
                                   "value": _json.dumps({
                                       "name":   item._eff.get("name",   ""),
                                       "type":   item._eff.get("type",   ""),
                                       "layers": item._eff.get("layers", []),
                                   })})
                types_set.add("effect")

        if not items_data:
            return

        drag = QDrag(source)
        mime = QMimeData()
        mime.setData('application/x-multi-library',       _json.dumps(items_data).encode())
        mime.setData('application/x-multi-library-types', ",".join(types_set).encode())
        drag.setMimeData(mime)

        # Pixmap : badge avec nombre d'items
        n   = len(items_data)
        pix = QPixmap(64, 28)
        pix.fill(QColor("#0d0d0d"))
        p = QPainter(pix)
        p.setPen(QPen(QColor("#00d4ff"), 1))
        p.drawRect(0, 0, 63, 27)
        p.setPen(QColor("#00d4ff"))
        f = p.font(); f.setBold(True); f.setPixelSize(11); p.setFont(f)
        p.drawText(pix.rect(), Qt.AlignCenter, f"× {n}")
        p.end()
        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(32, 14))
        drag.exec(Qt.CopyAction)

    # ── Remplissage ───────────────────────────────────────────────────────────

    def _populate_static(self):
        for name, c in PalettePanel.COLORS:
            self._sec_color.add_item(_LibraryColorItem(name, c, panel=self))
        for name, c1, c2 in PalettePanel.BICOLORS:
            self._sec_bi.add_item(_LibraryBicolorItem(name, c1, c2, panel=self))
        try:
            from effect_editor import BUILTIN_EFFECTS
            for eff in BUILTIN_EFFECTS:
                self._sec_eff.add_item(_LibraryEffectItem(eff, panel=self))
        except Exception:
            pass
        self._refresh_custom_effects()

    def _refresh_custom_effects(self):
        """Recharge les effets personnalisés dans la section MES EFFETS."""
        import json as _json
        removed = self._sec_custom_eff.clear_items()
        self._deregister_list(removed)

        custom_path = Path.home() / ".mystrow_custom_effects.json"
        custom_effects = []
        if custom_path.exists():
            try:
                with open(custom_path, "r", encoding="utf-8") as f:
                    custom_effects = _json.load(f)
            except Exception:
                custom_effects = []

        if custom_effects:
            for eff in custom_effects:
                item = _LibraryEffectItem(eff, panel=self)
                self._sec_custom_eff.add_item(item)
        else:
            empty = QLabel("  Aucun effet personnalisé")
            empty.setStyleSheet(
                "color: #2a2a2a; font-size: 10px; font-style: italic; "
                "background: transparent; padding: 5px 10px;"
            )
            self._sec_custom_eff.add_item(empty)

    def refresh(self):
        """Rafraîchit la section Mémoires et les effets personnalisés."""
        removed = self._sec_mem.clear_items()
        self._deregister_list(removed)

        mw       = getattr(self.parent_editor, 'main_window', None)
        memories = getattr(mw, 'memories', None) if mw else None
        count    = 0

        if memories:
            for mem_col, col_mems in enumerate(memories):
                for row_idx, mem in enumerate(col_mems):
                    if mem is None:
                        continue
                    color = PalettePanel._dominant_color(mem, mw, mem_col, row_idx)
                    label = f"MEM {mem_col + 1}.{row_idx + 1}"
                    self._sec_mem.add_item(
                        _LibraryMemItem(label, color, mem_col, row_idx, panel=self)
                    )
                    count += 1

        if count == 0:
            empty = QLabel("  Aucune mémoire")
            empty.setStyleSheet(
                "color: #2a2a2a; font-size: 10px; font-style: italic; "
                "background: transparent; padding: 5px 10px;"
            )
            self._sec_mem.add_item(empty)

        self._refresh_custom_effects()


# ══════════════════════════════════════════════════════════════════════════════
#  PALETTE PANEL  (conservé pour compatibilité — non affiché dans le nouveau layout)
# ══════════════════════════════════════════════════════════════════════════════

class PalettePanel(QWidget):
    """Palette 4 lignes : Couleurs / Bicoleurs / Mémoires / Effets — scrollables horizontalement."""

    _ROW_H   = 56
    _SCROLL_SS = """
        QScrollArea { background: transparent; border: none; }
        QScrollBar:horizontal {
            height: 4px; background: #181818; margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: #444; border-radius: 2px; min-width: 20px;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    """
    _LABEL_SS  = (
        "color: #606060; font-size: 7px; font-weight: bold; "
        "letter-spacing: 1px; background: transparent;"
    )

    COLORS = [
        (_cn("Rouge"),          QColor(255,  45,  45)),
        (_cn("Rouge vif"),      QColor(255,   0,   0)),
        (_cn("Orange"),         QColor(255, 140,  20)),
        (_cn("Jaune"),          QColor(255, 230,   0)),
        (_cn("Lime"),           QColor(140, 255,   0)),
        (_cn("Vert"),           QColor( 30, 210,  60)),
        (_cn("Turquoise"),      QColor(  0, 200, 140)),
        (_cn("Cyan"),           QColor(  0, 220, 255)),
        (_cn("Bleu ciel"),      QColor( 80, 170, 255)),
        (_cn("Bleu"),           QColor( 50, 110, 255)),
        (_cn("Bleu marine"),    QColor( 20,  50, 200)),
        (_cn("Violet"),         QColor(160,  30, 255)),
        (_cn("Indigo"),         QColor( 90,   0, 200)),
        (_cn("Magenta"),        QColor(255,  20, 210)),
        (_cn("Rose"),           QColor(255,  80, 160)),
        (_cn("Blanc"),          QColor(255, 255, 255)),
        (_cn("Blanc chaud"),    QColor(255, 220, 160)),
        (_cn("Ambre"),          QColor(255, 180,  30)),
        (_cn("Black Light"),    QColor(100,   0, 255)),
    ]

    BICOLORS = [
        (_bicolor_name("Rouge", "Bleu"),        QColor(255,  45,  45), QColor( 50, 110, 255)),
        (_bicolor_name("Rouge", "Cyan"),        QColor(255,  45,  45), QColor(  0, 220, 255)),
        (_bicolor_name("Rouge", "Violet"),      QColor(255,  45,  45), QColor(160,  30, 255)),
        (_bicolor_name("Rouge", "Orange"),      QColor(255,  45,  45), QColor(255, 140,  20)),
        (_bicolor_name("Rouge", "Rose"),        QColor(255,  45,  45), QColor(255,  80, 160)),
        (_bicolor_name("Rouge", "Blanc"),       QColor(255,  45,  45), QColor(255, 255, 255)),
        (_bicolor_name("Orange", "Bleu"),       QColor(255, 140,  20), QColor( 50, 110, 255)),
        (_bicolor_name("Orange", "Violet"),     QColor(255, 140,  20), QColor(160,  30, 255)),
        (_bicolor_name("Jaune", "Violet"),      QColor(255, 230,   0), QColor(160,  30, 255)),
        (_bicolor_name("Jaune", "Bleu"),        QColor(255, 230,   0), QColor( 50, 110, 255)),
        (_bicolor_name("Vert", "Rouge"),        QColor( 30, 210,  60), QColor(255,  45,  45)),
        (_bicolor_name("Vert", "Jaune"),        QColor( 30, 210,  60), QColor(255, 230,   0)),
        (_bicolor_name("Vert", "Violet"),       QColor( 30, 210,  60), QColor(160,  30, 255)),
        (_bicolor_name("Vert", "Orange"),       QColor( 30, 210,  60), QColor(255, 140,  20)),
        (_bicolor_name("Cyan", "Magenta"),      QColor(  0, 220, 255), QColor(255,  20, 210)),
        (_bicolor_name("Cyan", "Rouge"),        QColor(  0, 220, 255), QColor(255,  45,  45)),
        (_bicolor_name("Cyan", "Violet"),       QColor(  0, 220, 255), QColor(160,  30, 255)),
        (_bicolor_name("Bleu", "Violet"),       QColor( 50, 110, 255), QColor(160,  30, 255)),
        (_bicolor_name("Bleu", "Cyan"),         QColor( 50, 110, 255), QColor(  0, 220, 255)),
        (_bicolor_name("Bleu", "Rose"),         QColor( 50, 110, 255), QColor(255,  80, 160)),
        (_bicolor_name("Violet", "Rose"),       QColor(160,  30, 255), QColor(255,  80, 160)),
        (_bicolor_name("Magenta", "Jaune"),     QColor(255,  20, 210), QColor(255, 230,   0)),
        (_bicolor_name("Magenta", "Cyan"),      QColor(255,  20, 210), QColor(  0, 220, 255)),
        (_bicolor_name("Rose", "Blanc"),        QColor(255,  80, 160), QColor(255, 255, 255)),
        (_bicolor_name("Blanc", "Bleu"),        QColor(255, 255, 255), QColor( 50, 110, 255)),
        (_bicolor_name("Blanc chaud", "Bleu"),  QColor(255, 220, 160), QColor( 50, 110, 255)),
    ]

    def __init__(self, parent_editor):
        super().__init__()
        self.parent_editor = parent_editor
        self.setStyleSheet("background: #111111; border-top: 1px solid #252525;")

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── Couleurs ──────────────────────────────────────────────────────
        color_items = []
        for name, c in self.COLORS:
            sw = _ColorSwatch(c, label=name)
            sw.mousePressEvent = lambda e, col=c: self._drag_color(e, col)
            color_items.append(sw)
        v.addWidget(self._make_row(tr("lt_palette_colors"), color_items))
        v.addWidget(self._sep())

        # ── Bicoleurs ─────────────────────────────────────────────────────
        bi_items = []
        for name, c1, c2 in self.BICOLORS:
            sw = _ColorSwatch(c1, c2, label=name)
            sw.mousePressEvent = lambda e, a=c1, b=c2: self._drag_bicolor(e, a, b)
            bi_items.append(sw)
        v.addWidget(self._make_row(tr("lt_palette_bicolors"), bi_items))
        v.addWidget(self._sep())

        # ── Mémoires ─────────────────────────────────────────────────────
        mem_row_widget, self._mem_inner = self._make_row_dynamic(tr("lt_palette_memories"))
        v.addWidget(mem_row_widget)
        v.addWidget(self._sep())

        # ── Effets ───────────────────────────────────────────────────────
        eff_items = self._build_effect_chips()
        v.addWidget(self._make_row(tr("lt_palette_effects"), eff_items))

        self.refresh()

    # ── Helpers layout ────────────────────────────────────────────────────

    def _sep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #1e1e1e; border: none;")
        return sep

    def _make_scroll(self):
        sc = QScrollArea()
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidgetResizable(True)
        sc.setStyleSheet(self._SCROLL_SS)
        return sc

    def _make_row(self, label_text, widgets):
        row = QWidget()
        row.setFixedHeight(self._ROW_H)
        row.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(8, 5, 6, 5)
        hl.setSpacing(6)

        lbl = QLabel(label_text)
        lbl.setFixedWidth(62)
        lbl.setStyleSheet(self._LABEL_SS)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hl.addWidget(lbl)

        sc = self._make_scroll()
        cnt = QWidget(); cnt.setStyleSheet("background: transparent;")
        inner = QHBoxLayout(cnt)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)
        for w in widgets:
            inner.addWidget(w)
        inner.addStretch()
        sc.setWidget(cnt)
        hl.addWidget(sc, 1)
        return row

    def _make_row_dynamic(self, label_text):
        """Retourne (row_widget, inner_layout) pour remplissage dynamique."""
        row = QWidget()
        row.setFixedHeight(self._ROW_H)
        row.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(8, 5, 6, 5)
        hl.setSpacing(6)

        lbl = QLabel(label_text)
        lbl.setFixedWidth(62)
        lbl.setStyleSheet(self._LABEL_SS)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hl.addWidget(lbl)

        sc = self._make_scroll()
        cnt = QWidget(); cnt.setStyleSheet("background: transparent;")
        inner = QHBoxLayout(cnt)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)
        inner.addStretch()
        sc.setWidget(cnt)
        hl.addWidget(sc, 1)
        return row, inner

    # ── Drag couleurs ──────────────────────────────────────────────────────

    def _drag_color(self, event, color):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(color.name())
        drag.setMimeData(mime)
        pix = QPixmap(46, 46); pix.fill(color)
        drag.setPixmap(pix)
        drag.exec(Qt.CopyAction)

    def _drag_bicolor(self, event, c1, c2):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(f"{c1.name()}#{c2.name()}")
        drag.setMimeData(mime)
        pix = QPixmap(46, 46)
        p = QPainter(pix)
        p.fillRect(0, 0, 23, 46, c1)
        p.fillRect(23, 0, 23, 46, c2)
        p.end()
        drag.setPixmap(pix)
        drag.exec(Qt.CopyAction)

    # ── Effets ─────────────────────────────────────────────────────────────

    def _build_effect_chips(self):
        chips = []
        try:
            from effect_editor import BUILTIN_EFFECTS
            for eff in BUILTIN_EFFECTS:
                chips.append(_EffectChip(eff))
        except Exception:
            pass
        return chips

    # ── Mémoires ───────────────────────────────────────────────────────────

    def refresh(self):
        """Rafraîchit la ligne Mémoires."""
        inner = self._mem_inner
        while inner.count():
            item = inner.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        mw = getattr(self.parent_editor, 'main_window', None)
        memories = getattr(mw, 'memories', None) if mw else None
        count = 0

        if memories:
            for mem_col, col_mems in enumerate(memories):
                for row_idx, mem in enumerate(col_mems):
                    if mem is None:
                        continue
                    color = self._dominant_color(mem, mw, mem_col, row_idx)
                    label = f"MEM {mem_col + 1}.{row_idx + 1}"
                    btn = MemoryDragButton(label, color, mem_col, row_idx)
                    inner.addWidget(btn)
                    count += 1

        if count == 0:
            empty = QLabel(tr("lt_no_memory"))
            empty.setStyleSheet("color: #444; font-size: 10px; font-style: italic; background: transparent;")
            inner.addWidget(empty)

        inner.addStretch()

    @staticmethod
    def _dominant_color(mem, mw, mem_col, row):
        custom = getattr(mw, 'memory_custom_colors', None)
        if custom and custom[mem_col][row]:
            return QColor(custom[mem_col][row])
        counts = {}
        for ps in mem.get("projectors", []):
            if ps.get("level", 0) > 0:
                c = ps.get("base_color", "#000")
                counts[c] = counts.get(c, 0) + 1
        if counts:
            return QColor(max(counts, key=counts.get))
        return QColor("#444444")


class LightTrack(QWidget):
    """Une piste de lumiere (une ligne dans la timeline)"""

    def __init__(self, name, total_duration, parent_editor, color="#4488ff"):
        super().__init__()
        self.name = name
        self.total_duration = total_duration
        self.parent_editor = parent_editor
        self.track_color = QColor(color)
        self.clips = []
        self.pixels_per_ms = 0.05
        self.is_sequence_track = False   # piste dédiée aux clips de séquence AKAI
        self.is_effect_track   = False   # piste dédiée aux effets lumière

        self._collapsed = False
        self._normal_min_height = 100 if name == "Audio" else 60
        self.setMinimumHeight(self._normal_min_height)
        # Fixer la largeur minimale dès l'init pour que le scrollbar horizontal apparaisse
        self.setMinimumWidth(145 + int(self.total_duration * self.pixels_per_ms) + 50)
        self.setAcceptDrops(True)
        self.setStyleSheet("""
            QWidget {
                background: #0a0a0a;
                border-bottom: 1px solid #2a2a2a;
            }
        """)

        self.label = QLabel(name, self)
        self.label.setStyleSheet(f"""
            QLabel {{
                color: white;
                font-weight: bold;
                background: #1e1e1e;
                padding: 8px 10px;
                border-radius: 5px;
                border: 1px solid #333;
            }}
        """)
        self.label.setFixedWidth(104)
        self.label.move(11, 12)

        # Bouton collapse ▼/▶
        self._collapse_btn = QPushButton("▼", self)
        self._collapse_btn.setFixedSize(20, 20)
        self._collapse_btn.move(119, 18)
        self._collapse_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a2a;
                color: #aaa;
                border: none;
                border-radius: 3px;
                font-size: 9px;
                padding: 0;
            }
            QPushButton:hover { background: #3a3a3a; color: white; }
        """)
        self._collapse_btn.clicked.connect(self._toggle_collapse)

        # Variables pour interaction souris
        self.dragging_clip = None
        self.drag_offset = 0
        self.drag_start_positions = {}  # Pour drag multi-clips
        self.resizing_clip = None
        self.resize_edge = None
        self.selected_clips = []
        self.saved_positions = {}

        # Magnétisme
        self._snap_active = False
        self._snap_x = 0  # position pixel de la ligne de snap

        # Surlignage drop zone (drag depuis bibliothèque)
        self._drag_active = False

        # Position du clic droit pour "Couper ici"
        self.last_context_click_x = 0

        # Forme d'onde audio
        self.waveform_data = None

        self.setMouseTracking(True)

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._collapse_btn.setText("▶")
            self._collapse_btn.move(145, 3)
            self.setFixedHeight(26)
            self.label.hide()
        else:
            self._collapse_btn.setText("▼")
            self._collapse_btn.move(119, 18)
            self.setMinimumHeight(self._normal_min_height)
            self.setMaximumHeight(16777215)
            self.label.show()
        self.updateGeometry()
        self.update()

    def generate_waveform(self, audio_path, max_samples=5000, progress_callback=None, cancel_check=None):
        """Genere des donnees de forme d'onde a partir d'un fichier audio ou video"""
        print(f"🎵 Generation forme d'onde: {audio_path}")

        # Detecter les fichiers video -> extraction audio via ffmpeg
        ext = ''
        if '.' in audio_path:
            ext = audio_path.rsplit('.', 1)[-1].lower()
        video_extensions = ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', 'mpg', 'mpeg']

        if ext in video_extensions:
            print(f"   Fichier video detecte (.{ext}), tentative extraction audio...")
            # Essai 1: ffmpeg
            result = self._extract_waveform_ffmpeg(audio_path, max_samples, cancel_check=cancel_check)
            if result:
                return result
            if cancel_check and cancel_check():
                return None
            # Essai 2: QAudioDecoder (natif Qt, pas de dependance externe)
            result = self._extract_waveform_qt(audio_path, max_samples, progress_callback=progress_callback, cancel_check=cancel_check)
            if result:
                return result
            print("   Aucune methode disponible pour extraire l'audio de la video")
            return None

        # Essayer WAV natif d'abord (rapide)
        try:
            with wave.open(audio_path, 'rb') as wav_file:
                n_channels = wav_file.getnchannels()
                sampwidth = wav_file.getsampwidth()
                framerate = wav_file.getframerate()
                n_frames = wav_file.getnframes()

                print(f"   WAV detecte: {n_channels}ch, {sampwidth*8}bit, {framerate}Hz")

                frames = wav_file.readframes(n_frames)

                if sampwidth == 1:
                    dtype = 'B'
                    audio_data = array.array(dtype, frames)
                    audio_data = [x - 128 for x in audio_data]
                elif sampwidth == 2:
                    dtype = 'h'
                    audio_data = array.array(dtype, frames)
                else:
                    return None

                if n_channels == 2:
                    audio_data = [abs(audio_data[i] + audio_data[i+1]) // 2 for i in range(0, len(audio_data), 2)]
                else:
                    audio_data = [abs(x) for x in audio_data]

                return self._downsample_waveform(audio_data, max_samples)

        except wave.Error:
            print(f"   Pas un fichier WAV, tentative decodage...")
            # Essai 1: ffmpeg — le plus robuste, gere tous les MP3 (VBR, ID3 corrompus, encodages non-standard)
            result = self._extract_waveform_ffmpeg(audio_path, max_samples, cancel_check=cancel_check)
            if result:
                return result
            if cancel_check and cancel_check():
                return None
            # Essai 2: miniaudio
            result = self._decode_with_miniaudio(audio_path, max_samples, cancel_check=cancel_check)
            if result:
                return result
            if cancel_check and cancel_check():
                return None
            # Essai 3: QAudioDecoder (fallback natif Qt)
            return self._extract_waveform_qt(audio_path, max_samples, progress_callback=progress_callback, cancel_check=cancel_check)

        except Exception as e:
            print(f"❌ Erreur generation forme d'onde: {e}")
            return None

    def _decode_with_miniaudio(self, audio_path, max_samples, cancel_check=None):
        """Decode un fichier audio (MP3/FLAC/OGG/AAC...) via miniaudio ou subprocess"""
        # Essai 1 : miniaudio en direct dans un thread pour ne pas bloquer l'UI
        if HAS_MINIAUDIO:
            import threading
            result_holder = [None]
            error_holder = [None]

            def _run():
                try:
                    decoded = miniaudio.decode_file(
                        audio_path,
                        output_format=miniaudio.SampleFormat.SIGNED16,
                        nchannels=1,
                        sample_rate=22050
                    )
                    samples = array.array('h', decoded.samples)
                    audio_data = [abs(s) for s in samples]
                    result_holder[0] = self._downsample_waveform(audio_data, max_samples)
                except Exception as e:
                    error_holder[0] = e

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            while thread.is_alive():
                if cancel_check and cancel_check():
                    return None
                QApplication.processEvents()
                time.sleep(0.05)

            if result_holder[0] is not None:
                print(f"   miniaudio direct: {len(result_holder[0])} points")
                return result_holder[0]
            if error_holder[0]:
                print(f"   ⚠️ miniaudio direct echoue: {error_holder[0]}")

        # Essai 2 : subprocess vers Python 3.12 qui a miniaudio
        return self._decode_via_subprocess(audio_path, max_samples, cancel_check=cancel_check)

    def _decode_via_subprocess(self, audio_path, max_samples, cancel_check=None):
        """Decode via subprocess Python 3.12 (qui a miniaudio installe)"""
        import subprocess
        import json
        import os
        import threading

        # Chercher Python 3.12
        py312 = r"C:\Users\nikop\AppData\Local\Programs\Python\Python312\python.exe"
        if not os.path.exists(py312):
            for p in [r"C:\Python312\python.exe", r"C:\Python\python.exe"]:
                if os.path.exists(p):
                    py312 = p
                    break
            else:
                print(f"   ⚠️ Python 3.12 introuvable pour miniaudio")
                return None

        # Script inline qui decode et renvoie les amplitudes en JSON
        script = f'''
import miniaudio, array, json, sys
decoded = miniaudio.decode_file(
    r"{audio_path}",
    output_format=miniaudio.SampleFormat.SIGNED16,
    nchannels=1,
    sample_rate=22050
)
samples = array.array("h", decoded.samples)
step = max(1, len(samples) // {max_samples})
waveform = []
for i in range(0, len(samples), step):
    chunk = [abs(samples[j]) for j in range(i, min(i+step, len(samples)))]
    waveform.append(max(chunk))
max_val = max(waveform) if waveform else 1
waveform = [x / max_val for x in waveform] if max_val > 0 else waveform
print(json.dumps(waveform))
'''
        # Utiliser un thread pour eviter le deadlock de pipe (stdout peut depasser le buffer)
        proc_ref = [None]
        result_holder = [None]
        error_holder = [None]

        def run_proc():
            try:
                proc = subprocess.Popen(
                    [py312, "-c", script],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                proc_ref[0] = proc
                # communicate() gere correctement le buffering
                stdout, stderr = proc.communicate(timeout=30)
                result_holder[0] = (proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if proc_ref[0]:
                    proc_ref[0].kill()
                    proc_ref[0].communicate()
                print("   ⚠️ Subprocess timeout (30s)")
            except Exception as e:
                error_holder[0] = e

        thread = threading.Thread(target=run_proc, daemon=True)
        thread.start()

        start_t = time.time()
        while thread.is_alive():
            if cancel_check and cancel_check():
                if proc_ref[0]:
                    proc_ref[0].kill()
                return None
            QApplication.processEvents()
            time.sleep(0.05)
            if time.time() - start_t > 35:
                if proc_ref[0]:
                    proc_ref[0].kill()
                return None

        if error_holder[0] or result_holder[0] is None:
            if error_holder[0]:
                print(f"   ❌ Erreur subprocess: {error_holder[0]}")
            return None

        returncode, stdout, stderr = result_holder[0]
        if returncode != 0:
            print(f"   ⚠️ Subprocess erreur: {stderr[:200]}")
            return None

        try:
            waveform = json.loads(stdout.strip())
            print(f"   ✅ subprocess Python3.12 miniaudio: {len(waveform)} points")
            self.waveform_data = waveform
            return waveform
        except Exception as e:
            print(f"   ❌ Erreur parsing JSON: {e}")
            return None

    def _extract_waveform_ffmpeg(self, media_path, max_samples, cancel_check=None):
        """Extrait la forme d'onde d'un fichier video via ffmpeg"""
        import subprocess
        import tempfile
        import os

        temp_wav = None
        try:
            temp_wav = tempfile.mktemp(suffix='.wav')

            # ffmpeg: extraire l'audio en WAV mono 22050Hz 16-bit
            cmd = [
                'ffmpeg', '-i', media_path, '-vn', '-ac', '1', '-ar', '22050',
                '-acodec', 'pcm_s16le', '-y', temp_wav
            ]

            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            start_t = time.time()
            while proc.poll() is None:
                if cancel_check and cancel_check():
                    proc.kill()
                    proc.communicate()
                    return None
                QApplication.processEvents()
                time.sleep(0.1)
                if time.time() - start_t > 120:
                    proc.kill()
                    proc.communicate()
                    print("   ⚠️ ffmpeg timeout (120s)")
                    return None

            _, stderr_bytes = proc.communicate()
            if proc.returncode != 0:
                stderr_short = stderr_bytes.decode(errors='replace')[:200]
                print(f"   ⚠️ ffmpeg extraction echouee: {stderr_short}")
                return None

            if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) < 100:
                print("   ⚠️ Fichier WAV extrait vide ou inexistant")
                return None

            # Lire le WAV extrait
            with wave.open(temp_wav, 'rb') as wav_file:
                n_frames = wav_file.getnframes()
                sampwidth = wav_file.getsampwidth()

                if sampwidth != 2 or n_frames == 0:
                    print(f"   ⚠️ Format WAV inattendu: {sampwidth}bytes, {n_frames} frames")
                    return None

                frames = wav_file.readframes(n_frames)
                audio_data = array.array('h', frames)
                audio_data = [abs(x) for x in audio_data]
                print(f"   ✅ ffmpeg extraction: {len(audio_data)} samples")
                return self._downsample_waveform(audio_data, max_samples)

        except FileNotFoundError:
            print("   ⚠️ ffmpeg non trouve dans le PATH")
            return None
        except Exception as e:
            print(f"   ❌ Erreur ffmpeg: {e}")
            return None
        finally:
            if temp_wav:
                try:
                    os.unlink(temp_wav)
                except:
                    pass

    def _extract_waveform_qt(self, media_path, max_samples, progress_callback=None, cancel_check=None):
        """Extrait la forme d'onde via QAudioDecoder (natif Qt, fonctionne pour audio ET video)"""
        if not HAS_QAUDIO_DECODER:
            print("   QAudioDecoder non disponible")
            return None

        import time

        print(f"   Tentative QAudioDecoder pour: {media_path}")

        try:
            decoder = QAudioDecoder()

            # Format basse resolution pour vitesse : mono, 16-bit, 8000Hz
            fmt = QAudioFormat()
            fmt.setSampleRate(8000)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.Int16)
            decoder.setAudioFormat(fmt)

            decoder.setSource(QUrl.fromLocalFile(media_path))

            # Accumuler directement les pics par blocs (pas tous les samples)
            chunk_peaks = []
            samples_per_chunk = max(1, (8000 * 120) // max_samples)  # ~120s couvert
            current_chunk = []
            finished = [False]
            error_msg = [None]
            total_duration_ms = [0]

            def on_buffer_ready():
                nonlocal current_chunk
                buf = decoder.read()
                if buf.isValid():
                    raw = bytes(buf.data())
                    n = len(raw) // 2
                    if n == 0:
                        return
                    samples = array.array('h', raw)
                    for v in samples:
                        current_chunk.append(abs(v))
                        if len(current_chunk) >= samples_per_chunk:
                            chunk_peaks.append(max(current_chunk))
                            current_chunk = []

            def on_finished():
                finished[0] = True

            def on_error(error):
                error_msg[0] = str(decoder.errorString())
                finished[0] = True

            def on_duration_changed(dur):
                if dur > 0:
                    total_duration_ms[0] = dur

            decoder.bufferReady.connect(on_buffer_ready)
            decoder.finished.connect(on_finished)
            decoder.error.connect(on_error)
            decoder.durationChanged.connect(on_duration_changed)

            decoder.start()

            # Attendre la fin du decodage (max 120s)
            start_time = time.time()
            last_progress_pct = [0]
            while not finished[0] and (time.time() - start_time) < 120:
                QCoreApplication.processEvents()
                time.sleep(0.005)

                if cancel_check and cancel_check():
                    decoder.stop()
                    return None

                # Rapporter la progression
                if progress_callback and total_duration_ms[0] > 0:
                    pos = decoder.position()
                    if pos > 0:
                        pct = min(99, int(pos * 100 / total_duration_ms[0]))
                        if pct > last_progress_pct[0]:
                            last_progress_pct[0] = pct
                            progress_callback(pct)

            decoder.stop()

            # Ajouter le dernier chunk partiel
            if current_chunk:
                chunk_peaks.append(max(current_chunk))

            if error_msg[0]:
                print(f"   QAudioDecoder erreur: {error_msg[0]}")
                # Meme en cas d'erreur, on peut avoir des donnees partielles
                if not chunk_peaks:
                    return None

            if not chunk_peaks:
                print("   QAudioDecoder: aucun sample decode")
                return None

            # Normaliser 0.0-1.0
            max_val = max(chunk_peaks) if chunk_peaks else 1
            if max_val > 0:
                waveform = [p / max_val for p in chunk_peaks]
            else:
                waveform = chunk_peaks

            if progress_callback:
                progress_callback(100)

            elapsed = time.time() - start_time
            print(f"   QAudioDecoder: {len(waveform)} points en {elapsed:.1f}s")
            return waveform

        except Exception as e:
            print(f"   QAudioDecoder exception: {e}")
            return None

    def _downsample_waveform(self, audio_data, max_samples):
        """Reduit les donnees audio en max_samples points normalises 0.0-1.0"""
        step = max(1, len(audio_data) // max_samples)
        waveform = []
        for i in range(0, len(audio_data), step):
            chunk = audio_data[i:i+step]
            if chunk:
                waveform.append(max(chunk))

        if waveform:
            max_val = max(waveform)
            if max_val > 0:
                waveform = [x / max_val for x in waveform]

        print(f"✅ Forme d'onde generee: {len(waveform)} points")
        self.waveform_data = waveform
        return waveform

    def get_clip_at_pos(self, x, y):
        """Trouve le clip sous la position de la souris"""
        if y < 10 or y > 50:
            return None

        for clip in self.clips:
            clip_x = 145 + int(clip.start_time * self.pixels_per_ms)
            clip_width = int(clip.duration * self.pixels_per_ms)
            if clip_x <= x <= clip_x + clip_width:
                return clip, clip_x, clip_width
        return None

    def find_free_position(self, start_time, duration):
        """Trouve une position libre sur la timeline (pas de collision)"""
        sorted_clips = sorted(self.clips, key=lambda c: c.start_time)

        for clip in sorted_clips:
            clip_end = clip.start_time + clip.duration
            new_end = start_time + duration

            if start_time < clip_end and new_end > clip.start_time:
                start_time = clip_end

        return start_time

    def mousePressEvent(self, event):
        """Gere clic souris pour drag/resize/fade/menu + CUT MODE"""
        x = event.position().x()
        y = event.position().y()

        # === MODE CUT ACTIVE ===
        if hasattr(self.parent_editor, 'cut_mode') and self.parent_editor.cut_mode:
            result = self.get_clip_at_pos(x, y)
            if result:
                clip, clip_x, clip_width = result
                click_time_in_clip = (x - clip_x) / self.pixels_per_ms
                self.cut_clip_at_position(clip, click_time_in_clip)
                self.parent_editor.cut_mode = False
                self.parent_editor.cut_btn.setChecked(False)
                self.parent_editor.setCursor(Qt.ArrowCursor)
                for track in self.parent_editor.tracks:
                    track.setCursor(Qt.ArrowCursor)
            return

        result = self.get_clip_at_pos(x, y)

        if result:
            clip, clip_x, clip_width = result
            modifiers = event.modifiers()

            if modifiers & Qt.ControlModifier:
                if clip in self.selected_clips:
                    self.selected_clips.remove(clip)
                else:
                    self.selected_clips.append(clip)
                self.update()
                return
            elif modifiers & Qt.ShiftModifier:
                if self.selected_clips:
                    last_selected = self.selected_clips[-1]
                    if last_selected in self.clips:
                        start_idx = self.clips.index(last_selected)
                        end_idx = self.clips.index(clip)
                        if start_idx > end_idx:
                            start_idx, end_idx = end_idx, start_idx
                        for i in range(start_idx, end_idx + 1):
                            if self.clips[i] not in self.selected_clips:
                                self.selected_clips.append(self.clips[i])
                else:
                    self.selected_clips = [clip]
                self.update()
                return
            else:
                # Clic simple - verifier si le clip est deja selectionne (multi-pistes)
                all_selected = self.get_all_selected_clips()
                if clip not in all_selected:
                    if hasattr(self.parent_editor, 'clear_all_selections'):
                        self.parent_editor.clear_all_selections()
                    self.selected_clips = [clip]

            # Calculer positions des fades
            fade_in_px = int(clip.fade_in_duration * self.pixels_per_ms) if clip.fade_in_duration > 0 else 0
            fade_out_px = int(clip.fade_out_duration * self.pixels_per_ms) if clip.fade_out_duration > 0 else 0

            if fade_in_px > 0 and x < clip_x + fade_in_px and y >= 10 and y <= 50:
                self.resizing_clip = clip
                self.resize_edge = 'fade_in'
                self.saved_positions = {clip: (clip.start_time, clip.duration)}
            elif fade_out_px > 0 and x > clip_x + clip_width - fade_out_px and y >= 10 and y <= 50:
                self.resizing_clip = clip
                self.resize_edge = 'fade_out'
                self.saved_positions = {clip: (clip.start_time, clip.duration)}
            elif x < clip_x + 5:
                self.resizing_clip = clip
                self.resize_edge = 'left'
                self.saved_positions = {clip: (clip.start_time, clip.duration)}
            elif x > clip_x + clip_width - 5:
                self.resizing_clip = clip
                self.resize_edge = 'right'
                self.saved_positions = {clip: (clip.start_time, clip.duration)}
            else:
                # Drag - sauvegarder positions de TOUS les clips selectionnes (multi-pistes)
                self.dragging_clip = clip
                self.drag_offset = x - clip_x

                # Sauvegarder les positions de depart de tous les clips selectionnes
                self.drag_start_positions = {}
                for track in self.parent_editor.tracks:
                    for sel_clip in track.selected_clips:
                        self.drag_start_positions[sel_clip] = sel_clip.start_time

                # Ajouter le clip actuel si pas deja selectionne
                if clip not in self.drag_start_positions:
                    self.drag_start_positions[clip] = clip.start_time

                # Sauvegarder pour undo
                if hasattr(self.parent_editor, 'save_state'):
                    self.parent_editor.save_state()

            # Clip trouve -> accepter l'event, ne PAS propager au parent (evite rubber band)
            event.accept()
            return

        # Zone vide -> laisser le parent gerer (rubber band selection)
        super().mousePressEvent(event)

    def get_all_selected_clips(self):
        """Retourne tous les clips selectionnes sur toutes les pistes"""
        all_clips = []
        if hasattr(self.parent_editor, 'tracks'):
            for track in self.parent_editor.tracks:
                all_clips.extend(track.selected_clips)
        return all_clips

    def _apply_snap(self, time_ms, exclude_clip=None):
        """Retourne time_ms snappé au point le plus proche (playhead + bords clips).
        Active self._snap_active et self._snap_x si le magnétisme s'applique."""
        SNAP_PX = 10  # seuil en pixels
        threshold_ms = SNAP_PX / max(self.pixels_per_ms, 1e-6)

        snap_points = []

        # Playhead
        if hasattr(self.parent_editor, 'playback_position'):
            snap_points.append(self.parent_editor.playback_position)

        # Bords de tous les clips sur toutes les pistes
        for track in self.parent_editor.tracks:
            for clip in track.clips:
                if clip is exclude_clip:
                    continue
                snap_points.append(clip.start_time)
                snap_points.append(clip.start_time + clip.duration)

        best = None
        best_dist = threshold_ms
        for pt in snap_points:
            d = abs(time_ms - pt)
            if d < best_dist:
                best_dist = d
                best = pt

        if best is not None:
            self._snap_active = True
            self._snap_x = 145 + int(best * self.pixels_per_ms)
            return best
        else:
            self._snap_active = False
            return time_ms

    def mouseMoveEvent(self, event):
        """Gere drag et resize + ANTI-COLLISION + DRAG MULTI-CLIPS"""
        x = event.position().x()

        # Si mode cut actif
        if hasattr(self.parent_editor, 'cut_mode') and self.parent_editor.cut_mode:
            result = self.get_clip_at_pos(x, event.position().y())
            if result:
                self.setCursor(Qt.SplitHCursor)
            else:
                self.setCursor(Qt.ForbiddenCursor)
            return

        if self.dragging_clip:
            # Calculer le delta de deplacement
            new_x = max(145, x - self.drag_offset)
            new_start = (new_x - 145) / self.pixels_per_ms
            new_start = self._apply_snap(new_start, exclude_clip=self.dragging_clip)
            delta = new_start - self.drag_start_positions.get(self.dragging_clip, self.dragging_clip.start_time)

            # Deplacer TOUS les clips selectionnes sur TOUTES les pistes
            # Clamper le delta pour eviter de sauter par-dessus des clips
            clamped_delta = delta

            for track in self.parent_editor.tracks:
                for sel_clip in track.selected_clips:
                    if sel_clip not in self.drag_start_positions:
                        continue

                    original_start = self.drag_start_positions[sel_clip]

                    # Limiter pour ne pas aller sous 0
                    if original_start + clamped_delta < 0:
                        clamped_delta = -original_start

                    # Verifier collision avec les autres clips de cette piste
                    for other_clip in track.clips:
                        if other_clip in track.selected_clips:
                            continue
                        other_end = other_clip.start_time + other_clip.duration

                        sel_clip_end_orig = original_start + sel_clip.duration

                        if clamped_delta > 0:
                            # Drag vers la droite: bloquer avant le prochain clip
                            # Le clip bloqueur doit etre devant nous (son debut >= notre fin originale - marge)
                            if other_clip.start_time >= sel_clip_end_orig - 1:
                                max_delta = other_clip.start_time - sel_clip_end_orig
                                if max_delta < clamped_delta:
                                    clamped_delta = max(0, max_delta)
                        else:
                            # Drag vers la gauche: bloquer apres le clip precedent
                            # Le clip bloqueur doit etre derriere nous (sa fin <= notre debut original + marge)
                            if other_end <= original_start + 1:
                                max_delta = -(original_start - other_end)
                                if max_delta > clamped_delta:
                                    clamped_delta = min(0, max_delta)

            # Appliquer le deplacement avec le delta clampe
            if abs(clamped_delta) > 0.1:
                for track in self.parent_editor.tracks:
                    for sel_clip in track.selected_clips:
                        if sel_clip in self.drag_start_positions:
                            sel_clip.start_time = max(0, self.drag_start_positions[sel_clip] + clamped_delta)
                    track.update()

        elif self.resizing_clip:
            clip_x = 145 + int(self.resizing_clip.start_time * self.pixels_per_ms)

            if self.resize_edge == 'fade_in':
                new_fade = max(0, (x - clip_x) / self.pixels_per_ms)
                max_fade_in = self.resizing_clip.duration - self.resizing_clip.fade_out_duration
                self.resizing_clip.fade_in_duration = min(new_fade, max_fade_in)
            elif self.resize_edge == 'fade_out':
                clip_end = clip_x + int(self.resizing_clip.duration * self.pixels_per_ms)
                new_fade = max(0, (clip_end - x) / self.pixels_per_ms)
                max_fade_out = self.resizing_clip.duration - self.resizing_clip.fade_in_duration
                self.resizing_clip.fade_out_duration = min(new_fade, max_fade_out)
            elif self.resize_edge == 'left':
                new_start_ms = max(0, (x - 145) / self.pixels_per_ms)
                new_start_ms = self._apply_snap(new_start_ms, exclude_clip=self.resizing_clip)
                old_end_ms = self.resizing_clip.start_time + self.resizing_clip.duration

                for clip in self.clips:
                    if clip == self.resizing_clip:
                        continue
                    if clip.start_time < self.resizing_clip.start_time:
                        clip_end_ms = clip.start_time + clip.duration
                        if new_start_ms < clip_end_ms:
                            new_start_ms = clip_end_ms

                if new_start_ms < old_end_ms - 500:
                    self.resizing_clip.start_time = new_start_ms
                    self.resizing_clip.duration = old_end_ms - new_start_ms
            else:  # right
                new_end_ms = self.resizing_clip.start_time + (x - clip_x) / self.pixels_per_ms
                new_end_ms = self._apply_snap(new_end_ms, exclude_clip=self.resizing_clip)
                new_duration_ms = new_end_ms - self.resizing_clip.start_time

                for clip in self.clips:
                    if clip == self.resizing_clip:
                        continue
                    if clip.start_time > self.resizing_clip.start_time:
                        if new_end_ms > clip.start_time:
                            new_duration_ms = clip.start_time - self.resizing_clip.start_time
                            break

                self.resizing_clip.duration = max(500, new_duration_ms)

            self.update()

        else:
            result = self.get_clip_at_pos(x, event.position().y())
            if result:
                clip, clip_x, clip_width = result
                if x < clip_x + 5 or x > clip_x + clip_width - 5:
                    self.setCursor(Qt.SizeHorCursor)
                else:
                    self.setCursor(Qt.OpenHandCursor)

                # Tooltip pour les clips de séquence
                if getattr(clip, 'memory_ref', None) and self.is_sequence_track:
                    mem_ref = clip.memory_ref
                    label = getattr(clip, 'memory_label', f"MEM {mem_ref[0]+1}.{mem_ref[1]+1}")
                    tip = f"<b>{label}</b>"
                    # Chercher l'effet associé dans la mémoire
                    mw = getattr(self.parent_editor, 'main_window', None)
                    if mw:
                        memories = getattr(mw, 'memories', None)
                        if memories:
                            mc, rw = mem_ref
                            mem = memories[mc][rw] if mc < len(memories) and rw < len(memories[mc]) else None
                            if mem:
                                eff = mem.get("effect")
                                if eff and eff.get("layers"):
                                    eff_name = eff.get("name") or tr("lt_custom_effect")
                                    tip += f"<br><small>⚡ {eff_name}</small>"
                                else:
                                    tip += f"<br><small>{tr('lt_no_effect')}</small>"
                    QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                else:
                    QToolTip.hideText()
            else:
                self.setCursor(Qt.ArrowCursor)
                QToolTip.hideText()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Fin drag/resize"""
        self.dragging_clip = None
        self.drag_start_positions = {}
        self.resizing_clip = None
        self.resize_edge = None
        self._snap_active = False
        self.update()

        if not (hasattr(self.parent_editor, 'cut_mode') and self.parent_editor.cut_mode):
            self.setCursor(Qt.ArrowCursor)

        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        """Menu contextuel sur clip OU zone vide"""
        if hasattr(self.parent_editor, 'cut_mode') and self.parent_editor.cut_mode:
            return

        # Sauvegarder la position du clic pour "Couper ici"
        self.last_context_click_x = event.pos().x()

        result = self.get_clip_at_pos(event.pos().x(), event.pos().y())

        if self.is_effect_track:
            if result:
                clip, clip_x, _ = result
                click_pos_in_clip = (event.pos().x() - clip_x) / self.pixels_per_ms
                self.show_effect_clip_menu(clip, event.globalPos(), click_pos_in_clip)
            else:
                self.show_effect_empty_menu(event.pos(), event.globalPos())
        elif self.is_sequence_track:
            if result:
                clip, clip_x, _ = result
                self.show_sequence_clip_menu(clip, event.globalPos())
            else:
                self.show_sequence_empty_menu(event.pos(), event.globalPos())
        elif result:
            clip, clip_x, _ = result
            click_pos_in_clip = (event.pos().x() - clip_x) / self.pixels_per_ms
            self.show_clip_menu(clip, event.globalPos(), click_pos_in_clip)
        else:
            self.show_empty_menu(event.pos(), event.globalPos())

        super().contextMenuEvent(event)

    # ── Menus piste Effet ─────────────────────────────────────────────────────

    @staticmethod
    def _load_all_effects():
        """Charge BUILTIN_EFFECTS + effets custom (fichiers .mystrow_custom_effects.json)."""
        try:
            from effect_editor import BUILTIN_EFFECTS
            effects = list(BUILTIN_EFFECTS)
        except Exception:
            effects = []
        try:
            import json as _j
            from pathlib import Path as _P
            f = _P.home() / ".mystrow_custom_effects.json"
            if f.exists():
                custom = _j.loads(f.read_text(encoding="utf-8"))
                existing = {e.get("name") for e in effects}
                for e in custom:
                    if e.get("name") not in existing:
                        effects.append(e)
        except Exception:
            pass
        return effects

    _EFFECT_MENU_STYLE = """
        QMenu {
            background: #1a1a1a; border: 1px solid #3a3a3a;
            padding: 4px; font-size: 12px;
        }
        QMenu::item { padding: 6px 16px; border-radius: 3px; color: #e0e0e0; }
        QMenu::item:selected { background: #2a2a4a; color: #fff; }
        QMenu::item:disabled { color: #555; font-size: 10px; letter-spacing: 1px; }
        QMenu::separator { background: #333; height: 1px; margin: 3px 8px; }
    """

    def _build_effect_picker_menu(self, on_select):
        """Construit un QMenu de sélection d'effet avec barre de recherche."""
        from PySide6.QtWidgets import QWidgetAction, QLineEdit

        all_effects = self._load_all_effects()
        menu = QMenu(self)
        menu.setStyleSheet(self._EFFECT_MENU_STYLE)

        # ── Barre de recherche ────────────────────────────────────────────
        search_w = QWidget()
        search_w.setStyleSheet("background: transparent;")
        sl = QHBoxLayout(search_w)
        sl.setContentsMargins(6, 4, 6, 4)
        search_input = QLineEdit()
        search_input.setPlaceholderText(tr("lt_search_effect_placeholder"))
        search_input.setClearButtonEnabled(True)
        search_input.setStyleSheet("""
            QLineEdit {
                background: #111; color: #e0e0e0;
                border: 1px solid #444; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #cc44ff; }
        """)
        sl.addWidget(search_input)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(search_w)
        menu.addAction(wa)
        menu.addSeparator()

        # ── Effets par catégorie ──────────────────────────────────────────
        categories = {}
        for eff in all_effects:
            cat = eff.get("category", tr("lt_category_others"))
            categories.setdefault(cat, []).append(eff)

        actions_by_name = {}  # name -> QAction

        for cat, effs in categories.items():
            hdr = menu.addAction(cat.upper())
            hdr.setEnabled(False)
            for eff in effs:
                nm = eff.get("name", "")
                act = menu.addAction(f"   {eff.get('emoji', '✨')}  {nm}")
                act.triggered.connect(lambda _, e=eff: on_select(e))
                actions_by_name[nm.lower()] = act
            menu.addSeparator()

        # ── Filtrage par recherche ────────────────────────────────────────
        def _filter(text):
            txt = text.strip().lower()
            for nm_lower, act in actions_by_name.items():
                act.setVisible(not txt or txt in nm_lower)

        search_input.textChanged.connect(_filter)
        return menu

    def show_effect_empty_menu(self, local_pos, global_pos):
        """Menu clic droit sur zone vide de la piste Effet."""
        def _select(eff):
            self._fill_effect_at_pos(eff, local_pos)

        menu = self._build_effect_picker_menu(_select)
        menu.exec(global_pos)

    def show_effect_clip_menu(self, clip, global_pos, click_pos_in_clip):
        """Menu clic droit sur un clip d'effet existant."""
        menu = QMenu(self)
        menu.setStyleSheet(self._EFFECT_MENU_STYLE)

        # Changer l'effet → sous-menu picker identique à la page d'accueil
        cur_name = getattr(clip, 'effect_name', '') or ''
        changer_label = tr("lt_menu_change_effect_named", name=cur_name) if cur_name else tr("lt_menu_change_effect")
        act_change = menu.addAction(changer_label)
        def _open_picker():
            def _select(eff):
                clip.effect_name   = eff.get("name", "")
                clip.effect_layers = eff.get("layers", [])
                clip.effect_type   = eff.get("type", "")
                self.update()
                if hasattr(self.parent_editor, 'save_state'):
                    self.parent_editor.save_state()
            m = self._build_effect_picker_menu(_select)
            m.exec(global_pos)
        act_change.triggered.connect(_open_picker)

        menu.addSeparator()

        # Groupe cible
        cur_groups = getattr(clip, 'effect_target_groups', [])
        grp_label_str = ", ".join(cur_groups) if cur_groups else "Tous"
        act_grp = menu.addAction(f"🎯  Groupes : {grp_label_str}")
        act_grp.triggered.connect(lambda: self._edit_effect_target_groups(clip))

        # Vitesse
        cur_speed = getattr(clip, 'effect_speed', 50)
        act_speed = menu.addAction(f"⚡  Vitesse : {cur_speed}")
        act_speed.triggered.connect(lambda: self.edit_clip_effect_speed(clip))

        menu.addSeparator()

        # Couper ici (si le clic est à plus de 200ms des bords)
        if click_pos_in_clip is not None and 200 < click_pos_in_clip < clip.duration - 200:
            act_cut = menu.addAction(tr("lt_menu_cut_here"))
            act_cut.triggered.connect(lambda: self.cut_clip_at_position(clip, click_pos_in_clip))
            menu.addSeparator()

        act_del = menu.addAction(tr("lt_menu_delete"))
        act_del.triggered.connect(lambda: self._delete_effect_clip(clip))
        menu.exec(global_pos)

    # ── Menus piste Séquence ──────────────────────────────────────────────────

    _SEQ_MENU_STYLE = """
        QMenu {
            background: #1a1a1a; border: 1px solid #3a3a3a;
            padding: 4px; font-size: 12px;
        }
        QMenu::item { padding: 6px 16px; border-radius: 3px; color: #e0e0e0; }
        QMenu::item:selected { background: #003355; color: #fff; }
        QMenu::item:disabled { color: #555; font-size: 10px; letter-spacing: 1px; }
        QMenu::separator { background: #333; height: 1px; margin: 3px 8px; }
    """

    def _build_memory_picker_menu(self, on_select):
        """Construit un QMenu de sélection de mémoire."""
        from PySide6.QtWidgets import QWidgetAction, QLineEdit

        mw       = getattr(self.parent_editor, 'main_window', None)
        memories = getattr(mw, 'memories', None) if mw else None

        menu = QMenu(self)
        menu.setStyleSheet(self._SEQ_MENU_STYLE)

        if not memories:
            act = menu.addAction(tr("lt_no_memory"))
            act.setEnabled(False)
            return menu

        # Barre de recherche
        search_w = QWidget()
        search_w.setStyleSheet("background: transparent;")
        sl = QHBoxLayout(search_w)
        sl.setContentsMargins(6, 4, 6, 4)
        search_input = QLineEdit()
        search_input.setPlaceholderText("Rechercher une mémoire…")
        search_input.setClearButtonEnabled(True)
        search_input.setStyleSheet("""
            QLineEdit {
                background: #111; color: #e0e0e0;
                border: 1px solid #444; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #00d4ff; }
        """)
        sl.addWidget(search_input)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(search_w)
        menu.addAction(wa)
        menu.addSeparator()

        actions_by_label = {}
        for mem_col, col_mems in enumerate(memories):
            for row_idx, mem in enumerate(col_mems):
                if mem is None:
                    continue
                color  = PalettePanel._dominant_color(mem, mw, mem_col, row_idx)
                label  = f"MEM {mem_col + 1}.{row_idx + 1}"
                # Icône couleur
                pix = QPixmap(14, 14)
                pix.fill(color)
                act = menu.addAction(QIcon(pix), f"  {label}")
                act.triggered.connect(
                    lambda _, mc=mem_col, ri=row_idx, lbl=label, c=color:
                        on_select(mc, ri, lbl, c)
                )
                actions_by_label[label.lower()] = act

        def _filter(text):
            txt = text.strip().lower()
            for lbl_lower, act in actions_by_label.items():
                act.setVisible(not txt or txt in lbl_lower)

        search_input.textChanged.connect(_filter)
        return menu

    def show_sequence_empty_menu(self, local_pos, global_pos):
        """Menu clic droit sur zone vide de la piste Séquence."""
        def _select(mem_col, row_idx, label, color):
            drop_x     = local_pos.x() - 145
            start_time = max(0, drop_x / self.pixels_per_ms)
            start_time = self.find_free_position(start_time, 5000)
            clip = self.add_clip_direct(start_time, 5000, color, 100)
            clip.memory_ref   = (mem_col, row_idx)
            clip.memory_label = label
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()

        menu = self._build_memory_picker_menu(_select)
        menu.exec(global_pos)

    def show_sequence_clip_menu(self, clip, global_pos):
        """Menu clic droit sur un clip de séquence AKAI."""
        menu = QMenu(self)
        menu.setStyleSheet(self._SEQ_MENU_STYLE)

        # ── Changer la mémoire ─────────────────────────────────────────
        cur_label = getattr(clip, 'memory_label', '') or ''
        changer_lbl = f"Changer ({cur_label})" if cur_label else "Changer de mémoire"
        act_change = menu.addAction(changer_lbl)

        def _open_mem_picker():
            def _select(mem_col, row_idx, label, color):
                clip.color        = color
                clip.memory_ref   = (mem_col, row_idx)
                clip.memory_label = label
                self.update()
                if hasattr(self.parent_editor, 'save_state'):
                    self.parent_editor.save_state()
            m = self._build_memory_picker_menu(_select)
            m.exec(global_pos)

        act_change.triggered.connect(_open_mem_picker)

        menu.addSeparator()
        act_del = menu.addAction(tr("lt_menu_delete"))
        act_del.triggered.connect(lambda: self._delete_clip(clip))
        menu.exec(global_pos)

    def _delete_clip(self, clip):
        """Supprime un clip générique."""
        if clip in self.clips:
            self.clips.remove(clip)
            if clip in self.selected_clips:
                self.selected_clips.remove(clip)
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()

    def _fill_effect_at_pos(self, eff, local_pos):
        """Crée un clip d'effet dans le vide à la position cliquée."""
        drop_x = local_pos.x() - 145
        click_time = max(0, drop_x / self.pixels_per_ms)

        sorted_clips = sorted(self.clips, key=lambda c: c.start_time)
        gap_start = 0
        gap_end = self.total_duration
        for c in sorted_clips:
            if c.start_time + c.duration <= click_time:
                gap_start = c.start_time + c.duration
            elif c.start_time >= click_time:
                gap_end = c.start_time
                break

        gap_duration = gap_end - gap_start
        if gap_duration > 100:
            clip_duration = min(gap_duration, 10_000)  # 10 secondes max par défaut
            clip = self.add_clip(gap_start, clip_duration, QColor("#1a0a2e"), 100)
            clip.effect_name   = eff.get("name", "")
            clip.effect_layers = eff.get("layers", [])
            clip.effect_type   = eff.get("type", "")
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()

    def _delete_effect_clip(self, clip):
        """Supprime un clip d'effet."""
        if clip in self.clips:
            self.clips.remove(clip)
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()

    # ─────────────────────────────────────────────────────────────────────────

    def show_empty_menu(self, local_pos, global_pos):
        """Menu sur zone vide"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #2a2a2a;
                color: white;
                border: 2px solid #00d4ff;
                padding: 5px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 30px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #00d4ff;
                color: black;
            }
            QMenu::separator {
                background: #4a4a4a;
                height: 1px;
                margin: 5px 10px;
            }
        """)

        colors = [
            ("Rouge", QColor(255, 0, 0)),
            ("Vert", QColor(0, 255, 0)),
            ("Bleu", QColor(0, 0, 255)),
            ("Jaune", QColor(200, 200, 0)),
            ("Magenta", QColor(255, 0, 255)),
            ("Cyan", QColor(0, 255, 255)),
            ("Blanc", QColor(255, 255, 255)),
            ("Orange", QColor(255, 128, 0)),
            ("Black Light", QColor(100, 0, 255)),
        ]

        bicolors = [
            ("Rouge/Bleu", QColor(255, 0, 0), QColor(0, 0, 255)),
            ("Vert/Magenta", QColor(0, 255, 0), QColor(255, 0, 255)),
            ("Jaune/Cyan", QColor(200, 200, 0), QColor(0, 255, 255)),
            ("Rouge/Blanc", QColor(255, 0, 0), QColor(255, 255, 255)),
            ("Bleu/Blanc", QColor(0, 0, 255), QColor(255, 255, 255)),
        ]

        fill_gap_menu = menu.addMenu(tr("lt_menu_create_block"))

        for name, col in colors:
            action = fill_gap_menu.addAction(f"■ {name}")
            action.triggered.connect(lambda checked=False, c=col, p=local_pos: self.fill_gap_at_pos(c, p))

        fill_gap_menu.addSeparator()

        for name, col1, col2 in bicolors:
            action = fill_gap_menu.addAction(f"■■ {name}")
            action.triggered.connect(lambda checked=False, c1=col1, c2=col2, p=local_pos: self.fill_gap_bicolor_at_pos(c1, c2, p))

        menu.exec(global_pos)

    def fill_gap_at_pos(self, color, pos):
        """Comble le vide a la position cliquee"""
        drop_x = pos.x() - 145
        click_time = max(0, drop_x / self.pixels_per_ms)

        sorted_clips = sorted(self.clips, key=lambda c: c.start_time)

        gap_start = 0
        gap_end = self.total_duration

        for clip in sorted_clips:
            clip_end = clip.start_time + clip.duration

            if clip_end <= click_time:
                gap_start = clip_end
            elif clip.start_time >= click_time:
                gap_end = clip.start_time
                break

        gap_duration = gap_end - gap_start

        if gap_duration > 100:
            self.add_clip(gap_start, gap_duration, color, 100)
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()

    def fill_gap_bicolor_at_pos(self, color1, color2, pos):
        """Comble le vide avec un bicolore"""
        drop_x = pos.x() - 145
        click_time = max(0, drop_x / self.pixels_per_ms)

        sorted_clips = sorted(self.clips, key=lambda c: c.start_time)

        gap_start = 0
        gap_end = self.total_duration

        for clip in sorted_clips:
            clip_end = clip.start_time + clip.duration

            if clip_end <= click_time:
                gap_start = clip_end
            elif clip.start_time >= click_time:
                gap_end = clip.start_time
                break

        gap_duration = gap_end - gap_start

        if gap_duration > 100:
            clip = self.add_clip(gap_start, gap_duration, color1, 100)
            clip.color2 = color2
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()

    def show_clip_menu(self, clip, global_pos, click_pos_in_clip=None):
        """Affiche le menu contextuel d'un clip"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #2a2a2a;
                color: white;
                border: 2px solid #00d4ff;
                padding: 5px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 30px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #00d4ff;
                color: black;
            }
            QMenu::separator {
                background: #4a4a4a;
                height: 1px;
                margin: 5px 10px;
            }
        """)

        # === INTENSITE ===
        intensity_menu = menu.addMenu(tr("lt_menu_intensity"))
        for val in [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            action = intensity_menu.addAction(f"{val}%")
            action.triggered.connect(lambda checked=False, v=val, cl=clip: self.set_clip_intensity(cl, v))
        intensity_menu.addSeparator()
        custom_action = intensity_menu.addAction(tr("lt_menu_custom"))
        custom_action.triggered.connect(lambda: self.edit_clip_intensity(clip))

        # === COULEUR ===
        color_menu = menu.addMenu(tr("lt_menu_color"))
        colors = [
            ("Rouge", QColor(255, 0, 0)),
            ("Vert", QColor(0, 255, 0)),
            ("Bleu", QColor(0, 0, 255)),
            ("Jaune", QColor(200, 200, 0)),
            ("Magenta", QColor(255, 0, 255)),
            ("Cyan", QColor(0, 255, 255)),
            ("Blanc", QColor(255, 255, 255)),
            ("Black Light", QColor(100, 0, 255)),
        ]
        for name, col in colors:
            pixmap = QPixmap(16, 16)
            pixmap.fill(col)
            icon = QIcon(pixmap)
            action = color_menu.addAction(icon, name)
            action.triggered.connect(lambda checked=False, c=col, cl=clip: self.set_clip_color(cl, c))

        # Bicolores
        color_menu.addSeparator()
        bicolors = [
            ("Rouge/Vert", QColor(255, 0, 0), QColor(0, 200, 0)),
            ("Rouge/Bleu", QColor(255, 0, 0), QColor(0, 0, 255)),
            ("Rouge/Orange", QColor(255, 0, 0), QColor(255, 128, 0)),
            ("Rouge/Rose", QColor(255, 0, 0), QColor(255, 105, 180)),
            ("Bleu/Cyan", QColor(0, 0, 255), QColor(0, 255, 255)),
            ("Vert/Jaune", QColor(0, 200, 0), QColor(255, 255, 0)),
            ("Bleu/Violet", QColor(0, 0, 255), QColor(128, 0, 255)),
            ("Orange/Jaune", QColor(255, 128, 0), QColor(255, 255, 0)),
            ("Cyan/Violet", QColor(0, 255, 255), QColor(128, 0, 255)),
        ]
        for name, col1, col2 in bicolors:
            pixmap = QPixmap(16, 16)
            p = QPainter(pixmap)
            p.fillRect(0, 0, 8, 16, col1)
            p.fillRect(8, 0, 8, 16, col2)
            p.end()
            icon = QIcon(pixmap)
            action = color_menu.addAction(icon, name)
            action.triggered.connect(lambda checked=False, c1=col1, c2=col2, cl=clip: self.set_clip_bicolor(cl, c1, c2))

        # === MOUVEMENT (piste Lyres) ===
        if self.name == "Lyres":
            menu.addSeparator()
            move_label = tr("lt_menu_movement")
            if clip.move_effect:
                eff_icons = {"cercle":"⭕","figure8":"∞","balayage_h":"↔","balayage_v":"↕","aleatoire":"✦"}
                move_label = tr("lt_menu_movement_named", icon=eff_icons.get(clip.move_effect, clip.move_effect))
            elif clip.pan_start != clip.pan_end or clip.tilt_start != clip.tilt_end:
                move_label = tr("lt_menu_movement_traj")
            move_act = menu.addAction(move_label)
            move_act.triggered.connect(lambda: self.edit_clip_movement(clip))

        # === FADES ===
        menu.addSeparator()
        fade_in_action = menu.addAction(tr("lt_menu_fade_in"))
        fade_in_action.triggered.connect(lambda: self.add_clip_fade_in(clip))
        fade_out_action = menu.addAction(tr("lt_menu_fade_out"))
        fade_out_action.triggered.connect(lambda: self.add_clip_fade_out(clip))

        if clip.fade_in_duration > 0 or clip.fade_out_duration > 0:
            clear_fades = menu.addAction(tr("lt_menu_clear_fades"))
            clear_fades.triggered.connect(lambda: self.clear_clip_fades(clip))

        # === COPIER VERS ===
        menu.addSeparator()
        if hasattr(self.parent_editor, 'tracks'):
            copy_menu = menu.addMenu(tr("lt_menu_copy_to"))
            for track in self.parent_editor.tracks:
                if track != self and not track.is_sequence_track and not track.is_effect_track:
                    action = copy_menu.addAction(track.name)
                    action.triggered.connect(lambda checked=False, cl=clip, t=track: self.copy_clip_to_track(cl, t))

        # === COUPER ICI ===
        menu.addSeparator()
        if click_pos_in_clip is not None and click_pos_in_clip > 200 and click_pos_in_clip < clip.duration - 200:
            cut_here_action = menu.addAction(tr("lt_menu_cut_here"))
            cut_here_action.triggered.connect(lambda: self.cut_clip_at_position(clip, click_pos_in_clip))
        else:
            cut_action = menu.addAction(tr("lt_menu_cut_in_two"))
            cut_action.triggered.connect(lambda: self.cut_clip_in_two(clip))

        # === SUPPRIMER ===
        delete_action = menu.addAction(tr("lt_menu_delete_clip"))
        delete_action.triggered.connect(lambda: self.delete_clip(clip))

        menu.exec(global_pos)

    def set_clip_intensity(self, clip, value):
        clip.intensity = value
        self.update()
        if hasattr(self.parent_editor, 'save_state'):
            self.parent_editor.save_state()

    def edit_clip_intensity(self, clip):
        """Edite intensite avec dialog style"""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("lt_dlg_intensity_title"))
        dialog.setFixedSize(350, 200)
        dialog.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel { color: white; }
            QPushButton {
                background: #cccccc;
                color: black;
                border: 1px solid #999999;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover { background: #00d4ff; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 30, 30, 30)

        value_label = QLabel(f"{clip.intensity}%")
        value_label.setStyleSheet("color: white; font-size: 32px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(clip.intensity)
        slider.valueChanged.connect(lambda v: value_label.setText(f"{v}%"))
        layout.addWidget(slider)

        btn_layout = QHBoxLayout()
        cancel = QPushButton(tr("btn_cancel_x"))
        cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel)
        ok = QPushButton("✅ OK")
        ok.clicked.connect(dialog.accept)
        ok.setStyleSheet("background: #00d4ff; color: black; font-weight: bold;")
        btn_layout.addWidget(ok)
        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            clip.intensity = slider.value()
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()

    def set_clip_color(self, clip, color):
        clip.color = color
        clip.color2 = None
        self.update()
        if hasattr(self.parent_editor, 'save_state'):
            self.parent_editor.save_state()

    def set_clip_bicolor(self, clip, color1, color2):
        """Remplace la couleur du clip par une bicolore"""
        clip.color = color1
        clip.color2 = color2
        self.update()
        if hasattr(self.parent_editor, 'save_state'):
            self.parent_editor.save_state()

    def set_clip_effect(self, clip, effect):
        clip.effect = effect
        self.update()

    def _clear_clip_effect(self, clip):
        """Supprime l'effet du clip (legacy + nouveau système)."""
        clip.effect      = None
        clip.effect_name  = ""
        clip.effect_layers = []
        self.update()
        if hasattr(self.parent_editor, 'save_state'):
            self.parent_editor.save_state()

    def _apply_builtin_effect_to_clip(self, clip, eff_dict: dict):
        """Applique un effet builtin/custom au clip depuis le menu contextuel.
        Charge les layers depuis la config sauvegardée (bouton/bibliothèque) ou depuis le builtin."""
        from effect_editor import EffectLayer
        name = eff_dict.get("name", "")
        clip.effect_name = name
        clip.effect = None  # désactiver l'ancien système

        # Chercher les layers sauvegardés (config bouton ou bibliothèque)
        mw = getattr(self.parent_editor, 'main_window', None)
        saved_cfg = {}
        if mw:
            for cfg in getattr(mw, '_button_effect_configs', {}).values():
                if isinstance(cfg, dict) and cfg.get("name") == name:
                    saved_cfg = cfg
                    break
            if not saved_cfg:
                saved_cfg = getattr(mw, '_effect_library_configs', {}).get(name, {})

        if saved_cfg.get("layers"):
            clip.effect_layers    = list(saved_cfg["layers"])
            clip.effect_play_mode = saved_cfg.get("play_mode", "loop")
            clip.effect_duration  = saved_cfg.get("duration", 0)
        else:
            # Fallback : layers par défaut du builtin
            layers = EffectLayer.layers_from_builtin(eff_dict)
            clip.effect_layers    = [l.to_dict() for l in layers]
            clip.effect_play_mode = "loop"
            clip.effect_duration  = 0

        self.update()
        if hasattr(self.parent_editor, 'save_state'):
            self.parent_editor.save_state()

    def _open_effect_editor_for_clip(self, clip):
        """Ouvre l'éditeur d'effets complet avec ce clip comme cible."""
        try:
            from effect_editor import EffectEditorDialog
            mw = getattr(self.parent_editor, 'main_window', None)
            dlg = EffectEditorDialog(clips=[clip], main_window=mw, parent=self)
            if dlg.exec():
                self.update()
                if hasattr(self.parent_editor, 'save_state'):
                    self.parent_editor.save_state()
        except Exception as _e:
            pass

    def edit_clip_movement(self, clip):
        """Ouvre le dialog d'édition mouvement Pan/Tilt pour un clip Lyres."""
        dlg = MovementEditorDialog(clip, self)
        if dlg.exec() == QDialog.Accepted:
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()

    def _edit_effect_target_groups(self, clip):
        """Dialogue cases à cocher A-F pour cibler des groupes spécifiques."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                                       QCheckBox, QPushButton, QLabel, QFrame)
        from PySide6.QtCore import Qt
        _LETTERS = [("A", "Face"), ("B", "Lat"), ("C", "Contre"),
                    ("D", "Douche 1"), ("E", "Douche 2"), ("F", "Douche 3")]
        cur = list(getattr(clip, 'effect_target_groups', []))

        dlg = QDialog(self)
        dlg.setWindowTitle("Groupes ciblés")
        dlg.setFixedSize(380, 220)
        dlg.setStyleSheet("""
            QDialog { background:#1a1a1a; }
            QCheckBox {
                color:#e0e0e0; font-size:20px; font-weight:bold;
                spacing:6px;
            }
            QCheckBox::indicator { width:22px; height:22px; border-radius:4px; }
            QCheckBox::indicator:unchecked { background:#2a2a2a; border:1px solid #555; }
            QCheckBox::indicator:checked   { background:#00d4ff; border:1px solid #00d4ff; }
        """)
        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(20, 14, 20, 14)
        vl.setSpacing(10)

        lbl = QLabel("Sélectionne les groupes (vide = Tous)")
        lbl.setStyleSheet("color:#888; font-size:11px;")
        vl.addWidget(lbl)

        checks = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for i, (letter, group_name) in enumerate(_LETTERS):
            col = i % 3
            row_base = (i // 3) * 2

            cb = QCheckBox(letter)
            cb.setChecked(letter in cur)
            checks[letter] = cb
            grid.addWidget(cb, row_base, col, alignment=Qt.AlignHCenter)

            name_lbl = QLabel(group_name)
            name_lbl.setAlignment(Qt.AlignHCenter)
            name_lbl.setStyleSheet("color:#aaa; font-size:10px; font-weight:normal;")
            grid.addWidget(name_lbl, row_base + 1, col, alignment=Qt.AlignHCenter)

        vl.addLayout(grid)
        vl.addStretch()

        btns = QHBoxLayout()
        btn_all = QPushButton("Tous")
        btn_all.setStyleSheet("background:#2a2a2a;color:#e0e0e0;border:1px solid #444;border-radius:4px;padding:6px 12px;")
        btn_all.clicked.connect(lambda: [cb.setChecked(False) for cb in checks.values()])
        btns.addWidget(btn_all)
        btn_ok = QPushButton("OK")
        btn_ok.setStyleSheet("background:#00d4ff;color:#000;font-weight:bold;border-radius:4px;padding:6px 12px;")
        btn_ok.clicked.connect(dlg.accept)
        btns.addWidget(btn_ok)
        vl.addLayout(btns)

        if dlg.exec() == QDialog.Accepted:
            clip.effect_target_groups = [l for l, _ in _LETTERS if checks[l].isChecked()]
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()
            if hasattr(self.parent_editor, '_save_sequence_no_close'):
                self.parent_editor._save_sequence_no_close()

    def edit_clip_effect_speed(self, clip):
        """Dialog pour regler la vitesse de l'effet (0=lent, 100=rapide)"""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("lt_dlg_effect_speed_title"))
        dialog.setFixedSize(360, 210)
        dialog.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel { color: white; border: none; }
            QPushButton {
                background: #cccccc; color: black;
                border: 1px solid #999; border-radius: 6px;
                padding: 10px 20px; font-weight: bold;
            }
            QPushButton:hover { background: #00d4ff; }
            QSlider::groove:horizontal { background: #3a3a3a; height: 8px; border-radius: 4px; }
            QSlider::handle:horizontal {
                background: #00d4ff; width: 18px; height: 18px;
                margin: -5px 0; border-radius: 9px;
            }
            QSlider::sub-page:horizontal { background: #00d4ff; border-radius: 4px; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 25, 30, 20)
        layout.setSpacing(12)

        value_label = QLabel(tr("lt_speed_value", v=clip.effect_speed))
        value_label.setStyleSheet("color: white; font-size: 26px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)

        lbl_row = QHBoxLayout()
        lbl_slow = QLabel(tr("lt_speed_slow"))
        lbl_slow.setStyleSheet("color: #888; font-size: 11px;")
        lbl_fast = QLabel(tr("lt_speed_fast"))
        lbl_fast.setStyleSheet("color: #888; font-size: 11px;")
        lbl_row.addWidget(lbl_slow)
        lbl_row.addStretch()
        lbl_row.addWidget(lbl_fast)
        layout.addLayout(lbl_row)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(clip.effect_speed)
        slider.valueChanged.connect(lambda v: value_label.setText(tr("lt_speed_value", v=v)))
        layout.addWidget(slider)

        btn_layout = QHBoxLayout()
        cancel = QPushButton(tr("btn_cancel"))
        cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel)
        ok = QPushButton("OK")
        ok.clicked.connect(dialog.accept)
        ok.setStyleSheet("background: #00d4ff; color: black; font-weight: bold; padding: 10px 20px; border-radius: 6px;")
        btn_layout.addWidget(ok)
        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            clip.effect_speed = slider.value()
            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()
            if hasattr(self.parent_editor, '_save_sequence_no_close'):
                self.parent_editor._save_sequence_no_close()

    def delete_clip(self, clip):
        """Supprime le(s) clip(s)"""
        clips_to_delete = self.selected_clips if len(self.selected_clips) > 1 else [clip]

        for c in clips_to_delete:
            if c in self.clips:
                self.clips.remove(c)

        self.selected_clips.clear()
        self.update()

        # Sauvegarder APRES suppression
        if hasattr(self.parent_editor, 'save_state'):
            self.parent_editor.save_state()

    def cut_clip_in_two(self, clip):
        """Coupe un clip en deux parties egales"""
        if clip not in self.clips:
            return
        self.cut_clip_at_position(clip, clip.duration / 2)

    def cut_clip_at_position(self, clip, position_in_clip):
        """Coupe un clip a une position precise"""
        if clip not in self.clips:
            return

        min_duration = 200
        if position_in_clip < min_duration or position_in_clip > clip.duration - min_duration:
            print(f"⚠️ Position de coupe invalide: {position_in_clip:.0f}ms")
            return

        cut_point = clip.start_time + position_in_clip
        first_duration = position_in_clip
        second_duration = clip.duration - position_in_clip

        print(f"✂️ CUT: Clip {clip.start_time/1000:.2f}s → coupe a {cut_point/1000:.2f}s")

        clip.duration = first_duration

        new_clip = self.add_clip_direct(cut_point, second_duration, clip.color, clip.intensity)

        if clip.color2:
            new_clip.color2 = clip.color2
        new_clip.effect = clip.effect
        new_clip.effect_speed = clip.effect_speed
        new_clip.fade_out_duration = clip.fade_out_duration
        clip.fade_out_duration = 0

        self.update()
        print(f"   ✅ Clip coupe en 2 parties")

        # Sauvegarder APRES la coupe
        if hasattr(self.parent_editor, 'save_state'):
            self.parent_editor.save_state()

    def copy_clip_to_track(self, clip, target_track):
        """Copie le(s) clip(s) vers une autre piste"""
        clips_to_copy = self.selected_clips if len(self.selected_clips) > 1 else [clip]

        for source_clip in clips_to_copy:
            new_clip = target_track.add_clip(
                source_clip.start_time,
                source_clip.duration,
                source_clip.color,
                source_clip.intensity
            )

            if source_clip.color2:
                new_clip.color2 = source_clip.color2
            new_clip.fade_in_duration = source_clip.fade_in_duration
            new_clip.fade_out_duration = source_clip.fade_out_duration
            new_clip.effect = source_clip.effect
            new_clip.effect_speed = source_clip.effect_speed

        target_track.update()

    def add_clip_fade_in(self, clip):
        clip.fade_in_duration = 1000
        self.update()

    def add_clip_fade_out(self, clip):
        clip.fade_out_duration = 1000
        self.update()

    def clear_clip_fades(self, clip):
        clip.fade_in_duration = 0
        clip.fade_out_duration = 0
        self.update()

    def dragEnterEvent(self, event):
        mime = event.mimeData()

        # ── Multi-drag depuis la bibliothèque ─────────────────────────────
        if mime.hasFormat('application/x-multi-library'):
            types_raw = bytes(mime.data('application/x-multi-library-types')).decode() \
                        if mime.hasFormat('application/x-multi-library-types') else ''
            types = set(types_raw.split(',')) if types_raw else set()
            if self.is_effect_track:
                accepted = 'effect' in types
            elif self.is_sequence_track:
                accepted = 'memory' in types
            else:
                accepted = bool(types & {'color', 'bicolor'})
            if accepted:
                event.acceptProposedAction()
            else:
                event.ignore()
            self._drag_active = accepted
            self.update()
            return

        is_seq = mime.hasFormat('application/x-sequence')
        is_eff = mime.hasFormat('application/x-effect')
        accepted = False
        if self.is_effect_track:
            if is_eff:
                event.acceptProposedAction(); accepted = True
            else:
                event.ignore()
        elif self.is_sequence_track:
            if is_seq:
                event.acceptProposedAction(); accepted = True
            else:
                event.ignore()
        else:
            if not is_seq and mime.hasText():
                event.acceptProposedAction(); accepted = True
            else:
                event.ignore()
        self._drag_active = accepted
        self.update()

    def dragLeaveEvent(self, event):
        self._drag_active = False
        self.update()

    def dropEvent(self, event):
        """Drop d'une couleur, séquence ou effet sur la piste"""
        self._drag_active = False
        self.update()

        # ── Multi-drop depuis la bibliothèque ─────────────────────────────
        if event.mimeData().hasFormat('application/x-multi-library'):
            import json as _json
            raw   = bytes(event.mimeData().data('application/x-multi-library')).decode()
            items = _json.loads(raw)
            drop_x       = event.position().x() - 145
            current_time = max(0, drop_x / self.pixels_per_ms)

            for itd in items:
                typ = itd.get('type', '')
                val = itd.get('value', '')

                if typ in ('color', 'bicolor') and not self.is_sequence_track and not self.is_effect_track:
                    start = self.find_free_position(current_time, 5000)
                    if '#' in val:
                        c1h, c2h = val.split('#', 1)
                        clip = self.add_clip(start, 5000, QColor(c1h), 100)
                        clip.color2 = QColor(c2h)
                    else:
                        clip = self.add_clip(start, 5000, QColor(val), 100)
                    current_time = start + 5000

                elif typ == 'memory' and self.is_sequence_track:
                    parts = val.split(',', 3)
                    if len(parts) == 4:
                        mc, ri, label, chex = int(parts[0]), int(parts[1]), parts[2], parts[3]
                        start = self.find_free_position(current_time, 5000)
                        clip  = self.add_clip_direct(start, 5000, QColor(chex), 100)
                        clip.memory_ref   = (mc, ri)
                        clip.memory_label = label
                        current_time = start + 5000

                elif typ == 'effect' and self.is_effect_track:
                    eff = _json.loads(val)
                    start = self.find_free_position(current_time, 10_000)
                    clip  = self.add_clip(start, 10_000, QColor("#1a0a2e"), 100)
                    clip.effect_name   = eff.get('name', '')
                    clip.effect_type   = eff.get('type', '')
                    clip.effect_layers = eff.get('layers', [])
                    current_time = start + 10_000

            self.update()
            if hasattr(self.parent_editor, 'save_state'):
                self.parent_editor.save_state()
            event.acceptProposedAction()
            return

        # ── Drop effet sur piste Effet ──────────────────────────────────
        if self.is_effect_track and event.mimeData().hasFormat('application/x-effect'):
            import json as _json
            raw = bytes(event.mimeData().data('application/x-effect')).decode()
            try:
                data = _json.loads(raw)
            except Exception:
                data = {}
            eff_name = data.get("name", "")
            if eff_name:
                drop_x    = event.position().x() - 145
                click_time = max(0, drop_x / self.pixels_per_ms)
                sorted_clips = sorted(self.clips, key=lambda c: c.start_time)
                gap_start, gap_end = 0, self.total_duration
                for c in sorted_clips:
                    if c.start_time + c.duration <= click_time:
                        gap_start = c.start_time + c.duration
                    elif c.start_time >= click_time:
                        gap_end = c.start_time
                        break
                gap_duration = gap_end - gap_start
                if gap_duration > 100:
                    clip_duration = min(gap_duration, 10_000)
                    clip = self.add_clip(gap_start, clip_duration, QColor("#1a0a2e"), 100)
                    clip.effect_name   = eff_name
                    clip.effect_type   = data.get("type", "")
                    clip.effect_layers = data.get("layers", [])
                    self.update()
                    if hasattr(self.parent_editor, 'save_state'):
                        self.parent_editor.save_state()
            event.acceptProposedAction()
            return

        # ── Drop séquence AKAI ──────────────────────────────────────────
        if self.is_sequence_track and event.mimeData().hasFormat('application/x-sequence'):
            raw = bytes(event.mimeData().data('application/x-sequence')).decode()
            parts = raw.split(',', 3)
            if len(parts) == 4:
                mem_col, row = int(parts[0]), int(parts[1])
                label, color_hex = parts[2], parts[3]
                drop_x = event.position().x() - 145
                start_time = max(0, drop_x / self.pixels_per_ms)
                start_time = self.find_free_position(start_time, 5000)
                clip = self.add_clip_direct(start_time, 5000, QColor(color_hex), 100)
                clip.memory_ref = (mem_col, row)
                clip.memory_label = label
                self.update()
                if hasattr(self.parent_editor, 'save_state'):
                    self.parent_editor.save_state()
            event.acceptProposedAction()
            return

        # ── Drop couleur (pistes normales) ──────────────────────────────
        color_data = event.mimeData().text()

        drop_x = event.position().x() - 145
        start_time = max(0, drop_x / self.pixels_per_ms)
        clip_duration = 5000

        start_time = self.find_free_position(start_time, clip_duration)

        if '#' in color_data and color_data.count('#') >= 2:
            parts = color_data.split('#')
            parts = [p for p in parts if p]

            if len(parts) >= 2:
                color1 = QColor('#' + parts[0])
                color2 = QColor('#' + parts[1])

                if color1.isValid() and color2.isValid():
                    clip = self.add_clip(start_time, clip_duration, color1, 100)
                    clip.color2 = color2
                    self.update()
        else:
            color = QColor(color_data)
            self.add_clip(start_time, 5000, color, 100)

        if hasattr(self.parent_editor, 'save_state'):
            self.parent_editor.save_state()

        event.acceptProposedAction()

    def add_clip(self, start_time, duration, color, intensity):
        """Ajoute un clip avec anti-collision"""
        free_start = self.find_free_position(start_time, duration)
        clip = LightClip(free_start, duration, color, intensity, self)
        self.clips.append(clip)
        self.update()
        return clip

    def add_clip_direct(self, start_time, duration, color, intensity):
        """Ajoute un clip SANS anti-collision"""
        clip = LightClip(start_time, duration, color, intensity, self)
        self.clips.append(clip)
        self.update()
        return clip

    def update_clips(self):
        """Met a jour la position/taille de tous les clips"""
        for clip in self.clips:
            x = 145 + int(clip.start_time * self.pixels_per_ms)
            width = int(clip.duration * self.pixels_per_ms)
            clip.x_pos = x
            clip.width_val = max(20, width)
        self.update()

    def update_zoom(self, pixels_per_ms):
        """Met a jour le zoom"""
        self.pixels_per_ms = pixels_per_ms
        total_width = 145 + int(self.total_duration * pixels_per_ms) + 50
        self.setMinimumWidth(total_width)
        self.update_clips()
        self.update()

    def set_zoom(self, pixels_per_ms):
        """Change le niveau de zoom"""
        self.pixels_per_ms = pixels_per_ms
        self.update_clips()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        # Barre accent coloree (5px, cote gauche, hauteur totale de la piste)
        bar_color = QColor(self.track_color)
        bar_color.setAlpha(220)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bar_color))
        painter.drawRect(0, 0, 5, self.height())

        # Separateur haut de piste
        painter.setPen(QPen(QColor("#3a3a3a"), 1))
        painter.drawLine(0, 0, self.width(), 0)

        if self._collapsed:
            # Afficher juste le nom en mode reduit
            painter.setPen(QColor("#888"))
            font = painter.font()
            font.setBold(True)
            font.setPixelSize(11)
            painter.setFont(font)
            painter.drawText(11, 0, 130, 26, Qt.AlignVCenter, self.name)
            return

        # === FORME D'ONDE ===
        if self.waveform_data:
            timeline_width_px = int(self.total_duration * self.pixels_per_ms)
            pixels_per_sample = timeline_width_px / len(self.waveform_data) if self.waveform_data else 1
            y_center = self.height() // 2

            visible_start = max(0, int((0 - 145) / pixels_per_sample))
            visible_end = min(len(self.waveform_data),
                              int((self.width() + 10 - 145) / pixels_per_sample) + 1)

            if self.name == "Audio":
                # ── Piste Audio : waveform pixel-parfaite (1 valeur / pixel) ──
                try:
                    max_height = (self.height() // 2) - 4

                    # Plage visible exacte via clip rect (scroll pris en compte)
                    clip = event.rect()
                    px_start = max(145, clip.left())
                    px_end   = min(self.width(), clip.right() + 1)

                    if px_end > px_start:
                        amps = []
                        xs   = []
                        data = self.waveform_data
                        n    = len(data)

                        for px in range(px_start, px_end):
                            sample_pos = (px - 145) / pixels_per_sample
                            if sample_pos < 0:
                                continue

                            if pixels_per_sample >= 1.0:
                                # Zoom avant : interpolation lineaire entre samples
                                i    = int(sample_pos)
                                frac = sample_pos - i
                                if i + 1 < n:
                                    amp = data[i] * (1.0 - frac) + data[i + 1] * frac
                                elif i < n:
                                    amp = data[i]
                                else:
                                    break
                            else:
                                # Zoom arriere : peak de tous les samples du pixel
                                i0 = max(0, int(sample_pos))
                                i1 = min(n, int((px + 1 - 145) / pixels_per_sample) + 1)
                                if i0 >= n:
                                    break
                                amp = max(data[i0:i1]) if i0 < i1 else 0.0

                            amps.append(float(amp))
                            xs.append(float(px))

                        if len(xs) >= 2:
                            # ── Polygone précis (lineTo : pas de lissage artificiel) ──
                            painter.setRenderHint(QPainter.Antialiasing, False)

                            path_top = QPainterPath()
                            path_top.moveTo(xs[0], float(y_center))
                            for x, a in zip(xs, amps):
                                path_top.lineTo(x, y_center - max(1.0, a * max_height))
                            path_top.lineTo(xs[-1], float(y_center))
                            path_top.closeSubpath()

                            path_bot = QPainterPath()
                            path_bot.moveTo(xs[0], float(y_center))
                            for x, a in zip(xs, amps):
                                path_bot.lineTo(x, y_center + max(1.0, a * max_height))
                            path_bot.lineTo(xs[-1], float(y_center))
                            path_bot.closeSubpath()

                            # Gradient haut : sombre centre → cyan → blanc aux peaks
                            grad_top = QLinearGradient(0, y_center, 0, y_center - max_height)
                            grad_top.setColorAt(0.00, QColor(3,   18,  36, 210))
                            grad_top.setColorAt(0.18, QColor(0,   52, 112, 228))
                            grad_top.setColorAt(0.42, QColor(0,  130, 192, 244))
                            grad_top.setColorAt(0.68, QColor(0,  200, 246, 255))
                            grad_top.setColorAt(0.86, QColor(80, 228, 255, 255))
                            grad_top.setColorAt(1.00, QColor(185, 247, 255, 255))

                            # Gradient bas : miroir légèrement plus froid
                            grad_bot = QLinearGradient(0, y_center, 0, y_center + max_height)
                            grad_bot.setColorAt(0.00, QColor(3,   18,  36, 210))
                            grad_bot.setColorAt(0.18, QColor(0,   42, 100, 218))
                            grad_bot.setColorAt(0.42, QColor(0,  102, 175, 234))
                            grad_bot.setColorAt(0.68, QColor(0,  162, 220, 248))
                            grad_bot.setColorAt(0.86, QColor(50, 196, 242, 255))
                            grad_bot.setColorAt(1.00, QColor(135, 228, 255, 255))

                            painter.setPen(Qt.NoPen)
                            painter.setBrush(QBrush(grad_top))
                            painter.drawPath(path_top)
                            painter.setBrush(QBrush(grad_bot))
                            painter.drawPath(path_bot)

                            # Glow ligne centrale (4 passes concentriques)
                            x0, x1 = int(xs[0]), int(xs[-1])
                            painter.setBrush(Qt.NoBrush)
                            for pen_w, alpha in ((14, 10), (8, 26), (4, 60), (1, 180)):
                                painter.setPen(QPen(QColor(0, 218, 255, alpha), pen_w))
                                painter.drawLine(x0, y_center, x1, y_center)

                            # Contours précis haut + bas (antialiasing léger pour le polish)
                            painter.setRenderHint(QPainter.Antialiasing, True)
                            painter.setBrush(Qt.NoBrush)
                            painter.setOpacity(0.55)

                            edge_t = QPainterPath()
                            edge_t.moveTo(xs[0], y_center - max(1.0, amps[0] * max_height))
                            for x, a in zip(xs[1:], amps[1:]):
                                edge_t.lineTo(x, y_center - max(1.0, a * max_height))
                            painter.setPen(QPen(QColor(155, 235, 255), 1.2))
                            painter.drawPath(edge_t)

                            edge_b = QPainterPath()
                            edge_b.moveTo(xs[0], y_center + max(1.0, amps[0] * max_height))
                            for x, a in zip(xs[1:], amps[1:]):
                                edge_b.lineTo(x, y_center + max(1.0, a * max_height))
                            painter.setPen(QPen(QColor(110, 210, 250), 1.0))
                            painter.drawPath(edge_b)

                            painter.setOpacity(1.0)

                except Exception as e:
                    print(f"❌ ERREUR paintEvent Audio: {e}")
                    import traceback
                    traceback.print_exc()

            else:
                # ── Pistes lumiere : barres colorées selon la couleur de piste ──
                max_h = max(4, (self.height() // 2) - 10)
                tc = self.track_color
                n_vis = max(1, visible_end - visible_start)
                SKIP = max(1, n_vis // max(1, self.width() - 145))

                painter.setRenderHint(QPainter.Antialiasing, False)
                painter.setPen(Qt.NoPen)
                for i in range(visible_start, visible_end, SKIP):
                    end_i = min(i + SKIP, len(self.waveform_data))
                    amp = max(self.waveform_data[i:end_i])
                    if amp < 0.04:
                        continue
                    h = max(1, int(amp * max_h))
                    x = int(145 + i * pixels_per_sample)
                    bar_w = max(1, int(pixels_per_sample * SKIP))
                    alpha = int(22 + amp * 52)
                    painter.setBrush(QBrush(QColor(tc.red(), tc.green(), tc.blue(), alpha)))
                    painter.drawRect(x, y_center - h, bar_w, h * 2)
                painter.setRenderHint(QPainter.Antialiasing, True)

        # Grille temporelle - seulement les lignes visibles
        if self.pixels_per_ms > 0:
            visible_left  = event.rect().left()
            visible_right = event.rect().right()
            sec_start = max(0, int((visible_left  - 145) / (1000 * self.pixels_per_ms)))
            sec_end   =        int((visible_right - 145) / (1000 * self.pixels_per_ms)) + 2
            painter.setPen(QPen(QColor("#2a2a2a"), 1, Qt.SolidLine))
            for sec in range(sec_start, sec_end):
                x = 145 + int(sec * 1000 * self.pixels_per_ms)
                if 145 <= x <= self.width():
                    painter.drawLine(x, 0, x, self.height())

        # === DESSINER LES CLIPS ===
        painter.setRenderHint(QPainter.Antialiasing)
        _ev_left  = event.rect().left()
        _ev_right = event.rect().right()
        for clip in self.clips:
            x = 145 + int(clip.start_time * self.pixels_per_ms)
            width = int(clip.duration * self.pixels_per_ms)
            # Ignorer les clips entièrement hors de la zone visible
            if x + max(20, width) < _ev_left or x > _ev_right:
                continue
            y = 10
            height = 40

            clip_rect = QRect(x, y, max(20, width), height)

            if getattr(self, 'is_effect_track', False):
                # ── Clip d'effet (piste Effet) ─────────────────────────
                ACCENT = QColor("#cc44ff")
                path = QPainterPath()
                path.addRoundedRect(clip_rect.x(), clip_rect.y(), clip_rect.width(), clip_rect.height(), 5, 5)
                painter.setClipPath(path)

                # Fond sombre violet
                painter.fillRect(clip_rect, QColor("#1a0a2e"))
                grad = QLinearGradient(float(clip_rect.left()), 0, float(clip_rect.right()), 0)
                grad.setColorAt(0.0, QColor(180, 60, 255, 70))
                grad.setColorAt(1.0, QColor(180, 60, 255, 15))
                painter.fillRect(clip_rect, QBrush(grad))

                # Barre d'accent gauche
                painter.fillRect(QRect(clip_rect.left(), clip_rect.top(), 5, clip_rect.height()), ACCENT)

                painter.setClipRect(self.rect())
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(150, 30, 200, 180), 1))
                painter.drawRoundedRect(clip_rect, 5, 5)

                if width > 30:
                    # Retrouver l'emoji depuis BUILTIN_EFFECTS (cache module-level)
                    eff_name = getattr(clip, 'effect_name', '') or ''
                    eff_emoji = '✨'
                    try:
                        for _e in _get_builtin_effects():
                            if _e.get('name') == eff_name:
                                eff_emoji = _e.get('emoji', '✨')
                                break
                    except Exception:
                        pass
                    font = painter.font()
                    font.setBold(True)
                    font.setPixelSize(13)
                    painter.setFont(font)
                    tgt = getattr(clip, 'effect_target_groups', [])
                    grp_str = (" [" + ",".join(tgt) + "]") if tgt else ""
                    spd = getattr(clip, 'effect_speed', 50)
                    spd_str = f"  {spd}%" if spd != 50 else ""
                    painter.setPen(QColor(230, 200, 255, 230))
                    painter.drawText(clip_rect.adjusted(10, 0, -4, 0),
                                     Qt.AlignVCenter | Qt.AlignLeft,
                                     f"{eff_emoji}  {eff_name}{grp_str}{spd_str}" if eff_name else "✨  Effet")

            elif getattr(clip, 'memory_ref', None):
                # ── Clip de séquence AKAI ──────────────────────────────
                accent = clip.color   # couleur dominante de la mémoire
                path = QPainterPath()
                path.addRoundedRect(clip_rect.x(), clip_rect.y(), clip_rect.width(), clip_rect.height(), 5, 5)
                painter.setClipPath(path)

                # Fond sombre avec léger dégradé de la couleur accent
                grad = QLinearGradient(float(clip_rect.left()), 0, float(clip_rect.right()), 0)
                a = QColor(accent); a.setAlpha(80)
                b = QColor(accent); b.setAlpha(20)
                grad.setColorAt(0.0, a)
                grad.setColorAt(1.0, b)
                painter.fillRect(clip_rect, QColor("#111111"))
                painter.fillRect(clip_rect, QBrush(grad))

                # Barre colorée à gauche (identifiant visuel)
                painter.fillRect(QRect(clip_rect.left(), clip_rect.top(), 5, clip_rect.height()), accent)

                painter.setClipRect(self.rect())
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(accent.darker(150), 1))
                painter.drawRoundedRect(clip_rect, 5, 5)

                if width > 30:
                    font = painter.font()
                    font.setBold(True)
                    font.setPixelSize(13)
                    painter.setFont(font)
                    painter.setPen(QColor(255, 255, 255, 220))
                    lbl = getattr(clip, 'memory_label', '') or '⚡'
                    painter.drawText(clip_rect.adjusted(8, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, f"⚡ {lbl}")
            elif clip.color2:
                # ── Bicolore premium ──────────────────────────────────
                r = 5
                path = QPainterPath()
                path.addRoundedRect(float(clip_rect.x()), float(clip_rect.y()),
                                    float(clip_rect.width()), float(clip_rect.height()), r, r)
                painter.setClipPath(path)

                mid = clip_rect.left() + clip_rect.width() // 2
                # Moitié gauche
                left_r = QRect(clip_rect.left(), clip_rect.top(), clip_rect.width() // 2, clip_rect.height())
                painter.fillRect(left_r, clip.color)
                # Moitié droite
                right_r = QRect(mid, clip_rect.top(), clip_rect.width() - clip_rect.width() // 2, clip_rect.height())
                painter.fillRect(right_r, clip.color2)
                # Ligne séparatrice
                painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
                painter.drawLine(mid, clip_rect.top(), mid, clip_rect.bottom())

                # Gradient brillance commun (haut → bas)
                grad = QLinearGradient(0.0, float(clip_rect.top()), 0.0, float(clip_rect.bottom()))
                grad.setColorAt(0.0,  QColor(255, 255, 255, 65))
                grad.setColorAt(0.45, QColor(255, 255, 255, 0))
                grad.setColorAt(1.0,  QColor(0,   0,   0,  50))
                painter.fillRect(clip_rect, QBrush(grad))

                # Shine coin haut-gauche
                shine_w = min(clip_rect.width() // 2, int(clip_rect.width() * 0.55))
                shine_h = int(clip_rect.height() * 0.5)
                shine = QLinearGradient(float(clip_rect.left()), float(clip_rect.top()),
                                        float(clip_rect.left() + shine_w), float(clip_rect.top() + shine_h))
                shine.setColorAt(0.0, QColor(255, 255, 255, 75))
                shine.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillRect(QRect(clip_rect.left(), clip_rect.top(), shine_w, shine_h), QBrush(shine))

                painter.setClipRect(self.rect())
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
                painter.drawRoundedRect(clip_rect, r, r)
            else:
                # ── Couleur simple premium ────────────────────────────
                r = 5
                path = QPainterPath()
                path.addRoundedRect(float(clip_rect.x()), float(clip_rect.y()),
                                    float(clip_rect.width()), float(clip_rect.height()), r, r)
                painter.setClipPath(path)

                # Fond couleur
                painter.fillRect(clip_rect, clip.color)

                # Gradient brillance (haut → bas)
                grad = QLinearGradient(0.0, float(clip_rect.top()), 0.0, float(clip_rect.bottom()))
                grad.setColorAt(0.0,  QColor(255, 255, 255, 65))
                grad.setColorAt(0.45, QColor(255, 255, 255, 0))
                grad.setColorAt(1.0,  QColor(0,   0,   0,  50))
                painter.fillRect(clip_rect, QBrush(grad))

                # Shine coin haut-gauche
                shine_w = int(clip_rect.width() * 0.55)
                shine_h = int(clip_rect.height() * 0.5)
                shine = QLinearGradient(float(clip_rect.left()), float(clip_rect.top()),
                                        float(clip_rect.left() + shine_w), float(clip_rect.top() + shine_h))
                shine.setColorAt(0.0, QColor(255, 255, 255, 75))
                shine.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillRect(QRect(clip_rect.left(), clip_rect.top(), shine_w, shine_h), QBrush(shine))

                painter.setClipRect(self.rect())
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
                painter.drawRoundedRect(clip_rect, r, r)

            if not getattr(self, 'is_effect_track', False) and not getattr(clip, 'memory_ref', None) and width > 40:
                luminance = (clip.color.red() * 0.299 + clip.color.green() * 0.587 + clip.color.blue() * 0.114)
                txt_color = QColor(0, 0, 0, 200) if luminance > 140 else QColor(255, 255, 255, 220)
                painter.setPen(txt_color)

                font = painter.font()
                font.setBold(True)
                font.setPixelSize(13)
                painter.setFont(font)
                text = f"{clip.intensity}%"
                if clip.effect:
                    text += f" • {clip.effect}"
                painter.drawText(clip_rect, Qt.AlignCenter, text)

            # Indicateur mouvement Pan/Tilt (piste Lyres)
            has_move = (clip.move_effect or
                        clip.pan_start != clip.pan_end or
                        clip.tilt_start != clip.tilt_end)
            if has_move and width > 20:
                painter.save()
                painter.setClipRect(clip_rect.adjusted(2, 2, -2, -2))
                if clip.move_effect:
                    # Icône de l'effet
                    icons = {"cercle":"⭕","figure8":"∞","balayage_h":"↔",
                             "balayage_v":"↕","aleatoire":"✦"}
                    icon_txt = icons.get(clip.move_effect, "↺")
                    f2 = painter.font(); f2.setPixelSize(11); painter.setFont(f2)
                    painter.setPen(QColor(255, 220, 100, 200))
                    painter.drawText(clip_rect.adjusted(3, 0, -3, -2),
                                     Qt.AlignBottom | Qt.AlignLeft, icon_txt)
                else:
                    # Flèche de trajectoire
                    sx = clip_rect.left()  + 4
                    ex = clip_rect.right() - 4
                    h  = clip_rect.height()
                    sy = clip_rect.top() + int((clip.tilt_start / 255.0) * h)
                    ey = clip_rect.top() + int((clip.tilt_end   / 255.0) * h)
                    sy = max(clip_rect.top() + 3, min(clip_rect.bottom() - 3, sy))
                    ey = max(clip_rect.top() + 3, min(clip_rect.bottom() - 3, ey))
                    painter.setPen(QPen(QColor(255, 220, 100, 180), 2))
                    painter.drawLine(sx, sy, ex, ey)
                    # Tête de flèche
                    ang = math.atan2(ey - sy, ex - sx)
                    for da in (0.4, -0.4):
                        ax = int(ex - 7 * math.cos(ang + da))
                        ay = int(ey - 7 * math.sin(ang + da))
                        painter.drawLine(ex, ey, ax, ay)
                painter.restore()

            # Fades - couleur adaptee selon luminance du clip
            fade_in_px = int(clip.fade_in_duration * self.pixels_per_ms) if clip.fade_in_duration > 0 else 0
            fade_out_px = int(clip.fade_out_duration * self.pixels_per_ms) if clip.fade_out_duration > 0 else 0

            clip_lum = clip.color.red() * 0.299 + clip.color.green() * 0.587 + clip.color.blue() * 0.114
            is_bright = clip_lum > 180
            fade_fill = QColor(0, 0, 0, 120) if is_bright else QColor(255, 255, 255, 100)
            fade_line = QColor(0, 0, 0) if is_bright else QColor(255, 255, 255)
            fade_handle = QColor(80, 80, 80) if is_bright else QColor(0, 0, 0)

            if fade_in_px > 5:
                painter.setBrush(fade_fill)
                painter.setPen(Qt.NoPen)
                painter.drawPolygon(QPolygon([
                    QPoint(clip_rect.left(), clip_rect.top()),
                    QPoint(clip_rect.left() + fade_in_px, clip_rect.top()),
                    QPoint(clip_rect.left(), clip_rect.bottom())
                ]))
                painter.setPen(QPen(fade_line, 3))
                painter.drawLine(clip_rect.left() + fade_in_px, clip_rect.top(), clip_rect.left(), clip_rect.bottom())
                painter.setPen(QPen(fade_handle, 5))
                painter.drawLine(clip_rect.left() + fade_in_px, clip_rect.top() + 5, clip_rect.left() + fade_in_px, clip_rect.bottom() - 5)

            if fade_out_px > 5:
                painter.setBrush(fade_fill)
                painter.setPen(Qt.NoPen)
                painter.drawPolygon(QPolygon([
                    QPoint(clip_rect.right() - fade_out_px, clip_rect.top()),
                    QPoint(clip_rect.right(), clip_rect.top()),
                    QPoint(clip_rect.right(), clip_rect.bottom())
                ]))
                painter.setPen(QPen(fade_line, 3))
                painter.drawLine(clip_rect.right() - fade_out_px, clip_rect.top(), clip_rect.right(), clip_rect.bottom())
                painter.setPen(QPen(fade_handle, 5))
                painter.drawLine(clip_rect.right() - fade_out_px, clip_rect.top() + 5, clip_rect.right() - fade_out_px, clip_rect.bottom() - 5)

            # Selection
            if clip in self.selected_clips:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor("#00d4ff"), 3))
                painter.drawRoundedRect(clip_rect, 6, 6)

        # Curseur de lecture
        if hasattr(self.parent_editor, 'playback_position'):
            cursor_x = 145 + int(self.parent_editor.playback_position * self.pixels_per_ms)
            if 145 <= cursor_x < self.width():
                painter.setPen(QPen(QColor("#ff0000"), 3))
                painter.drawLine(cursor_x, 0, cursor_x, self.height())

        # Ligne de magnétisme
        if self._snap_active and 145 <= self._snap_x < self.width():
            pen = QPen(QColor("#ffdd00"), 1, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(self._snap_x, 0, self._snap_x, self.height())

        # Surlignage drop zone (drag depuis bibliothèque)
        if self._drag_active:
            painter.fillRect(self.rect(), QColor(0, 220, 80, 28))
            painter.setPen(QPen(QColor(0, 220, 80, 200), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(1, 1, self.width() - 2, self.height() - 2)

        painter.end()

    def get_clips_data(self):
        """Retourne les donnees des clips pour sauvegarde"""
        return [
            {
                'start': clip.start_time,
                'duration': clip.duration,
                'color': clip.color.name(),
                'color2': clip.color2.name() if clip.color2 else None,
                'intensity': clip.intensity,
                'fade_in': clip.fade_in_duration,
                'fade_out': clip.fade_out_duration,
                'effect': clip.effect,
                'effect_speed': clip.effect_speed,
                'track': self.name
            }
            for clip in self.clips
        ]


# Ce contenu sera appendé à light_timeline.py

class MovementEditorDialog(QDialog):
    """Éditeur de mouvement Pan/Tilt pour un clip de la piste Lyres."""

    _DIALOG_STYLE = """
        QDialog, QWidget { background: #1a1a1a; color: #cccccc; }
        QLabel { color: #cccccc; border: none; background: transparent; }
        QTabWidget::pane { border: 1px solid #333; background: #111; }
        QTabBar::tab { background: #222; color: #888; padding: 6px 14px;
                       border: 1px solid #333; border-bottom: none; border-radius: 4px 4px 0 0; }
        QTabBar::tab:selected { background: #1a1a1a; color: #00d4ff; }
        QPushButton { background: #2a2a2a; color: #ccc; border: 1px solid #444;
                      border-radius: 4px; padding: 6px 16px; }
        QPushButton:hover { background: #333; color: white; }
        QPushButton:checked { background: #005577; color: #00d4ff; border-color: #00d4ff; }
        QSlider::groove:horizontal { background: #333; height: 6px; border-radius: 3px; }
        QSlider::handle:horizontal { background: #00d4ff; width: 14px; height: 14px;
                                      margin: -4px 0; border-radius: 7px; }
        QSlider::sub-page:horizontal { background: #005577; border-radius: 3px; }
        QSpinBox { background: #222; color: #ccc; border: 1px solid #444;
                   border-radius: 4px; padding: 3px; min-width: 55px; }
    """

    _EFFECTS = [
        ("⭕", "cercle",     "Cercle"),
        ("∞",  "figure8",   "Figure 8"),
        ("↔",  "balayage_h","Balayage H"),
        ("↕",  "balayage_v","Balayage V"),
        ("✦",  "aleatoire", "Aléatoire"),
    ]

    def __init__(self, clip, parent=None):
        super().__init__(parent)
        self.clip = clip
        self.setWindowTitle(tr("lt_dlg_movement_title"))
        self.setFixedSize(480, 400)
        self.setStyleSheet(self._DIALOG_STYLE)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        tabs = QTabWidget()
        root.addWidget(tabs)

        # ── Onglet Trajectoire ──────────────────────────────────────────
        traj_tab = QWidget()
        traj_tab.setAttribute(Qt.WA_StyledBackground, True)
        tl = QVBoxLayout(traj_tab)
        tl.setContentsMargins(12, 12, 12, 12)
        tl.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(10)

        def _pad(pan, tilt):
            """Mini PanTiltPad 160×130."""
            from plan_de_feu import PanTiltPad
            return PanTiltPad(pan=pan, tilt=tilt)

        # Départ
        grid.addWidget(QLabel(tr("lt_move_start_pos")), 0, 0, Qt.AlignCenter)
        self._pad_start = _pad(self.clip.pan_start, self.clip.tilt_start)
        grid.addWidget(self._pad_start, 1, 0, Qt.AlignCenter)

        arrow = QLabel("→")
        arrow.setStyleSheet("color:#00d4ff; font-size:24px;")
        arrow.setAlignment(Qt.AlignCenter)
        grid.addWidget(arrow, 1, 1)

        # Arrivée
        grid.addWidget(QLabel(tr("lt_move_end_pos")), 0, 2, Qt.AlignCenter)
        self._pad_end = _pad(self.clip.pan_end, self.clip.tilt_end)
        grid.addWidget(self._pad_end, 1, 2, Qt.AlignCenter)

        tl.addLayout(grid)

        # Bouton "Même position"
        same_btn = QPushButton(tr("lt_move_same_pos"))
        same_btn.clicked.connect(self._same_position)
        tl.addWidget(same_btn)

        tabs.addTab(traj_tab, tr("lt_tab_trajectory"))

        # ── Onglet Effet auto ────────────────────────────────────────────
        eff_tab = QWidget()
        eff_tab.setAttribute(Qt.WA_StyledBackground, True)
        el = QVBoxLayout(eff_tab)
        el.setContentsMargins(12, 12, 12, 12)
        el.setSpacing(12)

        # Boutons effets
        eff_row = QHBoxLayout()
        eff_row.setSpacing(6)
        self._eff_btns = {}
        none_btn = QPushButton(tr("lt_move_none"))
        none_btn.setCheckable(True)
        none_btn.setChecked(self.clip.move_effect is None)
        none_btn.clicked.connect(lambda: self._select_effect(None))
        eff_row.addWidget(none_btn)
        self._eff_btns[None] = none_btn

        for icon, key, label in self._EFFECTS:
            btn = QPushButton(f"{icon} {label}")
            btn.setCheckable(True)
            btn.setChecked(self.clip.move_effect == key)
            btn.clicked.connect(lambda _, k=key: self._select_effect(k))
            eff_row.addWidget(btn)
            self._eff_btns[key] = btn
        el.addLayout(eff_row)

        # Vitesse
        spd_row = QHBoxLayout()
        spd_lbl = QLabel(tr("lt_move_speed"))
        spd_lbl.setFixedWidth(55)
        self._spd_slider = QSlider(Qt.Horizontal)
        self._spd_slider.setRange(1, 30)
        self._spd_slider.setValue(int(self.clip.move_speed * 10))
        self._spd_val = QLabel(f"{self.clip.move_speed:.1f} Hz")
        self._spd_val.setFixedWidth(44)
        self._spd_slider.valueChanged.connect(
            lambda v: self._spd_val.setText(f"{v/10:.1f} Hz"))
        spd_row.addWidget(spd_lbl)
        spd_row.addWidget(self._spd_slider)
        spd_row.addWidget(self._spd_val)
        el.addLayout(spd_row)

        # Amplitude
        amp_row = QHBoxLayout()
        amp_lbl = QLabel(tr("lt_move_amplitude"))
        amp_lbl.setFixedWidth(55)
        self._amp_slider = QSlider(Qt.Horizontal)
        self._amp_slider.setRange(5, 120)
        self._amp_slider.setValue(self.clip.move_amplitude)
        self._amp_val = QLabel(str(self.clip.move_amplitude))
        self._amp_val.setFixedWidth(44)
        self._amp_slider.valueChanged.connect(
            lambda v: self._amp_val.setText(str(v)))
        amp_row.addWidget(amp_lbl)
        amp_row.addWidget(self._amp_slider)
        amp_row.addWidget(self._amp_val)
        el.addLayout(amp_row)

        # Centre de l'effet
        ctr_row = QHBoxLayout()
        ctr_row.setSpacing(16)
        ctr_row.addWidget(QLabel(tr("lt_move_center_pan")))
        self._ctr_pan = QSpinBox()
        self._ctr_pan.setRange(0, 255)
        self._ctr_pan.setValue(self.clip.pan_start)
        ctr_row.addWidget(self._ctr_pan)
        ctr_row.addWidget(QLabel(tr("lt_move_center_tilt")))
        self._ctr_tilt = QSpinBox()
        self._ctr_tilt.setRange(0, 255)
        self._ctr_tilt.setValue(self.clip.tilt_start)
        ctr_row.addWidget(self._ctr_tilt)
        ctr_row.addStretch()
        el.addLayout(ctr_row)
        el.addStretch()

        tabs.addTab(eff_tab, tr("lt_tab_auto_effect"))

        # Sélectionner l'onglet actif
        tabs.setCurrentIndex(1 if self.clip.move_effect else 0)

        # ── Boutons OK/Annuler ──────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton(tr("btn_cancel"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(tr("lt_btn_apply"))
        ok.setStyleSheet("QPushButton{background:#005577;color:#00d4ff;border:1px solid #00d4ff;border-radius:4px;padding:6px 20px;font-weight:bold;} QPushButton:hover{background:#006688;}")
        ok.clicked.connect(self._apply)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        root.addLayout(btn_row)

    def _select_effect(self, key):
        for k, b in self._eff_btns.items():
            b.setChecked(k == key)

    def _same_position(self):
        pan = self._pad_start._pan
        tilt = self._pad_start._tilt
        self._pad_end.set_values(pan, tilt)

    def _current_effect(self):
        for k, b in self._eff_btns.items():
            if b.isChecked():
                return k
        return None

    def _apply(self):
        self.clip.pan_start    = self._pad_start._pan
        self.clip.tilt_start   = self._pad_start._tilt
        self.clip.pan_end      = self._pad_end._pan
        self.clip.tilt_end     = self._pad_end._tilt
        self.clip.move_effect  = self._current_effect()
        self.clip.move_speed   = self._spd_slider.value() / 10.0
        self.clip.move_amplitude = self._amp_slider.value()
        # Centre de l'effet = pad_start quand effet auto
        if self.clip.move_effect:
            self.clip.pan_start  = self._ctr_pan.value()
            self.clip.tilt_start = self._ctr_tilt.value()
        self.accept()
