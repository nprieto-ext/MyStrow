"""
test_flash_kill_reel.py — FLASH / FLASH KILL vus depuis la SORTIE DMX.

`test_flash_bouton.py` verifie le modele : `_recompute_memory_mix` posait bien
0 % (KILL) ou 100 % (FLASH) sur les projecteurs. Ca passait, et pourtant rien
ne se voyait sur les lampes.

La raison : `_recompute_memory_mix` n'est appele qu'aux evenements, alors que
`send_dmx_update` tourne a chaque frame (40 fps) et REPOSE par-dessus, en HTP,
les memoires (`_compute_htp_overrides`) et les pads manuels
(`_apply_pad_overrides_htp`) — a partir du fader BRUT. Une frame apres le
debut du KILL, tout etait donc rallume au niveau d'avant.

Ce test regarde donc ce qui part vraiment sur le fil :

  * les deux couches HTP lisent le fader a travers `_flash_level` ;
  * un KILL passe par une derniere porte avant l'envoi — le noir doit couper
    « le reste » sans exception (effet en cours, IA, timeline compris), puis
    se defaire aussitot : aucun etat du show ne bouge ;
  * un momentane ne touche pas au moteur d'effets (sinon un KILL tuait
    definitivement l'effet lance depuis un pad FX).

    python test_flash_kill_reel.py
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
    def start(self):
        pass

    def stop(self):
        pass

    def isActive(self):
        # `_compute_htp_overrides` interroge le timer de fondu : hors fondu, la
        # couche HTP repose les memoires comme avant (cf. test_fondu_memoire_lyre).
        return False


class FauxProjecteur:
    def __init__(self, group="face"):
        self.dmx_profile = ["R", "G", "B"]
        self.group = group
        self.level = 0
        self.base_color = QColor("black")
        self.color = QColor("black")
        self.pan = self.tilt = 32768
        self.uv = 0
        self.white_boost = 0
        self.amber_boost = 0
        self.orange_boost = 0
        self.strobe_speed = 0


class FauxPad:
    """Pad manuel AKAI : seule sa `base_color` interesse la couche HTP."""

    def __init__(self, couleur="#00ff00"):
        self._props = {"base_color": QColor(couleur)}

    def property(self, name):
        return self._props.get(name)


class FauxWin:
    """MainWindow reduite aux couches HTP et au momentane."""

    _flash_level             = mw.MainWindow._flash_level
    _flash_has_memories      = mw.MainWindow._flash_has_memories
    _flash_begin             = mw.MainWindow._flash_begin
    _flash_end               = mw.MainWindow._flash_end
    _recompute_memory_mix    = mw.MainWindow._recompute_memory_mix
    _mem_ensure_cues         = mw.MainWindow._mem_ensure_cues
    _mem_active_cue          = mw.MainWindow._mem_active_cue
    _bank_memory_slots       = mw.MainWindow._bank_memory_slots
    _slot_groups             = staticmethod(mw.MainWindow._slot_groups)
    _compute_htp_overrides   = mw.MainWindow._compute_htp_overrides
    _apply_pad_overrides_htp = mw.MainWindow._apply_pad_overrides_htp
    _KILL_EXTRA_CHANNELS     = mw.MainWindow._KILL_EXTRA_CHANNELS
    _kill_solo_groups        = mw.MainWindow._kill_solo_groups
    _apply_flash_kill_gate   = mw.MainWindow._apply_flash_kill_gate
    _restore_flash_kill_gate = mw.MainWindow._restore_flash_kill_gate

    def __init__(self, n_proj=2):
        self.tap_button_mode = "flash_kill"
        self._flash_kind = None
        self._flash_watchdog = _TimerMuet()
        self._fade_timer = _TimerMuet()

        # Colonne 0 = memoire 0 ; colonne 1 = groupe A (pads manuels).
        self._fader_map = [{"type": "memory", "mem_col": 0, "label": "MEM 1"},
                           {"type": "group", "group": "A", "label": "A"}]
        self.faders = {0: FauxFader(80), 1: FauxFader(60)}
        self._muted_faders = set()
        self._mem_ext_levels = {}
        self._mem_rows = {}
        self._mem_cue_idx = {}
        self._kill_solo_cols = {}
        self.projectors = [FauxProjecteur("face") for _ in range(n_proj)]
        self.active_pads = {}
        self.active_effect = None
        self.active_effect_config = {}

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
        self.active_memory_pads = {0: 0}
        self.logs = []
        self.effets_arretes = 0

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
        pass

    def stop_effect(self):
        self.effets_arretes += 1

    def start_effect(self, name):
        pass


# ══════════════════════════════════════════════════════════════════════════
class CoucheHtpMemoires(unittest.TestCase):
    """`_compute_htp_overrides` tourne a CHAQUE frame : elle doit voir le flash."""

    def setUp(self):
        self.w = FauxWin()

    def test_au_repos_la_memoire_est_reposee_au_niveau_du_fader(self):
        ov = self.w._compute_htp_overrides()
        self.assertEqual(len(ov), len(self.w.projectors))
        self.assertEqual(next(iter(ov.values()))[0], 80)   # 100 % x fader 80

    def test_kill_ne_touche_plus_au_niveau_lu(self):
        """KILL tenu seul ne coupe RIEN — la coupure est le solo, par projecteur.

        Avant, `_flash_level` ramenait toute colonne memoire a 0 sous KILL :
        c'etait un blackout des l'appui sur le bouton. La coupure passe
        desormais entierement par `_apply_flash_kill_gate` (cf. PorteDuSolo).
        """
        self.w._flash_kind = "kill"
        ov = self.w._compute_htp_overrides()
        self.assertEqual(len(ov), len(self.w.projectors))
        self.assertEqual(next(iter(ov.values()))[0], 80)

    def test_flash_repose_a_cent(self):
        self.w._flash_kind = "full"
        ov = self.w._compute_htp_overrides()
        self.assertEqual(next(iter(ov.values()))[0], 100)

    def test_le_fader_lui_meme_ne_bouge_pas(self):
        """Le momentane force le niveau LU, il ne touche aucun fader."""
        self.w._flash_kind = "kill"
        self.w._compute_htp_overrides()
        self.w._flash_kind = "full"
        self.w._compute_htp_overrides()
        self.assertEqual(self.w.faders[0].value, 80)


class CoucheHtpPadsManuels(unittest.TestCase):
    """Les pads manuels font partie du « reste » que le solo doit couper."""

    def setUp(self):
        self.w = FauxWin()
        self.w.active_memory_pads = {}      # que des pads, pas de memoire
        self.w.active_pads = {1: FauxPad("#00ff00")}

    def test_au_repos_le_pad_monte_au_niveau_du_fader(self):
        self.w._apply_pad_overrides_htp()
        self.assertEqual([p.level for p in self.w.projectors], [60, 60])

    def test_kill_seul_laisse_les_pads_manuels_tranquilles(self):
        """Tenir KILL ne coupe rien : c'est le solo qui coupe, et il vient apres."""
        self.w._flash_kind = "kill"
        self.w._apply_pad_overrides_htp()
        self.assertEqual([p.level for p in self.w.projectors], [60, 60])

    def test_le_solo_coupe_les_pads_manuels_hors_groupe(self):
        """La porte passe APRES cette couche : elle a le dernier mot."""
        self.w._flash_kind = "kill"
        self.w.projectors[1].group = "lat"
        self.w._apply_pad_overrides_htp()
        self.w._kill_solo_cols = {1: {"face"}}
        self.w._apply_flash_kill_gate()
        self.assertEqual([p.level for p in self.w.projectors], [60, 0])

    def test_flash_monte_les_pads_a_cent(self):
        self.w._flash_kind = "full"
        self.w._apply_pad_overrides_htp()
        self.assertEqual([p.level for p in self.w.projectors], [100, 100])

    def test_le_retour_rend_l_etat_d_avant(self):
        sauve = self.w._apply_pad_overrides_htp()
        for i, level, color, base in sauve:
            self.w.projectors[i].level = level
            self.w.projectors[i].color = color
            self.w.projectors[i].base_color = base
        self.assertEqual([p.level for p in self.w.projectors], [0, 0])


