"""Piles (totems) sur le plan de feu 2D.

Plusieurs appareils sur le MÊME point du plateau, à des hauteurs différentes :
un pied, un totem, deux ponts superposés. Le plan de feu est vu de dessus,
donc ils se superposent — d'où la pastille qui annonce le compte et donne
accès aux appareils du dessous.

Une pile n'est PAS un objet stocké : c'est une position partagée. Aucun champ
nouveau, donc aucune migration des shows ni du patch.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import plan_de_feu as pdf_mod
from plan_de_feu import FixtureCanvas, _find_free_canvas_pos
from projector import Projector

_app = QApplication.instance() or QApplication([])


def _Proj(name, x, y, h=None, group='face'):
    """Vrai `Projector` : le canvas lit une bonne vingtaine d'attributs pour
    peindre une fixture, un bouchon les laisserait filer."""
    p = Projector(group, name=name)
    p.canvas_x, p.canvas_y = x, y
    p.fixture_height = h
    return p


class _Pdf:
    def __init__(self, projs):
        self.projectors = projs
        self.selected_lamps = set()
        self.selected_lamps_ordered = []
        self._htp_overrides = None
        self.main_window = None
        self._canvas_editable = True
        self.reglages = []          # index des fixtures dont le menu s'est ouvert

    def _show_fixture_context_menu(self, global_pos, idx):
        # Le vrai menu est modal : on note seulement qui il vise.
        self.reglages.append(idx)

    def _show_canvas_context_menu(self, global_pos, local_pos=None):
        pass


def _canvas(projs):
    c = FixtureCanvas(_Pdf(projs))
    c.resize(800, 500)
    return c


def test_pile_detectee_sur_position_partagee():
    projs = [_Proj("Lyre haut", .5, .35, 3.2),
             _Proj("Lyre milieu", .5, .35, 2.1),
             _Proj("PAR bas", .5, .35, 1.0),
             _Proj("Ailleurs", .8, .60, 7.0)]
    c = _canvas(projs)

    assert len(c._stacks()) == 1
    assert c._stack_members(0) == [0, 1, 2]      # du plus haut au plus bas
    assert c._stack_members(3) == []             # seul sur son point


def test_membres_ordonnes_du_haut_vers_le_bas():
    projs = [_Proj("bas", .5, .35, 1.0),
             _Proj("haut", .5, .35, 3.2),
             _Proj("milieu", .5, .35, 2.1)]
    c = _canvas(projs)
    assert [projs[j].name for j in c._stack_members(0)] == ["haut", "milieu", "bas"]


def test_hauteur_absente_compte_comme_au_sol():
    projs = [_Proj("sans hauteur", .5, .35, None),
             _Proj("a 4m", .5, .35, 4.0)]
    c = _canvas(projs)
    assert [projs[j].name for j in c._stack_members(0)] == ["a 4m", "sans hauteur"]


def test_deux_appareils_voisins_ne_font_pas_une_pile():
    """La pile se crée par aimantation, pas par voisinage : 1 cm d'écart sur le
    plan (18 cm en X) doit rester deux appareils distincts."""
    projs = [_Proj("A", .500, .35), _Proj("B", .510, .35)]
    c = _canvas(projs)
    assert c._stacks() == {}


def test_une_seule_icone_et_une_pastille():
    projs = [_Proj("A", .5, .35, 3.0), _Proj("B", .5, .35, 2.0),
             _Proj("C", .5, .35, 1.0), _Proj("Seul", .2, .2, 5.0)]
    c = _canvas(projs)
    c.grab()                                  # force un paintEvent réel

    assert len(c._stack_badges) == 1          # une pastille, pas trois
    rect, membres = c._stack_badges[0]
    assert sorted(membres) == [0, 1, 2]
    assert rect.isValid()


def test_clic_sur_la_pastille_ouvre_la_liste():
    projs = [_Proj("A", .5, .35, 3.0), _Proj("B", .5, .35, 2.0)]
    c = _canvas(projs)
    c.grab()
    rect, _ = c._stack_badges[0]
    assert c._stack_badge_at(rect.center()) is not None
    # Loin de la pastille : rien
    assert c._stack_badge_at(rect.center() + pdf_mod.QPoint(120, 120)) is None


def test_choisir_un_membre_reduit_la_selection():
    projs = [_Proj("A", .5, .35, 3.0), _Proj("B", .5, .35, 2.0),
             _Proj("C", .5, .35, 1.0)]
    c = _canvas(projs)
    c._select_stack(c._stack_members(0))          # tout le totem
    assert len(c.pdf.selected_lamps) == 3
    c._select_stack([1])                          # un seul, via la liste
    assert c.pdf.selected_lamps == {c._local_idx(1)}


def test_anti_chevauchement_ne_disloque_pas_la_pile():
    """Extraire un appareil d'une pile ne doit pas faire exploser les autres."""
    projs = [_Proj("reste 1", .5, .35, 3.0), _Proj("reste 2", .5, .35, 2.0),
             _Proj("extrait", .5, .35, 1.0)]
    c = _canvas(projs)
    avant = [(p.canvas_x, p.canvas_y) for p in projs[:2]]

    projs[2].canvas_x += 0.001                    # tout début du glissement
    c._drag_starts = {2: (.5, .35)}
    c._resolve_overlaps(800, 500, {2})

    assert [(p.canvas_x, p.canvas_y) for p in projs[:2]] == avant


