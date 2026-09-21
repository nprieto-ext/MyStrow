"""
test_pad_memoire_comportement.py — Clic droit sur un pad memoire > Comportement.

Un pad memoire etait un INTERRUPTEUR et rien d'autre : on le pose, il reste, et
les autres colonnes continuent leur vie. Il se regle maintenant pad par pad :

  * normal      — inchange ;
  * flash       — momentane : la memoire n'est la que tant qu'on appuie ;
  * flash_solo  — momentane ET seule en scene.

Un mode « solo » latche (couper les autres, et rester) a existe une demi-journee
le 20/09/2026, puis a ete retire : le geste utile, c'est le momentane.

Ce que ce test surveille avant tout, c'est le RETOUR des deux momentanes :
un flash ne doit rien laisser derriere lui — ni look manuel perdu, ni pad
eteint au passage, ni cue rembobine. C'est le piege qu'avait deja le bouton
bas-droite (`_recompute_memory_mix` compose la scene a partir des SEULES
memoires : tout ce qui n'est porte par aucune tombe au noir).

    python test_pad_memoire_comportement.py
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

    def start(self, *a):
        self.started = True

    def stop(self):
        self.started = False

    def isActive(self):
        return self.started


class FauxProjecteur:
    def __init__(self, group="face"):
        self.dmx_profile = ["R", "G", "B"]
        self.group = group
        self.level = 0
        self.base_color = QColor("black")
        self.color = QColor("black")
        self.pan = self.tilt = 32768
        self.uv = self.amber_boost = self.white_boost = self.orange_boost = 0
        self.gobo = self.zoom = self.strobe_speed = 0
        self.muted = False
        self.dmx_mode = "Manuel"
        self.channel_extras = {}
        self._manual_color = False


def _cue(n_proj, niveaux, couleur="#ff0000"):
    """Un cue ou seuls les projos listes dans `niveaux` sont allumes."""
    projs = []
    for i in range(n_proj):
        lvl = niveaux.get(i, 0)
        projs.append({"level": lvl,
                      "base_color": couleur if lvl else "#000000",
                      "pan": 32768, "tilt": 32768})
    return {"label": "Cue 1", "projectors": projs, "effect": {}, "duration": 0}


class FauxWin:
    """MainWindow reduite aux pads memoire et a leur comportement."""

    MEM_PAD_MODES          = mw.MainWindow.MEM_PAD_MODES
    _MEM_MODE_KEYS         = mw.MainWindow._MEM_MODE_KEYS
    _MEM_MODE_HINTS        = mw.MainWindow._MEM_MODE_HINTS
    _MEM_FLASH_ATTRS       = mw.MainWindow._MEM_FLASH_ATTRS

    _mem_pad_mode          = mw.MainWindow._mem_pad_mode
    _set_mem_pad_mode      = mw.MainWindow._set_mem_pad_mode
    _deactivate_memory_pad = mw.MainWindow._deactivate_memory_pad
    _mem_cut_others        = mw.MainWindow._mem_cut_others
    _mem_flash_snapshot    = mw.MainWindow._mem_flash_snapshot
    _mem_flash_restore     = mw.MainWindow._mem_flash_restore
    _mem_flash_begin       = mw.MainWindow._mem_flash_begin
    _mem_flash_end         = mw.MainWindow._mem_flash_end
    _mem_flash_holds       = mw.MainWindow._mem_flash_holds
    _on_memory_pad_pressed = mw.MainWindow._on_memory_pad_pressed
    _on_memory_pad_released = mw.MainWindow._on_memory_pad_released
    _activate_memory_pad   = mw.MainWindow._activate_memory_pad

    _recompute_memory_mix  = mw.MainWindow._recompute_memory_mix
    _compute_htp_overrides = mw.MainWindow._compute_htp_overrides
    _clear_memory_from_projectors = mw.MainWindow._clear_memory_from_projectors
    _mem_ensure_cues       = mw.MainWindow._mem_ensure_cues
    _mem_active_cue        = mw.MainWindow._mem_active_cue
    _mem_advance_cue       = mw.MainWindow._mem_advance_cue
    _mem_ensure_fade       = mw.MainWindow._mem_ensure_fade
    _mem_fade_secs         = mw.MainWindow._mem_fade_secs
    _etat_couleur_courant  = mw.MainWindow._etat_couleur_courant
    _flash_level           = mw.MainWindow._flash_level
    _mem_flash_level       = mw.MainWindow._mem_flash_level
    _mem_pad_border_style  = mw.MainWindow._mem_pad_border_style

    def __init__(self, n_proj=3):
        # Deux colonnes memoire (indispensable pour tester un flash solo) + du groupe.
        self._fader_map = [{"type": "memory", "mem_col": 0, "label": "MEM 1"},
                           {"type": "memory", "mem_col": 1, "label": "MEM 2"}] + \
                          [{"type": "group", "group": g, "label": g} for g in "CDEFGH"]
        self.faders = {i: FauxFader(100) for i in range(9)}
        self._muted_faders = set()
        self._mem_ext_levels = {}
        self._mem_rows = {}
        self._mem_cue_idx = {}
        self._mem_rec_mode = False
        self._mem_flash = None
        self._mem_flash_watchdog = _TimerMuet()
        self._fade_timer = _TimerMuet()
        self._dur_timer = _TimerMuet()
        self._dur_progress_timer = _TimerMuet()
        self._dur_mem_col = -1
        self._dur_row = -1
        self._flash_kind = None
        self.go_mode = False
        self.projectors = [FauxProjecteur() for _ in range(n_proj)]
        self.active_effect = None
        self.active_effect_config = {}

        # MEM 1.1 : projo 0 en rouge. MEM 2.1 : projo 1 en bleu.
        self.memories = [[None] * 8 for _ in range(8)]
        self.memories[0][0] = {"cues": [_cue(n_proj, {0: 100}, "#ff0000")], "loop": True}
        self.memories[1][0] = {"cues": [_cue(n_proj, {1: 100}, "#0000ff")], "loop": True}

        self.active_memory_pads = {}
        self.logs = []
        self.dmx_envois = 0
        self.sauvegardes = 0

    # ── Dependances neutralisees ────────────────────────────────────────────
    def _fader_to_mem_col(self, fader_idx):
        slot = self._fader_map[fader_idx] if fader_idx < len(self._fader_map) else {}
        return slot.get("mem_col") if slot.get("type") == "memory" else None

    def _bank_memory_slots(self):
        return [(i, sl["mem_col"]) for i, sl in enumerate(self._fader_map)
                if sl["type"] == "memory"]

    def _mem_col_to_fader(self, mem_col):
        for i, slot in enumerate(self._fader_map):
            if slot.get("type") == "memory" and slot.get("mem_col") == mem_col:
                return i
        return 4 + min(mem_col, 3)

    def _style_memory_pad(self, mem_col, row, active):
        pass

    def _update_memory_pad_led(self, mem_col, row, active):
        pass

    def _refresh_memory_pad(self, mem_col, row):
        pass

    def _release_manual_grabs(self):
        pass

    def _blink_memory_pad(self, mem_col, row):
        pass

    def _start_cue_duration(self, mem_col, row):
        pass

    def _cue_fade_secs(self, mem_col, row):
        return 0.0

    def _auto_blink_stop(self):
        pass

    def _sync_cue_play_button(self):
        pass

    def _update_color_wheel(self, p, color):
        pass

    def _restore_effect_state(self):
        return {}

    def _log_message(self, text, level="info"):
        self.logs.append((level, text))

    def _save_akai_config_auto(self):
        self.sauvegardes += 1

    def send_dmx_update(self):
        self.dmx_envois += 1

    def stop_effect(self):
        pass

    def start_effect(self, name):
        pass

    # ── Aides de lecture ────────────────────────────────────────────────────
    def niveaux(self):
        return [p.level for p in self.projectors]

    def teintes(self):
        return [p.base_color.name() for p in self.projectors]

    def poser(self, mem_col, row=0):
        """Appui + relache complet sur un pad, comme a l'ecran ou sur l'AKAI."""
        col = self._mem_col_to_fader(mem_col)
        self._on_memory_pad_pressed(None, mem_col, row, col)
        self._on_memory_pad_released(mem_col, row, col)

    def appuyer(self, mem_col, row=0):
        self._on_memory_pad_pressed(None, mem_col, row, self._mem_col_to_fader(mem_col))

    def relacher(self, mem_col, row=0):
        self._on_memory_pad_released(mem_col, row, self._mem_col_to_fader(mem_col))


class Reglage(unittest.TestCase):
    """Le comportement se lit, s'ecrit, et voyage avec la memoire."""

    def test_defaut(self):
        w = FauxWin()
        self.assertEqual(w._mem_pad_mode(0, 0), "normal")

    def test_ecriture_et_relecture(self):
        w = FauxWin()
        for mode in ("flash", "flash_solo"):
            w._set_mem_pad_mode(0, 0, mode)
            self.assertEqual(w._mem_pad_mode(0, 0), mode)
            self.assertEqual(w.memories[0][0]["pad_mode"], mode)

    def test_normal_nejoute_aucune_cle(self):
        """Un show qui n'a jamais touche au reglage garde le format d'avant."""
        w = FauxWin()
        w._set_mem_pad_mode(0, 0, "flash")
        w._set_mem_pad_mode(0, 0, "normal")
        self.assertNotIn("pad_mode", w.memories[0][0])

    def test_valeur_inconnue_retombe_sur_normal(self):
        w = FauxWin()
        w.memories[0][0]["pad_mode"] = "n_importe_quoi"
        self.assertEqual(w._mem_pad_mode(0, 0), "normal")

    def test_lancien_mode_solo_retombe_sur_normal(self):
        """Un pad regle en solo avant son retrait redevient un interrupteur."""
        w = FauxWin()
        w.memories[1][0]["pad_mode"] = "solo"
        self.assertEqual(w._mem_pad_mode(1, 0), "normal")
        w.poser(0)
        w.poser(1)
        self.assertEqual(w.active_memory_pads, {0: 0, 1: 0},
                         "il ne doit plus couper les autres colonnes")

    def test_pad_vide(self):
        w = FauxWin()
        self.assertEqual(w._mem_pad_mode(3, 3), "normal")
        w._set_mem_pad_mode(3, 3, "flash")      # ne doit pas exploser
        self.assertIsNone(w.memories[3][3])

    def test_bordure_pointillee_pour_les_momentanes(self):
        w = FauxWin()
        self.assertEqual(w._mem_pad_border_style(0, 0), "solid")
        w._set_mem_pad_mode(0, 0, "flash")
        self.assertEqual(w._mem_pad_border_style(0, 0), "dashed")
        w._set_mem_pad_mode(0, 0, "flash_solo")
        self.assertEqual(w._mem_pad_border_style(0, 0), "dashed")

    def test_les_trois_modes_ont_leurs_textes(self):
        from i18n import TRANSLATIONS
        for mode in FauxWin.MEM_PAD_MODES:
            for table in (FauxWin._MEM_MODE_KEYS, FauxWin._MEM_MODE_HINTS):
                cle = table[mode]
                self.assertIn(cle, TRANSLATIONS, cle)
                for lg in ("en", "fr", "es", "de", "pt"):
                    self.assertTrue(TRANSLATIONS[cle].get(lg), f"{cle}/{lg}")


