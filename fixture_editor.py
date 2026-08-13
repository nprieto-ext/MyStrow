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
    QSizePolicy, QSplitter, QMenu,
    QGridLayout, QSpinBox, QCheckBox, QCompleter,
)
from PySide6.QtCore import (
    Qt, Signal, QTimer, QThread, QRectF,
    QStringListModel, QEvent,
)

from core import channel_label, ComboSansMolette
from PySide6.QtGui import QColor, QPainter, QPen, QFont

import gzip

from builtin_fixtures import BUILTIN_FIXTURES
from i18n import tr
from fixture_packs import (
    FixturePackBanner, FixturePackDownloadDialog,
    FixturePackCheckWorker, load_packs_state, should_check_now,
)

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

FIXTURE_TYPES = ["PAR LED", "Moving Head", "Barre LED", "Stroboscope", "Machine a fumee", "Gradateur"]

GROUP_OPTIONS = [
    "face", "douche1", "douche2", "douche3", "lat", "contre",
    "groupe_g", "groupe_h", "fumee",
]

ALL_CHANNEL_TYPES = [
    "R", "G", "B", "W", "Dim", "Dim2", "Strobe", "UV", "Ambre", "Orange", "Zoom",
    "Smoke", "Fan", "Pan", "PanFine", "Tilt", "TiltFine",
    "Gobo1", "Gobo1Rot", "Gobo2", "Prism", "PrismRot", "Focus", "ColorWheel", "Shutter", "Speed", "Mode",
    "Effects", "Reset",
]

CHANNEL_COLORS = {
    "R": "#cc2200", "G": "#00aa00", "B": "#0055ff", "W": "#bbbbbb",
    "Dim": "#888800", "Dim2": "#aaaa00", "Strobe": "#ffaa00", "UV": "#8800cc",
    "Ambre": "#ee6600", "Orange": "#ff4400", "Zoom": "#00ccaa",
    "Smoke": "#555555", "Fan": "#336699", "Pan": "#ff55aa",
    "PanFine": "#cc4488", "Tilt": "#00ddff", "TiltFine": "#00aacc",
    "Gobo1": "#aa8800", "Gobo1Rot": "#cc9900", "Gobo2": "#886600",
    "Prism": "#dd00dd", "PrismRot": "#bb00bb",
    "Focus": "#00aa88", "ColorWheel": "#ff8800", "Shutter": "#ff2266",
    "Speed": "#66ff66", "Mode": "#88aaff", "Effects": "#cc44ff", "Reset": "#ff3333",
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
    "Gradateur": [
        ("Dim 1ch",       ["Dim"]),
        ("Dim+Strobe 2ch",["Dim", "Strobe"]),
    ],
}


def _mode_defaults(mode: dict) -> list:
    """Valeurs fixes d'un mode, ramenées à la convention de l'éditeur (None = libre)."""
    if isinstance(mode.get("defaults"), list):
        return list(mode["defaults"])
    # Format admin panel / Firestore : des entiers, où 0 ne veut pas dire
    # « forcer à 0 » mais « rien d'imposé » — c'est la valeur de remplissage.
    return [v if isinstance(v, int) and v > 0 else None
            for v in (mode.get("default_values") or [])]


def _fixture_modes(fx: dict) -> list:
    """Modes éditables d'une fixture, quel que soit le format d'origine.

    Les canaux vivent soit à la racine (`profile`, fixtures de l'éditeur), soit
    dans `modes` (admin panel, OFL, QLC+). La liste rendue n'est jamais vide :
    l'éditeur a toujours un mode à afficher.
    """
    out = []
    for m in fx.get("modes") or []:
        if not isinstance(m, dict) or not m.get("profile"):
            continue
        out.append({
            "name":     m.get("name", ""),
            "profile":  list(m.get("profile") or []),
            "defaults": _mode_defaults(m),
            "matrix":   m["matrix"] if isinstance(m.get("matrix"), dict) else None,
        })
    if out:
        return out
    return [{
        "name":     fx.get("mode_name", ""),
        "profile":  list(fx.get("profile") or []),
        "defaults": _mode_defaults(fx),
        "matrix":   fx["matrix"] if isinstance(fx.get("matrix"), dict) else None,
    }]


# ──────────────────────────────────────────────────────────────────────────────
# Classes conservées pour compatibilité avec admin_pack_editor / admin_panel
# ──────────────────────────────────────────────────────────────────────────────

