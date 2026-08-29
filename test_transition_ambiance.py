# -*- coding: utf-8 -*-
"""L'ambiance tenue sur un fader + pad memoire doit SURVIVRE a un changement
de media, alors que le look du media qui se termine, lui, s'eteint.

Regression : `on_media_status_changed` appelait `full_blackout()` en fin de
media Play Lumiere. Or full_blackout descend les 9 faders et vide `active_pads`
-- exactement ce dont depend la couche HTP de `send_dmx_update()`. L'ambiance
mourait donc a chaque transition (« une legere coupure entre chaque media »).
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
app = QApplication.instance() or QApplication([])

from projector import Projector
from main_window import MainWindow


class FauxFader:
    def __init__(self, value): self.value = value
    def update(self): pass


class FauxPad:
    """Pad memoire AKAI : full_blackout lit sa couleur et le restyle."""
    def property(self, _name): return QColor("#00ff00")
    def setStyleSheet(self, _css): pass


class Stub:
    """Juste ce que les deux blackouts touchent."""
    # `transition_blackout` repose ensuite le look tenu sur les colonnes GROUPE
    # (cf. test_lumiere_manuelle_survit_media). Ici l'ambiance est sur une
    # colonne MEMOIRE : elle est portee par la couche HTP des memoires, pas par
    # les projecteurs — le rig doit donc bien rester a zero apres la transition.
    _slot_groups        = staticmethod(MainWindow._slot_groups)
    set_proj_level      = MainWindow.set_proj_level
    restore_manual_look = MainWindow.restore_manual_look

    def send_dmx_update(self): pass
    def _update_color_wheel(self, p, color): pass

    def __init__(self):
        self._fader_map = [{"type": "memory", "mem_col": i, "label": ""} for i in range(8)]
        self._muted_faders = set()
        self.projectors = [Projector(i, f"P{i}", 1 + i * 10) for i in range(3)]
        for p in self.projectors:          # un look de REC en cours
            p.level = 90
            p.base_color = QColor("#ff0000")
            p.color = QColor("#ff0000")
        self.faders = {i: FauxFader(0) for i in range(9)}
        self.faders[4].value = 75          # <- le fader qui porte l'ambiance
        self.active_pads = {4: FauxPad()}  # <- le pad memoire de l'ambiance
        self.effect_buttons = []
        self.active_effect = None
    def stop_effect(self): pass


s = Stub()
MainWindow.transition_blackout(s)

print("apres transition_blackout :")
print("  niveaux projecteurs :", [p.level for p in s.projectors])
print("  fader d'ambiance    :", s.faders[4].value)
print("  active_pads         :", len(s.active_pads), "pad(s)")

# Le look du media qui se termine s'eteint...
assert all(p.level == 0 for p in s.projectors), "le look ne s'eteint pas"
assert all(p.color == QColor("black") for p in s.projectors)
# ...mais la couche HTP qui porte l'ambiance est INTACTE.
assert s.faders[4].value == 75, "le fader d'ambiance a ete descendu -> HTP morte"
assert 4 in s.active_pads, "le pad memoire a ete lache -> HTP morte"
assert all(s.faders[i].value == 0 for i in range(9) if i != 4), "autres faders touches"

# Et full_blackout, lui, doit toujours TOUT couper (bouton Blackout explicite).
s2 = Stub()
s2.midi_handler = type("M", (), {"midi_out": None})()
MainWindow.full_blackout(s2)
print("\napres full_blackout (action explicite) :")
print("  fader d'ambiance    :", s2.faders[4].value)
print("  active_pads         :", len(s2.active_pads), "pad(s)")
assert s2.faders[4].value == 0, "full_blackout doit tout couper"
assert s2.active_pads == {}, "full_blackout doit lacher les pads"

print("\nOK - l'ambiance traverse la transition, le blackout explicite coupe tout.")
