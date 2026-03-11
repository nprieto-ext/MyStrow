"""
brad_diagnostic.py — Assistant de diagnostic DMX/Réseau pour MyStrow.
Accessible via : Connexion > Node > Assistant BRAD

Collecte toutes les infos utiles et génère un rapport copier-coller.
"""

import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QProgressBar, QFrame, QApplication,
)

from core import APP_NAME, VERSION

CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0


# ──────────────────────────────────────────────────────────────────────────────
# Thread de diagnostic (tourne tous les tests en arrière-plan)
# ──────────────────────────────────────────────────────────────────────────────

class _DiagWorker(QThread):
    progress = Signal(int, str)   # (%, message en cours)
    done     = Signal(list)       # liste de (categorie, statut, detail)

    def __init__(self, window):
        super().__init__()
        self._win = window

    def run(self):
        results = []
        w = self._win

        def add(cat, status, detail):
            results.append((cat, status, detail))

        # ── 1. Infos système ──────────────────────────────────────────────
        self.progress.emit(5, "Infos système...")
        add("Système",  "info", f"OS          : {platform.system()} {platform.version()}")
        add("Système",  "info", f"Python      : {sys.version.split()[0]}")
        add("Système",  "info", f"MyStrow     : {VERSION}")
        add("Système",  "info", f"Machine     : {platform.node()}")

        # ── 2. Licence ────────────────────────────────────────────────────
        self.progress.emit(12, "Licence...")
        try:
            lic = w._license
            add("Licence", "ok" if lic.dmx_allowed else "err",
                f"DMX autorisé : {'OUI' if lic.dmx_allowed else 'NON'} — état : {lic.state.name}")
        except Exception as e:
            add("Licence", "err", f"Impossible de lire la licence : {e}")

        # ── 3. Config ~/.mystrow_dmx.json ─────────────────────────────────
        self.progress.emit(20, "Config DMX...")
        cfg_path = Path.home() / ".mystrow_dmx.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                add("Config DMX", "ok",  f"Fichier     : {cfg_path}")
                add("Config DMX", "info", f"Transport   : {cfg.get('transport', '?')}")
                add("Config DMX", "info", f"IP cible    : {cfg.get('target_ip', '?')}")
                add("Config DMX", "info", f"Port        : {cfg.get('target_port', '?')}")
                add("Config DMX", "info", f"Univers     : {cfg.get('universe', '?')}")
                add("Config DMX", "info", f"Produit     : {cfg.get('product_name', '?')}")
            except Exception as e:
                add("Config DMX", "err", f"Erreur lecture : {e}")
        else:
            add("Config DMX", "warn", f"Fichier absent : {cfg_path}")

        # ── 4. Config ~/.maestro_dmx_patch.json ───────────────────────────
        self.progress.emit(28, "Patch DMX...")
        patch_path = Path.home() / ".maestro_dmx_patch.json"
        if patch_path.exists():
            try:
                patch = json.loads(patch_path.read_text(encoding="utf-8"))
                fixtures = patch.get("fixtures", [])
                add("Patch DMX", "ok", f"Fichier     : {patch_path}")
                add("Patch DMX", "info", f"Fixtures    : {len(fixtures)}")
                for i, f in enumerate(fixtures):
                    add("Patch DMX", "info",
                        f"  [{i}] {f.get('name','?')}  addr={f.get('start_address','?')}  "
                        f"profil={f.get('profile','?')}")
            except Exception as e:
                add("Patch DMX", "err", f"Erreur lecture : {e}")
        else:
            add("Patch DMX", "warn", f"Fichier absent : {patch_path}")

        # ── 5. Etat DMX en mémoire ────────────────────────────────────────
        self.progress.emit(35, "État DMX en mémoire...")
        try:
            dmx = w.dmx
            add("DMX live", "info", f"Transport   : {dmx.transport}")
            add("DMX live", "info", f"IP cible    : {dmx.target_ip}")
            add("DMX live", "info", f"Port        : {dmx.target_port}")
            add("DMX live", "info", f"Univers     : {dmx.universe}")
            add("DMX live", "ok" if dmx.connected else "err",
                f"Connecté    : {'OUI' if dmx.connected else 'NON'}")
            add("DMX live", "info", f"Socket      : {'ouvert' if dmx._socket else 'fermé'}")
            nb_patched = len(dmx.projector_channels)
            add("DMX live", "ok" if nb_patched > 0 else "err",
                f"Fixtures patchées : {nb_patched}")
            for key, chans in dmx.projector_channels.items():
                profil = dmx.projector_profiles.get(key, [])
                add("DMX live", "info", f"  {key} → canaux {chans}  profil {profil}")
        except Exception as e:
            add("DMX live", "err", f"Impossible de lire l'état DMX : {e}")

        # ── 6. Bouton DMX ON/OFF ──────────────────────────────────────────
        self.progress.emit(42, "Toggle DMX...")
        try:
            enabled = w.plan_de_feu.is_dmx_enabled()
            add("Interface", "ok" if enabled else "err",
                f"Bouton DMX  : {'ON ✓' if enabled else 'OFF ← PROBLÈME'}")
        except Exception as e:
            add("Interface", "err", f"Impossible de lire le toggle DMX : {e}")

        # ── 7. Carte réseau ───────────────────────────────────────────────
        self.progress.emit(50, "Cartes réseau...")
        try:
            result = subprocess.run(
                ["ipconfig"], capture_output=True, text=True,
                encoding="cp850", errors="replace",
                creationflags=CREATE_NO_WINDOW
            )
            adapters = _parse_adapters(result.stdout)
            if adapters:
                for name, ip in adapters:
                    ok = ip.startswith("2.")
                    add("Réseau", "ok" if ok else "warn",
                        f"{name[:35]:<35} IP={ip}")
            else:
                add("Réseau", "warn", "Aucun adaptateur Ethernet détecté")
        except Exception as e:
            add("Réseau", "err", f"ipconfig échoué : {e}")

        # ── 8. ArtPoll broadcast ──────────────────────────────────────────
        self.progress.emit(62, "ArtPoll broadcast...")
        try:
            found, sender = _artpoll_probe("2.255.255.255", timeout=1.5)
            add("ArtPoll broadcast",
                "ok" if found else "warn",
                f"2.255.255.255 → {'réponse de ' + sender if found else 'pas de réponse'}")
            found2, sender2 = _artpoll_probe("255.255.255.255", timeout=1.0)
            add("ArtPoll broadcast",
                "ok" if found2 else "warn",
                f"255.255.255.255 → {'réponse de ' + sender2 if found2 else 'pas de réponse'}")
        except Exception as e:
            add("ArtPoll broadcast", "err", f"Erreur : {e}")

        # ── 9. ArtPoll unicast vers IP configurée ─────────────────────────
        self.progress.emit(74, "ArtPoll unicast...")
        try:
            target = w.dmx.target_ip
            found, sender = _artpoll_probe(target, timeout=1.5, unicast=True)
            add("ArtPoll unicast",
                "ok" if found else "err",
                f"{target} → {'réponse de ' + sender if found else 'PAS DE RÉPONSE ← PROBLÈME'}")
        except Exception as e:
            add("ArtPoll unicast", "err", f"Erreur : {e}")

        # ── 10. Envoi test Art-Net ────────────────────────────────────────
        self.progress.emit(85, "Envoi paquet Art-Net test...")
        try:
            target_ip   = w.dmx.target_ip
            target_port = w.dmx.target_port
            universe    = w.dmx.universe
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sub_uni = universe & 0xFF
            net     = (universe >> 8) & 0x7F
            packet = (
                b'Art-Net\x00'
                + b'\x00\x50'
                + b'\x00\x0e'
                + b'\x01'
                + b'\x00'
                + bytes([sub_uni, net])
                + b'\x02\x00'
                + bytes(512)   # données nulles = blackout test
            )
            s.sendto(packet, (target_ip, target_port))
            s.close()
            add("Envoi test", "ok",
                f"Paquet ArtDMX envoyé → {target_ip}:{target_port} (univers {universe}, 512 ch à 0)")
        except Exception as e:
            add("Envoi test", "err", f"Erreur envoi : {e}")

        # ── 11. Projecteurs en mémoire ────────────────────────────────────
        self.progress.emit(92, "Projecteurs...")
        try:
            projs = w.projectors
            add("Projecteurs", "ok" if projs else "err",
                f"Nombre de projecteurs : {len(projs)}")
            for i, p in enumerate(projs):
                add("Projecteurs", "info",
                    f"  [{i}] {p.name:<18} groupe={p.group:<10} "
                    f"addr={p.start_address}  level={p.level}  "
                    f"color={p.color.name()}")
        except Exception as e:
            add("Projecteurs", "err", f"Erreur : {e}")

        self.progress.emit(100, "Terminé.")
        self.done.emit(results)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers réseau
