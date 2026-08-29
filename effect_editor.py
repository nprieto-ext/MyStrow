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
    QGridLayout, QMenu, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF, Signal, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QConicalGradient, QRadialGradient

from core import (projector_selection_keys, layer_selection_ranks,
                  block_index, chase_slot, layer_frequency, random_wave,
                  effect_dim_base_color, position_preset_values,
                  find_position_preset, ComboSansMolette)
from i18n import tr


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

# « Un par un » n'est pas une forme d'onde comme les autres : sa position vient
# du RANG de la fixture, pas d'une courbe échantillonnée. C'est ce qui lui permet
# de n'allumer qu'une fixture (ou qu'un paquet) à la fois — voir `core.chase_slot`.
FORMES = ["Sinus", "Flash", "Triangle", "Montée", "Descente", "Un par un",
          "Aléatoire", "Fixe", "Off"]

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
# « libre » reste défini dans PAN_TILT_SHAPES (compat des anciens effets) mais
# n'est plus proposé dans le menu — le défaut est désormais « cercle ».
_PT_SHAPE_ORDER = ["cercle", "huit", "infini", "balancier", "pendule", "carre"]

# Migration des anciens noms (fichiers .tui sauvegardés avant la refonte)
_FORME_COMPAT = {
    "Chase": "Flash", "Phase 1": "Montée", "Phase 2": "Descente",
    "Phase 3": "Triangle", "Sinusoïdale": "Sinus",
    "Toujours au max": "Fixe", "Toujours au min": "Off",
    "Son": "Aléatoire", "Pause": "Fixe",
    # « Audio » = ancien nom trompeur (ne réagissait pas au son dans un effet,
    # juste un scintillement aléatoire) → renommé « Aléatoire ».
    "Audio": "Aléatoire",
}


# ─── Styles ───────────────────────────────────────────────────────────────────

_MENU_STYLE = """
    QMenu {
        background: #1a1a2e; color: #ccc;
        border: 1px solid #333; border-radius: 4px;
    }
    QMenu::item { padding: 5px 18px; }
    QMenu::item:selected { background: #2a2a4e; color: #fff; }
    QMenu::item:disabled { color: #555; }
    QMenu::separator { height: 1px; background: #333; margin: 2px 0; }
"""

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
    QComboBox:disabled {
        background: #080808; color: #2b2b2b; border-color: #141414;
    }
    QComboBox::drop-down { border: none; width: 12px; }
    QComboBox QAbstractItemView {
        background: #1a1a1a; color: #ccc; border: 1px solid #00d4ff;
        selection-background-color: #003344; selection-color: #00d4ff;
        outline: none; font-size: 10px;
    }
