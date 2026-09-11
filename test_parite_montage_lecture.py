# -*- coding: utf-8 -*-
"""Parite entre le MONTAGE (apercu REC lumiere) et la LECTURE (restitution).

Retour client Christo (09/2026) : « en lecture automatique de la playlist, ce
n'est pas les effets demandes, vraiment different de ce qui est fait en REC
lumiere ». Trois causes ont ete tracees et corrigees ; ce fichier les verrouille.

Les moteurs sont deux chemins Qt distincts (`timeline_editor` pour l'apercu,
`sequencer` pour le show) : on teste donc la SOURCE la ou instancier le moteur
demanderait tout MyStrow, et le comportement reel partout ou c'est possible.
"""
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).parent


def src(nom):
    return (RACINE / nom).read_text(encoding='utf-8')


class AmplitudePanTilt(unittest.TestCase):
    """Ecart 1 — l'amplitude des couches Pan/Tilt, x4 en 3.1.91.

    3.1.91 avait porte le facteur de 8192 a 32768 : tout show monte avant
    balayait d'un coup 4x plus large que ce qui avait ete valide. Les 5 sites
    (2 dans le moteur du show, 3 dans l'apercu de l'editeur d'effets) doivent
    porter le MEME facteur, sinon l'apercu ment sur le mouvement reel.
    """

    MOTIF = re.compile(r'(?:size / 100\.0\) \* )(\d+)')

    def _facteurs(self, nom):
        """Les facteurs du CODE, commentaires exclus.

        Les commentaires citent l'expression exacte — c'est voulu, ils
        expliquent pourquoi elle ne bouge pas et renvoient d'un moteur a
        l'autre — et les compter faisait echouer ce test a la premiere phrase
        ajoutee (vu le 11/09/2026, en documentant le plafond AMP a 400).
        """
        code = '\n'.join(l for l in src(nom).splitlines()
                         if not l.lstrip().startswith('#'))
        return [int(m) for m in self.MOTIF.findall(code)]

    def test_les_cinq_sites_existent_toujours(self):
        self.assertEqual(len(self._facteurs('main_window.py')), 2)
        self.assertEqual(len(self._facteurs('effect_editor.py')), 3)

    def test_les_cinq_sites_portent_le_meme_facteur(self):
        tous = self._facteurs('main_window.py') + self._facteurs('effect_editor.py')
        self.assertEqual(len(set(tous)), 1,
                         "apercu et show doivent partager la meme echelle "
                         f"d'amplitude, trouve : {tous}")

    def test_le_facteur_est_bien_8192(self):
        """32768 quadruple le mouvement de tous les .lrec anterieurs a 3.1.91."""
        tous = self._facteurs('main_window.py') + self._facteurs('effect_editor.py')
        self.assertEqual(set(tous), {8192})


class VitesseDuClipDEffet(unittest.TestCase):
    """Ecart 2 — la VIT du clip, ignoree au montage et appliquee en lecture.

    `'speed_override': 50` etait ecrit en dur dans l'apercu pendant que la
    restitution lisait `effect_speed`. Consequence vue par le client : le
    reglage de vitesse (clic droit sur le clip) « ne changeait rien a l'oeil »,
    mais partait quand meme dans le .lrec et sortait le soir du show.
    """

    def test_l_apercu_ne_force_plus_50(self):
        self.assertNotIn("'speed_override': 50", src('timeline_editor.py'))

    def test_l_apercu_lit_la_vitesse_du_clip(self):
        t = src('timeline_editor.py')
        self.assertIn("getattr(_first_eff_clip, 'effect_speed', 50)", t)
        self.assertIn("'speed_override': _speed_override", t)

    def test_la_vitesse_entre_dans_la_garde_de_changement(self):
        """Sinon regler la VIT pendant que l'apercu tourne ne rafraichit rien."""
        t = src('timeline_editor.py')
        self.assertIn("_speed_override != getattr(self, '_eff_speed_active', None)", t)

    def test_vit_zero_n_est_pas_retransformee_en_50(self):
        """VIT 0 = effet quasi fige, c'est une valeur legitime.

        Un `or 50` la relancerait a mi-vitesse (0 est faux en Python).
        """
        t = src('timeline_editor.py')
        self.assertNotIn("'effect_speed', 50) or 50", t)

    def test_les_deux_moteurs_lisent_le_meme_champ(self):
        self.assertIn("effect_speed", src('sequencer.py'))
        self.assertIn("effect_speed", src('timeline_editor.py'))

    def test_le_defaut_reste_50_des_deux_cotes(self):
        self.assertIn("effet_clips[0].get('effect_speed', 50)", src('sequencer.py'))
        self.assertIn("getattr(_first_eff_clip, 'effect_speed', 50)", src('timeline_editor.py'))


class OrdreDesPistes(unittest.TestCase):
    """Ecart 3 — priorite « piste projecteur > piste de groupe ».

    La restitution trie pour que les pistes « un projecteur seul » soient
    ecrites en DERNIER (le rig repart d'une page blanche a chaque frame : la
    derniere piste ecrite gagne). L'apercu, lui, iterait les pistes dans
    l'ordre d'affichage — identique tant que les pistes projecteur avaient ete
    creees en dernier, divergent des qu'une piste de groupe etait ajoutee
    apres elles.
    """

    def test_l_apercu_trie_comme_la_restitution(self):
        t = src('timeline_editor.py')
        self.assertIn("key=lambda _tr: is_projector_track(getattr(_tr, 'name', ''))", t)

    def test_la_restitution_trie_toujours(self):
        self.assertIn("key=lambda kv: _is_proj_track(kv[0])", src('sequencer.py'))

    def test_le_tri_range_bien_les_pistes_projecteur_en_dernier(self):
        from core import is_projector_track
        pistes = ['Face', '@3', 'Douche 1', '@7', 'Contres']
        ordre = sorted(pistes, key=is_projector_track)
        self.assertEqual(ordre, ['Face', 'Douche 1', 'Contres', '@3', '@7'])

    def test_le_tri_est_stable(self):
        """L'ordre du fichier doit etre preserve a l'interieur de chaque famille."""
        from core import is_projector_track
        pistes = ['@1', 'Face', '@2', 'Lyres']
        self.assertEqual(sorted(pistes, key=is_projector_track),
                         ['Face', 'Lyres', '@1', '@2'])

    def test_le_tri_ne_casse_pas_sur_une_piste_sans_nom(self):
        from core import is_projector_track
        self.assertFalse(is_projector_track(''))
        self.assertFalse(is_projector_track(None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
