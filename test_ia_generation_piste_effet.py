"""
test_ia_generation_piste_effet.py — La generation IA remplissait la piste Effet.

Signale par un client : « lors de l'utilisation de la generation par l'IA, les
effets ne s'activent pas. Ils sont crees mais il est necessaire de faire Sortie
live puis sauvegarder pour qu'ils soient actives. »

La boite « Generation par IA » (REC Lumiere → Outils) listait une case par
piste, cochee d'office, en excluant Sequence / Position / Gobo / projecteur —
mais PAS la piste Effet. Or `perform_ai_generation` ne pose que des blocs de
COULEUR :

  * sur la piste Effet ils s'affichent « ✨ Effet », sans `effect_name` ni
    couches — l'aperçu (`timeline_editor`) comme la restitution (`sequencer`)
    exigent un nom resolu dans le catalogue pour armer un effet : ces blocs ne
    declenchaient donc rien, d'ou « ils sont crees mais ne s'activent pas » ;
  * la case etant cochee, generer commençait par vider la piste (`clips.clear()`)
    → les vrais effets deja poses partaient avec.

    python test_ia_generation_piste_effet.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import timeline_editor as te
from light_timeline import LightClip


class FausseP:
    """Piste reduite a ses drapeaux de type et a son verrou."""

    def __init__(self, name, **flags):
        self.name  = name
        self.clips = []
        self.locked = flags.pop('locked', False)
        for k, v in flags.items():
            setattr(self, k, v)

    def __repr__(self):
        return f"<{self.name}>"


class GenerationIA(unittest.TestCase):

    _tracks = staticmethod(te.LightTimelineEditor._ai_generable_tracks)

    def setUp(self):
        # L'ordre reel de `_create_tracks_from_fixtures` : Effet, Sequence,
        # Position, Gobo, puis les groupes et leurs pistes projecteur.
        self.effet   = FausseP("Effet",    is_effect_track=True)
        self.seq     = FausseP("Sequence", is_sequence_track=True)
        self.pos     = FausseP("Position", is_position_track=True)
        self.gobo    = FausseP("Gobo",     is_gobo_track=True)
        self.groupe_a = FausseP("A")
        self.groupe_b = FausseP("B")
        self.verrouillee = FausseP("C", locked=True)
        self.projo   = FausseP("PAR 1", is_projector_track=True)

        self.editeur = type("FauxEditeur", (), {
            "_editable": staticmethod(te.LightTimelineEditor._editable),
        })()
        self.editeur.tracks = [self.effet, self.seq, self.pos, self.gobo,
                               self.groupe_a, self.groupe_b,
                               self.verrouillee, self.projo]

    def test_piste_effet_exclue(self):
        """Le bug du client : la piste Effet n'est plus proposee ni remplie."""
        self.assertNotIn(self.effet, self._tracks(self.editeur))

    def test_seules_les_pistes_de_groupe_restent(self):
        self.assertEqual(self._tracks(self.editeur),
                         [self.groupe_a, self.groupe_b])

    def test_piste_verrouillee_exclue(self):
        """Le cadenas protege aussi de la generation (regression existante)."""
        self.assertNotIn(self.verrouillee, self._tracks(self.editeur))

    def test_bloc_genere_ne_porte_aucun_effet(self):
        """Pourquoi la piste Effet doit etre exclue : le bloc pose par la
        generation n'a ni nom d'effet ni couches — rien a armer."""
        from PySide6.QtGui import QColor
        clip = LightClip(0, 1000, QColor("#ff0000"), 80, None)
        self.assertEqual(getattr(clip, 'effect_name', ''), "")
        self.assertEqual(getattr(clip, 'effect_layers', []), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
