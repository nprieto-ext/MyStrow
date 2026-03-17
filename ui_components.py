"""
Composants UI pour le controleur AKAI
DualColorButton, EffectButton, FaderButton, ApcFader
"""
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QPushButton, QWidget, QMenu, QWidgetAction, QLabel, QHBoxLayout,
    QDoubleSpinBox, QLineEdit,
)
from PySide6.QtCore import Qt, QPoint, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygon


class DualColorButton(QPushButton):
    """Bouton avec deux couleurs en diagonale"""

    def __init__(self, color1, color2):
        super().__init__()
        self.color1 = color1
        self.color2 = color2
        self.setFixedSize(28, 28)
        self.active = False
        self.brightness = 0.3  # 30% par defaut

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Calculer les couleurs avec brightness
        c1 = QColor(
            int(self.color1.red() * self.brightness),
            int(self.color1.green() * self.brightness),
            int(self.color1.blue() * self.brightness)
        )
        c2 = QColor(
            int(self.color2.red() * self.brightness),
            int(self.color2.green() * self.brightness),
            int(self.color2.blue() * self.brightness)
        )

        # Diagonale couleur 1 (haut gauche)
        painter.setPen(Qt.NoPen)
        painter.setBrush(c1)
        points1 = [QPoint(0, 0), QPoint(28, 0), QPoint(0, 28)]
        painter.drawPolygon(QPolygon(points1))

        # Diagonale couleur 2 (bas droite)
        painter.setBrush(c2)
        points2 = [QPoint(28, 0), QPoint(28, 28), QPoint(0, 28)]
        painter.drawPolygon(QPolygon(points2))

        # Bordure
        if self.active:
            pen = QPen(QColor("#ffffff"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(1, 1, 26, 26, 4, 4)


EFFECT_PRESETS = [
    ("⭕ Aucun",           None,           "#2a2a2a"),
    ("⚡ Strobe",          "Strobe",        "#ffffff"),
    ("💥 Flash",           "Flash",         "#ffff00"),
    ("💜 Pulse",           "Pulse",         "#ff00ff"),
    ("🌊 Vague",           "Wave",          "#00ffff"),
    ("☄️ Comète",          "Comete",        "#ff8800"),
    ("🌈 Rainbow",         "Rainbow",       "#00ff00"),
    ("🌠 Etoile Filante",  "Etoile Filante","#aaddff"),
    ("🔥 Feu",             "Fire",          "#ff4400"),
    ("⬜ Passage Blanc",   "Chase",         "#e0e0e0"),
    ("↔️ Bascule",         "Bascule",       "#44ccff"),
]

# Effet par defaut pour chaque bouton (index 0-8)
DEFAULT_EFFECTS = [
    "Strobe", "Flash", "Pulse", "Wave",
    "Comete", "Rainbow", "Etoile Filante", "Chase", "Pulse"
]

def get_effect_emoji(effect_name):
    """Retourne l'emoji correspondant a un effet"""
    for label, name, _ in EFFECT_PRESETS:
        if name == effect_name:
            return label.split(" ")[0]
    return ""


class EffectButton(QPushButton):
    """Bouton d'effet carre rouge avec menu d'effets"""

    effect_config_selected = Signal(int, dict)   # (btn_index, config_dict)
    trigger_mode_changed   = Signal(int, str, int)  # (btn_index, mode, duration_ms)
    press_signal           = Signal(int)          # (btn_index)  — press physique
    released_signal        = Signal(int)          # (btn_index)  — release physique
    open_editor_requested  = Signal(int)          # (btn_index)  — ouvre l'éditeur d'effets

    def __init__(self, index):
        super().__init__()
        self.index = index
        self.setFixedSize(16, 16)
        self.active = False
        self.trigger_mode = "toggle"      # "toggle" | "flash" | "timer"
        self.trigger_duration = 2000      # ms, pour mode Timer
        # Effet par defaut selon la position
        if index < len(DEFAULT_EFFECTS):
            self.current_effect = DEFAULT_EFFECTS[index]
        else:
            self.current_effect = None
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_effects_menu)
        self.setToolTip(self._tooltip())
        self.update_style()

    def _tooltip(self):
        """Genere le tooltip avec emoji + nom de l'effet"""
        if not self.current_effect:
            return "Aucun effet"
        for label, name, _ in EFFECT_PRESETS:
            if name == self.current_effect:
                return label
        return self.current_effect

    def show_effects_menu(self, pos):
        """Affiche le menu des effets (chargés depuis l'éditeur d'effets)"""
        # Charger tous les effets : builtin + custom
        all_effects = []
        try:
            from effect_editor import BUILTIN_EFFECTS
            all_effects = list(BUILTIN_EFFECTS)
            effects_file = Path.home() / ".mystrow_effects.json"
            if effects_file.exists():
                custom = json.loads(effects_file.read_text(encoding="utf-8"))
                if isinstance(custom, list):
                    existing_names = {e["name"] for e in all_effects}
                    for e in custom:
                        if e.get("name") not in existing_names:
                            all_effects.append(e)
        except Exception:
            pass

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 16px;
                border-radius: 3px;
                color: #e0e0e0;
            }
            QMenu::item:selected { background: #2a3a3a; color: #fff; }
            QMenu::item:disabled { color: #555; font-size: 10px; letter-spacing: 1px; }
            QMenu::separator { background: #333; height: 1px; margin: 3px 8px; }
        """)

        # ── Barre de recherche ────────────────────────────────────────────────
        search_container = QWidget()
        search_container.setStyleSheet("background: transparent;")
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(6, 4, 6, 4)
        search_input = QLineEdit()
        search_input.setPlaceholderText("  Rechercher un effet…")
        search_input.setClearButtonEnabled(True)
        search_input.setStyleSheet("""
            QLineEdit {
                background: #111;
                color: #e0e0e0;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QLineEdit:focus { border-color: #00d4ff; }
        """)
        # Empêcher les touches directionnelles de fermer le menu
        def _search_key(event):
            if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter):
                event.accept()
                return
            QLineEdit.keyPressEvent(search_input, event)
        search_input.keyPressEvent = _search_key
        search_layout.addWidget(search_input)
        search_wa = QWidgetAction(menu)
        search_wa.setDefaultWidget(search_container)
        menu.addAction(search_wa)
        menu.addSeparator()

        # Si current_effect est un nom de type legacy ("Strobe", "Chase"...) sans match
        # exact dans la liste, on fait un fallback par type pour trouver le premier match
        cur = self.current_effect
        name_is_full_match = cur and any(e.get("name") == cur for e in all_effects)

        def _is_checked(eff):
            name = eff.get("name", "")
            if name == cur:
                return True
            # Fallback : current_effect est un type legacy ("Strobe", "Flash"...)
            if not name_is_full_match and cur and eff.get("type") == cur:
                first_of_type = next(
                    (e for e in all_effects if e.get("type") == cur), None
                )
                return first_of_type is not None and first_of_type.get("name") == name
            return False

        # Option "Aucun"
        act_none = menu.addAction("⭕  Aucun")
        act_none.setCheckable(True)
        act_none.setChecked(not cur)
        act_none.triggered.connect(lambda: self._select_editor_effect(None))
        sep_top = menu.addSeparator()

        # Grouper par catégorie et garder les références pour le filtrage
        CATS = ["Strobe / Flash", "Mouvement", "Ambiance", "Couleur", "Spécial", "Personnalisés", "Mes Effets"]
        # cat_groups : [(hdr_act, sep_act_before, [(eff_act, eff_name), ...])]
        cat_groups = []
        for cat in CATS:
            cat_effs = [e for e in all_effects if e.get("category") == cat]
            if not cat_effs:
                continue
            hdr = menu.addAction(f"  {cat.upper()}")
            hdr.setEnabled(False)
            eff_actions = []
            for eff in cat_effs:
                name = eff.get("name", "")
                act = menu.addAction(f"  {name}")
                act.setCheckable(True)
                act.setChecked(_is_checked(eff))
                act.triggered.connect(lambda checked=False, e=dict(eff): self._select_editor_effect(e))
                eff_actions.append((act, name))
            cat_groups.append((hdr, eff_actions))

        # Effets sans catégorie connue
        other = [e for e in all_effects if e.get("category", "") not in CATS]
        if other:
            sep_other = menu.addSeparator()
            other_actions = []
            for eff in other:
                name = eff.get("name", "")
                act = menu.addAction(f"  {name}")
                act.setCheckable(True)
                act.setChecked(_is_checked(eff))
                act.triggered.connect(lambda checked=False, e=dict(eff): self._select_editor_effect(e))
                other_actions.append((act, name))
            cat_groups.append((sep_other, other_actions))

        # ── Filtrage dynamique ────────────────────────────────────────────────
        def _apply_filter(text):
            q = text.strip().lower()
            # "Aucun" visible seulement sans filtre
            act_none.setVisible(not q)
            sep_top.setVisible(not q)
            for hdr_act, eff_acts in cat_groups:
                any_visible = False
                for act, name in eff_acts:
                    visible = not q or q in name.lower()
                    act.setVisible(visible)
                    if visible:
                        any_visible = True
                hdr_act.setVisible(any_visible)

        search_input.textChanged.connect(_apply_filter)
        # Focus automatique sur la barre de recherche à l'ouverture
        QTimer.singleShot(0, search_input.setFocus)

        # ── Sous-menu Mode de déclenchement ──────────────────────────────────
        menu.addSeparator()
        trig_menu = menu.addMenu("  ⏱  Mode de déclenchement")
        trig_menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item { padding: 6px 16px; border-radius: 3px; color: #e0e0e0; }
            QMenu::item:selected { background: #2a3a3a; color: #fff; }
            QMenu::item:checked { color: #00d4ff; }
        """)

        def _trig_checked(mode):
            return self.trigger_mode == mode

        act_tog = trig_menu.addAction("↕  Toggle (appui/relâche)")
        act_tog.setCheckable(True)
        act_tog.setChecked(_trig_checked("toggle"))
        act_tog.triggered.connect(lambda: self._set_trigger_mode("toggle"))

        act_fla = trig_menu.addAction("⚡  Flash (maintenir enfoncé)")
        act_fla.setCheckable(True)
        act_fla.setChecked(_trig_checked("flash"))
        act_fla.triggered.connect(lambda: self._set_trigger_mode("flash"))

        act_tim = trig_menu.addAction("⏳  Timer (durée automatique)")
        act_tim.setCheckable(True)
        act_tim.setChecked(_trig_checked("timer"))
        act_tim.triggered.connect(lambda: self._set_trigger_mode("timer"))

        # Durée du timer (QWidgetAction avec spinbox)
        trig_menu.addSeparator()
        dur_widget = QWidget()
        dur_layout = QHBoxLayout(dur_widget)
        dur_layout.setContentsMargins(16, 4, 16, 4)
        dur_layout.setSpacing(6)
        dur_lbl = QLabel("Durée :")
        dur_lbl.setStyleSheet("color: #aaa; font-size: 11px; background: transparent;")
        dur_spin = QDoubleSpinBox()
        dur_spin.setRange(0.1, 60.0)
        dur_spin.setSingleStep(0.5)
        dur_spin.setValue(self.trigger_duration / 1000.0)
        dur_spin.setSuffix(" s")
        dur_spin.setFixedWidth(80)
        dur_spin.setStyleSheet(
            "QDoubleSpinBox { background: #222; color: #fff; border: 1px solid #444;"
            " border-radius: 3px; padding: 2px 4px; font-size: 11px; }"
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button"
            " { width: 16px; background: #333; border: none; }"
        )
        dur_spin.valueChanged.connect(
            lambda v: self._set_trigger_duration(int(v * 1000))
        )
        dur_layout.addWidget(dur_lbl)
        dur_layout.addWidget(dur_spin)
        dur_layout.addStretch()
        dur_wa = QWidgetAction(trig_menu)
        dur_wa.setDefaultWidget(dur_widget)
        trig_menu.addAction(dur_wa)

        menu.addSeparator()
        act_editor = menu.addAction("🎨  Éditeur d'effets")
        act_editor.triggered.connect(lambda: self.open_editor_requested.emit(self.index))

        menu.exec(self.mapToGlobal(pos))

    def _set_trigger_mode(self, mode: str):
        self.trigger_mode = mode
        self.trigger_mode_changed.emit(self.index, mode, self.trigger_duration)

    def _set_trigger_duration(self, duration_ms: int):
        self.trigger_duration = duration_ms
        self.trigger_mode_changed.emit(self.index, self.trigger_mode, duration_ms)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.press_signal.emit(self.index)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.released_signal.emit(self.index)
        super().mouseReleaseEvent(e)

    def _select_editor_effect(self, cfg_or_none):
        """Applique un effet sélectionné dans le menu (avec ou sans config)."""
        if cfg_or_none is None:
            self.current_effect = None
            self.active = False
        else:
            self.current_effect = cfg_or_none.get("name", "")
            self.active = bool(self.current_effect)
        self.setToolTip(self.current_effect or "Aucun effet")
        self.update_style()
        cfg = dict(cfg_or_none) if cfg_or_none else {}
        self.effect_config_selected.emit(self.index, cfg)

    def set_effect(self, effect):
        """Definit l'effet actuel"""
        self.current_effect = effect
        if effect:
            self.active = True
        else:
            self.active = False
        self.setToolTip(self._tooltip())
        self.update_style()
        print(f"Effet {self.index}: {effect}")

    def update_style(self):
        if self.active:
            self.setStyleSheet("""
                QPushButton {
                    background: #33ff33;
                    border: 2px solid #ffffff;
                    border-radius: 3px;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background: #116611;
                    border: 1px solid #114411;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background: #118811;
                }
            """)


class FaderButton(QPushButton):
    """Bouton mute au-dessus du fader"""

    def __init__(self, index, callback):
        super().__init__()
        self.index = index
        self.callback = callback
        self.setFixedSize(16, 16)
        self.active = False
        self.update_style()

    def update_style(self):
        if self.active:
            self.setStyleSheet("""
                QPushButton {
                    background: #ff0000;
                    border: 2px solid #ff3333;
                    border-radius: 3px;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background: #440000;
                    border: 1px solid #660000;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background: #660000;
                }
            """)

    def mousePressEvent(self, e):
        self.active = not self.active
        self.update_style()
        self.callback(self.index, self.active)
        super().mousePressEvent(e)


class ApcFader(QWidget):
    """Fader style AKAI APC"""

    def __init__(self, index, callback, vertical=True, label=""):
        super().__init__()
        self.index = index
        self.callback = callback
        self.value = 0
        self.vertical = vertical
        self.label = label
        if vertical:
            self.setFixedWidth(50)
            self.setMinimumHeight(200)
        else:
            self.setFixedSize(26, 110)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setBrush(QColor("#333"))
        if not self.vertical:
            p.drawRoundedRect(w//2 - 2, 6, 4, h - 12, 2, 2)
            pos = h - 15 - int((self.value / 100) * (h - 25))
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(2, pos, 22, 10, 2, 2)
        else:
            p.drawRoundedRect(w//2 - 2, 15, 4, h - 30, 2, 2)
            pos = h - 30 - int((self.value / 100) * (h - 45))
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(w//2 - 15, pos + 10, 30, 12, 3, 3)

    def mousePressEvent(self, e):
        self.update_value(e.position())

    def mouseMoveEvent(self, e):
        self.update_value(e.position())

    def update_value(self, pos):
        limit = self.height() - (45 if self.vertical else 25)
        offset = 30 if self.vertical else 15
        y = max(10, min(self.height() - 10, int(pos.y())))
        self.value = int((self.height() - offset - y) / limit * 100)
        self.value = max(0, min(100, self.value))
        self.callback(self.index, self.value)
        self.update()

    def set_value(self, value):
        """Definit la valeur du fader (0-100)"""
        self.value = max(0, min(100, value))
        self.update()


class CartoucheButton(QPushButton):
    """Bouton cartouche audio/video avec 3 etats: IDLE, PLAYING, STOPPED"""

    IDLE = 0
    PLAYING = 1
    STOPPED = 2

    COLORS = [
        QColor("#ff8800"),  # Orange
        QColor("#ffdd00"),  # Jaune
        QColor("#00cc44"),  # Vert
        QColor("#0088ff"),  # Bleu
    ]

    VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'}
    AUDIO_EXTS = {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.wma'}

    def __init__(self, index, callback):
        super().__init__()
        self.index = index
        self.callback = callback
        self.state = self.IDLE
        self.base_color = self.COLORS[index % len(self.COLORS)]
        self.media_path = None
        self.media_title = None
        self.media_icon = ""
        self.volume = 100  # Volume 0-100, defaut 100%
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self._update_style()

    def _update_style(self):
        r = self.base_color.red()
        g = self.base_color.green()
        b = self.base_color.blue()
        hex_col = self.base_color.name()

        if self.media_title:
            label = f"{self.media_icon} {self.media_title}" if self.media_icon else self.media_title
        else:
            label = f"Cartouche {self.index + 1}"
        vol_str = f"   {self.volume}%" if self.volume < 100 else ""
        self.setText(label + vol_str)

        if self.state == self.PLAYING:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba({r},{g},{b},220),
                        stop:1 rgba({r//2},{g//2},{b//2},255));
                    border-left: 3px solid #ffffff;
                    border-top: 1px solid rgba({r},{g},{b},120);
                    border-right: 1px solid rgba({r//2},{g//2},{b//2},180);
                    border-bottom: 1px solid rgba({r},{g},{b},80);
                    border-radius: 4px;
                    color: white;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 4px 8px 4px 10px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    border-left: 3px solid white;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba({min(r+30,255)},{min(g+30,255)},{min(b+30,255)},230),
                        stop:1 rgba({r//2},{g//2},{b//2},255));
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba({r},{g},{b},70),
                        stop:0.45 rgba({r},{g},{b},25),
                        stop:1 rgba(20,20,20,255));
                    border-left: 3px solid {hex_col};
                    border-top: 1px solid rgba({r},{g},{b},55);
                    border-right: 1px solid #1e1e1e;
                    border-bottom: 1px solid rgba({r},{g},{b},40);
                    border-radius: 4px;
                    color: white;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 4px 8px 4px 10px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba({r},{g},{b},100),
                        stop:1 rgba(30,30,30,255));
                    border-left: 3px solid white;
                }}
            """)

    def set_idle(self):
        self.state = self.IDLE
        self._update_style()

    def set_playing(self):
        self.state = self.PLAYING
        self._update_style()

    def set_stopped(self):
        self.state = self.STOPPED
        self._update_style()

    def paintEvent(self, event):
        super().paintEvent(event)
        # Barre de volume en bas du bouton
        painter = QPainter(self)
        w = self.width()
        h = self.height()
        bar_h = 3
        bar_w = int((w - 4) * self.volume / 100)
        color = self.base_color if self.volume > 0 else QColor("#555")
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 160))
        painter.drawRoundedRect(2, h - bar_h - 1, bar_w, bar_h, 1, 1)
        painter.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.callback(self.index)
            e.accept()
            return
        super().mousePressEvent(e)
