"""
Editeur d'effets par couches - EffectEditorDialog
Layout 2 colonnes : [Presets + Éditeur couches] | [Plan de Feu live]

Modèle :  Canal × Forme × Vitesse × Taille × Décalage × Phase
  - Décalage (spread) : décalage de phase entre fixtures consécutives (0=ensemble, 100=étalé)
  - Phase : décalage global de cette couche (pour déphacer R/V/B entre eux, etc.)
"""
import math
import copy
import time as _time
import random as _rnd

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QScrollArea, QFrame, QSizePolicy, QSlider,
    QGridLayout, QSpinBox,
)
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QConicalGradient, QRadialGradient

from core import SPREAD_MODES, spread_rank


class SpreadPreview(QWidget):
    """
    Aperçu de la répartition : 8 pastilles teintées selon leur rang.

    Deux fixtures de même teinte partent ensemble. « Miroir (bords) » montre
    donc 1 et 8 identiques, puis 2 et 7, etc. Lire « 1&8, puis 2&7 » dans une
    infobulle demande un effort ; le voir est immédiat.
    """

    def __init__(self, count=8, parent=None):
        super().__init__(parent)
        self._count = count
        self._mode = "lineaire"
        self.setFixedHeight(22)
        self.setMinimumWidth(120)

    def set_mode(self, mode):
        if mode != self._mode:
            self._mode = mode or "lineaire"
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = self._count
        w = self.width() / max(n, 1)
        for i in range(n):
            r = spread_rank(i, n, self._mode)
            # Rang 0 = part en premier = plein cyan ; rang 1 = sombre
            inten = 1.0 - min(1.0, max(0.0, r)) * 0.82
            col = QColor(int(0x00 + 0x22 * inten), int(0x2a + 0xaa * inten),
                         int(0x36 + 0xc9 * inten))
            rect = QRectF(i * w + 1.5, 3, max(2.0, w - 3), self.height() - 6)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(rect, 2, 2)
            p.setPen(QColor("#000") if inten > 0.55 else QColor("#667"))
            f = p.font(); f.setPointSize(7); f.setBold(True); p.setFont(f)
            p.drawText(rect, Qt.AlignCenter, str(i + 1))
        p.end()


# ─── Raccourci couche ──────────────────────────────────────────────────────────

def _L(attr, forme, target="Tous", speed=50, size=100, spread=0, phase=0, fade=0, direction=1, color1="#ff0000", color2="#0000ff", shape="cercle", sym_pan=False, spread_mode="lineaire"):
    d = {"attribute": attr, "forme": forme, "target_preset": target,
         "speed": speed, "size": size, "spread": spread, "phase": phase,
         "fade": fade, "direction": direction, "color1": color1, "color2": color2,
         # Répartition du décalage entre fixtures : linéaire (chenillard),
         # miroir, pair/impair… « lineaire » = comportement historique.
         "spread_mode": spread_mode}
    if attr == "Pan/Tilt":
        d["mouvement_shape"] = shape
    if sym_pan:
        d["sym_pan"] = True
    return d


# ─── Effets prédéfinis ─────────────────────────────────────────────────────────

BUILTIN_EFFECTS = [
    # ── Strobe / Flash ────────────────────────────────────────────────────────
    {"name": "Strobe Classique",  "emoji": "⚡", "category": "Strobe / Flash", "type": "Strobe",
     "no_color": True,
     "layers": [_L("RGB", "Flash", speed=55, color1="#ffffff")]},

    {"name": "Strobe Lent",       "emoji": "⚡", "category": "Strobe / Flash", "type": "Strobe",
     "no_color": True,
     "layers": [_L("RGB", "Flash", speed=15, color1="#ffffff")]},

    {"name": "Strobe Rapide",     "emoji": "⚡", "category": "Strobe / Flash", "type": "Strobe",
     "no_color": True,
     "layers": [_L("RGB", "Flash", speed=90, color1="#ffffff")]},

    {"name": "Strobe Alternance", "emoji": "⚡", "category": "Strobe / Flash", "type": "Strobe",
     "no_color": True,
     "layers": [_L("RGB", "Flash", target="Pair",   speed=60, phase=0,  color1="#ffffff"),
                _L("RGB", "Flash", target="Impair", speed=60, phase=50, color1="#ffffff")]},

    {"name": "Flash Couleur",     "emoji": "◉", "category": "Strobe / Flash", "type": "Flash",
     "no_color": True,
     "layers": [_L("RGB", "Montée", speed=50, color1="#ff6600")]},

    {"name": "Flash Blanc",       "emoji": "◉", "category": "Strobe / Flash", "type": "Flash",
     "no_color": True,
     "layers": [_L("RGB", "Montée", speed=55, color1="#ffffff")]},

    # ── Mouvement ─────────────────────────────────────────────────────────────
    {"name": "Chase Blanc",       "emoji": "→", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Flash", speed=50, spread=180, color1="#ffffff")]},

    {"name": "Chase Rapide",      "emoji": "→", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Flash", speed=96, spread=180, color1="#ffffff")]},

    {"name": "Chase Retour",      "emoji": "←", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=50, spread=180, color1="#ffffff")]},

    {"name": "Chase Doux",        "emoji": "→", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Triangle", speed=40, spread=180, fade=35, color1="#ffffff")]},

    {"name": "Passage Blanc",     "emoji": "🌊", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Triangle", speed=22, spread=180, color1="#ffffff")]},

    {"name": "Comète",            "emoji": "☄", "category": "Mouvement", "type": "Comete",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=65, size=100, spread=180, color1="#ffffff")]},

    {"name": "Comète Colorée",    "emoji": "☄", "category": "Mouvement", "type": "Comete",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=65, size=100, spread=180, color1="#00aaff")]},

    # ── Ambiance ──────────────────────────────────────────────────────────────
    {"name": "Pulse Doux",        "emoji": "∿", "category": "Ambiance", "type": "Pulse",
     "no_color": True,
     "layers": [_L("RGB", "Sinus", speed=15, color1="#ffffff")]},

    {"name": "Pulse Rapide",      "emoji": "∿", "category": "Ambiance", "type": "Pulse",
     "no_color": True,
     "layers": [_L("RGB", "Sinus", speed=92, color1="#ffffff")]},

    {"name": "Pulse Décalé",      "emoji": "∿", "category": "Ambiance", "type": "Pulse",
     "no_color": True,
     "layers": [_L("RGB", "Sinus", speed=40, spread=90, color1="#ffffff")]},

    {"name": "Vague",             "emoji": "≈", "category": "Ambiance", "type": "Wave",
     "no_color": True,
     "layers": [_L("RGB", "Sinus", speed=40, spread=180, color1="#ffffff")]},

    # ── Couleur ───────────────────────────────────────────────────────────────
    {"name": "Rainbow",           "emoji": "◈", "category": "Couleur", "type": "Rainbow",
     "layers": [_L("R", "Sinus", speed=45, spread=180, phase=0),
                _L("V", "Sinus", speed=45, spread=180, phase=33),
                _L("B", "Sinus", speed=45, spread=180, phase=66)]},

    {"name": "Rainbow Rapide",    "emoji": "◈", "category": "Couleur", "type": "Rainbow",
     "layers": [_L("R", "Sinus", speed=85, spread=180, phase=0),
                _L("V", "Sinus", speed=85, spread=180, phase=33),
                _L("B", "Sinus", speed=85, spread=180, phase=66)]},

    {"name": "Feu",               "emoji": "▲", "category": "Couleur", "type": "Fire",
     "no_color": True,
     "layers": [_L("R", "Audio", speed=50, size=80),
                _L("V", "Audio", speed=50, size=20)]},

    # ── Spécial ───────────────────────────────────────────────────────────────
    {"name": "Bascule",           "emoji": "⇄", "category": "Spécial", "type": "Bascule",
     "no_color": True,
     "layers": [_L("RGB", "Flash", target="Pair",   speed=20, phase=0,  color1="#ff3300"),
                _L("RGB", "Flash", target="Impair", speed=20, phase=50, color1="#0033ff")]},

    # ── Nouveaux : Strobe / Flash ─────────────────────────────────────────────
    {"name": "Strobe Couleur",    "emoji": "⚡", "category": "Strobe / Flash", "type": "Strobe",
     "layers": [_L("Strobe", "Flash", speed=55),
                _L("R", "Sinus", speed=55, size=70, phase=0),
                _L("V", "Sinus", speed=55, size=70, phase=33),
                _L("B", "Sinus", speed=55, size=70, phase=66)]},

    {"name": "Blinder",           "emoji": "◎", "category": "Strobe / Flash", "type": "Flash",
     "layers": [_L("Dimmer", "Flash", speed=30, size=100),
                _L("Strobe", "Flash", speed=30, size=100)]},

    # ── Nouveaux : Mouvement ──────────────────────────────────────────────────
    {"name": "Ping Pong",         "emoji": "⇔", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Triangle", speed=38, spread=180, direction=0, color1="#ffffff")]},

    {"name": "Escalier",          "emoji": "↗", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Montée", speed=55, spread=180, direction=1, color1="#ffffff")]},

    # ── Répartitions : chases symétriques et à traînée ────────────────────────
    # Pensés pour les barres à pixels, mais valables sur 8 PAR : un pixel est
    # une fixture comme une autre.
    {"name": "Comète",            "emoji": "☄", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=45, spread=360, fade=45,
                   color1="#ffffff")]},

    {"name": "Miroir",            "emoji": "⇹", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=45, spread=180, fade=30,
                   spread_mode="miroir_in", color1="#ffffff")]},

    {"name": "Miroir Comète",     "emoji": "⋈", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=40, spread=360, fade=50,
                   spread_mode="miroir_in", color1="#ffffff")]},

    {"name": "Explosion",         "emoji": "✷", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=45, spread=180, fade=40,
                   spread_mode="miroir", color1="#ffffff")]},

    {"name": "Alterné",           "emoji": "⇵", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Flash", speed=45, spread=180,
                   spread_mode="pair_impair", color1="#ffffff")]},

    # Aller-retour : direction=0 fait osciller la base de temps, le chase
    # remonte donc de 8 vers 1 après être allé de 1 à 8.
    {"name": "Va-et-vient",       "emoji": "⇋", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Flash", speed=42, spread=180, direction=0,
                   color1="#ffffff")]},

    {"name": "Va-et-vient Comète", "emoji": "⤿", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=38, spread=360, fade=45,
                   direction=0, color1="#ffffff")]},

    {"name": "Scan",              "emoji": "↕", "category": "Mouvement", "type": "Chase",
     "no_color": True,
     "layers": [_L("Pan", "Triangle", speed=22, size=75),
                _L("RGB", "Fixe",     size=90, color1="#ffffff")]},

    # ── Nouveaux : Ambiance ───────────────────────────────────────────────────
    {"name": "Respiration",       "emoji": "∿", "category": "Ambiance", "type": "Pulse",
     "no_color": True,
     "layers": [_L("RGB", "Sinus", speed=10, color1="#ffffff")]},

    {"name": "Bougie",            "emoji": "✦", "category": "Ambiance", "type": "Pulse",
     "no_color": True,
     "layers": [_L("RGB", "Audio", speed=35, size=65, color1="#ff6600"),
                _L("RGB", "Fixe",  size=80,  color1="#ff6600")]},

    {"name": "Scintillement",     "emoji": "✧", "category": "Ambiance", "type": "Pulse",
     "no_color": True,
     "layers": [_L("RGB", "Audio", speed=88, size=100, spread=180, color1="#ffffff")]},

    # ── Nouveaux : Couleur ────────────────────────────────────────────────────
    {"name": "Police",            "emoji": "◈", "category": "Couleur", "type": "Bascule",
     "no_color": True,
     "layers": [_L("R", "Flash", speed=48, phase=0),
                _L("B", "Flash", speed=48, phase=50)]},

    {"name": "RGB Chase",         "emoji": "◈", "category": "Couleur", "type": "Chase",
     "layers": [_L("R", "Flash", speed=50, spread=180, phase=0),
                _L("V", "Flash", speed=50, spread=180, phase=33),
                _L("B", "Flash", speed=50, spread=180, phase=66)]},

    {"name": "Disco",             "emoji": "🪩", "category": "Couleur", "type": "Fire",
     "no_color": True,
     "layers": [_L("R", "Audio", speed=75, size=100),
                _L("V", "Audio", speed=75, size=100),
                _L("B", "Audio", speed=75, size=100)]},

    # ── Couleur custom ──────────────────────────────────────────────────────────
    {"name": "Violet Pulsé",      "emoji": "🟣", "category": "Couleur", "type": "Pulse",
     "layers": [_L("RGB", "Sinus", speed=25, size=100, color1="#8800ff")]},

    {"name": "Rose Flash",        "emoji": "🌸", "category": "Couleur", "type": "Strobe",
     "layers": [_L("RGB", "Flash", speed=40, spread=75, color1="#ff0080")]},

    {"name": "Amber Pulse",       "emoji": "🟡", "category": "Couleur", "type": "Pulse",
     "layers": [_L("RGB", "Sinus", speed=20, size=100, color1="#ffaa00")]},

    {"name": "Cyan Vague",        "emoji": "🌊", "category": "Couleur", "type": "Wave",
     "layers": [_L("RGB", "Sinus", speed=30, size=90, spread=110, color1="#00ffee")]},

    {"name": "Orange Chase",      "emoji": "🔶", "category": "Couleur", "type": "Chase",
     "layers": [_L("RGB", "Flash", speed=38, spread=90, color1="#ff5500")]},

    {"name": "Magenta Chase",     "emoji": "💗", "category": "Couleur", "type": "Chase",
     "layers": [_L("RGB", "Flash", speed=38, spread=90, color1="#ff00cc")]},

    {"name": "Blanc Strobe",      "emoji": "⬜", "category": "Couleur", "type": "Strobe",
     "layers": [_L("RGB", "Flash", speed=55, size=100, color1="#ffffff")]},

    {"name": "Nuit Bleue",        "emoji": "🌙", "category": "Couleur", "type": "Pulse",
     "layers": [_L("RGB", "Sinus", speed=12, size=70, color1="#001aff")]},

    {"name": "Vert Jungle",       "emoji": "🌿", "category": "Couleur", "type": "Pulse",
     "layers": [_L("RGB", "Sinus", speed=18, size=85, color1="#00cc44")]},

    {"name": "Spectre",           "emoji": "🌈", "category": "Couleur", "type": "Rainbow",
     "no_color": True,
     "layers": [_L("R", "Sinus", speed=20, spread=180, phase=0),
                _L("V", "Sinus", speed=20, spread=180, phase=33),
                _L("B", "Sinus", speed=20, spread=180, phase=66)]},

    # ── Nouveaux : Spécial ────────────────────────────────────────────────────
    {"name": "Explosion",         "emoji": "💥", "category": "Spécial", "type": "Flash",
     "no_color": True,
     "layers": [_L("RGB", "Descente", speed=18, size=100, color1="#ffffff"),
                _L("RGB", "Flash",    speed=92, size=80,  color1="#ffffff")]},

    {"name": "Matrix",            "emoji": "⬛", "category": "Spécial", "type": "Pulse",
     "layers": [_L("V",      "Audio",   speed=70, size=100, spread=180),
                _L("Dimmer", "Audio",   speed=70, size=80,  spread=180)]},

    # ── Strobe Couleurs ───────────────────────────────────────────────────────
    {"name": "Strobe Bleu",      "emoji": "💙", "category": "Strobe / Flash", "type": "Strobe",
     "layers": [_L("RGB", "Flash", speed=55, color1="#0033ff")]},

    {"name": "Strobe Vert",      "emoji": "💚", "category": "Strobe / Flash", "type": "Strobe",
     "layers": [_L("RGB", "Flash", speed=55, color1="#00dd00")]},

    {"name": "Strobe Rouge",     "emoji": "❤️",  "category": "Strobe / Flash", "type": "Strobe",
     "layers": [_L("RGB", "Flash", speed=55, color1="#ff0000")]},

    {"name": "Strobe Mémoire",   "emoji": "🔦", "category": "Strobe / Flash", "type": "Strobe",
     "layers": [_L("Strobe", "Flash", speed=55)]},  # intentionnel : utilise la couleur en place

    # ── Chase Couleurs ────────────────────────────────────────────────────────
    {"name": "Chase Rouge",  "emoji": "🔴", "category": "Mouvement", "type": "Chase",
     "layers": [_L("RGB", "Flash", speed=45, spread=145, color1="#ff0000")]},

    {"name": "Chase Vert",   "emoji": "🟢", "category": "Mouvement", "type": "Chase",
     "layers": [_L("RGB", "Flash", speed=45, spread=145, color1="#00dd00")]},

    {"name": "Chase Bleu",   "emoji": "🔵", "category": "Mouvement", "type": "Chase",
     "layers": [_L("RGB", "Flash", speed=45, spread=145, color1="#0033ff")]},

    # ── Permut ────────────────────────────────────────────────────────────────
    {"name": "Permut Rouge & Rose",    "emoji": "🌹", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=35, color1="#ff0000", color2="#ff0080")]},

    {"name": "Permut Bleu & Cyan",     "emoji": "🩵", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=35, color1="#0033ff", color2="#00ffff")]},

    {"name": "Permut Vert & Jaune",    "emoji": "💛", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=35, color1="#00dd00", color2="#ffee00")]},

    {"name": "Permut Violet & Blanc",  "emoji": "💜", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=35, color1="#8800ff", color2="#ffffff")]},

    {"name": "Permut Orange & Rouge",  "emoji": "🔶", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=35, color1="#ff6600", color2="#ff0000")]},

    {"name": "Permut Custom",          "emoji": "🎨", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=35, color1="#ff0000", color2="#0000ff")]},

    {"name": "Permut Rose & Blanc",    "emoji": "🌸", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=30, color1="#ff44aa", color2="#ffffff")]},

    {"name": "Permut Rouge & Or",      "emoji": "🌟", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=40, color1="#ff0000", color2="#ffaa00")]},

    {"name": "Permut Cyan & Blanc",    "emoji": "🌊", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=35, color1="#00ffee", color2="#ffffff")]},

    {"name": "Permut Feu",             "emoji": "🔥", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=45, color1="#ff2200", color2="#ff8800")]},

    {"name": "Permut Lent",            "emoji": "🌙", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Sinus", speed=15, color1="#4400ff", color2="#ff0066")]},

    {"name": "Permut Rapide",          "emoji": "⚡", "category": "Permut", "type": "Permut",
     "layers": [_L("Permut", "Flash", speed=70, color1="#ff0000", color2="#0000ff")]},

    # ── Lyre : mouvement + dimmer synchro ─────────────────────────────────────
    {"name": "Lyre Cercle",        "emoji": "⭕", "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus", speed=22, size=65, shape="cercle"),
                _L("Dimmer",   "Sinus", speed=22, size=100)]},          # pulse 1×/tour

    {"name": "Lyre Figure 8",      "emoji": "∞",  "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus", speed=20, size=70, shape="huit"),
                _L("Dimmer",   "Sinus", speed=20, size=100)]},

    {"name": "Lyre Infini",        "emoji": "🌀", "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus", speed=18, size=75, shape="infini"),
                _L("Dimmer",   "Sinus", speed=18, size=100)]},

    {"name": "Lyre Balancier",     "emoji": "↔",  "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus", speed=20, size=80, shape="balancier"),
                _L("Dimmer",   "Sinus", speed=20, size=100, phase=50)]}, # plein au centre

    {"name": "Lyre Pendule",       "emoji": "↕",  "category": "Lyre", "type": "Tilt",
     "layers": [_L("Pan/Tilt", "Sinus", speed=18, size=70, shape="pendule"),
                _L("Dimmer",   "Sinus", speed=18, size=100, phase=50)]}, # plein en bas

    {"name": "Lyre Carré",         "emoji": "□",  "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Triangle", speed=25, size=65, shape="carre"),
                _L("Dimmer",   "Fixe",     size=100)]},                  # toujours allumé

    {"name": "Lyre Sweep",         "emoji": "→",  "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan",    "Sinus", speed=25, size=80),
                _L("Dimmer", "Fixe",  size=100)]},

    {"name": "Lyre Rush",          "emoji": "⚡", "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus", speed=70, size=55, shape="cercle"),
                _L("Dimmer",   "Flash", speed=70, size=100)]},           # strobe sur le cercle rapide

    # ── Lyre : déphasage entre fixtures ───────────────────────────────────────
    {"name": "Lyre Vague",         "emoji": "≈",  "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan",    "Sinus", speed=20, size=70, spread=180),
                _L("Dimmer", "Sinus", speed=20, size=100, spread=180)]}, # vague pan + lumière

    {"name": "Lyre Canon",         "emoji": "💥", "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan",    "Sinus",  speed=30, size=65, spread=180),
                _L("Dimmer", "Montée", speed=30, size=100, spread=180)]},# chaque lyre tire dans la foulée

    {"name": "Lyre Spiral",        "emoji": "🔄", "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus", speed=22, size=60, spread=125, shape="cercle"),
                _L("Dimmer",   "Sinus", speed=22, size=100, spread=125)]},# cercles décalés + lumière

    {"name": "Lyre Pendule Décalé","emoji": "↕",  "category": "Lyre", "type": "Tilt",
     "layers": [_L("Pan/Tilt", "Sinus", speed=16, size=65, spread=145, shape="pendule"),
                _L("Dimmer",   "Sinus", speed=16, size=100, spread=145, phase=50)]},

    # ── Lyre : haché / stroboscopique ─────────────────────────────────────────
    {"name": "Lyre Cercle Haché",  "emoji": "✦",  "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus", speed=20, size=62, shape="cercle"),
                _L("Dimmer",   "Flash", speed=40, size=100)]},           # flash 2× par tour

    {"name": "Lyre Pendule Haché", "emoji": "✂",  "category": "Lyre", "type": "Tilt",
     "layers": [_L("Pan/Tilt", "Sinus", speed=18, size=65, shape="pendule"),
                _L("Dimmer",   "Flash", speed=36, size=100)]},           # flash synco balancier

    {"name": "Lyre Pendule Lent",  "emoji": "↕",  "category": "Lyre", "type": "Tilt",
     "layers": [_L("Tilt",   "Sinus", speed=10, size=60, direction=0),
                _L("Dimmer", "Sinus", speed=10, size=100, phase=50)]},

    # ── Lyre : avec couleur ────────────────────────────────────────────────────
    {"name": "Lyre Cercle + Couleur", "emoji": "🎨", "category": "Lyre", "type": "Pan",
     "no_color": True,
     "layers": [_L("Pan/Tilt", "Sinus", speed=22, size=65, shape="cercle"),
                _L("Dimmer",   "Sinus", speed=22, size=100),
                _L("RGB",      "Sinus", speed=15, size=100, color1="#00aaff")]},

    # ── Lyre : gobo ───────────────────────────────────────────────────────────
    {"name": "Lyre Gobo Spin",     "emoji": "🎯", "category": "Lyre", "type": "Gobo",
     "layers": [_L("Gobo",   "Flash", speed=40, spread=15),
                _L("Dimmer", "Fixe",  size=100)]},

    {"name": "Lyre Gobo + Cercle", "emoji": "🎪", "category": "Lyre", "type": "Gobo",
     "layers": [_L("Pan/Tilt", "Sinus", speed=18, size=55, shape="cercle"),
                _L("Dimmer",   "Sinus", speed=18, size=100),
                _L("Gobo",     "Flash", speed=35, spread=75)]},

    # ── Lyre : symétrie ───────────────────────────────────────────────────────
    {"name": "Lyre Papillon",        "emoji": "🦋", "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus",    speed=22, size=65, shape="cercle",    sym_pan=True),
                _L("Dimmer",   "Sinus",    speed=22, size=100)]},                # cercles en miroir

    {"name": "Lyre Éventail",        "emoji": "↔",  "category": "Lyre", "type": "Pan",
     "layers": [_L("Pan/Tilt", "Sinus",    speed=18, size=70, shape="balancier", sym_pan=True),
                _L("Dimmer",   "Sinus",    speed=18, size=100, phase=50)]},      # balanciers miroir

    # ── Lyre : roue de couleurs ───────────────────────────────────────────────
    {"name": "Lyre Roue Couleurs",   "emoji": "🎨", "category": "Lyre", "type": "ColorWheel",
     "layers": [_L("ColorWheel", "Montée", speed=20, size=100),
                _L("Dimmer",     "Fixe",   size=100)]},

    {"name": "Lyre CW + Cercle",     "emoji": "🌈", "category": "Lyre", "type": "ColorWheel",
     "layers": [_L("Pan/Tilt",   "Sinus",  speed=18, size=55, shape="cercle"),
                _L("ColorWheel", "Montée", speed=12, size=100),
                _L("Dimmer",     "Sinus",  speed=18, size=100)]},
]


