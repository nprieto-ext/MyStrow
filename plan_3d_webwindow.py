"""
Plan de feu 3D — rendu Three.js via QWebEngineView.
Remplace Plan3DWindow avec une API identique : init_scene(), refresh().
"""
import base64
import datetime
import json
import os
import sys
import time as _time
from pathlib import Path
from effect_editor import _NumCell

from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QLabel, QSlider, QPushButton,
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QWidget,
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QLineEdit,
    QDoubleSpinBox, QFrame, QGridLayout, QSizePolicy, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QObject, Slot, QEvent, QRectF
from PySide6.QtGui import QColor, QBrush, QPainter, QPen
from core import ComboSansMolette
from i18n import tr

TRUSS_Y   = 7.0
_HTML     = Path(getattr(__import__('sys'), '_MEIPASS', Path(__file__).parent)) / 'plan_3d_web.html'
# Décors 3D livrés avec l'application. Même résolution que _HTML : en EXE, tout
# est déplié dans le dossier temporaire de PyInstaller (_MEIPASS).
_DOSSIER_SCENES = Path(getattr(__import__('sys'), '_MEIPASS', Path(__file__).parent)) / 'scenes3d'


def _pos3d_from_canvas(cx, cy):
    """Position 3D (x, z) déduite d'une position du plan de feu 2D.

    Les DEUX axes sont inversés, et pour la même raison : la vue de référence
    est celle du PUBLIC. Une caméra placée en salle regarde vers les Z
    croissants, ce qui met les X croissants à sa gauche — côté jardin. Sans le
    signe sur X, le plan 2D et la 3D se lisaient en miroir : deux lyres posées à
    jardin sortaient à cour (remontée du 10/08/2026).
    """
    return round(-(cx - 0.5) * 18.0, 2), round(-(cy - 0.5) * 10.0, 2)


def _canvas_from_pos3d(x, z):
    """Réciproque de `_pos3d_from_canvas` : 3D → plan de feu 2D."""
    return (max(0.0, min(1.0, -x / 18.0 + 0.5)),
            max(0.0, min(1.0, -z / 10.0 + 0.5)))


def _set_pos3d_auto(proj, cx, cy):
    """Pose une position 3D DÉDUITE du plan 2D, en gardant sa provenance.

    `_pos3d_src` retient le point 2D d'où vient la position. Il distingue une
    position simplement recopiée du plan de feu d'une position réglée à la main
    dans le tableau 3D — sans lui, les deux sont indiscernables, et c'est ce qui
    débranchait le plan 2D : le tableau initialise `pos_3d_*` pour TOUS les
    projecteurs dès sa première ouverture, or `pos_3d_*` prime sur le 2D. Une
    lyre déplacée ensuite sur le plan de feu ne bougeait plus jamais en 3D
    (« je relance la 3D et je suis sur mon ancien plan de feu », 10/08/2026).
    """
    proj.pos_3d_x, proj.pos_3d_z = _pos3d_from_canvas(cx, cy)
    proj._pos3d_src = (cx, cy)


def _sync_pos3d_with_canvas(proj, cx, cy):
    """Recale la position 3D si le projecteur a bougé sur le plan 2D depuis.

    Ne touche pas aux positions réglées à la main dans le tableau 3D : celles-là
    n'ont pas de `_pos3d_src` (il est effacé à l'édition) et restent maîtresses.
    """
    if not hasattr(proj, '_pos3d_src'):
        # Show enregistré avant l'existence de `_pos3d_src` : si la position 3D
        # est exactement celle que le plan 2D produirait, c'est qu'elle en a été
        # déduite — on la rebranche. Sinon elle a été posée à la main, on la
        # laisse. Vrai tant que rien n'a bougé depuis le chargement, d'où cette
        # migration au tout premier passage.
        p3 = (getattr(proj, 'pos_3d_x', None), getattr(proj, 'pos_3d_z', None))
        proj._pos3d_src = (cx, cy) if p3 == _pos3d_from_canvas(cx, cy) else None
        return
    src = proj._pos3d_src
    if src is None:
        return
    bouge = abs(src[0] - cx) > 1e-9 or abs(src[1] - cy) > 1e-9
    # La FORMULE elle-même a pu changer (inversion de l'axe X du 10/08/2026) :
    # une position déduite qui ne correspond plus à ce que produit la conversion
    # courante est refaite. C'est ce qui remet d'aplomb, sans rien demander, les
    # rigs enregistrés avant l'inversion.
    perimee = (proj.pos_3d_x, proj.pos_3d_z) != _pos3d_from_canvas(*src)
    if bouge or perimee:
        _set_pos3d_auto(proj, cx, cy)

_SCENE_PRESETS = {
    'vide': {
        # Scène nue : ni truss ni accessoires. Utile quand le décor vient d'un
        # modèle importé (GLTF/GLB) — sinon le rig du preset reste dessous.
        'label': 'Aucun décor',
        'trusses': [],
    },
    # ── Décors livrés en modèle 3D ────────────────────────────────────────
    # `glb` = fichier du dossier scenes3d/, pousse dans la vue par
    # `_apply_preset`. Ces scenes n'ont AUCUN truss : le modele apporte sa
    # propre structure, en dessiner un second le ferait flotter au travers.
    # Les projecteurs qui accompagnaient le modele d'origine ont ete retires :
    # le rig, c'est le patch de l'utilisateur qui le pose, pas le decor.
    'concert_glb': {
        'label': 'Scène de concert',
        'trusses': [],
        'glb': 'concert_stage.glb',
        # Ce modèle est bâti fond de scène vers les Z NÉGATIFS, or ici les Z
        # négatifs sont l'avant-scène (cf. les trusses ci-dessous : « avant »
        # à z<0, « arrière » à z>0) et le plan 2D est converti dans ce repère.
        # Sans ce demi-tour, la ligne de contre du patch se retrouvait devant
        # le décor, côté public, et la face collée au fond (remontée du
        # 10/08/2026). Mesuré : 183 m² de mur à z=-5 contre 57 m² à z=+5.
        'yaw': 180.0,
        # Le grill du modèle est à 9,31 m à taille d'origine, mais `span` le
        # ramène à 16,2 m (×0,9) : il redescend donc à 8,4–9,0 m. Un projecteur
        # sans hauteur explicite s'accroche au milieu de cette poutre, au lieu
        # de rester à TRUSS_Y (7 m) et de flotter deux mètres plus bas.
        # ⚠️ Toute retouche de `span` déplace le grill : refaire le calcul.
        'rig_height': 8.7,
        # Ramené de 18 m à 16,2 m : c'est exactement l'emprise qu'un projecteur
        # peut atteindre depuis le plan de feu 2D (bornes 0,05–0,95 → ±8,1 m).
        # Les tours et les extrémités du grill tombent ainsi pile sur la position
        # la plus extérieure posable en 2D, et le grill avant/arrière (±4,1 m
        # après réduction) rentre dans les ±4,1/4,4 m atteignables en profondeur.
        'span': 16.2,
    },
    'truss_glb': {
        'label': 'Structure truss',
        'trusses': [],
        'glb': 'truss_structure.glb',
        # Portique : 3 arches reliées par des poutres longitudinales.
        # Symétrique en Z (mesuré : 15,3 m² de structure à z=-9 contre 16,3 à
        # z=+9) → pas de demi-tour à appliquer.
        # 20 m au lieu de 18 : la largeur passe à ±8,08 m, soit exactement
        # l'emprise atteignable depuis le plan de feu 2D (±8,1 m). Le rig tient
        # alors sous le portique au lieu de déborder sur les côtés.
        'span': 20.0,
        # La poutre haute court de 6,50 à 7,27 m (l'arche est cintrée, elle
        # n'est pas plate) : on accroche SOUS son point le plus bas, sinon les
        # projecteurs des extrémités traverseraient la structure.
        'rig_height': 6.3,
        # Ce portique est profond de ±10 m alors que le cyclorama est planté à
        # z = +5,6 : tout ce qui le dépasse passait derrière et se faisait
        # trancher net, la structure apparaissait coupée par un écran noir.
        'cyc': False,
    },
    # « Scène couverte » (warehouse_construction.glb) retirée le 10/08/2026 :
    # le modèle porte des éléments de structure qui flottent au milieu de l'aire
    # de jeu, impossibles à isoler proprement (géométrie partagée entre nœuds).
    # Le .glb a été sorti de `scenes3d/` — le dossier part en entier dans les 4
    # chemins de build, il aurait pesé pour rien dans l'installeur.
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
    'totem': {
        'label': 'Totems',
        'trusses': [
            {'label': 'Rig central', 'enabled': True, 'height': 5.5, 'z': -1.0, 'x_l': -2.5, 'x_r': 2.5},
        ],
    },
}