def test_aimantation_cree_la_pile():
    projs = [_Proj("cible", .5, .35, 3.0), _Proj("traine", .5, .35, 1.0)]
    c = _canvas(projs)
    c._drag_starts = {}
    # Lâché à quelques pixels de la cible → aimanté dessus
    tx, ty = c._norm_to_px(.5, .35)
    assert c._stack_snap_target(1, tx + 4, ty + 3) == 0
    # Lâché loin → pas d'aimantation
    assert c._stack_snap_target(1, tx + 90, ty) is None


def test_le_patch_ne_peut_toujours_pas_empiler_tout_seul():
    """L'ajout de fixtures garde son écartement : on empile à la souris, jamais
    par accident en patchant."""
    projs = [_Proj("A", .5, .35)]
    x, y = _find_free_canvas_pos(projs, .5, .35)
    assert (x, y) != (.5, .35)


def test_fixture_jamais_placee_nest_pas_une_pile():
    """Sans position stockée, le canvas place la fixture d'office à partir de la
    composition de son groupe : ce n'est pas un empilement voulu, et la pile se
    déferait au prochain ajout de projecteur."""
    projs = [_Proj("A", None, None), _Proj("B", None, None)]
    for p in projs:
        p.canvas_x = p.canvas_y = None
    c = _canvas(projs)
    assert c._stacks() == {}
    assert c._stack_members(0) == []
    c._drag_starts = {}
    tx, ty = c._norm_to_px(*c._get_norm_pos(0))
    assert c._stack_snap_target(1, tx, ty) is None


def test_menu_liste_chaque_appareil():
    projs = [_Proj("Lyre haut", .5, .35, 3.2), _Proj("Lyre bas", .5, .35, 1.0)]
    projs[0].start_address, projs[1].start_address = 1, 21
    c = _canvas(projs)

    menu = c._build_stack_menu(c._stack_members(0))
    joint = " | ".join(a.text() for a in menu.actions() if not a.isSeparator())

    assert "Lyre haut" in joint and "Lyre bas" in joint
    assert "3.20 m" in joint and "1.00 m" in joint      # hauteur, pour les distinguer
    assert "CH 1" in joint and "CH 21" in joint


def test_menu_permet_de_reprendre_tout_le_totem():
    projs = [_Proj("A", .5, .35, 3.0), _Proj("B", .5, .35, 2.0),
             _Proj("C", .5, .35, 1.0)]
    c = _canvas(projs)
    c._select_stack([1])                                # un seul membre
    menu = c._build_stack_menu(c._stack_members(0))

    # 1re action utile = « Selectionner tout » : elle rend la pile entiere
    [a for a in menu.actions() if a.isEnabled() and not a.isSeparator()][0].trigger()
    assert len(c.pdf.selected_lamps) == 3


