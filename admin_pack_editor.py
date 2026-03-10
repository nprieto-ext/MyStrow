"""
Éditeur de packs de fixtures — Admin Panel MyStrow.

Widget autonome intégré dans l'onglet "Packs" de l'admin panel.
Permet de créer / modifier des packs de fixtures et de les publier sur Firestore.

Layout :
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Liste des packs (gauche) │  Éditeur 3 colonnes (droite)            │
  │  - Pack A                │  Fabricants │ Fixtures │ Formulaire      │
  │  - Pack B   ◀ sélectionné│             │          │ Nom, Type...    │
  │  [+ Nouveau] [🗑 Suppr.]  │             │          │ Canaux R G B... │
  ├──────────────────────────────────────────────────────────────────────┤
  │  Status bar       [Charger depuis Firestore]  [Publier ↑]           │
  └──────────────────────────────────────────────────────────────────────┘
"""

import copy
import re
import time

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QFrame,
    QScrollArea, QSplitter, QMessageBox, QInputDialog, QSizePolicy,
    QTextEdit, QAbstractItemView, QDialog,
)
from PySide6.QtCore import Qt, Signal, QThread, QObject, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen

# Réutilisation directe des widgets et constantes du fixture_editor de MyStrow
from fixture_editor import (
    DmxPreviewWidget, ChannelRowWidget,
    ALL_CHANNEL_TYPES, CHANNEL_COLORS, FIXTURE_TYPES, GROUP_OPTIONS,
)

# ── Palette (reprise depuis admin_panel) ──────────────────────────────────────
BG_MAIN  = "#1a1a1a"
BG_PANEL = "#111111"
BG_INPUT = "#2a2a2a"
ACCENT   = "#00d4ff"
GREEN    = "#2d7a3a"
ORANGE   = "#c47f17"
RED      = "#a83232"
TEXT     = "#ffffff"
TEXT_DIM = "#aaaaaa"

_BTN = lambda bg, fg="#fff", brd=None: (
    f"QPushButton {{ background:{bg}; color:{fg}; border:{'1px solid ' + brd if brd else 'none'};"
    f" border-radius:4px; font-size:12px; padding:5px 14px; }}"
    f"QPushButton:hover {{ opacity:0.85; }}"
    f"QPushButton:disabled {{ background:#252525; color:#444; border:1px solid #333; }}"
)

_STYLE_EDITOR = f"""
    QWidget     {{ background:{BG_MAIN}; color:{TEXT}; font-family:'Segoe UI',sans-serif; }}
    QLabel      {{ color:{TEXT}; border:none; background:transparent; }}
    QLineEdit   {{ background:{BG_INPUT}; color:{TEXT}; border:1px solid #3a3a3a;
                   border-radius:4px; padding:5px 10px; font-size:12px; }}
    QLineEdit:focus {{ border:1px solid {ACCENT}; }}
    QComboBox   {{ background:{BG_INPUT}; color:{TEXT}; border:1px solid #3a3a3a;
                   border-radius:4px; padding:4px 8px; font-size:12px; }}
    QComboBox::drop-down {{ border:none; width:18px; }}
    QComboBox QAbstractItemView {{ background:{BG_INPUT}; color:{TEXT};
                   selection-background-color:{ACCENT}; selection-color:#000; }}
    QListWidget {{ background:#1e1e1e; color:{TEXT}; border:1px solid #333;
                   border-radius:5px; font-size:12px; outline:none; }}
    QListWidget::item {{ padding:5px 10px; }}
    QListWidget::item:selected {{ background:{ACCENT}; color:#000; font-weight:bold; }}
    QListWidget::item:hover:!selected {{ background:#2a2a2a; }}
    QPushButton {{ background:{BG_INPUT}; color:{TEXT_DIM}; border:1px solid #444;
                   border-radius:4px; font-size:11px; padding:5px 12px; }}
    QPushButton:hover {{ background:#3a3a3a; color:{TEXT}; }}
    QPushButton:disabled {{ background:#1a1a1a; color:#333; border-color:#2a2a2a; }}
    QScrollArea {{ background:transparent; border:none; }}
    QScrollBar:vertical {{ background:{BG_INPUT}; width:6px; border-radius:3px; }}
    QScrollBar::handle:vertical {{ background:#444; border-radius:3px; min-height:16px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    QTextEdit   {{ background:{BG_INPUT}; color:{TEXT}; border:1px solid #3a3a3a;
                   border-radius:4px; padding:5px; font-size:12px; }}
    QSplitter::handle {{ background:#2a2a2a; }}
"""


# ──────────────────────────────────────────────────────────────────────────────
# Worker : chargement des packs existants depuis Firestore
# ──────────────────────────────────────────────────────────────────────────────

