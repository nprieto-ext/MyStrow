"""
Assistant de connexion et configuration du Node DMX
- Détection rapide au démarrage (ArtPoll 0.5 s sur l'IP cible)
- Sélection explicite de la carte réseau (jamais automatique)
- Configuration IPv4 192.168.0.1 automatique ou manuelle
- Guide Electroconcept : câbles RJ45 + USB, configuration TCP/IP, recherche node
"""

import re
import time
import subprocess
import platform
from typing import List, Tuple, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QWidget, QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QCursor

# ============================================================
# CONSTANTES
# ============================================================

TARGET_IP   = "2.0.0.15"   # IP du node Art-Net Electroconcept
TARGET_PORT = 5568

CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0

# Mots-clés pour ignorer les adaptateurs non-Ethernet physiques
_SKIP_ADAPTERS = [
    "wi-fi", "wifi", "wireless", "loopback", "vmware", "virtual",
    "bluetooth", "tunnel", "teredo", "isatap", "6to4", "miniport",
    "local*",       # Connexion au réseau local* = Wi-Fi Direct virtuel
    "vethernet",    # Hyper-V virtual switch
]

# Index des pages
P_DETECTING   = 0
P_CONNECTED   = 1
P_CHOOSE      = 2
P_EC_CABLES   = 3
P_WORKING     = 4
P_NET_MANUAL  = 5
P_SUCCESS     = 6
P_NET_SELECT  = 7   # Sélection de la carte réseau Node
P_NET_METHOD  = 8   # Choix auto / manuel


# ============================================================
# UTILITAIRES RÉSEAU (module-level, réutilisables par les threads)
# ============================================================

def _artpoll_packet() -> bytes:
    p = bytearray(b'Art-Net\x00')
    p.extend(b'\x00\x20')  # OpCode ArtPoll
    p.extend(b'\x00\x0e')  # Protocol version 14
    p.extend(b'\x00\x00')  # TalkToMe + Priority
    return bytes(p)