def test_extraire_un_membre_deplace_le_BON_appareil():
    """Après avoir choisi un appareil dans la liste, le glisser ne doit sortir
    que lui — et pas celui qui porte l'icône."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QPointF

    projs = [_Proj("porte l'icone", .5, .35, 3.0),
             _Proj("choisi", .5, .35, 2.0),
             _Proj("reste", .5, .35, 1.0)]
    c = _canvas(projs)
    c.grab()
    c._select_stack([1])                          # choisi via la liste

    px, py = c._norm_to_px(.5, .35)
    ev = QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(px, py),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    c.mousePressEvent(ev)

    assert c._drag_index == 1, "le meneur du glisser doit etre l'appareil choisi"
    assert set(c._drag_starts) == {1}


# ── Le geste complet : glisser un appareil sur un autre ──────────────────────

def _glisser(c, idx, vers_px, pas=25):
    """Rejoue un vrai glisser souris de `idx` jusqu'à `vers_px`, par petits pas.

    ⚠️ Beaucoup de pas, et c'est essentiel : une souris réelle produit une nuée
    de petits déplacements. En sautant de loin à la cible en 6 pas, le test
    atterrissait d'un coup dans le rayon d'aimantation et ne traversait jamais
    la zone où l'anti-chevauchement repousse la cible — il validait donc un
    geste que l'utilisateur, lui, n'arrivait pas à faire.
    """
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QMouseEvent

    dx0, dy0 = c._norm_to_px(*c._get_norm_pos(idx))
    depart = QPointF(dx0, dy0)
    c.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, depart,
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    for k in range(1, pas + 1):
        t = k / pas
        p = QPointF(depart.x() + (vers_px[0] - depart.x()) * t,
                    depart.y() + (vers_px[1] - depart.y()) * t)
        c.mouseMoveEvent(QMouseEvent(QMouseEvent.MouseMove, p,
                                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    c.mouseReleaseEvent(QMouseEvent(QMouseEvent.MouseButtonRelease, QPointF(*vers_px),
                                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def test_glisser_un_appareil_sur_un_autre_les_empile():
    """LE geste : c'est le seul moyen de composer un totem à la souris."""
    projs = [_Proj("cible", .40, .40, 3.0), _Proj("traine", .70, .70, 1.0)]
    c = _canvas(projs)
    c.grab()
    assert c._stacks() == {}

    _glisser(c, 1, c._norm_to_px(.40, .40))

    assert c._stack_members(0) == [0, 1], "les deux doivent former une pile"
    assert (projs[1].canvas_x, projs[1].canvas_y) == (projs[0].canvas_x, projs[0].canvas_y)


def test_la_cible_ne_recule_pas_quand_on_approche():
    """L'anti-chevauchement repoussait la cible à 32 px alors que l'aimantation
    n'opère qu'à 13 : elle fuyait toujours avant d'être atteinte."""
    # Approche EN DIAGONALE : arriver par un axe aligné déclenche les Smart
    # Guides, qui désactivent l'anti-chevauchement et masquent le problème.
    projs = [_Proj("cible", .40, .40, 3.0), _Proj("traine", .70, .70, 1.0)]
    c = _canvas(projs)
    c.grab()
    pos_cible = (projs[0].canvas_x, projs[0].canvas_y)

    _glisser(c, 1, c._norm_to_px(.40, .40))

    assert (projs[0].canvas_x, projs[0].canvas_y) == pos_cible, "la cible a bougé"
    assert len(c._stack_members(0)) == 2


def test_deposer_a_cote_nempile_pas():
    projs = [_Proj("cible", .40, .40, 3.0), _Proj("traine", .70, .70, 1.0)]
    c = _canvas(projs)
    c.grab()
    tx, ty = c._norm_to_px(.40, .40)

    _glisser(c, 1, (tx + 70, ty + 70))

    assert c._stacks() == {}


def test_glisser_une_pile_entiere_la_deplace_sans_la_defaire():
    projs = [_Proj("A", .40, .40, 3.0), _Proj("B", .40, .40, 2.0),
             _Proj("C", .40, .40, 1.0)]
    c = _canvas(projs)
    c.grab()

    _glisser(c, 0, c._norm_to_px(.70, .60))

    membres = c._stack_members(0)
    assert len(membres) == 3, "la pile s'est disloquée"
    pos = {(projs[j].canvas_x, projs[j].canvas_y) for j in membres}
    assert len(pos) == 1, "les membres ont divergé"
    assert abs(projs[0].canvas_x - .70) < .02 and abs(projs[0].canvas_y - .60) < .02


# ── Défaire une pile ─────────────────────────────────────────────────────────

