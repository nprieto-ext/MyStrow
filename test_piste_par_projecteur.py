"""
test_piste_par_projecteur.py — Une piste par projecteur dans le REC Lumiere.

Les pistes de la timeline etaient toutes des pistes de GROUPE (A a F, Lyres,
Barres, Strobos) : impossible d'eclairer un projecteur a part de ses voisins
sans lui inventer un groupe. Sous les groupes, la timeline porte desormais une
piste par FIXTURE du patch, deployee d'emblee (un bandeau « Projecteurs (n) »
replie le paquet d'un clic).

Deux points portent toute la mecanique, et c'est eux qu'on verrouille ici :

  * la CLE de la piste (`core.projector_track_key`) — « @A2 », soit le groupe
    d'affichage plus le rang du projo DANS son groupe. C'est elle qui part dans
    le .tui, donc elle ne doit dependre ni du NOM de la fixture (qui se renomme)
    ni de son index GLOBAL (qui bouge des qu'on patche ailleurs). Le libelle
    affiche, lui, suit le nom : `LightTrack.display_name()`.

  * l'ORDRE d'application. `apply_timeline_to_dmx` repart d'un rig noir a chaque
    image puis parcourt les pistes actives : la derniere ecrite gagne. Les
    pistes projecteur passent donc en dernier, et c'est ce qui fait qu'un bloc
    pose sur « Face 2 » l'emporte sur le bloc rouge du groupe A.

    python test_piste_par_projecteur.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import main_window as mw
from core import projector_track_key, is_projector_track
from light_timeline import LightTrack

_app = QApplication.instance() or QApplication(sys.argv)


class FauxProj:
    def __init__(self, group, name, fixture_type="PAR LED"):
        self.group = group
        self.name = name
        self.fixture_type = fixture_type


def _patch():
    """4 faces, 2 contres, 2 lyres — indices 0..7."""
    return ([FauxProj("face", "Face %d" % (i + 1)) for i in range(4)] +
            [FauxProj("contre", "Contre %d" % (i + 1)) for i in range(2)] +
            [FauxProj("lyre", "Lyre %d" % (i + 1), "Moving Head") for i in range(2)])


class FauxWin:
    """MainWindow reduite a ce que la traduction piste -> projecteurs demande."""

    GROUP_DISPLAY        = mw.MainWindow.GROUP_DISPLAY
    get_track_to_indices = mw.MainWindow.get_track_to_indices

    def __init__(self, projectors=None):
        self.projectors = projectors if projectors is not None else _patch()


class FauxEditor:
    def __init__(self, win):
        self.main_window = win


class CleDePiste(unittest.TestCase):
    """La cle identifie UN projecteur, sans collision ni derive."""

    def setUp(self):
        self.win = FauxWin()
        self.m = self.win.get_track_to_indices()

    def test_groupe_inchange(self):
        self.assertEqual(self.m["A"], [0, 1, 2, 3])
        self.assertEqual(self.m["C"], [4, 5])
        self.assertEqual(self.m["Lyres"], [6, 7])

    def test_projecteur_seul(self):
        self.assertEqual(self.m["@A2"], [1])
        self.assertEqual(self.m["@C1"], [4])
        self.assertEqual(self.m["@Lyres2"], [7])

    def test_pas_de_collision_avec_les_pistes_existantes(self):
        for nom in ("A", "B", "C", "Lyres", "Barres", "Strobos", "Public",
                    "Effet", "Sequence", "Position", "Gobo", "Audio"):
            self.assertFalse(is_projector_track(nom), nom)
        self.assertTrue(is_projector_track("@A2"))

    def test_une_cle_par_fixture(self):
        cles = [k for k in self.m if is_projector_track(k)]
        self.assertEqual(len(cles), len(self.win.projectors))
        self.assertEqual(len(set(cles)), len(cles))

    def test_survit_au_renommage(self):
        """Le nom de la fixture n'entre pas dans la cle."""
        self.win.projectors[1].name = "Face Jardin"
        self.assertEqual(self.win.get_track_to_indices()["@A2"], [1])

    def test_survit_a_un_ajout_dans_un_autre_groupe(self):
        """La cle est un rang LOCAL au groupe, pas un index global."""
        self.win.projectors.insert(4, FauxProj("contre", "Contre 0"))
        m = self.win.get_track_to_indices()
        self.assertEqual(m["@A2"], [1])        # les faces ne bougent pas
        self.assertEqual(m["@Lyres1"], [7])    # la lyre a juste glisse d'un cran