"""


# ─── Modèle de données ────────────────────────────────────────────────────────

def _norm_selection(raw):
    """Normalise une liste de sélection en [[groupe, index_local(int)], ...].

    Tolère les tuples/listes venus du JSON et ignore les entrées malformées.
    """
    out = []
    for pair in (raw or []):
        try:
            g, li = pair
            out.append([g, int(li)])
        except Exception:
            continue
    return out


def _norm_pos_idx(raw):
    """Index de preset de position, ou None (= centre de course par défaut)."""
    if raw is None or raw == "":
        return None
    try:
        idx = int(raw)
    except (TypeError, ValueError):
        return None
    return idx if idx >= 0 else None


def _norm_block(raw):
    """Taille de paquet GROUPER, ramenée à un entier ≥ 1.

    Un effet enregistré avant l'arrivée de la colonne n'a pas la clé : il vaut
    1, soit exactement l'ancien comportement (une fixture par phase).
    """
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


class EffectLayer:
    """Données d'une couche d'effet (sérialisé en dict JSON dans LightClip)."""

    def __init__(self):
        self.attribute     = "Dimmer"
        self.forme         = "Sinus"
        self.target_preset = "Tous"
        self.target_groups = []
        # Cible « Sélection » : liste figée de projecteurs précis, identifiés par
        # (groupe, index_local) — même convention que le plan de feu. Active quand
        # target_preset == "Selection". Prime sur le groupe d'un clip en REC.
        self.target_selection = []
        self.speed     = 50    # vitesse du cycle 0-100
        self.size      = 100   # amplitude 0-100
        self.spread    = 0     # décalage de phase entre fixtures 0-100
        self.phase     = 0     # décalage global de phase 0-100 (0=no shift, 50=½ cycle, 100=full cycle)
        self.fade      = 0     # adoucissement de la forme 0=dur 100=doux
        self.direction = 1     # sens : 1=avant, -1=arrière, 0=bounce
        self.min_val   = 0     # plancher de sortie 0-100
        self.max_val   = 100   # plafond de sortie 0-100
        # Amplitude min/max PAR GROUPE (plancher/plafond d'intensité). Global à
        # l'effet mais répliqué sur chaque couche → persiste partout où les
        # couches sont sérialisées (clips, boutons, pads, bibliothèque, .lrec).
        # {nom_groupe: [min, max]} ; groupes absents = 0→100.
        self.group_amp = {}
        self.color1 = "#ff0000"
        self.color2 = "#0000ff"
        self.mouvement_shape = "cercle"  # forme de trajectoire Pan/Tilt (défaut)
        self.sym_pan = False            # miroir pan sur la 2e moitié des fixtures
        # POSITION : point AUTOUR duquel tourne un mouvement Pan/Tilt. Sans elle,
        # la trajectoire est centrée au milieu de la course (32768) — un cercle
        # « au centre du plateau ». Un preset de position donne à CHAQUE lyre son
        # propre centre, donc le cercle tourne autour de son point de visée.
        # None = pas de position choisie (centre par défaut). L'index suit la
        # convention des clips de position ; le nom sert de filet si la liste
        # de presets a bougé.
        self.pos_preset_idx  = None
        self.pos_preset_name = ""
        # Répartition du décalage entre fixtures (voir SPREAD_MODES) :
        # "lineaire" = chenillard 1,2,3… ; "miroir_in" = 1&8, 2&7, 3&6…
        self.spread_mode = "lineaire"
        # GROUPER : taille des paquets de fixtures qui partent ENSEMBLE. 1 = une
        # fixture à la fois (comportement historique). 5 sur 25 projecteurs =
        # 5 paquets de 5, donc un chenillard rangée par rangée au lieu de projo
        # par projo. Le paquet suit l'ordre de répartition, donc l'ordre de la
        # sélection quand la cible est « Sélection ».
        self.block = 1

    def to_dict(self):
        return {
            "attribute":     self.attribute,
            "forme":         self.forme,
            "target_preset": self.target_preset,
            "target_groups": list(self.target_groups),
            "target_selection": [list(x) for x in (self.target_selection or [])],
            "speed":     self.speed,
            "size":      self.size,
            "spread":    self.spread,
            "phase":     self.phase,
            "fade":      self.fade,
            "direction": self.direction,
            "min_val":   self.min_val,
            "max_val":   self.max_val,
            "group_amp": {k: list(v) for k, v in (self.group_amp or {}).items()},
            "color1": self.color1,
            "color2": self.color2,
            "mouvement_shape": self.mouvement_shape,
            "sym_pan": self.sym_pan,
            "spread_mode": self.spread_mode,
            "block": self.block,
            "pos_preset_idx":  self.pos_preset_idx,
            "pos_preset_name": self.pos_preset_name,
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
        layer.target_selection = _norm_selection(d.get("target_selection"))
        layer.speed     = d.get("speed",  50)
        layer.size      = d.get("size",   d.get("amplitude", 100))
        layer.spread    = d.get("spread", 0)
        layer.phase     = d.get("phase",  0)
        layer.fade      = d.get("fade",   0)
        layer.direction = d.get("direction", 1)
        layer.min_val   = d.get("min_val", 0)
        layer.max_val   = d.get("max_val", 100)
        layer.group_amp = {k: list(v) for k, v in (d.get("group_amp") or {}).items()
                           if isinstance(v, (list, tuple)) and len(v) >= 2}
        layer.color1 = d.get("color1", "#ff0000")
        layer.color2 = d.get("color2", "#0000ff")
        layer.mouvement_shape = d.get("mouvement_shape", "libre")
        layer.sym_pan = d.get("sym_pan", False)
        layer.spread_mode = d.get("spread_mode", "lineaire")
        layer.block = _norm_block(d.get("block"))
        layer.pos_preset_idx  = _norm_pos_idx(d.get("pos_preset_idx"))
        layer.pos_preset_name = d.get("pos_preset_name", "") or ""
        return layer

    @classmethod
    def layers_from_builtin(cls, eff: dict) -> list:
        result = []
        for ld in eff.get("layers", []):
            layer = cls()
            layer.attribute     = ld.get("attribute",     "Dimmer")
            _bf                 = ld.get("forme",         "Sinus")
            layer.forme         = _FORME_COMPAT.get(_bf, _bf)  # ex. « Audio » → « Aléatoire »
            layer.target_preset = ld.get("target_preset", "Tous")
            layer.target_groups = list(ld.get("target_groups", []))
            layer.target_selection = _norm_selection(ld.get("target_selection"))
            layer.speed     = ld.get("speed",  50)
            layer.size      = ld.get("size",   100)
            layer.spread    = ld.get("spread", 0)
            layer.phase     = ld.get("phase",  0)
            layer.fade      = ld.get("fade",   0)
            layer.direction = ld.get("direction", 1)
            layer.min_val   = ld.get("min_val", 0)
            layer.max_val   = ld.get("max_val", 100)
            layer.group_amp = {k: list(v) for k, v in (ld.get("group_amp") or {}).items()
                               if isinstance(v, (list, tuple)) and len(v) >= 2}
            layer.color1 = ld.get("color1", "#ff0000")
            layer.color2 = ld.get("color2", "#0000ff")
            layer.mouvement_shape = ld.get("mouvement_shape", "libre")
            layer.sym_pan = ld.get("sym_pan", False)
            layer.spread_mode = ld.get("spread_mode", "lineaire")
            layer.block = _norm_block(ld.get("block"))
            layer.pos_preset_idx  = _norm_pos_idx(ld.get("pos_preset_idx"))
            layer.pos_preset_name = ld.get("pos_preset_name", "") or ""
            result.append(layer)
        return result


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
        self.setToolTip(tr("ee2_pick_colour"))

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


# ─── Fonction d'onde (module-level) ──────────────────────────────────────────

def _layer_wave(forme: str, x: float) -> float:
    """Valeur 0-1 de la forme pour position x dans le cycle.

    « Un par un » n'a pas de courbe propre : sa position vient du rang de la
    fixture, pas de x (voir `core.chase_slot`). On rend ici une impulsion
    étroite, qui est ce que la vignette du tableau doit montrer — et qui reste
    un repli lisible si un chemin oubliait le cas particulier.
    """
    if forme == "Sinus":      return (math.sin(2 * math.pi * x) + 1) / 2
    elif forme == "Flash":    return 1.0 if x < 0.5 else 0.0
    elif forme == "Triangle": return 1.0 - abs(2 * x - 1)
    elif forme == "Montée":   return x
    elif forme == "Descente": return 1.0 - x
    elif forme == "Un par un": return 1.0 if x < 0.25 else 0.0
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

    def __init__(self, layer, parent=None, w=110, h=30):
        super().__init__(parent)
        self._layer = layer
        self._t     = 0.0
        self.setFixedSize(w, h)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_layer(self, layer):
        """Rebrancher la courbe sur une autre couche (réutilisation de la ligne)."""
        self._layer = layer
        self.update()

    def set_width(self, w):
        """Partie élastique de la cellule FORME : la courbe s'étire ou se serre.

        La courbe est échantillonnée sur sa largeur en pixels, elle reste donc
        juste à n'importe quelle taille — contrairement au nom de la forme, qui
        devient illisible dès qu'il est tronqué.
        """
        w = int(w)
        if w != self.width():
            self.setFixedWidth(w)
            self.update()

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
        freq   = layer_frequency(layer.speed)
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
            if layer.forme in ("Audio", "Aléatoire"):   # ancien nom + nouveau
                raw = random_wave(freq, self._t, xi)
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

    def __init__(self, layer, parent=None, size=34):
        super().__init__(parent)
        self._layer = layer
        self._t     = 0.0
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_layer(self, layer):
        """Rebrancher la trajectoire sur une autre couche."""
        self._layer = layer
        self.update()

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
        # Suit le VRAI mouvement : le SENS (direction) fait tourner le point dans
        # le bon sens, comme les lyres (→ avant · ← inverse · ↔ aller-retour).
        freq = max(0.01, layer.speed / 100.0) * 2.0
        _d   = getattr(layer, 'direction', 1)
        if _d == 0:      # aller-retour
            t_anim = abs(2 * ((self._t * freq) % 1.0) - 1)
        elif _d == -1:   # inverse
            t_anim = -self._t * freq
        else:            # avant
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


# ─── Tableau des couches ──────────────────────────────────────────────────────

# Une couche d'effet = une ligne, à la façon d'un pupitre GrandMA. L'en-tête et
# les lignes partagent cette table de colonnes : elle seule garantit que tout
# reste aligné, quelle que soit la largeur de la fenêtre.
#   (clé, titre, largeur px, infobulle)
LAYER_COLS = [
    ("cible",  "CIBLE",        74,
     "Quelles fixtures jouent cette couche.\n"
     "Tous, une sur deux, ou des groupes précis."),
    ("canal",  "CANAL",        76,
     "Le paramètre animé : intensité, couleur, position…"),
    ("forme",  "FORME",       166,
     "La courbe que suit le canal.\n"
     "Sur une couche Pan/Tilt : la trajectoire de la lyre."),
    ("vit",    "VIT",          42,
     "Vitesse du cycle.\n0 = très lent, 100 = très rapide.\n"
     "Molette = réglage au dixième (29,8 ≈ 128 BPM).\n"
     "Maj+molette = pas entier."),
    ("amp",    "AMP",          42,
     "Amplitude : intensité maximale atteinte par l'effet."),
    ("min",    "MIN",          42,
     "Niveau plancher : l'effet ne descend jamais en dessous.\n"
     "Au-dessus de 0, les projecteurs ne s'éteignent plus complètement."),
    ("max",    "MAX",          42,
     "Niveau plafond : l'effet ne monte jamais au-dessus."),
    ("dec",    "DÉC",          46,
     "Décalage entre fixtures — c'est lui qui crée le chenillard.\n"
     "0 = toutes ensemble · 180 = réparties sur un cycle · "
     "360 = deux motifs simultanés."),
    ("group",  "GROUPER",      52,
     "Nombre de fixtures qui partent ENSEMBLE, par paquets.\n"
     "1 = une par une (chenillard classique).\n"
     "5 sur 25 projecteurs = 5 paquets de 5 : la rangée entière s'allume\n"
     "d'un coup, et c'est la rangée qui défile.\n"
     "Les paquets suivent l'ordre de la CIBLE — donc l'ordre de sélection\n"
     "sur le plan quand la cible est « Sélection »."),
    ("fondu",  "FONDU",        46,
     "Adoucit la forme.\n0 = transitions franches, 100 = fondu doux.\n"
     "Combiné à la forme « Descente », c'est ce qui fait la traînée d'une comète."),
    ("depart", "DÉPART",       50,
     "Décale le démarrage de cette couche dans le cycle.\n"
     "0 = en même temps que les autres, 33 = un tiers de cycle plus tard.\n"
     "C'est ainsi qu'on décale R, V et B pour obtenir un arc-en-ciel."),
    ("sens",   "SENS",        102,   # 3 boutons carrés : voir LAYER_BTN
     "Sens de parcours des fixtures.\n"
     "→ direct · ← inverse · ↔ aller-retour"),
    ("coul",   "COUL.",        68,   # 2 pastilles carrées
     "Couleur(s) de la couche — canaux RGB et Permut uniquement."),
    ("pos",    "POSITION",     78,
     "Point autour duquel tourne le mouvement — canaux Pan, Tilt et Pan/Tilt.\n"
     "Sans position, la trajectoire est centrée au milieu de la course :\n"
     "un cercle « au centre du plateau », pour toutes les lyres au même endroit.\n"
     "Avec une position enregistrée, chaque lyre tourne autour de SON point\n"
     "de visée — le même que celui du rappel de position."),
    ("sym",    "SYM",          44,
     "Symétrie Pan — canaux Pan et Pan/Tilt.\n"
     "Les lyres situées à droite de l'axe partent en Pan INVERSÉ, celles de\n"
     "gauche en Pan normal : les trajectoires se répondent en miroir.\n"
     "C'est ce qui fait les ailes du « Lyre Papillon ».\n"
     "Le partage suit la POSITION sur le plan de feu, pas l'ordre du patch —\n"
     "même règle que le bouton SYM du plan 2D."),
    ("del",    "",             32, ""),
]

LAYER_COL_SPACING = 4
LAYER_ROW_H       = 54   # hauteur d'une ligne
LAYER_CELL_H      = 42   # hauteur des cellules à l'intérieur
LAYER_BTN         = 32   # côté des petits boutons carrés (sens, couleurs, ✕)
LAYER_ROW_BORDER  = 3    # bordure d'accent à gauche de chaque ligne
# Bordure des trois autres côtés du cadre d'une ligne. Elle a l'air anodine,
# mais Qt l'enlève de la zone de contenu au même titre que l'accent de gauche :
# une ligne dispose donc de 1 px de MOINS que l'en-tête, qui n'a pas de cadre.
# Non comptée, les colonnes réclamaient 1 px de plus que la place réelle et Qt
# rognait une cellule au hasard — tout ce qui suivait se décalait, d'où des
# titres qui ne tombaient plus en face de leurs cases.
LAYER_ROW_BORDER_R = 1
LAYER_WAVE_W      = 44   # aperçu de courbe, dans la cellule FORME
LAYER_TRAJ_W      = LAYER_CELL_H - 4   # aperçu de trajectoire (carré), idem
# L'aperçu de courbe est la partie élastique de la cellule FORME : il s'étire
# quand la fenêtre est large et cède le premier quand elle est étroite.
LAYER_WAVE_MAX_W  = 88
LAYER_WAVE_MIN_W  = 44

# Largeur totale du tableau à sa taille CONFORTABLE : c'est le point d'équilibre
# du calcul élastique — au-dessus les colonnes s'étirent, en dessous elles se
# resserrent jusqu'à leur plancher.
# La bordure d'accent est comptée ici et compensée par la marge de l'en-tête,
# sans quoi les titres seraient décalés de 3 px par rapport aux cellules.
LAYER_TABLE_W = (sum(c[2] for c in LAYER_COLS)
                 + LAYER_COL_SPACING * (len(LAYER_COLS) - 1)
                 + 12 + LAYER_ROW_BORDER + LAYER_ROW_BORDER_R)

# Largeur PLANCHER de chaque colonne, quand la fenêtre est trop étroite pour la
# largeur confortable. Absente = colonne incompressible.
#
# Sans ce resserrement, le tableau ne faisait que défiler horizontalement : à
# force d'ajouter des colonnes, le ✕ de suppression sortait de l'écran et une
# ligne devenait impossible à supprimer sans faire défiler. Mieux vaut des
# cellules serrées mais toutes atteignables.
#
# Les cellules à boutons carrés (SENS, COUL., ✕) n'ont pas de plancher : leurs
# boutons font 32 px fixes, les rétrécir les déformerait ou les tronquerait.
# Les cellules chiffrées descendent à 32 px : « 360 », la plus large valeur
# possible, y tient encore en Segoe UI 12 gras.
# FORME ne peut pas passer sous aperçu + liste à leurs minimums respectifs
# (LAYER_WAVE_MIN_W + espacement + 56), sans quoi son contenu déborderait de
# la cellule au lieu de la remplir.
_LAYER_COL_FLOOR = {
    "cible": 42, "canal": 48,
    "forme": LAYER_WAVE_MIN_W + 4 + 56,
    "vit": 32, "amp": 32, "min": 32, "max": 32, "dec": 32,
    "group": 32, "fondu": 32, "depart": 32,
    "pos": 40,
}

# Largeur du tableau une fois TOUT resserré : en dessous, le défilement
# horizontal reprend ses droits — il n'y a plus rien à gagner.
LAYER_TABLE_MIN_W = (sum(_LAYER_COL_FLOOR.get(c[0], c[2]) for c in LAYER_COLS)
                     + LAYER_COL_SPACING * (len(LAYER_COLS) - 1)
                     + 12 + LAYER_ROW_BORDER + LAYER_ROW_BORDER_R)

# Part de la place EXCÉDENTAIRE que prend chaque colonne quand la fenêtre est
# plus large que le tableau. 0 = colonne figée : les boutons carrés (sens,
# couleurs, ✕) ne gagnent rien à s'étirer, ils resteraient carrés au milieu
# d'une cellule vide. Les listes déroulantes et les libellés, eux, profitent de
# chaque pixel — c'est là que le texte est tronqué en fenêtre étroite.
LAYER_COL_FLEX = {
    "cible": 3, "canal": 3, "forme": 5,
    "vit": 2, "amp": 2, "min": 2, "max": 2, "dec": 2, "group": 2,
    "fondu": 2, "depart": 2,
    "sens": 0, "coul": 0, "pos": 3, "sym": 0, "del": 0,
}

_LAYER_COL_MIN = {c[0]: c[2] for c in LAYER_COLS}

# Ce qu'une colonne écrit dans une couche. Sert quand la colonne est
# sélectionnée : régler une case recopie ces attributs dans toutes les lignes.
# Une colonne peut porter plusieurs attributs — CIBLE en a deux (le préréglage
# et la liste de groupes), et les recopier séparément donnerait des lignes
# incohérentes.
LAYER_COL_ATTRS = {
    "cible":  ("target_preset", "target_groups", "target_selection"),
    "canal":  ("attribute",),
    "forme":  ("forme", "mouvement_shape"),
    "vit":    ("speed",),
    "amp":    ("size",),
    "min":    ("min_val",),
    "max":    ("max_val",),
    "dec":    ("spread",),
    "group":  ("block",),
    "fondu":  ("fade",),
    "depart": ("phase",),
    "sens":   ("direction",),
    "coul":   ("color1", "color2"),
    # Index ET nom : recopier le seul index sur une autre couche laisserait un
    # libellé faux dans sa cellule.
    "pos":    ("pos_preset_idx", "pos_preset_name"),
    "sym":    ("sym_pan",),
}


def layer_col_widths(dispo):
    """Largeur de chaque colonne pour une largeur de tableau `dispo`.

    Au-dessus de `LAYER_TABLE_W`, le surplus est distribué au prorata de
    `LAYER_COL_FLEX`. En dessous, le manque est repris aux colonnes qui ont
    de la marge (au prorata de cette marge) jusqu'à leur plancher : le tableau
    entier reste ainsi visible, ✕ de suppression compris, au lieu de déborder
    à droite. Sous `LAYER_TABLE_MIN_W` tout est au plancher et le défilement
    horizontal reprend.

    Dans les deux sens, le reliquat entier va à la dernière colonne concernée
    pour que la somme retombe EXACTEMENT sur la largeur demandée — sinon
    l'en-tête et les lignes dérivent de quelques pixels l'un par rapport à
    l'autre, et l'alignement du tableau saute.
    """
    largeurs = dict(_LAYER_COL_MIN)
    surplus  = int(dispo) - LAYER_TABLE_W

    if surplus < 0:
        manque = -surplus
        # Marge cédable de chaque colonne, dans l'ordre du tableau.
        marges = [(c[0], _LAYER_COL_MIN[c[0]] - _LAYER_COL_FLOOR[c[0]])
                  for c in LAYER_COLS if c[0] in _LAYER_COL_FLOOR]
        marges = [(k, m) for k, m in marges if m > 0]
        total  = sum(m for _, m in marges)
        if total <= 0:
            return largeurs
        if manque >= total:                 # tout au plancher
            for cle, _ in marges:
                largeurs[cle] = _LAYER_COL_FLOOR[cle]
            return largeurs
        repris = 0
        for cle, marge in marges:
            part = manque * marge // total
            largeurs[cle] -= part
            repris += part
        # Reliquat de la division entière : repris pixel par pixel sur les
        # colonnes qui ont encore de la marge. Le donner d'un bloc à la
        # dernière la ferait passer sous son plancher quand elle est étroite.
        i = 0
        while repris < manque and i < len(marges) * 64:
            cle = marges[i % len(marges)][0]
            if largeurs[cle] > _LAYER_COL_FLOOR[cle]:
                largeurs[cle] -= 1
                repris += 1
            i += 1
        return largeurs

    total = sum(LAYER_COL_FLEX.values())
    if surplus == 0 or total <= 0:
        return largeurs

    elastiques = [k for k, f in LAYER_COL_FLEX.items() if f > 0]
    donne = 0
    for cle in elastiques[:-1]:
        part = surplus * LAYER_COL_FLEX[cle] // total
        largeurs[cle] += part
        donne += part
    largeurs[elastiques[-1]] += surplus - donne
    return largeurs


def layer_table_width(dispo):
    """Largeur réellement occupée par le tableau dans `dispo` pixels."""
    return max(LAYER_TABLE_MIN_W, int(dispo))


class _ElasticBody(QWidget):
    """Conteneur qui signale la place réellement disponible pour le tableau.

    C'est lui qui déclenche le recalcul des colonnes : le tableau n'a pas de
    layout capable de s'étirer tout seul (chaque cellule est à largeur fixe,
    seul moyen de garder l'en-tête et les lignes rigoureusement alignés), donc
    quelqu'un doit redistribuer la place à chaque redimensionnement.

    On rapporte la largeur de la ZONE DE DÉFILEMENT, pas la sienne. Les lignes
    sont à largeur fixe : elles poussent la largeur minimale de ce conteneur:
    se mesurer soi-même revenait à lire la largeur qu'on vient d'imposer, donc
    à ne jamais voir qu'on est à l'étroit — les colonnes ne se resserraient
    jamais et le tableau débordait à droite, ✕ de suppression compris.
    """

    resized = Signal(int)

    def _dispo(self):
        p = self.parentWidget()          # viewport de la QScrollArea
        zone = p.parentWidget() if p is not None else None
        if zone is not None and hasattr(zone, 'viewport'):
            return zone.viewport().width()
        return self.width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.resized.emit(self._dispo())


class _ElasticScroll(QScrollArea):
    """Zone de défilement du tableau, qui signale la place qu'elle offre.

    Indispensable en plus de `_ElasticBody` : quand la fenêtre rétrécit sous la
    largeur du tableau, le conteneur intérieur garde sa taille (ses lignes sont
    fixes) et ne reçoit donc aucun resizeEvent. Seule la zone de défilement voit
    qu'elle a rapetissé — c'est elle qui doit demander le resserrement.
    """

    resized = Signal(int)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.resized.emit(self.viewport().width())

_SENS_TIPS = {
    1:  "Sens direct — 1, 2, 3… jusqu'à la dernière fixture",
    -1: "Sens inverse — de la dernière vers la première",
    0:  "Aller-retour — 1→8 puis 8→1, en boucle",
}


class _NumCell(QWidget):
    """Cellule chiffrée d'une ligne de couche.

    Glisser vers le haut/bas règle la valeur, la molette l'affine, un
    double-clic permet de la taper. Une jauge de fond donne le niveau d'un
    coup d'œil, sans prendre la place d'un curseur.
    """

    # Signal(object) et non Signal(int) : la cellule pilote aussi des grandeurs
    # décimales (cf. `decimals`). En mode entier — tous les usages historiques,
    # dont le tableau du plan 3D — elle émet toujours un int, les branchements
    # en place ne voient donc aucune différence.
    valueChanged = Signal(object)

    def __init__(self, value=0, maximum=100, width=42, accent="#00d4ff", parent=None,
                 minimum=0, height=None, decimals=0):
        super().__init__(parent)
        # `minimum` permet de réutiliser la cellule pour des grandeurs signées
        # (angles −180..180, coordonnées en cm). 0 par défaut : les couches
        # d'effet, seul usage historique, ne changent pas de comportement.
        # `decimals` ouvre le réglage sous l'unité (0 = entier, comportement
        # d'origine). Les bornes, elles, restent entières : aucune grandeur du
        # tableau n'a besoin d'un minimum ou d'un maximum fractionnaire.
        self._dec    = max(0, int(decimals))
        self._step   = 10.0 ** -self._dec     # plus petit écart représentable
        self._min    = int(minimum)
        self._max    = max(self._min + 1, int(maximum))
        self._value  = self._clamp(value)
        self._accent = accent
        self._drag_y = None
        self._drag_v = None
        self._edit   = None
        # « Mixte » : la cellule pilote plusieurs couches qui n'ont pas la même
        # valeur (en-tête de colonne). On affiche un tiret plutôt qu'un chiffre
        # qui ne correspondrait à aucune ligne.
        self._mixed  = False
        # `height` : le tableau du plan 3D veut des lignes plus compactes que
        # l'éditeur d'effets, où la cellule voisine des aperçus de courbe.
        self.setFixedSize(width, LAYER_CELL_H if height is None else int(height))
        self.setCursor(Qt.SizeVerCursor)

    def set_width(self, w):
        self.setFixedWidth(int(w))

    def value(self):
        return self._value

    def _clamp(self, v):
        """Valeur ramenée dans les bornes ET sur la grille de la cellule.

        Arrondir AVANT de comparer est ce qui rend `set_value` fiable en mode
        décimal : sans cela, deux gestes équivalents donneraient 29.8 et
        29.799999999999997 — deux flottants différents pour le même chiffre
        affiché, donc un signal de changement à chaque passage, et une couche
        marquée modifiée alors que rien n'a bougé à l'écran.

        Rend un int dès que la valeur n'a pas de partie fractionnaire, même sur
        une cellule décimale : sans cela, ouvrir l'éditeur suffirait à réécrire
        « speed: 50 » en « speed: 50.0 » dans tous les shows enregistrés — même
        valeur, mais un fichier qui change sans qu'on ait rien touché.
        """
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = float(self._min)
        v = max(float(self._min), min(float(self._max), v))
        if not self._dec:
            return int(round(v))
        v = round(v, self._dec)
        return int(v) if v == int(v) else v

    def _fmt(self, v):
        """Chiffre affiché. Une décimale nulle reste invisible.

        « 50 » et non « 50,0 » : la colonne fait 32 à 42 px et la plupart des
        valeurs tombent sur un entier. N'afficher la décimale que lorsqu'elle
        existe garde le tableau lisible, tout en signalant d'un coup d'œil les
        couches réglées finement. Virgule, comme la saisie l'accepte.
        """
        if not self._dec or float(v) == int(v):
            return str(int(v))
        return f"{float(v):.{self._dec}f}".replace(".", ",")

    def is_mixed(self):
        return self._mixed

    def set_mixed(self, mixed: bool):
        if bool(mixed) != self._mixed:
            self._mixed = bool(mixed)
            self.update()

    def set_value(self, v, emit=True):
        v = self._clamp(v)
        if v != self._value:
            self._value = v
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def _user_set(self, v):
        """Valeur posée par un geste de l'utilisateur.

        Sortir de l'état mixte doit émettre même si le chiffre ne bouge pas :
        trois couches à 20/45/45 ramenées à 45 restent un vrai changement pour
        deux d'entre elles, alors que `_value` valait déjà 45.
        """
        etait_mixte = self._mixed
        self._mixed = False
        if etait_mixte:
            self._value = self._clamp(v)
            self.update()
            self.valueChanged.emit(self._value)
        else:
            self.set_value(v)

    def set_accent(self, color):
        if color != self._accent:
            self._accent = color
            self.update()

    # ── Interaction ───────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_y = e.globalPosition().y()
            self._drag_v = self._value

    def mouseMoveEvent(self, e):
        if self._drag_y is not None:
            # 1 px = max/100 : la course complète tient dans ~100 px de geste,
            # que la plage aille jusqu'à 100 (niveaux) ou 360 (décalage).
            # Le pas reste ENTIER même sur une cellule décimale : le glisser est
            # le geste large, la molette le geste fin. Et comme le delta s'ajoute
            # à la valeur de DÉPART, une fraction posée à la molette traverse le
            # glissement intacte — 29,8 monte à 34,8 puis revient à 29,8.
            delta = int((self._drag_y - e.globalPosition().y())
                        * (self._max - self._min) / 100.0)
            self._user_set(self._drag_v + delta)

    def mouseReleaseEvent(self, _e):
        self._drag_y = None

    def wheelEvent(self, e):
        """Molette : le réglage fin. Maj enfoncé : le pas large.

        Sur une cellule décimale un cran vaut un dixième. C'est là que se gagne
        la précision d'une vitesse lente, où le cran entier fait sauter la
        période de plusieurs secondes. Maj+molette garde le pas d'origine pour
        traverser la plage sans y passer quatre cents crans.
        """
        gros = max(1, self._max // 100)
        pas  = gros if (not self._dec or (e.modifiers() & Qt.ShiftModifier)) else self._step
        self._user_set(self._value + (pas if e.angleDelta().y() > 0 else -pas))

    def mouseDoubleClickEvent(self, _e):
        self._start_edit()

    def changeEvent(self, e):
        # Une cellule grisée ne doit pas garder le curseur « glisser pour régler » :
        # il promettrait une action que le clic ne rend plus.
        if e.type() == QEvent.EnabledChange:
            self.setCursor(Qt.SizeVerCursor if self.isEnabled() else Qt.ArrowCursor)
            self.update()
        super().changeEvent(e)

    def _start_edit(self):
        if self._edit is not None:
            return
        ed = QLineEdit(self._fmt(self._value), self)
        ed.setGeometry(0, 0, self.width(), self.height())
        ed.setAlignment(Qt.AlignCenter)
        ed.setStyleSheet(
            "QLineEdit{background:#001a26;color:#00d4ff;border:1px solid #00d4ff;"
            "border-radius:4px;font-size:11px;font-weight:bold;padding:0;}")
        # La validation est liée à SON éditeur : editingFinished part aussi bien
        # sur Entrée que sur perte de focus, et éditer une seconde cellule fait
        # perdre le focus à la première — sans ce lien, le signal tardif de
        # l'ancienne cellule viendrait fermer l'éditeur de la nouvelle.
        ed.editingFinished.connect(lambda e=ed: self._commit_edit(e))
        self._edit = ed
        ed.show()
        ed.setFocus()
        ed.selectAll()

    def _commit_edit(self, ed):
        if ed is not self._edit:
            return          # éditeur déjà remplacé ou refermé : signal obsolète
        self._edit = None
        try:
            # Virgule ET point : le pavé numérique d'un clavier français tape
            # une virgule, la refuser rendrait la saisie décimale inutilisable.
            # `_clamp` ramène ensuite sur la grille — une cellule entière à qui
            # on tape « 29,8 » retient 30 plutôt que de rejeter la saisie.
            self._user_set(float(ed.text().strip().replace(",", ".")))
        except ValueError:
            pass            # saisie non numérique : on garde la valeur en place
        ed.deleteLater()

    # ── Rendu ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        live = self.isEnabled()

        # Fond + contour : sans contour, une cellule à 0 n'a plus de jauge et
        # se confond avec la ligne — la grille disparaît là où tout est à zéro.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0a0a0a" if live else "#080808"))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)

        # Jauge de fond proportionnelle : lire « 180 » demande un instant,
        # voir la barre aux trois quarts est immédiat. Éteinte si le réglage
        # est sans effet : afficher un niveau qui ne sert à rien induit en erreur.
        _etendue = float(self._max - self._min) or 1.0
        frac = (self._value - self._min) / _etendue
        if frac > 0 and live and not self._mixed:
            c = QColor(self._accent)
            c.setAlpha(46)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(0.5, 0.5, max(3.0, (w - 1) * frac), h - 1), 4, 4)

        p.setPen(QPen(QColor("#1e1e1e" if live else "#141414"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)

        if not live:
            col, txt = QColor("#2b2b2b"), self._fmt(self._value)
        elif self._mixed:
            # Valeurs différentes d'une ligne à l'autre : aucun chiffre ne serait
            # vrai, on affiche un tiret jusqu'au premier geste.
            col, txt = QColor("#555555"), "—"
        else:
            col = QColor("#dddddd") if self._value else QColor("#4a4a4a")
            txt = self._fmt(self._value)
        p.setPen(col)
        # « 29,8 » ne tient pas au corps 12 dans une colonne resserrée à 32 px :
        # on descend d'un cran plutôt que de laisser le chiffre déborder de sa
        # cellule. Réservé aux cellules décimales : les grandeurs entières
        # longues (« −180 » dans le tableau 3D) gardent leur taille d'origine.
        p.setFont(QFont("Segoe UI",
                        10 if (self._dec and len(txt) > 3) else 12, QFont.Bold))
        p.drawText(QRect(0, 0, w, h), Qt.AlignCenter, txt)
        p.end()


class _CiblePopup(QFrame):
    """Choix des fixtures visées : Tous / Pair / Impair, ou des groupes A-H.

    Reprend les pastilles de l'ancienne carte — c'est la seule commande qui a
    besoin de plus d'une cellule, donc elle s'ouvre par-dessus le tableau.
    """

    changed = Signal()

    _ON  = ("QPushButton{background:#001a2a;color:#00d4ff;border:1px solid #004466;"
            "border-radius:3px;font-size:9px;font-weight:bold;padding:0 5px;}"
            "QPushButton:hover{border-color:#006688;}")
    _OFF = ("QPushButton{background:#0c0c0c;color:#444;border:1px solid #1c1c1c;"
            "border-radius:3px;font-size:9px;font-weight:bold;padding:0 5px;}"
            "QPushButton:hover{border-color:#333;color:#888;}")

    def __init__(self, layers, parent=None, sel_source=None):
        super().__init__(parent, Qt.Popup)
        # Une liste : une seule couche pour une cellule de ligne, toutes les
        # couches quand le popup est ouvert depuis l'en-tête de colonne.
        self.layers = layers if isinstance(layers, (list, tuple)) else [layers]
        # Callable () -> iterable de (groupe, index_local) actuellement
        # sélectionnés sur le plan de feu. None = fonction Sélection indisponible.
        self._sel_source = sel_source
        self.setStyleSheet(
            "QFrame{background:#131313;border:1px solid #2a2a2a;border-radius:6px;}")

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(5)

        self._btns = {}

        r1 = QHBoxLayout()
        r1.setSpacing(3)
        for label in ["Tous", "Pair", "Impair"]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=label: self._pick(v, preset=True))
            self._btns[label] = b
            r1.addWidget(b)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(3)
        for label in ["A", "B", "C", "D", "E", "F", "G", "H"]:
            b = QPushButton(label)
            b.setFixedSize(24, 22)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=label: self._pick(v, preset=False))
            self._btns[label] = b
            r2.addWidget(b)
        v.addLayout(r2)

        # ── Cible « Sélection » : capture les projos sélectionnés sur le plan ──
        if self._sel_source is not None:
            b = QPushButton(tr("ee2_plan_select"))
            b.setFixedHeight(22)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(self._pick_selection)
            self._btns["Selection"] = b
            v.addWidget(b)
            self._sel_hint = QLabel("")
            self._sel_hint.setStyleSheet("color:#666;font-size:8px;")
            self._sel_hint.setAlignment(Qt.AlignCenter)
            v.addWidget(self._sel_hint)

        self._refresh()

    def _pick(self, val, preset):
        ref = self.layers[0] if self.layers else None
        if ref is None:
            return
        if preset:
            cible, groupes = val, []
        else:
            groupes = list(ref.target_groups)
            if val in groupes:
                groupes.remove(val)
            else:
                groupes.append(val)
            cible = "Tous" if not groupes else ""
        for couche in self.layers:
            couche.target_preset = cible
            couche.target_groups = list(groupes)
            # Quitter le mode « Sélection » dès qu'on repasse par un preset/groupe.
            couche.target_selection = []
        self._refresh()
        self.changed.emit()

    def _pick_selection(self):
        """Capte les projecteurs sélectionnés sur le plan et fige la cible dessus."""
        if self._sel_source is None:
            return
        try:
            keys = [[g, int(li)] for g, li in self._sel_source()]
        except Exception:
            keys = []
        for couche in self.layers:
            couche.target_preset    = "Selection"
            couche.target_groups    = []
            couche.target_selection = [list(k) for k in keys]
        self._refresh()
        self.changed.emit()

    def _refresh(self):
        ref = self.layers[0] if self.layers else None
        preset = (getattr(ref, 'target_preset', '') or "Tous") if ref else "Tous"
        groups = (getattr(ref, 'target_groups', None) or []) if ref else []
        is_sel = (preset == "Selection")
        for label, b in self._btns.items():
            if label == "Selection":
                active = is_sel
            elif label not in ("Tous", "Pair", "Impair"):
                active = (label in groups) and not is_sel
            else:
                active = (label == preset and not groups and not is_sel)
            b.setStyleSheet(self._ON if active else self._OFF)
        hint = getattr(self, '_sel_hint', None)
        if hint is not None:
            n = len(getattr(ref, 'target_selection', None) or []) if ref else 0
            hint.setText(f"{n} projecteur(s) figé(s), dans l'ordre 1→{n}" if is_sel
                         else "clique les projos sur le plan (1, 2, 3…), puis ici")


def cible_text(layer) -> str:
    """Résumé court de la cible, tel qu'affiché dans la cellule CIBLE."""
    if (getattr(layer, 'target_preset', '') == "Selection"):
        n = len(getattr(layer, 'target_selection', None) or [])
        return f"Sél. ({n})"
    groups = getattr(layer, 'target_groups', None) or []
    if groups:
        return ",".join(groups)
    return getattr(layer, 'target_preset', '') or "Tous"


