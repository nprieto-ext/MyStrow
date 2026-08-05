"""
Assistant guidé de configuration de la sortie DMX.
Colonne gauche : sélection du matériel.
Colonne droite : 3 étapes guidées (connecter → diagnostiquer → activer).
"""
import socket as _sock
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QListWidget, QListWidgetItem,
    QApplication, QWidget, QFrame, QTextEdit, QMessageBox,
)
from PySide6.QtGui import QFont, QColor
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from core import ComboSansMolette
from i18n import tr

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

from artnet_dmx import (TRANSPORT_ENTTEC, TRANSPORT_ENTTEC_D2XX,
                        TRANSPORT_ENTTEC_PRO, FTD2XX_AVAILABLE,
                        BREAK_BAUD, BREAK_US,
                        SERIAL_LINES_MODES, SERIAL_LINES_LABELS)

try:
    import ftd2xx
    import ftd2xx.defines as _ftd
except Exception:
    ftd2xx = None


def _port_info(port_device):
    """Retourne (present, is_ftdi, serial_number) pour un port COM donné.
    present = le port figure dans la liste des ports COM actuels."""
    if not SERIAL_AVAILABLE or not port_device:
        return False, False, None
    try:
        for p in serial.tools.list_ports.comports():
            if p.device == port_device:
                is_ftdi = (getattr(p, 'vid', None) == 0x0403)
                return True, is_ftdi, getattr(p, 'serial_number', None)
    except Exception:
        pass
    return False, False, None


def _d2xx_has_device():
    """True si au moins une puce FTDI est visible via le driver D2XX."""
    if not FTD2XX_AVAILABLE or ftd2xx is None:
        return False
    try:
        return bool(ftd2xx.listDevices())
    except Exception:
        return False


def resolve_usb_transport(port_device):
    """Décide du transport pour un boîtier USB-DMX donné.

    Boîtier FTDI (ENTTEC Open DMX, DMXKing…) + ftd2xx dispo → D2XX (fiable,
    comme QLC+). Sinon (clone CH340/CP210x, ou ftd2xx absent) → série VCP.
    Retourne (transport, ftdi_serial)."""
    present, is_ftdi, serial_no = _port_info(port_device)
    if FTD2XX_AVAILABLE:
        if is_ftdi:
            return TRANSPORT_ENTTEC_D2XX, serial_no
        # Port COM disparu (souvent parce que la puce est déjà ouverte en D2XX,
        # ce qui masque le port VCP) mais une puce FTDI reste visible en D2XX :
        # on reste en D2XX plutôt que de basculer en série (qui échouerait).
        if not present and _d2xx_has_device():
            return TRANSPORT_ENTTEC_D2XX, None
    return TRANSPORT_ENTTEC, None

# ---------------------------------------------------------------------------
# Catalogue de produits compatibles
# ---------------------------------------------------------------------------

PRODUCTS = [
    {
        "id":        "eurolite_usb",
        "name":      "Eurolite USB-DMX512 PRO (MK2)",
        "transport": TRANSPORT_ENTTEC_PRO,
        "info":      "Interface USB-DMX — la LED passe au vert quand la sortie est active.",
        "step1":     "Branchez l'interface sur un port USB.",
    },
    {
        "id":        "enttec_pro",
        "name":      "ENTTEC DMX USB Pro",
        "transport": TRANSPORT_ENTTEC_PRO,
        "info":      "Interface USB-DMX professionnelle.",
        "step1":     "Branchez l'interface sur un port USB.",
    },
    {
        "id":        "enttec_open",
        "name":      "ENTTEC Open DMX USB",
        "transport": TRANSPORT_ENTTEC,
        "info":      "Adaptateur USB-DMX simple.",
        "step1":     "Branchez le boîtier sur un port USB.",
    },
    {
        "id":        "electroconcept_opto",
        "name":      "OPTO OPEN DMX (ElectroConcept)",
        "transport": TRANSPORT_ENTTEC,
        "info":      "Open DMX USB opto-isolé — puce FTDI, piloté en D2XX si dispo.",
        "step1":     "Branchez le boîtier sur un port USB.",
    },
    {
        "id":        "dmxking_micro",
        "name":      "DMXKing UltraDMX Micro",
        "transport": TRANSPORT_ENTTEC,
        "info":      "Adaptateur USB-DMX compact.",
        "step1":     "Branchez le boîtier sur un port USB.",
    },
    {
        "id":        "generic_usb",
        "name":      "Autre interface USB-DMX",
        "transport": TRANSPORT_ENTTEC,
        "info":      "Adaptateur USB-DMX générique (FTDI ou clone).",
        "step1":     "Branchez votre interface sur un port USB.",
    },
]

_BY_ID = {p["id"]: p for p in PRODUCTS}


def product_by_id(pid):
    return _BY_ID.get(pid)


# ---------------------------------------------------------------------------
# Styles partagés
# ---------------------------------------------------------------------------

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

# Threads de connexion encore en vol. Un QThread détruit pendant qu'il tourne
# fait tomber le process : tant qu'il n'a pas fini, on garde une référence ici,
# même si le dialogue qui l'a lancé a déjà été fermé.
_PENDING_CONNECTS = set()


class _ConnectWorker(QThread):
    """Ouvre la sortie DMX hors du thread GUI.

    `serial.Serial()` et l'ouverture D2XX sont des appels système bloquants,
    sans borne de temps quand le boîtier ne répond pas (typique sur macOS quand
    la puce FTDI est déjà réservée par un autre driver) : exécutés sur le thread
    GUI, ils gelaient toute l'application — seul un « Forcer à quitter » en
    sortait. Ici l'UI reste vivante et le dialogue peut abandonner.
    """

    result = Signal(bool, str)   # (succès, transport réellement utilisé)

    def __init__(self, dmx, prod, port):
        super().__init__(None)
        self._dmx, self._prod, self._port = dmx, prod, port

    def run(self):
        transport = ""
        try:
            # ENTTEC Pro : protocole à paquets, piloté par le port série VCP normal
            # (le boîtier gère lui-même le break DMX → pas besoin du D2XX).
            # Sinon (Open DMX passif) : D2XX si dispo, repli série VCP.
            if self._prod.get("transport") == TRANSPORT_ENTTEC_PRO:
                transport, ftdi_serial = TRANSPORT_ENTTEC_PRO, None
            else:
                transport, ftdi_serial = resolve_usb_transport(self._port)
            ok = self._dmx.connect(
                transport=transport,
                product_id=self._prod["id"],
                product_name=self._prod["name"],
                com_port=self._port,
                ftdi_serial=ftdi_serial,
            )
            self.result.emit(bool(ok), transport)
        except Exception as e:
            print(f"[DMX] connexion échouée: {e}")
            self.result.emit(False, transport)


