"""Le tableau « Plan » de la 3D doit afficher le nom du BON projecteur.

Remontée du 27/08/2026 (capture `Bug_liste3D.png`) : après une modification du
patch, les lignes annonçaient « Lyre TEST 17 » … « Lyre TEST 20 » alors que ces
lignes réglaient des PROJECTEURS. Deux causes cumulées :

  * `_populate_mini` n'écrivait le nom qu'à la CRÉATION de la cellule — une
    ligne réutilisée gardait le nom de son occupant précédent ;
  * `refresh()` ne repeuplait jamais le tableau : il ne l'était qu'à
    l'ouverture de la fenêtre.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

import plan_3d_webwindow as w

_app = QApplication.instance() or QApplication([])


class _Proj:
    def __init__(self, name, group='face', cx=0.5, cy=0.5):
        self.name, self.group = name, group
        self.canvas_x, self.canvas_y = cx, cy


class _Faux(w.Plan3DWebWindow):
    """Instance minimale : on ne veut que le tableau, pas la vue web."""

    def __init__(self):
        self._mini_tbl = QTableWidget()
        self._mini_tbl.setColumnCount(10)
        self._highlighted_row = -1
        self._selected_rows = set()
        self._jog_spins = {}
        self._last_projectors = []
        self._pending = None
        self._ready = False

    # Coupe tout ce qui touche au moteur 3D / aux timers
    def _update_strobe_timer(self, projectors): pass
    def clear_selection(self): self._selected_rows.clear(); self._highlighted_row = -1

    class _T:
        @staticmethod
        def isActive(): return True
    _push_timer = _T()


def _noms(win):
    return [win._mini_tbl.item(r, 0).text()
            for r in range(win._mini_tbl.rowCount())]


def test_suppression_decale_les_noms():
    projs = [_Proj(f"Lyre TEST {i}") for i in range(1, 6)] + \
            [_Proj(f"PROJECTEUR {i}") for i in range(1, 4)]
    win = _Faux()
    win._populate_mini(projs)
    assert _noms(win)[0] == "Lyre TEST 1"

    # L'utilisateur supprime les 5 lyres depuis le patch DMX.
    del projs[:5]
    win.refresh(projs)

    assert _noms(win) == ["PROJECTEUR 1", "PROJECTEUR 2", "PROJECTEUR 3"]


def test_remplacement_a_nombre_egal():
    """Supprimer 2 lyres et patcher 2 projecteurs laisse le compte identique."""
    projs = [_Proj("Lyre TEST 1"), _Proj("Lyre TEST 2")]
    win = _Faux()
    win._populate_mini(projs)

    projs[:] = [_Proj("PROJECTEUR 1"), _Proj("PROJECTEUR 2")]
    win.refresh(projs)

    assert _noms(win) == ["PROJECTEUR 1", "PROJECTEUR 2"]


def test_renommage():
    projs = [_Proj("Lyre TEST 1")]
    win = _Faux()
    win._populate_mini(projs)

    projs[0].name = "Lyre cour"
    win.refresh(projs)

    assert _noms(win) == ["Lyre cour"]


def test_nom_tronque_garde_une_infobulle():
    """4 « PROJECTEUR SIMPLE n » s'affichent tous « PROJECTEUR S »."""
    projs = [_Proj("PROJECTEUR SIMPLE 3")]
    win = _Faux()
    win._populate_mini(projs)
    it = win._mini_tbl.item(0, 0)
    assert it.text() == "PROJECTEUR S"          # tronqué par la largeur de colonne
    assert it.toolTip() == "PROJECTEUR SIMPLE 3"


def test_pas_de_repeuplement_inutile():
    """`refresh()` tourne à 40 Hz : il ne doit rien reconstruire sans changement."""
    projs = [_Proj("Lyre TEST 1"), _Proj("Lyre TEST 2")]
    win = _Faux()
    win._populate_mini(projs)
    appels = []
    win._populate_mini = lambda p: appels.append(p)
    for _ in range(10):
        win.refresh(projs)
    assert appels == []