class LayerTableHeader(QWidget):
    """Titres de colonnes, cliquables comme dans un tableur.

    Cliquer un titre sélectionne la colonne entière : à partir de là, régler
    UNE cellule de cette colonne écrit la même valeur dans toutes les lignes.
    Sans colonne sélectionnée, chaque cellule ne touche que sa propre couche.
    C'est donc l'utilisateur qui décide quand il travaille en masse — il n'y a
    pas de mode caché ni de ligne qui agirait toute seule.
    """

    column_clicked = Signal(str)

    _TITRE_H = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self._titres = {}    # clé de colonne → QPushButton de titre
        self._sel    = None
        self.setFixedWidth(LAYER_TABLE_W)
        self.setFixedHeight(self._TITRE_H)
        self.setStyleSheet("background: transparent;")

        th = QHBoxLayout(self)
        # Mêmes marges UTILES que la ligne : l'en-tête n'ayant pas de cadre, il
        # compense à la main les DEUX bordures que Qt retire à la ligne.
        th.setContentsMargins(6 + LAYER_ROW_BORDER, 0, 6 + LAYER_ROW_BORDER_R, 0)
        th.setSpacing(LAYER_COL_SPACING)

        for cle, titre, largeur, tip in LAYER_COLS:
            b = QPushButton(titre)
            b.setFixedSize(largeur, self._TITRE_H)
            b.setFlat(True)
            self._titres[cle] = b
            if titre:
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(
                    (tip + "\n\n" if tip else "")
                    + "Clic sur ce titre : sélectionne la colonne.\n"
                      "Un réglage dans une case s'applique alors à TOUTES les "
                      "lignes. Re-cliquer libère la colonne.")
                b.clicked.connect(lambda _=False, k=cle: self.column_clicked.emit(k))
            else:
                # Colonne ✕ : sélectionner « supprimer » n'aurait aucun sens,
                # et un clic de trop viderait le tableau.
                b.setEnabled(False)
            th.addWidget(b)

        self.set_selected_column(None)

    # ── Sélection ─────────────────────────────────────────────────────────────
    def selected_column(self):
        return self._sel

    def set_selected_column(self, cle):
        self._sel = cle
        for k, b in self._titres.items():
            if k == cle:
                b.setStyleSheet(
                    "QPushButton{color:#04141b;background:#00d4ff;"
                    "border:none;border-radius:3px;"
                    "font-size:9px;font-weight:bold;letter-spacing:1px;}")
            else:
                b.setStyleSheet(
                    "QPushButton{color:#4a4a4a;background:transparent;"
                    "border:none;font-size:9px;font-weight:bold;"
                    "letter-spacing:1px;}"
                    "QPushButton:hover{color:#00d4ff;}"
                    "QPushButton:disabled{color:#4a4a4a;}")

    # ── Largeurs élastiques ───────────────────────────────────────────────────
    def set_col_widths(self, largeurs, total):
        """Réaccorde l'en-tête sur les largeurs calculées pour le tableau."""
        self.setFixedWidth(total)
        for cle, b in self._titres.items():
            b.setFixedWidth(largeurs[cle])


