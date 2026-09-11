"""
test_pistes_ordre_groupes.py — Ordre et couleur des pistes de groupe du REC
lumiere.

Retour Christo, 11/09/2026 : « les groupe son plus ordonner ». Exact :
`_TRACK_ORDER` (timeline_editor) s'arretait a F. Les groupes G et H prenaient
donc la cle des groupes INCONNUS et atterrissaient tout en bas de la timeline,
APRES les pistes speciales Lyres / Barres / Strobos / Fumee — et sans couleur
propre, ils heritaient du bleu de B.

C'etait le seul endroit du code tronque a F : les ~13 autres listes de groupes
(main_window, plan_de_feu, effect_editor, dmx_in_link, ui_components…) vont bien
de A a H. Ce test verrouille les deux bouts : l'ordre, et le fait qu'aucune des
huit lettres ne tombe dans le fourre-tout des inconnus.
"""

import io
import unittest

from timeline_editor import _TRACK_COLORS, _TRACK_ORDER, track_sort_key

_LETTRES  = ["A", "B", "C", "D", "E", "F", "G", "H"]
_SPECIALES = ["Lyres", "Barres", "Strobos", "Fumee"]


class TestOrdreCanonique(unittest.TestCase):

    def test_les_huit_groupes_sont_connus(self):
        """Aucune lettre ne doit tomber dans le rang des inconnus."""
        inconnu = len(_TRACK_ORDER)
        for lettre in _LETTRES:
            with self.subTest(groupe=lettre):
                self.assertLess(track_sort_key(lettre), inconnu)

    def test_les_lettres_sont_dans_l_ordre_alphabetique(self):
        rangs = [track_sort_key(l) for l in _LETTRES]
        self.assertEqual(rangs, sorted(rangs))
        self.assertEqual(rangs, list(range(8)))

    def test_les_groupes_precedent_les_pistes_speciales(self):
        """C'est le symptome signale : G et H passaient apres Fumee."""
        dernier_groupe = max(track_sort_key(l) for l in _LETTRES)
        for speciale in _SPECIALES:
            with self.subTest(piste=speciale):
                self.assertGreater(track_sort_key(speciale), dernier_groupe)

    def test_un_groupe_inconnu_va_a_la_fin(self):
        self.assertEqual(track_sort_key("Public"), len(_TRACK_ORDER))
        self.assertGreater(track_sort_key("Public"), track_sort_key("Fumee"))

    def test_le_tri_reel_range_g_et_h_a_leur_place(self):
        """Le tri tel que `_create_tracks_from_fixtures` l'applique."""
        # Ordre d'apparition dans un patch : les lyres patchees avant les PAR
        # des groupes G et H.
        vus = ["Lyres", "A", "H", "Fumee", "G", "B"]
        vus.sort(key=track_sort_key)
        self.assertEqual(vus, ["A", "B", "G", "H", "Lyres", "Fumee"])

    def test_le_tri_est_stable_pour_les_inconnus(self):
        vus = ["Public", "Truc", "A"]
        vus.sort(key=track_sort_key)
        self.assertEqual(vus, ["A", "Public", "Truc"])


class TestCouleurs(unittest.TestCase):

    def test_chaque_groupe_a_sa_couleur(self):
        for nom in _LETTRES + _SPECIALES:
            with self.subTest(piste=nom):
                self.assertIn(nom, _TRACK_COLORS)

    def test_aucune_couleur_en_double(self):
        """G heritait du bleu de B faute d'entree : deux pistes identiques."""
        couleurs = [_TRACK_COLORS[n] for n in _LETTRES]
        self.assertEqual(len(couleurs), len(set(couleurs)))

    def test_g_et_h_portent_les_couleurs_du_patch(self):
        """Memes teintes que les anneaux du plan de feu (`_GROUP_COLORS`)."""
        from plan_de_feu import _GROUP_COLORS
        self.assertEqual(_TRACK_COLORS["G"], _GROUP_COLORS["groupe_g"])
        self.assertEqual(_TRACK_COLORS["H"], _GROUP_COLORS["groupe_h"])


class TestPlusAucuneListeTronquee(unittest.TestCase):
    """Le fourre-tout par defaut de `GROUP_DISPLAY` connait G et H lui aussi.

    `_create_tracks_from_fixtures` lit `main_window.GROUP_DISPLAY` mais garde une
    copie de secours en dur : si elle oubliait G/H, les pistes s'appelleraient
    « Groupe_g » et retomberaient chez les inconnus malgre le tri corrige.
    """

    def test_le_repli_group_display_couvre_g_et_h(self):
        with io.open('timeline_editor.py', encoding='utf-8') as f:
            src = f.read()
        debut = src.index('def _create_tracks_from_fixtures')
        corps = src[debut:debut + 1200]
        self.assertIn('"groupe_g": "G"', corps)
        self.assertIn('"groupe_h": "H"', corps)


if __name__ == "__main__":
    unittest.main(verbosity=2)