# ─── Constantes ───────────────────────────────────────────────────────────────

ATTR_ORDER = ["Dimmer", "R", "V", "B", "W", "Ambre", "Pan", "Tilt", "Pan/Tilt", "Zoom", "Gobo", "ColorWheel", "Strobe"]

FIXTURE_ATTRS = {
    "Trad":        ["Dimmer"],
    "PAR LED":     ["Dimmer", "R", "V", "B", "W", "Ambre", "Strobe"],
    "Barre LED":   ["Dimmer", "R", "V", "B", "W", "Ambre"],
    "Moving Head": ["Dimmer", "R", "V", "B", "W", "Ambre", "Pan", "Tilt", "Pan/Tilt", "Zoom", "Gobo", "ColorWheel", "Strobe"],
    "Lyre":        ["Dimmer", "R", "V", "B", "W", "Ambre", "Pan", "Tilt", "Pan/Tilt", "Zoom", "Gobo", "ColorWheel", "Strobe"],
    "Strobe":      ["Dimmer", "Strobe"],
    "Generic":     ["Dimmer", "R", "V", "B", "W", "Ambre"],
}

# Liste complète toujours disponible dans le dropdown (indépendante du type de fixture)
ATTR_ALL = ["Dimmer", "R", "V", "B", "W", "Ambre", "RGB", "Permut",
            "Pan", "Tilt", "Pan/Tilt", "Zoom", "Gobo", "ColorWheel", "Strobe"]

FORMES = ["Sinus", "Flash", "Triangle", "Montée", "Descente", "Audio", "Fixe", "Off"]

# Formes de trajectoire pour les lyres (Pan/Tilt couplés mathématiquement)
# Chaque forme : {"pan": (forme, phase 0-100, speed_mult), "tilt": (forme, phase, speed_mult)}
# phase 25 = décalage de 90°, speed_mult 2.0 = vitesse double
# Compensation physique du ratio pan/tilt : le PAN d'une lyre couvre ~540° pour
# ~270° de TILT. À amplitude DMX égale, le pan balaie 2× plus d'angle → un
# « cercle » se projette en « 8 » (et le pan qui fait 1,5 tour repasse au centre).
# On réduit donc l'amplitude PAN de moitié pour que pan et tilt couvrent le même
# angle → vrai cercle à amplitude max. (Ajustable si vos lyres ont un autre ratio.)
PAN_ANGULAR_RATIO = 0.5

PAN_TILT_SHAPES = {
    "cercle":    {"label": "○  Cercle",     "pan": ("Sinus",    0,  1.0), "tilt": ("Sinus",    25, 1.0)},
    "huit":      {"label": "8  Huit",       "pan": ("Sinus",    0,  1.0), "tilt": ("Sinus",     0, 2.0)},
    "infini":    {"label": "∞  Infini",     "pan": ("Sinus",    0,  2.0), "tilt": ("Sinus",     0, 1.0)},
    "balancier": {"label": "↔  Balancier",  "pan": ("Sinus",    0,  1.0), "tilt": (None,        0, 1.0)},
    "pendule":   {"label": "↕  Pendule",    "pan": (None,       0,  1.0), "tilt": ("Sinus",     0, 1.0)},
    "carre":     {"label": "□  Carré",      "pan": ("Triangle", 0,  1.0), "tilt": ("Triangle", 25, 1.0)},
    "libre":     {"label": "~  Libre",      "pan": (None,       0,  1.0), "tilt": (None,        0, 1.0)},
}
_PT_SHAPE_ORDER = ["cercle", "huit", "infini", "balancier", "pendule", "carre", "libre"]

# Migration des anciens noms (fichiers .tui sauvegardés avant la refonte)
_FORME_COMPAT = {
    "Chase": "Flash", "Phase 1": "Montée", "Phase 2": "Descente",
    "Phase 3": "Triangle", "Sinusoïdale": "Sinus",
    "Toujours au max": "Fixe", "Toujours au min": "Off",
    "Son": "Audio", "Pause": "Fixe",
}

CIBLES_PRESET = ["Tous"]
GROUPES       = ["A", "B", "C", "D", "E", "F", "G"]


# ─── Styles ───────────────────────────────────────────────────────────────────

_COMBO_STYLE = """
    QComboBox {
        background: #232323; color: #ddd;
        border: 1px solid #333; border-radius: 4px;
        padding: 4px 8px; font-size: 12px; min-height: 26px;
    }
    QComboBox:hover { border-color: #00d4ff; }
    QComboBox::drop-down { border: none; width: 16px; }
    QComboBox QAbstractItemView {
        background: #232323; color: #ddd; border: 1px solid #00d4ff;
        selection-background-color: #00d4ff;
        selection-color: #000; outline: none;
    }
"""

_DIALOG_STYLE = """
    QDialog  { background: #0d0d0d; }
    QWidget  { font-family: 'Segoe UI', Arial, sans-serif; color: #ddd; }
    QLabel   { border: none; }
    QFrame   { border: none; }
    QToolTip {
        color: #ffffff; background-color: #1e1e1e;
        border: 1px solid #555; border-radius: 4px; padding: 4px 8px;
        font-size: 11px;
    }
""" + _COMBO_STYLE

# ─── Paramètres "magiques" par type d'effet ────────────────────────────────

_MAGIC_PARAMS = {
    "Strobe":  {"key": "spread", "label": "DÉCALAGE",        "hint": "Ensemble ↔ Alternance"},
    "Flash":   {"key": "spread", "label": "DÉCALAGE",        "hint": "Ensemble ↔ Alternance"},
    "Chase":   {"key": "spread", "label": "ÉTALEMENT",       "hint": "Serré ↔ Étalé"},
    "Pulse":   {"key": "spread", "label": "DÉCALAGE",        "hint": "Ensemble ↔ Vague"},
    "Wave":    {"key": "spread", "label": "LONGUEUR D'ONDE", "hint": "Court ↔ Long"},
    "Rainbow": {"key": "spread", "label": "LARGEUR",         "hint": "Étroit ↔ Large"},
    "Fire":    {"key": "spread", "label": "VARIATION",       "hint": "Synchrone ↔ Aléatoire"},
    "Bascule": {"key": "phase",  "label": "DÉCALAGE PHASE",  "hint": "0° ↔ 180°"},
    "Comete":  {"key": "spread", "label": "TRAÎNE",          "hint": "Courte ↔ Longue"},
}

_SLIDER_STYLE = """
    QSlider::groove:horizontal {
        background: #1a1a1a; height: 4px; border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #00d4ff; width: 14px; height: 14px;
        margin: -5px 0; border-radius: 7px; border: 2px solid #0d0d0d;
    }
    QSlider::sub-page:horizontal {
        background: #00d4ff; height: 4px; border-radius: 2px;
    }
    QSlider::handle:horizontal:disabled { background: #2a2a2a; border-color: #1a1a1a; }
    QSlider::sub-page:horizontal:disabled { background: #1e1e1e; }
"""

_COMBO_STYLE_COMPACT = """
    QComboBox {
        background: #151515; color: #aaa;
        border: 1px solid #252525; border-radius: 4px;
        padding: 1px 6px; font-size: 10px;
    }
    QComboBox:hover { border-color: #00d4ff; }
    QComboBox::drop-down { border: none; width: 12px; }
    QComboBox QAbstractItemView {
        background: #1a1a1a; color: #ccc; border: 1px solid #00d4ff;
        selection-background-color: #003344; selection-color: #00d4ff;
        outline: none; font-size: 10px;
    }
"""


# ─── Modèle de données ────────────────────────────────────────────────────────

class EffectLayer:
    """Données d'une couche d'effet (sérialisé en dict JSON dans LightClip)."""

    def __init__(self):
        self.attribute     = "Dimmer"
        self.forme         = "Sinus"
        self.target_preset = "Tous"
        self.target_groups = []
        self.speed     = 50    # vitesse du cycle 0-100
        self.size      = 100   # amplitude 0-100
        self.spread    = 0     # décalage de phase entre fixtures 0-100
        self.phase     = 0     # décalage global de phase 0-100 (0=no shift, 50=½ cycle, 100=full cycle)
        self.fade      = 0     # adoucissement de la forme 0=dur 100=doux
        self.direction = 1     # sens : 1=avant, -1=arrière, 0=bounce
        self.min_val   = 0     # plancher de sortie 0-100
        self.max_val   = 100   # plafond de sortie 0-100
        self.color1 = "#ff0000"
        self.color2 = "#0000ff"
        self.mouvement_shape = "libre"  # forme de trajectoire Pan/Tilt
        self.sym_pan = False            # miroir pan sur la 2e moitié des fixtures
        # Répartition du décalage entre fixtures (voir SPREAD_MODES) :
        # "lineaire" = chenillard 1,2,3… ; "miroir_in" = 1&8, 2&7, 3&6…
        self.spread_mode = "lineaire"

    def to_dict(self):
        return {
            "attribute":     self.attribute,
            "forme":         self.forme,
            "target_preset": self.target_preset,
            "target_groups": list(self.target_groups),
            "speed":     self.speed,
            "size":      self.size,
            "spread":    self.spread,
            "phase":     self.phase,
            "fade":      self.fade,
            "direction": self.direction,
            "min_val":   self.min_val,
            "max_val":   self.max_val,
            "color1": self.color1,
            "color2": self.color2,
            "mouvement_shape": self.mouvement_shape,
            "sym_pan": self.sym_pan,
            "spread_mode": self.spread_mode,
        }

    @classmethod
    def from_dict(cls, d):
        layer = cls()
        layer.attribute     = d.get("attribute",     "Dimmer")
        forme               = d.get("forme",         "Sinus")
        layer.forme         = _FORME_COMPAT.get(forme, forme)
        if layer.forme not in FORMES:
            layer.forme = "Sinus"
        layer.target_preset = d.get("target_preset", "Tous")
        layer.target_groups = list(d.get("target_groups", []))
        layer.speed     = d.get("speed",  50)
        layer.size      = d.get("size",   d.get("amplitude", 100))
        layer.spread    = d.get("spread", 0)
        layer.phase     = d.get("phase",  0)
        layer.fade      = d.get("fade",   0)
        layer.direction = d.get("direction", 1)
        layer.min_val   = d.get("min_val", 0)
        layer.max_val   = d.get("max_val", 100)
        layer.color1 = d.get("color1", "#ff0000")
        layer.color2 = d.get("color2", "#0000ff")
        layer.mouvement_shape = d.get("mouvement_shape", "libre")
        layer.sym_pan = d.get("sym_pan", False)
        layer.spread_mode = d.get("spread_mode", "lineaire")
        return layer

    @classmethod
    def layers_from_builtin(cls, eff: dict) -> list:
        result = []
        for ld in eff.get("layers", []):
            layer = cls()
            layer.attribute     = ld.get("attribute",     "Dimmer")
            layer.forme         = ld.get("forme",         "Sinus")
            layer.target_preset = ld.get("target_preset", "Tous")
            layer.target_groups = list(ld.get("target_groups", []))
            layer.speed     = ld.get("speed",  50)
            layer.size      = ld.get("size",   100)
            layer.spread    = ld.get("spread", 0)
            layer.phase     = ld.get("phase",  0)
            layer.fade      = ld.get("fade",   0)
            layer.direction = ld.get("direction", 1)
            layer.min_val   = ld.get("min_val", 0)
            layer.max_val   = ld.get("max_val", 100)
            layer.color1 = ld.get("color1", "#ff0000")
            layer.color2 = ld.get("color2", "#0000ff")
            layer.mouvement_shape = ld.get("mouvement_shape", "libre")
            layer.sym_pan = ld.get("sym_pan", False)
            layer.spread_mode = ld.get("spread_mode", "lineaire")
            result.append(layer)
        return result


# ─── Potard rotatif ───────────────────────────────────────────────────────────