# ──────────────────────────────────────────────────────────────────────────────

def _artpoll_packet() -> bytes:
    p = bytearray(b'Art-Net\x00')
    p.extend(b'\x00\x20')
    p.extend(b'\x00\x0e')
    p.extend(b'\x00\x00')
    return bytes(p)


def _artpoll_probe(target_ip: str, timeout: float = 1.5,
                   unicast: bool = False):
    """Envoie un ArtPoll et retourne (found, sender_ip)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if not unicast:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        try:
            s.bind(("", 6454))
        except OSError:
            s.bind(("", 0))   # fallback si 6454 déjà pris
        s.sendto(_artpoll_packet(), (target_ip, 6454))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                s.settimeout(max(0.05, deadline - time.time()))
                data, (sender, _) = s.recvfrom(512)
                if data[:8] == b'Art-Net\x00':
                    s.close()
                    return True, sender
            except Exception:
                break
        s.close()
    except Exception:
        pass
    return False, ""


def _parse_adapters(ipconfig_out: str):
    """Parse basique ipconfig pour extraire (nom, IP)."""
    import re
    adapters = []
    current = None
    skip_keywords = ["wi-fi", "wifi", "wireless", "loopback", "bluetooth",
                     "tunnel", "vmware", "virtual", "vethernet", "isatap"]
    for line in ipconfig_out.splitlines():
        if line and not line.startswith(" "):
            low = line.lower()
            if any(k in low for k in skip_keywords):
                current = None
            elif ":" in line:
                current = line.strip().rstrip(":")
        elif current and "ipv4" in line.lower():
            m = __import__("re").search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
            if m:
                ip = m.group(1)
                if not ip.startswith("127."):
                    adapters.append((current, ip))
                    current = None
    return adapters


# ──────────────────────────────────────────────────────────────────────────────
# Dialog principal
# ──────────────────────────────────────────────────────────────────────────────

_STATUS_COLOR = {
    "ok":   "#4caf50",
    "err":  "#f44336",
    "warn": "#ff9800",
    "info": "#888888",
}
_STATUS_ICON = {
    "ok":   "✓",
    "err":  "✗",
    "warn": "⚠",
    "info": "·",
}


class BradDiagnosticDialog(QDialog):
    """Assistant BRAD — diagnostic complet DMX/Réseau."""

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self.setWindowTitle("Assistant BRAD — Diagnostic DMX")
        self.setMinimumSize(680, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog   { background: #111111; color: #e0e0e0; }
            QLabel    { background: transparent; color: #e0e0e0; }
            QTextEdit { background: #0a0a0a; color: #cccccc;
                        border: 1px solid #222; border-radius: 6px;
                        font-family: Consolas, monospace; font-size: 11px; }
            QPushButton {
                background: #1e1e1e; color: #aaa;
                border: 1px solid #333; border-radius: 6px;
                padding: 8px 20px; font-size: 12px;
            }
            QPushButton:hover  { background: #252525; color: #eee; border-color: #555; }
            QPushButton:pressed { background: #0a0a0a; }
            QProgressBar {
                background: #1a1a1a; border: none; border-radius: 4px; height: 6px;
            }
            QProgressBar::chunk { background: #00d4ff; border-radius: 4px; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ── Titre ──
        title = QLabel("Assistant BRAD")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #00d4ff;")
        sub = QLabel("Diagnostic automatique de la sortie DMX Art-Net")
        sub.setStyleSheet("color: #555; font-size: 11px;")
        root.addWidget(title)
        root.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #222;")
        root.addWidget(sep)

        # ── Barre de progression ──
        self._prog = QProgressBar()
        self._prog.setRange(0, 100)
        self._prog.setValue(0)
        self._status_lbl = QLabel("Démarrage des tests...")
        self._status_lbl.setStyleSheet("color: #666; font-size: 10px;")
        root.addWidget(self._prog)
        root.addWidget(self._status_lbl)

        # ── Zone de résultats ──
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setMinimumHeight(340)
        root.addWidget(self._output)

        # ── Boutons ──
        btn_row = QHBoxLayout()
        self._copy_btn = QPushButton("📋  Copier le rapport")
        self._copy_btn.setEnabled(False)
        self._copy_btn.setStyleSheet("""
            QPushButton {
                background: #003a4a; color: #00d4ff;
                border: 1px solid #00d4ff44; border-radius: 6px;
                padding: 10px 28px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover  { background: #004a5a; border-color: #00d4ff99; }
            QPushButton:pressed { background: #001a2a; }
            QPushButton:disabled { background: #1a1a1a; color: #333; border-color: #222; }
        """)
        self._copy_btn.clicked.connect(self._copy_report)

        self._retry_btn = QPushButton("↺  Relancer")
        self._retry_btn.setEnabled(False)
        self._retry_btn.clicked.connect(self._start)

        close_btn = QPushButton("Fermer")
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(self._copy_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._retry_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._raw_lines = []   # lignes texte brut pour le copier-coller
        self._worker = None

        QTimer.singleShot(150, self._start)

    # ── lancement ─────────────────────────────────────────────────────────────

    def _start(self):
        self._copy_btn.setEnabled(False)
        self._retry_btn.setEnabled(False)
        self._prog.setValue(0)
        self._output.clear()
        self._raw_lines = []
        self._append_html(
            '<span style="color:#00d4ff;font-weight:bold;">BRAD — Rapport de diagnostic</span><br>'
            f'<span style="color:#444;">{time.strftime("%Y-%m-%d %H:%M:%S")}'
            f'  —  {APP_NAME} {VERSION}</span><br>'
        )
        self._raw_lines.append("=" * 60)
        self._raw_lines.append(f"BRAD — Rapport de diagnostic MyStrow {VERSION}")
        self._raw_lines.append(time.strftime("%Y-%m-%d %H:%M:%S"))
        self._raw_lines.append("=" * 60)

        self._worker = _DiagWorker(self._window)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    # ── slots worker ──────────────────────────────────────────────────────────

    def _on_progress(self, pct: int, msg: str):
        self._prog.setValue(pct)
        self._status_lbl.setText(msg)

    def _on_done(self, results: list):
        self._prog.setValue(100)
        self._status_lbl.setText("Terminé.")

        current_cat = None
        for cat, status, detail in results:
            if cat != current_cat:
                current_cat = cat
                self._append_html(
                    f'<br><span style="color:#00d4ff;font-size:11px;font-weight:bold;">'
                    f'▸ {cat}</span>'
                )
                self._raw_lines.append("")
                self._raw_lines.append(f"[ {cat} ]")

            color = _STATUS_COLOR.get(status, "#888")
            icon  = _STATUS_ICON.get(status, "·")
            self._append_html(
                f'<span style="color:{color};">{icon}</span>'
                f'<span style="color:#ccc;"> {detail}</span>'
            )
            prefix = {"ok": "✓", "err": "✗", "warn": "⚠", "info": " "}.get(status, " ")
            self._raw_lines.append(f"  {prefix} {detail}")

        # Résumé
        errors   = [r for r in results if r[1] == "err"]
        warnings = [r for r in results if r[1] == "warn"]
        self._append_html("<br>")
        if errors:
            self._append_html(
                f'<span style="color:#f44336;font-weight:bold;">'
                f'⚠ {len(errors)} problème(s) détecté(s)</span>'
            )
        elif warnings:
            self._append_html(
                f'<span style="color:#ff9800;font-weight:bold;">'
                f'⚠ {len(warnings)} avertissement(s)</span>'
            )
        else:
            self._append_html(
                '<span style="color:#4caf50;font-weight:bold;">'
                '✓ Tous les tests sont OK</span>'
            )

        self._raw_lines.append("")
        self._raw_lines.append("=" * 60)
        self._raw_lines.append(
            f"{'PROBLÈMES: ' + str(len(errors)) if errors else 'OK — Aucun problème détecté'}"
        )
        self._raw_lines.append("=" * 60)

        self._copy_btn.setEnabled(True)
        self._retry_btn.setEnabled(True)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _append_html(self, html: str):
        self._output.append(html)

    def _copy_report(self):
        text = "\n".join(self._raw_lines)
        QApplication.clipboard().setText(text)
        self._copy_btn.setText("✓  Copié !")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText("📋  Copier le rapport"))
