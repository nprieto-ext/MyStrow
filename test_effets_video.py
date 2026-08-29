"""
test_effets_video.py — Effets sur la sortie video (calque + dimmer + colonne VIDEO).

Six effets, tous de la meme famille : un calque de couleur uni pose par-dessus
la sortie, dont seule l'opacite varie. Aucun traitement par image, donc rien qui
vienne disputer le thread GUI au timer DMX 25 fps.

Ce que ces tests verrouillent :

  * la COMPOSITION effet + dimmer est exacte — le calque unique rend
    pixel pour pixel ce que rendraient deux calques empiles (c'est ce qui
    permet de repiquer la couleur telle quelle sur la dalle LED du plan 3D) ;
  * le fader d'une colonne VIDEO est un NIVEAU DE SORTIE, pas un niveau de
    projecteur : `_startup_faders_down()` et `_clear_akai_state()` ne doivent
    jamais le baisser, sinon l'ecran de la salle part au noir au lancement et a
    chaque CLEAR sans que rien ne l'explique (meme piege que la colonne FX) ;
  * les effets ne se SUPERPOSENT pas — armer le second desarme le premier ;
  * la coupure est un noir FRANC, qu'aucun effet ne vient eclaircir ;
  * un effet a opacite constante ARRETE son timer de repaint ;
  * un effet a UN COUP (coup de blanc, coup de noir) se desarme tout seul, et un
    nouvel appui le REDECLENCHE au lieu de l'eteindre ;
  * scene et widget sont EXCLUSIFS a poser le calque, sinon la couleur est
    melangee deux fois ;
  * le bouton EFFET clignote et porte le titre de l'effet arme.

    python test_effets_video.py
"""

import os
import sys
import time
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QPixmap

import main_window as mw
from i18n import tr

_app = QApplication.instance() or QApplication(sys.argv)


def _melange(valeur, couleur, alpha):
    """Reference : melanger une composante vers `couleur` a l'opacite `alpha`."""
    return valeur * (1.0 - alpha) + couleur * alpha


def _caler(w, fx, offset_ms):
    """Arme `fx` en le figeant a `offset_ms` de son debut.

    `video_fx_overlay_color` lit `time.time() - video_fx_start` : laisser
    `video_fx_start` a 0 mettrait l'effet a une phase ARBITRAIRE (l'heure Unix
    courante), ce qui rendrait tout test de strobe aleatoire.
    """
    w.video_fx = fx
    w.video_fx_start = time.time() - offset_ms / 1000.0
    return mw._video_fx_alpha(fx, offset_ms)[0]


class FauxFader:
    def __init__(self, value=0):
        self.value = value

    def update(self):
        pass


class FauxTimer:
    def __init__(self):
        self.actif = False

    def isActive(self):
        return self.actif

    def start(self):
        self.actif = True

    def stop(self):
        self.actif = False


class FauxWin:
    """MainWindow reduite aux methodes des effets video."""

    video_fx_overlay_color = mw.MainWindow.video_fx_overlay_color
    _apply_video_fx        = mw.MainWindow._apply_video_fx
    set_video_fx           = mw.MainWindow.set_video_fx
    toggle_video_fx        = mw.MainWindow.toggle_video_fx
    set_video_cut          = mw.MainWindow.set_video_cut
    toggle_video_cut       = mw.MainWindow.toggle_video_cut
    set_video_dimmer       = mw.MainWindow.set_video_dimmer
    set_proj_level         = mw.MainWindow.set_proj_level
    _sync_video_fader      = mw.MainWindow._sync_video_fader
    _video_columns         = mw.MainWindow._video_columns
    _video_pad_active      = mw.MainWindow._video_pad_active
    _video_pad_color       = mw.MainWindow._video_pad_color
    _activate_video_pad    = mw.MainWindow._activate_video_pad
    _startup_faders_down   = mw.MainWindow._startup_faders_down
    _clear_akai_state      = mw.MainWindow._clear_akai_state
    video_bpm              = mw.MainWindow.video_bpm
    _vfx_columns           = mw.MainWindow._vfx_columns
    _vfx_pad_key           = mw.MainWindow._vfx_pad_key
    _activate_vfx_pad      = mw.MainWindow._activate_vfx_pad
    _video_fx_pad_exists   = mw.MainWindow._video_fx_pad_exists
    _sync_vfx_fader        = mw.MainWindow._sync_vfx_fader
    set_video_fx_amplitude = mw.MainWindow.set_video_fx_amplitude
    _assign_vfx_pad        = mw.MainWindow._assign_vfx_pad

    def __init__(self, layout=None, vfx=False):
        # Le layout de l'utilisateur : colonne 0 typee VIDEO (ou VFX si demande),
        # le reste en groupes.
        tete = ({"type": "vfx", "label": "VFX"} if vfx
                else {"type": "video", "label": "VIDEO"})
        self._fader_map = layout or (
            [tete] + [{"type": "group", "group": g, "label": g} for g in "BCDEFGH"])
        self.faders = {i: FauxFader(0) for i in range(8)}
        self._muted_faders = set()

        self.video_fx        = None
        self.video_fx_start  = 0.0
        self.video_dimmer    = 100
        self.video_fx_amplitude = 100
        self.video_cut       = False
        self._tap_bpm        = 0.0
        self.live_engine     = None
        self.vfx_pads = [None] * 8
        if vfx:
            # Les pads VFX se garnissent A LA MAIN (clic droit) ; le decor du
            # test se les pose lui-meme.
            for r, cle in enumerate(mw._VIDEO_FX_ORDER[:8]):
                self.vfx_pads[r] = cle
        self._video_fx_timer = FauxTimer()
        self._video_fx_oneshot_guard = False
        self.video_output_window = None
        self.video_fx_preview    = None

        # Decor de _clear_akai_state
        self.projectors = []
        self.active_pads = {}
        self.active_memory_pads = {}
        self.effect_buttons = []
        self.fx_amplitudes = [100] * mw._FX_COL_MAX
        self.active_fx_pads = {}
        self._stacked_effects = []
        self.active_effect = None
        self.active_effect_config = {}
        self.effect_saved_colors = {}
        self.plan_de_feu = None
        self.fader_buttons = []
        self._mem_cue_idx = {}
        self._dur_timer = self._dur_progress_timer = FauxTimer()
        self._dur_paused_left = None
        self.journal = []

    # ── Le decor, neutralise ────────────────────────────────────────────────
    def _refresh_video_fx_btn(self):
        pass

    def _rebuild_video_pads_style(self):
        pass

    def _refresh_video_leds(self):
        pass

    def _style_vfx_pads(self):
        pass

    def _refresh_vfx_leds(self):
        pass

    def _save_akai_config_auto(self):
        pass

    def activate_default_white_pads(self, group_rows=None):
        pass

    def send_dmx_update(self):
        pass

    def _slot_groups(self, slot):
        return []

    def _sync_fx_fader(self, index, slot):
        return 100

    def _auto_blink_stop(self):
        pass

    def _sync_cue_play_button(self):
        pass

    def _log_message(self, texte, niveau="info"):
        self.journal.append((texte, niveau))


