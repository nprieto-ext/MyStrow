"""
DMX Tester — 512 faders verticaux avec sélection multiple.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QWidget, QFrame, QSpinBox, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QLinearGradient


# ── Dimensions des faders ─────────────────────────────────────────────────────
FADER_W  = 18   # largeur de chaque fader (px)
FADER_H  = 72   # hauteur de la zone de fader
LABEL_H  = 12   # hauteur du numéro de canal en-dessous
GAP      = 2    # espace entre faders
COLS     = 32
ROWS     = 16
SLOT_W   = FADER_W + GAP    # 20
SLOT_H   = FADER_H + LABEL_H + GAP + 2   # 88


# ── Widget faders ─────────────────────────────────────────────────────────────

class DmxFaderView(QWidget):
    """
    Affiche 512 canaux DMX comme des faders verticaux.
    - Clic            → sélectionner + régler la valeur
    - Glisser         → modifier la valeur en live
    - Ctrl + clic     → ajouter / retirer de la sélection
    - Shift + clic    → sélectionner la plage
    """

    selection_changed = Signal(list)   # liste d'indices 0-based sélectionnés
    value_changed     = Signal(int, int)  # (channel, value) — drag direct sur fader

    def __init__(self):
        super().__init__()
        self._values    = [0] * 512
        self._selected  = set()
        self._hovered   = -1
        self._last      = 0

        self._drag_mode = None   # 'value' | None
        self._drag_ch   = -1

        self.setFixedSize(COLS * SLOT_W - GAP, ROWS * SLOT_H - GAP)
        self.setMouseTracking(True)
        self.setCursor(Qt.SizeVerCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    # ── Données ──────────────────────────────────────────────────────────────

    def set_values(self, values):
        self._values = list(values[:512])
        self.update()

    def set_channel(self, ch, val):
        if 0 <= ch < 512:
            self._values[ch] = max(0, min(255, val))
        self.update()

    def set_selection(self, indices):
        self._selected = set(indices)
        self.update()

    def selected(self):
        return sorted(self._selected)

    # ── Géométrie ────────────────────────────────────────────────────────────

    def _pos_to_ch_val(self, pos):
        """Retourne (channel_index, value|None) depuis une position souris."""
        col = pos.x() // SLOT_W
        row = pos.y() // SLOT_H
        if 0 <= col < COLS and 0 <= row < ROWS:
            ch = row * COLS + col
            y_in_slot = pos.y() - row * SLOT_H
            if 0 <= y_in_slot < FADER_H:
                val = max(0, min(255, int((1.0 - y_in_slot / FADER_H) * 255)))
                return ch, val
            return ch, None   # clic dans la zone étiquette
        return -1, None

    # ── Rendu ────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        for i in range(512):
            col = i % COLS
            row = i // COLS
            x   = col * SLOT_W
            y   = row * SLOT_H
            val = self._values[i]
            sel = i in self._selected
            hov = i == self._hovered

            # ── Fond du fader ──────────────────────────────
            bg = QColor("#1e1e1e") if hov and not sel else QColor("#141414")
            p.fillRect(x, y, FADER_W, FADER_H, bg)

            # ── Rainure centrale ───────────────────────────
            groove_x = x + (FADER_W - 4) // 2
            p.fillRect(groove_x, y + 2, 4, FADER_H - 4, QColor("#222222"))

            # ── Remplissage (de bas en haut) ───────────────
            t      = val / 255.0
            fill_h = max(2, int(t * (FADER_H - 4)))
            fill_y = y + FADER_H - 2 - fill_h

            if val > 0:
                grad = QLinearGradient(0, fill_y, 0, fill_y + fill_h)
                grad.setColorAt(0.0, QColor(0, int(180 + t * 75), int(200 + t * 55)))
                grad.setColorAt(1.0, QColor(0, int(40  + t * 80), int(80  + t * 80)))
                p.fillRect(groove_x, fill_y, 4, fill_h, QBrush(grad))

            # Curseur toujours visible — cyan si val > 0, gris sombre si val = 0
            handle_col = QColor(0, 220, 255, 220) if val > 0 else QColor(60, 60, 60, 200)
            p.fillRect(x + 2, fill_y, FADER_W - 4, 2, handle_col)

            # ── Sélection ──────────────────────────────────
            if sel:
                p.fillRect(x, y, FADER_W, FADER_H, QColor(0, 212, 255, 25))
                pen = QPen(QColor("#00d4ff"))
                pen.setWidth(2)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(x + 1, y + 1, FADER_W - 2, FADER_H - 2)

            # ── Numéro de canal ────────────────────────────
            alpha = 130 if (val > 0 or sel) else 50
            p.setPen(QColor(255, 255, 255, alpha))
            p.setFont(QFont("Segoe UI", 5))
            p.drawText(
                QRect(x, y + FADER_H + 2, FADER_W, LABEL_H),
                Qt.AlignCenter, str(i + 1),
            )

    # ── Souris ───────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        ch, val = self._pos_to_ch_val(e.position().toPoint())
        if ch < 0:
            return
        mods = e.modifiers()

        if mods & Qt.ControlModifier:
            if ch in self._selected:
                self._selected.discard(ch)
            else:
                self._selected.add(ch)
            self._drag_mode = None

        elif mods & Qt.ShiftModifier:
            a, b = min(self._last, ch), max(self._last, ch)
            self._selected |= set(range(a, b + 1))
            self._drag_mode = None

        else:
            self._selected  = {ch}
            self._drag_mode = 'value'
            self._drag_ch   = ch
            if val is not None:
                self._values[ch] = val
                self.value_changed.emit(ch, val)

        self._last = ch
        self.update()
        self.selection_changed.emit(self.selected())

    def mouseMoveEvent(self, e):
        ch, val = self._pos_to_ch_val(e.position().toPoint())

        if ch != self._hovered:
            self._hovered = ch
            self.update()

        if (e.buttons() & Qt.LeftButton) and self._drag_mode == 'value':
            if ch == self._drag_ch and val is not None:
                self._values[ch] = val
                self.value_changed.emit(ch, val)
                self.update()
                self.selection_changed.emit(self.selected())

    def mouseReleaseEvent(self, _):
        self._drag_mode = None

    def leaveEvent(self, _):
        self._hovered = -1
        self.update()

    def keyPressEvent(self, e):
        if e.modifiers() & Qt.ControlModifier and e.key() == Qt.Key_A:
            self._selected = set(range(512))
            self.update()
            self.selection_changed.emit(self.selected())
        else:
            super().keyPressEvent(e)


# ── Dialog ───────────────────────────────────────────────────────────────────

class DmxTesterDialog(QDialog):

    def __init__(self, dmx, parent=None):
        super().__init__(parent)
        self._dmx      = dmx
        self._uni      = 0
        self._snapshot = [list(dmx.dmx_data[u][:512]) for u in range(4)]
        self._group    = 0
        for u in range(4):
            for i in range(512):
                dmx.dmx_data[u][i] = 0

        self.setWindowTitle("DMX Tester")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog   { background: #111111; }
            QLabel    { color: #cccccc; background: transparent; border: none; }
            QSpinBox  {
                background: #1c1c1c; color: #e0e0e0;
                border: 1px solid #2a2a2a; border-radius: 4px;
                padding: 2px 6px; font-size: 11px; min-height: 24px;
            }
            QSpinBox:focus { border-color: #00d4ff; }
            QSpinBox::up-button, QSpinBox::down-button {
                background: #242424; border: none; width: 14px;
            }
            QScrollArea { border: none; background: #111111; }
            QScrollBar:vertical {
                background: #0e0e0e; width: 8px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #2a2a2a; border-radius: 4px; min-height: 20px;
            }
            QScrollBar::handle:vertical:hover { background: #3a3a3a; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._build_ui()
        self._refresh_grid()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet("background:#0a0a0a; border-bottom:1px solid #1e1e1e;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        t = QLabel("🔬  DMX Tester")
        t.setFont(QFont("Segoe UI", 13, QFont.Bold))
        t.setStyleSheet("color:#00d4ff;")
        hl.addWidget(t)
        hl.addStretch()
        self.lbl_status = QLabel("Clic + glisser pour régler  ·  Ctrl = multi-sélection  ·  Shift = plage")
        self.lbl_status.setFont(QFont("Segoe UI", 9))
        self.lbl_status.setStyleSheet("color:#333;")
        hl.addWidget(self.lbl_status)
        root.addWidget(hdr)

        # ── Corps : faders (scroll) + panneau droit ────────
        body = QWidget()
        body.setStyleSheet("background:#111111;")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(16)

        # ScrollArea contenant les faders
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFixedWidth(COLS * SLOT_W - GAP + 10)  # +10 pour la scrollbar

        self.grid = DmxFaderView()
        self.grid.selection_changed.connect(self._on_selection_changed)
        self.grid.value_changed.connect(self._on_fader_drag)
        scroll.setWidget(self.grid)
        scroll.setFixedHeight(480)
        bl.addWidget(scroll)
        self.grid.setFocus()

        bl.addWidget(self._build_right_panel())
        root.addWidget(body)

        # ── Barre canal sélectionné ────────────────────────
        ctrl = QWidget()
        ctrl.setStyleSheet("background:#0e0e0e; border-top:1px solid #1e1e1e;")
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(20, 10, 20, 10)
        cl.setSpacing(12)

        self.lbl_sel_info = QLabel("Aucun canal sélectionné")
        self.lbl_sel_info.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_sel_info.setStyleSheet("color:#555; min-width:220px;")
        cl.addWidget(self.lbl_sel_info)

        cl.addWidget(self._small_lbl("Valeur fine"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 255)
        self.slider.setValue(255)
        self.slider.setEnabled(False)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background:#1e1e1e; height:4px; border-radius:2px;
            }
            QSlider::sub-page:horizontal { background:#00d4ff; border-radius:2px; }
            QSlider::handle:horizontal {
                background:white; width:14px; height:14px;
                margin:-5px 0; border-radius:7px;
            }
            QSlider:disabled { opacity: 0.3; }
        """)
        cl.addWidget(self.slider, 1)

        self.lbl_val = QLabel("—")
        self.lbl_val.setFixedWidth(36)
        self.lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_val.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_val.setStyleSheet("color:#00d4ff;")
        cl.addWidget(self.lbl_val)

        self.slider.valueChanged.connect(self._apply_slider)
        root.addWidget(ctrl)

        # ── Footer ────────────────────────────────────────
        foot = QWidget()
        foot.setFixedHeight(50)
        foot.setStyleSheet("background:#0a0a0a; border-top:1px solid #1e1e1e;")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 0, 20, 0)
        fl.setSpacing(10)

        self.btn_on  = self._btn("●  Full ON",  "#1a2a1a", "#4CAF50")
        self.btn_off = self._btn("○  Full OFF", "#2a1a1a", "#f44336")
        self.btn_on.setToolTip("Sélection → applique à la sélection. Sans sélection → tous les 512.")
        self.btn_off.setToolTip("Sélection → applique à la sélection. Sans sélection → tous les 512.")
        self.btn_on.clicked.connect(lambda: self._send_val(255))
        self.btn_off.clicked.connect(lambda: self._send_val(0))
        fl.addWidget(self.btn_on)
        fl.addWidget(self.btn_off)
        fl.addStretch()

        btn_close = self._btn("Fermer", "#1a2a3a", "#00d4ff")
        btn_close.clicked.connect(self.close)
        fl.addWidget(btn_close)
        root.addWidget(foot)

    def _build_right_panel(self):
        w = QWidget()
        w.setFixedWidth(220)
        w.setStyleSheet(
            "background:#0e0e0e; border:1px solid #1e1e1e; border-radius:6px;"
        )
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        t = QLabel("ASSISTANT")
        t.setFont(QFont("Segoe UI", 8, QFont.Bold))
        t.setStyleSheet("color:#00d4ff; letter-spacing:2px; border:none; background:transparent;")
        lay.addWidget(t)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border:1px solid #1e1e1e;")
        lay.addWidget(sep)

        lbl_sz = QLabel("Canaux par groupe")
        lbl_sz.setFont(QFont("Segoe UI", 9))
        lbl_sz.setStyleSheet("color:#555; border:none; background:transparent;")
        lay.addWidget(lbl_sz)

        self.spin_group = QSpinBox()
        self.spin_group.setRange(1, 50)
        self.spin_group.setValue(5)
        self.spin_group.setFixedHeight(34)
        self.spin_group.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.spin_group.setStyleSheet(
            "QSpinBox{background:#1a1a1a;color:#00d4ff;border:1px solid #2a2a2a;"
            "border-radius:5px;padding:0 8px;}"
            "QSpinBox:focus{border-color:#00d4ff;}"
            "QSpinBox::up-button,QSpinBox::down-button{background:#242424;border:none;width:18px;}"
        )
        self.spin_group.valueChanged.connect(lambda: setattr(self, '_group', 0) or self._update_assistant())
        lay.addWidget(self.spin_group)

        nav = QHBoxLayout(); nav.setSpacing(6)
        self.btn_prev_grp = QPushButton("◀")
        self.btn_prev_grp.setFixedSize(30, 30)
        self.btn_prev_grp.setStyleSheet(self._nav_btn_style())
        self.btn_prev_grp.clicked.connect(self._prev_group)
        nav.addWidget(self.btn_prev_grp)

        self.lbl_group_range = QLabel("1 → 5")
        self.lbl_group_range.setAlignment(Qt.AlignCenter)
        self.lbl_group_range.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_group_range.setStyleSheet(
            "color:#00d4ff; background:#141414; border:1px solid #2a2a2a;"
            "border-radius:4px; padding:4px 2px;"
        )
        nav.addWidget(self.lbl_group_range, 1)

        self.btn_next_grp = QPushButton("▶")
        self.btn_next_grp.setFixedSize(30, 30)
        self.btn_next_grp.setStyleSheet(self._nav_btn_style())
        self.btn_next_grp.clicked.connect(self._next_group)
        nav.addWidget(self.btn_next_grp)
        lay.addLayout(nav)

        self.btn_send_grp = QPushButton("● Envoyer à 100%")
        self.btn_send_grp.setFixedHeight(30)
        self.btn_send_grp.setStyleSheet(
            "QPushButton{background:#1a2a1a;color:#4CAF50;border:1px solid #4CAF5044;"
            "border-radius:4px;font-size:10px;font-weight:bold;}"
            "QPushButton:hover{border-color:#4CAF50;}"
        )
        self.btn_send_grp.clicked.connect(self._send_group)
        lay.addWidget(self.btn_send_grp)

        btn_send_next = QPushButton("▶▶  Envoyer les suivants")
        btn_send_next.setFixedHeight(30)
        btn_send_next.setStyleSheet(
            "QPushButton{background:#1a2a2a;color:#00d4ff;border:1px solid #00d4ff44;"
            "border-radius:4px;font-size:10px;font-weight:bold;}"
            "QPushButton:hover{border-color:#00d4ff;}"
        )
        btn_send_next.clicked.connect(self._send_group_and_advance)
        lay.addWidget(btn_send_next)

        btn_cut_next = QPushButton("✂  Envoyer uniquement les suivants")
        btn_cut_next.setFixedHeight(30)
        btn_cut_next.setStyleSheet(
            "QPushButton{background:#2a1a1a;color:#f44336;border:1px solid #f4433644;"
            "border-radius:4px;font-size:10px;font-weight:bold;}"
            "QPushButton:hover{border-color:#f44336;}"
        )
        btn_cut_next.clicked.connect(self._cut_and_send_next)
        lay.addWidget(btn_cut_next)

        sep_uni = QFrame(); sep_uni.setFrameShape(QFrame.HLine)
        sep_uni.setStyleSheet("border:1px solid #1e1e1e;")
        lay.addWidget(sep_uni)

        lbl_uni = QLabel("Univers DMX")
        lbl_uni.setFont(QFont("Segoe UI", 9))
        lbl_uni.setStyleSheet("color:#555; border:none; background:transparent;")
        lay.addWidget(lbl_uni)

        uni_row = QHBoxLayout(); uni_row.setSpacing(6)
        self._uni_btns = []
        for u in range(4):
            b = QPushButton(str(u + 1))
            b.setFixedSize(38, 30)
            b.setCheckable(True)
            b.setChecked(u == 0)
            b.setStyleSheet(self._uni_btn_style(u == 0))
            b.clicked.connect(lambda _, idx=u: self._switch_universe(idx))
            uni_row.addWidget(b)
            self._uni_btns.append(b)
        lay.addLayout(uni_row)

        lay.addStretch()
        self._update_assistant()
        return w

    # ── Logique ──────────────────────────────────────────────────────────────

    def _on_fader_drag(self, ch, val):
        """Appelé en temps réel quand l'utilisateur glisse un fader."""
        self._dmx.dmx_data[self._uni][ch] = val
        self._dmx.send_dmx()
        n = len(self.grid.selected())
        txt = f"Canal {ch+1}" if n <= 1 else f"{n} canaux"
        self.lbl_sel_info.setText(f"{txt}  —  {val} / 255")
        self.lbl_sel_info.setStyleSheet("color:#00d4ff; min-width:220px;")
        self._set_slider(val)
        self.slider.setEnabled(True)
        self.lbl_val.setText(str(val))

    def _on_selection_changed(self, sel):
        n = len(sel)
        if n == 0:
            self.lbl_sel_info.setText("Aucun canal sélectionné")
            self.lbl_sel_info.setStyleSheet("color:#444; min-width:220px;")
            self.lbl_val.setText("—")
            self.slider.setEnabled(False)
        elif n == 1:
            ch  = sel[0]
            val = self._dmx.dmx_data[self._uni][ch]
            self.lbl_sel_info.setText(f"Canal {ch+1}  —  {val} / 255")
            self.lbl_sel_info.setStyleSheet("color:#00d4ff; min-width:220px;")
            self._set_slider(val)
            self.slider.setEnabled(True)
        else:
            self.lbl_sel_info.setText(f"{n} canaux sélectionnés")
            self.lbl_sel_info.setStyleSheet("color:#00d4ff; min-width:220px;")
            vals = {self._dmx.dmx_data[self._uni][c] for c in sel}
            if len(vals) == 1:
                self._set_slider(vals.pop())
            self.slider.setEnabled(True)
        self._update_status()

    def _apply_slider(self, val):
        sel = self.grid.selected()
        if not sel:
            return
        for ch in sel:
            self._dmx.dmx_data[self._uni][ch] = val
            self.grid.set_channel(ch, val)
        self._dmx.send_dmx()
        self.lbl_val.setText(str(val))
        n   = len(sel)
        txt = f"Canal {sel[0]+1}" if n == 1 else f"{n} canaux"
        self.lbl_sel_info.setText(f"{txt}  —  {val} / 255")
        self.lbl_sel_info.setStyleSheet("color:#00d4ff; min-width:220px;")

    def _send_val(self, val):
        sel = self.grid.selected()
        targets = sel if sel else list(range(512))
        for ch in targets:
            self._dmx.dmx_data[self._uni][ch] = val
        self._dmx.send_dmx()
        color = "#4CAF50" if val == 255 else "#f44336"
        label = "Full ON" if val == 255 else "Full OFF"
        n = len(targets)
        self.lbl_status.setText(f"{label} — {n} canal(s) à {val}")
        self.lbl_status.setStyleSheet(f"color:{color};")
        self._refresh_grid()

    def _restore(self):
        for u in range(4):
            for i, v in enumerate(self._snapshot[u]):
                self._dmx.dmx_data[u][i] = v
        self._dmx.send_dmx()
        self.lbl_status.setText("Show restauré ✓")
        self.lbl_status.setStyleSheet("color:#4CAF50;")
        self._refresh_grid()

    # ── Assistant groupe ──────────────────────────────────────────────────────

    def _update_assistant(self):
        size  = self.spin_group.value()
        start = self._group * size
        end   = min(start + size - 1, 511)
        self.lbl_group_range.setText(f"{start+1} → {end+1}")
        self.btn_prev_grp.setEnabled(self._group > 0)
        self.btn_next_grp.setEnabled(self._group < 511 // size)

    def _prev_group(self):
        self._group = max(0, self._group - 1)
        self._update_assistant()
        self._select_and_scroll_group()

    def _next_group(self):
        size    = self.spin_group.value()
        self._group = min(511 // size, self._group + 1)
        self._update_assistant()
        self._select_and_scroll_group()

    def _group_channels(self):
        size  = self.spin_group.value()
        start = self._group * size
        return list(range(start, min(start + size, 512)))

    def _select_and_scroll_group(self):
        chs = self._group_channels()
        self.grid.set_selection(chs)
        self._on_selection_changed(chs)
        # Scroller pour que le groupe soit visible
        if chs:
            first_ch = chs[0]
            row = first_ch // COLS
            y   = row * SLOT_H
            # Trouver le QScrollArea parent
            parent = self.grid.parent()
            if hasattr(parent, 'verticalScrollBar'):
                parent.verticalScrollBar().setValue(max(0, y - 20))

    def _send_group(self):
        chs = self._group_channels()
        self.grid.set_selection(chs)
        for ch in chs:
            self._dmx.dmx_data[self._uni][ch] = 255
        self._dmx.send_dmx()
        self._on_selection_changed(chs)
        self._set_slider(255)
        self._refresh_grid()

    def _send_group_and_advance(self):
        self._send_group()
        self._next_group()

    def _cut_and_send_next(self):
        for ch in self._group_channels():
            self._dmx.dmx_data[self._uni][ch] = 0
        self._dmx.send_dmx()
        self._next_group()
        self._send_group()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _refresh_grid(self):
        self.grid.set_values(self._dmx.dmx_data[self._uni][:512])

    def _set_slider(self, val):
        self.slider.blockSignals(True)
        self.slider.setValue(val)
        self.lbl_val.setText(str(val))
        self.slider.blockSignals(False)

    def _update_status(self):
        sel = self.grid.selected()
        if sel:
            self.lbl_status.setText(f"{len(sel)} canal(s) sélectionné(s)")
            self.lbl_status.setStyleSheet("color:#555;")

    def closeEvent(self, event):
        self._restore()
        super().closeEvent(event)

    def _small_lbl(self, text):
        l = QLabel(text)
        l.setFont(QFont("Segoe UI", 9))
        l.setStyleSheet("color:#555;")
        return l

    def _btn(self, text, bg, fg):
        b = QPushButton(text)
        b.setFixedHeight(30)
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {fg}44;"
            f"border-radius:5px;font-size:11px;font-weight:bold;padding:0 14px;}}"
            f"QPushButton:hover{{border-color:{fg};}}"
        )
        return b

    def _switch_universe(self, idx):
        self._uni = idx
        for i, b in enumerate(self._uni_btns):
            b.setChecked(i == idx)
            b.setStyleSheet(self._uni_btn_style(i == idx))
        self.grid.set_selection([])
        self._refresh_grid()
        self.lbl_status.setText(f"Univers {idx + 1} actif")
        self.lbl_status.setStyleSheet("color:#00d4ff;")

    def _uni_btn_style(self, active):
        if active:
            return ("QPushButton{background:#00d4ff22;color:#00d4ff;"
                    "border:1px solid #00d4ff;border-radius:4px;font-weight:bold;font-size:11px;}"
                    "QPushButton:hover{background:#00d4ff33;}")
        return ("QPushButton{background:#1a1a1a;color:#333;"
                "border:1px solid #222;border-radius:4px;font-size:11px;}"
                "QPushButton:hover{color:#666;border-color:#333;}")

    def _nav_btn_style(self):
        return (
            "QPushButton{background:#1a1a1a;color:#888;border:1px solid #2a2a2a;"
            "border-radius:4px;font-size:12px;}"
            "QPushButton:hover{color:white;border-color:#555;}"
            "QPushButton:disabled{color:#2a2a2a;border-color:#1e1e1e;}"
        )
