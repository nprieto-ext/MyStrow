"""
Plan de Feu - Visualisation des projecteurs (canvas 2D libre)
"""
import math
import json
import os
import time as _time
from i18n import tr
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QGridLayout, QHBoxLayout,
    QLabel, QMenu, QWidgetAction, QPushButton, QSlider,
    QDialog, QTabWidget, QListWidget, QListWidgetItem, QSplitter,
    QFormLayout, QLineEdit, QComboBox, QSpinBox, QDialogButtonBox,
    QMessageBox, QSizePolicy, QApplication, QStackedWidget
)
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRect, QSize, Signal, QRectF
from PySide6.QtGui import (
    QColor, QFont, QImage, QPainter, QPen, QBrush, QPainterPath, QPolygon,
    QLinearGradient, QRadialGradient, QCursor, QMouseEvent,
)


import math as _math_eff

# ─────────────────────────────────────────────────────────────────────────────
# EFFETS AUTOMATIQUES MOVING HEAD
# ─────────────────────────────────────────────────────────────────────────────

class _EffectState:
    """État d'un effet automatique Pan/Tilt sur une fixture."""

    DT = 0.1  # secondes (timer 100 ms)

    def __init__(self, effect, speed, amplitude, center_pan, center_tilt):
        self.effect       = effect        # "cercle","figure8","balayage_h","balayage_v","aleatoire"
        self.speed        = speed         # Hz (0.1 – 3.0)
        self.amplitude    = amplitude     # 0-120
        self.center_pan   = center_pan
        self.center_tilt  = center_tilt
        self.phase        = 0.0           # radians
        # Pour l'effet aléatoire
        self._r_pan   = float(center_pan)
        self._r_tilt  = float(center_tilt)
        self._r_tpan  = float(center_pan)
        self._r_ttilt = float(center_tilt)
        self._r_steps = 1
        self._r_step  = 0

    def tick(self):
        """Avance la phase et retourne (pan, tilt) clampé 0-255."""
        import random
        self.phase += 2 * _math_eff.pi * self.speed * self.DT
        a = self.amplitude

        if self.effect == "cercle":
            pan  = self.center_pan  + a * _math_eff.sin(self.phase)
            tilt = self.center_tilt + a * _math_eff.cos(self.phase)

        elif self.effect == "figure8":
            pan  = self.center_pan  + a * _math_eff.sin(self.phase)
            tilt = self.center_tilt + (a / 2) * _math_eff.sin(2 * self.phase)

        elif self.effect == "balayage_h":
            pan  = self.center_pan  + a * _math_eff.sin(self.phase)
            tilt = self.center_tilt

        elif self.effect == "balayage_v":
            pan  = self.center_pan
            tilt = self.center_tilt + a * _math_eff.sin(self.phase)

        elif self.effect == "aleatoire":
            if self._r_step >= self._r_steps:
                self._r_tpan   = self.center_pan  + random.uniform(-a, a)
                self._r_ttilt  = self.center_tilt + random.uniform(-a, a)
                self._r_steps  = max(1, int(random.uniform(0.3, 1.5) / (self.speed * self.DT)))
                self._r_step   = 0
            t = self._r_step / self._r_steps
            self._r_pan  += (self._r_tpan  - self._r_pan)  * 0.15
            self._r_tilt += (self._r_ttilt - self._r_tilt) * 0.15
            self._r_step += 1
            pan, tilt = self._r_pan, self._r_tilt

        else:
            pan, tilt = self.center_pan, self.center_tilt

        return int(max(0, min(255, pan))), int(max(0, min(255, tilt)))


_PRESETS_FILE = os.path.expanduser("~/.mystrow_moving_presets.json")

_DEFAULT_PRESETS = [
    {"name": "Centre",  "pan": 128, "tilt": 128},
    {"name": "Face",    "pan": 128, "tilt": 180},
    {"name": "Sol",     "pan": 128, "tilt": 230},
    {"name": "Plafond", "pan": 128, "tilt": 30},
    {"name": "Gauche",  "pan": 60,  "tilt": 128},
    {"name": "Droite",  "pan": 195, "tilt": 128},
]


def _load_presets():
    try:
        with open(_PRESETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return [dict(p) for p in _DEFAULT_PRESETS]


def _save_presets(presets):
    try:
        with open(_PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


class PresetBar(QWidget):
    """Rangée de boutons presets Pan/Tilt — clic = appliquer, clic droit = mémoriser."""

    preset_selected = Signal(int, int)   # pan, tilt

    _BTN_STYLE = """
        QPushButton {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 rgba({r},{g},{b},70), stop:1 rgba(20,20,20,255));
            border-left: 3px solid {hex};
            border-top: none; border-right: none; border-bottom: none;
            border-radius: 3px;
            color: #cccccc;
            font-size: 10px;
            padding: 3px 6px;
            min-width: 52px;
        }}
        QPushButton:hover {{ color: white; border-left-color: #00d4ff; }}
    """

    def __init__(self, get_current_pan_tilt, parent=None):
        """get_current_pan_tilt : callable → (pan, tilt) actuel du pad."""
        super().__init__(parent)
        self._get_current = get_current_pan_tilt
        self._presets = _load_presets()
        self._buttons = []
        self._build()

    _COLS = 2  # nombre de colonnes dans la grille

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # En-tête : label + bouton "+"
        header = QHBoxLayout()
        header.setSpacing(4)
        lbl = QLabel(tr("pdf_presets_label"))
        lbl.setStyleSheet("color: #555; font-size: 9px;")
        header.addWidget(lbl)
        header.addStretch()
        add_btn = QPushButton("+")
        add_btn.setFixedSize(22, 22)
        add_btn.setToolTip(tr("pdf_tooltip_save_preset"))
        add_btn.setStyleSheet("""
            QPushButton { background: #1a3a1a; color: #4CAF50; border: 1px solid #2a5a2a;
                          border-radius: 3px; font-weight: bold; font-size: 13px; }
            QPushButton:hover { background: #2a5a2a; color: white; }
        """)
        add_btn.clicked.connect(self._add_preset)
        header.addWidget(add_btn)
        layout.addLayout(header)

        # Conteneur grille
        self._btn_container_w = QWidget()
        self._btn_grid = QGridLayout(self._btn_container_w)
        self._btn_grid.setSpacing(4)
        self._btn_grid.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._btn_container_w)

        self._rebuild_buttons()

    def _rebuild_buttons(self):
        # Vider la grille
        while self._btn_grid.count():
            item = self._btn_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons.clear()

        colors = ["#00d4ff", "#ff9800", "#4CAF50", "#e91e63", "#9c27b0", "#ff5722"]
        for i, preset in enumerate(self._presets):
            c = QColor(colors[i % len(colors)])
            r, g, b = c.red(), c.green(), c.blue()
            btn = QPushButton(preset["name"])
            btn.setFixedHeight(22)
            btn.setStyleSheet(self._BTN_STYLE.format(r=r, g=g, b=b, hex=c.name()))
            btn.setToolTip(tr("pdf_tooltip_preset_btn", pan=preset['pan'], tilt=preset['tilt']))
            btn.clicked.connect(lambda _, p=preset: self.preset_selected.emit(p["pan"], p["tilt"]))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda _, idx=i: self._ctx_preset(idx))
            row, col = divmod(i, self._COLS)
            self._btn_grid.addWidget(btn, row, col)
            self._buttons.append(btn)

    def _ctx_preset(self, idx):
        pan, tilt = self._get_current()
        m = QMenu(self)
        m.setStyleSheet("""
            QMenu { background: #1e1e1e; color: #ccc; border: 1px solid #333; }
            QMenu::item:selected { background: #2a2a2a; }
        """)
        m.addAction(tr("pdf_ctx_memorize", pan=pan, tilt=tilt),
                    lambda: self._memorize(idx, pan, tilt))
        m.addSeparator()
        m.addAction(tr("pdf_ctx_rename"), lambda: self._rename(idx))
        if len(self._presets) > 1:
            m.addAction(tr("pdf_ctx_delete"), lambda: self._delete(idx))
        m.exec(QCursor.pos())

    def _memorize(self, idx, pan, tilt):
        self._presets[idx]["pan"]  = pan
        self._presets[idx]["tilt"] = tilt
        _save_presets(self._presets)
        self._rebuild_buttons()

    def _rename(self, idx):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, tr("pdf_rename_title"), tr("pdf_rename_prompt"),
                                        text=self._presets[idx]["name"])
        if ok and name.strip():
            self._presets[idx]["name"] = name.strip()
            _save_presets(self._presets)
            self._rebuild_buttons()

    def _add_preset(self):
        from PySide6.QtWidgets import QInputDialog
        pan, tilt = self._get_current()
        name, ok = QInputDialog.getText(self, tr("pdf_new_preset_title"),
                                        tr("pdf_new_preset_prompt"), text=f"Pos {len(self._presets)+1}")
        if ok and name.strip():
            self._presets.append({"name": name.strip(), "pan": pan, "tilt": tilt})
            _save_presets(self._presets)
            self._rebuild_buttons()

    def _delete(self, idx):
        if 0 <= idx < len(self._presets):
            self._presets.pop(idx)
            _save_presets(self._presets)
            self._rebuild_buttons()


