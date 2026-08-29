"""
test_flash_bouton.py — Le bouton bas-droite du controleur gagne FLASH / FLASH KILL.

Il n'avait que deux fonctions, choisies par une case a cocher : TAP BPM, ou GO.
Il en a maintenant quatre, choisies dans « Configuration du controleur » :

  * TAP BPM     — inchange, tape en rythme pour regler la vitesse des effets ;
  * GO          — inchange, avance a la memoire suivante ;
  * FLASH       — momentane : tenu, toutes les memoires actives passent a 100 % ;
  * FLASH KILL  — momentane : tenu, toutes les memoires actives sont coupees.

Les deux momentanes ne touchent AUCUN fader : ils forcent le niveau lu par
`_recompute_memory_mix`. Le relacher n'a donc rien a restaurer — un simple
recalcul rend, au bit pres, l'etat d'avant. C'est ce que ce test verifie :
l'aller ET le retour.

    python test_flash_bouton.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)


class FauxFader:
    def __init__(self, value=0):
        self.value = value


class _TimerMuet:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def isActive(self):
        return self.started


class FauxProjecteur:
    def __init__(self):
        self.dmx_profile = ["R", "G", "B"]
        self.level = 0
        self.base_color = QColor("black")
        self.color = QColor("black")
        self.pan = self.tilt = 32768


class FauxWin:
    """MainWindow reduite au bouton bas-droite et au mix des memoires."""

    _flash_level           = mw.MainWindow._flash_level
    _flash_begin           = mw.MainWindow._flash_begin
    _flash_end             = mw.MainWindow._flash_end
    _tap_tempo             = mw.MainWindow._tap_tempo
    _tap_tempo_released    = mw.MainWindow._tap_tempo_released
    _recompute_memory_mix  = mw.MainWindow._recompute_memory_mix
    _flash_has_memories    = mw.MainWindow._flash_has_memories
    _mem_ensure_cues       = mw.MainWindow._mem_ensure_cues
    _mem_active_cue        = mw.MainWindow._mem_active_cue
    go_mode                = mw.MainWindow.go_mode
    _TAP_BTN_LOOK          = mw.MainWindow._TAP_BTN_LOOK

    def __init__(self, n_proj=2):
        self.tap_button_mode = "flash"
        self._flash_kind = None
        self._flash_had_memories = False
        self._flash_watchdog = _TimerMuet()
        self._fade_timer = _TimerMuet()

        # Colonne 0 = memoire 0, le reste en groupes.
        self._fader_map = [{"type": "memory", "mem_col": 0, "label": "MEM 1"}] + \
                          [{"type": "group", "group": g, "label": g} for g in "BCDEFGH"]
        self.faders = {i: FauxFader(0) for i in range(9)}
        self._muted_faders = set()
        self._mem_ext_levels = {}
        self._mem_rows = {}
        self._mem_cue_idx = {}
        self.projectors = [FauxProjecteur() for _ in range(n_proj)]
        self.active_effect = None
        self.active_effect_config = {}

        # Une seule memoire enregistree : MEM 1.1, deux projos en rouge plein.
        self.memories = [[None] * 8 for _ in range(8)]
        self.memories[0][0] = {
            "cues": [{
                "label": "Cue 1",
                "projectors": [{"level": 100, "base_color": "#ff0000"}
                               for _ in range(n_proj)],
                "effect": {},
                "duration": 0,
            }],
            "loop": True,
        }
        self.active_memory_pads = {}
        self.logs = []
        self.dmx_envois = 0

    # ── Dependances neutralisees ────────────────────────────────────────────
    def _fader_to_mem_col(self, fader_idx):
        slot = self._fader_map[fader_idx] if fader_idx < len(self._fader_map) else {}
        return slot.get("mem_col") if slot.get("type") == "memory" else None

    def _update_color_wheel(self, p, color):
        pass

    def _update_tap_go_btn_style(self):
        pass

    def _log_message(self, text, level="info"):
        self.logs.append((level, text))

    def send_dmx_update(self):
        self.dmx_envois += 1

    def stop_effect(self):
        pass

    def start_effect(self, name):
        pass

    def _go_advance(self):
        self.logs.append(("go", "GO"))

    # ── Aides de lecture ────────────────────────────────────────────────────
    def niveaux(self):
        return [p.level for p in self.projectors]


class ModeDuBouton(unittest.TestCase):
    """Le mode configure decide de ce que fait l'appui."""

    def test_go_reste_du_go(self):
        w = FauxWin()
        w.tap_button_mode = "go"
        w._tap_tempo()
        self.assertIn(("go", "GO"), w.logs)
        self.assertIsNone(w._flash_kind)

    def test_go_mode_reste_lisible(self):
        """L'ancien attribut booleen `go_mode` continue de repondre."""
        w = FauxWin()
        w.tap_button_mode = "go"
        self.assertTrue(w.go_mode)
        for autre in ("bpm", "flash", "flash_kill"):
            w.tap_button_mode = autre
            self.assertFalse(w.go_mode, autre)

    def test_bpm_ne_declenche_aucun_flash(self):
        w = FauxWin()
        w.tap_button_mode = "bpm"
        w._flash_begin = lambda: self.fail("le mode BPM ne doit pas flasher")
        # Le corps TAP BPM touche des widgets absents ici : seule compte
        # l'absence de flash, verifiee par le garde ci-dessus.
        try:
            w._tap_tempo()
        except AttributeError:
            pass
        self.assertIsNone(w._flash_kind)


