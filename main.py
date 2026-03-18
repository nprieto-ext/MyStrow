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

# Fix encodage console Windows (cp1252 ne supporte pas les emojis)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Sur Mac (app bundle PyInstaller), rediriger stderr vers un log lisible
if sys.platform == "darwin" and getattr(sys, 'frozen', False):
    try:
        from pathlib import Path
        _log_dir = Path.home() / "Library" / "Logs" / "MyStrow"
        _log_dir.mkdir(parents=True, exist_ok=True)
        _log_file = open(_log_dir / "crash.log", "w", encoding="utf-8")
        sys.stderr = _log_file
        print(f"[MyStrow] Log demarre", file=_log_file, flush=True)
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
    dlg.setWindowTitle("MyStrow — Erreur d'intégrité")
    dlg.setFixedWidth(460)
    dlg.setStyleSheet("background:#1a1a1a; color:#e0e0e0;")

    layout = QVBoxLayout(dlg)
    layout.setSpacing(16)
    layout.setContentsMargins(28, 24, 28, 24)

    icon_lbl = QLabel("⚠️")
    icon_lbl.setAlignment(Qt.AlignCenter)
    icon_lbl.setStyleSheet("font-size:38px; background:transparent;")
    layout.addWidget(icon_lbl)

    msg = QLabel(
        "L'intégrité de l'application n'a pas pu être vérifiée.\n\n"
        "Le fichier exécutable semble avoir été modifié.\n"
        "Veuillez réinstaller l'application depuis le site officiel."
    )
    msg.setWordWrap(True)
    msg.setAlignment(Qt.AlignCenter)
    msg.setStyleSheet("font-size:13px; background:transparent; line-height:1.5;")
    layout.addWidget(msg)

    layout.addSpacing(4)

    btn_dl = QPushButton("⬇  Télécharger l'installeur")
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

    btn_close = QPushButton("Fermer")
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
def main():
    """Point d'entree principal de Maestro"""
    print(f"Demarrage de {APP_NAME} v{VERSION}")
    print("Mode modulaire active")
    print("-" * 40)

    app = QApplication(sys.argv)
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
    splash.set_status("Chargement...")
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
        _header = (
            f"MyStrow {VERSION}  |  Python {sys.version.split()[0]}"
            f"  |  {_plt.system()} {_plt.release()} ({_plt.machine()})\n"
            f"{'─' * 60}\n\n"
        )
        _dlg = _QDlg()
        _dlg.setWindowTitle(f"MyStrow {VERSION} — Erreur au démarrage")
        _dlg.setMinimumSize(680, 420)
        _vl = _QVL(_dlg)
        _lbl = _QLbl(f"<b>MyStrow {VERSION}</b> — Impossible de charger l'application")
        _lbl.setStyleSheet("color:#f44;font-size:13px;padding:4px 0;")
        _vl.addWidget(_lbl)
        _te = _QTE()
        _te.setReadOnly(True)
        _te.setPlainText(_header + _err_msg)
        _te.setStyleSheet("background:#111;color:#f44;font-family:monospace;font-size:11px;")
        _vl.addWidget(_te)
        _pb = _QPB("Fermer")
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
    splash.set_status("Verification de l'integrite...")
    app.processEvents()

    if not check_exe_integrity():
        splash.close()
        _show_integrity_error()
        sys.exit(1)

    # ------------------------------------------------------------------
    # LICENCE + AKAI + DMX — tous en parallele
    # ------------------------------------------------------------------
    splash.set_status("Initialisation...")
    app.processEvents()

    _license_box = [None]
    _akai_box    = [False]
    _dmx_box     = [False, "Non configuré"]  # [ok, label]

    # Déterminer le type de sortie DMX depuis la config pour le splash
    _dmx_node_label = "Sortie Node"
    try:
        import json as _j, os as _o
        _cfg = _j.load(open(_o.path.expanduser("~/.mystrow_dmx.json")))
        _dmx_node_label = "Sortie DMX USB" if _cfg.get("transport") == "enttec" else "Sortie Node"
    except Exception:
        pass
    splash.set_hw_label("node", _dmx_node_label)

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
            for name in ports:
                if 'APC' in name.upper() or 'AKAI' in name.upper():
                    _akai_box[0] = True
                    break
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
            if transport == "enttec":
                com = cfg.get("com_port")
                if com:
                    try:
                        import serial as _s
                        p = _s.Serial(com, 250000, stopbits=_s.STOPBITS_TWO, timeout=0.5)
                        p.close()
                        _dmx_box[0] = True
                        _dmx_box[1] = f"{product_name or 'USB DMX'}  —  {com}"
                    except Exception:
                        _dmx_box[0] = False
                        _dmx_box[1] = f"{product_name or 'USB DMX'}  —  {com} hors ligne"
                else:
                    _dmx_box[1] = f"{product_name or 'USB DMX'}  —  Non configuré"
            else:
                ip   = cfg.get("target_ip", "")
                name = product_name or "Electroconcept"
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
                else:
                    _dmx_box[0] = False
                _dmx_box[1] = name if ip else f"{name}  —  Non configuré"
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
            splash.set_hw_status("akai", "Connecte" if _akai_box[0] else "Non detecte", _akai_box[0])
            app.processEvents()
            akai_shown = True
            if _akai_box[0]:
                akai_effect.start()

        if not dmx_shown and not t_dmx.is_alive():
            splash.set_hw_status("node", _dmx_box[1], _dmx_box[0])
            app.processEvents()
            dmx_shown = True

        if not t_license.is_alive() and akai_shown and dmx_shown:
            break

        time.sleep(0.05)

    # Afficher les resultats manquants si timeout
    if not akai_shown:
        splash.set_hw_status("akai", "Non detecte", False)
    if not dmx_shown:
        splash.set_hw_status("node", _dmx_box[1], _dmx_box[0])

    license_result = _license_box[0] or _result_not_activated()
    print(f"Licence: {license_result}")

    # Afficher le statut licence sur le splash
    _license_labels = {
        LicenseState.LICENSE_ACTIVE: ("Compte actif", True),
        LicenseState.TRIAL_ACTIVE: (f"Essai - {license_result.days_remaining}j restants", True),
        LicenseState.NOT_ACTIVATED: ("—", True),
        LicenseState.TRIAL_EXPIRED: ("Essai expire", False),
        LicenseState.LICENSE_EXPIRED: ("Licence expiree", False),
        LicenseState.INVALID: ("Compte invalide", False),
        LicenseState.FRAUD_CLOCK: ("Erreur horloge", False),
    }
    lic_text, lic_ok = _license_labels.get(license_result.state, ("Inconnue", False))
    splash.set_hw_status("license", lic_text, lic_ok)
    app.processEvents()

    # Arrêter l'effet AKAI avant de créer MainWindow (libère le port MIDI)
    akai_effect.stop()

    # Initialiser la fenetre principale avec le resultat de licence
    splash.set_status("Initialisation...")
    app.processEvents()
    window = MainWindow(license_result=license_result)

    # Connecter le signal de mise a jour
    update_checker.update_available.connect(window.on_update_available)
    window._update_checker = update_checker

    # Garantir un affichage minimum de 5 secondes
    elapsed = time.time() - start_time
    remaining_ms = max(0, int((5.0 - elapsed) * 1000))
    if remaining_ms > 0:
        splash.set_status("Pret !")
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
    main()
