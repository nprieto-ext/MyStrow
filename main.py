#!/usr/bin/env python3
"""
Maestro - Controleur Lumiere DMX
Point d'entree principal de l'application

Structure des modules:
- config.py            : Imports, constantes, utilitaires
- projector.py         : Classe Projector
- midi_handler.py      : Classe MIDIHandler
- artnet_dmx.py        : Classe ArtNetDMX
- audio_ai.py          : Classe AudioColorAI
- ui_components.py     : Widgets UI
- plan_de_feu.py       : Plan de feu
- recording_waveform.py: Analyse audio
- sequencer.py         : Sequencer
- light_timeline.py    : Timeline lumiere
- timeline_editor.py   : Editeur de timeline
- main_window.py       : Fenetre principale
- updater.py           : Splash screen et mise a jour
- license_manager.py   : Systeme de licence
- license_ui.py        : Interface licence
"""

# ------------------------------------------------------------------
# FIX PYINSTALLER / IMPORTS
# ------------------------------------------------------------------
import sys
import os
import time
import faulthandler
import traceback

# Fix SSL certificates sur macOS + PyInstaller :
# certifi est bundlé dans _MEIPASS mais ssl ne le trouve pas automatiquement.
# Forcer SSL_CERT_FILE avant tout import réseau.
if sys.platform == "darwin":
    try:
        import certifi as _certifi
        _ca = _certifi.where()
        if _ca and os.path.exists(_ca):
            os.environ.setdefault("SSL_CERT_FILE", _ca)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)
    except Exception:
        pass

# Fix encodage console Windows (cp1252 ne supporte pas les emojis)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ------------------------------------------------------------------
# BACKEND VIDÉO — diagnostic uniquement (on NE force PAS le backend).
# But : savoir quels plugins multimedia sont réellement embarqués. Forcer FFmpeg
# via QT_MEDIA_BACKEND blanchissait la vidéo dans le visualisateur sur certaines
# config (rendu QVideoWidget). On laisse donc Qt choisir son backend par défaut ;
# le packaging (MyStrow.spec) se contente de rendre le plugin FFmpeg DISPONIBLE.
# ------------------------------------------------------------------
def _log_media_backend():
    try:
        import PySide6
        _roots = [os.path.dirname(PySide6.__file__)]
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            _roots += [sys._MEIPASS, os.path.join(sys._MEIPASS, 'PySide6')]
        _plugins = []
        for _root in _roots:
            _mm = os.path.join(_root, 'plugins', 'multimedia')
            if os.path.isdir(_mm):
                _plugins = os.listdir(_mm)
                break
        _has_ffmpeg = any('ffmpeg' in f.lower() for f in _plugins)
        _forced = os.environ.get("QT_MEDIA_BACKEND", "(defaut Qt)")
        print(f"[Media] Plugins multimedia: {_plugins or 'AUCUN'} | ffmpeg dispo={'oui' if _has_ffmpeg else 'non'} | backend={_forced}")
    except Exception as _e:
        print(f"[Media] diagnostic backend impossible: {_e}")

_log_media_backend()

# Sur Mac (app bundle PyInstaller) : log complet avant tout import Qt
# faulthandler capture aussi les segfaults (crash Qt natif, dylib manquante…)
_MAC_LOG_FILE = None
if sys.platform == "darwin" and getattr(sys, 'frozen', False):
    try:
        import platform as _plt
        _log_dir = os.path.join(os.path.expanduser("~"), "Library", "Logs", "MyStrow")
        os.makedirs(_log_dir, exist_ok=True)
        _log_path = os.path.join(_log_dir, "crash.log")
        _MAC_LOG_FILE = open(_log_path, "w", encoding="utf-8", buffering=1)
        sys.stdout = _MAC_LOG_FILE
        sys.stderr = _MAC_LOG_FILE
        faulthandler.enable(file=_MAC_LOG_FILE, all_threads=True)
        print(f"[MyStrow] === STARTUP LOG ===", flush=True)
        print(f"[MyStrow] Python   : {sys.version}", flush=True)
        print(f"[MyStrow] macOS    : {_plt.mac_ver()[0]}", flush=True)
        print(f"[MyStrow] Machine  : {_plt.machine()}", flush=True)
        print(f"[MyStrow] _MEIPASS : {getattr(sys, '_MEIPASS', 'N/A')}", flush=True)
        print(f"[MyStrow] argv[0]  : {sys.argv[0]}", flush=True)
        print(f"", flush=True)
        # Variables Qt nécessaires sur macOS 26 Tahoe pour le rendu Cocoa
        os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
        # Debug plugins Qt → capturé dans le log si libqcocoa.dylib manque
        os.environ.setdefault("QT_DEBUG_PLUGINS", "1")
    except Exception:
        pass


