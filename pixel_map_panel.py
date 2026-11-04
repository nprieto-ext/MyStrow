"""
Panneau « Effets pixel » du plan de feu 2D.

    SENS            Tout · Dégradés · Vagues · Chenillards · Blocs · Rampes
    ↖  ↑  ↗        ┌────────────┬────────────┐
    ←  ◎  →        │ Vague      │ Vague ×2   │   vignettes ANIMÉES : chacune
    ↙  ↓  ↘        │ ▮▯▯▮▮▯▯▮   │ ▮▯▮▯▮▯▮▯   │   montre son motif avec les
    [⊚ Bords→centre]└────────────┴────────────┘   couleurs et le sens choisis
    [🎲 Aléatoire]
    Couleurs : (●) ──▶ (●)   + palettes toutes faites
    Noir : court ━━●━━ long     Vitesse : figé ━━●━━ rapide
    [■ Arrêter] [💾 Enregistrer]                       [OK]

Le SENS se règle une seule fois, au pavé de flèches ; les vignettes proposent
les motifs et leurs variantes (1, 2 ou 4 passages à la fois).

Le plan 2D, derrière, montre le rendu réel en direct. Fermer (OK) laisse
l'effet tourner ; « Arrêter » rend les fixtures à leur état d'avant ;
« Enregistrer » le range dans la bibliothèque d'effets (pads, REC Lumière,
tablette…).
"""

from __future__ import annotations

import math
import time as _time

from PySide6.QtCore import Qt, QRectF, Signal, QPoint, QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QDialog, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QWidget,
    QPushButton, QSlider, QColorDialog, QAbstractButton, QScrollArea,
    QButtonGroup,
)

from i18n import tr, TRANSLATIONS
from pixel_map import (GradientSpec, PRESETS, output_for, spatial_positions, spec_positions,
                       is_wheel_fixture)


# ── Lyres à roue de couleurs ────────────────────────────────────────────────
def _hue_name(hx):
    c = QColor(hx)
    if c.saturation() < 40:
        return tr("pxm_c_white")
    h = c.hue()
    for lim, key in ((15, "red"), (45, "orange"), (70, "yellow"), (160, "green"),
                     (200, "cyan"), (255, "blue"), (290, "violet"), (340, "pink")):
        if h < lim:
            return tr("pxm_c_" + key)
    return tr("pxm_c_red")


def wheel_colors(plan, targets):
    """Couleurs de la roue si la sélection n'est QUE des lyres à roue (sinon
    None : un PAR RVB garde la palette complète, chaque lyre prenant alors le
    slot le plus proche). Roue non calibrée → table générique de l'app."""
    if not targets or not all(is_wheel_fixture(p) for p in targets):
        return None
    slots = next((getattr(p, 'color_wheel_slots', None) for p in targets
                  if getattr(p, 'color_wheel_slots', None)), None)
    if not slots:
        mw = getattr(plan, 'main_window', None)
        slots = getattr(mw, '_GENERIC_WHEEL_SLOTS', None)
        if not slots:
            from main_window import MainWindow
            slots = MainWindow._GENERIC_WHEEL_SLOTS
    out = []
    for sl in slots:
        hx = QColor(sl.get('color', '#ffffff')).name()
        if hx not in out and hx != "#000000":
            out.append(hx)
    return out or None


def wheel_presets(colors):
    """Palettes faites des SEULES couleurs de la roue : chaque couleur sur
    noir (le noir se fait au dim), puis toute la roue."""
    pres = {}
    for hx in colors:
        pres[f"{_hue_name(hx)}/{tr('pxm_c_black')}"] = [hx, "#000000"]
    if len(colors) >= 3:
        pres[tr("pxm_whole_wheel")] = [c for c in colors
                                       if QColor(c).saturation() >= 40] or list(colors)
    return pres


def snap_to_wheel(stops, colors):
    """Ramène chaque couleur sur la couleur de roue la plus proche (le noir
    reste noir)."""
    from core import cw_slot_for_color
    slots = [{"color": c} for c in colors]
    out = []
    for hx in stops:
        best = cw_slot_for_color(slots, QColor(hx))
        out.append("#000000" if best is None else best["color"])
    return out


