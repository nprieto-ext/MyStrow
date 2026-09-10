"""Debattement pan/tilt reglable par fixture.

Remontee client (09/09/2026, dossier RENAUT) : « la 3D ne correspond pas a la
realite ». Le debattement etait ecrit EN DUR, et pas avec la meme valeur selon
l'endroit :

  - plan_3d_web.html  : 360 deg de pan  (`* Math.PI`)
  - effect_editor.py  : 540 deg de pan  (`PAN_ANGULAR_RATIO = 0.5`)

Sur une lyre 540 -- la grande majorite -- la 3D ne montrait donc qu'un demi-tour
la ou l'appareil en faisait un et demi.

Le debattement se lit desormais SUR LA FIXTURE (`pan_range` / `tilt_range`), et
les defauts reprennent ce que le moteur d'effets supposait deja : la sortie DMX
d'un show existant ne bouge pas d'un pas.
"""
import inspect
import io
import json
import math
import unittest

import core
from projector import Projector


def _lyre(pan_range=None, tilt_range=None):
    p = Projector('face', name='LYRE-1', fixture_type='Moving Head')
    if pan_range is not None:
        p.pan_range = pan_range
    if tilt_range is not None:
        p.tilt_range = tilt_range
    return p


class TestDefauts(unittest.TestCase):
    """Les defauts doivent laisser l'existant strictement inchange."""

    def test_une_lyre_neuve_est_en_540_270(self):
        self.assertEqual(core.pan_tilt_ranges(_lyre()), (540.0, 270.0))

    def test_le_ratio_par_defaut_vaut_l_ancienne_constante(self):
        # PAN_ANGULAR_RATIO valait 0.5 en dur : la sortie DMX des effets d'un
        # show existant doit rester identique au pas pres.
        self.assertEqual(core.pan_angular_ratio(_lyre()), 0.5)

    def test_le_tilt_reproduit_exactement_l_ancien_calcul_3d(self):
        # Ancien : theta = (dmx - 32768) / 32768 * pi * 0.75
        p = _lyre()
        for dmx in (0, 12345, 32768, 50000, 65535):
            _, tilt = core.pan_tilt_angles(p, dmx, dmx)
            ancien = (dmx - 32768) / 32768.0 * math.pi * 0.75
            self.assertAlmostEqual(tilt, ancien, places=12)


class TestConversion(unittest.TestCase):

    def test_32768_est_le_milieu_de_course(self):
        # 0 n'est pas « eteint » sur une lyre, c'est une butee. Le neutre est
        # au milieu, et c'est la que le faisceau descend a la verticale.
        pan, tilt = core.pan_tilt_angles(_lyre(), 32768, 32768)
        self.assertAlmostEqual(pan, 0.0, places=12)
        self.assertAlmostEqual(tilt, 0.0, places=12)

    def test_les_butees_couvrent_le_debattement_annonce(self):
        p = _lyre(540.0, 270.0)
        pan_bas,  tilt_bas  = core.pan_tilt_angles(p, 0, 0)
        pan_haut, tilt_haut = core.pan_tilt_angles(p, 65535, 65535)
        self.assertAlmostEqual(math.degrees(pan_haut - pan_bas),  540.0, places=1)
        self.assertAlmostEqual(math.degrees(tilt_haut - tilt_bas), 270.0, places=1)

    def test_une_lyre_360_180_balaie_moins(self):
        p = _lyre(360.0, 180.0)
        pan, tilt = core.pan_tilt_angles(p, 65535, 65535)
        self.assertAlmostEqual(math.degrees(pan),  180.0, places=1)
        self.assertAlmostEqual(math.degrees(tilt),  90.0, places=1)

    def test_le_ratio_rend_le_cercle_rond_sur_une_360(self):
        # A amplitude DMX egale, le pan couvre pan_range/tilt_range fois plus
        # d'angle : sur une 360/270 il faut 0,75 et non 0,5, sinon le cercle
        # sort aplati dans l'autre sens.
        self.assertAlmostEqual(core.pan_angular_ratio(_lyre(360.0, 270.0)), 0.75)
        self.assertAlmostEqual(core.pan_angular_ratio(_lyre(270.0, 270.0)), 1.0)


class TestGardeFous(unittest.TestCase):
    """Un debattement nul replierait tous les faisceaux sur la verticale."""

    def test_valeurs_absurdes_retombent_sur_le_defaut(self):
        for mauvais in (0, None, '', 'nawak', -540, 5, 5000):
            p = _lyre()
            p.pan_range = mauvais
            self.assertEqual(core.pan_tilt_ranges(p)[0], 540.0,
                             f"{mauvais!r} aurait du retomber sur le defaut")

    def test_attribut_absent_tolere(self):
        # Une fixture reconstruite a la main, ou un vieux pickle.
        class Nue:
            pass
        self.assertEqual(core.pan_tilt_ranges(Nue()), (540.0, 270.0))


