"""REC des effets rapides du plan 2D (demande artifice81, 12/11/2026).

REC → pad (FX ou mémoire) : le pad rejoue tout ce qui tourne — effets lancés
ET effets rapides de lyres (vitesse, amplitude, déphasage, mêmes lyres dans le
même ordre). Sur un pad FX, couleur / roue / gobo / niveau sont posés une
seule fois au lancement (`start_look`), jamais par une couche — sinon le gobo
ne pourrait plus être changé pendant le mouvement.
"""
import sys, types, unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
app = QApplication.instance() or QApplication(sys.argv)
import main_window as mw
import effect_editor
from plan_de_feu import _EffectState
from core import layer_frequency

M = mw.MainWindow


class P:
    def __init__(s, g, ft="Moving Head"):
        s.group = g; s.base_color = QColor("#ff00aa"); s.color = QColor("#ff00aa")
        s.color_wheel = 12; s.gobo = 40; s.pan = 30000; s.tilt = 30000
        s.fixture_type = ft; s.level = 100


class FauxPdf:
    def __init__(s, effects, phase):
        s._effects = effects; s._qe_phase = phase; s.stopped = None

    def stop_effect(s, projs):
        s.stopped = list(projs)
        for p in projs:
            s._effects.pop(id(p), None)


class FauxWin:
    _QE_TO_SHAPE = M._QE_TO_SHAPE
    _quick_move_layers = M._quick_move_layers
    _effect_for_rec = M._effect_for_rec
    _stop_quick_moves = M._stop_quick_moves
    _apply_effect_start_look = M._apply_effect_start_look
    _record_fx_pad = M._record_fx_pad

    def __init__(s, projs, effects, phase=60):
        s.projectors = projs
        s.plan_de_feu = FauxPdf(effects, phase)
        s.active_effect = None; s.active_effect_config = {}
        s._stacked_effects = []
        s.active_fx_pads = {}
        s.fx_pads = [[None] * 8 for _ in range(8)]
        s.log = []; s.errors = []

    def _show_error_toast(s, t): s.errors.append(t)
    def _style_fx_pad(s, c, r): pass
    def _update_fx_pad_led(s, c, r): pass
    def _save_akai_config_auto(s): pass
    def _log_message(s, t, k=None): s.log.append(t)


class T(unittest.TestCase):
    def setUp(self):
        self._load, self._save = effect_editor._load_custom_effects, effect_editor._save_custom_effects
        self.saved = []
        effect_editor._load_custom_effects = lambda: list(self.saved)
        effect_editor._save_custom_effects = lambda l: self.saved.__init__(l)
        # patch : lat 0, lat 1, contre 0 (lyres) + face 0 (PAR, hors effet)
        self.projs = [P("lat"), P("lat"), P("contre"), P("face", "PAR LED")]
        self.fx = {}
        # déphasage : ordre de sélection = lat 1, lat 0, contre 0
        for k, p in enumerate([self.projs[1], self.projs[0], self.projs[2]]):
            st = _EffectState("cercle", 0.5, 10000, 31000, 29000)
            st.speed = 0.7; st.amplitude = 8000; st.phase_offset = k * 0.5
            self.fx[id(p)] = st

    def tearDown(self):
        effect_editor._load_custom_effects, effect_editor._save_custom_effects = self._load, self._save

    def win(self, **kw):
        return FauxWin(self.projs, self.fx, **kw)

    def test_couche_equivalente(self):
        layers, centres = self.win()._quick_move_layers()
        self.assertEqual(len(layers), 1)
        pt = layers[0]
        self.assertEqual(pt["mouvement_shape"], "cercle")
        self.assertAlmostEqual(layer_frequency(pt["speed"]), 0.7, delta=0.01)
        self.assertAlmostEqual(pt["size"] / 100 * 8192, 8000, delta=82)
        self.assertEqual(pt["spread"], 60)
        self.assertEqual(pt["target_preset"], "Selection")
        self.assertEqual(pt["target_selection"], [["lat", 1], ["lat", 0], ["contre", 0]])
        self.assertEqual(centres[id(self.projs[0])], (31000, 29000))

    def test_deux_mouvements_deux_couches(self):
        self.fx[id(self.projs[2])].effect = "balayage_v"
        layers, _ = self.win()._quick_move_layers()
        self.assertEqual(sorted(l["mouvement_shape"] for l in layers), ["cercle", "pendule"])

    def test_combine_avec_effet_lance(self):
        w = self.win()
        w.active_effect = "Lyre Gobo Spin"
        w.active_effect_config = {"name": "Lyre Gobo Spin", "layers": [{"attribute": "Gobo"}]}
        eff, _ = w._effect_for_rec()
        self.assertEqual([l["attribute"] for l in eff["layers"]], ["Gobo", "Pan/Tilt"])
        self.assertTrue(eff["quick_move"])
        self.assertEqual(w.active_effect_config["layers"], [{"attribute": "Gobo"}])  # copie

    def test_rien_ne_tourne(self):
        self.fx.clear()
        w = self.win()
        self.assertFalse(w._record_fx_pad(0, 0))
        self.assertTrue(w.errors)
        self.assertIsNone(w.fx_pads[0][0])

    def test_rec_pad_fx(self):
        w = self.win()
        self.assertTrue(w._record_fx_pad(2, 3))
        pad = w.fx_pads[2][3]
        self.assertEqual(pad["name"], "Mouvement 1")
        self.assertEqual({l["attribute"] for l in pad["layers"]}, {"Pan/Tilt"})
        # look des lyres allumées seulement, pas du PAR
        self.assertEqual(set(pad["start_look"]), {"lat|0", "lat|1", "contre|0"})
        self.assertEqual(pad["start_look"]["lat|0"],
                         {"level": 100, "color": "#ff00aa", "color_wheel": 12, "gobo": 40})
        self.assertEqual(self.saved[0]["name"], "Mouvement 1")
        # 2e REC : nom suivant
        w._record_fx_pad(2, 4)
        self.assertEqual(w.fx_pads[2][4]["name"], "Mouvement 2")

    def test_lancement_pose_le_look_et_coupe_l_effet_rapide(self):
        w = self.win()
        w._record_fx_pad(0, 0)
        cfg = w.fx_pads[0][0]
        for p in self.projs[:3]:
            p.gobo = 0; p.base_color = QColor("#000000"); p.pan = 1
        w._stop_quick_moves()
        w._apply_effect_start_look(cfg)
        self.assertEqual(len(w.plan_de_feu.stopped), 3)
        for p in self.projs[:3]:
            self.assertEqual((p.gobo, p.base_color.name(), p.pan), (40, "#ff00aa", 31000))


if __name__ == "__main__":
    unittest.main()