# ────────────────────────────────────────────────────────────────────────────
class TestComposition(unittest.TestCase):
    """Le calque unique doit rendre EXACTEMENT ce que rendraient deux calques."""

    def test_dimmer_seul_est_un_vrai_dimmer(self):
        w = FauxWin()
        w.video_dimmer = 40
        c = w.video_fx_overlay_color()
        # Melanger vers du noir a l'opacite a donne v x (1 - a) : a 40 % de
        # dimmer, il reste bien 40 % du signal.
        for src in (0, 128, 255):
            self.assertAlmostEqual(
                _melange(src, c.red(), c.alpha() / 255.0), src * 0.40, delta=1.0,
                msg="le dimmer video n'est pas multiplicatif")

    def test_dimmer_100_ne_pose_aucun_calque(self):
        w = FauxWin()
        self.assertEqual(w.video_fx_overlay_color().alpha(), 0,
                         "un calque est pose alors qu'il n'y a rien a faire")

    def test_effet_puis_dimmer_equivaut_a_deux_calques(self):
        w = FauxWin()
        alpha_fx = _caler(w, "pulse", mw._VFX_PULSE_MS / 2)   # crete de la pulsation
        w.video_dimmer = 60
        c = w.video_fx_overlay_color()
        for src in (0, 90, 200, 255):
            # Reference : d'abord l'effet, ENSUITE le dimmer.
            ref = _melange(_melange(src, 0, alpha_fx), 0, 0.40)
            got = _melange(src, c.red(), c.alpha() / 255.0)
            self.assertAlmostEqual(got, ref, delta=1.0,
                                   msg="composition effet + dimmer inexacte")

    def test_le_dimmer_passe_par_dessus_l_effet(self):
        """Baisser le fader doit assombrir un flash blanc, pas se faire recouvrir."""
        w = FauxWin()
        self.assertEqual(_caler(w, "strobe_white", 0), 1.0)   # phase haute : blanc plein
        w.video_dimmer = 0
        c = w.video_fx_overlay_color()
        self.assertEqual(c.alpha(), 255)
        self.assertEqual((c.red(), c.green(), c.blue()), (0, 0, 0),
                         "le fader a 0 laisse passer du blanc")


class TestCoupure(unittest.TestCase):

    def test_coupure_est_un_noir_franc(self):
        w = FauxWin()
        self.assertEqual(_caler(w, "strobe_white", 0), 1.0)   # phase haute : blanc plein
        w.video_cut = True
        c = w.video_fx_overlay_color()
        self.assertEqual((c.red(), c.green(), c.blue(), c.alpha()), (0, 0, 0, 255),
                         "un effet eclaircit la coupure video")

    def test_pad_coupure_bascule_dans_les_deux_sens(self):
        w = FauxWin()
        w._activate_video_pad("cut")
        self.assertTrue(w.video_cut)
        w._activate_video_pad("cut")
        self.assertFalse(w.video_cut)


