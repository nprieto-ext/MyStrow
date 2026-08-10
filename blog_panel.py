"""
Blog IA — Génération et publication d'articles via Claude API + WordPress REST API.
Intégré dans l'AdminPanel de MyStrow.
"""

import json
import base64
import html
import re
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QSplitter, QScrollArea, QGridLayout,
    QFrame, QComboBox, QProgressBar, QCheckBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QPixmap, QImage

# ── Style (cohérent avec admin_panel.py) ─────────────────────────────────────
BG_MAIN  = "#0d0d0d"
BG_PANEL = "#111111"
BG_INPUT = "#1a1a1a"
ACCENT   = "#00d4ff"
TEXT     = "#ffffff"
TEXT_DIM = "#aaaaaa"
RED      = "#e74c3c"

WP_BASE_URL  = "https://mystrow.fr"
CONFIG_PATH  = Path.home() / ".mystrow_blog_config.json"


# ── Persistance config ────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cfg(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ── Workers (QThread) ─────────────────────────────────────────────────────────

class _MediaWorker(QObject):
    finished = Signal(list)
    error    = Signal(str)

    def __init__(self, user: str, pwd: str):
        super().__init__()
        self._user, self._pwd = user, pwd

    def run(self):
        try:
            creds = base64.b64encode(f"{self._user}:{self._pwd}".encode()).decode()
            results, page = [], 1
            while len(results) < 150:
                url = (f"{WP_BASE_URL}/wp-json/wp/v2/media"
                       f"?per_page=50&page={page}&media_type=image")
                req = urllib.request.Request(url)
                req.add_header("Authorization", f"Basic {creds}")
                with urllib.request.urlopen(req, timeout=15) as r:
                    items = json.loads(r.read())
                if not items:
                    break
                for it in items:
                    sizes = it.get("media_details", {}).get("sizes", {})
                    thumb = (sizes.get("medium", sizes.get("thumbnail", {}))
                             .get("source_url", it.get("source_url", "")))
                    results.append({
                        "id":       it["id"],
                        "url":      it.get("source_url", ""),
                        "thumb":    thumb,
                        "alt":      it.get("alt_text", "") or it.get("slug", ""),
                    })
                page += 1
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class _GenerateWorker(QObject):
    finished = Signal(str, str)   # titre, contenu HTML
    error    = Signal(str)

    def __init__(self, api_key: str, topic: str, lang: str, tone: str):
        super().__init__()
        self._key, self._topic, self._lang, self._tone = api_key, topic, lang, tone

    def run(self):
        try:
            lang_str = "en français" if self._lang == "FR" else "in English"
            system = (
                "Tu es un rédacteur web expert en logiciels d'éclairage scénique et DMX. "
                "Tu écris pour mystrow.fr, un logiciel professionnel de contrôle lumière. "
                "Écris des articles structurés avec des sous-titres <h2>, paragraphes <p>, "
                "listes <ul> si utile. Ton contenu doit être riche, précis, engageant. "
                f"Ton demandé : {self._tone}. "
                "Retourne UNIQUEMENT le HTML de l'article (sans balises html/body/head), "
                "puis une ligne vide, puis exactement : TITLE: <le titre de l'article>"
            )
            payload = json.dumps({
                "model": "claude-opus-4-6",
                "max_tokens": 2500,
                "system": system,
                "messages": [{"role": "user", "content":
                    f"Rédige un article de blog {lang_str} sur : {self._topic}"}],
            }).encode()

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload, method="POST")
            req.add_header("x-api-key", self._key)
            req.add_header("anthropic-version", "2023-06-01")
            req.add_header("content-type", "application/json")

            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read())

            text = data["content"][0]["text"].strip()
            if "\nTITLE:" in text:
                content, _, title_line = text.rpartition("\nTITLE:")
                title = title_line.strip()
            else:
                content = text
                title = self._topic[:80]

            self.finished.emit(title, content.strip())
        except Exception as e:
            self.error.emit(str(e))


