"""
Sequenceur - Gestion de la playlist et des sequences lumiere
"""
import os
import sys
import bisect
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QMenu, QComboBox, QFileDialog, QMessageBox, QDialog, QSlider, QSpinBox,
    QStackedWidget, QProgressBar, QColorDialog, QScrollArea,
    QFormLayout, QDoubleSpinBox, QDialogButtonBox, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QMimeData, QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtGui import (QColor, QFont, QBrush, QCursor, QDrag, QActionGroup,
                           QFontMetrics)
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

from core import (fmt_time, media_icon, MIDI_AVAILABLE, rgb_to_akai_velocity,
                  MEDIA_EXTENSIONS_FILTER, apply_special_block, ComboSansMolette)
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
        self.setWindowTitle(tr("seq_live_params"))
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
        tl = QLabel(tr("seq2_live_params_hdr"))
        tl.setStyleSheet("color:#e0e0e0; font-size:14px; font-weight:bold; letter-spacing:2px;")
        root.addWidget(tl)
        root.addWidget(self._sep())

        # ── Source ──────────────────────────────────────────────────────────────
        root.addWidget(self._slbl("SOURCE AUDIO", LS))
        self._source_combo = ComboSansMolette()
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
        rst = QPushButton(tr("seq2_reset"))
        rst.setStyleSheet(self._gbtn())
        rst.setCursor(Qt.PointingHandCursor)
        rst.clicked.connect(self._reset_all)
        cnl = QPushButton(tr("seq_cancel"))
        cnl.setStyleSheet(self._gbtn())
        cnl.setCursor(Qt.PointingHandCursor)
        cnl.clicked.connect(self.reject)
        apl = QPushButton(tr("seq_apply"))
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