class FlashPleinFeu(unittest.TestCase):
    """FLASH : les memoires actives montent a 100 %, puis retombent."""

    def setUp(self):
        self.w = FauxWin()
        self.w.tap_button_mode = "flash"
        self.w.active_memory_pads = {0: 0}      # MEM 1.1 posee
        self.w.faders[0].value = 30             # ... mais fader a 30 %
        self.w._recompute_memory_mix()
        # Niveau de reference : le melange additif arrondit (30 % -> 29), on
        # compare donc a l'etat reellement rendu, pas a la valeur du fader.
        self.avant = self.w.niveaux()

    def test_avant_le_flash(self):
        self.assertTrue(0 < self.avant[0] < 100, self.avant)

    def test_pendant_le_flash(self):
        self.w._tap_tempo()
        self.assertEqual(self.w._flash_kind, "full")
        self.assertEqual(self.w.niveaux(), [100, 100])

    def test_le_fader_nest_pas_touche(self):
        self.w._tap_tempo()
        self.assertEqual(self.w.faders[0].value, 30,
                         "le flash ne doit deplacer aucun fader")

    def test_apres_le_relacher(self):
        self.w._tap_tempo()
        self.w._tap_tempo_released()
        self.assertIsNone(self.w._flash_kind)
        self.assertEqual(self.w.niveaux(), self.avant)

    def test_memoire_a_zero_remonte_puis_redescend(self):
        """Fader a 0 : rien n'etait envoye ; le flash l'allume, le relacher l'eteint."""
        self.w.faders[0].value = 0
        self.w._recompute_memory_mix()
        self.assertEqual(self.w.niveaux(), [0, 0])
        self.w._tap_tempo()
        self.assertEqual(self.w.niveaux(), [100, 100])
        self.w._tap_tempo_released()
        self.assertEqual(self.w.niveaux(), [0, 0])

    def test_sans_memoire_active_rien_ne_sallume(self):
        self.w.active_memory_pads = {}
        self.w._recompute_memory_mix()
        self.w._tap_tempo()
        self.assertEqual(self.w.niveaux(), [0, 0])

    def test_colonne_mutee_reste_mutee(self):
        """Un mute est deliberé : le flash ne le contourne pas."""
        self.w._muted_faders.add(0)
        self.w._recompute_memory_mix()
        self.w._tap_tempo()
        self.assertEqual(self.w.niveaux(), [0, 0])