class TestExclusivite(unittest.TestCase):
    """« Les effets ne peuvent pas se superposer, on reste dans le simple. »"""

    def test_armer_un_second_effet_desarme_le_premier(self):
        w = FauxWin(vfx=True)
        w._activate_vfx_pad(0)
        premier = w.video_fx
        w._activate_vfx_pad(1)
        self.assertNotEqual(w.video_fx, premier,
                            "deux effets video se superposent")

    def test_le_meme_pad_rappuye_eteint(self):
        w = FauxWin(vfx=True)
        w._activate_vfx_pad(0)             # strobe : pas un one-shot
        self.assertEqual(w.video_fx, "strobe")
        w._activate_vfx_pad(0)
        self.assertIsNone(w.video_fx)

    def test_pad_pas_d_effet(self):
        w = FauxWin()
        w.set_video_fx("pulse")
        w._activate_video_pad("none")
        self.assertIsNone(w.video_fx)
        self.assertTrue(w._video_pad_active("none"))


class TestFaderVideo(unittest.TestCase):
    """Meme piege que la colonne FX : ce fader n'est pas un niveau de projecteur."""

    def test_demarrage_ne_coupe_pas_la_video(self):
        w = FauxWin()
        w._startup_faders_down()
        self.assertEqual(w.video_dimmer, 100,
                         "le demarrage a mis la sortie video au noir")
        self.assertEqual(w.faders[0].value, 100,
                         "le fader VIDEO affiche 0 alors que la sortie est a 100")

    def test_clear_ne_coupe_pas_la_video(self):
        w = FauxWin()
        w._clear_akai_state()
        self.assertEqual(w.video_dimmer, 100,
                         "CLEAR a mis l'ecran de la salle au noir")

    def test_clear_desarme_l_effet_mais_pas_la_coupure(self):
        """Desarmer un effet ne peut pas assombrir ; retablir une coupure, si."""
        w = FauxWin()
        w.set_video_fx("strobe")
        w.set_video_cut(True)
        w.video_dimmer = 70
        w._clear_akai_state()
        self.assertIsNone(w.video_fx, "CLEAR laisse un strobe sur la sortie video")
        self.assertTrue(w.video_cut,
                        "CLEAR a renvoye de la video sur l'ecran de la salle")
        self.assertEqual(w.video_dimmer, 70,
                         "CLEAR a remonte le niveau de sortie video tout seul")

    def test_les_colonnes_de_groupe_restent_baissees(self):
        """La garantie a ne pas casser en echange : le reste descend bien a 0."""
        w = FauxWin()
        for i in range(1, 8):
            w.faders[i].value = 80
        w._startup_faders_down()
        for i in range(1, 8):
            self.assertEqual(w.faders[i].value, 0,
                             f"la colonne de groupe {i} n'est pas baissee au demarrage")

    def test_le_fader_pilote_le_dimmer(self):
        w = FauxWin()
        w.set_proj_level(0, 35)
        self.assertEqual(w.video_dimmer, 35)
        self.assertEqual(w.faders[0].value, 35)

    def test_baisser_soi_meme_le_fader_assombrit_bien(self):
        """L'exemption du demarrage ne doit pas rendre le fader inoperant."""
        w = FauxWin()
        w._startup_faders_down()
        w.set_proj_level(0, 0)
        self.assertEqual(w.video_dimmer, 0)
        self.assertEqual(w.video_fx_overlay_color().alpha(), 255,
                         "fader a 0 : la sortie video n'est pas noire")


class TestTimerRepaint(unittest.TestCase):
    """Un calque immobile ne doit pas etre redessine 40 fois par seconde."""

    def test_effet_fige_arreterait_le_timer(self):
        """Aucun des trois effets n'est fige, mais la mecanique doit tenir.

        Garde-fou pour le jour ou on rajoute une teinte ou un fondu : un calque
        d'opacite constante ne doit pas etre repeint 40 fois par seconde.
        """
        w = FauxWin()
        w.set_video_fx("strobe")
        self.assertTrue(w._video_fx_timer.isActive())
        w.video_fx = "un_effet_fige"    # _video_fx_alpha rend (0.0, False)
        w._apply_video_fx()
        self.assertFalse(w._video_fx_timer.isActive(),
                         "un calque immobile fait tourner le timer pour rien")

    def test_effet_anime_fait_tourner_le_timer(self):
        w = FauxWin()
        w.set_video_fx("strobe")
        self.assertTrue(w._video_fx_timer.isActive(),
                        "le strobe ne se rafraichit pas")

    def test_coupure_ne_fait_pas_tourner_le_timer(self):
        w = FauxWin()
        w.set_video_fx("strobe")
        w.set_video_cut(True)
        self.assertFalse(w._video_fx_timer.isActive(),
                         "un noir franc n'a rien a rafraichir")


