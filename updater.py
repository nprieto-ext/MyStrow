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
import time
import threading
import urllib.request
import random
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QDialog, QMessageBox, QApplication, QFrame,
    QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QRect, QPointF, QSize
from PySide6.QtGui import (
    QFont, QFontMetricsF, QScreen, QPixmap, QDesktopServices,
    QColor, QPainter, QRadialGradient, QBrush, QPen, QIcon, QPainterPath
)

from core import VERSION, resource_path
from i18n import get_language, set_language, tr
from i18n import tr

# === SSL ===
def _make_ssl_context():
    """Contexte SSL de l'updater — délégué à core.make_ssl_context().

    L'implémentation vivait ici, et c'est précisément le problème qu'elle a
    causé : les autres clients réseau (licence, Brevo, tutoriels) ont continué
    d'utiliser un contexte certifi SEUL, donc de tomber en erreur SSL derrière
    un antivirus à scan HTTPS pendant que la mise à jour, elle, passait.
    """
    try:
        from core import make_ssl_context
        return make_ssl_context()
    except Exception:
        # Dernier recours : réseau totalement non standard
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
class _SplashTitle(QWidget):
    """Titre « MYSTROW » bicolore, centré au pixel près.

    Historique de ce petit widget — deux tentatives ratées avant lui :
      1. deux QLabel côte à côte : décalés dès que la police de repli n'avait
         pas les mêmes métriques d'une plateforme à l'autre ;
      2. un QLabel unique en texte riche : sur macOS, Qt passe alors par un
         QTextDocument qui se centre sur SA largeur idéale, pas sur celle du
         label — le titre partait ~20 px à gauche du logo et de la version.

    On mesure donc le texte nous-mêmes et on le peint. Aucune dépendance à la
    résolution de police ni au moteur de texte riche : même rendu partout.
    """

    def __init__(self, font, parent=None):
        super().__init__(parent)
        self._font = font
        fm = QFontMetricsF(font)
        # L'espacement absolu est ajouté APRÈS chaque caractère, y compris le
        # dernier : cette avance en trop décentrerait le texte vers la gauche.
        self._trailing = (font.letterSpacing()
                          if font.letterSpacingType() == QFont.AbsoluteSpacing else 0.0)
        self._w_my = fm.horizontalAdvance("MY")
        self._w_all = fm.horizontalAdvance("MYSTROW") - self._trailing
        self.setMinimumHeight(int(fm.height()) + 6)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setFont(self._font)
        fm = QFontMetricsF(self._font)
        x = (self.width() - self._w_all) / 2.0
        y = (self.height() + fm.ascent() - fm.descent()) / 2.0
        p.setPen(QColor("#ffffff"))
        p.drawText(QPointF(x, y), "MY")
        p.setPen(QColor("#FFE000"))
        p.drawText(QPointF(x + self._w_my, y), "STROW")
        p.end()


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
        # Peint à la main : ni deux labels (métriques divergentes), ni texte
        # riche (QTextDocument mal centré sur macOS). Voir _SplashTitle.
        lbl_title = _SplashTitle(_title_font)
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
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(value)

        # `full` garde le texte entier : `value` n'affiche qu'une version
        # tronquée quand la place manque (voir `_ajuster_valeur`).
        return {"layout": row, "indicator": indicator, "value": value,
                "label": label, "full": initial_value, "detail": ""}

    # Place occupée par le reste de la ligne : marges du layout du splash
    # (30+30), marges de la ligne (10+10), pastille (16) et les deux espaces
    # de 8 px. Ce qui reste est le budget du texte de droite.
    _FIXE_LIGNE_STATUT = 30 + 30 + 10 + 10 + 16 + 8 + 8

    def _ajuster_valeur(self, row):
        """Pose la valeur d'une ligne, tronquée si elle déborde encore.

        Les libellés sont volontairement courts (« Art-Net · 2.0.0.15 ») pour
        tenir dans la largeur fixe du splash ; cette élision n'est qu'un
        garde-fou, pour un port ou une IP inhabituellement longs. On coupe au
        milieu — le début (le type de sortie) et la fin (l'état) sont les deux
        parties utiles. Le détail complet reste en infobulle.
        """
        valeur = row["value"]
        plein  = row.get("full", "")
        valeur.setToolTip(row.get("detail") or plein)
        dispo = (self.width() - self._FIXE_LIGNE_STATUT
                 - row["label"].sizeHint().width())
        if dispo <= 0:
            valeur.setText(plein)
            return
        valeur.setText(valeur.fontMetrics().elidedText(
            plein, Qt.ElideMiddle, dispo))

    def set_hw_label(self, target, text):
        """Met à jour l'étiquette gauche d'une ligne de statut hardware."""
        row = getattr(self, f"status_{target}", None)
        if row and "label" in row:
            row["label"].setText(text)
            # L'étiquette de gauche mange le budget de la valeur : la
            # re-tronquer, sinon la ligne déborde à nouveau.
            self._ajuster_valeur(row)

    def set_hw_status(self, target, text, ok, detail=None):
        """Met a jour un statut hardware (akai, node, license).
        ok=True  -> vert  (connecte)
        ok=False -> rouge (erreur / non configure)
        ok=None  -> orange (configure mais non verifie)

        `detail` : texte long (nom commercial, port, IP) montré en infobulle.
        La ligne elle-même reste courte, faute de place sur le splash."""
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
        row["full"]   = text or ""
        row["detail"] = detail or ""
        self._ajuster_valeur(row)

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
class _UpdateDialog(QDialog):
    """Fenetre de telechargement — volontairement impossible a fermer par megarde.

    Le telechargement tourne dans le THREAD PRINCIPAL (boucle read() +
    processEvents) : la fenetre est le seul retour visuel, et rien ne reprend
    la main si elle disparait. Sur macOS un simple clic a cote suffisait a la
    faire passer derriere la fenetre principale — de l'avis de l'utilisateur,
    la mise a jour etait « perdue ».

    D'ou : modale applicative (les clics exterieurs ne l'atteignent plus),
    pas de bouton de fermeture, Echap neutralise, et closeEvent refuse tant que
    `verrouille` est vrai. Toutes les sorties passent par `_fermer()`, qui leve
    le verrou : ne JAMAIS appeler dlg.close() directement, la fenetre
    resterait a l'ecran."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.verrouille = True
        self.setWindowModality(Qt.ApplicationModal)

    def closeEvent(self, event):
        if self.verrouille:
            event.ignore()
        else:
            super().closeEvent(event)

    def keyPressEvent(self, event):
        # Echap declenche reject() sur un QDialog : on l'avale pendant le
        # telechargement, sinon la fenetre se ferme sans rien interrompre.
        if self.verrouille and event.key() == Qt.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

    def reject(self):
        if not self.verrouille:
            super().reject()


def _purge_update_dir(update_dir):
    """Vide les telechargements precedents du dossier temporaire.

    Un fichier encore verrouille (installeur reste ouvert) resiste a unlink() :
    on l'ignore, `_open_download_target` prendra le relais."""
    for old in update_dir.glob("MyStrow_*"):
        if old.suffix.lower() not in (".exe", ".dmg"):
            continue
        try:
            old.unlink()
        except Exception:
            pass