class PanTiltPad(QWidget):
    """Pad XY interactif pour contrôler Pan/Tilt d'une Moving Head."""

    changed = Signal(int, int)  # pan, tilt (0-255)

    _PAD_W = 200
    _PAD_H = 160
    _MARGIN = 10

    def __init__(self, pan=128, tilt=128, parent=None):
        super().__init__(parent)
        self._pan  = max(0, min(255, pan))
        self._tilt = max(0, min(255, tilt))
        self._dragging = False

        total_w = self._PAD_W + self._MARGIN * 2
        total_h = self._PAD_H + self._MARGIN * 2 + 28  # +28 pour les labels + bouton
        self.setFixedSize(total_w, total_h)
        self.setMouseTracking(True)

    # ── Coordonnées ─────────────────────────────────────────────────────
    def _val_to_px(self):
        """Retourne (px, py) en pixels absolus dans le widget."""
        m = self._MARGIN
        px = m + int(self._pan  / 255.0 * self._PAD_W)
        py = m + int(self._tilt / 255.0 * self._PAD_H)
        return px, py

    def _px_to_val(self, x, y):
        m = self._MARGIN
        pan  = int(max(0, min(255, (x - m) / self._PAD_W * 255)))
        tilt = int(max(0, min(255, (y - m) / self._PAD_H * 255)))
        return pan, tilt

    # ── Souris ──────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._update_from_mouse(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_mouse(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False

    def mouseDoubleClickEvent(self, event):
        """Double-clic = centre (128, 128)"""
        self._pan, self._tilt = 128, 128
        self.changed.emit(self._pan, self._tilt)
        self.update()

    def _update_from_mouse(self, pos):
        pan, tilt = self._px_to_val(pos.x(), pos.y())
        if pan != self._pan or tilt != self._tilt:
            self._pan, self._tilt = pan, tilt
            self.changed.emit(self._pan, self._tilt)
            self.update()

    def set_values(self, pan, tilt):
        self._pan  = max(0, min(255, pan))
        self._tilt = max(0, min(255, tilt))
        self.update()

    # ── Dessin ──────────────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        m = self._MARGIN

        # Fond du pad
        pad_rect = QRect(m, m, self._PAD_W, self._PAD_H)
        painter.fillRect(pad_rect, QColor("#1a1a2e"))

        # Grille
        painter.setPen(QPen(QColor("#2a2a4a"), 1))
        step_x = self._PAD_W // 4
        step_y = self._PAD_H // 4
        for i in range(1, 4):
            painter.drawLine(m + i * step_x, m, m + i * step_x, m + self._PAD_H)
            painter.drawLine(m, m + i * step_y, m + self._PAD_W, m + i * step_y)

        # Axes centraux
        painter.setPen(QPen(QColor("#3a3a6a"), 1, Qt.DashLine))
        cx = m + self._PAD_W // 2
        cy = m + self._PAD_H // 2
        painter.drawLine(cx, m, cx, m + self._PAD_H)
        painter.drawLine(m, cy, m + self._PAD_W, cy)

        # Bordure
        painter.setPen(QPen(QColor("#00d4ff"), 1))
        painter.drawRect(pad_rect)

        # Curseur (croix + cercle)
        px, py = self._val_to_px()
        painter.setPen(QPen(QColor("#00d4ff"), 1))
        painter.drawLine(px - 8, py, px + 8, py)
        painter.drawLine(px, py - 8, px, py + 8)
        painter.setPen(QPen(QColor("#00d4ff"), 2))
        painter.setBrush(QColor(0, 212, 255, 60))
        painter.drawEllipse(QRect(px - 7, py - 7, 14, 14))

        # Labels Pan / Tilt
        painter.setPen(QColor("#888888"))
        painter.setFont(QFont("Segoe UI", 8))
        label_y = m + self._PAD_H + 6
        painter.drawText(QRect(m, label_y, self._PAD_W // 2, 18),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         f"Pan: {self._pan}")
        painter.drawText(QRect(m + self._PAD_W // 2, label_y, self._PAD_W // 2, 18),
                         Qt.AlignRight | Qt.AlignVCenter,
                         f"Tilt: {self._tilt}")

        # Hint double-clic
        painter.setPen(QColor("#444"))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRect(m, label_y + 14, self._PAD_W, 12),
                         Qt.AlignCenter, tr("pdf_hint_double_click"))

        painter.end()


class EffectPanel(QWidget):
    """Panneau d'effets automatiques Pan/Tilt pour Moving Head."""

    effect_started = Signal(str, float, int)   # effect, speed, amplitude
    effect_stopped = Signal()

    _EFFECTS = [
        ("⭕", "cercle",     "Cercle"),
        ("∞",  "figure8",   "Figure 8"),
        ("↔",  "balayage_h","Balayage H"),
        ("↕",  "balayage_v","Balayage V"),
        ("✦",  "aleatoire", "Aléatoire"),
    ]

    _BTN_ON  = "QPushButton { background:#005577; color:#00d4ff; border:1px solid #00d4ff; border-radius:4px; font-size:14px; font-weight:bold; min-width:32px; min-height:28px; }"
    _BTN_OFF = "QPushButton { background:#222; color:#666; border:1px solid #333; border-radius:4px; font-size:14px; min-width:32px; min-height:28px; } QPushButton:hover{color:#ccc;border-color:#555;}"

    def __init__(self, active_effect=None, active_speed=0.5, active_amplitude=60, parent=None):
        super().__init__(parent)
        self._current = active_effect
        self._build(active_speed, active_amplitude)

    def _build(self, speed, amplitude):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Titre
        title = QLabel(tr("pdf_auto_effects_title"))
        title.setStyleSheet("color:#888; font-size:9px; font-weight:bold;")
        root.addWidget(title)

        # Boutons effets
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._eff_btns = {}
        for icon, key, tooltip in self._EFFECTS:
            btn = QPushButton(icon)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(self._BTN_ON if key == self._current else self._BTN_OFF)
            btn.clicked.connect(lambda _, k=key: self._on_effect(k))
            btn_row.addWidget(btn)
            self._eff_btns[key] = btn

        stop_btn = QPushButton("■")
        stop_btn.setToolTip(tr("pdf_tooltip_stop_effect"))
        stop_btn.setStyleSheet("QPushButton{background:#3a1a1a;color:#f44;border:1px solid #622;border-radius:4px;font-size:14px;min-width:32px;min-height:28px;} QPushButton:hover{background:#4a2a2a;}")
        stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(stop_btn)
        root.addLayout(btn_row)

        # Vitesse
        spd_row = QHBoxLayout()
        spd_row.setSpacing(6)
        spd_lbl = QLabel(tr("pdf_speed_label"))
        spd_lbl.setStyleSheet("color:#888; font-size:9px;")
        spd_lbl.setFixedWidth(44)
        spd_row.addWidget(spd_lbl)
        self._spd_slider = QSlider(Qt.Horizontal)
        self._spd_slider.setRange(1, 30)  # 0.1–3.0 Hz ×10
        self._spd_slider.setValue(int(speed * 10))
        self._spd_slider.setFixedWidth(120)
        self._spd_slider.setStyleSheet("""
            QSlider::groove:horizontal{background:#333;height:6px;border-radius:3px;}
            QSlider::handle:horizontal{background:#00d4ff;width:14px;height:14px;margin:-4px 0;border-radius:7px;}
            QSlider::sub-page:horizontal{background:#005577;border-radius:3px;}
        """)
        self._spd_val = QLabel(f"{speed:.1f} Hz")
        self._spd_val.setStyleSheet("color:#ccc; font-size:9px; min-width:36px;")
        self._spd_slider.valueChanged.connect(
            lambda v: (self._spd_val.setText(f"{v/10:.1f} Hz"), self._emit_if_active()))
        spd_row.addWidget(self._spd_slider)
        spd_row.addWidget(self._spd_val)
        root.addLayout(spd_row)

        # Amplitude
        amp_row = QHBoxLayout()
        amp_row.setSpacing(6)
        amp_lbl = QLabel(tr("pdf_amplitude_label"))
        amp_lbl.setStyleSheet("color:#888; font-size:9px;")
        amp_lbl.setFixedWidth(44)
        amp_row.addWidget(amp_lbl)
        self._amp_slider = QSlider(Qt.Horizontal)
        self._amp_slider.setRange(5, 120)
        self._amp_slider.setValue(amplitude)
        self._amp_slider.setFixedWidth(120)
        self._amp_slider.setStyleSheet(self._spd_slider.styleSheet())
        self._amp_val = QLabel(f"{amplitude}")
        self._amp_val.setStyleSheet("color:#ccc; font-size:9px; min-width:36px;")
        self._amp_slider.valueChanged.connect(
            lambda v: (self._amp_val.setText(str(v)), self._emit_if_active()))
        amp_row.addWidget(self._amp_slider)
        amp_row.addWidget(self._amp_val)
        root.addLayout(amp_row)

    def _on_effect(self, key):
        self._current = key
        for k, b in self._eff_btns.items():
            b.setStyleSheet(self._BTN_ON if k == key else self._BTN_OFF)
        self._emit_if_active()

    def _on_stop(self):
        self._current = None
        for b in self._eff_btns.values():
            b.setStyleSheet(self._BTN_OFF)
        self.effect_stopped.emit()

    def _emit_if_active(self):
        if self._current:
            self.effect_started.emit(
                self._current,
                self._spd_slider.value() / 10.0,
                self._amp_slider.value()
            )

    def get_speed(self):
        return self._spd_slider.value() / 10.0

    def get_amplitude(self):
        return self._amp_slider.value()


class ColorPickerWidget(QWidget):
    """Gradient HSV cliquable/draggable - integre dans un menu contextuel"""

    colorSelected = Signal(QColor)

    def __init__(self, width=230, height=140, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self.setCursor(Qt.CrossCursor)
        self._image = None
        self._marker_pos = None
        self._generate_gradient()

    def _generate_gradient(self):
        """Genere le gradient HSV: hue horizontal, blanc en haut, noir en bas"""
        w, h = self.width(), self.height()
        self._image = QImage(w, h, QImage.Format_RGB32)
        mid = h / 2.0
        for x in range(w):
            hue = x / w
            for y in range(h):
                if y <= mid:
                    sat = y / mid if mid > 0 else 1.0
                    val = 1.0
                else:
                    sat = 1.0
                    val = (h - y) / mid if mid > 0 else 0.0
                color = QColor.fromHsvF(
                    min(hue, 1.0), min(sat, 1.0), min(val, 1.0)
                )
                self._image.setPixelColor(x, y, color)

    def paintEvent(self, event):
        if not self._image:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawImage(0, 0, self._image)
        # Marqueur de position
        if self._marker_pos:
            x, y = self._marker_pos
            pen = QPen(QColor("white"), 2)
            painter.setPen(pen)
            painter.drawEllipse(QPoint(x, y), 6, 6)
            pen.setColor(QColor("black"))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawEllipse(QPoint(x, y), 7, 7)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pick_color(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick_color(event.pos())

    def _pick_color(self, pos):
        x = max(0, min(pos.x(), self.width() - 1))
        y = max(0, min(pos.y(), self.height() - 1))
        self._marker_pos = (x, y)
        color = QColor(self._image.pixelColor(x, y))
        self.colorSelected.emit(color)
        self.update()


# Couleurs predefinies = meme ordre que les pads AKAI (sans noir)
PRESET_COLORS = [
    ("Blanc", QColor(255, 255, 255)),
    ("Rouge", QColor(255, 0, 0)),
    ("Orange", QColor(255, 136, 0)),
    ("Jaune", QColor(255, 221, 0)),
    ("Vert", QColor(0, 255, 0)),
    ("Cyan", QColor(0, 221, 221)),
    ("Bleu", QColor(0, 0, 255)),
    ("Magenta", QColor(255, 0, 255)),
]


class _HSVSlider(QWidget):
    """Slider horizontal avec fond dégradé et marqueur circulaire (style HSV)."""

    valueChanged = Signal(float)   # 0.0 – 1.0
    _R = 9                         # rayon du handle

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value: float = 0.0
        self._stops: list = []
        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)

    def set_stops(self, stops: list):
        self._stops = stops
        self.update()

    def set_value(self, v: float):
        self._value = max(0.0, min(1.0, v))
        self.update()

    def value(self) -> float:
        return self._value

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bar_h = 10
        bar_y = (h - bar_h) // 2

        if self._stops:
            grad = QLinearGradient(0, 0, w, 0)
            for pos, color in self._stops:
                grad.setColorAt(pos, color)
            painter.setBrush(grad)
        else:
            painter.setBrush(QColor("#333"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, bar_y, w, bar_h, 5, 5)

        # Handle circulaire blanc
        hx = int(self._value * w)
        hy = h // 2
        painter.setBrush(QColor("white"))
        painter.setPen(QPen(QColor(60, 60, 60), 1.5))
        painter.drawEllipse(QPoint(hx, hy), self._R, self._R)
        painter.end()

    def _pick(self, pos):
        w = self.width()
        v = max(0.0, min(1.0, pos.x() / w if w else 0.0))
        if v != self._value:
            self._value = v
            self.valueChanged.emit(v)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pick(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.pos())


class ColorPickerBlock(QFrame):
    """Color picker HSV avec sliders Teinte/Luminosité."""

    def __init__(self, plan_de_feu, parent=None):
        super().__init__(parent)
        self.plan_de_feu = plan_de_feu
        self._h = 0.0
        self._s = 1.0
        self._v = 1.0

        self.setStyleSheet("ColorPickerBlock { border: none; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        # ── Hue ──────────────────────────────────────────────────────────
        self._hue_val_lbl = self._add_row(layout, "Couleur", "0°")
        self._hue_slider = _HSVSlider()
        self._hue_slider.set_stops(
            [(i / 6, QColor.fromHsvF(i / 6, 1.0, 1.0)) for i in range(7)]
        )
        self._hue_slider.valueChanged.connect(self._on_hue)
        layout.addWidget(self._hue_slider)

        # ── Saturation ───────────────────────────────────────────────────
        self._sat_val_lbl = self._add_row(layout, "Saturation", "100%")
        self._sat_slider = _HSVSlider()
        self._sat_slider.set_value(1.0)
        self._sat_slider.valueChanged.connect(self._on_sat)
        layout.addWidget(self._sat_slider)

        # ── Luminosité ───────────────────────────────────────────────────
        self._bri_val_lbl = self._add_row(layout, "Luminosité", "100%")
        self._bri_slider = _HSVSlider()
        self._bri_slider.set_value(1.0)
        self._bri_slider.valueChanged.connect(self._on_bri)
        layout.addWidget(self._bri_slider)

        self._update_sat_stops()
        self._update_bri_stops()

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _add_row(layout, text: str, value: str) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        val = QLabel(value)
        val.setStyleSheet("color: #ddd; font-size: 11px;")
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(val)
        layout.addLayout(row)
        return val

    def _current_qcolor(self) -> QColor:
        return QColor.fromHsvF(self._h, self._s, self._v)

    def _update_sat_stops(self):
        white = QColor(255, 255, 255)
        full  = QColor.fromHsvF(self._h, 1.0, 1.0)
        self._sat_slider.set_stops([(0.0, white), (1.0, full)])

    def _update_bri_stops(self):
        black = QColor(0, 0, 0)
        full  = QColor.fromHsvF(self._h, self._s, 1.0)
        self._bri_slider.set_stops([(0.0, black), (1.0, full)])

    # ── Slider callbacks ──────────────────────────────────────────────────────
    def _on_hue(self, v: float):
        self._h = v
        self._hue_val_lbl.setText(f"{int(v * 359)}°")
        self._update_sat_stops()
        self._update_bri_stops()
        self._send_color(self._current_qcolor())

    def _on_sat(self, v: float):
        self._s = v
        self._sat_val_lbl.setText(f"{int(v * 100)}%")
        self._update_bri_stops()
        self._send_color(self._current_qcolor())

    def _on_bri(self, v: float):
        self._v = v
        self._bri_val_lbl.setText(f"{int(v * 100)}%")
        self._send_color(self._current_qcolor())

    # ── DMX output ────────────────────────────────────────────────────────────
    def _send_color(self, color: QColor):
        pdf = self.plan_de_feu
        if not pdf.selected_lamps:
            return
        targets = []
        for g, i in pdf.selected_lamps:
            projs = [p for p in pdf.projectors if p.group == g]
            if i < len(projs):
                targets.append((projs[i], g, i))
        for proj, g, i in targets:
            proj.base_color = color
            proj.level = 100
            proj.color = QColor(color.red(), color.green(), color.blue())
        if pdf.main_window and hasattr(pdf.main_window, 'dmx') and pdf.main_window.dmx:
            pdf.main_window.dmx.update_from_projectors(pdf.projectors)
        pdf.refresh()


# ── Bibliotheque de fixtures ─────────────────────────────────────────────────

FIXTURE_LIBRARY = {
    "PAR LED": [
        {"name": "PAR LED 5CH (RGB+Dim+Strobe)", "fixture_type": "PAR LED", "group": "face", "profile": "RGBDS"},
        {"name": "PAR LED 4CH (RGB+Dim)", "fixture_type": "PAR LED", "group": "face", "profile": "RGBD"},
        {"name": "PAR LED 3CH (RGB)", "fixture_type": "PAR LED", "group": "face", "profile": "RGB"},
        {"name": "PAR LED RGBW 4CH", "fixture_type": "PAR LED", "group": "face", "profile": "RGBW"},
        {"name": "PAR LED RGBW+Dim 5CH", "fixture_type": "PAR LED", "group": "face", "profile": "RGBWD"},
        {"name": "PAR contre 5CH", "fixture_type": "PAR LED", "group": "contre", "profile": "RGBDS"},
    ],
    "Moving Head": [
        {"name": "Moving Head 8CH", "fixture_type": "Moving Head", "group": "face", "profile": "MOVING_8CH"},
        {"name": "Moving Head RGB 9CH", "fixture_type": "Moving Head", "group": "face", "profile": "MOVING_RGB"},
        {"name": "Moving Head RGBW 9CH", "fixture_type": "Moving Head", "group": "face", "profile": "MOVING_RGBW"},
    ],
    "Barre LED": [
        {"name": "Barre LED RGB 5CH", "fixture_type": "Barre LED", "group": "face", "profile": "LED_BAR_RGB"},
    ],
    "Stroboscope": [
        {"name": "Stroboscope 2CH", "fixture_type": "Stroboscope", "group": "face", "profile": "STROBE_2CH"},
    ],
    "Machine a fumee": [
        {"name": "Machine a fumee 2CH", "fixture_type": "Machine a fumee", "group": "face", "profile": "2CH_FUMEE"},
    ],
    "Gradateur": [
        {"name": "Gradateur 1CH", "fixture_type": "Gradateur", "group": "face", "profile": "DIM"},
    ],
}

# Positions par defaut sur le canvas (coordonnees normalisees 0-1)
_DEFAULT_POSITIONS = {
    "face":     lambda li, n: (0.20 + li * 0.60 / max(n - 1, 1), 0.78),
    "contre":   lambda li, n: (0.15 + li * 0.70 / max(n - 1, 1), 0.10),
    "douche1":  lambda li, n: (0.24 + li * 0.08, 0.50),
    "douche2":  lambda li, n: (0.46 + li * 0.08, 0.50),
    "douche3":  lambda li, n: (0.68 + li * 0.08, 0.50),
    "lat":      lambda li, n: (0.07 if li == 0 else 0.93, 0.40),
    "public":   lambda li, n: (0.50, 0.90),
    "fumee":    lambda li, n: (0.10, 0.90),
    "lyre":     lambda li, n: (0.15 + li * 0.70 / max(n - 1, 1), 0.25),
    "barre":    lambda li, n: (0.15 + li * 0.70 / max(n - 1, 1), 0.35),
    "strobe":   lambda li, n: (0.15 + li * 0.70 / max(n - 1, 1), 0.45),
    "groupe_e": lambda li, n: (0.20 + li * 0.60 / max(n - 1, 1), 0.62),
    "groupe_f": lambda li, n: (0.20 + li * 0.60 / max(n - 1, 1), 0.46),
}

class _PersistentMenu(QMenu):
    """QMenu qui ne se ferme pas quand on clique sur un QWidgetAction (ex: boutons couleur)."""

    def _forward_to_widget(self, event):
        """Retransmet l'event souris au widget de la QWidgetAction avec coordonnees locales."""
        action = self.actionAt(event.pos())
        if isinstance(action, QWidgetAction):
            w = action.defaultWidget()
            if w:
                # Traduire les coordonnees menu → widget local
                local_pos = QPointF(w.mapFrom(self, event.pos()))
                new_event = QMouseEvent(
                    event.type(),
                    local_pos,
                    event.globalPosition(),
                    event.button(),
                    event.buttons(),
                    event.modifiers(),
                )
                w.event(new_event)
            return True
        return False

    def mouseReleaseEvent(self, event):
        if not self._forward_to_widget(event):
            super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        if not self._forward_to_widget(event):
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._forward_to_widget(event):
            super().mouseMoveEvent(event)


_MENU_STYLE = """
QMenu {
    background: #1e1e1e;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    padding: 6px;
    color: white;
    font-size: 11px;
}
QMenu::item {
    padding: 6px 20px;
    border-radius: 3px;
}
QMenu::item:selected {
    background: #333;
}
QMenu::separator {
    height: 1px;
    background: #3a3a3a;
    margin: 4px 8px;
}
"""


# Couleurs de groupe pour les anneaux indicateurs
_GROUP_COLORS = {
    "face":     "#ff8844",
    "contre":   "#4488ff",
    "douche1":  "#44cc88",
    "douche2":  "#ffcc44",
    "douche3":  "#ff4488",
    "lat":      "#aa55ff",
    "lyre":     "#ff44cc",
    "barre":    "#44aaff",
    "strobe":   "#ffee44",
    "fumee":    "#88aaaa",
    "public":   "#ff6655",
    "groupe_e": "#cc44ff",
    "groupe_f": "#ffcc22",
}

# ── Helpers de positionnement ─────────────────────────────────────────────────

def _find_free_canvas_pos(projectors, pref_x, pref_y, min_dist=0.07):
    """Retourne une position (x, y) normalisée libre autour de (pref_x, pref_y).

    Fait une recherche en cercles concentriques jusqu'à trouver un emplacement
    qui ne chevauche pas les fixtures existantes.
    """
    import math as _m
    occupied = [
        (p.canvas_x, p.canvas_y)
        for p in projectors
        if p.canvas_x is not None and p.canvas_y is not None
    ]

    def _clear(x, y):
        return all((x - ox) ** 2 + (y - oy) ** 2 >= min_dist ** 2
                   for ox, oy in occupied)

    pref_x = max(0.05, min(0.95, pref_x))
    pref_y = max(0.05, min(0.95, pref_y))

    if not occupied or _clear(pref_x, pref_y):
        return pref_x, pref_y

    for r in range(1, 20):
        n_angles = max(8, r * 8)
        candidates = []
        for k in range(n_angles):
            angle = 2 * _m.pi * k / n_angles
            nx = max(0.05, min(0.95, pref_x + r * min_dist * _m.cos(angle)))
            ny = max(0.05, min(0.95, pref_y + r * min_dist * _m.sin(angle)))
            if _clear(nx, ny):
                candidates.append((nx, ny))
        if candidates:
            return min(candidates, key=lambda p: (p[0] - pref_x) ** 2 + (p[1] - pref_y) ** 2)

    return pref_x, pref_y  # Dernier recours


# ── FixtureCanvas ─────────────────────────────────────────────────────────────

class _PanTiltFloater(QFrame):
    """Panneau flottant Pan/Tilt qui s'accroche à une Moving Head dans le canvas."""

    closed = Signal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas  = canvas
        self._targets = []   # liste de Projector à contrôler

        self.setWindowFlags(Qt.SubWindow)
        self.setStyleSheet("""
            _PanTiltFloater, QFrame {
                background: #0e0e0e;
                border: 1px solid #00d4ff44;
                border-radius: 8px;
            }
        """)
        self.setStyleSheet(
            "background:#0e0e0e; border:1px solid #00d4ff55; border-radius:8px;"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        lbl = QLabel("Pan / Tilt")
        lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl.setStyleSheet("color:#00d4ff; background:transparent; border:none;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._lbl_vals = QLabel("P:128  T:128")
        self._lbl_vals.setFont(QFont("Segoe UI", 8))
        self._lbl_vals.setStyleSheet("color:#444; background:transparent; border:none;")
        hdr.addWidget(self._lbl_vals)
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(16, 16)
        btn_close.setStyleSheet(
            "QPushButton{background:transparent;color:#444;border:none;font-size:10px;}"
            "QPushButton:hover{color:#f44336;}"
        )
        btn_close.clicked.connect(self.hide_floater)
        hdr.addWidget(btn_close)
        lay.addLayout(hdr)

        # Pad XY
        self._pad = PanTiltPad(128, 128)
        self._pad.changed.connect(self._on_changed)
        lay.addWidget(self._pad, 0, Qt.AlignHCenter)

        # Presets compacts
        self._presets = _load_presets()
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        colors = ["#00d4ff", "#ff9800", "#4CAF50", "#e91e63", "#9c27b0", "#ff5722"]
        for i, pr in enumerate(self._presets[:6]):
            c = QColor(colors[i % len(colors)])
            b = QPushButton(pr["name"])
            b.setFixedHeight(20)
            b.setStyleSheet(
                f"QPushButton{{background:#1a1a1a;color:{c.name()};"
                f"border:1px solid {c.name()}44;border-radius:3px;font-size:9px;}}"
                f"QPushButton:hover{{border-color:{c.name()};}}"
            )
            b.clicked.connect(lambda _, p=pr: self._apply_preset(p))
            preset_row.addWidget(b)
        lay.addLayout(preset_row)

        # Bouton centre
        btn_center = QPushButton("⊕  Centre (128 / 128)")
        btn_center.setFixedHeight(22)
        btn_center.setStyleSheet(
            "QPushButton{background:#1a1a1a;color:#555;border:1px solid #222;"
            "border-radius:4px;font-size:9px;}"
            "QPushButton:hover{color:#00d4ff;border-color:#00d4ff44;}"
        )
        btn_center.clicked.connect(lambda: self._apply_preset({"pan": 128, "tilt": 128}))
        lay.addWidget(btn_center)

        self.adjustSize()
        self.hide()

    def show_for(self, idx, canvas_pos):
        """Affiche le floater près de la fixture idx."""
        projs = self.get_group_projs(idx)
        self._targets = projs
        if projs:
            pan  = getattr(projs[0], 'pan',  128)
            tilt = getattr(projs[0], 'tilt', 128)
        else:
            pan, tilt = 128, 128

        self._pad.set_values(pan, tilt)
        self._lbl_vals.setText(f"P:{pan}  T:{tilt}")

        # Positionner à côté de la fixture sans sortir du canvas
        fw, fh = self.sizeHint().width(), self.sizeHint().height()
        cw, ch = self._canvas.width(), self._canvas.height()
        x = canvas_pos.x() + 20
        y = canvas_pos.y() - fh // 2
        x = max(4, min(x, cw - fw - 4))
        y = max(4, min(y, ch - fh - 4))
        self.move(x, y)
        self.adjustSize()
        self.raise_()
        self.show()

    def get_group_projs(self, idx):
        """Retourne tous les Moving Head du même groupe que idx."""
        proj = self._canvas.pdf.projectors[idx]
        group = proj.group
        return [
            p for p in self._canvas.pdf.projectors
            if p.group == group and getattr(p, 'fixture_type', '') == 'Moving Head'
        ] or [proj]

    def _on_changed(self, pan, tilt):
        for p in self._targets:
            p.pan  = pan
            p.tilt = tilt
        self._lbl_vals.setText(f"P:{pan}  T:{tilt}")
        self._canvas.update()
        # Flush DMX
        pdf = self._canvas.pdf
        if hasattr(pdf, '_flush_dmx'):
            pdf._flush_dmx()

    def _apply_preset(self, pr):
        self._pad.set_values(pr["pan"], pr["tilt"])

    def hide_floater(self):
        self._targets = []
        self._pt_fixture = None if not self._canvas else None
        self._canvas._pt_fixture = None
        self.hide()
        self.closed.emit()


class FixtureCanvas(QWidget):
    """Canvas 2D libre - toutes les fixtures sont dessinees via paintEvent"""

    def __init__(self, pdf, parent=None):
        super().__init__(parent)
        self.pdf = pdf
        self.setFocusPolicy(Qt.ClickFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        # Mode edition : True dans le dialog Patch DMX, False sur la vue principale
        self._editable = getattr(pdf, '_canvas_editable', True)

        # Mode compact : icones plus petites, sans labels (utilisé dans la vue principale)
        self.compact = False

        self._guides      = []   # Smart Guides temporaires pendant le drag

        self._drag_index  = None
        self._drag_offset = QPoint()

        # Drag direct du faisceau Pan/Tilt (Moving Head)
        self._beam_drag_idx     = None   # index de la fixture cliquée
        self._beam_drag_start   = None   # QPoint origin du drag
        self._beam_drag_pt0     = None   # (pan0, tilt0) au début du drag
        self._beam_drag_targets = []     # [(proj, pan0, tilt0)] à modifier
        self._drag_starts = {}         # {proj_idx: (norm_x, norm_y)} pour multi-drag
        self._hover_index = None
        self._rubber_origin = None
        self._rubber_rect   = None
        # Beam "en attente" : press sur faisceau sans drag → rubber band prioritaire
        self._pending_beam  = None       # dict {beam_idx, pos, targets} ou None
        self._pt_floater    = None       # floater Pan/Tilt (référence externe, peut être None)

    # ── Helpers de position ─────────────────────────────────────────

    def _get_canvas_pos(self, i):
        """Retourne (px, py) en pixels pour la fixture i"""
        proj = self.pdf.projectors[i]
        w, h = max(self.width(), 1), max(self.height(), 1)
        cx = getattr(proj, 'canvas_x', None)
        cy = getattr(proj, 'canvas_y', None)
        if cx is not None and cy is not None:
            return int(cx * w), int(cy * h)
        group = proj.group
        group_indices = [j for j, p in enumerate(self.pdf.projectors) if p.group == group]
        li = group_indices.index(i) if i in group_indices else 0
        n = len(group_indices)
        pos_fn = _DEFAULT_POSITIONS.get(group, lambda li, n: (0.5, 0.5))
        fx, fy = pos_fn(li, n)
        return int(fx * w), int(fy * h)

    def _get_norm_pos(self, i):
        """Retourne la position normalisee (0-1) de la fixture i"""
        w, h = max(self.width(), 1), max(self.height(), 1)
        px, py = self._get_canvas_pos(i)
        return px / w, py / h

    def _local_idx(self, i):
        """Retourne (group, local_idx) pour la fixture i"""
        proj = self.pdf.projectors[i]
        group = proj.group
        group_indices = [j for j, p in enumerate(self.pdf.projectors) if p.group == group]
        li = group_indices.index(i) if i in group_indices else 0
        return group, li

    def _fixture_at(self, pos):
        """Retourne l'index de la fixture sous pos, ou None"""
        px, py = pos.x(), pos.y()
        for i in range(len(self.pdf.projectors) - 1, -1, -1):
            cx, cy = self._get_canvas_pos(i)
            ftype = getattr(self.pdf.projectors[i], 'fixture_type', 'PAR LED')
            if ftype == "Barre LED":
                if abs(px - cx) <= 16 and abs(py - cy) <= 6:
                    return i
            elif ftype == "Machine a fumee":
                if abs(px - cx) <= 13 and abs(py - cy) <= 7:
                    return i
            else:
                if (px - cx) ** 2 + (py - cy) ** 2 <= 13 * 13:
                    return i
        return None

    def _beam_at(self, pos):
        """Retourne l'index d'une Moving Head dont le faisceau est sous pos, ou None."""
        import math as _m
        px, py = pos.x(), pos.y()
        r = 9 if self.compact else 13
        TOL = 12  # px de tolérance latérale pour faciliter la prise
        for i in range(len(self.pdf.projectors) - 1, -1, -1):
            proj = self.pdf.projectors[i]
            if getattr(proj, 'fixture_type', '') != 'Moving Head':
                continue
            cx, cy = self._get_canvas_pos(i)
            pan_val    = getattr(proj, 'pan',  128)
            tilt_val   = getattr(proj, 'tilt', 128)
            pan_angle  = (pan_val - 128) / 128.0 * 135.0
            tilt_ratio = tilt_val / 255.0
            beam_len   = int(r * 2 + tilt_ratio * r * 7)
            beam_hw    = int(r * 0.6 + tilt_ratio * r * 2.5)

            # Transformer dans le repère local (centré + rotation inverse)
            rad = _m.radians(-pan_angle)
            dx, dy = px - cx, py - cy
            lx =  dx * _m.cos(rad) - dy * _m.sin(rad)
            ly =  dx * _m.sin(rad) + dy * _m.cos(rad)

            # Zone : de la sortie de la fixture jusqu'au bout du faisceau + impact
            base_hw = r // 2
            if 0 < ly <= beam_len + beam_hw + TOL:
                t = max(0.0, min(1.0, (ly - r) / max(1, beam_len - r)))
                hw_at_ly = base_hw + (beam_hw - base_hw) * t
                if abs(lx) <= hw_at_ly + TOL:
                    return i
        return None

    # ── Dessin ─────────────────────────────────────────────────────

    def _get_fill_color(self, proj):
        htp = self.pdf._htp_overrides
        if htp and id(proj) in htp:
            level, color = htp[id(proj)][:2]
            if level > 0 and not proj.muted:
                c = QColor(color)
                r = int(c.red()   * level)
                g = int(c.green() * level)
                b = int(c.blue()  * level)
                return QColor(r, g, b)
            return QColor("#1a1a1a")
        if proj.muted or proj.level == 0:
            return QColor("#1a1a1a")
        # Strobe visuel : clignotement selon strobe_speed
        strobe_spd = getattr(proj, 'strobe_speed', 0)
        if strobe_spd > 0:
            freq = 1.0 + (strobe_spd / 100.0) * 14.0  # 1 Hz → 15 Hz
            if int(_time.time() * freq * 2) % 2 == 1:
                return QColor("#1a1a1a")  # phase éteinte
        return QColor(proj.color)

    def _draw_fixture(self, painter, cx, cy, proj, is_selected, is_hover):
        """Dessine une fixture avec glow, forme adaptee et indicateurs visuels"""
        ftype      = getattr(proj, 'fixture_type', 'PAR LED')
        fill_color = self._get_fill_color(proj)
        r          = 9 if self.compact else 13
        is_lit     = not proj.muted and proj.level > 0
        gc         = QColor(_GROUP_COLORS.get(proj.group, "#555555"))

        # Dimensions dérivées de r pour barre et fumee
        barre_hw = int(r * 1.23); barre_hh = max(3, int(r * 0.38))
        fumee_hw = int(r * 0.92); fumee_hh = max(3, int(r * 0.46))

        # ── Halo de lumiere (quand allumee) ─────────────────────
        if is_lit:
            fc      = fill_color
            glow_r  = r + 9 if self.compact else r + 14
            grad    = QRadialGradient(float(cx), float(cy), float(glow_r))
            grad.setColorAt(0.0, QColor(fc.red(), fc.green(), fc.blue(), 110))
            grad.setColorAt(0.5, QColor(fc.red(), fc.green(), fc.blue(), 35))
            grad.setColorAt(1.0, QColor(fc.red(), fc.green(), fc.blue(), 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QPoint(cx, cy), glow_r, glow_r)

        # ── Contour (selection / survol / groupe) ────────────────
        if is_selected:
            pen = QPen(QColor("#00d4ff"), 3)
        elif is_hover:
            pen = QPen(QColor("#cccccc"), 2)
        else:
            pen = QPen(gc, 1)

        painter.setPen(pen)
        painter.setBrush(QBrush(fill_color))

        if ftype == "Moving Head":
            pan_val  = getattr(proj, 'pan',  128)
            tilt_val = getattr(proj, 'tilt', 128)
            # Pan → rotation du faisceau (-135° … +135°)
            pan_angle  = (pan_val - 128) / 128.0 * 135.0
            # Tilt → longueur du faisceau (0=court, 255=long)
            tilt_ratio = tilt_val / 255.0
            beam_len   = int(r * 2 + tilt_ratio * r * 7)
            beam_hw    = int(r * 0.6 + tilt_ratio * r * 2.5)

            # Cone de faisceau orienté
            if is_lit:
                gobo_val = getattr(proj, 'gobo', 0)
                gobo_idx = int(gobo_val // 32) if gobo_val > 0 else 0  # 0=open, 1-7=gobos

                beam_col = QColor(fill_color)
                beam_col.setAlpha(14 if gobo_idx > 0 else 22)
                painter.save()
                painter.translate(cx, cy)
                painter.rotate(pan_angle)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(beam_col))
                cone = QPolygon([
                    QPoint(-r // 2, r),
                    QPoint( r // 2, r),
                    QPoint( beam_hw, beam_len),
                    QPoint(-beam_hw, beam_len),
                ])
                painter.drawPolygon(cone)

                # Impact au sol
                impact_col = QColor(fill_color)
                impact_col.setAlpha(55)
                iw = beam_hw; ih = max(3, beam_hw // 3)
                painter.setBrush(QBrush(impact_col))
                painter.drawEllipse(QPoint(0, beam_len), iw, ih)

                # Motif gobo dans l'impact
                if gobo_idx > 0:
                    pat_col = QColor(fill_color)
                    pat_col.setAlpha(160)
                    pat_pen = QPen(pat_col, max(1, iw // 6))
                    painter.setPen(pat_pen)
                    painter.setBrush(Qt.NoBrush)
                    import math as _gm
                    if gobo_idx == 1:   # lignes horizontales
                        for dy in (-ih // 2, 0, ih // 2):
                            painter.drawLine(-iw + 2, beam_len + dy, iw - 2, beam_len + dy)
                    elif gobo_idx == 2:  # croix +
                        painter.drawLine(-iw + 2, beam_len, iw - 2, beam_len)
                        painter.drawLine(0, beam_len - ih + 1, 0, beam_len + ih - 1)
                    elif gobo_idx == 3:  # croix ×
                        painter.drawLine(-iw + 2, beam_len - ih + 1, iw - 2, beam_len + ih - 1)
                        painter.drawLine(-iw + 2, beam_len + ih - 1, iw - 2, beam_len - ih + 1)
                    elif gobo_idx == 4:  # étoile 6 branches
                        for angle_deg in range(0, 180, 30):
                            rad = _gm.radians(angle_deg)
                            dx = int(_gm.cos(rad) * iw)
                            dy = int(_gm.sin(rad) * ih)
                            painter.drawLine(-dx, beam_len - dy, dx, beam_len + dy)
                    elif gobo_idx == 5:  # cercle inscrit
                        painter.drawEllipse(QPoint(0, beam_len), iw * 2 // 3, ih * 2 // 3)
                    elif gobo_idx == 6:  # triangle
                        painter.drawPolygon(QPolygon([
                            QPoint(0,       beam_len - ih + 1),
                            QPoint(iw - 2,  beam_len + ih - 1),
                            QPoint(-iw + 2, beam_len + ih - 1),
                        ]))
                    elif gobo_idx == 7:  # deux cercles concentriques
                        painter.drawEllipse(QPoint(0, beam_len), iw * 2 // 3, ih * 2 // 3)
                        painter.drawEllipse(QPoint(0, beam_len), iw // 3, ih // 3)

                painter.restore()
            # ── Lyre / Moving Head ───────────────────────────────────────────────
            lr          = int(r * 1.4)
            yoke_top_hw = int(lr * 0.88)
            yoke_bot_hw = int(lr * 0.54)
            bar_t       = max(3, int(lr * 0.26))
            arm_t_top   = max(3, int(lr * 0.26))
            arm_t_bot   = max(2, int(lr * 0.20))
            arm_bot_y   = cy + int(lr * 0.08)
            head_r      = int(lr * 0.46)
            head_cy     = arm_bot_y
            pivot_r     = max(2, int(lr * 0.17))
            lens_ring_r = int(lr * 0.30)
            lens_dot_r  = max(1, int(lr * 0.15))

            # Barre de fixation (accroche truss)
            bar_g = QLinearGradient(cx, cy - lr, cx, cy - lr + bar_t)
            bar_g.setColorAt(0.0, gc.lighter(162))
            bar_g.setColorAt(1.0, gc.darker(132))
            painter.setBrush(QBrush(bar_g))
            painter.setPen(pen)
            painter.drawRoundedRect(cx - yoke_top_hw, cy - lr,
                                    yoke_top_hw * 2, bar_t,
                                    bar_t // 2, bar_t // 2)

            # Bras gauche (trapèze) avec gradient latéral métallique
            arm_left = QPolygon([
                QPoint(cx - yoke_top_hw,             cy - lr + bar_t),
                QPoint(cx - yoke_top_hw + arm_t_top, cy - lr + bar_t),
                QPoint(cx - yoke_bot_hw + arm_t_bot, arm_bot_y),
                QPoint(cx - yoke_bot_hw,             arm_bot_y),
            ])
            arm_lg = QLinearGradient(cx - yoke_top_hw, 0,
                                     cx - yoke_top_hw + arm_t_top * 2, 0)
            arm_lg.setColorAt(0.0, gc.darker(138))
            arm_lg.setColorAt(0.4, gc.lighter(128))
            arm_lg.setColorAt(1.0, gc.darker(122))
            painter.setBrush(QBrush(arm_lg))
            painter.drawPolygon(arm_left)

            # Bras droit (trapèze) avec gradient latéral métallique
            arm_right = QPolygon([
                QPoint(cx + yoke_top_hw - arm_t_top, cy - lr + bar_t),
                QPoint(cx + yoke_top_hw,             cy - lr + bar_t),
                QPoint(cx + yoke_bot_hw,             arm_bot_y),
                QPoint(cx + yoke_bot_hw - arm_t_bot, arm_bot_y),
            ])
            arm_rg = QLinearGradient(cx + yoke_top_hw - arm_t_top * 2, 0,
                                     cx + yoke_top_hw, 0)
            arm_rg.setColorAt(0.0, gc.darker(122))
            arm_rg.setColorAt(0.6, gc.lighter(128))
            arm_rg.setColorAt(1.0, gc.darker(138))
            painter.setBrush(QBrush(arm_rg))
            painter.drawPolygon(arm_right)

            # Points pivot (vis de rotation)
            painter.setPen(QPen(gc.darker(160), 1))
            painter.setBrush(QBrush(gc.lighter(195)))
            painter.drawEllipse(QPoint(cx - yoke_bot_hw + arm_t_bot // 2, head_cy),
                                pivot_r, pivot_r)
            painter.drawEllipse(QPoint(cx + yoke_bot_hw - arm_t_bot // 2, head_cy),
                                pivot_r, pivot_r)

            # Tête (cercle — la tête de la lyre)
            head_grad = QRadialGradient(
                float(cx - head_r * 0.28), float(head_cy - head_r * 0.28),
                float(head_r * 1.5))
            head_grad.setColorAt(0.0, fill_color.lighter(165))
            head_grad.setColorAt(0.55, fill_color)
            head_grad.setColorAt(1.0, fill_color.darker(155))
            painter.setPen(pen)
            painter.setBrush(QBrush(head_grad))
            painter.drawEllipse(QPoint(cx, head_cy), head_r, head_r)

            # Anneau réflecteur
            painter.setPen(QPen(fill_color.darker(180), max(1, int(lr * 0.09))))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPoint(cx, head_cy), lens_ring_r, lens_ring_r)

            # Lentille sombre
            lens_g = QRadialGradient(float(cx), float(head_cy), float(lens_dot_r * 2.5))
            lens_g.setColorAt(0.0, fill_color.darker(100))
            lens_g.setColorAt(1.0, fill_color.darker(200))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(lens_g))
            painter.drawEllipse(QPoint(cx, head_cy), lens_dot_r, lens_dot_r)

            # Point brillant (reflet lentille)
            painter.setBrush(QBrush(QColor(255, 255, 255, 210)))
            hl_r = max(1, int(lens_dot_r * 0.45))
            painter.drawEllipse(
                QPoint(cx - int(lens_dot_r * 0.35), head_cy - int(lens_dot_r * 0.35)),
                hl_r, hl_r)

        elif ftype == "Barre LED":
            painter.drawRoundedRect(QRect(cx - barre_hw, cy - barre_hh, barre_hw * 2, barre_hh * 2), 3, 3)
            # Segments internes
            if is_lit:
                seg_col = QColor(fill_color)
                seg_col.setAlpha(160)
                painter.setPen(QPen(seg_col, 1))
                seg_step = max(4, barre_hw * 2 // 4)
                for seg in range(1, 4):
                    sx = cx - barre_hw + seg * seg_step
                    painter.drawLine(sx, cy - barre_hh + 1, sx, cy + barre_hh - 1)

        elif ftype == "Stroboscope":
            inner_r = r // 2
            pts = [
                QPoint(
                    int(cx + (r if k % 2 == 0 else inner_r) * math.cos(math.pi / 2 + k * math.pi / 6)),
                    int(cy - (r if k % 2 == 0 else inner_r) * math.sin(math.pi / 2 + k * math.pi / 6))
                )
                for k in range(12)
            ]
            painter.drawPolygon(QPolygon(pts))

        elif ftype == "Machine a fumee":
            painter.drawEllipse(QRect(cx - fumee_hw, cy - fumee_hh, fumee_hw * 2, fumee_hh * 2))
            # Nuages de fumee (petits cercles)
            if is_lit:
                smoke_col = QColor(200, 200, 200, 40)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(smoke_col))
                for ox, oy, sr in [(-7, -10, 5), (0, -12, 6), (7, -10, 5), (-4, -16, 4), (4, -16, 4)]:
                    painter.drawEllipse(QPoint(cx + ox, cy + oy), sr, sr)

        else:  # PAR LED (defaut)
            painter.drawEllipse(QPoint(cx, cy), r, r)

        # ── Croix mute ──────────────────────────────────────────
        if proj.muted:
            painter.setPen(QPen(QColor("#ff4444"), 2))
            painter.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
            painter.drawLine(cx + 5, cy - 5, cx - 5, cy + 5)

    def _draw_hover_card(self, painter, cx, cy, proj):
        """Tooltip flottant avec infos de la fixture survolee"""
        gd = {}
        if hasattr(self.pdf, 'main_window') and hasattr(self.pdf.main_window, 'GROUP_DISPLAY'):
            gd = self.pdf.main_window.GROUP_DISPLAY
        ftype = getattr(proj, 'fixture_type', 'PAR LED')
        lines = [
            proj.name or proj.group,
            f"{ftype}  ·  {gd.get(proj.group, proj.group)}",
            f"U{getattr(proj,'universe',0)+1} CH {proj.start_address}  ·  Niveau {proj.level}%" + ("  (mute)" if proj.muted else ""),
        ]
        card_w, line_h = 178, 15
        card_h = len(lines) * line_h + 14
        # Positionner à droite de la fixture; basculer à gauche si ça déborde
        if cx + 26 + card_w < self.width() - 4:
            cx_card = cx + 26
        else:
            cx_card = max(4, cx - card_w - 10)
        cy_card = max(6, cy - card_h - 10)

        path = QPainterPath()
        path.addRoundedRect(QRectF(cx_card, cy_card, card_w, card_h), 7, 7)
        painter.fillPath(path, QColor("#1b1b26"))
        painter.setPen(QPen(QColor("#2e2e44"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
        painter.setPen(QColor("#e8e8e8"))
        painter.drawText(
            QRect(cx_card + 10, cy_card + 6, card_w - 20, line_h),
            Qt.AlignLeft, lines[0]
        )
        painter.setFont(QFont("Segoe UI", 8))
        for j, line in enumerate(lines[1:], 1):
            painter.setPen(QColor("#777777"))
            painter.drawText(
                QRect(cx_card + 10, cy_card + 6 + j * line_h, card_w - 20, line_h),
                Qt.AlignLeft, line
            )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        W, H = self.width(), self.height()
        SB_H = 22   # hauteur barre de statut

        # ── Fond general ─────────────────────────────────────────
        painter.fillRect(self.rect(), QColor("#0a0a0a"))

        # ── Zone scene ───────────────────────────────────────────
        mx  = int(W * 0.04)
        my  = int(H * 0.05)
        sw  = W - 2 * mx
        sh  = H - 2 * my - SB_H
        sx, sy = mx, my

        stage_path = QPainterPath()
        stage_path.addRoundedRect(QRectF(sx, sy, sw, sh), 14, 14)
        painter.fillPath(stage_path, QColor("#0d0d0d"))

        # Degrade zone CONTRE (haut, bleu subtil)
        g_top = QLinearGradient(float(sx), float(sy), float(sx), float(sy + sh * 0.30))
        g_top.setColorAt(0.0, QColor(30, 60, 150, 20))
        g_top.setColorAt(1.0, QColor(0,   0,   0,  0))
        painter.fillPath(stage_path, QBrush(g_top))

        # Degrade zone FACE (bas, orange subtil)
        g_bot = QLinearGradient(float(sx), float(sy + sh * 0.70), float(sx), float(sy + sh))
        g_bot.setColorAt(0.0, QColor(0,   0,  0,  0))
        g_bot.setColorAt(1.0, QColor(160, 80, 20, 20))
        painter.fillPath(stage_path, QBrush(g_bot))

        # Grille tres discrete
        painter.setPen(QPen(QColor(255, 255, 255, 7), 1))
        for col in range(1, 4):
            x = sx + col * sw // 4
            painter.drawLine(x, sy + 10, x, sy + sh - 10)
        for row in range(1, 4):
            y = sy + row * sh // 4
            painter.drawLine(sx + 10, y, sx + sw - 10, y)

        # Labels de zone
        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QColor("#242424"))
        painter.drawText(QRect(sx, sy + 5,       sw, 14), Qt.AlignHCenter, tr("pdf_canvas_contre_haut"))
        painter.drawText(QRect(sx, sy + sh - 18, sw, 14), Qt.AlignHCenter, tr("pdf_canvas_face_bas"))

        # Bordure scene
        painter.setPen(QPen(QColor("#1c1c1c"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(stage_path)

        # ── Fixtures ─────────────────────────────────────────────
        font_name = QFont("Segoe UI", 8)
        font_ch   = QFont("Segoe UI", 7)

        for i, proj in enumerate(self.pdf.projectors):
            cx, cy = self._get_canvas_pos(i)
            group, local_idx = self._local_idx(i)
            key = (group, local_idx)
            is_selected = key in self.pdf.selected_lamps
            is_hover    = (i == self._hover_index)

            self._draw_fixture(painter, cx, cy, proj, is_selected, is_hover)

            if not self.compact:
                # Nom (en cyan si selectionne)
                painter.setFont(font_name)
                painter.setPen(QColor("#00d4ff" if is_selected else "#888888"))
                painter.drawText(QRect(cx - 38, cy + 16, 76, 14), Qt.AlignCenter,
                                 (proj.name[:11] if proj.name else group[:11]))

                # Adresse DMX discrete
                painter.setFont(font_ch)
                painter.setPen(QColor("#333333"))
                painter.drawText(QRect(cx - 26, cy + 28, 52, 12), Qt.AlignCenter,
                                 f"U{getattr(proj,'universe',0)+1} CH {proj.start_address}")

        # ── Rubber band ───────────────────────────────────────────
        if self._rubber_rect and not self._rubber_rect.isNull():
            painter.setPen(QPen(QColor("#00d4ff"), 1, Qt.DashLine))
            painter.setBrush(QColor(0, 212, 255, 18))
            painter.drawRect(self._rubber_rect)

        # ── Smart Guides ──────────────────────────────────────────
        if self._guides:
            self._draw_guides(painter, W, H)

        # ── Tooltip survol (masque pendant drag) ─────────────────
        if self._hover_index is not None and self._drag_index is None:
            hx, hy = self._get_canvas_pos(self._hover_index)
            self._draw_hover_card(painter, hx, hy, self.pdf.projectors[self._hover_index])

        # ── Barre de statut (bas du canvas) ──────────────────────
        n_fix = len(self.pdf.projectors)
        n_sel = len(self.pdf.selected_lamps)
        painter.fillRect(QRect(0, H - SB_H, W, SB_H), QColor("#080808"))
        painter.setPen(QPen(QColor("#1a1a1a"), 1))
        painter.drawLine(0, H - SB_H, W, H - SB_H)

        info_left = f"  {n_fix} fixture{'s' if n_fix != 1 else ''}"
        if n_sel:
            sel_word = tr("pdf_status_selected_pl") if n_sel > 1 else tr("pdf_status_selected")
            info_left += f"  /  {n_sel} {sel_word}{'s' if n_sel != 1 else ''}"
        if self._editable:
            info_right = tr("pdf_status_hint_edit")
        else:
            info_right = tr("pdf_status_hint_view")

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#3a3a3a"))
        painter.drawText(QRect(0, H - SB_H, W,   SB_H), Qt.AlignVCenter | Qt.AlignLeft,  info_left)
        painter.setPen(QColor("#1e1e1e"))
        painter.drawText(QRect(0, H - SB_H, W-4, SB_H), Qt.AlignVCenter | Qt.AlignRight, info_right)

        painter.end()

    # ── Interactions souris ─────────────────────────────────────────

    def mousePressEvent(self, event):
        pos = event.pos()
        idx = self._fixture_at(pos)

        if event.button() == Qt.LeftButton:
            # Clic sur le faisceau d'une Moving Head → drag pan/tilt (en attente de mouvement)
            beam_idx = self._beam_at(pos)
            if beam_idx is not None and idx is None:
                proj = self.pdf.projectors[beam_idx]
                group, local_idx = self._local_idx(beam_idx)
                key = (group, local_idx)
                if key in self.pdf.selected_lamps and self.pdf.selected_lamps:
                    targets = []
                    for j, p in enumerate(self.pdf.projectors):
                        gj, lj = self._local_idx(j)
                        if (gj, lj) in self.pdf.selected_lamps and getattr(p, 'fixture_type', '') == 'Moving Head':
                            targets.append(p)
                else:
                    targets = [proj]
                # Mémoriser le beam cliqué SANS commettre le drag :
                # on attend de voir si l'utilisateur bouge vraiment (> 5 px).
                # En attendant, on laisse le rubber-band démarrer normalement.
                self._pending_beam = {
                    'beam_idx': beam_idx,
                    'pos':      pos,
                    'proj':     proj,
                    'targets':  targets,
                }
                # Démarrer aussi le rubber-band (sera annulé si le drag beam se confirme)
                if not (event.modifiers() & Qt.ControlModifier):
                    self.pdf.selected_lamps.clear()
                if self._pt_floater is not None:
                    self._pt_floater.hide_floater()
                self._rubber_origin = pos
                self._rubber_rect   = QRect(pos, QSize())
                self.update()
                return

            if idx is not None:
                group, local_idx = self._local_idx(idx)
                key = (group, local_idx)
                if event.modifiers() & Qt.ControlModifier:
                    if key in self.pdf.selected_lamps:
                        self.pdf.selected_lamps.discard(key)
                    else:
                        self.pdf.selected_lamps.add(key)
                elif key not in self.pdf.selected_lamps:
                    self.pdf.selected_lamps = {key}
                # Drag uniquement en mode edition
                if self._editable:
                    cx, cy = self._get_canvas_pos(idx)
                    self._drag_index  = idx
                    self._drag_offset = pos - QPoint(cx, cy)
                    g_cnt = {}
                    self._drag_starts = {}
                    for j, p in enumerate(self.pdf.projectors):
                        li = g_cnt.get(p.group, 0)
                        if (p.group, li) in self.pdf.selected_lamps:
                            self._drag_starts[j] = self._get_norm_pos(j)
                        g_cnt[p.group] = li + 1
                self.update()
            else:
                if not (event.modifiers() & Qt.ControlModifier):
                    self.pdf.selected_lamps.clear()
                # Cacher le floater si on clique dans le vide
                if self._pt_floater is not None:
                    self._pt_floater.hide_floater()
                self._rubber_origin = pos
                self._rubber_rect   = QRect(pos, QSize())
                self.update()

        elif event.button() == Qt.RightButton:
            if idx is not None:
                group, local_idx = self._local_idx(idx)
                key = (group, local_idx)
                if key not in self.pdf.selected_lamps:
                    self.pdf.selected_lamps = {key}
                    self.update()
                self.pdf._show_fixture_context_menu(event.globalPos(), idx)
            else:
                self.pdf._show_canvas_context_menu(event.globalPos(), event.pos())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._editable:
            idx = self._fixture_at(event.pos())
            if idx is not None:
                self.pdf._edit_fixture(idx)

    def _resolve_overlaps(self, canvas_w, canvas_h, dragged_set):
        """Pousse les fixtures non-draguées qui chevauchent une fixture draguée."""
        r = 9 if self.compact else 13
        min_sep = r * 2 + 6   # distance min centre à centre (pixels)
        SB_H = 22
        x_min, x_max = 0.05, 0.95
        y_min = 0.06
        y_max = 1.0 - 0.05 - SB_H / max(canvas_h, 1)

        for i, pi in enumerate(self.pdf.projectors):
            if i in dragged_set:
                continue
            if pi.canvas_x is None or pi.canvas_y is None:
                continue  # Fixture auto-positionnée, ne pas forcer sa position
            xi = pi.canvas_x * canvas_w
            yi = pi.canvas_y * canvas_h

            for j in dragged_set:
                pj = self.pdf.projectors[j]
                xj = (pj.canvas_x or 0.5) * canvas_w
                yj = (pj.canvas_y or 0.5) * canvas_h

                dx, dy = xi - xj, yi - yj
                dist = math.sqrt(dx * dx + dy * dy)

                if dist < min_sep:
                    if dist > 0.5:
                        scale = min_sep / dist
                        xi = xj + dx * scale
                        yi = yj + dy * scale
                    else:
                        xi = xj + min_sep   # chevauchement exact : décaler à droite
                    pi.canvas_x = max(x_min, min(x_max, xi / canvas_w))
                    pi.canvas_y = max(y_min, min(y_max, yi / canvas_h))
                    xi = pi.canvas_x * canvas_w
                    yi = pi.canvas_y * canvas_h

    def _fixture_bbox_px(self, i):
        """Retourne (cx, cy, hw, hh) en pixels pour la fixture i (demi-largeur / demi-hauteur)."""
        cx, cy = self._get_canvas_pos(i)
        r = 9 if self.compact else 13
        ftype = getattr(self.pdf.projectors[i], 'fixture_type', 'PAR LED')
        if ftype == "Barre LED":
            hw = int(r * 1.23)
            hh = max(3, int(r * 0.38))
        elif ftype == "Machine a fumee":
            hw = int(r * 0.92)
            hh = max(3, int(r * 0.46))
        else:
            hw = hh = r
        return cx, cy, hw, hh

    def _compute_snap_guides(self, raw_x, raw_y, canvas_w, canvas_h, dragged_set):
        """
        Calcule le snap et les guides visuels en O(n).
        Retourne (snapped_norm_x, snapped_norm_y, guides_list).
        """
        SNAP_PX   = 8   # Seuil de snap en pixels
        ALIGN_THR = 8   # Tolérance d'alignement pour afficher la distance

        px = raw_x * canvas_w
        py = raw_y * canvas_h

        # Bbox de la fixture principale draguée
        drag_idx        = next(iter(dragged_set))
        _, _, dhw, dhh  = self._fixture_bbox_px(drag_idx)

        best_x, best_dx = px, SNAP_PX + 1
        best_y, best_dy = py, SNAP_PX + 1
        guides          = []

        # Snap au centre du canvas
        cx_mid = canvas_w * 0.5
        cy_mid = canvas_h * 0.5
        dx = abs(px - cx_mid)
        if dx < SNAP_PX and dx < best_dx:
            best_x, best_dx = cx_mid, dx
        dy = abs(py - cy_mid)
        if dy < SNAP_PX and dy < best_dy:
            best_y, best_dy = cy_mid, dy

        # Listes de fixtures alignées (candidats mesure de distance)
        aligned_h = []   # alignées horizontalement (même Y ± ALIGN_THR)
        aligned_v = []   # alignées verticalement   (même X ± ALIGN_THR)

        # ── Boucle unique O(n) ────────────────────────────────────────
        for i in range(len(self.pdf.projectors)):
            if i in dragged_set:
                continue
            ocx, ocy, ohw, ohh = self._fixture_bbox_px(i)

            # Snap X (axe vertical — aligner les centres X)
            dx = abs(px - ocx)
            if dx < SNAP_PX and dx < best_dx:
                best_x, best_dx = ocx, dx

            # Snap Y (axe horizontal — aligner les centres Y)
            dy = abs(py - ocy)
            if dy < SNAP_PX and dy < best_dy:
                best_y, best_dy = ocy, dy

            # Candidats mesure bord-à-bord
            if abs(py - ocy) <= ALIGN_THR:
                aligned_h.append((ocx, ocy, ohw, ohh))
            if abs(px - ocx) <= ALIGN_THR:
                aligned_v.append((ocx, ocy, ohw, ohh))

        snapped_x = best_x / canvas_w
        snapped_y = best_y / canvas_h

        # Guides d'alignement (lignes cyan pointillées)
        if best_dx <= SNAP_PX:
            guides.append({'type': 'v', 'x': snapped_x})
        if best_dy <= SNAP_PX:
            guides.append({'type': 'h', 'y': snapped_y})

        spx = best_x   # position snappée en pixels
        spy = best_y

        # ── Mesures de distance horizontales (bord droit drag ↔ bord gauche other) ──
        for (ocx, ocy, ohw, ohh) in aligned_h:
            if spx <= ocx:
                e_drag  = spx + dhw   # bord droit de la fixture draguée
                e_other = ocx - ohw   # bord gauche de l'autre fixture
            else:
                e_drag  = spx - dhw   # bord gauche drag
                e_other = ocx + ohw   # bord droit other
            gap = int(e_other - e_drag) if spx <= ocx else int(e_drag - e_other)
            if gap < 0:
                continue              # chevauchement : pas d'affichage
            guides.append({
                'type': 'dist_h',
                'x1':   min(e_drag, e_other) / canvas_w,
                'x2':   max(e_drag, e_other) / canvas_w,
                'y':    spy / canvas_h,
                'gap':  gap,
            })

        # ── Mesures de distance verticales (bord bas drag ↔ bord haut other) ──
        for (ocx, ocy, ohw, ohh) in aligned_v:
            if spy <= ocy:
                e_drag  = spy + dhh   # bord bas drag
                e_other = ocy - ohh   # bord haut other
            else:
                e_drag  = spy - dhh   # bord haut drag
                e_other = ocy + ohh   # bord bas other
            gap = int(e_other - e_drag) if spy <= ocy else int(e_drag - e_other)
            if gap < 0:
                continue
            guides.append({
                'type': 'dist_v',
                'y1':   min(e_drag, e_other) / canvas_h,
                'y2':   max(e_drag, e_other) / canvas_h,
                'x':    spx / canvas_w,
                'gap':  gap,
            })

        return snapped_x, snapped_y, guides

    def _draw_guides(self, painter, canvas_w, canvas_h):
        """Dessine les Smart Guides : lignes d'alignement cyan + mesures de distance."""
        pen_align = QPen(QColor(0, 212, 255, 160), 1, Qt.DashLine)
        pen_align.setDashPattern([6, 4])
        pen_dist  = QPen(QColor(0, 212, 255, 210), 1)
        font_dist = QFont("Segoe UI", 8)
        font_dist.setBold(True)

        for g in self._guides:
            gtype = g.get('type')

            if gtype == 'v':
                gx = int(g['x'] * canvas_w)
                painter.setPen(pen_align)
                painter.drawLine(gx, 0, gx, canvas_h)

            elif gtype == 'h':
                gy = int(g['y'] * canvas_h)
                painter.setPen(pen_align)
                painter.drawLine(0, gy, canvas_w, gy)

            elif gtype == 'dist_h':
                x1_px = int(g['x1'] * canvas_w)
                x2_px = int(g['x2'] * canvas_w)
                y_px  = int(g['y']  * canvas_h)
                gap   = g['gap']
                mid_x = (x1_px + x2_px) // 2

                painter.setPen(pen_dist)
                painter.drawLine(x1_px, y_px, x2_px, y_px)
                painter.drawLine(x1_px, y_px - 5, x1_px, y_px + 5)
                painter.drawLine(x2_px, y_px - 5, x2_px, y_px + 5)

                label = f"{gap} px"
                painter.setFont(font_dist)
                fm = painter.fontMetrics()
                lw = fm.horizontalAdvance(label) + 10
                lh = 16
                lx = mid_x - lw // 2
                ly = y_px - lh - 5
                if ly < 2:
                    ly = y_px + 7
                painter.fillRect(QRect(lx, ly, lw, lh), QColor(0, 0, 0, 200))
                painter.setPen(QPen(QColor(0, 212, 255, 70), 1))
                painter.drawRect(QRect(lx, ly, lw, lh))
                painter.setPen(QColor(0, 212, 255, 255))
                painter.drawText(QRect(lx, ly, lw, lh), Qt.AlignCenter, label)

            elif gtype == 'dist_v':
                y1_px = int(g['y1'] * canvas_h)
                y2_px = int(g['y2'] * canvas_h)
                x_px  = int(g['x']  * canvas_w)
                gap   = g['gap']
                mid_y = (y1_px + y2_px) // 2

                painter.setPen(pen_dist)
                painter.drawLine(x_px, y1_px, x_px, y2_px)
                painter.drawLine(x_px - 5, y1_px, x_px + 5, y1_px)
                painter.drawLine(x_px - 5, y2_px, x_px + 5, y2_px)

                label = f"{gap} px"
                painter.setFont(font_dist)
                fm = painter.fontMetrics()
                lw = fm.horizontalAdvance(label) + 10
                lh = 16
                lx = x_px + 8
                ly = mid_y - lh // 2
                if lx + lw > canvas_w - 4:
                    lx = x_px - lw - 8
                painter.fillRect(QRect(lx, ly, lw, lh), QColor(0, 0, 0, 200))
                painter.setPen(QPen(QColor(0, 212, 255, 70), 1))
                painter.drawRect(QRect(lx, ly, lw, lh))
                painter.setPen(QColor(0, 212, 255, 255))
                painter.drawText(QRect(lx, ly, lw, lh), Qt.AlignCenter, label)

    def mouseMoveEvent(self, event):
        pos = event.pos()

        # ── Beam en attente : commit si > 5 px de mouvement ──────
        if self._pending_beam is not None and (event.buttons() & Qt.LeftButton):
            if (pos - self._pending_beam['pos']).manhattanLength() > 5:
                pb = self._pending_beam
                self._pending_beam      = None
                self._rubber_origin     = None
                self._rubber_rect       = None
                proj    = pb['proj']
                targets = pb['targets']
                self._beam_drag_idx     = pb['beam_idx']
                self._beam_drag_start   = pb['pos']
                self._beam_drag_pt0     = (getattr(proj, 'pan', 128), getattr(proj, 'tilt', 128))
                self._beam_drag_targets = [(p, getattr(p, 'pan', 128), getattr(p, 'tilt', 128)) for p in targets]
                for p in targets:
                    if p.level == 0:
                        p.level = 100
                        p.color = QColor(p.base_color.red(), p.base_color.green(), p.base_color.blue())
                self.setCursor(Qt.CrossCursor)
                # tomber dans le handler beam ci-dessous au prochain move

        # ── Drag faisceau Pan/Tilt ────────────────────────────────
        if self._beam_drag_idx is not None and (event.buttons() & Qt.LeftButton):
            import math as _m
            r = 9 if self.compact else 13
            beam_len_max = float(r * 2 + r * 7)  # beam_len à tilt=255

            if len(self._beam_drag_targets) == 1:
                # Une seule fixture : le faisceau pointe absolument vers le curseur
                p, _, _ = self._beam_drag_targets[0]
                cx, cy = self._get_canvas_pos(self._beam_drag_idx)
                dx, dy = pos.x() - cx, pos.y() - cy
                dist = _m.sqrt(dx * dx + dy * dy)
                angle = _m.degrees(_m.atan2(dx, dy))  # axe de référence = bas
                pan_angle = max(-135.0, min(135.0, angle))
                p.pan  = int(128 + pan_angle / 135.0 * 128)
                p.tilt = int(max(0, min(255, dist / beam_len_max * 255)))
            else:
                # Plusieurs fixtures : décalage relatif commun (pan/tilt delta)
                cx, cy = self._get_canvas_pos(self._beam_drag_idx)
                # Position de référence = position de départ du premier clic
                ref_dx = self._beam_drag_start.x() - cx
                ref_dy = self._beam_drag_start.y() - cy
                ref_dist = max(1.0, _m.sqrt(ref_dx**2 + ref_dy**2))
                ref_angle = _m.degrees(_m.atan2(ref_dx, ref_dy))
                ref_pan   = int(128 + max(-135.0, min(135.0, ref_angle)) / 135.0 * 128)
                ref_tilt  = int(max(0, min(255, ref_dist / beam_len_max * 255)))

                now_dx = pos.x() - cx
                now_dy = pos.y() - cy
                now_dist  = max(1.0, _m.sqrt(now_dx**2 + now_dy**2))
                now_angle = _m.degrees(_m.atan2(now_dx, now_dy))
                now_pan   = int(128 + max(-135.0, min(135.0, now_angle)) / 135.0 * 128)
                now_tilt  = int(max(0, min(255, now_dist / beam_len_max * 255)))

                dpan  = now_pan  - ref_pan
                dtilt = now_tilt - ref_tilt
                for p, pan0, tilt0 in self._beam_drag_targets:
                    p.pan  = int(max(0, min(255, pan0 + dpan)))
                    p.tilt = int(max(0, min(255, tilt0 + dtilt)))

            if hasattr(self.pdf, '_flush_dmx'):
                self.pdf._flush_dmx()
            self.update()
            return

        if self._editable and self._drag_index is not None and (event.buttons() & Qt.LeftButton):
            w, h = max(self.width(), 1), max(self.height(), 1)
            SB_H = 22
            # Bounds = stage rectangle (4% / 5% margins, status bar at bottom)
            mx_f = 0.04; my_f = 0.05
            x_min = mx_f + 0.01; x_max = 1.0 - mx_f - 0.01
            y_min = my_f + 0.01; y_max = 1.0 - my_f - (SB_H / h) - 0.01

            new_raw = pos - self._drag_offset
            new_x   = max(x_min, min(x_max, new_raw.x() / w))
            new_y   = max(y_min, min(y_max, new_raw.y() / h))

            if event.modifiers() & Qt.ShiftModifier:
                snap  = 1.0 / 16.0
                new_x = round(new_x / snap) * snap
                new_y = round(new_y / snap) * snap
                self._guides = []
            else:
                # Smart Guides : snap aux axes des autres fixtures
                dragged = set(self._drag_starts.keys()) or {self._drag_index}
                snapped_x, snapped_y, self._guides = self._compute_snap_guides(
                    new_x, new_y, w, h, dragged)
                new_x = max(x_min, min(x_max, snapped_x))
                new_y = max(y_min, min(y_max, snapped_y))

            orig = self._drag_starts.get(self._drag_index, (None, None))
            if orig[0] is not None:
                dx, dy = new_x - orig[0], new_y - orig[1]
                for j, (ox, oy) in self._drag_starts.items():
                    p = self.pdf.projectors[j]
                    p.canvas_x = max(x_min, min(x_max, ox + dx))
                    p.canvas_y = max(y_min, min(y_max, oy + dy))
            else:
                proj = self.pdf.projectors[self._drag_index]
                proj.canvas_x = new_x
                proj.canvas_y = new_y

            # Anti-overlap : pousser les fixtures non-draguées qui chevauchent.
            # Désactivé quand des Smart Guides snappent : l'anti-overlap fighterait
            # la fixture cible de l'alignement en la poussant au loin à chaque frame.
            if not self._guides:
                self._resolve_overlaps(w, h, set(self._drag_starts.keys()) or {self._drag_index})
            self.update()

        elif self._rubber_origin is not None and (event.buttons() & Qt.LeftButton):
            self._rubber_rect = QRect(self._rubber_origin, pos).normalized()
            self.update()

        else:
            new_hover = self._fixture_at(pos)
            if new_hover != self._hover_index:
                self._hover_index = new_hover
                self.update()
            # Curseur contextuel (priorité : faisceau > fixture)
            on_beam = self._beam_at(pos) is not None and new_hover is None
            if on_beam:
                self.setCursor(Qt.CrossCursor)
            elif new_hover is not None and self._editable:
                self.setCursor(Qt.SizeAllCursor)
            elif new_hover is not None:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Annuler le beam en attente (l'utilisateur n'a pas draggé assez)
            if self._pending_beam is not None:
                self._pending_beam = None
            if self._beam_drag_idx is not None:
                self._beam_drag_idx     = None
                self._beam_drag_start   = None
                self._beam_drag_pt0     = None
                self._beam_drag_targets = []
                self.setCursor(Qt.ArrowCursor)
                self.update()
                return
            if self._drag_index is not None:
                self._drag_index  = None
                self._drag_starts = {}
                self._guides      = []   # Effacer les smart guides au release
                if self.pdf.main_window and hasattr(self.pdf.main_window, 'save_dmx_patch_config'):
                    self.pdf.main_window.save_dmx_patch_config()
            elif self._rubber_rect and self._rubber_origin is not None:
                for i in range(len(self.pdf.projectors)):
                    cx, cy = self._get_canvas_pos(i)
                    if self._rubber_rect.contains(QPoint(cx, cy)):
                        group, local_idx = self._local_idx(i)
                        self.pdf.selected_lamps.add((group, local_idx))
                self._rubber_rect   = None
                self._rubber_origin = None
                self.update()

    def leaveEvent(self, event):
        if self._hover_index is not None:
            self._hover_index = None
            self.update()

    # ── Clavier ─────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_A and (event.modifiers() & Qt.ControlModifier):
            for i in range(len(self.pdf.projectors)):
                group, local_idx = self._local_idx(i)
                self.pdf.selected_lamps.add((group, local_idx))
            self.update()
        elif event.key() == Qt.Key_Escape:
            self.pdf.selected_lamps.clear()
            self.update()
        elif event.key() == Qt.Key_Delete:
            if hasattr(self.pdf, '_delete_selected_fixtures'):
                self.pdf._delete_selected_fixtures()
        elif event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            if not self._editable or not self.pdf.selected_lamps:
                super().keyPressEvent(event)
                return
            step_px = 10 if (event.modifiers() & Qt.ShiftModifier) else 1
            cw = max(self.width(),  1)
            ch = max(self.height(), 1)
            dx = dy = 0.0
            if event.key() == Qt.Key_Left:  dx = -step_px / cw
            if event.key() == Qt.Key_Right: dx =  step_px / cw
            if event.key() == Qt.Key_Up:    dy = -step_px / ch
            if event.key() == Qt.Key_Down:  dy =  step_px / ch
            x_min, x_max = 0.03, 0.97
            y_min, y_max = 0.04, 0.96
            # Convertir selected_lamps en indices globaux
            g_cnt = {}
            for i, p in enumerate(self.pdf.projectors):
                li = g_cnt.get(p.group, 0)
                g_cnt[p.group] = li + 1
                if (p.group, li) in self.pdf.selected_lamps:
                    if p.canvas_x is None:
                        p.canvas_x, p.canvas_y = 0.5, 0.5
                    p.canvas_x = max(x_min, min(x_max, p.canvas_x + dx))
                    p.canvas_y = max(y_min, min(y_max, p.canvas_y + dy))
            self.update()
            if self.pdf.main_window and hasattr(self.pdf.main_window, 'save_dmx_patch_config'):
                self.pdf.main_window.save_dmx_patch_config()
        else:
            super().keyPressEvent(event)


# ── PlanDeFeu ─────────────────────────────────────────────────────────────────

class PlanDeFeu(QFrame):
    """Visualisation du plan de feu - canvas 2D libre"""

    def __init__(self, projectors, main_window=None, show_toolbar=True):
        super().__init__()
        self.setFocusPolicy(Qt.ClickFocus)
        self.projectors = projectors
        self.main_window = main_window
        self.selected_lamps = set()   # set of (group, local_idx)
        self._htp_overrides = None    # dict {id(proj): (level, QColor)} ou None
        self._canvas_editable = False  # Vue principale : lecture seule (edition dans Patch DMX)
        self._effects = {}            # id(proj) -> _EffectState
        self._custom_groups = {}      # nom → frozenset of (group, local_idx)
        self._load_custom_groups()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Barre d'outils ──────────────────────────────────────────
        if show_toolbar:
            toolbar = QHBoxLayout()
            toolbar.setContentsMargins(0, 0, 0, 0)

            _PARAM_SS = (
                "QPushButton { background: #1e1e1e; color: #aaa; border: 1px solid #3a3a3a; "
                "border-radius: 4px; font-size: 13px; } "
                "QPushButton:hover { background: #2a2a2a; color: #fff; border-color: #0077bb; }"
            )
            if main_window is not None and hasattr(main_window, 'show_dmx_patch_config'):
                patch_btn = QPushButton("⚙")
                patch_btn.setFixedSize(26, 26)
                patch_btn.setToolTip("Patch DMX — configuration des adresses de canaux")
                patch_btn.setStyleSheet(_PARAM_SS)
                patch_btn.clicked.connect(main_window.show_dmx_patch_config)
                toolbar.addWidget(patch_btn)
                toolbar.addSpacing(4)

            toolbar.addStretch()

            _BTN_SS = (
                "QPushButton {{ background: #1e1e1e; color: {fg}; border: 1px solid {bd}; "
                "border-radius: 4px; font-size: 9px; font-weight: bold; }} "
                "QPushButton:hover {{ background: #2a2a2a; color: {fgh}; border-color: {bdh}; }} "
                "QPushButton:pressed {{ background: #333; }}"
            )

            selec_btn = QPushButton("SELEC")
            selec_btn.setFixedSize(46, 26)
            selec_btn.setToolTip(tr("pdf_tooltip_selec"))
            selec_btn.setStyleSheet(
                _BTN_SS.format(fg="#aaa", bd="#3a3a3a", fgh="#fff", bdh="#0077bb")
            )
            selec_btn.clicked.connect(self._show_select_menu)
            toolbar.addWidget(selec_btn)
            toolbar.addSpacing(2)

            clr_btn = QPushButton("CLEAR")
            clr_btn.setFixedSize(46, 26)
            clr_btn.setToolTip(tr("pdf_tooltip_clear"))
            clr_btn.setStyleSheet(
                _BTN_SS.format(fg="#888", bd="#3a3a3a", fgh="#fff", bdh="#555")
            )
            clr_btn.clicked.connect(self._clear_plan_de_feu)
            toolbar.addWidget(clr_btn)
            toolbar.addSpacing(2)

            self.dmx_toggle_btn = QPushButton("ON")
            self.dmx_toggle_btn.setCheckable(True)
            self.dmx_toggle_btn.setChecked(True)
            self.dmx_toggle_btn.setFixedSize(44, 26)
            self.dmx_toggle_btn.setToolTip(tr("pdf_tooltip_dmx_toggle"))
            self.dmx_toggle_btn.setStyleSheet(
                _BTN_SS.format(fg="#00cc66", bd="#00cc66", fgh="#00ff88", bdh="#00ff88")
            )
            self.dmx_toggle_btn.clicked.connect(self._toggle_dmx_output)
            toolbar.addWidget(self.dmx_toggle_btn)

            root.addLayout(toolbar)
        else:
            # Stub pour éviter les AttributeError dans set_dmx_blocked
            self.dmx_toggle_btn = QPushButton()
            self.dmx_toggle_btn.setVisible(False)

        # ── Canvas ─────────────────────────────────────────────────
        self.canvas = FixtureCanvas(self)
        self.canvas.compact = True
        root.addWidget(self.canvas)

        self._dirty = True  # Redessiner seulement si les données ont changé

        # Timer de refresh — 50 ms quand strobe actif, 100 ms sinon
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._timer_tick)
        self.timer.start(50)

    def _timer_tick(self):
        has_strobe = any(getattr(p, 'strobe_speed', 0) > 0 for p in self.projectors)
        # Adapter la fréquence dynamiquement
        interval = 40 if has_strobe else 100
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        self._dirty = True  # Toujours redessiner pour refléter l'état live des projecteurs
        self.refresh()
        self._tick_effects()

    # ── API externe (identique a l'ancienne version) ────────────────

    @property
    def lamps(self):
        """Liste de (group, local_idx, None) pour compatibilite"""
        result = []
        group_counters = {}
        for proj in self.projectors:
            g = proj.group
            li = group_counters.get(g, 0)
            group_counters[g] = li + 1
            result.append((g, li, None))
        return result

    def refresh(self):
        if self._dirty:
            self.canvas.update()
            self._dirty = False

    def mark_dirty(self):
        """Signale qu'un repaint est nécessaire au prochain tick."""
        self._dirty = True

    def _tick_effects(self):
        """Applique les effets automatiques Pan/Tilt à 10 fps."""
        if not self._effects:
            return
        dead = []
        for proj_id, state in self._effects.items():
            # Retrouver le projecteur
            proj = next((p for p in self.projectors if id(p) == proj_id), None)
            if proj is None:
                dead.append(proj_id)
                continue
            pan, tilt = state.tick()
            proj.pan  = pan
            proj.tilt = tilt
        for proj_id in dead:
            del self._effects[proj_id]
        if self.main_window and hasattr(self.main_window, 'dmx') and self.main_window.dmx:
            self.main_window.dmx.update_from_projectors(self.projectors)
        self.canvas.update()

    def start_effect(self, projectors, effect, speed, amplitude):
        """Démarre un effet sur une liste de projecteurs."""
        for proj in projectors:
            self._effects[id(proj)] = _EffectState(
                effect, speed, amplitude,
                center_pan=getattr(proj, 'pan', 128),
                center_tilt=getattr(proj, 'tilt', 128)
            )

    def stop_effect(self, projectors):
        """Stoppe l'effet sur une liste de projecteurs."""
        for proj in projectors:
            self._effects.pop(id(proj), None)

    def set_htp_overrides(self, overrides):
        if overrides != self._htp_overrides:
            self._htp_overrides = overrides
            self._dirty = True

    def set_dmx_blocked(self):
        self.dmx_toggle_btn.setChecked(False)
        self.dmx_toggle_btn.setText("OFF")
        self.dmx_toggle_btn.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #cc3333; "
            "border-radius: 4px; font-size: 10px; font-weight: bold; } "
            "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #ff4444; } "
            "QPushButton:pressed { background: #333; }"
        )

    def set_dmx_unblocked(self):
        """Réactive le toggle DMX après une reconnexion de licence."""
        self.dmx_toggle_btn.setChecked(True)
        self.dmx_toggle_btn.setText("ON")
        self.dmx_toggle_btn.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #00cc66; border: 1px solid #00cc66; "
            "border-radius: 4px; font-size: 10px; font-weight: bold; } "
            "QPushButton:hover { background: #2a2a2a; color: #00ff88; border-color: #00ff88; } "
            "QPushButton:pressed { background: #333; }"
        )

    def is_dmx_enabled(self):
        return self.dmx_toggle_btn.isChecked()

    def _flush_dmx(self):
        """Envoie immédiatement l'état des projecteurs en DMX."""
        if self.main_window and hasattr(self.main_window, 'dmx') and self.main_window.dmx:
            self.main_window.dmx.update_from_projectors(self.projectors)

    # ── DMX toggle ──────────────────────────────────────────────────

    def _toggle_dmx_output(self):
        if self.main_window and hasattr(self.main_window, '_license'):
            if not self.main_window._license.dmx_allowed:
                self.dmx_toggle_btn.setChecked(False)
                self.dmx_toggle_btn.setText("OFF")
                from PySide6.QtWidgets import QMessageBox as _QMB
                state = self.main_window._license.state
                from license_manager import LicenseState
                if state == LicenseState.TRIAL_EXPIRED:
                    msg = tr("pdf_dmx_trial_expired_msg")
                elif state == LicenseState.LICENSE_EXPIRED:
                    msg = tr("pdf_dmx_lic_expired_msg")
                else:
                    msg = tr("pdf_dmx_not_activated_msg")
                _QMB.warning(self.main_window, tr("pdf_artnet_output_title"), msg)
                return
        on = self.dmx_toggle_btn.isChecked()
        self.dmx_toggle_btn.setText("ON" if on else "OFF")
        if on:
            self.dmx_toggle_btn.setStyleSheet(
                "QPushButton { background: #1e1e1e; color: #00cc66; border: 1px solid #00cc66; "
                "border-radius: 4px; font-size: 10px; font-weight: bold; } "
                "QPushButton:hover { background: #2a2a2a; color: #00ff88; border-color: #00ff88; } "
                "QPushButton:pressed { background: #333; }"
            )
        else:
            self.dmx_toggle_btn.setStyleSheet(
                "QPushButton { background: #1e1e1e; color: #cc3333; border: 1px solid #cc3333; "
                "border-radius: 4px; font-size: 10px; font-weight: bold; } "
                "QPushButton:hover { background: #2a2a2a; color: #ff4444; border-color: #ff4444; } "
                "QPushButton:pressed { background: #333; }"
            )

    # ── Selection helpers ────────────────────────────────────────────

    def _deselect_all(self):
        self.selected_lamps.clear()
        self.refresh()

    def _select_all(self):
        self.selected_lamps.clear()
        for group, local_idx, _ in self.lamps:
            self.selected_lamps.add((group, local_idx))
        self.refresh()

    def _clear_all_projectors(self):
        for proj in self.projectors:
            proj.level = 0
            proj.base_color = QColor(0, 0, 0)
            proj.color = QColor(0, 0, 0)
            # Canaux spéciaux
            proj.uv           = 0
            proj.white_boost  = 0
            proj.amber_boost  = 0
            proj.orange_boost = 0
            # Moving head
            proj.pan          = 128
            proj.tilt         = 128
            proj.gobo         = 0
            proj.gobo_rotation = 0
            proj.zoom         = 0
            proj.shutter      = 255
            proj.color_wheel  = 0
            proj.prism        = 0
            proj.prism_rotation = 0
        self.selected_lamps.clear()
        self.refresh()

    def _clear_plan_de_feu(self):
        """Éteint tous les projecteurs depuis le plan de feu et envoie le DMX."""
        self._clear_all_projectors()
        if self.main_window and hasattr(self.main_window, 'dmx') and self.main_window.dmx:
            self.main_window.dmx.update_from_projectors(self.projectors)
        if self.main_window and hasattr(self.main_window, '_log_message'):
            self.main_window._log_message("Plan de feu — CLEAR tous projecteurs", "info")

    def _select_group(self, selection):
        self.selected_lamps.clear()
        if selection == "pairs_lat_contre":
            for group, idx, _ in self.lamps:
                if group == "contre" and idx in (1, 4):
                    self.selected_lamps.add((group, idx))
                elif group == "lat":
                    self.selected_lamps.add((group, idx))
        elif selection == "impairs_lat_contre":
            for group, idx, _ in self.lamps:
                if group == "contre" and idx in (0, 2, 3, 5):
                    self.selected_lamps.add((group, idx))
        elif selection == "all_lat_contre":
            for group, idx, _ in self.lamps:
                if group in ("contre", "lat"):
                    self.selected_lamps.add((group, idx))
        else:
            for group, idx, _ in self.lamps:
                if group == selection:
                    self.selected_lamps.add((group, idx))
        self.refresh()

    # Mapping groupe interne → lettre affichée
    _GROUP_LABEL = {
        "face":    "Groupe A",
        "lat":     "Groupe B",
        "contre":  "Groupe C",
        "douche1": "Groupe D",
        "douche2": "Groupe E",
        "douche3": "Groupe F",
        "public":  "Groupe G",
        "lyre":    "Groupe H",
        "barre":   "Groupe I",
        "strobe":  "Groupe J",
        "fumee":   "Groupe K",
    }

    def _show_select_menu(self):
        """Affiche le menu de sélection des projecteurs."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #1e1e1e; color: #ccc; border: 1px solid #3a3a3a; } "
            "QMenu::item { padding: 6px 20px; } "
            "QMenu::item:selected { background: #0077bb; color: #fff; } "
            "QMenu::separator { background: #3a3a3a; height: 1px; margin: 3px 8px; }"
        )

        menu.addAction(tr("pdf_select_all"),    self._select_all)
        menu.addAction(tr("pdf_deselect_all"),  self._deselect_all)
        menu.addSeparator()

        # Groupes présents dans les projecteurs, dans l'ordre du mapping
        present_groups = {p.group for p in self.projectors}
        for internal, label in self._GROUP_LABEL.items():
            if internal in present_groups:
                menu.addAction(label, lambda g=internal: self._select_group(g))

        # Groupes non répertoriés dans le mapping
        unlisted = present_groups - set(self._GROUP_LABEL)
        for g in sorted(unlisted):
            menu.addAction(g.capitalize(), lambda grp=g: self._select_group(grp))

        # Groupes de sélection rapide personnalisés — 1 clic direct
        if self._custom_groups:
            menu.addSeparator()
            for gname, members in self._custom_groups.items():
                act = menu.addAction(f"★  {gname}  ({len(members)})")
                act.triggered.connect(lambda checked, m=members: self._select_custom_group(m))

        menu.addSeparator()
        menu.addAction(tr("pdf_add_group_from_sel"), self._open_add_group_dialog)
        if self._custom_groups:
            menu.addAction(tr("pdf_manage_groups"), self._open_group_manager)

        # Trouver le bouton SELEC pour positionner le menu
        sender = self.sender()
        if sender:
            menu.exec(sender.mapToGlobal(sender.rect().bottomLeft()))
        else:
            menu.exec(self.mapToGlobal(self.rect().topRight()))

    def _open_add_group_dialog(self):
        """Sauvegarde la sélection courante comme groupe de sélection rapide."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox

        if not self.selected_lamps:
            QMessageBox.information(self, tr("pdf_no_selection_title"), tr("pdf_no_selection_msg"))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("pdf_new_group_title"))
        dlg.setFixedSize(340, 145)
        dlg.setStyleSheet("QDialog { background: #1a1a1a; color: #ddd; }")

        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(20, 16, 20, 16)
        vl.setSpacing(12)

        count = len(self.selected_lamps)
        s = "s" if count > 1 else ""
        sp = "s" if count > 1 else ""
        lbl = QLabel(tr("pdf_new_group_lbl", count=count, s=s, sp=sp))
        lbl.setStyleSheet("font-size: 12px; color: #aaa;")
        vl.addWidget(lbl)

        inp = QLineEdit()
        inp.setPlaceholderText("ex: Backlight, FOH, Cyclo...")
        inp.setStyleSheet(
            "QLineEdit { background: #111; color: #fff; border: 1px solid #444; "
            "border-radius: 4px; padding: 5px 8px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #0077bb; }"
        )
        vl.addWidget(inp)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_cancel = QPushButton(tr("pdf_btn_cancel"))
        btn_ok = QPushButton(tr("pdf_btn_create"))
        for b, fg, bg in [(btn_cancel, "#888", "#1e1e1e"), (btn_ok, "#fff", "#007a45")]:
            b.setFixedHeight(28)
            b.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid #3a3a3a; "
                f"border-radius: 4px; font-size: 12px; font-weight: bold; }} "
                f"QPushButton:hover {{ background: {'#2a2a2a' if bg == '#1e1e1e' else '#009950'}; }}"
            )
        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        vl.addLayout(btn_row)

        inp.setFocus()
        inp.returnPressed.connect(dlg.accept)

        if dlg.exec() != QDialog.Accepted:
            return

        group_name = inp.text().strip()
        if not group_name:
            return

        # Sauvegarder la selection courante comme groupe rapide
        self._custom_groups[group_name] = frozenset(self.selected_lamps)
        self._save_custom_groups()

    def _select_custom_group(self, members):
        """Restaure la sélection d'un groupe personnalisé."""
        self.selected_lamps.clear()
        self.selected_lamps.update(members)
        self.refresh()

    @staticmethod
    def _groups_file_path():
        import pathlib
        return pathlib.Path.home() / ".mystrow_selection_groups.json"

    def _save_custom_groups(self):
        """Persiste les groupes personnalisés sur disque."""
        try:
            data = {}
            for name, members in self._custom_groups.items():
                data[name] = [[str(g), int(i)] for g, i in members]
            path = self._groups_file_path()
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[PlanDeFeu] Groupes sauvegardés ({len(data)}) → {path}")
        except Exception:
            import traceback
            print(f"[PlanDeFeu] Erreur sauvegarde groupes:")
            traceback.print_exc()

    def _load_custom_groups(self):
        """Charge les groupes personnalisés depuis le disque."""
        try:
            import pathlib
            path = self._groups_file_path()
            if not path.exists():
                print(f"[PlanDeFeu] Pas de fichier groupes: {path}")
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            for name, members in data.items():
                self._custom_groups[name] = frozenset((str(g), int(i)) for g, i in members)
            print(f"[PlanDeFeu] Groupes chargés ({len(data)}) ← {path}")
        except Exception:
            import traceback
            print(f"[PlanDeFeu] Erreur chargement groupes:")
            traceback.print_exc()

    def _delete_custom_group(self, name):
        """Supprime un groupe de sélection rapide personnalisé."""
        self._custom_groups.pop(name, None)
        self._save_custom_groups()

    def _open_group_manager(self):
        """Dialog de gestion des groupes personnalisés : réordonner, renommer, supprimer."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
            QListWidget, QListWidgetItem, QLineEdit, QMessageBox,
        )
        from PySide6.QtCore import Qt

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("pdf_manage_groups_title"))
        dlg.setMinimumSize(380, 420)
        dlg.setStyleSheet(
            "QDialog { background: #1a1a1a; color: #ddd; }"
            "QListWidget { background: #111; color: #ddd; border: 1px solid #333;"
            " border-radius: 4px; font-size: 13px; outline: none; }"
            "QListWidget::item { padding: 8px 12px; border-radius: 3px; }"
            "QListWidget::item:selected { background: #0077bb; color: #fff; }"
            "QListWidget::item:hover:!selected { background: #222; }"
            "QPushButton { background: #2a2a2a; color: #ccc; border: 1px solid #3a3a3a;"
            " border-radius: 4px; font-size: 12px; padding: 4px 12px; }"
            "QPushButton:hover { background: #333; color: #fff; }"
            "QPushButton:disabled { color: #444; border-color: #222; }"
            "QLineEdit { background: #111; color: #fff; border: 1px solid #444;"
            " border-radius: 4px; padding: 4px 8px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #0077bb; }"
        )

        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(10)

        title = QLabel(tr("pdf_groups_saved_title"))
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #fff;")
        vl.addWidget(title)

        sub = QLabel(tr("pdf_groups_reorder_hint"))
        sub.setStyleSheet("font-size: 10px; color: #666;")
        sub.setWordWrap(True)
        vl.addWidget(sub)

        lw = QListWidget()
        lw.setDragDropMode(QListWidget.InternalMove)
        lw.setSelectionMode(QListWidget.SingleSelection)
        for gname, members in self._custom_groups.items():
            s = "s" if len(members) > 1 else ""
            item = QListWidgetItem(tr("pdf_group_item_text", name=gname, n=len(members), s=s))
            item.setData(Qt.UserRole, gname)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            lw.addItem(item)
        vl.addWidget(lw, 1)

        # ── Barre de renommage ─────────────────────────────────────────────────
        rename_row = QHBoxLayout()
        rename_edit = QLineEdit()
        rename_edit.setPlaceholderText(tr("pdf_rename_new_ph"))
        rename_edit.setFixedHeight(30)
        btn_rename = QPushButton(tr("pdf_btn_rename"))
        btn_rename.setFixedHeight(30)
        btn_rename.setEnabled(False)
        rename_row.addWidget(rename_edit, 1)
        rename_row.addWidget(btn_rename)
        vl.addLayout(rename_row)

        # ── Boutons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_up  = QPushButton("▲")
        btn_dn  = QPushButton("▼")
        btn_del = QPushButton(tr("pdf_btn_delete_group"))
        btn_del.setStyleSheet(
            "QPushButton { background: #2a0000; color: #cc4444; border: 1px solid #3a1111;"
            " border-radius: 4px; font-size: 12px; padding: 4px 12px; }"
            "QPushButton:hover { background: #440000; color: #ff6666; }"
            "QPushButton:disabled { color: #444; border-color: #222; }"
        )
        for b in (btn_up, btn_dn, btn_del):
            b.setFixedHeight(30)
            b.setEnabled(False)
        btn_row.addWidget(btn_up)
        btn_row.addWidget(btn_dn)
        btn_row.addStretch()
        btn_row.addWidget(btn_del)
        vl.addLayout(btn_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #2a2a2a;")
        vl.addWidget(sep)

        close_row = QHBoxLayout()
        btn_close = QPushButton(tr("pdf_btn_close"))
        btn_close.setFixedHeight(32)
        btn_close.clicked.connect(dlg.accept)
        close_row.addStretch()
        close_row.addWidget(btn_close)
        vl.addLayout(close_row)

        # ── Logique ────────────────────────────────────────────────────────────
        def _on_selection():
            has = lw.currentRow() >= 0
            btn_up.setEnabled(has and lw.currentRow() > 0)
            btn_dn.setEnabled(has and lw.currentRow() < lw.count() - 1)
            btn_del.setEnabled(has)
            btn_rename.setEnabled(has)
            if has:
                name = lw.currentItem().data(Qt.UserRole)
                rename_edit.setText(name)

        def _move(delta):
            row = lw.currentRow()
            if row < 0:
                return
            new_row = row + delta
            if new_row < 0 or new_row >= lw.count():
                return
            item = lw.takeItem(row)
            lw.insertItem(new_row, item)
            lw.setCurrentRow(new_row)
            _apply_order()

        def _apply_order():
            new_groups = {}
            for i in range(lw.count()):
                name = lw.item(i).data(Qt.UserRole)
                if name in self._custom_groups:
                    new_groups[name] = self._custom_groups[name]
            self._custom_groups.clear()
            self._custom_groups.update(new_groups)
            self._save_custom_groups()

        def _do_rename():
            row = lw.currentRow()
            if row < 0:
                return
            old_name = lw.item(row).data(Qt.UserRole)
            new_name = rename_edit.text().strip()
            if not new_name or new_name == old_name:
                return
            if new_name in self._custom_groups:
                QMessageBox.warning(dlg, tr("pdf_existing_name_title"),
                                    tr("pdf_existing_name_msg", name=new_name))
                return
            members = self._custom_groups.pop(old_name)
            # Reconstruire le dict en conservant l'ordre
            new_groups = {}
            for i in range(lw.count()):
                n = lw.item(i).data(Qt.UserRole)
                new_groups[new_name if n == old_name else n] = (
                    members if n == old_name else self._custom_groups.get(n)
                )
            self._custom_groups.clear()
            self._custom_groups.update(new_groups)
            self._save_custom_groups()
            item = lw.item(row)
            item.setData(Qt.UserRole, new_name)
            s = "s" if len(members) > 1 else ""
            item.setText(tr("pdf_group_item_text", name=new_name, n=len(members), s=s))

        def _do_delete():
            row = lw.currentRow()
            if row < 0:
                return
            name = lw.item(row).data(Qt.UserRole)
            rep = QMessageBox.question(
                dlg, tr("pdf_delete_group_title"),
                tr("pdf_delete_group_msg", name=name),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if rep != QMessageBox.Yes:
                return
            self._custom_groups.pop(name, None)
            self._save_custom_groups()
            lw.takeItem(row)
            _on_selection()

        lw.currentRowChanged.connect(lambda _: _on_selection())
        lw.model().rowsMoved.connect(lambda *_: _apply_order())
        btn_up.clicked.connect(lambda: _move(-1))
        btn_dn.clicked.connect(lambda: _move(1))
        btn_del.clicked.connect(_do_delete)
        btn_rename.clicked.connect(_do_rename)
        rename_edit.returnPressed.connect(_do_rename)

        dlg.exec()

    # ── Couleur / dimmer ─────────────────────────────────────────────

    def _get_target_projectors(self, group, idx):
        targets = []
        for g, i in self.selected_lamps:
            projs = [p for p in self.projectors if p.group == g]
            if i < len(projs):
                targets.append((projs[i], g, i))
        if not targets:
            projs = [p for p in self.projectors if p.group == group]
            if idx < len(projs):
                targets.append((projs[idx], group, idx))
        return targets

    def _apply_color_to_targets(self, targets, color, close_menu=None):
        for proj, g, i in targets:
            proj.base_color = color
            if proj.level == 0:
                proj.level = 100
            brightness = proj.level / 100.0
            proj.color = QColor(
                int(color.red() * brightness),
                int(color.green() * brightness),
                int(color.blue() * brightness)
            )
        if self.main_window and hasattr(self.main_window, 'dmx') and self.main_window.dmx:
            self.main_window.dmx.update_from_projectors(self.projectors)
        self.canvas.update()
        if close_menu:
            close_menu.close()

    def _set_dimmer_for_targets(self, targets, level):
        for proj, g, i in targets:
            self.set_projector_dimmer(proj, level)

    def set_projector_dimmer(self, proj, level):
        proj.level = level
        if level > 0:
            brightness = level / 100.0
            proj.color = QColor(
                int(proj.base_color.red() * brightness),
                int(proj.base_color.green() * brightness),
                int(proj.base_color.blue() * brightness)
            )
        else:
            proj.color = QColor(0, 0, 0)
        if self.main_window and hasattr(self.main_window, 'dmx') and self.main_window.dmx:
            self.main_window.dmx.update_from_projectors(self.projectors)
        self.refresh()

    def change_projector_color_only(self, group, idx, color):
        projs = [p for p in self.projectors if p.group == group]
        if idx < len(projs):
            p = projs[idx]
            p.base_color = color
            if p.level > 0:
                brightness = p.level / 100.0
                p.color = QColor(
                    int(color.red() * brightness),
                    int(color.green() * brightness),
                    int(color.blue() * brightness)
                )
            else:
                p.color = QColor(0, 0, 0)

    def change_projector_color(self, group, idx, color, pad_row):
        self.change_projector_color_only(group, idx, color)

    # ── Menus contextuels ────────────────────────────────────────────

    def _pos_outside(self, menu):
        """Retourne une position globale qui place le menu en dehors du plan de feu.
        Priorité : droite → gauche → bas → haut du widget."""
        from PySide6.QtGui import QGuiApplication
        screen_rect = QGuiApplication.primaryScreen().availableGeometry()
        menu_sz     = menu.sizeHint()
        widget_tl   = self.mapToGlobal(QPoint(0, 0))
        widget_rect = QRect(widget_tl, self.size())

        # Essai à droite
        x = widget_rect.right() + 4
        y = widget_tl.y() + 20
        if x + menu_sz.width() <= screen_rect.right():
            return QPoint(x, max(screen_rect.top(), min(y, screen_rect.bottom() - menu_sz.height())))

        # Essai à gauche
        x = widget_rect.left() - menu_sz.width() - 4
        if x >= screen_rect.left():
            return QPoint(x, max(screen_rect.top(), min(y, screen_rect.bottom() - menu_sz.height())))

        # Essai en bas
        x = widget_tl.x() + 20
        y = widget_rect.bottom() + 4
        if y + menu_sz.height() <= screen_rect.bottom():
            return QPoint(max(screen_rect.left(), min(x, screen_rect.right() - menu_sz.width())), y)

        # Fallback : en haut
        return QPoint(
            max(screen_rect.left(), min(x, screen_rect.right() - menu_sz.width())),
            max(screen_rect.top(), widget_rect.top() - menu_sz.height() - 4)
        )

    def _show_fixture_context_menu(self, global_pos, fixture_idx):
        proj = self.projectors[fixture_idx]
        group, local_idx = self.canvas._local_idx(fixture_idx)
        targets = self._get_target_projectors(group, local_idx)
        if not targets:
            return

        menu = _PersistentMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        _SS  = "color:#888; font-size:11px; font-weight:bold; border:none; background:transparent;"
        _SLI = """
            QSlider::groove:horizontal { background:#333; height:6px; border-radius:3px; }
            QSlider::handle:horizontal { background:#00d4ff; width:14px; height:14px;
                                         margin:-4px 0; border-radius:7px; }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #005577,stop:1 #00d4ff);
                border-radius:3px; }
        """

        def _flush(t=targets):
            if self.main_window and hasattr(self.main_window, 'dmx') and self.main_window.dmx:
                self.main_window.dmx.update_from_projectors(self.projectors)
            self.canvas.update()

        def _wa(widget):
            wa = QWidgetAction(menu)
            wa.setDefaultWidget(widget)
            menu.addAction(wa)

        # ── Titre ────────────────────────────────────────────────────────
        if len(targets) == 1:
            p0, g0, i0 = targets[0]
            info_text = f"{p0.name or (g0.capitalize() + ' ' + str(i0+1))}  (CH {p0.start_address})"
        else:
            info_text = tr("pdf_n_fixtures_selected", n=len(targets))
        lbl = QLabel(info_text)
        lbl.setStyleSheet("color:#00d4ff; font-weight:bold; font-size:12px; padding:4px 8px;")
        lbl.setAlignment(Qt.AlignCenter)
        _wa(lbl)
        menu.addSeparator()

        # ── Dimmer (EN PREMIER) ──────────────────────────────────────────
        dim_w = QWidget(); dim_h = QHBoxLayout(dim_w)
        dim_h.setContentsMargins(10, 5, 10, 5); dim_h.setSpacing(8)
        dim_lbl = QLabel(tr("pdf_dim_label")); dim_lbl.setStyleSheet(_SS)
        dim_sli = QSlider(Qt.Horizontal)
        dim_sli.setRange(0, 100); dim_sli.setValue(targets[0][0].level)
        dim_sli.setFixedWidth(150); dim_sli.setStyleSheet(_SLI)
        dim_val = QLabel(f"{targets[0][0].level}%")
        dim_val.setStyleSheet("color:#ddd; font-size:12px; font-weight:bold; min-width:34px;")
        dim_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        dim_sli.valueChanged.connect(lambda v, t=targets: self._set_dimmer_for_targets(t, v))
        dim_sli.valueChanged.connect(lambda v: dim_val.setText(f"{v}%"))
        for w in (dim_lbl, dim_sli, dim_val): dim_h.addWidget(w)
        _wa(dim_w)

        # ── Strobe (tout sauf Machine à fumée) ───────────────────────────
        if proj.fixture_type != "Machine a fumee":
            menu.addSeparator()
            strobe_w = QWidget(); strobe_h = QHBoxLayout(strobe_w)
            strobe_h.setContentsMargins(10, 5, 10, 5); strobe_h.setSpacing(8)

            strobe_lbl = QLabel(tr("pdf_strobe_label")); strobe_lbl.setStyleSheet(_SS)
            current_spd = getattr(targets[0][0], 'strobe_speed', 0)

            strobe_sli = QSlider(Qt.Horizontal)
            strobe_sli.setRange(0, 100)
            strobe_sli.setValue(current_spd)
            strobe_sli.setFixedWidth(150)
            strobe_sli.setStyleSheet(_SLI)

            strobe_val = QLabel(f"{current_spd}%" if current_spd > 0 else tr("pdf_strobe_off"))
            strobe_val.setStyleSheet("color:#ddd; font-size:12px; font-weight:bold; min-width:34px;")
            strobe_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            def _on_strobe_speed(v, t=targets):
                for p, g, i in t:
                    p.strobe_speed = v
                strobe_val.setText(f"{v}%" if v > 0 else tr("pdf_strobe_off"))
                _flush()

            strobe_sli.valueChanged.connect(_on_strobe_speed)

            for w in (strobe_lbl, strobe_sli, strobe_val):
                strobe_h.addWidget(w)
            _wa(strobe_w)

        # ── Canaux spéciaux : UV / Blanc / Ambre / Orange ────────────────────
        _proj_profile = getattr(proj, 'dmx_profile', None) or []

        _EXTRA_CHANNELS = [
            ("UV",     "UV",           "#8844ff", "uv",           0,   255),
            ("W",      "Blanc",        "#ffffff", "white_boost",  0,   255),
            ("Ambre",  "Ambre",        "#ff9900", "amber_boost",  0,   255),
            ("Orange", "Orange",       "#ff6600", "orange_boost", 0,   255),
        ]

        _extra_shown = False
        for ch_key, ch_label, ch_color, attr_name, vmin, vmax in _EXTRA_CHANNELS:
            if ch_key not in _proj_profile:
                continue
            if not _extra_shown:
                menu.addSeparator()
                _sec_lbl = QLabel("CANAUX SPÉCIAUX")
                _sec_lbl.setStyleSheet("color:#444;font-size:9px;font-weight:bold;"
                                       "padding:2px 10px;border:none;background:transparent;")
                _wa(_sec_lbl)
                _extra_shown = True

            cur_val = getattr(targets[0][0], attr_name, 0)

            # Barre de style adaptée à la couleur du canal
            _sli_extra = (
                "QSlider::groove:horizontal { background:#333; height:6px; border-radius:3px; }"
                f"QSlider::handle:horizontal {{ background:{ch_color}; width:14px; height:14px;"
                "margin:-4px 0; border-radius:7px; }"
                f"QSlider::sub-page:horizontal {{ background:{ch_color}44; border-radius:3px; }}"
            )

            ch_w = QWidget(); ch_h = QHBoxLayout(ch_w)
            ch_h.setContentsMargins(10, 4, 10, 4); ch_h.setSpacing(8)

            ch_lbl = QLabel(ch_label)
            ch_lbl.setStyleSheet(f"color:{ch_color};font-size:11px;font-weight:bold;border:none;"
                                  "background:transparent;")
            ch_lbl.setFixedWidth(52)

            ch_sli = QSlider(Qt.Horizontal)
            ch_sli.setRange(vmin, vmax); ch_sli.setValue(cur_val)
            ch_sli.setFixedWidth(140); ch_sli.setStyleSheet(_sli_extra)

            # Pourcent pour UV direct, "+" pour les boosts
            _is_boost = attr_name != "uv"
            _pct = int(cur_val / 255 * 100)
            ch_val_lbl = QLabel(
                f"{_pct}%" if not _is_boost or cur_val == 0
                else f"+{_pct}%"
            )
            ch_val_lbl.setStyleSheet("color:#ddd;font-size:12px;font-weight:bold;min-width:36px;")
            ch_val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            def _apply_special_visual(p):
                """Recalcule p.color en intégrant UV et Ambre pour le simulateur."""
                br = (p.level / 100.0) if p.level > 0 else 0.0
                r = p.base_color.red()   * br
                g = p.base_color.green() * br
                b = p.base_color.blue()  * br
                uv_f  = getattr(p, 'uv',           0) / 255.0
                amb_f = getattr(p, 'amber_boost',  0) / 255.0
                # UV → violet (#8844ff)
                r += 136 * uv_f;  g += 68 * uv_f;  b += 255 * uv_f
                # Ambre → orange (#ff9900)
                r += 255 * amb_f; g += 153 * amb_f
                p.color = QColor(min(255, int(r)), min(255, int(g)), min(255, int(b)))

            def _make_ch_cb(aname, lbl_ref, is_boost):
                def _cb(v, t=targets):
                    for p, g, i in t:
                        setattr(p, aname, v)
                        if aname in ("uv", "amber_boost"):
                            _apply_special_visual(p)
                    pct = int(v / 255 * 100)
                    lbl_ref.setText(f"+{pct}%" if is_boost and v > 0 else f"{pct}%")
                    _flush()
                return _cb

            ch_sli.valueChanged.connect(_make_ch_cb(attr_name, ch_val_lbl, _is_boost))

            for w in (ch_lbl, ch_sli, ch_val_lbl): ch_h.addWidget(w)
            _wa(ch_w)

        # ── Moving Head : PanTilt + Presets + Roue Couleur + Gobo + Prisme ──
        if proj.fixture_type == "Moving Head":
            menu.addSeparator()

            # Conteneur horizontal : pad à gauche, presets à droite
            mh_w = QWidget(); mh_h = QHBoxLayout(mh_w)
            mh_h.setContentsMargins(6, 4, 6, 4); mh_h.setSpacing(6)

            pt_pad = PanTiltPad(
                pan=getattr(targets[0][0], 'pan', 128),
                tilt=getattr(targets[0][0], 'tilt', 128)
            )
            def _on_pantilt(pan, tilt, t=targets):
                for p, g, i in t:
                    p.pan = pan; p.tilt = tilt
                _flush()
            pt_pad.changed.connect(_on_pantilt)
            mh_h.addWidget(pt_pad)

            preset_bar = PresetBar(get_current_pan_tilt=lambda: (pt_pad._pan, pt_pad._tilt))
            def _on_preset(pan, tilt, pad=pt_pad, t=targets):
                pad.set_values(pan, tilt)
                for p, g, i in t:
                    p.pan = pan; p.tilt = tilt
                _flush()
            preset_bar.preset_selected.connect(_on_preset)
            mh_h.addWidget(preset_bar)
            _wa(mh_w)

            proj_profile = getattr(targets[0][0], 'dmx_profile', None)
            has_profile = isinstance(proj_profile, list)

            _SS_BTN_ON  = ("QPushButton{background:#00d4ff;color:#000;border:none;"
                           "border-radius:4px;font-size:12px;font-weight:bold;padding:0 4px;}")
            _SS_BTN_OFF = ("QPushButton{background:#1e1e1e;color:#aaa;border:1px solid #333;"
                           "border-radius:4px;font-size:12px;padding:0 4px;}"
                           "QPushButton:hover{background:#2a2a2a;color:#fff;border-color:#555;}")

            def _slider_row(label_text, cur_val, max_val, on_change):
                """Crée une ligne label + slider + valeur numérique."""
                row_w = QWidget(); row_h = QHBoxLayout(row_w)
                row_h.setContentsMargins(10, 4, 10, 4); row_h.setSpacing(8)
                lbl = QLabel(label_text); lbl.setStyleSheet(_SS)
                sli = QSlider(Qt.Horizontal)
                sli.setRange(0, max_val); sli.setValue(cur_val)
                sli.setFixedWidth(140); sli.setStyleSheet(_SLI)
                val_lbl = QLabel(str(cur_val))
                val_lbl.setStyleSheet("color:#ddd;font-size:12px;font-weight:bold;min-width:28px;")
                val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                sli.valueChanged.connect(lambda v: val_lbl.setText(str(v)))
                sli.valueChanged.connect(on_change)
                for w in (lbl, sli, val_lbl): row_h.addWidget(w)
                return row_w

            # ── Roue de couleur ─────────────────────────────────────────
            if not has_profile or 'ColorWheel' in proj_profile:
                menu.addSeparator()
                cur_cw = getattr(targets[0][0], 'color_wheel', 0)

                def _on_cw(v, t=targets):
                    for p, g, i in t:
                        p.color_wheel = v
                        # Trouver la couleur du slot le plus proche et mettre à jour le simulateur
                        slots = getattr(p, 'color_wheel_slots', []) or [
                            {"dmx": 0,   "color": "#ffffff"}, {"dmx": 20,  "color": "#ff3300"},
                            {"dmx": 42,  "color": "#ff8800"}, {"dmx": 64,  "color": "#ffff00"},
                            {"dmx": 85,  "color": "#00cc44"}, {"dmx": 106, "color": "#00ccff"},
                            {"dmx": 128, "color": "#0044ff"}, {"dmx": 149, "color": "#cc00ff"},
                            {"dmx": 170, "color": "#ff99cc"}, {"dmx": 192, "color": "#ffee88"},
                        ]
                        passed = [s for s in slots if s["dmx"] <= v]
                        closest = max(passed, key=lambda s: s["dmx"]) if passed else min(slots, key=lambda s: s["dmx"])
                        qc = QColor(closest["color"])
                        if p.level == 0:
                            p.level = 100
                        brightness = p.level / 100.0
                        p.base_color = qc
                        p.color = QColor(
                            int(qc.red() * brightness),
                            int(qc.green() * brightness),
                            int(qc.blue() * brightness),
                        )
                    _flush()

                _wa(_slider_row("Roue couleur", cur_cw, 255, _on_cw))

                # Préférences OFL si disponibles, sinon génériques
                _ofl_cw = getattr(proj, 'color_wheel_slots', [])
                if _ofl_cw:
                    _CW_PRESETS = [
                        (s['dmx'], s['color'], s['name']) for s in _ofl_cw
                    ]
                else:
                    _CW_PRESETS = [
                        (0,   "#ffffff", "Open"),    (20,  "#ff3300", "Rouge"),
                        (42,  "#ff8800", "Orange"),  (64,  "#ffff00", "Jaune"),
                        (85,  "#00cc44", "Vert"),    (106, "#00ccff", "Cyan"),
                        (128, "#0044ff", "Bleu"),    (149, "#cc00ff", "Magenta"),
                        (170, "#ff99cc", "Rose"),    (192, "#ffee88", "CTO"),
                    ]

                cw_presets_w = QWidget(); cw_ph = QVBoxLayout(cw_presets_w)
                cw_ph.setContentsMargins(10, 0, 10, 4); cw_ph.setSpacing(2)

                # Ligne boutons de couleur + bouton Éditer
                cw_top_row = QWidget(); cw_tr = QHBoxLayout(cw_top_row)
                cw_tr.setContentsMargins(0, 0, 0, 0); cw_tr.setSpacing(3)

                cw_btns_row = QWidget(); cw_br = QHBoxLayout(cw_btns_row)
                cw_br.setContentsMargins(0, 0, 0, 0); cw_br.setSpacing(3)

                def _luminance(hex_c):
                    """Retourne True si la couleur est claire (texte noir)."""
                    c = hex_c.lstrip("#")
                    if len(c) != 6:
                        return True
                    r, g, b = int(c[0:2],16), int(c[2:4],16), int(c[4:6],16)
                    return (0.299*r + 0.587*g + 0.114*b) > 128

                # Stocker (bouton, dmx_val, hex_color) pour pouvoir re-styler après clic
                _cw_btn_refs = []

                def _restyle_cw_btns(selected_dmx):
                    for _b, _dv, _hc in _cw_btn_refs:
                        _tc = "#000" if _luminance(_hc) else "#fff"
                        _active = abs(_dv - selected_dmx) < 8
                        _border = "#00d4ff" if _active else "#555"
                        _bw = "3px" if _active else "2px"
                        _b.setStyleSheet(
                            f"QPushButton{{background:{_hc};border:{_bw} solid {_border};"
                            f"border-radius:11px;color:{_tc};font-size:8px;}}"
                            f"QPushButton:hover{{border-color:#00d4ff;}}"
                        )

                for dmx_v, hex_c, tip in _CW_PRESETS:
                    cb = QPushButton()
                    cb.setFixedSize(22, 22)
                    cb.setToolTip(f"{tip}  (DMX {dmx_v})")
                    tc = "#000" if _luminance(hex_c) else "#fff"
                    active = abs(dmx_v - cur_cw) < 8
                    border = "#00d4ff" if active else "#555"
                    bw = "3px" if active else "2px"
                    cb.setStyleSheet(
                        f"QPushButton{{background:{hex_c};border:{bw} solid {border};"
                        f"border-radius:11px;color:{tc};font-size:8px;}}"
                        f"QPushButton:hover{{border-color:#00d4ff;}}"
                    )
                    _cw_btn_refs.append((cb, dmx_v, hex_c))
                    def _on_cw_preset(chk, v=dmx_v, hc=hex_c, t=targets):
                        qc = QColor(hc)
                        for p, g, i in t:
                            p.color_wheel = v
                            if p.level == 0:
                                p.level = 100
                            brightness = p.level / 100.0
                            p.base_color = qc
                            p.color = QColor(
                                int(qc.red() * brightness),
                                int(qc.green() * brightness),
                                int(qc.blue() * brightness)
                            )
                        _restyle_cw_btns(v)
                        _flush()
                    cb.clicked.connect(_on_cw_preset)
                    cw_br.addWidget(cb)
                cw_br.addStretch()
                cw_tr.addWidget(cw_btns_row, 1)

                # Bouton éditeur de roue
                _edit_cw_btn = QPushButton("✏  Éditer")
                _edit_cw_btn.setFixedHeight(22)
                _edit_cw_btn.setToolTip("Éditer la roue de couleur de cette fixture")
                _edit_cw_btn.setStyleSheet(
                    "QPushButton{background:#1e1e1e;color:#888;border:1px solid #333;"
                    "border-radius:4px;font-size:11px;padding:0 6px;}"
                    "QPushButton:hover{border-color:#00d4ff;color:#00d4ff;background:#1a2a3a;}"
                )

                def _open_cw_editor(chk=False, _p=proj, _t=targets):
                    from color_wheel_editor import ColorWheelEditorDialog
                    menu.close()
                    all_proj = self.projectors if hasattr(self, 'projectors') else []
                    mw = self.main_window if hasattr(self, 'main_window') else None
                    dlg = ColorWheelEditorDialog(_p, all_proj, mw, self)
                    if dlg.exec():
                        # Rafraîchir l'affichage du plan de feu
                        self.refresh() if hasattr(self, 'refresh') else None

                _edit_cw_btn.clicked.connect(_open_cw_editor)
                cw_tr.addWidget(_edit_cw_btn)

                cw_ph.addWidget(cw_top_row)
                _wa(cw_presets_w)

            # ── Gobo ────────────────────────────────────────────────────
            if not has_profile or 'Gobo1' in proj_profile:
                menu.addSeparator()
                cur_gobo = getattr(targets[0][0], 'gobo', 0)

                def _on_gobo(v, t=targets):
                    for p, g, i in t:
                        p.gobo = v
                    _flush()

                _wa(_slider_row("Gobo", cur_gobo, 255, _on_gobo))

                # Boutons presets gobo — OFL si disponible, sinon génériques
                _ofl_gobo = getattr(proj, 'gobo_wheel_slots', [])
                if _ofl_gobo:
                    _GOBO_SLOTS = [
                        (s['dmx'], s['name'][:6], s['name']) for s in _ofl_gobo
                    ]
                else:
                    _GOBO_ICONS = ["○", "✦", "◈", "⊕", "⊗", "❋", "⌘", "✿"]
                    _GOBO_SLOTS = [
                        (i * 32, _GOBO_ICONS[i % len(_GOBO_ICONS)],
                         "Open" if i == 0 else f"Gobo {i}")
                        for i in range(8)
                    ]
                gobo_w = QWidget(); gobo_h = QHBoxLayout(gobo_w)
                gobo_h.setContentsMargins(10, 0, 10, 6); gobo_h.setSpacing(3)

                def _set_gobo_btn(val, t=targets, gw=gobo_w):
                    _on_gobo(val, t)
                    for b in gw.findChildren(QPushButton):
                        bv = b.property("gobo_val")
                        if bv is not None:
                            b.setStyleSheet(_SS_BTN_ON if bv == val else _SS_BTN_OFF)

                for dmx_val, icon, tip in _GOBO_SLOTS:
                    btn = QPushButton(icon)
                    btn.setFixedSize(30, 28); btn.setToolTip(f"{tip}  (DMX {dmx_val})")
                    btn.setProperty("gobo_val", dmx_val)
                    btn.setStyleSheet(_SS_BTN_ON if abs(dmx_val - cur_gobo) < 16 else _SS_BTN_OFF)
                    btn.clicked.connect(lambda chk, v=dmx_val: _set_gobo_btn(v))
                    gobo_h.addWidget(btn)
                gobo_h.addStretch()

                # Bouton éditeur de gobo
                _edit_gobo_btn = QPushButton("✏  Éditer")
                _edit_gobo_btn.setFixedHeight(22)
                _edit_gobo_btn.setToolTip("Éditer la roue de gobos de cette fixture")
                _edit_gobo_btn.setStyleSheet(
                    "QPushButton{background:#1e1e1e;color:#888;border:1px solid #333;"
                    "border-radius:4px;font-size:11px;padding:0 6px;}"
                    "QPushButton:hover{border-color:#ff9900;color:#ff9900;background:#2a1e00;}"
                )
                def _open_gobo_editor(chk=False, _p=proj, _t=targets):
                    from color_wheel_editor import GoboWheelEditorDialog
                    menu.close()
                    dlg = GoboWheelEditorDialog(
                        _p, self.projectors,
                        main_window=self.main_window, parent=self
                    )
                    if dlg.exec():
                        # Rafraîchir les presets dans le menu (rouvrir)
                        self.refresh() if hasattr(self, 'refresh') else None
                _edit_gobo_btn.clicked.connect(_open_gobo_editor)
                gobo_h.addWidget(_edit_gobo_btn)

                _wa(gobo_w)

            # ── Rotation Gobo ────────────────────────────────────────────
            if has_profile and 'Gobo1Rot' in proj_profile:
                cur_gobo_rot = getattr(targets[0][0], 'gobo_rotation', 0)

                def _on_gobo_rot(v, t=targets):
                    for p, g, i in t:
                        p.gobo_rotation = v
                    _flush()

                _wa(_slider_row("Rotation Gobo", cur_gobo_rot, 255, _on_gobo_rot))

            # ── Prisme ──────────────────────────────────────────────────
            if has_profile and 'Prism' in proj_profile:
                menu.addSeparator()
                cur_prism = getattr(targets[0][0], 'prism', 0)

                # Slider rotation prisme (0 = off, 1-255 = vitesse/position)
                def _on_prism(v, t=targets):
                    for p, g, i in t:
                        p.prism = v
                    _flush()

                prism_row_w = QWidget(); prism_row_h = QHBoxLayout(prism_row_w)
                prism_row_h.setContentsMargins(10, 4, 10, 4); prism_row_h.setSpacing(8)
                prism_lbl = QLabel("Prisme"); prism_lbl.setStyleSheet(_SS)

                prism_off_btn = QPushButton("OFF")
                prism_off_btn.setFixedSize(42, 26)
                prism_on_btn  = QPushButton("ON")
                prism_on_btn.setFixedSize(42, 26)

                prism_sli = QSlider(Qt.Horizontal)
                prism_sli.setRange(0, 255); prism_sli.setValue(cur_prism)
                prism_sli.setFixedWidth(100); prism_sli.setStyleSheet(_SLI)

                prism_val_lbl = QLabel(str(cur_prism))
                prism_val_lbl.setStyleSheet("color:#ddd;font-size:12px;font-weight:bold;min-width:28px;")
                prism_val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                def _prism_update(v):
                    prism_sli.setValue(v)
                    prism_val_lbl.setText(str(v))
                    _on_prism(v)
                    is_on = v > 0
                    prism_off_btn.setStyleSheet(_SS_BTN_ON if not is_on else _SS_BTN_OFF)
                    prism_on_btn.setStyleSheet(_SS_BTN_ON if is_on else _SS_BTN_OFF)

                prism_off_btn.clicked.connect(lambda: _prism_update(0))
                prism_on_btn.clicked.connect(lambda: _prism_update(64))
                prism_sli.valueChanged.connect(lambda v: (prism_val_lbl.setText(str(v)), _on_prism(v),
                    prism_off_btn.setStyleSheet(_SS_BTN_ON if v == 0 else _SS_BTN_OFF),
                    prism_on_btn.setStyleSheet(_SS_BTN_ON if v > 0 else _SS_BTN_OFF)))

                prism_off_btn.setStyleSheet(_SS_BTN_ON if cur_prism == 0 else _SS_BTN_OFF)
                prism_on_btn.setStyleSheet(_SS_BTN_ON if cur_prism > 0 else _SS_BTN_OFF)

                for w in (prism_lbl, prism_off_btn, prism_on_btn, prism_sli, prism_val_lbl):
                    prism_row_h.addWidget(w)
                _wa(prism_row_w)

            # ── Rotation Prisme ──────────────────────────────────────────
            if has_profile and 'PrismRot' in proj_profile:
                cur_prism_rot = getattr(targets[0][0], 'prism_rotation', 0)

                def _on_prism_rot(v, t=targets):
                    for p, g, i in t:
                        p.prism_rotation = v
                    _flush()

                _wa(_slider_row("Rotation Prisme", cur_prism_rot, 255, _on_prism_rot))

        # ── Couleurs ─────────────────────────────────────────────────────
        # Masquer pour : fumée/gradateurs, et Moving Head à roue de couleur
        # (la section ColorWheel ci-dessus est déjà le sélecteur de couleur)
        _has_cw_in_profile = 'ColorWheel' in (_proj_profile or [])
        _is_cw_mh = (proj.fixture_type == "Moving Head" and _has_cw_in_profile)
        NO_COLOR_TYPES = {"Machine a fumee", "Gradateur"}
        if proj.fixture_type not in NO_COLOR_TYPES and not _is_cw_mh:
            menu.addSeparator()
            _col_sec = QLabel("COULEUR")
            _col_sec.setStyleSheet("color:#444;font-size:9px;font-weight:bold;"
                                   "padding:2px 10px;border:none;background:transparent;")
            _wa(_col_sec)
            colors_w = QWidget(); colors_g = QGridLayout(colors_w)
            colors_g.setContentsMargins(8, 4, 8, 4); colors_g.setSpacing(5)
            for ci, (label, color) in enumerate(PRESET_COLORS):
                row, col = divmod(ci, 4)
                btn = QPushButton(); btn.setFixedSize(28, 28)
                bc = "#555" if color.lightness() < 50 else color.darker(130).name()
                btn.setStyleSheet(
                    f"QPushButton{{background:{color.name()};border:2px solid {bc};"
                    f"border-radius:14px;}}QPushButton:hover{{border:2px solid #00d4ff;}}"
                )
                btn.setToolTip(label); btn.setCursor(Qt.PointingHandCursor)
                def _on_color_btn(checked, c=color, t=targets):
                    self._apply_color_to_targets(t, c)
                    v = t[0][0].level
                    dim_sli.setValue(v)
                    dim_val.setText(f"{v}%")
                btn.clicked.connect(_on_color_btn)
                colors_g.addWidget(btn, row, col)
            _wa(colors_w)


        # ── Clear sélectif ───────────────────────────────────────────────
        menu.addSeparator()
        n_sel = len(targets)
        clear_label = f"🔲  Clear ({n_sel})" if n_sel > 1 else "🔲  Clear"
        def _clear_targets(t=targets):
            black = QColor(0, 0, 0)
            for p, g, i in t:
                p.level        = 0
                p.base_color   = black
                p.color        = black
                p.uv           = 0
                p.white_boost  = 0
                p.amber_boost  = 0
                p.orange_boost = 0
                p.strobe_speed = 0
                p.pan          = 128
                p.tilt         = 128
                p.gobo         = 0
                p.zoom         = 0
                p.shutter      = 255
                p.color_wheel  = 0
                p.prism        = 0
            _flush()
        menu.addAction(clear_label, _clear_targets)

        # ── Bas de menu ──────────────────────────────────────────────────
        menu.addSeparator()
        patch_w = QWidget()
        patch_w.setCursor(Qt.PointingHandCursor)
        patch_l = QHBoxLayout(patch_w)
        patch_l.setContentsMargins(0, 6, 0, 6)
        patch_lbl = QLabel("Editer Patch")
        patch_lbl.setAlignment(Qt.AlignCenter)
        patch_lbl.setStyleSheet("color:#888; font-size:11px; border:none; background:transparent;")
        patch_l.addWidget(patch_lbl)
        patch_wa = QWidgetAction(menu)
        patch_wa.setDefaultWidget(patch_w)
        patch_wa.triggered.connect(lambda: self._edit_fixture(fixture_idx))
        patch_w.mouseReleaseEvent = lambda e: (self._edit_fixture(fixture_idx), menu.close())
        menu.addAction(patch_wa)
        menu.exec(self._pos_outside(menu))

    def _show_canvas_context_menu(self, global_pos, local_pos=None):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        act_add = menu.addAction("+ Ajouter fixture")
        act_add.triggered.connect(lambda: self._open_add_fixture_dialog(local_pos))
        menu.addSeparator()

        act_sel_all = menu.addAction("Tout selectionner")
        act_sel_all.triggered.connect(self._select_all)

        act_desel = menu.addAction("Tout deselectionner")
        act_desel.triggered.connect(self._deselect_all)
        menu.addSeparator()

        act_clear = menu.addAction("Clear (tout a 0)")
        act_clear.triggered.connect(self._clear_all_projectors)
        menu.addSeparator()

        # Selectionner par groupe (noms depuis GROUP_DISPLAY si disponible)
        gd = {}
        if self.main_window and hasattr(self.main_window, 'GROUP_DISPLAY'):
            gd = self.main_window.GROUP_DISPLAY
        groups_present = []
        for p in self.projectors:
            if p.group not in groups_present:
                groups_present.append(p.group)
        if groups_present:
            sel_menu = menu.addMenu("Sélectionner...")
            for g in groups_present:
                label = gd.get(g, g)
                act = sel_menu.addAction(label)
                act.triggered.connect(lambda checked, grp=g: self._select_group(grp))

            # Groupes personnalisés créés via le bouton SELEC
            if self._custom_groups:
                sel_menu.addSeparator()
                for gname, members in self._custom_groups.items():
                    act = sel_menu.addAction(f"★  {gname}  ({len(members)})")
                    act.triggered.connect(lambda checked, m=members: self._select_custom_group(m))

        menu.exec(self._pos_outside(menu))

    # ── Ajout / edition / suppression ────────────────────────────────

    def _open_new_plan_wizard(self):
        """Ouvre le wizard de creation d'un nouveau plan de feu"""
        dlg = NewPlanWizard(self)
        if dlg.exec() != QDialog.Accepted:
            return
        fixtures = dlg.get_result()
        if not fixtures:
            QMessageBox.warning(self, "Plan vide", "Aucune fixture configurée. Plan non appliqué.")
            return

        # Reconstruction des projectors in-place (preserve la reference main_window.projectors)
        from projector import Projector
        self.projectors.clear()
        self.selected_lamps.clear()
        for fd in fixtures:
            p = Projector(fd['group'], name=fd['name'], fixture_type=fd['fixture_type'])
            p.universe = fd.get('universe', 0)
            p.start_address = fd['start_address']
            p.canvas_x = None  # Position par defaut (calculee par le canvas)
            p.canvas_y = None
            if fd['fixture_type'] == "Machine a fumee":
                p.fan_speed = 0
            self.projectors.append(p)

        if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
            self.main_window._rebuild_dmx_patch()
        self.refresh()

    def _open_add_fixture_dialog(self, local_pos=None):
        from projector import Projector
        dlg = AddFixtureDialog(self.projectors, self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_fixture_data()
            if data:
                p = Projector(data['group'], name=data['name'], fixture_type=data['fixture_type'])
                p.universe = data.get('universe', 0)
                p.start_address = data['start_address']
                if local_pos is not None:
                    cw = max(self.canvas.width(), 1)
                    ch = max(self.canvas.height(), 1)
                    px = max(0.05, min(0.95, local_pos.x() / cw))
                    py = max(0.06, min(0.94, local_pos.y() / ch))
                else:
                    px, py = 0.5, 0.5
                p.canvas_x, p.canvas_y = _find_free_canvas_pos(self.projectors, px, py)
                profile = data.get('profile')
                if isinstance(profile, list) and profile:
                    p.dmx_profile = profile
                self.projectors.append(p)
                if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
                    self.main_window._rebuild_dmx_patch()
                self.refresh()

    def _edit_fixture(self, fixture_idx):
        if fixture_idx >= len(self.projectors):
            return
        if self.main_window and hasattr(self.main_window, 'show_dmx_patch_config'):
            self.main_window.show_dmx_patch_config(select_idx=fixture_idx)
            return
        # Fallback sans main_window
        proj = self.projectors[fixture_idx]
        dlg = EditFixtureDialog(proj, self.projectors, self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_fixture_data()
            if data:
                proj.name = data['name']
                proj.fixture_type = data['fixture_type']
                proj.group = data['group']
                proj.universe = data.get('universe', 0)
                proj.start_address = data['start_address']
                if data.get('profile'):
                    proj.dmx_profile = data['profile']
                if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
                    self.main_window._rebuild_dmx_patch()
                self.refresh()

    def _delete_fixture(self, fixture_idx):
        if fixture_idx >= len(self.projectors):
            return
        proj = self.projectors[fixture_idx]
        name = proj.name or f"{proj.group}"
        reply = QMessageBox.question(
            self, "Supprimer fixture",
            f"Supprimer '{name}' ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.projectors.pop(fixture_idx)
            self.selected_lamps.clear()
            if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
                self.main_window._rebuild_dmx_patch()
            self.refresh()

    def _delete_selected_fixtures(self):
        selected = list(self.selected_lamps)
        if not selected:
            return
        if len(selected) > 1:
            reply = QMessageBox.question(
                self, "Supprimer fixtures",
                f"Supprimer {len(selected)} fixture(s) selectionnee(s) ?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # Construire les indices a supprimer
        to_remove = set()
        group_counters = {}
        for i, proj in enumerate(self.projectors):
            g = proj.group
            li = group_counters.get(g, 0)
            group_counters[g] = li + 1
            if (g, li) in self.selected_lamps:
                to_remove.add(i)

        for i in sorted(to_remove, reverse=True):
            self.projectors.pop(i)

        self.selected_lamps.clear()
        if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
            self.main_window._rebuild_dmx_patch()
        self.refresh()

    # ── Raccourcis clavier (re-expose depuis le QFrame) ──────────────

    def keyPressEvent(self, event):
        import time as _time
        now = _time.time()
        if event.key() == Qt.Key_Escape:
            if not hasattr(self, '_esc_times'):
                self._esc_times = []
            self._esc_times.append(now)
            self._esc_times = [t for t in self._esc_times if now - t < 1.5]
            if len(self._esc_times) >= 3:
                self._esc_times.clear()
                self._clear_all_projectors()
            else:
                self._deselect_all()
        elif event.key() == Qt.Key_A and (event.modifiers() & Qt.ControlModifier):
            self._select_all()
        elif event.key() == Qt.Key_Delete:
            self._delete_selected_fixtures()
        elif event.key() == Qt.Key_1:
            self._select_group("pairs_lat_contre")
        elif event.key() == Qt.Key_2:
            self._select_group("impairs_lat_contre")
        elif event.key() == Qt.Key_3:
            self._select_group("all_lat_contre")
        elif event.key() == Qt.Key_F:
            self._select_group("face")
        elif event.key() == Qt.Key_4:
            self._select_group("douche1")
        elif event.key() == Qt.Key_5:
            self._select_group("douche2")
        elif event.key() == Qt.Key_6:
            self._select_group("douche3")
        else:
            super().keyPressEvent(event)


# ── Dialogs Ajouter / Modifier ────────────────────────────────────────────────

class _FixtureFormWidget(QWidget):
    """Formulaire commun pour ajouter/modifier une fixture"""

    def __init__(self, projectors, preset=None, parent=None):
        super().__init__(parent)
        self._projectors = projectors

        layout = QFormLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.name_edit = QLineEdit(preset.get('name', '') if preset else '')
        self.name_edit.setPlaceholderText("Ex: Face gauche, Lyre SL...")
        layout.addRow("Nom :", self.name_edit)

        self.type_combo = QComboBox()
        for t in ["PAR LED", "Moving Head", "Barre LED", "Stroboscope", "Machine a fumee", "Gradateur"]:
            self.type_combo.addItem(t)
        if preset:
            idx = self.type_combo.findText(preset.get('fixture_type', 'PAR LED'))
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
        layout.addRow("Type :", self.type_combo)

        self.uni_combo = QComboBox()
        for i, lbl in enumerate(["U1", "U2", "U3", "U4"]):
            self.uni_combo.addItem(lbl, i)
        auto_uni, auto_addr = self._next_patch()
        self.uni_combo.setCurrentIndex(preset.get('universe', auto_uni) if preset else auto_uni)
        layout.addRow("Univers :", self.uni_combo)

        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(1, 512)
        self.addr_spin.setValue(preset.get('start_address', auto_addr) if preset else auto_addr)
        layout.addRow("Adresse DMX :", self.addr_spin)

        self.group_combo = QComboBox()
        _GROUPS = [
            ("face",    "A"),
            ("lat",     "B"),
            ("contre",  "C"),
            ("douche1", "D"),
            ("douche2", "E"),
            ("douche3", "F"),
        ]
        for key, label in _GROUPS:
            self.group_combo.addItem(label, key)
        # Sélection initiale — tout groupe inconnu (lyre, fumee…) → A
        default_group = preset.get('group', 'face') if preset else 'face'
        sel = 0
        for i in range(self.group_combo.count()):
            if self.group_combo.itemData(i) == default_group:
                sel = i
                break
        self.group_combo.setCurrentIndex(sel)
        layout.addRow("Groupe :", self.group_combo)

        self.profile_combo = QComboBox()
        self._populate_profiles(self.type_combo.currentText())
        if preset and 'profile' in preset:
            idx = self.profile_combo.findData(preset['profile'])
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        layout.addRow("Profil DMX :", self.profile_combo)

        self.type_combo.currentTextChanged.connect(self._on_type_changed)

    def _next_patch(self):
        """Retourne (universe, addr) pour la prochaine fixture en autopatch intelligent."""
        if not self._projectors:
            return 0, 1
        _CH = {"PAR LED": 5, "Moving Head": 8, "Barre LED": 5, "Stroboscope": 2, "Machine a fumee": 2, "Gradateur": 1}
        max_uni = max(getattr(p, 'universe', 0) for p in self._projectors)
        projs_on_uni = [p for p in self._projectors if getattr(p, 'universe', 0) == max_uni]
        next_addr = max(p.start_address + _CH.get(getattr(p, 'fixture_type', 'PAR LED'), 5)
                        for p in projs_on_uni)
        if next_addr > 512:
            if max_uni < 3:
                return max_uni + 1, 1
            return max_uni, 512
        return max_uni, next_addr

    # Alias retro-compat (utilisé nulle part mais au cas où)
    def _next_address(self):
        _, addr = self._next_patch()
        return addr

    def _populate_profiles(self, fixture_type):
        from artnet_dmx import DMX_PROFILES, profile_display_text
        self.profile_combo.clear()
        TYPE_PROFILES = {
            "PAR LED":        ["DIM", "RGB", "RGBD", "RGBDS", "RGBSD", "DRGB", "DRGBS",
                               "RGBW", "RGBWD", "RGBWDS", "RGBWZ", "RGBWA", "RGBWAD", "RGBWOUV"],
            "Moving Head":    ["MOVING_5CH", "MOVING_8CH", "MOVING_RGB", "MOVING_RGBW"],
            "Barre LED":      ["LED_BAR_RGB", "RGB", "RGBD", "RGBDS"],
            "Stroboscope":    ["STROBE_2CH"],
            "Machine a fumee": ["2CH_FUMEE"],
            "Gradateur":      ["DIM"],
        }
        allowed = TYPE_PROFILES.get(fixture_type, list(DMX_PROFILES.keys()))
        for key in allowed:
            if key in DMX_PROFILES:
                label = f"{key}  ({profile_display_text(DMX_PROFILES[key])})"
                self.profile_combo.addItem(label, key)

    def _on_type_changed(self, ftype):
        current_data = self.profile_combo.currentData()
        self._populate_profiles(ftype)
        # Restaurer la valeur si disponible
        idx = self.profile_combo.findData(current_data)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)

    def get_data(self):
        from artnet_dmx import DMX_PROFILES
        profile_key = self.profile_combo.currentData() or 'RGBDS'
        profile = list(DMX_PROFILES.get(profile_key, DMX_PROFILES['RGBDS']))
        return {
            'name': self.name_edit.text().strip(),
            'fixture_type': self.type_combo.currentText(),
            'universe': self.uni_combo.currentData(),
            'start_address': self.addr_spin.value(),
            'group': self.group_combo.currentData() or self.group_combo.currentText(),
            'profile': profile,
        }


class AddFixtureDialog(QDialog):
    """Dialog pour ajouter une fixture (2 onglets: bibliotheque + formulaire)"""

    def __init__(self, projectors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajouter une fixture")
        self.setMinimumSize(500, 380)
        self._projectors = projectors
        self._result_data = None

        self.setStyleSheet("""
            QDialog { background: #1a1a1a; color: white; }
            QTabWidget::pane { border: 1px solid #333; }
            QTabBar::tab { background: #2a2a2a; color: #aaa; padding: 6px 14px; }
            QTabBar::tab:selected { background: #333; color: white; }
            QListWidget { background: #222; border: 1px solid #333; color: white; }
            QListWidget::item:selected { background: #00d4ff; color: black; }
            QLineEdit, QComboBox, QSpinBox {
                background: #2a2a2a; color: white; border: 1px solid #444;
                border-radius: 3px; padding: 3px;
            }
            QLabel { color: #ccc; }
        """)

        root = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Onglet Bibliotheque ─────────────────────────────────────
        lib_w = QWidget()
        lib_layout = QVBoxLayout(lib_w)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        self.cat_list = QListWidget()
        self.cat_list.setMaximumWidth(150)
        for cat in FIXTURE_LIBRARY:
            self.cat_list.addItem(cat)
        splitter.addWidget(self.cat_list)

        self.preset_list = QListWidget()
        splitter.addWidget(self.preset_list)
        splitter.setSizes([140, 320])

        lib_layout.addWidget(splitter)

        self.cat_list.currentTextChanged.connect(self._on_category_changed)
        self.preset_list.itemDoubleClicked.connect(self._accept_library)
        self.cat_list.setCurrentRow(0)

        tabs.addTab(lib_w, "Bibliotheque")

        # ── Onglet Formulaire rapide ────────────────────────────────
        self._form = _FixtureFormWidget(projectors, parent=self)
        tabs.addTab(self._form, "Formulaire rapide")

        root.addWidget(tabs)
        self._tabs = tabs

        # Boutons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _on_category_changed(self, cat):
        self.preset_list.clear()
        for preset in FIXTURE_LIBRARY.get(cat, []):
            item = QListWidgetItem(preset['name'])
            item.setData(Qt.UserRole, preset)
            self.preset_list.addItem(item)

    def _accept_library(self, item):
        self._result_data = item.data(Qt.UserRole)
        self.accept()

    def _on_accept(self):
        if self._tabs.currentIndex() == 0:
            # Bibliotheque
            item = self.preset_list.currentItem()
            if item:
                self._result_data = item.data(Qt.UserRole)
                # Calculer adresse DMX compacte
                _CH = {"PAR LED": 5, "Moving Head": 8, "Barre LED": 5, "Stroboscope": 2, "Machine a fumee": 2, "Gradateur": 1}
                if self._projectors:
                    next_addr = max(
                        p.start_address + _CH.get(getattr(p, 'fixture_type', 'PAR LED'), 5)
                        for p in self._projectors
                    )
                else:
                    next_addr = 1
                self._result_data = dict(self._result_data)
                self._result_data['start_address'] = next_addr
                self.accept()
            else:
                QMessageBox.warning(self, "Aucun preset", "Selectionnez un preset dans la bibliotheque.")
        else:
            self._result_data = self._form.get_data()
            self.accept()

    def get_fixture_data(self):
        return self._result_data


class EditFixtureDialog(QDialog):
    """Dialog pour modifier une fixture existante"""

    def __init__(self, proj, projectors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier la fixture")
        self.setMinimumSize(420, 300)
        self._result_data = None

        self.setStyleSheet("""
            QDialog { background: #1a1a1a; color: white; }
            QLineEdit, QComboBox, QSpinBox {
                background: #2a2a2a; color: white; border: 1px solid #444;
                border-radius: 3px; padding: 3px;
            }
            QLabel { color: #ccc; }
        """)

        # Retrouver la clé du profil DMX à partir de la liste stockée sur le projecteur
        profile_key = None
        stored_profile = getattr(proj, 'dmx_profile', None)
        if isinstance(stored_profile, list) and stored_profile:
            try:
                from artnet_dmx import DMX_PROFILES
                for k, v in DMX_PROFILES.items():
                    if list(v) == stored_profile:
                        profile_key = k
                        break
            except Exception:
                pass

        preset = {
            'name': proj.name,
            'fixture_type': getattr(proj, 'fixture_type', 'PAR LED'),
            'start_address': proj.start_address,
            'group': proj.group,
            'profile': profile_key,
        }
        root = QVBoxLayout(self)
        self._form = _FixtureFormWidget(projectors, preset=preset, parent=self)
        root.addWidget(self._form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _on_accept(self):
        self._result_data = self._form.get_data()
        self.accept()

    def get_fixture_data(self):
        return self._result_data


# ── Wizard "Nouveau plan de feu" ──────────────────────────────────────────────

class _CounterWidget(QWidget):
    """Grand compteur +/- utilisé dans le wizard"""
    valueChanged = Signal(int)

    def __init__(self, value=0, min_val=0, max_val=20, parent=None):
        super().__init__(parent)
        self._value = value
        self._min = min_val
        self._max = max_val

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)

        self.btn_minus = QPushButton("−")
        self.btn_minus.setFixedSize(60, 60)
        self.btn_minus.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: white; border: 2px solid #444;
                border-radius: 30px; font-size: 30px; font-weight: bold;
            }
            QPushButton:hover  { background: #3a3a3a; border-color: #888; }
            QPushButton:pressed{ background: #444; }
            QPushButton:disabled{ color: #333; border-color: #2a2a2a; }
        """)
        row.addWidget(self.btn_minus)

        self.lbl = QLabel(str(value))
        self.lbl.setAlignment(Qt.AlignCenter)
        self.lbl.setFixedWidth(90)
        self.lbl.setStyleSheet("color: white; font-size: 54px; font-weight: bold;")
        row.addWidget(self.lbl)

        self.btn_plus = QPushButton("+")
        self.btn_plus.setFixedSize(60, 60)
        self.btn_plus.setStyleSheet("""
            QPushButton {
                background: #00d4ff; color: black; border: none;
                border-radius: 30px; font-size: 30px; font-weight: bold;
            }
            QPushButton:hover  { background: #33ddff; }
            QPushButton:pressed{ background: #00aacc; }
            QPushButton:disabled{ background: #1a4455; color: #1a1a1a; }
        """)
        row.addWidget(self.btn_plus)

        self.btn_minus.clicked.connect(self._dec)
        self.btn_plus.clicked.connect(self._inc)
        self._refresh_buttons()

    def _dec(self):
        if self._value > self._min:
            self._value -= 1
            self.lbl.setText(str(self._value))
            self.valueChanged.emit(self._value)
            self._refresh_buttons()

    def _inc(self):
        if self._value < self._max:
            self._value += 1
            self.lbl.setText(str(self._value))
            self.valueChanged.emit(self._value)
            self._refresh_buttons()

    def _refresh_buttons(self):
        self.btn_minus.setEnabled(self._value > self._min)
        self.btn_plus.setEnabled(self._value < self._max)

    def value(self):
        return self._value

    def set_value(self, v):
        self._value = max(self._min, min(self._max, v))
        self.lbl.setText(str(self._value))
        self._refresh_buttons()


class _FixturePreviewBar(QWidget):
    """Rangée de petits cercles représentant les fixtures"""

    def __init__(self, count=0, color="#00d4ff", parent=None):
        super().__init__(parent)
        self._count = count
        self._color = QColor(color)
        self.setFixedHeight(36)
        self.setMinimumWidth(200)

    def set_count(self, n):
        self._count = n
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0d0d0d"))

        n = self._count
        if n == 0:
            painter.setPen(QColor("#444"))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(self.rect(), Qt.AlignCenter, "Aucune fixture")
            painter.end()
            return

        r = 12
        gap = 6
        total_w = n * r * 2 + (n - 1) * gap
        # Si trop large, réduire r
        if total_w > self.width() - 20:
            r = max(4, (self.width() - 20 - (n - 1) * gap) // (2 * n))
            total_w = n * r * 2 + (n - 1) * gap
        cx0 = (self.width() - total_w) // 2 + r
        cy = self.height() // 2

        painter.setBrush(QBrush(self._color))
        painter.setPen(QPen(self._color.lighter(140), 1))
        for i in range(n):
            cx = cx0 + i * (r * 2 + gap)
            painter.drawEllipse(QPoint(cx, cy), r, r)
        painter.end()


class NewPlanWizard(QDialog):
    """Assistant étape par étape pour créer un nouveau plan de feu"""

    _STEPS = [
        dict(
            group="face",   label="Groupe A — Face",
            subtitle="Combien de projecteurs face au public ?\n(éclairage frontal de scène)",
            ftype="PAR LED", profile="RGBDS", prefix="Face",
            color="#ffaa33", default=4, max=20,
        ),
        dict(
            group="contre", label="Groupe B — Contre-jour",
            subtitle="Combien de contre-jour ?\n(lumières arrière, hautes, sur les perches)",
            ftype="PAR LED", profile="RGBDS", prefix="Contre",
            color="#4488ff", default=6, max=20,
        ),
        dict(
            group="lat",    label="Groupe C — Latéraux",
            subtitle="Combien de projecteurs latéraux ?\n(éclairage de côté, jardin et cour)",
            ftype="PAR LED", profile="RGBDS", prefix="Lat",
            color="#88aaff", default=2, max=10,
        ),
        dict(
            group="douche1", label="Groupe D — Douches",
            subtitle="Combien de projecteurs en douche ?\n(éclairage vertical depuis le plafond)",
            ftype="PAR LED", profile="RGBDS", prefix="Douche",
            color="#44ee88", default=3, max=20,
        ),
        dict(
            group="lyre",   label="Groupe E — Lyres",
            subtitle="Combien de lyres / moving heads ?\n(laisser à 0 si aucun)",
            ftype="Moving Head", profile="MOVING_8CH", prefix="Lyre",
            color="#ee44ff", default=0, max=10,
        ),
        dict(
            group="fumee",  label="Machine à fumée",
            subtitle="Combien de machines à fumée / hazers ?\n(laisser à 0 si aucune)",
            ftype="Machine a fumee", profile="2CH_FUMEE", prefix="Fumée",
            color="#aaaaaa", default=0, max=4,
        ),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau plan de feu")
        self.setModal(True)
        self.setMinimumSize(560, 500)
        self.setStyleSheet("""
            QDialog { background: #141414; color: white; }
        """)

        self._counts = [s['default'] for s in self._STEPS]
        self._step = 0
        self._step_custom_fixtures = [None] * len(self._STEPS)  # fixture choisie par l'user
        self.fixture_selector_cb = None  # injecté par main_window

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── En-tête ────────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(72)
        self._header.setStyleSheet("background: #0d0d0d; border-bottom: 1px solid #2a2a2a;")
        hh = QHBoxLayout(self._header)
        hh.setContentsMargins(28, 0, 28, 0)

        self._title_lbl = QLabel()
        self._title_lbl.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self._title_lbl.setStyleSheet("color: white;")
        hh.addWidget(self._title_lbl)
        hh.addStretch()

        self._dots_lbl = QLabel()
        self._dots_lbl.setStyleSheet("color: #555; font-size: 18px; letter-spacing: 6px;")
        hh.addWidget(self._dots_lbl)

        root.addWidget(self._header)

        # ── Pages ─────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._step_pages = []
        for i, step in enumerate(self._STEPS):
            page = self._build_step_page(i, step)
            self._stack.addWidget(page)
            self._step_pages.append(page)

        self._summary_page = self._build_summary_page()
        self._stack.addWidget(self._summary_page)

        root.addWidget(self._stack)

        # ── Pied de page ───────────────────────────────────────────
        footer = QWidget()
        footer.setFixedHeight(68)
        footer.setStyleSheet("background: #0d0d0d; border-top: 1px solid #2a2a2a;")
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(28, 0, 28, 0)
        fh.setSpacing(10)

        cancel_btn = QPushButton("Annuler")
        cancel_btn.setFixedHeight(38)
        cancel_btn.setStyleSheet(
            "background:#222; color:#888; border:1px solid #444; border-radius:4px; padding:0 16px;"
        )
        cancel_btn.clicked.connect(self.reject)
        fh.addWidget(cancel_btn)
        fh.addStretch()

        self._back_btn = QPushButton("← Retour")
        self._back_btn.setFixedHeight(38)
        self._back_btn.setStyleSheet(
            "background:#2a2a2a; color:white; border:1px solid #444; border-radius:4px; padding:0 16px;"
        )
        self._back_btn.clicked.connect(self._go_prev)
        fh.addWidget(self._back_btn)

        self._next_btn = QPushButton("Suivant →")
        self._next_btn.setFixedHeight(38)
        self._next_btn.setStyleSheet(
            "background:#00d4ff; color:black; font-weight:bold; border:none; border-radius:4px; padding:0 20px;"
        )
        self._next_btn.clicked.connect(self._go_next)
        fh.addWidget(self._next_btn)

        root.addWidget(footer)
        self._refresh_ui()

    # ── Construction des pages ─────────────────────────────────────

    def _build_step_page(self, idx, step):
        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(50, 36, 50, 24)
        vl.setSpacing(0)

        subtitle = QLabel(step['subtitle'])
        subtitle.setStyleSheet("color: #888; font-size: 13px;")
        subtitle.setAlignment(Qt.AlignCenter)
        vl.addWidget(subtitle)
        vl.addSpacing(28)

        # Sélecteur de fixture
        fx_row = QHBoxLayout()
        fx_row.setSpacing(8)
        fx_lbl = QLabel(f"{step['ftype']}  (défaut)")
        fx_lbl.setStyleSheet(
            "color:#555; font-size:11px; background:#1a1a1a;"
            " border:1px solid #2a2a2a; border-radius:4px; padding:4px 10px;"
        )
        btn_pick = QPushButton("Choisir fixture…")
        btn_pick.setFixedHeight(30)
        btn_pick.setStyleSheet(
            "QPushButton { background:#1e1e1e; color:#aaa; border:1px solid #333;"
            " border-radius:4px; padding:0 12px; font-size:11px; }"
            "QPushButton:hover { border-color:#00d4ff55; color:#fff; background:#1e2530; }"
        )
        btn_pick.clicked.connect(lambda checked=False, i=idx: self._pick_fixture(i))
        fx_row.addWidget(fx_lbl, 1)
        fx_row.addWidget(btn_pick)
        vl.addLayout(fx_row)
        vl.addSpacing(20)

        counter = _CounterWidget(value=self._counts[idx], max_val=step['max'])
        counter.valueChanged.connect(lambda v, i=idx: self._on_count(i, v))
        vl.addWidget(counter, 0, Qt.AlignCenter)
        vl.addSpacing(28)

        preview = _FixturePreviewBar(count=self._counts[idx], color=step['color'])
        vl.addWidget(preview)
        vl.addSpacing(10)

        info_lbl = QLabel()
        info_lbl.setStyleSheet("color: #555; font-size: 11px;")
        info_lbl.setAlignment(Qt.AlignCenter)
        vl.addWidget(info_lbl)
        vl.addStretch()

        page._counter = counter
        page._preview = preview
        page._info = info_lbl
        page._fx_lbl = fx_lbl
        page._idx = idx
        self._refresh_step_page(page)
        return page

    def _pick_fixture(self, idx):
        if not self.fixture_selector_cb:
            return
        result = self.fixture_selector_cb()
        if not result:
            return
        fx = result[0]  # (preset, qty, custom_name)
        self._step_custom_fixtures[idx] = fx
        page = self._step_pages[idx]
        name = fx.get('name', '?')
        mfr  = fx.get('manufacturer', '')
        n_ch = len(fx.get('profile', []))
        page._fx_lbl.setText(f"{mfr}  {name}  ·  {n_ch}ch")
        page._fx_lbl.setStyleSheet(
            "color:#00d4ff; font-size:11px; background:#0d1a20;"
            " border:1px solid #00d4ff44; border-radius:4px; padding:4px 10px;"
        )
        self._refresh_step_page(page)

    def _refresh_step_page(self, page):
        from artnet_dmx import DMX_PROFILES
        idx = page._idx
        step = self._STEPS[idx]
        count = self._counts[idx]
        custom_fx = self._step_custom_fixtures[idx]
        if custom_fx:
            ch_per = len(custom_fx.get('profile', []))
        else:
            ch_per = len(DMX_PROFILES.get(step['profile'], ['?'] * 5))
        page._preview.set_count(count)
        if count == 0:
            page._info.setText("Ce groupe sera vide")
        else:
            s = 's' if count > 1 else ''
            page._info.setText(
                f"{count} fixture{s} · {ch_per} canaux chacune · {count * ch_per} canaux au total"
            )

    def _build_summary_page(self):
        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(50, 28, 50, 24)
        vl.setSpacing(0)

        sub = QLabel("Voici votre plan de feu. Cliquez sur Configurer pour l'appliquer.")
        sub.setStyleSheet("color: #888; font-size: 12px;")
        sub.setAlignment(Qt.AlignCenter)
        vl.addWidget(sub)
        vl.addSpacing(20)

        self._summary_inner = QWidget()
        vl.addWidget(self._summary_inner)
        vl.addStretch()
        return page

    def _refresh_summary(self):
        from artnet_dmx import DMX_PROFILES

        # Nettoyer l'ancien layout
        old = self._summary_inner.layout()
        if old:
            while old.count():
                item = old.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            import sip
            try:
                sip.delete(old)
            except Exception:
                pass

        grid = QGridLayout(self._summary_inner)
        grid.setSpacing(10)
        grid.setColumnStretch(2, 1)

        addr = 1
        total_fx = 0
        total_ch = 0
        row = 0

        for i, step in enumerate(self._STEPS):
            count = self._counts[i]
            profile = DMX_PROFILES.get(step['profile'], ['?'] * 5)
            ch = len(profile) * count

            # Ligne de séparateur légère entre groupes
            if row > 0:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet("background: #222; margin: 0;")
                sep.setFixedHeight(1)
                grid.addWidget(sep, row, 0, 1, 4)
                row += 1

            # Indicateur couleur
            dot = QLabel("●")
            alpha = "ff" if count > 0 else "33"
            dot.setStyleSheet(f"color: {step['color']}; font-size: 18px;")
            dot.setAlignment(Qt.AlignCenter)
            dot.setFixedWidth(28)
            grid.addWidget(dot, row, 0)

            # Nom du groupe
            name = QLabel(step['label'])
            name.setStyleSheet(
                f"color: {'white' if count > 0 else '#444'}; font-size: 13px; font-weight: bold;"
            )
            grid.addWidget(name, row, 1)

            # Compte
            count_lbl = QLabel(f"{count} fixture{'s' if count != 1 else ''}" if count > 0 else "—")
            count_lbl.setStyleSheet("color: #888; font-size: 12px;")
            count_lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(count_lbl, row, 2)

            # Plage d'adresses
            if count > 0:
                addr_text = f"CH {addr} – {addr + ch - 1}"
                addr_lbl = QLabel(addr_text)
                addr_lbl.setStyleSheet("color: #00d4ff; font-size: 12px;")
                addr_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                grid.addWidget(addr_lbl, row, 3)
                addr += ch
                total_fx += count
                total_ch += ch

            row += 1

        # Total
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background: #333;")
        sep2.setFixedHeight(1)
        grid.addWidget(sep2, row, 0, 1, 4)
        row += 1

        if total_fx == 0:
            warn = QLabel("⚠  Aucune fixture configurée. Ajoutez au moins un projecteur.")
            warn.setStyleSheet("color: #ff8800; font-size: 12px;")
            warn.setAlignment(Qt.AlignCenter)
            grid.addWidget(warn, row, 0, 1, 4)
        else:
            total_lbl = QLabel(
                f"Total : {total_fx} fixture{'s' if total_fx > 1 else ''}  ·  {total_ch} canaux DMX utilisés"
            )
            total_lbl.setStyleSheet("color: #666; font-size: 11px;")
            total_lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(total_lbl, row, 0, 1, 4)

    # ── Navigation ─────────────────────────────────────────────────

    def _on_count(self, idx, value):
        self._counts[idx] = value
        self._refresh_step_page(self._step_pages[idx])

    def _go_prev(self):
        if self._step > 0:
            self._step -= 1
            self._refresh_ui()

    def _go_next(self):
        n = len(self._STEPS)
        if self._step < n:
            self._step += 1
            if self._step == n:
                self._refresh_summary()
            self._refresh_ui()
        else:
            self.accept()

    def _refresh_ui(self):
        n = len(self._STEPS)
        is_summary = (self._step == n)

        # Dots progress
        dots = "".join("●" if i < self._step else "○" for i in range(n))
        self._dots_lbl.setText(dots)

        if is_summary:
            self._stack.setCurrentWidget(self._summary_page)
            self._title_lbl.setText("Résumé")
            self._next_btn.setText("✓  Configurer")
            self._next_btn.setStyleSheet(
                "background:#22cc55; color:white; font-weight:bold;"
                " border:none; border-radius:4px; padding:0 20px;"
            )
        else:
            self._stack.setCurrentIndex(self._step)
            self._title_lbl.setText(self._STEPS[self._step]['label'])
            self._next_btn.setText("Suivant →")
            self._next_btn.setStyleSheet(
                "background:#00d4ff; color:black; font-weight:bold;"
                " border:none; border-radius:4px; padding:0 20px;"
            )

        self._back_btn.setEnabled(self._step > 0)

    # ── Résultat ───────────────────────────────────────────────────

    def get_result(self):
        """Retourne la liste de dicts {name, group, fixture_type, start_address, profile}"""
        from artnet_dmx import DMX_PROFILES
        fixtures = []
        addr = 1
        for i, step in enumerate(self._STEPS):
            count = self._counts[i]
            custom_fx = self._step_custom_fixtures[i]
            if custom_fx:
                profile   = list(custom_fx.get('profile', ['R', 'G', 'B', 'Dim', 'Strobe']))
                ftype     = custom_fx.get('fixture_type', step['ftype'])
                prefix    = custom_fx.get('name', step['prefix'])
            else:
                profile = list(DMX_PROFILES.get(step['profile'], ['R', 'G', 'B', 'Dim', 'Strobe']))
                ftype   = step['ftype']
                prefix  = step['prefix']
            ch = len(profile)
            for j in range(count):
                name = f"{prefix} {j + 1}" if count > 1 else prefix
                fixtures.append({
                    'name': name,
                    'group': step['group'],
                    'fixture_type': ftype,
                    'start_address': addr,
                    'profile': profile,
                })
                addr += ch
        return fixtures


# ── _PatchCanvasProxy ────────────────────────────────────────────────────────
# Interface minimale requise par FixtureCanvas pour le dialog Patch DMX

class _PatchCanvasProxy:
    """Proxy léger permettant d'utiliser FixtureCanvas dans le dialog Patch DMX.
    Implémente l'interface attendue par FixtureCanvas (projectors, selected_lamps,
    _htp_overrides, _show_fixture_context_menu, _show_canvas_context_menu).
    """

    def __init__(self, projectors, main_window):
        self.projectors = projectors
        self.main_window = main_window
        self.selected_lamps = set()
        self._htp_overrides = None
        self.canvas_widget = None           # Référence au FixtureCanvas (pour calcul de position)
        # Callbacks injectés par le dialog
        self._add_cb               = None
        self._wizard_cb            = None
        self._align_row_cb         = None   # Aligner sur la même ligne (même Y)
        self._distribute_cb        = None   # Centrer + distribuer également
        self._select_fixture_cb    = None   # Basculer sur l'onglet Fixtures + sélectionner la carte
        self._refresh_cb           = None   # Rafraîchir l'onglet Fixtures après modif externe

    # ── Menus contextuels ───────────────────────────────────────────

    def _show_fixture_context_menu(self, global_pos, idx):
        if idx >= len(self.projectors):
            return
        proj = self.projectors[idx]
        menu = QMenu()
        menu.setStyleSheet(_MENU_STYLE)

        info = menu.addAction(f"{proj.name or proj.group}  ·  CH {proj.start_address}")
        info.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Modifier...", lambda: self._edit_fixture(idx))
        menu.addSeparator()

        grp_menu = menu.addMenu("⬡  Assigner groupe")
        for _letter in ["A", "B", "C", "D", "E", "F"]:
            grp_menu.addAction(_letter).triggered.connect(
                lambda checked, l=_letter: self._assign_group_to_selected(l)
            )

        menu.addSeparator()
        n = len(self.selected_lamps)
        menu.addAction(f"🗑  Supprimer ({n})" if n > 1 else "🗑  Supprimer",
                       self._delete_selected_fixtures)

        menu.exec(global_pos)

    def _show_canvas_context_menu(self, global_pos, local_pos=None):
        # Calculer la position normalisée pour le placement à l'emplacement du clic
        norm_x, norm_y = 0.5, 0.5
        if local_pos is not None and self.canvas_widget:
            w = max(1, self.canvas_widget.width())
            h = max(1, self.canvas_widget.height())
            norm_x = max(0.0, min(1.0, local_pos.x() / w))
            norm_y = max(0.0, min(1.0, local_pos.y() / h))

        menu = QMenu()
        menu.setStyleSheet(_MENU_STYLE)

        if self._add_cb:
            menu.addAction("➕  Ajouter fixture",
                           lambda: self._add_cb(norm_x, norm_y))
        menu.addSeparator()

        def _sel_all():
            g_cnt = {}
            for p in self.projectors:
                g = p.group; li = g_cnt.get(g, 0); g_cnt[g] = li + 1
                self.selected_lamps.add((g, li))

        menu.addAction("Tout sélectionner", _sel_all)
        menu.addAction("Tout désélectionner", lambda: self.selected_lamps.clear())

        if self.selected_lamps:
            menu.addSeparator()
            grp_menu = menu.addMenu("⬡  Assigner groupe")
            for _letter in ["A", "B", "C", "D", "E", "F"]:
                grp_menu.addAction(_letter).triggered.connect(
                    lambda checked, l=_letter: self._assign_group_to_selected(l)
                )
            n = len(self.selected_lamps)
            menu.addAction(f"🗑  Supprimer ({n})" if n > 1 else "🗑  Supprimer",
                           self._delete_selected_fixtures)

        if self.selected_lamps and (self._align_row_cb or self._distribute_cb):
            menu.addSeparator()
            if self._align_row_cb:
                menu.addAction("⟶  Aligner sur la même ligne", self._align_row_cb)
            if self._distribute_cb:
                menu.addAction("⟺  Distribuer également",      self._distribute_cb)

        menu.exec(global_pos)

    # ── Assigner groupe ──────────────────────────────────────────────

    def _assign_group_to_selected(self, letter):
        _MAP = {"A": "face", "B": "lat", "C": "contre",
                "D": "douche1", "E": "douche2", "F": "douche3"}
        new_group = _MAP.get(letter, letter)
        g_cnt = {}
        to_update = []
        for i, proj in enumerate(self.projectors):
            li = g_cnt.get(proj.group, 0)
            if (proj.group, li) in self.selected_lamps:
                to_update.append(i)
            g_cnt[proj.group] = li + 1
        for i in to_update:
            self.projectors[i].group = new_group
        self.selected_lamps.clear()
        if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
            self.main_window._rebuild_dmx_patch()
        if self._refresh_cb:
            self._refresh_cb()

    # ── Modifier / Supprimer ────────────────────────────────────────

    def _edit_fixture(self, idx):
        # Si le dialog Patch DMX est ouvert, basculer sur l'onglet Fixtures + sélectionner la carte
        if self._select_fixture_cb:
            self._select_fixture_cb(idx)
            return
        # Fallback : dialog autonome (si appelé hors du dialog Patch DMX)
        proj = self.projectors[idx]
        dlg = EditFixtureDialog(proj, self.projectors)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_fixture_data()
            if data:
                proj.name         = data['name']
                proj.fixture_type = data['fixture_type']
                proj.group        = data['group']
                proj.start_address = data['start_address']
                if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
                    self.main_window._rebuild_dmx_patch()

    def _delete_fixture(self, idx):
        proj = self.projectors[idx]
        reply = QMessageBox.question(
            None, "Supprimer",
            f"Supprimer '{proj.name or proj.group}' ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.projectors.pop(idx)
            self.selected_lamps.clear()
            if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
                self.main_window._rebuild_dmx_patch()

    def _delete_selected_fixtures(self):
        if not self.selected_lamps:
            return
        n = len(self.selected_lamps)
        reply = QMessageBox.question(
            None, "Supprimer",
            f"Supprimer {n} fixture{'s' if n > 1 else ''} selectionnee{'s' if n > 1 else ''} ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        to_remove = set()
        g_cnt = {}
        for i, proj in enumerate(self.projectors):
            li = g_cnt.get(proj.group, 0)
            if (proj.group, li) in self.selected_lamps:
                to_remove.add(i)
            g_cnt[proj.group] = li + 1
        for i in sorted(to_remove, reverse=True):
            self.projectors.pop(i)
        self.selected_lamps.clear()
        if self.main_window and hasattr(self.main_window, '_rebuild_dmx_patch'):
            self.main_window._rebuild_dmx_patch()
        if self._refresh_cb:
            self._refresh_cb()


# ── PlanDeFeuPreview ──────────────────────────────────────────────────────────

class PlanDeFeuPreview(QWidget):
    """Previsualisation du plan de feu sous la timeline"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setFixedHeight(120)
        self.setStyleSheet("background: #0a0a0a; border-top: 2px solid #3a3a3a;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("Plan de Feu - Previsualisation")
        title.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(5)

        self.projector_widgets = {}

        face_label = QLabel("Face:")
        face_label.setStyleSheet("color: #888; font-size: 11px;")
        grid.addWidget(face_label, 0, 0)
        self.face_widget = QLabel("O")
        self.face_widget.setFixedSize(40, 40)
        self.face_widget.setAlignment(Qt.AlignCenter)
        self.face_widget.setStyleSheet("background: #1a1a1a; border-radius: 20px; font-size: 20px;")
        grid.addWidget(self.face_widget, 0, 1)

        for i in range(3):
            douche_label = QLabel(f"Douche {i+1}:")
            douche_label.setStyleSheet("color: #888; font-size: 11px;")
            grid.addWidget(douche_label, 0, 2 + i*2)
            widget = QLabel("O")
            widget.setFixedSize(40, 40)
            widget.setAlignment(Qt.AlignCenter)
            widget.setStyleSheet("background: #1a1a1a; border-radius: 20px; font-size: 20px;")
            grid.addWidget(widget, 0, 3 + i*2)
            self.projector_widgets[f'douche{i+1}'] = widget

        contres_label = QLabel("Contres:")
        contres_label.setStyleSheet("color: #888; font-size: 11px;")
        grid.addWidget(contres_label, 0, 8)
        self.contres_widget = QLabel("O")
        self.contres_widget.setFixedSize(40, 40)
        self.contres_widget.setAlignment(Qt.AlignCenter)
        self.contres_widget.setStyleSheet("background: #1a1a1a; border-radius: 20px; font-size: 20px;")
        grid.addWidget(self.contres_widget, 0, 9)

        layout.addLayout(grid)

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_preview)
        self.update_timer.start(50)

    def update_preview(self):
        if not self.main_window or not hasattr(self.main_window, 'projectors'):
            return

        for proj in self.main_window.projectors:
            widget = None

            if proj.group == "face":
                widget = self.face_widget
            elif proj.group == "contre":
                pass
            elif proj.group == "douche":
                widget = self.projector_widgets.get(f'douche{proj.index + 1}')

            if widget and proj.level > 0:
                color = proj.color
                widget.setStyleSheet(f"""
                    background: {color.name()};
                    border-radius: 20px;
                    font-size: 20px;
                """)
            elif widget:
                widget.setStyleSheet("""
                    background: #1a1a1a;
                    border-radius: 20px;
                    font-size: 20px;
                """)
