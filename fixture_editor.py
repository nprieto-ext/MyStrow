"""
Editeur de fixture DMX — MyStrow
Dialog de création et gestion de templates de fixtures pour le patch DMX.
"""
import copy
import gzip
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QLineEdit, QComboBox, QFrame,
    QMessageBox, QListWidget, QListWidgetItem, QMenuBar,
    QFileDialog, QSplitter, QAbstractItemView, QSizePolicy,
    QProgressBar, QStyledItemDelegate, QStyleFactory,
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QObject, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QAction, QKeySequence, QPalette

from builtin_fixtures import BUILTIN_FIXTURES
from fixture_packs import (
    FixturePackBanner, FixturePackDownloadDialog,
    FixturePackCheckWorker, load_packs_state, should_check_now,
)

_BUNDLE_ROLE = Qt.UserRole + 3   # data role for OFL bundle fixtures in QListWidget
_BUNDLE_CACHE: list | None = None  # module-level lazy cache

_BUNDLE_GROUP = {
    "Moving Head":     "lyre",
    "Barre LED":       "barre",
    "Stroboscope":     "strobe",
    "Machine a fumee": "fumee",
}


def _load_bundle() -> list:
    """Charge fixtures_bundle.json.gz (OFL) en cache module. Thread-safe en lecture."""
    global _BUNDLE_CACHE
    if _BUNDLE_CACHE is not None:
        return _BUNDLE_CACHE
    try:
        bundle_path = Path(__file__).parent / "fixtures_bundle.json.gz"
        if not bundle_path.exists():
            _BUNDLE_CACHE = []
            return _BUNDLE_CACHE
        with gzip.open(bundle_path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        items = []
        for fx in data:
            modes = fx.get("modes", [])
            n_modes = len(modes)
            for m in modes:
                profile = m.get("profile", [])
                if not profile:
                    continue
                name = fx["name"]
                if n_modes > 1:
                    name += f" · {m['name']}"
                items.append({
                    "name":         name,
                    "manufacturer": fx.get("manufacturer", ""),
                    "fixture_type": fx.get("fixture_type", "PAR LED"),
                    "group":        _BUNDLE_GROUP.get(fx.get("fixture_type", ""), "face"),
                    "profile":      profile,
                    "source":       "ofl",
                    "_bundle":      True,
                })
        _BUNDLE_CACHE = items
    except Exception:
        _BUNDLE_CACHE = []
    return _BUNDLE_CACHE


class _NoScrollCombo(QComboBox):
    """QComboBox qui ignore le scroll souris (évite de changer de canal par accident)."""
    def wheelEvent(self, event):
        event.ignore()


FIXTURE_FILE = Path.home() / ".mystrow_fixtures.json"

FIXTURE_TYPES = ["PAR LED", "Moving Head", "Barre LED", "Stroboscope", "Machine a fumee"]

# Profils DMX autorisés par type de fixture (pour le filtre "Charger un profil")
TYPE_PROFILES = {
    "PAR LED":        ["RGB","RGBD","RGBDS","RGBSD","DRGB","DRGBS",
                       "RGBW","RGBWD","RGBWDS","RGBWZ","RGBWA","RGBWAD","RGBWOUV"],
    "Moving Head":    ["MOVING_5CH","MOVING_8CH","MOVING_RGB","MOVING_RGBW"],
    "Barre LED":      ["LED_BAR_RGB","RGB","RGBD","RGBDS"],
    "Stroboscope":    ["STROBE_2CH"],
    "Machine a fumee":["2CH_FUMEE"],
}
GROUP_OPTIONS = [
    "face", "douche1", "douche2", "douche3", "lat", "contre",
    "lyre", "barre", "strobe", "fumee",
]
ALL_CHANNEL_TYPES = [
    "R", "G", "B", "W", "Dim", "Strobe", "UV", "Ambre", "Orange", "Zoom",
    "Smoke", "Fan", "Pan", "PanFine", "Tilt", "TiltFine",
    "Gobo1", "Gobo2", "Prism", "Focus", "ColorWheel", "Shutter", "Speed", "Mode",
]
CHANNEL_COLORS = {
    "R": "#cc2200", "G": "#00aa00", "B": "#0055ff", "W": "#bbbbbb",
    "Dim": "#888800", "Strobe": "#ffaa00", "UV": "#8800cc",
    "Ambre": "#ee6600", "Orange": "#ff4400", "Zoom": "#00ccaa",
    "Smoke": "#555555", "Fan": "#336699", "Pan": "#ff55aa",
    "PanFine": "#cc4488", "Tilt": "#00ddff", "TiltFine": "#00aacc",
    "Gobo1": "#aa8800", "Gobo2": "#886600", "Prism": "#dd00dd",
    "Focus": "#00aa88", "ColorWheel": "#ff8800", "Shutter": "#ff2266",
    "Speed": "#66ff66", "Mode": "#88aaff",
}


# ──────────────────────────────────────────────────────────────────────────────
# DmxPreviewWidget — barre colorée représentant les canaux
# ──────────────────────────────────────────────────────────────────────────────

class DmxPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels = []
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_channels(self, channels):
        self._channels = list(channels)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#1a1a1a"))
        n = len(self._channels)
        if n == 0:
            painter.setPen(QColor("#555"))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(0, 0, w, h, Qt.AlignCenter, "Aucun canal défini")
            return
        block_w = max(22, min(72, w // n))
        total_w = block_w * n
        x0 = max(0, (w - total_w) // 2)
        for i, ch in enumerate(self._channels):
            x = x0 + i * block_w
            color = QColor(CHANNEL_COLORS.get(ch, "#444444"))
            painter.fillRect(x + 1, 4, block_w - 2, h - 8, color.darker(200))
            painter.setPen(QPen(color, 1))
            painter.drawRect(x + 1, 4, block_w - 2, h - 8)
            painter.setPen(QColor("#999"))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(x, 4, block_w, 12, Qt.AlignCenter, str(i + 1))
            painter.setPen(color.lighter(170))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            display = ch if len(ch) <= 6 else ch[:5] + "."
            painter.drawText(x, 16, block_w, h - 20, Qt.AlignCenter, display)
        painter.end()


# ──────────────────────────────────────────────────────────────────────────────
# ChannelRowWidget — une ligne de canal: numéro + type + ↑↓×
# ──────────────────────────────────────────────────────────────────────────────

class ChannelRowWidget(QWidget):
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
        idx = ALL_CHANNEL_TYPES.index(ch_type) if ch_type in ALL_CHANNEL_TYPES else 0
        self._combo.setCurrentIndex(idx)
        self._combo.currentTextChanged.connect(self._on_type_changed)
        layout.addWidget(self._combo, 1)

        _btn_style = (
            "QPushButton{background:#2a2a2a;color:#999;border:1px solid #3a3a3a;"
            "border-radius:3px;font-size:10px;min-width:0;padding:0;}"
            "QPushButton:hover{background:#3a3a3a;color:#fff;border-color:#555;}"
        )
        for text, slot in [("▲", self._on_up), ("▼", self._on_dn)]:
            b = QPushButton(text)
            b.setFixedSize(34, 30)
            b.setStyleSheet(_btn_style)
            b.clicked.connect(slot)
            layout.addWidget(b)

        btn_rm = QPushButton("✕")
        btn_rm.setFixedSize(34, 30)
        btn_rm.setStyleSheet(
            "QPushButton{background:#2a0000;color:#cc4444;border:1px solid #3a1111;"
            "border-radius:3px;font-size:11px;font-weight:bold;min-width:0;padding:0;}"
            "QPushButton:hover{background:#440000;color:#ff6666;border-color:#553333;}"
        )
        btn_rm.clicked.connect(self._on_rm)
        layout.addWidget(btn_rm)

    def _set_num_style(self, color):
        self._num_lbl.setStyleSheet(
            f"QLabel{{background:{color}22;border:1px solid {color};"
            f"border-radius:3px;color:{color};font-weight:bold;font-size:11px;}}"
        )

    def set_type(self, t):
        """Change le type sans déclencher la validation (revert)."""
        self._combo.blockSignals(True)
        idx = ALL_CHANNEL_TYPES.index(t) if t in ALL_CHANNEL_TYPES else 0
        self._combo.setCurrentIndex(idx)
        self._set_num_style(CHANNEL_COLORS.get(t, "#666"))
        self._combo.blockSignals(False)
        self._prev_type = t

    def _on_type_changed(self, ch_type):
        color = CHANNEL_COLORS.get(ch_type, "#666")
        self._set_num_style(color)
        self.changed.emit()

    def _on_up(self):  self.move_up_requested.emit(self)
    def _on_dn(self):  self.move_dn_requested.emit(self)
    def _on_rm(self):  self.remove_requested.emit(self)

    def set_num(self, n):
        self._num_lbl.setText(f"{n:02d}")

    def get_type(self):
        return self._combo.currentText()


_SUB_ROLE = Qt.UserRole + 2   # sous-texte type · canaux

class _FixtureItemDelegate(QStyledItemDelegate):
    """Affiche une ligne simple : nom coloré selon sélection."""
    def sizeHint(self, option, index):
        if not index.data(Qt.UserRole):  # headers
            return QSize(option.rect.width(), 22)
        return QSize(option.rect.width(), 28)

    def paint(self, painter, option, index):
        if not index.data(Qt.UserRole):  # section header — rendu standard
            super().paint(painter, option, index)
            return
        painter.save()
        from PySide6.QtWidgets import QStyle
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hovered  = bool(option.state & QStyle.State_MouseOver)
        if is_selected:
            bg = QColor("#00d4ff18")
        elif is_hovered:
            bg = QColor("#1e1e1e")
        else:
            bg = QColor(0, 0, 0, 0)
        painter.fillRect(option.rect, bg)
        x, y, w, h = option.rect.x(), option.rect.y(), option.rect.width(), option.rect.height()
        if is_selected:
            name_color = QColor("#00d4ff")
        else:
            fg = index.data(Qt.ForegroundRole)
            name_color = fg.color() if fg else QColor("#aaa")
        f_name = option.font
        f_name.setBold(is_selected)
        painter.setFont(f_name)
        painter.setPen(name_color)
        painter.drawText(QRect(x + 10, y, w - 14, h), Qt.AlignVCenter | Qt.AlignLeft,
                         index.data(Qt.DisplayRole) or "")
        painter.restore()


# ──────────────────────────────────────────────────────────────────────────────
# FixtureEditorDialog
# ──────────────────────────────────────────────────────────────────────────────

class FixtureEditorDialog(QDialog):
    """Editeur de templates de fixtures DMX"""
    fixture_added = Signal(dict)

    _STYLE = """
        QDialog       { background: #141414; color: #e0e0e0; }
        QWidget       { background: #141414; color: #e0e0e0; }
        QLabel        { color: #e0e0e0; background: transparent; }
        QLineEdit     { background: #1e1e1e; color: #fff;
                        border: 1px solid #444; border-radius: 6px;
                        padding: 6px 12px; font-size: 13px; }
        QLineEdit:focus { border-color: #00d4ff88; }
        QComboBox     { background: #1e1e1e; color: #e0e0e0; border: 1px solid #444;
                        border-radius: 6px; padding: 4px 10px; font-size: 12px; }
        QComboBox::drop-down { border: none; width: 20px; }
        QComboBox QAbstractItemView { background: #1e1e1e; color: #e0e0e0;
                        selection-background-color: #00d4ff; selection-color: #000;
                        border: 1px solid #444; }
        QListWidget   { background: #1e1e1e; color: #e0e0e0;
                        border: 1px solid #333; border-radius: 6px;
                        font-size: 12px; outline: none; }
        QListWidget::item { padding: 5px 10px; }
        QListWidget::item:selected { background: #00d4ff; color: #000; font-weight: bold; }
        QListWidget::item:hover:!selected { background: #2a2a2a; }
        QPushButton   { background: #2a2a2a; color: #ccc;
                        border: 1px solid #4a4a4a; border-radius: 6px;
                        padding: 6px 16px; font-size: 12px; }
        QPushButton:hover { border-color: #00d4ff; color: #fff; }
        QPushButton:disabled { background: #1a1a1a; color: #333; border-color: #2a2a2a; }
        QScrollArea   { background: transparent; border: none; }
        QScrollBar:vertical { background: #1a1a1a; width: 7px; border-radius: 3px; }
        QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 3px; min-height: 16px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QSplitter::handle { background: #2a2a2a; width: 2px; }
        QMenuBar { background: #0d0d0d; color: #888; border-bottom: 1px solid #1a1a1a;
                   padding: 2px 8px; font-size: 12px; }
        QMenuBar::item { padding: 5px 14px; background: transparent; border-radius: 4px; }
        QMenuBar::item:selected { background: #1a1a1a; color: #ddd; }
        QMenu { background: #111; color: #ccc; border: 1px solid #2a2a2a; padding: 4px; font-size: 12px; }
        QMenu::item { padding: 7px 28px; border-radius: 3px; }
        QMenu::item:selected { background: #00d4ff22; color: #00d4ff; }
        QMenu::separator { background: #1e1e1e; height: 1px; margin: 3px 8px; }
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Editeur de fixture — MyStrow")
        self.setMinimumSize(960, 580)
        self.showMaximized()
        self._fixtures        = []   # custom fixtures (user-saved)
        self._current_idx     = -1   # index in _all_fixtures()
        self._is_builtin      = False
        self._channel_rows    = []
        self._undo_stack      = []
        self._btn_add_to_patch = None
        self._pack_check_thread  = None
        self._pack_check_worker  = None

        self._load_fixtures()
        self._build_ui()
        self._rebuild_mfr_list()
        self._rebuild_list()
        if self._all_fixtures():
            self._select_fixture(0)

        # Vérification des packs distants en arrière-plan (throttlée à 1h)
        QTimer.singleShot(800, self._check_fixture_packs)

    # ── Data helpers ─────────────────────────────────────────────────────────

    def _all_fixtures(self):
        return BUILTIN_FIXTURES + self._fixtures

    def _load_fixtures(self):
        try:
            if FIXTURE_FILE.exists():
                data = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._fixtures = [f for f in data
                                      if isinstance(f, dict) and not f.get("builtin")]
        except Exception:
            self._fixtures = []

    def _save_fixtures(self):
        try:
            FIXTURE_FILE.write_text(
                json.dumps(self._fixtures, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Sauvegarde impossible:\n{e}")

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self._fixtures))
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _undo(self):
        if not self._undo_stack:
            return
        self._fixtures = self._undo_stack.pop()
        self._save_fixtures()
        self._rebuild_list()

    # ── Packs de fixtures distants ────────────────────────────────────────────

    def _check_fixture_packs(self):
        """Lance la vérification des packs Firestore en arrière-plan (throttlée)."""
        state = load_packs_state()
        if not should_check_now(state):
            return

        id_token = None
        try:
            from license_manager import get_current_id_token
            id_token = get_current_id_token()
        except Exception:
            pass

        self._pack_check_worker = FixturePackCheckWorker(id_token)
        self._pack_check_thread = QThread()
        self._pack_check_worker.moveToThread(self._pack_check_thread)
        self._pack_check_thread.started.connect(self._pack_check_worker.run)
        self._pack_check_worker.found.connect(self._on_packs_found)
        self._pack_check_worker.found.connect(self._pack_check_thread.quit)
        self._pack_check_worker.no_update.connect(self._pack_check_thread.quit)
        self._pack_check_worker.error.connect(self._pack_check_thread.quit)
        self._pack_check_thread.start()

    def _on_packs_found(self, packs: list):
        """Affiche la bannière quand des packs sont disponibles."""
        if packs:
            self._pack_banner.set_packs(packs)

    def _open_pack_download(self, packs: list):
        """Ouvre le dialogue de téléchargement des packs."""
        id_token = None
        try:
            from license_manager import get_current_id_token
            id_token = get_current_id_token()
        except Exception:
            pass

        dlg = FixturePackDownloadDialog(packs, id_token, parent=self)
        dlg.download_complete.connect(self._on_packs_downloaded)
        self._pack_banner.hide()
        dlg.exec()

    def _on_packs_downloaded(self, total_new: int):
        """Recharge les fixtures après un téléchargement réussi."""
        if total_new > 0:
            self._load_fixtures()
            self._rebuild_mfr_list()
            self._rebuild_list()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(self._STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        menubar = QMenuBar()
        self._create_menu_bar(menubar)
        outer.addWidget(menubar)

        # ── Bannière packs distants (cachée par défaut) ───────────────────────
        self._pack_banner = FixturePackBanner(self)
        self._pack_banner.download_clicked.connect(self._open_pack_download)
        outer.addWidget(self._pack_banner)

        # ── Barre de recherche + bouton Nouvelle fixture ─────────────────────
        top_bar = QWidget()
        top_bar.setFixedHeight(52)
        top_bar.setStyleSheet("QWidget{background:#0d0d0d;border-bottom:1px solid #1a1a1a;}")
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(12, 8, 12, 8)
        tb_layout.setSpacing(10)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍  Rechercher fabricant ou fixture...")
        self._search_edit.setFixedHeight(32)
        self._search_edit.setStyleSheet(
            "QLineEdit{background:#1a1a1a;color:#ddd;border:1px solid #2a2a2a;"
            "border-radius:6px;padding:0 12px;font-size:12px;}"
            "QLineEdit:focus{border-color:#00d4ff55;}"
        )
        self._search_edit.textChanged.connect(self._on_search_changed)
        tb_layout.addWidget(self._search_edit, 1)

        btn_new = QPushButton("✦  Nouvelle fixture")
        btn_new.setFixedHeight(32)
        btn_new.setStyleSheet(
            "QPushButton{background:#1a3a2a;color:#44cc88;border:1px solid #44cc8844;"
            "border-radius:6px;font-size:12px;font-weight:bold;padding:0 14px;}"
            "QPushButton:hover{border-color:#44cc88;color:#66ee99;}"
        )
        btn_new.clicked.connect(self._new_fixture)
        tb_layout.addWidget(btn_new)
        outer.addWidget(top_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        outer.addWidget(splitter, 1)

        _LIST_SS = (
            "QListWidget{background:transparent;border:none;color:#aaa;"
            "font-size:12px;outline:none;}"
            "QListWidget::item{padding:7px 10px;border-radius:5px;margin:1px 0;}"
            "QListWidget::item:selected{background:#00d4ff18;color:#00d4ff;font-weight:bold;}"
            "QListWidget::item:hover:!selected{background:#1e1e1e;color:#ddd;}"
        )

        # ── Col 1 : Fabricants ───────────────────────────────────────────────
        mfr_panel = QWidget()
        mfr_panel.setMinimumWidth(140)
        mfr_panel.setStyleSheet("QWidget{background:#0d0d0d;border-right:1px solid #1a1a1a;}")
        mv = QVBoxLayout(mfr_panel)
        mv.setContentsMargins(8, 10, 8, 10)
        mv.setSpacing(0)

        self._mfr_list = QListWidget()
        self._mfr_list.setStyleSheet(_LIST_SS)
        self._mfr_list.currentItemChanged.connect(self._on_mfr_changed)
        mv.addWidget(self._mfr_list, 1)
        splitter.addWidget(mfr_panel)

        # ── Col 2 : Fixtures ─────────────────────────────────────────────────
        fix_panel = QWidget()
        fix_panel.setMinimumWidth(180)
        fix_panel.setStyleSheet("QWidget{background:#0d0d0d;border-right:1px solid #1a1a1a;}")
        fv2 = QVBoxLayout(fix_panel)
        fv2.setContentsMargins(8, 10, 8, 10)
        fv2.setSpacing(0)

        self._list_widget = QListWidget()
        self._list_widget.setStyleSheet(_LIST_SS)
        self._list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list_widget.setSpacing(1)
        self._list_widget.setMouseTracking(True)
        self._list_widget.viewport().setMouseTracking(True)
        self._list_widget.setItemDelegate(_FixtureItemDelegate(self._list_widget))
        fv2.addWidget(self._list_widget, 1)
        splitter.addWidget(fix_panel)

        # ── Col 3 : Édition ──────────────────────────────────────────────────
        right = QWidget()
        right.setStyleSheet("QWidget{background:#141414;}")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(20, 16, 20, 16)
        rv.setSpacing(10)

        hdr_row = QHBoxLayout()
        self._header_lbl = QLabel("Nouvelle fixture")
        self._header_lbl.setStyleSheet(
            "font-size:18px;font-weight:bold;color:#00d4ff;background:transparent;"
        )
        hdr_row.addWidget(self._header_lbl, 1)
        rv.addLayout(hdr_row)

        self._builtin_badge = QLabel("  ⚙  Fixture intégrée — Dupliquer pour créer votre version  ")
        self._builtin_badge.setStyleSheet(
            "QLabel{background:#001a10;color:#44aa66;border:1px solid #00d4ff22;"
            "border-radius:6px;padding:6px 12px;font-size:11px;}"
        )
        self._builtin_badge.setVisible(False)
        rv.addWidget(self._builtin_badge)

        _sep = lambda: self._make_sep()
        rv.addWidget(_sep())

        form_row = QHBoxLayout()
        form_row.setSpacing(16)

        def _labeled(lbl_txt, widget):
            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = QLabel(lbl_txt)
            lbl.setStyleSheet(
                "font-size:10px;color:#555;font-weight:bold;letter-spacing:1px;background:transparent;"
            )
            col.addWidget(lbl)
            col.addWidget(widget)
            return col

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Nom de la fixture...")
        self._name_edit.setFixedHeight(36)
        self._name_edit.textChanged.connect(lambda t: self._header_lbl.setText(t or "Nouvelle fixture"))
        form_row.addLayout(_labeled("NOM", self._name_edit), 2)

        self._manufacturer_edit = QLineEdit()
        self._manufacturer_edit.setPlaceholderText("Ex: Chauvet DJ, ADJ...")
        self._manufacturer_edit.setFixedHeight(36)
        form_row.addLayout(_labeled("FABRICANT", self._manufacturer_edit), 1)

        self._type_combo = _NoScrollCombo()
        self._type_combo.setFixedHeight(36)
        for ft in FIXTURE_TYPES:
            self._type_combo.addItem(ft)
        form_row.addLayout(_labeled("TYPE", self._type_combo), 1)
        rv.addLayout(form_row)

        rv.addWidget(_sep())

        ch_hdr = QHBoxLayout()
        ch_lbl = QLabel("CANAUX DMX")
        ch_lbl.setStyleSheet(
            "font-size:10px;color:#555;font-weight:bold;letter-spacing:1px;background:transparent;"
        )
        ch_hdr.addWidget(ch_lbl)
        ch_hdr.addStretch()
        self._add_ch_combo = _NoScrollCombo()
        self._add_ch_combo.setFixedHeight(30)
        self._add_ch_combo.setFixedWidth(110)
        for ct in ALL_CHANNEL_TYPES:
            self._add_ch_combo.addItem(ct)
        ch_hdr.addWidget(self._add_ch_combo)
        btn_add_ch = QPushButton("+ Canal")
        btn_add_ch.setFixedHeight(30)
        btn_add_ch.setStyleSheet(
            "QPushButton{background:#1a2a3a;color:#00d4ff;border:1px solid #00d4ff44;"
            "border-radius:6px;font-size:12px;padding:0 12px;}"
            "QPushButton:hover{border-color:#00d4ff;}"
        )
        btn_add_ch.clicked.connect(self._add_channel)
        ch_hdr.addWidget(btn_add_ch)
        rv.addLayout(ch_hdr)

        self._ch_scroll = QScrollArea()
        self._ch_scroll.setWidgetResizable(True)
        self._ch_scroll.setFixedHeight(180)
        self._ch_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._ch_container = QWidget()
        self._ch_container.setStyleSheet(
            "QWidget{background:#1e1e1e;border-radius:6px;border:1px solid #2a2a2a;}"
        )
        self._ch_vbox = QVBoxLayout(self._ch_container)
        self._ch_vbox.setContentsMargins(6, 6, 6, 6)
        self._ch_vbox.setSpacing(3)
        self._ch_vbox.addStretch()
        self._ch_scroll.setWidget(self._ch_container)
        rv.addWidget(self._ch_scroll)

        rv.addWidget(_sep())

        prev_lbl = QLabel("PRÉVISUALISATION")
        prev_lbl.setStyleSheet(
            "font-size:10px;color:#555;font-weight:bold;letter-spacing:1px;background:transparent;"
        )
        rv.addWidget(prev_lbl)

        self._preview = DmxPreviewWidget()
        self._preview.setStyleSheet("background:#1e1e1e;border-radius:6px;border:1px solid #2a2a2a;")
        rv.addWidget(self._preview)

        rv.addStretch()
        rv.addWidget(_sep())

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_duplicate = QPushButton("⎘  Dupliquer")
        self._btn_duplicate.setFixedHeight(36)
        self._btn_duplicate.setStyleSheet(
            "QPushButton{background:#1a1a2a;color:#8888cc;border:1px solid #33335555;"
            "border-radius:6px;font-size:12px;padding:0 14px;}"
            "QPushButton:hover{border-color:#8888cc;color:#aaaaee;}"
        )
        self._btn_duplicate.clicked.connect(self._duplicate_fixture)
        btn_row.addWidget(self._btn_duplicate)

        self._btn_delete = QPushButton("🗑  Supprimer")
        self._btn_delete.setFixedHeight(36)
        self._btn_delete.setEnabled(False)
        self._btn_delete.setStyleSheet(
            "QPushButton{background:#1a0808;color:#cc4444;border:1px solid #55111144;"
            "border-radius:6px;font-size:12px;padding:0 14px;}"
            "QPushButton:hover{border-color:#cc4444;color:#ff6666;}"
            "QPushButton:disabled{background:#141414;color:#333;border-color:#222;}"
        )
        self._btn_delete.clicked.connect(self._delete_fixture)
        btn_row.addWidget(self._btn_delete)

        btn_row.addStretch()

        self._btn_save = QPushButton("💾  Enregistrer")
        self._btn_save.setFixedHeight(36)
        self._btn_save.setStyleSheet(
            "QPushButton{background:#00d4ff;color:#000;border:none;"
            "border-radius:6px;font-size:13px;font-weight:bold;padding:0 20px;}"
            "QPushButton:hover{background:#33ddff;}"
            "QPushButton:disabled{background:#1a1a1a;color:#333;border:1px solid #2a2a2a;}"
        )
        self._btn_save.clicked.connect(self._save_current)
        btn_row.addWidget(self._btn_save)

        rv.addLayout(btn_row)
        splitter.addWidget(right)
        splitter.setSizes([155, 210, 700])

        self._list_widget.currentRowChanged.connect(self._on_list_selection)

    def _make_sep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#2a2a2a;")
        return sep

    def _create_menu_bar(self, menubar):
        menubar.setStyleSheet("""
            QMenuBar { background: #1a1a1a; color: #e0e0e0; border-bottom: 1px solid #2a2a2a; }
            QMenuBar::item { padding: 4px 10px; border-radius: 3px; }
            QMenuBar::item:selected { background: #2a2a2a; }
            QMenu { background: #1e1e1e; color: #e0e0e0; border: 1px solid #3a3a3a; }
            QMenu::item { padding: 6px 20px 6px 12px; }
            QMenu::item:selected { background: #00d4ff22; color: #00d4ff; }
            QMenu::separator { background: #2a2a2a; height: 1px; margin: 3px 8px; }
        """)
        m_file = menubar.addMenu("Fichier")
        act_import = m_file.addAction("📂  Importer des fixtures...")
        act_export = m_file.addAction("📤  Exporter la fixture...")
        m_file.addSeparator()
        act_reset = m_file.addAction("↺  Réinitialiser aux défauts")

        m_edit = menubar.addMenu("Edition")
        act_undo = m_edit.addAction("↩  Annuler\tCtrl+Z")
        act_undo.setShortcut(QKeySequence("Ctrl+Z"))

        act_import.triggered.connect(self._import_fixtures)
        act_export.triggered.connect(self._export_fixture)
        act_reset.triggered.connect(self._reset_to_defaults)
        act_undo.triggered.connect(self._undo)

    # ── List management ───────────────────────────────────────────────────────

    def _on_search_changed(self, text):
        self._rebuild_mfr_list()
        self._rebuild_list()

    def _on_mfr_changed(self, current, previous):
        self._rebuild_list()

    def _rebuild_mfr_list(self):
        """Peuple la colonne Fabricants depuis les fixtures + OFL si recherche active."""
        if not hasattr(self, '_mfr_list'):
            return
        query = self._search_edit.text().strip().lower() if hasattr(self, '_search_edit') else ""

        cur_item = self._mfr_list.currentItem()
        cur_mfr = cur_item.data(Qt.UserRole) if cur_item else None

        self._mfr_list.blockSignals(True)
        self._mfr_list.clear()

        mfr_counts: dict[str, int] = {}
        for fx in self._all_fixtures():
            mfr = fx.get("manufacturer") or "Générique"
            name = fx.get("name", "")
            if query and query not in name.lower() and query not in mfr.lower():
                continue
            mfr_counts[mfr] = mfr_counts.get(mfr, 0) + 1

        sorted_mfrs = []
        if "Générique" in mfr_counts:
            sorted_mfrs.append("Générique")
        for m in sorted(mfr_counts):
            if m != "Générique":
                sorted_mfrs.append(m)

        for mfr in sorted_mfrs:
            item = QListWidgetItem(mfr)
            item.setData(Qt.UserRole, mfr)
            self._mfr_list.addItem(item)

        if query:
            bundle_matches = [
                fx for fx in _load_bundle()
                if query in fx["name"].lower() or query in fx["manufacturer"].lower()
            ]
            if bundle_matches:
                ofl_item = QListWidgetItem(f"OFL  ({min(len(bundle_matches), 150)})")
                ofl_item.setData(Qt.UserRole, "__ofl__")
                ofl_item.setForeground(QColor("#4488aa"))
                self._mfr_list.addItem(ofl_item)

        self._mfr_list.blockSignals(False)

        # Restore selection
        for i in range(self._mfr_list.count()):
            item = self._mfr_list.item(i)
            if item and item.data(Qt.UserRole) == cur_mfr:
                self._mfr_list.blockSignals(True)
                self._mfr_list.setCurrentRow(i)
                self._mfr_list.blockSignals(False)
                return
        self._mfr_list.blockSignals(True)
        self._mfr_list.setCurrentRow(0)
        self._mfr_list.blockSignals(False)

    def _rebuild_list(self):
        query = self._search_edit.text().strip().lower() if hasattr(self, '_search_edit') else ""

        cur_mfr_item = self._mfr_list.currentItem() if hasattr(self, '_mfr_list') else None
        mfr_filter = cur_mfr_item.data(Qt.UserRole) if cur_mfr_item else None

        self._list_widget.blockSignals(True)
        self._list_widget.clear()

        if mfr_filter == "__ofl__":
            # Afficher les résultats OFL bundle uniquement
            bundle_matches = [
                fx for fx in _load_bundle()
                if not query or query in fx["name"].lower() or query in fx["manufacturer"].lower()
            ][:150]
            for bfx in bundle_matches:
                bname  = bfx.get("name", "")
                bmfr   = bfx.get("manufacturer", "")
                bftype = bfx.get("fixture_type", "")
                bn_ch  = len(bfx.get("profile", []))
                bitem  = QListWidgetItem(bname)
                bitem.setData(_BUNDLE_ROLE, bfx)
                bitem.setData(_SUB_ROLE, f"{bftype}  ·  {bn_ch} ch  ·  {bmfr}")
                bitem.setForeground(QColor("#4488aa"))
                bitem.setToolTip(f"{bmfr} — {bname}\n{bftype} · {bn_ch} canaux")
                self._list_widget.addItem(bitem)
        else:
            # Trier : Générique en tête, builtin ensuite, custom en dernier
            all_fx = self._all_fixtures()
            def _sort_key(pair):
                _, fx = pair
                if not isinstance(fx, dict):
                    return (3, "")
                mfr = fx.get("manufacturer", "")
                is_builtin = fx.get("builtin", False)
                if mfr.lower() == "générique":
                    return (0, fx.get("name", ""))
                if is_builtin:
                    return (1, fx.get("name", ""))
                return (2, fx.get("name", ""))
            ordered = sorted(enumerate(all_fx), key=_sort_key)
            for i, fx in ordered:
                name = fx.get("name", "")
                mfr  = fx.get("manufacturer") or "Générique"
                if query and query not in name.lower() and query not in mfr.lower():
                    continue
                if mfr_filter is not None and mfr != mfr_filter:
                    continue
                is_builtin = fx.get("builtin", False)
                ftype  = fx.get("fixture_type", "")
                n_ch   = len(fx.get("profile", []))
                item   = QListWidgetItem(name)
                item.setData(Qt.UserRole, i)
                item.setData(_SUB_ROLE, f"{ftype}  ·  {n_ch} ch")
                item.setForeground(QColor("#777" if is_builtin else "#dddddd"))
                item.setToolTip(f"{mfr} — {name}\n{ftype} · {n_ch} canaux")
                self._list_widget.addItem(item)

            if not query and mfr_filter is None:
                hint = QListWidgetItem("  🔍  Tapez pour chercher dans la bibliothèque OFL")
                hint.setFlags(Qt.NoItemFlags)
                hint.setForeground(QColor("#2a2a2a"))
                self._list_widget.addItem(hint)

        self._list_widget.blockSignals(False)
        if self._current_idx >= 0:
            self._select_list_item(self._current_idx)

    def _on_list_selection(self, row):
        item = self._list_widget.item(row)
        if item is None:
            return
        bundle_fx = item.data(_BUNDLE_ROLE)
        if bundle_fx is not None:
            self._select_bundle_fixture(bundle_fx)
            return
        idx = item.data(Qt.UserRole)
        if idx is None:
            return
        self._select_fixture(idx)

    def _select_bundle_fixture(self, fx: dict):
        """Affiche une fixture OFL (lecture seule) dans le formulaire."""
        self._current_idx = -1
        self._is_builtin  = True

        self._name_edit.blockSignals(True)
        self._name_edit.setText(fx.get("name", ""))
        self._name_edit.blockSignals(False)
        self._header_lbl.setText(fx.get("name", ""))

        self._manufacturer_edit.setText(fx.get("manufacturer", ""))
        fi = self._type_combo.findText(fx.get("fixture_type", "PAR LED"))
        if fi >= 0:
            self._type_combo.setCurrentIndex(fi)

        self._set_channels(fx.get("profile", []))

        self._builtin_badge.setVisible(True)
        self._btn_delete.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._btn_save.setToolTip("Fixture OFL — utilisez « Dupliquer » pour créer votre propre version.")
        self._btn_save.setCursor(Qt.ForbiddenCursor)
        self._manufacturer_edit.setReadOnly(True)
        if self._btn_add_to_patch:
            self._btn_add_to_patch.setEnabled(True)

    def _select_fixture(self, idx):
        all_fx = self._all_fixtures()
        if idx < 0 or idx >= len(all_fx):
            return
        fx = all_fx[idx]
        self._current_idx = idx
        self._is_builtin  = fx.get("builtin", False)

        self._name_edit.blockSignals(True)
        self._name_edit.setText(fx.get("name", ""))
        self._name_edit.blockSignals(False)
        self._header_lbl.setText(fx.get("name", ""))

        self._manufacturer_edit.setText(fx.get("manufacturer", ""))

        fi = self._type_combo.findText(fx.get("fixture_type", "PAR LED"))
        if fi >= 0:
            self._type_combo.setCurrentIndex(fi)

        self._set_channels(fx.get("profile", ["R", "G", "B"]))

        self._builtin_badge.setVisible(self._is_builtin)
        self._btn_delete.setEnabled(not self._is_builtin)
        self._btn_save.setEnabled(not self._is_builtin)
        self._btn_save.setToolTip(
            "Cette fixture est intégrée et ne peut pas être modifiée.\n"
            "Utilisez « Dupliquer » pour créer votre propre version."
            if self._is_builtin else ""
        )
        self._btn_save.setCursor(
            Qt.ForbiddenCursor if self._is_builtin else Qt.ArrowCursor
        )
        self._manufacturer_edit.setReadOnly(self._is_builtin)
        self._select_list_item(idx)

    def _select_list_item(self, fx_idx):
        # Sélectionner le bon fabricant dans la colonne gauche
        if hasattr(self, '_mfr_list') and fx_idx >= 0:
            all_fx = self._all_fixtures()
            if fx_idx < len(all_fx):
                mfr = all_fx[fx_idx].get("manufacturer") or "Générique"
                for i in range(self._mfr_list.count()):
                    mi = self._mfr_list.item(i)
                    if mi and mi.data(Qt.UserRole) == mfr:
                        if self._mfr_list.currentItem() is not mi:
                            self._mfr_list.blockSignals(True)
                            self._mfr_list.setCurrentRow(i)
                            self._mfr_list.blockSignals(False)
                            self._rebuild_list()
                        break
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item and item.data(Qt.UserRole) == fx_idx:
                self._list_widget.blockSignals(True)
                self._list_widget.setCurrentRow(i)
                self._list_widget.blockSignals(False)
                self._list_widget.scrollToItem(item)
                return

    # ── Channel rows ─────────────────────────────────────────────────────────

    def _set_channels(self, channels):
        for row in self._channel_rows:
            self._ch_vbox.removeWidget(row)
            row.deleteLater()
        self._channel_rows.clear()
        for i, ch in enumerate(channels):
            self._append_channel_row(i + 1, ch)
        self._update_preview()

    def _append_channel_row(self, num, ch_type):
        row = ChannelRowWidget(num, ch_type)
        row.remove_requested.connect(self._remove_channel_row)
        row.move_up_requested.connect(self._move_channel_up)
        row.move_dn_requested.connect(self._move_channel_dn)
        row.changed.connect(lambda row=row: self._on_channel_type_changed(row))
        self._ch_vbox.insertWidget(self._ch_vbox.count() - 1, row)
        self._channel_rows.append(row)

    def _remove_channel_row(self, row):
        if row in self._channel_rows:
            self._channel_rows.remove(row)
            self._ch_vbox.removeWidget(row)
            row.deleteLater()
            self._renumber_rows()
            self._update_preview()

    def _move_channel_up(self, row):
        idx = self._channel_rows.index(row) if row in self._channel_rows else -1
        if idx <= 0:
            return
        self._channel_rows[idx], self._channel_rows[idx - 1] = self._channel_rows[idx - 1], self._channel_rows[idx]
        self._ch_vbox.removeWidget(row)
        self._ch_vbox.insertWidget(idx - 1, row)
        self._renumber_rows()
        self._update_preview()

    def _move_channel_dn(self, row):
        idx = self._channel_rows.index(row) if row in self._channel_rows else -1
        if idx < 0 or idx >= len(self._channel_rows) - 1:
            return
        self._channel_rows[idx], self._channel_rows[idx + 1] = self._channel_rows[idx + 1], self._channel_rows[idx]
        self._ch_vbox.removeWidget(row)
        self._ch_vbox.insertWidget(idx + 1, row)
        self._renumber_rows()
        self._update_preview()

    def _renumber_rows(self):
        for i, row in enumerate(self._channel_rows):
            row.set_num(i + 1)

    def _on_channel_type_changed(self, row):
        """Validation : refuse un doublon de type (sauf Mode)."""
        new_type = row.get_type()
        if new_type != "Mode":
            for other in self._channel_rows:
                if other is not row and other.get_type() == new_type:
                    row.set_type(row._prev_type)
                    return
        row._prev_type = new_type
        self._update_preview()

    def _add_channel(self):
        ch_type = self._add_ch_combo.currentText()
        if ch_type != "Mode":
            used = [r.get_type() for r in self._channel_rows]
            if ch_type in used:
                QMessageBox.warning(self, "Canal dupliqué",
                    f"Le canal «{ch_type}» est déjà présent dans ce profil.")
                return
        self._append_channel_row(len(self._channel_rows) + 1, ch_type)
        self._update_preview()
        self._ch_scroll.verticalScrollBar().setValue(
            self._ch_scroll.verticalScrollBar().maximum()
        )

    def _get_current_channels(self):
        return [row.get_type() for row in self._channel_rows]

    def _update_preview(self):
        channels = self._get_current_channels()
        self._preview.set_channels(channels)

    # ── Form data ─────────────────────────────────────────────────────────────

    def _get_form_data(self):
        return {
            "name":         self._name_edit.text().strip(),
            "manufacturer": self._manufacturer_edit.text().strip() or "Générique",
            "fixture_type": self._type_combo.currentText(),
            "group":        "face",
            "profile":      self._get_current_channels(),
        }

    # ── CRUD actions ──────────────────────────────────────────────────────────

    def _new_fixture(self):
        self._current_idx = -1
        self._is_builtin  = False
        self._name_edit.blockSignals(True)
        self._name_edit.setText("")
        self._name_edit.blockSignals(False)
        self._manufacturer_edit.setText("")
        self._header_lbl.setText("Nouvelle fixture")
        self._type_combo.setCurrentIndex(0)
        self._set_channels(["R", "G", "B"])
        self._builtin_badge.setVisible(False)
        self._btn_delete.setEnabled(False)
        self._btn_save.setEnabled(True)
        self._btn_save.setToolTip("")
        self._btn_save.setCursor(Qt.ArrowCursor)
        self._list_widget.blockSignals(True)
        self._list_widget.clearSelection()
        self._list_widget.blockSignals(False)
        self._name_edit.setFocus()

    def _save_current(self):
        data = self._get_form_data()
        if not data["name"]:
            QMessageBox.warning(self, "Nom requis", "Veuillez entrer un nom pour la fixture.")
            self._name_edit.setFocus()
            return
        if not data["profile"]:
            QMessageBox.warning(self, "Canaux requis", "Ajoutez au moins un canal DMX.")
            return
        self._push_undo()
        all_fx = self._all_fixtures()
        if (self._current_idx >= 0 and self._current_idx < len(all_fx)
                and not all_fx[self._current_idx].get("builtin")):
            custom_idx = self._current_idx - len(BUILTIN_FIXTURES)
            if 0 <= custom_idx < len(self._fixtures):
                self._fixtures[custom_idx] = data
        else:
            existing_names = {f["name"] for f in self._fixtures}
            name = data["name"]
            if name in existing_names:
                c = 2
                while f"{name} ({c})" in existing_names:
                    c += 1
                data["name"] = f"{name} ({c})"
                self._name_edit.setText(data["name"])
            self._fixtures.append(data)
            self._current_idx = len(BUILTIN_FIXTURES) + len(self._fixtures) - 1
        self._save_fixtures()
        self._rebuild_list()
        self._select_fixture(self._current_idx)
        self._btn_delete.setEnabled(True)

    def _duplicate_fixture(self):
        data = self._get_form_data()
        name = data["name"] or "Fixture"
        data["name"] = name + " (copie)"
        self._push_undo()
        self._fixtures.append(data)
        self._save_fixtures()
        self._current_idx = len(BUILTIN_FIXTURES) + len(self._fixtures) - 1
        self._is_builtin  = False
        self._rebuild_list()
        self._builtin_badge.setVisible(False)
        self._btn_delete.setEnabled(True)
        self._btn_save.setEnabled(True)
        self._name_edit.setText(data["name"])
        self._header_lbl.setText(data["name"])

    def _delete_fixture(self):
        if self._is_builtin:
            return
        name = self._name_edit.text().strip() or "cette fixture"
        if QMessageBox.question(
            self, "Supprimer",
            f"Supprimer la fixture « {name} » ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        all_fx = self._all_fixtures()
        if 0 <= self._current_idx < len(all_fx):
            custom_idx = self._current_idx - len(BUILTIN_FIXTURES)
            if 0 <= custom_idx < len(self._fixtures):
                self._push_undo()
                self._fixtures.pop(custom_idx)
                self._save_fixtures()
                self._current_idx = -1
                self._rebuild_list()
                self._new_fixture()

    def _add_to_patch(self):
        data = self._get_form_data()
        if not data["name"]:
            QMessageBox.warning(self, "Nom requis", "Entrez un nom pour la fixture.")
            return
        if not data["profile"]:
            QMessageBox.warning(self, "Canaux requis", "Ajoutez au moins un canal DMX.")
            return
        self.fixture_added.emit(data)
        self._btn_add_to_patch.setText("✓  Ajouté !")
        self._btn_add_to_patch.setEnabled(False)
        QTimer.singleShot(1400, self._reset_add_btn)

    def _reset_add_btn(self):
        if self._btn_add_to_patch:
            self._btn_add_to_patch.setText("⊕  Ajouter au patch")
            self._btn_add_to_patch.setEnabled(True)

    # ── Import / Export ───────────────────────────────────────────────────────

    def _import_fixtures(self):
        from fixture_parser import parse_file
        from PySide6.QtWidgets import QInputDialog

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importer des fixtures", str(Path.home()),
            "Tous les formats supportés (*.mft *.json *.xml *.mystrow);;"
            "Fixture MyStrow (*.mft *.json *.mystrow);;"
            "GrandMA2/3 XML (*.xml)"
        )
        if not paths:
            return

        _GROUP = {"Moving Head": "lyre", "Barre LED": "barre",
                  "Stroboscope": "strobe", "Machine a fumee": "fumee"}

        self._push_undo()
        existing = {f["name"] for f in self._fixtures}
        imported = 0
        errors = []

        for path in paths:
            ext = Path(path).suffix.lower()
            try:
                raw = Path(path).read_bytes()

                if ext == ".xml":
                    # ── Fichier GrandMA2/3 XML ────────────────────────────────
                    ofl_fx = parse_file(path)
                    modes = [m for m in (ofl_fx.get("modes") or [])
                             if isinstance(m, dict) and m.get("profile")]
                    if not modes:
                        raise ValueError("Aucun canal DMX trouvé dans ce fichier XML.")
                    ftype = ofl_fx.get("fixture_type", "PAR LED")
                    candidates = [{
                        "name":         ofl_fx.get("name", Path(path).stem)
                                        + (f" — {m['name']}" if len(modes) > 1 else ""),
                        "manufacturer": ofl_fx.get("manufacturer", ""),
                        "fixture_type": ftype,
                        "group":        _GROUP.get(ftype, "face"),
                        "profile":      m["profile"],
                        "source":       ofl_fx.get("source", "ma"),
                    } for m in modes]
                    if len(candidates) > 1:
                        mode_names = [c["name"] for c in candidates]
                        choice, ok = QInputDialog.getItem(
                            self, "Choisir un mode",
                            f"{ofl_fx.get('name')} — {len(candidates)} modes.\nMode à importer :",
                            mode_names, 0, False
                        )
                        if not ok:
                            continue
                        to_add = [candidates[mode_names.index(choice)]]
                    else:
                        to_add = candidates

                else:
                    # ── Fichier JSON / mystrow / mft ──────────────────────────
                    parsed = json.loads(raw.decode("utf-8"))
                    to_add = [parsed] if isinstance(parsed, dict) else parsed
                    if not isinstance(to_add, list):
                        raise ValueError("Format invalide (liste de fixtures attendue).")
                    to_add = [f for f in to_add if isinstance(f, dict)]

                for fx in to_add:
                    if not isinstance(fx, dict):
                        continue
                    if not fx.get("name") or not fx.get("profile"):
                        continue
                    fx.pop("builtin", None)
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

        self._save_fixtures()
        self._rebuild_list()

        msg = f"{imported} fixture(s) importée(s)."
        if errors:
            msg += f"\n\n{len(errors)} fichier(s) ignoré(s) :\n" + "\n".join(errors)
            QMessageBox.warning(self, "Import partiel", msg)
        else:
            QMessageBox.information(self, "Import réussi", msg)

    def _export_fixture(self):
        data = self._get_form_data()
        if not data["name"]:
            QMessageBox.warning(self, "Rien à exporter", "Sélectionnez ou créez une fixture d'abord.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter la fixture",
            str(Path.home() / f"{data['name']}.mft"),
            "Fixture MyStrow (*.mft)"
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Export réussi", f"Fixture exportée :\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Erreur d'export", f"Impossible d'exporter:\n{e}")

    def _reset_to_defaults(self):
        if QMessageBox.question(
            self, "Réinitialiser",
            "Supprimer toutes les fixtures personnalisées et revenir aux défauts ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self._push_undo()
        self._fixtures = []
        self._save_fixtures()
        self._current_idx = -1
        self._rebuild_list()
        if BUILTIN_FIXTURES:
            self._select_fixture(0)

    def _open_ofl_browser(self):
        dlg = OflBrowserDialog(self)
        dlg.fixture_selected.connect(self._import_from_ofl)
        dlg.exec()

    def _import_from_ofl(self, fx: dict):
        """Reçoit une fixture depuis le browser OFL et l'ajoute aux customs."""
        fx.pop("builtin", None)
        self._push_undo()
        existing = {f["name"] for f in self._fixtures}
        name = fx.get("name", "Fixture OFL")
        if name in existing:
            c = 2
            while f"{name} ({c})" in existing:
                c += 1
            fx["name"] = f"{name} ({c})"
        self._fixtures.append(fx)
        self._save_fixtures()
        self._current_idx = len(BUILTIN_FIXTURES) + len(self._fixtures) - 1
        self._is_builtin = False
        self._rebuild_list()
        self._select_fixture(self._current_idx)
        self._btn_delete.setEnabled(True)


# ──────────────────────────────────────────────────────────────────────────────
# OflFetchWorker — thread de chargement Firebase
# ──────────────────────────────────────────────────────────────────────────────

class _OflFetchWorker(QObject):
    finished = Signal(list, object)  # (fixtures, next_cursor)
    error    = Signal(str)

    def __init__(self, id_token, fixture_type, cursor):
        super().__init__()
        self._id_token    = id_token
        self._fixture_type = fixture_type
        self._cursor      = cursor  # None ou {"manufacturer": ..., "name": ...}

    def run(self):
        try:
            import firebase_client as fc
            kw = {}
            if self._cursor:
                kw["cursor_manufacturer"] = self._cursor["manufacturer"]
                kw["cursor_name"]         = self._cursor["name"]
            result = fc.fetch_gdtf_fixtures(
                self._id_token,
                fixture_type=self._fixture_type,
                page_size=100,
                **kw,
            )
            self.finished.emit(result["fixtures"], result["next_cursor"])
        except Exception as exc:
            self.error.emit(str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# OflBrowserDialog — navigateur de la bibliothèque OFL Firebase
# ──────────────────────────────────────────────────────────────────────────────

class OflBrowserDialog(QDialog):
    """Dialogue de navigation / import de la bibliothèque OFL Firebase."""
    fixture_selected = Signal(dict)  # dict fixture prêt à importer

    _STYLE = """
        QDialog      { background: #141414; color: #e0e0e0; }
        QLabel        { color: #e0e0e0; }
        QLineEdit     { background: #222; color: #e0e0e0; border: 1px solid #3a3a3a;
                        border-radius: 4px; padding: 5px 8px; font-size: 13px; }
        QLineEdit:focus { border: 1px solid #00d4ff; }
        QComboBox     { background: #222; color: #e0e0e0; border: 1px solid #3a3a3a;
                        border-radius: 4px; padding: 4px 8px; font-size: 12px; }
        QComboBox::drop-down { border: none; width: 20px; }
        QComboBox QAbstractItemView { background: #222; color: #e0e0e0;
                        selection-background-color: #00d4ff33; }
        QListWidget   { background: #1a1a1a; color: #e0e0e0; border: 1px solid #2a2a2a;
                        border-radius: 4px; outline: none; }
        QListWidget::item { padding: 5px 10px; border-radius: 3px; }
        QListWidget::item:selected { background: #00d4ff22; color: #00d4ff; }
        QListWidget::item:hover { background: #2a2a2a; }
        QPushButton   { background: #1e2a3a; color: #00d4ff; border: 1px solid #00d4ff44;
                        border-radius: 4px; font-size: 12px; padding: 5px 14px; }
        QPushButton:hover  { background: #1e3a4a; border-color: #00d4ff; }
        QPushButton:disabled { background: #1a1a1a; color: #444; border-color: #2a2a2a; }
        QProgressBar  { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 4px;
                        height: 6px; text-align: center; }
        QProgressBar::chunk { background: #00d4ff; border-radius: 4px; }
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Bibliothèque OFL — MyStrow")
        self.setMinimumSize(720, 560)
        self.resize(820, 620)
        self.setStyleSheet(self._STYLE)

        self._all_loaded: list = []   # toutes les fixtures chargées pour le type courant
        self._next_cursor = None       # curseur Firestore pour la page suivante
        self._id_token    = None
        self._thread      = None
        self._worker      = None
        self._selected_fx = None       # fixture OFL actuellement sélectionnée

        self._build_ui()
        self._load_token()

    # ── Token ──────────────────────────────────────────────────────────────

    def _load_token(self):
        try:
            from license_manager import get_current_id_token
            self._id_token = get_current_id_token()
        except Exception:
            self._id_token = None

        if not self._id_token:
            self._status_lbl.setText(
                "⚠  Connexion requise — connectez-vous avec votre compte MyStrow pour accéder à la bibliothèque."
            )
            self._btn_search.setEnabled(False)

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        # Titre
        title = QLabel("🌐  Bibliothèque de fixtures OFL")
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#00d4ff;")
        outer.addWidget(title)

        sub = QLabel("Parcourez les milliers de profils récupérés depuis Open Fixture Library.")
        sub.setStyleSheet("font-size:11px;color:#666;")
        outer.addWidget(sub)

        # Barre de filtres
        flt = QHBoxLayout()
        flt.setSpacing(8)

        self._type_combo = _NoScrollCombo()
        self._type_combo.addItem("Tous les types", "")
        for ft in FIXTURE_TYPES:
            self._type_combo.addItem(ft, ft)
        self._type_combo.setFixedHeight(32)
        flt.addWidget(QLabel("Type :"))
        flt.addWidget(self._type_combo)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filtrer par nom ou fabricant…")
        self._search_edit.setFixedHeight(32)
        self._search_edit.textChanged.connect(self._apply_filter)
        flt.addWidget(self._search_edit, 1)

        self._btn_search = QPushButton("Charger")
        self._btn_search.setFixedHeight(32)
        self._btn_search.clicked.connect(self._do_search)
        flt.addWidget(self._btn_search)

        outer.addLayout(flt)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(6)
        self._progress.setVisible(False)
        outer.addWidget(self._progress)

        # Status
        self._status_lbl = QLabel("Choisissez un type et cliquez sur Charger.")
        self._status_lbl.setStyleSheet("font-size:11px;color:#666;")
        outer.addWidget(self._status_lbl)

        # Liste résultats
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.currentItemChanged.connect(self._on_item_changed)
        outer.addWidget(self._list, 1)

        # Charger plus
        self._btn_more = QPushButton("Charger 100 de plus…")
        self._btn_more.setVisible(False)
        self._btn_more.clicked.connect(self._load_more)
        outer.addWidget(self._btn_more)

        # Panneau de sélection du mode
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(QLabel("Mode DMX :"))
        self._mode_combo = _NoScrollCombo()
        self._mode_combo.setFixedHeight(30)
        self._mode_combo.setEnabled(False)
        mode_row.addWidget(self._mode_combo, 1)
        mode_row.addWidget(QLabel("Groupe :"))
        self._group_combo = _NoScrollCombo()
        for g in GROUP_OPTIONS:
            self._group_combo.addItem(g)
        self._group_combo.setFixedHeight(30)
        self._group_combo.setEnabled(False)
        mode_row.addWidget(self._group_combo)
        outer.addLayout(mode_row)

        # Boutons bas
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_import = QPushButton("⊕  Importer dans mes fixtures")
        self._btn_import.setFixedHeight(36)
        self._btn_import.setEnabled(False)
        self._btn_import.setStyleSheet(
            "QPushButton{background:#1a3a1a;color:#44cc44;border:1px solid #2a6a2a;"
            "border-radius:4px;font-size:12px;font-weight:bold;padding:0 16px;}"
            "QPushButton:hover{background:#2a4a2a;border-color:#44aa44;}"
            "QPushButton:disabled{background:#1a1a1a;color:#444;border-color:#2a2a2a;}"
        )
        self._btn_import.clicked.connect(self._do_import)
        btn_row.addWidget(self._btn_import)

        btn_close = QPushButton("Fermer")
        btn_close.setFixedHeight(36)
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        outer.addLayout(btn_row)

    # ── Chargement Firebase ────────────────────────────────────────────────

    def _do_search(self):
        """Lance un nouveau chargement (réinitialise la liste)."""
        self._all_loaded.clear()
        self._next_cursor = None
        self._list.clear()
        self._selected_fx = None
        self._btn_import.setEnabled(False)
        self._mode_combo.clear()
        self._mode_combo.setEnabled(False)
        self._group_combo.setEnabled(False)
        self._btn_more.setVisible(False)
        self._load_page()

    def _load_more(self):
        self._load_page(cursor=self._next_cursor)

    def _load_page(self, cursor=None):
        if not self._id_token:
            return
        if self._thread and self._thread.isRunning():
            return

        fixture_type = self._type_combo.currentData()
        self._progress.setVisible(True)
        self._btn_search.setEnabled(False)
        self._btn_more.setVisible(False)
        self._status_lbl.setText("Chargement en cours…")

        self._worker = _OflFetchWorker(self._id_token, fixture_type, cursor)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_fetch_done)
        self._worker.error.connect(self._on_fetch_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_fetch_done(self, fixtures: list, next_cursor):
        self._progress.setVisible(False)
        self._btn_search.setEnabled(True)

        self._all_loaded.extend(fixtures)
        self._next_cursor = next_cursor

        self._apply_filter()

        total = len(self._all_loaded)
        self._status_lbl.setText(f"{total} fixture(s) chargée(s).")

        if next_cursor:
            self._btn_more.setText(f"Charger 100 de plus… (total actuel : {total})")
            self._btn_more.setVisible(True)

    def _on_fetch_error(self, msg: str):
        self._progress.setVisible(False)
        self._btn_search.setEnabled(True)
        self._status_lbl.setText(f"Erreur : {msg}")

    # ── Filtrage local ──────────────────────────────────────────────────────

    def _apply_filter(self):
        query = self._search_edit.text().strip().lower()
        self._list.blockSignals(True)
        self._list.clear()

        current_mfr = None
        for fx in self._all_loaded:
            name = fx.get("name", "")
            mfr  = fx.get("manufacturer", "")
            if query and query not in name.lower() and query not in mfr.lower():
                continue
            if mfr != current_mfr:
                current_mfr = mfr
                hdr = QListWidgetItem(f"  {mfr.upper()}")
                hdr.setFlags(Qt.NoItemFlags)
                hdr.setForeground(QColor("#555"))
                f = hdr.font(); f.setPointSize(8); hdr.setFont(f)
                hdr.setBackground(QColor("#111"))
                self._list.addItem(hdr)

            modes = fx.get("modes", [])
            mode_info = ""
            if modes:
                counts = " / ".join(f"{m.get('channelCount', len(m.get('profile', [])))}ch" for m in modes[:3])
                mode_info = f" [{fx.get('fixture_type', '?')} · {counts}]"
            item = QListWidgetItem(f"    {name}{mode_info}")
            item.setData(Qt.UserRole, fx)
            item.setForeground(QColor("#cccccc"))
            self._list.addItem(item)

        self._list.blockSignals(False)

    # ── Sélection / Import ─────────────────────────────────────────────────

    def _on_item_changed(self, item):
        if item is None:
            self._selected_fx = None
            self._btn_import.setEnabled(False)
            self._mode_combo.setEnabled(False)
            self._group_combo.setEnabled(False)
            return
        fx = item.data(Qt.UserRole)
        if not fx:
            self._selected_fx = None
            self._btn_import.setEnabled(False)
            return
        self._selected_fx = fx
        self._btn_import.setEnabled(True)

        # Remplir le combo de modes
        self._mode_combo.blockSignals(True)
        self._mode_combo.clear()
        modes = fx.get("modes", [])
        for m in modes:
            n_ch = m.get("channelCount") or len(m.get("profile", []))
            self._mode_combo.addItem(f"{m.get('name', 'Mode')} — {n_ch} canaux", m)
        self._mode_combo.blockSignals(False)
        self._mode_combo.setEnabled(bool(modes))

        # Groupe par défaut selon type
        ftype = fx.get("fixture_type", "PAR LED")
        default_group = {
            "Moving Head": "lyre",
            "Barre LED":   "barre",
            "Stroboscope": "strobe",
            "Machine a fumee": "fumee",
        }.get(ftype, "face")
        idx = GROUP_OPTIONS.index(default_group) if default_group in GROUP_OPTIONS else 0
        self._group_combo.setCurrentIndex(idx)
        self._group_combo.setEnabled(True)

    def _do_import(self):
        if not self._selected_fx:
            return
        fx = self._selected_fx
        mode_data = self._mode_combo.currentData()
        if not mode_data:
            modes = fx.get("modes", [])
            mode_data = modes[0] if modes else {"name": "Mode 1", "profile": []}

        profile = mode_data.get("profile", [])
        group   = self._group_combo.currentText()
        ftype   = fx.get("fixture_type", "PAR LED")

        # Construire le dict custom fixture (format fixture_editor)
        custom = {
            "name":         fx.get("name", "Fixture OFL"),
            "manufacturer": fx.get("manufacturer", ""),
            "fixture_type": ftype,
            "group":        group,
            "profile":      profile,
        }
        self.fixture_selected.emit(custom)

        # Feedback visuel
        self._btn_import.setText("✓  Importé !")
        self._btn_import.setEnabled(False)
        QTimer.singleShot(1200, self._reset_import_btn)

    def _reset_import_btn(self):
        self._btn_import.setText("⊕  Importer dans mes fixtures")
        self._btn_import.setEnabled(self._selected_fx is not None)
