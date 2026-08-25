"""
Relecture d'un patch importe — MyStrow

`patch_import` lit le fichier et propose une correspondance ; ce module la fait
RELIRE avant d'y toucher. C'est tout l'enjeu : un patch venu d'ailleurs contient
toujours deux ou trois appareils que la bibliotheque ne connait pas, et les
patcher en silence donne un plan de feu faux que personne ne remarque avant la
salle. Chaque ligne montre donc d'ou vient son profil et ce qu'il faut verifier.

Les lignes inexploitables (univers au-dela des 4 d'Art-Net, adresse qui deborde
du canal 512) arrivent decochees : elles restent visibles, avec leur raison,
mais ne partent pas dans le patch.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QRadioButton,
    QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

import patch_import
from i18n import tr

_ACCENT = "#00d4ff"

# Pastille + couleur du texte par niveau de confiance. Le code couleur est le
# meme que partout dans l'app : cyan = sur, jaune = a relire, rouge = a refaire.
_CONF = {
    "exact":   ("✅", "#44cc88", "pimp_conf_exact"),
    "good":    ("✅", "#44cc88", "pimp_conf_good"),
    "approx":  ("⚠",  "#ffcc44", "pimp_conf_approx"),
    "generic": ("❌", "#ff6666", "pimp_conf_generic"),
}

_SS = f"""
QDialog {{ background:#141414; color:#e0e0e0; }}
QLabel {{ color:#aaa; font-size:12px; }}
QTableWidget {{
    background:#1a1a1a; color:#ddd; gridline-color:#262626;
    border:1px solid #2a2a2a; border-radius:6px; font-size:12px;
    selection-background-color:{_ACCENT}33; selection-color:#fff;
}}
QHeaderView::section {{
    background:#111; color:#8a8a8a; border:0; border-right:1px solid #262626;
    border-bottom:1px solid #262626; padding:6px 8px; font-size:11px;
}}
QPushButton {{
    background:#222; color:#ccc; border:1px solid #3a3a3a; border-radius:6px;
    padding:6px 14px; font-size:12px;
}}
QPushButton:hover {{ border-color:{_ACCENT}; color:#fff; }}
QPushButton#primary {{
    background:{_ACCENT}22; color:{_ACCENT}; border-color:{_ACCENT}66;
    font-weight:bold;
}}
QPushButton#primary:hover {{ background:{_ACCENT}33; }}
QRadioButton, QCheckBox {{ color:#bbb; font-size:12px; }}
QComboBox {{
    background:#1e1e1e; color:#ddd; border:1px solid #3a3a3a;
    border-radius:5px; padding:4px 8px; font-size:12px;
}}
QComboBox QAbstractItemView {{
    background:#1a1a1a; color:#ddd; selection-background-color:{_ACCENT}44;
}}
"""

# Colonnes
C_CHK, C_NAME, C_SRC, C_MODE, C_UNI, C_ADDR, C_CH, C_PROF, C_GRP, C_ISSUE = range(10)


class _GroupDelegate(QStyledItemDelegate):
    """Colonne « Groupe » : un combo, pas une saisie libre.

    Un delegate plutot qu'un QComboBox par ligne : sur un patch de 200 appareils,
    200 widgets vivants rendaient le defilement collant.
    """

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(patch_import.GROUPS)
        return cb

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data(Qt.DisplayRole) or "face")

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.DisplayRole)


class PatchImportDialog(QDialog):
    """Tableau de relecture. `selected_rows()` rend les lignes cochees."""

    def __init__(self, rows, warnings=None, current_count=0, parent=None):
        super().__init__(parent)
        self._rows = rows
        self.setWindowTitle(tr("pimp_title"))
        self.setStyleSheet(_SS)
        self.resize(1180, 660)
        self.setMinimumSize(880, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel(tr("pimp_title"))
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet("color:#fff;")
        root.addWidget(title)

        summary = patch_import.summarize(rows)
        lbl_sum = QLabel(tr("pimp_summary",
                            total=summary["total"],
                            ok=summary["exact"] + summary["good"],
                            approx=summary["approx"],
                            generic=summary["generic"],
                            blocking=summary["blocking"]))
        lbl_sum.setStyleSheet(f"color:{_ACCENT}; font-size:12px; font-weight:bold;")
        root.addWidget(lbl_sum)

        hint = QLabel(tr("pimp_intro"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        if warnings:
            box = QLabel("⚠  " + "\n⚠  ".join(warnings))
            box.setWordWrap(True)
            box.setStyleSheet(
                "color:#ffcc44; background:#ffcc4411; border:1px solid #ffcc4433;"
                " border-radius:6px; padding:8px 10px; font-size:11px;")
            root.addWidget(box)

        # ── Barre d'outils ────────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.setSpacing(8)
        b_all = QPushButton(tr("pimp_check_all"))
        b_none = QPushButton(tr("pimp_uncheck_all"))
        b_ok = QPushButton(tr("pimp_check_ok"))
        for b in (b_all, b_none, b_ok):
            bar.addWidget(b)
        bar.addSpacing(16)
        self.cb_group = QComboBox()
        self.cb_group.addItems(patch_import.GROUPS)
        bar.addWidget(self.cb_group)
        b_grp = QPushButton(tr("pimp_group_apply"))
        bar.addWidget(b_grp)
        bar.addStretch()
        root.addLayout(bar)

        # ── Tableau ───────────────────────────────────────────────────────────
        self.table = QTableWidget(len(rows), 10)
        self.table.setHorizontalHeaderLabels([
            "", tr("pimp_col_name"), tr("pimp_col_source"), tr("pimp_col_mode"),
            tr("pimp_col_uni"), tr("pimp_col_addr"), tr("pimp_col_ch"),
            tr("pimp_col_profile"), tr("pimp_col_group"), tr("pimp_col_issue"),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.SelectedClicked)
        self.table.setItemDelegateForColumn(C_GRP, _GroupDelegate(self.table))
        self.table.setAlternatingRowColors(False)
        self._fill()
        hdr = self.table.horizontalHeader()
        for col, mode in ((C_CHK, QHeaderView.Fixed), (C_UNI, QHeaderView.Fixed),
                          (C_ADDR, QHeaderView.Fixed), (C_CH, QHeaderView.Fixed),
                          (C_GRP, QHeaderView.Fixed)):
            hdr.setSectionResizeMode(col, mode)
        self.table.setColumnWidth(C_CHK, 34)
        self.table.setColumnWidth(C_UNI, 54)
        self.table.setColumnWidth(C_ADDR, 70)
        self.table.setColumnWidth(C_CH, 48)
        self.table.setColumnWidth(C_GRP, 92)
        hdr.setSectionResizeMode(C_NAME, QHeaderView.Interactive)
        hdr.setSectionResizeMode(C_ISSUE, QHeaderView.Stretch)
        self.table.setColumnWidth(C_NAME, 160)
        self.table.setColumnWidth(C_SRC, 190)
        self.table.setColumnWidth(C_MODE, 130)
        self.table.setColumnWidth(C_PROF, 200)
        root.addWidget(self.table, 1)

        # ── Cible de l'import ─────────────────────────────────────────────────
        low = QHBoxLayout()
        low.setSpacing(14)
        self.rb_replace = QRadioButton(tr("pimp_replace"))
        self.rb_append = QRadioButton(tr("pimp_append"))
        self.rb_replace.setChecked(True)
        # Sans patch en cours, « ajouter » et « remplacer » font la meme chose :
        # le choix n'a de sens que s'il y a quelque chose a ecraser.
        self.rb_append.setEnabled(current_count > 0)
        self.rb_replace.setEnabled(current_count > 0)
        low.addWidget(self.rb_replace)
        low.addWidget(self.rb_append)
        low.addStretch()
        self.btn_cancel = QPushButton(tr("mw_cancel"))
        self.btn_ok = QPushButton()
        self.btn_ok.setObjectName("primary")
        low.addWidget(self.btn_cancel)
        low.addWidget(self.btn_ok)
        root.addLayout(low)

        b_all.clicked.connect(lambda: self._set_all(True))
        b_none.clicked.connect(lambda: self._set_all(False))
        b_ok.clicked.connect(self._check_recognised)
        b_grp.clicked.connect(self._apply_group)
        self.table.itemChanged.connect(self._on_item_changed)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._accept)
        self._refresh_ok()

    # ── Remplissage ───────────────────────────────────────────────────────────
    def _fill(self):
        self.table.blockSignals(True)
        for i, r in enumerate(self._rows):
            icon, color, conf_key = _CONF.get(r["confidence"], _CONF["approx"])

            chk = QTableWidgetItem(icon)
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if r["include"] else Qt.Unchecked)
            chk.setToolTip(tr(conf_key))
            chk.setForeground(QColor(color))
            self.table.setItem(i, C_CHK, chk)

            def cell(text, editable=False, tip="", fg=None):
                it = QTableWidgetItem(str(text))
                flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
                if editable:
                    flags |= Qt.ItemIsEditable
                it.setFlags(flags)
                if tip:
                    it.setToolTip(tip)
                if fg:
                    it.setForeground(QColor(fg))
                return it

            src = " ".join(x for x in (r.get("manufacturer", ""),
                                       r.get("model", "")) if x)
            prof_txt = r["matched"] or tr("pimp_conf_generic")
            self.table.setItem(i, C_NAME, cell(r["name"], editable=True))
            self.table.setItem(i, C_SRC, cell(src))
            self.table.setItem(i, C_MODE, cell(r.get("mode", "")))
            self.table.setItem(i, C_UNI, cell(r["universe"] + 1))
            self.table.setItem(i, C_ADDR, cell(r["address"]))
            self.table.setItem(i, C_CH, cell(r["channels"]))
            self.table.setItem(i, C_PROF, cell(prof_txt, tip=" ".join(r["profile"]),
                                               fg=color))

            grp = QTableWidgetItem(r["group"])
            grp.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            self.table.setItem(i, C_GRP, grp)

            issue = cell(" · ".join(r["issues"]), tip="\n".join(r["issues"]),
                         fg="#ff6666" if r["blocking"] else "#ffcc44")
            self.table.setItem(i, C_ISSUE, issue)

            if r["blocking"]:
                for c in range(10):
                    self.table.item(i, c).setBackground(QColor("#3a1414"))
        self.table.blockSignals(False)

    # ── Actions de la barre ───────────────────────────────────────────────────
    def _set_all(self, state):
        self.table.blockSignals(True)
        for i, r in enumerate(self._rows):
            # Une ligne bloquante ne se coche pas, meme par « Tout cocher » :
            # l'importer sortirait de l'univers ou du canal 512.
            on = state and not r["blocking"]
            self.table.item(i, C_CHK).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.table.blockSignals(False)
        self._refresh_ok()

    def _check_recognised(self):
        self.table.blockSignals(True)
        for i, r in enumerate(self._rows):
            on = r["confidence"] in ("exact", "good") and not r["blocking"]
            self.table.item(i, C_CHK).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.table.blockSignals(False)
        self._refresh_ok()

    def _apply_group(self):
        grp = self.cb_group.currentText()
        rows = {ix.row() for ix in self.table.selectedIndexes()}
        if not rows:
            return
        self.table.blockSignals(True)
        for i in rows:
            self.table.item(i, C_GRP).setText(grp)
        self.table.blockSignals(False)

    def _on_item_changed(self, item):
        if item.column() == C_CHK:
            self._refresh_ok()

    def _checked_count(self):
        return sum(1 for i in range(self.table.rowCount())
                   if self.table.item(i, C_CHK).checkState() == Qt.Checked)

    def _refresh_ok(self):
        n = self._checked_count()
        self.btn_ok.setText(tr("pimp_do_import", n=n))
        self.btn_ok.setEnabled(n > 0)

    def _accept(self):
        if self._checked_count() == 0:
            QMessageBox.information(self, tr("pimp_title"), tr("pimp_nothing"))
            return
        self.accept()

    # ── Resultat ──────────────────────────────────────────────────────────────
    def replace_mode(self) -> bool:
        return self.rb_replace.isChecked()

    def selected_rows(self) -> list:
        """Lignes cochees, avec le nom et le groupe tels que relus a l'ecran."""
        out = []
        for i, r in enumerate(self._rows):
            if self.table.item(i, C_CHK).checkState() != Qt.Checked:
                continue
            row = dict(r)
            row["name"] = self.table.item(i, C_NAME).text().strip() or r["name"]
            grp = self.table.item(i, C_GRP).text().strip()
            row["group"] = grp if grp in patch_import.GROUPS else "face"
            out.append(row)
        return out


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entree : lire un fichier deja choisi, le faire relire
# ──────────────────────────────────────────────────────────────────────────────

def review_file(parent, path: str, current_count: int = 0):
    """Lit le patch designe par `path` et montre l'ecran de relecture.

    Le fichier est deja choisi par « Importer le patch » : c'est l'extension
    qui decide du lecteur, l'utilisateur n'a jamais a nommer un format. Rend
    (lignes, remplacer) ou None si l'utilisateur a renonce — a ce stade, RIEN
    n'a encore ete patche.
    """
    est_tableau = not path.lower().endswith(".qxw")
    parse = (patch_import.parse_table if est_tableau
             else patch_import.parse_qlcplus_workspace)
    try:
        entries, warnings = parse(path)
    except Exception as e:
        msg = str(e)
        if est_tableau:
            msg += "\n\n" + tr("pimp_table_hint")
        QMessageBox.critical(parent, tr("pimp_read_error"), msg)
        return None
    if not entries:
        QMessageBox.information(parent, tr("pimp_read_error"), tr("pimp_empty"))
        return None

    rows = patch_import.resolve(entries)
    dlg = PatchImportDialog(rows, warnings, current_count, parent)
    if dlg.exec() != QDialog.Accepted:
        return None
    return dlg.selected_rows(), dlg.replace_mode()