class TestCourbes(unittest.TestCase):

    def test_le_strobe_a_deux_demi_periodes_egales(self):
        pas = [mw._video_fx_alpha("strobe", t)[0]
               for t in range(0, mw._VFX_STROBE_MS)]
        self.assertAlmostEqual(sum(pas) / len(pas), 0.5, delta=0.02,
                               msg="le rapport cyclique du strobe n'est pas 1/2")

    def test_la_pulsation_reste_dans_ses_bornes(self):
        vals = [mw._video_fx_alpha("pulse", t)[0]
                for t in range(0, mw._VFX_PULSE_MS, 10)]
        self.assertGreaterEqual(min(vals), 0.0)
        self.assertLessEqual(max(vals), mw._VFX_PULSE_MAX + 1e-9)
        self.assertAlmostEqual(min(vals), 0.0, delta=1e-6,
                               msg="la pulsation ne redescend jamais a l'image nue")

    def test_un_effet_inconnu_ne_pose_rien(self):
        self.assertEqual(mw._video_fx_alpha("nawak", 500), (0.0, False))

    def test_les_huit_lignes_de_la_colonne_sont_definies(self):
        self.assertEqual(len(mw._VIDEO_ROWS), 8)

    def test_les_huit_effets_tombent_sur_une_colonne(self):
        """C'est ce qui permet de pre-remplir une colonne VFX d'un coup."""
        self.assertEqual(len(mw._VIDEO_FX_ORDER), 8)
        self.assertEqual(set(mw._VIDEO_FX_ORDER), set(mw._VIDEO_FX))

    def test_la_colonne_video_garde_ses_deux_commandes(self):
        """Elle ne porte plus que couper et tout eteindre : les effets sont
        passes sur les colonnes VFX, ou ils sont assignables."""
        actions = [a for a, _g, _c in mw._VIDEO_ROWS if a is not None]
        self.assertEqual(actions, ["cut", "none"])

    def test_chaque_effet_a_une_couleur_de_calque(self):
        """Plus de couleur dynamique : tout effet doit porter la sienne."""
        for cle in mw._VIDEO_FX_ORDER:
            self.assertTrue(mw._VIDEO_FX[cle][1],
                            f"l'effet {cle} n'a pas de couleur de calque")


class TestWatermark(unittest.TestCase):
    """Un calque noir opaque ne doit PAS effacer le watermark de licence."""

    def test_le_watermark_reste_au_dessus_du_calque(self):
        from PySide6.QtGui import QPixmap

        win = mw.VideoOutputWindow()
        win.set_watermark(True)
        # Le vrai logo (Mystrow_blanc.png) n'est plus dans le depot : on en pose
        # un faux, ce qu'on teste ici etant l'ORDRE D'EMPILEMENT.
        px = QPixmap(200, 60)
        px.fill(QColor(255, 255, 255, 102))
        win._watermark.setPixmap(px)
        win._create_watermark_pixmap = lambda: None
        win.setGeometry(0, 0, 960, 540)
        win.show()
        _app.processEvents()
        win.stack.setCurrentIndex(win.PAGE_BLACK)
        _app.processEvents()

        def lum_max():
            img = win.grab().toImage()
            g = win._watermark.geometry()
            best = 0
            for y in range(max(0, g.top()), min(img.height(), g.bottom()), 2):
                for x in range(max(0, g.left()), min(img.width(), g.right()), 2):
                    best = max(best, QColor(img.pixel(x, y)).lightness())
            return best

        nu = lum_max()
        self.assertGreater(nu, 0, "le decor du test ne montre meme pas le watermark")
        win.set_fx_overlay(QColor(0, 0, 0, 255))
        _app.processEvents()
        self.assertEqual(lum_max(), nu,
                         "un calque noir opaque efface le watermark de licence")
        win.close()


