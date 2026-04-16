"""
Assistant guidé de configuration de la sortie DMX.
Colonne gauche : sélection du matériel.
Colonne droite : 3 étapes guidées (connecter → diagnostiquer → activer).
"""
import socket as _sock

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem,
    QStackedWidget, QApplication, QWidget, QFrame, QTextEdit,
)
from PySide6.QtGui import QFont, QColor
from PySide6.QtCore import Qt

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

from artnet_dmx import TRANSPORT_ENTTEC, TRANSPORT_ARTNET

# ---------------------------------------------------------------------------
# Catalogue de produits compatibles
# ---------------------------------------------------------------------------

PRODUCTS = [
    # ── USB / Série ────────────────────────────────────────────────────────
    {
        "id":        "enttec_open",
        "name":      "ENTTEC Open DMX USB",
        "transport": TRANSPORT_ENTTEC,
        "info":      "Adaptateur passif — puce FTDI FT232R",
        "step1":     "Branchez le boîtier ENTTEC sur un port USB de votre ordinateur.",
    },
    {
        "id":        "dmxking_micro",
        "name":      "DMXKing UltraDMX Micro",
        "transport": TRANSPORT_ENTTEC,
        "info":      "Compact, compatible FTDI",
        "step1":     "Branchez le boîtier DMXKing sur un port USB.",
    },
    {
        "id":        "eurolite_usb",
        "name":      "Eurolite USB-DMX512 PRO",
        "transport": TRANSPORT_ENTTEC,
        "info":      "Interface USB-DMX512",
        "step1":     "Branchez l'interface Eurolite sur un port USB.",
    },
    {
        "id":        "generic_usb",
        "name":      "Interface USB-DMX générique",
        "transport": TRANSPORT_ENTTEC,
        "info":      "Tout adaptateur USB-série DMX (FTDI ou clone)",
        "step1":     "Branchez votre interface USB-DMX sur un port USB.",
    },
    # ── Réseau Art-Net ─────────────────────────────────────────────────────
    {
        "id":        "electroconcept",
        "name":      "ElectroConcept Node",
        "transport": TRANSPORT_ARTNET,
        "info":      "IP par défaut : 2.0.0.15",
        "step1":     "Reliez le boîtier ElectroConcept à votre ordinateur\nvia un câble Ethernet (direct ou switch).",
        "defaults":  {"target_ip": "2.0.0.15", "target_port": 6454, "universe": 0},
    },
    {
        "id":        "chauvet_an2",
        "name":      "Chauvet DMX-AN2",
        "transport": TRANSPORT_ARTNET,
        "info":      "Convertisseur Art-Net 2 univers — IP par défaut : 2.0.0.1",
        "step1":     "Reliez le Chauvet DMX-AN2 à votre ordinateur\nvia un câble Ethernet (direct ou switch).",
        "defaults":  {"target_ip": "2.0.0.1", "target_port": 6454, "universe": 0},
    },
    {
        "id":        "enttec_ode",
        "name":      "ENTTEC ODE MkII",
        "transport": TRANSPORT_ARTNET,
        "info":      "Open DMX Ethernet — IP par défaut : 192.168.1.78",
        "step1":     "Reliez l'ENTTEC ODE à votre réseau Ethernet.",
        "defaults":  {"target_ip": "192.168.1.78", "target_port": 6454, "universe": 0},
    },
    {
        "id":        "chamsys",
        "name":      "Chamsys Ethernet Node",
        "transport": TRANSPORT_ARTNET,
        "info":      "IP par défaut : 2.0.0.1",
        "step1":     "Reliez le node Chamsys à votre réseau Ethernet.",
        "defaults":  {"target_ip": "2.0.0.1", "target_port": 6454, "universe": 0},
    },
    {
        "id":        "luminex",
        "name":      "Luminex GigaCore / Araneo",
        "transport": TRANSPORT_ARTNET,
        "info":      "IP par défaut : 2.0.0.1",
        "step1":     "Reliez le boîtier Luminex à votre réseau Ethernet.",
        "defaults":  {"target_ip": "2.0.0.1", "target_port": 6454, "universe": 0},
    },
    {
        "id":        "generic_artnet",
        "name":      "Node Art-Net générique",
        "transport": TRANSPORT_ARTNET,
        "info":      "Tout node Art-Net standard (port 6454)",
        "step1":     "Reliez votre node Art-Net à votre réseau Ethernet.",
        "defaults":  {"target_ip": "2.0.0.1", "target_port": 6454, "universe": 0},
    },
]

