"""
Assistant de mapping de contrôleur MIDI.
Permet de créer un profil pour n'importe quel contrôleur non supporté nativement.
"""
import json
import threading
import urllib.parse
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QStackedWidget, QWidget, QLineEdit,
    QFrame, QGridLayout, QScrollArea, QSizePolicy, QTextEdit, QSlider,
    QFileDialog, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QDesktopServices
from PySide6.QtCore import QUrl

from controller_profile import (list_profiles, save_profile, load_profile,
                                export_profile, unique_profile_path)
from core import MIDI_AVAILABLE, ComboSansMolette
from i18n import tr

# ─── Style cohérent avec le thème MyStrow ────────────────────────────────────
_STYLE = """
QDialog        { background: #080808; color: #cccccc; font-family: 'Segoe UI'; font-size: 10pt; }
QLabel         { color: #cccccc; background: transparent; }
QLabel#title   { color: #00aaff; font-size: 16pt; font-weight: bold; }
QLabel#sub     { color: #888888; font-size: 9pt; }
QLabel#step    { color: #555555; font-size: 8pt; }
QLabel#listen  { color: #00ff88; font-size: 10pt; font-weight: bold; }
QLabel#warn    { color: #ffaa00; font-size: 9pt; }
QFrame#card    { background: #111111; border: 1px solid #222222; border-radius: 8px; }
QFrame#sep     { background: #1a1a1a; }
QLineEdit, QComboBox, QSpinBox {
    background: #141414; border: 1px solid #2a2a2a; color: #cccccc;
    border-radius: 5px; padding: 6px 10px; font-size: 10pt;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #0066aa; }
QPushButton {
    background: #181828; border: 1px solid #2a2a4a; color: #99aadd;
    border-radius: 6px; padding: 8px 20px; font-size: 10pt;
}
QPushButton:hover   { background: #222238; border-color: #3a3a6a; }
QPushButton:pressed { background: #2a2a48; }
QPushButton#primary {
    background: #0a2a4a; border: 1px solid #0055aa; color: #00aaff;
    font-weight: bold;
}
QPushButton#primary:hover   { background: #0d3560; border-color: #0077cc; }
QPushButton#primary:pressed { background: #0a2040; }
QPushButton#skip   { color: #555555; border-color: #1a1a1a; background: #0d0d0d; font-size: 9pt; }
QPushButton#danger { background: #2a0a0a; border: 1px solid #550000; color: #ff4444; }
QPushButton#share  {
    background: #0a2a0a; border: 1px solid #005500; color: #00cc44;
    font-weight: bold;
}
QScrollArea { border: none; background: transparent; }
QTextEdit { background: #0d0d0d; border: 1px solid #222; color: #888; border-radius: 5px; }
"""

# Velocities AKAI standard et leur nom couleur
_LED_VELOCITIES = [
    (0,   "Éteint",   "#000000"),
    (3,   "?",        "#888888"),
    (5,   "?",        "#888888"),
    (9,   "?",        "#888888"),
    (13,  "?",        "#888888"),
    (21,  "?",        "#888888"),
    (25,  "?",        "#888888"),
    (37,  "?",        "#888888"),
    (45,  "?",        "#888888"),
    (49,  "?",        "#888888"),
    (53,  "?",        "#888888"),
    (63,  "?",        "#888888"),
    (127, "?",        "#888888"),
]

_COLOR_CHOICES = [
    ("Éteint",  "#222222", 0),
    ("Rouge",   "#ff2222", None),
    ("Vert",    "#22ff44", None),
    ("Bleu",    "#2244ff", None),
    ("Blanc",   "#ffffff", None),
    ("Orange",  "#ff8800", None),
    ("Jaune",   "#ffdd00", None),
    ("Cyan",    "#00dddd", None),
    ("Violet",  "#aa22ff", None),
    ("Magenta", "#ff22aa", None),
]

# Map nom couleur → velocity AKAI par défaut (fallback si l'utilisateur ne teste pas)
_COLOR_DEFAULT_VEL = {
    "Éteint": 0, "Rouge": 3, "Vert": 21, "Bleu": 45, "Blanc": 5,
    "Orange": 9, "Jaune": 13, "Cyan": 37, "Violet": 53, "Magenta": 49,
}


def _rtmidi_module():
    """Module rtmidi utilisable (python-rtmidi ou rtmidi2), None si aucun."""
    if not MIDI_AVAILABLE:
        return None
    try:
        import rtmidi
        return rtmidi
    except ImportError:
        try:
            import rtmidi2
            return rtmidi2
        except ImportError:
            return None


def _get_midi_ports():
    """Retourne la liste des ports MIDI IN disponibles."""
    mod = _rtmidi_module()
    if not mod:
        return []
    try:
        return list(mod.MidiIn().get_ports())
    except Exception:
        return []


def _get_midi_out_ports():
    """Retourne la liste des ports MIDI OUT disponibles."""
    mod = _rtmidi_module()
    if not mod:
        return []
    try:
        return list(mod.MidiOut().get_ports())
    except Exception:
        return []


def _port_keyword(port_name: str) -> str:
    """Mot-clé de détection déduit d'un nom de port.

    Windows suffixe le nom par l'index du port (« DDJ-400 0 »). Ce numéro
    change d'une machine — ou d'un rebranchement — à l'autre : un mot-clé qui
    le contient ne retrouverait plus le contrôleur au démarrage suivant.
    """
    parts = port_name.upper().split()
    while len(parts) > 1 and parts[-1].isdigit():
        parts.pop()
    return " ".join(parts[:3])


# ─── Widget grille de pads ────────────────────────────────────────────────────

