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
    QWidget, QStackedWidget, QScrollArea, QLineEdit, QComboBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QCursor

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


def _get_ethernet_adapters_mac():
    """Détecte les interfaces réseau sur macOS via ifconfig."""
    _SKIP_PREFIXES = ("lo", "utun", "awdl", "llw", "stf", "gif", "anpi",
                      "bridge", "ap1", "XHC", "p2p")
    try:
        r = subprocess.run(["ifconfig", "-a"], capture_output=True, text=True, timeout=5)
    except Exception:
        return []

    adapters = []
    current_name = None
    current_ip = ""
    current_connected = False

    for line in r.stdout.splitlines():
        # Ligne d'en-tête d'interface : "en0: flags=..."
        m = re.match(r'^(\w[\w.]*): ', line)
        if m:
            if current_name and not any(current_name.startswith(p) for p in _SKIP_PREFIXES):
                adapters.append((current_name, current_ip, current_name, current_connected))
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

    if current_name and not any(current_name.startswith(p) for p in _SKIP_PREFIXES):
        adapters.append((current_name, current_ip, current_name, current_connected))

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
    """ArtPoll vers target_ip, filtre les réponses du PC lui-même."""
    local_ips = _get_all_local_ips()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind(("", 6454))
        except OSError:
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
                if data[:8] == b'Art-Net\x00' and sender not in local_ips:
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
            eth_detail = "Aucune carte Ethernet détectée — vérifiez le câble RJ45"
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
        self.setWindowTitle("Paramétrer la sortie Node DMX")
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
        title = QLabel("Sortie Node DMX")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet("color: #f0f0f0;")
        sub = QLabel(f"Boîtier ElectroConcept  ·  {TARGET_IP}  ·  Art-Net")
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
            d = QLabel("Vérification en cours...")
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

        root.addStretch()

        # Boutons
        btn_row = QHBoxLayout()

        self._fix_btn = QPushButton("⚙️  Configurer le réseau")
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

        self._retry_btn = QPushButton("↺  Relancer")
        self._retry_btn.setEnabled(False)
        self._retry_btn.clicked.connect(self._run)

        self._manual_btn = QPushButton("📂  Réseau")
        self._manual_btn.setVisible(False)
        self._manual_btn.clicked.connect(_open_network_connections)

        close_btn = QPushButton("Fermer")
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
        self._retry_btn.setEnabled(False)
        self._msg_lbl.setText("Analyse en cours...")
        self._msg_lbl.setStyleSheet("color: #555;")
        for icon, t, d in self._row_widgets:
            icon.setText("◌")
            icon.setStyleSheet(f"color: {_C_DIM};")
            d.setText("Vérification en cours...")
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
            self._msg_lbl.setText("Tout est opérationnel ✓")
            self._msg_lbl.setStyleSheet(f"color: {_C_OK}; font-weight: bold;")
        elif cable_issue:
            self._msg_lbl.setText("Aucune carte Ethernet détectée.\nVérifiez que le câble RJ45 est bien branché.")
            self._msg_lbl.setStyleSheet(f"color: {_C_ERR};")
            self._manual_btn.setVisible(True)
        elif box_issue and not fixable:
            self._msg_lbl.setText(f"Le boîtier {TARGET_IP} ne répond pas.\nVérifiez qu'il est allumé et que le câble est branché.")
            self._msg_lbl.setStyleSheet(f"color: {_C_ERR};")
        else:
            self._msg_lbl.setText(f"{len(errors)} problème(s) détecté(s)")
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