class FlashKill(unittest.TestCase):
    """FLASH KILL : les memoires actives sont coupees, puis revenues."""

    def setUp(self):
        self.w = FauxWin()
        self.w.tap_button_mode = "flash_kill"
        self.w.active_memory_pads = {0: 0}
        self.w.faders[0].value = 70
        self.w._recompute_memory_mix()
        self.avant = self.w.niveaux()

    def test_avant_le_kill(self):
        self.assertTrue(0 < self.avant[0] < 100, self.avant)

    def test_pendant_le_kill(self):
        """Tenir KILL s'arme, mais ne coupe RIEN — ni modele, ni niveau lu.

        La coupure est un SOLO : elle est decidee a l'appui d'un pad couleur et
        appliquee par PROJECTEUR, le temps d'une frame, juste avant l'envoi
        (test_flash_kill_reel.py, classe PorteDuSolo).
        """
        self.w._tap_tempo()
        self.assertEqual(self.w._flash_kind, "kill")
        self.assertEqual(self.w.niveaux(), self.avant,
                         "le bouton KILL seul a coupe quelque chose")
        self.assertEqual(self.w._flash_level(70), 70,
                         "le niveau lu ne doit plus dependre du KILL")

    def test_apres_le_relacher(self):
        self.w._tap_tempo()
        self.w._tap_tempo_released()
        self.assertEqual(self.w.niveaux(), self.avant)
        self.assertEqual(self.w.faders[0].value, 70)

    def test_couleur_rendue_a_lidentique(self):
        avant = [(p.level, p.base_color.name(), p.color.name())
                 for p in self.w.projectors]
        self.w._tap_tempo()
        self.w._tap_tempo_released()
        apres = [(p.level, p.base_color.name(), p.color.name())
                 for p in self.w.projectors]
        self.assertEqual(avant, apres)


class NiveauxDuPupitre(unittest.TestCase):
    """Les memoires tenues par l'entree DMX hors page suivent le flash aussi."""

    def setUp(self):
        self.w = FauxWin()
        # La colonne 0 affiche la memoire 0 ; la memoire 1 n'est sur aucune page.
        self.w.memories[1][2] = {
            "cues": [{"label": "Cue 1",
                      "projectors": [{"level": 100, "base_color": "#0000ff"}
                                     for _ in range(2)],
                      "effect": {}, "duration": 0}],
            "loop": True,
        }
        self.w._mem_rows = {1: 2}
        self.w._mem_ext_levels = {1: 40}

    def test_kill_ne_touche_pas_au_pupitre(self):
        """Le KILL ne passe plus par `_flash_level` : il ne baisse rien.

        Sa coupure est un solo par projecteur (PorteDuSolo), pas un niveau lu
        par colonne — le pupitre n'a donc aucune raison de bouger.
        """
        self.w.tap_button_mode = "flash_kill"
        self.w._recompute_memory_mix()
        avant = self.w.niveaux()
        self.assertTrue(0 < avant[0] < 100, avant)
        self.w._tap_tempo()
        self.assertEqual(self.w._flash_level(40), 40)
        self.assertEqual(self.w.niveaux(), avant)
        self.w._tap_tempo_released()
        self.assertEqual(self.w.niveaux(), avant)

    def test_flash_monte_aussi_le_pupitre(self):
        self.w.tap_button_mode = "flash"
        self.w._recompute_memory_mix()
        avant = self.w.niveaux()
        self.w._tap_tempo()
        self.assertEqual(self.w.niveaux(), [100, 100])
        self.w._tap_tempo_released()
        self.assertEqual(self.w.niveaux(), avant)


class GardeFous(unittest.TestCase):
    """Un flash ne doit jamais rester colle."""

    def test_second_appui_termine_le_flash(self):
        """Filet si le controleur n'envoie pas de Note Off."""
        w = FauxWin()
        w.active_memory_pads = {0: 0}
        w.faders[0].value = 50
        w._recompute_memory_mix()
        avant = w.niveaux()
        w._tap_tempo()
        self.assertEqual(w.niveaux(), [100, 100])
        w._tap_tempo()                       # second appui, pas de relachement
        self.assertIsNone(w._flash_kind)
        self.assertEqual(w.niveaux(), avant)

    def test_watchdog_arme_puis_desarme(self):
        w = FauxWin()
        w._tap_tempo()
        self.assertTrue(w._flash_watchdog.isActive())
        w._tap_tempo_released()
        self.assertFalse(w._flash_watchdog.isActive())

    def test_relacher_sans_flash_ne_fait_rien(self):
        w = FauxWin()
        w.active_memory_pads = {0: 0}
        w.faders[0].value = 50
        w._recompute_memory_mix()
        avant, envois = w.niveaux(), w.dmx_envois
        w._tap_tempo_released()
        self.assertEqual(w.dmx_envois, envois)
        self.assertEqual(w.niveaux(), avant)

    def test_double_appui_ne_reempile_pas(self):
        w = FauxWin()
        w._flash_begin()
        w._flash_begin()
        self.assertEqual(w._flash_kind, "full")
        w._flash_end()
        self.assertIsNone(w._flash_kind)


