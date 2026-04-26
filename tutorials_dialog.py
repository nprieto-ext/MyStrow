"""
TutorialsDialog — playlist YouTube MyStrow chargée en live via flux RSS.
Pas d'API key requise. Vignettes chargées de façon asynchrone.
"""
import webbrowser
import urllib.request
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt, QThread, Signal, QByteArray
from PySide6.QtGui import QPixmap, QCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QGridLayout, QSizePolicy, QFrame,
)

PLAYLIST_ID   = "PLh_Rm54lr_GtbfFQxltOA08YCUGLor4zu"
RSS_URL       = f"https://www.youtube.com/feeds/videos.xml?playlist_id={PLAYLIST_ID}"
PLAYLIST_LINK = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"

_A   = "http://www.w3.org/2005/Atom"
_YT  = "http://www.youtube.com/xml/schemas/2015"


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class _RSSFetcher(QThread):
    done  = Signal(list)
    error = Signal(str)

    def run(self):
        try:
            req = urllib.request.Request(RSS_URL, headers={"User-Agent": "MyStrow/3.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = r.read()
            root = ET.fromstring(data)
            videos = []
            for entry in root.findall(f"{{{_A}}}entry"):
                vid_id = entry.findtext(f"{{{_YT}}}videoId") or ""
                title  = entry.findtext(f"{{{_A}}}title") or "Sans titre"
                pub    = (entry.findtext(f"{{{_A}}}published") or "")[:10]
                videos.append({
                    "id":    vid_id,
                    "title": title,
                    "date":  pub,
                    "link":  f"https://www.youtube.com/watch?v={vid_id}",
                    "thumb": f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg",
                })
            self.done.emit(videos)
        except Exception as exc:
            self.error.emit(str(exc))


class _ThumbFetcher(QThread):
    done = Signal(str, QByteArray)

    def __init__(self, vid_id: str, url: str):
        super().__init__()
        self._id  = vid_id
        self._url = url

    def run(self):
        try:
            req = urllib.request.Request(self._url, headers={"User-Agent": "MyStrow/3.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                self.done.emit(self._id, QByteArray(r.read()))
        except Exception:
            self.done.emit(self._id, QByteArray())


# ---------------------------------------------------------------------------
# Video card
# ---------------------------------------------------------------------------

class _VideoCard(QFrame):
    _STYLE = """
        QFrame { background:#1e1e1e; border:1px solid #2a2a2a; border-radius:8px; }
        QFrame:hover { border:1px solid #E2CE16; background:#252525; }
    """

    def __init__(self, video: dict, parent=None):
        super().__init__(parent)
        self._link = video["link"]
        self.setStyleSheet(self._STYLE)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedWidth(265)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(5)

        self._thumb = QLabel("⏳")
        self._thumb.setFixedSize(265, 149)
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setStyleSheet(
            "background:#111; border-radius:8px 8px 0 0; color:#555; font-size:20px;"
        )
        lay.addWidget(self._thumb)

        title = QLabel(video["title"])
        title.setWordWrap(True)
        title.setFixedWidth(249)
        title.setStyleSheet("color:#eee; font-size:12px; font-weight:600; padding:0 8px;")
        lay.addWidget(title)

        if video.get("date"):
            date = QLabel(video["date"])
            date.setStyleSheet("color:#555; font-size:10px; padding:0 8px;")
            lay.addWidget(date)

    def set_thumbnail(self, data: QByteArray):
        pix = QPixmap()
        pix.loadFromData(data)
        if not pix.isNull():
            pix = pix.scaled(265, 149, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self._thumb.setPixmap(pix.copy(0, 0, 265, 149))
        else:
            self._thumb.setText("▶")

    def mousePressEvent(self, _):
        webbrowser.open(self._link)


# ---------------------------------------------------------------------------
# Dialog principal
# ---------------------------------------------------------------------------

class TutorialsDialog(QDialog):

    _BTN = """
        QPushButton {
            background:#E2CE16; color:#000; border:none;
            border-radius:6px; padding:8px 18px;
            font-weight:700; font-size:12px;
        }
        QPushButton:hover { background:#f0dc28; }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tutoriels MyStrow")
        self.setModal(True)
        self.setMinimumSize(590, 520)
        self.setStyleSheet("background:#141414; color:#eee;")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # En-tête
        hdr = QHBoxLayout()
        ttl = QLabel("📺  Tutoriels MyStrow")
        ttl.setStyleSheet("font-size:17px; font-weight:700; color:#E2CE16;")
        hdr.addWidget(ttl)
        hdr.addStretch()
        btn = QPushButton("▶  Playlist complète")
        btn.setStyleSheet(self._BTN)
        btn.clicked.connect(lambda: webbrowser.open(PLAYLIST_LINK))
        hdr.addWidget(btn)
        root.addLayout(hdr)

        sub = QLabel("Cliquez sur une vidéo pour la regarder sur YouTube")
        sub.setStyleSheet("color:#555; font-size:11px;")
        root.addWidget(sub)

        # Zone défilable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border:none; background:#141414; }")
        self._container = QWidget()
        self._container.setStyleSheet("background:#141414;")
        self._grid = QGridLayout(self._container)
        self._grid.setSpacing(12)
        self._grid.setContentsMargins(2, 2, 2, 2)
        scroll.setWidget(self._container)
        root.addWidget(scroll)

        self._status = QLabel("Chargement de la playlist…")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color:#888; font-size:13px;")
        self._grid.addWidget(self._status, 0, 0, 1, 2)

        self._cards: dict[str, _VideoCard] = {}
        self._fetchers: list[QThread] = []

        self._rss = _RSSFetcher()
        self._rss.done.connect(self._on_videos)
        self._rss.error.connect(self._on_error)
        self._rss.start()

    def _on_videos(self, videos: list):
        # Vide la grille
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if not videos:
            lbl = QLabel("Aucune vidéo trouvée dans la playlist.")
            lbl.setStyleSheet("color:#888;")
            self._grid.addWidget(lbl, 0, 0)
            return

        for i, v in enumerate(videos):
            card = _VideoCard(v)
            self._cards[v["id"]] = card
            self._grid.addWidget(card, i // 2, i % 2)

        for v in videos:
            t = _ThumbFetcher(v["id"], v["thumb"])
            t.done.connect(self._on_thumb)
            t.start()
            self._fetchers.append(t)

    def _on_thumb(self, vid_id: str, data: QByteArray):
        if vid_id in self._cards and data.size() > 0:
            self._cards[vid_id].set_thumbnail(data)

    def _on_error(self, msg: str):
        self._status.setText(
            "Impossible de charger la playlist.\n"
            "Vérifiez votre connexion internet."
        )
        self._status.setStyleSheet("color:#e44; font-size:12px;")
