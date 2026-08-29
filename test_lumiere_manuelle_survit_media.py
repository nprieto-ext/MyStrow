# -*- coding: utf-8 -*-
"""L'eclairage monte a la main sur l'APC doit survivre au LANCEMENT d'un media.

Remontee : « j'ai monte des lumieres avec mon APC mini mk2 ; quand je lance un
media ca passe au black », « et pareil quand je lance la musique suivante ».

Deux ecritures de noir etaient en cause, toutes deux automatiques (aucune action
de l'utilisateur) :

  * `play_row()` en mode Manuel (sequencer.py) : remettait TOUT le rig a
    level=0 / noir — « Manuel = pas de lumiere » — y compris le look que les
    pads couleur + faders tenaient a la main ;
  * `dmx_blackout()` (lignes PAUSE de la playlist) : descendait les 9 faders a 0
    alors que sa propre docstring promettait de « conserver l'eclairage AKAI ».
    Or un fader a 0 coupe les deux couches HTP de `send_dmx_update()` : c'etait
    la seule chose capable de rallumer l'ambiance apres coup.

Le correctif est `MainWindow.restore_manual_look()` : apres chaque extinction
AUTOMATIQUE, on repose sur les projecteurs ce que l'APC tient reellement — pad
actif + fader leve, colonne non mutee. Ce qui n'est tenu par personne reste noir.
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
    def __init__(self, couleur): self._c = QColor(couleur)
    def property(self, nom):
        return self._c if nom == "base_color" else None
    def setStyleSheet(self, _css): pass


class Stub:
    """Le strict necessaire : colonnes A (face) et B (lat)."""
    _slot_groups = staticmethod(MainWindow._slot_groups)

    def __init__(self):
        self.projectors = []
        for i in range(4):
            p = Projector(i, f"P{i}", 1 + i * 10)
            p.group = "face" if i < 2 else "lat"
            self.projectors.append(p)
        self._fader_map = [{"type": "group", "group": "A", "label": "A"},
                           {"type": "group", "group": "B", "label": "B"}]
        self._fader_map += [{"type": "group", "group": chr(67 + i), "label": ""}
                            for i in range(6)]
        self.faders = {i: FauxFader(0) for i in range(9)}
        self._muted_faders = set()
        self.active_pads = {}
        self.pads = {}
        self.effect_buttons = []
        self.active_effect = None
        self.dmx_sends = 0

    # --- ce que set_proj_level appelle, hors de notre sujet ---
    set_proj_level      = MainWindow.set_proj_level
    restore_manual_look = MainWindow.restore_manual_look

    def send_dmx_update(self): self.dmx_sends += 1
    def _update_color_wheel(self, p, color): pass
    def stop_effect(self): pass

    # --- l'utilisateur monte son look sur l'APC ---
    def monter_look(self, col, couleur, niveau):
        self.active_pads[col] = FauxPad(couleur)
        self.faders[col].value = niveau
        MainWindow.set_proj_level(self, col, niveau)

    def etat(self):
        return [(p.level, p.base_color.name()) for p in self.projectors]


def wipe_manuel(s):
    """La remise a noir de play_row() en mode Manuel, telle quelle."""
    for p in s.projectors:
        p.level = 0
        p.color = QColor("black")
        p.base_color = QColor("black")


# ── 1. Lancement d'un media en mode Manuel ────────────────────────────────────
s = Stub()
s.monter_look(0, "#ff0000", 80)      # colonne A : rouge a 80 % sur les "face"
# la colonne B n'est tenue par personne : elle doit rester noire
print("look monte a la main :", s.etat())
assert s.projectors[0].level == 80 and s.projectors[2].level == 0

wipe_manuel(s)
print("apres le noir de play_row :", s.etat())
assert all(p.level == 0 for p in s.projectors)

MainWindow.restore_manual_look(s)
print("apres restore_manual_look :", s.etat())
assert s.projectors[0].level == 80, "le look tenu a la main ne revient pas"
assert s.projectors[1].level == 80
assert s.projectors[0].base_color == QColor("#ff0000"), "couleur du pad perdue"
assert s.projectors[2].level == 0, "un groupe que personne ne tient doit rester noir"
assert s.projectors[3].level == 0

# ── 2. Fader a 0 : rien a rallumer, meme si le pad est actif ──────────────────
s2 = Stub()
s2.monter_look(0, "#00ff00", 0)
wipe_manuel(s2)
MainWindow.restore_manual_look(s2)
assert all(p.level == 0 for p in s2.projectors), "fader a 0 = pas de lumiere"

# ── 3. Colonne mutee : le mute reste un mute ──────────────────────────────────
s3 = Stub()
s3.monter_look(0, "#0000ff", 90)
s3._muted_faders.add(0)
wipe_manuel(s3)
MainWindow.restore_manual_look(s3)
assert all(p.level == 0 for p in s3.projectors), "une colonne mutee doit rester noire"

# ── 4. Ligne PAUSE : dmx_blackout ne doit plus toucher aux faders ─────────────
s4 = Stub()
s4.monter_look(0, "#ff00ff", 70)
MainWindow.dmx_blackout(s4)
print("apres dmx_blackout (ligne PAUSE) :", s4.etat(), "| fader 0 =", s4.faders[0].value)
assert s4.faders[0].value == 70, "dmx_blackout descend encore les faders -> HTP morte"
assert s4.projectors[0].level == 70, "l'ambiance ne traverse pas la ligne PAUSE"
assert s4.projectors[0].base_color == QColor("#ff00ff")

# ── 5. Fin de media : transition_blackout repose aussi le look tenu ───────────
s5 = Stub()
s5.monter_look(0, "#ffaa00", 60)
for p in s5.projectors:              # par-dessus, le look du REC qui se termine
    p.level = 100
    p.base_color = QColor("#ff0000")
MainWindow.transition_blackout(s5)
print("apres transition_blackout :", s5.etat())
assert s5.projectors[0].level == 60, "le look tenu a la main ne revient pas"
assert s5.projectors[0].base_color == QColor("#ffaa00"), "couleur du REC restee collee"
assert s5.projectors[2].level == 0, "le look du REC deborde sur un groupe non tenu"

print("\nOK - l'eclairage tenu sur l'APC traverse lancement, PAUSE et fin de media.")
