"""Tableau « Plan » de la fenêtre 3D : sélection par plage et répartition.

Deux demandes du 27/08/2026 :
  * cliquer une ligne, puis Maj+clic plus bas, doit retenir toute la plage ;
  * répartir régulièrement les appareils entre deux valeurs sur un axe — le
    « -15 thru 15 » des pupitres.

⚠️ La répartition met en jeu la limite de l'emprise du plan 2D : celui-ci ne
couvre que ±9 m en X et ±5 m en Z, et la position rabotée repartait vers la 3D
au tick suivant. Une répartition « de -15 à 15 » s'écrasait sur les bords.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidget, QVBoxLayout, QWidget

import plan_3d_webwindow as w
from plan_3d_webwindow import _pos3d_from_canvas, _sync_pos3d_with_canvas
from projector import Projector

_app = QApplication.instance() or QApplication([])


def _proj(nom, x=0.0, z=0.0, h=7.0):
    p = Projector('face', name=nom)
    p.canvas_x, p.canvas_y = 0.5, 0.5
    p.pos_3d_x, p.pos_3d_z = x, z
    p._pos3d_src = (0.5, 0.5)
    p.fixture_height = h
    return p


class _OngletsBidon:
    """`_on_projo_selected` ramène le panneau sur l'onglet Plan."""
    def setCurrentIndex(self, i): pass


class _Faux(w.Plan3DWebWindow):
    """Le tableau et la barre de répartition, sans la vue web ni les timers."""

    def __init__(self, projs):
        self._mini_tbl = QTableWidget()
        self._mini_tbl.setColumnCount(10)
        self._highlighted_row = -1
        self._selected_rows = set()
        self._jog_spins = {}
        self._undo_stack = []
        self._last_projectors = projs
        self._pending = None
        self._ready = False
        self._parent_mw = None
        self._lbl_multi = None
        self._right_tabs = _OngletsBidon()
        self._rep_bar = self._build_repartir_bar()
        self._populate_mini(projs)

    def _update_strobe_timer(self, projectors): pass
    def _push_selection_3d(self): pass
    def _update_jog_pad_from_primary(self): pass
    def _maj_bandeau_multi(self): self._maj_repartir()
    def _save_patch(self): pass
    def refresh(self, projectors): self._last_projectors = projectors

    class _T:
        @staticmethod
        def isActive(): return True
    _push_timer = _T()


# ── Sélection par plage ──────────────────────────────────────────────────────

def test_maj_clic_retient_toute_la_plage():
    win = _Faux([_proj(f"P{i}") for i in range(8)])
    win._on_projo_selected(1)
    win._select_range(win._highlighted_row, 6)
    assert win._selected_rows == {1, 2, 3, 4, 5, 6}


def test_lancre_ne_bouge_pas():
    """Maj+clics successifs doivent élargir ou réduire depuis le MÊME point."""
    win = _Faux([_proj(f"P{i}") for i in range(8)])
    win._on_projo_selected(2)
    win._select_range(win._highlighted_row, 6)
    win._select_range(win._highlighted_row, 4)      # on réduit
    assert win._selected_rows == {2, 3, 4}
    assert win._highlighted_row == 2


def test_maj_clic_vers_le_haut():
    win = _Faux([_proj(f"P{i}") for i in range(8)])
    win._on_projo_selected(5)
    win._select_range(win._highlighted_row, 1)
    assert win._selected_rows == {1, 2, 3, 4, 5}


def test_ctrl_maj_ajoute_au_lieu_de_remplacer():
    win = _Faux([_proj(f"P{i}") for i in range(10)])
    win._on_projo_selected(0)
    win._select_range(0, 2)
    win._select_range(6, 8, ajouter=True)
    assert win._selected_rows == {0, 1, 2, 6, 7, 8}


# ── Répartition ──────────────────────────────────────────────────────────────

def _repartir(win, rows, axe, de_cm, a_cm):
    win._selected_rows = set(rows)
    win._rep_axe.setCurrentIndex(axe)
    win._rep_de.setValue(de_cm)
    win._rep_a.setValue(a_cm)
    win._repartir()


def test_repartition_reguliere_sur_x():
    projs = [_proj(f"P{i}") for i in range(5)]
    win = _Faux(projs)
    _repartir(win, range(5), 0, -400, 400)
    assert [p.pos_3d_x for p in projs] == [-4.0, -2.0, 0.0, 2.0, 4.0]