class Normal(unittest.TestCase):
    """Le comportement d'avant, intact : deux colonnes cohabitent."""

    def test_les_deux_memoires_restent(self):
        w = FauxWin()
        w.poser(0)
        w.poser(1)
        self.assertEqual(w.active_memory_pads, {0: 0, 1: 0})
        self.assertEqual(w.niveaux(), [100, 100, 0])
        self.assertEqual(w.teintes()[:2], ["#ff0000", "#0000ff"])


class Flash(unittest.TestCase):
    """Flash : present tant qu'on appuie, et RIEN derriere lui."""

    def setUp(self):
        self.w = FauxWin()
        self.w._set_mem_pad_mode(1, 0, "flash")

    def test_pendant_lappui(self):
        self.w.appuyer(1)
        self.assertTrue(self.w._mem_flash_holds(1, 0))
        self.assertEqual(self.w.niveaux(), [0, 100, 0])

    def test_le_relache_rend_la_scene(self):
        self.w.poser(0)                       # look porte par MEM 1
        avant_niv, avant_teintes = self.w.niveaux(), self.w.teintes()
        self.w.appuyer(1)
        self.assertEqual(self.w.niveaux(), [100, 100, 0], "le flash s'ajoute")
        self.w.relacher(1)
        self.assertEqual(self.w.niveaux(), avant_niv)
        self.assertEqual(self.w.teintes(), avant_teintes)
        self.assertEqual(self.w.active_memory_pads, {0: 0},
                         "le registre des pads doit revenir a l'identique")
        self.assertIsNone(self.w._mem_flash)

    def test_un_look_manuel_survit(self):
        """Le piege du bouton FLASH : un look porte par AUCUNE memoire.

        `_recompute_memory_mix` eteint tout ce qu'aucune memoire ne touche. Sans
        la photo prise a l'appui, le projo 2 serait noirci a l'appui et ne
        reviendrait jamais.
        """
        p = self.w.projectors[2]
        p.level, p.base_color, p.color = 80, QColor("#00ff00"), QColor("#00cc00")
        self.w.appuyer(1)
        self.w.relacher(1)
        self.assertEqual(p.level, 80)
        self.assertEqual(p.base_color.name(), "#00ff00")
        self.assertEqual(self.w.niveaux(), [0, 0, 80])

    def test_le_strobe_dun_flash_ne_reste_pas_colle(self):
        """Une memoire qui ne porte qu'un canal faisceau doit le rendre aussi."""
        self.w.memories[1][0]["cues"][0]["projectors"][2]["strobe_speed"] = 200
        self.w.appuyer(1)
        self.w.relacher(1)
        self.assertEqual(self.w.projectors[2].strobe_speed, 0)

    def test_le_cue_courant_nest_pas_rembobine(self):
        """Un flash repart a son cue 1 sans toucher a celui des autres pads."""
        self.w.memories[0][0]["cues"].append(_cue(3, {2: 100}, "#00ff00"))
        self.w.poser(0)
        self.w._mem_cue_idx[(0, 0)] = 1       # MEM 1 en est au cue 2
        self.w.appuyer(1)
        self.w.relacher(1)
        self.assertEqual(self.w._mem_cue_idx.get((0, 0)), 1)
        self.assertNotIn((1, 0), self.w._mem_cue_idx)

    def test_relache_dun_pad_non_tenu(self):
        w = self.w
        w.relacher(0)                          # personne ne tient rien
        self.assertIsNone(w._mem_flash)

    def test_changer_de_mode_pendant_lappui_rend_la_scene(self):
        self.w.appuyer(1)
        self.w._set_mem_pad_mode(1, 0, "normal")
        self.assertIsNone(self.w._mem_flash)
        self.assertEqual(self.w.niveaux(), [0, 0, 0])

    def test_garde_fou_arme_puis_desarme(self):
        """Un controleur muet au Note Off ne doit pas coller le pad."""
        self.w.appuyer(1)
        self.assertTrue(self.w._mem_flash_watchdog.isActive())
        self.w._mem_flash_end()                # ce que fera le garde-fou
        self.assertFalse(self.w._mem_flash_watchdog.isActive())
        self.assertIsNone(self.w._mem_flash)


