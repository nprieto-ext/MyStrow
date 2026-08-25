"""
node_connection.py — Paramétrer la sortie Node DMX
Détecte et corrige automatiquement les problèmes de connexion Art-Net.
Tous les boîtiers ElectroConcept sont sur 2.0.0.15.
"""

import re
import time
import socket
import subprocess
import platform

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QApplication,
    QWidget, QStackedWidget, QScrollArea, QLineEdit, QComboBox, QCheckBox,
    QGridLayout,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRectF, QPointF, QRect
from PySide6.QtGui import (
    QFont, QCursor, QPainter, QPen, QBrush, QColor, QLinearGradient,
    QPainterPath, QFontMetrics,
)
from core import ComboSansMolette, guide_banner
from i18n import tr

# ============================================================
# CONSTANTES
# ============================================================

TARGET_IP   = "2.0.0.15"
TARGET_PORT = 6454

CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0

_SKIP_ADAPTERS = [
    "wi-fi", "wifi", "wireless", "loopback", "vmware", "virtual",
    "bluetooth", "tunnel", "teredo", "isatap", "6to4", "miniport",
    "local*", "vethernet",
]


# ============================================================
# UTILITAIRES RÉSEAU
# ============================================================

def _artpoll_packet() -> bytes:
    p = bytearray(b'Art-Net\x00')
    p.extend(b'\x00\x20')
    p.extend(b'\x00\x0e')
    p.extend(b'\x00\x00')
    return bytes(p)


def _get_all_local_ips() -> set:
    """Toutes les IPs locales du PC pour filtrer les faux positifs ArtPoll."""
    local = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if not ip.startswith("127.") and ":" not in ip:
                local.add(ip)
    except Exception:
        pass
    try:
        r = subprocess.run(["ipconfig"], capture_output=True, text=True,
                           encoding="cp1252", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
        for line in r.stdout.splitlines():
            if "ipv4" in line.lower():
                m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
                if m:
                    local.add(m.group(1))
    except Exception:
        pass
    return local


def _get_ethernet_adapters():
    """Retourne [(nom, ip, description, connected)] — Windows et Mac."""
    if platform.system() == "Darwin":
        return _get_ethernet_adapters_mac()
    return _get_ethernet_adapters_windows()


def _get_ethernet_adapters_windows():
    """Détecte les adaptateurs réseau sur Windows via ipconfig /all."""
    try:
        r = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True,
                           encoding="cp1252", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
    except Exception:
        return []

    adapters = []
    current_name = None
    current_ip = ""
    current_desc = ""
    current_connected = False
    skip_current = False

    for line in r.stdout.splitlines():
        stripped = line.strip()
        is_section = (line and not line.startswith(("\t", " "))
                      and stripped.endswith(":"))
        if is_section:
            if current_name and not skip_current:
                adapters.append((current_name, current_ip, current_desc, current_connected))
            raw = stripped.rstrip(":").strip()
            for prefix in ("Carte Ethernet ", "Ethernet adapter ",
                           "Carte réseau sans fil ", "Wireless LAN adapter ",
                           "Adaptateur ", "Adapter "):
                if raw.lower().startswith(prefix.lower()):
                    raw = raw[len(prefix):]
                    break
            current_name = raw.strip()
            current_ip = ""
            current_desc = ""
            current_connected = False
            skip_current = any(kw in current_name.lower() for kw in _SKIP_ADAPTERS)
            continue
        if not current_name or skip_current:
            continue
        if "ipv4" in stripped.lower():
            m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", stripped)
            if m and not m.group(1).startswith("127."):
                current_ip = m.group(1)
                current_connected = True
        elif "description" in stripped.lower() or "description" in line.lower():
            parts = stripped.split(":", 1)
            if len(parts) == 2:
                current_desc = parts[1].strip()
        elif "media disconnected" in stripped.lower() or "média déconnecté" in stripped.lower():
            current_connected = False

    if current_name and not skip_current:
        adapters.append((current_name, current_ip, current_desc, current_connected))
    return adapters


def _mac_hardware_ports():
    """Associe chaque interface BSD macOS à son nom lisible.

    `ifconfig` ne connaît que en0, en1, en5… — des noms qui ne disent rien à
    l'utilisateur, et qui se ressemblent tous. `networksetup` donne le libellé
    du Réglage Système correspondant (« Wi-Fi », « Ethernet Thunderbolt »…).
    Retourne {"en0": "Wi-Fi", ...}, vide si la commande échoue.
    """
    ports = {}
    try:
        r = subprocess.run(["networksetup", "-listallhardwareports"],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return ports
    label = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("Hardware Port:"):
            label = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and label:
            device = line.split(":", 1)[1].strip()
            if device:
                ports[device] = label
            label = None
    return ports


def _get_ethernet_adapters_mac():
    """Détecte les interfaces réseau sur macOS via ifconfig."""
    _SKIP_PREFIXES = ("lo", "utun", "awdl", "llw", "stf", "gif", "anpi",
                      "bridge", "ap1", "XHC", "p2p")
    try:
        r = subprocess.run(["ifconfig", "-a"], capture_output=True, text=True, timeout=5)
    except Exception:
        return []

    hw_ports = _mac_hardware_ports()

    adapters = []
    current_name = None
    current_ip = ""
    current_connected = False

    def _keep(device, ip):
        """Une interface mérite-t-elle d'être proposée à l'utilisateur ?

        Un Mac expose une dizaine d'interfaces en*, dont la plupart sont des
        emplacements Thunderbolt/USB vides : sans nom lisible ET sans adresse,
        elles n'apportent rien et noient la vraie carte dans la liste.
        """
        if not device or any(device.startswith(p) for p in _SKIP_PREFIXES):
            return False
        return bool(ip) or device in hw_ports

    def _label(device):
        """« Ethernet Thunderbolt (en5) » plutôt que « en5 »."""
        port = hw_ports.get(device)
        return f"{port} ({device})" if port else device

    def _flush():
        if _keep(current_name, current_ip):
            # description = nom BSD brut, utile en diagnostic.
            adapters.append((_label(current_name), current_ip,
                             current_name, current_connected))

    for line in r.stdout.splitlines():
        # Ligne d'en-tête d'interface : "en0: flags=..."
        m = re.match(r'^(\w[\w.]*): ', line)
        if m:
            _flush()
            current_name = m.group(1)
            current_ip = ""
            current_connected = "UP" in line
        elif current_name:
            stripped = line.strip()
            if stripped.startswith("inet ") and "inet6" not in stripped:
                m2 = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", stripped)
                if m2:
                    ip = m2.group(1)
                    if not ip.startswith("127."):
                        current_ip = ip
                        current_connected = True

    _flush()

    # Les cartes configurées passent devant : c'est celle du node qu'on cherche.
    adapters.sort(key=lambda a: (not a[1].startswith("2."), not a[1]))
    return adapters


def _ping(ip: str, timeout_ms: int = 1000) -> bool:
    try:
        if platform.system() == "Darwin":
            r = subprocess.run(
                ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), ip],
                capture_output=True
            )
        else:
            r = subprocess.run(
                ["ping", "-n", "1", "-w", str(timeout_ms), ip],
                capture_output=True, creationflags=CREATE_NO_WINDOW
            )
        return r.returncode == 0
    except Exception:
        return False


def _artpoll_probe(target_ip: str, timeout: float = 1.5) -> bool:
    """ArtPoll vers target_ip, filtre les réponses du PC lui-même.

    On écoute sur le port 6454, PAS sur un port éphémère : la spec Art-Net veut
    que l'ArtPollReply soit émis vers le port 6454, pas vers le port source. Un
    node qui respecte la spec répondait donc dans le vide, et l'assistant
    concluait « le boîtier n'a pas répondu » alors qu'il répondait très bien
    (reproduit sur Mac : le même ArtPoll lancé depuis le Terminal, socket liée
    à 6454, recevait la réponse immédiatement).

    Le port éphémère servait à ne pas recevoir notre propre broadcast en
    loopback sous Windows ; le filtre sur l'opcode ArtPollReply (0x2100) et sur
    les IP locales couvre déjà ce cas, sans sacrifier les réponses réelles.
    """
    # Si aucune carte réseau n'a d'IP en 2.x, le boitier est forcément inaccessible
    adapters = _get_ethernet_adapters()
    if not any(ip.startswith("2.") for _, ip, _, _ in adapters):
        return False
    local_ips = _get_all_local_ips()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            # macOS/BSD : sans ça, cohabiter avec une autre appli DMX sur 6454
            # échoue même avec SO_REUSEADDR.
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        try:
            s.bind(("", 6454))
        except OSError:
            # Port déjà pris (QLC+, Chataigne…) : on retombe sur un port
            # éphémère, qui ne verra que les nodes répondant au port source.
            s.bind(("", 0))
        s.settimeout(timeout)
        for dst in ("2.255.255.255", "255.255.255.255", target_ip):
            try:
                s.sendto(_artpoll_packet(), (dst, 6454))
            except Exception:
                pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                s.settimeout(max(0.05, deadline - time.time()))
                data, (sender, _) = s.recvfrom(512)
                # Accepter uniquement ArtPollReply (opcode 0x2100),
                # en ignorant notre propre ArtPoll (0x2000) et le PC lui-même
                if (data[:8] == b'Art-Net\x00'
                        and data[8:10] == b'\x00\x21'
                        and sender not in local_ips):
                    s.close()
                    return True
            except Exception:
                break
        s.close()
    except Exception:
        pass
    return False


def _set_static_ip(adapter_name: str) -> bool:
    """Configure l'IP statique 2.0.0.1/8 sur l'adaptateur.
    Essaie PowerShell (plus fiable), puis netsh en fallback."""

    # ── Méthode 1 : PowerShell New-NetIPAddress ────────────────────────
    try:
        ps_cmd = (
            f"$iface = Get-NetAdapter | Where-Object {{ $_.Name -eq '{adapter_name}' }};"
            f"if ($iface) {{"
            f"  $iface | Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue"
            f"    | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue;"
            f"  $iface | New-NetIPAddress -AddressFamily IPv4"
            f"    -IPAddress '2.0.0.1' -PrefixLength 8 -ErrorAction Stop | Out-Null;"
            f"}}"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=15
        )
        if r.returncode == 0:
            return True
        print(f"[SetIP] PowerShell rc={r.returncode}: {r.stderr.decode(errors='replace').strip()}")
    except Exception as e:
        print(f"[SetIP] PowerShell exception: {e}")

    # ── Méthode 2 : netsh (fallback) ─────────────────────────────────
    try:
        r = subprocess.run(
            ["netsh", "interface", "ip", "set", "address",
             f"name={adapter_name}", "static", "2.0.0.1", "255.0.0.0", "none"],
            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=10
        )
        if r.returncode == 0:
            return True
        print(f"[SetIP] netsh rc={r.returncode}: {r.stderr.decode(errors='replace').strip()}")
    except Exception as e:
        print(f"[SetIP] netsh exception: {e}")

    return False


