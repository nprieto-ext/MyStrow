"""
ext_window.py — Fenêtre EXT : surface d'exécuteurs configurable (façon grandMA).

MVP étape 2 :
  - Coquille (étape 1) : fenêtre externe + banques à gauche + grille magnétique
    + bascule Édition / Live.
  - Palette de blocs par banque (colonne gauche). Clic sur un item = ajoute le bloc
    sur la surface (placé sur la 1re cellule libre de la grille).
  - Les blocs déclenchent une ACTION RÉELLE en mode Live :
      • Couleur → MainWindow._apply_color_shortcut(QColor)
      • Strobe  → MainWindow._apply_strobe_shortcut()
      • Position / MEM → stubs « à venir » (branchés aux étapes suivantes).
  - Clic droit sur un bloc = le supprimer.

Étapes suivantes (non incluses) :
  - Étape 3 : drag + resize des blocs sur la grille (poignées, déplacement).
  - Étape 4 : sauvegarde/chargement du layout (JSON, façon .tui).
"""
import os
import json
from copy import deepcopy

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QButtonGroup, QScrollArea, QMenu,
    QDialog, QRadioButton, QCheckBox, QDialogButtonBox, QMessageBox, QFileDialog,
    QSpinBox, QDoubleSpinBox,
)
from i18n import tr
from PySide6.QtCore import Qt, QTimer, QPoint, QMimeData
from PySide6.QtGui import QPainter, QColor, QPen, QDrag, QFont


# Banques de la colonne de gauche (comme la colonne du REC Lumière)
EXT_CATEGORIES = [
    ("color",     "🎨  Couleur"),
    ("select",    "◉  Sélection"),
    ("position",  "🎯  Position"),
    ("mem",       "💾  MEM"),
    ("effects",   "✨  Effets"),
    ("special",   "⭐  Spécial"),
]

# Catalogue de blocs STATIQUES (banques fixes).
# Position et MEM sont générées dynamiquement depuis les presets de l'app
# (voir ExtWindow._position_specs / _mem_specs).
BLOCK_LIBRARY = {
    "color": [
        {"label": "ROUGE",   "color": "#ff3030", "action": {"type": "color", "rgb": [255,   0,   0], "groups": "all"}},
        {"label": "VERT",    "color": "#30ff30", "action": {"type": "color", "rgb": [0,   255,   0], "groups": "all"}},
        {"label": "BLEU",    "color": "#3060ff", "action": {"type": "color", "rgb": [0,    60, 255], "groups": "all"}},
        {"label": "CYAN",    "color": "#30ffff", "action": {"type": "color", "rgb": [0,   255, 255], "groups": "all"}},
        {"label": "MAGENTA", "color": "#ff30ff", "action": {"type": "color", "rgb": [255,   0, 255], "groups": "all"}},
        {"label": "JAUNE",   "color": "#ffff30", "action": {"type": "color", "rgb": [255, 255,   0], "groups": "all"}},
        {"label": "ORANGE",  "color": "#ffaa20", "action": {"type": "color", "rgb": [255, 110,   0], "groups": "all"}},
        {"label": "BLANC",   "color": "#ffffff", "action": {"type": "color", "rgb": [255, 255, 255], "groups": "all"}},
        {"label": "BLACK LIGHT", "color": "#6400ff", "action": {"type": "color", "rgb": [100, 0, 255], "groups": "all"}},
    ],
    "effects": [
        {"label": "Strobe", "color": "#ffffff", "action": {"type": "strobe"}},
    ],
    "transport": [
        {"label": "PLAY",      "color": "#4CAF50", "action": {"type": "play"}},
        {"label": "NEXT",      "color": "#00d4ff", "action": {"type": "next"}},
        {"label": "GO",        "color": "#4CAF50", "action": {"type": "go_next"}},
        {"label": "GO −",      "color": "#4CAF50", "action": {"type": "go_prev"}},
        {"label": "TAP TEMPO", "color": "#33c0ff", "action": {"type": "tap_tempo"}},
    ],
    "master": [
        {"label": "MASTER +",     "color": "#00d4ff", "action": {"type": "master_nudge", "delta":  10}},
        {"label": "MASTER −",     "color": "#00d4ff", "action": {"type": "master_nudge", "delta": -10}},
        {"label": "Fader Master", "color": "#00d4ff", "span_r": 3, "action": {"type": "fader", "groups": "master"}},
    ],
    "system": [
        {"label": "REC",         "color": "#cc3333", "action": {"type": "rec_mem"}},
        {"label": "Sélec. Tout", "color": "#00d4ff", "action": {"type": "select_all"}},
        {"label": "Désélec.",    "color": "#5a6470", "action": {"type": "clear_sel"}},
        {"label": "CLEAR",       "color": "#22ccaa", "action": {"type": "clear"}},
        {"label": "Stop Effets", "color": "#ff8800", "action": {"type": "stop_fx"}},
        {"label": "BLACKOUT",    "color": "#ff4444", "action": {"type": "blackout"}},
        {"label": "Coupe DMX",   "color": "#ff5555", "action": {"type": "dmx_cut"}},
        {"label": "Coupe Vidéo", "color": "#cc66ff", "action": {"type": "video_toggle"}},
    ],
    "display": [
        {"label": "Horloge", "color": "#888888", "span_c": 3, "action": {"type": "clock"}},
        {"label": "Slot",    "color": "#00d4ff", "span_c": 2, "action": {"type": "cartouche", "index": 0}},
    ],
}

# Banques statiques hors couleurs/effets : regroupées dans la banque « Spécial »
# de la palette et utilisées telles quelles par le layout par défaut.
_STATIC_BANKS = ("transport", "master", "system", "display")

# Couleur d'accent des blocs effet selon leur catégorie (fenêtre EXT)
_EFFECT_CAT_COLOR = {
    "Strobe / Flash": "#ffffff",
    "Mouvement":      "#33c0ff",
    "Ambiance":       "#ffaa33",
    "Couleur":        "#ff5fae",
    "Permut":         "#b070ff",
    "Lyre":           "#5ad17f",
    "Spécial":        "#ff6644",
    "Personnalisés":  "#c8a020",
    "Mes Effets":     "#c8a020",
}

GRID_CELL = 64   # taille d'une cellule de la grille magnétique (px)
_LEFT_COL_W = 170  # largeur de la colonne palette (masquée en mode Live)
_CELL_MARGIN = 4 # marge interne d'un bloc dans sa/ses cellule(s)
_HANDLE = 18     # taille de la zone de poignée de resize (coin bas-droit, px)
_MIME = "application/x-mystrow-extblock"   # format drag&drop palette → grille


