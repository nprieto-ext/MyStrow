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
from i18n import tr

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
        self._color_btn.setToolTip(tr("cwe2_click_colour"))
        self._color_btn.clicked.connect(self._pick_color)
        row.addWidget(self._color_btn)

        # ── Nom ───────────────────────────────────────────────────────────
        self._name = QLineEdit(slot.get("name", ""))
        self._name.setPlaceholderText(tr("cwe_name"))
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
        self._btn_del.setToolTip(tr("cwe_del_slot"))
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

        self.setWindowTitle(tr("cwe_wheel_named", a0=proj.name or proj.group))
        self.setMinimumSize(520, 500)
        self.resize(540, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_DLG_SS)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── En-tête ───────────────────────────────────────────────────────
        title_lbl = QLabel(tr("cwe_wheel"))
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_lbl.setStyleSheet("color:#00d4ff;")
        root.addWidget(title_lbl)

        sub_lbl = QLabel(
            tr("cwe_color_intro")
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

        live_lbl = QLabel(tr("cwe_test_live"))
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
        btn_add = QPushButton(tr("cwe2_add_colour"))
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
                tr("cwe_only_type", a0=(proj.name or proj.group).rsplit(' ', 1)[0], a1=len(_same_name) + 1)
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
        btn_cancel = QPushButton(tr("cwe_cancel"))
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton(tr("cwe_save"))
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

        self.setWindowTitle(tr("cwe_gobo_named", a0=proj.name or proj.group))
        self.setMinimumSize(520, 500)
        self.resize(540, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_DLG_SS)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── En-tête ───────────────────────────────────────────────────────
        title_lbl = QLabel(tr("cwe_gobo_wheel"))
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_lbl.setStyleSheet("color:#ff9900;")
        root.addWidget(title_lbl)

        sub_lbl = QLabel(
            tr("cwe_gobo_intro")
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

        live_lbl = QLabel(tr("cwe_test_live"))
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
        btn_add = QPushButton(tr("cwe2_add_gobo"))
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
                tr("cwe_only_type", a0=(proj.name or proj.group).rsplit(' ', 1)[0], a1=len(_same_name) + 1)
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
        btn_cancel = QPushButton(tr("cwe_cancel"))
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton(tr("cwe_save"))
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

# 4e champ = étape OPTIONNELLE. Les correcteurs de température (CTO, CTB) et
# l'UV n'existent que sur une minorité de lyres : les imposer à tout le monde
# ferait enregistrer des positions DMX inventées, qui renverraient ensuite une
# couleur fausse en restitution. Elles sont donc décochées par défaut et ne
# sont sauvegardées que si l'utilisateur les déclare présentes.
_CALIB_STEPS = [
    ("Open",    "#ffffff", "Blanc / Open", False),
    ("Rouge",   "#ff2200", "Rouge",        False),
    ("Orange",  "#ff8800", "Orange",       False),
    ("Jaune",   "#ffff00", "Jaune",        False),
    ("Vert",    "#00cc44", "Vert",         False),
    ("Cyan",    "#00ccff", "Cyan",         False),
    ("Bleu",    "#0044ff", "Bleu",         False),
    ("Magenta", "#cc00ff", "Magenta",      False),
    ("CTO",     "#ffcc66", "CTO",          True),
    ("CTB",     "#aaddff", "CTB",          True),
    ("UV",      "#7722dd", "UV",           True),
]

_DEFAULT_CALIB_DMX = [0, 20, 42, 64, 85, 106, 128, 149, 170, 192, 213]

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

    Étape -1 : intro — ouvre le faisceau (Dim + obturateur), roue à 0.
    Étapes 0-7 : pour chaque couleur, l'utilisateur règle le curseur jusqu'à
                 voir la bonne couleur sur la lyre, puis clique Suivant.
    À la fin, les slots sont sauvegardés et appliqués aux fixtures similaires.
    """

    # Stratégies d'ouverture du faisceau, enchaînées par le bouton « Ma lyre ne
    # s'allume pas ». Chacune décrit un état COMPLET : (valeur forcée sur le
    # canal Strobe — 0 = ne pas forcer, shutter inversé, libellé). On ne peut
    # pas deviner où se trouve l'obturateur d'une lyre, alors on propose les
    # conventions rencontrées sur le terrain plutôt qu'une seule.
    _OPEN_MODES = [
        (255, False, "Strobe à fond — obturateur intégré au canal Strobe"),
        (32,  False, "Strobe à 32 — plage « ouvert » de certaines lyres"),
        (0,   True,  "Shutter inversé — 0 = ouvert"),
        (0,   False, "Aucune ouverture forcée"),
    ]

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
        self._orig_extras      = dict(getattr(proj, 'channel_extras', {}) or {})
        self._orig_strobe_spd  = getattr(proj, 'strobe_speed', 0)
        self._orig_base_color  = QColor(getattr(proj, 'base_color', QColor("white")))
        self._orig_color       = QColor(getattr(proj, 'color', QColor("black")))

        # Où est l'obturateur ? Beaucoup de lyres n'ont pas de canal Shutter
        # séparé : l'obturateur est INTÉGRÉ au canal Strobe, et il faut envoyer
        # ce canal à fond pour que la lyre émette. Or le moteur DMX sort
        # Strobe = 0 quand aucun strobe n'est demandé — soit obturateur fermé
        # sur ces fixtures : la calibration se faisait dans le noir complet.
        _prof = getattr(proj, 'dmx_profile', None) or []
        self._has_shutter = 'Shutter' in _prof
        self._has_strobe  = 'Strobe'  in _prof
        # Mode de départ : forcer le Strobe seulement quand il n'y a PAS de
        # canal Shutter distinct — sinon on ferait strober une lyre dont
        # l'obturateur est déjà géré, et les couleurs clignoteraient.
        self._open_mode = 0 if (self._has_strobe and not self._has_shutter) else 3

        # Initialiser les valeurs depuis les slots existants ou les défauts
        existing = getattr(proj, 'color_wheel_slots', [])
        self._values: list[int] = []
        # `_present` dit ce qui sera ECRIT a la fin. Une etape obligatoire l'est
        # toujours ; une optionnelle ne l'est que si la lyre a deja ce slot,
        # c'est-a-dire si l'utilisateur l'a declaree lors d'une passe precedente
        # (ou si le profil OFL la fournit).
        self._present: list[bool] = []
        for i, (name, color, label, optional) in enumerate(_CALIB_STEPS):
            match = next(
                (s for s in existing if s.get('name', '').lower() == name.lower()), None
            )
            self._values.append(match['dmx'] if match else _DEFAULT_CALIB_DMX[i])
            self._present.append(True if not optional else match is not None)

        # Slots que l'assistant ne couvre pas (Rose, ou tout nom saisi a la main
        # dans l'editeur). Ils sont mis de cote ici pour etre RECOPIES au moment
        # d'enregistrer : sans cela, une passe de calibration les effacait.
        _connus = {n.lower() for n, _c, _l, _o in _CALIB_STEPS}
        self._extra_slots = [
            dict(s) for s in existing
            if s.get('name', '').strip().lower() not in _connus
        ]

        self.setWindowTitle(tr("cwe_calib_title"))
        # 410 et non 380 : les etapes optionnelles ajoutent une ligne de consigne
        # et la case « Ma lyre possede cette couleur ». Hauteur FIXE malgre tout,
        # pour que la fenetre ne saute pas d'une etape a l'autre.
        self.setFixedSize(460, 410)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_DLG_SS)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(14)

        # ── Titre ────────────────────────────────────────────────────────────
        self._title_lbl = QLabel(tr("cwe_calib_title"))
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

        # ── Présence de la couleur (étapes optionnelles) ──────────────────────
        self._chk_present = QCheckBox(tr("cwe_calib_has_colour"))
        self._chk_present.setStyleSheet("color:#ffaa00;font-size:11px;")
        self._chk_present.setCursor(QCursor(Qt.PointingHandCursor))
        self._chk_present.toggled.connect(self._on_present_toggled)
        self._chk_present.setVisible(False)
        root.addWidget(self._chk_present, alignment=Qt.AlignCenter)

        # ── Séparateur ────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(sep)

        # ── Bouton shutter inversé ────────────────────────────────────────────
        self._btn_shutter_inv = QPushButton(tr("cwe2_no_light"))
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

        btn_cancel = QPushButton(tr("cwe_cancel"))
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.clicked.connect(self._on_cancel)

        self._btn_prev = QPushButton(tr("cwe2_prev"))
        self._btn_prev.setStyleSheet(_BTN_PREV)
        self._btn_prev.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_prev.clicked.connect(self._go_prev)

        self._btn_next = QPushButton(tr("cwe2_start"))
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
            # Chercher la position au curseur SUR une etape optionnelle, c'est
            # declarer qu'on a trouve la couleur : cocher tout seul evite le
            # piege de la regler puis de la perdre en cliquant « Suivant ».
            if _CALIB_STEPS[self._step][3] and not self._present[self._step]:
                self._chk_present.setChecked(True)
            self._proj.color_wheel = v
            self._send_dmx()

    def _on_present_toggled(self, on: bool):
        if self._step >= 0 and _CALIB_STEPS[self._step][3]:
            self._present[self._step] = on

    # ── Affichage par étape ───────────────────────────────────────────────────

    def _show_step(self, step: int):
        self._step = step

        if step == -1:
            self._title_lbl.setText(tr("cwe_calib_title"))
            self._title_lbl.setStyleSheet("color:#00d4ff;")
            # Annoncer 11 couleurs decouragerait : 3 ne concernent qu'une
            # minorite de lyres. On separe les deux comptes.
            _n_opt = sum(1 for s in _CALIB_STEPS if s[3])
            self._progress_lbl.setText(
                tr("cwe_n_colors_opt", a0=len(_CALIB_STEPS) - _n_opt, a1=_n_opt)
            )
            self._circle_wrap.setVisible(False)
            self._instr_lbl.setText(
                tr("cwe_calib_intro")
            )
            self._slider_w.setVisible(False)
            self._chk_present.setVisible(False)
            self._btn_prev.setVisible(False)
            self._btn_next.setText(tr("cwe2_start"))

        else:
            name, color, label, optional = _CALIB_STEPS[step]

            self._progress_lbl.setText(tr("cwe_color_n", a0=step + 1, a1=len(_CALIB_STEPS)))

            self._circle.setStyleSheet(
                f"background:{color};border-radius:38px;border:3px solid #555;"
            )
            self._circle_wrap.setVisible(True)

            self._title_lbl.setText(
                f"{label} — {tr('cwe_calib_optional')}" if optional else label)
            # Use the color directly; if it's dark against our dark background,
            # fall back to a lighter tint by reducing darkness threshold.
            lum = sum(int(color.lstrip('#')[i*2:i*2+2], 16) * w
                      for i, w in enumerate((0.299, 0.587, 0.114)))
            display_color = color if lum > 60 else "#aaaaaa"
            self._title_lbl.setStyleSheet(f"color:{display_color};")

            self._instr_lbl.setText(
                tr("cwe_calib_optional_step") if optional else tr("cwe_calib_step")
            )

            # La case reflete l'etat courant sans le reecrire : `setChecked`
            # declenche `toggled`, qui repasserait par `_on_present_toggled`
            # avec l'etape deja changee.
            self._chk_present.setVisible(optional)
            if optional:
                self._chk_present.blockSignals(True)
                self._chk_present.setChecked(self._present[step])
                self._chk_present.blockSignals(False)

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
                self._btn_next.setText(tr("cwe_finish"))
            else:
                self._btn_next.setText(tr("cwe_next"))

    # ── Navigation ────────────────────────────────────────────────────────────

    def _apply_open_mode(self):
        """Applique la stratégie d'ouverture courante (obturateur + strobe)."""
        sval, inv, _lbl = self._OPEN_MODES[self._open_mode]
        self._proj.shutter          = 255
        self._proj.shutter_inverted = inv
        # Blanc plein : régler `level` ne suffit PAS à ouvrir le dimmer. Le
        # moteur DMX compare `color` à `base_color × level` pour détecter un
        # effet en cours ; en partant d'une lyre éteinte (color noire) il
        # concluait « effet actif, luminosité nulle » et sortait Dim = 0 — la
        # calibration se faisait donc dans le noir sur toute fixture à canal Dim.
        self._proj.base_color       = QColor(255, 255, 255)
        self._proj.color            = QColor(255, 255, 255)
        # Un strobe qui tournait avant la calibration ferait clignoter la lyre :
        # on juge une couleur à faisceau STABLE.
        self._proj.strobe_speed     = 0
        extras = dict(self._orig_extras)
        if sval > 0 and self._has_strobe:
            # Contrôle brut : c'est le seul chemin qui peut sortir une valeur
            # arbitraire sur le canal Strobe (le moteur, lui, n'en sort que 0
            # ou une vitesse de strobe).
            extras['Strobe'] = sval
        else:
            extras.pop('Strobe', None)
        self._proj.channel_extras = extras
        self._send_dmx()
        self._refresh_open_btn()

    def _refresh_open_btn(self):
        _s, _i, lbl = self._OPEN_MODES[self._open_mode]
        if self._open_mode == 0 and not self._has_strobe:
            lbl = "Aucune ouverture forcée"
        self._btn_shutter_inv.setText(tr("cwe_not_lighting", lbl=lbl))
        _actif = self._OPEN_MODES[self._open_mode][0] > 0 or self._OPEN_MODES[self._open_mode][1]
        _col = "#ffaa00" if _actif else "#888"
        self._btn_shutter_inv.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            f" color: {_col}; font-size: 11px; text-decoration: underline; padding: 2px 0; }}"
            "QPushButton:hover { color: #ff7700; }"
        )

    def _toggle_shutter_inverted(self):
        """Essai suivant : on fait défiler les conventions d'ouverture."""
        self._open_mode = (self._open_mode + 1) % len(self._OPEN_MODES)
        self._apply_open_mode()

    def _go_next(self):
        if self._step == -1:
            # Démarrer : dimmer à fond + ouverture du faisceau (shutter OU strobe)
            self._proj.level   = 100
            self._proj.color_wheel = self._values[0]
            self._apply_open_mode()
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
        # Une etape optionnelle non declaree n'est PAS ecrite : un slot « UV »
        # sur une lyre qui n'en a pas enverrait la roue sur une position au
        # hasard. Les slots hors assistant (Rose, noms saisis a la main) sont
        # recopies : la liste etait jusqu'ici reconstruite a partir des seules
        # etapes, ce qui les effacait a chaque calibration.
        slots = [
            {"name": name, "color": color, "dmx": self._values[i]}
            for i, (name, color, _label, _opt) in enumerate(_CALIB_STEPS)
            if self._present[i]
        ] + self._extra_slots

        # Appliquer à toutes les fixtures de même nom (même modèle de lyre)
        base = (self._proj.name or self._proj.group).rsplit(" ", 1)[0]
        targets = [
            p for p in self._all_projectors
            if (p.name or "").rsplit(" ", 1)[0] == base
            and getattr(p, 'fixture_type', '') == "Moving Head"
        ]
        if not targets:
            targets = [self._proj]

        # Ouverture retenue : elle doit SURVIVRE à la calibration, sinon la lyre
        # se rallume noire dès qu'on quitte l'assistant. `channel_extras` est un
        # override temporaire ; la forme persistante d'un « canal à ouvrir » est
        # `channel_defaults`, appliqué par le moteur quand le canal sortirait 0
        # (donc sans jamais gêner un vrai strobe demandé plus tard).
        _sval, _inv, _ = self._OPEN_MODES[self._open_mode]
        for p in targets:
            p.color_wheel_slots = [dict(s) for s in slots]
            p._needs_cw_calib = False
            p.shutter_inverted = _inv
            if _sval > 0 and self._has_strobe:
                _d = dict(getattr(p, 'channel_defaults', {}) or {})
                _d['Strobe'] = _sval
                p.channel_defaults = _d

        # Retirer l'override brut posé pendant la calibration
        self._proj.channel_extras = dict(self._orig_extras)

        if self._mw and hasattr(self._mw, 'save_dmx_patch_config'):
            self._mw.save_dmx_patch_config()

        self._send_dmx()
        self.accept()

    def _on_cancel(self):
        # Restaurer l'état original de la lyre (y compris shutter_inverted et
        # l'ouverture brute posée sur le canal Strobe pendant l'assistant)
        self._proj.shutter          = self._orig_shutter
        self._proj.shutter_inverted = self._orig_shutter_inv
        self._proj.level            = self._orig_level
        self._proj.color_wheel      = self._orig_cw
        self._proj.channel_extras   = dict(self._orig_extras)
        self._proj.strobe_speed     = self._orig_strobe_spd
        self._proj.base_color       = QColor(self._orig_base_color)
        self._proj.color            = QColor(self._orig_color)
        self._send_dmx()
        self.reject()
