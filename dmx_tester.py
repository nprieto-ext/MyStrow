"""
DMX Tester — 512 faders verticaux avec sélection multiple.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QWidget, QFrame, QSpinBox, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QRect, QRectF, QPoint, QTimer
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QLinearGradient
from i18n import tr


# ── Dimensions des faders ─────────────────────────────────────────────────────
FADER_W   = 20   # largeur de chaque fader (px)
FADER_H   = 78   # hauteur de la zone de fader
LABEL_H   = 14   # hauteur du numéro de canal en-dessous
GAP       = 3    # espace entre faders
COLS      = 32
ROWS      = 16
SLOT_W    = FADER_W + GAP                  # 23
SLOT_H    = FADER_H + LABEL_H + 8          # 100
BLOCK     = 8    # faders regroupés par 8 pour se repérer d'un coup d'œil
BLOCK_GAP = 8    # espace supplémentaire entre deux blocs
BLOCK_W   = BLOCK * SLOT_W + BLOCK_GAP
VISIBLE_ROWS = 5

# ── Palette ───────────────────────────────────────────────────────────────────
ACCENT   = "#00d4ff"
BG       = "#101114"
SURFACE  = "#16181c"
RAISED   = "#1c1f24"
LINE     = "#262a31"
TEXT     = "#e6e8eb"
MUTED    = "#8a9099"
FAINT    = "#5a6069"
GREEN    = "#4caf50"
RED      = "#f44336"
ORANGE   = "#ff8800"


def _rgba(hex_color, alpha):
    """'#rrggbb' → 'rgba(r,g,b,a)' : Qt lit '#xxxxxxxx' en ARGB, pas en RGBA."""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(alpha * 255)})"


def _col_x(col):
    return col * SLOT_W + (col // BLOCK) * BLOCK_GAP

# ── Contrôleur MIDI (AKAI APC mini…) ─────────────────────────────────────────
# Les 9 faders pilotent les canaux 1-9 de l'univers affiché. La grille de pads
# prend un motif propre au testeur, impossible à confondre avec le show : fond
# orange tamisé, et chaque colonne devient un vu-mètre cyan du fader en dessous
# (les boutons de droite font le vu-mètre du 9e fader).
# Shift (bouton TAP) ou ▶ dans l'en-tête passe à la page de 9 canaux
# suivante ; le MUTE du fader 8 ou ◀ la précédente.
# 512 canaux → 57 pages.
MIDI_FADERS   = 9
MIDI_MUTE_PREV = 7    # index 0-based : MUTE du fader 8
MIDI_PAGES    = (512 + MIDI_FADERS - 1) // MIDI_FADERS
LED_TEST_BG   = 9     # orange (palette APC mini mk2)
LED_TEST_BAR  = 37    # cyan — la couleur du testeur


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

        self.setFixedSize(_col_x(COLS - 1) + FADER_W, ROWS * SLOT_H)
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
        blk, rx = divmod(pos.x(), BLOCK_W)
        in_blk  = rx // SLOT_W
        col = blk * BLOCK + in_blk if in_blk < BLOCK else -1   # -1 : entre deux blocs
        row = pos.y() // SLOT_H
        if 0 <= col < COLS and 0 <= row < ROWS:
            ch = row * COLS + col
            y_in_slot = pos.y() - row * SLOT_H - 4
            if 0 <= y_in_slot < FADER_H:
                # 3 px de butée en haut et en bas : 0 et 255 s'attrapent sans viser
                t   = 1.0 - (y_in_slot - 3) / (FADER_H - 6)
                val = max(0, min(255, int(round(t * 255))))
                return ch, val
            return ch, None   # clic dans la zone étiquette
        return -1, None

    # ── Rendu ────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(BG))

        f_num = QFont("Segoe UI"); f_num.setPixelSize(9)
        f_val = QFont("Segoe UI"); f_val.setPixelSize(8); f_val.setBold(True)
        accent = QColor(ACCENT)

        for i in range(512):
            col = i % COLS
            row = i // COLS
            x   = _col_x(col)
            y   = row * SLOT_H + 4
            val = self._values[i]
            sel = i in self._selected
            hov = i == self._hovered
            body = QRectF(x + 0.5, y + 0.5, FADER_W - 1, FADER_H - 1)

            # ── Fond du fader ──────────────────────────────
            p.setPen(QPen(QColor("#3a404a") if hov and not sel else QColor(LINE), 1))
            p.setBrush(QColor(RAISED) if hov and not sel else QColor(SURFACE))
            p.drawRoundedRect(body, 3, 3)

            # ── Remplissage (de bas en haut) ───────────────
            t      = val / 255.0
            inner  = FADER_H - 4
            fill_h = int(round(t * inner))
            fill_y = y + 2 + inner - fill_h

            if val > 0:
                grad = QLinearGradient(0, fill_y, 0, y + FADER_H - 2)
                grad.setColorAt(0.0, QColor(0, 212, 255, int(110 + t * 120)))
                grad.setColorAt(1.0, QColor(0, 90, 140, int(60 + t * 80)))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(grad))
                p.drawRoundedRect(QRectF(x + 2, fill_y, FADER_W - 4, fill_h), 2, 2)
                # Trait lumineux en haut du remplissage : le niveau se lit d'un coup d'œil
                p.fillRect(QRectF(x + 2, fill_y, FADER_W - 4, 1.5), QColor(190, 245, 255))
                # Valeur numérique au-dessus du niveau (ou dedans s'il est en haut)
                p.setFont(f_val)
                p.setPen(QColor(TEXT) if fill_y - y > 14 else QColor("#06222b"))
                ty = fill_y - 12 if fill_y - y > 14 else fill_y + 1
                p.drawText(QRect(x, int(ty), FADER_W, 11), Qt.AlignCenter, str(val))
            else:
                # Rainure discrète quand le canal est à 0
                p.fillRect(QRectF(x + FADER_W / 2 - 1, y + 6, 2, FADER_H - 12), QColor("#23272e"))

            # ── Sélection ──────────────────────────────────
            # Pas de cadre : un voile cyan + le numéro en cyan suffisent
            if sel:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 212, 255, 30))
                p.drawRoundedRect(body, 3, 3)

            # ── Numéro de canal ────────────────────────────
            p.setFont(f_num)
            if sel:
                p.setPen(accent)
            elif val > 0:
                p.setPen(QColor(TEXT))
            else:
                p.setPen(QColor(FAINT))
            p.drawText(
                QRect(x - 2, y + FADER_H + 1, FADER_W + 4, LABEL_H),
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

    def wheelEvent(self, e):
        """Molette au-dessus d'un fader : ±5 par cran (Ctrl : ±1).
        Si le fader survolé fait partie de la sélection, toute la sélection suit.
        Ailleurs (numéros, espaces entre blocs) la molette fait défiler la grille."""
        ch, val = self._pos_to_ch_val(e.position().toPoint())
        if ch < 0 or val is None:
            e.ignore()
            return
        # Touchpad : petits deltas cumulés jusqu'à un cran complet (120)
        self._wheel_acc = getattr(self, '_wheel_acc', 0) + e.angleDelta().y()
        notches = int(self._wheel_acc / 120)
        if notches == 0:
            e.accept()
            return
        self._wheel_acc -= notches * 120
        step = 1 if e.modifiers() & Qt.ControlModifier else 5
        if ch not in self._selected:
            self._selected = {ch}
            self._last = ch
            self.selection_changed.emit(self.selected())
        for c in sorted(self._selected):
            v = max(0, min(255, self._values[c] + notches * step))
            self._values[c] = v
            self.value_changed.emit(c, v)
        self.update()
        e.accept()

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

    def __init__(self, dmx, parent=None, midi=None):
        super().__init__(parent)
        self._dmx      = dmx
        self._midi     = midi
        self._midi_page = 0
        self._uni      = 0
        self._snapshot = [list(dmx.dmx_data[u][:512]) for u in range(4)]
        self._group    = 0
        for u in range(4):
            for i in range(512):
                dmx.dmx_data[u][i] = 0
        dmx.send_dmx()  # envoie immédiatement l'état zéro

        # Timer 25 Hz : envoie DMX régulièrement sans surcharger le réseau
        self._tx_timer = QTimer(self)
        self._tx_timer.timeout.connect(self._dmx.send_dmx)
        self._tx_timer.start(40)

        self.setWindowTitle(tr("dt_title"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(f"""
            QDialog   {{ background: {BG}; }}
            QLabel    {{ color: {MUTED}; background: transparent; border: none; }}
            #hdr      {{ background: {SURFACE}; border-bottom: 1px solid {LINE}; }}
            #ctrl     {{ background: {SURFACE}; border-top: 1px solid {LINE}; }}
            #foot     {{ background: {BG}; border-top: 1px solid {LINE}; }}
            #panel    {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 8px; }}
            #faders   {{ background: {BG}; }}
            #sep      {{ background: {LINE}; border: none; max-height: 1px; min-height: 1px; }}
            #section  {{ color: {ACCENT}; font-size: 10px; font-weight: bold; letter-spacing: 1.5px; }}
            #pill     {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 11px;
                         padding: 3px 12px; color: {MUTED}; }}
            QSpinBox  {{
                background: {RAISED}; color: {ACCENT};
                border: 1px solid {LINE}; border-radius: 6px;
                padding: 0 8px;
            }}
            QSpinBox:focus {{ border-color: {ACCENT}; }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: transparent; border: none; width: 18px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {LINE}; }}
            QScrollArea {{ border: none; background: {BG}; }}
            QScrollBar:vertical {{
                background: transparent; width: 10px; margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: #2c313a; border-radius: 3px; min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{ background: #3d4450; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
            QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; }}
        """)
        self._build_ui()
        self._refresh_grid()
        self._midi_attach()

    # ── Contrôleur MIDI ──────────────────────────────────────────────────────

    def _midi_attach(self):
        if self._midi is None or not getattr(self._midi, 'midi_in', None):
            self._midi = None
            return
        self._midi.fader_changed.connect(self._on_midi_fader)
        # Le bouton TAP/Shift ne fait plus de tap tempo sur le show tant que
        # le testeur est ouvert : il tourne les pages de faders.
        self._midi.tap_override = lambda: self._set_midi_page(self._midi_page + 1)
        # Les MUTE ne coupent plus les groupes du show ; celui du fader 8, voisin
        # de Shift, recule d'une page.
        self._midi.mute_override = self._on_midi_mute
        self._set_mute_leds(on=True)
        self.midi_bar.setVisible(True)
        self._set_midi_page(0)

    def _midi_detach(self):
        if self._midi is None:
            return
        try:
            self._midi.fader_changed.disconnect(self._on_midi_fader)
        except (RuntimeError, TypeError):
            pass
        self._midi.tap_override = None
        self._midi.mute_override = None
        self._set_mute_leds(on=False)
        self._midi = None

    def _on_midi_mute(self, idx):
        if idx == MIDI_MUTE_PREV:
            self._set_midi_page(self._midi_page - 1)

    def _set_mute_leds(self, on):
        """APC mini : seul le MUTE « page précédente » est allumé pendant le test."""
        out = getattr(self._midi, 'midi_out', None)
        if not out or self._midi.controller_type != 'apc_mini':
            return
        try:
            for i in range(8):
                out.send_message([0x90, 100 + i, 3 if on and i == MIDI_MUTE_PREV else 0])
        except Exception:
            pass

    def _midi_page_channels(self):
        start = self._midi_page * MIDI_FADERS
        return list(range(start, min(start + MIDI_FADERS, 512)))

    def _set_midi_page(self, page):
        """Change la page des faders (boucle) : label, sélection, vu-mètres."""
        if self._midi is None:
            return
        self._midi_page = page % MIDI_PAGES
        chs = self._midi_page_channels()
        self.lbl_midi.setText(
            f"<span style='color:{ACCENT}'>🎛</span>&nbsp; "
            f"{tr('dt_midi_hint', a=f'<b>{chs[0] + 1}</b>', b=f'<b>{chs[-1] + 1}</b>')}"
            f"&nbsp;&nbsp;<span style='color:{FAINT}'>{self._midi_page + 1}/{MIDI_PAGES}</span>")
        self._select_and_scroll(chs)
        data = self._dmx.dmx_data[self._uni]
        for col in range(MIDI_FADERS):
            v = data[chs[col]] if col < len(chs) else 0
            self._paint_midi_column(col, round(v * 127 / 255))

    def _on_midi_fader(self, idx, value):
        if not 0 <= idx < MIDI_FADERS:
            return
        ch = self._midi_page * MIDI_FADERS + idx
        if ch >= 512:
            return   # dernière page : 8 canaux seulement, le 9e fader est libre
        val = round(value * 255 / 127)
        self._dmx.dmx_data[self._uni][ch] = val
        self.grid.set_channel(ch, val)
        self._paint_midi_column(idx, value)
        self.lbl_status.setText(tr("dt_channel_val", a0=ch + 1, val=val))
        self._tint_status(ACCENT)
        if ch in self.grid.selected():
            self._set_slider(val)

    def _paint_midi_column(self, col, value):
        """Vu-mètre d'un fader sur sa colonne de pads (rangée 7 = bas)."""
        lit = round(value * 8 / 127)
        for row in range(8):
            on = (7 - row) < lit
            if col == 8:
                # Boutons de droite : une seule couleur, allumé / éteint
                self._midi.set_pad_led(row, col, 1 if on else 0)
            else:
                self._midi.set_pad_led(row, col, LED_TEST_BAR if on else LED_TEST_BG,
                                       brightness_percent=100 if on else 20)

    # ── Construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────
        hdr = QWidget(objectName="hdr")
        hdr.setAttribute(Qt.WA_StyledBackground, True)
        hdr.setFixedHeight(58)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(12)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background:{ACCENT}; border-radius:5px;")
        hl.addWidget(dot)

        titles = QVBoxLayout(); titles.setSpacing(0)
        t = QLabel(tr("dt_header"))
        t.setFont(QFont("Segoe UI", 13, QFont.Bold))
        t.setStyleSheet(f"color:{TEXT};")
        titles.addWidget(t)
        sub = QLabel(tr("dt_subtitle"))
        sub.setFont(QFont("Segoe UI", 8))
        sub.setStyleSheet(f"color:{FAINT};")
        titles.addWidget(sub)
        hl.addLayout(titles)
        hl.addSpacing(16)

        # Sélecteur de page des faders du contrôleur : ◀ [canaux a–b · n/57] ▶
        self.midi_bar = QWidget()
        mb = QHBoxLayout(self.midi_bar)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(4)
        btn_prev_page = QPushButton("◀")
        btn_prev_page.setFixedSize(30, 30)
        btn_prev_page.setStyleSheet(self._nav_btn_style())
        btn_prev_page.setToolTip(tr("dt_midi_prev_tip"))
        btn_prev_page.clicked.connect(lambda: self._set_midi_page(self._midi_page - 1))
        mb.addWidget(btn_prev_page)
        self.lbl_midi = QLabel()
        self.lbl_midi.setFont(QFont("Segoe UI", 9))
        self.lbl_midi.setFixedHeight(30)
        self.lbl_midi.setAlignment(Qt.AlignCenter)
        self.lbl_midi.setStyleSheet(
            f"color:{TEXT}; background:{BG}; border:1px solid {_rgba(ACCENT, 0.35)};"
            f"border-radius:6px; padding:0 12px;"
        )
        self.lbl_midi.setToolTip(tr("dt_midi_page_tip"))
        mb.addWidget(self.lbl_midi)
        btn_next_page = QPushButton("▶")
        btn_next_page.setFixedSize(30, 30)
        btn_next_page.setStyleSheet(self._nav_btn_style())
        btn_next_page.setToolTip(tr("dt_midi_next_tip"))
        btn_next_page.clicked.connect(lambda: self._set_midi_page(self._midi_page + 1))
        mb.addWidget(btn_next_page)
        self.midi_bar.setVisible(False)
        hl.addWidget(self.midi_bar, 0, Qt.AlignVCenter)
        hl.addStretch()
        self.lbl_status = QLabel(tr("dt2_drag_hint"), objectName="pill")
        self.lbl_status.setFont(QFont("Segoe UI", 9))
        self.lbl_status.setFixedHeight(26)
        hl.addWidget(self.lbl_status, 0, Qt.AlignVCenter)
        root.addWidget(hdr)

        # ── Corps : faders (scroll) + panneau droit ────────
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(18, 16, 18, 16)
        bl.setSpacing(18)

        # ScrollArea contenant les faders
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.viewport().setObjectName("faders")

        self.grid = DmxFaderView()
        self.grid.selection_changed.connect(self._on_selection_changed)
        self.grid.value_changed.connect(self._on_fader_drag)
        scroll.setWidget(self.grid)
        scroll.setFixedWidth(self.grid.width() + 14)  # +14 pour la scrollbar
        scroll.setFixedHeight(VISIBLE_ROWS * SLOT_H)
        bl.addWidget(scroll)
        self.grid.setFocus()

        bl.addWidget(self._build_right_panel())
        root.addWidget(body)

        # ── Barre canal sélectionné ────────────────────────
        ctrl = QWidget(objectName="ctrl")
        ctrl.setAttribute(Qt.WA_StyledBackground, True)
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(20, 12, 20, 12)
        cl.setSpacing(14)

        self.lbl_sel_info = QLabel(tr("dt2_no_channel"))
        self.lbl_sel_info.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_sel_info.setStyleSheet(f"color:{FAINT}; min-width:240px;")
        cl.addWidget(self.lbl_sel_info)

        cl.addWidget(self._small_lbl(tr("dmt3_068")))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 255)
        self.slider.setValue(255)
        self.slider.setEnabled(False)
        self.slider.setFixedHeight(22)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background:{LINE}; height:6px; border-radius:3px;
            }}
            QSlider::sub-page:horizontal {{ background:{ACCENT}; border-radius:3px; }}
            QSlider::handle:horizontal {{
                background:{TEXT}; width:12px; height:12px;
                margin:-5px 0; border-radius:8px; border:2px solid {ACCENT};
            }}
            QSlider::sub-page:horizontal:disabled {{ background:#2c313a; }}
            QSlider::handle:horizontal:disabled {{ background:#2c313a; border-color:#2c313a; }}
        """)
        cl.addWidget(self.slider, 1)

        self.lbl_val = QLabel("—")
        self.lbl_val.setFixedSize(56, 30)
        self.lbl_val.setAlignment(Qt.AlignCenter)
        self.lbl_val.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_val.setStyleSheet(
            f"color:{ACCENT}; background:{RAISED}; border:1px solid {LINE}; border-radius:6px;"
        )
        cl.addWidget(self.lbl_val)

        self.slider.valueChanged.connect(self._apply_slider)
        root.addWidget(ctrl)

        # ── Footer ────────────────────────────────────────
        foot = QWidget(objectName="foot")
        foot.setAttribute(Qt.WA_StyledBackground, True)
        foot.setFixedHeight(58)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 0, 20, 0)
        fl.setSpacing(10)

        self.btn_on  = self._btn("●  Full ON",  GREEN)
        self.btn_off = self._btn("○  Full OFF", RED)
        self.btn_on.setToolTip(tr("dt2_all_up"))
        self.btn_off.setToolTip(tr("dt2_all_down"))
        self.btn_on.clicked.connect(lambda: self._send_val(255))
        self.btn_off.clicked.connect(lambda: self._send_val(0))
        fl.addWidget(self.btn_on)
        fl.addWidget(self.btn_off)
        fl.addStretch()

        btn_close = QPushButton(tr("dmt3_069"))
        btn_close.setFixedHeight(34)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#04161c;border:none;"
            f"border-radius:6px;font-size:11px;font-weight:bold;padding:0 22px;}}"
            f"QPushButton:hover{{background:#3fe0ff;}}"
        )
        btn_close.clicked.connect(self.close)
        fl.addWidget(btn_close)
        root.addWidget(foot)

    def _build_right_panel(self):
        w = QWidget(objectName="panel")
        w.setAttribute(Qt.WA_StyledBackground, True)
        w.setFixedWidth(256)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        lay.addWidget(QLabel(tr("dt_wizard"), objectName="section"))
        lay.addWidget(self._small_lbl(tr("dt_chan_per_group")))

        self.spin_group = QSpinBox()
        self.spin_group.setRange(1, 50)
        self.spin_group.setValue(5)
        self.spin_group.setFixedHeight(36)
        self.spin_group.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.spin_group.valueChanged.connect(lambda: setattr(self, '_group', 0) or self._update_assistant())
        lay.addWidget(self.spin_group)

        nav = QHBoxLayout(); nav.setSpacing(6)
        self.btn_prev_grp = QPushButton("◀")
        self.btn_prev_grp.setFixedSize(34, 34)
        self.btn_prev_grp.setStyleSheet(self._nav_btn_style())
        self.btn_prev_grp.clicked.connect(self._prev_group)
        nav.addWidget(self.btn_prev_grp)

        self.lbl_group_range = QLabel("1 → 5")
        self.lbl_group_range.setAlignment(Qt.AlignCenter)
        self.lbl_group_range.setFixedHeight(34)
        self.lbl_group_range.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_group_range.setStyleSheet(
            f"color:{TEXT}; background:{BG}; border:1px solid {LINE}; border-radius:6px;"
        )
        nav.addWidget(self.lbl_group_range, 1)

        self.btn_next_grp = QPushButton("▶")
        self.btn_next_grp.setFixedSize(34, 34)
        self.btn_next_grp.setStyleSheet(self._nav_btn_style())
        self.btn_next_grp.clicked.connect(self._next_group)
        nav.addWidget(self.btn_next_grp)
        lay.addLayout(nav)
        lay.addSpacing(4)

        self.btn_send_grp = self._action_btn(tr("dt2_send_100"), GREEN)
        self.btn_send_grp.clicked.connect(self._send_group)
        lay.addWidget(self.btn_send_grp)

        btn_send_next = self._action_btn(tr("dt2_send_next"), ACCENT)
        btn_send_next.clicked.connect(self._send_group_and_advance)
        lay.addWidget(btn_send_next)

        btn_cut_next = self._action_btn(tr("dt2_send_only"), RED)
        btn_cut_next.clicked.connect(self._cut_and_send_next)
        lay.addWidget(btn_cut_next)

        lay.addSpacing(6)
        lay.addWidget(QFrame(objectName="sep"))
        lay.addSpacing(6)

        lay.addWidget(QLabel(tr("dt_universe").upper(), objectName="section"))

        uni_row = QHBoxLayout(); uni_row.setSpacing(6)
        self._uni_btns = []
        for u in range(4):
            b = QPushButton(str(u + 1))
            b.setFixedHeight(34)
            b.setCheckable(True)
            b.setChecked(u == 0)
            b.setCursor(Qt.PointingHandCursor)
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
        # Pas de send_dmx() ici — le timer 25 Hz gère l'envoi sans surcharger
        n = len(self.grid.selected())
        txt = tr("dmt3_072", a=ch+1) if n <= 1 else tr("dmt3_073", n=n)
        self.lbl_sel_info.setText(f"{txt}  —  {val} / 255")
        self.lbl_sel_info.setStyleSheet("color:#00d4ff; min-width:240px;")
        self._set_slider(val)
        self.slider.setEnabled(True)
        self.lbl_val.setText(str(val))

    def _on_selection_changed(self, sel):
        n = len(sel)
        if n == 0:
            self.lbl_sel_info.setText(tr("dt2_no_channel"))
            self.lbl_sel_info.setStyleSheet("color:#5a6069; min-width:240px;")
            self.lbl_val.setText("—")
            self.slider.setEnabled(False)
        elif n == 1:
            ch  = sel[0]
            val = self._dmx.dmx_data[self._uni][ch]
            self.lbl_sel_info.setText(tr("dt_channel_val", a0=ch + 1, val=val))
            self.lbl_sel_info.setStyleSheet("color:#00d4ff; min-width:240px;")
            self._set_slider(val)
            self.slider.setEnabled(True)
        else:
            self.lbl_sel_info.setText(tr("dt_n_channels", n=n))
            self.lbl_sel_info.setStyleSheet("color:#00d4ff; min-width:240px;")
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
        txt = tr("dmt3_072", a=sel[0]+1) if n == 1 else tr("dmt3_073", n=n)
        self.lbl_sel_info.setText(f"{txt}  —  {val} / 255")
        self.lbl_sel_info.setStyleSheet("color:#00d4ff; min-width:240px;")

    def _send_val(self, val):
        # Full ON / Full OFF agissent TOUJOURS sur les 512 canaux de l'univers,
        # independamment du fader eventuellement selectionne.
        targets = list(range(512))
        for ch in targets:
            self._dmx.dmx_data[self._uni][ch] = val
        self._dmx.send_dmx()
        color = GREEN if val == 255 else RED
        label = "Full ON" if val == 255 else "Full OFF"
        self.lbl_status.setText(tr("dt_univ_full", label=label, val=val))
        self._tint_status(color)
        self._refresh_grid()

    def _restore(self):
        for u in range(4):
            for i, v in enumerate(self._snapshot[u]):
                self._dmx.dmx_data[u][i] = v
        self._dmx.send_dmx()
        self.lbl_status.setText(tr("dt2_show_restored"))
        self._tint_status(GREEN)
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
        self._select_and_scroll(self._group_channels())

    def _select_and_scroll(self, chs):
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
            self.lbl_status.setText(tr("dt_n_channels_sel", a0=len(sel)))
            self._tint_status(None)

    def done(self, result):
        # done() et non closeEvent() : Échap ferme le dialogue par reject()
        # sans passer par closeEvent, et laissait le testeur sur la sortie.
        self._midi_detach()
        self._restore()
        super().done(result)

    def _small_lbl(self, text):
        l = QLabel(text)
        l.setFont(QFont("Segoe UI", 9))
        l.setStyleSheet(f"color:{MUTED};")
        return l

    def _tint_status(self, color):
        """Pastille d'état du header : teintée de la couleur du message (None = neutre)."""
        if color is None:
            self.lbl_status.setStyleSheet("")
            return
        self.lbl_status.setStyleSheet(
            f"color:{color}; background:{_rgba(color, 0.08)}; border-color:{_rgba(color, 0.35)};"
        )

    def _btn(self, text, fg):
        b = QPushButton(text)
        b.setFixedHeight(34)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{_rgba(fg, 0.10)};color:{fg};border:1px solid {_rgba(fg, 0.35)};"
            f"border-radius:6px;font-size:11px;font-weight:bold;padding:0 16px;}}"
            f"QPushButton:hover{{background:{_rgba(fg, 0.18)};border-color:{fg};}}"
            f"QPushButton:pressed{{background:{_rgba(fg, 0.28)};}}"
        )
        return b

    def _action_btn(self, text, fg):
        b = self._btn(text, fg)
        b.setStyleSheet(b.styleSheet().replace("padding:0 16px", "padding:0 10px;text-align:left")
                             .replace("font-size:11px", "font-size:10px"))
        return b

    def _switch_universe(self, idx):
        self._uni = idx
        for i, b in enumerate(self._uni_btns):
            b.setChecked(i == idx)
            b.setStyleSheet(self._uni_btn_style(i == idx))
        self.grid.set_selection([])
        self._refresh_grid()
        self.lbl_status.setText(tr("dt_univ_active", a0=idx + 1))
        self._tint_status(ACCENT)

    def _uni_btn_style(self, active):
        if active:
            return (f"QPushButton{{background:{_rgba(ACCENT, 0.14)};color:{ACCENT};"
                    f"border:1px solid {ACCENT};border-radius:6px;font-weight:bold;font-size:12px;}}"
                    f"QPushButton:hover{{background:{_rgba(ACCENT, 0.22)};}}")
        return (f"QPushButton{{background:{RAISED};color:{MUTED};"
                f"border:1px solid {LINE};border-radius:6px;font-size:12px;}}"
                f"QPushButton:hover{{color:{TEXT};border-color:#3a404a;}}")

    def _nav_btn_style(self):
        return (
            f"QPushButton{{background:{RAISED};color:{MUTED};border:1px solid {LINE};"
            f"border-radius:6px;font-size:12px;}}"
            f"QPushButton:hover{{color:{TEXT};border-color:#3a404a;}}"
            f"QPushButton:disabled{{color:#2c313a;border-color:{LINE};background:{SURFACE};}}"
        )