class LayerRow(QFrame):
    """Une couche d'effet sur une seule ligne de tableau.

    Remplace l'ancienne carte à curseurs : mêmes réglages, mais tous visibles
    d'un coup et alignés d'une couche à l'autre, ce qui permet de comparer deux
    couches sans les lire l'une après l'autre.
    """

    deleted          = Signal(object)
    changed          = Signal()
    # (ligne, clé de colonne) — émis en plus de `changed` pour que le panneau
    # sache QUELLE colonne vient d'être touchée, et puisse la recopier partout
    # si elle est sélectionnée.
    cell_changed     = Signal(object, str)

    _ATTRS  = ["Dimmer", "R", "V", "B", "W", "Ambre", "UV", "RGB", "Permut",
               "Pan", "Tilt", "Pan/Tilt", "Zoom", "Gobo", "Strobe"]
    _FORMES = list(FORMES)

    _ATTR_COLORS = WaveformCanvas._ATTR_COLORS

    # (clé de colonne, attribut de la couche, maximum, minimum, décimales)
    # GROUPER part de 1 : un paquet de 0 fixture ne veut rien dire, et la
    # cellule doit refuser de descendre en dessous plutôt que de laisser passer
    # une valeur que les moteurs devraient rattraper.
    #
    # VITESSE au dixième : la fréquence est LINÉAIRE (`core.layer_frequency`,
    # 0,05 + vit/100 × 7 Hz), donc toute la résolution est du côté rapide. Un
    # cran entier vaut 37 % de période à VIT 1 (8,3 s → 5,3 s) et 1 % à VIT 100
    # (1,4 ms) : la finesse manquait exactement là où on règle les mouvements
    # lents. Le dixième est aussi ce qui permet de tomber sur un tempo — 128 BPM
    # = VIT 29,8, entre deux crans entiers (29 = 125 BPM, 30 = 129 BPM).
    #
    # Rien à migrer : `layer_frequency` travaille déjà en flottant et `to_dict`
    # écrit `speed` tel quel. Les shows et les préréglages en place gardent
    # leurs valeurs entières, donc exactement leur figure.
    _NUM_FIELDS = [
        ("vit",    "speed",   100, 0, 1),
        ("amp",    "size",    100, 0, 0),
        ("min",    "min_val", 100, 0, 0),
        ("max",    "max_val", 100, 0, 0),
        ("dec",    "spread",  360, 0, 0),
        ("group",  "block",    64, 1, 0),
        ("fondu",  "fade",    100, 0, 0),
        ("depart", "phase",   100, 0, 0),
    ]

    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self.layer   = layer
        self._sel_col = None     # colonne sélectionnée dans l'en-tête
        self._cells  = {}
        self._w      = {c[0]: c[2] for c in LAYER_COLS}
        self._tip    = {c[0]: c[3] for c in LAYER_COLS}
        self._build()

    # ── Construction ──────────────────────────────────────────────────────────
    def _accent(self):
        return self._ATTR_COLORS.get(self.layer.attribute, "#3a3a3a")

    def _apply_frame_style(self):
        self.setStyleSheet(f"""
            QFrame#LRow {{
                background: #111111;
                border: {LAYER_ROW_BORDER_R}px solid #1c1c1c;
                border-left: {LAYER_ROW_BORDER}px solid {self._accent()};
                border-radius: 5px;
            }}
            QFrame#LRow:hover {{ border-color: #262626;
                                 border-left-color: {self._accent()}; }}
        """)

    def _emit(self, cle):
        """Signale un réglage, en disant de quelle colonne il vient."""
        self.cell_changed.emit(self, cle)
        self.changed.emit()

    # ── Colonne sélectionnée ──────────────────────────────────────────────────
    def set_selected_column(self, cle):
        """Surligne la cellule de la colonne sélectionnée, façon tableur.

        Le cadre est posé en superposition plutôt qu'appliqué au style de
        chaque cellule : les cellules ont des styles très différents (liste,
        bouton, cellule peinte à la main) et il n'existe pas de bordure qui
        conviendrait aux trois sans les redessiner une par une.
        """
        self._sel_col = cle
        self._place_marqueur()

    def _place_marqueur(self):
        cible = self._boites.get(self._sel_col) if self._sel_col else None
        if cible is None:
            self._marqueur.hide()
            return
        g = cible.geometry()
        self._marqueur.setGeometry(g.adjusted(-3, -3, 3, 3))
        self._marqueur.show()
        self._marqueur.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_marqueur()

    def _build(self):
        self.setObjectName("LRow")
        self.setFixedHeight(LAYER_ROW_H)
        self.setFixedWidth(LAYER_TABLE_W)
        self._apply_frame_style()
        self._boites = {}

        h = QHBoxLayout(self)
        h.setContentsMargins(6, 0, 6, 0)
        h.setSpacing(LAYER_COL_SPACING)

        self._boites["cible"] = self._mk_cible()
        self._boites["canal"] = self._mk_canal()
        self._boites["forme"] = self._mk_forme()
        for cle in ("cible", "canal", "forme"):
            h.addWidget(self._boites[cle])
        for key, attr, maximum, mini, dec in self._NUM_FIELDS:
            self._boites[key] = self._mk_num(key, attr, maximum, mini, dec)
            h.addWidget(self._boites[key])
        self._boites["sens"]   = self._mk_sens()
        self._boites["coul"]   = self._mk_coul()
        self._boites["pos"]    = self._mk_pos()
        self._boites["sym"]    = self._mk_sym()
        self._boites["del"]    = self._mk_del()
        for cle in ("sens", "coul", "pos", "sym", "del"):
            h.addWidget(self._boites[cle])

        # Cadre de colonne sélectionnée : transparent aux clics, sinon il
        # avalerait les gestes destinés à la cellule qu'il désigne.
        self._marqueur = QFrame(self)
        self._marqueur.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._marqueur.setStyleSheet(
            "background: rgba(0,212,255,26); border: 1px solid #00d4ff;"
            "border-radius: 5px;")
        self._marqueur.hide()

        self._refresh_color_btns()
        self._refresh_pos_btn()
        self._refresh_sym()
        self._sync_enabled_state()

    # ── Largeurs élastiques ───────────────────────────────────────────────────
    def set_col_widths(self, largeurs, total):
        """Réaccorde la ligne sur les largeurs calculées pour le tableau.

        Même calcul que l'en-tête, donc même alignement. Les cellules qui
        contiennent un aperçu (courbe, trajectoire) rendent le surplus à leur
        liste déroulante : c'est le texte qui manque de place, pas le dessin.
        À l'inverse, quand la place manque, c'est l'aperçu de courbe qui cède
        en premier — une courbe étroite reste lisible, un nom de forme tronqué
        à trois lettres ne l'est plus.
        """
        self.setFixedWidth(total)
        for cle, boite in self._boites.items():
            if isinstance(boite, _NumCell):
                boite.set_width(largeurs[cle])
            elif cle == "del":
                boite.setFixedSize(largeurs[cle], LAYER_BTN)
            else:
                boite.setFixedWidth(largeurs[cle])

        reste_forme = largeurs["forme"] - 4
        self._wave.set_width(min(LAYER_WAVE_MAX_W, max(LAYER_WAVE_MIN_W,
                                                       reste_forme - 74)))
        self._forme_cb.setFixedWidth(max(56, reste_forme - self._wave.width()))
        self._shape_cb.setFixedWidth(max(56, reste_forme - self._traj.width()))
        self._place_marqueur()

    # ── Menu contextuel ───────────────────────────────────────────────────────
    def contextMenuEvent(self, e):
        """Clic droit n'importe où sur la ligne : supprimer la couche.

        Filet de sécurité pour les écrans étroits. Le ✕ est en bout de ligne :
        si la fenêtre est trop petite même pour le tableau resserré, il part
        hors champ et il faut faire défiler pour l'atteindre. Le clic droit,
        lui, tombe toujours sur la ligne.
        """
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        act = menu.addAction(tr("fx_del_layer"))
        if menu.exec(e.globalPos()) is act:
            self.deleted.emit(self)

    # ── Cellules ──────────────────────────────────────────────────────────────
    def _mk_cible(self):
        b = QPushButton(cible_text(self.layer))
        b.setFixedSize(self._w["cible"], LAYER_CELL_H)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(self._tip["cible"])
        b.setStyleSheet(
            "QPushButton{background:#0f0f0f;color:#00d4ff;border:1px solid #1e1e1e;"
            "border-radius:4px;font-size:10px;font-weight:bold;}"
            "QPushButton:hover{border-color:#00d4ff;}")
        b.clicked.connect(self._open_cible_popup)
        self._cible_btn = b
        return b

    def _open_cible_popup(self):
        pop = _CiblePopup([self.layer], self, sel_source=self._plan_selection_source())
        pop.changed.connect(self._on_cible_changed)
        pop.adjustSize()
        pop.move(self._cible_btn.mapToGlobal(QPoint(0, self._cible_btn.height() + 2)))
        pop.show()

    def _plan_selection_source(self):
        """Callable () -> sélection courante du plan de feu de l'éditeur, ou None.

        Remonte la chaîne des parents jusqu'au dialogue qui porte `_plan_widget`.
        """
        w = self.parent()
        while w is not None:
            plan = getattr(w, '_plan_widget', None)
            if plan is not None and hasattr(plan, 'selected_lamps'):
                # ORDRE de sélection, pas un ensemble. C'est lui qui donne son
                # sens à un chenillard : « Sélection » doit déclencher les
                # projecteurs dans l'ordre où on les a cliqués — c'est aussi
                # l'ordre des pastilles numérotées affichées sur le plan. Un set
                # le perdait, et l'effet repartait dans l'ordre du patch.
                def _ordonnee(pl=plan):
                    fn = getattr(pl, 'selection_ordered', None)
                    if callable(fn):
                        return fn()
                    ordre = list(getattr(pl, 'selected_lamps_ordered', []))
                    vus = set(ordre)
                    return ([k for k in ordre if k in pl.selected_lamps]
                            + [k for k in pl.selected_lamps if k not in vus])
                return _ordonnee
            w = w.parent()
        return None

    def _on_cible_changed(self):
        self._cible_btn.setText(cible_text(self.layer))
        self._emit("cible")

    def _mk_canal(self):
        cb = ComboSansMolette()
        cb.addItems(self._ATTRS)
        cb.setCurrentText(self.layer.attribute)
        cb.setFixedSize(self._w["canal"], LAYER_CELL_H)
        cb.setStyleSheet(_COMBO_STYLE_COMPACT)
        cb.setToolTip(self._tip["canal"])
        cb.currentTextChanged.connect(self._on_attr)
        self._attr_cb = cb
        return cb

    def _mk_forme(self):
        box = QWidget()
        box.setFixedWidth(self._w["forme"])
        box.setStyleSheet("background: transparent;")
        bh = QHBoxLayout(box)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(4)

        self._wave = WaveformCanvas(self.layer, w=88, h=LAYER_CELL_H - 4)
        bh.addWidget(self._wave)

        self._forme_cb = ComboSansMolette()
        self._forme_cb.addItems(self._FORMES)
        self._forme_cb.setCurrentText(
            self.layer.forme if self.layer.forme in self._FORMES else "Sinus")
        self._forme_cb.setFixedSize(74, LAYER_CELL_H)
        self._forme_cb.setStyleSheet(_COMBO_STYLE_COMPACT)
        self._forme_cb.currentTextChanged.connect(self._on_forme)
        bh.addWidget(self._forme_cb)

        # Variante Pan/Tilt : la « forme » devient une trajectoire de lyre.
        self._traj = TrajectoryCanvas(self.layer, size=LAYER_CELL_H - 4)
        bh.addWidget(self._traj)

        self._shape_cb = ComboSansMolette()
        for sid in _PT_SHAPE_ORDER:
            self._shape_cb.addItem(PAN_TILT_SHAPES[sid]["label"], sid)
        cur = getattr(self.layer, 'mouvement_shape', 'libre')
        self._shape_cb.setCurrentIndex(
            _PT_SHAPE_ORDER.index(cur) if cur in _PT_SHAPE_ORDER
            else 0)   # forme retirée (ex. « libre ») → afficher « cercle »
        self._shape_cb.setFixedSize(96, LAYER_CELL_H)
        self._shape_cb.setStyleSheet(_COMBO_STYLE_COMPACT)
        self._shape_cb.currentIndexChanged.connect(self._on_shape_changed)
        bh.addWidget(self._shape_cb)

        box.setToolTip(self._tip["forme"])
        self._forme_box = box
        self._sync_forme_mode()
        return box

    def _sync_forme_mode(self):
        is_pt = (self.layer.attribute == "Pan/Tilt")
        self._wave.setVisible(not is_pt)
        self._forme_cb.setVisible(not is_pt)
        self._traj.setVisible(is_pt)
        self._shape_cb.setVisible(is_pt)

    # Formes constantes : elles rendent la même valeur à chaque instant du cycle.
    _FORMES_CONSTANTES = ("Fixe", "Off")

    def _sync_enabled_state(self):
        """Grise les réglages qui ne produisent plus rien sur cette couche.

        Une forme constante ne parcourt aucun cycle : la vitesse, le décalage,
        le départ, le sens et la répartition ne changent alors strictement rien
        à la sortie. Sauf si le FONDU est ouvert — il mélange la forme vers un
        sinus, et ce sinus dépend à nouveau du temps : tout se rallume. Le fondu
        reste donc toujours réglable, c'est la porte de sortie.

        « Un par un » est l'autre cas : il tire sa position du RANG de la
        fixture, pas d'une courbe parcourue. Le DÉCALAGE (qui déphase une
        courbe) et le FONDU (qui la mélange vers un sinus) n'ont alors plus
        de prise — et le fondu rallumerait les voisins, ce qui détruirait
        justement l'exclusivité recherchée.

        Les couches Pan/Tilt sont hors sujet : leur mouvement vient de la
        trajectoire, pas de `forme`.
        """
        gele = (self.layer.attribute != "Pan/Tilt"
                and self.layer.forme in self._FORMES_CONSTANTES
                and not getattr(self.layer, 'fade', 0))
        un_par_un = (self.layer.attribute != "Pan/Tilt"
                     and self.layer.forme == "Un par un")

        # Sortie = (MIN + forme×(MAX−MIN)) × AMP. Sur une forme constante :
        #  · « Fixe » (forme=1) → sortie = MAX×AMP : MIN s'annule → inerte.
        #  · « Off »  (forme=0) → sortie = MIN×AMP : MAX s'annule → inerte.
        # AMP et le niveau restant (MAX sur Fixe / MIN sur Off) restent utiles.
        dead_level = None
        if gele:
            dead_level = "min" if self.layer.forme == "Fixe" else "max"

        for key in ("vit", "depart"):
            self._cells[key].setEnabled(not gele)
        self._cells["dec"].setEnabled(not gele and not un_par_un)
        self._cells["fondu"].setEnabled(not un_par_un)
        self._sens_box.setEnabled(not gele)
        self._cells["min"].setEnabled(dead_level != "min")
        self._cells["max"].setEnabled(dead_level != "max")

        # GROUPER ne fait que regrouper le DÉCALAGE : sans décalage, tout part
        # déjà ensemble et la valeur ne change rien pour l'instant. Le tooltip
        # le dit, mais la cellule reste RÉGLABLE : la griser créait un
        # œuf-et-poule (« je ne peux pas grouper mes lyres ») où il fallait
        # deviner qu'on doit ouvrir DÉC d'abord pour pouvoir grouper ensuite —
        # or grouper est le geste que l'utilisateur a en tête, le décalage n'en
        # est que le corollaire.
        # « Un par un » est le cas où GROUPER agit même à DÉC 0 : il ignore le
        # décalage mais respecte les paquets (un paquet allumé à la fois).
        _sans_dec = not gele and not un_par_un and not getattr(self.layer, 'spread', 0)
        self._cells["group"].setEnabled(not gele)

        tip = ("Sans effet sur une forme constante : ouvrez le FONDU pour "
               "réanimer la couche.")
        tip_upu = ("Sans objet sur « Un par un » : la position vient du rang "
                   "de la fixture, pas d'une courbe déphasée.")
        for w, key in ((self._cells["vit"],    "vit"),
                       (self._cells["depart"], "depart"),
                       (self._sens_box,        "sens")):
            w.setToolTip(tip if gele else self._tip[key])
        self._cells["dec"].setToolTip(
            tip if gele else tip_upu if un_par_un else self._tip["dec"])
        self._cells["fondu"].setToolTip(
            ("Sans objet sur « Un par un » : adoucir la forme rallumerait les "
             "voisins et il n'y aurait plus un seul projecteur allumé.")
            if un_par_un else self._tip["fondu"])
        self._cells["group"].setToolTip(
            tip if gele else
            "Paquets réglables, mais sans effet tant que DÉC vaut 0 : les "
            "fixtures partent déjà toutes ensemble. Ouvrez DÉC pour que les "
            "paquets se décalent." if _sans_dec else self._tip["group"])
        self._cells["min"].setToolTip(tip if dead_level == "min" else self._tip["min"])
        self._cells["max"].setToolTip(tip if dead_level == "max" else self._tip["max"])

    def _mk_num(self, key, attr, maximum, minimum=0, decimals=0):
        cell = _NumCell(getattr(self.layer, attr, minimum), maximum,
                        width=self._w[key], accent=self._accent(),
                        minimum=minimum, decimals=decimals)
        cell.setToolTip(self._tip[key])
        cell.valueChanged.connect(
            lambda v, a=attr, k=key: (setattr(self.layer, a, v),
                                      self._sync_enabled_state(),
                                      self._emit(k)))
        self._cells[key] = cell
        return cell

    def _mk_sens(self):
        box = QWidget()
        box.setFixedWidth(self._w["sens"])
        box.setStyleSheet("background: transparent;")
        bh = QHBoxLayout(box)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(3)

        self._sens_btns = {}
        cur = getattr(self.layer, 'direction', 1)
        for val, sym in [(1, "→"), (-1, "←"), (0, "↔")]:
            b = QPushButton(sym)
            b.setFixedSize(LAYER_BTN, LAYER_BTN)
            b.setCheckable(True)
            b.setChecked(val == cur)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(_SENS_TIPS[val])
            b.clicked.connect(lambda _=False, v=val: self._on_sens(v))
            self._sens_btns[val] = b
            bh.addWidget(b)
        self._sens_box = box
        self._refresh_sens()
        return box

    def refresh(self):
        """Recharge tous les widgets depuis la couche, sans reconstruire la ligne.

        Sert à l'édition par colonne : un geste sur l'en-tête écrit dans toutes
        les couches, chaque ligne se remet ensuite en accord. Reconstruire les
        lignes à chaque cran de glisser détruirait le widget en cours d'usage.
        """
        blocs = (self._attr_cb, self._forme_cb, self._shape_cb)
        for w in blocs:
            w.blockSignals(True)

        self._cible_btn.setText(cible_text(self.layer))
        self._attr_cb.setCurrentText(self.layer.attribute)

        forme = self.layer.forme if self.layer.forme in self._FORMES else "Sinus"
        self._forme_cb.setCurrentText(forme)

        shape = getattr(self.layer, 'mouvement_shape', 'libre')
        self._shape_cb.setCurrentIndex(
            _PT_SHAPE_ORDER.index(shape) if shape in _PT_SHAPE_ORDER
            else 0)   # forme retirée (ex. « libre ») → afficher « cercle »

        for w in blocs:
            w.blockSignals(False)

        for key, attr, _max, _min, _dec in self._NUM_FIELDS:
            cell = self._cells[key]
            cell.blockSignals(True)
            cell.set_mixed(False)
            cell.set_value(getattr(self.layer, attr, _min), emit=False)
            cell.blockSignals(False)

        self._apply_frame_style()
        accent = self._accent()
        for cell in self._cells.values():
            cell.set_accent(accent)
        self._wave.set_layer(self.layer)
        self._refresh_sens()
        self._refresh_color_btns()
        self._refresh_pos_btn()
        self._refresh_sym()
        self._sync_forme_mode()
        self._sync_enabled_state()

    def _mk_coul(self):
        box = QWidget()
        box.setFixedWidth(self._w["coul"])
        box.setStyleSheet("background: transparent;")
        bh = QHBoxLayout(box)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(4)

        self._col1_btn = QPushButton()
        self._col1_btn.setFixedSize(LAYER_BTN, LAYER_BTN)
        self._col1_btn.setCursor(Qt.PointingHandCursor)
        self._col1_btn.clicked.connect(lambda: self._pick_color(1))
        bh.addWidget(self._col1_btn)

        self._col2_btn = QPushButton()
        self._col2_btn.setFixedSize(LAYER_BTN, LAYER_BTN)
        self._col2_btn.setCursor(Qt.PointingHandCursor)
        self._col2_btn.clicked.connect(lambda: self._pick_color(2))
        bh.addWidget(self._col2_btn)

        bh.addStretch()
        return box

    def _mk_del(self):
        b = QPushButton("×")
        b.setFixedSize(self._w["del"], LAYER_BTN)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tr("ee2_del_layer"))
        b.setStyleSheet(
            "QPushButton{background:#0d0606;color:#2e1010;border:1px solid #180c0c;"
            "border-radius:4px;font-size:11px;font-weight:bold;}"
            "QPushButton:hover{color:#ff5555;border-color:#551111;background:#1a0808;}")
        b.clicked.connect(lambda: self.deleted.emit(self))
        return b

    # ── Réactions ─────────────────────────────────────────────────────────────
    def set_time(self, t: float):
        self._wave.set_time(t)
        self._traj.set_time(t)

    def _on_attr(self, v):
        self.layer.attribute = v
        self._apply_frame_style()
        accent = self._accent()
        for cell in self._cells.values():
            cell.set_accent(accent)
        self._refresh_color_btns()
        self._refresh_pos_btn()
        self._refresh_sym()
        self._sync_forme_mode()
        self._sync_enabled_state()
        is_pt = (v == "Pan/Tilt")
        if is_pt:
            self._on_shape_changed(self._shape_cb.currentIndex())
        self._emit("canal")

    def _on_forme(self, v):
        self.layer.forme = v
        self._sync_enabled_state()
        self._emit("forme")

    def _on_shape_changed(self, _idx):
        self.layer.mouvement_shape = self._shape_cb.currentData() or "libre"
        self._traj.update()
        self._emit("forme")

    def _on_sens(self, val):
        self.layer.direction = val
        self._refresh_sens()
        self._emit("sens")
    def _refresh_sens(self):
        _dis = "QPushButton:disabled{background:#080808;color:#232323;border-color:#141414;}"
        on  = ("QPushButton{background:#001a2a;color:#00d4ff;border:1px solid #004466;"
               "border-radius:3px;font-size:10px;font-weight:bold;}"
               "QPushButton:hover{border-color:#444;}" + _dis)
        off = ("QPushButton{background:#0c0c0c;color:#444;border:1px solid #1c1c1c;"
               "border-radius:3px;font-size:10px;font-weight:bold;}"
               "QPushButton:hover{border-color:#444;}" + _dis)
        for v, b in self._sens_btns.items():
            b.blockSignals(True)
            b.setChecked(v == self.layer.direction)
            b.setStyleSheet(on if v == self.layer.direction else off)
            b.blockSignals(False)

    def _pick_color(self, which):
        from PySide6.QtWidgets import QColorDialog
        attr    = 'color1' if which == 1 else 'color2'
        default = '#ff0000' if which == 1 else '#0000ff'
        c = QColorDialog.getColor(
            QColor(getattr(self.layer, attr, default)), self,
            f"Couleur {which}", QColorDialog.DontUseNativeDialog)
        if c.isValid():
            setattr(self.layer, attr, c.name())
            self._refresh_color_btns()
            self._emit("coul")

    # ── Position de départ (canaux de mouvement) ──────────────────────────────
    _ATTRS_MOUVEMENT = ("Pan", "Tilt", "Pan/Tilt")

    def _mk_pos(self):
        b = QPushButton("—")
        b.setFixedSize(self._w["pos"], LAYER_CELL_H)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(self._tip["pos"])
        b.setStyleSheet(
            "QPushButton{background:#0f0f0f;color:#ff9900;border:1px solid #1e1e1e;"
            "border-radius:4px;font-size:10px;font-weight:bold;}"
            "QPushButton:hover{border-color:#ff9900;}")
        b.clicked.connect(self._open_pos_menu)
        # La cellule POSITION est masquee hors canaux de mouvement, mais elle
        # doit GARDER SA PLACE : un widget cache sort du layout, et QHBoxLayout
        # redistribue alors ses 78 px dans les ecarts entre toutes les autres
        # cellules. Chaque colonne glissait vers la droite un peu plus que la
        # precedente (+5, +10, +15... +65 px mesures), et tout ce qui suit POS
        # partait au contraire vers la gauche : les libelles de l'en-tete ne
        # tombaient plus en face de leurs cellules.
        _sp = b.sizePolicy()
        _sp.setRetainSizeWhenHidden(True)
        b.setSizePolicy(_sp)
        self._pos_btn = b
        return b

    # ── Symétrie Pan (canaux Pan et Pan/Tilt) ─────────────────────────────────
    # Tilt est exclu : sym_pan n'inverse que le Pan, la case n'y produirait rien.
    _ATTRS_SYM = ("Pan", "Pan/Tilt")

    def _mk_sym(self):
        b = QPushButton("⇄")
        b.setCheckable(True)
        b.setFixedSize(self._w["sym"], LAYER_CELL_H)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(self._tip["sym"])
        b.setStyleSheet(
            "QPushButton{background:#0f0f0f;color:#555;border:1px solid #1e1e1e;"
            "border-radius:4px;font-size:14px;font-weight:bold;}"
            "QPushButton:hover{border-color:#00d4ff;}"
            "QPushButton:checked{background:#0d1f2a;color:#00d4ff;"
            "border-color:#00d4ff;}")
        b.toggled.connect(self._on_sym_toggled)
        # Même raison que POSITION : garder la place quand la cellule est
        # masquée, sinon toutes les colonnes suivantes glissent.
        _sp = b.sizePolicy()
        _sp.setRetainSizeWhenHidden(True)
        b.setSizePolicy(_sp)
        self._sym_btn = b
        return b

    def _on_sym_toggled(self, on):
        self.layer.sym_pan = bool(on)
        self._emit("sym")

    def _refresh_sym(self):
        btn = getattr(self, '_sym_btn', None)
        if btn is None:
            return
        actif = self.layer.attribute in self._ATTRS_SYM
        btn.setVisible(actif)
        if not actif:
            return
        btn.blockSignals(True)
        btn.setChecked(bool(getattr(self.layer, 'sym_pan', False)))
        btn.blockSignals(False)

    def _find_main_window(self):
        """Fenêtre principale, par remontée de parents.

        Même remontée que le plan de feu : la ligne ne connaît pas la fenêtre
        principale, seul le dialogue d'édition la porte.
        """
        w = self.parent()
        while w is not None:
            mw = getattr(w, '_main_window', None)
            if mw is not None:
                return mw
            w = w.parent()
        return None

    def _position_presets(self):
        """Positions AKAI enregistrées de l'application, ou [] si introuvables."""
        mw = self._find_main_window()
        return list(getattr(mw, 'position_presets', []) or []) if mw else []

    def _pdf_position_presets(self, mw, deja_pris):
        """Positions du PLAN DE FEU absentes de la liste AKAI, par nom.

        Les positions vivent dans DEUX fichiers : celles créées depuis le plan
        de feu 2D (`~/.mystrow_moving_presets.json`) et les positions AKAI
        (`~/.maestro_akai_config.json`). Ce menu ne listait que les secondes —
        une position tout juste créée sur le plan de feu était donc
        introuvable ici, alors qu'elle existait bel et bien.

        Le rapprochement se fait par NOM, comme dans la bibliothèque de REC
        Lumière : deux positions homonymes sont considérées identiques et c'est
        la copie AKAI qui est affichée (pas de doublon dans le menu).
        """
        if mw is None or not hasattr(mw, '_load_pdf_presets'):
            return []
        try:
            return [p for p in (mw._load_pdf_presets() or [])
                    if p.get("name") and p.get("name") not in deja_pris]
        except Exception as e:
            print(f"[FX] lecture des positions Plan de Feu impossible : {e}")
            return []

    def _open_pos_menu(self):
        mw = self._find_main_window()
        # Une position AKAI qui a un jumeau côté plan de feu est une COPIE, qui
        # peut dater : on la remet à jour avant d'ouvrir le menu, comme le fait
        # la bibliothèque de REC Lumière. Idempotent, n'ajoute jamais rien.
        if mw is not None and hasattr(mw, 'sync_pdf_positions_into_akai'):
            try:
                mw.sync_pdf_positions_into_akai()
            except Exception:
                pass
        presets = self._position_presets()
        pdf_presets = self._pdf_position_presets(
            mw, {p.get("name") for p in presets})
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        cur = getattr(self.layer, 'pos_preset_idx', None)

        act = menu.addAction(("✓ " if cur is None else "    ") + "Centre (par défaut)")
        act.triggered.connect(lambda: self._set_pos(None, ""))

        if presets:
            menu.addSeparator()
            for i, p in enumerate(presets):
                nom = p.get("name", f"Position {i + 1}")
                a = menu.addAction(("✓ " if cur == i else "    ") + nom)
                a.triggered.connect(lambda _=False, k=i, n=nom: self._set_pos(k, n))

        if pdf_presets:
            menu.addSeparator()
            titre = menu.addAction(tr("fx_pos_from_pdf"))
            titre.setEnabled(False)
            for p in pdf_presets:
                nom = p.get("name", "")
                a = menu.addAction("    " + nom)
                a.triggered.connect(
                    lambda _=False, pdf=p: self._set_pos_from_pdf(pdf))

        if not presets and not pdf_presets:
            a = menu.addAction(tr("fx_no_position"))
            a.setEnabled(False)

        menu.exec(self._pos_btn.mapToGlobal(QPoint(0, self._pos_btn.height() + 2)))

    def _set_pos_from_pdf(self, pdf_preset):
        """Choisit une position du plan de feu : la couche vise un INDEX dans
        `position_presets`, il faut donc d'abord y fabriquer la copie.

        Conversion à la SÉLECTION et pas à l'affichage : sinon ouvrir ce menu
        recopierait toutes les positions du plan de feu dans la config AKAI.
        """
        mw = self._find_main_window()
        if mw is None or not hasattr(mw, 'pdf_position_to_akai_index'):
            return
        idx = mw.pdf_position_to_akai_index(pdf_preset)
        if idx is None:
            return
        self._set_pos(idx, pdf_preset.get("name", ""))

    def _set_pos(self, idx, nom):
        self.layer.pos_preset_idx  = idx
        self.layer.pos_preset_name = nom
        self._refresh_pos_btn()
        self._refresh_sym()
        self._emit("pos")

    def _refresh_pos_btn(self):
        """Le bouton POSITION ne concerne que les canaux de mouvement.

        Sur une couche Dimmer ou RGB il n'y a pas de trajectoire à centrer :
        on le cache, comme les pastilles de couleur hors RGB/Permut.
        """
        btn = getattr(self, '_pos_btn', None)
        if btn is None:
            return
        actif = self.layer.attribute in self._ATTRS_MOUVEMENT
        btn.setVisible(actif)
        if not actif:
            return
        idx = getattr(self.layer, 'pos_preset_idx', None)
        nom = getattr(self.layer, 'pos_preset_name', '') or ''
        if idx is None:
            btn.setText("—")
            btn.setToolTip(self._tip["pos"])
            return
        presets = self._position_presets()
        trouve = find_position_preset(presets, idx, nom)
        if trouve is None:
            # Preset supprimé : le dire plutôt que d'afficher un nom qui ne
            # correspond plus à rien — le moteur retombera sur le centre.
            btn.setText("⚠ " + (nom[:8] if nom else "?"))
            btn.setToolTip(tr("fx_f_pos_missing", nom=nom))
            return
        vrai = trouve.get("name", nom) or nom
        btn.setText(vrai[:10])
        btn.setToolTip(f"Centré sur la position « {vrai} ».\n\n" + self._tip["pos"])

    def _refresh_color_btns(self):
        attr = self.layer.attribute
        has1 = attr in ("RGB", "Permut")
        has2 = attr == "Permut"
        self._col1_btn.setVisible(has1)
        self._col2_btn.setVisible(has2)
        for btn, flag, key, default in (
                (self._col1_btn, has1, 'color1', '#ff0000'),
                (self._col2_btn, has2, 'color2', '#0000ff')):
            if flag:
                col = getattr(self.layer, key, default)
                btn.setStyleSheet(
                    f"QPushButton{{background:{col};border:1px solid #333;"
                    f"border-radius:4px;}}"
                    f"QPushButton:hover{{border-color:#666;}}")
                btn.setToolTip(tr("fx_f_color", a0=key[-1], col=col))