# ------------------------------------------------------------------
# CAPTURE DES CRASHS — Windows / Linux (macOS frozen a son propre bloc ci-dessus)
# But : un crash NATIF (segfault Qt, plugin multimedia ffmpeg/WMF, driver audio,
# décodage d'un .wav/.mp4 exotique…) ne laisse AUCUNE trace sur Windows sans
# faulthandler. On écrit dans un log dédié, gardé ouvert toute la vie du process,
# + un excepthook global pour les exceptions Python non rattrapées.
# ------------------------------------------------------------------
_CRASH_LOG_FILE = None
if not (sys.platform == "darwin" and getattr(sys, "frozen", False)):
    try:
        if sys.platform == "win32":
            _cl_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "MyStrow", "Logs")
        else:
            _cl_dir = os.path.join(os.path.expanduser("~"), ".mystrow_logs")
        os.makedirs(_cl_dir, exist_ok=True)
        _cl_path = os.path.join(_cl_dir, "faulthandler.log")
        # Plafond : repartir à zéro si le fichier dépasse 5 Mo (évite l'inflation)
        _cl_mode = "a"
        try:
            if os.path.exists(_cl_path) and os.path.getsize(_cl_path) > 5 * 1024 * 1024:
                _cl_mode = "w"
        except Exception:
            pass
        _CRASH_LOG_FILE = open(_cl_path, _cl_mode, encoding="utf-8", buffering=1)
        import datetime as _dt
        print(f"\n===== MyStrow session {_dt.datetime.now().isoformat()} =====",
              file=_CRASH_LOG_FILE, flush=True)
        # Capture des crashs natifs (segfault, abort) avec pile C de tous les threads
        faulthandler.enable(file=_CRASH_LOG_FILE, all_threads=True)

        # Capture des exceptions Python non rattrapées au niveau global
        _prev_excepthook = sys.excepthook
        def _log_excepthook(exc_type, exc_val, exc_tb):
            try:
                print("----- Exception Python non rattrapée -----",
                      file=_CRASH_LOG_FILE, flush=True)
                traceback.print_exception(exc_type, exc_val, exc_tb, file=_CRASH_LOG_FILE)
                _CRASH_LOG_FILE.flush()
            except Exception:
                pass
            _prev_excepthook(exc_type, exc_val, exc_tb)
        sys.excepthook = _log_excepthook
    except Exception:
        pass


def _mac_fatal(title: str, msg: str):
    """Affiche une alerte macOS native sans Qt (osascript) et écrit dans le log."""
    if _MAC_LOG_FILE:
        try:
            print(f"[FATAL] {title}: {msg}", file=_MAC_LOG_FILE, flush=True)
            traceback.print_exc(file=_MAC_LOG_FILE)
        except Exception:
            pass
    try:
        import subprocess
        safe = msg.replace('"', "'").replace('\\', '/')[:400]
        subprocess.run(
            ['osascript', '-e',
             f'display alert "{title}" message "{safe}\\n\\nLog : ~/Library/Logs/MyStrow/crash.log" as critical'],
            timeout=15
        )
    except Exception:
        pass

# ------------------------------------------------------------------
# IMPORTS APPLICATION
# ------------------------------------------------------------------

import socket
import threading

from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtGui import QIcon
import webbrowser
import platform

# Imports légers uniquement — tout ce qui est lourd est différé après le splash
from core import APP_NAME, VERSION, MIDI_AVAILABLE, resource_path
from updater import SplashScreen, UpdateChecker, AkaiSplashEffect
from i18n import tr

# Bloc jamais exécuté — uniquement pour que PyInstaller détecte ces modules
# lors de l'analyse statique et les inclue dans le bundle Mac/Windows.
if False:  # noqa
    import main_window      # noqa: F401
    import license_manager  # noqa: F401
    import license_ui       # noqa: F401