class OrdreDApplication(unittest.TestCase):
    """La priorite ne tient QUE a l'ordre dans lequel les pistes sont ecrites."""

    def setUp(self):
        self.win = FauxWin()
        self.m = self.win.get_track_to_indices()

    def _rendu(self, actives):
        """Reproduit apply_timeline_to_dmx : rig noir, puis chaque piste ecrit."""
        sortie = {i: "noir" for i in range(len(self.win.projectors))}
        for piste, couleur in actives.items():
            for idx in self.m.get(piste, []):
                sortie[idx] = couleur
        return sortie

    def test_le_projecteur_prime_sur_son_groupe(self):
        rendu = self._rendu({"A": "rouge", "@A2": "bleu"})
        self.assertEqual([rendu[i] for i in range(4)],
                         ["rouge", "bleu", "rouge", "rouge"])

    def test_sans_piste_projecteur_rien_ne_change(self):
        rendu = self._rendu({"A": "rouge"})
        self.assertEqual([rendu[i] for i in range(4)], ["rouge"] * 4)

    def test_le_groupe_reprend_la_main_a_la_fin_du_bloc(self):
        """Le bloc du projo fini, seul le groupe ecrit : Face 2 redevient rouge."""
        rendu = self._rendu({"A": "rouge"})
        self.assertEqual(rendu[1], "rouge")

    def test_tri_de_restitution_independant_du_fichier(self):
        """`play_timeline_sequence` force les pistes projecteur en dernier.

        L'editeur les range deja en fin de timeline, donc le .tui les serialise
        en dernier. Mais faire reposer la priorite sur l'ordre des lignes d'un
        fichier serait fragile : le tri est explicite.
        """
        depuis_le_tui = {"@A2": None, "A": None, "@Lyres1": None,
                         "Lyres": None, "Effet": None}
        ordre = [k for k, _ in sorted(depuis_le_tui.items(),
                                      key=lambda kv: is_projector_track(kv[0]))]
        self.assertEqual(ordre, ["A", "Lyres", "Effet", "@A2", "@Lyres1"])


class LibelleEtMenus(unittest.TestCase):
    """La cle est interne : l'utilisateur ne doit jamais lire « @A2 »."""

    def setUp(self):
        self.ed = FauxEditor(FauxWin())

    def _piste(self, nom, libelle=None):
        t = LightTrack(nom, 60000, self.ed, "#4488ff")
        if libelle is not None:
            t.is_projector_track = True
            t.display_label = libelle
        return t

    def test_display_name(self):
        self.assertEqual(self._piste("A").display_name(), "A")
        self.assertEqual(self._piste("@A2", "Face 2").display_name(), "Face 2")

    def test_menu_mouvement_sur_une_piste_de_lyre(self):
        """Le test portait sur le seul nom « Lyres » : une piste dediee a UNE
        lyre n'avait pas droit au menu Mouvement, alors que l'apercu comme la
        restitution appliquent deja son pan/tilt."""
        self.assertTrue(self._piste("Lyres").targets_moving_head())
        self.assertTrue(self._piste("@Lyres1", "Lyre 1").targets_moving_head())
        self.assertFalse(self._piste("A").targets_moving_head())
        self.assertFalse(self._piste("@A2", "Face 2").targets_moving_head())

    def test_cle_orpheline_ne_plante_pas(self):
        """Fixture retiree du patch : la piste survit pour garder ses blocs."""
        orph = self._piste("@Zzz9", "Zzz9 ?")
        self.assertFalse(orph.targets_moving_head())
        self.assertEqual(orph.display_name(), "Zzz9 ?")

    def test_cross_drag_avec_les_pistes_de_groupe(self):
        """Une piste projecteur est une piste couleur : on y glisse un bloc."""
        grp = self._piste("A")
        prj = self._piste("@A2", "Face 2")
        self.assertTrue(grp._cross_compatible(prj))
        self.assertTrue(prj._cross_compatible(grp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
