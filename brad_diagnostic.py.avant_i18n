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

from core import APP_NAME, VERSION, send_report_email

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
            # Décrire le transport RÉELLEMENT actif. Afficher « IP cible / port
            # 6454 / socket fermé » sur une sortie USB faisait chercher un
            # problème réseau là où il n'y en a pas — et masquait le vrai sujet.
            _serie = dmx.transport in ("enttec", "enttec_pro", "enttec_d2xx")
            add("DMX live", "info", f"Transport   : {dmx.transport}"
                                    f"  ({'USB / série' if _serie else 'réseau Art-Net'})")
            if _serie:
                add("DMX live", "info", f"Port série  : {dmx.com_port or '— non configuré —'}")
                add("DMX live", "info",
                    f"Port ouvert : {'oui' if getattr(dmx, '_serial', None) else 'non'}")
                add("DMX live", "warn",
                    f"(IP {dmx.target_ip} ignorée : ce transport n'utilise pas le réseau)")
            else:
                add("DMX live", "info", f"IP cible    : {dmx.target_ip}")
                add("DMX live", "info", f"Port        : {dmx.target_port}")
                add("DMX live", "info", f"Socket      : {'ouvert' if dmx._socket else 'fermé'}")
            add("DMX live", "info", f"Univers     : {dmx.universe}")
            add("DMX live", "ok" if dmx.connected else "err",
                f"Connecté    : {'OUI' if dmx.connected else 'NON'}"
                + ("" if dmx.connected else "  ← rien ne sort tant que c'est NON"))
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
            # Tous les adaptateurs (sans filtre agressif)
            all_adapters = _lire_adaptateurs(filter_irrelevant=False)
            # Filtrer loopback/tunnel pour l'affichage
            skip_display = ["loopback", "bluetooth", "tunnel", "vmware", "vethernet", "isatap"]
            adapters = [(n, ip) for n, ip in all_adapters
                        if not any(k in n.lower() for k in skip_display)
                        and not ip.startswith("127.") and not ip.startswith("169.254.")]
            if adapters:
                for name, ip in adapters:
                    ok = ip.startswith("2.")
                    add("Réseau", "ok" if ok else "info",
                        f"{name[:35]:<35} IP={ip}")
            else:
                # Montrer quand même tous les adaptateurs trouvés pour diagnostic
                visible = [(n, ip) for n, ip in all_adapters if not ip.startswith("127.")]
                if visible:
                    add("Réseau", "warn", "Aucun adaptateur sur réseau 2.x.x.x — adaptateurs trouvés :")
                    for name, ip in visible:
                        add("Réseau", "info", f"  {name[:35]:<35} IP={ip}")
                else:
                    add("Réseau", "err", "Aucun adaptateur Ethernet détecté — branchez le câble RJ45 !")
        except Exception as e:
            add("Réseau", "warn", f"Liste des interfaces indisponible : {e}")

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

        # ── 9. Scan ARP — détection boîtiers sur 2.x.x.x ────────────────
        self.progress.emit(62, "Scan réseau 2.0.0.x...")
        try:
            # Balayage 2.0.0.1 → 2.0.0.30 pour peupler la table ARP. Un simple
            # datagramme UDP suffit : l'envoyer force la résolution ARP de
            # l'IP visée, sans les droits root d'un ping ICMP et sans dépendre
            # d'un shell (l'ancien `cmd /c for /L …` échouait sur macOS avec
            # « No such file or directory: 'cmd' », et le scan ne servait plus).
            _sonde = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _sonde.settimeout(0.05)
            for _n in range(1, 31):
                try:
                    _sonde.sendto(b"\x00", (f"2.0.0.{_n}", 6454))
                except Exception:
                    pass
            _sonde.close()
            time.sleep(0.6)          # laisser les réponses ARP arriver

            arp = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                                 encoding=_ENCODAGE_CMD, errors="replace",
                                 timeout=10,
                                 creationflags=CREATE_NO_WINDOW)
            import re as _re
            found_devices = []
            # Windows : « 2.0.0.15   00-11-22-33-44-55   dynamique »
            # macOS   : « ? (2.0.0.15) at 0:11:22:33:44:55 on en5 … »
            # `(?<![\d.])` est indispensable : sans lui, « 192.168.1.1 » se fait
            # lire comme « 2.168.1.1 » et le rapport invente un boîtier sur le
            # réseau 2.x qui n'existe pas.
            _rx = _re.compile(r"(?<![\d.])(2\.\d{1,3}\.\d{1,3}\.\d{1,3})\)?\s+(?:at\s+)?"
                              r"([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})")
            _locales = {ip for _, ip in _lire_adaptateurs(filter_irrelevant=False)}
            for line in arp.stdout.splitlines():
                m = _rx.search(line)
                if m:
                    found_devices.append((m.group(1), m.group(2)))
            if found_devices:
                for ip, mac in found_devices:
                    is_pc = ip == w.dmx.target_ip or ip in _locales
                    label = " ← boîtier probable" if not is_pc else " ← ce PC"
                    add("Scan réseau", "ok" if not is_pc else "info",
                        f"Appareil trouvé : {ip}  MAC={mac}{label}")
            else:
                add("Scan réseau", "warn", "Aucun appareil trouvé sur 2.0.0.1–30")
        except Exception as e:
            add("Scan réseau", "warn", f"Scan ARP non disponible : {e}")

        # ── 10. Ping vers IP configurée ───────────────────────────────────
        self.progress.emit(68, "Ping boîtier...")
        try:
            target = w.dmx.target_ip
            # `-n` (nombre) et `-w` (délai en ms) sont propres à Windows ; sur
            # macOS/Linux ce sont `-c` et `-W` (en secondes). Avec les mauvais
            # arguments, ping sortait en erreur et le rapport concluait « ne
            # répond PAS » sur un boîtier parfaitement joignable.
            _args = (["ping", "-n", "2", "-w", "1000", target] if _WINDOWS
                     else ["ping", "-c", "2", "-W", "1", target])
            ping_result = subprocess.run(
                _args, capture_output=True, text=True,
                encoding=_ENCODAGE_CMD, errors="replace", timeout=10,
                creationflags=CREATE_NO_WINDOW
            )
            ping_ok = "ttl=" in ping_result.stdout.lower()
            if ping_ok:
                add("Ping", "ok", f"Boîtier {target} répond au ping ✓")
            else:
                # Beaucoup de nodes Art-Net ignorent l'ICMP par conception :
                # un ping muet n'est PAS une preuve de panne. C'est l'ArtPoll
                # unicast juste après qui tranche.
                add("Ping", "warn",
                    f"Boîtier {target} ne répond pas au ping "
                    f"(normal sur beaucoup de nodes — voir l'ArtPoll ci-dessous)")
        except Exception as e:
            add("Ping", "err", f"Ping échoué : {e}")

        # ── 10. ArtPoll unicast vers IP configurée ────────────────────────
        self.progress.emit(74, "ArtPoll unicast...")
        try:
            target = w.dmx.target_ip
            found, sender = _artpoll_probe(target, timeout=1.5, unicast=True)
            add("ArtPoll unicast",
                "ok" if found else "err",
                f"{target} → {'réponse de ' + sender if found else 'PAS DE RÉPONSE ← PROBLÈME'}")
        except Exception as e:
            add("ArtPoll unicast", "err", f"Erreur : {e}")

        # ── 11. Envoi test Art-Net ────────────────────────────────────────
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

        # ── 12. Projecteurs en mémoire ────────────────────────────────────
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