# ──────────────────────────────────────────────────────────────────────
class ExtBlock(QPushButton):
    """Bloc-exécuteur posé sur la grille.

    - Mode Live   : un clic déclenche l'action.
    - Mode Édition : glisser le corps = déplacer ; glisser la poignée
      (coin bas-droit) = redimensionner. Aimantation à la grille au relâché.
    """

    def __init__(self, spec: dict, canvas: "GridCanvas"):
        super().__init__(canvas)
        self.spec = spec
        self.canvas = canvas
        self.col = self.row = 0
        self.span_c = self.span_r = 1
        self.active = False          # True = bloc « allumé » (latché)
        self._flashing = False       # True pendant un appui en mode flash
        self._mode = None            # None | "move" | "resize"
        self._press_pos = QPoint()
        self._orig_geo = None
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor if canvas.edit_mode else Qt.PointingHandCursor)
        self._apply_style()
        self._refresh_caption()

    def _set_active(self, on: bool):
        """Allume/éteint l'état latché du bloc."""
        on = bool(on)
        if getattr(self, "active", False) != on:
            self.active = on
            self._apply_style()
            self.update()

    def _refresh_caption(self):
        """Texte + infobulle du bloc ; la cible des couleurs est mise sur la ligne du dessous."""
        label = self.spec.get("label", "?")
        act = self.spec.get("action", {})
        target, tip = None, None
        if act.get("type") == "color":
            label = label.upper()
            g = act.get("groups", "all")   # défaut = tous les groupes
            if g == "selection":
                target, tip = "Sél.", "Couleur → projecteurs sélectionnés"
            elif g == "all":
                target, tip = "Tous", "Couleur → tous les groupes"
            elif g:
                disp = getattr(self.canvas, "group_display", {}) or {}
                letters = ",".join(disp.get(x, x) for x in g)
                target, tip = letters, f"Couleur → groupes : {letters}"
        elif act.get("type") == "effect":
            g = act.get("groups", "all")
            if g and g != "all":
                disp = getattr(self.canvas, "group_display", {}) or {}
                letters = ",".join(disp.get(x, x) for x in g)
                target, tip = letters, f"Effet → groupes : {letters}"
        elif act.get("type") == "master_nudge":
            step = abs(int(act.get("delta", 0)))
            fade = float(act.get("fade", 0) or 0)
            target = f"{step}%" + (f" · {fade:g}s" if fade else "")
        # Le texte est peint par paintEvent (avec retour à la ligne, sans troncature)
        self._caption = f"{label}\n{target}" if target else label
        self.setText("")

    def _apply_style(self):
        accent = self.spec.get("color", "#0077bb")
        if getattr(self, "active", False):
            # Bloc allumé : rempli de sa couleur + liseré blanc.
            # Texte blanc, sauf sur les couleurs claires (blanc, jaune, cyan…)
            # où il passe en noir pour rester lisible.
            c = QColor(accent)
            lum = c.red() * 0.299 + c.green() * 0.587 + c.blue() * 0.114
            txt = "#000" if lum > 185 else "#fff"
            self.setStyleSheet(
                f"QPushButton {{ background:{accent}; color:{txt}; border:3px solid #ffffff; "
                f"border-radius:8px; font-size:10px; font-weight:bold; }}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{ background:#1b1b1b; color:#eee; border:2px solid {accent}; "
                f"border-radius:8px; font-size:10px; font-weight:bold; }} "
                f"QPushButton:hover {{ background:#262626; }} "
                f"QPushButton:pressed {{ background:{accent}; color:#000; }}"
            )

    def place(self, col: int, row: int):
        self.col, self.row = col, row
        g, m = GRID_CELL, _CELL_MARGIN
        self.setGeometry(col * g + m, row * g + m,
                         self.span_c * g - 2 * m, self.span_r * g - 2 * m)

    def _on_handle(self, pos) -> bool:
        return (pos.x() >= self.width() - _HANDLE and
                pos.y() >= self.height() - _HANDLE)

    # ── Souris ──────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.canvas.edit_mode:
            self._press_pos = ev.globalPosition().toPoint()
            self._orig_geo = self.geometry()
            self._mode = "resize" if self._on_handle(ev.position()) else "move"
            self.raise_()
            ev.accept()
            return
        self._mode = None
        # Live + mode flash : l'action démarre à l'appui (momentané)
        if (not self.canvas.edit_mode and ev.button() == Qt.LeftButton
                and self.spec.get("flash")):
            self._flashing = True
            if getattr(self.canvas, "flash_on_cb", None):
                self.canvas.flash_on_cb(self.spec.get("action", {}), self)
            super().mousePressEvent(ev)
            return
        super().mousePressEvent(ev)   # Live : visuel pressed normal

    def mouseMoveEvent(self, ev):
        if self._mode == "move":
            delta = ev.globalPosition().toPoint() - self._press_pos
            ng = self._orig_geo.translated(delta)
            self.move(max(0, ng.x()), max(0, ng.y()))
            ev.accept()
            return
        if self._mode == "resize":
            delta = ev.globalPosition().toPoint() - self._press_pos
            g, m = GRID_CELL, _CELL_MARGIN
            self.resize(max(g - 2 * m, self._orig_geo.width() + delta.x()),
                        max(g - 2 * m, self._orig_geo.height() + delta.y()))
            ev.accept()
            return
        # Survol : curseur adapté
        if self.canvas.edit_mode:
            self.setCursor(Qt.SizeFDiagCursor if self._on_handle(ev.position())
                           else Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.PointingHandCursor)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._mode in ("move", "resize"):
            was_resize = (self._mode == "resize")
            self._mode = None
            self._snap_to_grid(resize=was_resize)
            ev.accept()
            return
        # Live + mode flash : l'action s'arrête au relâché
        if self._flashing:
            self._flashing = False
            super().mouseReleaseEvent(ev)
            if getattr(self.canvas, "flash_off_cb", None):
                self.canvas.flash_off_cb(self.spec.get("action", {}), self)
            return
        inside = self.rect().contains(ev.position().toPoint())
        super().mouseReleaseEvent(ev)
        # Live : un clic relâché dans le bloc déclenche l'action
        if (not self.canvas.edit_mode and ev.button() == Qt.LeftButton
                and inside and self.canvas.activate_cb):
            self.canvas.activate_cb(self.spec.get("action", {}), self)

    def _snap_to_grid(self, resize: bool):
        g, m = GRID_CELL, _CELL_MARGIN
        geo = self.geometry()
        col = max(0, round((geo.x() - m) / g))
        row = max(0, round((geo.y() - m) / g))
        if resize:
            span_c = max(1, round((geo.width() + 2 * m) / g))
            span_r = max(1, round((geo.height() + 2 * m) / g))
        else:
            span_c, span_r = self.span_c, self.span_r
        # Bornage horizontal sur le nombre de colonnes
        cols = self.canvas._cols()
        span_c = min(span_c, cols)
        col = min(col, max(0, cols - span_c))
        # Aimantation seulement si la zone est libre, sinon retour à l'ancienne place
        if self.canvas._cells_free(col, row, span_c, span_r, exclude=self):
            self.col, self.row, self.span_c, self.span_r = col, row, span_c, span_r
        self.place(self.col, self.row)
        self.canvas._changed()

    def paintEvent(self, ev):
        super().paintEvent(ev)   # fond / bordure / hover / pressed (texte vide)
        p = QPainter(self)
        accent = QColor(self.spec.get("color", "#0077bb"))
        w, h = self.width(), self.height()
        # Légende peinte à la main : retour à la ligne, jamais tronquée
        caption = getattr(self, "_caption", "")
        if caption:
            if getattr(self, "active", False):
                lum = accent.red() * 0.299 + accent.green() * 0.587 + accent.blue() * 0.114
                p.setPen(QColor("#000") if lum > 185 else QColor("#fff"))
            else:
                p.setPen(QColor("#eee"))
            f = QFont(); f.setBold(True)
            f.setPixelSize(9 if h >= 44 else 8)
            p.setFont(f)
            flags = int(Qt.AlignCenter | Qt.TextWordWrap)
            p.drawText(self.rect().adjusted(3, 2, -3, -2), flags, caption)
        # Poignée de resize (3 traits en coin) visible en mode Édition
        if self.canvas.edit_mode:
            pen = QPen(accent); pen.setWidth(2); p.setPen(pen)
            for off in (5, 9, 13):
                p.drawLine(w - off, h - 3, w - 3, h - off)
        p.end()

    def contextMenuEvent(self, ev):
        menu = QMenu(self)
        atype = self.spec.get("action", {}).get("type")
        act_edit = act_flash = act_settings = act_cues = None
        slot_acts = {}
        if atype in ("color", "effect", "fader"):
            act_edit = menu.addAction(tr("ext_edit_groups"))
        if atype == "master_nudge":
            act_settings = menu.addAction(tr("ext_settings"))
        if atype == "mem":
            act_cues = menu.addAction(tr("ext_manage_cues"))
        if atype in ("cartouche", "slot"):
            cur_idx = int(self.spec.get("action", {}).get("index", 0))
            sub = menu.addMenu(tr("ext_link_slot"))
            for i in range(4):
                a = sub.addAction(f"Slot {i + 1}")
                a.setCheckable(True)
                a.setChecked(i == cur_idx)
                slot_acts[a] = i
        if atype in ("effect", "strobe", "color"):
            act_flash = menu.addAction(tr("ext_flash_mode"))
            act_flash.setCheckable(True)
            act_flash.setChecked(bool(self.spec.get("flash")))
        if menu.actions():
            menu.addSeparator()
        act_del = menu.addAction(tr("ext_del_block"))
        chosen = menu.exec(ev.globalPos())
        if chosen is None:
            return
        if act_edit is not None and chosen == act_edit and self.canvas.edit_cb:
            self.canvas.edit_cb(self)
        elif act_settings is not None and chosen == act_settings and self.canvas.settings_cb:
            self.canvas.settings_cb(self)
        elif act_cues is not None and chosen == act_cues and self.canvas.cue_cb:
            self.canvas.cue_cb(self)
        elif chosen in slot_acts:
            self.spec.setdefault("action", {})["index"] = slot_acts[chosen]
            self.update()
            self.canvas._changed()
        elif act_flash is not None and chosen == act_flash:
            self.spec["flash"] = not self.spec.get("flash")
            self.canvas._changed()
        elif chosen == act_del:
            self.canvas.remove_block(self)


# ──────────────────────────────────────────────────────────────────────
class ExtFaderBlock(ExtBlock):
    """Bloc-tirette : en Live, glisser verticalement règle un niveau (0-100 %).

    Réutilise toute la machinerie d'ExtBlock en Édition (déplacer / redimensionner
    / menu contextuel / sérialisation) ; seul le comportement Live et le rendu
    sont personnalisés.
    """

    def __init__(self, spec: dict, canvas: "GridCanvas"):
        self.value = int(spec.get("value", spec.get("action", {}).get("value", 100)))
        self._adjusting = False
        self._target_txt = ""
        super().__init__(spec, canvas)

    def _refresh_caption(self):
        act = self.spec.get("action", {})
        g = act.get("groups", "master")
        if g in ("master", "all", None):
            self._target_txt = "MASTER"
        else:
            disp = getattr(self.canvas, "group_display", {}) or {}
            self._target_txt = ",".join(disp.get(x, x) for x in g)
        self.setText("")   # tout est peint dans paintEvent

    def _apply_style(self):
        self.setStyleSheet("QPushButton { border:none; background:transparent; }")

    def _value_from_y(self, y) -> int:
        h = max(1, self.height())
        return int(max(0, min(100, round((1 - y / h) * 100))))

    def _set_value(self, v: int, apply: bool = True):
        v = int(max(0, min(100, v)))
        if v != self.value:
            self.value = v
            self.update()
        if apply and getattr(self.canvas, "fader_cb", None):
            self.canvas.fader_cb(self.spec.get("action", {}), self.value)

    # ── Souris (Live : glisser = régler ; Édition : hérité d'ExtBlock) ──
    def mousePressEvent(self, ev):
        if not self.canvas.edit_mode and ev.button() == Qt.LeftButton:
            self._adjusting = True
            self._set_value(self._value_from_y(ev.position().y()))
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._adjusting:
            self._set_value(self._value_from_y(ev.position().y()))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._adjusting:
            self._adjusting = False
            ev.accept()
            self.canvas._changed()   # persiste la valeur réglée
            return
        super().mouseReleaseEvent(ev)

    def paintEvent(self, ev):
        p = QPainter(self)
        accent = QColor(self.spec.get("color", "#00d4ff"))
        w, h = self.width(), self.height()
        # fond + remplissage bas → haut selon la valeur
        p.fillRect(0, 0, w, h, QColor("#141414"))
        fill_h = int(h * self.value / 100)
        p.fillRect(0, h - fill_h, w, fill_h,
                   QColor(accent.red(), accent.green(), accent.blue(), 110))
        pen = QPen(accent); pen.setWidth(2); p.setPen(pen)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 8, 8)
        # textes : cible en haut, pourcentage en bas
        p.setPen(QColor("#eee"))
        f = QFont(); f.setPointSize(7); f.setBold(True); p.setFont(f)
        p.drawText(self.rect().adjusted(2, 4, -2, 0),
                   Qt.AlignTop | Qt.AlignHCenter, self._target_txt)
        p.drawText(self.rect().adjusted(2, 0, -2, -4),
                   Qt.AlignBottom | Qt.AlignHCenter, f"{self.value}%")
        # poignée de resize en Édition
        if self.canvas.edit_mode:
            for off in (5, 9, 13):
                p.drawLine(w - off, h - 3, w - 3, h - off)
        p.end()