class NodeSetupWizard(QDialog):
    """Wizard de configuration réseau pas à pas pour le Node DMX."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Node DMX")
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
        self._btn_back = QPushButton("← Retour"); self._btn_back.setFixedHeight(36)
        self._btn_back.setStyleSheet(_BTN_GHOST)
        self._btn_back.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_back.clicked.connect(self._on_back); self._btn_back.hide()
        fl.addWidget(self._btn_back); fl.addStretch()
        close_btn = QPushButton("Fermer"); close_btn.setFixedHeight(36)
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
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("🔌")); lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Branchons le boîtier")); lay.addSpacing(4)
        lay.addWidget(self._sub_lbl("Vérifiez que les 2 connexions sont bien faites"))
        lay.addSpacing(14)
        lay.addWidget(self._card("🔵", "Câble RJ45 (Ethernet)",
            "Entre le boîtier et l'ordinateur  —  données DMX", accent="#00d4ff"))
        lay.addSpacing(8)
        lay.addWidget(self._card("🔴", "Alimentation",
            "Port USB carré (USB-B) ou USB Type-C selon le modèle", accent="#f87171"))
        lay.addSpacing(16); lay.addWidget(self._step_indicator(0)); lay.addSpacing(14)
        lay.addWidget(self._primary_btn("Les 2 sont branchés  →", self._start_adapter_scan))
        return w

    def _pg_adapters(self):
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("🌐")); lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Quelle carte réseau ?")); lay.addSpacing(4)
        lay.addWidget(self._sub_lbl("Choisissez la carte RJ45 reliée au boîtier\n(pas la Wi-Fi)"))
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
        self._btn_net_suivant = QPushButton("Continuer  →")
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
        note = QLabel("ⓘ  Droits administrateur requis pour la configuration auto")
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
            lbl = QLabel("Aucune carte Ethernet détectée.\nVérifiez que le câble RJ45 est bien branché.")
            lbl.setStyleSheet("color: #fbbf24; background: #2a2000; border: 1px solid #554400; "
                "border-radius: 6px; padding: 12px;")
            lbl.setWordWrap(True); lbl.setAlignment(Qt.AlignCenter)
            self._adapters_layout.insertWidget(0, lbl)
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
                f"Carte : « {adapter_name} »  —  IP actuelle : {ip_display}")
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
            f"1.  Clic droit sur {label}\n"
            "2.  Propriétés\n"
            "3.  TCP/IPv4  →  Propriétés\n"
            "4.  Adresse IP :          2 . 0 . 0 . 1\n"
            "    Masque :  255 . 0 . 0 . 0\n"
            "5.  OK  →  OK  →  Fermer"
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
                f"Le boîtier n'a pas répondu sur {TARGET_IP}.\n"
                "Vérifiez qu'il est allumé et que le câble RJ45 est branché.")
            self._manual_steps_lbl.setText(
                f"1.  Clic droit sur {label}\n"
                "2.  Propriétés\n"
                "3.  TCP/IPv4  →  Propriétés\n"
                "4.  Adresse IP :          2 . 0 . 0 . 1\n"
                "    Masque :  255 . 0 . 0 . 0\n"
                "5.  OK  →  OK  →  Fermer"
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
    from artnet_dmx import TRANSPORT_ARTNET, TRANSPORT_ENTTEC
except ImportError:
    TRANSPORT_ARTNET = "artnet"
    TRANSPORT_ENTTEC = "enttec"

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
        self.setWindowTitle("Paramétrer la sortie DMX")
        self.setFixedSize(520, 490)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(_SS_DIALOG)

        dmx = getattr(parent, 'dmx', None)
        self._dmx = dmx
        self._transport = dmx.transport if dmx else TRANSPORT_ARTNET

        self._build_ui()
        self._refresh_ports()
        self._set_transport(self._transport, save=False)

    # ── Construction UI ────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)

        # Titre
        title = QLabel("Paramétrer la sortie DMX")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet("color: #f0f0f0;")
        root.addWidget(title)

        # Toggle Node / USB
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(8)

        self._btn_node = QPushButton("🌐  Sortie Node")
        self._btn_node.setFixedHeight(40)
        self._btn_node.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_node.clicked.connect(lambda: self._set_transport(TRANSPORT_ARTNET))
        toggle_row.addWidget(self._btn_node)

        self._btn_usb = QPushButton("🔌  Sortie DMX USB")
        self._btn_usb.setFixedHeight(40)
        self._btn_usb.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_usb.clicked.connect(lambda: self._set_transport(TRANSPORT_ENTTEC))
        toggle_row.addWidget(self._btn_usb)
        root.addLayout(toggle_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { border: none; border-top: 1px solid #222; }")
        root.addWidget(sep)

        # Pages
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_node())
        self._stack.addWidget(self._page_usb())
        root.addWidget(self._stack, 1)

        # Boutons bas
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #555; font-size: 10px;")
        btn_row.addWidget(self._status_lbl, 1)

        btn_cancel = QPushButton("Fermer")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.clicked.connect(self.accept)
        btn_row.addWidget(btn_cancel)

        self._btn_apply = QPushButton("✓  Appliquer")
        self._btn_apply.setFixedHeight(36)
        self._btn_apply.setStyleSheet(_BTN_APPLY)
        self._btn_apply.clicked.connect(self._apply)
        btn_row.addWidget(self._btn_apply)
        root.addLayout(btn_row)

    def _page_node(self):
        """Page Art-Net : statut de connexion (lecture seule) + bouton de configuration."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        info = QLabel("Boîtier réseau Art-Net (ElectroConcept, MA Lighting, etc.)")
        info.setStyleSheet("color: #555; font-size: 10px;")
        lay.addWidget(info)

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
        self._node_status_lbl = QLabel("Vérification en cours…")
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
        net_key = QLabel("Carte réseau")
        net_key.setFont(QFont("Segoe UI", 9))
        net_key.setStyleSheet("color: #666; background: transparent; border: none;")
        net_row.addWidget(net_key)
        net_row.addStretch()
        self._node_net_lbl = QLabel("Détection…")
        self._node_net_lbl.setFont(QFont("Segoe UI", 9))
        self._node_net_lbl.setStyleSheet("color: #888; background: transparent; border: none;")
        self._node_net_lbl.setAlignment(Qt.AlignRight)
        net_row.addWidget(self._node_net_lbl)
        card_lay.addLayout(net_row)

        lay.addWidget(card)

        cfg_btn = QPushButton("⚙️  Configurer la connexion réseau")
        cfg_btn.setFixedHeight(36)
        cfg_btn.setStyleSheet(_BTN_DIAG)
        cfg_btn.setCursor(QCursor(Qt.PointingHandCursor))
        cfg_btn.clicked.connect(self._open_node_wizard)
        lay.addWidget(cfg_btn)

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
            self._node_status_lbl.setText("Boîtier connecté  ✓")
            self._node_status_lbl.setStyleSheet(
                "color: #4ade80; font-weight: 700; background: transparent; border: none;")
        else:
            self._node_status_dot.setStyleSheet(
                "color: #f87171; font-size: 20px; background: transparent; border: none;")
            self._node_status_lbl.setText("Boîtier non détecté")
            self._node_status_lbl.setStyleSheet(
                "color: #f87171; font-weight: 700; background: transparent; border: none;")

    def _on_adapters_for_status(self, adapters: list):
        for name, ip, desc, connected in adapters:
            if ip.startswith("2."):
                self._node_net_lbl.setText(name)
                self._node_net_lbl.setStyleSheet(
                    "color: #aaa; background: transparent; border: none;")
                return
        self._node_net_lbl.setText("Non configurée")
        self._node_net_lbl.setStyleSheet(
            "color: #f87171; background: transparent; border: none;")

    def _open_node_wizard(self):
        self.accept()
        if self._main_win:
            dlg = NodeSetupWizard(self._main_win)
            dlg.exec()

    def _page_usb(self):
        """Page ENTTEC : sélection du port COM."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        info = QLabel("ENTTEC Open DMX USB — connexion via port série (250 000 bauds)")
        info.setStyleSheet("color: #555; font-size: 10px;")
        lay.addWidget(info)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #1a1a1a; border: 1px solid #252525; border-radius: 10px; }"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(18, 14, 18, 14)
        card_lay.setSpacing(12)

        # Port COM
        port_row = QHBoxLayout()
        port_lbl = QLabel("Port COM")
        port_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        port_row.addWidget(port_lbl)
        port_row.addStretch()

        self._port_combo = QComboBox()
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

        self._usb_status_lbl = QLabel("Sélectionnez un port")
        self._usb_status_lbl.setStyleSheet("color: #666; font-size: 10px;")
        status_row.addWidget(self._usb_status_lbl, 1)

        test_btn = QPushButton("🔌  Tester")
        test_btn.setFixedHeight(30)
        test_btn.setStyleSheet(_BTN_TEST)
        test_btn.setCursor(QCursor(Qt.PointingHandCursor))
        test_btn.clicked.connect(self._test_usb)
        status_row.addWidget(test_btn)
        card_lay.addLayout(status_row)

        lay.addWidget(card)

        lay.addStretch()
        return w

    # ── Actions ────────────────────────────────────────────────────────

    def _set_transport(self, transport, save=True):
        self._transport = transport
        is_node = (transport == TRANSPORT_ARTNET)
        self._btn_node.setStyleSheet(_BTN_TOGGLE_ON if is_node else _BTN_TOGGLE_OFF)
        self._btn_usb.setStyleSheet(_BTN_TOGGLE_OFF if is_node else _BTN_TOGGLE_ON)
        self._stack.setCurrentIndex(0 if is_node else 1)
        self._status_lbl.setText("")

    def _refresh_ports(self):
        """Actualise la liste des ports COM disponibles."""
        self._port_combo.clear()
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
                self._port_combo.addItem("Aucun port détecté", None)
        except ImportError:
            self._port_combo.addItem("Module série non disponible", None)

    def _test_usb(self):
        """Teste si le port COM sélectionné est accessible."""
        com = self._port_combo.currentData()
        if not com:
            self._usb_indicator.setStyleSheet("color: #f87171;")
            self._usb_status_lbl.setText("Aucun port sélectionné")
            return
        self._usb_status_lbl.setText("Test en cours…")
        self._usb_indicator.setStyleSheet("color: #888;")

        # Si le module DMX a déjà ce port ouvert, pas besoin de rouvrir
        dmx_serial = getattr(self._dmx, '_serial', None)
        if (dmx_serial and dmx_serial.is_open
                and getattr(self._dmx, 'com_port', None) == com):
            self._usb_indicator.setStyleSheet("color: #4ade80;")
            self._usb_status_lbl.setText(f"Port {com} accessible ✓")
            return

        try:
            import serial as _s
            p = _s.Serial(com, 250000, stopbits=_s.STOPBITS_TWO, timeout=0.5)
            p.close()
            self._usb_indicator.setStyleSheet("color: #4ade80;")
            self._usb_status_lbl.setText(f"Port {com} accessible ✓")
        except ImportError:
            self._usb_indicator.setStyleSheet("color: #f87171;")
            self._usb_status_lbl.setText("Module série non disponible — relancez l'application")
        except Exception as e:
            self._usb_indicator.setStyleSheet("color: #f87171;")
            err = str(e)
            if "13" in err or "permission" in err.lower() or "access" in err.lower():
                self._usb_status_lbl.setText(
                    f"Port {com} occupé par une autre application\n"
                    "(Chataigne, ENTTEC Software…) — fermez-la d'abord"
                )
            else:
                self._usb_status_lbl.setText(f"Erreur : {e}")

    def _apply(self):
        """Sauvegarde le transport actif et reconnecte."""
        if not self._dmx:
            self.accept()
            return

        if self._transport == TRANSPORT_ARTNET:
            self._dmx.connect(
                transport=TRANSPORT_ARTNET,
                target_ip=TARGET_IP,
                target_port=TARGET_PORT,
                universe=0,
                product_id="artnet",
                product_name="Art-Net (réseau)",
            )
            self._status_lbl.setStyleSheet("color: #4ade80; font-size: 10px;")
            self._status_lbl.setText(f"Sortie Node appliquée — {TARGET_IP}:{TARGET_PORT}")
        else:
            com = self._port_combo.currentData()
            if not com:
                self._status_lbl.setStyleSheet("color: #f87171; font-size: 10px;")
                self._status_lbl.setText("Sélectionnez un port COM")
                return
            ok = self._dmx.connect(
                transport=TRANSPORT_ENTTEC,
                com_port=com,
                product_id="enttec",
                product_name="ENTTEC Open DMX USB",
            )
            if not ok:
                self._status_lbl.setStyleSheet("color: #f87171; font-size: 10px;")
                self._status_lbl.setText(
                    f"Port {com} inaccessible — fermez Chataigne ou toute autre app DMX"
                )
                return
            self._status_lbl.setStyleSheet("color: #4ade80; font-size: 10px;")
            self._status_lbl.setText(f"Sortie USB appliquée — {com}")

        self.transport_changed.emit(self._transport)
        self.accept()
