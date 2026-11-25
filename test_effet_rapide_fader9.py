"""Fader 9 (vitesse des effets) sur les effets rapides du plan de feu.

Ils l'ignoraient : poussé pour suivre la musique, il ne changeait rien à un
cercle lancé depuis le plan 2D (FuraxX / Djch28, 21/11/2026).
"""
import sys, types, unittest, time
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from plan_de_feu import PlanDeFeu, _EffectState


class P:
    pan = 32768; tilt = 32768


def phase_apres(fader, mw=True):
    p = P()
    st = _EffectState("cercle", 1.0, 5000, 32768, 32768)
    fake = types.SimpleNamespace(
        _effects={id(p): st}, _led_effects={}, projectors=[p],
        main_window=types.SimpleNamespace(effect_speed=fader) if mw else None,
        _fx_last_tick=time.monotonic() - 0.1)
    try:
        PlanDeFeu._tick_effects(fake)
    except Exception:
        pass   # la suite du tick (rafraîchissement, DMX) n'existe pas ici
    return st.phase


class T(unittest.TestCase):
    def test_defaut_inchange(self):
        # fader à 80 (défaut) ou pas de fenêtre : vitesse d'avant
        self.assertAlmostEqual(phase_apres(80), phase_apres(80, mw=False), delta=0.05)

    def test_fader_haut_accelere(self):
        self.assertGreater(phase_apres(100), 2.5 * phase_apres(80))

    def test_fader_bas_ralentit_sans_figer(self):
        lent = phase_apres(0)
        self.assertGreater(lent, 0.0)
        self.assertLess(lent, 0.2 * phase_apres(80))


if __name__ == "__main__":
    unittest.main()
