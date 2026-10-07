"""
web_display.py — Pages web affichées par la playlist (ligne « 🌐 Site internet »).

Une page par URL, chargée UNE fois (dès que la ligne existe) puis gardée
vivante : un mur de messages qui défile garde son état, et passer sur la ligne
l'affiche instantanément, sans écran de chargement.

La vue n'a qu'UN parent à la fois : le préview quand la sortie vidéo est
fermée, la fenêtre de sortie sinon (le préview montre alors des captures).
Deux vues sur la même URL doubleraient le réseau, la mémoire — et le son.
Déplacer une vue d'un parent à l'autre ne recharge pas la page (vérifié).
"""

from PySide6.QtCore import QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget


RETRY_MS = 10_000          # réessai de chargement (connexion coupée)
CRASH_RELOAD_MS = 2_000    # relance après un plantage du moteur de rendu


class _QuietPage(QWebEnginePage):
    """Page muette : pas de boîte de dialogue JS (alert/confirm) qui viendrait
    bloquer la régie, pas de console dans la sortie standard."""

    def javaScriptAlert(self, origin, msg):
        print(f"[web] alert ignorée : {msg[:120]}")

    def javaScriptConfirm(self, origin, msg):
        return False

    def javaScriptPrompt(self, origin, msg, default):
        return False, ""

    def javaScriptConsoleMessage(self, level, msg, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print(f"[web] {msg[:200]}")


def block_input(view):
    """Rend la vue sourde à la souris. Le moteur reçoit les clics par un widget
    enfant créé à la demande (et recréé au changement de parent) : on pose
    l'attribut sur toute la descendance, à rappeler après chaque déplacement."""
    view.setAttribute(Qt.WA_TransparentForMouseEvents)
    for w in view.findChildren(QWidget):
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        w.setFocusPolicy(Qt.NoFocus)


class WebPagePool(QObject):
    """Vues web vivantes, indexées par URL."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._views = {}

    def urls(self):
        return list(self._views)

    def get(self, url):
        """Vue de `url`, créée et chargée au premier appel."""
        view = self._views.get(url)
        if view is None:
            view = self._create(url)
            self._views[url] = view
        return view

    def keep_only(self, urls):
        """Libère les pages dont plus aucune ligne n'a besoin."""
        garder = set(urls)
        for url in [u for u in self._views if u not in garder]:
            view = self._views.pop(url)
            view.setParent(None)
            view.deleteLater()

    def _create(self, url):
        view = QWebEngineView()
        page = _QuietPage(view)
        view.setPage(page)
        page.setBackgroundColor(QColor("black"))   # pas de flash blanc au chargement
        page.setAudioMuted(True)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
        s.setAttribute(QWebEngineSettings.ShowScrollBars, False)
        view.setContextMenuPolicy(Qt.NoContextMenu)
        # Affichage seul : un clic égaré sur l'écran de la salle (la croix d'un
        # mur de messages, un lien) ne doit rien déclencher dans la page.
        view.setFocusPolicy(Qt.NoFocus)
        block_input(view)

        retry = QTimer(view)
        retry.setSingleShot(True)
        retry.timeout.connect(lambda: view.load(QUrl(url)))

        def _fini(ok):
            block_input(view)
            if ok:
                return
            print(f"[web] chargement échoué, nouvel essai dans {RETRY_MS // 1000} s : {url}")
            retry.start(RETRY_MS)

        def _plantage(status, code):
            if status == QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus:
                return      # fermeture voulue (page libérée)
            print(f"[web] moteur de rendu arrêté ({status}, {code}) : relance de {url}")
            QTimer.singleShot(CRASH_RELOAD_MS, view.reload)

        view.loadFinished.connect(_fini)
        page.renderProcessTerminated.connect(_plantage)
        view.load(QUrl(url))
        return view
