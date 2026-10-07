"""
test_ligne_site_internet.py — Ligne « 🌐 Site internet » de la playlist.

Une page web (ex. mur de messages qui défile) affichée comme une image : sur
la sortie vidéo si elle est ouverte (le préview en montre des captures), sinon
dans le préview. La page est chargée UNE fois et ne doit jamais être
rechargée en passant du préview à la sortie : elle perdrait son état.

Le test d'intégration utilise le vrai moteur web et la vraie fenêtre de
sortie, sur une page locale (pas besoin d'internet) dont un compteur JS
avance tout seul — s'il repartait de zéro, la page aurait été rechargée.

    python test_ligne_site_internet.py
"""

import os
import sys
import tempfile
import unittest

from PySide6.QtCore import Qt, QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  (avant QApplication)
from PySide6.QtWidgets import (QApplication, QLabel, QStackedWidget,
                               QTableWidget, QTableWidgetItem)

import core
import main_window as mw
import sequencer as sq
from web_display import WebPagePool

_app = QApplication.instance() or QApplication(sys.argv)


def attendre(ms):
    boucle = QEventLoop()
    QTimer.singleShot(ms, boucle.quit)
    boucle.exec()


def js(view, code, ms=3000):
    """Évalue `code` dans la page et rend le résultat (synchrone)."""
    res = {}
    boucle = QEventLoop()
    view.page().runJavaScript(code, 0, lambda v: (res.setdefault("v", v), boucle.quit()))
    QTimer.singleShot(ms, boucle.quit)
    boucle.exec()
    return res.get("v")


PAGE = """<!doctype html><html><body style="margin:0;background:#c03">
<h1 id="n" style="color:white;font-size:80px">0</h1>
<script>window.compteur=0;window.chargements=(window.chargements||0)+1;
setInterval(function(){compteur++;document.getElementById('n').textContent=compteur;},100);
</script></body></html>"""


class Utilitaires(unittest.TestCase):

    def test_media_icon_reconnait_un_site_meme_en_mp4(self):
        self.assertEqual(core.media_icon("WEB:https://exemple.fr/clip.mp4"), "web")
        self.assertEqual(core.media_icon("chanson.mp3"), "audio")
        self.assertEqual(core.web_url("WEB:https://a.fr/x"), "https://a.fr/x")
        self.assertEqual(core.web_url("chanson.mp3"), "")

    def test_adresse_completee_et_titre(self):
        S = sq.Sequencer
        self.assertEqual(S._normalize_url(" muramessages.flutterflow.app/ecran "),
                         "https://muramessages.flutterflow.app/ecran")
        self.assertEqual(S._normalize_url("http://a.fr"), "http://a.fr")
        self.assertEqual(S._normalize_url("   "), "")
        self.assertEqual(S._web_title("https://muramessages.flutterflow.app/ecran/"),
                         "muramessages.flutterflow.app/ecran")


class FauxSeq:
    def __init__(self, entrees):
        self.table = QTableWidget(0, 5)
        for r, data in enumerate(entrees):
            self.table.insertRow(r)
            it = QTableWidgetItem(str(data))
            it.setData(Qt.UserRole, data)
            self.table.setItem(r, 1, it)
        self.current_row = -1

    def linked_image_path(self, row):
        return None


class FauxWin:
    _output_visible            = mw.MainWindow._output_visible
    _current_web_url           = mw.MainWindow._current_web_url
    show_web                   = mw.MainWindow.show_web
    _web_preview_tick          = mw.MainWindow._web_preview_tick
    preload_web_rows           = mw.MainWindow.preload_web_rows
    _update_video_output_state = mw.MainWindow._update_video_output_state
    hide_image                 = mw.MainWindow.hide_image

    def __init__(self, seq):
        self.seq = seq
        self._cart_video_lead = False
        self._linked_image_row = None
        self.web_pages = WebPagePool()
        self.video_stack = QStackedWidget()
        self.video_stack.addWidget(QLabel("video"))
        self.image_label = QLabel()
        self.video_stack.addWidget(self.image_label)
        self.web_host_preview = QStackedWidget()
        self.video_stack.addWidget(self.web_host_preview)
        self.video_stack.resize(480, 270)
        self.video_stack.show()
        self._web_preview_timer = QTimer()
        self._web_preview_timer.timeout.connect(self._web_preview_tick)
        self.video_output_window = None