class _NoScrollCombo(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


# ──────────────────────────────────────────────────────────────────────────────
# Recherche d'un type de canal : taper « pa » propose Pan puis PanFine
# ──────────────────────────────────────────────────────────────────────────────

def _ch_norm(s: str) -> str:
    """Clé de comparaison : minuscules, sans accents ni séparateurs."""
    s = (s or "").lower().strip()
    for src, dst in (("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"), ("à", "a"),
                     ("â", "a"), ("î", "i"), ("ï", "i"), ("ô", "o"), ("ù", "u"),
                     ("û", "u"), ("ü", "u"), ("ç", "c")):
        s = s.replace(src, dst)
    return "".join(c for c in s if c.isalnum())


# Alias normalisé → type de canal, alimenté par qui possède déjà un tel
# vocabulaire (le pack editor admin, cf. register_channel_search_aliases). On
# l'enregistre au lieu de l'importer : `fixture_editor` est embarqué dans l'app
# utilisateur, un import vers un module admin y ferait entrer du code admin.
# Table absente = recherche sur les seuls noms de types, ce qui couvre déjà
# « pan » → Pan / PanFine.
_CH_ALIAS_INDEX: dict[str, str] = {}


def register_channel_search_aliases(mapping: dict):
    """Ajoute des alias de recherche (« amber » → Ambre, « obturateur » → Shutter)."""
    _CH_ALIAS_INDEX.update({_ch_norm(k): v for k, v in mapping.items()})


def channel_type_matches(text: str) -> list[str]:
    """Types de canaux correspondant à une saisie libre, du plus pertinent au moins.

    « pa » ou « pan » → [Pan, PanFine] · « fine » → [PanFine, TiltFine] ·
    « amber » → [Ambre] (via alias). Saisie vide → la liste complète.
    """
    q = _ch_norm(text)
    if not q:
        return list(ALL_CHANNEL_TYPES)

    exact, starts, contains = [], [], []
    for t in ALL_CHANNEL_TYPES:
        n = _ch_norm(t)
        if n == q:
            exact.append(t)
        elif n.startswith(q):
            starts.append(t)
        elif q in n:
            contains.append(t)

    direct = exact + starts + contains
    if direct:
        # Les alias ne servent que de repêchage : sinon « pa » ferait remonter
        # Speed (via l'alias « panspeed ») derrière Pan et PanFine.
        return direct

    alias = []
    for key, t in _CH_ALIAS_INDEX.items():
        if t in ALL_CHANNEL_TYPES and t not in alias and q in key:
            alias.append(t)
    alias.sort(key=ALL_CHANNEL_TYPES.index)
    return alias


class ChannelTypeCombo(_NoScrollCombo):
    """Combo des types de canaux avec recherche par saisie.

    Éditable uniquement pour saisir un filtre : la valeur retenue est toujours
    un élément de ALL_CHANNEL_TYPES (insertion désactivée, et toute saisie non
    résolue revient au type courant). D'où le signal `type_changed`, qui ne part
    que sur un type valide — `currentTextChanged` partirait à chaque frappe.
    """

    type_changed = Signal(str)

    def __init__(self, ch_type: str = "", parent=None):
        super().__init__(parent)
        self.addItems(ALL_CHANNEL_TYPES)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setToolTip("Tapez pour rechercher : « pan » → Pan, PanFine")
        self.lineEdit().setPlaceholderText("Rechercher un canal…")
        # padding/margin remis à zéro explicitement : une feuille de style
        # d'application (STYLE_APP de l'admin : « QLineEdit{padding:8px} ») vise
        # aussi ce QLineEdit interne, et ce qu'on ne redéfinit pas ici en est
        # hérité. Avec 8 px haut et bas dans les 22 px utiles du combo, le texte
        # du canal se retrouve rogné.
        self.lineEdit().setStyleSheet(
            "background:transparent;border:none;color:#e0e0e0;"
            "padding:0;margin:0;font-size:12px;")
        # Un combo éditable place un curseur au lieu d'ouvrir la liste : on
        # rétablit le geste d'avant (clic = liste complète), la frappe filtrant
        # ensuite. Sans ça, le champ n'a plus aucune affordance de liste, la
        # feuille de style des lignes de canal masquant déjà la flèche.
        self.lineEdit().installEventFilter(self)

        self._model     = QStringListModel(list(ALL_CHANNEL_TYPES), self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        # Le modèle est déjà filtré par channel_type_matches : on demande au
        # completer de tout afficher. En mode filtré il re-filtrerait par
        # préfixe, et « amber » (qui ne préfixe pas « Ambre ») ne proposerait
        # plus rien.
        self._completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        # Le popup d'un QCompleter n'a rien du menu déroulant natif d'un combo :
        # il n'affiche que 7 lignes par défaut (sur 29 types) et prend la largeur
        # du champ au lieu de se dimensionner sur son contenu. On rétablit les
        # deux, sinon la liste paraît tronquée en hauteur comme en largeur.
        self._completer.setMaxVisibleItems(16)
        popup = self._completer.popup()
        popup.setStyleSheet(
            "QAbstractItemView{background:#222;color:#e0e0e0;"
            "border:1px solid #3a3a3a;outline:none;}"
            "QAbstractItemView::item{padding:2px 4px;}"
            "QAbstractItemView::item:selected{background:#00c8ff;color:#000;}"
            "QScrollBar:vertical{background:#1a1a1a;width:10px;margin:0;}"
            "QScrollBar::handle:vertical{background:#3a3a3a;border-radius:5px;"
            "min-height:24px;}"
            "QScrollBar::handle:vertical:hover{background:#4a4a4a;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}"
        )
        _fm = popup.fontMetrics()
        popup.setMinimumWidth(
            max(_fm.horizontalAdvance(t) for t in ALL_CHANNEL_TYPES) + 40)
        self.setCompleter(self._completer)

        self.set_type(ch_type)
        self.lineEdit().textEdited.connect(self._on_text_edited)
        self.lineEdit().editingFinished.connect(self._on_editing_finished)
        self._completer.activated[str].connect(self._commit)
        self.activated.connect(lambda i: self._commit(self.itemText(i)))

    # ── API ───────────────────────────────────────────────────────────────────

    def current_type(self) -> str:
        """Type retenu — jamais le texte de recherche en cours de frappe."""
        return self._type

    def set_type(self, ch_type: str):
        """Positionne le type sans émettre type_changed (chargement d'un profil)."""
        idx = ALL_CHANNEL_TYPES.index(ch_type) if ch_type in ALL_CHANNEL_TYPES else 0
        self._type = ALL_CHANNEL_TYPES[idx]
        self.blockSignals(True)
        self.setCurrentIndex(idx)
        self.blockSignals(False)
        self.lineEdit().setText(self._type)

    # ── Interne ───────────────────────────────────────────────────────────────

    def focusInEvent(self, event):
        super().focusInEvent(event)
        # Sélectionner le texte : taper remplace la recherche au lieu de s'y ajouter
        self.lineEdit().selectAll()

    def eventFilter(self, obj, event):
        if (obj is self.lineEdit() and event.type() == QEvent.MouseButtonPress
                and self.isEnabled()):
            # Différé : ouvrir le popup pendant le clic le ferait refermer aussitôt
            QTimer.singleShot(0, self._show_all)
        return super().eventFilter(obj, event)

    def _show_all(self):
        self._model.setStringList(list(ALL_CHANNEL_TYPES))
        self.lineEdit().selectAll()
        self._completer.complete()

    def _on_text_edited(self, text: str):
        matches = channel_type_matches(text)
        self._model.setStringList(matches)
        if matches:
            self._completer.complete()
        else:
            self._completer.popup().hide()

    def _commit(self, ch_type: str):
        if ch_type not in ALL_CHANNEL_TYPES:
            return
        # On compare au type retenu (self._type) et pas à currentIndex : Qt
        # resynchronise l'index tout seul dès que le texte saisi correspond à un
        # élément (« pan » → Pan), ce qui ferait passer le changement inaperçu.
        changed = ch_type != self._type
        self._type = ch_type
        self.blockSignals(True)
        self.setCurrentIndex(ALL_CHANNEL_TYPES.index(ch_type))
        self.blockSignals(False)
        self.lineEdit().setText(ch_type)
        if changed:
            self.type_changed.emit(ch_type)

    def _on_editing_finished(self):
        """Sortie du champ : on résout la saisie, ou on revient au type courant."""
        text = self.lineEdit().text()
        matches = channel_type_matches(text) if text.strip() else []
        if matches and _ch_norm(text) != _ch_norm(self.current_type()):
            self._commit(matches[0])
        else:
            self.lineEdit().setText(self.current_type())


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
            _lbl = channel_label(ch)
            painter.drawText(x, 14, bw, h - 17, Qt.AlignCenter,
                             _lbl if len(_lbl) <= 5 else _lbl[:4] + ".")
        painter.end()


class ChannelRowWidget(QWidget):
    """Une ligne de canal : n° coloré, type cherchable, et actions ▲ ▼ ✕.

    `show_default` ajoute la case de valeur fixe DMX. Elle descend à -1, affiché
    « — » : c'est l'état « aucune valeur imposée », qu'un simple 0-255 ne saurait
    pas dire — or 0 sur un Dim, c'est un projecteur éteint, pas une absence de
    consigne.
    """
    remove_requested  = Signal(object)
    move_up_requested = Signal(object)
    move_dn_requested = Signal(object)
    changed           = Signal()

    def __init__(self, ch_num, ch_type, parent=None,
                 default_val=None, show_default=False):
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
        self._combo = ChannelTypeCombo(ch_type)
        self._combo.setFixedHeight(26)
        self._combo.setStyleSheet(
            "QComboBox{background:#2a2a2a;color:#e0e0e0;border:1px solid #3a3a3a;"
            "border-radius:3px;padding:1px 6px;font-size:12px;}"
            "QComboBox::drop-down{border:none;width:16px;}"
            "QComboBox QAbstractItemView{background:#222;color:#e0e0e0;}"
        )
        self._combo.type_changed.connect(self._on_type_changed)
        layout.addWidget(self._combo, 1)

        self._default_spin = None
        if show_default:
            self._default_spin = QSpinBox()
            self._default_spin.setRange(-1, 255)
            self._default_spin.setSpecialValueText("—")
            self._default_spin.setValue(-1 if default_val is None else int(default_val))
            self._default_spin.setFixedSize(58, 26)
            self._default_spin.setAlignment(Qt.AlignCenter)
            self._default_spin.setToolTip(tr("fe2_fixed_value_hint"))
            self._default_spin.setStyleSheet(
                "QSpinBox{background:#2a2a2a;color:#e0e0e0;border:1px solid #3a3a3a;"
                "border-radius:3px;padding:0 2px;font-size:11px;}"
                "QSpinBox::up-button,QSpinBox::down-button{width:12px;}")
            self._default_spin.valueChanged.connect(lambda _: self.changed.emit())
            layout.addWidget(self._default_spin)

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
        self._combo.set_type(t)   # n'émet pas type_changed
        self._set_num_style(CHANNEL_COLORS.get(t, "#666"))
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
    def get_type(self): return self._combo.current_type()

    def get_default(self):
        """Valeur fixe DMX, ou None si la case est sur « — »."""
        if self._default_spin is None:
            return None
        v = self._default_spin.value()
        return None if v < 0 else v

    def set_default(self, val):
        if self._default_spin is None:
            return
        self._default_spin.blockSignals(True)
        self._default_spin.setValue(-1 if val is None else int(val))
        self._default_spin.blockSignals(False)


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
        self.setWindowTitle(tr("fe_title"))
        self.setMinimumSize(860, 520)
        self.setWindowState(Qt.WindowMaximized)

        self._fixtures    = []
        self._current_idx = -1
        self._btn_add_to_patch = None   # compatibilité externe
        self.last_saved   = None        # dernière fixture enregistrée
        self._pack_check_thread = None
        self._pack_check_worker = None

        # Modes DMX de la fixture en cours d'édition. `_modes_data[_cur_mode]`
        # n'est à jour qu'après _commit_current_mode() : entre deux, la vérité
        # est dans les lignes affichées (`_rows`).
        self._modes_data  = []
        self._cur_mode    = -1
        self._mode_tabs   = []
        self._rows        = []
        self._pixel_matrix = None

        self._load_fixtures()
        self._build_ui()
        self._rebuild_list()

        if self._fixtures:
            self._select_fixture(0)
        else:
            self._show_empty_state()

        QTimer.singleShot(800, self._check_fixture_packs)

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
            QMessageBox.warning(self, tr("fe_error"), tr("fe_f_save_failed", e=e))

    # ── Packs de fixtures distants ────────────────────────────────────────────

    def _check_fixture_packs(self):
        """Lance la vérification des packs Firestore en arrière-plan (throttlée à 1h)."""
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
        if packs:
            self._pack_banner.set_packs(packs)

    def _open_pack_download(self, packs: list):
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
        if total_new > 0:
            self._load_fixtures()
            self._rebuild_list()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(self._STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._pack_banner = FixturePackBanner(self)
        self._pack_banner.download_clicked.connect(self._open_pack_download)
        root.addWidget(self._pack_banner)

        inner = QWidget()
        inner_layout = QHBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        root.addWidget(inner, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        inner_layout.addWidget(splitter)

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
        lbl = QLabel(tr("fe_my_fixtures"))
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

        # Boutons Nouveau + Copier + Importer
        foot = QWidget()
        foot.setFixedHeight(134)
        foot.setStyleSheet("background:#0d0d0d;border-top:1px solid #1a1a1a;")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(5)
        btn_new = QPushButton(tr("fe_new_fixture"))
        btn_new.setFixedHeight(34)
        btn_new.setStyleSheet(
            "QPushButton{background:#00d4ff;color:#000;border:none;"
            "border-radius:7px;font-size:12px;font-weight:bold;}"
            "QPushButton:hover{background:#33ddff;}"
        )
        btn_new.clicked.connect(self._new_fixture)
        fl.addWidget(btn_new)
        btn_copy_lib = QPushButton(tr("fe2_copy_lib"))
        btn_copy_lib.setFixedHeight(28)
        btn_copy_lib.setStyleSheet(
            "QPushButton{background:#1a1a2a;color:#8899cc;border:1px solid #2a2a44;"
            "border-radius:6px;font-size:11px;}"
            "QPushButton:hover{background:#222236;color:#aabbee;border-color:#4444aa;}"
        )
        btn_copy_lib.clicked.connect(self._copy_from_library)
        fl.addWidget(btn_copy_lib)
        btn_import = QPushButton(tr("fe_import_fixture"))
        btn_import.setFixedHeight(28)
        btn_import.setToolTip(tr("fe_import_formats"))
        btn_import.setStyleSheet(
            "QPushButton{background:#1a2a1a;color:#88cc88;border:1px solid #2a442a;"
            "border-radius:6px;font-size:11px;}"
            "QPushButton:hover{background:#223322;color:#aaeaaa;border-color:#44aa44;}"
        )
        btn_import.clicked.connect(self._do_import)
        fl.addWidget(btn_import)
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
        self._editor_title = QLabel(tr("fe_new_fixture_title"))
        self._editor_title.setStyleSheet(
            "font-size:22px;font-weight:bold;color:#00d4ff;"
        )
        hdr.addWidget(self._editor_title, 1)
        self._btn_delete = QPushButton(tr("fe_delete_m"))
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
        hdr.addSpacing(10)
        self._btn_export = QPushButton(tr("fe_export_m"))
        self._btn_export.setFixedHeight(30)
        self._btn_export.setStyleSheet(
            "QPushButton{background:#1a2a1a;color:#88cc88;border:1px solid #2a442a;"
            "border-radius:5px;font-size:11px;padding:0 12px;}"
            "QPushButton:hover{background:#223322;color:#aaeaaa;border-color:#44aa44;}"
        )
        self._btn_export.clicked.connect(self._do_export)
        hdr.addWidget(self._btn_export)
        hdr.addSpacing(10)
        self._btn_save = QPushButton(tr("fe_save_m"))
        self._btn_save.setFixedHeight(30)
        self._btn_save.setStyleSheet(
            "QPushButton{background:#00d4ff;color:#000;border:none;"
            "border-radius:5px;font-size:11px;font-weight:bold;padding:0 14px;}"
            "QPushButton:hover{background:#33ddff;}"
            "QPushButton:disabled{background:#181818;color:#333;border:1px solid #222;}"
        )
        self._btn_save.clicked.connect(self._save_current)
        hdr.addWidget(self._btn_save)
        hdr.addSpacing(10)
        btn_close = QPushButton(tr("fe_close_m"))
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
            tr("fe_ex_name")
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
        tc.addWidget(self._type_combo)
        type_mode_row.addLayout(tc, 1)

        mc = QVBoxLayout()
        mc.setSpacing(5)
        mc.addWidget(self._lbl("MARQUE (FABRICANT)"))
        self._mfr_edit = QLineEdit()
        self._mfr_edit.setPlaceholderText(tr("fe2_mfr_ph"))
        self._mfr_edit.setFixedHeight(38)
        mc.addWidget(self._mfr_edit)
        type_mode_row.addLayout(mc, 1)

        rv.addLayout(type_mode_row)
        rv.addSpacing(28)

        # Séparateur
        rv.addWidget(self._sep())
        rv.addSpacing(22)

        # ── Section canaux ────────────────────────────────────────────────────
        ch_hdr = QHBoxLayout()
        ch_hdr.addWidget(self._lbl("PROFIL DMX"))
        self._ch_count_lbl = QLabel(tr("fe_zero_channel"))
        self._ch_count_lbl.setStyleSheet("font-size:11px;color:#444;")
        ch_hdr.addStretch()
        ch_hdr.addWidget(self._ch_count_lbl)
        rv.addLayout(ch_hdr)
        rv.addSpacing(6)

        # ── Onglets de modes DMX ──────────────────────────────────────────────
        # Un même appareil expose plusieurs protocoles (8CH, 13CH…). Les tenir
        # dans UNE fixture à plusieurs modes, plutôt qu'une fixture par mode,
        # c'est ce que sait déjà lire le sélecteur de mode de la bibliothèque.
        rv.addWidget(self._lbl("MODES DMX"))
        rv.addSpacing(6)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        self._mode_tab_host = QWidget()
        self._mode_tab_host.setStyleSheet("QWidget{background:transparent;}")
        self._mode_tab_layout = QHBoxLayout(self._mode_tab_host)
        self._mode_tab_layout.setContentsMargins(0, 0, 0, 0)
        self._mode_tab_layout.setSpacing(4)
        tab_row.addWidget(self._mode_tab_host, 1)

        btn_add_mode = QPushButton(tr("fe2_add_mode"))
        btn_add_mode.setFixedHeight(28)
        btn_add_mode.setCursor(Qt.PointingHandCursor)
        btn_add_mode.setStyleSheet(self._MODE_TAB_IDLE)
        btn_add_mode.clicked.connect(self._add_mode)
        tab_row.addWidget(btn_add_mode)

        self._btn_del_mode = QPushButton("✕")
        self._btn_del_mode.setFixedSize(28, 28)
        self._btn_del_mode.setToolTip(tr("fe2_del_mode"))
        self._btn_del_mode.setStyleSheet(
            "QPushButton{background:#2a0000;color:#cc4444;border:1px solid #3a1111;"
            "border-radius:5px;font-size:11px;font-weight:bold;padding:0;}"
            "QPushButton:hover{background:#440000;color:#ff6666;}"
            "QPushButton:disabled{background:#181818;color:#333;border-color:#222;}")
        self._btn_del_mode.clicked.connect(self._del_mode)
        tab_row.addWidget(self._btn_del_mode)
        rv.addLayout(tab_row)
        rv.addSpacing(8)

        # Nom du mode courant
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        lbl_mn = QLabel(tr("fe2_mode_name"))
        lbl_mn.setStyleSheet("font-size:11px;color:#777;")
        name_row.addWidget(lbl_mn)
        self._mode_name_edit = QLineEdit()
        self._mode_name_edit.setPlaceholderText(tr("fe_ex_mode"))
        self._mode_name_edit.setFixedHeight(30)
        self._mode_name_edit.textChanged.connect(self._on_mode_name_changed)
        name_row.addWidget(self._mode_name_edit, 1)
        rv.addLayout(name_row)
        rv.addSpacing(14)

        # Aperçu DMX du mode courant
        self._preview = DmxPreviewWidget()
        rv.addWidget(self._preview)
        rv.addSpacing(8)

        # Lignes de canaux
        rows_hint = QLabel(tr("fe2_rows_hint"))
        rows_hint.setStyleSheet("font-size:10px;color:#444;")
        rv.addWidget(rows_hint)
        rv.addSpacing(5)

        self._ch_scroll = QScrollArea()
        self._ch_scroll.setWidgetResizable(True)
        self._ch_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._ch_scroll.setMinimumHeight(190)
        self._ch_scroll.setMaximumHeight(430)
        self._ch_scroll.setStyleSheet(
            "QScrollArea{background:#111;border:1px solid #222;border-radius:8px;}")
        self._ch_host = QWidget()
        self._ch_host.setStyleSheet("QWidget{background:#111;}")
        self._ch_vbox = QVBoxLayout(self._ch_host)
        self._ch_vbox.setContentsMargins(6, 6, 6, 6)
        self._ch_vbox.setSpacing(3)
        self._ch_vbox.addStretch()
        self._ch_scroll.setWidget(self._ch_host)
        rv.addWidget(self._ch_scroll)
        rv.addSpacing(8)

        add_row = QHBoxLayout()
        btn_add_ch = QPushButton(tr("fe2_add_channel"))
        btn_add_ch.setFixedHeight(28)
        btn_add_ch.setCursor(Qt.PointingHandCursor)
        btn_add_ch.setStyleSheet(
            "QPushButton{background:#0d2630;color:#00d4ff;border:1px solid #14404f;"
            "border-radius:5px;font-size:11px;font-weight:bold;padding:0 14px;}"
            "QPushButton:hover{background:#12323f;border-color:#00d4ff;}")
        btn_add_ch.clicked.connect(lambda: self._append_channel("Dim"))
        add_row.addWidget(btn_add_ch)
        add_row.addStretch()
        rv.addLayout(add_row)
        rv.addSpacing(18)

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
        self._mfr_edit.setText("")
        self._editor_title.setText(tr("fe_new_fixture_title"))
        self._type_combo.setCurrentIndex(0)
        self._pixel_matrix = None
        self._load_modes([{"name": "", "profile": ["R", "G", "B"], "defaults": []}])
        self._btn_delete.setEnabled(False)

    # ── Modes DMX ─────────────────────────────────────────────────────────────

    _MODE_TAB_IDLE = (
        "QPushButton{background:#1a1a1a;color:#888;border:1px solid #2a2a2a;"
        "border-radius:5px;font-size:11px;padding:0 12px;}"
        "QPushButton:hover{background:#222;color:#ccc;border-color:#3a3a3a;}")
    _MODE_TAB_ACTIVE = (
        "QPushButton{background:#00d4ff22;color:#00d4ff;border:1px solid #00d4ff66;"
        "border-radius:5px;font-size:11px;font-weight:bold;padding:0 12px;}")

    def _load_modes(self, modes: list):
        """Remplace la pile de modes et affiche le premier."""
        self._modes_data = []
        for m in modes or []:
            self._modes_data.append({
                "name":     m.get("name", ""),
                "profile":  list(m.get("profile", []) or []),
                "defaults": list(m.get("defaults", []) or []),
                "matrix":   dict(m["matrix"]) if isinstance(m.get("matrix"), dict) else None,
            })
        if not self._modes_data:
            self._modes_data.append({"name": "", "profile": [], "defaults": [], "matrix": None})
        self._cur_mode = -1
        self._rebuild_mode_tabs()
        self._select_mode(0)

    def _commit_current_mode(self):
        """Recopie les lignes affichées dans le mode courant."""
        if 0 <= self._cur_mode < len(self._modes_data):
            m = self._modes_data[self._cur_mode]
            m["profile"]  = self._get_profile()
            m["defaults"] = self._get_defaults()
            m["matrix"]   = getattr(self, "_pixel_matrix", None)

    def _rebuild_mode_tabs(self):
        while self._mode_tab_layout.count():
            it = self._mode_tab_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._mode_tabs = []
        for i, m in enumerate(self._modes_data):
            n = len(m.get("profile", []))
            btn = QPushButton(f"{m['name'] or f'Mode {i + 1}'}  ·  {n}ch")
            btn.setFixedHeight(28)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setChecked(i == self._cur_mode)
            btn.setStyleSheet(self._MODE_TAB_ACTIVE if i == self._cur_mode
                              else self._MODE_TAB_IDLE)
            btn.clicked.connect(lambda _=False, x=i: self._select_mode(x))
            self._mode_tab_layout.addWidget(btn)
            self._mode_tabs.append(btn)
        self._mode_tab_layout.addStretch()
        self._btn_del_mode.setEnabled(len(self._modes_data) > 1)

    def _refresh_mode_tab_label(self):
        """Met à jour l'onglet courant (nom + nombre de canaux) sans tout rebâtir."""
        if not (0 <= self._cur_mode < len(self._mode_tabs)):
            return
        m = self._modes_data[self._cur_mode]
        self._mode_tabs[self._cur_mode].setText(
            f"{m['name'] or f'Mode {self._cur_mode + 1}'}  ·  {len(self._get_profile())}ch")

    def _select_mode(self, idx: int):
        self._commit_current_mode()
        self._cur_mode = max(0, min(idx, len(self._modes_data) - 1))
        for i, btn in enumerate(self._mode_tabs):
            active = (i == self._cur_mode)
            btn.setChecked(active)
            btn.setStyleSheet(self._MODE_TAB_ACTIVE if active else self._MODE_TAB_IDLE)
        m = self._modes_data[self._cur_mode]
        self._mode_name_edit.blockSignals(True)
        self._mode_name_edit.setText(m.get("name", ""))
        self._mode_name_edit.blockSignals(False)
        # La géométrie pixel appartient au mode : un 8CH « Look » et un 48CH
        # « Pixel » de la même barre n'ont pas la même matrice.
        self._pixel_matrix = m.get("matrix")
        self._set_profile(m.get("profile", []), m.get("defaults", []))

    def _on_mode_name_changed(self, text: str):
        if 0 <= self._cur_mode < len(self._modes_data):
            self._modes_data[self._cur_mode]["name"] = text
            self._refresh_mode_tab_label()

    def _add_mode(self):
        self._commit_current_mode()
        self._modes_data.append({
            "name": f"Mode {len(self._modes_data) + 1}",
            "profile": [], "defaults": [], "matrix": None,
        })
        self._cur_mode = -1          # rien à recopier : la pile vient de changer
        self._rebuild_mode_tabs()
        self._select_mode(len(self._modes_data) - 1)
        self._mode_name_edit.setFocus()

    def _del_mode(self):
        if len(self._modes_data) <= 1:
            return
        m = self._modes_data[self._cur_mode]
        if m.get("profile") and QMessageBox.question(
            self, tr("fe2_del_mode"),
            tr("fe2_f_del_mode_q", name=m.get("name") or f"Mode {self._cur_mode + 1}"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._modes_data.pop(self._cur_mode)
        new_idx = max(0, self._cur_mode - 1)
        self._cur_mode = -1          # rien à recopier : le mode vient d'être retiré
        self._rebuild_mode_tabs()
        self._select_mode(new_idx)

    # ── Lignes de canaux ──────────────────────────────────────────────────────

    def _get_profile(self) -> list:
        return [r.get_type() for r in self._rows]

    def _get_defaults(self) -> list:
        return [r.get_default() for r in self._rows]

    def _set_profile(self, profile: list, defaults: list | None = None):
        """Reconstruit les lignes de canaux affichées."""
        defaults = defaults or []
        for r in self._rows:
            r.setParent(None)
            r.deleteLater()
        self._rows = []
        while self._ch_vbox.count():
            self._ch_vbox.takeAt(0)
        for i, ch in enumerate(profile):
            d = defaults[i] if i < len(defaults) else None
            self._rows.append(self._make_row(i + 1, ch, d))
            self._ch_vbox.addWidget(self._rows[-1])
        self._ch_vbox.addStretch()
        self._on_channels_changed()

    def _make_row(self, num: int, ch_type: str, default_val=None) -> ChannelRowWidget:
        row = ChannelRowWidget(num, ch_type, default_val=default_val, show_default=True)
        row.remove_requested.connect(self._remove_row)
        row.move_up_requested.connect(self._move_row_up)
        row.move_dn_requested.connect(self._move_row_dn)
        row.changed.connect(self._on_channels_changed)
        return row

    def _append_channel(self, ch_type: str):
        """Ajoute un canal en fin de profil (bouton + Canal, ou clic palette)."""
        row = self._make_row(len(self._rows) + 1, ch_type)
        self._ch_vbox.insertWidget(max(0, self._ch_vbox.count() - 1), row)
        self._rows.append(row)
        self._on_channels_changed()
        self._ch_scroll.verticalScrollBar().setValue(
            self._ch_scroll.verticalScrollBar().maximum())

    def _remove_row(self, row):
        if row not in self._rows:
            return
        self._rows.remove(row)
        self._ch_vbox.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._renumber()
        self._on_channels_changed()

    def _move_row_up(self, row):
        i = self._rows.index(row) if row in self._rows else -1
        if i > 0:
            self._rows[i], self._rows[i - 1] = self._rows[i - 1], self._rows[i]
            self._reinsert_rows()

    def _move_row_dn(self, row):
        i = self._rows.index(row) if row in self._rows else -1
        if 0 <= i < len(self._rows) - 1:
            self._rows[i], self._rows[i + 1] = self._rows[i + 1], self._rows[i]
            self._reinsert_rows()

    def _reinsert_rows(self):
        while self._ch_vbox.count():
            self._ch_vbox.takeAt(0)
        for r in self._rows:
            self._ch_vbox.addWidget(r)
        self._ch_vbox.addStretch()
        self._renumber()
        self._on_channels_changed()

    def _renumber(self):
        for i, r in enumerate(self._rows):
            r.set_num(i + 1)

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
        act_dup = menu.addAction(tr("fe_duplicate"))
        act_del = menu.addAction(tr("fe_delete"))
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
        self._mfr_edit.setText(fx.get("manufacturer", ""))
        self._editor_title.setText(fx.get("name", "Projecteur"))
        self._type_combo.blockSignals(True)
        ti = self._type_combo.findText(fx.get("fixture_type", "PAR LED"))
        if ti >= 0:
            self._type_combo.setCurrentIndex(ti)
        self._type_combo.blockSignals(False)
        # Repartir de la géométrie de CETTE fixture (ou aucune) : sans ça,
        # celle générée pour la précédente serait recollée à la suivante.
        self._load_modes(_fixture_modes(fx))
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
        self._mfr_edit.setText("")
        self._editor_title.setText(tr("fe_new_fixture_title"))
        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentIndex(0)
        self._type_combo.blockSignals(False)
        self._pixel_matrix = None
        self._load_modes([{"name": "", "profile": ["R", "G", "B"], "defaults": []}])
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
        dlg.setWindowTitle(tr("fe2_copy_from_lib"))
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
        search.setPlaceholderText(tr("fe_search"))
        search.setFixedHeight(36)
        vl.addWidget(search)

        lst = QListWidget()
        vl.addWidget(lst, 1)

        hint = QLabel(tr("fe2_dblclick_hint"))
        hint.setAlignment(Qt.AlignCenter)
        vl.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton(tr("fe2_copy_profile"))
        btn_ok.setFixedHeight(36)
        btn_ok.setStyleSheet(
            "QPushButton{background:#00d4ff;color:#000;font-weight:bold;"
            "border:none;border-radius:6px;padding:6px 24px;font-size:13px;}"
            "QPushButton:hover{background:#33ddff;}"
        )
        btn_cancel = QPushButton(tr("fe_cancel"))
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
        if fx.get("manufacturer") and not self._mfr_edit.text().strip():
            self._mfr_edit.setText(fx["manufacturer"])
        # TOUS les modes de la source sont repris : une lyre OFL en expose
        # souvent 3 ou 4, et n'en copier qu'un obligeait à refaire l'opération
        # (puis à patcher deux fixtures distinctes) pour changer de protocole.
        self._load_modes(_fixture_modes(fx))

    # ── Canaux ────────────────────────────────────────────────────────────────

    def _on_channels_changed(self):
        channels = self._get_profile()
        n = len(channels)
        self._ch_count_lbl.setText(tr("fe_f_n_channels", n=n, a0='x' if n > 1 else ''))
        self._preview.set_channels(channels)
        self._refresh_mode_tab_label()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _kept_matrix(matrix, profile):
        """Géométrie pixel, conservée seulement si le profil lui correspond encore.

        L'utilisateur a pu retirer des canaux à la main après génération : une
        matrice qui ne compte plus ses canaux ferait éclater la fixture en
        pixels fantômes sur le plan de feu.
        """
        if not matrix:
            return None
        expected = (len(matrix.get("head") or []) +
                    matrix.get("pixel_count", 0) * len(matrix.get("pixel_channels") or []))
        return dict(matrix) if len(profile) == expected else None

    def _get_form_data(self):
        self._commit_current_mode()
        # Les modes vides sont écartés : ils ne décrivent aucun protocole et le
        # sélecteur de mode de la bibliothèque les ignorerait de toute façon.
        modes = [m for m in self._modes_data if m.get("profile")]

        out_modes = []
        for i, m in enumerate(modes):
            entry = {
                "name":         m.get("name") or f"Mode {i + 1}",
                "channelCount": len(m["profile"]),
                "profile":      list(m["profile"]),
            }
            if any(v is not None for v in m.get("defaults") or []):
                entry["defaults"] = list(m["defaults"])
            mx = self._kept_matrix(m.get("matrix"), m["profile"])
            if mx:
                entry["matrix"] = mx
            out_modes.append(entry)

        # La racine décrit le PREMIER mode : c'est ce que lisent le patch, les
        # exports et les fixtures d'avant les modes. Le reste vit dans `modes`,
        # que le sélecteur de la bibliothèque sait proposer.
        first = out_modes[0] if out_modes else {"name": "", "profile": []}
        data = {
            "name":         self._name_edit.text().strip(),
            "manufacturer": self._mfr_edit.text().strip() or "Générique",
            "fixture_type": self._type_combo.currentText(),
            "mode_name":    first.get("name", ""),
            "max_channels": 512,
            "group":        "face",
            "profile":      list(first.get("profile") or []),
            "source":       "user",
        }
        if first.get("defaults"):
            data["defaults"] = list(first["defaults"])
        if first.get("matrix"):
            data["matrix"] = dict(first["matrix"])
        if out_modes:
            data["modes"] = out_modes
        return data

    def _save_current(self):
        data = self._get_form_data()
        if not data["name"]:
            QMessageBox.warning(self, tr("fe_name_required"),
                tr("fe_enter_name"))
            self._name_edit.setFocus()
            return
        if not data["profile"]:
            QMessageBox.warning(self, tr("fe_channels_required"),
                tr("fe_add_one_channel"))
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
        # Signaux bloqués : laisser partir currentRowChanged rechargerait la
        # fixture qu'on vient d'écrire et ramènerait l'affichage au mode 1 —
        # on repartirait du mauvais onglet après chaque enregistrement.
        self._my_list.blockSignals(True)
        self._my_list.setCurrentRow(self._current_idx)
        self._my_list.blockSignals(False)
        self._btn_delete.setEnabled(True)
        self._editor_title.setText(data["name"])

        self.last_saved = data
        if is_new:
            self.fixture_added.emit(data)

        orig = self._btn_save.text()
        self._btn_save.setText(tr("fe2_saved"))
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
            self, tr("fe_delete"),
            tr("fe_f_delete_q", name=name),
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

    # ── Export ────────────────────────────────────────────────────────────────

    def _do_export(self):
        """Exporte la fixture courante dans un fichier .mft (JSON) réimportable."""
        # Fixture enregistrée sélectionnée → données complètes (slots, defaults…)
        if 0 <= self._current_idx < len(self._fixtures):
            data = copy.deepcopy(self._fixtures[self._current_idx])
        else:
            data = self._get_form_data()   # fixture en cours d'édition, non enregistrée
        if not data.get("name") or not data.get("profile"):
            QMessageBox.warning(self, tr("fe_nothing_to_export"),
                tr("fe_select_before_export"))
            return
        safe = "".join(c for c in data["name"] if c.isalnum() or c in " -_").strip() or "fixture"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter la fixture", str(Path.home() / f"{safe}.mft"),
            "Fixture MyStrow (*.mft);;JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, tr("fe_export_failed"), str(e))
            return
        QMessageBox.information(self, tr("fe_export_ok"),
            tr("fe_f_exported", a0=data['name'], path=path))

    # ── Import ────────────────────────────────────────────────────────────────

    def _do_import(self):
        from fixture_parser import parse_file as _parse_file
        from PySide6.QtWidgets import QInputDialog

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importer des fixtures", str(Path.home()),
            "Tous les formats (*.mft *.json *.xml *.mystrow);;"
            "Fixture MyStrow (*.mft *.json *.mystrow);;"
            "XML QLC+ (*.xml)"
        )
        if not paths:
            return

        _GROUP = {
            "Machine a fumee": "fumee",
        }
        existing = {f["name"] for f in self._fixtures}
        imported, errors = 0, []
        newly_imported = []   # proposées ensuite au partage communautaire

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
                        # Provenance réelle du fichier : "source" est écrasé par
                        # "user" pour marquer la fixture comme locale, mais le
                        # partage communautaire a besoin de l'origine d'origine.
                        "origin_source": ofl_fx.get("source", ""),
                    } for m in modes]
                    if len(candidates) > 1:
                        names = [c["name"] for c in candidates]
                        choice, ok = QInputDialog.getItem(
                            self, tr("fe_mode_to_import"), tr("fe_choose"), names, 0, False)
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
                    newly_imported.append(fx)
                    imported += 1
            except Exception as e:
                errors.append(f"• {Path(path).name} : {e}")

        if imported == 0:
            msg = "Aucune fixture importée."
            if errors:
                msg += "\n\n" + "\n".join(errors)
            QMessageBox.warning(self, tr("fe_import_failed"), msg)
            return

        self._save_fixtures()
        self._rebuild_list()
        self._select_fixture(len(self._fixtures) - 1)
        msg = f"{imported} fixture{'s' if imported > 1 else ''} importée{'s' if imported > 1 else ''}."
        if errors:
            msg += f"\n\n{len(errors)} ignoré(s) :\n" + "\n".join(errors)
            QMessageBox.warning(self, tr("fe_import_partial"), msg)
        else:
            QMessageBox.information(self, tr("fe_import_ok"), msg)

        # Proposer de verser ces appareils à la bibliothèque commune (modération
        # + filtrage par licence côté fixture_share). Silencieux si l'utilisateur
        # n'est pas connecté : l'import local ne dépend pas du partage.
        from fixture_share import offer_share
        offer_share(self, newly_imported)