class PorteDuSolo(unittest.TestCase):
    """FLASH KILL = SOLO momentane, arme par l'appui d'un pad couleur.

    Tenu SEUL, le bouton ne coupe rien : il faut un pad couleur presse. Le
    groupe de ce pad sort normalement, tout le reste part au noir — et
    seulement le temps de la frame, aucun etat du show n'est touche.

    Ici projectors[0] est du groupe « face », projectors[1] du groupe « lat ».
    """

    def setUp(self):
        self.w = FauxWin()
        # Un solo n'epargne qu'une partie du rig : il faut deux groupes pour
        # le voir. projectors[0] = « face », projectors[1] = « lat ».
        self.w.projectors[1].group = "lat"
        for p in self.w.projectors:
            p.level = 70
            p.color = QColor("#ff8800")
            p.base_color = QColor("#ff8800")
            p.uv = 200
            p.amber_boost = 150
            p.white_boost = 90
            p.orange_boost = 40
            p.strobe_speed = 180

    def _solo(self, *groupes):
        self.w._kill_solo_cols = {1: set(groupes)}

    def test_hors_kill_la_porte_ne_fait_rien(self):
        self.assertIsNone(self.w._apply_flash_kill_gate())
        self.assertEqual(self.w.projectors[0].level, 70)

    def test_le_bouton_kill_seul_ne_coupe_rien(self):
        """LE point de la refonte : tenir KILL sans pad ne fait PLUS de blackout."""
        self.w._flash_kind = "kill"
        self.assertIsNone(self.w._apply_flash_kill_gate())
        self.assertEqual([p.level for p in self.w.projectors], [70, 70])

    def test_un_flash_plein_n_est_pas_une_porte(self):
        """FLASH monte les memoires ; il n'a rien a couper."""
        self.w._flash_kind = "full"
        self.assertIsNone(self.w._apply_flash_kill_gate())
        self.assertEqual(self.w.projectors[0].level, 70)

    def test_le_solo_coupe_les_autres_groupes(self):
        self.w._flash_kind = "kill"
        self._solo("lat")
        self.w._apply_flash_kill_gate()
        coupe = self.w.projectors[0]        # groupe « face »
        self.assertEqual(coupe.level, 0)
        self.assertEqual(coupe.color.name(), "#000000")
        self.assertEqual(coupe.base_color.name(), "#000000")

    def test_le_groupe_tenu_sort_normalement(self):
        self.w._flash_kind = "kill"
        self._solo("lat")
        self.w._apply_flash_kill_gate()
        epargne = self.w.projectors[1]      # groupe « lat »
        self.assertEqual(epargne.level, 70)
        self.assertEqual(epargne.color.name(), "#ff8800")
        self.assertEqual(epargne.uv, 200)

    def test_le_solo_coupe_aussi_l_uv_et_les_boosts(self):
        """Un dimmer a 0 ne suffit pas : l'UV et l'ambre sortent a part."""
        self.w._flash_kind = "kill"
        self._solo("lat")
        self.w._apply_flash_kill_gate()
        p = self.w.projectors[0]
        self.assertEqual((p.uv, p.amber_boost, p.white_boost, p.orange_boost), (0, 0, 0, 0))
        self.assertEqual(p.strobe_speed, 0)

    def test_deux_pads_tenus_epargnent_les_deux_groupes(self):
        """Le solo epargne l'UNION des groupes tenus : ici, plus rien a couper."""
        self.w._flash_kind = "kill"
        self.w._kill_solo_cols = {1: {"lat"}, 2: {"face"}}
        self.assertEqual(self.w._apply_flash_kill_gate(), [])
        self.assertEqual([p.level for p in self.w.projectors], [70, 70])

    def test_la_porte_se_defait_aussitot(self):
        """La coupure ne dure qu'une frame : aucun etat du show n'est perdu."""
        self.w._flash_kind = "kill"
        self._solo("lat")
        sauve = self.w._apply_flash_kill_gate()
        self.w._restore_flash_kill_gate(sauve)
        p = self.w.projectors[0]
        self.assertEqual(p.level, 70)
        self.assertEqual(p.color.name(), "#ff8800")
        self.assertEqual((p.uv, p.amber_boost, p.white_boost, p.orange_boost), (200, 150, 90, 40))
        self.assertEqual(p.strobe_speed, 180)

    def test_restaurer_sans_rien_de_sauve_ne_casse_pas(self):
        self.w._restore_flash_kill_gate(None)