def test_sortir_de_la_pile_par_le_menu():
    projs = [_Proj("A", .40, .40, 3.0), _Proj("B", .40, .40, 2.0),
             _Proj("C", .40, .40, 1.0)]
    c = _canvas(projs)
    c.grab()

    c._unstack(1)

    assert c._stack_members(0) == [0, 2], "B doit avoir quitté la pile"
    assert (projs[1].canvas_x, projs[1].canvas_y) != (projs[0].canvas_x, projs[0].canvas_y)
    # Posé À CÔTÉ, pas à l'autre bout du plan : on doit voir qu'il en est sorti.
    d = ((projs[1].canvas_x - .40) ** 2 + (projs[1].canvas_y - .40) ** 2) ** .5
    assert 0.02 < d < 0.20, f"écart inattendu : {d:.3f}"
    assert c.pdf.selected_lamps == {c._local_idx(1)}


def test_sortir_le_dernier_dissout_la_pile():
    projs = [_Proj("A", .40, .40, 3.0), _Proj("B", .40, .40, 2.0)]
    c = _canvas(projs)
    c.grab()

    c._unstack(1)

    assert c._stacks() == {}, "à deux, en sortir un ne laisse plus de pile"


def test_menu_propose_de_sortir_chaque_appareil():
    projs = [_Proj("Lyre haut", .5, .35, 3.2), _Proj("Lyre bas", .5, .35, 1.0)]
    c = _canvas(projs)
    menu = c._build_stack_menu(c._stack_members(0))

    sous = [a.menu() for a in menu.actions() if a.menu() is not None]
    assert len(sous) == 1, "un sous-menu « Sortir de la pile »"
    assert [a.text() for a in sous[0].actions()] == ["Lyre haut", "Lyre bas"]


def test_sortir_au_glisser_marche_aussi():
    """Le geste : on choisit l'appareil dans la liste, puis on le tire à l'écart."""
    projs = [_Proj("A", .40, .40, 3.0), _Proj("B", .40, .40, 2.0),
             _Proj("C", .40, .40, 1.0)]
    c = _canvas(projs)
    c.grab()
    c._select_stack([1])                       # choisi dans la liste

    _glisser(c, 1, c._norm_to_px(.70, .65))

    assert c._stack_members(0) == [0, 2]
    assert abs(projs[1].canvas_x - .70) < .02 and abs(projs[1].canvas_y - .65) < .02


def test_un_petit_glisser_ne_sort_pas_de_la_pile():
    """Zone morte : un tremblement de souris ne doit pas défaire un totem."""
    projs = [_Proj("A", .40, .40, 3.0), _Proj("B", .40, .40, 2.0)]
    c = _canvas(projs)
    c.grab()
    c._select_stack([1])
    px, py = c._norm_to_px(.40, .40)

    _glisser(c, 1, (px + 5, py + 4))

    assert c._stack_members(0) == [0, 1], "la pile a été défaite par un micro-mouvement"


# ── Clic droit : la liste d'abord, les réglages ensuite ──────────────────────

def _clic_droit(c, px, py):
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QMouseEvent
    c.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(px, py),
                                  Qt.RightButton, Qt.RightButton, Qt.NoModifier))


def test_clic_droit_sur_un_totem_passe_par_la_liste():
    """Sans ça, le clic droit tombait droit sur le gros menu de réglages de
    l'appareil qui porte le dessin : les autres n'étaient pas réglables."""
    projs = [_Proj("haut", .5, .35, 3.0), _Proj("bas", .5, .35, 1.0)]
    c = _canvas(projs)
    c.grab()
    vus = []
    c._show_stack_menu = lambda gp, membres, edit=False: vus.append((membres, edit))

    _clic_droit(c, *c._norm_to_px(.5, .35))

    assert vus == [([0, 1], True)]
    assert c.pdf.reglages == [], "le menu de réglages ne doit pas s'ouvrir tout seul"


def test_clic_droit_hors_pile_ouvre_directement_les_reglages():
    projs = [_Proj("seul", .5, .35, 3.0), _Proj("ailleurs", .8, .6, 2.0)]
    c = _canvas(projs)
    c.grab()
    c._show_stack_menu = lambda *a, **k: (_ for _ in ()).throw(AssertionError("pas une pile"))

    _clic_droit(c, *c._norm_to_px(.5, .35))

    assert c.pdf.reglages == [0]


def test_clic_droit_sur_une_selection_plus_large_garde_le_menu_de_groupe():
    """Rectangle de sélection sur le totem ET d'autres projecteurs : le clic
    droit vise ce lot — interposer la liste le réduirait au seul totem."""
    projs = [_Proj("haut", .5, .35, 3.0), _Proj("bas", .5, .35, 1.0),
             _Proj("ailleurs", .8, .6, 2.0)]
    c = _canvas(projs)
    c.grab()
    c._select_stack([0, 1, 2])
    c._show_stack_menu = lambda *a, **k: (_ for _ in ()).throw(AssertionError("liste interposée"))

    _clic_droit(c, *c._norm_to_px(.5, .35))

    assert c.pdf.reglages == [0]
    assert len(c.pdf.selected_lamps) == 3, "le clic droit ne doit pas casser la sélection"


