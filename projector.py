"""
Classe Projector pour la gestion des projecteurs DMX
"""
from PySide6.QtGui import QColor

import os as _os, time as _time, traceback as _traceback

# ── Mouchard DEBUG (build 3.1.63) — barre LED qui s'éteint/strobe au patch ─────
# But : logger QUI met la barre à level=0 / couleur=noir, avec la pile d'appel,
# pour identifier la régression 3.1.62. Guardé, dédupliqué (une pile = 1 ligne),
# plafonné, et JAMAIS fatal (tout est try/except). Mettre _BAR_DEBUG = False
# pour désactiver complètement (build normal).
_BAR_DEBUG = True
_BAR_MATCH = "swing"      # sous-chaîne (minuscules) du NOM des fixtures surveillées
_BAR_SEEN  = set()        # signatures de piles déjà loggées (anti-flood)
_BAR_MAX   = 60           # plafond d'événements distincts


def _bar_logpath():
    try:
        d = _os.path.join(_os.path.expanduser("~"), "AppData", "Local", "MyStrow", "Logs")
        _os.makedirs(d, exist_ok=True)
        return _os.path.join(d, "bar_debug.log")
    except Exception:
        return _os.path.join(_os.path.expanduser("~"), "mystrow_bar_debug.log")


def _bar_log(kind, proj, old, new):
    try:
        if len(_BAR_SEEN) >= _BAR_MAX:
            return
        stack = _traceback.extract_stack()[:-2]          # sans _bar_log ni __setattr__
        sig = tuple((fr.filename, fr.lineno) for fr in stack[-8:])
        if sig in _BAR_SEEN:
            return
        _BAR_SEEN.add(sig)
        with open(_bar_logpath(), "a", encoding="utf-8") as f:
            f.write(f"\n===== {_time.strftime('%H:%M:%S')}  '{getattr(proj, 'name', '?')}' "
                    f"({getattr(proj, 'group', '?')})  {kind}: {old} -> {new} =====\n")
            f.write("".join(_traceback.format_list(stack[-18:])))
    except Exception:
        pass


if _BAR_DEBUG:
    try:
        with open(_bar_logpath(), "a", encoding="utf-8") as _f:
            _f.write(f"\n########## SESSION {_time.ctime()} — mouchard barre actif "
                     f"(match='{_BAR_MATCH}') ##########\n")
    except Exception:
        pass


