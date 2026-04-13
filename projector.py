"""
Classe Projector pour la gestion des projecteurs DMX
"""
from PySide6.QtGui import QColor


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
        self.pan = 128                # Pan (0-255, centre=128)
        self.tilt = 128               # Tilt (0-255, centre=128)
        self.gobo = 0                 # Gobo wheel (0-255)
        self.zoom = 0                 # Zoom (0-255)
        self.shutter = 255            # Shutter/Iris (0-255)
        self.color_wheel = 0          # Color wheel (0-255)
        self.prism = 0                # Prism (0=off, >0=actif)
        self.channel_defaults = {}    # {ch_type: 0-255} valeurs par défaut par canal
        self.color_wheel_slots = []   # [{"name": str, "color": "#rrggbb", "dmx": int}] depuis OFL
        self.gobo_wheel_slots  = []   # [{"name": str, "color": "#rrggbb", "dmx": int}] depuis OFL

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