class ConfigPersistee(unittest.TestCase):
    """Le mode se relit, y compris depuis les configs d'avant les flashs."""

    def test_normalisation(self):
        self.assertEqual(mw.normalize_tap_button_mode(True), "go")
        self.assertEqual(mw.normalize_tap_button_mode(False), "bpm")
        self.assertEqual(mw.normalize_tap_button_mode("flash"), "flash")
        self.assertEqual(mw.normalize_tap_button_mode("FLASH_KILL"), "flash_kill")
        self.assertEqual(mw.normalize_tap_button_mode(None), "bpm")
        self.assertEqual(mw.normalize_tap_button_mode("n'importe quoi"), "bpm")

    def test_dialogue_aller_retour(self):
        slots = [{"type": "group", "group": "A"} for _ in range(8)]
        for mode in mw.TAP_BUTTON_MODES:
            dlg = mw.AkaiLayoutEditorDialog(slots, tap_button_mode=mode)
            self.assertEqual(dlg.get_tap_button_mode(), mode)
            # Le bouton porte le libelle du mode, pas un intitule generique
            self.assertIn(mw.tr(mw._TAP_MODE_KEYS[mode]), dlg._tap_mode_btn.text())
            dlg.deleteLater()

    def test_dialogue_changement_par_le_menu(self):
        """Choisir dans le menu met a jour le bouton ET la valeur rendue."""
        slots = [{"type": "group", "group": "A"} for _ in range(8)]
        dlg = mw.AkaiLayoutEditorDialog(slots, tap_button_mode="bpm")
        dlg._set_tap_mode("flash_kill")
        self.assertEqual(dlg.get_tap_button_mode(), "flash_kill")
        self.assertIn(mw.tr("tap_btn_mode_kill"), dlg._tap_mode_btn.text())
        dlg.deleteLater()

    def test_dialogue_accepte_lancien_booleen(self):
        slots = [{"type": "group", "group": "A"} for _ in range(8)]
        dlg = mw.AkaiLayoutEditorDialog(slots, tap_button_mode=True)
        self.assertEqual(dlg.get_tap_button_mode(), "go")
        dlg.deleteLater()


class ApparenceDuBouton(unittest.TestCase):
    """Le bouton a l'ecran annonce son mode, et qu'un flash est en cours."""

    def _bouton(self, mode, flash=None):
        from PySide6.QtWidgets import QToolButton
        w = FauxWin()
        w.tap_button_mode = mode
        w._flash_kind = flash
        w._tap_btn = QToolButton()
        w._update_tap_go_btn_style =             mw.MainWindow._update_tap_go_btn_style.__get__(w, FauxWin)
        w._update_tap_go_btn_style()
        return w._tap_btn

    def test_chaque_mode_a_une_apparence(self):
        vus = {}
        for mode in mw.TAP_BUTTON_MODES:
            b = self._bouton(mode)
            vus[mode] = (b.text(), b.toolTip())
            self.assertTrue(b.toolTip(), mode)
            self.assertTrue(b.styleSheet(), mode)
        # BPM garde la pastille grise sans libelle, tous les autres sont marques
        self.assertEqual(vus["bpm"][0], "")
        for mode in mw.TAP_BUTTON_MODES:
            if mode != "bpm":
                self.assertTrue(vus[mode][0], mode)
        # Chaque mode a son propre texte d'aide
        self.assertEqual(len({t for _, t in vus.values()}), len(mw.TAP_BUTTON_MODES))

    def test_flash_en_cours_change_le_fond(self):
        repos = self._bouton("flash").styleSheet()
        actif = self._bouton("flash", flash="full").styleSheet()
        self.assertNotEqual(repos, actif)

    def test_le_bouton_est_carre(self):
        """Il figure une touche du controleur : carree, pas ronde."""
        for mode in mw.TAP_BUTTON_MODES:
            ss = self._bouton(mode).styleSheet()
            self.assertIn("border-radius: 3px", ss, mode)
            self.assertNotIn("border-radius: 8px", ss, mode)

    def test_kill_se_distingue_du_flash(self):
        self.assertNotEqual(self._bouton("flash").styleSheet(),
                            self._bouton("flash_kill").styleSheet())


