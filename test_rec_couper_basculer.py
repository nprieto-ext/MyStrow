"""
test_rec_couper_basculer.py — Couper un bloc ici et le basculer d'une ligne.

Depuis que chaque groupe est suivi de ses propres projecteurs, la ligne
« en dessous » d'un groupe est l'un de SES projecteurs. D'ou le geste, au clic
droit sur un bloc de piste couleur (jamais sur Effet / Sequence / Position /
Gobo, qui ont leurs propres menus) :

    ✂️  Couper ici et basculer la suite sur « Face 1 »
    ↓   Basculer sur « Face 1 »
    ↑   Basculer sur « A »

C'est le « scinder et pousser » d'un outil de montage : la tete reste en place,
la queue part sur la ligne d'a cote. Concretement, cela sert a detacher la fin
d'un bloc de groupe pour ne la garder que sur un projecteur.

Trois pieges, et c'est eux qu'on verrouille ici :

  * QUELLE ligne est « en dessous ». Celle qu'on VOIT : les lignes masquees,
    les pistes specialisees et celles qu'un cadenas protege sont sautees. Y
    pousser un bloc echouerait en silence, le menu ne doit proposer que ce qui
    va marcher — et ne rien proposer du tout s'il n'y a pas de voisine.

  * la COPIE. Elle passe par `_clone_clip`, seul cloneur de l'editeur : un bloc
    qui perd son identite en changeant de piste retombe en simple bloc couleur.

  * le CHEVAUCHEMENT sur la cible. Meme resolution qu'un glisser cross-piste
    (`_resolve_overlap`) : le bloc se range dans le trou le plus proche au lieu
    de se superposer en silence a ce qui s'y trouve deja.

    python test_rec_couper_basculer.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

from light_timeline import LightTrack

_app = QApplication.instance() or QApplication(sys.argv)


class FauxWin:
    GROUP_DISPLAY = {"face": "A"}
    projectors = []

    def get_track_to_indices(self):
        return {}


class FauxEditor:
    """Editeur reduit a ce que le geste demande : une liste de pistes."""

    main_window = FauxWin()

    def __init__(self):
        self.tracks = []
        self.etats = 0        # compteur d'appels a save_state
        self.ecritures = 0    # compteur d'appels a _save_sequence_no_close

    def save_state(self):
        self.etats += 1

    def _save_sequence_no_close(self):
        self.ecritures += 1


def _rig():
    """Effet, puis un groupe A suivi de deux de ses projecteurs."""
    ed = FauxEditor()
    eff = LightTrack("Effet", 60000, ed, "#cc44ff")
    eff.is_effect_track = True
    a = LightTrack("A", 60000, ed, "#ff8844")
    p1 = LightTrack("@A1", 60000, ed, "#ff8844")
    p1.is_projector_track = True
    p1.display_label = "Face 1"
    p2 = LightTrack("@A2", 60000, ed, "#ff8844")
    p2.is_projector_track = True
    p2.display_label = "Face 2"
    ed.tracks = [eff, a, p1, p2]
    for t in ed.tracks:
        t.show()
    return ed, a, p1, p2


class LigneVoisine(unittest.TestCase):
    """Ce que le menu proposera — ou ne proposera pas."""

    def setUp(self):
        self.ed, self.a, self.p1, self.p2 = _rig()

    def test_dessous_et_dessus(self):
        self.assertIs(self.a.voisine(1), self.p1)
        self.assertIs(self.p1.voisine(1), self.p2)
        self.assertIs(self.p1.voisine(-1), self.a)

    def test_derniere_ligne(self):
        self.assertIsNone(self.p2.voisine(1))

    def test_piste_specialisee_ignoree(self):
        """Une piste Effet n'est pas une cible, et n'en cherche pas."""
        self.assertIsNone(self.ed.tracks[0].voisine(1))
        self.assertIsNone(self.a.voisine(-1))   # au-dessus de A : Effet

    def test_ligne_masquee_sautee(self):
        self.p1.hide()
        self.assertIs(self.a.voisine(1), self.p2)

    def test_ligne_verrouillee_sautee(self):
        """Y pousser un bloc echouerait : autant viser la suivante."""
        self.p1.set_locked(True)
        self.assertIs(self.a.voisine(1), self.p2)
        self.p1.set_locked(False)
        self.assertIs(self.a.voisine(1), self.p1)


class CouperEtBasculer(unittest.TestCase):

    def setUp(self):
        self.ed, self.a, self.p1, self.p2 = _rig()
        self.clip = self.a.add_clip(2000, 10000, QColor("#ff3322"), 90)

    def test_tete_et_queue(self):
        self.a.cut_and_push(self.clip, 4000, 1)
        self.assertEqual(len(self.a.clips), 1)
        self.assertEqual((self.clip.start_time, self.clip.duration), (2000, 4000))
        self.assertEqual(len(self.p1.clips), 1)
        q = self.p1.clips[0]
        self.assertEqual((q.start_time, q.duration), (6000, 6000))

    def test_la_queue_garde_tout(self):
        """Sans `_clone_clip`, elle retomberait en bloc couleur nu."""
        self.clip.effect_name = "Sinus"
        self.clip.strobe_speed = 7
        self.clip.fade_out_duration = 500
        self.a.cut_and_push(self.clip, 4000, 1)
        q = self.p1.clips[0]
        self.assertEqual(q.color.name(), "#ff3322")
        self.assertEqual(q.intensity, 90)
        self.assertEqual(q.effect_name, "Sinus")
        self.assertEqual(q.strobe_speed, 7)
        self.assertEqual(q.fade_out_duration, 500)

    def test_pas_de_fondu_parasite_au_point_de_coupe(self):
        self.clip.fade_in_duration = 400
        self.clip.fade_out_duration = 500
        self.a.cut_and_push(self.clip, 4000, 1)
        self.assertEqual(self.clip.fade_out_duration, 0)
        self.assertEqual(self.p1.clips[0].fade_in_duration, 0)
        # …mais les fondus « extérieurs » survivent chacun de leur côté.
        self.assertEqual(self.clip.fade_in_duration, 400)
        self.assertEqual(self.p1.clips[0].fade_out_duration, 500)

    def test_coupe_trop_pres_du_bord_refusee(self):
        self.a.cut_and_push(self.clip, 50, 1)
        self.assertEqual(len(self.a.clips), 1)
        self.assertEqual(self.a.clips[0].duration, 10000)
        self.assertEqual(len(self.p1.clips), 0)

    def test_sans_voisine_rien_ne_bouge(self):
        c = self.p2.add_clip(0, 8000, QColor("#00ff00"), 80)
        self.p2.cut_and_push(c, 4000, 1)
        self.assertEqual(len(self.p2.clips), 1)
        self.assertEqual(c.duration, 8000)

    def test_chevauchement_resolu(self):
        """La place est prise : le bloc se range, il n'ecrase pas."""
        self.p1.add_clip(6000, 3000, QColor("#0000ff"), 100)
        self.a.cut_and_push(self.clip, 4000, 1)
        self.assertEqual(len(self.p1.clips), 2)
        bornes = sorted((c.start_time, c.start_time + c.duration)
                        for c in self.p1.clips)
        for i in range(len(bornes) - 1):
            self.assertLessEqual(bornes[i][1], bornes[i + 1][0])

    def test_historique_et_restitution(self):
        """Annulable, et ecrit tout de suite dans seq.sequences."""
        self.a.cut_and_push(self.clip, 4000, 1)
        self.assertEqual(self.ed.etats, 1)
        self.assertEqual(self.ed.ecritures, 1)


class BasculerLeBlocEntier(unittest.TestCase):

    def setUp(self):
        self.ed, self.a, self.p1, self.p2 = _rig()
        self.clip = self.a.add_clip(1000, 3000, QColor("#ff00ff"), 60)

    def test_descend(self):
        self.a.push_clip(self.clip, 1)
        self.assertEqual(len(self.a.clips), 0)
        self.assertEqual(len(self.p1.clips), 1)
        self.assertEqual(self.p1.clips[0].start_time, 1000)

    def test_remonte(self):
        self.a.push_clip(self.clip, 1)
        self.p1.push_clip(self.p1.clips[0], -1)
        self.assertEqual(len(self.a.clips), 1)
        self.assertEqual(len(self.p1.clips), 0)

    def test_sort_de_la_selection(self):
        """Un bloc parti ailleurs ne doit plus figurer dans la selection."""
        self.a.selected_clips = [self.clip]
        self.a.push_clip(self.clip, 1)
        self.assertEqual(self.a.selected_clips, [])

    def test_sans_voisine(self):
        c = self.p2.add_clip(0, 2000, QColor("#00ffff"), 50)
        self.p2.push_clip(c, 1)
        self.assertEqual(len(self.p2.clips), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
