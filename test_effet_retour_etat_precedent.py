"""
test_effet_retour_etat_precedent.py — Couper un effet doit rendre CE QU'IL Y AVAIT.

Trois symptomes remontes le 28/08/2026, une meme racine et deux voisines :

  1. « Bleu au pad AKAI, effet de mouvement, rouge au pad, je relache l'effet :
     je retombe sur du bleu. » `effect_saved_colors` etait un instantane MORT,
     pris au demarrage de l'effet et rendu tel quel a l'arret : tout ce que
     l'utilisateur posait pendant l'effet etait jete a la coupure.

  2. « Effet passage au blanc, je l'enleve, je suis oblige de renvoyer les
     couleurs au pad. » Deux chemins arretaient le timer d'effet SANS restituer :
     le changement de pad memoire (la capture etait simplement VIDEE) et
     `turn_off_all_effects` (bouton « Arreter les effets » de la fenetre
     externe). Les projecteurs restaient figes sur la derniere image de l'effet.

  3. Lyre a ROUE de couleurs sous une couche RVB : le moteur encode toute la
     brillance dans `proj.color` et force `level = 100`. L'affichage d'une
     fixture a roue lit la roue pour la teinte et `level` pour l'intensite : la
     brillance etait donc jetee, la lyre sautait de slot en slot a intensite
     constante en 2D comme en 3D pendant que le vrai projecteur pulsait.

    python test_effet_retour_etat_precedent.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import core
import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)


class FauxProj:
    """Projecteur reduit aux attributs que la capture d'effet manipule."""

    def __init__(self, group="face", profile=None, color="#000000", level=0):
        self.group = group
        self.fixture_type = "PAR LED"
        self.dmx_profile = list(profile if profile is not None else ["R", "G", "B", "Dim"])
        self.base_color = QColor(color)
        self.color = QColor(color)
        self.level = level
        self.pan = self.tilt = 32768
        self.white_boost = self.amber_boost = self.uv = 0
        self.color_wheel = self.gobo = self.zoom = 0
        self.color_wheel_slots = []
        self.dmx_mode = "Manuel"

    def release_color_overrides(self):
        pass


class _TimerMuet:
    def __init__(self):
        self.actif = False

    def stop(self):
        self.actif = False

    def isActive(self):
        return self.actif


class FauxWin:
    """MainWindow reduite a la capture/restitution d'etat d'effet."""

    # `staticmethod` explicite : recopiees telles quelles, ces deux-la
    # redeviendraient des methodes d'instance et recevraient `self` en premier.
    _effect_state_tuple   = staticmethod(mw.MainWindow._effect_state_tuple)
    _effect_state_key     = staticmethod(mw.MainWindow._effect_state_key)
    _snapshot_effect_state = mw.MainWindow._snapshot_effect_state
    _restore_effect_state = mw.MainWindow._restore_effect_state
    _record_effect_frame  = mw.MainWindow._record_effect_frame
    _sync_effect_baseline = mw.MainWindow._sync_effect_baseline
    update_effect         = mw.MainWindow.update_effect
    turn_off_all_effects  = mw.MainWindow.turn_off_all_effects

    def __init__(self, projectors):
        self.projectors = projectors
        self.effect_saved_colors = {}
        self._effect_engine_frame = None
        self.active_effect = None
        self.active_effect_config = {}
        self._stacked_effects = []
        self.effect_buttons = []
        self.active_fx_pads = {}
        self._fader_map = []
        self.effect_timer = _TimerMuet()
        # Le moteur d'effet, remplace par une fonction posee par le test
        self.moteur = lambda: None

    # ── ce que fait le moteur, neutralise : le test pose `self.moteur` ──────
    def _run_effect_frame(self):
        self.moteur()

    def _style_fx_pad(self, *a):
        pass

    def _update_fx_pad_led(self, *a):
        pass


def _pad(proj, color, level):
    """Ce que fait `activate_pad` : couleur pure + couleur affichee."""
    proj.base_color = QColor(color)
    proj.level = level
    br = level / 100.0
    proj.color = QColor(int(proj.base_color.red() * br),
                        int(proj.base_color.green() * br),
                        int(proj.base_color.blue() * br))