class RetourLedMidi(unittest.TestCase):
    """La LED du bouton reste allumee pendant un flash, clignote sinon."""

    class FauxOut:
        def __init__(self):
            self.envois = []

        def send_message(self, msg):
            self.envois.append(list(msg))

    class FauxOwner:
        def __init__(self, mode):
            self.tap_button_mode = mode
            self.appuis = 0
            self.relachements = 0

        def _tap_tempo(self):
            self.appuis += 1

        def _tap_tempo_released(self):
            self.relachements += 1

    def _handler(self, mode):
        import midi_handler as mh
        h = mh.MIDIHandler.__new__(mh.MIDIHandler)
        h.owner_window = self.FauxOwner(mode)
        h.midi_out = self.FauxOut()
        return h

    def test_appui_transmis_dans_tous_les_modes(self):
        for mode in mw.TAP_BUTTON_MODES:
            h = self._handler(mode)
            h._tap_button_pressed(122, 3)
            self.assertEqual(h.owner_window.appuis, 1, mode)
            self.assertIn([0x90, 122, 3], h.midi_out.envois, mode)

    def test_led_maintenue_en_flash(self):
        """Pas d'extinction immediate : la LED doit rester allumee tant qu'on tient."""
        for mode in ("flash", "flash_kill"):
            h = self._handler(mode)
            h._tap_button_pressed(122, 3)
            self.assertEqual(h.midi_out.envois, [[0x90, 122, 3]], mode)
            h._tap_button_released(122)
            self.assertEqual(h.owner_window.relachements, 1, mode)
            self.assertEqual(h.midi_out.envois[-1], [0x90, 122, 0], mode)

    def test_relachement_transmis_meme_sans_sortie_midi(self):
        h = self._handler("flash")
        h.midi_out = None
        h._tap_button_released(122)
        self.assertEqual(h.owner_window.relachements, 1)

    def test_sans_fenetre_proprietaire_rien_ne_casse(self):
        import midi_handler as mh
        h = mh.MIDIHandler.__new__(mh.MIDIHandler)
        h.owner_window = None
        h.midi_out = self.FauxOut()
        h._tap_button_pressed(122, 3)
        h._tap_button_released(122)
        self.assertEqual(h.midi_out.envois[-1], [0x90, 122, 0])


