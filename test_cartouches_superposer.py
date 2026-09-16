"""
test_cartouches_superposer.py — Option « Superposer par-dessus la playlist ».

Une case commune aux 4 cartouches, DÉCOCHÉE par défaut.

Ce que ces tests verrouillent :

  * décochée, rien ne change : une cartouche coupe la playlist, la playlist
    coupe la cartouche ;
  * cochée, les deux jouent ensemble et la playlist qui avance ne coupe plus
    la cartouche ;
  * entre slots, toujours exclusif : le dernier lancé prend la main ;
  * réappui = stop, appui suivant = relance depuis le début ;
  * le pad STOP coupe tout, même cochée ;
  * une cartouche VIDÉO superposée prend l'image (player principal détaché,
    playlist empêchée de reprendre l'aperçu), et la rend à la fin — en
    réaffichant la ligne où la playlist est ARRIVÉE entre-temps.

    python test_cartouches_superposer.py
"""

import os
import sys
import tempfile
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QApplication, QStackedWidget, QLabel, QTableWidget, QTableWidgetItem, QWidget

import main_window as mw
from ui_components import CartoucheButton

_app = QApplication.instance() or QApplication(sys.argv)

QMP = mw.QMediaPlayer
ITEM = object()          # tient lieu du QGraphicsVideoItem de l'aperçu


class FauxSignal:
    def connect(self, *a):
        pass

    def disconnect(self, *a):
        pass


class FauxPlayer:
    def __init__(self):
        self.etat = QMP.StoppedState
        self.sortie = ITEM
        self.sources = []
        self.durationChanged = FauxSignal()

    def playbackState(self):
        return self.etat

    def play(self):
        self.etat = QMP.PlayingState

    def pause(self):
        self.etat = QMP.PausedState

    def stop(self):
        self.etat = QMP.StoppedState

    def setSource(self, url):
        self.sources.append(os.path.normpath(url.toLocalFile()))

    def setVideoOutput(self, out):
        self.sortie = out


class FauxAudio:
    def setVolume(self, v):
        pass


class FauxFenetreVideo:
    def __init__(self):
        self.affiche = None

    def isVisible(self):
        return True

    def show_video(self):
        self.affiche = "video"

    def show_black(self):
        self.affiche = "noir"

    def show_image(self, pixmap):
        self.affiche = "image"


class Fenetre:
    """MainWindow réduite au cartoucheur et à l'aperçu vidéo."""
    on_cartouche_clicked       = mw.MainWindow.on_cartouche_clicked
    _play_cartouche            = mw.MainWindow._play_cartouche
    _stop_cartouche            = mw.MainWindow._stop_cartouche
    _stop_all_cartouches       = mw.MainWindow._stop_all_cartouches
    on_cart_media_status       = mw.MainWindow.on_cart_media_status
    _cart_take_video           = mw.MainWindow._cart_take_video
    _cart_release_video        = mw.MainWindow._cart_release_video
    show_image                 = mw.MainWindow.show_image
    hide_image                 = mw.MainWindow.hide_image
    show_black_preview         = mw.MainWindow.show_black_preview
    _update_video_output_state = mw.MainWindow._update_video_output_state
    play_path                  = mw.MainWindow.play_path
    _activate_play_pad         = mw.MainWindow._activate_play_pad

    def __init__(self, fichiers):
        self.player = FauxPlayer()
        self.cart_player = FauxPlayer()
        self.cart_player.sortie = None
        self.cart_audio = FauxAudio()
        self.cart_playing_index = -1
        self.cart_superposer = False
        self._cart_video_lead = False
        self.pause_mode = False
        self.video_output_window = FauxFenetreVideo()

        self.video_stack = QStackedWidget()
        self.video_stack.resize(320, 180)
        self.video_stack.addWidget(QWidget())
        self.image_label = QLabel()
        self.video_stack.addWidget(self.image_label)

        table = QTableWidget(len(fichiers), 3)
        for r, f in enumerate(fichiers):
            it = QTableWidgetItem(os.path.basename(f))
            it.setData(Qt.UserRole, f)
            table.setItem(r, 1, it)
        self.seq = types.SimpleNamespace(current_row=-1, table=table)

        self.cartouches = [CartoucheButton(i, self.on_cartouche_clicked) for i in range(4)]

    def _video_out(self):
        return ITEM

    def _refresh_play_leds(self):
        pass

    def charger(self, index, path):
        self.cartouches[index].media_path = path
        self.cartouches[index].set_idle()