_WINDOWS = platform.system() == "Windows"
_ENCODAGE_CMD = "cp850" if _WINDOWS else "utf-8"


def _lire_adaptateurs(filter_irrelevant: bool = True):
    """Liste [(nom, IPv4)] des interfaces réseau, quel que soit le système.

    Sur macOS/Linux, `ipconfig` n'existe pas : le diagnostic annonçait alors
    « Aucun adaptateur Ethernet détecté — branchez le câble RJ45 » alors que le
    câble était branché et que le boîtier répondait à l'ArtPoll juste en
    dessous. Un diagnostic qui ment sur ce point envoie chercher la panne au
    mauvais endroit.
    """
    if _WINDOWS:
        out = subprocess.run(["ipconfig"], capture_output=True, text=True,
                             encoding=_ENCODAGE_CMD, errors="replace",
                             creationflags=CREATE_NO_WINDOW).stdout
        return _parse_adapters(out, filter_irrelevant)

    out = subprocess.run(["ifconfig", "-a"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=10).stdout
    return _parse_adapters_unix(out, filter_irrelevant)


def _parse_adapters_unix(ifconfig_out: str, filter_irrelevant: bool = True):
    """Parse `ifconfig` (macOS / Linux) pour extraire (nom, IPv4).

    Un bloc commence en colonne 0 par « en0: flags=… » et porte ses adresses
    sur les lignes indentées qui suivent (« inet 2.0.0.5 netmask … »).
    """
    import re
    adapters = []
    current = None
    ignorer = ("lo", "gif", "stf", "awdl", "llw", "utun", "bridge", "ap")
    for line in ifconfig_out.splitlines():
        if line and not line[0].isspace():
            nom = line.split(":", 1)[0].strip()
            saute = filter_irrelevant and nom.startswith(ignorer)
            current = None if saute else nom
        elif current:
            m = re.match(r"\s+inet\s+(\d{1,3}(?:\.\d{1,3}){3})", line)
            if m and not m.group(1).startswith("127."):
                adapters.append((current, m.group(1)))
                current = None
    return adapters


def _parse_adapters(ipconfig_out: str, filter_irrelevant: bool = True):
    """Parse ipconfig pour extraire (nom, IP).
    Si filter_irrelevant=False, retourne tous les adaptateurs avec une IPv4."""
    import re
    adapters = []
    current = None
    skip_keywords = ["loopback", "bluetooth", "tunnel", "vmware",
                     "vethernet", "isatap"]
    for line in ipconfig_out.splitlines():
        if line and not line.startswith(" "):
            low = line.lower()
            skip = filter_irrelevant and any(k in low for k in skip_keywords)
            current = None if skip else (line.strip().rstrip(":") if ":" in line else None)
        elif current and "ipv4" in line.lower():
            m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
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


def _ajuster_largeur(btn, marge=48):
    """Garantit que le libellé d'un bouton tient en entier.

    Les libellés commencent par un emoji, qui passe par une police de repli
    dont Qt estime mal la largeur : la taille naturelle calculée était trop
    courte et le texte se retrouvait tronqué. On mesure donc nous-mêmes.

    `ensurePolished()` est indispensable : sans lui on mesurerait la police par
    défaut du widget, pas celle que la feuille de style vient de lui poser.
    `marge` couvre le remplissage horizontal du style plus les bordures.
    """
    btn.ensurePolished()
    btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(btn.text()) + marge)