class MenuClicDroit(unittest.TestCase):
    """Le menu des 4 fonctions, partage entre la config et le clic droit."""

    def test_le_menu_liste_les_quatre_modes(self):
        choisis = []
        menu = mw.build_tap_mode_menu(None, "flash", choisis.append)
        actions = [a for a in menu.actions() if a.isEnabled() and not a.isSeparator()]
        self.assertEqual([a.data() for a in actions], list(mw.TAP_BUTTON_MODES))
        for a in actions:
            self.assertIn(mw.tr(mw._TAP_MODE_KEYS[a.data()]), a.text())

    def test_le_mode_courant_est_marque(self):
        """Marque de selection cochee, comme dans le menu des effets."""
        for courant in mw.TAP_BUTTON_MODES:
            menu = mw.build_tap_mode_menu(None, courant, lambda m: None)
            coches = [a.data() for a in menu.actions()
                      if a.isEnabled() and not a.isSeparator() and a.isChecked()]
            self.assertEqual(coches, [courant])

    def test_meme_habillage_que_le_menu_des_effets(self):
        """La marque de selection est celle des effets : fond vert + lisere."""
        ss = mw.build_tap_mode_menu(None, "go", lambda m: None).styleSheet()
        for regle in ("QMenu::item:checked", "background:#004400", "color:#44ff44",
                      "border-left:3px solid #44ff44",
                      "QMenu::indicator { width:0px; height:0px; image:none; }"):
            self.assertIn(regle, ss)

    def test_declencher_une_entree_transmet_le_mode(self):
        for attendu in mw.TAP_BUTTON_MODES:
            choisis = []
            menu = mw.build_tap_mode_menu(None, "bpm", choisis.append)
            action = next(a for a in menu.actions()
                          if a.isEnabled() and not a.isSeparator() and a.data() == attendu)
            action.trigger()
            self.assertEqual(choisis, [attendu])

    def test_changement_depuis_le_bouton(self):
        w = FauxWin()
        w.tap_button_mode = "bpm"
        w.sauvegardes = 0
        w._save_akai_config_auto = lambda: setattr(w, "sauvegardes", w.sauvegardes + 1)
        w._set_tap_button_mode =             mw.MainWindow._set_tap_button_mode.__get__(w, FauxWin)
        w._set_tap_button_mode("flash_kill")
        self.assertEqual(w.tap_button_mode, "flash_kill")
        self.assertEqual(w.sauvegardes, 1, "le choix doit etre retenu")

    def test_changer_de_mode_termine_un_flash_en_cours(self):
        w = FauxWin()
        w.active_memory_pads = {0: 0}
        w.faders[0].value = 60
        w._recompute_memory_mix()
        avant = w.niveaux()
        w._save_akai_config_auto = lambda: None
        w._set_tap_button_mode =             mw.MainWindow._set_tap_button_mode.__get__(w, FauxWin)
        w._tap_tempo()                      # flash en cours
        self.assertEqual(w.niveaux(), [100, 100])
        w._set_tap_button_mode("bpm")       # ... et on change de fonction
        self.assertIsNone(w._flash_kind)
        self.assertEqual(w.niveaux(), avant)

    def test_clic_droit_ne_declenche_pas_de_flash(self):
        """Le clic droit ouvre le menu ; il ne doit surtout pas flasher."""
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QToolButton

        appuis = []
        b = QToolButton()
        b.setFixedSize(16, 16)
        b.pressed.connect(lambda: appuis.append("gauche"))
        b.setContextMenuPolicy(Qt.CustomContextMenu)
        pt = QPointF(8, 8)
        for bouton in (Qt.RightButton, Qt.MiddleButton):
            b.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pt, pt,
                                          bouton, bouton, Qt.NoModifier))
        self.assertEqual(appuis, [], "seul le clic gauche doit declencher le bouton")
        # ... et le clic gauche, lui, declenche bien
        b.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pt, pt,
                                      Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(appuis, ["gauche"])

    def test_remettre_le_meme_mode_ne_sauvegarde_pas(self):
        w = FauxWin()
        w.tap_button_mode = "go"
        w.sauvegardes = 0
        w._save_akai_config_auto = lambda: setattr(w, "sauvegardes", w.sauvegardes + 1)
        w._set_tap_button_mode =             mw.MainWindow._set_tap_button_mode.__get__(w, FauxWin)
        w._set_tap_button_mode("go")
        self.assertEqual(w.sauvegardes, 0)


class TestFlashSansMemoire(unittest.TestCase):
    """FLASH ne doit RIEN toucher quand aucune memoire n'est tenue.

    `_recompute_memory_mix` compose le rig A PARTIR des memoires : sans
    memoire, chaque projecteur tombe dans « aucune memoire ne me touche →
    eteint ». L'appui sur FLASH faisait donc un blackout, et comme le relache
    rappelait le meme mix vide, le look manuel etait perdu pour de bon.
    """

    def _look_manuel(self, w):
        """Un blanc pose a la main (pads couleur / plan 2D), hors memoires."""
        for p in w.projectors:
            p.level = 80
            p.base_color = QColor(255, 255, 255)
            p.color = QColor(204, 204, 204)

    def test_l_appui_ne_noircit_pas_le_look_manuel(self):
        w = FauxWin()
        self._look_manuel(w)
        w._flash_begin()
        self.assertEqual(w.niveaux(), [80, 80], "FLASH a noirci le rig")
        for p in w.projectors:
            self.assertEqual(p.base_color.getRgb()[:3], (255, 255, 255))

    def test_le_relache_ne_noircit_pas_non_plus(self):
        w = FauxWin()
        self._look_manuel(w)
        w._flash_begin()
        w._flash_end()
        self.assertEqual(w.niveaux(), [80, 80])
        for p in w.projectors:
            self.assertEqual(p.color.getRgb()[:3], (204, 204, 204))

    def test_une_memoire_mutee_ne_compte_pas(self):
        w = FauxWin()
        w.active_memory_pads = {0: 0}
        w._muted_faders = {0}
        self._look_manuel(w)
        w._flash_begin()
        self.assertEqual(w.niveaux(), [80, 80],
                         "une memoire mutee n'a rien a flasher")

    def test_pad_latche_sur_une_case_vide_ne_compte_pas(self):
        w = FauxWin()
        w.active_memory_pads = {0: 3}          # ligne 3 : aucune memoire dedans
        self._look_manuel(w)
        w._flash_begin()
        self.assertEqual(w.niveaux(), [80, 80])

    def test_avec_une_memoire_le_flash_agit_comme_avant(self):
        """Le garde-fou ne doit pas desactiver le FLASH quand il a un sens."""
        w = FauxWin()
        w.active_memory_pads = {0: 0}
        w.faders[0].value = 0                  # fader baisse : FLASH le monte quand meme
        w._flash_begin()
        self.assertEqual(w.niveaux(), [100, 100],
                         "FLASH doit monter la memoire tenue a 100 %")
        w._flash_end()
        self.assertEqual(w.niveaux(), [0, 0],
                         "au relache la memoire redescend a son fader")

    def test_memoire_posee_pendant_le_flash_redescend_au_relache(self):
        w = FauxWin()
        self._look_manuel(w)
        w._flash_begin()                       # rien a flasher
        w.active_memory_pads = {0: 0}          # memoire posee PENDANT le flash
        w.faders[0].value = 50
        w._flash_end()
        # ~50 et non 100 : le mix arrondit (100 x 0,50), ce qui compte est que
        # la memoire soit redescendue a son fader.
        for lvl in w.niveaux():
            self.assertTrue(45 <= lvl <= 55, f"reste bloque a {lvl} apres le flash")