class FlashSolo(unittest.TestCase):
    """Flash solo : seule en scene pendant l'appui, tout revient au relache."""

    def setUp(self):
        self.w = FauxWin()
        self.w._set_mem_pad_mode(1, 0, "flash_solo")

    def test_pendant_lappui_elle_est_seule(self):
        self.w.poser(0)
        self.w.appuyer(1)
        self.assertEqual(self.w.niveaux(), [0, 100, 0])
        self.assertEqual(self.w.active_memory_pads, {1: 0})

    def test_tout_revient_au_relache(self):
        self.w.poser(0)
        avant = self.w.niveaux()
        self.w.appuyer(1)
        self.w.relacher(1)
        self.assertEqual(self.w.niveaux(), avant)
        self.assertEqual(self.w.active_memory_pads, {0: 0})

    def test_une_memoire_du_pupitre_se_tait_aussi(self):
        """Hors page, une memoire tenue par l'entree DMX n'a pas de pad a
        eteindre : le mix doit cesser de la compter pendant l'appui."""
        w = FauxWin()
        w._set_mem_pad_mode(1, 0, "flash_solo")
        # MEM 3 n'est sur aucune colonne affichee, tenue a 100 % par le pupitre.
        w.memories[2][0] = {"cues": [_cue(3, {2: 100}, "#00ff00")], "loop": True}
        w._mem_rows[2] = 0
        w._mem_ext_levels[2] = 100
        w._recompute_memory_mix()
        self.assertEqual(w.niveaux(), [0, 0, 100])
        w.appuyer(1)
        self.assertEqual(w.niveaux(), [0, 100, 0])
        w.relacher(1)
        self.assertEqual(w.niveaux(), [0, 0, 100])