# Clés propres au panneau, ajoutées au dictionnaire global sans écraser
# celles qui y seraient déjà (migration i18n en cours).
_T = {
    "pxm_title":     {"fr": "Effets pixel", "en": "Pixel effects"},
    "pxm_count":     {"fr": "{n} projecteurs", "en": "{n} fixtures"},
    "pxm_sense":     {"fr": "SENS", "en": "DIRECTION"},
    "pxm_motifs":    {"fr": "MOTIF", "en": "PATTERN"},
    "pxm_all":       {"fr": "Tout", "en": "All"},
    "pxm_m_degrade": {"fr": "Dégradé", "en": "Gradient"},
    "pxm_m_vague":   {"fr": "Vague", "en": "Wave"},
    "pxm_m_chenillard": {"fr": "Chenillard", "en": "Chase"},
    "pxm_m_bloc":    {"fr": "Bloc", "en": "Block"},
    "pxm_m_rampe":   {"fr": "Rampe", "en": "Ramp"},
    "pxm_t_degrade": {"fr": "Dégradés", "en": "Gradients"},
    "pxm_t_vague":   {"fr": "Vagues", "en": "Waves"},
    "pxm_t_chenillard": {"fr": "Chenillards", "en": "Chases"},
    "pxm_t_bloc":    {"fr": "Blocs", "en": "Blocks"},
    "pxm_t_rampe":   {"fr": "Rampes", "en": "Ramps"},
    "pxm_rep_1":     {"fr": "1 passage", "en": "1 pass"},
    "pxm_rep_n":     {"fr": "{n} à la fois", "en": "{n} at once"},
    "pxm_d_out":     {"fr": "S'ouvre depuis le centre : le motif part du milieu et s'étale vers les bords",
                      "en": "Opens from the centre: the pattern starts in the middle and spreads outwards"},
    "pxm_d_in":      {"fr": "⊚  Vers le centre", "en": "⊚  To the centre"},
    "pxm_d_in_tip":  {"fr": "L'inverse du ◎ : le motif part des bords et se referme au milieu",
                      "en": "The reverse of ◎: the pattern starts at the edges and closes in the middle"},
    "pxm_d_rnd":     {"fr": "🎲  Aléatoire", "en": "🎲  Random"},
    "pxm_d_arrow":   {"fr": "Vers {dir}", "en": "Towards {dir}"},
    "pxm_colors":    {"fr": "COULEURS", "en": "COLOURS"},
    "pxm_dim":       {"fr": "DIM", "en": "DIM"},
    "pxm_dim_tip":   {"fr": "Intensité générale de l'effet", "en": "Overall intensity of the effect"},
    "pxm_color_tip": {"fr": "Couleur allumée", "en": "Lit colour"},
    "pxm_color_n":   {"fr": "Couleur {n}", "en": "Colour {n}"},
    "pxm_reset":     {"fr": "↺  Réinitialiser", "en": "↺  Reset"},
    "pxm_reset_tip": {"fr": "Réinitialiser : reprendre les couleurs d'origine de la palette « {name} »",
                      "en": "Reset: back to the original colours of the “{name}” palette"},
    "pxm_back_tip":  {"fr": "Fond (noir = éteint)", "en": "Background (black = off)"},
    "pxm_black":     {"fr": "NOIR", "en": "BLACK"},
    "pxm_back":      {"fr": "FOND", "en": "BACKGROUND"},
    "pxm_back_tip2": {"fr": "Allonge la couleur de fond entre deux passages",
                      "en": "Stretches the background colour between two passes"},
    "pxm_black_tip": {"fr": "Allonge la partie éteinte entre deux passages",
                      "en": "Stretches the dark part between two passes"},
    "pxm_short":     {"fr": "court", "en": "short"},
    "pxm_long":      {"fr": "long", "en": "long"},
    "pxm_speed":     {"fr": "VITESSE", "en": "SPEED"},
    "pxm_static":    {"fr": "figé", "en": "static"},
    "pxm_fast":      {"fr": "rapide", "en": "fast"},
    "pxm_stop":      {"fr": "■  Arrêter", "en": "■  Stop"},
    "pxm_save":      {"fr": "💾  Enregistrer", "en": "💾  Save"},
    "pxm_save_tip":  {"fr": "Ranger l'effet dans la bibliothèque : il se pose ensuite "
                            "sur un pad, dans le REC Lumière, sur la tablette…",
                      "en": "Store the effect in the library: then drop it on a pad, "
                            "in the light REC, on the tablet…"},
    "pxm_save_title": {"fr": "Enregistrer l'effet", "en": "Save the effect"},
    "pxm_save_label": {"fr": "Nom de l'effet :", "en": "Effect name:"},
    "pxm_saved":     {"fr": "✓  « {name} » enregistré — dans la bibliothèque d'effets",
                      "en": "✓  “{name}” saved — in the effects library"},
    "pxm_ok":        {"fr": "OK", "en": "OK"},
    "pxm_ok_tip":    {"fr": "L'effet continue de tourner", "en": "The effect keeps running"},
    "pxm_pick":      {"fr": "Choisir la couleur", "en": "Pick the colour"},
    "pxm_other":     {"fr": "Autre…", "en": "Other…"},
    "pxm_wheel_note": {"fr": "Lyres à roue : seulement les couleurs de leur roue, le noir passe par le dim",
                       "en": "Colour-wheel heads: only their wheel colours, black goes through the dimmer"},
    "pxm_whole_wheel": {"fr": "Toute la roue", "en": "Whole wheel"},
    "pxm_c_white":   {"fr": "Blanc", "en": "White"},
    "pxm_c_black":   {"fr": "Noir", "en": "Black"},
    "pxm_c_red":     {"fr": "Rouge", "en": "Red"},
    "pxm_c_orange":  {"fr": "Orange", "en": "Orange"},
    "pxm_c_yellow":  {"fr": "Jaune", "en": "Yellow"},
    "pxm_c_green":   {"fr": "Vert", "en": "Green"},
    "pxm_c_cyan":    {"fr": "Cyan", "en": "Cyan"},
    "pxm_c_blue":    {"fr": "Bleu", "en": "Blue"},
    "pxm_c_violet":  {"fr": "Violet", "en": "Purple"},
    "pxm_c_pink":    {"fr": "Rose", "en": "Pink"},
    "pxm_menu_tip":  {"fr": "Effets pixel : dégradés, vagues, chenillards… selon la "
                            "position des projecteurs sur le plan.",
                      "en": "Pixel effects: gradients, waves, chases… following the "
                            "fixtures' position on the plan."},
}
for _k, _v in _T.items():
    TRANSLATIONS.setdefault(_k, _v)


MOTIF_ORDER = ["degrade", "vague", "chenillard", "bloc", "rampe"]
REPEATS = [1.0, 2.0, 4.0]

# Pavé de flèches : (ligne, colonne) → (icône, angle). Angle en sens écran :
# 0 = vers la droite, 90 = vers le bas.
ARROWS = {
    (0, 0): ("↖", 225.0), (0, 1): ("↑", 270.0), (0, 2): ("↗", 315.0),
    (1, 0): ("←", 180.0),                       (1, 2): ("→", 0.0),
    (2, 0): ("↙", 135.0), (2, 1): ("↓", 90.0),  (2, 2): ("↘", 45.0),
}
ARROW_BY_ANGLE = {a: icon for icon, a in ARROWS.values()}

QUICK_COLORS = ["#ff0000", "#ff6000", "#ffd000", "#00ff00", "#00ffff",
                "#0040ff", "#8000ff", "#ff00ff", "#ffffff", "#000000"]

