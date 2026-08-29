"""
test_bouton_page_et_led_pos.py — Deux gestes du controleur.

1. Le bouton bas-droite gagne une 5e fonction : PAGE +1. Un seul appui passe a
   la page de layout suivante, et revient a la premiere apres la derniere — un
   bouton suffit donc a faire le tour des pages sans lacher le controleur.
   C'est le MEME chemin que la fleche a l'ecran (`_next_bank_page`) : pads,
   faders et LED suivent exactement pareil.

2. Une position fraichement enregistree allume tout de suite sa LED sur le
   controleur. Avant, `_record_position_akai` ne repeignait que le pad a
   l'ECRAN : sur l'AKAI le pad restait noir jusqu'au premier rappel — on ne
   voyait pas ce qu'on venait d'enregistrer. Meme oubli a l'assignation d'un
   preset existant.

    python test_bouton_page_et_led_pos.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import main_window as mw

_app = QApplication.instance() or QApplication(sys.argv)


class _TimerMuet:
    def start(self):
        pass

    def stop(self):
        pass


class FauxWinPage:
    """MainWindow reduite au dispatch du bouton bas-droite."""

    _tap_tempo      = mw.MainWindow._tap_tempo
    _tap_next_page  = mw.MainWindow._tap_next_page
    _flash_begin    = mw.MainWindow._flash_begin
    _flash_end      = mw.MainWindow._flash_end
    _flash_level    = mw.MainWindow._flash_level

    def __init__(self, n_pages=3):
        self.tap_button_mode = "page"
        self._flash_kind = None
        self._flash_watchdog = _TimerMuet()
        self._bank_pages = [[] for _ in range(n_pages)]
        self._bank_page_idx = 0
        self.logs = []
        self.toasts = []

    def _next_bank_page(self):
        # Copie conforme de MainWindow._next_bank_page, sans l'UI derriere.
        self._bank_page_idx = (self._bank_page_idx + 1) % len(self._bank_pages)

    def _show_mem_toast(self, text):
        self.toasts.append(text)

    def _log_message(self, text, level="info"):
        self.logs.append((level, text))

    def _go_advance(self):
        self.logs.append(("go", "GO"))


class ModePage(unittest.TestCase):

    def test_le_mode_existe_et_a_son_libelle(self):
        self.assertIn("page", mw.TAP_BUTTON_MODES)
        self.assertIn("page", mw._TAP_MODE_KEYS)
        self.assertIn("page", mw._TAP_MODE_COLORS)
        self.assertTrue(mw.tr(mw._TAP_MODE_KEYS["page"]))

    def test_le_mode_survit_a_la_config(self):
        self.assertEqual(mw.normalize_tap_button_mode("page"), "page")

    def test_le_menu_propose_la_page(self):
        menu = mw.build_tap_mode_menu(None, "page", lambda m: None)
        actions = [a for a in menu.actions() if a.isEnabled() and not a.isSeparator()]
        self.assertIn("page", [a.data() for a in actions])
        coches = [a.data() for a in actions if a.isChecked()]
        self.assertEqual(coches, ["page"])

    def test_un_appui_fait_plus_un(self):
        w = FauxWinPage(n_pages=3)
        w._tap_tempo()
        self.assertEqual(w._bank_page_idx, 1)
        w._tap_tempo()
        self.assertEqual(w._bank_page_idx, 2)

    def test_apres_la_derniere_on_revient_a_la_premiere(self):
        w = FauxWinPage(n_pages=3)
        for _ in range(3):
            w._tap_tempo()
        self.assertEqual(w._bank_page_idx, 0)

    def test_le_numero_de_page_est_annonce(self):
        w = FauxWinPage(n_pages=4)
        w._tap_tempo()
        self.assertEqual(w.toasts[-1], "PAGE 2/4")

    def test_une_seule_page_previent_au_lieu_de_boucler(self):
        w = FauxWinPage(n_pages=1)
        w._tap_tempo()
        self.assertEqual(w._bank_page_idx, 0)
        self.assertEqual(w.logs[-1][0], "warn")
        self.assertEqual(w.toasts, [])

    def test_sans_page_du_tout_rien_ne_casse(self):
        w = FauxWinPage(n_pages=1)
        w._bank_pages = []
        w._tap_tempo()
        self.assertEqual(w.logs[-1][0], "warn")

    def test_la_page_n_est_pas_un_momentane(self):
        """Relacher le bouton ne doit rien declencher en mode PAGE."""
        w = FauxWinPage(n_pages=3)
        w._tap_tempo()
        self.assertIsNone(w._flash_kind)

    def test_les_autres_modes_ne_changent_pas_de_page(self):
        for mode in ("bpm", "go", "flash", "flash_kill"):
            w = FauxWinPage(n_pages=3)
            w.tap_button_mode = mode
            w._tap_times = []
            w._tap_btn = None
            try:
                w._tap_tempo()
            except AttributeError:
                pass          # TAP BPM va plus loin que ce faux objet
            self.assertEqual(w._bank_page_idx, 0, mode)


# ══════════════════════════════════════════════════════════════════════════
class FauxWinPos:
    """MainWindow reduite aux pads POS et a leur LED."""

    _assign_position_akai = mw.MainWindow._assign_position_akai

    def __init__(self):
        self.position_pads = [[None] * 8 for _ in range(mw._POS_COL_MAX)]
        self.position_presets = []
        self.active_position_pads = {}
        self.leds = []
        self.styles = []

    def _style_position_akai_pad(self, pos_col, row):
        self.styles.append((pos_col, row))

    def _update_pos_pad_led(self, pos_col, row):
        self.leds.append((pos_col, row))

    def _save_akai_config_auto(self):
        pass

    def _log_message(self, text, level="info"):
        pass


class LedDuPadPosition(unittest.TestCase):

    def test_assigner_un_preset_allume_la_led(self):
        w = FauxWinPos()
        w.position_presets.append({"name": "Centre", "projectors": []})
        w._assign_position_akai(0, 2, 0)
        self.assertIn((0, 2), w.leds)
        self.assertIn((0, 2), w.styles)

    def test_l_enregistrement_appelle_la_led(self):
        """Lecture du source : `_record_position_akai` doit poser la LED.

        Le corps ouvre une QInputDialog — on verifie donc que l'appel est bien
        la, a cote du repeint a l'ecran, plutot que de piloter un dialogue.
        """
        import inspect
        src = inspect.getsource(mw.MainWindow._record_position_akai)
        self.assertIn("_style_position_akai_pad", src)
        self.assertIn("_update_pos_pad_led", src)

    def test_toutes_les_ecritures_de_pad_posent_la_led(self):
        """Aucun chemin ne doit repeindre l'ecran sans toucher le controleur."""
        import inspect
        for nom in ("_record_position_akai", "_assign_position_akai",
                    "_clear_position_akai", "_recall_position_akai"):
            src = inspect.getsource(getattr(mw.MainWindow, nom))
            self.assertIn("_update_pos_pad_led", src, nom)


if __name__ == "__main__":
    unittest.main(verbosity=2)
