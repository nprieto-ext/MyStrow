"""
Systeme de mise a jour et ecran de chargement pour MyStrow
- SplashScreen : ecran de demarrage
- UpdateChecker : verification async des mises a jour
- UpdateBar : barre de notification de mise a jour
- download_update : telechargement + verification SHA256 + batch updater
- AkaiSplashEffect : animation LED sur l'AKAI APC mini pendant le splash
"""
import os
import sys
import json
import hashlib
import tempfile
import subprocess
import ssl
import urllib.request
import random
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QDialog, QMessageBox, QApplication, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QRect
from PySide6.QtGui import (
    QFont, QScreen, QPixmap, QDesktopServices,
    QColor, QPainter
)

from core import VERSION, resource_path
from i18n import get_language, set_language, tr

# === SSL ===
def _make_ssl_context():
    """Contexte SSL compatible Mac/Windows/PyInstaller.
    Priorité : certifi (bundlé) → contexte système → non vérifié (dernier recours)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()

# === CONSTANTES ===
_GITHUB_REPO       = "nprieto-ext/MAESTRO"
_UPDATE_API_URL    = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
_RELEASES_LATEST   = f"https://github.com/{_GITHUB_REPO}/releases/latest"
REMINDER_FILE      = Path.home() / ".maestro_update_reminder.json"


def _version_tuple(v):
    """Convertit '2.5.0' en (2, 5, 0) pour comparaison"""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def version_gt(remote, local):
    """True si remote > local"""
    return _version_tuple(remote) > _version_tuple(local)


# ============================================================
# GLITCH LOGO
# ============================================================
class GlitchLogoLabel(QWidget):
    """Logo avec effet glitch : décalage de tranches + aberration chromatique."""

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._px            = pixmap
        self._glitching     = False
        self._slices        = []   # list of (y, h, dx)
        self._rgb_shift     = 0
        self._burst_frames  = 0

        # Taille fixe : un peu plus large que le pixmap pour absorber les décalages
        self.setFixedSize(pixmap.width() + 60, pixmap.height() + 6)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        # Timer rapide pendant un burst (40 ms ≈ 25 fps)
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._next_frame)

        # Timer pour déclencher les bursts aléatoirement
        self._burst_timer = QTimer(self)
        self._burst_timer.timeout.connect(self._start_burst)

        # Burst initial : après que le splash soit bien affiché
        QTimer.singleShot(900, self._start_burst)

    def _start_burst(self):
        self._glitching    = True
        self._burst_frames = random.randint(3, 6)
        self._frame_timer.start(45)
        # Prochain burst dans 4–10 s
        self._burst_timer.start(random.randint(4000, 10000))

    def _next_frame(self):
        if self._burst_frames <= 0:
            self._glitching = False
            self._slices    = []
            self._frame_timer.stop()
            self.update()
            return
        self._burst_frames -= 1

        h   = self._px.height()
        w   = self._px.width()
        n   = random.randint(1, 3)
        slices = []
        for _ in range(n):
            sy  = random.randint(0, max(1, h - 8))
            sh  = random.randint(2, min(12, h - sy))
            dx  = random.choice([-1, 1]) * random.randint(3, 12)
            slices.append((sy, sh, dx))
        self._slices    = slices
        self._rgb_shift = random.randint(1, 3)
        self.update()

    def paintEvent(self, event):
        p   = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        ox  = (self.width()  - self._px.width())  // 2
        oy  = (self.height() - self._px.height()) // 2

        if not self._glitching or not self._slices:
            p.drawPixmap(ox, oy, self._px)
            p.end()
            return

        # Aberration chromatique : deux copies décalées, semi-transparentes
        s = self._rgb_shift
        p.setOpacity(0.13)
        p.drawPixmap(ox - s, oy, self._px)   # ghost gauche
        p.drawPixmap(ox + s, oy, self._px)   # ghost droite
        p.setOpacity(1.0)

        # Image de base
        p.drawPixmap(ox, oy, self._px)

        # Tranches décalées (clippées à leur bande)
        for (sy, sh, dx) in self._slices:
            clip = QRect(0, oy + sy, self.width(), sh)
            p.setClipRect(clip)
            p.drawPixmap(ox + dx, oy, self._px)
        p.setClipping(False)
        p.end()


# ============================================================
# SPLASH SCREEN
# ============================================================
class SplashScreen(QWidget):
    """Ecran de chargement au demarrage"""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(420, 380)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        self.setStyleSheet("""
            SplashScreen {
                background: #1a1a1a;
                border: 2px solid #00d4ff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 16)
        layout.setSpacing(8)

        # --- Logo avec effet glitch ---
        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            px = QPixmap(logo_path).scaledToHeight(80, Qt.SmoothTransformation)
            self.logo_label = GlitchLogoLabel(px, self)
            logo_row = QHBoxLayout()
            logo_row.addStretch()
            logo_row.addWidget(self.logo_label)
            logo_row.addStretch()
            layout.addLayout(logo_row)
        else:
            self.logo_label = QLabel()
            layout.addWidget(self.logo_label)

        # --- Titre bicolore MY / STROW (Bebas Neue) ---
        title = QLabel(
            '<span style="color:#ffffff; font-family:\'Bebas Neue\'; font-size:36px; letter-spacing:2px;">MY</span>'
            '<span style="color:#FFE000; font-family:\'Bebas Neue\'; font-size:36px; letter-spacing:2px;">STROW</span>'
        )
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # --- Version sous le titre ---
        ver = QLabel(f"v{VERSION}")
        ver.setFont(QFont("Segoe UI", 10))
        ver.setStyleSheet("color: #666666;")
        ver.setAlignment(Qt.AlignCenter)
        layout.addWidget(ver)

        layout.addSpacing(10)

        # --- Status hardware (AKAI, Node, Licence) ---
        self.status_akai = self._create_status_row(tr("splash_akai_label"), tr("searching"))
        layout.addLayout(self.status_akai["layout"])

        self.status_node = self._create_status_row(tr("splash_dmx_label"), tr("searching"))
        layout.addLayout(self.status_node["layout"])

        self.status_license = self._create_status_row(tr("splash_license_label"), tr("verifying"))
        layout.addLayout(self.status_license["layout"])

        layout.addSpacing(8)

        # --- Barre de progression ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminee
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                background: #333333;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #00d4ff;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress)

        self.status_label = QLabel(tr("starting_app"))
        self.status_label.setFont(QFont("Segoe UI", 9))
        self.status_label.setStyleSheet("color: #666666;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self._center_on_screen()

    def _create_status_row(self, label_text, initial_value):
        """Cree une ligne de statut avec indicateur et texte"""
        row = QHBoxLayout()
        row.setContentsMargins(10, 2, 10, 2)
        row.setSpacing(8)

        indicator = QLabel("\u25CF")  # Cercle plein
        indicator.setFont(QFont("Segoe UI", 10))
        indicator.setStyleSheet("color: #666666;")
        indicator.setFixedWidth(16)
        row.addWidget(indicator)

        label = QLabel(label_text)
        label.setFont(QFont("Segoe UI", 10))
        label.setStyleSheet("color: #cccccc;")
        row.addWidget(label)

        row.addStretch()

        value = QLabel(initial_value)
        value.setFont(QFont("Segoe UI", 10))
        value.setStyleSheet("color: #888888;")
        row.addWidget(value)

        return {"layout": row, "indicator": indicator, "value": value, "label": label}

    def set_hw_label(self, target, text):
        """Met à jour l'étiquette gauche d'une ligne de statut hardware."""
        row = getattr(self, f"status_{target}", None)
        if row and "label" in row:
            row["label"].setText(text)

    def set_hw_status(self, target, text, ok):
        """Met a jour un statut hardware (akai, node, license).
        ok=True  -> vert  (connecte)
        ok=False -> rouge (erreur / non configure)
        ok=None  -> orange (configure mais non verifie)"""
        row = getattr(self, f"status_{target}", None)
        if not row:
            return
        if ok is True:
            color = "#4CAF50"   # Vert
        elif ok is None:
            color = "#ff9800"   # Orange (configure, non verifie)
        else:
            color = "#f44336"   # Rouge
        row["indicator"].setStyleSheet(f"color: {color};")
        row["value"].setStyleSheet(f"color: {color};")
        row["value"].setText(text)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)

    def set_status(self, text):
        self.status_label.setText(text)


# ============================================================
# UPDATE CHECKER (QThread)
# ============================================================
class UpdateChecker(QThread):
    """Verifie les mises a jour disponibles en arriere-plan"""

    update_available = Signal(str, str, str, str)  # version, exe_url, hash_url, sig_url
    check_finished   = Signal(bool, str)       # found, remote_version
    check_error      = Signal(str)             # message d'erreur lisible

    def __init__(self, force=False):
        super().__init__()
        self.force = force

    @staticmethod
    def _ssl_context():
        return _make_ssl_context()

    def _get_latest_version_redirect(self):
        """Récupère la dernière version via la redirection GitHub releases/latest.
        Pas de rate limiting — aucun token requis."""
        req = urllib.request.Request(
            _RELEASES_LATEST,
            headers={"User-Agent": "MyStrow-Updater"}
        )
        ctx = self._ssl_context()
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            final_url = resp.geturl()   # URL finale après redirection
        # final_url = ".../releases/tag/v3.0.49"
        if "/tag/" not in final_url:
            return None
        tag = final_url.split("/tag/")[-1].strip()
        return tag.lstrip("v") if tag else None

    def _build_urls(self, remote_version):
        """Construit les URLs de téléchargement depuis le numéro de version."""
        base = f"https://github.com/{_GITHUB_REPO}/releases/download/v{remote_version}"
        if sys.platform == "darwin":
            return {
                "setup":  f"{base}/MyStrow_Installer.dmg",
                "sha256": "",
                "sig":    "",
            }
        return {
            "setup":  f"{base}/MyStrow_Setup.exe",
            "sha256": f"{base}/sha256.txt",
            "sig":    f"{base}/MyStrow.exe.sig",
        }

    def run(self):
        if self._reminder_active() and not self.force:
            self.check_finished.emit(False, "")
            return
        try:
            # ── 1. Obtenir la version via redirection (sans rate limit) ──
            remote_version = self._get_latest_version_redirect()

            # ── 2. Fallback API si la redirection échoue ─────────────────
            if not remote_version:
                req = urllib.request.Request(
                    _UPDATE_API_URL,
                    headers={"Accept": "application/vnd.github.v3+json",
                             "User-Agent": "MyStrow-Updater"}
                )
                with urllib.request.urlopen(req, timeout=8,
                                            context=self._ssl_context()) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                remote_version = data.get("tag_name", "").lstrip("v")

            if not remote_version:
                self.check_error.emit(tr("err_no_version"))
                return

            if not version_gt(remote_version, VERSION):
                self.check_finished.emit(False, remote_version)
                return

            # ── 3. Construire les URLs (pas d'appel API supplémentaire) ──
            urls = self._build_urls(remote_version)
            self.update_available.emit(
                remote_version, urls["setup"], urls["sha256"], urls["sig"]
            )
            self.check_finished.emit(True, remote_version)

        except urllib.error.HTTPError as e:
            if e.code == 403:
                self.check_error.emit(tr("err_github_rate_limit"))
            else:
                self.check_error.emit(tr("err_http", code=e.code, reason=e.reason))
        except urllib.error.URLError as e:
            reason = str(e.reason)
            if "AppData" in reason or "cacert" in reason.lower() or "SSL" in reason.upper():
                self.check_error.emit(tr("err_ssl"))
            else:
                self.check_error.emit(tr("err_network", reason=e.reason))
        except Exception as e:
            msg = str(e)
            if "AppData" in msg or "cacert" in msg.lower():
                self.check_error.emit(tr("err_ssl"))
            else:
                self.check_error.emit(msg)

    def _reminder_active(self):
        try:
            data = json.loads(REMINDER_FILE.read_text(encoding="utf-8"))
            remind_after = datetime.fromisoformat(data["remind_after"])
            stored_version = data.get("version", "")
            return datetime.now() < remind_after and stored_version != ""
        except Exception:
            return False

    @staticmethod
    def save_reminder(version):
        try:
            data = {
                "remind_after": (datetime.now() + timedelta(hours=24)).isoformat(),
                "version": version,
            }
            REMINDER_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass


# ============================================================
# UPDATE BAR
# ============================================================
class UpdateBar(QWidget):
    """Barre de notification mise a jour — meme style que LicenseBanner."""

    later_clicked  = Signal()
    update_clicked = Signal()

    _BG     = "#0b3d4a"
    _BORDER = "#00bcd4"
    _ACCENT = "#00bcd4"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.version  = ""
        self.exe_url  = ""
        self.hash_url = ""
        self.sig_url  = ""

        self.setFixedHeight(38)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            UpdateBar {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {self._BG}, stop:1 #1a1a1a
                );
                border: 1px solid {self._BORDER};
                border-radius: 5px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(8)

        # Icone
        icon_lbl = QLabel("↑")
        icon_lbl.setFixedWidth(18)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        icon_lbl.setStyleSheet(f"color: {self._ACCENT}; background: transparent; border: none;")
        layout.addWidget(icon_lbl)

        # Separateur vertical
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setFixedHeight(20)
        sep.setStyleSheet(f"background: {self._ACCENT}; border: none;")
        layout.addWidget(sep)

        # Texte
        self.label = QLabel()
        self.label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.label.setStyleSheet("color: #fff; background: transparent; border: none;")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label, 1)

        # Bouton Mettre a jour
        btn_update = QPushButton(tr("btn_update_arrow"))
        btn_update.setFixedHeight(24)
        btn_update.setCursor(Qt.PointingHandCursor)
        btn_update.setStyleSheet(f"""
            QPushButton {{
                color: #000; background: {self._ACCENT};
                border: none; border-radius: 3px;
                padding: 2px 12px; font-size: 9px; font-weight: bold;
            }}
            QPushButton:hover {{ background: white; }}
        """)
        btn_update.clicked.connect(self.update_clicked)
        layout.addWidget(btn_update)

        # Bouton Plus tard (croix)
        btn_later = QPushButton("✕")
        btn_later.setFixedSize(22, 22)
        btn_later.setCursor(Qt.PointingHandCursor)
        btn_later.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,0.45); background: transparent;
                border: none; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { color: white; }
        """)
        btn_later.clicked.connect(self.later_clicked)
        layout.addWidget(btn_later)

    def set_info(self, version, exe_url, hash_url, sig_url=""):
        self.version  = version
        self.exe_url  = exe_url
        self.hash_url = hash_url
        self.sig_url  = sig_url
        self.label.setText(tr("update_bar_msg", ver=version))


# ============================================================
# DOWNLOAD + INSTALL
# ============================================================
def download_update(parent, version, exe_url, hash_url, sig_url=""):
    """Telecharge la mise a jour avec verification SHA256 et lance le batch updater"""

    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("update_dlg_title", ver=version))
    dlg.setFixedSize(460, 200)
    dlg.setWindowFlags(dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    dlg.setStyleSheet("background: #1e1e1e; color: #cccccc;")

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(10)

    # --- Titre ---
    title = QLabel(tr("update_dlg_heading", ver=version))
    title.setFont(QFont("Segoe UI", 11, QFont.Bold))
    title.setStyleSheet("color: #00d4ff;")
    layout.addWidget(title)

    # --- Etapes visuelles ---
    steps_layout = QHBoxLayout()
    steps_layout.setSpacing(0)

    def _make_step(text):
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 9))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #555555; padding: 4px 10px;")
        return lbl

    step_dl   = _make_step(tr("step_download"))
    step_check = _make_step(tr("step_verify"))
    step_inst  = _make_step(tr("step_install"))

    for s in (step_dl, step_check, step_inst):
        steps_layout.addWidget(s, 1)
    layout.addLayout(steps_layout)

    # --- Barre de progression ---
    progress = QProgressBar()
    progress.setRange(0, 100)
    progress.setValue(0)
    progress.setFixedHeight(14)
    progress.setTextVisible(False)
    progress.setStyleSheet("""
        QProgressBar {
            background: #333333;
            border: none;
            border-radius: 7px;
        }
        QProgressBar::chunk {
            background: #00d4ff;
            border-radius: 7px;
        }
    """)
    layout.addWidget(progress)

    # --- Label de detail ---
    status_label = QLabel(tr("preparing"))
    status_label.setFont(QFont("Segoe UI", 9))
    status_label.setStyleSheet("color: #888888;")
    status_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(status_label)

    def _set_step(active_step):
        """Met en evidence l'etape active"""
        for s in (step_dl, step_check, step_inst):
            s.setStyleSheet("color: #555555; padding: 4px 10px;")
        active_step.setStyleSheet(
            "color: #00d4ff; font-weight: bold; padding: 4px 10px; "
            "border-bottom: 2px solid #00d4ff;"
        )

    _set_step(step_dl)
    dlg.show()
    QApplication.processEvents()

    update_dir = Path(tempfile.gettempdir()) / "mystrow_update"
    update_dir.mkdir(exist_ok=True)

    # Détecter le type de fichier
    is_dmg       = exe_url.lower().endswith(".dmg")
    is_installer = "setup" in exe_url.lower() and not is_dmg
    if is_dmg:
        filename = "MyStrow_Installer.dmg"
    elif is_installer:
        filename = "MyStrow_Setup.exe"
    else:
        filename = "MyStrow.exe"
    new_file = update_dir / filename

    # --- Telechargement ---
    try:
        status_label.setText(tr("connecting_server"))
        QApplication.processEvents()
        req = urllib.request.Request(exe_url, headers={"User-Agent": "MyStrow-Updater"})
        ctx = _make_ssl_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 65536
            with open(str(new_file), "wb") as f:
                while True:
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = min(int(downloaded * 100 / total_size), 100)
                        progress.setValue(pct)
                        dl_mb = downloaded / (1024 * 1024)
                        size_mb = total_size / (1024 * 1024)
                        status_label.setText(tr("downloading_progress", dl_mb=dl_mb, size_mb=size_mb))
                    else:
                        status_label.setText(tr("downloading"))
                    QApplication.processEvents()
    except Exception as e:
        dlg.close()
        QMessageBox.critical(parent, tr("err_download_title"), tr("err_download_msg", err=e))
        return

    # --- Verification SHA256 (seulement si sha256.txt dispo) ---
    _set_step(step_check)
    progress.setRange(0, 0)  # indetermine pendant la verif
    status_label.setText(tr("verifying_integrity"))
    QApplication.processEvents()

    if hash_url and not is_installer:
        expected_hash = ""
        try:
            with urllib.request.urlopen(hash_url, timeout=10,
                                        context=_make_ssl_context()) as resp:
                content = resp.read().decode("utf-8").strip()
                expected_hash = content.split()[0].lower()
        except Exception:
            expected_hash = ""

        if expected_hash:
            sha = hashlib.sha256()
            with open(new_file, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha.update(chunk)
            actual_hash = sha.hexdigest().lower()
            if actual_hash != expected_hash:
                dlg.close()
                try:
                    new_file.unlink()
                except Exception:
                    pass
                QMessageBox.critical(parent, tr("err_verify_title"),
                                     tr("err_verify_msg",
                                        expected=expected_hash[:16],
                                        actual=actual_hash[:16]))
                return

    # --- Installation ---
    _set_step(step_inst)
    progress.setRange(0, 0)
    status_label.setText(tr("launching_installer"))
    QApplication.processEvents()

    if not getattr(sys, 'frozen', False):
        dlg.close()
        QMessageBox.information(parent, tr("dev_mode_title"), tr("dev_mode_msg", path=new_file))
        return

    # Petite pause pour que l'utilisateur voit l'etape installation
    QTimer.singleShot(800, dlg.close)
    QTimer.singleShot(800, QApplication.quit)

    is_dmg = exe_url.lower().endswith(".dmg")

    if is_dmg:
        # Mac DMG : script shell qui monte le DMG, remplace le .app, relance
        current_app = _get_mac_app_path()
        shell_path = _create_updater_shell(str(new_file), current_app)
        QTimer.singleShot(400, lambda: subprocess.Popen(
            ["bash", str(shell_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ))
    elif is_installer:
        # Lancer l'installeur Inno Setup et quitter
        # L'installeur déploie MyStrow.exe ET MyStrow.exe.sig → intégrité garantie
        QTimer.singleShot(400, lambda: subprocess.Popen(
            [str(new_file), "/SILENT", "/CLOSEAPPLICATIONS"]
        ))
    else:
        # Fallback : batch replace (exe brut)
        # Télécharger aussi le .sig pour que check_exe_integrity() passe au redémarrage
        new_sig = None
        if sig_url:
            try:
                new_sig = update_dir / "MyStrow.exe.sig"
                urllib.request.urlretrieve(sig_url, str(new_sig))
            except Exception:
                new_sig = None   # sig indisponible : on continue sans
        current_sig = sys.executable + ".sig"
        batch_path = _create_updater_batch(str(new_file), sys.executable,
                                           str(new_sig) if new_sig else "",
                                           current_sig)
        QTimer.singleShot(400, lambda: subprocess.Popen(
            ["cmd.exe", "/c", str(batch_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        ))


# ============================================================
# ABOUT DIALOG
# ============================================================
class AboutDialog(QDialog):
    """Dialogue A propos : version actuelle + vérification des mises à jour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about_title"))
        self.setFixedSize(380, 300)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog, QWidget {
                background: #1a1a1a;
                color: #cccccc;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel  { border: none; background: transparent; }
        """)
        self._new_version = ""
        self._exe_url     = ""
        self._hash_url    = ""
        self._sig_url     = ""
        self._build_ui()
        self._start_check()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 18)
        lay.setSpacing(0)

        # Logo
        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignCenter)
        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            px = QPixmap(logo_path)
            px = px.scaledToHeight(64, Qt.SmoothTransformation)
            logo_lbl.setPixmap(px)
        lay.addWidget(logo_lbl)
        lay.addSpacing(10)

        # Nom
        name_lbl = QLabel("MyStrow")
        name_lbl.setFont(QFont("Segoe UI", 18, QFont.Bold))
        name_lbl.setStyleSheet("color: #00d4ff;")
        name_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(name_lbl)

        # Version
        ver_lbl = QLabel(f"v{VERSION}")
        ver_lbl.setFont(QFont("Segoe UI", 10))
        ver_lbl.setStyleSheet("color: #555;")
        ver_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(ver_lbl)
        lay.addSpacing(18)

        # Cadre état mise à jour
        self._update_box = QWidget()
        self._update_box.setMinimumHeight(52)
        self._update_box.setStyleSheet(
            "QWidget { background: #111; border: 1px solid #2a2a2a; border-radius: 6px; }"
        )
        box_lay = QVBoxLayout(self._update_box)
        box_lay.setContentsMargins(12, 8, 12, 8)
        box_lay.setSpacing(4)

        self.status_lbl = QLabel(tr("checking_updates"))
        self.status_lbl.setFont(QFont("Segoe UI", 9))
        self.status_lbl.setStyleSheet("color: #555; background: transparent; border: none;")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setWordWrap(True)
        box_lay.addWidget(self.status_lbl)

        self.btn_download = QPushButton()
        self.btn_download.setFixedHeight(26)
        self.btn_download.setStyleSheet("""
            QPushButton {
                background: #2d7a3a; color: white; border: none;
                border-radius: 4px; font-weight: bold; font-size: 10px;
            }
            QPushButton:hover { background: #3a9a4a; }
        """)
        self.btn_download.clicked.connect(self._on_download)
        self.btn_download.hide()
        box_lay.addWidget(self.btn_download)
        lay.addWidget(self._update_box)
        lay.addSpacing(6)

        # Lien revérifier
        self.btn_recheck = QPushButton(tr("btn_recheck"))
        self.btn_recheck.setFixedHeight(24)
        self.btn_recheck.setEnabled(False)
        self.btn_recheck.setStyleSheet("""
            QPushButton          { background: transparent; color: #444; border: none; font-size: 10px; }
            QPushButton:hover:enabled { color: #aaa; }
            QPushButton:disabled { color: #333; }
        """)
        self.btn_recheck.clicked.connect(self._start_check)
        lay.addWidget(self.btn_recheck, alignment=Qt.AlignCenter)
        lay.addStretch()

        # Boutons bas
        btns_lay = QHBoxLayout()
        btns_lay.setSpacing(8)

        btn_close = QPushButton(tr("btn_close"))
        btn_close.setFixedHeight(34)
        btn_close.setStyleSheet("""
            QPushButton       { background: #2a2a2a; color: #888; border: 1px solid #3a3a3a;
                                border-radius: 4px; font-size: 11px; }
            QPushButton:hover { background: #333; color: #ccc; }
        """)
        btn_close.clicked.connect(self.accept)
        btns_lay.addWidget(btn_close)

        lay.addLayout(btns_lay)

    # ------------------------------------------------------------------

    def _start_check(self):
        self.btn_recheck.setEnabled(False)
        self.btn_download.hide()
        self._new_version = ""
        self._exe_url     = ""
        self._hash_url    = ""
        self._sig_url     = ""
        self._update_box.setStyleSheet(
            "QWidget { background: #111; border: 1px solid #2a2a2a; border-radius: 6px; }"
        )
        self.status_lbl.setStyleSheet("color: #555; background: transparent; border: none;")
        self.status_lbl.setText(tr("checking_updates"))
        self._checker = UpdateChecker(force=True)
        self._checker.update_available.connect(self._on_update_available)
        self._checker.check_finished.connect(self._on_check_finished)
        self._checker.check_error.connect(self._on_check_error)
        self._checker.start()

    def _on_update_available(self, version, exe_url, hash_url, sig_url=""):
        self._new_version = version
        self._exe_url     = exe_url
        self._hash_url    = hash_url
        self._sig_url     = sig_url
        self._update_box.setStyleSheet(
            "QWidget { background: #111; border: 1px solid #005f6b; border-radius: 6px; }"
        )
        self.status_lbl.setStyleSheet("color: #00d4ff; background: transparent; border: none;")
        self.status_lbl.setText(tr("version_available", ver=version))
        self.btn_download.setText(tr("btn_download_ver", ver=version))
        self.btn_download.show()

    def _on_check_finished(self, found, version):
        self.btn_recheck.setEnabled(True)
        if not found:
            self._update_box.setStyleSheet(
                "QWidget { background: #111; border: 1px solid #2a4a2a; border-radius: 6px; }"
            )
            self.status_lbl.setStyleSheet("color: #4CAF50; background: transparent; border: none;")
            self.status_lbl.setText(tr("up_to_date"))
        elif not self._exe_url:
            # Ne devrait plus arriver (fallback URL dans UpdateChecker)
            self._update_box.setStyleSheet(
                "QWidget { background: #111; border: 1px solid #5a4a15; border-radius: 6px; }"
            )
            self.status_lbl.setStyleSheet("color: #c47f17; background: transparent; border: none;")
            self.status_lbl.setText(tr("update_no_installer", ver=version))

    def _on_check_error(self, error: str):
        self.btn_recheck.setEnabled(True)
        self._update_box.setStyleSheet(
            "QWidget { background: #111; border: 1px solid #6b2a2a; border-radius: 6px; }"
        )
        self.status_lbl.setStyleSheet("color: #e57373; background: transparent; border: none;")
        self.status_lbl.setText(f"⚠️  {error}")

    def _on_download(self):
        parent   = self.parent()
        version  = self._new_version
        exe_url  = self._exe_url
        hash_url = self._hash_url
        sig_url  = self._sig_url
        self.accept()
        QTimer.singleShot(100, lambda: download_update(parent, version, exe_url, hash_url, sig_url))


# ============================================================
# AKAI SPLASH EFFECT
# ============================================================
class AkaiSplashEffect:
    """
    Animation LED sur les pads de l'AKAI APC mini pendant le splash screen.

    Effet : vague diagonale qui balaie la grille 8x8 du coin haut-gauche
    au coin bas-droit, en changeant de palette de couleurs à chaque sweep.
    Palettes : cyan/bleu/violet, vert/cyan/bleu, jaune/orange/rouge, magenta/violet/bleu.
    """

    # Palettes AKAI velocity : [avant, milieu, queue]
    _PALETTES = [
        [37, 45, 53],   # Cyan -> Bleu -> Violet
        [25, 37, 45],   # Vert -> Cyan -> Bleu
        [13,  9,  3],   # Jaune -> Orange -> Rouge
        [49, 53, 45],   # Magenta -> Violet -> Bleu
    ]
    _WAVE_WIDTH   = 3   # Nombre de diagonales allumées simultanément
    _TOTAL_DIAG   = 14  # max r+c sur grille 8×8 (7+7)
    _PAUSE_FRAMES = 6   # Frames d'obscurité entre deux sweeps

    def __init__(self):
        self.midi_out    = None
        self._timer      = QTimer()
        self._timer.timeout.connect(self._tick)
        self._frame      = 0
        self._palette_idx = 0
        self._connect()

    # ------------------------------------------------------------------
    def _connect(self):
        """Ouvre le port MIDI AKAI sans bloquer le thread Qt."""
        _rt = None
        try:
            import rtmidi as _r; _rt = _r
        except ImportError:
            try:
                import rtmidi2 as _r; _rt = _r
            except ImportError:
                return
        try:
            out = _rt.MidiOut()
            for idx, name in enumerate(out.get_ports()):
                if 'APC' in name.upper() or 'MINI' in name.upper():
                    out.open_port(idx)
                    self.midi_out = out
                    return
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _tick(self):
        if not self.midi_out:
            return

        CYCLE = self._TOTAL_DIAG + self._WAVE_WIDTH + self._PAUSE_FRAMES
        wave_pos = self._frame % CYCLE
        palette  = self._PALETTES[self._palette_idx % len(self._PALETTES)]

        for row in range(8):
            for col in range(8):
                note = (7 - row) * 8 + col   # Mapping physique AKAI
                d    = row + col              # Indice diagonal (0-14)
                rel  = wave_pos - d           # Position relative au front de vague

                if 0 <= rel < self._WAVE_WIDTH:
                    vel     = palette[min(rel, len(palette) - 1)]
                    channel = 0x96 if rel == 0 else 0x90  # Avant = pleine luminosite
                else:
                    vel, channel = 0, 0x90   # Eteint

                try:
                    self.midi_out.send_message([channel, note, vel])
                except Exception:
                    return  # Port perdu, on abandonne silencieusement

        self._frame += 1

        # Changer de palette à chaque début de cycle
        if wave_pos == CYCLE - 1:
            self._palette_idx += 1

    # ------------------------------------------------------------------
    def start(self):
        """Démarre l'animation si l'AKAI est disponible."""
        if self.midi_out:
            self._frame = 0
            self._timer.start(90)   # ~11 fps

    def stop(self):
        """Arrête l'animation, éteint tous les pads et libère le port."""
        self._timer.stop()
        if self.midi_out:
            try:
                for note in range(64):
                    self.midi_out.send_message([0x90, note, 0])
            except Exception:
                pass
            try:
                self.midi_out.close_port()
            except Exception:
                pass
            self.midi_out = None

    @property
    def active(self):
        return self.midi_out is not None


def _get_mac_app_path() -> str:
    """Retourne le chemin du .app courant sur macOS.
    Dans un bundle PyInstaller : sys.executable = .../MyStrow.app/Contents/MacOS/MyStrow"""
    if getattr(sys, "frozen", False):
        # Remonter de Contents/MacOS/MyStrow → .app
        p = Path(sys.executable)
        for _ in range(3):
            p = p.parent
            if p.suffix == ".app":
                return str(p)
    # Fallback : chemin standard
    return "/Applications/MyStrow.app"


def _create_updater_shell(new_dmg: str, current_app: str) -> Path:
    """Crée le script shell de mise à jour Mac (DMG → remplacement .app + relance)."""
    script_path = Path(tempfile.gettempdir()) / "mystrow_update" / "update_mystrow.sh"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""#!/bin/bash
sleep 2
MOUNT="/tmp/mystrow_dmg_mount_$$"
hdiutil attach "{new_dmg}" -nobrowse -quiet -mountpoint "$MOUNT" 2>/dev/null
APP=$(ls -d "$MOUNT"/*.app 2>/dev/null | head -1)
if [ -n "$APP" ]; then
    cp -rf "$APP" "{current_app}"
    hdiutil detach "$MOUNT" -quiet 2>/dev/null
    open "{current_app}"
else
    hdiutil detach "$MOUNT" -quiet 2>/dev/null
    open "{new_dmg}"
fi
rm -f "$0"
"""
    script_path.write_text(content, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def _create_updater_batch(new_exe, current_exe, new_sig="", current_sig=""):
    """Cree le script batch de mise a jour (remplace exe + sig si disponibles)"""
    batch_path = Path(tempfile.gettempdir()) / "mystrow_update" / "update_mystrow.bat"

    # Copie du .sig si fourni (indispensable pour check_exe_integrity au redémarrage)
    sig_block = ""
    if new_sig and current_sig:
        sig_block = f'''
copy /y "{new_sig}" "{current_sig}" >nul 2>&1
del "{new_sig}" >nul 2>&1'''

    batch_content = f'''@echo off
echo Mise a jour MyStrow en cours...
timeout /t 2 /nobreak >nul
:retry
copy /y "{new_exe}" "{current_exe}" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto retry
){sig_block}
del "{new_exe}" >nul 2>&1
start "" "{current_exe}"
del "%~f0"
'''
    batch_path.write_text(batch_content, encoding="utf-8")
    return batch_path
