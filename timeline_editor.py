"""
Editeur de timeline lumiere - LightTimelineEditor
"""
import os
import json
import hashlib
import random
from i18n import tr
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton,
    QScrollArea, QWidget, QComboBox, QProgressBar, QCheckBox,
    QMessageBox, QApplication, QMenuBar, QMenu, QSizePolicy, QFrame,
    QFileDialog, QSplitter
)
from PySide6.QtCore import Qt, QSize, QTimer, QUrl, QPoint, QRect, QMimeData
from PySide6.QtGui import QColor, QPainter, QPen, QPolygon, QPalette, QBrush, QCursor, QKeySequence, QShortcut, QDrag, QPixmap
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
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
    class QAudioOutput:  # type: ignore
        def __init__(self): pass
        def setVolume(self, *a): pass
try:
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    QVideoWidget = None

from light_timeline import LightTrack, LightClip, PalettePanel, LibraryPanel
from core import media_icon, create_icon
from effect_editor import EffectEditorDialog
from plan_de_feu import PlanDeFeu


class _AnalysisCancelled(Exception):
    """Exception interne pour interrompre l'analyse audio"""
    pass


class RubberBandOverlay(QWidget):
    """Overlay transparent pour dessiner le rectangle de selection"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.rect = None

    def set_rect(self, rect):
        self.rect = rect
        self.update()

    def clear(self):
        self.rect = None
        self.update()

    def paintEvent(self, event):
        if self.rect:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            # Fond semi-transparent cyan
            painter.setBrush(QBrush(QColor(0, 212, 255, 50)))
            painter.setPen(QPen(QColor("#00d4ff"), 2, Qt.DashLine))
            painter.drawRect(self.rect)

            painter.end()


class LightTimelineEditor(QDialog):
    """Editeur de sequence lumiere - Theme coherent"""

    def __init__(self, main_window, media_row):
        super().__init__(main_window)
        self.main_window = main_window
        self.media_row = media_row

        # Recuperer infos du media
        item = main_window.seq.table.item(media_row, 1)
        self.media_path = item.data(Qt.UserRole) if item else ""
        self._original_media_path = self.media_path  # conservé même si media_path est vidé (PAUSE)
        self.media_name = item.text() if item else f"Media {media_row + 1}"

        # Detecter les PAUSE (indefinies et temporisees) et ancien format TEMPO
        self.is_tempo = False
        self.media_duration_override = 0
        if self.media_path == "PAUSE":
            self.is_tempo = True
            self.media_duration_override = 60000  # 60s par defaut pour editeur
            self.media_path = ""
            self.media_name = "Pause"
        elif self.media_path and (str(self.media_path).startswith("PAUSE:") or str(self.media_path).startswith("TEMPO:")):
            self.is_tempo = True
            pause_seconds = int(str(self.media_path).split(":")[1])
            self.media_duration_override = pause_seconds * 1000
            self.media_path = ""
            self.media_name = f"Pause ({pause_seconds}s)"

        self.setWindowTitle(tr("te_title", name=self.media_name))

        # Configuration palette tooltips
        palette = self.palette()
        palette.setColor(QPalette.ToolTipBase, QColor("white"))
        palette.setColor(QPalette.ToolTipText, QColor("black"))
        self.setPalette(palette)

        app_palette = QApplication.instance().palette()
        app_palette.setColor(QPalette.ToolTipBase, QColor("white"))
        app_palette.setColor(QPalette.ToolTipText, QColor("black"))
        QApplication.instance().setPalette(app_palette)

        # Theme global avec TOOLTIPS CORRIGES
        self.setStyleSheet("""
            QDialog {
                background: #0a0a0a;
            }
            * {
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QToolTip {
                background-color: #2a2a2a;
                color: #00d4ff;
                border: 2px solid #00d4ff;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                font-weight: bold;
            }
            QMessageBox {
                background: #1a1a1a;
            }
            QMessageBox QLabel {
                color: white;
            }
            QMessageBox QPushButton {
                color: black;
                background: #cccccc;
                border: 1px solid #999999;
                border-radius: 4px;
                padding: 6px 20px;
                font-weight: bold;
            }
            QMessageBox QPushButton:hover {
                background: #00d4ff;
            }
        """)

        # Plein ecran avec boutons maximiser/minimiser
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)

        # Curseur de lecture
        if main_window.player.playbackState() == QMediaPlayer.PlayingState:
            self.playback_position = main_window.player.position()
        else:
            self.playback_position = 0
        self._prev_playback_position = self.playback_position

        self._seq_clip_active = None   # clip de séquence actuellement actif (pour effets)
        self._eff_clip_active = None   # clip d'effet (piste Effet) actuellement actif

        self.playback_timer = QTimer()
        self.playback_timer.timeout.connect(self.update_playhead)

        # Demarrer le timer si le player principal joue deja
        if main_window.player.playbackState() == QMediaPlayer.PlayingState:
            self.playback_timer.start(40)

        # Démarrer/arrêter le timer quand le player principal change d'état
        main_window.player.playbackStateChanged.connect(self._on_main_player_state_changed)

        # Recuperer duree du media
        self.media_duration = self.get_media_duration()

        # Historique undo
        self.history = []
        self.history_index = -1
        self._saved_history_index = -1  # index au moment du dernier save_sequence

        # Mode cut
        self.cut_mode = False

        # Selection multi-pistes (rubber band)
        self.rubber_band_active = False
        self.rubber_band_start = None
        self.rubber_band_rect = None
        self.rubber_band_origin_track = None

        # Clipboard pour copier/coller
        self.clipboard = []

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Menu bar
        menubar = self._create_menu_bar()
        layout.addWidget(menubar)

        # Header
        header = self._create_header()
        layout.addWidget(header)

        # ── Layout principal : [Gauche: bibliothèque] | [Droite: plan de feu / timeline] ──
        self._pdf_window = None
        self._live_pdf = None
        self._pdf_show_action = None

        _splitter_ss = "QSplitter::handle { background: #1e1e1e; }"

        # Splitter horizontal externe : gauche (biblio) / droite (plan de feu + timeline)
        outer_splitter = QSplitter(Qt.Horizontal)
        outer_splitter.setHandleWidth(4)
        outer_splitter.setStyleSheet(_splitter_ss)

        # ── Droite : Plan de Feu (haut) + Timeline (bas) ─────────────────
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setHandleWidth(4)
        left_splitter.setStyleSheet(_splitter_ss)

        try:
            pdf = PlanDeFeu(self.main_window.projectors, main_window=self.main_window, show_toolbar=False)
            pdf.setStyleSheet("border: none; background: #0d0d0d;")
            left_splitter.addWidget(pdf)
            self._live_pdf = pdf
            self._pdf_window = pdf
        except Exception:
            _ph = QWidget(); _ph.setStyleSheet("background: #0d0d0d;")
            left_splitter.addWidget(_ph)

        # ── Timeline complète ─────────────────────────────────────────────
        timeline_widget = QWidget()
        timeline_widget.setStyleSheet("background: #0a0a0a;")
        tl = QVBoxLayout(timeline_widget)
        tl.setSpacing(0)
        tl.setContentsMargins(0, 0, 0, 0)

        # Ruler
        self.ruler = QWidget()
        self.ruler.setFixedHeight(35)
        self.ruler.setStyleSheet("background: #1a1a1a; border-bottom: 1px solid #2a2a2a;")
        self.ruler.paintEvent = self.paint_ruler
        self.ruler.mousePressEvent = self.ruler_mouse_press
        self.ruler.mouseMoveEvent = self.ruler_mouse_move
        self.ruler.mouseReleaseEvent = self.ruler_mouse_release
        tl.addWidget(self.ruler)

        # Scroll area pour les pistes
        self.tracks_scroll = QScrollArea()
        self.tracks_scroll.setWidgetResizable(True)
        self.tracks_scroll.setStyleSheet("""
            QScrollArea { background: #0a0a0a; border: none; }
            QScrollBar:vertical { background: #1a1a1a; width: 12px; }
            QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 6px; }
            QScrollBar:horizontal { background: #1a1a1a; height: 12px; }
            QScrollBar::handle:horizontal { background: #3a3a3a; border-radius: 6px; }
        """)

        tracks_container = QWidget()
        tracks_container.setStyleSheet("background: #0a0a0a;")
        tracks_layout = QVBoxLayout(tracks_container)
        tracks_layout.setSpacing(0)
        tracks_layout.setContentsMargins(0, 0, 0, 0)

        # Piste waveform en haut (masquee pour images et pauses)
        self.track_waveform = LightTrack("Audio", self.media_duration, self, "#00d4ff")
        self.track_waveform.setAcceptDrops(False)
        self.track_waveform.setMinimumHeight(80)

        is_image = self.media_path and media_icon(self.media_path) == "image"
        show_audio = not is_image and not self.is_tempo

        if show_audio:
            tracks_layout.addWidget(self.track_waveform)
        else:
            self.track_waveform.hide()

        # Creer les pistes dynamiquement depuis les fixtures (sous la waveform)
        self._create_tracks_from_fixtures(main_window.projectors, tracks_layout)

        tracks_layout.addStretch()

        # Stocker le container pour l'overlay
        self.tracks_container = tracks_container
        self.tracks_scroll.setWidget(tracks_container)
        tl.addWidget(self.tracks_scroll, 1)

        # Footer (transport + save/close) dans la zone timeline
        footer = self._create_footer()
        tl.addWidget(footer)

        left_splitter.addWidget(timeline_widget)
        left_splitter.setSizes([280, 520])
        left_splitter.setStretchFactor(0, 0)
        left_splitter.setStretchFactor(1, 1)

        # ── Gauche : Bibliothèque pleine hauteur ─────────────────────────
        self._library = LibraryPanel(self)
        outer_splitter.addWidget(self._library)
        outer_splitter.addWidget(left_splitter)
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)

        layout.addWidget(outer_splitter, 1)

        # Creer l'overlay pour le rubber band (rectangle de selection visible)
        self.rubber_band_overlay = RubberBandOverlay(self.tracks_scroll.viewport())
        self.rubber_band_overlay.setGeometry(self.tracks_scroll.viewport().rect())
        self.rubber_band_overlay.hide()

        # Synchroniser ruler avec scroll horizontal
        self.tracks_scroll.horizontalScrollBar().valueChanged.connect(self.on_scroll_changed)

        # Zoom par defaut
        self.current_zoom = 1.0

        # Player audio pour preview
        self.setup_audio_player()

        # Raccourci Espace global (capturé au niveau fenetre, independant du focus)
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play_pause)

        # Charger sequence existante
        self.load_existing_sequence()

        # Forcer affichage du curseur
        QTimer.singleShot(100, lambda: self.ruler.update())

        # Generer la forme d'onde (sauf pour les images et les pauses)
        is_image = self.media_path and media_icon(self.media_path) == "image"
        if self.media_path and os.path.exists(self.media_path) and not is_image and not self.is_tempo:
            QTimer.singleShot(50, self._load_waveform_async)

        # Maximiser la fenetre apres construction complete
        self.showMaximized()

    def _create_tracks_from_fixtures(self, projectors, tracks_layout):
        """Genere les pistes de la timeline depuis la liste de fixtures"""
        GROUP_DISPLAY = getattr(self.main_window, 'GROUP_DISPLAY', {
            "face":    "A", "lat":     "B", "contre":  "C",
            "douche1": "D", "douche2": "E", "douche3": "F",
            "public": "Public", "fumee": "Fumee", "lyre": "Lyres",
            "barre": "Barres", "strobe": "Strobos",
        })
        # Groupes sans piste lumiere
        SKIP_GROUPS = {"fumee"}

        # Couleurs associees a chaque groupe (identiques au patch DMX)
        TRACK_COLORS = {
            "A":      "#ff8844",
            "B":      "#4488ff",
            "C":      "#44cc88",
            "D":      "#ff6655",
            "E":      "#cc44ff",
            "F":      "#ffcc22",
            "Fumee":  "#88aaaa",
            "Lyres":  "#ff44cc",
            "Barres": "#44aaff",
            "Strobos":"#ffee44",
        }
        # Ordre canonique des pistes dans la timeline (A→F alphabetique, puis specials)
        TRACK_ORDER = ["A", "B", "C", "D", "E", "F",
                       "Lyres", "Barres", "Strobos", "Fumee"]

        seen_groups = []
        for proj in projectors:
            gname = GROUP_DISPLAY.get(proj.group, proj.group.capitalize())
            if gname not in seen_groups and proj.group not in SKIP_GROUPS:
                seen_groups.append(gname)

        # Trier selon l'ordre canonique (groupes inconnus a la fin)
        seen_groups.sort(key=lambda g: TRACK_ORDER.index(g) if g in TRACK_ORDER else len(TRACK_ORDER))

        self.tracks = []
        self.track_map = {}

        # ── Piste Effet (tout en haut — priorité absolue sur les groupes) ─
        eff_track = LightTrack("Effet", self.media_duration, self, "#cc44ff")
        eff_track.is_effect_track = True
        eff_track.setMinimumHeight(50)
        self.tracks.append(eff_track)
        self.track_map["Effet"] = eff_track
        tracks_layout.addWidget(eff_track)

        # ── Piste Séquence (avant les groupes) ────────────────────────────
        seq_track = LightTrack("Séquence", self.media_duration, self, "#aa77ff")
        seq_track.is_sequence_track = True
        seq_track.setMinimumHeight(50)
        self.tracks.append(seq_track)
        self.track_map["Séquence"] = seq_track
        tracks_layout.addWidget(seq_track)

        for gname in seen_groups:
            color = TRACK_COLORS.get(gname, "#4488ff")
            track = LightTrack(gname, self.media_duration, self, color)
            self.tracks.append(track)
            self.track_map[gname] = track
            tracks_layout.addWidget(track)

        # Alias de compatibilite pour le code existant
        self.track_face = self.track_map.get("A")
        self.track_douche1 = self.track_map.get("D")
        self.track_douche2 = self.track_map.get("E")
        self.track_douche3 = self.track_map.get("F")
        self.track_contre = self.track_map.get("C")

    def _get_waveform_cache_path(self):
        """Retourne le chemin du fichier cache pour la forme d'onde"""
        if not self.media_path:
            return None
        abs_path = os.path.abspath(self.media_path)
        try:
            stat = os.stat(abs_path)
            key = f"{abs_path}:{stat.st_size}:{int(stat.st_mtime)}"
        except OSError:
            key = abs_path
        hash_key = hashlib.md5(key.encode()).hexdigest()
        cache_dir = os.path.join(os.path.expanduser("~"), '.maestro_cache')
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"{hash_key}.json")

    def _save_waveform_cache(self, waveform):
        """Sauvegarde la forme d'onde dans le cache fichier"""
        cache_path = self._get_waveform_cache_path()
        if cache_path and waveform:
            try:
                compact = [round(x, 3) for x in waveform]
                with open(cache_path, 'w') as f:
                    json.dump(compact, f)
                print(f"   Cache waveform sauvegarde: {cache_path}")
            except Exception as e:
                print(f"   Warning: impossible de sauvegarder le cache: {e}")

    def _load_waveform_from_cache(self):
        """Charge la forme d'onde depuis le cache fichier"""
        cache_path = self._get_waveform_cache_path()
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
            except Exception:
                pass
        return None

    def _apply_waveform(self, waveform):
        """Applique les donnees de forme d'onde a toutes les pistes et force le rafraichissement"""
        self.track_waveform.waveform_data = waveform
        for track in self.tracks:
            track.waveform_data = waveform
        self.track_waveform.update()
        for track in self.tracks:
            track.update()

    def _load_waveform_async(self):
        """Charge la waveform avec cache et dialog de progression"""
        # 1. Deja chargee depuis les donnees de sequence ?
        if self.track_waveform.waveform_data:
            print(f"   Waveform deja chargee depuis sequence ({len(self.track_waveform.waveform_data)} points)")
            self._apply_waveform(self.track_waveform.waveform_data)
            return

        # 2. Cache fichier ?
        cached = self._load_waveform_from_cache()
        if cached:
            self._apply_waveform(cached)
            print(f"   Waveform chargee depuis cache ({len(cached)} points)")
            return

        # 3. Generation avec barre de progression
        self._analysis_cancelled = False

        loading = QDialog(self)
        loading.setWindowTitle(tr("te_loading_title"))
        loading.setFixedSize(380, 170)
        loading.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        loading.setStyleSheet("""
            QDialog { background: #1a1a1a; border: 2px solid #00d4ff; border-radius: 10px; }
            QLabel { color: white; border: none; }
            QProgressBar { background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 5px; text-align: center; color: white; }
            QProgressBar::chunk { background: #00d4ff; border-radius: 4px; }
        """)
        lay = QVBoxLayout(loading)
        lay.setContentsMargins(20, 15, 20, 15)
        is_vid = hasattr(self, 'is_video_file') and self.is_video_file
        status = QLabel(tr("te_extract_pct", pct=0) if is_vid else tr("te_analyse_pct", pct=0))
        status.setAlignment(Qt.AlignCenter)
        status.setStyleSheet("font-size: 14px; font-weight: bold;")
        lay.addWidget(status)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        lay.addWidget(bar)

        cancel_btn = QPushButton(tr("te_cancel_analysis"))
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #5a2a2a; color: white; border: none;
                border-radius: 6px; padding: 8px 20px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #8b3a3a; }
        """)
        cancel_btn.clicked.connect(lambda: setattr(self, '_analysis_cancelled', True))
        lay.addWidget(cancel_btn, alignment=Qt.AlignCenter)

        loading.show()
        QApplication.processEvents()

        def on_progress(pct):
            if self._analysis_cancelled:
                raise _AnalysisCancelled()
            bar.setValue(pct)
            prefix = tr("te_extract_prefix") if is_vid else tr("te_analyse_prefix")
            status.setText(f"{prefix}... {pct}%")
            QApplication.processEvents()
            if self._analysis_cancelled:
                raise _AnalysisCancelled()

        try:
            waveform = self.track_waveform.generate_waveform(
                self.media_path, max_samples=5000, progress_callback=on_progress,
                cancel_check=lambda: self._analysis_cancelled
            )
            if self._analysis_cancelled:
                # Annule: fermer dialog sans fermer l'editeur
                loading.close()
                print("Analyse annulee - editeur reste ouvert sans forme d'onde")
                return
            if waveform:
                self._apply_waveform(waveform)
                # Sauvegarder dans le cache fichier
                self._save_waveform_cache(waveform)
                # Stocker dans les donnees de sequence (en memoire)
                if self.media_row in self.main_window.seq.sequences:
                    self.main_window.seq.sequences[self.media_row]['waveform'] = [round(x, 3) for x in waveform]
                bar.setValue(100)
                status.setText(tr("te_points_analysed", n=len(waveform)))
                QApplication.processEvents()
                loading.close()
            else:
                # Aucune methode n'a reussi — editeur reste ouvert et utilisable sans forme d'onde
                status.setText(tr("te_audio_failed"))
                status.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff8800;")
                bar.setVisible(False)
                cancel_btn.setVisible(False)
                QApplication.processEvents()
                QTimer.singleShot(1800, loading.close)
        except _AnalysisCancelled:
            print("Analyse annulee par l'utilisateur")
            loading.close()
        except Exception as e:
            status.setText("⚠  Analyse Audio Impossible")
            status.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff8800;")
            bar.setVisible(False)
            cancel_btn.setVisible(False)
            print(f"Erreur forme d'onde: {e}")
            QApplication.processEvents()
            QTimer.singleShot(1800, loading.close)

        # Forcer le rafraichissement
        self.track_waveform.update()
        for track in self.tracks:
            track.update()

    def _create_menu_bar(self):
        """Cree la barre de menus Edition / Outils / Effet"""
        menubar = QMenuBar()
        menu_style = """
            QMenuBar {
                background: #1a1a1a;
                color: white;
                border-bottom: 1px solid #3a3a3a;
                padding: 2px;
                font-size: 13px;
            }
            QMenuBar::item {
                padding: 6px 14px;
                background: transparent;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background: #3a3a3a;
            }
            QMenu {
                background: #2a2a2a;
                color: white;
                border: 2px solid #00d4ff;
                padding: 5px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 30px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #00d4ff;
                color: black;
            }
            QMenu::separator {
                background: #4a4a4a;
                height: 1px;
                margin: 5px 10px;
            }
        """
        menubar.setStyleSheet(menu_style)

        # === FICHIER ===
        file_menu = menubar.addMenu(tr("te_menu_file"))

        export_action = file_menu.addAction(tr("te_menu_export_rec"))
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_sequence)

        import_action = file_menu.addAction(tr("te_menu_import_rec"))
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self.import_sequence)

        file_menu.addSeparator()

        save_action = file_menu.addAction(tr("te_menu_save"))
        save_action.triggered.connect(self.save_sequence)

        # === EDITION ===
        edit_menu = menubar.addMenu(tr("te_menu_edit"))

        undo_action = edit_menu.addAction(tr("te_menu_undo"))
        undo_action.triggered.connect(self.undo)

        redo_action = edit_menu.addAction(tr("te_menu_redo"))
        redo_action.triggered.connect(self.redo)

        edit_menu.addSeparator()

        cut_action = edit_menu.addAction(tr("te_menu_cut"))
        cut_action.triggered.connect(self.cut_selected_clips)

        copy_action = edit_menu.addAction(tr("te_menu_copy"))
        copy_action.triggered.connect(self.copy_selected_clips)

        paste_action = edit_menu.addAction(tr("te_menu_paste"))
        paste_action.triggered.connect(self.paste_clips)

        edit_menu.addSeparator()

        select_all_action = edit_menu.addAction(tr("te_menu_select_all"))
        select_all_action.triggered.connect(self.select_all_clips)

        delete_action = edit_menu.addAction(tr("te_menu_delete"))
        delete_action.triggered.connect(self.delete_selected_clips)

        delete_all_action = edit_menu.addAction(tr("te_menu_delete_all"))
        delete_all_action.triggered.connect(self.clear_all_clips)

        # === TOOLS ===
        effect_menu = menubar.addMenu(tr("te_menu_effect"))
        fade_in_action = effect_menu.addAction("🎬 Fade In")
        fade_in_action.triggered.connect(self.apply_fade_in_to_selection)
        fade_out_action = effect_menu.addAction("🎬 Fade Out")
        fade_out_action.triggered.connect(self.apply_fade_out_to_selection)
        remove_fades_action = effect_menu.addAction(tr("te_menu_remove_fades"))
        remove_fades_action.triggered.connect(self.remove_fades_from_selection)
        effect_menu.addSeparator()
        speed_action = effect_menu.addAction(tr("te_menu_effect_speed"))
        speed_action.triggered.connect(self.edit_effect_speed_selection)
        fx_editor_action = effect_menu.addAction(tr("te_menu_fx_editor"))
        fx_editor_action.triggered.connect(self.open_effect_editor)

        tools_menu = menubar.addMenu(tr("te_menu_tools"))

        cut_tool_action = tools_menu.addAction(tr("te_menu_cut_tool"))
        cut_tool_action.triggered.connect(self.toggle_cut_mode_from_menu)

        ai_action = tools_menu.addAction(tr("te_menu_ai_gen"))
        ai_action.triggered.connect(self.generate_ai_sequence)

        return menubar

    def _create_header(self):
        """Cree le header avec titre et boutons"""
        header = QWidget()
        header.setStyleSheet("background: #1a1a1a; border-bottom: 2px solid #3a3a3a;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)

        title = QLabel(f"🎬 {self.media_name}")
        title.setStyleSheet("color: white; font-size: 16px; font-weight: bold; border: none; text-decoration: none;")
        header_layout.addWidget(title)

        duration_seconds = int(self.media_duration / 1000)
        dur_min = duration_seconds // 60
        dur_sec = duration_seconds % 60
        self.total_time_str = f"{dur_min}:{dur_sec:02d}"
        self.position_label = QLabel(f"⏱ 0:00 / {self.total_time_str}")
        self.position_label.setStyleSheet("color: #00d4ff; font-size: 13px; border: none; text-decoration: none;")
        header_layout.addWidget(self.position_label)

        header_layout.addStretch()

        btn_style = """
            QPushButton {
                background: #3a3a3a;
                color: white;
                border: none;
                border-radius: 22px;
                font-size: 22px;
            }
            QPushButton:hover { background: #4a4a4a; }
        """

        # Undo
        undo_btn = QPushButton("↶")
        undo_btn.setToolTip(tr("te_tooltip_undo"))
        undo_btn.clicked.connect(self.undo)
        undo_btn.setFixedSize(45, 45)
        undo_btn.setStyleSheet(btn_style)
        header_layout.addWidget(undo_btn)

        # Cut
        self.cut_btn = QPushButton("✂")
        self.cut_btn.setToolTip(tr("te_tooltip_cut_tool"))
        self.cut_btn.clicked.connect(self.toggle_cut_mode)
        self.cut_btn.setFixedSize(45, 45)
        self.cut_btn.setCheckable(True)
        self.cut_btn.setStyleSheet(btn_style + """
            QPushButton:checked { background: #00d4ff; color: black; }
        """)
        header_layout.addWidget(self.cut_btn)

        header_layout.addSpacing(20)

        # Zoom
        zoom_btn_style = """
            QPushButton {
                background: #2a2a2a;
                color: white;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                font-size: 18px;
            }
            QPushButton:hover { background: #3a3a3a; }
        """

        zoom_out_btn = QPushButton("➖")
        zoom_out_btn.clicked.connect(self.zoom_out)
        zoom_out_btn.setFixedSize(40, 40)
        zoom_out_btn.setFocusPolicy(Qt.NoFocus)
        zoom_out_btn.setStyleSheet(zoom_btn_style)
        zoom_out_btn.setToolTip("Zoom arrière  (ou  Shift + Molette ↓)")
        header_layout.addWidget(zoom_out_btn)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setStyleSheet("color: white; padding: 0 15px; font-size: 13px;")
        self.zoom_label.setToolTip("Niveau de zoom  —  Shift + Molette pour zoomer")
        header_layout.addWidget(self.zoom_label)

        zoom_in_btn = QPushButton("➕")
        zoom_in_btn.clicked.connect(self.zoom_in)
        zoom_in_btn.setFixedSize(40, 40)
        zoom_in_btn.setFocusPolicy(Qt.NoFocus)
        zoom_in_btn.setStyleSheet(zoom_btn_style)
        zoom_in_btn.setToolTip("Zoom avant  (ou  Shift + Molette ↑)")
        header_layout.addWidget(zoom_in_btn)

        return header

    def _create_footer(self):
        """Cree le footer avec controles audio et boutons"""
        footer = QWidget()
        footer.setStyleSheet("background: #1a1a1a; border-top: 2px solid #2a2a2a;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(15, 10, 15, 10)
        footer_layout.setSpacing(10)

        side_style = """
            QToolButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3a3a3a, stop:1 #222222);
                border: 1px solid #555555;
                border-radius: 22px;
                padding: 10px;
            }
            QToolButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #444444, stop:1 #2a2a2a);
                border: 1px solid #00d4ff;
            }
            QToolButton:pressed { background: #1a1a1a; border: 1px solid #00aacc; }
        """

        play_style = """
            QToolButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #006680, stop:1 #003344);
                border: 2px solid #00d4ff;
                border-radius: 32px;
                padding: 14px;
            }
            QToolButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #008aaa, stop:1 #004455);
                border: 2px solid #33eeff;
            }
            QToolButton:pressed { background: #002233; border: 2px solid #0099bb; }
        """

        # Aller au début
        start_btn = QToolButton()
        start_btn.setIcon(create_icon("to_start", "#cccccc"))
        start_btn.setIconSize(QSize(28, 28))
        start_btn.setFixedSize(52, 52)
        start_btn.setStyleSheet(side_style)
        start_btn.setToolTip("Aller au début")
        start_btn.clicked.connect(self._go_to_start)

        # Play / Pause
        self.play_pause_btn = QToolButton()
        self.play_pause_btn.setIcon(create_icon("play", "#ffffff"))
        self.play_pause_btn.setIconSize(QSize(36, 36))
        self.play_pause_btn.setFixedSize(72, 72)
        self.play_pause_btn.setStyleSheet(play_style)
        self.play_pause_btn.setToolTip("Play / Pause  (Espace)")
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)

        # Aller à la fin
        end_btn = QToolButton()
        end_btn.setIcon(create_icon("to_end", "#cccccc"))
        end_btn.setIconSize(QSize(28, 28))
        end_btn.setFixedSize(52, 52)
        end_btn.setStyleSheet(side_style)
        end_btn.setToolTip("Aller à la fin")
        end_btn.clicked.connect(self._go_to_end)

        # Transport centré
        transport_layout = QHBoxLayout()
        transport_layout.setSpacing(8)
        transport_layout.addStretch()
        transport_layout.addWidget(start_btn)
        transport_layout.addSpacing(4)
        transport_layout.addWidget(self.play_pause_btn)
        transport_layout.addSpacing(4)
        transport_layout.addWidget(end_btn)
        transport_layout.addStretch()
        footer_layout.addLayout(transport_layout, 1)

        # Sauvegarder
        save_btn = QPushButton(tr("te_btn_save"))
        save_btn.setStyleSheet("""
            QPushButton {
                background: #2a5a2a;
                color: white;
                padding: 10px 30px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background: #3a6a3a; }
        """)
        save_btn.clicked.connect(self.save_sequence)
        footer_layout.addWidget(save_btn)

        # Fermer
        close_btn = QPushButton(tr("te_btn_close"))
        close_btn.setStyleSheet("""
            QPushButton {
                background: #4a2a2a;
                color: white;
                padding: 10px 30px;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover { background: #5a3a3a; }
        """)
        close_btn.clicked.connect(self.close_editor)
        footer_layout.addWidget(close_btn)

        return footer

    def get_media_duration(self):
        """Recupere la duree reelle du media (audio et video)"""
        # TEMPO/PAUSE: utiliser la duree definie
        if hasattr(self, 'media_duration_override') and self.media_duration_override > 0:
            return self.media_duration_override

        # Image: utiliser la duree definie dans image_durations
        if self.media_path and media_icon(self.media_path) == "image":
            image_dur = self.main_window.seq.image_durations.get(self.media_row)
            if image_dur:
                return image_dur * 1000
            return 30000  # 30s par defaut

        is_video = self.media_path and media_icon(self.media_path) == "video"

        # QMediaPlayer avec outputs audio/video pour charger correctement le media
        try:
            import time

            temp_player = QMediaPlayer()
            temp_audio = QAudioOutput()
            temp_player.setAudioOutput(temp_audio)

            # Pour les fichiers video, ajouter un output video
            # Sans ca, Qt ne parse pas correctement le conteneur video
            if is_video and QVideoWidget is not None:
                temp_video = QVideoWidget()
                temp_video.setFixedSize(1, 1)
                temp_video.hide()
                temp_player.setVideoOutput(temp_video)

            duration_ms = [0]

            def on_duration_changed(dur):
                if dur > 0:
                    duration_ms[0] = dur

            temp_player.durationChanged.connect(on_duration_changed)
            temp_player.setSource(QUrl.fromLocalFile(self.media_path))

            timeout = 10 if is_video else 5
            start = time.time()
            while duration_ms[0] == 0 and (time.time() - start) < timeout:
                QApplication.processEvents()
                time.sleep(0.05)

            if duration_ms[0] > 0:
                return duration_ms[0]
        except Exception as e:
            print(f"Erreur duree : {e}")

        return 180000  # 3 minutes par defaut

    def setup_audio_player(self):
        """Configure le player audio/video pour preview (pas pour images/pauses)"""
        self.preview_player = QMediaPlayer()
        self.preview_audio = QAudioOutput()
        self.preview_player.setAudioOutput(self.preview_audio)

        is_image = self.media_path and media_icon(self.media_path) == "image"

        # Pour les fichiers video, ajouter un output video pour que QMediaPlayer
        # puisse traiter correctement le fichier (lecture audio + tracking position)
        self.is_video_file = self.media_path and media_icon(self.media_path) == "video"
        if self.is_video_file and QVideoWidget is not None:
            self.preview_video_widget = QVideoWidget(self)
            self.preview_video_widget.setFixedSize(1, 1)
            self.preview_video_widget.hide()
            self.preview_player.setVideoOutput(self.preview_video_widget)

        # Ne pas charger les images ni les pauses dans le player
        if self.media_path and not is_image and not self.is_tempo:
            self.preview_player.setSource(QUrl.fromLocalFile(self.media_path))

    def toggle_play_pause(self):
        """Toggle play/pause avec timer - synchro preview et player principal"""
        main_playing = self.main_window.player.playbackState() == QMediaPlayer.PlayingState
        preview_playing = self.preview_player.playbackState() == QMediaPlayer.PlayingState

        if preview_playing or main_playing:
            # Arreter les deux
            self.preview_player.pause()
            self.main_window.player.pause()
            self.play_pause_btn.setIcon(create_icon("play", "#ffffff"))
            self.playback_timer.stop()
            # Arrêter les effets actifs (séquence et effet track)
            if self._seq_clip_active is not None or self._eff_clip_active is not None:
                self.main_window.active_effect        = None
                self.main_window.active_effect_config = {}
                if hasattr(self.main_window, 'stop_effect'):
                    self.main_window.stop_effect()
                self._seq_clip_active = None
                self._eff_clip_active = None
        else:
            # Lancer le preview a la position actuelle du curseur
            pos = int(self.playback_position)
            if pos > 0:
                self.preview_player.setPosition(pos)
            self.preview_player.play()
            self.play_pause_btn.setIcon(create_icon("pause", "#ffffff"))
            self.playback_timer.start(40)

    def seek_relative(self, delta_ms):
        """Seek relatif (+/- 10s)"""
        current = self.preview_player.position()
        new_pos = max(0, min(current + delta_ms, self.media_duration))
        self.preview_player.setPosition(int(new_pos))

    def _go_to_start(self):
        """Aller au début de la timeline"""
        self.preview_player.setPosition(0)
        self.playback_position = 0
        self.ruler.update()
        for track in self.tracks:
            track.update()

    def _go_to_end(self):
        """Aller à la fin de la timeline"""
        self.preview_player.setPosition(int(self.media_duration))
        self.playback_position = self.media_duration
        self.ruler.update()
        for track in self.tracks:
            track.update()

    def zoom_in(self):
        """Zoom avant centre sur le curseur rouge"""
        self.apply_zoom(1.3)

    def zoom_out(self):
        """Zoom arriere centre sur le curseur rouge"""
        self.apply_zoom(1.0 / 1.3)

    def apply_zoom(self, factor):
        """Applique le zoom en gardant le curseur rouge au meme endroit dans la vue"""
        old_zoom = self.current_zoom
        self.current_zoom = max(0.02, min(10.0, self.current_zoom * factor))

        scrollbar = self.tracks_scroll.horizontalScrollBar()
        viewport_width = self.tracks_scroll.viewport().width()

        # Calculer ou est le curseur dans le viewport AVANT le zoom
        old_pixels_per_ms = 0.05 * old_zoom
        cursor_abs_x = 145 + self.playback_position * old_pixels_per_ms
        cursor_viewport_x = cursor_abs_x - scrollbar.value()

        # Appliquer le nouveau zoom aux pistes
        new_pixels_per_ms = 0.05 * self.current_zoom
        for track in self.tracks:
            track.update_zoom(new_pixels_per_ms)
        self.track_waveform.update_zoom(new_pixels_per_ms)

        # Mettre a jour le label
        self.zoom_label.setText(f"{int(self.current_zoom * 100)}%")

        # Calculer la nouvelle position absolue du curseur
        new_cursor_abs_x = 145 + self.playback_position * new_pixels_per_ms

        # Ajuster le scroll pour que le curseur reste au meme endroit dans le viewport
        new_scroll = new_cursor_abs_x - cursor_viewport_x
        scrollbar.setValue(max(0, int(new_scroll)))

        # Forcer le rafraichissement
        self.ruler.update()
        self.tracks_scroll.viewport().update()

    def ruler_mouse_press(self, event):
        """Clic sur ruler pour deplacer le curseur"""
        self.ruler_dragging = True
        self.update_cursor_from_ruler(event)

    def ruler_mouse_move(self, event):
        """Drag sur ruler"""
        if hasattr(self, 'ruler_dragging') and self.ruler_dragging:
            self.update_cursor_from_ruler(event)

    def ruler_mouse_release(self, event):
        """Release sur ruler"""
        self.ruler_dragging = False

    def on_scroll_changed(self, value):
        """Met a jour le ruler quand on scroll"""
        self.ruler.update()

    def update_cursor_from_ruler(self, event):
        """Met a jour curseur depuis position souris (avec auto-scroll aux bords)"""
        x = event.position().x()
        viewport_width = self.ruler.width()
        scrollbar = self.tracks_scroll.horizontalScrollBar()

        # Auto-scroll si pres des bords (zone de 80px)
        edge_zone = 80
        scroll_speed = 30

        if x < edge_zone:
            # Scroll vers la gauche
            new_scroll = max(0, scrollbar.value() - scroll_speed)
            scrollbar.setValue(new_scroll)
        elif x > viewport_width - edge_zone:
            # Scroll vers la droite
            new_scroll = scrollbar.value() + scroll_speed
            scrollbar.setValue(new_scroll)

        # Calculer la position temporelle en tenant compte du scroll actuel
        scroll_offset = scrollbar.value()
        x_in_content = x + scroll_offset

        pixels_per_ms = 0.05 * self.current_zoom
        time_ms = (x_in_content - 145) / pixels_per_ms
        time_ms = max(0, min(time_ms, self.media_duration))

        self.playback_position = time_ms
        self.preview_player.setPosition(int(time_ms))

        # Mettre a jour le compteur
        pos_sec = int(time_ms / 1000)
        self.position_label.setText(f"⏱ {pos_sec // 60}:{pos_sec % 60:02d} / {self.total_time_str}")

        # Rafraichir l'affichage
        self.ruler.update()
        for track in self.tracks:
            track.update()
        self.track_waveform.update()

        # Mettre à jour le plan de feu en temps réel pendant le scrub
        self._apply_preview_to_projectors(self.playback_position)

    def ensure_playhead_visible(self):
        """S'assure que le curseur de lecture est visible - auto-scroll pendant lecture"""
        scrollbar = self.tracks_scroll.horizontalScrollBar()
        viewport_width = self.tracks_scroll.viewport().width()
        scroll_pos = scrollbar.value()

        pixels_per_ms = 0.05 * self.current_zoom
        cursor_abs_x = 145 + int(self.playback_position * pixels_per_ms)

        # Zone visible: de scroll_pos a scroll_pos + viewport_width
        visible_start = scroll_pos
        visible_end = scroll_pos + viewport_width

        # Marge pour anticiper le scroll (150px avant le bord)
        margin = 150

        if cursor_abs_x > visible_end - margin:
            # Le curseur approche du bord droit - scroll pour le garder visible
            new_scroll = cursor_abs_x - viewport_width + margin
            scrollbar.setValue(int(new_scroll))
            self.ruler.update()
        elif cursor_abs_x < visible_start + 50:
            # Le curseur est trop a gauche
            new_scroll = max(0, cursor_abs_x - 50)
            scrollbar.setValue(int(new_scroll))
            self.ruler.update()

    def paint_ruler(self, event):
        """Dessine la regle temporelle avec curseur rouge (synchronise avec scroll)"""
        painter = QPainter(self.ruler)
        painter.fillRect(0, 0, self.ruler.width(), self.ruler.height(), QColor("#1a1a1a"))

        # Recuperer le scroll horizontal pour synchroniser
        scroll_offset = self.tracks_scroll.horizontalScrollBar().value()

        painter.setPen(QColor("#888"))
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)

        pixels_per_ms = 0.05 * self.current_zoom

        if self.current_zoom < 0.5:
            step = 5
        elif self.current_zoom < 1.0:
            step = 2
        else:
            step = 1

        for sec in range(0, int(self.media_duration / 1000) + 1, step):
            x = 145 + int(sec * 1000 * pixels_per_ms) - scroll_offset
            if -50 < x < self.ruler.width() + 50:
                painter.drawLine(x, 25, x, 35)

                if sec >= 60:
                    minutes = sec // 60
                    seconds = sec % 60
                    time_str = f"{minutes}:{seconds:02d}"
                else:
                    time_str = f"{sec}s"

                painter.drawText(x - 18, 18, time_str)

        # Curseur de lecture (rouge) - aussi decale par le scroll
        cursor_x = 145 + int(self.playback_position * pixels_per_ms) - scroll_offset
        if -10 < cursor_x < self.ruler.width() + 10:
            painter.setPen(QPen(QColor("#ff0000"), 3))
            painter.drawLine(cursor_x, 0, cursor_x, self.ruler.height())

            painter.setBrush(QColor("#ff0000"))
            painter.setPen(Qt.NoPen)
            triangle = QPolygon([
                QPoint(cursor_x - 6, 0),
                QPoint(cursor_x + 6, 0),
                QPoint(cursor_x, 10)
            ])
            painter.drawPolygon(triangle)

    def _on_main_player_state_changed(self, state):
        """Démarre/arrête le timer playhead selon l'état du player principal."""
        if state == QMediaPlayer.PlayingState:
            if not self.playback_timer.isActive():
                self.playback_timer.start(40)
        else:
            # Arrêter seulement si le preview interne ne joue pas non plus
            if self.preview_player.playbackState() != QMediaPlayer.PlayingState:
                self.playback_timer.stop()

    def update_playhead(self):
        """Met a jour la position du curseur pendant lecture (preview ou player principal)"""
        playing = False

        if self.preview_player.playbackState() == QMediaPlayer.PlayingState:
            self.playback_position = self.preview_player.position()
            playing = True
        elif self.main_window.player.playbackState() == QMediaPlayer.PlayingState:
            self.playback_position = self.main_window.player.position()
            playing = True

        if playing:
            # Auto-scroll pour suivre le curseur pendant la lecture
            self.ensure_playhead_visible()

            # Mettre a jour le compteur de position
            pos_sec = int(self.playback_position / 1000)
            self.position_label.setText(f"⏱ {pos_sec // 60}:{pos_sec % 60:02d} / {self.total_time_str}")

            # Mise à jour dirty-rect : uniquement la bande du curseur (ancien + nouveau)
            ppm = self.tracks[0].pixels_per_ms if self.tracks else 0
            if ppm > 0 and self.playback_position != self._prev_playback_position:
                old_x = 145 + int(self._prev_playback_position * ppm)
                new_x = 145 + int(self.playback_position * ppm)
                for track in self.tracks:
                    h = track.height()
                    track.update(QRect(old_x - 2, 0, 5, h))
                    track.update(QRect(new_x - 2, 0, 5, h))
                self.track_waveform.update(QRect(old_x - 2, 0, 5, self.track_waveform.height()))
                self.track_waveform.update(QRect(new_x - 2, 0, 5, self.track_waveform.height()))
            else:
                for track in self.tracks:
                    track.update()
                self.track_waveform.update()
            self.ruler.update()
            self._prev_playback_position = self.playback_position

            # Appliquer les clips actifs aux projecteurs pour le plan de feu live
            self._apply_preview_to_projectors(self.playback_position)

    def _apply_preview_to_projectors(self, current_time):
        """Applique directement les clips actifs aux projecteurs (preview rapide)."""
        if self._live_pdf is None:
            return

        track_to_indices = self.main_window.get_track_to_indices()
        projectors = self.main_window.projectors

        # Éteindre tous les projecteurs
        for p in projectors:
            p.level = 0
            p.base_color = QColor("black")
            p.color = QColor("black")

        # ── Détecter le clip de séquence actif ───────────────────────────────
        seq_track = self.track_map.get("Séquence")
        new_seq_clip = None
        if seq_track:
            for clip in seq_track.clips:
                if clip.start_time <= current_time <= clip.start_time + clip.duration:
                    new_seq_clip = clip
                    break

        # Changement de clip de séquence → gérer l'effet associé
        if new_seq_clip is not self._seq_clip_active:
            if self._seq_clip_active is not None:
                self.main_window.active_effect        = None
                self.main_window.active_effect_config = {}
                if hasattr(self.main_window, 'stop_effect'):
                    self.main_window.stop_effect()
            self._seq_clip_active = new_seq_clip
            if new_seq_clip:
                mem_ref = getattr(new_seq_clip, 'memory_ref', None)
                if mem_ref:
                    memories = getattr(self.main_window, 'memories', None)
                    if memories:
                        mem_col, row = mem_ref
                        mem = memories[mem_col][row] if mem_col < len(memories) and row < len(memories[mem_col]) else None
                        if mem:
                            eff_cfg = mem.get("effect")
                            if eff_cfg and eff_cfg.get("layers") and hasattr(self.main_window, 'start_effect'):
                                self.main_window.active_effect = eff_cfg.get("name", "")
                                self.main_window.active_effect_config = eff_cfg
                                self.main_window.start_effect(eff_cfg.get("name", ""))

        # ── Détecter le clip d'effet actif ───────────────────────────────────
        eff_track = self.track_map.get("Effet")
        new_eff_clip = None
        if eff_track:
            for clip in eff_track.clips:
                if clip.start_time <= current_time <= clip.start_time + clip.duration:
                    new_eff_clip = clip
                    break

        if new_eff_clip is not self._eff_clip_active:
            if self._eff_clip_active is not None:
                prev_name = getattr(self._eff_clip_active, 'effect_name', '')
                if getattr(self.main_window, 'active_effect', None) == prev_name:
                    self.main_window.active_effect        = None
                    self.main_window.active_effect_config = {}
                    if hasattr(self.main_window, 'stop_effect'):
                        self.main_window.stop_effect()
            self._eff_clip_active = new_eff_clip
            if new_eff_clip:
                eff_name = getattr(new_eff_clip, 'effect_name', '')
                if eff_name:
                    eff_layers = list(getattr(new_eff_clip, 'effect_layers', []))
                    eff_type   = getattr(new_eff_clip, 'effect_type', '')
                    if not eff_layers:
                        try:
                            from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
                            for _e in BUILTIN_EFFECTS + _load_custom_effects():
                                if _e.get('name') == eff_name:
                                    eff_layers = [dict(l) for l in _e.get('layers', [])]
                                    eff_type   = _e.get('type', '')
                                    break
                        except Exception:
                            pass
                    cfg = {
                        'name': eff_name, 'type': eff_type, 'layers': eff_layers, 'play_mode': 'loop',
                        'target_groups': getattr(new_eff_clip, 'effect_target_groups', []),
                        'speed_override': getattr(new_eff_clip, 'effect_speed', 50),
                    }
                    self.main_window.active_effect        = eff_name
                    self.main_window.active_effect_config = cfg
                    if hasattr(self.main_window, 'start_effect'):
                        self.main_window.start_effect(eff_name)

        # ── 1) Appliquer les clips de couleur par groupe (priorité basse) ─────
        for track in self.tracks:
            if getattr(track, 'is_sequence_track', False) or getattr(track, 'is_effect_track', False):
                continue
            for clip in track.clips:
                start = clip.start_time
                end = start + clip.duration
                if start <= current_time <= end:
                    intensity = clip.intensity
                    fade_in = getattr(clip, 'fade_in_duration', 0)
                    fade_out = getattr(clip, 'fade_out_duration', 0)
                    elapsed = current_time - start
                    remaining = end - current_time
                    if fade_in > 0 and elapsed < fade_in:
                        intensity = int(intensity * elapsed / fade_in)
                    elif fade_out > 0 and remaining < fade_out:
                        intensity = int(intensity * remaining / fade_out)

                    color = clip.color
                    brightness = intensity / 100.0
                    display_color = QColor(
                        int(color.red()   * brightness),
                        int(color.green() * brightness),
                        int(color.blue()  * brightness),
                    )
                    for idx in track_to_indices.get(track.name, []):
                        if idx < len(projectors):
                            p = projectors[idx]
                            p.level = intensity
                            p.base_color = color
                            p.color = display_color
                    break

        # ── 2) Appliquer la séquence par-dessus les groupes (priorité haute) ──
        if new_seq_clip:
            mem_ref = getattr(new_seq_clip, 'memory_ref', None)
            if mem_ref:
                mem_col, row = mem_ref
                memories = getattr(self.main_window, 'memories', None)
                if memories and mem_col < len(memories) and row < len(memories[mem_col]):
                    mem = memories[mem_col][row]
                    if mem:
                        brightness = new_seq_clip.intensity / 100.0
                        for i, ps in enumerate(mem.get("projectors", [])):
                            if i >= len(projectors):
                                continue
                            p = projectors[i]
                            # Pan/Tilt toujours appliqués (même si projecteur éteint)
                            if "pan"  in ps: p.pan  = ps["pan"]
                            if "tilt" in ps: p.tilt = ps["tilt"]
                            if ps.get("level", 0) > 0:
                                lvl = int(ps["level"] * brightness)
                                base = QColor(ps["base_color"])
                                p.level = lvl
                                p.base_color = base
                                p.color = QColor(
                                    int(base.red()   * lvl / 100.0),
                                    int(base.green() * lvl / 100.0),
                                    int(base.blue()  * lvl / 100.0),
                                )

        # ── 3) Appliquer l'effet courant (priorité maximale) ─────────────────
        if getattr(self.main_window, 'active_effect', None) and hasattr(self.main_window, 'update_effect'):
            self.main_window.update_effect()

        if hasattr(self.main_window, 'send_dmx_update'):
            self.main_window.send_dmx_update()
        if self._live_pdf is not None:
            self._live_pdf.update()

    def load_existing_sequence(self):
        """Charge la sequence existante si elle existe"""
        if self.media_row in self.main_window.seq.sequences:
            seq = self.main_window.seq.sequences[self.media_row]
            clips_data = seq.get('clips', [])

            for clip_data in clips_data:
                track_name = clip_data.get('track')
                track = self.track_map.get(track_name)

                if track:
                    color = QColor(clip_data.get('color', '#ffffff'))
                    clip = track.add_clip(
                        clip_data.get('start', 0),
                        clip_data.get('duration', 1000),
                        color,
                        clip_data.get('intensity', 80)
                    )

                    clip.fade_in_duration = clip_data.get('fade_in', 0)
                    clip.fade_out_duration = clip_data.get('fade_out', 0)
                    clip.effect = clip_data.get('effect')
                    clip.effect_speed = clip_data.get('effect_speed', 50)
                    clip.effect_layers    = clip_data.get('effect_layers', [])
                    clip.effect_play_mode = clip_data.get('effect_play_mode', 'loop')
                    clip.effect_duration  = clip_data.get('effect_duration', 0)
                    clip.effect_name         = clip_data.get('effect_name', '')
                    clip.effect_type         = clip_data.get('effect_type', '')
                    clip.effect_target_groups = clip_data.get('effect_target_groups', [])
                    if clip_data.get('color2'):
                        clip.color2 = QColor(clip_data['color2'])
                    clip.pan_start      = clip_data.get('pan_start', 128)
                    clip.tilt_start     = clip_data.get('tilt_start', 128)
                    clip.pan_end        = clip_data.get('pan_end', 128)
                    clip.tilt_end       = clip_data.get('tilt_end', 128)
                    clip.move_effect    = clip_data.get('move_effect', None)
                    clip.move_speed     = clip_data.get('move_speed', 0.5)
                    clip.move_amplitude = clip_data.get('move_amplitude', 60)
                    if clip_data.get('memory_ref'):
                        clip.memory_ref   = tuple(clip_data['memory_ref'])
                        clip.memory_label = clip_data.get('memory_label', '')

            # Charger la forme d'onde depuis les donnees de sequence
            waveform = seq.get('waveform')
            if waveform:
                self.track_waveform.waveform_data = waveform
                for track in self.tracks:
                    track.waveform_data = waveform

            # Rafraichir toutes les pistes
            for track in self.tracks:
                track.update()

        # Sauvegarder l'etat initial pour undo
        self.save_state()

    def _save_sequence_no_close(self):
        """Sauvegarde seq.sequences sans fermer l'éditeur (modif inline d'un clip)."""
        all_clips = []
        for track in self.tracks:
            for clip in track.clips:
                clip_data = {
                    'track': track.name,
                    'start': clip.start_time,
                    'duration': clip.duration,
                    'color': clip.color.name(),
                    'intensity': clip.intensity,
                    'fade_in': getattr(clip, 'fade_in_duration', 0),
                    'fade_out': getattr(clip, 'fade_out_duration', 0),
                    'effect': getattr(clip, 'effect', None),
                    'effect_speed': getattr(clip, 'effect_speed', 50),
                    'effect_layers': getattr(clip, 'effect_layers', []),
                    'effect_play_mode': getattr(clip, 'effect_play_mode', 'loop'),
                    'effect_duration': getattr(clip, 'effect_duration', 0),
                    'effect_name': getattr(clip, 'effect_name', ''),
                    'effect_type': getattr(clip, 'effect_type', ''),
                    'effect_target_groups': getattr(clip, 'effect_target_groups', []),
                }
                if hasattr(clip, 'color2') and clip.color2:
                    clip_data['color2'] = clip.color2.name()
                if getattr(clip, 'memory_ref', None):
                    clip_data['memory_ref'] = list(clip.memory_ref)
                    clip_data['memory_label'] = getattr(clip, 'memory_label', '')
                if (getattr(clip, 'move_effect', None) or
                        getattr(clip, 'pan_start', 128) != 128 or getattr(clip, 'pan_end', 128) != 128 or
                        getattr(clip, 'tilt_start', 128) != 128 or getattr(clip, 'tilt_end', 128) != 128):
                    clip_data.update({
                        'pan_start': getattr(clip, 'pan_start', 128), 'tilt_start': getattr(clip, 'tilt_start', 128),
                        'pan_end': getattr(clip, 'pan_end', 128), 'tilt_end': getattr(clip, 'tilt_end', 128),
                        'move_effect': getattr(clip, 'move_effect', None),
                        'move_speed': getattr(clip, 'move_speed', 0.5),
                        'move_amplitude': getattr(clip, 'move_amplitude', 60),
                    })
                all_clips.append(clip_data)
        self.main_window.seq.sequences[self.media_row] = {
            'clips': all_clips,
            'duration': self.media_duration,
            'waveform': [round(x, 3) for x in self.track_waveform.waveform_data] if self.track_waveform.waveform_data else None
        }
        self.main_window.seq.is_dirty = True

    def save_sequence(self):
        """Sauvegarde la sequence au format .tui avec effets et bicolore"""
        all_clips = []
        for track in self.tracks:
            for clip in track.clips:
                clip_data = {
                    'track': track.name,
                    'start': clip.start_time,
                    'duration': clip.duration,
                    'color': clip.color.name(),
                    'intensity': clip.intensity,
                    'fade_in': getattr(clip, 'fade_in_duration', 0),
                    'fade_out': getattr(clip, 'fade_out_duration', 0),
                    'effect': getattr(clip, 'effect', None),
                    'effect_speed': getattr(clip, 'effect_speed', 50),
                    'effect_layers': getattr(clip, 'effect_layers', []),
                    'effect_play_mode': getattr(clip, 'effect_play_mode', 'loop'),
                    'effect_duration':  getattr(clip, 'effect_duration', 0),
                    'effect_name':         getattr(clip, 'effect_name', ''),
                    'effect_type':         getattr(clip, 'effect_type', ''),
                    'effect_target_groups': getattr(clip, 'effect_target_groups', []),
                }

                if hasattr(clip, 'color2') and clip.color2:
                    clip_data['color2'] = clip.color2.name()
                # Clip de séquence AKAI
                if getattr(clip, 'memory_ref', None):
                    clip_data['memory_ref'] = list(clip.memory_ref)
                    clip_data['memory_label'] = getattr(clip, 'memory_label', '')
                # Mouvement Pan/Tilt
                if (getattr(clip, 'move_effect', None) or
                        getattr(clip, 'pan_start', 128) != 128 or
                        getattr(clip, 'pan_end', 128) != 128 or
                        getattr(clip, 'tilt_start', 128) != 128 or
                        getattr(clip, 'tilt_end', 128) != 128):
                    clip_data.update({
                        'pan_start':     getattr(clip, 'pan_start', 128),
                        'tilt_start':    getattr(clip, 'tilt_start', 128),
                        'pan_end':       getattr(clip, 'pan_end', 128),
                        'tilt_end':      getattr(clip, 'tilt_end', 128),
                        'move_effect':   getattr(clip, 'move_effect', None),
                        'move_speed':    getattr(clip, 'move_speed', 0.5),
                        'move_amplitude':getattr(clip, 'move_amplitude', 60),
                    })
                all_clips.append(clip_data)

        self.main_window.seq.sequences[self.media_row] = {
            'clips': all_clips,
            'duration': self.media_duration,
            'waveform': [round(x, 3) for x in self.track_waveform.waveform_data] if self.track_waveform.waveform_data else None
        }

        self.main_window.seq.is_dirty = True
        self._saved_history_index = self.history_index  # marquer propre

        combo = self.main_window.seq._get_dmx_combo(self.media_row)
        if combo:
            if combo.findText("Play Lumiere") == -1:
                combo.addItem("Play Lumiere")
            combo.blockSignals(True)
            combo.setCurrentText("Play Lumiere")
            combo.blockSignals(False)
            self.main_window.seq.on_dmx_changed(self.media_row, "Play Lumiere")

        # Auto-export .lrec à côté du fichier média
        self._autosave_lrec(all_clips)

        self.close_editor()

    # ── Import / Export ──────────────────────────────────────────────────

    def export_sequence(self):
        """Exporte le REC lumière dans un fichier .lrec (JSON)"""
        import json as _json
        default_name = (self.media_name or "rec_lumiere").replace(" ", "_") + ".lrec"
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le REC lumière", default_name,
            "REC Lumière (*.lrec);;JSON (*.json)"
        )
        if not path:
            return

        all_clips = []
        for track in self.tracks:
            for clip in track.clips:
                clip_data = {
                    'track': track.name,
                    'start': clip.start_time,
                    'duration': clip.duration,
                    'color': clip.color.name(),
                    'intensity': clip.intensity,
                    'fade_in': getattr(clip, 'fade_in_duration', 0),
                    'fade_out': getattr(clip, 'fade_out_duration', 0),
                    'effect': getattr(clip, 'effect', None),
                    'effect_speed': getattr(clip, 'effect_speed', 50),
                    'effect_layers': getattr(clip, 'effect_layers', []),
                    'effect_play_mode': getattr(clip, 'effect_play_mode', 'loop'),
                    'effect_duration':  getattr(clip, 'effect_duration', 0),
                    'effect_name':         getattr(clip, 'effect_name', ''),
                    'effect_type':         getattr(clip, 'effect_type', ''),
                    'effect_target_groups': getattr(clip, 'effect_target_groups', []),
                }
                if hasattr(clip, 'color2') and clip.color2:
                    clip_data['color2'] = clip.color2.name()
                all_clips.append(clip_data)

        data = {
            'version': 1,
            'media_name': self.media_name,
            'duration': self.media_duration,
            'clips': all_clips,
        }

        try:
            with open(path, 'w', encoding='utf-8') as f:
                _json.dump(data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, tr("te_export_ok_title"),
                tr("te_export_ok_msg", n=len(all_clips), path=path))
        except Exception as e:
            QMessageBox.critical(self, tr("te_export_err_title"), str(e))

    def import_sequence(self):
        """Importe un fichier .lrec dans l'éditeur (remplace les clips existants)"""
        import json as _json
        path, _ = QFileDialog.getOpenFileName(
            self, tr("te_import_dlg_title"), "",
            tr("te_import_filter")
        )
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)
        except Exception as e:
            QMessageBox.critical(self, tr("te_import_err_title"), tr("te_import_err_msg", e=e))
            return

        clips_data = data.get('clips', [])
        if not clips_data:
            QMessageBox.warning(self, tr("te_import_ok_title"), tr("te_import_no_clips"))
            return

        # Avertissement si des clips dépassent la durée du média courant
        out_of_bounds = [c for c in clips_data
                         if c.get('start', 0) + c.get('duration', 0) > self.media_duration]
        warning_msg = ""
        if out_of_bounds:
            src_duration_s = data.get('duration', 0) / 1000
            cur_duration_s = self.media_duration / 1000
            warning_msg = tr("te_import_warn",
                n=len(out_of_bounds), cur=cur_duration_s, src=src_duration_s)

        reply = QMessageBox.question(
            self, tr("te_import_confirm_title"),
            tr("te_import_confirm_msg", n=len(clips_data), path=path, warn=warning_msg),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # Effacer les clips actuels
        for track in self.tracks:
            track.clips.clear()

        # Charger les nouveaux clips
        for clip_data in clips_data:
            track_name = clip_data.get('track')
            track = self.track_map.get(track_name)
            if not track:
                continue
            color = QColor(clip_data.get('color', '#ffffff'))
            clip = track.add_clip(
                clip_data.get('start', 0),
                clip_data.get('duration', 1000),
                color,
                clip_data.get('intensity', 80)
            )
            clip.fade_in_duration  = clip_data.get('fade_in', 0)
            clip.fade_out_duration = clip_data.get('fade_out', 0)
            clip.effect            = clip_data.get('effect')
            clip.effect_speed      = clip_data.get('effect_speed', 50)
            clip.effect_layers     = clip_data.get('effect_layers', [])
            clip.effect_play_mode  = clip_data.get('effect_play_mode', 'loop')
            clip.effect_duration   = clip_data.get('effect_duration', 0)
            clip.effect_name       = clip_data.get('effect_name', '')
            clip.effect_type       = clip_data.get('effect_type', '')
            if clip_data.get('color2'):
                clip.color2 = QColor(clip_data['color2'])

        for track in self.tracks:
            track.update()

        self.save_state()
        QMessageBox.information(self, tr("te_import_ok_title"),
            tr("te_import_ok_msg", n=len(clips_data)))

    def clear_all_clips(self):
        """Efface tous les clips"""
        reply = QMessageBox.question(self, tr("te_clear_title"),
            tr("te_clear_msg"),
            QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            for track in self.tracks:
                track.clips.clear()
                track.update()

    def generate_ai_sequence(self):
        """Genere une sequence avec IA"""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("te_ai_title"))
        dialog.setFixedSize(550, 450)
        dialog.setStyleSheet("background: #1a1a1a;")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(tr("te_ai_color_label"))
        title.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        color_combo = QComboBox()
        color_combo.setStyleSheet("""
            QComboBox {
                background: #2a2a2a;
                color: white;
                border: 1px solid #3a3a3a;
                padding: 10px;
                border-radius: 6px;
                font-size: 14px;
            }
        """)

        colors = [
            (tr("te_ai_color_red"),     "#ff0000"),
            (tr("color_vert"),          "#00ff00"),
            (tr("te_ai_color_blue"),    "#0000ff"),
            (tr("color_jaune"),         "#c8c800"),
            (tr("color_magenta"),       "#ff00ff"),
            (tr("color_cyan"),          "#00ffff"),
            (tr("color_orange"),        "#ff8800"),
            (tr("te_ai_color_violet"),  "#8800ff"),
            (tr("te_ai_color_white"),   "#ffffff"),
            (tr("te_ai_color_rainbow"), "rainbow"),
        ]

        for name, _ in colors:
            color_combo.addItem(name)

        layout.addWidget(color_combo)

        # Checkboxes pistes
        tracks_label = QLabel(tr("te_ai_tracks_label"))
        tracks_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-top: 10px;")
        layout.addWidget(tracks_label)

        tracks_checks = {}
        for track in self.tracks:
            if getattr(track, 'is_sequence_track', False):
                continue
            clip_count = len(track.clips)
            checkbox = QCheckBox(f"{track.name} {'(' + str(clip_count) + ' clips)' if clip_count > 0 else ''}")
            checkbox.setChecked(True)
            checkbox.setStyleSheet("""
                QCheckBox { color: white; font-size: 13px; spacing: 10px; }
                QCheckBox::indicator { width: 20px; height: 20px; }
            """)
            tracks_checks[track] = checkbox
            layout.addWidget(checkbox)

        # Progress
        progress = QProgressBar()
        progress.setVisible(False)
        progress.setStyleSheet("""
            QProgressBar {
                background: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                text-align: center;
                color: white;
                height: 30px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #8B00FF, stop:1 #FF00FF);
                border-radius: 6px;
            }
        """)
        layout.addWidget(progress)

        status_label = QLabel("")
        status_label.setStyleSheet("color: #888; font-size: 12px;")
        status_label.setVisible(False)
        layout.addWidget(status_label)

        layout.addStretch()

        # Boutons
        btn_layout = QHBoxLayout()

        cancel_btn = QPushButton(tr("te_ai_cancel"))
        cancel_btn.clicked.connect(dialog.reject)
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
                font-size: 14px;
            }
            QPushButton:hover { background: #4a4a4a; }
        """)
        btn_layout.addWidget(cancel_btn)

        generate_btn = QPushButton(tr("te_ai_generate"))
        generate_btn.setFixedHeight(40)
        generate_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #8B00FF, stop:1 #FF00FF);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 30px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #9B10FF, stop:1 #FF10FF);
            }
        """)

        def start_generation():
            generate_btn.setEnabled(False)
            color_combo.setEnabled(False)
            progress.setVisible(True)
            status_label.setVisible(True)

            selected_idx = color_combo.currentIndex()
            _, color_code = colors[selected_idx]

            selected_tracks = [track for track, checkbox in tracks_checks.items() if checkbox.isChecked()]
            self.perform_ai_generation(color_code, selected_tracks, progress, status_label, dialog)

        generate_btn.clicked.connect(start_generation)
        btn_layout.addWidget(generate_btn)

        layout.addLayout(btn_layout)
        dialog.exec()

    def perform_ai_generation(self, color_code, selected_tracks, progress, status_label, dialog):
        """Genere les clips avec progression et rythme dynamique"""
        self.save_state()  # snapshot avant génération → permet le undo
        for track in selected_tracks:
            track.clips.clear()

        progress.setValue(10)
        status_label.setText(tr("te_ai_detecting_beats"))
        QApplication.processEvents()

        # ── Palette complete (toutes les couleurs vivides) ───────────────
        FULL_PALETTE = [
            QColor("#ff0000"), QColor("#ff4400"), QColor("#ff8800"),
            QColor("#ffcc00"), QColor("#c8ff00"), QColor("#00ff44"),
            QColor("#00ffcc"), QColor("#00ccff"), QColor("#0066ff"),
            QColor("#4400ff"), QColor("#aa00ff"), QColor("#ff00cc"),
            QColor("#ff0066"), QColor("#ffffff"), QColor("#ffcc44"),
        ]

        # Palette selon la couleur choisie
        if color_code == "rainbow":
            palette = FULL_PALETTE[:]
        else:
            base = QColor(color_code)
            # Couleur choisie + ses voisines complementaires dans FULL_PALETTE
            palette = [base]
            # Ajouter couleurs complementaires (hue +30, +60, +150, +180, +210)
            h = base.hsvHue() if base.hsvHue() >= 0 else 0
            for offset in [30, 60, 120, 150, 180, 210, 300, 330]:
                palette.append(QColor.fromHsv((h + offset) % 360, 255, 255))

        # S'assurer que la palette a assez de couleurs pour alterner entre les pistes
        while len(palette) < max(len(selected_tracks), 4):
            palette = palette * 2

        progress.setValue(20)
        status_label.setText(tr("te_ai_analysing"))
        QApplication.processEvents()

        duration_ms = self.media_duration
        BASE_BEAT = 500  # 500 ms = 1 beat a 120 BPM

        # ── Detection des beats depuis la waveform ───────────────────────
        waveform = getattr(self.track_waveform, 'waveform_data', None)
        beat_positions = []  # liste de (time_ms, energy 0-1)

        if waveform and len(waveform) > 30:
            n = len(waveform)
            max_e = max(waveform) or 1.0
            ms_per_pt = duration_ms / n

            # Lisser la waveform
            smooth = []
            w = max(1, n // 120)
            for i in range(n):
                chunk = waveform[max(0, i - w): i + w + 1]
                smooth.append(sum(chunk) / len(chunk))

            # Trouver les onsets (montees d'energie significatives)
            threshold = (sum(smooth) / n) * 0.6
            min_gap_pts = int(250 / ms_per_pt)  # 250 ms min entre 2 beats
            last_beat = -min_gap_pts

            for i in range(1, n - 1):
                flux = max(0.0, smooth[i] - smooth[i - 1])
                if flux > 0.0 and smooth[i] > threshold and (i - last_beat) >= min_gap_pts:
                    # Energie locale = moyenne autour du pic
                    e_chunk = smooth[max(0, i - w): i + w + 1]
                    e_local = (sum(e_chunk) / len(e_chunk)) / max_e
                    beat_positions.append((int(i * ms_per_pt), e_local))
                    last_beat = i

        # Fallback : beats reguliers si waveform insuffisante
        if len(beat_positions) < 4:
            t = 0
            while t < duration_ms:
                p = t / max(1, duration_ms)
                e = 0.9 if p < 0.08 else (0.85 if 0.45 < p < 0.72 else 0.55)
                beat_positions.append((t, e))
                t += BASE_BEAT

        # Ajouter la fin
        if not beat_positions or beat_positions[-1][0] < duration_ms - 100:
            beat_positions.append((duration_ms, 0.0))

        progress.setValue(35)
        status_label.setText(tr("te_ai_generating"))
        QApplication.processEvents()

        # ── Generation des clips ─────────────────────────────────────────
        n_tracks = len(selected_tracks)
        # Offset de couleur par piste : reparties uniformement dans la palette
        step = max(1, len(palette) // max(n_tracks, 1))
        track_offsets = [i * step for i in range(n_tracks)]

        clip_count = 0
        first_clip = {track: True for track in selected_tracks}

        for beat_idx, (t_start, e) in enumerate(beat_positions[:-1]):
            t_end = beat_positions[beat_idx + 1][0]
            clip_duration = t_end - t_start

            if clip_duration < 100:
                continue

            # Grouper plusieurs beats si energie faible (swing naturel)
            if e < 0.40 and beat_idx + 2 < len(beat_positions):
                # Doubler la duree sur les zones calmes
                t_end2 = beat_positions[beat_idx + 2][0]
                if t_end2 - t_start <= 3000:
                    clip_duration = t_end2 - t_start

            if t_start + clip_duration > duration_ms:
                clip_duration = duration_ms - t_start
            if clip_duration < 100:
                continue

            for ti, track in enumerate(selected_tracks):
                # Couleur de ce beat pour cette piste :
                # chaque piste tourne dans la palette avec son propre offset
                color_idx = (beat_idx + track_offsets[ti]) % len(palette)
                color = palette[color_idx]
                intensity = min(100, int(72 + e * 26) + random.randint(-4, 4))

                clip = track.add_clip(t_start, clip_duration, color, intensity)

                # Bicolore : couleur suivante dans la palette (50-65%)
                bicolor_prob = 0.65 if e > 0.60 else 0.45
                if random.random() < bicolor_prob:
                    color2_idx = (color_idx + len(palette) // 2) % len(palette)
                    clip.color2 = palette[color2_idx]

                # Fade In uniquement sur le tout premier clip
                if first_clip[track]:
                    fade_ms = min(int(clip_duration * 0.5), 1500)
                    if fade_ms >= 150:
                        clip.fade_in_duration = fade_ms
                    first_clip[track] = False

                clip_count += 1

            progress.setValue(35 + int((t_start / duration_ms) * 60))
            if beat_idx % 10 == 0:
                QApplication.processEvents()

        progress.setValue(100)
        status_label.setText(tr("te_ai_clips_created", n=clip_count))
        QApplication.processEvents()

        self.save_state()  # snapshot après génération → undo ramène ici
        QTimer.singleShot(800, dialog.accept)

    def wheelEvent(self, event):
        """Shift+Scroll = Zoom | Scroll = défilement horizontal de la timeline"""
        if event.modifiers() & Qt.ShiftModifier:
            # Zoom centré sur la barre rouge
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            # Scroll horizontal dans la timeline
            sb = self.tracks_scroll.horizontalScrollBar()
            delta = -event.angleDelta().y()
            sb.setValue(sb.value() + delta)
            event.accept()

    def _create_bottom_panel(self):
        """Panneau bas : [Couleurs + Séquences] | [Plan de Feu]"""
        _TITLE_SS = (
            "color: #444; font-size: 8px; font-weight: bold; letter-spacing: 2px; "
            "background: #111111; padding: 2px 10px; border-bottom: 1px solid #1e1e1e;"
        )
        panel = QWidget()
        panel.setStyleSheet("background: #111111; border-top: 1px solid #252525;")
        h = QHBoxLayout(panel)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ── Gauche : Couleurs + Séquences ────────────────────────────────
        left = QWidget()
        left.setStyleSheet("background: transparent;")
        v = QVBoxLayout(left)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.palette_panel = PalettePanel(self)
        v.addWidget(self.palette_panel)

        h.addWidget(left, 1)

        # Séparateur vertical
        vsep = QFrame()
        vsep.setFrameShape(QFrame.VLine)
        vsep.setFixedWidth(1)
        vsep.setStyleSheet("background: #252525; border: none;")
        h.addWidget(vsep)

        # ── Droite : Plan de Feu ─────────────────────────────────────────
        right = QWidget()
        right.setFixedWidth(260)
        right.setStyleSheet("background: #0d0d0d;")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        pdf_title = QLabel(tr("te_plan_label"))
        pdf_title.setStyleSheet(_TITLE_SS)
        rv.addWidget(pdf_title)

        try:
            pdf = PlanDeFeu(self.main_window.projectors, main_window=self.main_window, show_toolbar=False)
            pdf.setStyleSheet("border: none; background: #0d0d0d;")
            rv.addWidget(pdf, 1)
            self._live_pdf = pdf
            self._pdf_window = pdf   # garde dans _apply_preview_to_projectors
        except Exception:
            self._live_pdf = None
            self._pdf_window = None

        h.addWidget(right)
        return panel

    def _toggle_pdf_window(self, checked):
        """Toggle visibilité du panneau Plan de Feu (colonne droite du panneau bas)."""
        if not self._live_pdf:
            return
        parent = self._live_pdf.parent()
        if parent:
            parent.setVisible(checked)
        if self._pdf_show_action:
            self._pdf_show_action.setChecked(checked)

    def keyPressEvent(self, event):
        """Raccourcis clavier"""
        if event.key() == Qt.Key_Space:
            self.toggle_play_pause()
            event.accept()
            return
        elif event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            self.undo()
            event.accept()
            return
        elif event.key() == Qt.Key_Y and event.modifiers() & Qt.ControlModifier:
            self.redo()
            event.accept()
            return
        elif event.key() == Qt.Key_Delete:
            self.delete_selected_clips()
            event.accept()
            return
        elif event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self.select_all_clips()
            event.accept()
            return
        elif event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            self.copy_selected_clips()
            event.accept()
            return
        elif event.key() == Qt.Key_X and event.modifiers() & Qt.ControlModifier:
            self.cut_selected_clips()
            event.accept()
            return
        elif event.key() == Qt.Key_V and event.modifiers() & Qt.ControlModifier:
            self.paste_clips()
            event.accept()
            return
        elif event.key() == Qt.Key_C:
            # Touche C seule = Mode CUT
            self.cut_btn.setChecked(not self.cut_btn.isChecked())
            self.toggle_cut_mode()
            event.accept()
            return
        elif event.key() == Qt.Key_Escape:
            # Echap = Desactiver mode cut et deselectionner
            if self.cut_mode:
                self.cut_btn.setChecked(False)
                self.toggle_cut_mode()
            self.clear_all_selections()
            event.accept()
            return
        else:
            super().keyPressEvent(event)

    def select_all_clips(self):
        """Selectionne tous les clips de toutes les pistes"""
        for track in self.tracks:
            track.selected_clips = track.clips[:]
            track.update()

    def delete_selected_clips(self):
        """Supprime tous les clips selectionnes"""
        if not any(track.selected_clips for track in self.tracks):
            return

        total_deleted = 0
        for track in self.tracks:
            if track.selected_clips:
                count = len(track.selected_clips)
                for clip in track.selected_clips[:]:
                    track.clips.remove(clip)
                track.selected_clips.clear()
                track.update()
                total_deleted += count

        self.save_state()
        print(f"🗑️ {total_deleted} clip(s) supprime(s)")

    def copy_selected_clips(self):
        """Copie les clips selectionnes dans le clipboard"""
        self.clipboard = []
        min_start = None
        for track in self.tracks:
            for clip in track.selected_clips:
                if min_start is None or clip.start_time < min_start:
                    min_start = clip.start_time
                self.clipboard.append({
                    'track': track.name,
                    'start': clip.start_time,
                    'duration': clip.duration,
                    'color': clip.color.name(),
                    'color2': clip.color2.name() if clip.color2 else None,
                    'intensity': clip.intensity,
                    'fade_in': clip.fade_in_duration,
                    'fade_out': clip.fade_out_duration,
                    'effect': clip.effect,
                    'effect_speed': clip.effect_speed,
                    'effect_layers': getattr(clip, 'effect_layers', []),
                    'effect_play_mode': getattr(clip, 'effect_play_mode', 'loop'),
                    'effect_duration':  getattr(clip, 'effect_duration', 0),
                    'effect_name':         getattr(clip, 'effect_name', ''),
                    'effect_type':         getattr(clip, 'effect_type', ''),
                    'effect_target_groups': getattr(clip, 'effect_target_groups', []),
                })
        # Stocker les offsets relatifs au premier clip
        if min_start is not None:
            for item in self.clipboard:
                item['offset'] = item['start'] - min_start
        if self.clipboard:
            print(f"📋 {len(self.clipboard)} clip(s) copie(s)")

    def cut_selected_clips(self):
        """Coupe les clips selectionnes (copie + suppression)"""
        self.copy_selected_clips()
        if self.clipboard:
            self.delete_selected_clips()
            print(f"✂️ {len(self.clipboard)} clip(s) coupe(s)")

    def paste_clips(self):
        """Colle les clips du clipboard a la position du curseur"""
        if not self.clipboard:
            return

        paste_time = self.playback_position
        track_map = {t.name: t for t in self.tracks}

        self.clear_all_selections()
        count = 0
        for item in self.clipboard:
            track = track_map.get(item['track'])
            if not track:
                continue
            start = paste_time + item.get('offset', 0)
            clip = track.add_clip(start, item['duration'], QColor(item['color']), item['intensity'])
            if item.get('color2'):
                clip.color2 = QColor(item['color2'])
            clip.fade_in_duration = item.get('fade_in', 0)
            clip.fade_out_duration = item.get('fade_out', 0)
            clip.effect = item.get('effect')
            clip.effect_speed = item.get('effect_speed', 50)
            clip.effect_layers    = item.get('effect_layers', [])
            clip.effect_play_mode = item.get('effect_play_mode', 'loop')
            clip.effect_duration  = item.get('effect_duration', 0)
            clip.effect_name         = item.get('effect_name', '')
            clip.effect_type         = item.get('effect_type', '')
            clip.effect_target_groups = item.get('effect_target_groups', [])
            track.selected_clips.append(clip)
            count += 1

        for track in self.tracks:
            track.update()
        self.save_state()
        print(f"📌 {count} clip(s) colle(s) a {paste_time/1000:.1f}s")

    def save_state(self):
        """Sauvegarde l'etat actuel pour undo"""
        state = []
        for track in self.tracks:
            for clip in track.clips:
                clip_data = {
                    'track': track.name,
                    'start': clip.start_time,
                    'duration': clip.duration,
                    'color': clip.color.name(),
                    'color2': clip.color2.name() if clip.color2 else None,
                    'intensity': clip.intensity,
                    'fade_in': clip.fade_in_duration,
                    'fade_out': clip.fade_out_duration,
                    'effect': clip.effect,
                    'effect_speed': clip.effect_speed,
                    'effect_layers': getattr(clip, 'effect_layers', []),
                    'effect_play_mode': getattr(clip, 'effect_play_mode', 'loop'),
                    'effect_duration':  getattr(clip, 'effect_duration', 0),
                    'effect_name':         getattr(clip, 'effect_name', ''),
                    'effect_type':         getattr(clip, 'effect_type', ''),
                    'effect_target_groups': getattr(clip, 'effect_target_groups', []),
                }
                state.append(clip_data)

        # Tronquer l'historique si on a fait undo puis nouvelle action
        self.history = self.history[:self.history_index + 1]
        self.history.append(state)
        self.history_index += 1

        # Limiter la taille de l'historique
        if len(self.history) > 50:
            self.history.pop(0)
            self.history_index -= 1

        print(f"💾 Etat sauvegarde: {len(state)} clips, history_index={self.history_index}")

    def _restore_state(self, state):
        """Restaure un etat depuis l'historique"""
        for track in self.tracks:
            track.clips.clear()
            track.selected_clips.clear()

        for clip_data in state:
            track = self.track_map.get(clip_data.get('track'))
            if track:
                color = QColor(clip_data.get('color', '#ffffff'))
                clip = track.add_clip_direct(
                    clip_data.get('start', 0),
                    clip_data.get('duration', 1000),
                    color,
                    clip_data.get('intensity', 80)
                )
                if clip_data.get('color2'):
                    clip.color2 = QColor(clip_data['color2'])
                clip.fade_in_duration = clip_data.get('fade_in', 0)
                clip.fade_out_duration = clip_data.get('fade_out', 0)
                clip.effect = clip_data.get('effect')
                clip.effect_speed = clip_data.get('effect_speed', 50)
                clip.effect_layers    = clip_data.get('effect_layers', [])
                clip.effect_play_mode = clip_data.get('effect_play_mode', 'loop')
                clip.effect_duration  = clip_data.get('effect_duration', 0)
                clip.effect_name      = clip_data.get('effect_name', '')
                clip.effect_type      = clip_data.get('effect_type', '')

        for track in self.tracks:
            track.update()

    def undo(self):
        """Annuler la derniere action"""
        if len(self.history) == 0 or self.history_index <= 0:
            return

        self.history_index -= 1
        self._restore_state(self.history[self.history_index])
        print(f"↶ Undo effectue (index={self.history_index})")

    def redo(self):
        """Retablir la derniere action annulee"""
        if self.history_index >= len(self.history) - 1:
            return

        self.history_index += 1
        self._restore_state(self.history[self.history_index])
        print(f"↷ Redo effectue (index={self.history_index})")

    def toggle_cut_mode_from_menu(self):
        """Active/desactive le mode CUT depuis le menu"""
        self.cut_btn.setChecked(not self.cut_btn.isChecked())
        self.toggle_cut_mode()

    def apply_effect_to_selection(self, effect):
        """Applique un effet aux clips selectionnes (pistes A-F uniquement)"""
        selected = []
        for track in self.tracks:
            if not getattr(track, 'is_sequence_track', False):
                selected.extend(track.selected_clips)

        if not selected:
            QMessageBox.warning(self, tr("te_no_selection_title"),
                tr("te_no_selection_msg"))
            return

        # Résoudre les layers depuis builtin puis custom
        eff_layers = []
        eff_type = ''
        if effect:
            try:
                from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
                all_effects = BUILTIN_EFFECTS + _load_custom_effects()
                for _e in all_effects:
                    if _e.get('name') == effect:
                        eff_layers = [dict(l) for l in _e.get('layers', [])]
                        eff_type   = _e.get('type', '')
                        break
            except Exception:
                pass

        for clip in selected:
            clip.effect        = effect
            clip.effect_name   = effect or ''
            clip.effect_layers = eff_layers
            clip.effect_type   = eff_type
        for track in self.tracks:
            track.update()
        self.save_state()

    def apply_fade_in_to_selection(self):
        """Applique un fade in aux clips selectionnes"""
        selected = []
        for track in self.tracks:
            selected.extend(track.selected_clips)

        if not selected:
            QMessageBox.warning(self, tr("te_no_selection_title"),
                tr("te_no_selection_msg"))
            return

        for clip in selected:
            clip.fade_in_duration = 1000
        for track in self.tracks:
            track.update()
        self.save_state()

    def apply_fade_out_to_selection(self):
        """Applique un fade out aux clips selectionnes"""
        selected = []
        for track in self.tracks:
            selected.extend(track.selected_clips)

        if not selected:
            QMessageBox.warning(self, tr("te_no_selection_title"),
                tr("te_no_selection_msg"))
            return

        for clip in selected:
            clip.fade_out_duration = 1000
        for track in self.tracks:
            track.update()
        self.save_state()

    def remove_fades_from_selection(self):
        """Supprime les fades des clips selectionnes"""
        selected = []
        for track in self.tracks:
            selected.extend(track.selected_clips)

        if not selected:
            QMessageBox.warning(self, tr("te_no_selection_title"),
                tr("te_no_selection_msg"))
            return

        for clip in selected:
            clip.fade_in_duration = 0
            clip.fade_out_duration = 0
        for track in self.tracks:
            track.update()
        self.save_state()

    def toggle_cut_mode(self):
        """Active/desactive le mode CUT avec curseur visuel"""
        self.cut_mode = not self.cut_mode

        if self.cut_mode:
            # Curseur ciseaux sur toute la fenetre et les pistes
            self.setCursor(Qt.SplitHCursor)
            for track in self.tracks:
                track.setCursor(Qt.SplitHCursor)
            self.track_waveform.setCursor(Qt.SplitHCursor)
            print("✂️ Mode CUT active - Cliquez sur un clip pour le couper")
        else:
            # Restaurer curseur normal
            self.setCursor(Qt.ArrowCursor)
            for track in self.tracks:
                track.setCursor(Qt.ArrowCursor)
            self.track_waveform.setCursor(Qt.ArrowCursor)

    def clear_all_selections(self):
        """Deselectionne tous les clips sur toutes les pistes"""
        for track in self.tracks:
            track.selected_clips.clear()
            track.update()

    def start_rubber_band(self, pos, origin_track):
        """Demarre la selection rectangulaire multi-pistes"""
        self.rubber_band_active = True
        self.rubber_band_start = pos
        self.rubber_band_origin_track = origin_track
        self.rubber_band_rect = None
        self.clear_all_selections()

        # Afficher et redimensionner l'overlay
        self.rubber_band_overlay.setGeometry(self.tracks_scroll.viewport().rect())
        self.rubber_band_overlay.show()
        self.rubber_band_overlay.raise_()

    def update_rubber_band(self, current_pos):
        """Met a jour le rectangle de selection avec overlay visible"""
        if not self.rubber_band_active or not self.rubber_band_start:
            return

        # Calculer le rectangle dans les coordonnees du viewport
        viewport = self.tracks_scroll.viewport()
        start_in_viewport = viewport.mapFrom(self, self.rubber_band_start)
        current_in_viewport = viewport.mapFrom(self, current_pos)

        x1 = min(start_in_viewport.x(), current_in_viewport.x())
        y1 = min(start_in_viewport.y(), current_in_viewport.y())
        x2 = max(start_in_viewport.x(), current_in_viewport.x())
        y2 = max(start_in_viewport.y(), current_in_viewport.y())

        self.rubber_band_rect = QRect(x1, y1, x2 - x1, y2 - y1)

        # Mettre a jour l'overlay
        self.rubber_band_overlay.set_rect(self.rubber_band_rect)

        # Selectionner les clips dans le rectangle sur TOUTES les pistes
        scroll_offset = self.tracks_scroll.horizontalScrollBar().value()
        v_scroll_offset = self.tracks_scroll.verticalScrollBar().value()
        pixels_per_ms = 0.05 * self.current_zoom

        for track in self.tracks:
            # Position Y de la piste dans le conteneur
            track_y_in_container = track.mapTo(self.tracks_container, QPoint(0, 0)).y()
            # Position Y dans le viewport (avec scroll)
            track_y_in_viewport = track_y_in_container - v_scroll_offset

            track.selected_clips.clear()

            for clip in track.clips:
                clip_x = 145 + int(clip.start_time * pixels_per_ms) - scroll_offset
                clip_width = int(clip.duration * pixels_per_ms)

                # Rectangle du clip dans le viewport
                clip_rect = QRect(clip_x, track_y_in_viewport + 10, clip_width, 40)

                if self.rubber_band_rect.intersects(clip_rect):
                    track.selected_clips.append(clip)

            track.update()

    def end_rubber_band(self):
        """Termine la selection rectangulaire"""
        self.rubber_band_active = False
        self.rubber_band_start = None
        self.rubber_band_rect = None
        self.rubber_band_origin_track = None

        # Cacher l'overlay
        self.rubber_band_overlay.clear()
        self.rubber_band_overlay.hide()

        # Compter les clips selectionnes
        total = sum(len(track.selected_clips) for track in self.tracks)
        if total > 0:
            print(f"📦 {total} clip(s) selectionne(s) sur plusieurs pistes")

    def mousePressEvent(self, event):
        """Gere le clic pour demarrer le rubber band si dans la zone des pistes"""
        # Verifier si le clic est dans la zone des pistes (viewport du scroll)
        viewport = self.tracks_scroll.viewport()
        pos_in_viewport = viewport.mapFrom(self, event.pos())

        if viewport.rect().contains(pos_in_viewport):
            # Verifier qu'on est dans la zone timeline (pas sur les labels)
            if pos_in_viewport.x() > 145:
                self.rubber_band_active = True
                self.rubber_band_start = event.pos()
                self.clear_all_selections()

                # Preparer l'overlay
                self.rubber_band_overlay.setGeometry(viewport.rect())
                self.rubber_band_overlay.show()
                self.rubber_band_overlay.raise_()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Gere le deplacement pour le rubber band"""
        if self.rubber_band_active and self.rubber_band_start:
            self.update_rubber_band(event.pos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Termine le rubber band"""
        if self.rubber_band_active:
            self.end_rubber_band()
        super().mouseReleaseEvent(event)

    def edit_effect_speed_selection(self):
        """Ouvre un dialog pour regler la vitesse des effets sur les clips selectionnes (pistes A-F uniquement)"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton
        selected = []
        for track in self.tracks:
            if not getattr(track, 'is_sequence_track', False):
                selected.extend(track.selected_clips)

        if not selected:
            QMessageBox.warning(self, tr("te_no_selection_title"),
                tr("te_no_selection_msg"))
            return

        current_speed = selected[0].effect_speed if selected else 50

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("te_effect_speed_title"))
        dialog.setFixedSize(360, 210)
        dialog.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel { color: white; border: none; }
            QPushButton {
                background: #cccccc; color: black;
                border: 1px solid #999; border-radius: 6px;
                padding: 10px 20px; font-weight: bold;
            }
            QPushButton:hover { background: #00d4ff; }
            QSlider::groove:horizontal { background: #3a3a3a; height: 8px; border-radius: 4px; }
            QSlider::handle:horizontal {
                background: #00d4ff; width: 18px; height: 18px;
                margin: -5px 0; border-radius: 9px;
            }
            QSlider::sub-page:horizontal { background: #00d4ff; border-radius: 4px; }
        """)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(30, 25, 30, 20)
        layout.setSpacing(12)

        value_label = QLabel(tr("te_speed_value", v=current_speed))
        value_label.setStyleSheet("color: white; font-size: 26px; font-weight: bold;")
        value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(value_label)

        lbl_row = QHBoxLayout()
        lbl_slow = QLabel(tr("te_speed_slow"))
        lbl_slow.setStyleSheet("color: #888; font-size: 11px;")
        lbl_fast = QLabel(tr("te_speed_fast"))
        lbl_fast.setStyleSheet("color: #888; font-size: 11px;")
        lbl_row.addWidget(lbl_slow)
        lbl_row.addStretch()
        lbl_row.addWidget(lbl_fast)
        layout.addLayout(lbl_row)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(current_speed)
        slider.valueChanged.connect(lambda v: value_label.setText(tr("te_speed_value", v=v)))
        layout.addWidget(slider)

        btn_layout = QHBoxLayout()
        cancel = QPushButton(tr("btn_cancel"))
        cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel)
        ok = QPushButton("OK")
        ok.clicked.connect(dialog.accept)
        ok.setStyleSheet("background: #00d4ff; color: black; font-weight: bold; padding: 10px 20px; border-radius: 6px;")
        btn_layout.addWidget(ok)
        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.Accepted:
            for clip in selected:
                clip.effect_speed = slider.value()
            for track in self.tracks:
                track.update()
            self.save_state()

    def open_effect_editor(self):
        """Ouvre l'editeur d'effets par couches sur les clips selectionnes (pistes A-F uniquement)"""
        selected = []
        for track in self.tracks:
            if not getattr(track, 'is_sequence_track', False):
                selected.extend(track.selected_clips)

        if not selected:
            QMessageBox.warning(self, tr("te_no_selection_title"),
                tr("te_no_selection_msg"))
            return

        dlg = EffectEditorDialog(selected, self.main_window, parent=self)
        if dlg.exec() == EffectEditorDialog.Accepted:
            for track in self.tracks:
                track.update()
            self.save_state()

    def _autosave_lrec(self, all_clips):
        """Sauvegarde automatique du .lrec à côté du fichier média."""
        import json as _json
        from pathlib import Path as _Path
        media = getattr(self, '_original_media_path', None) or self.media_path
        if not media:
            return
        lrec_path = str(_Path(media).parent / (_Path(media).stem + '_reclumiere.lrec'))
        data = {
            'version': 1,
            'media_name': self.media_name,
            'duration': self.media_duration,
            'clips': all_clips,
        }
        try:
            with open(lrec_path, 'w', encoding='utf-8') as f:
                _json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # silencieux — ne pas bloquer la sauvegarde principale

    def _is_dirty(self):
        """Retourne True si des modifications n'ont pas été sauvegardées."""
        return self.history_index != self._saved_history_index

    def close_editor(self):
        """Ferme l'éditeur — alerte si modifications non sauvegardées."""
        if self._is_dirty():
            # Compter les clips pour donner du contexte
            total_clips = sum(len(t.clips) for t in self.tracks)
            msg = QMessageBox(self)
            msg.setWindowTitle(tr("te_unsaved_title"))
            msg.setText(tr("te_unsaved_msg", n=total_clips))
            msg.setIcon(QMessageBox.Warning)
            btn_save    = msg.addButton(tr("te_btn_save_icon"), QMessageBox.AcceptRole)
            btn_discard = msg.addButton(tr("te_btn_close_no_save"), QMessageBox.DestructiveRole)
            msg.setStyleSheet("""
                QMessageBox { background: #1a1a1a; color: #cccccc; }
                QLabel { color: #cccccc; }
                QPushButton {
                    background: #2a2a2a; color: #cccccc;
                    border: 1px solid #444; border-radius: 4px;
                    padding: 6px 14px; min-width: 80px;
                }
                QPushButton:hover { background: #333; color: white; }
            """)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == btn_save:
                self.save_sequence()
                return  # save_sequence appellera close_editor après confirmation
            if clicked != btn_discard:
                return  # fenêtre fermée sans choix → on annule

        self.playback_timer.stop()
        self.preview_player.stop()
        # Deconnecter tous les signaux du player principal pour eviter
        # que le timer de preview continue de s'activer apres fermeture
        try:
            self.main_window.player.playbackStateChanged.disconnect(self._on_main_player_state_changed)
        except Exception:
            pass
        self.reject()