class _PadGrid(QFrame):
    """Grille visuelle de pads pour le mapping."""

    PAD_SIZE  = 28
    PAD_GAP   = 3

    COLOR_EMPTY   = "#1a1a1a"
    COLOR_TARGET  = "#cc6600"
    COLOR_MAPPED  = "#004400"
    COLOR_SKIPPED = "#2a2a2a"

    def __init__(self, rows, cols, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.cols = cols
        self._cells = {}
        self._build(rows, cols)

    def _build(self, rows, cols):
        layout = QGridLayout(self)
        layout.setSpacing(self.PAD_GAP)
        layout.setContentsMargins(8, 8, 8, 8)
        for r in range(rows):
            for c in range(cols):
                cell = QFrame()
                cell.setFixedSize(self.PAD_SIZE, self.PAD_SIZE)
                cell.setStyleSheet(f"background:{self.COLOR_EMPTY}; border-radius:4px;")
                layout.addWidget(cell, r, c)
                self._cells[(r, c)] = cell
        self.setFixedSize(
            cols * (self.PAD_SIZE + self.PAD_GAP) + 16 + self.PAD_GAP,
            rows * (self.PAD_SIZE + self.PAD_GAP) + 16 + self.PAD_GAP,
        )

    def set_target(self, row, col):
        for (r, c), cell in self._cells.items():
            if (r, c) == (row, col):
                cell.setStyleSheet(f"background:{self.COLOR_TARGET}; border-radius:4px; border: 2px solid #ff8800;")

    def set_mapped(self, row, col):
        if (row, col) in self._cells:
            self._cells[(row, col)].setStyleSheet(f"background:{self.COLOR_MAPPED}; border-radius:4px;")

    def set_skipped(self, row, col):
        if (row, col) in self._cells:
            self._cells[(row, col)].setStyleSheet(f"background:{self.COLOR_SKIPPED}; border-radius:4px;")

    def clear_target(self, row, col):
        if (row, col) in self._cells:
            self._cells[(row, col)].setStyleSheet(f"background:{self.COLOR_EMPTY}; border-radius:4px;")


# ─── Wizard principal ─────────────────────────────────────────────────────────

class MidiMappingWizard(QDialog):
    """
    Assistant step-by-step pour créer un profil de mapping contrôleur MIDI.
    Résultat sauvegardé dans controllers/<name>.json.
    """

    profile_saved = Signal(str)  # émet le chemin du profil sauvegardé

    # Indices des pages dans le QStackedWidget
    # Page d'accueil retiree le 20/08/2026 : elle n'annoncait rien que la page
    # « Nom » ne dise mieux, et faisait payer un clic pour lire un texte.
    PAGE_NAME       = 0
    PAGE_DIMENSIONS = 1
    PAGE_PADS       = 2
    PAGE_MUTES      = 3
    PAGE_FADERS     = 4
    PAGE_EFFECTS    = 5
    PAGE_LEDS       = 6
    PAGE_SAVE       = 7

    def __init__(self, midi_handler, parent=None):
        super().__init__(parent)
        self.midi_handler = midi_handler
        self.setWindowTitle(tr("cmw_win_title"))
        self.setMinimumSize(700, 520)
        self.setStyleSheet(_STYLE)
        self.setModal(True)

        # Données collectées
        self._profile_name = ""
        self._keywords = []
        self._grid_rows = 8
        self._grid_cols = 8
        self._fader_count = 8
        self._effect_count = 8
        self._pad_map    = {}   # {(row,col): {'channel': int, 'note': int}}
        self._mute_map   = {}   # {idx: {'channel': int, 'note': int}}
        self._fader_map  = {}   # {idx: {'channel': int, 'cc': int}}
        self._effect_map = {}   # {idx: {'channel': int, 'note': int}}
        self._led_colors = {}   # {vel: 'Couleur'} velocity → label couleur

        # Contrôleur DJ : pads seulement, ni faders, ni effets, ni test des LED.
        self._dj_mode = False

        # Aperçu en direct de la page Dimensions : pads distincts déjà reçus.
        # Initialisés ICI et pas dans la page : cocher « contrôleur DJ » écrit
        # dans les compteurs, ce qui déclenche un redessin de la grille avant
        # même que la page ait été affichée une première fois.
        self._dim_seen = []
        self._dim_grid_widget = None

        # État mapping pads
        self._pad_row = 0
        self._pad_col = 0
        self._pad_grid_widget = None

        # État mapping courant
        self._mapping_cursor = 0

        # LED test
        self._led_vel_idx = 0
        self._led_vel_labels = {}  # vel -> label bouton

        # Pulsation "en écoute"
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_listen)
        self._pulse_state = False
        self._listen_label = None

        # Mode édition (profil existant chargé)
        self._edit_file = None

        # ── Écoute MIDI propre à l'assistant ──────────────────────────────────
        # L'assistant ne peut PAS se reposer sur le MIDIHandler : celui-ci
        # n'ouvre un port que pour un contrôleur qu'il reconnaît déjà (natif ou
        # profil custom existant). Pour un contrôleur inconnu — le seul cas où
        # cet assistant sert à quelque chose — `midi_in` reste None, `poll_midi`
        # sort immédiatement et AUCUN message n'arrive jamais : l'utilisateur
        # appuie sur ses pads devant une fenêtre qui « écoute » dans le vide.
        # On ouvre donc nous-mêmes le port choisi dans le menu déroulant.
        self._own_in     = None
        self._own_out    = None
        self._own_port   = ""     # port réellement écouté (le nôtre ou celui du handler)
        self._capture_cb = None
        self._port_error = ""
        self._rx_count   = 0
        self._last_raw   = None
        self._rx_queue   = []
        self._rx_lock    = threading.Lock()
        # Les callbacks rtmidi arrivent sur le thread MIDI et les étapes du
        # wizard touchent l'UI : on passe par une file vidée sur le thread Qt.
        self._rx_timer = QTimer(self)
        self._rx_timer.timeout.connect(self._drain_rx)
        self._rx_timer.start(10)

        self._build_ui()
        self._reset_all_leds()
        self._show_page(self.PAGE_NAME)

    # ─── Reset LEDs ──────────────────────────────────────────────────────────

    def _reset_all_leds(self):
        """Éteint tous les LEDs du contrôleur (notes 0-127, canaux 0-8)."""
        if not self._out_port():
            return
        for ch in range(9):
            for note in range(128):
                self._send_raw([0x90 | ch, note, 0])

    # ─── Construction UI principale ──────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Barre de progression en haut
        self._step_label = QLabel("", self)
        self._step_label.setObjectName("step")
        self._step_label.setAlignment(Qt.AlignCenter)
        self._step_label.setFixedHeight(24)
        self._step_label.setStyleSheet("background: #0a0a0a; color: #444; font-size: 8pt; padding: 4px;")
        root.addWidget(self._step_label)

        # Stack de pages
        self._stack = QStackedWidget()
        self._pages = [
            self._build_name(),
            self._build_dimensions(),
            self._build_pads(),
            self._build_mutes(),
            self._build_faders(),
            self._build_effects(),
            self._build_leds(),
            self._build_save(),
        ]
        for p in self._pages:
            self._stack.addWidget(p)
        root.addWidget(self._stack, 1)

    # ─── Pages ───────────────────────────────────────────────────────────────

    def _build_name(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(14)

        lbl_title = QLabel(tr("cmw_new_ctrl"))
        lbl_title.setObjectName("title")
        v.addWidget(lbl_title)

        lbl_sub = QLabel(tr("cmw_name_and_port"))
        lbl_sub.setObjectName("sub")
        v.addWidget(lbl_sub)
        v.addSpacing(8)

        v.addWidget(QLabel(tr("cmw_ctrl_name")))
        self._inp_name = QLineEdit()
        self._inp_name.setPlaceholderText(tr("cmw_ex_model"))
        v.addWidget(self._inp_name)

        v.addSpacing(4)
        v.addWidget(QLabel(tr("cmw_midi_port")))
        self._combo_ports = ComboSansMolette()
        self._combo_ports.addItem(tr("cmw_no_port"), None)
        for p in _get_midi_ports():
            self._combo_ports.addItem(p, p)
        self._combo_ports.currentIndexChanged.connect(self._port_selected)
        # Le contrôleur est souvent branché APRÈS l'ouverture de l'assistant :
        # sans bouton d'actualisation il fallait tout fermer et recommencer.
        h_port = QHBoxLayout(); h_port.setSpacing(8)
        h_port.addWidget(self._combo_ports, 1)
        btn_refresh = QPushButton(tr("cmw_refresh_ports")); btn_refresh.setObjectName("skip")
        btn_refresh.setFixedHeight(32)
        btn_refresh.clicked.connect(self._refresh_ports)
        h_port.addWidget(btn_refresh)
        v.addLayout(h_port)

        v.addSpacing(4)
        v.addWidget(QLabel(tr("cmw_keyword")))
        self._inp_keyword = QLineEdit()
        self._inp_keyword.setPlaceholderText(tr("cmw_ex_port"))
        v.addWidget(self._inp_keyword)

        lbl_hint = QLabel(tr("cmw_keyword_hint"))
        lbl_hint.setObjectName("warn")
        v.addWidget(lbl_hint)

        v.addSpacing(6)
        self._chk_dj = QCheckBox(tr("cmw_dj_ctrl"))
        self._chk_dj.setStyleSheet("color:#88bbff; font-weight:bold;")
        v.addWidget(self._chk_dj)
        lbl_dj = QLabel(tr("cmw_dj_hint"))
        lbl_dj.setObjectName("sub"); lbl_dj.setWordWrap(True)
        v.addWidget(lbl_dj)

        # État du port : ouvert, déjà pris par un autre logiciel, messages reçus.
        # Sans ce retour, un port indisponible est indiscernable d'un contrôleur
        # muet — c'est exactement le symptôme « rien n'y fait ».
        self._port_status = QLabel("")
        self._port_status.setWordWrap(True)
        self._port_status.setStyleSheet("color:#888888; font-size:9pt;")
        v.addWidget(self._port_status)

        v.addStretch()
        h = QHBoxLayout()
        btn_back = QPushButton(tr("cmw_back")); btn_back.setObjectName("skip")
        # Premiere page de l'assistant : « Retour » ne peut que sortir.
        btn_back.clicked.connect(self.reject)
        h.addWidget(btn_back)
        h.addStretch()
        btn_next = QPushButton(tr("cmw_continue")); btn_next.setObjectName("primary")
        btn_next.setFixedHeight(42)
        btn_next.clicked.connect(self._name_next)
        self._btn_name_next = btn_next
        h.addWidget(btn_next)
        v.addLayout(h)
        self._update_name_next_state()
        return w

    def _update_name_next_state(self):
        """« Continuer » reste bloqué tant qu'aucun port MIDI n'est choisi.

        Sans port, l'assistant ne peut RIEN capturer : on avancerait jusqu'aux
        pads pour y attendre indéfiniment un message qui n'arrivera jamais.
        Autant le dire ici, où l'utilisateur peut encore brancher son
        contrôleur et cliquer sur Actualiser.
        """
        btn = getattr(self, "_btn_name_next", None)
        if btn is None:
            return
        ports = _get_midi_ports()
        choisi = bool(self._combo_ports.currentData())
        btn.setEnabled(choisi)
        if not ports:
            self._port_status.setText(tr("cmw_no_port_block"))
            self._port_status.setStyleSheet("color:#e6a817; font-size:9pt;")
        elif not choisi:
            self._port_status.setText(tr("cmw_pick_port_first"))
            self._port_status.setStyleSheet("color:#e6a817; font-size:9pt;")

    def _build_dimensions(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(14)

        lbl_title = QLabel(tr("cmw_structure"))
        lbl_title.setObjectName("title")
        v.addWidget(lbl_title)
        lbl_sub = QLabel(tr("cmw_structure_hint"))
        lbl_sub.setObjectName("sub"); lbl_sub.setWordWrap(True)
        v.addWidget(lbl_sub)
        v.addSpacing(8)

        grid = QGridLayout(); grid.setSpacing(10)

        def _spin(lo, hi, default):
            s = QSpinBox()
            s.setRange(lo, hi); s.setValue(default)
            s.setFixedWidth(90)
            return s

        grid.addWidget(QLabel(tr("cmw_pad_rows")), 0, 0)
        self._spin_rows = _spin(0, 16, 8)
        grid.addWidget(self._spin_rows, 0, 1)

        grid.addWidget(QLabel(tr("cmw_pad_cols")), 1, 0)
        self._spin_cols = _spin(0, 16, 8)
        grid.addWidget(self._spin_cols, 1, 1)

        grid.addWidget(QLabel(tr("cmw_fader_count")), 2, 0)
        self._spin_faders = _spin(0, 16, 8)
        grid.addWidget(self._spin_faders, 2, 1)

        grid.addWidget(QLabel(tr("cmw_fx_buttons")), 3, 0)
        self._spin_effects = _spin(0, 16, 8)
        grid.addWidget(self._spin_effects, 3, 1)

        v.addLayout(grid)

        # Contrôle en direct : on appuie sur ses pads, ils s'allument ici.
        # Sans ça, on devinait les dimensions et on ne s'apercevait de l'erreur
        # qu'à l'étape suivante, une fois le mappage commencé.
        v.addSpacing(6)
        lbl_live = QLabel(tr("cmw_dim_live"))
        lbl_live.setObjectName("sub"); lbl_live.setWordWrap(True)
        v.addWidget(lbl_live)

        self._dim_grid_area = QFrame(); self._dim_grid_area.setObjectName("card")
        self._dim_grid_layout = QVBoxLayout(self._dim_grid_area)
        self._dim_grid_layout.setAlignment(Qt.AlignCenter)
        v.addWidget(self._dim_grid_area, 0, Qt.AlignHCenter)

        self._dim_count = QLabel("")
        self._dim_count.setObjectName("sub")
        self._dim_count.setAlignment(Qt.AlignCenter)
        v.addWidget(self._dim_count)

        # Redessiner dès qu'on change une dimension : la grille doit refléter
        # ce qui est saisi, pas ce qui l'était en arrivant sur la page.
        self._spin_rows.valueChanged.connect(self._rebuild_dim_grid)
        self._spin_cols.valueChanged.connect(self._rebuild_dim_grid)

        v.addStretch()

        h = QHBoxLayout()
        btn_back = QPushButton(tr("cmw_back")); btn_back.setObjectName("skip")
        btn_back.clicked.connect(lambda: self._show_page(self.PAGE_NAME))
        h.addWidget(btn_back); h.addStretch()
        btn_next = QPushButton(tr("cmw_continue")); btn_next.setObjectName("primary")
        btn_next.setFixedHeight(42)
        btn_next.clicked.connect(self._dimensions_next)
        h.addWidget(btn_next)
        v.addLayout(h)
        return w

    def _build_pads(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(12)

        h_top = QHBoxLayout(); h_top.setSpacing(24)

        # Grille visuelle (remplacée dynamiquement)
        self._pad_grid_area = QFrame()
        self._pad_grid_area.setObjectName("card")
        self._pad_grid_area.setFixedSize(320, 290)
        self._pad_grid_layout = QVBoxLayout(self._pad_grid_area)
        self._pad_grid_layout.setAlignment(Qt.AlignCenter)
        h_top.addWidget(self._pad_grid_area)

        # Panneau droit
        right = QVBoxLayout(); right.setSpacing(10)
        lbl_title = QLabel(tr("cmw_pad_mapping")); lbl_title.setObjectName("title")
        right.addWidget(lbl_title)

        self._pad_instr = QLabel(tr("cmw_press_pad"))
        self._pad_instr.setWordWrap(True)
        self._pad_instr.setStyleSheet("font-size: 12pt; color: #ddd;")
        right.addWidget(self._pad_instr)

        self._listen_label = QLabel(tr("cmw_listening"))
        self._listen_label.setObjectName("listen")
        right.addWidget(self._listen_label)

        right.addSpacing(8)

        btn_skip_cell = QPushButton(tr("cmw_skip_pos"))
        btn_skip_cell.setObjectName("skip")
        btn_skip_cell.clicked.connect(self._pad_skip_cell)
        right.addWidget(btn_skip_cell)

        btn_end_row = QPushButton(tr("cmw_end_row"))
        btn_end_row.setObjectName("skip")
        btn_end_row.clicked.connect(self._pad_end_row)
        right.addWidget(btn_end_row)

        btn_done = QPushButton(tr("cmw_finish_pads"))
        btn_done.setObjectName("danger")
        btn_done.clicked.connect(self._pad_done)
        right.addWidget(btn_done)

        right.addStretch()
        h_top.addLayout(right)
        v.addLayout(h_top)
        return w

    def _build_mutes(self):
        return self._build_generic_map_page(
            title="Boutons de tranche",
            subtitle=(
                "Pour chaque tranche, appuyez sur son bouton de silence (mute / solo).\n"
                "Si votre contrôleur n'a pas ces boutons, cliquez sur\n"
                "\"Aucun bouton de tranche\" pour passer."
            ),
            attr_prefix="mute",
            skip_all_label="Aucun bouton de tranche — Continuer",
        )

    def _build_faders(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(14)

        lbl_title = QLabel(tr("cmw_fader_mapping")); lbl_title.setObjectName("title")
        v.addWidget(lbl_title)
        lbl_sub = QLabel(
            tr("cmw_fader_step")
        )
        lbl_sub.setObjectName("sub"); lbl_sub.setWordWrap(True)
        v.addWidget(lbl_sub)
        v.addSpacing(8)

        self._fader_instr = QLabel(tr("cmw_move_fader1"))
        self._fader_instr.setStyleSheet("font-size: 14pt; color: #ddd;")
        v.addWidget(self._fader_instr)

        self._fader_listen = QLabel(tr("cmw_listening"))
        self._fader_listen.setObjectName("listen")
        v.addWidget(self._fader_listen)

        self._fader_progress = QLabel("")
        self._fader_progress.setObjectName("sub")
        v.addWidget(self._fader_progress)

        v.addSpacing(8)

        btn_skip = QPushButton(tr("cmw_skip_fader"))
        btn_skip.setObjectName("skip")
        btn_skip.clicked.connect(self._fader_skip)
        v.addWidget(btn_skip)

        v.addStretch()
        return w

    def _build_effects(self):
        return self._build_generic_map_page(
            title="Boutons Effet",
            subtitle="Appuyez sur le bouton effet (colonne de droite) indiqué.",
            attr_prefix="effect",
            skip_all_label="Aucun bouton effet sur ce contrôleur",
        )

    def _build_leds(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(12)

        lbl_title = QLabel(tr("cmw_led_test")); lbl_title.setObjectName("title")
        v.addWidget(lbl_title)

        self._led_phase_label = QLabel("")
        self._led_phase_label.setObjectName("sub")
        v.addWidget(self._led_phase_label)
        v.addSpacing(6)

        # ── Section luminosité (affichée en 1er) ──────────────────────────────
        # ── Phase 1 : slider libre ─────────────────────────────────────────────
        self._bright_section = QFrame()
        bright_v = QVBoxLayout(self._bright_section)
        bright_v.setContentsMargins(0, 0, 0, 0)
        bright_v.setSpacing(10)

        lbl_bright_intro = QLabel(
            tr("cmw_test1")
        )
        lbl_bright_intro.setObjectName("sub"); lbl_bright_intro.setWordWrap(True)
        bright_v.addWidget(lbl_bright_intro)

        self._bright_slider = QSlider(Qt.Horizontal)
        self._bright_slider.setRange(0, 127)
        self._bright_slider.setValue(64)
        self._bright_slider.setFixedHeight(32)
        self._bright_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #1a1a1a; border: 1px solid #333;
                height: 8px; border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00aaff; border: 1px solid #0088cc;
                width: 20px; height: 20px; margin: -6px 0;
                border-radius: 10px;
            }
            QSlider::sub-page:horizontal { background: #00aaff44; border-radius: 4px; }
        """)
        self._bright_slider.valueChanged.connect(self._on_bright_slider)
        bright_v.addWidget(self._bright_slider)

        self._bright_vel_label = QLabel(tr("cmw_velocity"))
        self._bright_vel_label.setAlignment(Qt.AlignCenter)
        self._bright_vel_label.setStyleSheet("color: #00aaff; font-size: 11pt;")
        bright_v.addWidget(self._bright_vel_label)

        h_bright1 = QHBoxLayout(); h_bright1.setSpacing(10)
        btn_bright_ok1 = QPushButton(tr("cmw_bright_ok"))
        btn_bright_ok1.setFixedHeight(38)
        btn_bright_ok1.setStyleSheet(
            "background:#0a2a0a; border:1px solid #004400; color:#00cc44;"
            " border-radius:6px; font-weight:bold;"
        )
        btn_bright_ok1.clicked.connect(self._bright_confirm)
        h_bright1.addWidget(btn_bright_ok1)
        btn_next_test = QPushButton(tr("cmw_no_change"))
        btn_next_test.setObjectName("skip")
        btn_next_test.clicked.connect(self._bright_try_specific)
        h_bright1.addWidget(btn_next_test)
        bright_v.addLayout(h_bright1)
        v.addWidget(self._bright_section)

        # ── Phase 2 : velocités précises + méthodes alternatives ──────────────
        self._bright_specific_section = QFrame()
        spec_v = QVBoxLayout(self._bright_specific_section)
        spec_v.setContentsMargins(0, 0, 0, 0)
        spec_v.setSpacing(10)

        lbl_spec_intro = QLabel(
            tr("cmw_test2")
        )
        lbl_spec_intro.setObjectName("sub"); lbl_spec_intro.setWordWrap(True)
        spec_v.addWidget(lbl_spec_intro)

        # Grille de velocités précises
        vel_grid = QGridLayout(); vel_grid.setSpacing(6)
        _SPECIFIC_VELS = [1, 5, 10, 21, 37, 45, 63, 100, 120, 127]
        self._bright_specific_vel = None
        for i, vel in enumerate(_SPECIFIC_VELS):
            btn_v = QPushButton(f"{vel}")
            btn_v.setFixedHeight(32)
            btn_v.setStyleSheet(
                "QPushButton{background:#141428; border:1px solid #2a2a5a; color:#8888cc;"
                " border-radius:5px; font-size:10pt;}"
                "QPushButton:hover{background:#1e1e3e; border-color:#00aaff; color:#00aaff;}"
                "QPushButton:pressed{background:#0a0a2a;}"
            )
            btn_v.clicked.connect(lambda _, v=vel: self._bright_send_specific(v))
            vel_grid.addWidget(btn_v, i // 5, i % 5)
        spec_v.addLayout(vel_grid)

        # Méthodes alternatives sur une ligne
        h_alt = QHBoxLayout(); h_alt.setSpacing(8)
        self._bright_alt_channel_label = QLabel(tr("cmw_channel1"))
        self._bright_alt_channel_label.setStyleSheet("color: #555; font-size: 8pt;")
        btn_alt_ch = QPushButton(tr("cmw_channel_alt"))
        btn_alt_ch.setObjectName("skip"); btn_alt_ch.setFixedHeight(28)
        btn_alt_ch.clicked.connect(self._bright_test_channel)
        h_alt.addWidget(btn_alt_ch)
        h_alt.addWidget(self._bright_alt_channel_label)
        btn_alt_off = QPushButton(tr("cmw_note_off_vel"))
        btn_alt_off.setObjectName("skip"); btn_alt_off.setFixedHeight(28)
        btn_alt_off.clicked.connect(self._bright_test_noteoff)
        h_alt.addWidget(btn_alt_off)
        h_alt.addStretch()
        spec_v.addLayout(h_alt)

        h_bright2 = QHBoxLayout(); h_bright2.setSpacing(10)
        btn_bright_ok2 = QPushButton(tr("cmw_something_changes"))
        btn_bright_ok2.setFixedHeight(38)
        btn_bright_ok2.setStyleSheet(
            "background:#0a2a0a; border:1px solid #004400; color:#00cc44;"
            " border-radius:6px; font-weight:bold;"
        )
        btn_bright_ok2.clicked.connect(self._bright_confirm)
        h_bright2.addWidget(btn_bright_ok2)
        btn_skip_all = QPushButton(tr("cmw_nothing_changes"))
        btn_skip_all.setObjectName("skip")
        btn_skip_all.clicked.connect(self._bright_skip)
        h_bright2.addWidget(btn_skip_all)
        spec_v.addLayout(h_bright2)
        v.addWidget(self._bright_specific_section)

        # ── Section couleurs (affichée en 2e) ─────────────────────────────────
        self._color_section = QFrame()
        color_v = QVBoxLayout(self._color_section)
        color_v.setContentsMargins(0, 0, 0, 0)
        color_v.setSpacing(10)

        lbl_color_intro = QLabel(
            tr("cmw_color_test")
        )
        lbl_color_intro.setObjectName("sub"); lbl_color_intro.setWordWrap(True)
        color_v.addWidget(lbl_color_intro)

        self._led_vel_label = QLabel(tr("cmw_velocity_none"))
        self._led_vel_label.setStyleSheet("font-size: 12pt; color: #00aaff;")
        color_v.addWidget(self._led_vel_label)

        color_grid = QGridLayout(); color_grid.setSpacing(8)
        self._led_color_btns = {}
        for i, (name, hex_col, _vel) in enumerate(_COLOR_CHOICES):
            btn = QPushButton(name)
            btn.setFixedHeight(36)
            # Couleurs claires (blanc, jaune) : fond sombre sinon le texte est invisible
            r = int(hex_col[1:3], 16)
            g = int(hex_col[3:5], 16)
            b = int(hex_col[5:7], 16)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            if luminance > 0.65:
                style = (
                    f"background: #1e1e1e; border: 2px solid {hex_col}; "
                    f"color: {hex_col}; border-radius: 5px;"
                )
            else:
                style = (
                    f"background: {hex_col}22; border: 1px solid {hex_col}55; "
                    f"color: {hex_col}; border-radius: 5px;"
                )
            btn.setStyleSheet(style)
            btn.clicked.connect(lambda checked=False, n=name: self._led_color_chosen(n))
            color_grid.addWidget(btn, i // 5, i % 5)
            self._led_color_btns[name] = btn
        color_v.addLayout(color_grid)

        btn_skip_color = QPushButton(tr("cmw_skip_colour"))
        btn_skip_color.setObjectName("skip")
        btn_skip_color.clicked.connect(self._led_skip)
        color_v.addWidget(btn_skip_color)
        v.addWidget(self._color_section)

        v.addStretch()
        return w

    def _build_save(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(14)

        lbl_title = QLabel(tr("cmw_test_done"))
        lbl_title.setObjectName("title")
        v.addWidget(lbl_title)

        self._save_summary = QTextEdit()
        self._save_summary.setReadOnly(True)
        self._save_summary.setFixedHeight(130)
        v.addWidget(self._save_summary)

        v.addSpacing(6)

        # ── Action principale : installer le profil et s'en servir tout de suite ──
        # L'utilisateur vient de mapper son contrôleur ; ce qu'il veut d'abord,
        # c'est le voir marcher — pas envoyer un mail et attendre une réponse.
        frame_use = QFrame(); frame_use.setObjectName("card")
        fu = QVBoxLayout(frame_use); fu.setContentsMargins(16, 14, 16, 14); fu.setSpacing(10)

        lbl_use_title = QLabel(tr("cmw_use_title"))
        lbl_use_title.setStyleSheet("color: #00cc44; font-weight: bold; font-size: 11pt;")
        fu.addWidget(lbl_use_title)

        lbl_use_sub = QLabel(tr("cmw_use_hint"))
        lbl_use_sub.setObjectName("sub"); lbl_use_sub.setWordWrap(True)
        fu.addWidget(lbl_use_sub)

        self._btn_use = QPushButton(tr("cmw_use_btn"))
        self._btn_use.setFixedHeight(48)
        self._btn_use.setStyleSheet(
            "QPushButton { background:#0a2a0a; border:2px solid #00aa33; color:#00ff66;"
            " border-radius:6px; font-weight:bold; font-size:12pt; }"
            "QPushButton:hover { background:#0e3a0e; border-color:#00cc44; }"
        )
        self._btn_use.clicked.connect(self._do_save)
        fu.addWidget(self._btn_use)

        self._save_confirm = QLabel("")
        self._save_confirm.setObjectName("sub")
        self._save_confirm.setWordWrap(True)
        self._save_confirm.setVisible(False)
        fu.addWidget(self._save_confirm)
        v.addWidget(frame_use)

        v.addSpacing(4)

        # ── Partager son profil à la communauté ───────────────────────────────
        #
        # Cet argumentaire ouvrait l'assistant. Il y était au mauvais endroit :
        # on demandait d'adhérer à une communauté avant d'avoir rien obtenu.
        # Ici, l'utilisateur vient de faire marcher son contrôleur — c'est le
        # moment où rendre service à son tour a du sens.
        frame_share = QFrame(); frame_share.setObjectName("card")
        fs = QVBoxLayout(frame_share); fs.setContentsMargins(16, 14, 16, 14); fs.setSpacing(8)

        lbl_community = QLabel(tr("cmw_community"))
        lbl_community.setStyleSheet("color: #00aaff; font-size: 11pt; font-weight: bold;")
        fs.addWidget(lbl_community)

        lbl_share = QLabel(tr("cmw_share_title"))
        lbl_share.setObjectName("sub"); lbl_share.setWordWrap(True)
        fs.addWidget(lbl_share)

        lbl_promise = QLabel(tr("cmw_mail_notice"))
        lbl_promise.setStyleSheet("color: #00cc44; font-size: 9pt;")
        lbl_promise.setWordWrap(True)
        fs.addWidget(lbl_promise)

        h_share = QHBoxLayout(); h_share.setSpacing(8)
        btn_export = QPushButton(tr("cmw_export_btn")); btn_export.setObjectName("skip")
        btn_export.setFixedHeight(34); btn_export.clicked.connect(self._export_profile)
        h_share.addWidget(btn_export)
        btn_send = QPushButton(tr("cmw_send_btn")); btn_send.setObjectName("skip")
        btn_send.setFixedHeight(34); btn_send.setToolTip(tr("cmw_send_hint"))
        btn_send.clicked.connect(self._share_profile)
        h_share.addWidget(btn_send)
        h_share.addStretch()
        fs.addLayout(h_share)
        v.addWidget(frame_share)

        v.addStretch()

        h = QHBoxLayout()
        h.addStretch()
        btn_close = QPushButton(tr("cmw_close")); btn_close.setObjectName("skip")
        btn_close.clicked.connect(self.accept)
        h.addWidget(btn_close)
        v.addLayout(h)
        return w

    # ─── Page générique pour mutes/effects ───────────────────────────────────

    def _build_generic_map_page(self, title, subtitle, attr_prefix, skip_all_label):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(14)

        lbl_title = QLabel(title); lbl_title.setObjectName("title")
        v.addWidget(lbl_title)
        lbl_sub = QLabel(subtitle); lbl_sub.setObjectName("sub"); lbl_sub.setWordWrap(True)
        v.addWidget(lbl_sub)
        v.addSpacing(8)

        instr = QLabel(tr("cmw_f_button1"))
        instr.setStyleSheet("font-size: 14pt; color: #ddd;")
        v.addWidget(instr)

        listen = QLabel(tr("cmw_listening"))
        listen.setObjectName("listen")
        v.addWidget(listen)

        progress = QLabel("")
        progress.setObjectName("sub")
        v.addWidget(progress)

        v.addSpacing(8)
        h_btns = QHBoxLayout(); h_btns.setSpacing(10)

        btn_skip = QPushButton(tr("cmw_skip")); btn_skip.setObjectName("skip")
        btn_done = QPushButton(skip_all_label); btn_done.setObjectName("danger")
        h_btns.addWidget(btn_skip); h_btns.addWidget(btn_done)
        v.addLayout(h_btns)
        v.addStretch()

        # Stocker refs par préfixe
        setattr(self, f"_{attr_prefix}_instr",    instr)
        setattr(self, f"_{attr_prefix}_listen",   listen)
        setattr(self, f"_{attr_prefix}_progress", progress)
        setattr(self, f"_{attr_prefix}_skip_btn", btn_skip)
        setattr(self, f"_{attr_prefix}_done_btn", btn_done)
        return w

    # ─── Navigation entre pages ───────────────────────────────────────────────

    def _show_page(self, idx):
        self._stop_capture()
        self._pulse_timer.stop()
        self._stack.setCurrentIndex(idx)
        steps = ["Nom", "Dimensions", "Pads", "Mutes", "Faders", "Effets", "LEDs", "Sauvegarde"]
        # Total lu sur la pile, jamais ecrit en dur : la phrase traduite annoncait
        # « /9 » dans les cinq langues alors que l'assistant n'a plus que 8 pages.
        self._step_label.setText(
            tr("cmw_f_step", a0=idx + 1, a1=steps[idx], a2=self._stack.count()))

        if idx == self.PAGE_NAME:
            # Le contrôleur a pu être branché APRÈS l'ouverture de l'assistant.
            self._refresh_ports()
        elif idx == self.PAGE_DIMENSIONS:
            self._dim_seen = []
            self._rebuild_dim_grid()
            self._start_capture(self._on_dim_midi)
        elif idx == self.PAGE_PADS:
            self._start_pad_phase()
        elif idx == self.PAGE_MUTES:
            self._start_generic_phase("mute", self._mute_map, self._fader_count, self._on_mute_midi, self._mutes_done)
        elif idx == self.PAGE_FADERS:
            self._start_fader_phase()
        elif idx == self.PAGE_EFFECTS:
            self._start_generic_phase("effect", self._effect_map, self._effect_count, self._on_effect_midi, self._effects_done)
        elif idx == self.PAGE_LEDS:
            self._start_led_phase()
        elif idx == self.PAGE_SAVE:
            self._release_ports_for_handler()
            self._populate_save_page()

    def _goto_leds_or_save(self):
        """Étape LED si elle a un sens, sinon la page finale.

        Point unique : quatre transitions y menaient, la règle DJ aurait dérivé
        à la première modification de l'une d'elles.

        Sur un contrôleur DJ, les LED des pads sont pilotées par le logiciel DJ.
        Les tester ne prouverait rien et les ferait clignoter en plein set —
        deux écrivains sur la même LED, exactement ce qu'on évite ailleurs.
        """
        if self._pad_map and not getattr(self, "_dj_mode", False):
            self._show_page(self.PAGE_LEDS)
        else:
            self._show_page(self.PAGE_SAVE)

    def _next_after_pads(self):
        if self._fader_count > 0:
            self._show_page(self.PAGE_MUTES)
        elif self._effect_count > 0:
            self._show_page(self.PAGE_EFFECTS)
        else:
            self._goto_leds_or_save()

    def _next_after_mutes(self):
        if self._fader_count > 0:
            self._show_page(self.PAGE_FADERS)
        elif self._effect_count > 0:
            self._show_page(self.PAGE_EFFECTS)
        else:
            self._goto_leds_or_save()

    def _next_after_faders(self):
        if self._effect_count > 0:
            self._show_page(self.PAGE_EFFECTS)
        else:
            self._goto_leds_or_save()

    def _next_after_effects(self):
        self._goto_leds_or_save()

    def _load_profile_into_state(self, data):
        self._profile_name  = data.get("name", "")
        self._keywords      = data.get("keywords", [])
        self._grid_rows     = data.get("grid_rows", 8)
        self._grid_cols     = data.get("grid_cols", 8)
        self._fader_count   = data.get("fader_count", 8)
        self._effect_count  = data.get("effect_count", 8)
        self._pad_map       = {tuple(map(int, k.split(","))): v for k, v in data.get("pad_map", {}).items()}
        self._mute_map      = {int(k): v for k, v in data.get("mute_map", {}).items()}
        self._fader_map     = {int(k): v for k, v in data.get("fader_map", {}).items()}
        self._effect_map    = {int(k): v for k, v in data.get("effect_map", {}).items()}
        self._led_colors    = {int(k): v for k, v in data.get("led_velocity_map", {}).items()}

    # ─── Logique page Name ────────────────────────────────────────────────────

    def _port_selected(self, idx):
        self._update_name_next_state()
        port = self._combo_ports.currentData()
        if port:
            self._inp_keyword.setText(_port_keyword(port))
        self._open_own_port(port)

    def _refresh_ports(self):
        """Relit la liste des ports MIDI et resélectionne le port courant."""
        previous = self._combo_ports.currentData()
        ports = _get_midi_ports()
        self._combo_ports.blockSignals(True)
        self._combo_ports.clear()
        self._combo_ports.addItem(tr("cmw_no_port"), None)
        for p in ports:
            self._combo_ports.addItem(p, p)
        self._combo_ports.blockSignals(False)

        # Le port déjà choisi s'il est toujours là ; sinon, quand une seule
        # entrée existe, c'est forcément celle du contrôleur à configurer.
        target = previous if previous in ports else (ports[0] if len(ports) == 1 else None)
        if target:
            self._combo_ports.setCurrentIndex(ports.index(target) + 1)  # → _port_selected
        else:
            self._open_own_port(None)

    def _open_own_port(self, port_name):
        """Ouvre le port choisi pour y écouter les appuis (et piloter les LEDs)."""
        self._close_own_ports()
        self._port_error = ""
        self._rx_count   = 0
        self._last_raw   = None
        self._own_port   = ""

        if not port_name:
            self._update_port_status('none')
            return

        # Port déjà ouvert par MyStrow (contrôleur reconnu) : la plupart des
        # pilotes MIDI Windows n'acceptent qu'un seul client, inutile de lui
        # disputer l'accès — on récupère ses messages via le handler.
        try:
            handler_ports = self.midi_handler.open_input_names() if self.midi_handler else []
        except Exception:
            handler_ports = []
        if port_name in handler_ports:
            self._own_port = port_name
            self._update_port_status('handler')
            return

        mod = _rtmidi_module()
        if not mod:
            self._port_error = "python-rtmidi"
            self._update_port_status('error')
            return

        try:
            port_in = mod.MidiIn()
            port_in.open_port(port_in.get_ports().index(port_name))
            port_in.set_callback(self._on_raw_midi)
            port_in.ignore_types(sysex=True, timing=True, active_sense=True)
            self._own_in   = port_in
            self._own_port = port_name
        except Exception as e:
            self._own_in = None
            self._port_error = f"{type(e).__name__}: {e}"
            self._update_port_status('error')
            return

        self._open_own_output(port_name)
        self._update_port_status('own')

    def _open_own_output(self, in_name):
        """Ouvre la sortie du même appareil — sans elle, le test des LEDs est muet."""
        mod = _rtmidi_module()
        if not mod:
            return
        outs = _get_midi_out_ports()
        target = in_name if in_name in outs else None
        if target is None:
            kw = _port_keyword(in_name)
            target = next((p for p in outs if kw and kw in p.upper()), None)
        if target is None:
            return
        try:
            port_out = mod.MidiOut()
            port_out.open_port(outs.index(target))
            self._own_out = port_out
        except Exception:
            self._own_out = None

    def _close_own_ports(self):
        for port in (self._own_in, self._own_out):
            if port is None:
                continue
            try:
                port.cancel_callback()
            except Exception:
                pass
            try:
                port.close_port()
            except Exception:
                pass
        self._own_in  = None
        self._own_out = None

    def _release_ports_for_handler(self):
        """Rend le contrôleur au MIDIHandler avant la page de sauvegarde.

        Enregistrer le profil déclenche `connect_controller()` : si l'assistant
        tenait encore le port, la reconnexion échouerait sur tout appareil qui
        n'accepte qu'un seul client.
        """
        self._turn_off_test_pad()
        self._close_own_ports()

    def _update_port_status(self, state):
        if not hasattr(self, '_port_status'):
            return
        if state == 'own':
            text, color = tr("cmw_port_open"), "#00cc44"
        elif state == 'handler':
            text, color = tr("cmw_port_shared"), "#00cc44"
        elif state == 'error':
            text, color = tr("cmw_port_busy", e=self._port_error), "#ff5555"
        else:
            text, color = tr("cmw_port_none"), "#888888"
        self._port_status.setText(text)
        self._port_status.setStyleSheet(f"color:{color}; font-size:9pt;")

    def _name_next(self):
        name = self._inp_name.text().strip()
        if not name:
            self._inp_name.setPlaceholderText(tr("cmw_name_required"))
            return
        self._profile_name = name
        kw = self._inp_keyword.text().strip().upper()
        self._keywords = [kw] if kw else []

        # Contrôleur DJ : pads seulement. Les faders et les boutons d'effet
        # tombent à 0, ce qui suffit à faire sauter leurs étapes — toute la
        # navigation de l'assistant est déjà pilotée par ces compteurs.
        self._dj_mode = self._chk_dj.isChecked()
        if self._dj_mode:
            self._spin_rows.setValue(2)
            self._spin_cols.setValue(4)
            self._spin_faders.setValue(0)
            self._spin_effects.setValue(0)
        self._show_page(self.PAGE_DIMENSIONS)

    # ─── Logique page Dimensions ──────────────────────────────────────────────

    def _rebuild_dim_grid(self):
        """Redessine la grille d'aperçu et rejoue les pads déjà reçus."""
        for child in self._dim_grid_area.findChildren(_PadGrid):
            child.setParent(None)
            child.deleteLater()
        rows = max(1, self._spin_rows.value())
        cols = max(1, self._spin_cols.value())
        self._dim_grid_widget = _PadGrid(rows, cols)
        self._dim_grid_layout.addWidget(self._dim_grid_widget)
        # Les pads deja pressés restent allumés : changer une dimension ne doit
        # pas obliger a tout re-presser pour comparer deux tailles.
        for i, _ in enumerate(self._dim_seen):
            if i >= rows * cols:
                break
            self._dim_grid_widget.set_mapped(i // cols, i % cols)
        self._update_dim_count()

    def _update_dim_count(self):
        n = len(self._dim_seen)
        total = max(1, self._spin_rows.value()) * max(1, self._spin_cols.value())
        couleur = "#00cc44" if 0 < n <= total else ("#e6a817" if n > total else "#666")
        self._dim_count.setText(f"{n} / {total}")
        self._dim_count.setStyleSheet(f"color:{couleur}; font-weight:bold;")

    def _on_dim_midi(self, msg):
        """Note reçue pendant la page Dimensions : allume la case suivante.

        On ne mappe RIEN ici — c'est un simple comptage de pads distincts, pour
        que l'utilisateur vérifie sa grille avant de se lancer dans le mappage.
        """
        if len(msg) < 3:
            return
        status, note, vel = msg[0], msg[1], msg[2]
        if (status & 0xF0) != 0x90 or vel <= 0:
            return
        cle = (status & 0x0F, note)
        if cle in self._dim_seen:
            return
        self._dim_seen.append(cle)
        cols = max(1, self._spin_cols.value())
        i = len(self._dim_seen) - 1
        if self._dim_grid_widget is not None and i < self._dim_grid_widget.rows * cols:
            self._dim_grid_widget.set_mapped(i // cols, i % cols)
        self._update_dim_count()

    def _dimensions_next(self):
        self._grid_rows   = self._spin_rows.value()
        self._grid_cols   = self._spin_cols.value()
        self._fader_count = self._spin_faders.value()
        self._effect_count = self._spin_effects.value()

        if self._grid_rows > 0 and self._grid_cols > 0:
            self._show_page(self.PAGE_PADS)
        elif self._fader_count > 0:
            self._show_page(self.PAGE_MUTES)
        elif self._effect_count > 0:
            self._show_page(self.PAGE_EFFECTS)
        else:
            self._show_page(self.PAGE_SAVE)

    # ─── Logique page Pads ────────────────────────────────────────────────────

    def _start_pad_phase(self):
        self._pad_row = 0
        self._pad_col = 0
        self._pad_map = {}

        # Reconstruire la grille visuelle
        for child in self._pad_grid_area.findChildren(QFrame):
            if child is not self._pad_grid_area:
                child.deleteLater()
        for child in self._pad_grid_area.findChildren(_PadGrid):
            child.deleteLater()

        grid = _PadGrid(self._grid_rows, self._grid_cols)
        self._pad_grid_widget = grid
        self._pad_grid_layout.addWidget(grid)

        self._update_pad_ui()
        self._start_capture(self._on_pad_midi)
        self._start_pulse(self._listen_label)

    def _update_pad_ui(self):
        r, c = self._pad_row, self._pad_col
        if self._pad_grid_widget:
            self._pad_grid_widget.set_target(r, c)
        self._pad_instr.setText(
            tr("cmw_f_press_pad", a0=c + 1, a1=r + 1)
        )

    def _on_pad_midi(self, msg):
        if len(msg) < 3:
            return
        status, note, vel = msg[0], msg[1], msg[2]
        if (status & 0xF0) == 0x90 and vel > 0:
            channel = status & 0x0F
            key = (self._pad_row, self._pad_col)
            self._pad_map[key] = {"channel": channel, "note": note}
            if self._pad_grid_widget:
                self._pad_grid_widget.set_mapped(self._pad_row, self._pad_col)
            self._pad_advance()

    def _pad_advance(self):
        self._pad_col += 1
        if self._pad_col >= self._grid_cols:
            self._pad_col = 0
            self._pad_row += 1
        if self._pad_row >= self._grid_rows:
            self._pad_done()
            return
        self._update_pad_ui()

    def _pad_skip_cell(self):
        if self._pad_grid_widget:
            self._pad_grid_widget.set_skipped(self._pad_row, self._pad_col)
        self._pad_advance()

    def _pad_end_row(self):
        if self._pad_grid_widget:
            for c in range(self._pad_col, self._grid_cols):
                self._pad_grid_widget.set_skipped(self._pad_row, c)
        self._pad_col = 0
        self._pad_row += 1
        if self._pad_row >= self._grid_rows:
            self._pad_done()
            return
        self._update_pad_ui()

    def _pad_done(self):
        self._stop_capture()
        self._pulse_timer.stop()
        self._next_after_pads()

    # ─── Logique pages Mutes / Effects (générique) ────────────────────────────

    def _start_generic_phase(self, prefix, target_map, count, midi_cb, done_cb):
        target_map.clear()
        setattr(self, f"_{prefix}_cursor", 0)

        skip_btn = getattr(self, f"_{prefix}_skip_btn")
        done_btn = getattr(self, f"_{prefix}_done_btn")

        try:
            skip_btn.clicked.disconnect()
        except RuntimeError:
            pass
        try:
            done_btn.clicked.disconnect()
        except RuntimeError:
            pass

        skip_btn.clicked.connect(lambda: self._generic_skip(prefix, target_map, count, midi_cb, done_cb))
        done_btn.clicked.connect(done_cb)

        self._update_generic_ui(prefix, count)
        self._start_capture(midi_cb)
        listen = getattr(self, f"_{prefix}_listen")
        self._start_pulse(listen)

    def _update_generic_ui(self, prefix, total):
        cursor = getattr(self, f"_{prefix}_cursor", 0)
        instr    = getattr(self, f"_{prefix}_instr")
        progress = getattr(self, f"_{prefix}_progress")
        if prefix == "mute":
            instr.setText(
                tr("cmw_f_press_strip_btn", a0=cursor + 1)
            )
        else:
            instr.setText(tr("cmw_f_press_fx_btn", a0=cursor + 1))
        progress.setText(tr("cmw_f_strip", a0=cursor + 1, total=total))

    def _generic_skip(self, prefix, target_map, count, midi_cb, done_cb):
        cursor = getattr(self, f"_{prefix}_cursor", 0)
        cursor += 1
        setattr(self, f"_{prefix}_cursor", cursor)
        if cursor >= count:
            done_cb()
        else:
            self._update_generic_ui(prefix, count)

    def _on_mute_midi(self, msg):
        if len(msg) < 3:
            return
        status, note, vel = msg[0], msg[1], msg[2]
        if (status & 0xF0) == 0x90 and vel > 0:
            channel = status & 0x0F
            cursor = self._mute_cursor
            self._mute_map[cursor] = {"channel": channel, "note": note}
            self._mute_cursor += 1
            if self._mute_cursor >= self._fader_count:
                self._mutes_done()
            else:
                self._update_generic_ui("mute", self._fader_count)

    def _mutes_done(self):
        self._stop_capture(); self._pulse_timer.stop()
        self._next_after_mutes()

    def _on_effect_midi(self, msg):
        if len(msg) < 3:
            return
        status, note, vel = msg[0], msg[1], msg[2]
        if (status & 0xF0) == 0x90 and vel > 0:
            channel = status & 0x0F
            cursor = self._effect_cursor
            self._effect_map[cursor] = {"channel": channel, "note": note}
            self._effect_cursor += 1
            if self._effect_cursor >= self._effect_count:
                self._effects_done()
            else:
                self._update_generic_ui("effect", self._effect_count)

    def _effects_done(self):
        self._stop_capture(); self._pulse_timer.stop()
        self._next_after_effects()

    # ─── Logique page Faders ──────────────────────────────────────────────────

    def _start_fader_phase(self):
        self._fader_map.clear()
        self._fader_cursor = 0
        self._update_fader_ui()
        self._start_capture(self._on_fader_midi)
        self._start_pulse(self._fader_listen)

    def _update_fader_ui(self):
        self._fader_instr.setText(tr("cmw_f_move_fader", a0=self._fader_cursor + 1))
        self._fader_progress.setText(f"{self._fader_cursor + 1} / {self._fader_count}")

    def _on_fader_midi(self, msg):
        if len(msg) < 3:
            return
        status, cc, val = msg[0], msg[1], msg[2]
        if (status & 0xF0) == 0xB0 and val > 64:  # doit être à fond (>50%)
            channel = status & 0x0F
            # Ignorer un CC déjà enregistré pour un fader précédent
            if any(v["channel"] == channel and v["cc"] == cc for v in self._fader_map.values()):
                return
            self._fader_map[self._fader_cursor] = {"channel": channel, "cc": cc}
            self._fader_cursor += 1
            if self._fader_cursor >= self._fader_count:
                self._fader_done()
            else:
                self._update_fader_ui()

    def _fader_skip(self):
        self._fader_cursor += 1
        if self._fader_cursor >= self._fader_count:
            self._fader_done()
        else:
            self._update_fader_ui()

    def _fader_done(self):
        self._stop_capture(); self._pulse_timer.stop()
        self._next_after_faders()

    # ─── Logique page LEDs ────────────────────────────────────────────────────

    def _get_first_pad_entry(self):
        for r in range(self._grid_rows):
            for c in range(self._grid_cols):
                if (r, c) in self._pad_map:
                    return self._pad_map[(r, c)]
        return None

    def _start_led_phase(self):
        self._led_colors      = {}
        self._led_vel_idx     = 0
        self._led_dim_velocity = None
        self._bright_ref_entry = self._get_first_pad_entry()

        if self._bright_ref_entry is None:
            self._show_page(self.PAGE_SAVE)
            return

        # Nettoyer tous les LEDs avant de commencer les tests
        self._reset_all_leds()

        # Phase 1 : slider libre
        self._bright_section.setVisible(True)
        self._bright_specific_section.setVisible(False)
        self._color_section.setVisible(False)
        self._led_phase_label.setText(tr("cmw_step1"))
        self._bright_alt_ch = 0
        self._bright_alt_channel_label.setText(tr("cmw_channel1"))
        self._bright_specific_vel = None

        self._bright_slider.setValue(64)
        self._send_to_pad(
            self._bright_ref_entry.get("channel", 0),
            self._bright_ref_entry["note"],
            64,
        )

    def _on_bright_slider(self, val):
        self._bright_vel_label.setText(tr("cmw_f_velocity", val=val))
        entry = self._bright_ref_entry
        if entry:
            self._send_to_pad(entry.get("channel", 0), entry["note"], val)

    def _bright_try_specific(self):
        """Phase 1 échoue → affiche la phase 2 (velocités précises)."""
        self._bright_section.setVisible(False)
        self._bright_specific_section.setVisible(True)
        self._led_phase_label.setText(tr("cmw_step1_retry"))
        # Éteindre le pad pour partir d'un état neutre
        self._turn_off_test_pad()

    def _bright_send_specific(self, vel):
        """Envoie une velocité précise au pad depuis la grille phase 2."""
        self._bright_specific_vel = vel
        entry = self._bright_ref_entry
        if entry:
            self._send_to_pad(entry.get("channel", 0), entry["note"], vel)

    def _bright_test_channel(self):
        """Envoie la note sur le prochain canal MIDI (1→6) pour tester le mode APC/Launchpad."""
        self._bright_alt_ch = (self._bright_alt_ch + 1) % 7  # canaux 0-6
        self._bright_alt_channel_label.setText(tr("cmw_f_channel", a0=self._bright_alt_ch + 1))
        entry = self._bright_ref_entry
        if entry:
            self._send_raw([0x90 | self._bright_alt_ch, entry["note"],
                            self._bright_slider.value()])

    def _bright_test_noteoff(self):
        """Envoie Note Off (0x80) avec la vélocité du slider — certains contrôleurs allument la LED en mode dim."""
        entry = self._bright_ref_entry
        if entry:
            self._send_raw([0x80 | entry.get("channel", 0), entry["note"],
                            self._bright_slider.value()])

    def _bright_confirm(self):
        # Phase 2 active → prendre la dernière velocité précise cliquée, sinon le slider
        if self._bright_specific_section.isVisible() and self._bright_specific_vel is not None:
            self._led_dim_velocity = self._bright_specific_vel
        else:
            self._led_dim_velocity = self._bright_slider.value()
        self._turn_off_test_pad()
        self._start_color_phase()

    def _bright_skip(self):
        """Phase 2 échoue aussi → pas de contrôle de luminosité, on passe aux couleurs."""
        self._led_dim_velocity = None
        self._turn_off_test_pad()
        self._start_color_phase()

    def _turn_off_test_pad(self):
        entry = getattr(self, '_bright_ref_entry', None)
        if entry:
            self._send_to_pad(entry.get("channel", 0), entry["note"], 0)

    def _send_to_pad(self, channel, note, vel):
        self._send_raw([0x90 | channel, note, vel])

    def _start_color_phase(self):
        self._led_vel_idx = 0
        self._bright_section.setVisible(False)
        self._color_section.setVisible(True)
        self._led_phase_label.setText(tr("cmw_step2"))
        self._send_led_test()

    def _send_led_test(self):
        if self._led_vel_idx >= len(_LED_VELOCITIES):
            self._show_page(self.PAGE_SAVE)
            return
        vel, _label, _ = _LED_VELOCITIES[self._led_vel_idx]
        self._led_vel_label.setText(tr("cmw_f_velocity_test", vel=vel))
        entry = self._bright_ref_entry or self._get_first_pad_entry()
        if entry:
            self._send_to_pad(entry.get("channel", 0), entry["note"], vel)

    def _led_color_chosen(self, color_name):
        vel, _, __ = _LED_VELOCITIES[self._led_vel_idx]
        if color_name != "Éteint":
            self._led_colors[vel] = color_name
        self._led_vel_idx += 1
        self._send_led_test()

    def _led_skip(self):
        self._turn_off_test_pad()
        self._show_page(self.PAGE_SAVE)

    # ─── Logique page Save ────────────────────────────────────────────────────

    def _populate_save_page(self):
        lines = [
            f"Contrôleur : {self._profile_name}",
            f"Grille pads : {self._grid_rows} lignes × {self._grid_cols} colonnes"
                f"  →  {len(self._pad_map)} pad(s) testés",
            f"Faders      : {len(self._fader_map)} / {self._fader_count} détectés",
            f"Boutons mute: {len(self._mute_map)} / {self._fader_count} détectés",
            f"Boutons effet: {len(self._effect_map)} / {self._effect_count} détectés",
            f"LEDs        : {len(self._led_colors)} couleur(s) identifiée(s)",
        ]
        self._save_summary.setPlainText("\n".join(lines))

    def _build_profile_dict(self):
        """Construit le dict de profil à partir des données collectées."""
        safe = "".join(
            c if c.isalnum() or c == "_" else "_"
            for c in self._profile_name.lower()
        ).strip("_")

        # Construire led_velocity_map : vel -> velocity AKAI standard (identité si testé,
        # sinon fallback sur les valeurs AKAI par défaut)
        led_vel_map = {}
        for vel, color in self._led_colors.items():
            led_vel_map[str(vel)] = color

        # Construire le led_colors mapping standard (nom → velocity sur ce contrôleur)
        led_colors_out = {}
        # Inverser : pour chaque (vel, color) testé, on sait que vel → color
        # On cherche à obtenir color → vel
        for vel, color in self._led_colors.items():
            if color not in led_colors_out:
                led_colors_out[color] = vel
        # Fallback AKAI pour les couleurs non testées
        for color, default_vel in _COLOR_DEFAULT_VEL.items():
            if color not in led_colors_out:
                led_colors_out[color] = default_vel

        return {
            "id":           safe,
            "name":         self._profile_name,
            "version":      "1.0",
            "keywords":     self._keywords,
            "grid_rows":    self._grid_rows,
            "grid_cols":    self._grid_cols,
            "fader_count":  self._fader_count,
            "effect_count": self._effect_count,
            "pad_map":    {f"{r},{c}": v for (r, c), v in self._pad_map.items()},
            "mute_map":   {str(k): v for k, v in self._mute_map.items()},
            "fader_map":  {str(k): v for k, v in self._fader_map.items()},
            "effect_map": {str(k): v for k, v in self._effect_map.items()},
            "led_velocity_map": led_vel_map,
            "led_colors":       led_colors_out,
            "led_dim_velocity":  getattr(self, "_led_dim_velocity", None),
        }

    def _do_save(self):
        data = self._build_profile_dict()
        # Sans chemin d'édition, ne jamais écraser un profil du même nom en
        # silence : l'utilisateur perdrait un mapping qu'il croyait conservé.
        path = self._edit_file or unique_profile_path(data["name"])
        try:
            path = save_profile(data, path)
        except OSError as e:
            self._save_confirm.setText(tr("cmw_save_failed", e=str(e)))
            self._save_confirm.setStyleSheet("color:#ff5555; font-size:9pt;")
            self._save_confirm.setVisible(True)
            return
        self._edit_file = path
        self.profile_saved.emit(path)
        self._btn_use.setText(tr("cmw_use_done"))
        self._save_confirm.setText(tr("cmw_save_ok", path=path))
        self._save_confirm.setStyleSheet("color:#00cc44; font-size:9pt;")
        self._save_confirm.setVisible(True)

    def _export_profile(self):
        """Enregistre le profil dans un fichier choisi — pour l'échanger."""
        data = self._build_profile_dict()
        suggested = f"{data.get('id') or 'controleur'}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("cmw_export_btn"), suggested, "Profil MyStrow (*.json)")
        if not path:
            return
        try:
            export_profile(data, path)
        except OSError as e:
            QMessageBox.warning(self, tr("cmw_export_btn"), tr("cmw_save_failed", e=str(e)))
            return
        self._save_confirm.setText(tr("cmw_export_ok", path=path))
        self._save_confirm.setStyleSheet("color:#00cc44; font-size:9pt;")
        self._save_confirm.setVisible(True)

    def load_for_edit(self, path: str):
        """Ouvre l'assistant sur un profil existant : mêmes nom, mot-clé et
        dimensions pré-remplis, et la sauvegarde réécrit CE fichier."""
        data = load_profile(path)
        self._edit_file = path
        self._load_profile_into_state(data)
        self._show_page(self.PAGE_NAME)
        self._inp_name.setText(self._profile_name)
        self._inp_keyword.setText(self._keywords[0] if self._keywords else "")
        self._spin_rows.setValue(self._grid_rows)
        self._spin_cols.setValue(self._grid_cols)
        self._spin_faders.setValue(self._fader_count)
        self._spin_effects.setValue(self._effect_count)

    def _share_profile(self):
        data = self._build_profile_dict()
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        subject = urllib.parse.quote(f"[MyStrow] Contrôleur non reconnu : {self._profile_name}")
        body = urllib.parse.quote(
            f"Bonjour,\n\n"
            f"Mon contrôleur MIDI n'est pas reconnu par MyStrow. "
            f"Je viens de faire le test de mapping — voici les résultats.\n\n"
            f"Contrôleur : {self._profile_name}\n\n"
            f"--- Données de test (ne pas modifier) ---\n\n"
            f"{json_str}\n\n"
            f"Merci de revenir vers moi rapidement !"
        )
        url = QUrl(f"mailto:Nicolas@mystrow.fr?subject={subject}&body={body}")
        QDesktopServices.openUrl(url)

    # ─── MIDI capture ─────────────────────────────────────────────────────────

    def _start_capture(self, callback):
        self._capture_cb = callback
        # Pas de port à nous : le contrôleur est déjà reconnu par MyStrow, ses
        # messages passent par le handler (qui les remonte sur le thread Qt).
        if self.midi_handler and not self._own_in:
            self.midi_handler.set_raw_capture(self._queue_from_handler)

    def _stop_capture(self):
        self._capture_cb = None
        if self.midi_handler:
            self.midi_handler.clear_raw_capture()

    def _queue_from_handler(self, msg):
        with self._rx_lock:
            self._rx_queue.append(list(msg))

    def _on_raw_midi(self, event, data=None):
        """Callback rtmidi — thread MIDI : on empile, rien d'autre."""
        if (isinstance(event, tuple) and len(event) == 2
                and isinstance(event[0], (list, tuple))):
            msg = event[0]          # python-rtmidi : (message, delta)
        else:
            msg = event             # rtmidi2 : message seul
        if not msg:
            return
        with self._rx_lock:
            self._rx_queue.append(list(msg))

    def _drain_rx(self):
        """Vide la file sur le thread Qt et alimente l'étape en cours."""
        if not self._rx_queue:
            return
        with self._rx_lock:
            messages = self._rx_queue
            self._rx_queue = []

        page = self._stack.currentIndex()
        for msg in messages:
            self._rx_count += 1
            self._last_raw = msg
            callback = self._capture_cb
            if callback:
                try:
                    callback(msg)
                except Exception:
                    pass
            # Un callback peut faire changer de page (donc de cible) : on
            # s'arrête là plutôt que de verser le reste du lot dans l'étape
            # suivante, ce qui mapperait plusieurs cases d'un seul appui.
            if self._stack.currentIndex() != page:
                break

        if page == self.PAGE_NAME:
            raw = " ".join(f"{b:02X}" for b in (self._last_raw or []))
            self._port_status.setText(tr("cmw_port_rx", n=self._rx_count, raw=raw))
            self._port_status.setStyleSheet("color:#00cc44; font-size:9pt;")

    # ─── Sortie MIDI ──────────────────────────────────────────────────────────

    def _out_port(self):
        """Sortie à utiliser : la nôtre, sinon celle du MIDIHandler."""
        if self._own_out:
            return self._own_out
        if self.midi_handler and self.midi_handler.midi_out:
            return self.midi_handler.midi_out
        return None

    def _send_raw(self, message):
        out = self._out_port()
        if not out:
            return
        try:
            out.send_message(message)
        except Exception:
            pass

    # ─── Animation écoute ─────────────────────────────────────────────────────

    def _start_pulse(self, label):
        self._listen_label = label
        self._pulse_state = True
        self._pulse_timer.start(600)

    def _pulse_listen(self):
        if self._listen_label:
            self._pulse_state = not self._pulse_state
            color = "#00ff88" if self._pulse_state else "#005522"
            self._listen_label.setStyleSheet(f"color: {color}; font-size: 10pt; font-weight: bold;")

    # ─── Fermeture ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._stop_capture()
        self._pulse_timer.stop()
        self._rx_timer.stop()
        # Éteindre le pad de test LED si actif
        if self._led_vel_idx > 0 and self._pad_map:
            for _cell, entry in self._pad_map.items():
                self._send_raw([0x90 | entry.get("channel", 0), entry["note"], 0])
                break
        # Libérer le contrôleur : le MIDIHandler doit pouvoir le rouvrir.
        self._close_own_ports()
        super().closeEvent(event)