class TestCartouchesSuperposer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dossier = tempfile.mkdtemp()
        cls.image = os.path.join(cls.dossier, "decor.png")
        pm = QPixmap(8, 8)
        pm.fill(QColor("red"))
        pm.save(cls.image)
        cls.video_playlist = os.path.join(cls.dossier, "clip.mp4")
        cls.son_a = os.path.join(cls.dossier, "porte_sourde.mp3")
        cls.son_b = os.path.join(cls.dossier, "porte_claire.mp3")
        cls.video_cart = os.path.join(cls.dossier, "flash.mp4")

    def fenetre(self):
        w = Fenetre([self.image, self.video_playlist, self.son_a])
        w.charger(0, self.son_a)
        w.charger(1, self.son_b)
        w.charger(2, self.video_cart)
        return w

    # ── Décochée : comportement historique ──────────────────────────────────

    def test_decochee_par_defaut(self):
        self.assertFalse(self.fenetre().cart_superposer)

    def test_decochee_cartouche_coupe_playlist(self):
        w = self.fenetre()
        w.player.play()
        w.on_cartouche_clicked(0)
        self.assertEqual(w.player.etat, QMP.StoppedState)
        self.assertEqual(w.cart_player.etat, QMP.PlayingState)

    def test_decochee_playlist_coupe_cartouche(self):
        w = self.fenetre()
        w.on_cartouche_clicked(0)
        w.play_path(self.son_b)
        self.assertEqual(w.cart_player.etat, QMP.StoppedState)
        self.assertEqual(w.cart_playing_index, -1)

    def test_decochee_video_ne_detache_pas_la_playlist(self):
        w = self.fenetre()
        w.on_cartouche_clicked(2)
        self.assertIs(w.player.sortie, ITEM)
        self.assertIs(w.cart_player.sortie, ITEM)
        self.assertFalse(w._cart_video_lead)

    # ── Cochée : par-dessus la playlist ─────────────────────────────────────

    def test_cochee_cartouche_ne_coupe_pas_playlist(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.player.play()
        w.on_cartouche_clicked(0)
        self.assertEqual(w.player.etat, QMP.PlayingState)
        self.assertEqual(w.cart_player.etat, QMP.PlayingState)

    def test_cochee_playlist_qui_avance_ne_coupe_pas_cartouche(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.on_cartouche_clicked(0)
        w.play_path(self.son_b)
        self.assertEqual(w.cart_player.etat, QMP.PlayingState)
        self.assertEqual(w.cart_playing_index, 0)
        self.assertEqual(w.cartouches[0].state, CartoucheButton.PLAYING)

    def test_dernier_slot_lance_prend_la_main(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.on_cartouche_clicked(0)
        w.on_cartouche_clicked(1)
        self.assertEqual(w.cart_playing_index, 1)
        self.assertEqual(w.cartouches[0].state, CartoucheButton.IDLE)
        self.assertEqual(w.cartouches[1].state, CartoucheButton.PLAYING)
        self.assertEqual(w.cart_player.sources[-1], self.son_b)

    def test_reappui_stoppe_puis_relance_depuis_le_debut(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.on_cartouche_clicked(0)
        w.on_cartouche_clicked(0)
        self.assertEqual(w.cart_player.etat, QMP.StoppedState)
        w.on_cartouche_clicked(0)
        self.assertEqual(w.cart_player.etat, QMP.PlayingState)
        # Source rechargée à chaque lancement = repart de 0, pas de reprise
        self.assertEqual(w.cart_player.sources, [self.son_a, self.son_a])

    def test_pad_stop_coupe_tout_meme_cochee(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.player.play()
        w.on_cartouche_clicked(0)
        w._activate_play_pad("stop")
        self.assertEqual(w.player.etat, QMP.StoppedState)
        self.assertEqual(w.cart_player.etat, QMP.StoppedState)

    # ── Vidéo superposée : la cartouche prend l'image ───────────────────────

    def test_video_cochee_prend_image(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.seq.current_row = 0            # la playlist montre une image
        w.show_image(self.image)
        self.assertEqual(w.video_stack.currentIndex(), 1)

        w.on_cartouche_clicked(2)
        self.assertTrue(w._cart_video_lead)
        self.assertIsNone(w.player.sortie)
        self.assertIs(w.cart_player.sortie, ITEM)
        self.assertEqual(w.video_stack.currentIndex(), 0)
        self.assertEqual(w.video_output_window.affiche, "video")

    def test_playlist_ne_reprend_pas_image_pendant_video(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.on_cartouche_clicked(2)
        w.show_image(self.image)
        w.show_black_preview()
        w._update_video_output_state()
        self.assertEqual(w.video_stack.currentIndex(), 0)
        self.assertEqual(w.video_output_window.affiche, "video")

    def test_fin_video_rend_image_a_la_ligne_courante(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.seq.current_row = 2            # son de playlist pendant la vidéo
        w.on_cartouche_clicked(2)
        w.seq.current_row = 0            # la playlist est passée à une image
        w.on_cart_media_status(QMP.EndOfMedia)
        self.assertFalse(w._cart_video_lead)
        self.assertIs(w.player.sortie, ITEM)
        self.assertIsNone(w.cart_player.sortie)
        self.assertEqual(w.video_stack.currentIndex(), 1)
        self.assertEqual(w.video_output_window.affiche, "image")

    def test_stop_video_sur_ligne_video_rend_la_video(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.seq.current_row = 1
        w.on_cartouche_clicked(2)
        w.on_cartouche_clicked(2)
        self.assertFalse(w._cart_video_lead)
        self.assertIs(w.player.sortie, ITEM)
        self.assertEqual(w.video_stack.currentIndex(), 0)
        self.assertEqual(w.video_output_window.affiche, "video")

    def test_video_puis_son_rend_image(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.seq.current_row = 2
        w.on_cartouche_clicked(2)
        w.on_cartouche_clicked(0)
        self.assertFalse(w._cart_video_lead)
        self.assertIs(w.player.sortie, ITEM)
        self.assertIsNone(w.cart_player.sortie)
        self.assertEqual(w.video_output_window.affiche, "noir")

    def test_decocher_pendant_video_rend_image_au_lancement_suivant(self):
        w = self.fenetre()
        w.cart_superposer = True
        w.on_cartouche_clicked(2)
        w.cart_superposer = False
        w.on_cartouche_clicked(0)
        self.assertFalse(w._cart_video_lead)
        self.assertIs(w.player.sortie, ITEM)


if __name__ == "__main__":
    unittest.main(verbosity=2)