class RecEtGardes(unittest.TestCase):
    """Les autres chemins du pad gardent la priorite."""

    def test_le_mode_rec_passe_devant_le_flash(self):
        w = FauxWin()
        w._set_mem_pad_mode(1, 0, "flash")
        w._mem_rec_mode = True
        enregistres = []
        w._record_memory = lambda mc, r: enregistres.append((mc, r))
        w._rec_mem_btn = None
        w.appuyer(1)
        self.assertEqual(enregistres, [(1, 0)])
        self.assertIsNone(w._mem_flash, "le REC ne doit pas armer un momentane")

    def test_un_pad_vide_ne_flashe_pas(self):
        w = FauxWin()
        w.memories[1][0]["pad_mode"] = "flash"
        w.memories[1][0] = None                 # ... puis efface
        w.appuyer(1)
        self.assertIsNone(w._mem_flash)

    def test_un_second_appui_nempile_pas(self):
        w = FauxWin()
        w._set_mem_pad_mode(1, 0, "flash")
        w.appuyer(1)
        photo = w._mem_flash["photo"]
        w.appuyer(1)
        self.assertIs(w._mem_flash["photo"], photo,
                      "le deuxieme appui ne doit pas ecraser la photo du premier")


class TimerDenchainement(unittest.TestCase):
    """Couper un pad arrete l'enchainement minute qui lui appartenait."""

    def test_le_timer_sarrete(self):
        w = FauxWin()
        w.poser(0)
        w._dur_mem_col, w._dur_row = 0, 0
        w._dur_timer.start()
        w._dur_progress_timer.start()
        w._set_mem_pad_mode(1, 0, "flash_solo")
        w.appuyer(1)
        self.assertFalse(w._dur_timer.isActive(),
                         "le cue d'une memoire coupee ne doit plus avancer")
        self.assertEqual(w._dur_mem_col, -1)