class BradDiagnosticDialog(QDialog):
    """Assistant BRAD — diagnostic complet DMX/Réseau."""

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self.setWindowTitle("Assistant de diagnostic Node — Diagnostic DMX")
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
        title = QLabel("Assistant de diagnostic Node")
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
                padding: 10px 18px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover  { background: #004a5a; border-color: #00d4ff99; }
            QPushButton:pressed { background: #001a2a; }
            QPushButton:disabled { background: #1a1a1a; color: #333; border-color: #222; }
        """)
        self._copy_btn.clicked.connect(self._copy_report)

        self._send_btn = QPushButton("✉️  Envoyer au support")
        self._send_btn.setEnabled(False)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: #cccccc;
                border: 1px solid #444; border-radius: 6px;
                padding: 10px 18px; font-size: 13px; font-weight: bold;
            }
            QPushButton:hover  { background: #333; border-color: #666; }
            QPushButton:pressed { background: #222; }
            QPushButton:disabled { background: #1a1a1a; color: #333; border-color: #222; }
        """)
        self._send_btn.clicked.connect(self._send_report)

        self._retry_btn = QPushButton("↺  Relancer")
        self._retry_btn.setEnabled(False)
        self._retry_btn.clicked.connect(self._start)

        close_btn = QPushButton("Fermer")
        close_btn.clicked.connect(self.accept)

        btn_row.setSpacing(10)
        btn_row.addWidget(self._copy_btn)
        btn_row.addWidget(self._send_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._retry_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        # Mesure APRÈS que la feuille de style du dialogue soit posée : c'est
        # elle qui fixe la police et le remplissage des boutons.
        # Le minimum est calculé sur « 📋  Copier le rapport », plus long que
        # le « ✓  Copié ! » qui le remplace un instant : le bouton garde donc
        # sa taille et la rangée ne saute pas pendant le message.
        for _b in (self._copy_btn, self._send_btn, self._retry_btn, close_btn):
            _ajuster_largeur(_b)

        self._raw_lines = []   # lignes texte brut pour le copier-coller
        self._worker = None
        # Problèmes réseau détectés {clé: valeur}. Servent à formuler un
        # diagnostic clair ; la correction, elle, reste manuelle — l'ancien
        # bouton « Corriger automatiquement » reconnectait le DMX dans le dos
        # de l'utilisateur, ce qui n'a pas sa place dans un outil de constat.
        self._fixable = {}

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
        self._fixable = {}

        # Détecter les problèmes corrigeables avant d'afficher
        dmx = self._window.dmx
        if dmx.transport != "artnet":
            self._fixable["transport"] = "artnet"

        # Détecter absence de carte Ethernet
        no_ethernet = any(
            cat == "Réseau" and "branchez le câble" in detail
            for cat, status, detail in results
        )
        if no_ethernet:
            self._fixable["no_ethernet"] = True

        # Récupérer les IPs locales pour détecter si target_ip == PC lui-même
        local_ips = set()
        try:
            local_ips = {ip for _, ip in _lire_adaptateurs()}
        except Exception:
            pass

        if dmx.target_ip in local_ips:
            # L'IP cible est le PC lui-même — chercher l'IP du boîtier dans les réponses ArtPoll
            external_found = None
            for cat, status, detail in results:
                if cat == "ArtPoll broadcast" and status == "ok" and "réponse de" in detail:
                    found_ip = detail.split("réponse de")[-1].strip()
                    if found_ip and found_ip not in local_ips:
                        external_found = found_ip
                        break
            if external_found:
                self._fixable["target_ip"] = external_found
            else:
                # Pas de boîtier détecté (câble débranché ?) — signaler sans proposer d'IP
                self._fixable["target_ip_local"] = dmx.target_ip
        else:
            # Si ArtPoll a trouvé un boîtier à une IP différente de la cible
            for cat, status, detail in results:
                if cat == "ArtPoll broadcast" and status == "ok" and "réponse de" in detail:
                    found_ip = detail.split("réponse de")[-1].strip()
                    if found_ip and found_ip != dmx.target_ip and found_ip not in local_ips:
                        self._fixable["target_ip"] = found_ip
                        break

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

        # ── Le piège n°1 : un node répond, mais la sortie est réglée sur USB ──
        # `send_dmx()` aiguille sur le transport ACTIF : avec `enttec`, l'envoi
        # Art-Net n'est jamais appelé et le node ne reçoit rien — alors que tous
        # les tests réseau ci-dessus sont au vert, puisqu'ils ouvrent leur PROPRE
        # socket et ne passent pas par la sortie de l'application. C'est
        # exactement ce qui fait chercher des heures du côté du réseau.
        _tr = getattr(dmx, 'transport', '')
        if _tr in ("enttec", "enttec_pro", "enttec_d2xx"):
            _node = next((d.split("réponse de")[-1].strip()
                          for c, s, d in results
                          if c.startswith("ArtPoll") and s == "ok" and "réponse de" in d),
                         None)
            if _node:
                self._append_html(
                    f'<br><span style="color:#ff9800;font-size:13px;font-weight:bold;">'
                    f'⚠ Un node Art-Net répond sur {_node}, mais la sortie est réglée '
                    f'sur « {_tr} » (USB).</span>'
                    f'<br><span style="color:#ccc;">Rien ne part sur le réseau tant que '
                    f'le transport est sur USB — les tests réseau ci-dessus passent par '
                    f'leur propre socket, pas par la sortie de MyStrow.<br>'
                    f'→ Connexions ▸ 🌐 Sortie DMX ▸ ⚙️ Paramétrer la sortie, '
                    f'choisir le node Art-Net, puis <b>Connecter</b>.</span>'
                )
                self._raw_lines.append("")
                self._raw_lines.append(
                    f"  ⚠ Node Art-Net détecté sur {_node} mais transport = {_tr} (USB)"
                    f" — rien ne part sur le réseau.")

        # Avertissement câble débranché
        if "no_ethernet" in self._fixable:
            self._append_html(
                '<br><span style="color:#f44336;font-size:13px;font-weight:bold;">'
                '🔌 Aucun câble RJ45 détecté — branchez le câble Ethernet entre le PC et le boîtier !</span>'
            )

        # Forcer une erreur visible si target_ip == IP locale (PC lui-même)
        if "target_ip_local" in self._fixable:
            self._append_html(
                f'<br><span style="color:#f44336;font-weight:bold;">'
                f'✗ IP cible ({self._fixable["target_ip_local"]}) est l\'IP du PC lui-même —'
                f' les paquets DMX ne partent pas vers le boîtier !</span>'
            )
        elif "target_ip" in self._fixable and self._fixable["target_ip"] != self._window.dmx.target_ip:
            self._append_html(
                f'<br><span style="color:#ff9800;font-weight:bold;">'
                f'⚠ Boîtier détecté sur {self._fixable["target_ip"]}'
                f' mais IP cible = {self._window.dmx.target_ip}</span>'
            )

        self._copy_btn.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._retry_btn.setEnabled(True)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _append_html(self, html: str):
        self._output.append(html)

    def _copy_report(self):
        text = "\n".join(self._raw_lines)
        QApplication.clipboard().setText(text)
        self._copy_btn.setText("✓  Copié !")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText("📋  Copier le rapport"))

    def _send_report(self):
        """Ouvre un mail au support avec le rapport BRAD pré-rempli."""
        send_report_email(
            self, "Diagnostic BRAD (DMX / réseau)", "\n".join(self._raw_lines),
            intro="Bonjour,\n\nVoici le rapport du diagnostic BRAD (sortie DMX / réseau).")