class _PublishWorker(QObject):
    finished = Signal(str)   # URL article publié
    error    = Signal(str)

    def __init__(self, user: str, pwd: str, title: str, content: str,
                 featured_id, wp_status: str):
        super().__init__()
        self._user, self._pwd = user, pwd
        self._title, self._content = title, content
        self._featured_id = featured_id
        self._status = wp_status

    def run(self):
        try:
            payload: dict = {
                "title":   self._title,
                "content": self._content,
                "status":  self._status,
            }
            if self._featured_id:
                payload["featured_media"] = self._featured_id

            req = urllib.request.Request(
                f"{WP_BASE_URL}/wp-json/wp/v2/posts",
                data=json.dumps(payload).encode(), method="POST")
            creds = base64.b64encode(f"{self._user}:{self._pwd}".encode()).decode()
            req.add_header("Authorization", f"Basic {creds}")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
            self.finished.emit(result.get("link", ""))
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            self.error.emit(f"HTTP {e.code} — {body[:400]}")
        except Exception as e:
            self.error.emit(str(e))


class _DiscordWorker(QObject):
    """Relaie un article publié vers un canal Discord via webhook.

    Volontairement silencieux en cas d'échec côté remontée : l'article est
    déjà en ligne sur WordPress, un webhook mort ne doit pas ressembler à un
    échec de publication.
    """
    finished = Signal()
    error    = Signal(str)

    def __init__(self, webhook: str, title: str, excerpt: str,
                 url: str, image: str):
        super().__init__()
        self._webhook = webhook
        self._title, self._excerpt = title, excerpt
        self._url, self._image = url, image

    def run(self):
        try:
            embed = {
                "author": {"name": "Nouvel article"},
                "title":  self._title,
                "url":    self._url,
                "color":  0xE2CE16,
                "description": self._excerpt,
                "footer": {"text": "mystrow.fr"},
            }
            if self._image:
                embed["image"] = {"url": self._image}

            payload = {
                "username":   "MyStrow",
                "avatar_url": "https://mystrow.fr/og-image.webp",
                "embeds":     [embed],
            }
            req = urllib.request.Request(
                self._webhook, data=json.dumps(payload).encode("utf-8"),
                method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("User-Agent", "MyStrow/1.0")
            with urllib.request.urlopen(req, timeout=20):
                pass
            self.finished.emit()
        except urllib.error.HTTPError as e:
            self.error.emit("HTTP %s — %s" % (e.code, e.read().decode(errors="ignore")[:200]))
        except Exception as e:
            self.error.emit(str(e))


def _excerpt_from_html(content: str, limit: int = 320) -> str:
    """Transforme le HTML de l'article en resume lisible pour un embed."""
    txt = re.sub(r"(?is)<(script|style).*?</\1>", " ", content)
    txt = re.sub(r"(?i)<br\s*/?>|</p>|</h[1-6]>", "\n", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n\n", txt).strip()
    if len(txt) > limit:
        cut = txt[:limit]
        # couper sur une frontiere de phrase plutot qu'en plein mot
        stop = max(cut.rfind(". "), cut.rfind("\n"))
        txt = (cut[:stop + 1] if stop > limit // 2 else cut.rstrip()) + " […]"
    return txt


class _ThumbLoader(QObject):
    done = Signal(bytes)
    fail = Signal()

    def __init__(self, url: str):
        super().__init__()
        self._url = url

    def run(self):
        try:
            req = urllib.request.Request(
                self._url, headers={"User-Agent": "MyStrowAdmin/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                self.done.emit(r.read())
        except Exception:
            self.fail.emit()


# ── Widget miniature cliquable ────────────────────────────────────────────────

class _ThumbLabel(QLabel):
    clicked = Signal(dict)

    _IDLE     = "border: 2px solid transparent; border-radius:4px; background:#1a1a1a;"
    _SELECTED = f"border: 2px solid {ACCENT}; border-radius:4px; background:#1a1a1a;"

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.setFixedSize(74, 74)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(self._IDLE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(item.get("alt") or item["url"].split("/")[-1])
        self.setText("…")
        # Charger le thumbnail en thread
        self._start_load(item["thumb"])

    def _start_load(self, url: str):
        worker = _ThumbLoader(url)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._set_pixmap)
        worker.done.connect(thread.quit)
        worker.fail.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        # Garder les références vivantes
        self._tw, self._tt = worker, thread
        thread.start()

    def _set_pixmap(self, data: bytes):
        img = QImage()
        img.loadFromData(data)
        if not img.isNull():
            self.setPixmap(
                QPixmap.fromImage(img).scaled(
                    70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.setText("")

    def set_selected(self, selected: bool):
        self.setStyleSheet(self._SELECTED if selected else self._IDLE)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.item)
        super().mousePressEvent(event)


# ── Style helpers ─────────────────────────────────────────────────────────────

def _lbl(text: str, bold: bool = False) -> QLabel:
    l = QLabel(text)
    color = TEXT if bold else TEXT_DIM
    weight = "font-weight:bold;" if bold else ""
    l.setStyleSheet(f"color:{color}; font-size:12px; background:transparent; {weight}")
    return l

def _inp() -> str:
    return (f"QLineEdit {{ background:{BG_INPUT}; color:{TEXT}; border:1px solid #333; "
            f"border-radius:4px; padding:4px 8px; font-size:12px; }}"
            f"QLineEdit:focus {{ border:1px solid {ACCENT}; }}")

def _cmb() -> str:
    return (f"QComboBox {{ background:{BG_INPUT}; color:{TEXT}; border:1px solid #333; "
            f"border-radius:4px; padding:2px 8px; font-size:12px; }}"
            f"QComboBox::drop-down {{ border:none; }}"
            f"QComboBox QAbstractItemView {{ background:{BG_INPUT}; color:{TEXT}; "
            f"selection-background-color:{ACCENT}; selection-color:#000; }}")

def _btn_accent() -> str:
    return (f"QPushButton {{ background:{ACCENT}; color:#000; border:none; border-radius:4px; "
            f"font-weight:bold; font-size:12px; padding:0 14px; }}"
            f"QPushButton:hover {{ background:#33ddff; }}"
            f"QPushButton:disabled {{ background:#1a5566; color:#555; }}")

def _btn_sec() -> str:
    return (f"QPushButton {{ background:{BG_INPUT}; color:{TEXT_DIM}; border:1px solid #444; "
            f"border-radius:4px; font-size:12px; }}"
            f"QPushButton:hover {{ color:{TEXT}; border-color:#666; }}")


# ── Panneau principal ─────────────────────────────────────────────────────────

class BlogPanel(QWidget):
    """Panneau Blog IA : génération Claude + galerie médias WP + publication."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg = _load_cfg()
        self._media_items: list   = []
        self._featured_id         = None
        self._featured_url        = ""
        self._thumb_labels: list  = []
        self._threads: list       = []
        self._build_ui()

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_config_bar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background:#1e1e1e; width:2px; }")
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([290, 710])
        root.addWidget(splitter, 1)

    def _build_config_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(50)
        bar.setStyleSheet(f"background:{BG_PANEL}; border-bottom:1px solid #222;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(10)

        lay.addWidget(_lbl("Clé Claude :"))
        self._inp_claude = QLineEdit(self._cfg.get("claude_api_key", ""))
        self._inp_claude.setEchoMode(QLineEdit.Password)
        self._inp_claude.setPlaceholderText("sk-ant-…")
        self._inp_claude.setFixedWidth(230)
        self._inp_claude.setStyleSheet(_inp())
        lay.addWidget(self._inp_claude)

        lay.addSpacing(8)
        lay.addWidget(_lbl("WP User :"))
        self._inp_wp_user = QLineEdit(self._cfg.get("wp_user", ""))
        self._inp_wp_user.setPlaceholderText("admin")
        self._inp_wp_user.setFixedWidth(110)
        self._inp_wp_user.setStyleSheet(_inp())
        lay.addWidget(self._inp_wp_user)

        lay.addWidget(_lbl("App Password :"))
        self._inp_wp_pwd = QLineEdit(self._cfg.get("wp_pwd", ""))
        self._inp_wp_pwd.setEchoMode(QLineEdit.Password)
        self._inp_wp_pwd.setPlaceholderText("xxxx xxxx xxxx xxxx xxxx xxxx")
        self._inp_wp_pwd.setFixedWidth(215)
        self._inp_wp_pwd.setStyleSheet(_inp())
        lay.addWidget(self._inp_wp_pwd)

        lay.addSpacing(8)
        self._chk_discord = QCheckBox("→ Discord")
        self._chk_discord.setChecked(bool(self._cfg.get("discord_enabled", False)))
        self._chk_discord.setToolTip(
            "Annonce l'article sur Discord apres publication.\n"
            "Sans effet sur un brouillon.")
        self._chk_discord.setStyleSheet(f"color:{TEXT}; font-size:11px;")
        lay.addWidget(self._chk_discord)

        self._inp_discord = QLineEdit(self._cfg.get("discord_webhook", ""))
        self._inp_discord.setEchoMode(QLineEdit.Password)
        self._inp_discord.setPlaceholderText("https://discord.com/api/webhooks/…")
        self._inp_discord.setFixedWidth(200)
        self._inp_discord.setStyleSheet(_inp())
        lay.addWidget(self._inp_discord)

        btn = QPushButton("Sauvegarder")
        btn.setFixedHeight(30)
        btn.setStyleSheet(_btn_accent())
        btn.clicked.connect(self._save_cfg_ui)
        lay.addWidget(btn)

        lay.addStretch()
        return bar

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(240)
        w.setMaximumWidth(320)
        w.setStyleSheet(f"background:{BG_PANEL};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 14, 12, 14)
        lay.setSpacing(8)

        # ── Génération ────────────────────────────────────────────────────────
        lay.addWidget(_lbl("Sujet / Prompt", bold=True))

        self._inp_topic = QTextEdit()
        self._inp_topic.setPlaceholderText(
            "Ex: Comment configurer Art-Net avec MyStrow sur un réseau 2.x.x.x…")
        self._inp_topic.setFixedHeight(80)
        self._inp_topic.setStyleSheet(
            f"background:{BG_INPUT}; color:{TEXT}; border:1px solid #333; "
            f"border-radius:4px; padding:6px; font-size:12px;")
        lay.addWidget(self._inp_topic)

        row1 = QHBoxLayout()
        row1.addWidget(_lbl("Langue :"))
        self._cmb_lang = QComboBox()
        self._cmb_lang.addItems(["FR", "EN"])
        self._cmb_lang.setStyleSheet(_cmb())
        row1.addWidget(self._cmb_lang)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(_lbl("Ton :"))
        self._cmb_tone = QComboBox()
        self._cmb_tone.addItems(["Professionnel", "Pédagogique", "Commercial", "Technique"])
        self._cmb_tone.setStyleSheet(_cmb())
        row2.addWidget(self._cmb_tone)
        lay.addLayout(row2)

        self._btn_gen = QPushButton("✨  Générer l'article")
        self._btn_gen.setFixedHeight(36)
        self._btn_gen.setStyleSheet(_btn_accent())
        self._btn_gen.clicked.connect(self._on_generate)
        lay.addWidget(self._btn_gen)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar {{ border:none; background:#222; border-radius:2px; }}"
            f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:2px; }}")
        lay.addWidget(self._progress)

        # ── Séparateur médias ─────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border-top:1px solid #2a2a2a;")
        lay.addWidget(sep)

        hdr = QHBoxLayout()
        hdr.addWidget(_lbl("Photos du site", bold=True))
        hdr.addStretch()
        btn_r = QPushButton("↺")
        btn_r.setFixedSize(26, 26)
        btn_r.setStyleSheet(_btn_sec())
        btn_r.setToolTip("Actualiser la galerie depuis WordPress")
        btn_r.clicked.connect(self._load_media)
        hdr.addWidget(btn_r)
        lay.addLayout(hdr)

        hint = QLabel("Cliquer sur une photo = image principale de l'article\n"
                      "Double-clic = insérer la balise <img> dans l'éditeur")
        hint.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        self._media_container = QWidget()
        self._media_container.setStyleSheet("background:transparent;")
        self._media_grid = QGridLayout(self._media_container)
        self._media_grid.setSpacing(4)
        scroll.setWidget(self._media_container)
        lay.addWidget(scroll, 1)

        self._media_lbl = QLabel("Entrez vos identifiants WP puis cliquez ↺")
        self._media_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px;")
        self._media_lbl.setWordWrap(True)
        lay.addWidget(self._media_lbl)

        return w

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background:{BG_MAIN};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # Titre
        row_t = QHBoxLayout()
        row_t.addWidget(_lbl("Titre :"))
        self._inp_title = QLineEdit()
        self._inp_title.setPlaceholderText("Titre de l'article…")
        self._inp_title.setStyleSheet(_inp())
        row_t.addWidget(self._inp_title, 1)
        lay.addLayout(row_t)

        # Image principale sélectionnée
        self._lbl_featured = QLabel("Image principale : aucune sélectionnée")
        self._lbl_featured.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px;")
        lay.addWidget(self._lbl_featured)

        # Éditeur HTML
        lbl_ed = _lbl("Contenu HTML", bold=True)
        lay.addWidget(lbl_ed)
        self._editor = QTextEdit()
        self._editor.setPlaceholderText(
            "Le contenu HTML généré par l'IA apparaîtra ici.\n"
            "Vous pouvez l'éditer librement avant publication.\n\n"
            "Astuce : double-cliquer sur une photo dans la galerie "
            "insère la balise <img> à la position du curseur.")
        self._editor.setStyleSheet(
            f"background:{BG_INPUT}; color:{TEXT}; border:1px solid #333; "
            f"border-radius:4px; padding:8px; "
            f"font-family:'Consolas','Courier New',monospace; font-size:12px;")
        lay.addWidget(self._editor, 1)

        # Barre publication
        pub = QHBoxLayout()

        self._cmb_pub = QComboBox()
        self._cmb_pub.addItems(["Brouillon", "Publier"])
        self._cmb_pub.setStyleSheet(_cmb())
        self._cmb_pub.setFixedWidth(120)
        pub.addWidget(self._cmb_pub)

        pub.addStretch()

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px;")
        pub.addWidget(self._lbl_status)

        pub.addSpacing(10)

        self._btn_publish = QPushButton("Publier sur mystrow.fr  →")
        self._btn_publish.setFixedHeight(36)
        self._btn_publish.setStyleSheet(_btn_accent())
        self._btn_publish.clicked.connect(self._on_publish)
        pub.addWidget(self._btn_publish)

        lay.addLayout(pub)
        return w

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _save_cfg_ui(self):
        self._cfg["claude_api_key"]  = self._inp_claude.text().strip()
        self._cfg["wp_user"]         = self._inp_wp_user.text().strip()
        self._cfg["wp_pwd"]          = self._inp_wp_pwd.text().strip()
        self._cfg["discord_webhook"] = self._inp_discord.text().strip()
        self._cfg["discord_enabled"] = self._chk_discord.isChecked()
        _save_cfg(self._cfg)
        self._set_status("Config sauvegardée.")

    def _load_media(self):
        user = self._inp_wp_user.text().strip() or self._cfg.get("wp_user", "")
        pwd  = self._inp_wp_pwd.text().strip()  or self._cfg.get("wp_pwd", "")
        if not user or not pwd:
            self._media_lbl.setText("Renseignez User/App Password WordPress d'abord.")
            return
        self._media_lbl.setText("Chargement des médias…")
        self._clear_media_grid()

        worker = _MediaWorker(user, pwd)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_media_loaded)
        worker.finished.connect(thread.quit)
        worker.error.connect(lambda e: self._media_lbl.setText(f"Erreur : {e}"))
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._threads.append(thread)
        thread.start()

    def _on_media_loaded(self, items: list):
        self._media_items = items
        self._media_lbl.setText(f"{len(items)} image(s) disponible(s)")
        cols = 3
        for idx, item in enumerate(items):
            row, col = divmod(idx, cols)
            lbl = _ThumbLabel(item)
            lbl.clicked.connect(self._on_thumb_click)
            lbl.mouseDoubleClickEvent = lambda _e, it=item: self._insert_img_tag(it)
            self._media_grid.addWidget(lbl, row, col)
            self._thumb_labels.append(lbl)

    def _on_thumb_click(self, item: dict):
        self._featured_id = item["id"]
        self._featured_url = item.get("url", "")
        name = item.get("alt") or item["url"].split("/")[-1]
        self._lbl_featured.setText(f"Image principale : {name}")
        self._lbl_featured.setStyleSheet(f"color:{ACCENT}; font-size:11px;")
        for lbl in self._thumb_labels:
            lbl.set_selected(lbl.item["id"] == item["id"])

    def _insert_img_tag(self, item: dict):
        alt = item.get("alt", "")
        tag = f'<img src="{item["url"]}" alt="{alt}" style="max-width:100%;height:auto;" />'
        self._editor.insertPlainText(tag)

    def _on_generate(self):
        api_key = self._inp_claude.text().strip() or self._cfg.get("claude_api_key", "")
        topic   = self._inp_topic.toPlainText().strip()
        if not api_key:
            self._set_status("Renseignez la clé Claude API d'abord.")
            return
        if not topic:
            self._set_status("Entrez un sujet d'article.")
            return

        self._btn_gen.setEnabled(False)
        self._progress.setVisible(True)
        self._set_status("Génération en cours…")

        worker = _GenerateWorker(
            api_key, topic,
            self._cmb_lang.currentText(),
            self._cmb_tone.currentText())
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_generated)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._on_generate_error)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._threads.append(thread)
        thread.start()

    def _on_generated(self, title: str, content: str):
        self._inp_title.setText(title)
        self._editor.setPlainText(content)
        self._btn_gen.setEnabled(True)
        self._progress.setVisible(False)
        self._set_status("Article généré — vérifiez et publiez !")

    def _on_generate_error(self, err: str):
        self._btn_gen.setEnabled(True)
        self._progress.setVisible(False)
        self._set_status(f"Erreur génération : {err}", error=True)

    def _on_publish(self):
        user    = self._inp_wp_user.text().strip() or self._cfg.get("wp_user", "")
        pwd     = self._inp_wp_pwd.text().strip()  or self._cfg.get("wp_pwd", "")
        title   = self._inp_title.text().strip()
        content = self._editor.toPlainText().strip()

        if not user or not pwd:
            self._set_status("Identifiants WordPress manquants.", error=True); return
        if not title:
            self._set_status("Titre manquant.", error=True); return
        if not content:
            self._set_status("Contenu vide.", error=True); return

        wp_status = "publish" if self._cmb_pub.currentText() == "Publier" else "draft"
        # Fige le contenu tel qu'envoye : l'editeur peut etre modifie pendant
        # que la requete WordPress est en vol.
        self._pending_discord = {
            "announce": wp_status == "publish",
            "title":    title,
            "excerpt":  _excerpt_from_html(content),
            "image":    self._featured_url,
        }
        self._btn_publish.setEnabled(False)
        self._set_status("Publication en cours…")

        worker = _PublishWorker(user, pwd, title, content, self._featured_id, wp_status)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_published)
        worker.finished.connect(thread.quit)
        worker.error.connect(self._on_publish_error)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._threads.append(thread)
        thread.start()

    def _on_published(self, url: str):
        self._btn_publish.setEnabled(True)
        self._set_status(f"Publié ! {url}")
        self._announce_on_discord(url)
        if url:
            webbrowser.open(url)

    # ── Relais Discord ────────────────────────────────────────────────────────

    def _announce_on_discord(self, url: str):
        pending = getattr(self, "_pending_discord", None)
        self._pending_discord = None
        if not pending or not pending["announce"]:
            return          # brouillon : rien a annoncer
        if not self._chk_discord.isChecked():
            return
        webhook = (self._inp_discord.text().strip()
                   or self._cfg.get("discord_webhook", ""))
        if "discord.com/api/webhooks/" not in webhook or not url:
            return

        worker = _DiscordWorker(webhook, pending["title"], pending["excerpt"],
                                url, pending["image"])
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda: self._set_status(
            f"Publié et annoncé sur Discord ! {url}"))
        worker.finished.connect(thread.quit)
        worker.error.connect(self._on_discord_error)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        # Reference gardee : sans elle le QThread est collecte et Qt abort.
        self._threads.append(thread)
        thread.start()

    def _on_discord_error(self, err: str):
        # L'article EST en ligne : on le dit, sans faire passer ca pour un echec
        # de publication.
        self._set_status(f"Publié — mais l'annonce Discord a échoué : {err}",
                         error=True)

    def _on_publish_error(self, err: str):
        self._btn_publish.setEnabled(True)
        self._set_status(f"Erreur publication : {err}", error=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, error: bool = False):
        color = RED if error else TEXT_DIM
        self._lbl_status.setStyleSheet(f"color:{color}; font-size:11px;")
        self._lbl_status.setText(msg)

    def _clear_media_grid(self):
        for i in reversed(range(self._media_grid.count())):
            w = self._media_grid.itemAt(i).widget()
            if w:
                w.deleteLater()
        self._thumb_labels.clear()
        self._media_items.clear()
        self._featured_id = None