# ─── Panneau d'édition simplifié (colonne centrale) ───────────────────────────

class SimpleEffectPanel(QWidget):
    """
    Panneau central : le tableau des couches, une couche par ligne.

    « AJUSTER TOUT » et « ASSIGNER » sont construits ici mais reparentés sous le
    plan de feu (colonne 3) par EffectEditorDialog.
    """

    changed          = Signal()
    rename_requested = Signal(object)  # émet l'effet courant (dict)

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._layers       = []
        self._effect       = None
        self._main_window  = main_window
        self._layer_cards: list = []
        self._sel_col = None         # colonne sélectionnée dans l'en-tête
        self._group_amp: dict = {}   # {groupe: [min, max]} amplitude par groupe

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
        self._eff_title = QLabel(tr("ee2_pick_effect"))
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
        self._rename_btn.setToolTip(tr("ee2_rename_effect"))
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
        # Largeurs de colonnes : confortables tant qu'on ne connaît pas la place
        # disponible, recalculées au premier resize de `lw_inner` (qui les
        # resserrera si la fenêtre est plus étroite).
        self._table_w = LAYER_TABLE_W
        self._col_w   = layer_col_widths(LAYER_TABLE_W)

        lw_inner = _ElasticBody()
        lw_inner.setStyleSheet("background: #0d0d0d;")
        lw_inner.resized.connect(self._on_body_resized)
        self._ll = QVBoxLayout(lw_inner)
        self._ll.setContentsMargins(14, 14, 10, 12)
        self._ll.setSpacing(0)

        # En-tête COUCHES + rappel de la colonne sélectionnée.
        sep = self._mk_sep("COUCHES")
        self._scope_lbl = QLabel("")
        self._scope_lbl.setStyleSheet(
            "color:#00d4ff;font-size:9px;font-weight:bold;letter-spacing:1px;"
            "background:transparent;")
        sep.layout().insertWidget(1, self._scope_lbl)
        self._ll.addWidget(sep)
        self._ll.addSpacing(6)

        # Titres de colonnes du tableau (mêmes largeurs que les lignes)
        self._table_header = LayerTableHeader()
        self._table_header.setVisible(False)
        self._table_header.column_clicked.connect(self._on_column_clicked)
        self._ll.addWidget(self._table_header, 0, Qt.AlignLeft)
        self._ll.addSpacing(3)

        # Conteneur des LayerRow — une couche par ligne
        self._layers_container = QWidget()
        self._layers_container.setStyleSheet("background: transparent;")
        self._layers_vl = QVBoxLayout(self._layers_container)
        self._layers_vl.setContentsMargins(0, 0, 0, 0)
        self._layers_vl.setSpacing(3)
        self._layers_vl.setAlignment(Qt.AlignLeft)
        self._ll.addWidget(self._layers_container, 0, Qt.AlignLeft)

        self._ll.addSpacing(4)

        # Placeholder "Sélectionner un effet" (visible quand aucun effet sélectionné)
        self._no_effect_lbl = QLabel(tr("ee2_back_select"))
        self._no_effect_lbl.setStyleSheet(
            "color: #2a2a2a; font-size: 11px; font-style: italic; "
            "background: transparent; padding: 6px 0;"
        )
        self._ll.addWidget(self._no_effect_lbl)

        # Bouton + sous les couches
        self._add_layer_btn = QPushButton(tr("ee2_add_layer_btn"))
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
        self._add_layer_btn.setToolTip(tr("ee2_add_layer"))
        self._add_layer_btn.clicked.connect(self._on_add_layer)
        self._add_layer_btn.setVisible(False)
        self._add_layer_btn.setFixedWidth(LAYER_TABLE_W)
        self._ll.addWidget(self._add_layer_btn, 0, Qt.AlignLeft)

        self._ll.addStretch()

        lw_scroll = _ElasticScroll()
        lw_scroll.resized.connect(self._on_body_resized)
        lw_scroll.setWidget(lw_inner)
        lw_scroll.setWidgetResizable(True)
        # Le tableau a une largeur fixe : la barre horizontale n'apparaît que si
        # la fenêtre est trop étroite pour afficher toutes les colonnes.
        lw_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        lw_scroll.setStyleSheet("""
            QScrollArea { background: #0d0d0d; border: none; }
            QScrollBar:vertical { background: #0d0d0d; width: 4px; border-radius: 2px; }
            QScrollBar::handle:vertical { background: #252525; border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { background: #0d0d0d; height: 6px; border-radius: 3px; }
            QScrollBar::handle:horizontal { background: #252525; border-radius: 3px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        """)

        # AJUSTER TOUT et ASSIGNER : créés ici (widgets + connexions) puis placés
        # sous le plan de feu (colonne 3) par EffectEditorDialog. L'aperçu a été
        # retiré → la colonne 2 est désormais mono-colonne (uniquement les couches).
        self._build_assigner_section()

        bl.addWidget(lw_scroll, 1)
        outer.addWidget(body, 1)

        self._set_enabled(False)

    # ── Colonnes élastiques ───────────────────────────────────────────────────

    def _on_body_resized(self, largeur_body):
        """La colonne des couches a changé de largeur : réétaler les colonnes."""
        # 14 + 10 de marges du layout, plus 4 px de garde pour que le tableau ne
        # vienne jamais frôler la barre de défilement (elle apparaîtrait, ce qui
        # rétrécirait le corps, ce qui la ferait disparaître… en boucle).
        # Plancher = tableau entièrement resserré, pas la largeur confortable :
        # entre les deux, les colonnes se resserrent au lieu de déborder à
        # droite (le ✕ de suppression restait alors hors écran).
        dispo = max(LAYER_TABLE_MIN_W, largeur_body - 28)
        if dispo == self._table_w:
            return
        self._table_w = dispo
        self._col_w   = layer_col_widths(dispo)
        self._apply_col_widths()

    def _apply_col_widths(self):
        self._table_header.set_col_widths(self._col_w, self._table_w)
        for row in self._layer_cards:
            row.set_col_widths(self._col_w, self._table_w)
        self._add_layer_btn.setFixedWidth(self._table_w)

    # ── Construction sections ─────────────────────────────────────────────────

    def _build_assigner_section(self):
        # Section « ASSIGNER » dans un conteneur autonome (self._assign_widget) :
        # EffectEditorDialog le place sous le plan de feu (colonne 3).
        cont = QWidget()
        cont.setStyleSheet("background: transparent;")
        cv = QVBoxLayout(cont)
        cv.setContentsMargins(14, 4, 14, 10)
        cv.setSpacing(0)

        cv.addWidget(self._mk_sep("ASSIGNER"))
        cv.addSpacing(6)

        self._assign_btns = {}
        assign_row = QHBoxLayout()
        assign_row.setSpacing(3)
        # 8 boutons, pas 9 : la colonne d'effets de la fenêtre principale en
        # compte 8. Un « E9 » stockait sa config sur un index qu'aucun bouton
        # ne relit — assignation sans effet visible.
        for i in range(8):
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
        cv.addLayout(assign_row)
        cv.addSpacing(10)

        # Boutons lecture conservés comme objets orphelins (référencés par EffectEditorDialog)
        self._btn_loop = QPushButton()
        self._btn_loop.setCheckable(True)
        self._btn_loop.setChecked(True)
        self._btn_once = QPushButton()
        self._btn_once.setCheckable(True)

        self._assign_widget = cont

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

    def _set_enabled(self, enabled: bool):
        self._no_effect_lbl.setVisible(not enabled)
        self._add_layer_btn.setVisible(enabled)

    # ── Interface publique ────────────────────────────────────────────────────

    def set_effect(self, eff: dict, layers: list):
        self._effect    = eff
        self._layers    = layers

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
        self._rebuild_layer_widgets()

    # ── Rafraîchissement ──────────────────────────────────────────────────────

    def _refresh(self):
        if not self._layers:
            return
        # Amplitude min/max par groupe : plus réglable dans l'éditeur, mais on
        # continue de relire ce que portent les couches pour ne pas l'effacer des
        # effets déjà enregistrés (le moteur l'applique toujours).
        _ga = next((getattr(x, 'group_amp', None) for x in self._layers
                    if getattr(x, 'group_amp', None)), {})
        self._group_amp = {k: list(v) for k, v in (_ga or {}).items()}

    # ── Gestion des couches ────────────────────────────────────────────────────

    def _rebuild_layer_widgets(self):
        self._layer_cards = []
        self._pt_pad_widget = None
        while self._layers_vl.count():
            item = self._layers_vl.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for layer in self._layers:
            row = LayerRow(layer)
            row.deleted.connect(lambda _w, l=layer: self._on_delete_layer(l))
            row.changed.connect(self.changed)
            row.cell_changed.connect(self._on_cell_changed)
            # Une ligne naît aux largeurs minimales : il faut la mettre tout de
            # suite à l'échelle courante, sinon elle reste étroite jusqu'au
            # prochain redimensionnement de la fenêtre.
            row.set_col_widths(self._col_w, self._table_w)
            row.set_selected_column(self._sel_col)
            self._layers_vl.addWidget(row)
            self._layer_cards.append(row)

        # L'en-tête ne sert à rien sans ligne dessous.
        if hasattr(self, '_table_header'):
            self._table_header.setVisible(bool(self._layers))

    # ── Colonne sélectionnée ──────────────────────────────────────────────────

    def _on_column_clicked(self, cle):
        """Clic sur un titre : on sélectionne la colonne, ou on la relâche."""
        self._sel_col = None if cle == self._sel_col else cle
        self._table_header.set_selected_column(self._sel_col)
        for row in self._layer_cards:
            row.set_selected_column(self._sel_col)

        titre = next((c[1] for c in LAYER_COLS if c[0] == self._sel_col), "")
        self._scope_lbl.setText(
            f"— COLONNE {titre} SÉLECTIONNÉE : UN RÉGLAGE S'APPLIQUE À TOUTES "
            f"LES LIGNES" if self._sel_col else "")

    def _on_cell_changed(self, row, cle):
        """Un réglage vient d'être fait dans une ligne.

        Si sa colonne est sélectionnée, on recopie la nouvelle valeur dans
        toutes les autres couches — c'est tout ce que « sélectionner une
        colonne » veut dire. Hors sélection, on ne touche à rien : la cellule
        n'a modifié que sa propre couche, comme n'importe quel tableau.
        """
        if cle != self._sel_col:
            return

        for attr in LAYER_COL_ATTRS.get(cle, ()):
            if not hasattr(row.layer, attr):
                continue
            valeur = getattr(row.layer, attr)
            for couche in self._layers:
                if couche is row.layer:
                    continue
                # Copie : `target_groups` est une liste, la partager ferait
                # bouger toutes les couches ensemble au prochain changement.
                setattr(couche, attr, copy.copy(valeur))

        # La ligne d'origine n'est pas rafraîchie : son widget est peut-être
        # sous le curseur en plein glisser, et le reconstruire couperait le geste.
        for autre in self._layer_cards:
            if autre is not row:
                autre.refresh()
        self.changed.emit()

    def _on_add_layer(self):
        new_layer           = EffectLayer()
        new_layer.attribute = "Dimmer"
        new_layer.forme     = "Sinus"
        # Sans potard global, la couche neuve s'aligne sur les couches en place
        # (plutôt qu'une valeur arbitraire qui casserait la synchro de l'effet).
        new_layer.speed     = self._layers[0].speed if self._layers else 50
        new_layer.group_amp = {k: list(v) for k, v in self._group_amp.items()}
        self._layers.append(new_layer)
        self._rebuild_layer_widgets()
        self.changed.emit()

    def _on_delete_layer(self, layer: EffectLayer):
        if layer in self._layers:
            self._layers.remove(layer)
        self._rebuild_layer_widgets()
        self.changed.emit()

    # ── Tick d'animation ──────────────────────────────────────────────────────

    def tick(self, t: float):
        """Mettre à jour toutes les waveforms des LayerRow + pad XY Pan/Tilt."""
        for card in self._layer_cards:
            card.set_time(t)
        if getattr(self, '_pt_pad_widget', None) is not None:
            self._pt_pad_widget.set_time(t)

    def set_preview_levels(self, levels: list, colors: list):
        if hasattr(self, '_preview_strip'):
            self._preview_strip.set_levels(levels, colors)

    # ── Événements ────────────────────────────────────────────────────────────


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
    cancel = QPushButton(tr("fx_cancel"))
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


