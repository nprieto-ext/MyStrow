"""
Sequenceur - Gestion de la playlist et des sequences lumiere
"""
import os
import sys
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QMenu, QComboBox, QFileDialog, QMessageBox, QDialog, QSlider, QSpinBox,
    QStackedWidget, QProgressBar, QColorDialog, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QMimeData
from PySide6.QtGui import QDesktopServices
from PySide6.QtGui import QColor, QFont, QBrush, QCursor, QDrag
try:
    from PySide6.QtMultimedia import QMediaPlayer
except ImportError:
    class QMediaPlayer:  # type: ignore
        PlayingState = 1; StoppedState = 0; PausedState = 2; EndOfMedia = 7
        def __init__(self): pass
        def setAudioOutput(self, *a): pass
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

from core import fmt_time, media_icon, MIDI_AVAILABLE, rgb_to_akai_velocity, MEDIA_EXTENSIONS_FILTER
from i18n import tr


class LoopMidiHelper:
    """Détection et configuration du port MIDI virtuel loopMIDI."""

    KNOWN_PATHS = [
        r"C:\Program Files (x86)\Tobias Erichsen\loopMIDI\loopMIDI.exe",
        r"C:\Program Files\Tobias Erichsen\loopMIDI\loopMIDI.exe",
    ]
    PORT_NAME    = "MyStrow"
    DOWNLOAD_URL = "https://www.tobias-erichsen.de/software/loopmidi.html"

    @classmethod
    def install_path(cls):
        for p in cls.KNOWN_PATHS:
            if os.path.exists(p):
                return p
        return None

    @classmethod
    def is_installed(cls):
        return cls.install_path() is not None

    @classmethod
    def has_port(cls):
        """Vérifie si le port MyStrow est visible dans les ports MIDI actifs."""
        try:
            import rtmidi as _rm
            return any(cls.PORT_NAME.lower() in p.lower()
                       for p in _rm.MidiIn().get_ports())
        except Exception:
            pass
        try:
            import rtmidi2 as _rm2
            return any(cls.PORT_NAME.lower() in p.lower()
                       for p in _rm2.get_in_ports())
        except Exception:
            pass
        return False

    @classmethod
    def create_port(cls):
        """Tente de créer le port MyStrow. Retourne (ok: bool, message: str)."""
        # Essai 1 : API COM (loopMIDI doit être en cours)
        try:
            import win32com.client
            app = win32com.client.Dispatch("loopMIDI.Application")
            existing = [app.getPort(i) for i in range(app.getPortCount())]
            if cls.PORT_NAME not in existing:
                app.addPort(cls.PORT_NAME)
            return True, f'Port "{cls.PORT_NAME}" créé via COM'
        except Exception:
            pass

        # Essai 2 : config XML + (re)lancer loopMIDI
        try:
            cfg_dir  = os.path.join(os.environ.get('APPDATA', ''), 'loopMIDI')
            cfg_path = os.path.join(cfg_dir, 'loopMIDI.xml')
            os.makedirs(cfg_dir, exist_ok=True)

            if os.path.exists(cfg_path):
                tree = ET.parse(cfg_path)
                root = tree.getroot()
            else:
                root = ET.Element('loopMIDI')
                tree = ET.ElementTree(root)

            ports_el = root.find('Ports')
            if ports_el is None:
                ports_el = ET.SubElement(root, 'Ports')

            if not any(p.get('name') == cls.PORT_NAME
                       for p in ports_el.findall('Port')):
                ET.SubElement(ports_el, 'Port', name=cls.PORT_NAME)
                tree.write(cfg_path, xml_declaration=True, encoding='utf-8')

            exe = cls.install_path()
            if exe:
                subprocess.Popen([exe], creationflags=0x08000000)
            return True, f'Port "{cls.PORT_NAME}" configuré — loopMIDI démarré'
        except Exception as e:
            pass

        # Fallback : ouvrir loopMIDI manuellement
        exe = cls.install_path()
        if exe:
            subprocess.Popen([exe], creationflags=0x08000000)
            return False, f'loopMIDI ouvert — ajoutez un port "{cls.PORT_NAME}"'
        return False, 'Impossible de créer le port automatiquement'

    @classmethod
    def open_download(cls):
        QDesktopServices.openUrl(QUrl(cls.DOWNLOAD_URL))


class LiveTile(QWidget):
    """Tuile draggable du panneau mode LIVE (toggle mode ou preset couleur)."""

    toggled = Signal(str, bool)  # (tile_id, is_active)

    def __init__(self, tile_id: str, label: str, accent: str = "#00d4ff",
                 checkable: bool = True, swatch: bool = False, parent=None):
        super().__init__(parent)
        self.tile_id    = tile_id
        self._accent    = accent
        self._checkable = checkable
        self._checked   = False
        self._press_pos = None

        self.setFixedHeight(48)
        self.setMinimumWidth(80)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 4, 8, 4)
        lay.setSpacing(5)

        self._handle = QLabel("⠿")
        self._handle.setFixedWidth(14)
        self._handle.setAlignment(Qt.AlignCenter)
        self._handle.setCursor(Qt.SizeAllCursor)
        lay.addWidget(self._handle)

        if swatch:
            dot = QLabel()
            dot.setFixedSize(11, 11)
            dot.setStyleSheet(
                f"background:{accent}; border-radius:5px; border:1px solid #666;")
            lay.addWidget(dot)

        self._lbl = QLabel(label)
        lay.addWidget(self._lbl, 1)

        self._refresh()

    @property
    def is_checked(self):
        return self._checked

    def set_checked(self, state: bool, silent: bool = False):
        if self._checked == state:
            return
        self._checked = state
        self._refresh()
        if not silent:
            self.toggled.emit(self.tile_id, state)

    def _refresh(self):
        if self._checked:
            border, bg, fg = self._accent, "#0c1820", self._accent
        else:
            border, bg, fg = "#2a2a2a", "#141414", "#666"
        self.setStyleSheet(
            f"LiveTile {{ background:{bg}; border:1px solid {border}; border-radius:8px; }}")
        self._lbl.setStyleSheet(
            f"color:{fg}; font-size:11px; font-weight:bold; background:transparent;")
        self._handle.setStyleSheet(
            f"color:{'#555' if self._checked else '#2d2d2d'}; "
            f"font-size:13px; background:transparent;")

    def enterEvent(self, event):
        if not self._checked:
            self.setStyleSheet(
                "LiveTile { background:#1c1c1c; border:1px solid #3a3a3a; border-radius:8px; }")
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._checked:
            self._refresh()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press_pos is not None and
                (event.pos() - self._press_pos).manhattanLength() > 8 and
                self._press_pos.x() < 18):
            self._press_pos = None
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(self.tile_id)
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(event.pos())
            drag.exec(Qt.MoveAction)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._press_pos is not None:
            pp = self._press_pos
            self._press_pos = None
            if pp.x() >= 18:
                if self._checkable:
                    self.set_checked(not self._checked)
                else:
                    self.toggled.emit(self.tile_id, True)
        else:
            self._press_pos = None
        super().mouseReleaseEvent(event)