class TestPersistance(unittest.TestCase):

    def test_le_debattement_survit_a_un_aller_retour_patch(self):
        import main_window as mw
        p = _lyre(360.0, 180.0)
        relu = Projector('face', fixture_type='Moving Head')
        mw._apply_pantilt_meta(relu, json.loads(json.dumps(mw._pantilt_meta(p))))
        self.assertEqual((relu.pan_range, relu.tilt_range), (360.0, 180.0))

    def test_un_patch_anterieur_garde_les_defauts(self):
        # Les cles n'existent pas dans le fichier : la lyre ne doit pas se
        # retrouver avec un debattement nul.
        import main_window as mw
        p = Projector('face', fixture_type='Moving Head')
        mw._apply_pantilt_meta(p, {'pan_min': 0, 'pan_max': 65535})
        self.assertEqual((p.pan_range, p.tilt_range), (540.0, 270.0))

    def test_le_champ_est_dans_le_point_unique(self):
        # `_PANTILT_META_FIELDS` est ce qui donne d'un coup la sauvegarde du
        # patch, celle du show, le snapshot de la fenetre Patch et le Ctrl+Z.
        import main_window as mw
        for champ in ('pan_range', 'tilt_range'):
            self.assertIn(champ, mw._PANTILT_META_FIELDS)


class TestPariteAvecLa3D(unittest.TestCase):
    """Python et JavaScript doivent tirer le MEME angle.

    Le faisceau (`beamFloor`) et le corps (`updateScene`) sont deux calculs
    separes dans plan_3d_web.html : les laisser diverger fait partir le cone a
    cote de la lentille.
    """

    def setUp(self):
        with io.open('plan_3d_web.html', encoding='utf-8') as f:
            self.html = f.read()

    def test_le_helper_js_existe_et_sert_aux_deux_sites(self):
        self.assertIn('function ptAngles(p)', self.html)
        # 1 definition + 2 appels (faisceau et corps)
        self.assertEqual(self.html.count('ptAngles(p)'), 3)

    def test_plus_aucun_debattement_en_dur_dans_la_3d(self):
        self.assertNotIn('Math.PI * 0.75', self.html)
        self.assertNotIn('- 32768)  / 32768.0 * Math.PI', self.html)

    def test_le_js_calcule_le_meme_angle_que_python(self):
        def js(pan_deg, tilt_deg, pan, tilt):
            pd = pan_deg  if pan_deg  > 0 else 540.0
            td = tilt_deg if tilt_deg > 0 else 270.0
            return (-(pan - 32768) / 32768.0 * (pd / 2.0) * math.pi / 180.0,
                     (32768 - tilt) / 32768.0 * (td / 2.0) * math.pi / 180.0)

        for pr, tr in ((540, 270), (360, 180), (630, 270)):
            p = _lyre(float(pr), float(tr))
            for dmx in (0, 16384, 32768, 49152, 65535):
                py = core.pan_tilt_angles(p, dmx, dmx)
                jsv = js(pr, tr, dmx, dmx)
                # Le signe differe par convention de repere, pas l'ampleur.
                self.assertAlmostEqual(abs(py[0]), abs(jsv[0]), places=12)
                self.assertAlmostEqual(abs(py[1]), abs(jsv[1]), places=12)

    def test_la_3d_recoit_le_debattement(self):
        with io.open('plan_3d_webwindow.py', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'pan_range'", src)
        self.assertIn("'tilt_range'", src)
        self.assertIn('pan_tilt_ranges(p)', src)


class TestPariteApercuEtShow(unittest.TestCase):
    """L'apercu de l'editeur et le moteur du show lisent la meme fixture."""

    def test_les_deux_moteurs_appellent_le_helper(self):
        import effect_editor
        import main_window as mw
        apercu = inspect.getsource(effect_editor.EffectEditorDialog._compute_preview)
        show   = inspect.getsource(mw.MainWindow._update_effect_from_layers)
        for nom, src in (('apercu', apercu), ('show', show)):
            self.assertIn('pan_angular_ratio(proj)', src,
                          f"le {nom} est reste sur un ratio fige")

    def test_plus_de_ratio_fige_dans_les_moteurs(self):
        import effect_editor
        import main_window as mw
        apercu = inspect.getsource(effect_editor.EffectEditorDialog._compute_preview)
        show   = inspect.getsource(mw.MainWindow._update_effect_from_layers)
        self.assertNotIn('PAN_ANGULAR_RATIO', apercu)
        self.assertNotIn('_PAN_RATIO', show)


if __name__ == "__main__":
    unittest.main(verbosity=2)