# ------------------------------------------------------------------
# DIALOGUE ERREUR INTEGRITE
# ------------------------------------------------------------------
def _show_integrity_error():
    is_mac = platform.system() == "Darwin"
    download_url = (
        "https://github.com/nprieto-ext/MAESTRO/releases/latest/download/MyStrow_Installer.dmg"
        if is_mac else
        "https://github.com/nprieto-ext/MAESTRO/releases/latest/download/MyStrow_Setup.exe"
    )

    dlg = QDialog()
    dlg.setWindowTitle(tr("integrity_title"))
    dlg.setFixedWidth(460)
    dlg.setStyleSheet("background:#1a1a1a; color:#e0e0e0;")

    layout = QVBoxLayout(dlg)
    layout.setSpacing(16)
    layout.setContentsMargins(28, 24, 28, 24)

    icon_lbl = QLabel("⚠️")
    icon_lbl.setAlignment(Qt.AlignCenter)
    icon_lbl.setStyleSheet("font-size:38px; background:transparent;")
    layout.addWidget(icon_lbl)

    msg = QLabel(tr("integrity_msg"))
    msg.setWordWrap(True)
    msg.setAlignment(Qt.AlignCenter)
    msg.setStyleSheet("font-size:13px; background:transparent; line-height:1.5;")
    layout.addWidget(msg)

    layout.addSpacing(4)

    btn_dl = QPushButton(tr("integrity_download"))
    btn_dl.setFixedHeight(40)
    btn_dl.setStyleSheet("""
        QPushButton {
            background: #0078d4; color: white;
            border: none; border-radius: 6px;
            font-size: 13px; font-weight: bold;
        }
        QPushButton:hover { background: #1a8ee0; }
        QPushButton:pressed { background: #005fa3; }
    """)
    btn_dl.clicked.connect(lambda: webbrowser.open(download_url))
    layout.addWidget(btn_dl)

    btn_close = QPushButton(tr("close"))
    btn_close.setFixedHeight(34)
    btn_close.setStyleSheet("""
        QPushButton {
            background: #2a2a2a; color: #aaa;
            border: 1px solid #3a3a3a; border-radius: 6px;
            font-size: 12px;
        }
        QPushButton:hover { background: #333; color: #ddd; }
    """)
    btn_close.clicked.connect(dlg.accept)
    layout.addWidget(btn_close)

    dlg.exec()


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def _free_console():
    """Detache completement Python de sa console et redirige stdout/stderr vers un log.
    Garantit la disparition de la fenetre console (conhost.exe)."""
    try:
        import ctypes
        log_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "MyStrow", "Logs")
        os.makedirs(log_dir, exist_ok=True)
        _log_path = os.path.join(log_dir, "console.log")
        # Plafond 20 Mo : le log s'ouvrait en append sans limite (vu à 256 Mo).
        # Au-delà, on repart d'un fichier vide au lieu de gonfler indéfiniment.
        _log_mode = "a"
        try:
            if os.path.exists(_log_path) and os.path.getsize(_log_path) > 20 * 1024 * 1024:
                _log_mode = "w"
        except Exception:
            pass
        _log = open(_log_path, _log_mode, encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = _log
        sys.stderr = _log
        try:
            os.dup2(_log.fileno(), 1)
            os.dup2(_log.fileno(), 2)
        except Exception:
            pass
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def _hide_orphan_console():
    """Masque la fenetre console Python (conhost.exe).
    1. ShowWindow(SW_HIDE) + WS_EX_TOOLWINDOW pour cacher la fenetre
       (fonctionne meme si plusieurs process sont attaches a la console).
    2. FreeConsole() pour detacher Python et rediriger stdout/stderr vers log."""
    if sys.platform != "win32" or getattr(sys, 'frozen', False):
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        hwnd = k32.GetConsoleWindow()
        if not hwnd or not u32.IsWindowVisible(hwnd):
            return
        # Retirer de la barre des taches + cacher visuellement
        GWL_EXSTYLE      = -20
        WS_EX_TOOLWINDOW = 0x80
        WS_EX_APPWINDOW  = 0x40000
        cur = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, (cur | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        u32.ShowWindow(hwnd, 0)  # SW_HIDE
        # Detacher Python de la console + rediriger stdout/stderr vers log
        _free_console()
    except Exception:
        pass


def main():
    """Point d'entree principal de Maestro"""
    _hide_orphan_console()
    print(tr("starting", app=APP_NAME, ver=VERSION))
    print(tr("modular_mode"))
    print("-" * 40)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    icon_path = resource_path("mystrow.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Splash screen
    splash = SplashScreen()
    splash.show()
    app.processEvents()
    start_time = time.time()

    # ------------------------------------------------------------------
    # IMPORTS LOURDS — différés pour que le splash soit visible immédiatement
    # ------------------------------------------------------------------
    splash.set_status(tr("loading"))
    app.processEvents()

    try:
        from license_manager import verify_license, check_exe_integrity, LicenseState, _result_not_activated
        from main_window import MainWindow
    except Exception as _import_err:
        import traceback as _tb
        _err_msg = _tb.format_exc()
        # Ecrire dans le log
        try:
            from pathlib import Path as _Path
            _log = _Path.home() / "MyStrow_crash.log"
            _log.write_text(_err_msg, encoding="utf-8")
        except Exception:
            pass
        # Afficher une boite d'erreur visible
        from PySide6.QtWidgets import QMessageBox as _QMB, QTextEdit as _QTE, QDialog as _QDlg, QVBoxLayout as _QVL, QPushButton as _QPB, QLabel as _QLbl
        import platform as _plt
        # Diagnostic bundle PyInstaller
        _meipass_files = ""
        if hasattr(sys, '_MEIPASS'):
            try:
                _meipass_files = "\nBundle (_MEIPASS): " + sys._MEIPASS + "\n"
                _meipass_files += "  main_window present: " + str(os.path.exists(os.path.join(sys._MEIPASS, 'main_window.pyc'))) + "\n"
                _meipass_files += "  .pyc files: " + ", ".join(f for f in os.listdir(sys._MEIPASS) if f.endswith('.pyc') and 'main' in f.lower()) + "\n"
                _meipass_files += "sys.path: " + str(sys.path[:4]) + "\n"
            except Exception as _e:
                _meipass_files = f"\n(diagnostic error: {_e})\n"
        _header = (
            f"MyStrow {VERSION}  |  Python {sys.version.split()[0]}"
            f"  |  {_plt.system()} {_plt.release()} ({_plt.machine()})\n"
            f"{'─' * 60}\n"
            f"{_meipass_files}\n"
        )
        _dlg = _QDlg()
        _dlg.setWindowTitle(tr("startup_error_title", ver=VERSION))
        _dlg.setMinimumSize(680, 420)
        _vl = _QVL(_dlg)
        _lbl = _QLbl(tr("startup_error_label", ver=VERSION))
        _lbl.setStyleSheet("color:#f44;font-size:13px;padding:4px 0;")
        _vl.addWidget(_lbl)
        _te = _QTE()
        _te.setReadOnly(True)
        _te.setPlainText(_header + _err_msg)
        _te.setStyleSheet("background:#111;color:#f44;font-family:monospace;font-size:11px;")
        _vl.addWidget(_te)
        _pb = _QPB(tr("close"))
        _pb.clicked.connect(_dlg.accept)
        _vl.addWidget(_pb)
        splash.close()
        _dlg.exec()
        sys.exit(1)

    # Lancer la verification des mises a jour en arriere-plan
    update_checker = UpdateChecker()
    update_checker.start()

    # ------------------------------------------------------------------
    # VERIFICATION INTEGRITE (anti-patch, uniquement en mode frozen)
    # ------------------------------------------------------------------
    splash.set_status(tr("checking_integrity"))
    app.processEvents()

    if not check_exe_integrity():
        splash.close()
        _show_integrity_error()
        sys.exit(1)

    # ------------------------------------------------------------------
    # LICENCE + AKAI + DMX — tous en parallele
    # ------------------------------------------------------------------
    splash.set_status(tr("initializing"))
    app.processEvents()

    _license_box = [None]
    _akai_box    = [False]
    # [ok, libellé court affiché, détail complet pour l'infobulle]
    _dmx_box     = [False, tr("not_configured"), ""]

    # La ligne garde son libellé neutre « Sortie DMX ». Elle affichait
    # « Sortie DMX USB » ou « Sortie Node » selon le transport enregistré, ce qui
    # exposait un détail de câblage sans utilité au démarrage — et induisait en
    # erreur quand la config gardait un transport obsolète. Même choix que le
    # menu Connexion : c'est la même sortie, quel que soit le câble derrière.

    def _bg_license():
        _license_box[0] = verify_license()

    def _bg_akai():
        if not MIDI_AVAILABLE:
            return
        try:
            import rtmidi as _rt
        except ImportError:
            try:
                import rtmidi2 as _rt
            except ImportError:
                return
        try:
            _mi = _rt.MidiIn()
            ports = _mi.get_ports()
            print(f"[MIDI] Ports disponibles: {ports}")
            # Même détection que MIDIHandler → reconnaît TOUS les contrôleurs
            # supportés (APC, Launchpad MK3, MIDImix…) + profils custom.
            from midi_handler import _detect_controller
            ctrl, _ = _detect_controller(ports)
            if ctrl is not None:
                _akai_box[0] = True
            else:
                try:
                    from controller_profile import find_profile_for_port
                    if any(find_profile_for_port(name) for name in ports):
                        _akai_box[0] = True
                except Exception:
                    pass
            # Fermeture explicite avant que MIDIHandler n'ouvre le port
            try:
                _mi.close_port()
            except Exception:
                pass
            del _mi
        except Exception as e:
            print(f"[MIDI] Erreur probe AKAI: {e}")

    def _bg_dmx():
        try:
            import json as _j, os as _o
            cfg_file = _o.path.expanduser("~/.mystrow_dmx.json")
            if not _o.path.exists(cfg_file):
                return
            with open(cfg_file) as f:
                cfg = _j.load(f)
            transport    = cfg.get("transport", "enttec")
            product_name = cfg.get("product_name", "")
            # Le splash a une largeur fixe : la ligne « Sortie DMX » tient en
            # une petite trentaine de caractères. On y met donc un nom COURT —
            # le type de sortie et son point de raccordement — et rien d'autre.
            # Le nom commercial du produit est trompeur en plus d'être long :
            # il reste celui du dernier matériel configuré, si bien qu'un
            # « Art-Net (réseau) » s'affichait encore sur une sortie USB.
            # Tout le détail part dans l'infobulle.
            if transport in ("enttec", "enttec_pro", "enttec_d2xx"):
                com = cfg.get("com_port")
                if com:
                    try:
                        import serial as _s
                        p = _s.Serial(com, 250000, stopbits=_s.STOPBITS_TWO, timeout=0.5)
                        p.close()
                        _dmx_box[0] = True
                        _dmx_box[1] = f"USB DMX · {com}"
                    except Exception:
                        _dmx_box[0] = False
                        _dmx_box[1] = f"USB DMX · {tr('offline')}"
                    _dmx_box[2] = f"{product_name or 'USB DMX'} — {com}"
                else:
                    _dmx_box[1] = f"USB DMX · {tr('not_configured')}"
                    _dmx_box[2] = product_name or "USB DMX"
            else:
                ip = cfg.get("target_ip", "")
                if ip:
                    try:
                        import socket as _sock
                        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                        s.settimeout(0.8)
                        r = s.connect_ex((ip, 80))
                        s.close()
                        # r==0 : connexion OK  /  10061 (Windows) ou 111 (Linux) : refusée = hôte en ligne
                        _dmx_box[0] = True if r in (0, 111, 10061) else False
                    except Exception:
                        _dmx_box[0] = None  # orange = inconnu
                    _dmx_box[1] = (f"Art-Net · {ip}" if _dmx_box[0] is not False
                                   else f"Art-Net · {tr('offline')}")
                else:
                    _dmx_box[0] = False
                    _dmx_box[1] = f"Art-Net · {tr('not_configured')}"
                _dmx_box[2] = f"{product_name or 'Art-Net'} — {ip or tr('not_configured')}"
        except Exception:
            pass

    t_license = threading.Thread(target=_bg_license, daemon=True)
    t_akai    = threading.Thread(target=_bg_akai,    daemon=True)
    t_dmx     = threading.Thread(target=_bg_dmx,     daemon=True)
    t_license.start(); t_akai.start(); t_dmx.start()

    # Effet visuel AKAI — démarré dès que la connexion est confirmée
    akai_effect = AkaiSplashEffect()

    # Attendre les threads sans bloquer Qt — on process les events pendant l'attente
    deadline = time.time() + 8
    akai_shown = dmx_shown = False
    while time.time() < deadline:
        app.processEvents()

        if not akai_shown and not t_akai.is_alive():
            splash.set_hw_status("akai", tr("connected") if _akai_box[0] else tr("not_detected"), _akai_box[0])
            app.processEvents()
            akai_shown = True
            if _akai_box[0]:
                akai_effect.start()

        if not dmx_shown and not t_dmx.is_alive():
            splash.set_hw_status("node", _dmx_box[1], _dmx_box[0], detail=_dmx_box[2])
            app.processEvents()
            dmx_shown = True

        if not t_license.is_alive() and akai_shown and dmx_shown:
            break

        time.sleep(0.05)

    # Afficher les resultats manquants si timeout
    if not akai_shown:
        splash.set_hw_status("akai", tr("not_detected"), False)
    if not dmx_shown:
        splash.set_hw_status("node", _dmx_box[1], _dmx_box[0], detail=_dmx_box[2])

    license_result = _license_box[0] or _result_not_activated()
    print(f"Licence: {license_result}")

    # Afficher le statut licence sur le splash
    _license_labels = {
        LicenseState.LICENSE_ACTIVE:  (tr("lic_active"), True),
        LicenseState.TRIAL_ACTIVE:    (tr("lic_trial", days=license_result.days_remaining), True),
        LicenseState.NOT_ACTIVATED:   (tr("lic_not_activated"), True),
        LicenseState.TRIAL_EXPIRED:   (tr("lic_trial_expired"), False),
        LicenseState.LICENSE_EXPIRED: (tr("lic_expired"), False),
        LicenseState.INVALID:         (tr("lic_invalid"), False),
        LicenseState.FRAUD_CLOCK:     (tr("lic_clock_error"), False),
    }
    lic_text, lic_ok = _license_labels.get(license_result.state, ("Inconnue", False))
    splash.set_hw_status("license", lic_text, lic_ok)
    app.processEvents()

    # Arrêter l'effet AKAI avant de créer MainWindow (libère le port MIDI)
    akai_effect.stop()

    # Initialiser la fenetre principale avec le resultat de licence
    splash.set_status(tr("initializing"))
    app.processEvents()
    window = MainWindow(license_result=license_result)

    # Connecter le signal de mise a jour
    update_checker.update_available.connect(window.on_update_available)
    window._update_checker = update_checker

    # Garantir un affichage minimum de 5 secondes
    elapsed = time.time() - start_time
    remaining_ms = max(0, int((5.0 - elapsed) * 1000))
    if remaining_ms > 0:
        splash.set_status(tr("ready"))
        app.processEvents()
        loop = QEventLoop()
        QTimer.singleShot(remaining_ms, loop.quit)
        loop.exec()

    # Fermer le splash et afficher la fenetre
    splash.close()
    window.showMaximized()

    # Afficher le dialogue d'avertissement licence si necessaire
    # (apres que la fenetre soit visible)
    QTimer.singleShot(500, window.show_license_warning_if_needed)
    # Deuxieme tentative de masquage console (cas ou le lanceur n'avait pas quitte)
    QTimer.singleShot(1000, _hide_orphan_console)

    # Ré-ouvrir le wizard Node à la page IP si on a été relancé en admin
    _node_config_ip = None
    _argv = sys.argv[1:]
    for _i, _arg in enumerate(_argv):
        if _arg == "--node-config-ip" and _i + 1 < len(_argv):
            _node_config_ip = _argv[_i + 1]
            break
    if _node_config_ip:
        QTimer.singleShot(800, lambda: window.open_node_wizard_at_ip_manual(_node_config_ip))

    sys.exit(app.exec())

# ------------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    except Exception as _e:
        _msg = traceback.format_exc()
        _mac_fatal("MyStrow — Erreur fatale au démarrage", str(_e))
        sys.exit(1)
