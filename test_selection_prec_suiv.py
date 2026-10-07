# -*- coding: utf-8 -*-
"""Préc. / Tous / Suiv. : parcourir un groupe projecteur par projecteur (05/10/2026)."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from projector import Projector
from plan_de_feu import PlanDeFeu

projs = [Projector("face", f"PAR {i+1}", "PAR LED") for i in range(4)] \
      + [Projector("contre", "Contre 1", "PAR LED")]
for i, p in enumerate(projs):
    p.canvas_x, p.canvas_y = 0.1 + i * 0.15, 0.5
pdf = PlanDeFeu(projs)

# Groupe A sélectionné, cliqué dans le désordre : 3, 1, 4, 2
pdf.selected_lamps = {("face", 2), ("face", 0), ("face", 3), ("face", 1)}
pdf.selected_lamps_ordered = [("face", 2), ("face", 0), ("face", 3), ("face", 1)]
GRP = [("face", 2), ("face", 0), ("face", 3), ("face", 1)]

vus = []
for _ in range(5):
    idx = pdf.step_selection(+1)
    assert len(pdf.selected_lamps) == 1
    vus.append(next(iter(pdf.selected_lamps)))
    assert projs[idx].name == f"PAR {vus[-1][1] + 1}"
assert vus == GRP + [GRP[0]], vus            # ordre de sélection, puis boucle

pdf.step_selection(-1)
assert pdf.selected_lamps == {GRP[3]}         # précédent depuis le 1er = dernier

pdf.step_selection(0)
assert pdf.selected_lamps == set(GRP)          # Tous
assert pdf.selection_ordered() == GRP          # l'ordre est conservé

# Une AUTRE sélection remplace le parcours
pdf.selected_lamps = {("contre", 0), ("face", 1)}
pdf.selected_lamps_ordered = [("contre", 0), ("face", 1)]
pdf.step_selection(+1)
assert pdf.selected_lamps == {("contre", 0)}

# Un seul projecteur : rien à parcourir
pdf.selected_lamps = {("face", 0)}; pdf.selected_lamps_ordered = [("face", 0)]
assert pdf.step_selection(+1) is None

# Flèches au clavier sur le plan principal (non éditable)
pdf.selected_lamps = set(GRP); pdf.selected_lamps_ordered = list(GRP)
pdf._step_pool = None
from PySide6.QtTest import QTest
QTest.keyClick(pdf.canvas, Qt.Key_Right)
assert pdf.selected_lamps == {GRP[0]}, pdf.selected_lamps
QTest.keyClick(pdf.canvas, Qt.Key_Right)
assert pdf.selected_lamps == {GRP[1]}
QTest.keyClick(pdf.canvas, Qt.Key_Up)
assert pdf.selected_lamps == set(GRP)
print("OK - Préc. / Tous / Suiv.")