class LiveQuickBar(QWidget):
    """Grille 3×N de LiveTile draggables — modes lyre + presets couleur."""

    lyre_mode_changed = Signal(str)   # '' | 'circle' | 'eight'
    color_selected    = Signal(str)   # hex color (#rrggbb)
    tile_toggled      = Signal(str, bool)

    _LYRE_TILES = [
        ("cercle", "Cercle",  "#00d4ff", True,  False),
        ("eight",  "Mode 8",  "#00d4ff", True,  False),
    ]
    _EFFECT_TILES = [
        ("auto",   "AUTO ⚡",  "#ffdd00", True,  False),
        ("flash",  "Flash",   "#ffffff", True,  False),
        ("strobe", "Strobe",  "#ffcc00", True,  False),
        ("gobo",   "Gobo",    "#cc66ff", True,  False),
    ]
    _COLOR_TILES = [
        ("rouge",  "Rouge",   "#ff2200", False, True),
        ("bleu",   "Bleu",    "#0066ff", False, True),
        ("vert",   "Vert",    "#00cc44", False, True),
        ("blanc",  "Blanc",   "#ffffff", False, True),
        ("violet", "Violet",  "#9900ff", False, True),
        ("orange", "Orange",  "#ff8800", False, True),
        ("rose",   "Rose",    "#ff44aa", False, True),
        ("jaune",  "Jaune",   "#eecc00", False, True),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        all_defs = self._LYRE_TILES + self._EFFECT_TILES + self._COLOR_TILES
        self._order  = [t[0] for t in all_defs]
        self._tiles: dict = {}

        for tile_id, label, accent, checkable, swatch in all_defs:
            t = LiveTile(tile_id, label, accent, checkable, swatch)
            if tile_id in ("cercle", "eight"):
                t.toggled.connect(self._on_lyre_tile)
            elif tile_id in ("flash", "strobe", "gobo"):
                t.toggled.connect(
                    lambda _id, _state: self.tile_toggled.emit(_id, _state))
            else:
                t.toggled.connect(
                    lambda _id, _state, c=accent: self.color_selected.emit(c))
            self._tiles[tile_id] = t

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(5)
        self._relayout()

    def lyre_mode(self) -> str:
        if self._tiles["cercle"].is_checked:
            return "circle"
        if self._tiles["eight"].is_checked:
            return "eight"
        return ""

    def _on_lyre_tile(self, tile_id: str, state: bool):
        if state:
            for other in ("cercle", "eight"):
                if other != tile_id:
                    self._tiles[other].set_checked(False, silent=True)
        self.lyre_mode_changed.emit(self.lyre_mode())
        self.tile_toggled.emit(tile_id, state)

    def _relayout(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        cols = 3
        for i, tid in enumerate(self._order):
            tile = self._tiles.get(tid)
            if tile:
                self._grid.addWidget(tile, i // cols, i % cols)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        dragged_id = event.mimeData().text()
        if dragged_id not in self._order:
            return
        drop_pos = event.position().toPoint()
        target_id = None
        for tid in self._order:
            tile = self._tiles.get(tid)
            if tile and tile.geometry().contains(drop_pos):
                target_id = tid
                break
        if target_id and target_id != dragged_id:
            i1 = self._order.index(dragged_id)
            i2 = self._order.index(target_id)
            self._order[i1], self._order[i2] = self._order[i2], self._order[i1]
            self._relayout()
        event.acceptProposedAction()


class LiveSettingsDialog(QDialog):
    """Paramètres du mode LIVE : source, groupes, effets, positions lyres, palette."""

    def __init__(self, config: dict, sources: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PARAMETRE LIVE")
        self.setModal(True)
        self.setMinimumWidth(420)
        # Deep copy config (on garde 'allowed_groups' + 'no_auto_strobe' uniquement)
        self._config = {
            'source':           config.get('source', 'loopback'),
            'allowed_groups':   set(config.get('allowed_groups', set())),
            'no_auto_strobe':   config.get('no_auto_strobe', False),
            # champs hérités conservés pour compatibilité (non éditables ici)
            'allowed_effects':  set(),
            'lyre_presets':     [],
            'palette':          [],
        }
        self._sources = sources
        self._setup_ui()
        self._load_config()

    def set_position_getter(self, fn):
        pass   # positions lyres retirées de ce dialog

    # ── UI ──────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet("""
            QDialog { background: #0d0d0d; color: #e0e0e0; }
            QLabel  { color: #e0e0e0; }
            QComboBox {
                background: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a; border-radius: 4px;
                padding: 6px 12px; font-size: 12px;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a;
                selection-background-color: #2a4a5a;
            }
            QSpinBox {
                background: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }
            QScrollArea  { border: none; background: transparent; }
            QScrollBar:vertical {
                background: #111; width: 6px; border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #333; border-radius: 3px; min-height: 20px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        LS = "color:#888; font-size:10px; font-weight:bold; letter-spacing:1.5px;"

        # Title
        tl = QLabel("⚙  PARAMÈTRES LIVE")
        tl.setStyleSheet("color:#e0e0e0; font-size:14px; font-weight:bold; letter-spacing:2px;")
        root.addWidget(tl)
        root.addWidget(self._sep())

        # ── Source ──────────────────────────────────────────────────────────────
        root.addWidget(self._slbl("SOURCE AUDIO", LS))
        self._source_combo = QComboBox()
        for label, _ in self._sources:
            self._source_combo.addItem(label)
        self._source_combo.wheelEvent = lambda e: e.ignore()
        root.addWidget(self._source_combo)
        root.addWidget(self._sep())

        # ── Groupes éclairage ───────────────────────────────────────────────────
        root.addWidget(self._slbl("GROUPES ÉCLAIRAGE  —  vide = tous autorisés", LS))
        grp_row = QHBoxLayout()
        grp_row.setSpacing(8)
        self._grp_btns = {}
        _GROUPS = [
            ('face',     'A', 'Face'),
            ('lat',      'B', 'Lat'),
            ('contre',   'C', 'Contre'),
            ('douche1',  'D', 'Douche 1'),
            ('douche2',  'E', 'Douche 2'),
            ('douche3',  'F', 'Douche 3'),
            ('groupe_g', 'G', 'Groupe G'),
            ('groupe_h', 'H', 'Groupe H'),
        ]
        for gid, letter, fullname in _GROUPS:
            b = self._mkbtn(letter)
            b.setFixedSize(36, 36)
            b.setToolTip(fullname)
            self._grp_btns[gid] = b
            grp_row.addWidget(b)
        grp_row.addStretch()
        root.addLayout(grp_row)
        root.addWidget(self._sep())

        root.addWidget(self._sep())

        # ── Boutons ─────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        rst = QPushButton("Réinitialiser")
        rst.setStyleSheet(self._gbtn())
        rst.setCursor(Qt.PointingHandCursor)
        rst.clicked.connect(self._reset_all)
        cnl = QPushButton("Annuler")
        cnl.setStyleSheet(self._gbtn())
        cnl.setCursor(Qt.PointingHandCursor)
        cnl.clicked.connect(self.reject)
        apl = QPushButton("Appliquer")
        apl.setStyleSheet("""
            QPushButton {
                background:#003a50; color:#00d4ff;
                border:1px solid #00d4ff; border-radius:4px;
                padding:7px 22px; font-size:12px; font-weight:bold;
            }
            QPushButton:hover { background:#004a60; }
        """)
        apl.setCursor(Qt.PointingHandCursor)
        apl.clicked.connect(self._do_apply)
        btn_row.addWidget(rst)
        btn_row.addStretch()
        btn_row.addWidget(cnl)
        btn_row.addWidget(apl)
        root.addLayout(btn_row)

    # ── Helpers ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _sep():
        s = QFrame()
        s.setFrameShape(QFrame.HLine)
        s.setStyleSheet("QFrame { color:#1e1e1e; }")
        return s

    @staticmethod
    def _slbl(text, style):
        l = QLabel(text)
        l.setStyleSheet(style)
        return l

    @staticmethod
    def _gbtn():
        return """
            QPushButton {
                background:#1a1a1a; color:#888;
                border:1px solid #252525; border-radius:4px;
                padding:4px 12px; font-size:11px;
            }
            QPushButton:hover { background:#222; border-color:#444; color:#e0e0e0; }
        """

    def _mkbtn(self, label: str) -> QPushButton:
        b = QPushButton(label)
        b.setCheckable(True)
        b.setFixedHeight(28)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(self._off_style())
        b.toggled.connect(lambda checked, btn=b:
                          btn.setStyleSheet(self._on_style() if checked else self._off_style()))
        return b

    @staticmethod
    def _on_style():
        return ("QPushButton{background:#003a50;color:#00d4ff;"
                "border:1px solid #00d4ff;border-radius:4px;"
                "padding:0 10px;font-size:11px;font-weight:bold;}"
                "QPushButton:hover{background:#004a60;}")

    @staticmethod
    def _off_style():
        return ("QPushButton{background:#151515;color:#555;"
                "border:1px solid #1e1e1e;border-radius:4px;"
                "padding:0 10px;font-size:11px;}"
                "QPushButton:hover{background:#1e1e1e;border-color:#333;color:#888;}")


    # ── Load / Reset / Apply ─────────────────────────────────────────────────────

    def _load_config(self):
        src_key = self._config.get('source', 'loopback')
        for i, (_, k) in enumerate(self._sources):
            if k == src_key:
                self._source_combo.setCurrentIndex(i)
                break
        ag = self._config.get('allowed_groups', set())
        for gid, b in self._grp_btns.items():
            b.setChecked(gid in ag)

    def _reset_all(self):
        for b in self._grp_btns.values():
            b.setChecked(False)

    def _do_apply(self):
        idx = self._source_combo.currentIndex()
        self._config['source']         = (self._sources[idx][1]
                                          if 0 <= idx < len(self._sources) else 'loopback')
        self._config['allowed_groups'] = {g for g, b in self._grp_btns.items() if b.isChecked()}
        self.accept()

    def get_config(self) -> dict:
        return self._config


class _ModeTile(QFrame):
    """Tuile cliquable de sélection de mode LIVE."""
    clicked = Signal(str)

    _CSS_IDLE = """
        _ModeTile {
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 8px;
        }
    """
    _CSS_ACTIVE = """
        _ModeTile {
            background: #130a2a;
            border: 2px solid #7733ff;
            border-radius: 8px;
        }
    """

    def __init__(self, key: str, icon: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self._key = key
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(84)
        self.setStyleSheet(self._CSS_IDLE)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(6, 8, 6, 8)
        vbox.setSpacing(3)

        icon_lbl = QLabel(icon)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size:18px; background:transparent; border:none;")

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(
            "color:#e0e0e0; font-size:10px; font-weight:bold;"
            " letter-spacing:1px; background:transparent; border:none;")

        sub_lbl = QLabel(subtitle)
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(
            "color:#999; font-size:11px; font-style:italic;"
            " background:transparent; border:none;")

        vbox.addWidget(icon_lbl)
        vbox.addWidget(title_lbl)
        vbox.addWidget(sub_lbl)

    def set_active(self, active: bool):
        self.setStyleSheet(self._CSS_ACTIVE if active else self._CSS_IDLE)

    def mousePressEvent(self, event):
        self.clicked.emit(self._key)
        super().mousePressEvent(event)


class _MovTile(QFrame):
    """Tuile de pattern de mouvement lyre (grille MOUVEMENTS).

    Trois états visuels :
      - idle     : gris, non sélectionné
      - selected : violet pâle, dans le pool de mouvements (sera joué)
      - playing  : violet vif + bordure lumineuse, en cours d'exécution
    """
    clicked = Signal(str)

    _CSS_IDLE = """
        _MovTile {
            background: #141414;
            border: 1px solid #252525;
            border-radius: 6px;
        }
    """
    _CSS_SELECTED = """
        _MovTile {
            background: #0e0720;
            border: 1px solid #4411aa;
            border-radius: 6px;
        }
    """
    _CSS_PLAYING = """
        _MovTile {
            background: #1e0a42;
            border: 2px solid #bb77ff;
            border-radius: 6px;
        }
    """
    # Alias pour compatibilité ascendante
    _CSS_ACTIVE = _CSS_PLAYING

    def __init__(self, key: str, icon: str, label: str, parent=None):
        super().__init__(parent)
        self._key = key
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(54)
        self.setStyleSheet(self._CSS_IDLE)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(4, 6, 4, 6)
        vbox.setSpacing(2)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setStyleSheet(
            "font-size:15px; background:transparent; border:none; color:#555;")

        self._title_lbl = QLabel(label)
        self._title_lbl.setAlignment(Qt.AlignCenter)
        self._title_lbl.setStyleSheet(
            "color:#555; font-size:8px; font-weight:bold; letter-spacing:0.5px;"
            " background:transparent; border:none;")

        vbox.addWidget(self._icon_lbl)
        vbox.addWidget(self._title_lbl)

    def set_state(self, selected: bool, playing: bool):
        """Met à jour l'apparence selon l'état (idle / selected / playing)."""
        if playing:
            self.setStyleSheet(self._CSS_PLAYING)
            self._icon_lbl.setStyleSheet(
                "font-size:15px; background:transparent; border:none; color:#dd99ff;")
            self._title_lbl.setStyleSheet(
                "color:#aa77ff; font-size:8px; font-weight:bold; letter-spacing:0.5px;"
                " background:transparent; border:none;")
        elif selected:
            self.setStyleSheet(self._CSS_SELECTED)
            self._icon_lbl.setStyleSheet(
                "font-size:15px; background:transparent; border:none; color:#7744cc;")
            self._title_lbl.setStyleSheet(
                "color:#5533aa; font-size:8px; font-weight:bold; letter-spacing:0.5px;"
                " background:transparent; border:none;")
        else:
            self.setStyleSheet(self._CSS_IDLE)
            self._icon_lbl.setStyleSheet(
                "font-size:15px; background:transparent; border:none; color:#555;")
            self._title_lbl.setStyleSheet(
                "color:#555; font-size:8px; font-weight:bold; letter-spacing:0.5px;"
                " background:transparent; border:none;")

    def set_active(self, active: bool):
        """Compat ascendante — utiliser set_state() de préférence."""
        self.set_state(selected=active, playing=active)

    def mousePressEvent(self, event):
        self.clicked.emit(self._key)
        super().mousePressEvent(event)

class _ColorTile(QWidget):
    """Tuile couleur ronde — cercle peint + label.

    AUTO      → cercle sombre avec contour cyan
    Mono      → cercle plein coloré
    Bicolore  → cercle coupé diagonalement en deux couleurs
    États : idle (anneau discret) / selected (anneau violet) / playing (anneau vif + glow)
    """
    clicked = Signal(str)
    D = 36   # diamètre du cercle

    def __init__(self, key: str, color1, color2, label: str, parent=None):
        super().__init__(parent)
        self._key    = key
        self._c1     = QColor(color1) if color1 else None
        self._c2     = QColor(color2) if color2 else None
        self._label  = label
        self._state  = 'idle'   # 'idle' | 'selected' | 'playing'
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.D + 8, self.D + 16)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_state(self, selected: bool, playing: bool):
        new = 'playing' if playing else ('selected' if selected else 'idle')
        if new != self._state:
            self._state = new
            self.update()

    def set_active(self, active: bool):
        self.set_state(active, active)

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QPainterPath, QRadialGradient, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cx = self.width() // 2
        r  = self.D // 2
        cy = r + 2   # centre vertical du cercle

        # ── Glow playing ──────────────────────────────────────────────────
        if self._state == 'playing':
            g = QRadialGradient(cx, cy, r + 6)
            g.setColorAt(0.0, QColor(180, 100, 255, 80))
            g.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawEllipse(cx - r - 6, cy - r - 6, (r + 6) * 2, (r + 6) * 2)

        # ── Dessin du cercle ───────────────────────────────────────────────
        path = QPainterPath()
        path.addEllipse(cx - r, cy - r, self.D, self.D)
        p.setClipPath(path)

        if self._c1 is None:
            # AUTO
            p.fillPath(path, QColor('#0a1520'))
        elif self._c2 is None:
            # Mono
            p.fillPath(path, self._c1)
        else:
            # Bicolore : moitié gauche / moitié droite
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            left = QPainterPath()
            left.addRect(cx - r, cy - r, r, self.D)
            left = left.intersected(path)
            p.fillPath(left, self._c1)
            right = QPainterPath()
            right.addRect(cx, cy - r, r, self.D)
            right = right.intersected(path)
            p.fillPath(right, self._c2)

        p.setClipping(False)

        # ── Anneau d'état ─────────────────────────────────────────────────
        if self._state == 'playing':
            pen = QPen(QColor('#cc88ff'), 2.5)
        elif self._state == 'selected':
            pen = QPen(QColor('#6633bb'), 1.5)
        elif self._c1 is None:
            pen = QPen(QColor('#00d4ff'), 1.5)
        else:
            pen = QPen(QColor('#2a2a2a'), 1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(cx - r + 1, cy - r + 1, self.D - 2, self.D - 2)

        # ── Checkmark (sélectionné ou en cours) ───────────────────────────
        if self._state in ('selected', 'playing'):
            ck_color = QColor('#ffffff') if self._state == 'playing' else QColor('#cc88ff')
            ck_pen = QPen(ck_color, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(ck_pen)
            # Petit ✓ centré dans le cercle
            _ox, _oy = cx - 5, cy - 2
            from PySide6.QtCore import QLineF
            p.drawLine(int(_ox),     int(_oy + 4),
                       int(_ox + 3), int(_oy + 7))
            p.drawLine(int(_ox + 3), int(_oy + 7),
                       int(_ox + 9), int(_oy))

        # ── Label ─────────────────────────────────────────────────────────
        if self._state == 'playing':
            p.setPen(QColor('#cc88ff'))
        elif self._state == 'selected':
            p.setPen(QColor('#7744cc'))
        else:
            p.setPen(QColor('#444'))
        from PySide6.QtGui import QFont as _QFont
        f = _QFont(); f.setPointSize(7); f.setBold(True)
        p.setFont(f)
        p.drawText(0, cy + r + 2, self.width(), 12, Qt.AlignHCenter, self._label)
        p.end()

    def mousePressEvent(self, event):
        self.clicked.emit(self._key)
        super().mousePressEvent(event)


class _SpecialTile(_MovTile):
    """Tuile d'effet spécial — même design que _MovTile.
    Comportement toggle : cliquer sur l'actif le désactive.
    """

    def __init__(self, key: str, icon: str, label: str, desc: str, accent: str, parent=None):
        super().__init__(key, icon, label, parent)
        self._active = False
        self.setToolTip(desc)

    def set_active(self, active: bool):
        self._active = active
        self.set_state(selected=active, playing=active)


# ─────────────────────────────────────────────────────────────────────────────

class _VuSensWidget(QWidget):
    """VU-mètre + marqueur de seuil de sensibilité fusionnés.
    - Barre de niveau audio (gradient bleu)
    - Marqueur blanc déplaçable = seuil de détection des beats
    """
    valueChanged = Signal(int)   # sensibilité 0-100

    def __init__(self, initial_sens=80, parent=None):
        super().__init__(parent)
        self._level = 0           # niveau VU courant (0-100)
        self._sens  = initial_sens
        self._dragging = False
        self.setFixedHeight(18)
        self.setCursor(Qt.SizeHorCursor)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        # Proxy QSlider caché pour compatibilité signaux
        self._sens_proxy = QSlider(Qt.Horizontal)
        self._sens_proxy.setRange(0, 100)
        self._sens_proxy.setValue(initial_sens)
        self._sens_proxy.hide()
        self._sens_proxy.valueChanged.connect(self._on_proxy_changed)

    def _on_proxy_changed(self, v):
        self._sens = v
        self.update()

    # Compat QProgressBar.setValue (appelé par set_vu)
    def setValue(self, v: int):
        self._level = max(0, min(100, v))
        self.update()

    def setRange(self, lo, hi): pass
    def setTextVisible(self, v): pass

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QLinearGradient, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Fond
        p.setBrush(QColor('#0d1a28'))
        p.setPen(QPen(QColor('#1a3050'), 1))
        p.drawRoundedRect(0, 0, w, h, 3, 3)

        # Barre VU — niveau affiché réduit proportionnellement à la sensibilité
        _displayed = self._level * (self._sens / 100.0)
        fill_w = int(w * _displayed / 100)
        if fill_w > 0:
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0.0,  QColor('#003355'))
            g.setColorAt(0.65, QColor('#0088cc'))
            g.setColorAt(0.92, QColor('#00d4ff'))
            g.setColorAt(1.0,  QColor('#ffffff'))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(1, 1, fill_w - 1, h - 2, 2, 2)

        # Marqueur seuil (ligne blanche + triangle)
        mx = int(w * self._sens / 100)
        p.setPen(QPen(QColor('#ffffff'), 2))
        p.drawLine(mx, 0, mx, h)
        # Petit triangle indicateur en haut
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint
        tri = QPolygon([QPoint(mx-4, 0), QPoint(mx+4, 0), QPoint(mx, 5)])
        p.setBrush(QColor('#ffffff'))
        p.setPen(Qt.NoPen)
        p.drawPolygon(tri)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._set_from_x(e.position().x())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._set_from_x(e.position().x())
            e.accept()

    def mouseReleaseEvent(self, e):
        self._dragging = True
        e.accept()

    def _set_from_x(self, x):
        v = max(0, min(100, int(x / max(1, self.width()) * 100)))
        self._sens = v
        self._sens_proxy.setValue(v)
        self.valueChanged.emit(v)
        self.update()


class LiveModePanel(QWidget):
    """Panneau de controle du mode LIVE - remplace la playlist quand actif"""

    color_changed       = Signal(object)  # QColor
    nervosity_changed   = Signal(int)     # 0–100
    sensitivity_changed = Signal(int)     # 0–100
    luminosity_changed  = Signal(int)     # 0–100
    lyre_mode_changed   = Signal(str)     # '' | 'circle' | 'eight'
    bpm_override        = Signal(float)   # BPM manuel
    bpm_released        = Signal()        # retour auto
    settings_applied    = Signal(dict)    # config live mise à jour
    ia_mode_changed     = Signal(str)     # 'musical' | 'ambiance' | 'manuel'
    source_changed      = Signal(str)     # nouvelle source_key
    movement_changed    = Signal(str)     # pattern mouvement lyre

    # Sources fixes + périphériques dynamiques (ajoutés à l'init)
    _SOURCES_STATIC = [
        ("Micro / Line In",                              "mic"),
        ("MIDI Clock  (VirtualDJ, Rekordbox, Serato…)",  "midi_clock"),
    ]

    SOURCES = [
        ("Micro / Line In",                              "mic"),
        ("MIDI Clock  (VirtualDJ, Rekordbox, Serato…)",  "midi_clock"),
    ]

    # Styles des sections musicales pour l'indicateur animé
    _SECTION_STYLES = {
        'drop':  {'text': 'DROP !',  'color_a': '#ff2200', 'color_b': '#661100', 'fs': 22},
        'high':  {'text': 'PEAK',    'color_a': '#ff8800', 'color_b': '#cc6600', 'fs': 18},
        'build': {'text': 'MONTÉE',  'color_a': '#ffcc00', 'color_b': '#aa8800', 'fs': 18},
        'verse': {'text': 'BEAT',    'color_a': '#00d4ff', 'color_b': '#00d4ff', 'fs': 16},
        'quiet': {'text': 'CALME',   'color_a': '#445566', 'color_b': '#445566', 'fs': 14},
    }

    _SOURCE_INFO = {
        "mic":        "Table de mixage, micro, entrée ligne, interface audio",
        "midi_clock": "BPM + beats via loopMIDI — VirtualDJ, Rekordbox, Serato, Traktor…",
        "ia_file":    "Utilise la pré-analyse IA du fichier en cours — beats parfaitement calés",
    }

    _SLIDER_STYLE = """
        QSlider::groove:horizontal {
            border: 1px solid #3a3a3a; height: 6px;
            background: #252525; border-radius: 3px;
        }
        QSlider::sub-page:horizontal {
            background: #00d4ff; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #00d4ff; border: 2px solid #ffffff;
            width: 16px; margin: -5px 0; border-radius: 8px;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dominant_color = QColor("#ff4400")
        self.color2         = QColor("#0044ff")
        self._pulse_phase   = 0
        self._pulse_section = ''
        self._bpm_manual        = False
        self._sync_tap_times: list = []   # timestamps des taps SYNC
        self._sync_reset_timer = None     # QTimer reset après inactivité
        self._ia_mode            = 'musical'
        self._movement_patterns  = {'cercle'}   # set des mouvements sélectionnés
        self._current_movement   = 'cercle'     # mouvement en cours d'exécution
        self._movement_speed     = 50
        self._movement_size      = 70
        self._movement_duration  = 40         # durée en % (0-100)
        # ── Couleurs lyres (pool + cycle, même principe que mouvements) ────
        self._color_tile_pool  = {'rouge', 'orange', 'jaune', 'ambre'}
        self._current_color    = 'rouge'
        self._color_duration   = 40         # durée en % (0-100)
        self._color_restrict   = True       # toujours restreindre à la sélection
        # Enrichir SOURCES avec les périphériques audio détectés
        self._refresh_audio_sources()

        self._color_max        = 4          # nombre de couleurs simultanées max (1-4)
        # ── Effet spécial (radio : un seul à la fois) ─────────────────────
        self._active_special   = None       # None | 'strobe' | 'strobe_couleur' | 'fixe_blanc'
        self._passage_speed    = 50         # vitesse du passage (1-100)
        self._gobo_pool        = {0}         # set de slots sélectionnés (comme _movement_patterns)
        self._current_gobo     = 0          # slot actif en cours
        self._gobo_duration    = 40         # durée par gobo en % (0-100)
        self._gobo_rotation    = False      # rotation activée
        self._gobo_rot_speed   = 50         # vitesse rotation (1-100)
        self._strob_fast       = True       # autoriser strobe rapide
        self._strob_slow       = True       # autoriser strobe lent
        self._strob_none       = True       # autoriser absence de strobe
        self._live_config   = {
            'source':          'loopback',
            'allowed_groups':  set(),
            'allowed_effects': set(),
            'lyre_presets':    [],
            'palette':         [],
            'no_auto_strobe':  False,
        }
        self._pos_getter = None
        # Presets live (4 slots, None = vide)
        self._live_presets: list = [None, None, None, None]
        # Timestamps press pour clic long (presets)
        self._preset_press_ts: list = [0.0, 0.0, 0.0, 0.0]
        # Charger la config sauvegardée AVANT _setup_ui (les valeurs sont lues à la construction)
        self._load_live_panel_config()

        self._setup_ui()

        # Appliquer sensibilité et luminosité chargées
        if hasattr(self, '_saved_sensitivity') and hasattr(self, '_vu_sens'):
            self._vu_sens._sens = self._saved_sensitivity
            self._vu_sens._sens_proxy.setValue(self._saved_sensitivity)
        if hasattr(self, '_saved_luminosity') and hasattr(self, 'lumi_slider'):
            self.lumi_slider.setValue(self._saved_luminosity)
        if hasattr(self, '_saved_reaction') and hasattr(self, 'reac_slider'):
            self.reac_slider.setValue(self._saved_reaction)

        # Brancher les signaux après création des sliders
        self.nerv_slider.valueChanged.connect(self.nervosity_changed)
        self.sens_slider.valueChanged.connect(self.sensitivity_changed)
        self.lumi_slider.valueChanged.connect(self.luminosity_changed)
        if hasattr(self, '_vu_sens'):
            self._vu_sens.valueChanged.connect(self.sensitivity_changed)

        # Sauvegarder sur chaque changement (timer debounce 1s)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)
        self._save_timer.timeout.connect(self._save_live_panel_config)

        # Connecter les sliders pour déclencher la sauvegarde
        for sl_attr in ('lumi_slider', 'nerv_slider', 'sens_slider'):
            sl = getattr(self, sl_attr, None)
            if sl:
                sl.valueChanged.connect(lambda _: self._request_save())
        if hasattr(self, '_vu_sens'):
            self._vu_sens.valueChanged.connect(lambda _: self._request_save())

        # Timer d'animation section (120 ms)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_timer.start(120)

    @property
    def ia_mode(self) -> str:
        return self._ia_mode

    @property
    def movement_pattern(self) -> str:
        """Mouvement en cours d'exécution (ou le premier sélectionné)."""
        return self._current_movement

    @property
    def movement_patterns(self) -> list:
        """Liste ordonnée des mouvements dans le pool (ordre de _MOVEMENTS)."""
        order = [k for k, _, _ in self._MOVEMENTS]
        return [k for k in order if k in self._movement_patterns]

    @property
    def movement_speed(self) -> int:
        return self._movement_speed

    @property
    def movement_size(self) -> int:
        return self._movement_size

    @property
    def movement_duration(self) -> int:
        return self._movement_duration

    @property
    def color_restrict(self) -> bool:
        return self._color_restrict

    @property
    def color_max(self) -> int:
        return self._color_max

    @property
    def color_tile_pool(self) -> list:
        """Tuiles couleur sélectionnées, dans l'ordre de _COLOR_TILES."""
        order = [row[0] for row in self._COLOR_TILES]
        return [k for k in order if k in self._color_tile_pool]

    @property
    def current_color_tile(self) -> str:
        return self._current_color

    @property
    def color_duration(self) -> int:
        return self._color_duration

    @property
    def active_special(self):
        """Effet spécial actif (None si aucun)."""
        return self._active_special

    @property
    def passage_speed(self) -> int:
        return self._passage_speed

    def get_color_data(self, key: str):
        """Retourne (QColor|None, QColor|None) pour une tuile couleur.
        color1=None signifie AUTO (utiliser la palette IA)."""
        for row in self._COLOR_TILES:
            k, c1, c2 = row[0], row[1], row[2]
            if k == key:
                return (QColor(c1) if c1 else None,
                        QColor(c2) if c2 else None)
        return None, None

    # ── Persistance ──────────────────────────────────────────────────────────

    _LIVE_PANEL_CFG = str(Path.home() / '.mystrow_live_panel.json')

    def _request_save(self):
        """Déclenche une sauvegarde différée (debounce 1s)."""
        if hasattr(self, '_save_timer'):
            self._save_timer.start()

    def _save_live_panel_config(self):
        """Sauvegarde tous les réglages du panneau live."""
        try:
            import json as _json
            cfg = {
                'color_pool':       list(self._color_tile_pool),
                'current_color':    self._current_color,
                'color_duration':   self._color_duration,
                'color_max':        self._color_max,
                'mov_patterns':     list(self._movement_patterns),
                'current_mov':      self._current_movement,
                'mov_speed':        self._movement_speed,
                'mov_size':         self._movement_size,
                'mov_duration':     self._movement_duration,
                'gobo_pool':        list(self._gobo_pool),
                'current_gobo':     self._current_gobo,
                'gobo_duration':    self._gobo_duration,
                'gobo_rotation':    self._gobo_rotation,
                'gobo_rot_speed':   self._gobo_rot_speed,
                'strob_fast':       self._strob_fast,
                'strob_slow':       self._strob_slow,
                'strob_none':       self._strob_none,
                'dimmer_values':    getattr(self, '_dimmer_values', {}),
                'sensitivity':      self._vu_sens._sens if hasattr(self, '_vu_sens') else 80,
                'ia_mode':          self._ia_mode if hasattr(self, '_ia_mode') else 'musical',
                'source':           self._live_config.get('source', 'loopback'),
                'allowed_groups':   list(self._live_config.get('allowed_groups', set())),
                'luminosity':       self.lumi_slider.value() if hasattr(self, 'lumi_slider') else 100,
                'reaction':         self.reac_slider.value() if hasattr(self, 'reac_slider') else 70,
                'live_presets':     getattr(self, '_live_presets', [None, None, None, None]),
            }
            with open(self._LIVE_PANEL_CFG, 'w', encoding='utf-8') as f:
                _json.dump(cfg, f, indent=2)
        except Exception as e:
            print(f"[LivePanel] save: {e}")

    def _load_live_panel_config(self):
        """Charge et applique les réglages sauvegardés."""
        try:
            import json as _json
            if not Path(self._LIVE_PANEL_CFG).exists():
                return
            with open(self._LIVE_PANEL_CFG, 'r', encoding='utf-8') as f:
                cfg = _json.load(f)
            self._color_tile_pool   = set(cfg.get('color_pool', list(self._color_tile_pool)))
            self._current_color     = cfg.get('current_color', self._current_color)
            self._color_duration    = int(cfg.get('color_duration', self._color_duration))
            self._color_max         = int(cfg.get('color_max', self._color_max))
            self._movement_patterns = set(cfg.get('mov_patterns', list(self._movement_patterns)))
            self._current_movement  = cfg.get('current_mov', self._current_movement)
            self._movement_speed    = int(cfg.get('mov_speed', self._movement_speed))
            self._movement_size     = int(cfg.get('mov_size', self._movement_size))
            self._movement_duration = int(cfg.get('mov_duration', self._movement_duration))
            self._gobo_pool         = set(int(x) for x in cfg.get('gobo_pool', list(self._gobo_pool)))
            self._current_gobo      = int(cfg.get('current_gobo', self._current_gobo))
            self._gobo_duration     = int(cfg.get('gobo_duration', self._gobo_duration))
            self._gobo_rotation     = bool(cfg.get('gobo_rotation', self._gobo_rotation))
            self._gobo_rot_speed    = int(cfg.get('gobo_rot_speed', self._gobo_rot_speed))
            self._strob_fast        = bool(cfg.get('strob_fast', self._strob_fast))
            self._strob_slow        = bool(cfg.get('strob_slow', self._strob_slow))
            self._strob_none        = bool(cfg.get('strob_none', self._strob_none))
            if 'dimmer_values' in cfg:
                self._dimmer_values = cfg['dimmer_values']
            if 'source' in cfg:
                self._live_config['source'] = cfg['source']
            if 'allowed_groups' in cfg:
                self._live_config['allowed_groups'] = set(cfg['allowed_groups'])
            self._saved_sensitivity = int(cfg.get('sensitivity', 80))
            self._saved_luminosity  = int(cfg.get('luminosity', 100))
            self._saved_reaction    = int(cfg.get('reaction', 70))
            self._live_presets      = cfg.get('live_presets', [None, None, None, None])
            # S'assurer que la liste a exactement 4 slots
            while len(self._live_presets) < 4:
                self._live_presets.append(None)
        except Exception as e:
            print(f"[LivePanel] load: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        lbl_style = "color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;"

        # ── Source : combo caché (état interne) — affiché dans la carte INPUT ──
        # Le sélecteur visible est la carte INPUT elle-même (clique → ⚙ paramètres).
        self.source_combo = QComboBox()
        for label, key in self.SOURCES:
            if key is None:
                self.source_combo.addItem(label)
                item = self.source_combo.model().item(self.source_combo.count() - 1)
                if item:
                    item.setEnabled(False)
            else:
                self.source_combo.addItem(label, key)
        self.source_combo.wheelEvent = lambda e: e.ignore()
        # Restaurer la dernière source sélectionnée
        _saved_src = self._live_config.get('source', 'mic')
        for _i in range(self.source_combo.count()):
            if self.source_combo.itemData(_i) == _saved_src:
                self.source_combo.blockSignals(True)
                self.source_combo.setCurrentIndex(_i)
                self.source_combo.blockSignals(False)
                break
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        # Fantômes non affichés (méthodes existantes les référencent)
        self._source_info_lbl = QLabel()
        self.device_lbl       = QLabel()
        self._detected_badge  = QLabel()
        # Dot de connexion (sera placé dans la carte INPUT)
        self._conn_dot = QLabel()
        self._conn_dot.setFixedSize(10, 10)
        self._conn_dot.setToolTip("Statut de connexion")
        self._set_conn_dot('off')
        # MIDI setup — affiché après la carte INPUT si MIDI Clock sélectionné
        self._midi_setup = self._build_midi_setup_widget()

        # ── PARAMETRE LIVE (style carteson) + BPM — côte à côte ─────────────
        layout.addLayout(self._build_settings_bpm_row())
        layout.addWidget(self._midi_setup)
        self._midi_setup.hide()

        layout.addWidget(self._separator())

        # ── Sélecteur de mode IA ────────────────────────────────────────────
        layout.addLayout(self._build_mode_tiles())

        layout.addWidget(self._separator())

        # ── Luminosité ──────────────────────────────────────────────────────
        layout.addLayout(self._slider_row("LUMINOSITÉ", "lumi", 100,
                                          "Luminosité globale des projecteurs sélectionnés"))

        # ── Réaction ─────────────────────────────────────────────────────────
        _reac_default = getattr(self, '_saved_reaction', 70)
        layout.addLayout(self._slider_row("RÉACTION", "reac", _reac_default,
                                          "Vitesse de réponse de l'IA (0%=lent/lissé, 100%=immédiat)"))
        self.reac_slider.valueChanged.connect(lambda _: self._request_save())

        # nerv_slider et sens_slider créés ailleurs — fallback si absent
        if not hasattr(self, 'nerv_slider'):
            self.nerv_slider = QSlider(Qt.Horizontal)
            self.nerv_slider.setRange(0, 100)
            self.nerv_slider.setValue(50)
        if not hasattr(self, 'sens_slider'):
            self.sens_slider = QSlider(Qt.Horizontal)
            self.sens_slider.setRange(0, 100)
            self.sens_slider.setValue(80)

        # vu_bar conservé (non affiché) pour compatibilité avec set_vu()
        self.vu_bar = QProgressBar()
        self.vu_bar.setRange(0, 100)

        layout.addSpacing(8)

        # ── Presets live P1–P4 ──────────────────────────────────────────────
        layout.addLayout(self._build_preset_row())

        # ── Panel Mouvements ────────────────────────────────────────────────
        layout.addWidget(self._build_movement_panel())

        layout.addStretch()

        # ── Mention bêta ────────────────────────────────────────────────────
        beta_lbl = QLabel(
            "✦  Fonctionnalité en cours de développement\n"
            "Nous améliorons continuellement notre algorithme prédictif\n"
            "pour de meilleures performances.\n\n"
            "N'hésitez pas à nous <a href='idea' style='color:#00aaff;'>contacter</a>"
        )
        beta_lbl.setWordWrap(True)
        beta_lbl.setAlignment(Qt.AlignCenter)
        beta_lbl.setTextFormat(Qt.RichText)
        beta_lbl.setOpenExternalLinks(False)
        beta_lbl.setStyleSheet(
            "color:#484848; font-size:13px; font-style:italic; "
            "padding:10px 10px; background:transparent;"
        )
        beta_lbl.linkActivated.connect(self._on_beta_contact_clicked)
        layout.addWidget(beta_lbl)

        self.setStyleSheet("""
            LiveModePanel {
                background: #0d0d0d;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
            }
        """)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _separator():
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { color: #2a2a2a; }")
        return sep

    def _slider_row(self, label, attr_prefix, default, tooltip=""):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;")
        lbl.setFixedWidth(100)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(default)
        slider.setStyleSheet(self._SLIDER_STYLE)
        if tooltip:
            slider.setToolTip(tooltip)
        val_lbl = QLabel(f"{default}%")
        val_lbl.setStyleSheet("color: #00d4ff; font-size: 12px; font-weight: bold; min-width: 38px;")
        val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(lambda v, l=val_lbl: l.setText(f"{v}%"))
        setattr(self, f"{attr_prefix}_slider", slider)
        setattr(self, f"{attr_prefix}_lbl", val_lbl)
        row.addWidget(lbl)
        row.addWidget(slider, 1)
        row.addWidget(val_lbl)
        return row

    # ── API publique (pour le moteur audio - étape 2) ────────────────────────

    @property
    def source_key(self):
        key = self.source_combo.currentData()
        return key if key else "loopback"

    @property
    def luminosity(self) -> float:
        return self.lumi_slider.value() / 100.0

    @property
    def reaction(self) -> float:
        """Vitesse de réaction IA (0.0–1.0, défaut 0.7)."""
        if hasattr(self, 'reac_slider'):
            return self.reac_slider.value() / 100.0
        return 0.7

    @property
    def nervosity(self):
        return self.nerv_slider.value() / 100.0

    @property
    def sensitivity(self):
        return self.sens_slider.value() / 100.0

    # Noms courts affichés dans la carte INPUT
    _SOURCE_SHORT = {
        'mic':        'ENTRÉE MICRO',
        'midi_clock': 'MIDI CLOCK',
    }

    def _source_display_name(self) -> str:
        key = self.source_key
        if key in self._SOURCE_SHORT:
            return self._SOURCE_SHORT[key]
        # Pour dev_in:N et dev_out:N → retourner le label du combo
        if hasattr(self, 'source_combo'):
            idx = self.source_combo.currentIndex()
            label = self.source_combo.itemText(idx)
            if label:
                # Enlever l'emoji et l'espace initial (🎤  ou 🔊 )
                return label.lstrip('🎤🔊 ').strip()
        return key.upper()

    def _on_source_changed(self, idx: int):
        key = self.source_combo.itemData(idx) or "loopback"
        self._source_info_lbl.setText(self._SOURCE_INFO.get(key, ""))
        self._set_conn_dot('off')
        self.device_lbl.setText("—")
        if hasattr(self, '_input_name_lbl'):
            self._input_name_lbl.setText(self._source_display_name())
        is_midi = key in ('midi_clock', 'rekordbox')
        self._midi_setup.setVisible(is_midi)
        # "?" visible pour les sources nécessitant une config (MIDI, VDJ, Rekordbox)
        needs_help = key in ('midi_clock', 'rekordbox', 'virtualdj')
        if hasattr(self, '_source_help_btn'):
            self._source_help_btn.setVisible(needs_help)
            if not needs_help:
                self._source_help_btn.setChecked(False)
        if is_midi:
            QTimer.singleShot(0, self._refresh_midi_status)
            QTimer.singleShot(50, self._refresh_midi_ctrl_combo)
        # Redémarrer le moteur si live actif
        self.source_changed.emit(key)
        self._request_save()

    def _build_midi_setup_widget(self):
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background:#080f08; border:1px solid #1a3a1a; border-radius:6px; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        # ── Ligne 1 : liste contrôleurs + "MIDI VIRTUEL" + dot ──────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        # Combo contrôleurs MIDI détectés
        self._midi_ctrl_combo = QComboBox()
        self._midi_ctrl_combo.setStyleSheet(
            "QComboBox { background:#0d180d; color:#88cc88; border:1px solid #2a4a2a;"
            " border-radius:4px; padding:3px 8px; font-size:10px; }"
            "QComboBox::drop-down { border:none; width:14px; }"
            "QComboBox QAbstractItemView { background:#0d180d; color:#88cc88;"
            " border:1px solid #2a4a2a; }"
        )
        self._midi_ctrl_combo.setCursor(Qt.PointingHandCursor)
        self._midi_ctrl_combo.setFixedHeight(24)
        top_row.addWidget(self._midi_ctrl_combo, 1)

        # "MIDI VIRTUEL" compact
        mv_lbl = QLabel("MIDI VIRTUEL")
        mv_lbl.setStyleSheet(
            "color:#2a6a2a; font-size:8px; font-weight:bold; letter-spacing:1px; "
            "background:transparent; border:none;")
        mv_lbl.setFixedWidth(72)
        top_row.addWidget(mv_lbl)

        # Carré vert / rouge
        self._midi_dot = QLabel()
        self._midi_dot.setFixedSize(10, 10)
        self._midi_dot.setStyleSheet("background:#333; border-radius:2px;")
        top_row.addWidget(self._midi_dot)

        lay.addLayout(top_row)

        # ── Ligne 2 : statut + bouton refresh ────────────────────────────────
        bot_row = QHBoxLayout()
        bot_row.setSpacing(6)

        self._midi_status_lbl = QLabel("Vérification…")
        self._midi_status_lbl.setStyleSheet(
            "color:#668866; font-size:10px; background:transparent; border:none;")
        self._midi_status_lbl.setWordWrap(False)
        bot_row.addWidget(self._midi_status_lbl, 1)

        # Bouton caché — conservé pour compatibilité
        self._midi_btn = QPushButton()
        self._midi_btn.hide()
        self._midi_btn.clicked.connect(self._on_midi_btn_clicked)
        self._midi_guide_open_btn = QPushButton()
        self._midi_guide_open_btn.hide()

        lay.addLayout(bot_row)

        self._midi_instr_lbl = QLabel("")
        self._midi_instr_lbl.setStyleSheet(
            "color:#336633; font-size:9px; font-style:italic;"
            " background:transparent; border:none;")
        self._midi_instr_lbl.setWordWrap(True)
        lay.addWidget(self._midi_instr_lbl)
        self._midi_instr_lbl.hide()

        # ── Container guide (caché par défaut) ───────────────────────────────
        self._midi_guide_container = QWidget()
        self._midi_guide_container.setStyleSheet("background:transparent;")
        gc_lay = QVBoxLayout(self._midi_guide_container)
        gc_lay.setContentsMargins(0, 4, 0, 0)
        gc_lay.setSpacing(4)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { border:none; border-top:1px solid #1a3a1a; }")
        gc_lay.addWidget(sep)

        dj_row = QHBoxLayout(); dj_row.setSpacing(4)
        dj_lbl = QLabel("Logiciel :")
        dj_lbl.setStyleSheet("color:#446644; font-size:9px; background:transparent; border:none;")
        dj_lbl.setFixedWidth(52)
        dj_row.addWidget(dj_lbl)
        self._midi_dj_combo = QComboBox()
        self._midi_dj_combo.addItems(["Virtual DJ", "Rekordbox", "Serato"])
        self._midi_dj_combo.setFixedHeight(22)
        self._midi_dj_combo.setStyleSheet(
            "QComboBox { background:#0d180d; color:#88cc88; border:1px solid #2a4a2a;"
            " border-radius:4px; padding:2px 6px; font-size:9px; }"
            "QComboBox::drop-down { border:none; width:12px; }"
            "QComboBox QAbstractItemView { background:#0d180d; color:#88cc88; border:1px solid #2a4a2a; }"
        )
        self._midi_dj_combo.currentIndexChanged.connect(self._update_midi_guide)
        dj_row.addWidget(self._midi_dj_combo, 1)
        gc_lay.addLayout(dj_row)

        self._midi_guide_lbl = QLabel("")
        self._midi_guide_lbl.setWordWrap(True)
        self._midi_guide_lbl.setStyleSheet(
            "color:#558855; font-size:9px; background:transparent; border:none; padding:2px 0;")
        gc_lay.addWidget(self._midi_guide_lbl)

        self._midi_guide_container.hide()
        lay.addWidget(self._midi_guide_container)

        # Remplir le combo contrôleurs
        QTimer.singleShot(100, self._refresh_midi_ctrl_combo)

        return frame

    def _toggle_midi_guide(self, visible: bool):
        if hasattr(self, '_midi_guide_container'):
            self._midi_guide_container.setVisible(visible)
            if visible:
                self._update_midi_guide()

    def _open_midi_guide_dialog(self):
        """Ouvre un dialog avec le guide de configuration MIDI Clock."""
        import platform
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                       QLabel, QPushButton, QComboBox, QFrame,
                                       QApplication)
        dlg = QDialog(QApplication.activeWindow())
        dlg.setWindowTitle("Guide MIDI Clock")
        dlg.setFixedWidth(420)
        dlg.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        dlg.setStyleSheet("""
            QDialog { background:#0d0d0d; color:#e0e0e0; }
            QLabel  { background:transparent; border:none; }
            QComboBox { background:#1a1a1a; color:#e0e0e0; border:1px solid #333;
                border-radius:5px; padding:5px 10px; font-size:12px; }
            QComboBox::drop-down { border:none; width:18px; }
            QComboBox QAbstractItemView { background:#1a1a1a; color:#e0e0e0;
                border:1px solid #333; selection-background-color:#0055aa; }
        """)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel("🎛  Guide MIDI Clock")
        title.setStyleSheet("color:#00aaff; font-size:15px; font-weight:bold;")
        lay.addWidget(title)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border-top:1px solid #222;")
        lay.addWidget(sep)

        # Sélecteur logiciel
        row = QHBoxLayout()
        row.addWidget(QLabel("Logiciel DJ :"))
        combo = QComboBox()
        combo.addItems(["Virtual DJ", "Rekordbox", "Serato"])
        row.addWidget(combo, 1)
        lay.addLayout(row)

        # Texte guide
        guide_lbl = QLabel()
        guide_lbl.setWordWrap(True)
        guide_lbl.setTextFormat(Qt.RichText)
        guide_lbl.setOpenExternalLinks(True)
        guide_lbl.setStyleSheet("color:#aaa; font-size:12px;")
        lay.addWidget(guide_lbl)

        is_mac = platform.system() == 'Darwin'
        port   = LoopMidiHelper.PORT_NAME

        def update(idx=0):
            soft = combo.currentText()
            if is_mac:
                s1 = "① Ouvrez <b>Audio MIDI Setup</b> (Applications → Utilitaires)"
                s2 = "② Menu Fenêtre → <b>Afficher le studio MIDI</b>"
                s3 = f'③ Double-clic sur <b>IAC Driver</b> → cocher <b>"Le périphérique est en ligne"</b> → + → nommer <b>"{port}"</b>'
            else:
                s1 = '① Téléchargez <b><a href="https://www.tobias-erichsen.de/software/loopmidi.html" style="color:#00aaff;">loopMIDI</a></b> (gratuit, Windows)'
                s2 = f'② Lancez loopMIDI → champ en bas → tapez <b>"{port}"</b> → cliquez <b>"+"</b>'
                s3 = "③ Laissez loopMIDI <b>actif en arrière-plan</b>"

            if soft == "Virtual DJ":
                s4 = "④ VirtualDJ → <b>Paramètres → Contrôleurs</b>"
                s5 = f'⑤ <b>Sortie horloge MIDI</b> → sélectionnez <b>"{port}"</b>'
            elif soft == "Rekordbox":
                s4 = "④ Rekordbox → <b>Préférences → MIDI</b>"
                s5 = f'⑤ Activer <b>MIDI Clock</b> → Sortie → <b>"{port}"</b>'
            else:
                s4 = "④ Installez le plugin <b>MIDI Link</b> dans Serato (gratuit)"
                s5 = f'⑤ MIDI Link → Sortie → <b>"{port}"</b>'

            s6 = "⑥ Dans MyStrow → Source audio → <b>MIDI Clock</b> ✓"
            guide_lbl.setText(f"{s1}<br>{s2}<br>{s3}<br><br>{s4}<br>{s5}<br><br>{s6}")

        combo.currentIndexChanged.connect(update)
        update()

        close_btn = QPushButton("Fermer")
        close_btn.setFixedHeight(34)
        close_btn.setStyleSheet(
            "QPushButton { background:#1a1a1a; color:#888; border:1px solid #333;"
            " border-radius:5px; font-size:12px; }"
            "QPushButton:hover { color:#ccc; }"
        )
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)

        dlg.exec()

    def _update_midi_guide(self):
        """Met à jour le guide selon l'OS et le logiciel sélectionné."""
        if not hasattr(self, '_midi_guide_lbl') or not hasattr(self, '_midi_dj_combo'):
            return
        import platform
        is_mac = platform.system() == 'Darwin'
        soft = self._midi_dj_combo.currentText()
        port = LoopMidiHelper.PORT_NAME

        if is_mac:
            step1 = "① Ouvrez Audio MIDI Setup → Utilitaires"
            step2 = "② Fenêtre → Afficher le studio MIDI"
            step3 = f'③ IAC Driver → Cocher "En ligne" → + → nommer "{port}"'
        else:
            step1 = "① Téléchargez loopMIDI (tobias-erichsen.de)"
            step2 = f'② Lancez loopMIDI → cliquez "+" → nommez "{port}"'
            step3 = "③ Laissez loopMIDI actif en arrière-plan"

        if soft == "Virtual DJ":
            step4 = "④ VDJ → Paramètres → Contrôleurs → Sortie horloge MIDI"
            step5 = f'⑤ Sélectionnez "{port}" → Valider'
        elif soft == "Rekordbox":
            step4 = "④ Rekordbox → Préférences → MIDI"
            step5 = f'⑤ Activer MIDI Clock → Sortie : "{port}"'
        else:  # Serato
            step4 = "④ Installez MIDI Link (plugin Serato, gratuit)"
            step5 = f'⑤ MIDI Link → Sortie : "{port}"'

        step6 = "⑥ Dans MyStrow → Source : MIDI Clock ✓"

        self._midi_guide_lbl.setText(
            f"{step1}\n{step2}\n{step3}\n{step4}\n{step5}\n{step6}"
        )

    def _refresh_midi_ctrl_combo(self):
        """Remplit le combo avec les ports MIDI disponibles."""
        if not hasattr(self, '_midi_ctrl_combo'):
            return
        self._midi_ctrl_combo.clear()
        try:
            try:
                import rtmidi as _rm
                ports = _rm.MidiIn().get_ports()
            except Exception:
                import rtmidi2 as _rm2
                ports = _rm2.get_in_ports()
            if not ports:
                self._midi_ctrl_combo.addItem("Aucun port MIDI détecté")
            else:
                for p in ports:
                    self._midi_ctrl_combo.addItem(p)
                # Pré-sélectionner le port MyStrow si présent
                for i in range(self._midi_ctrl_combo.count()):
                    if 'mystrow' in self._midi_ctrl_combo.itemText(i).lower():
                        self._midi_ctrl_combo.setCurrentIndex(i)
                        break
        except Exception:
            self._midi_ctrl_combo.addItem("rtmidi non disponible")

    def _refresh_midi_status(self):
        installed = LoopMidiHelper.is_installed()
        has_port  = LoopMidiHelper.has_port() if installed else False

        if has_port:
            self._midi_dot.setStyleSheet(
                "background: #00cc44; border-radius: 5px;")
            self._midi_status_lbl.setText(
                f'Port "{LoopMidiHelper.PORT_NAME}" actif')
            self._midi_btn.setText("↺  Rafraîchir")
            self._midi_instr_lbl.show()
        elif installed:
            self._midi_dot.setStyleSheet(
                "background: #ffaa00; border-radius: 5px;")
            self._midi_status_lbl.setText(
                "loopMIDI installé · port manquant")
            self._midi_btn.setText(f'Créer le port "{LoopMidiHelper.PORT_NAME}"')
            self._midi_instr_lbl.hide()
        else:
            self._midi_dot.setStyleSheet(
                "background: #444; border-radius: 5px;")
            self._midi_status_lbl.setText("loopMIDI non installé (gratuit)")
            self._midi_btn.setText("Installer loopMIDI  ↗")
            self._midi_instr_lbl.hide()

    def _on_midi_btn_clicked(self):
        installed = LoopMidiHelper.is_installed()
        has_port  = LoopMidiHelper.has_port() if installed else False

        if not installed:
            LoopMidiHelper.open_download()
        elif not has_port:
            ok, msg = LoopMidiHelper.create_port()
            self._midi_status_lbl.setText(msg)
            # Vérifier si le port est apparu après démarrage de loopMIDI
            QTimer.singleShot(2000, self._refresh_midi_status)
        else:
            self._refresh_midi_status()

    def _set_conn_dot(self, status: str):
        """status : 'off' | 'waiting' | 'connected'"""
        colors = {'off': '#2a2a2a', 'waiting': '#ff8800', 'connected': '#00cc44'}
        bg = colors.get(status, '#2a2a2a')
        self._conn_dot.setStyleSheet(
            f"background: {bg}; border-radius: 5px; border: 1px solid #111;")

    def set_connection_status(self, status: str):
        """Appelé par le moteur : 'off' | 'waiting' | 'connected'"""
        self._set_conn_dot(status)

    def set_device_info(self, text: str):
        self.device_lbl.setText(text)
        t = text.lower()
        if any(k in t for k in ('erreur', 'manquant', 'introuvable', 'aucun', 'échoué')):
            color = "#cc4400"
        elif any(k in t for k in ('loopback', 'wasapi', 'micro', 'midi', 'rekordbox', 'virtual dj')):
            color = "#00aa55"
        else:
            color = "#666"
        self.device_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; font-style: italic; padding-left: 104px;")
        # Aussi mettre à jour le sous-titre de la carte INPUT
        if hasattr(self, '_input_device_lbl') and text and text != "—":
            self._input_device_lbl.setText(text)
            self._input_device_lbl.setStyleSheet(
                f"color:{color}; font-size:9px; font-style:italic;"
                " background:transparent; border:none;")

    def set_vu(self, value_0_100):
        v = int(max(0, min(100, value_0_100)))
        self.vu_bar.setValue(v)
        self._input_level_bar.setValue(v)

    def set_status(self, bpm=None, section=None, bpm_confidence: float = -1.0):
        if bpm is not None:
            self.set_bpm_auto(bpm)
        if bpm_confidence >= 0.0 and hasattr(self, '_bpm_conf_bar'):
            conf_pct = int(bpm_confidence * 100)
            self._bpm_conf_bar.setValue(conf_pct)
            if bpm_confidence >= 0.65:
                color = '#00cc55'   # vert — stable
            elif bpm_confidence >= 0.35:
                color = '#ffaa00'   # orange — moyen
            else:
                color = '#ff3333'   # rouge — incertain
            self._bpm_conf_bar.setStyleSheet(
                "QProgressBar { background:#1a1a1a; border:none; border-radius:2px; }"
                f"QProgressBar::chunk {{ background:{color}; border-radius:2px; }}"
            )
            # Afficher la barre uniquement quand le BPM est actif
            self._bpm_conf_bar.setVisible(conf_pct > 0)

    def _pulse_tick(self):
        pass  # indicateur de section retiré

    # ── Panel Mouvements Lyre ─────────────────────────────────────────────────

    # (key, color1_hex|None, color2_hex|None, label)
    # color1=None → AUTO (suit la palette IA)
    # color2!=None → bicolore (lyres alternées A/B)
    _COLOR_TILES = [
        # (key, c1, c2, label, category)
        # CHAUD
        ('rouge',        '#ff1133', None,      'ROUGE',    'chaud'),
        ('orange',       '#ff8800', None,      'ORANGE',   'chaud'),
        ('jaune',        '#ffee00', None,      'JAUNE',    'chaud'),
        ('ambre',        '#ffaa00', None,      'AMBRE',    'chaud'),
        ('rose',         '#ff44aa', None,      'ROSE',     'chaud'),
        ('rose_chaud',   '#ff2266', None,      'R.CHAUD',  'chaud'),
        # FROID
        ('vert',         '#00ff55', None,      'VERT',     'froid'),
        ('cyan',         '#00eeff', None,      'CYAN',     'froid'),
        ('bleu',         '#0055ff', None,      'BLEU',     'froid'),
        ('bleu_nuit',    '#001aff', None,      'B.NUIT',   'froid'),
        ('violet',       '#aa22ff', None,      'VIOLET',   'froid'),
        ('lavande',      '#cc88ff', None,      'LAVANDE',  'froid'),
        # NEUTRE
        ('blanc',        '#ffffff', None,      'BLANC',    'neutre'),
        ('auto',         None,      None,      'AUTO',     'neutre'),
        # BICOULEUR
        ('bi_rb',        '#ff1133', '#0055ff', 'R+B',      'bi'),
        ('bi_vo',        '#aa22ff', '#ff8800', 'V+O',      'bi'),
        ('bi_vj',        '#00ff55', '#ffee00', 'V+J',      'bi'),
        ('bi_rv',        '#ff1133', '#aa22ff', 'R+V',      'bi'),
        ('bi_cc',        '#ff8800', '#00eeff', 'CH+FR',    'bi'),
        ('bi_bv',        '#0055ff', '#00ff55', 'B+V',      'bi'),
    ]

    _MOVEMENTS = [
        ('vague',     '〜', 'VAGUE'),
        ('cercle',    '○',  'CERCLE'),
        ('diagonale', '╱',  'DIAGONALE'),
        ('random',    '✦',  'RANDOM'),
        ('spirale',   '⊛',  'SPIRALE'),
        ('bounce',    '⇔',  'BOUNCE'),
        ('huit',      '∞',  'HUIT'),
        ('pixel',     '⠿',  'PIXEL'),
    ]

    # (key, icon, label, description, accent_color)
    _SPECIAL_TILES = [
        ('strobe',         '⚡', 'STROBE',         'Stroboscope blanc · suit le BPM',          '#e0e0e0'),
        ('strobe_couleur', '⚡', 'STROBE COULEUR',  'Stroboscope coloré · couleur active',      '#ff8833'),
        ('fixe_blanc',     '◻', 'FIXE BLANC',      'Plein blanc statique à 100 %',             '#ffffbb'),
    ]

    _MOV_SLIDER_STYLE = """
        QSlider::groove:horizontal {
            border: 1px solid #2a2040; height: 5px;
            background: #1a1030; border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: #6622ee; border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #aa77ff; border: 2px solid #ffffff;
            width: 14px; margin: -5px 0; border-radius: 7px;
        }
    """

    # ── Presets live ─────────────────────────────────────────────────────────

    def _build_preset_row(self) -> QHBoxLayout:
        """Ligne P1–P4 : clic simple = rappeler, clic long (>500ms) = sauvegarder."""
        row = QHBoxLayout()
        row.setSpacing(6)

        preset_lbl = QLabel("PRESETS")
        preset_lbl.setStyleSheet(
            "color:#888; font-size:10px; font-weight:bold; letter-spacing:1.5px;")
        row.addWidget(preset_lbl)
        row.addStretch()

        self._preset_btns: list[QPushButton] = []
        for i in range(4):
            btn = QPushButton(f"P{i+1}")
            btn.setFixedSize(36, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"Clic = rappeler  |  Clic long = sauvegarder  (Preset {i+1})")
            self._update_preset_btn_style(btn, i)
            btn.pressed.connect(lambda _=False, idx=i: self._on_preset_pressed(idx))
            btn.released.connect(lambda _=False, idx=i: self._on_preset_released(idx))
            self._preset_btns.append(btn)
            row.addWidget(btn)

        return row

    def _update_preset_btn_style(self, btn: QPushButton, idx: int):
        filled = (
            idx < len(self._live_presets)
            and self._live_presets[idx] is not None
        )
        if filled:
            btn.setStyleSheet(
                "QPushButton { background:#1a3a1a; color:#88ee88;"
                " border:1px solid #44aa44; border-radius:4px;"
                " font-size:9px; font-weight:bold; }"
                "QPushButton:hover { background:#224422; border-color:#66cc66; }"
                "QPushButton:pressed { background:#2a5a2a; }"
            )
        else:
            btn.setStyleSheet(
                "QPushButton { background:#141414; color:#444;"
                " border:1px solid #252525; border-radius:4px;"
                " font-size:9px; font-weight:bold; }"
                "QPushButton:hover { color:#666; }"
            )

    def _on_preset_pressed(self, idx: int):
        import time as _t
        self._preset_press_ts[idx] = _t.monotonic()

    def _on_preset_released(self, idx: int):
        import time as _t
        held = _t.monotonic() - self._preset_press_ts[idx]
        if held >= 0.5:
            self._save_preset(idx)
        else:
            self._recall_preset(idx)

    def _current_live_state(self) -> dict:
        """Capture l'état complet du panneau live dans un dict sérialisable."""
        return {
            'color_pool':       list(self._color_tile_pool),
            'current_color':    self._current_color,
            'color_duration':   self._color_duration,
            'color_max':        self._color_max,
            'mov_patterns':     list(self._movement_patterns),
            'current_mov':      self._current_movement,
            'mov_speed':        self._movement_speed,
            'mov_size':         self._movement_size,
            'mov_duration':     self._movement_duration,
            'gobo_pool':        list(self._gobo_pool),
            'current_gobo':     self._current_gobo,
            'gobo_duration':    self._gobo_duration,
            'gobo_rotation':    self._gobo_rotation,
            'gobo_rot_speed':   self._gobo_rot_speed,
            'strob_fast':       self._strob_fast,
            'strob_slow':       self._strob_slow,
            'strob_none':       self._strob_none,
            'luminosity':       self.lumi_slider.value() if hasattr(self, 'lumi_slider') else 100,
            'dimmer_values':    dict(getattr(self, '_dimmer_values', {})),
        }

    def _save_preset(self, idx: int):
        """Clic long : enregistrer l'état courant dans le preset idx."""
        self._live_presets[idx] = self._current_live_state()
        if hasattr(self, '_preset_btns') and idx < len(self._preset_btns):
            self._update_preset_btn_style(self._preset_btns[idx], idx)
        self._request_save()

    def _recall_preset(self, idx: int):
        """Clic simple : rappeler le preset idx (si non vide)."""
        if idx >= len(self._live_presets) or self._live_presets[idx] is None:
            return
        cfg = self._live_presets[idx]
        # Appliquer la config comme dans _load_live_panel_config
        if 'color_pool' in cfg:
            self._color_tile_pool = set(cfg['color_pool'])
        if 'current_color' in cfg:
            self._current_color = cfg['current_color']
        if 'color_duration' in cfg:
            self._color_duration = int(cfg['color_duration'])
        if 'color_max' in cfg:
            self._color_max = int(cfg['color_max'])
        if 'mov_patterns' in cfg:
            self._movement_patterns = set(cfg['mov_patterns'])
        if 'current_mov' in cfg:
            self._current_movement = cfg['current_mov']
        if 'mov_speed' in cfg:
            self._movement_speed = int(cfg['mov_speed'])
        if 'mov_size' in cfg:
            self._movement_size = int(cfg['mov_size'])
        if 'mov_duration' in cfg:
            self._movement_duration = int(cfg['mov_duration'])
        if 'gobo_pool' in cfg:
            self._gobo_pool = set(int(x) for x in cfg['gobo_pool'])
        if 'current_gobo' in cfg:
            self._current_gobo = int(cfg['current_gobo'])
        if 'gobo_duration' in cfg:
            self._gobo_duration = int(cfg['gobo_duration'])
        if 'gobo_rotation' in cfg:
            self._gobo_rotation = bool(cfg['gobo_rotation'])
        if 'gobo_rot_speed' in cfg:
            self._gobo_rot_speed = int(cfg['gobo_rot_speed'])
        if 'strob_fast' in cfg:
            self._strob_fast = bool(cfg['strob_fast'])
        if 'strob_slow' in cfg:
            self._strob_slow = bool(cfg['strob_slow'])
        if 'strob_none' in cfg:
            self._strob_none = bool(cfg['strob_none'])
        if 'luminosity' in cfg and hasattr(self, 'lumi_slider'):
            self.lumi_slider.setValue(int(cfg['luminosity']))
        if 'dimmer_values' in cfg:
            self._dimmer_values = dict(cfg['dimmer_values'])
        # Rafraîchir les tuiles UI
        self._refresh_color_tiles()
        self._refresh_gobo_tiles()
        if hasattr(self, '_mov_tiles'):
            self._refresh_mov_tiles()
        # Strob tiles
        for key, attr in (('fast', '_strob_fast'), ('slow', '_strob_slow'), ('none', '_strob_none')):
            t = getattr(self, '_strob_tiles', {}).get(key)
            if t:
                v = getattr(self, attr, True)
                t.set_state(selected=v, playing=v)
        self._request_save()

    def _build_movement_panel(self) -> QWidget:
        """Conteneur principal avec onglets MOUVEMENT / COULEURS / SPÉCIAL."""
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(8)

        # ── En-tête + onglets ─────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        mov_lbl = QLabel("EFFETS")
        mov_lbl.setStyleSheet(
            "color:#888; font-size:10px; font-weight:bold; letter-spacing:1.5px;")
        hdr.addWidget(mov_lbl)
        hdr.addStretch()

        self._effect_tab_on  = (
            "QPushButton { background:#1a0a3a; color:#aa77ff;"
            " border:1px solid #6622ee; border-radius:4px;"
            " font-size:9px; font-weight:bold; padding:3px 8px; }"
        )
        self._effect_tab_off = (
            "QPushButton { background:#141414; color:#555;"
            " border:1px solid #252525; border-radius:4px;"
            " font-size:9px; font-weight:bold; padding:3px 8px; }"
            "QPushButton:hover { color:#888; }"
        )
        self._effect_tab_btns: dict[str, QPushButton] = {}
        for i, tab_label in enumerate(("MOUVEMENT", "DIMMER", "COULEURS", "GOBO", "STROB", "SPÉCIAL")):
            btn = QPushButton(tab_label)
            btn.setFixedHeight(22)
            btn.setStyleSheet(self._effect_tab_on if i == 0 else self._effect_tab_off)
            btn.clicked.connect(lambda _=False, idx=i: self._switch_effect_tab(idx))
            self._effect_tab_btns[tab_label] = btn
            hdr.addWidget(btn)

        vbox.addLayout(hdr)

        # ── Pages (QStackedWidget) ────────────────────────────────────────
        self._effect_stack = QStackedWidget()
        self._effect_stack.addWidget(self._build_movement_content())  # 0
        self._effect_stack.addWidget(self._build_dimmer_content())    # 1
        self._effect_stack.addWidget(self._build_color_content())     # 2
        self._effect_stack.addWidget(self._build_gobo_content())      # 3
        self._effect_stack.addWidget(self._build_strob_content())     # 4
        self._effect_stack.addWidget(self._build_special_content())   # 5
        self._effect_stack.setCurrentIndex(0)
        vbox.addWidget(self._effect_stack)

        return container

    def _switch_effect_tab(self, idx: int):
        """Bascule entre les onglets MOUVEMENT / DIMMER / COULEURS / GOBO / STROB / SPÉCIAL."""
        self._effect_stack.setCurrentIndex(idx)
        for i, label in enumerate(("MOUVEMENT", "DIMMER", "COULEURS", "GOBO", "STROB", "SPÉCIAL")):
            self._effect_tab_btns[label].setStyleSheet(
                self._effect_tab_on if i == idx else self._effect_tab_off)

    # ── Page 0 : Mouvements ───────────────────────────────────────────────────

    def _build_movement_content(self) -> QWidget:
        """Grille de patterns de mouvement + sliders VITESSE/TAILLE/DURÉE."""
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 4, 0, 0)
        vbox.setSpacing(8)

        self._mov_tiles: dict[str, _MovTile] = {}
        for row_idx in range(2):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            for col_idx in range(4):
                i = row_idx * 4 + col_idx
                key, icon, label = self._MOVEMENTS[i]
                tile = _MovTile(key, icon, label, w)
                tile.clicked.connect(self._on_movement_selected)
                tile.set_state(
                    selected=key in self._movement_patterns,
                    playing=key == self._current_movement,
                )
                self._mov_tiles[key] = tile
                row_layout.addWidget(tile)
            vbox.addLayout(row_layout)

        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(10)

        def _make_slider(lbl_txt: str, value: int, attr: str) -> QHBoxLayout:
            h = QHBoxLayout()
            h.setSpacing(5)
            lbl = QLabel(lbl_txt)
            lbl.setStyleSheet(
                "color:#666; font-size:9px; font-weight:bold; letter-spacing:0.5px;")
            lbl.setFixedWidth(44)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(value)
            sl.setStyleSheet(self._MOV_SLIDER_STYLE)
            val_lbl = QLabel(f"{value}%")
            val_lbl.setFixedWidth(28)
            val_lbl.setStyleSheet("color:#aa77ff; font-size:9px; font-weight:bold;")
            sl.valueChanged.connect(lambda v, a=attr, vl=val_lbl: (
                setattr(self, a, v), vl.setText(f"{v}%")
            ))
            h.addWidget(lbl)
            h.addWidget(sl)
            h.addWidget(val_lbl)
            setattr(self, f"_mov_{attr.lstrip('_movement_')}_slider", sl)
            return h

        sliders_row.addLayout(_make_slider("VITESSE", self._movement_speed,    '_movement_speed'))
        sliders_row.addLayout(_make_slider("TAILLE",  self._movement_size,     '_movement_size'))

        # Slider DURÉE en secondes (1-30s)
        dur_h = QHBoxLayout()
        dur_h.setSpacing(4)
        dur_lbl_m = QLabel("DURÉE")
        dur_lbl_m.setStyleSheet("color:#666; font-size:9px; font-weight:bold; letter-spacing:0.5px;")
        dur_lbl_m.setFixedWidth(44)
        dur_sl_m = QSlider(Qt.Horizontal)
        dur_sl_m.setRange(0, 100)
        dur_sl_m.setValue(self._movement_duration)
        dur_sl_m.setStyleSheet(self._MOV_SLIDER_STYLE)
        dur_val_m = QLabel(f"{self._movement_duration}%")
        dur_val_m.setFixedWidth(28)
        dur_val_m.setStyleSheet("color:#aa77ff; font-size:9px; font-weight:bold;")
        dur_sl_m.valueChanged.connect(lambda v, vl=dur_val_m: (
            setattr(self, '_movement_duration', v), vl.setText(f"{v}%")
        ))
        dur_h.addWidget(dur_lbl_m)
        dur_h.addWidget(dur_sl_m)
        dur_h.addWidget(dur_val_m)
        sliders_row.addLayout(dur_h)
        vbox.addLayout(sliders_row)
        return w

    # ── Page 1 : Dimmer par groupe ───────────────────────────────────────────

    _DIMMER_GROUPS = [
        ('face',     'A'),
        ('lat',      'B'),
        ('contre',   'C'),
        ('douche1',  'D'),
        ('douche2',  'E'),
        ('douche3',  'F'),
        ('groupe_g', 'G'),
        ('groupe_h', 'H'),
        ('lyre',     'LYRES'),
    ]

    def _build_dimmer_content(self) -> QWidget:
        """Sliders de dimmer max par groupe — contrôle en temps réel."""
        if not hasattr(self, '_dimmer_values'):
            self._dimmer_values = {g: 100 for g, _ in self._DIMMER_GROUPS}

        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 4, 0, 4)
        vbox.setSpacing(5)

        self._dimmer_sliders: dict = {}
        for group, label in self._DIMMER_GROUPS:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                "color:#666; font-size:9px; font-weight:bold; letter-spacing:0.5px;")
            lbl.setFixedWidth(54)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(self._dimmer_values.get(group, 100))
            sl.setStyleSheet(self._MOV_SLIDER_STYLE)
            val_lbl = QLabel(f"{sl.value()}%")
            val_lbl.setFixedWidth(28)
            val_lbl.setStyleSheet("color:#aa77ff; font-size:9px; font-weight:bold;")
            sl.valueChanged.connect(
                lambda v, g=group, vl=val_lbl: (
                    self._dimmer_values.__setitem__(g, v), vl.setText(f"{v}%")
                )
            )
            row.addWidget(lbl)
            row.addWidget(sl)
            row.addWidget(val_lbl)
            vbox.addLayout(row)
            self._dimmer_sliders[group] = sl

        vbox.addStretch()
        return w

    @property
    def dimmer_values(self) -> dict:
        return getattr(self, '_dimmer_values', {})

    # ── Page 2 : Couleurs lyres ───────────────────────────────────────────────

    def _build_color_content(self) -> QWidget:
        """Grille de tuiles couleur par section CHAUD/FROID/NEUTRE/BI + épinglage + DURÉE."""
        if not hasattr(self, '_pinned_colors'):
            self._pinned_colors: set = set()

        w = QWidget()
        self._color_content_widget = w
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 2, 0, 0)
        vbox.setSpacing(4)

        self._color_tiles: dict[str, _ColorTile] = {}

        def _sec_lbl(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "color:#444; font-size:8px; font-weight:bold; letter-spacing:1px;"
                " background:transparent; padding:2px 0 1px 0;")
            return lbl

        def _make_row(keys_subset):
            row = QHBoxLayout()
            row.setSpacing(4)
            for key in keys_subset:
                tile = self._color_tiles.get(key)
                if tile:
                    row.addWidget(tile)
            row.addStretch()
            return row

        # Créer toutes les tuiles
        for tdef in self._COLOR_TILES:
            key, c1, c2, label = tdef[0], tdef[1], tdef[2], tdef[3]
            tile = _ColorTile(key, c1, c2, label, w)
            tile.set_state(
                selected=key in self._color_tile_pool,
                playing=key == self._current_color,
            )
            tile.clicked.connect(self._on_color_tile_selected)
            tile.setContextMenuPolicy(Qt.CustomContextMenu)
            tile.customContextMenuRequested.connect(
                lambda pos, k=key: self._on_color_pin_menu(k))
            self._color_tiles[key] = tile

        # ── Section Épinglés ──────────────────────────────────────────────
        self._pinned_section_lbl = _sec_lbl("📌  ÉPINGLÉS")
        self._pinned_row_layout  = QHBoxLayout()
        self._pinned_row_layout.setSpacing(4)
        self._pinned_section_container = QWidget()
        self._pinned_section_container.setStyleSheet("background:transparent;")
        psc_v = QVBoxLayout(self._pinned_section_container)
        psc_v.setContentsMargins(0, 0, 0, 0)
        psc_v.setSpacing(2)
        psc_v.addWidget(self._pinned_section_lbl)
        psc_v.addLayout(self._pinned_row_layout)
        vbox.addWidget(self._pinned_section_container)
        self._pinned_section_container.setVisible(bool(self._pinned_colors))

        # ── Toutes les couleurs en grille ─────────────────────────────────
        all_keys = [row[0] for row in self._COLOR_TILES]
        cols = 8
        for i in range(0, len(all_keys), cols):
            vbox.addLayout(_make_row(all_keys[i:i + cols]))

        # ── Nombre de couleurs max simultanées ────────────────────────────
        max_row = QHBoxLayout()
        max_row.setSpacing(5)
        max_lbl = QLabel("COULEURS SIMULTANÉES")
        max_lbl.setStyleSheet(
            "color:#666; font-size:9px; font-weight:bold; letter-spacing:0.5px;")
        max_row.addWidget(max_lbl)
        max_row.addStretch()
        for n in (1, 2, 3, 4):
            btn = QPushButton(str(n))
            btn.setFixedSize(26, 22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background:#1a0a3a; color:#aa77ff; border:1px solid #6622ee;"
                " border-radius:3px; font-size:10px; font-weight:bold; }"
                if n == self._color_max else
                "QPushButton { background:#141414; color:#555; border:1px solid #252525;"
                " border-radius:3px; font-size:10px; font-weight:bold; }"
                "QPushButton:hover { color:#888; }"
            )
            btn.clicked.connect(lambda _, v=n: self._on_color_max(v))
            max_row.addWidget(btn)
            setattr(self, f'_color_max_btn_{n}', btn)
        vbox.addLayout(max_row)

        # ── Slider DURÉE ──────────────────────────────────────────────────
        vbox.addSpacing(4)
        dur_row = QHBoxLayout()
        dur_row.setSpacing(5)
        dur_lbl = QLabel("DURÉE")
        dur_lbl.setStyleSheet(
            "color:#666; font-size:9px; font-weight:bold; letter-spacing:0.5px;")
        dur_lbl.setFixedWidth(44)
        dur_sl = QSlider(Qt.Horizontal)
        dur_sl.setRange(0, 100)
        dur_sl.setValue(self._color_duration)
        dur_sl.setStyleSheet(self._MOV_SLIDER_STYLE)
        dur_val = QLabel(f"{self._color_duration}%")
        dur_val.setFixedWidth(28)
        dur_val.setStyleSheet("color:#aa77ff; font-size:9px; font-weight:bold;")
        dur_sl.valueChanged.connect(lambda v, vl=dur_val: (
            setattr(self, '_color_duration', v), vl.setText(f"{v}%")
        ))
        dur_row.addWidget(dur_lbl)
        dur_row.addWidget(dur_sl)
        dur_row.addWidget(dur_val)
        vbox.addLayout(dur_row)
        vbox.addStretch()

        self._refresh_pinned_row()
        return w

    def _on_color_pin_menu(self, key: str):
        """Menu contextuel clic droit : Épingler / Désépingler."""
        if not hasattr(self, '_pinned_colors'):
            self._pinned_colors = set()
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background:#1a1a1a; color:#ccc; border:1px solid #333; padding:4px; }"
            "QMenu::item { padding:6px 16px; border-radius:3px; }"
            "QMenu::item:selected { background:#2a2a3a; color:#aa77ff; }"
        )
        if key in self._pinned_colors:
            act = menu.addAction("📌  Désépingler")
            act.triggered.connect(lambda: self._toggle_pin(key))
        else:
            act = menu.addAction("📌  Épingler en haut")
            act.triggered.connect(lambda: self._toggle_pin(key))
        tile = self._color_tiles.get(key)
        if tile:
            menu.exec(tile.mapToGlobal(tile.rect().center()))

    def _toggle_pin(self, key: str):
        if not hasattr(self, '_pinned_colors'):
            self._pinned_colors = set()
        if key in self._pinned_colors:
            self._pinned_colors.discard(key)
        else:
            self._pinned_colors.add(key)
        self._refresh_pinned_row()

    def _on_color_max(self, value: int):
        self._color_max = value
        _SS_ON  = ("QPushButton { background:#1a0a3a; color:#aa77ff; border:1px solid #6622ee;"
                   " border-radius:3px; font-size:10px; font-weight:bold; }")
        _SS_OFF = ("QPushButton { background:#141414; color:#555; border:1px solid #252525;"
                   " border-radius:3px; font-size:10px; font-weight:bold; }"
                   "QPushButton:hover { color:#888; }")
        for n in (1, 2, 3, 4):
            btn = getattr(self, f'_color_max_btn_{n}', None)
            if btn:
                btn.setStyleSheet(_SS_ON if n == value else _SS_OFF)
        self._request_save()

    def _refresh_pinned_row(self):
        if not hasattr(self, '_pinned_row_layout'):
            return
        # Vider la rangée épinglés
        while self._pinned_row_layout.count():
            item = self._pinned_row_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        pinned = [row[0] for row in self._COLOR_TILES if row[0] in self._pinned_colors]
        for key in pinned:
            tile = self._color_tiles.get(key)
            if tile:
                self._pinned_row_layout.addWidget(tile)
        self._pinned_row_layout.addStretch()
        has_pins = bool(pinned)
        if hasattr(self, '_pinned_section_container'):
            self._pinned_section_container.setVisible(has_pins)

    # ── Page 2 : Spécial ─────────────────────────────────────────────────────

    def _build_special_content(self) -> QWidget:
        """Trois tuiles d'effets spéciaux (STROBE / STROBE COULEUR / FIXE BLANC)."""
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 4, 0, 4)
        vbox.setSpacing(6)

        self._special_tiles: dict = {}
        row = QHBoxLayout()
        row.setSpacing(5)
        for key, icon, label, desc, accent in self._SPECIAL_TILES:
            tile = _SpecialTile(key, icon, label, desc, accent, w)
            tile.set_active(key == self._active_special)
            tile.clicked.connect(self._on_special_tile_selected)
            self._special_tiles[key] = tile
            row.addWidget(tile)
        vbox.addLayout(row)

        vbox.addStretch()
        return w

    def _on_special_tile_selected(self, key: str):
        """Radio toggle : active la tuile (clic sur l'actif = désactive)."""
        if self._active_special == key:
            self._active_special = None
        else:
            self._active_special = key
        self._refresh_special_tiles()
        self._request_save()

    def _refresh_special_tiles(self):
        """Rafraîchit l'apparence de toutes les tuiles spéciales."""
        if not hasattr(self, '_special_tiles'):
            return
        for k, tile in self._special_tiles.items():
            tile.set_active(k == self._active_special)

    # ── Page 4 : Strob ───────────────────────────────────────────────────────

    def _build_strob_content(self) -> QWidget:
        """3 tuiles toggle : STROB RAPIDE / STROB LENT / PAS DE STROB."""
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 4, 0, 4)
        vbox.setSpacing(6)

        defs = [
            ('fast', '⚡', 'RAPIDE',   '_strob_fast'),
            ('slow', '〜', 'LENT',     '_strob_slow'),
            ('none', '○', 'Pas de Strobe', '_strob_none'),
        ]

        self._strob_tiles: dict = {}
        row = QHBoxLayout()
        row.setSpacing(5)
        for key, icon, label, attr in defs:
            tile = _MovTile(key, icon, label)
            tile.set_state(selected=True, playing=True)   # tous actifs par défaut
            tile.clicked.connect(lambda _k, a=attr, t=key: self._on_strob_toggle(a, t))
            self._strob_tiles[key] = tile
            row.addWidget(tile)
        vbox.addLayout(row)

        info = QLabel(
            "RAPIDE : strobe beat rapide\n"
            "LENT : strobe lent / build\n"
            "PAS DE : autorise absence de strobe"
        )
        info.setStyleSheet(
            "color:#333; font-size:8px; background:transparent; padding-top:6px;")
        vbox.addWidget(info)
        vbox.addStretch()
        return w

    def _on_strob_toggle(self, attr: str, key: str):
        setattr(self, attr, not getattr(self, attr))
        v = getattr(self, attr)
        t = self._strob_tiles.get(key)
        if t:
            t.set_state(selected=v, playing=v)
        self._request_save()

    # ── Sources audio dynamiques ─────────────────────────────────────────────

    def _refresh_audio_sources(self):
        """Enrichit self.SOURCES avec les périphériques audio détectés sur ce PC."""
        try:
            from live_audio import get_audio_devices
            devices = get_audio_devices()
        except Exception:
            return
        sources = list(self._SOURCES_STATIC)
        if devices:
            sources.append(("─── Périphériques ───", None))
            for d in devices:
                sources.append((d['label'], d['key']))
        # Mettre à jour la liste de classe pour ce panel
        LiveModePanel.SOURCES = sources
        # Mettre à jour le combo si déjà créé
        if hasattr(self, 'source_combo'):
            current = self.source_combo.currentData() or 'loopback'
            self.source_combo.blockSignals(True)
            self.source_combo.clear()
            for label, key in sources:
                if key is None:
                    self.source_combo.addItem(label)
                    idx = self.source_combo.count() - 1
                    item = self.source_combo.model().item(idx)
                    if item:
                        item.setEnabled(False)
                else:
                    self.source_combo.addItem(label, key)
            for i in range(self.source_combo.count()):
                if self.source_combo.itemData(i) == current:
                    self.source_combo.setCurrentIndex(i)
                    break
            self.source_combo.blockSignals(False)

    def _on_beta_contact_clicked(self, _href):
        """Ouvre la fenêtre Soumettre une idée depuis le lien bêta."""
        main_win = self.window()
        if hasattr(main_win, '_show_idea_dialog'):
            main_win._show_idea_dialog()

    # ── Adaptation dynamique aux fixtures patchées ───────────────────────────

    def adapt_to_fixtures(self, projectors):
        """Adapte les onglets et couleurs selon les fixtures patchées."""
        has_moving = any(getattr(p, 'fixture_type', '') == 'Moving Head'    for p in projectors)
        has_led    = any(getattr(p, 'fixture_type', '') in (
            'PAR LED', 'Barre LED', 'Gradateur', 'Stroboscope') for p in projectors)

        # ── Visibilité des onglets MOUVEMENT et GOBO ─────────────────────
        for tab_name in ("MOUVEMENT", "GOBO"):
            btn = self._effect_tab_btns.get(tab_name)
            if btn:
                btn.setVisible(has_moving)

        # Si l'onglet actif est masqué, basculer sur COULEURS (index 1)
        cur = self._effect_stack.currentIndex()
        tab_labels = ("MOUVEMENT", "COULEURS", "GOBO", "SPÉCIAL")
        if cur < len(tab_labels):
            cur_label = tab_labels[cur]
            if cur_label in ("MOUVEMENT", "GOBO") and not has_moving:
                self._switch_effect_tab(1)

        # ── Filtrage des couleurs ─────────────────────────────────────────
        if not hasattr(self, '_color_tiles'):
            return

        if has_moving and not has_led:
            # Uniquement des lyres → filtrer selon la roue couleur
            _NAME_MAP = {
                'red': 'rouge',    'rouge': 'rouge',
                'orange': 'orange',
                'yellow': 'jaune', 'jaune': 'jaune',
                'green': 'vert',   'vert': 'vert',
                'cyan': 'cyan',    'turquoise': 'cyan',
                'blue': 'bleu',    'bleu': 'bleu',
                'violet': 'violet','purple': 'violet', 'magenta': 'violet',
                'white': 'blanc',  'blanc': 'blanc',   'open': 'blanc',
                'pink': 'rose',    'rose': 'rose',
                'amber': 'ambre',  'ambre': 'ambre',
            }
            wheel_keys = {'auto'}
            for p in projectors:
                if getattr(p, 'fixture_type', '') == 'Moving Head':
                    for slot in getattr(p, 'color_wheel_slots', []):
                        name = slot.get('name', '').lower().strip()
                        key = _NAME_MAP.get(name)
                        if key:
                            wheel_keys.add(key)

            for tile_key, tile in self._color_tiles.items():
                tdef = next((r for r in self._COLOR_TILES if r[0] == tile_key), None)
                is_bi = tdef and tdef[4] == 'bi'
                tile.setVisible(is_bi or tile_key in wheel_keys)
        else:
            # PAR LED présents (ou mixte) → tout afficher
            for tile in self._color_tiles.values():
                tile.setVisible(True)

    # ── Page 3 : Gobo ────────────────────────────────────────────────────────

    def _build_gobo_content(self) -> QWidget:
        """Grille de slots gobo + toggle rotation + vitesse — design _MovTile."""
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 4, 0, 4)
        vbox.setSpacing(6)

        # Grille 2×4 : OUVERT + Gobo 1-7
        self._gobo_tiles: list = []
        slot_defs = [
            ('○', 'OUVERT'), ('①', 'G1'), ('②', 'G2'), ('③', 'G3'),
            ('④', 'G4'),     ('⑤', 'G5'), ('⑥', 'G6'), ('⑦', 'G7'),
        ]
        for row_idx in range(2):
            row = QHBoxLayout()
            row.setSpacing(5)
            for col_idx in range(4):
                i = row_idx * 4 + col_idx
                icon, lbl = slot_defs[i]
                tile = _MovTile(str(i), icon, lbl)
                tile.set_state(selected=(i in self._gobo_pool),
                               playing=(i == self._current_gobo))
                tile.clicked.connect(lambda _key, idx=i: self._on_gobo_slot(idx))
                self._gobo_tiles.append(tile)
                row.addWidget(tile)
            vbox.addLayout(row)

        # Rotation — tuile _MovTile façon toggle
        rot_row = QHBoxLayout()
        rot_row.setSpacing(5)
        self._gobo_rot_tile = _MovTile('rot', '↻', 'ROTATION')
        self._gobo_rot_tile.set_state(selected=self._gobo_rotation,
                                      playing=self._gobo_rotation)
        self._gobo_rot_tile.clicked.connect(self._on_gobo_rot_toggle)
        rot_row.addWidget(self._gobo_rot_tile)
        rot_row.addStretch()
        vbox.addLayout(rot_row)

        # Slider DURÉE (temps par gobo)
        dur_row = QHBoxLayout()
        dur_row.setSpacing(4)
        dur_lbl = QLabel("DURÉE")
        dur_lbl.setStyleSheet(
            "color:#666; font-size:9px; font-weight:bold; letter-spacing:0.5px;")
        dur_lbl.setFixedWidth(48)
        dur_sl = QSlider(Qt.Horizontal)
        dur_sl.setRange(0, 100)
        dur_sl.setValue(self._gobo_duration)
        dur_sl.setStyleSheet(self._MOV_SLIDER_STYLE)
        dur_val = QLabel(f"{self._gobo_duration}%")
        dur_val.setFixedWidth(28)
        dur_val.setStyleSheet("color:#aa77ff; font-size:9px; font-weight:bold;")
        dur_sl.valueChanged.connect(lambda v, vl=dur_val: (
            setattr(self, '_gobo_duration', v), vl.setText(f"{v}%")
        ))
        dur_row.addWidget(dur_lbl)
        dur_row.addWidget(dur_sl)
        dur_row.addWidget(dur_val)
        vbox.addLayout(dur_row)

        # Slider vitesse rotation
        spd_row = QHBoxLayout()
        spd_row.setSpacing(4)
        spd_lbl = QLabel("ROTATION")
        spd_lbl.setStyleSheet(
            "color:#666; font-size:9px; font-weight:bold; letter-spacing:0.5px;")
        spd_lbl.setFixedWidth(48)
        spd_sl = QSlider(Qt.Horizontal)
        spd_sl.setRange(1, 100)
        spd_sl.setValue(self._gobo_rot_speed)
        spd_sl.setStyleSheet(self._MOV_SLIDER_STYLE)
        spd_val = QLabel(f"{self._gobo_rot_speed}%")
        spd_val.setFixedWidth(28)
        spd_val.setStyleSheet("color:#aa77ff; font-size:9px; font-weight:bold;")
        spd_sl.valueChanged.connect(lambda v, vl=spd_val: (
            setattr(self, '_gobo_rot_speed', v), vl.setText(f"{v}%")
        ))
        spd_row.addWidget(spd_lbl)
        spd_row.addWidget(spd_sl)
        spd_row.addWidget(spd_val)
        vbox.addLayout(spd_row)

        vbox.addStretch()
        return w

    def _on_gobo_slot(self, idx: int):
        if idx in self._gobo_pool:
            if len(self._gobo_pool) <= 1:
                return
            self._gobo_pool.discard(idx)
            if self._current_gobo == idx:
                self._current_gobo = min(self._gobo_pool)
        else:
            self._gobo_pool.add(idx)
            self._current_gobo = idx
        self._refresh_gobo_tiles()
        self._request_save()

    def _refresh_gobo_tiles(self):
        if not hasattr(self, '_gobo_tiles'):
            return
        for i, tile in enumerate(self._gobo_tiles):
            tile.set_state(
                selected=(i in self._gobo_pool),
                playing=(i == self._current_gobo),
            )

    def _on_gobo_rot_toggle(self, _key):
        self._gobo_rotation = not self._gobo_rotation
        if hasattr(self, '_gobo_rot_tile'):
            self._gobo_rot_tile.set_state(selected=self._gobo_rotation,
                                           playing=self._gobo_rotation)
        self._request_save()

    @property
    def strob_fast(self) -> bool:
        return self._strob_fast

    @property
    def strob_slow(self) -> bool:
        return self._strob_slow

    @property
    def strob_none(self) -> bool:
        return self._strob_none

    @property
    def gobo_pool(self) -> list:
        """Slots gobo sélectionnés, triés."""
        return sorted(self._gobo_pool)

    @property
    def current_gobo(self) -> int:
        return self._current_gobo

    @property
    def gobo_duration(self) -> int:
        return self._gobo_duration

    @property
    def gobo_rotation(self) -> bool:
        return self._gobo_rotation

    @property
    def gobo_rot_speed(self) -> int:
        return self._gobo_rot_speed

    # ── Handlers couleur ─────────────────────────────────────────────────────

    def _on_color_tile_selected(self, key: str):
        """Toggle une tuile couleur dans/hors du pool.
        Cliquer sur une tuile la rend immédiatement 'en cours'."""
        if key in self._color_tile_pool:
            if len(self._color_tile_pool) <= 1:
                return   # ne peut pas décocher la dernière
            self._color_tile_pool.discard(key)
            if self._current_color == key:
                order = [row[0] for row in self._COLOR_TILES]
                for k in order:
                    if k in self._color_tile_pool:
                        self._current_color = k
                        break
        else:
            self._color_tile_pool.add(key)
            self._current_color = key   # ← joue immédiatement cette couleur
        self._refresh_color_tiles()
        self._request_save()

    def set_current_color_tile(self, key: str):
        """Appelé par le moteur quand il bascule vers la prochaine couleur."""
        if key not in self._color_tile_pool or key == self._current_color:
            return
        self._current_color = key
        self._refresh_color_tiles()

    def _refresh_color_tiles(self):
        for k, tile in self._color_tiles.items():
            tile.set_state(
                selected=k in self._color_tile_pool,
                playing=k == self._current_color,
            )

    def _on_movement_selected(self, key: str):
        """Toggle un mouvement dans/hors du pool de mouvements."""
        if key in self._movement_patterns:
            # Déselectionner : interdit si c'est le dernier
            if len(self._movement_patterns) <= 1:
                return
            self._movement_patterns.discard(key)
            # Si c'était le courant, passer au premier restant (ordre _MOVEMENTS)
            if self._current_movement == key:
                order = [k for k, _, _ in self._MOVEMENTS]
                for k in order:
                    if k in self._movement_patterns:
                        self._current_movement = k
                        break
        else:
            # Ajouter au pool
            self._movement_patterns.add(key)
        # Rafraîchir toutes les tuiles
        self._refresh_mov_tiles()
        self.movement_changed.emit(self._current_movement)
        self._request_save()

    def set_current_movement(self, key: str):
        """Appelé par le moteur quand il bascule vers le prochain mouvement du pool."""
        if key not in self._movement_patterns or key == self._current_movement:
            return
        self._current_movement = key
        self._refresh_mov_tiles()

    def _refresh_mov_tiles(self):
        """Met à jour l'état visuel de toutes les tuiles de mouvement."""
        for k, tile in self._mov_tiles.items():
            tile.set_state(
                selected=k in self._movement_patterns,
                playing=k == self._current_movement,
            )

    # ── Sélecteur de mode IA ──────────────────────────────────────────────────

    _MODES = [
        ('musical', '♪', 'MUSICAL IA',  'Réagit à la musique'),
        ('ambiance', '○', 'AMBIANCE IA', "Lumière d'ambiance"),
        ('manuel',  '⊟', 'MANUEL',      'Reprenez le contrôle'),
    ]

    def _build_settings_bpm_row(self) -> QHBoxLayout:
        """Carte PARAMETRE LIVE (style carteson) — BPM retiré."""
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._build_settings_block(), 1)
        # Construire la carte BPM en caché pour conserver les signaux
        self._build_bpm_card()
        return row

    def _build_settings_block(self) -> QFrame:
        """Carte PARAMETRE LIVE style carteson.png — cliquable, ouvre les paramètres."""
        card = QFrame()
        card.setObjectName("settingsCard")
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet("""
            QFrame#settingsCard {
                background: #0a1520;
                border: 1px solid #1e3a5a;
                border-radius: 10px;
            }
            QFrame#settingsCard:hover { border-color: #00aaff; }
        """)

        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(6)

        # ── Ligne 1 : label "INPUT" + gear ──────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(4)

        param_lbl = QLabel("INPUT")
        param_lbl.setStyleSheet(
            "color:#4a7a9a; font-size:9px; font-weight:bold; letter-spacing:1.5px;")
        top.addWidget(param_lbl)
        top.addStretch()

        # Dot de connexion intégré à la carte
        top.addWidget(self._conn_dot)

        vbox.addLayout(top)

        # ── Ligne 2 : nom de l'entrée (dynamique) + indicateur BEAT ─────────
        mid = QHBoxLayout()
        mid.setSpacing(8)

        self._input_name_lbl = QLabel(self._source_display_name())
        self._input_name_lbl.setStyleSheet(
            "color:#e0e0e0; font-size:16px; font-weight:bold;")
        mid.addWidget(self._input_name_lbl)

        # Bouton "?" — visible pour les sources MIDI (VDJ, Rekordbox, MIDI Clock)
        self._source_help_btn = QPushButton("?")
        self._source_help_btn.setFixedSize(20, 20)
        self._source_help_btn.setCursor(Qt.PointingHandCursor)
        self._source_help_btn.setToolTip("Guide de configuration")
        self._source_help_btn.setCheckable(True)
        self._source_help_btn.setVisible(False)
        self._source_help_btn.setStyleSheet(
            "QPushButton { background:#0a1a2a; color:#0088cc; border:1px solid #0055aa;"
            " border-radius:10px; font-size:10px; font-weight:bold; }"
            "QPushButton:checked { background:#0055aa; color:#fff; border-color:#00aaff; }"
            "QPushButton:hover { background:#0a2a3a; }"
        )
        self._source_help_btn.toggled.connect(self._toggle_midi_guide)
        mid.addWidget(self._source_help_btn)
        mid.addStretch()

        # Cercle BEAT (intégré dans la carte)
        self._beat_btn = QPushButton("●")
        self._beat_btn.setFixedSize(28, 28)
        self._beat_btn.setEnabled(False)
        self._beat_idle_style = (
            "QPushButton { background:#0d1a28; color:#1e3a5a;"
            " border:2px solid #1e3a5a; border-radius:14px; font-size:13px; }"
        )
        self._beat_active_style = (
            "QPushButton { background:#ffffff18; color:#ffffff;"
            " border:2px solid #ffffff; border-radius:14px; font-size:13px; }"
        )
        self._beat_btn.setStyleSheet(self._beat_idle_style)

        beat_col = QVBoxLayout()
        beat_col.setSpacing(1)
        beat_col.addWidget(self._beat_btn)
        beat_lbl_w = QLabel("BEAT")
        beat_lbl_w.setStyleSheet(
            "color:#2a4a5a; font-size:8px; font-weight:bold; letter-spacing:1px;")
        beat_lbl_w.setAlignment(Qt.AlignCenter)
        beat_col.addWidget(beat_lbl_w)
        mid.addLayout(beat_col)

        vbox.addLayout(mid)

        # Sous-titre : device / logiciel détecté ─────────────────────────────
        self._input_device_lbl = QLabel("")
        self._input_device_lbl.setStyleSheet(
            "color:#3a6a8a; font-size:9px; font-style:italic;"
            " background:transparent; border:none;")
        vbox.addWidget(self._input_device_lbl)

        # ── VU-mètre + Sensibilité fusionnés ──────────────────────────────────
        self._vu_sens = _VuSensWidget(initial_sens=80)
        self._vu_sens.setToolTip("Niveau audio · Glisser le marqueur blanc = seuil de sensibilité")
        # Alias pour compatibilité avec set_vu() et sens_slider
        self._input_level_bar = self._vu_sens   # set_vu appelle setValue
        self.sens_slider       = self._vu_sens._sens_proxy
        vbox.addSpacing(2)
        vbox.addWidget(self._vu_sens)

        # Label BPM — visible uniquement en source MIDI Clock
        self._midi_bpm_lbl = QLabel("")
        self._midi_bpm_lbl.setAlignment(Qt.AlignCenter)
        self._midi_bpm_lbl.setStyleSheet(
            "color:#00d4ff; font-size:18px; font-weight:bold; "
            "background:transparent; border:none; padding:2px 0;"
        )
        self._midi_bpm_lbl.setVisible(False)
        vbox.addWidget(self._midi_bpm_lbl)

        # Barre de confiance BPM (verte=stable, orange=moyen, rouge=incertain)
        self._bpm_conf_bar = QProgressBar()
        self._bpm_conf_bar.setRange(0, 100)
        self._bpm_conf_bar.setValue(0)
        self._bpm_conf_bar.setFixedHeight(4)
        self._bpm_conf_bar.setTextVisible(False)
        self._bpm_conf_bar.setVisible(False)
        self._bpm_conf_bar.setStyleSheet(
            "QProgressBar { background:#1a1a1a; border:none; border-radius:2px; }"
            "QProgressBar::chunk { background:#00cc55; border-radius:2px; }"
        )
        vbox.addWidget(self._bpm_conf_bar)

        card.mousePressEvent = lambda e: self._open_settings()
        return card

    def _build_bpm_card(self) -> QVBoxLayout:
        """Carte BPM : affichage grand + bouton SYNC + slider de réglage."""
        bpm_col = QVBoxLayout()
        bpm_col.setSpacing(6)
        bpm_col.setAlignment(Qt.AlignTop)

        bpm_card = QFrame()
        bpm_card.setFixedSize(130, 96)
        bpm_card.setStyleSheet("""
            QFrame {
                background: #0a1520;
                border: 1px solid #1e3a5a;
                border-radius: 10px;
            }
        """)
        card_vbox = QVBoxLayout(bpm_card)
        card_vbox.setContentsMargins(8, 6, 8, 7)
        card_vbox.setSpacing(4)

        self._bpm_display = QLabel("—  BPM")
        self._bpm_display.setAlignment(Qt.AlignCenter)
        self._bpm_display.setStyleSheet(self._BPM_CARD_NORMAL)
        card_vbox.addWidget(self._bpm_display)

        self._sync_btn = QPushButton("SYNC")
        self._sync_btn.setFixedHeight(20)
        self._sync_btn.setCheckable(True)
        self._sync_btn.setStyleSheet("""
            QPushButton {
                background:#1a1a1a; color:#666;
                border:1px solid #2a2a2a; border-radius:5px;
                font-size:10px; font-weight:bold; letter-spacing:1.5px;
            }
            QPushButton:checked {
                background:#001a33; color:#00aaff;
                border:1px solid #0055aa;
            }
            QPushButton:hover { background:#252525; }
            QPushButton:checked:hover { background:#002244; }
        """)
        self._sync_btn.clicked.connect(lambda _checked: self._on_sync_clicked())
        card_vbox.addWidget(self._sync_btn)

        # Slider BPM caché (conservé pour compatibilité des signaux)
        self._bpm_slider = QSlider(Qt.Horizontal)
        self._bpm_slider.setRange(60, 200)
        self._bpm_slider.setValue(120)
        self._bpm_slider.sliderMoved.connect(self._on_bpm_moved)
        self._bpm_slider.valueChanged.connect(self._on_bpm_changed)
        self._bpm_slider.hide()

        bpm_card.hide()
        bpm_col.addWidget(bpm_card)

        # Widgets cachés pour compatibilité
        self._bpm_val_lbl = QLabel("—")
        self._bpm_val_lbl.hide()
        self._bpm_auto_btn = QPushButton("AUTO ↺")
        self._bpm_auto_btn.clicked.connect(self._on_bpm_auto_reset)
        self._bpm_auto_btn.hide()

        return bpm_col

    def _build_mode_tiles(self) -> QHBoxLayout:
        self._mode_tiles: dict[str, _ModeTile] = {}
        row = QHBoxLayout()
        row.setSpacing(8)
        for key, icon, title, sub in self._MODES:
            tile = _ModeTile(key, icon, title, sub, self)
            tile.clicked.connect(self._on_mode_selected)
            tile.set_active(key == self._ia_mode)
            self._mode_tiles[key] = tile
            row.addWidget(tile)
        return row

    def _on_mode_selected(self, key: str):
        if key == self._ia_mode:
            return
        self._ia_mode = key
        for k, tile in self._mode_tiles.items():
            tile.set_active(k == key)
        self.ia_mode_changed.emit(key)
        self._request_save()

    # ── Beat + BPM ────────────────────────────────────────────────────────────

    _BPM_CARD_NORMAL  = ("color:#ffffff; font-size:22px; font-weight:bold;"
                         " background:transparent; border:none;")
    _BPM_CARD_MANUAL  = ("color:#ffaa00; font-size:22px; font-weight:bold;"
                         " background:transparent; border:none;")
    _BPM_CARD_SYNCED  = ("color:#00aaff; font-size:22px; font-weight:bold;"
                         " background:transparent; border:none;")

    def flash_beat(self):
        """Flash le bouton beat — appelé par le moteur à chaque beat détecté."""
        self._beat_btn.setStyleSheet(self._beat_active_style)
        QTimer.singleShot(80, lambda: self._beat_btn.setStyleSheet(self._beat_idle_style))

    def set_bpm_auto(self, bpm: float):
        """Met à jour l'affichage BPM en mode auto (ignoré si manuel/synced)."""
        if self._bpm_manual:
            return
        if bpm > 0:
            self._bpm_slider.blockSignals(True)
            self._bpm_slider.setValue(int(min(200, max(60, bpm))))
            self._bpm_slider.blockSignals(False)
        self._bpm_val_lbl.setText(f"{bpm:.0f}" if bpm > 0 else "—")
        self._bpm_display.setText(f"{bpm:.0f}  BPM" if bpm > 0 else "—  BPM")

        # Afficher le BPM dans la carte INPUT uniquement en source MIDI Clock
        if hasattr(self, '_midi_bpm_lbl'):
            is_midi = self.source_key == 'midi_clock'
            self._midi_bpm_lbl.setVisible(is_midi)
            if is_midi:
                self._midi_bpm_lbl.setText(f"{bpm:.0f} BPM" if bpm > 0 else "—")

    def _on_sync_clicked(self):
        """SYNC tap tempo : appuyez 2+ fois pour calculer le BPM depuis les taps."""
        import time as _t
        now = _t.monotonic()

        # Filtrer les taps trop anciens (> 3 s = nouveau cycle)
        self._sync_tap_times = [t for t in self._sync_tap_times if now - t < 3.0]
        self._sync_tap_times.append(now)
        n = len(self._sync_tap_times)

        # Annuler le timer de reset précédent
        if self._sync_reset_timer:
            self._sync_reset_timer.stop()

        if n < 2:
            # 1er tap : attente du 2e
            self._sync_btn.setChecked(False)
            self._bpm_display.setStyleSheet(self._BPM_CARD_NORMAL)
            self._bpm_display.setText("TAP...")
            return

        # Calculer BPM depuis les intervalles (max 6 derniers taps)
        taps = self._sync_tap_times[-6:]
        intervals = [taps[i+1] - taps[i] for i in range(len(taps) - 1)]
        avg_iv = sum(intervals) / len(intervals)
        bpm = max(60, min(200, round(60.0 / avg_iv)))

        # Appliquer le BPM
        self._bpm_manual = True
        self._sync_btn.setChecked(True)
        self._bpm_slider.blockSignals(True)
        self._bpm_slider.setValue(bpm)
        self._bpm_slider.blockSignals(False)
        self._bpm_display.setStyleSheet(self._BPM_CARD_SYNCED)
        self._bpm_display.setText(f"{bpm}  BPM")
        self.bpm_override.emit(float(bpm))

        # Après 4 s sans tap : retour en mode auto
        if self._sync_reset_timer is None:
            self._sync_reset_timer = QTimer()
            self._sync_reset_timer.setSingleShot(True)
            self._sync_reset_timer.timeout.connect(self._on_sync_tap_expired)
        self._sync_reset_timer.start(4000)

    def _on_sync_tap_expired(self):
        """4 s sans tap → libérer le BPM manuel et repasser en auto."""
        self._sync_tap_times.clear()
        self._on_bpm_auto_reset()

    def _on_bpm_moved(self):
        """Déclenché quand l'utilisateur glisse le handle du slider."""
        if not self._bpm_manual:
            self._bpm_manual = True
            self._sync_btn.setChecked(True)
            self._bpm_display.setStyleSheet(self._BPM_CARD_MANUAL)

    def _on_bpm_changed(self, value: int):
        self._bpm_val_lbl.setText(str(value))
        if self._bpm_manual:
            self._bpm_display.setText(f"{value}  BPM")
            self.bpm_override.emit(float(value))

    def _on_bpm_auto_reset(self):
        self._bpm_manual = False
        self._bpm_auto_btn.hide()
        self._sync_btn.setChecked(False)
        self._bpm_display.setStyleSheet(self._BPM_CARD_NORMAL)
        self._bpm_val_lbl.setStyleSheet(
            "color:#00d4ff; font-size:14px; font-weight:bold; min-width:36px;")
        self.bpm_released.emit()

    # ── Lyre mode ──────────────────────────────────────────────────────────────

    @property
    def lyre_mode(self) -> str:
        return ''

    # ── Tile state ────────────────────────────────────────────────────────────

    def is_tile_active(self, tile_id: str) -> bool:
        return False

    # ── Color presets ─────────────────────────────────────────────────────────

    def _on_color_preset(self, hex_color: str):
        c = QColor(hex_color)
        if c.isValid():
            self.dominant_color = c
            self.color_changed.emit(c)

    # ── Detected software ─────────────────────────────────────────────────────

    def set_detected_software(self, name: str, source_key: str):
        """Appelé par SoftwareDetector — auto-sélectionne la source et met à jour la carte INPUT."""
        if name:
            # Auto-sélectionner la source correspondante dans le combo (interne)
            for i, (_, key) in enumerate(self.SOURCES):
                if key == source_key:
                    if self.source_combo.currentIndex() != i:
                        self.source_combo.setCurrentIndex(i)   # déclenche _on_source_changed
                    break
            # Afficher le logiciel détecté dans la carte INPUT (sous-titre vert)
            if hasattr(self, '_input_device_lbl'):
                self._input_device_lbl.setText(f"◉  {name}")
                self._input_device_lbl.setStyleSheet(
                    "color:#00cc44; font-size:9px; font-style:italic;"
                    " background:transparent; border:none;")
        else:
            if hasattr(self, '_input_device_lbl'):
                self._input_device_lbl.setText("")

    # ── Paramètres Live ───────────────────────────────────────────────────────

    def set_lyre_position_getter(self, fn):
        """Fournit une fonction qui retourne [(pan, tilt), ...] en 0-255 pour les lyres."""
        self._pos_getter = fn

    @property
    def allowed_groups(self) -> set:
        return self._live_config.get('allowed_groups', set())

    @property
    def allowed_effects(self) -> set:
        return self._live_config.get('allowed_effects', set())

    @property
    def lyre_presets(self) -> list:
        return self._live_config.get('lyre_presets', [])

    @property
    def live_palette(self) -> list:
        return self._live_config.get('palette', [])

    @property
    def no_auto_strobe(self) -> bool:
        """True = stroboscopes automatiques (DROP/BUILD) désactivés."""
        return self._live_config.get('no_auto_strobe', False)

    def _open_settings(self):
        dlg = LiveSettingsDialog(self._live_config, self.SOURCES, self)
        dlg.set_position_getter(self._pos_getter)
        if dlg.exec() == QDialog.Accepted:
            cfg = dlg.get_config()
            self._live_config = cfg
            # Sync source combo avec le nouveau choix
            src_key = cfg.get('source', 'loopback')
            for i, (_, k) in enumerate(self.SOURCES):
                if k == src_key:
                    if self.source_combo.currentIndex() != i:
                        self.source_combo.setCurrentIndex(i)
                    break
            self.settings_applied.emit(cfg)


