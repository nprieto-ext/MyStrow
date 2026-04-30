"""
Sequenceur - Gestion de la playlist et des sequences lumiere
"""
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QMenu, QComboBox, QFileDialog, QMessageBox, QDialog, QSlider
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QBrush, QCursor
try:
    from PySide6.QtMultimedia import QMediaPlayer
except ImportError:
    class QMediaPlayer:  # type: ignore
        PlayingState = 1; StoppedState = 0; PausedState = 2; EndOfMedia = 7
        def __init__(self): pass
        def setAudioOutput(self, *a): pass
        def setSource(self, *a): pass
        def play(self): pass
        def pause(self): pass
        def stop(self): pass
        def position(self): return 0
        def duration(self): return 0
        def setPosition(self, *a): pass
        def setPlaybackRate(self, *a): pass
        def playbackState(self): return QMediaPlayer.StoppedState
        def mediaStatus(self): return 0
        def source(self): return None
        playbackStateChanged = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
        mediaStatusChanged   = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
        positionChanged      = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
        durationChanged      = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()
        errorOccurred        = type('S', (), {'connect': lambda *a: None, 'disconnect': lambda *a: None})()

from core import fmt_time, media_icon, MIDI_AVAILABLE, rgb_to_akai_velocity, MEDIA_EXTENSIONS_FILTER
from i18n import tr


