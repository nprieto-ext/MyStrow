"""
test_pads_couleur_momentanes.py — Pads couleur momentanes tant que FLASH est tenu.

Scenario reel (signale le 28/08/2026) : groupes A B C D montes, les 4 pads
BLANC allumes. En tenant le bouton FLASH (bas-droite du controleur, ou la
touche F), appuyer sur le pad ROUGE de la colonne D doit :

  * a l'appui   — envoyer le rouge sur D (modele + DMX), allumer le pad ROUGE
                  et eteindre le pad BLANC de cette colonne SEULEMENT ;
  * au relache  — rendre EXACTEMENT l'etat d'avant : couleur de base, couleur
                  courante, roue de couleurs, pad BLANC rallume, pad ROUGE
                  eteint. Les colonnes A, B et C ne bougent jamais.

Hors FLASH, le pad couleur reste un latch : appuyer pose la couleur, relacher
ne fait rien. C'est la regle qui separe les deux comportements, et c'est l'etat
AU MOMENT DE L'APPUI qui compte — lacher FLASH avant le pad ne colle pas la
couleur.

    python test_pads_couleur_momentanes.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QPushButton

import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)


class FauxFader:
    def __init__(self, value=100):
        self.value = value


class FauxProjecteur:
    def __init__(self, group):
        self.group = group
        self.dmx_profile = ["R", "G", "B"]
        self.level = 100
        self.base_color = QColor("black")
        self.color = QColor("black")
        self.color_wheel = 0
        self.color_wheel_slots = []
        self.channel_extras = {}

    def release_color_overrides(self):
        return False


class FauxMidi:
    midi_out = None


class FauxWin:
    """MainWindow reduite aux pads couleur et au momentane FLASH."""

    _GENERIC_WHEEL_SLOTS  = mw.MainWindow._GENERIC_WHEEL_SLOTS
    _update_color_wheel   = mw.MainWindow._update_color_wheel
    activate_pad          = mw.MainWindow.activate_pad
    _pads_are_momentary   = mw.MainWindow._pads_are_momentary
    _repaint_color_column = mw.MainWindow._repaint_color_column
    _column_groups        = mw.MainWindow._column_groups
    _kill_solo_groups     = mw.MainWindow._kill_solo_groups
    _snapshot_color_column = mw.MainWindow._snapshot_color_column
    _restore_color_column = mw.MainWindow._restore_color_column
    _on_color_pad_pressed = mw.MainWindow._on_color_pad_pressed
    _on_color_pad_released = mw.MainWindow._on_color_pad_released

    # Groupes internes des 4 colonnes A B C D du test
    _GROUPES = ["face", "douche1", "douche2", "lat"]

    def __init__(self):
        self.projectors = [FauxProjecteur(g) for g in self._GROUPES]
        self.dmx = None
        self.midi_handler = FauxMidi()
        self.akai_active_brightness = 100
        self.akai_inactive_brightness = 30
        self._mem_rec_mode = False
        self._rec_mem_btn = None
        self._flash_kind = None
        self._pad_flash_snaps = {}
        self._kill_solo_cols = {}
        self.active_pads = {}
        self.faders = {c: FauxFader(100) for c in range(4)}
        self._fader_map = [{"type": "group", "group": g} for g in self._GROUPES]
        self.dmx_sends = 0

        # 8 pads par colonne ; seules 2 couleurs nous interessent ici
        self.pads = {}
        self._couleurs = [QColor(255, 255, 255), QColor(255, 0, 0)] + \
                         [QColor(0, 0, 255)] * 6
        for c in range(4):
            for r in range(8):
                b = QPushButton()
                col = self._couleurs[r]
                b.setProperty("base_color", col)
                b.setProperty("dim_color", QColor(col.red() // 2, col.green() // 2,
                                                  col.blue() // 2))
                b.setProperty("cw_dmx_val", None)
                self.pads[(r, c)] = b

    # Le vrai _slot_groups mappe la lettre vers les groupes internes ; ici le
    # slot porte deja le groupe interne.
    def _slot_groups(self, slot):
        return [slot["group"]]

    def send_dmx_update(self):
        self.dmx_sends += 1

    def _show_error_toast(self, msg):
        pass


BLANC, ROUGE = 0, 1     # lignes de pads


def _scene():
    """4 colonnes montees, les 4 pads BLANC latches."""
    w = FauxWin()
    for c in range(4):
        w.activate_pad(w.pads[(BLANC, c)], c)
    return w


class TestMomentaneSousFlash(unittest.TestCase):

    def test_hors_flash_le_pad_reste_un_latch(self):
        w = _scene()
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w._on_color_pad_released(3)
        self.assertEqual(w.projectors[3].base_color.getRgb()[:3], (255, 0, 0),
                         "sans FLASH, relacher ne doit rien rendre")
        self.assertIs(w.active_pads[3], w.pads[(ROUGE, 3)])

    def test_appui_sous_flash_envoie_le_rouge_sur_la_seule_colonne(self):
        w = _scene()
        w._flash_kind = "full"                     # bouton FLASH tenu
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertEqual(w.projectors[3].color.getRgb()[:3], (255, 0, 0))
        for i in range(3):
            self.assertEqual(w.projectors[i].color.getRgb()[:3], (255, 255, 255),
                             "le momentane a deborde sur les autres groupes")

    def test_relache_rend_couleur_roue_et_pad(self):
        w = _scene()
        w.projectors[3].color_wheel = 42
        avant = (QColor(w.projectors[3].base_color), QColor(w.projectors[3].color),
                 w.projectors[3].color_wheel)

        w._flash_kind = "full"
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertIs(w.active_pads[3], w.pads[(ROUGE, 3)],
                      "le pad ROUGE doit etre le pad actif pendant l'appui")

        w._on_color_pad_released(3)
        apres = (QColor(w.projectors[3].base_color), QColor(w.projectors[3].color),
                 w.projectors[3].color_wheel)
        self.assertEqual(avant[0].getRgb(), apres[0].getRgb())
        self.assertEqual(avant[1].getRgb(), apres[1].getRgb())
        self.assertEqual(avant[2], apres[2])
        self.assertIs(w.active_pads[3], w.pads[(BLANC, 3)],
                      "le pad BLANC doit se reactiver au relache")

    def test_les_autres_colonnes_gardent_leur_pad(self):
        w = _scene()
        w._flash_kind = "full"
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w._on_color_pad_released(3)
        for c in range(4):
            self.assertIs(w.active_pads[c], w.pads[(BLANC, c)])

    def test_lacher_flash_avant_le_pad_ne_colle_pas_la_couleur(self):
        """L'etat qui compte est celui de l'APPUI, pas celui du relache."""
        w = _scene()
        w._flash_kind = "full"
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w._flash_kind = None                      # bouton FLASH relache en premier
        w._on_color_pad_released(3)
        self.assertEqual(w.projectors[3].color.getRgb()[:3], (255, 255, 255))
        self.assertIs(w.active_pads[3], w.pads[(BLANC, 3)])

    def test_prendre_flash_apres_l_appui_ne_rend_rien(self):
        """Appui hors FLASH : le pad reste latche meme si FLASH arrive apres."""
        w = _scene()
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w._flash_kind = "full"
        w._on_color_pad_released(3)
        self.assertEqual(w.projectors[3].base_color.getRgb()[:3], (255, 0, 0))

    def test_deux_colonnes_momentanees_sont_independantes(self):
        w = _scene()
        w._flash_kind = "full"
        w._on_color_pad_pressed(w.pads[(ROUGE, 2)], 2)
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        w._on_color_pad_released(2)
        self.assertEqual(w.projectors[2].color.getRgb()[:3], (255, 255, 255))
        self.assertEqual(w.projectors[3].color.getRgb()[:3], (255, 0, 0),
                         "relacher une colonne ne doit pas rendre l'autre")
        w._on_color_pad_released(3)
        self.assertEqual(w.projectors[3].color.getRgb()[:3], (255, 255, 255))

    def test_sous_kill_le_pad_arme_un_solo_sur_son_groupe(self):
        """FLASH KILL : l'appui du pad epargne SON groupe et coupe les autres."""
        w = _scene()
        w._flash_kind = "kill"
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertEqual(w._kill_solo_groups(), {"lat"},
                         "seul le groupe du pad tenu doit rester allume")
        w._on_color_pad_released(3)
        self.assertIsNone(w._kill_solo_groups(), "le solo doit tomber au relache")
        self.assertIs(w.active_pads[3], w.pads[(BLANC, 3)])

    def test_deux_pads_tenus_sous_kill_epargnent_les_deux_groupes(self):
        w = _scene()
        w._flash_kind = "kill"
        w._on_color_pad_pressed(w.pads[(ROUGE, 2)], 2)
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertEqual(w._kill_solo_groups(), {"douche2", "lat"})
        w._on_color_pad_released(2)
        self.assertEqual(w._kill_solo_groups(), {"lat"})
        w._on_color_pad_released(3)
        self.assertIsNone(w._kill_solo_groups())

    def test_hors_kill_aucun_solo_n_est_arme(self):
        """FLASH normal : le pad est momentane, mais il ne coupe personne."""
        w = _scene()
        w._flash_kind = "full"
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertIsNone(w._kill_solo_groups())
        w._on_color_pad_released(3)

    def test_le_bouton_kill_seul_ne_coupe_rien(self):
        """Tenir FLASH KILL sans toucher un pad ne doit RIEN faire."""
        w = _scene()
        w._flash_kind = "kill"
        self.assertIsNone(w._kill_solo_groups())


class TestPasDeFuiteDInstantane(unittest.TestCase):

    def test_le_relache_d_une_colonne_jamais_pressee_ne_fait_rien(self):
        w = _scene()
        w._on_color_pad_released(1)          # note-off d'une colonne non couleur
        self.assertIs(w.active_pads[1], w.pads[(BLANC, 1)])
        self.assertEqual(w._pad_flash_snaps, {})

    def test_l_instantane_est_purge_au_relache(self):
        w = _scene()
        w._flash_kind = "full"
        w._on_color_pad_pressed(w.pads[(ROUGE, 3)], 3)
        self.assertIn(3, w._pad_flash_snaps)
        w._on_color_pad_released(3)
        self.assertEqual(w._pad_flash_snaps, {},
                         "un instantane laisse derriere ferait un latch fantome")


if __name__ == "__main__":
    unittest.main(verbosity=2)