def _open_download_target(update_dir, filename):
    """Ouvre le fichier de destination en ecriture.

    Un installeur d'une tentative precedente reste ouvert garde un verrou sur
    le .exe : Windows refuse alors toute reecriture ([Errno 13] Permission
    denied) et AUCUNE mise a jour ne passe plus tant qu'il traine. On bascule
    dans ce cas sur un nom horodate au lieu d'echouer.

    Retourne (handle, chemin, occupe) — occupe=True si le nom canonique etait
    verrouille, ce qui signale un installeur deja en cours."""
    target = update_dir / filename
    try:
        return open(str(target), "wb"), target, False
    except PermissionError:
        pass
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    alt = update_dir / f"{target.stem}_{horodatage}{target.suffix}"
    return open(str(alt), "wb"), alt, True


def download_update(parent, version, exe_url, hash_url, sig_url=""):
    """Telecharge la mise a jour avec verification SHA256 et lance le batch updater"""

    # Sans parent, la fenetre flotte librement et passe derriere l'application
    # au premier clic exterieur (macOS) : on la rattache a la fenetre active.
    if parent is None:
        parent = QApplication.activeWindow()

    dlg = _UpdateDialog(parent)
    dlg.setWindowTitle(tr("update_dlg_title", ver=version))
    dlg.setFixedSize(460, 200)
    dlg.setWindowFlags(dlg.windowFlags()
                       & ~Qt.WindowContextHelpButtonHint
                       & ~Qt.WindowCloseButtonHint)
    dlg.setStyleSheet("background: #1e1e1e; color: #cccccc;")

    def _fermer():
        """Seule facon de fermer la fenetre : leve le verrou puis ferme."""
        dlg.verrouille = False
        dlg.close()

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
    _purge_update_dir(update_dir)

    # Détecter le type de fichier
    is_dmg       = exe_url.lower().endswith(".dmg")
    is_installer = "setup" in exe_url.lower() and not is_dmg
    if is_dmg:
        filename = "MyStrow_Installer.dmg"
    elif is_installer:
        filename = "MyStrow_Setup.exe"
    else:
        filename = "MyStrow.exe"

    # --- Telechargement ---
    installeur_occupe = False
    try:
        status_label.setText(tr("connecting_server"))
        QApplication.processEvents()
        req = urllib.request.Request(exe_url, headers={"User-Agent": "MyStrow-Updater"})
        ctx = _make_ssl_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 65536
            handle, new_file, installeur_occupe = _open_download_target(
                update_dir, filename)
            with handle as f:
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
    except PermissionError as e:
        # Meme le nom de repli est refuse : dossier verrouille par l'installeur
        # ouvert ou par l'antivirus. Le message generique ne disait pas quoi
        # faire, l'utilisateur restait bloque a chaque tentative.
        _fermer()
        QMessageBox.critical(parent, tr("err_download_title"),
                             tr("err_installer_busy_msg", err=e))
        return
    except Exception as e:
        _fermer()
        QMessageBox.critical(parent, tr("err_download_title"), tr("err_download_msg", err=e))
        return

    # Un installeur precedent tient encore le nom canonique : prevenir avant
    # d'en lancer un second par-dessus.
    if installeur_occupe:
        rep = QMessageBox.warning(
            parent, tr("installer_open_title"), tr("installer_open_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if rep != QMessageBox.Yes:
            _fermer()
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
                _fermer()
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
        _fermer()
        QMessageBox.information(parent, tr("dev_mode_title"), tr("dev_mode_msg", path=new_file))
        return

    _fermer()

    # MyStrow doit etre SORTI avant que l'installeur ne touche a MyStrow.exe.
    # On le demande donc franchement, au lieu de laisser Setup buter dessus et
    # afficher sa propre page « applications ouvertes » : celle-la, on ne
    # controle ni son moment, ni son texte, et l'utilisateur y voit une erreur
    # alors qu'il vient juste de demander une mise a jour.
    if not _confirmer_fermeture(parent, version):
        QMessageBox.information(parent, tr("upd_later_title"),
                                tr("upd_later_msg", path=str(new_file)))
        return

    is_dmg = exe_url.lower().endswith(".dmg")

    if is_dmg:
        # Mac DMG : script shell qui monte le DMG, remplace le .app, relance
        current_app = _get_mac_app_path()
        shell_path = _create_updater_shell(str(new_file), current_app)
        subprocess.Popen(
            ["bash", str(shell_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    elif is_installer:
        # L'installeur deploie MyStrow.exe ET MyStrow.exe.sig, mais il ne doit
        # surtout PAS demarrer avant que MyStrow soit sorti — voir
        # _create_installer_batch pour ce que ca cassait.
        _bat = _create_installer_batch(str(new_file), os.getpid(),
                                       _langue_installeur())
        subprocess.Popen(
            ["cmd.exe", "/c", str(_bat)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
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
        subprocess.Popen(
            ["cmd.exe", "/c", str(batch_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )

    _quitter_pour_installer(parent)


# ============================================================
# FERMETURE POUR INSTALLATION
# ============================================================

def _langue_installeur() -> str:
    """Nom de langue Inno correspondant a la langue de MyStrow.

    Doit correspondre EXACTEMENT a un `Name:` de la section [Languages] de
    maestro.iss : un nom inconnu fait echouer Setup au demarrage.
    """
    return {"fr": "french", "es": "spanish", "de": "german",
            "pt": "brazilianportuguese"}.get(get_language(), "english")


def _confirmer_fermeture(parent, version) -> bool:
    """Demande a fermer MyStrow, et propose d'enregistrer le show au passage.

    Deux choses se jouent ici. D'abord l'accord : quelqu'un peut avoir lance la
    verification en plein show sans imaginer que l'installation ferme la
    console. Ensuite le show en cours — la question « enregistrer avant de
    quitter ? » de `closeEvent` ne peut PAS servir a ce moment-la : elle
    arriverait pendant que l'installeur attend derriere, et une fenetre modale
    oubliee suffit a bloquer toute la mise a jour. On la pose donc maintenant,
    tant que rien n'attend.
    """
    fenetre = parent.window() if parent is not None else None
    seq = getattr(fenetre, "seq", None)
    show_modifie = bool(getattr(seq, "is_dirty", False))

    boite = QMessageBox(parent)
    boite.setIcon(QMessageBox.Question)
    boite.setWindowTitle(tr("upd_quit_title"))
    boite.setText(tr("upd_quit_msg", ver=version))
    b_save = None
    if show_modifie:
        boite.setInformativeText(tr("upd_quit_dirty"))
        b_save = boite.addButton(tr("upd_quit_save"), QMessageBox.AcceptRole)
    b_go = boite.addButton(tr("upd_quit_go"), QMessageBox.AcceptRole)
    b_non = boite.addButton(tr("upd_quit_cancel"), QMessageBox.RejectRole)
    boite.setDefaultButton(b_save or b_go)
    boite.exec()

    clique = boite.clickedButton()
    if clique is b_non or clique is None:
        return False
    if clique is b_save:
        try:
            # save_show() rend faux si l'utilisateur annule le selecteur de
            # fichier : on ne ferme pas derriere son dos.
            if not fenetre.save_show():
                return False
        except Exception as exc:
            print(f"[MAJ] enregistrement du show impossible : {exc}")
            return False
    return True


def _quitter_pour_installer(parent):
    """Fait REELLEMENT sortir MyStrow, pour que l'installeur trouve la place.

    `QApplication.quit()` seul ne suffit pas : il sort de la boucle
    d'evenements sans jamais appeler le moindre `closeEvent`. Ni la config AKAI
    (donc les mappings, les memoires renommees...) n'etait sauvee, ni le MIDI
    ferme, ni les serveurs tablette / Stream Deck arretes. `closeAllWindows()`
    fait tout cela avant.
    """
    app = QApplication.instance()
    fenetre = parent.window() if parent is not None else None
    if fenetre is not None:
        # Dit a closeEvent que la question du show a deja ete posee juste
        # au-dessus. La reposer ici ouvrirait une modale pendant que
        # l'installeur attend : c'est exactement le blocage qu'on corrige.
        setattr(fenetre, "_fermeture_pour_maj", True)

    # Le filet est arme AVANT de fermer quoi que ce soit : si une fenetre
    # refuse de partir ou qu'une bibliotheque native retient le processus,
    # l'installeur trouverait MyStrow encore vivant et s'arreterait sur sa
    # propre page d'applications ouvertes. A cet instant tout est deja
    # enregistre, sortir en force ne coute rien. Thread demon : il disparait
    # avec le processus si la fermeture normale aboutit d'abord.
    filet = threading.Timer(8.0, lambda: os._exit(0))
    filet.daemon = True
    filet.start()

    app.closeAllWindows()
    app.quit()


# ============================================================
# ABOUT DIALOG
# ============================================================
def _download_cloud_icon(color: str = "#8fc6ff", size: int = 18) -> QIcon:
    """Icone « nuage + fleche descendante » dessinee au QPainter.

    Pas d'emoji ni de fichier PNG : les emoji ne se rendent pas de la meme
    facon d'un Windows a l'autre, et un PNG de plus a embarquer dans le build
    est un fichier de plus a oublier dans le .spec. Ici l'icone suit la
    resolution de l'ecran (devicePixelRatio) et reste nette en HiDPI.
    """
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)

    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)

    u = size / 18.0  # tout est dessine dans une grille de reference 18x18

    # Nuage (trois bosses posees sur une base plate)
    cloud = QPainterPath()
    cloud.moveTo(4.5 * u, 11.5 * u)
    cloud.arcTo(2.0 * u, 6.5 * u, 5.0 * u, 5.0 * u, 270.0, -180.0)
    cloud.arcTo(4.5 * u, 3.25 * u, 6.5 * u, 6.5 * u, 180.0, -169.9)
    cloud.arcTo(9.5 * u, 5.5 * u, 6.0 * u, 6.0 * u, 121.1, -211.1)
    cloud.closeSubpath()
    p.drawPath(cloud)

    # Fleche vers le bas
    p.drawLine(QPointF(9.0 * u, 9.0 * u), QPointF(9.0 * u, 15.5 * u))
    p.drawLine(QPointF(6.3 * u, 12.8 * u), QPointF(9.0 * u, 15.5 * u))
    p.drawLine(QPointF(11.7 * u, 12.8 * u), QPointF(9.0 * u, 15.5 * u))
    p.end()

    return QIcon(px)


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

        # Page de telechargement du site — un vrai bouton, pas un lien : c'est
        # le recours quand la mise a jour automatique ne peut pas aboutir
        # (integrite, droits, antivirus), et « A propos » est l'ecran ou
        # l'utilisateur vient chercher sa version, donc celui ou il doit
        # trouver de quoi reinstaller. Un lien en 10 px se remarquait a peine.
        from core import SITE_URL
        btn_site = QPushButton("  " + tr("about_download_site"))
        btn_site.setFixedHeight(38)
        btn_site.setCursor(Qt.PointingHandCursor)
        btn_site.setIcon(_download_cloud_icon("#8fc6ff"))
        btn_site.setIconSize(QSize(18, 18))
        btn_site.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #1e3a52, stop:1 #16232e);
                color: #8fc6ff;
                border: 1px solid #34597a;
                border-radius: 6px;
                font-size: 11px; font-weight: 600;
                padding-left: 6px; padding-right: 6px;
                text-align: center;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #24506f, stop:1 #2a5f85);
                color: #d6ecff;
                border-color: #6fb0ea;
            }
            QPushButton:pressed {
                background: #14212c;
                color: #8fc6ff;
                border-color: #4a90d9;
            }
        """)
        btn_site.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(SITE_URL)))
        btns_lay.addWidget(btn_site, 3)

        btn_close = QPushButton(tr("btn_close"))
        btn_close.setFixedHeight(38)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton       { background: #2a2a2a; color: #888; border: 1px solid #3a3a3a;
                                border-radius: 6px; font-size: 11px; }
            QPushButton:hover { background: #333; color: #ccc; border-color: #4a4a4a; }
            QPushButton:pressed { background: #242424; }
        """)
        btn_close.clicked.connect(self.accept)
        btns_lay.addWidget(btn_close, 1)

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
        self.btn_download.setText(tr("btn_download_update"))
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
# Fiche produit de la fenêtre « Matériel recommandé ».
#
# `img_url` : la photo telle qu'elle est déjà servie par mystrow.fr. C'est par
#             là que passent TOUTES les photos de cette fenêtre : rien à
#             commiter, rien à déclarer dans les builds, et remplacer une photo
#             sur le site la remplace dans le logiciel sans publier de version.
#             Téléchargée une fois, puis gardée en cache disque.
# `img`      : fichier embarqué dans l'exe. Le chemin existe encore mais plus
#             personne ne l'emprunte, et c'est voulu : un fichier embarqué doit
#             être déclaré dans les QUATRE configurations de build
#             (MyStrow.spec, release.py, .github/workflows/release.yml,
#             build_intel_mac.sh) — en oublier une donne une photo absente sur
#             cette plateforme-là uniquement — et il fallait publier une
#             version pour changer une image. Les deux photos de contrôleurs
#             qui passaient par là pesaient 1,07 Mo dans l'installeur.
# `bandeau` : la ligne de positionnement, reprise de boutique.html pour que le
#             site et le logiciel racontent la même chose. C'est aussi là que
#             va le prix — et SEULEMENT quand il est stable. Les liens Amazon
#             bougent en permanence : un tarif figé dans un exe installé serait
#             faux la semaine suivante. Les ordres de grandeur des autres
#             modèles vivent dans les tableaux de compatibilité, plus bas.
_GEAR_IMG  = "https://mystrow.fr/img-interfaces/"
# ⚠️ /img-shop/ et NON /shop/ : /shop est l'URL de la page boutique (une
# réécriture), pas un dossier — /shop/<fichier> répond 500.
_GEAR_SHOP = "https://mystrow.fr/img-shop/"

# Cache des photos produit. Une photo téléchargée une fois n'est plus jamais
# redemandée : la fenêtre s'ouvre instantanément aux visites suivantes, et elle
# reste illustrée hors ligne. Le nom du fichier est un hachage de l'URL —
# changer la photo sur le site change l'URL de fait (nouveau contenu, même nom)
# … donc on garde AUSSI la date : au-delà d'une semaine on revalide.
_GEAR_CACHE_DIR = Path.home() / ".mystrow_cache" / "materiel"
_GEAR_CACHE_JOURS = 7


def _gear_cache_path(url: str) -> Path:
    suffixe = os.path.splitext(url.split("?")[0])[1] or ".img"
    return _GEAR_CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:20] + suffixe)


def _gear_cache_perime(chemin: Path) -> bool:
    try:
        age = time.time() - chemin.stat().st_mtime
        return age > _GEAR_CACHE_JOURS * 86400
    except Exception:
        return True


# Téléchargements en vol. Le thread n'est PAS rattaché à la fenêtre et n'est
# pas attendu à la fermeture : fermer pendant le téléchargement détruisait un
# QThread encore en train de tourner — « QThread: Destroyed while thread is
# still running », c'est-à-dire un process qui tombe. Attendre à la place
# figeait la fermeture le temps de rapatrier un mégaoctet. Le thread vit donc
# sa vie ici, écrit le cache pour la prochaine fois, et se retire de la liste
# en finissant. Si la fenêtre est partie entre-temps, Qt a déjà coupé la
# connexion vers son slot — il n'y a personne à prévenir, et c'est très bien.
_GEAR_LOADERS = []


class _GearImageLoader(QThread):
    """Télécharge les photos produit hors du fil graphique.

    Le signal ne porte que l'URL : c'est le thread qui écrit le fichier de
    cache, et la fenêtre le relit. Ainsi un téléchargement terminé après la
    fermeture profite quand même à la prochaine ouverture — et on ne fabrique
    aucun QPixmap hors du fil graphique, ce qui n'est pas permis.
    """

    charge = Signal(str)

    def __init__(self, urls):
        super().__init__(None)
        self._urls = list(urls)
        self.finished.connect(lambda: _GEAR_LOADERS.remove(self)
                              if self in _GEAR_LOADERS else None)

    def run(self):
        for u in self._urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "MyStrow"})
                with urllib.request.urlopen(req, timeout=8,
                                            context=_make_ssl_context()) as r:
                    data = r.read(4 * 1024 * 1024)
                if not data:
                    continue
                # Écrit d'abord à côté puis renommé : une fenêtre fermée ou un
                # réseau coupé en plein écrit ne doit pas laisser un fichier de
                # cache tronqué, que la prochaine ouverture afficherait comme
                # une image cassée sans jamais la retélécharger.
                chemin = _gear_cache_path(u)
                chemin.parent.mkdir(parents=True, exist_ok=True)
                tmp = chemin.with_suffix(chemin.suffix + ".part")
                tmp.write_bytes(data)
                os.replace(str(tmp), str(chemin))
                self.charge.emit(u)
            except Exception:
                # Fenêtre illustrée = confort, pas fonction vitale : hors ligne
                # ou site injoignable, l'emoji reste et on n'embête personne.
                pass

_GEAR = [
    {
        "emoji": "🎹", "nom": "AKAI APC mini mk2",
        "desc": "gear_d_akai",
        "url": "https://amzn.to/3PhCmBO",
        "couleur": "#E2CE16", "fond": "#141100",
        "img_url": _GEAR_SHOP + "AKAIAPCMINI.png",
        "bandeau": "gear_b_principal", "prix": "~89 €",
    },
    {
        "emoji": "🔌", "nom": "Node ArtNet / DMX",
        "desc": "gear_d_node",
        "url": "https://amzn.to/4tQKRCM",
        "couleur": "#00d4ff", "fond": "#1a1a1a",
        "img_url": _GEAR_IMG + "ec-node.webp",
        # Les trois bandeaux disent désormais la même chose — le nombre
        # d'univers — pour que la rangée se compare d'un coup d'œil. Ils
        # parlaient chacun d'un axe différent (usage, recommandation,
        # capacité), donc de rien de comparable.
        "bandeau": "gear_b_1univ", "prix": "~59 €",
    },
    {
        "emoji": "🔌", "nom": "USB Node ArtNet",
        # « Vrai node ArtNet en USB, sans carte réseau » ne voulait rien dire, et
        # était même faux : branché, ce boîtier SE PRÉSENTE à Windows comme une
        # carte réseau — c'est tout l'objet de la branche USB de l'assistant de
        # connexion. Ce qu'il faut dire, c'est ce qu'il remplace.
        "desc": "gear_d_usbnode",
        "url": "https://amzn.to/4w3sY4A",
        "couleur": "#a064ff", "fond": "#1a1a1a",
        "img_url": _GEAR_IMG + "ec-usb-node.webp",
        "bandeau": "gear_b_1univ", "prix": "~59 €",
    },
    {
        "emoji": "🔌", "nom": "Node ArtNet 4 univers",
        "desc": "gear_d_node4",
        "url": "https://amzn.to/4yLlyFo",
        "couleur": "#4ade80", "fond": "#1a1a1a",
        "img_url": _GEAR_IMG + "ec-node4.webp",
        "bandeau": "gear_b_4univ", "prix": "~129 €",
    },
]

# Contrôleurs recommandés — à choisir en mode "OU" (un seul suffit)
_GEAR_CONTROLLERS = [
    _GEAR[0],
    {
        "emoji": "🎹", "nom": "Novation Launchpad Mini MK3",
        "desc": "gear_d_novation",
        "url": "https://amzn.to/43j8Y1B",
        "couleur": "#E2CE16", "fond": "#141100",
        "img_url": _GEAR_SHOP + "Novation.png",
        "bandeau": "gear_b_alt_apc", "prix": "~89 €",
    },
]

_GEAR_ARTNET_COMPAT = [
    ("ENTTEC ODE Mk2",           "~200€",  "gear_c_ode"),
    ("ENTTEC EtherGate",         "~150€",  "gear_c_ethergate"),
    ("DMXking eDMX1 PRO",        "~130€",  "gear_c_edmx1"),
    ("DMXking eDMX2 PRO",        "~200€",  "gear_c_edmx2"),
    ("Node ArtNet 4 univers",    "129€",   "gear_c_node4"),
    ("Luminex Ethernet-DMX",     "~300€+", "gear_c_luminex"),
    ("Node générique (Alibaba)", "20–60€", "gear_c_generique"),
    ("ESP32 DIY + lib ArtNet",   "~10€",   "gear_c_esp32"),
]

_GEAR_USB_COMPAT = [
    ("ENTTEC DMX USB PRO",      "gear_c_usbpro"),
    ("DMXking ultraDMX Micro",  "gear_c_ultradmx"),
    ("Eurolite USB-DMX512 PRO", "gear_c_eurolite"),
    ("ENTTEC Open DMX USB",     "gear_c_opendmx"),
]

_GEAR_CONTROLLERS_COMPAT = [
    ("AKAI APC Mini MK1 & MK2",      "gear_c_apc_orig"),
    ("Novation Launchpad Mini MK3",  "gear_c_lp_reco"),
    ("Novation Launchpad Mini MK1",  "2012"),
    ("Novation Launchpad Mini MK2",  "2014"),
    ("AKAI APC40",                   ""),
    ("AKAI MIDImix",                 ""),
]


class GearDialog(QDialog):
    """Fenêtre dédiée au matériel recommandé avec liens affiliés Amazon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("up2_reco_hw"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        # Fenêtre redimensionnable : le contenu est dans une zone scrollable, on
        # se contente donc de ne jamais dépasser l'écran disponible.
        self.setMinimumSize(700, 380)
        _h, _w = 815, 900
        try:
            _avail = QApplication.primaryScreen().availableGeometry()
            _h = min(_h, _avail.height() - 60)
            _w = min(_w, _avail.width() - 40)
        except Exception:
            pass
        self.resize(_w, _h)
        self.setStyleSheet("""
            QDialog, QWidget { background: #141414; color: #cccccc;
                               font-family: 'Segoe UI', sans-serif; }
            QLabel  { border: none; background: transparent; }
        """)
        # {url: [QLabel, …]} — les vignettes qui attendent leur téléchargement.
        self._img_attente = {}
        self._img_loader = None
        self._build_ui()
        self._lancer_telechargements()

    # ── photos produit ────────────────────────────────────────────────────────

    @staticmethod
    def _poser_photo(label, chemin) -> bool:
        """Charge un fichier dans une vignette. False si l'image est illisible."""
        pm = QPixmap(str(chemin))
        if pm.isNull():
            return False
        label.setPixmap(pm.scaledToHeight(96, Qt.SmoothTransformation))
        return True

    def _lancer_telechargements(self):
        """Va chercher les photos manquantes, une fois la fenêtre construite."""
        if not self._img_attente:
            return
        # Sans parent, et gardé par la liste de module : la fenêtre peut être
        # fermée sans emporter un thread en cours d'exécution.
        self._img_loader = _GearImageLoader(self._img_attente.keys())
        _GEAR_LOADERS.append(self._img_loader)
        # Slot d'un QObject du fil graphique, PAS un lambda : la connexion est
        # alors automatiquement mise en file d'attente au passage de fil. Un
        # lambda nu se serait exécuté en connexion directe, donc dans le thread
        # de téléchargement, et aurait touché des widgets depuis là.
        self._img_loader.charge.connect(self._on_photo_recue)
        self._img_loader.start()

    def _on_photo_recue(self, url):
        """Pose la photo fraîchement mise en cache dans les vignettes en attente."""
        chemin = _gear_cache_path(url)
        for label in self._img_attente.get(url, []):
            try:
                if self._poser_photo(label, chemin):
                    label.setText("")
            except RuntimeError:
                # Vignette déjà détruite : le fichier est en cache, ça suffit.
                pass

    def _carte_produit(self, produit):
        """Une carte de la fenêtre matériel : bandeau, photo, nom, desc, CTA.

        Les deux rangées — contrôleurs et sortie DMX — en construisaient chacune
        une version, à cinquante lignes près identiques. Elles avaient déjà
        divergé : seule celle des contrôleurs affichait la photo, celle du DMX
        se contentait d'un emoji alors que les photos des boîtiers existaient.
        Un seul constructeur, donc, et les deux rangées ne peuvent plus dériver.
        """
        # `desc` et `bandeau` sont des CLÉS i18n, traduites ici et pas à
        # l'import : les listes `_GEAR*` sont construites au chargement du
        # module, donc un tr() posé là-bas figerait la langue du démarrage et
        # la fenêtre resterait dans l'ancienne langue après un changement.
        # Le nom du produit, lui, ne se traduit pas — « AKAI APC mini mk2 »
        # s'écrit pareil partout, c'est ce qui est imprimé sur le boîtier.
        emoji   = produit["emoji"]
        name    = produit["nom"]
        desc    = tr(produit["desc"])
        url     = produit["url"]
        color   = produit["couleur"]
        bg      = produit["fond"]
        img     = produit.get("img")
        bandeau = produit.get("bandeau")
        bandeau = tr(bandeau) if bandeau else None

        # Bordure teintée en rgba() et non en « #RRGGBB + 55 » : Qt ne lit pas
        # le canal alpha collé derrière un hexa à six chiffres, il relit les
        # huit comme du #AARRGGBB — d'où les liserés ROUGES qu'affichaient les
        # cartes contrôleur (#E2CE16 + 55 se relisait en CE1655).
        _c = QColor(color)
        _bord = f"rgba({_c.red()},{_c.green()},{_c.blue()},0.34)"
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {_bord};"
            f" border-radius: 10px; }}"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(16, 12, 16, 14)
        card_lay.setSpacing(8)

        # Bandeau de positionnement, comme sur boutique.html — le prix s'y
        # accroche derrière un point médian, même forme que « 4 univers · 129 € »
        # sur le site. Le tilde n'est pas décoratif : ce sont des liens
        # affiliés Amazon, dont le tarif bouge d'une semaine à l'autre alors
        # que l'exe installé, lui, ne bouge pas. Un montant sans tilde
        # passerait pour un engagement.
        prix = produit.get("prix")
        if bandeau:
            bd = QLabel(bandeau.upper())
            bd.setFont(QFont("Segoe UI", 7, QFont.Bold))
            bd.setStyleSheet(
                f"color: {color}; background: transparent; border: none;"
                " letter-spacing: 1px;"
            )
            bd.setAlignment(Qt.AlignCenter)
            bd.setWordWrap(True)
            # Hauteur de DEUX lignes, toujours : les bandeaux n'ont pas la même
            # longueur, et sans hauteur fixe les photos des trois cartes d'une
            # rangée ne démarraient pas au même niveau.
            bd.setFixedHeight(26)
            card_lay.addWidget(bd)

        # Nom AVANT la photo : bandeau, nom et prix forment l'en-tête de la
        # carte, et on sait ce qu'on regarde avant de regarder. Placé sous
        # l'image, le nom obligeait à redescendre les yeux pour identifier le
        # produit qu'on venait de voir.
        nm = QLabel(name)
        nm.setFont(QFont("Segoe UI", 9, QFont.Bold))
        nm.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        nm.setAlignment(Qt.AlignCenter)
        nm.setWordWrap(True)
        card_lay.addWidget(nm)
        if prix:
            # Espace insécable avant le symbole, sinon « ~59 » et « € » se
            # séparaient en fin de ligne.
            px = QLabel(prix.replace(" €", " €"))
            px.setFont(QFont("Segoe UI", 11, QFont.Bold))
            px.setStyleSheet("color: #e8e8e8; background: transparent; border: none;")
            px.setAlignment(Qt.AlignCenter)
            card_lay.addWidget(px)

        # Photo, dans cet ordre : fichier embarqué → cache disque → réseau.
        # L'emoji ne s'affiche que le temps du téléchargement, et reste s'il
        # échoue. Rien ne bloque : la fenêtre s'ouvre tout de suite, les photos
        # se posent quand elles arrivent.
        em = QLabel()
        em.setAlignment(Qt.AlignCenter)
        em.setStyleSheet("background: transparent; border: none;")
        em.setMinimumHeight(96)
        _img_path = resource_path(img) if img else None
        if not (_img_path and os.path.exists(_img_path)):
            _img_path = None
            _u = produit.get("img_url")
            if _u:
                _cache = _gear_cache_path(_u)
                if _cache.exists():
                    # On affiche la version en cache TOUT DE SUITE, et si elle
                    # a plus d'une semaine on la rafraîchit derrière : une photo
                    # remplacée sur le site finit par arriver, sans jamais faire
                    # attendre l'utilisateur devant une vignette vide.
                    _img_path = str(_cache)
                    if _gear_cache_perime(_cache):
                        self._img_attente.setdefault(_u, []).append(em)
                else:
                    self._img_attente.setdefault(_u, []).append(em)
        if _img_path and not self._poser_photo(em, _img_path):
            _img_path = None
        if not _img_path:
            em.setText(emoji)
            em.setFont(QFont("Segoe UI", 22))
        card_lay.addWidget(em)

        ds = QLabel(desc.replace("\n", " — "))
        ds.setFont(QFont("Segoe UI", 7))
        ds.setStyleSheet("color: #666; background: transparent; border: none;")
        ds.setAlignment(Qt.AlignCenter)
        ds.setWordWrap(True)
        card_lay.addWidget(ds)

        card_lay.addStretch()

        btn = QPushButton(tr("up2_see_amazon"))
        btn.setFixedHeight(24)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: {color}; color: #000; border: none;"
            f" border-radius: 4px; font-size: 9px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: white; }}"
        )
        btn.clicked.connect(lambda _, u=url: __import__('webbrowser').open(u))
        card_lay.addWidget(btn)
        return card

    def _chip_ou(self):
        """Le « OU » entre deux cartes qui s'excluent."""
        ou = QLabel(tr("upd_or"))
        ou.setFont(QFont("Segoe UI", 12, QFont.Black))
        ou.setStyleSheet(
            "color: #E2CE16; background: rgba(226,206,22,0.10);"
            " border: 1px solid rgba(226,206,22,0.45); border-radius: 8px;"
            " letter-spacing: 1px;"
        )
        ou.setAlignment(Qt.AlignCenter)
        # Largeur MESURÉE : 46 px codés en dur convenaient à « OU », mais
        # l'allemand écrit « ODER » et le texte touchait les deux bords.
        ou.setFixedWidth(max(46, round(
            QFontMetricsF(ou.font()).horizontalAdvance(ou.text())) + 22))
        return ou

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Zone scrollable englobant tout le contenu ─────────────────────────
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.NoFrame)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page.setStyleSheet(
            "QScrollArea { border: none; background: #141414; }"
            "QScrollBar:vertical { background: #111; width: 8px; border: none;"
            " margin: 0; }"
            "QScrollBar::handle:vertical { background: #2f2f2f; border-radius: 4px;"
            " min-height: 30px; }"
            "QScrollBar::handle:vertical:hover { background: #444; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }"
        )
        content = QWidget()
        content.setStyleSheet("background: #141414;")
        page.setWidget(content)
        outer.addWidget(page)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(32, 28, 32, 26)
        lay.setSpacing(0)

        # ── Bouton fermer (en haut à droite) ──────────────────────────────────
        top_bar = QHBoxLayout()
        top_bar.addStretch()
        btn_close_top = QPushButton(tr("upd_close"))
        btn_close_top.setFixedHeight(28)
        btn_close_top.setCursor(Qt.PointingHandCursor)
        btn_close_top.setStyleSheet("""
            QPushButton       { background: #222; color: #888; border: 1px solid #333;
                                border-radius: 4px; font-size: 11px; padding: 0 14px; }
            QPushButton:hover { background: #2a2a2a; color: #ccc; }
        """)
        btn_close_top.clicked.connect(self.accept)
        top_bar.addWidget(btn_close_top)
        lay.addLayout(top_bar)
        lay.addSpacing(8)

        # ── Titre ─────────────────────────────────────────────────────────────
        title = QLabel(tr("up2_reco_hw"))
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet("color: #E2CE16;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        sub = QLabel(tr("up2_two_products"))
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet("color: #555;")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(26)

        # ── Ligne DMX, EN PREMIER ────────────────────────────────────────────
        # L'interface passe avant le contrôleur, et pas par goût de l'ordre :
        # sans sortie DMX, MyStrow ne peut allumer aucun projecteur. Le
        # contrôleur, lui, ne fait que remplacer la souris. Ouvrir sur les
        # contrôleurs laissait croire que l'AKAI était le premier achat à faire.
        dmx_lbl = QLabel(tr("up2_for_dmx_out"))
        dmx_lbl.setFont(QFont("Segoe UI", 8))
        dmx_lbl.setStyleSheet("color: #444;")
        dmx_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(dmx_lbl)
        lay.addSpacing(6)

        dmx_row = QHBoxLayout()
        dmx_row.setSpacing(12)
        for produit in _GEAR[1:]:
            dmx_row.addWidget(self._carte_produit(produit))

        lay.addLayout(dmx_row)
        lay.addSpacing(26)

        # ── Ligne Contrôleur : AKAI | OU | Novation Launchpad ──────────────────
        # En jaune et non en gris : c'est la seule ligne de la fenêtre qui
        # évite un achat inutile, elle ne peut pas être plus discrète que les
        # produits qu'elle rend facultatifs.
        ctrl_lbl = QLabel(tr("up2_for_control_opt"))
        ctrl_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        ctrl_lbl.setStyleSheet("color: #E2CE16; letter-spacing: 1px;")
        ctrl_lbl.setAlignment(Qt.AlignCenter)
        ctrl_lbl.setWordWrap(True)
        lay.addWidget(ctrl_lbl)
        lay.addSpacing(6)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(16)

        for idx, produit in enumerate(_GEAR_CONTROLLERS):
            ctrl_row.addWidget(self._carte_produit(produit))
            if idx == 0:
                ctrl_row.addWidget(self._chip_ou())

        lay.addLayout(ctrl_row)
        lay.addSpacing(14)

        # ── Séparateur ────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #222;")
        lay.addWidget(sep)
        lay.addSpacing(8)

        compat_lbl = QLabel(tr("up2_other_models"))
        compat_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        compat_lbl.setStyleSheet("color: #444;")
        compat_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(compat_lbl)
        lay.addSpacing(6)

        # ── Liste modèles (3 colonnes) ────────────────────────────────────────
        # Pas de scroll imbriqué : la fenêtre entière défile désormais.
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
                # Les tables à prix portent (nom, prix, note) ; les autres
                # (nom, note). La note est une CLÉ i18n, traduite à l'affichage.
                name, price, note = ((item[0], item[1], item[2]) if show_price
                                     else (item[0], "", item[1]))
                row_w = QFrame()
                row_w.setStyleSheet("QFrame { background: #1a1a1a; border-radius: 4px; border: none; }")
                row_h = QHBoxLayout(row_w)
                row_h.setContentsMargins(8, 3, 8, 3)
                row_h.setSpacing(6)
                nm_lbl = QLabel(name)
                nm_lbl.setFont(QFont("Segoe UI", 8))
                nm_lbl.setStyleSheet("color: #999; background: transparent;")
                row_h.addWidget(nm_lbl, stretch=1)
                # La note était extraite de la ligne… puis jetée : personne ne
                # l'a jamais vue. La mettre en infobulle la rend lisible sans
                # ajouter une deuxième ligne à chacune des dix-huit entrées,
                # ce qui doublerait la hauteur de la fenêtre.
                if note:
                    row_w.setToolTip(tr(note))
                if show_price:
                    price_lbl = QLabel(price)
                    price_lbl.setFont(QFont("Segoe UI", 8, QFont.Bold))
                    # rgba() et non « {color}99 » : Qt relit un hexa à huit
                    # chiffres comme du #AARRGGBB, donc la couleur changeait au
                    # lieu de s'atténuer — même piège que la bordure des cartes.
                    _pc = QColor(color)
                    price_lbl.setStyleSheet(
                        f"color: rgba({_pc.red()},{_pc.green()},{_pc.blue()},0.60);"
                        " background: transparent;")
                    price_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    row_h.addWidget(price_lbl)
                section_col.addWidget(row_w)

            if not show_price and items is _GEAR_CONTROLLERS_COMPAT:
                soon_lbl = QLabel(tr("up2_more_soon"))
                soon_lbl.setFont(QFont("Segoe UI", 7))
                soon_lbl.setStyleSheet("color: #444; padding-top: 4px;")
                soon_lbl.setWordWrap(True)
                section_col.addWidget(soon_lbl)

            section_col.addStretch()
            col_container = QWidget()
            col_container.setStyleSheet("background: transparent;")
            col_container.setLayout(section_col)
            scroll_lay.addWidget(col_container)

        lay.addWidget(scroll_widget)
        lay.addSpacing(8)

        # La note « MyStrow envoie en ArtNet UDP vers 2.0.0.15:6454 » a été
        # retirée : c'est un détail de configuration réseau, et sa place est
        # dans l'assistant de connexion du boîtier, pas au bas d'une page qui
        # sert à choisir quoi acheter. La clé `upd_artnet_hint` reste dans
        # i18n.py, d'autres écrans peuvent s'en servir.

        # ── Disclaimer affilié ────────────────────────────────────────────────
        aff = QLabel(tr("up2_affiliate"))
        aff.setFont(QFont("Segoe UI", 7))
        aff.setStyleSheet("color: #2a2a2a;")
        aff.setAlignment(Qt.AlignCenter)
        aff.setWordWrap(True)
        lay.addWidget(aff)


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
    # ⚠️ NE PAS utiliser `cp -rf "$APP" "{current_app}"` : quand le bundle de
    # destination existe déjà (cas d'une MISE À JOUR), cp copie le nouveau .app
    # DEDANS → /Applications/MyStrow.app/MyStrow.app, et le bundle qui tourne
    # reste inchangé. Résultat : l'app se ferme, se rouvre sur l'ANCIENNE version,
    # « mise à jour non prise en compte ». On remplace donc le bundle en entier.
    content = f"""#!/bin/bash
sleep 2
MOUNT="/tmp/mystrow_dmg_mount_$$"
hdiutil attach "{new_dmg}" -nobrowse -quiet -mountpoint "$MOUNT" 2>/dev/null
APP=$(ls -d "$MOUNT"/*.app 2>/dev/null | head -1)
OK=0
if [ -n "$APP" ]; then
    # Staging dans le MÊME dossier que l'app (même volume → mv atomique, et ça
    # sonde qu'on a les droits d'écriture avant de toucher à l'ancien bundle).
    PARENT=$(dirname "{current_app}")
    STAGE="$PARENT/.mystrow_update_$$.app"
    rm -rf "$STAGE"
    if ditto "$APP" "$STAGE" 2>/dev/null; then
        rm -rf "{current_app}"
        if mv "$STAGE" "{current_app}" 2>/dev/null; then
            OK=1
            # Sans ça, Gatekeeper peut bloquer la copie fraîche au 1er lancement.
            xattr -dr com.apple.quarantine "{current_app}" 2>/dev/null
        fi
    fi
    rm -rf "$STAGE" 2>/dev/null
fi
hdiutil detach "$MOUNT" -quiet 2>/dev/null
if [ "$OK" = "1" ]; then
    open "{current_app}"
else
    # Échec (bundle introuvable ou droits insuffisants) : ouvrir le DMG pour que
    # l'utilisateur glisse l'app à la main, plutôt que de relancer l'ancienne.
    open "{new_dmg}"
fi
rm -f "$0"
"""
    script_path.write_text(content, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def _create_installer_batch(installer_path, pid, langue="english"):
    """Batch qui ATTEND la sortie de MyStrow avant de lancer l'installeur.

    L'installeur etait lance a 400 ms alors que l'application ne quittait qu'a
    800 ms. Inno demarrait donc pendant que MyStrow tournait encore :
    MyStrow.exe, verrouille par le processus en cours, n'etait PAS remplace,
    tandis que MyStrow.exe.sig - 221 octets, jamais verrouille - etait copie
    sans probleme. L'utilisateur se retrouvait avec le NOUVEAU .sig sur
    l'ANCIEN exe : check_exe_integrity() echouait au demarrage suivant et
    l'application refusait de se lancer (« L'integrite de l'application n'a
    pas pu etre verifiee »). Impossible d'en sortir par une mise a jour,
    puisque l'app ne demarrait plus : seule une reinstallation manuelle
    debloquait la situation.

    C'est une course : d'ou des utilisateurs touches et d'autres non, selon la
    vitesse de la machine et l'antivirus.

    L'attente est bornee (~30 s) : si le processus s'eternise on lance quand
    meme l'installeur, /CLOSEAPPLICATIONS servant alors de dernier recours.

    `/LANG` est indispensable : sans lui, Setup choisit sa langue tout seul et
    un francais se retrouvait avec les messages d'Inno en anglais — a commencer
    par celui, justement, des applications encore ouvertes.
    """
    batch_path = Path(tempfile.gettempdir()) / "mystrow_update" / "run_installer.bat"
    # Wait-Process plutot que tasklist : `tasklist` s'est revele muet dans
    # certains environnements (sortie vide, filtre ignore), donc inutilisable
    # comme condition. Un simple delai fixe n'est pas fiable non plus sur une
    # machine lente. -Timeout borne l'attente, -ErrorAction rend la main tout
    # de suite si le processus est deja parti.
    batch_content = f'''@echo off
powershell -NoProfile -NonInteractive -Command "Wait-Process -Id {pid} -Timeout 30 -ErrorAction SilentlyContinue"
ping -n 3 127.0.0.1 >nul
start "" "{installer_path}" /SILENT /CLOSEAPPLICATIONS /LANG={langue}
del "%~f0"
'''
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(batch_content, encoding="utf-8")
    return batch_path


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