class DmxSetupDialog(QDialog):
    """Assistant de configuration de la sortie DMX"""

    # Au-delà, on rend la main à l'utilisateur au lieu de le laisser devant une
    # fenêtre morte. Large exprès : une ouverture série lente mais valide (≈2-3 s
    # sur certains câbles) doit réussir, on ne coupe que les cas vraiment bloqués.
    CONNECT_TIMEOUT_MS = 8000

    def __init__(self, dmx, parent=None):
        super().__init__(parent)
        self._dmx = dmx
        self._parent_win = parent
        self._connect_worker = None    # thread de connexion en cours (ou None)
        self._connect_timer = None
        self._connect_timed_out = False
        self._connect_name = ""
        self.setWindowTitle(tr("ent_title"))
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
        lbl = QLabel(tr("ent_title"))
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

        hint = QLabel(tr("es2_your_iface"))
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

        _header("  Choisissez votre interface USB-DMX")
        for p in PRODUCTS:
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

        lay.addWidget(self._make_usb_panel())

        lay.addSpacing(12)

        # ── Étape 2 : DIAGNOSTIC ─────────────────────────────────────────────
        hdr2 = self._step_hdr("2", "DIAGNOSTIC")
        lay.addLayout(hdr2)
        lay.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(26, 0, 0, 0)

        self.btn_diag = QPushButton(tr("es2_run_diag"))
        self.btn_diag.setFixedSize(160, 28)
        self.btn_diag.setStyleSheet(
            "QPushButton { background: #1e2a3a; color: #00d4ff; border: 1px solid #00d4ff;"
            " border-radius: 4px; font-size: 10px; font-weight: bold; }"
            "QPushButton:hover { background: #243040; }"
            "QPushButton:disabled { color: #444; border-color: #333; background: #1a1a1a; }"
        )
        self.btn_diag.clicked.connect(self._run_diag)
        btn_row.addWidget(self.btn_diag)

        self.btn_test100 = QPushButton(tr("ent_test_full"))
        self.btn_test100.setFixedSize(110, 28)
        self.btn_test100.setStyleSheet(
            "QPushButton { background: #2a1e00; color: #ffaa00; border: 1px solid #ffaa00;"
            " border-radius: 4px; font-size: 10px; font-weight: bold; }"
            "QPushButton:hover { background: #3a2a00; }"
            "QPushButton:disabled { color: #444; border-color: #333; background: #1a1a1a; }"
        )
        self.btn_test100.clicked.connect(self._run_test100)
        btn_row.addWidget(self.btn_test100)

        # Balayage RTS/DTR : sert quand le boîtier passif reste muet alors que
        # tout le diagnostic est vert (émetteur RS485 inhibé — cf. artnet_dmx).
        self.btn_lines = QPushButton(tr("ent_test_rtsdtr"))
        self.btn_lines.setFixedSize(120, 28)
        self.btn_lines.setToolTip(
            tr("ent_rtsdtr_intro")
        )
        self.btn_lines.setStyleSheet(
            "QPushButton { background: #241a2e; color: #c07bff; border: 1px solid #c07bff;"
            " border-radius: 4px; font-size: 10px; font-weight: bold; }"
            "QPushButton:hover { background: #2f2340; }"
            "QPushButton:disabled { color: #444; border-color: #333; background: #1a1a1a; }"
        )
        self.btn_lines.clicked.connect(self._run_lines_test)
        btn_row.addWidget(self.btn_lines)

        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        lay.addSpacing(6)

        # Zone de sortie du diagnostic
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(140)
        self._log.setStyleSheet(_LOG_STYLE)
        self._log.setPlaceholderText(tr("es2_results_here"))
        lay.addWidget(self._log)

        copy_row = QHBoxLayout()
        copy_row.setContentsMargins(0, 2, 0, 0)
        copy_row.addStretch()
        btn_copy = QPushButton(tr("es2_copy_report"))
        btn_copy.setFixedHeight(22)
        btn_copy.setStyleSheet(
            "QPushButton { background: #1a1a1a; color: #555; border: 1px solid #2a2a2a;"
            " border-radius: 3px; padding: 0 10px; font-size: 9px; }"
            "QPushButton:hover { color: #ccc; border-color: #444; }"
        )
        btn_copy.clicked.connect(self._copy_report)
        copy_row.addWidget(btn_copy)

        btn_send = QPushButton(tr("ent_send_support"))
        btn_send.setFixedHeight(22)
        btn_send.setStyleSheet(
            "QPushButton { background: #1a1a1a; color: #555; border: 1px solid #2a2a2a;"
            " border-radius: 3px; padding: 0 10px; font-size: 9px; }"
            "QPushButton:hover { color: #ccc; border-color: #444; }"
        )
        btn_send.clicked.connect(self._send_report)
        copy_row.addWidget(btn_send)
        lay.addLayout(copy_row)

        lay.addSpacing(12)

        # ── Étape 3 ──────────────────────────────────────────────────────────
        lay.addLayout(self._step_hdr("3", "Utiliser cette interface DMX"))
        lay.addSpacing(6)

        row3 = QHBoxLayout()
        row3.setContentsMargins(26, 0, 0, 0)
        self.btn_connect = QPushButton(tr("ent_connect"))
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
        btn_close = QPushButton(tr("ent_close"))
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
        lbl = QLabel(tr("ent_com_port"))
        lbl.setFont(QFont("Segoe UI", 10))
        lbl.setFixedWidth(72)
        row.addWidget(lbl)
        self.port_combo = ComboSansMolette()
        self.port_combo.setStyleSheet(_COMBO)
        row.addWidget(self.port_combo, 1)
        btn_r = QPushButton("↻")
        btn_r.setFixedSize(26, 26)
        btn_r.setToolTip(tr("es2_refresh_ports"))
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

    def _current_product(self):
        item = self.product_list.currentItem()
        if not item:
            return None
        return product_by_id(item.data(Qt.UserRole))

    def _refresh_ports(self):
        self.port_combo.clear()
        if not SERIAL_AVAILABLE:
            self.port_combo.addItem(tr("ent_no_pyserial"))
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
            self.port_combo.addItem(tr("ent_no_port"))
            self.lbl_port_hint.setText(tr("es2_plug_then"))
        elif enttec:
            self.lbl_port_hint.setText(tr("ent_n_ftdi", a0=len(enttec)))
        else:
            self.lbl_port_hint.setText(tr("es2_manual_port"))

        if self._dmx.com_port:
            for i in range(self.port_combo.count()):
                if self.port_combo.itemData(i) == self._dmx.com_port:
                    self.port_combo.setCurrentIndex(i)
                    break

    # ── TEST 100% ───────────────────────────────────────────────────────────

    def _send_serial_frame(self, ser, frame):
        """Émet UNE trame DMX (break + MAB + data) sur un port série brut.

        Copie EXACTE de la séquence de `ArtNetDMX._enttec_loop`, choix de la
        méthode de break par plateforme compris. Un test qui n'utilise pas la
        même séquence que la sortie live ne prouve rien : sur macOS,
        `send_break` réussit sans lever d'exception mais ne produit aucun break
        électrique valide — le Test 100 % s'en servait, il pouvait donc annoncer
        « frames envoyées sans erreur » sur une ligne DMX totalement silencieuse.
        """
        import time as _time
        if sys.platform == 'darwin':
            ser.baudrate = BREAK_BAUD
            ser.write(b'\x00')
            ser.flush()
            _time.sleep(0.0015)
            ser.baudrate = 250000
            _time.sleep(0.0001)      # MAB ≥ 8 µs
        else:
            ser.send_break(duration=0.001)
        ser.write(frame)
        ser.flush()

    def _run_lines_test(self):
        """Balaye les 4 états possibles des lignes RTS/DTR, 4 s de plein feu chacun.

        À utiliser quand un boîtier passif (Open DMX) reste muet alors que tout
        le diagnostic est vert : sur ce matériel la broche Driver Enable du
        transceiver RS485 peut être câblée sur RTS ou DTR, et pyserial les
        asserte à l'ouverture — l'émetteur reste alors désactivé, sans la
        moindre erreur côté PC (cf. SERIAL_LINES_MODES dans artnet_dmx.py).
        L'état qui allume les projecteurs est mémorisé dans ~/.mystrow_dmx.json,
        donc trouvé une fois, il s'applique à toutes les connexions suivantes.
        """
        import time as _time

        ok = "#4CAF50"; warn = "#ff9800"; err = "#f44336"; cyan = "#00d4ff"; dim = "#888888"

        # `btn_diag` sert de drapeau « occupé » commun aux trois tests : il est
        # désactivé pendant le diagnostic ET pendant le Test 100 %. Deux writers
        # simultanés sur la même puce FTDI = port refermé en pleine séquence.
        if not self.btn_diag.isEnabled():
            self._log_line("  ⏳  Un test est déjà en cours — attendez la fin.", warn)
            return

        self._log.clear()
        self._log_line("═══ TEST DES LIGNES RTS / DTR ═══", cyan)

        live_transport = getattr(self._dmx, 'transport', '')
        port = self.port_combo.currentData()
        port_transport = resolve_usb_transport(port)[0] if port else TRANSPORT_ENTTEC
        if live_transport == TRANSPORT_ENTTEC_D2XX or port_transport == TRANSPORT_ENTTEC_D2XX:
            self._log_line("  –  Boîtier piloté en D2XX : les lignes sont gérées par le", dim)
            self._log_line("     driver FTDI, ce test ne s'applique pas.", dim)
            return
        if live_transport == TRANSPORT_ENTTEC_PRO or port_transport == TRANSPORT_ENTTEC_PRO:
            self._log_line("  –  Interface « Pro » (microcontrôleur) : elle n'utilise pas", dim)
            self._log_line("     RTS/DTR pour activer sa sortie. Test inutile ici.", dim)
            return

        self.btn_diag.setEnabled(False)
        self.btn_test100.setEnabled(False)
        self.btn_lines.setEnabled(False)

        # ── Port : emprunter celui de la sortie live, ou l'ouvrir ────────────
        ser = None
        opened_here = False
        paused_live = False
        dmx_serial = getattr(self._dmx, '_serial', None)

        if dmx_serial and dmx_serial.is_open:
            self._dmx._enttec_pause = True
            paused_live = True
            _wait = _time.monotonic() + 0.6
            while (_time.monotonic() < _wait
                   and not getattr(self._dmx, '_enttec_paused', False)):
                QApplication.processEvents()
                _time.sleep(0.01)
            ser = dmx_serial
            self._log_line(f"  ✓  Connexion MyStrow empruntée ({self._dmx.com_port})", ok)
        elif port:
            try:
                ser = serial.Serial(
                    port=port, baudrate=250000,
                    bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_TWO, timeout=0.1,
                )
                opened_here = True
                self._log_line(f"  ✓  Port {port} ouvert", ok)
            except Exception as e:
                self._log_line(f"  ✗  Impossible d'ouvrir le port : {e}", err)
                self._lines_test_done()
                return
        else:
            self._log_line("  ✗  Aucun port disponible — connectez d'abord le boîtier", err)
            self._lines_test_done()
            return

        modes = list(SERIAL_LINES_MODES.keys())
        DURATION_S = 4
        INTERVAL_MS = 40                       # 25 fps, comme la sortie live
        per_mode = int(DURATION_S * 1000 / INTERVAL_MS)
        full_frame = b'\x00' + bytes([255] * 512)
        state = {"mode": -1, "sent": 0, "errors": 0}

        self._log_line("")
        self._log_line(f"  4 séquences de {DURATION_S} s, tous canaux à 255.", "#cccccc")
        self._log_line("  👀  REGARDEZ LES PROJECTEURS et notez le n° qui les allume.", warn)
        self._log_line("")

        def _start_mode():
            state["mode"] += 1
            state["sent"] = 0
            if state["mode"] >= len(modes):
                _timer.stop()
                _ask()
                return
            mode = modes[state["mode"]]
            self._dmx.apply_serial_lines(ser, mode)
            self._log_line(f"  [{state['mode'] + 1}/4]  {SERIAL_LINES_LABELS[mode]}…", cyan)

        def _tick():
            # Callback QTimer : toute exception non rattrapée ici tue le
            # process PySide6 (cf. les wrappers des timers de restitution).
            try:
                if state["sent"] >= per_mode:
                    _start_mode()
                    return
                try:
                    self._send_serial_frame(ser, full_frame)
                    state["sent"] += 1
                except Exception as ex:
                    state["errors"] += 1
                    if state["errors"] > 10:
                        _timer.stop()
                        self._log_line(f"  ✗  Erreurs répétées — test arrêté : {ex}", err)
                        _cleanup(None)
            except Exception as ex:
                _timer.stop()
                self._log_line(f"  ✗  Test interrompu : {ex}", err)
                self._lines_test_done()

        def _ask():
            box = QMessageBox(self)
            box.setWindowTitle(tr("ent_rtsdtr"))
            box.setIcon(QMessageBox.Question)
            box.setText(tr("es2_which_seq"))
            box.setInformativeText(
                tr("ent_rtsdtr_saved")
            )
            buttons = {}
            for i, mode in enumerate(modes):
                buttons[box.addButton(f"{i + 1} — {SERIAL_LINES_LABELS[mode]}",
                                      QMessageBox.AcceptRole)] = mode
            btn_none = box.addButton(tr("ent_none"), QMessageBox.RejectRole)
            box.exec()
            _cleanup(buttons.get(box.clickedButton()) if box.clickedButton() is not btn_none else None)

        def _cleanup(chosen):
            self._log_line("")
            if chosen:
                self._dmx.serial_lines = chosen
                self._dmx._save_config()
                self._log_line(f"  ✓  Réglage mémorisé : {SERIAL_LINES_LABELS[chosen]}", ok)
            else:
                self._log_line("  ⚠  Aucune séquence retenue — réglage inchangé "
                               f"({SERIAL_LINES_LABELS.get(getattr(self._dmx, 'serial_lines', 'clear'), '?')})", warn)
                self._log_line("      Le problème est alors ailleurs : câble XLR, adresse DMX,", dim)
                self._log_line("      ou boîtier exigeant le driver D2XX.", dim)
            # Le balayage a laissé les lignes sur le DERNIER mode testé : sans
            # cette remise en état, la sortie live resterait muette jusqu'à la
            # prochaine reconnexion.
            try:
                self._dmx.apply_serial_lines(ser)
            except Exception:
                pass
            if opened_here:
                try: ser.close()
                except Exception: pass
            if paused_live:
                self._dmx._enttec_pause = False
            self._lines_test_done()

        _timer = QTimer(self)          # créé AVANT _start_mode : la closure l'utilise
        _timer.timeout.connect(_tick)
        _start_mode()
        _timer.start(INTERVAL_MS)

    def _lines_test_done(self):
        self.btn_diag.setEnabled(True)
        self.btn_test100.setEnabled(True)
        self.btn_lines.setEnabled(True)

    def _run_test100(self):
        """Envoie 3 secondes de DMX full (tous canaux = 255) via l'Enttec connecté."""
        from PySide6.QtCore import QTimer as _QTimer
        import time as _time

        self.btn_test100.setEnabled(False)
        self.btn_diag.setEnabled(False)
        self._log.clear()

        ok   = "#4CAF50"; warn = "#ff9800"; err = "#f44336"; cyan = "#00d4ff"
        self._log_line("═══ TEST DMX — TOUS CANAUX À 100% (255) ═══", cyan)

        port = self.port_combo.currentData()

        # Boîtier FTDI piloté en D2XX : la puce n'est PAS accessible via le port
        # COM (le driver D2XX la détient), il faut tester via D2XX.
        live_d2xx = (getattr(self._dmx, 'transport', '') == TRANSPORT_ENTTEC_D2XX)
        port_d2xx = (resolve_usb_transport(port)[0] == TRANSPORT_ENTTEC_D2XX) if port else False
        if live_d2xx or port_d2xx:
            self._run_test100_d2xx(live_d2xx)
            return

        # ── Trouver / ouvrir le port ─────────────────────────────────────────
        ser = None
        opened_here = False
        paused_live = False   # True si on a suspendu le thread ENTTEC live
        dmx_serial = getattr(self._dmx, '_serial', None)

        if dmx_serial and dmx_serial.is_open:
            ser = dmx_serial
            # Suspendre le thread de fond : sinon il écrit en parallèle sur le
            # même port FTDI, ce qui provoque une erreur puis la fermeture du
            # port ("Attempting to use a port that is not open").
            self._dmx._enttec_pause = True
            paused_live = True
            # Attendre que le thread live ait acquitté la pause : il doit avoir
            # atteint sa branche pause (et lâché le port) AVANT qu'on écrive.
            # Sans cette synchro, les deux threads écrivent en parallèle sur le
            # FTDI → le thread live tombe en erreur, ferme le port, et le test
            # échoue avec "Attempting to use a port that is not open".
            _wait_until = _time.monotonic() + 0.6
            while (_time.monotonic() < _wait_until
                   and not getattr(self._dmx, '_enttec_paused', False)):
                QApplication.processEvents()
                _time.sleep(0.01)
            self._log_line(f"  ✓  Utilisation de la connexion MyStrow ({self._dmx.com_port})", ok)
        elif port:
            self._log_line(f"  →  Ouverture de {port} pour le test…", "#cccccc")
            QApplication.processEvents()
            try:
                ser = serial.Serial(
                    port=port, baudrate=250000,
                    bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_TWO, timeout=0.1,
                )
                opened_here = True
                # Mêmes lignes RTS/DTR que la sortie live, sinon le test peut
                # rester muet (ou marcher !) pour une raison qui ne se
                # reproduira pas en show.
                self._dmx.apply_serial_lines(ser)
                self._log_line(f"  ✓  Port ouvert", ok)
            except Exception as e:
                self._log_line(f"  ✗  Impossible d'ouvrir le port : {e}", err)
                self.btn_test100.setEnabled(True)
                self.btn_diag.setEnabled(True)
                return
        else:
            self._log_line("  ✗  Aucun port disponible — connectez d'abord le boîtier", err)
            self.btn_test100.setEnabled(True)
            self.btn_diag.setEnabled(True)
            return

        # ── Frame full-on ────────────────────────────────────────────────────
        full_frame = b'\x00' + bytes([255] * 512)
        DURATION_S = 3
        INTERVAL_MS = 40   # 25 fps
        total_frames = int(DURATION_S * 1000 / INTERVAL_MS)
        sent = [0]
        errors = [0]

        self._log_line("")
        self._log_line(f"  Envoi de {total_frames} frames ({DURATION_S} s) — "
                       f"tous les canaux = 255…", "#cccccc")
        self._log_line("  Si vos appareils ne réagissent pas, vérifiez :", warn)
        self._log_line("   • Câble DMX branché sur le boîtier (sortie XLR)", "#888888")
        self._log_line("   • Adresse DMX des projecteurs (CH1 = 001)", "#888888")
        self._log_line("   • Mode DMX des projecteurs (pas en 'no signal')", "#888888")

        def _send_frame():
            if sent[0] >= total_frames:
                _timer.stop()
                _finish()
                return
            try:
                # Même séquence break + trame que la sortie live, plateforme
                # comprise (sur macOS send_break ne produit pas de break valide).
                self._send_serial_frame(ser, full_frame)
                sent[0] += 1
            except Exception as ex:
                errors[0] += 1
                if errors[0] > 5:
                    _timer.stop()
                    self._log_line(f"  ✗  Erreurs répétées — test arrêté : {ex}", err)
                    _cleanup()

        def _finish():
            self._log_line("")
            if errors[0] == 0:
                self._log_line(f"  ✓  {sent[0]}/{total_frames} frames envoyées sans erreur", ok)
                self._log_line("  Si aucun appareil ne réagit → problème de câblage DMX", warn)
            else:
                self._log_line(f"  ⚠  {sent[0]} frames OK, {errors[0]} erreurs", warn)
            _cleanup()

        def _cleanup():
            if opened_here:
                try: ser.close()
                except Exception: pass
            if paused_live:
                self._dmx._enttec_pause = False   # relancer le thread live
            self.btn_test100.setEnabled(True)
            self.btn_diag.setEnabled(True)

        _timer = _QTimer(self)
        _timer.timeout.connect(_send_frame)
        _timer.start(INTERVAL_MS)

    def _run_test100_d2xx(self, live_d2xx):
        """Test 100% via le driver FTDI D2XX (boîtier passif FT232R)."""
        from PySide6.QtCore import QTimer as _QTimer
        import time as _time

        ok = "#4CAF50"; warn = "#ff9800"; err = "#f44336"
        self._log_line("  (pilote D2XX direct — comme QLC+)", "#888888")

        dev = None
        opened_here = False
        paused_live = False

        if live_d2xx and getattr(self._dmx, 'connected', False):
            # Réutiliser la puce déjà ouverte par MyStrow : on suspend le thread
            # live (avec acquittement) pour ne pas écrire à deux sur le FTDI.
            self._dmx._d2xx_pause = True
            paused_live = True
            _wait = _time.monotonic() + 0.6
            while (_time.monotonic() < _wait
                   and not getattr(self._dmx, '_d2xx_paused', False)):
                QApplication.processEvents()
                _time.sleep(0.01)
            dev = getattr(self._dmx, '_d2xx', None)   # relire après la pause
            if dev is None:
                self._log_line("  ✗  Connexion live active mais handle indisponible — réessayez", err)
                self._dmx._d2xx_pause = False
                self.btn_test100.setEnabled(True)
                self.btn_diag.setEnabled(True)
                return
            self._log_line("  ✓  Utilisation de la connexion MyStrow (D2XX)", ok)
        else:
            self._log_line("  →  Ouverture de la puce FTDI en D2XX…", "#cccccc")
            QApplication.processEvents()
            try:
                index = self._dmx._resolve_d2xx_index()
                dev = ftd2xx.open(index)
                dev.setBaudRate(250000)
                dev.setDataCharacteristics(_ftd.BITS_8, _ftd.STOP_BITS_2, _ftd.PARITY_NONE)
                dev.setFlowControl(_ftd.FLOW_NONE, 0, 0)
                dev.setLatencyTimer(1)
                dev.setTimeouts(100, 100)
                dev.purge(_ftd.PURGE_TX | _ftd.PURGE_RX)
                opened_here = True
                self._log_line("  ✓  Puce FTDI ouverte (D2XX)", ok)
            except Exception as e:
                self._log_line(f"  ✗  Ouverture D2XX impossible : {e}", err)
                self._log_line("      → Fermez QLC+ ou tout autre logiciel DMX, puis réessayez", warn)
                self.btn_test100.setEnabled(True)
                self.btn_diag.setEnabled(True)
                return

        full_frame = b'\x00' + bytes([255] * 512)
        DURATION_S = 3
        INTERVAL_MS = 25   # ~40 fps
        total_frames = int(DURATION_S * 1000 / INTERVAL_MS)
        sent = [0]; errors = [0]

        self._log_line("")
        self._log_line(f"  Envoi de {total_frames} frames ({DURATION_S} s) — tous canaux = 255…", "#cccccc")
        self._log_line("  Si rien ne réagit : câble XLR, adresse DMX (CH1=001), mode du projo.", warn)

        def _send_frame():
            if sent[0] >= total_frames:
                _timer.stop(); _finish(); return
            try:
                dev.setBreakOn()
                _time.sleep(0.0001)
                dev.setBreakOff()
                _time.sleep(0.000012)
                dev.write(full_frame)
                sent[0] += 1
            except Exception as ex:
                errors[0] += 1
                if errors[0] > 5:
                    _timer.stop()
                    self._log_line(f"  ✗  Erreurs répétées — test arrêté : {ex}", err)
                    _cleanup()

        def _finish():
            self._log_line("")
            if errors[0] == 0:
                self._log_line(f"  ✓  {sent[0]}/{total_frames} frames envoyées sans erreur", ok)
                self._log_line("  Si aucun appareil ne réagit → problème de câblage DMX ou de patch", warn)
            else:
                self._log_line(f"  ⚠  {sent[0]} frames OK, {errors[0]} erreurs", warn)
            _cleanup()

        def _cleanup():
            if opened_here and dev is not None:
                try: dev.setBreakOff()
                except Exception: pass
                try: dev.close()
                except Exception: pass
            if paused_live:
                self._dmx._d2xx_pause = False
            self.btn_test100.setEnabled(True)
            self.btn_diag.setEnabled(True)

        _timer = _QTimer(self)
        _timer.timeout.connect(_send_frame)
        _timer.start(INTERVAL_MS)

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
        try:
            import platform as _plat
            from core import APP_NAME, VERSION
            self._log_line(f"  {APP_NAME} v{VERSION}  —  {_plat.system()} {_plat.release()}", "#888888")
        except Exception:
            pass

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

        # ── Mode de pilotage retenu : D2XX vs série VCP ──────────────────────
        # LE point critique sur Open DMX USB. Le D2XX (comme QLC+) génère un
        # break DMX propre ; la série VCP corrompt son timing (Latency Timer
        # FTDI) → clignotements et lyres qui bougent seules. Si FTD2XX_AVAILABLE
        # est faux, MyStrow retombe SILENCIEUSEMENT sur la série VCP : on le
        # rend visible ici pour ne plus chercher à l'aveugle.
        self._log_line("")
        if getattr(self._dmx, 'transport', '') == TRANSPORT_ENTTEC_PRO:
            # Interface ENTTEC Pro : protocole à paquets, le boîtier génère le
            # break lui-même → le D2XX/VCP ne le concerne pas.
            self._log_line("      →  Mode retenu : ENTTEC Pro (protocole à paquets)", ok)
            self._log_line("         Le boîtier gère le break DMX lui-même —", dim)
            self._log_line("         aucun pilote D2XX nécessaire.", dim)
        else:
            resolved = resolve_usb_transport(port)[0]
            if FTD2XX_AVAILABLE:
                self._log_line("      ✓  Pilote D2XX disponible (FTDI direct, comme QLC+)", ok)
            else:
                self._log_line("      ⚠  Pilote D2XX indisponible → repli sur la série VCP", warn)
                self._log_line("         Si votre interface est une « Pro » (ENTTEC DMX USB Pro,", dim)
                self._log_line("         Eurolite USB-DMX512 PRO MK2…), sélectionnez-la dans la", dim)
                self._log_line("         liste des interfaces : elle n'a pas besoin du D2XX.", dim)
            if resolved == TRANSPORT_ENTTEC_D2XX:
                self._log_line("      →  Mode retenu pour ce boîtier : D2XX (fiable)", ok)
            else:
                self._log_line("      →  Mode retenu pour ce boîtier : série VCP", warn)

        # ── Boîtier FTDI piloté en D2XX → diagnostic via le driver direct ────
        # La puce n'est pas accessible par le port COM quand D2XX la détient :
        # on lance un diagnostic D2XX dédié (steps 4-6) puis l'état live.
        if (resolve_usb_transport(port)[0] == TRANSPORT_ENTTEC_D2XX
                or getattr(self._dmx, 'transport', '') == TRANSPORT_ENTTEC_D2XX):
            self._diag_d2xx_steps()
            self._diag_live_state()
            self.btn_diag.setEnabled(True)
            return

        # ── Pause du thread live ENTTEC avant tout accès au port ─────────────
        # Sans ça, le thread de fond (_enttec_loop) et le diagnostic ouvrent /
        # ferment le même handle FTDI en parallèle → crash natif du driver
        # Windows (l'appli se ferme), reproductible en lançant le diagnostic
        # 2 fois de suite : le 1er run force le thread live en reconnexion, le
        # 2e run ouvre le port pile pendant que le thread le rouvre aussi.
        # On suspend le thread (avec acquittement) le temps des étapes 4-6,
        # exactement comme le Test 100%. Relâché après l'étape 6 (et sur chaque
        # sortie anticipée). closeEvent() relâche aussi en garde-fou.
        # L'ENTTEC Pro a exactement le même problème : son thread (_pro_loop)
        # écrit à 25 fps sur le tty. Il n'était pas suspendu — d'où le crash de
        # l'appli au lancement du diagnostic avec une Pro connectée, puis une
        # sortie DMX morte (LED qui cesse de clignoter, fixtures en autonome).
        _paused_live = False
        _live_transport = getattr(self._dmx, 'transport', '')
        _attr_pause = {TRANSPORT_ENTTEC:     ('_enttec_pause', '_enttec_paused'),
                       TRANSPORT_ENTTEC_PRO: ('_pro_pause',    '_pro_paused')}.get(
                           _live_transport)
        if _attr_pause:
            _drapeau, _ack = _attr_pause
            setattr(self._dmx, _drapeau, True)
            _paused_live = True
            _wait_until = _time.monotonic() + 0.6
            while (_time.monotonic() < _wait_until
                   and not getattr(self._dmx, _ack, False)):
                QApplication.processEvents()
                _time.sleep(0.01)

        def _unpause_live():
            if _paused_live:
                try:
                    setattr(self._dmx, _attr_pause[0], False)
                except Exception:
                    pass

        # ── 4. Ouverture du port ─────────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 4 ] Ouverture à 250 000 bauds", cyan)

        # Vérifier si le port est déjà ouvert par MyStrow. Les deux handles
        # comptent : _serial (Open DMX) ET _pro_serial (ENTTEC Pro). N'en
        # regarder qu'un laissait le diagnostic rouvrir le tty d'une Pro déjà
        # tenue par la sortie live.
        dmx_serial = (getattr(self._dmx, '_serial', None)
                      or getattr(self._dmx, '_pro_serial', None))
        if dmx_serial and dmx_serial.is_open and getattr(dmx_serial, 'port', None) == port:
            # Le thread live vient d'être suspendu juste au-dessus : on peut
            # emprunter SON handle au lieu de sauter les tests. Avant, les étapes
            # 5 et 6 étaient « ignorées » dès que la sortie était connectée —
            # c'est-à-dire précisément quand l'utilisateur cherche pourquoi ses
            # projecteurs ne répondent pas. Le diagnostic ne testait alors plus
            # rien et concluait quand même « opérationnel ».
            self._log_line(f"  ⚠  Port déjà ouvert par MyStrow (connexion active)", warn)
            self._log_line("      Tests menés sur cette connexion (envoi live suspendu)", dim)
            ser = dmx_serial
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
                self._dmx.apply_serial_lines(ser)   # comme la sortie live
                self._log_line(f"  ✓  Ouvert en {elapsed:.0f} ms", ok)
            except serial.SerialException as e:
                msg = str(e)
                self._log_line(f"  ✗  Échec ouverture : {msg}", err)
                if "access" in msg.lower() or "13" in msg or "permission" in msg.lower():
                    self._log_line("      → Port utilisé par une autre application", warn)
                    self._log_line("        Fermez tous les logiciels DMX et relancez", warn)
                elif "could not open" in msg.lower() or "no such" in msg.lower():
                    self._log_line("      → Port introuvable — rebranchez le boîtier", warn)
                _unpause_live()
                self.btn_diag.setEnabled(True)
                return
            except Exception as e:
                self._log_line(f"  ✗  Erreur inattendue : {e}", err)
                _unpause_live()
                self.btn_diag.setEnabled(True)
                return

        # ── 5. Test signal Break ─────────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 5 ] Signal Break DMX", cyan)
        _break_ok = False
        _break_method_used = "—"
        if ser and sys.platform == 'darwin':
            # macOS : on teste la MÊME méthode que la sortie live (_enttec_loop).
            # `break_condition` y réussit sans lever d'exception tout en ne
            # produisant aucun break électrique valide — le tester ici afficherait
            # un « ✓ » mensonger alors que les projecteurs ignorent tout.
            try:
                # Pas de reset_output_buffer() : il bloque ~1 s par appel sur
                # macOS (FTDI VCP) et jetterait le break qu'on vient d'émettre.
                # Doit rester la copie EXACTE de `_enttec_loop`, sinon ce test
                # valide une séquence que la sortie live n'utilise pas.
                ser.baudrate = BREAK_BAUD
                ser.write(b'\x00')
                ser.flush()
                _time.sleep(0.0015)
                ser.baudrate = 250000
                self._log_line(f"  ✓  Baud-rate trick OK — break ≈ {BREAK_US:.0f} µs", ok)
                self._log_line("      (méthode utilisée par la sortie live sur macOS)", dim)
                _break_ok = True
                _break_method_used = "baud-rate trick"
            except Exception as e:
                self._log_line(f"  ✗  Baud-rate trick échoué : {e}", err)
        elif ser:
            # Méthode 1 : break_condition (FTDI VCP standard)
            try:
                ser.break_condition = True
                _time.sleep(0.000176)
                ser.break_condition = False
                self._log_line("  ✓  break_condition OK (méthode standard)", ok)
                _break_ok = True
                _break_method_used = "break_condition"
            except (AttributeError, OSError) as e:
                self._log_line(f"  ⚠  break_condition échoué : {e}", warn)
                self._log_line("      → Tentative de la méthode baud-rate…", dim)
                # Méthode 2 : baud-rate trick (CH340, FTDI clones, drivers Windows 11)
                try:
                    ser.baudrate = BREAK_BAUD
                    ser.write(b'\x00')
                    ser.flush()
                    _time.sleep(0.001)
                    ser.baudrate = 250000
                    self._log_line("  ✓  Baud-rate trick OK (méthode compatible)", ok)
                    self._log_line("      (MyStrow basculera automatiquement sur cette méthode)", dim)
                    _break_ok = True
                    _break_method_used = "baud-rate trick"
                except Exception as e2:
                    self._log_line(f"  ✗  Les deux méthodes ont échoué : {e2}", err)
                    self._log_line("      → Pilote FTDI manquant ou interface non compatible", warn)
                    self._log_line("      → Téléchargez le pilote VCP FTDI : ftdichip.com", warn)
            except Exception as e:
                self._log_line(f"  ✗  Break signal échoué : {e}", err)

        # ── 6. Envoi de frames DMX ───────────────────────────────────────────
        self._log_line("")
        self._log_line("[ 6 ] Envoi 10 frames DMX (canaux 1-4 = 255)", cyan)
        if ser and _break_ok:
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
                    if _break_method_used == "baud-rate trick":
                        ser.baudrate = BREAK_BAUD
                        ser.write(b'\x00')
                        ser.flush()
                        _time.sleep(0.001)
                        ser.baudrate = 250000
                    else:
                        ser.break_condition = True
                        _time.sleep(0.000176)
                        ser.break_condition = False
                    ser.write(frame)
                    ser.flush()
                    ok_count += 1
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
        elif ser and not _break_ok:
            self._log_line("  –   Test ignoré — signal break non fonctionnel", dim)

        try:
            if ser and not port_already_open:
                ser.close()
        except Exception:
            pass

        # Étapes 4-6 terminées : on rend le port au thread live. L'étape 7 ne
        # lit que l'état (dmx_data), elle ne touche pas au port série.
        _unpause_live()

        # ── 7. État live MyStrow ─────────────────────────────────────────────
        self._diag_live_state()
        self.btn_diag.setEnabled(True)

    def _diag_live_state(self):
        """Étape 7 du diagnostic : état de la sortie DMX live (agnostique au
        transport — utilisée par le diagnostic série ET D2XX)."""
        ok = "#4CAF50"; warn = "#ff9800"; err = "#f44336"; dim = "#555555"; cyan = "#00d4ff"
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
        # Sur le transport série brut, l'état RTS/DTR conditionne l'activation
        # de l'émetteur RS485 de certains boîtiers passifs : à faire figurer
        # dans le rapport, sinon une sortie muette reste inexplicable.
        if transport_str == TRANSPORT_ENTTEC:
            _lines = getattr(dmx, 'serial_lines', 'clear')
            self._log_line(f"  Lignes RTS/DTR : {SERIAL_LINES_LABELS.get(_lines, _lines)}",
                           "#cccccc")

        # ── Cohérence transport ↔ interface testée ───────────────────────────
        # Cet assistant ne propose QUE des interfaces USB/série. Si la sortie
        # live est encore en Art-Net (le défaut), MyStrow n'envoie rien sur le
        # boîtier USB testé ci-dessus : le DMX part sur le réseau. C'est la
        # cause n°1 de « le diagnostic passe mais le parc ne réagit pas » —
        # les étapes [4]–[6] ouvrent le port COM en direct et réussissent, ce
        # qui masque le fait que la sortie live n'est pas branchée dessus.
        prod = self._current_product()
        # enttec (série VCP) ET enttec_d2xx (FTDI direct) sont deux transports
        # USB valides pour ces boîtiers — seul un transport réseau (Art-Net) ou
        # Pro signale que la sortie live n'est pas branchée sur l'USB testé.
        usb_transports = (TRANSPORT_ENTTEC, TRANSPORT_ENTTEC_D2XX)
        if transport_str not in usb_transports:
            prod_name = prod["name"] if prod else "interface USB-DMX"
            self._log_line("")
            self._log_line("  ⛔  ATTENTION : la sortie live n'utilise PAS votre interface USB", err)
            self._log_line(f"      Transport actif = « {transport_str} » (réseau Art-Net),", warn)
            self._log_line(f"      alors que vous testez une interface USB ({prod_name}).", warn)
            self._log_line("      Les tests ci-dessus ouvrent le port COM en direct et", dim)
            self._log_line("      réussissent, MAIS MyStrow envoie le DMX sur le réseau,", dim)
            self._log_line("      pas sur le boîtier USB → le parc ne peut pas réagir.", dim)
            self._log_line("      ✅  SOLUTION : à l'ÉTAPE 3 ci-dessous, cliquez « Connecter »", ok)
            self._log_line("          pour basculer la sortie DMX sur votre boîtier USB.", ok)

        # Timer DMX — on lit la CADENCE RÉELLE, pas un texte en dur : le timer
        # a déjà été relancé à une période dégradée par un autre écran, et un
        # diagnostic qui annonce « 25 fps » sans mesurer ne peut pas le voir.
        timer_ok = False
        timer_ms = 0
        try:
            win = self._parent_win
            for attr in ('dmx_send_timer', 'dmx_timer', '_dmx_timer'):
                if win and hasattr(win, attr):
                    _t = getattr(win, attr)
                    timer_ok = _t.isActive()
                    timer_ms = _t.interval()
                    break
        except Exception:
            pass
        _fps = (1000.0 / timer_ms) if timer_ms > 0 else 0.0
        try:
            from core import DMX_FRAME_MS as _NOMINAL
        except Exception:
            _NOMINAL = 25
        _degrade = timer_ok and timer_ms > _NOMINAL
        timer_color = warn if (not timer_ok or _degrade) else ok
        if not timer_ok:
            timer_str = "inactif ou inconnu"
        else:
            timer_str = f"ACTIF ({_fps:.0f} fps, période {timer_ms} ms)"
        self._log_line(f"  Timer DMX : {timer_str}", timer_color)
        if _degrade:
            self._log_line(f"      ⚠  Cadence DÉGRADÉE : attendu {1000.0 / _NOMINAL:.0f} fps "
                           f"({_NOMINAL} ms).", warn)
            self._log_line("      → Redémarrez MyStrow pour retrouver la cadence nominale.", warn)

        # Sortie DMX activée dans le plan de feu ?
        try:
            win = self._parent_win
            pf = getattr(win, 'plan_de_feu', None)
            if pf and hasattr(pf, 'is_dmx_enabled'):
                dmx_on = pf.is_dmx_enabled()
                if dmx_on:
                    self._log_line("  ✓  Sortie DMX activée (bouton vert dans le plan de feu)", ok)
                else:
                    self._log_line("  ⚠  Sortie DMX DÉSACTIVÉE dans le plan de feu", warn)
                    self._log_line("      → Cliquez le bouton DMX (icône prise) pour l'activer", warn)
        except Exception:
            pass

        # Patch projecteurs
        try:
            n_patched = len(dmx.projector_channels)
            if n_patched == 0:
                self._log_line("  ⚠  Aucun projecteur patché — le patch DMX n'est pas configuré", warn)
                self._log_line("      → Ouvrez Paramètres › Patch DMX pour assigner les adresses", warn)
            else:
                self._log_line(f"  ✓  {n_patched} projecteur(s) patché(s)", ok)
        except Exception:
            pass

        # Données DMX actuelles (univers 0, canaux 1-10)
        try:
            uni0 = dmx.dmx_data[0] if dmx.dmx_data else []
            if uni0:
                vals = "  ".join(f"CH{i+1}={uni0[i]}" for i in range(10))
                self._log_line(f"  Univers 0 canaux 1-10 :", "#cccccc")
                self._log_line(f"    {vals}", "#888888")
                non_zero = sum(1 for v in uni0[:512] if v > 0)
                if non_zero == 0:
                    self._log_line("  ⚠  Tous les canaux sont à 0", warn)
                    self._log_line("      Causes possibles :", warn)
                    self._log_line("      • Sortie DMX désactivée (voir ci-dessus)", dim)
                    self._log_line("      • Aucun projecteur patché (voir ci-dessus)", dim)
                    self._log_line("      • Tous les projecteurs sont à niveau 0", dim)
                else:
                    self._log_line(f"  ✓  {non_zero} canaux non-nuls dans l'univers 0", ok)
        except Exception as e:
            self._log_line(f"  Impossible de lire dmx_data : {e}", err)

        self._log_line("")
        self._log_line("═══ FIN DU DIAGNOSTIC ═══", cyan)

    def _diag_d2xx_steps(self):
        """Étapes 4-6 du diagnostic en mode D2XX (driver FTDI direct)."""
        import time as _time
        ok = "#4CAF50"; warn = "#ff9800"; err = "#f44336"; dim = "#555555"; cyan = "#00d4ff"

        self._log_line("")
        self._log_line("[ 4 ] Driver FTDI D2XX (mode direct, comme QLC+)", cyan)
        if not FTD2XX_AVAILABLE or ftd2xx is None:
            self._log_line("  ✗  Module ftd2xx indisponible", err)
            self._log_line("      → pip install ftd2xx  (et pilote FTDI installé)", warn)
            return
        try:
            devices = ftd2xx.listDevices() or []
        except Exception as e:
            self._log_line(f"  ✗  Impossible de lister les puces FTDI : {e}", err)
            return
        if not devices:
            self._log_line("  ✗  Aucune puce FTDI détectée en D2XX", err)
            self._log_line("      → Fermez QLC+/autre logiciel DMX (la puce ne s'ouvre", warn)
            self._log_line("        que dans une seule application à la fois)", warn)
            return
        for i, sn in enumerate(devices):
            sn_s = sn.decode(errors="ignore") if isinstance(sn, bytes) else str(sn)
            self._log_line(f"  ★ FTDI  index {i}  —  série « {sn_s} »", ok)

        # ── 5/6 : ouverture + envoi de frames ────────────────────────────────
        self._log_line("")
        self._log_line("[ 5-6 ] Ouverture D2XX + envoi de 10 frames (CH1-4 = 255)", cyan)

        paused_live = False
        dev = None
        opened_here = False

        # Si MyStrow tient déjà la puce en D2XX (connexion live active), on NE
        # PEUT PAS rouvrir un 2e handle (DEVICE_NOT_OPENED) : on suspend le thread
        # live et on réutilise SON handle. Décision basée sur connected (le handle
        # peut être transitoirement nul pendant une reconnexion).
        live_active = (getattr(self._dmx, 'transport', '') == TRANSPORT_ENTTEC_D2XX
                       and getattr(self._dmx, 'connected', False))
        if live_active:
            self._dmx._d2xx_pause = True
            paused_live = True
            _wait = _time.monotonic() + 0.6
            while (_time.monotonic() < _wait
                   and not getattr(self._dmx, '_d2xx_paused', False)):
                QApplication.processEvents()
                _time.sleep(0.01)
            dev = getattr(self._dmx, '_d2xx', None)   # relire après la pause
            if dev is not None:
                self._log_line("  ⚠  Puce déjà ouverte par MyStrow — réutilisation (D2XX)", warn)
            else:
                self._log_line("  –  Connexion live active mais handle indisponible", warn)
                self._log_line("      → La sortie live MyStrow gère l'envoi (voir étape 7)", dim)
                self._dmx._d2xx_pause = False
                return
        else:
            try:
                index = self._dmx._resolve_d2xx_index()
                dev = ftd2xx.open(index)
                dev.setBaudRate(250000)
                dev.setDataCharacteristics(_ftd.BITS_8, _ftd.STOP_BITS_2, _ftd.PARITY_NONE)
                dev.setFlowControl(_ftd.FLOW_NONE, 0, 0)
                dev.setLatencyTimer(1)
                dev.setTimeouts(100, 100)
                dev.purge(_ftd.PURGE_TX | _ftd.PURGE_RX)
                opened_here = True
                self._log_line("  ✓  Puce FTDI ouverte (250 kbaud, latency 1 ms)", ok)
            except Exception as e:
                self._log_line(f"  ✗  Ouverture D2XX impossible : {e}", err)
                self._log_line("      → Fermez QLC+/autre logiciel DMX puis réessayez", warn)
                return

        frame = b'\x00' + bytes([255, 255, 255, 255] + [0] * 508)
        ok_count = 0
        last_err = ""
        for _ in range(10):
            try:
                dev.setBreakOn()
                _time.sleep(0.0001)
                dev.setBreakOff()
                _time.sleep(0.000012)
                dev.write(frame)
                ok_count += 1
            except Exception as e:
                last_err = str(e)
            _time.sleep(0.025)

        if ok_count == 10:
            self._log_line(f"  ✓  10/10 frames envoyées — DMX D2XX opérationnel", ok)
            self._log_line("      Si les projecteurs ne répondent pas → vérifiez le patch", warn)
        elif ok_count > 0:
            self._log_line(f"  ⚠  {ok_count}/10 frames OK — connexion instable", warn)
            if last_err:
                self._log_line(f"      Dernière erreur : {last_err[:60]}", err)
        else:
            self._log_line(f"  ✗  0/10 frames — envoi impossible", err)
            if last_err:
                self._log_line(f"      Erreur : {last_err[:70]}", err)

        if opened_here:
            try: dev.setBreakOff()
            except Exception: pass
            try: dev.close()
            except Exception: pass
        if paused_live:
            self._dmx._d2xx_pause = False

    def closeEvent(self, event):
        # Garde-fou : ne jamais laisser le thread ENTTEC en pause si le
        # dialogue est fermé pendant un Test 100% (sinon la sortie DMX reste
        # figée). On relâche toujours la pause à la fermeture.
        try:
            self._dmx._enttec_pause = False
        except Exception:
            pass
        try:
            self._dmx._d2xx_pause = False
        except Exception:
            pass
        # Le compte à rebours n'a plus de destinataire une fois la fenêtre fermée.
        # Le thread de connexion, lui, continue : il se libère seul (_PENDING_CONNECTS).
        if self._connect_timer is not None:
            self._connect_timer.stop()
        super().closeEvent(event)

    def _copy_report(self):
        """Copie le rapport de diagnostic dans le presse-papiers en texte brut."""
        text = self._log.toPlainText()
        if text.strip():
            QApplication.clipboard().setText(text)

    def _send_report(self):
        """Ouvre un mail au support avec le rapport USB pré-rempli."""
        from core import send_report_email
        prod = self._current_product()
        name = prod["name"] if prod else "interface inconnue"
        port = self.port_combo.currentData() or "aucun port"
        report = (f"Interface : {name}\nPort : {port}\n\n"
                  + self._log.toPlainText())
        send_report_email(
            self, "Diagnostic sortie DMX USB", report,
            intro="Bonjour,\n\nVoici le rapport du diagnostic de ma sortie DMX USB.")

    # ── Connexion ───────────────────────────────────────────────────────────

    def _connect(self):
        """Lance la connexion dans un thread, avec abandon au bout du délai.

        L'ouverture du port ne se fait plus sur le thread GUI : sur macOS un
        boîtier qui ne répond pas figeait l'application entière, sans issue.
        """
        prod = self._current_product()
        if not prod:
            return

        # Ré-entrance : tant qu'un thread de connexion tourne, un 2e clic
        # lancerait un second connect() par-dessus le premier → deux writers
        # sur la même puce. Le bouton est désactivé, mais on verrouille aussi
        # ici car un clic peut déjà être en file d'attente.
        if self._connect_worker is not None:
            return

        port = self.port_combo.currentData()
        if not port:
            self._set_connect("Sélectionnez un port COM valide", error=True)
            return

        self.btn_connect.setEnabled(False)
        self._set_connect("Connexion en cours…")
        self._connect_timed_out = False
        self._connect_name = prod["name"]

        worker = _ConnectWorker(self._dmx, prod, port)
        self._connect_worker = worker
        _PENDING_CONNECTS.add(worker)
        # Libération portée par le thread lui-même : si le dialogue est fermé
        # avant la fin, ses slots sont déconnectés et ne rendraient jamais la
        # référence — le thread resterait dans le set pour toujours.
        worker.finished.connect(lambda w=worker: _PENDING_CONNECTS.discard(w))
        worker.result.connect(self._on_connect_result)
        worker.finished.connect(self._on_connect_finished)

        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self._on_connect_timeout)
        self._connect_timer.start(self.CONNECT_TIMEOUT_MS)
        worker.start()

    def _on_connect_timeout(self):
        """Délai dépassé : on rend la main sans figer l'interface.

        Le thread n'est pas tuable (il est coincé dans un appel système), on le
        laisse se terminer seul. Le bouton reste désactivé jusque-là : relancer
        une connexion en parallèle de celle qui traîne recréerait exactement le
        double writer qu'on cherche à éviter.
        """
        self._connect_timed_out = True
        self._set_connect("✗  Délai dépassé — le boîtier ne répond pas", error=True)
        self._journal(
            f"Sortie DMX : {self._connect_name} ne répond pas — délai dépassé", "error")

    def _on_connect_result(self, ok, transport):
        """Résultat du thread — peut arriver après le délai (connexion lente)."""
        if self._connect_timer is not None:
            self._connect_timer.stop()
        if ok:
            mode = {TRANSPORT_ENTTEC_D2XX: "D2XX",
                    TRANSPORT_ENTTEC_PRO:  "ENTTEC Pro"}.get(transport, "série")
            self._set_connect(f"✓  {self._connect_name} connecté ({mode})", ok=True)
            self._journal(
                f"Sortie DMX : {self._connect_name} connecté "
                f"({mode}) — {self._dmx.com_port}", "success")
        elif not self._connect_timed_out:
            # Après un timeout on garde le message de délai dépassé, plus parlant.
            self._set_connect("✗  Échec de la connexion", error=True)
            self._journal(
                f"Sortie DMX : échec de connexion — {self._connect_name}", "error")

    def _on_connect_finished(self):
        """Le thread est terminé : on relâche le verrou et le bouton."""
        worker = self._connect_worker
        self._connect_worker = None
        if worker is not None:
            _PENDING_CONNECTS.discard(worker)
            worker.deleteLater()
        self.btn_connect.setEnabled(True)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _set_connect(self, text, ok=False, error=False):
        color = "#4CAF50" if ok else ("#f44336" if error else "#555")
        self.lbl_connect.setText(text)
        self.lbl_connect.setStyleSheet(f"color: {color};")

    def _journal(self, text: str, level: str = "info"):
        """Écrit dans le journal de la fenêtre principale, si elle est joignable.

        L'assistant s'ouvre aussi depuis le diagnostic, parfois sans parent :
        l'absence de journal ne doit jamais gêner la connexion.
        """
        win = self._parent_win
        if win is not None and hasattr(win, '_log_message'):
            try:
                win._log_message(text, level)
            except Exception:
                pass


# Alias de compatibilité
EnttecSetupDialog = DmxSetupDialog
