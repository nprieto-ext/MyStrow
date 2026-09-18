# -*- coding: utf-8 -*-
"""« Contenu sequence » : retirer un parametre d'une memoire en un clic.

Contexte (18/09/2026) : mem 99.1 de Niko = 2 projecteurs a niveau 100 blanc,
pan/tilt legerement hors centre, strobe 92. Il la voulait « que du strobe » :
il fallait pouvoir retirer Position et Niveau + couleur sans toucher au strobe.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from light_timeline import (SequenceInfoDialog, memory_param_families,
                            strip_memory_param, compose_memory_params)
from projector import Projector

ECHECS = []


def check(nom, cond):
    print(("  OK   " if cond else "  ECHEC") + "  " + nom)
    if not cond:
        ECHECS.append(nom)


def etat(**kw):
    base = {"group": "lat", "base_color": "#000000", "level": 0,
            "pan": 32768, "tilt": 32768, "uv": 0, "amber_boost": 0,
            "white_boost": 0, "orange_boost": 0, "gobo": 0, "gobo_rotation": 0,
            "zoom": 0, "strobe_speed": 0, "focus": 0, "gobo2": 0, "speed": 0,
            "mode_value": 0, "color_wheel": 0, "prism": 0, "prism_rotation": 0,
            "effects": 0, "iris": 0, "fan_speed": 0, "shutter": 255,
            "channel_extras": {}}
    base.update(kw)
    return base


def mem_99_1():
    return [etat(level=100, base_color="#ffffff", pan=32931, tilt=33422,
                 strobe_speed=92) for _ in range(2)] + [etat() for _ in range(3)]


class FauxMW:
    def __init__(self, etats):
        self.projectors = [Projector("lat", name="P%d" % (i + 1))
                           for i in range(len(etats))]
        self.memories = [[{"cues": [{"projectors": etats}], "loop": True}]]


print("\n1. Familles et retrait")
ps = mem_99_1()[0]
check("99.1 envoie niveau, position, strobe",
      memory_param_families(ps) == ["light", "position", "strobe_speed"])
strip_memory_param(ps, "position")
check("position retiree = cles pan/tilt supprimees",
      "pan" not in ps and "tilt" not in ps)
strip_memory_param(ps, "light")
check("niveau retire = 0 et noir", ps["level"] == 0 and ps["base_color"] == "#000000")
check("il ne reste que le strobe", memory_param_families(ps) == ["strobe_speed"])
params, _ = compose_memory_params([ps])
check("la composition n'impose plus que le strobe",
      set(params) == {"strobe_speed"} and params["strobe_speed"][0] == 92)
check("pan au pied de butee (0) compte comme position",
      "position" in memory_param_families(etat(pan=0)))

print("\n2. La fenetre")
etats = mem_99_1()
dlg = SequenceInfoDialog(None, FauxMW(etats), (0, 0))
check("pastilles : Niveau + couleur / Position / Strobe, 2 projecteurs chacune",
      dlg._families_count() == {"light": 2, "position": 2, "strobe_speed": 2})
dlg._strip("position")
dlg._strip("light")
check("apres retraits : que du strobe, sur les 2",
      dlg._families_count() == {"strobe_speed": 2})
check("les 2 lignes restent affichees (le strobe les garde)", len(dlg._idxs) == 2)
dlg._undo_last()
check("Annuler remet le niveau", dlg._families_count().get("light") == 2)
check("... sans remettre la position (une etape a la fois)",
      "position" not in dlg._families_count())
dlg._undo_last()
check("2e Annuler remet la position", etats[0]["pan"] == 32931)
check("Annuler desactive quand la pile est vide", not dlg._btn_undo.isEnabled())
dlg._strip("strobe_speed", [1])
check("retrait sur une ligne seulement",
      etats[0]["strobe_speed"] == 92 and etats[1]["strobe_speed"] == 0)

print("\n3. Une colonne par canal de la lyre, Suppr pour vider")
from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent

etats = mem_99_1()
mw = FauxMW(etats)
for p in mw.projectors:
    p.dmx_profile = ["Pan", "PanFine", "Tilt", "TiltFine", "Dim", "Shutter",
                     "ColorWheel", "Gobo1", "Prism"]
dlg = SequenceInfoDialog(None, mw, (0, 0))
canaux = dlg._cols[len(dlg._FIXED_COLS):-2]
check("colonnes = canaux du profil : " + repr(canaux),
      canaux == ["gobo", "color_wheel", "prism", "shutter", "strobe_speed"])
check("le strobe passe par le shutter : colonne Strobe presente et a 92",
      dlg._table.item(0, dlg._col("strobe_speed")).text() == "92")
check("gobo au repos = « · »", dlg._table.item(0, dlg._col("gobo")).text() == "·")

# Clic sur le titre « Pan » puis Suppr : toute la colonne
dlg._table.selectColumn(dlg.C_PAN)
dlg._table.keyPressEvent  # (le filtre est sur le tableau)
app.sendEvent(dlg._table, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
check("Suppr sur la colonne Pan : pan retire des 2, tilt garde",
      all("pan" not in e and e["tilt"] == 33422 for e in etats[:2]))
dlg._table.clearSelection()
dlg._table.selectColumn(dlg.C_TILT)
dlg._table.selectionModel().select(dlg._table.model().index(0, dlg.C_LEVEL),
                                   QItemSelectionModel.Select)
dlg._clear_selected_cells()
check("tilt vide + niveau de la ligne 1 seulement",
      "tilt" not in etats[0] and etats[0]["level"] == 0 and etats[1]["level"] == 100)
check("la ligne reste a sa place (pas de saut)", dlg._table.rowCount() == 2)
dlg._table.item(0, dlg._col("gobo")).setText("40")
check("taper une valeur dans une case vide la pose", etats[0]["gobo"] == 40)
dlg._table.item(0, dlg._col("gobo")).setText("")
check("vider la case remet au repos", etats[0]["gobo"] == 0)
n = len(dlg._undo)
dlg._undo_last(); dlg._undo_last()
check("Annuler defait aussi les saisies", etats[0]["gobo"] == 0 and len(dlg._undo) == n - 2)
check("strobe toujours la", etats[0]["strobe_speed"] == 92)

print("\n4. Ctrl+Z")
from PySide6.QtTest import QTest
dlg.show()
dlg.activateWindow()
app.processEvents()
dlg._strip("strobe_speed")
check("strobe retire", etats[0]["strobe_speed"] == 0)
QTest.keyClick(dlg._table, Qt.Key_Z, Qt.ControlModifier)
app.processEvents()
check("Ctrl+Z le remet", etats[0]["strobe_speed"] == 92)
dlg.close()

print("\nTOUT PASSE" if not ECHECS else "\n%d ECHEC(S)" % len(ECHECS))
sys.exit(1 if ECHECS else 0)