class Sequencer(QFrame):
    """Sequenceur de medias avec gestion des sequences lumiere"""

    def __init__(self, player_ui):
        super().__init__()
        self.player_ui = player_ui
        self.current_row = -1
        self.is_dirty = False

        # Systeme d'enregistrement de sequences
        self.sequences = {}  # {row: {"keyframes": [...], "duration": ms}}
        self.recording = False
        self.recording_row = -1
        self.recording_start_time = 0
        self.recording_timer = None

        # Timers pour playback
        self.playback_timer = None
        self.playback_row = -1
        self.playback_index = 0
        self.timeline_playback_timer = None
        self.tempo_timer = None
        self.tempo_elapsed = 0
        self.tempo_duration = 0
        self.tempo_running = False
        self.tempo_paused = False

        # Couleurs IA Lumiere par ligne
        self.ia_colors = {}  # {row: QColor}
        self.ia_analysis = {}  # {row: {"energy_map": [...], "beats": [...]}}
        self.image_durations = {}  # {row: seconds} - duree d'affichage des images
        self._loading = False  # Flag pour eviter dialog pendant load_show
        self._temp_players = []  # QMediaPlayer temporaires pour detection duree

        self._setup_ui()

    def _setup_ui(self):
        """Configure l'interface utilisateur"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header avec boutons
        header = QHBoxLayout()

        btn_style = """
            QPushButton {
                background: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                color: #00d4ff;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: #3a3a3a;
                border: 1px solid #00d4ff;
            }
            QPushButton:pressed {
                background: #1a1a1a;
            }
        """

        # Bouton LIVE toggle — tout à gauche
        self.live_btn = QPushButton("● LIVE")
        self.live_btn.setFixedHeight(32)
        self.live_btn.setCheckable(True)
        self.live_btn.setChecked(False)
        self._live_btn_style_off = btn_style
        self._live_btn_style_on = """
            QPushButton {
                background: #3a0000;
                border: 1px solid #ff3300;
                border-radius: 4px;
                color: #ff3300;
                font-weight: bold;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background: #4a0000;
                border: 1px solid #ff5500;
            }
        """
        self.live_btn.setStyleSheet(self._live_btn_style_off)
        self.live_btn.clicked.connect(self._toggle_live)

        # Bouton paramètres Live (⚙) — à gauche de LIVE, visible uniquement quand LIVE actif
        self._live_settings_btn = QPushButton("⚙")
        self._live_settings_btn.setFixedSize(26, 26)
        self._live_settings_btn.setCursor(Qt.PointingHandCursor)
        self._live_settings_btn.setToolTip("Paramètres Live")
        self._live_settings_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #556677; border: none; "
            "font-size: 15px; border-radius: 4px; } "
            "QPushButton:hover { color: #00aaff; background: #1a2a3a; }"
        )
        self._live_settings_btn.clicked.connect(
            lambda: self.live_panel._open_settings())
        self._live_settings_btn.setVisible(False)
        header.addWidget(self.live_btn)
        header.addWidget(self._live_settings_btn)

        header.addStretch()

        self.up_btn = QPushButton("▲")
        self.up_btn.setFixedSize(40, 32)
        self.up_btn.setStyleSheet(btn_style)
        self.up_btn.clicked.connect(self.move_up)
        header.addWidget(self.up_btn)

        self.down_btn = QPushButton("▼")
        self.down_btn.setFixedSize(40, 32)
        self.down_btn.setStyleSheet(btn_style)
        self.down_btn.clicked.connect(self.move_down)
        header.addWidget(self.down_btn)

        self.del_btn = QPushButton("🗑")
        self.del_btn.setFixedSize(40, 32)
        self.del_btn.setStyleSheet(btn_style)
        self.del_btn.clicked.connect(self.delete_selected)
        header.addWidget(self.del_btn)

        self.add_btn = QPushButton("➕")
        self.add_btn.setFixedSize(40, 32)
        self.add_btn.setStyleSheet(btn_style + "QPushButton { font-size: 18px; }")
        self.add_btn.clicked.connect(self.show_add_menu)
        header.addWidget(self.add_btn)

        self.autosave_lbl = QLabel()
        self.autosave_lbl.setStyleSheet("color: #3a8a3a; font-size: 10px;")
        self.autosave_lbl.hide()
        header.addWidget(self.autosave_lbl)

        layout.addLayout(header)

        # Panneau LIVE (créé une seule fois, caché par défaut)
        self.live_panel = LiveModePanel(self)

        # Envelopper le live panel dans un QScrollArea pour éviter
        # qu'il pousse le transport hors de l'écran
        self._live_scroll = QScrollArea()
        self._live_scroll.setWidget(self.live_panel)
        self._live_scroll.setWidgetResizable(True)
        self._live_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._live_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { background: #0d0d0d; width: 5px; border-radius: 2px; }"
            "QScrollBar::handle:vertical { background: #2a2a2a; border-radius: 2px; }"
        )

        # Stack : page 0 = table, page 1 = live panel
        self.content_stack = QStackedWidget()

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", tr("seq_col_title"), tr("seq_col_duration"), tr("seq_col_vol"), "DMX"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_row_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(55)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnWidth(4, 110)
        self.table.setAcceptDrops(True)
        self.table.dragEnterEvent = self._on_drag_enter
        self.table.dragMoveEvent  = self._on_drag_move
        self.table.dropEvent      = self._on_drop
        self.table.setStyleSheet("""
            QTableWidget {
                background: #0a0a0a;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
                gridline-color: #1a1a1a;
                outline: none;
            }
            QTableWidget::item {
                padding: 10px 8px;
                border-bottom: 1px solid #1a1a1a;
                font-size: 14px;
                color: #e0e0e0;
                outline: none;
            }
            QTableWidget::item:selected {
                background: #2a4a5a;
                border-left: 3px solid #4a8aaa;
                outline: none;
            }
            QHeaderView::section {
                background: #1a1a1a;
                color: #999;
                padding: 10px 8px;
                border: none;
                border-bottom: 2px solid #2a2a2a;
                font-weight: bold;
                font-size: 11px;
            }
        """)

        self.content_stack.addWidget(self.table)         # index 0
        self.content_stack.addWidget(self._live_scroll) # index 1
        layout.addWidget(self.content_stack)

        # Timer pour mise a jour UI
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_ui_state)
        self.timer.start(200)

    def _toggle_live(self, checked):
        """Active / désactive le mode LIVE"""
        _playlist_btns = (self.up_btn, self.down_btn, self.del_btn, self.add_btn)
        if checked:
            self.live_btn.setStyleSheet(self._live_btn_style_on)
            self.content_stack.setCurrentIndex(1)
            self._live_settings_btn.setVisible(True)
            # Cacher les boutons playlist — inutiles en mode LIVE
            for btn in _playlist_btns:
                btn.setVisible(False)
        else:
            self.live_btn.setStyleSheet(self._live_btn_style_off)
            self.content_stack.setCurrentIndex(0)
            self._live_settings_btn.setVisible(False)
            # Réafficher les boutons playlist
            for btn in _playlist_btns:
                btn.setVisible(True)

    @property
    def live_mode_active(self):
        return self.live_btn.isChecked()

    def show_add_menu(self):
        """Menu contextuel pour ajouter media, pause ou tempo"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                border: 1px solid #2a2a2a;
                padding: 8px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
                color: #ddd;
            }
            QMenu::item:selected {
                background: #2a4a5a;
            }
        """)
        menu.addAction(tr("seq_menu_add_media"), self.add_files_dialog)
        menu.addAction(tr("seq_menu_add_pause"), self.add_pause)
        menu.exec(QCursor.pos())

    @staticmethod
    def _ci(text: str) -> "QTableWidgetItem":
        """QTableWidgetItem centré."""
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        return item

    def add_pause(self):
        """Ajoute une pause dans la sequence"""
        # Pendant le chargement, toujours ajouter à la fin pour respecter l'ordre du fichier.
        # En mode interactif, insérer après la sélection courante.
        if getattr(self, '_loading', False):
            r = self.table.rowCount()
        else:
            current = self.table.currentRow()
            r = current + 1 if current >= 0 else self.table.rowCount()

        original_count = self.table.rowCount()
        self.table.insertRow(r)
        if r < original_count:
            self._reindex_sequences_insert(r)
        pause_icon = QTableWidgetItem("\u23f8\ufe0f")
        pause_icon.setData(Qt.UserRole, "\u23f8\ufe0f")
        self.table.setItem(r, 0, pause_icon)
        pause_item = QTableWidgetItem("PAUSE")
        pause_item.setData(Qt.UserRole, "PAUSE")
        self.table.setItem(r, 1, pause_item)
        self.table.setItem(r, 2, self._ci("--:--"))
        self.table.setItem(r, 3, self._ci("--"))
        self.table.setCellWidget(r, 4, self._create_dmx_cell_widget(r))
        self.table.selectRow(r)
        self.is_dirty = True

    def edit_pause_duration(self, row):
        """Edite la duree d'une pause avec slider + spinboxes min/sec."""
        title_item = self.table.item(row, 1)
        if not title_item:
            return

        data = str(title_item.data(Qt.UserRole) or "")
        current_seconds = 30
        is_timed = data.startswith("PAUSE:")
        if is_timed:
            current_seconds = int(data.split(":")[1])

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("seq_dlg_pause_title"))
        dialog.setMinimumWidth(520)
        dialog.setStyleSheet("background: #1a1a1a; color: white;")

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # ── Label résumé ──────────────────────────────────────────────────
        def _fmt_duration(secs):
            h = secs // 3600
            m = (secs % 3600) // 60
            s = secs % 60
            if h > 0:
                return tr("seq_duration_h_m_s", h=h, m=m, s=s, total=secs)
            elif m > 0:
                return tr("seq_duration_min_sec", m=m, s=s, total=secs)
            return tr("seq_duration_seconds", n=secs)

        value_label = QLabel(_fmt_duration(current_seconds) if is_timed else tr("seq_indefinite"))
        value_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("color: #ffa500; padding: 6px;")
        layout.addWidget(value_label)

        # ── Spinboxes min / sec ───────────────────────────────────────────
        spin_style = """
            QSpinBox {
                background: #252525; color: white;
                border: 1px solid #3a3a3a; border-radius: 4px;
                padding: 4px 8px; font-size: 15px; font-weight: bold;
                min-width: 64px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                width: 20px; background: #333; border: none;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #444; }
        """
        spin_row = QHBoxLayout()
        spin_row.setSpacing(8)
        spin_row.addStretch()

        spin_min = QSpinBox()
        spin_min.setRange(0, 60)
        spin_min.setSuffix(" m")
        spin_min.setStyleSheet(spin_style)
        spin_min.setValue(current_seconds // 60)

        spin_sec = QSpinBox()
        spin_sec.setRange(0, 59)
        spin_sec.setSuffix(" s")
        spin_sec.setStyleSheet(spin_style)
        spin_sec.setValue(current_seconds % 60)

        spin_row.addWidget(spin_min)
        spin_row.addWidget(spin_sec)
        spin_row.addStretch()
        layout.addLayout(spin_row)

        # ── Slider ────────────────────────────────────────────────────────
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(10)
        slider.setMaximum(3600)
        slider.setValue(max(10, current_seconds))
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #3a3a3a; height: 8px;
                background: #252525; border-radius: 4px;
            }
            QSlider::sub-page:horizontal {
                background: #ffa500; border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #ffa500; border: 2px solid #ffcc00;
                width: 18px; margin: -5px 0; border-radius: 9px;
            }
        """)
        layout.addWidget(slider)

        # ── Marqueurs 0 / 30m / 1h ────────────────────────────────────────
        marks_row = QHBoxLayout()
        marks_row.setContentsMargins(0, 0, 0, 0)
        for txt in ("0", "15m", "30m", "45m", "1h"):
            lbl = QLabel(txt)
            lbl.setStyleSheet("color:#555;font-size:9px;")
            lbl.setAlignment(Qt.AlignCenter)
            marks_row.addWidget(lbl)
        layout.addLayout(marks_row)

        result = {"indefini": False}
        _syncing = [False]

        def _total():
            return spin_min.value() * 60 + spin_sec.value()

        def _from_slider(value):
            if _syncing[0]:
                return
            _syncing[0] = True
            spin_min.setValue(value // 60)
            spin_sec.setValue(value % 60)
            value_label.setText(_fmt_duration(value))
            result["indefini"] = False
            _syncing[0] = False

        def _from_spins():
            if _syncing[0]:
                return
            _syncing[0] = True
            total = max(10, min(3600, _total()))
            slider.setValue(total)
            value_label.setText(_fmt_duration(total))
            result["indefini"] = False
            _syncing[0] = False

        slider.valueChanged.connect(_from_slider)
        spin_min.valueChanged.connect(_from_spins)
        spin_sec.valueChanged.connect(_from_spins)

        # ── Boutons ───────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()

        indef_btn = QPushButton(tr("seq_btn_indefinite"))
        indef_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a3a; color: #aaaaff;
                border: 1px solid #4a4a6a; padding: 8px 16px;
                border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background: #3a3a4a; }
        """)

        def set_indefini():
            result["indefini"] = True
            value_label.setText(tr("seq_indefinite"))

        indef_btn.clicked.connect(set_indefini)
        btn_layout.addWidget(indef_btn)

        ok_btn = QPushButton("✅ OK")
        ok_btn.clicked.connect(dialog.accept)
        ok_btn.setStyleSheet("""
            QPushButton {
                background: #2a4a5a; color: white; border: none;
                padding: 8px 20px; border-radius: 4px; font-weight: bold;
            }
        """)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton(tr("btn_cancel_x"))
        cancel_btn.clicked.connect(dialog.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a; color: white; border: none;
                padding: 8px 20px; border-radius: 4px;
            }
        """)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            if result["indefini"]:
                title_item.setData(Qt.UserRole, "PAUSE")
                title_item.setText("PAUSE")
                dur_item = self.table.item(row, 2)
                if dur_item:
                    dur_item.setText("--:--")
                # Supprimer la sequence lumiere et retirer Play Lumiere
                self._remove_play_lumiere(row)
            else:
                value = slider.value()
                title_item.setData(Qt.UserRole, f"PAUSE:{value}")
                hours = value // 3600
                minutes = (value % 3600) // 60
                seconds = value % 60
                if hours > 0:
                    title_item.setText(f"Pause ({hours}h {minutes:02d}m {seconds:02d}s)" if seconds else f"Pause ({hours}h {minutes:02d}m)")
                elif minutes > 0:
                    title_item.setText(f"Pause ({minutes}m {seconds}s)")
                else:
                    title_item.setText(f"Pause ({value}s)")
                dur_item = self.table.item(row, 2)
                if dur_item:
                    if hours > 0:
                        dur_item.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
                    else:
                        dur_item.setText(f"{minutes:02d}:{seconds:02d}")

            self.is_dirty = True

    def _create_dmx_cell_widget(self, row):
        """Cree le widget composite pour la colonne DMX: bouton visible + combo caché"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        # Combo caché — toute la logique interne continue à l'utiliser
        combo = QComboBox(container)
        combo.addItems(["Manuel", "IA Lumiere"])
        combo.setCurrentText("Manuel")
        combo.setObjectName("dmx_combo")
        combo.hide()
        combo.wheelEvent = lambda event: event.ignore()
        combo.currentTextChanged.connect(
            lambda text, r=row: self.on_dmx_changed(r, text)
        )

        # Bouton visible
        btn = QPushButton("Manuel", container)
        btn.setObjectName("dmx_btn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        self._style_dmx_btn(btn, "Manuel")

        def _show_mode_menu(_, c=combo, b=btn, r=row):
            menu = QMenu(b)
            menu.setStyleSheet("""
                QMenu { background:#1a1a1a; border:1px solid #2a2a2a; padding:4px; }
                QMenu::item { padding:6px 18px; color:#ddd; border-radius:3px; }
                QMenu::item:selected { background:#2a4a5a; }
                QMenu::separator { height:1px; background:#2a2a2a; margin:3px 8px; }
            """)
            for i in range(c.count()):
                txt = c.itemText(i)
                act = menu.addAction(txt)
                act.setCheckable(True)
                act.setChecked(c.currentText() == txt)
            menu.addSeparator()
            rec_act = menu.addAction("✦ Rec Lumière")
            rec_act.setData("__rec__")
            chosen = menu.exec(b.mapToGlobal(b.rect().bottomLeft()))
            if not chosen:
                return
            if chosen.data() == "__rec__":
                QTimer.singleShot(0, lambda: self.open_light_editor_for_row(r))
            else:
                mode = chosen.text()
                QTimer.singleShot(0, lambda m=mode: c.setCurrentText(m))

        btn.clicked.connect(_show_mode_menu)
        layout.addWidget(btn)

        color_btn = QPushButton()
        color_btn.setFixedSize(14, 14)
        color_btn.setStyleSheet("background: transparent; border: none; border-radius: 3px;")
        color_btn.setVisible(False)
        color_btn.setObjectName("ia_color_indicator")
        color_btn.setCursor(Qt.PointingHandCursor)
        color_btn.setFlat(True)
        color_btn.clicked.connect(lambda _, r=row: self._on_color_indicator_clicked(r))
        layout.addWidget(color_btn)

        return container

    def _get_dmx_combo(self, row):
        """Extrait le QComboBox de la cellule DMX (col 4)"""
        widget = self.table.cellWidget(row, 4)
        if not widget:
            return None
        if isinstance(widget, QComboBox):
            return widget
        combo = widget.findChild(QComboBox, "dmx_combo")
        if combo:
            return combo
        if widget.layout():
            for i in range(widget.layout().count()):
                item = widget.layout().itemAt(i)
                if item and isinstance(item.widget(), QComboBox):
                    return item.widget()
        return None

    def _get_color_indicator(self, row):
        """Extrait le QPushButton indicateur couleur de la cellule DMX"""
        widget = self.table.cellWidget(row, 4)
        if not widget or isinstance(widget, QComboBox):
            return None
        return widget.findChild(QPushButton, "ia_color_indicator")

    def _update_color_indicator(self, row, color):
        """Met a jour l'indicateur couleur dans la cellule DMX"""
        indicator = self._get_color_indicator(row)
        if indicator:
            if color:
                indicator.setStyleSheet(
                    f"background: {color.name()}; border: 1px solid #666; border-radius: 4px;"
                )
                indicator.setVisible(True)
            else:
                indicator.setVisible(False)

    def move_up(self):
        row = self.table.currentRow()
        if row > 0:
            self.swap_rows(row, row - 1)
            self.table.selectRow(row - 1)
            self.is_dirty = True

    def move_down(self):
        row = self.table.currentRow()
        if 0 <= row < self.table.rowCount() - 1:
            self.swap_rows(row, row + 1)
            self.table.selectRow(row + 1)
            self.is_dirty = True

    def swap_rows(self, r1, r2):
        """Echange deux lignes"""
        try:
            for col in range(self.table.columnCount()):
                if col == 4:  # Colonne DMX avec widget composite
                    combo1 = self._get_dmx_combo(r1)
                    combo2 = self._get_dmx_combo(r2)
                    w1 = self.table.cellWidget(r1, col)
                    w2 = self.table.cellWidget(r2, col)

                    w1_data = combo1.currentText() if combo1 else None
                    w2_data = combo2.currentText() if combo2 else None

                    # Sauvegarder les couleurs IA et analyses
                    color1 = self.ia_colors.get(r1)
                    color2 = self.ia_colors.get(r2)
                    analysis1 = self.ia_analysis.get(r1)
                    analysis2 = self.ia_analysis.get(r2)

                    self.table.removeCellWidget(r1, col)
                    self.table.removeCellWidget(r2, col)

                    if w2_data:
                        self.table.setCellWidget(r1, col, self._create_dmx_cell_widget(r1))
                        new_combo1 = self._get_dmx_combo(r1)
                        if new_combo1:
                            new_combo1.blockSignals(True)
                            new_combo1.setCurrentText(w2_data)
                            new_combo1.blockSignals(False)
                            if w2_data == "IA Lumiere":
                                self._apply_ia_style(new_combo1)
                            elif w2_data == "Play Lumiere":
                                self._apply_play_lumiere_style(new_combo1)
                        if color2:
                            self.ia_colors[r1] = color2
                            self._update_color_indicator(r1, color2)
                        elif r1 in self.ia_colors:
                            del self.ia_colors[r1]
                        if analysis2:
                            self.ia_analysis[r1] = analysis2
                        elif r1 in self.ia_analysis:
                            del self.ia_analysis[r1]
                    elif w2:
                        self.table.setCellWidget(r1, col, QWidget())

                    if w1_data:
                        self.table.setCellWidget(r2, col, self._create_dmx_cell_widget(r2))
                        new_combo2 = self._get_dmx_combo(r2)
                        if new_combo2:
                            new_combo2.blockSignals(True)
                            new_combo2.setCurrentText(w1_data)
                            new_combo2.blockSignals(False)
                            if w1_data == "IA Lumiere":
                                self._apply_ia_style(new_combo2)
                            elif w1_data == "Play Lumiere":
                                self._apply_play_lumiere_style(new_combo2)
                        if color1:
                            self.ia_colors[r2] = color1
                            self._update_color_indicator(r2, color1)
                        elif r2 in self.ia_colors:
                            del self.ia_colors[r2]
                        if analysis1:
                            self.ia_analysis[r2] = analysis1
                        elif r2 in self.ia_analysis:
                            del self.ia_analysis[r2]
                    elif w1:
                        self.table.setCellWidget(r2, col, QWidget())
                else:
                    item1 = self.table.takeItem(r1, col)
                    item2 = self.table.takeItem(r2, col)
                    if item2:
                        self.table.setItem(r1, col, item2)
                    if item1:
                        self.table.setItem(r2, col, item1)

            # Swap image_durations
            dur1 = self.image_durations.get(r1)
            dur2 = self.image_durations.get(r2)
            if dur2 is not None:
                self.image_durations[r1] = dur2
            elif r1 in self.image_durations:
                del self.image_durations[r1]
            if dur1 is not None:
                self.image_durations[r2] = dur1
            elif r2 in self.image_durations:
                del self.image_durations[r2]

            # Swap sequences (rec lumière)
            seq1 = self.sequences.get(r1)
            seq2 = self.sequences.get(r2)
            if seq2 is not None:
                self.sequences[r1] = seq2
            elif r1 in self.sequences:
                del self.sequences[r1]
            if seq1 is not None:
                self.sequences[r2] = seq1
            elif r2 in self.sequences:
                del self.sequences[r2]

            if self.current_row == r1:
                self.current_row = r2
            elif self.current_row == r2:
                self.current_row = r1
        except Exception as e:
            print(f"Erreur swap_rows: {e}")

    def delete_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        if self.current_row in rows:
            QMessageBox.warning(self, tr("seq_delete_impossible_title"),
                tr("seq_delete_impossible_msg"))
            return
        for row in rows:
            self.table.removeRow(row)
            self._reindex_ia_colors(row)
            if self.current_row > row:
                self.current_row -= 1
        self.is_dirty = True

    def _reindex_ia_colors(self, deleted_row):
        """Reindexe ia_colors, ia_analysis et image_durations apres suppression d'une ligne"""
        if deleted_row in self.ia_colors:
            del self.ia_colors[deleted_row]
        new_colors = {}
        for old_row, color in self.ia_colors.items():
            if old_row < deleted_row:
                new_colors[old_row] = color
            elif old_row > deleted_row:
                new_colors[old_row - 1] = color
        self.ia_colors = new_colors

        if deleted_row in self.ia_analysis:
            del self.ia_analysis[deleted_row]
        new_analysis = {}
        for old_row, data in self.ia_analysis.items():
            if old_row < deleted_row:
                new_analysis[old_row] = data
            elif old_row > deleted_row:
                new_analysis[old_row - 1] = data
        self.ia_analysis = new_analysis

        if deleted_row in self.image_durations:
            del self.image_durations[deleted_row]
        new_durations = {}
        for old_row, dur in self.image_durations.items():
            if old_row < deleted_row:
                new_durations[old_row] = dur
            elif old_row > deleted_row:
                new_durations[old_row - 1] = dur
        self.image_durations = new_durations

        # Réindexer les rec lumière (sequences) — même logique
        if deleted_row in self.sequences:
            del self.sequences[deleted_row]
        new_seqs = {}
        for old_row, seq in self.sequences.items():
            if old_row < deleted_row:
                new_seqs[old_row] = seq
            elif old_row > deleted_row:
                new_seqs[old_row - 1] = seq
        self.sequences = new_seqs

    def _reindex_sequences_insert(self, inserted_row):
        """Décale les sequences d'un cran vers le bas après insertion d'une ligne au milieu."""
        new_seqs = {}
        for old_row, seq in self.sequences.items():
            if old_row < inserted_row:
                new_seqs[old_row] = seq
            else:
                new_seqs[old_row + 1] = seq
        self.sequences = new_seqs

    def clear_sequence(self):
        self.table.setRowCount(0)
        self.current_row = -1
        self.ia_colors = {}
        self.ia_analysis = {}
        self.image_durations = {}
        self.is_dirty = False

    def set_volume(self, row, value):
        vol = int(value / 1.27)
        if self.table.item(row, 3):
            self.table.item(row, 3).setText(str(vol))
            self.is_dirty = True

    def show_row_context_menu(self, pos):
        """Menu contextuel sur une ligne du sequenceur"""
        item = self.table.itemAt(pos)
        if not item:
            return

        selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        row = item.row()

        _MENU_SS = """
            QMenu {
                background: #1a1a1a;
                border: 1px solid #2a2a2a;
                padding: 8px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
                color: #ddd;
            }
            QMenu::item:selected { background: #2a4a5a; }
        """

        # ── Multi-sélection ────────────────────────────────────────────────
        if len(selected_rows) > 1:
            menu = QMenu(self)
            menu.setStyleSheet(_MENU_SS)
            menu.addAction(f"{len(selected_rows)} tracks sélectionnés").setEnabled(False)
            menu.addSeparator()
            ia_act  = menu.addAction("Basculer en IA Lumiere")
            man_act = menu.addAction("Basculer en Manuel")
            menu.addSeparator()
            del_act = menu.addAction(f"Supprimer ({len(selected_rows)})")

            action = menu.exec(self.table.viewport().mapToGlobal(pos))

            if action == ia_act or action == man_act:
                mode = "IA Lumiere" if action == ia_act else "Manuel"
                for r in selected_rows:
                    title_item = self.table.item(r, 1)
                    if not title_item:
                        continue
                    d = str(title_item.data(Qt.UserRole) or "")
                    if d.startswith("PAUSE:") or d == "PAUSE" or d.startswith("TEMPO:"):
                        continue
                    combo = self._get_dmx_combo(r)
                    if combo and combo.currentText() != mode:
                        combo.blockSignals(True)
                        combo.setCurrentText(mode)
                        combo.blockSignals(False)
                        if mode == "IA Lumiere":
                            self._apply_ia_style(combo)
                        else:
                            self._apply_default_style(combo)
                self.is_dirty = True
            elif action == del_act:
                self.delete_selected()
            return

        # ── Sélection simple ───────────────────────────────────────────────
        title_item = self.table.item(row, 1)
        if not title_item:
            return
        data = title_item.data(Qt.UserRole)

        if data and (str(data) == "PAUSE" or str(data).startswith("PAUSE:")):
            menu = QMenu(self)
            menu.setStyleSheet(_MENU_SS)
            edit_action   = menu.addAction(tr("seq_menu_set_duration"))
            rec_action    = menu.addAction(tr("seq_menu_rec_light"))
            delete_action = menu.addAction(tr("seq_menu_delete"))
            action = menu.exec(self.table.viewport().mapToGlobal(pos))
            if action == edit_action:
                self.edit_pause_duration(row)
            elif action == rec_action:
                self.open_light_editor_for_row(row)
            elif action == delete_action:
                if row == self.current_row:
                    QMessageBox.warning(self, tr("seq_delete_impossible_title"),
                        tr("seq_delete_impossible_msg"))
                else:
                    self.table.removeRow(row)
                    self._reindex_ia_colors(row)
                    self.is_dirty = True
        else:
            self.show_media_context_menu(pos)

    def edit_duration(self, row):
        """Edite la duree d'une image ou d'une pause (methode unifiee)"""
        title_item = self.table.item(row, 1)
        if not title_item:
            return
        data = str(title_item.data(Qt.UserRole) or "")
        if data == "PAUSE" or data.startswith("PAUSE:"):
            self.edit_pause_duration(row)
        elif media_icon(data) == "image":
            self.edit_image_duration(row)

    def edit_image_duration(self, row):
        """Edite la duree d'affichage d'une image"""
        current_seconds = self.image_durations.get(row, 30)
        has_duration = row in self.image_durations

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("seq_dlg_display_duration_title"))
        dialog.setMinimumWidth(350)
        dialog.setStyleSheet("background: #1a1a1a; color: white;")

        layout = QVBoxLayout(dialog)

        value_label = QLabel(tr("seq_duration_seconds", n=current_seconds) if has_duration else tr("seq_indefinite"))
        value_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("color: #ffa500; padding: 10px;")
        layout.addWidget(value_label)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(5)
        slider.setMaximum(600)
        slider.setValue(current_seconds)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #3a3a3a;
                height: 8px;
                background: #1a1a1a;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #ffa500;
                border: 2px solid #ffcc00;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
        """)

        result = {"indefini": not has_duration}

        def update_label(value):
            minutes = value // 60
            seconds = value % 60
            if minutes > 0:
                value_label.setText(tr("seq_duration_min_sec", m=minutes, s=seconds, total=value))
            else:
                value_label.setText(tr("seq_duration_seconds", n=value))
            result["indefini"] = False

        slider.valueChanged.connect(update_label)
        layout.addWidget(slider)

        btn_layout = QHBoxLayout()

        indef_btn = QPushButton(tr("seq_btn_indefinite"))
        indef_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a3a;
                color: #aaaaff;
                border: 1px solid #4a4a6a;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background: #3a3a4a; }
        """)

        def set_indefini():
            result["indefini"] = True
            value_label.setText(tr("seq_indefinite"))

        indef_btn.clicked.connect(set_indefini)
        btn_layout.addWidget(indef_btn)

        ok_btn = QPushButton("✅ OK")
        ok_btn.clicked.connect(dialog.accept)
        ok_btn.setStyleSheet("""
            QPushButton {
                background: #2a4a5a;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton(tr("btn_cancel_x"))
        cancel_btn.clicked.connect(dialog.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
            }
        """)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            if result["indefini"]:
                if row in self.image_durations:
                    del self.image_durations[row]
                dur_item = self.table.item(row, 2)
                if dur_item:
                    dur_item.setText("--:--")
                # Supprimer la sequence lumiere et retirer Play Lumiere
                self._remove_play_lumiere(row)
            else:
                value = slider.value()
                self.image_durations[row] = value
                dur_item = self.table.item(row, 2)
                if dur_item:
                    minutes = value // 60
                    seconds = value % 60
                    dur_item.setText(f"{minutes:02d}:{seconds:02d}")

            self.is_dirty = True

    # ── Drag & drop fichiers ──────────────────────────────────────────────────
    def _on_drag_enter(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and media_icon(url.toLocalFile()) != "file":
                    event.acceptProposedAction()
                    return
        event.ignore()

    def _on_drag_move(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_drop(self, event):
        if event.mimeData().hasUrls():
            files = [url.toLocalFile() for url in event.mimeData().urls()
                     if url.isLocalFile()]
            if files:
                self.add_files(files)
                event.acceptProposedAction()
                return
        event.ignore()

    def add_files_dialog(self):
        files = QFileDialog.getOpenFileNames(self, tr("seq_dlg_add_media_title"), "", MEDIA_EXTENSIONS_FILTER)[0]
        if files:
            self.add_files(files)

    def add_files(self, files):
        for f in files:
            if media_icon(f) == "file":
                continue
            try:
                r = self.table.rowCount()
                self.table.insertRow(r)

                icon = media_icon(f)
                icon_text = {"audio": "\U0001f3b5", "video": "\U0001f3ac", "image": "\U0001f5bc"}.get(icon, "?")
                icon_item = QTableWidgetItem(icon_text)
                icon_item.setData(Qt.UserRole, icon_text)
                self.table.setItem(r, 0, icon_item)

                it = QTableWidgetItem(Path(f).name)
                it.setData(Qt.UserRole, f)
                self.table.setItem(r, 1, it)
                self.table.setItem(r, 2, self._ci("--:--"))
                self.table.setItem(r, 3, self._ci("--" if icon == "image" else "100"))

                self.table.setCellWidget(r, 4, self._create_dmx_cell_widget(r))

                # Charger la duree - garder le player en vie
                temp_p = QMediaPlayer()
                self._temp_players.append(temp_p)

                def update_duration(duration, row_idx=r, player=temp_p):
                    if duration > 0:
                        item = self.table.item(row_idx, 2)
                        if item:
                            item.setText(fmt_time(duration))
                    # Nettoyer dans tous les cas (durée trouvée ou 0 = fichier non lisible)
                    if player in self._temp_players:
                        self._temp_players.remove(player)
                        player.deleteLater()

                def _cleanup_on_status(status, player=temp_p):
                    from PySide6.QtMultimedia import QMediaPlayer as QMP
                    # Libérer si le media est chargé (avec ou sans durée) ou en erreur
                    if status in (QMP.MediaStatus.LoadedMedia,
                                  QMP.MediaStatus.InvalidMedia,
                                  QMP.MediaStatus.NoMedia):
                        if player in self._temp_players:
                            self._temp_players.remove(player)
                            player.deleteLater()

                temp_p.durationChanged.connect(update_duration)
                temp_p.mediaStatusChanged.connect(_cleanup_on_status)
                temp_p.setSource(QUrl.fromLocalFile(f))

            except Exception as e:
                print(f"Erreur ajout fichier: {e}")
                continue
        self.is_dirty = True

    # ── Styles des boutons DMX ────────────────────────────────────────────────
    _SS_BTN = {
        "Manuel": (
            "Manuel",
            "QPushButton{background:#1c1c1c;border:1px solid #2e2e2e;border-radius:8px;"
            "color:#555;font-size:11px;padding:3px 10px;}"
            "QPushButton:hover{border-color:#3a3a3a;color:#888;}"),
        "IA Lumiere": (
            "IA",
            "QPushButton{background:#0d1f3a;border:1px solid #2a5090;border-radius:8px;"
            "color:#6aadff;font-size:11px;font-weight:bold;padding:3px 10px;}"
            "QPushButton:hover{background:#152a4a;border-color:#4a80d0;}"),
        "Play Lumiere": (
            "▶ Seq",
            "QPushButton{background:#2a0d0d;border:1px solid #7a2020;border-radius:8px;"
            "color:#ff7070;font-size:11px;font-weight:bold;padding:3px 10px;}"
            "QPushButton:hover{background:#3a1010;border-color:#aa3030;}"),
        "Programme": (
            "PRG",
            "QPushButton{background:#0d2a0d;border:1px solid #207020;border-radius:8px;"
            "color:#70dd70;font-size:11px;font-weight:bold;padding:3px 10px;}"
            "QPushButton:hover{background:#103010;border-color:#30a030;}"),
    }

    def _style_dmx_btn(self, btn, mode: str):
        label, ss = self._SS_BTN.get(mode, (mode, self._SS_BTN["Manuel"][1]))
        btn.setText(label)
        btn.setStyleSheet(ss)

    def _refresh_dmx_btn(self, combo):
        container = combo.parent()
        if not container:
            return
        btn = container.findChild(QPushButton, "dmx_btn")
        if btn:
            self._style_dmx_btn(btn, combo.currentText())

    def _apply_ia_style(self, combo):
        self._refresh_dmx_btn(combo)

    def _apply_default_style(self, combo):
        self._refresh_dmx_btn(combo)

    def _apply_play_lumiere_style(self, combo):
        self._refresh_dmx_btn(combo)

    def _remove_play_lumiere(self, row):
        """Supprime la sequence lumiere et remet le combo DMX a Manuel"""
        if row in self.sequences:
            del self.sequences[row]
        combo = self._get_dmx_combo(row)
        if combo:
            idx = combo.findText("Play Lumiere")
            if idx != -1:
                combo.blockSignals(True)
                combo.setCurrentText("Manuel")
                combo.removeItem(idx)
                combo.blockSignals(False)
                self._apply_default_style(combo)
                self._update_color_indicator(row, None)

    def on_dmx_changed(self, row, text):
        """Gere le changement de mode DMX - affiche le dialog couleur si IA Lumiere"""
        combo = self._get_dmx_combo(row)
        if not combo:
            return

        # Si on quitte Play Lumiere, stopper le timer de timeline si c'est la ligne active
        if text != "Play Lumiere":
            if (getattr(self, 'timeline_playback_row', None) == row and
                    self.timeline_playback_timer and self.timeline_playback_timer.isActive()):
                self._stop_timeline_effect()
                self.timeline_playback_timer.stop()
                if hasattr(self, 'timeline_playback_row'):
                    del self.timeline_playback_row
                self.timeline_tracks_data = {}

        if text == "IA Lumiere":
            self._apply_ia_style(combo)

            if not self._loading:
                # Demander la couleur dominante
                color = self.player_ui.show_ia_color_dialog()
                if color:
                    self.ia_colors[row] = color
                    self._update_color_indicator(row, color)
                    # Lancer l'analyse audio immediatement
                    self._analyze_ia_for_row(row, color)
                else:
                    # Annule -> revenir a Manuel
                    combo.blockSignals(True)
                    combo.setCurrentText("Manuel")
                    combo.blockSignals(False)
                    self._apply_default_style(combo)
                    self._update_color_indicator(row, None)
                    return
            else:
                # Pendant le chargement, juste afficher l'indicateur si couleur existe
                if row in self.ia_colors:
                    self._update_color_indicator(row, self.ia_colors[row])
        elif text == "Play Lumiere":
            self._apply_play_lumiere_style(combo)
            self._update_color_indicator(row, None)
        else:
            self._apply_default_style(combo)
            self._update_color_indicator(row, None)

    def _analyze_ia_for_row(self, row, color):
        """Analyse audio pour une ligne IA Lumiere (au moment de la selection)"""
        # Recuperer le filepath du media
        item = self.table.item(row, 1)
        if not item:
            return
        filepath = item.data(Qt.UserRole)
        if not filepath or filepath in ("PAUSE",) or str(filepath).startswith("PAUSE:") or str(filepath).startswith("TEMPO:"):
            return

        import os
        if not os.path.isfile(filepath):
            return

        from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar

        # Configurer l'IA
        self.player_ui.audio_ai.set_dominant_color(color)

        # Dialog de chargement
        loading = QDialog(self)
        loading.setWindowTitle("IA Lumiere")
        loading.setFixedSize(320, 90)
        loading.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        loading.setStyleSheet("""
            QDialog { background: #1a1a1a; border: 2px solid #00d4ff; border-radius: 10px; }
            QLabel { color: white; border: none; }
            QProgressBar { background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; text-align: center; color: white; }
            QProgressBar::chunk { background: #00d4ff; border-radius: 3px; }
        """)
        lay = QVBoxLayout(loading)
        lay.setContentsMargins(15, 10, 15, 10)
        label = QLabel(tr("seq_analyzing_audio"))
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 13px; font-weight: bold;")
        lay.addWidget(label)
        bar = QProgressBar()
        bar.setRange(0, 0)
        lay.addWidget(bar)
        loading.show()
        QApplication.processEvents()

        # Lancer l'analyse
        self.player_ui.audio_ai.analyze(filepath)

        # Stocker les resultats
        self.ia_analysis[row] = {
            "energy_map": list(self.player_ui.audio_ai.energy_map),
            "beats": list(self.player_ui.audio_ai.beats),
        }

        loading.close()
        print(f"IA Lumiere: analyse pre-calculee pour ligne {row}")

    def _on_color_indicator_clicked(self, row):
        """Clic sur le carre couleur - permet de changer la couleur sans re-analyser"""
        color = self.player_ui.show_ia_color_dialog()
        if color:
            self.ia_colors[row] = color
            self._update_color_indicator(row, color)
            self.player_ui.audio_ai.set_dominant_color(color)
            self.is_dirty = True

    def update_ui_state(self):
        for r in range(self.table.rowCount()):
            bg = "#0a0a0a"
            if r == self.current_row:
                combo = self._get_dmx_combo(r)
                if combo:
                    mode = combo.currentText()
                    if mode == "Manuel":
                        bg = "#1a3a5a"
                    elif mode == "IA Lumiere":
                        bg = "#5a1a1a"
                else:
                    dmx_widget = self.table.cellWidget(r, 4)
                    if not dmx_widget or (isinstance(dmx_widget, QWidget) and not isinstance(dmx_widget, QComboBox)):
                        bg = "#3a3a1a"

            for c in range(4):
                it = self.table.item(r, c)
                if it:
                    it.setBackground(QBrush(QColor(bg)))
                    it.setForeground(QBrush(QColor("#ffffff")))

    def update_playing_indicator(self, playing_row):
        """Met a jour l'emoji de lecture : 🟢 pour la ligne en cours, restaure l'original pour les autres"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                if row == playing_row:
                    item.setText("\U0001f7e2")
                else:
                    original = item.data(Qt.UserRole)
                    item.setText(original if original else "")

    def play_row(self, row):
        if 0 <= row < self.table.rowCount():
            try:
                self.update_playing_indicator(row)

                # Arreter le timer timeline du media precedent
                if self.timeline_playback_timer and self.timeline_playback_timer.isActive():
                    self._stop_timeline_effect()
                    self.timeline_playback_timer.stop()
                if hasattr(self, 'timeline_playback_row'):
                    del self.timeline_playback_row

                # Arreter les cartouches
                if hasattr(self.player_ui, '_stop_all_cartouches'):
                    self.player_ui._stop_all_cartouches()

                # Arreter tout playback precedent (timeline, keyframes, TEMPO)
                self.stop_sequence_playback()
                self.tempo_running = False
                self.tempo_paused = False
                if self.tempo_timer and self.tempo_timer.isActive():
                    self.tempo_timer.stop()

                item = self.table.item(row, 1)
                data = item.data(Qt.UserRole) if item else None

                # PAUSE temporisee (PAUSE:seconds)
                if data and str(data).startswith("PAUSE:"):
                    seconds = int(str(data).split(":")[1])
                    self.current_row = row
                    self.table.selectRow(row)
                    print(f"Pause temporisee: Attente de {seconds} secondes...")

                    self.player_ui.player.stop()
                    # Cacher l'image si affichee
                    if hasattr(self.player_ui, 'hide_image'):
                        self.player_ui.hide_image()
                    self.tempo_elapsed = 0
                    self.tempo_duration = seconds * 1000
                    self.tempo_running = True
                    self.tempo_paused = False

                    if not self.tempo_timer:
                        self.tempo_timer = QTimer()
                        self.tempo_timer.timeout.connect(self.update_tempo_timeline)

                    self.tempo_timer.start(100)

                    # Mettre a jour l'icone play
                    self.player_ui.update_play_icon(QMediaPlayer.PlayingState)

                    # Jouer la sequence lumiere si disponible
                    dmx_mode = self.get_dmx_mode(row)
                    if dmx_mode == "Manuel":
                        self.player_ui.dmx_blackout()
                    elif dmx_mode in ["Programme", "Play Lumiere"] and row in self.sequences:
                        self.play_sequence(row)
                    return

                # PAUSE indefinie
                if data == "PAUSE":
                    self.player_ui.player.stop()
                    self.player_ui.dmx_blackout()
                    # Cacher l'image si affichee
                    if hasattr(self.player_ui, 'hide_image'):
                        self.player_ui.hide_image()

                    self.current_row = row
                    self.table.selectRow(row)
                    self.player_ui.update_play_icon(QMediaPlayer.StoppedState)

                    # Jouer la sequence lumiere si disponible
                    dmx_mode = self.get_dmx_mode(row)
                    if dmx_mode in ["Programme", "Play Lumiere"] and row in self.sequences:
                        self.play_sequence(row)

                    next_row = row + 1
                    if next_row < self.table.rowCount():
                        next_item = self.table.item(next_row, 1)
                        next_data = next_item.data(Qt.UserRole) if next_item else None
                        if next_item and next_data != "PAUSE" and not str(next_data or "").startswith("PAUSE:"):
                            vol_item = self.table.item(next_row, 3)
                            if vol_item and vol_item.text() != "--":
                                path = next_item.data(Qt.UserRole)
                                vol = int(vol_item.text())
                                self.player_ui.audio.setVolume(vol / 100)
                                if media_icon(path) != "image":
                                    self.player_ui.player.setSource(QUrl.fromLocalFile(path))
                                self.current_row = next_row
                                self.player_ui.trigger_pause_mode()
                                # Masquer la 1re frame du media precharge — le preview doit rester noir
                                if hasattr(self.player_ui, 'show_black_preview'):
                                    self.player_ui.show_black_preview()
                    return

                # Lecture normale (media)
                self.current_row = row
                vol_item = self.table.item(row, 3)
                if item and vol_item:
                    path = item.data(Qt.UserRole)

                    # Verifier que le fichier existe
                    if path and not os.path.isfile(path):
                        msg = QMessageBox(self)
                        msg.setIcon(QMessageBox.Critical)
                        msg.setWindowTitle(tr("seq_file_not_found_title"))
                        msg.setText(tr("seq_file_not_found_msg", name=Path(path).name))
                        btn_ok = msg.addButton(QMessageBox.Ok)
                        btn_locate = msg.addButton(tr("seq_locate_file"), QMessageBox.ActionRole)
                        msg.exec()
                        if msg.clickedButton() == btn_locate:
                            start_dir = str(Path(path).parent) if Path(path).parent.exists() else str(Path.home())
                            new_path, _ = QFileDialog.getOpenFileName(self, tr("seq_locate_file"), start_dir, MEDIA_EXTENSIONS_FILTER)
                            if new_path:
                                item.setData(Qt.UserRole, new_path)
                                item.setText(Path(new_path).name)
                                icon_item = self.table.item(row, 0)
                                if icon_item:
                                    new_icon = media_icon(new_path)
                                    icon_text = {"audio": "\U0001f3b5", "video": "\U0001f3ac", "image": "\U0001f5bc"}.get(new_icon, "?")
                                    icon_item.setText(icon_text)
                                    icon_item.setData(Qt.UserRole, icon_text)
                                path = new_path
                            else:
                                return
                        else:
                            return

                    vol = int(vol_item.text()) if vol_item.text() not in ("--", "") else 100

                    dmx_mode = self.get_dmx_mode(row)
                    self.last_dmx_mode = dmx_mode

                    # IA Lumiere : utilise les donnees pre-analysees
                    if dmx_mode == "IA Lumiere":
                        self.player_ui.audio_ai.reset()
                        color = self.ia_colors.get(row)
                        if color:
                            self.player_ui.audio_ai.set_dominant_color(color)
                        if row in self.ia_analysis:
                            self.player_ui.audio_ai.load_analysis(self.ia_analysis[row])

                    # Gestion des images
                    if media_icon(path) == "image":
                        self.player_ui.player.stop()
                        self.player_ui.show_image(path)
                        # Mettre a jour la sortie video externe
                        if hasattr(self.player_ui, '_update_video_output_state'):
                            self.player_ui._update_video_output_state()

                        image_duration = self.image_durations.get(row)
                        if image_duration:
                            # Image avec duree : lancer le tempo timer
                            self.tempo_elapsed = 0
                            self.tempo_duration = image_duration * 1000
                            self.tempo_running = True
                            self.tempo_paused = False

                            if not self.tempo_timer:
                                self.tempo_timer = QTimer()
                                self.tempo_timer.timeout.connect(self.update_tempo_timeline)

                            self.tempo_timer.start(100)
                            self.player_ui.update_play_icon(QMediaPlayer.PlayingState)
                        else:
                            # Image sans duree : attendre action utilisateur
                            self.player_ui.update_play_icon(QMediaPlayer.PausedState)

                        if dmx_mode == "Manuel":
                            for p in self.player_ui.projectors:
                                p.level = 0
                                p.color = QColor("black")
                                p.base_color = QColor("black")
                        elif dmx_mode in ["Programme", "Play Lumiere"] and row in self.sequences:
                            self.play_sequence(row)
                        return

                    # Cacher l'image si affichee precedemment
                    if hasattr(self.player_ui, 'hide_image'):
                        self.player_ui.hide_image()

                    self.player_ui.audio.setVolume(vol / 100)
                    # Arreter proprement l'ancien media avant de changer de source
                    # (evite les signaux Qt parasites EndOfMedia lors du changement)
                    self.player_ui.player.stop()
                    self.player_ui._media_source_row = row
                    self.player_ui.player.setSource(QUrl.fromLocalFile(path))
                    self.player_ui.player.play()

                    # Mettre a jour la sortie video externe
                    if hasattr(self.player_ui, '_update_video_output_state'):
                        self.player_ui._update_video_output_state()

                    if dmx_mode == "Manuel":
                        # Manuel = pas de lumiere
                        for p in self.player_ui.projectors:
                            p.level = 0
                            p.color = QColor("black")
                            p.base_color = QColor("black")
                        self.player_ui.recording_waveform.hide()
                    elif dmx_mode in ["Programme", "Play Lumiere"]:
                        self.play_sequence(row)
                    else:
                        self.player_ui.recording_waveform.hide()

            except Exception as e:
                print(f"Erreur lecture: {e}")
                QMessageBox.critical(None, tr("err_save_title"), tr("seq_err_play_msg", e=e))

    def update_tempo_timeline(self):
        """Met a jour la timeline pendant une Pause minutee"""
        if not self.tempo_running:
            return

        self.tempo_elapsed += 100

        if self.tempo_elapsed >= self.tempo_duration:
            self.tempo_timer.stop()
            self.tempo_running = False
            self.tempo_paused = False
            self.continue_after_tempo_in_seq(self.current_row)
            return

        progress = (self.tempo_elapsed / self.tempo_duration) * self.player_ui.timeline.maximum() if self.tempo_duration > 0 else 0
        self.player_ui.timeline.setValue(int(progress))

        seconds = self.tempo_elapsed // 1000
        total_seconds = self.tempo_duration // 1000
        self.player_ui.time_label.setText(f"{seconds//60:02d}:{seconds%60:02d}")
        remaining_seconds = total_seconds - seconds
        self.player_ui.remaining_label.setText(f"-{remaining_seconds//60:02d}:{remaining_seconds%60:02d}")

    def continue_after_tempo_in_seq(self, tempo_row):
        """Continue la sequence apres une Pause minutee ou une image temporisee"""
        if self.tempo_timer and self.tempo_timer.isActive():
            self.tempo_timer.stop()
        self.tempo_running = False
        self.tempo_paused = False
        self.tempo_elapsed = 0

        # Cacher l'image si affichee
        if hasattr(self.player_ui, 'hide_image'):
            self.player_ui.hide_image()

        # Arreter le timer timeline si actif
        if self.timeline_playback_timer and self.timeline_playback_timer.isActive():
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
        if hasattr(self, 'timeline_playback_row'):
            del self.timeline_playback_row
        self.timeline_tracks_data = {}

        next_row = tempo_row + 1
        if next_row < self.table.rowCount():
            self.play_row(next_row)
        else:
            print("Fin de la sequence")
            self.player_ui.update_play_icon(QMediaPlayer.StoppedState)

    def get_dmx_mode(self, row):
        """Recupere le mode DMX d'une ligne"""
        combo = self._get_dmx_combo(row)
        if combo:
            return combo.currentText()
        return "Manuel"

    def toggle_recording(self, row, checked):
        """Active/desactive l'enregistrement d'une sequence"""
        if checked:
            self.recording = True
            self.recording_row = row
            self.recording_start_time = 0

            self.sequences[row] = {
                "keyframes": [],
                "duration": 0
            }

            if not self.recording_timer:
                self.recording_timer = QTimer()
                self.recording_timer.timeout.connect(self.record_keyframe)

            self.recording_timer.start(500)
            print(f"Enregistrement sequence ligne {row} demarre")
        else:
            self.recording = False
            if self.recording_timer:
                self.recording_timer.stop()

            if self.recording_row in self.sequences:
                self.sequences[self.recording_row]["duration"] = self.recording_start_time
                nb_keyframes = len(self.sequences[self.recording_row]["keyframes"])
                print(f"Enregistrement arrete - {nb_keyframes} keyframes")

            self.recording_row = -1
            self.recording_start_time = 0
            self.is_dirty = True

    def record_keyframe(self):
        """Enregistre un keyframe de l'etat actuel AKAI"""
        if not self.recording or self.recording_row < 0:
            return

        main_window = self.player_ui

        keyframe = {
            "time": self.recording_start_time,
            "faders": [],
            "active_pad": None,
            "active_effects": []
        }

        for i in range(9):
            if i in main_window.faders:
                keyframe["faders"].append(main_window.faders[i].value)
            else:
                keyframe["faders"].append(0)

        if main_window.active_pad:
            for (r, c), pad in main_window.pads.items():
                if pad == main_window.active_pad:
                    keyframe["active_pad"] = {
                        "row": r,
                        "col": c,
                        "color": pad.property("base_color").name()
                    }
                    break

        for i, btn in enumerate(main_window.effect_buttons):
            if btn.active and btn.current_effect:
                cfg = main_window._button_effect_configs.get(i, {})
                keyframe["active_effects"].append({
                    "active": True,
                    "name": btn.current_effect,
                    "config": cfg,
                })
            else:
                keyframe["active_effects"].append({"active": False})

        self.sequences[self.recording_row]["keyframes"].append(keyframe)

        pad_color = None
        if keyframe["active_pad"]:
            pad_color = QColor(keyframe["active_pad"]["color"])
        active_effs = [e for e in keyframe["active_effects"] if isinstance(e, dict) and e.get("active")]
        effect_name = active_effs[0].get("name", "") if active_effs else ""
        main_window.recording_waveform.add_keyframe(
            self.recording_start_time,
            keyframe["faders"],
            pad_color,
            effect_name,
        )

        self.recording_start_time += 500

    def play_sequence(self, row):
        """Joue une sequence"""
        if row not in self.sequences:
            return

        sequence = self.sequences[row]

        if "clips" in sequence:
            self.play_timeline_sequence(row)
        elif "keyframes" in sequence:
            self.play_keyframes_sequence(row)

    def play_timeline_sequence(self, row):
        """Joue sequence timeline avec clips"""
        sequence = self.sequences[row]
        clips_data = sequence.get("clips", [])

        if not clips_data:
            return

        print(f"Lecture timeline ligne {row} - {len(clips_data)} clips")

        tracks_clips = {}
        for clip_data in clips_data:
            track_name = clip_data.get('track', 'Face')
            tracks_clips.setdefault(track_name, []).append(clip_data)

        # Couper tout effet actif avant de démarrer la timeline (évite le strobe)
        main_win = self.player_ui
        if hasattr(main_win, 'effect_timer') and main_win.effect_timer.isActive():
            main_win.effect_timer.stop()
        if getattr(main_win, 'active_effect', None) is not None:
            main_win.active_effect = None
            main_win.active_effect_config = {}

        self.timeline_playback_row = row
        self.timeline_tracks_data = tracks_clips
        self.timeline_last_update = -100  # Garantit que le 1er tick fire immediatement
        self._timeline_tick = 0  # Repart de zero pour les effets

        if not self.timeline_playback_timer:
            self.timeline_playback_timer = QTimer()
            self.timeline_playback_timer.timeout.connect(self.update_timeline_playback)

        self.timeline_playback_timer.start(50)

    def update_timeline_playback(self):
        """Met a jour DMX selon position timeline"""
        if not hasattr(self, 'timeline_playback_row'):
            return

        # Garde supplementaire: verifier que la timeline correspond bien au media en cours
        if self.timeline_playback_row != getattr(self, 'current_row', -1):
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            del self.timeline_playback_row
            self.timeline_tracks_data = {}
            return

        # Garde supplementaire: verifier que le mode DMX courant est toujours "Play Lumiere"
        current_dmx_mode = self.get_dmx_mode(getattr(self, 'current_row', -1))
        if current_dmx_mode != "Play Lumiere":
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            if hasattr(self, 'timeline_playback_row'):
                del self.timeline_playback_row
            self.timeline_tracks_data = {}
            return

        # Source du temps: tempo_elapsed pour TEMPO, player.position pour media
        if self.tempo_running:
            current_time = self.tempo_elapsed
        else:
            current_time = self.player_ui.player.position()

        # Debounce: ignorer uniquement si la position n'a pas change du tout
        if current_time == self.timeline_last_update:
            # Sur pause : si un effet tourne, l'éteindre et envoyer du noir
            if getattr(self, '_timeline_effect_name', None) is not None:
                _player = getattr(self.player_ui, 'player', None)
                _state  = _player.playbackState() if _player else None
                if _state != QMediaPlayer.PlayingState:
                    self._stop_timeline_effect()
                    for _proj in self.player_ui.projectors:
                        _proj.level      = 0
                        _proj.base_color = QColor("black")
                        _proj.color      = QColor("black")
                    if hasattr(self.player_ui, 'artnet') and self.player_ui.artnet:
                        self.player_ui.artnet.update_from_projectors(self.player_ui.projectors)
            return

        self.timeline_last_update = current_time

        # Compteur pour les effets
        if not hasattr(self, '_timeline_tick'):
            self._timeline_tick = 0
        self._timeline_tick += 1

        active_clips = {}
        last_clip_end = 0

        for track_name, clips in self.timeline_tracks_data.items():
            for clip_data in clips:
                start = clip_data['start']
                end = start + clip_data['duration']
                if end > last_clip_end:
                    last_clip_end = end

                if start <= current_time <= end:
                    intensity = self.calculate_clip_intensity(clip_data, current_time)
                    progress = (current_time - start) / max(1, clip_data['duration'])

                    entry = {
                        'color': QColor(clip_data['color']),
                        'color2': QColor(clip_data['color2']) if clip_data.get('color2') else None,
                        'intensity': intensity,
                        'effect': clip_data.get('effect', None),
                        'effect_speed':         clip_data.get('effect_speed', 50),
                        'effect_name':          clip_data.get('effect_name', ''),
                        'effect_type':          clip_data.get('effect_type', ''),
                        'effect_layers':        clip_data.get('effect_layers', []),
                        'effect_target_groups': clip_data.get('effect_target_groups', []),
                        'memory_ref':    clip_data.get('memory_ref'),
                        'seq_intensity': intensity,
                    }
                    # Mouvement Pan/Tilt
                    if clip_data.get('move_effect') or 'pan_start' in clip_data:
                        entry['move_effect']    = clip_data.get('move_effect')
                        entry['move_speed']     = clip_data.get('move_speed', 0.5)
                        entry['move_amplitude'] = clip_data.get('move_amplitude', 60)
                        entry['pan_start']      = clip_data.get('pan_start', 128)
                        entry['tilt_start']     = clip_data.get('tilt_start', 128)
                        entry['pan_end']        = clip_data.get('pan_end', 128)
                        entry['tilt_end']       = clip_data.get('tilt_end', 128)
                        entry['move_progress']  = progress
                        entry['move_elapsed']   = (current_time - start) / 1000.0
                    # Preset de position lyre (plan de feu)
                    if clip_data.get('position_preset_idx') is not None:
                        entry['position_preset_idx'] = clip_data['position_preset_idx']

                    active_clips[track_name] = entry
                    break

        # Auto-stop: si tous les clips sont finis et qu'on depasse la fin du dernier clip
        if not active_clips and current_time > last_clip_end and last_clip_end > 0:
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            if hasattr(self, 'timeline_playback_row'):
                del self.timeline_playback_row
            self.timeline_tracks_data = {}
            return

        # ── Gérer la piste Effet (priorité sur tout) ─────────────────────
        effet_clip = active_clips.pop("Effet", None)
        self._handle_timeline_effect(effet_clip)

        self.apply_timeline_to_dmx(active_clips)

    def _handle_timeline_effect(self, effet_clip):
        """Démarre / maintient / arrête l'effet de la piste Effet de la timeline."""
        main_win = self.player_ui
        if effet_clip is None:
            # Aucun clip actif → arrêter l'effet timeline s'il était actif
            self._stop_timeline_effect()
            return

        eff_name = effet_clip.get('effect_name', '')
        if not eff_name:
            self._stop_timeline_effect()
            return

        # Déjà le bon effet en cours avec mêmes paramètres → ne pas redémarrer
        same_group = getattr(self, '_timeline_effect_group', None) == tuple(effet_clip.get('effect_target_groups', []))
        same_speed = getattr(self, '_timeline_effect_speed', None) == effet_clip.get('effect_speed', 50)
        if getattr(self, '_timeline_effect_name', None) == eff_name and same_group and same_speed:
            return

        # Charger la config de l'effet (layers depuis BUILTIN_EFFECTS ou custom)
        eff_layers = effet_clip.get('effect_layers', [])
        eff_type   = effet_clip.get('effect_type', '')
        if not eff_layers:
            # Chercher dans BUILTIN_EFFECTS
            try:
                from effect_editor import BUILTIN_EFFECTS
                for _e in BUILTIN_EFFECTS:
                    if _e.get('name') == eff_name:
                        eff_layers = [dict(l) for l in _e.get('layers', [])]
                        eff_type   = _e.get('type', '')
                        break
            except Exception:
                pass

        target_groups  = effet_clip.get('effect_target_groups', [])
        speed_override = effet_clip.get('effect_speed', 50)
        cfg = {
            'name':            eff_name,
            'type':            eff_type,
            'layers':          eff_layers,
            'play_mode':       'loop',
            'target_groups':   target_groups,
            'speed_override':  speed_override,
        }

        # Démarrer l'effet (initialiser l'état sans démarrer le effect_timer —
        # la timeline appelle update_effect() elle-même à chaque tick)
        self._timeline_effect_name  = eff_name
        self._timeline_effect_group = tuple(effet_clip.get('effect_target_groups', []))
        self._timeline_effect_speed = effet_clip.get('effect_speed', 50)
        main_win.active_effect        = eff_name
        main_win.active_effect_config = cfg
        # Initialiser les compteurs d'état de l'effet
        main_win.effect_state      = 0
        main_win.effect_brightness = 0
        main_win.effect_direction  = 1
        main_win.effect_hue        = 0
        main_win.effect_saved_colors = {}
        for p in main_win.projectors:
            main_win.effect_saved_colors[id(p)] = (
                p.base_color, p.color, p.level,
                getattr(p, 'pan', 128), getattr(p, 'tilt', 128)
            )
        import time as _time
        main_win.effect_t0 = _time.monotonic()

    def _stop_timeline_effect(self):
        """Arrête l'effet lancé par la timeline (si c'est bien lui qui tourne)."""
        main_win = self.player_ui
        timeline_name = getattr(self, '_timeline_effect_name', None)
        if timeline_name is None:
            return
        self._timeline_effect_name  = None
        self._timeline_effect_group = None
        self._timeline_effect_speed = None
        # N'arrêter que si c'est encore l'effet de la timeline qui tourne
        if getattr(main_win, 'active_effect', None) == timeline_name:
            main_win.active_effect        = None
            main_win.active_effect_config = {}
            if hasattr(main_win, 'stop_effect'):
                main_win.stop_effect()

    def calculate_clip_intensity(self, clip_data, current_time):
        """Calcule intensite avec fades"""
        start = clip_data['start']
        duration = clip_data['duration']
        base_intensity = clip_data.get('intensity', 100)

        fade_in = clip_data.get('fade_in', 0)
        fade_out = clip_data.get('fade_out', 0)

        relative_pos = (current_time - start) / duration
        intensity = base_intensity

        if fade_in > 0:
            fade_in_ratio = fade_in / duration
            if relative_pos < fade_in_ratio:
                intensity *= (relative_pos / fade_in_ratio)

        if fade_out > 0:
            fade_out_ratio = fade_out / duration
            if relative_pos > (1 - fade_out_ratio):
                intensity *= ((1 - relative_pos) / fade_out_ratio)

        return int(intensity)

    def _apply_seq_memory(self, seq_clip_info, main_win):
        """Applique la mémoire de séquence sur les projecteurs (priorité haute)."""
        if not seq_clip_info:
            return
        mem_ref = seq_clip_info.get('memory_ref')
        if not mem_ref:
            return
        memories = getattr(main_win, 'memories', None)
        if not memories:
            return
        mem_col, row_idx = mem_ref[0], mem_ref[1]
        if mem_col < len(memories) and row_idx < len(memories[mem_col]):
            mem = memories[mem_col][row_idx]
            if mem:
                # Lire les projecteurs depuis les cues (format actuel) ou le niveau
                # supérieur (ancien format migré) pour compatibilité ascendante.
                cues = mem.get("cues", [])
                if cues:
                    cue_idx = seq_clip_info.get('cue_index', 0) or 0
                    cue = cues[min(cue_idx, len(cues) - 1)]
                    projectors_state = cue.get("projectors", [])
                else:
                    projectors_state = mem.get("projectors", [])
                brightness = seq_clip_info.get('seq_intensity', 100) / 100.0
                for i, ps in enumerate(projectors_state):
                    if i >= len(main_win.projectors):
                        continue
                    proj = main_win.projectors[i]
                    # Pan/Tilt toujours appliqués (même si level=0)
                    if "pan"  in ps: proj.pan  = ps["pan"]
                    if "tilt" in ps: proj.tilt = ps["tilt"]
                    if ps.get("level", 0) > 0:
                        lvl  = int(ps["level"] * brightness)
                        base = QColor(ps["base_color"])
                        proj.level      = lvl
                        proj.base_color = base
                        proj.color      = QColor(
                            int(base.red()   * lvl / 100.0),
                            int(base.green() * lvl / 100.0),
                            int(base.blue()  * lvl / 100.0),
                        )

    def apply_timeline_to_dmx(self, active_clips):
        """Applique les clips actifs aux projecteurs DMX avec effets"""
        import math
        import random

        main_win = self.player_ui
        if hasattr(main_win, 'get_track_to_indices'):
            track_to_indices = main_win.get_track_to_indices()
        else:
            track_to_indices = {
                'Face': list(range(0, 4)),
                'Douche 1': list(range(4, 7)),
                'Douche 2': list(range(7, 10)),
                'Douche 3': list(range(10, 13)),
                'Contres': list(range(15, 21))
            }

        tick = getattr(self, '_timeline_tick', 0)

        for proj in self.player_ui.projectors:
            proj.level = 0
            proj.base_color = QColor("black")
            proj.color = QColor("black")

        for track_name, clip_info in active_clips.items():
            indices = track_to_indices.get(track_name, [])
            effect = clip_info.get('effect')
            effect_speed = clip_info.get('effect_speed', 50)

            # Calculer le facteur de vitesse pour les effets
            speed_factor = max(1, int(10 - effect_speed / 12))

            for idx_position, idx in enumerate(indices):
                if idx >= len(self.player_ui.projectors):
                    continue

                proj = self.player_ui.projectors[idx]
                intensity = clip_info['intensity']

                if clip_info['color2']:
                    color = clip_info['color'] if idx_position % 2 == 0 else clip_info['color2']
                else:
                    color = clip_info['color']

                # Appliquer l'effet sur la couleur/intensite
                if effect == "Strobe":
                    if (tick // speed_factor) % 2 == 0:
                        color = QColor(255, 255, 255)
                    else:
                        color = QColor("black")
                        intensity = 0
                elif effect == "Flash":
                    if (tick // speed_factor) % 2 == 0:
                        pass  # couleur normale
                    else:
                        color = QColor("black")
                        intensity = 0
                elif effect == "Pulse":
                    phase = math.sin(tick * 0.15 / max(1, speed_factor / 5)) * 0.5 + 0.5
                    intensity = int(intensity * phase)
                elif effect == "Wave":
                    phase = math.sin((tick + idx_position * 3) * 0.2 / max(1, speed_factor / 5)) * 0.5 + 0.5
                    intensity = int(intensity * phase)
                elif effect == "Random":
                    if tick % speed_factor == 0:
                        if random.random() > 0.5:
                            intensity = 0
                elif effect == "Sparkle":
                    # Chaque projecteur scintille independamment et aleatoirement
                    spark_period = max(1, speed_factor)
                    spark_tick = tick // spark_period
                    rng = random.Random(spark_tick * 100 + idx_position * 37)
                    if rng.random() > 0.5:
                        intensity = 0
                elif effect == "Rainbow":
                    # Cycle chromatique continu, decale par projecteur
                    hue = (tick * 4 // max(1, speed_factor) + idx_position * 40) % 360
                    color = QColor.fromHsv(hue, 255, 255)
                elif effect == "Fire":
                    # Scintillement dans les tons chauds rouge/orange
                    rng = random.Random((tick + idx_position * 7) * 3)
                    r = min(255, 175 + int(rng.random() * 80))
                    g = int(rng.random() * 80)
                    color = QColor(r, g, 0)

                proj.level = intensity
                proj.base_color = color
                proj.color = QColor(
                    int(color.red() * intensity / 100),
                    int(color.green() * intensity / 100),
                    int(color.blue() * intensity / 100)
                )

        # --- Appliquer Pan/Tilt pour les Lyres ---
        # La piste position s'appelle "Position" dans la timeline; fallback sur "Lyres" pour anciens .tui
        lyres_clip = active_clips.get('Position') or active_clips.get('Lyres')
        if lyres_clip:
            # Recuperer les indices du groupe "lyres" / "Lyres"
            lyres_indices = track_to_indices.get('Lyres', [])
            if not lyres_indices and hasattr(main_win, 'projectors'):
                lyres_indices = [
                    i for i, p in enumerate(main_win.projectors)
                    if getattr(p, 'fixture_type', '') == 'Moving Head'
                ]

            # --- Cas 1 : preset de position nommé (par lyre, 16-bit, avec transition animée) ---
            if lyres_clip.get('position_preset_idx') is not None:
                import time as _time
                preset_idx = lyres_clip['position_preset_idx']
                presets = getattr(main_win, 'position_presets', [])
                if preset_idx < len(presets):
                    preset   = presets[preset_idx]
                    lyres_cur = [main_win.projectors[i] for i in lyres_indices
                                 if i < len(main_win.projectors)]
                    lyre_by_name = {p.name: p for p in lyres_cur if p.name}

                    _ANIM_DUR = 1.5  # secondes

                    # Nouveau preset → capturer positions courantes comme point de départ
                    if getattr(self, '_pos_anim_target_idx', None) != preset_idx:
                        self._pos_anim_target_idx = preset_idx
                        self._pos_anim_start_t    = _time.monotonic()
                        self._pos_anim_start_vals = {
                            id(p): (getattr(p, 'pan', 32768), getattr(p, 'tilt', 32768))
                            for p in lyres_cur
                        }

                    elapsed = _time.monotonic() - getattr(self, '_pos_anim_start_t', 0.0)
                    raw = min(1.0, elapsed / _ANIM_DUR)
                    frac = raw * raw * (3.0 - 2.0 * raw)  # smoothstep

                    for k, ps in enumerate(preset.get("projectors", [])):
                        p = lyres_cur[k] if k < len(lyres_cur) else lyre_by_name.get(ps.get("name"))
                        if p is None:
                            continue
                        s_pan, s_tilt = getattr(self, '_pos_anim_start_vals', {}).get(
                            id(p), (getattr(p, 'pan', 32768), getattr(p, 'tilt', 32768)))
                        t_pan  = int(ps.get("pan",  32768))
                        t_tilt = int(ps.get("tilt", 32768))
                        p.pan  = int(s_pan  + (t_pan  - s_pan)  * frac)
                        p.tilt = int(s_tilt + (t_tilt - s_tilt) * frac)
            # --- Cas 2 : trajectoire ou effet automatique (16-bit) ---
            elif lyres_clip.get('move_effect') or 'pan_start' in lyres_clip:
                self._pos_anim_target_idx = None  # pas de preset actif
                move_effect  = lyres_clip.get('move_effect')
                move_speed   = lyres_clip.get('move_speed', 0.5)
                move_amp     = lyres_clip.get('move_amplitude', 60)
                progress     = lyres_clip.get('move_progress', 0.0)
                elapsed      = lyres_clip.get('move_elapsed', 0.0)

                pan_start    = lyres_clip.get('pan_start', 128)
                tilt_start   = lyres_clip.get('tilt_start', 128)
                pan_end      = lyres_clip.get('pan_end', 128)
                tilt_end     = lyres_clip.get('tilt_end', 128)

                if move_effect:
                    # Effets auto — centre 0-255 (spinbox dialog), amplitude 5-120, converti en 16-bit
                    t        = elapsed * move_speed * 2 * math.pi
                    ctr_pan  = pan_start  * 257   # 0-255 → 0-65535
                    ctr_tilt = tilt_start * 257
                    amp_16   = move_amp   * 256   # 5-120 → 1280-30720
                    if move_effect == 'cercle':
                        pan_val  = ctr_pan  + int(amp_16 * math.cos(t))
                        tilt_val = ctr_tilt + int(amp_16 * math.sin(t))
                    elif move_effect == 'figure8':
                        pan_val  = ctr_pan  + int(amp_16 * math.sin(t))
                        tilt_val = ctr_tilt + int(amp_16 * math.sin(2 * t) / 2)
                    elif move_effect == 'balayage_h':
                        pan_val  = ctr_pan  + int(amp_16 * math.sin(t))
                        tilt_val = ctr_tilt
                    elif move_effect == 'balayage_v':
                        pan_val  = ctr_pan
                        tilt_val = ctr_tilt + int(amp_16 * math.sin(t))
                    elif move_effect == 'aleatoire':
                        pan_val  = ctr_pan  + int(amp_16 * 0.6 * math.sin(t * 1.0) +
                                                  amp_16 * 0.4 * math.sin(t * 1.7 + 1.3))
                        tilt_val = ctr_tilt + int(amp_16 * 0.6 * math.cos(t * 0.8 + 0.7) +
                                                  amp_16 * 0.4 * math.cos(t * 2.1 + 2.5))
                    else:
                        pan_val  = ctr_pan
                        tilt_val = ctr_tilt
                else:
                    # Trajectoire linéaire — valeurs 16-bit (PanTiltPad, 0-65535)
                    p = max(0.0, min(1.0, progress))
                    pan_val  = int(pan_start  + (pan_end  - pan_start)  * p)
                    tilt_val = int(tilt_start + (tilt_end - tilt_start) * p)

                pan_val  = max(0, min(65535, pan_val))
                tilt_val = max(0, min(65535, tilt_val))

                for idx in lyres_indices:
                    if idx < len(self.player_ui.projectors):
                        proj = self.player_ui.projectors[idx]
                        proj.pan  = pan_val
                        proj.tilt = tilt_val

        # ── Appliquer la séquence mémoire par-dessus les groupes ────────────
        self._apply_seq_memory(active_clips.get('Séquence'), main_win)

        # ── Appliquer l'effet de la piste Effet par-dessus tout ─────────────
        # (le effect_timer n'est pas actif en mode timeline — on gère ici)
        if getattr(main_win, 'active_effect', None) is not None:
            if hasattr(main_win, 'update_effect'):
                main_win.update_effect()

        if hasattr(self.player_ui, 'artnet') and self.player_ui.artnet:
            self.player_ui.artnet.update_from_projectors(self.player_ui.projectors)

            if hasattr(self.player_ui, 'plan') and self.player_ui.plan:
                self.player_ui.plan.refresh()

    def play_keyframes_sequence(self, row):
        """Joue sequence keyframes"""
        sequence = self.sequences[row]
        keyframes = sequence["keyframes"]

        if not keyframes:
            return

        main_window = self.player_ui
        main_window.recording_waveform.clear()

        for kf in keyframes:
            pad_color = None
            if kf.get("active_pad"):
                pad_color = QColor(kf["active_pad"]["color"])
            main_window.recording_waveform.add_keyframe(
                kf["time"],
                kf["faders"],
                pad_color
            )

        main_window.recording_waveform.duration = sequence.get("duration", 0)
        main_window.recording_waveform.show()

        self.playback_row = row
        self.playback_index = 0

        if not self.playback_timer:
            self.playback_timer = QTimer()
            self.playback_timer.timeout.connect(self.update_sequence_playback)

        self.playback_timer.start(50)

    def update_sequence_playback(self):
        """Met a jour la lecture de la sequence"""
        if self.playback_row < 0:
            return

        current_time = self.player_ui.player.position()

        sequence = self.sequences.get(self.playback_row)
        if not sequence:
            return

        keyframes = sequence["keyframes"]

        for i, kf in enumerate(keyframes):
            if kf["time"] <= current_time < (kf["time"] + 500):
                if i != self.playback_index:
                    self.apply_keyframe(kf)
                    self.playback_index = i
                break

    def apply_keyframe(self, keyframe):
        """Applique un keyframe a l'etat AKAI"""
        main_window = self.player_ui

        for i, value in enumerate(keyframe["faders"]):
            if i in main_window.faders:
                main_window.faders[i].value = value
                main_window.set_proj_level(i, value)
                main_window.faders[i].update()

                if MIDI_AVAILABLE and main_window.midi_handler and main_window.midi_handler.midi_out:
                    midi_value = int((value / 100.0) * 127)
                    main_window.midi_handler.set_fader(i, midi_value)

        if keyframe["active_pad"]:
            pad_info = keyframe["active_pad"]
            pad = main_window.pads.get((pad_info["row"], pad_info["col"]))
            if pad:
                main_window.activate_pad(pad, pad_info["col"])

                if MIDI_AVAILABLE and main_window.midi_handler and main_window.midi_handler.midi_out:
                    velocity = rgb_to_akai_velocity(pad.property("base_color"))
                    main_window.midi_handler.set_pad_led(pad_info["row"], pad_info["col"], velocity, 100)

        for i, eff_entry in enumerate(keyframe["active_effects"]):
            if i >= len(main_window.effect_buttons):
                continue
            btn = main_window.effect_buttons[i]
            # Rétrocompat : ancien format bool, nouveau format dict
            if isinstance(eff_entry, bool):
                active = eff_entry
            else:
                active = eff_entry.get("active", False)
                if active:
                    name = eff_entry.get("name", "")
                    cfg  = eff_entry.get("config", {})
                    if name:
                        btn.current_effect = name
                        btn.setToolTip(name)
                        main_window._button_effect_configs[i] = cfg
            if active != btn.active:
                main_window.toggle_effect(i)

    def show_media_context_menu(self, pos):
        """Menu contextuel sur media"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                color: white;
                border: 2px solid #4a4a4a;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 30px;
            }
            QMenu::item:selected {
                background: #4a8aaa;
            }
        """)

        title_item = self.table.item(row, 1)
        path = title_item.data(Qt.UserRole) if title_item else None
        media_type = media_icon(path) if path else None

        # Volume uniquement pour audio et video
        if media_type in ("audio", "video"):
            volume_action = menu.addAction(tr("seq_menu_volume"))
            volume_action.triggered.connect(lambda: self.edit_media_volume(row))

        # Definir la duree uniquement pour les images
        if media_type == "image":
            duration_action = menu.addAction(tr("seq_menu_set_duration"))
            duration_action.triggered.connect(lambda: self.edit_image_duration(row))

        menu.addSeparator()

        rec_action = menu.addAction(tr("seq_menu_rec_light"))
        rec_action.triggered.connect(lambda: self.open_light_editor_for_row(row))

        menu.addSeparator()
        delete_action = menu.addAction(tr("seq_menu_delete"))
        delete_action.triggered.connect(lambda: self.delete_media_row(row))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def edit_media_volume(self, row):
        """Edite le volume d'un media (audio/video uniquement)"""
        vol_item = self.table.item(row, 3)
        if not vol_item or vol_item.text() == "--":
            return

        current_vol = int(vol_item.text())

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("seq_menu_volume"))
        dialog.setFixedSize(350, 200)
        dialog.setStyleSheet("background: #1a1a1a;")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        value_label = QLabel(f"{current_vol}%")
        value_label.setStyleSheet("color: white; font-size: 32px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(current_vol)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2a2a2a;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00d4ff;
                width: 20px;
                height: 20px;
                border-radius: 10px;
                margin: -6px 0;
            }
        """)
        slider.valueChanged.connect(lambda v: value_label.setText(f"{v}%"))
        layout.addWidget(slider)

        btn_layout = QHBoxLayout()

        cancel = QPushButton(tr("btn_cancel_x"))
        cancel.clicked.connect(dialog.reject)
        cancel.setStyleSheet("background: #3a3a3a; color: white; border: none; border-radius: 6px; padding: 10px 20px;")
        btn_layout.addWidget(cancel)

        ok = QPushButton("✅ OK")
        ok.setDefault(True)
        ok.clicked.connect(dialog.accept)
        ok.setStyleSheet("background: #00d4ff; color: black; border: none; border-radius: 6px; padding: 10px 30px; font-weight: bold;")
        btn_layout.addWidget(ok)

        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            vol_item.setText(str(slider.value()))
            self.is_dirty = True

        if hasattr(self.player_ui, 'recording_waveform'):
            self.player_ui.recording_waveform.hide()

    def open_light_editor_for_row(self, row):
        """Ouvre l'editeur de timeline pour ce media"""
        if hasattr(self.player_ui, 'recording_waveform'):
            self.player_ui.recording_waveform.hide()

        self.player_ui.open_light_editor(row)

    def delete_media_row(self, row):
        """Supprime une ligne du sequenceur"""
        if row == self.current_row:
            QMessageBox.warning(self, tr("seq_delete_impossible_title"),
                tr("seq_delete_impossible_msg"))
            return

        item = self.table.item(row, 1)
        media_name = item.text() if item else f"Ligne {row + 1}"

        reply = QMessageBox.question(
            self,
            tr("seq_delete_media_title"),
            tr("seq_delete_media_msg", name=media_name),
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.table.removeRow(row)

            if row in self.sequences:
                del self.sequences[row]

            new_sequences = {}
            for old_row, seq in self.sequences.items():
                if old_row < row:
                    new_sequences[old_row] = seq
                elif old_row > row:
                    new_sequences[old_row - 1] = seq
            self.sequences = new_sequences

            self._reindex_ia_colors(row)  # Also reindexes ia_analysis
            self.is_dirty = True

    def stop_sequence_playback(self):
        """Arrete la lecture de la sequence"""
        if self.playback_timer:
            self.playback_timer.stop()
        self.playback_row = -1
        self.playback_index = 0

        if self.timeline_playback_timer:
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
        if hasattr(self, 'timeline_playback_row'):
            del self.timeline_playback_row
        self.timeline_tracks_data = {}
