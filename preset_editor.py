"""
Éditeur de blocs de preset — MyStrow

Un canal de type `Preset1..4` porte une fonction à valeurs pré-enregistrées de
l'appareil : « Auto 1 », « Sound active », « Fondu », « Blackout »… Cet éditeur
associe un NOM à chaque valeur DMX, exactement comme l'éditeur de roue de gobos
le fait pour les positions d'une roue — mais sans couleur, et surtout sans le
moindre effet sur le rendu 2D/3D.

C'est ce qui manquait dans MyStrow : `Gobo1` et `ColorWheel` étaient les deux
seuls types de canaux à offrir des presets nommés, et tous deux dessinent
quelque chose à l'écran. Qui voulait des presets sur un canal de programme
déclarait donc son canal en « Gobo » puis le renommait — et son PAR LED se
couvrait de motifs de gobo (cf. `core.fixture_projects_gobo`).
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QCheckBox, QApplication, QSlider,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QCursor

from i18n import tr
# Ligne d'édition, styles et boutons sont partagés avec l'éditeur de roue : même
# dialogue, même grammaire visuelle. Les dupliquer aurait garanti la dérive.
from color_wheel_editor import (
    _SlotRow, _DLG_SS, _BTN_ADD, _BTN_SAVE, _BTN_CANCEL,
)

# Blocs proposés quand le canal n'en a encore aucun. Volontairement VIDES de
# valeur (dmx=0) sauf le premier : inventer des valeurs de macro ferait
# déclencher à l'appareil un programme que personne n'a choisi. L'utilisateur
# lit la notice de son appareil et remplit — c'est le geste de calibration.
_GENERIC_PRESET_SLOTS = [
    {"name": "Arrêt", "color": "#888888", "dmx": 0},
]


class PresetEditorDialog(QDialog):
    """Éditeur des blocs nommés d'un canal de preset.

    Args:
        proj:           Projecteur source
        ch_type:        « Preset1 » … « Preset4 »
        all_projectors: Tous les projecteurs (pour « appliquer au même modèle »)
        main_window:    Fenêtre principale (pour save_dmx_patch_config)
        parent:         Widget parent Qt
    """

    def __init__(self, proj, ch_type: str, all_projectors: list,
                 main_window=None, parent=None):
        super().__init__(parent)
        self._proj           = proj
        self._ch_type        = ch_type
        self._all_projectors = all_projectors or []
        self._main_window    = main_window
        self._rows: list = []
        # Valeur d'origine : le curseur de test écrit en direct dans le
        # projecteur, Annuler doit pouvoir la rendre.
        self._attr     = f"preset{ch_type[-1]}"
        self._val_init = int(getattr(proj, self._attr, 0) or 0)

        _num = ch_type[-1]
        self.setWindowTitle(tr("pst_title", a0=_num, a1=proj.name or proj.group))
        self.setMinimumSize(480, 460)
        self.resize(520, 540)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_DLG_SS)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── En-tête ───────────────────────────────────────────────────────
        title_lbl = QLabel(tr("pst_blocks", a0=_num))
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_lbl.setStyleSheet("color:#00cc99;")
        root.addWidget(title_lbl)

        # Nom constructeur du canal, quand on le connaît : sur un appareil qui a
        # plusieurs canaux de programme, « Preset 2 » ne dit pas lequel on règle.
        _label = self._channel_label()
        if _label:
            ch_lbl = QLabel(_label)
            ch_lbl.setStyleSheet("color:#00cc99;font-size:11px;font-weight:bold;")
            root.addWidget(ch_lbl)

        sub_lbl = QLabel(tr("pst_intro"))
        sub_lbl.setStyleSheet("color:#666;font-size:11px;")
        sub_lbl.setWordWrap(True)
        root.addWidget(sub_lbl)

        existing = list((getattr(proj, 'preset_slots', None) or {}).get(ch_type, []))
        if not existing:
            existing = [dict(s) for s in _GENERIC_PRESET_SLOTS]

        # ── Curseur test en direct ────────────────────────────────────────
        # C'est LE geste de calibration : on balaie, on regarde l'appareil, et
        # on note la valeur à laquelle le programme démarre.
        live_w = QWidget(); live_w.setAttribute(Qt.WA_StyledBackground, True)
        live_h = QHBoxLayout(live_w)
        live_h.setContentsMargins(0, 0, 0, 4); live_h.setSpacing(8)

        live_lbl = QLabel(tr("cwe_test_live"))
        live_lbl.setStyleSheet("color:#666;font-size:11px;min-width:70px;")
        live_h.addWidget(live_lbl)

        live_sli = QSlider(Qt.Horizontal)
        live_sli.setRange(0, 255)
        live_sli.setValue(self._val_init)
        live_sli.setStyleSheet(
            "QSlider::groove:horizontal{background:#2a2a2a;height:6px;border-radius:3px;}"
            "QSlider::handle:horizontal{background:#00cc99;width:14px;height:14px;"
            "border-radius:7px;margin:-4px 0;}"
            "QSlider::sub-page:horizontal{background:#00cc9944;border-radius:3px;}"
        )
        live_h.addWidget(live_sli, 1)

        live_val = QLabel(str(self._val_init))
        live_val.setStyleSheet("color:#00cc99;font-size:11px;min-width:28px;")
        live_h.addWidget(live_val)

        live_sli.valueChanged.connect(
            lambda v: self._on_live(v, live_val))
        root.addWidget(live_w)

        # ── Colonne headers ───────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0); hdr.setSpacing(6)
        for txt, w in [(tr("cwe_name"), 100), ("", 30), (tr("pst_dmx_col"), 100)]:
            l = QLabel(txt)
            l.setStyleSheet("color:#555;font-size:10px;")
            if w:
                l.setFixedWidth(w)
            hdr.addWidget(l)
        hdr.addStretch()
        root.addLayout(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(sep)

        # ── Zone scrollable des blocs ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:#141414;}"
            "QScrollBar:vertical{background:#111;width:6px;border:none;}"
            "QScrollBar::handle:vertical{background:#2a2a2a;border-radius:3px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        self._slots_container = QWidget()
        self._slots_container.setAttribute(Qt.WA_StyledBackground, True)
        self._slots_container.setStyleSheet("background: #141414;")
        self._slots_layout = QVBoxLayout(self._slots_container)
        self._slots_layout.setContentsMargins(0, 4, 0, 4)
        self._slots_layout.setSpacing(3)
        self._slots_layout.addStretch()
        scroll.setWidget(self._slots_container)
        root.addWidget(scroll, 1)

        for s in existing:
            self._add_slot(s)

        # ── Bouton ajouter ────────────────────────────────────────────────
        add_row = QHBoxLayout()
        btn_add = QPushButton(tr("pst_add"))
        btn_add.setFixedHeight(30)
        btn_add.setStyleSheet(_BTN_ADD)
        btn_add.setCursor(QCursor(Qt.PointingHandCursor))
        # Nouveau bloc pré-rempli à la valeur du curseur de test : on balaie
        # jusqu'au programme voulu, on clique « Ajouter », il ne reste qu'à le
        # nommer. Sans ça, il fallait relire la valeur et la ressaisir.
        btn_add.clicked.connect(lambda: self._add_slot(
            {"name": "", "color": "#888888", "dmx": live_sli.value()}
        ))
        add_row.addWidget(btn_add)
        add_row.addStretch()
        root.addLayout(add_row)

        # ── Appliquer aux appareils du même modèle ────────────────────────
        apply_sep = QFrame(); apply_sep.setFrameShape(QFrame.HLine)
        apply_sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(apply_sep)

        # Le critère est le PROFIL DMX, pas le nom : deux appareils qui ont le
        # même profil ont les mêmes macros sur le même canal. Se caler sur le nom
        # (comme l'éditeur de roue) laissait de côté les appareils renommés, et
        # attrapait des modèles différents nommés pareil.
        self._same_model = self._matching_projectors()
        self._chk_same = QCheckBox(
            tr("pst_apply_model", a0=len(self._same_model))
            if self._same_model else tr("pst_no_other")
        )
        self._chk_same.setEnabled(bool(self._same_model))
        self._chk_same.setChecked(bool(self._same_model))
        root.addWidget(self._chk_same)

        # ── Boutons finaux ────────────────────────────────────────────────
        btn_sep = QFrame(); btn_sep.setFrameShape(QFrame.HLine)
        btn_sep.setStyleSheet("background:#2a2a2a;max-height:1px;border:none;")
        root.addWidget(btn_sep)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton(tr("cwe_cancel"))
        btn_cancel.setStyleSheet(_BTN_CANCEL)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.clicked.connect(self._cancel)

        btn_save = QPushButton(tr("cwe_save"))
        btn_save.setStyleSheet(_BTN_SAVE)
        btn_save.setCursor(QCursor(Qt.PointingHandCursor))
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    # ── Aides ────────────────────────────────────────────────────────────────

    def _channel_label(self) -> str:
        """Nom constructeur du canal de preset, s'il est connu."""
        prof   = list(getattr(self._proj, 'dmx_profile', None) or [])
        labels = list(getattr(self._proj, 'channel_labels', None) or [])
        # ⚠️ Une liste de libellés désalignée désigne le mauvais canal : mieux
        # vaut aucun nom qu'un nom faux. Même règle que partout ailleurs.
        if len(labels) != len(prof) or self._ch_type not in prof:
            return ""
        return (labels[prof.index(self._ch_type)] or "").strip()

    def _matching_projectors(self) -> list:
        """Autres projecteurs qui portent le même canal au même endroit."""
        prof = list(getattr(self._proj, 'dmx_profile', None) or [])
        if self._ch_type not in prof:
            return []
        return [
            p for p in self._all_projectors
            if p is not self._proj
            and self._ch_type in (getattr(p, 'dmx_profile', None) or [])
        ]

    def _on_live(self, v, lbl):
        """Curseur de test : écrit en direct et surligne le bloc atteint."""
        lbl.setText(str(v))
        setattr(self._proj, self._attr, v)
        mw = self._main_window
        if mw is not None and getattr(mw, 'dmx', None):
            mw.dmx.update_from_projectors(
                getattr(mw, 'projectors', None) or self._all_projectors)
        # Dernier bloc franchi (`dmx <= v`), même règle que `core.cw_slot_at` :
        # une position occupe une plage, elle n'est pas un point.
        if self._rows:
            passed = [r for r in self._rows if r._dmx.value() <= v]
            active = (max(passed, key=lambda r: r._dmx.value())
                      if passed else self._rows[0])
            for r in self._rows:
                r.set_active(r is active)

    # ── Gestion des lignes ───────────────────────────────────────────────────

    def _add_slot(self, slot: dict):
        row_widget = _SlotRow(slot, self._slots_container, show_color=False)
        row_widget._btn_del.clicked.connect(lambda: self._remove_slot(row_widget))
        row_widget._btn_up.clicked.connect(lambda: self._move_slot(row_widget, -1))
        row_widget._btn_down.clicked.connect(lambda: self._move_slot(row_widget, +1))
        insert_idx = self._slots_layout.count() - 1
        self._slots_layout.insertWidget(insert_idx, row_widget)
        self._rows.append(row_widget)
        self._update_move_buttons()
        QApplication.processEvents()
        sa = self.findChild(QScrollArea)
        if sa:
            sa.verticalScrollBar().setValue(sa.verticalScrollBar().maximum())

    def _remove_slot(self, row_widget):
        if row_widget in self._rows:
            self._rows.remove(row_widget)
        self._slots_layout.removeWidget(row_widget)
        row_widget.deleteLater()
        self._update_move_buttons()

    def _move_slot(self, row_widget, direction: int):
        idx = self._rows.index(row_widget)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._rows):
            return
        self._rows[idx], self._rows[new_idx] = self._rows[new_idx], self._rows[idx]
        for r in self._rows:
            self._slots_layout.removeWidget(r)
        self._slots_layout.takeAt(0)
        for r in self._rows:
            self._slots_layout.addWidget(r)
        self._slots_layout.addStretch()
        self._update_move_buttons()

    def _update_move_buttons(self):
        for i, r in enumerate(self._rows):
            r._btn_up.setEnabled(i > 0)
            r._btn_down.setEnabled(i < len(self._rows) - 1)

    # ── Sortie ───────────────────────────────────────────────────────────────

    def _collect_slots(self) -> list:
        """Blocs retenus, sans la couleur — un preset n'en a pas.

        Une ligne sans nom ET à 0 est une ligne qu'on a ajoutée puis laissée
        vide : elle est écartée. En revanche un bloc nommé à 0 est légitime
        (« Arrêt », « Blackout » valent souvent 0), d'où le test sur le NOM et
        non sur la valeur.
        """
        out = []
        for r in self._rows:
            s = r.get_slot()
            if not s["name"] and not s["dmx"]:
                continue
            out.append({"name": s["name"], "dmx": int(s["dmx"])})
        return out

    def _cancel(self):
        """Annuler rend au canal la valeur qu'il avait en ouvrant."""
        setattr(self._proj, self._attr, self._val_init)
        mw = self._main_window
        if mw is not None and getattr(mw, 'dmx', None):
            mw.dmx.update_from_projectors(
                getattr(mw, 'projectors', None) or self._all_projectors)
        self.reject()

    def _save(self):
        slots = self._collect_slots()

        targets = [self._proj]
        if self._chk_same.isChecked():
            targets += self._same_model

        for p in targets:
            # Copie par projecteur : un dict partagé ferait que régler un
            # appareil les réglerait tous, silencieusement.
            store = dict(getattr(p, 'preset_slots', None) or {})
            if slots:
                store[self._ch_type] = [dict(s) for s in slots]
            else:
                # Tout supprimé = retour au curseur nu, pas un dict à moitié
                # rempli qui afficherait une rangée de boutons vide.
                store.pop(self._ch_type, None)
            p.preset_slots = store

        if self._main_window and hasattr(self._main_window, 'save_dmx_patch_config'):
            self._main_window.save_dmx_patch_config()

        self.accept()

    def get_slots(self) -> list:
        return self._collect_slots()