def test_choisir_un_appareil_au_clic_droit_ouvre_SES_reglages():
    from PySide6.QtCore import QPoint
    projs = [_Proj("haut", .5, .35, 3.0), _Proj("milieu", .5, .35, 2.0),
             _Proj("bas", .5, .35, 1.0)]
    c = _canvas(projs)

    menu = c._build_stack_menu(c._stack_members(0), edit_pos=QPoint(10, 10))
    utiles = [a for a in menu.actions()
              if a.isEnabled() and not a.isSeparator() and a.menu() is None]
    utiles[2].trigger()                      # 0 = tout le totem, puis les membres
    _app.processEvents()                     # le menu de réglages est différé

    assert c.pdf.selected_lamps == {c._local_idx(1)}, "sélection réduite au choisi"
    assert c.pdf.reglages == [1], "les réglages doivent viser l'appareil choisi"


def test_tout_le_totem_au_clic_droit_regle_l_ensemble():
    from PySide6.QtCore import QPoint
    projs = [_Proj("A", .5, .35, 3.0), _Proj("B", .5, .35, 2.0),
             _Proj("C", .5, .35, 1.0)]
    c = _canvas(projs)

    menu = c._build_stack_menu(c._stack_members(0), edit_pos=QPoint(10, 10))
    utiles = [a for a in menu.actions()
              if a.isEnabled() and not a.isSeparator() and a.menu() is None]
    utiles[0].trigger()
    _app.processEvents()

    assert len(c.pdf.selected_lamps) == 3
    assert c.pdf.reglages == [0], "le menu vise l'appareil qui porte le dessin"


def test_clic_gauche_sur_la_pastille_selectionne_sans_ouvrir_les_reglages():
    """Le clic gauche garde son rôle : choisir, point."""
    from PySide6.QtCore import QPoint
    projs = [_Proj("A", .5, .35, 3.0), _Proj("B", .5, .35, 2.0)]
    c = _canvas(projs)

    menu = c._build_stack_menu(c._stack_members(0))
    utiles = [a for a in menu.actions()
              if a.isEnabled() and not a.isSeparator() and a.menu() is None]
    utiles[1].trigger()
    _app.processEvents()

    assert c.pdf.selected_lamps == {c._local_idx(0)}
    assert c.pdf.reglages == []


# ── Regression 3.1.89 : plantage au tout premier lancement ───────────────────

def _peindre(c):
    """Force un vrai `paintEvent` hors ecran et rend ce que la console a craché."""
    from PySide6.QtGui import QPixmap
    px = QPixmap(c.size())
    c.render(px)
    _app.processEvents()


def test_fixture_jamais_placee_ne_casse_pas_le_dessin():
    """Une fixture sortie de `Projector()` n'a AUCUNE position : c'est le cas
    de toutes les fixtures par defaut, au premier lancement, tant qu'aucun
    `.maestro_dmx_patch.json` n'existe. En 3.1.89 `_stacks` lisait `canvas_x`
    en direct : AttributeError a chaque repaint, puis segfault."""
    p = Projector('face', name='Face 1')          # brut, comme _load_default_fixtures
    assert p.canvas_x is None and p.canvas_y is None
    c = _canvas([p, _Proj("place", .5, .35)])
    assert c._stacks() == {}
    assert c._stack_members(0) == []
    _peindre(c)                                    # ne doit rien lever


def test_une_erreur_de_dessin_ne_tue_pas_le_widget():
    """Le garde-fou : meme si `_paint` explose, le QPainter est ferme et le
    repaint suivant repart proprement. Sans le `finally`, le painter reste
    actif sur le backing store et Qt finit par tomber."""
    c = _canvas([_Proj("A", .5, .35)])
    boom = {'n': 0}

    def _explose(painter, event):
        boom['n'] += 1
        raise RuntimeError("panne simulee")

    c._paint = _explose
    _peindre(c)
    _peindre(c)
    assert boom['n'] == 2, "le widget doit continuer a recevoir des repaints"

    del c._paint                                   # le vrai dessin revient
    _peindre(c)
