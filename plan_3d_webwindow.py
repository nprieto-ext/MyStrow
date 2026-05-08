"""
Plan de feu 3D — rendu Three.js/WebGL via QWebEngineView.
Remplace Plan3DWindow avec une API identique : init_scene(), refresh().
"""
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QLabel, QSlider, QPushButton,
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QWidget,
    QCheckBox, QLineEdit, QDoubleSpinBox, QFrame,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtCore import Qt, QTimer, QUrl, Signal

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
            sp = QDoubleSpinBox()
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


class Plan3DWebWindow(QMainWindow):
    """Fenêtre 3D WebGL (Three.js) avec bloom, faisceaux volumétriques."""

    _TB_BTN = (
        "QPushButton { background:#1a1a36; color:#7777aa; border:1px solid #282850;"
        " border-radius:4px; font-size:10px; padding:3px 10px; min-width:44px; }"
        "QPushButton:hover { background:#252550; color:#ccccff; }"
        "QPushButton:checked { background:#003d66; color:#00d4ff; border-color:#005588; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Plan de feu 3D — WebGL")
        self.resize(1150, 700)
        self.setStyleSheet("background:#05050f;")

        self._view = QWebEngineView()
        s = self._view.settings()
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self._view.load(QUrl.fromLocalFile(str(_HTML)))
        self.setCentralWidget(self._view)

        self._projectors  = []
        self._pending     = None
        self._ready       = False
        self._trusses     = [
            {'label': 'Truss avant',   'enabled': True, 'height': TRUSS_Y, 'z': -3.8, 'x_l': -9.0, 'x_r': 9.0},
            {'label': 'Truss arrière', 'enabled': True, 'height': TRUSS_Y, 'z':  4.0, 'x_l': -9.0, 'x_r': 9.0},
        ]

        self._view.loadFinished.connect(self._on_load_finished)

        # Debounce : on coalesce les refresh rapides (MIDI) → max 25 fps
        self._push_timer = QTimer(self)
        self._push_timer.setSingleShot(True)
        self._push_timer.setInterval(40)
        self._push_timer.timeout.connect(self._do_push)

        self._build_toolbar()

    # ── Toolbar ──────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar(self)
        tb.setMovable(False)
        tb.setStyleSheet(
            "QToolBar { background:#0c0c20; border-bottom:1px solid #1a1a38;"
            " spacing:4px; padding:3px 8px; }"
        )
        self.addToolBar(tb)

        # Presets caméra
        for code, label in [('iso','ISO'), ('front','FACE'), ('top','DESSUS'), ('side','CÔTÉ')]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(code == 'iso')
            btn.setStyleSheet(self._TB_BTN)
            btn.clicked.connect(lambda _, c=code, b=btn: self._set_cam(c, b))
            tb.addWidget(btn)
            setattr(self, f'_btn_cam_{code}', btn)
        self._cam_btns = {
            'iso':   self._btn_cam_iso,
            'front': self._btn_cam_front,
            'top':   self._btn_cam_top,
            'side':  self._btn_cam_side,
        }

        tb.addSeparator()

        lbl_amb = QLabel("  Ambiance :")
        lbl_amb.setStyleSheet("color:#5555aa; font-size:10px;")
        tb.addWidget(lbl_amb)

        sl_amb = QSlider(Qt.Horizontal)
        sl_amb.setRange(0, 200)
        sl_amb.setValue(5)
        sl_amb.setFixedWidth(120)
        sl_amb.setToolTip("Lumière de scène — 0 = nuit noire, 100 = demi-jour, 200 = plein feu salle")
        sl_amb.setStyleSheet(
            "QSlider::groove:horizontal{height:3px;background:#222244;border-radius:2px;}"
            "QSlider::handle:horizontal{width:11px;height:11px;margin:-4px 0;"
            "background:#4455aa;border-radius:6px;}"
            "QSlider::sub-page:horizontal{background:#3344aa;border-radius:2px;}"
        )
        sl_amb.valueChanged.connect(
            lambda v: self._js(f'ambLight.intensity={v/100:.2f}'))
        tb.addWidget(sl_amb)

        tb.addSeparator()

        lbl_bl = QLabel("  Bloom :")
        lbl_bl.setStyleSheet("color:#5555aa; font-size:10px;")
        tb.addWidget(lbl_bl)

        sl_bl = QSlider(Qt.Horizontal)
        sl_bl.setRange(0, 40)
        sl_bl.setValue(18)
        sl_bl.setFixedWidth(100)
        sl_bl.setToolTip("Intensité de l'effet bloom")
        sl_bl.setStyleSheet(sl_amb.styleSheet())
        sl_bl.valueChanged.connect(
            lambda v: self._js(f'bloomPass.strength={v/10:.1f}'))
        tb.addWidget(sl_bl)

        tb.addSeparator()

        lbl_bs = QLabel("  Faisceaux :")
        lbl_bs.setStyleSheet("color:#5555aa; font-size:10px;")
        tb.addWidget(lbl_bs)

        sl_bs = QSlider(Qt.Horizontal)
        sl_bs.setRange(5, 30)
        sl_bs.setValue(14)
        sl_bs.setFixedWidth(90)
        sl_bs.setToolTip("Largeur des faisceaux")
        sl_bs.setStyleSheet(sl_amb.styleSheet())
        sl_bs.valueChanged.connect(
            lambda v: self._js(f'window.beamScale={v/10:.1f}'))
        tb.addWidget(sl_bs)

        tb.addSeparator()

        lbl_scene = QLabel("  Scène :")
        lbl_scene.setStyleSheet("color:#5555aa; font-size:10px;")
        tb.addWidget(lbl_scene)

        self._preset_btns = {}
        for code, label in [('live', 'Live'), ('dj', 'DJ'), ('concert', 'Concert'), ('club', 'Club')]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(code == 'live')
            btn.setStyleSheet(self._TB_BTN)
            btn.setToolTip(f"Preset scène : {_SCENE_PRESETS[code]['label']}")
            btn.clicked.connect(lambda _, c=code: self._apply_preset(c))
            tb.addWidget(btn)
            self._preset_btns[code] = btn

        btn_custom = QPushButton("Custom ⚙")
        btn_custom.setCheckable(True)
        btn_custom.setStyleSheet(self._TB_BTN)
        btn_custom.setToolTip("Éditeur de trusses personnalisé")
        btn_custom.clicked.connect(self._open_truss_editor)
        tb.addWidget(btn_custom)
        self._btn_trusses = btn_custom
        self._truss_editor = None

    # ── Truss Editor ─────────────────────────────────────────────────────────

    def _apply_preset(self, code: str):
        preset = _SCENE_PRESETS.get(code)
        if not preset:
            return
        self._trusses = [t.copy() for t in preset['trusses']]
        self._js(f"window.setScenePreset('{code}')")
        for k, btn in self._preset_btns.items():
            btn.setChecked(k == code)
        self._btn_trusses.setChecked(False)
        if self._truss_editor and self._truss_editor.isVisible():
            self._truss_editor.close()

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

    def _set_cam(self, code: str, btn: QPushButton):
        for b in self._cam_btns.values():
            b.setChecked(False)
        btn.setChecked(True)
        self._js(f"window.setCam('{code}')")

    # ── Load ─────────────────────────────────────────────────────────────────

    def _on_load_finished(self, ok: bool):
        self._ready = ok
        if ok:
            # Pousser l'état truss initial
            self._js(f'window.setTrusses({json.dumps(self._trusses)})')
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
        for i, p in enumerate(projectors):
            col  = getattr(p, 'color', None)
            r = col.red()   if col else 0
            g = col.green() if col else 0
            b = col.blue()  if col else 0
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
                'name':           getattr(p, 'name', ''),
                'group':          getattr(p, 'group', ''),
            })
        return out

    # ── Push vers Three.js ───────────────────────────────────────────────────

    def _do_push(self):
        if not self._ready or self._pending is None:
            return
        data = json.dumps(self._to_data(self._pending))
        self._js(f'if(window.updateScene) window.updateScene({data})')
        self._pending = None

    # ── API publique (identique à Plan3DWindow) ───────────────────────────────

    def init_scene(self, projectors):
        self._pending = projectors
        if self._ready:
            self._do_push()

    def refresh(self, projectors):
        self._pending = projectors
        if not self._push_timer.isActive():
            self._push_timer.start()

    def set_trusses(self, trusses):
        """Met à jour la configuration des trusses."""
        self._trusses = trusses
        self._js(f'window.setTrusses({json.dumps(trusses)})')

    def closeEvent(self, event):
        event.ignore()