class _PackLoadWorker(QObject):
    finished = Signal(list)
    error    = Signal(str)

    def __init__(self, sa_path: str):
        super().__init__()
        self._sa_path = sa_path

    def run(self):
        try:
            import firebase_client as fc
            token = fc.get_admin_token(self._sa_path)
            packs_meta = fc.fetch_fixture_packs_index(token)
            full_packs = []
            for meta in packs_meta:
                pack_id = meta.get("id", "")
                try:
                    full = fc.fetch_fixture_pack(pack_id, token)
                    full_packs.append(full)
                except Exception:
                    # Pas de fixtures encore → utiliser les métadonnées
                    meta.setdefault("fixtures", [])
                    full_packs.append(meta)
            self.finished.emit(full_packs)
        except Exception as e:
            self.error.emit(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Worker : publication d'un pack sur Firestore
# ──────────────────────────────────────────────────────────────────────────────

class _PackPublishWorker(QObject):
    finished = Signal(int)   # nouvelle version
    error    = Signal(str)

    def __init__(self, pack_id: str, pack_data: dict, sa_path: str):
        super().__init__()
        self._pack_id   = pack_id
        self._pack_data = pack_data
        self._sa_path   = sa_path

    def run(self):
        try:
            import firebase_client as fc
            token  = fc.get_admin_token(self._sa_path)
            result = fc.write_fixture_pack(self._pack_id, self._pack_data, token)
            new_version = result.get("version", 1)
            self.finished.emit(new_version)
        except Exception as e:
            self.error.emit(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# NoScrollCombo — QComboBox sans scroll accidentel
# ──────────────────────────────────────────────────────────────────────────────

class _NoScroll(QComboBox):
    def wheelEvent(self, e):
        e.ignore()


# ──────────────────────────────────────────────────────────────────────────────
# Widget principal : AdminPackEditorWidget
# ──────────────────────────────────────────────────────────────────────────────

class AdminPackEditorWidget(QWidget):
    """
    Éditeur complet de packs de fixtures pour l'admin panel.
    Intègre : liste des packs, éditeur 3 colonnes, publication Firestore.
    Utilise le service_account.json pour un token admin qui bypass les règles Firestore.
    """

    def __init__(self, sa_path: str, parent=None):
        super().__init__(parent)
        self._sa_path        = sa_path
        self._id_token       = None   # résolu à la demande via _get_token()
        self._packs: list    = []          # [{id, name, description, version, fixtures:[]}]
        self._current_pack   = None        # dict du pack sélectionné
        self._channel_rows   = []          # liste des ChannelRowWidget actifs
        self._cur_fx_idx     = -1          # index fixture dans le pack courant
        self._load_thread    = None
        self._pub_thread     = None

        self.setStyleSheet(_STYLE_EDITOR)
        self._build_ui()

    def _get_token(self) -> str:
        """
        Retourne un Google OAuth2 access token issu du service_account.json.
        Ce token a un accès admin complet et bypass les règles Firestore.
        Le token est mis en cache et renouvelé si expiré.
        """
        import firebase_client as fc
        self._id_token = fc.get_admin_token(self._sa_path)
        return self._id_token

    # ── Construction UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Panneau gauche : liste des packs ─────────────────────────────────
        left = QFrame()
        left.setFixedWidth(210)
        left.setStyleSheet(f"QFrame {{ background:{BG_PANEL}; border-right:1px solid #2a2a2a; }}")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(10, 12, 10, 12)
        left_lay.setSpacing(8)

        lbl_packs = QLabel("Packs")
        lbl_packs.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_packs.setStyleSheet(f"color:{ACCENT};")
        left_lay.addWidget(lbl_packs)

        self._pack_list = QListWidget()
        self._pack_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._pack_list.currentRowChanged.connect(self._on_pack_selected)
        left_lay.addWidget(self._pack_list, 1)

        btn_new_pack = QPushButton("＋  Nouveau pack")
        btn_new_pack.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:#000; border:none;"
            f" border-radius:4px; font-weight:bold; font-size:11px; padding:6px 10px; }}"
            f"QPushButton:hover {{ background:#33e0ff; }}"
        )
        btn_new_pack.clicked.connect(self._new_pack)
        left_lay.addWidget(btn_new_pack)

        self._btn_del_pack = QPushButton("🗑  Supprimer le pack")
        self._btn_del_pack.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{RED}; border:1px solid #6a2020;"
            f" border-radius:4px; font-size:11px; padding:5px 10px; }}"
            f"QPushButton:hover {{ background:{RED}; color:#fff; }}"
            f"QPushButton:disabled {{ color:#333; border-color:#2a2a2a; }}"
        )
        self._btn_del_pack.setEnabled(False)
        self._btn_del_pack.clicked.connect(self._delete_pack)
        left_lay.addWidget(self._btn_del_pack)

        root.addWidget(left)

        # ── Panneau droit : éditeur fixtures ─────────────────────────────────
        right_container = QWidget()
        right_lay = QVBoxLayout(right_container)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # Metadata du pack (nom, description)
        self._meta_bar = self._build_meta_bar()
        right_lay.addWidget(self._meta_bar)

        # Éditeur 3 colonnes
        editor_area = self._build_editor_area()
        right_lay.addWidget(editor_area, 1)

        # Barre d'état + publication
        status_bar = self._build_status_bar()
        right_lay.addWidget(status_bar)

        root.addWidget(right_container, 1)

        # État initial : placeholder
        self._show_placeholder(True)

    def _build_meta_bar(self) -> QWidget:
        """Barre supérieure : nom du pack + description."""
        bar = QFrame()
        bar.setFixedHeight(60)
        bar.setStyleSheet(
            f"QFrame {{ background:{BG_PANEL}; border-bottom:1px solid #2a2a2a; }}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        lay.addWidget(QLabel("Nom :"))
        self._pack_name_edit = QLineEdit()
        self._pack_name_edit.setPlaceholderText("Nom du pack…")
        self._pack_name_edit.setFixedHeight(32)
        self._pack_name_edit.setFixedWidth(200)
        self._pack_name_edit.textChanged.connect(self._on_pack_meta_changed)
        lay.addWidget(self._pack_name_edit)

        lay.addWidget(QLabel("Description :"))
        self._pack_desc_edit = QLineEdit()
        self._pack_desc_edit.setPlaceholderText("Description courte du pack…")
        self._pack_desc_edit.setFixedHeight(32)
        self._pack_desc_edit.textChanged.connect(self._on_pack_meta_changed)
        lay.addWidget(self._pack_desc_edit, 1)

        self._pack_version_lbl = QLabel("v—")
        self._pack_version_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px;")
        lay.addWidget(self._pack_version_lbl)

        bar.setEnabled(False)   # activé quand un pack est sélectionné
        self._meta_bar_ref = bar
        return bar

    def _build_editor_area(self) -> QWidget:
        """Zone éditeur 3 colonnes : Fabricants | Fixtures | Formulaire."""
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # ── Colonne 1 : Fabricants ────────────────────────────────────────────
        mfr_panel = QWidget()
        mfr_panel.setMinimumWidth(130)
        mfr_panel.setMaximumWidth(180)
        mfr_lay = QVBoxLayout(mfr_panel)
        mfr_lay.setContentsMargins(8, 8, 4, 8)
        mfr_lay.setSpacing(4)

        lbl_mfr = QLabel("Fabricants")
        lbl_mfr.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px; font-weight:bold;")
        mfr_lay.addWidget(lbl_mfr)

        self._mfr_list = QListWidget()
        self._mfr_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._mfr_list.currentItemChanged.connect(self._on_mfr_changed)
        mfr_lay.addWidget(self._mfr_list, 1)
        splitter.addWidget(mfr_panel)

        # ── Colonne 2 : Liste fixtures du pack ────────────────────────────────
        fx_panel = QWidget()
        fx_panel.setMinimumWidth(170)
        fx_panel.setMaximumWidth(240)
        fx_lay = QVBoxLayout(fx_panel)
        fx_lay.setContentsMargins(4, 8, 4, 8)
        fx_lay.setSpacing(4)

        lbl_fx = QLabel("Fixtures du pack")
        lbl_fx.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px; font-weight:bold;")
        fx_lay.addWidget(lbl_fx)

        self._fx_list = QListWidget()
        self._fx_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._fx_list.currentRowChanged.connect(self._on_fx_selected)
        fx_lay.addWidget(self._fx_list, 1)

        # Boutons fixture (sous la liste)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._btn_new_fx = QPushButton("＋ Nouvelle")
        self._btn_new_fx.setFixedHeight(26)
        self._btn_new_fx.clicked.connect(self._new_fixture)
        btn_row.addWidget(self._btn_new_fx)

        self._btn_dup_fx = QPushButton("⎘ Dupliquer")
        self._btn_dup_fx.setFixedHeight(26)
        self._btn_dup_fx.setEnabled(False)
        self._btn_dup_fx.clicked.connect(self._duplicate_fixture)
        btn_row.addWidget(self._btn_dup_fx)
        fx_lay.addLayout(btn_row)

        splitter.addWidget(fx_panel)

        # ── Colonne 3 : Formulaire d'édition ─────────────────────────────────
        form_panel = QWidget()
        form_lay = QVBoxLayout(form_panel)
        form_lay.setContentsMargins(8, 8, 12, 8)
        form_lay.setSpacing(8)

        # Placeholder (affiché quand aucune fixture sélectionnée)
        self._form_placeholder = QLabel("Sélectionnez ou créez une fixture →")
        self._form_placeholder.setAlignment(Qt.AlignCenter)
        self._form_placeholder.setStyleSheet(f"color:{TEXT_DIM}; font-size:12px;")
        form_lay.addWidget(self._form_placeholder, 1)

        # Conteneur du formulaire réel (caché par défaut)
        self._form_widget = QWidget()
        self._form_widget.hide()
        form_inner = QVBoxLayout(self._form_widget)
        form_inner.setContentsMargins(0, 0, 0, 0)
        form_inner.setSpacing(8)

        # Nom de la fixture
        self._fx_name = QLineEdit()
        self._fx_name.setPlaceholderText("Nom de la fixture…")
        self._fx_name.setFixedHeight(32)
        form_inner.addWidget(self._fx_name)

        # Fabricant
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        lbl_f = QLabel("Fab. :")
        lbl_f.setFixedWidth(32)
        row1.addWidget(lbl_f)
        self._fx_mfr = QLineEdit()
        self._fx_mfr.setPlaceholderText("Fabricant…")
        self._fx_mfr.setFixedHeight(28)
        row1.addWidget(self._fx_mfr, 1)
        form_inner.addLayout(row1)

        # Type + Groupe
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        lbl_t = QLabel("Type :")
        lbl_t.setFixedWidth(36)
        row2.addWidget(lbl_t)
        self._fx_type = _NoScroll()
        for ft in FIXTURE_TYPES:
            self._fx_type.addItem(ft)
        self._fx_type.setFixedHeight(28)
        row2.addWidget(self._fx_type, 1)

        lbl_g = QLabel("Groupe :")
        row2.addWidget(lbl_g)
        self._fx_group = _NoScroll()
        for g in GROUP_OPTIONS:
            self._fx_group.addItem(g)
        self._fx_group.setFixedHeight(28)
        row2.addWidget(self._fx_group)
        form_inner.addLayout(row2)

        # Séparateur canaux
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2a2a2a; max-height:1px;")
        form_inner.addWidget(sep)

        # Ligne "Ajouter canal"
        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        lbl_ch = QLabel("Canal :")
        lbl_ch.setFixedWidth(44)
        add_row.addWidget(lbl_ch)
        self._add_ch_combo = _NoScroll()
        for ct in ALL_CHANNEL_TYPES:
            self._add_ch_combo.addItem(ct)
        self._add_ch_combo.setFixedHeight(26)
        add_row.addWidget(self._add_ch_combo, 1)
        btn_add_ch = QPushButton("＋")
        btn_add_ch.setFixedSize(26, 26)
        btn_add_ch.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:#000; border:none; border-radius:4px;"
            f" font-weight:bold; font-size:14px; }}"
            f"QPushButton:hover {{ background:#33e0ff; }}"
        )
        btn_add_ch.clicked.connect(self._add_channel)
        add_row.addWidget(btn_add_ch)
        form_inner.addLayout(add_row)

        # Scroll area des canaux
        ch_scroll = QScrollArea()
        ch_scroll.setWidgetResizable(True)
        ch_scroll.setMinimumHeight(120)
        ch_scroll.setMaximumHeight(240)
        ch_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._ch_container = QWidget()
        self._ch_vbox = QVBoxLayout(self._ch_container)
        self._ch_vbox.setContentsMargins(0, 0, 0, 0)
        self._ch_vbox.setSpacing(2)
        self._ch_vbox.addStretch()
        ch_scroll.setWidget(self._ch_container)
        form_inner.addWidget(ch_scroll, 1)

        # Prévisualisation DMX
        self._preview = DmxPreviewWidget()
        form_inner.addWidget(self._preview)

        # Boutons Sauvegarder / Supprimer
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(6)
        self._btn_save_fx = QPushButton("💾  Enregistrer")
        self._btn_save_fx.setStyleSheet(
            f"QPushButton {{ background:{GREEN}; color:#fff; border:none; border-radius:4px;"
            f" font-weight:bold; font-size:12px; padding:6px 14px; }}"
            f"QPushButton:hover {{ background:#3a9a4a; }}"
        )
        self._btn_save_fx.clicked.connect(self._save_fixture)
        btn_row2.addWidget(self._btn_save_fx, 1)

        self._btn_del_fx = QPushButton("🗑")
        self._btn_del_fx.setFixedSize(32, 32)
        self._btn_del_fx.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{RED}; border:1px solid #6a2020;"
            f" border-radius:4px; font-size:14px; }}"
            f"QPushButton:hover {{ background:{RED}; color:#fff; }}"
        )
        self._btn_del_fx.clicked.connect(self._delete_fixture)
        btn_row2.addWidget(self._btn_del_fx)
        form_inner.addLayout(btn_row2)

        form_lay.addWidget(self._form_widget, 1)
        splitter.addWidget(form_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)

        # Wrapper pour cacher/afficher selon sélection pack
        self._editor_splitter = splitter
        return splitter

    def _build_status_bar(self) -> QWidget:
        """Barre du bas : infos pack + boutons Charger/Publier."""
        bar = QFrame()
        bar.setFixedHeight(50)
        bar.setStyleSheet(
            f"QFrame {{ background:{BG_PANEL}; border-top:1px solid #2a2a2a; }}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        self._status_lbl = QLabel("Aucun pack sélectionné")
        self._status_lbl.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px;")
        lay.addWidget(self._status_lbl, 1)

        self._btn_load_fs = QPushButton("☁  Charger depuis Firestore")
        self._btn_load_fs.setFixedHeight(34)
        self._btn_load_fs.setStyleSheet(
            f"QPushButton {{ background:{BG_INPUT}; color:{TEXT_DIM}; border:1px solid #444;"
            f" border-radius:4px; font-size:11px; padding:0 14px; }}"
            f"QPushButton:hover {{ background:#3a3a3a; color:{TEXT}; }}"
        )
        self._btn_load_fs.clicked.connect(self._load_from_firestore)
        lay.addWidget(self._btn_load_fs)

        self._btn_publish = QPushButton("🚀  Publier sur Firestore")
        self._btn_publish.setFixedHeight(34)
        self._btn_publish.setEnabled(False)
        self._btn_publish.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:#000; border:none;"
            f" border-radius:4px; font-weight:bold; font-size:12px; padding:0 18px; }}"
            f"QPushButton:hover {{ background:#33e0ff; }}"
            f"QPushButton:disabled {{ background:#1a2a2a; color:#2a5a6a; border:1px solid #2a4a5a; }}"
        )
        self._btn_publish.clicked.connect(self._publish_pack)
        lay.addWidget(self._btn_publish)

        return bar

    # ── Placeholder ──────────────────────────────────────────────────────────

    def _show_placeholder(self, show: bool):
        """Affiche ou cache le placeholder 'sélectionnez un pack'."""
        self._meta_bar_ref.setEnabled(not show)
        self._editor_splitter.setEnabled(not show)
        self._btn_publish.setEnabled(not show)
        self._btn_del_pack.setEnabled(not show)

    # ── Gestion des packs ────────────────────────────────────────────────────

    def _new_pack(self):
        name, ok = QInputDialog.getText(
            self, "Nouveau pack", "Nom du pack :", text="Mon pack"
        )
        if not ok or not name.strip():
            return
        pack_id = re.sub(r"[^a-z0-9_]", "_", name.strip().lower())
        # Éviter les doublons d'ID
        existing_ids = {p.get("id", "") for p in self._packs}
        if pack_id in existing_ids:
            suffix = 2
            while f"{pack_id}_{suffix}" in existing_ids:
                suffix += 1
            pack_id = f"{pack_id}_{suffix}"

        new_pack = {
            "id":          pack_id,
            "name":        name.strip(),
            "description": "",
            "version":     0,
            "fixtures":    [],
        }
        self._packs.append(new_pack)
        item = QListWidgetItem(name.strip())
        item.setData(Qt.UserRole, len(self._packs) - 1)
        self._pack_list.addItem(item)
        self._pack_list.setCurrentRow(self._pack_list.count() - 1)

    def _delete_pack(self):
        if not self._current_pack:
            return
        name = self._current_pack.get("name", "?")
        reply = QMessageBox.question(
            self, "Supprimer le pack",
            f"Supprimer le pack « {name} » de Firestore ?\n\nCette action est irréversible.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        pack_id = self._current_pack.get("id", "")
        if pack_id:
            try:
                import firebase_client as fc
                fc.delete_fixture_pack(pack_id, self._get_token())
            except Exception as e:
                QMessageBox.warning(self, "Erreur", f"Suppression Firestore échouée :\n{e}")

        # Retirer de la liste locale
        self._packs = [p for p in self._packs if p.get("id") != pack_id]
        self._current_pack = None
        self._rebuild_pack_list()
        self._show_placeholder(True)
        self._status_lbl.setText("Pack supprimé.")

    def _on_pack_selected(self, row: int):
        if row < 0 or row >= len(self._packs):
            self._current_pack = None
            self._show_placeholder(True)
            return
        self._current_pack = self._packs[row]
        self._show_placeholder(False)
        self._cur_fx_idx = -1

        # Charger les métadonnées dans la barre
        self._pack_name_edit.blockSignals(True)
        self._pack_desc_edit.blockSignals(True)
        self._pack_name_edit.setText(self._current_pack.get("name", ""))
        self._pack_desc_edit.setText(self._current_pack.get("description", ""))
        self._pack_name_edit.blockSignals(False)
        self._pack_desc_edit.blockSignals(False)
        v = self._current_pack.get("version", 0)
        self._pack_version_lbl.setText(f"v{v}" if v else "Brouillon")

        self._rebuild_mfr_list()
        self._status_lbl.setText(
            f"{len(self._current_pack.get('fixtures', []))} fixture(s) dans ce pack"
        )

    def _on_pack_meta_changed(self):
        if not self._current_pack:
            return
        self._current_pack["name"]        = self._pack_name_edit.text().strip()
        self._current_pack["description"] = self._pack_desc_edit.text().strip()
        # Mettre à jour le label dans la liste
        row = self._pack_list.currentRow()
        if 0 <= row < self._pack_list.count():
            item = self._pack_list.item(row)
            if item:
                item.setText(self._current_pack["name"] or "Sans nom")

    def _rebuild_pack_list(self):
        self._pack_list.blockSignals(True)
        self._pack_list.clear()
        for i, p in enumerate(self._packs):
            n    = p.get("name", "?")
            nfx  = len(p.get("fixtures", []))
            item = QListWidgetItem(f"{n}  ({nfx} fx)")
            item.setData(Qt.UserRole, i)
            self._pack_list.addItem(item)
        self._pack_list.blockSignals(False)

    # ── Gestion des fabricants ────────────────────────────────────────────────

    def _rebuild_mfr_list(self):
        fixtures = self._current_pack.get("fixtures", []) if self._current_pack else []
        mfrs = sorted({f.get("manufacturer", "") for f in fixtures if f.get("manufacturer")})
        self._mfr_list.blockSignals(True)
        self._mfr_list.clear()
        all_item = QListWidgetItem("— Tous —")
        all_item.setData(Qt.UserRole, "")
        self._mfr_list.addItem(all_item)
        for m in mfrs:
            it = QListWidgetItem(m)
            it.setData(Qt.UserRole, m)
            self._mfr_list.addItem(it)
        self._mfr_list.setCurrentRow(0)
        self._mfr_list.blockSignals(False)
        self._rebuild_fx_list()

    def _on_mfr_changed(self, current, _prev):
        self._rebuild_fx_list()

    def _rebuild_fx_list(self):
        fixtures = self._current_pack.get("fixtures", []) if self._current_pack else []
        mfr_filter = ""
        cur = self._mfr_list.currentItem()
        if cur:
            mfr_filter = cur.data(Qt.UserRole) or ""

        self._fx_list.blockSignals(True)
        self._fx_list.clear()
        for i, fx in enumerate(fixtures):
            if mfr_filter and fx.get("manufacturer", "") != mfr_filter:
                continue
            label = fx.get("name", "—")
            ch_count = len(fx.get("profile", []))
            item = QListWidgetItem(f"{label}  [{ch_count}ch]")
            item.setData(Qt.UserRole, i)   # index réel dans fixtures[]
            self._fx_list.addItem(item)
        self._fx_list.blockSignals(False)

    # ── Gestion des fixtures ─────────────────────────────────────────────────

    def _on_fx_selected(self, row: int):
        if row < 0:
            self._cur_fx_idx = -1
            self._form_widget.hide()
            self._form_placeholder.show()
            self._btn_dup_fx.setEnabled(False)
            return
        item = self._fx_list.item(row)
        if not item:
            return
        real_idx = item.data(Qt.UserRole)
        fixtures = self._current_pack.get("fixtures", [])
        if real_idx < 0 or real_idx >= len(fixtures):
            return
        self._cur_fx_idx = real_idx
        self._populate_form(fixtures[real_idx])
        self._form_placeholder.hide()
        self._form_widget.show()
        self._btn_dup_fx.setEnabled(True)

    def _populate_form(self, fx: dict):
        """Remplit le formulaire avec les données d'une fixture."""
        self._fx_name.setText(fx.get("name", ""))
        self._fx_mfr.setText(fx.get("manufacturer", ""))

        ft = fx.get("fixture_type", "PAR LED")
        idx = FIXTURE_TYPES.index(ft) if ft in FIXTURE_TYPES else 0
        self._fx_type.setCurrentIndex(idx)

        grp = fx.get("group", "face")
        gi  = GROUP_OPTIONS.index(grp) if grp in GROUP_OPTIONS else 0
        self._fx_group.setCurrentIndex(gi)

        self._rebuild_channel_rows(fx.get("profile", []))

    def _rebuild_channel_rows(self, profile: list):
        """Reconstruit les lignes de canaux depuis un profil."""
        # Supprimer les anciens widgets
        for row_w in self._channel_rows:
            row_w.setParent(None)
            row_w.deleteLater()
        self._channel_rows.clear()

        # Retirer le stretch existant
        while self._ch_vbox.count():
            item = self._ch_vbox.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        for i, ch_type in enumerate(profile):
            self._append_channel_row(i + 1, ch_type)

        self._ch_vbox.addStretch()
        self._update_preview()

    def _append_channel_row(self, ch_num: int, ch_type: str):
        row_w = ChannelRowWidget(ch_num, ch_type)
        row_w.remove_requested.connect(self._remove_channel_row)
        row_w.move_up_requested.connect(self._move_channel_up)
        row_w.move_dn_requested.connect(self._move_channel_dn)
        row_w.changed.connect(self._update_preview)
        # Insérer avant le stretch
        insert_pos = max(0, self._ch_vbox.count() - 1)
        self._ch_vbox.insertWidget(insert_pos, row_w)
        self._channel_rows.append(row_w)

    def _add_channel(self):
        ch_type = self._add_ch_combo.currentText()
        ch_num  = len(self._channel_rows) + 1
        self._append_channel_row(ch_num, ch_type)
        self._update_preview()

    def _remove_channel_row(self, row_w: ChannelRowWidget):
        if row_w in self._channel_rows:
            self._channel_rows.remove(row_w)
        row_w.setParent(None)
        row_w.deleteLater()
        self._renumber_channels()
        self._update_preview()

    def _move_channel_up(self, row_w: ChannelRowWidget):
        idx = self._channel_rows.index(row_w) if row_w in self._channel_rows else -1
        if idx <= 0:
            return
        self._channel_rows[idx], self._channel_rows[idx - 1] = (
            self._channel_rows[idx - 1], self._channel_rows[idx]
        )
        self._reorder_channel_widgets()
        self._renumber_channels()
        self._update_preview()

    def _move_channel_dn(self, row_w: ChannelRowWidget):
        idx = self._channel_rows.index(row_w) if row_w in self._channel_rows else -1
        if idx < 0 or idx >= len(self._channel_rows) - 1:
            return
        self._channel_rows[idx], self._channel_rows[idx + 1] = (
            self._channel_rows[idx + 1], self._channel_rows[idx]
        )
        self._reorder_channel_widgets()
        self._renumber_channels()
        self._update_preview()

    def _reorder_channel_widgets(self):
        """Réinsère les widgets de canaux dans l'ordre de self._channel_rows."""
        for row_w in self._channel_rows:
            self._ch_vbox.removeWidget(row_w)
        stretch = self._ch_vbox.takeAt(self._ch_vbox.count() - 1)
        for row_w in self._channel_rows:
            self._ch_vbox.addWidget(row_w)
        if stretch:
            self._ch_vbox.addItem(stretch)

    def _renumber_channels(self):
        for i, row_w in enumerate(self._channel_rows):
            row_w._num_lbl.setText(f"{i + 1:02d}")

    def _current_profile(self) -> list:
        return [rw._combo.currentText() for rw in self._channel_rows]

    def _update_preview(self):
        self._preview.set_channels(self._current_profile())

    def _new_fixture(self):
        if not self._current_pack:
            return
        new_fx = {
            "name":         "Nouvelle fixture",
            "manufacturer": "",
            "fixture_type": "PAR LED",
            "group":        "face",
            "profile":      ["R", "G", "B"],
        }
        self._current_pack.setdefault("fixtures", []).append(new_fx)
        self._cur_fx_idx = len(self._current_pack["fixtures"]) - 1
        self._rebuild_mfr_list()
        self._fx_list.setCurrentRow(self._fx_list.count() - 1)
        self._update_pack_status()

    def _duplicate_fixture(self):
        if not self._current_pack or self._cur_fx_idx < 0:
            return
        fixtures = self._current_pack.get("fixtures", [])
        if self._cur_fx_idx >= len(fixtures):
            return
        dup = copy.deepcopy(fixtures[self._cur_fx_idx])
        dup["name"] = dup.get("name", "") + " (copie)"
        fixtures.append(dup)
        self._cur_fx_idx = len(fixtures) - 1
        self._rebuild_mfr_list()
        self._fx_list.setCurrentRow(self._fx_list.count() - 1)
        self._update_pack_status()

    def _save_fixture(self):
        """Enregistre le formulaire dans la liste locale du pack."""
        if not self._current_pack or self._cur_fx_idx < 0:
            return
        fixtures = self._current_pack.setdefault("fixtures", [])
        if self._cur_fx_idx >= len(fixtures):
            return
        fx = fixtures[self._cur_fx_idx]
        fx["name"]         = self._fx_name.text().strip() or "Sans nom"
        fx["manufacturer"] = self._fx_mfr.text().strip()
        fx["fixture_type"] = self._fx_type.currentText()
        fx["group"]        = self._fx_group.currentText()
        fx["profile"]      = self._current_profile()
        self._rebuild_mfr_list()
        self._update_pack_status()
        self._status_lbl.setText(f"✓ Fixture « {fx['name']} » enregistrée localement.")

    def _delete_fixture(self):
        if not self._current_pack or self._cur_fx_idx < 0:
            return
        fixtures = self._current_pack.get("fixtures", [])
        if self._cur_fx_idx >= len(fixtures):
            return
        name = fixtures[self._cur_fx_idx].get("name", "?")
        if QMessageBox.question(
            self, "Supprimer",
            f"Supprimer la fixture « {name} » du pack ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        fixtures.pop(self._cur_fx_idx)
        self._cur_fx_idx = -1
        self._form_widget.hide()
        self._form_placeholder.show()
        self._btn_dup_fx.setEnabled(False)
        self._rebuild_mfr_list()
        self._update_pack_status()

    def _update_pack_status(self):
        n = len(self._current_pack.get("fixtures", [])) if self._current_pack else 0
        self._status_lbl.setText(f"{n} fixture(s) dans ce pack — non publié")
        # Mettre à jour le label dans la liste des packs
        row = self._pack_list.currentRow()
        if 0 <= row < self._pack_list.count():
            item = self._pack_list.item(row)
            if item and self._current_pack:
                item.setText(f"{self._current_pack.get('name', '?')}  ({n} fx)")

    # ── Chargement Firestore ─────────────────────────────────────────────────

    def _load_from_firestore(self):
        self._status_lbl.setText("Chargement depuis Firestore…")
        self._btn_load_fs.setEnabled(False)

        self._load_worker = _PackLoadWorker(self._sa_path)
        self._load_thread = QThread()
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.finished.connect(self._on_loaded)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.error.connect(self._load_thread.quit)
        self._load_thread.start()

    def _on_loaded(self, packs: list):
        self._btn_load_fs.setEnabled(True)
        self._packs = packs
        self._current_pack = None
        self._rebuild_pack_list()
        self._show_placeholder(True)
        n = len(packs)
        self._status_lbl.setText(
            f"{n} pack(s) chargé(s) depuis Firestore."
            if n else "Aucun pack trouvé sur Firestore."
        )

    def _on_load_error(self, msg: str):
        self._btn_load_fs.setEnabled(True)
        self._status_lbl.setText(f"Erreur chargement : {msg}")

    # ── Publication Firestore ────────────────────────────────────────────────

    def _publish_pack(self):
        if not self._current_pack:
            return
        name     = self._current_pack.get("name", "").strip()
        pack_id  = self._current_pack.get("id", "")
        n_fx     = len(self._current_pack.get("fixtures", []))

        if not name:
            QMessageBox.warning(self, "Nom requis", "Le pack doit avoir un nom avant d'être publié.")
            return
        if n_fx == 0:
            QMessageBox.warning(self, "Pack vide", "Ajoutez au moins une fixture avant de publier.")
            return

        v_next = self._current_pack.get("version", 0) + 1
        reply = QMessageBox.question(
            self, "Publier le pack",
            f"Publier « {name} » sur Firestore ?\n\n"
            f"  Pack ID : {pack_id}\n"
            f"  Fixtures : {n_fx}\n"
            f"  Nouvelle version : v{v_next}\n\n"
            f"Les utilisateurs pourront télécharger ce pack depuis MyStrow.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Construire le payload
        pack_data = {
            "name":        name,
            "description": self._current_pack.get("description", ""),
            "tags":        self._current_pack.get("tags", []),
            "fixtures":    self._current_pack.get("fixtures", []),
        }

        self._btn_publish.setEnabled(False)
        self._btn_publish.setText("Publication en cours…")
        self._status_lbl.setText("Envoi sur Firestore…")

        self._pub_worker = _PackPublishWorker(pack_id, pack_data, self._sa_path)
        self._pub_thread = QThread()
        self._pub_worker.moveToThread(self._pub_thread)
        self._pub_thread.started.connect(self._pub_worker.run)
        self._pub_worker.finished.connect(self._on_published)
        self._pub_worker.error.connect(self._on_publish_error)
        self._pub_worker.finished.connect(self._pub_thread.quit)
        self._pub_worker.error.connect(self._pub_thread.quit)
        self._pub_thread.start()

    def _on_published(self, new_version: int):
        self._btn_publish.setEnabled(True)
        self._btn_publish.setText("🚀  Publier sur Firestore")
        self._current_pack["version"] = new_version
        self._pack_version_lbl.setText(f"v{new_version}")
        n = len(self._current_pack.get("fixtures", []))
        self._status_lbl.setText(
            f"✓ Pack publié avec succès — v{new_version}  •  {n} fixture(s)"
        )
        self._status_lbl.setStyleSheet(f"color:#4CAF50; font-size:11px;")
        QTimer.singleShot(4000, lambda: self._status_lbl.setStyleSheet(
            f"color:{TEXT_DIM}; font-size:11px;"
        ))

    def _on_publish_error(self, msg: str):
        self._btn_publish.setEnabled(True)
        self._btn_publish.setText("🚀  Publier sur Firestore")
        self._status_lbl.setText(f"Erreur publication : {msg}")
        self._status_lbl.setStyleSheet(f"color:{RED}; font-size:11px;")
        QMessageBox.critical(self, "Erreur publication", msg)
        QTimer.singleShot(4000, lambda: self._status_lbl.setStyleSheet(
            f"color:{TEXT_DIM}; font-size:11px;"
        ))