class PageVivante(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.html = os.path.join(cls.tmp, "mur.html")
        with open(cls.html, "w", encoding="utf-8") as f:
            f.write(PAGE)
        cls.url = QUrl.fromLocalFile(cls.html).toString()

    def setUp(self):
        self.seq = FauxSeq(["chanson.mp3", core.WEB_PREFIX + self.url])
        self.win = FauxWin(self.seq)
        self.win.preload_web_rows()
        self.view = self.win.web_pages.get(self.url)
        attendre(1500)

    def tearDown(self):
        self.win._web_preview_timer.stop()
        if self.win.video_output_window:
            self.win.video_output_window.hide()
        self.win.web_pages.keep_only([])
        self.win.video_stack.hide()
        attendre(200)

    def test_prechargee_une_seule_fois(self):
        self.assertEqual(self.win.web_pages.urls(), [self.url])
        self.assertEqual(js(self.view, "window.chargements"), 1)
        self.assertGreater(js(self.view, "window.compteur"), 0, "la page tourne deja")

    def test_sans_sortie_le_site_est_dans_le_preview(self):
        self.seq.current_row = 1
        self.win.show_web(self.url)
        self.assertIs(self.view.parent(), self.win.web_host_preview)
        self.assertEqual(self.win.video_stack.currentIndex(), 2)
        self.assertFalse(self.win._web_preview_timer.isActive())

    def test_sortie_ouverte_puis_fermee_sans_rechargement(self):
        self.seq.current_row = 1
        self.win.show_web(self.url)
        avant = js(self.view, "window.compteur")

        out = mw.VideoOutputWindow()
        out.resize(640, 360)
        out.show()
        self.win.video_output_window = out
        self.win._update_video_output_state()
        attendre(1200)
        self.assertEqual(out.stack.currentIndex(), out.PAGE_WEB)
        self.assertIs(out.web_host.currentWidget(), self.view)
        self.assertTrue(self.win._web_preview_timer.isActive(), "le preview montre des captures")
        self.assertEqual(self.win.video_stack.currentIndex(), 1)
        self.assertIsNotNone(self.win.image_label.pixmap())
        self.assertFalse(self.win.image_label.pixmap().isNull())

        # Fermeture de la sortie : la page revient au préview
        out.hide()
        self.win.show_web(self.win._current_web_url())
        attendre(500)
        self.assertIs(self.view.parent(), self.win.web_host_preview)
        self.assertEqual(js(self.view, "window.chargements"), 1, "jamais rechargee")
        self.assertGreater(js(self.view, "window.compteur"), avant, "le compteur a continue")

    def test_autre_media_arrete_les_captures(self):
        out = mw.VideoOutputWindow()
        out.show()
        self.win.video_output_window = out
        self.seq.current_row = 1
        self.win.show_web(self.url)
        self.assertTrue(self.win._web_preview_timer.isActive())
        self.seq.current_row = 0          # on passe sur la chanson
        self.win._web_preview_tick()
        self.assertFalse(self.win._web_preview_timer.isActive())
        self.win._update_video_output_state()
        self.assertEqual(out.stack.currentIndex(), out.PAGE_BLACK)

    def test_page_liberee_quand_la_ligne_disparait(self):
        self.seq.table.removeRow(1)
        self.win.preload_web_rows()
        self.assertEqual(self.win.web_pages.urls(), [])

    def test_cartouche_video_garde_l_image(self):
        self.win._cart_video_lead = True
        self.seq.current_row = 1
        self.win.show_web(self.url)
        self.assertNotEqual(self.win.video_stack.currentIndex(), 2)


if __name__ == "__main__":
    res = unittest.main(verbosity=2, exit=False).result
    # Sortie directe : hors d'une boucle Qt, le démontage du moteur web à la
    # fin de l'interpréteur bloque indéfiniment.
    os._exit(0 if res.wasSuccessful() else 1)
