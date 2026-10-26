"""Dialogue « Raccourcis clavier » : édition, presets, retour aux défauts.

Rien n'est écrit sur le disque tant qu'on n'a pas cliqué « Enregistrer » ;
les presets, eux, s'enregistrent dès leur création (comme un fichier).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QInputDialog, QKeySequenceEdit,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QToolButton, QVBoxLayout,
    QWidget,
)

import shortcuts
from i18n import tr

_BTN = """
    QPushButton { background: #333333; color: #dddddd; padding: 8px 16px;
                  border-radius: 6px; font-size: 13px; border: 1px solid #4a4a4a; }
    QPushButton:hover { background: #3a3a3a; color: #ffffff; }
    QPushButton:disabled { color: #666666; }
"""
_BTN_MAIN = """
    QPushButton { background: #00a8cc; color: #ffffff; padding: 8px 22px;
                  border-radius: 6px; font-size: 13px; font-weight: bold; border: none; }
    QPushButton:hover { background: #00c0e8; }
    QPushButton:disabled { background: #2a3a40; color: #6a7a80; }
"""
# Le champ visible est le QLineEdit interne du QKeySequenceEdit.
_EDIT_OK = ("QKeySequenceEdit QLineEdit { background: #111; color: #fff; border: 1px solid #444;"
            " border-radius: 4px; padding: 3px 6px; font-family: Consolas; font-size: 13px; }"
            "QKeySequenceEdit QLineEdit:focus { border: 1px solid #00d4ff; }")
_EDIT_ERR = ("QKeySequenceEdit QLineEdit { background: #2a1111; color: #fff; border: 1px solid #ff5555;"
             " border-radius: 4px; padding: 3px 6px; font-family: Consolas; font-size: 13px; }")

# Raccourcis gérés par d'autres fenêtres : affichés pour mémoire.
_OTHERS = [
    ("mwy_116", [("Ctrl + A", "mwy_118"), ("@mwy_119", "mwy_120"), ("@mwy_121", "mwy_122"),
                 ("1", "mwy_126"), ("2", "mwy_128"), ("3", "mwy_130"),
                 ("4", "mwy_132"), ("5", "mwy_134"), ("6", "mwy_136")]),
    ("mwy_137", [("@mwy_138", "sc_play"), ("Ctrl + Z", "mwy_141"), ("Ctrl + Y", "mwy_143"),
                 ("@mwy_144", "mwy_145"), ("Ctrl + A", "mwy_147"), ("Ctrl + C", "mwy_149"),
                 ("Ctrl + X", "mwy_151"), ("Ctrl + V", "mwy_153"), ("C", "mwy_155"),
                 ("@mwy_119", "mwy_157")]),
]


def _shown(seq: str) -> str:
    return QKeySequence(seq, QKeySequence.PortableText).toString(QKeySequence.NativeText) if seq \
        else tr("sc_none")


class ShortcutsDialog(QDialog):
    def __init__(self, parent, keys: dict):
        super().__init__(parent)
        self._keys = dict(keys)
        self._edits = {}
        self.setWindowTitle(tr("mw_shortcuts"))
        self.setMinimumSize(720, 680)
        self.setStyleSheet("""
            QDialog { background: #1a1a1a; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QScrollArea { border: none; background: #1a1a1a; }
            QWidget#shortcut_content { background: #1a1a1a; }
            QComboBox { background: #222; color: #eee; border: 1px solid #444;
                        border-radius: 4px; padding: 5px 8px; min-width: 200px; }
            QToolButton { background: transparent; color: #888; border: none; font-size: 15px; }
            QToolButton:hover { color: #fff; }
        """)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(20, 20, 20, 16)

        title = QLabel(tr("mw_shortcuts"))
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #ffffff;")
        lay.addWidget(title)
        hint = QLabel(tr("sc_hint"))
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #8a8a8a; font-size: 12px;")
        lay.addWidget(hint)

        # Presets
        prow = QHBoxLayout()
        prow.addWidget(QLabel(tr("sc_preset")))
        self._presets = QComboBox()
        prow.addWidget(self._presets, 1)
        self._btn_save_preset = QPushButton(tr("sc_preset_save"))
        self._btn_del_preset = QPushButton(tr("sc_preset_delete"))
        for b in (self._btn_save_preset, self._btn_del_preset):
            b.setStyleSheet(_BTN)
            b.setAutoDefault(False)
            prow.addWidget(b)
        lay.addLayout(prow)
        self._fill_presets()
        self._presets.activated.connect(self._load_preset)
        self._btn_save_preset.clicked.connect(self._save_preset)
        self._btn_del_preset.clicked.connect(self._delete_preset)

        # Liste
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("shortcut_content")
        sl = QVBoxLayout(content)
        sl.setSpacing(3)
        group = None
        for aid, default, label_key, group_key in shortcuts.ACTIONS:
            if group_key != group:
                group = group_key
                sl.addWidget(self._group_label(tr(group_key)))
            sl.addWidget(self._row(aid, default, tr(label_key)))
        sl.addWidget(self._group_label(tr("sc_others")))
        for group_key, rows in _OTHERS:
            sub = QLabel(f"  {tr(group_key)}")
            sub.setStyleSheet("color: #777; font-size: 11px; font-weight: bold; padding-top: 4px;")
            sl.addWidget(sub)
            for key, desc in rows:
                sl.addWidget(self._static_row(tr(key[1:]) if key.startswith("@") else key, tr(desc)))
        sl.addStretch()
        scroll.setWidget(content)
        lay.addWidget(scroll, 1)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #ff7777; font-size: 12px;")
        lay.addWidget(self._status)

        brow = QHBoxLayout()
        reset = QPushButton(tr("sc_reset_all"))
        reset.setStyleSheet(_BTN)
        reset.setAutoDefault(False)
        reset.clicked.connect(lambda: self._set_all(dict(shortcuts.DEFAULTS)))
        brow.addWidget(reset)
        brow.addStretch()
        cancel = QPushButton(tr("sc_cancel"))
        cancel.setStyleSheet(_BTN)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        self._ok = QPushButton(tr("sc_save"))
        self._ok.setStyleSheet(_BTN_MAIN)
        self._ok.setAutoDefault(False)
        self._ok.clicked.connect(self.accept)
        brow.addWidget(cancel)
        brow.addWidget(self._ok)
        lay.addLayout(brow)

        self._refresh()

    # -- construction --------------------------------------------------------
    @staticmethod
    def _group_label(text):
        lab = QLabel(f"  {text}")
        lab.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lab.setStyleSheet("color: #00d4ff; padding: 8px 0 2px 0;")
        return lab

    def _frame(self):
        f = QFrame()
        f.setStyleSheet("QFrame { background: #222222; border-radius: 6px; }"
                        "QFrame:hover { background: #2a2a2a; }")
        h = QHBoxLayout(f)
        h.setContentsMargins(12, 4, 8, 4)
        return f, h

    def _row(self, aid, default, label):
        f, h = self._frame()
        desc = QLabel(label)
        desc.setStyleSheet("color: #cccccc; font-size: 13px; background: transparent;")
        h.addWidget(desc, 1)
        ed = QKeySequenceEdit()
        ed.setMaximumSequenceLength(1)       # une seule combinaison, pas d'accords
        ed.setFixedWidth(190)
        inner = ed.findChild(QLineEdit)
        if inner is not None:
            inner.setPlaceholderText(tr("sc_none"))   # sinon « Press shortcut » en anglais
        ed.setKeySequence(QKeySequence(self._keys.get(aid, ""), QKeySequence.PortableText))
        ed.keySequenceChanged.connect(lambda seq, a=aid: self._changed(a, seq))
        h.addWidget(ed)
        clear = QToolButton()
        clear.setText("✕")
        clear.clicked.connect(lambda _=False, a=aid: self._set_one(a, ""))
        h.addWidget(clear)
        back = QToolButton()
        back.setText("↺")
        back.setToolTip(tr("sc_reset_one", seq=_shown(default)))
        back.clicked.connect(lambda _=False, a=aid: self._set_one(a, shortcuts.DEFAULTS[a]))
        h.addWidget(back)
        self._edits[aid] = ed
        return f

    def _static_row(self, key, desc):
        f, h = self._frame()
        d = QLabel(desc)
        d.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
        h.addWidget(d, 1)
        k = QLabel(key)
        k.setFixedWidth(190)
        k.setStyleSheet("color: #aaa; font-family: Consolas; font-size: 12px; background: transparent;")
        h.addWidget(k)
        h.addSpacing(52)
        return f

    # -- édition ---------------------------------------------------------------
    def _changed(self, aid, seq):
        self._keys[aid] = shortcuts.normalize(seq)
        self._refresh()

    def _set_one(self, aid, seq):
        ed = self._edits[aid]
        ed.blockSignals(True)
        ed.setKeySequence(QKeySequence(seq, QKeySequence.PortableText))
        ed.blockSignals(False)
        self._keys[aid] = shortcuts.normalize(seq)
        self._refresh()

    def _set_all(self, keys):
        for aid in self._edits:
            self._set_one(aid, keys.get(aid, ""))

    def _refresh(self):
        labels = {a[0]: tr(a[2]) for a in shortcuts.ACTIONS}
        bad = shortcuts.conflicts(self._keys)
        for aid, ed in self._edits.items():
            if aid in bad:
                other = bad[aid]
                ed.setStyleSheet(_EDIT_ERR)
                ed.setToolTip(tr("sc_conflict", other=labels[other]) if other in labels
                              else tr("sc_conflict_reserved", seq=_shown(other)))
            else:
                ed.setStyleSheet(_EDIT_OK)
                ed.setToolTip("")
        self._status.setText(tr("sc_conflicts_block", n=len(bad)) if bad else "")
        self._ok.setEnabled(not bad)
        self._btn_save_preset.setEnabled(not bad)

    # -- presets ---------------------------------------------------------------
    def _fill_presets(self, select=None):
        self._presets.clear()
        self._presets.addItem(tr("sc_preset_none"), None)
        for name in sorted(shortcuts.presets(), key=str.lower):
            self._presets.addItem(name, name)
        i = self._presets.findData(select) if select else 0
        self._presets.setCurrentIndex(max(i, 0))
        self._btn_del_preset.setEnabled(bool(select))

    def _load_preset(self, _index=None):
        name = self._presets.currentData()
        self._btn_del_preset.setEnabled(bool(name))
        if name:
            self._set_all(shortcuts.preset_keys(name))

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, tr("sc_preset_save"), tr("sc_preset_name"),
                                        text=self._presets.currentData() or "")
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in shortcuts.presets() and QMessageBox.question(
                self, tr("sc_preset_save"), tr("sc_preset_overwrite", name=name)) != QMessageBox.Yes:
            return
        shortcuts.save_preset(name, self._keys)
        self._fill_presets(select=name)

    def _delete_preset(self):
        name = self._presets.currentData()
        if not name or QMessageBox.question(
                self, tr("sc_preset_delete"), tr("sc_preset_delete_confirm", name=name)) != QMessageBox.Yes:
            return
        shortcuts.delete_preset(name)
        self._fill_presets()

    def keys(self) -> dict:
        return dict(self._keys)