class TestLesCoups(unittest.TestCase):
    """Un coup se tape sur un temps fort : il retombe et se retire tout seul."""

    def test_part_a_fond_et_retombe_a_zero(self):
        self.assertEqual(mw._video_fx_alpha("hit_white", 0)[0], 1.0)
        self.assertEqual(mw._video_fx_alpha("hit_white", mw._VFX_HIT_MS)[0], 0.0)

    def test_la_retombee_est_rapide_au_debut(self):
        """Une decroissance lineaire donne un flash mou : au quart du temps,
        il doit rester nettement moins que les trois quarts."""
        quart = mw._video_fx_alpha("hit_white", mw._VFX_HIT_MS // 4)[0]
        self.assertLess(quart, 0.70)

    def test_ne_reste_jamais_arme_une_fois_retombe(self):
        w = FauxWin()
        w.set_video_fx("hit_white")
        self.assertEqual(w.video_fx, "hit_white")
        w.video_fx_start = time.time() - (mw._VFX_HIT_MS + 50) / 1000.0
        w._apply_video_fx()
        self.assertIsNone(w.video_fx,
                          "le pad reste allume sur un coup qui ne fait plus rien")
        self.assertFalse(w._video_fx_timer.isActive())

    def test_deux_appuis_rapproches_donnent_deux_coups(self):
        """Sur un one-shot, le pad REDECLENCHE au lieu d'eteindre."""
        w = FauxWin()
        w.toggle_video_fx("hit_white")
        premier = w.video_fx_start
        time.sleep(0.01)
        w.toggle_video_fx("hit_white")          # bien avant la fin de la retombee
        self.assertEqual(w.video_fx, "hit_white",
                         "le second appui a annule le coup au lieu de le rejouer")
        self.assertGreater(w.video_fx_start, premier,
                           "le second coup n'est pas reparti de zero")

    def test_le_desarmement_auto_ne_boucle_pas(self):
        """set_video_fx rappelle _apply_video_fx : la garde doit tenir."""
        w = FauxWin()
        w.set_video_fx("hit_white")
        w.video_fx_start = time.time() - (mw._VFX_HIT_MS + 50) / 1000.0
        w._apply_video_fx()                 # ne doit pas partir en recursion
        self.assertFalse(w._video_fx_oneshot_guard)


class TestStrobeAleatoire(unittest.TestCase):

    def test_est_deterministe(self):
        """La sortie et la dalle 3D interrogent la courbe SEPAREMENT : deux
        appels au meme instant doivent donner la meme reponse."""
        for t in (0, 37, 128, 999, 5000):
            self.assertEqual(mw._video_fx_alpha("strobe_rand", t),
                             mw._video_fx_alpha("strobe_rand", t),
                             "le strobe aleatoire desynchroniserait sortie et 3D")

    def test_n_est_pas_periodique_comme_le_strobe_regulier(self):
        pas = [mw._video_fx_alpha("strobe_rand", t)[0]
               for t in range(0, 4000, mw._VFX_RAND_MS)]
        regulier = [mw._video_fx_alpha("strobe", t)[0]
                    for t in range(0, 4000, mw._VFX_RAND_MS)]
        self.assertNotEqual(pas, regulier)
        # Et il ne doit pas rester bloque sur une seule valeur
        self.assertIn(0.0, pas)
        self.assertIn(1.0, pas)

    def test_le_rapport_cyclique_tient_la_consigne(self):
        pas = [mw._video_fx_alpha("strobe_rand", t)[0]
               for t in range(0, 60000, mw._VFX_RAND_MS)]
        part = sum(pas) / len(pas)
        self.assertAlmostEqual(part, mw._VFX_RAND_DUTY / 100.0, delta=0.06,
                               msg="le strobe aleatoire n'allume pas la part prevue")

    def test_les_pas_durent_bien_leur_duree(self):
        """Deux instants du meme pas donnent la meme valeur."""
        for base in (0, 450, 3000):
            a = mw._video_fx_alpha("strobe_rand", base)[0]
            b = mw._video_fx_alpha("strobe_rand", base + mw._VFX_RAND_MS - 1)[0]
            self.assertEqual(a, b)


class TestCoupDeNoirEtDeBlanc(unittest.TestCase):
    """Meme courbe, meme mecanique : seule la COULEUR du calque differe."""

    def test_meme_courbe_de_retombee(self):
        for t in (0, 40, 130, 259, 260, 400):
            self.assertEqual(mw._video_fx_alpha("hit_white", t),
                             mw._video_fx_alpha("hit_black", t))

    def test_les_deux_sont_a_un_coup(self):
        self.assertIn("hit_white", mw._VFX_ONESHOT)
        self.assertIn("hit_black", mw._VFX_ONESHOT)

    def test_le_coup_de_blanc_va_vers_le_blanc(self):
        w = FauxWin()
        _caler(w, "hit_white", 0)
        c = w.video_fx_overlay_color()
        self.assertEqual((c.red(), c.green(), c.blue()), (255, 255, 255))

    def test_le_coup_de_noir_va_vers_le_noir(self):
        w = FauxWin()
        _caler(w, "hit_black", 0)
        c = w.video_fx_overlay_color()
        self.assertEqual((c.red(), c.green(), c.blue()), (0, 0, 0))
        self.assertEqual(c.alpha(), 255, "le coup de noir n'est pas un noir plein")

    def test_le_coup_de_noir_se_desarme_aussi(self):
        w = FauxWin()
        w.set_video_fx("hit_black")
        w.video_fx_start = time.time() - (mw._VFX_HIT_MS + 50) / 1000.0
        w._apply_video_fx()
        self.assertIsNone(w.video_fx)


class TestBoutonEffet(unittest.TestCase):
    """Le bouton EFFET clignote au titre de l'effet arme."""

    def _fen(self):
        from PySide6.QtWidgets import QPushButton
        w = FauxWin()
        w.video_fx_btn = QPushButton("EFFET")
        w._video_fx_blink_on = False
        w._video_fx_blink_timer = FauxTimer()
        w._refresh_video_fx_btn = types.MethodType(
            mw.MainWindow._refresh_video_fx_btn, w)
        w._video_fx_btn_font = types.MethodType(
            mw.MainWindow._video_fx_btn_font, w)
        w._video_fx_blink_tick = types.MethodType(
            mw.MainWindow._video_fx_blink_tick, w)
        return w

    def test_au_repos_le_bouton_dit_effet(self):
        w = self._fen()
        w._refresh_video_fx_btn()
        self.assertEqual(w.video_fx_btn.text(), tr("vfx_button"))
        self.assertFalse(w._video_fx_blink_timer.isActive(),
                         "le bouton clignote alors qu'aucun effet n'est arme")

    def test_arme_le_bouton_porte_le_titre(self):
        w = self._fen()
        w.set_video_fx("pulse")
        self.assertEqual(w.video_fx_btn.text(), tr("vfx_pulse"))
        self.assertTrue(w._video_fx_blink_timer.isActive())

    def test_le_titre_long_est_elide_pas_deborde(self):
        w = self._fen()
        w.set_video_fx("strobe_rand")
        self.assertLessEqual(w.video_fx_btn.width(), mw._VFX_BTN_W_MAX,
                             "le bouton pousse le bouton VIDEO hors du cadre")
        # Elide ou non, le titre complet reste lisible en tooltip.
        self.assertEqual(w.video_fx_btn.toolTip(), tr("vfx_strobe_rand"))

    def test_le_clignotement_alterne_deux_apparences(self):
        w = self._fen()
        w.set_video_fx("strobe")
        avant = w.video_fx_btn.styleSheet()
        w._video_fx_blink_tick()
        self.assertNotEqual(w.video_fx_btn.styleSheet(), avant,
                            "les deux phases du clignotement sont identiques")
        w._video_fx_blink_tick()
        self.assertEqual(w.video_fx_btn.styleSheet(), avant)

    def test_desarmer_arrete_le_clignotement(self):
        w = self._fen()
        w.set_video_fx("strobe")
        w.set_video_fx(None)
        self.assertFalse(w._video_fx_blink_timer.isActive())
        self.assertEqual(w.video_fx_btn.text(), tr("vfx_button"))
        self.assertEqual(w.video_fx_btn.width(), mw._VFX_BTN_W_MIN)


class TestColonneVFX(unittest.TestCase):
    """Pads d'effets ASSIGNABLES : c'est ce qui leve la limite de huit."""

    def test_une_colonne_neuve_est_vide(self):
        """Comme une colonne FX, memoire ou groupe : rien n'est pose d'office,
        la colonne appartient a l'utilisateur."""
        w = FauxWin()
        self.assertTrue(all(k is None for k in w.vfx_pads),
                        "une colonne VFX arrive pre-remplie")

    def test_il_n_y_a_qu_une_seule_colonne_vfx(self):
        """Un seul effet video est actif a la fois et l'amplitude est globale :
        des colonnes VFX indexees auraient pilote le meme etat."""
        self.assertIn("VFX", mw._AKAI_SLOT_OPTIONS)
        self.assertNotIn("VFX 1", mw._AKAI_SLOT_OPTIONS)
        self.assertFalse(hasattr(mw, "_VFX_COL_MAX"))

    def test_assigner_un_pad_le_retient(self):
        w = FauxWin(vfx=True)
        w._assign_vfx_pad(3, "burst")
        self.assertEqual(w._vfx_pad_key(3), "burst")

    def test_un_pad_arme_son_effet(self):
        w = FauxWin(vfx=True)
        w.vfx_pads[2] = "burst"
        w._activate_vfx_pad(2)
        self.assertEqual(w.video_fx, "burst")

    def test_un_pad_vide_est_inerte(self):
        w = FauxWin(vfx=True)
        w.vfx_pads[4] = None
        w.set_video_fx("strobe")
        w._activate_vfx_pad(4)
        self.assertEqual(w.video_fx, "strobe")

    def test_un_effet_inconnu_sur_un_pad_est_ignore(self):
        """Un effet retire d'une version a l'autre ne doit pas laisser un pad
        qui pointe dans le vide."""
        w = FauxWin(vfx=True)
        w.vfx_pads[0] = "effet_dune_ancienne_version"
        self.assertIsNone(w._vfx_pad_key(0))
        w._activate_vfx_pad(0)
        self.assertIsNone(w.video_fx)

    def test_vider_le_pad_du_seul_effet_arme_le_desarme(self):
        """Sinon l'effet tourne sans plus aucun pad pour l'eteindre."""
        w = FauxWin(vfx=True)
        for r in range(1, 8):               # une seule case occupee
            w.vfx_pads[r] = None
        w.vfx_pads[0] = "strobe"
        w._activate_vfx_pad(0)
        self.assertEqual(w.video_fx, "strobe")
        w._assign_vfx_pad(0, None)
        self.assertIsNone(w.video_fx, "l'effet reste arme sans pad pour l'eteindre")

    def test_une_colonne_video_suffit_a_garder_la_main(self):
        """Elle porte « pas d'effet », qui eteint n'importe quel effet."""
        w = FauxWin(vfx=True)
        w._fader_map[1] = {"type": "video", "label": "VIDEO"}
        w.vfx_pads[0] = "strobe"
        w.set_video_fx("strobe")
        w._assign_vfx_pad(0, None)
        self.assertEqual(w.video_fx, "strobe",
                         "desarme alors que la colonne VIDEO pouvait l'eteindre")


class TestAmplitudeVFX(unittest.TestCase):
    """Le fader d'une colonne VFX : troisieme occurrence du piege FX/VIDEO."""

    def test_demarrage_ne_rend_pas_la_colonne_muette(self):
        w = FauxWin(vfx=True)
        w._startup_faders_down()
        self.assertEqual(w.video_fx_amplitude, 100,
                         "le demarrage a mis l'amplitude d'effet a 0")
        self.assertEqual(w.faders[0].value, 100)

    def test_clear_ne_rend_pas_la_colonne_muette(self):
        w = FauxWin(vfx=True)
        w._clear_akai_state()
        self.assertEqual(w.video_fx_amplitude, 100)

    def test_l_amplitude_attenue_l_effet(self):
        w = FauxWin(vfx=True)
        _caler(w, "strobe_white", 0)         # phase haute : blanc plein
        self.assertEqual(w.video_fx_overlay_color().alpha(), 255)
        w.set_video_fx_amplitude(40)
        self.assertEqual(w.video_fx_overlay_color().alpha(), 102)

    def test_l_amplitude_n_agit_pas_sur_le_dimmer(self):
        """Baisser l'amplitude adoucit l'effet, ca n'eteint pas la video."""
        w = FauxWin(vfx=True)
        w.video_dimmer = 50
        w.set_video_fx_amplitude(0)
        self.assertEqual(w.video_fx_overlay_color().alpha(), 128)

    def test_baisser_soi_meme_le_fader_agit_bien(self):
        w = FauxWin(vfx=True)
        w._startup_faders_down()
        w.set_proj_level(0, 0)
        self.assertEqual(w.video_fx_amplitude, 0)


class TestStrobeAuTempo(unittest.TestCase):

    def test_la_periode_suit_le_bpm(self):
        """Un eclat par temps : a 120 BPM, un cycle fait 500 ms."""
        alpha = lambda t, b: mw._video_fx_alpha("strobe_bpm", t, b)[0]
        self.assertEqual(alpha(0, 120), 1.0)
        self.assertEqual(alpha(499, 120), 0.0)
        self.assertEqual(alpha(500, 120), 1.0)      # temps suivant
        # A 60 BPM le cycle double
        self.assertEqual(alpha(999, 60), 0.0)
        self.assertEqual(alpha(1000, 60), 1.0)

    def test_l_eclat_est_plus_court_que_le_silence(self):
        """Un carre 50/50 se lit comme un clignotement lent, pas comme un coup."""
        pas = [mw._video_fx_alpha("strobe_bpm", t, 120)[0] for t in range(0, 500)]
        self.assertAlmostEqual(sum(pas) / len(pas), mw._VFX_BPM_DUTY, delta=0.02)

    def test_un_bpm_absurde_est_borne(self):
        for b in (0, -5, 5, 10000, None):
            try:
                a, anime = mw._video_fx_alpha("strobe_bpm", 10, b or 0)
            except (TypeError, ValueError):
                self.fail(f"BPM {b} fait planter la courbe")
            self.assertIn(a, (0.0, 1.0))
            self.assertTrue(anime)

    def test_le_repli_quand_aucun_tempo_n_est_connu(self):
        w = FauxWin()
        self.assertEqual(w.video_bpm(), mw._VFX_BPM_DEFAUT)

    def test_le_tap_manuel_est_utilise(self):
        w = FauxWin()
        w._tap_bpm = 128.0
        self.assertEqual(w.video_bpm(), 128.0)

    def test_le_moteur_live_a_la_priorite_sur_le_tap(self):
        w = FauxWin()
        w._tap_bpm = 128.0
        w.live_engine = type("M", (), {"_bpm": 140.0})()
        self.assertEqual(w.video_bpm(), 140.0)

    def test_un_moteur_live_muet_ne_masque_pas_le_tap(self):
        w = FauxWin()
        w._tap_bpm = 128.0
        w.live_engine = type("M", (), {"_bpm": 0.0})()
        self.assertEqual(w.video_bpm(), 128.0)


class TestRafale(unittest.TestCase):

    def test_trois_coups_puis_le_silence(self):
        coups = 0
        precedent = 0.0
        for t in range(0, mw._VFX_BURST_MS):
            a = mw._video_fx_alpha("burst", t)[0]
            if a > 0 and precedent == 0.0:
                coups += 1
            precedent = a
        self.assertEqual(coups, mw._VFX_BURST_N)

    def test_le_silence_occupe_la_majeure_partie_du_cycle(self):
        pas = [mw._video_fx_alpha("burst", t)[0]
               for t in range(0, mw._VFX_BURST_MS)]
        self.assertLess(sum(pas) / len(pas), 0.25,
                        "la rafale ne respire pas, c'est un strobe")

    def test_le_cycle_se_repete(self):
        for t in (0, 40, 115, 300):
            self.assertEqual(mw._video_fx_alpha("burst", t),
                             mw._video_fx_alpha("burst", t + mw._VFX_BURST_MS))


class TestPopupDeSlot(unittest.TestCase):
    """Le popup qui s'ouvre sous l'etiquette du fader liste ses sections EN DUR.

    Ajouter une entree a `_AKAI_SLOT_OPTIONS` ne suffit donc PAS a la rendre
    assignable : le gros editeur de layout la voit, ce popup non — alors que
    c'est le chemin normal. VIDEO et VFX etaient dans ce cas.
    """

    def _popup(self, current="A"):
        return mw._SlotPickerPopup(mw._AKAI_SLOT_OPTIONS, current)

    def _entrees(self, popup):
        return [item for item, _btn, _lbl in popup._all_btns]

    def test_video_est_proposable_dans_le_popup(self):
        pop = self._popup()
        self.assertIn("VIDEO", self._entrees(pop))
        pop.close()

    def test_la_colonne_vfx_est_proposable_dans_le_popup(self):
        pop = self._popup()
        self.assertIn("VFX", self._entrees(pop))
        pop.close()

    def test_le_popup_couvre_tout_ce_que_l_editeur_propose(self):
        """La garantie qui empeche le trou de revenir : les deux chemins
        d'assignation doivent offrir les memes colonnes."""
        pop = self._popup()
        entrees = set(self._entrees(pop))
        manquants = [o for o in mw._AKAI_SLOT_OPTIONS if o not in entrees]
        self.assertEqual(manquants, [],
                         "assignable dans l'editeur de layout mais absent du popup")
        pop.close()


class TestPorteursDuCalque(unittest.TestCase):
    """Scene (page video) et widget (pages image/noir) sont EXCLUSIFS.

    Les laisser agir tous les deux melange la couleur deux fois : mesure sur
    une vraie video, un dimmer a 30 % rendait 9 % (0,3 x 0,3).
    """

    def _fenetre(self):
        win = mw.VideoOutputWindow()
        win.setGeometry(0, 0, 640, 360)
        win.show()
        _app.processEvents()
        return win

    def test_page_video_le_widget_se_retire(self):
        win = self._fenetre()
        if not isinstance(win.video_widget, mw.VideoSurface):
            self.skipTest("Qt Multimedia Widgets absent")
        win.show_video()
        _app.processEvents()
        win.set_fx_overlay(QColor(0, 0, 0, 180))
        self.assertEqual(win.video_widget.fx_color().alpha(), 180,
                         "la scene ne porte pas le calque sur la page video")
        self.assertEqual(win.fx_overlay.color().alpha(), 0,
                         "le widget double le calque de la scene")
        win.close()

    def test_page_image_le_widget_reprend(self):
        win = self._fenetre()
        win.show_image(QPixmap(4, 4))
        _app.processEvents()
        win.set_fx_overlay(QColor(0, 0, 0, 180))
        self.assertEqual(win.fx_overlay.color().alpha(), 180,
                         "une photo echappe au dimmer et aux effets")
        win.close()

    def test_changer_de_page_repose_le_calque(self):
        """Sans ca, passer sur une photo laissait l'effet derriere soi."""
        win = self._fenetre()
        if not isinstance(win.video_widget, mw.VideoSurface):
            self.skipTest("Qt Multimedia Widgets absent")
        win.show_video()
        _app.processEvents()
        win.set_fx_overlay(QColor(0, 0, 0, 180))
        win.show_image(QPixmap(4, 4))       # currentChanged -> re-pose
        _app.processEvents()
        self.assertEqual(win.fx_overlay.color().alpha(), 180)
        self.assertEqual(win.video_widget.fx_color().alpha(), 180)
        win.close()


class TestSlotVideo(unittest.TestCase):

    def test_video_est_proposable_comme_colonne(self):
        self.assertIn("VIDEO", mw._AKAI_SLOT_OPTIONS)

    def test_l_etiquette_est_abregee(self):
        # 28 px de large, 9 px de fonte : « VIDEO » deborde, « VID » non.
        self.assertEqual(mw._fader_label_text("VIDEO"), "VID")
        self.assertTrue(mw._fader_label_tooltip({"type": "video", "label": "VIDEO"}),
                        "l'etiquette abregee n'a pas de tooltip pour la rattraper")

    def test_les_lignes_libres_ne_declenchent_rien(self):
        """Un pad vide (action None) doit etre inerte, pas planter."""
        w = FauxWin()
        w.set_video_fx("strobe")
        w._activate_video_pad(None)
        self.assertEqual(w.video_fx, "strobe")
        self.assertFalse(w._video_pad_active(None))

    def test_vfx_est_proposable_comme_colonne(self):
        self.assertIn("VFX", mw._AKAI_SLOT_OPTIONS)

    def test_l_etiquette_vfx_tient_telle_quelle(self):
        # 3 caracteres : pas besoin d'abreger comme « VIDEO » -> « VID ».
        self.assertEqual(mw._fader_label_text("VFX"), "VFX")


if __name__ == "__main__":
    unittest.main(verbosity=2)