class Sequencer(QFrame):
    """Sequenceur de medias avec gestion des sequences lumiere"""

    def __init__(self, player_ui):
        super().__init__()
        self.player_ui = player_ui
        self.current_row = -1
        self.is_dirty = False

        # Systeme d'enregistrement de sequences
        self.sequences = {}  # {row: {"keyframes": [...], "duration": ms}}
        self.recording = False
        self.recording_row = -1
        self.recording_start_time = 0
        self.recording_timer = None

        # Timers pour playback
        self.playback_timer = None
        self.playback_row = -1
        self.playback_index = 0
        self.timeline_playback_timer = None
        self.tempo_timer = None
        self.tempo_elapsed = 0
        self.tempo_duration = 0
        self.tempo_running = False
        self.tempo_paused = False

        # Couleurs IA Lumiere par ligne
        self.ia_colors = {}  # {row: QColor}
        self.ia_analysis = {}  # {row: {"energy_map": [...], "beats": [...]}}
        self.image_durations = {}  # {row: seconds} - duree d'affichage des images
        self._loading = False  # Flag pour eviter dialog pendant load_show
        self._temp_players = []  # QMediaPlayer temporaires pour detection duree

        self._setup_ui()

    def _setup_ui(self):
        """Configure l'interface utilisateur"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header avec boutons
        header = QHBoxLayout()

        self.autosave_lbl = QLabel()
        self.autosave_lbl.setStyleSheet("color: #3a8a3a; font-size: 10px;")
        self.autosave_lbl.hide()
        header.addWidget(self.autosave_lbl)

        header.addStretch()

        btn_style = """
            QPushButton {
                background: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                color: #00d4ff;
                font-weight: bold;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: #3a3a3a;
                border: 1px solid #00d4ff;
            }
            QPushButton:pressed {
                background: #1a1a1a;
            }
        """

        self.up_btn = QPushButton("▲")
        self.up_btn.setFixedSize(40, 32)
        self.up_btn.setStyleSheet(btn_style)
        self.up_btn.clicked.connect(self.move_up)
        header.addWidget(self.up_btn)

        self.down_btn = QPushButton("▼")
        self.down_btn.setFixedSize(40, 32)
        self.down_btn.setStyleSheet(btn_style)
        self.down_btn.clicked.connect(self.move_down)
        header.addWidget(self.down_btn)

        self.del_btn = QPushButton("🗑")
        self.del_btn.setFixedSize(40, 32)
        self.del_btn.setStyleSheet(btn_style)
        self.del_btn.clicked.connect(self.delete_selected)
        header.addWidget(self.del_btn)

        self.add_btn = QPushButton("➕")
        self.add_btn.setFixedSize(40, 32)
        self.add_btn.setStyleSheet(btn_style + "QPushButton { font-size: 18px; }")
        self.add_btn.clicked.connect(self.show_add_menu)
        header.addWidget(self.add_btn)

        layout.addLayout(header)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", tr("seq_col_title"), tr("seq_col_duration"), tr("seq_col_vol"), "DMX"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_row_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(55)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnWidth(4, 110)
        self.table.setAcceptDrops(True)
        self.table.dragEnterEvent = self._on_drag_enter
        self.table.dragMoveEvent  = self._on_drag_move
        self.table.dropEvent      = self._on_drop
        self.table.setStyleSheet("""
            QTableWidget {
                background: #0a0a0a;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
                gridline-color: #1a1a1a;
                outline: none;
            }
            QTableWidget::item {
                padding: 10px 8px;
                border-bottom: 1px solid #1a1a1a;
                font-size: 14px;
                color: #e0e0e0;
                outline: none;
            }
            QTableWidget::item:selected {
                background: #2a4a5a;
                border-left: 3px solid #4a8aaa;
                outline: none;
            }
            QHeaderView::section {
                background: #1a1a1a;
                color: #999;
                padding: 10px 8px;
                border: none;
                border-bottom: 2px solid #2a2a2a;
                font-weight: bold;
                font-size: 11px;
            }
        """)

        layout.addWidget(self.table)

        # Timer pour mise a jour UI
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_ui_state)
        self.timer.start(200)

    def show_add_menu(self):
        """Menu contextuel pour ajouter media, pause ou tempo"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                border: 1px solid #2a2a2a;
                padding: 8px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
                color: #ddd;
            }
            QMenu::item:selected {
                background: #2a4a5a;
            }
        """)
        menu.addAction(tr("seq_menu_add_media"), self.add_files_dialog)
        menu.addAction(tr("seq_menu_add_pause"), self.add_pause)
        menu.exec(QCursor.pos())

    @staticmethod
    def _ci(text: str) -> "QTableWidgetItem":
        """QTableWidgetItem centré."""
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        return item

    def add_pause(self):
        """Ajoute une pause dans la sequence"""
        # Pendant le chargement, toujours ajouter à la fin pour respecter l'ordre du fichier.
        # En mode interactif, insérer après la sélection courante.
        if getattr(self, '_loading', False):
            r = self.table.rowCount()
        else:
            current = self.table.currentRow()
            r = current + 1 if current >= 0 else self.table.rowCount()

        self.table.insertRow(r)
        pause_icon = QTableWidgetItem("\u23f8\ufe0f")
        pause_icon.setData(Qt.UserRole, "\u23f8\ufe0f")
        self.table.setItem(r, 0, pause_icon)
        pause_item = QTableWidgetItem("PAUSE")
        pause_item.setData(Qt.UserRole, "PAUSE")
        self.table.setItem(r, 1, pause_item)
        self.table.setItem(r, 2, self._ci("--:--"))
        self.table.setItem(r, 3, self._ci("--"))
        self.table.setCellWidget(r, 4, self._create_dmx_cell_widget(r))
        self.table.selectRow(r)
        self.is_dirty = True

    def edit_pause_duration(self, row):
        """Edite la duree d'une pause avec un slider"""
        title_item = self.table.item(row, 1)
        if not title_item:
            return

        data = str(title_item.data(Qt.UserRole) or "")
        current_seconds = 30
        is_timed = data.startswith("PAUSE:")
        if is_timed:
            current_seconds = int(data.split(":")[1])

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("seq_dlg_pause_title"))
        dialog.setMinimumWidth(350)
        dialog.setStyleSheet("background: #1a1a1a; color: white;")

        layout = QVBoxLayout(dialog)

        value_label = QLabel(tr("seq_duration_seconds", n=current_seconds) if is_timed else tr("seq_indefinite"))
        value_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("color: #ffa500; padding: 10px;")
        layout.addWidget(value_label)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(10)
        slider.setMaximum(600)
        slider.setValue(current_seconds)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #3a3a3a;
                height: 8px;
                background: #1a1a1a;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #ffa500;
                border: 2px solid #ffcc00;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
        """)

        result = {"indefini": False}

        def update_label(value):
            minutes = value // 60
            seconds = value % 60
            if minutes > 0:
                value_label.setText(tr("seq_duration_min_sec", m=minutes, s=seconds, total=value))
            else:
                value_label.setText(tr("seq_duration_seconds", n=value))
            result["indefini"] = False

        slider.valueChanged.connect(update_label)
        layout.addWidget(slider)

        btn_layout = QHBoxLayout()

        indef_btn = QPushButton(tr("seq_btn_indefinite"))
        indef_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a3a;
                color: #aaaaff;
                border: 1px solid #4a4a6a;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background: #3a3a4a; }
        """)

        def set_indefini():
            result["indefini"] = True
            value_label.setText(tr("seq_indefinite"))

        indef_btn.clicked.connect(set_indefini)
        btn_layout.addWidget(indef_btn)

        ok_btn = QPushButton("✅ OK")
        ok_btn.clicked.connect(dialog.accept)
        ok_btn.setStyleSheet("""
            QPushButton {
                background: #2a4a5a;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton(tr("btn_cancel_x"))
        cancel_btn.clicked.connect(dialog.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
            }
        """)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            if result["indefini"]:
                title_item.setData(Qt.UserRole, "PAUSE")
                title_item.setText("PAUSE")
                dur_item = self.table.item(row, 2)
                if dur_item:
                    dur_item.setText("--:--")
                # Supprimer la sequence lumiere et retirer Play Lumiere
                self._remove_play_lumiere(row)
            else:
                value = slider.value()
                title_item.setData(Qt.UserRole, f"PAUSE:{value}")
                minutes = value // 60
                seconds = value % 60
                title_item.setText(f"Pause ({minutes}m {seconds}s)" if minutes > 0 else f"Pause ({value}s)")
                dur_item = self.table.item(row, 2)
                if dur_item:
                    dur_item.setText(f"{minutes:02d}:{seconds:02d}")

            self.is_dirty = True

    def _create_dmx_cell_widget(self, row):
        """Cree le widget composite pour la colonne DMX: bouton visible + combo caché"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        # Combo caché — toute la logique interne continue à l'utiliser
        combo = QComboBox(container)
        combo.addItems(["Manuel", "IA Lumiere"])
        combo.setCurrentText("Manuel")
        combo.setObjectName("dmx_combo")
        combo.hide()
        combo.wheelEvent = lambda event: event.ignore()
        combo.currentTextChanged.connect(
            lambda text, r=row: self.on_dmx_changed(r, text)
        )

        # Bouton visible
        btn = QPushButton("Manuel", container)
        btn.setObjectName("dmx_btn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        self._style_dmx_btn(btn, "Manuel")

        def _show_mode_menu(_, c=combo, b=btn, r=row):
            menu = QMenu(b)
            menu.setStyleSheet("""
                QMenu { background:#1a1a1a; border:1px solid #2a2a2a; padding:4px; }
                QMenu::item { padding:6px 18px; color:#ddd; border-radius:3px; }
                QMenu::item:selected { background:#2a4a5a; }
                QMenu::separator { height:1px; background:#2a2a2a; margin:3px 8px; }
            """)
            for i in range(c.count()):
                txt = c.itemText(i)
                act = menu.addAction(txt)
                act.setCheckable(True)
                act.setChecked(c.currentText() == txt)
            menu.addSeparator()
            rec_act = menu.addAction("✦ Rec Lumière")
            rec_act.setData("__rec__")
            chosen = menu.exec(b.mapToGlobal(b.rect().bottomLeft()))
            if not chosen:
                return
            if chosen.data() == "__rec__":
                QTimer.singleShot(0, lambda: self.open_light_editor_for_row(r))
            else:
                mode = chosen.text()
                QTimer.singleShot(0, lambda m=mode: c.setCurrentText(m))

        btn.clicked.connect(_show_mode_menu)
        layout.addWidget(btn)

        color_btn = QPushButton()
        color_btn.setFixedSize(14, 14)
        color_btn.setStyleSheet("background: transparent; border: none; border-radius: 3px;")
        color_btn.setVisible(False)
        color_btn.setObjectName("ia_color_indicator")
        color_btn.setCursor(Qt.PointingHandCursor)
        color_btn.setFlat(True)
        color_btn.clicked.connect(lambda _, r=row: self._on_color_indicator_clicked(r))
        layout.addWidget(color_btn)

        return container

    def _get_dmx_combo(self, row):
        """Extrait le QComboBox de la cellule DMX (col 4)"""
        widget = self.table.cellWidget(row, 4)
        if not widget:
            return None
        if isinstance(widget, QComboBox):
            return widget
        combo = widget.findChild(QComboBox, "dmx_combo")
        if combo:
            return combo
        if widget.layout():
            for i in range(widget.layout().count()):
                item = widget.layout().itemAt(i)
                if item and isinstance(item.widget(), QComboBox):
                    return item.widget()
        return None

    def _get_color_indicator(self, row):
        """Extrait le QPushButton indicateur couleur de la cellule DMX"""
        widget = self.table.cellWidget(row, 4)
        if not widget or isinstance(widget, QComboBox):
            return None
        return widget.findChild(QPushButton, "ia_color_indicator")

    def _update_color_indicator(self, row, color):
        """Met a jour l'indicateur couleur dans la cellule DMX"""
        indicator = self._get_color_indicator(row)
        if indicator:
            if color:
                indicator.setStyleSheet(
                    f"background: {color.name()}; border: 1px solid #666; border-radius: 4px;"
                )
                indicator.setVisible(True)
            else:
                indicator.setVisible(False)

    def move_up(self):
        row = self.table.currentRow()
        if row > 0:
            self.swap_rows(row, row - 1)
            self.table.selectRow(row - 1)
            self.is_dirty = True

    def move_down(self):
        row = self.table.currentRow()
        if 0 <= row < self.table.rowCount() - 1:
            self.swap_rows(row, row + 1)
            self.table.selectRow(row + 1)
            self.is_dirty = True

    def swap_rows(self, r1, r2):
        """Echange deux lignes"""
        try:
            for col in range(self.table.columnCount()):
                if col == 4:  # Colonne DMX avec widget composite
                    combo1 = self._get_dmx_combo(r1)
                    combo2 = self._get_dmx_combo(r2)
                    w1 = self.table.cellWidget(r1, col)
                    w2 = self.table.cellWidget(r2, col)

                    w1_data = combo1.currentText() if combo1 else None
                    w2_data = combo2.currentText() if combo2 else None

                    # Sauvegarder les couleurs IA et analyses
                    color1 = self.ia_colors.get(r1)
                    color2 = self.ia_colors.get(r2)
                    analysis1 = self.ia_analysis.get(r1)
                    analysis2 = self.ia_analysis.get(r2)

                    self.table.removeCellWidget(r1, col)
                    self.table.removeCellWidget(r2, col)

                    if w2_data:
                        self.table.setCellWidget(r1, col, self._create_dmx_cell_widget(r1))
                        new_combo1 = self._get_dmx_combo(r1)
                        if new_combo1:
                            new_combo1.blockSignals(True)
                            new_combo1.setCurrentText(w2_data)
                            new_combo1.blockSignals(False)
                            if w2_data == "IA Lumiere":
                                self._apply_ia_style(new_combo1)
                            elif w2_data == "Play Lumiere":
                                self._apply_play_lumiere_style(new_combo1)
                        if color2:
                            self.ia_colors[r1] = color2
                            self._update_color_indicator(r1, color2)
                        elif r1 in self.ia_colors:
                            del self.ia_colors[r1]
                        if analysis2:
                            self.ia_analysis[r1] = analysis2
                        elif r1 in self.ia_analysis:
                            del self.ia_analysis[r1]
                    elif w2:
                        self.table.setCellWidget(r1, col, QWidget())

                    if w1_data:
                        self.table.setCellWidget(r2, col, self._create_dmx_cell_widget(r2))
                        new_combo2 = self._get_dmx_combo(r2)
                        if new_combo2:
                            new_combo2.blockSignals(True)
                            new_combo2.setCurrentText(w1_data)
                            new_combo2.blockSignals(False)
                            if w1_data == "IA Lumiere":
                                self._apply_ia_style(new_combo2)
                            elif w1_data == "Play Lumiere":
                                self._apply_play_lumiere_style(new_combo2)
                        if color1:
                            self.ia_colors[r2] = color1
                            self._update_color_indicator(r2, color1)
                        elif r2 in self.ia_colors:
                            del self.ia_colors[r2]
                        if analysis1:
                            self.ia_analysis[r2] = analysis1
                        elif r2 in self.ia_analysis:
                            del self.ia_analysis[r2]
                    elif w1:
                        self.table.setCellWidget(r2, col, QWidget())
                else:
                    item1 = self.table.takeItem(r1, col)
                    item2 = self.table.takeItem(r2, col)
                    if item2:
                        self.table.setItem(r1, col, item2)
                    if item1:
                        self.table.setItem(r2, col, item1)

            # Swap image_durations
            dur1 = self.image_durations.get(r1)
            dur2 = self.image_durations.get(r2)
            if dur2 is not None:
                self.image_durations[r1] = dur2
            elif r1 in self.image_durations:
                del self.image_durations[r1]
            if dur1 is not None:
                self.image_durations[r2] = dur1
            elif r2 in self.image_durations:
                del self.image_durations[r2]

            # Swap sequences (rec lumière)
            seq1 = self.sequences.get(r1)
            seq2 = self.sequences.get(r2)
            if seq2 is not None:
                self.sequences[r1] = seq2
            elif r1 in self.sequences:
                del self.sequences[r1]
            if seq1 is not None:
                self.sequences[r2] = seq1
            elif r2 in self.sequences:
                del self.sequences[r2]

            if self.current_row == r1:
                self.current_row = r2
            elif self.current_row == r2:
                self.current_row = r1
        except Exception as e:
            print(f"Erreur swap_rows: {e}")

    def delete_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        if self.current_row in rows:
            QMessageBox.warning(self, tr("seq_delete_impossible_title"),
                tr("seq_delete_impossible_msg"))
            return
        for row in rows:
            self.table.removeRow(row)
            self._reindex_ia_colors(row)
            if self.current_row > row:
                self.current_row -= 1
        self.is_dirty = True

    def _reindex_ia_colors(self, deleted_row):
        """Reindexe ia_colors, ia_analysis et image_durations apres suppression d'une ligne"""
        if deleted_row in self.ia_colors:
            del self.ia_colors[deleted_row]
        new_colors = {}
        for old_row, color in self.ia_colors.items():
            if old_row < deleted_row:
                new_colors[old_row] = color
            elif old_row > deleted_row:
                new_colors[old_row - 1] = color
        self.ia_colors = new_colors

        if deleted_row in self.ia_analysis:
            del self.ia_analysis[deleted_row]
        new_analysis = {}
        for old_row, data in self.ia_analysis.items():
            if old_row < deleted_row:
                new_analysis[old_row] = data
            elif old_row > deleted_row:
                new_analysis[old_row - 1] = data
        self.ia_analysis = new_analysis

        if deleted_row in self.image_durations:
            del self.image_durations[deleted_row]
        new_durations = {}
        for old_row, dur in self.image_durations.items():
            if old_row < deleted_row:
                new_durations[old_row] = dur
            elif old_row > deleted_row:
                new_durations[old_row - 1] = dur
        self.image_durations = new_durations

    def clear_sequence(self):
        self.table.setRowCount(0)
        self.current_row = -1
        self.ia_colors = {}
        self.ia_analysis = {}
        self.image_durations = {}
        self.is_dirty = False

    def set_volume(self, row, value):
        vol = int(value / 1.27)
        if self.table.item(row, 3):
            self.table.item(row, 3).setText(str(vol))
            self.is_dirty = True

    def show_row_context_menu(self, pos):
        """Menu contextuel sur une ligne du sequenceur"""
        item = self.table.itemAt(pos)
        if not item:
            return

        selected_rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        row = item.row()

        _MENU_SS = """
            QMenu {
                background: #1a1a1a;
                border: 1px solid #2a2a2a;
                padding: 8px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
                color: #ddd;
            }
            QMenu::item:selected { background: #2a4a5a; }
        """

        # ── Multi-sélection ────────────────────────────────────────────────
        if len(selected_rows) > 1:
            menu = QMenu(self)
            menu.setStyleSheet(_MENU_SS)
            menu.addAction(f"{len(selected_rows)} tracks sélectionnés").setEnabled(False)
            menu.addSeparator()
            ia_act  = menu.addAction("Basculer en IA Lumiere")
            man_act = menu.addAction("Basculer en Manuel")
            menu.addSeparator()
            del_act = menu.addAction(f"Supprimer ({len(selected_rows)})")

            action = menu.exec(self.table.viewport().mapToGlobal(pos))

            if action == ia_act or action == man_act:
                mode = "IA Lumiere" if action == ia_act else "Manuel"
                for r in selected_rows:
                    title_item = self.table.item(r, 1)
                    if not title_item:
                        continue
                    d = str(title_item.data(Qt.UserRole) or "")
                    if d.startswith("PAUSE:") or d == "PAUSE" or d.startswith("TEMPO:"):
                        continue
                    combo = self._get_dmx_combo(r)
                    if combo and combo.currentText() != mode:
                        combo.blockSignals(True)
                        combo.setCurrentText(mode)
                        combo.blockSignals(False)
                        if mode == "IA Lumiere":
                            self._apply_ia_style(combo)
                        else:
                            self._apply_default_style(combo)
                self.is_dirty = True
            elif action == del_act:
                self.delete_selected()
            return

        # ── Sélection simple ───────────────────────────────────────────────
        title_item = self.table.item(row, 1)
        if not title_item:
            return
        data = title_item.data(Qt.UserRole)

        if data and (str(data) == "PAUSE" or str(data).startswith("PAUSE:")):
            menu = QMenu(self)
            menu.setStyleSheet(_MENU_SS)
            edit_action   = menu.addAction(tr("seq_menu_set_duration"))
            rec_action    = menu.addAction(tr("seq_menu_rec_light"))
            delete_action = menu.addAction(tr("seq_menu_delete"))
            action = menu.exec(self.table.viewport().mapToGlobal(pos))
            if action == edit_action:
                self.edit_pause_duration(row)
            elif action == rec_action:
                self.open_light_editor_for_row(row)
            elif action == delete_action:
                if row == self.current_row:
                    QMessageBox.warning(self, tr("seq_delete_impossible_title"),
                        tr("seq_delete_impossible_msg"))
                else:
                    self.table.removeRow(row)
                    self._reindex_ia_colors(row)
                    self.is_dirty = True
        else:
            self.show_media_context_menu(pos)

    def edit_duration(self, row):
        """Edite la duree d'une image ou d'une pause (methode unifiee)"""
        title_item = self.table.item(row, 1)
        if not title_item:
            return
        data = str(title_item.data(Qt.UserRole) or "")
        if data == "PAUSE" or data.startswith("PAUSE:"):
            self.edit_pause_duration(row)
        elif media_icon(data) == "image":
            self.edit_image_duration(row)

    def edit_image_duration(self, row):
        """Edite la duree d'affichage d'une image"""
        current_seconds = self.image_durations.get(row, 30)
        has_duration = row in self.image_durations

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("seq_dlg_display_duration_title"))
        dialog.setMinimumWidth(350)
        dialog.setStyleSheet("background: #1a1a1a; color: white;")

        layout = QVBoxLayout(dialog)

        value_label = QLabel(tr("seq_duration_seconds", n=current_seconds) if has_duration else tr("seq_indefinite"))
        value_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("color: #ffa500; padding: 10px;")
        layout.addWidget(value_label)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(5)
        slider.setMaximum(600)
        slider.setValue(current_seconds)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #3a3a3a;
                height: 8px;
                background: #1a1a1a;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #ffa500;
                border: 2px solid #ffcc00;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
        """)

        result = {"indefini": not has_duration}

        def update_label(value):
            minutes = value // 60
            seconds = value % 60
            if minutes > 0:
                value_label.setText(tr("seq_duration_min_sec", m=minutes, s=seconds, total=value))
            else:
                value_label.setText(tr("seq_duration_seconds", n=value))
            result["indefini"] = False

        slider.valueChanged.connect(update_label)
        layout.addWidget(slider)

        btn_layout = QHBoxLayout()

        indef_btn = QPushButton(tr("seq_btn_indefinite"))
        indef_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a3a;
                color: #aaaaff;
                border: 1px solid #4a4a6a;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background: #3a3a4a; }
        """)

        def set_indefini():
            result["indefini"] = True
            value_label.setText(tr("seq_indefinite"))

        indef_btn.clicked.connect(set_indefini)
        btn_layout.addWidget(indef_btn)

        ok_btn = QPushButton("✅ OK")
        ok_btn.clicked.connect(dialog.accept)
        ok_btn.setStyleSheet("""
            QPushButton {
                background: #2a4a5a;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton(tr("btn_cancel_x"))
        cancel_btn.clicked.connect(dialog.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
            }
        """)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            if result["indefini"]:
                if row in self.image_durations:
                    del self.image_durations[row]
                dur_item = self.table.item(row, 2)
                if dur_item:
                    dur_item.setText("--:--")
                # Supprimer la sequence lumiere et retirer Play Lumiere
                self._remove_play_lumiere(row)
            else:
                value = slider.value()
                self.image_durations[row] = value
                dur_item = self.table.item(row, 2)
                if dur_item:
                    minutes = value // 60
                    seconds = value % 60
                    dur_item.setText(f"{minutes:02d}:{seconds:02d}")

            self.is_dirty = True

    # ── Drag & drop fichiers ──────────────────────────────────────────────────
    def _on_drag_enter(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and media_icon(url.toLocalFile()) != "file":
                    event.acceptProposedAction()
                    return
        event.ignore()

    def _on_drag_move(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_drop(self, event):
        if event.mimeData().hasUrls():
            files = [url.toLocalFile() for url in event.mimeData().urls()
                     if url.isLocalFile()]
            if files:
                self.add_files(files)
                event.acceptProposedAction()
                return
        event.ignore()

    def add_files_dialog(self):
        files = QFileDialog.getOpenFileNames(self, tr("seq_dlg_add_media_title"), "", MEDIA_EXTENSIONS_FILTER)[0]
        if files:
            self.add_files(files)

    def add_files(self, files):
        for f in files:
            if media_icon(f) == "file":
                continue
            try:
                r = self.table.rowCount()
                self.table.insertRow(r)

                icon = media_icon(f)
                icon_text = {"audio": "\U0001f3b5", "video": "\U0001f3ac", "image": "\U0001f5bc"}.get(icon, "?")
                icon_item = QTableWidgetItem(icon_text)
                icon_item.setData(Qt.UserRole, icon_text)
                self.table.setItem(r, 0, icon_item)

                it = QTableWidgetItem(Path(f).name)
                it.setData(Qt.UserRole, f)
                self.table.setItem(r, 1, it)
                self.table.setItem(r, 2, self._ci("--:--"))
                self.table.setItem(r, 3, self._ci("--" if icon == "image" else "100"))

                self.table.setCellWidget(r, 4, self._create_dmx_cell_widget(r))

                # Charger la duree - garder le player en vie
                temp_p = QMediaPlayer()
                self._temp_players.append(temp_p)

                def update_duration(duration, row_idx=r, player=temp_p):
                    if duration > 0:
                        item = self.table.item(row_idx, 2)
                        if item:
                            item.setText(fmt_time(duration))
                    # Nettoyer dans tous les cas (durée trouvée ou 0 = fichier non lisible)
                    if player in self._temp_players:
                        self._temp_players.remove(player)
                        player.deleteLater()

                def _cleanup_on_status(status, player=temp_p):
                    from PySide6.QtMultimedia import QMediaPlayer as QMP
                    # Libérer si le media est chargé (avec ou sans durée) ou en erreur
                    if status in (QMP.MediaStatus.LoadedMedia,
                                  QMP.MediaStatus.InvalidMedia,
                                  QMP.MediaStatus.NoMedia):
                        if player in self._temp_players:
                            self._temp_players.remove(player)
                            player.deleteLater()

                temp_p.durationChanged.connect(update_duration)
                temp_p.mediaStatusChanged.connect(_cleanup_on_status)
                temp_p.setSource(QUrl.fromLocalFile(f))

            except Exception as e:
                print(f"Erreur ajout fichier: {e}")
                continue
        self.is_dirty = True

    # ── Styles des boutons DMX ────────────────────────────────────────────────
    _SS_BTN = {
        "Manuel": (
            "Manuel",
            "QPushButton{background:#1c1c1c;border:1px solid #2e2e2e;border-radius:8px;"
            "color:#555;font-size:11px;padding:3px 10px;}"
            "QPushButton:hover{border-color:#3a3a3a;color:#888;}"),
        "IA Lumiere": (
            "IA",
            "QPushButton{background:#0d1f3a;border:1px solid #2a5090;border-radius:8px;"
            "color:#6aadff;font-size:11px;font-weight:bold;padding:3px 10px;}"
            "QPushButton:hover{background:#152a4a;border-color:#4a80d0;}"),
        "Play Lumiere": (
            "▶ Seq",
            "QPushButton{background:#2a0d0d;border:1px solid #7a2020;border-radius:8px;"
            "color:#ff7070;font-size:11px;font-weight:bold;padding:3px 10px;}"
            "QPushButton:hover{background:#3a1010;border-color:#aa3030;}"),
        "Programme": (
            "PRG",
            "QPushButton{background:#0d2a0d;border:1px solid #207020;border-radius:8px;"
            "color:#70dd70;font-size:11px;font-weight:bold;padding:3px 10px;}"
            "QPushButton:hover{background:#103010;border-color:#30a030;}"),
    }

    def _style_dmx_btn(self, btn, mode: str):
        label, ss = self._SS_BTN.get(mode, (mode, self._SS_BTN["Manuel"][1]))
        btn.setText(label)
        btn.setStyleSheet(ss)

    def _refresh_dmx_btn(self, combo):
        container = combo.parent()
        if not container:
            return
        btn = container.findChild(QPushButton, "dmx_btn")
        if btn:
            self._style_dmx_btn(btn, combo.currentText())

    def _apply_ia_style(self, combo):
        self._refresh_dmx_btn(combo)

    def _apply_default_style(self, combo):
        self._refresh_dmx_btn(combo)

    def _apply_play_lumiere_style(self, combo):
        self._refresh_dmx_btn(combo)

    def _remove_play_lumiere(self, row):
        """Supprime la sequence lumiere et remet le combo DMX a Manuel"""
        if row in self.sequences:
            del self.sequences[row]
        combo = self._get_dmx_combo(row)
        if combo:
            idx = combo.findText("Play Lumiere")
            if idx != -1:
                combo.blockSignals(True)
                combo.setCurrentText("Manuel")
                combo.removeItem(idx)
                combo.blockSignals(False)
                self._apply_default_style(combo)
                self._update_color_indicator(row, None)

    def on_dmx_changed(self, row, text):
        """Gere le changement de mode DMX - affiche le dialog couleur si IA Lumiere"""
        combo = self._get_dmx_combo(row)
        if not combo:
            return

        # Si on quitte Play Lumiere, stopper le timer de timeline si c'est la ligne active
        if text != "Play Lumiere":
            if (getattr(self, 'timeline_playback_row', None) == row and
                    self.timeline_playback_timer and self.timeline_playback_timer.isActive()):
                self._stop_timeline_effect()
                self.timeline_playback_timer.stop()
                if hasattr(self, 'timeline_playback_row'):
                    del self.timeline_playback_row
                self.timeline_tracks_data = {}

        if text == "IA Lumiere":
            self._apply_ia_style(combo)

            if not self._loading:
                # Demander la couleur dominante
                color = self.player_ui.show_ia_color_dialog()
                if color:
                    self.ia_colors[row] = color
                    self._update_color_indicator(row, color)
                    # Lancer l'analyse audio immediatement
                    self._analyze_ia_for_row(row, color)
                else:
                    # Annule -> revenir a Manuel
                    combo.blockSignals(True)
                    combo.setCurrentText("Manuel")
                    combo.blockSignals(False)
                    self._apply_default_style(combo)
                    self._update_color_indicator(row, None)
                    return
            else:
                # Pendant le chargement, juste afficher l'indicateur si couleur existe
                if row in self.ia_colors:
                    self._update_color_indicator(row, self.ia_colors[row])
        elif text == "Play Lumiere":
            self._apply_play_lumiere_style(combo)
            self._update_color_indicator(row, None)
        else:
            self._apply_default_style(combo)
            self._update_color_indicator(row, None)

    def _analyze_ia_for_row(self, row, color):
        """Analyse audio pour une ligne IA Lumiere (au moment de la selection)"""
        # Recuperer le filepath du media
        item = self.table.item(row, 1)
        if not item:
            return
        filepath = item.data(Qt.UserRole)
        if not filepath or filepath in ("PAUSE",) or str(filepath).startswith("PAUSE:") or str(filepath).startswith("TEMPO:"):
            return

        import os
        if not os.path.isfile(filepath):
            return

        from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QProgressBar

        # Configurer l'IA
        self.player_ui.audio_ai.set_dominant_color(color)

        # Dialog de chargement
        loading = QDialog(self)
        loading.setWindowTitle("IA Lumiere")
        loading.setFixedSize(320, 90)
        loading.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        loading.setStyleSheet("""
            QDialog { background: #1a1a1a; border: 2px solid #00d4ff; border-radius: 10px; }
            QLabel { color: white; border: none; }
            QProgressBar { background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; text-align: center; color: white; }
            QProgressBar::chunk { background: #00d4ff; border-radius: 3px; }
        """)
        lay = QVBoxLayout(loading)
        lay.setContentsMargins(15, 10, 15, 10)
        label = QLabel(tr("seq_analyzing_audio"))
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 13px; font-weight: bold;")
        lay.addWidget(label)
        bar = QProgressBar()
        bar.setRange(0, 0)
        lay.addWidget(bar)
        loading.show()
        QApplication.processEvents()

        # Lancer l'analyse
        self.player_ui.audio_ai.analyze(filepath)

        # Stocker les resultats
        self.ia_analysis[row] = {
            "energy_map": list(self.player_ui.audio_ai.energy_map),
            "beats": list(self.player_ui.audio_ai.beats),
        }

        loading.close()
        print(f"IA Lumiere: analyse pre-calculee pour ligne {row}")

    def _on_color_indicator_clicked(self, row):
        """Clic sur le carre couleur - permet de changer la couleur sans re-analyser"""
        color = self.player_ui.show_ia_color_dialog()
        if color:
            self.ia_colors[row] = color
            self._update_color_indicator(row, color)
            self.player_ui.audio_ai.set_dominant_color(color)
            self.is_dirty = True

    def update_ui_state(self):
        for r in range(self.table.rowCount()):
            bg = "#0a0a0a"
            if r == self.current_row:
                combo = self._get_dmx_combo(r)
                if combo:
                    mode = combo.currentText()
                    if mode == "Manuel":
                        bg = "#1a3a5a"
                    elif mode == "IA Lumiere":
                        bg = "#5a1a1a"
                else:
                    dmx_widget = self.table.cellWidget(r, 4)
                    if not dmx_widget or (isinstance(dmx_widget, QWidget) and not isinstance(dmx_widget, QComboBox)):
                        bg = "#3a3a1a"

            for c in range(4):
                it = self.table.item(r, c)
                if it:
                    it.setBackground(QBrush(QColor(bg)))
                    it.setForeground(QBrush(QColor("#ffffff")))

    def update_playing_indicator(self, playing_row):
        """Met a jour l'emoji de lecture : 🟢 pour la ligne en cours, restaure l'original pour les autres"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                if row == playing_row:
                    item.setText("\U0001f7e2")
                else:
                    original = item.data(Qt.UserRole)
                    item.setText(original if original else "")

    def play_row(self, row):
        if 0 <= row < self.table.rowCount():
            try:
                self.update_playing_indicator(row)

                # Arreter le timer timeline du media precedent
                if self.timeline_playback_timer and self.timeline_playback_timer.isActive():
                    self._stop_timeline_effect()
                    self.timeline_playback_timer.stop()
                if hasattr(self, 'timeline_playback_row'):
                    del self.timeline_playback_row

                # Arreter les cartouches
                if hasattr(self.player_ui, '_stop_all_cartouches'):
                    self.player_ui._stop_all_cartouches()

                # Arreter tout playback precedent (timeline, keyframes, TEMPO)
                self.stop_sequence_playback()
                self.tempo_running = False
                self.tempo_paused = False
                if self.tempo_timer and self.tempo_timer.isActive():
                    self.tempo_timer.stop()

                item = self.table.item(row, 1)
                data = item.data(Qt.UserRole) if item else None

                # PAUSE temporisee (PAUSE:seconds)
                if data and str(data).startswith("PAUSE:"):
                    seconds = int(str(data).split(":")[1])
                    self.current_row = row
                    self.table.selectRow(row)
                    print(f"Pause temporisee: Attente de {seconds} secondes...")

                    self.player_ui.player.stop()
                    # Cacher l'image si affichee
                    if hasattr(self.player_ui, 'hide_image'):
                        self.player_ui.hide_image()
                    self.tempo_elapsed = 0
                    self.tempo_duration = seconds * 1000
                    self.tempo_running = True
                    self.tempo_paused = False

                    if not self.tempo_timer:
                        self.tempo_timer = QTimer()
                        self.tempo_timer.timeout.connect(self.update_tempo_timeline)

                    self.tempo_timer.start(100)

                    # Mettre a jour l'icone play
                    self.player_ui.update_play_icon(QMediaPlayer.PlayingState)

                    # Jouer la sequence lumiere si disponible
                    dmx_mode = self.get_dmx_mode(row)
                    if dmx_mode == "Manuel":
                        self.player_ui.dmx_blackout()
                    elif dmx_mode in ["Programme", "Play Lumiere"] and row in self.sequences:
                        self.play_sequence(row)
                    return

                # PAUSE indefinie
                if data == "PAUSE":
                    self.player_ui.player.stop()
                    self.player_ui.dmx_blackout()
                    # Cacher l'image si affichee
                    if hasattr(self.player_ui, 'hide_image'):
                        self.player_ui.hide_image()

                    self.current_row = row
                    self.table.selectRow(row)
                    self.player_ui.update_play_icon(QMediaPlayer.StoppedState)

                    # Jouer la sequence lumiere si disponible
                    dmx_mode = self.get_dmx_mode(row)
                    if dmx_mode in ["Programme", "Play Lumiere"] and row in self.sequences:
                        self.play_sequence(row)

                    next_row = row + 1
                    if next_row < self.table.rowCount():
                        next_item = self.table.item(next_row, 1)
                        next_data = next_item.data(Qt.UserRole) if next_item else None
                        if next_item and next_data != "PAUSE" and not str(next_data or "").startswith("PAUSE:"):
                            vol_item = self.table.item(next_row, 3)
                            if vol_item and vol_item.text() != "--":
                                path = next_item.data(Qt.UserRole)
                                vol = int(vol_item.text())
                                self.player_ui.audio.setVolume(vol / 100)
                                if media_icon(path) != "image":
                                    self.player_ui.player.setSource(QUrl.fromLocalFile(path))
                                self.current_row = next_row
                                self.player_ui.trigger_pause_mode()
                                # Masquer la 1re frame du media precharge — le preview doit rester noir
                                if hasattr(self.player_ui, 'show_black_preview'):
                                    self.player_ui.show_black_preview()
                    return

                # Lecture normale (media)
                self.current_row = row
                vol_item = self.table.item(row, 3)
                if item and vol_item:
                    path = item.data(Qt.UserRole)

                    # Verifier que le fichier existe
                    if path and not os.path.isfile(path):
                        msg = QMessageBox(self)
                        msg.setIcon(QMessageBox.Critical)
                        msg.setWindowTitle(tr("seq_file_not_found_title"))
                        msg.setText(tr("seq_file_not_found_msg", name=Path(path).name))
                        btn_ok = msg.addButton(QMessageBox.Ok)
                        btn_locate = msg.addButton(tr("seq_locate_file"), QMessageBox.ActionRole)
                        msg.exec()
                        if msg.clickedButton() == btn_locate:
                            start_dir = str(Path(path).parent) if Path(path).parent.exists() else str(Path.home())
                            new_path, _ = QFileDialog.getOpenFileName(self, tr("seq_locate_file"), start_dir, MEDIA_EXTENSIONS_FILTER)
                            if new_path:
                                item.setData(Qt.UserRole, new_path)
                                item.setText(Path(new_path).name)
                                icon_item = self.table.item(row, 0)
                                if icon_item:
                                    new_icon = media_icon(new_path)
                                    icon_text = {"audio": "\U0001f3b5", "video": "\U0001f3ac", "image": "\U0001f5bc"}.get(new_icon, "?")
                                    icon_item.setText(icon_text)
                                    icon_item.setData(Qt.UserRole, icon_text)
                                path = new_path
                            else:
                                return
                        else:
                            return

                    vol = int(vol_item.text()) if vol_item.text() not in ("--", "") else 100

                    dmx_mode = self.get_dmx_mode(row)
                    self.last_dmx_mode = dmx_mode

                    # IA Lumiere : utilise les donnees pre-analysees
                    if dmx_mode == "IA Lumiere":
                        self.player_ui.audio_ai.reset()
                        color = self.ia_colors.get(row)
                        if color:
                            self.player_ui.audio_ai.set_dominant_color(color)
                        if row in self.ia_analysis:
                            self.player_ui.audio_ai.load_analysis(self.ia_analysis[row])

                    # Gestion des images
                    if media_icon(path) == "image":
                        self.player_ui.player.stop()
                        self.player_ui.show_image(path)
                        # Mettre a jour la sortie video externe
                        if hasattr(self.player_ui, '_update_video_output_state'):
                            self.player_ui._update_video_output_state()

                        image_duration = self.image_durations.get(row)
                        if image_duration:
                            # Image avec duree : lancer le tempo timer
                            self.tempo_elapsed = 0
                            self.tempo_duration = image_duration * 1000
                            self.tempo_running = True
                            self.tempo_paused = False

                            if not self.tempo_timer:
                                self.tempo_timer = QTimer()
                                self.tempo_timer.timeout.connect(self.update_tempo_timeline)

                            self.tempo_timer.start(100)
                            self.player_ui.update_play_icon(QMediaPlayer.PlayingState)
                        else:
                            # Image sans duree : attendre action utilisateur
                            self.player_ui.update_play_icon(QMediaPlayer.PausedState)

                        if dmx_mode == "Manuel":
                            for p in self.player_ui.projectors:
                                p.level = 0
                                p.color = QColor("black")
                                p.base_color = QColor("black")
                        elif dmx_mode in ["Programme", "Play Lumiere"] and row in self.sequences:
                            self.play_sequence(row)
                        return

                    # Cacher l'image si affichee precedemment
                    if hasattr(self.player_ui, 'hide_image'):
                        self.player_ui.hide_image()

                    self.player_ui.audio.setVolume(vol / 100)
                    # Arreter proprement l'ancien media avant de changer de source
                    # (evite les signaux Qt parasites EndOfMedia lors du changement)
                    self.player_ui.player.stop()
                    self.player_ui._media_source_row = row
                    self.player_ui.player.setSource(QUrl.fromLocalFile(path))
                    self.player_ui.player.play()

                    # Mettre a jour la sortie video externe
                    if hasattr(self.player_ui, '_update_video_output_state'):
                        self.player_ui._update_video_output_state()

                    if dmx_mode == "Manuel":
                        # Manuel = pas de lumiere
                        for p in self.player_ui.projectors:
                            p.level = 0
                            p.color = QColor("black")
                            p.base_color = QColor("black")
                        self.player_ui.recording_waveform.hide()
                    elif dmx_mode in ["Programme", "Play Lumiere"]:
                        self.play_sequence(row)
                    else:
                        self.player_ui.recording_waveform.hide()

            except Exception as e:
                print(f"Erreur lecture: {e}")
                QMessageBox.critical(None, tr("err_save_title"), tr("seq_err_play_msg", e=e))

    def update_tempo_timeline(self):
        """Met a jour la timeline pendant une Pause minutee"""
        if not self.tempo_running:
            return

        self.tempo_elapsed += 100

        if self.tempo_elapsed >= self.tempo_duration:
            self.tempo_timer.stop()
            self.tempo_running = False
            self.tempo_paused = False
            self.continue_after_tempo_in_seq(self.current_row)
            return

        progress = (self.tempo_elapsed / self.tempo_duration) * self.player_ui.timeline.maximum() if self.tempo_duration > 0 else 0
        self.player_ui.timeline.setValue(int(progress))

        seconds = self.tempo_elapsed // 1000
        total_seconds = self.tempo_duration // 1000
        self.player_ui.time_label.setText(f"{seconds//60:02d}:{seconds%60:02d}")
        remaining_seconds = total_seconds - seconds
        self.player_ui.remaining_label.setText(f"-{remaining_seconds//60:02d}:{remaining_seconds%60:02d}")

    def continue_after_tempo_in_seq(self, tempo_row):
        """Continue la sequence apres une Pause minutee ou une image temporisee"""
        if self.tempo_timer and self.tempo_timer.isActive():
            self.tempo_timer.stop()
        self.tempo_running = False
        self.tempo_paused = False
        self.tempo_elapsed = 0

        # Cacher l'image si affichee
        if hasattr(self.player_ui, 'hide_image'):
            self.player_ui.hide_image()

        # Arreter le timer timeline si actif
        if self.timeline_playback_timer and self.timeline_playback_timer.isActive():
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
        if hasattr(self, 'timeline_playback_row'):
            del self.timeline_playback_row
        self.timeline_tracks_data = {}

        next_row = tempo_row + 1
        if next_row < self.table.rowCount():
            self.play_row(next_row)
        else:
            print("Fin de la sequence")
            self.player_ui.update_play_icon(QMediaPlayer.StoppedState)

    def get_dmx_mode(self, row):
        """Recupere le mode DMX d'une ligne"""
        combo = self._get_dmx_combo(row)
        if combo:
            return combo.currentText()
        return "Manuel"

    def toggle_recording(self, row, checked):
        """Active/desactive l'enregistrement d'une sequence"""
        if checked:
            self.recording = True
            self.recording_row = row
            self.recording_start_time = 0

            self.sequences[row] = {
                "keyframes": [],
                "duration": 0
            }

            if not self.recording_timer:
                self.recording_timer = QTimer()
                self.recording_timer.timeout.connect(self.record_keyframe)

            self.recording_timer.start(500)
            print(f"Enregistrement sequence ligne {row} demarre")
        else:
            self.recording = False
            if self.recording_timer:
                self.recording_timer.stop()

            if self.recording_row in self.sequences:
                self.sequences[self.recording_row]["duration"] = self.recording_start_time
                nb_keyframes = len(self.sequences[self.recording_row]["keyframes"])
                print(f"Enregistrement arrete - {nb_keyframes} keyframes")

            self.recording_row = -1
            self.recording_start_time = 0
            self.is_dirty = True

    def record_keyframe(self):
        """Enregistre un keyframe de l'etat actuel AKAI"""
        if not self.recording or self.recording_row < 0:
            return

        main_window = self.player_ui

        keyframe = {
            "time": self.recording_start_time,
            "faders": [],
            "active_pad": None,
            "active_effects": []
        }

        for i in range(9):
            if i in main_window.faders:
                keyframe["faders"].append(main_window.faders[i].value)
            else:
                keyframe["faders"].append(0)

        if main_window.active_pad:
            for (r, c), pad in main_window.pads.items():
                if pad == main_window.active_pad:
                    keyframe["active_pad"] = {
                        "row": r,
                        "col": c,
                        "color": pad.property("base_color").name()
                    }
                    break

        for i, btn in enumerate(main_window.effect_buttons):
            keyframe["active_effects"].append(btn.active)

        self.sequences[self.recording_row]["keyframes"].append(keyframe)

        pad_color = None
        if keyframe["active_pad"]:
            pad_color = QColor(keyframe["active_pad"]["color"])
        main_window.recording_waveform.add_keyframe(
            self.recording_start_time,
            keyframe["faders"],
            pad_color
        )

        self.recording_start_time += 500

    def play_sequence(self, row):
        """Joue une sequence"""
        if row not in self.sequences:
            return

        sequence = self.sequences[row]

        if "clips" in sequence:
            self.play_timeline_sequence(row)
        elif "keyframes" in sequence:
            self.play_keyframes_sequence(row)

    def play_timeline_sequence(self, row):
        """Joue sequence timeline avec clips"""
        sequence = self.sequences[row]
        clips_data = sequence.get("clips", [])

        if not clips_data:
            return

        print(f"Lecture timeline ligne {row} - {len(clips_data)} clips")

        tracks_clips = {}
        for clip_data in clips_data:
            track_name = clip_data.get('track', 'Face')
            tracks_clips.setdefault(track_name, []).append(clip_data)

        # Couper tout effet actif avant de démarrer la timeline (évite le strobe)
        main_win = self.player_ui
        if hasattr(main_win, 'effect_timer') and main_win.effect_timer.isActive():
            main_win.effect_timer.stop()
        if getattr(main_win, 'active_effect', None) is not None:
            main_win.active_effect = None
            main_win.active_effect_config = {}

        self.timeline_playback_row = row
        self.timeline_tracks_data = tracks_clips
        self.timeline_last_update = -100  # Garantit que le 1er tick fire immediatement
        self._timeline_tick = 0  # Repart de zero pour les effets

        if not self.timeline_playback_timer:
            self.timeline_playback_timer = QTimer()
            self.timeline_playback_timer.timeout.connect(self.update_timeline_playback)

        self.timeline_playback_timer.start(50)

    def update_timeline_playback(self):
        """Met a jour DMX selon position timeline"""
        if not hasattr(self, 'timeline_playback_row'):
            return

        # Garde supplementaire: verifier que la timeline correspond bien au media en cours
        if self.timeline_playback_row != getattr(self, 'current_row', -1):
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            del self.timeline_playback_row
            self.timeline_tracks_data = {}
            return

        # Garde supplementaire: verifier que le mode DMX courant est toujours "Play Lumiere"
        current_dmx_mode = self.get_dmx_mode(getattr(self, 'current_row', -1))
        if current_dmx_mode != "Play Lumiere":
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            if hasattr(self, 'timeline_playback_row'):
                del self.timeline_playback_row
            self.timeline_tracks_data = {}
            return

        # Source du temps: tempo_elapsed pour TEMPO, player.position pour media
        if self.tempo_running:
            current_time = self.tempo_elapsed
        else:
            current_time = self.player_ui.player.position()

        # Debounce: ignorer uniquement si la position n'a pas change du tout
        if current_time == self.timeline_last_update:
            return

        self.timeline_last_update = current_time

        # Compteur pour les effets
        if not hasattr(self, '_timeline_tick'):
            self._timeline_tick = 0
        self._timeline_tick += 1

        active_clips = {}
        last_clip_end = 0

        for track_name, clips in self.timeline_tracks_data.items():
            for clip_data in clips:
                start = clip_data['start']
                end = start + clip_data['duration']
                if end > last_clip_end:
                    last_clip_end = end

                if start <= current_time <= end:
                    intensity = self.calculate_clip_intensity(clip_data, current_time)
                    progress = (current_time - start) / max(1, clip_data['duration'])

                    entry = {
                        'color': QColor(clip_data['color']),
                        'color2': QColor(clip_data['color2']) if clip_data.get('color2') else None,
                        'intensity': intensity,
                        'effect': clip_data.get('effect', None),
                        'effect_speed':         clip_data.get('effect_speed', 50),
                        'effect_name':          clip_data.get('effect_name', ''),
                        'effect_type':          clip_data.get('effect_type', ''),
                        'effect_layers':        clip_data.get('effect_layers', []),
                        'effect_target_groups': clip_data.get('effect_target_groups', []),
                        'memory_ref':    clip_data.get('memory_ref'),
                        'seq_intensity': intensity,
                    }
                    # Mouvement Pan/Tilt
                    if clip_data.get('move_effect') or 'pan_start' in clip_data:
                        entry['move_effect']    = clip_data.get('move_effect')
                        entry['move_speed']     = clip_data.get('move_speed', 0.5)
                        entry['move_amplitude'] = clip_data.get('move_amplitude', 60)
                        entry['pan_start']      = clip_data.get('pan_start', 128)
                        entry['tilt_start']     = clip_data.get('tilt_start', 128)
                        entry['pan_end']        = clip_data.get('pan_end', 128)
                        entry['tilt_end']       = clip_data.get('tilt_end', 128)
                        entry['move_progress']  = progress
                        entry['move_elapsed']   = (current_time - start) / 1000.0

                    active_clips[track_name] = entry
                    break

        # Auto-stop: si tous les clips sont finis et qu'on depasse la fin du dernier clip
        if not active_clips and current_time > last_clip_end and last_clip_end > 0:
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
            if hasattr(self, 'timeline_playback_row'):
                del self.timeline_playback_row
            self.timeline_tracks_data = {}
            return

        # ── Gérer la piste Effet (priorité sur tout) ─────────────────────
        effet_clip = active_clips.pop("Effet", None)
        self._handle_timeline_effect(effet_clip)

        self.apply_timeline_to_dmx(active_clips)

    def _handle_timeline_effect(self, effet_clip):
        """Démarre / maintient / arrête l'effet de la piste Effet de la timeline."""
        main_win = self.player_ui
        if effet_clip is None:
            # Aucun clip actif → arrêter l'effet timeline s'il était actif
            self._stop_timeline_effect()
            return

        eff_name = effet_clip.get('effect_name', '')
        if not eff_name:
            self._stop_timeline_effect()
            return

        # Déjà le bon effet en cours avec mêmes paramètres → ne pas redémarrer
        same_group = getattr(self, '_timeline_effect_group', None) == tuple(effet_clip.get('effect_target_groups', []))
        same_speed = getattr(self, '_timeline_effect_speed', None) == effet_clip.get('effect_speed', 50)
        if getattr(self, '_timeline_effect_name', None) == eff_name and same_group and same_speed:
            return

        # Charger la config de l'effet (layers depuis BUILTIN_EFFECTS ou custom)
        eff_layers = effet_clip.get('effect_layers', [])
        eff_type   = effet_clip.get('effect_type', '')
        if not eff_layers:
            # Chercher dans BUILTIN_EFFECTS
            try:
                from effect_editor import BUILTIN_EFFECTS
                for _e in BUILTIN_EFFECTS:
                    if _e.get('name') == eff_name:
                        eff_layers = [dict(l) for l in _e.get('layers', [])]
                        eff_type   = _e.get('type', '')
                        break
            except Exception:
                pass

        target_groups  = effet_clip.get('effect_target_groups', [])
        speed_override = effet_clip.get('effect_speed', 50)
        cfg = {
            'name':            eff_name,
            'type':            eff_type,
            'layers':          eff_layers,
            'play_mode':       'loop',
            'target_groups':   target_groups,
            'speed_override':  speed_override,
        }

        # Démarrer l'effet (initialiser l'état sans démarrer le effect_timer —
        # la timeline appelle update_effect() elle-même à chaque tick)
        self._timeline_effect_name  = eff_name
        self._timeline_effect_group = tuple(effet_clip.get('effect_target_groups', []))
        self._timeline_effect_speed = effet_clip.get('effect_speed', 50)
        main_win.active_effect        = eff_name
        main_win.active_effect_config = cfg
        # Initialiser les compteurs d'état de l'effet
        main_win.effect_state      = 0
        main_win.effect_brightness = 0
        main_win.effect_direction  = 1
        main_win.effect_hue        = 0
        main_win.effect_saved_colors = {}
        for p in main_win.projectors:
            main_win.effect_saved_colors[id(p)] = (
                p.base_color, p.color, p.level,
                getattr(p, 'pan', 128), getattr(p, 'tilt', 128)
            )
        import time as _time
        main_win.effect_t0 = _time.monotonic()

    def _stop_timeline_effect(self):
        """Arrête l'effet lancé par la timeline (si c'est bien lui qui tourne)."""
        main_win = self.player_ui
        timeline_name = getattr(self, '_timeline_effect_name', None)
        if timeline_name is None:
            return
        self._timeline_effect_name  = None
        self._timeline_effect_group = None
        self._timeline_effect_speed = None
        # N'arrêter que si c'est encore l'effet de la timeline qui tourne
        if getattr(main_win, 'active_effect', None) == timeline_name:
            main_win.active_effect        = None
            main_win.active_effect_config = {}
            if hasattr(main_win, 'stop_effect'):
                main_win.stop_effect()

    def calculate_clip_intensity(self, clip_data, current_time):
        """Calcule intensite avec fades"""
        start = clip_data['start']
        duration = clip_data['duration']
        base_intensity = clip_data.get('intensity', 100)

        fade_in = clip_data.get('fade_in', 0)
        fade_out = clip_data.get('fade_out', 0)

        relative_pos = (current_time - start) / duration
        intensity = base_intensity

        if fade_in > 0:
            fade_in_ratio = fade_in / duration
            if relative_pos < fade_in_ratio:
                intensity *= (relative_pos / fade_in_ratio)

        if fade_out > 0:
            fade_out_ratio = fade_out / duration
            if relative_pos > (1 - fade_out_ratio):
                intensity *= ((1 - relative_pos) / fade_out_ratio)

        return int(intensity)

    def _apply_seq_memory(self, seq_clip_info, main_win):
        """Applique la mémoire de séquence sur les projecteurs (priorité haute)."""
        if not seq_clip_info:
            return
        mem_ref = seq_clip_info.get('memory_ref')
        if not mem_ref:
            return
        memories = getattr(main_win, 'memories', None)
        if not memories:
            return
        mem_col, row_idx = mem_ref[0], mem_ref[1]
        if mem_col < len(memories) and row_idx < len(memories[mem_col]):
            mem = memories[mem_col][row_idx]
            if mem:
                # Lire les projecteurs depuis les cues (format actuel) ou le niveau
                # supérieur (ancien format migré) pour compatibilité ascendante.
                cues = mem.get("cues", [])
                if cues:
                    cue_idx = seq_clip_info.get('cue_index', 0) or 0
                    cue = cues[min(cue_idx, len(cues) - 1)]
                    projectors_state = cue.get("projectors", [])
                else:
                    projectors_state = mem.get("projectors", [])
                brightness = seq_clip_info.get('seq_intensity', 100) / 100.0
                for i, ps in enumerate(projectors_state):
                    if i >= len(main_win.projectors):
                        continue
                    proj = main_win.projectors[i]
                    # Pan/Tilt toujours appliqués (même si level=0)
                    if "pan"  in ps: proj.pan  = ps["pan"]
                    if "tilt" in ps: proj.tilt = ps["tilt"]
                    if ps.get("level", 0) > 0:
                        lvl  = int(ps["level"] * brightness)
                        base = QColor(ps["base_color"])
                        proj.level      = lvl
                        proj.base_color = base
                        proj.color      = QColor(
                            int(base.red()   * lvl / 100.0),
                            int(base.green() * lvl / 100.0),
                            int(base.blue()  * lvl / 100.0),
                        )

    def apply_timeline_to_dmx(self, active_clips):
        """Applique les clips actifs aux projecteurs DMX avec effets"""
        import math
        import random

        main_win = self.player_ui
        if hasattr(main_win, 'get_track_to_indices'):
            track_to_indices = main_win.get_track_to_indices()
        else:
            track_to_indices = {
                'Face': list(range(0, 4)),
                'Douche 1': list(range(4, 7)),
                'Douche 2': list(range(7, 10)),
                'Douche 3': list(range(10, 13)),
                'Contres': list(range(15, 21))
            }

        tick = getattr(self, '_timeline_tick', 0)

        for proj in self.player_ui.projectors:
            proj.level = 0
            proj.base_color = QColor("black")
            proj.color = QColor("black")

        for track_name, clip_info in active_clips.items():
            indices = track_to_indices.get(track_name, [])
            effect = clip_info.get('effect')
            effect_speed = clip_info.get('effect_speed', 50)

            # Calculer le facteur de vitesse pour les effets
            speed_factor = max(1, int(10 - effect_speed / 12))

            for idx_position, idx in enumerate(indices):
                if idx >= len(self.player_ui.projectors):
                    continue

                proj = self.player_ui.projectors[idx]
                intensity = clip_info['intensity']

                if clip_info['color2']:
                    color = clip_info['color'] if idx_position % 2 == 0 else clip_info['color2']
                else:
                    color = clip_info['color']

                # Appliquer l'effet sur la couleur/intensite
                if effect == "Strobe":
                    if (tick // speed_factor) % 2 == 0:
                        color = QColor(255, 255, 255)
                    else:
                        color = QColor("black")
                        intensity = 0
                elif effect == "Flash":
                    if (tick // speed_factor) % 2 == 0:
                        pass  # couleur normale
                    else:
                        color = QColor("black")
                        intensity = 0
                elif effect == "Pulse":
                    phase = math.sin(tick * 0.15 / max(1, speed_factor / 5)) * 0.5 + 0.5
                    intensity = int(intensity * phase)
                elif effect == "Wave":
                    phase = math.sin((tick + idx_position * 3) * 0.2 / max(1, speed_factor / 5)) * 0.5 + 0.5
                    intensity = int(intensity * phase)
                elif effect == "Random":
                    if tick % speed_factor == 0:
                        if random.random() > 0.5:
                            intensity = 0
                elif effect == "Sparkle":
                    # Chaque projecteur scintille independamment et aleatoirement
                    spark_period = max(1, speed_factor)
                    spark_tick = tick // spark_period
                    rng = random.Random(spark_tick * 100 + idx_position * 37)
                    if rng.random() > 0.5:
                        intensity = 0
                elif effect == "Rainbow":
                    # Cycle chromatique continu, decale par projecteur
                    hue = (tick * 4 // max(1, speed_factor) + idx_position * 40) % 360
                    color = QColor.fromHsv(hue, 255, 255)
                elif effect == "Fire":
                    # Scintillement dans les tons chauds rouge/orange
                    rng = random.Random((tick + idx_position * 7) * 3)
                    r = min(255, 175 + int(rng.random() * 80))
                    g = int(rng.random() * 80)
                    color = QColor(r, g, 0)

                proj.level = intensity
                proj.base_color = color
                proj.color = QColor(
                    int(color.red() * intensity / 100),
                    int(color.green() * intensity / 100),
                    int(color.blue() * intensity / 100)
                )

        # --- Appliquer Pan/Tilt pour les Lyres ---
        lyres_clip = active_clips.get('Lyres')
        if lyres_clip and 'pan_start' in lyres_clip:
            # Recuperer les indices du groupe "lyres" / "Lyres"
            lyres_indices = track_to_indices.get('Lyres', [])
            if not lyres_indices and hasattr(main_win, 'projectors'):
                lyres_indices = [
                    i for i, p in enumerate(main_win.projectors)
                    if getattr(p, 'group', '').lower() == 'lyres'
                ]

            move_effect  = lyres_clip.get('move_effect')
            move_speed   = lyres_clip.get('move_speed', 0.5)
            move_amp     = lyres_clip.get('move_amplitude', 60)
            progress     = lyres_clip.get('move_progress', 0.0)
            elapsed      = lyres_clip.get('move_elapsed', 0.0)

            pan_start    = lyres_clip.get('pan_start', 128)
            tilt_start   = lyres_clip.get('tilt_start', 128)
            pan_end      = lyres_clip.get('pan_end', 128)
            tilt_end     = lyres_clip.get('tilt_end', 128)

            if move_effect:
                # Effets automatiques — math periodique
                t = elapsed * move_speed * 2 * math.pi
                amp = move_amp  # amplitude en valeur DMX (0-127)
                if move_effect == 'Cercle':
                    pan_val  = 128 + int(amp * math.cos(t))
                    tilt_val = 128 + int(amp * math.sin(t))
                elif move_effect == 'Figure 8':
                    pan_val  = 128 + int(amp * math.sin(t))
                    tilt_val = 128 + int(amp * math.sin(2 * t) / 2)
                elif move_effect == 'Balayage H':
                    pan_val  = 128 + int(amp * math.sin(t))
                    tilt_val = 128
                elif move_effect == 'Balayage V':
                    pan_val  = 128
                    tilt_val = 128 + int(amp * math.sin(t))
                elif move_effect == 'Aléatoire':
                    # Interpolation smooth via sin combines — deterministique sur elapsed
                    pan_val  = 128 + int(amp * 0.6 * math.sin(t * 1.0) +
                                         amp * 0.4 * math.sin(t * 1.7 + 1.3))
                    tilt_val = 128 + int(amp * 0.6 * math.cos(t * 0.8 + 0.7) +
                                         amp * 0.4 * math.cos(t * 2.1 + 2.5))
                else:
                    pan_val  = 128
                    tilt_val = 128
            else:
                # Trajectoire lineaire entre start et end
                p = max(0.0, min(1.0, progress))
                pan_val  = int(pan_start  + (pan_end  - pan_start)  * p)
                tilt_val = int(tilt_start + (tilt_end - tilt_start) * p)

            pan_val  = max(0, min(255, pan_val))
            tilt_val = max(0, min(255, tilt_val))

            for idx in lyres_indices:
                if idx < len(self.player_ui.projectors):
                    proj = self.player_ui.projectors[idx]
                    proj.pan  = pan_val
                    proj.tilt = tilt_val

        # ── Appliquer la séquence mémoire par-dessus les groupes ────────────
        self._apply_seq_memory(active_clips.get('Séquence'), main_win)

        # ── Appliquer l'effet de la piste Effet par-dessus tout ─────────────
        # (le effect_timer n'est pas actif en mode timeline — on gère ici)
        if getattr(main_win, 'active_effect', None) is not None:
            if hasattr(main_win, 'update_effect'):
                main_win.update_effect()

        if hasattr(self.player_ui, 'artnet') and self.player_ui.artnet:
            self.player_ui.artnet.update_from_projectors(self.player_ui.projectors)

            if hasattr(self.player_ui, 'plan') and self.player_ui.plan:
                self.player_ui.plan.refresh()

    def play_keyframes_sequence(self, row):
        """Joue sequence keyframes"""
        sequence = self.sequences[row]
        keyframes = sequence["keyframes"]

        if not keyframes:
            return

        main_window = self.player_ui
        main_window.recording_waveform.clear()

        for kf in keyframes:
            pad_color = None
            if kf.get("active_pad"):
                pad_color = QColor(kf["active_pad"]["color"])
            main_window.recording_waveform.add_keyframe(
                kf["time"],
                kf["faders"],
                pad_color
            )

        main_window.recording_waveform.duration = sequence.get("duration", 0)
        main_window.recording_waveform.show()

        self.playback_row = row
        self.playback_index = 0

        if not self.playback_timer:
            self.playback_timer = QTimer()
            self.playback_timer.timeout.connect(self.update_sequence_playback)

        self.playback_timer.start(50)

    def update_sequence_playback(self):
        """Met a jour la lecture de la sequence"""
        if self.playback_row < 0:
            return

        current_time = self.player_ui.player.position()

        sequence = self.sequences.get(self.playback_row)
        if not sequence:
            return

        keyframes = sequence["keyframes"]

        for i, kf in enumerate(keyframes):
            if kf["time"] <= current_time < (kf["time"] + 500):
                if i != self.playback_index:
                    self.apply_keyframe(kf)
                    self.playback_index = i
                break

    def apply_keyframe(self, keyframe):
        """Applique un keyframe a l'etat AKAI"""
        main_window = self.player_ui

        for i, value in enumerate(keyframe["faders"]):
            if i in main_window.faders:
                main_window.faders[i].value = value
                main_window.set_proj_level(i, value)
                main_window.faders[i].update()

                if MIDI_AVAILABLE and main_window.midi_handler and main_window.midi_handler.midi_out:
                    midi_value = int((value / 100.0) * 127)
                    main_window.midi_handler.set_fader(i, midi_value)

        if keyframe["active_pad"]:
            pad_info = keyframe["active_pad"]
            pad = main_window.pads.get((pad_info["row"], pad_info["col"]))
            if pad:
                main_window.activate_pad(pad, pad_info["col"])

                if MIDI_AVAILABLE and main_window.midi_handler and main_window.midi_handler.midi_out:
                    velocity = rgb_to_akai_velocity(pad.property("base_color"))
                    main_window.midi_handler.set_pad_led(pad_info["row"], pad_info["col"], velocity, 100)

        for i, active in enumerate(keyframe["active_effects"]):
            if i < len(main_window.effect_buttons):
                if active != main_window.effect_buttons[i].active:
                    main_window.toggle_effect(i)

    def show_media_context_menu(self, pos):
        """Menu contextuel sur media"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1a1a1a;
                color: white;
                border: 2px solid #4a4a4a;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 30px;
            }
            QMenu::item:selected {
                background: #4a8aaa;
            }
        """)

        title_item = self.table.item(row, 1)
        path = title_item.data(Qt.UserRole) if title_item else None
        media_type = media_icon(path) if path else None

        # Volume uniquement pour audio et video
        if media_type in ("audio", "video"):
            volume_action = menu.addAction(tr("seq_menu_volume"))
            volume_action.triggered.connect(lambda: self.edit_media_volume(row))

        # Definir la duree uniquement pour les images
        if media_type == "image":
            duration_action = menu.addAction(tr("seq_menu_set_duration"))
            duration_action.triggered.connect(lambda: self.edit_image_duration(row))

        menu.addSeparator()

        rec_action = menu.addAction(tr("seq_menu_rec_light"))
        rec_action.triggered.connect(lambda: self.open_light_editor_for_row(row))

        menu.addSeparator()
        delete_action = menu.addAction(tr("seq_menu_delete"))
        delete_action.triggered.connect(lambda: self.delete_media_row(row))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def edit_media_volume(self, row):
        """Edite le volume d'un media (audio/video uniquement)"""
        vol_item = self.table.item(row, 3)
        if not vol_item or vol_item.text() == "--":
            return

        current_vol = int(vol_item.text())

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("seq_menu_volume"))
        dialog.setFixedSize(350, 200)
        dialog.setStyleSheet("background: #1a1a1a;")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        value_label = QLabel(f"{current_vol}%")
        value_label.setStyleSheet("color: white; font-size: 32px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(current_vol)
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2a2a2a;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00d4ff;
                width: 20px;
                height: 20px;
                border-radius: 10px;
                margin: -6px 0;
            }
        """)
        slider.valueChanged.connect(lambda v: value_label.setText(f"{v}%"))
        layout.addWidget(slider)

        btn_layout = QHBoxLayout()

        cancel = QPushButton(tr("btn_cancel_x"))
        cancel.clicked.connect(dialog.reject)
        cancel.setStyleSheet("background: #3a3a3a; color: white; border: none; border-radius: 6px; padding: 10px 20px;")
        btn_layout.addWidget(cancel)

        ok = QPushButton("✅ OK")
        ok.setDefault(True)
        ok.clicked.connect(dialog.accept)
        ok.setStyleSheet("background: #00d4ff; color: black; border: none; border-radius: 6px; padding: 10px 30px; font-weight: bold;")
        btn_layout.addWidget(ok)

        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            vol_item.setText(str(slider.value()))
            self.is_dirty = True

        if hasattr(self.player_ui, 'recording_waveform'):
            self.player_ui.recording_waveform.hide()

    def open_light_editor_for_row(self, row):
        """Ouvre l'editeur de timeline pour ce media"""
        if hasattr(self.player_ui, 'recording_waveform'):
            self.player_ui.recording_waveform.hide()

        self.player_ui.open_light_editor(row)

    def delete_media_row(self, row):
        """Supprime une ligne du sequenceur"""
        if row == self.current_row:
            QMessageBox.warning(self, tr("seq_delete_impossible_title"),
                tr("seq_delete_impossible_msg"))
            return

        item = self.table.item(row, 1)
        media_name = item.text() if item else f"Ligne {row + 1}"

        reply = QMessageBox.question(
            self,
            tr("seq_delete_media_title"),
            tr("seq_delete_media_msg", name=media_name),
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.table.removeRow(row)

            if row in self.sequences:
                del self.sequences[row]

            new_sequences = {}
            for old_row, seq in self.sequences.items():
                if old_row < row:
                    new_sequences[old_row] = seq
                elif old_row > row:
                    new_sequences[old_row - 1] = seq
            self.sequences = new_sequences

            self._reindex_ia_colors(row)  # Also reindexes ia_analysis
            self.is_dirty = True

    def stop_sequence_playback(self):
        """Arrete la lecture de la sequence"""
        if self.playback_timer:
            self.playback_timer.stop()
        self.playback_row = -1
        self.playback_index = 0

        if self.timeline_playback_timer:
            self._stop_timeline_effect()
            self.timeline_playback_timer.stop()
        if hasattr(self, 'timeline_playback_row'):
            del self.timeline_playback_row
        self.timeline_tracks_data = {}
