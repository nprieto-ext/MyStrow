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
    QDialog, QRadioButton, QCheckBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt, QTimer, QPoint, QMimeData
from PySide6.QtGui import QPainter, QColor, QPen, QDrag, QFont


# Banques de la colonne de gauche (comme la colonne du REC Lumière)
EXT_CATEGORIES = [
    ("color",    "🎨  Couleur"),
    ("position", "🎯  Position"),
    ("mem",      "💾  MEM"),
    ("effects",  "✨  Effets"),
    ("special",  "⭐  Spécial"),
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
    ],
    "effects": [
        {"label": "Strobe", "color": "#ffffff", "action": {"type": "strobe"}},
    ],
    "special": [
        {"label": "Sélec. Tout", "color": "#00d4ff", "action": {"type": "select_all"}},
        {"label": "Désélec.",    "color": "#5a6470", "action": {"type": "clear_sel"}},
        {"label": "CLEAR",       "color": "#22ccaa", "action": {"type": "clear"}},
        {"label": "Stop Effets", "color": "#ff8800", "action": {"type": "stop_fx"}},
    ],
}

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
        self.setText(f"{label}\n{target}" if target else label)
        if tip:
            self.setToolTip(tip)

    def _apply_style(self):
        accent = self.spec.get("color", "#0077bb")
        if getattr(self, "active", False):
            # Bloc allumé : rempli de sa couleur + liseré blanc
            self.setStyleSheet(
                f"QPushButton {{ background:{accent}; color:#000; border:3px solid #ffffff; "
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
        super().paintEvent(ev)
        # Poignée de resize (3 traits en coin) visible en mode Édition
        if not self.canvas.edit_mode:
            return
        p = QPainter(self)
        pen = QPen(QColor(self.spec.get("color", "#0077bb")))
        pen.setWidth(2)
        p.setPen(pen)
        w, h = self.width(), self.height()
        for off in (5, 9, 13):
            p.drawLine(w - off, h - 3, w - 3, h - off)
        p.end()

    def contextMenuEvent(self, ev):
        menu = QMenu(self)
        act_edit = None
        if self.spec.get("action", {}).get("type") in ("color", "effect"):
            act_edit = menu.addAction("🎯  Modifier les groupes…")
            menu.addSeparator()
        act_del = menu.addAction("🗑  Supprimer le bloc")
        chosen = menu.exec(ev.globalPos())
        if chosen is None:
            return
        if act_edit is not None and chosen == act_edit and self.canvas.edit_cb:
            self.canvas.edit_cb(self)
        elif chosen == act_del:
            self.canvas.remove_block(self)


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
    def add_block(self, spec: dict) -> ExtBlock:
        blk = ExtBlock(deepcopy(spec), self)
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
        blk = ExtBlock(deepcopy(spec), self)
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
        self.setWindowTitle("EXT — Surface configurable")
        self.setFont(QFont("Segoe UI"))   # même police que le reste du logiciel
        self.resize(1100, 680)
        self._build_ui()
        self._load_layout()

    # ── Construction UI ───────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_left_column())
        root.addWidget(self._build_right_zone(), 1)

        self._cat_buttons["color"].setChecked(True)
        self._on_category("color")

    def _build_left_column(self) -> QWidget:
        left = QWidget()
        left.setFixedWidth(170)
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

        hdr = QLabel("Surface EXT")
        hdr.setStyleSheet("color:#888; font-size:12px; font-weight:bold;")
        bl.addWidget(hdr)
        bl.addStretch()

        self._status = QLabel("")
        self._status.setStyleSheet("color:#00d4ff; font-size:11px;")
        bl.addWidget(self._status)
        bl.addSpacing(10)

        self._lock_btn = QPushButton("🔓  Édition")
        self._lock_btn.setCheckable(True)
        self._lock_btn.setChecked(True)   # démarre en Édition
        self._lock_btn.setFixedHeight(28)
        self._lock_btn.setCursor(Qt.PointingHandCursor)
        self._lock_btn.setStyleSheet(self._lock_btn_ss())
        self._lock_btn.toggled.connect(self._on_lock_toggled)
        bl.addWidget(self._lock_btn)
        rv.addWidget(bar)

        self.canvas = GridCanvas()
        self.canvas.activate_cb = self._dispatch_action
        self.canvas.edit_cb = self._edit_block_groups
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
        if code in BLOCK_LIBRARY:
            return BLOCK_LIBRARY[code]
        if code == "position":
            return self._position_specs()
        if code == "mem":
            return self._mem_specs()
        return []

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
                out.append({
                    "label": f"MEM {c + 1}.{r + 1}", "color": "#c080ff",
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
        b.setToolTip("Cliquer pour ajouter, ou glisser vers la surface")
        b.setStyleSheet(
            f"QPushButton {{ background:#1a1a1a; color:#ddd; border:1px solid #2e2e2e; "
            f"border-left:4px solid {accent}; border-radius:4px; font-size:11px; "
            f"text-align:left; padding-left:8px; }} "
            f"QPushButton:hover {{ background:#252525; color:#fff; }}"
        )
        b.clicked.connect(lambda _=False, s=spec: self.canvas.add_block(s))
        return b

    def _on_lock_toggled(self, edit_on: bool):
        self._lock_btn.setText("🔓  Édition" if edit_on else "🔒  Live")
        self.canvas.set_edit_mode(edit_on)

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
            self._flash_status("Position rappelée")
        elif t == "mem":
            owner._apply_memory_to_projectors(action.get("col", 0), action.get("row", 0))
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
        else:
            self._flash_status(f"« {action.get('what', t)} » — à venir")

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
        cur = act.get("groups", "all")    # défaut = tous les groupes
        disp = getattr(self._owner, "GROUP_DISPLAY", {}) or {}

        # Groupes proposés : pour un effet, seulement ceux mappés sur une lettre A–H
        groups_avail = self._available_groups()
        if not is_color:
            groups_avail = [g for g in groups_avail
                            if len(disp.get(g, "")) == 1 and disp.get(g, "").isalpha()]

        accent = blk.spec.get("color", "#00d4ff")
        dlg = QDialog(self)
        dlg.setWindowTitle("Cible de la couleur" if is_color else "Cible de l'effet")
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

        hdr = QLabel((("Couleur" if is_color else "Effet")
                      + f"  « {blk.spec.get('label', '?')} »"))
        hdr.setObjectName("hdr")
        lay.addWidget(hdr)
        sub = QLabel("Où envoyer la couleur ?" if is_color
                     else "Sur quels groupes jouer l'effet ?")
        sub.setObjectName("sub")
        lay.addWidget(sub)
        lay.addSpacing(10)

        rb_all = QRadioButton("Tous les groupes")
        rb_sel = QRadioButton("Projecteurs sélectionnés")   # couleurs uniquement
        rb_grp = QRadioButton("Groupes spécifiques")
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
            cb = QCheckBox(f"  {tag} · {g.capitalize()}".rstrip())
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
        bb.button(QDialogButtonBox.Ok).setText("Valider")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
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
    def _save_layout(self):
        try:
            data = {"version": 1, "blocks": [
                {
                    "label":  b.spec.get("label"),
                    "color":  b.spec.get("color"),
                    "action": b.spec.get("action"),
                    "col": b.col, "row": b.row,
                    "span_c": b.span_c, "span_r": b.span_r,
                }
                for b in self.canvas.blocks
            ]}
            with open(self.LAYOUT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[EXT] Échec sauvegarde layout : {e}")

    def _load_layout(self):
        try:
            if not os.path.exists(self.LAYOUT_FILE):
                return
            with open(self.LAYOUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[EXT] Échec lecture layout : {e}")
            return

        self.canvas._loading = True
        try:
            for d in data.get("blocks", []):
                spec = {
                    "label":  d.get("label", "?"),
                    "color":  d.get("color", "#0077bb"),
                    "action": d.get("action", {}),
                }
                blk = ExtBlock(deepcopy(spec), self.canvas)
                blk.span_c = max(1, int(d.get("span_c", 1)))
                blk.span_r = max(1, int(d.get("span_r", 1)))
                blk.place(int(d.get("col", 0)), int(d.get("row", 0)))
                blk.show()
                self.canvas.blocks.append(blk)
        finally:
            self.canvas._loading = False

    def closeEvent(self, ev):
        self._save_layout()
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