class FlashFaderBaisse(unittest.TestCase):
    """Un pad de flash joue meme si son fader est a zero.

    C'est un geste, pas un reglage : personne ne monte un fader avant de
    flasher. Le niveau part a 100 %, comme le bouton FLASH monte les memoires
    tenues sans toucher a leur fader.
    """

    def setUp(self):
        self.w = FauxWin()
        self.w.faders[1].value = 0            # la colonne de MEM 2 est en bas
        self.w._set_mem_pad_mode(1, 0, "flash")

    def test_le_flash_monte_quand_meme(self):
        self.w.appuyer(1)
        self.assertEqual(self.w.niveaux(), [0, 100, 0])
        self.assertEqual(self.w.teintes()[1], "#0000ff")

    def test_le_fader_nest_pas_touche(self):
        self.w.appuyer(1)
        self.assertEqual(self.w.faders[1].value, 0,
                         "le flash ne doit deplacer aucun fader")

    def test_le_relache_le_fait_redescendre(self):
        self.w.appuyer(1)
        self.w.relacher(1)
        self.assertEqual(self.w.niveaux(), [0, 0, 0],
                         "fader a zero : la memoire doit disparaitre d'elle-meme")

    def test_la_couche_htp_par_frame_voit_le_niveau_force(self):
        """Sans ca, le flash durerait UNE frame : `_compute_htp_overrides`
        repose les memoires depuis le fader brut a chaque envoi DMX."""
        self.w.appuyer(1)
        p = self.w.projectors[1]
        p.level = 0                            # comme si une autre couche l'avait baisse
        ov = self.w._compute_htp_overrides()
        self.assertIn(id(p), ov)
        self.assertEqual(ov[id(p)][0], 100)

    def test_aucune_fuite_sur_les_autres_colonnes(self):
        """Le forcage vaut pour la colonne tenue, pas pour les voisines."""
        self.w.faders[0].value = 0             # MEM 1 posee mais fader a zero
        self.w.poser(0)
        self.w.appuyer(1)
        self.assertEqual(self.w.niveaux(), [0, 100, 0])

    def test_flash_solo_fader_baisse(self):
        w = FauxWin()
        w._set_mem_pad_mode(1, 0, "flash_solo")
        w.faders[1].value = 0
        w.poser(0)
        w.appuyer(1)
        self.assertEqual(w.niveaux(), [0, 100, 0])
        w.relacher(1)
        self.assertEqual(w.niveaux(), [100, 0, 0])


