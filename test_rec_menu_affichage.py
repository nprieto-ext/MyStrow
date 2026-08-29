"""
test_rec_menu_affichage.py — Menu Affichage et en-tete de piste du REC Lumiere.

L'en-tete de piste etait un pave : un QLabel encadre de 104 px, un bouton de
repli, parfois un « × ». Trois widgets enfants par piste, a replacer a la main
a chaque defilement horizontal — et sur un rig de 50 fixtures, cela faisait
~180 widgets pour afficher trois choses. Il est desormais PEINT dans
`paintEvent`, sur le modele d'un en-tete de piste de montage :

    [ cadenas ]  Nom de la piste

Trois choses tiennent a cet en-tete, et c'est elles qu'on verrouille ici :

  * la GEOMETRIE. Le clic tape dans le meme rectangle que le rendu
    (`_header_rects`), a n'importe quelle densite de lignes — sinon on
    verrouillerait une piste en croyant viser a cote.

  * le CADENAS. Une piste verrouillee refuse tout ce qui modifie ses blocs,
    y compris les chemins qui ne passent pas par la souris (coller, supprimer
    la selection, dupliquer, generer). Mais elle continue de JOUER : c'est une
    protection d'edition, pas un mute.

  * le MASQUAGE d'une ligne, passe au menu Affichage (il n'y a plus d'oeil par
    piste). Du rangement d'ecran : les blocs restent, la sauvegarde les
    emporte, le show ne bouge pas d'un canal.

La densite des lignes (100 / 75 / 50 / 25 %) multiplie ligne, bloc et textes ;
la geometrie verticale d'un bloc etait recopiee en dur a quatre endroits et
passe maintenant par clip_top() / clip_h() / clip_bottom().

    python test_rec_menu_affichage.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

from light_timeline import LightTrack

_app = QApplication.instance() or QApplication(sys.argv)


class FauxProj:
    def __init__(self, group, name, fixture_type="PAR LED"):
        self.group = group
        self.name = name
        self.fixture_type = fixture_type


class FauxWin:
    GROUP_DISPLAY = {"face": "A", "lyre": "Lyres"}
    projectors = [FauxProj("face", "Face 1")]

    def get_track_to_indices(self):
        return {"A": [0]}


class FauxEditor:
    main_window = FauxWin()


def _piste(nom="A", base=60):
    t = LightTrack(nom, 60000, FauxEditor(), "#4488ff")
    t.set_base_height(base)
    return t


class HauteurDesLignes(unittest.TestCase):
    """Ligne, bloc et textes suivent la meme echelle."""

    def setUp(self):
        self.t = _piste()

    def test_echelle_1(self):
        self.t.apply_height_scale(1.0)
        self.assertEqual(self.t.minimumHeight(), 60)
        self.assertEqual((self.t.clip_top(), self.t.clip_h()), (10, 40))

    def test_defaut_75(self):
        """Nouvelle valeur par defaut : l'en-tete tient sur une ligne."""
        self.t.apply_height_scale(0.75)
        self.assertEqual(self.t.minimumHeight(), 45)
        self.assertEqual(self.t.clip_h(), 30)

    def test_moitie(self):
        self.t.apply_height_scale(0.5)
        self.assertEqual(self.t.minimumHeight(), 30)
        self.assertEqual((self.t.clip_top(), self.t.clip_h()), (5, 20))

    def test_quart(self):
        self.t.apply_height_scale(0.25)
        self.assertEqual(self.t.minimumHeight(), 15)
        self.assertEqual((self.t.clip_top(), self.t.clip_h()), (2, 10))

    def test_piste_specialisee_suit(self):
        """Les pistes Effet/Sequence/Position/Gobo/Projecteur partent de 50 px."""
        sp = _piste("Séquence", base=50)
        sp.apply_height_scale(0.5)
        self.assertEqual(sp.minimumHeight(), 25)

    def test_hauteur_figee_des_deux_cotes(self):
        """min == max : sinon la ligne se re-etirerait au premier recalcul."""
        self.t.apply_height_scale(0.5)
        self.assertEqual(self.t.minimumHeight(), self.t.maximumHeight())

    def test_bornes(self):
        """Une echelle absurde ne doit pas produire une ligne de 0 px."""
        self.t.apply_height_scale(0.01)
        self.assertGreaterEqual(self.t.clip_h(), LightTrack._CLIP_H_MIN)
        self.t.apply_height_scale(5.0)
        self.assertEqual(self.t.minimumHeight(), 60)