_ACCENT = "#00d4ff"
_SS_DLG = "QDialog{background:#0f0f0f;} QLabel{color:#ccc;background:transparent;}"
_SS_SEC = "color:#5a5a5a;font-size:9px;font-weight:bold;letter-spacing:2px;"
_SS_TAB = ("QPushButton{background:transparent;color:#777;border:none;"
           "border-bottom:2px solid transparent;padding:5px 8px;font-size:11px;"
           "font-weight:bold;}"
           "QPushButton:hover{color:#ddd;}"
           "QPushButton:checked{color:#00d4ff;border-bottom:2px solid #00d4ff;}")
_SS_ARROW = ("QPushButton{background:#1a1a1a;color:#9a9a9a;border:1px solid #2c2c2c;"
             "border-radius:10px;font-size:22px;}"
             "QPushButton:hover{color:#fff;border-color:#666;background:#222;}"
             "QPushButton:checked{background:#00303f;color:#00d4ff;"
             "border:2px solid #00d4ff;}")
_SS_SENSE = ("QPushButton{background:#1a1a1a;color:#aaa;border:1px solid #2c2c2c;"
             "border-radius:8px;padding:7px 8px;font-size:11px;text-align:left;}"
             "QPushButton:hover{color:#fff;border-color:#666;}"
             "QPushButton:checked{background:#00303f;color:#00d4ff;"
             "border:2px solid #00d4ff;}")
_SS_STOP = ("QPushButton{background:#2a1010;color:#f55;border:1px solid #5a2222;"
            "border-radius:8px;padding:10px 18px;font-size:12px;font-weight:bold;}"
            "QPushButton:hover{background:#3a1515;color:#f77;}")
_SS_SAVE = ("QPushButton{background:#1c1c1c;color:#ddd;border:1px solid #3a3a3a;"
            "border-radius:8px;padding:10px 18px;font-size:12px;font-weight:bold;}"
            "QPushButton:hover{color:#fff;border-color:#00d4ff;}")
_SS_OK = ("QPushButton{background:#00303f;color:#00d4ff;border:1px solid #00d4ff;"
          "border-radius:8px;padding:10px 30px;font-size:12px;font-weight:bold;}"
          "QPushButton:hover{background:#004458;}")
_SS_SLI = ("QSlider::groove:horizontal{height:6px;background:#242424;border-radius:3px;}"
           "QSlider::sub-page:horizontal{background:#00a0cc;border-radius:3px;}"
           "QSlider::handle:horizontal{background:#e8faff;width:16px;margin:-6px 0;"
           "border-radius:8px;border:2px solid #00d4ff;}")
_SS_SCROLL = ("QScrollArea{border:none;background:transparent;}"
              "QScrollBar:vertical{background:#111;width:8px;margin:0;}"
              "QScrollBar::handle:vertical{background:#333;border-radius:4px;min-height:30px;}"
              "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")


def _qc(rgb):
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _sep():
    s = QFrame(); s.setFixedHeight(1)
    s.setStyleSheet("background:#1f1f1f;border:none;")
    return s


def sense_of(spec):
    """Sens courant : ("arrow", angle) | ("out",) | ("in",) | ("rnd",)."""
    if spec.shape == "radial":
        return ("out",)
    if spec.shape == "radial_in":
        return ("in",)
    if spec.shape == "random":
        return ("rnd",)
    return ("arrow", float(int(round(spec.angle / 45.0)) * 45 % 360))


def sense_label(spec):
    s = sense_of(spec)
    if s[0] == "arrow":
        return ARROW_BY_ANGLE.get(s[1], "→")
    if s[0] == "out":
        return "◎"
    if s[0] == "in":
        return "⊚"
    return "🎲"


# ─────────────────────────────────────────────────────────────────────────────
# Vignette animée
# ─────────────────────────────────────────────────────────────────────────────

class _MotifTile(QAbstractButton):
    """Une vignette « Vague · ×2 » avec son rendu qui tourne, dans le sens
    choisi au pavé de flèches."""

    CELLS = 14

    def __init__(self, motif, repeat, dialog, parent=None):
        super().__init__(parent)
        self.motif = motif
        self.repeat = repeat
        self.dlg = dialog
        self.setCheckable(True)
        self.setFixedHeight(66)
        self.setMinimumWidth(170)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, ev):
        self.update(); super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.update(); super().leaveEvent(ev)

    def _spec(self):
        base = self.dlg.spec
        shape, angle = base.shape, base.angle
        if shape == "linear":
            # La bande est horizontale : un sens vertical s'y lit comme
            # gauche→droite (↓) ou droite→gauche (↑).
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            angle = 180.0 if (c < -0.01 or (abs(c) <= 0.01 and s < 0)) else 0.0
        return GradientSpec(stops=list(base.stops), motif=self.motif,
                            shape=shape, angle=angle, gap=base.gap,
                            repeat=self.repeat, speed=base.speed,
                            dim=base.dim)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        on = self.isChecked()
        p.setBrush(QColor("#0d2a33") if on else QColor("#161616"))
        if on:
            p.setPen(QPen(QColor(_ACCENT), 2))
        elif self.underMouse():
            p.setPen(QPen(QColor("#666"), 1.2))
        else:
            p.setPen(QPen(QColor("#252525"), 1))
        p.drawRoundedRect(r, 8, 8)

        # Titre : motif en gras + variante
        f = QFont(); f.setPixelSize(12); f.setBold(True); p.setFont(f)
        p.setPen(QColor("#ffffff") if on else QColor("#d6d6d6"))
        tr_ = QRectF(r.left() + 10, r.top() + 6, r.width() - 20, 17)
        p.drawText(tr_, Qt.AlignLeft | Qt.AlignVCenter, tr("pxm_m_" + self.motif))
        f2 = QFont(); f2.setPixelSize(10); p.setFont(f2)
        p.setPen(QColor("#7fdcf5") if on else QColor("#808080"))
        sub = tr("pxm_rep_1") if self.repeat == 1 else tr("pxm_rep_n", n=int(self.repeat))
        p.drawText(tr_, Qt.AlignRight | Qt.AlignVCenter, sub)

        # Bande de cellules animée
        spec = self._spec()
        n = self.CELLS
        pts = [(i / (n - 1), 0.5) for i in range(n)]
        pos = spec_positions(pts, spec)
        # Phase commune à toutes les vignettes, accumulée (cf. preview_phase)
        turns = self.dlg.preview_phase()
        top = r.top() + 29
        h = r.bottom() - 8 - top
        gap = 2.0
        cw = (r.width() - 20 - gap * (n - 1)) / n
        p.setPen(Qt.NoPen)
        for i, s in enumerate(pos):
            c = _qc(output_for(spec, s, turns))
            x = r.left() + 10 + i * (cw + gap)
            p.setBrush(QColor("#050505"))
            p.drawRoundedRect(QRectF(x, top, cw, h), 2, 2)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x + 1, top + 1, cw - 2, h - 2), 2, 2)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# Couleurs