class TestKillNeToucheJamaisLeModele(unittest.TestCase):
    """FLASH KILL ne doit modifier AUCUN etat du show.

    La coupure est ailleurs : une porte posee et defaite le temps d'une frame
    juste avant l'envoi DMX (test_flash_kill_reel.py), plus un drapeau
    d'affichage sur le plan 2D (test_flash_kill_affichage.py). Appeler
    `_recompute_memory_mix` en plus etait destructeur : sous KILL toutes les
    memoires sont ramenees a 0, le mix est donc VIDE et noircit le modele —
    le look manuel partait pour de bon, l'appui blackait et le relache ne
    rendait rien.
    """

    def _win_kill(self, look=True):
        w = FauxWin()
        w.tap_button_mode = "flash_kill"
        if look:
            for p in w.projectors:
                p.level = 80
                p.base_color = QColor(255, 255, 255)
                p.color = QColor(204, 204, 204)
        return w

    def test_sans_memoire_le_look_manuel_survit(self):
        w = self._win_kill()
        w._flash_begin()
        self.assertEqual(w.niveaux(), [80, 80])
        w._flash_end()
        self.assertEqual(w.niveaux(), [80, 80])

    def test_avec_une_memoire_tenue_le_look_manuel_survit_aussi(self):
        """Le cas qui restait casse : une memoire tenue amenait le mix vide."""
        w = self._win_kill()
        w.active_memory_pads = {0: 0}
        w.faders[0].value = 100
        w._flash_begin()
        self.assertEqual(w.niveaux(), [80, 80],
                         "le KILL a noirci le MODELE au lieu de la seule frame")
        w._flash_end()
        self.assertEqual(w.niveaux(), [80, 80],
                         "le look manuel doit revenir intact au relache")
        for p in w.projectors:
            self.assertEqual(p.base_color.getRgb()[:3], (255, 255, 255))

    def test_le_kill_reste_arme_pendant_l_appui(self):
        """Ne rien ecrire ne veut pas dire ne rien faire : la porte doit s'armer."""
        w = self._win_kill()
        w._flash_begin()
        self.assertEqual(w._flash_kind, "kill")
        w._flash_end()
        self.assertIsNone(w._flash_kind)

    def test_flash_plein_monte_toujours_les_memoires(self):
        """Le garde-fou du KILL ne doit pas toucher au FLASH normal."""
        w = FauxWin()                      # tap_button_mode = "flash"
        w.active_memory_pads = {0: 0}
        w.faders[0].value = 0
        w._flash_begin()
        self.assertEqual(w.niveaux(), [100, 100])
        w._flash_end()
        self.assertEqual(w.niveaux(), [0, 0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
