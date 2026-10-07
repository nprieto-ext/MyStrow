"""
test_image_lancee_avec_son.py — « Lancer avec le son précédent » (ligne image).

Une image posée sous un son peut s'y accrocher : elle s'affiche pendant ce son
(aperçu + sortie vidéo), et les deux lignes ne font qu'une étape — à la fin du
son, la playlist passe à la ligne d'après l'image. Seul le son pilote la
lumière : la ligne image n'est jamais lancée pour elle-même.

    python test_image_lancee_avec_son.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

import main_window as mw
import sequencer as sq

_app = QApplication.instance() or QApplication(sys.argv)
S = sq.Sequencer


class FauxSeq:
    LINK_ROLE = S.LINK_ROLE
    LOOP_ROLE = S.LOOP_ROLE
    _row_media_kind   = S._row_media_kind
    can_link_row      = S.can_link_row
    is_row_linked     = S.is_row_linked
    set_row_linked    = S.set_row_linked
    toggle_row_linked = S.toggle_row_linked
    linked_image_path = S.linked_image_path
    next_step_row     = S.next_step_row
    play_row          = S.play_row

    def __init__(self, chemins):
        self.table = QTableWidget(0, 5)
        for r, p in enumerate(chemins):
            self.table.insertRow(r)
            it = QTableWidgetItem(os.path.basename(p))
            it.setData(Qt.UserRole, p)
            self.table.setItem(r, 1, it)
        self.current_row = -1
        self.is_dirty = False
        self.lancees = []

    def _refresh_row_marks(self, row):
        pass

    def _fade_out_before(self, row):
        # Point d'entrée de play_row après la redirection : on note la ligne
        # réellement lancée et on s'arrête là.
        self.lancees.append(row)
        return True


PLAYLIST = ["intro.mp3", "chanson.mp3", "affiche.png", "video.mp4", "fin.png", "PAUSE"]


class LigneAccrochee(unittest.TestCase):

    def setUp(self):
        self.seq = FauxSeq(PLAYLIST)

    def test_seule_une_image_sous_un_son_peut_s_accrocher(self):
        self.assertTrue(self.seq.can_link_row(2))
        self.assertFalse(self.seq.can_link_row(4), "sous une video : non")
        self.assertFalse(self.seq.can_link_row(1), "un son : non")
        self.assertFalse(self.seq.can_link_row(0))

    def test_drapeau_sans_effet_hors_d_un_son(self):
        self.seq.set_row_linked(4, True)
        self.assertFalse(self.seq.is_row_linked(4))

    def test_chemin_et_etape_suivante(self):
        self.assertIsNone(self.seq.linked_image_path(1))
        self.assertEqual(self.seq.next_step_row(1), 2)
        self.seq.set_row_linked(2, True)
        self.assertEqual(self.seq.linked_image_path(1), "affiche.png")
        self.assertEqual(self.seq.next_step_row(1), 3, "l'image accrochee est sautee")
        self.assertEqual(self.seq.next_step_row(0), 1)

    def test_suivant_depuis_le_son_saute_l_image(self):
        self.seq.set_row_linked(2, True)
        self.seq.current_row = 1
        self.seq.play_row(2)
        self.assertEqual(self.seq.lancees, [3])

    def test_lancer_l_image_relance_son_son(self):
        self.seq.set_row_linked(2, True)
        self.seq.current_row = 3          # « Précédent » depuis la vidéo
        self.seq.play_row(2)
        self.seq.current_row = -1         # double-clic à l'arrêt
        self.seq.play_row(2)
        self.assertEqual(self.seq.lancees, [1, 1])

    def test_image_ordinaire_inchangee(self):
        self.seq.current_row = 1
        self.seq.play_row(2)
        self.assertEqual(self.seq.lancees, [2])

    def test_deplacer_l_image_sous_la_video_la_decroche(self):
        self.seq.set_row_linked(2, True)
        t = self.seq.table
        a, b = t.takeItem(2, 1), t.takeItem(3, 1)
        t.setItem(2, 1, b)
        t.setItem(3, 1, a)
        self.assertFalse(self.seq.is_row_linked(3))
        self.assertIsNone(self.seq.linked_image_path(1))


class FauxSortie:
    def __init__(self):
        self.etat = None

    def isVisible(self):
        return True

    def show_black(self):
        self.etat = "noir"

    def show_image(self, pixmap):
        self.etat = "image"

    def show_video(self):
        self.etat = "video"


class FauxWin:
    _update_video_output_state = mw.MainWindow._update_video_output_state
    _show_linked_image         = mw.MainWindow._show_linked_image
    hide_image                 = mw.MainWindow.hide_image

    def __init__(self, seq, image):
        self.seq = seq
        self._cart_video_lead = False
        self._linked_image_row = None
        self.video_output_window = FauxSortie()
        self.apercu = None
        self._image = image

        class _Stack:
            def setCurrentIndex(s, i):
                pass
        self.video_stack = _Stack()

    def show_image(self, path):
        self.apercu = path


class SortieVideo(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.png = os.path.join(self.tmp, "affiche.png")
        pix = QPixmap(4, 4)
        pix.fill(QColor("red"))
        pix.save(self.png)
        self.seq = FauxSeq(["chanson.mp3", self.png, "suite.mp3"])
        self.win = FauxWin(self.seq, self.png)

    def test_son_seul_ecran_noir(self):
        self.seq.current_row = 0
        self.assertFalse(self.win._show_linked_image(0))
        self.win._update_video_output_state()
        self.assertEqual(self.win.video_output_window.etat, "noir")

    def test_son_avec_image_l_affiche_partout(self):
        self.seq.set_row_linked(1, True)
        self.seq.current_row = 0
        self.assertTrue(self.win._show_linked_image(0))
        self.assertEqual(self.win.apercu, self.png)
        self.assertEqual(self.win.video_output_window.etat, "image")

    def test_masquee_retombe_au_noir(self):
        self.seq.set_row_linked(1, True)
        self.seq.current_row = 0
        self.win._show_linked_image(0)
        self.win.hide_image()
        self.win._update_video_output_state()
        self.assertEqual(self.win.video_output_window.etat, "noir")

    def test_cartouche_video_garde_la_main(self):
        self.seq.set_row_linked(1, True)
        self.seq.current_row = 0
        self.win._cart_video_lead = True
        self.assertFalse(self.win._show_linked_image(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