class TestCaptureVivante(unittest.TestCase):
    """1. Une couleur posee PENDANT l'effet doit survivre a sa coupure."""

    def setUp(self):
        self.p = FauxProj()
        self.w = FauxWin([self.p])

    def _effet_blanc(self):
        """Ce qu'ecrit une couche RVB : brillance dans color, level a 100."""
        self.p.level = 100
        self.p.color = QColor(255, 255, 255)

    def test_couleur_posee_pendant_l_effet_est_conservee(self):
        _pad(self.p, "#0000ff", 100)          # bleu au pad
        self.w._snapshot_effect_state()
        self.w.moteur = self._effet_blanc
        self.w.update_effect()                 # 1re frame d'effet

        _pad(self.p, "#ff0000", 100)           # rouge au pad, effet en cours
        self.w.update_effect()                 # frame suivante : l'effet reecrit

        self.w._restore_effect_state()
        self.assertEqual(self.p.base_color.name(), "#ff0000",
                         "le rouge pose pendant l'effet a ete jete au profit du bleu")
        self.assertEqual(self.p.color.name(), "#ff0000")

    def test_sans_intervention_l_etat_d_avant_revient(self):
        _pad(self.p, "#0000ff", 60)
        self.w._snapshot_effect_state()
        self.w.moteur = self._effet_blanc
        for _ in range(3):
            self.w.update_effect()

        self.w._restore_effect_state()
        self.assertEqual(self.p.base_color.name(), "#0000ff")
        self.assertEqual(self.p.level, 60)
        self.assertEqual(self.p.color.name(), "#000099")

    def test_le_centre_pan_tilt_ne_bouge_pas_sous_l_effet(self):
        """Un pad couleur ne doit pas deplacer le centre de la trajectoire."""
        self.p.pan, self.p.tilt = 20000, 40000
        _pad(self.p, "#0000ff", 100)
        self.w._snapshot_effect_state()

        def _mouvement():
            self.p.pan += 500          # l'effet fait tourner la lyre
            self.p.tilt -= 300
        self.w.moteur = _mouvement
        self.w.update_effect()
        _pad(self.p, "#ff0000", 100)   # couleur changee, pas la position
        self.w.update_effect()

        saved = self.w.effect_saved_colors[id(self.p)]
        self.assertEqual((saved[3], saved[4]), (20000, 40000),
                         "le centre pan/tilt a suivi l'effet au lieu de rester fixe")

    def test_position_reprise_a_la_main_est_conservee(self):
        self.p.pan = 20000
        self.w._snapshot_effect_state()
        self.w.moteur = lambda: None    # effet qui ne touche pas au pan
        self.w.update_effect()
        self.p.pan = 51000              # l'utilisateur vise ailleurs
        self.w.update_effect()

        self.w._restore_effect_state()
        self.assertEqual(self.p.pan, 51000)


class TestCoupureSansRestitution(unittest.TestCase):
    """2. Arreter le timer ne defait rien : il faut restituer."""

    def test_turn_off_all_effects_rend_l_etat_d_avant(self):
        p = FauxProj()
        _pad(p, "#0000ff", 100)
        w = FauxWin([p])
        w._snapshot_effect_state()
        p.level, p.color = 100, QColor(255, 255, 255)   # effet blanc en cours

        w.turn_off_all_effects()
        self.assertEqual(p.color.name(), "#0000ff",
                         "les projecteurs sont restes figes sur l'image blanche")
        self.assertEqual(w.effect_saved_colors, {})

    def test_turn_off_all_effects_sans_effet_ne_casse_rien(self):
        """Ce chemin sert aussi au demarrage : la capture est vide."""
        p = FauxProj(color="#00ff00", level=80)
        w = FauxWin([p])
        w.turn_off_all_effects()
        self.assertEqual(p.color.name(), "#00ff00")
        self.assertEqual(p.level, 80)

    def test_changement_de_pad_memoire_restitue_avant_de_nettoyer(self):
        """`_activate_memory_pad` : la restitution passe AVANT le nettoyage.

        Ordre inverse, la restitution rendrait l'etat d'avant l'effet — memoire
        allumee comprise — et ecraserait l'extinction de la memoire quittee.
        """
        import inspect
        src = inspect.getsource(mw.MainWindow._activate_memory_pad)
        i_restore = src.index("self._restore_effect_state()")
        i_clear = src.index("self._clear_memory_from_projectors(mem_col, prev_row)")
        self.assertLess(i_restore, i_clear)
        self.assertNotIn("self.effect_saved_colors = {}", src,
                         "la capture est de nouveau videe sans restitution")


class TestRoueSousCoucheRVB(unittest.TestCase):
    """3. L'intensite d'une lyre a roue ne doit pas se perdre en route."""

    def _lyre_roue(self):
        p = FauxProj(profile=["Pan", "Tilt", "Dim", "ColorWheel", "Gobo1"])
        p.fixture_type = "Moving Head"
        p.color_wheel_slots = [{"dmx": 0, "color": "#ffffff"},
                               {"dmx": 20, "color": "#ff3300"}]
        return p

    def test_brillance_encodee_dans_color_est_retrouvee(self):
        p = self._lyre_roue()
        p.base_color = QColor("#ff0000")
        p.level = 100                       # force par le moteur d'effets
        p.color = QColor(64, 0, 0)          # brillance reelle : 25 %
        p.color_wheel = 20
        self.assertAlmostEqual(core.emitted_brightness(p), 64 / 255.0, places=3)

    def test_sans_effet_la_brillance_reste_le_niveau(self):
        p = self._lyre_roue()
        p.base_color = QColor("#ff0000")
        p.level = 40
        p.color = QColor(102, 0, 0)         # = base x level, pas d'effet
        self.assertAlmostEqual(core.emitted_brightness(p), 0.4, places=2)

    def test_projecteur_eteint(self):
        p = self._lyre_roue()
        p.level = 0
        p.color = QColor(0, 0, 0)
        self.assertEqual(core.emitted_brightness(p), 0.0)

    def test_plan_2d_affiche_la_roue_a_l_intensite_reelle(self):
        p = self._lyre_roue()
        p.base_color = QColor("#ff0000")
        p.level = 100
        p.color = QColor(64, 0, 0)
        p.color_wheel = 20                   # slot rouge
        vue   = core.color_wheel_display_color(p, core.emitted_brightness(p))
        plein = core.color_wheel_display_color(p)          # slot a pleine valeur
        self.assertLess(vue.red(), 120,
                        "la lyre s'affiche a fond alors qu'elle est a 25 %")
        self.assertGreater(vue.red(), 20)
        # Meme teinte, seule l'intensite change : le quart du slot, a l'arrondi pres
        self.assertAlmostEqual(vue.red()   / max(1, plein.red()),   0.25, places=1)
        self.assertAlmostEqual(vue.green() / max(1, plein.green()), 0.25, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
