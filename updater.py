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
    QPushButton, QProgressBar, QDialog, QMessageBox, QApplication, QFrame,
    QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QRect
from PySide6.QtGui import (
    QFont, QScreen, QPixmap, QDesktopServices,
    QColor, QPainter, QRadialGradient, QBrush, QPen
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
    except Exception:
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

        # --- Logo statique (sans animation) ---
        logo_path = resource_path("logo.png")
        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setStyleSheet("background: transparent;")
        if os.path.exists(logo_path):
            px = QPixmap(logo_path).scaledToHeight(80, Qt.SmoothTransformation)
            self.logo_label.setPixmap(px)
        logo_row = QHBoxLayout()
        logo_row.addStretch()
        logo_row.addWidget(self.logo_label)
        logo_row.addStretch()
        layout.addLayout(logo_row)

        # --- Titre bicolore MY / STROW ---
        # Police avec stack de fallback : Bebas Neue (si installée) → Impact → Arial Black
        # Impact est présente sur Windows/macOS/Linux et visuellement très proche.
        _title_font = QFont()
        _title_font.setFamilies(["Bebas Neue", "Impact", "Arial Black", "Arial"])
        _title_font.setPointSize(36)
        _title_font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        # Un seul QLabel HTML évite les problèmes de centrage quand les métriques
        # de police diffèrent selon la plateforme (deux labels côte à côte pouvaient
        # sembler décalés si le font fallback avait des dimensions différentes).
        lbl_title = QLabel('<span style="color:#ffffff;">MY</span>'
                           '<span style="color:#FFE000;">STROW</span>')
        lbl_title.setFont(_title_font)
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("background: transparent;")
        layout.addWidget(lbl_title)

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
        Pas de rate limiting — aucun token requis.
        Retourne None en cas d'échec (fallback vers l'API dans run())."""
        try:
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
        except Exception:
            return None  # Fallback vers l'API GitHub

    def _build_urls(self, remote_version):
        """Construit les URLs de téléchargement depuis le numéro de version."""
        base = f"https://github.com/{_GITHUB_REPO}/releases/download/v{remote_version}"
        if sys.platform == "darwin":
            # Le DMG est nommé par architecture dans la release :
            #   Apple Silicon (M1/M2/M3/M4) → MyStrow_arm64.dmg  (build CI)
            #   Intel (x86_64)              → MyStrow_intel.dmg   (upload manuel)
            # (l'ancien nom "MyStrow_Installer.dmg" n'existe pas → 404 → faux "à jour")
            import platform as _pf
            dmg = "MyStrow_arm64.dmg" if _pf.machine() == "arm64" else "MyStrow_intel.dmg"
            return {
                "setup":  f"{base}/{dmg}",
                "sha256": "",
                "sig":    "",
            }
        return {
            "setup":  f"{base}/MyStrow_Setup.exe",
            "sha256": f"{base}/sha256.txt",
            "sig":    f"{base}/MyStrow.exe.sig",
        }

    def _dmg_available(self, url):
        """Vérifie via une requête HEAD que le DMG existe dans la release.
        Évite de présenter une mise à jour Mac quand le build CI a échoué."""
        try:
            req = urllib.request.Request(
                url, method="HEAD",
                headers={"User-Agent": "MyStrow-Updater", "Range": "bytes=0-0"}
            )
            with urllib.request.urlopen(req, timeout=8, context=self._ssl_context()):
                return True
        except urllib.error.HTTPError as e:
            return e.code not in (404, 410)
        except Exception:
            return True  # Erreur réseau : ne pas bloquer la vérification

    def _find_latest_intel_release(self):
        """Mac Intel : (version, dmg_url) de la release la plus récente possédant
        réellement un MyStrow_intel.dmg, sinon None.

        Le DMG Intel est uploadé manuellement (build sur Mac Intel séparé) et peut
        manquer sur la dernière release ; on remonte les releases pour trouver la
        dernière qui l'a effectivement.
        """
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{_GITHUB_REPO}/releases?per_page=20",
                headers={"Accept": "application/vnd.github.v3+json",
                         "User-Agent": "MyStrow-Updater"}
            )
            with urllib.request.urlopen(req, timeout=8,
                                        context=self._ssl_context()) as resp:
                releases = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

        best = None  # (version_str, url)
        for rel in releases:
            if rel.get("draft") or rel.get("prerelease"):
                continue
            ver = (rel.get("tag_name") or "").lstrip("v")
            if not ver:
                continue
            for asset in rel.get("assets", []):
                if asset.get("name") == "MyStrow_intel.dmg":
                    url = asset.get("browser_download_url")
                    if url and (best is None or version_gt(ver, best[0])):
                        best = (ver, url)
                    break
        return best

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

            # ── 4. macOS : résoudre le bon DMG selon l'architecture ──────
            if sys.platform == "darwin":
                import platform as _pf
                if _pf.machine() != "arm64":
                    # Mac Intel : le DMG Intel est uploadé manuellement et peut
                    # manquer sur la dernière release. On retombe sur la release
                    # la plus récente qui a réellement un MyStrow_intel.dmg
                    # → évite le 404 ET la boucle de maj (on s'arrête sur la
                    #   dernière version Intel réellement disponible).
                    intel = self._find_latest_intel_release()
                    if not intel or not version_gt(intel[0], VERSION):
                        self.check_finished.emit(False, remote_version)
                        return
                    remote_version = intel[0]
                    urls = self._build_urls(remote_version)
                    urls["setup"] = intel[1]   # URL exacte de l'asset Intel
                elif urls["setup"]:
                    if not self._dmg_available(urls["setup"]):
                        self.check_finished.emit(False, remote_version)
                        return

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
        layout.setContentsMargins(8, 0, 6, 0)
        layout.setSpacing(6)

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
                padding: 2px 10px; font-size: 9px; font-weight: bold;
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
        self.setFixedSize(460, 380)
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
        lay.addSpacing(18)

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
# GEAR DIALOG — Matériel recommandé
# ============================================================
_GEAR = [
    (
        "🎹",
        "AKAI APC mini mk2",
        "Le contrôleur natif MyStrow.\nGrille 8×8 LED, 9 faders, plug & play.",
        "https://amzn.to/3PhCmBO",
        "#E2CE16", "#141100",
    ),
    (
        "🔌",
        "Node ArtNet / DMX",
        "Interface réseau RJ45 → DMX512.\nIdéal clubs et installations fixes.",
        "https://amzn.to/4tQKRCM",
        "#00d4ff", "#1a1a1a",
    ),
    (
        "🔌",
        "Interface USB / DMX",
        "Branchement direct USB → DMX512.\nParfait pour débuter ou en itinérant.",
        "https://amzn.to/4n7cDbH",
        "#a064ff", "#1a1a1a",
    ),
]

_GEAR_ARTNET_COMPAT = [
    ("ENTTEC ODE Mk2",           "~200€",  "Node ArtNet 1 univers, référence"),
    ("ENTTEC EtherGate",         "~150€",  "Node compact, ArtNet/sACN"),
    ("DMXking eDMX1 PRO",        "~130€",  "Compact, ArtNet/sACN — recommandé"),
    ("DMXking eDMX2 PRO",        "~200€",  "2 univers ArtNet/sACN"),
    ("Luminex Ethernet-DMX",     "~300€+", "Pro, multi-univers"),
    ("Node générique (Alibaba)", "20–60€", "Fonctionne, qualité variable"),
    ("ESP32 DIY + lib ArtNet",   "~10€",   "Solution DIY, très répandue"),
]

_GEAR_USB_COMPAT = [
    ("ENTTEC DMX USB PRO",      "Référence absolue, drivers stables"),
    ("DMXking ultraDMX Micro",  "Compact, plug-and-play"),
    ("Eurolite USB-DMX512 PRO", "Bon rapport qualité/prix"),
    ("ENTTEC Open DMX USB",     "Nécessite lib spéciale (pyenttec)"),
]

_GEAR_CONTROLLERS_COMPAT = [
    ("AKAI APC Mini MK1 & MK2",     "Support original, inchangé"),
    ("Novation Launchpad Mini MK1", "2012"),
    ("Novation Launchpad Mini MK2", "2014"),
    ("AKAI APC40",                  ""),
    ("AKAI MIDImix",                ""),
]


class GearDialog(QDialog):
    """Fenêtre dédiée au matériel recommandé avec liens affiliés Amazon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Matériel recommandé")
        self.setFixedSize(900, 700)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog, QWidget { background: #141414; color: #cccccc;
                               font-family: 'Segoe UI', sans-serif; }
            QLabel  { border: none; background: transparent; }
        """)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(0)

        # ── Titre ─────────────────────────────────────────────────────────────
        title = QLabel("Matériel recommandé")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet("color: #E2CE16;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        sub = QLabel("2 produits suffisent pour piloter une scène entière avec MyStrow.")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet("color: #555;")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(14)

        # ── Card AKAI (horizontale, pleine largeur) ────────────────────────────
        akai_emoji, akai_name, akai_desc, akai_url, akai_color, akai_bg = _GEAR[0]
        akai_card = QFrame()
        akai_card.setStyleSheet(
            f"QFrame {{ background: {akai_bg}; border: 1px solid {akai_color}55; border-radius: 10px; }}"
        )
        akai_h = QHBoxLayout(akai_card)
        akai_h.setContentsMargins(16, 12, 16, 12)
        akai_h.setSpacing(14)

        em_akai = QLabel(akai_emoji)
        em_akai.setFont(QFont("Segoe UI", 26))
        em_akai.setStyleSheet("background: transparent; border: none;")
        akai_h.addWidget(em_akai)

        txt_col = QVBoxLayout()
        txt_col.setSpacing(2)
        nm_akai = QLabel(akai_name)
        nm_akai.setFont(QFont("Segoe UI", 11, QFont.Bold))
        nm_akai.setStyleSheet(f"color: {akai_color}; background: transparent; border: none;")
        txt_col.addWidget(nm_akai)
        ds_akai = QLabel(akai_desc.replace("\n", " — "))
        ds_akai.setFont(QFont("Segoe UI", 8))
        ds_akai.setStyleSheet("color: #666; background: transparent; border: none;")
        ds_akai.setWordWrap(True)
        txt_col.addWidget(ds_akai)
        akai_h.addLayout(txt_col, stretch=1)

        btn_akai = QPushButton("Voir sur Amazon ↗")
        btn_akai.setFixedSize(130, 28)
        btn_akai.setCursor(Qt.PointingHandCursor)
        btn_akai.setStyleSheet(
            f"QPushButton {{ background: {akai_color}; color: #000; border: none;"
            f" border-radius: 5px; font-size: 10px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: white; }}"
        )
        btn_akai.clicked.connect(lambda: __import__('webbrowser').open(akai_url))
        akai_h.addWidget(btn_akai)
        lay.addWidget(akai_card)
        lay.addSpacing(12)

        # ── Ligne DMX : Node ArtNet | OU | Interface USB/DMX ─────────────────
        dmx_lbl = QLabel("Pour la sortie DMX — choisir une option :")
        dmx_lbl.setFont(QFont("Segoe UI", 8))
        dmx_lbl.setStyleSheet("color: #444;")
        dmx_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(dmx_lbl)
        lay.addSpacing(6)

        dmx_row = QHBoxLayout()
        dmx_row.setSpacing(8)

        for idx, (emoji, name, desc, url, color, bg) in enumerate(_GEAR[1:]):
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px; }"
            )
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(12, 12, 12, 12)
            card_lay.setSpacing(4)

            em = QLabel(emoji)
            em.setFont(QFont("Segoe UI", 22))
            em.setAlignment(Qt.AlignCenter)
            em.setStyleSheet("background: transparent; border: none;")
            card_lay.addWidget(em)

            nm = QLabel(name)
            nm.setFont(QFont("Segoe UI", 9, QFont.Bold))
            nm.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            nm.setAlignment(Qt.AlignCenter)
            nm.setWordWrap(True)
            card_lay.addWidget(nm)

            ds = QLabel(desc)
            ds.setFont(QFont("Segoe UI", 7))
            ds.setStyleSheet("color: #555; background: transparent; border: none;")
            ds.setAlignment(Qt.AlignCenter)
            ds.setWordWrap(True)
            card_lay.addWidget(ds)

            card_lay.addStretch()

            btn = QPushButton("Voir sur Amazon ↗")
            btn.setFixedHeight(24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background: #E2CE16; color: #000; border: none;"
                " border-radius: 4px; font-size: 9px; font-weight: bold; }"
                "QPushButton:hover { background: white; }"
            )
            btn.clicked.connect(lambda _, u=url: __import__('webbrowser').open(u))
            card_lay.addWidget(btn)
            dmx_row.addWidget(card)

            if idx == 0:
                ou = QLabel("OU")
                ou.setFont(QFont("Segoe UI", 9, QFont.Bold))
                ou.setStyleSheet("color: #444; background: transparent; border: none;")
                ou.setAlignment(Qt.AlignCenter)
                ou.setFixedWidth(30)
                dmx_row.addWidget(ou)

        lay.addLayout(dmx_row)
        lay.addSpacing(14)

        # ── Séparateur ────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #222;")
        lay.addWidget(sep)
        lay.addSpacing(8)

        compat_lbl = QLabel("Autres modèles compatibles")
        compat_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        compat_lbl.setStyleSheet("color: #444;")
        compat_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(compat_lbl)
        lay.addSpacing(6)

        # ── Liste modèles (scrollable, 2 colonnes) ────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { background: #111; width: 5px; border: none; }"
            "QScrollBar::handle:vertical { background: #2a2a2a; border-radius: 2px; }"
        )

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        scroll_lay = QHBoxLayout(scroll_widget)
        scroll_lay.setContentsMargins(0, 0, 4, 0)
        scroll_lay.setSpacing(12)

        for section_title, items, color, show_price in [
            ("🎹  Contrôleurs compatibles", _GEAR_CONTROLLERS_COMPAT, "#E2CE16", False),
            ("🔌  Nodes ArtNet / DMX",      _GEAR_ARTNET_COMPAT,      "#00d4ff", True),
            ("🔌  Interfaces USB / DMX",    _GEAR_USB_COMPAT,         "#a064ff", False),
        ]:
            section_col = QVBoxLayout()
            section_col.setSpacing(3)
            sec_lbl = QLabel(section_title)
            sec_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
            sec_lbl.setStyleSheet(f"color: {color};")
            section_col.addWidget(sec_lbl)

            for item in items:
                name, price, note = (item[0], item[1], "") if show_price else (item[0], "", item[1])
                row_w = QFrame()
                row_w.setStyleSheet("QFrame { background: #1a1a1a; border-radius: 4px; border: none; }")
                row_h = QHBoxLayout(row_w)
                row_h.setContentsMargins(8, 3, 8, 3)
                row_h.setSpacing(6)
                nm_lbl = QLabel(name)
                nm_lbl.setFont(QFont("Segoe UI", 8))
                nm_lbl.setStyleSheet("color: #999; background: transparent;")
                row_h.addWidget(nm_lbl, stretch=1)
                if show_price:
                    price_lbl = QLabel(price)
                    price_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
                    price_lbl.setStyleSheet(f"color: {color}99; background: transparent;")
                    price_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    row_h.addWidget(price_lbl)
                section_col.addWidget(row_w)

            if not show_price and items is _GEAR_CONTROLLERS_COMPAT:
                soon_lbl = QLabel("⏳  D'autres contrôleurs arrivent prochainement")
                soon_lbl.setFont(QFont("Segoe UI", 7))
                soon_lbl.setStyleSheet("color: #444; padding-top: 4px;")
                soon_lbl.setWordWrap(True)
                section_col.addWidget(soon_lbl)

            section_col.addStretch()
            col_container = QWidget()
            col_container.setStyleSheet("background: transparent;")
            col_container.setLayout(section_col)
            scroll_lay.addWidget(col_container)

        scroll.setWidget(scroll_widget)
        scroll.setFixedHeight(150)
        lay.addWidget(scroll)
        lay.addSpacing(8)

        # ── Note technique ────────────────────────────────────────────────────
        note_tech = QLabel(
            "💡  MyStrow envoie en ArtNet UDP vers 2.0.0.15:6454 — "
            "un Node ArtNet est recommandé en production (aucun driver, faible latence)."
        )
        note_tech.setFont(QFont("Segoe UI", 7))
        note_tech.setStyleSheet("color: #333;")
        note_tech.setAlignment(Qt.AlignCenter)
        note_tech.setWordWrap(True)
        lay.addWidget(note_tech)
        lay.addSpacing(4)

        # ── Disclaimer affilié ────────────────────────────────────────────────
        aff = QLabel("* Liens affiliés Amazon — si vous achetez via ces liens, nous percevons une petite commission sans aucun surcoût pour vous.")
        aff.setFont(QFont("Segoe UI", 7))
        aff.setStyleSheet("color: #2a2a2a;")
        aff.setAlignment(Qt.AlignCenter)
        aff.setWordWrap(True)
        lay.addWidget(aff)
        lay.addSpacing(8)

        # ── Bouton fermer ─────────────────────────────────────────────────────
        btn_close = QPushButton("Fermer")
        btn_close.setFixedHeight(30)
        btn_close.setStyleSheet("""
            QPushButton       { background: #222; color: #888; border: 1px solid #333;
                                border-radius: 4px; font-size: 11px; }
            QPushButton:hover { background: #2a2a2a; color: #ccc; }
        """)
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close)


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