class Projector:
    """Represente un projecteur avec son etat (niveau, couleur, mute)"""

    def __init__(self, group, name="", fixture_type="PAR LED"):
        self.group = group
        self.name = name              # Nom affiche ("Face 1", "Lyre SL"...)
        self.fixture_type = fixture_type  # Categorie ("PAR LED", "Moving Head"...)
        self.start_address = 1        # Adresse DMX de depart (1-512)
        self.universe = 0             # Univers Art-Net (0-3)
        self.level = 0
        self.base_color = QColor("white")
        self.color = QColor("black")
        self.dmx_mode = "Manuel"
        self.muted = False
        self.pan = 32768              # Pan  16-bit (0-65535, centre=32768)
        self.tilt = 32768             # Tilt 16-bit (0-65535, centre=32768)
        self.fixture_height = None    # Hauteur de suspension (m), None = auto (7m truss)
        self.pos_3d_x = None          # Position 3D indépendante X (m), None = dérivé du plan 2D
        self.pos_3d_z = None          # Position 3D indépendante Z (m), None = dérivé du plan 2D
        self.body_rotation = 0.0     # Rotation du corps sur la truss (degrés, 0-360)
        self.gobo = 0                 # Gobo wheel (0-255)
        self.zoom = 0                 # Zoom (0-255)
        self.shutter = 255            # Shutter/Iris (0-255)
        self.shutter_inverted = False  # True si convention inversée (0=ouvert, 255=fermé)
        self.color_wheel = 0          # Color wheel (0-255)
        self.prism = 0                # Prism (0=off, >0=actif)
        self.gobo_rotation = 0        # Rotation gobo (0-255)
        self.prism_rotation = 0       # Rotation prisme (0-255)
        self.effects          = 0   # Effects/Macro channel (0-255) — programme interne fixture
        self.channel_defaults = {}    # {ch_type: 0-255} valeurs par défaut par canal
        self.channel_extras   = {}    # {ch_type: 0-255} contrôle brut prioritaire (Reset, Mode…)
        # Canaux spéciaux — contrôle manuel indépendant
        self.uv           = 0   # UV (0-255, direct)
        self.white_boost  = 0   # Blanc extra au-dessus du RGB-dérivé (0-255)
        self.amber_boost  = 0   # Ambre extra (0-255)
        self.orange_boost = 0   # Orange extra (0-255)
        self.color_wheel_slots = []   # [{"name": str, "color": "#rrggbb", "dmx": int}] depuis OFL
        self.gobo_wheel_slots  = []   # [{"name": str, "color": "#rrggbb", "dmx": int}] depuis OFL
        # Limites de mouvement pan/tilt (16-bit, 0–65535 ; 0/65535 = aucune limite)
        self.pan_min  = 0
        self.pan_max  = 65535
        self.tilt_min = 0
        self.tilt_max = 65535
        self.pan_invert    = False  # Inverser le sens du pan (65535 - valeur)
        self.tilt_invert   = False  # Inverser le sens du tilt (65535 - valeur)
        self.pan_tilt_swap = False  # Permuter pan ↔ tilt
        # ── Fixture à pixels (matrice / barre LED) ───────────────────────────
        # Un fixture "matrice" est patché comme N projecteurs enfants (1 par
        # pixel) + éventuellement 1 projecteur "master" pour les canaux globaux
        # (Dim/Strobe). Ces champs relient les enfants entre eux et portent la
        # géométrie (pour le plan de feu 2D/3D). None/0 = projecteur classique.
        self.matrix_id    = None    # identifiant partagé par les pixels d'une même matrice
        self.matrix_role  = None    # "master" | "pixel" | None
        self.pixel_index  = None    # index du pixel dans l'ordre DMX (0-based)
        self.pixel_row    = None    # ligne physique (0-based)
        self.pixel_col    = None    # colonne physique (0-based)
        self.matrix_rows  = 0       # nb de lignes de la matrice
        self.matrix_cols  = 0       # nb de colonnes de la matrice
        self.matrix_phys_w = None   # largeur physique (mm), None = inconnu
        self.matrix_phys_h = None   # hauteur physique (mm), None = inconnu
        self.matrix_rot   = 0       # rotation du bloc sur le plan (0..3 quarts de tour)

    def __setattr__(self, key, value):
        # Mouchard DEBUG (build 3.1.63) : trace qui éteint la barre LED surveillée.
        # Jamais fatal — object.__setattr__ effectue toujours l'écriture réelle.
        if _BAR_DEBUG and key in ("level", "color"):
            try:
                nm = getattr(self, "name", "") or ""
                ft = getattr(self, "fixture_type", "") or ""
                if _BAR_MATCH in nm.lower() or ft == "Barre LED":
                    if key == "level":
                        old = getattr(self, "level", 0)
                        if old not in (0, None) and value == 0:
                            _bar_log("level", self, old, value)
                    elif value is not None:  # key == "color"
                        old = getattr(self, "color", None)
                        try:
                            was_on  = old is not None and (old.red() or old.green() or old.blue())
                            now_off = not (value.red() or value.green() or value.blue())
                        except Exception:
                            was_on = now_off = False
                        if was_on and now_off:
                            _bar_log("color->noir", self,
                                     old.getRgb()[:3] if old else None,
                                     value.getRgb()[:3])
            except Exception:
                pass
        object.__setattr__(self, key, value)

    def set_color(self, color, brightness=None):
        """Definit la couleur de base et recalcule la couleur effective"""
        self.base_color = color
        if brightness is not None:
            self.level = brightness

        if self.level > 0:
            factor = self.level / 100.0
            self.color = QColor(
                int(self.base_color.red() * factor),
                int(self.base_color.green() * factor),
                int(self.base_color.blue() * factor)
            )
        else:
            self.color = QColor(0, 0, 0)

    def set_level(self, level):
        """Definit le niveau de luminosite"""
        self.level = max(0, min(100, level))
        self.set_color(self.base_color)

    def toggle_mute(self):
        """Bascule l'etat mute"""
        self.muted = not self.muted
        return self.muted

    def get_dmx_rgb(self):
        """Retourne les valeurs RGB pour DMX (0-255)"""
        if self.muted or self.level == 0:
            return (0, 0, 0)
        return (self.color.red(), self.color.green(), self.color.blue())

    def __repr__(self):
        return f"Projector({self.group}, level={self.level}, muted={self.muted})"