class MoteurDEffets(unittest.TestCase):
    """Un momentane ne doit pas tuer l'effet en cours."""

    def test_le_kill_ne_stoppe_pas_l_effet(self):
        w = FauxWin()
        w.active_effect = "Strobe Classique"       # lance depuis un pad FX
        w._flash_kind = "kill"
        w._recompute_memory_mix()
        self.assertEqual(w.effets_arretes, 0)
        self.assertEqual(w.active_effect, "Strobe Classique")

    def test_hors_flash_le_moteur_reprend_la_main(self):
        """Sans momentane, la regle d'avant s'applique telle quelle."""
        w = FauxWin()
        w.active_effect = "Strobe Classique"
        w.active_memory_pads = {}                  # plus aucune memoire retenue
        w._recompute_memory_mix()
        self.assertEqual(w.effets_arretes, 1)
        self.assertIsNone(w.active_effect)


class AllerRetour(unittest.TestCase):
    """L'appui du PAD coupe les autres, le relacher rend l'etat d'avant."""

    @staticmethod
    def _sortie(w):
        """Niveau reellement envoye, dans l'ordre exact de `send_dmx_update` :
        le modele, releve en HTP par les memoires, PUIS la porte du solo qui a
        le dernier mot sur la frame.

        La porte est indispensable ici : le KILL n'ecrit plus rien dans le
        modele (il effacait le look manuel pour de bon), toute la coupure passe
        desormais par elle.
        """
        ov = w._compute_htp_overrides()
        garde = w._apply_flash_kill_gate()
        niveaux = [max(p.level, ov.get(id(p), (0,))[0]) for p in w.projectors]
        w._restore_flash_kill_gate(garde)
        return niveaux

    def test_le_bouton_kill_seul_ne_change_rien(self):
        """Le vrai contrat : tenir KILL sans pad ne touche a RIEN."""
        w = FauxWin()
        w._recompute_memory_mix()
        avant = self._sortie(w)
        self.assertEqual(avant, [80, 80])
        w._flash_begin()
        self.assertEqual(w._flash_kind, "kill")
        self.assertEqual(self._sortie(w), avant, "le bouton seul a coupe")
        w._flash_end()
        self.assertEqual(self._sortie(w), avant)

    def test_solo_puis_relacher(self):
        w = FauxWin()
        w.projectors[1].group = "lat"      # 2e groupe : c'est lui qu'on solote
        w._recompute_memory_mix()
        avant = self._sortie(w)

        w._flash_begin()
        w._kill_solo_cols = {1: {"lat"}}          # pad couleur tenu sur « lat »
        # projectors[0] = « face » coupe, projectors[1] = « lat » epargne
        self.assertEqual(self._sortie(w), [0, avant[1]])

        w._kill_solo_cols = {}                    # pad relache
        w._flash_end()
        self.assertIsNone(w._flash_kind)
        self.assertEqual(self._sortie(w), avant)


if __name__ == "__main__":
    unittest.main(verbosity=2)
