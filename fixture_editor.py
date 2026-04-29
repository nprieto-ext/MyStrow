"""
Editeur de fixture DMX — MyStrow
Interface simple : Mes projecteurs + formulaire d'édition.
"""
import copy
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QLineEdit, QComboBox, QFrame,
    QMessageBox, QListWidget, QListWidgetItem, QFileDialog,
    QAbstractItemView, QSizePolicy, QSplitter, QMenu,
    QStyledItemDelegate, QGridLayout,
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QRectF, QMimeData, QPoint
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QDrag, QPixmap, QCursor

import gzip

from builtin_fixtures import BUILTIN_FIXTURES

# Cache module du bundle OFL (chargé une seule fois à la demande)
_OFL_BUNDLE: list | None = None

# Cache module du bundle custom (fixtures Firestore exportées depuis l'admin panel)
_CUSTOM_BUNDLE: list | None = None


def _load_custom_bundle() -> list:
    """Charge fixtures_bundle_custom.json.gz en cache module (fixtures admin panel)."""
    global _CUSTOM_BUNDLE
    if _CUSTOM_BUNDLE is not None:
        return _CUSTOM_BUNDLE
    # Chercher à côté du script ou dans le dossier de l'exe (PyInstaller)
    import sys as _sys
    base = Path(getattr(_sys, "_MEIPASS", Path(__file__).parent))
    bundle_path = base / "fixtures_bundle_custom.json.gz"
    if not bundle_path.exists():
        bundle_path = Path(__file__).parent / "fixtures_bundle_custom.json.gz"
    if not bundle_path.exists():
        _CUSTOM_BUNDLE = []
        return _CUSTOM_BUNDLE
    try:
        with gzip.open(bundle_path, "rb") as f:
            _CUSTOM_BUNDLE = json.loads(f.read().decode("utf-8"))
    except Exception:
        _CUSTOM_BUNDLE = []
    return _CUSTOM_BUNDLE

def _load_ofl_bundle() -> list:
    """Charge fixtures_bundle.json.gz (OFL) en cache module."""
    global _OFL_BUNDLE
    if _OFL_BUNDLE is not None:
        return _OFL_BUNDLE
    bundle_path = Path(__file__).parent / "fixtures_bundle.json.gz"
    if not bundle_path.exists():
        _OFL_BUNDLE = []
        return _OFL_BUNDLE
    try:
        with gzip.open(bundle_path, "rb") as f:
            _OFL_BUNDLE = json.loads(f.read().decode("utf-8"))
    except Exception:
        _OFL_BUNDLE = []
    return _OFL_BUNDLE

FIXTURE_FILE = Path.home() / ".mystrow_fixtures.json"

FIXTURE_TYPES = ["PAR LED", "Moving Head", "Barre LED", "Stroboscope", "Machine a fumee"]

GROUP_OPTIONS = [
    "face", "douche1", "douche2", "douche3", "lat", "contre",
    "fumee",
]

ALL_CHANNEL_TYPES = [
    "R", "G", "B", "W", "Dim", "Strobe", "UV", "Ambre", "Orange", "Zoom",
    "Smoke", "Fan", "Pan", "PanFine", "Tilt", "TiltFine",
    "Gobo1", "Gobo1Rot", "Gobo2", "Prism", "PrismRot", "Focus", "ColorWheel", "Shutter", "Speed", "Mode",
]

CHANNEL_COLORS = {
    "R": "#cc2200", "G": "#00aa00", "B": "#0055ff", "W": "#bbbbbb",
    "Dim": "#888800", "Strobe": "#ffaa00", "UV": "#8800cc",
    "Ambre": "#ee6600", "Orange": "#ff4400", "Zoom": "#00ccaa",
    "Smoke": "#555555", "Fan": "#336699", "Pan": "#ff55aa",
    "PanFine": "#cc4488", "Tilt": "#00ddff", "TiltFine": "#00aacc",
    "Gobo1": "#aa8800", "Gobo1Rot": "#cc9900", "Gobo2": "#886600",
    "Prism": "#dd00dd", "PrismRot": "#bb00bb",
    "Focus": "#00aa88", "ColorWheel": "#ff8800", "Shutter": "#ff2266",
    "Speed": "#66ff66", "Mode": "#88aaff",
}