class PariteDessinSurvol(unittest.TestCase):
    """Ce qui est dessine est ce qu'on peut attraper — a toute densite."""

    def setUp(self):
        self.t = _piste()
        self.clip = self.t.add_clip(1000, 4000, QColor("#0000ff"), 100)

    def _x(self):
        return 145 + int(1000 * self.t.pixels_per_ms) + 5

    def test_toutes_les_densites(self):
        for scale in (1.0, 0.75, 0.5, 0.25):
            with self.subTest(scale=scale):
                self.t.apply_height_scale(scale)
                x = self._x()
                milieu = self.t.clip_top() + self.t.clip_h() // 2
                touche = self.t.get_clip_at_pos(x, milieu)
                self.assertIsNotNone(touche)
                self.assertIs(touche[0], self.clip)
                self.assertIsNone(self.t.get_clip_at_pos(x, self.t.clip_top() - 1))
                self.assertIsNone(self.t.get_clip_at_pos(x, self.t.clip_bottom() + 1))

    def test_marqueur_xfade_sur_la_moitie_basse(self):
        """Le fondu enchaine occupe la moitie BASSE du bloc, a toute echelle."""
        suite = self.t.add_clip(5000, 4000, QColor("#00ff00"), 100)
        suite.xfade = 600
        for scale in (1.0, 0.5, 0.25):
            with self.subTest(scale=scale):
                self.t.apply_height_scale(scale)
                jx = 145 + int(5000 * self.t.pixels_per_ms)
                self.assertIs(self.t._xfade_marker_at(jx, self.t.clip_bottom() - 1), suite)
                self.assertIsNone(self.t._xfade_marker_at(jx, self.t.clip_top() + 1))


class EnTeteDePiste(unittest.TestCase):
    """Cadenas : peint et clique aux memes coordonnees."""

    def setUp(self):
        self.t = _piste()
        self.t.resize(800, self.t.minimumHeight())

    def test_les_icones_restent_dans_la_colonne(self):
        for scale in (1.0, 0.75, 0.5):
            with self.subTest(scale=scale):
                self.t.apply_height_scale(scale)
                self.t.resize(800, self.t.minimumHeight())
                r = self.t._header_rects(0)
                self.assertGreaterEqual(r['lock'].left(), 5)   # après l'accent
                self.assertLess(r['lock'].right(), LightTrack.HEADER_W)

    def test_survol_des_icones(self):
        for scale in (1.0, 0.75, 0.5):
            with self.subTest(scale=scale):
                self.t.apply_height_scale(scale)
                self.t.resize(800, self.t.minimumHeight())
                r = self.t._header_rects(0)
                self.assertEqual(
                    self.t.header_hit(r['lock'].center().x(), r['lock'].center().y()),
                    'lock')

    def test_hors_de_la_colonne_rien(self):
        self.assertIsNone(self.t.header_hit(400, 20))

    def test_ligne_trop_basse_pas_d_icone(self):
        """A 25 %, les pictogrammes deviendraient des taches : plus de cible."""
        self.t.apply_height_scale(0.25)
        self.t.resize(800, self.t.minimumHeight())
        r = self.t._header_rects(0)
        self.assertIsNone(self.t.header_hit(r['lock'].center().x(),
                                            r['lock'].center().y()))

    def test_audio_sans_cadenas(self):
        """L'Audio ne porte aucun bloc : un cadenas n'aurait rien a proteger."""
        wf = _piste("Audio", base=100)
        wf.lockable = False
        wf.resize(800, wf.minimumHeight())
        r = wf._header_rects(0)
        self.assertIsNone(wf.header_hit(r['lock'].center().x(), r['lock'].center().y()))

    def test_case_du_cadenas_reservee_meme_sans_cadenas(self):
        """Les noms de TOUTES les lignes s'alignent sur la meme verticale."""
        wf = _piste("Audio", base=60)
        wf.lockable = False
        self.assertEqual(wf._header_rects(0)['lock'], self.t._header_rects(0)['lock'])

    def test_survol_du_cadenas(self):
        """Le survol eclaircit l'icone — et ne repeint que si l'etat change."""
        r = self.t._header_rects(0)
        self.assertIsNone(self.t._hdr_hover)
        self.t.update_header_hover(r['lock'].center().x(), r['lock'].center().y())
        self.assertEqual(self.t._hdr_hover, 'lock')
        self.t.update_header_hover(400, 20)
        self.assertIsNone(self.t._hdr_hover)


class Cadenas(unittest.TestCase):
    """Le verrou bloque l'edition et rien d'autre."""

    def setUp(self):
        self.t = _piste()
        self.clip = self.t.add_clip(1000, 4000, QColor("#0000ff"), 100)

    def test_bascule(self):
        self.assertFalse(self.t.locked)
        self.t.set_locked(True)
        self.assertTrue(self.t.locked)
        self.t.set_locked(False)
        self.assertFalse(self.t.locked)

    def test_deselectionne_en_verrouillant(self):
        """Sinon une selection restee active ferait passer les actions globales."""
        self.t.selected_clips = [self.clip]
        self.t.set_locked(True)
        self.assertEqual(self.t.selected_clips, [])

    def test_les_blocs_restent(self):
        """Verrouiller ne touche pas au contenu : le show sort a l'identique."""
        self.t.set_locked(True)
        self.assertEqual(len(self.t.clips), 1)
        self.assertEqual(self.t.get_clips_data()[0]['duration'], 4000)


class MasquageDeLigne(unittest.TestCase):
    """L'oeil range l'ecran, il ne coupe pas la lumiere."""

    def setUp(self):
        self.t = _piste()
        self.t.add_clip(0, 2000, QColor("#ff0000"), 80)

    def test_drapeau(self):
        self.assertFalse(self.t.row_hidden)
        self.t.row_hidden = True
        self.assertTrue(self.t.row_hidden)

    def test_les_blocs_partent_toujours_dans_la_sauvegarde(self):
        self.t.row_hidden = True
        self.assertEqual(len(self.t.get_clips_data()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
