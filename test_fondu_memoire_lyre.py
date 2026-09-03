"""
test_fondu_memoire_lyre.py — Le fondu entre deux memoires doit teindre AUSSI
les lyres, pas seulement les PAR.

Symptome remonte le 02/09/2026 : « autant ca fonctionne bien pour les par led,
autant sur les lyres le mouvement se fait petit a petit mais le fondu de la
couleur RVB ne marche pas — ni sur le plan 2D/3D, ni sur les vraies lyres ».

Racine : `_compute_htp_overrides` repose les memoires en HTP par-dessus le
modele a CHAQUE frame DMX, en comparant le niveau de la memoire au niveau
INSTANTANE du projecteur — jamais a la cible du fondu. Des que la memoire
d'arrivee est un cran plus haute que le look de depart (les lyres du show de
test : 24 % -> 25 %), `mem_level > proj.level` reste vrai pendant TOUTE la
rampe : la couleur d'arrivee etait reposee seche des la premiere frame. Les
PAR, eux, restaient a 100 % des deux cotes -> aucun override -> fondu visible.
Le pan/tilt glissait bien, l'HTP n'y touchant pas : d'ou l'impression d'un
fondu « qui ne marche que sur la couleur des PAR ».

    python test_fondu_memoire_lyre.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)


class FauxProj:
    def __init__(self, fixture_type="PAR LED", color="#000000", level=0):
        self.group = "face"
        self.fixture_type = fixture_type
        self.dmx_profile = ["R", "G", "B", "Dim"]
        self.base_color = QColor(color)
        self.color = QColor(color)
        self.level = level
        self.pan = self.tilt = 32768
        self.muted = False


class FauxFader:
    def __init__(self, value=100):
        self.value = value


class FauxTimer:
    """QTimer reduit a ce que le fondu en interroge."""

    def __init__(self):
        self.actif = False

    def start(self):
        self.actif = True

    def stop(self):
        self.actif = False

    def isActive(self):
        return self.actif


def _etat(level, base):
    """Etat d'un projecteur dans une memoire, reduit aux cles lues ici."""
    return {"level": level, "base_color": base}


class FauxWin:
    """MainWindow reduite au fondu de memoire et a la couche HTP."""

    _compute_htp_overrides = mw.MainWindow._compute_htp_overrides
    _fade_tick             = mw.MainWindow._fade_tick

    def __init__(self, projectors, memoires):
        self.projectors = projectors
        self.memories = memoires
        self.faders = {0: FauxFader(100)}
        self._muted_faders = set()
        self.active_memory_pads = {0: 0}
        self._mem_cue_idx = {}
        self._fade_timer = FauxTimer()
        self._fade_from = []
        self._fade_to = []
        self._fade_start = 0.0
        self._fade_dur = 0.0

    def _bank_memory_slots(self):
        return [(0, 0)]

    def _flash_level(self, v):
        return v

    def _mem_ensure_cues(self, mem):
        pass

    # ── outillage du test ─────────────────────────────────────────────────
    def armer_fondu(self, depart, cible, duree=3.5):
        """Pose le rig sur `depart` et arme la rampe vers `cible`."""
        import time

        self._fade_from = [(lvl, QColor(c)) for lvl, c in depart]
        self._fade_to = [(lvl, QColor(c)) for lvl, c in cible]
        for p, (lvl, col) in zip(self.projectors, self._fade_from):
            p.level = lvl
            p.base_color = QColor(col)
            p.color = QColor(int(col.red() * lvl / 100.0),
                             int(col.green() * lvl / 100.0),
                             int(col.blue() * lvl / 100.0))
        self._fade_dur = duree
        self._fade_start = time.time()
        self._fade_timer.start()

    def couleur_rendue(self, i):
        """Ce que voient le plan 2D et la sortie DMX : modele + overrides HTP."""
        ov = self._compute_htp_overrides()
        p = self.projectors[i]
        if id(p) in ov:
            return ov[id(p)][2]      # base_color de l'override
        return QColor(p.base_color)

    def avancer(self, ratio):
        import time
        self._fade_start = time.time() - self._fade_dur * ratio
        self._fade_tick()


# Le show de test du client : deux lyres a 24/25 %, un PAR a 100 %.
ROUGE, BLEU = "#ff0000", "#0000ff"
MEM_DEPART = [_etat(24, ROUGE), _etat(24, ROUGE), _etat(100, ROUGE)]
MEM_CIBLE  = [_etat(25, BLEU),  _etat(25, BLEU),  _etat(100, BLEU)]


def _faux_win():
    projos = [FauxProj("Moving Head"), FauxProj("Moving Head"), FauxProj("PAR LED")]
    # La memoire ACTIVE est celle d'arrivee : c'est elle que l'HTP repose.
    memoires = [[{"cues": [{"projectors": MEM_CIBLE}]}]]
    w = FauxWin(projos, memoires)
    w.armer_fondu([(s["level"], s["base_color"]) for s in MEM_DEPART],
                  [(s["level"], s["base_color"]) for s in MEM_CIBLE])
    return w


class TestFonduMemoire(unittest.TestCase):

    def test_la_lyre_traverse_le_violet_comme_le_par(self):
        """A mi-rampe, lyres ET PAR doivent etre entre le rouge et le bleu."""
        w = _faux_win()
        w.avancer(0.5)
        for i, nom in ((0, "lyre 1"), (1, "lyre 2"), (2, "PAR")):
            c = w.couleur_rendue(i)
            self.assertGreater(c.red(), 40, f"{nom} : le rouge a deja disparu")
            self.assertGreater(c.blue(), 40, f"{nom} : le bleu n'est pas encore la")

    def test_pas_de_saut_a_la_premiere_frame(self):
        """La 1re frame ne doit pas deja poser la couleur d'arrivee (le bug)."""
        w = _faux_win()
        w.avancer(0.02)
        for i, nom in ((0, "lyre 1"), (1, "lyre 2"), (2, "PAR")):
            c = w.couleur_rendue(i)
            self.assertGreater(c.red(), 200, f"{nom} : saute au bleu des le debut")

    def test_l_htp_reprend_la_main_le_fondu_fini(self):
        """Fondu termine : la couche HTP redevient active (aucune regression)."""
        w = _faux_win()
        w.avancer(1.0)                       # `_fade_tick` arrete le timer
        self.assertFalse(w._fade_timer.isActive())
        w.projectors[0].level = 0            # un autre moteur baisse la lyre
        w.projectors[0].base_color = QColor("#000000")
        self.assertEqual(w.couleur_rendue(0).name(), BLEU,
                         "la memoire n'est plus reposee en HTP apres le fondu")


if __name__ == "__main__":
    unittest.main(verbosity=2)