# Profils rapides proposés à l'utilisateur
_PRESETS_BY_TYPE = {
    "PAR LED": [
        ("RGB",       ["R", "G", "B"]),
        ("RGBD",      ["R", "G", "B", "Dim"]),
        ("DRGB",      ["Dim", "R", "G", "B"]),
        ("RGBDS",     ["R", "G", "B", "Dim", "Strobe"]),
        ("DRGBS",     ["Dim", "R", "G", "B", "Strobe"]),
        ("RGBW",      ["R", "G", "B", "W"]),
        ("RGBWD",     ["R", "G", "B", "W", "Dim"]),
        ("RGBWDS",    ["R", "G", "B", "W", "Dim", "Strobe"]),
        ("RGBWA",     ["R", "G", "B", "W", "Ambre"]),
        ("RGBWUV",    ["R", "G", "B", "W", "UV"]),
        ("RGBWAUV",   ["R", "G", "B", "W", "Ambre", "UV"]),
        ("Dim 1ch",   ["Dim"]),
        ("Dim+Strobe",["Dim", "Strobe"]),
    ],
    "Moving Head": [
        ("Wash 7ch",  ["Pan", "Tilt", "R", "G", "B", "Dim", "Speed"]),
        ("Wash 8ch",  ["Pan", "Tilt", "R", "G", "B", "Dim", "Shutter", "Speed"]),
        ("Wash 9ch",  ["Pan", "Tilt", "R", "G", "B", "W", "Dim", "Shutter", "Speed"]),
        ("Wash 10ch", ["Pan", "Tilt", "R", "G", "B", "W", "Ambre", "Dim", "Shutter", "Speed"]),
        ("Spot 5ch",  ["Shutter", "Dim", "ColorWheel", "Gobo1", "Speed"]),
        ("Spot 8ch",  ["Pan", "Tilt", "Shutter", "Dim", "ColorWheel", "Gobo1", "Speed", "Mode"]),
        ("Spot 12ch", ["Pan", "PanFine", "Tilt", "TiltFine", "Speed", "ColorWheel", "Gobo1", "Gobo1Rot", "Prism", "PrismRot", "Shutter", "Dim"]),
        ("Beam 7ch",  ["Pan", "Tilt", "ColorWheel", "Gobo1", "Shutter", "Dim", "Speed"]),
    ],
    "Barre LED": [
        ("RGB",       ["R", "G", "B"]),
        ("RGBD",      ["R", "G", "B", "Dim"]),
        ("RGBDS",     ["R", "G", "B", "Dim", "Strobe"]),
        ("RGBW",      ["R", "G", "B", "W"]),
        ("RGBWDS",    ["R", "G", "B", "W", "Dim", "Strobe"]),
        ("RGBWAUV",   ["R", "G", "B", "W", "Ambre", "UV"]),
    ],
    "Stroboscope": [
        ("1ch",       ["Dim"]),
        ("2ch",       ["Shutter", "Dim"]),
        ("3ch",       ["Shutter", "Dim", "Speed"]),
    ],
    "Machine a fumee": [
        ("Fumée 1ch", ["Smoke"]),
        ("Fumée 2ch", ["Smoke", "Fan"]),
        ("Hazer 2ch", ["Smoke", "Fan"]),
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# Classes conservées pour compatibilité avec admin_pack_editor / admin_panel
# ──────────────────────────────────────────────────────────────────────────────

class _NoScrollCombo(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class DmxPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels = []
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_channels(self, channels):
        self._channels = list(channels)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#111"))
        n = len(self._channels)
        if n == 0:
            painter.setPen(QColor("#444"))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(0, 0, w, h, Qt.AlignCenter, "Aucun canal")
            return
        bw = max(20, min(70, w // n))
        x0 = max(0, (w - bw * n) // 2)
        for i, ch in enumerate(self._channels):
            x = x0 + i * bw
            c = QColor(CHANNEL_COLORS.get(ch, "#444"))
            painter.fillRect(x + 1, 3, bw - 2, h - 6, c.darker(220))
            painter.setPen(QPen(c, 1))
            painter.drawRect(x + 1, 3, bw - 2, h - 6)
            painter.setPen(QColor("#888"))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(x, 3, bw, 11, Qt.AlignCenter, str(i + 1))
            painter.setPen(c.lighter(170))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(x, 14, bw, h - 17, Qt.AlignCenter,
                             ch if len(ch) <= 5 else ch[:4] + ".")
        painter.end()


class ChannelRowWidget(QWidget):
    """Conservé pour compatibilité admin_pack_editor."""
    remove_requested  = Signal(object)
    move_up_requested = Signal(object)
    move_dn_requested = Signal(object)
    changed           = Signal()

    def __init__(self, ch_num, ch_type, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self.setStyleSheet("background:#1e1e1e;border-radius:3px;")
        self._prev_type = ch_type
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        color = CHANNEL_COLORS.get(ch_type, "#666")
        self._num_lbl = QLabel(f"{ch_num:02d}")
        self._num_lbl.setFixedSize(26, 26)
        self._num_lbl.setAlignment(Qt.AlignCenter)
        self._set_num_style(color)
        layout.addWidget(self._num_lbl)
        self._combo = _NoScrollCombo()
        self._combo.setFixedHeight(26)
        self._combo.setStyleSheet(
            "QComboBox{background:#2a2a2a;color:#e0e0e0;border:1px solid #3a3a3a;"
            "border-radius:3px;padding:1px 6px;font-size:12px;}"
            "QComboBox::drop-down{border:none;width:16px;}"
            "QComboBox QAbstractItemView{background:#222;color:#e0e0e0;}"
        )
        for ct in ALL_CHANNEL_TYPES:
            self._combo.addItem(ct)
        self._combo.setCurrentIndex(
            ALL_CHANNEL_TYPES.index(ch_type) if ch_type in ALL_CHANNEL_TYPES else 0
        )
        self._combo.currentTextChanged.connect(self._on_type_changed)
        layout.addWidget(self._combo, 1)
        _bs = ("QPushButton{background:#2a2a2a;color:#999;border:1px solid #3a3a3a;"
               "border-radius:3px;font-size:10px;min-width:0;padding:0;}"
               "QPushButton:hover{background:#3a3a3a;color:#fff;border-color:#555;}")
        self._action_btns = []
        for text, slot in [("▲", self._on_up), ("▼", self._on_dn)]:
            b = QPushButton(text)
            b.setFixedSize(34, 30)
            b.setStyleSheet(_bs)
            b.clicked.connect(slot)
            layout.addWidget(b)
            self._action_btns.append(b)
        btn_rm = QPushButton("✕")
        btn_rm.setFixedSize(34, 30)
        btn_rm.setStyleSheet(
            "QPushButton{background:#2a0000;color:#cc4444;border:1px solid #3a1111;"
            "border-radius:3px;font-size:11px;font-weight:bold;min-width:0;padding:0;}"
            "QPushButton:hover{background:#440000;color:#ff6666;}")
        btn_rm.clicked.connect(self._on_rm)
        layout.addWidget(btn_rm)
        self._action_btns.append(btn_rm)

    def _set_num_style(self, color):
        self._num_lbl.setStyleSheet(
            f"QLabel{{background:{color}22;border:1px solid {color};"
            f"border-radius:3px;color:{color};font-weight:bold;font-size:11px;}}")

    def set_type(self, t):
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(
            ALL_CHANNEL_TYPES.index(t) if t in ALL_CHANNEL_TYPES else 0)
        self._set_num_style(CHANNEL_COLORS.get(t, "#666"))
        self._combo.blockSignals(False)
        self._prev_type = t

    def set_read_only(self, ro):
        self._combo.setEnabled(not ro)
        for b in self._action_btns:
            b.setVisible(not ro)

    def _on_type_changed(self, t):
        self._set_num_style(CHANNEL_COLORS.get(t, "#666"))
        self.changed.emit()

    def _on_up(self): self.move_up_requested.emit(self)
    def _on_dn(self): self.move_dn_requested.emit(self)
    def _on_rm(self): self.remove_requested.emit(self)
    def set_num(self, n): self._num_lbl.setText(f"{n:02d}")
    def get_type(self): return self._combo.currentText()


# ──────────────────────────────────────────────────────────────────────────────
# _ProfileBlockDelegate — blocs carrés colorés pour la ligne de profil
# ──────────────────────────────────────────────────────────────────────────────

_BLOCK_W = 72
_BLOCK_H = 72

# Rôles de données pour les items du profil
_ROLE_CH  = Qt.UserRole        # str  : nom du canal ("R", "Mode"…)
_ROLE_VAL = Qt.UserRole + 1    # int  : valeur fixe 0-255, ou -1 si non définie


class _ProfileBlockDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(_BLOCK_W, _BLOCK_H)

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyle
        from PySide6.QtCore import QRect
        ch  = index.data(_ROLE_CH) or ""
        raw = index.data(_ROLE_VAL)
        val = int(raw) if isinstance(raw, int) and raw >= 0 else None
        num = index.row() + 1
        col = QColor(CHANNEL_COLORS.get(ch, "#444"))
        sel = bool(option.state & QStyle.State_Selected)

        painter.save()
        r = option.rect.adjusted(4, 4, -4, -4)

        # Fond coloré
        painter.setPen(QPen(col if sel else col.darker(160), 1.5))
        painter.setBrush(col.darker(240) if not sel else col.darker(180))
        painter.drawRoundedRect(QRectF(r), 8, 8)

        # Numéro (petit, en haut à gauche)
        painter.setPen(QColor("#777") if not sel else QColor("#aaa"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(r.adjusted(6, 4, 0, 0), Qt.AlignTop | Qt.AlignLeft, f"{num:02d}")

        # Nom du canal (centré, grand)
        painter.setPen(col.lighter(200) if not sel else col.lighter(240))
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.drawText(r, Qt.AlignCenter, ch)

        # Badge valeur fixe — fond blanc, texte noir, en haut à droite
        if val is not None:
            badge_txt = str(val)
            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(badge_txt) + 6
            th = fm.height() + 2
            badge_r = QRect(r.right() - tw - 3, r.top() + 3, tw, th)
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(badge_r), 3, 3)
            painter.setPen(QColor("#000000"))
            painter.drawText(badge_r, Qt.AlignCenter, badge_txt)

        # Petites poignées drag en bas
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#444") if not sel else QColor("#666"))
        bx = r.center().x() - 7
        by = r.bottom() - 8
        for dx in (0, 6, 12):
            painter.drawEllipse(bx + dx, by, 3, 3)

        painter.restore()


# ──────────────────────────────────────────────────────────────────────────────
# _ProfileStrip — ligne horizontale de blocs drag & drop
# ──────────────────────────────────────────────────────────────────────────────

class _ProfileStrip(QListWidget):
    """Ligne horizontale de blocs colorés représentant le profil DMX.
    Drag & drop interne pour réordonner. Accepte aussi le drop depuis la palette.
    """
    order_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setItemDelegate(_ProfileBlockDelegate(self))
        self.setSpacing(4)
        self.setFixedHeight(_BLOCK_H + 18)
        self.setStyleSheet(
            "QListWidget{background:#111;border:1px solid #222;border-radius:10px;outline:none;"
            "padding:4px;}"
            "QListWidget::item{border-radius:8px;}"
            "QScrollBar:horizontal{background:#111;height:5px;border-radius:2px;}"
            "QScrollBar::handle:horizontal{background:#333;border-radius:2px;}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}"
        )
        self.model().rowsMoved.connect(lambda: self.order_changed.emit())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            row = self.currentRow()
            if row >= 0:
                self.takeItem(row)
                self.order_changed.emit()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Double-clic pour retirer un canal."""
        item = self.itemAt(event.pos())
        if item:
            self.takeItem(self.row(item))
            self.order_changed.emit()

    # ── Accepter les drops depuis la palette ──────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasText() and event.source() is not self:
            ch = event.mimeData().text()
            # Vérifier doublon (sauf Mode)
            if ch != "Mode":
                for i in range(self.count()):
                    if self.item(i).data(_ROLE_CH) == ch:
                        event.acceptProposedAction()
                        return
            # Insérer à la position du drop
            target = self.indexAt(event.pos())
            insert_row = target.row() if target.isValid() else self.count()
            self.insertItem(insert_row, self._make_item(ch, -1))
            self.scrollToItem(self.item(insert_row))
            self.order_changed.emit()
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
            self.order_changed.emit()

    # ── Clic droit → valeur fixe ──────────────────────────────────────────────

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QInputDialog
        item = self.itemAt(event.pos())
        if not item:
            return
        ch  = item.data(_ROLE_CH) or ""
        raw = item.data(_ROLE_VAL)
        val = int(raw) if isinstance(raw, int) and raw >= 0 else None

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#1e1e1e;color:#ccc;border:1px solid #2a2a2a;font-size:12px;}"
            "QMenu::item{padding:7px 20px;}"
            "QMenu::item:selected{background:#00d4ff18;color:#00d4ff;}"
            "QMenu::item:disabled{color:#444;}"
        )
        lbl = f"Valeur fixe : {val}" if val is not None else "Définir valeur fixe…"
        act_set   = menu.addAction(lbl)
        act_clear = menu.addAction("Effacer la valeur fixe")
        act_clear.setEnabled(val is not None)
        menu.addSeparator()
        act_del = menu.addAction("Supprimer ce canal")

        chosen = menu.exec(self.mapToGlobal(event.pos()))
        if chosen == act_set:
            v, ok = QInputDialog.getInt(
                self, "Valeur fixe DMX",
                f"Valeur DMX pour « {ch} » (0 = éteint, 255 = 100%) :",
                val if val is not None else 0, 0, 255
            )
            if ok:
                item.setData(_ROLE_VAL, v)
                self.order_changed.emit()
        elif chosen == act_clear:
            item.setData(_ROLE_VAL, -1)
            self.order_changed.emit()
        elif chosen == act_del:
            self.takeItem(self.row(item))
            self.order_changed.emit()

    # ── API ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _make_item(ch: str, val: int = -1) -> QListWidgetItem:
        """Crée un item correctement typé (val = -1 → pas de valeur fixe)."""
        item = QListWidgetItem()
        item.setData(_ROLE_CH, ch)
        item.setData(_ROLE_VAL, val)
        item.setSizeHint(QSize(_BLOCK_W, _BLOCK_H))
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
        return item

    def get_channels(self):
        return [self.item(i).data(_ROLE_CH) or "" for i in range(self.count())]

    def get_defaults(self):
        result = []
        for i in range(self.count()):
            raw = self.item(i).data(_ROLE_VAL)
            result.append(int(raw) if isinstance(raw, int) and raw >= 0 else None)
        return result

    def add_channel(self, ch_type) -> bool:
        if ch_type != "Mode":
            if any(self.item(i).data(_ROLE_CH) == ch_type for i in range(self.count())):
                return False
        self.addItem(self._make_item(ch_type))
        self.scrollToItem(self.item(self.count() - 1))
        self.order_changed.emit()
        return True

    def set_channels(self, channels, defaults=None):
        self.blockSignals(True)
        self.clear()
        for i, ch in enumerate(channels):
            d = defaults[i] if defaults and i < len(defaults) else None
            val = int(d) if d is not None and int(d) >= 0 else -1
            self.addItem(self._make_item(ch, val))
        self.blockSignals(False)
        self.order_changed.emit()


# ──────────────────────────────────────────────────────────────────────────────
# _PaletteBlock — bloc de canal glissable depuis la palette
# ──────────────────────────────────────────────────────────────────────────────

class _PaletteBlock(QWidget):
    """Bloc coloré représentant un type de canal. Clic ou drag pour ajouter."""
    clicked_channel = Signal(str)

    _W, _H = 68, 52

    def __init__(self, ch_type, parent=None):
        super().__init__(parent)
        self._ch = ch_type
        col = CHANNEL_COLORS.get(ch_type, "#444")
        self._col = QColor(col)
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Cliquer ou glisser pour ajouter « {ch_type} »")
        self._drag_start: QPoint | None = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(2, 2, -2, -2)
        c = self._col
        # Fond
        painter.setPen(QPen(c.darker(160), 1))
        painter.setBrush(c.darker(280))
        painter.drawRoundedRect(QRectF(r), 7, 7)
        # Nom centré
        painter.setPen(c.lighter(200))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(r, Qt.AlignCenter, self._ch)
        # Petite icône drag en bas
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#555"))
        bx = r.center().x() - 5
        by = r.bottom() - 7
        for dx in (0, 5, 10):
            painter.drawEllipse(bx + dx, by, 2, 2)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if self._drag_start is None:
            return
        if (event.pos() - self._drag_start).manhattanLength() < 8:
            return
        # Lancer le drag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self._ch)
        drag.setMimeData(mime)
        # Pixmap de prévisualisation
        pix = QPixmap(self._W, self._H)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self._col, 1.5))
        p.setBrush(self._col.darker(220))
        p.drawRoundedRect(QRectF(2, 2, self._W - 4, self._H - 4), 7, 7)
        p.setPen(self._col.lighter(200))
        p.setFont(QFont("Segoe UI", 11, QFont.Bold))
        p.drawText(pix.rect(), Qt.AlignCenter, self._ch)
        p.end()
        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(self._W // 2, self._H // 2))
        drag.exec(Qt.CopyAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_start is not None:
            if (event.pos() - self._drag_start).manhattanLength() < 8:
                self.clicked_channel.emit(self._ch)
        self._drag_start = None


# ──────────────────────────────────────────────────────────────────────────────
# FixtureEditorDialog
# ──────────────────────────────────────────────────────────────────────────────

class FixtureEditorDialog(QDialog):
    fixture_added = Signal(dict)

    _STYLE = """
        QDialog, QWidget   { background:#141414; color:#e0e0e0; }
        QLabel             { background:transparent; color:#e0e0e0; }
        QLineEdit          { background:#1e1e1e; color:#fff; border:1px solid #333;
                             border-radius:6px; padding:6px 12px; font-size:13px; }
        QLineEdit:focus    { border-color:#00d4ff66; }
        QComboBox          { background:#1e1e1e; color:#e0e0e0; border:1px solid #333;
                             border-radius:6px; padding:4px 10px; font-size:12px; }
        QComboBox::drop-down { border:none; width:20px; }
        QComboBox QAbstractItemView { background:#1e1e1e; color:#e0e0e0;
                             selection-background-color:#00d4ff; selection-color:#000;
                             border:1px solid #333; }
        QPushButton        { background:#222; color:#ccc; border:1px solid #383838;
                             border-radius:6px; padding:5px 14px; font-size:12px; }
        QPushButton:hover  { border-color:#00d4ff; color:#fff; }
        QPushButton:disabled { background:#181818; color:#333; border-color:#222; }
        QScrollBar:vertical { background:#1a1a1a; width:6px; border-radius:3px; }
        QScrollBar::handle:vertical { background:#333; border-radius:3px; min-height:16px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        QSplitter::handle  { background:#1e1e1e; }
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Mes projecteurs — MyStrow")
        self.setMinimumSize(860, 520)
        self.showMaximized()

        self._fixtures    = []
        self._current_idx = -1
        self._btn_add_to_patch = None   # compatibilité externe

        self._load_fixtures()
        self._build_ui()
        self._rebuild_presets(FIXTURE_TYPES[0])
        self._rebuild_list()

        if self._fixtures:
            self._select_fixture(0)
        else:
            self._show_empty_state()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_fixtures(self):
        """Charge uniquement les fixtures créées par l'utilisateur."""
        try:
            if FIXTURE_FILE.exists():
                data = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._fixtures = [
                        f for f in data
                        if isinstance(f, dict)
                        and not f.get("builtin")
                        and f.get("source", "user") not in ("firestore", "ofl")
                    ]
                    for f in self._fixtures:
                        if not f.get("profile") and f.get("modes"):
                            f["profile"] = f["modes"][0].get("profile", [])
        except Exception:
            self._fixtures = []

    def _save_fixtures(self):
        try:
            FIXTURE_FILE.write_text(
                json.dumps(self._fixtures, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Sauvegarde impossible :\n{e}")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(self._STYLE)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        root.addWidget(splitter)

        # ── Colonne gauche ────────────────────────────────────────────────────
        left = QWidget()
        left.setStyleSheet("QWidget{background:#0d0d0d;}")
        left.setMinimumWidth(180)
        left.setMaximumWidth(260)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        # En-tête
        hbar = QWidget()
        hbar.setFixedHeight(50)
        hbar.setStyleSheet("background:#111;border-bottom:1px solid #1e1e1e;")
        hbl = QHBoxLayout(hbar)
        hbl.setContentsMargins(14, 0, 10, 0)
        lbl = QLabel("Mes projecteurs")
        lbl.setStyleSheet("font-size:13px;font-weight:bold;color:#ddd;")
        hbl.addWidget(lbl)
        lv.addWidget(hbar)

        # Liste
        self._my_list = QListWidget()
        self._my_list.setStyleSheet(
            "QListWidget{background:transparent;border:none;color:#ccc;"
            "font-size:12px;outline:none;}"
            "QListWidget::item{padding:11px 14px;border-left:3px solid transparent;}"
            "QListWidget::item:selected{background:#00d4ff12;color:#00d4ff;"
            "font-weight:bold;border-left:3px solid #00d4ff;}"
            "QListWidget::item:hover:!selected{background:#161616;color:#eee;}"
        )
        self._my_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._my_list.customContextMenuRequested.connect(self._list_context_menu)
        self._my_list.currentRowChanged.connect(self._on_list_selection)
        lv.addWidget(self._my_list, 1)

        # Boutons Nouveau + Copier
        foot = QWidget()
        foot.setFixedHeight(96)
        foot.setStyleSheet("background:#0d0d0d;border-top:1px solid #1a1a1a;")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(6)
        btn_new = QPushButton("+ Nouveau projecteur")
        btn_new.setFixedHeight(34)
        btn_new.setStyleSheet(
            "QPushButton{background:#00d4ff;color:#000;border:none;"
            "border-radius:7px;font-size:12px;font-weight:bold;}"
            "QPushButton:hover{background:#33ddff;}"
        )
        btn_new.clicked.connect(self._new_fixture)
        fl.addWidget(btn_new)
        btn_copy_lib = QPushButton("📋  Copier depuis bibliothèque")
        btn_copy_lib.setFixedHeight(30)
        btn_copy_lib.setStyleSheet(
            "QPushButton{background:#1a1a2a;color:#8899cc;border:1px solid #2a2a44;"
            "border-radius:6px;font-size:11px;}"
            "QPushButton:hover{background:#222236;color:#aabbee;border-color:#4444aa;}"
        )
        btn_copy_lib.clicked.connect(self._copy_from_library)
        fl.addWidget(btn_copy_lib)
        lv.addWidget(foot)
        splitter.addWidget(left)

        # ── Panneau droit ─────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:#141414;border:none;}")
        self._right_inner = QWidget()
        self._right_inner.setStyleSheet("QWidget{background:#141414;}")
        self._right_vbox = QVBoxLayout(self._right_inner)
        self._right_vbox.setContentsMargins(40, 32, 40, 32)
        self._right_vbox.setSpacing(0)
        scroll.setWidget(self._right_inner)
        splitter.addWidget(scroll)
        splitter.setSizes([220, 800])

        self._build_editor_panel()

    def _build_editor_panel(self):
        rv = self._right_vbox

        # Titre + Supprimer
        hdr = QHBoxLayout()
        self._editor_title = QLabel("Nouveau projecteur")
        self._editor_title.setStyleSheet(
            "font-size:22px;font-weight:bold;color:#00d4ff;"
        )
        hdr.addWidget(self._editor_title, 1)
        self._btn_delete = QPushButton("🗑  Supprimer")
        self._btn_delete.setFixedHeight(30)
        self._btn_delete.setEnabled(False)
        self._btn_delete.setStyleSheet(
            "QPushButton{background:transparent;color:#554444;border:1px solid #332222;"
            "border-radius:5px;font-size:11px;padding:0 12px;}"
            "QPushButton:hover{color:#cc4444;border-color:#993333;}"
            "QPushButton:disabled{color:#333;border-color:#1e1e1e;}"
        )
        self._btn_delete.clicked.connect(self._delete_fixture)
        hdr.addWidget(self._btn_delete)
        self._btn_save = QPushButton("💾  Enregistrer")
        self._btn_save.setFixedHeight(30)
        self._btn_save.setStyleSheet(
            "QPushButton{background:#00d4ff;color:#000;border:none;"
            "border-radius:5px;font-size:11px;font-weight:bold;padding:0 14px;}"
            "QPushButton:hover{background:#33ddff;}"
            "QPushButton:disabled{background:#181818;color:#333;border:1px solid #222;}"
        )
        self._btn_save.clicked.connect(self._save_current)
        hdr.addWidget(self._btn_save)
        btn_close = QPushButton("✕  Fermer")
        btn_close.setFixedHeight(30)
        btn_close.setStyleSheet(
            "QPushButton{background:transparent;color:#666;border:1px solid #333;"
            "border-radius:5px;font-size:11px;padding:0 12px;}"
            "QPushButton:hover{color:#fff;border-color:#555;}"
        )
        btn_close.clicked.connect(self.accept)
        hdr.addWidget(btn_close)
        rv.addLayout(hdr)
        rv.addSpacing(28)

        # Nom
        rv.addWidget(self._lbl("MARQUE ET MODÈLE"))
        rv.addSpacing(5)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(
            "Ex : Chauvet SlimPAR Pro H, ADJ Mega Tri Par, Lyre Beam 7R…"
        )
        self._name_edit.setFixedHeight(40)
        self._name_edit.textChanged.connect(
            lambda t: self._editor_title.setText(t or "Nouveau projecteur")
        )
        rv.addWidget(self._name_edit)
        rv.addSpacing(16)

        # Type + Nom du mode sur la même ligne
        type_mode_row = QHBoxLayout()
        type_mode_row.setSpacing(16)

        tc = QVBoxLayout()
        tc.setSpacing(5)
        tc.addWidget(self._lbl("TYPE"))
        self._type_combo = _NoScrollCombo()
        self._type_combo.setFixedHeight(38)
        for ft in FIXTURE_TYPES:
            self._type_combo.addItem(ft)
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        tc.addWidget(self._type_combo)
        type_mode_row.addLayout(tc, 1)

        mc = QVBoxLayout()
        mc.setSpacing(5)
        mc.addWidget(self._lbl("NOM DU MODE / PROTOCOLE"))
        self._mode_name_edit = QLineEdit()
        self._mode_name_edit.setPlaceholderText("Ex : Mode 8ch, Standard, Extended…")
        self._mode_name_edit.setFixedHeight(38)
        mc.addWidget(self._mode_name_edit)
        type_mode_row.addLayout(mc, 1)

        rv.addLayout(type_mode_row)
        rv.addSpacing(28)

        # Séparateur
        rv.addWidget(self._sep())
        rv.addSpacing(22)

        # ── Section canaux ────────────────────────────────────────────────────
        ch_hdr = QHBoxLayout()
        ch_hdr.addWidget(self._lbl("PROFIL DMX"))
        self._ch_count_lbl = QLabel("0 canal")
        self._ch_count_lbl.setStyleSheet("font-size:11px;color:#444;")
        ch_hdr.addStretch()
        ch_hdr.addWidget(self._ch_count_lbl)
        rv.addLayout(ch_hdr)
        rv.addSpacing(6)

        # Profils rapides — grille dynamique selon le type
        rv.addWidget(self._lbl("DÉMARRER AVEC UN PROFIL"))
        rv.addSpacing(6)
        self._presets_wrap = QWidget()
        self._presets_wrap.setStyleSheet("QWidget{background:transparent;}")
        self._presets_grid = QGridLayout(self._presets_wrap)
        self._presets_grid.setContentsMargins(0, 0, 0, 0)
        self._presets_grid.setSpacing(5)
        rv.addWidget(self._presets_wrap)
        rv.addSpacing(14)

        # Ligne de profil (blocs drag & drop)
        profile_hint = QLabel(
            "Profil actuel — glisser pour réordonner · double-clic/Suppr pour retirer · clic droit pour valeur fixe"
        )
        profile_hint.setStyleSheet("font-size:10px;color:#444;")
        rv.addWidget(profile_hint)
        rv.addSpacing(5)

        self._ch_list = _ProfileStrip()
        self._ch_list.order_changed.connect(self._on_channels_changed)
        rv.addWidget(self._ch_list)
        rv.addSpacing(18)

        # Palette — tous les canaux disponibles
        palette_lbl = QLabel("Canaux disponibles — cliquer ou glisser vers le profil")
        palette_lbl.setStyleSheet("font-size:10px;color:#444;")
        rv.addWidget(palette_lbl)
        rv.addSpacing(8)

        palette_wrap = QWidget()
        palette_wrap.setStyleSheet("QWidget{background:transparent;}")
        pg = QGridLayout(palette_wrap)
        pg.setContentsMargins(0, 0, 0, 0)
        pg.setSpacing(6)
        cols = 8
        for idx, ct in enumerate(ALL_CHANNEL_TYPES):
            ri, ci = divmod(idx, cols)
            block = _PaletteBlock(ct)
            block.clicked_channel.connect(self._ch_list.add_channel)
            pg.addWidget(block, ri, ci)
        rv.addWidget(palette_wrap)
        rv.addSpacing(16)

        rv.addSpacing(28)
        rv.addWidget(self._sep())
        rv.addSpacing(20)

        rv.addStretch()

    def _lbl(self, text):
        l = QLabel(text)
        l.setStyleSheet(
            "font-size:10px;color:#555;font-weight:bold;letter-spacing:1.2px;"
        )
        return l

    def _sep(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setFixedHeight(1)
        f.setStyleSheet("background:#222;")
        return f

    # ── Etat vide ─────────────────────────────────────────────────────────────

    def _show_empty_state(self):
        self._current_idx = -1
        self._name_edit.setText("")
        self._editor_title.setText("Nouveau projecteur")
        self._type_combo.setCurrentIndex(0)
        self._rebuild_presets(FIXTURE_TYPES[0])
        self._mode_name_edit.setText("")
        self._ch_list.set_channels(["R", "G", "B"])
        self._btn_delete.setEnabled(False)

    # ── Gestion liste ─────────────────────────────────────────────────────────

    def _rebuild_list(self):
        self._my_list.blockSignals(True)
        self._my_list.clear()
        for fx in self._fixtures:
            name = fx.get("name", "Sans nom")
            n_ch = len(fx.get("profile", []))
            item = QListWidgetItem(name)
            item.setToolTip(f"{fx.get('fixture_type', '')}  ·  {n_ch} ch")
            self._my_list.addItem(item)
        self._my_list.blockSignals(False)

    def _on_list_selection(self, row):
        if 0 <= row < len(self._fixtures):
            self._select_fixture(row)

    def _list_context_menu(self, pos):
        item = self._my_list.itemAt(pos)
        if not item:
            return
        row = self._my_list.row(item)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#1e1e1e;color:#ccc;border:1px solid #2a2a2a;}"
            "QMenu::item{padding:7px 20px;}"
            "QMenu::item:selected{background:#00d4ff18;color:#00d4ff;}"
        )
        act_dup = menu.addAction("Dupliquer")
        act_del = menu.addAction("Supprimer")
        act = menu.exec(self._my_list.mapToGlobal(pos))
        if act == act_dup:
            self._duplicate_at(row)
        elif act == act_del:
            self._delete_at(row)

    def _select_fixture(self, idx):
        if idx < 0 or idx >= len(self._fixtures):
            return
        self._current_idx = idx
        fx = self._fixtures[idx]
        self._name_edit.blockSignals(True)
        self._name_edit.setText(fx.get("name", ""))
        self._name_edit.blockSignals(False)
        self._editor_title.setText(fx.get("name", "Projecteur"))
        self._type_combo.blockSignals(True)
        ti = self._type_combo.findText(fx.get("fixture_type", "PAR LED"))
        if ti >= 0:
            self._type_combo.setCurrentIndex(ti)
        self._type_combo.blockSignals(False)
        self._rebuild_presets(fx.get("fixture_type", "PAR LED"))
        self._mode_name_edit.setText(fx.get("mode_name", ""))
        max_ch = fx.get("max_channels", 512)
        self._ch_list.set_channels(fx.get("profile", []), fx.get("defaults"))
        self._btn_delete.setEnabled(True)
        self._my_list.blockSignals(True)
        self._my_list.setCurrentRow(idx)
        item = self._my_list.item(idx)
        if item:
            self._my_list.scrollToItem(item)
        self._my_list.blockSignals(False)
        self._name_edit.setFocus()

    def _new_fixture(self):
        self._current_idx = -1
        self._name_edit.blockSignals(True)
        self._name_edit.setText("")
        self._name_edit.blockSignals(False)
        self._editor_title.setText("Nouveau projecteur")
        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentIndex(0)
        self._type_combo.blockSignals(False)
        self._rebuild_presets(FIXTURE_TYPES[0])
        self._mode_name_edit.setText("")
        self._ch_list.set_channels(["R", "G", "B"])
        self._btn_delete.setEnabled(False)
        self._my_list.blockSignals(True)
        self._my_list.clearSelection()
        self._my_list.blockSignals(False)
        self._name_edit.setFocus()

    def _copy_from_library(self):
        """Ouvre un picker sur les fixtures builtin pour copier profil/type dans l'éditeur."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
            QListWidget, QListWidgetItem, QLabel,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("Copier depuis la bibliothèque")
        dlg.resize(560, 460)
        dlg.setStyleSheet(
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
            "QLabel{color:#888;font-size:11px;}"
        )

        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(10)

        search = QLineEdit()
        search.setPlaceholderText("🔍  Rechercher par nom ou type…")
        search.setFixedHeight(36)
        vl.addWidget(search)

        lst = QListWidget()
        vl.addWidget(lst, 1)

        hint = QLabel("Double-clic ou bouton Copier pour importer le profil dans l'éditeur.")
        hint.setAlignment(Qt.AlignCenter)
        vl.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Copier le profil")
        btn_ok.setFixedHeight(36)
        btn_ok.setStyleSheet(
            "QPushButton{background:#00d4ff;color:#000;font-weight:bold;"
            "border:none;border-radius:6px;padding:6px 24px;font-size:13px;}"
            "QPushButton:hover{background:#33ddff;}"
        )
        btn_cancel = QPushButton("Annuler")
        btn_cancel.setFixedHeight(36)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        vl.addLayout(btn_row)

        # Builtins + bundle OFL + bundle custom (admin panel) — dédupliqués
        _seen = {(fx["name"], fx.get("manufacturer", "")) for fx in BUILTIN_FIXTURES}
        ofl_extra = [
            fx for fx in _load_ofl_bundle()
            if (fx["name"], fx.get("manufacturer", "")) not in _seen
        ]
        _seen.update((fx["name"], fx.get("manufacturer", "")) for fx in ofl_extra)
        custom_extra = []
        for fx in _load_custom_bundle():
            key = (fx.get("name", ""), fx.get("manufacturer", ""))
            if key not in _seen:
                if not fx.get("profile") and fx.get("modes"):
                    fx = dict(fx)
                    fx["profile"] = fx["modes"][0].get("profile", [])
                custom_extra.append(fx)
                _seen.add(key)
        all_fixtures = list(BUILTIN_FIXTURES) + ofl_extra + custom_extra

        def _fill(q=""):
            lst.clear()
            q = q.strip().lower()
            for fx in all_fixtures:
                if q and q not in fx.get("name", "").lower() \
                       and q not in fx.get("fixture_type", "").lower() \
                       and q not in fx.get("manufacturer", "").lower():
                    continue
                n   = fx.get("name", "?")
                mfr = fx.get("manufacturer", "")
                nch = len(fx.get("profile", []))
                lbl = f"{n}  ({nch}ch)"
                if mfr:
                    lbl += f"   — {mfr}"
                item = QListWidgetItem(lbl)
                item.setData(Qt.UserRole, fx)
                lst.addItem(item)
            if lst.count():
                lst.setCurrentRow(0)

        search.textChanged.connect(_fill)
        _fill()

        result = [None]

        def _accept():
            item = lst.currentItem()
            if not item:
                return
            result[0] = item.data(Qt.UserRole)
            dlg.accept()

        btn_ok.clicked.connect(_accept)
        lst.itemDoubleClicked.connect(lambda _: _accept())

        dlg.exec()
        fx = result[0]
        if not fx:
            return

        # Remplir le formulaire avec les données copiées (sans écraser le nom)
        self._type_combo.blockSignals(True)
        ti = self._type_combo.findText(fx.get("fixture_type", "PAR LED"))
        if ti >= 0:
            self._type_combo.setCurrentIndex(ti)
        self._type_combo.blockSignals(False)
        self._rebuild_presets(fx.get("fixture_type", "PAR LED"))
        if fx.get("mode_name"):
            self._mode_name_edit.setText(fx["mode_name"])
        max_ch = fx.get("max_channels", 512)
        self._ch_list.set_channels(fx.get("profile", []), fx.get("defaults"))

    # ── Presets dynamiques ────────────────────────────────────────────────────

    def _on_type_changed(self, fixture_type: str):
        self._rebuild_presets(fixture_type)

    def _rebuild_presets(self, fixture_type: str | None = None):
        if fixture_type is None:
            fixture_type = self._type_combo.currentText()
        # Vider la grille
        while self._presets_grid.count():
            item = self._presets_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        presets = _PRESETS_BY_TYPE.get(fixture_type, [])
        _pcols = 7
        for pi, (label, profile) in enumerate(presets):
            pr, pc = divmod(pi, _pcols)
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton{background:#1a1a1a;color:#777;border:1px solid #2a2a2a;"
                "border-radius:5px;font-size:10px;padding:0 10px;}"
                "QPushButton:hover{background:#222;color:#bbb;border-color:#3a3a3a;}"
            )
            btn.clicked.connect(lambda _=False, p=profile: self._ch_list.set_channels(p))
            self._presets_grid.addWidget(btn, pr, pc)

    # ── Canaux ────────────────────────────────────────────────────────────────

    def _on_channels_changed(self):
        channels = self._ch_list.get_channels()
        n = len(channels)
        self._ch_count_lbl.setText(f"{n} canal{'x' if n > 1 else ''}")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _get_form_data(self):
        profile  = self._ch_list.get_channels()
        defaults = self._ch_list.get_defaults()
        data = {
            "name":         self._name_edit.text().strip(),
            "manufacturer": "Générique",
            "fixture_type": self._type_combo.currentText(),
            "mode_name":    self._mode_name_edit.text().strip(),
            "max_channels": 512,
            "group":        "face",
            "profile":      profile,
            "source":       "user",
        }
        if any(v is not None for v in defaults):
            data["defaults"] = defaults
        return data

    def _save_current(self):
        data = self._get_form_data()
        if not data["name"]:
            QMessageBox.warning(self, "Nom requis",
                "Veuillez entrer un nom pour le projecteur.")
            self._name_edit.setFocus()
            return
        if not data["profile"]:
            QMessageBox.warning(self, "Canaux requis",
                "Ajoutez au moins un canal DMX.")
            return

        is_new = self._current_idx < 0
        if not is_new and 0 <= self._current_idx < len(self._fixtures):
            self._fixtures[self._current_idx] = data
        else:
            existing = {f["name"] for f in self._fixtures}
            name = data["name"]
            if name in existing:
                c = 2
                while f"{name} ({c})" in existing:
                    c += 1
                data["name"] = f"{name} ({c})"
                self._name_edit.setText(data["name"])
            self._fixtures.append(data)
            self._current_idx = len(self._fixtures) - 1

        self._save_fixtures()
        self._rebuild_list()
        self._my_list.setCurrentRow(self._current_idx)
        self._btn_delete.setEnabled(True)
        self._editor_title.setText(data["name"])

        if is_new:
            self.fixture_added.emit(data)

        orig = self._btn_save.text()
        self._btn_save.setText("✓  Enregistré !")
        self._btn_save.setEnabled(False)
        QTimer.singleShot(1200, lambda: (
            self._btn_save.setText(orig),
            self._btn_save.setEnabled(True),
        ))

    def _delete_fixture(self):
        self._delete_at(self._current_idx)

    def _delete_at(self, idx):
        if idx < 0 or idx >= len(self._fixtures):
            return
        name = self._fixtures[idx].get("name", "ce projecteur")
        if QMessageBox.question(
            self, "Supprimer",
            f"Supprimer « {name} » ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._fixtures.pop(idx)
        self._save_fixtures()
        self._current_idx = -1
        self._rebuild_list()
        if self._fixtures:
            self._select_fixture(min(idx, len(self._fixtures) - 1))
        else:
            self._show_empty_state()

    def _duplicate_at(self, idx):
        if idx < 0 or idx >= len(self._fixtures):
            return
        fx = copy.deepcopy(self._fixtures[idx])
        existing = {f["name"] for f in self._fixtures}
        base, c = fx["name"], 2
        while f"{base} ({c})" in existing:
            c += 1
        fx["name"] = f"{base} ({c})"
        self._fixtures.append(fx)
        self._save_fixtures()
        self._rebuild_list()
        self._select_fixture(len(self._fixtures) - 1)

    # ── Import ────────────────────────────────────────────────────────────────

    def _do_import(self):
        from fixture_parser import parse_file as _parse_file
        from PySide6.QtWidgets import QInputDialog

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importer des fixtures", str(Path.home()),
            "Tous les formats (*.mft *.json *.xml *.mystrow);;"
            "Fixture MyStrow (*.mft *.json *.mystrow);;"
            "GrandMA2/3 XML (*.xml)"
        )
        if not paths:
            return

        _GROUP = {
            "Machine a fumee": "fumee",
        }
        existing = {f["name"] for f in self._fixtures}
        imported, errors = 0, []

        for path in paths:
            ext = Path(path).suffix.lower()
            try:
                if ext == ".xml":
                    ofl_fx = _parse_file(path)
                    modes = [m for m in (ofl_fx.get("modes") or []) if m.get("profile")]
                    if not modes:
                        raise ValueError("Aucun canal DMX trouvé.")
                    ftype = ofl_fx.get("fixture_type", "PAR LED")
                    candidates = [{
                        "name": ofl_fx.get("name", Path(path).stem)
                                + (f" — {m['name']}" if len(modes) > 1 else ""),
                        "manufacturer": ofl_fx.get("manufacturer", "Générique"),
                        "fixture_type": ftype,
                        "group": _GROUP.get(ftype, "face"),
                        "profile": m["profile"],
                        "color_wheel_slots": ofl_fx.get("color_wheel_slots", []),
                        "gobo_wheel_slots":  ofl_fx.get("gobo_wheel_slots", []),
                        "channel_defaults":  ofl_fx.get("channel_defaults", {}),
                        "source": "user",
                    } for m in modes]
                    if len(candidates) > 1:
                        names = [c["name"] for c in candidates]
                        choice, ok = QInputDialog.getItem(
                            self, "Mode à importer", "Choisir :", names, 0, False)
                        if not ok:
                            continue
                        to_add = [candidates[names.index(choice)]]
                    else:
                        to_add = candidates
                else:
                    raw = Path(path).read_bytes()
                    parsed = json.loads(raw.decode("utf-8"))
                    to_add = [parsed] if isinstance(parsed, dict) else parsed
                    to_add = [f for f in to_add if isinstance(f, dict)]

                for fx in to_add:
                    if not fx.get("profile") and fx.get("modes"):
                        fx["profile"] = fx["modes"][0].get("profile", [])
                    if not fx.get("name") or not fx.get("profile"):
                        continue
                    fx.pop("builtin", None)
                    fx["source"] = "user"
                    name = fx["name"]
                    if name in existing:
                        c = 2
                        while f"{name} ({c})" in existing:
                            c += 1
                        fx["name"] = f"{name} ({c})"
                    self._fixtures.append(fx)
                    existing.add(fx["name"])
                    imported += 1
            except Exception as e:
                errors.append(f"• {Path(path).name} : {e}")

        if imported == 0:
            msg = "Aucune fixture importée."
            if errors:
                msg += "\n\n" + "\n".join(errors)
            QMessageBox.warning(self, "Import échoué", msg)
            return

        self._save_fixtures()
        self._rebuild_list()
        self._select_fixture(len(self._fixtures) - 1)
        msg = f"{imported} fixture{'s' if imported > 1 else ''} importée{'s' if imported > 1 else ''}."
        if errors:
            msg += f"\n\n{len(errors)} ignoré(s) :\n" + "\n".join(errors)
            QMessageBox.warning(self, "Import partiel", msg)
        else:
            QMessageBox.information(self, "Import réussi", msg)