# ─────────────────────────────────────────────────────────────────────────────

class _PaletteChip(QAbstractButton):
    """Petite palette toute faite : bande de couleurs + nom."""

    def __init__(self, name, stops, parent=None):
        super().__init__(parent)
        self.name = name.replace("/", " / ")
        self.stops = list(stops)
        self.setCheckable(True)
        self.setFixedHeight(32)
        self.setMinimumWidth(80)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(name)

    def enterEvent(self, ev):
        self.update(); super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.update(); super().leaveEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        g = QLinearGradient(r.left(), 0, r.right(), 0)
        n = len(self.stops)
        for i, hx in enumerate(self.stops):
            g.setColorAt(i / max(1, n - 1), QColor(hx))
        p.setBrush(QBrush(g)); p.setPen(Qt.NoPen)
        p.drawRoundedRect(r, 6, 6)
        f = QFont(); f.setPixelSize(9); f.setBold(True); p.setFont(f)
        band = QRectF(r.left() + 4, r.center().y() - 7, r.width() - 8, 14)
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawRoundedRect(band, 7, 7)
        p.setPen(QColor("#ffffff"))
        p.drawText(band, Qt.AlignCenter, self.name)
        if self.isChecked():
            pen = QPen(QColor(_ACCENT), 2.5)
        elif self.underMouse():
            pen = QPen(QColor("#cccccc"), 1.5)
        else:
            pen = QPen(QColor("#2a2a2a"), 1)
        p.setBrush(Qt.NoBrush); p.setPen(pen)
        p.drawRoundedRect(r, 6, 6)
        p.end()


class _Swatch(QAbstractButton):
    """Grosse pastille ronde."""

    def __init__(self, hx, tip, parent=None):
        super().__init__(parent)
        self.hx = hx
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)

    def set_color(self, hx):
        self.hx = hx; self.update()

    def set_small(self, small):
        s = 32 if small else 44
        if self.width() != s:
            self.setFixedSize(s, s)

    def enterEvent(self, ev):
        self.update(); super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.update(); super().leaveEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setBrush(QColor(self.hx))
        p.setPen(QPen(QColor("#ffffff") if self.underMouse() else QColor("#555"), 2))
        p.drawEllipse(r)
        p.end()


