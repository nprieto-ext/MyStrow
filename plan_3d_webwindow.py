"""
Plan de feu 3D — rendu Three.js via QWebEngineView.
Remplace Plan3DWindow avec une API identique : init_scene(), refresh().
"""
import base64
import json
import time as _time
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QLabel, QSlider, QPushButton,
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QWidget,
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QLineEdit,
    QDoubleSpinBox, QFrame, QGridLayout, QSizePolicy, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QObject, Slot, QEvent
from PySide6.QtGui import QColor, QBrush

TRUSS_Y   = 7.0
_HTML     = Path(getattr(__import__('sys'), '_MEIPASS', Path(__file__).parent)) / 'plan_3d_web.html'

_SCENE_PRESETS = {
    'live': {
        'label': 'Live',
        'trusses': [
            {'label': 'Truss avant',   'enabled': True, 'height': 7.0, 'z': -3.8, 'x_l': -9.0, 'x_r': 9.0},
            {'label': 'Truss arrière', 'enabled': True, 'height': 7.0, 'z':  4.0, 'x_l': -9.0, 'x_r': 9.0},
        ],
    },
    'dj': {
        'label': 'DJ',
        'trusses': [
            {'label': 'Truss avant', 'enabled': True, 'height': 6.0, 'z': -3.5, 'x_l': -7.0, 'x_r': 7.0},
            {'label': 'Overhead',    'enabled': True, 'height': 5.0, 'z':  0.0, 'x_l': -4.0, 'x_r': 4.0},
        ],
    },
    'concert': {
        'label': 'Concert',
        'trusses': [
            {'label': 'Truss avant',   'enabled': True, 'height': 8.0, 'z': -4.5, 'x_l': -10.0, 'x_r': 10.0},
            {'label': 'Truss milieu',  'enabled': True, 'height': 7.5, 'z':  0.0, 'x_l':  -9.0, 'x_r':  9.0},
            {'label': 'Truss arrière', 'enabled': True, 'height': 7.0, 'z':  5.0, 'x_l':  -9.0, 'x_r':  9.0},
        ],
    },
    'club': {
        'label': 'Club',
        'trusses': [
            {'label': 'Rig central', 'enabled': True, 'height': 4.5, 'z':  0.0, 'x_l': -5.0, 'x_r': 5.0},
            {'label': 'Truss avant', 'enabled': True, 'height': 4.0, 'z': -3.0, 'x_l': -7.0, 'x_r': 7.0},
        ],
    },
    'festival': {
        'label': 'Festival',
        'trusses': [
            {'label': 'Face',    'enabled': True, 'height': 9.0, 'z': -4.5, 'x_l': -11.0, 'x_r': 11.0},
            {'label': 'Mid',     'enabled': True, 'height': 8.5, 'z':  0.5, 'x_l': -10.0, 'x_r': 10.0},
            {'label': 'Arrière', 'enabled': True, 'height': 8.0, 'z':  5.5, 'x_l': -10.0, 'x_r': 10.0},
            {'label': 'Overhead','enabled': True, 'height': 9.5, 'z': -1.0, 'x_l':  -3.5, 'x_r':  3.5},
        ],
    },
    'arena': {
        'label': 'Grande scène',
        'trusses': [
            {'label': 'Avant',   'enabled': True, 'height': 10.0, 'z': -5.0, 'x_l': -11.0, 'x_r': 11.0},
            {'label': 'Milieu',  'enabled': True, 'height':  9.5, 'z':  0.5, 'x_l': -10.0, 'x_r': 10.0},
            {'label': 'Arrière', 'enabled': True, 'height':  9.0, 'z':  6.0, 'x_l': -10.0, 'x_r': 10.0},
        ],
    },
    'sono': {
        'label': 'Sono Mobile',
        'trusses': [
            {'label': 'Truss face',    'enabled': True, 'height': 3.4, 'z': -0.5, 'x_l': -2.5, 'x_r': 2.5},
            {'label': 'Truss arrière', 'enabled': True, 'height': 3.4, 'z': -3.5, 'x_l': -2.5, 'x_r': 2.5},
        ],
    },
    'totem': {
        'label': 'Totems',
        'trusses': [
            {'label': 'Rig central', 'enabled': True, 'height': 5.5, 'z': -1.0, 'x_l': -2.5, 'x_r': 2.5},
        ],
    },
}

_DARK  = "background:#0c0c20; color:#7777aa;"
_STYLE_DLG = """
    QDialog, QWidget { background:#0c0c1e; color:#aaaacc;
                       font-family:'Segoe UI',sans-serif; }
    QLabel  { background:transparent; border:none; }
    QLineEdit {
        background:#12122a; color:#ccccff; border:1px solid #222244;
        border-radius:3px; padding:2px 6px; font-size:11px;
    }
    QCheckBox { spacing:6px; }
    QCheckBox::indicator { width:14px; height:14px; border-radius:3px;
        border:1px solid #333366; background:#12122a; }
    QCheckBox::indicator:checked { background:#003d66; border-color:#00d4ff; }
    QScrollArea { border:none; background:transparent; }
    QScrollBar:vertical { background:#0c0c20; width:5px; border:none; }
    QScrollBar::handle:vertical { background:#222244; border-radius:2px; }
"""
_STYLE_SPIN = (
    "QDoubleSpinBox { background:#12122a; color:#ccccff; border:1px solid #222244;"
    " border-radius:3px; padding:1px 4px; font-size:10px; }"
    "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button"
    " { background:#1a1a38; width:14px; border:none; }"
)
_STYLE_ROW_BTN = (
    "QPushButton { background:#12122a; color:#7777aa; border:1px solid #1c1c40;"
    " border-radius:3px; font-size:10px; padding:2px 8px; }"
    "QPushButton:hover { background:#1a1a38; color:#ccccff; }"
    "QPushButton:pressed { background:#222255; }"
)


