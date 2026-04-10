"""
Assistant guidé de configuration de la sortie DMX.
Colonne gauche : sélection du matériel.
Colonne droite : 3 étapes guidées (connecter → tester → activer).
"""
import socket as _sock

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem,
    QStackedWidget, QApplication, QWidget, QFrame,
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


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class DmxSetupDialog(QDialog):
    """Assistant de configuration de la sortie DMX"""

    def __init__(self, dmx, parent=None):
        super().__init__(parent)
        self._dmx = dmx
        self.setWindowTitle("Sortie DMX — Configuration")
        self.setFixedSize(640, 450)
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

        spacer = QListWidgetItem("")
        spacer.setFlags(Qt.NoItemFlags)
        spacer.setSizeHint(spacer.sizeHint().__class__(0, 10))
        self.product_list.addItem(spacer)

        _header("  Réseau Art-Net")
        for p in PRODUCTS:
            if p["transport"] == TRANSPORT_ARTNET:
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

        lay.addSpacing(14)

        # ── Étape 2 ──────────────────────────────────────────────────────────
        lay.addLayout(self._step_hdr("2", "Testez la connexion"))
        lay.addSpacing(6)

        row2 = QHBoxLayout()
        row2.setContentsMargins(26, 0, 0, 0)
        self.btn_test = QPushButton("Tester")
        self.btn_test.setFixedSize(80, 28)
        self.btn_test.setStyleSheet(
            "QPushButton { background: #1e3a4a; color: #00d4ff; border: 1px solid #00d4ff;"
            " border-radius: 4px; font-size: 10px; }"
            "QPushButton:hover { background: #254a5a; }"
        )
        self.btn_test.clicked.connect(self._test)
        row2.addWidget(self.btn_test)
        self.lbl_test = QLabel("")
        self.lbl_test.setFont(QFont("Segoe UI", 9))
        self.lbl_test.setWordWrap(True)
        row2.addWidget(self.lbl_test, 1)
        lay.addLayout(row2)

        lay.addSpacing(14)

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

        lay.addSpacing(14)

        # ── Diagnostic ───────────────────────────────────────────────────────
        lay.addLayout(self._step_hdr("✦", "Diagnostic"))
        lay.addSpacing(6)

        row4 = QHBoxLayout()
        row4.setContentsMargins(26, 0, 0, 0)
        self.btn_diag = QPushButton("Envoyer 20 frames")
        self.btn_diag.setFixedSize(130, 28)
        self.btn_diag.setStyleSheet(
            "QPushButton { background: #2a2020; color: #aaa; border: 1px solid #444;"
            " border-radius: 4px; font-size: 10px; }"
            "QPushButton:hover { background: #333; color: white; }"
        )
        self.btn_diag.clicked.connect(self._run_diag)
        row4.addWidget(self.btn_diag)
        self.lbl_diag = QLabel("Testez l'envoi réel après connexion")
        self.lbl_diag.setFont(QFont("Segoe UI", 9))
        self.lbl_diag.setWordWrap(True)
        self.lbl_diag.setStyleSheet("color: #555;")
        row4.addWidget(self.lbl_diag, 1)
        lay.addLayout(row4)

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
        self.lbl_test.setText("")
        self.lbl_connect.setText("")

        if prod["transport"] == TRANSPORT_ENTTEC:
            self.stack.setCurrentIndex(0)
        else:
            self.stack.setCurrentIndex(1)
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

    # ── Test ────────────────────────────────────────────────────────────────

    def _test(self):
        prod = self._current_product()
        if not prod:
            return
        self._set_test("Test en cours…")
        QApplication.processEvents()
        if prod["transport"] == TRANSPORT_ENTTEC:
            self._test_usb()
        else:
            self._test_artnet()

    def _test_usb(self):
        port = self.port_combo.currentData()
        if not port:
            self._set_test("Sélectionnez un port COM valide", error=True)
            return
        if not SERIAL_AVAILABLE:
            self._set_test("pyserial non installé — pip install pyserial", error=True)
            return
        try:
            import serial as _s
            ser = _s.Serial(port=port, baudrate=250000,
                            bytesize=_s.EIGHTBITS, parity=_s.PARITY_NONE,
                            stopbits=_s.STOPBITS_TWO, timeout=0.5)
            ser.send_break(duration=0.001)
            ser.write(b'\x00' + bytes(512))
            ser.close()
            self._set_test(f"✓  {port} — boîtier opérationnel", ok=True)
        except Exception as e:
            self._set_test(f"✗  {port} — {e}", error=True)

    def _test_artnet(self):
        ip = self.ip_edit.text().strip()
        try:
            port = int(self.port_edit.text().strip())
            uni  = int(self.univ_edit.text().strip())
        except ValueError:
            self._set_test("Port ou univers invalide", error=True)
            return
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
            s.settimeout(1.5)
            # ArtPoll — le boîtier doit répondre avec ArtPollReply
            artpoll = b'Art-Net\x00\x00\x20\x00\x0e\x00\x00'
            s.sendto(artpoll, (ip, port))
            try:
                data, _ = s.recvfrom(512)
                s.close()
                if data[:8] == b'Art-Net\x00':
                    self._set_test(f"✓  Boîtier détecté sur {ip} — Art-Net opérationnel", ok=True)
                else:
                    self._set_test(f"Réponse inattendue depuis {ip}", error=True)
            except _sock.timeout:
                s.close()
                self._set_test(
                    f"Pas de réponse sur {ip} — vérifiez que le boîtier\nest allumé et connecté au réseau",
                    error=True,
                )
        except Exception as e:
            self._set_test(f"Erreur réseau : {e}", error=True)

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

    # ── Diagnostic ──────────────────────────────────────────────────────────

    def _run_diag(self):
        """Envoie 20 frames DMX directement sur le port sélectionné et compte les succès."""
        prod = self._current_product()
        if not prod:
            self.lbl_diag.setText("Sélectionnez un produit")
            self.lbl_diag.setStyleSheet("color: #f44336;")
            return

        if prod["transport"] != TRANSPORT_ENTTEC:
            self.lbl_diag.setText("Diagnostic USB uniquement")
            self.lbl_diag.setStyleSheet("color: #888;")
            return

        port = self.port_combo.currentData()
        if not port:
            self.lbl_diag.setText("Sélectionnez un port COM")
            self.lbl_diag.setStyleSheet("color: #f44336;")
            return

        if not SERIAL_AVAILABLE:
            self.lbl_diag.setText("pyserial non installé")
            self.lbl_diag.setStyleSheet("color: #f44336;")
            return

        self.lbl_diag.setText("Envoi en cours…")
        self.lbl_diag.setStyleSheet("color: #888;")
        QApplication.processEvents()

        import time as _time
        import serial as _s

        ok_count = 0
        err_msg = ""
        # Frame de test : tous canaux à 127 (50% — allume les lumières si patchées)
        test_frame = b'\x00' + bytes([127] * 512)

        try:
            ser = _s.Serial(
                port=port, baudrate=250000,
                bytesize=_s.EIGHTBITS, parity=_s.PARITY_NONE,
                stopbits=_s.STOPBITS_TWO, timeout=0.1,
            )
            for i in range(20):
                try:
                    ser.break_condition = True
                    _time.sleep(0.000200)
                    ser.break_condition = False
                    ser.write(test_frame)
                    ser.flush()
                    ok_count += 1
                except Exception as e:
                    err_msg = str(e)
                _time.sleep(0.04)  # ~25 fps
            ser.close()
        except Exception as e:
            err_msg = str(e)

        if ok_count == 20:
            self.lbl_diag.setText(f"✓ 20/20 frames envoyées — DMX opérationnel")
            self.lbl_diag.setStyleSheet("color: #4CAF50;")
        elif ok_count > 0:
            self.lbl_diag.setText(f"⚠ {ok_count}/20 frames OK — instable ({err_msg[:40]})")
            self.lbl_diag.setStyleSheet("color: #ff9800;")
        else:
            self.lbl_diag.setText(f"✗ 0/20 frames — {err_msg[:60]}")
            self.lbl_diag.setStyleSheet("color: #f44336;")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _set_test(self, text, ok=False, error=False):
        color = "#4CAF50" if ok else ("#f44336" if error else "#555")
        self.lbl_test.setText(text)
        self.lbl_test.setStyleSheet(f"color: {color};")

    def _set_connect(self, text, ok=False, error=False):
        color = "#4CAF50" if ok else ("#f44336" if error else "#555")
        self.lbl_connect.setText(text)
        self.lbl_connect.setStyleSheet(f"color: {color};")


# Alias de compatibilité
EnttecSetupDialog = DmxSetupDialog