class _SeqTile(QFrame):
    """Tuile d'une mémoire de pad, dans l'onglet SÉQUENCE du panneau LIVE.

    Trois états, exactement comme `_MovTile` — c'est le même geste : on
    constitue un POOL, et le moteur en joue une à la fois.
      - idle     : hors pool
      - selected : dans le pool (sera jouée)
      - playing  : en cours

    La pastille reprend la couleur dominante de la mémoire, comme la vignette
    du pad et la bibliothèque de REC Lumière : on retrouve son look à l'œil.
    """
    clicked = Signal(object)   # (mem_col, row)

    _CSS_IDLE     = ("_SeqTile { background:#141414; border:1px solid #252525;"
                     " border-radius:6px; }")
    _CSS_SELECTED = ("_SeqTile { background:#0e0720; border:1px solid #4411aa;"
                     " border-radius:6px; }")
    _CSS_PLAYING  = ("_SeqTile { background:#1e0a42; border:2px solid #bb77ff;"
                     " border-radius:6px; }")

    def __init__(self, ref, name: str, color: QColor, cues: int = 1, parent=None):
        super().__init__(parent)
        self._ref      = ref
        self._color    = QColor(color)
        self._selected = False
        self._playing  = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(54)
        self.setToolTip(name if cues <= 1
                        else tr("live_seq_cues_tip", a0=name, a1=cues))

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(4, 6, 4, 6)
        vbox.setSpacing(3)

        dot_row = QHBoxLayout()
        dot_row.setContentsMargins(0, 0, 0, 0)
        dot_row.addStretch()
        self._dot = QLabel()
        self._dot.setFixedSize(12, 12)
        self._dot.setStyleSheet(
            f"background:{self._color.name()}; border-radius:6px;"
            " border:1px solid #666;")
        dot_row.addWidget(self._dot)
        # Une mémoire à plusieurs cues n'est pas un look, c'est une séquence qui
        # se déroule : le compteur le dit sur la tuile, sinon rien ne distingue
        # les deux avant de l'avoir déclenchée.
        self._cues_lbl = QLabel(f"×{cues}" if cues > 1 else "")
        self._cues_lbl.setStyleSheet(
            "color:#5533aa; font-size:8px; font-weight:bold;"
            " background:transparent; border:none;")
        dot_row.addWidget(self._cues_lbl)
        dot_row.addStretch()
        vbox.addLayout(dot_row)

        self._name = name
        self._lbl = QLabel(name)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setWordWrap(False)
        # Un nom de mémoire est libre (« Refrain chaud contre-jour ») : sans ces
        # deux lignes, la largeur mini du LABEL remonte jusqu'au panneau, qui
        # exigeait alors 1026 px au lieu de 624 — le panneau LIVE déborde et le
        # séquenceur avec. La politique `Ignored` coupe cette remontée, et
        # `resizeEvent` écourte le texte à la largeur réellement disponible.
        # Le nom complet reste lisible en infobulle (posée ci-dessus).
        self._lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        vbox.addWidget(self._lbl)

        self._refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Largeur mesurée sur la TUILE, pas sur le label : quand cet événement
        # arrive, la mise en page interne n'a pas encore redimensionné le label,
        # qui rend donc encore son ancienne largeur — et rien n'était écourté.
        dispo = max(10, self.width() - 12)   # marges du QVBoxLayout (4 + 4) + air
        self._lbl.setText(
            QFontMetrics(self._lbl.font()).elidedText(
                self._name, Qt.ElideRight, dispo))

    @property
    def ref(self):
        return self._ref

    @property
    def is_selected(self) -> bool:
        return self._selected

    @property
    def is_playing(self) -> bool:
        return self._playing

    def set_state(self, selected: bool, playing: bool):
        if (self._selected, self._playing) == (selected, playing):
            return
        self._selected, self._playing = selected, playing
        self._refresh()

    def _refresh(self):
        if self._playing:
            css, fg, dim = self._CSS_PLAYING, "#dd99ff", "#aa77ff"
        elif self._selected:
            css, fg, dim = self._CSS_SELECTED, "#5533aa", "#5533aa"
        else:
            css, fg, dim = self._CSS_IDLE, "#666", "#2d2d2d"
        self.setStyleSheet(css)
        self._lbl.setStyleSheet(
            f"color:{fg}; font-size:8px; font-weight:bold; letter-spacing:0.5px;"
            " background:transparent; border:none;")
        self._cues_lbl.setStyleSheet(
            f"color:{dim}; font-size:8px; font-weight:bold;"
            " background:transparent; border:none;")

    def mousePressEvent(self, event):
        self.clicked.emit(self._ref)
        super().mousePressEvent(event)


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
    dimmers_changed     = Signal(dict)    # {groupe: 0–100} dimmer max par groupe
    sequences_changed   = Signal(list)    # [(mem_col, row), ...] pool de mémoires

    # Sources fixes + périphériques dynamiques (ajoutés à l'init)
    _SOURCES_STATIC = [
        ("Micro / Line In",                              "mic"),
        ("MIDI Clock",                                   "midi_clock"),
    ]

    SOURCES = [
        ("Micro / Line In",                              "mic"),
        ("MIDI Clock",                                   "midi_clock"),
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
        "midi_clock": "BPM + beats depuis votre logiciel DJ (Traktor, VirtualDJ…) — configuration : bouton ?",
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
        # Quatre teintes OPPOSEES (0/120/240/300 deg), pas quatre chaudes.
        # L'ancien defaut rouge/orange/jaune/ambre tient dans 60 deg de
        # teinte : sur un PAR LED le cycle se lisait comme une couleur
        # fixe, et c'est le tout premier reglage que voit un nouvel
        # utilisateur de l'IA (retour client, 02/09/2026).
        self._color_tile_pool  = {'rouge', 'vert', 'bleu', 'rose'}
        self._current_color    = 'rouge'
        self._color_duration   = 40         # durée en % (0-100)
        self._color_restrict   = True       # toujours restreindre à la sélection
        # Les périphériques audio NE sont PAS énumérés ici : les lister charge
        # PortAudio, dont l'initialisation peut tuer le process (access
        # violation non rattrapable) selon les pilotes de la machine — et donc
        # empêcher MyStrow de démarrer alors que l'utilisateur ne veut même pas
        # du mode LIVE. L'énumération se fait au premier affichage du panneau
        # (showEvent), c'est-à-dire quand on passe vraiment en mode LIVE.
        self._audio_sources_loaded = False

        self._color_max        = 4          # nombre de couleurs simultanées max (1-4)
        # ── Effet spécial (radio : un seul à la fois) ─────────────────────
        self._active_special   = None       # None | 'strobe' | 'strobe_couleur' | 'fixe_blanc'
        self._passage_speed    = 50         # vitesse du passage (1-100)
        self._gobo_pool        = {0}         # set de slots sélectionnés (comme _movement_patterns)
        self._current_gobo     = 0          # slot actif en cours
        self._gobo_duration    = 40         # durée par gobo en % (0-100)
        self._gobo_rotation    = False      # rotation activée
        self._gobo_rot_speed   = 50         # vitesse rotation (1-100)
        # Strobe = choix exclusif (radio) : un seul des 3 actif à la fois
        self._strob_fast       = True       # strobe rapide (défaut)
        self._strob_slow       = False      # strobe lent
        self._strob_none       = False      # pas de strobe
        self._live_config   = {
            'source':          'loopback',
            'allowed_groups':  set(),
            'allowed_effects': set(),
            'lyre_presets':    [],
            'palette':         [],
            'no_auto_strobe':  False,
        }
        self._pos_getter = None
        # ── Onglet SÉQUENCE : pool de mémoires de pads ────────────────────
        # Même mécanique que le pool de mouvements : plusieurs mémoires cochées,
        # le moteur en joue UNE à la fois et passe à la suivante selon DURÉE.
        # Le panneau ne connaît pas `main_window` : il reçoit la liste des
        # mémoires par un getter injecté (même patron que `_pos_getter`) et
        # renvoie son pool par signal. La grille est reconstruite à chaque
        # entrée en LIVE — une mémoire enregistrée entre-temps y apparaît sans
        # redémarrage.
        self._seq_getter    = None
        self._seq_tiles     = {}     # (mem_col, row) -> _SeqTile
        self._seq_pool      = []     # refs cochées, dans l'ordre d'appui
        self._current_seq   = None   # ref en cours de lecture
        self._seq_duration  = 10     # durée par mémoire en SECONDES (1-60)
        self._seq_intensity = 100    # % appliqué aux mémoires jouées ici
        self._seq_positions = False  # la mémoire impose-t-elle le pan/tilt ?
        self._seq_overrides = set()  # onglets repris par la mémoire en cours
        # Charger la config sauvegardée AVANT _setup_ui (les valeurs sont lues à la construction)
        self._load_live_panel_config()

        self._setup_ui()

        # Appliquer sensibilité et luminosité chargées
        if hasattr(self, '_saved_sensitivity') and hasattr(self, '_vu_sens'):
            self._vu_sens._sens = self._saved_sensitivity
            self._vu_sens._sens_proxy.setValue(self._saved_sensitivity)
        if hasattr(self, '_saved_luminosity') and hasattr(self, 'lumi_slider'):
            self.lumi_slider.setValue(self._saved_luminosity)

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
    def color_cycle(self) -> bool:
        """Le moteur doit-il faire défiler le pool de couleurs ?

        Toujours oui côté panneau LIVE : « Couleurs simultanées » y compte les
        couleurs présentes EN MÊME TEMPS sur le plan, pas le nombre de couleurs
        que le morceau a le droit de traverser — c'est le curseur DURÉE qui
        règle le défilement. À 1, on veut donc une couleur à la fois, qui
        défile ; le préréglage d'un média (`IASettings`), lui, entend « 1 » au
        sens d'une couleur tenue, et rend `False`.
        """
        return True

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
                'seq_duration':     self._seq_duration,
                'seq_intensity':    self._seq_intensity,
                'seq_positions':    self._seq_positions,
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
            self._seq_duration      = max(1, min(60, int(
                cfg.get('seq_duration', self._seq_duration))))
            self._seq_intensity     = int(cfg.get('seq_intensity', self._seq_intensity))
            self._seq_positions     = bool(cfg.get('seq_positions', self._seq_positions))
            self._saved_sensitivity = int(cfg.get('sensitivity', 80))
            self._saved_luminosity  = int(cfg.get('luminosity', 100))
        except Exception as e:
            print(f"[LivePanel] load: {e}")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        lbl_style = "color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;"

        # ── Source : combo caché (état interne) — affiché dans la carte INPUT ──
        # Le sélecteur visible est la carte INPUT elle-même (clique → ⚙ paramètres).
        self.source_combo = ComboSansMolette()
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
        self._conn_dot.setToolTip(tr("seq_conn_status"))
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
        # Slider luminosité caché — conservé pour compatibilité signaux
        self.lumi_slider = QSlider(Qt.Horizontal)
        self.lumi_slider.setRange(0, 100)
        self.lumi_slider.setValue(100)
        self.lumi_slider.hide()

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

        # ── Panel Mouvements ────────────────────────────────────────────────
        layout.addWidget(self._build_movement_panel())

        layout.addStretch()


        self.setStyleSheet("""
            LiveModePanel {
                background: #0d0d0d;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
            }
            /* QLabel derive de QFrame : la regle globale
               `QFrame { border: 1px solid #1a1a1a; }` (main_window.apply_styles)
               dessinait donc un petit rectangle autour de CHAQUE texte du
               panneau. Les 22 labels concernes ne s'en excluaient pas un par
               un — on neutralise ici pour tout le panneau, y compris les
               labels ajoutes plus tard. Un label qui definit sa propre
               bordure garde la sienne (son style prime sur celui du parent). */
            QLabel { border: none; background: transparent; }
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
        # Le guide de configuration est désormais en ligne (bouton "?" de la carte INPUT) :
        # on n'affiche plus les instructions loopMIDI in-app (incorrectes sur Mac).
        self._midi_setup.setVisible(False)
        if hasattr(self, '_source_help_btn'):
            self._source_help_btn.setVisible(False)
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
        self._midi_ctrl_combo = ComboSansMolette()
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

        self._midi_status_lbl = QLabel(tr("seq2_checking"))
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
        dj_lbl = QLabel(tr("seq_software"))
        dj_lbl.setStyleSheet("color:#446644; font-size:9px; background:transparent; border:none;")
        dj_lbl.setFixedWidth(52)
        dj_row.addWidget(dj_lbl)
        self._midi_dj_combo = ComboSansMolette()
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
        dlg.setWindowTitle(tr("seq_midi_clock_guide"))
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

        title = QLabel(tr("seq_midi_clock_guide_m"))
        title.setStyleSheet("color:#00aaff; font-size:15px; font-weight:bold;")
        lay.addWidget(title)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border-top:1px solid #222;")
        lay.addWidget(sep)

        # Sélecteur logiciel
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("seq_dj_software")))
        combo = ComboSansMolette()
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

        close_btn = QPushButton(tr("seq_close"))
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
                self._midi_ctrl_combo.addItem(tr("seq_no_midi_port"))
            else:
                for p in ports:
                    self._midi_ctrl_combo.addItem(p)
                # Pré-sélectionner le port MyStrow si présent
                for i in range(self._midi_ctrl_combo.count()):
                    if 'mystrow' in self._midi_ctrl_combo.itemText(i).lower():
                        self._midi_ctrl_combo.setCurrentIndex(i)
                        break
        except Exception:
            self._midi_ctrl_combo.addItem(tr("seq_no_rtmidi"))

    def _refresh_midi_status(self):
        installed = LoopMidiHelper.is_installed()
        has_port  = LoopMidiHelper.has_port() if installed else False

        if has_port:
            self._midi_dot.setStyleSheet(
                "background: #00cc44; border-radius: 5px;")
            self._midi_status_lbl.setText(
                tr("seq_f_port_active", a0=LoopMidiHelper.PORT_NAME))
            self._midi_btn.setText(tr("seq2_refresh"))
            self._midi_instr_lbl.show()
        elif installed:
            self._midi_dot.setStyleSheet(
                "background: #ffaa00; border-radius: 5px;")
            self._midi_status_lbl.setText(
                tr("seq2_loopmidi_port"))
            self._midi_btn.setText(tr("seq_f_create_port", a0=LoopMidiHelper.PORT_NAME))
            self._midi_instr_lbl.hide()
        else:
            self._midi_dot.setStyleSheet(
                "background: #444; border-radius: 5px;")
            self._midi_status_lbl.setText(tr("seq2_loopmidi_none"))
            self._midi_btn.setText(tr("seq_install_loopmidi"))
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

    def set_status(self, bpm=None, section=None):
        if bpm is not None:
            self.set_bpm_auto(bpm)

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

    # Onglets du panneau d'effets. Source UNIQUE : la barre de boutons et la
    # pile de pages étaient deux listes recopiées à la main, qui divergeaient au
    # premier onglet ajouté (bouton présent, page absente — ou l'inverse).
    _EFFECT_TABS = ("MOUVEMENT", "DIMMER", "COULEURS", "GOBO",
                    "STROB", "SPÉCIAL", "SÉQUENCE")

    # Clés stables des mêmes onglets. Le moteur désigne par elles les onglets
    # qu'une mémoire reprend : il n'a pas à connaître des libellés d'interface,
    # qui sont du texte affiché et changeront le jour où ils seront traduits.
    _EFFECT_TAB_KEYS = ("mouvement", "dimmer", "couleurs", "gobo",
                        "strob", "special", "sequence")

    _MOVEMENTS = [
        ('vague',     '〜', 'VAGUE'),
        ('cercle',    '○',  'CERCLE'),
        ('diagonale', '╱',  'DIAGONALE'),
        ('spirale',   '⊛',  'SPIRALE'),
        ('bounce',    '⇔',  'BOUNCE'),
        ('huit',      '∞',  'HUIT'),
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

    def _build_movement_panel(self) -> QWidget:
        """Conteneur principal avec onglets MOUVEMENT / COULEURS / SPÉCIAL."""
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(8)

        # ── Barre d'onglets ───────────────────────────────────────────────
        # Les sept onglets sur UNE ligne, sans titre à gauche.
        #
        # Le titre « EFFETS » a sauté : il ne nommait rien que les onglets ne
        # disent déjà, et il coûtait 68 px de largeur minimale — de quoi faire
        # basculer la barre sur deux lignes une fois le 7e onglet ajouté. Le
        # padding passe de 8 à 6 px dans la foulée. Ces deux gestes ramènent la
        # largeur minimale du panneau à 617 px, soit MOINS que les 624 px qu'il
        # exigeait à six onglets et avec le titre.
        #
        # Ce n'est pas cosmétique : le panneau LIVE vit dans un QScrollArea dont
        # la barre horizontale est désactivée (cf. `_live_scroll`). Ce qui
        # dépasse est COUPÉ, pas atteignable — un onglet hors champ serait un
        # onglet mort. Toute modification de cette barre doit donc se mesurer,
        # pas s'estimer.
        # Un vrai bandeau d'onglets, pas sept boutons côte à côte : segments
        # jointifs (espacement nul), soulignés d'un trait continu que seul
        # l'onglet actif allume en violet. On lit d'un coup d'œil où on est, et
        # le bandeau se rattache visuellement à la page qu'il commande.
        bande = QWidget()
        bande.setObjectName("effectTabBar")
        bande.setStyleSheet(
            "#effectTabBar { background:#101010; border:1px solid #1e1e1e;"
            " border-radius:5px; }")
        hdr = QHBoxLayout(bande)
        hdr.setContentsMargins(2, 2, 2, 2)
        hdr.setSpacing(0)

        self._effect_tab_on  = (
            "QPushButton { background:#1a0a3a; color:#bb88ff;"
            " border:none; border-bottom:2px solid #8844ff; border-radius:3px;"
            " font-size:9px; font-weight:bold; padding:4px 5px; }"
        )
        self._effect_tab_off = (
            "QPushButton { background:transparent; color:#555;"
            " border:none; border-bottom:2px solid #1e1e1e; border-radius:3px;"
            " font-size:9px; font-weight:bold; padding:4px 5px; }"
            "QPushButton:hover { color:#9977cc; background:#161616; }"
        )
        # « Repris par la mémoire en cours » : ambre, pour ne pas se confondre
        # avec le violet qui dit « tu es ici ». Un onglet peut être les deux.
        self._effect_tab_over = (
            "QPushButton { background:transparent; color:#aa7733;"
            " border:none; border-bottom:2px solid #6a4416; border-radius:3px;"
            " font-size:9px; font-weight:bold; padding:4px 5px; }"
            "QPushButton:hover { color:#ddaa55; background:#161616; }"
        )
        self._effect_tab_on_over = (
            "QPushButton { background:#1a0a3a; color:#ddaa55;"
            " border:none; border-bottom:2px solid #cc8833; border-radius:3px;"
            " font-size:9px; font-weight:bold; padding:4px 5px; }"
        )
        self._effect_tab_btns: dict[str, QPushButton] = {}
        for i, tab_label in enumerate(self._EFFECT_TABS):
            btn = QPushButton(tab_label)
            btn.setFixedHeight(24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._effect_tab_on if i == 0 else self._effect_tab_off)
            btn.clicked.connect(lambda _=False, idx=i: self._switch_effect_tab(idx))
            self._effect_tab_btns[tab_label] = btn
            # Facteur d'étirement identique : les onglets se partagent la largeur
            # à parts égales au lieu de se tasser à gauche en laissant un trou.
            hdr.addWidget(btn, 1)

        self._effect_tab_idx = 0
        self._maj_tab_styles()
        vbox.addWidget(bande)

        # ── Pages (QStackedWidget) ────────────────────────────────────────
        self._effect_stack = QStackedWidget()
        self._effect_stack.addWidget(self._build_movement_content())  # 0
        self._effect_stack.addWidget(self._build_dimmer_content())    # 1
        self._effect_stack.addWidget(self._build_color_content())     # 2
        self._effect_stack.addWidget(self._build_gobo_content())      # 3
        self._effect_stack.addWidget(self._build_strob_content())     # 4
        self._effect_stack.addWidget(self._build_special_content())   # 5
        self._effect_stack.addWidget(self._build_sequence_content())  # 6
        self._effect_stack.setCurrentIndex(0)
        vbox.addWidget(self._effect_stack)

        return container

    def _switch_effect_tab(self, idx: int):
        """Bascule d'un onglet d'effets à l'autre (cf. `_EFFECT_TABS`)."""
        self._effect_stack.setCurrentIndex(idx)
        self._effect_tab_idx = idx
        self._maj_tab_styles()

    def set_sequence_overrides(self, cles):
        """Onglets dont la mémoire en cours reprend les réglages (clés stables).

        Appelée par le moteur à chaque changement de mémoire ou de cue — jamais
        par image. Purement informatif : les onglets restent cliquables et
        continuent d'agir là où la mémoire ne va pas (elle ne s'empare que des
        projecteurs qu'elle allume et des canaux qu'elle a réglés).
        """
        cles = set(cles or ())
        if cles == self._seq_overrides:
            return
        self._seq_overrides = cles
        self._maj_tab_styles()

    def _maj_tab_styles(self):
        """Applique à chaque onglet son style : actif, repris, ou les deux.

        Le marquage passe par la COULEUR (texte + soulignement), jamais par un
        caractère ajouté au libellé : la barre doit tenir sur une ligne dans un
        QScrollArea sans défilement horizontal, un libellé qui s'allonge la
        ferait déborder — et ce qui déborde est coupé, pas atteignable.
        """
        if not hasattr(self, '_effect_tab_btns'):
            return
        for i, label in enumerate(self._EFFECT_TABS):
            btn = self._effect_tab_btns.get(label)
            if btn is None:
                continue
            actif  = (i == self._effect_tab_idx)
            repris = self._EFFECT_TAB_KEYS[i] in self._seq_overrides
            if actif:
                css = self._effect_tab_on_over if repris else self._effect_tab_on
            else:
                css = self._effect_tab_over if repris else self._effect_tab_off
            btn.setStyleSheet(css)
            btn.setToolTip(tr("live_seq_overridden") if repris else "")

    # ── Séquences REC ─────────────────────────────────────────────────────────

    # ── Page 6 : Séquences (mémoires des pads) ────────────────────────────────

    def set_sequences_getter(self, fn):
        """Injecte la source des mémoires de pads affichées dans l'onglet.

        `fn()` doit rendre une liste de dicts {ref: (mem_col, row), name: str,
        color: QColor|str, cues: int}. Le panneau vit dans `sequencer.py` et n'a
        pas accès à `main_window.memories` : même patron d'injection que le
        getter de positions de lyres.
        """
        self._seq_getter = fn
        self.refresh_sequences()

    @property
    def sequence_pool(self) -> list:
        """Mémoires du pool, dans l'ordre de la grille."""
        return list(self._seq_pool)

    @property
    def current_sequence(self):
        """Mémoire en cours de lecture (None si le pool est vide)."""
        return self._current_seq

    @property
    def sequence_duration(self) -> int:
        """Tenue d'une mémoire sans minutage propre, en SECONDES.

        En secondes et non en mesures — contrairement au pool de mouvements —
        parce que l'horloge du LIVE avance même dans le silence (cf.
        `live_audio._process_chunk`, +50 ms par bloc que le RMS soit nul ou
        non) alors que le BPM, lui, retombe à son plancher de 60. Compté en
        mesures, le même réglage aurait donné 20 s sans musique et 9 s sur un
        morceau à 128 — pour un simple changement de look, c'est déroutant
        sans rien apporter.
        """
        return self._seq_duration

    @property
    def sequence_intensity(self) -> int:
        return self._seq_intensity

    @property
    def sequence_positions(self) -> bool:
        """La mémoire jouée impose-t-elle sa position de lyres ?

        Décoché (défaut) : le moteur garde la main sur le pan/tilt, les lyres
        continuent le mouvement de l'onglet MOUVEMENT. Coché : la mémoire
        pointe les lyres là où elle a été enregistrée.
        """
        return self._seq_positions

    def set_current_sequence(self, ref):
        """Appelée par le moteur quand il passe à la mémoire suivante du pool.

        ⚠️ Écrit par le moteur, pas par l'utilisateur : mêmes précautions que
        `set_current_movement`. On ne touche qu'à l'état visuel, jamais au pool.
        """
        ref = tuple(ref) if ref else None
        if ref == self._current_seq:
            return
        self._current_seq = ref
        self._sync_seq_tiles()

    def _build_sequence_content(self) -> QWidget:
        """Grille des mémoires de pads + curseurs DURÉE et INTENSITÉ.

        Même geste que l'onglet MOUVEMENT : on coche plusieurs mémoires pour
        constituer un POOL, le moteur en joue UNE à la fois et passe à la
        suivante toutes les N mesures (curseur DURÉE). Un pool d'une seule
        mémoire = ce look, tenu, sans cycle.
        """
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 4, 0, 0)
        vbox.setSpacing(8)

        self._seq_grid_host = QWidget()
        self._seq_grid = QGridLayout(self._seq_grid_host)
        self._seq_grid.setContentsMargins(0, 0, 0, 0)
        self._seq_grid.setSpacing(6)
        vbox.addWidget(self._seq_grid_host)

        sliders = QHBoxLayout()
        sliders.setSpacing(10)

        def _curseur(txt, valeur, attr, mini, maxi, suffixe):
            h = QHBoxLayout()
            h.setSpacing(5)
            lbl = QLabel(txt)
            lbl.setStyleSheet(
                "color:#666; font-size:9px; font-weight:bold; letter-spacing:0.5px;")
            lbl.setFixedWidth(48)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(mini, maxi)
            sl.setValue(valeur)
            sl.setStyleSheet(self._MOV_SLIDER_STYLE)
            vl = QLabel(f"{valeur}{suffixe}")
            vl.setFixedWidth(30)
            vl.setStyleSheet("color:#aa77ff; font-size:9px; font-weight:bold;")
            sl.valueChanged.connect(lambda v, a=attr, _vl=vl: (
                setattr(self, a, v), _vl.setText(f"{v}{suffixe}"),
                self._request_save()))
            h.addWidget(lbl); h.addWidget(sl); h.addWidget(vl)
            return h

        sliders.addLayout(_curseur(tr("live_seq_duration"),
                                   self._seq_duration, '_seq_duration', 1, 60, " s"))
        sliders.addLayout(_curseur(tr("live_seq_intensity"),
                                   self._seq_intensity, '_seq_intensity', 0, 100, "%"))
        vbox.addLayout(sliders)

        # ── Interrupteur POSITIONS ────────────────────────────────────────
        # Une mémoire capture aussi le pan/tilt des lyres. Appliqué tel quel en
        # LIVE, il les FIGE tant que la mémoire tourne — et comme l'onglet
        # MOUVEMENT refuse de rester vide (`_on_movement_selected` interdit de
        # retirer le dernier motif), un mouvement tourne toujours : la mémoire
        # l'écraserait systématiquement. D'où cet interrupteur, décoché par
        # défaut : la mémoire apporte couleur, gobo et faisceau, les lyres
        # continuent de danser. On le coche quand les mémoires servent
        # justement à POINTER (contre-jour sur le batteur, face au chanteur).
        pos_row = QHBoxLayout()
        pos_row.setSpacing(6)
        self._seq_pos_btn = QPushButton(tr("live_seq_positions"))
        self._seq_pos_btn.setFixedHeight(22)
        self._seq_pos_btn.setCheckable(True)
        self._seq_pos_btn.setChecked(self._seq_positions)
        self._seq_pos_btn.setCursor(Qt.PointingHandCursor)
        self._seq_pos_btn.setToolTip(tr("live_seq_positions_tip"))
        self._seq_pos_btn.toggled.connect(self._on_seq_positions_toggled)
        self._maj_seq_pos_btn()
        pos_row.addWidget(self._seq_pos_btn)
        pos_hint = QLabel(tr("live_seq_positions_hint"))
        pos_hint.setStyleSheet(
            "color:#3a3a3a; font-size:9px; font-style:italic;"
            " background:transparent;")
        pos_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pos_row.addWidget(pos_hint, 1)
        vbox.addLayout(pos_row)

        self.refresh_sequences()
        return w

    def _on_seq_positions_toggled(self, coche: bool):
        self._seq_positions = coche
        self._maj_seq_pos_btn()
        self._request_save()

    # Style propre à l'interrupteur POSITIONS. Il empruntait celui des onglets ;
    # depuis que ceux-ci forment un bandeau souligné, un bouton isolé qui en
    # reprend l'apparence se lit comme un onglet égaré. Il garde donc les
    # couleurs de la famille, mais la forme d'un interrupteur.
    _SEQ_POS_ON = (
        "QPushButton { background:#1a0a3a; color:#bb88ff;"
        " border:1px solid #8844ff; border-radius:11px;"
        " font-size:9px; font-weight:bold; padding:3px 12px; }"
    )
    _SEQ_POS_OFF = (
        "QPushButton { background:#141414; color:#555;"
        " border:1px solid #252525; border-radius:11px;"
        " font-size:9px; font-weight:bold; padding:3px 12px; }"
        "QPushButton:hover { color:#9977cc; border-color:#3a3a3a; }"
    )

    def _maj_seq_pos_btn(self):
        self._seq_pos_btn.setStyleSheet(
            self._SEQ_POS_ON if self._seq_positions else self._SEQ_POS_OFF)

    def refresh_sequences(self):
        """Reconstruit la grille depuis le getter, en gardant le pool courant.

        Une mémoire effacée du pad disparaît donc du pool au lieu d'y rester
        comme une référence morte que le moteur résoudrait dans le vide à
        chaque image.
        """
        if not hasattr(self, '_seq_grid'):
            return   # appelé avant _setup_ui (set_sequences_getter précoce)
        while self._seq_grid.count():
            item = self._seq_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._seq_tiles.clear()

        try:
            entrees = list(self._seq_getter()) if self._seq_getter else []
        except Exception as e:
            print(f"[Live] lecture des mémoires de pads échouée : {e}")
            entrees = []

        if not entrees:
            self._vider_pool_sequences()
            vide = QLabel(tr("live_seq_none"))
            vide.setStyleSheet(
                "color:#2a2a2a; font-size:10px; font-style:italic;"
                " background:transparent; padding:6px 2px;")
            self._seq_grid.addWidget(vide, 0, 0, 1, 4)
            return

        cols = 4
        for i, e in enumerate(entrees):
            ref = tuple(e.get('ref') or ())
            if len(ref) != 2:
                continue
            tuile = _SeqTile(ref, e.get('name') or "MEM",
                             QColor(e.get('color') or "#444444"),
                             int(e.get('cues') or 1), self._seq_grid_host)
            tuile.clicked.connect(self._on_seq_tile_clicked)
            self._seq_tiles[ref] = tuile
            self._seq_grid.addWidget(tuile, i // cols, i % cols)

        # Purger le pool des mémoires qui n'existent plus.
        vivantes = [r for r in self._seq_pool if r in self._seq_tiles]
        if vivantes != self._seq_pool:
            self._seq_pool = vivantes
            self._normaliser_courante()
            self.sequences_changed.emit(list(self._seq_pool))
        self._sync_seq_tiles()

    def _on_seq_tile_clicked(self, ref):
        ref = tuple(ref)
        if ref in self._seq_pool:
            self._seq_pool.remove(ref)
        else:
            self._seq_pool.append(ref)
        self._normaliser_courante()
        self._sync_seq_tiles()
        self.sequences_changed.emit(list(self._seq_pool))

    def _vider_pool_sequences(self):
        """Vide le pool et prévient le moteur, s'il ne l'était pas déjà."""
        if not self._seq_pool and self._current_seq is None:
            return
        self._seq_pool = []
        self._current_seq = None
        for t in self._seq_tiles.values():
            t.set_state(False, False)
        self.sequences_changed.emit([])

    def _normaliser_courante(self):
        """La mémoire en cours doit toujours être dans le pool (ou None)."""
        if self._current_seq not in self._seq_pool:
            self._current_seq = self._seq_pool[0] if self._seq_pool else None

    def _sync_seq_tiles(self):
        for ref, tuile in self._seq_tiles.items():
            tuile.set_state(selected=ref in self._seq_pool,
                            playing=ref == self._current_seq)

    # ── Page 0 : Mouvements ───────────────────────────────────────────────────

    def _build_movement_content(self) -> QWidget:
        """Grille de patterns de mouvement + sliders VITESSE/TAILLE/DURÉE."""
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(0, 4, 0, 0)
        vbox.setSpacing(8)

        self._mov_tiles: dict[str, _MovTile] = {}
        cols = 4
        for row_idx in range((len(self._MOVEMENTS) + cols - 1) // cols):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            for col_idx in range(cols):
                i = row_idx * cols + col_idx
                if i >= len(self._MOVEMENTS):
                    break
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
        dur_lbl_m = QLabel(tr("seq2_duration"))
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
                    self._dimmer_values.__setitem__(g, v), vl.setText(f"{v}%"),
                    self.dimmers_changed.emit(dict(self._dimmer_values))
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
        max_lbl = QLabel(tr("seq2_sim_colours"))
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
        dur_lbl = QLabel(tr("seq2_duration"))
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
            act = menu.addAction(tr("seq_unpin"))
            act.triggered.connect(lambda: self._toggle_pin(key))
        else:
            act = menu.addAction(tr("seq_pin_top"))
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

        # Normalise : exactement UN actif (radio). Priorité fast > slow > none.
        active = ('fast' if self._strob_fast
                  else 'slow' if self._strob_slow
                  else 'none' if self._strob_none
                  else 'fast')
        self._strob_fast = (active == 'fast')
        self._strob_slow = (active == 'slow')
        self._strob_none = (active == 'none')

        self._strob_tiles: dict = {}
        row = QHBoxLayout()
        row.setSpacing(5)
        for key, icon, label, attr in defs:
            tile = _MovTile(key, icon, label)
            on = (key == active)
            tile.set_state(selected=on, playing=on)   # un seul actif (radio)
            tile.clicked.connect(lambda _k, a=attr, t=key: self._on_strob_toggle(a, t))
            self._strob_tiles[key] = tile
            row.addWidget(tile)
        vbox.addLayout(row)

        info = QLabel(
            tr("seq_strobe_hint")
        )
        info.setStyleSheet(
            "color:#333; font-size:8px; background:transparent; padding-top:6px;")
        vbox.addWidget(info)
        vbox.addStretch()
        return w

    def _on_strob_toggle(self, attr: str, key: str):
        # Choix exclusif (radio) : la tuile cliquée devient active, les 2 autres s'éteignent.
        mapping = {'fast': '_strob_fast', 'slow': '_strob_slow', 'none': '_strob_none'}
        for k, a in mapping.items():
            on = (k == key)
            setattr(self, a, on)
            t = self._strob_tiles.get(k)
            if t:
                t.set_state(selected=on, playing=on)
        self._request_save()

    # ── Sources audio dynamiques ─────────────────────────────────────────────

    def showEvent(self, event):
        """Premier affichage du panneau LIVE : c'est là qu'on énumère l'audio.

        Repousser jusqu'ici garantit qu'une machine dont la pile audio fait
        tomber PortAudio peut quand même lancer MyStrow et travailler en
        manuel, en séquenceur ou en REC Lumière.
        """
        super().showEvent(event)
        # Les séquences REC vivent dans les mémoires du show : elles changent
        # entre deux passages en LIVE (nouveau REC, renommage, suppression).
        # On les relit à chaque entrée dans le panneau plutôt qu'une seule fois.
        #
        # AVANT l'énumération audio, volontairement : celle-ci charge PortAudio,
        # dont l'initialisation peut tuer le process sur certaines machines (cf.
        # le commentaire de `live_audio.ensure_sounddevice`). Ce qui ne dépend
        # pas d'elle doit être fait pendant qu'on est encore vivant.
        self.refresh_sequences()
        if not getattr(self, '_audio_sources_loaded', False):
            self._audio_sources_loaded = True
            self._refresh_audio_sources()

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
        dur_lbl = QLabel(tr("seq2_duration"))
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
        spd_lbl = QLabel(tr("seq_rotation"))
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

        # Bouton "?" → ouvre le guide en ligne (synchroniser MyStrow avec un logiciel DJ)
        help_web_btn = QPushButton("?")
        help_web_btn.setFixedSize(18, 18)
        help_web_btn.setCursor(Qt.PointingHandCursor)
        help_web_btn.setToolTip(tr("seq2_sync_help"))
        help_web_btn.setStyleSheet(
            "QPushButton { background:#0a1a2a; color:#00aaff; border:1px solid #0055aa;"
            " border-radius:9px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#0a2a3a; border-color:#00aaff; }"
        )
        help_web_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://mystrow.fr/synchroniser-mystrow-logiciel-dj.html")))
        top.addWidget(help_web_btn)

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
        self._source_help_btn.setToolTip(tr("seq_setup_guide"))
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
        self._vu_sens.setToolTip(tr("seq2_audio_level"))
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
        try:
            self._bpm_val_lbl.setText(f"{bpm:.0f}" if bpm > 0 else "—")
            self._bpm_display.setText(f"{bpm:.0f}  BPM" if bpm > 0 else "—  BPM")
        except RuntimeError:
            pass

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


# Feuille de style UNIQUE des menus du séquenceur.
#
# Il y en avait quatre différentes — clic droit sur une ligne, clic droit sur un
# média, menu de la ligne PAUSE et menu du bouton DMX — avec des bordures, des
# rayons et des couleurs de survol qui ne se ressemblaient pas. Le menu changeait
# donc d'allure selon l'endroit exact du clic, ce qui donnait l'impression que
# ce n'était pas le même logiciel. Un seul style ici, utilisé partout.
#
# `QMenu::item:disabled` sert aux TITRES de section : une action désactivée est
# le seul moyen d'obtenir un intitulé non cliquable dans un QMenu Qt.
_SEQ_MENU_SS = """
    QMenu {
        background: #161616;
        border: 1px solid #2a2a2a;
        border-radius: 6px;
        padding: 6px;
    }
    QMenu::item {
        padding: 7px 26px 7px 24px;
        border-radius: 4px;
        color: #ddd;
        font-size: 12px;
    }
    QMenu::item:selected { background: #2a4a5a; color: #fff; }
    QMenu::item:disabled {
        color: #5a5a5a;
        font-size: 9px;
        font-weight: bold;
        padding: 8px 10px 3px 10px;
    }
    QMenu::separator { height: 1px; background: #2a2a2a; margin: 5px 8px; }
    QMenu::indicator { width: 14px; height: 14px; left: 6px; }
"""


class Sequencer(QFrame):
    """Sequenceur de medias avec gestion des sequences lumiere"""

    # Data-role sur l'item titre (col 1) : True si le média est en lecture boucle.
    # Stocké sur l'item → suit la ligne lors d'un swap et survit à un renommage.
    LOOP_ROLE = Qt.UserRole + 1
    _LOOP_PREFIX = "\U0001f501 "   # « 🔁 » affiché devant le nom dans la playlist

    # Fondus audio de la ligne, en MILLISECONDES, portés par le même item que
    # LOOP_ROLE — donc suivis lors d'un déplacement de ligne et conservés au
    # renommage. 0 = pas de fondu.
    FADE_IN_ROLE  = Qt.UserRole + 2
    FADE_OUT_ROLE = Qt.UserRole + 3

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
        # Prereglages IA Lumiere par ligne — couleurs, mouvements de lyres,
        # gobos et nervosite propres a CE media. `ia_colors` ne portait qu'une
        # couleur dominante ; il est conserve pour l'indicateur de la colonne et
        # pour relire les shows enregistres avant les prereglages.
        self.ia_settings = {}  # {row: IASettings}
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
        self._live_settings_btn.setToolTip(tr("seq2_live_params"))
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
        # Deux cases de marqueurs devant le titre (fondu, boucle) : sans taille
        # explicite, Qt réduit l'image au carré du style et la moitié droite
        # sort du cadre. Voir `_row_marks_icon`.
        self.table.setIconSize(QSize(*self.MARK_ICON_SIZE))
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
        menu.setStyleSheet(_SEQ_MENU_SS)
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
                    title_item.setText(tr("seq_f_pause_ms", minutes=minutes, seconds=seconds))
                else:
                    title_item.setText(tr("seq_f_pause_s", value=value))
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
        btn = QPushButton(tr("seq_manual"), container)
        btn.setObjectName("dmx_btn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        self._style_dmx_btn(btn, "Manuel")

        def _show_mode_menu(_, c=combo, b=btn, r=row):
            # Même section de modes que le clic droit (`_add_dmx_mode_section`) :
            # les deux menus listaient les modes différemment, et celui-ci
            # affichait les codes bruts (« IA Lumiere ») au lieu de libellés.
            menu = QMenu(b)
            menu.setStyleSheet(_SEQ_MENU_SS)
            self._add_dmx_mode_section(menu, r, avec_titre=False)
            menu.addSeparator()
            rec_act = menu.addAction(tr("seq_rec_light"))
            rec_act.setData(("__rec__", r))
            chosen = menu.exec(b.mapToGlobal(b.rect().bottomLeft()))
            if not chosen:
                return
            donnee = chosen.data()
            if isinstance(donnee, (tuple, list)) and donnee and donnee[0] == "__rec__":
                QTimer.singleShot(0, lambda: self.open_light_editor_for_row(r))
            else:
                self._handle_dmx_mode_action(chosen, r)

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
                    settings1 = self.ia_settings.get(r1)
                    settings2 = self.ia_settings.get(r2)

                    self.table.removeCellWidget(r1, col)
                    self.table.removeCellWidget(r2, col)

                    if w2_data:
                        self.table.setCellWidget(r1, col, self._create_dmx_cell_widget(r1))
                        new_combo1 = self._get_dmx_combo(r1)
                        if new_combo1:
                            # Le combo recréé ne contient que Manuel/IA : réinsérer
                            # les modes ajoutés dynamiquement (Play Lumiere/Programme)
                            # sinon setCurrentText échoue et le mode retombe sur
                            # Manuel → REC Lumière orphelin/perdu au déplacement.
                            if new_combo1.findText(w2_data) == -1:
                                new_combo1.addItem(w2_data)
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
                        if settings2 is not None:
                            self.ia_settings[r1] = settings2
                        elif r1 in self.ia_settings:
                            del self.ia_settings[r1]
                    elif w2:
                        self.table.setCellWidget(r1, col, QWidget())

                    if w1_data:
                        self.table.setCellWidget(r2, col, self._create_dmx_cell_widget(r2))
                        new_combo2 = self._get_dmx_combo(r2)
                        if new_combo2:
                            if new_combo2.findText(w1_data) == -1:
                                new_combo2.addItem(w1_data)
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
                        if settings1 is not None:
                            self.ia_settings[r2] = settings1
                        elif r2 in self.ia_settings:
                            del self.ia_settings[r2]
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
        self._delete_rows(rows)

    def _delete_rows(self, rows):
        """Chemin UNIQUE de suppression de lignes : retire chaque ligne (de bas en
        haut) et réindexe sequences / ia_colors / ia_analysis / image_durations via
        _reindex_ia_colors. Toute suppression DOIT passer par ici — dupliquer la
        réindexation ailleurs a déjà causé une perte de REC Lumière."""
        for row in sorted(set(rows), reverse=True):
            self.table.removeRow(row)
            self._reindex_ia_colors(row)
            if self.current_row > row:
                self.current_row -= 1
        self.is_dirty = True

    def _reindex_ia_colors(self, deleted_row):
        """Reindexe ia_colors, ia_settings, ia_analysis et image_durations apres
        suppression d'une ligne"""
        if deleted_row in self.ia_settings:
            del self.ia_settings[deleted_row]
        self.ia_settings = {(r - 1 if r > deleted_row else r): v
                            for r, v in self.ia_settings.items()}

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
        """Décale d'un cran vers le bas TOUTES les données indexées par ligne après
        insertion d'une ligne à `inserted_row` : sequences (REC Lumière) + ia_colors
        + ia_analysis + image_durations. Contrepartie de _reindex_ia_colors (côté
        suppression) — sans ça, insérer une pause au milieu désalignait les
        couleurs/analyses IA et durées des médias situés en dessous."""
        def _shift(d):
            return {(old + 1 if old >= inserted_row else old): v for old, v in d.items()}
        self.sequences       = _shift(self.sequences)
        self.ia_colors       = _shift(self.ia_colors)
        self.ia_settings     = _shift(self.ia_settings)
        self.ia_analysis     = _shift(self.ia_analysis)
        self.image_durations = _shift(self.image_durations)

    def clear_sequence(self):
        self.table.setRowCount(0)
        self.current_row = -1
        self.ia_colors = {}
        self.ia_settings = {}
        self.ia_analysis = {}
        self.image_durations = {}
        self.is_dirty = False

    def set_volume(self, row, value):
        vol = int(value / 1.27)
        if self.table.item(row, 3):
            self.table.item(row, 3).setText(str(vol))
            self.is_dirty = True

    # Noms des modes DMX dans les menus. Volontairement COURTS : une phrase
    # d'explication en face de chaque ligne (« Manuel — faders et pads ») allonge
    # le menu, le rend bavard, et n'apprend rien à quelqu'un qui s'en sert tous
    # les jours. Le nom seul suffit ; le pictogramme reprend celui du badge de la
    # colonne, pour qu'on retrouve la même chose au même endroit.
    #
    # Les CODES restent ceux du combo — voir `_SS_BTN` et la note du chargement de
    # show : on manipule le code, jamais le libellé, sinon `setCurrentText` échoue
    # et le mode retombe silencieusement sur Manuel.
    # Clé i18n de chaque mode. Les libellés étaient écrits en dur en français :
    # le menu restait en français quelle que soit la langue de l'app, alors que
    # tout ce qui l'entoure était traduit. L'emoji vit dans `i18n.py` avec le
    # texte, comme pour les autres entrées de ce menu.
    _MODE_MENU_KEYS = {
        "Manuel":       "seq_mode_manual",
        "IA Lumiere":   "seq_mode_ai",
        "Play Lumiere": "seq_mode_lightseq",
        "Programme":    "seq_mode_program",
    }

    @classmethod
    def _mode_menu_label(cls, code: str) -> str:
        """Libellé affiché d'un mode DMX. Le CODE reste la valeur stockée.

        ⚠️ Ne jamais renvoyer ce libellé à `combo.setCurrentText()` : le combo
        contient les codes (« IA Lumiere »), et les fichiers de show aussi.
        """
        key = cls._MODE_MENU_KEYS.get(code)
        return tr(key) if key else code

    def _add_dmx_mode_section(self, menu, row, avec_titre=True):
        """Ajoute la section « MODE DMX » à un menu, avec le mode courant coché.

        Partagée entre le clic droit sur la ligne et le bouton de la colonne DMX :
        les deux proposaient des choses différentes (le bouton listait les modes,
        le clic droit non), donc l'utilisateur devait deviner lequel des deux
        ouvrir selon ce qu'il voulait faire.

        Rend la liste des actions créées, à passer à `_handle_dmx_mode_action`.
        """
        combo = self._get_dmx_combo(row)
        if combo is None:
            return []
        if avec_titre:
            menu.addAction("MODE DMX").setEnabled(False)

        groupe = QActionGroup(menu)
        groupe.setExclusive(True)
        actions = []
        courant = combo.currentText()
        for i in range(combo.count()):
            code = combo.itemText(i)
            act = menu.addAction(self._mode_menu_label(code))
            act.setCheckable(True)
            act.setChecked(code == courant)
            act.setData(("__mode__", code))
            groupe.addAction(act)
            actions.append(act)

        # Réglages IA : seulement quand la ligne est en IA — ailleurs, l'entrée
        # ouvrirait une fenêtre qui ne piloterait rien.
        if courant == "IA Lumiere":
            act = menu.addAction(tr("seq_mode_ai_settings"))
            act.setData(("__ia_settings__", row))
            actions.append(act)
        return actions

    def _handle_dmx_mode_action(self, action, row) -> bool:
        """Exécute une action produite par `_add_dmx_mode_section`. Rend True si traitée."""
        # ⚠️ Qt fait transiter `setData` par un QVariant, qui rend un tuple sous
        # forme de LISTE. Tester `isinstance(..., tuple)` seul ne matche jamais,
        # et le changement de mode passait silencieusement à la trappe.
        donnee = action.data() if action else None
        if not isinstance(donnee, (tuple, list)) or not donnee:
            return False
        genre = donnee[0]
        if genre == "__mode__":
            code = donnee[1]
            combo = self._get_dmx_combo(row)
            if combo is not None and combo.currentText() != code:
                # Signaux NON bloqués : c'est `on_dmx_changed` qui ouvre les
                # réglages IA et lance l'analyse audio. Le différer d'un tour de
                # boucle laisse le menu se fermer avant qu'une fenêtre modale
                # s'ouvre par-dessus.
                QTimer.singleShot(0, lambda c=combo, m=code: c.setCurrentText(m))
            return True
        if genre == "__ia_settings__":
            QTimer.singleShot(0, lambda r=donnee[1]: self._on_color_indicator_clicked(r))
            return True
        return False

    def show_row_context_menu(self, pos):
        """Menu contextuel sur une ligne du sequenceur"""
        item = self.table.itemAt(pos)
        if not item:
            return

        selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        row = item.row()

        _MENU_SS = _SEQ_MENU_SS   # style commun à tous les menus du séquenceur

        # ── Multi-sélection ────────────────────────────────────────────────
        if len(selected_rows) > 1:
            menu = QMenu(self)
            menu.setStyleSheet(_MENU_SS)
            menu.addAction(tr("seq_f_tracks_sel", a0=len(selected_rows))).setEnabled(False)
            menu.addSeparator()
            menu.addAction("MODE DMX").setEnabled(False)
            ia_act  = menu.addAction(self._mode_menu_label("IA Lumiere"))
            man_act = menu.addAction(self._mode_menu_label("Manuel"))

            # Fondus de toute la sélection. C'est CE menu qui s'ouvre dès qu'il
            # y a plus d'une ligne — l'entrée posée dans le menu à une seule
            # ligne n'y apparaissait jamais, donc régler vingt morceaux d'un
            # coup était impossible alors même que le code savait le faire.
            fade_rows = self.fade_target_rows(row)
            fade_act = fade_off_act = None
            if fade_rows:
                menu.addSeparator()
                menu.addAction("MÉDIA").setEnabled(False)
                fade_act = menu.addAction(
                    tr("seq_menu_fade") + f"  ({len(fade_rows)})")
                if any(any(self.get_row_fades(r)) for r in fade_rows):
                    fade_off_act = menu.addAction(
                        tr("seq_menu_fade_off") + f"  ({len(fade_rows)})")

            menu.addSeparator()
            menu.addAction("ACTION").setEnabled(False)
            # `seq_f_delete` est l'un des rares libellés SANS emoji dans i18n.py
            # (contrairement à `seq_menu_delete`) : celui-ci est donc à sa place.
            del_act = menu.addAction("🗑️  " + tr("seq_f_delete", a0=len(selected_rows)))

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
            elif fade_act is not None and action == fade_act:
                # Différé d'un tour : le menu doit s'être fermé avant qu'une
                # boîte modale s'ouvre par-dessus (même raison qu'au changement
                # de mode DMX plus haut).
                QTimer.singleShot(0, lambda r=fade_rows[0]: self.edit_row_fades(r))
            elif fade_off_act is not None and action == fade_off_act:
                for r in fade_rows:
                    self.set_row_fades(r, 0, 0)
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
            menu.addAction("PAUSE").setEnabled(False)
            edit_action   = menu.addAction(tr("seq_menu_set_duration"))
            menu.addSeparator()
            menu.addAction("LUMIÈRE").setEnabled(False)
            rec_action    = menu.addAction(tr("seq_menu_rec_light"))
            menu.addSeparator()
            menu.addAction("ACTION").setEnabled(False)
            duplicate_action = menu.addAction(tr("seq_duplicate_with_rec"))
            delete_action = menu.addAction(tr("seq_menu_delete"))
            action = menu.exec(self.table.viewport().mapToGlobal(pos))
            if action == edit_action:
                self.edit_pause_duration(row)
            elif action == rec_action:
                self.open_light_editor_for_row(row)
            elif action == duplicate_action:
                self.duplicate_media_row(row)
            elif action == delete_action:
                if row == self.current_row:
                    QMessageBox.warning(self, tr("seq_delete_impossible_title"),
                        tr("seq_delete_impossible_msg"))
                else:
                    self._delete_rows([row])   # chemin de suppression unifié
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
                self._clear_timeline_leftovers()
                if hasattr(self, 'timeline_playback_row'):
                    del self.timeline_playback_row
                self.timeline_tracks_data = {}

        if text == "IA Lumiere":
            self._apply_ia_style(combo)

            if not self._loading:
                # Réglages IA de CETTE ligne (couleurs, mouvements, nervosité).
                color = self._open_ia_settings(row)
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

    def get_ia_settings(self, row):
        """Prereglage IA de cette ligne, cree a la demande.

        Trois provenances, dans cet ordre :
          1. deja en memoire (ou relu du .tui) ;
          2. show enregistre avant les prereglages : on repart de la couleur
             dominante (`ia_colors`) pour rester proche du rendu d'origine ;
          3. ligne neuve : on copie l'etat courant du panneau LIVE, pour que
             l'utilisateur retrouve l'ambiance qu'il vient de regler en live.

        La copie du panneau est faite UNE fois, a la creation : ensuite le
        prereglage vit sa vie et le panneau LIVE peut changer sans toucher au
        show. C'est tout l'interet du reglage par media.
        """
        s = self.ia_settings.get(row)
        if s is not None:
            return s
        from ia_settings import IASettings
        col = self.ia_colors.get(row)
        if col is not None:
            s = IASettings.from_dominant_color(col)
        else:
            s = IASettings.from_panel(getattr(self, 'live_panel', None))
        self.ia_settings[row] = s
        return s

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
        loading.setWindowTitle(tr("seq_ai_light"))
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
        """Clic sur le carre couleur — rouvre les reglages IA sans re-analyser."""
        color = self._open_ia_settings(row)
        if color:
            self.ia_colors[row] = color
            self._update_color_indicator(row, color)
            self.player_ui.audio_ai.set_dominant_color(color)
            self.is_dirty = True

    def _open_ia_settings(self, row):
        """Ouvre les reglages IA de la ligne. Rend la couleur d'indicateur, ou None si annule.

        La couleur rendue sert a deux choses : le carre de la colonne DMX, et la
        `dominant_color` de l'analyse audio — dont l'IA derive encore sa palette
        pour la tuile AUTO et pour les fixtures qu'aucune tuile ne couvre. On la
        prend sur la premiere couleur UNIE du pool : c'est celle que
        l'utilisateur voit jouer en premier, donc celle qui represente le mieux
        l'ambiance qu'il vient de regler.
        """
        from ia_settings_dialog import IASettingsDialog
        titre_item = self.table.item(row, 1)
        titre = titre_item.text() if titre_item else ""
        dlg = IASettingsDialog(self.get_ia_settings(row), titre, self)
        if dlg.exec() != QDialog.Accepted:
            return None
        reglages = dlg.resultat()
        self.ia_settings[row] = reglages
        self.is_dirty = True

        for key in [reglages.current_color_tile] + list(reglages.color_tile_pool):
            c1, _ = reglages.get_color_data(key)
            if c1 is not None:
                return c1
        # Pool ne contenant que AUTO : l'IA choisit seule, on garde un repere neutre.
        return QColor("#ffffff")

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
            if self._fade_out_before(row):
                return          # on repassera ici une fois le fondu terminé
            try:
                self.update_playing_indicator(row)

                # Arreter le timer timeline du media precedent
                if self.timeline_playback_timer and self.timeline_playback_timer.isActive():
                    self._stop_timeline_effect()
                    self.timeline_playback_timer.stop()
                    # Sinon le REC Lumiere du media precedent laissait ses canaux
                    # bruts / gobo / strobe colles sur le media suivant.
                    self._clear_timeline_leftovers()
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
                            # Manuel = aucun MOTEUR de lumiere. On efface le look
                            # laisse par le media precedent, puis on repose ce que
                            # l'APC tient a la main (cf. restore_manual_look).
                            for p in self.player_ui.projectors:
                                p.level = 0
                                p.color = QColor("black")
                                p.base_color = QColor("black")
                            self.player_ui.restore_manual_look()
                        elif dmx_mode in ["Programme", "Play Lumiere"] and row in self.sequences:
                            self.play_sequence(row)
                        return

                    # Cacher l'image si affichee precedemment
                    if hasattr(self.player_ui, 'hide_image'):
                        self.player_ui.hide_image()

                    # Nouveau média : le fondu de queue de la piste précédente
                    # est terminé, on réarme pour celle-ci.
                    self.player_ui._audio_fade_reset()
                    fade_in, _ = self.get_row_fades(row)
                    # Volume posé AVANT play() dans les deux cas : démarrer au
                    # volume plein puis descendre laisserait passer un éclat.
                    self.player_ui.audio.setVolume(0.0 if fade_in > 0 else vol / 100)
                    # Arreter proprement l'ancien media avant de changer de source
                    # (evite les signaux Qt parasites EndOfMedia lors du changement)
                    self.player_ui.player.stop()
                    self.player_ui._media_source_row = row
                    self.player_ui.player.setSource(QUrl.fromLocalFile(path))
                    self.player_ui.player.play()
                    if fade_in > 0:
                        self.player_ui.start_audio_fade(vol / 100, fade_in)

                    # Mettre a jour la sortie video externe
                    if hasattr(self.player_ui, '_update_video_output_state'):
                        self.player_ui._update_video_output_state()

                    if dmx_mode == "Manuel":
                        # Manuel = pas de lumiere AUTOMATIQUE. On efface le look du
                        # media precedent, mais l'eclairage monte a la main sur
                        # l'APC (pad couleur + fader) n'a aucune raison de s'eteindre
                        # parce qu'on lance une piste : c'est justement lui qui tient
                        # la salle entre deux morceaux. Voir restore_manual_look().
                        for p in self.player_ui.projectors:
                            p.level = 0
                            p.color = QColor("black")
                            p.base_color = QColor("black")
                        self.player_ui.restore_manual_look()
                        self.player_ui.recording_waveform.hide()
                    elif dmx_mode in ["Programme", "Play Lumiere"]:
                        self.play_sequence(row)
                    else:
                        self.player_ui.recording_waveform.hide()

            except Exception as e:
                print(f"Erreur lecture: {e}")
                QMessageBox.critical(None, tr("err_save_title"), tr("seq_err_play_msg", e=e))

    def _log_tick_error(self, where, exc):
        """Log throttlé d'une exception survenue dans un callback de timer.

        Un timer de restitution tique à 20 Hz : sans throttling, une erreur
        récurrente inonderait la console. On ne réémet un message que si le
        texte d'erreur change (nouveau type de défaut).
        """
        try:
            key = f"{where}:{type(exc).__name__}:{exc}"
            if getattr(self, '_last_tick_error', None) != key:
                self._last_tick_error = key
                import traceback
                print(f"[restitution:{where}] {type(exc).__name__}: {exc}")
                traceback.print_exc()
        except Exception:
            pass

    def update_tempo_timeline(self):
        """Callback QTimer (100 ms) — protégé : une exception non rattrapée
        dans un slot de timer fait crasher tout MyStrow (PySide6 abort). On
        logge au lieu de crasher pour ne jamais interrompre un show."""
        try:
            self._do_update_tempo_timeline()
        except Exception as e:
            self._log_tick_error('tempo', e)

    def _do_update_tempo_timeline(self):
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
            self._clear_timeline_leftovers()
        if hasattr(self, 'timeline_playback_row'):
            del self.timeline_playback_row
        self.timeline_tracks_data = {}

        # Image en boucle : rejouer la même ligne au lieu d'avancer
        if self.is_row_loop(tempo_row):
            self.play_row(tempo_row)
            return

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

    def ensure_light_playback_armed(self):
        """Arme la restitution lumière de la ligne courante si elle ne l'est pas.

        `play_row()` était le SEUL endroit qui armait la lumière : appuyer sur
        Play sur un média DÉJÀ chargé (bouton, barre d'espace, pad PLAY de
        l'APC, tablette, fenêtre EXT — tout passe par `MainWindow.toggle_play`)
        se contentait de `player.play()`, donc le son repartait sans la lumière.

        Le cas typique remonté : on enregistre un REC Lumière, on sauvegarde —
        ce qui bascule la ligne en « Play Lumiere » et referme l'éditeur, en
        laissant le lecteur en pause —, on revient à l'écran principal et on
        fait Play. Sans re-double-cliquer le média, la séquence ne partait
        jamais. Elle n'existait même pas encore au moment du dernier `play_row`.

        Sans effet si la restitution tourne déjà (reprise après pause) : la
        garde évite de repartir du début de la séquence. Armer en cours de
        morceau est sûr, la restitution est pilotée par `player.position()` et
        rattrape l'état des clips à la position courante dès le premier tick.
        """
        row = getattr(self, 'current_row', -1)
        if row is None or row < 0 or row not in self.sequences:
            return
        if self.get_dmx_mode(row) not in ("Programme", "Play Lumiere"):
            return
        sequence = self.sequences[row] or {}
        if "clips" in sequence:
            deja_arme = (getattr(self, 'timeline_playback_row', None) == row
                         and self.timeline_playback_timer is not None
                         and self.timeline_playback_timer.isActive())
        elif "keyframes" in sequence:
            deja_arme = (getattr(self, 'playback_row', -1) == row
                         and self.playback_timer is not None
                         and self.playback_timer.isActive())
        else:
            return
        if not deja_arme:
            self.play_sequence(row)

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

        # Positions : resynchroniser les copies AKAI sur les presets du plan de
        # feu AVANT de jouer. Un show lancé sans repasser par REC Lumière
        # rejouerait sinon une copie figée — une lyre ajoutée au rig puis
        # fusionnée dans la position resterait immobile. Parité avec l'aperçu.
        if hasattr(main_win, 'sync_pdf_positions_into_akai'):
            main_win.sync_pdf_positions_into_akai()
        if hasattr(main_win, 'effect_timer') and main_win.effect_timer.isActive():
            main_win.effect_timer.stop()
        if getattr(main_win, 'active_effect', None) is not None:
            main_win.active_effect = None
            main_win.active_effect_config = {}

        self.timeline_playback_row = row
        self.timeline_tracks_data = tracks_clips
        self.timeline_last_update = -100  # Garantit que le 1er tick fire immediatement
        self._timeline_tick = 0  # Repart de zero pour les effets

        # Pré-indexation : clips triés par start + tableau des starts pour une
        # recherche bisect O(log N) à chaque tick, au lieu de balayer TOUS les
        # clips (O(N)). Décisif sur un REC long/dense (vidéo 40 min) où le
        # balayage par tick saturait le thread UI.
        self._timeline_sorted = {}
        _max_end = 0
        # Ordre d'insertion = ordre d'application (`apply_timeline_to_dmx` parcourt
        # `active_clips` dans cet ordre, sur un rig remis à blanc chaque frame :
        # la dernière piste écrite gagne). Les pistes « un projecteur seul »
        # passent donc TOUJOURS en dernier, pour primer sur celle de leur groupe.
        # L'éditeur les range déjà en fin de timeline, mais on ne veut pas que la
        # règle de priorité repose sur l'ordre des lignes d'un fichier .tui.
        from core import is_projector_track as _is_proj_track
        _ordre = sorted(tracks_clips.items(), key=lambda kv: _is_proj_track(kv[0]))
        for _tname, _clips in _ordre:
            _sc = sorted(_clips, key=lambda c: c.get('start', 0))
            self._timeline_sorted[_tname] = (_sc, [c.get('start', 0) for c in _sc])
            for _c in _sc:
                _e = _c.get('start', 0) + _c.get('duration', 0)
                if _e > _max_end:
                    _max_end = _e
        self._timeline_last_end = _max_end

        if not self.timeline_playback_timer:
            self.timeline_playback_timer = QTimer()
            self.timeline_playback_timer.timeout.connect(self.update_timeline_playback)

        self.timeline_playback_timer.start(50)

    def update_timeline_playback(self):
        """Callback QTimer (50 ms) — protégé : une exception non rattrapée dans
        ce slot (clip malformé, couleur invalide, attribut projecteur manquant…)
        ferait crasher tout MyStrow en plein show (PySide6 abort). On logge."""
        try:
            self._do_update_timeline_playback()
        except Exception as e:
            self._log_tick_error('timeline', e)

    def _media_light_time(self):
        """Position média (ms) corrigée de l'offset de synchro lumière.

        Sur une vidéo, QMediaPlayer.position() peut devancer le son audible
        (latence du pipeline vidéo) → les lumières partent trop tôt. L'offset
        (global, réglable, défaut 0) retarde l'horloge lumière pour recaler sur
        le son. Réglé une fois par machine (menu Réglages → Synchro lumière/vidéo).

        IMPORTANT : l'offset ne compense QUE la latence vidéo. On ne l'applique
        donc que si le média courant a une piste vidéo — les fichiers audio (mp3…)
        étaient déjà parfaitement synchro et ne doivent surtout pas être décalés.
        """
        pos = self.player_ui.player.position()
        off = int(getattr(self.player_ui, 'light_sync_offset_ms', 0) or 0)
        if not off:
            return pos
        try:
            is_video = bool(self.player_ui.player.hasVideo())
        except Exception:
            is_video = False
        if not is_video:
            return pos
        return max(0, pos - off)

    def _do_update_timeline_playback(self):
        """Met a jour DMX selon position timeline"""
        if not hasattr(self, 'timeline_playback_row'):
            return

        # Garde supplementaire: verifier que la timeline correspond bien au media en cours
        if self.timeline_playback_row != getattr(self, 'current_row', -1):
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            self._clear_timeline_leftovers()
            del self.timeline_playback_row
            self.timeline_tracks_data = {}
            return

        # Garde supplementaire: verifier que le mode DMX courant est toujours "Play Lumiere"
        current_dmx_mode = self.get_dmx_mode(getattr(self, 'current_row', -1))
        if current_dmx_mode != "Play Lumiere":
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            self._clear_timeline_leftovers()
            if hasattr(self, 'timeline_playback_row'):
                del self.timeline_playback_row
            self.timeline_tracks_data = {}
            return

        # Source du temps: tempo_elapsed pour TEMPO, player.position pour media
        if self.tempo_running:
            current_time = self.tempo_elapsed
        else:
            current_time = self._media_light_time()

        # Debounce: ignorer uniquement si la position n'a pas change du tout
        if current_time == self.timeline_last_update:
            # Cas image/pause minutee : l'horloge est le TEMPO (timer 100 ms) alors
            # que la timeline tique a 50 ms. Un tick sur deux lit donc la meme valeur
            # de tempo_elapsed : la position "fige" sans que ce soit une pause. Comme
            # le QMediaPlayer reste Stopped pour une image, ne PAS retomber dans le
            # blackout ci-dessous (sinon strobe ON/OFF a ~10 Hz). On attend le tick
            # suivant en conservant l'etat courant des projecteurs.
            if self.tempo_running and not self.tempo_paused:
                return
            # Position figee = pause/stop probable. Si on n'est pas en lecture,
            # eteindre les projecteurs (et l'effet eventuel) — sinon un bloc de
            # couleur simple resterait allume tant qu'on est en pause.
            _player = getattr(self.player_ui, 'player', None)
            _state  = _player.playbackState() if _player else None
            if _state is not None and _state != QMediaPlayer.PlayingState:
                # Noircir UNE SEULE FOIS. Répété à chaque tick (50 ms), ce bloc
                # réécrasait les projecteurs 20 fois par seconde : après un stop,
                # toute reprise en main manuelle (plan de feu 2D, AKAI, pads)
                # était effacée dans la foulée et paraissait sans effet.
                if not getattr(self, '_timeline_pause_blackout', False):
                    self._timeline_pause_blackout = True
                    if getattr(self, '_timeline_effect_name', None) is not None:
                        self._stop_timeline_effect()
                    # Noircir ne suffit pas : un « jeu de lumiere » dont le mode
                    # auto/son est un canal brut ignore le dimmer et continuait
                    # de tourner en pause. On ramene tout le faisceau au repos.
                    self._clear_timeline_leftovers(blackout=True)
            return

        self.timeline_last_update = current_time
        # La position a bougé : on est bien en lecture. Réarmer le blackout de
        # pause, sinon la prochaine pause laisserait les lumières allumées.
        self._timeline_pause_blackout = False

        # Compteur pour les effets
        if not hasattr(self, '_timeline_tick'):
            self._timeline_tick = 0
        self._timeline_tick += 1

        active_clips = {}
        last_clip_end = getattr(self, '_timeline_last_end', 0)

        # Clips non chevauchants par piste : le candidat actif est le dernier dont
        # le start <= current_time → recherche bisect O(log N) au lieu de balayer
        # tous les clips à chaque tick (cf. play_timeline_sequence).
        for track_name, (sclips, starts) in getattr(self, '_timeline_sorted', {}).items():
            j = bisect.bisect_right(starts, current_time) - 1
            if j < 0:
                continue
            clip_data = sclips[j]
            start = clip_data.get('start', 0)
            end = start + clip_data.get('duration', 0)
            if not (start <= current_time <= end):
                continue

            intensity = self.calculate_clip_intensity(clip_data, current_time)
            progress = (current_time - start) / max(1, clip_data.get('duration', 0))

            _color  = QColor(clip_data.get('color', '#000000'))
            _color2 = QColor(clip_data['color2']) if clip_data.get('color2') else None
            # Fondu enchaîné couleur CENTRÉ sur la jointure (parité aperçu
            # éditeur) : morphe couleur + intensité entre les 2 blocs sans passer
            # par le noir. Le bloc actif peut être en tête (jointure gauche, il
            # porte le xfade) ou en queue (jointure droite, le suivant le porte).
            from light_timeline import xfade_resolve, xfade_dict_get
            _prev_c = sclips[j - 1] if j > 0 else None
            _next_c = sclips[j + 1] if (j + 1) < len(sclips) else None
            _xr = xfade_resolve(clip_data, _prev_c, _next_c, current_time, xfade_dict_get)
            if _xr:
                _xc, _xc2, _xi = _xr
                _color = _xc
                if _xc2 is not None:
                    _color2 = _xc2
                intensity = _xi

            entry = {
                'color': _color,
                'color2': _color2,
                'intensity': intensity,
                'effect': clip_data.get('effect', None),
                'effect_speed':         clip_data.get('effect_speed', 50),
                'effect_name':          clip_data.get('effect_name', ''),
                'effect_type':          clip_data.get('effect_type', ''),
                'effect_layers':        clip_data.get('effect_layers', []),
                'effect_target_groups': clip_data.get('effect_target_groups', []),
                'memory_ref':    clip_data.get('memory_ref'),
                'cue_index':     clip_data.get('cue_index'),
                'seq_intensity': intensity,
                # Identité du clip source. `_handle_timeline_effect` s'en sert pour
                # savoir qu'on a CHANGÉ de clip d'effet : deux clips voisins
                # portent souvent le même nom d'effet, les mêmes groupes et la
                # même vitesse tout en ayant des couches différentes (Sinus puis
                # Montée…). Sans elle, la garde « même effet en cours » ne
                # redémarrait pas et le clip précédent débordait sur le suivant.
                '_fx_key': (track_name, start, clip_data.get('duration', 0)),
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
            # Gobo
            if clip_data.get('gobo_dmx') is not None:
                entry['gobo_dmx']      = clip_data['gobo_dmx']
                entry['gobo_rotation'] = clip_data.get('gobo_rotation', 0)

            active_clips[track_name] = entry

        # Auto-stop: si tous les clips sont finis et qu'on depasse la fin du dernier clip
        if not active_clips and current_time > last_clip_end and last_clip_end > 0:
            # Plus aucun clip Position : oublier la visée qu'il imposait AVANT de
            # couper l'effet, sinon `stop_effect` y ramène les lyres et le
            # prochain effet live tournerait autour d'une position périmée.
            self.player_ui._timeline_pos_centers = {}
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            if hasattr(self, 'timeline_playback_row'):
                del self.timeline_playback_row
            self.timeline_tracks_data = {}
            # Eteindre les projecteurs : sans ca, ils restent figes sur la
            # derniere valeur posee par le dernier clip (groupe qui ne s'eteint
            # plus). Le niveau ne suffit pas — les canaux bruts (mode auto/son
            # d'un jeu de lumiere), le strobe, le gobo et la roue survivaient a
            # la fin du morceau et ne s'arretaient qu'au CLEAR.
            self._clear_timeline_leftovers(blackout=True)
            return

        # ── Gérer les pistes Effet (Effet + Effet 2/3/4… → superposition) ──
        # On retire TOUTES les pistes Effet de active_clips et on les fusionne,
        # à parité avec l'aperçu REC Lumière (sinon seul « Effet » jouait en show).
        effet_clips = [active_clips.pop(tn) for tn in list(active_clips)
                       if tn == "Effet" or tn.startswith("Effet ")]
        self._handle_timeline_effect(effet_clips)

        self.apply_timeline_to_dmx(active_clips)

    def _fx_catalog(self):
        """Catalogue d'effets (intégrés + perso), mis en cache.

        Il était rechargé — lecture disque + parse JSON — à CHAQUE image de la
        restitution (25 fps, dans le timer qui alimente le DMX) alors qu'il ne
        sert qu'au changement de clip d'effet. Le cache est invalidé sur la date
        de modification du fichier : un effet édité en cours de show reste pris
        en compte.
        """
        try:
            from effect_editor import (BUILTIN_EFFECTS, _load_custom_effects,
                                       _CUSTOM_EFFECTS_FILE)
            try:
                stamp = _CUSTOM_EFFECTS_FILE.stat().st_mtime_ns
            except OSError:
                stamp = None   # fichier absent : rien à recharger
            if getattr(self, '_fx_catalog_stamp', '?') != stamp:
                self._fx_catalog_stamp = stamp
                self._fx_catalog_cache = BUILTIN_EFFECTS + _load_custom_effects()
            return self._fx_catalog_cache
        except Exception:
            return []

    def _handle_timeline_effect(self, effet_clips):
        """Démarre / maintient / arrête l'effet des pistes Effet de la timeline.

        Fusionne TOUTES les pistes Effet actives (Effet, Effet 2, …) en un seul
        effet combiné → superposition, à parité avec l'aperçu REC Lumière
        (cf. timeline_editor._apply_preview_to_projectors)."""
        main_win = self.player_ui
        if not effet_clips:
            # Aucune piste Effet active → arrêter l'effet timeline s'il tournait
            self._stop_timeline_effect()
            return

        # Fusionner les couches de tous les clips d'effet actifs
        _catalog = self._fx_catalog()
        from light_timeline import scope_layers_to_groups as _scope_layers_to_groups
        merged_layers, merged_names, merged_tg = [], [], []
        merged_type = ''
        has_all_groups = False
        merged_no_color = False
        for clip in effet_clips:
            eff_name   = clip.get('effect_name', '')
            eff_layers = list(clip.get('effect_layers', []))
            eff_type   = clip.get('effect_type', '')
            eff_tg     = list(clip.get('effect_target_groups', []))
            # Résoudre depuis le catalogue : couches manquantes + flag no_color
            _cat = next((_e for _e in _catalog if _e.get('name') == eff_name), None)
            if _cat:
                if not eff_layers:
                    eff_layers = [dict(l) for l in _cat.get('layers', [])]
                    eff_type   = _cat.get('type', '')
                if _cat.get('no_color'):
                    merged_no_color = True
            # Cloisonner les couches par groupe : chaque couche de CE clip ne doit
            # s'appliquer qu'aux groupes du clip. Sinon, quand 2 effets se
            # superposent (couleur sur A,B + lyre sur D), la fusion applique les
            # couches "Tous" à toute l'union A,B,D → la lyre (D) se fait flasher
            # par l'effet couleur des A,B. On tague donc chaque couche non déjà
            # restreinte avec les groupes cible du clip.
            eff_layers = _scope_layers_to_groups(eff_layers, eff_tg)
            merged_layers.extend(eff_layers)
            if eff_name:
                merged_names.append(eff_name)
            if not merged_type:
                merged_type = eff_type
            if not eff_tg:
                has_all_groups = True
            else:
                for g in eff_tg:
                    if g not in merged_tg:
                        merged_tg.append(g)

        combined_name  = " + ".join(merged_names) if merged_names else ''
        if not combined_name or not merged_layers:
            self._stop_timeline_effect()
            return

        target_groups  = [] if has_all_groups else merged_tg
        speed_override = effet_clips[0].get('effect_speed', 50)

        # Déjà le bon effet combiné en cours → ne pas réinitialiser.
        # L'identité de l'effet, c'est le JEU DE CLIPS actifs, pas (nom, groupes,
        # vitesse) : dans un show réel, les clips voisins d'une même piste portent
        # presque toujours le même `effect_name` (« Strobe Rouge »…), les mêmes
        # `effect_target_groups` et la même `effect_speed`, alors que leurs COUCHES
        # diffèrent (forme Sinus → Montée, vitesse de couche 48 → 65, groupe B,E →
        # B,E + C,D). La garde concluait « c'est le même effet » et gardait l'ancien
        # en vie : l'effet précédent débordait sur le suivant (« le sinus continue à
        # la place de la montée », « le triangle empiète sur l'aléatoire ») et les
        # groupes ajoutés par le nouveau clip restaient sans effet, en couleur fixe.
        # Rien de tout ça dans l'aperçu REC, qui compare l'IDENTITÉ des clips
        # (cf. timeline_editor `new_eff_clips != self._eff_clips_active`) : d'où le
        # « pas le même rendu qu'à l'enregistrement ». On compare donc pareil.
        clips_key  = tuple(sorted(c.get('_fx_key') or () for c in effet_clips))
        same_clips = getattr(self, '_timeline_effect_clips', None) == clips_key
        same_group = getattr(self, '_timeline_effect_group', None) == tuple(target_groups)
        same_speed = getattr(self, '_timeline_effect_speed', None) == speed_override
        if (getattr(self, '_timeline_effect_name', None) == combined_name
                and same_clips and same_group and same_speed):
            return

        cfg = {
            'name':            combined_name,
            'type':            merged_type,
            'layers':          merged_layers,
            'play_mode':       'loop',
            'target_groups':   target_groups,
            'speed_override':  speed_override,
            'no_color':        merged_no_color,
        }

        # Démarrer l'effet (initialiser l'état sans démarrer le effect_timer —
        # la timeline appelle update_effect() elle-même à chaque tick)
        self._timeline_effect_name  = combined_name
        self._timeline_effect_clips = clips_key
        self._timeline_effect_group = tuple(target_groups)
        self._timeline_effect_speed = speed_override
        main_win.active_effect        = combined_name
        main_win.active_effect_config = cfg
        # Initialiser les compteurs d'état de l'effet
        main_win.effect_state      = 0
        main_win.effect_brightness = 0
        main_win.effect_direction  = 1
        main_win.effect_hue        = 0
        # Même capture que le live AKAI : c'est stop_effect() qui la restitue,
        # et lui attend le tuple complet (roue de couleurs, gobo, zoom…).
        main_win._snapshot_effect_state()
        import time as _time
        main_win.effect_t0 = _time.monotonic()
        # Horloge de phase de l'effet, remise a zero comme en live (sans elle,
        # le clip repartirait a la position laissee par l'effet precedent).
        main_win._effect_clock    = 0.0
        main_win._effect_clock_ts = None

    def _clear_timeline_leftovers(self, blackout=False):
        """Nettoie les canaux laissés posés par la timeline qu'on vient d'arrêter.

        `_stop_timeline_effect()` ne coupe que l'EFFET. Tout ce que les clips
        écrivaient directement sur les projecteurs (canaux bruts, strobe, gobo,
        roue, prisme, UV/ambre…) restait, lui, gravé sur les `Projector` — et le
        moteur DMX continuait de l'émettre en boucle. D'où « les modes restent
        actifs sans fin, faut faire clear partout pour stopper ».

        Pendant la lecture, ce nettoyage est fait à chaque image par
        `apply_timeline_to_dmx` ; il ne manquait qu'au moment de l'arrêt.
        """
        main_win = self.player_ui
        projs = getattr(main_win, 'projectors', None)
        if not projs:
            return
        try:
            from light_timeline import reset_beam_channels
            reset_beam_channels(projs, blackout=blackout)
            if getattr(main_win, 'artnet', None):
                main_win.artnet.update_from_projectors(projs)
        except Exception as e:
            print(f"[TIMELINE] nettoyage de fin impossible : {e}")

    def _stop_timeline_effect(self):
        """Arrête l'effet lancé par la timeline (si c'est bien lui qui tourne)."""
        main_win = self.player_ui
        # Couper le suivi clip→effet (ids périmés une fois la timeline arrêtée)
        main_win._fx_clip_ids = None
        timeline_name = getattr(self, '_timeline_effect_name', None)
        if timeline_name is None:
            return
        self._timeline_effect_name  = None
        self._timeline_effect_clips = None
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
        start = clip_data.get('start', 0)
        duration = clip_data.get('duration', 0)
        base_intensity = clip_data.get('intensity', 100)

        # Clip dégénéré (durée nulle/négative) : pas de fade possible, on renvoie
        # l'intensité pleine. Évite un ZeroDivisionError qui, levé dans le timer
        # de restitution (thread Qt), ferait crasher tout MyStrow en plein show.
        if duration <= 0:
            return int(base_intensity)

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

        # Projecteurs sous un clip actif ce frame : l'effet de la piste Effet
        # (appliqué plus bas via update_effect) suivra leur couleur + leur fade.
        main_win._fx_clip_ids = set()

        # Remise à zéro complète du rig AVANT de réappliquer les clips actifs :
        # la timeline est un writer ABSOLU, chaque frame repart d'une page
        # blanche. C'est ce qui fait qu'un bloc « s'éteint tout seul » à sa fin.
        #
        # La liste était recopiée à la main ici (level/couleur, strobe, roue,
        # canaux bruts, UV/blanc/ambre/orange) et il y MANQUAIT tout le reste du
        # faisceau : gobo, gobo2, rotation de gobo, zoom, focus, prisme, rotation
        # de prisme, shutter, effects/speed/mode_value. Ces canaux-là n'étaient
        # jamais remis au repos en cours de lecture : une mémoire qui posait un
        # gobo ou un prisme le laissait collé APRÈS la fin de son bloc, jusqu'au
        # prochain CLEAR. Symptôme client : « problème de fin de REC, il faut
        # ajouter un bloc noir pour que ça s'arrête ».
        #
        # `reset_beam_channels()` fait déjà exactement ce nettoyage (elle servait
        # uniquement à l'ARRÊT de la timeline) : on l'appelle ici pour n'avoir
        # qu'UNE seule définition du repos, partagée avec l'aperçu de l'éditeur.
        # Le pan/tilt en est volontairement exclu — recentrer les lyres à chaque
        # frame les figerait au milieu de la course.
        #
        # Sûr vis-à-vis des mémoires : `apply_seq_memories_htp` REPOSE ces mêmes
        # canaux à chaque frame depuis le snapshot tant que le bloc est actif.
        from light_timeline import reset_beam_channels
        reset_beam_channels(self.player_ui.projectors, blackout=True)

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

                main_win._fx_clip_ids.add(id(proj))
                # Bloc « canal dédié » (Black Light / Ambre) : pilote la LED
                # dédiée seule, RVB à zéro. Sur une fixture qui n'a pas ce canal,
                # retombe sur le rendu RVB. Parité obligatoire avec l'aperçu REC.
                if apply_special_block(proj, color, intensity):
                    continue

                proj.level = intensity
                proj.base_color = color
                proj.color = QColor(
                    int(color.red() * intensity / 100),
                    int(color.green() * intensity / 100),
                    int(color.blue() * intensity / 100)
                )
                # Lyres ColorWheel : positionner la roue sur la couleur du clip
                # (no-op pour les lyres RGB). Sans ça, la couleur ne sort pas en
                # restitution alors qu'elle sort en REC Lumière. Aligné sur preview.
                if hasattr(main_win, '_update_color_wheel'):
                    main_win._update_color_wheel(proj, color)

        # --- Appliquer la piste Gobo ---
        # Parité obligatoire avec l'aperçu REC Lumière : la roue de couleurs
        # avait déjà été oubliée ici et ne sortait qu'en REC, pas en show.
        gobo_clip = active_clips.get('Gobo')
        _gobo_locked_idxs = set()   # gobos pilotés par la piste Gobo
        if gobo_clip and gobo_clip.get('gobo_dmx') is not None:
            _g_val = max(0, min(255, int(gobo_clip['gobo_dmx'])))
            _g_rot = max(0, min(255, int(gobo_clip.get('gobo_rotation', 0) or 0)))
            for _gi, proj in enumerate(main_win.projectors):
                if 'Gobo1' in (getattr(proj, 'dmx_profile', None) or []):
                    proj.gobo = _g_val
                    proj.gobo_rotation = _g_rot
                    # Verrou explicite, même principe que la piste Position :
                    # les mémoires jouées juste après ne réécrivent pas ce gobo.
                    _gobo_locked_idxs.add(_gi)

        # --- Appliquer Pan/Tilt pour les Lyres ---
        # La piste position s'appelle "Position" dans la timeline; fallback sur "Lyres" pour anciens .tui
        lyres_clip = active_clips.get('Position') or active_clips.get('Lyres')
        _pos_locked_idxs = set()   # lyres dont le pan/tilt est piloté par la piste Position
        # Remis à vide à CHAQUE image : hors clip Position, le moteur d'effets
        # doit retrouver son comportement d'origine (centre = état capturé).
        main_win._timeline_pos_centers = {}
        if lyres_clip:
            # Recuperer les indices du groupe "lyres" / "Lyres"
            lyres_indices = track_to_indices.get('Lyres', [])
            if not lyres_indices and hasattr(main_win, 'projectors'):
                lyres_indices = [
                    i for i, p in enumerate(main_win.projectors)
                    if getattr(p, 'fixture_type', '') == 'Moving Head'
                ]
            # Ces lyres sont sous contrôle Position → les séquences ne doivent pas
            # écraser leur pan/tilt (la piste Position prime).
            _pos_locked_idxs = set(lyres_indices)

            # Centre imposé au moteur d'effets. Parité obligatoire avec l'aperçu
            # REC Lumière : sans ça une couche Pan/Tilt sans colonne POSITION
            # recentre sur l'état capturé au démarrage de l'effet, et les lyres
            # dérivent de la position posée par le clip.
            try:
                from core import position_preset_values, find_position_preset
                _pr = find_position_preset(
                    getattr(main_win, 'position_presets', []) or [],
                    lyres_clip.get('position_preset_idx'),
                    lyres_clip.get('position_preset_name', ''))
                _lyres_obj = [main_win.projectors[i] for i in lyres_indices
                              if i < len(main_win.projectors)]
                main_win._timeline_pos_centers = (
                    position_preset_values(_pr, _lyres_obj) if _pr else {})
            except Exception as _e:
                print(f"[SHOW] centre de position indisponible : {_e}")
                main_win._timeline_pos_centers = {}

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

        # ── Appliquer les séquences mémoire (HTP) par-dessus les groupes ────
        # Toutes les pistes Séquence actives sont fusionnées : sur un projecteur
        # partagé, la mémoire la plus lumineuse gagne ; les mémoires disjointes
        # s'empilent. Même fonction que l'aperçu éditeur → parité garantie.
        from light_timeline import apply_seq_memories_htp
        _seq_entries = [
            {'memory_ref': c.get('memory_ref'),
             'cue_index': c.get('cue_index'),
             'brightness': c.get('seq_intensity', 100) / 100.0}
            for c in active_clips.values()
            if isinstance(c, dict) and c.get('memory_ref')
        ]
        apply_seq_memories_htp(_seq_entries, getattr(main_win, 'memories', None),
                               main_win.projectors, main_win,
                               lock_pantilt_idxs=_pos_locked_idxs,
                               lock_gobo_idxs=_gobo_locked_idxs)

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
        wf = main_window.recording_waveform
        wf.clear()

        # Construire les blocs sans déclencher un repaint par keyframe (sur un REC
        # de 40 min ≈ 4800 keyframes, ça évite une avalanche de repaints au lancement).
        wf.setUpdatesEnabled(False)
        try:
            for kf in keyframes:
                pad_color = None
                if kf.get("active_pad"):
                    pad_color = QColor(kf["active_pad"]["color"])
                wf.add_keyframe(kf["time"], kf["faders"], pad_color)
        finally:
            wf.setUpdatesEnabled(True)
        wf.duration = sequence.get("duration", 0)
        wf.show()
        wf.update()

        # Cache des temps de keyframes (triés) pour une recherche bisect O(log N)
        # par tick au lieu de rescanner depuis 0 (coût qui grandit avec l'avancement).
        self._kf_times = [kf["time"] for kf in keyframes]

        self.playback_row = row
        self.playback_index = 0

        if not self.playback_timer:
            self.playback_timer = QTimer()
            self.playback_timer.timeout.connect(self.update_sequence_playback)

        self.playback_timer.start(50)

    def update_sequence_playback(self):
        """Callback QTimer (50 ms) — protégé : un keyframe issu d'un ancien .tui
        peut manquer une clé (faders/active_pad/active_effects) → KeyError qui,
        levé dans ce slot, crasherait tout MyStrow (PySide6 abort). On logge."""
        try:
            self._do_update_sequence_playback()
        except Exception as e:
            self._log_tick_error('keyframes', e)

    def _do_update_sequence_playback(self):
        """Met a jour la lecture de la sequence"""
        if self.playback_row < 0:
            return

        current_time = self._media_light_time()

        sequence = self.sequences.get(self.playback_row)
        if not sequence:
            return

        keyframes = sequence["keyframes"]

        # Recherche bisect O(log N) : keyframes triés par temps → le candidat actif
        # est le dernier dont time <= current_time. Évite de rescanner depuis 0 à
        # chaque tick (le coût grandissait avec l'avancement → décalage progressif).
        times = getattr(self, '_kf_times', None)
        if times is None or len(times) != len(keyframes):
            times = [kf["time"] for kf in keyframes]
            self._kf_times = times

        i = bisect.bisect_right(times, current_time) - 1
        if i >= 0:
            kf = keyframes[i]
            if kf["time"] <= current_time < (kf["time"] + 500) and i != self.playback_index:
                self.apply_keyframe(kf)
                self.playback_index = i

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

    def is_row_loop(self, row) -> bool:
        """True si le média de cette ligne est marqué « jouer en boucle »."""
        item = self.table.item(row, 1)
        return bool(item and item.data(self.LOOP_ROLE))

    def set_row_loop(self, row, enabled: bool):
        """Active/désactive la lecture en boucle d'un média + met à jour le visuel."""
        item = self.table.item(row, 1)
        if not item:
            return
        item.setData(self.LOOP_ROLE, True if enabled else None)
        # Nettoyer un éventuel ancien préfixe emoji (versions précédentes)
        txt = item.text()
        if txt.startswith(self._LOOP_PREFIX):
            item.setText(txt[len(self._LOOP_PREFIX):])
        self._refresh_row_marks(row)
        self.is_dirty = True

    def toggle_row_loop(self, row):
        """Bascule l'état boucle depuis le menu contextuel."""
        self.set_row_loop(row, not self.is_row_loop(row))

    # ── Marqueurs visuels de la ligne (boucle + fondus) ───────────────────────
    # Boucle et fondus se signalent sur la MÊME case — l'item titre n'a qu'un
    # emplacement d'icône et une infobulle. D'où ce point unique : quand chacun
    # posait la sienne, activer la boucle effaçait le marqueur de fondu.

    _FADE_COLOR = "#ffb300"     # ambre : ne se confond pas avec le cyan boucle

    # Canevas à DEUX cases fixes : fondu à gauche, boucle à droite. Toutes les
    # icônes de la colonne ont donc le même format, donc la même réduction — et
    # la boucle reste à la même abscisse d'une ligne à l'autre. Une image dont
    # la largeur suivrait le nombre de symboles serait écrasée par Qt, qui la
    # met à l'échelle de `iconSize` en gardant ses proportions : trois symboles
    # dans une case prévue pour un carré, et il ne reste qu'un trait.
    _MARK_SLOT = 32                       # rendu 2× pour rester net une fois réduit
    MARK_ICON_SIZE = (32, 16)             # taille d'affichage dans la table

    def _row_marks_icon(self, loop: bool, fade_in: int, fade_out: int):
        """Icône d'état de la ligne : rampe(s) de fondu + symbole de boucle."""
        from PySide6.QtGui import QIcon, QPixmap, QPainter
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QByteArray, QRectF
        cle = (loop, bool(fade_in), bool(fade_out))
        cache = getattr(self, '_row_icon_cache', None)
        if cache is None:
            cache = self._row_icon_cache = {}
        if cle in cache:
            return cache[cle]
        if cle == (False, False, False):
            cache[cle] = QIcon()
            return cache[cle]

        f = self._FADE_COLOR
        if fade_in and fade_out:
            # Un seul symbole pour les deux : la montée puis la descente,
            # exactement la forme du volume sur la durée du morceau.
            fondu = (f'<path fill="{f}" d="M2 21 L11 6 L11 21 Z"/>'
                     f'<path fill="{f}" d="M22 21 L13 6 L13 21 Z"/>')
        elif fade_in:
            fondu = f'<path fill="{f}" d="M3 21 L21 5 L21 21 Z"/>'
        elif fade_out:
            fondu = f'<path fill="{f}" d="M3 5 L21 21 L3 21 Z"/>'
        else:
            fondu = ""
        boucle = ('<path fill="#00d4ff" d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3'
                  'l-4 4 4 4v-3h12v-6h-2v4z"/>') if loop else ""

        s = self._MARK_SLOT
        pix = QPixmap(s * 2, s)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        for i, g in enumerate((fondu, boucle)):
            if not g:
                continue
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{g}</svg>'
            QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(
                p, QRectF(s * i, 0, s, s))
        p.end()
        cache[cle] = QIcon(pix)
        return cache[cle]

    def _fade_short(self, fade_in: int, fade_out: int) -> str:
        """« ↗ 2 s », « ↘ 3 s », « ↗ 2 s ↘ 3 s » — forme compacte pour un menu.

        Seul ce qui est posé apparaît : « 2 s / — » forçait à décoder un tiret
        qui ne veut rien dire d'autre que « rien ici ».
        """
        bouts = []
        if fade_in:
            bouts.append(f"↗ {self._fmt_fade(fade_in)}")
        if fade_out:
            bouts.append(f"↘ {self._fmt_fade(fade_out)}")
        return "  ".join(bouts)

    def _fade_summary(self, fade_in: int, fade_out: int) -> str:
        """« Fondu d'entrée 2 s » · « … · de sortie 4 s ». Vide si aucun fondu.

        Seuls les fondus RÉELLEMENT posés sont cités : « de sortie — » disait au
        lecteur d'aller vérifier quelque chose qui n'existe pas.
        """
        bouts = []
        if fade_in:
            bouts.append(f"{tr('seq_fade_in')} {self._fmt_fade(fade_in)}")
        if fade_out:
            bouts.append(f"{tr('seq_fade_out')} {self._fmt_fade(fade_out)}")
        return "  ·  ".join(bouts)

    def _refresh_row_marks(self, row):
        """Repose icône, infobulle et teinte d'une ligne d'après son état."""
        item = self.table.item(row, 1)
        if not item:
            return
        loop = bool(item.data(self.LOOP_ROLE))
        fi, fo = self.get_row_fades(row)
        item.setIcon(self._row_marks_icon(loop, fi, fo))
        # Teinte cyan réservée à la boucle : c'est elle qui change ce que fait
        # la playlist (elle ne passe plus au suivant). Un fondu, lui, ne se
        # signale que par son icône ambre — sinon toute la liste serait colorée.
        item.setForeground(QBrush(QColor("#00d4ff") if loop else QColor("#e0e0e0")))
        bulles = []
        if loop:
            bulles.append(tr("seq_menu_loop"))
        resume = self._fade_summary(fi, fo)
        if resume:
            bulles.append(resume)
        item.setToolTip("\n".join(bulles))

    # ── Fondus audio de ligne ─────────────────────────────────────────────────

    def _fade_out_before(self, row) -> bool:
        """Descend le morceau en cours avant de passer à `row`. True = différé.

        Point d'interception UNIQUE, en tête de `play_row` : tous les chemins qui
        changent de piste y passent (fin de morceau, bouton Suivant, double-clic
        dans la liste, pad de l'APC). En brancher un par un en aurait laissé.

        Trois cas rendent la main tout de suite :
          - rien ne joue, ou on relance la ligne courante (une boucle) ;
          - la ligne quittée n'a pas de fondu de sortie ;
          - un fondu est DÉJÀ en cours — c'est le deuxième appel, celui qu'on a
            soi-même programmé, ou l'utilisateur qui reclique pour couper court.
        """
        pu = self.player_ui
        if getattr(pu, '_audio_fade_cb', None) is not None:
            # Fondu en cours : deuxième sollicitation = coupure immédiate.
            pu._audio_fade_reset()
            return False
        cur = self.current_row
        if cur < 0 or cur == row:
            return False
        if pu.player.playbackState() != QMediaPlayer.PlayingState:
            return False
        _, fade_out = self.get_row_fades(cur)
        if fade_out <= 0:
            return False
        # Ne pas rejouer le fondu de queue : le morceau est déjà descendu tout
        # seul en approchant de sa fin, repartir de 0 ne ferait qu'attendre.
        if getattr(pu, '_audio_fade_armed', False):
            return False
        pu.start_audio_fade(0.0, fade_out, lambda: self.play_row(row))
        # Armé APRÈS l'appel (start_ le remet à zéro) : au retour du callback,
        # play_row repasse ici et ce drapeau est ce qui l'empêche de relancer un
        # fondu — sinon la piste ne partirait jamais.
        pu._audio_fade_armed = True
        return True

    def get_row_fades(self, row) -> tuple:
        """(fondu d'entrée, fondu de sortie) en millisecondes. (0, 0) si aucun."""
        item = self.table.item(row, 1)
        if not item:
            return (0, 0)
        return (int(item.data(self.FADE_IN_ROLE) or 0),
                int(item.data(self.FADE_OUT_ROLE) or 0))

    def set_row_fades(self, row, fade_in_ms: int, fade_out_ms: int):
        """Pose les fondus d'une ligne et met à jour son infobulle."""
        item = self.table.item(row, 1)
        if not item:
            return
        fi = max(0, int(fade_in_ms or 0))
        fo = max(0, int(fade_out_ms or 0))
        # None et non 0 : un rôle absent ne pèse rien dans le fichier de show,
        # et `get_row_fades` lit les deux formes de la même façon.
        item.setData(self.FADE_IN_ROLE, fi or None)
        item.setData(self.FADE_OUT_ROLE, fo or None)
        self._refresh_row_marks(row)
        self.is_dirty = True

    @staticmethod
    def _fmt_fade(ms: int) -> str:
        """0 → « — » ; 2500 → « 2,5 s » ; 4000 → « 4 s ».

        Séparateur décimal selon la langue : l'anglais est le seul des cinq à
        écrire « 4.5 s ». Un « 4,5 s » anglais se lit comme deux nombres.
        """
        if not ms:
            return "—"
        from i18n import get_language
        txt = f"{ms / 1000.0:.1f}".rstrip("0").rstrip(".")
        if get_language() != "en":
            txt = txt.replace(".", ",")
        return f"{txt} s"

    def fade_target_rows(self, row) -> list:
        """Lignes visées par un réglage de fondu : la sélection, ou la ligne visée.

        Un clic droit HORS sélection ne doit pas retomber sur vingt lignes
        sélectionnées ailleurs — dans ce cas la ligne cliquée gagne. Les lignes
        sans média (PAUSE, TEMPO) sont écartées : elles n'ont pas de son.
        """
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if row not in rows:
            rows = [row]
        gardees = []
        for r in rows:
            it = self.table.item(r, 1)
            p = it.data(Qt.UserRole) if it else None
            if p and media_icon(p) in ("audio", "video"):
                gardees.append(r)
        return gardees or ([row] if row >= 0 else [])

    def clear_row_fades(self, row):
        """Retire les fondus de la sélection (ou de la ligne visée)."""
        for r in self.fade_target_rows(row):
            self.set_row_fades(r, 0, 0)

    def edit_row_fades(self, row):
        """Boîte de réglage des fondus — curseurs identiques à la vue « Curseurs »."""
        # Style de curseur emprunté au menu du plan de feu : c'est le même geste
        # (clic = saut à la valeur, molette par crans), autant que ce soit aussi
        # le même objet. Import local : `sequencer` n'a pas besoin du plan de feu
        # pour tout le reste, et le charger au niveau module fixerait un ordre
        # d'import entre deux gros modules pour un seul dialogue.
        from plan_de_feu import _CurseurCanal, _feuille_curseur

        rows = self.fade_target_rows(row)
        fi, fo = self.get_row_fades(row)

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("seq_fade_title"))
        dlg.setMinimumWidth(430)
        dlg.setStyleSheet(
            "QDialog{background:#0d0d0d;}"
            "QLabel{color:#e0e0e0;background:transparent;}"
            "QPushButton{background:#1a1a1a;color:#ccc;border:1px solid #2a2a2a;"
            "border-radius:5px;padding:7px 16px;font-size:12px;}"
            "QPushButton:hover{background:#242424;border-color:#3a3a3a;color:#fff;}"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(14)

        cible = QLabel(tr("seq_fade_rows", n=len(rows)) if len(rows) > 1
                       else Path(self.table.item(row, 1).data(Qt.UserRole) or "").name)
        cible.setStyleSheet("color:#00d4ff;font-size:12px;font-weight:bold;"
                            "background:transparent;")
        lay.addWidget(cible)

        curseurs = {}

        def ligne(cle, libelle, valeur_ms, teinte):
            """Étiquette + curseur + valeur, alignées comme dans le menu 2D."""
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)

            lbl = QLabel(libelle)
            lbl.setFixedWidth(120)
            lbl.setStyleSheet("color:#999;font-size:12px;font-weight:bold;"
                              "background:transparent;")

            sli = _CurseurCanal(Qt.Horizontal)
            # Unité = le DIXIÈME de seconde : la molette de _CurseurCanal avance
            # de 5 crans, soit un demi-pas de seconde — le pas de réglage d'un
            # fondu en régie. Ctrl donne le dixième, Maj deux secondes et demie.
            sli.setRange(0, 600)
            sli.setValue(int(round(valeur_ms / 100.0)))
            sli.setStyleSheet(_feuille_curseur(True, teinte))
            sli.setFixedHeight(22)
            sli.setCursor(Qt.PointingHandCursor)

            val = QLabel()
            val.setFixedWidth(58)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setStyleSheet(f"color:{teinte};font-size:12px;font-weight:bold;"
                              "background:transparent;")

            def montrer(v):
                val.setText(self._fmt_fade(v * 100))
            sli.valueChanged.connect(montrer)
            montrer(sli.value())

            h.addWidget(lbl)
            h.addWidget(sli, 1)
            h.addWidget(val)
            curseurs[cle] = sli
            lay.addWidget(w)

        ligne("in", tr("seq_fade_in"), fi, "#00d4ff")
        ligne("out", tr("seq_fade_out"), fo, self._FADE_COLOR)

        hint = QLabel(tr("seq_fade_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;font-size:11px;background:transparent;")
        lay.addWidget(hint)

        barre = QHBoxLayout()
        btn_clear = QPushButton(tr("seq_fade_clear"))
        btn_clear.setStyleSheet(
            "QPushButton{background:#2a0000;color:#cc4444;border:1px solid #3a1111;"
            "border-radius:5px;padding:7px 16px;font-size:12px;}"
            "QPushButton:hover{background:#440000;color:#ff6666;}")
        # Remet les curseurs à zéro PUIS valide : « Retirer le fondu » est une
        # décision, pas un réglage. Laisser la boîte ouverte obligeait à cliquer
        # OK derrière, et un clic sur Annuler à ce moment-là annulait le retrait
        # qu'on venait de demander — exactement l'inverse de l'intention.
        def _retirer():
            for c in curseurs.values():
                c.setValue(0)
            dlg.accept()
        btn_clear.clicked.connect(_retirer)
        barre.addWidget(btn_clear)
        barre.addStretch()

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        # Libellés posés à la main : les traductions natives de Qt ne sont pas
        # chargées ici, un « Cancel » anglais s'affichait dans une boîte française.
        btns.button(QDialogButtonBox.Cancel).setText(tr("btn_cancel"))
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        barre.addWidget(btns)
        lay.addLayout(barre)

        if dlg.exec() != QDialog.Accepted:
            return
        for r in rows:
            self.set_row_fades(r, curseurs["in"].value() * 100,
                               curseurs["out"].value() * 100)

    def show_media_context_menu(self, pos):
        """Menu contextuel sur media — sections MODE DMX / LUMIÈRE / MÉDIA / LIGNE."""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        menu = QMenu(self)
        menu.setStyleSheet(_SEQ_MENU_SS)

        title_item = self.table.item(row, 1)
        path = title_item.data(Qt.UserRole) if title_item else None
        media_type = media_icon(path) if path else None

        # ⚠️ Ne JAMAIS préfixer une entrée d'un emoji ici : les libellés de
        # `i18n.py` en portent déjà un (🔊 Volume, 🔁 Jouer en boucle, 🗑
        # Supprimer…). En rajouter un affichait deux pictogrammes côte à côte,
        # souvent les deux mêmes. L'emoji appartient à la traduction, pas au menu.

        # ── Média ────────────────────────────────────────────────────────────
        entrees_media = []
        if media_type in ("audio", "video"):
            entrees_media.append((tr("seq_menu_volume"),
                                  lambda: self.edit_media_volume(row)))
        if media_type == "image":
            entrees_media.append((tr("seq_menu_set_duration"),
                                  lambda: self.edit_image_duration(row)))
        if media_type in ("audio", "video"):
            # Valeurs en clair dans le libellé : le seul autre repère est
            # l'infobulle de la ligne, qu'il faut survoler pour voir.
            _fi, _fo = self.get_row_fades(row)
            _cibles = self.fade_target_rows(row)
            _suffixe = f"  ({len(_cibles)})" if len(_cibles) > 1 else ""
            entrees_media.append((
                (tr("seq_menu_fade_set", v=self._fade_short(_fi, _fo))
                 if (_fi or _fo) else tr("seq_menu_fade")) + _suffixe,
                lambda: self.edit_row_fades(row)))
            # Retrait direct, sans passer par la boîte : c'est le geste qu'on
            # fait le plus souvent après coup, et sur toute une sélection.
            if any(any(self.get_row_fades(r)) for r in _cibles):
                entrees_media.append((tr("seq_menu_fade_off") + _suffixe,
                                      lambda: self.clear_row_fades(row)))
        if media_type in ("audio", "video", "image"):
            loop_label = tr("seq_menu_loop_off") if self.is_row_loop(row) else tr("seq_menu_loop")
            entrees_media.append((loop_label, lambda: self.toggle_row_loop(row)))
        if path and media_type in ("audio", "video", "image"):
            # NB : triggered émet un bool `checked` → on l'absorbe pour ne pas
            # écraser p (sinon _reveal_in_explorer reçoit False au lieu du chemin).
            entrees_media.append((tr("seq_locate_file_m"),
                                  lambda checked=False, p=path: self._reveal_in_explorer(p)))
        if entrees_media:
            menu.addAction("MÉDIA").setEnabled(False)
            for libelle, slot in entrees_media:
                menu.addAction(libelle).triggered.connect(slot)
            menu.addSeparator()

        # ── Lumière ──────────────────────────────────────────────────────────
        menu.addAction("LUMIÈRE").setEnabled(False)
        rec_action = menu.addAction(tr("seq_menu_rec_light"))
        rec_action.triggered.connect(lambda: self.open_light_editor_for_row(row))

        # ── Mode DMX ─────────────────────────────────────────────────────────
        menu.addSeparator()
        mode_actions = self._add_dmx_mode_section(menu, row)

        # ── Action ───────────────────────────────────────────────────────────
        menu.addSeparator()
        menu.addAction("ACTION").setEnabled(False)
        duplicate_action = menu.addAction(tr("seq_duplicate_with_rec"))
        duplicate_action.triggered.connect(lambda: self.duplicate_media_row(row))
        delete_action = menu.addAction(tr("seq_menu_delete"))
        delete_action.triggered.connect(lambda: self.delete_media_row(row))

        choisie = menu.exec(self.table.viewport().mapToGlobal(pos))
        # Les modes DMX passent par `data()`, pas par un `triggered` : le mode
        # courant est coché, donc le re-cliquer ne doit rien déclencher.
        if choisie in mode_actions:
            self._handle_dmx_mode_action(choisie, row)

    def _reveal_in_explorer(self, path):
        """Ouvre l'explorateur (Windows/macOS/Linux) sur l'emplacement du média.
        Robuste : gère QUrl / URL file:// / chemin brut, ouvre le dossier en secours,
        et logge le chemin exact si introuvable (diagnostic)."""
        import sys, os, subprocess
        from PySide6.QtCore import QUrl
        raw = path
        if isinstance(path, QUrl):
            path = path.toLocalFile()
        elif isinstance(path, str) and path.strip().lower().startswith("file:"):
            path = QUrl(path.strip()).toLocalFile()
        path = os.path.normpath(str(path or "").strip().strip('"'))

        is_file = bool(path) and os.path.isfile(path)
        folder  = os.path.dirname(path) if path else ""
        has_dir = bool(folder) and os.path.isdir(folder)

        print(f"[localiser] brut={raw!r} normalise={path!r} is_file={is_file} has_dir={has_dir}")

        if not is_file and not has_dir:
            QMessageBox.warning(self, tr("seq_file_not_found"),
                                "Emplacement introuvable :\n" + str(path))
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", path] if is_file else ["explorer", folder])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path] if is_file else ["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            print(f"[localiser] erreur ouverture explorateur : {e}")

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
            # Chemin de suppression unifié (même réindexation que le bouton
            # corbeille) → plus aucun risque de double décalage / perte REC Lumière.
            self._delete_rows([row])

    def _apply_row_dmx(self, row, mode):
        """(Re)crée le widget DMX de `row` et applique `mode`. Réinjecte les modes
        dynamiques (Play Lumiere / Programme) absents du combo par défaut, et
        réaffiche l'indicateur de couleur IA si la ligne en a une. Sert à poser le
        mode d'une ligne dupliquée ET à recâbler les lignes décalées (leurs closures
        capturent l'ancien index — sinon un changement de mode viserait la mauvaise
        ligne)."""
        self.table.setCellWidget(row, 4, self._create_dmx_cell_widget(row))
        combo = self._get_dmx_combo(row)
        if combo and mode:
            if combo.findText(mode) == -1:
                combo.addItem(mode)
            combo.blockSignals(True)
            combo.setCurrentText(mode)
            combo.blockSignals(False)
            if mode == "IA Lumiere":
                self._apply_ia_style(combo)
            elif mode == "Play Lumiere":
                self._apply_play_lumiere_style(combo)
            else:
                self._refresh_dmx_btn(combo)
        if row in self.ia_colors:
            self._update_color_indicator(row, self.ia_colors[row])

    def duplicate_media_row(self, row):
        """Duplique une ligne (média ou pause) juste en dessous, en copiant aussi son
        REC Lumière (sequences), sa couleur/analyse IA et sa durée d'image si présents."""
        import copy
        if row < 0 or row >= self.table.rowCount():
            return

        was_loop = self.is_row_loop(row)
        src_mode = self.get_dmx_mode(row)
        has_dmx  = self.table.cellWidget(row, 4) is not None
        dst      = row + 1

        # Modes des lignes qui vont être décalées (pour recâbler leurs widgets).
        shifted_modes = {r: self.get_dmx_mode(r)
                         for r in range(dst, self.table.rowCount())
                         if self.table.cellWidget(r, 4) is not None}

        # Insérer + décaler toutes les données par-ligne (>= dst). La source
        # (row < dst) reste intacte.
        self.table.insertRow(dst)
        self._reindex_sequences_insert(dst)

        # Cellules 0..3 : icône, titre (+chemin), durée, volume.
        for col in (0, 1, 2, 3):
            src = self.table.item(row, col)
            if src is None:
                continue
            new = QTableWidgetItem(src.text())
            new.setData(Qt.UserRole, src.data(Qt.UserRole))
            new.setTextAlignment(src.textAlignment())
            self.table.setItem(dst, col, new)

        # Données par-ligne (deep copy pour ne pas partager les objets mutables).
        if row in self.sequences:
            self.sequences[dst] = copy.deepcopy(self.sequences[row])
        if row in self.ia_colors:
            self.ia_colors[dst] = self.ia_colors[row]
        if row in self.ia_settings:
            # `copy()` et non deepcopy : le prereglage doit etre INDEPENDANT
            # (le moteur y ecrit la couleur/le mouvement en cours pendant la
            # lecture), mais deepcopy tenterait de cloner des QColor.
            self.ia_settings[dst] = self.ia_settings[row].copy()
        if row in self.ia_analysis:
            self.ia_analysis[dst] = copy.deepcopy(self.ia_analysis[row])
        if row in self.image_durations:
            self.image_durations[dst] = self.image_durations[row]

        # Widget DMX du duplicata + recâblage des lignes décalées (leur index a
        # changé de r → r+1).
        if has_dmx:
            self._apply_row_dmx(dst, src_mode)
        for r, m in sorted(shifted_modes.items(), reverse=True):
            self._apply_row_dmx(r + 1, m)

        # Flag boucle + visuel.
        if was_loop:
            self.set_row_loop(dst, True)

        # current_row décalé si la ligne courante était au-dessous du point d'insert.
        if self.current_row >= dst:
            self.current_row += 1

        self.is_dirty = True

    def stop_sequence_playback(self):
        """Arrete la lecture de la sequence"""
        if self.playback_timer:
            self.playback_timer.stop()
        self.playback_row = -1
        self.playback_index = 0

        if self.timeline_playback_timer:
            _etait_actif = self.timeline_playback_timer.isActive()
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            # Uniquement si une timeline tournait vraiment : hors Play Lumiere,
            # les canaux bruts appartiennent a l'utilisateur (curseurs du plan de
            # feu, rappel memoire) et un STOP n'a pas a les effacer.
            if _etait_actif:
                self._clear_timeline_leftovers()
        if hasattr(self, 'timeline_playback_row'):
            del self.timeline_playback_row
        self.timeline_tracks_data = {}
        # Le prochain démarrage doit pouvoir noircir à nouveau sur pause
        self._timeline_pause_blackout = False