class RotaryKnob(QWidget):
    """Potard rotatif. Glisser verticalement ou molette. Range configurable via max_val."""

    valueChanged = Signal(int)
    _S  = 54
    _LH = 16

    def __init__(self, label="", default=50, size=None, parent=None, max_val=100):
        super().__init__(parent)
        if size is not None:
            self._S  = size
            self._LH = max(14, size // 4)
        self._max    = max_val
        self._value  = max(0, min(self._max, default))
        self._label  = label
        self._drag_y = None
        self._drag_v = None
        self.setFixedSize(self._S, self._S + self._LH)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(f"{label}: {self._value}")

    @property
    def value(self):
        return self._value

    def set_value(self, v):
        v = max(0, min(self._max, int(v)))
        if v != self._value:
            self._value = v
            self.setToolTip(f"{self._label}: {v}")
            self.valueChanged.emit(v)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_y = e.globalPosition().y()
            self._drag_v = self._value

    def mouseMoveEvent(self, e):
        if self._drag_y is not None:
            # Sensibilité adaptée : 1px = max/100 unités (cohérent quelle que soit la plage)
            delta = int((self._drag_y - e.globalPosition().y()) * self._max / 100)
            self.set_value(self._drag_v + delta)

    def mouseReleaseEvent(self, _e):
        self._drag_y = None

    def mouseDoubleClickEvent(self, _e):
        self.set_value(self._max)

    def wheelEvent(self, e):
        step = max(1, self._max // 100)
        self.set_value(self._value + (step if e.angleDelta().y() > 0 else -step))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        S, cx, cy = self._S, self._S // 2, self._S // 2
        r = S // 2 - 5

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#1c1c1c")))
        p.drawEllipse(cx - S//2 + 2, cy - S//2 + 2, S - 4, S - 4)

        rect = QRect(cx - r, cy - r, r * 2, r * 2)
        p.setPen(QPen(QColor("#2e2e2e"), 5, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, 225 * 16, -270 * 16)

        if self._value > 0:
            p.setPen(QPen(QColor("#00d4ff"), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, 225 * 16, int(-270 * 16 * self._value / self._max))

        ang = math.radians(225.0 - 270.0 * self._value / self._max)
        dr  = r - 1
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#00d4ff")))
        p.drawEllipse(QPoint(int(cx + dr * math.cos(ang)),
                             int(cy - dr * math.sin(ang))), 4, 4)

        # Affichage valeur + suffixe "°" si max=360
        val_str = f"{self._value}°" if self._max == 360 else str(self._value)
        p.setPen(QPen(QColor("#ffffff")))
        p.setFont(QFont("Segoe UI", 8 if self._max == 360 else 9, QFont.Bold))
        p.drawText(QRect(0, cy - 9, S, 18), Qt.AlignCenter, val_str)

        p.setPen(QPen(QColor("#666")))
        p.setFont(QFont("Segoe UI", 7))
        p.drawText(QRect(0, S + 1, S, self._LH - 1), Qt.AlignCenter, self._label)
        p.end()


# ─── Sélecteur de cible ───────────────────────────────────────────────────────

class TargetSelector(QWidget):
    """Tous / Pair / Impair  +  Groupes A-G (multi-sélection)."""

    changed = Signal()

    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self._layer = layer
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        row1 = QHBoxLayout()
        row1.setSpacing(2)
        self._preset_btns = {}
        for p in CIBLES_PRESET:
            btn = QPushButton(p)
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(lambda _=False, pp=p: self._on_preset(pp))
            self._preset_btns[p] = btn
            row1.addWidget(btn)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(2)
        self._group_btns = {}
        for g in GROUPES:
            btn = QPushButton(g)
            btn.setCheckable(True)
            btn.setFixedSize(24, 22)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(lambda _=False, gg=g: self._on_group(gg))
            self._group_btns[g] = btn
            row2.addWidget(btn)
        row2.addStretch()
        layout.addLayout(row2)
        self._refresh_ui()

    def _btn_style(self):
        return """
            QPushButton {
                background: #222; color: #888;
                border: 1px solid #333; border-radius: 3px;
                font-size: 10px; padding: 0 2px;
            }
            QPushButton:checked {
                background: #00d4ff; color: #000;
                font-weight: bold; border-color: #00d4ff;
            }
            QPushButton:hover:!checked { background: #2e2e2e; }
        """

    def _on_preset(self, preset):
        self._layer.target_preset = preset
        self._layer.target_groups = []
        self._refresh_ui()
        self.changed.emit()

    def _on_group(self, group):
        if group in self._layer.target_groups:
            self._layer.target_groups.remove(group)
        else:
            self._layer.target_groups.append(group)
        self._layer.target_preset = "" if self._layer.target_groups else "Tous"
        self._refresh_ui()
        self.changed.emit()

    def _refresh_ui(self):
        for preset, btn in self._preset_btns.items():
            btn.blockSignals(True)
            btn.setChecked(preset == self._layer.target_preset)
            btn.blockSignals(False)
        for g, btn in self._group_btns.items():
            btn.blockSignals(True)
            btn.setChecked(g in self._layer.target_groups)
            btn.blockSignals(False)


# ─── Icônes de formes d'onde ──────────────────────────────────────────────────

def _make_shape_icon(forme: str, w: int = 56, h: int = 26):
    from PySide6.QtGui import QPixmap, QIcon
    px = QPixmap(w, h)
    px.fill(QColor("#1e1e1e"))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)

    mg = 3
    pw, ph = w - 2 * mg, h - 2 * mg - 1

    def pt(xn, yn):
        return QPoint(int(mg + xn * pw), int(mg + (1.0 - max(0.0, min(1.0, yn))) * ph))

    def draw(pts, color="#00d4ff", dash=False):
        style = Qt.DashLine if dash else Qt.SolidLine
        p.setPen(QPen(QColor(color), 1.5, style, Qt.RoundCap, Qt.RoundJoin))
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])

    N = 64

    if forme == "Sinus":
        pts = [pt(i/N, (1 + math.sin(i/N * 2*math.pi * 2.5)) / 2) for i in range(N+1)]
        draw(pts)

    elif forme == "Flash":
        pts = [pt(i/N, 1.0 if (int(i/N * 4) % 2 == 0) else 0.0) for i in range(N+1)]
        draw(pts)

    elif forme == "Triangle":
        pts = [pt(i/N, 1.0 - abs(2 * ((i/N * 3) % 1.0) - 1)) for i in range(N+1)]
        draw(pts)

    elif forme == "Montée":
        pts = [pt(i/N, (i/N * 3) % 1.0) for i in range(N+1)]
        draw(pts)

    elif forme == "Descente":
        pts = [pt(i/N, 1.0 - (i/N * 3) % 1.0) for i in range(N+1)]
        draw(pts)

    elif forme == "Audio":
        rng = _rnd.Random(7)
        y, pts = 0.5, []
        for i in range(N+1):
            y = max(0.05, min(0.95, y + rng.uniform(-0.22, 0.22)))
            pts.append(pt(i/N, y))
        draw(pts, color="#ff8800")

    elif forme == "Fixe":
        draw([pt(0, 1.0), pt(1, 1.0)])

    elif forme == "Off":
        draw([pt(0, 0.0), pt(1, 0.0)], color="#555")

    p.end()
    return QIcon(px)


_SHAPE_ICONS: dict = {}

def _get_shape_icon(forme: str):
    if forme not in _SHAPE_ICONS:
        _SHAPE_ICONS[forme] = _make_shape_icon(forme)
    return _SHAPE_ICONS[forme]


# ─── Ligne d'une couche ───────────────────────────────────────────────────────

class EffectLayerRow(QFrame):
    """Une couche : [⠿] CANAL | FORME | CIBLE | Vitesse Taille Décalage Phase [✕]"""

    delete_requested = Signal(object)
    changed          = Signal()

    def __init__(self, layer: EffectLayer, fixture_types: list, parent=None):
        super().__init__(parent)
        self.layer          = layer
        self._fixture_types = fixture_types or ["PAR LED"]

        self.setFixedHeight(132)
        self.setObjectName("EffectLayerRow")
        self.setStyleSheet("""
            QFrame#EffectLayerRow {
                background: #181818;
                border: 1px solid #272727;
                border-radius: 8px;
            }
            QFrame#EffectLayerRow:hover { border-color: #333; }
        """)

        main = QHBoxLayout(self)
        main.setContentsMargins(10, 8, 10, 8)
        main.setSpacing(10)

        grip = QLabel("⠿")
        grip.setStyleSheet("color: #2e2e2e; font-size: 18px;")
        grip.setFixedWidth(14)
        main.addWidget(grip)

        # 1) Canal
        col_a = self._col("CANAL")
        self.attr_combo = QComboBox()
        self.attr_combo.setFixedWidth(100)
        self.attr_combo.setStyleSheet(_COMBO_STYLE)
        self._fill_attrs()
        self.attr_combo.currentTextChanged.connect(
            lambda t: (setattr(self.layer, 'attribute', t), self.changed.emit()))
        col_a.addWidget(self.attr_combo)
        col_a.addStretch()
        main.addLayout(col_a)
        main.addWidget(self._vsep())

        # 2) Forme
        col_f = self._col("FORME")
        self.forme_combo = QComboBox()
        self.forme_combo.setFixedWidth(155)
        self.forme_combo.setIconSize(QSize(56, 24))
        self.forme_combo.setStyleSheet(_COMBO_STYLE + """
            QComboBox { min-height: 30px; padding: 2px 6px; }
            QComboBox QAbstractItemView::item { min-height: 30px; }
        """)
        for f in FORMES:
            self.forme_combo.addItem(_get_shape_icon(f), f)
        idx = self.forme_combo.findText(layer.forme)
        self.forme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.forme_combo.currentTextChanged.connect(
            lambda t: (setattr(self.layer, 'forme', t), self.changed.emit()))
        col_f.addWidget(self.forme_combo)
        col_f.addStretch()
        main.addLayout(col_f)
        main.addWidget(self._vsep())

        # 3) Cible
        col_c = self._col("CIBLE")
        self.target_sel = TargetSelector(layer)
        self.target_sel.changed.connect(self.changed)
        col_c.addWidget(self.target_sel)
        col_c.addStretch()
        main.addLayout(col_c)
        main.addWidget(self._vsep())

        # 4) Potards : Vitesse / Taille / Décalage / Phase
        col_k = self._col("PARAMÈTRES")
        k_row = QHBoxLayout()
        k_row.setSpacing(8)
        self.k_speed  = RotaryKnob("Vitesse",  layer.speed)
        self.k_size   = RotaryKnob("Taille",   layer.size)
        self.k_spread = RotaryKnob("Décalage", layer.spread, max_val=360)
        self.k_phase  = RotaryKnob("Phase",    layer.phase)
        self.k_speed.valueChanged.connect( lambda v: (setattr(layer, 'speed',  v), self.changed.emit()))
        self.k_size.valueChanged.connect(  lambda v: (setattr(layer, 'size',   v), self.changed.emit()))
        self.k_spread.valueChanged.connect(lambda v: (setattr(layer, 'spread', v), self.changed.emit()))
        self.k_phase.valueChanged.connect( lambda v: (setattr(layer, 'phase',  v), self.changed.emit()))
        for k in (self.k_speed, self.k_size, self.k_spread, self.k_phase):
            k_row.addWidget(k)
        col_k.addLayout(k_row)
        col_k.addStretch()
        main.addLayout(col_k)
        main.addStretch()

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #444;
                border: 1px solid #333; border-radius: 11px; font-size: 10px;
            }
            QPushButton:hover { color: #ff5555; border-color: #ff5555; }
        """)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self))
        main.addWidget(del_btn, alignment=Qt.AlignTop | Qt.AlignRight)

    def _col(self, title):
        col = QVBoxLayout()
        col.setSpacing(4)
        col.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(title)
        lbl.setStyleSheet("color: #444; font-size: 8px; font-weight: bold;")
        col.addWidget(lbl)
        return col

    def _vsep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: #242424;")
        return sep

    def _fill_attrs(self):
        self.attr_combo.clear()
        for a in ATTR_ALL:
            self.attr_combo.addItem(a)
        idx = self.attr_combo.findText(self.layer.attribute)
        self.attr_combo.setCurrentIndex(idx if idx >= 0 else 0)


# ─── Ligne compacte de couche supplémentaire ───────────────────────────────────

class _CompactLayerRow(QFrame):
    """Couche supplémentaire complète : [Cible] [Attr] [Forme] [→←↔] [×]"""

    deleted = Signal(object)
    changed = Signal()

    _ATTRS   = ["Dimmer", "R", "V", "B", "W", "Ambre", "UV", "RGB", "Permut",
                "Pan", "Tilt", "Pan/Tilt", "Zoom", "Gobo", "Strobe"]
    _FORMES  = ["Sinus", "Flash", "Triangle", "Montée", "Descente", "Audio", "Fixe"]
    _CIBLES  = ["Tous", "A", "B", "C", "D", "E", "F", "G"]
    _SENS    = [(1, "→"), (-1, "←"), (0, "↔")]

    _SENS_BTN_STYLE = """
        QPushButton {{
            background: {bg}; color: {fg};
            border: 1px solid {bd}; border-radius: 3px;
            font-size: 10px; font-weight: bold;
        }}
        QPushButton:hover {{ background: #1a1a1a; }}
    """

    def __init__(self, layer: EffectLayer, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.setFixedHeight(38)
        self.setObjectName("CLR")
        self.setStyleSheet("""
            QFrame#CLR {
                background: #0e0e0e;
                border: 1px solid #1e1e1e;
                border-radius: 6px;
            }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 6, 0)
        lay.setSpacing(5)

        # ── Cible ─────────────────────────────────────────────────────────────
        self._cible = QComboBox()
        self._cible.addItems(self._CIBLES)
        cur_cible = layer.target_preset if layer.target_preset in self._CIBLES else (
            layer.target_groups[0] if layer.target_groups else "Tous"
        )
        self._cible.setCurrentText(cur_cible)
        self._cible.setFixedSize(58, 22)
        self._cible.setStyleSheet(_COMBO_STYLE_COMPACT)
        self._cible.currentTextChanged.connect(self._on_cible)
        lay.addWidget(self._cible)

        # ── Attr ──────────────────────────────────────────────────────────────
        self._attr = QComboBox()
        self._attr.addItems(self._ATTRS)
        self._attr.setCurrentText(layer.attribute)
        self._attr.setFixedSize(60, 22)
        self._attr.setStyleSheet(_COMBO_STYLE_COMPACT)
        self._attr.currentTextChanged.connect(self._on_attr)
        lay.addWidget(self._attr)

        # ── Forme ─────────────────────────────────────────────────────────────
        self._forme = QComboBox()
        self._forme.addItems(self._FORMES)
        t = layer.forme if layer.forme in self._FORMES else "Sinus"
        self._forme.setCurrentText(t)
        self._forme.setFixedSize(76, 22)
        self._forme.setStyleSheet(_COMBO_STYLE_COMPACT)
        self._forme.currentTextChanged.connect(self._on_forme)
        lay.addWidget(self._forme)

        # ── Sens ──────────────────────────────────────────────────────────────
        self._sens_btns = {}
        sens_layout = QHBoxLayout()
        sens_layout.setSpacing(2)
        sens_layout.setContentsMargins(0, 0, 0, 0)
        for val, sym in self._SENS:
            btn = QPushButton(sym)
            btn.setFixedSize(22, 22)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setChecked(val == getattr(layer, 'direction', 1))
            self._sens_btns[val] = btn
            btn.clicked.connect(lambda _=False, v=val: self._on_sens(v))
            sens_layout.addWidget(btn)
        self._refresh_sens_style()
        lay.addLayout(sens_layout)

        lay.addStretch()

        # ── Supprimer ─────────────────────────────────────────────────────────
        del_btn = QPushButton("×")
        del_btn.setFixedSize(20, 20)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet("""
            QPushButton {
                background: #1a0808; color: #5a2222;
                border: 1px solid #2a1212; border-radius: 4px;
                font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background: #2a1010; color: #ff5555; border-color: #551111; }
        """)
        del_btn.clicked.connect(lambda: self.deleted.emit(self))
        lay.addWidget(del_btn)

    def _refresh_sens_style(self):
        cur = getattr(self.layer, 'direction', 1)
        for val, btn in self._sens_btns.items():
            if val == cur:
                ss = self._SENS_BTN_STYLE.format(bg="#001a2a", fg="#00d4ff", bd="#004466")
            else:
                ss = self._SENS_BTN_STYLE.format(bg="#111", fg="#333", bd="#1e1e1e")
            btn.setStyleSheet(ss)

    def _on_cible(self, v):
        if v in ("Tous", "Pair", "Impair"):
            self.layer.target_preset = v
            self.layer.target_groups = []
        else:
            self.layer.target_preset = ""
            self.layer.target_groups = [v]
        self.changed.emit()

    def _on_attr(self, v):
        self.layer.attribute = v
        self.changed.emit()

    def _on_forme(self, v):
        self.layer.forme = v
        self.changed.emit()

    def _on_sens(self, val: int):
        self.layer.direction = val
        for v, btn in self._sens_btns.items():
            btn.blockSignals(True)
            btn.setChecked(v == val)
            btn.blockSignals(False)
        self._refresh_sens_style()
        self.changed.emit()


# ─── Symboles de formes ───────────────────────────────────────────────────────

_FORME_SYMBOLS = {
    "Sinus":    "∿",
    "Flash":    "⌇",
    "Triangle": "△",
    "Montée":   "↗",
    "Descente": "↘",
    "Audio":    "♪",
    "Fixe":     "━",
}

# ─── Roue de couleurs ─────────────────────────────────────────────────────────

class ColorWheel(QWidget):
    """Roue de couleurs compacte (Hue + Saturation). Valeur fixée à 1.0."""

    colorChanged = Signal(QColor)

    def __init__(self, color=None, parent=None):
        super().__init__(parent)
        c = color or QColor("#ff0000")
        h = c.hsvHueF()
        self._hue = max(0.0, h)
        self._sat = c.hsvSaturationF()
        self._dragging = False
        self._R = 52
        d = self._R * 2 + 8
        self.setFixedSize(d, d)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip("Cliquer / glisser pour choisir la couleur")

    # ── Accès couleur ─────────────────────────────────────────────────────────

    def color(self) -> QColor:
        return QColor.fromHsvF(self._hue, self._sat, 1.0)

    def set_color(self, c: QColor):
        h = c.hsvHueF()
        self._hue = max(0.0, h)
        self._sat = c.hsvSaturationF()
        self.update()

    # ── Conversion position ↔ HS ──────────────────────────────────────────────

    def _cx(self): return self.width() // 2
    def _cy(self): return self.height() // 2

    def _pos_to_hs(self, x, y):
        dx = x - self._cx()
        dy = y - self._cy()
        dist = math.sqrt(dx * dx + dy * dy)
        sat = min(1.0, dist / self._R)
        hue = (math.atan2(-dy, dx) / (2 * math.pi)) % 1.0
        return hue, sat

    def _hs_to_pos(self):
        angle = self._hue * 2 * math.pi
        dist = self._sat * self._R
        return self._cx() + dist * math.cos(angle), self._cy() - dist * math.sin(angle)

    # ── Souris ────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._update_from_pos(e.position().x(), e.position().y())

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._update_from_pos(e.position().x(), e.position().y())

    def mouseReleaseEvent(self, _e):
        self._dragging = False

    def _update_from_pos(self, x, y):
        h, s = self._pos_to_hs(x, y)
        self._hue = h
        self._sat = s
        self.update()
        self.colorChanged.emit(self.color())

    # ── Peinture ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = self._cx(), self._cy(), self._R

        # ── Dégradé conique (teintes) ──────────────────────────────────────
        cg = QConicalGradient(cx, cy, 0)
        hue_stops = [
            (0/6, QColor(255, 0,   0)),
            (1/6, QColor(255, 255, 0)),
            (2/6, QColor(0,   255, 0)),
            (3/6, QColor(0,   255, 255)),
            (4/6, QColor(0,   0,   255)),
            (5/6, QColor(255, 0,   255)),
            (1.0, QColor(255, 0,   0)),
        ]
        for pos, col in hue_stops:
            cg.setColorAt(pos, col)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(cg))
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # ── Dégradé radial blanc (saturation) ─────────────────────────────
        rg = QRadialGradient(cx, cy, r)
        rg.setColorAt(0, QColor(255, 255, 255, 255))
        rg.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(rg))
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # ── Bordure ───────────────────────────────────────────────────────
        p.setPen(QPen(QColor("#1a1a1a"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # ── Curseur ───────────────────────────────────────────────────────
        px, py = self._hs_to_pos()
        sel = self.color()
        # Halo sombre si couleur claire
        lum = 0.2126 * sel.redF() + 0.7152 * sel.greenF() + 0.0722 * sel.blueF()
        ring_col = QColor("#000000") if lum > 0.5 else QColor("#ffffff")
        p.setPen(QPen(ring_col, 2))
        p.setBrush(QBrush(sel))
        p.drawEllipse(int(px - 6), int(py - 6), 12, 12)


# ─── Prévisualisation mini fixtures ───────────────────────────────────────────

class MiniFixturePreview(QWidget):
    """Barre animée : N colonnes colorées représentant les fixtures en temps réel."""

    def __init__(self, n=8, parent=None):
        super().__init__(parent)
        self._n      = max(1, n)
        self._levels = [0.0] * self._n
        self._colors = [QColor(255, 255, 255)] * self._n
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_levels(self, levels: list, colors: list):
        n = min(len(levels), len(colors))
        if n == 0:
            return
        self._n      = n
        self._levels = list(levels[:n])
        self._colors = list(colors[:n])
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mg, gap = 3, 2
        n = self._n
        bar_w = max(3, (w - 2 * mg - (n - 1) * gap) // n)
        inner_h = h - 2 * mg

        for i in range(n):
            level = max(0.0, min(1.0, self._levels[i] if i < len(self._levels) else 0.0))
            color = self._colors[i] if i < len(self._colors) else QColor(255, 255, 255)
            x = mg + i * (bar_w + gap)

            # Slot de fond
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(18, 18, 18))
            p.drawRoundedRect(x, mg, bar_w, inner_h, 2, 2)

            # Barre colorée
            bar_h = max(0, int(inner_h * level))
            if bar_h > 0:
                c = QColor(color)
                # Dégradé lumineux : fond sombre, haut coloré
                grad_y = mg + inner_h - bar_h
                from PySide6.QtGui import QLinearGradient
                grad = QLinearGradient(x, grad_y, x, mg + inner_h)
                grad.setColorAt(0, c)
                dark = QColor(int(c.red() * 0.25), int(c.green() * 0.25), int(c.blue() * 0.25))
                grad.setColorAt(1, dark)
                p.setBrush(QBrush(grad))
                p.drawRoundedRect(x, grad_y, bar_w, bar_h, 2, 2)
        p.end()


# ─── Fonction d'onde (module-level) ──────────────────────────────────────────

def _layer_wave(forme: str, x: float) -> float:
    """Valeur 0-1 de la forme pour position x dans le cycle."""
    if forme == "Sinus":      return (math.sin(2 * math.pi * x) + 1) / 2
    elif forme == "Flash":    return 1.0 if x < 0.5 else 0.0
    elif forme == "Triangle": return 1.0 - abs(2 * x - 1)
    elif forme == "Montée":   return x
    elif forme == "Descente": return 1.0 - x
    elif forme == "Fixe":     return 1.0
    return 0.0


# ─── Waveform Canvas ──────────────────────────────────────────────────────────

class WaveformCanvas(QWidget):
    """Courbe animée (~110×30 px) pour une couche — mise à jour via set_time()."""

    _ATTR_COLORS = {
        "Dimmer": "#00d4ff", "Strobe": "#cccccc",
        "R": "#ff4444",      "V": "#44dd44",    "B": "#4488ff",
        "RGB": "#ffaa44",    "Permut": "#ff44ff",
        "Pan": "#ffaa00",    "Tilt": "#ff8800",  "Gobo": "#aa44ff",
        "Pan/Tilt": "#ff9900",
    }

    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self._layer = layer
        self._t     = 0.0
        self.setFixedSize(110, 30)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_time(self, t: float):
        self._t = t
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mg = 3

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(8, 8, 8))
        p.drawRoundedRect(0, 0, w, h, 3, 3)

        layer  = self._layer
        N      = w - 2 * mg
        freq   = 0.05 + layer.speed / 100.0 * 7.0
        fade_f = getattr(layer, 'fade', 0) / 100.0
        attr   = layer.attribute

        if attr == "RGB":
            col = QColor(getattr(layer, 'color1', '#ffffff'))
        elif attr == "Permut":
            col = QColor(getattr(layer, 'color1', '#ff44ff'))
        else:
            col = QColor(self._ATTR_COLORS.get(attr, "#00d4ff"))

        pts = []
        for xi in range(N):
            xn = xi / max(N - 1, 1)
            x  = (freq * self._t + xn * 2) % 1.0
            if layer.forme == "Audio":
                rng = _rnd.Random(int(self._t * 12) * 100 + xi)
                raw = max(0.0, min(1.0, 0.5 + rng.uniform(-0.4, 0.4)))
            else:
                raw = _layer_wave(layer.forme, x)
            if fade_f > 0:
                sin_v = (math.sin(2 * math.pi * x) + 1) / 2
                raw   = raw * (1 - fade_f) + sin_v * fade_f
            min_v = getattr(layer, 'min_val', 0) / 100.0
            max_v = getattr(layer, 'max_val', 100) / 100.0
            scaled = min_v + raw * (max_v - min_v)
            y = mg + int((1.0 - scaled) * (h - 2 * mg))
            pts.append(QPoint(mg + xi, y))

        if pts:
            p.setPen(QPen(col, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            for i in range(len(pts) - 1):
                p.drawLine(pts[i], pts[i + 1])
        p.end()


# ─── Trajectoire Lissajous Pan/Tilt ──────────────────────────────────────────

class TrajectoryCanvas(QWidget):
    """Aperçu Lissajous 34×34 px pour la couche Pan/Tilt — mis à jour via set_time()."""

    _COLOR = QColor(255, 153, 0)          # orange Pan/Tilt

    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self._layer = layer
        self._t     = 0.0
        self.setFixedSize(34, 34)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_time(self, t: float):
        self._t = t
        self.update()

    # ── tracé ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mg = 4

        # Fond
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(8, 8, 8))
        p.drawRoundedRect(0, 0, w, h, 3, 3)

        layer = self._layer
        sid   = getattr(layer, 'mouvement_shape', 'libre')
        sdef  = PAN_TILT_SHAPES.get(sid, PAN_TILT_SHAPES['libre'])
        pan_forme,  pan_ph,  pan_mult  = sdef.get('pan',  (None, 0, 1.0))
        tilt_forme, tilt_ph, tilt_mult = sdef.get('tilt', (None, 0, 1.0))

        inner_w = w - 2 * mg
        inner_h = h - 2 * mg

        # ── Mode "Libre" (les deux axes None) : croix centrale ───────────────
        if sid == 'libre' or (pan_forme is None and tilt_forme is None):
            cx, cy = w // 2, h // 2
            p.setPen(QPen(QColor("#2a2a2a"), 1))
            p.drawLine(mg, cy, w - mg, cy)
            p.drawLine(cx, mg, cx, h - mg)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#444444"))
            p.drawEllipse(cx - 2, cy - 2, 4, 4)
            p.end()
            return

        # Axe unique None → fixé au centre (0.5)
        def _pv(t_n): return _layer_wave(pan_forme,  (t_n * pan_mult  + pan_ph  / 100.0) % 1.0) if pan_forme  else 0.5
        def _tv(t_n): return _layer_wave(tilt_forme, (t_n * tilt_mult + tilt_ph / 100.0) % 1.0) if tilt_forme else 0.5

        # ── Calcul de la trajectoire (N points) ───────────────────────────────
        N   = 160
        pts = []
        for i in range(N + 1):
            t_n  = i / N                               # 0..1 période normalisée
            sx   = mg + _pv(t_n) * inner_w
            sy   = mg + (1.0 - _tv(t_n)) * inner_h    # axe Y inversé (haut = tilt max)
            pts.append(QPoint(int(sx), int(sy)))

        # Tracé fantôme (trajectoire complète, semi-transparent)
        trail_col = QColor(255, 153, 0, 55)
        p.setPen(QPen(trail_col, 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])

        # Axes de référence (très discrets)
        p.setPen(QPen(QColor(40, 40, 40, 120), 1, Qt.DotLine))
        cx, cy = w // 2, h // 2
        p.drawLine(mg, cy, w - mg, cy)
        p.drawLine(cx, mg, cx, h - mg)

        # ── Point animé ───────────────────────────────────────────────────────
        freq   = max(0.01, layer.speed / 100.0) * 2.0
        t_anim = self._t * freq
        ax  = int(mg + _pv(t_anim) * inner_w)
        ay  = int(mg + (1.0 - _tv(t_anim)) * inner_h)

        # Halo
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 153, 0, 60))
        p.drawEllipse(ax - 4, ay - 4, 8, 8)
        # Point vif
        p.setBrush(QColor(255, 220, 80))
        p.drawEllipse(ax - 2, ay - 2, 4, 4)

        p.end()


# ─── Aperçu Pan/Tilt (pad XY animé) ──────────────────────────────────────────

def _wave_at(t, speed, size, phase, direction, forme):
    """Retourne une valeur [0..1] (0.5 = centre) pour une couche à l'instant t."""
    freq = max(0.01, speed / 100.0) * 2.0
    t_adj = t * freq + phase / 100.0
    if forme == "Sinus":
        raw = math.sin(t_adj * math.pi * 2)
    elif forme == "Triangle":
        frac = t_adj % 1.0
        raw = 4 * frac - 1 if frac < 0.5 else 3 - 4 * frac
    elif forme == "Flash":
        raw = 1.0 if (t_adj % 1.0) < 0.5 else -1.0
    elif forme == "Montée":
        raw = (t_adj % 1.0) * 2 - 1
    elif forme == "Descente":
        raw = 1 - (t_adj % 1.0) * 2
    else:
        raw = 0.0
    d = direction if direction != 0 else 1
    return 0.5 + raw * d * (size / 100.0) * 0.5


class PanTiltLivePad(QWidget):
    """
    Pad XY interactif pour les couches Pan/Tilt d'un effet.
    - Tracé de la trajectoire complète
    - Point animé qui se déplace en temps réel
    - Centre draggable (stocké dans pan_layer.phase / tilt_layer.phase en tant qu'offset)
    - Sliders vitesse et amplitude
    """

    changed = Signal()
    deleted = Signal()   # demande de suppression des couches Pan/Tilt

    _W = 220
    _H = 170
    _M = 12

    _SL = """
        QSlider::groove:horizontal {
            background: #1a1a1a; height: 4px; border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: #00d4ff; border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #00d4ff; width: 10px; height: 10px;
            margin: -3px 0; border-radius: 5px;
        }
    """

    def __init__(self, pan_layer, tilt_layer, parent=None):
        super().__init__(parent)
        self._pan_l  = pan_layer   # EffectLayer ou None
        self._tilt_l = tilt_layer  # EffectLayer ou None
        self._t = 0.0
        self._base_speed = 50      # vitesse "slider" avant multiplicateurs
        # Centre de la trajectoire (0..255), draggable
        self._cx = 128
        self._cy = 128
        self._dragging = False
        self.setMouseTracking(True)

        pad_w = self._W + self._M * 2
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # ── Header : label PAN/TILT + sélecteur forme + bouton suppression ────
        shape_row = QHBoxLayout()
        shape_row.setContentsMargins(self._M, 0, self._M, 0)
        shape_row.setSpacing(6)
        shape_lbl = QLabel("PAN / TILT")
        shape_lbl.setStyleSheet(
            "color:#555; font-size:8px; font-weight:bold; letter-spacing:1px;"
        )
        shape_row.addWidget(shape_lbl)
        self._shape_cb = QComboBox()
        for sid in _PT_SHAPE_ORDER:
            self._shape_cb.addItem(PAN_TILT_SHAPES[sid]["label"], sid)
        self._shape_cb.setStyleSheet("""
            QComboBox {
                background: #1a1a1a; color: #ccc; border: 1px solid #333;
                border-radius: 3px; padding: 2px 6px; font-size: 11px;
            }
            QComboBox::drop-down { border: none; width: 18px; }
            QComboBox QAbstractItemView {
                background: #1a1a1a; color: #ccc; border: 1px solid #444;
                selection-background-color: #2a3a3a;
            }
        """)
        shape_row.addWidget(self._shape_cb, 1)

        self._sym_btn = QPushButton("SYM")
        self._sym_btn.setFixedSize(34, 18)
        self._sym_btn.setCheckable(True)
        self._sym_btn.setToolTip("Symétrie Pan : la 2e moitié des lyres se déplace en miroir")
        self._sym_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a1a; color: #555; border: 1px solid #333;
                border-radius: 3px; font-size: 8px; font-weight: bold; padding: 0;
            }
            QPushButton:checked {
                background: #002233; color: #00d4ff; border-color: #00d4ff66;
            }
        """)
        self._sym_btn.clicked.connect(self._on_sym_toggled)
        shape_row.addWidget(self._sym_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(18, 18)
        del_btn.setToolTip("Supprimer les couches Pan/Tilt")
        del_btn.setStyleSheet("""
            QPushButton {
                color: #555; background: transparent; border: none;
                font-size: 10px; font-weight: bold;
            }
            QPushButton:hover { color: #e05555; }
        """)
        del_btn.clicked.connect(self.deleted.emit)
        shape_row.addWidget(del_btn)
        outer.addLayout(shape_row)

        # Canvas du pad
        self._canvas = _PanTiltCanvas(self)
        self._canvas.setFixedSize(pad_w, self._H + self._M * 2)
        outer.addWidget(self._canvas)

        # Sliders vitesse / amplitude
        sl_row = QHBoxLayout()
        sl_row.setSpacing(12)
        sl_row.setContentsMargins(self._M, 0, self._M, 0)

        self._sl_speed, self._lbl_speed = self._mk_slider("VIT", 50)
        self._sl_amp,   self._lbl_amp   = self._mk_slider("AMP", 100)
        sl_row.addLayout(self._sl_speed_lay)
        sl_row.addLayout(self._sl_amp_lay)
        outer.addLayout(sl_row)

        self._sync_from_layers()

        self._sl_speed.valueChanged.connect(self._on_speed)
        self._sl_amp.valueChanged.connect(self._on_amp)
        self._shape_cb.currentIndexChanged.connect(self._on_shape_changed)

    def _mk_slider(self, label, val):
        lay = QVBoxLayout()
        lay.setSpacing(2)
        top = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet("color:#2a2a2a; font-size:7px; font-weight:bold; letter-spacing:1px;")
        top.addWidget(lbl)
        top.addStretch()
        vlbl = QLabel(str(val))
        vlbl.setStyleSheet("color:#444; font-size:9px; font-weight:bold;")
        vlbl.setFixedWidth(24)
        vlbl.setAlignment(Qt.AlignRight)
        top.addWidget(vlbl)
        lay.addLayout(top)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(1, 100)
        sl.setValue(val)
        sl.setFixedHeight(14)
        sl.setStyleSheet(self._SL)
        lay.addWidget(sl)
        # stockage temporaire pour récupérer dans __init__
        if label == "VIT":
            self._sl_speed_lay = lay
        else:
            self._sl_amp_lay = lay
        return sl, vlbl

    def _get_shape_def(self):
        """Retourne la définition de la forme courante."""
        sid = self._shape_cb.currentData() if hasattr(self, '_shape_cb') else "libre"
        return PAN_TILT_SHAPES.get(sid or "libre", PAN_TILT_SHAPES["libre"])

    def _apply_shape_to_layers(self, shape_def, base_speed=None):
        """Applique les formes/phases/vitesses de la shape_def aux couches Pan/Tilt."""
        spd = base_speed if base_speed is not None else self._base_speed
        pan_forme, pan_phase, pan_mult  = shape_def["pan"]
        tilt_forme, tilt_phase, tilt_mult = shape_def["tilt"]
        sid = self._shape_cb.currentData() if hasattr(self, '_shape_cb') else "libre"
        sym = self._sym_btn.isChecked() if hasattr(self, '_sym_btn') else False
        if self._pan_l:
            if pan_forme is not None:
                self._pan_l.forme = pan_forme
            self._pan_l.phase = pan_phase
            self._pan_l.speed = max(1, int(spd * pan_mult))
            self._pan_l.mouvement_shape = sid
            self._pan_l.sym_pan = sym
        if self._tilt_l:
            if tilt_forme is not None:
                self._tilt_l.forme = tilt_forme
            self._tilt_l.phase = tilt_phase
            self._tilt_l.speed = max(1, int(spd * tilt_mult))
            self._tilt_l.mouvement_shape = sid
            self._tilt_l.sym_pan = sym

    def _sync_from_layers(self):
        """Lit les valeurs des couches et met à jour les sliders + shape ComboBox."""
        l = self._pan_l or self._tilt_l
        if not l:
            return
        # Déduire la vitesse de base depuis la couche Pan (en inversant son multiplicateur)
        if hasattr(self, '_shape_cb'):
            sid = getattr(l, 'mouvement_shape', 'libre')
            if sid not in PAN_TILT_SHAPES:
                sid = 'libre'
            idx = _PT_SHAPE_ORDER.index(sid) if sid in _PT_SHAPE_ORDER else len(_PT_SHAPE_ORDER) - 1
            self._shape_cb.blockSignals(True)
            self._shape_cb.setCurrentIndex(idx)
            self._shape_cb.blockSignals(False)
            pan_mult = PAN_TILT_SHAPES[sid]["pan"][2]
            self._base_speed = max(1, int(l.speed / pan_mult)) if pan_mult > 0 else l.speed
        else:
            self._base_speed = l.speed
        if hasattr(self, '_sym_btn'):
            self._sym_btn.blockSignals(True)
            self._sym_btn.setChecked(getattr(l, 'sym_pan', False))
            self._sym_btn.blockSignals(False)
        self._sl_speed.blockSignals(True)
        self._sl_amp.blockSignals(True)
        self._sl_speed.setValue(max(1, self._base_speed))
        self._sl_amp.setValue(max(1, l.size))
        self._lbl_speed.setText(str(self._base_speed))
        self._lbl_amp.setText(str(l.size))
        self._sl_speed.blockSignals(False)
        self._sl_amp.blockSignals(False)

    def _on_sym_toggled(self, checked):
        """L'utilisateur a activé/désactivé la symétrie Pan."""
        if self._pan_l:
            self._pan_l.sym_pan = checked
        if self._tilt_l:
            self._tilt_l.sym_pan = checked
        self.changed.emit()

    def _on_shape_changed(self, _idx):
        """L'utilisateur a choisi une nouvelle forme de trajectoire."""
        shape_def = self._get_shape_def()
        self._apply_shape_to_layers(shape_def)
        self.changed.emit()
        self._canvas.update()

    def _on_speed(self, v):
        self._base_speed = v
        self._lbl_speed.setText(str(v))
        shape_def = self._get_shape_def()
        pan_mult  = shape_def["pan"][2]
        tilt_mult = shape_def["tilt"][2]
        if self._pan_l:
            self._pan_l.speed = max(1, int(v * pan_mult))
        if self._tilt_l:
            self._tilt_l.speed = max(1, int(v * tilt_mult))
        self.changed.emit()
        self._canvas.update()

    def _on_amp(self, v):
        self._lbl_amp.setText(str(v))
        for l in (self._pan_l, self._tilt_l):
            if l:
                l.size = v
        self.changed.emit()
        self._canvas.update()

    # ── API publique ────────────────────────────────────────────────────────
    def set_time(self, t: float):
        self._t = t
        self._canvas.update()

    def get_t(self):        return self._t
    def get_cx(self):       return self._cx
    def get_cy(self):       return self._cy
    def get_pan_layer(self): return self._pan_l
    def get_tilt_layer(self): return self._tilt_l

    # ── Souris (délégué au canvas) ──────────────────────────────────────────
    def on_canvas_press(self, pos):
        self._dragging = True
        self._move_center(pos)

    def on_canvas_move(self, pos):
        if self._dragging:
            self._move_center(pos)

    def on_canvas_release(self):
        self._dragging = False

    def on_canvas_double(self):
        self._cx, self._cy = 128, 128
        self._canvas.update()
        self.changed.emit()

    def _move_center(self, pos):
        m = self._M
        W, H = self._W, self._H
        fx = max(0.0, min(1.0, (pos.x() - m) / W))
        fy = max(0.0, min(1.0, (pos.y() - m) / H))
        self._cx = int(fx * 255)
        self._cy = int(fy * 255)
        self._canvas.update()
        self.changed.emit()


class _PanTiltCanvas(QWidget):
    """Canvas interne du PanTiltLivePad."""

    N_TRAJ = 120  # nombre de points pour le tracé

    def __init__(self, pad: 'PanTiltLivePad'):
        super().__init__(pad)
        self._pad = pad
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._pad.on_canvas_press(ev.position())

    def mouseMoveEvent(self, ev):
        self._pad.on_canvas_move(ev.position())

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._pad.on_canvas_release()

    def mouseDoubleClickEvent(self, ev):
        self._pad.on_canvas_double()

    def _to_px(self, fx, fy):
        m = self._pad._M
        W, H = self._pad._W, self._pad._H
        return int(m + fx * W), int(m + fy * H)

    def _traj_point(self, tf):
        pad = self._pad
        cx = pad.get_cx() / 255.0
        cy = pad.get_cy() / 255.0
        pl = pad.get_pan_layer()
        tl = pad.get_tilt_layer()
        if pl:
            xv = _wave_at(tf, pl.speed, pl.size, pl.phase, pl.direction, pl.forme)
            xv = cx + (xv - 0.5)
        else:
            xv = cx
        if tl:
            yv = _wave_at(tf, tl.speed, tl.size, tl.phase, tl.direction, tl.forme)
            yv = cy + (yv - 0.5)
        else:
            yv = cy
        return max(0.0, min(1.0, xv)), max(0.0, min(1.0, yv))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pad = self._pad
        m, W, H = pad._M, pad._W, pad._H

        # Fond
        p.fillRect(QRect(m, m, W, H), QColor("#0a0d14"))

        # Grille fine
        p.setPen(QPen(QColor("#141820"), 1))
        for i in range(1, 8):
            p.drawLine(m + i * W // 8, m, m + i * W // 8, m + H)
            p.drawLine(m, m + i * H // 8, m + W, m + i * H // 8)

        # Axe central du centre draggable
        cx_f = pad.get_cx() / 255.0
        cy_f = pad.get_cy() / 255.0
        cpx, cpy = self._to_px(cx_f, cy_f)
        p.setPen(QPen(QColor("#1e2235"), 1, Qt.DashLine))
        p.drawLine(cpx, m, cpx, m + H)
        p.drawLine(m, cpy, m + W, cpy)

        # Bordure
        p.setPen(QPen(QColor("#1a2a3a"), 1))
        p.drawRect(QRect(m, m, W, H))

        # ── Tracé de trajectoire (cycle complet fixe, ne bouge pas) ────────────
        N = self.N_TRAJ
        t_now = pad.get_t()
        l = pad.get_pan_layer() or pad.get_tilt_layer()
        freq = max(0.01, (l.speed if l else 50) / 100.0) * 2.0
        period = 1.0 / freq
        pts = [self._traj_point(i / N * period) for i in range(N + 1)]
        for i in range(N):
            col = QColor(0, 180, 255, 160)
            p.setPen(QPen(col, 1.5))
            x0, y0 = self._to_px(*pts[i])
            x1, y1 = self._to_px(*pts[i + 1])
            p.drawLine(x0, y0, x1, y1)

        # ── Centre draggable (croix orange) ─────────────────────────────────
        p.setPen(QPen(QColor("#cc6600"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRect(cpx - 5, cpy - 5, 10, 10))
        p.drawLine(cpx - 9, cpy, cpx + 9, cpy)
        p.drawLine(cpx, cpy - 9, cpx, cpy + 9)

        # ── Point animé (position actuelle) ────────────────────────────────
        dx, dy = self._traj_point(t_now)
        dpx, dpy = self._to_px(dx, dy)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 212, 255, 40))
        p.drawEllipse(QRect(dpx - 10, dpy - 10, 20, 20))
        p.setBrush(QColor(0, 212, 255, 230))
        p.drawEllipse(QRect(dpx - 4, dpy - 4, 8, 8))
        p.setPen(QPen(QColor("#00d4ff"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRect(dpx - 4, dpy - 4, 8, 8))

        # Labels valeurs actuelles
        p.setPen(QColor("#2a3050"))
        p.setFont(QFont("Segoe UI", 7))
        p.drawText(QRect(m + 2, m + 2, 60, 12), Qt.AlignLeft, f"Pan {int(dx * 255)}")
        p.drawText(QRect(m + W - 62, m + 2, 60, 12), Qt.AlignRight, f"Tilt {int(dy * 255)}")
        p.end()


# ─── Carte d'une couche ───────────────────────────────────────────────────────

class LayerCard(QFrame):
    """Couche d'effet : waveform animée + attr/forme/cible + 4 mini-potards + couleurs."""

    deleted = Signal(object)
    changed = Signal()
    pan_tilt_created = Signal()   # émis quand l'utilisateur passe la couche en Pan/Tilt

    _ATTRS  = ["Dimmer", "R", "V", "B", "W", "Ambre", "UV", "RGB", "Permut",
               "Pan", "Tilt", "Pan/Tilt", "Zoom", "Gobo", "Strobe"]
    _FORMES = ["Sinus", "Flash", "Triangle", "Montée", "Descente", "Audio", "Fixe", "Off"]
    _CIBLES = ["Tous", "A", "B", "C", "D", "E", "F", "G"]
    _ATTR_COLORS = WaveformCanvas._ATTR_COLORS

    _PARAM_STYLE = """
        QLabel { color: #2a2a2a; font-size: 7px; font-weight: bold; letter-spacing: 1px; }
    """

    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self.layer = layer
        self._build_ui()

    def _accent(self):
        return self._ATTR_COLORS.get(self.layer.attribute, "#333333")

    def _apply_frame_style(self):
        a = self._accent()
        self.setStyleSheet(f"""
            QFrame#LCard {{
                background: #111111;
                border: 1px solid #1c1c1c;
                border-left: 3px solid {a};
                border-radius: 7px;
            }}
            QFrame#LCard:hover {{ border-color: #252525; border-left-color: {a}; }}
        """)

    def _build_ui(self):
        self.setObjectName("LCard")
        self._apply_frame_style()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 7, 8, 7)
        outer.setSpacing(5)

        # ── Row 1 : Attr · Forme · Wave · Target · Colors · Del ───────────────
        row1 = QHBoxLayout()
        row1.setSpacing(5)

        self._attr_cb = QComboBox()
        self._attr_cb.addItems(self._ATTRS)
        self._attr_cb.setCurrentText(self.layer.attribute)
        self._attr_cb.setFixedSize(72, 22)
        self._attr_cb.setStyleSheet(_COMBO_STYLE_COMPACT)
        self._attr_cb.currentTextChanged.connect(self._on_attr)
        row1.addWidget(self._attr_cb)

        self._forme_cb = QComboBox()
        self._forme_cb.addItems(self._FORMES)
        t = self.layer.forme if self.layer.forme in self._FORMES else "Sinus"
        self._forme_cb.setCurrentText(t)
        self._forme_cb.setFixedSize(82, 22)
        self._forme_cb.setStyleSheet(_COMBO_STYLE_COMPACT)
        self._forme_cb.currentTextChanged.connect(self._on_forme)
        row1.addWidget(self._forme_cb)

        # Sélecteur trajectoire Pan/Tilt (visible uniquement si attr == "Pan/Tilt")
        self._shape_cb = QComboBox()
        for sid in _PT_SHAPE_ORDER:
            self._shape_cb.addItem(PAN_TILT_SHAPES[sid]["label"], sid)
        cur_shape = getattr(self.layer, 'mouvement_shape', 'libre')
        idx = _PT_SHAPE_ORDER.index(cur_shape) if cur_shape in _PT_SHAPE_ORDER else len(_PT_SHAPE_ORDER) - 1
        self._shape_cb.setCurrentIndex(idx)
        self._shape_cb.setFixedSize(120, 22)
        self._shape_cb.setStyleSheet(_COMBO_STYLE_COMPACT)
        self._shape_cb.currentIndexChanged.connect(self._on_shape_changed)
        row1.addWidget(self._shape_cb)

        self._wave = WaveformCanvas(self.layer)
        row1.addWidget(self._wave)

        self._pt_canvas = TrajectoryCanvas(self.layer)
        row1.addWidget(self._pt_canvas)

        # Visibilité initiale selon l'attribut
        is_pt = self.layer.attribute == "Pan/Tilt"
        self._forme_cb.setVisible(not is_pt)
        self._shape_cb.setVisible(is_pt)
        self._wave.setVisible(not is_pt)
        self._pt_canvas.setVisible(is_pt)

        row1.addStretch()

        # Boutons SENS
        _sens_style = (
            "QPushButton{{background:{bg};color:{fg};"
            "border:1px solid {bd};border-radius:3px;"
            "font-size:10px;font-weight:bold;}}"
            "QPushButton:hover{{border-color:#444;}}"
        )
        self._sens_btns = {}
        cur_dir = getattr(self.layer, 'direction', 1)
        # Le sens « ↔ » fait osciller la base de temps : le chase va de 1 à 8
        # PUIS revient de 8 à 1. Sans infobulle personne ne pouvait le deviner.
        _sens_tips = {
            1:  "Sens direct — 1, 2, 3… jusqu'à la dernière fixture",
            -1: "Sens inverse — de la dernière vers la première",
            0:  "Aller-retour — 1→8 puis 8→1, en boucle",
        }
        for dval, dlabel in [(1, "→"), (-1, "←"), (0, "↔")]:
            sb = QPushButton(dlabel)
            sb.setFixedSize(22, 22)
            sb.setCheckable(True)
            sb.setChecked(dval == cur_dir)
            sb.setToolTip(_sens_tips[dval])
            sb.setCursor(Qt.PointingHandCursor)
            on_ss  = _sens_style.format(bg="#001a2a", fg="#00d4ff", bd="#004466")
            off_ss = _sens_style.format(bg="#0c0c0c", fg="#444",    bd="#1c1c1c")
            sb.setStyleSheet(on_ss if dval == cur_dir else off_ss)
            sb.clicked.connect(lambda _=False, v=dval: self._on_sens(v))
            self._sens_btns[dval] = sb
            row1.addWidget(sb)

        self._col1_btn = QPushButton()
        self._col1_btn.setFixedSize(22, 22)
        self._col1_btn.setCursor(Qt.PointingHandCursor)
        self._col1_btn.clicked.connect(self._on_color1)
        row1.addWidget(self._col1_btn)

        self._col2_btn = QPushButton()
        self._col2_btn.setFixedSize(22, 22)
        self._col2_btn.setCursor(Qt.PointingHandCursor)
        self._col2_btn.clicked.connect(self._on_color2)
        row1.addWidget(self._col2_btn)

        del_btn = QPushButton("×")
        del_btn.setFixedSize(20, 20)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet("""
            QPushButton { background:#0d0606; color:#2e1010; border:1px solid #180c0c;
                          border-radius:4px; font-size:11px; font-weight:bold; }
            QPushButton:hover { color:#ff5555; border-color:#551111; background:#1a0808; }
        """)
        del_btn.clicked.connect(lambda: self.deleted.emit(self))
        row1.addWidget(del_btn)

        outer.addLayout(row1)

        # ── Row 2 : 2 sliders VITESSE / AMPLITUDE ───────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self._sl_speed, self._vl_speed = self._mk_slider("VIT", self.layer.speed)
        self._speed_container = self._slider_containers[-1]
        self._sl_amp,   self._vl_amp   = self._mk_slider("AMP", self.layer.size)

        self._sl_speed.valueChanged.connect(lambda v: (setattr(self.layer, 'speed', v), self._vl_speed.setText(str(v)), self.changed.emit()))
        self._sl_amp.valueChanged.connect(  lambda v: (setattr(self.layer, 'size',  v), self._vl_amp.setText(str(v)),   self.changed.emit()))

        for container in self._slider_containers:
            row2.addWidget(container, 1)

        outer.addLayout(row2)

        if self.layer.forme == "Fixe":
            self._speed_container.setEnabled(False)

        # ── Row 2b : MIN / MAX / DÉC (spread) ────────────────────────────────
        row2b = QHBoxLayout()
        row2b.setSpacing(10)
        self._slider_containers = []

        self._sl_min,    self._vl_min    = self._mk_slider("MIN", getattr(self.layer, 'min_val', 0))
        self._sl_max,    self._vl_max    = self._mk_slider("MAX", getattr(self.layer, 'max_val', 100))
        self._sl_spread, self._vl_spread = self._mk_slider("DÉC", self.layer.spread)
        # FADE adoucit la forme (0 = franc, 100 = fondu). Il était utilisé au
        # rendu et par plusieurs effets prédéfinis, mais n'avait aucun contrôle :
        # impossible de refaire une traînée de comète à la main.
        self._sl_fade,   self._vl_fade   = self._mk_slider("FONDU", getattr(self.layer, 'fade', 0))

        self._sl_min.valueChanged.connect(   lambda v: (setattr(self.layer, 'min_val', v), self._vl_min.setText(str(v)),    self.changed.emit()))
        self._sl_max.valueChanged.connect(   lambda v: (setattr(self.layer, 'max_val', v), self._vl_max.setText(str(v)),    self.changed.emit()))
        self._sl_spread.valueChanged.connect(lambda v: (setattr(self.layer, 'spread',  v), self._vl_spread.setText(str(v)), self.changed.emit()))
        self._sl_fade.valueChanged.connect(  lambda v: (setattr(self.layer, 'fade',    v), self._vl_fade.setText(str(v)),   self.changed.emit()))

        for container in self._slider_containers:
            row2b.addWidget(container, 1)

        outer.addLayout(row2b)

        # ── Row 2c : RÉPARTITION du décalage ─────────────────────────────────
        # Le curseur DÉC dit de COMBIEN les fixtures sont décalées ; ceci dit
        # DANS QUEL ORDRE. « Miroir (bords) » donne 1&8, puis 2&7, puis 3&6.
        row2c = QHBoxLayout()
        row2c.setSpacing(8)
        _lbl_sm = QLabel("RÉPARTITION")
        _lbl_sm.setStyleSheet("color:#666;font-size:9px;font-weight:bold;"
                              "letter-spacing:1px;background:transparent;border:none;")
        _lbl_sm.setFixedWidth(84)
        row2c.addWidget(_lbl_sm)

        self._cb_spread_mode = QComboBox()
        self._cb_spread_mode.setFixedHeight(26)
        self._cb_spread_mode.setStyleSheet(
            "QComboBox{background:#161616;color:#ddd;border:1px solid #2a2a2a;"
            "border-radius:4px;padding:2px 8px;font-size:11px;}"
            "QComboBox::drop-down{border:none;width:18px;}"
            "QComboBox QAbstractItemView{background:#161616;color:#ddd;"
            "selection-background-color:#00d4ff;selection-color:#000;"
            "border:1px solid #2a2a2a;}")
        for _key, _lbl, _hint in SPREAD_MODES:
            self._cb_spread_mode.addItem(_lbl, _key)
            self._cb_spread_mode.setItemData(
                self._cb_spread_mode.count() - 1, _hint, Qt.ToolTipRole)
        _cur_sm = getattr(self.layer, 'spread_mode', 'lineaire')
        _i_sm = next((k for k, (kk, _l, _h) in enumerate(SPREAD_MODES)
                      if kk == _cur_sm), 0)
        self._cb_spread_mode.setCurrentIndex(_i_sm)
        self._cb_spread_mode.setToolTip(SPREAD_MODES[_i_sm][2])

        self._spread_prev = SpreadPreview(8)
        self._spread_prev.set_mode(_cur_sm)
        self._spread_prev.setToolTip(
            "Ordre de démarrage des fixtures : même teinte = partent ensemble.")

        def _on_spread_mode(idx):
            key = self._cb_spread_mode.itemData(idx) or "lineaire"
            self.layer.spread_mode = key
            self._cb_spread_mode.setToolTip(
                next((h for k, _l, h in SPREAD_MODES if k == key), ""))
            self._spread_prev.set_mode(key)
            self.changed.emit()
        self._cb_spread_mode.currentIndexChanged.connect(_on_spread_mode)

        row2c.addWidget(self._cb_spread_mode, 1)
        row2c.addWidget(self._spread_prev, 1)

        # DÉPART : décalage temporel de CETTE couche. C'est lui qui décale le
        # rouge, le vert et le bleu dans les arcs-en-ciel prédéfinis — il était
        # utilisé au rendu sans aucun contrôle, donc ces effets n'étaient pas
        # reproductibles à la main.
        _lbl_ph = QLabel("DÉPART")
        _lbl_ph.setStyleSheet("color:#666;font-size:9px;font-weight:bold;"
                              "letter-spacing:1px;background:transparent;border:none;")
        _lbl_ph.setFixedWidth(52)
        row2c.addWidget(_lbl_ph)

        self._sl_phase = QSlider(Qt.Horizontal)
        self._sl_phase.setRange(0, 100)
        self._sl_phase.setValue(int(getattr(self.layer, 'phase', 0) or 0))
        self._sl_phase.setFixedWidth(96)
        self._sl_phase.setToolTip(
            "Décale le démarrage de cette couche dans le cycle.\n"
            "0 = en même temps que les autres, 33 = un tiers de cycle plus tard.\n"
            "C'est ainsi qu'on décale R, V et B pour obtenir un arc-en-ciel.")
        self._sl_phase.setStyleSheet(
            "QSlider::groove:horizontal{background:#222;height:4px;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#00d4ff;width:10px;height:10px;"
            "margin:-4px 0;border-radius:5px;}")
        self._vl_phase = QLabel(str(self._sl_phase.value()))
        self._vl_phase.setFixedWidth(24)
        self._vl_phase.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._vl_phase.setStyleSheet("color:#ddd;font-size:10px;font-weight:bold;"
                                     "background:transparent;border:none;")
        self._sl_phase.valueChanged.connect(
            lambda v: (setattr(self.layer, 'phase', v),
                       self._vl_phase.setText(str(v)),
                       self.changed.emit()))
        row2c.addWidget(self._sl_phase)
        row2c.addWidget(self._vl_phase)

        outer.addLayout(row2c)

        # ── Row 3 : Cible (pills multi-select) ────────────────────────────────
        row3 = QHBoxLayout()
        row3.setSpacing(3)

        _cible_on  = ("QPushButton{background:#001a2a;color:#00d4ff;border:1px solid #004466;"
                      "border-radius:3px;font-size:9px;font-weight:bold;padding:0 5px;}"
                      "QPushButton:hover{border-color:#006688;}")
        _cible_off = ("QPushButton{background:#0c0c0c;color:#444;border:1px solid #1c1c1c;"
                      "border-radius:3px;font-size:9px;font-weight:bold;padding:0 5px;}"
                      "QPushButton:hover{border-color:#333;color:#888;}")

        self._cible_btns = {}
        preset = self.layer.target_preset or "Tous"
        groups = self.layer.target_groups or []

        for label in ["Tous", "Pair", "Impair"]:
            btn = QPushButton(label)
            btn.setFixedHeight(20)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            active = (label == preset and not groups)
            btn.setChecked(active)
            btn.setStyleSheet(_cible_on if active else _cible_off)
            btn.clicked.connect(lambda _=False, v=label: self._on_cible_pill(v, preset=True))
            self._cible_btns[label] = btn
            row3.addWidget(btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("QFrame{background:#222;border:none;}")
        row3.addWidget(sep)

        for label in ["A", "B", "C", "D", "E", "F", "G", "H"]:
            btn = QPushButton(label)
            btn.setFixedSize(22, 20)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            active = (label in groups)
            btn.setChecked(active)
            btn.setStyleSheet(_cible_on if active else _cible_off)
            btn.clicked.connect(lambda _=False, v=label: self._on_cible_pill(v, preset=False))
            self._cible_btns[label] = btn
            row3.addWidget(btn)

        row3.addStretch()
        outer.addLayout(row3)

        self._refresh_color_btns()

    # Ce que règle chaque curseur, en clair. Les abréviations sur 3 lettres ne
    # disent rien à personne : « DÉC » est le réglage le plus puissant de
    # l'éditeur et le moins compréhensible sans explication.
    _SLIDER_TIPS = {
        "VIT":   "Vitesse du cycle.\n0 = très lent, 100 = très rapide.",
        "AMP":   "Amplitude : intensité maximale atteinte par l'effet.",
        "MIN":   "Niveau plancher : l'effet ne descend jamais en dessous.\n"
                 "Au-dessus de 0, les projecteurs ne s'éteignent plus complètement.",
        "MAX":   "Niveau plafond : l'effet ne monte jamais au-dessus.",
        "DÉC":   "Décalage entre fixtures — c'est lui qui crée le chenillard.\n"
                 "0 = toutes ensemble · 180 = réparties sur un cycle · "
                 "360 = deux motifs simultanés.\n"
                 "L'ORDRE des fixtures se choisit avec RÉPARTITION.",
        "FONDU": "Adoucit la forme.\n0 = transitions franches, 100 = fondu doux.\n"
                 "Combiné à la forme « Descente », c'est ce qui fait la traînée "
                 "d'une comète.",
    }

    def _mk_slider(self, label: str, val: int):
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        _tip = self._SLIDER_TIPS.get(label)
        if _tip:
            container.setToolTip(_tip)
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(1)

        top = QHBoxLayout()
        top.setSpacing(2)
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #2a2a2a; font-size: 7px; font-weight: bold; letter-spacing: 1px;")
        top.addWidget(lbl)
        top.addStretch()
        val_lbl = QLabel(str(val))
        val_lbl.setStyleSheet("color: #444; font-size: 9px; font-weight: bold;")
        val_lbl.setFixedWidth(24)
        val_lbl.setAlignment(Qt.AlignRight)
        top.addWidget(val_lbl)
        vl.addLayout(top)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(val)
        slider.setFixedHeight(14)
        slider.setStyleSheet(_SLIDER_STYLE)
        if _tip:
            slider.setToolTip(_tip)   # le survol du curseur lui-même compte
        vl.addWidget(slider)

        if not hasattr(self, '_slider_containers'):
            self._slider_containers = []
        self._slider_containers.append(container)

        return slider, val_lbl

    def set_time(self, t: float):
        self._wave.set_time(t)
        self._pt_canvas.set_time(t)

    def _on_attr(self, v: str):
        self.layer.attribute = v
        self._apply_frame_style()
        self._refresh_color_btns()
        is_pt = (v == "Pan/Tilt")
        self._forme_cb.setVisible(not is_pt)
        self._shape_cb.setVisible(is_pt)
        self._wave.setVisible(not is_pt)
        self._pt_canvas.setVisible(is_pt)
        if is_pt:
            self._on_shape_changed(self._shape_cb.currentIndex())
        self.changed.emit()
        if is_pt:
            # Mouvement créé à la main → le parent le rend visible & lent par défaut.
            self.pan_tilt_created.emit()

    def _on_shape_changed(self, _idx: int):
        sid = self._shape_cb.currentData() or "libre"
        self.layer.mouvement_shape = sid
        self._pt_canvas.update()
        self.changed.emit()

    def _on_forme(self, v: str):
        self.layer.forme = v
        self._speed_container.setEnabled(v != "Fixe")
        self.changed.emit()

    def _on_cible_pill(self, val: str, preset: bool):
        if preset:
            self.layer.target_preset = val
            self.layer.target_groups = []
        else:
            self.layer.target_preset = ""
            groups = list(self.layer.target_groups)
            if val in groups:
                groups.remove(val)
            else:
                groups.append(val)
            if not groups:
                self.layer.target_preset = "Tous"
            self.layer.target_groups = groups
        self._refresh_cible_btns()
        self.changed.emit()

    def _refresh_cible_btns(self):
        _on  = ("QPushButton{background:#001a2a;color:#00d4ff;border:1px solid #004466;"
                "border-radius:3px;font-size:9px;font-weight:bold;padding:0 5px;}"
                "QPushButton:hover{border-color:#006688;}")
        _off = ("QPushButton{background:#0c0c0c;color:#444;border:1px solid #1c1c1c;"
                "border-radius:3px;font-size:9px;font-weight:bold;padding:0 5px;}"
                "QPushButton:hover{border-color:#333;color:#888;}")
        preset = self.layer.target_preset or "Tous"
        groups = self.layer.target_groups or []
        for label, btn in self._cible_btns.items():
            if label in ("Tous", "Pair", "Impair"):
                active = (label == preset and not groups)
            else:
                active = (label in groups)
            btn.blockSignals(True)
            btn.setChecked(active)
            btn.setStyleSheet(_on if active else _off)
            btn.blockSignals(False)

    def _on_sens(self, val: int):
        self.layer.direction = val
        _on  = ("QPushButton{background:#001a2a;color:#00d4ff;border:1px solid #004466;"
                "border-radius:3px;font-size:10px;font-weight:bold;}"
                "QPushButton:hover{border-color:#444;}")
        _off = ("QPushButton{background:#0c0c0c;color:#444;border:1px solid #1c1c1c;"
                "border-radius:3px;font-size:10px;font-weight:bold;}"
                "QPushButton:hover{border-color:#444;}")
        for v, btn in self._sens_btns.items():
            btn.blockSignals(True)
            btn.setChecked(v == val)
            btn.setStyleSheet(_on if v == val else _off)
            btn.blockSignals(False)
        self.changed.emit()

    def _on_color1(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(
            QColor(getattr(self.layer, 'color1', '#ff0000')), self,
            "Couleur 1", QColorDialog.DontUseNativeDialog
        )
        if c.isValid():
            self.layer.color1 = c.name()
            self._refresh_color_btns()
            self.changed.emit()

    def _on_color2(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(
            QColor(getattr(self.layer, 'color2', '#0000ff')), self,
            "Couleur 2", QColorDialog.DontUseNativeDialog
        )
        if c.isValid():
            self.layer.color2 = c.name()
            self._refresh_color_btns()
            self.changed.emit()

    def _refresh_color_btns(self):
        attr = self.layer.attribute
        has_c1 = attr in ("RGB", "Permut")
        has_c2 = attr in ("Permut",)
        self._col1_btn.setVisible(has_c1)
        self._col2_btn.setVisible(has_c2)
        if has_c1:
            c1 = getattr(self.layer, 'color1', '#ff0000')
            self._col1_btn.setStyleSheet(
                f"QPushButton {{ background:{c1}; border:1px solid #333; border-radius:4px; }}"
                f"QPushButton:hover {{ border-color:#666; }}"
            )
            self._col1_btn.setToolTip(f"Couleur : {c1}")
        if has_c2:
            c2 = getattr(self.layer, 'color2', '#0000ff')
            self._col2_btn.setStyleSheet(
                f"QPushButton {{ background:{c2}; border:1px solid #333; border-radius:4px; }}"
                f"QPushButton:hover {{ border-color:#666; }}"
            )
            self._col2_btn.setToolTip(f"Couleur 2 : {c2}")


# ─── Panneau d'édition simplifié (colonne centrale) ───────────────────────────

class SimpleEffectPanel(QWidget):
    """
    Panneau central bi-colonnes :
      Gauche  — LayerCards (couches) + CIBLE + SENS/OPTIONS/GOBO contextuels
      Droite  — 4 Potards globaux + APERÇU
    """

    changed          = Signal()
    rename_requested = Signal(object)  # émet l'effet courant (dict)

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._layers       = []
        self._effect       = None
        self._direction    = 1
        self._main_window  = main_window
        self._layer_cards: list = []

        self.setStyleSheet("background: #0d0d0d;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet("background: #0a0a0a; border-bottom: 1px solid #181818;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(12)

        self._eff_emoji = QLabel("✦")
        self._eff_emoji.setFixedWidth(32)
        self._eff_emoji.setAlignment(Qt.AlignCenter)
        self._eff_emoji.setStyleSheet("color: #1e1e1e; font-size: 22px; background: transparent;")

        tc = QVBoxLayout()
        tc.setSpacing(1)
        self._eff_title = QLabel("Sélectionnez un effet")
        self._eff_title.setStyleSheet(
            "color: #1e1e1e; font-size: 13px; font-weight: bold; background: transparent;"
        )
        self._eff_cat = QLabel("")
        self._eff_cat.setStyleSheet(
            "color: #1a1a1a; font-size: 8px; letter-spacing: 2px; background: transparent;"
        )
        tc.addWidget(self._eff_title)
        tc.addWidget(self._eff_cat)

        self._rename_btn = QPushButton("✏")
        self._rename_btn.setFixedSize(28, 28)
        self._rename_btn.setCursor(Qt.PointingHandCursor)
        self._rename_btn.setToolTip("Renommer cet effet")
        self._rename_btn.setVisible(False)
        self._rename_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #333;
                border: 1px solid #252525; border-radius: 5px;
                font-size: 13px;
            }
            QPushButton:hover { color: #ffaa00; border-color: #554400; background: #1a1400; }
        """)
        self._rename_btn.clicked.connect(lambda: self.rename_requested.emit(self._effect))

        hl.addWidget(self._eff_emoji)
        hl.addLayout(tc, 1)
        hl.addWidget(self._rename_btn)
        outer.addWidget(hdr)

        # ── Corps bi-colonnes ──────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background: #0d0d0d;")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        # ── Colonne gauche (scrollable) : couches + contrôles ─────────────────
        lw_inner = QWidget()
        lw_inner.setStyleSheet("background: #0d0d0d;")
        self._ll = QVBoxLayout(lw_inner)
        self._ll.setContentsMargins(14, 14, 10, 12)
        self._ll.setSpacing(0)

        # En-tête COUCHES
        self._ll.addWidget(self._mk_sep("COUCHES"))
        self._ll.addSpacing(6)

        # Conteneur des LayerCard
        self._layers_container = QWidget()
        self._layers_container.setStyleSheet("background: transparent;")
        self._layers_vl = QVBoxLayout(self._layers_container)
        self._layers_vl.setContentsMargins(0, 0, 0, 0)
        self._layers_vl.setSpacing(5)
        self._ll.addWidget(self._layers_container)

        self._ll.addSpacing(4)

        # Placeholder "Sélectionner un effet" (visible quand aucun effet sélectionné)
        self._no_effect_lbl = QLabel("← Sélectionner un effet")
        self._no_effect_lbl.setStyleSheet(
            "color: #2a2a2a; font-size: 11px; font-style: italic; "
            "background: transparent; padding: 6px 0;"
        )
        self._ll.addWidget(self._no_effect_lbl)

        # Bouton + sous les couches
        self._add_layer_btn = QPushButton("＋  Ajouter une couche")
        self._add_layer_btn.setFixedHeight(22)
        self._add_layer_btn.setCursor(Qt.PointingHandCursor)
        self._add_layer_btn.setStyleSheet("""
            QPushButton {
                background: #1a3a1a; color: #55cc55;
                border: 1px solid #3a6a3a; border-radius: 3px;
                font-size: 11px; font-weight: bold; padding: 0 6px;
                text-align: left;
            }
            QPushButton:hover { color: #88ff88; border-color: #55aa55; background: #1f4a1f; }
            QPushButton:pressed { background: #0d2a0d; color: #44aa44; }
        """)
        self._add_layer_btn.setToolTip("Ajouter une couche")
        self._add_layer_btn.clicked.connect(self._on_add_layer)
        self._add_layer_btn.setVisible(False)
        self._ll.addWidget(self._add_layer_btn)

        self._ll.addSpacing(12)

        # SENS (contextuel)
        self._ll.addSpacing(10)
        self._build_sens()

        # OPTIONS + GOBO (contextuels)
        self._ll.addSpacing(10)
        self._build_context()

        self._ll.addStretch()

        lw_scroll = QScrollArea()
        lw_scroll.setWidget(lw_inner)
        lw_scroll.setWidgetResizable(True)
        lw_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lw_scroll.setStyleSheet("""
            QScrollArea { background: #0d0d0d; border: none; }
            QScrollBar:vertical { background: #0d0d0d; width: 4px; border-radius: 2px; }
            QScrollBar::handle:vertical { background: #252525; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        vs = QFrame()
        vs.setFrameShape(QFrame.VLine)
        vs.setFixedWidth(1)
        vs.setStyleSheet("QFrame { border: none; background: #161616; }")

        # ── Colonne droite (scrollable) : potards globaux + tempo + aperçu ────
        rw_inner = QWidget()
        rw_inner.setStyleSheet("background: #0d0d0d;")
        self._rl = QVBoxLayout(rw_inner)
        self._rl.setContentsMargins(14, 16, 20, 12)
        self._rl.setSpacing(0)
        self._build_knobs()
        self._rl.addSpacing(14)
        self._build_preview_strip()
        self._rl.addSpacing(14)
        self._build_assigner_section()
        self._rl.addStretch()

        rw_scroll = QScrollArea()
        rw_scroll.setWidget(rw_inner)
        rw_scroll.setWidgetResizable(True)
        rw_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rw_scroll.setStyleSheet("""
            QScrollArea { background: #0d0d0d; border: none; }
            QScrollBar:vertical { background: #0d0d0d; width: 4px; border-radius: 2px; }
            QScrollBar::handle:vertical { background: #252525; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        bl.addWidget(lw_scroll, 3)
        bl.addWidget(vs)
        bl.addWidget(rw_scroll, 1)
        outer.addWidget(body, 1)

        self._set_enabled(False)
        self._refresh_sens()

    # ── Construction sections ─────────────────────────────────────────────────

    def _build_sens(self):
        self._sens_section = QWidget()
        self._sens_section.setStyleSheet("background: transparent;")
        self._sens_section.setVisible(False)
        sv = QVBoxLayout(self._sens_section)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(6)
        sv.addWidget(self._mk_sep("SENS"))

        sens_row = QHBoxLayout()
        sens_row.setSpacing(4)
        self._sens_btns = {}
        for direction, label in [(1, "→  Avant"), (-1, "←  Arrière"), (0, "↔  Bounce")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: #0f0f0f; color: #383838;
                    border: 1px solid #1c1c1c; border-radius: 5px;
                    font-size: 10px; font-weight: bold;
                }
                QPushButton:checked {
                    background: #0d1e0d; color: #44cc66; border-color: #226622;
                }
                QPushButton:hover:!checked { background: #181818; color: #777; border-color: #262626; }
            """)
            btn.clicked.connect(lambda _=False, d=direction: self._on_sens(d))
            self._sens_btns[direction] = btn
            sens_row.addWidget(btn)
        sens_row.addStretch()
        sv.addLayout(sens_row)
        self._ll.addWidget(self._sens_section)

    _CTX_TYPES_SENS       = {"Chase", "Wave"}
    _CTX_TYPES_FONDU      = {"Chase"}
    _CTX_TYPES_GOBO       = {"Gobo"}
    _CTX_TYPES_COLORWHEEL = {"ColorWheel"}

    def _build_context(self):
        """Section contextuelle : options spécifiques par type d'effet."""
        self._ctx_section = QWidget()
        self._ctx_section.setStyleSheet("background: transparent;")
        self._ctx_section.setVisible(False)
        cv = QVBoxLayout(self._ctx_section)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)
        cv.addWidget(self._mk_sep("OPTIONS"))

        row = QHBoxLayout()
        row.setSpacing(6)

        _pill = """
            QPushButton {
                background: #0f0f0f; color: #383838;
                border: 1px solid #1c1c1c; border-radius: 5px;
                font-size: 10px; font-weight: bold; padding: 0 10px;
            }
            QPushButton:checked { background: #0d1e0d; color: #44cc66; border-color: #226622; }
            QPushButton:hover:!checked { background: #181818; color: #777; }
        """
        self._fondu_btn = QPushButton("〜  Fondu")
        self._fondu_btn.setCheckable(True)
        self._fondu_btn.setFixedHeight(26)
        self._fondu_btn.setCursor(Qt.PointingHandCursor)
        self._fondu_btn.setStyleSheet(_pill)
        self._fondu_btn.setToolTip("Transition douce (Sinus) au lieu de coupure franche (Flash)")
        self._fondu_btn.clicked.connect(self._on_fondu_toggle)
        row.addWidget(self._fondu_btn)
        row.addStretch()
        cv.addLayout(row)
        self._ll.addWidget(self._ctx_section)

        # ── Section GOBO (Lyre) ────────────────────────────────────────────────
        self._gobo_section = QWidget()
        self._gobo_section.setStyleSheet("background: transparent;")
        self._gobo_section.setVisible(False)
        gv = QVBoxLayout(self._gobo_section)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.setSpacing(6)
        gv.addWidget(self._mk_sep("GOBO"))

        gobo_row = QHBoxLayout()
        gobo_row.setSpacing(8)
        self._gobo_toggle = QPushButton("⦿  Activer GOBO")
        self._gobo_toggle.setCheckable(True)
        self._gobo_toggle.setFixedHeight(26)
        self._gobo_toggle.setCursor(Qt.PointingHandCursor)
        self._gobo_toggle.setStyleSheet(_pill)
        self._gobo_toggle.setToolTip("Ajouter une rotation de gobo à cet effet")
        self._gobo_toggle.clicked.connect(self._on_gobo_toggle)
        gobo_row.addWidget(self._gobo_toggle)
        gobo_row.addStretch()
        gv.addLayout(gobo_row)

        gobo_knob_row = QHBoxLayout()
        gobo_knob_row.setSpacing(8)
        self._knob_gobo = RotaryKnob("GOBO VIT.", default=40, size=52)
        self._knob_gobo.setEnabled(False)
        self._knob_gobo.valueChanged.connect(self._on_gobo_speed)
        gobo_knob_row.addWidget(self._knob_gobo)
        gobo_knob_row.addStretch()
        gv.addLayout(gobo_knob_row)
        self._ll.addWidget(self._gobo_section)

        # ── Section ROUE DE COULEURS (Lyre) ───────────────────────────────────
        self._cw_section = QWidget()
        self._cw_section.setStyleSheet("background: transparent;")
        self._cw_section.setVisible(False)
        cwv = QVBoxLayout(self._cw_section)
        cwv.setContentsMargins(0, 0, 0, 0)
        cwv.setSpacing(6)
        cwv.addWidget(self._mk_sep("ROUE COULEURS"))

        cw_row = QHBoxLayout()
        cw_row.setSpacing(8)
        self._cw_toggle = QPushButton("🎨  Activer Roue Couleurs")
        self._cw_toggle.setCheckable(True)
        self._cw_toggle.setFixedHeight(26)
        self._cw_toggle.setCursor(Qt.PointingHandCursor)
        self._cw_toggle.setStyleSheet(_pill)
        self._cw_toggle.setToolTip("Ajouter un cycle de roue de couleurs à cet effet")
        self._cw_toggle.clicked.connect(self._on_cw_toggle)
        cw_row.addWidget(self._cw_toggle)
        cw_row.addStretch()
        cwv.addLayout(cw_row)

        cw_knob_row = QHBoxLayout()
        cw_knob_row.setSpacing(8)
        self._knob_cw = RotaryKnob("CW VIT.", default=20, size=52)
        self._knob_cw.setEnabled(False)
        self._knob_cw.valueChanged.connect(self._on_cw_speed)
        cw_knob_row.addWidget(self._knob_cw)
        cw_knob_row.addStretch()
        cwv.addLayout(cw_knob_row)
        self._ll.addWidget(self._cw_section)

    def _build_knobs(self):
        self._rl.addWidget(self._mk_sep("AJUSTER TOUT"))
        self._rl.addSpacing(10)

        knob_w = QWidget()
        knob_w.setStyleSheet("background: transparent;")
        kl = QGridLayout(knob_w)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setHorizontalSpacing(18)
        kl.setVerticalSpacing(12)

        self._knob_speed  = RotaryKnob("VITESSE",   default=50,  size=60)
        self._knob_amp    = RotaryKnob("AMPLITUDE", default=100, size=60)
        self._knob_spread = RotaryKnob("DÉCALAGE",  default=0,   size=60)

        kl.addWidget(self._knob_speed,  0, 0, Qt.AlignCenter)
        kl.addWidget(self._knob_amp,    0, 1, Qt.AlignCenter)
        kl.addWidget(self._knob_spread, 1, 0, Qt.AlignCenter)

        self._knob_speed.valueChanged.connect(self._on_speed)
        self._knob_amp.valueChanged.connect(self._on_amp)
        self._knob_spread.valueChanged.connect(self._on_spread)

        self._rl.addWidget(knob_w, 0, Qt.AlignCenter)

    def _build_preview_strip(self):
        self._rl.addWidget(self._mk_sep("APERÇU"))
        self._rl.addSpacing(6)
        self._preview_strip = MiniFixturePreview(n=8)
        self._rl.addWidget(self._preview_strip)

    def _build_assigner_section(self):
        _sep_style = "color: #282828; font-size: 8px; font-weight: bold; letter-spacing: 2px;"

        self._rl.addWidget(self._mk_sep("ASSIGNER"))
        self._rl.addSpacing(6)

        self._assign_btns = {}
        assign_row = QHBoxLayout()
        assign_row.setSpacing(3)
        for i in range(9):
            btn = QPushButton(f"E{i + 1}")
            btn.setCheckable(True)
            btn.setFixedSize(26, 22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: #0f0f0f; color: #333;
                    border: 1px solid #1c1c1c; border-radius: 4px;
                    font-size: 9px; font-weight: bold;
                }
                QPushButton:checked { background: #001a2a; color: #00d4ff; border-color: #004466; }
                QPushButton:hover:!checked { background: #181818; color: #666; border-color: #252525; }
            """)
            self._assign_btns[i] = btn
            assign_row.addWidget(btn)
        assign_row.addStretch()
        self._rl.addLayout(assign_row)
        self._rl.addSpacing(10)

        # Boutons lecture conservés comme objets orphelins (référencés par EffectEditorDialog)
        self._btn_loop = QPushButton()
        self._btn_loop.setCheckable(True)
        self._btn_loop.setChecked(True)
        self._btn_once = QPushButton()
        self._btn_once.setCheckable(True)

        timer_row = QHBoxLayout()
        timer_row.setSpacing(6)
        timer_icon = QLabel("⏱")
        timer_icon.setStyleSheet("color: #2a2a2a; font-size: 14px;")
        timer_row.addWidget(timer_icon)
        self._timer_spin = QSpinBox()
        self._timer_spin.setRange(0, 3600)
        self._timer_spin.setValue(0)
        self._timer_spin.setSuffix("  s")
        self._timer_spin.setSpecialValueText("—")
        self._timer_spin.setFixedSize(78, 24)
        self._timer_spin.setStyleSheet("""
            QSpinBox {
                background: #111; color: #555;
                border: 1px solid #1e1e1e; border-radius: 4px;
                padding: 1px 4px; font-size: 10px;
            }
            QSpinBox:focus { border-color: #00d4ff; color: #aaa; }
            QSpinBox::up-button, QSpinBox::down-button { width: 14px; }
        """)
        timer_row.addWidget(self._timer_spin)
        timer_lbl = QLabel("Minuteur")
        timer_lbl.setStyleSheet("color: #282828; font-size: 9px; font-weight: bold; letter-spacing: 1px;")
        timer_row.addWidget(timer_lbl)
        timer_row.addStretch()
        self._rl.addLayout(timer_row)

    # ── Helpers UI ────────────────────────────────────────────────────────────

    def _mk_sep(self, text: str) -> QWidget:
        w = QWidget()
        w.setFixedHeight(12)
        w.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #222; font-size: 8px; font-weight: bold; letter-spacing: 2px;")
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("QFrame { border: none; background: #161616; }")
        line.setFixedHeight(1)
        lay.addWidget(lbl)
        lay.addWidget(line, 1)
        return w

    def _mk_pill(self, text: str, fixed_w: int = 0, h: int = 26) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setFixedHeight(h)
        if fixed_w:
            btn.setFixedWidth(fixed_w)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: #0f0f0f; color: #383838;
                border: 1px solid #1c1c1c; border-radius: 5px;
                font-size: 10px; font-weight: bold; padding: 0 8px;
            }
            QPushButton:checked {
                background: #003344; color: #00d4ff; border-color: #005566;
            }
            QPushButton:hover:!checked { background: #181818; color: #777; border-color: #252525; }
        """)
        return btn

    def _set_enabled(self, enabled: bool):
        for knob in (self._knob_speed, self._knob_amp, self._knob_spread):
            knob.setEnabled(enabled)
        for btn in self._sens_btns.values():
            btn.setEnabled(enabled)
        self._no_effect_lbl.setVisible(not enabled)
        self._add_layer_btn.setVisible(enabled)

    # ── Interface publique ────────────────────────────────────────────────────

    def set_effect(self, eff: dict, layers: list):
        self._effect    = eff
        self._layers    = layers
        self._direction = layers[0].direction if layers else 1

        emoji = eff.get("emoji",    "") if eff else ""
        name  = eff.get("name",     "") if eff else ""
        cat   = eff.get("category", "") if eff else ""

        self._eff_emoji.setText(emoji or "✦")
        self._eff_emoji.setStyleSheet("color: #bbb; font-size: 22px; background: transparent;")
        self._eff_title.setText(name)
        self._eff_title.setStyleSheet(
            "color: #eee; font-size: 13px; font-weight: bold; background: transparent;"
        )
        self._eff_cat.setText(cat.upper())
        self._eff_cat.setStyleSheet(
            "color: #3a3a3a; font-size: 8px; letter-spacing: 2px; background: transparent;"
        )
        self._rename_btn.setVisible(cat == "Mes Effets")

        self._set_enabled(bool(layers))
        self._refresh()
        self._refresh_context()
        self._rebuild_layer_widgets()

    # ── Rafraîchissement ──────────────────────────────────────────────────────

    def _refresh(self):
        if not self._layers:
            return
        l = self._layers[0]

        for knob, val in [
            (self._knob_speed,  l.speed),
            (self._knob_amp,    l.size),
            (self._knob_spread, l.spread),
        ]:
            knob.blockSignals(True)
            knob.set_value(val)
            knob.blockSignals(False)

        self._refresh_sens()

    def _refresh_sens(self):
        for d, btn in self._sens_btns.items():
            btn.blockSignals(True)
            btn.setChecked(d == self._direction)
            btn.blockSignals(False)

    def _refresh_context(self):
        eff_type   = self._effect.get("type", "") if self._effect else ""
        show_sens  = eff_type in self._CTX_TYPES_SENS
        show_fondu = eff_type in self._CTX_TYPES_FONDU
        show_gobo  = eff_type in self._CTX_TYPES_GOBO
        show_cw    = eff_type in self._CTX_TYPES_COLORWHEEL
        self._sens_section.setVisible(show_sens)
        self._ctx_section.setVisible(show_fondu)
        self._gobo_section.setVisible(show_gobo)
        self._cw_section.setVisible(show_cw)
        if show_fondu and self._layers:
            self._fondu_btn.blockSignals(True)
            self._fondu_btn.setChecked(self._layers[0].forme == "Sinus")
            self._fondu_btn.blockSignals(False)
        if show_gobo:
            has_gobo = any(l.attribute == "Gobo" for l in self._layers)
            self._gobo_toggle.blockSignals(True)
            self._gobo_toggle.setChecked(has_gobo)
            self._gobo_toggle.blockSignals(False)
            self._knob_gobo.setEnabled(has_gobo)
            if has_gobo:
                gobo_layer = next((l for l in self._layers if l.attribute == "Gobo"), None)
                if gobo_layer:
                    self._knob_gobo.blockSignals(True)
                    self._knob_gobo.set_value(gobo_layer.speed)
                    self._knob_gobo.blockSignals(False)
        if show_cw:
            has_cw = any(l.attribute == "ColorWheel" for l in self._layers)
            self._cw_toggle.blockSignals(True)
            self._cw_toggle.setChecked(has_cw)
            self._cw_toggle.blockSignals(False)
            self._knob_cw.setEnabled(has_cw)
            if has_cw:
                cw_layer = next((l for l in self._layers if l.attribute == "ColorWheel"), None)
                if cw_layer:
                    self._knob_cw.blockSignals(True)
                    self._knob_cw.set_value(cw_layer.speed)
                    self._knob_cw.blockSignals(False)

    # ── Gestion des couches ────────────────────────────────────────────────────

    def _rebuild_layer_widgets(self):
        self._layer_cards = []
        self._pt_pad_widget = None
        while self._layers_vl.count():
            item = self._layers_vl.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for layer in self._layers:
            card = LayerCard(layer)
            card.deleted.connect(lambda _w, l=layer: self._on_delete_layer(l))
            card.changed.connect(self.changed)
            card.pan_tilt_created.connect(self._on_pan_tilt_created)
            self._layers_vl.addWidget(card)
            self._layer_cards.append(card)

    def _on_pan_tilt_created(self):
        """Un Pan/Tilt vient d'être créé à la main → le rendre prêt à l'emploi :
        dimmer fixe 100 % + couleur blanche (mouvement visible) et vitesse douce.
        Les variantes/builtins ne passent JAMAIS ici (chargées sans action UI)."""
        has_dim   = any(l.attribute == "Dimmer" for l in self._layers)
        has_color = any(l.attribute in ("R", "V", "B", "RGB", "Permut")
                        for l in self._layers)
        # Cibler les mêmes fixtures que le mouvement (sinon le blanc part sur « Tous »).
        pt = next((l for l in self._layers
                   if l.attribute in ("Pan/Tilt", "Pan", "Tilt")), None)
        tp = pt.target_preset if pt else "Tous"
        tg = list(pt.target_groups) if pt else []
        changed = False
        if not has_dim:
            dl = EffectLayer()
            dl.attribute = "Dimmer"; dl.forme = "Fixe"; dl.size = 100
            dl.target_preset = tp; dl.target_groups = list(tg)
            self._layers.append(dl); changed = True
        if not has_color:
            cl = EffectLayer()
            cl.attribute = "RGB"; cl.forme = "Fixe"; cl.color1 = "#ffffff"; cl.size = 100
            cl.target_preset = tp; cl.target_groups = list(tg)
            self._layers.append(cl); changed = True
        # Vitesse douce par défaut pour le mouvement (règle knob + toutes les couches).
        if hasattr(self, '_knob_speed'):
            self._knob_speed.set_value(15)
        if changed:
            # Reconstruction différée : ne pas détruire la LayerCard pendant son
            # propre handler _on_attr (qui a émis ce signal).
            QTimer.singleShot(0, self._rebuild_layer_widgets)
        self.changed.emit()

    def _on_add_layer(self):
        new_layer           = EffectLayer()
        new_layer.attribute = "Dimmer"
        new_layer.forme     = "Sinus"
        new_layer.speed     = self._knob_speed.value
        self._layers.append(new_layer)
        self._rebuild_layer_widgets()
        self.changed.emit()

    def _on_delete_layer(self, layer: EffectLayer):
        if layer in self._layers:
            self._layers.remove(layer)
        self._rebuild_layer_widgets()
        self.changed.emit()

    def _on_delete_pt_layers(self):
        """Supprime toutes les couches Pan et Tilt."""
        self._layers = [l for l in self._layers if l.attribute not in ("Pan", "Tilt")]
        self._rebuild_layer_widgets()
        self.changed.emit()

    # ── Tick d'animation ──────────────────────────────────────────────────────

    def tick(self, t: float):
        """Mettre à jour toutes les waveforms des LayerCard + pad XY Pan/Tilt."""
        for card in self._layer_cards:
            card.set_time(t)
        if getattr(self, '_pt_pad_widget', None) is not None:
            self._pt_pad_widget.set_time(t)

    def set_preview_levels(self, levels: list, colors: list):
        if hasattr(self, '_preview_strip'):
            self._preview_strip.set_levels(levels, colors)

    # ── Événements ────────────────────────────────────────────────────────────

    def _on_speed(self, val: int):
        for layer in self._layers:
            layer.speed = val
        self.changed.emit()

    def _on_amp(self, val: int):
        for layer in self._layers:
            layer.size = val
        self.changed.emit()

    def _on_spread(self, val: int):
        for layer in self._layers:
            layer.spread = val
        self.changed.emit()

    def _on_fade(self, val: int):
        for layer in self._layers:
            layer.fade = val
        self.changed.emit()

    def _on_sens(self, direction: int):
        self._direction = direction
        for layer in self._layers:
            layer.direction = direction
        self._refresh_sens()
        self.changed.emit()

    def _on_fondu_toggle(self, checked: bool):
        forme = "Sinus" if checked else "Flash"
        for layer in self._layers:
            layer.forme = forme
        self.changed.emit()

    def _on_gobo_toggle(self, checked: bool):
        self._knob_gobo.setEnabled(checked)
        if checked:
            if not any(l.attribute == "Gobo" for l in self._layers):
                layer           = EffectLayer()
                layer.attribute = "Gobo"
                layer.forme     = "Sinus"
                layer.speed     = self._knob_gobo.value
                layer.size      = 100
                layer.spread    = 0
                self._layers.append(layer)
        else:
            self._layers[:] = [l for l in self._layers if l.attribute != "Gobo"]
        self._rebuild_layer_widgets()
        self.changed.emit()

    def _on_gobo_speed(self, val: int):
        for l in self._layers:
            if l.attribute == "Gobo":
                l.speed = val
        self.changed.emit()

    def _on_cw_toggle(self, checked: bool):
        self._knob_cw.setEnabled(checked)
        if checked:
            if not any(l.attribute == "ColorWheel" for l in self._layers):
                layer           = EffectLayer()
                layer.attribute = "ColorWheel"
                layer.forme     = "Montée"
                layer.speed     = self._knob_cw.value
                layer.size      = 100
                layer.spread    = 0
                self._layers.append(layer)
        else:
            self._layers[:] = [l for l in self._layers if l.attribute != "ColorWheel"]
        self._rebuild_layer_widgets()
        self.changed.emit()

    def _on_cw_speed(self, val: int):
        for l in self._layers:
            if l.attribute == "ColorWheel":
                l.speed = val
        self.changed.emit()


# ─── Dialog principal ──────────────────────────────────────────────────────────

_EFFECT_CATEGORIES = ["Strobe / Flash", "Mouvement", "Ambiance", "Couleur", "Spécial", "Permut", "Lyre"]

import json as _json
import pathlib as _pathlib

_CUSTOM_EFFECTS_FILE = _pathlib.Path.home() / ".mystrow_custom_effects.json"


def _load_custom_effects() -> list:
    try:
        if _CUSTOM_EFFECTS_FILE.exists():
            data = _json.loads(_CUSTOM_EFFECTS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_custom_effects(effects: list):
    try:
        _CUSTOM_EFFECTS_FILE.write_text(
            _json.dumps(effects, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _ask_name(parent, title: str, label: str, default: str = "") -> tuple[str, bool]:
    """Dialog de saisie de nom stylisé (remplace QInputDialog.getText)."""
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                   QLabel, QLineEdit, QPushButton)
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(340)
    dlg.setStyleSheet("""
        QDialog   { background: #1a1a1a; }
        QLabel    { color: #cccccc; font-size: 13px; padding-bottom: 4px; }
        QLineEdit {
            background: #2a2a2a; color: #ffffff;
            border: 1px solid #444; border-radius: 4px;
            padding: 6px 10px; font-size: 13px;
        }
        QLineEdit:focus { border-color: #00d4ff; }
        QPushButton {
            background: #2a2a2a; color: #cccccc;
            border: 1px solid #444; border-radius: 4px;
            padding: 6px 18px; font-size: 12px; min-width: 70px;
        }
        QPushButton:hover  { background: #333; color: #fff; }
        QPushButton#ok_btn { background: #003a4a; color: #00d4ff;
                             border-color: #00d4ff; }
        QPushButton#ok_btn:hover { background: #004d63; }
    """)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(20, 18, 20, 16)
    lay.setSpacing(10)
    lay.addWidget(QLabel(label))
    edit = QLineEdit(default)
    edit.selectAll()
    lay.addWidget(edit)
    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    btn_row.addStretch()
    cancel = QPushButton("Annuler")
    ok     = QPushButton("OK")
    ok.setObjectName("ok_btn")
    ok.setDefault(True)
    btn_row.addWidget(cancel)
    btn_row.addWidget(ok)
    lay.addLayout(btn_row)
    result = [("", False)]
    ok.clicked.connect(lambda: (result.__setitem__(0, (edit.text(), True)),  dlg.accept()))
    cancel.clicked.connect(dlg.reject)
    edit.returnPressed.connect(ok.click)
    dlg.exec()
    return result[0]


class EffectEditorDialog(QDialog):
    """
    Editeur d'effets — 3 colonnes :
      [Bibliothèque effets] | [Barre presets + Éditeur couches] | [Plan de Feu live]
    """

    def __init__(self, clips, main_window, parent=None, initial_effect=None):
        super().__init__(parent)
        self._clips       = clips or []
        self._main_window = main_window
        self._layers: list = []
        self._rows:   list = []

        if self._clips:
            for item in getattr(self._clips[0], 'effect_layers', []):
                if isinstance(item, dict):
                    self._layers.append(EffectLayer.from_dict(item))
                elif isinstance(item, EffectLayer):
                    self._layers.append(copy.deepcopy(item))

        self._fixture_types = list({
            getattr(pr, 'fixture_type', 'PAR LED')
            for pr in getattr(main_window, 'projectors', [])
        }) or ["PAR LED"]

        self._play_mode       = 'loop'
        self._effect_duration = getattr(self._clips[0], 'effect_duration', 0) if self._clips else 0
        self._preview_t0      = 0.0
        # Pré-sélectionner : 1) initial_effect passé en param, 2) effet du clip, 3) premier builtin
        saved_name = getattr(self._clips[0], 'effect_name', '') if self._clips else ''
        raw_name = initial_effect or saved_name or (BUILTIN_EFFECTS[0]['name'] if BUILTIN_EFFECTS else None)
        # Si raw_name est un type legacy ("Flash", "Strobe"...) sans correspondance exacte,
        # trouver le premier effet builtin dont le type correspond
        _all_builtin_names = {e.get("name") for e in BUILTIN_EFFECTS}
        if raw_name and raw_name not in _all_builtin_names:
            _fallback = next((e.get("name") for e in BUILTIN_EFFECTS if e.get("type") == raw_name), None)
            raw_name = _fallback or raw_name
        self._selected_card = raw_name
        # Restaurer play_mode et duration depuis la config sauvegardée (si pas de clips)
        if not self._clips and self._selected_card:
            _saved_cfg = self._get_saved_cfg_for(self._selected_card)
            if _saved_cfg:
                self._play_mode       = _saved_cfg.get("play_mode", self._play_mode)
                self._effect_duration = _saved_cfg.get("duration",   self._effect_duration)
        self._custom_effects = _load_custom_effects()

        self.setWindowTitle("Editeur d'effets")
        self.setMinimumSize(1160, 620)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._preview_tick)
        self.finished.connect(lambda _: self._stop_preview())
        self.finished.connect(lambda _: self._autosave_on_close())

        self._selected_card_widget = None
        self._build_ui()
        self._rebuild_rows()
        # Défiler la bibliothèque de gauche jusqu'à l'effet du clip (sinon on ne
        # voit pas quel effet est sélectionné si sa carte est plus bas).
        QTimer.singleShot(0, self._reveal_selected_card)

    def _reveal_selected_card(self):
        """Amène la carte de l'effet sélectionné dans la vue de la bibliothèque."""
        try:
            w  = getattr(self, '_selected_card_widget', None)
            sc = getattr(self, '_lib_scroll', None)
            if w and sc:
                sc.ensureWidgetVisible(w, 0, 40)
        except Exception:
            pass

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._mk_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Colonne 1 : bibliothèque (240px fixe)
        body.addWidget(self._mk_library_panel())

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setFixedWidth(1)
        sep1.setStyleSheet("background: #1e1e1e;")
        body.addWidget(sep1)

        # Colonne 2 : éditeur simplifié (stretch)
        body.addWidget(self._mk_simple_panel(), 1)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFixedWidth(1)
        sep2.setStyleSheet("background: #1e1e1e;")
        body.addWidget(sep2)

        # Colonne 3 : plan de feu
        body.addWidget(self._mk_plan_panel())

        root.addLayout(body, 1)
        root.addWidget(self._mk_footer())

    # ── Colonne 1 : bibliothèque ──────────────────────────────────────────────

    def _mk_library_panel(self):
        panel = QWidget()
        panel.setFixedWidth(260)
        panel.setStyleSheet("background: #0a0a0a;")

        lv = QVBoxLayout(panel)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet("background: #080808; border-bottom: 1px solid #161616;")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(14, 0, 10, 0)
        ttl = QLabel("Effets")
        ttl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        ttl.setStyleSheet("color: #ddd;")
        hh.addWidget(ttl)
        hh.addStretch()
        save_btn = QPushButton("＋ Ajouter un effet")
        save_btn.setFixedHeight(26)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setToolTip("Sauvegarder l'effet actuel dans Mes Effets")
        save_btn.setStyleSheet("""
            QPushButton {
                background: #0a1a0a; color: #285028;
                border: 1px solid #1a3a1a; border-radius: 5px;
                font-size: 10px; font-weight: bold; padding: 0 8px;
            }
            QPushButton:hover { background: #0d220d; color: #55aa55; border-color: #2a5a2a; }
        """)
        save_btn.clicked.connect(self._save_current_as_custom)
        hh.addWidget(save_btn)
        lv.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: #0a0a0a; border: none; }
            QScrollBar:vertical { background: #080808; width: 5px; border-radius: 2px; }
            QScrollBar::handle:vertical { background: #222; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._list_w = QWidget()
        self._list_w.setStyleSheet("background: #0a0a0a;")
        self._list_vl = QVBoxLayout(self._list_w)
        self._list_vl.setContentsMargins(8, 8, 8, 8)
        self._list_vl.setSpacing(0)
        self._list_vl.addStretch()
        scroll.setWidget(self._list_w)
        lv.addWidget(scroll, 1)
        self._lib_scroll = scroll   # pour défiler jusqu'à l'effet sélectionné

        self._rebuild_library()
        return panel

    def _rebuild_library(self):
        while self._list_vl.count() > 1:
            item = self._list_vl.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)

        card_w = (260 - 16 - 8) // 2  # (panel_width - h_margins - gap) / 2

        def _insert_category(label, items, deletable=False):
            if not items:
                return
            ch = QLabel(label.upper())
            ch.setFixedHeight(20)
            ch.setStyleSheet(
                "color: #2a2a2a; font-size: 8px; font-weight: bold; "
                "letter-spacing: 1.5px; background: transparent; padding-left: 2px;"
            )
            self._list_vl.insertWidget(self._list_vl.count() - 1, ch)
            for idx in range(0, len(items), 2):
                pair = items[idx:idx + 2]
                row_w = QWidget()
                row_w.setStyleSheet("background: transparent;")
                row_h = QHBoxLayout(row_w)
                row_h.setContentsMargins(0, 0, 0, 0)
                row_h.setSpacing(6)
                for eff in pair:
                    row_h.addWidget(self._mk_card(eff, card_w, deletable=deletable))
                if len(pair) == 1:
                    row_h.addStretch()
                row_w.setFixedHeight(58)
                self._list_vl.insertWidget(self._list_vl.count() - 1, row_w)
            spc = QWidget()
            spc.setFixedHeight(6)
            spc.setStyleSheet("background: transparent;")
            self._list_vl.insertWidget(self._list_vl.count() - 1, spc)

        # Effets intégrés
        for cat in _EFFECT_CATEGORIES:
            _insert_category(cat, [e for e in BUILTIN_EFFECTS if e.get("category") == cat])

        # Effets custom — header toujours visible avec bouton import
        mes_hdr_w = QWidget()
        mes_hdr_w.setStyleSheet("background: transparent;")
        mes_hdr_w.setFixedHeight(20)
        mes_hdr_h = QHBoxLayout(mes_hdr_w)
        mes_hdr_h.setContentsMargins(2, 0, 2, 0)
        mes_hdr_h.setSpacing(4)
        mes_hdr_lbl = QLabel("MES EFFETS")
        mes_hdr_lbl.setStyleSheet(
            "color: #2a2a2a; font-size: 8px; font-weight: bold; "
            "letter-spacing: 1.5px; background: transparent;"
        )
        mes_hdr_h.addWidget(mes_hdr_lbl, 1)
        imp_btn = QPushButton("+")
        imp_btn.setFixedSize(16, 16)
        imp_btn.setToolTip("Importer un effet (.mystrow_effect)")
        imp_btn.setCursor(Qt.PointingHandCursor)
        imp_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a1a; color: #446644;
                border: 1px solid #2a2a2a; border-radius: 3px;
                font-size: 12px; font-weight: bold; padding: 0;
            }
            QPushButton:hover { background: #1e2e1e; color: #44cc44; border-color: #336633; }
        """)
        imp_btn.clicked.connect(self._import_custom_effect)
        mes_hdr_h.addWidget(imp_btn)
        self._list_vl.insertWidget(self._list_vl.count() - 1, mes_hdr_w)

        if self._custom_effects:
            for idx in range(0, len(self._custom_effects), 2):
                pair = self._custom_effects[idx:idx + 2]
                row_w = QWidget()
                row_w.setStyleSheet("background: transparent;")
                row_h = QHBoxLayout(row_w)
                row_h.setContentsMargins(0, 0, 0, 0)
                row_h.setSpacing(6)
                for eff in pair:
                    row_h.addWidget(self._mk_card(eff, card_w, deletable=True))
                if len(pair) == 1:
                    row_h.addStretch()
                row_w.setFixedHeight(58)
                self._list_vl.insertWidget(self._list_vl.count() - 1, row_w)
        else:
            empty_lbl = QLabel("Aucun effet — importez ou créez-en un")
            empty_lbl.setAlignment(Qt.AlignCenter)
            empty_lbl.setStyleSheet(
                "color: #222; font-size: 9px; font-style: italic; background: transparent;"
            )
            empty_lbl.setFixedHeight(28)
            self._list_vl.insertWidget(self._list_vl.count() - 1, empty_lbl)

        spc_me = QWidget()
        spc_me.setFixedHeight(6)
        spc_me.setStyleSheet("background: transparent;")
        self._list_vl.insertWidget(self._list_vl.count() - 1, spc_me)

    def _mk_card(self, eff: dict, width: int = 116, deletable: bool = False) -> QWidget:
        name = eff.get("name", "")
        sel  = (name == self._selected_card)

        card = QWidget()
        card.setFixedSize(width, 54)
        card.setCursor(Qt.PointingHandCursor)
        card.setObjectName("ECard")
        sel_bg    = "#0d1e1a"
        sel_bdr   = "#00d4ff"
        hover_bg  = "#141414"
        card.setStyleSheet(f"""
            QWidget#ECard {{
                background: {sel_bg if sel else "#111"};
                border: 1px solid {sel_bdr if sel else "#1a1a1a"};
                border-radius: 7px;
            }}
            QWidget#ECard:hover {{ background: {hover_bg}; border-color: #282828; }}
        """)

        if sel:
            self._selected_card_widget = card   # cible du défilement auto à l'ouverture

        vl = QVBoxLayout(card)
        vl.setContentsMargins(4, 5, 4, 4)
        vl.setSpacing(2)

        # Rangée haute : emoji + bouton × si custom
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)

        emoji_lbl = QLabel(eff.get("emoji", ""))
        emoji_lbl.setAlignment(Qt.AlignCenter)
        emoji_lbl.setStyleSheet(
            "color: #00d4ff; font-size: 15px;" if sel else "color: #666; font-size: 15px;"
        )
        top_row.addWidget(emoji_lbl, 1)

        if deletable:
            ren_btn = QPushButton("✎")
            ren_btn.setFixedSize(14, 14)
            ren_btn.setCursor(Qt.PointingHandCursor)
            ren_btn.setToolTip("Renommer")
            ren_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #446644;
                    border: none; font-size: 10px;
                }
                QPushButton:hover { color: #44cc44; }
            """)
            ren_btn.clicked.connect(lambda _=False, e=eff: self._rename_custom_effect(e))
            top_row.addWidget(ren_btn)

            del_btn = QPushButton("×")
            del_btn.setFixedSize(14, 14)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #884444;
                    border: none; font-size: 10px; font-weight: bold;
                }
                QPushButton:hover { color: #ff5555; }
            """)
            del_btn.clicked.connect(lambda _=False, e=eff: self._delete_custom_effect(e))
            top_row.addWidget(del_btn)

        vl.addLayout(top_row)

        # AKAI badge if assigned
        akai = self._get_assigned_btn_label(name)

        name_lbl = QLabel(name)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            "color: #00d4ff; font-size: 8px; font-weight: bold; background: transparent;" if sel
            else "color: #555; font-size: 8px; background: transparent;"
        )
        vl.addWidget(name_lbl, 1)

        if akai:
            badge_row = QHBoxLayout()
            badge_row.setContentsMargins(2, 0, 2, 0)
            badge = QLabel(akai)
            badge.setFixedHeight(12)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                "background: #003344; color: #00d4ff; border: 1px solid #005566; "
                "border-radius: 2px; font-size: 7px; font-weight: bold;"
            )
            badge_row.addWidget(badge)
            vl.addLayout(badge_row)

        def _card_mouse_press(_e, e=eff):
            if _e.button() == Qt.RightButton:
                _e.accept()
            else:
                self._apply_preset(e)

        card.mousePressEvent = _card_mouse_press
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, e=eff, d=deletable: self._show_card_context_menu(card, pos, e, d)
        )
        return card

    def _get_assigned_btn_label(self, name: str) -> str:
        cfg_map = getattr(self._main_window, '_button_effect_configs', {})
        for idx, cfg in cfg_map.items():
            if isinstance(cfg, dict) and cfg.get("name") == name:
                return f"E{int(idx) + 1}"
        return ""

    def _save_current_as_custom(self):
        """Sauvegarde l'effet actuellement chargé dans Mes Effets."""
        existing_names = {e.get("name", "") for e in self._custom_effects}

        if not self._layers:
            # Aucun effet chargé : créer un effet vierge avec une couche par défaut
            base = "Mon Effet"
            i = 2
            while base in existing_names:
                base = f"Mon Effet {i}"; i += 1
            name, ok = _ask_name(self, "Nouvel effet", "Nom de l'effet :", base)
            if not ok or not name.strip():
                return
            name = name.strip()
            default_layer = _L("Dimmer", "Sinus", speed=50, size=100, spread=0)
            custom = {
                "name":     name,
                "emoji":    "★",
                "category": "Mes Effets",
                "type":     "Custom",
                "layers":   [default_layer],
            }
            self._custom_effects.append(custom)
            _save_custom_effects(self._custom_effects)
            self._selected_card = name
            self._rebuild_library()
            self._apply_preset(custom)
            return

        # Effet chargé : proposer de le sauvegarder sous un nom
        # Exclure aussi les noms builtins pour éviter les conflits de déduplication
        all_existing = existing_names | {e.get("name", "") for e in BUILTIN_EFFECTS}
        base = self._selected_card or "Mon Effet"
        i = 2
        candidate = base
        while candidate in all_existing:
            candidate = f"{base} {i}"; i += 1
        name, ok = _ask_name(
            self, "Sauvegarder l'effet", "Nom de l'effet :", candidate
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        src_eff = next(
            (e for e in BUILTIN_EFFECTS + self._custom_effects if e.get("name") == self._selected_card),
            None
        )
        custom = {
            "name":     name,
            "emoji":    "★",
            "category": "Mes Effets",
            "type":     src_eff.get("type", "Custom") if src_eff else "Custom",
            "layers":   [l.to_dict() for l in self._layers],
        }
        self._custom_effects.append(custom)
        _save_custom_effects(self._custom_effects)
        self._selected_card = name
        self._rebuild_library()
        self._apply_preset(custom)

    def _show_card_context_menu(self, card, pos, eff: dict, deletable: bool):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a2e; color: #ccc;
                border: 1px solid #333; border-radius: 4px;
            }
            QMenu::item { padding: 5px 18px; }
            QMenu::item:selected { background: #2a2a4e; color: #fff; }
            QMenu::separator { height: 1px; background: #333; margin: 2px 0; }
        """)
        act_dup = menu.addAction("Dupliquer")
        act_exp = menu.addAction("Exporter…")
        if deletable:
            menu.addSeparator()
            act_del = menu.addAction("Supprimer")
        else:
            act_del = None
        chosen = menu.exec(card.mapToGlobal(pos))
        if chosen == act_dup:
            self._duplicate_custom_effect(eff)
        elif chosen == act_exp:
            self._export_custom_effect(eff)
        elif act_del and chosen == act_del:
            self._delete_custom_effect(eff)

    def _duplicate_custom_effect(self, eff: dict):
        existing_names = {e.get("name", "") for e in self._custom_effects} | \
                         {e.get("name", "") for e in BUILTIN_EFFECTS}
        base = f"Copie de {eff.get('name', 'Effet')}"
        candidate = base
        i = 2
        while candidate in existing_names:
            candidate = f"{base} {i}"; i += 1
        # Charger les couches depuis l'effet source
        src_layers = []
        if eff in self._custom_effects or any(e is eff for e in self._custom_effects):
            src_layers = list(eff.get("layers", []))
        else:
            # Builtin: construire les couches par défaut
            src_layers = [l.to_dict() for l in EffectLayer.layers_from_builtin(eff)]
        copy_eff = {
            "name":     candidate,
            "emoji":    eff.get("emoji", "✨"),
            "category": "Mes Effets",
            "type":     eff.get("type", "Custom"),
            "layers":   src_layers,
        }
        self._custom_effects.append(copy_eff)
        _save_custom_effects(self._custom_effects)
        self._selected_card = candidate
        self._rebuild_library()
        self._apply_preset(copy_eff)

    def _delete_custom_effect(self, eff: dict):
        name = eff.get("name", "")
        self._custom_effects = [e for e in self._custom_effects if e.get("name") != name]
        _save_custom_effects(self._custom_effects)
        if self._selected_card == name:
            self._selected_card = None
        self._rebuild_library()

    def _export_custom_effect(self, eff: dict):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import json as _j
        is_custom = any(e is eff for e in self._custom_effects)
        if is_custom:
            layers = list(eff.get("layers", []))
        else:
            layers = [l.to_dict() for l in EffectLayer.layers_from_builtin(eff)]
        export_data = {
            "name":    eff.get("name", "Effet"),
            "emoji":   eff.get("emoji", "✨"),
            "category": "Mes Effets",
            "type":    eff.get("type", "Custom"),
            "layers":  layers,
        }
        safe = eff.get("name", "effet").replace("/", "_").replace("\\", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter l'effet",
            str(_pathlib.Path.home() / f"{safe}.mystrow_effect"),
            "Effet MyStrow (*.mystrow_effect);;JSON (*.json)"
        )
        if not path:
            return
        try:
            _pathlib.Path(path).write_text(
                _j.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Erreur export", str(exc))

    def _import_custom_effect(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import json as _j
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer un effet",
            str(_pathlib.Path.home()),
            "Effet MyStrow (*.mystrow_effect);;JSON (*.json);;Tous (*.*)"
        )
        if not path:
            return
        try:
            data = _j.loads(_pathlib.Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "Erreur import", f"Fichier invalide :\n{exc}")
            return
        if not isinstance(data, dict) or "layers" not in data:
            QMessageBox.warning(self, "Erreur import", "Ce fichier ne contient pas un effet valide.")
            return
        existing_names = {e.get("name", "") for e in self._custom_effects} | \
                         {e.get("name", "") for e in BUILTIN_EFFECTS}
        base = data.get("name", "Effet importé")
        candidate = base
        i = 2
        while candidate in existing_names:
            candidate = f"{base} ({i})"; i += 1
        new_eff = {
            "name":     candidate,
            "emoji":    data.get("emoji", "✨"),
            "category": "Mes Effets",
            "type":     data.get("type", "Custom"),
            "layers":   data.get("layers", []),
        }
        self._custom_effects.append(new_eff)
        _save_custom_effects(self._custom_effects)
        self._selected_card = candidate
        self._rebuild_library()
        self._apply_preset(new_eff)

    def _rename_custom_effect(self, eff: dict):
        old_name = eff.get("name", "")
        existing = {e.get("name", "") for e in self._custom_effects}
        new_name, ok = _ask_name(self, "Renommer l'effet", "Nouveau nom :", old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        if new_name in existing:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Nom déjà utilisé", f'Un effet "{new_name}" existe déjà.')
            return
        # Mettre à jour le dict de l'effet
        eff["name"] = new_name
        _save_custom_effects(self._custom_effects)
        # Mettre à jour les configs sauvegardées (boutons AKAI + librairie)
        if self._main_window:
            for cfg in getattr(self._main_window, '_button_effect_configs', {}).values():
                if isinstance(cfg, dict) and cfg.get("name") == old_name:
                    cfg["name"] = new_name
            if hasattr(self._main_window, '_save_effect_assignments'):
                self._main_window._save_effect_assignments()
            lib = getattr(self._main_window, '_effect_library_configs', {})
            if old_name in lib:
                lib[new_name] = lib.pop(old_name)
                lib[new_name]["name"] = new_name
            if hasattr(self._main_window, '_save_effect_library'):
                self._main_window._save_effect_library()
        if self._selected_card == old_name:
            self._selected_card = new_name
        self._rebuild_library()

    # ── Barre de presets ──────────────────────────────────────────────────────

    def _mk_presets_bar(self):
        bar = QWidget()
        bar.setStyleSheet("background: #0a0a0a; border-bottom: 1px solid #1c1c1c;")
        bar.setFixedHeight(48)
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(6)

        lbl = QLabel("Presets :")
        lbl.setStyleSheet("color: #444; font-size: 10px; margin-right: 4px;")
        h.addWidget(lbl)

        for eff in BUILTIN_EFFECTS:
            btn = QPushButton(f"{eff.get('emoji', '+')}  {eff['name']}")
            btn.setFixedHeight(30)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background: #161616; color: #aaa;
                    border: 1px solid #282828; border-radius: 5px;
                    font-size: 10px; padding: 0 10px;
                }
                QPushButton:hover { background: #1e1e1e; border-color: #00d4ff; color: #fff; }
                QPushButton:pressed { background: #002233; border-color: #00d4ff; }
            """)
            btn.clicked.connect(lambda _=False, e=eff: self._apply_preset(e))
            h.addWidget(btn)

        h.addStretch()
        return bar

    # ── Colonne 2 : panneau simplifié ─────────────────────────────────────────

    def _mk_simple_panel(self) -> QWidget:
        self._simple_panel = SimpleEffectPanel(main_window=self._main_window)
        self._simple_panel.changed.connect(self._ensure_preview_running)
        self._simple_panel.changed.connect(self._push_layers_to_live)
        self._simple_panel.rename_requested.connect(self._rename_custom_effect)

        # Aliases vers les widgets créés dans SimpleEffectPanel._build_assigner_section
        self._btn_loop    = self._simple_panel._btn_loop
        self._btn_once    = self._simple_panel._btn_once
        self._assign_btns = self._simple_panel._assign_btns
        self._timer_spin  = self._simple_panel._timer_spin

        # Connexions
        self._btn_loop.clicked.connect(lambda: self._set_play_mode("loop"))
        self._btn_once.clicked.connect(lambda: self._set_play_mode("once"))
        for _i, _btn in self._assign_btns.items():
            _btn.clicked.connect(lambda _=False, idx=_i: self._on_assign(idx))

        # Charger les layers : existants si le clip en a, sinon preset sélectionné par défaut
        if self._layers:
            self._simple_panel._layers = self._layers
            self._simple_panel._set_enabled(True)
            self._simple_panel._refresh()
        elif self._selected_card:
            default_eff = next(
                (e for e in BUILTIN_EFFECTS + self._custom_effects if e.get('name') == self._selected_card),
                None
            )
            if default_eff:
                self._apply_preset(default_eff)

        self._timer_spin.setValue(self._effect_duration)
        self._refresh_mode_btns()
        return self._simple_panel

    # ── Colonne 3 : plan de feu + contrôles ──────────────────────────────────

    def _mk_plan_panel(self):
        panel = QWidget()
        panel.setFixedWidth(280)
        panel.setStyleSheet("background: #0a0a0a;")

        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        try:
            from plan_de_feu import PlanDeFeu
            projectors = getattr(self._main_window, 'projectors', [])
            self._plan_widget = PlanDeFeu(projectors, self._main_window, show_toolbar=False)
            pv.addWidget(self._plan_widget, 1)
        except Exception:
            self._plan_widget = None
            fallback = QLabel("Plan de feu\nnon disponible")
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setStyleSheet("color: #444; font-size: 11px;")
            pv.addWidget(fallback, 1)

        return panel

    def _mk_ctrl_sep(self, text: str) -> QWidget:
        w = QWidget()
        w.setFixedHeight(14)
        w.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #282828; font-size: 8px; font-weight: bold; letter-spacing: 2px;")
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("QFrame { border: none; background: #161616; }")
        line.setFixedHeight(1)
        lay.addWidget(lbl)
        lay.addWidget(line, 1)
        return w

    def _refresh_assign_btns(self):
        if not self._main_window:
            return
        cfg_map  = getattr(self._main_window, '_button_effect_configs', {})
        cur_name = self._selected_card or ""
        for i, btn in self._assign_btns.items():
            cfg   = cfg_map.get(i, {})
            is_me = isinstance(cfg, dict) and cfg.get("name") == cur_name and bool(cur_name)
            btn.blockSignals(True)
            btn.setChecked(is_me)
            btn.blockSignals(False)

    def _autosave_on_close(self):
        """À la fermeture, sauvegarde automatiquement les couches éditées sur tous
        les boutons déjà assignés à l'effet courant — plus besoin de cliquer E1-E8."""
        if not self._main_window or not self._selected_card or not self._layers:
            return
        cfg_map  = getattr(self._main_window, '_button_effect_configs', {})
        cur_name = self._selected_card
        eff_dict = next(
            (e for e in BUILTIN_EFFECTS + self._custom_effects if e.get("name") == cur_name),
            None
        )
        layers_data = [l.to_dict() for l in self._layers]
        saved = False
        cur_duration = self._timer_spin.value() if hasattr(self, '_timer_spin') else self._effect_duration
        for btn_idx, cfg in cfg_map.items():
            if isinstance(cfg, dict) and cfg.get("name") == cur_name:
                cfg["layers"]    = layers_data
                cfg["play_mode"] = self._play_mode
                cfg["duration"]  = cur_duration
                if eff_dict:
                    cfg["type"] = eff_dict.get("type", cfg.get("type", ""))
                saved = True
        # Mettre à jour les pads FX qui ont cet effet assigné
        fx_pads = getattr(self._main_window, 'fx_pads', None)
        if fx_pads:
            for col in fx_pads:
                for i, cfg in enumerate(col):
                    if isinstance(cfg, dict) and cfg.get("name") == cur_name:
                        cfg["layers"]    = layers_data
                        cfg["play_mode"] = self._play_mode
                        cfg["duration"]  = cur_duration
                        if eff_dict:
                            cfg["type"] = eff_dict.get("type", cfg.get("type", ""))
                        saved = True
        if saved:
            if hasattr(self._main_window, '_save_effect_assignments'):
                self._main_window._save_effect_assignments()  # also calls _refresh_active_effect_config
            if hasattr(self._main_window, '_save_akai_config_auto'):
                self._main_window._save_akai_config_auto()
        else:
            # Effet non assigné à un bouton ni FX pad → sauvegarder dans la bibliothèque d'effets
            lib = getattr(self._main_window, '_effect_library_configs', None)
            if lib is not None:
                lib[cur_name] = {
                    "name":      cur_name,
                    "type":      eff_dict.get("type", "") if eff_dict else "",
                    "layers":    layers_data,
                    "play_mode": self._play_mode,
                    "duration":  cur_duration,
                }
                if hasattr(self._main_window, '_save_effect_library'):
                    self._main_window._save_effect_library()  # also calls _refresh_active_effect_config
            # Aussi persister les couches éditées dans le fichier custom_effects
            # pour que les menus contextuels voient la version à jour
            for e in self._custom_effects:
                if e.get("name") == cur_name:
                    e["layers"] = layers_data
                    _save_custom_effects(self._custom_effects)
                    break

    def _on_assign(self, btn_idx: int):
        if not self._main_window or not self._selected_card:
            self._assign_btns[btn_idx].setChecked(False)
            return
        cur_name = self._selected_card
        eff_dict = next(
            (e for e in BUILTIN_EFFECTS + self._custom_effects if e.get("name") == cur_name),
            None
        )
        cfg = {
            "name":      cur_name,
            "type":      eff_dict.get("type", "") if eff_dict else "",
            "layers":    [l.to_dict() for l in self._layers],
            "play_mode": self._play_mode,
            "duration":  self._timer_spin.value() if hasattr(self, '_timer_spin') else self._effect_duration,
        }
        if hasattr(self._main_window, '_on_effect_assigned'):
            self._main_window._on_effect_assigned(btn_idx, cfg)
        self._refresh_assign_btns()

    # ── Header / Footer ───────────────────────────────────────────────────────

    def _mk_header(self):
        w = QWidget()
        w.setFixedHeight(46)
        w.setStyleSheet("background: #141414; border-bottom: 1px solid #1e1e1e;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 14, 0)
        title = QLabel("Editeur d'effets")
        title.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        lay.addWidget(title)
        if self._clips:
            n   = len(self._clips)
            sub = QLabel(f"— {n} bloc{'s' if n > 1 else ''} sélectionné{'s' if n > 1 else ''}")
            sub.setStyleSheet("color: #444; font-size: 11px; margin-left: 8px;")
            lay.addWidget(sub)
        lay.addStretch()
        return w

    def _mk_footer(self):
        w = QWidget()
        w.setFixedHeight(52)
        w.setStyleSheet("background: #141414; border-top: 1px solid #1e1e1e;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.addStretch()

        # ── Sortie live DMX ───────────────────────────────────────────────────
        # Volontairement un interrupteur, pas un envoi permanent : ouvrir
        # l'éditeur pendant un show ne doit pas prendre la main sur les lampes.
        self._btn_live_dmx = QPushButton("  Sortie live")
        self._btn_live_dmx.setCheckable(True)
        self._btn_live_dmx.setFixedHeight(34)
        self._btn_live_dmx.setCursor(Qt.PointingHandCursor)
        self._btn_live_dmx.setToolTip(
            "Envoie l'aperçu sur le DMX : tes projecteurs jouent l'effet\n"
            "pendant que tu le règles.\n"
            "Désactivé, l'éditeur ne touche à rien.")
        self._live_dmx_off_ss = (
            "QPushButton{background:#1e1e1e;color:#888;border:1px solid #2e2e2e;"
            "border-radius:6px;font-size:12px;padding:0 14px;}"
            "QPushButton:hover{background:#2a2a2a;color:#ccc;}")
        self._live_dmx_on_ss = (
            "QPushButton{background:#3a0f0f;color:#ff5555;border:1px solid #ff5555;"
            "border-radius:6px;font-size:12px;font-weight:bold;padding:0 14px;}")
        self._btn_live_dmx.setStyleSheet(self._live_dmx_off_ss)
        self._btn_live_dmx.toggled.connect(self._on_live_dmx_toggled)
        lay.addWidget(self._btn_live_dmx)

        cancel = QPushButton("Annuler")
        cancel.setFixedSize(96, 34)
        cancel.setStyleSheet("""
            QPushButton {
                background: #1e1e1e; color: #aaa;
                border: 1px solid #2e2e2e; border-radius: 6px; font-size: 12px;
            }
            QPushButton:hover { background: #2a2a2a; }
        """)
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel)

        ok = QPushButton("Sauvegarder")
        ok.setFixedSize(116, 34)
        ok.setStyleSheet("""
            QPushButton {
                background: #00d4ff; color: #000; border: none;
                border-radius: 6px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: #00bce0; }
        """)
        ok.clicked.connect(self._apply)
        lay.addWidget(ok)
        return w

    # ── Gestion des couches ───────────────────────────────────────────────────

    def _rebuild_rows(self):
        pass  # Layer rows replaced by SimpleEffectPanel

    def _get_saved_layers_for(self, name: str) -> list:
        """Retourne les EffectLayer sauvegardés pour cet effet (priorité : config active > FX pads > boutons)."""
        saved_cfg = self._get_saved_cfg_for(name)
        layers_data = saved_cfg.get("layers", []) if saved_cfg else []
        if layers_data:
            return [EffectLayer.from_dict(d) for d in layers_data]
        return []

    def _get_saved_cfg_for(self, name: str) -> dict:
        """Retourne le dict de config complet sauvegardé pour cet effet (play_mode, duration, layers).
        Priorité : config active en cours > pads FX > boutons assignés > bibliothèque d'effets."""
        if not self._main_window or not name:
            return {}
        # Priorité 1 : config en cours d'exécution (ce qui joue vraiment)
        active_cfg = getattr(self._main_window, 'active_effect_config', None)
        if isinstance(active_cfg, dict) and active_cfg.get("name") == name:
            return active_cfg
        # Priorité 2 : pads FX (assignation directe)
        fx_pads = getattr(self._main_window, 'fx_pads', None)
        if fx_pads:
            for col in fx_pads:
                for cfg in col:
                    if isinstance(cfg, dict) and cfg.get("name") == name:
                        return cfg
        # Priorité 3 : boutons AKAI assignés
        cfg_map = getattr(self._main_window, '_button_effect_configs', {})
        for cfg in cfg_map.values():
            if isinstance(cfg, dict) and cfg.get("name") == name:
                return cfg
        # Priorité 4 : bibliothèque d'effets (édités mais non assignés)
        lib = getattr(self._main_window, '_effect_library_configs', {})
        if name in lib:
            return lib[name]
        return {}

    def _apply_preset(self, eff: dict):
        """Remplace les couches par le preset et met à jour le panneau central."""
        self._selected_card = eff.get("name", "")
        self._layers.clear()
        # Priorité 1 : couches vivantes de l'effet actif en live (édition en temps réel)
        mw = self._main_window
        live_cfg = getattr(mw, 'active_effect_config', {}) if mw else {}
        live_layers = []
        if isinstance(live_cfg, dict) and live_cfg.get('name') == self._selected_card:
            live_layers = [EffectLayer.from_dict(d) for d in live_cfg.get('layers', [])]
        saved_cfg = self._get_saved_cfg_for(self._selected_card)
        if live_layers:
            self._layers.extend(live_layers)
        else:
            # Priorité 2 : couches sauvegardées sur un bouton/bibliothèque
            saved_layers = [EffectLayer.from_dict(d) for d in saved_cfg.get("layers", [])] if saved_cfg else []
            if saved_layers:
                self._layers.extend(saved_layers)
            else:
                self._layers.extend(EffectLayer.layers_from_builtin(eff))
        # Restaurer play_mode et duration depuis la config sauvegardée
        if saved_cfg:
            self._play_mode       = saved_cfg.get("play_mode", self._play_mode)
            self._effect_duration = saved_cfg.get("duration",   self._effect_duration)
            if hasattr(self, '_timer_spin'):
                self._timer_spin.setValue(self._effect_duration)
            self._refresh_mode_btns()
        self._simple_panel.set_effect(eff, self._layers)
        self._rebuild_library()
        self._refresh_assign_btns()
        self._start_preview()

    # ── Prévisualisation live ─────────────────────────────────────────────────

    def _start_preview(self):
        self._preview_t0 = _time.monotonic()
        if not self._preview_timer.isActive():
            self._preview_timer.start(40)   # ~25 fps

    def _ensure_preview_running(self):
        if not self._preview_timer.isActive() and self._layers:
            if not self._preview_t0:
                self._preview_t0 = _time.monotonic()
            self._preview_timer.start(40)

    def _stop_preview(self):
        self._preview_timer.stop()
        # L'aperçu s'arrête → plus personne n'alimente les overrides. Les
        # laisser en place figerait les projecteurs sur la dernière frame.
        self._release_live_dmx()
        plan = getattr(self, '_plan_widget', None)
        if plan is not None:
            try:
                plan.set_htp_overrides(None)
            except Exception:
                pass

    def _push_layers_to_live(self):
        """Pousse les couches éditées dans active_effect_config si l'effet est actif en live."""
        mw = self._main_window
        if not mw or not self._selected_card:
            return
        cfg = getattr(mw, 'active_effect_config', {})
        if isinstance(cfg, dict) and cfg.get('name') == self._selected_card:
            cfg['layers'] = [l.to_dict() for l in self._layers]

    def _on_live_dmx_toggled(self, checked):
        """Active/coupe l'envoi DMX de l'aperçu."""
        btn = self._btn_live_dmx
        btn.setText("  ⏺  Sortie live" if checked else "  Sortie live")
        btn.setStyleSheet(self._live_dmx_on_ss if checked else self._live_dmx_off_ss)
        mw = self._main_window
        if mw is None:
            return
        if checked:
            if not self._preview_timer.isActive() and self._layers:
                self._preview_t0 = _time.monotonic()
                self._preview_timer.start(40)
        else:
            # Rendre la main immédiatement, sans attendre le prochain tick
            mw._editor_live_overrides = None

    def _release_live_dmx(self):
        """Coupe la sortie live — à appeler sur toute sortie de l'éditeur."""
        mw = self._main_window
        if mw is not None:
            mw._editor_live_overrides = None

    def closeEvent(self, event):
        self._release_live_dmx()
        super().closeEvent(event)

    def done(self, r):
        # Couvre Sauvegarder ET Annuler ET la croix : sans ça, fermer l'éditeur
        # laisserait les projecteurs figés sur la dernière frame d'aperçu.
        self._release_live_dmx()
        super().done(r)

    def _preview_tick(self):
        plan = getattr(self, '_plan_widget', None)
        if not self._layers:
            self._stop_preview()
            return
        # Si l'effet est actif en live, synchroniser le temps pour que le décalage
        # affiché dans la 3D corresponde exactement à ce qui tourne sur le DMX
        mw = self._main_window
        if mw and getattr(mw, 'active_effect', None) == self._selected_card:
            t = _time.monotonic() - getattr(mw, 'effect_t0', self._preview_t0)
        else:
            t = _time.monotonic() - self._preview_t0
        try:
            overrides = self._compute_preview(t)
            if plan is not None:
                plan.set_htp_overrides(overrides)
            # Sortie live : la boucle DMX les applique puis les restaure
            if self._main_window is not None:
                self._main_window._editor_live_overrides = (
                    overrides if self._btn_live_dmx.isChecked() else None)
            # Alimenter la mini strip (même filtre anti-fumée que _compute_preview)
            all_proj = getattr(self._main_window, 'projectors', [])
            strip_proj = [p for p in all_proj if getattr(p, 'group', '') != 'fumee'][:16]
            if strip_proj and overrides:
                levels = [overrides[id(p)][0] if id(p) in overrides else 0.0 for p in strip_proj]
                colors = [overrides[id(p)][1] if id(p) in overrides else QColor(0, 0, 0) for p in strip_proj]
                self._simple_panel.set_preview_levels(levels, colors)
            self._simple_panel.tick(t)
        except Exception:
            pass

    @staticmethod
    def _wave(forme: str, x: float) -> float:
        """Valeur 0-1 de la forme pour une position x (0-1) dans le cycle."""
        if forme == "Sinus":
            return (math.sin(2 * math.pi * x) + 1) / 2
        elif forme == "Flash":
            return 1.0 if x < 0.5 else 0.0
        elif forme == "Triangle":
            return 1.0 - abs(2 * x - 1)
        elif forme == "Montée":
            return x
        elif forme == "Descente":
            return 1.0 - x
        elif forme == "Fixe":
            return 1.0
        elif forme == "Off":
            return 0.0
        return 0.0  # Audio géré séparément

    def _compute_preview(self, t: float) -> dict:
        """Calcule {id(proj): (level, QColor)} depuis self._layers."""
        # Fix F : exclure la fumée (identique à l'exécution live)
        projectors = [p for p in getattr(self._main_window, 'projectors', [])
                      if getattr(p, 'group', '') != 'fumee']
        if not projectors or not self._layers:
            return {}

        # Fix A : appliquer le fader FX pour que la vitesse preview = vitesse live
        fader_mult = max(0.01, getattr(self._main_window, 'effect_speed', 80) / 100.0)

        n      = len(projectors)
        result = {}

        for i, proj in enumerate(projectors):
            dim = 0.0; r = 0.0; g = 0.0; b = 0.0
            has_dim = False
            has_rgb_layer = False
            has_movement = False
            pan_v  = 32768
            tilt_v = 32768

            _LETTER_TO_GROUP = {
                "A": "face", "B": "lat", "C": "contre",
                "D": "douche1", "E": "douche2", "F": "douche3",
                "G": "groupe_g", "H": "groupe_h",
            }
            for layer in self._layers:
                preset = layer.target_preset
                groups = list(getattr(layer, 'target_groups', []))
                if preset == "Pair"   and i % 2 != 0: continue
                if preset == "Impair" and i % 2 != 1: continue
                if preset in _LETTER_TO_GROUP and getattr(proj, 'group', '') != _LETTER_TO_GROUP[preset]: continue
                if groups and getattr(proj, 'group', '') not in [_LETTER_TO_GROUP.get(g, g) for g in groups]: continue

                freq      = (0.05 + layer.speed / 100.0 * 7.0) * fader_mult
                spread    = layer.spread / 100.0
                # Mouvement (Pan/Tilt) : plafonner a 1.0 = etalement parfait, pas de
                # re-enroulement des lyres au-dela (idem moteur live).
                if layer.attribute in ("Pan", "Tilt", "Pan/Tilt"):
                    spread = min(1.0, spread)
                phase     = layer.phase  / 100.0
                direction = getattr(layer, 'direction', 1)
                if direction == 0:   # bounce
                    t_osc = abs(2 * ((freq * t) % 1.0) - 1)
                    x = (t_osc + i / max(n, 1) * spread + phase) % 1.0
                elif direction == -1:  # arrière
                    x = (freq * t - i / max(n, 1) * spread + phase) % 1.0
                else:                  # avant (défaut)
                    x = (freq * t + i / max(n, 1) * spread + phase) % 1.0

                if layer.forme == "Audio":
                    rng = _rnd.Random(int(t * 15) * 100 + i)
                    raw = max(0.0, min(1.0, 0.5 + rng.uniform(-0.4, 0.4)))
                else:
                    raw = self._wave(layer.forme, x)

                # FADE : adoucit la forme vers un sinus (0=dur, 100=doux)
                fade_f = getattr(layer, 'fade', 0) / 100.0
                if fade_f > 0:
                    sin_val = (math.sin(2 * math.pi * x) + 1) / 2
                    raw = raw * (1.0 - fade_f) + sin_val * fade_f

                min_v = getattr(layer, 'min_val', 0) / 100.0
                max_v = getattr(layer, 'max_val', 100) / 100.0
                scaled = (min_v + raw * (max_v - min_v)) * layer.size / 100.0

                attr = layer.attribute
                if attr in ("Dimmer", "Strobe"):
                    dim += scaled; has_dim = True
                elif attr == "R": r += scaled; has_rgb_layer = True
                elif attr == "V": g += scaled; has_rgb_layer = True
                elif attr == "B": b += scaled; has_rgb_layer = True
                elif attr == "RGB":
                    has_rgb_layer = True
                    c1 = QColor(getattr(layer, 'color1', '#ffffff'))
                    r += c1.redF()   * scaled
                    g += c1.greenF() * scaled
                    b += c1.blueF()  * scaled
                elif attr == "Permut":
                    # raw = 0..1 (forme). Color1 ↔ Color2 selon raw.
                    # Pour Flash: raw=1 → c1, raw=0 → c2. Pour Sinus: blend doux.
                    has_rgb_layer = True
                    c1 = QColor(getattr(layer, 'color1', '#ff0000'))
                    c2 = QColor(getattr(layer, 'color2', '#0000ff'))
                    amp = layer.size / 100.0
                    r2 = 1.0 - raw  # fraction dans c2
                    r += (c1.redF()   * raw + c2.redF()   * r2) * amp
                    g += (c1.greenF() * raw + c2.greenF() * r2) * amp
                    b += (c1.blueF()  * raw + c2.blueF()  * r2) * amp
                elif attr == "Pan":
                    amp = (layer.size / 100.0) * 8192 * PAN_ANGULAR_RATIO
                    sym_pan  = getattr(layer, 'sym_pan', False)
                    pan_sign = -1 if (sym_pan and i * 2 >= n) else 1
                    pan_v = int(max(0, min(65535, 32768 + pan_sign * (raw - 0.5) * 2 * amp)))
                    has_movement = True
                elif attr == "Tilt":
                    amp = (layer.size / 100.0) * 8192
                    tilt_v = int(max(0, min(65535, 32768 + (raw - 0.5) * 2 * amp)))
                    has_movement = True
                elif attr == "Pan/Tilt":
                    sid      = getattr(layer, 'mouvement_shape', 'cercle')
                    sdef     = PAN_TILT_SHAPES.get(sid, PAN_TILT_SHAPES.get('cercle', {}))
                    pan_cfg  = sdef.get('pan',  ('Sinus',  0, 1.0))
                    tilt_cfg = sdef.get('tilt', ('Sinus', 25, 1.0))
                    pt_amp   = (layer.size / 100.0) * 8192
                    sym_pan  = getattr(layer, 'sym_pan', False)
                    pan_sign = -1 if (sym_pan and i * 2 >= n) else 1
                    p_forme, p_ph, p_mult = pan_cfg
                    if p_forme and p_forme != "Fixe":
                        p_freq = (0.05 + layer.speed * p_mult / 100.0 * 7.0) * fader_mult
                        p_x    = (p_freq * t + i / max(n, 1) * spread + phase + p_ph / 100.0) % 1.0
                        p_raw  = self._wave(p_forme, p_x)
                        pan_v  = int(max(0, min(65535, 32768 + pan_sign * (p_raw - 0.5) * 2 * pt_amp * PAN_ANGULAR_RATIO)))
                    t_forme, t_ph, t_mult = tilt_cfg
                    if t_forme and t_forme != "Fixe":
                        t_freq = (0.05 + layer.speed * t_mult / 100.0 * 7.0) * fader_mult
                        t_x    = (t_freq * t + i / max(n, 1) * spread + phase + t_ph / 100.0) % 1.0
                        t_raw  = self._wave(t_forme, t_x)
                        tilt_v = int(max(0, min(65535, 32768 + (t_raw - 0.5) * 2 * pt_amp)))
                    has_movement = True
                # Gobo ignoré pour la prévisualisation

            level = min(1.0, dim) if has_dim else 1.0
            has_color = r > 0 or g > 0 or b > 0
            if has_color:
                color = QColor(min(255, int(r * 255)),
                               min(255, int(g * 255)),
                               min(255, int(b * 255)))
                if not has_dim:
                    level = min(1.0, max(r, g, b))
            elif has_rgb_layer:
                # Couche couleur présente mais en phase off → noir (pas blanc)
                color = QColor(0, 0, 0)
                if not has_dim:
                    level = 0.0
            elif has_dim:
                # Dimmer seul : oscille la couleur existante du projecteur
                # level est déjà appliqué par _get_fill_color, on passe la couleur brute
                color = QColor(proj.color)
            elif has_movement:
                # Pan/Tilt seul : NE force PAS de couleur/intensité (parité avec la
                # restitution réelle, qui laisse la lyre dans son état). L'effet ne
                # fait que DÉPLACER la lyre — sa couleur vient d'un bloc/mémoire.
                color = QColor(proj.color)
                level = getattr(proj, 'level', 0) / 100.0
            else:
                # Aucune couche ne cible ce projecteur → ne pas forcer de couleur
                continue

            result[id(proj)] = (level, color, pan_v, tilt_v)

        return result

    # ── Mode de lecture ───────────────────────────────────────────────────────

    def _set_play_mode(self, mode: str):
        self._play_mode = mode
        self._refresh_mode_btns()

    def _refresh_mode_btns(self):
        _on  = "background:#00d4ff;color:#000;border-color:#00d4ff;"
        _off = "background:#1a1a1a;color:#666;border-color:#2a2a2a;"
        _s   = "QPushButton{{{inner}border-radius:4px;font-size:10px;font-weight:bold;padding:0 8px;}}"
        self._btn_loop.blockSignals(True)
        self._btn_once.blockSignals(True)
        self._btn_loop.setChecked(self._play_mode == "loop")
        self._btn_once.setChecked(self._play_mode == "once")
        self._btn_loop.blockSignals(False)
        self._btn_once.blockSignals(False)
        self._btn_loop.setStyleSheet(_s.format(inner=_on if self._play_mode == "loop" else _off))
        self._btn_once.setStyleSheet(_s.format(inner=_on if self._play_mode == "once" else _off))

    # ── Application ───────────────────────────────────────────────────────────

    def _apply(self):
        data = [layer.to_dict() for layer in self._layers]
        for clip in self._clips:
            clip.effect_layers    = data
            clip.effect_play_mode = self._play_mode
            clip.effect_duration  = self._timer_spin.value()
            clip.effect_name      = self._selected_card or ""
        self.accept()