def _open_network_connections():
    try:
        if platform.system() == "Darwin":
            # Ouvre les Préférences Réseau (fonctionne sur macOS Monterey, Ventura, Sonoma)
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.network"])
        else:
            subprocess.Popen(["control", "ncpa.cpl"], creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


# ============================================================
# WORKER — tourne tous les checks en arrière-plan
# ============================================================

class _DiagWorker(QThread):
    step   = Signal(int, str, str, str)  # (index, status, titre, detail)
    done   = Signal(list)                # [(status, titre, detail, fix_key)]

    def run(self):
        results = []

        # ── 1. Transport Art-Net ──────────────────────────────────────────
        try:
            from artnet_dmx import TRANSPORT_ARTNET
            import importlib, sys
            # Trouver l'instance ArtNetDMX via le module déjà chargé
            transport_ok = True
            transport_val = "?"
            for mod in sys.modules.values():
                if hasattr(mod, '_dmx_instance'):
                    dmx = mod._dmx_instance
                    transport_val = dmx.transport
                    transport_ok = (dmx.transport == TRANSPORT_ARTNET)
                    break
        except Exception as e:
            transport_ok = False
            transport_val = str(e)

        results.append((
            "ok" if transport_ok else "err",
            "Transport Art-Net",
            f"Mode actuel : {transport_val}" if not transport_ok else "Mode Art-Net actif",
            "fix_transport" if not transport_ok else None
        ))
        self.step.emit(0, results[-1][0], results[-1][1], results[-1][2])

        # ── 2. Carte Ethernet sur 2.x.x.x ───────────────────────────────
        adapters = _get_ethernet_adapters()
        eth_ok = any(ip.startswith("2.") for n, ip, d, c in adapters)
        eth_name = next((n for n, ip, d, c in adapters if ip.startswith("2.")), None)
        if not adapters:
            # Pas « vérifiez le câble RJ45 » : sur un USB NODE DMX il n'y en a
            # pas, et c'est le câble USB qui porte la carte réseau.
            eth_detail = "Aucune carte réseau détectée — vérifiez le câble entre le PC et le boîtier"
            eth_fix = "fix_cable"
        elif not eth_ok:
            eth_name = adapters[0][0]
            eth_detail = f"Carte « {eth_name} » — IP incorrecte ({adapters[0][1] or 'non configurée'})"
            eth_fix = "fix_ip"
        else:
            eth_detail = f"Carte « {eth_name} » — IP 2.0.0.x ✓"
            eth_fix = None

        results.append(("ok" if eth_ok else "err", "Carte Ethernet", eth_detail, eth_fix))
        self.step.emit(1, results[-1][0], results[-1][1], results[-1][2])

        # ── 3. Boîtier 2.0.0.15 joignable ──────────────────────────────
        if eth_ok:
            box_ok = _ping(TARGET_IP, timeout_ms=1200)
            if not box_ok:
                box_ok = _artpoll_probe(TARGET_IP, timeout=1.5)
            box_detail = f"Boîtier {TARGET_IP} répond ✓" if box_ok else f"Boîtier {TARGET_IP} ne répond pas — allumé ? câble branché ?"
        else:
            box_ok = False
            box_detail = "En attente de la carte réseau"

        results.append(("ok" if box_ok else "err", f"Boîtier {TARGET_IP}", box_detail,
                        None if box_ok else "fix_box"))
        self.step.emit(2, results[-1][0], results[-1][1], results[-1][2])

        # ── 4. IP cible dans MyStrow ─────────────────────────────────────
        ip_ok = False
        ip_detail = "Impossible de vérifier"
        ip_fix = None
        try:
            import sys
            for mod in sys.modules.values():
                if hasattr(mod, '_dmx_instance'):
                    dmx = mod._dmx_instance
                    ip_ok = (dmx.target_ip == TARGET_IP)
                    ip_detail = (f"IP cible : {dmx.target_ip} ✓" if ip_ok
                                 else f"IP cible : {dmx.target_ip} → doit être {TARGET_IP}")
                    ip_fix = None if ip_ok else "fix_target_ip"
                    break
        except Exception:
            pass

        results.append(("ok" if ip_ok else "err", "IP cible MyStrow", ip_detail, ip_fix))
        self.step.emit(3, results[-1][0], results[-1][1], results[-1][2])

        self.done.emit(results)


# ============================================================
# DIALOG
# ============================================================

_C_OK   = "#4ade80"
_C_ERR  = "#f87171"
_C_WARN = "#fbbf24"
_C_INFO = "#00d4ff"
_C_DIM  = "#555555"


class NodeConnectionDialog(QDialog):
    """Paramétrer la sortie Node DMX — détection et correction automatique."""

    def __init__(self, parent=None, target_ip: str = TARGET_IP):
        super().__init__(parent)
        self._main_win = parent
        self.setWindowTitle(tr("nc_setup_node_out"))
        self.setFixedSize(480, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog  { background: #131313; }
            QLabel   { color: #e0e0e0; background: transparent; }
            QPushButton {
                background: #1e1e1e; color: #aaa;
                border: 1px solid #333; border-radius: 6px;
                padding: 8px 20px; font-size: 12px;
            }
            QPushButton:hover  { background: #252525; color: #eee; border-color: #555; }
            QPushButton:pressed { background: #0a0a0a; }
            QPushButton:disabled { color: #333; border-color: #222; }
        """)

        self._worker = None
        self._results = []
        self._row_widgets = []  # [(icon_lbl, title_lbl, detail_lbl)]

        self._build_ui()
        QTimer.singleShot(200, self._run)

    # ──────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)

        # Titre
        title = QLabel(tr("nc_node_out_title"))
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet("color: #f0f0f0;")
        sub = QLabel(tr("nc_f_box", TARGET_IP=TARGET_IP))
        sub.setStyleSheet("color: #444; font-size: 10px;")
        root.addWidget(title)
        root.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #222;")
        root.addWidget(sep)

        # 4 lignes de check
        checks_frame = QFrame()
        checks_frame.setStyleSheet(
            "QFrame { background: #1a1a1a; border: 1px solid #252525; border-radius: 10px; }"
        )
        checks_lay = QVBoxLayout(checks_frame)
        checks_lay.setContentsMargins(18, 14, 18, 14)
        checks_lay.setSpacing(14)

        labels = [
            "Transport Art-Net",
            "Carte Ethernet",
            f"Boîtier {TARGET_IP}",
            "IP cible MyStrow",
        ]
        for i, label in enumerate(labels):
            row = QHBoxLayout()
            row.setSpacing(12)

            icon = QLabel("◌")
            icon.setFont(QFont("Segoe UI", 14))
            icon.setStyleSheet(f"color: {_C_DIM};")
            icon.setFixedWidth(22)
            icon.setAlignment(Qt.AlignCenter)

            col = QVBoxLayout()
            col.setSpacing(2)
            t = QLabel(label)
            t.setFont(QFont("Segoe UI", 10, QFont.Bold))
            t.setStyleSheet("color: #ccc;")
            d = QLabel(tr("nc_checking"))
            d.setFont(QFont("Segoe UI", 9))
            d.setStyleSheet(f"color: {_C_DIM};")
            d.setWordWrap(True)
            col.addWidget(t)
            col.addWidget(d)

            row.addWidget(icon)
            row.addLayout(col, 1)
            checks_lay.addLayout(row)

            if i < len(labels) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet("color: #222; border: none; border-top: 1px solid #222;")
                checks_lay.addWidget(line)

            self._row_widgets.append((icon, t, d))

        root.addWidget(checks_frame)

        # Zone message global
        self._msg_lbl = QLabel("")
        self._msg_lbl.setAlignment(Qt.AlignCenter)
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setFont(QFont("Segoe UI", 10))
        self._msg_lbl.setStyleSheet("color: #555;")
        root.addWidget(self._msg_lbl)

        # Bouton Actualiser inline (affiché uniquement sur câble_issue)
        self._refresh_inline_btn = QPushButton(tr("nc_refresh"))
        self._refresh_inline_btn.setFixedHeight(34)
        self._refresh_inline_btn.setStyleSheet(
            "QPushButton { background: #1a2a1a; color: #66cc66; border: 1px solid #336633;"
            " border-radius: 6px; padding: 0 20px; font-size: 11px; }"
            "QPushButton:hover { background: #223322; color: #88ee88; border-color: #448844; }"
        )
        self._refresh_inline_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_inline_btn.setVisible(False)
        self._refresh_inline_btn.clicked.connect(self._run)
        _inline_row = QHBoxLayout()
        _inline_row.addStretch()
        _inline_row.addWidget(self._refresh_inline_btn)
        _inline_row.addStretch()
        root.addSpacing(6)
        root.addLayout(_inline_row)

        root.addStretch()

        # Boutons
        btn_row = QHBoxLayout()

        self._fix_btn = QPushButton(tr("nc_config_network"))
        self._fix_btn.setVisible(False)
        self._fix_btn.setStyleSheet("""
            QPushButton {
                background: #1a0f00; color: #fbbf24;
                border: 1px solid #fbbf2444; border-radius: 6px;
                padding: 10px 20px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: #251500; border-color: #fbbf2499; }
        """)
        self._fix_btn.clicked.connect(self._open_wizard)

        self._retry_btn = QPushButton(tr("nc_rerun"))
        self._retry_btn.setEnabled(False)
        self._retry_btn.clicked.connect(self._run)

        self._manual_btn = QPushButton(tr("nc_network_folder"))
        self._manual_btn.setVisible(False)
        self._manual_btn.clicked.connect(_open_network_connections)

        close_btn = QPushButton(tr("nc_close"))
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(self._fix_btn)
        btn_row.addWidget(self._manual_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._retry_btn)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ──────────────────────────────────────────────────────
    # CHECKS
    # ──────────────────────────────────────────────────────

    def _run(self):
        self._fix_btn.setVisible(False)
        self._manual_btn.setVisible(False)
        self._refresh_inline_btn.setVisible(False)
        self._retry_btn.setEnabled(False)
        self._msg_lbl.setText(tr("nc_analysing"))
        self._msg_lbl.setStyleSheet("color: #555;")
        for icon, t, d in self._row_widgets:
            icon.setText("◌")
            icon.setStyleSheet(f"color: {_C_DIM};")
            d.setText(tr("nc_checking"))
            d.setStyleSheet(f"color: {_C_DIM};")

        # Injecter l'instance dmx dans un attribut module pour que le worker y accède
        if self._main_win and hasattr(self._main_win, 'dmx'):
            import sys
            import artnet_dmx as _adm
            _adm._dmx_instance = self._main_win.dmx

        self._worker = _DiagWorker()
        self._worker.step.connect(self._on_step)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_step(self, idx: int, status: str, titre: str, detail: str):
        if idx >= len(self._row_widgets):
            return
        icon, t, d = self._row_widgets[idx]
        if status == "ok":
            icon.setText("✓")
            icon.setStyleSheet(f"color: {_C_OK};")
            d.setStyleSheet(f"color: {_C_DIM};")
        else:
            icon.setText("✗")
            icon.setStyleSheet(f"color: {_C_ERR};")
            d.setStyleSheet(f"color: {_C_ERR};")
        d.setText(detail)

    def _on_done(self, results: list):
        self._results = results
        errors = [r for r in results if r[0] == "err"]
        fixable = [r for r in errors if r[3] and r[3] != "fix_cable" and r[3] != "fix_box"]
        cable_issue = any(r[3] == "fix_cable" for r in errors)
        box_issue = any(r[3] == "fix_box" for r in errors)

        if not errors:
            self._msg_lbl.setText(tr("nc_all_ok"))
            self._msg_lbl.setStyleSheet(f"color: {_C_OK}; font-weight: bold;")
        elif cable_issue:
            self._msg_lbl.setText(tr("nc_no_ethernet"))
            self._msg_lbl.setStyleSheet(f"color: {_C_ERR};")
            self._manual_btn.setVisible(True)
            self._refresh_inline_btn.setVisible(True)
        elif box_issue and not fixable:
            self._msg_lbl.setText(tr("nc_f_no_answer2", TARGET_IP=TARGET_IP))
            self._msg_lbl.setStyleSheet(f"color: {_C_ERR};")
        else:
            self._msg_lbl.setText(tr("nc_f_n_problems", a0=len(errors)))
            self._msg_lbl.setStyleSheet(f"color: {_C_WARN};")

        self._fix_btn.setVisible(bool(fixable))
        self._retry_btn.setEnabled(True)

    # ──────────────────────────────────────────────────────
    # AUTO-FIX
    # ──────────────────────────────────────────────────────

    def _open_wizard(self):
        self.accept()
        if self._main_win:
            dlg = NodeSetupWizard(self._main_win)
            dlg.exec()


# ============================================================
# WIZARD — Configuration réseau pas à pas
# ============================================================

_BTN_PRIMARY = """
QPushButton {
    background: #00d4ff; color: #000000; font-weight: 700;
    font-size: 12px; border-radius: 6px; border: none; padding: 0 20px;
}
QPushButton:hover { background: #22ddff; }
QPushButton:disabled { background: #1a3a3a; color: #2a6a6a; }
"""
_BTN_SECONDARY = """
QPushButton {
    background: #242424; color: #aaaaaa; font-size: 11px;
    border: 1px solid #383838; border-radius: 6px; padding: 0 16px;
}
QPushButton:hover { background: #2e2e2e; color: #e0e0e0; border-color: #484848; }
"""
_BTN_GHOST = """
QPushButton {
    background: transparent; color: #555555; font-size: 11px;
    border: none; border-radius: 4px; padding: 0 12px;
}
QPushButton:hover { color: #aaaaaa; background: #222222; }
"""
_BTN_ADAPTER = """
QPushButton {
    background: #212121; color: #cccccc; font-size: 10px;
    border: 1px solid #2e2e2e; border-radius: 7px;
    text-align: left; padding: 10px 14px;
}
QPushButton:hover { background: #282828; border-color: #00d4ff; color: white; }
"""
_BTN_ADAPTER_OK = """
QPushButton {
    background: #0f2318; color: #4ade80; font-size: 10px;
    border: 1px solid #1a4a2a; border-radius: 7px;
    text-align: left; padding: 10px 14px;
}
QPushButton:hover { background: #162d20; }
"""
_BTN_ADAPTER_SEL = """
QPushButton {
    background: #0a2830; color: #00d4ff; font-size: 10px;
    border: 2px solid #00d4ff; border-radius: 7px;
    text-align: left; padding: 10px 14px; font-weight: bold;
}
"""

_WIZARD_STEPS = ["Câbles", "Carte réseau", "Adresse IP", "Connexion"]

P_W_DETECTING = 0
P_W_CONNECTED = 1
P_W_CABLES    = 2
P_W_ADAPTERS  = 3
P_W_IP_METHOD = 4
P_W_WORKING   = 5
P_W_IP_MANUAL = 6
P_W_SUCCESS   = 7


class _AdapterScanner(QThread):
    done = Signal(list)
    def run(self): self.done.emit(_get_ethernet_adapters())


class _NetworkSetup(QThread):
    done = Signal(str, str)
    def __init__(self, adapter_name):
        super().__init__()
        self.adapter_name = adapter_name
    def run(self):
        if _set_static_ip(self.adapter_name):
            time.sleep(1.5)
            self.done.emit("ok", self.adapter_name)
        else:
            self.done.emit("manual", self.adapter_name)


class _NodeSearcher(QThread):
    finished = Signal(bool)
    def run(self):
        time.sleep(0.5)
        try:
            adapters = _get_ethernet_adapters()
            if not any(ip.startswith("2.") for n, ip, d, c in adapters):
                self.finished.emit(False); return
            if _artpoll_probe(TARGET_IP, timeout=2.0):
                self.finished.emit(True); return
            self.finished.emit(_ping(TARGET_IP, timeout_ms=1500))
        except Exception:
            self.finished.emit(False)


class _QuickDetector(QThread):
    finished = Signal(bool)
    def run(self):
        try:
            if not _get_ethernet_adapters():
                self.finished.emit(False); return
            self.finished.emit(_artpoll_probe(TARGET_IP, timeout=1.0)
                               or _ping(TARGET_IP, timeout_ms=800))
        except Exception:
            self.finished.emit(False)


class NodeWiringAnim(QWidget):
    """Le branchement du boîtier, joué en boucle — dessiné, pas filmé.

    La page « Branchons le boîtier » décrivait DEUX câbles : un RJ45 pour les
    données, un USB pour l'alimentation. C'est vrai du NODE 1 (face `NET` +
    `POWER`), c'est FAUX du USB NODE DMX, qui n'a qu'une seule prise USB-C par
    laquelle passent à la fois le courant ET l'Art-Net. Le client qui a acheté
    ce modèle-là cherchait un câble réseau qui n'existe pas sur son boîtier.

    D'où deux variantes, choisies par l'utilisateur d'après ce qu'il voit sur
    la face de son boîtier — la seule question à laquelle il peut répondre sans
    rien connaître :
      • `rj45` : deux prises, deux câbles, deux rôles ;
      • `usb`  : une prise, un câble, les deux rôles à la fois.

    Dessiné au QPainter et non filmé : une vidéo voudrait dire embarquer un
    média et QtMultimedia dans les quatre configurations de build, pour une
    boucle de trois secondes qui ne montrerait qu'UN des deux boîtiers. Ici les
    deux variantes coûtent quelques coordonnées, restent nettes en 4K et
    suivent le thème sombre. Même technique que le dessin de la manette.
    """

    # Repères de la scène, en coordonnées logiques (le painter met à l'échelle).
    _W, _H = 296.0, 146.0

    _CYAN   = "#00d4ff"   # données (Art-Net)
    _AMBRE  = "#f0a030"   # courant
    _VERT   = "#4ade80"   # LED alimentée
    _CORPS  = "#242424"
    _TRAIT  = "#3a3a3a"

    def __init__(self, variant="rj45", parent=None):
        super().__init__(parent)
        self._variant = variant
        self._t = 0.0
        # 220 et non 190 : la légende supprimée sous le dessin a rendu sa
        # hauteur à la page, et c'est la hauteur qui bride l'échelle ici (la
        # largeur est déjà saturée). Autant la donner au boîtier.
        self.setMinimumHeight(220)
        self.setStyleSheet("background: transparent;")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._avancer)

    def set_variant(self, variant):
        if variant != self._variant:
            self._variant = variant
            self._t = 0.0
            self.update()

    # Le dialogue reste ouvert pendant tout l'assistant : une animation qui
    # continue de tourner sur une page qu'on ne voit plus, c'est 25 repaints par
    # seconde pour rien.
    def showEvent(self, e):
        super().showEvent(e)
        self._timer.start(40)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _avancer(self):
        self._t = (self._t + 0.04 / 4.2) % 1.0   # boucle de 4,2 s
        self.update()

    @staticmethod
    def _amorti(x):
        """Ease-out : le câble ralentit en arrivant sur la prise."""
        x = max(0.0, min(1.0, x))
        return 1.0 - (1.0 - x) ** 3

    # ── géométrie du boîtier ──────────────────────────────────
    # Vue de trois quarts, comme les photos du guide : la plaque de face est
    # de front (c'est elle qu'on doit lire), le corps fuit vers l'arrière-droit.
    _FACE = (100.0, 26.0, 116.0, 108.0)      # x, y, largeur, hauteur
    _PROF = (74.0, -18.0)                    # vecteur de fuite

    def _face_pts(self):
        x, y, w, h = self._FACE
        return (QPointF(x, y), QPointF(x + w, y),
                QPointF(x + w, y + h), QPointF(x, y + h))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Scène dessinée en repère fixe puis mise à l'échelle : les coordonnées
        # ci-dessous ne bougent pas si le dialogue change de taille.
        ech = min(self.width() / self._W, self.height() / self._H)
        p.translate((self.width() - self._W * ech) / 2.0,
                    (self.height() - self._H * ech) / 2.0)
        p.scale(ech, ech)

        t = self._t
        # Deux temps seulement : le câble entre (0 → 35 %), puis il est en place
        # et le boîtier est alimenté (35 % → fin). Il y avait un troisième temps
        # `vie`, qui ne démarrait qu'à 50 % — l'alimentation semblait arriver un
        # instant APRÈS le branchement, alors que c'est le branchement qui la
        # donne. Le voyant part maintenant à la seconde où la fiche s'engage.
        avance  = self._amorti(t / 0.35) if t < 0.35 else 1.0
        branche = 1.0 if t >= 0.35 else 0.0

        self._dessiner_corps(p)
        self._dessiner_face(p, branche)
        self._dessiner_cables(p, avance, branche)
        p.end()

    def _clignote(self, depuis, battements):
        """Créneau 0/1 pour un voyant qui clignote, depuis l'instant `depuis`.

        Un sinus donnait une respiration, pas un clignotement : l'œil y lit
        « ça pulse ». Il faut un créneau — allumé net, éteint net — avec juste
        assez d'adoucissement sur les fronts pour ne pas scintiller.
        """
        u = self._t - depuis
        if u <= 0:
            return 0.0
        ph = (u * battements) % 1.0
        m = 0.07                       # durée des fronts, en fraction de cycle
        if ph < m:        return ph / m
        if ph < 0.5 - m:  return 1.0
        if ph < 0.5:      return (0.5 - ph) / m
        return 0.0

    # ── le boîtier ────────────────────────────────────────────

    def _dessiner_corps(self, p):
        """Corps alu extrudé, dessus nervuré — la signature des ElectroConcept.

        C'est aux nervures qu'on reconnaît ces boîtiers sur les photos du
        guide, avant même de lire la sérigraphie. Sans elles on dessine « une
        boîte noire », ce que le client ne rapproche de rien.
        """
        a, b, c, d = self._face_pts()
        dx, dy = self._PROF
        ap = QPointF(a.x() + dx, a.y() + dy)
        bp = QPointF(b.x() + dx, b.y() + dy)
        cp = QPointF(c.x() + dx, c.y() + dy)

        # Flanc droit
        flanc = QPainterPath(b)
        flanc.lineTo(bp); flanc.lineTo(cp); flanc.lineTo(c); flanc.closeSubpath()
        deg = QLinearGradient(b.x(), 0, bp.x(), 0)
        deg.setColorAt(0.0, QColor("#26262a"))
        deg.setColorAt(1.0, QColor("#171719"))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(deg)); p.drawPath(flanc)

        # Dessus
        dessus = QPainterPath(a)
        dessus.lineTo(b); dessus.lineTo(bp); dessus.lineTo(ap); dessus.closeSubpath()
        degt = QLinearGradient(0, a.y(), 0, ap.y())
        degt.setColorAt(0.0, QColor("#3c3c42"))
        degt.setColorAt(1.0, QColor("#2a2a30"))
        p.setBrush(QBrush(degt)); p.drawPath(dessus)

        # Nervures : des lignes qui suivent la fuite, du bord avant au bord
        # arrière. Écrêtées au dessus pour ne pas baver sur la face.
        p.save()
        p.setClipPath(dessus)
        n = 22
        for i in range(1, n):
            u = i / n
            p1 = QPointF(a.x() + (b.x() - a.x()) * u, a.y())
            p2 = QPointF(ap.x() + (bp.x() - ap.x()) * u, ap.y())
            # Creux puis crête : c'est le couple ombre/lumière qui fait lire une
            # nervure. Un seul trait sombre passait pour une rayure.
            p.setPen(QPen(QColor(0, 0, 0, 190), 1.5))
            p.drawLine(p1, p2)
            p.setPen(QPen(QColor(255, 255, 255, 40), 1.1))
            p.drawLine(QPointF(p1.x() + 1.9, p1.y()), QPointF(p2.x() + 1.9, p2.y()))
        p.restore()

        # Arêtes vives : l'alu anodisé accroche la lumière sur les angles.
        p.setPen(QPen(QColor("#55555c"), 1.2))
        p.drawLine(a, b); p.drawLine(b, bp); p.drawLine(a, ap)
        p.setPen(QPen(QColor("#000000"), 1.2))
        p.drawLine(c, cp)

    def _dessiner_face(self, p, branche):
        """Plaque de face : vis aux quatre coins, sérigraphie blanche, prises."""
        a, b, c, d = self._face_pts()
        x, y, w, h = self._FACE
        plaque = QRectF(x, y, w, h)

        deg = QLinearGradient(0, y, 0, y + h)
        deg.setColorAt(0.0, QColor("#242428"))
        deg.setColorAt(1.0, QColor("#141416"))
        p.setPen(QPen(QColor("#050505"), 1.4))
        p.setBrush(QBrush(deg))
        p.drawRect(plaque)

        for sx, sy in ((x + 9, y + 9), (x + w - 9, y + 9),
                       (x + 9, y + h - 9), (x + w - 9, y + h - 9)):
            self._vis(p, sx, sy)

        # La plaque n'est siglée que dans la variante USB. Là c'est justifié :
        # le USB NODE DMX est un boîtier ElectroConcept précis, sans équivalent
        # chez les autres marques, et le reconnaître à sa sérigraphie est
        # exactement ce qu'on demande à l'utilisateur. La variante RJ45, elle,
        # vaut pour des dizaines de nodes (ODE, eDMX, générique…) : un nom de
        # modèle y aurait dit au propriétaire d'un autre boîtier que le dessin
        # ne parlait pas du sien.
        # POWER clignote en vert dès que la fiche est engagée : c'est le retour
        # que l'utilisateur doit aller chercher des yeux sur son propre boîtier
        # pour savoir que le branchement a pris. CPU reste fixe à côté — deux
        # voyants qui clignotent ensemble ne signalent plus rien.
        power = self._clignote(0.35, 7.0) if branche else 0.0
        if self._variant == "usb":
            p.setPen(QColor("#d0d0d0"))
            p.setFont(QFont("Segoe UI", 6, QFont.Bold))
            p.drawText(QRectF(x, y + 9, w, 11), Qt.AlignCenter, "USB NODE DMX")
            self._marque_ce(p, x + 6, y + 22)
            self._led(p, x + 32, y + 44, branche, self._CYAN, "CPU")
            self._led(p, x + w - 32, y + 44, power, self._VERT, "POWER")
            # Prise unique, au centre de la plaque : tout passe par elle.
            self._prise_usb(p, x + 44, y + 72, branche, self._CYAN)
            p.setPen(QColor("#c8c8c8"))
            p.setFont(QFont("Segoe UI", 5, QFont.Bold))
            p.drawText(QRectF(x + 30, y + 83, 56, 9), Qt.AlignCenter, "USB")
            # La marque, sérigraphiée en bas et espacée comme sur le boîtier.
            # Plus petite que le nom du modèle : c'est le modèle qu'on cherche
            # à reconnaître, la marque n'est qu'une mention.
            _marque = QFont("Segoe UI", 3, QFont.Bold)
            _marque.setLetterSpacing(QFont.PercentageSpacing, 130)
            p.setFont(_marque)
            p.setPen(QColor("#8a8a92"))
            p.drawText(QRectF(x, y + h - 16, w, 9), Qt.AlignCenter, "ELECTROCONCEPT")
        else:
            # Les deux prises CÔTE À CÔTE, comme sur la face du vrai boîtier —
            # empilées l'une sur l'autre, elles suggéraient un agencement qui
            # n'existe pas.
            self._marque_ce(p, x + 12, y + 12)
            # Décalé de la vis d'angle : allumé, le halo du voyant mordait
            # dessus.
            self._led(p, x + w - 28, y + 20, power, self._VERT, "")
            p.setPen(QColor("#c8c8c8"))
            p.setFont(QFont("Segoe UI", 5, QFont.Bold))
            p.drawText(QRectF(x + 2, y + 34, 50, 10), Qt.AlignCenter, "ETHERNET")
            p.drawText(QRectF(x + 58, y + 34, 52, 10), Qt.AlignCenter, "USB")
            self._prise_rj45(p, x + 12, y + 60, branche)
            self._prise_usb(p, x + 70, y + 60, branche, self._AMBRE)

    def _vis(self, p, cx, cy):
        """Vis à six pans creux, comme aux coins des plaques ElectroConcept."""
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#3e3e44")))
        p.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
        p.setBrush(QBrush(QColor("#111113")))
        p.drawEllipse(QPointF(cx, cy), 2.0, 2.0)
        p.setPen(QPen(QColor("#5a5a62"), 0.7))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 4.0, 4.0)

    def _marque_ce(self, p, x, y):
        p.setPen(QColor("#9a9a9a"))
        p.setFont(QFont("Segoe UI", 5, QFont.Bold))
        p.drawText(QRectF(x, y, 18, 10), Qt.AlignCenter, "CE")

    def _led(self, p, cx, cy, intensite, teinte, libelle):
        """Voyant de la plaque. `intensite` : 0 éteint, 1 allumé à fond.

        L'appelant décide du régime — fixe ou clignotant — plutôt que le voyant
        d'imposer sa propre pulsation à tout le monde : sur la plaque du USB
        NODE DMX, CPU doit rester fixe pendant que POWER clignote.
        """
        p.setPen(QPen(QColor("#0a0a0a"), 0.8))
        p.setBrush(QBrush(QColor("#0e0e10")))
        p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
        i = max(0.0, min(1.0, float(intensite)))
        # Halo : c'est lui qui fait « s'allumer » plutôt que « changer de
        # couleur », et il rend le clignotement lisible même à 6 px.
        if i > 0.02:
            halo = QColor(teinte)
            halo.setAlphaF(0.30 * i)
            p.setPen(Qt.NoPen); p.setBrush(QBrush(halo))
            p.drawEllipse(QPointF(cx, cy), 3.2 + 2.6 * i, 3.2 + 2.6 * i)
        c = QColor(teinte)
        c.setAlphaF(max(0.10, i))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(cx, cy), 2.4, 2.4)
        if libelle:
            p.setPen(QColor("#8e8e8e"))
            p.setFont(QFont("Segoe UI", 4))
            p.drawText(QRectF(cx - 16, cy + 5, 32, 8), Qt.AlignCenter, libelle)

    # ── prises ────────────────────────────────────────────────

    def _prise_rj45(self, p, x, cy, branche):
        """Embase Ethernet, dessinée comme on la voit sur un boîtier.

        La version précédente était un carré noir avec huit barres jaunes —
        « une prise », sans plus. Ce qui fait reconnaître une RJ45 tient en
        trois choses, et les trois y sont maintenant : le **blindage métal**
        qui encadre l'ouverture, l'**encoche de l'ergot** en bas au centre (le
        cran où vient claquer la languette de la fiche), et les **huit contacts
        dorés suspendus au plafond** de la cavité — pas posés au fond.
        """
        glow = QColor(self._CYAN); glow.setAlphaF(0.16 * branche)
        p.setPen(QPen(glow, 5)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(x - 4, cy - 16, 38, 34), 4, 4)

        # Blindage : cadre métal légèrement bombé.
        cadre = QLinearGradient(0, cy - 14, 0, cy + 15)
        cadre.setColorAt(0.0, QColor("#6e6e78"))
        cadre.setColorAt(0.45, QColor("#4a4a53"))
        cadre.setColorAt(1.0, QColor("#31313a"))
        p.setPen(QPen(QColor("#22222a"), 1.0))
        p.setBrush(QBrush(cadre))
        p.drawRoundedRect(QRectF(x, cy - 14, 30, 29), 2.5, 2.5)

        # Cavité + encoche de l'ergot, d'un seul tenant.
        cav = QPainterPath()
        cav.addRect(QRectF(x + 3.5, cy - 11, 23, 17))
        cav.addRect(QRectF(x + 11, cy + 4, 8, 7))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#08080a")))
        p.drawPath(cav.simplified())

        # Contacts dorés, accrochés en haut et descendant dans l'ouverture.
        p.setBrush(QBrush(QColor("#d8b03c")))
        for i in range(8):
            p.drawRect(QRectF(x + 5.4 + i * 2.6, cy - 10.5, 1.5, 8.5))

        # Filet de lumière sur l'arête haute du blindage.
        p.setPen(QPen(QColor("#9a9aa6"), 0.9)); p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(x + 2, cy - 13), QPointF(x + 28, cy - 13))

    def _prise_usb(self, p, x, cy, branche, teinte):
        """Embase USB-C : ovale très plat, languette centrale."""
        glow = QColor(teinte); glow.setAlphaF(0.16 * branche)
        p.setPen(QPen(glow, 5)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(x - 4, cy - 11, 36, 22), 11, 11)

        p.setPen(QPen(QColor("#3a3a3e"), 1.2))
        p.setBrush(QBrush(QColor("#0c0c0e")))
        p.drawRoundedRect(QRectF(x, cy - 6.5, 28, 13), 6.5, 6.5)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor("#2e2e34")))
        p.drawRoundedRect(QRectF(x + 4, cy - 2.2, 20, 4.4), 2.2, 2.2)

    # ── câbles ────────────────────────────────────────────────

    def _dessiner_cables(self, p, avance, branche):
        """Les câbles glissent du PC vers leur prise, puis y restent."""
        x, y, w, h = self._FACE
        if self._variant == "usb":
            # Dégradé ambre → cyan : un seul câble, les DEUX rôles. C'est
            # l'image que la page doit laisser, et le dégradé la dit sans
            # phrase.
            deg = QLinearGradient(2.0, 0.0, x + 44, 0.0)
            deg.setColorAt(0.0, QColor(self._AMBRE))
            deg.setColorAt(1.0, QColor(self._CYAN))
            self._cable(p, 2, 126, x + 44, y + 72, avance, QBrush(deg))
            self._fiche_usb(p, x + 44, y + 72, branche, self._CYAN)
        else:
            self._cable(p, 2, 44, x + 12, y + 60, avance, QBrush(QColor(self._CYAN)))
            self._fiche_rj45(p, x + 12, y + 60, branche)
            # Le câble d'alimentation part légèrement après : deux traits qui
            # avancent au même instant se lisent comme un seul objet. Il monte
            # par le BAS et démarre à droite de l'embase Ethernet : parti du
            # bord gauche comme l'autre, il lui passait en travers.
            av2 = self._amorti((avance - 0.15) / 0.85)
            self._cable(p, 86, 146, x + 70, y + 60, av2, QBrush(QColor(self._AMBRE)))
            self._fiche_usb(p, x + 70, y + 60, branche, self._AMBRE)

    def _cable(self, p, x0, y0, x1, y1, avance, brosse):
        """Un câble en courbe douce, tracé sur `avance` de sa longueur."""
        avance = max(0.0, min(1.0, avance))
        if avance <= 0.01:
            return
        xa = x0 + (x1 - x0) * avance
        ya = y0 + (y1 - y0) * avance
        chemin = QPainterPath(QPointF(x0, y0))
        chemin.cubicTo(QPointF(x0 + (xa - x0) * 0.55, y0),
                       QPointF(x0 + (xa - x0) * 0.55, ya),
                       QPointF(xa, ya))
        stylo = QPen(brosse, 4.0)
        stylo.setCapStyle(Qt.RoundCap)
        p.setPen(stylo); p.setBrush(Qt.NoBrush)
        p.drawPath(chemin)

    def _fiche_rj45(self, p, x, cy, branche):
        """La fiche engagée dans l'embase : c'est elle qui dit « branché »."""
        if branche <= 0.01:
            return
        # Fiche grise translucide, sa languette VERS LE BAS — elle doit tomber
        # dans l'encoche de l'embase, qui est en bas — et la gaine derrière.
        p.setPen(QPen(QColor("#15151a"), 1.0))
        p.setBrush(QBrush(QColor("#a2a2ac")))
        p.drawRoundedRect(QRectF(x - 2, cy - 12, 28, 24), 2, 2)
        p.setBrush(QBrush(QColor("#8a8a94")))
        p.drawRoundedRect(QRectF(x + 9, cy + 9, 9, 7), 1.5, 1.5)
        p.setBrush(QBrush(QColor("#65656d")))
        p.drawRoundedRect(QRectF(x - 15, cy - 7, 13, 14), 3, 3)

    def _fiche_usb(self, p, x, cy, branche, teinte):
        if branche <= 0.01:
            return
        p.setPen(QPen(QColor("#1a1a1c"), 1.0))
        p.setBrush(QBrush(QColor("#3a3a40")))
        p.drawRoundedRect(QRectF(x - 2, cy - 6, 18, 12), 5, 5)
        p.setBrush(QBrush(QColor(teinte)))
        p.drawRoundedRect(QRectF(x - 14, cy - 5, 13, 10), 3, 3)

    # ── décor ─────────────────────────────────────────────────


class NodeSetupWizard(QDialog):
    """Wizard de configuration réseau pas à pas pour le Node DMX."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("nc_node_config"))
        self.setFixedSize(500, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(
            "QDialog { background: #171717; } "
            "QLabel { color: #e0e0e0; border: none; background: transparent; }"
        )
        self._adapter_name = ""
        self._selected_adapter_name = ""
        self._selected_adapter_ip = ""
        self._adapter_buttons = []
        # Modèle de boîtier déclaré sur la page câbles. Sur un USB NODE DMX la
        # carte réseau est PORTÉE par le boîtier lui-même — ce n'est pas une
        # prise RJ45 qu'il faut chercher dans la liste.
        self._cable_variant = "rj45"
        self._net_came_from_method = False
        self._threads = []
        self._spin_frames = ["◐", "◓", "◑", "◒"]
        self._spin_idx = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._tick)
        self._build_ui()
        QTimer.singleShot(150, self._start_quick_detection)

    # ── helpers ──────────────────────────────────────────────

    def _make_page(self):
        w = QWidget(); w.setStyleSheet("background: #171717;")
        lay = QVBoxLayout(w); lay.setContentsMargins(32, 24, 32, 20); lay.setSpacing(0)
        return w, lay

    def _big_icon(self, text, color="#00d4ff"):
        lbl = QLabel(text); lbl.setFont(QFont("Segoe UI Emoji", 32))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {color}; background: transparent;")
        return lbl

    def _title_lbl(self, text):
        lbl = QLabel(text); lbl.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl.setAlignment(Qt.AlignCenter); lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #f0f0f0; background: transparent;")
        return lbl

    def _sub_lbl(self, text, color="#777777"):
        lbl = QLabel(text); lbl.setFont(QFont("Segoe UI", 10))
        lbl.setAlignment(Qt.AlignCenter); lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color}; background: transparent;")
        return lbl

    def _card(self, icon_char, bold_text, dim_text, accent="#00d4ff"):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: #222222; border: 1px solid #333333; "
            f"border-left: 3px solid {accent}; border-radius: 8px; padding: 12px 14px; }}"
        )
        row = QHBoxLayout(frame); row.setContentsMargins(10, 8, 10, 8); row.setSpacing(10)
        icon = QLabel(icon_char); icon.setFont(QFont("Segoe UI Emoji", 16))
        icon.setStyleSheet("background: transparent; border: none;"); icon.setFixedWidth(28)
        row.addWidget(icon)
        col = QVBoxLayout(); col.setSpacing(2)
        b = QLabel(bold_text); b.setFont(QFont("Segoe UI", 10, QFont.Bold))
        b.setStyleSheet("color: #e0e0e0; background: transparent; border: none;")
        d = QLabel(dim_text); d.setFont(QFont("Segoe UI", 9)); d.setWordWrap(True)
        d.setStyleSheet("color: #777777; background: transparent; border: none;")
        col.addWidget(b); col.addWidget(d); row.addLayout(col, 1)
        return frame

    def _step_indicator(self, active):
        container = QWidget(); container.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(container); outer.setContentsMargins(0,0,0,0); outer.setSpacing(4)
        dots_row = QHBoxLayout(); dots_row.setContentsMargins(0,0,0,0); dots_row.setSpacing(0)
        n = len(_WIZARD_STEPS)
        for i in range(n):
            color = "#4ade80" if i < active else ("#00d4ff" if i == active else "#333333")
            char  = "●" if i <= active else "○"
            dot = QLabel(char); dot.setFont(QFont("Segoe UI", 12))
            dot.setStyleSheet(f"color: {color}; background: transparent;")
            dot.setAlignment(Qt.AlignCenter); dot.setFixedWidth(20)
            dots_row.addWidget(dot)
            if i < n - 1:
                lc = "#4ade80" if i < active else "#2a2a2a"
                line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFixedHeight(2)
                line.setStyleSheet(f"QFrame {{ background: {lc}; border: none; border-top: 2px solid {lc}; }}")
                dots_row.addWidget(line, 1)
        outer.addLayout(dots_row)
        labels_row = QHBoxLayout(); labels_row.setContentsMargins(0,0,0,0); labels_row.setSpacing(0)
        for i, name in enumerate(_WIZARD_STEPS):
            c = "#4ade80" if i < active else ("#00d4ff" if i == active else "#444444")
            lbl = QLabel(name); lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet(f"color: {c}; background: transparent;")
            lbl.setAlignment(Qt.AlignCenter); labels_row.addWidget(lbl, 1)
        outer.addLayout(labels_row)
        return container

    def _primary_btn(self, text, cb):
        btn = QPushButton(text); btn.setStyleSheet(_BTN_PRIMARY)
        btn.setFixedHeight(42); btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.clicked.connect(cb); return btn

    def _secondary_btn(self, text, cb):
        btn = QPushButton(text); btn.setStyleSheet(_BTN_SECONDARY)
        btn.setFixedHeight(36); btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.clicked.connect(cb); return btn

    # ── pages ────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: #171717;")
        root.addWidget(self._stack, 1)

        # Pages
        self._stack.addWidget(self._pg_detecting())
        self._stack.addWidget(self._pg_connected())
        self._stack.addWidget(self._pg_cables())
        self._stack.addWidget(self._pg_adapters())
        self._stack.addWidget(self._pg_ip_method())
        self._stack.addWidget(self._pg_working())
        self._stack.addWidget(self._pg_ip_manual())
        self._stack.addWidget(self._pg_success())

        # Footer
        ftr = QFrame(); ftr.setFixedHeight(64)
        ftr.setStyleSheet("QFrame { background: #111111; border-top: 1px solid #222222; }")
        fl = QHBoxLayout(ftr); fl.setContentsMargins(24, 0, 24, 0); fl.setSpacing(10)
        self._btn_back = QPushButton(tr("nc_back")); self._btn_back.setFixedHeight(36)
        self._btn_back.setStyleSheet(_BTN_GHOST)
        self._btn_back.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_back.clicked.connect(self._on_back); self._btn_back.hide()
        fl.addWidget(self._btn_back); fl.addStretch()
        close_btn = QPushButton(tr("nc_close")); close_btn.setFixedHeight(36)
        close_btn.setStyleSheet(_BTN_GHOST)
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        close_btn.clicked.connect(self.accept)
        fl.addWidget(close_btn)
        root.addWidget(ftr)

    def _pg_detecting(self):
        w, lay = self._make_page(); lay.addStretch()
        self._spin_lbl = QLabel("◐"); self._spin_lbl.setFont(QFont("Segoe UI", 48))
        self._spin_lbl.setStyleSheet("color: #00d4ff; background: transparent;")
        self._spin_lbl.setAlignment(Qt.AlignCenter); lay.addWidget(self._spin_lbl)
        lay.addSpacing(12); lay.addWidget(self._sub_lbl("Recherche du boîtier DMX..."))
        lay.addStretch(); return w

    def _pg_connected(self):
        w, lay = self._make_page(); lay.addStretch()
        lay.addWidget(self._big_icon("✅", "#4ade80")); lay.addSpacing(12)
        lay.addWidget(self._title_lbl("Boîtier connecté !")); lay.addSpacing(8)
        self._connected_ip_lbl = self._sub_lbl(f"Adresse IP : {TARGET_IP}")
        lay.addWidget(self._connected_ip_lbl); lay.addSpacing(24)
        lay.addWidget(self._primary_btn("Super, fermer  ✓", self.accept))
        lay.addSpacing(8)
        lay.addWidget(self._secondary_btn("↺  Relancer depuis le début", self._restart_wizard))
        lay.addStretch(); return w

    def _pg_cables(self):
        """Branchement — le boîtier d'abord, les câbles ensuite.

        L'ancienne page réclamait toujours « les 2 connexions » : un RJ45 pour
        les données, un USB pour l'alimentation. Le USB NODE DMX n'a qu'une
        prise USB-C, qui porte le courant ET l'Art-Net : son propriétaire
        cherchait un câble réseau absent de son boîtier, à la première étape de
        l'assistant. On demande donc d'abord ce qu'on voit sur la face — la
        seule question à laquelle on peut répondre sans rien connaître — et
        l'animation et le bouton suivent.
        """
        w, lay = self._make_page()
        lay.addWidget(self._title_lbl("Branchons le boîtier"))
        lay.addSpacing(14)

        # Choix du modèle
        choix = QWidget(); choix.setStyleSheet("background: transparent;")
        crow = QHBoxLayout(choix); crow.setContentsMargins(0, 0, 0, 0); crow.setSpacing(8)
        self._cable_btns = {}
        # Hauteur MESURÉE, pas devinée : les trois lignes plus la marge de la
        # feuille de style ne tenaient pas dans les 58 px codés en dur et le bas
        # du libellé était rogné.
        _police = QFont("Segoe UI", 8)
        _fm = QFontMetrics(_police)
        _haut = 0
        for cle, titre in (("rj45", "Une prise réseau\n+ une prise USB"),
                           ("usb",  "Une seule\nprise USB")):
            _haut = max(_haut, _fm.boundingRect(
                QRect(0, 0, 190, 400), Qt.TextWordWrap | Qt.AlignCenter, titre).height())
        _haut += 22   # les 6 px de padding haut et bas, plus une marge de sûreté

        for cle, titre in (
            ("rj45", "Une prise réseau\n+ une prise USB"),
            ("usb",  "Une seule\nprise USB"),
        ):
            b = QPushButton(titre)
            b.setCheckable(True); b.setFixedHeight(_haut)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setFont(_police)
            b.clicked.connect(lambda _c=False, k=cle: self._set_cable_variant(k))
            self._cable_btns[cle] = b
            crow.addWidget(b, 1)
        lay.addWidget(choix)
        # Le dessin est à sa taille maximale (il occupe déjà toute la largeur
        # utile) : le vide restant se répartit au-dessus ET au-dessous, sinon
        # il s'accumule en bas et le bloc semble collé en haut.
        lay.addStretch()

        # Plus de légende sous le dessin : les étiquettes ETHERNET et USB sont
        # sur la plaque, à côté de leur prise. Les redire en dessous en trois
        # lignes de texte n'apprenait rien de plus et noyait l'image.
        self._cables_anim = NodeWiringAnim("rj45")
        lay.addWidget(self._cables_anim)

        lay.addStretch()
        lay.addWidget(self._step_indicator(0)); lay.addSpacing(12)
        self._btn_cables_next = self._primary_btn("C'est branché  →", self._start_adapter_scan)
        lay.addWidget(self._btn_cables_next)
        self._set_cable_variant("rj45")
        return w

    def _set_cable_variant(self, cle):
        """Applique le modèle choisi à l'animation et au bouton."""
        self._cable_variant = cle
        for k, b in self._cable_btns.items():
            actif = (k == cle)
            b.setChecked(actif)
            b.setStyleSheet(
                "QPushButton { background: %s; color: %s; border: 1px solid %s; "
                "border-radius: 8px; padding: 6px; text-align: center; }"
                % (("#0d2a33", "#e0e0e0", "#00d4ff") if actif
                   else ("#1e1e1e", "#8a8a8a", "#2e2e2e"))
            )
        self._cables_anim.set_variant(cle)
        self._btn_cables_next.setText("Le câble USB est branché  →" if cle == "usb"
                                      else "Les 2 câbles sont branchés  →")

    def _pg_adapters(self):
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("🌐")); lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Quelle carte réseau ?")); lay.addSpacing(4)
        # Le libellé dépend du boîtier : sur un USB NODE DMX, la carte à choisir
        # n'est reliée à rien — c'est le boîtier lui-même, qui se présente à
        # Windows comme une carte réseau (« Electroconcept USB Node »).
        self._adapters_hint = self._sub_lbl(
            "Choisissez la carte réseau reliée au boîtier\n(pas la Wi-Fi)")
        lay.addWidget(self._adapters_hint)
        lay.addSpacing(12)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { background: #1e1e1e; width: 6px; border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 3px; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(); inner.setStyleSheet("background: transparent;")
        self._adapters_layout = QVBoxLayout(inner)
        self._adapters_layout.setSpacing(6); self._adapters_layout.setContentsMargins(0,0,0,0)
        self._adapters_layout.addStretch()
        scroll.setWidget(inner); lay.addWidget(scroll, 1)
        lay.addSpacing(12); lay.addWidget(self._step_indicator(1)); lay.addSpacing(12)
        self._btn_net_suivant = QPushButton(tr("nc_continue"))
        self._btn_net_suivant.setStyleSheet(_BTN_PRIMARY); self._btn_net_suivant.setFixedHeight(42)
        self._btn_net_suivant.setEnabled(False)
        self._btn_net_suivant.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_net_suivant.clicked.connect(self._on_net_suivant)
        lay.addWidget(self._btn_net_suivant); return w

    def _pg_ip_method(self):
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("⚙️")); lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Configuration IP")); lay.addSpacing(12)
        info = QFrame(); info.setStyleSheet(
            "QFrame { background: #222222; border: 1px solid #333333; border-radius: 8px; }")
        il = QVBoxLayout(info); il.setContentsMargins(16,12,16,12); il.setSpacing(4)
        self._ip_method_adapter_lbl = QLabel()
        self._ip_method_adapter_lbl.setFont(QFont("Segoe UI", 10))
        self._ip_method_adapter_lbl.setStyleSheet("color: #666666; background: transparent; border: none;")
        self._ip_method_adapter_lbl.setAlignment(Qt.AlignCenter)
        il.addWidget(self._ip_method_adapter_lbl)
        ip_t = QLabel("IP cible :  2.0.0.1  /  255.0.0.0")
        ip_t.setFont(QFont("Segoe UI", 11, QFont.Bold))
        ip_t.setStyleSheet("color: #00d4ff; background: transparent; border: none;")
        ip_t.setAlignment(Qt.AlignCenter); il.addWidget(ip_t)
        lay.addWidget(info); lay.addSpacing(10)
        note = QLabel(tr("nc_admin_required"))
        note.setFont(QFont("Segoe UI", 9)); note.setWordWrap(True)
        note.setStyleSheet("color: #444444; background: transparent;")
        note.setAlignment(Qt.AlignCenter); lay.addWidget(note)
        lay.addSpacing(16); lay.addWidget(self._step_indicator(2)); lay.addSpacing(14)
        lay.addWidget(self._primary_btn("Configurer automatiquement  ✓", self._do_auto_config))
        lay.addSpacing(8)
        lay.addWidget(self._secondary_btn("Je configure moi-même", self._show_manual_from_method))
        return w

    def _pg_working(self):
        w, lay = self._make_page(); lay.addStretch()
        self._work_spin_lbl = QLabel("◐"); self._work_spin_lbl.setFont(QFont("Segoe UI", 48))
        self._work_spin_lbl.setStyleSheet("color: #00d4ff; background: transparent;")
        self._work_spin_lbl.setAlignment(Qt.AlignCenter); lay.addWidget(self._work_spin_lbl)
        lay.addSpacing(12)
        self._work_status_lbl = QLabel("")
        self._work_status_lbl.setFont(QFont("Segoe UI", 11))
        self._work_status_lbl.setStyleSheet("color: #888888; background: transparent;")
        self._work_status_lbl.setWordWrap(True); self._work_status_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._work_status_lbl); lay.addSpacing(6)
        self._work_detail_lbl = QLabel("")
        self._work_detail_lbl.setFont(QFont("Segoe UI", 9))
        self._work_detail_lbl.setStyleSheet("color: #444444; background: transparent;")
        self._work_detail_lbl.setAlignment(Qt.AlignCenter); lay.addWidget(self._work_detail_lbl)
        lay.addStretch(); return w

    def _pg_ip_manual(self):
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("📋")); lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Configuration manuelle")); lay.addSpacing(6)
        self._manual_ctx_lbl = self._sub_lbl(""); lay.addWidget(self._manual_ctx_lbl)
        lay.addSpacing(12)
        sf = QFrame(); sf.setStyleSheet(
            "QFrame { background: #222222; border: 1px solid #333333; border-radius: 8px; padding: 14px; }")
        sl = QVBoxLayout(sf); sl.setContentsMargins(14,10,14,10)
        self._manual_steps_lbl = QLabel()
        self._manual_steps_lbl.setFont(QFont("Segoe UI", 10))
        self._manual_steps_lbl.setStyleSheet("color: #cccccc; background: transparent; border: none;")
        self._manual_steps_lbl.setWordWrap(True); sl.addWidget(self._manual_steps_lbl)
        lay.addWidget(sf); lay.addSpacing(8)
        lay.addWidget(self._secondary_btn("📂  Ouvrir les connexions réseau", _open_network_connections))
        lay.addSpacing(4)
        lay.addWidget(self._secondary_btn("🔑  Relancer en administrateur", self._restart_as_admin))
        lay.addSpacing(12); lay.addWidget(self._step_indicator(2)); lay.addSpacing(12)
        lay.addWidget(self._primary_btn("J'ai configuré  →  Tester la connexion", self._start_final_search))
        return w

    def _pg_success(self):
        w, lay = self._make_page(); lay.addStretch()
        lay.addWidget(self._big_icon("🎉", "#4ade80")); lay.addSpacing(12)
        lay.addWidget(self._title_lbl("Connexion établie !")); lay.addSpacing(8)
        lay.addWidget(self._sub_lbl("Votre boîtier est prêt à recevoir les données DMX."))
        lay.addSpacing(20); lay.addWidget(self._step_indicator(3)); lay.addSpacing(20)
        lay.addWidget(self._primary_btn("Super, fermer  ✓", self.accept))
        lay.addStretch(); return w

    # ── navigation ───────────────────────────────────────────

    def _go_to(self, page):
        self._stack.setCurrentIndex(page)
        self._btn_back.setVisible(page in {P_W_ADAPTERS, P_W_IP_METHOD, P_W_IP_MANUAL})

    def _on_back(self):
        p = self._stack.currentIndex()
        if p == P_W_ADAPTERS:   self._go_to(P_W_CABLES)
        elif p == P_W_IP_METHOD: self._go_to(P_W_ADAPTERS)
        elif p == P_W_IP_MANUAL: self._go_to(P_W_IP_METHOD if self._net_came_from_method else P_W_ADAPTERS)

    def _restart_wizard(self):
        self._adapter_name = ""
        self._selected_adapter_name = ""
        self._selected_adapter_ip = ""
        self._net_came_from_method = False
        self._stop_spinner()
        self._go_to(P_W_CABLES)

    # ── spinner ──────────────────────────────────────────────

    def _tick(self):
        self._spin_idx = (self._spin_idx + 1) % len(self._spin_frames)
        f = self._spin_frames[self._spin_idx]
        p = self._stack.currentIndex()
        if p == P_W_DETECTING: self._spin_lbl.setText(f)
        elif p == P_W_WORKING: self._work_spin_lbl.setText(f)

    def _set_working(self, status, detail=""):
        self._work_status_lbl.setText(status); self._work_detail_lbl.setText(detail)
        self._go_to(P_W_WORKING); self._spin_timer.start(180)

    def _stop_spinner(self): self._spin_timer.stop()

    # ── quick detection ──────────────────────────────────────

    def _start_quick_detection(self):
        self._go_to(P_W_DETECTING); self._spin_timer.start(180)
        t = _QuickDetector(); t.finished.connect(self._on_quick_done)
        self._threads.append(t); t.start()

    def _on_quick_done(self, found):
        self._stop_spinner()
        if found: self._go_to(P_W_CONNECTED)
        else:     self._go_to(P_W_CABLES)

    # ── adapter scan ─────────────────────────────────────────

    def _start_adapter_scan(self):
        if getattr(self, "_adapters_hint", None) is not None:
            # Sur un USB NODE DMX le boîtier EST la carte : Windows le nomme
            # selon le pilote qui le prend en charge — « Electroconcept USB
            # Node » ou « UsbNcm Host Device » selon la source. On ne promet
            # donc pas un nom exact, on dit où regarder.
            self._adapters_hint.setText(
                "Le boîtier EST la carte réseau : prenez celle\n"
                "qui apparaît quand vous le branchez"
                if self._cable_variant == "usb"
                else "Choisissez la carte réseau reliée au boîtier\n(pas la Wi-Fi)")
        self._set_working("Scan des cartes réseau...", "Recherche des adaptateurs Ethernet")
        t = _AdapterScanner(); t.done.connect(self._on_adapters_scanned)
        self._threads.append(t); t.start()

    def _on_adapters_scanned(self, adapters):
        while self._adapters_layout.count() > 1:
            item = self._adapters_layout.takeAt(0)
            if item.widget(): item.widget().setParent(None)
        self._adapter_buttons.clear()
        self._selected_adapter_name = ""
        self._selected_adapter_ip = ""
        self._btn_net_suivant.setEnabled(False)

        if not adapters:
            lbl = QLabel(tr("nc_no_ethernet"))
            lbl.setStyleSheet("color: #fbbf24; background: #2a2000; border: 1px solid #554400; "
                "border-radius: 6px; padding: 12px;")
            lbl.setWordWrap(True); lbl.setAlignment(Qt.AlignCenter)
            self._adapters_layout.insertWidget(0, lbl)
            btn_scan_again = QPushButton(tr("nc_refresh"))
            btn_scan_again.setFixedHeight(34)
            btn_scan_again.setCursor(Qt.PointingHandCursor)
            btn_scan_again.setStyleSheet(
                "QPushButton { background: #1a2a1a; color: #66cc66; border: 1px solid #336633;"
                " border-radius: 6px; padding: 0 20px; font-size: 11px; }"
                "QPushButton:hover { background: #223322; color: #88ee88; border-color: #448844; }"
            )
            btn_scan_again.clicked.connect(self._start_adapter_scan)
            self._adapters_layout.insertWidget(1, btn_scan_again)
        else:
            # Auto-sélection : déjà ok > câble branché > premier
            recommended = next((name for name, ip, d, c in adapters if ip.startswith("2.0.0.")), None)
            if not recommended:
                recommended = next((name for name, ip, d, c in adapters if c and ip), None)
            if not recommended and adapters:
                recommended = adapters[0][0]

            for i, (name, ip, desc, connected) in enumerate(adapters):
                already_ok = ip.startswith("2.0.0.")
                if already_ok:
                    state = "✓  IP Art-Net déjà configurée"
                elif connected and ip:
                    state = f"🔌 Câble branché  —  IP : {ip}"
                elif connected:
                    state = "🔌 Câble branché  —  IP non configurée"
                else:
                    state = "⚠  Câble débranché"
                desc_line = f"\n  {desc}" if desc and desc.lower() != name.lower() else ""
                txt = f"  {name}{desc_line}\n  {state}"
                style = _BTN_ADAPTER_OK if already_ok else _BTN_ADAPTER
                btn = QPushButton(txt)
                btn.setStyleSheet(style)
                btn.setFixedHeight(68 if desc_line else 58)
                btn.setCursor(QCursor(Qt.PointingHandCursor))
                btn.clicked.connect(lambda _, n=name, curr_ip=ip: self._select_adapter(n, curr_ip))
                self._adapters_layout.insertWidget(i, btn)
                self._adapter_buttons.append((btn, name, ip))

            # Auto-sélection si une seule carte ou si une seule est ok
            ok_adapters = [(n, ip) for n, ip, d, c in adapters if ip.startswith("2.0.0.")]
            if len(adapters) == 1 or ok_adapters:
                auto_name = ok_adapters[0][0] if ok_adapters else adapters[0][0]
                auto_ip   = ok_adapters[0][1] if ok_adapters else adapters[0][1]
                self._select_adapter(auto_name, auto_ip)
            elif recommended:
                rec_ip = next((ip for n, ip, d, c in adapters if n == recommended), "")
                self._select_adapter(recommended, rec_ip)

        self._stop_spinner(); self._go_to(P_W_ADAPTERS)

    def _select_adapter(self, name, ip):
        self._selected_adapter_name = name; self._selected_adapter_ip = ip
        for btn, n, _ in self._adapter_buttons:
            already_ok = n == name and ip.startswith("2.0.0.")
            btn.setStyleSheet(_BTN_ADAPTER_SEL if n == name else
                              (_BTN_ADAPTER_OK if any(i.startswith("2.0.0.") and nm == n
                                                      for btn2, nm, i in self._adapter_buttons) else _BTN_ADAPTER))
        self._btn_net_suivant.setEnabled(True)

    def _on_net_suivant(self):
        self._on_adapter_selected(self._selected_adapter_name, self._selected_adapter_ip)

    def _on_adapter_selected(self, adapter_name, current_ip):
        self._adapter_name = adapter_name
        if current_ip.startswith("2.0.0."):
            self._set_working("IP déjà configurée ✓", f"Recherche du boîtier sur {TARGET_IP}...")
            self._start_final_search()
        else:
            ip_display = current_ip if current_ip else "non configurée"
            self._ip_method_adapter_lbl.setText(
                tr("nc_f_adapter", adapter_name=adapter_name, ip_display=ip_display))
            self._net_came_from_method = False
            self._go_to(P_W_IP_METHOD)

    # ── auto config ──────────────────────────────────────────

    def _do_auto_config(self):
        self._set_working("Configuration en cours...",
            f"Application de 2.0.0.1 sur « {self._adapter_name} »...")
        t = _NetworkSetup(self._adapter_name); t.done.connect(self._on_network_done)
        self._threads.append(t); t.start()

    def _on_network_done(self, status, adapter):
        self._adapter_name = adapter
        if status == "ok":
            self._start_final_search(); return
        self._stop_spinner()
        self._net_came_from_method = True
        self._show_net_manual(adapter, status)

    def _show_manual_from_method(self):
        self._net_came_from_method = True
        self._show_net_manual(self._adapter_name, "manual")

    def _show_net_manual(self, adapter, status="manual"):
        label = f"« {adapter} »" if adapter else "votre carte Ethernet"
        ctx = (f"Droits insuffisants sur {label}.\nConfigurez manuellement ou relancez en administrateur."
               if status == "manual" else f"Carte : {label}")
        self._manual_ctx_lbl.setText(ctx)
        self._manual_steps_lbl.setText(
            tr("nc_f_ip_steps", label=label)
        )
        self._go_to(P_W_IP_MANUAL)

    # ── node search ──────────────────────────────────────────

    def _start_final_search(self):
        self._set_working("Recherche du boîtier DMX...", f"Envoi ArtPoll sur {TARGET_IP}...")
        t = _NodeSearcher(); t.finished.connect(self._on_search_done)
        self._threads.append(t); t.start()

    def _on_search_done(self, found):
        self._stop_spinner()
        if found:
            self._go_to(P_W_SUCCESS)
        else:
            label = f"« {self._adapter_name} »" if self._adapter_name else "votre carte Ethernet"
            self._manual_ctx_lbl.setText(
                tr("nc_f_no_answer", TARGET_IP=TARGET_IP))
            self._manual_steps_lbl.setText(
                tr("nc_f_ip_steps", label=label)
            )
            self._net_came_from_method = True
            self._go_to(P_W_IP_MANUAL)

    # ── admin restart ────────────────────────────────────────

    def _restart_as_admin(self):
        import sys, ctypes
        try:
            exe = sys.executable
            extra = f' "--node-config-ip" "{self._adapter_name}"' if self._adapter_name else ""
            args = " ".join(f'"{a}"' for a in sys.argv) + extra
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
        except Exception:
            pass

    def jump_to_ip_manual(self, adapter_name: str):
        """Navigue directement à la page de configuration manuelle pour un adaptateur donné.
        Utilisé après un redémarrage en mode administrateur."""
        self._adapter_name = adapter_name
        self._net_came_from_method = True
        self._show_net_manual(adapter_name, "manual")

    def closeEvent(self, event):
        self._spin_timer.stop()
        for t in self._threads:
            if t.isRunning(): t.quit(); t.wait(300)
        super().closeEvent(event)


# ============================================================
# DIALOG UNIFIÉ — Paramétrer la sortie DMX
# ============================================================

from PySide6.QtCore import Signal as _Signal

try:
    from artnet_dmx import (
        TRANSPORT_ARTNET, TRANSPORT_ENTTEC, TRANSPORT_ENTTEC_PRO,
        TRANSPORT_ENTTEC_D2XX, OUTPUT_OFF, OUTPUT_INPUT,
    )
except ImportError:
    TRANSPORT_ARTNET    = "artnet"
    TRANSPORT_ENTTEC    = "enttec"
    TRANSPORT_ENTTEC_PRO = "enttec_pro"
    TRANSPORT_ENTTEC_D2XX = "enttec_d2xx"
    OUTPUT_OFF = -1
    OUTPUT_INPUT = -2

_SS_DIALOG = """
    QDialog  { background: #131313; }
    QLabel   { color: #e0e0e0; background: transparent; }
    QLineEdit {
        background: #1e1e1e; color: #e0e0e0;
        border: 1px solid #333; border-radius: 6px;
        padding: 6px 10px; font-size: 12px;
    }
    QLineEdit:focus { border-color: #00d4ff; }
    QComboBox {
        background: #1e1e1e; color: #e0e0e0;
        border: 1px solid #333; border-radius: 6px;
        padding: 6px 10px; font-size: 12px;
    }
    QComboBox::drop-down { border: none; width: 20px; }
    QComboBox QAbstractItemView {
        background: #1e1e1e; color: #e0e0e0;
        selection-background-color: #00d4ff;
        selection-color: #000;
    }
"""

_BTN_NET_TODO = (
    "QPushButton { background: #2a2413; color: #e6a817; border: 1px solid #5a4820; "
    "border-radius: 6px; font-size: 11px; font-weight: bold; } "
    "QPushButton:hover { background: #3a3018; color: #ffc94a; }"
)


_BTN_TOGGLE_ON = (
    "QPushButton { background: #00d4ff; color: #000; font-weight: 700; "
    "border: none; border-radius: 8px; font-size: 12px; padding: 0 20px; }"
)
_BTN_TOGGLE_OFF = (
    "QPushButton { background: #1e1e1e; color: #555; border: 1px solid #2a2a2a; "
    "border-radius: 8px; font-size: 12px; padding: 0 20px; } "
    "QPushButton:hover { background: #252525; color: #999; border-color: #333; }"
)
_BTN_APPLY = (
    "QPushButton { background: #00d4ff; color: #000; font-weight: 700; "
    "border: none; border-radius: 6px; padding: 0 20px; } "
    "QPushButton:hover { background: #22ddff; } "
    "QPushButton:disabled { background: #1a3a3a; color: #2a6a6a; }"
)
_BTN_CANCEL = (
    "QPushButton { background: #1e1e1e; color: #888; border: 1px solid #2a2a2a; "
    "border-radius: 6px; padding: 0 16px; } "
    "QPushButton:hover { background: #252525; color: #ccc; }"
)
_BTN_DIAG = (
    "QPushButton { background: #1a1a1a; color: #00d4ff; border: 1px solid #00d4ff44; "
    "border-radius: 6px; padding: 0 16px; font-size: 11px; } "
    "QPushButton:hover { background: #1a2a2a; border-color: #00d4ff99; }"
)
_BTN_TEST = (
    "QPushButton { background: #1a1a1a; color: #aaa; border: 1px solid #333; "
    "border-radius: 6px; padding: 0 14px; font-size: 10px; } "
    "QPushButton:hover { color: #fff; border-color: #555; }"
)


class DmxOutputDialog(QDialog):
    """Dialogue unifié pour basculer entre Sortie Node (Art-Net) et Sortie DMX USB (ENTTEC)."""

    transport_changed = _Signal(str)   # "artnet" | "enttec"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_win = parent
        self.setWindowTitle(tr("nc_setup_dmx_out"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(_SS_DIALOG)

        dmx = getattr(parent, 'dmx', None)
        self._dmx = dmx
        self._transport = self._initial_transport(dmx)

        self._build_ui()
        self._refresh_ports()
        self._set_transport(self._transport, save=False)
        self._fit_to_content()

    def _fit_to_content(self):
        """Ouvre la fenêtre à la hauteur réellement demandée par la page.

        Largeur figée (520), hauteur calculée : hauteur de tout ce qui entoure
        la zone défilante + hauteur souhaitée par la plus grande des pages,
        plafonnée à l'écran. Sans ça, la page Node dépassait la taille fixe et
        la carte « Aiguillage des sorties » se retrouvait rognée.
        """
        besoin = (self.layout().minimumSize().height()
                  - self._scroll.minimumHeight()
                  + self._stack.sizeHint().height())
        ecran = self.screen() or QApplication.primaryScreen()
        dispo = int(ecran.availableGeometry().height() * 0.92) if ecran else 800
        self.setFixedWidth(520)
        self.setMinimumHeight(min(430, besoin))
        self.setMaximumHeight(besoin)
        self.resize(520, min(besoin, dispo))

    def _usb_port_available(self, dmx):
        """Un port série exploitable est-il réellement présent ?"""
        try:
            import serial.tools.list_ports as _lp
            devices = [p.device for p in _lp.comports()]
        except Exception:
            return False
        if not devices:
            return False
        com = getattr(dmx, 'com_port', None)
        # Port mémorisé toujours là → on peut rester en USB. Aucun port mémorisé
        # mais des ports disponibles → l'utilisateur en choisira un.
        return (com in devices) if com else True

    def _initial_transport(self, dmx):
        """Onglet affiché à l'ouverture du dialogue.

        On suivait aveuglément le champ `transport` de ~/.mystrow_dmx.json. Or
        ce champ est écrit par tout `connect()`, y compris ceux des scripts de
        diagnostic : une seule session de test USB, et le dialogue s'ouvrait
        pour toujours sur « Sortie DMX USB » — même boîtier débranché, même sur
        une installation Art-Net. Même effet si l'utilisateur range son boîtier
        USB après l'avoir utilisé une fois.

        On montre donc ce qui fonctionne réellement, et on retombe sur le Node
        (le cas le plus courant) dès qu'il y a le moindre doute.
        """
        if dmx is None:
            return TRANSPORT_ARTNET
        transport = getattr(dmx, 'transport', TRANSPORT_ARTNET)
        if transport == TRANSPORT_ARTNET:
            return TRANSPORT_ARTNET
        # Sortie USB réellement ouverte : c'est bien celle-là qu'il faut montrer.
        if getattr(dmx, 'connected', False):
            return transport
        return transport if self._usb_port_available(dmx) else TRANSPORT_ARTNET

    # ── Construction UI ────────────────────────────────────────────────

    def _build_ui(self):
        content = QVBoxLayout(self)
        content.setContentsMargins(28, 24, 28, 20)
        content.setSpacing(16)

        # Titre
        title = QLabel(tr("nc_setup_dmx_out"))
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet("color: #f0f0f0;")
        content.addWidget(title)

        # Toggle Node / USB
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(8)

        self._btn_node = QPushButton(tr("nc_tab_node"))
        self._btn_node.setFixedHeight(40)
        self._btn_node.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_node.clicked.connect(lambda: self._set_transport(TRANSPORT_ARTNET))
        toggle_row.addWidget(self._btn_node)

        self._btn_usb = QPushButton(tr("nc_tab_usb"))
        self._btn_usb.setFixedHeight(40)
        self._btn_usb.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_usb.clicked.connect(lambda: self._set_transport(TRANSPORT_ENTTEC))
        toggle_row.addWidget(self._btn_usb)
        content.addLayout(toggle_row)


        # Bandeau guide — en haut de la fenêtre, façon bibliothèque de fixtures.
        # En pied de fenêtre il passait sous la barre de tâches sur certaines
        # configs et personne ne le voyait.
        hint = QLabel(
            tr("nc_help_link")
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setOpenExternalLinks(True)
        hint.setStyleSheet(
            "color:#888; font-size:11px; background:#161f16; border:1px solid #2a3a2a;"
            " border-radius:5px; padding:5px 10px;"
        )
        content.addWidget(hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { border: none; border-top: 1px solid #222; }")
        content.addWidget(sep)

        # Pages — dans une zone défilante. La fenêtre était figée à 490 px de
        # haut alors que la page Node en réclame ~660 avec l'aiguillage des
        # sorties : Qt écrasait la carte et la tronquait en plein milieu des
        # combos. Ici la fenêtre s'ouvre à la bonne hauteur, et si l'écran est
        # trop petit on scrolle au lieu de couper.
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_node())
        self._stack.addWidget(self._page_usb())

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setMinimumHeight(180)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { background: #1e1e1e; width: 6px; border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        # Sans ça le viewport du QScrollArea se peint en clair (palette par
        # défaut) et découpe un rectangle blanc au milieu du dialogue sombre.
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._stack.setStyleSheet("background: transparent;")
        self._scroll.setWidget(self._stack)
        content.addWidget(self._scroll, 1)

        # Boutons bas
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #555; font-size: 10px;")
        btn_row.addWidget(self._status_lbl, 1)

        btn_cancel = QPushButton(tr("nc_close"))
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.clicked.connect(self.accept)
        btn_row.addWidget(btn_cancel)

        self._btn_apply = QPushButton(tr("nc_connect"))
        self._btn_apply.setFixedHeight(36)
        self._btn_apply.setStyleSheet(_BTN_APPLY)
        self._btn_apply.clicked.connect(self._apply)
        btn_row.addWidget(self._btn_apply)
        content.addLayout(btn_row)


    def _page_node(self):
        """Page Art-Net : statut de connexion (lecture seule) + bouton de configuration."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #1a1a1a; border: 1px solid #252525; border-radius: 10px; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(18, 16, 18, 16)
        card_lay.setSpacing(10)

        # Statut connexion
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self._node_status_dot = QLabel("◌")
        self._node_status_dot.setStyleSheet(
            "color: #555; font-size: 20px; background: transparent; border: none;")
        status_row.addWidget(self._node_status_dot)
        self._node_status_lbl = QLabel(tr("nc_checking_ell"))
        self._node_status_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self._node_status_lbl.setStyleSheet("color: #aaa; background: transparent; border: none;")
        status_row.addWidget(self._node_status_lbl, 1)
        card_lay.addLayout(status_row)

        def _sep():
            s = QFrame(); s.setFrameShape(QFrame.HLine)
            s.setStyleSheet("QFrame { border: none; border-top: 1px solid #252525; }")
            return s

        card_lay.addWidget(_sep())

        # Carte réseau (lecture seule)
        net_row = QHBoxLayout()
        net_key = QLabel(tr("nc_network_card"))
        net_key.setFont(QFont("Segoe UI", 9))
        net_key.setStyleSheet("color: #666; background: transparent; border: none;")
        net_row.addWidget(net_key)
        net_row.addStretch()
        self._node_net_lbl = QLabel(tr("nc_detecting"))
        self._node_net_lbl.setFont(QFont("Segoe UI", 9))
        self._node_net_lbl.setStyleSheet("color: #888; background: transparent; border: none;")
        self._node_net_lbl.setAlignment(Qt.AlignRight)
        net_row.addWidget(self._node_net_lbl)
        card_lay.addLayout(net_row)

        # Le bouton qui regle le probleme est place LA, juste sous le statut
        # reseau, plutot qu'une consigne texte renvoyant vers un bouton en bas
        # de page. Il reste visible en permanence — reconfigurer le reseau est
        # utile meme quand tout va bien — et passe en orange quand la carte
        # n'est pas en 2.x (voir _set_net_hint).
        cfg_btn = QPushButton(tr("nc_config_net_conn"))
        self._node_cfg_btn = cfg_btn
        cfg_btn.setFixedHeight(32)
        cfg_btn.setStyleSheet(_BTN_DIAG)
        cfg_btn.setCursor(QCursor(Qt.PointingHandCursor))
        cfg_btn.clicked.connect(self._open_node_wizard)
        card_lay.addWidget(cfg_btn)

        # Aiguillage des 4 sorties du Node.
        # Remplace l'ancien sélecteur « DMX 2 / Miroir », qui n'avait AUCUN effet :
        # `mirror_output` était sauvegardé mais jamais lu par `_send_artnet`.
        # Ici, mettre deux sorties sur le même univers reproduit le miroir, et
        # permet en plus n'importe quelle autre combinaison.
        self._out_combos = []
        if self._dmx is not None:
            card_lay.addWidget(_sep())

            titre = QLabel(tr("nc_output_routing"))
            titre.setFont(QFont("Segoe UI", 9, QFont.Bold))
            titre.setStyleSheet("color: #888; background: transparent; border: none;")
            card_lay.addWidget(titre)

            aide = QLabel(tr("nc_routing_hint"))
            aide.setStyleSheet("color: #555; font-size: 9px; background: transparent; border: none;")
            aide.setWordWrap(True)
            card_lay.addWidget(aide)

            grille = QGridLayout()
            grille.setContentsMargins(0, 6, 0, 0)
            grille.setHorizontalSpacing(10)
            grille.setVerticalSpacing(6)

            for n in range(4):
                sortie = QLabel(f"DMX {n + 1}")
                sortie.setFont(QFont("Segoe UI", 9))
                sortie.setStyleSheet("color: #999; background: transparent; border: none;")
                grille.addWidget(sortie, n, 0)

                fleche = QLabel("←")
                fleche.setStyleSheet("color: #444; background: transparent; border: none;")
                grille.addWidget(fleche, n, 1)

                combo = ComboSansMolette()
                for u in range(4):
                    combo.addItem(tr("nc_f_universe", a0=u + 1), userData=u)
                combo.addItem(tr("nc_disabled"), userData=OUTPUT_OFF)
                # Port bascule en ENTREE : MyStrow se TAIT dessus, au lieu
                # d'y emettre des zeros comme pour une sortie desactivee.
                combo.addItem(tr("nc_out_input"), userData=OUTPUT_INPUT)
                courant = (self._dmx.output_map[n]
                           if n < len(getattr(self._dmx, 'output_map', [])) else n)
                combo.setCurrentIndex({OUTPUT_OFF: 4, OUTPUT_INPUT: 5}.get(
                    courant, max(0, min(3, courant))))
                combo.setFont(QFont("Segoe UI", 9))
                combo.setStyleSheet(
                    "QComboBox { background:#2a2a2a; color:white; border:1px solid #3a3a3a;"
                    " border-radius:4px; padding:3px 8px; }"
                    "QComboBox::drop-down { border: none; }"
                    "QComboBox QAbstractItemView { background:#2a2a2a; color:white; }")
                combo.currentIndexChanged.connect(self._refresh_out_hint)
                grille.addWidget(combo, n, 2)

                art = QLabel("")
                art.setStyleSheet("color: #444; font-size: 9px; background: transparent; border: none;")
                grille.addWidget(art, n, 3)

                self._out_combos.append((combo, art))

            grille.setColumnStretch(2, 1)
            card_lay.addLayout(grille)

            self._out_hint = QLabel("")
            self._out_hint.setStyleSheet("color: #e6a817; font-size: 9px; background: transparent; border: none;")
            self._out_hint.setWordWrap(True)
            card_lay.addWidget(self._out_hint)
            self._refresh_out_hint()

        lay.addWidget(card)


        lay.addStretch()

        QTimer.singleShot(120, self._check_node_status)
        return w

    # ── détection Node asynchrone ────────────────────────────────────────

    def _check_node_status(self):
        self._node_qt = _QuickDetector()
        self._node_qt.finished.connect(self._on_node_checked)
        self._node_scanner = _AdapterScanner()
        self._node_scanner.done.connect(self._on_adapters_for_status)
        self._node_qt.start()
        self._node_scanner.start()

    def _on_node_checked(self, found: bool):
        if found:
            self._node_status_dot.setStyleSheet(
                "color: #4ade80; font-size: 20px; background: transparent; border: none;")
            self._node_status_lbl.setText(tr("nc_device_connected"))
            self._node_status_lbl.setStyleSheet(
                "color: #4ade80; font-weight: 700; background: transparent; border: none;")
        else:
            self._node_status_dot.setStyleSheet(
                "color: #f87171; font-size: 20px; background: transparent; border: none;")
            self._node_status_lbl.setText(tr("nc_device_not_found"))
            self._node_status_lbl.setStyleSheet(
                "color: #f87171; font-weight: 700; background: transparent; border: none;")

    def _on_adapters_for_status(self, adapters: list):
        for name, ip, desc, connected in adapters:
            if ip.startswith("2."):
                self._node_net_lbl.setText(name)
                self._node_net_lbl.setStyleSheet(
                    "color: #aaa; background: transparent; border: none;")
                self._set_net_hint(False)
                return
        self._node_net_lbl.setText(tr("nc_not_configured"))
        self._node_net_lbl.setStyleSheet(
            "color: #f87171; background: transparent; border: none;")
        self._set_net_hint(True)

    def _set_net_hint(self, a_configurer: bool):
        """Met le bouton de configuration reseau en avant quand la carte
        n'est pas en 2.x."""
        btn = getattr(self, '_node_cfg_btn', None)
        if btn is not None:
            btn.setStyleSheet(_BTN_NET_TODO if a_configurer else _BTN_DIAG)

    def _open_node_wizard(self):
        self.accept()
        if self._main_win:
            dlg = NodeSetupWizard(self._main_win)
            dlg.exec()

    def _page_usb(self):
        """Page ENTTEC : sélection du protocole + port COM."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Sélecteur d'interface (le protocole est choisi automatiquement en coulisses)
        proto_row = QHBoxLayout()
        proto_lbl = QLabel(tr("nc_interface"))
        proto_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        proto_row.addWidget(proto_lbl)
        proto_row.addStretch()
        self._proto_combo = ComboSansMolette()
        for _label, _tr in [
            ("Eurolite USB-DMX512 PRO (MK2)", TRANSPORT_ENTTEC_PRO),
            ("ENTTEC DMX USB Pro",            TRANSPORT_ENTTEC_PRO),
            ("ENTTEC Open DMX USB",           TRANSPORT_ENTTEC),
            ("OPTO OPEN DMX (ElectroConcept)", TRANSPORT_ENTTEC),
            ("DMXKing UltraDMX Micro",        TRANSPORT_ENTTEC),
            ("Autre interface USB-DMX",       TRANSPORT_ENTTEC),
        ]:
            self._proto_combo.addItem(_label, _tr)
        cur_transport = self._dmx.transport if self._dmx else TRANSPORT_ENTTEC
        # enttec_d2xx est une variante d'Open DMX → pointer sur l'entrée Open DMX
        if cur_transport == TRANSPORT_ENTTEC_D2XX:
            cur_transport = TRANSPORT_ENTTEC
        _idx = self._proto_combo.findData(cur_transport)
        if _idx < 0:                                   # défaut sûr = Open DMX, pas Pro
            _idx = self._proto_combo.findData(TRANSPORT_ENTTEC)
        self._proto_combo.setCurrentIndex(max(0, _idx))
        self._proto_combo.setFixedWidth(310)
        self._proto_combo.setFont(QFont("Segoe UI", 9))
        self._proto_combo.setStyleSheet(
            "QComboBox { background:#2a2a2a; color:white; border:1px solid #3a3a3a;"
            " border-radius:4px; padding:3px 8px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background:#2a2a2a; color:white; }")
        self._proto_combo.currentIndexChanged.connect(self._on_proto_changed)
        proto_row.addWidget(self._proto_combo)
        lay.addLayout(proto_row)

        self._proto_info = QLabel("")
        self._proto_info.setStyleSheet("color: #555; font-size: 10px;")
        lay.addWidget(self._proto_info)
        self._update_proto_info()

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #1a1a1a; border: 1px solid #252525; border-radius: 10px; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(18, 14, 18, 14)
        card_lay.setSpacing(12)

        # Port COM
        port_row = QHBoxLayout()
        port_lbl = QLabel(tr("nc_com_port"))
        port_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        port_row.addWidget(port_lbl)
        port_row.addStretch()

        self._port_combo = ComboSansMolette()
        self._port_combo.setFixedWidth(200)
        port_row.addWidget(self._port_combo)

        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.setStyleSheet(
            "QPushButton { background: #222; color: #888; border: 1px solid #333; border-radius: 6px; } "
            "QPushButton:hover { color: #ccc; }"
        )
        refresh_btn.setCursor(QCursor(Qt.PointingHandCursor))
        refresh_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(refresh_btn)
        card_lay.addLayout(port_row)

        _h = QFrame(); _h.setFrameShape(QFrame.HLine)
        _h.setStyleSheet("QFrame { border: none; border-top: 1px solid #252525; }")
        card_lay.addWidget(_h)

        # Status + test
        status_row = QHBoxLayout()
        self._usb_indicator = QLabel("●")
        self._usb_indicator.setFont(QFont("Segoe UI", 12))
        self._usb_indicator.setStyleSheet("color: #444;")
        self._usb_indicator.setFixedWidth(18)
        status_row.addWidget(self._usb_indicator)

        self._usb_status_lbl = QLabel(tr("nc_select_port"))
        self._usb_status_lbl.setStyleSheet("color: #666; font-size: 10px;")
        status_row.addWidget(self._usb_status_lbl, 1)

        test_btn = QPushButton(tr("nc_diagnostic"))
        test_btn.setFixedHeight(30)
        test_btn.setStyleSheet(_BTN_TEST)
        test_btn.setCursor(QCursor(Qt.PointingHandCursor))
        test_btn.clicked.connect(self._open_usb_diagnostic)
        status_row.addWidget(test_btn)
        card_lay.addLayout(status_row)

        lay.addWidget(card)

        # ── Renvoi vers l'onglet Node (masqué tant qu'un port existe) ────────
        self._renvoi_node = QFrame()
        self._renvoi_node.setStyleSheet(
            "QFrame { background: #1e1a10; border: 1px solid #4a3a15;"
            " border-radius: 8px; }")
        rn_lay = QVBoxLayout(self._renvoi_node)
        rn_lay.setContentsMargins(12, 10, 12, 10)
        rn_lay.setSpacing(8)

        rn_txt = QLabel(
            tr("nc_no_usb_iface"))
        rn_txt.setWordWrap(True)
        rn_txt.setStyleSheet(
            "color: #d6b878; font-size: 10px; background: transparent; border: none;")
        rn_lay.addWidget(rn_txt)

        rn_btn = QPushButton(tr("nc_go_node_tab"))
        rn_btn.setFixedHeight(30)
        rn_btn.setCursor(QCursor(Qt.PointingHandCursor))
        rn_btn.setStyleSheet(
            "QPushButton { background: #2a2413; color: #e6a817; border: 1px solid #5a4820;"
            " border-radius: 6px; font-size: 10px; font-weight: bold; padding: 0 14px; }"
            "QPushButton:hover { background: #3a3018; color: #ffc94a; }")
        rn_btn.clicked.connect(lambda: self._set_transport(TRANSPORT_ARTNET))
        rn_lay.addWidget(rn_btn, 0, Qt.AlignLeft)

        self._renvoi_node.setVisible(False)   # affiché par _maj_renvoi_node
        lay.addWidget(self._renvoi_node)

        lay.addStretch()
        return w

    # ── Actions ────────────────────────────────────────────────────────

    def _on_proto_changed(self, _idx):
        self._update_proto_info()

    def _update_proto_info(self):
        if not hasattr(self, '_proto_info'):
            return
        proto = self._proto_combo.currentData() if hasattr(self, '_proto_combo') else TRANSPORT_ENTTEC
        # Rien à dire sur les adaptateurs simples : le label est masqué pour ne
        # pas laisser une ligne vide sous le sélecteur d'interface.
        texte = ("La LED de l'interface passe au vert quand la sortie DMX est active."
                 if proto == TRANSPORT_ENTTEC_PRO else "")
        self._proto_info.setText(texte)
        self._proto_info.setVisible(bool(texte))

    def _set_transport(self, transport, save=True):
        self._transport = transport
        is_node = (transport == TRANSPORT_ARTNET)
        self._btn_node.setStyleSheet(_BTN_TOGGLE_ON if is_node else _BTN_TOGGLE_OFF)
        self._btn_usb.setStyleSheet(_BTN_TOGGLE_OFF if is_node else _BTN_TOGGLE_ON)
        self._stack.setCurrentIndex(0 if is_node else 1)
        # Synchroniser le combo interface si on bascule en mode USB
        if not is_node and hasattr(self, '_proto_combo'):
            lookup = TRANSPORT_ENTTEC if transport == TRANSPORT_ENTTEC_D2XX else transport
            idx = self._proto_combo.findData(lookup)
            if idx >= 0:
                self._proto_combo.setCurrentIndex(idx)
        self._status_lbl.setText("")

    def _refresh_ports(self):
        """Actualise la liste des ports COM disponibles."""
        self._port_combo.clear()
        aucun = False
        try:
            import serial.tools.list_ports as _lp
            ports = list(_lp.comports())
            current_com = self._dmx.com_port if self._dmx else None
            for p in sorted(ports, key=lambda x: x.device):
                desc = p.description if p.description and p.description != "n/a" else ""
                label = f"{p.device}  —  {desc}" if desc else p.device
                self._port_combo.addItem(label, p.device)
                if p.device == current_com:
                    self._port_combo.setCurrentIndex(self._port_combo.count() - 1)
            if not ports:
                self._port_combo.addItem(tr("nc_no_port"), None)
                aucun = True
        except ImportError:
            self._port_combo.addItem(tr("nc_no_serial"), None)
            aucun = True
        self._maj_renvoi_node(aucun)

    def _maj_renvoi_node(self, aucun_port: bool):
        """Affiche le renvoi vers l'onglet Node quand l'onglet USB est une impasse.

        « Aucun port détecté » est exactement l'écran où atterrit quelqu'un qui a
        acheté un Node Art-Net et cherche à le brancher ici. Sans renvoi, il
        recharge la liste en boucle et conclut que son boîtier est mort. Le
        message n'apparaît que dans ce cas : quand un port existe, il n'y a pas
        d'ambiguïté à lever.
        """
        bloc = getattr(self, '_renvoi_node', None)
        if bloc is None:
            return
        bloc.setVisible(aucun_port)

    def _open_usb_diagnostic(self):
        """Ouvre le diagnostic complet DMX USB (enttec_setup.py)."""
        from enttec_setup import DmxSetupDialog
        dlg = DmxSetupDialog(self._dmx, parent=self._main_win or self)
        # Présélectionner le port COM actuellement choisi dans ce dialogue
        com = self._port_combo.currentData()
        if com and hasattr(dlg, 'port_combo'):
            for i in range(dlg.port_combo.count()):
                if dlg.port_combo.itemData(i) == com:
                    dlg.port_combo.setCurrentIndex(i)
                    break
        dlg.exec()

    def _out_map_from_ui(self):
        """Correspondance sortie -> univers lue dans les combos."""
        return [c.currentData() for c, _ in getattr(self, '_out_combos', [])]

    def _refresh_out_hint(self):
        """Rappelle l'univers Art-Net de chaque sortie et signale les cas piégeux."""
        if not getattr(self, '_out_combos', None) or self._dmx is None:
            return
        base = getattr(self._dmx, 'universe', 0)
        mapping = self._out_map_from_ui()

        for n, (_c, art) in enumerate(self._out_combos):
            if mapping[n] == OUTPUT_OFF:
                art.setText("— noir —")
            elif mapping[n] == OUTPUT_INPUT:
                art.setText(f"← Art-Net {base + n}")
            else:
                art.setText(f"Art-Net {base + n}")

        # Pas d'alerte « univers non diffusé » ici : un patch n'occupe presque
        # jamais les 4 univers, et signaler les 3 vides à chaque ouverture ne
        # décrivait qu'une situation normale.
        doublons  = sorted({u + 1 for u in mapping
                            if u not in (OUTPUT_OFF, OUTPUT_INPUT)
                            and mapping.count(u) > 1})
        eteintes  = [n + 1 for n, u in enumerate(mapping) if u == OUTPUT_OFF]
        entrees   = [n + 1 for n, u in enumerate(mapping) if u == OUTPUT_INPUT]
        msgs = []
        if entrees:
            msgs.append(tr("nc_out_input_hint", a0=", DMX ".join(map(str, entrees)),
                           a1=", ".join(str(base + n - 1) for n in entrees)))
        if eteintes:
            msgs.append("Sortie désactivée : DMX " + ", DMX ".join(map(str, eteintes)))
        if doublons:
            msgs.append("Dupliqué (miroir) : " + ", ".join(map(str, doublons)))
        self._out_hint.setText("   ·   ".join(msgs))

    def _journal(self, text: str, level: str = "info"):
        """Écrit dans le journal de la fenêtre principale, si elle est joignable.

        Le dialogue peut être ouvert sans parent (tests, diagnostic) : l'absence
        de journal ne doit jamais empêcher la connexion de se faire.
        """
        win = self._main_win
        if win is not None and hasattr(win, '_log_message'):
            try:
                win._log_message(text, level)
            except Exception:
                pass

    def _apply(self):
        """Sauvegarde le transport actif et reconnecte."""
        if not self._dmx:
            self.accept()
            return

        if self._transport == TRANSPORT_ARTNET:
            # Aiguillage des sorties, appliqué AVANT connect() : c'est lui qui
            # décide quelles données partent sur quelle sortie du Node.
            mapping = self._out_map_from_ui()
            if mapping:
                self._dmx.set_output_map(mapping)
            actifs = [u for u in mapping if u not in (OUTPUT_OFF, OUTPUT_INPUT)]
            mirror_on = len(set(actifs)) < len(actifs)
            u2 = self._dmx.universe + 1
            self._dmx.connect(
                transport=TRANSPORT_ARTNET,
                target_ip=TARGET_IP,
                target_port=TARGET_PORT,
                universe=0,
                universe2=u2,
                mirror_output=mirror_on,
                product_id="artnet",
                product_name="Art-Net (réseau)",
            )
            # Résumé lisible de l'aiguillage : « DMX1←U1  DMX2←U1  DMX3←U3… »
            routage = "  ".join(
                f"DMX{n+1}←{ {OUTPUT_OFF: 'OFF', OUTPUT_INPUT: 'IN'}.get(u, f'U{u+1}') }"
                for n, u in enumerate(mapping)) if mapping else ""
            self._status_lbl.setStyleSheet("color: #4ade80; font-size: 10px;")
            self._status_lbl.setText(
                f"Sortie Node appliquée — {TARGET_IP}:{TARGET_PORT}"
                + (f"  •  {routage}" if routage else ""))
            self._journal(
                f"Sortie DMX : Art-Net connecté — {TARGET_IP}:{TARGET_PORT}"
                + (f"  ({routage})" if routage else ""),
                "success",
            )
        else:
            com = self._port_combo.currentData()
            if not com:
                self._status_lbl.setStyleSheet("color: #f87171; font-size: 10px;")
                self._status_lbl.setText(tr("nc_select_com_port"))
                return

            proto = self._proto_combo.currentData() if hasattr(self, '_proto_combo') else TRANSPORT_ENTTEC
            is_pro = (proto == TRANSPORT_ENTTEC_PRO)

            # Open DMX USB & assimilés (FTDI passif) : préférer le D2XX, fiable et
            # propre comme QLC+. Le port COM/VCP corrompt le timing du break DMX
            # (Latency Timer FTDI) → clignotements / lyres qui bougent seules.
            # resolve_usb_transport retombe sur la série si le D2XX est indispo.
            ftdi_serial = None
            if not is_pro:
                try:
                    from enttec_setup import resolve_usb_transport
                    proto, ftdi_serial = resolve_usb_transport(com)
                except Exception:
                    proto = TRANSPORT_ENTTEC

            # Si le boîtier est déjà ouvert avec le même transport, ne pas reconnecter.
            if proto == TRANSPORT_ENTTEC_D2XX:
                already_open = (
                    getattr(self._dmx, '_d2xx', None) is not None
                    and getattr(self._dmx, 'connected', False)
                    and getattr(self._dmx, 'transport', None) == proto
                )
            else:
                _ser = getattr(self._dmx, '_pro_serial' if is_pro else '_serial', None)
                already_open = (
                    _ser and _ser.is_open
                    and getattr(self._dmx, 'com_port', None) == com
                    and getattr(self._dmx, 'transport', None) == proto
                )
            if already_open:
                self._dmx.transport    = proto
                self._dmx.com_port     = com
                self._dmx.product_id   = "enttec_pro" if is_pro else "enttec"
                self._dmx.product_name = "ENTTEC DMX USB Pro" if is_pro else "ENTTEC Open DMX USB"
                self._dmx._save_config()
            else:
                ok = self._dmx.connect(
                    transport=proto,
                    com_port=com,
                    ftdi_serial=ftdi_serial,
                    product_id="enttec_pro" if is_pro else "enttec",
                    product_name="ENTTEC DMX USB Pro" if is_pro else "ENTTEC Open DMX USB",
                )
                if not ok:
                    self._status_lbl.setStyleSheet("color: #f87171; font-size: 10px;")
                    self._status_lbl.setText(
                        tr("nc_f_port_busy", com=com)
                    )
                    self._journal(
                        f"Sortie DMX : échec de connexion sur {com} — port inaccessible",
                        "error",
                    )
                    return
            if is_pro:
                proto_label = "Pro"
            elif proto == TRANSPORT_ENTTEC_D2XX:
                proto_label = "Open (D2XX)"
            else:
                proto_label = "Open (série)"
            self._status_lbl.setStyleSheet("color: #4ade80; font-size: 10px;")
            self._status_lbl.setText(tr("nc_f_usb_applied", proto_label=proto_label, com=com))
            # Vaut aussi pour la branche « déjà ouvert » : l'utilisateur a cliqué
            # « Connecter », le journal doit confirmer l'état obtenu — pas
            # rester muet sous prétexte qu'aucun port n'a été rouvert.
            self._journal(
                f"Sortie DMX : {'ENTTEC DMX USB Pro' if is_pro else 'ENTTEC Open DMX USB'} "
                f"connecté — {com} ({proto_label})",
                "success",
            )

        self.transport_changed.emit(self._transport)
        self.accept()