class _ArrowSep(QWidget):
    """Flèche fine entre deux pastilles (le « ▶ » texte s'affichait en
    pavé selon la police)."""

    def __init__(self, small=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(14 if small else 26, 32 if small else 44)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        y = h / 2.0
        pen = QPen(QColor("#7a7a7a"), 1.6)
        pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        x0, x1 = 2.0, w - 2.0
        p.drawLine(QPointF(x0, y), QPointF(x1, y))
        a = 4.0
        p.drawLine(QPointF(x1 - a, y - a), QPointF(x1, y))
        p.drawLine(QPointF(x1 - a, y + a), QPointF(x1, y))
        p.end()


class _ColorPopup(QFrame):
    """Palette rapide sous une pastille : 10 couleurs + « Autre… »."""

    picked = Signal(str)

    def __init__(self, current, parent=None, colors=None, allow_other=True):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet("QFrame{background:#161616;border:1px solid #333;"
                           "border-radius:8px;}")
        self._current = current
        lay = QVBoxLayout(self); lay.setContentsMargins(8, 8, 8, 8); lay.setSpacing(6)
        grid = QGridLayout(); grid.setSpacing(5)
        for i, hx in enumerate(colors or QUICK_COLORS):
            b = QPushButton(); b.setFixedSize(30, 30)
            b.setCursor(Qt.PointingHandCursor)
            sel = hx.lower() == (current or "").lower()
            b.setStyleSheet(
                f"QPushButton{{background:{hx};border:2px solid "
                f"{'#00d4ff' if sel else '#444'};border-radius:15px;}}"
                "QPushButton:hover{border-color:#fff;}")
            b.clicked.connect(lambda _=False, c=hx: self._choose(c))
            grid.addWidget(b, i // 5, i % 5)
        lay.addLayout(grid)
        if not allow_other:
            return
        other = QPushButton(tr("pxm_other"))
        other.setStyleSheet("QPushButton{background:#1c1c1c;color:#aaa;border:1px solid #333;"
                            "border-radius:6px;padding:4px;font-size:11px;}"
                            "QPushButton:hover{color:#fff;}")
        other.clicked.connect(self._other)
        lay.addWidget(other)

    def _choose(self, hx):
        self.picked.emit(hx); self.close()

    def _other(self):
        self.hide()
        c = QColorDialog.getColor(QColor(self._current), self.parentWidget(),
                                  tr("pxm_pick"))
        if c.isValid():
            self.picked.emit(c.name())
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
# Panneau
# ─────────────────────────────────────────────────────────────────────────────

class PixelMapDialog(QDialog):
    """Effets pixel sur une sélection du plan : un sens, un motif, des
    couleurs, la longueur du noir et la vitesse."""

    def __init__(self, plan, projectors, spec=None, parent=None):
        super().__init__(parent or plan)
        self.plan = plan
        self.projectors = list(projectors)
        self.targets = plan.gradient_targets(self.projectors)
        # Copie : le spec est référencé par les effets en cours, le modifier
        # en place changerait aussi l'effet d'une AUTRE sélection.
        base = spec or getattr(plan, '_last_gradient_spec', None)
        self.spec = GradientSpec.from_dict(base.to_dict()) if base else \
            GradientSpec(stops=list(PRESETS["Rouge/Noir"]), motif="vague",
                         speed=0.4, gap=0.3)
        if self.spec.repeat not in REPEATS:
            self.spec.repeat = 1.0
        # Sélection 100 % lyres à roue : on ne propose QUE leurs couleurs.
        self.wheel = wheel_colors(plan, self.targets)
        if self.wheel:
            self._presets = wheel_presets(self.wheel)
            self.spec.stops = snap_to_wheel(self.spec.stops, self.wheel)
        else:
            self._presets = PRESETS
        self.spec.reverse = False
        # Palette d'origine (pour ↺) : celle dont on part, si elle en est une
        self._palette_ref = next(
            (nm for nm, st in self._presets.items()
             if [x.lower() for x in st] == [x.lower() for x in self.spec.stops]), None)
        self._t0 = _time.monotonic()
        self._last_tick = self._t0
        self._phase = 0.0
        self._tab = "all"
        self.setWindowTitle(tr("pxm_title"))
        self.setWindowFlag(Qt.Tool, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(_SS_DLG)
        self._build()
        self._refresh()
        self._apply(start=True)

        # Vignettes animées
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick)
        self._anim.start(33)

    def clock(self):
        return _time.monotonic() - self._t0

    # Vitesse minimale des vignettes : même « figé », une vignette doit
    # montrer son mouvement.
    _TILE_MIN_SPEED = 0.35

    def preview_phase(self):
        """Phase (en tours) des vignettes.

        ACCUMULÉE image par image (`vitesse × dt`) et non `vitesse × temps
        écoulé` : sinon accélérer faisait sauter tous les motifs d'un coup —
        d'autant plus loin que le panneau était ouvert depuis longtemps.
        Même principe que l'horloge de phase du moteur d'effets.
        """
        return self._phase

    def _tick(self):
        now = _time.monotonic()
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now
        self._phase += max(self._TILE_MIN_SPEED, self.spec.speed) * dt
        for t in self._tiles:
            if t.isVisible():
                t.update()

    # ── Construction ────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18); root.setSpacing(12)

        # En-tête
        head = QHBoxLayout(); head.setSpacing(10)
        title = QLabel("🎨  " + tr("pxm_title"))
        title.setStyleSheet("color:#eee;font-size:16px;font-weight:bold;")
        cnt = QLabel(tr("pxm_count", n=len(self.targets)))
        cnt.setStyleSheet("color:#00d4ff;font-size:10px;font-weight:bold;"
                          "background:#00303f;border-radius:9px;padding:3px 10px;")
        head.addWidget(title); head.addWidget(cnt); head.addStretch()
        root.addLayout(head)
        root.addWidget(_sep())

        # ── Sens (pavé) | Motifs (vignettes) ───────────────────────────────
        body = QHBoxLayout(); body.setSpacing(18)

        sense = QVBoxLayout(); sense.setSpacing(8)
        lbl = QLabel(tr("pxm_sense")); lbl.setStyleSheet(_SS_SEC)
        sense.addWidget(lbl)
        pad = QGridLayout(); pad.setSpacing(6)
        self._arrow_btns = {}
        for rc in [(r, c) for r in range(3) for c in range(3)]:
            if rc == (1, 1):
                b = QPushButton("◎"); b.setToolTip(tr("pxm_d_out"))
                b.clicked.connect(lambda: self._set_sense(("out",)))
                self._out_btn = b
            else:
                icon, ang = ARROWS[rc]
                b = QPushButton(icon); b.setToolTip(tr("pxm_d_arrow", dir=icon))
                b.clicked.connect(lambda _=False, a=ang: self._set_sense(("arrow", a)))
                self._arrow_btns[ang] = b
            b.setCheckable(True); b.setFixedSize(54, 54); b.setStyleSheet(_SS_ARROW)
            pad.addWidget(b, *rc)
        sense.addLayout(pad)
        sense.addSpacing(4)
        self._in_btn = QPushButton(tr("pxm_d_in")); self._in_btn.setCheckable(True)
        self._in_btn.setToolTip(tr("pxm_d_in_tip"))
        self._in_btn.setStyleSheet(_SS_SENSE)
        self._in_btn.clicked.connect(lambda: self._set_sense(("in",)))
        self._rnd_btn = QPushButton(tr("pxm_d_rnd")); self._rnd_btn.setCheckable(True)
        self._rnd_btn.setStyleSheet(_SS_SENSE)
        self._rnd_btn.clicked.connect(lambda: self._set_sense(("rnd",)))
        sense.addWidget(self._in_btn); sense.addWidget(self._rnd_btn)
        sense.addStretch()
        body.addLayout(sense)

        motifs = QVBoxLayout(); motifs.setSpacing(8)
        tabs = QHBoxLayout(); tabs.setSpacing(2)
        self._tab_btns = {}
        grp = QButtonGroup(self); grp.setExclusive(True)
        for key, lbl_k in [("all", "pxm_all")] + [(m, "pxm_t_" + m) for m in MOTIF_ORDER]:
            b = QPushButton(tr(lbl_k)); b.setCheckable(True); b.setStyleSheet(_SS_TAB)
            b.clicked.connect(lambda _=False, k=key: self._set_tab(k))
            grp.addButton(b); self._tab_btns[key] = b; tabs.addWidget(b)
        tabs.addStretch()
        motifs.addLayout(tabs)
        self._tab_btns["all"].setChecked(True)

        self._tiles = []
        inner = QWidget(); inner.setStyleSheet("background:transparent;")
        self._grid = QGridLayout(inner)
        self._grid.setContentsMargins(0, 2, 6, 2)
        self._grid.setHorizontalSpacing(8); self._grid.setVerticalSpacing(8)
        for m in MOTIF_ORDER:
            for rep in REPEATS:
                t = _MotifTile(m, rep, self)
                t.clicked.connect(lambda _=False, tt=t: self._pick_tile(tt))
                self._tiles.append(t)
        self._layout_tiles()
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(inner)
        sc.setStyleSheet(_SS_SCROLL)
        sc.setFixedHeight(self._TILES_H)
        self._tiles_scroll = sc
        motifs.addWidget(sc)
        body.addLayout(motifs, 1)
        root.addLayout(body)
        root.addWidget(_sep())

        # ── Couleurs ───────────────────────────────────────────────────────
        self._colors_box = QWidget()
        cbox = QVBoxLayout(self._colors_box)
        cbox.setContentsMargins(0, 0, 0, 0); cbox.setSpacing(8)
        lbl = QLabel(tr("pxm_colors")); lbl.setStyleSheet(_SS_SEC)
        cbox.addWidget(lbl)
        crow = QHBoxLayout(); crow.setSpacing(10)
        # UNE pastille par couleur de la palette (avant : la 1re et la
        # dernière seulement — « Police » s'affichait rouge → noir, son bleu
        # était invisible et inéditable ; remontée de Nico, 04/11/26). Chaque
        # pastille ne change QUE sa couleur ; ↺ rend celles de la palette.
        self._sw_lay = QHBoxLayout(); self._sw_lay.setSpacing(4)
        self._sws = []
        self._rebuild_swatches()
        # Juste SOUS les pastilles, aligné à gauche (demande de Nico)
        self._reset_btn = QPushButton(tr("pxm_reset"))
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.setStyleSheet(
            "QPushButton{background:#1c1c1c;color:#ccc;border:1px solid #3a3a3a;"
            "border-radius:6px;padding:3px 10px;font-size:11px;}"
            "QPushButton:hover{color:#fff;border-color:#00d4ff;}"
            "QPushButton:disabled{color:#555;border-color:#2a2a2a;}")
        self._reset_btn.clicked.connect(self._reset_colors)
        swv = QVBoxLayout(); swv.setSpacing(6)
        swv.addLayout(self._sw_lay)
        swv.addWidget(self._reset_btn, 0, Qt.AlignLeft)
        swv.addStretch()
        crow.addLayout(swv)
        crow.addSpacing(12)
        pal = QGridLayout(); pal.setHorizontalSpacing(6); pal.setVerticalSpacing(6)
        self._chips = {}
        if self.wheel:
            note = QLabel(tr("pxm_wheel_note"))
            note.setStyleSheet("color:#c9a227;font-size:10px;")
            note.setWordWrap(True)
            cbox.addWidget(note)
        for i, (name, stops) in enumerate(self._presets.items()):
            c = _PaletteChip(name, stops)
            c.clicked.connect(lambda _=False, nm=name: self._set_palette(nm))
            self._chips[name] = c
            pal.addWidget(c, i // 5, i % 5)
        crow.addLayout(pal, 1)
        cbox.addLayout(crow)
        root.addWidget(self._colors_box)
        root.addWidget(_sep())

        # ── Noir + vitesse ─────────────────────────────────────────────────
        sl = QGridLayout(); sl.setHorizontalSpacing(10); sl.setVerticalSpacing(12)
        self.gap_sli = self._slider(0, 90, self._on_gap)
        self.gap_sli.setToolTip(tr("pxm_black_tip"))
        self.spd_sli = self._slider(0, 100, self._on_speed)
        self.dim_sli = self._slider(0, 100, self._on_dim)
        self.dim_sli.setToolTip(tr("pxm_dim_tip"))
        for row, (key, lo, hi, s) in enumerate((
                ("pxm_black", "pxm_short", "pxm_long", self.gap_sli),
                ("pxm_speed", "pxm_static", "pxm_fast", self.spd_sli),
                ("pxm_dim", "0 %", "100 %", self.dim_sli))):
            if key == "pxm_black":
                # Titre qui suit la couleur de fond : « NOIR » sur fond noir,
                # « FOND » sinon (Rouge/Bleu : c'est le bleu qui s'allonge),
                # avec une pastille de cette couleur.
                k = QWidget(); kl = QHBoxLayout(k)
                kl.setContentsMargins(0, 0, 0, 0); kl.setSpacing(6)
                self.gap_dot = QLabel(); self.gap_dot.setFixedSize(10, 10)
                self.gap_title = QLabel(tr(key)); self.gap_title.setStyleSheet(_SS_SEC)
                kl.addWidget(self.gap_dot); kl.addWidget(self.gap_title); kl.addStretch()
                k.setFixedWidth(84)
            else:
                k = QLabel(tr(key)); k.setStyleSheet(_SS_SEC); k.setFixedWidth(84)
            a = QLabel(tr(lo)); a.setStyleSheet("color:#777;font-size:10px;")
            b = QLabel(tr(hi)); b.setStyleSheet("color:#777;font-size:10px;")
            a.setFixedWidth(34); b.setFixedWidth(40)
            sl.addWidget(k, row, 0); sl.addWidget(a, row, 1)
            sl.addWidget(s, row, 2); sl.addWidget(b, row, 3)
        sl.setColumnStretch(2, 1)
        root.addLayout(sl)

        # Message d'enregistrement
        self.saved_lbl = QLabel("")
        self.saved_lbl.setStyleSheet("color:#4caf50;font-size:11px;font-weight:bold;")
        self.saved_lbl.setVisible(False)
        root.addWidget(self.saved_lbl)

        # Actions
        root.addSpacing(4)
        act = QHBoxLayout(); act.setSpacing(10)
        stop = QPushButton(tr("pxm_stop")); stop.setStyleSheet(_SS_STOP)
        stop.clicked.connect(self._stop)
        save = QPushButton(tr("pxm_save")); save.setStyleSheet(_SS_SAVE)
        save.setToolTip(tr("pxm_save_tip"))
        # lambda : `clicked` envoie un booléen (False) qui arrivait dans
        # `name` → pas de demande de nom puis `False.strip()` → plantage muet.
        save.clicked.connect(lambda _=False: self._save())
        ok = QPushButton(tr("pxm_ok")); ok.setStyleSheet(_SS_OK)
        ok.setToolTip(tr("pxm_ok_tip"))
        ok.clicked.connect(self.close)
        act.addWidget(stop); act.addWidget(save); act.addStretch(); act.addWidget(ok)
        root.addLayout(act)

        self.setFixedWidth(660)

    _TILES_H = 5 * 74 + 4
    _TILES_MIN_H = 2 * 74 + 4

    def fit_height(self, avail_h):
        """Petits écrans (portable 768 px) : la grille de vignettes — qui
        défile — rétrécit pour que toute la fenêtre tienne à l'écran."""
        self._tiles_scroll.setFixedHeight(self._TILES_H)
        self.adjustSize()
        excess = self.sizeHint().height() - (avail_h - 40)
        if excess > 0:
            self._tiles_scroll.setFixedHeight(
                max(self._TILES_MIN_H, self._TILES_H - excess))
            self.adjustSize()

    def _slider(self, lo, hi, cb):
        s = QSlider(Qt.Horizontal); s.setRange(lo, hi)
        s.setStyleSheet(_SS_SLI)
        s.valueChanged.connect(cb)
        return s

    def _layout_tiles(self):
        while self._grid.count():
            self._grid.takeAt(0)
        vis = [t for t in self._tiles if self._tab in ("all", t.motif)]
        for t in self._tiles:
            t.setVisible(t in vis)
        for i, t in enumerate(vis):
            self._grid.addWidget(t, i // 2, i % 2)
        self._grid.setRowStretch(len(vis) // 2 + 1, 1)

    # ── État affiché ───────────────────────────────────────────────────────
    def _refresh(self):
        s = self.spec
        sense = sense_of(s)
        for ang, b in self._arrow_btns.items():
            b.setChecked(sense == ("arrow", ang))
        self._out_btn.setChecked(sense == ("out",))
        self._in_btn.setChecked(sense == ("in",))
        self._rnd_btn.setChecked(sense == ("rnd",))
        for t in self._tiles:
            t.setChecked(t.motif == s.motif and t.repeat == s.repeat)
        for name, c in self._chips.items():
            c.setChecked([x.lower() for x in self._presets[name]] ==
                         [x.lower() for x in s.stops])
        if len(self._sws) != len(s.stops):
            self._rebuild_swatches()
        for w, hx in zip(self._sws, s.stops):
            w.set_color(hx)
        ref = self._presets.get(self._palette_ref) if self._palette_ref else None
        self._reset_btn.setVisible(ref is not None)
        if ref is not None:
            self._reset_btn.setEnabled([x.lower() for x in ref] !=
                                       [x.lower() for x in s.stops])
            self._reset_btn.setToolTip(tr("pxm_reset_tip", name=self._palette_ref))
        fond = self.background_color()
        is_black = QColor(fond).lightness() < 10
        self.gap_title.setText(tr("pxm_black") if is_black else tr("pxm_back"))
        self.gap_dot.setStyleSheet(
            f"background:{fond};border:1px solid #555;border-radius:5px;")
        self.gap_sli.setToolTip(tr("pxm_black_tip") if is_black else tr("pxm_back_tip2"))
        for w, v in ((self.dim_sli, int(round((s.dim if s.dim is not None else 1) * 100))),
                     (self.gap_sli, int(round((s.gap or 0) * 100))),
                     (self.spd_sli, max(0, min(100, int(round(s.speed * 50)))))):
            w.blockSignals(True); w.setValue(v); w.blockSignals(False)
        for t in self._tiles:
            t.update()

    def _changed(self):
        self._refresh()
        self._apply()

    # ── Réglages ────────────────────────────────────────────────────────────
    def _set_tab(self, key):
        self._tab = key
        for k, b in self._tab_btns.items():
            if b.isChecked() != (k == key):
                b.setChecked(k == key)
        self._layout_tiles()

    def _pick_tile(self, tile):
        self.spec.motif = tile.motif
        self.spec.repeat = tile.repeat
        self._changed()

    def _set_sense(self, sense):
        kind = sense[0]
        if kind == "arrow":
            self.spec.shape, self.spec.angle = "linear", float(sense[1])
        elif kind == "out":
            self.spec.shape, self.spec.angle = "radial", 0.0
        elif kind == "in":
            self.spec.shape, self.spec.angle = "radial_in", 0.0
        else:
            self.spec.shape, self.spec.angle = "random", 0.0
        self._changed()

    def _set_palette(self, name):
        self._palette_ref = name
        self.spec.stops = list(self._presets[name]); self._changed()

    def _reset_colors(self):
        if self._palette_ref in self._presets:
            self._set_palette(self._palette_ref)

    # Compat : 1re et dernière pastille
    @property
    def sw1(self):
        return self._sws[0]

    @property
    def sw2(self):
        return self._sws[-1]

    def _rebuild_swatches(self):
        while self._sw_lay.count():
            it = self._sw_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()           # deleteLater est différé : sinon l'ancienne
                w.deleteLater()    # pastille reste peinte sous la nouvelle
        self._sws = []
        stops = self.spec.stops or ["#ffffff"]
        n = len(stops)
        for k, hx in enumerate(stops):
            if k:
                self._sw_lay.addWidget(_ArrowSep(small=n > 2))
            tip = (tr("pxm_color_tip") if k == 0 else
                   tr("pxm_back_tip") if k == n - 1 else tr("pxm_color_n", n=k + 1))
            w = _Swatch(hx, tip)
            w.set_small(n > 2)
            w.clicked.connect(lambda _=False, i=k: self._pick_color(i))
            self._sw_lay.addWidget(w)
            self._sws.append(w)

    def _pick_color(self, which):
        which = max(0, min(len(self._sws) - 1, which))
        cur = self._sws[which].hx
        if self.wheel:
            pop = _ColorPopup(cur, self, colors=self.wheel + ["#000000"],
                              allow_other=False)
        else:
            pop = _ColorPopup(cur, self)
        pop.picked.connect(lambda hx, w=which: self._set_custom(w, hx))
        sw = self._sws[which]
        pop.adjustSize()
        pop.move(sw.mapToGlobal(QPoint(0, sw.height() + 4)))
        pop.show()

    def _set_custom(self, which, hx):
        # Ne change QUE la couleur de cette pastille : les autres couleurs de
        # la palette (le bleu et les noirs de « Police ») restent en place.
        # Avant, toute retouche ramenait l'effet à 2 couleurs. ↺ = d'origine.
        stops = list(self.spec.stops)
        if which < 0:                 # compat : -1 = la dernière (le fond)
            which = len(stops) - 1
        which = max(0, min(len(stops) - 1, which))
        stops[which] = hx
        self.spec.stops = stops; self._changed()

    def _on_gap(self, v):
        self.spec.gap = v / 100.0; self._changed()

    def _on_speed(self, v):
        self.spec.speed = v / 50.0; self._changed()

    def _on_dim(self, v):
        self.spec.dim = v / 100.0; self._changed()

    def background_color(self):
        """Couleur que le curseur NOIR/FOND allonge : la dernière de la
        palette, le fond du motif."""
        return self.spec.stops[-1]

    # Compat (tests / appels existants)
    def _set_preset(self, name):
        self._set_palette(name)

    def _set_direction(self, shape, angle):
        self.spec.shape, self.spec.angle = shape, float(angle)
        self._changed()

    # ── Moteur ──────────────────────────────────────────────────────────────
    def _apply(self, start=False):
        self.plan._last_gradient_spec = self.spec
        if start:
            self.plan.start_gradient_effect(self.projectors, self.spec)
        else:
            self.plan.update_gradient_effect(self.projectors, self.spec)

    def _stop(self):
        self.plan.stop_gradient_effect(self.projectors)
        self.close()

    def default_name(self):
        pal = next((n for n, st in self._presets.items()
                    if [x.lower() for x in st] == [x.lower() for x in self.spec.stops]),
                   None)
        rep = "" if self.spec.repeat == 1 else f"×{int(self.spec.repeat)}"
        return " ".join(x for x in (tr("pxm_m_" + self.spec.motif), rep, pal,
                                    sense_label(self.spec)) if x)

    def _save(self, name=None):
        """Range l'effet dans la bibliothèque d'effets perso."""
        if not isinstance(name, str):
            from effect_editor import _ask_name
            name, ok = _ask_name(self, tr("pxm_save_title"), tr("pxm_save_label"),
                                 self.default_name())
            if not ok or not (name or "").strip():
                return None
        eff = save_pixel_effect(self.plan, self.targets, self.spec, name.strip())
        if eff:
            self.saved_lbl.setText(tr("pxm_saved", name=eff["name"]))
            self.saved_lbl.setVisible(True)
        return eff

    def closeEvent(self, ev):
        self._anim.stop()
        super().closeEvent(ev)


# ─────────────────────────────────────────────────────────────────────────────
# Enregistrement dans la bibliothèque d'effets
# ─────────────────────────────────────────────────────────────────────────────

def build_pixel_effect(plan, targets, spec, name):
    """Effet de bibliothèque : UNE couche « Dégradé » ciblant précisément ces
    fixtures (cible « Sélection »), avec tous les réglages du panneau.

    La cible « Sélection » vise des fixtures PRÉCISES (groupe, index local) :
    l'effet rejoue sur les mêmes projecteurs depuis un pad ou le REC Lumière,
    et suit leur position sur le plan au moment où il tourne.
    """
    from core import projector_selection_keys
    from effect_editor import EffectLayer
    keys = dict(zip(map(id, plan.projectors), projector_selection_keys(plan.projectors)))
    sel = [list(keys[id(p)]) for p in targets if id(p) in keys]
    layer = EffectLayer()
    layer.attribute = "Dégradé"
    layer.forme = "Fixe"
    layer.target_preset = "Selection"
    layer.target_selection = [tuple(x) for x in sel]
    layer.color1 = spec.stops[0]
    layer.color2 = spec.stops[-1]
    layer.size = 100
    layer.grad = spec.to_dict()
    ld = layer.to_dict()
    return {
        "name": name,
        "emoji": "🎨",
        "category": "Mes Effets",
        "type": "Dégradé",
        "layers": [ld],
    }


def save_pixel_effect(plan, targets, spec, name):
    from effect_editor import _load_custom_effects, _save_custom_effects
    effects = _load_custom_effects()
    names = {e.get("name", "") for e in effects}
    base, k = name, 2
    while name in names:
        name = f"{base} {k}"; k += 1
    eff = build_pixel_effect(plan, targets, spec, name)
    effects.append(eff)
    _save_custom_effects(effects)
    return eff
