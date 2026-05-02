"""
Assistant de mapping de contrôleur MIDI.
Permet de créer un profil pour n'importe quel contrôleur non supporté nativement.
"""
import json
import urllib.parse
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QStackedWidget, QWidget, QLineEdit,
    QFrame, QGridLayout, QScrollArea, QSizePolicy, QTextEdit, QSlider
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QDesktopServices
from PySide6.QtCore import QUrl

from controller_profile import list_profiles, save_profile
from core import MIDI_AVAILABLE

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


def _get_midi_ports():
    """Retourne la liste des ports MIDI IN disponibles."""
    if not MIDI_AVAILABLE:
        return []
    try:
        import rtmidi
        m = rtmidi.MidiIn()
        ports = m.get_ports()
        try:
            m.close_port()
        except Exception:
            pass
        return ports
    except Exception:
        try:
            import rtmidi2 as rtmidi
            m = rtmidi.MidiIn()
            ports = m.get_ports()
            return ports
        except Exception:
            return []


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
    PAGE_WELCOME    = 0
    PAGE_NAME       = 1
    PAGE_DIMENSIONS = 2
    PAGE_PADS       = 3
    PAGE_MUTES      = 4
    PAGE_FADERS     = 5
    PAGE_EFFECTS    = 6
    PAGE_LEDS       = 7
    PAGE_SAVE       = 8

    def __init__(self, midi_handler, parent=None):
        super().__init__(parent)
        self.midi_handler = midi_handler
        self.setWindowTitle("Mon contrôleur n'est pas reconnu — MyStrow")
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

        self._build_ui()
        self._reset_all_leds()
        self._show_page(self.PAGE_WELCOME)

    # ─── Reset LEDs ──────────────────────────────────────────────────────────

    def _reset_all_leds(self):
        """Éteint tous les LEDs du contrôleur (notes 0-127, canaux 0-8)."""
        if not (self.midi_handler and self.midi_handler.midi_out):
            return
        try:
            for ch in range(9):
                for note in range(128):
                    self.midi_handler.midi_out.send_message([0x90 | ch, note, 0])
        except Exception:
            pass

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
            self._build_welcome(),
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

    def _build_welcome(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(16)

        lbl_title = QLabel("🎹  Mon contrôleur n'est pas reconnu")
        lbl_title.setObjectName("title")
        v.addWidget(lbl_title)

        sep = QFrame(); sep.setObjectName("sep"); sep.setFixedHeight(1)
        v.addWidget(sep)

        # Bloc communauté
        card = QFrame(); card.setObjectName("card")
        card_v = QVBoxLayout(card); card_v.setContentsMargins(20, 16, 20, 16); card_v.setSpacing(10)

        lbl_community = QLabel("MyStrow, c'est une communauté.")
        lbl_community.setStyleSheet("color: #00aaff; font-size: 12pt; font-weight: bold;")
        card_v.addWidget(lbl_community)

        lbl_explain = QLabel(
            "Votre contrôleur n'est pas encore dans notre liste ? Pas de problème.\n"
            "Faites le test ci-dessous en 3 minutes — appuyez sur vos pads, bougez vos faders —\n"
            "et on revient vers vous rapidement pour l'ajouter à MyStrow."
        )
        lbl_explain.setObjectName("sub")
        lbl_explain.setWordWrap(True)
        card_v.addWidget(lbl_explain)

        lbl_promise = QLabel("✉️  Un mail vous sera envoyé à notre équipe. Réponse rapide garantie.")
        lbl_promise.setStyleSheet("color: #00cc44; font-size: 9pt;")
        card_v.addWidget(lbl_promise)
        v.addWidget(card)

        v.addStretch()
        btn = QPushButton("Commencer le test  →")
        btn.setObjectName("primary")
        btn.setFixedHeight(48)
        btn.clicked.connect(self._welcome_next)
        v.addWidget(btn)
        return w

    def _build_name(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(14)

        lbl_title = QLabel("Nouveau contrôleur")
        lbl_title.setObjectName("title")
        v.addWidget(lbl_title)

        lbl_sub = QLabel("Donnez un nom à votre contrôleur et indiquez son port MIDI.")
        lbl_sub.setObjectName("sub")
        v.addWidget(lbl_sub)
        v.addSpacing(8)

        v.addWidget(QLabel("Nom du contrôleur :"))
        self._inp_name = QLineEdit()
        self._inp_name.setPlaceholderText("ex: Novation Launchpad X")
        v.addWidget(self._inp_name)

        v.addSpacing(4)
        v.addWidget(QLabel("Port MIDI détecté (sélectionnez le vôtre) :"))
        self._combo_ports = QComboBox()
        self._combo_ports.addItem("— Aucun port sélectionné —", None)
        for p in _get_midi_ports():
            self._combo_ports.addItem(p, p)
        self._combo_ports.currentIndexChanged.connect(self._port_selected)
        v.addWidget(self._combo_ports)

        v.addSpacing(4)
        v.addWidget(QLabel("Mot-clé de détection (extrait automatiquement, modifiable) :"))
        self._inp_keyword = QLineEdit()
        self._inp_keyword.setPlaceholderText("ex: LAUNCHPAD X")
        v.addWidget(self._inp_keyword)

        lbl_hint = QLabel("Ce mot-clé sera cherché dans le nom du port MIDI au démarrage.")
        lbl_hint.setObjectName("warn")
        v.addWidget(lbl_hint)

        v.addStretch()
        h = QHBoxLayout()
        btn_back = QPushButton("← Retour"); btn_back.setObjectName("skip")
        btn_back.clicked.connect(lambda: self._show_page(self.PAGE_WELCOME))
        h.addWidget(btn_back)
        h.addStretch()
        btn_next = QPushButton("Continuer  →"); btn_next.setObjectName("primary")
        btn_next.setFixedHeight(42)
        btn_next.clicked.connect(self._name_next)
        h.addWidget(btn_next)
        v.addLayout(h)
        return w

    def _build_dimensions(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 32, 40, 32)
        v.setSpacing(14)

        lbl_title = QLabel("Structure du contrôleur")
        lbl_title.setObjectName("title")
        v.addWidget(lbl_title)
        lbl_sub = QLabel("Indiquez combien de pads, faders et boutons possède votre contrôleur.\nMettez 0 s'il n'en a pas.")
        lbl_sub.setObjectName("sub"); lbl_sub.setWordWrap(True)
        v.addWidget(lbl_sub)
        v.addSpacing(8)

        grid = QGridLayout(); grid.setSpacing(10)

        def _spin(lo, hi, default):
            s = QSpinBox()
            s.setRange(lo, hi); s.setValue(default)
            s.setFixedWidth(90)
            return s

        grid.addWidget(QLabel("Lignes de pads (0 = pas de pads) :"), 0, 0)
        self._spin_rows = _spin(0, 16, 8)
        grid.addWidget(self._spin_rows, 0, 1)

        grid.addWidget(QLabel("Colonnes de pads :"), 1, 0)
        self._spin_cols = _spin(0, 16, 8)
        grid.addWidget(self._spin_cols, 1, 1)

        grid.addWidget(QLabel("Nombre de faders (0 = aucun) :"), 2, 0)
        self._spin_faders = _spin(0, 16, 8)
        grid.addWidget(self._spin_faders, 2, 1)

        grid.addWidget(QLabel("Boutons effet / colonne droite (0 = aucun) :"), 3, 0)
        self._spin_effects = _spin(0, 16, 8)
        grid.addWidget(self._spin_effects, 3, 1)

        v.addLayout(grid)
        v.addStretch()

        h = QHBoxLayout()
        btn_back = QPushButton("← Retour"); btn_back.setObjectName("skip")
        btn_back.clicked.connect(lambda: self._show_page(self.PAGE_NAME))
        h.addWidget(btn_back); h.addStretch()
        btn_next = QPushButton("Continuer  →"); btn_next.setObjectName("primary")
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
        lbl_title = QLabel("Mapping des pads"); lbl_title.setObjectName("title")
        right.addWidget(lbl_title)

        self._pad_instr = QLabel("Appuyez sur le pad indiqué\nsur votre contrôleur.")
        self._pad_instr.setWordWrap(True)
        self._pad_instr.setStyleSheet("font-size: 12pt; color: #ddd;")
        right.addWidget(self._pad_instr)

        self._listen_label = QLabel("● En écoute MIDI...")
        self._listen_label.setObjectName("listen")
        right.addWidget(self._listen_label)

        right.addSpacing(8)

        btn_skip_cell = QPushButton("Passer cette position")
        btn_skip_cell.setObjectName("skip")
        btn_skip_cell.clicked.connect(self._pad_skip_cell)
        right.addWidget(btn_skip_cell)

        btn_end_row = QPushButton("← Fin de cette ligne")
        btn_end_row.setObjectName("skip")
        btn_end_row.clicked.connect(self._pad_end_row)
        right.addWidget(btn_end_row)

        btn_done = QPushButton("✓  Terminer les pads")
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

        lbl_title = QLabel("Mapping des faders"); lbl_title.setObjectName("title")
        v.addWidget(lbl_title)
        lbl_sub = QLabel(
            "Bougez chaque fader de bas en haut. Passez par tous les faders\n"
            "avant d'accéder aux boutons effets."
        )
        lbl_sub.setObjectName("sub"); lbl_sub.setWordWrap(True)
        v.addWidget(lbl_sub)
        v.addSpacing(8)

        self._fader_instr = QLabel("Bougez le fader 1")
        self._fader_instr.setStyleSheet("font-size: 14pt; color: #ddd;")
        v.addWidget(self._fader_instr)

        self._fader_listen = QLabel("● En écoute MIDI...")
        self._fader_listen.setObjectName("listen")
        v.addWidget(self._fader_listen)

        self._fader_progress = QLabel("")
        self._fader_progress.setObjectName("sub")
        v.addWidget(self._fader_progress)

        v.addSpacing(8)

        btn_skip = QPushButton("Passer ce fader →")
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

        lbl_title = QLabel("Test des LEDs"); lbl_title.setObjectName("title")
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
            "Test 1 — Bougez le curseur et observez le pad en haut à gauche.\n"
            "Si la luminosité de la LED change, validez !"
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

        self._bright_vel_label = QLabel("Velocité : 64  /  127")
        self._bright_vel_label.setAlignment(Qt.AlignCenter)
        self._bright_vel_label.setStyleSheet("color: #00aaff; font-size: 11pt;")
        bright_v.addWidget(self._bright_vel_label)

        h_bright1 = QHBoxLayout(); h_bright1.setSpacing(10)
        btn_bright_ok1 = QPushButton("✓  La luminosité change — Valider")
        btn_bright_ok1.setFixedHeight(38)
        btn_bright_ok1.setStyleSheet(
            "background:#0a2a0a; border:1px solid #004400; color:#00cc44;"
            " border-radius:6px; font-weight:bold;"
        )
        btn_bright_ok1.clicked.connect(self._bright_confirm)
        h_bright1.addWidget(btn_bright_ok1)
        btn_next_test = QPushButton("Aucun changement — Essayer autre chose →")
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
            "Test 2 — Cliquez sur chaque bouton et observez le pad.\n"
            "Certains contrôleurs (ex. AKAI) n'ont pas de luminosité variable\n"
            "mais réagissent différemment selon la plage de velocité."
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
        self._bright_alt_channel_label = QLabel("Canal 1")
        self._bright_alt_channel_label.setStyleSheet("color: #555; font-size: 8pt;")
        btn_alt_ch = QPushButton("Canal alternatif (1→6)")
        btn_alt_ch.setObjectName("skip"); btn_alt_ch.setFixedHeight(28)
        btn_alt_ch.clicked.connect(self._bright_test_channel)
        h_alt.addWidget(btn_alt_ch)
        h_alt.addWidget(self._bright_alt_channel_label)
        btn_alt_off = QPushButton("Note Off + vel")
        btn_alt_off.setObjectName("skip"); btn_alt_off.setFixedHeight(28)
        btn_alt_off.clicked.connect(self._bright_test_noteoff)
        h_alt.addWidget(btn_alt_off)
        h_alt.addStretch()
        spec_v.addLayout(h_alt)

        h_bright2 = QHBoxLayout(); h_bright2.setSpacing(10)
        btn_bright_ok2 = QPushButton("✓  Quelque chose change — Valider")
        btn_bright_ok2.setFixedHeight(38)
        btn_bright_ok2.setStyleSheet(
            "background:#0a2a0a; border:1px solid #004400; color:#00cc44;"
            " border-radius:6px; font-weight:bold;"
        )
        btn_bright_ok2.clicked.connect(self._bright_confirm)
        h_bright2.addWidget(btn_bright_ok2)
        btn_skip_all = QPushButton("Rien ne change — Passer au test couleurs")
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
            "Nous envoyons différentes velocités au pad.\n"
            "Cliquez sur la couleur qui s'affiche sur votre contrôleur."
        )
        lbl_color_intro.setObjectName("sub"); lbl_color_intro.setWordWrap(True)
        color_v.addWidget(lbl_color_intro)

        self._led_vel_label = QLabel("Velocité testée : —")
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

        btn_skip_color = QPushButton("Passer le test de couleur")
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

        lbl_title = QLabel("✅  Test terminé — Envoyez-nous les résultats")
        lbl_title.setObjectName("title")
        v.addWidget(lbl_title)

        self._save_summary = QTextEdit()
        self._save_summary.setReadOnly(True)
        self._save_summary.setFixedHeight(130)
        v.addWidget(self._save_summary)

        v.addSpacing(6)

        # Bloc principal : envoyer à MyStrow
        frame_send = QFrame(); frame_send.setObjectName("card")
        fs = QVBoxLayout(frame_send); fs.setContentsMargins(16, 14, 16, 14); fs.setSpacing(10)

        lbl_send_title = QLabel("📩  Envoyez le test à l'équipe MyStrow")
        lbl_send_title.setStyleSheet("color: #00aaff; font-weight: bold; font-size: 11pt;")
        fs.addWidget(lbl_send_title)

        lbl_send_sub = QLabel(
            "Un clic suffit — votre client mail s'ouvre avec tout le contenu rempli.\n"
            "On revient vers vous rapidement pour ajouter votre contrôleur à MyStrow !"
        )
        lbl_send_sub.setObjectName("sub"); lbl_send_sub.setWordWrap(True)
        fs.addWidget(lbl_send_sub)

        btn_send = QPushButton("✉️  Envoyer à l'équipe MyStrow  →")
        btn_send.setObjectName("share"); btn_send.setFixedHeight(44)
        btn_send.setStyleSheet(
            "background:#0a2a0a; border:1px solid #005500; color:#00cc44;"
            " border-radius:6px; font-weight:bold; font-size:11pt;"
        )
        btn_send.clicked.connect(self._share_profile)
        fs.addWidget(btn_send)
        v.addWidget(frame_send)

        v.addStretch()

        h = QHBoxLayout(); h.setSpacing(10)
        btn_save = QPushButton("💾  Sauvegarder en local"); btn_save.setObjectName("skip")
        btn_save.setFixedHeight(36); btn_save.clicked.connect(self._do_save)
        h.addWidget(btn_save)
        h.addStretch()
        btn_close = QPushButton("Fermer"); btn_close.setObjectName("skip")
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

        instr = QLabel(f"Bouton 1")
        instr.setStyleSheet("font-size: 14pt; color: #ddd;")
        v.addWidget(instr)

        listen = QLabel("● En écoute MIDI...")
        listen.setObjectName("listen")
        v.addWidget(listen)

        progress = QLabel("")
        progress.setObjectName("sub")
        v.addWidget(progress)

        v.addSpacing(8)
        h_btns = QHBoxLayout(); h_btns.setSpacing(10)

        btn_skip = QPushButton("Passer"); btn_skip.setObjectName("skip")
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
        steps = ["Bienvenue", "Nom", "Dimensions", "Pads", "Mutes", "Faders", "Effets", "LEDs", "Sauvegarde"]
        self._step_label.setText(f"Étape {idx+1}/9  —  {steps[idx]}")

        if idx == self.PAGE_PADS:
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
            self._populate_save_page()

    def _next_after_pads(self):
        if self._fader_count > 0:
            self._show_page(self.PAGE_MUTES)
        elif self._effect_count > 0:
            self._show_page(self.PAGE_EFFECTS)
        elif self._pad_map:
            self._show_page(self.PAGE_LEDS)
        else:
            self._show_page(self.PAGE_SAVE)

    def _next_after_mutes(self):
        if self._fader_count > 0:
            self._show_page(self.PAGE_FADERS)
        elif self._effect_count > 0:
            self._show_page(self.PAGE_EFFECTS)
        elif self._pad_map:
            self._show_page(self.PAGE_LEDS)
        else:
            self._show_page(self.PAGE_SAVE)

    def _next_after_faders(self):
        if self._effect_count > 0:
            self._show_page(self.PAGE_EFFECTS)
        elif self._pad_map:
            self._show_page(self.PAGE_LEDS)
        else:
            self._show_page(self.PAGE_SAVE)

    def _next_after_effects(self):
        if self._pad_map:
            self._show_page(self.PAGE_LEDS)
        else:
            self._show_page(self.PAGE_SAVE)

    # ─── Logique page Welcome ─────────────────────────────────────────────────

    def _welcome_next(self):
        self._show_page(self.PAGE_NAME)

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
        port = self._combo_ports.currentData()
        if port:
            # Prendre les premiers mots du nom de port comme keyword
            parts = port.upper().split()
            kw = " ".join(parts[:3]) if len(parts) >= 3 else port.upper()
            self._inp_keyword.setText(kw)

    def _name_next(self):
        name = self._inp_name.text().strip()
        if not name:
            self._inp_name.setPlaceholderText("⚠️  Nom requis !")
            return
        self._profile_name = name
        kw = self._inp_keyword.text().strip().upper()
        self._keywords = [kw] if kw else []
        self._show_page(self.PAGE_DIMENSIONS)

    # ─── Logique page Dimensions ──────────────────────────────────────────────

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
            f"Appuyez sur le pad\nColonne {c+1}, Ligne {r+1}\nsur votre contrôleur"
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
                f"Appuyez sur le bouton de la tranche {cursor + 1}\n"
                f"(le bouton qui coupe le son / mute / solo)"
            )
        else:
            instr.setText(f"Appuyez sur le bouton effet {cursor + 1}\n(colonne de droite)")
        progress.setText(f"Tranche {cursor + 1} / {total}")

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
        self._fader_instr.setText(f"Bougez le fader {self._fader_cursor + 1} complètement")
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
        self._led_phase_label.setText("Étape 1 / 2  —  Test de luminosité")
        self._bright_alt_ch = 0
        self._bright_alt_channel_label.setText("Canal 1")
        self._bright_specific_vel = None

        self._bright_slider.setValue(64)
        self._send_to_pad(
            self._bright_ref_entry.get("channel", 0),
            self._bright_ref_entry["note"],
            64,
        )

    def _on_bright_slider(self, val):
        self._bright_vel_label.setText(f"Velocité : {val}  /  127")
        entry = self._bright_ref_entry
        if entry:
            self._send_to_pad(entry.get("channel", 0), entry["note"], val)

    def _bright_try_specific(self):
        """Phase 1 échoue → affiche la phase 2 (velocités précises)."""
        self._bright_section.setVisible(False)
        self._bright_specific_section.setVisible(True)
        self._led_phase_label.setText("Étape 1 / 2  —  Test de luminosité (essai 2)")
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
        self._bright_alt_channel_label.setText(f"Canal {self._bright_alt_ch + 1}")
        entry = self._bright_ref_entry
        if entry:
            val = self._bright_slider.value()
            if self.midi_handler and self.midi_handler.midi_out:
                try:
                    self.midi_handler.midi_out.send_message(
                        [0x90 | self._bright_alt_ch, entry["note"], val]
                    )
                except Exception:
                    pass

    def _bright_test_noteoff(self):
        """Envoie Note Off (0x80) avec la vélocité du slider — certains contrôleurs allument la LED en mode dim."""
        entry = self._bright_ref_entry
        if entry:
            val = self._bright_slider.value()
            if self.midi_handler and self.midi_handler.midi_out:
                try:
                    self.midi_handler.midi_out.send_message(
                        [0x80 | entry.get("channel", 0), entry["note"], val]
                    )
                except Exception:
                    pass

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
        entry = self._bright_ref_entry
        if entry and self.midi_handler and self.midi_handler.midi_out:
            self._send_to_pad(entry.get("channel", 0), entry["note"], 0)

    def _send_to_pad(self, channel, note, vel):
        if self.midi_handler and self.midi_handler.midi_out:
            try:
                self.midi_handler.midi_out.send_message([0x90 | channel, note, vel])
            except Exception:
                pass

    def _start_color_phase(self):
        self._led_vel_idx = 0
        self._bright_section.setVisible(False)
        self._color_section.setVisible(True)
        self._led_phase_label.setText("Étape 2 / 2  —  Test des couleurs")
        self._send_led_test()

    def _send_led_test(self):
        if self._led_vel_idx >= len(_LED_VELOCITIES):
            self._show_page(self.PAGE_SAVE)
            return
        vel, _label, _ = _LED_VELOCITIES[self._led_vel_idx]
        self._led_vel_label.setText(f"Velocité testée : {vel}   (envoyée au pad 1)")
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
        path = save_profile(data, self._edit_file)
        self._edit_file = path
        self.profile_saved.emit(path)
        # Feedback visuel
        self._save_summary.append(f"\n✅  Profil enregistré :\n{path}")

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
        if self.midi_handler:
            self.midi_handler.set_raw_capture(callback)

    def _stop_capture(self):
        if self.midi_handler:
            self.midi_handler.clear_raw_capture()

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
        # Éteindre le pad de test LED si actif
        if self._led_vel_idx > 0 and self._pad_map:
            for (r, c), entry in self._pad_map.items():
                if self.midi_handler and self.midi_handler.midi_out:
                    try:
                        ch = entry.get("channel", 0)
                        self.midi_handler.midi_out.send_message([0x90 | ch, entry["note"], 0])
                    except Exception:
                        pass
                break
        super().closeEvent(event)