class _WheelSpinBox(QDoubleSpinBox):
    """SpinBox avec molette + glisser horizontal (scrub) sur le champ texte."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scrub   = False
        self._scrub_x = 0
        self._scrub_v = 0.0
        le = self.lineEdit()
        le.setCursor(Qt.SizeHorCursor)
        le.installEventFilter(self)   # intercepte les events avant la QLineEdit

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.setValue(self.value() + (self.singleStep() if delta > 0 else -self.singleStep()))
        event.accept()

    def eventFilter(self, obj, event):
        if obj is not self.lineEdit():
            return super().eventFilter(obj, event)
        t = event.type()
        if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._scrub   = True
            self._scrub_x = event.globalPos().x()
            self._scrub_v = self.value()
            obj.grabMouse()   # redirige tous les move/release vers la lineEdit
            return True
        if t == QEvent.MouseMove and self._scrub:
            dx    = event.globalPos().x() - self._scrub_x
            new_v = self._scrub_v + dx * self.singleStep() / 3.0
            self.setValue(max(self.minimum(), min(self.maximum(), new_v)))
            return True
        if t == QEvent.MouseButtonRelease and self._scrub and event.button() == Qt.LeftButton:
            self._scrub = False
            obj.releaseMouse()
            return True
        return False


class _TrussRow(QFrame):
    """Ligne d'un truss dans l'éditeur."""
    changed = Signal()

    _LABEL_W = 100

    def __init__(self, truss: dict, parent=None):
        super().__init__(parent)
        self._t = truss
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background:#0e0e26; border:1px solid #1a1a38; border-radius:5px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # ── Ligne 1 : nom + enable ────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)

        self._chk = QCheckBox()
        self._chk.setChecked(truss.get('enabled', True))
        self._chk.setToolTip("Activer / masquer ce truss")
        top.addWidget(self._chk)

        self._name = QLineEdit(truss.get('label', 'Truss'))
        self._name.setFixedWidth(130)
        self._name.setToolTip("Nom du truss")
        top.addWidget(self._name)
        top.addStretch()
        root.addLayout(top)

        # ── Ligne 2-4 : sliders H / Z / Largeur ──────────────────────────
        def _row(label, lo, hi, val, step=0.5, tip=""):
            rw = QHBoxLayout()
            rw.setSpacing(6)
            lbl = QLabel(label)
            lbl.setFixedWidth(self._LABEL_W)
            lbl.setStyleSheet("color:#444466; font-size:9px;")
            sp = _WheelSpinBox()
            sp.setRange(lo, hi); sp.setSingleStep(step)
            sp.setDecimals(1); sp.setValue(val)
            sp.setFixedWidth(70); sp.setStyleSheet(_STYLE_SPIN)
            sp.setToolTip(tip)
            rw.addWidget(lbl); rw.addWidget(sp); rw.addStretch()
            return rw, sp

        r1, self._h  = _row("Hauteur (m)",  1.0, 15.0, truss.get('height', TRUSS_Y),
                             tip="Hauteur du truss au-dessus de la scène")
        r2, self._z  = _row("Position Z",  -8.0, 10.0, truss.get('z', 0.0),
                             tip="Avant (−) / Arrière (+) de la scène")
        r3, self._xl = _row("Bord gauche", -15.0, 0.0,  truss.get('x_l', -9.0),
                             tip="Position X gauche du truss")
        r4, self._xr = _row("Bord droit",   0.0, 15.0,  truss.get('x_r',  9.0),
                             tip="Position X droite du truss")
        for r in (r1, r2, r3, r4):
            root.addLayout(r)

        # Connexions
        for w in (self._chk, self._name, self._h, self._z, self._xl, self._xr):
            if hasattr(w, 'stateChanged'):
                w.stateChanged.connect(self._emit)
            elif hasattr(w, 'textChanged'):
                w.textChanged.connect(self._emit)
            elif hasattr(w, 'valueChanged'):
                w.valueChanged.connect(self._emit)

    def _emit(self, *_):
        self._t['enabled'] = self._chk.isChecked()
        self._t['label']   = self._name.text()
        self._t['height']  = self._h.value()
        self._t['z']       = self._z.value()
        self._t['x_l']     = self._xl.value()
        self._t['x_r']     = self._xr.value()
        self.changed.emit()

    def data(self) -> dict:
        return self._t.copy()


class TrussEditorDialog(QDialog):
    """Éditeur de trusses 3D — ajout, suppression, réglages live."""

    trusses_changed = Signal(list)

    _BTN = (
        "QPushButton { background:#1a1a36; color:#7777aa; border:1px solid #282850;"
        " border-radius:4px; font-size:10px; padding:4px 14px; }"
        "QPushButton:hover { background:#252550; color:#ccccff; }"
        "QPushButton:pressed { background:#003d66; color:#00d4ff; }"
    )

    def __init__(self, trusses: list, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Éditeur de Trusses")
        self.resize(340, 560)
        self.setStyleSheet(_STYLE_DLG)
        self._trusses = [t.copy() for t in trusses]
        self._rows: list[_TrussRow] = []
        self._build_ui()
        self._rebuild_rows()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # Titre
        title = QLabel("Trusses 3D")
        title.setStyleSheet("color:#00d4ff; font-size:13px; font-weight:bold;")
        root.addWidget(title)

        sub = QLabel("Les modifications sont appliquées en temps réel.")
        sub.setStyleSheet("color:#333355; font-size:9px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # Zone scrollable
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._container = QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setSpacing(6)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.addStretch()
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        # Boutons bas
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border:none; border-top:1px solid #1a1a38;")
        root.addWidget(sep)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        btn_add = QPushButton("+ Ajouter un truss")
        btn_add.setStyleSheet(self._BTN)
        btn_add.clicked.connect(self._add_truss)
        btns.addWidget(btn_add)

        btn_del = QPushButton("− Supprimer le dernier")
        btn_del.setStyleSheet(self._BTN)
        btn_del.clicked.connect(self._remove_last)
        btns.addWidget(btn_del)
        root.addLayout(btns)

    def _rebuild_rows(self):
        # Vider les anciennes lignes
        for row in self._rows:
            self._vbox.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        for t in self._trusses:
            row = _TrussRow(t, self._container)
            row.changed.connect(self._on_change)
            # Insérer avant le stretch
            self._vbox.insertWidget(self._vbox.count() - 1, row)
            self._rows.append(row)

    def _on_change(self):
        self._trusses = [r.data() for r in self._rows]
        self.trusses_changed.emit(self._trusses)

    def _add_truss(self):
        n = len(self._trusses) + 1
        self._trusses.append({
            'label':   f'Truss {n}',
            'enabled': True,
            'height':  TRUSS_Y,
            'z':       float((n - 1) * 2 - 4),
            'x_l':    -9.0,
            'x_r':     9.0,
        })
        self._rebuild_rows()
        self.trusses_changed.emit(self._trusses)

    def _remove_last(self):
        if len(self._trusses) <= 1:
            return
        self._trusses.pop()
        self._rebuild_rows()
        self.trusses_changed.emit(self._trusses)

    def current_trusses(self) -> list:
        return [t.copy() for t in self._trusses]


class ProjectorTableDialog(QDialog):
    """Tableau de positionnement 3D — édition X/Y/Z/RotXYZ, multi-sélection."""

    _HDR  = ['', 'Projecteur', 'X (m)', 'Y haut.', 'Z (m)', 'Rot Y°', 'Rot X°', 'Rot Z°']
    _ATTR = [None, None, 'pos_3d_x', 'fixture_height', 'pos_3d_z',
             'body_rotation', 'rot3d_x', 'rot3d_z']
    _LO   = [None, None, -12.0,  1.0, -8.0, -180.0, -90.0, -180.0]
    _HI   = [None, None,  12.0, 15.0, 10.0,  180.0,  90.0,  180.0]
    _STEP = [None, None,   0.5,  0.5,  0.5,    1.0,   1.0,   1.0]
    _DEC  = [None, None,     1,    1,    1,       0,     0,     0]
    _CW   = [22, 150, 66, 66, 66, 66, 66, 66]

    _GRP_COLOR = {
        'face': '#ff8844', 'contre': '#4488ff', 'douche1': '#44cc88',
        'douche2': '#ffcc44', 'douche3': '#ff4488', 'lat': '#aa55ff',
        'lyre': '#ee44bb', 'barre': '#44aaff',
        'groupe_g': '#22ddcc', 'groupe_h': '#ff7722',
    }
    _TBL = (
        "QTableWidget{background:#080818;color:#aaaacc;border:1px solid #1a1a38;"
        "gridline-color:#111128;font-size:10px;font-family:'Segoe UI',sans-serif;}"
        "QTableWidget::item{padding:0;border:none;}"
        "QHeaderView::section{background:#0c0c22;color:#333355;border:none;"
        "border-right:1px solid #111128;border-bottom:1px solid #1a1a38;"
        "padding:4px 4px;font-size:8px;letter-spacing:1px;font-weight:700;}"
        "QScrollBar:vertical{background:#080818;width:6px;border:none;}"
        "QScrollBar::handle:vertical{background:#1a1a38;border-radius:3px;}"
    )
    _SP = (
        "QDoubleSpinBox{background:#0c0c20;color:#ccccff;border:none;"
        "padding:2px 1px;font-size:10px;font-family:'Segoe UI',sans-serif;}"
        "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button"
        "{background:#151530;border:none;width:12px;}"
    )
    _SP_ON = (
        "QDoubleSpinBox{background:#002244;color:#00d4ff;border:none;"
        "padding:2px 1px;font-size:10px;font-family:'Segoe UI',sans-serif;}"
        "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button"
        "{background:#003366;border:none;width:12px;}"
    )
    _BTN = (
        "QPushButton{background:#1a1a36;color:#7777aa;border:1px solid #282850;"
        "border-radius:4px;font-size:10px;padding:4px 12px;}"
        "QPushButton:hover{background:#252550;color:#ccccff;}"
        "QPushButton:pressed{background:#003d66;color:#00d4ff;}"
    )

    def __init__(self, get_projectors, norm_pos_cb, refresh_cb, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Positionnement 3D")
        self.resize(700, 480)
        self.setStyleSheet(_STYLE_DLG)
        self._get  = get_projectors   # () → list[Projector]
        self._npos = norm_pos_cb      # (projectors, i) → (cx, cy)
        self._cb   = refresh_cb       # (projectors) → None
        self._busy = False
        self._build_ui()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hdr = QLabel("Positionnement des projecteurs")
        hdr.setStyleSheet("color:#00d4ff;font-size:13px;font-weight:bold;")
        root.addWidget(hdr)

        sub = QLabel(
            "Cochez plusieurs lignes pour les modifier ensemble.  "
            "X/Z = position sur scène  ·  Y = hauteur de suspension  ·  "
            "Rot Y = pivot horizontal (pan)  ·  Rot X = inclinaison (tilt)  ·  Rot Z = roulis"
        )
        sub.setStyleSheet("color:#333355;font-size:9px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self._tbl = QTableWidget(0, len(self._HDR))
        self._tbl.setHorizontalHeaderLabels(self._HDR)
        self._tbl.setStyleSheet(self._TBL)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setShowGrid(True)
        for i, w in enumerate(self._CW):
            self._tbl.setColumnWidth(i, w)
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.itemChanged.connect(self._on_chk_changed)
        root.addWidget(self._tbl, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border:none;border-top:1px solid #1a1a38;")
        root.addWidget(sep)

        bot = QHBoxLayout()
        bot.setSpacing(6)
        for label, slot in [
            ("Tout cocher",       lambda: self._set_all(True)),
            ("Tout décocher",     lambda: self._set_all(False)),
            ("Réinit. sélection", self._reset_sel),
        ]:
            b = QPushButton(label)
            b.setStyleSheet(self._BTN)
            b.clicked.connect(slot)
            bot.addWidget(b)
        bot.addStretch()
        root.addLayout(bot)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _checked(self):
        return [r for r in range(self._tbl.rowCount())
                if (it := self._tbl.item(r, 0)) and it.checkState() == Qt.Checked]

    def _refresh_row_style(self, row):
        it  = self._tbl.item(row, 0)
        sel = it and it.checkState() == Qt.Checked
        s   = self._SP_ON if sel else self._SP
        for c in range(2, len(self._HDR)):
            w = self._tbl.cellWidget(row, c)
            if w:
                w.setStyleSheet(s)

    def _set_all(self, state):
        self._busy = True
        for r in range(self._tbl.rowCount()):
            it = self._tbl.item(r, 0)
            if it:
                it.setCheckState(Qt.Checked if state else Qt.Unchecked)
                self._refresh_row_style(r)
        self._busy = False

    def _on_chk_changed(self, item):
        if item.column() == 0 and not self._busy:
            self._refresh_row_style(item.row())

    # ── Populate ──────────────────────────────────────────────────────────────

    def populate(self, projectors):
        self._busy = True
        self._tbl.setRowCount(len(projectors))

        for row, p in enumerate(projectors):
            # Initialise pos_3d depuis canvas si absent
            if getattr(p, 'pos_3d_x', None) is None:
                cx, cy = self._npos(projectors, row)
                p.pos_3d_x = round((cx - 0.5) * 18.0, 2)
                p.pos_3d_z = round(-(cy - 0.5) * 10.0, 2)

            # Col 0 — checkbox
            if not self._tbl.item(row, 0):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Unchecked)
                self._tbl.setItem(row, 0, chk)

            # Col 1 — nom coloré selon le groupe
            if not self._tbl.item(row, 1):
                grp  = getattr(p, 'group', '')
                name = getattr(p, 'name', '') or grp or f'#{row + 1}'
                nm   = QTableWidgetItem(name)
                nm.setFlags(Qt.ItemIsEnabled)
                nm.setForeground(QBrush(QColor(self._GRP_COLOR.get(grp, '#666688'))))
                self._tbl.setItem(row, 1, nm)

            # Cols 2-7 — spinboxes
            vals = [
                getattr(p, 'pos_3d_x',      0.0),
                getattr(p, 'fixture_height', 7.0),
                getattr(p, 'pos_3d_z',       0.0),
                getattr(p, 'body_rotation',  0.0),
                getattr(p, 'rot3d_x',        0.0),
                getattr(p, 'rot3d_z',        0.0),
            ]
            for ci, (val, lo, hi, step, dec) in enumerate(
                    zip(vals, self._LO[2:], self._HI[2:], self._STEP[2:], self._DEC[2:])):
                col = ci + 2
                sp  = self._tbl.cellWidget(row, col)
                if sp is None:
                    sp = _WheelSpinBox()
                    sp.setRange(lo, hi)
                    sp.setSingleStep(step)
                    sp.setDecimals(dec)
                    sp.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
                    sp.setStyleSheet(self._SP)
                    sp.setFrame(False)
                    sp.valueChanged.connect(lambda v, r=row, c=col: self._on_spin(r, c, v))
                    self._tbl.setCellWidget(row, col, sp)
                sp.blockSignals(True)
                sp.setValue(float(val) if val is not None else 0.0)
                sp.blockSignals(False)

            self._tbl.setRowHeight(row, 26)

        self._busy = False

    # ── Edition ───────────────────────────────────────────────────────────────

    def _on_spin(self, row, col, value):
        if self._busy:
            return
        projs = self._get()
        attr  = self._ATTR[col]
        rows  = self._checked()
        if row not in rows:
            rows = [row]

        self._busy = True
        for r in rows:
            if r < len(projs):
                setattr(projs[r], attr, value)
                if r != row:
                    sp = self._tbl.cellWidget(r, col)
                    if sp:
                        sp.blockSignals(True)
                        sp.setValue(value)
                        sp.blockSignals(False)
        self._busy = False
        self._cb(projs)

    def _reset_sel(self):
        projs = self._get()
        rows  = self._checked() or list(range(len(projs)))
        for r in rows:
            if r < len(projs):
                p = projs[r]
                p.pos_3d_x      = None
                p.pos_3d_z      = None
                p.body_rotation = 0.0
                p.rot3d_x       = 0.0
                p.rot3d_z       = 0.0
        self.populate(projs)
        self._cb(projs)


class _Bridge(QObject):
    """Pont QWebChannel — reçoit les clics sur les fixtures depuis Three.js."""

    def __init__(self, win):
        super().__init__()
        self._win = win

    @Slot(int)
    def projoSelected(self, index: int):
        self._win._on_projo_selected(index)


class Plan3DWebWindow(QMainWindow):
    """Fenêtre 3D (Three.js) avec bloom, faisceaux volumétriques."""

    _TB_BTN = (
        "QPushButton { background:#1a1a36; color:#7777aa; border:1px solid #282850;"
        " border-radius:4px; font-size:10px; padding:3px 10px; min-width:44px; }"
        "QPushButton:hover { background:#252550; color:#ccccff; }"
        "QPushButton:checked { background:#003d66; color:#00d4ff; border-color:#005588; }"
    )
    _JOG_BTN = (
        "QPushButton{background:#0e0e28;color:#6666aa;border:1px solid #1a1a38;"
        "border-radius:4px;font-size:14px;padding:3px;}"
        "QPushButton:hover{background:#1a1a38;color:#ccccff;}"
        "QPushButton:pressed{background:#003d66;color:#00d4ff;}"
    )
    _JOG_STEP_BTN = (
        "QPushButton{background:#0c0c22;color:#444466;border:1px solid #1a1a38;"
        "border-radius:3px;font-size:8px;padding:2px 4px;}"
        "QPushButton:hover{background:#1a1a38;color:#aaaacc;}"
        "QPushButton:checked{background:#003d66;color:#00d4ff;border-color:#005588;}"
    )

    def __init__(self, parent=None):
        super().__init__(None, Qt.Window)   # pas de parent Qt → évite le bleeding visuel sur Windows
        self._parent_mw = parent
        self.setWindowTitle("Plan de feu 3D")
        self.resize(1150, 700)
        self.setStyleSheet("background:#05050f;")

        self._view = QWebEngineView()
        s = self._view.settings()
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)

        # QWebChannel — communication JS → Python (clic sur fixture)
        self._channel = QWebChannel()
        self._bridge  = _Bridge(self)
        self._channel.registerObject('bridge', self._bridge)
        self._view.page().setWebChannel(self._channel)

        # Connecter loadFinished AVANT load() pour ne pas manquer le signal
        # (la page locale peut charger avant que la ligne suivante soit atteinte)
        self._view.loadFinished.connect(self._on_load_finished)
        self._view.page().renderProcessTerminated.connect(self._on_render_crashed)
        self._view.load(QUrl.fromLocalFile(str(_HTML)))
        self._view.installEventFilter(self)

        # Layout : QSplitter (vue 3D | panneau onglets redimensionnable)
        self._right_panel = self._build_right_panel()
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setStyleSheet(
            "QSplitter::handle{background:#0e0e28;width:4px;}"
            "QSplitter::handle:hover{background:#003d66;}"
        )
        self._splitter.addWidget(self._view)
        self._splitter.addWidget(self._right_panel)
        self._splitter.setSizes([850, 240])
        self._splitter.setChildrenCollapsible(False)
        self._right_panel_sizes = [850, 240]
        self.setCentralWidget(self._splitter)

        self._projectors      = []
        self._last_projectors = []
        self._pending         = None
        self._ready           = False
        self._placement_dlg   = None
        self._truss_editor    = None
        self._highlighted_row = -1
        self._selected_rows: set = set()
        self._undo_stack: list = []
        self._trusses     = [
            {'label': 'Truss avant',   'enabled': True, 'height': TRUSS_Y, 'z': -3.8, 'x_l': -9.0, 'x_r': 9.0},
            {'label': 'Truss arrière', 'enabled': True, 'height': TRUSS_Y, 'z':  4.0, 'x_l': -9.0, 'x_r': 9.0},
        ]
        self._scene_preset_code = 'live'

        # Charger la scène sauvegardée depuis le patch, avant que la page HTML charge
        try:
            _cfg_path = Path.home() / '.maestro_dmx_patch.json'
            if _cfg_path.exists():
                _cfg = json.loads(_cfg_path.read_text(encoding='utf-8'))
                _s3d = _cfg.get('scene_3d', {})
                if _s3d.get('preset') in _SCENE_PRESETS:
                    self._scene_preset_code = _s3d['preset']
                if _s3d.get('trusses'):
                    self._trusses = _s3d['trusses']
        except Exception:
            pass

        # Debounce : on coalesce les refresh rapides (MIDI) → max 25 fps
        self._push_timer = QTimer(self)
        self._push_timer.setSingleShot(True)
        self._push_timer.setInterval(40)
        self._push_timer.timeout.connect(self._do_push)
        self._strobe_timer = QTimer(self)
        self._strobe_timer.setInterval(40)
        self._strobe_timer.timeout.connect(self._do_strobe_push)

        self._build_toolbar()

    # ── Toolbar ──────────────────────────────────────────────────────────────

    def _svg_icon(self, inner):
        """Rend un fragment SVG (viewBox 0 0 24 24) en QIcon net (pixmap 48px)."""
        from PySide6.QtGui import QIcon, QPixmap, QPainter
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QByteArray, QRectF
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{inner}</svg>'
        pix = QPixmap(48, 48)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p, QRectF(0, 0, 48, 48))
        p.end()
        return QIcon(pix)

    def _build_toolbar(self):
        tb = QToolBar(self)
        tb.setMovable(False)
        tb.setStyleSheet(
            "QToolBar { background:#0c0c20; border-bottom:1px solid #1a1a38;"
            " spacing:4px; padding:3px 8px; }"
        )
        self.addToolBar(tb)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        _PDF_BTN = (
            "QPushButton { background:#1e1e1e; color:#aaa; border:1px solid #3a3a3a;"
            " border-radius:4px; font-size:11px; font-weight:bold; padding:2px 8px; }"
            "QPushButton:hover { background:#2a2a2a; color:#fff; border-color:#0077bb; }"
            "QPushButton:pressed { background:#333; }"
            "QPushButton:checked { background:#0d2030; color:#00d4ff; border-color:#0077bb; }"
        )

        from PySide6.QtCore import QSize
        _col = "#d0d0d0"
        # Épingle (façon Material push_pin)
        _pin_svg = (
            f'<path fill="{_col}" d="M16 9V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1'
            f's.45 1 1 1h1v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z"/>'
        )
        # Panneau latéral droit
        _panel_svg = (
            f'<rect x="3" y="4.5" width="18" height="15" rx="2.2" fill="none" stroke="{_col}" stroke-width="1.8"/>'
            f'<rect x="14.3" y="4.5" width="6.7" height="15" rx="2.2" fill="{_col}" opacity="0.7"/>'
            f'<line x1="14.3" y1="4.5" x2="14.3" y2="19.5" stroke="{_col}" stroke-width="1.8"/>'
        )

        btn_pin = QPushButton()
        btn_pin.setIcon(self._svg_icon(_pin_svg))
        btn_pin.setIconSize(QSize(17, 17))
        btn_pin.setCheckable(True)
        btn_pin.setChecked(False)
        btn_pin.setToolTip("Garder la fenêtre au premier plan")
        btn_pin.setFixedSize(28, 28)
        btn_pin.setStyleSheet(_PDF_BTN)
        btn_pin.clicked.connect(lambda checked: self._set_always_on_top(checked))
        tb.addWidget(btn_pin)
        self._btn_pin = btn_pin

        tb.addSeparator()

        self._btn_toggle_panel = QPushButton()
        self._btn_toggle_panel.setIcon(self._svg_icon(_panel_svg))
        self._btn_toggle_panel.setIconSize(QSize(18, 18))
        self._btn_toggle_panel.setCheckable(True)
        self._btn_toggle_panel.setChecked(False)
        self._btn_toggle_panel.setToolTip("Masquer / afficher le panneau de droite")
        self._btn_toggle_panel.setFixedSize(28, 28)
        self._btn_toggle_panel.setStyleSheet(_PDF_BTN)
        self._btn_toggle_panel.clicked.connect(self._toggle_right_panel)
        tb.addWidget(self._btn_toggle_panel)



    def _set_always_on_top(self, enabled: bool):
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def _toggle_right_panel(self):
        visible = self._right_panel.isVisible()
        if visible:
            self._right_panel_sizes = self._splitter.sizes()
            self._right_panel.setVisible(False)
            self._btn_toggle_panel.setChecked(True)
        else:
            self._right_panel.setVisible(True)
            self._splitter.setSizes(self._right_panel_sizes)
            self._btn_toggle_panel.setChecked(False)

    # ── Panneau latéral droit (onglets) ─────────────────────────────────────

    _PANEL_W = 248

    _TAB_STYLE = (
        "QTabWidget::pane{border:none;background:#080818;}"
        "QTabBar{background:#060616;}"
        "QTabBar::tab{background:#060616;color:#2a2a4a;border:none;"
        "padding:6px 10px;font-size:9px;letter-spacing:0.8px;font-weight:700;"
        "border-right:1px solid #0e0e28;}"
        "QTabBar::tab:selected{background:#080818;color:#00d4ff;"
        "border-bottom:2px solid #00d4ff;}"
        "QTabBar::tab:hover{color:#7777aa;}"
    )
    _PANEL_BTN = (
        "QPushButton{background:#0e0e28;color:#555577;border:1px solid #1a1a38;"
        "border-radius:4px;font-size:10px;letter-spacing:0.5px;padding:5px 0;"
        "font-family:'Segoe UI',sans-serif;}"
        "QPushButton:hover{background:#1a1a38;color:#aaaacc;border-color:#333366;}"
        "QPushButton:checked{background:rgba(0,55,100,0.85);color:#00d4ff;"
        "border-color:#005588;}"
    )

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(160)
        w.setStyleSheet("background:#080818;border-left:1px solid #0e0e28;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        tabs = QTabWidget()
        tabs.setStyleSheet(self._TAB_STYLE)
        tabs.addTab(self._build_cam_tab(),       "Cam.")
        tabs.addTab(self._build_placement_tab(), "Plan")
        tabs.addTab(self._build_scene_tab(),     "Scène")
        lay.addWidget(tabs)
        self._right_tabs = tabs
        return w

    # ── Onglet Caméra ─────────────────────────────────────────────────────────

    def _build_cam_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#080818;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(4)

        self._cam_btns_py = {}
        for code, label in [('iso','ISO'), ('front','FACE'), ('top','DESSUS'), ('side','CÔTÉ')]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(code == 'iso')
            btn.setStyleSheet(self._PANEL_BTN)
            btn.clicked.connect(lambda _, c=code: self._set_cam_py(c))
            lay.addWidget(btn)
            self._cam_btns_py[code] = btn

        lay.addSpacing(10)

        # ── Ambiance ──────────────────────────────────────────────────────
        lbl_amb = QLabel("Ambiance salle")
        lbl_amb.setStyleSheet("color:#4444aa;font-size:9px;letter-spacing:0.5px;")
        lay.addWidget(lbl_amb)

        self._amb_val_lbl = QLabel("100%")
        self._amb_val_lbl.setStyleSheet("color:#7777cc;font-size:9px;")
        self._amb_val_lbl.setAlignment(Qt.AlignRight)
        lay.addWidget(self._amb_val_lbl)

        sl_amb = QSlider(Qt.Horizontal)
        sl_amb.setRange(0, 1000)
        sl_amb.setValue(200)
        sl_amb.setToolTip("Lumière ambiante — glissez à droite pour éclairer davantage la salle")
        sl_amb.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#0e0e28;border-radius:2px;}"
            "QSlider::sub-page:horizontal{background:#3344aa;border-radius:2px;}"
            "QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;"
            "background:#5566cc;border-radius:6px;}"
            "QSlider::handle:horizontal:hover{background:#7788ff;}"
        )

        def _on_amb(v):
            self._amb_val_lbl.setText(f"{v//10}%")
            self._js(f'ambLight.intensity={v/100:.2f}')

        sl_amb.valueChanged.connect(_on_amb)
        lay.addWidget(sl_amb)
        self._sl_amb = sl_amb

        lay.addStretch()

        hint = QLabel("drag · scroll · double-clic reset")
        hint.setStyleSheet(
            "color:#1a1a32;font-size:8px;font-family:'Segoe UI',sans-serif;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _set_cam_py(self, code: str):
        for k, b in self._cam_btns_py.items():
            b.setChecked(k == code)
        self._js(f"window.setCam('{code}')")

    # ── Onglet Placement (mini-table) ─────────────────────────────────────────

    _MINI_TBL = (
        "QTableWidget{background:#060616;color:#aaaacc;border:none;"
        "gridline-color:#0e0e28;font-size:9px;font-family:'Segoe UI',sans-serif;}"
        "QTableWidget::item{padding:0;border:none;}"
        "QHeaderView::section{background:#080820;color:#2a2a4a;border:none;"
        "border-right:1px solid #0e0e28;border-bottom:1px solid #0e0e28;"
        "padding:3px 2px;font-size:7px;letter-spacing:0.8px;font-weight:700;}"
        "QScrollBar:vertical{background:#060616;width:5px;border:none;}"
        "QScrollBar::handle:vertical{background:#1a1a38;border-radius:2px;}"
    )
    _MINI_SP = (
        "QDoubleSpinBox{background:#060616;color:#ccccff;border:none;"
        "padding:1px 0;font-size:9px;}"
        "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button"
        "{background:#0e0e28;border:none;width:10px;}"
    )
    _MINI_SP_ON = (
        "QDoubleSpinBox{background:#002244;color:#00d4ff;border:none;"
        "padding:1px 0;font-size:9px;}"
        "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button"
        "{background:#003366;border:none;width:10px;}"
    )

    def _build_placement_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#080818;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Mini-table : checkbox + nom + X / Z / Haut
        self._mini_tbl = QTableWidget(0, 4)
        self._mini_tbl.setHorizontalHeaderLabels(['Projecteur', 'X', 'Z', 'H'])
        self._mini_tbl.setStyleSheet(self._MINI_TBL)
        self._mini_tbl.verticalHeader().setVisible(False)
        self._mini_tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self._mini_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        cw = [80, 34, 34, 34]
        for i, w_ in enumerate(cw):
            self._mini_tbl.setColumnWidth(i, w_)
        self._mini_tbl.horizontalHeader().setStretchLastSection(True)
        self._mini_tbl.cellClicked.connect(self._on_mini_tbl_clicked)
        lay.addWidget(self._mini_tbl, 1)

        # Jog pad
        self._jog_pad = self._build_jog_pad()
        lay.addWidget(self._jog_pad)

        return w

    def _mini_reset(self):
        projs = self._last_projectors
        rows  = list(self._selected_rows) or list(range(len(projs)))
        for r in rows:
            if r < len(projs):
                p = projs[r]
                p.pos_3d_x = None; p.pos_3d_z = None
                p.body_rotation = 0.0
                p.rot3d_x = 0.0;  p.rot3d_z = 0.0
        self._populate_mini(projs)
        self.refresh(projs)
        self._save_patch()

    def _mini_spin_changed(self, row, col, value):
        projs = self._last_projectors
        if not projs:
            return
        attr_map = {
            1: 'pos_3d_x',
            2: 'pos_3d_z',
            3: 'fixture_height',
        }
        attr = attr_map.get(col)
        if attr is None:
            return
        rows = list(self._selected_rows) if row in self._selected_rows else [row]
        for r in rows:
            if r < len(projs):
                p = projs[r]
                if attr in ('pos_3d_x', 'pos_3d_z') and getattr(p, 'pos_3d_x', None) is None:
                    cx, cy = self._norm_pos(projs, r)
                    p.pos_3d_x = round((cx - 0.5) * 18.0, 2)
                    p.pos_3d_z = round(-(cy - 0.5) * 10.0, 2)
                setattr(p, attr, value)
                if r != row:
                    sp = self._mini_tbl.cellWidget(r, col)
                    if sp:
                        sp.blockSignals(True)
                        sp.setValue(value)
                        sp.blockSignals(False)
        # Sync jog pad spinbox si la ligne modifiée est le primaire
        if row == self._highlighted_row and attr in self._jog_spins:
            sp_jog = self._jog_spins[attr]
            sp_jog.blockSignals(True); sp_jog.setValue(value); sp_jog.blockSignals(False)
        # Sync 2D plan pour X/Z
        if attr in ('pos_3d_x', 'pos_3d_z'):
            for r in rows:
                if r < len(projs):
                    self._sync_canvas_pos(projs[r])
        self.refresh(projs)
        self._save_patch()

    def _populate_mini(self, projectors):
        self._mini_tbl.setRowCount(len(projectors))
        for row, p in enumerate(projectors):
            if getattr(p, 'pos_3d_x', None) is None:
                cx, cy = self._norm_pos(projectors, row)
                p.pos_3d_x = round((cx - 0.5) * 18.0, 2)
                p.pos_3d_z = round(-(cy - 0.5) * 10.0, 2)

            if not self._mini_tbl.item(row, 0):
                grp  = getattr(p, 'group', '')
                name = getattr(p, 'name', '') or grp or f'#{row+1}'
                nm   = QTableWidgetItem(name[:12])
                nm.setFlags(Qt.ItemIsEnabled)
                nm.setForeground(QBrush(QColor(
                    ProjectorTableDialog._GRP_COLOR.get(grp, '#666688'))))
                self._mini_tbl.setItem(row, 0, nm)

            vals  = [
                getattr(p, 'pos_3d_x',       0.0),
                getattr(p, 'pos_3d_z',        0.0),
                getattr(p, 'fixture_height',  7.0),
            ]
            specs = [
                (-12, 12, 0.1, 1),
                (-8,  10, 0.1, 1),
                (1,   15, 0.1, 1),
            ]
            for ci, (val, (lo, hi, step, dec)) in enumerate(zip(vals, specs)):
                col = ci + 1
                sp  = self._mini_tbl.cellWidget(row, col)
                if sp is None:
                    sp = _WheelSpinBox()
                    sp.setRange(lo, hi); sp.setSingleStep(step); sp.setDecimals(dec)
                    sp.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
                    sp.setStyleSheet(self._MINI_SP); sp.setFrame(False)
                    sp.valueChanged.connect(
                        lambda v, r=row, c=col: self._mini_spin_changed(r, c, v))
                    self._mini_tbl.setCellWidget(row, col, sp)
                sp.blockSignals(True)
                sp.setValue(float(val) if val is not None else 0.0)
                sp.blockSignals(False)

            self._mini_tbl.setRowHeight(row, 22)

    # ── Jog pad ───────────────────────────────────────────────────────────────

    def _build_jog_pad(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame{background:#050514;border-top:1px solid #1a1a38;}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)

        # Nom du projecteur sélectionné
        self._jog_name = QLabel("—")
        self._jog_name.setStyleSheet(
            "color:#00d4ff;font-size:10px;font-weight:700;"
            "background:transparent;border:none;padding-bottom:1px;"
        )
        lay.addWidget(self._jog_name)

        # Sélecteur de pas
        step_row = QHBoxLayout()
        step_row.setSpacing(2)
        lbl_step = QLabel("Pas :")
        lbl_step.setStyleSheet(
            "color:#333355;font-size:8px;background:transparent;border:none;")
        step_row.addWidget(lbl_step)
        self._jog_step = 0.5
        self._jog_step_btns: dict = {}
        for s in (0.1, 0.5, 1.0, 2.0):
            b = QPushButton(f"{s}m")
            b.setCheckable(True)
            b.setChecked(s == 0.5)
            b.setStyleSheet(self._JOG_STEP_BTN)
            b.clicked.connect(lambda _, v=s: self._jog_set_step(v))
            step_row.addWidget(b)
            self._jog_step_btns[s] = b
        lay.addLayout(step_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border:none;border-top:1px solid #0e0e28;margin:1px 0;")
        lay.addWidget(sep)

        # Rangées d'axe : [label] [−] [spinbox] [+]
        _AXIS_SP = (
            "QDoubleSpinBox{background:#0c0c22;color:#ccccff;border:1px solid #1a1a38;"
            "border-radius:3px;padding:1px 2px;font-size:10px;}"
            "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button"
            "{background:#0e0e28;border:none;width:12px;}"
        )
        _AXIS_LBL = (
            "color:#444466;font-size:9px;font-weight:700;"
            "background:transparent;border:none;min-width:14px;"
        )
        self._jog_spins: dict = {}

        # (attr, label, btn_minus, btn_plus, lo, hi, dx, dz, dh)
        _AXES = [
            ('pos_3d_x',      'X', '◄', '►', -12.0, 12.0,  -1,  0,  0),
            ('pos_3d_z',      'Z', '▲', '▼',  -8.0, 10.0,   0, -1,  0),
            ('fixture_height', 'H', '−', '+',   1.0, 15.0,   0,  0, -1),
        ]
        for attr, lbl_txt, btn_m_txt, btn_p_txt, lo, hi, dx, dz, dh in _AXES:
            row_lay = QHBoxLayout()
            row_lay.setSpacing(3)

            lbl = QLabel(lbl_txt)
            lbl.setStyleSheet(_AXIS_LBL)
            lbl.setFixedWidth(14)
            row_lay.addWidget(lbl)

            btn_m = QPushButton(btn_m_txt)
            btn_m.setFixedSize(26, 24)
            btn_m.setStyleSheet(self._JOG_BTN)
            btn_m.clicked.connect(lambda _, x=dx, z=dz, h=dh: self._jog_move(x, z, h))
            row_lay.addWidget(btn_m)

            sp = _WheelSpinBox()
            sp.setRange(lo, hi)
            sp.setDecimals(2)
            sp.setSingleStep(0.1)
            sp.setStyleSheet(_AXIS_SP)
            sp.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
            sp.setFrame(False)
            sp.valueChanged.connect(lambda v, a=attr: self._jog_spin_changed(a, v))
            row_lay.addWidget(sp)
            self._jog_spins[attr] = sp

            btn_p = QPushButton(btn_p_txt)
            btn_p.setFixedSize(26, 24)
            btn_p.setStyleSheet(self._JOG_BTN)
            btn_p.clicked.connect(lambda _, x=-dx, z=-dz, h=-dh: self._jog_move(x, z, h))
            row_lay.addWidget(btn_p)

            lay.addLayout(row_lay)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("border:none;border-top:1px solid #0e0e28;margin:1px 0;")
        lay.addWidget(sep2)

        # Ligne RX — rotation du corps (retournement)
        rx_row = QHBoxLayout()
        rx_row.setSpacing(3)
        lbl_rx = QLabel("RX")
        lbl_rx.setStyleSheet(_AXIS_LBL)
        lbl_rx.setFixedWidth(14)
        rx_row.addWidget(lbl_rx)

        btn_rx_m = QPushButton("↺")
        btn_rx_m.setFixedSize(26, 24)
        btn_rx_m.setStyleSheet(self._JOG_BTN)
        btn_rx_m.clicked.connect(lambda: self._jog_rx(-1))
        rx_row.addWidget(btn_rx_m)

        sp_rx = _WheelSpinBox()
        sp_rx.setRange(-180.0, 180.0)
        sp_rx.setDecimals(1)
        sp_rx.setSingleStep(1.0)
        sp_rx.setStyleSheet(_AXIS_SP)
        sp_rx.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
        sp_rx.setFrame(False)
        sp_rx.valueChanged.connect(lambda v: self._jog_spin_changed('rot3d_x', v))
        rx_row.addWidget(sp_rx)
        self._jog_spins['rot3d_x'] = sp_rx

        btn_rx_p = QPushButton("↻")
        btn_rx_p.setFixedSize(26, 24)
        btn_rx_p.setStyleSheet(self._JOG_BTN)
        btn_rx_p.clicked.connect(lambda: self._jog_rx(1))
        rx_row.addWidget(btn_rx_p)
        lay.addLayout(rx_row)

        btn_flip = QPushButton("↕ Retourner  (0° ↔ 180°)")
        btn_flip.setStyleSheet(
            "QPushButton{background:#0e0e28;color:#6666aa;border:1px solid #1a1a38;"
            "border-radius:4px;font-size:10px;padding:4px;}"
            "QPushButton:hover{background:#1a1a38;color:#ccccff;}"
            "QPushButton:pressed{background:#003d66;color:#00d4ff;}"
        )
        btn_flip.clicked.connect(self._jog_flip)
        lay.addWidget(btn_flip)

        # Lignes RY et RZ
        for attr, lbl_txt in [('body_rotation', 'RY'), ('rot3d_z', 'RZ')]:
            r_row = QHBoxLayout()
            r_row.setSpacing(3)
            lbl_r = QLabel(lbl_txt)
            lbl_r.setStyleSheet(_AXIS_LBL)
            lbl_r.setFixedWidth(14)
            r_row.addWidget(lbl_r)

            btn_m = QPushButton("↺")
            btn_m.setFixedSize(26, 24)
            btn_m.setStyleSheet(self._JOG_BTN)
            btn_m.clicked.connect(lambda _, a=attr: self._jog_rot(a, -1))
            r_row.addWidget(btn_m)

            sp_r = _WheelSpinBox()
            sp_r.setRange(-180.0, 180.0)
            sp_r.setDecimals(1)
            sp_r.setSingleStep(1.0)
            sp_r.setStyleSheet(_AXIS_SP)
            sp_r.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
            sp_r.setFrame(False)
            sp_r.valueChanged.connect(lambda v, a=attr: self._jog_spin_changed(a, v))
            r_row.addWidget(sp_r)
            self._jog_spins[attr] = sp_r

            btn_p = QPushButton("↻")
            btn_p.setFixedSize(26, 24)
            btn_p.setStyleSheet(self._JOG_BTN)
            btn_p.clicked.connect(lambda _, a=attr: self._jog_rot(a, 1))
            r_row.addWidget(btn_p)

            lay.addLayout(r_row)

        return frame

    def _jog_set_step(self, step: float):
        self._jog_step = step
        for s, b in self._jog_step_btns.items():
            b.setChecked(s == step)

    def _jog_rx(self, direction: int):
        self._jog_rot('rot3d_x', direction)

    def _jog_rot(self, attr: str, direction: int):
        """Incrémente/décrémente un attribut de rotation pour tous les projecteurs sélectionnés."""
        projs = self._last_projectors
        rows = self._selected_rows or ({self._highlighted_row} if self._highlighted_row >= 0 else set())
        rows = {r for r in rows if 0 <= r < len(projs)}
        if not rows or not projs:
            return
        step = max(1.0, self._jog_step * 10)
        undo_steps = [{'idx': r, 'attrs': {attr: float(getattr(projs[r], attr, 0.0) or 0.0)}}
                      for r in rows]
        self._push_undo(undo_steps)
        for r in rows:
            p = projs[r]
            cur = float(getattr(p, attr, 0.0) or 0.0)
            setattr(p, attr, round(max(-180.0, min(180.0, cur + direction * step)), 1))
        sp = self._jog_spins.get(attr)
        primary = self._highlighted_row
        if sp and 0 <= primary < len(projs):
            sp.blockSignals(True)
            sp.setValue(float(getattr(projs[primary], attr, 0.0) or 0.0))
            sp.blockSignals(False)
        self.refresh(projs)
        self._save_patch()

    def _jog_flip(self):
        """Bascule rot3d_x entre 0° et 180° (retourne le projecteur)."""
        projs = self._last_projectors
        rows = self._selected_rows or ({self._highlighted_row} if self._highlighted_row >= 0 else set())
        rows = {r for r in rows if 0 <= r < len(projs)}
        if not rows or not projs:
            return
        undo_steps = [{'idx': r, 'attrs': {'rot3d_x': float(getattr(projs[r], 'rot3d_x', 0.0) or 0.0)}}
                      for r in rows]
        self._push_undo(undo_steps)
        for r in rows:
            p = projs[r]
            cur = float(getattr(p, 'rot3d_x', 0.0) or 0.0)
            p.rot3d_x = 0.0 if abs(cur) > 90.0 else 180.0
        sp = self._jog_spins.get('rot3d_x')
        primary = self._highlighted_row
        if sp and 0 <= primary < len(projs):
            sp.blockSignals(True)
            sp.setValue(float(getattr(projs[primary], 'rot3d_x', 0.0) or 0.0))
            sp.blockSignals(False)
        self.refresh(projs)
        self._save_patch()

    def _jog_spin_changed(self, attr: str, value: float):
        """Saisie directe dans un spinbox du jog pad → modifie le projecteur primaire."""
        idx = self._highlighted_row
        projs = self._last_projectors
        if idx < 0 or not projs or idx >= len(projs):
            return
        p = projs[idx]
        if attr in ('pos_3d_x', 'pos_3d_z') and getattr(p, 'pos_3d_x', None) is None:
            cx, cy = self._norm_pos(projs, idx)
            p.pos_3d_x = round((cx - 0.5) * 18.0, 2)
            p.pos_3d_z = round(-(cy - 0.5) * 10.0, 2)
        setattr(p, attr, value)
        # Sync mini-table spinbox
        attr_col = {'pos_3d_x': 1, 'pos_3d_z': 2, 'fixture_height': 3}
        col = attr_col.get(attr)
        if col is not None:
            sp = self._mini_tbl.cellWidget(idx, col)
            if sp:
                sp.blockSignals(True); sp.setValue(value); sp.blockSignals(False)
        if attr in ('pos_3d_x', 'pos_3d_z'):
            self._sync_canvas_pos(p)
        self.refresh(projs)
        self._save_patch()

    def _jog_move(self, dx: int, dz: int, dh: int):
        projs = self._last_projectors
        rows  = self._selected_rows or ({self._highlighted_row} if self._highlighted_row >= 0 else set())
        rows  = {r for r in rows if 0 <= r < len(projs)}
        if not rows or not projs:
            return
        step = self._jog_step

        # Sauvegarde undo pour tous les projecteurs sélectionnés
        undo_steps = []
        for r in rows:
            p = projs[r]
            if getattr(p, 'pos_3d_x', None) is None:
                cx, cy = self._norm_pos(projs, r)
                p.pos_3d_x = round((cx - 0.5) * 18.0, 2)
                p.pos_3d_z = round(-(cy - 0.5) * 10.0, 2)
            undo_steps.append({'idx': r, 'attrs': {
                'pos_3d_x':      float(getattr(p, 'pos_3d_x',      0)   or 0),
                'pos_3d_z':      float(getattr(p, 'pos_3d_z',      0)   or 0),
                'fixture_height':float(getattr(p, 'fixture_height', 7.0) or 7.0),
                'canvas_x':      getattr(p, 'canvas_x', None),
                'canvas_y':      getattr(p, 'canvas_y', None),
            }})
        self._push_undo(undo_steps)

        # Applique le déplacement
        for r in rows:
            p = projs[r]
            if dx:
                p.pos_3d_x = round(float(getattr(p, 'pos_3d_x', 0) or 0) + dx * step, 2)
            if dz:
                p.pos_3d_z = round(float(getattr(p, 'pos_3d_z', 0) or 0) + dz * step, 2)
            if dh:
                cur = float(getattr(p, 'fixture_height', 7.0) or 7.0)
                p.fixture_height = round(max(1.0, min(15.0, cur + dh * step)), 2)
            if dx or dz:
                self._sync_canvas_pos(p)
            # Sync mini-table spinboxes
            attr_col = {'pos_3d_x': 1, 'pos_3d_z': 2, 'fixture_height': 3}
            for attr, col in attr_col.items():
                sp = self._mini_tbl.cellWidget(r, col)
                if sp:
                    sp.blockSignals(True)
                    sp.setValue(float(getattr(p, attr, 0) or 0))
                    sp.blockSignals(False)

        # Met à jour les spinboxes du jog pad depuis le projecteur primaire
        primary = self._highlighted_row
        if primary >= 0 and primary < len(projs):
            pp = projs[primary]
            _def = {'pos_3d_x': 0.0, 'pos_3d_z': 0.0, 'fixture_height': 7.0,
                    'rot3d_x': 0.0, 'body_rotation': 0.0, 'rot3d_z': 0.0}
            for attr, sp in self._jog_spins.items():
                sp.blockSignals(True)
                dflt = _def.get(attr, 0.0)
                sp.setValue(float(getattr(pp, attr, dflt) or dflt))
                sp.blockSignals(False)
        self.refresh(projs)
        self._save_patch()

    # ── Undo (Ctrl+Z) ────────────────────────────────────────────────────────

    _UNDO_MAX = 50

    def _push_undo(self, steps: list):
        """steps: liste de {'idx': int, 'attrs': dict}"""
        if len(self._undo_stack) >= self._UNDO_MAX:
            self._undo_stack.pop(0)
        self._undo_stack.append(steps)

    def _undo(self):
        if not self._undo_stack:
            return
        steps = self._undo_stack.pop()
        projs = self._last_projectors
        if not projs:
            return
        attr_col = {'pos_3d_x': 1, 'pos_3d_z': 2, 'fixture_height': 3}
        for step in steps:
            idx = step['idx']
            if idx >= len(projs):
                continue
            p = projs[idx]
            for attr, val in step['attrs'].items():
                setattr(p, attr, val)
            self._sync_canvas_pos(p)
            for attr, col in attr_col.items():
                if attr in step['attrs']:
                    sp = self._mini_tbl.cellWidget(idx, col)
                    if sp:
                        sp.blockSignals(True)
                        sp.setValue(float(getattr(p, attr, 0) or 0))
                        sp.blockSignals(False)
        # Sync jog spinboxes depuis le primaire
        _def = {'pos_3d_x': 0.0, 'pos_3d_z': 0.0, 'fixture_height': 7.0, 'rot3d_x': 0.0}
        primary = self._highlighted_row
        if primary >= 0 and primary < len(projs):
            pp = projs[primary]
            for attr, sp in self._jog_spins.items():
                sp.blockSignals(True)
                dflt = _def.get(attr, 0.0)
                sp.setValue(float(getattr(pp, attr, dflt) or dflt))
                sp.blockSignals(False)
        self.refresh(projs)
        self._save_patch()

    def eventFilter(self, obj, event):
        if (obj is self._view and
                event.type() == QEvent.KeyPress and
                event.modifiers() == Qt.ControlModifier and
                event.key() == Qt.Key_Z):
            self._undo()
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Z:
            self._undo()
        else:
            super().keyPressEvent(event)

    # ── Sync 3D position → 2D canvas ─────────────────────────────────────────

    def _save_patch(self):
        mw = self._parent_mw
        if hasattr(mw, 'save_dmx_patch_config'):
            mw.save_dmx_patch_config()

    def _sync_canvas_pos(self, p):
        """Met à jour canvas_x/canvas_y depuis pos_3d et redessine le plan 2D."""
        if getattr(p, 'pos_3d_x', None) is not None:
            p.canvas_x = max(0.0, min(1.0, p.pos_3d_x / 18.0 + 0.5))
        if getattr(p, 'pos_3d_z', None) is not None:
            p.canvas_y = max(0.0, min(1.0, -p.pos_3d_z / 10.0 + 0.5))
        mw = self._parent_mw
        if mw and hasattr(mw, 'plan_de_feu'):
            mw.plan_de_feu.update()

    def _mini_tbl_set_highlight(self, row: int, on: bool):
        bg = QColor('#003d80') if on else QColor('#060616')
        fg = QColor('#ffffff') if on else QColor('#aaaacc')
        for col in range(self._mini_tbl.columnCount()):
            it = self._mini_tbl.item(row, col)
            if it:
                it.setBackground(QBrush(bg))
                it.setForeground(QBrush(fg))
        for col in (1, 2, 3):
            sp = self._mini_tbl.cellWidget(row, col)
            if sp:
                sp.setStyleSheet(self._MINI_SP_ON if on else self._MINI_SP)

    # ── Sélection (simple et multi Ctrl+clic) ────────────────────────────────

    def _on_mini_tbl_clicked(self, row: int, col: int):
        from PySide6.QtWidgets import QApplication
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        if ctrl:
            self._toggle_select(row)
        else:
            self._on_projo_selected(row)

    def _toggle_select(self, index: int):
        """Ctrl+clic : ajoute ou retire un projecteur de la sélection multiple."""
        if index in self._selected_rows:
            self._selected_rows.discard(index)
            self._mini_tbl_set_highlight(index, False)
            if index == self._highlighted_row:
                self._highlighted_row = max(self._selected_rows, default=-1)
                if self._highlighted_row >= 0:
                    self._mini_tbl_set_highlight(self._highlighted_row, True)
        else:
            self._selected_rows.add(index)
            self._highlighted_row = index
            self._mini_tbl_set_highlight(index, True)
            item = self._mini_tbl.item(index, 0)
            if item:
                self._mini_tbl.scrollToItem(item)
        self._js(f'if(window.highlightProjo)window.highlightProjo({self._highlighted_row})')
        self._update_jog_pad_from_primary()

    def _update_jog_pad_from_primary(self):
        """Met à jour le jog pad depuis le projecteur primaire sélectionné."""
        idx   = self._highlighted_row
        projs = self._last_projectors
        if idx < 0 or not projs or idx >= len(projs):
            self._jog_name.setText("—")
            for sp in self._jog_spins.values():
                sp.blockSignals(True); sp.setValue(0.0); sp.blockSignals(False)
            return
        p    = projs[idx]
        name = getattr(p, 'name', '') or getattr(p, 'group', '') or f'#{idx + 1}'
        n    = len(self._selected_rows)
        self._jog_name.setText(f"{name}  (+{n-1})" if n > 1 else name)
        _defaults = {'pos_3d_x': 0.0, 'pos_3d_z': 0.0, 'fixture_height': 7.0,
                     'rot3d_x': 0.0, 'body_rotation': 0.0, 'rot3d_z': 0.0}
        for attr, sp in self._jog_spins.items():
            sp.blockSignals(True)
            dflt = _defaults.get(attr, 0.0)
            sp.setValue(float(getattr(p, attr, dflt) or dflt))
            sp.blockSignals(False)

    def _on_projo_selected(self, index: int):
        """Sélection simple (depuis la table ou depuis le clic 3D)."""
        for r in self._selected_rows:
            self._mini_tbl_set_highlight(r, False)
        self._selected_rows = {index} if index >= 0 else set()
        self._highlighted_row = index

        self._js(f'if(window.highlightProjo)window.highlightProjo({index})')

        projs = self._last_projectors
        if index < 0 or not projs or index >= len(projs):
            self._jog_name.setText("—")
            return

        self._right_tabs.setCurrentIndex(1)
        self._mini_tbl_set_highlight(index, True)
        item = self._mini_tbl.item(index, 1) or self._mini_tbl.item(index, 0)
        if item:
            self._mini_tbl.scrollToItem(item)
        self._update_jog_pad_from_primary()

    # ── Onglet Scène ──────────────────────────────────────────────────────────

    def _build_scene_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#080818;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(4)

        self._scene_btns = {}
        for code, label in [
            ('live','Live'), ('dj','DJ'), ('concert','Concert'), ('club','Club'),
            ('festival','Festival'), ('arena','Grande scène'),
            ('sono','Sono Mobile'), ('totem','Totems'),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(code == 'live')
            btn.setStyleSheet(self._PANEL_BTN)
            btn.setToolTip(f"Preset scène : {_SCENE_PRESETS[code]['label']}")
            btn.clicked.connect(lambda _, c=code: self._apply_preset(c))
            lay.addWidget(btn)
            self._scene_btns[code] = btn

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        self._btn_trusses = QPushButton()  # kept for _apply_preset compat, not displayed
        sep.setStyleSheet("border:none;border-top:1px solid #1a1a38;margin:6px 0;")
        lay.addWidget(sep)

        lbl = QLabel("IMPORTER SCÈNE")
        lbl.setStyleSheet(
            "color:#2a2a4a;font-size:8px;letter-spacing:1.2px;font-weight:700;")
        lay.addWidget(lbl)

        btn_gltf = QPushButton("↓  GLTF / GLB")
        btn_gltf.setStyleSheet(self._PANEL_BTN)
        btn_gltf.setToolTip(
            "Importe un modèle 3D GLTF ou GLB\n"
            "Blender : File › Export › glTF 2.0 (.glb)\n"
            "SketchUp : Extensions › glTF Export\n"
            "Vectorworks : Export › 3D › glTF")
        btn_gltf.clicked.connect(self._import_scene)
        lay.addWidget(btn_gltf)

        btn_clear = QPushButton("✕  Effacer import")
        btn_clear.setStyleSheet(self._PANEL_BTN)
        btn_clear.clicked.connect(
            lambda: self._js('if(window.clearImportedScene)window.clearImportedScene()'))
        lay.addWidget(btn_clear)

        lay.addStretch()

        hint = QLabel(
            "Blender (gratuit) est recommandé :\n"
            "File → Export → glTF 2.0 → Format: GLB"
        )
        hint.setStyleSheet(
            "color:#1e1e3a;font-size:8px;font-family:'Segoe UI',sans-serif;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _import_scene(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer une scène 3D", "",
            "Fichiers 3D (*.gltf *.glb);;glTF JSON (*.gltf);;GLB binaire (*.glb)"
        )
        if not path:
            return
        with open(path, 'rb') as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode('ascii')
        is_glb = path.lower().endswith('.glb')
        self._js(f'if(window.loadGLTF)window.loadGLTF("{b64}",{str(is_glb).lower()})')

    # ── Truss Editor ─────────────────────────────────────────────────────────

    def _apply_preset(self, code: str):
        preset = _SCENE_PRESETS.get(code)
        if not preset:
            return
        self._scene_preset_code = code
        self._trusses = [t.copy() for t in preset['trusses']]
        self._js(f"window.setScenePreset('{code}')")
        for k, btn in getattr(self, '_scene_btns', {}).items():
            btn.setChecked(k == code)
        self._btn_trusses.setChecked(False)
        if self._truss_editor and self._truss_editor.isVisible():
            self._truss_editor.close()
        self._save_patch()

    def _open_truss_editor(self):
        if self._truss_editor and self._truss_editor.isVisible():
            self._truss_editor.close()
            self._btn_trusses.setChecked(False)
            return
        self._truss_editor = TrussEditorDialog(self._trusses, self)
        self._truss_editor.trusses_changed.connect(self._on_trusses_changed)
        self._truss_editor.finished.connect(lambda _: self._btn_trusses.setChecked(False))
        self._truss_editor.show()
        self._btn_trusses.setChecked(True)

    def _on_trusses_changed(self, trusses: list):
        self._trusses = trusses
        self.set_trusses(trusses)

    # ── Helpers JS ───────────────────────────────────────────────────────────

    def _js(self, code: str):
        """Exécute du JavaScript dans la page Three.js."""
        self._view.page().runJavaScript(code)

    def _open_placement(self):
        if self._placement_dlg and self._placement_dlg.isVisible():
            self._placement_dlg.raise_()
            return
        self._placement_dlg = ProjectorTableDialog(
            get_projectors=lambda: self._last_projectors,
            norm_pos_cb=self._norm_pos,
            refresh_cb=self.refresh,
            parent=self,
        )
        if self._last_projectors:
            self._placement_dlg.populate(self._last_projectors)
        self._placement_dlg.show()

    # ── Load ─────────────────────────────────────────────────────────────────

    def _on_render_crashed(self, status, exit_code):
        """Appelé quand le process de rendu WebEngine crashe ou est tué."""
        self._ready = False
        # Recharger la page après un court délai pour laisser le crash se nettoyer
        QTimer.singleShot(800, lambda: self._view.load(QUrl.fromLocalFile(str(_HTML))))

    def _on_load_finished(self, ok: bool):
        self._ready = ok
        if ok:
            # Restaurer le preset de scène (décors 3D + trusses du preset)
            self._js(f"window.setScenePreset('{self._scene_preset_code}')")
            # Puis appliquer les trusses réellement configurés (peuvent différer du preset)
            self._js(f'window.setTrusses({json.dumps(self._trusses)})')
            amb = getattr(self, '_sl_amb', None)
            if amb:
                self._js(f'window.ambLight.intensity={amb.value()/100:.2f}')
            self._js('if(window.setBloom)window.setBloom(0.0)')
            self._js('window.beamScale=0.5')
            if self._pending is not None:
                self._do_push()

    # ── Conversion projecteurs → JSON ─────────────────────────────────────────

    def _norm_pos(self, projectors, i):
        from plan_de_feu import _DEFAULT_POSITIONS
        p  = projectors[i]
        cx = getattr(p, 'canvas_x', None)
        cy = getattr(p, 'canvas_y', None)
        if cx is not None and cy is not None:
            return cx, cy
        group = getattr(p, 'group', '')
        gi    = [j for j, q in enumerate(projectors) if getattr(q, 'group', '') == group]
        li    = gi.index(i) if i in gi else 0
        fn    = _DEFAULT_POSITIONS.get(group, lambda li, n: (0.5, 0.5))
        return fn(li, len(gi))

    def _to_data(self, projectors):
        out = []
        now = _time.time()
        for i, p in enumerate(projectors):
            col  = getattr(p, 'color', None)
            r = col.red()   if col else 0
            g = col.green() if col else 0
            b = col.blue()  if col else 0
            # Strobe : bascule r/g/b à 0 sur la phase off
            spd = getattr(p, 'strobe_speed', 0)
            if spd > 0:
                freq = 1.0 + (spd / 100.0) * 19.0
                if int(now * freq * 2) % 2 == 0:
                    r = g = b = 0
            elif getattr(p, 'dmx_mode', '') == 'Strobe':
                if int(now * 10) % 2 == 0:
                    r = g = b = 0
            cx, cy = self._norm_pos(projectors, i)
            fh  = getattr(p, 'fixture_height', None)
            p3x = getattr(p, 'pos_3d_x', None)
            p3z = getattr(p, 'pos_3d_z', None)
            x_w = p3x if p3x is not None else (cx - 0.5) * 18.0
            z_w = p3z if p3z is not None else -(cy - 0.5) * 10.0
            out.append({
                'level':          int(getattr(p, 'level', 0)),
                'r': r, 'g': g, 'b': b,
                'x':              x_w,
                'z':              z_w,
                'pan':            getattr(p, 'pan',  32768),
                'tilt':           getattr(p, 'tilt', 32768),
                'fixture_type':   getattr(p, 'fixture_type', 'PAR LED'),
                'fixture_height': fh if fh is not None else TRUSS_Y,
                'body_rotation':  getattr(p, 'body_rotation', 0.0),
                'rot3d_x':        getattr(p, 'rot3d_x', 0.0),
                'rot3d_y':        getattr(p, 'body_rotation', 0.0),
                'rot3d_z':        getattr(p, 'rot3d_z', 0.0),
                'name':           getattr(p, 'name', ''),
                'group':          getattr(p, 'group', ''),
                'gobo':           int(getattr(p, 'gobo', 0) or 0),
                'gobo_rotation':  int(getattr(p, 'gobo_rotation', 0) or 0),
                'prism':          int(getattr(p, 'prism', 0) or 0),
                'prism_rotation': int(getattr(p, 'prism_rotation', 0) or 0),
            })
        return out

    # ── Push vers Three.js ───────────────────────────────────────────────────

    def _do_push(self):
        if not self._ready or self._pending is None:
            return
        data = json.dumps(self._to_data(self._pending))
        self._js(f'if(window.updateScene) window.updateScene({data})')
        self._pending = None

    def _do_strobe_push(self):
        if not self._ready or not self._last_projectors:
            return
        data = json.dumps(self._to_data(self._last_projectors))
        self._js(f'if(window.updateScene) window.updateScene({data})')

    def _update_strobe_timer(self, projectors):
        has_strobe = any(
            getattr(p, 'strobe_speed', 0) > 0 or getattr(p, 'dmx_mode', '') == 'Strobe'
            for p in projectors
        )
        if has_strobe and not self._strobe_timer.isActive():
            self._strobe_timer.start()
        elif not has_strobe and self._strobe_timer.isActive():
            self._strobe_timer.stop()

    # ── API publique (identique à Plan3DWindow) ───────────────────────────────

    def init_scene(self, projectors):
        self._last_projectors = projectors
        self._pending = projectors
        self._update_strobe_timer(projectors)
        if hasattr(self, '_mini_tbl'):
            self._populate_mini(projectors)
        if self._ready:
            self._do_push()

    def refresh(self, projectors):
        self._last_projectors = projectors
        self._pending = projectors
        self._update_strobe_timer(projectors)
        if not self._push_timer.isActive():
            self._push_timer.start()

    def set_trusses(self, trusses):
        """Met à jour la configuration des trusses."""
        self._trusses = trusses
        self._js(f'window.setTrusses({json.dumps(trusses)})')

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        mw = self._parent_mw
        if mw and hasattr(mw, 'plan_de_feu') and hasattr(mw.plan_de_feu, 'btn_3d'):
            mw.plan_de_feu.btn_3d.setChecked(False)