_BY_ID = {p["id"]: p for p in PRODUCTS}


def product_by_id(pid):
    return _BY_ID.get(pid)


# ---------------------------------------------------------------------------
# Styles partagés
# ---------------------------------------------------------------------------

_FIELD = (
    "QLineEdit { background: #242424; color: white; border: 1px solid #2e2e2e;"
    " border-radius: 4px; padding: 0 8px; font-size: 11px; min-height: 26px; }"
    "QLineEdit:focus { border: 1px solid #00d4ff; }"
)
_COMBO = (
    "QComboBox { background: #242424; color: white; border: 1px solid #2e2e2e;"
    " border-radius: 4px; padding: 0 8px; font-size: 11px; min-height: 26px; }"
    "QComboBox::drop-down { border: none; width: 18px; }"
    "QComboBox QAbstractItemView { background: #242424; color: white;"
    " border: 1px solid #2e2e2e; selection-background-color: #1e3a4a; }"
)
_LOG_STYLE = (
    "QTextEdit { background: #0d0d0d; color: #cccccc; border: 1px solid #1e1e1e;"
    " border-radius: 4px; font-family: Consolas, monospace; font-size: 10px; }"
)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class DmxSetupDialog(QDialog):
    """Assistant de configuration de la sortie DMX"""

    def __init__(self, dmx, parent=None):
        super().__init__(parent)
        self._dmx = dmx
        self._parent_win = parent
        self.setWindowTitle("Sortie DMX — Configuration")
        self.setFixedSize(680, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel  { color: #cccccc; border: none; background: transparent; }
            QListWidget {
                background: #141414; border: none; outline: none;
            }
            QListWidget::item {
                color: #999; padding: 7px 14px;
                border-radius: 4px; margin: 1px 4px;
            }
            QListWidget::item:selected  { background: #1e3a4a; color: white; }
            QListWidget::item:hover:!selected { background: #1c1c1c; color: #ccc; }
        """)
        self._build_ui()
        self._refresh_ports()
        self._restore_selection()

    # ── Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tête
        hdr = QWidget()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet("background: #0f0f0f;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        lbl = QLabel("Sortie DMX — Configuration")
        lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl.setStyleSheet("color: #00d4ff;")
        hl.addWidget(lbl)
        root.addWidget(hdr)

        # Corps
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._make_left())
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("border: none; border-left: 1px solid #1e1e1e;")
        body.addWidget(sep)
        body.addWidget(self._make_right(), 1)
        root.addLayout(body, 1)

    # ── Colonne gauche ───────────────────────────────────────────────────────

    def _make_left(self):
        w = QWidget()
        w.setFixedWidth(195)
        w.setStyleSheet("background: #141414;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(0)

        hint = QLabel("  Votre interface DMX")
        hint.setFont(QFont("Segoe UI", 8))
        hint.setStyleSheet("color: #3a3a3a; padding: 0 8px 6px 8px;")
        lay.addWidget(hint)

        self.product_list = QListWidget()
        self.product_list.setFocusPolicy(Qt.NoFocus)
        self.product_list.setFont(QFont("Segoe UI", 10))
        self._fill_product_list()
        self.product_list.currentItemChanged.connect(self._on_product_changed)
        lay.addWidget(self.product_list)
        return w

    def _fill_product_list(self):
        self._id_to_item = {}

        def _header(text):
            item = QListWidgetItem(text)
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(QColor("#00d4ff"))
            f = item.font()
            f.setBold(True)
            f.setPointSize(8)
            item.setFont(f)
            self.product_list.addItem(item)

        def _item(prod):
            item = QListWidgetItem("  " + prod["name"])
            item.setData(Qt.UserRole, prod["id"])
            self.product_list.addItem(item)
            self._id_to_item[prod["id"]] = item

        _header("  USB / Série")
        for p in PRODUCTS:
            if p["transport"] == TRANSPORT_ENTTEC:
                _item(p)

    def _restore_selection(self):
        pid = self._dmx.product_id
        item = self._id_to_item.get(pid)
        if item:
            self.product_list.setCurrentItem(item)
        elif self._id_to_item:
            self.product_list.setCurrentItem(next(iter(self._id_to_item.values())))

    # ── Colonne droite : assistant ───────────────────────────────────────────

    def _make_right(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 18, 26, 16)
        lay.setSpacing(0)

        # Nom + info produit
        self.lbl_name = QLabel("—")
        self.lbl_name.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_name.setStyleSheet("color: white;")
        lay.addWidget(self.lbl_name)

        self.lbl_info = QLabel("")
        self.lbl_info.setFont(QFont("Segoe UI", 9))
        self.lbl_info.setStyleSheet("color: #444;")
        lay.addWidget(self.lbl_info)

        lay.addSpacing(10)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: 1px solid #222;")
        lay.addWidget(sep)
        lay.addSpacing(10)

        # ── Étape 1 ──────────────────────────────────────────────────────────
        lay.addLayout(self._step_hdr("1", "Connectez le matériel"))
        lay.addSpacing(4)

        self.lbl_step1 = QLabel("")
        self.lbl_step1.setWordWrap(True)
        self.lbl_step1.setFont(QFont("Segoe UI", 9))
        self.lbl_step1.setStyleSheet("color: #666; margin-left: 26px; margin-bottom: 6px;")
        lay.addWidget(self.lbl_step1)

        # Zone de config USB ou Art-Net
        self.stack = QStackedWidget()
        self.stack.addWidget(self._make_usb_panel())     # 0
        self.stack.addWidget(self._make_artnet_panel())  # 1
        lay.addWidget(self.stack)

        lay.addSpacing(12)

        # ── Étape 2 : DIAGNOSTIC ─────────────────────────────────────────────
        hdr2 = self._step_hdr("2", "DIAGNOSTIC")
        lay.addLayout(hdr2)
        lay.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(26, 0, 0, 0)

        self.btn_diag = QPushButton("▶  Lancer le diagnostic")
        self.btn_diag.setFixedSize(160, 28)
        self.btn_diag.setStyleSheet(
            "QPushButton { background: #1e2a3a; color: #00d4ff; border: 1px solid #00d4ff;"
            " border-radius: 4px; font-size: 10px; font-weight: bold; }"
            "QPushButton:hover { background: #243040; }"
            "QPushButton:disabled { color: #444; border-color: #333; background: #1a1a1a; }"
        )
        self.btn_diag.clicked.connect(self._run_diag)
        btn_row.addWidget(self.btn_diag)

        self._diag_hint = QLabel("USB uniquement — teste port, break et envoi")
        self._diag_hint.setFont(QFont("Segoe UI", 8))
        self._diag_hint.setStyleSheet("color: #444; margin-left: 8px;")
        btn_row.addWidget(self._diag_hint, 1)
        lay.addLayout(btn_row)

        lay.addSpacing(6)

        # Zone de sortie du diagnostic
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(140)
        self._log.setStyleSheet(_LOG_STYLE)
        self._log.setPlaceholderText("Les résultats du diagnostic s'affichent ici…")
        lay.addWidget(self._log)

        copy_row = QHBoxLayout()
        copy_row.setContentsMargins(0, 2, 0, 0)
        copy_row.addStretch()
        btn_copy = QPushButton("📋  Copier le rapport")
        btn_copy.setFixedHeight(22)
        btn_copy.setStyleSheet(
            "QPushButton { background: #1a1a1a; color: #555; border: 1px solid #2a2a2a;"
            " border-radius: 3px; padding: 0 10px; font-size: 9px; }"
            "QPushButton:hover { color: #ccc; border-color: #444; }"
        )
        btn_copy.clicked.connect(self._copy_report)
        copy_row.addWidget(btn_copy)
        lay.addLayout(copy_row)

        lay.addSpacing(12)

        # ── Étape 3 ──────────────────────────────────────────────────────────
        lay.addLayout(self._step_hdr("3", "Utiliser cette interface DMX"))
        lay.addSpacing(6)

        row3 = QHBoxLayout()
        row3.setContentsMargins(26, 0, 0, 0)
        self.btn_connect = QPushButton("Connecter")
        self.btn_connect.setFixedSize(100, 32)
        self.btn_connect.setStyleSheet(
            "QPushButton { background: #1e4a1e; color: #4CAF50; border: 1px solid #4CAF50;"
            " border-radius: 4px; font-weight: bold; font-size: 10px; }"
            "QPushButton:hover { background: #255525; }"
        )
        self.btn_connect.clicked.connect(self._connect)
        row3.addWidget(self.btn_connect)
        self.lbl_connect = QLabel("")
        self.lbl_connect.setFont(QFont("Segoe UI", 9))
        self.lbl_connect.setWordWrap(True)
        row3.addWidget(self.lbl_connect, 1)
        lay.addLayout(row3)

        lay.addStretch()

        # Fermer
        footer = QHBoxLayout()
        footer.addStretch()
        btn_close = QPushButton("Fermer")
        btn_close.setFixedHeight(28)
        btn_close.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #777; border: 1px solid #2a2a2a;"
            " border-radius: 4px; padding: 0 14px; font-size: 10px; }"
            "QPushButton:hover { color: white; background: #252525; }"
        )
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        lay.addLayout(footer)

        return w

    def _step_hdr(self, num, text):
        row = QHBoxLayout()
        badge = QLabel(num)
        badge.setFixedSize(18, 18)
        badge.setAlignment(Qt.AlignCenter)
        badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
        badge.setStyleSheet(
            "background: #00d4ff; color: #000; border-radius: 9px;"
        )
        row.addWidget(badge)
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl.setStyleSheet("color: #cccccc; margin-left: 6px;")
        row.addWidget(lbl)
        row.addStretch()
        return row

    # ── Panneaux de config ───────────────────────────────────────────────────

    def _make_usb_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 0, 0, 0)
        lay.setSpacing(5)

        row = QHBoxLayout()
        lbl = QLabel("Port COM :")
        lbl.setFont(QFont("Segoe UI", 10))
        lbl.setFixedWidth(72)
        row.addWidget(lbl)
        self.port_combo = QComboBox()
        self.port_combo.setStyleSheet(_COMBO)
        row.addWidget(self.port_combo, 1)
        btn_r = QPushButton("↻")
        btn_r.setFixedSize(26, 26)
        btn_r.setToolTip("Rafraîchir les ports")
        btn_r.setStyleSheet(
            "QPushButton { background: #1e1e1e; color: #777; border: 1px solid #2a2a2a;"
            " border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { color: white; }"
        )
        btn_r.clicked.connect(self._refresh_ports)
        row.addWidget(btn_r)
        lay.addLayout(row)

        self.lbl_port_hint = QLabel("")
        self.lbl_port_hint.setFont(QFont("Segoe UI", 8))
        self.lbl_port_hint.setStyleSheet("color: #3a3a3a;")
        lay.addWidget(self.lbl_port_hint)
        return w

    def _make_artnet_panel(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(26, 0, 0, 0)
        lay.setSpacing(5)

        def _row(label_text, attr, default, width=None):
            r = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFont(QFont("Segoe UI", 10))
            lbl.setFixedWidth(80)
            r.addWidget(lbl)
            edit = QLineEdit(str(default))
            edit.setStyleSheet(_FIELD)
            if width:
                edit.setFixedWidth(width)
                r.addWidget(edit)
                r.addStretch()
            else:
                r.addWidget(edit, 1)
            lay.addLayout(r)
            setattr(self, attr, edit)

        _row("Adresse IP :", "ip_edit",   "2.0.0.1")
        _row("Port :",       "port_edit",  6454,    width=72)
        _row("Univers :",    "univ_edit",  0,       width=56)
        return w

    # ── Événements ──────────────────────────────────────────────────────────

    def _on_product_changed(self, current, _prev):
        if not current:
            return
        pid = current.data(Qt.UserRole)
        if not pid:
            return
        prod = product_by_id(pid)
        if not prod:
            return

        self.lbl_name.setText(prod["name"])
        self.lbl_info.setText(prod.get("info", ""))
        self.lbl_step1.setText(prod.get("step1", ""))
        self.lbl_connect.setText("")
        self._log.clear()

        is_usb = (prod["transport"] == TRANSPORT_ENTTEC)
        if is_usb:
            self.stack.setCurrentIndex(0)
            self.btn_diag.setEnabled(True)
            self._diag_hint.setText("Teste port, break signal et envoi DMX")
        else:
            self.stack.setCurrentIndex(1)
            self.btn_diag.setEnabled(False)
            self._diag_hint.setText("Diagnostic disponible pour les interfaces USB uniquement")
            d = prod.get("defaults", {})
            self.ip_edit.setText(str(d.get("target_ip",   self._dmx.target_ip)))
            self.port_edit.setText(str(d.get("target_port", self._dmx.target_port)))
            self.univ_edit.setText(str(d.get("universe",    self._dmx.universe)))

    def _current_product(self):
        item = self.product_list.currentItem()
        if not item:
            return None
        return product_by_id(item.data(Qt.UserRole))

    def _refresh_ports(self):
        self.port_combo.clear()
        if not SERIAL_AVAILABLE:
            self.port_combo.addItem("pyserial non installé")
            self.lbl_port_hint.setText("pip install pyserial")
            return

        ports = list(serial.tools.list_ports.comports())
        enttec = [p for p in ports if getattr(p, 'vid', None) == 0x0403]
        others = [p for p in ports if getattr(p, 'vid', None) != 0x0403]

        for p in enttec:
            self.port_combo.addItem(f"{p.device}  ★  {p.description}", userData=p.device)
        for p in others:
            self.port_combo.addItem(f"{p.device}  —  {p.description}", userData=p.device)

        if not ports:
            self.port_combo.addItem("Aucun port détecté")
            self.lbl_port_hint.setText("Branchez le boîtier puis ↻")
        elif enttec:
            self.lbl_port_hint.setText(f"{len(enttec)} boîtier(s) FTDI détecté(s) ★")
        else:
            self.lbl_port_hint.setText("Sélectionnez le port manuellement")

        if self._dmx.com_port:
            for i in range(self.port_combo.count()):
                if self.port_combo.itemData(i) == self._dmx.com_port:
                    self.port_combo.setCurrentIndex(i)
                    break

    # ── DIAGNOSTIC ──────────────────────────────────────────────────────────

    def _log_line(self, text, color="#cccccc"):
        self._log.append(f'<span style="color:{color};">{text}</span>')
        QApplication.processEvents()

    def _run_diag(self):
        """Diagnostic complet de la sortie DMX USB."""
        import time as _time
        self._log.clear()
        self.btn_diag.setEnabled(False)
        QApplication.processEvents()

        ok   = "#4CAF50"
        warn = "#ff9800"
        err  = "#f44336"
        dim  = "#555555"
        cyan = "#00d4ff"

        self._log_line("═══ DIAGNOSTIC DMX USB ═══", cyan)

        # ── 1. Bibliothèque pyserial ─────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 1 ] Bibliothèque pyserial", cyan)
        if not SERIAL_AVAILABLE:
            self._log_line("  ✗  pyserial non installé", err)
            self._log_line("      → Exécutez : pip install pyserial", warn)
            self.btn_diag.setEnabled(True)
            return
        try:
            import serial as _s
            ver = getattr(_s, '__version__', '?')
        except Exception:
            ver = '?'
        self._log_line(f"  ✓  pyserial {ver} disponible", ok)

        # ── 2. Ports série détectés ──────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 2 ] Ports série disponibles", cyan)
        try:
            import serial.tools.list_ports as _lp
            all_ports = list(_lp.comports())
        except Exception as e:
            self._log_line(f"  ✗  Impossible de lister les ports : {e}", err)
            all_ports = []

        if not all_ports:
            self._log_line("  ✗  Aucun port série détecté", err)
            self._log_line("", dim)
            self._log_line("  Causes possibles :", warn)
            self._log_line("  • Boîtier USB-DMX non branché", dim)
            self._log_line("    → Branchez-le et cliquez ↻ pour relancer", dim)
            self._log_line("  • Pilote FTDI non installé (Windows)", dim)
            self._log_line("    → Ouvrez le Gestionnaire de périphériques (Win+X)", dim)
            self._log_line("    → Si vous voyez un ⚠ sous 'Autres périphériques'", dim)
            self._log_line("       le pilote est manquant — téléchargez-le :", dim)
            self._log_line("       ftdichip.com  →  Drivers  →  VCP Drivers  →  Windows", warn)
            self._log_line("    → Après installation, débranchez / rebranchez le boîtier", dim)
            self._log_line("  • Si le port apparaît en COM mais ne fonctionne pas :", dim)
            self._log_line("    → Vérifiez que ce n'est pas le pilote D2XX (mode direct)", dim)
            self._log_line("       Il faut le mode VCP (Virtual COM Port), pas D2XX", warn)
        else:
            for p in all_ports:
                vid = getattr(p, 'vid', None)
                pid_hw = getattr(p, 'pid', None)
                mfg = getattr(p, 'manufacturer', '') or ''
                desc = getattr(p, 'description', '') or ''
                vid_str = f"VID:{vid:04X}" if vid is not None else "VID:????"
                pid_str = f"PID:{pid_hw:04X}" if pid_hw is not None else "PID:????"
                is_ftdi = (vid == 0x0403)
                marker = "★ FTDI" if is_ftdi else "  "
                color = ok if is_ftdi else dim
                self._log_line(
                    f"  {marker}  {p.device}  —  {desc}  [{vid_str} {pid_str}]  {mfg}",
                    color
                )
        QApplication.processEvents()

        # ── 3. Port sélectionné ──────────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 3 ] Port sélectionné", cyan)
        port = self.port_combo.currentData()
        if not port:
            self._log_line("  ✗  Aucun port sélectionné dans la liste", err)
            self.btn_diag.setEnabled(True)
            return
        self._log_line(f"  →   {port}", "#cccccc")

        # Chercher les détails de ce port
        try:
            import serial.tools.list_ports as _lp
            port_info = next((p for p in _lp.comports() if p.device == port), None)
            if port_info:
                vid = getattr(port_info, 'vid', None)
                pid_hw = getattr(port_info, 'pid', None)
                if vid == 0x0403:
                    self._log_line(f"      Puce FTDI détectée (VID:0403 PID:{pid_hw:04X})", ok)
                    self._log_line("      Compatible ENTTEC Open DMX / DMXKing", ok)
                elif vid is not None:
                    self._log_line(f"      VID:{vid:04X} PID:{pid_hw:04X} — non-FTDI", warn)
                    self._log_line("      Peut fonctionner avec un clone CH340 ou CP210x", warn)
                else:
                    self._log_line("      VID/PID inconnu — vérifiez le pilote", warn)
        except Exception:
            pass

        # ── 4. Ouverture du port ─────────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 4 ] Ouverture à 250 000 bauds", cyan)

        # Vérifier si le port est déjà ouvert par MyStrow
        dmx_serial = getattr(self._dmx, '_serial', None)
        if dmx_serial and dmx_serial.is_open and getattr(dmx_serial, 'port', None) == port:
            self._log_line(f"  ⚠  Port déjà ouvert par MyStrow (connexion active)", warn)
            self._log_line("      Le test d'ouverture est ignoré — port en cours d'utilisation", dim)
            ser = None
            port_already_open = True
        else:
            port_already_open = False
            ser = None
            try:
                t0 = _time.perf_counter()
                ser = serial.Serial(
                    port=port, baudrate=250000,
                    bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_TWO, timeout=0.1,
                )
                elapsed = (_time.perf_counter() - t0) * 1000
                self._log_line(f"  ✓  Ouvert en {elapsed:.0f} ms", ok)
            except serial.SerialException as e:
                msg = str(e)
                self._log_line(f"  ✗  Échec ouverture : {msg}", err)
                if "access" in msg.lower() or "13" in msg or "permission" in msg.lower():
                    self._log_line("      → Port utilisé par une autre application", warn)
                    self._log_line("        Fermez tous les logiciels DMX et relancez", warn)
                elif "could not open" in msg.lower() or "no such" in msg.lower():
                    self._log_line("      → Port introuvable — rebranchez le boîtier", warn)
                self.btn_diag.setEnabled(True)
                return
            except Exception as e:
                self._log_line(f"  ✗  Erreur inattendue : {e}", err)
                self.btn_diag.setEnabled(True)
                return

        # ── 5. Test signal Break ─────────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 5 ] Signal Break DMX (176 µs)", cyan)
        if port_already_open:
            self._log_line("  –   Port occupé par MyStrow — test ignoré", dim)
        elif ser:
            try:
                ser.break_condition = True
                _time.sleep(0.000176)
                ser.break_condition = False
                self._log_line("  ✓  Break signal OK", ok)
            except AttributeError:
                try:
                    ser.send_break(duration=0.000176)
                    self._log_line("  ✓  Break signal OK (send_break)", ok)
                except Exception as e:
                    self._log_line(f"  ✗  Break signal échoué : {e}", err)
                    self._log_line("      → Pilote FTDI peut être manquant ou incorrect", warn)
            except Exception as e:
                self._log_line(f"  ✗  Break signal échoué : {e}", err)

        # ── 6. Envoi de frames DMX ───────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 6 ] Envoi 10 frames DMX (canaux 1-4 = 255)", cyan)
        if port_already_open:
            self._log_line("  –   Port occupé par MyStrow — test ignoré", dim)
            self._log_line("      MyStrow gère l'envoi en direct (voir étape 7)", dim)
        elif ser:
            test_data = bytearray(512)
            test_data[0] = 255   # CH1
            test_data[1] = 255   # CH2
            test_data[2] = 255   # CH3
            test_data[3] = 255   # CH4
            frame = b'\x00' + bytes(test_data)
            ok_count = 0
            last_err = ""
            for i in range(10):
                try:
                    ser.break_condition = True
                    _time.sleep(0.000176)
                    ser.break_condition = False
                    ser.write(frame)
                    ser.flush()
                    ok_count += 1
                except AttributeError:
                    try:
                        ser.send_break(duration=0.000176)
                        ser.write(frame)
                        ser.flush()
                        ok_count += 1
                    except Exception as e:
                        last_err = str(e)
                except Exception as e:
                    last_err = str(e)
                _time.sleep(0.04)

            if ok_count == 10:
                self._log_line(f"  ✓  10/10 frames envoyées — DMX opérationnel", ok)
                self._log_line("      Si les projecteurs ne répondent pas → vérifiez le patch", warn)
            elif ok_count > 0:
                self._log_line(f"  ⚠  {ok_count}/10 frames OK — connexion instable", warn)
                if last_err:
                    self._log_line(f"      Dernière erreur : {last_err[:60]}", err)
            else:
                self._log_line(f"  ✗  0/10 frames — envoi impossible", err)
                if last_err:
                    self._log_line(f"      Erreur : {last_err[:70]}", err)

            try:
                ser.close()
            except Exception:
                pass

        # ── 7. État live MyStrow ─────────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 7 ] État DMX live MyStrow", cyan)
        dmx = self._dmx
        transport_str = getattr(dmx, 'transport', '?')
        connected_str = "OUI" if getattr(dmx, 'connected', False) else "NON"
        com_str = getattr(dmx, 'com_port', None) or "—"
        conn_color = ok if getattr(dmx, 'connected', False) else err
        self._log_line(f"  Transport : {transport_str}", "#cccccc")
        self._log_line(f"  Port configuré : {com_str}", "#cccccc")
        self._log_line(f"  Connecté : {connected_str}", conn_color)

        # Timer DMX (25fps)
        timer_ok = False
        try:
            win = self._parent_win
            if win and hasattr(win, 'dmx_timer'):
                timer_ok = win.dmx_timer.isActive()
            elif win and hasattr(win, '_dmx_timer'):
                timer_ok = win._dmx_timer.isActive()
        except Exception:
            pass
        timer_color = ok if timer_ok else warn
        timer_str = "ACTIF (25 fps)" if timer_ok else "inactif ou inconnu"
        self._log_line(f"  Timer DMX : {timer_str}", timer_color)

        # Données DMX actuelles (univers 0, canaux 1-10)
        try:
            uni0 = dmx.dmx_data[0] if dmx.dmx_data else []
            if uni0:
                vals = "  ".join(f"CH{i+1}={uni0[i]}" for i in range(10))
                self._log_line(f"  Univers 0 canaux 1-10 :", "#cccccc")
                self._log_line(f"    {vals}", "#888888")
                non_zero = sum(1 for v in uni0[:512] if v > 0)
                if non_zero == 0:
                    self._log_line("  ⚠  Tous les canaux sont à 0 — aucune lumière active", warn)
                else:
                    self._log_line(f"  ✓  {non_zero} canaux non-nuls dans l'univers 0", ok)
        except Exception as e:
            self._log_line(f"  Impossible de lire dmx_data : {e}", err)

        self._log_line("")
        self._log_line("═══ FIN DU DIAGNOSTIC ═══", cyan)
        self.btn_diag.setEnabled(True)

    def _copy_report(self):
        """Copie le rapport de diagnostic dans le presse-papiers en texte brut."""
        text = self._log.toPlainText()
        if text.strip():
            QApplication.clipboard().setText(text)

    # ── Connexion ───────────────────────────────────────────────────────────

    def _connect(self):
        prod = self._current_product()
        if not prod:
            return
        self._set_connect("Connexion en cours…")
        QApplication.processEvents()

        kwargs = dict(
            transport=prod["transport"],
            product_id=prod["id"],
            product_name=prod["name"],
        )

        if prod["transport"] == TRANSPORT_ENTTEC:
            port = self.port_combo.currentData()
            if not port:
                self._set_connect("Sélectionnez un port COM valide", error=True)
                return
            kwargs["com_port"] = port
        else:
            ip = self.ip_edit.text().strip()
            try:
                port = int(self.port_edit.text().strip())
                uni  = int(self.univ_edit.text().strip())
            except ValueError:
                self._set_connect("Port ou univers invalide", error=True)
                return
            kwargs.update(target_ip=ip, target_port=port, universe=uni)

        if self._dmx.connect(**kwargs):
            self._set_connect(f"✓  {prod['name']} connecté", ok=True)
        else:
            self._set_connect("✗  Échec de la connexion", error=True)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _set_connect(self, text, ok=False, error=False):
        color = "#4CAF50" if ok else ("#f44336" if error else "#555")
        self.lbl_connect.setText(text)
        self.lbl_connect.setStyleSheet(f"color: {color};")


# Alias de compatibilité
EnttecSetupDialog = DmxSetupDialog