_DARK  = "background:#0c0c20; color:#999999;"
_STYLE_DLG = """
    QDialog, QWidget { background:#0c0c1e; color:#aaaaaa;
                       font-family:'Segoe UI',sans-serif; }
    QLabel  { background:transparent; border:none; }
    QLineEdit {
        background:#12122a; color:#dddddd; border:1px solid #222244;
        border-radius:3px; padding:2px 6px; font-size:11px;
    }
    QCheckBox { spacing:6px; }
    QCheckBox::indicator { width:14px; height:14px; border-radius:3px;
        border:1px solid #00d4ff; background:#12122a; }
    QCheckBox::indicator:checked { background:#003d66; border-color:#00d4ff; }
    QScrollArea { border:none; background:transparent; }
    QScrollBar:vertical { background:#0c0c20; width:5px; border:none; }
    QScrollBar::handle:vertical { background:#222244; border-radius:2px; }
"""
_STYLE_SPIN = (
    "QDoubleSpinBox { background:#12122a; color:#dddddd; border:1px solid #222244;"
    " border-radius:3px; padding:1px 4px; font-size:10px; }"
    "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button"
    " { background:#252525; width:14px; border:none; }"
)
_STYLE_ROW_BTN = (
    "QPushButton { background:#12122a; color:#999999; border:1px solid #1c1c40;"
    " border-radius:3px; font-size:10px; padding:2px 8px; }"
    "QPushButton:hover { background:#252525; color:#dddddd; }"
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
            "QFrame { background:#111111; border:1px solid #252525; border-radius:5px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # ── Ligne 1 : nom + enable ────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)

        self._chk = QCheckBox()
        self._chk.setChecked(truss.get('enabled', True))
        self._chk.setToolTip(tr("p3w_truss_toggle"))
        top.addWidget(self._chk)

        self._name = QLineEdit(truss.get('label', 'Truss'))
        self._name.setFixedWidth(130)
        self._name.setToolTip(tr("p3w_truss_name"))
        top.addWidget(self._name)
        top.addStretch()
        root.addLayout(top)

        # ── Ligne 2-4 : sliders H / Z / Largeur ──────────────────────────
        def _row(label, lo, hi, val, step=0.5, tip=""):
            rw = QHBoxLayout()
            rw.setSpacing(6)
            lbl = QLabel(label)
            lbl.setFixedWidth(self._LABEL_W)
            lbl.setStyleSheet("color:#4a4a4a; font-size:9px;")
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
        "QPushButton { background:#1a1a36; color:#999999; border:1px solid #282850;"
        " border-radius:4px; font-size:10px; padding:4px 14px; }"
        "QPushButton:hover { background:#252550; color:#dddddd; }"
        "QPushButton:pressed { background:#003d66; color:#00d4ff; }"
    )

    def __init__(self, trusses: list, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(tr("p3w_truss_editor"))
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
        title = QLabel(tr("p3w_trusses"))
        title.setStyleSheet("color:#00d4ff; font-size:13px; font-weight:bold;")
        root.addWidget(title)

        sub = QLabel(tr("p3w_live_changes"))
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
        sep.setStyleSheet("border:none; border-top:1px solid #252525;")
        root.addWidget(sep)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        btn_add = QPushButton(tr("p3w_add_truss"))
        btn_add.setStyleSheet(self._BTN)
        btn_add.clicked.connect(self._add_truss)
        btns.addWidget(btn_add)

        btn_del = QPushButton(tr("p3w_del_truss"))
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

    # En-tête de la colonne des cases : cliquable pour tout cocher d'un coup.
    # Une colonne vide ne disait pas qu'on pouvait sélectionner plusieurs
    # appareils, et les boutons du bas passaient inaperçus.
    _HDR  = ['☑', 'Projecteur', 'X (m)', 'Y haut.', 'Z (m)', 'Rot Y°', 'Rot X°', 'Rot Z°']
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
        "QTableWidget{background:#0d0d0d;color:#aaaaaa;border:1px solid #252525;"
        "gridline-color:#1c1c1c;font-size:10px;font-family:'Segoe UI',sans-serif;}"
        "QTableWidget::item{padding:0;border:none;}"
        "QHeaderView::section{background:#111111;color:#333355;border:none;"
        "border-right:1px solid #1c1c1c;border-bottom:1px solid #252525;"
        "padding:4px 4px;font-size:8px;letter-spacing:1px;font-weight:700;}"
        "QScrollBar:vertical{background:#0d0d0d;width:6px;border:none;}"
        "QScrollBar::handle:vertical{background:#252525;border-radius:3px;}"
    )
    _SP = (
        "QDoubleSpinBox{background:#0c0c20;color:#dddddd;border:none;"
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
        "QPushButton{background:#1a1a36;color:#999999;border:1px solid #282850;"
        "border-radius:4px;font-size:10px;padding:4px 12px;}"
        "QPushButton:hover{background:#252550;color:#dddddd;}"
        "QPushButton:pressed{background:#003d66;color:#00d4ff;}"
    )

    def __init__(self, get_projectors, norm_pos_cb, refresh_cb, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(tr("p3w_positioning"))
        self.resize(700, 480)
        self.setStyleSheet(_STYLE_DLG)
        self._get  = get_projectors   # () → list[Projector]
        self._npos = norm_pos_cb      # (projectors, i) → (cx, cy)
        self._cb   = refresh_cb       # (projectors) → None
        self._busy = False
        self._rows = []               # modèle : 1 ligne = 1 appareil (barre = 1)
        self._build_ui()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        hdr = QLabel(tr("p3w_fixture_pos"))
        hdr.setStyleSheet("color:#00d4ff;font-size:13px;font-weight:bold;")
        root.addWidget(hdr)

        sub = QLabel(
            tr("p3w_positioning_hint")
        )
        sub.setStyleSheet("color:#333355;font-size:9px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self._tbl = QTableWidget(0, len(self._HDR))
        # Libellés posés ICI et non dans `_HDR` : cet attribut de classe est
        # évalué à l'import, donc un `tr()` y resterait figé sur la langue du
        # démarrage. `_HDR` ne sert plus qu'à compter les colonnes.
        self._tbl.setHorizontalHeaderLabels(
            ['☑', tr("p3w_col_fixture"), 'X (m)', tr("p3w_col_height"), 'Z (m)',
             'Rot Y°', 'Rot X°', 'Rot Z°'])
        self._tbl.setStyleSheet(self._TBL)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setShowGrid(True)
        for i, w in enumerate(self._CW):
            self._tbl.setColumnWidth(i, w)
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.itemChanged.connect(self._on_chk_changed)
        # Clic sur l'en-tête de la colonne des cases = tout cocher / tout
        # décocher, le geste attendu d'un tableau à cases.
        self._tbl.horizontalHeader().setSectionsClickable(True)
        self._tbl.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        root.addWidget(self._tbl, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border:none;border-top:1px solid #252525;")
        root.addWidget(sep)

        bot = QHBoxLayout()
        bot.setSpacing(6)
        for label, slot in [
            (tr("p3w_check_all"),   lambda: self._set_all(True)),
            (tr("p3w_uncheck_all"), lambda: self._set_all(False)),
            (tr("p3w_reset_sel"),   self._reset_sel),
        ]:
            b = QPushButton(label)
            b.setStyleSheet(self._BTN)
            b.clicked.connect(slot)
            bot.addWidget(b)
        bot.addStretch()
        # Dit noir sur blanc à quoi s'applique la prochaine édition. Sans ce
        # repère, rien ne signalait qu'une valeur tapée sur une ligne allait
        # aussi partir sur toutes les autres lignes cochées.
        self._lbl_sel = QLabel()
        self._lbl_sel.setStyleSheet("color:#00d4ff;font-size:10px;")
        bot.addWidget(self._lbl_sel)
        root.addLayout(bot)
        self._maj_compteur()

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

    def _maj_compteur(self):
        n = len(self._checked())
        if n > 1:
            self._lbl_sel.setText(tr("p3w_sel_many", n=n))
        elif n == 1:
            self._lbl_sel.setText(tr("p3w_sel_one"))
        else:
            self._lbl_sel.setText(tr("p3w_sel_none"))

    def _on_header_clicked(self, col):
        """Clic sur l'en-tête ☑ : bascule tout coché / tout décoché."""
        if col == 0:
            self._set_all(len(self._checked()) < self._tbl.rowCount())

    def _set_all(self, state):
        self._busy = True
        for r in range(self._tbl.rowCount()):
            it = self._tbl.item(r, 0)
            if it:
                it.setCheckState(Qt.Checked if state else Qt.Unchecked)
                self._refresh_row_style(r)
        self._busy = False
        self._maj_compteur()

    def _on_chk_changed(self, item):
        if item.column() == 0 and not self._busy:
            self._refresh_row_style(item.row())
            self._maj_compteur()

    # ── Populate ──────────────────────────────────────────────────────────────

    def populate(self, projectors):
        self._busy = True

        # Init pos_3d pour TOUS les projecteurs (y compris les pixels d'une barre
        # non affichés) — sinon déplacer une barre casserait sur un pos None.
        for i, p in enumerate(projectors):
            cx, cy = self._npos(projectors, i)
            if getattr(p, 'pos_3d_x', None) is None:
                _set_pos3d_auto(p, cx, cy)
            else:
                # Déjà une position 3D : la recaler si elle vient du plan 2D et
                # que le projecteur y a bougé depuis (patch modifié, fixture
                # déplacée d'un groupe à l'autre…).
                _sync_pos3d_with_canvas(p, cx, cy)

        # Modèle de lignes : UN appareil par ligne. Une barre/matrice = 1 ligne
        # (ses N pixels regroupés), pas N lignes « · px1, · px2… ».
        self._rows = []
        seen = {}
        for i, p in enumerate(projectors):
            mid = getattr(p, 'matrix_id', None)
            if mid is not None:
                g = seen.get(mid)
                if g is None:
                    name = (getattr(p, 'name', '') or '').split(' · ')[0] \
                        or getattr(p, 'group', '') or f'#{i + 1}'
                    g = {'rep': i, 'members': [], 'name': name,
                         'group': getattr(p, 'group', '')}
                    seen[mid] = g
                    self._rows.append(g)
                g['members'].append(i)
            else:
                name = getattr(p, 'name', '') or getattr(p, 'group', '') or f'#{i + 1}'
                self._rows.append({'rep': i, 'members': [i], 'name': name,
                                   'group': getattr(p, 'group', '')})

        self._tbl.setRowCount(len(self._rows))
        for row, rd in enumerate(self._rows):
            p = projectors[rd['rep']]
            members = rd['members']
            # Position affichée = centroïde de l'appareil (barre : centre, pas 1 px)
            cx3 = sum(getattr(projectors[m], 'pos_3d_x', 0.0) or 0.0
                      for m in members) / len(members)
            cz3 = sum(getattr(projectors[m], 'pos_3d_z', 0.0) or 0.0
                      for m in members) / len(members)

            # Col 0 — checkbox
            if not self._tbl.item(row, 0):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Unchecked)
                self._tbl.setItem(row, 0, chk)

            # Col 1 — nom de l'appareil, coloré selon le groupe
            grp  = rd['group']
            nm_item = self._tbl.item(row, 1)
            if nm_item is None:
                nm_item = QTableWidgetItem()
                nm_item.setFlags(Qt.ItemIsEnabled)
                self._tbl.setItem(row, 1, nm_item)
            nm_item.setText(rd['name'])
            nm_item.setForeground(QBrush(QColor(self._GRP_COLOR.get(grp, '#666688'))))

            # Cols 2-7 — spinboxes
            vals = [
                cx3,
                getattr(p, 'fixture_height', 7.0),
                cz3,
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
        self._maj_compteur()

    # ── Edition ───────────────────────────────────────────────────────────────

    def _on_spin(self, row, col, value):
        if self._busy:
            return
        projs = self._get()
        attr  = self._ATTR[col]
        rows  = self._checked()
        if row not in rows:
            rows = [row]
        # X/Z : déplacer l'appareil ENTIER en delta (une barre garde l'écart de
        # ses pixels). Hauteur/rotations : valeur absolue, identique à tous.
        is_pos = attr in ('pos_3d_x', 'pos_3d_z')

        # Le déplacement se mesure UNE FOIS, sur la ligne qu'on manipule, puis
        # s'applique tel quel à toute la sélection. Il était recalculé pour
        # chaque ligne (`value - centroïde de la ligne`), ce qui amenait chaque
        # appareil sur la MÊME valeur absolue : sélectionner tout le rig et
        # toucher X empilait les projecteurs sur un seul point au lieu de les
        # décaler ensemble. L'écart entre appareils est maintenant conservé,
        # comme l'était déjà celui des pixels d'une barre.
        delta = 0.0
        if is_pos and row < len(self._rows):
            _ref = self._rows[row]['members']
            delta = value - (sum((getattr(projs[m], attr, 0.0) or 0.0)
                                 for m in _ref) / len(_ref))

        self._busy = True
        for r in rows:
            if r >= len(self._rows):
                continue
            members = self._rows[r]['members']
            if is_pos:
                for m in members:
                    if m < len(projs):
                        base = getattr(projs[m], attr, 0.0) or 0.0
                        setattr(projs[m], attr, base + delta)
                        # Placement 3D voulu par l'utilisateur : il cesse de
                        # suivre le plan 2D (cf. `_set_pos3d_auto`).
                        projs[m]._pos3d_src = None
            else:
                for m in members:
                    if m < len(projs):
                        setattr(projs[m], attr, value)
            if r != row:
                sp = self._tbl.cellWidget(r, col)
                if sp:
                    # En déplacement, chaque ligne garde SA valeur (décalée du
                    # même delta) : réafficher `value` partout ferait mentir le
                    # tableau, qui annoncerait un rig empilé sur un point.
                    if is_pos:
                        _shown = sum((getattr(projs[m], attr, 0.0) or 0.0)
                                     for m in members) / len(members)
                    else:
                        _shown = value
                    sp.blockSignals(True)
                    sp.setValue(_shown)
                    sp.blockSignals(False)
        self._busy = False
        self._cb(projs)

    def _reset_sel(self):
        projs = self._get()
        rows  = self._checked() or list(range(len(self._rows)))
        for r in rows:
            if r >= len(self._rows):
                continue
            for m in self._rows[r]['members']:
                if m < len(projs):
                    p = projs[m]
                    p.pos_3d_x      = None
                    p.pos_3d_z      = None
                    p._pos3d_src    = None   # repartira du plan 2D
                    p.body_rotation = 0.0
                    p.rot3d_x       = 0.0
                    p.rot3d_z       = 0.0
        self.populate(projs)
        self._cb(projs)


def _diag_log_path() -> str:
    """Fichier journal du plan 3D, à côté des autres logs de l'application."""
    if sys.platform == "win32":
        d = os.path.join(os.path.expanduser("~"), "AppData", "Local", "MyStrow", "Logs")
    else:
        d = os.path.join(os.path.expanduser("~"), ".mystrow_logs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "plan3d.log")


_diag_fh = None


def _diag_note(txt: str):
    """Journalise une ligne de diagnostic 3D : terminal ET fichier.

    Le fichier compte autant que la sortie standard : le glitch dure un quart
    de seconde et l'application est lancée au clic la plupart du temps —
    demander de guetter un terminal ne tient pas. Le fichier, lui, s'envoie.
    """
    global _diag_fh
    print(f"[Plan3D] {txt}")
    try:
        if _diag_fh is None:
            chemin = _diag_log_path()
            # Repartir à zéro au-delà de 2 Mo : ce journal sert à porter un
            # incident récent, pas à s'accumuler indéfiniment.
            mode = "a"
            if os.path.exists(chemin) and os.path.getsize(chemin) > 2 * 1024 * 1024:
                mode = "w"
            _diag_fh = open(chemin, mode, encoding="utf-8", buffering=1)
            _diag_fh.write(
                f"\n===== session {datetime.datetime.now():%d/%m/%Y %H:%M:%S} =====\n")
        _diag_fh.write(
            f"{datetime.datetime.now():%H:%M:%S.%f}"[:-3] + f"  {txt}\n")
    except Exception:
        pass   # un journal ne doit jamais empêcher la 3D de tourner


class _LoggingPage(QWebEnginePage):
    """Page qui fait remonter les messages de diagnostic de la scène 3D.

    QWebEngine avale les `console.*` par défaut. Or c'est la page — et elle
    seule — qui voit passer une perte de contexte WebGL, une image anormalement
    longue ou un changement de qualité. Sans ce relais, l'enquête sur le
    clignotement noir se faisait à l'aveugle.

    Filtré volontairement sur le préfixe `[3D]` : le bruit d'une page WebGL
    (avertissements de shaders, dépréciations) noierait le journal.
    """

    def javaScriptConsoleMessage(self, level, message, line, source):
        if not message.startswith("[3D]"):
            return
        _diag_note(message[4:].strip())


class _Bridge(QObject):
    """Pont QWebChannel — reçoit les clics sur les fixtures depuis Three.js."""

    def __init__(self, win):
        super().__init__()
        self._win = win

    @Slot(int)
    def projoSelected(self, index: int):
        self._win._on_projo_selected(index)

    @Slot(str, str)
    def saveGlitchShot(self, data_url: str, raison: str):
        """Écrit sur le disque l'image que la scène juge fautive.

        Le clignotement dure un quart de seconde : impossible de cliquer sur
        « exporter » à temps, et une photo d'écran prise au téléphone ne permet
        pas de distinguer un vrai tramage d'un moiré d'appareil photo. La scène
        se capture donc elle-même, au pixel près, à l'instant où sa sonde
        déclenche.
        """
        try:
            b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
            nom = (f"plan3d_{raison}_"
                   f"{datetime.datetime.now():%H%M%S}.jpg")
            chemin = os.path.join(os.path.dirname(_diag_log_path()), nom)
            with open(chemin, "wb") as f:
                f.write(base64.b64decode(b64))
            _diag_note(f"capture écrite : {chemin}")
        except Exception as e:
            _diag_note(f"capture non enregistrée : {e}")


class _P3Cell(_NumCell):
    """Cellule chiffrée du tableau 3D — celle de l'éditeur d'effets.

    Même geste et même rendu que dans l'éditeur : glisser vers le haut/bas
    règle la valeur, la molette l'affine, un double-clic permet de la taper, et
    une jauge de fond donne le niveau d'un coup d'œil. On lui ajoute juste
    l'API d'un QDoubleSpinBox (`setValue`) pour que le reste du tableau, qui
    manipule ses cellules comme des spinboxes, n'ait pas à changer.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._row_sel = False

    def set_row_selected(self, on: bool):
        on = bool(on)
        if on != self._row_sel:
            self._row_sel = on
            self.update()

    def paintEvent(self, e):
        """Rendu normal, plus un liseré cyan quand la ligne est sélectionnée.

        On repeint par-dessus au lieu de dupliquer le dessin de la cellule :
        la feuille de style, elle, n'a aucun effet ici — la cellule se peint
        entièrement au QPainter, c'est pourquoi l'ancien surlignage restait
        invisible sur ces colonnes.
        """
        super().paintEvent(e)
        if not self._row_sel:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#00d4ff"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 4, 4)
        p.end()
    def setValue(self, v):
        self.set_value(int(round(float(v))), emit=False)

    def wheelEvent(self, event):
        """La molette fait défiler le tableau, elle ne règle pas la valeur.

        Dans l'éditeur d'effets la liste tient à l'écran, la molette peut donc
        affiner une valeur sans ambiguïté. Ici le tableau défile : molette sur
        une cellule en cherchant la ligne du bas, et on déréglait un projecteur
        au passage — sans le voir, puisqu'on regardait ailleurs.
        On laisse l'événement remonter à la zone de défilement.
        """
        event.ignore()


class Plan3DWebWindow(QMainWindow):
    """Fenêtre 3D (Three.js) avec bloom, faisceaux volumétriques."""

    _TB_BTN = (
        "QPushButton { background:#1a1a36; color:#999999; border:1px solid #282850;"
        " border-radius:4px; font-size:10px; padding:3px 10px; min-width:44px; }"
        "QPushButton:hover { background:#252550; color:#dddddd; }"
        "QPushButton:checked { background:#003d66; color:#00d4ff; border-color:#005588; }"
    )
    _JOG_BTN = (
        "QPushButton{background:#151515;color:#999999;border:1px solid #252525;"
        "border-radius:4px;font-size:14px;padding:3px;}"
        "QPushButton:hover{background:#252525;color:#dddddd;}"
        "QPushButton:pressed{background:#003d66;color:#00d4ff;}"
    )
    _JOG_STEP_BTN = (
        "QPushButton{background:#111111;color:#4a4a4a;border:1px solid #252525;"
        "border-radius:3px;font-size:8px;padding:2px 4px;}"
        "QPushButton:hover{background:#252525;color:#aaaaaa;}"
        "QPushButton:checked{background:#003d66;color:#00d4ff;border-color:#005588;}"
    )

    def __init__(self, parent=None):
        super().__init__(None, Qt.Window)   # pas de parent Qt → évite le bleeding visuel sur Windows
        self._parent_mw = parent
        self.setWindowTitle(tr("p3w_title"))
        self.resize(1150, 700)
        self.setStyleSheet("background:#05050f;")

        self._view = QWebEngineView()
        # Sans cette page, les `console.*` de la scène 3D ne vont NULLE PART :
        # QWebEngine les avale en silence. C'est ce qui rendait le clignotement
        # noir introuvable — tout ce que la page savait du problème restait
        # enfermé dedans. On ne remonte que ce qui est diagnostique.
        self._view.setPage(_LoggingPage(self._view))
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

        # État interne AVANT _build_right_panel() : l'onglet Cam. lit
        # self._quality pour positionner son combo. Défini après, il levait
        # AttributeError en pleine construction de MainWindow — MyStrow
        # mourait juste après le splash, sans fenêtre ni message.
        self._projectors      = []
        self._last_projectors = []
        self._pending         = None
        self._ready           = False
        # Sortie live de l'éditeur d'effets — cf. set_fx_overrides()
        self._fx_overrides    = None
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
        self._imported_path = ''
        self._pinned = False   # « toujours au-dessus » demandé par l'utilisateur
        # Points de vue mémorisés : nom → dict {pos, tgt, fov}
        # Vues mémorisées : l'interface a été retirée du panneau, mais on
        # continue de lire et réécrire la clé pour ne pas effacer les cadrages
        # déjà enregistrés dans le patch d'un utilisateur.
        self._views: dict = {}
        # Niveau de qualité de rendu (index dans QUALITY côté JS)
        self._quality = 2
        self._auto_quality = True
        # Ambiance salle, en unités du curseur (200 = 100 %). 160 = 80 %, valeur
        # jugée plus juste à l'usage que le 100 % d'origine, et surtout
        # mémorisée : c'était un réglage à refaire à chaque ouverture.
        self._ambience = 160
        # Brouillard dans les faisceaux : 0 % par défaut, donc rendu inchangé
        # pour qui ne va pas le chercher — et aucun coût GPU tant qu'il est nul.
        self._fog = 0
        self._fog_scale = 55        # 0,55 m⁻¹ ≈ une volute tous les 1,8 m
        self._fog_speed = 35        # ≈ 10 cm/s : la fumée flotte, elle ne file pas

        # Charger la scène sauvegardée depuis le patch, avant que la page HTML charge
        try:
            _cfg_path = Path.home() / '.maestro_dmx_patch.json'
            if _cfg_path.exists():
                _cfg = json.loads(_cfg_path.read_text(encoding='utf-8'))
                _s3d = _cfg.get('scene_3d', {})
                if _s3d.get('preset') in _SCENE_PRESETS:
                    self._scene_preset_code = _s3d['preset']
                # `in` et non truthiness : une liste VIDE est fausse en Python.
                # Avec l'ancien test, « aucune structure » ne se relisait jamais
                # — le patch enregistrait bien [], mais au chargement on gardait
                # les deux trusses par défaut. D'où un décor qui réapparaissait
                # à chaque démarrage sans qu'on puisse s'en débarrasser.
                if isinstance(_s3d.get('trusses'), list):
                    self._trusses = _s3d['trusses']
                self._imported_path = _s3d.get('imported_model', '') or ''
                if isinstance(_s3d.get('views'), dict):
                    self._views = _s3d['views']
                if isinstance(_s3d.get('quality'), int):
                    self._quality = max(0, min(3, _s3d['quality']))
                self._auto_quality = bool(_s3d.get('auto_quality', True))
                if isinstance(_s3d.get('ambience'), (int, float)):
                    self._ambience = max(0, min(4000, int(_s3d['ambience'])))
                if isinstance(_s3d.get('fog'), (int, float)):
                    self._fog = max(0, min(100, int(_s3d['fog'])))
                if isinstance(_s3d.get('fog_scale'), (int, float)):
                    self._fog_scale = max(15, min(200, int(_s3d['fog_scale'])))
                if isinstance(_s3d.get('fog_speed'), (int, float)):
                    self._fog_speed = max(0, min(100, int(_s3d['fog_speed'])))
        except Exception:
            pass

        # Layout : QSplitter (vue 3D | panneau onglets redimensionnable)
        self._right_panel = self._build_right_panel()
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setStyleSheet(
            "QSplitter::handle{background:#151515;width:4px;}"
            "QSplitter::handle:hover{background:#003d66;}"
        )
        self._splitter.addWidget(self._view)
        self._splitter.addWidget(self._right_panel)
        self._splitter.setSizes([850, 240])
        self._splitter.setChildrenCollapsible(False)
        self._right_panel_sizes = [850, 240]
        self.setCentralWidget(self._splitter)


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
            "QToolBar { background:#0c0c20; border-bottom:1px solid #252525;"
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
        btn_pin.setToolTip(tr("p3w_always_top"))
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
        self._btn_toggle_panel.setToolTip(tr("p3w_toggle_panel"))
        self._btn_toggle_panel.setFixedSize(28, 28)
        self._btn_toggle_panel.setStyleSheet(_PDF_BTN)
        self._btn_toggle_panel.clicked.connect(self._toggle_right_panel)
        tb.addWidget(self._btn_toggle_panel)



    def _set_always_on_top(self, enabled: bool):
        self._pinned = bool(enabled)
        self._apply_on_top(enabled)

    def _apply_on_top(self, enabled: bool):
        """Met la fenêtre au-dessus des autres, SANS toucher aux flags Qt.

        `setWindowFlags()` masque la fenêtre et impose un `show()` derrière :
        chaque bascule (y compris les désépinglages automatiques ci-dessous,
        déclenchés par le moindre dialogue modal) ré-affiche donc le plan 3D et
        lui redonne le premier plan — au milieu d'une séquence de fermeture,
        c'est tout sauf souhaitable.

        Sous Windows, SetWindowPos bascule le style WS_EX_TOPMOST sur la
        fenêtre existante : pas de hide/show, pas de vol de focus, pas de
        clignotement de la vue QWebEngine. Mesuré : le HWND est inchangé et le
        style survit à un cycle hide()/show().
        """
        import sys as _sys
        if _sys.platform == 'win32':
            try:
                import ctypes
                HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
                SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
                ctypes.windll.user32.SetWindowPos(
                    ctypes.c_void_p(int(self.winId())),
                    ctypes.c_void_p(HWND_TOPMOST if enabled else HWND_NOTOPMOST),
                    0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
                return
            except Exception:
                pass    # repli sur les flags Qt

        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def showEvent(self, event):
        """Réapplique l'épinglage : Qt peut avoir recréé la fenêtre entre-temps."""
        super().showEvent(event)
        if getattr(self, '_pinned', False):
            self._apply_on_top(True)

    def event(self, e):
        """Désépingle temporairement quand un dialogue modal s'ouvre.

        Une fenêtre épinglée reste au-dessus de TOUT, y compris d'un dialogue
        modal — lequel bloque en retour toutes les autres fenêtres. Résultat :
        le plan 3D masquait le patch DMX tout en refusant le moindre clic, sa
        croix de fermeture comprise. Plus aucun moyen de s'en sortir sans tuer
        l'application.

        Qt prévient les fenêtres concernées par WindowBlocked / WindowUnblocked :
        on retire l'épinglage le temps du dialogue, et on le remet après. Le
        bouton reste coché — du point de vue de l'utilisateur, rien n'a changé.
        """
        t = e.type()
        if t == QEvent.WindowBlocked and getattr(self, '_pinned', False):
            self._apply_on_top(False)
        elif t == QEvent.WindowUnblocked and getattr(self, '_pinned', False):
            self._apply_on_top(True)
        return super().event(e)

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

    # Palette alignée sur le reste du logiciel (éditeur d'effets, dialogues) :
    # gris neutres #0d0d0d / #151515 / #252525 et cyan #00d4ff en accent.
    # Le panneau 3D tirait vers le bleu nuit (#0d0d0d, #151515) et jurait avec
    # tout le reste, tableau compris.
    _TAB_STYLE = (
        "QTabWidget::pane{border:none;background:#0d0d0d;}"
        "QTabBar{background:#0d0d0d;}"
        "QTabBar::tab{background:transparent;color:#4a4a4a;border:none;"
        "padding:7px 14px;font-size:10px;letter-spacing:1px;font-weight:700;"
        "font-family:'Segoe UI',sans-serif;border-bottom:2px solid transparent;}"
        "QTabBar::tab:selected{color:#00d4ff;border-bottom:2px solid #00d4ff;}"
        "QTabBar::tab:hover:!selected{color:#999999;}"
    )
    _PANEL_BTN = (
        "QPushButton{background:#151515;color:#999999;border:1px solid #252525;"
        "border-radius:5px;font-size:10px;letter-spacing:0.5px;padding:6px 0;"
        "font-family:'Segoe UI',sans-serif;}"
        "QPushButton:hover{background:#1e1e1e;color:#00d4ff;border-color:#00d4ff;}"
        "QPushButton:checked{background:#00303d;color:#00d4ff;"
        "border-color:#00d4ff;}"
    )

    _PANEL_COMBO = (
        "QComboBox{background:#151515;color:#aaaaaa;border:1px solid #252525;"
        "border-radius:4px;font-size:10px;padding:4px 6px;"
        "font-family:'Segoe UI',sans-serif;}"
        "QComboBox:hover{border-color:#00d4ff;}"
        "QComboBox::drop-down{border:none;width:16px;}"
        "QComboBox QAbstractItemView{background:#151515;color:#dddddd;"
        "selection-background-color:#00d4ff;selection-color:#000000;"
        "border:1px solid #00d4ff;outline:none;font-size:10px;}"
    )

    _PANEL_CHK = (
        "QCheckBox{color:#999999;font-size:10px;spacing:6px;"
        "font-family:'Segoe UI',sans-serif;}"
        "QCheckBox:hover{color:#00d4ff;}"
        "QCheckBox::indicator{width:12px;height:12px;border-radius:3px;"
        "border:1px solid #252525;background:#151515;}"
        "QCheckBox::indicator:hover{border-color:#00d4ff;}"
        "QCheckBox::indicator:checked{background:#00d4ff;border-color:#00d4ff;}"
    )

    # Style commun aux curseurs des panneaux (ambiance, brouillard…). Extrait
    # en constante parce que le bloc Brouillard vit dans l'onglet Scène alors
    # qu'il empruntait la feuille de style du curseur d'ambiance, resté dans
    # l'onglet Caméra.
    _SLIDER_QSS = (
        "QSlider::groove:horizontal{height:4px;background:#151515;border-radius:2px;}"
        "QSlider::sub-page:horizontal{background:#3344aa;border-radius:2px;}"
        "QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;"
        "background:#5566cc;border-radius:6px;}"
        "QSlider::handle:horizontal:hover{background:#7788ff;}"
    )

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(160)
        w.setStyleSheet("background:#0d0d0d;border-left:1px solid #1c1c1c;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        tabs = QTabWidget()
        tabs.setStyleSheet(self._TAB_STYLE)
        tabs.addTab(self._build_cam_tab(),       tr("p3w_cam"))
        tabs.addTab(self._build_placement_tab(), tr("p3w_plan"))
        tabs.addTab(self._build_scene_tab(),     tr("p3w_stage"))
        lay.addWidget(tabs)
        self._right_tabs = tabs
        tabs.currentChanged.connect(self._on_right_tab_changed)
        return w

    # ── Onglet Caméra ─────────────────────────────────────────────────────────

    def _build_cam_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#0d0d0d;")
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
        lbl_amb = QLabel(tr("p3w_room_ambience"))
        lbl_amb.setStyleSheet("color:#4444aa;font-size:9px;letter-spacing:0.5px;")
        lay.addWidget(lbl_amb)

        self._amb_val_lbl = QLabel("100%")
        self._amb_val_lbl.setStyleSheet("color:#7777cc;font-size:9px;")
        self._amb_val_lbl.setAlignment(Qt.AlignRight)
        lay.addWidget(self._amb_val_lbl)

        sl_amb = QSlider(Qt.Horizontal)
        # Plafond porté de 1000 à 4000 : ×4 de marge en haut de course. 200 reste
        # le réglage d'origine (affiché 100 %), la butée haute monte à 2000 %.
        sl_amb.setRange(0, 4000)
        sl_amb.setValue(getattr(self, '_ambience', 160))
        sl_amb.setPageStep(200)
        sl_amb.setToolTip(tr("p3w_ambient"))
        sl_amb.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#151515;border-radius:2px;}"
            "QSlider::sub-page:horizontal{background:#3344aa;border-radius:2px;}"
            "QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;"
            "background:#5566cc;border-radius:6px;}"
            "QSlider::handle:horizontal:hover{background:#7788ff;}"
        )

        def _on_amb(v):
            # 200 = réglage d'origine → affiché 100 %. Le curseur monte jusqu'à
            # 500 %, et pilote les trois lumières d'ambiance via setRoomAmbience
            # (il ne touchait que l'AmbientLight, d'où son manque d'effet).
            self._amb_val_lbl.setText(f"{v//2}%")
            self._ambience = int(v)
            self._js(f'window.setRoomAmbience && window.setRoomAmbience({v/200:.3f})')

        sl_amb.valueChanged.connect(_on_amb)
        # Enregistrement au relâchement seulement : valueChanged part à chaque
        # pixel du glissement, réécrire le patch à ce rythme serait absurde.
        sl_amb.sliderReleased.connect(self._save_patch)
        _on_amb(sl_amb.value())          # applique l'état mémorisé à l'ouverture
        lay.addWidget(sl_amb)
        self._sl_amb = sl_amb

        lay.addSpacing(10)


        lay.addSpacing(12)

        btn_snap = QPushButton(tr("p3w_export_img"))
        btn_snap.setStyleSheet(self._PANEL_BTN)
        btn_snap.setToolTip(tr("p3w_save_png"))
        btn_snap.clicked.connect(self._export_image)
        lay.addWidget(btn_snap)

        lay.addSpacing(12)

        # ── Qualité de rendu ──────────────────────────────────────────────
        lbl_q = QLabel(tr("p3w_quality"))
        lbl_q.setStyleSheet("color:#4444aa;font-size:9px;letter-spacing:0.5px;")
        lay.addWidget(lbl_q)

        self._cb_quality = ComboSansMolette()
        self._cb_quality.setStyleSheet(self._PANEL_COMBO)
        self._cb_quality.addItems(["Bas", "Moyen", "Haut", "Ultra"])
        self._cb_quality.setCurrentIndex(self._quality)
        self._cb_quality.setToolTip(
            tr("p3w_beam_quality"))
        self._cb_quality.activated.connect(self._on_quality_changed)
        lay.addWidget(self._cb_quality)

        self._chk_auto_q = QCheckBox(tr("p3w_auto_lower"))
        self._chk_auto_q.setChecked(self._auto_quality)
        self._chk_auto_q.setStyleSheet(self._PANEL_CHK)
        self._chk_auto_q.toggled.connect(self._on_auto_quality)
        lay.addWidget(self._chk_auto_q)

        self._chk_fps = QCheckBox(tr("p3w_show_fps"))
        self._chk_fps.setChecked(False)
        self._chk_fps.setStyleSheet(self._PANEL_CHK)
        self._chk_fps.toggled.connect(
            lambda on: self._js(f'window.showFps && window.showFps({str(bool(on)).lower()})'))
        lay.addWidget(self._chk_fps)

        lay.addStretch()

        hint = QLabel(tr("p3w_cam_hint"))
        hint.setStyleSheet(
            "color:#1a1a32;font-size:8px;font-family:'Segoe UI',sans-serif;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _set_cam_py(self, code: str):
        for k, b in self._cam_btns_py.items():
            b.setChecked(k == code)
        self._js(f"window.setCam('{code}')")

    # ── Export image ─────────────────────────────────────────────────────────

    def _export_image(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le plan 3D", "plan_3d.png", "Image PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith('.png'):
            path += '.png'

        def _got(data_url):
            if not data_url or not isinstance(data_url, str):
                self._snap_failed("aucune donnée renvoyée par le rendu")
                return
            if data_url.startswith('ERR:'):
                self._snap_failed(data_url[4:])
                return
            try:
                b64 = data_url.split(',', 1)[1]
                Path(path).write_bytes(base64.b64decode(b64))
            except Exception as e:
                self._snap_failed(str(e))

        self._view.page().runJavaScript("window.snapshot && window.snapshot()", _got)

    def _snap_failed(self, why: str):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, tr("p3w_export_failed"),
                            tr("p3w_export_failed_why", why=why))

    # ── Qualité de rendu ─────────────────────────────────────────────────────

    def _on_quality_changed(self, idx: int):
        self._quality = max(0, min(3, int(idx)))
        self._js(f"window.setQuality && window.setQuality({self._quality})")
        self._save_patch()

    def _on_auto_quality(self, on: bool):
        self._auto_quality = bool(on)
        self._js(f"window.autoQuality = {str(bool(on)).lower()}")
        self._save_patch()

    # ── Onglet Placement (mini-table) ─────────────────────────────────────────

    # Habillage repris de l'éditeur d'effets : fond noir, pas de quadrillage
    # (ce sont les cellules qui dessinent leur propre cadre arrondi), en-têtes
    # gris discrets qui passent au cyan au survol.
    _MINI_TBL = (
        "QTableWidget{background:#0d0d0d;color:#aaaaaa;border:none;"
        "gridline-color:transparent;font-size:9px;font-family:'Segoe UI',sans-serif;}"
        "QTableWidget::item{padding:0;border:none;}"
        "QHeaderView::section{background:#0d0d0d;color:#4a4a4a;border:none;"
        "padding:4px 2px;font-size:9px;letter-spacing:1px;font-weight:700;}"
        "QHeaderView::section:hover{color:#00d4ff;}"
        "QScrollBar:vertical{background:#0d0d0d;width:6px;border:none;}"
        "QScrollBar::handle:vertical{background:#262626;border-radius:3px;}"
        # Ascenseur HORIZONTAL volontairement plus visible que le vertical :
        # les colonnes font 486 px dans un panneau qui descend à 160 px, donc
        # RZ, Faisc. et Taille sont hors cadre — et rien ne le laissait
        # deviner. Le débordement vertical, lui, se devine au nombre de lignes.
        "QScrollBar:horizontal{background:#111118;height:11px;border:none;margin:0;}"
        "QScrollBar::handle:horizontal{background:#3d3d5c;border-radius:5px;min-width:36px;}"
        "QScrollBar::handle:horizontal:hover{background:#00d4ff;}"
        "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal"
        "{width:0;height:0;}"
        "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal"
        "{background:transparent;}"
    )
    _MINI_SP = (
        "QDoubleSpinBox{background:#0d0d0d;color:#dddddd;border:none;"
        "padding:1px 0;font-size:9px;}"
        "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button"
        "{background:#151515;border:none;width:10px;}"
    )
    _MINI_SP_ON = (
        "QDoubleSpinBox{background:#002244;color:#00d4ff;border:none;"
        "padding:1px 0;font-size:9px;}"
        "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button"
        "{background:#003366;border:none;width:10px;}"
    )

    def _build_placement_tab(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#0d0d0d;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Mini-table : checkbox + nom + X / Z / Haut
        # Tableau complet : position, orientation ET puissance de faisceau.
        # Tout se règle ici, ligne par ligne, sans passer par le jog pad qui ne
        # traite qu'un projecteur à la fois.
        self._mini_tbl = QTableWidget(0, 10)
        # X/Z/H/RX/RY/RZ restent tels quels : ce sont des symboles d'axes, pas
        # des mots — les traduire ne ferait que les rendre méconnaissables.
        self._mini_tbl.setHorizontalHeaderLabels(
            [tr("p3w_col_fixture"), 'X', 'Z', 'H', 'RX', 'RY', 'RZ',
             tr("p3w_col_beam"), tr("p3w_col_angle"), tr("p3w_col_size")])
        self._mini_tbl.setStyleSheet(self._MINI_TBL)
        self._mini_tbl.verticalHeader().setVisible(False)
        self._mini_tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self._mini_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        cw = [78, 44, 44, 44, 44, 44, 44, 48, 48, 48]
        for i, w_ in enumerate(cw):
            self._mini_tbl.setColumnWidth(i, w_)
        self._mini_tbl.horizontalHeader().setStretchLastSection(False)
        # Toujours affiché, même quand le panneau est assez large : c'est LUI
        # qui annonce qu'il y a des colonnes à droite. En mode « au besoin »,
        # il n'apparaît qu'une fois qu'on a compris qu'il fallait défiler.
        self._mini_tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        for _c, _tip in enumerate((
                tr("p3w_tip_fixture"), tr("p3w_tip_x"), tr("p3w_tip_z"),
                tr("p3w_tip_h"), tr("p3w_tip_rx"), tr("p3w_tip_ry"),
                tr("p3w_tip_rz"), tr("p3w_tip_beam"), tr("p3w_tip_angle"),
                tr("p3w_tip_size"))):
            _h = self._mini_tbl.horizontalHeaderItem(_c)
            if _h is not None:
                _h.setToolTip(_tip)
        self._mini_tbl.cellClicked.connect(self._on_mini_tbl_clicked)
        lay.addWidget(self._mini_tbl, 1)

        # La sélection multiple existait — Ctrl+clic, et toute valeur modifiée
        # part sur toutes les lignes retenues — mais RIEN ne l'annonçait : ni
        # case à cocher, ni libellé, ni raccourci listé. Fonction invisible =
        # fonction absente. Ce bandeau l'énonce et sert de compteur vivant.
        self._lbl_multi = QLabel(tr("p3w_plan_multi_hint"))
        self._lbl_multi.setStyleSheet(
            "color:#556; font-size:9px; padding:3px 4px;"
            "border-top:1px solid #1c1c1c;")
        self._lbl_multi.setWordWrap(True)
        lay.addWidget(self._lbl_multi)

        # Jog pad : construit mais NON affiché. Le tableau ci-dessus expose
        # désormais toutes ses valeurs — position, orientation, faisceau — ligne
        # par ligne, ce que le pad ne faisait que pour un projecteur à la fois.
        # On le garde vivant plutôt que de le supprimer : sept méthodes
        # (_jog_spin_changed, _jog_move, _jog_flip, _sync_ry_state, l'annulation…)
        # écrivent dans ses champs. Les arracher demanderait de réécrire tout ce
        # code de synchronisation, pour ne rien gagner de visible.
        self._jog_pad = self._build_jog_pad()
        self._jog_pad.setParent(w)
        self._jog_pad.hide()

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
                p.beam_gain = 100.0
                p.beam_angle = 100.0
                p.fixture_scale = 100.0
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
            4: 'rot3d_x',
            5: 'body_rotation',   # envoyé à la 3D sous le nom rot3d_y
            6: 'rot3d_z',
            7: 'beam_gain',       # pourcentage : 100 = rendu d'origine
            8: 'beam_angle',      # pourcentage : 100 = rendu d'origine
            9: 'fixture_scale',   # pourcentage : 100 = modèle d'origine
        }
        attr = attr_map.get(col)
        if attr is None:
            return
        rows = list(self._selected_rows) if row in self._selected_rows else [row]

        # Ctrl+Z : on empile l'état AVANT modification. Un geste de glissement
        # émet des dizaines de valeurs ; on ne garde que la première, sinon la
        # pile ne contiendrait qu'un seul mouvement de souris étalé sur 50 pas.
        _key = (tuple(sorted(rows)), attr)
        if getattr(self, '_mini_undo_key', None) != _key:
            self._mini_undo_key = _key
            _def = 100.0 if attr in ('beam_gain', 'beam_angle', 'fixture_scale') else (
                7.0 if attr == 'fixture_height' else 0.0)
            # Défaut explicite : l'attribut peut ne pas exister encore sur le
            # projecteur, et restaurer None le casserait au lieu de l'annuler.
            self._push_undo([
                {'idx': r, 'attrs': {attr: (getattr(projs[r], attr, None)
                                            if getattr(projs[r], attr, None) is not None
                                            else _def)}}
                for r in rows if r < len(projs)])

        # Les cellules de position parlent en centimètres, les projecteurs en mètres.
        if attr in ('pos_3d_x', 'pos_3d_z', 'fixture_height'):
            value = float(value) / 100.0
        for r in rows:
            if r < len(projs):
                p = projs[r]
                if attr in ('pos_3d_x', 'pos_3d_z') and getattr(p, 'pos_3d_x', None) is None:
                    cx, cy = self._norm_pos(projs, r)
                    p.pos_3d_x, p.pos_3d_z = _pos3d_from_canvas(cx, cy)
                setattr(p, attr, value)
                if r != row:
                    sp = self._mini_tbl.cellWidget(r, col)
                    if sp:
                        sp.blockSignals(True)
                        sp.setValue(value * 100 if attr in (
                            'pos_3d_x', 'pos_3d_z', 'fixture_height') else value)
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
                p.pos_3d_x, p.pos_3d_z = _pos3d_from_canvas(cx, cy)

            if not self._mini_tbl.item(row, 0):
                grp  = getattr(p, 'group', '')
                name = getattr(p, 'name', '') or grp or f'#{row+1}'
                nm   = QTableWidgetItem(name[:12])
                nm.setFlags(Qt.ItemIsEnabled)
                nm.setForeground(QBrush(QColor(
                    ProjectorTableDialog._GRP_COLOR.get(grp, '#666688'))))
                self._mini_tbl.setItem(row, 0, nm)

            # Les positions passent en CENTIMÈTRES : la cellule de l'éditeur
            # d'effets est entière, et le cm est de toute façon plus parlant
            # qu'un mètre à une décimale pour placer un projecteur.
            vals  = [
                (getattr(p, 'pos_3d_x',      0.0) or 0.0) * 100,
                (getattr(p, 'pos_3d_z',      0.0) or 0.0) * 100,
                (getattr(p, 'fixture_height', 7.0) or 7.0) * 100,
                getattr(p, 'rot3d_x',       0.0) or 0.0,
                getattr(p, 'body_rotation', 0.0) or 0.0,
                getattr(p, 'rot3d_z',       0.0) or 0.0,
                getattr(p, 'beam_gain',   100.0) if getattr(p, 'beam_gain', None) is not None else 100.0,
                getattr(p, 'beam_angle',  100.0) if getattr(p, 'beam_angle', None) is not None else 100.0,
                getattr(p, 'fixture_scale', 100.0) if getattr(p, 'fixture_scale', None) is not None else 100.0,
            ]
            specs = [
                (-1200, 1200), (-800, 1000), (100, 1500),
                (-180, 180), (-180, 180), (-180, 180),
                (0, 200),
                # Minimum 10 et non 0 : à 0 le cône a un rayon nul, la géométrie
                # dégénère et le faisceau disparaît au lieu de se resserrer.
                (10, 200),
                # Taille du corps : même plancher, un appareil à 0 % disparaît
                # complètement de la scène et rien ne permettrait de le
                # retrouver pour le regrandir.
                (10, 300),
            ]
            _accent = ProjectorTableDialog._GRP_COLOR.get(
                getattr(p, 'group', ''), '#00d4ff')
            for ci, (val, (lo, hi)) in enumerate(zip(vals, specs)):
                col = ci + 1
                sp  = self._mini_tbl.cellWidget(row, col)
                if sp is None:
                    sp = _P3Cell(value=int(val), maximum=hi, minimum=lo,
                                 width=self._mini_tbl.columnWidth(col) - 4,
                                 accent=_accent, height=self._CELL_H)
                    sp.valueChanged.connect(
                        lambda v, r=row, c=col: self._mini_spin_changed(r, c, v))
                    self._mini_tbl.setCellWidget(row, col, sp)
                else:
                    sp.set_accent(_accent)
                sp.blockSignals(True)
                sp.setValue(val)
                sp.blockSignals(False)

            self._mini_tbl.setRowHeight(row, self._CELL_H + 4)

    # ── Jog pad ───────────────────────────────────────────────────────────────

    def _build_jog_pad(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame{background:#050514;border-top:1px solid #252525;}"
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
        lbl_step = QLabel(tr("p3w_step"))
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
        sep.setStyleSheet("border:none;border-top:1px solid #151515;margin:1px 0;")
        lay.addWidget(sep)

        # Rangées d'axe : [label] [−] [spinbox] [+]
        _AXIS_SP = (
            "QDoubleSpinBox{background:#111111;color:#dddddd;border:1px solid #252525;"
            "border-radius:3px;padding:1px 2px;font-size:10px;}"
            "QDoubleSpinBox::up-button,QDoubleSpinBox::down-button"
            "{background:#151515;border:none;width:12px;}"
        )
        _AXIS_LBL = (
            "color:#4a4a4a;font-size:9px;font-weight:700;"
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
        sep2.setStyleSheet("border:none;border-top:1px solid #151515;margin:1px 0;")
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

        btn_flip = QPushButton(tr("p3w_flip"))
        btn_flip.setStyleSheet(
            "QPushButton{background:#151515;color:#999999;border:1px solid #252525;"
            "border-radius:4px;font-size:10px;padding:4px;}"
            "QPushButton:hover{background:#252525;color:#dddddd;}"
            "QPushButton:pressed{background:#003d66;color:#00d4ff;}"
        )
        btn_flip.clicked.connect(self._jog_flip)
        lay.addWidget(btn_flip)

        # Lignes RY et RZ
        self._jog_ry_row = []      # widgets de la ligne RY, à estomper si inerte
        self._jog_ry_sp  = None
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

            if attr == 'body_rotation':
                self._jog_ry_row = [lbl_r, btn_m, sp_r, btn_p]
                self._jog_ry_sp  = sp_r
                self._jog_ry_lbl = lbl_r

            lay.addLayout(r_row)

        # Explication de l'inertie de RY, affichée seulement quand elle s'applique.
        self._jog_ry_hint = QLabel("")
        self._jog_ry_hint.setWordWrap(True)
        self._jog_ry_hint.setStyleSheet(
            "color:#886644;font-size:8px;background:transparent;border:none;"
            "padding:0 0 0 17px;")
        self._jog_ry_hint.setVisible(False)
        lay.addWidget(self._jog_ry_hint)

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
        self._sync_ry_state()
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
        self._sync_ry_state()
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
            p.pos_3d_x, p.pos_3d_z = _pos3d_from_canvas(cx, cy)
        setattr(p, attr, value)
        # Sync mini-table spinbox
        self._tbl_sync(idx, attr, value)
        if attr in ('pos_3d_x', 'pos_3d_z'):
            self._sync_canvas_pos(p)
        self._sync_ry_state()
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
                p.pos_3d_x, p.pos_3d_z = _pos3d_from_canvas(cx, cy)
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
            for attr in ('pos_3d_x', 'pos_3d_z', 'fixture_height'):
                self._tbl_sync(r, attr, getattr(p, attr, 0) or 0)

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

    # Correspondance attribut ↔ colonne du tableau, et attributs affichés en
    # centimètres. Défini une seule fois : trois méthodes synchronisent le
    # tableau (jog pad, déplacement au clavier, annulation) et elles doivent
    # rester d'accord — c'est en les laissant diverger qu'une colonne cessait
    # d'être rafraîchie.
    # Hauteur des cellules du tableau. Volontairement plus compacte que dans
    # l'éditeur d'effets (42 px) : ici les lignes sont nombreuses — un
    # projecteur chacune — et c'est le nombre de lignes visibles d'un coup qui
    # compte, pas la place pour un aperçu graphique.
    _CELL_H = 24

    _TBL_COL = {'pos_3d_x': 1, 'pos_3d_z': 2, 'fixture_height': 3,
                'rot3d_x': 4, 'body_rotation': 5, 'rot3d_z': 6, 'beam_gain': 7,
                'beam_angle': 8, 'fixture_scale': 9}
    _TBL_CM  = ('pos_3d_x', 'pos_3d_z', 'fixture_height')

    def _tbl_sync(self, row, attr, value):
        """Réaffiche une cellule sans déclencher son signal."""
        col = self._TBL_COL.get(attr)
        if col is None:
            return
        sp = self._mini_tbl.cellWidget(row, col)
        if sp is None:
            return
        v = 0.0 if value is None else float(value)
        sp.blockSignals(True)
        sp.setValue(v * 100 if attr in self._TBL_CM else v)
        sp.blockSignals(False)

    _UNDO_MAX = 50

    def _push_undo(self, steps: list):
        """steps: liste de {'idx': int, 'attrs': dict}"""
        if len(self._undo_stack) >= self._UNDO_MAX:
            self._undo_stack.pop(0)
        self._undo_stack.append(steps)

    def _undo(self):
        # Le prochain réglage devra ré-empiler : sans ça, modifier de nouveau
        # la même case après un Ctrl+Z passerait pour la suite du même geste et
        # ne serait plus annulable.
        self._mini_undo_key = None
        if not self._undo_stack:
            return
        steps = self._undo_stack.pop()
        projs = self._last_projectors
        if not projs:
            return

        for step in steps:
            idx = step['idx']
            if idx >= len(projs):
                continue
            p = projs[idx]
            for attr, val in step['attrs'].items():
                setattr(p, attr, val)
            self._sync_canvas_pos(p)
            for attr in step['attrs']:
                self._tbl_sync(idx, attr, getattr(p, attr, None))
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
        # La vue web avale les touches dès qu'elle a le focus — c'est-à-dire dès
        # qu'on a orbité dans la 3D, donc la plupart du temps. Tout raccourci
        # doit être traité ICI en plus de keyPressEvent, sinon il ne répond
        # qu'une fois sur deux selon l'endroit où on a cliqué en dernier.
        if obj is self._view and event.type() == QEvent.KeyPress:
            if (event.modifiers() == Qt.ControlModifier
                    and event.key() == Qt.Key_Z):
                self._undo()
                return True
            if event.key() == Qt.Key_Escape:
                self.clear_selection()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Z:
            self._undo()
        elif event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_A:
            # Tout sélectionner. Il fallait jusqu'ici Ctrl+cliquer chaque ligne
            # une par une — sur un rig de 40 projecteurs, la sélection multiple
            # était théorique.
            self._select_all_rows()
        elif event.key() == Qt.Key_Escape:
            # Échap éteint le repérage — la touche ne servait à rien jusqu'ici
            # (QMainWindow, donc pas de reject() comme sur un QDialog).
            self.clear_selection()
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
            p.canvas_x = _canvas_from_pos3d(p.pos_3d_x, 0.0)[0]
        if getattr(p, 'pos_3d_z', None) is not None:
            p.canvas_y = _canvas_from_pos3d(0.0, p.pos_3d_z)[1]
        mw = self._parent_mw
        if mw and hasattr(mw, 'plan_de_feu'):
            mw.plan_de_feu.update()

    def _mini_tbl_set_highlight(self, row: int, on: bool):
        """Surligne toute la ligne d'un projecteur.

        Le nom prend un fond cyan sombre, et CHAQUE cellule chiffrée reçoit un
        liseré cyan. L'ancienne version ne traitait que les colonnes 1 à 3 et
        passait par une feuille de style — sans effet sur des cellules peintes
        au QPainter : la sélection ne se voyait donc quasiment pas.
        """
        it = self._mini_tbl.item(row, 0)
        if it:
            it.setBackground(QBrush(QColor('#00303d') if on else QColor('#0d0d0d')))
            it.setForeground(QBrush(QColor('#00d4ff') if on else QColor(
                ProjectorTableDialog._GRP_COLOR.get(
                    getattr(self._last_projectors[row], 'group', ''), '#666688')
                if row < len(self._last_projectors) else '#666688')))
        for col in range(1, self._mini_tbl.columnCount()):
            sp = self._mini_tbl.cellWidget(row, col)
            if sp is not None and hasattr(sp, 'set_row_selected'):
                sp.set_row_selected(on)

    # ── Sélection (simple et multi Ctrl+clic) ────────────────────────────────

    def _on_mini_tbl_clicked(self, row: int, col: int):
        from PySide6.QtWidgets import QApplication
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        if ctrl:
            self._toggle_select(row)
        else:
            self._on_projo_selected(row)

    def clear_selection(self):
        """Éteint le repérage : plus aucun projecteur surligné, en 3D ni au tableau.

        Il n'existait aucun moyen d'en sortir. Une fois un faisceau repéré, il
        le restait : quitter l'onglet Plan masquait le tableau — donc le seul
        endroit d'où désélectionner — et Échap n'était traité nulle part (ni
        `keyPressEvent`, qui ne connaissait que Ctrl+Z, ni la page web). Le
        repérage restait donc allumé en travers du plan de feu, sans issue."""
        if not self._selected_rows and self._highlighted_row < 0:
            return
        lignes = set(self._selected_rows)
        if self._highlighted_row >= 0:
            lignes.add(self._highlighted_row)      # primaire pas toujours dans le lot
        for r in lignes:
            self._mini_tbl_set_highlight(r, False)
        self._selected_rows.clear()
        self._highlighted_row = -1
        self._push_selection_3d()
        self._maj_bandeau_multi()

    def _on_right_tab_changed(self, index: int):
        """Quitter l'onglet Plan coupe le repérage.

        Le tableau est le seul pilote de cette sélection : le laisser actif
        alors qu'il n'est plus à l'écran laisse un faisceau marqué que plus rien
        ne commande."""
        if self._right_tabs is not None and self._right_tabs.tabText(index) != "Plan":
            self.clear_selection()

    def _select_all_rows(self):
        """Ctrl+A : retient toutes les lignes du tableau (ou vide la sélection).

        Bascule volontairement : sur un rig entièrement sélectionné, Ctrl+A
        redonne une table vierge sans avoir à viser la touche Échap.
        """
        total = self._mini_tbl.rowCount()
        if total and len(self._selected_rows) >= total:
            self.clear_selection()
            self._maj_bandeau_multi()
            return
        for r in range(total):
            self._selected_rows.add(r)
            self._mini_tbl_set_highlight(r, True)
        if total:
            self._highlighted_row = 0
        self._push_selection_3d()
        self._update_jog_pad_from_primary()
        self._maj_bandeau_multi()

    def _maj_bandeau_multi(self):
        """Le bandeau de l'onglet Plan devient un compteur dès qu'on sélectionne."""
        lbl = getattr(self, '_lbl_multi', None)
        if lbl is None:
            return
        n = len(self._selected_rows)
        if n > 1:
            lbl.setText(tr("p3w_sel_many", n=n))
            lbl.setStyleSheet("color:#00d4ff;font-size:9px;padding:3px 4px;"
                              "border-top:1px solid #1c1c1c;")
        else:
            lbl.setText(tr("p3w_plan_multi_hint"))
            lbl.setStyleSheet("color:#556;font-size:9px;padding:3px 4px;"
                              "border-top:1px solid #1c1c1c;")

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
        self._push_selection_3d()
        self._update_jog_pad_from_primary()
        self._maj_bandeau_multi()

    def _push_selection_3d(self):
        """Envoie la sélection complète à la vue 3D.

        `highlightProjo` ne connaît qu'un projecteur — le primaire, celui dont
        le corps est surligné. Il faut donc lui adjoindre l'ensemble, sinon un
        Ctrl+clic n'allumait en blanc que le dernier cliqué.
        L'ordre compte : highlightProjo réduit la sélection à ce seul index.
        """
        self._js(f'if(window.highlightProjo)window.highlightProjo({self._highlighted_row})')
        rows = sorted(r for r in self._selected_rows if r >= 0)
        self._js('if(window.setSelectedProjos)'
                 f'window.setSelectedProjos({json.dumps(rows)})')

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
        self._sync_ry_state()

    def _sync_ry_state(self):
        """Signale quand RY ne peut rien faire au faisceau.

        Le calcul du faisceau (beamFloor, plan_3d_web.html) donne
        bx = sin(RY)·sin(RX) et bz = cos(RY)·sin(RX) : RY n'y intervient que
        MULTIPLIÉ par sin(RX). Tilt à 0 → le faisceau descend à la verticale et
        aucune valeur de RY ne le déplace, alors que le corps du projecteur,
        lui, pivote bien à l'écran. D'où l'impression que « le faisceau reste
        bloqué ». On ne bride pas la commande (régler RY avant d'incliner reste
        légitime), on dit juste pourquoi il ne se passe rien.

        Cas de la lyre : RY oriente le PIED (l'accroche), et le Pan DMX balaie
        par-dessus — les deux angles s'additionnent sur mhGrp.rotation.y. Elle
        n'est donc plus inerte. Seule subsiste la réserve du faisceau vertical :
        tilt au nadir, la tache ne bouge pas même si le corps pivote.
        """
        if not getattr(self, '_jog_ry_row', None):
            return
        idx   = self._highlighted_row
        projs = self._last_projectors
        p     = projs[idx] if (projs and 0 <= idx < len(projs)) else None

        if p is None:
            inerte, court, long_ = False, "", ""
        elif getattr(p, 'fixture_type', '') == 'Moving Head':
            inerte = False
            court  = ""
            long_  = ("RY oriente le PIED de la lyre (son accroche).\n"
                      "Le Pan DMX balaie ensuite à partir de cette orientation :\n"
                      "les deux angles s'additionnent, comme sur le vrai appareil.\n\n"
                      "Utile pour accrocher des lyres sur les faces d'une structure\n"
                      "orientée (tour, portique biais) sans qu'elles regardent\n"
                      "toutes dans la même direction.")
        elif abs(float(getattr(p, 'rot3d_x', 0.0) or 0.0)) < 0.05:
            inerte = True
            court  = "Faisceau à la verticale : inclinez avec RX pour que RY le déplace."
            long_  = ("Le faisceau vise le sol à la verticale : le faire pivoter\n"
                      "autour de son propre axe ne déplace pas la tache.\n\n"
                      "Inclinez d'abord avec RX — RY balaiera alors la salle.")
        else:
            inerte, court, long_ = False, "", ""

        for w in self._jog_ry_row:
            w.setToolTip(long_)
        self._jog_ry_lbl.setStyleSheet(
            ("color:#886644;" if inerte else "color:#4a4a4a;")
            + "font-size:9px;font-weight:700;background:transparent;"
              "border:none;min-width:14px;")
        self._jog_ry_hint.setText(court)
        self._jog_ry_hint.setVisible(inerte)

    def _on_projo_selected(self, index: int):
        """Sélection simple (depuis la table ou depuis le clic 3D)."""
        for r in self._selected_rows:
            self._mini_tbl_set_highlight(r, False)
        self._selected_rows = {index} if index >= 0 else set()
        self._highlighted_row = index

        self._push_selection_3d()

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
        w.setStyleSheet("background:#0d0d0d;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(4)

        self._scene_btns = {}
        # Liste construite depuis _SCENE_PRESETS, et non recopiee a la main :
        # les deux etaient tenues separement, si bien qu'une scene ajoutee au
        # dictionnaire n'apparaissait nulle part dans le panneau.
        for code, label in [(c, p['label']) for c, p in _SCENE_PRESETS.items()]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(code == 'live')
            btn.setStyleSheet(self._PANEL_BTN)
            btn.setToolTip(tr("p3w_stage_preset", a0=_SCENE_PRESETS[code]['label']))
            btn.clicked.connect(lambda _, c=code: self._apply_preset(c))
            lay.addWidget(btn)
            self._scene_btns[code] = btn

        # ── Brouillard ────────────────────────────────────────────────────
        # Module la densité de fumée DANS les faisceaux (bruit 3D animé en
        # coordonnées monde). À 0 %, la branche du shader n'est jamais prise :
        # aucun surcoût pour qui n'en veut pas.
        lbl_fog = QLabel(tr("p3w_fog"))
        lbl_fog.setStyleSheet("color:#4444aa;font-size:9px;letter-spacing:0.5px;")
        lay.addWidget(lbl_fog)

        self._fog_val_lbl = QLabel("0%")
        self._fog_val_lbl.setStyleSheet("color:#7777cc;font-size:9px;")
        self._fog_val_lbl.setAlignment(Qt.AlignRight)
        lay.addWidget(self._fog_val_lbl)

        sl_fog = QSlider(Qt.Horizontal)
        sl_fog.setRange(0, 100)
        sl_fog.setValue(getattr(self, '_fog', 0))
        sl_fog.setPageStep(10)
        sl_fog.setToolTip(tr("p3w_fog_amount_hint"))
        sl_fog.setStyleSheet(self._SLIDER_QSS)
        self._sl_fog = sl_fog

        sl_gr = QSlider(Qt.Horizontal)      # finesse des volutes

        def _on_fog(v):
            self._fog_val_lbl.setText(f"{v}%")
            self._fog = int(v)
            self._js(f'window.setFog && window.setFog({v})')
            # Finesse et vitesse ne se règlent que s'il y a de la fumée à régler.
            # (définis plus bas : _on_fog n'est appelé qu'en fin de construction)
            for _w in (sl_gr, lbl_gr, sl_vit, lbl_vit):
                _w.setEnabled(v > 0)

        sl_fog.valueChanged.connect(_on_fog)
        sl_fog.sliderReleased.connect(self._save_patch)
        lay.addWidget(sl_fog)

        lbl_gr = QLabel(tr("p3w_fog_detail"))
        lbl_gr.setStyleSheet("color:#3a3a88;font-size:9px;letter-spacing:0.5px;")
        lay.addWidget(lbl_gr)

        # 15..200 → 0,15..2,0 m⁻¹ : nappes larges à gauche, fumée nerveuse à droite
        sl_gr.setRange(15, 200)
        sl_gr.setValue(getattr(self, '_fog_scale', 55))
        sl_gr.setPageStep(20)
        sl_gr.setToolTip(tr("p3w_fog_hint"))
        sl_gr.setStyleSheet(self._SLIDER_QSS)

        def _on_fog_scale(v):
            self._fog_scale = int(v)
            self._js(f'window.setFogScale && window.setFogScale({v/100:.2f})')

        sl_gr.valueChanged.connect(_on_fog_scale)
        sl_gr.sliderReleased.connect(self._save_patch)
        lay.addWidget(sl_gr)
        self._sl_fog_scale = sl_gr

        lbl_vit = QLabel(tr("p3w_fog_speed"))
        lbl_vit.setStyleSheet("color:#3a3a88;font-size:9px;letter-spacing:0.5px;")
        lay.addWidget(lbl_vit)

        sl_vit = QSlider(Qt.Horizontal)
        sl_vit.setRange(0, 100)
        sl_vit.setValue(getattr(self, '_fog_speed', 35))
        sl_vit.setPageStep(10)
        sl_vit.setToolTip(
            tr("p3w_fog_speed_hint")
        )
        sl_vit.setStyleSheet(self._SLIDER_QSS)

        def _on_fog_speed(v):
            self._fog_speed = int(v)
            self._js(f'window.setFogSpeed && window.setFogSpeed({v})')

        sl_vit.valueChanged.connect(_on_fog_speed)
        sl_vit.sliderReleased.connect(self._save_patch)
        lay.addWidget(sl_vit)
        self._sl_fog_speed = sl_vit

        _on_fog_scale(sl_gr.value())
        _on_fog_speed(sl_vit.value())
        _on_fog(sl_fog.value())          # applique l'état mémorisé (et grise si 0)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        self._btn_trusses = QPushButton()  # kept for _apply_preset compat, not displayed
        sep.setStyleSheet("border:none;border-top:1px solid #252525;margin:6px 0;")
        lay.addWidget(sep)

        lbl = QLabel(tr("p3w_import_scene"))
        lbl.setStyleSheet(
            "color:#4a4a4a;font-size:8px;letter-spacing:1.2px;font-weight:700;")
        lay.addWidget(lbl)

        btn_gltf = QPushButton("↓  GLTF / GLB")
        btn_gltf.setStyleSheet(self._PANEL_BTN)
        btn_gltf.setToolTip(
            tr("p3w_import_hint"))
        btn_gltf.clicked.connect(self._import_scene)
        lay.addWidget(btn_gltf)

        btn_clear = QPushButton(tr("p3w_clear_import"))
        btn_clear.setStyleSheet(self._PANEL_BTN)
        btn_clear.clicked.connect(self._clear_import)
        lay.addWidget(btn_clear)

        lay.addStretch()
        return w

    def _import_scene(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer une scène 3D", "",
            "Fichiers 3D (*.gltf *.glb);;glTF JSON (*.gltf);;GLB binaire (*.glb)"
        )
        if not path:
            return
        if self._push_model(path):
            self._imported_path = path
            self._save_patch()

    def _push_model(self, path: str) -> bool:
        """Envoie un GLTF/GLB à la vue. False si le fichier est illisible."""
        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except OSError:
            return False
        b64 = base64.b64encode(raw).decode('ascii')
        is_glb = path.lower().endswith('.glb')
        self._js(f'if(window.loadGLTF)window.loadGLTF("{b64}",{str(is_glb).lower()})')
        return True

    def _clear_import(self):
        """Efface le décor importé — définitivement.

        Le bouton ne vidait que le groupe 3D de la page. Le chemin restait
        dans `_imported_path`, donc réécrit dans le patch, et
        `_restore_imported_model()` le rechargeait à l'ouverture suivante :
        le décor revenait indéfiniment malgré l'effacement.
        """
        self._js('if(window.clearImportedScene)window.clearImportedScene()')
        self._imported_path = ''
        self._save_patch()

    def _push_cyclorama(self, preset: dict, code: str):
        """Allume ou éteint le fond de scène selon le décor.

        Toujours appelé, et APRÈS `setStageFloor` qui le rallume sans condition.
        """
        on = bool(preset.get('cyc', True)) and code != 'vide'
        self._js(f'if(window.setCyclorama)window.setCyclorama({str(on).lower()})')

    def _push_scene_glb(self, preset: dict):
        """Envoie (ou retire) le décor 3D livré avec une scène par défaut.

        Toujours appelé, y compris pour les scènes sans modèle : c'est ce qui
        retire le décor de la scène précédente. Sans cet appel systématique, la
        scène de concert restait affichée sous le rig de la scène suivante.
        Le décor importé à la main par l'utilisateur n'est pas concerné, il vit
        dans un autre groupe.
        """
        nom = preset.get('glb')
        if not nom:
            self._js('if(window.clearSceneGLB)window.clearSceneGLB()')
            return
        chemin = _DOSSIER_SCENES / nom
        try:
            b64 = base64.b64encode(chemin.read_bytes()).decode('ascii')
        except OSError as exc:
            print(f"[3D] décor de scène introuvable ({chemin}) : {exc}")
            self._js('if(window.clearSceneGLB)window.clearSceneGLB()')
            return
        yaw  = float(preset.get('yaw', 0.0))
        span = float(preset.get('span', 18.0))
        self._js(f'if(window.loadSceneGLB)window.loadSceneGLB("{b64}",{yaw},{span})')

    def _restore_scene_glb(self):
        """Recharge le décor de la scène courante quand la page est prête."""
        preset = _SCENE_PRESETS.get(getattr(self, '_scene_preset_code', ''), None)
        if preset:
            self._push_scene_glb(preset)

    def _restore_imported_model(self):
        """Recharge le décor importé mémorisé (appelé quand la page est prête).

        Le fichier peut avoir été déplacé/supprimé depuis : on oublie alors la
        référence plutôt que de la traîner indéfiniment.
        """
        path = getattr(self, '_imported_path', '')
        if not path:
            return
        if not self._push_model(path):
            self._imported_path = ''

    # ── Truss Editor ─────────────────────────────────────────────────────────

    def _apply_preset(self, code: str):
        preset = _SCENE_PRESETS.get(code)
        if not preset:
            return
        self._scene_preset_code = code
        self._trusses = [t.copy() for t in preset['trusses']]
        self._js(f"window.setScenePreset('{code}')")
        self._js(f'if(window.setStageFloor)window.setStageFloor({str(code != "vide").lower()})')
        self._push_cyclorama(preset, code)
        self._push_scene_glb(preset)
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

    _render_crashes = 0

    def _on_render_crashed(self, status, exit_code):
        """Appelé quand le process de rendu WebEngine crashe ou est tué.

        La page était rechargée en silence : à l'écran, le plan 3D disparaît
        puis revient — un « glitch » inexplicable et introuvable dans les logs.
        On le trace désormais, avec un compteur : un incident isolé est bénin,
        des plantages répétés désignent le pilote graphique ou la scène.
        """
        self._ready = False
        Plan3DWebWindow._render_crashes += 1
        _diag_note(f"Le rendu 3D a planté (statut={status}, code={exit_code}) "
                   f"— rechargement automatique. Incident n°{self._render_crashes} "
                   f"depuis le lancement.")
        if self._render_crashes >= 3:
            _diag_note("Plantages répétés : pilote graphique probablement en cause. "
                       "Baisser la qualité de rendu (onglet Cam.) réduit la charge GPU.")
        # Recharger la page après un court délai pour laisser le crash se nettoyer
        QTimer.singleShot(800, lambda: self._view.load(QUrl.fromLocalFile(str(_HTML))))

    def _on_load_finished(self, ok: bool):
        self._ready = ok
        if ok:
            # Restaurer le preset de scène (décors 3D + trusses du preset)
            self._js(f"window.setScenePreset('{self._scene_preset_code}')")
            self._js('if(window.setStageFloor)window.setStageFloor('
                     f'{str(self._scene_preset_code != "vide").lower()})')
            # Après `setStageFloor`, qui rallume le cyclorama sans condition :
            # sans ce rappel, le fond de scène revenait couper le décor au
            # premier rechargement de la page.
            _p = _SCENE_PRESETS.get(self._scene_preset_code)
            if _p:
                self._push_cyclorama(_p, self._scene_preset_code)
            # Puis appliquer les trusses réellement configurés (peuvent différer du preset)
            self._js(f'window.setTrusses({json.dumps(self._trusses)})')
            # Décor de la scène courante : page neuve = _sceneGrp vide, il faut
            # le repousser, sinon la scène choisie revient sans son modèle.
            self._restore_scene_glb()
            # Décor importé mémorisé : le recharger (page neuve = _importedGrp vide)
            self._restore_imported_model()
            amb = getattr(self, '_sl_amb', None)
            if amb is None:
                self._js('window.setRoomAmbience && '
                         f'window.setRoomAmbience({getattr(self, "_ambience", 160)/200:.3f})')
            if amb:
                # Même formule que le curseur : cette ligne ne rétablissait que
                # l'AmbientLight, à l'ancienne échelle. Au moindre rechargement
                # de page (changement de preset, décor importé), le réglage
                # d'ambiance retombait donc silencieusement à sa version faible.
                self._js('window.setRoomAmbience && '
                         f'window.setRoomAmbience({amb.value()/200:.3f})')
            # Même piège que l'ambiance juste au-dessus : sans ce rappel, le
            # brouillard retombe à 0 au moindre rechargement de page
            # (changement de preset, import de décor…), sans rien dire.
            self._js('window.setFogScale && '
                     f'window.setFogScale({getattr(self, "_fog_scale", 55)/100:.2f})')
            self._js('window.setFogSpeed && '
                     f'window.setFogSpeed({int(getattr(self, "_fog_speed", 35))})')
            self._js(f'window.setFog && window.setFog({int(getattr(self, "_fog", 0))})')
            self._js('if(window.setBloom)window.setBloom(0.0)')
            self._js('window.beamScale=0.5')
            # Qualité de rendu des faisceaux volumétriques
            self._js(f'window.autoQuality = {str(bool(self._auto_quality)).lower()}')
            self._js(f'if(window.setQuality)window.setQuality({int(self._quality)})')
            if getattr(self, '_chk_fps', None) and self._chk_fps.isChecked():
                self._js('window.showFps && window.showFps(true)')
            if self._pending is not None:
                self._do_push()

    # ── Conversion projecteurs → JSON ─────────────────────────────────────────

    def _rig_height(self):
        """Hauteur d'accroche par défaut, selon le décor affiché.

        Un projecteur sans `fixture_height` explicite retombait toujours sur
        `TRUSS_Y` (7 m), la hauteur des trusses dessinés par les presets. Sur un
        décor livré en modèle 3D, le grill est là où le modèle l'a mis — celui de
        la scène de concert est à 9,3 m — et tout le rig flottait 2 m en dessous
        au lieu d'être accroché. La valeur reste surchargeable projecteur par
        projecteur : elle ne sert que de défaut.
        """
        preset = _SCENE_PRESETS.get(getattr(self, '_scene_preset_code', ''), None)
        if preset:
            return float(preset.get('rig_height', TRUSS_Y))
        return TRUSS_Y

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
        fx  = self._fx_overrides or {}
        for i, p in enumerate(projectors):
            # Sortie live de l'éditeur d'effets : elle prime sur l'état du
            # projecteur, que le moteur DMX a déjà restauré à ce stade.
            ov   = fx.get(id(p))
            # Canaux couleur repris à la main dans la vue « Curseurs » du plan
            # de feu : ils ne passent plus par `p.color`, et sur un PAR sans
            # canal Dim le niveau du modèle reste à 0 — la fixture serait restée
            # noire ici alors qu'elle éclaire. Même recomposition qu'en 2D
            # (`PlanDeFeuCanvas._get_fill_color`). La sortie live de l'éditeur
            # d'effets garde la priorité, et une fixture mutée ne sort rien.
            _repris = None
            if ov is None and not getattr(p, 'muted', False) \
                    and hasattr(p, 'display_color_override'):
                _repris = p.display_color_override()
                if _repris is not None and not (_repris.red() or _repris.green()
                                                or _repris.blue()):
                    _repris = None
            if _repris is not None:
                col = _repris
            else:
                col = QColor(ov[1]) if ov is not None else getattr(p, 'color', None)
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
            # Le plan de feu 2D reste maître d'une position 3D qui en a été
            # déduite : sans ce recalage, une fixture déplacée sur le plan (ou
            # changée de groupe dans le patch) gardait sa place d'avant en 3D.
            _sync_pos3d_with_canvas(p, cx, cy)
            p3x = getattr(p, 'pos_3d_x', None)
            p3z = getattr(p, 'pos_3d_z', None)
            _dx, _dz = _pos3d_from_canvas(cx, cy)
            x_w = p3x if p3x is not None else _dx
            z_w = p3z if p3z is not None else _dz
            # L'éditeur d'effets travaille en niveau 0..1 (convention du plan de
            # feu 2D), la 3D attend l'échelle du projecteur, 0..100.
            if ov is not None:
                lvl = int(round(max(0.0, min(1.0, ov[0])) * 100))
            elif _repris is not None and int(getattr(p, 'level', 0)) == 0:
                # Fixture pilotée uniquement par des canaux repris : sans canal
                # Dim, son niveau vaut 0 en permanence et le faisceau serait
                # resté éteint. C'est la couleur qui porte l'intensité.
                lvl = int(round(max(r, g, b) / 255 * 100))
            else:
                lvl = int(getattr(p, 'level', 0))
            pan_v  = getattr(p, 'pan',  32768)
            tilt_v = getattr(p, 'tilt', 32768)
            if ov is not None and len(ov) > 3:
                if ov[2] is not None:
                    pan_v = ov[2]
                if ov[3] is not None:
                    tilt_v = ov[3]
            out.append({
                'level':          lvl,
                'r': r, 'g': g, 'b': b,
                'x':              x_w,
                'z':              z_w,
                'pan':            pan_v,
                'tilt':           tilt_v,
                'fixture_type':   getattr(p, 'fixture_type', 'PAR LED'),
                'fixture_height': fh if fh is not None else self._rig_height(),
                'body_rotation':  getattr(p, 'body_rotation', 0.0),
                'rot3d_x':        getattr(p, 'rot3d_x', 0.0),
                'rot3d_y':        getattr(p, 'body_rotation', 0.0),
                # Puissance de faisceau par projecteur (%) → facteur 0..2
                'beam_gain':      float(getattr(p, 'beam_gain', 100.0) or 0.0) / 100.0,
                # Ouverture de faisceau par projecteur (%) → facteur 0,1..2.
                # `or` refuserait 0 mais laisserait passer None ; le plancher
                # est repris ici pour qu'un patch ancien ou bidouillé à la main
                # ne puisse pas envoyer un cône de rayon nul à la 3D.
                'beam_angle':     max(0.1, float(getattr(p, 'beam_angle', 100.0) or 100.0) / 100.0),
                # Taille du corps (%) → facteur 0,1..3. Même plancher que
                # l'ouverture, pour la même raison : un facteur nul escamote
                # l'appareil sans moyen de le récupérer depuis la 3D.
                'fixture_scale':  max(0.1, float(getattr(p, 'fixture_scale', 100.0) or 100.0) / 100.0),
                'rot3d_z':        getattr(p, 'rot3d_z', 0.0),
                'name':           getattr(p, 'name', ''),
                'group':          getattr(p, 'group', ''),
                'gobo':           int(getattr(p, 'gobo', 0) or 0),
                'gobo_rotation':  int(getattr(p, 'gobo_rotation', 0) or 0),
                'prism':          int(getattr(p, 'prism', 0) or 0),
                'prism_rotation': int(getattr(p, 'prism_rotation', 0) or 0),
                'matrix_id':      getattr(p, 'matrix_id', None),
                'matrix_role':    getattr(p, 'matrix_role', None),
                # Zoom : largeur de faisceau pilotée par DMX. `has_zoom` évite
                # de rétrécir les projos SANS canal zoom (dont zoom=0 en
                # permanence). Le zoom manuel passe par channel_extras['Zoom']
                # (canal avancé), pas proj.zoom — mêmes priorités que l'Art-Net,
                # sinon un changement de zoom manuel ne se voyait pas en 3D.
                'zoom':           int((getattr(p, 'channel_extras', None) or {}).get(
                                       'Zoom', getattr(p, 'zoom', 0)) or 0),
                'has_zoom':       'Zoom' in (getattr(p, 'dmx_profile', None) or []),
                # Focus : même logique que le zoom, la valeur vit dans les
                # canaux bruts (curseur « Focus » des canaux avancés).
                # Sans canal Focus, l'appareil est mis au point une fois pour
                # toutes sur le plateau → la 3D le rend net, plutôt que de
                # laisser un gobo flou que rien ne permettrait de régler.
                'has_focus':      'Focus' in (getattr(p, 'dmx_profile', None) or []),
                'focus':          int((getattr(p, 'channel_extras', None) or {}).get(
                                       'Focus', getattr(p, 'focus', 0)) or 0),
            })
        # Barres/matrices : rendu PER-PIXEL. Chaque pixel garde sa couleur, son
        # niveau et sa position → un chase se VOIT courir le long de la barre.
        # On ne dessine pas une lyre/PAR complet par pixel (16 corps + 16
        # faisceaux = lourd et absurde), mais une petite cellule lumineuse
        # (drapeau `is_pixel`). Le master (canaux globaux) n'a pas de forme :
        # `is_master`, non dessiné.
        import math as _m
        groups = {}
        for i, e in enumerate(out):
            role = e.get('matrix_role')
            if role == 'pixel':
                e['is_pixel'] = True
            elif role == 'master':
                e['is_master'] = True
            mid = e.get('matrix_id')
            if mid is not None:
                groups.setdefault(mid, []).append(i)

        # Boîtier physique de l'appareil : sans lui, les pixels flottants se
        # lisent comme un « rectangle coloré » abstrait, pas comme une barre.
        # On attache au représentant (1er membre) la géométrie d'une réglette
        # sombre reliant les pixels : centre, longueur, angle dans le plan XZ.
        for mid, idxs in groups.items():
            pix = [out[i] for i in idxs if out[i].get('is_pixel')] or \
                  [out[i] for i in idxs]
            if not pix:
                continue
            xs = [p['x'] for p in pix]
            zs = [p['z'] for p in pix]
            cx = sum(xs) / len(pix)
            cz = sum(zs) / len(pix)
            # Direction = extrêmes du bloc ; longueur = diagonale + marge pixel
            dx = max(xs) - min(xs)
            dz = max(zs) - min(zs)
            length = _m.hypot(dx, dz) + 0.18
            angle = _m.atan2(dz, dx) if (dx or dz) else 0.0
            out[idxs[0]]['housing'] = {
                'cx': cx, 'cz': cz, 'len': length, 'angle': angle,
            }
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

    def set_fx_overrides(self, overrides):
        """Sortie live de l'éditeur d'effets : {id(proj): (level 0-1, QColor, pan, tilt)}.

        Passée en DONNÉE, et surtout pas en appliquant les valeurs sur les
        projecteurs : `refresh()` ne fait qu'armer un timer de 40 ms, et
        `_to_data()` relit les objets à l'expiration — bien après que la boucle
        DMX ait restauré leur état. Une frame appliquée puis restaurée autour de
        `refresh()` n'arriverait donc jamais jusqu'ici.

        None coupe le miroir et redonne la main à l'état réel des projecteurs.
        """
        if overrides is None and self._fx_overrides is None:
            return
        self._fx_overrides = overrides
        if self._last_projectors:
            self.refresh(self._last_projectors)

    def set_trusses(self, trusses):
        """Met à jour la configuration des trusses."""
        self._trusses = trusses
        self._js(f'window.setTrusses({json.dumps(trusses)})')

    def force_close(self):
        """Fermeture réelle, appelée quand l'application se termine.

        La fenêtre n'a pas de parent Qt (cf. __init__) et son closeEvent se
        contente de masquer : à l'arrêt de MyStrow elle restait donc affichée,
        épinglée par-dessus tout, et maintenait le processus en vie —
        `quitOnLastWindowClosed` ne se déclenche que sur une vraie fermeture,
        jamais sur un hide().
        """
        self._pinned = False
        try:
            self._apply_on_top(False)
        except Exception:
            pass
        self._force_close = True
        self.close()

    def closeEvent(self, event):
        if getattr(self, '_force_close', False):
            for _t in ('_push_timer', '_strobe_timer'):
                try:
                    getattr(self, _t).stop()
                except Exception:
                    pass
            event.accept()
            return

        # Fermeture par l'utilisateur : on masque pour garder la scène chargée.
        # On désépingle d'abord, sinon la fenêtre suivante à s'ouvrir hérite
        # d'un topmost fantôme au ré-affichage.
        if getattr(self, '_pinned', False):
            try:
                self._apply_on_top(False)
            except Exception:
                pass
        event.ignore()
        self.hide()
        try:
            mw = self._parent_mw
            if mw and hasattr(mw, 'plan_de_feu') and hasattr(mw.plan_de_feu, 'btn_3d'):
                mw.plan_de_feu.btn_3d.setChecked(False)
        except RuntimeError:
            pass    # fenêtre principale déjà détruite côté C++
