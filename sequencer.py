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
        self.setWindowTitle("Paramètres Live")
        self.setModal(True)
        self.setMinimumWidth(500)
        # Deep copy config
        self._config = {
            'source':          config.get('source', 'loopback'),
            'allowed_groups':  set(config.get('allowed_groups', set())),
            'allowed_effects': set(config.get('allowed_effects', set())),
            'lyre_presets':    list(config.get('lyre_presets', [])),
            'palette':         list(config.get('palette', [])),
        }
        self._sources      = sources
        self._color_btns   = []   # [(QPushButton, QColor)]
        self._preset_rows  = []   # [(QWidget, pan_spin, tilt_spin)]
        self._pos_getter   = None
        self._setup_ui()
        self._load_config()

    def set_position_getter(self, fn):
        self._pos_getter = fn
        self._cap_btn.setVisible(fn is not None)

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
        grp_row.setSpacing(6)
        self._grp_btns = {}
        for gid, lbl in [('face','Face'), ('douche','Douche'),
                          ('lat','Lat'), ('contre','Contre'), ('lyre','Lyres')]:
            b = self._mkbtn(lbl)
            self._grp_btns[gid] = b
            grp_row.addWidget(b)
        root.addLayout(grp_row)
        root.addWidget(self._sep())

        # ── Effets autorisés ────────────────────────────────────────────────────
        root.addWidget(self._slbl("EFFETS AUTORISÉS  —  vide = tous autorisés", LS))
        eff_row = QHBoxLayout()
        eff_row.setSpacing(6)
        self._eff_btns = {}
        for eid, lbl in [('flash','Flash'), ('strobe','Strobe'), ('gobo','Gobo'),
                          ('auto','AUTO ⚡'), ('circle','Cercle'), ('eight','Huit')]:
            b = self._mkbtn(lbl)
            self._eff_btns[eid] = b
            eff_row.addWidget(b)
        root.addLayout(eff_row)
        root.addWidget(self._sep())

        # ── Positions lyres ─────────────────────────────────────────────────────
        pos_hdr = QHBoxLayout()
        pos_hdr.addWidget(self._slbl("POSITIONS LYRES PRÉDÉFINIES", LS))
        pos_hdr.addStretch()
        add_p = QPushButton("+ Ajouter")
        add_p.setFixedHeight(24)
        add_p.setStyleSheet(self._gbtn())
        add_p.setCursor(Qt.PointingHandCursor)
        add_p.clicked.connect(lambda: self._add_preset_row(128, 128))
        pos_hdr.addWidget(add_p)
        self._cap_btn = QPushButton("📍 Capturer")
        self._cap_btn.setFixedHeight(24)
        self._cap_btn.setStyleSheet(self._gbtn())
        self._cap_btn.setCursor(Qt.PointingHandCursor)
        self._cap_btn.clicked.connect(self._capture_positions)
        self._cap_btn.setVisible(False)
        pos_hdr.addWidget(self._cap_btn)
        root.addLayout(pos_hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(110)
        self._pos_container = QWidget()
        self._pos_layout = QVBoxLayout(self._pos_container)
        self._pos_layout.setContentsMargins(0, 4, 0, 4)
        self._pos_layout.setSpacing(4)
        self._pos_layout.addStretch()
        scroll.setWidget(self._pos_container)
        root.addWidget(scroll)
        root.addWidget(self._sep())

        # ── Palette couleurs ────────────────────────────────────────────────────
        root.addWidget(self._slbl("PALETTE COULEURS  —  vide = palette auto", LS))
        pal_w = QWidget()
        self._pal_row = QHBoxLayout(pal_w)
        self._pal_row.setContentsMargins(0, 0, 0, 0)
        self._pal_row.setSpacing(6)
        self._pal_row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_c = QPushButton("+")
        add_c.setFixedSize(36, 36)
        add_c.setToolTip("Ajouter une couleur")
        add_c.setStyleSheet(self._gbtn() + " QPushButton { font-size:18px; }")
        add_c.setCursor(Qt.PointingHandCursor)
        add_c.clicked.connect(self._add_palette_color)
        self._pal_row.addWidget(add_c)
        root.addWidget(pal_w)
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

    # ── Positions lyres ──────────────────────────────────────────────────────────

    def _add_preset_row(self, pan: int, tilt: int):
        row_w = QWidget()
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        pan_lbl = QLabel("Pan")
        pan_lbl.setStyleSheet("color:#666; font-size:11px;")
        pan_s = QSpinBox()
        pan_s.setRange(0, 255)
        pan_s.setValue(pan)
        pan_s.setFixedWidth(70)
        tlt_lbl = QLabel("Tilt")
        tlt_lbl.setStyleSheet("color:#666; font-size:11px;")
        tlt_s = QSpinBox()
        tlt_s.setRange(0, 255)
        tlt_s.setValue(tilt)
        tlt_s.setFixedWidth(70)
        rm = QPushButton("✕")
        rm.setFixedSize(22, 22)
        rm.setCursor(Qt.PointingHandCursor)
        rm.setStyleSheet("""
            QPushButton{background:#1a0808;color:#aa3333;
                border:1px solid #3a1818;border-radius:4px;padding:0;font-size:10px;}
            QPushButton:hover{background:#2a1010;}
        """)
        rm.clicked.connect(lambda: self._rm_preset(row_w))
        rl.addWidget(pan_lbl); rl.addWidget(pan_s)
        rl.addWidget(tlt_lbl); rl.addWidget(tlt_s)
        rl.addStretch(); rl.addWidget(rm)
        self._pos_layout.insertWidget(self._pos_layout.count() - 1, row_w)
        self._preset_rows.append((row_w, pan_s, tlt_s))

    def _rm_preset(self, w: QWidget):
        self._preset_rows = [(rw, p, t) for rw, p, t in self._preset_rows if rw is not w]
        w.deleteLater()

    def _capture_positions(self):
        if self._pos_getter:
            for pan, tilt in self._pos_getter():
                self._add_preset_row(pan, tilt)

    # ── Palette ──────────────────────────────────────────────────────────────────

    def _add_color_swatch(self, color: QColor):
        btn = QPushButton()
        btn.setFixedSize(36, 36)
        btn.setCursor(Qt.PointingHandCursor)
        h = color.name()
        btn.setToolTip(h)
        btn.setStyleSheet(
            f"QPushButton{{background:{h};border:2px solid #3a3a3a;border-radius:4px;}}"
            "QPushButton:hover{border-color:#00d4ff;}")
        btn.setContextMenuPolicy(Qt.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda _pos, b=btn: self._swatch_menu(b))
        self._pal_row.insertWidget(self._pal_row.count() - 1, btn)
        self._color_btns.append((btn, color))

    def _swatch_menu(self, btn):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu{background:#1a1a1a;color:#e0e0e0;border:1px solid #3a3a3a;}
            QMenu::item:selected{background:#2a2a2a;}
        """)
        rm = menu.addAction("Supprimer")
        if menu.exec(btn.mapToGlobal(btn.rect().bottomLeft())) == rm:
            self._color_btns = [(b, c) for b, c in self._color_btns if b is not btn]
            btn.deleteLater()

    def _add_palette_color(self):
        c = QColorDialog.getColor(QColor("#ff4400"), self, "Ajouter une couleur",
                                  QColorDialog.DontUseNativeDialog)
        if c.isValid():
            self._add_color_swatch(c)

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
        ae = self._config.get('allowed_effects', set())
        for eid, b in self._eff_btns.items():
            b.setChecked(eid in ae)
        for pan, tilt in self._config.get('lyre_presets', []):
            self._add_preset_row(pan, tilt)
        for c in self._config.get('palette', []):
            self._add_color_swatch(c)

    def _reset_all(self):
        for b in self._grp_btns.values():
            b.setChecked(False)
        for b in self._eff_btns.values():
            b.setChecked(False)
        for w, _, _ in list(self._preset_rows):
            w.deleteLater()
        self._preset_rows.clear()
        for b, _ in list(self._color_btns):
            b.deleteLater()
        self._color_btns.clear()

    def _do_apply(self):
        idx = self._source_combo.currentIndex()
        self._config['source'] = (self._sources[idx][1]
                                  if 0 <= idx < len(self._sources) else 'loopback')
        self._config['allowed_groups']  = {g for g, b in self._grp_btns.items() if b.isChecked()}
        self._config['allowed_effects'] = {e for e, b in self._eff_btns.items() if b.isChecked()}
        self._config['lyre_presets']    = [(p.value(), t.value()) for _, p, t in self._preset_rows]
        self._config['palette']         = [c for _, c in self._color_btns]
        self.accept()

    def get_config(self) -> dict:
        return self._config


class LiveModePanel(QWidget):
    """Panneau de controle du mode LIVE - remplace la playlist quand actif"""

    color_changed       = Signal(object)  # QColor
    nervosity_changed   = Signal(int)     # 0–100
    sensitivity_changed = Signal(int)     # 0–100
    lyre_mode_changed   = Signal(str)     # '' | 'circle' | 'eight'
    bpm_override        = Signal(float)   # BPM manuel
    bpm_released        = Signal()        # retour auto
    settings_applied    = Signal(dict)    # config live mise à jour

    SOURCES = [
        ("Loopback système",   "loopback"),
        ("Micro / Line In",    "mic"),
        ("MIDI Clock",         "midi_clock"),
        ("Virtual DJ",         "virtualdj"),
        ("Rekordbox",          "rekordbox"),
        ("Analyse IA (fichier)", "ia_file"),
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
        "loopback":   "Spotify, YouTube, VLC, Deezer, tout lecteur système",
        "mic":        "Table de mixage, micro, entrée ligne, interface audio",
        "midi_clock": "Rekordbox · Traktor · Virtual DJ · Ableton · Serato · Mixxx",
        "virtualdj":  "Virtual DJ 8 / 2023 / 2024  —  HTTP localhost:8088",
        "rekordbox":  "Rekordbox 6+  —  Préférences › MIDI › activer MIDI Clock",
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
        self._pulse_phase   = 0
        self._pulse_section = ''
        self._bpm_manual    = False
        self._live_config   = {
            'source':          'loopback',
            'allowed_groups':  set(),
            'allowed_effects': set(),
            'lyre_presets':    [],
            'palette':         [],
        }
        self._pos_getter = None
        self._setup_ui()
        # Brancher les signaux après création des sliders
        self.nerv_slider.valueChanged.connect(self.nervosity_changed)
        self.sens_slider.valueChanged.connect(self.sensitivity_changed)
        # Timer d'animation section (120 ms)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_timer.start(120)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        lbl_style = "color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;"

        # ── Source ─────────────────────────────────────────────────────────
        src_row = QHBoxLayout()
        src_lbl = QLabel("SOURCE")
        src_lbl.setStyleSheet(lbl_style)
        src_lbl.setFixedWidth(100)
        self.source_combo = QComboBox()
        for label, _ in self.SOURCES:
            self.source_combo.addItem(label)
        self.source_combo.setStyleSheet("""
            QComboBox {
                background: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a; border-radius: 4px;
                padding: 6px 12px; font-size: 13px;
            }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView {
                background: #1e1e1e; color: #e0e0e0;
                border: 1px solid #3a3a3a;
                selection-background-color: #2a4a5a;
            }
        """)
        self.source_combo.wheelEvent = lambda e: e.ignore()
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        src_row.addWidget(src_lbl)
        src_row.addWidget(self.source_combo, 1)

        # Dot de connexion (●)
        self._conn_dot = QLabel()
        self._conn_dot.setFixedSize(10, 10)
        self._conn_dot.setToolTip("Statut de connexion")
        self._set_conn_dot('off')
        src_row.addWidget(self._conn_dot)

        # Bouton paramètres ⚙
        cfg_btn = QPushButton("⚙")
        cfg_btn.setFixedSize(26, 26)
        cfg_btn.setCursor(Qt.PointingHandCursor)
        cfg_btn.setToolTip("Paramètres Live")
        cfg_btn.setStyleSheet("""
            QPushButton {
                background:#1a1a1a; color:#666;
                border:1px solid #252525; border-radius:4px;
                font-size:13px; padding:0;
            }
            QPushButton:hover { background:#222; color:#e0e0e0; border-color:#444; }
        """)
        cfg_btn.clicked.connect(self._open_settings)
        src_row.addWidget(cfg_btn)

        layout.addLayout(src_row)

        # Info source (logiciels compatibles)
        self._source_info_lbl = QLabel(self._SOURCE_INFO.get("loopback", ""))
        self._source_info_lbl.setStyleSheet(
            "color: #505050; font-size: 10px; font-style: italic; padding-left: 104px;")
        layout.addWidget(self._source_info_lbl)

        # Label device actif (rempli par le moteur au démarrage)
        self.device_lbl = QLabel("—")
        self.device_lbl.setStyleSheet(
            "color: #444; font-size: 10px; font-style: italic; padding-left: 104px;")
        layout.addWidget(self.device_lbl)

        # Badge logiciel détecté (caché par défaut)
        self._detected_badge = QLabel()
        self._detected_badge.setAlignment(Qt.AlignCenter)
        self._detected_badge.setFixedHeight(26)
        self._detected_badge.setStyleSheet("""
            color: #00cc44; font-size: 11px; font-weight: bold;
            background: #001800; border: 1px solid #00cc44;
            border-radius: 4px; padding: 0 10px; letter-spacing: 1.5px;
        """)
        layout.addWidget(self._detected_badge)
        self._detected_badge.hide()

        # ── Section MIDI virtuel (loopMIDI) — visible seulement en MIDI Clock ─
        self._midi_setup = self._build_midi_setup_widget()
        layout.addWidget(self._midi_setup)
        self._midi_setup.hide()

        layout.addWidget(self._separator())

        # ── Couleur dominante ───────────────────────────────────────────────
        color_row = QHBoxLayout()
        color_lbl = QLabel("COULEUR DOMINANTE")
        color_lbl.setStyleSheet(lbl_style)
        color_lbl.setFixedWidth(150)
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(110, 30)
        self.color_btn.setCursor(Qt.PointingHandCursor)
        self.color_btn.clicked.connect(self._pick_color)
        self._refresh_color_btn()
        color_row.addWidget(color_lbl)
        color_row.addWidget(self.color_btn)
        color_row.addStretch()
        layout.addLayout(color_row)

        # ── Nervosité ───────────────────────────────────────────────────────
        layout.addLayout(self._slider_row("NERVOSITÉ", "nerv", 50,
                                          "Vitesse des changements d'effets et de couleurs"))

        # ── Sensibilité ─────────────────────────────────────────────────────
        layout.addLayout(self._slider_row("SENSIBILITÉ", "sens", 70,
                                          "Seuil de détection des beats"))

        layout.addWidget(self._separator())

        # ── VU Mètre ────────────────────────────────────────────────────────
        vu_lbl = QLabel("NIVEAU AUDIO")
        vu_lbl.setStyleSheet(lbl_style)
        layout.addWidget(vu_lbl)

        self.vu_bar = QProgressBar()
        self.vu_bar.setRange(0, 100)
        self.vu_bar.setValue(0)
        self.vu_bar.setTextVisible(False)
        self.vu_bar.setFixedHeight(12)
        self.vu_bar.setStyleSheet("""
            QProgressBar {
                background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 5px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00d4ff, stop:0.6 #00ff88,
                    stop:0.85 #ffaa00, stop:1 #ff3300);
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.vu_bar)

        # ── Statut BPM / Section (ligne compacte) ────────────────────────────
        status_row = QHBoxLayout()
        self.bpm_lbl = QLabel("BPM  —")
        self.bpm_lbl.setStyleSheet("color: #555; font-size: 12px; font-weight: bold;")
        self.section_lbl = QLabel("—")
        self.section_lbl.setStyleSheet("color: #555; font-size: 12px; font-weight: bold;")
        status_row.addWidget(self.bpm_lbl)
        status_row.addStretch()
        status_row.addWidget(self.section_lbl)
        layout.addLayout(status_row)

        # ── Grand indicateur de section (animé) ──────────────────────────────
        self._section_ind = QLabel("—")
        self._section_ind.setAlignment(Qt.AlignCenter)
        self._section_ind.setFixedHeight(46)
        self._section_ind.setStyleSheet("""
            color: #333; font-size: 20px; font-weight: bold;
            letter-spacing: 4px; background: #0a0a0a;
            border: 1px solid #1e1e1e; border-radius: 6px;
        """)
        layout.addWidget(self._section_ind)

        layout.addWidget(self._separator())

        # ── Beat + BPM ─────────────────────────────────────────────────────
        layout.addLayout(self._build_beat_bpm_row())

        layout.addWidget(self._separator())

        # ── Contrôles rapides (tuiles draggables) ───────────────────────────
        ctrl_lbl = QLabel("CONTRÔLES RAPIDES")
        ctrl_lbl.setStyleSheet(lbl_style)
        layout.addWidget(ctrl_lbl)

        self._quick_bar = LiveQuickBar(self)
        self._quick_bar.lyre_mode_changed.connect(self.lyre_mode_changed)
        self._quick_bar.color_selected.connect(self._on_color_preset)
        layout.addWidget(self._quick_bar)

        layout.addStretch()

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

    def _refresh_color_btn(self):
        hex_c = self.dominant_color.name()
        lum = (self.dominant_color.red() * 299 +
               self.dominant_color.green() * 587 +
               self.dominant_color.blue() * 114) / 1000
        txt = "#000" if lum > 128 else "#fff"
        self.color_btn.setStyleSheet(f"""
            QPushButton {{
                background: {hex_c};
                border: 2px solid #3a3a3a;
                border-radius: 4px;
                color: {txt};
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{ border-color: #00d4ff; }}
        """)
        self.color_btn.setText(hex_c.upper())

    def _pick_color(self):
        c = QColorDialog.getColor(self.dominant_color, self, "Couleur dominante",
                                  QColorDialog.DontUseNativeDialog)
        if c.isValid():
            self.dominant_color = c
            self._refresh_color_btn()
            self.color_changed.emit(c)

    # ── API publique (pour le moteur audio - étape 2) ────────────────────────

    @property
    def source_key(self):
        idx = self.source_combo.currentIndex()
        return self.SOURCES[idx][1] if 0 <= idx < len(self.SOURCES) else "loopback"

    @property
    def nervosity(self):
        return self.nerv_slider.value() / 100.0

    @property
    def sensitivity(self):
        return self.sens_slider.value() / 100.0

    def _on_source_changed(self, idx: int):
        key = self.SOURCES[idx][1] if 0 <= idx < len(self.SOURCES) else "loopback"
        self._source_info_lbl.setText(self._SOURCE_INFO.get(key, ""))
        self._set_conn_dot('off')
        self.device_lbl.setText("—")
        is_midi = (key == 'midi_clock')
        self._midi_setup.setVisible(is_midi)
        if is_midi:
            QTimer.singleShot(0, self._refresh_midi_status)

    def _build_midi_setup_widget(self):
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: #080f08;
                border: 1px solid #1a3a1a;
                border-radius: 6px;
            }
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(7)

        hdr = QHBoxLayout()
        lbl = QLabel("MIDI VIRTUEL")
        lbl.setStyleSheet(
            "color: #44aa44; font-size: 10px; font-weight: bold; letter-spacing: 1.5px;")
        self._midi_dot = QLabel()
        self._midi_dot.setFixedSize(10, 10)
        self._midi_dot.setStyleSheet("background: #333; border-radius: 5px;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        hdr.addWidget(self._midi_dot)
        lay.addLayout(hdr)

        self._midi_status_lbl = QLabel("Vérification…")
        self._midi_status_lbl.setStyleSheet(
            "color: #668866; font-size: 11px;")
        self._midi_status_lbl.setWordWrap(True)
        lay.addWidget(self._midi_status_lbl)

        self._midi_btn = QPushButton()
        self._midi_btn.setCursor(Qt.PointingHandCursor)
        self._midi_btn.setStyleSheet("""
            QPushButton {
                background: #142014; color: #44cc44;
                border: 1px solid #2a5a2a; border-radius: 4px;
                padding: 5px 12px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background: #1e341e; border-color: #44cc44; }
        """)
        self._midi_btn.clicked.connect(self._on_midi_btn_clicked)
        lay.addWidget(self._midi_btn)

        self._midi_instr_lbl = QLabel(
            f'Dans votre logiciel DJ : sélectionnez "{LoopMidiHelper.PORT_NAME}"')
        self._midi_instr_lbl.setStyleSheet(
            "color: #336633; font-size: 10px; font-style: italic;")
        self._midi_instr_lbl.setWordWrap(True)
        lay.addWidget(self._midi_instr_lbl)
        self._midi_instr_lbl.hide()

        return frame

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
        self.device_lbl.setStyleSheet(
            "color: #558; font-size: 10px; font-style: italic; padding-left: 104px;")

    def set_vu(self, value_0_100):
        self.vu_bar.setValue(int(max(0, min(100, value_0_100))))

    def set_status(self, bpm=None, section=None):
        _section_colors = {
            'DROP': '#ff3300', 'HIGH': '#ff8800', 'BUILD': '#ffcc00',
            'VERSE': '#00d4ff', 'QUIET': '#555',
        }
        if bpm is not None:
            self.bpm_lbl.setText(f"BPM  {bpm:.0f}" if bpm > 0 else "BPM  —")
            self.set_bpm_auto(bpm)
        if section is not None:
            tag = section.upper()
            color = _section_colors.get(tag, '#aaa')
            self.section_lbl.setText(tag)
            self.section_lbl.setStyleSheet(
                f"color: {color}; font-size: 12px; font-weight: bold;")
            # Mettre à jour le grand indicateur
            self._pulse_section = tag.lower()
            self._apply_section_style(tag.lower(), bright=True)

    def _apply_section_style(self, sec: str, bright: bool = True):
        """Applique le style du grand indicateur pour la section donnée."""
        style = self._SECTION_STYLES.get(sec)
        if style:
            color = style['color_a'] if bright else style['color_b']
            fs    = style['fs']
            text  = style['text']
            self._section_ind.setText(text)
            self._section_ind.setStyleSheet(f"""
                color: {color}; font-size: {fs}px; font-weight: bold;
                letter-spacing: 4px; background: #0a0a0a;
                border: 1px solid {color}55; border-radius: 6px;
            """)
        elif sec in ('—', ''):
            self._section_ind.setText("—")
            self._section_ind.setStyleSheet("""
                color: #333; font-size: 20px; font-weight: bold;
                letter-spacing: 4px; background: #0a0a0a;
                border: 1px solid #1e1e1e; border-radius: 6px;
            """)

    def _pulse_tick(self):
        """Animation de l'indicateur de section (DROP et MONTÉE pulsent)."""
        self._pulse_phase = (self._pulse_phase + 1) % 10
        sec = self._pulse_section
        if sec in ('drop', 'build'):
            # Dim 1 frame sur 4 pour un effet de pulsation
            bright = self._pulse_phase % 4 != 0
            self._apply_section_style(sec, bright)

    # ── Beat + BPM ────────────────────────────────────────────────────────────

    def _build_beat_bpm_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        # Indicateur beat (cercle)
        self._beat_btn = QPushButton("●")
        self._beat_btn.setFixedSize(44, 44)
        self._beat_btn.setEnabled(False)
        self._beat_idle_style = (
            "QPushButton { background:#0d0d0d; color:#252525;"
            " border:2px solid #1e1e1e; border-radius:22px; font-size:20px; }"
        )
        self._beat_active_style = (
            "QPushButton { background:#ffffff18; color:#ffffff;"
            " border:2px solid #ffffff; border-radius:22px; font-size:20px; }"
        )
        self._beat_btn.setStyleSheet(self._beat_idle_style)

        beat_col = QVBoxLayout()
        beat_col.setSpacing(2)
        beat_col.addWidget(self._beat_btn)
        beat_lbl = QLabel("BEAT")
        beat_lbl.setStyleSheet(
            "color:#444; font-size:9px; font-weight:bold; letter-spacing:1px;")
        beat_lbl.setAlignment(Qt.AlignCenter)
        beat_col.addWidget(beat_lbl)
        row.addLayout(beat_col)

        row.addStretch()

        # Slider BPM
        bpm_col = QVBoxLayout()
        bpm_col.setSpacing(4)

        bpm_hdr = QHBoxLayout()
        bpm_hdr.setSpacing(6)
        bpm_ttl = QLabel("BPM")
        bpm_ttl.setStyleSheet(
            "color:#888; font-size:10px; font-weight:bold; letter-spacing:1.5px;")
        self._bpm_val_lbl = QLabel("—")
        self._bpm_val_lbl.setStyleSheet(
            "color:#00d4ff; font-size:14px; font-weight:bold; min-width:36px;")
        self._bpm_val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._bpm_auto_btn = QPushButton("AUTO ↺")
        self._bpm_auto_btn.setFixedHeight(20)
        self._bpm_auto_btn.setStyleSheet("""
            QPushButton {
                background:#1a2a1a; color:#44cc44;
                border:1px solid #2a5a2a; border-radius:4px;
                padding:0 6px; font-size:9px; font-weight:bold;
            }
            QPushButton:hover { background:#223322; }
        """)
        self._bpm_auto_btn.clicked.connect(self._on_bpm_auto_reset)
        self._bpm_auto_btn.hide()
        bpm_hdr.addWidget(bpm_ttl)
        bpm_hdr.addStretch()
        bpm_hdr.addWidget(self._bpm_val_lbl)
        bpm_hdr.addWidget(self._bpm_auto_btn)

        self._bpm_slider = QSlider(Qt.Horizontal)
        self._bpm_slider.setRange(60, 200)
        self._bpm_slider.setValue(120)
        self._bpm_slider.setStyleSheet(self._SLIDER_STYLE)
        self._bpm_slider.sliderMoved.connect(self._on_bpm_moved)
        self._bpm_slider.valueChanged.connect(self._on_bpm_changed)

        bpm_col.addLayout(bpm_hdr)
        bpm_col.addWidget(self._bpm_slider)
        row.addLayout(bpm_col)

        return row

    def flash_beat(self):
        """Flash le bouton beat — appelé par le moteur à chaque beat détecté."""
        self._beat_btn.setStyleSheet(self._beat_active_style)
        QTimer.singleShot(80, lambda: self._beat_btn.setStyleSheet(self._beat_idle_style))

    def set_bpm_auto(self, bpm: float):
        """Met à jour le slider BPM en mode auto (ignoré si manuel)."""
        if self._bpm_manual:
            return
        if bpm > 0:
            self._bpm_slider.blockSignals(True)
            self._bpm_slider.setValue(int(min(200, max(60, bpm))))
            self._bpm_slider.blockSignals(False)
        self._bpm_val_lbl.setText(f"{bpm:.0f}" if bpm > 0 else "—")

    def _on_bpm_moved(self):
        """Déclenché seulement quand l'utilisateur glisse vraiment le handle."""
        if not self._bpm_manual:
            self._bpm_manual = True
            self._bpm_auto_btn.show()
            self._bpm_val_lbl.setStyleSheet(
                "color:#ffaa00; font-size:14px; font-weight:bold; min-width:36px;")

    def _on_bpm_changed(self, value: int):
        self._bpm_val_lbl.setText(str(value))
        if self._bpm_manual:
            self.bpm_override.emit(float(value))

    def _on_bpm_auto_reset(self):
        self._bpm_manual = False
        self._bpm_auto_btn.hide()
        self._bpm_val_lbl.setStyleSheet(
            "color:#00d4ff; font-size:14px; font-weight:bold; min-width:36px;")
        self.bpm_released.emit()

    # ── Lyre mode ──────────────────────────────────────────────────────────────

    @property
    def lyre_mode(self) -> str:
        return self._quick_bar.lyre_mode()

    # ── Tile state ────────────────────────────────────────────────────────────

    def is_tile_active(self, tile_id: str) -> bool:
        tile = self._quick_bar._tiles.get(tile_id)
        return tile.is_checked if tile else False

    # ── Color presets ─────────────────────────────────────────────────────────

    def _on_color_preset(self, hex_color: str):
        c = QColor(hex_color)
        if c.isValid():
            self.dominant_color = c
            self._refresh_color_btn()
            self.color_changed.emit(c)

    # ── Detected software ─────────────────────────────────────────────────────

    def set_detected_software(self, name: str, source_key: str):
        """Appelé par SoftwareDetector — affiche le badge et auto-sélectionne la source."""
        if name:
            self._detected_badge.setText(f"◉  {name.upper()} DÉTECTÉ")
            self._detected_badge.show()
            # Auto-sélectionner la source correspondante dans le combo
            for i, (_, key) in enumerate(self.SOURCES):
                if key == source_key:
                    if self.source_combo.currentIndex() != i:
                        self.source_combo.setCurrentIndex(i)
                    break
        else:
            self._detected_badge.hide()

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

        self.autosave_lbl = QLabel()
        self.autosave_lbl.setStyleSheet("color: #3a8a3a; font-size: 10px;")
        self.autosave_lbl.hide()
        header.addWidget(self.autosave_lbl)

        header.addStretch()

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

        # Séparateur visuel
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("QFrame { color: #3a3a3a; }")
        sep.setFixedHeight(24)
        header.addWidget(sep)

        # Bouton LIVE toggle
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
        self.live_btn.setVisible(False)
        header.addWidget(self.live_btn)

        layout.addLayout(header)

        # Panneau LIVE (créé une seule fois, caché par défaut)
        self.live_panel = LiveModePanel(self)

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

        self.content_stack.addWidget(self.table)       # index 0
        self.content_stack.addWidget(self.live_panel)  # index 1
        layout.addWidget(self.content_stack)

        # Timer pour mise a jour UI
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_ui_state)
        self.timer.start(200)

    def _toggle_live(self, checked):
        """Active / désactive le mode LIVE"""
        if checked:
            self.live_btn.setText("● LIVE")
            self.live_btn.setStyleSheet(self._live_btn_style_on)
            self.content_stack.setCurrentIndex(1)
            # Désactiver les boutons playlist inutiles en mode LIVE
            for btn in (self.up_btn, self.down_btn, self.del_btn, self.add_btn):
                btn.setEnabled(False)
                btn.setStyleSheet(btn.styleSheet() + "QPushButton { opacity: 0.3; }")
        else:
            self.live_btn.setText("● LIVE")
            self.live_btn.setStyleSheet(self._live_btn_style_off)
            self.content_stack.setCurrentIndex(0)
            for btn in (self.up_btn, self.down_btn, self.del_btn, self.add_btn):
                btn.setEnabled(True)
            # Re-appliquer les styles d'origine
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
            self.up_btn.setStyleSheet(btn_style)
            self.down_btn.setStyleSheet(btn_style)
            self.del_btn.setStyleSheet(btn_style)
            self.add_btn.setStyleSheet(btn_style + "QPushButton { font-size: 18px; }")

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
