"""
test_effet_une_fois.py — Editeur d'effets : lecture « Une fois ».

Le moteur savait deja jouer un effet en mode "once", mais :
1. les boutons En boucle / Une fois etaient des objets orphelins, jamais poses
   dans l'editeur — impossible de choisir le mode ;
2. "once" s'arretait apres 2 s fixes, quelle que soit la VITESSE : un effet
   lent etait coupe en plein milieu, un effet rapide tournait plusieurs fois ;
3. en superposition, la fin d'un effet "once" arretait le timer commun, donc
   TOUS les effets empiles.

Desormais un passage = un tour de la couche la plus lente, sur l'horloge de
phase (`core.effect_cycle_seconds`).
"""

import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core import effect_cycle_seconds, layer_frequency

_app = QApplication.instance() or QApplication(sys.argv)


def _couche(**kw):
    d = {"attribute": "Dimmer", "forme": "Sinus", "speed": 50, "direction": 1, "block": 1}
    d.update(kw)
    return d


class TestDureeDunPassage(unittest.TestCase):

    def test_une_couche_fait_un_tour(self):
        self.assertAlmostEqual(effect_cycle_seconds([_couche(speed=50)]),
                               1.0 / layer_frequency(50))

    def test_la_couche_la_plus_lente_fixe_la_duree(self):
        lente, rapide = _couche(speed=10), _couche(speed=90)
        self.assertAlmostEqual(effect_cycle_seconds([rapide, lente]),
                               1.0 / layer_frequency(10))

    def test_couches_immobiles_ignorees(self):
        self.assertEqual(effect_cycle_seconds([_couche(forme="Fixe"),
                                               _couche(forme="Off"),
                                               _couche(speed=0)]), 0.0)

    def test_pan_tilt_compte_meme_en_forme_fixe(self):
        pt = _couche(attribute="Pan/Tilt", forme="Fixe", speed=40)
        self.assertAlmostEqual(effect_cycle_seconds([pt]), 1.0 / layer_frequency(40))

    def test_chenillard_aller_retour_revient_au_depart(self):
        # 8 fixtures, aller-retour 1..8..2 = 14 pas = 14/8 de cycle
        ch = _couche(forme="Un par un", direction=0, speed=50)
        self.assertAlmostEqual(effect_cycle_seconds([ch], 8),
                               (14 / 8) / layer_frequency(50))
        # GROUPER par 4 : 2 paquets → aller-retour = 1 cycle
        self.assertAlmostEqual(effect_cycle_seconds([dict(ch, block=4)], 8),
                               1.0 / layer_frequency(50))


class FauxTimer:
    def __init__(self):
        self.stops = 0

    def stop(self):
        self.stops += 1


class FauxShow:
    """MainWindow reduite a ce que le debut de `_update_effect_from_layers` lit."""

    def __init__(self, clock):
        from main_window import MainWindow
        self._run = MainWindow._update_effect_from_layers
        self.effect_speed     = 100
        self.effect_t0        = time.monotonic()
        self._effect_clock    = clock
        self._effect_clock_ts = None
        self.projectors       = []
        self.effect_timer     = FauxTimer()
        self._stacked_tick    = None

    def _stop_once_effect(self):
        pass

    def frame(self, cfg):
        self._run(self, cfg)


class TestMoteurUneFois(unittest.TestCase):

    CYCLE = 1.0 / layer_frequency(50)

    def _cfg(self, mode="once"):
        return {"name": "Test", "layers": [_couche(speed=50)], "play_mode": mode}

    def test_continue_pendant_le_passage(self):
        show = FauxShow(clock=self.CYCLE * 0.5)
        show.frame(self._cfg())
        self.assertEqual(show.effect_timer.stops, 0)

    def test_s_arrete_apres_un_tour(self):
        show = FauxShow(clock=self.CYCLE * 1.01)
        show.frame(self._cfg())
        self.assertEqual(show.effect_timer.stops, 1)

    def test_boucle_ne_s_arrete_jamais(self):
        show = FauxShow(clock=self.CYCLE * 50)
        show.frame(self._cfg("loop"))
        self.assertEqual(show.effect_timer.stops, 0)

    def test_superposition_ne_coupe_que_cet_effet(self):
        show = FauxShow(clock=self.CYCLE * 1.01)
        show._stacked_tick = {"idx": 2}
        show.frame(self._cfg())
        self.assertEqual(show.effect_timer.stops, 0, "le timer commun doit continuer")
        self.assertTrue(show._stacked_tick.get("once_done"))

    def test_ancienne_duree_en_secondes_respectee(self):
        cfg = dict(self._cfg(), duration=30)
        show = FauxShow(clock=self.CYCLE * 5)   # 5 tours, mais 30 s pas écoulées
        show.frame(cfg)
        self.assertEqual(show.effect_timer.stops, 0)


if __name__ == "__main__":
    unittest.main()
