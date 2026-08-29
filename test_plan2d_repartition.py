"""Répartition « de … à … » portée sur le plan de feu 2D (Patch DMX).

Demande du 28/08/2026 : la bande « Répartir X/Z de -5 m à 5 m » du tableau de
la fenêtre 3D doit aussi exister sur l'onglet « Plan de feu », réduite à ses
deux axes visibles — X (jardin/cour) et Y (avant/fond de scène).

⚠️ Le plan 2D ne couvre que 18 m en X et 10 m en Y. Au-delà la position n'est
plus représentable : les bornes de la barre sont limitées à l'emprise de l'axe
CHOISI, sinon l'appareil s'écraserait en silence sur le bord.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from plan_3d_webwindow import _pos3d_from_canvas, repartir_canvas
from projector import Projector


def _proj(nom, cx=0.5, cy=0.5):
    p = Projector('face', name=nom)
    p.canvas_x, p.canvas_y = cx, cy
    return p


def _x_m(p):
    """Position X du plateau, en mètres, telle que la 3D la relira."""
    return _pos3d_from_canvas(p.canvas_x, p.canvas_y)[0]


def _y_m(p):
    return _pos3d_from_canvas(p.canvas_x, p.canvas_y)[1]


def test_repartition_reguliere_sur_x():
    projs = [_proj(f"P{i}") for i in range(5)]
    repartir_canvas(projs, True, -4.0, 4.0)
    assert [_x_m(p) for p in projs] == [-4.0, -2.0, 0.0, 2.0, 4.0]


def test_les_bornes_sont_exactes():
    projs = [_proj(f"P{i}") for i in range(3)]
    repartir_canvas(projs, True, -2.5, 7.5)
    assert _x_m(projs[0]) == -2.5 and _x_m(projs[-1]) == 7.5


def test_repartition_sur_y():
    projs = [_proj(f"P{i}") for i in range(3)]
    repartir_canvas(projs, False, -4.0, 4.0)
    assert [_y_m(p) for p in projs] == [-4.0, 0.0, 4.0]


def test_laxe_non_choisi_ne_bouge_pas():
    """Répartir sur X ne doit toucher que X — c'est la promesse du sélecteur."""
    projs = [_proj(f"P{i}", cy=0.3 + 0.1 * i) for i in range(3)]
    avant = [p.canvas_y for p in projs]
    repartir_canvas(projs, True, -4.0, 4.0)
    assert [p.canvas_y for p in projs] == avant


def test_un_seul_appareil_ne_repartit_rien():
    p = _proj("P0", cx=0.2)
    repartir_canvas([p], True, -9.0, 9.0)
    assert p.canvas_x == 0.2


def test_les_bornes_de_lemprise_touchent_les_bords():
    """±9 m en X, ±5 m en Y : exactement le plan, ni raboté ni débordant."""
    projs = [_proj(f"P{i}") for i in range(2)]
    repartir_canvas(projs, True, -9.0, 9.0)
    assert [p.canvas_x for p in projs] == [1.0, 0.0]

    projs = [_proj(f"P{i}") for i in range(2)]
    repartir_canvas(projs, False, -5.0, 5.0)
    assert [p.canvas_y for p in projs] == [1.0, 0.0]


def test_le_signe_suit_le_tableau_3d():
    """X positif = même côté qu'en 3D, sinon le plan et le tableau se lisent
    en miroir (la bévue du 10/08/2026)."""
    projs = [_proj("A"), _proj("B")]
    repartir_canvas(projs, True, 3.0, -3.0)
    assert _x_m(projs[0]) == 3.0 and _x_m(projs[1]) == -3.0
