"""
Composants UI pour le controleur AKAI
DualColorButton, EffectButton, FaderButton, ApcFader
"""
import json
from pathlib import Path
from i18n import tr
from core import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from PySide6.QtWidgets import (
    QPushButton, QWidget, QMenu, QWidgetAction, QLabel, QHBoxLayout,
    QVBoxLayout, QDoubleSpinBox, QLineEdit, QSizePolicy, QSlider,
    QGraphicsDropShadowEffect,
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


def _effect_presets():
    return [
        (tr("uic_effect_none"),         None,           "#2a2a2a"),
        ("⚡ Strobe",                   "Strobe",        "#ffffff"),
        ("💥 Flash",                    "Flash",         "#ffff00"),
        ("💜 Pulse",                    "Pulse",         "#ff00ff"),
        (tr("uic_effect_wave"),         "Wave",          "#00ffff"),
        (tr("uic_effect_comet"),        "Comete",        "#ff8800"),
        ("🌈 Rainbow",                  "Rainbow",       "#00ff00"),
        (tr("uic_effect_shooting_star"),"Etoile Filante","#aaddff"),
        ("🔥 Feu",                      "Fire",          "#ff4400"),
        (tr("uic_effect_white_chase"),  "Chase",         "#e0e0e0"),
        (tr("uic_effect_bascule"),      "Bascule",       "#44ccff"),
    ]

EFFECT_PRESETS = _effect_presets()

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

    effect_config_selected  = Signal(int, dict)      # (btn_index, config_dict)
    trigger_mode_changed    = Signal(int, str, int)  # (btn_index, mode, duration_ms)
    layer_overrides_changed = Signal(int, list, int) # (btn_index, target_groups, speed)
    press_signal            = Signal(int)            # (btn_index)  — press physique
    released_signal         = Signal(int)            # (btn_index)  — release physique
    open_editor_requested   = Signal(int)            # (btn_index)  — ouvre l'éditeur d'effets

    def __init__(self, index):
        super().__init__()
        self.index = index
        self.setFixedSize(16, 16)
        self.active = False
        self.trigger_mode = "toggle"      # "toggle" | "flash" | "timer"
        self.trigger_duration = 2000      # ms, pour mode Timer
        self._target_groups = ["A", "B", "C", "D", "E", "F", "G", "H"]
        self._speed = 50
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
            return tr("uic_tooltip_no_effect")
        for label, name, _ in EFFECT_PRESETS:
            if name == self.current_effect:
                return label
        return self.current_effect

    def show_effects_menu(self, pos):
        """Affiche le menu des effets (chargés depuis l'éditeur d'effets)"""
        all_effects = []
        try:
            from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
            custom = _load_custom_effects()
            custom_names = {e.get("name", "") for e in custom}
            # Builtins (sauf ceux remplacés par un custom de même nom) + custom
            all_effects = [e for e in BUILTIN_EFFECTS if e.get("name", "") not in custom_names] + custom
        except Exception:
            pass

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                padding: 2px;
                font-size: 11px;
            }
            QMenu::item {
                padding: 4px 10px;
                border-radius: 3px;
                color: #e0e0e0;
            }
            QMenu::item:selected { background: #2a3a3a; color: #fff; }
            QMenu::item:disabled { color: #555; font-size: 9px; letter-spacing: 1px; }
            QMenu::separator { background: #333; height: 1px; margin: 2px 6px; }
        """)

        # ── Section 1 : GROUPES + VITESSE ────────────────────────────────────
        _mw = self.window()
        if _mw and hasattr(_mw, '_button_effect_configs'):
            _lyr0 = _mw._button_effect_configs.get(self.index, {}).get("layers", [])
            _init_groups = list(_lyr0[0].get("target_groups", ["A","B","C","D","E","F","G","H"])) if _lyr0 else list(self._target_groups)
            _init_speed  = int(_lyr0[0].get("speed", self._speed)) if _lyr0 else self._speed
        else:
            _init_groups = list(self._target_groups)
            _init_speed  = self._speed
        _sel_groups = list(_init_groups)

        _spd_slider = QSlider(Qt.Horizontal)
        _spd_slider.setRange(0, 100)
        _spd_slider.setValue(_init_speed)
        _spd_slider.setFixedWidth(100)
        _spd_slider.setStyleSheet(
            "QSlider::groove:horizontal{background:#333;height:4px;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#00aaff;width:12px;height:12px;margin:-4px 0;border-radius:6px;}"
        )

        _GRP_ON  = "QPushButton{background:#00aaff;color:#fff;border:1px solid #0088cc;border-radius:3px;font-size:10px;font-weight:bold;}"
        _GRP_OFF = "QPushButton{background:#2a2a2a;color:#777;border:1px solid #3a3a3a;border-radius:3px;font-size:10px;}"
        _grp_btn_map = {}

        def _toggle_grp(g_id):
            if g_id in _sel_groups:
                _sel_groups.remove(g_id)
            else:
                _sel_groups.append(g_id)
            _grp_btn_map[g_id].setStyleSheet(_GRP_ON if g_id in _sel_groups else _GRP_OFF)
            self.layer_overrides_changed.emit(self.index, list(_sel_groups), _spd_slider.value())

        grp_outer = QWidget(); grp_outer.setStyleSheet("background: transparent;")
        grp_vlay = QVBoxLayout(grp_outer)
        grp_vlay.setContentsMargins(10, 6, 10, 2); grp_vlay.setSpacing(4)

        grp_hdr = QLabel(tr("uic_groups")); grp_hdr.setStyleSheet("color:#555;font-size:9px;letter-spacing:1px;background:transparent;")
        grp_vlay.addWidget(grp_hdr)

        btns_h = QHBoxLayout(); btns_h.setSpacing(3); btns_h.setContentsMargins(0, 0, 0, 0)
        for _gid, _glbl in [("A","A"),("B","B"),("C","C"),("D","D"),("E","E"),("F","F"),("G","G"),("H","H")]:
            _gb = QPushButton(_glbl); _gb.setFixedSize(36, 22)
            _gb.setStyleSheet(_GRP_ON if _gid in _sel_groups else _GRP_OFF)
            _gb.clicked.connect(lambda _, g=_gid: _toggle_grp(g))
            _grp_btn_map[_gid] = _gb; btns_h.addWidget(_gb)
        grp_vlay.addLayout(btns_h)

        spd_row = QHBoxLayout(); spd_row.setSpacing(6); spd_row.setContentsMargins(0, 2, 0, 0)
        spd_lbl = QLabel(tr("uic_speed")); spd_lbl.setStyleSheet("color:#aaa;font-size:11px;background:transparent;")
        spd_val_lbl = QLabel(f"{_init_speed}"); spd_val_lbl.setFixedWidth(26)
        spd_val_lbl.setStyleSheet("color:#fff;font-size:11px;background:transparent;")
        _spd_slider.valueChanged.connect(lambda v: spd_val_lbl.setText(f"{v}"))
        _spd_slider.valueChanged.connect(lambda v: self.layer_overrides_changed.emit(self.index, list(_sel_groups), v))
        spd_row.addWidget(spd_lbl); spd_row.addWidget(_spd_slider); spd_row.addWidget(spd_val_lbl); spd_row.addStretch()
        grp_vlay.addLayout(spd_row)

        grp_wa = QWidgetAction(menu); grp_wa.setDefaultWidget(grp_outer); menu.addAction(grp_wa)
        menu.addSeparator()

        # ── Section 2 : MODE DE DÉCLENCHEMENT (inline) ───────────────────────
        trig_outer = QWidget(); trig_outer.setStyleSheet("background: transparent;")
        trig_vlay = QVBoxLayout(trig_outer)
        trig_vlay.setContentsMargins(10, 4, 10, 6); trig_vlay.setSpacing(4)

        trig_hdr = QLabel(tr("ui2_trigger")); trig_hdr.setStyleSheet("color:#555;font-size:9px;letter-spacing:1px;background:transparent;")
        trig_vlay.addWidget(trig_hdr)

        _TRIG_ON  = ("QPushButton{background:#00aaff;color:#fff;border:1px solid #0088cc;"
                     "border-radius:3px;font-size:10px;font-weight:bold;padding:2px 6px;}")
        _TRIG_OFF = ("QPushButton{background:#2a2a2a;color:#777;border:1px solid #3a3a3a;"
                     "border-radius:3px;font-size:10px;padding:2px 6px;}")

        trig_btns_row = QHBoxLayout(); trig_btns_row.setSpacing(4); trig_btns_row.setContentsMargins(0,0,0,0)
        _trig_btn_map = {}
        _mode_labels = [("toggle", "Toggle"), ("flash", "Flash"), ("timer", "Timer")]
        for _mode, _mlbl in _mode_labels:
            _tb = QPushButton(_mlbl)
            _tb.setStyleSheet(_TRIG_ON if self.trigger_mode == _mode else _TRIG_OFF)
            _trig_btn_map[_mode] = _tb
            trig_btns_row.addWidget(_tb)
        trig_btns_row.addStretch()
        trig_vlay.addLayout(trig_btns_row)

        # Ligne durée (toujours visible, active en mode timer)
        dur_row = QHBoxLayout(); dur_row.setSpacing(6); dur_row.setContentsMargins(0, 2, 0, 0)
        dur_lbl = QLabel(tr("uic_duration_label"))
        dur_lbl.setStyleSheet("color:#aaa;font-size:11px;background:transparent;")
        dur_spin = QDoubleSpinBox()
        dur_spin.setRange(0.1, 60.0)
        dur_spin.setSingleStep(0.5)
        dur_spin.setValue(self.trigger_duration / 1000.0)
        dur_spin.setSuffix(" s")
        dur_spin.setFixedWidth(80)
        dur_spin.setEnabled(self.trigger_mode == "timer")
        dur_spin.setStyleSheet(
            "QDoubleSpinBox { background: #222; color: #fff; border: 1px solid #444;"
            " border-radius: 3px; padding: 2px 4px; font-size: 11px; }"
            "QDoubleSpinBox:disabled { color: #555; border-color: #333; }"
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button"
            " { width: 16px; background: #333; border: none; }"
        )
        dur_spin.valueChanged.connect(lambda v: self._set_trigger_duration(int(v * 1000)))
        dur_row.addWidget(dur_lbl); dur_row.addWidget(dur_spin); dur_row.addStretch()
        trig_vlay.addLayout(dur_row)

        def _set_trig_mode(mode):
            self._set_trigger_mode(mode)
            for m, b in _trig_btn_map.items():
                b.setStyleSheet(_TRIG_ON if m == mode else _TRIG_OFF)
            dur_spin.setEnabled(mode == "timer")

        for _mode, _tb in _trig_btn_map.items():
            _tb.clicked.connect(lambda _, m=_mode: _set_trig_mode(m))

        trig_wa = QWidgetAction(menu); trig_wa.setDefaultWidget(trig_outer); menu.addAction(trig_wa)
        menu.addSeparator()

        # ── Section 3 : EFFETS ────────────────────────────────────────────────
        search_container = QWidget(); search_container.setStyleSheet("background: transparent;")
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(6, 4, 6, 4)
        search_input = QLineEdit()
        search_input.setPlaceholderText(tr("uic_search_effect_ph"))
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

        cur = self.current_effect
        name_is_full_match = cur and any(e.get("name") == cur for e in all_effects)

        def _is_checked(eff):
            name = eff.get("name", "")
            if name == cur:
                return True
            if not name_is_full_match and cur and eff.get("type") == cur:
                first_of_type = next((e for e in all_effects if e.get("type") == cur), None)
                return first_of_type is not None and first_of_type.get("name") == name
            return False

        # Style pour l'effet actuellement sélectionné
        _SEL_SS = (
            "QMenu::indicator { width: 0px; height: 0px; image: none; }"
            "QMenu::item:checked { background: #004400; color: #44ff44;"
            " font-weight: bold; border-left: 3px solid #44ff44; }"
            "QMenu::item:checked:selected { background: #005500; color: #55ff55; }"
        )

        act_none = menu.addAction(tr("uic_none"))
        act_none.setCheckable(True)
        act_none.setChecked(not cur)
        act_none.triggered.connect(lambda: self._select_editor_effect(None))
        sep_top = menu.addSeparator()

        _CAT_KEYS = [
            "Strobe / Flash", "Mouvement", "Ambiance", "Couleur",
            "Permut", "Lyre", "Spécial", "Personnalisés", "Mes Effets",
        ]
        _CAT_LABELS = {
            "Strobe / Flash": tr("uic_cat_strobe_flash"),
            "Mouvement":      tr("uic_cat_mouvement"),
            "Ambiance":       tr("uic_cat_ambiance"),
            "Couleur":        tr("uic_cat_couleur"),
            "Permut":         tr("uic_cat_permut"),
            "Lyre":           tr("uic_cat_lyre"),
            "Spécial":        tr("uic_cat_special"),
            "Personnalisés":  tr("uic_cat_perso"),
            "Mes Effets":     tr("uic_cat_mes_effets"),
        }
        cat_groups = []
        for cat in _CAT_KEYS:
            cat_effs = [e for e in all_effects if e.get("category") == cat]
            if not cat_effs:
                continue
            hdr = menu.addAction(f"  {_CAT_LABELS.get(cat, cat).upper()}")
            hdr.setEnabled(False)
            eff_actions = []
            for eff in cat_effs:
                name = eff.get("name", "")
                selected = _is_checked(eff)
                label = f"  {name}"
                act = menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(selected)
                if selected:
                    act.setProperty("class", "selected_effect")
                act.triggered.connect(lambda checked=False, e=dict(eff): self._select_editor_effect(e))
                eff_actions.append((act, name, selected))
            cat_groups.append((hdr, eff_actions))

        other = [e for e in all_effects if e.get("category", "") not in _CAT_KEYS]
        if other:
            sep_other = menu.addSeparator()
            other_actions = []
            for eff in other:
                name = eff.get("name", "")
                selected = _is_checked(eff)
                label = f"  {name}"
                act = menu.addAction(label)
                act.setCheckable(True)
                act.setChecked(selected)
                act.triggered.connect(lambda checked=False, e=dict(eff): self._select_editor_effect(e))
                other_actions.append((act, name, selected))
            cat_groups.append((sep_other, other_actions))

        # Patch le stylesheet du menu pour les items cochés
        menu.setStyleSheet(menu.styleSheet() + _SEL_SS)

        def _apply_filter(text):
            q = text.strip().lower()
            act_none.setVisible(not q)
            sep_top.setVisible(not q)
            for hdr_act, eff_acts in cat_groups:
                any_visible = False
                for act, name, *_ in eff_acts:
                    visible = not q or q in name.lower()
                    act.setVisible(visible)
                    if visible:
                        any_visible = True
                hdr_act.setVisible(any_visible)

        search_input.textChanged.connect(_apply_filter)
        QTimer.singleShot(0, search_input.setFocus)

        # « Éditeur d'effets » : un BOUTON pleine largeur en tête du menu, pas
        # une ligne de menu de plus. Remonté en première position ne suffisait
        # pas — au-dessus de 92 effets intégrés plus les effets perso, une
        # entrée de menu de plus se lit comme un effet parmi les autres.
        # Construit ici, après la liste, puis déplacé en tête : rien ne dépend
        # de sa place, l'action est branchée sur le clic du bouton.
        edit_outer = QWidget()
        edit_outer.setStyleSheet("background: transparent;")
        edit_lay = QVBoxLayout(edit_outer)
        edit_lay.setContentsMargins(6, 6, 6, 2)
        edit_lay.setSpacing(0)

        btn_editor = QPushButton(tr("uic_effect_editor_menu").strip() + "   ›")
        btn_editor.setCursor(Qt.PointingHandCursor)
        btn_editor.setFixedHeight(30)
        btn_editor.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #0d2b33, stop:1 #101820);color:#00d4ff;"
            "border:1px solid #00d4ff55;border-radius:4px;font-size:11px;"
            "font-weight:bold;letter-spacing:0.5px;padding:4px 10px;text-align:left;}"
            "QPushButton:hover{background:#0f3a45;border-color:#00d4ff;color:#7fe9ff;}"
            "QPushButton:pressed{background:#08222a;}"
        )

        def _open_editor():
            # Un QWidgetAction avale le clic : le menu ne se ferme pas tout
            # seul. Et on n'ouvre pas l'éditeur DEPUIS la boucle d'événements
            # du menu — d'où le report au tour suivant.
            menu.close()
            QTimer.singleShot(0, lambda: self.open_editor_requested.emit(self.index))

        btn_editor.clicked.connect(_open_editor)
        edit_lay.addWidget(btn_editor)

        act_editor = QWidgetAction(menu)
        act_editor.setDefaultWidget(edit_outer)
        menu.addAction(act_editor)
        _premier = next((a for a in menu.actions() if a is not act_editor), None)
        if _premier is not None:
            menu.removeAction(act_editor)
            menu.insertAction(_premier, act_editor)
            menu.insertSeparator(_premier)

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
        self.setToolTip(self.current_effect or tr("uic_tooltip_no_effect"))
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
                    background: #44ff44;
                    border: 2px solid #ffffff;
                    border-radius: 3px;
                }
            """)
            glow = QGraphicsDropShadowEffect(self)
            glow.setColor(QColor(0, 255, 80, 220))
            glow.setBlurRadius(14)
            glow.setOffset(0, 0)
            self.setGraphicsEffect(glow)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background: #0d2a0d;
                    border: 1px solid #1a3a1a;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background: #154015;
                    border-color: #226622;
                }
            """)
            self.setGraphicsEffect(None)


class PositionPadButton(QPushButton):
    """Pad de position lyre — bleu, grille 4×5 (20 pads)"""

    def __init__(self, pad_idx, parent=None):
        super().__init__(parent)
        self.pad_idx = pad_idx
        self.preset_name = None
        self.is_active = False
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.update_style()

    def update_style(self):
        n = self.pad_idx + 1
        if self.is_active:
            bg, border, color = "#2255ee", "#6699ff", "#ffffff"
        elif self.preset_name:
            bg, border, color = "#0d2a5c", "#1a4aa0", "#88aaff"
        else:
            bg, border, color = "#0a0f1e", "#1a2040", "#334466"
        label = (self.preset_name[:4] if self.preset_name else f"P{n}")
        self.setText(label)
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; border: 1px solid {border}; "
            f"border-radius: 3px; color: {color}; font-size: 7px; font-weight: bold; "
            f"padding: 0px; }}"
            f"QPushButton:pressed {{ background: #3377ff; border-color: #88bbff; }}"
        )
        tip = self.preset_name if self.preset_name else tr("pos_pad_empty_tip", n=n)
        self.setToolTip(tip)


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
        QColor("#00d4ff"),  # Cyan MyStrow
        QColor("#00d4ff"),
        QColor("#00d4ff"),
        QColor("#00d4ff"),
    ]

    # Listes prises dans core : elles avaient divergé, et une cartouche chargée
    # avec un .m4a ou un .aif tombait dans le « else » (icône fichier, type
    # inconnu) alors que le lecteur la joue sans broncher.
    VIDEO_EXTS = set(VIDEO_EXTENSIONS)
    AUDIO_EXTS = set(AUDIO_EXTENSIONS)

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
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Ne jamais forcer la colonne à s'élargir à cause d'un titre long :
        # largeur mini = 0, et le texte est élidé (…) pour tenir (voir _apply_text).
        self.setMinimumWidth(0)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self._update_style()

    def _update_style(self):
        r = self.base_color.red()
        g = self.base_color.green()
        b = self.base_color.blue()
        hex_col = self.base_color.name()

        self._apply_text()

        if self.state == self.PLAYING:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({r},{g},{b},18);
                    border-left: 3px solid rgba({r},{g},{b},255);
                    border-top: 1px solid rgba({r},{g},{b},60);
                    border-right: 1px solid rgba({r},{g},{b},20);
                    border-bottom: 1px solid rgba({r},{g},{b},40);
                    border-radius: 4px;
                    color: rgba({r},{g},{b},255);
                    font-weight: bold;
                    font-size: 11px;
                    padding: 4px 8px 4px 10px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: rgba({r},{g},{b},28);
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: #111111;
                    border-left: 3px solid rgba({r},{g},{b},120);
                    border-top: 1px solid #1e1e1e;
                    border-right: 1px solid #1a1a1a;
                    border-bottom: 1px solid #1e1e1e;
                    border-radius: 4px;
                    color: #888888;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 4px 8px 4px 10px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: #161616;
                    border-left: 3px solid rgba({r},{g},{b},200);
                    color: #bbbbbb;
                }}
            """)

    def _apply_text(self):
        """Texte du bouton, élidé (…) pour tenir dans la largeur courante.
        Un titre long ne doit jamais élargir la colonne des cartouches."""
        if self.media_title:
            label = f"{self.media_icon} {self.media_title}" if self.media_icon else self.media_title
        else:
            label = tr("uic_cartouche_label", n=self.index + 1)
        vol_str = f"   {self.volume}%" if self.volume < 100 else ""
        fm = self.fontMetrics()
        # Réserver la place du % + le padding gauche/droite (~26 px)
        avail = self.width() - 26 - fm.horizontalAdvance(vol_str)
        if avail < 24:
            avail = 24
        self.setText(fm.elidedText(label, Qt.ElideRight, avail) + vol_str)
        # Titre complet au survol (utile quand il est tronqué)
        self.setToolTip(self.media_title or "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_text()

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
