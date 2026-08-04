"""
CueListPanel — éditeur de cues, panneau flottant.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QSlider,
)
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QFont, QBrush, QPainter, QPen

_EFFECT_EMOJI_CACHE: dict | None = None

def _effect_emoji(name: str) -> str:
    global _EFFECT_EMOJI_CACHE
    if _EFFECT_EMOJI_CACHE is None:
        try:
            from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
            all_e = list(BUILTIN_EFFECTS) + _load_custom_effects()
            _EFFECT_EMOJI_CACHE = {e["name"]: e.get("emoji", "⚡") for e in all_e}
        except Exception:
            _EFFECT_EMOJI_CACHE = {}
    return _EFFECT_EMOJI_CACHE.get(name, "⚡")

# ── Palette ────────────────────────────────────────────────────────────────
_BG     = "#0a0a0a"
_PANEL  = "#1a1a1a"
_BORDER = "#2a2a2a"
_ACCENT = "#00d4ff"
_SEL_BG = "#1e3a4a"
_TEXT   = "#e0e0e0"
_MUTED  = "#666666"

_BTN = f"""
    QPushButton {{
        background:#2a2a2a; border:1px solid #3a3a3a;
        border-radius:4px; color:{_ACCENT};
        font-weight:bold; padding:6px 12px;
    }}
    QPushButton:hover  {{ background:#3a3a3a; border-color:{_ACCENT}; }}
    QPushButton:pressed{{ background:#1a1a1a; }}
    QPushButton:disabled{{ color:#3a3a3a; border-color:#222; }}
"""
_TABLE = f"""
    QTableWidget {{
        background:{_BG}; border:1px solid {_BORDER};
        border-radius:6px; gridline-color:#161616; outline:none;
    }}
    QTableWidget::item {{
        padding:6px 10px; border-bottom:1px solid #161616;
        font-size:12px; color:{_TEXT}; outline:none;
    }}
    QTableWidget::item:selected {{
        background:{_SEL_BG}; border-left:3px solid {_ACCENT}; outline:none;
    }}
    QHeaderView::section {{
        background:{_PANEL}; color:{_MUTED};
        padding:6px 10px; border:none;
        border-bottom:2px solid {_BORDER};
        font-weight:bold; font-size:10px;
    }}
"""

# ── Échelle 3 segments : 0–10 s / 10 s–1 min / 1 min–10 min ───────────────
# ticks 0     : 0 s
# ticks 1–100 : 0.1 s → 10 s  (pas 0.1 s)
# ticks 101–200 : 10 s → 60 s  (pas 0.5 s)
# ticks 201–300 : 60 s → 600 s (pas 5.4 s)
_MAX_TICKS = 300

def _ticks_to_secs(t: int) -> float:
    if t <= 0:   return 0.0
    if t <= 100: return t * 0.1
    if t <= 200: return 10.0 + (t - 100) * 0.5
    return 60.0 + (t - 200) * 5.4

def _secs_to_ticks(s: float) -> int:
    if s <= 0:   return 0
    if s <= 10:  return min(100, round(s / 0.1))
    if s <= 60:  return min(200, 100 + round((s - 10) / 0.5))
    return min(300, 200 + round((s - 60) / 5.4))

def _fmt_ticks(t: int) -> str:
    if t == 0: return "—"
    s = _ticks_to_secs(t)
    if s < 10:  return f"{s:.1f}s"
    if s < 60:  return f"{s:.0f}s"
    m, r = divmod(int(s), 60)
    return f"{m}m{r:02d}s"

def _fmt_time(val) -> str:
    return _fmt_ticks(_secs_to_ticks(float(val)))


# ── Toggle switch ──────────────────────────────────────────────────────────
class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 22)
        self._checked = False
        self._handle_x = 3.0
        self._anim = QPropertyAnimation(self, b"handle_x", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self): return self._checked

    def setChecked(self, val: bool):
        self._checked = val
        self._handle_x = 21.0 if val else 3.0
        self.update()

    def mousePressEvent(self, e):
        self._checked = not self._checked
        self._anim.stop()
        self._anim.setStartValue(self._handle_x)
        self._anim.setEndValue(21.0 if self._checked else 3.0)
        self._anim.start()
        if not self.signalsBlocked():
            self.toggled.emit(self._checked)

    def get_handle_x(self): return self._handle_x
    def set_handle_x(self, v):
        self._handle_x = v
        self.update()
    handle_x = Property(float, get_handle_x, set_handle_x)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(_ACCENT) if self._checked else QColor("#333"))
        p.drawRoundedRect(0, 3, 42, 16, 8, 8)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(int(self._handle_x), 1, 20, 20)
        p.end()


# ── Barre de progression durée ─────────────────────────────────────────────
class _ProgressStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self._ratio = -1.0

    def set_ratio(self, r: float):
        self._ratio = r
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        if self._ratio < 0:
            p.end()
            return
        p.setBrush(QColor("#1a1a1a"))
        p.drawRect(self.rect())
        w = int(self.width() * max(0.0, min(1.0, self._ratio)))
        if w > 0:
            p.setBrush(QColor(_ACCENT))
            p.drawRect(0, 0, w, self.height())
        p.end()


# ── Popup curseur amélioré ─────────────────────────────────────────────────
class _SliderPopup(QWidget):
    committed = Signal(float)

    _SS = """
        QSlider::groove:horizontal {
            height:6px; background:#2a2a2a; border-radius:3px;
        }
        QSlider::sub-page:horizontal {
            background:#00d4ff; border-radius:3px;
        }
        QSlider::handle:horizontal {
            width:18px; height:18px; margin:-6px 0;
            background:#fff; border-radius:9px;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(320, 100)

        outer = QWidget(self)
        outer.setObjectName("sp_outer")
        outer.setStyleSheet("""
            QWidget#sp_outer {
                background:#161616; border:1px solid #2a2a2a; border-radius:10px;
            }
        """)
        outer.setGeometry(0, 0, 320, 100)

        vl = QVBoxLayout(outer)
        vl.setContentsMargins(14, 10, 14, 8)
        vl.setSpacing(6)

        # Ligne titre + valeur
        top = QHBoxLayout()
        self._key_lbl = QLabel("Durée")
        self._key_lbl.setStyleSheet("color:#666; font-size:10px; font-weight:bold; background:transparent;")
        top.addWidget(self._key_lbl)
        top.addStretch()
        self._val_lbl = QLabel("—")
        self._val_lbl.setStyleSheet("color:#00d4ff; font-size:15px; font-weight:bold; background:transparent;")
        top.addWidget(self._val_lbl)
        vl.addLayout(top)

        # Slider
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, _MAX_TICKS)
        self._slider.setStyleSheet(self._SS)
        self._slider.valueChanged.connect(lambda v: self._val_lbl.setText(_fmt_ticks(v)))
        self._slider.sliderReleased.connect(self._on_release)
        vl.addWidget(self._slider)

        # Repères de segments
        marks = QHBoxLayout()
        marks.setContentsMargins(0, 0, 0, 0)
        for txt in ("0", "10s", "1min", "10min"):
            lbl = QLabel(txt)
            lbl.setStyleSheet("color:#444; font-size:9px; background:transparent;")
            if txt == "0":
                lbl.setAlignment(Qt.AlignLeft)
            elif txt == "10min":
                lbl.setAlignment(Qt.AlignRight)
            else:
                lbl.setAlignment(Qt.AlignCenter)
            marks.addWidget(lbl, 1)
        vl.addLayout(marks)

    def show_for(self, key: str, current_secs: float, global_pos):
        self._key_lbl.setText(key)
        t = _secs_to_ticks(current_secs)
        self._slider.blockSignals(True)
        self._slider.setValue(t)
        self._slider.blockSignals(False)
        self._val_lbl.setText(_fmt_ticks(t))
        x = global_pos.x() - self.width() // 2
        y = global_pos.y() - self.height() - 8
        self.move(x, y)
        self.show()

    def _on_release(self):
        self.committed.emit(_ticks_to_secs(self._slider.value()))
        self.hide()



# ── Panel principal ────────────────────────────────────────────────────────
class CueListPanel(QWidget):
    cues_changed         = Signal()
    cue_activated        = Signal(int)
    effect_pick_requested = Signal(int)   # row index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mem_col = -1
        self.row     = -1
        self.mem_data: dict | None = None
        self._popup     = _SliderPopup()
        self._popup.committed.connect(self._on_popup_committed)
        self._popup_col = -1
        self._popup_row = -1
        self.setStyleSheet(f"background:{_BG}; color:{_TEXT};")
        self._build_ui()
        self._show_empty()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # En-tête : count à gauche, boucle à droite
        hdr = QHBoxLayout()
        self._active_idx = 0
        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet(f"color:{_ACCENT}; font-size:12px; font-weight:bold;")
        hdr.addWidget(self._lbl_count)
        hdr.addStretch()
        loop_lbl = QLabel("Boucle")
        loop_lbl.setStyleSheet(f"color:{_MUTED}; font-size:10px;")
        hdr.addWidget(loop_lbl)
        hdr.addSpacing(6)
        self._chk_loop = ToggleSwitch()
        self._chk_loop.toggled.connect(self._on_loop)
        hdr.addWidget(self._chk_loop)
        root.addLayout(hdr)

        # Barre de progression durée (fine ligne bleue)
        self._progress = _ProgressStrip()
        root.addWidget(self._progress)

        # Barre d'outils : ▲▼ = naviguer, 🗑 = supprimer
        tb = QHBoxLayout()
        tb.setSpacing(6)
        self._btn_prev = self._mk_btn("▲", self._nav_prev)
        self._btn_next = self._mk_btn("▼", self._nav_next)
        self._btn_del  = self._mk_btn("🗑", self._delete_cue)
        for b in (self._btn_prev, self._btn_next, self._btn_del):
            b.setFixedSize(40, 32)
            tb.addWidget(b)
        tb.addStretch()
        root.addLayout(tb)

        # Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["#", "Label", "Durée", "Fade", "Effet"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(40)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 32)
        self._table.setColumnWidth(1, 110)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 90)
        self._table.setStyleSheet(_TABLE)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)
        root.addWidget(self._table)

        # Placeholder
        self._placeholder = QLabel("Ouvre le menu d'un pad mémoire\npuis clique sur  📋 Cues")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(f"color:{_MUTED}; font-size:13px;")
        root.addWidget(self._placeholder)

    def _mk_btn(self, text, slot):
        b = QPushButton(text)
        b.setStyleSheet(_BTN)
        b.clicked.connect(slot)
        return b

    # ── API publique ──────────────────────────────────────────────────────

    def load(self, mem_col: int, row: int, mem_data: dict):
        self.mem_col  = mem_col
        self.row      = row
        self.mem_data = mem_data
        self._table.show()
        self._placeholder.hide()
        self._chk_loop.blockSignals(True)
        self._chk_loop.setChecked(mem_data.get("loop", True))
        self._chk_loop.blockSignals(False)
        self._refresh()

    def add_cue(self, cue: dict):
        if self.mem_data is None:
            return
        n = len(self.cues)
        cue.setdefault("label", f"Cue {n + 1}")
        cue.setdefault("duration", 0)
        cue.setdefault("fade", 0)
        self.cues.append(cue)
        self._refresh()
        self._table.selectRow(len(self.cues) - 1)
        self.cues_changed.emit()

    def _update_count_label(self):
        n = len(self.cues) if self.mem_data else 0
        if n == 0:
            self._lbl_count.setText("")
        else:
            self._lbl_count.setText(f"{self._active_idx + 1} / {n}")

    def highlight_cue(self, idx: int):
        self._active_idx = idx
        self._update_count_label()
        self._table.selectionModel().currentRowChanged.disconnect(self._on_row_changed)
        for r in range(self._table.rowCount()):
            is_active = (r == idx)
            for c in range(self._table.columnCount()):
                item = self._table.item(r, c)
                if item:
                    item.setForeground(QBrush(QColor(_ACCENT) if is_active else QColor(_TEXT)))
        if 0 <= idx < self._table.rowCount():
            self._table.setCurrentCell(idx, 0)
            self._table.scrollToItem(self._table.item(idx, 0))
        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)

    def set_cue_effect(self, row: int, eff_name: str):
        """Met à jour la cellule Effet d'une ligne (appelé depuis main_window)."""
        item = self._table.item(row, 4)
        if item:
            item.setText(f"{_effect_emoji(eff_name)} {eff_name}" if eff_name else "—")
            item.setForeground(QBrush(QColor(_ACCENT) if eff_name else QColor(_MUTED)))

    def set_progress(self, ratio: float):
        """ratio ∈ [0,1] = avancement de la durée courante ; -1 = masqué."""
        self._progress.set_ratio(ratio)

    # ── Interne ───────────────────────────────────────────────────────────

    def _show_empty(self):
        self._table.hide()
        self._placeholder.show()
        self._active_idx = 0
        self._lbl_count.setText("")
        self._progress.set_ratio(-1)

    @property
    def cues(self):
        return self.mem_data["cues"] if self.mem_data else []

    def _refresh(self):
        self._table.selectionModel().currentRowChanged.disconnect(self._on_row_changed)
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for i, cue in enumerate(self.cues):
            self._add_row(i, cue)
        self._table.blockSignals(False)
        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self._update_count_label()

    def _add_row(self, idx: int, cue: dict):
        self._table.insertRow(idx)
        _ro = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        _rw = _ro | Qt.ItemIsEditable

        num = QTableWidgetItem(str(idx + 1))
        num.setTextAlignment(Qt.AlignCenter)
        num.setFlags(_ro)
        num.setForeground(QBrush(QColor(_MUTED)))
        self._table.setItem(idx, 0, num)

        lbl = QTableWidgetItem(cue.get("label", f"Cue {idx + 1}"))
        lbl.setFont(QFont("Segoe UI", 11))
        lbl.setFlags(_rw)
        self._table.setItem(idx, 1, lbl)

        dur_val = float(cue.get("duration", 0))
        dur = QTableWidgetItem(_fmt_time(dur_val))
        dur.setTextAlignment(Qt.AlignCenter)
        dur.setFlags(_ro)
        dur.setForeground(QBrush(QColor(_ACCENT) if dur_val > 0 else QColor(_MUTED)))
        self._table.setItem(idx, 2, dur)

        fade_val = float(cue.get("fade", 0))
        fade = QTableWidgetItem(_fmt_time(fade_val))
        fade.setTextAlignment(Qt.AlignCenter)
        fade.setFlags(_ro)
        fade.setForeground(QBrush(QColor(_ACCENT) if fade_val > 0 else QColor(_MUTED)))
        self._table.setItem(idx, 3, fade)

        eff_name = (cue.get("effect") or {}).get("name", "")
        eff_item = QTableWidgetItem(f"{_effect_emoji(eff_name)} {eff_name}" if eff_name else "—")
        eff_item.setTextAlignment(Qt.AlignCenter)
        eff_item.setFlags(_ro)
        eff_item.setForeground(QBrush(QColor(_ACCENT) if eff_name else QColor(_MUTED)))
        self._table.setItem(idx, 4, eff_item)

    def _current_idx(self):
        return self._table.currentRow()

    def _on_row_changed(self, current, _previous):
        row = current.row()
        if 0 <= row < len(self.cues):
            self.cue_activated.emit(row)

    def _on_cell_clicked(self, row: int, col: int):
        if not (0 <= row < len(self.cues)):
            return
        if col in (2, 3):
            key   = "Durée" if col == 2 else "Fade"
            field = "duration" if col == 2 else "fade"
            cur   = float(self.cues[row].get(field, 0))
            rect  = self._table.visualItemRect(self._table.item(row, col))
            pos   = self._table.viewport().mapToGlobal(rect.center())
            self._popup_col = col
            self._popup_row = row
            self._popup.show_for(key, cur, pos)
        elif col == 4:
            self.effect_pick_requested.emit(row)

    def _on_popup_committed(self, secs: float):
        row, col = self._popup_row, self._popup_col
        if not (0 <= row < len(self.cues)) or col not in (2, 3):
            return
        cue = self.cues[row]
        if col == 2:  # Durée
            cue["duration"] = secs
            # Fade ne peut pas dépasser la durée
            if secs > 0 and float(cue.get("fade", 0)) > secs:
                cue["fade"] = secs
                self._refresh_cell(row, 3, secs)
        else:  # Fade
            cue["fade"] = secs
            # Durée doit être au moins égale au fade
            dur = float(cue.get("duration", 0))
            if secs > 0 and (dur == 0 or dur < secs):
                cue["duration"] = secs
                self._refresh_cell(row, 2, secs)
        self._table.blockSignals(True)
        item = self._table.item(row, col)
        if item:
            item.setText(_fmt_time(secs))
            item.setForeground(QBrush(QColor(_ACCENT) if secs > 0 else QColor(_MUTED)))
        self._table.blockSignals(False)
        self.cues_changed.emit()

    def _refresh_cell(self, row: int, col: int, secs: float):
        self._table.blockSignals(True)
        item = self._table.item(row, col)
        if item:
            item.setText(_fmt_time(secs))
            item.setForeground(QBrush(QColor(_ACCENT) if secs > 0 else QColor(_MUTED)))
        self._table.blockSignals(False)

    # — Navigation ▲▼
    def _nav_prev(self):
        i = self._current_idx()
        n = len(self.cues)
        if n == 0:
            return
        target = (i - 1) % n if self.mem_data and self.mem_data.get("loop", True) else max(0, i - 1)
        if target != i:
            self._table.selectRow(target)

    def _nav_next(self):
        i = self._current_idx()
        n = len(self.cues)
        if n == 0:
            return
        target = (i + 1) % n if self.mem_data and self.mem_data.get("loop", True) else min(n - 1, i + 1)
        if target != i:
            self._table.selectRow(target)

    # — Réordonnancement (drag & drop + clic droit)
    def _on_rows_reordered(self, src: int, dst: int):
        if not self.mem_data or not (0 <= src < len(self.cues)) or not (0 <= dst < len(self.cues)):
            return
        cue = self.cues.pop(src)
        self.cues.insert(dst, cue)
        self._refresh()
        self._table.selectRow(dst)
        self.cues_changed.emit()

    def _reorder_up(self, i: int):
        self._reorder_by(i, -1)

    def _reorder_down(self, i: int):
        self._reorder_by(i, 1)

    def _reorder_by(self, i: int, delta: int):
        if not self.mem_data:
            return
        target = max(0, min(len(self.cues) - 1, i + delta))
        if target == i:
            return
        cue = self.cues.pop(i)
        self.cues.insert(target, cue)
        self._refresh()
        self._table.selectRow(target)
        self.cues_changed.emit()

    def _reorder_to(self, i: int, target: int):
        if not self.mem_data or target == i:
            return
        target = max(0, min(len(self.cues) - 1, target))
        cue = self.cues.pop(i)
        self.cues.insert(target, cue)
        self._refresh()
        self._table.selectRow(target)
        self.cues_changed.emit()

    def _on_table_context_menu(self, pos):
        idx = self._table.rowAt(pos.y())
        if idx < 0 or not self.mem_data:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background:#1a1a1a; border:1px solid #2a2a2a;
                     border-radius:6px; color:{_TEXT}; }}
            QMenu::item {{ padding:6px 16px; font-size:11px; }}
            QMenu::item:selected {{ background:{_SEL_BG}; color:{_ACCENT}; }}
            QMenu::item:disabled {{ color:#444; }}
            QMenu::separator {{ height:1px; background:#2a2a2a; margin:3px 0; }}
        """)
        n = len(self.cues)
        top    = menu.addAction("⏫  En premier")
        up5    = menu.addAction("⬆⬆  Monter de 5")
        up     = menu.addAction("⬆  Monter")
        menu.addSeparator()
        down   = menu.addAction("⬇  Descendre")
        down5  = menu.addAction("⬇⬇  Descendre de 5")
        bot    = menu.addAction("⏬  En dernier")
        menu.addSeparator()
        delete = menu.addAction("🗑  Supprimer")

        top.setEnabled(idx > 0)
        up5.setEnabled(idx > 0)
        up.setEnabled(idx > 0)
        down.setEnabled(idx < n - 1)
        down5.setEnabled(idx < n - 1)
        bot.setEnabled(idx < n - 1)
        delete.setEnabled(n > 1)

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen == top:
            self._reorder_to(idx, 0)
        elif chosen == up5:
            self._reorder_by(idx, -5)
        elif chosen == up:
            self._reorder_by(idx, -1)
        elif chosen == down:
            self._reorder_by(idx, 1)
        elif chosen == down5:
            self._reorder_by(idx, 5)
        elif chosen == bot:
            self._reorder_to(idx, n - 1)
        elif chosen == delete:
            self._delete_row(idx)

    def _delete_row(self, idx: int):
        if not self.mem_data or len(self.cues) <= 1:
            return
        self.cues.pop(idx)
        self._refresh()
        self.cues_changed.emit()

    def _delete_cue(self):
        self._delete_row(self._current_idx())

    def _on_item_changed(self, item: QTableWidgetItem):
        if not self.mem_data or item.column() != 1:
            return
        idx = item.row()
        if 0 <= idx < len(self.cues):
            self.cues[idx]["label"] = item.text()
            self.cues_changed.emit()

    def _on_loop(self, checked: bool):
        if self.mem_data:
            self.mem_data["loop"] = checked
            self.cues_changed.emit()
