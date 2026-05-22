"""
Éditeur de roue de couleur — MyStrow
Permet de définir les positions DMX exactes de chaque couleur
d'une roue de couleur fixture par fixture.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QLineEdit, QSpinBox, QFrame,
    QSizePolicy, QCheckBox, QApplication, QColorDialog, QSlider,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QCursor

# ── Profil générique de départ (si aucun profil OFL disponible) ───────────────
_GENERIC_SLOTS = [
    {"name": "Open",    "color": "#ffffff", "dmx": 0},
    {"name": "Rouge",   "color": "#ff2200", "dmx": 20},
    {"name": "Orange",  "color": "#ff8800", "dmx": 42},
    {"name": "Jaune",   "color": "#ffff00", "dmx": 64},
    {"name": "Vert",    "color": "#00cc44", "dmx": 85},
    {"name": "Cyan",    "color": "#00ccff", "dmx": 106},
    {"name": "Bleu",    "color": "#0044ff", "dmx": 128},
    {"name": "Magenta", "color": "#cc00ff", "dmx": 149},
    {"name": "Rose",    "color": "#ff88cc", "dmx": 170},
    {"name": "CTO",     "color": "#ffee88", "dmx": 192},
]

# ── Styles ────────────────────────────────────────────────────────────────────
_DLG_SS = """
QDialog        { background: #141414; color: #e0e0e0; }
QWidget        { background: #141414; color: #e0e0e0; }
QScrollArea    { background: #141414; border: none; }
QScrollArea > QWidget > QWidget { background: #141414; }
QLabel         { color: #ccc; font-size: 12px; background: transparent; }
QLineEdit      { background: #1e1e1e; color: #eee; border: 1px solid #333;
                 border-radius: 4px; padding: 3px 6px; font-size: 12px; }
QLineEdit:focus{ border-color: #00d4ff55; }
QSpinBox       { background: #1e1e1e; color: #eee; border: 1px solid #333;
                 border-radius: 4px; padding: 2px 4px; font-size: 12px;
                 min-width: 54px; }
QSpinBox:focus { border-color: #00d4ff55; }
QSpinBox::up-button   { width: 0; border: none; }
QSpinBox::down-button { width: 0; border: none; }
QCheckBox      { color: #bbb; font-size: 11px; spacing: 6px; background: transparent; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #555;
                        border-radius: 3px; background: #1e1e1e; }
QCheckBox::indicator:checked { background: #00d4ff; border-color: #00d4ff; }
QFrame         { background: #141414; }
"""

_ROW_SS        = "background: #1a1a1a; border-radius: 4px; border: 1px solid transparent;"
_ROW_SS_ACTIVE = "background: #1a2a1a; border-radius: 4px; border: 1px solid #00d4ff;"

_BTN_ADD = (
    "QPushButton { background: #1a2f1a; color: #44cc88; border: 1px solid #44cc8844; "
    "border-radius: 5px; font-size: 12px; padding: 4px 14px; } "
    "QPushButton:hover { border-color: #44cc88; color: #66ee99; background: #1e381e; }"
)
_BTN_SAVE = (
    "QPushButton { background: #00d4ff; color: #000; border: none; "
    "border-radius: 5px; font-size: 13px; font-weight: bold; padding: 6px 20px; } "
    "QPushButton:hover { background: #33e0ff; }"
)
_BTN_CANCEL = (
    "QPushButton { background: #2a2a2a; color: #aaa; border: 1px solid #3a3a3a; "
    "border-radius: 5px; font-size: 12px; padding: 6px 16px; } "
    "QPushButton:hover { background: #333; color: #eee; }"
)
_BTN_DEL = (
    "QPushButton { background: transparent; color: #555; border: none; "
    "font-size: 14px; padding: 0 4px; } "
    "QPushButton:hover { color: #cc3333; }"
)
_BTN_MOVE = (
    "QPushButton { background: transparent; color: #555; border: none; "
    "font-size: 11px; padding: 0 2px; } "
    "QPushButton:hover { color: #00d4ff; }"
)


def _luminance(hex_c: str) -> bool:
    """True si la couleur est claire (→ texte noir)."""
    c = hex_c.lstrip("#")
    if len(c) != 6:
        return True
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) > 128


class _SlotRow(QWidget):
    """Une ligne dans l'éditeur de roue : couleur + nom + DMX + move + delete."""

    def __init__(self, slot: dict, parent=None):
        super().__init__(parent)
        self._color = slot.get("color", "#ffffff")
        self._changed_cb = None  # appelé à chaque modif

        self.setFixedHeight(42)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_ROW_SS)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(6)

        # ── Bouton couleur ────────────────────────────────────────────────
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(30, 30)
        self._color_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._apply_color_style()
        self._color_btn.setToolTip("Cliquer pour changer la couleur")
        self._color_btn.clicked.connect(self._pick_color)
        row.addWidget(self._color_btn)

        # ── Nom ───────────────────────────────────────────────────────────
        self._name = QLineEdit(slot.get("name", ""))
        self._name.setPlaceholderText("Nom…")
        self._name.setFixedWidth(100)
        self._name.textChanged.connect(self._notify)
        row.addWidget(self._name)

        # ── DMX ───────────────────────────────────────────────────────────
        dmx_lbl = QLabel("DMX")
        dmx_lbl.setStyleSheet("color:#666;font-size:11px;")
        row.addWidget(dmx_lbl)

        self._dmx = QSpinBox()
        self._dmx.setRange(0, 255)
        self._dmx.setValue(slot.get("dmx", 0))
        self._dmx.setFixedWidth(58)
        self._dmx.valueChanged.connect(self._notify)
        row.addWidget(self._dmx)

        # ── Boutons +/− ───────────────────────────────────────────────────
        btn_minus = QPushButton("−")
        btn_plus  = QPushButton("+")
        for b in (btn_minus, btn_plus):
            b.setFixedSize(22, 22)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setStyleSheet(
                "QPushButton{background:#252525;color:#aaa;border:1px solid #3a3a3a;"
                "border-radius:4px;font-size:13px;font-weight:bold;}"
                "QPushButton:hover{background:#333;color:#fff;border-color:#00d4ff;}"
            )
        btn_minus.clicked.connect(lambda: self._dmx.setValue(self._dmx.value() - 1))
        btn_plus.clicked.connect(lambda:  self._dmx.setValue(self._dmx.value() + 1))
        row.addWidget(btn_minus)
        row.addWidget(btn_plus)

        row.addStretch()

        # ── Boutons déplacement ───────────────────────────────────────────
        self._btn_up   = QPushButton("▲")
        self._btn_down = QPushButton("▼")
        for b in (self._btn_up, self._btn_down):
            b.setFixedSize(18, 18)
            b.setStyleSheet(_BTN_MOVE)
            b.setCursor(QCursor(Qt.PointingHandCursor))
        row.addWidget(self._btn_up)
        row.addWidget(self._btn_down)

        # ── Supprimer ─────────────────────────────────────────────────────
        self._btn_del = QPushButton("✕")
        self._btn_del.setFixedSize(22, 22)
        self._btn_del.setStyleSheet(_BTN_DEL)
        self._btn_del.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_del.setToolTip("Supprimer ce slot")
        row.addWidget(self._btn_del)

    # ── Getters ──────────────────────────────────────────────────────────────

    def get_slot(self) -> dict:
        return {"name": self._name.text().strip(), "color": self._color,
                "dmx": self._dmx.value()}

    # ── Callbacks internes ────────────────────────────────────────────────────

    def _apply_color_style(self):
        tc = "#000" if _luminance(self._color) else "#fff"
        self._color_btn.setStyleSheet(
            f"QPushButton {{ background:{self._color}; border:2px solid #555; "
            f"border-radius:15px; color:{tc}; }} "
            f"QPushButton:hover {{ border-color:#00d4ff; }}"
        )

    def _pick_color(self):
        initial = QColor(self._color)
        c = QColorDialog.getColor(initial, self, "Choisir la couleur",
                                  QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self._color = c.name()
            self._apply_color_style()
            self._update_bar(self._dmx.value())
            self._notify()

    def set_active(self, active: bool):
        self.setStyleSheet(_ROW_SS_ACTIVE if active else _ROW_SS)

    def _notify(self, *_):
        if self._changed_cb:
            self._changed_cb()


class ColorWheelEditorDialog(QDialog):
    """
    Éditeur de profil roue de couleur.

    Args:
        proj:          Projecteur source (Moving Head)
        all_projectors: Tous les projecteurs (pour "appliquer à toutes les lyres")
        main_window:   Fenêtre principale (pour save_dmx_patch_config)
        parent:        Widget parent Qt
    """

    def __init__(self, proj, all_projectors: list, main_window=None, parent=None):
        super().__init__(parent)
        self._proj           = proj
        self._all_projectors = all_projectors
        self._main_window    = main_window
        self._rows: list[_SlotRow] = []

        self.setWindowTitle(f"Roue de couleur — {proj.name or proj.group}")
        self.setMinimumSize(520, 500)
        self.resize(540, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_DLG_SS)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── En-tête ───────────────────────────────────────────────────────
        title_lbl = QLabel(f"Roue de couleur")
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_lbl.setStyleSheet("color:#00d4ff;")
        root.addWidget(title_lbl)

        sub_lbl = QLabel(
            "Associez chaque couleur de la roue à sa valeur DMX exacte.\n"
            "Utilisez le sélecteur de couleur pour la teinte visuelle et ajustez le DMX."
        )
        sub_lbl.setStyleSheet("color:#666;font-size:11px;")
        sub_lbl.setWordWrap(True)
        root.addWidget(sub_lbl)

        # ── Source OFL ────────────────────────────────────────────────────
        existing = list(getattr(proj, 'color_wheel_slots', []))
        if not existing:
            existing = [dict(s) for s in _GENERIC_SLOTS]

        # ── Curseur test en direct ────────────────────────────────────────
        live_w = QWidget(); live_w.setAttribute(Qt.WA_StyledBackground, True)
        live_h = QHBoxLayout(live_w)
        live_h.setContentsMargins(0, 0, 0, 4); live_h.setSpacing(8)

        live_lbl = QLabel("Test direct")
        live_lbl.setStyleSheet("color:#666;font-size:11px;min-width:70px;")
        live_h.addWidget(live_lbl)

        live_sli = QSlider(Qt.Horizontal)
        live_sli.setRange(0, 255)
        live_sli.setValue(getattr(proj, 'color_wheel', 0))
        live_sli.setStyleSheet(
            "QSlider::groove:horizontal{background:#2a2a2a;height:6px;border-radius:3px;}"
            "QSlider::handle:horizontal{background:#00d4ff;width:14px;height:14px;"
            "border-radius:7px;margin:-4px 0;}"
            "QSlider::sub-page:horizontal{background:#00d4ff44;border-radius:3px;}"
        )
        live_h.addWidget(live_sli, 1)

        live_val = QLabel(str(getattr(proj, 'color_wheel', 0)))
        live_val.setStyleSheet("color:#00d4ff;font-size:11px;min-width:28px;")
        live_h.addWidget(live_val)

        def _on_live(v):
            live_val.setText(str(v))
            proj.color_wheel = v
            if main_window and hasattr(main_window, 'dmx') and main_window.dmx:
                import_projs = getattr(main_window, 'projectors', None) or all_projectors
                main_window.dmx.update_from_projectors(import_projs)
            if main_window and hasattr(main_window, 'plan_de_feu'):
                main_window.plan_de_feu.canvas.update()
            # Surligner le dernier slot dont la valeur DMX est <= v (slot "actif")
            if self._rows:
                passed = [r for r in self._rows if r._dmx.value() <= v]
                active = max(passed, key=lambda r: r._dmx.value()) if passed else self._rows[0]
                for r in self._rows:
                    r.set_active(r is active)

        live_sli.valueChanged.connect(_on_live)
        root.addWidget(live_w)

        # ── Colonne headers ───────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(6)
        for txt, w in [("Couleur", 30), ("Nom", 100), ("", 30), ("Valeur DMX (0-255)", 100)]:
            l = QLabel(txt)
            l.setStyleSheet("color:#555;font-size:10px;")
            if w:
                l.setFixedWidth(w)
            hdr.addWidget(l)
        hdr.addStretch()
        root.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(sep)

        # ── Zone scrollable des slots ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:#141414;}"
            "QScrollBar:vertical{background:#111;width:6px;border:none;}"
            "QScrollBar::handle:vertical{background:#2a2a2a;border-radius:3px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        self._slots_container = QWidget()
        self._slots_container.setAttribute(Qt.WA_StyledBackground, True)
        self._slots_container.setStyleSheet("background: #141414;")
        self._slots_layout = QVBoxLayout(self._slots_container)
        self._slots_layout.setContentsMargins(0, 4, 0, 4)
        self._slots_layout.setSpacing(3)
        self._slots_layout.addStretch()
        scroll.setWidget(self._slots_container)
        root.addWidget(scroll, 1)

        # Charger les slots existants
        for s in existing:
            self._add_slot(s)

        # ── Bouton ajouter ────────────────────────────────────────────────
        add_row = QHBoxLayout()
        btn_add = QPushButton("+ Ajouter une couleur")
        btn_add.setFixedHeight(30)
        btn_add.setStyleSheet(_BTN_ADD)
        btn_add.setCursor(QCursor(Qt.PointingHandCursor))
        btn_add.clicked.connect(lambda: self._add_slot(
            {"name": "", "color": "#ffffff", "dmx": 0}
        ))
        add_row.addWidget(btn_add)
        add_row.addStretch()
        root.addLayout(add_row)

        # ── Option d'application ──────────────────────────────────────────
        apply_sep = QFrame(); apply_sep.setFrameShape(QFrame.HLine)
        apply_sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(apply_sep)

        # Compter les autres Moving Head du même type
        _mh_others = [
            p for p in all_projectors
            if p is not proj and getattr(p, 'fixture_type', '') == "Moving Head"
        ]
        _same_name = [
            p for p in _mh_others
            if (p.name or "").rsplit(" ", 1)[0] == (proj.name or "").rsplit(" ", 1)[0]
        ]

        self._chk_all = QCheckBox(
            f"Appliquer à toutes les lyres ({len(_mh_others)} autres Moving Head)"
            if _mh_others else "Aucune autre lyre dans le show"
        )
        self._chk_all.setEnabled(bool(_mh_others))
        root.addWidget(self._chk_all)

        if _same_name:
            self._chk_same = QCheckBox(
                f"Uniquement les \"{(proj.name or proj.group).rsplit(' ', 1)[0]}\" "
                f"({len(_same_name) + 1} fixtures)"
            )
            self._chk_same.setChecked(True)
            root.addWidget(self._chk_same)
            # Les deux checkboxes sont mutuellement exclusifs
            self._chk_all.toggled.connect(
                lambda on: self._chk_same.setChecked(False) if on else None
            )
            self._chk_same.toggled.connect(
                lambda on: self._chk_all.setChecked(False) if on else None
            )
        else:
            self._chk_same = None

        # ── Boutons finaux ────────────────────────────────────────────────
        btn_sep = QFrame(); btn_sep.setFrameShape(QFrame.HLine)
        btn_sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(btn_sep)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("✓  Enregistrer")
        btn_save.setStyleSheet(_BTN_SAVE)
        btn_save.setCursor(QCursor(Qt.PointingHandCursor))
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    # ── Gestion des slots ─────────────────────────────────────────────────────

    def _add_slot(self, slot: dict):
        row_widget = _SlotRow(slot, self._slots_container)

        # Relier les boutons déplacement / suppression
        row_widget._btn_del.clicked.connect(lambda: self._remove_slot(row_widget))
        row_widget._btn_up.clicked.connect(lambda: self._move_slot(row_widget, -1))
        row_widget._btn_down.clicked.connect(lambda: self._move_slot(row_widget, +1))

        # Insérer avant le stretch (dernier item)
        insert_idx = self._slots_layout.count() - 1
        self._slots_layout.insertWidget(insert_idx, row_widget)
        self._rows.append(row_widget)
        self._update_move_buttons()

        # Scroll vers le bas si ajout manuel
        QApplication.processEvents()
        sa = self.findChild(QScrollArea)
        if sa:
            sa.verticalScrollBar().setValue(sa.verticalScrollBar().maximum())

    def _remove_slot(self, row_widget: _SlotRow):
        if row_widget in self._rows:
            self._rows.remove(row_widget)
        self._slots_layout.removeWidget(row_widget)
        row_widget.deleteLater()
        self._update_move_buttons()

    def _move_slot(self, row_widget: _SlotRow, direction: int):
        idx = self._rows.index(row_widget)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._rows):
            return
        # Échanger dans la liste
        self._rows[idx], self._rows[new_idx] = self._rows[new_idx], self._rows[idx]
        # Reconstruire l'ordre dans le layout
        for r in self._rows:
            self._slots_layout.removeWidget(r)
        stretch = self._slots_layout.takeAt(0)
        for r in self._rows:
            self._slots_layout.addWidget(r)
        self._slots_layout.addStretch()
        self._update_move_buttons()

    def _update_move_buttons(self):
        for i, r in enumerate(self._rows):
            r._btn_up.setEnabled(i > 0)
            r._btn_down.setEnabled(i < len(self._rows) - 1)

    # ── Sauvegarde ───────────────────────────────────────────────────────────

    def _collect_slots(self) -> list:
        return [r.get_slot() for r in self._rows if r.get_slot()["name"] or r.get_slot()["dmx"] > 0]

    def _save(self):
        slots = self._collect_slots()
        if not slots:
            return

        # Fixtures cibles
        targets = [self._proj]
        if self._chk_all.isChecked():
            targets += [
                p for p in self._all_projectors
                if p is not self._proj and getattr(p, 'fixture_type', '') == "Moving Head"
            ]
        elif self._chk_same and self._chk_same.isChecked():
            base = (self._proj.name or self._proj.group).rsplit(" ", 1)[0]
            targets += [
                p for p in self._all_projectors
                if p is not self._proj
                and (p.name or "").rsplit(" ", 1)[0] == base
                and getattr(p, 'fixture_type', '') == "Moving Head"
            ]

        for p in targets:
            p.color_wheel_slots = [dict(s) for s in slots]

        # Persister dans le patch
        if self._main_window and hasattr(self._main_window, 'save_dmx_patch_config'):
            self._main_window.save_dmx_patch_config()

        self.accept()

    def get_slots(self) -> list:
        """Retourne les slots après fermeture par accept()."""
        return self._collect_slots()


# ── Slots génériques gobo ─────────────────────────────────────────────────────
_GENERIC_GOBO_SLOTS = [
    {"name": "Open",   "color": "#ffffff", "dmx": 0},
    {"name": "Gobo 1", "color": "#aaaaaa", "dmx": 32},
    {"name": "Gobo 2", "color": "#aaaaaa", "dmx": 64},
    {"name": "Gobo 3", "color": "#aaaaaa", "dmx": 96},
    {"name": "Gobo 4", "color": "#aaaaaa", "dmx": 128},
    {"name": "Gobo 5", "color": "#aaaaaa", "dmx": 160},
    {"name": "Gobo 6", "color": "#aaaaaa", "dmx": 192},
    {"name": "Gobo 7", "color": "#aaaaaa", "dmx": 224},
]


class GoboWheelEditorDialog(QDialog):
    """
    Éditeur de roue de gobos.

    Args:
        proj:          Projecteur source (Moving Head)
        all_projectors: Tous les projecteurs
        main_window:   Fenêtre principale
        parent:        Widget parent Qt
    """

    def __init__(self, proj, all_projectors: list, main_window=None, parent=None):
        super().__init__(parent)
        self._proj           = proj
        self._all_projectors = all_projectors
        self._main_window    = main_window
        self._rows: list[_SlotRow] = []

        self.setWindowTitle(f"Roue de gobos — {proj.name or proj.group}")
        self.setMinimumSize(520, 500)
        self.resize(540, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_DLG_SS)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── En-tête ───────────────────────────────────────────────────────
        title_lbl = QLabel("Roue de gobos")
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_lbl.setStyleSheet("color:#ff9900;")
        root.addWidget(title_lbl)

        sub_lbl = QLabel(
            "Associez chaque gobo à sa valeur DMX exacte.\n"
            "La couleur sert d'indicateur visuel (teinture du gobo)."
        )
        sub_lbl.setStyleSheet("color:#666;font-size:11px;")
        sub_lbl.setWordWrap(True)
        root.addWidget(sub_lbl)

        # ── Slots existants ou génériques ─────────────────────────────────
        existing = list(getattr(proj, 'gobo_wheel_slots', []))
        if not existing:
            existing = [dict(s) for s in _GENERIC_GOBO_SLOTS]

        # ── Curseur test en direct ────────────────────────────────────────
        live_w = QWidget(); live_w.setAttribute(Qt.WA_StyledBackground, True)
        live_h = QHBoxLayout(live_w)
        live_h.setContentsMargins(0, 0, 0, 4); live_h.setSpacing(8)

        live_lbl = QLabel("Test direct")
        live_lbl.setStyleSheet("color:#666;font-size:11px;min-width:70px;")
        live_h.addWidget(live_lbl)

        live_sli = QSlider(Qt.Horizontal)
        live_sli.setRange(0, 255)
        live_sli.setValue(getattr(proj, 'gobo', 0))
        live_sli.setStyleSheet(
            "QSlider::groove:horizontal{background:#2a2a2a;height:6px;border-radius:3px;}"
            "QSlider::handle:horizontal{background:#ff9900;width:14px;height:14px;"
            "border-radius:7px;margin:-4px 0;}"
            "QSlider::sub-page:horizontal{background:#ff990044;border-radius:3px;}"
        )
        live_h.addWidget(live_sli, 1)

        live_val = QLabel(str(getattr(proj, 'gobo', 0)))
        live_val.setStyleSheet("color:#ff9900;font-size:11px;min-width:28px;")
        live_h.addWidget(live_val)

        def _on_live(v):
            live_val.setText(str(v))
            proj.gobo = v
            if main_window and hasattr(main_window, 'dmx') and main_window.dmx:
                import_projs = getattr(main_window, 'projectors', None) or all_projectors
                main_window.dmx.update_from_projectors(import_projs)
            if main_window and hasattr(main_window, 'plan_de_feu'):
                main_window.plan_de_feu.canvas.update()
            # Surligner le dernier slot dont le DMX est <= v
            if self._rows:
                passed = [r for r in self._rows if r._dmx.value() <= v]
                active = max(passed, key=lambda r: r._dmx.value()) if passed else self._rows[0]
                for r in self._rows:
                    r.set_active(r is active)

        live_sli.valueChanged.connect(_on_live)
        root.addWidget(live_w)

        # ── Colonne headers ───────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0); hdr.setSpacing(6)
        for txt, w in [("Couleur", 30), ("Nom", 100), ("", 30), ("Valeur DMX (0-255)", 100)]:
            l = QLabel(txt)
            l.setStyleSheet("color:#555;font-size:10px;")
            if w:
                l.setFixedWidth(w)
            hdr.addWidget(l)
        hdr.addStretch()
        root.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(sep)

        # ── Zone scrollable des slots ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:#141414;}"
            "QScrollBar:vertical{background:#111;width:6px;border:none;}"
            "QScrollBar::handle:vertical{background:#2a2a2a;border-radius:3px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        self._slots_container = QWidget()
        self._slots_container.setAttribute(Qt.WA_StyledBackground, True)
        self._slots_container.setStyleSheet("background: #141414;")
        self._slots_layout = QVBoxLayout(self._slots_container)
        self._slots_layout.setContentsMargins(0, 4, 0, 4)
        self._slots_layout.setSpacing(3)
        self._slots_layout.addStretch()
        scroll.setWidget(self._slots_container)
        root.addWidget(scroll, 1)

        for s in existing:
            self._add_slot(s)

        # ── Bouton ajouter ────────────────────────────────────────────────
        add_row = QHBoxLayout()
        btn_add = QPushButton("+ Ajouter un gobo")
        btn_add.setFixedHeight(30)
        btn_add.setStyleSheet(_BTN_ADD)
        btn_add.setCursor(QCursor(Qt.PointingHandCursor))
        btn_add.clicked.connect(lambda: self._add_slot(
            {"name": "", "color": "#aaaaaa", "dmx": 0}
        ))
        add_row.addWidget(btn_add)
        add_row.addStretch()
        root.addLayout(add_row)

        # ── Option d'application ──────────────────────────────────────────
        apply_sep = QFrame(); apply_sep.setFrameShape(QFrame.HLine)
        apply_sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(apply_sep)

        _mh_others = [
            p for p in all_projectors
            if p is not proj and getattr(p, 'fixture_type', '') == "Moving Head"
        ]
        _same_name = [
            p for p in _mh_others
            if (p.name or "").rsplit(" ", 1)[0] == (proj.name or "").rsplit(" ", 1)[0]
        ]

        self._chk_all = QCheckBox(
            f"Appliquer à toutes les lyres ({len(_mh_others)} autres Moving Head)"
            if _mh_others else "Aucune autre lyre dans le show"
        )
        self._chk_all.setEnabled(bool(_mh_others))
        root.addWidget(self._chk_all)

        if _same_name:
            self._chk_same = QCheckBox(
                f"Uniquement les \"{(proj.name or proj.group).rsplit(' ', 1)[0]}\" "
                f"({len(_same_name) + 1} fixtures)"
            )
            self._chk_same.setChecked(True)
            root.addWidget(self._chk_same)
            self._chk_all.toggled.connect(
                lambda on: self._chk_same.setChecked(False) if on else None
            )
            self._chk_same.toggled.connect(
                lambda on: self._chk_all.setChecked(False) if on else None
            )
        else:
            self._chk_same = None

        # ── Boutons finaux ────────────────────────────────────────────────
        btn_sep = QFrame(); btn_sep.setFrameShape(QFrame.HLine)
        btn_sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(btn_sep)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("✓  Enregistrer")
        btn_save.setStyleSheet(_BTN_SAVE)
        btn_save.setCursor(QCursor(Qt.PointingHandCursor))
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    def _add_slot(self, slot: dict):
        row_widget = _SlotRow(slot, self._slots_container)
        row_widget._btn_del.clicked.connect(lambda: self._remove_slot(row_widget))
        row_widget._btn_up.clicked.connect(lambda: self._move_slot(row_widget, -1))
        row_widget._btn_down.clicked.connect(lambda: self._move_slot(row_widget, +1))
        insert_idx = self._slots_layout.count() - 1
        self._slots_layout.insertWidget(insert_idx, row_widget)
        self._rows.append(row_widget)
        self._update_move_buttons()
        QApplication.processEvents()
        sa = self.findChild(QScrollArea)
        if sa:
            sa.verticalScrollBar().setValue(sa.verticalScrollBar().maximum())

    def _remove_slot(self, row_widget: _SlotRow):
        if row_widget in self._rows:
            self._rows.remove(row_widget)
        self._slots_layout.removeWidget(row_widget)
        row_widget.deleteLater()
        self._update_move_buttons()

    def _move_slot(self, row_widget: _SlotRow, direction: int):
        idx = self._rows.index(row_widget)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._rows):
            return
        self._rows[idx], self._rows[new_idx] = self._rows[new_idx], self._rows[idx]
        for r in self._rows:
            self._slots_layout.removeWidget(r)
        self._slots_layout.takeAt(0)
        for r in self._rows:
            self._slots_layout.addWidget(r)
        self._slots_layout.addStretch()
        self._update_move_buttons()

    def _update_move_buttons(self):
        for i, r in enumerate(self._rows):
            r._btn_up.setEnabled(i > 0)
            r._btn_down.setEnabled(i < len(self._rows) - 1)

    def _collect_slots(self) -> list:
        return [r.get_slot() for r in self._rows if r.get_slot()["name"] or r.get_slot()["dmx"] > 0]

    def _save(self):
        slots = self._collect_slots()
        if not slots:
            return

        targets = [self._proj]
        if self._chk_all.isChecked():
            targets += [
                p for p in self._all_projectors
                if p is not self._proj and getattr(p, 'fixture_type', '') == "Moving Head"
            ]
        elif self._chk_same and self._chk_same.isChecked():
            base = (self._proj.name or self._proj.group).rsplit(" ", 1)[0]
            targets += [
                p for p in self._all_projectors
                if p is not self._proj
                and (p.name or "").rsplit(" ", 1)[0] == base
                and getattr(p, 'fixture_type', '') == "Moving Head"
            ]

        for p in targets:
            p.gobo_wheel_slots = [dict(s) for s in slots]

        if self._main_window and hasattr(self._main_window, 'save_dmx_patch_config'):
            self._main_window.save_dmx_patch_config()

        self.accept()

    def get_slots(self) -> list:
        return self._collect_slots()


# ── Wizard de calibration pas-à-pas ──────────────────────────────────────────

_CALIB_STEPS = [
    ("Open",    "#ffffff", "Blanc / Open"),
    ("Rouge",   "#ff2200", "Rouge"),
    ("Orange",  "#ff8800", "Orange"),
    ("Jaune",   "#ffff00", "Jaune"),
    ("Vert",    "#00cc44", "Vert"),
    ("Cyan",    "#00ccff", "Cyan"),
    ("Bleu",    "#0044ff", "Bleu"),
    ("Magenta", "#cc00ff", "Magenta"),
]

_DEFAULT_CALIB_DMX = [0, 20, 42, 64, 85, 106, 128, 149]

_BTN_NEXT = (
    "QPushButton { background: #00d4ff; color: #000; border: none; "
    "border-radius: 5px; font-size: 13px; font-weight: bold; padding: 6px 18px; } "
    "QPushButton:hover { background: #33e0ff; }"
)
_BTN_PREV = (
    "QPushButton { background: #1e1e1e; color: #888; border: 1px solid #333; "
    "border-radius: 5px; font-size: 12px; padding: 6px 14px; } "
    "QPushButton:hover { background: #2a2a2a; color: #bbb; } "
    "QPushButton:disabled { color: #333; border-color: #222; }"
)
_BTN_INCR = (
    "QPushButton { background: #252525; color: #bbb; border: 1px solid #333; "
    "border-radius: 4px; font-size: 11px; font-weight: bold; } "
    "QPushButton:hover { background: #333; color: #fff; border-color: #00d4ff; }"
)


class ColorWheelCalibWizard(QDialog):
    """
    Wizard pas-à-pas pour calibrer les positions DMX d'une roue de couleur.

    Étape -1 : intro — met Shutter+Dim à fond, roue à 0.
    Étapes 0-7 : pour chaque couleur, l'utilisateur règle le curseur jusqu'à
                 voir la bonne couleur sur la lyre, puis clique Suivant.
    À la fin, les slots sont sauvegardés et appliqués aux fixtures similaires.
    """

    def __init__(self, proj, all_projectors: list, main_window=None, parent=None):
        super().__init__(parent)
        self._proj           = proj
        self._all_projectors = all_projectors
        self._mw             = main_window
        self._step           = -1

        # Sauvegarder l'état original pour restauration si annulation
        self._orig_shutter     = getattr(proj, 'shutter', 255)
        self._orig_shutter_inv = getattr(proj, 'shutter_inverted', False)
        self._orig_level       = getattr(proj, 'level', 100)
        self._orig_cw          = getattr(proj, 'color_wheel', 0)

        # Initialiser les valeurs depuis les slots existants ou les défauts
        existing = getattr(proj, 'color_wheel_slots', [])
        self._values: list[int] = []
        for i, (name, color, label) in enumerate(_CALIB_STEPS):
            match = next(
                (s for s in existing if s.get('name', '').lower() == name.lower()), None
            )
            self._values.append(match['dmx'] if match else _DEFAULT_CALIB_DMX[i])

        self.setWindowTitle("Calibration — Roue de couleur")
        self.setFixedSize(460, 380)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_DLG_SS)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(14)

        # ── Titre ────────────────────────────────────────────────────────────
        self._title_lbl = QLabel("Calibration — Roue de couleur")
        self._title_lbl.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self._title_lbl.setStyleSheet("color:#00d4ff;")
        self._title_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self._title_lbl)

        # ── Indicateur de progression ─────────────────────────────────────────
        self._progress_lbl = QLabel("")
        self._progress_lbl.setStyleSheet("color:#555;font-size:11px;")
        self._progress_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self._progress_lbl)

        # ── Cercle couleur ────────────────────────────────────────────────────
        self._circle = QFrame()
        self._circle.setFixedSize(76, 76)
        self._circle.setAttribute(Qt.WA_StyledBackground, True)
        _circ_wrap = QWidget()
        _circ_wrap.setAttribute(Qt.WA_StyledBackground, True)
        _cw_lay = QHBoxLayout(_circ_wrap)
        _cw_lay.setContentsMargins(0, 0, 0, 0)
        _cw_lay.addStretch()
        _cw_lay.addWidget(self._circle)
        _cw_lay.addStretch()
        self._circle_wrap = _circ_wrap
        root.addWidget(_circ_wrap)

        # ── Instructions ──────────────────────────────────────────────────────
        self._instr_lbl = QLabel("")
        self._instr_lbl.setStyleSheet("color:#bbb;font-size:12px;")
        self._instr_lbl.setAlignment(Qt.AlignCenter)
        self._instr_lbl.setWordWrap(True)
        root.addWidget(self._instr_lbl)

        # ── Zone curseur ──────────────────────────────────────────────────────
        self._slider_w = QWidget()
        self._slider_w.setAttribute(Qt.WA_StyledBackground, True)
        sli_lay = QHBoxLayout(self._slider_w)
        sli_lay.setContentsMargins(0, 0, 0, 0)
        sli_lay.setSpacing(6)

        self._sli = QSlider(Qt.Horizontal)
        self._sli.setRange(0, 255)
        self._sli.setStyleSheet(
            "QSlider::groove:horizontal{background:#2a2a2a;height:6px;border-radius:3px;}"
            "QSlider::handle:horizontal{background:#00d4ff;width:16px;height:16px;"
            "border-radius:8px;margin:-5px 0;}"
            "QSlider::sub-page:horizontal{background:#00d4ff55;border-radius:3px;}"
        )
        self._val_lbl = QLabel("0")
        self._val_lbl.setStyleSheet(
            "color:#00d4ff;font-size:14px;font-weight:bold;min-width:36px;"
        )
        self._val_lbl.setAlignment(Qt.AlignCenter)

        for lbl, delta in [("−5", -5), ("−", -1), ("+", 1), ("+5", 5)]:
            _b = QPushButton(lbl)
            _b.setFixedSize(34, 28)
            _b.setStyleSheet(_BTN_INCR)
            _d = delta
            _b.clicked.connect(lambda _chk=False, d=_d: self._sli.setValue(
                max(0, min(255, self._sli.value() + d))
            ))
            if delta < 0:
                sli_lay.addWidget(_b)
            else:
                if delta == 1:
                    sli_lay.addWidget(self._sli, 1)
                sli_lay.addWidget(_b)

        sli_lay.addWidget(self._val_lbl)

        self._sli.valueChanged.connect(self._on_slider)
        root.addWidget(self._slider_w)

        # ── Séparateur ────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(sep)

        # ── Bouton shutter inversé ────────────────────────────────────────────
        self._btn_shutter_inv = QPushButton("💡  Ma lyre ne s'allume pas")
        self._btn_shutter_inv.setStyleSheet(
            "QPushButton { background: transparent; color: #888; border: none;"
            " font-size: 11px; text-decoration: underline; padding: 2px 0; }"
            "QPushButton:hover { color: #ffaa00; }"
        )
        self._btn_shutter_inv.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_shutter_inv.clicked.connect(self._toggle_shutter_inverted)
        self._btn_shutter_inv.setVisible(False)
        root.addWidget(self._btn_shutter_inv, alignment=Qt.AlignCenter)

        # ── Navigation ────────────────────────────────────────────────────────
        nav = QHBoxLayout()
        nav.setSpacing(8)

        btn_cancel = QPushButton("Annuler")
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.clicked.connect(self._on_cancel)

        self._btn_prev = QPushButton("◀  Précédent")
        self._btn_prev.setStyleSheet(_BTN_PREV)
        self._btn_prev.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_prev.clicked.connect(self._go_prev)

        self._btn_next = QPushButton("Démarrer  ▶")
        self._btn_next.setStyleSheet(_BTN_NEXT)
        self._btn_next.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_next.clicked.connect(self._go_next)

        nav.addWidget(btn_cancel)
        nav.addStretch()
        nav.addWidget(self._btn_prev)
        nav.addWidget(self._btn_next)
        root.addLayout(nav)

        self._show_step(-1)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _send_dmx(self):
        if self._mw and hasattr(self._mw, 'dmx') and self._mw.dmx:
            projs = getattr(self._mw, 'projectors', None) or self._all_projectors
            self._mw.dmx.update_from_projectors(projs)

    def _on_slider(self, v: int):
        self._val_lbl.setText(str(v))
        if self._step >= 0:
            self._values[self._step] = v
            self._proj.color_wheel = v
            self._send_dmx()

    # ── Affichage par étape ───────────────────────────────────────────────────

    def _show_step(self, step: int):
        self._step = step

        if step == -1:
            self._title_lbl.setText("Calibration — Roue de couleur")
            self._title_lbl.setStyleSheet("color:#00d4ff;")
            self._progress_lbl.setText(
                f"{len(_CALIB_STEPS)} couleurs à configurer"
            )
            self._circle_wrap.setVisible(False)
            self._instr_lbl.setText(
                "Cet assistant configure les positions DMX\n"
                "de votre roue de couleur en temps réel.\n\n"
                "Assurez-vous que la lyre est alimentée et connectée.\n"
                "Le Shutter et le Dimmer seront mis à fond automatiquement."
            )
            self._slider_w.setVisible(False)
            self._btn_prev.setVisible(False)
            self._btn_next.setText("Démarrer  ▶")

        else:
            name, color, label = _CALIB_STEPS[step]

            self._progress_lbl.setText(f"Couleur {step + 1} / {len(_CALIB_STEPS)}")

            self._circle.setStyleSheet(
                f"background:{color};border-radius:38px;border:3px solid #555;"
            )
            self._circle_wrap.setVisible(True)

            self._title_lbl.setText(label)
            # Use the color directly; if it's dark against our dark background,
            # fall back to a lighter tint by reducing darkness threshold.
            lum = sum(int(color.lstrip('#')[i*2:i*2+2], 16) * w
                      for i, w in enumerate((0.299, 0.587, 0.114)))
            display_color = color if lum > 60 else "#aaaaaa"
            self._title_lbl.setStyleSheet(f"color:{display_color};")

            self._instr_lbl.setText(
                "Bougez le curseur jusqu'à ce que votre lyre\n"
                "affiche cette couleur, puis cliquez sur Suivant."
            )

            self._slider_w.setVisible(True)
            # Block signal to avoid sending DMX prematurely
            self._sli.blockSignals(True)
            self._sli.setValue(self._values[step])
            self._val_lbl.setText(str(self._values[step]))
            self._sli.blockSignals(False)

            # Send current value live
            self._proj.color_wheel = self._values[step]
            self._send_dmx()

            self._btn_prev.setVisible(True)
            self._btn_prev.setEnabled(step > 0)

            if step == len(_CALIB_STEPS) - 1:
                self._btn_next.setText("✓  Terminer")
            else:
                self._btn_next.setText("Suivant  ▶")

    # ── Navigation ────────────────────────────────────────────────────────────

    def _toggle_shutter_inverted(self):
        self._proj.shutter_inverted = not getattr(self._proj, 'shutter_inverted', False)
        self._send_dmx()
        if self._proj.shutter_inverted:
            self._btn_shutter_inv.setText("✓  Shutter inversé — cliquer pour annuler")
            self._btn_shutter_inv.setStyleSheet(
                "QPushButton { background: transparent; color: #ffaa00; border: none;"
                " font-size: 11px; text-decoration: underline; padding: 2px 0; }"
                "QPushButton:hover { color: #ff7700; }"
            )
        else:
            self._btn_shutter_inv.setText("💡  Ma lyre ne s'allume pas")
            self._btn_shutter_inv.setStyleSheet(
                "QPushButton { background: transparent; color: #888; border: none;"
                " font-size: 11px; text-decoration: underline; padding: 2px 0; }"
                "QPushButton:hover { color: #ffaa00; }"
            )

    def _go_next(self):
        if self._step == -1:
            # Démarrer : mettre shutter et dim à fond
            self._proj.shutter = 255
            self._proj.level   = 100
            self._proj.color_wheel = self._values[0]
            self._send_dmx()
            self._btn_shutter_inv.setVisible(True)
            self._show_step(0)
        elif self._step < len(_CALIB_STEPS) - 1:
            self._show_step(self._step + 1)
        else:
            self._save()

    def _go_prev(self):
        if self._step > 0:
            self._show_step(self._step - 1)

    # ── Sauvegarde ────────────────────────────────────────────────────────────

    def _save(self):
        slots = [
            {"name": name, "color": color, "dmx": self._values[i]}
            for i, (name, color, _label) in enumerate(_CALIB_STEPS)
        ]

        # Appliquer à toutes les fixtures de même nom (même modèle de lyre)
        base = (self._proj.name or self._proj.group).rsplit(" ", 1)[0]
        targets = [
            p for p in self._all_projectors
            if (p.name or "").rsplit(" ", 1)[0] == base
            and getattr(p, 'fixture_type', '') == "Moving Head"
        ]
        if not targets:
            targets = [self._proj]

        for p in targets:
            p.color_wheel_slots = [dict(s) for s in slots]
            p._needs_cw_calib = False
            p.shutter_inverted = getattr(self._proj, 'shutter_inverted', False)

        if self._mw and hasattr(self._mw, 'save_dmx_patch_config'):
            self._mw.save_dmx_patch_config()

        self.accept()

    def _on_cancel(self):
        # Restaurer l'état original de la lyre (y compris shutter_inverted)
        self._proj.shutter          = self._orig_shutter
        self._proj.shutter_inverted = self._orig_shutter_inv
        self._proj.level            = self._orig_level
        self._proj.color_wheel      = self._orig_cw
        self._send_dmx()
        self.reject()