class RelacheRetireLaMemoire(unittest.TestCase):
    """Relacher un pad momentane ENLEVE sa memoire, meme si elle etait posee.

    Seul point ou un flash change l'etat d'avant, et c'est voulu : un pad de
    flash ne doit jamais laisser sa memoire allumee derriere lui.
    """

    def test_une_memoire_deja_posee_est_retiree(self):
        w = FauxWin()
        w.poser(1)                              # posee alors qu'elle etait normale
        w._set_mem_pad_mode(1, 0, "flash")      # ... puis reglee en flash
        self.assertEqual(w.niveaux(), [0, 100, 0])
        w.appuyer(1)
        w.relacher(1)
        self.assertEqual(w.active_memory_pads, {},
                         "le pad tenu ne doit pas revenir dans le registre")
        self.assertEqual(w.niveaux(), [0, 0, 0])

    def test_les_autres_colonnes_reviennent(self):
        w = FauxWin()
        w.poser(0)
        w.poser(1)                              # MEM 2 posee elle aussi
        w._set_mem_pad_mode(1, 0, "flash_solo")
        w.appuyer(1)
        w.relacher(1)
        self.assertEqual(w.active_memory_pads, {0: 0})
        self.assertEqual(w.niveaux(), [100, 0, 0])

    def test_une_autre_ligne_de_la_meme_colonne_revient(self):
        """Ce n'est pas « la memoire qu'on appuie » : elle, elle revient."""
        w = FauxWin()
        w.memories[1][3] = {"cues": [_cue(3, {2: 100}, "#00ff00")], "loop": True}
        w.poser(1, 3)                           # MEM 2.4 posee
        w._set_mem_pad_mode(1, 0, "flash")
        self.assertEqual(w.niveaux(), [0, 0, 100])
        w.appuyer(1, 0)                         # flash sur MEM 2.1
        self.assertEqual(w.niveaux(), [0, 100, 0])
        w.relacher(1, 0)
        self.assertEqual(w.active_memory_pads, {1: 3})
        self.assertEqual(w.niveaux(), [0, 0, 100])

    def test_le_cue_de_la_memoire_retiree_est_oublie(self):
        w = FauxWin()
        w.memories[1][0]["cues"].append(_cue(3, {2: 100}, "#00ff00"))
        w.poser(1)                              # cue 1 : le projo 2 en bleu
        w.poser(1)                              # 2e appui : elle avance au cue 2
        w._set_mem_pad_mode(1, 0, "flash")
        self.assertEqual(w._mem_cue_idx.get((1, 0)), 1)
        self.assertEqual(w.niveaux(), [0, 0, 100], "cue 2 : le projo 3 en vert")
        w.appuyer(1)
        self.assertEqual(w.niveaux(), [0, 100, 0],
                         "un flash repart de son cue 1")
        w.relacher(1)
        self.assertNotIn((1, 0), w._mem_cue_idx)
        self.assertEqual(w.niveaux(), [0, 0, 0],
                         "ni le cue 1 du flash ni le cue 2 d'avant ne restent")


class ChangementDePage(unittest.TestCase):
    """Bascule de page pendant qu'un pad momentane est tenu."""

    def test_le_flash_est_rendu_avant_la_bascule(self):
        """`active_memory_pads` est indexe par colonne VISIBLE : la page suivante
        n'a pas les memes, la scene serait rendue a des colonnes fantomes."""
        w = FauxWin()
        w._set_bank_page = mw.MainWindow._set_bank_page.__get__(w)
        w._bank_pages = [w._fader_map, list(reversed(w._fader_map))]
        w._bank_page_idx = 0
        w._custom_bank_slots = w._bank_pages[0]
        w._apply_active_bank_layout = lambda: None
        w._update_bank_page_indicator = lambda: None
        w._set_mem_pad_mode(1, 0, "flash")
        w.poser(0)
        w.appuyer(1)
        self.assertTrue(w._mem_flash_holds(1, 0))
        w._set_bank_page(1)
        self.assertIsNone(w._mem_flash)
        self.assertEqual(w.active_memory_pads, {0: 0})
        self.assertEqual(w.niveaux(), [100, 0, 0])