def _ask_add_effect_mode(parent, has_layers: bool) -> str:
    """Demande comment ajouter un effet : "import", "create", ou "" si annulé.

    L'import existait deja, mais son seul acces etait un bouton de 16 px colle
    a l'en-tete "Mes Effets" : personne ne le trouvait. Il est desormais offert
    a egalite avec la creation, des le bouton "Ajouter un effet".
    """
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                   QLabel, QPushButton)
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("ee2_add_title"))
    dlg.setModal(True)
    dlg.setMinimumWidth(470)
    dlg.setStyleSheet("""
        QDialog { background: #1a1a1a; }
        QLabel  { color: #cccccc; font-size: 13px; background: transparent; }
        QLabel#opt_t { color: #ffffff; font-size: 13px; font-weight: bold; }
        QLabel#opt_d { color: #888888; font-size: 11px; }
        QPushButton#opt {
            background: #222222; border: 1px solid #383838;
            border-radius: 6px; text-align: left;
        }
        QPushButton#opt:hover { background: #1e2e33; border-color: #00d4ff; }
        QPushButton#cancel {
            background: #2a2a2a; color: #cccccc;
            border: 1px solid #444; border-radius: 4px;
            padding: 6px 18px; font-size: 12px; min-width: 70px;
        }
        QPushButton#cancel:hover { background: #333; color: #fff; }
    """)

    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(20, 18, 20, 16)
    lay.setSpacing(10)
    lay.addWidget(QLabel(tr("ee2_add_q")))

    choice = [""]

    def _mk_option(icon, title, desc, value):
        btn = QPushButton()
        btn.setObjectName("opt")
        btn.setCursor(Qt.PointingHandCursor)
        # QPushButton dimensionne sur son propre texte, pas sur le layout qu'on
        # lui pose dedans : sans cette reserve, la description sur deux lignes
        # (allemand, ou « enregistre les couches... » en francais) est rognee.
        btn.setMinimumHeight(84)
        row = QHBoxLayout(btn)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)
        ic = QLabel(icon)
        ic.setStyleSheet("font-size: 22px; background: transparent;")
        row.addWidget(ic)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        lt = QLabel(title); lt.setObjectName("opt_t")
        ld = QLabel(desc);  ld.setObjectName("opt_d")
        ld.setWordWrap(True)
        col.addWidget(lt)
        col.addWidget(ld)
        row.addLayout(col, 1)
        # Sans ce drapeau, les QLabel avalent le clic et le bouton ne part pas.
        for w in (ic, lt, ld):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        btn.clicked.connect(
            lambda: (choice.__setitem__(0, value), dlg.accept()))
        return btn

    lay.addWidget(_mk_option(
        "✏️", tr("ee2_add_create_t"),
        tr("ee2_add_create_d_cur") if has_layers else tr("ee2_add_create_d_new"),
        "create"))
    lay.addWidget(_mk_option(
        "📂", tr("ee2_add_import_t"), tr("ee2_add_import_d"), "import"))

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    cancel = QPushButton(tr("fx_cancel"))
    cancel.setObjectName("cancel")
    cancel.clicked.connect(dlg.reject)
    btn_row.addWidget(cancel)
    lay.addLayout(btn_row)

    dlg.exec()
    return choice[0]


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
        # Horloge de PHASE de l'aperçu : temps déformé par la vitesse, pour que
        # bouger le fader FX (ou la VITESSE d'une couche) change la cadence sans
        # faire sauter la position dans le cycle. Miroir de
        # `MainWindow._effect_clock` — parité aperçu/show.
        self._preview_clock    = 0.0
        self._preview_clock_ts = None
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

        self.setWindowTitle(tr("fx_title"))
        self.setMinimumSize(1160, 620)
        # Assez large pour que les colonnes du tableau tiennent sans défilement :
        # 260 (bibliothèque) + 300 (plan de feu) + séparateurs + LAYER_TABLE_W.
        # Le minimum reste bas : sur un petit écran les colonnes se resserrent
        # d'elles-mêmes, et replier la bibliothèque (◀) ou le plan de feu (▶)
        # rend leurs 220 + 260 px au tableau — de quoi tout afficher même là.
        self.resize(LAYER_TABLE_W + 620, 800)
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

    def _scroll_library_to_bottom(self, tours=6):
        """Amène la bibliothèque tout en bas, là où atterrit un effet neuf.

        « Mes Effets » est la dernière catégorie de la liste et un effet créé,
        dupliqué ou importé s'ajoute à sa fin : il naît donc hors écran, la
        bibliothèque débordant toujours (90 effets intégrés). On créait un effet
        et il ne se passait rien de visible.

        ⚠️ Défiler une seule fois, même en différé, NE MARCHE PAS — et rallonger
        le délai ne corrige rien. La géométrie se stabilise en DEUX passes : à la
        première les cartes sont déjà placées, mais le conteneur porte encore sa
        hauteur d'avant, donc la barre s'arrête à un maximum périmé, juste
        au-dessus de la carte neuve. Ce n'est qu'à la passe suivante qu'il
        grandit. C'est une course, pas une latence : un report de 50 ms tombe
        dans la même fenêtre et échoue autant qu'un report d'un tour.

        Piège suivant, pour qui voudrait s'arrêter dès que la carte est visible :
        `mapTo` rend lui aussi une position périmée à la première passe, et la
        carte a l'air en vue alors qu'elle ne l'est pas. Aucune lecture de
        géométrie n'est fiable à cet instant.

        D'où le parti pris : réaffirmer « en bas » sur quelques tours de boucle
        au lieu d'interroger quoi que ce soit. Chaque tour utilise le maximum du
        moment ; dès que la plage cesse de croître les tours suivants ne font
        plus rien. Le tout dure quelques millisecondes, invisible à l'œil, et se
        termine toujours — il n'y a pas de condition à satisfaire.
        """
        sc = getattr(self, '_lib_scroll', None)
        if sc is None:
            return
        vsb = sc.verticalScrollBar()

        def au_fond(reste):
            try:
                vsb.setValue(vsb.maximum())
            except RuntimeError:
                return          # fenêtre refermée entre-temps
            if reste > 0:
                QTimer.singleShot(0, lambda: au_fond(reste - 1))

        QTimer.singleShot(0, lambda: au_fond(tours))

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

    # ── Colonne 1 : bibliothèque ──────────────────────────────────────────────

    def _mk_library_panel(self):
        panel = QWidget()
        panel.setFixedWidth(260)
        panel.setStyleSheet("background: #0a0a0a;")
        self._lib_panel = panel

        lv = QVBoxLayout(panel)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet("background: #080808; border-bottom: 1px solid #161616;")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(14, 0, 10, 0)
        self._lib_hdr_layout = hh
        ttl = QLabel(tr("fx_effects"))
        ttl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        ttl.setStyleSheet("color: #ddd;")
        hh.addWidget(ttl)
        hh.addStretch()
        self._lib_title = ttl
        save_btn = QPushButton(tr("ee2_add_effect"))
        save_btn.setFixedHeight(26)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setToolTip(tr("ee2_add_tip"))
        save_btn.setStyleSheet("""
            QPushButton {
                background: #0a1a0a; color: #285028;
                border: 1px solid #1a3a1a; border-radius: 5px;
                font-size: 10px; font-weight: bold; padding: 0 8px;
            }
            QPushButton:hover { background: #0d220d; color: #55aa55; border-color: #2a5a2a; }
        """)
        save_btn.clicked.connect(self._on_add_effect)
        hh.addWidget(save_btn)
        self._lib_save_btn = save_btn

        # Repli de la bibliothèque : rend ses 260 px au tableau des couches,
        # utile dès que la fenêtre est trop étroite pour toutes les colonnes.
        collapse = QPushButton("◀")
        collapse.setFixedSize(20, 26)
        collapse.setCursor(Qt.PointingHandCursor)
        collapse.setToolTip(tr("ee2_fold_list"))
        collapse.setStyleSheet("""
            QPushButton {
                background: #101010; color: #444;
                border: 1px solid #1e1e1e; border-radius: 5px;
                font-size: 9px; font-weight: bold; padding: 0;
            }
            QPushButton:hover { color: #00d4ff; border-color: #00d4ff; }
        """)
        collapse.clicked.connect(self._toggle_library)
        hh.addWidget(collapse)
        self._lib_collapse_btn = collapse
        self._lib_collapsed    = False

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
        # Même ressort de queue que la colonne du plan : replié, le panneau n'a
        # plus d'élément extensible et son bouton dériverait vers le milieu.
        lv.addStretch(0)
        self._lib_scroll = scroll   # pour défiler jusqu'à l'effet sélectionné

        self._rebuild_library()
        return panel

    def _toggle_library(self):
        """Replie / déplie la colonne des effets pour élargir le tableau."""
        self._lib_collapsed = not self._lib_collapsed
        collapsed = self._lib_collapsed

        self._lib_panel.setFixedWidth(40 if collapsed else 260)
        self._lib_title.setVisible(not collapsed)
        self._lib_save_btn.setVisible(not collapsed)
        self._lib_scroll.setVisible(not collapsed)
        self._lib_hdr_layout.setContentsMargins(
            *((6, 0, 6, 0) if collapsed else (14, 0, 10, 0)))
        self._lib_collapse_btn.setText("▶" if collapsed else "◀")
        self._lib_collapse_btn.setToolTip(
            tr("ee2_show_list") if collapsed
            else "Replier la liste des effets")

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
        mes_hdr_lbl = QLabel(tr("fx_my_effects"))
        mes_hdr_lbl.setStyleSheet(
            "color: #2a2a2a; font-size: 8px; font-weight: bold; "
            "letter-spacing: 1.5px; background: transparent;"
        )
        mes_hdr_h.addWidget(mes_hdr_lbl, 1)
        imp_btn = QPushButton("+")
        imp_btn.setFixedSize(16, 16)
        imp_btn.setToolTip(tr("ee2_import_effect"))
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
            empty_lbl = QLabel(tr("ee2_no_effect"))
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
            ren_btn.setToolTip(tr("fx_rename"))
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
                self._switch_to_effect(e)

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

    def _on_add_effect(self):
        """Bouton « Ajouter un effet » : laisse choisir importer ou créer."""
        mode = _ask_add_effect_mode(self, bool(self._layers))
        if mode == "import":
            self._import_custom_effect()
        elif mode == "create":
            self._save_current_as_custom()

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
            self._scroll_library_to_bottom()
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
        self._scroll_library_to_bottom()

    def _show_card_context_menu(self, card, pos, eff: dict, deletable: bool):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        act_dup = menu.addAction(tr("fx_duplicate"))
        act_exp = menu.addAction(tr("fx_export"))
        if deletable:
            menu.addSeparator()
            act_del = menu.addAction(tr("fx_delete"))
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
        self._scroll_library_to_bottom()

    def _delete_custom_effect(self, eff: dict):
        """Supprime un effet de « Mes Effets », sur confirmation.

        Le ✕ de la carte fait 14 px et vit juste à côté du ✎ de renommage : un
        clic de travers effaçait un effet pour de bon, sans retour possible.
        Point de passage unique du ✕ ET du menu contextuel — la confirmation
        est donc ici, pas dans les deux appelants.
        """
        from PySide6.QtWidgets import QMessageBox
        name = eff.get("name", "")
        if QMessageBox.question(
                self, tr("fx_delete_title"),
                tr("fx_f_delete_confirm", name=name),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel) != QMessageBox.Yes:
            return
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
            QMessageBox.warning(self, tr("fx_export_error"), str(exc))

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
            QMessageBox.warning(self, tr("fx_import_error"), tr("fx_f_invalid_file", exc=exc))
            return
        if not isinstance(data, dict) or "layers" not in data:
            QMessageBox.warning(self, tr("fx_import_error"), tr("fx_invalid_effect"))
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
        self._scroll_library_to_bottom()

    def _rename_custom_effect(self, eff: dict):
        old_name = eff.get("name", "")
        existing = {e.get("name", "") for e in self._custom_effects}
        new_name, ok = _ask_name(self, "Renommer l'effet", "Nouveau nom :", old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        if new_name in existing:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("fx_name_taken"), tr("fx_f_effect_exists", new_name=new_name))
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

        self._refresh_mode_btns()
        return self._simple_panel

    # ── Colonne 3 : plan de feu + contrôles ──────────────────────────────────

    _PLAN_W = 300

    def _mk_plan_panel(self):
        panel = QWidget()
        panel.setFixedWidth(self._PLAN_W)
        panel.setStyleSheet("background: #0a0a0a;")
        self._plan_panel = panel

        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        # ── En-tête repliable ─────────────────────────────────────────────────
        # Symétrique de celui de la bibliothèque : les deux colonnes latérales se
        # replient de la même façon, et leurs 260 + 300 px reviennent au tableau
        # des couches quand la fenêtre est trop étroite pour toutes ses colonnes.
        hdr = QWidget()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet("background: #080808; border-bottom: 1px solid #161616;")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(10, 0, 14, 0)
        self._plan_hdr_layout = hh

        collapse = QPushButton("▶")
        collapse.setFixedSize(20, 26)
        collapse.setCursor(Qt.PointingHandCursor)
        collapse.setToolTip(tr("ee2_fold_plan"))
        collapse.setStyleSheet("""
            QPushButton {
                background: transparent; color: #3a3a3a;
                border: 1px solid #1e1e1e; border-radius: 4px;
                font-size: 10px; font-weight: bold;
            }
            QPushButton:hover { color: #00d4ff; border-color: #1e3a44; background: #0a1a1f; }
        """)
        collapse.clicked.connect(self._toggle_plan)
        hh.addWidget(collapse)
        self._plan_collapse_btn = collapse
        self._plan_collapsed    = False

        ttl = QLabel(tr("fx_light_plan"))
        ttl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        ttl.setStyleSheet("color: #ddd;")
        hh.addStretch()
        hh.addWidget(ttl)
        self._plan_title = ttl

        pv.addWidget(hdr)

        # ── AU-DESSUS du plan de feu : ASSIGNER ───────────────────────────────
        # Widget créé dans le panneau simple (colonne 2) mais reparenté ici.
        # « Ajuster tout » a disparu : chaque colonne du tableau se règle
        # désormais depuis son en-tête, qui écrit sur toutes les couches.
        self._plan_repliables = []   # ce que le repli doit masquer
        sp = getattr(self, '_simple_panel', None)
        if sp is not None:
            w = getattr(sp, '_assign_widget', None)
            if w is not None:
                pv.addWidget(w)
                self._plan_repliables.append(w)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet("QFrame { border: none; background: #161616; }")
            pv.addWidget(sep)
            self._plan_repliables.append(sep)

        # ── Plan de feu (remplit le reste) ────────────────────────────────────
        try:
            from plan_de_feu import PlanDeFeu
            projectors = getattr(self._main_window, 'projectors', [])
            # select_only : le plan sert à SÉLECTIONNER des projos pour la cible
            # « Sélection » (clic + lasso), sans jamais modifier leur état réel
            # (pas de drag pan/tilt ni de menus couleur) pendant l'édition d'effet.
            self._plan_widget = PlanDeFeu(projectors, self._main_window,
                                          show_toolbar=False, select_only=True)
            pv.addWidget(self._plan_widget, 1)
            self._plan_repliables.append(self._plan_widget)
        except Exception:
            self._plan_widget = None
            fallback = QLabel(tr("fx_plan_unavailable"))
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setStyleSheet("color: #444; font-size: 11px;")
            pv.addWidget(fallback, 1)
            self._plan_repliables.append(fallback)

        # Ressort de queue : une fois le panneau replié, tout ce qui pouvait
        # s'étirer est masqué et la colonne n'a plus rien pour absorber sa
        # hauteur — le bouton se retrouverait centré au milieu du vide au lieu
        # de rester en haut, en face de celui de la bibliothèque.
        pv.addStretch(0)

        return panel

    def _toggle_plan(self):
        """Replie / déplie le plan de feu pour élargir le tableau des couches.

        Le plan sert à composer la cible « Sélection » ; une fois la sélection
        figée dans les couches, il ne sert plus à rien pendant qu'on règle les
        colonnes — d'où l'intérêt de lui rendre sa place.
        """
        self._plan_collapsed = not self._plan_collapsed
        replie = self._plan_collapsed

        self._plan_panel.setFixedWidth(40 if replie else self._PLAN_W)
        self._plan_title.setVisible(not replie)
        for w in self._plan_repliables:
            w.setVisible(not replie)
        self._plan_hdr_layout.setContentsMargins(
            *((6, 0, 6, 0) if replie else (10, 0, 14, 0)))
        self._plan_collapse_btn.setText("◀" if replie else "▶")
        self._plan_collapse_btn.setToolTip(
            tr("ee2_show_plan") if replie else "Replier le plan de feu")

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
        cur_duration = self._effect_duration
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
        # Second clic sur un bouton déjà assigné à CET effet = désassignation.
        # Sans ça le bouton se décochait visuellement puis _refresh_assign_btns
        # le recochait aussitôt : impossible de libérer un E1-E8.
        cfg_map  = getattr(self._main_window, '_button_effect_configs', {})
        existing = cfg_map.get(btn_idx)
        if isinstance(existing, dict) and existing.get("name") == cur_name:
            if hasattr(self._main_window, '_on_effect_assigned'):
                self._main_window._on_effect_assigned(btn_idx, None)
            self._refresh_assign_btns()
            self._rebuild_library()   # retire le badge « E1 » de la carte
            return
        eff_dict = next(
            (e for e in BUILTIN_EFFECTS + self._custom_effects if e.get("name") == cur_name),
            None
        )
        cfg = {
            "name":      cur_name,
            "type":      eff_dict.get("type", "") if eff_dict else "",
            "layers":    [l.to_dict() for l in self._layers],
            "play_mode": self._play_mode,
            "duration":  self._effect_duration,
        }
        if hasattr(self._main_window, '_on_effect_assigned'):
            self._main_window._on_effect_assigned(btn_idx, cfg)
        self._refresh_assign_btns()
        self._rebuild_library()   # affiche le badge « E1 » sur la carte

    # ── Header / Footer ───────────────────────────────────────────────────────

    def _mk_header(self):
        w = QWidget()
        w.setFixedHeight(48)
        w.setStyleSheet("background: #141414; border-bottom: 1px solid #1e1e1e;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 7, 14, 7)
        lay.setSpacing(8)
        title = QLabel(tr("fx_title"))
        title.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        lay.addWidget(title)
        if self._clips:
            n   = len(self._clips)
            sub = QLabel(tr("fx_f_blocks_sel", n=n, a0='s' if n > 1 else '', a1='s' if n > 1 else ''))
            sub.setStyleSheet("color: #444; font-size: 11px; margin-left: 8px;")
            lay.addWidget(sub)
        lay.addStretch()

        # ── Actions déplacées en haut (comme le patch DMX) ────────────────────
        # Sortie live · Annuler · Sauvegarder.
        self._btn_live_dmx = QPushButton(tr("fx_live_out"))
        self._btn_live_dmx.setCheckable(True)
        self._btn_live_dmx.setFixedHeight(34)
        self._btn_live_dmx.setCursor(Qt.PointingHandCursor)
        self._btn_live_dmx.setToolTip(
            tr("fx_live_out_hint"))
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

        cancel = QPushButton(tr("fx_cancel"))
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

        ok = QPushButton(tr("fx_save"))
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

    def _switch_to_effect(self, eff: dict):
        """Changement d'effet depuis la bibliothèque — garde d'abord le travail
        en cours.

        `_apply_preset` vide `self._layers` : sans ce passage, cliquer sur une
        autre carte pour la regarder JETAIT toutes les couches éditées de
        l'effet précédent. La machinerie pour les garder existait déjà et était
        complète (`_autosave_on_close` : boutons E1-E8, pads FX, bibliothèque
        d'effets, fichier custom_effects) — elle n'était simplement branchée
        que sur la fermeture de l'éditeur. Même contrat ici : on ne perd rien
        en naviguant, et revenir sur l'effet le retrouve tel qu'on l'a laissé.

        Volontairement PAS dans `_apply_preset` : la duplication, l'import et
        la sauvegarde sous un nouveau nom passent aussi par lui, mais après
        avoir déjà déplacé `_selected_card` sur le nouvel effet — l'autosave y
        écrirait les couches courantes sous le nom du nouveau.
        """
        if eff.get("name", "") != self._selected_card:
            self._autosave_on_close()
        self._apply_preset(eff)

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
            self._refresh_mode_btns()
        self._simple_panel.set_effect(eff, self._layers)
        self._rebuild_library()
        self._refresh_assign_btns()
        self._start_preview()

    # ── Prévisualisation live ─────────────────────────────────────────────────

    def _start_preview(self):
        self._preview_t0 = _time.monotonic()
        self._preview_clock, self._preview_clock_ts = 0.0, None
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
            self._release_live_dmx()

    def _push_overrides_to_3d(self, overrides):
        """Miroir de la sortie live dans la fenêtre 3D, si elle est ouverte.

        La 3D lit l'état persistant des projecteurs : sans ce relais elle reste
        sur l'état d'avant l'effet, la boucle DMX restaurant les projecteurs
        aussitôt la trame envoyée.
        """
        mw   = self._main_window
        p3d  = getattr(mw, '_plan3d', None) if mw is not None else None
        if p3d is None:
            return
        try:
            if overrides is not None and not p3d.isVisible():
                overrides = None
            p3d.set_fx_overrides(overrides)
        except RuntimeError:
            pass    # fenêtre 3D déjà détruite côté C++

    def _release_live_dmx(self):
        """Coupe la sortie live — à appeler sur toute sortie de l'éditeur."""
        mw = self._main_window
        if mw is not None:
            mw._editor_live_overrides = None
        self._push_overrides_to_3d(None)

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
            # L'effet tourne pour de vrai : on lit SON horloge de phase, sinon
            # l'aperçu et la 3D dérivent du DMX dès que le fader FX n'est pas à
            # 100 % (le temps déformé n'avance pas à la seconde).
            t = getattr(mw, '_effect_clock', None)
            if t is None:
                t = _time.monotonic() - getattr(mw, 'effect_t0', self._preview_t0)
        else:
            # Aperçu seul : même horloge déformée, entretenue ici. Bouger la
            # VITESSE ne doit pas faire sauter l'aperçu non plus.
            _now  = _time.monotonic()
            _mult = max(0.01, getattr(mw, 'effect_speed', 80) / 100.0) if mw else 0.8
            _last = self._preview_clock_ts
            _dt   = 0.0 if _last is None else min(0.25, max(0.0, _now - _last))
            self._preview_clock_ts = _now
            self._preview_clock   += _dt * _mult
            t = self._preview_clock
        try:
            overrides = self._compute_preview(t)
            if plan is not None:
                plan.set_htp_overrides(overrides)
            # Sortie live : la boucle DMX les applique puis les restaure
            _live = self._btn_live_dmx.isChecked()
            if self._main_window is not None:
                self._main_window._editor_live_overrides = overrides if _live else None
            # La 3D reflète ce qui part sur le DMX, donc armée par le même bouton
            self._push_overrides_to_3d(overrides if _live else None)
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
        elif forme == "Un par un":
            # Repli seulement : le vrai « Un par un » est calculé sur le rang
            # (voir `core.chase_slot`), pas échantillonné sur x.
            return 1.0 if x < 0.25 else 0.0
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

        # Le fader FX ne multiplie plus la fréquence : il déforme l'HORLOGE
        # (`_preview_clock` / `MainWindow._effect_clock`), pour que le bouger
        # change la cadence sans faire sauter la phase. L'appliquer ici aussi le
        # compterait deux fois. Vitesse aperçu = vitesse live, comme avant.

        n      = len(projectors)
        result = {}

        # Cible « Sélection » : clés (groupe, index_local) sur la liste COMPLÈTE
        # (convention plan de feu) + set par couche pour un test O(1). Identique
        # au moteur live pour la parité aperçu/show.
        _all_proj = getattr(self._main_window, 'projectors', [])
        _sel_key_by_id = {id(p): k for p, k in
                          zip(_all_proj, projector_selection_keys(_all_proj))}
        # {clé: rang} et non un set : sur une cible « Sélection », l'étalement
        # doit suivre l'ORDRE de sélection (chenillard 1→2→3), pas l'ordre du
        # patch. Idem moteur live, pour la parité aperçu/show.
        _layer_sel = {id(_l): layer_selection_ranks(_l) for _l in self._layers}

        # Amplitude min/max par groupe (répliquée sur les couches) — parité moteur.
        _group_amp = {}
        for _l in self._layers:
            _gd = getattr(_l, 'group_amp', None)
            if _gd:
                _group_amp.update(_gd)

        # POSITION : centre de la trajectoire, par couche et par lyre. Résolu sur
        # TOUTES les lyres (pas la liste filtrée) — même règle que le moteur live,
        # dont l'appariement de secours se fait par rang.
        _all_lyres = [p for p in _all_proj
                      if getattr(p, 'fixture_type', '') in ('Moving Head', 'Lyre')]
        _presets = getattr(self._main_window, 'position_presets', []) or []
        _pos_centers = {}
        for _l in self._layers:
            if getattr(_l, 'attribute', '') not in ("Pan", "Tilt", "Pan/Tilt"):
                continue
            _pr = find_position_preset(_presets,
                                       getattr(_l, 'pos_preset_idx', None),
                                       getattr(_l, 'pos_preset_name', ''))
            if _pr is not None:
                _pos_centers[id(_l)] = position_preset_values(_pr, _all_lyres)

        # SYM : quelles lyres partent en Pan miroir. Le partage se fait sur la
        # POSITION sur le plan (même règle que le bouton SYM du plan 2D), pas
        # sur l'index de la fixture dans l'effet : deux règles différentes pour
        # le même mot, c'était intenable. Import différé — effect_editor est
        # importé par plan_de_feu en amont.
        _sym_ids = {}
        if any(getattr(_l, 'sym_pan', False) for _l in self._layers):
            from plan_de_feu import sym_mirror_ids as _sym_mirror_ids
            _lyres_fx = [p for p in projectors
                         if getattr(p, 'fixture_type', '') in ('Moving Head', 'Lyre')]
            _mir = _sym_mirror_ids(_lyres_fx, _all_proj)
            for _l in self._layers:
                if getattr(_l, 'sym_pan', False):
                    _sym_ids[id(_l)] = _mir

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
                # Index d'étalement : par défaut la place dans le patch, mais sur
                # une cible « Sélection » la place dans la SÉLECTION (ordre des
                # clics sur le plan) — c'est ce qui rend le chenillard dirigeable.
                i_fx, n_fx = i, n
                if preset == "Selection":
                    _ranks = _layer_sel.get(id(layer), {})
                    _k     = _sel_key_by_id.get(id(proj))
                    if _k not in _ranks:
                        continue
                    i_fx, n_fx = _ranks[_k], max(1, len(_ranks))
                elif preset == "Pair"   and i % 2 != 0: continue
                elif preset == "Impair" and i % 2 != 1: continue
                elif preset in _LETTER_TO_GROUP and getattr(proj, 'group', '') != _LETTER_TO_GROUP[preset]: continue
                if groups and getattr(proj, 'group', '') not in [_LETTER_TO_GROUP.get(g, g) for g in groups]: continue

                # GROUPER : replier l'index sur des paquets. Les fixtures d'un
                # même paquet partagent la phase, donc partent ensemble.
                i_fx, n_fx = block_index(i_fx, n_fx, getattr(layer, 'block', 1))

                freq      = layer_frequency(layer.speed)
                spread    = layer.spread / 100.0
                # Mouvement (Pan/Tilt) : plafonner a 1.0 = etalement parfait, pas de
                # re-enroulement des lyres au-dela (idem moteur live).
                if layer.attribute in ("Pan", "Tilt", "Pan/Tilt"):
                    spread = min(1.0, spread)
                phase     = layer.phase  / 100.0
                direction = getattr(layer, 'direction', 1)
                if direction == 0:   # bounce
                    t_osc = abs(2 * ((freq * t) % 1.0) - 1)
                    x = (t_osc + i_fx / max(n_fx, 1) * spread + phase) % 1.0
                elif direction == -1:  # arrière
                    x = (freq * t - i_fx / max(n_fx, 1) * spread + phase) % 1.0
                else:                  # avant (défaut)
                    x = (freq * t + i_fx / max(n_fx, 1) * spread + phase) % 1.0

                if layer.forme == "Un par un":
                    # Chenillard exclusif : allumée uniquement quand c'est son
                    # tour. Position prise sur le RANG, pas sur la forme d'onde
                    # (identique au moteur live — parité aperçu/show).
                    raw = 1.0 if chase_slot(freq * t + phase, n_fx,
                                            direction) == i_fx else 0.0
                elif layer.forme in ("Audio", "Aléatoire"):   # ancien nom + nouveau
                    # Même tirage que le live (core.random_wave) : la cadence
                    # 15 Hz codée en dur ignorait VIT et ne montrait qu'une
                    # plage 0,1-0,9 là où le show allait de 0 à 1.
                    raw = random_wave(freq, t, i_fx)
                else:
                    raw = self._wave(layer.forme, x)

                # FADE : adoucit la forme vers un sinus (0=dur, 100=doux).
                # Sans objet sur « Un par un » : il rallumerait les voisins.
                fade_f = getattr(layer, 'fade', 0) / 100.0
                if fade_f > 0 and layer.forme != "Un par un":
                    sin_val = (math.sin(2 * math.pi * x) + 1) / 2
                    raw = raw * (1.0 - fade_f) + sin_val * fade_f

                _grp = getattr(proj, 'group', '')
                if _grp in _group_amp:
                    min_v = _group_amp[_grp][0] / 100.0
                    max_v = _group_amp[_grp][1] / 100.0
                else:
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
                    pan_sign = -1 if (sym_pan and id(proj) in _sym_ids.get(id(layer), ())) else 1
                    _ctr = _pos_centers.get(id(layer), {}).get(id(proj))
                    c_pan = _ctr[0] if _ctr is not None else 32768
                    pan_v = int(max(0, min(65535, c_pan + pan_sign * (raw - 0.5) * 2 * amp)))
                    has_movement = True
                elif attr == "Tilt":
                    amp = (layer.size / 100.0) * 8192
                    _ctr = _pos_centers.get(id(layer), {}).get(id(proj))
                    c_tilt = _ctr[1] if _ctr is not None else 32768
                    tilt_v = int(max(0, min(65535, c_tilt + (raw - 0.5) * 2 * amp)))
                    has_movement = True
                elif attr == "Pan/Tilt":
                    sid      = getattr(layer, 'mouvement_shape', 'cercle')
                    sdef     = PAN_TILT_SHAPES.get(sid, PAN_TILT_SHAPES.get('cercle', {}))
                    pan_cfg  = sdef.get('pan',  ('Sinus',  0, 1.0))
                    tilt_cfg = sdef.get('tilt', ('Sinus', 25, 1.0))
                    pt_amp   = (layer.size / 100.0) * 8192
                    sym_pan  = getattr(layer, 'sym_pan', False)
                    pan_sign = -1 if (sym_pan and id(proj) in _sym_ids.get(id(layer), ())) else 1
                    # SENS de la trajectoire : → avant · ← inverse (la lyre tourne
                    # dans l'autre sens) · ↔ aller-retour. On agit sur le TEMPS,
                    # pas sur l'étalement (c'est le sens de MOUVEMENT de chaque lyre).
                    def _pt_time(freq, _d=direction):
                        if _d == 0:   return abs(2 * ((freq * t) % 1.0) - 1)
                        if _d == -1:  return -freq * t
                        return freq * t
                    # Centre de la trajectoire : POSITION choisie, sinon milieu
                    # de course (l'aperçu n'a pas d'état capturé, contrairement
                    # au moteur live).
                    _ctr   = _pos_centers.get(id(layer), {}).get(id(proj))
                    c_pan  = _ctr[0] if _ctr is not None else 32768
                    c_tilt = _ctr[1] if _ctr is not None else 32768
                    p_forme, p_ph, p_mult = pan_cfg
                    if p_forme and p_forme != "Fixe":
                        p_freq = layer_frequency(layer.speed, p_mult)
                        p_x    = (_pt_time(p_freq) + i_fx / max(n_fx, 1) * spread + phase + p_ph / 100.0) % 1.0
                        p_raw  = self._wave(p_forme, p_x)
                        pan_v  = int(max(0, min(65535, c_pan + pan_sign * (p_raw - 0.5) * 2 * pt_amp * PAN_ANGULAR_RATIO)))
                    t_forme, t_ph, t_mult = tilt_cfg
                    if t_forme and t_forme != "Fixe":
                        t_freq = layer_frequency(layer.speed, t_mult)
                        t_x    = (_pt_time(t_freq) + i_fx / max(n_fx, 1) * spread + phase + t_ph / 100.0) % 1.0
                        t_raw  = self._wave(t_forme, t_x)
                        tilt_v = int(max(0, min(65535, c_tilt + (t_raw - 0.5) * 2 * pt_amp)))
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
                # (la couleur de sa ROUE sur un spot sans RGB, qui n'a pas de
                #  RGB à moduler — même règle que le moteur, et c'est bien la
                #  roue et non du blanc en dur : cf. core.effect_dim_base_color)
                color = effect_dim_base_color(proj, QColor(proj.color))
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
            clip.effect_duration  = self._effect_duration
            clip.effect_name      = self._selected_card or ""
        self.accept()