# ──────────────────────────────────────────────────────────────────────
class ExtClockBlock(ExtBlock):
    """Bloc horloge digitale : affiche l'heure courante (HH:MM:SS), rafraîchie
    chaque seconde. Déplaçable / redimensionnable comme les autres blocs ;
    un clic en Live ne déclenche aucune action."""

    def __init__(self, spec: dict, canvas: "GridCanvas"):
        super().__init__(spec, canvas)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self.update)
        self._clock_timer.start()

    def _apply_style(self):
        self.setStyleSheet("QPushButton { border:none; background:transparent; }")

    def _refresh_caption(self):
        self.setText("")   # tout est peint dans paintEvent

    def paintEvent(self, ev):
        import datetime
        p = QPainter(self)
        accent = QColor(self.spec.get("color", "#00d4ff"))
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#0d0d0d"))
        pen = QPen(accent); pen.setWidth(2); p.setPen(pen)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 8, 8)
        now = datetime.datetime.now().strftime("%H:%M:%S")
        p.setPen(QColor("#f0f0f0"))
        f = QFont("Consolas"); f.setBold(True)
        f.setPixelSize(max(11, int(min(h * 0.5, w / 5.2))))
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, now)
        if self.canvas.edit_mode:
            pen2 = QPen(accent); pen2.setWidth(2); p.setPen(pen2)
            for off in (5, 9, 13):
                p.drawLine(w - off, h - 3, w - 3, h - off)
        p.end()