class MenuContextuel(unittest.TestCase):
    """Le sous-menu existe vraiment, coche le mode courant et le change.

    ⚠️ Un QMenu s'ouvre en boucle modale : reassigner `QMenu.exec` ne prend
    pas (type Shiboken). Ce qui marche, c'est un QTimer arme AVANT l'appel, qui
    retrouve le menu visible et le ferme — en relevant son contenu d'abord, Qt
    detruisant les sous-menus juste apres.
    """

    def _fenetre(self):
        from PySide6.QtWidgets import QWidget, QPushButton
        from sequencer import Sequencer

        class FauxFenetre(QWidget):
            _show_memory_context_menu = mw.MainWindow._show_memory_context_menu
            _mem_pad_mode    = mw.MainWindow._mem_pad_mode
            _mem_ensure_cues = mw.MainWindow._mem_ensure_cues
            _mem_ensure_fade = mw.MainWindow._mem_ensure_fade
            _mem_fade_secs   = mw.MainWindow._mem_fade_secs
            _fmt_mem_fade    = mw.MainWindow._fmt_mem_fade
            MEM_PAD_MODES    = mw.MainWindow.MEM_PAD_MODES
            _MEM_MODE_KEYS   = mw.MainWindow._MEM_MODE_KEYS
            _MEM_MODE_HINTS  = mw.MainWindow._MEM_MODE_HINTS

            def __init__(self):
                super().__init__()
                self.memories = [[None] * 8 for _ in range(8)]
                self.memories[0][0] = {"cues": [_cue(2, {0: 100})], "loop": True}
                self.memory_custom_colors = [[None] * 8 for _ in range(8)]
                self._button_effect_configs = {}
                self._effect_library_configs = {}
                self.poses = []

            def _set_mem_pad_mode(self, mem_col, row, mode):
                self.poses.append((mem_col, row, mode))

        w = FauxFenetre()
        return w, QPushButton(w)

    def _ouvrir(self, w, btn, choisir=None):
        """Ouvre le menu, releve le sous-menu Comportement, referme.

        `choisir` declenche une action AVANT la fermeture : apres, Qt a detruit
        les QAction du sous-menu et les toucher leve « Internal C++ object
        already deleted ».
        """
        from PySide6.QtCore import QTimer, QPoint
        from PySide6.QtWidgets import QMenu, QApplication
        releve = {}

        def _attraper():
            for top in QApplication.topLevelWidgets():
                if isinstance(top, QMenu) and top.isVisible():
                    for act in top.actions():
                        sm = act.menu()
                        if sm is None:
                            continue
                        titres = [a.text() for a in sm.actions()]
                        if any(t == mw.tr("mw_mem_beh_flash") for t in titres):
                            releve["titre"] = act.text()
                            releve["actions"] = [(a.text(), a.isChecked(),
                                                  a.toolTip()) for a in sm.actions()]
                            if choisir is not None:
                                for a in sm.actions():
                                    if a.text() == choisir:
                                        a.trigger()
                                        break
                    top.close()

        QTimer.singleShot(0, _attraper)
        w._show_memory_context_menu(QPoint(0, 0), 0, 0, btn)
        return releve

    def test_le_sous_menu_est_la_avec_les_trois_modes(self):
        w, btn = self._fenetre()
        releve = self._ouvrir(w, btn)
        self.assertIn("actions", releve, "sous-menu Comportement introuvable")
        textes = [t for t, _c, _h in releve["actions"]]
        for mode in FauxWin.MEM_PAD_MODES:
            self.assertIn(mw.tr(FauxWin._MEM_MODE_KEYS[mode]), textes)
        # Chaque mode s'explique : les libelles seuls ne disent pas ce que
        # devient la scene au relache.
        self.assertTrue(all(h for _t, _c, h in releve["actions"]))

    def test_le_mode_courant_est_coche_et_annonce(self):
        w, btn = self._fenetre()
        w.memories[0][0]["pad_mode"] = "flash_solo"
        releve = self._ouvrir(w, btn)
        coches = [t for t, c, _h in releve["actions"] if c]
        self.assertEqual(coches, [mw.tr("mw_mem_beh_flash_solo")])
        self.assertIn(mw.tr("mw_mem_beh_flash_solo"), releve["titre"],
                      "le titre du sous-menu doit dire le mode en cours")

    def test_choisir_un_mode_le_pose(self):
        w, btn = self._fenetre()
        self._ouvrir(w, btn, choisir=mw.tr("mw_mem_beh_flash"))
        self.assertEqual(w.poses, [(0, 0, "flash")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