def _open_network_connections():
    """Ouvre le panneau Connexions réseau Windows."""
    try:
        subprocess.Popen(["control", "ncpa.cpl"],
                         creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def _get_ethernet_adapters() -> List[Tuple[str, str]]:
    """
    Retourne [(nom_interface, ipv4)] pour tous les adaptateurs réseau actifs.
    Parse ipconfig /all — robuste quelle que soit la locale Windows.
    """
    try:
        r = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True, text=True,
            encoding="cp1252", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return []

    adapters     = []
    current_name = None
    current_ip   = ""
    skip_current = False

    for line in r.stdout.splitlines():
        # Ligne de section : ne commence pas par un espace, se termine par ":"
        # (avec possible \xa0 ou espace insécable avant le ":")
        stripped_line = line.strip()
        is_section = (
            line
            and not line.startswith("\t")
            and not line.startswith(" ")
            and stripped_line.endswith(":")
        )

        if is_section:
            # Enregistrer l'adaptateur précédent si valide
            if current_name and not skip_current:
                adapters.append((current_name, current_ip))

            # Extraire le nom : retirer le préfixe de catégorie
            raw = stripped_line.rstrip(":").strip()
            for prefix in (
                "Carte Ethernet ", "Ethernet adapter ",
                "Carte réseau sans fil ", "Wireless LAN adapter ",
                "Adaptateur ", "Adapter ",
            ):
                if raw.lower().startswith(prefix.lower()):
                    raw = raw[len(prefix):]
                    break

            current_name = raw.strip()
            current_ip   = ""
            # Filtrer Wi-Fi, Bluetooth, Virtual, Tunnel, Loopback…
            skip_current = any(kw in current_name.lower() for kw in _SKIP_ADAPTERS)
            continue

        if not current_name or skip_current:
            continue

        stripped = line.strip()

        low = stripped.lower()
        # Tunnel = jamais pertinent
        if "tunnel" in low:
            skip_current = True
            continue

        # Adresse IPv4 — regex pour ignorer "(Préféré)"/"(Preferred)" collé à l'IP
        if "ipv4" in low:
            m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", stripped)
            if m:
                ip = m.group(1)
                if not ip.startswith("127."):
                    current_ip = ip

    # Dernier adaptateur
    if current_name and not skip_current:
        adapters.append((current_name, current_ip))

    return adapters


def _set_static_ip(adapter_name: str) -> bool:
    """Configure l'IP statique 2.0.0.1/255.0.0.0 (sans passerelle) via netsh. Requiert les droits admin."""
    try:
        r = subprocess.run(
            [
                "netsh", "interface", "ip", "set", "address",
                f"name={adapter_name}",
                "static", "2.0.0.1", "255.0.0.0", "none",
            ],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


# ============================================================
# THREADS
# ============================================================

def _artpoll_broadcast(timeout: float = 1.0) -> bool:
    """
    Envoie un ArtPoll en broadcast sur le réseau Art-Net (port 6454)
    et retourne True si un boîtier répond avec un paquet Art-Net valide.
    Sonde: 2.255.255.255, 255.255.255.255, TARGET_IP.
    """
    import socket as _sock, time as _t
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.setsockopt(_sock.SOL_SOCKET, _sock.SO_BROADCAST, 1)
        s.bind(("", 6454))
        s.settimeout(timeout)
        for ip in ("2.255.255.255", "255.255.255.255", TARGET_IP):
            try:
                s.sendto(_artpoll_packet(), (ip, 6454))
            except Exception:
                pass
        found = False
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            try:
                s.settimeout(max(0.05, deadline - _t.time()))
                data, _ = s.recvfrom(512)
                if data[:8] == b'Art-Net\x00':
                    found = True
                    break
            except Exception:
                break
        s.close()
        return found
    except Exception:
        return False


def _artpoll_unicast(target_ip: str, timeout: float = 1.0) -> bool:
    """
    Envoie un ArtPoll directement en unicast vers target_ip (port 6454).
    Pour les vieux boitiers qui ne repondent pas au broadcast.
    """
    import socket as _sock
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(_artpoll_packet(), (target_ip, 6454))
        deadline = __import__('time').time() + timeout
        while __import__('time').time() < deadline:
            try:
                s.settimeout(max(0.05, deadline - __import__('time').time()))
                data, _ = s.recvfrom(512)
                if data[:8] == b'Art-Net\x00':
                    s.close()
                    return True
            except Exception:
                break
        s.close()
    except Exception:
        pass
    return False


class QuickDetector(QThread):
    """Vérifie qu'un boîtier Art-Net répond — broadcast d'abord, puis unicast vers target_ip."""
    finished = Signal(bool)

    def __init__(self, target_ip: str = TARGET_IP, parent=None):
        super().__init__(parent)
        self._target_ip = target_ip

    def run(self):
        try:
            adapters = _get_ethernet_adapters()
            if not adapters:
                self.finished.emit(False)
                return
            # 1. Broadcast Art-Net (nouveaux boitiers)
            if _artpoll_broadcast(timeout=0.8):
                self.finished.emit(True)
                return
            # 2. Unicast vers l'IP configuree (vieux boitiers qui ne repondent pas au broadcast)
            if self._target_ip and self._target_ip != TARGET_IP:
                if _artpoll_unicast(self._target_ip, timeout=0.8):
                    self.finished.emit(True)
                    return
            self.finished.emit(False)
        except Exception:
            self.finished.emit(False)


class AdapterScanner(QThread):
    """Scanne les adaptateurs Ethernet connectés de façon asynchrone."""
    done = Signal(list)   # list of (name, ip)

    def run(self):
        self.done.emit(_get_ethernet_adapters())


class NetworkSetup(QThread):
    """
    Configure l'IP statique 2.0.0.1/255.0.0.0 (sans passerelle) sur l'adaptateur choisi.
    Émet : ('ok'|'manual', adapter_name)
    """
    done = Signal(str, str)

    def __init__(self, adapter_name: str):
        super().__init__()
        self.adapter_name = adapter_name

    def run(self):
        if _set_static_ip(self.adapter_name):
            time.sleep(1.5)
            self.done.emit("ok", self.adapter_name)
        else:
            self.done.emit("manual", self.adapter_name)


class NodeSearcher(QThread):
    """Après stabilisation réseau, sonde le boîtier Art-Net (broadcast + unicast)."""
    finished = Signal(bool)

    def __init__(self, target_ip: str = TARGET_IP, parent=None):
        super().__init__(parent)
        self._target_ip = target_ip

    def run(self):
        time.sleep(0.5)
        try:
            adapters = _get_ethernet_adapters()
            if not any(ip.startswith("2.") for _, ip in adapters):
                self.finished.emit(False)
                return
            if _artpoll_broadcast(timeout=2.0):
                self.finished.emit(True)
                return
            if self._target_ip:
                self.finished.emit(_artpoll_unicast(self._target_ip, timeout=1.5))
                return
            self.finished.emit(False)
        except Exception:
            self.finished.emit(False)


# ============================================================
# STYLES
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

# Wizard step labels
_WIZARD_STEPS = ["Câbles", "Carte réseau", "Adresse IP", "Connexion"]

# Page index constants
P_DETECTING  = 0   # spinner auto-detect
P_CONNECTED  = 1   # already connected
P_CABLES     = 2   # step 1: verify cables
P_ADAPTERS   = 3   # step 2: select network adapter
P_IP_METHOD  = 4   # step 3: auto vs manual IP
P_WORKING    = 5   # spinner (config in progress)
P_IP_MANUAL  = 6   # step 3b: manual IP instructions
P_SUCCESS    = 7   # success


# ============================================================
# DIALOG
# ============================================================

class NodeConnectionDialog(QDialog):
    """Assistant de connexion et configuration du Node DMX."""

    def __init__(self, parent=None, target_ip: str = TARGET_IP):
        super().__init__(parent)
        self._configured_ip = target_ip
        self.setWindowTitle("Connexion – Node DMX")
        self.setFixedSize(500, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet(
            "QDialog { background: #171717; } "
            "QLabel { color: #e0e0e0; border: none; background: transparent; }"
        )

        self._adapter_name: str = ""
        self._selected_adapter_name: str = ""
        self._selected_adapter_ip: str = ""
        self._adapter_buttons: list = []
        self._net_came_from_method: bool = False

        self._q_detect     = None
        self._adapter_scan = None
        self._net_setup    = None
        self._node_srch    = None

        self._spin_frames = ["◐", "◓", "◑", "◒"]
        self._spin_idx = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._tick)

        self._build_ui()
        QTimer.singleShot(150, self._start_quick_detection)

    # ──────────────────────────────────────────────────────
    # WIDGET HELPERS
    # ──────────────────────────────────────────────────────

    def _make_page(self):
        """Returns (QWidget, QVBoxLayout) with dark background and standard margins."""
        w = QWidget()
        w.setStyleSheet("background: #171717;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(32, 24, 32, 20)
        lay.setSpacing(0)
        return w, lay

    def _big_icon(self, text: str, color: str = "#00d4ff") -> QLabel:
        lbl = QLabel(text)
        f = QFont("Segoe UI Emoji", 32)
        lbl.setFont(f)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color: {color}; background: transparent;")
        return lbl

    def _title_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #f0f0f0; background: transparent;")
        return lbl

    def _sub_lbl(self, text: str, color: str = "#777777") -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 10))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {color}; background: transparent;")
        return lbl

    def _card(self, icon_char: str, bold_text: str, dim_text: str,
              accent: str = "#00d4ff") -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: #222222; border: 1px solid #333333; "
            f"border-left: 3px solid {accent}; border-radius: 8px; padding: 12px 14px; }}"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)

        icon_lbl = QLabel(icon_char)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 16))
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_lbl.setFixedWidth(28)
        row.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        bold_lbl = QLabel(bold_text)
        bold_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        bold_lbl.setStyleSheet("color: #e0e0e0; background: transparent; border: none;")
        text_col.addWidget(bold_lbl)
        dim_lbl = QLabel(dim_text)
        dim_lbl.setFont(QFont("Segoe UI", 9))
        dim_lbl.setWordWrap(True)
        dim_lbl.setStyleSheet("color: #777777; background: transparent; border: none;")
        text_col.addWidget(dim_lbl)

        row.addLayout(text_col, 1)
        return frame

    def _step_indicator(self, active: int) -> QWidget:
        """Renders a row of step dots with connecting lines and labels."""
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Top row: dots + lines
        dots_row = QHBoxLayout()
        dots_row.setContentsMargins(0, 0, 0, 0)
        dots_row.setSpacing(0)

        n = len(_WIZARD_STEPS)
        for i in range(n):
            # Dot
            if i < active:
                dot_color = "#4ade80"
                dot_char = "●"
            elif i == active:
                dot_color = "#00d4ff"
                dot_char = "●"
            else:
                dot_color = "#333333"
                dot_char = "○"

            dot = QLabel(dot_char)
            dot.setFont(QFont("Segoe UI", 12))
            dot.setStyleSheet(f"color: {dot_color}; background: transparent;")
            dot.setAlignment(Qt.AlignCenter)
            dot.setFixedWidth(20)
            dots_row.addWidget(dot)

            # Connecting line (not after the last dot)
            if i < n - 1:
                line_color = "#4ade80" if i < active else "#2a2a2a"
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setFrameShadow(QFrame.Plain)
                line.setFixedHeight(2)
                line.setStyleSheet(
                    f"QFrame {{ background: {line_color}; border: none; "
                    f"border-top: 2px solid {line_color}; }}"
                )
                dots_row.addWidget(line, 1)

        outer.addLayout(dots_row)

        # Bottom row: labels under each dot
        labels_row = QHBoxLayout()
        labels_row.setContentsMargins(0, 0, 0, 0)
        labels_row.setSpacing(0)

        for i, step_name in enumerate(_WIZARD_STEPS):
            if i < active:
                lbl_color = "#4ade80"
            elif i == active:
                lbl_color = "#00d4ff"
            else:
                lbl_color = "#444444"

            lbl = QLabel(step_name)
            lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet(f"color: {lbl_color}; background: transparent;")
            lbl.setAlignment(Qt.AlignCenter)
            labels_row.addWidget(lbl, 1)

        outer.addLayout(labels_row)
        return container

    def _primary_btn(self, text: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(_BTN_PRIMARY)
        btn.setFixedHeight(42)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.clicked.connect(callback)
        return btn

    def _secondary_btn(self, text: str, callback) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(_BTN_SECONDARY)
        btn.setFixedHeight(36)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.clicked.connect(callback)
        return btn

    # ──────────────────────────────────────────────────────
    # BUILD UI
    # ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: #171717;")
        root.addWidget(self._stack, 1)

        # Add pages in order
        self._stack.addWidget(self._pg_detecting())   # 0 = P_DETECTING
        self._stack.addWidget(self._pg_connected())   # 1 = P_CONNECTED
        self._stack.addWidget(self._pg_cables())      # 2 = P_CABLES
        self._stack.addWidget(self._pg_adapters())    # 3 = P_ADAPTERS
        self._stack.addWidget(self._pg_ip_method())   # 4 = P_IP_METHOD
        self._stack.addWidget(self._pg_working())     # 5 = P_WORKING
        self._stack.addWidget(self._pg_ip_manual())   # 6 = P_IP_MANUAL
        self._stack.addWidget(self._pg_success())     # 7 = P_SUCCESS

        # Footer (back + close)
        ftr = QFrame()
        ftr.setFixedHeight(64)
        ftr.setStyleSheet("QFrame { background: #111111; border-top: 1px solid #222222; }")
        fl = QHBoxLayout(ftr)
        fl.setContentsMargins(24, 0, 24, 0)
        fl.setSpacing(10)

        self._btn_back = QPushButton("← Retour")
        self._btn_back.setFixedHeight(36)
        self._btn_back.setStyleSheet(_BTN_GHOST)
        self._btn_back.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_back.clicked.connect(self._on_back)
        self._btn_back.hide()
        fl.addWidget(self._btn_back)
        fl.addStretch()

        self._btn_close = QPushButton("Fermer")
        self._btn_close.setFixedHeight(36)
        self._btn_close.setStyleSheet(_BTN_GHOST)
        self._btn_close.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_close.clicked.connect(self.accept)
        fl.addWidget(self._btn_close)

        root.addWidget(ftr)

    # ──────────────────────────────────────────────────────
    # PAGES
    # ──────────────────────────────────────────────────────

    # 0 — P_DETECTING
    def _pg_detecting(self):
        w, lay = self._make_page()
        lay.addStretch()
        self._spin_lbl = QLabel("◐")
        self._spin_lbl.setFont(QFont("Segoe UI", 48))
        self._spin_lbl.setStyleSheet("color: #00d4ff; background: transparent;")
        self._spin_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._spin_lbl)
        lay.addSpacing(12)
        lay.addWidget(self._sub_lbl("Recherche du boîtier DMX..."))
        lay.addStretch()
        return w

    # 1 — P_CONNECTED
    def _pg_connected(self):
        w, lay = self._make_page()
        lay.addStretch()
        lay.addWidget(self._big_icon("✅", "#4ade80"))
        lay.addSpacing(12)
        lay.addWidget(self._title_lbl("Boîtier connecté !"))
        lay.addSpacing(8)
        self._connected_ip_lbl = self._sub_lbl("")
        lay.addWidget(self._connected_ip_lbl)
        lay.addSpacing(24)
        lay.addWidget(self._primary_btn("Super, fermer  ✓", self.accept))
        lay.addStretch()
        return w

    # 2 — P_CABLES
    def _pg_cables(self):
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("🔌"))
        lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Branchons le boîtier"))
        lay.addSpacing(4)
        lay.addWidget(self._sub_lbl("Vérifiez que les 2 connexions sont bien faites"))
        lay.addSpacing(14)
        lay.addWidget(self._card(
            "🔵", "Câble RJ45 (Ethernet)",
            "Entre le boîtier et l'ordinateur  —  données DMX",
            accent="#00d4ff"
        ))
        lay.addSpacing(8)
        lay.addWidget(self._card(
            "🔴", "Alimentation",
            "Port USB carré (USB-B) ou USB Type-C selon le modèle\n"
            "Prise secteur ou port USB de l'ordinateur",
            accent="#f87171"
        ))
        lay.addSpacing(16)
        lay.addWidget(self._step_indicator(0))
        lay.addSpacing(14)
        lay.addWidget(self._primary_btn("Les 2 sont branchés  →", self._start_adapter_scan))
        return w

    # 3 — P_ADAPTERS
    def _pg_adapters(self):
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("🌐"))
        lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Quelle carte réseau ?"))
        lay.addSpacing(4)
        lay.addWidget(self._sub_lbl(
            "Choisissez la carte RJ45 reliée au boîtier\n"
            "(pas la Wi-Fi, pas la carte Internet)"
        ))
        lay.addSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { background: #1e1e1e; width: 6px; border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 3px; }"
        )
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._adapters_layout = QVBoxLayout(inner)
        self._adapters_layout.setSpacing(6)
        self._adapters_layout.setContentsMargins(0, 0, 0, 0)
        self._adapters_layout.addStretch()

        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        lay.addSpacing(12)
        lay.addWidget(self._step_indicator(1))
        lay.addSpacing(12)

        self._btn_net_suivant = QPushButton("Continuer  →")
        self._btn_net_suivant.setStyleSheet(_BTN_PRIMARY)
        self._btn_net_suivant.setFixedHeight(42)
        self._btn_net_suivant.setEnabled(False)
        self._btn_net_suivant.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_net_suivant.clicked.connect(self._on_net_suivant)
        lay.addWidget(self._btn_net_suivant)
        return w

    # 4 — P_IP_METHOD
    def _pg_ip_method(self):
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("⚙️"))
        lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Configuration IP"))
        lay.addSpacing(12)

        # Info card
        info_frame = QFrame()
        info_frame.setStyleSheet(
            "QFrame { background: #222222; border: 1px solid #333333; border-radius: 8px; }"
        )
        info_lay = QVBoxLayout(info_frame)
        info_lay.setContentsMargins(16, 12, 16, 12)
        info_lay.setSpacing(4)

        self._ip_method_adapter_lbl = QLabel()
        self._ip_method_adapter_lbl.setFont(QFont("Segoe UI", 10))
        self._ip_method_adapter_lbl.setStyleSheet(
            "color: #666666; background: transparent; border: none;"
        )
        self._ip_method_adapter_lbl.setAlignment(Qt.AlignCenter)
        info_lay.addWidget(self._ip_method_adapter_lbl)

        ip_target = QLabel("IP cible :  2.0.0.1  /  255.0.0.0")
        ip_target.setFont(QFont("Segoe UI", 11, QFont.Bold))
        ip_target.setStyleSheet("color: #00d4ff; background: transparent; border: none;")
        ip_target.setAlignment(Qt.AlignCenter)
        info_lay.addWidget(ip_target)

        lay.addWidget(info_frame)
        lay.addSpacing(10)

        admin_note = QLabel(
            "ⓘ  Droits administrateur requis pour la configuration auto"
        )
        admin_note.setFont(QFont("Segoe UI", 9))
        admin_note.setWordWrap(True)
        admin_note.setStyleSheet("color: #444444; background: transparent;")
        admin_note.setAlignment(Qt.AlignCenter)
        lay.addWidget(admin_note)

        lay.addSpacing(16)
        lay.addWidget(self._step_indicator(2))
        lay.addSpacing(14)
        lay.addWidget(self._primary_btn("Configurer automatiquement  ✓", self._do_auto_config))
        lay.addSpacing(8)
        lay.addWidget(self._secondary_btn("Je configure moi-même", self._show_manual_from_method))
        return w

    # 5 — P_WORKING
    def _pg_working(self):
        w, lay = self._make_page()
        lay.addStretch()
        self._work_spin_lbl = QLabel("◐")
        self._work_spin_lbl.setFont(QFont("Segoe UI", 48))
        self._work_spin_lbl.setStyleSheet("color: #00d4ff; background: transparent;")
        self._work_spin_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._work_spin_lbl)
        lay.addSpacing(12)
        self._work_status_lbl = QLabel("")
        self._work_status_lbl.setFont(QFont("Segoe UI", 11))
        self._work_status_lbl.setStyleSheet("color: #888888; background: transparent;")
        self._work_status_lbl.setWordWrap(True)
        self._work_status_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._work_status_lbl)
        lay.addSpacing(6)
        self._work_detail_lbl = QLabel("")
        self._work_detail_lbl.setFont(QFont("Segoe UI", 9))
        self._work_detail_lbl.setStyleSheet("color: #444444; background: transparent;")
        self._work_detail_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._work_detail_lbl)
        lay.addStretch()
        return w

    # 6 — P_IP_MANUAL
    def _pg_ip_manual(self):
        w, lay = self._make_page()
        lay.addWidget(self._big_icon("📋"))
        lay.addSpacing(8)
        lay.addWidget(self._title_lbl("Configuration manuelle"))
        lay.addSpacing(6)
        self._manual_ctx_lbl = self._sub_lbl("")
        lay.addWidget(self._manual_ctx_lbl)
        lay.addSpacing(12)

        steps_frame = QFrame()
        steps_frame.setStyleSheet(
            "QFrame { background: #222222; border: 1px solid #333333; "
            "border-radius: 8px; padding: 14px; }"
        )
        steps_lay = QVBoxLayout(steps_frame)
        steps_lay.setContentsMargins(14, 10, 14, 10)
        self._manual_steps_lbl = QLabel()
        self._manual_steps_lbl.setFont(QFont("Segoe UI", 10))
        self._manual_steps_lbl.setStyleSheet(
            "color: #cccccc; background: transparent; border: none;"
        )
        self._manual_steps_lbl.setWordWrap(True)
        steps_lay.addWidget(self._manual_steps_lbl)
        lay.addWidget(steps_frame)

        lay.addSpacing(8)
        lay.addWidget(self._secondary_btn(
            "📂  Ouvrir les connexions réseau", _open_network_connections
        ))
        lay.addSpacing(4)
        lay.addWidget(self._secondary_btn(
            "🔑  Relancer en administrateur", self._restart_as_admin
        ))
        lay.addSpacing(12)
        lay.addWidget(self._step_indicator(2))
        lay.addSpacing(12)
        lay.addWidget(self._primary_btn(
            "J'ai configuré  →  Tester la connexion", self._start_final_search
        ))
        return w

    # 7 — P_SUCCESS
    def _pg_success(self):
        w, lay = self._make_page()
        lay.addStretch()
        lay.addWidget(self._big_icon("🎉", "#4ade80"))
        lay.addSpacing(12)
        lay.addWidget(self._title_lbl("Connexion établie !"))
        lay.addSpacing(8)
        self._success_sub_lbl = self._sub_lbl(
            "Votre boîtier est prêt à recevoir les données DMX."
        )
        lay.addWidget(self._success_sub_lbl)
        lay.addSpacing(20)
        lay.addWidget(self._step_indicator(3))
        lay.addSpacing(20)
        lay.addWidget(self._primary_btn("Super, fermer  ✓", self.accept))
        lay.addStretch()
        return w

    # ──────────────────────────────────────────────────────
    # NAVIGATION
    # ──────────────────────────────────────────────────────

    def _go_to(self, page: int):
        self._stack.setCurrentIndex(page)
        self._btn_back.setVisible(page in {P_ADAPTERS, P_IP_METHOD, P_IP_MANUAL})

    def _on_back(self):
        page = self._stack.currentIndex()
        if page == P_ADAPTERS:
            self._go_to(P_CABLES)
        elif page == P_IP_METHOD:
            self._go_to(P_ADAPTERS)
        elif page == P_IP_MANUAL:
            self._go_to(P_IP_METHOD if self._net_came_from_method else P_ADAPTERS)

    # ──────────────────────────────────────────────────────
    # SPINNER
    # ──────────────────────────────────────────────────────

    def _tick(self):
        self._spin_idx = (self._spin_idx + 1) % len(self._spin_frames)
        f = self._spin_frames[self._spin_idx]
        p = self._stack.currentIndex()
        if p == P_DETECTING:
            self._spin_lbl.setText(f)
        elif p == P_WORKING:
            self._work_spin_lbl.setText(f)

    def _set_working(self, status: str, detail: str = ""):
        self._work_status_lbl.setText(status)
        self._work_detail_lbl.setText(detail)
        self._go_to(P_WORKING)
        self._spin_timer.start(180)

    def _stop_spinner(self):
        self._spin_timer.stop()

    # ──────────────────────────────────────────────────────
    # STEP 1 — QUICK DETECTION
    # ──────────────────────────────────────────────────────

    def _start_quick_detection(self):
        self._go_to(P_DETECTING)
        self._spin_timer.start(180)
        self._q_detect = QuickDetector(target_ip=self._configured_ip)
        self._q_detect.finished.connect(self._on_quick_done)
        self._q_detect.start()

    def _on_quick_done(self, found: bool):
        self._stop_spinner()
        if found:
            self._connected_ip_lbl.setText(f"Adresse IP : {TARGET_IP}")
            self._go_to(P_CONNECTED)
        else:
            self._go_to(P_CABLES)

    # ──────────────────────────────────────────────────────
    # STEP 2 — ADAPTER SCAN
    # ──────────────────────────────────────────────────────

    def _start_adapter_scan(self):
        self._set_working("Scan des cartes réseau...", "Recherche des adaptateurs Ethernet")
        self._adapter_scan = AdapterScanner()
        self._adapter_scan.done.connect(self._on_adapters_scanned)
        self._adapter_scan.start()

    def _on_adapters_scanned(self, adapters: list):
        # clear adapters_layout (keep stretch at end)
        while self._adapters_layout.count() > 1:
            item = self._adapters_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self._adapter_buttons.clear()
        self._selected_adapter_name = ""
        self._selected_adapter_ip = ""
        self._btn_net_suivant.setEnabled(False)

        if not adapters:
            lbl = QLabel("Aucune carte Ethernet détectée.\nVérifiez que le câble RJ45 est bien branché.")
            lbl.setStyleSheet(
                "color: #fbbf24; background: #2a2000; border: 1px solid #554400; "
                "border-radius: 6px; padding: 12px;"
            )
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignCenter)
            self._adapters_layout.insertWidget(0, lbl)
        else:
            for i, (name, ip) in enumerate(adapters):
                already_ok = ip.startswith("2.0.0.")
                ip_display = ip if ip else "IP non configurée"
                if already_ok:
                    txt = f"  {name}\n  {ip_display}   ✓  déjà configurée pour le Node"
                    style = _BTN_ADAPTER_OK
                else:
                    txt = f"  {name}\n  IP actuelle : {ip_display}"
                    style = _BTN_ADAPTER
                btn = QPushButton(txt)
                btn.setStyleSheet(style)
                btn.setFixedHeight(58)
                btn.setCursor(QCursor(Qt.PointingHandCursor))
                btn.clicked.connect(lambda _, n=name, curr_ip=ip: self._select_adapter(n, curr_ip))
                self._adapters_layout.insertWidget(i, btn)
                self._adapter_buttons.append((btn, name, ip))

        self._stop_spinner()
        self._go_to(P_ADAPTERS)

    def _select_adapter(self, name: str, ip: str):
        self._selected_adapter_name = name
        self._selected_adapter_ip = ip
        for btn, n, _ in self._adapter_buttons:
            btn.setStyleSheet(_BTN_ADAPTER_SEL if n == name else _BTN_ADAPTER)
        self._btn_net_suivant.setEnabled(True)

    def _on_net_suivant(self):
        self._on_adapter_selected(self._selected_adapter_name, self._selected_adapter_ip)

    # ──────────────────────────────────────────────────────
    # STEP 3 — ADAPTER SELECTED, IP CHECK
    # ──────────────────────────────────────────────────────

    def _on_adapter_selected(self, adapter_name: str, current_ip: str):
        self._adapter_name = adapter_name
        if current_ip.startswith("2.0.0."):
            self._set_working("IP déjà configurée ✓", f"Recherche du boîtier sur {TARGET_IP}...")
            self._start_final_search()
        else:
            ip_display = current_ip if current_ip else "non configurée"
            self._ip_method_adapter_lbl.setText(
                f"Carte : « {adapter_name} »  —  IP actuelle : {ip_display}"
            )
            self._net_came_from_method = False
            self._go_to(P_IP_METHOD)

    # ──────────────────────────────────────────────────────
    # STEP 4A — AUTO CONFIG
    # ──────────────────────────────────────────────────────

    def _do_auto_config(self):
        self._set_working(
            "Configuration en cours...",
            f"Application de 2.0.0.1 sur « {self._adapter_name} »..."
        )
        self._net_setup = NetworkSetup(self._adapter_name)
        self._net_setup.done.connect(self._on_network_done)
        self._net_setup.start()

    def _on_network_done(self, status: str, adapter: str):
        self._adapter_name = adapter
        if status == "ok":
            self._start_final_search()
            return
        self._stop_spinner()
        self._net_came_from_method = True
        self._show_net_manual(adapter, status)

    # ──────────────────────────────────────────────────────
    # STEP 4B — MANUAL CONFIG
    # ──────────────────────────────────────────────────────

    def _show_manual_from_method(self):
        self._net_came_from_method = True
        self._show_net_manual(self._adapter_name, "manual")

    def _show_net_manual(self, adapter: str, status: str = "manual"):
        adapter_label = f"« {adapter} »" if adapter else "votre carte Ethernet"
        if status == "manual":
            ctx = (
                f"Droits insuffisants sur {adapter_label}.\n"
                "Configurez manuellement ou relancez en administrateur."
            )
        elif status == "no_adapter":
            ctx = "Aucune carte Ethernet détectée. Vérifiez le câble RJ45."
        else:
            ctx = f"Carte : {adapter_label}"
        self._manual_ctx_lbl.setText(ctx)
        self._manual_steps_lbl.setText(
            f"1.  Clic droit sur {adapter_label}\n"
            "2.  Propriétés\n"
            "3.  TCP/IPv4  →  Propriétés\n"
            "4.  Adresse IP :          2 . 0 . 0 . 1\n"
            "    Masque :  255 . 0 . 0 . 0\n"
            "5.  OK  →  OK  →  Fermer"
        )
        self._go_to(P_IP_MANUAL)

    # ──────────────────────────────────────────────────────
    # STEP 5 — SEARCH NODE
    # ──────────────────────────────────────────────────────

    def _start_final_search(self):
        self._start_node_search()

    def _start_node_search(self):
        self._set_working("Recherche du boîtier DMX...", f"Envoi ArtPoll sur {self._configured_ip}...")
        self._node_srch = NodeSearcher(target_ip=self._configured_ip)
        self._node_srch.finished.connect(self._on_search_done)
        self._node_srch.start()

    def _on_search_done(self, found: bool):
        self._stop_spinner()
        if found:
            self._go_to(P_SUCCESS)
        else:
            adapter_label = f"« {self._adapter_name} »" if self._adapter_name else "votre carte Ethernet"
            self._manual_ctx_lbl.setText(
                f"Le boîtier n'a pas répondu sur {TARGET_IP}.\n"
                "Vérifiez qu'il est allumé et que le câble RJ45 est branché."
            )
            self._manual_steps_lbl.setText(
                f"1.  Clic droit sur {adapter_label}\n"
                "2.  Propriétés\n"
                "3.  TCP/IPv4  →  Propriétés\n"
                "4.  Adresse IP :          2 . 0 . 0 . 1\n"
                "    Masque :  255 . 0 . 0 . 0\n"
                "5.  OK  →  OK  →  Fermer"
            )
            self._net_came_from_method = True
            self._go_to(P_IP_MANUAL)

    # ──────────────────────────────────────────────────────
    # ADMIN RESTART
    # ──────────────────────────────────────────────────────

    def _restart_as_admin(self):
        import sys, ctypes
        try:
            exe = sys.executable
            args = " ".join(f'"{a}"' for a in sys.argv)
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────
    # CLEANUP
    # ──────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._spin_timer.stop()
        for t in (self._q_detect, self._adapter_scan, self._net_setup, self._node_srch):
            if t and t.isRunning():
                t.quit()
                t.wait(300)
        super().closeEvent(event)