# ──────────────────────────────────────────────────────────────────────
class ExtSlotBlock(ExtBlock):
    """Slot lié à une cartouche (média) de la page principale : joue / arrête
    la cartouche N ; affiche son titre ; s'allume pendant la lecture."""

    def __init__(self, spec: dict, canvas: "GridCanvas"):
        self._slot_title = ""
        super().__init__(spec, canvas)

    def _apply_style(self):
        self.setStyleSheet("QPushButton { border:none; background:transparent; }")

    def _refresh_caption(self):
        self.setText("")

    def _slot_index(self) -> int:
        return int(self.spec.get("action", {}).get("index", 0))

    def paintEvent(self, ev):
        p = QPainter(self)
        accent = QColor(self.spec.get("color", "#00d4ff"))
        w, h = self.width(), self.height()
        active = bool(getattr(self, "active", False))
        if active:
            p.fillRect(0, 0, w, h,
                       QColor(accent.red(), accent.green(), accent.blue(), 45))
        else:
            p.fillRect(0, 0, w, h, QColor("#141414"))
        pen = QPen(accent); pen.setWidth(2 if active else 1); p.setPen(pen)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 8, 8)
        # Numéro de slot en haut à gauche
        p.setPen(QColor(accent.red(), accent.green(), accent.blue(), 200))
        fn = QFont(); fn.setBold(True); fn.setPixelSize(8); p.setFont(fn)
        p.drawText(self.rect().adjusted(6, 3, -4, 0),
                   Qt.AlignTop | Qt.AlignLeft, f"◈ {self._slot_index() + 1}")
        # Titre (média chargé) ou libellé par défaut
        title = self._slot_title or f"SLOT {self._slot_index() + 1}"
        p.setPen(QColor("#f0f0f0") if active else QColor("#cccccc"))
        ft = QFont(); ft.setBold(True)
        ft.setPixelSize(max(8, min(h // 3, 11))); p.setFont(ft)
        p.drawText(self.rect().adjusted(4, 10, -4, -4),
                   Qt.AlignCenter | Qt.TextWordWrap, title)
        if self.canvas.edit_mode:
            pen2 = QPen(accent); pen2.setWidth(2); p.setPen(pen2)
            for off in (5, 9, 13):
                p.drawLine(w - off, h - 3, w - 3, h - off)
        p.end()


# ──────────────────────────────────────────────────────────────────────
class GridCanvas(QWidget):
    """Surface magnétique : héberge les blocs, les aligne sur la grille.

    En mode Édition la grille est dessinée ; en Live elle disparaît.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.edit_mode = True
        self.blocks: list[ExtBlock] = []
        self.activate_cb = None     # callback(action_dict) défini par ExtWindow
        self.edit_cb = None         # callback(block) pour éditer la cible d'un bloc
        self.settings_cb = None     # callback(block) pour régler un bloc (master ±)
        self.cue_cb = None          # callback(block) pour gérer les cues d'une mémoire
        self.fader_cb = None        # callback(action, value) pour les blocs-faders
        self.flash_on_cb = None     # callback(action, block) appui en mode flash
        self.flash_off_cb = None    # callback(action, block) relâché en mode flash
        self.group_display = {}     # {groupe interne: lettre} pour les suffixes
        self.on_changed = None      # callback() après mutation (pour auto-save)
        self._loading = False       # True pendant le chargement (pas d'auto-save)
        self.setStyleSheet("background:#0e0e0e;")
        self.setAcceptDrops(True)

    def _changed(self):
        if not self._loading and self.on_changed:
            self.on_changed()

    # — grille —
    def set_edit_mode(self, on: bool):
        self.edit_mode = bool(on)
        for b in self.blocks:
            b.setCursor(Qt.OpenHandCursor if self.edit_mode else Qt.PointingHandCursor)
            b.update()
        self.update()

    def content_size(self) -> tuple:
        """Encombrement réel des blocs en px (largeur, hauteur).

        Les blocs sont positionnés en absolu sur la grille : si le canvas est
        plus étroit que ça, ceux de droite deviennent inatteignables. Sert à
        dimensionner la zone défilante quand la surface est embarquée au centre.
        """
        w = h = 0
        for b in self.blocks:
            w = max(w, b.x() + b.width())
            h = max(h, b.y() + b.height())
        return w + _CELL_MARGIN, h + _CELL_MARGIN

    def _cols(self) -> int:
        return max(1, self.width() // GRID_CELL)

    def _occupied(self) -> set:
        occ = set()
        for b in self.blocks:
            for c in range(b.col, b.col + b.span_c):
                for r in range(b.row, b.row + b.span_r):
                    occ.add((c, r))
        return occ

    def _next_free_cell(self) -> tuple:
        occ = self._occupied()
        cols = self._cols()
        r = 0
        while True:
            for c in range(cols):
                if (c, r) not in occ:
                    return c, r
            r += 1

    def _cells_free(self, col, row, span_c, span_r, exclude=None) -> bool:
        """True si le rectangle de cellules n'empiète sur aucun autre bloc."""
        occ = set()
        for b in self.blocks:
            if b is exclude:
                continue
            for c in range(b.col, b.col + b.span_c):
                for r in range(b.row, b.row + b.span_r):
                    occ.add((c, r))
        for c in range(col, col + span_c):
            for r in range(row, row + span_r):
                if (c, r) in occ:
                    return False
        return True

    # — blocs —
    def new_block(self, spec: dict) -> ExtBlock:
        """Instancie le bon type de bloc selon l'action ; applique les spans du spec."""
        atype = spec.get("action", {}).get("type")
        cls = {"fader": ExtFaderBlock, "clock": ExtClockBlock,
               "cartouche": ExtSlotBlock, "slot": ExtSlotBlock}.get(atype, ExtBlock)
        blk = cls(deepcopy(spec), self)
        blk.span_c = max(1, int(spec.get("span_c", 1)))
        blk.span_r = max(1, int(spec.get("span_r", 1)))
        return blk

    def add_block(self, spec: dict) -> ExtBlock:
        blk = self.new_block(spec)
        c, r = self._next_free_cell()
        blk.place(c, r)
        blk.show()
        self.blocks.append(blk)
        self._changed()
        return blk

    def add_block_at(self, spec: dict, col: int, row: int) -> ExtBlock:
        """Ajoute un bloc à la cellule visée (drop) ; si occupée, 1re cellule libre."""
        cols = self._cols()
        col = max(0, min(col, cols - 1))
        row = max(0, row)
        if not self._cells_free(col, row, 1, 1):
            col, row = self._next_free_cell()
        blk = self.new_block(spec)
        blk.place(col, row)
        blk.show()
        self.blocks.append(blk)
        self._changed()
        return blk

    # — drag & drop depuis la palette de gauche —
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(_MIME):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(_MIME):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        if not ev.mimeData().hasFormat(_MIME):
            return
        try:
            spec = json.loads(bytes(ev.mimeData().data(_MIME)).decode("utf-8"))
        except Exception:
            return
        pos = ev.position().toPoint()
        self.add_block_at(spec, pos.x() // GRID_CELL, pos.y() // GRID_CELL)
        ev.acceptProposedAction()

    def remove_block(self, blk: ExtBlock):
        if blk in self.blocks:
            self.blocks.remove(blk)
            blk.setParent(None)
            blk.deleteLater()
            self._changed()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self.edit_mode:
            return
        p = QPainter(self)
        pen = QPen(QColor("#1d1d1d"))
        pen.setWidth(1)
        p.setPen(pen)
        w, h = self.width(), self.height()
        x = 0
        while x < w:
            p.drawLine(x, 0, x, h)
            x += GRID_CELL
        y = 0
        while y < h:
            p.drawLine(0, y, w, y)
            y += GRID_CELL
        p.end()


# ──────────────────────────────────────────────────────────────────────
class _PaletteItem(QPushButton):
    """Item de la palette de gauche : cliquable (ajout auto) ET glissable vers la grille."""

    def __init__(self, spec: dict, text: str, parent=None):
        super().__init__(text, parent)
        self.spec = spec
        self._press = None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._press = ev.position().toPoint()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if (self._press is not None and (ev.buttons() & Qt.LeftButton)
                and (ev.position().toPoint() - self._press).manhattanLength() > 8):
            self._start_drag()
            return
        super().mouseMoveEvent(ev)

    def _start_drag(self):
        self._press = None
        md = QMimeData()
        md.setData(_MIME, json.dumps(self.spec).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(md)
        pm = self.grab()
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        drag.exec(Qt.CopyAction)


# ──────────────────────────────────────────────────────────────────────
class ExtWindow(QMainWindow):
    """Fenêtre EXT — surface d'exécuteurs configurable façon grandMA."""

    # Layout perso, indépendant du show (.tui), rechargé à chaque démarrage.
    LAYOUT_FILE = os.path.expanduser("~/.mystrow_ext.json")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._owner = parent          # MainWindow : pour brancher les actions réelles
        self._current_cat = "color"
        self._palette_shown = False   # la colonne palette occupe-t-elle 170 px ?
        self.setWindowTitle(tr("ext_title"))
        self.setFont(QFont("Segoe UI"))   # même police que le reste du logiciel
        self.resize(1240, 760)
        self._build_ui()
        self._load_layout()
        self._restore_geometry()
        self._restore_mode()   # ouvre en Live par défaut (ou dernier mode mémorisé)

        # Synchronise en continu l'état visuel des blocs « bascule »
        # (Play, Coupe Vidéo, mémoires, niveau du fader master).
        self._state_timer = QTimer(self)
        self._state_timer.setInterval(400)
        self._state_timer.timeout.connect(self._sync_states)
        self._state_timer.start()

    # ── Construction UI ───────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._left_col = self._build_left_column()
        root.addWidget(self._left_col)
        root.addWidget(self._build_right_zone(), 1)

        self._cat_buttons["color"].setChecked(True)
        self._on_category("color")
        self._apply_mode(False)   # défaut = Live (écrasé ensuite si un mode est mémorisé)

    def _build_left_column(self) -> QWidget:
        left = QWidget()
        left.setFixedWidth(_LEFT_COL_W)
        left.setStyleSheet("background:#161616; border-right:1px solid #2a2a2a;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 12, 8, 12)
        lv.setSpacing(6)

        lv.addWidget(self._section_label("BANQUES"))

        self._cat_group = QButtonGroup(self)
        self._cat_group.setExclusive(True)
        self._cat_buttons = {}
        for code, label in EXT_CATEGORIES:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedHeight(42)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(self._cat_btn_ss())
            b.clicked.connect(lambda _=False, c=code: self._on_category(c))
            self._cat_group.addButton(b)
            self._cat_buttons[code] = b
            lv.addWidget(b)

        lv.addSpacing(8)
        lv.addWidget(self._section_label("BLOCS"))

        # Palette scrollable (mise à jour selon la banque sélectionnée)
        self._palette_scroll = QScrollArea()
        self._palette_scroll.setWidgetResizable(True)
        self._palette_scroll.setStyleSheet(
            "QScrollArea { border:none; background:transparent; }"
        )
        host = QWidget()
        self._palette_layout = QVBoxLayout(host)
        self._palette_layout.setContentsMargins(0, 4, 0, 4)
        self._palette_layout.setSpacing(5)
        self._palette_layout.addStretch()
        self._palette_scroll.setWidget(host)
        lv.addWidget(self._palette_scroll, 1)
        return left

    def _build_right_zone(self) -> QWidget:
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet("background:#141414; border-bottom:1px solid #2a2a2a;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 4, 10, 4)

        hdr = QLabel("PADS")
        hdr.setStyleSheet("color:#888; font-size:12px; font-weight:bold;")
        bl.addWidget(hdr)
        bl.addStretch()

        self._status = QLabel("")
        self._status.setStyleSheet("color:#00d4ff; font-size:11px;")
        bl.addWidget(self._status)
        bl.addSpacing(10)

        self._lock_btn = QPushButton(tr("ext2_edit"))
        self._lock_btn.setCheckable(True)
        self._lock_btn.setChecked(True)   # démarre en Édition
        self._lock_btn.setFixedHeight(28)
        self._lock_btn.setCursor(Qt.PointingHandCursor)
        self._lock_btn.setStyleSheet(self._lock_btn_ss())
        self._lock_btn.toggled.connect(self._on_lock_toggled)
        bl.addWidget(self._lock_btn)

        # Menu ☰ : réinitialiser / tout effacer / importer / exporter
        self._menu_btn = QPushButton("☰")
        self._menu_btn.setFixedSize(28, 28)
        self._menu_btn.setCursor(Qt.PointingHandCursor)
        self._menu_btn.setStyleSheet(
            "QPushButton { background:#2a2a2a; color:#ccc; border:1px solid #3a3a3a; "
            "border-radius:5px; font-size:15px; font-weight:bold; } "
            "QPushButton:hover { background:#333; color:#fff; border-color:#0077bb; } "
            "QPushButton::menu-indicator { image:none; width:0; }"
        )
        self._menu_btn.clicked.connect(self._show_surface_menu)
        bl.addSpacing(6)
        bl.addWidget(self._menu_btn)
        rv.addWidget(bar)

        self.canvas = GridCanvas()
        self.canvas.activate_cb = self._dispatch_action
        self.canvas.edit_cb = self._edit_block_groups
        self.canvas.settings_cb = self._edit_master_settings
        self.canvas.cue_cb = self._edit_mem_cues
        self.canvas.fader_cb = self._dispatch_fader
        self.canvas.flash_on_cb = self._dispatch_flash_on
        self.canvas.flash_off_cb = self._dispatch_flash_off
        self.canvas.group_display = getattr(self._owner, "GROUP_DISPLAY", {}) or {}
        self.canvas.on_changed = self._save_layout
        rv.addWidget(self.canvas, 1)
        return right

    # ── Callbacks ──────────────────────────────────────────────────────
    def _on_category(self, code: str):
        self._current_cat = code
        # Vider la palette (sauf le stretch final)
        while self._palette_layout.count() > 1:
            item = self._palette_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        # Reconstruire les items de la banque
        specs = self._specs_for(code)
        if specs:
            for i, spec in enumerate(specs):
                self._palette_layout.insertWidget(i, self._make_palette_item(spec))
        else:
            info = QLabel(self._empty_hint(code))
            info.setWordWrap(True)
            info.setAlignment(Qt.AlignCenter)
            info.setStyleSheet("color:#555; font-size:10px; padding:8px;")
            self._palette_layout.insertWidget(0, info)

    def _specs_for(self, code: str) -> list:
        """Retourne les specs de blocs d'une banque (statiques ou dynamiques)."""
        if code == "effects":
            return self._effect_specs()
        if code == "select":
            return self._select_specs()
        if code == "special":
            specs = []
            for bank in _STATIC_BANKS:
                specs.extend(BLOCK_LIBRARY.get(bank, []))
            return specs
        if code in BLOCK_LIBRARY:
            return BLOCK_LIBRARY[code]
        if code == "position":
            return self._position_specs()
        if code == "mem":
            return self._mem_specs()
        return []

    def _select_specs(self) -> list:
        """Blocs de sélection rapide : Tout / Désélec. + un bloc par groupe présent
        + les groupes de sélection personnalisés (comme le menu SELEC du plan de feu)."""
        owner = self._owner
        pdf = getattr(owner, "plan_de_feu", None)
        specs = [
            {"label": "Tout",     "color": "#00d4ff", "action": {"type": "select_all"}},
            {"label": "Désélec.", "color": "#5a6470", "action": {"type": "clear_sel"}},
        ]
        if pdf is None:
            return specs
        present = {p.group for p in getattr(owner, "projectors", []) or []}
        label_map = getattr(pdf, "_GROUP_LABEL", {}) or {}
        seen = set()
        for internal, label in label_map.items():
            if internal in present:
                specs.append({"label": label, "color": "#33c0ff",
                              "action": {"type": "select_group", "group": internal}})
                seen.add(internal)
        for g in sorted(present - seen):
            specs.append({"label": g.capitalize(), "color": "#33c0ff",
                          "action": {"type": "select_group", "group": g}})
        for gname in (getattr(pdf, "_custom_groups", {}) or {}):
            specs.append({"label": f"★ {gname}", "color": "#c8a020",
                          "action": {"type": "select_custom", "name": gname}})
        return specs

    def _effect_specs(self) -> list:
        """Bloc 'Strobe' rapide + un bloc par effet de la bibliothèque
        (intégrés + personnalisés), comme dans l'éditeur d'effets."""
        specs = list(BLOCK_LIBRARY.get("effects", []))
        seen = {s.get("label") for s in specs}
        try:
            from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
            effects = list(BUILTIN_EFFECTS) + _load_custom_effects()
        except Exception:
            effects = []
        for eff in effects:
            name = eff.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            specs.append({
                "label": name,
                "color": _EFFECT_CAT_COLOR.get(eff.get("category", ""), "#c8a020"),
                "action": {"type": "effect", "name": name},
            })
        return specs

    def _position_specs(self) -> list:
        """Un bloc par position lyre enregistrée (position_pads → position_presets)."""
        owner = self._owner
        pads = getattr(owner, "position_pads", None)
        presets = getattr(owner, "position_presets", None)
        if not pads or presets is None:
            return []
        out = []
        for c, column in enumerate(pads):
            for r, idx in enumerate(column):
                if idx is None or idx >= len(presets):
                    continue
                name = presets[idx].get("name") or f"POS {c + 1}.{r + 1}"
                out.append({
                    "label": name, "color": "#33c0ff",
                    "action": {"type": "position", "col": c, "row": r},
                })
        return out

    def _mem_specs(self) -> list:
        """Un bloc par mémoire enregistrée (self.memories[col][row] non vide)."""
        owner = self._owner
        mems = getattr(owner, "memories", None)
        if not mems:
            return []
        out = []
        for c, column in enumerate(mems):
            for r, mem in enumerate(column):
                if not mem:
                    continue
                name = (mem.get("name") if isinstance(mem, dict) else "") or ""
                out.append({
                    "label": name if name else f"MEM {c + 1}.{r + 1}", "color": "#c080ff",
                    "action": {"type": "mem", "col": c, "row": r},
                })
        return out

    @staticmethod
    def _empty_hint(code: str) -> str:
        if code == "position":
            return "Aucune position enregistrée.\nConfigure-les via les pads POS."
        if code == "mem":
            return "Aucune mémoire enregistrée.\nEnregistre via le bouton 🔴."
        return "Aucun bloc."

    def _make_palette_item(self, spec: dict) -> QPushButton:
        accent = spec.get("color", "#0077bb")
        b = _PaletteItem(spec, "➕  " + spec.get("label", "?"))
        b.setFixedHeight(34)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ background:#1a1a1a; color:#ddd; border:1px solid #2e2e2e; "
            f"border-left:4px solid {accent}; border-radius:4px; font-size:11px; "
            f"text-align:left; padding-left:8px; }} "
            f"QPushButton:hover {{ background:#252525; color:#fff; }}"
        )
        b.clicked.connect(lambda _=False, s=spec: self.canvas.add_block(s))
        return b

    def _set_palette(self, visible: bool):
        """Affiche/masque la colonne palette en compensant la largeur de la
        fenêtre, pour que la surface de pads garde la même largeur utile dans
        les deux modes (sinon les pads de droite sortiraient du cadre)."""
        visible = bool(visible)
        self._left_col.setVisible(visible)
        if visible == self._palette_shown:
            return
        self._palette_shown = visible
        if self.isMaximized() or self.isFullScreen():
            return   # fenêtre plein cadre : impossible d'élargir, on ne touche à rien
        delta = _LEFT_COL_W if visible else -_LEFT_COL_W
        self.resize(max(600, self.width() + delta), self.height())

    def _on_lock_toggled(self, edit_on: bool):
        self._lock_btn.setText(tr("ext2_edit") if edit_on else "🔒  Live")
        self.canvas.set_edit_mode(edit_on)
        self._set_palette(edit_on)   # palette masquée en Live, largeur compensée

    def _apply_mode(self, edit_on: bool):
        """Applique un mode (Édition/Live) sans déclencher le signal toggled."""
        self._lock_btn.blockSignals(True)
        self._lock_btn.setChecked(edit_on)
        self._lock_btn.blockSignals(False)
        self._lock_btn.setText(tr("ext2_edit") if edit_on else "🔒  Live")
        self.canvas.set_edit_mode(edit_on)
        self._set_palette(edit_on)   # palette masquée en Live, largeur compensée

    def _dispatch_action(self, action: dict, block: "ExtBlock" = None):
        """Exécute l'action d'un bloc via la MainWindow."""
        owner = self._owner
        t = (action or {}).get("type")
        if owner is None:
            return

        # Strobe nécessite toujours une sélection de projecteurs
        if t == "strobe":
            pdf = getattr(owner, "plan_de_feu", None)
            if not getattr(pdf, "selected_lamps", None):
                self._flash_status("⚠ Sélectionnez des projecteurs d'abord")
                return

        if t == "color":
            r, g, b = action.get("rgb", [255, 255, 255])
            groups = action.get("groups", "all")   # défaut = tous les groupes
            if groups == "selection":
                pdf = getattr(owner, "plan_de_feu", None)
                if not getattr(pdf, "selected_lamps", None):
                    self._flash_status("⚠ Sélectionnez des projecteurs d'abord")
                    return
                owner._apply_color_shortcut(QColor(r, g, b))
                self._flash_status("Couleur → sélection")
            else:
                n = owner._apply_color_to_groups(QColor(r, g, b), groups)
                cible = "tous les groupes" if groups == "all" else "groupes ciblés"
                self._flash_status(f"Couleur → {cible} ({n} proj.)")
            self._latch_color(block)          # le bloc couleur reste allumé
        elif t == "strobe":
            owner._apply_strobe_shortcut()
            self._flash_status("Strobe basculé")
        elif t == "position":
            owner._recall_position_akai(action.get("col", 0), action.get("row", 0))
            self._sync_pos_latches()
            self._flash_status("Position rappelée")
        elif t == "mem":
            # Passe par trigger_memory (point d'entrée externe) : gère les
            # mémoires multi-cue (ré-appui = cue suivant), comme les pads AKAI.
            owner.trigger_memory(action.get("col", 0), action.get("row", 0))
            self._sync_mem_latches()
            self._flash_status("Mémoire rappelée")
        elif t == "effect":
            name = action.get("name", "")
            res = owner._toggle_ext_effect(name, action.get("groups"))
            if res is None:
                self._flash_status(f"⚠ Effet « {name} » introuvable")
            else:
                self._flash_status(f"Effet {'ON' if res else 'OFF'} : {name}")
                if res:
                    self._latch_effect(block)
                elif block is not None:
                    block._set_active(False)
        elif t == "select_all":
            n = owner._ext_select_all()
            self._flash_status(f"{n} projecteur(s) sélectionné(s)")
        elif t == "clear_sel":
            owner._ext_clear_selection()
            self._flash_status("Sélection vidée")
        elif t == "select_group":
            pdf = getattr(owner, "plan_de_feu", None)
            if pdf is not None and hasattr(pdf, "_select_group"):
                pdf._select_group(action.get("group"))
            n = len(getattr(pdf, "selected_lamps", None) or [])
            self._flash_status(f"{n} projecteur(s) sélectionné(s)")
        elif t == "select_custom":
            pdf = getattr(owner, "plan_de_feu", None)
            members = (getattr(pdf, "_custom_groups", {}) or {}).get(action.get("name")) \
                if pdf is not None else None
            if pdf is not None and members and hasattr(pdf, "_select_custom_group"):
                pdf._select_custom_group(members)
            n = len(getattr(pdf, "selected_lamps", None) or [])
            self._flash_status(f"★ {action.get('name')} — {n} proj.")
        elif t == "clear":
            owner._ext_clear()
            self._flash_status("Clear")
            self._clear_color_latches()
        elif t == "full":
            n = owner._ext_full_on()
            self._flash_status(f"Plein feu ({n} proj.)")
            self._clear_color_latches()       # les pastilles couleur ne reflètent plus l'état
        elif t == "blackout":
            owner._ext_blackout()
            self._flash_status("Blackout")
            self._clear_all_latches()
        elif t == "stop_fx":
            owner._ext_stop_effects()
            self._flash_status("Effets arrêtés")
            self._clear_effect_latches()
        elif t == "play":
            owner.toggle_play()
            self._flash_status("Play / Pause")
        elif t == "next":
            owner.next_media()
            self._flash_status("Média suivant")
        elif t == "video_toggle":
            state = owner._ext_toggle_video()
            self._flash_status("Vidéo " + ("ON" if state else "OFF")
                               if state is not None else "Vidéo indisponible")
        elif t == "dmx_cut":
            state = owner._ext_cut_dmx()
            self._flash_status(("DMX " + ("ON" if state else "coupé"))
                               if state is not None else "DMX indisponible")
        elif t == "rec_mem":
            owner._toggle_mem_rec_mode()
            on = bool(getattr(owner, "_mem_rec_mode", False))
            self._flash_status("REC " + ("armé — clique une mémoire" if on else "désactivé"))
        elif t == "tap_tempo":
            owner._tap_tempo()
            self._flash_status("Tap tempo")
        elif t == "go_next":
            owner._go_advance()
            self._flash_status("GO ▶")
        elif t == "go_prev":
            owner._go_back()
            self._flash_status("GO ◀")
        elif t == "master_nudge":
            cur = getattr(owner, "master_level", 100)
            new = max(0, min(100, cur + int(action.get("delta", 0))))
            fade = float(action.get("fade", 0) or 0)
            self._animate_master(new, fade)
            self._flash_status(f"Master {new}%" + (f" ({fade:g}s)" if fade else ""))
        elif t in ("cartouche", "slot"):
            idx = int(action.get("index", 0))
            if hasattr(owner, "on_cartouche_clicked"):
                owner.on_cartouche_clicked(idx)
            self._flash_status(f"Slot {idx + 1}")
        elif t in ("fader", "clock"):
            pass   # fader = glissé (ExtFaderBlock) ; clock = affichage seul
        else:
            self._flash_status(f"« {action.get('what', t)} » — à venir")

    def _dispatch_fader(self, action: dict, value: int):
        """Applique la valeur d'un bloc-fader (Master ou groupes)."""
        owner = self._owner
        if owner is None:
            return
        groups = (action or {}).get("groups", "master")
        if groups in ("master", "all", None):
            owner.set_master_level(0, value)
        else:
            owner._ext_set_group_level(groups, value)

    # ── Fondu du master (blocs MASTER ± avec temps de fade) ────────────
    def _animate_master(self, target: int, duration_s: float):
        """Amène le master à `target` (%) sur `duration_s` secondes (0 = immédiat)."""
        import time
        owner = self._owner
        if owner is None:
            return
        start = float(getattr(owner, "master_level", 100))
        target = float(max(0, min(100, target)))
        if duration_s <= 0 or abs(target - start) < 0.5:
            owner.set_master_level(0, int(round(target)))
            self._refresh_master_faders()
            return
        self._master_from = start
        self._master_to = target
        self._master_dur = duration_s
        self._master_t0 = time.monotonic()
        if getattr(self, "_master_timer", None) is None:
            self._master_timer = QTimer(self)
            self._master_timer.setInterval(25)   # ~40 fps
            self._master_timer.timeout.connect(self._master_tick)
        self._master_timer.start()

    def _master_tick(self):
        import time
        owner = self._owner
        if owner is None:
            self._master_timer.stop()
            return
        frac = (time.monotonic() - self._master_t0) / self._master_dur
        if frac >= 1.0:
            owner.set_master_level(0, int(round(self._master_to)))
            self._refresh_master_faders()
            self._master_timer.stop()
            return
        v = self._master_from + (self._master_to - self._master_from) * frac
        owner.set_master_level(0, int(round(v)))
        self._refresh_master_faders()

    def _refresh_master_faders(self):
        """Met à jour immédiatement les blocs Fader Master sur la valeur réelle."""
        master = int(getattr(self._owner, "master_level", 100))
        for b in self.canvas.blocks:
            if isinstance(b, ExtFaderBlock) \
                    and b.spec.get("action", {}).get("groups") in ("master", "all", None) \
                    and not getattr(b, "_adjusting", False) and b.value != master:
                b.value = master
                b.update()

    def _edit_mem_cues(self, blk: "ExtBlock"):
        """Ouvre l'éditeur de cues de la mémoire ciblée (ajout/gestion de cues)."""
        owner = self._owner
        act = blk.spec.get("action", {})
        opener = getattr(owner, "_open_cue_editor", None)
        if opener is None:
            self._flash_status("Éditeur de cues indisponible")
            return
        opener(act.get("col", 0), act.get("row", 0))

    def _edit_master_settings(self, blk: "ExtBlock"):
        """Dialogue de réglage d'un bloc MASTER ± : pas (%) et temps de fondu (s)."""
        act = dict(blk.spec.get("action", {}))
        cur_delta = int(act.get("delta", 10))
        sign = -1 if cur_delta < 0 else 1
        accent = blk.spec.get("color", "#00d4ff")

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ext2_master_cfg"))
        dlg.setMinimumWidth(320)
        dlg.setStyleSheet(f"""
            QDialog {{ background:#161616; }}
            QLabel#hdr {{ color:#f0f0f0; font-size:15px; font-weight:bold; }}
            QLabel {{ color:#cfcfcf; font-size:12px; }}
            QSpinBox, QDoubleSpinBox {{ background:#1e1e1e; color:#eee;
                border:1px solid #3a3a3a; border-radius:5px; padding:5px 8px;
                font-size:13px; min-height:22px; }}
            QSpinBox:focus, QDoubleSpinBox:focus {{ border-color:{accent}; }}
        """)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(8)

        hdr = QLabel(f"Master {'−' if sign < 0 else '+'}  « {blk.spec.get('label', '?')} »")
        hdr.setObjectName("hdr")
        lay.addWidget(hdr)
        lay.addWidget(QLabel(tr("ext2_master_hint")))
        lay.addSpacing(6)

        lay.addWidget(QLabel(tr("ext2_step_pct")))
        sp_step = QSpinBox()
        sp_step.setRange(1, 100)
        sp_step.setSuffix(" %")
        sp_step.setValue(abs(cur_delta) or 10)
        lay.addWidget(sp_step)

        lay.addWidget(QLabel(tr("ext_fade_time")))
        sp_fade = QDoubleSpinBox()
        sp_fade.setRange(0.0, 10.0)
        sp_fade.setSingleStep(0.5)
        sp_fade.setDecimals(1)
        sp_fade.setSuffix(" s")
        sp_fade.setValue(float(act.get("fade", 0) or 0))
        lay.addWidget(sp_fade)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("ext_confirm"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("ext_cancel"))
        bb.setStyleSheet(f"""
            QPushButton {{ background:#1e1e1e; color:#bbb; border:1px solid #333;
                border-radius:6px; padding:8px 20px; font-size:12px; }}
            QPushButton:hover {{ background:#2a2a2a; color:#fff; }}
            QPushButton:default {{ background:{accent}; color:#000; border:none;
                font-weight:bold; }}
        """)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addSpacing(8)
        lay.addWidget(bb)

        if dlg.exec() != QDialog.Accepted:
            return
        act["delta"] = sign * sp_step.value()
        act["fade"] = round(sp_fade.value(), 1)
        blk.spec["action"] = act
        blk._refresh_caption()
        self.canvas._changed()

    def _dispatch_flash_on(self, action: dict, block: "ExtBlock"):
        """Appui d'un bloc en mode flash : l'action démarre (momentané)."""
        owner = self._owner
        t = (action or {}).get("type")
        if owner is None:
            return
        if t == "strobe":
            pdf = getattr(owner, "plan_de_feu", None)
            if not getattr(pdf, "selected_lamps", None):
                self._flash_status("⚠ Sélectionnez des projecteurs d'abord")
                return
            owner._ext_set_strobe(True)
            if block is not None:
                block._set_active(True)
            self._flash_status("Flash strobe")
        elif t == "effect":
            if block is not None and not getattr(block, "active", False):
                res = owner._toggle_ext_effect(action.get("name", ""), action.get("groups"))
                if res:
                    block._set_active(True)
            self._flash_status("Flash effet")
        elif t == "color":
            groups = action.get("groups", "all")
            if groups == "selection" and not getattr(
                    getattr(owner, "plan_de_feu", None), "selected_lamps", None):
                self._flash_status("⚠ Sélectionnez des projecteurs d'abord")
                return
            r, g, b = action.get("rgb", [255, 255, 255])
            # Instantané de l'état avant flash → restauré au relâché
            block._flash_snap = owner._ext_snapshot_groups(groups)
            if groups == "selection":
                owner._apply_color_shortcut(QColor(r, g, b))
            else:
                owner._apply_color_to_groups(QColor(r, g, b), groups)
            if block is not None:
                block._set_active(True)
            self._flash_status("Flash couleur")

    def _dispatch_flash_off(self, action: dict, block: "ExtBlock"):
        """Relâché d'un bloc en mode flash : l'action s'arrête."""
        owner = self._owner
        t = (action or {}).get("type")
        if owner is None:
            return
        if t == "strobe":
            owner._ext_set_strobe(False)
            if block is not None:
                block._set_active(False)
        elif t == "effect":
            if block is not None and getattr(block, "active", False):
                owner._toggle_ext_effect(action.get("name", ""), action.get("groups"))
                block._set_active(False)
        elif t == "color":
            snap = getattr(block, "_flash_snap", None)
            if snap is not None:
                owner._ext_restore_snapshot(snap)
                block._flash_snap = None
            if block is not None:
                block._set_active(False)

    # ── Latch visuel des blocs (état « allumé ») ───────────────────────
    def _latch_color(self, block):
        """Allume le bloc couleur cliqué et éteint les autres blocs couleur."""
        for b in self.canvas.blocks:
            if b.spec.get("action", {}).get("type") == "color" and b is not block:
                b._set_active(False)
        if block is not None:
            block._set_active(True)

    def _latch_effect(self, block):
        for b in self.canvas.blocks:
            if b.spec.get("action", {}).get("type") == "effect" and b is not block:
                b._set_active(False)
        if block is not None:
            block._set_active(True)

    def _clear_color_latches(self):
        for b in self.canvas.blocks:
            if b.spec.get("action", {}).get("type") == "color":
                b._set_active(False)

    def _clear_effect_latches(self):
        for b in self.canvas.blocks:
            if b.spec.get("action", {}).get("type") == "effect":
                b._set_active(False)

    def _clear_all_latches(self):
        for b in self.canvas.blocks:
            b._set_active(False)

    def _sync_mem_latches(self):
        """Allume les blocs MEM dont la mémoire est active (état réel de l'app).
        Reflète l'exclusivité par colonne : activer une mémoire éteint la
        précédente de la même colonne."""
        owner = self._owner
        active = getattr(owner, "active_memory_pads", {}) or {}
        col_to_fader = getattr(owner, "_mem_col_to_fader", None)
        mems = getattr(owner, "memories", None) or []
        for b in self.canvas.blocks:
            act = b.spec.get("action", {})
            if act.get("type") != "mem":
                continue
            mem_col, row = act.get("col", 0), act.get("row", 0)
            try:
                fader = col_to_fader(mem_col) if col_to_fader else mem_col
                on = active.get(fader) == row
            except Exception:
                on = False
            b._set_active(on)
            # Libellé = nom perso de la mémoire si défini, sinon « MEM c.r »
            try:
                mem = mems[mem_col][row]
            except (IndexError, TypeError):
                mem = None
            name = (mem.get("name") if isinstance(mem, dict) else "") or ""
            want = name if name else f"MEM {mem_col + 1}.{row + 1}"
            if b.spec.get("label") != want:
                b.spec["label"] = want
                b._refresh_caption()
                b.update()

    def _sync_pos_latches(self):
        """Allume les blocs Position dont le preset est actif (état réel de l'app).
        Exclusivité par colonne, comme les pads position de la page principale."""
        owner = self._owner
        active = getattr(owner, "active_position_pads", {}) or {}
        for b in self.canvas.blocks:
            act = b.spec.get("action", {})
            if act.get("type") != "position":
                continue
            on = active.get(act.get("col", 0)) == act.get("row", 0)
            b._set_active(on)

    def _sync_states(self):
        """Reflète en continu l'état réel de l'app sur les blocs concernés :
        Play (lecture), Coupe Vidéo (sortie ON), mémoires, niveau master."""
        owner = self._owner
        if owner is None:
            return
        playing = bool(getattr(owner, "_ext_is_playing", lambda: False)())
        vid_btn = getattr(owner, "video_output_btn", None)
        video_on = bool(vid_btn.isChecked()) if vid_btn is not None else False
        rec_on = bool(getattr(owner, "_mem_rec_mode", False))
        pdf = getattr(owner, "plan_de_feu", None)
        dmx_off = bool(pdf is not None and hasattr(pdf, "is_dmx_enabled")
                       and not pdf.is_dmx_enabled())
        master = int(getattr(owner, "master_level", 100))
        carts = getattr(owner, "cartouches", None) or []
        playing_cart = int(getattr(owner, "cart_playing_index", -1))
        for b in self.canvas.blocks:
            t = b.spec.get("action", {}).get("type")
            if t == "play":
                b._set_active(playing)
            elif t == "video_toggle":
                b._set_active(video_on)
            elif t == "rec_mem":
                b._set_active(rec_on)
            elif t == "dmx_cut":
                b._set_active(dmx_off)   # allumé = DMX coupé
            elif t in ("cartouche", "slot"):
                idx = int(b.spec.get("action", {}).get("index", 0))
                title = carts[idx].media_title if 0 <= idx < len(carts) else None
                if getattr(b, "_slot_title", "") != (title or ""):
                    b._slot_title = title or ""
                    b.update()
                b._set_active(idx == playing_cart)
            elif t == "fader" and isinstance(b, ExtFaderBlock) \
                    and b.spec.get("action", {}).get("groups") in ("master", "all", None):
                if not getattr(b, "_adjusting", False) and b.value != master:
                    b.value = master
                    b.update()
        self._sync_mem_latches()
        self._sync_pos_latches()

    def _flash_status(self, msg: str):
        self._status.setText(msg)
        QTimer.singleShot(2200, lambda: self._status.setText(""))

    # ── Édition de la cible d'un bloc couleur ──────────────────────────
    def _available_groups(self) -> list:
        """Groupes internes possédant au moins un projecteur, dans l'ordre d'affichage."""
        owner = self._owner
        projs = getattr(owner, "projectors", None) or []
        disp = getattr(owner, "GROUP_DISPLAY", {}) or {}
        present, seen = [], set()
        for g in list(disp.keys()) + [p.group for p in projs]:
            if g not in seen and any(p.group == g for p in projs):
                present.append(g)
                seen.add(g)
        return present

    def _group_color(self, g: str):
        """Couleur représentative d'un groupe = couleur courante de ses projecteurs."""
        from PySide6.QtGui import QColor as _QC
        projs = [p for p in (getattr(self._owner, "projectors", None) or []) if p.group == g]
        for p in projs:
            c = getattr(p, "base_color", None) or getattr(p, "color", None)
            if isinstance(c, _QC) and c.isValid() and (c.red() + c.green() + c.blue()) > 0:
                return _QC(c)
        return _QC("#3a3a3a")

    def _edit_block_groups(self, blk: "ExtBlock"):
        """Dialogue : choisir la cible (tous / sélection / groupes) d'un bloc
        couleur ou effet."""
        act = dict(blk.spec.get("action", {}))
        is_color = act.get("type") == "color"
        is_fader = act.get("type") == "fader"
        cur = act.get("groups", "all")    # défaut = tous les groupes
        if is_fader and cur == "master":
            cur = "all"                   # master ↔ "tous" dans ce dialogue
        disp = getattr(self._owner, "GROUP_DISPLAY", {}) or {}

        # Groupes proposés : pour un effet, seulement ceux mappés sur une lettre A–H
        groups_avail = self._available_groups()
        if not is_color:
            groups_avail = [g for g in groups_avail
                            if len(disp.get(g, "")) == 1 and disp.get(g, "").isalpha()]

        accent = blk.spec.get("color", "#00d4ff")
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ext2_colour_target") if is_color
                           else ("Cible du fader" if is_fader else "Cible de l'effet"))
        dlg.setMinimumWidth(340)
        dlg.setStyleSheet(f"""
            QDialog {{ background:#161616; }}
            QLabel#hdr {{ color:#f0f0f0; font-size:15px; font-weight:bold; }}
            QLabel#sub {{ color:#888; font-size:11px; }}
            QRadioButton {{ color:#dcdcdc; font-size:13px; padding:7px 4px; spacing:9px; }}
            QRadioButton:hover {{ color:#ffffff; }}
            QRadioButton::indicator {{ width:16px; height:16px; }}
            QRadioButton::indicator:unchecked {{
                border:2px solid #555; border-radius:9px; background:#1b1b1b; }}
            QRadioButton::indicator:unchecked:hover {{ border-color:#999; }}
            QRadioButton::indicator:checked {{
                border:2px solid {accent}; border-radius:9px; background:{accent}; }}
        """)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(3)

        _kind = "Couleur" if is_color else ("Fader" if is_fader else "Effet")
        hdr = QLabel(((_kind)
                      + f"  « {blk.spec.get('label', '?')} »"))
        hdr.setObjectName("hdr")
        lay.addWidget(hdr)
        sub = QLabel(tr("ext2_where_colour") if is_color
                     else ("Quels projecteurs piloter ?" if is_fader
                           else "Sur quels groupes jouer l'effet ?"))
        sub.setObjectName("sub")
        lay.addWidget(sub)
        lay.addSpacing(10)

        rb_all = QRadioButton(tr("ext2_all_groups"))
        rb_sel = QRadioButton(tr("ext2_selected"))   # couleurs uniquement
        rb_grp = QRadioButton(tr("ext2_spec_groups"))
        lay.addWidget(rb_all)
        if is_color:
            lay.addWidget(rb_sel)
        lay.addWidget(rb_grp)

        # Panneau des groupes (cases colorées)
        box = QWidget()
        box.setStyleSheet("background:#1b1b1b; border-radius:8px;")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(5)
        checks = {}
        for g in groups_avail:
            tag = disp.get(g, "")
            cb = QCheckBox(f"  {tag}".rstrip() or f"  {g.capitalize()}")
            col = self._group_color(g)
            lum = col.red() * 0.299 + col.green() * 0.587 + col.blue() * 0.114
            txt = "#000" if lum > 140 else "#fff"
            cb.setStyleSheet(
                f"QCheckBox {{ background:{col.name()}; color:{txt}; border-radius:6px; "
                f"padding:8px 10px; font-weight:bold; font-size:12px; spacing:9px; }} "
                f"QCheckBox::indicator {{ width:15px; height:15px; border-radius:3px; "
                f"border:2px solid {txt}; background:transparent; }} "
                f"QCheckBox::indicator:checked {{ background:{txt}; }}"
            )
            checks[g] = cb
            bl.addWidget(cb)
        lay.addSpacing(4)
        lay.addWidget(box)

        # État initial
        if cur == "selection" and is_color:
            rb_sel.setChecked(True)
        elif cur == "all":
            rb_all.setChecked(True)
        else:
            rb_grp.setChecked(True)
            for g in (cur or []):
                if g in checks:
                    checks[g].setChecked(True)

        def _sync():
            on = rb_grp.isChecked()
            box.setEnabled(on)
            box.setStyleSheet("background:#1b1b1b; border-radius:8px;"
                              if on else "background:#181818; border-radius:8px;")
        for rb in (rb_all, rb_sel, rb_grp):
            rb.toggled.connect(_sync)
        _sync()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("ext_confirm"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("ext_cancel"))
        bb.setStyleSheet(f"""
            QPushButton {{ background:#1e1e1e; color:#bbb; border:1px solid #333;
                border-radius:6px; padding:8px 20px; font-size:12px; }}
            QPushButton:hover {{ background:#2a2a2a; color:#ffffff; }}
            QPushButton:default {{ background:{accent}; color:#000000; border:none;
                font-weight:bold; }}
        """)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addSpacing(10)
        lay.addWidget(bb)

        if dlg.exec() != QDialog.Accepted:
            return

        if is_color and rb_sel.isChecked():
            act["groups"] = "selection"
        elif rb_grp.isChecked():
            sel = [g for g, cb in checks.items() if cb.isChecked()]
            act["groups"] = sel if sel else "all"   # rien coché → tous les groupes
        else:
            act["groups"] = "all"

        blk.spec["action"] = act
        blk._refresh_caption()
        self.canvas._changed()

    # ── Persistance du layout (~/.mystrow_ext.json) ─────────────────────
    def _layout_data(self) -> dict:
        """Sérialise la disposition courante (utilisé par la sauvegarde et l'export)."""
        g = self.geometry()
        # Largeur stockée = base « Live » (hors palette). _restore_mode rajoute
        # la palette si on rouvre en Édition → pas de dérive de ±170 px.
        w_px = g.width()
        if self._palette_shown and not (self.isMaximized() or self.isFullScreen()):
            w_px -= _LEFT_COL_W
        return {
            "version": 1,
            "window": {"x": g.x(), "y": g.y(), "w": w_px, "h": g.height()},
            "edit_mode": bool(getattr(self.canvas, "edit_mode", True)),
            "blocks": [
                {
                    "label":  b.spec.get("label"),
                    "color":  b.spec.get("color"),
                    "action": b.spec.get("action"),
                    "col": b.col, "row": b.row,
                    "span_c": b.span_c, "span_r": b.span_r,
                    "flash": bool(b.spec.get("flash")),
                    **({"value": b.value} if hasattr(b, "value") else {}),
                }
                for b in self.canvas.blocks
            ],
        }

    def _restore_geometry(self):
        """Restaure la taille/position de la fenêtre depuis le fichier de layout."""
        try:
            if not os.path.exists(self.LAYOUT_FILE):
                return
            with open(self.LAYOUT_FILE, "r", encoding="utf-8") as f:
                w = (json.load(f) or {}).get("window")
            if isinstance(w, dict):
                self.setGeometry(int(w["x"]), int(w["y"]),
                                 max(600, int(w["w"])), max(400, int(w["h"])))
        except Exception:
            pass

    def _restore_mode(self):
        """Applique le mode d'ouverture : Live par défaut, ou le dernier mémorisé."""
        edit_on = False   # défaut = Live (surface verrouillée, prête à jouer)
        try:
            if os.path.exists(self.LAYOUT_FILE):
                with open(self.LAYOUT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                if isinstance(data, dict) and "edit_mode" in data:
                    edit_on = bool(data["edit_mode"])
        except Exception:
            pass
        self._apply_mode(edit_on)

    def _save_layout(self):
        try:
            with open(self.LAYOUT_FILE, "w", encoding="utf-8") as f:
                json.dump(self._layout_data(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[EXT] Échec sauvegarde layout : {e}")

    def _default_layout_blocks(self) -> list:
        """Layout de démarrage (1er lancement) : disposition personnalisée.

        Palette couleurs + effets (strobes / chases) à gauche, console
        transport/système au centre, master à droite, slots + horloge en bas.
        """
        def b(label, color, action, col, row, span_c=1, span_r=1):
            return {"label": label, "color": color, "action": action,
                    "col": col, "row": row, "span_c": span_c, "span_r": span_r}

        return [
            # ── Palette couleurs (lignes 0-1) ──
            b("ROUGE",       "#ff3030", {"type": "color", "rgb": [255,   0,   0], "groups": "all"}, 0, 0),
            b("VERT",        "#30ff30", {"type": "color", "rgb": [0,   255,   0], "groups": "all"}, 1, 0),
            b("CYAN",        "#30ffff", {"type": "color", "rgb": [0,   255, 255], "groups": "all"}, 2, 0),
            b("MAGENTA",     "#ff30ff", {"type": "color", "rgb": [255,   0, 255], "groups": "all"}, 3, 0),
            b("BLEU",        "#3060ff", {"type": "color", "rgb": [0,    60, 255], "groups": "all"}, 4, 0),
            b("JAUNE",       "#ffff30", {"type": "color", "rgb": [255, 255,   0], "groups": "all"}, 0, 1),
            b("ORANGE",      "#ffaa20", {"type": "color", "rgb": [255, 110,   0], "groups": "all"}, 1, 1),
            b("BLANC",       "#ffffff", {"type": "color", "rgb": [255, 255, 255], "groups": "all"}, 2, 1),
            b("BLACK LIGHT", "#6400ff", {"type": "color", "rgb": [100,   0, 255], "groups": "all"}, 3, 1),
            # ── Effets : strobes (ligne 3) + chases (ligne 4) ──
            b("Strobe",            "#ffffff", {"type": "strobe"}, 0, 3),
            b("Strobe Classique",  "#ffffff", {"type": "effect", "name": "Strobe Classique"}, 1, 3),
            b("Strobe Lent",       "#ffffff", {"type": "effect", "name": "Strobe Lent"}, 2, 3),
            b("Strobe Alternance", "#ffffff", {"type": "effect", "name": "Strobe Alternance"}, 3, 3),
            b("Flash Couleur",     "#ffffff", {"type": "effect", "name": "Flash Couleur"}, 4, 3),
            b("Chase Blanc",       "#33c0ff", {"type": "effect", "name": "Chase Blanc"}, 0, 4),
            b("Chase Rapide",      "#33c0ff", {"type": "effect", "name": "Chase Rapide"}, 1, 4),
            b("Chase Retour",      "#33c0ff", {"type": "effect", "name": "Chase Retour"}, 2, 4),
            b("Chase Doux",        "#33c0ff", {"type": "effect", "name": "Chase Doux"}, 3, 4),
            b("Passage Blanc",     "#33c0ff", {"type": "effect", "name": "Passage Blanc"}, 4, 4),
            # ── Console centrale : urgences / transport / système ──
            b("Coupe DMX",    "#ff5555", {"type": "dmx_cut"}, 6, 0),
            b("Coupe Vidéo",  "#cc66ff", {"type": "video_toggle"}, 7, 0),
            b("Stop Effets",  "#ff8800", {"type": "stop_fx"}, 8, 0),
            b("TAP TEMPO",    "#33c0ff", {"type": "tap_tempo"}, 6, 2, span_c=2),
            b("Strobe",       "#ffffff", {"type": "strobe"}, 8, 2),
            b("Sélec. Tout",  "#00d4ff", {"type": "select_all"}, 6, 3),
            b("Désélec.",     "#5a6470", {"type": "clear_sel"}, 7, 3),
            b("CLEAR",        "#22ccaa", {"type": "clear"}, 6, 4, span_c=2),
            b("REC",          "#cc3333", {"type": "rec_mem"}, 6, 7),
            b("PLAY",         "#4CAF50", {"type": "play"}, 6, 8),
            b("NEXT",         "#00d4ff", {"type": "next"}, 7, 8),
            b("GO −",         "#4CAF50", {"type": "go_prev"}, 6, 9),
            b("GO",           "#4CAF50", {"type": "go_next"}, 7, 9),
            # ── Master (colonnes 10-11) ──
            b("Fader Master", "#00d4ff", {"type": "fader", "groups": "master"}, 10, 0, span_c=2, span_r=6),
            b("MASTER +",     "#00d4ff", {"type": "master_nudge", "delta":  20, "fade": 0.0}, 10, 7, span_c=2),
            b("MASTER −",     "#00d4ff", {"type": "master_nudge", "delta": -20, "fade": 0.0}, 10, 8, span_c=2),
            # ── Bas de surface : blackout / slots / horloge ──
            b("BLACKOUT",     "#ff4444", {"type": "blackout"}, 0, 6, span_c=2),
            b("Slot",         "#00d4ff", {"type": "cartouche", "index": 0}, 0, 9, span_c=2),
            b("Slot",         "#00d4ff", {"type": "cartouche", "index": 1}, 2, 9, span_c=2),
            b("Horloge",      "#888888", {"type": "clock"}, 9, 9, span_c=3),
        ]

    def _load_layout(self):
        first_run = not os.path.exists(self.LAYOUT_FILE)
        if first_run:
            data = {"blocks": self._default_layout_blocks()}
        else:
            try:
                with open(self.LAYOUT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"[EXT] Échec lecture layout : {e}")
                return

        self._place_blocks(data.get("blocks", []))

        # Matérialise le layout par défaut sur disque dès le 1er lancement.
        if first_run and self.canvas.blocks:
            self._save_layout()

    def _place_blocks(self, block_dicts: list):
        """Instancie et pose sur la grille une liste de blocs sérialisés."""
        self.canvas._loading = True
        try:
            for d in block_dicts:
                spec = {
                    "label":  d.get("label", "?"),
                    "color":  d.get("color", "#0077bb"),
                    "action": d.get("action", {}),
                    "flash":  bool(d.get("flash")),
                    "span_c": max(1, int(d.get("span_c", 1))),
                    "span_r": max(1, int(d.get("span_r", 1))),
                    "value":  d.get("value", 100),
                }
                blk = self.canvas.new_block(spec)
                if hasattr(blk, "value"):
                    blk.value = int(d.get("value", blk.value))
                blk.place(int(d.get("col", 0)), int(d.get("row", 0)))
                blk.show()
                self.canvas.blocks.append(blk)
        finally:
            self.canvas._loading = False

    def reload_layout(self):
        """Vide la surface et la recharge depuis le fichier (après import de config)."""
        for blk in list(self.canvas.blocks):
            self.canvas.remove_block(blk)
        self._load_layout()
        self._flash_status("Disposition rechargée")

    def _reset_to_defaults(self):
        """Vide la surface et repose le layout par défaut (avec confirmation)."""
        resp = QMessageBox.question(
            self, tr("ext_reset_surface"),
            tr("ext_reset_surface_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        for blk in list(self.canvas.blocks):
            self.canvas.remove_block(blk)
        self._place_blocks(self._default_layout_blocks())
        self._save_layout()
        self._flash_status("Surface réinitialisée")

    def _clear_all_blocks(self):
        """Vide entièrement la surface (avec confirmation)."""
        if not self.canvas.blocks:
            self._flash_status("Surface déjà vide")
            return
        resp = QMessageBox.question(
            self, tr("ext_clear_all"),
            tr("ext_clear_all_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        for blk in list(self.canvas.blocks):
            self.canvas.remove_block(blk)
        self._save_layout()
        self._flash_status("Surface vidée")

    # ── Menu ☰ (gestion de la disposition) ─────────────────────────────
    def _show_surface_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#1c1c1c; color:#ddd; border:1px solid #333; padding:4px; }"
            "QMenu::item { padding:7px 22px; border-radius:4px; }"
            "QMenu::item:selected { background:#0c2d3a; color:#fff; }"
            "QMenu::separator { height:1px; background:#333; margin:4px 8px; }"
        )
        act_reset  = menu.addAction(tr("ext_reset_default"))
        act_clear  = menu.addAction(tr("ext_clear_all_m"))
        act_clear.setEnabled(bool(self.canvas.blocks))
        menu.addSeparator()
        act_import = menu.addAction(tr("ext_import_layout"))
        act_export = menu.addAction(tr("ext_export_layout"))
        act_export.setEnabled(bool(self.canvas.blocks))
        # Positionne le menu sous le bouton ☰
        chosen = menu.exec(self._menu_btn.mapToGlobal(
            self._menu_btn.rect().bottomLeft()))
        if chosen is act_reset:
            self._reset_to_defaults()
        elif chosen is act_clear:
            self._clear_all_blocks()
        elif chosen is act_import:
            self._import_layout()
        elif chosen is act_export:
            self._export_layout()

    def _export_layout(self):
        """Enregistre la disposition courante dans un fichier .json choisi."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter la disposition", "disposition_ext.json",
            "Disposition EXT (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._layout_data(), f, ensure_ascii=False, indent=2)
            self._flash_status("Disposition exportée")
        except Exception as e:
            QMessageBox.warning(self, tr("ext_export"), f"Échec de l'export :\n{e}")

    def _import_layout(self):
        """Remplace la surface par une disposition chargée depuis un fichier .json."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer une disposition", "",
            "Disposition EXT (*.json);;Tous les fichiers (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, tr("ext_import"), f"Fichier illisible :\n{e}")
            return
        blocks = data.get("blocks") if isinstance(data, dict) else None
        if not isinstance(blocks, list):
            QMessageBox.warning(self, tr("ext_import"),
                                tr("ext_invalid_layout"))
            return
        for blk in list(self.canvas.blocks):
            self.canvas.remove_block(blk)
        self._place_blocks(blocks)
        self._save_layout()
        self._flash_status("Disposition importée")

    def closeEvent(self, ev):
        self._save_layout()
        # Décoche le bouton EXT de la fenêtre principale (fermeture via la croix)
        btn = getattr(self._owner, "_ext_btn", None)
        if btn is not None:
            btn.setChecked(False)
        super().closeEvent(ev)

    # ── Styles ─────────────────────────────────────────────────────────
    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color:#666; font-size:10px; font-weight:bold; letter-spacing:1px;"
        )
        return lbl

    @staticmethod
    def _cat_btn_ss() -> str:
        return (
            "QPushButton { background:#1e1e1e; color:#aaa; border:1px solid #2e2e2e; "
            "border-radius:5px; font-size:12px; text-align:left; padding-left:10px; } "
            "QPushButton:hover { background:#262626; color:#fff; } "
            "QPushButton:checked { background:#0c2d3a; color:#00d4ff; "
            "border-color:#0077bb; }"
        )

    @staticmethod
    def _lock_btn_ss() -> str:
        # Live (décoché) = orange ; Édition (coché) = cyan.
        return (
            "QPushButton { background:#3a2a0c; color:#ffaa33; border:1px solid #bb7700; "
            "border-radius:5px; font-size:11px; font-weight:bold; padding:0 12px; } "
            "QPushButton:checked { background:#0c2d3a; color:#00d4ff; "
            "border-color:#0077bb; }"
        )