def test_les_bornes_sont_exactes():
    projs = [_proj(f"P{i}") for i in range(3)]
    win = _Faux(projs)
    _repartir(win, range(3), 0, -250, 750)
    assert projs[0].pos_3d_x == -2.5 and projs[-1].pos_3d_x == 7.5


def test_repartition_hors_emprise_du_plan_2d():
    """« -15 thru 15 » : au-delà de ±9 m, le plan 2D ne sait plus représenter la
    position. Elle doit être CONSERVÉE, pas rabotée."""
    projs = [_proj(f"P{i}") for i in range(3)]
    win = _Faux(projs)
    _repartir(win, range(3), 0, -1500, 1500)

    assert [p.pos_3d_x for p in projs] == [-15.0, 0.0, 15.0]
    # Et le tick suivant ne doit pas les ramener dans l'emprise
    for p in projs:
        _sync_pos3d_with_canvas(p, p.canvas_x, p.canvas_y)
    assert [p.pos_3d_x for p in projs] == [-15.0, 0.0, 15.0]


def test_une_position_dans_lemprise_reste_liee_au_plan_2d():
    """Le découplage ne doit frapper QUE ce qui sort du plan."""
    projs = [_proj(f"P{i}") for i in range(3)]
    win = _Faux(projs)
    _repartir(win, range(3), 0, -400, 400)

    for p in projs:
        assert p._pos3d_src is not None, "position encore representable en 2D"
    # Déplacer sur le plan 2D doit toujours piloter la 3D
    projs[0].canvas_x, projs[0].canvas_y = 0.2, 0.7
    _sync_pos3d_with_canvas(projs[0], 0.2, 0.7)
    assert (projs[0].pos_3d_x, projs[0].pos_3d_z) == _pos3d_from_canvas(0.2, 0.7)


def test_repartition_sur_la_hauteur_bornee():
    projs = [_proj(f"P{i}") for i in range(3)]
    win = _Faux(projs)
    _repartir(win, range(3), 2, 100, 1500)
    assert [p.fixture_height for p in projs] == [1.0, 8.0, 15.0]


def test_repartition_annulable():
    projs = [_proj(f"P{i}", x=float(i)) for i in range(4)]
    win = _Faux(projs)
    _repartir(win, range(4), 0, -900, 900)
    assert projs[0].pos_3d_x == -9.0

    win._undo()
    assert [p.pos_3d_x for p in projs] == [0.0, 1.0, 2.0, 3.0]


def test_un_seul_appareil_ne_repartit_rien():
    projs = [_proj("P0", x=1.0)]
    win = _Faux(projs)
    _repartir(win, [0], 0, -900, 900)
    assert projs[0].pos_3d_x == 1.0


def test_la_barre_napparait_qua_partir_de_deux():
    win = _Faux([_proj(f"P{i}") for i in range(4)])
    win._on_projo_selected(0)
    assert not win._rep_bar.isVisible()
    win._select_range(0, 2)
    assert win._rep_bar.isVisible()


# ── Encombrement ─────────────────────────────────────────────────────────────
# Le panneau de droite s'ouvre à 240 px (`_splitter.setSizes([850, 240])`). En
# un seul rang la bande en réclamait plus de 300 : le bouton, seul élément
# élastique, encaissait tout le manque et sortait rogné — remontée du
# 28/08/2026. C'est la partie qu'on ne peut PAS deviner, contrairement aux
# bornes qui portent leur chiffre.

_PANNEAU = 240


def test_la_bande_tient_dans_le_panneau():
    win = _Faux([_proj(f"P{i}") for i in range(3)])
    assert win._rep_bar.minimumSizeHint().width() <= _PANNEAU


def test_le_bouton_nest_pas_rogne():
    win = _Faux([_proj(f"P{i}") for i in range(3)])
    win._rep_bar.setVisible(True)
    hote = QWidget()
    lay = QVBoxLayout(hote)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(win._rep_bar)
    hote.resize(_PANNEAU, 200)
    hote.layout().activate()
    assert win._rep_btn.width() >= win._rep_btn.sizeHint().width()


def test_les_bornes_sont_a_laplomb_des_colonnes():
    """Les cellules gardent la largeur des colonnes X / Z / H du tableau.

    Elle était lue sur le tableau DÉJÀ construit : la bande dépendait alors de
    l'ordre des appels, et prenait 100 px — la largeur par défaut — partout où
    les colonnes n'avaient pas encore été dimensionnées.
    """
    win = _Faux([_proj(f"P{i}") for i in range(3)])
    attendu = w.Plan3DWebWindow._MINI_CW[1] - 4
    assert win._rep_de.width() == attendu
    assert win._rep_a.width() == attendu
