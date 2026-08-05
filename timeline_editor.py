"""
Editeur de timeline lumiere - LightTimelineEditor
"""
import os
import copy
import json
import hashlib
import random
import time
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

from light_timeline import (LightTrack, LightClip, PalettePanel, LibraryPanel,
                            xfade_resolve, xfade_obj_get as _clip_obj_get,
                            scope_layers_to_groups,
                            REC_MEM_COL_START, REC_MEM_COL_END)
from core import media_icon, create_icon, apply_special_block, ComboSansMolette
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

    _saved_geometry = None  # mémorise la taille entre ouvertures

    def __init__(self, main_window, media_row):
        super().__init__(main_window,
            Qt.Dialog | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
            | Qt.WindowCloseButtonHint | Qt.WindowMaximizeButtonHint)
        self.main_window = main_window
        self.media_row = media_row

        # L'aperçu REC Lumière devient le SEUL pilote de l'effet (il appelle
        # update_effect() lui-même à chaque frame du playhead). On le signale à
        # send_dmx_update pour qu'il NE re-pilote PAS l'effet en parallèle
        # (timer DMX 25 ms) : sinon un effet à compteur avance à 2 cadences
        # déphasées → strobe dans l'aperçu (OK en restitution car timeline_active).
        self.main_window._rec_preview_active = True

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


        # Curseur de lecture
        if main_window.player.playbackState() == QMediaPlayer.PlayingState:
            self.playback_position = main_window.player.position()
        else:
            self.playback_position = 0
        self._prev_playback_position = self.playback_position

        self._seq_clip_active  = None   # clip de séquence actuellement actif (pour effets)
        self._eff_clips_active = {}     # {track_name: clip} — clips d'effet actifs par piste
        self._pos_clip_active  = None   # clip de position lyre actuellement actif

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

        # Mode paint
        self.paint_mode = False
        self.paint_brush = None

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

        # ── Haut : Plan de Feu + aperçu vidéo côte à côte ────────────────
        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.setHandleWidth(4)
        top_splitter.setStyleSheet(_splitter_ss)
        self._top_splitter = top_splitter

        try:
            pdf = PlanDeFeu(self.main_window.projectors, main_window=self.main_window,
                            show_toolbar=False, interactive=True)
            pdf._menu_at_cursor = True   # menu contextuel au curseur (plan embarqué)
            pdf._allow_quick_effects = False   # pas d'effets rapides en REC Lumière
            pdf.setStyleSheet("border: none; background: #0d0d0d;")
            top_splitter.addWidget(pdf)
            self._live_pdf = pdf
            self._pdf_window = pdf
        except Exception:
            _ph = QWidget(); _ph.setStyleSheet("background: #0d0d0d;")
            top_splitter.addWidget(_ph)

        # Conteneur aperçu vidéo (affiché seulement si media vidéo)
        self._video_preview_container = QWidget()
        self._video_preview_container.setStyleSheet("background: #000;")
        self._video_preview_container.setMinimumWidth(120)
        self._video_preview_container.hide()
        _vpc_layout = QVBoxLayout(self._video_preview_container)
        _vpc_layout.setContentsMargins(0, 0, 0, 0)
        top_splitter.addWidget(self._video_preview_container)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 0)

        left_splitter.addWidget(top_splitter)

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
        self._has_audio_track = bool(show_audio)   # utilisé par reanalyze_audio()

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

        # Intercepter les wheel events sur le viewport pour forcer scroll horizontal
        self.tracks_scroll.viewport().installEventFilter(self)
        self.tracks_scroll.installEventFilter(self)

        # Zoom par defaut
        self.current_zoom = 1.0

        # Focus clavier par défaut dès l'ouverture
        self.setFocusPolicy(Qt.StrongFocus)
        QTimer.singleShot(0, self.setFocus)

        self.preview_player = None
        self.preview_audio = None
        self.is_video_file = False
        self.preview_video_widget = None
        # Lecture d'une pause temporisée (pas de média) : horloge manuelle.
        self._tempo_playing    = False
        self._tempo_start_wall = 0.0
        self._tempo_start_pos  = 0
        QTimer.singleShot(0, self.setup_audio_player)

        # ── État du poussoir REC ───────────────────────────────────────────────
        # REC est cliquable dès que rien ne joue. Au clic, il capture l'état
        # AFFICHÉ du rig (peu importe la source : plan 2D OU bloc de la timeline
        # sous le curseur). Le message « rien n'est envoyé » n'apparaît que si le
        # rig est réellement tout noir. Un petit timer synchronise juste l'état
        # du bouton avec la lecture (grisé pendant qu'on joue).
        self._update_rec_btn_state()
        self._rec_watch_timer = QTimer(self)
        self._rec_watch_timer.setInterval(200)
        self._rec_watch_timer.timeout.connect(self._update_rec_btn_state)
        self._rec_watch_timer.start()

        # Raccourci Espace global (capturé au niveau fenetre, independant du focus)
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play_pause)

        # Échap global : sort du mode « bloquer » (peinture) / coupe même si le
        # focus est sur la bibliothèque après un clic droit. WindowShortcut =
        # capté partout dans la fenêtre.
        _esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        _esc.setContext(Qt.WindowShortcut)
        _esc.activated.connect(self._on_escape)

        # ── Instantané d'annulation ──────────────────────────────────────────
        # Les éditions inline (fin de redimensionnement, fades, vitesse d'effet,
        # fondu enchaîné…) écrivent DIRECTEMENT dans seq.sequences via
        # _save_sequence_no_close, pour que la restitution suive sans passer par
        # Sauvegarder. Conséquence : « Fermer sans sauvegarder » n'avait rien à
        # restaurer et la modification survivait. On garde donc l'état d'avant.
        # La waveform est gardée par référence : ce n'est pas de l'édition, et
        # elle est de toute façon recalculable depuis le cache fichier.
        _src = self.main_window.seq.sequences.get(self.media_row)
        self._orig_sequence = None if _src is None else {
            k: (v if k == 'waveform' else copy.deepcopy(v)) for k, v in _src.items()
        }
        # L'éditeur est modal : rien d'autre ne peut salir le show entre-temps,
        # donc ce drapeau reflète bien l'état d'avant l'ouverture.
        self._orig_is_dirty = getattr(self.main_window.seq, 'is_dirty', False)

        # Charger sequence existante
        self.load_existing_sequence()

        # Forcer affichage du curseur
        QTimer.singleShot(100, lambda: self.ruler.update())

        # Generer la forme d'onde (sauf pour les images et les pauses)
        is_image = self.media_path and media_icon(self.media_path) == "image"
        if self.media_path and os.path.exists(self.media_path) and not is_image and not self.is_tempo:
            QTimer.singleShot(50, self._load_waveform_async)

        # Ouverture en GRAND, mais bornée à la zone utile (au-dessus de la barre
        # des tâches) pour que la barre de transport (bouton Play) reste visible.
        _scr = self.screen() or QApplication.primaryScreen()
        _avail = _scr.availableGeometry() if _scr else None
        if LightTimelineEditor._saved_geometry:
            self.restoreGeometry(LightTimelineEditor._saved_geometry)
            # Si la taille mémorisée déborde sous la barre des tâches → on la ramène.
            if _avail and not self.isMaximized():
                g = self.frameGeometry()
                if (g.height() > _avail.height() or g.bottom() > _avail.bottom()
                        or g.top() < _avail.top()):
                    self.resize(min(self.width(), _avail.width() - 40),
                                _avail.height() - 60)
                    self.move(_avail.left() + 20, _avail.top() + 20)
        elif _avail:
            # Première ouverture : grande fenêtre couvrant la zone utile, avec une
            # marge en bas pour ne jamais masquer le Play sous la barre des tâches.
            self.resize(_avail.width() - 40, _avail.height() - 60)
            self.move(_avail.left() + 20, _avail.top() + 20)

    def closeEvent(self, event):
        LightTimelineEditor._saved_geometry = self.saveGeometry()
        # Arrêter le timer de preview
        if hasattr(self, 'playback_timer'):
            self.playback_timer.stop()
        # Arrêter le timer de surveillance REC
        if hasattr(self, '_rec_watch_timer'):
            self._rec_watch_timer.stop()
        # L'aperçu ne pilote plus l'effet : rendre la main à send_dmx_update.
        self.main_window._rec_preview_active = False
        # Blackout : remettre tous les projecteurs à niveau 0 au retour
        try:
            # Couper un effet éventuellement laissé actif par l'aperçu (sinon il
            # continue de tourner dans la fenêtre principale après fermeture).
            if getattr(self.main_window, 'active_effect', None):
                self.main_window.active_effect = None
                self.main_window.active_effect_config = {}
                if hasattr(self.main_window, 'stop_effect'):
                    self.main_window.stop_effect()
            for proj in self.main_window.projectors:
                proj.level = 0
            if hasattr(self.main_window, 'dmx'):
                self.main_window.dmx.blackout()
            # Ne pas laisser le suivi clip→effet actif en mode live (ids périmés)
            self.main_window._fx_clip_ids = None
        except Exception:
            pass
        super().closeEvent(event)

    def _create_tracks_from_fixtures(self, projectors, tracks_layout):
        """Genere les pistes de la timeline depuis la liste de fixtures"""
        GROUP_DISPLAY = getattr(self.main_window, 'GROUP_DISPLAY', {
            "face":     "A", "lat":     "B", "contre":  "C",
            "douche1":  "D", "douche2": "E", "douche3": "F",
            "groupe_g": "G", "groupe_h": "H",
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
        self._tracks_layout = tracks_layout

        # ── Piste Effet (tout en haut — priorité absolue sur les groupes) ─
        eff_track = LightTrack("Effet", self.media_duration, self, "#cc44ff")
        eff_track.is_effect_track = True
        eff_track.setMinimumHeight(50)
        self.tracks.append(eff_track)
        self.track_map["Effet"] = eff_track
        self._effect_tracks = [eff_track]
        tracks_layout.addWidget(eff_track)

        # ── Bouton + Piste Effet (max 4) ──────────────────────────────────
        self._add_eff_btn_row = QWidget()
        self._add_eff_btn_row.setFixedHeight(24)
        self._add_eff_btn_row.setStyleSheet("background: #0a0a0a;")
        _aer_lay = QHBoxLayout(self._add_eff_btn_row)
        _aer_lay.setContentsMargins(11, 2, 11, 2)
        _aer_lay.setSpacing(0)
        self._add_eff_btn = QPushButton(tr("tle_add_effect"))
        self._add_eff_btn.setFixedHeight(20)
        self._add_eff_btn.setCursor(Qt.PointingHandCursor)
        self._add_eff_btn.setStyleSheet(self._add_track_btn_style("#cc44ff"))
        self._add_eff_btn.clicked.connect(self._add_effect_track)
        _aer_lay.addWidget(self._add_eff_btn)
        _aer_lay.addStretch()
        tracks_layout.addWidget(self._add_eff_btn_row)
        # Gardé pour épingler le bouton au bord gauche du viewport (on_scroll_changed).
        self._add_eff_btn_lay = _aer_lay

        # ── Piste Séquence (avant les groupes) ────────────────────────────
        seq_track = LightTrack("Séquence", self.media_duration, self, "#aa77ff")
        seq_track.is_sequence_track = True
        seq_track.setMinimumHeight(50)
        self.tracks.append(seq_track)
        self.track_map["Séquence"] = seq_track
        self._sequence_tracks = [seq_track]
        tracks_layout.addWidget(seq_track)

        # ── Bouton + Piste Séquence (superposition HTP de plusieurs mémoires) ─
        self._add_seq_btn_row = QWidget()
        self._add_seq_btn_row.setFixedHeight(24)
        self._add_seq_btn_row.setStyleSheet("background: #0a0a0a;")
        _asr_lay = QHBoxLayout(self._add_seq_btn_row)
        _asr_lay.setContentsMargins(11, 2, 11, 2)
        _asr_lay.setSpacing(0)
        self._add_seq_btn = QPushButton(tr("te2_add_sequence"))
        self._add_seq_btn.setFixedHeight(20)
        self._add_seq_btn.setCursor(Qt.PointingHandCursor)
        self._add_seq_btn.setStyleSheet(self._add_track_btn_style("#aa77ff"))
        self._add_seq_btn.setToolTip(
            tr("tle_add_seq_hint"))
        self._add_seq_btn.clicked.connect(self._add_sequence_track)
        _asr_lay.addWidget(self._add_seq_btn)
        _asr_lay.addStretch()
        tracks_layout.addWidget(self._add_seq_btn_row)
        self._add_seq_btn_lay = _asr_lay

        # ── Piste Position Lyre (si au moins une lyre dans le patch) ──────────
        has_lyres = any(getattr(p, 'fixture_type', '') == 'Moving Head' for p in projectors)
        if has_lyres:
            pos_track = LightTrack("Position", self.media_duration, self, "#2255ee")
            pos_track.is_position_track = True
            pos_track.setMinimumHeight(50)
            self.tracks.append(pos_track)
            self.track_map["Position"] = pos_track
            tracks_layout.addWidget(pos_track)

        # ── Piste Gobo (si au moins une fixture a une roue de gobos) ──────────
        has_gobo = any('Gobo1' in (getattr(p, 'dmx_profile', None) or [])
                       for p in projectors)
        if has_gobo:
            gobo_track = LightTrack("Gobo", self.media_duration, self, "#e6c060")
            gobo_track.is_gobo_track = True
            gobo_track.setMinimumHeight(50)
            self.tracks.append(gobo_track)
            self.track_map["Gobo"] = gobo_track
            tracks_layout.addWidget(gobo_track)

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

    @staticmethod
    def _add_track_btn_style(accent):
        """
        Boutons « + Piste » : discrets. Gris neutre au repos, l'accent
        n'apparaît qu'au survol — beaucoup moins fluo qu'une pastille colorée.
        """
        return f"""
            QPushButton {{
                background: transparent; color: #6a6a72;
                border: 1px solid #2a2a2e; border-radius: 6px;
                font-size: 11px; font-weight: 500; padding: 3px 14px;
            }}
            QPushButton:hover {{ background: {accent}14; color: {accent};
                                 border-color: {accent}55; }}
            QPushButton:disabled {{ color: #333; border-color: #1e1e1e; }}
        """

    @staticmethod
    def _remove_track_btn_style(accent):
        """Style commun du × de suppression d'une piste supplémentaire."""
        return f"""
            QPushButton {{
                background: transparent; color: #666;
                border: none; border-radius: 8px;
                font-size: 13px; font-weight: bold; padding: 0;
            }}
            QPushButton:hover {{ background: {accent}; color: #000; }}
        """

    _MAX_EFFECT_TRACKS = 8

    def _add_effect_track(self):
        """Ajoute une piste Effet supplémentaire (max _MAX_EFFECT_TRACKS)."""
        if len(self._effect_tracks) >= self._MAX_EFFECT_TRACKS:
            return
        existing_names = {t.name for t in self._effect_tracks}
        n = 2
        while f"Effet {n}" in existing_names:
            n += 1
        self._add_effect_track_named(f"Effet {n}")

    def _add_effect_track_named(self, name):
        """Crée une piste Effet avec le nom donné et l'insère dans le layout."""
        if len(self._effect_tracks) >= self._MAX_EFFECT_TRACKS:
            return
        new_track = LightTrack(name, self.media_duration, self, "#cc44ff")
        new_track.is_effect_track = True
        new_track.setMinimumHeight(50)
        # Insérer dans le layout juste avant le bouton +
        idx = self._tracks_layout.indexOf(self._add_eff_btn_row)
        self._tracks_layout.insertWidget(idx, new_track)
        # Insérer dans self.tracks juste après le dernier effet track
        last_idx = self.tracks.index(self._effect_tracks[-1])
        self.tracks.insert(last_idx + 1, new_track)
        self.track_map[name] = new_track
        self._effect_tracks.append(new_track)
        # Bouton × de suppression
        rm_btn = QPushButton("×", new_track)
        rm_btn.setFixedSize(16, 16)
        rm_btn.move(118, 2)
        rm_btn.setCursor(Qt.PointingHandCursor)
        rm_btn.setToolTip(tr("te2_del_track"))
        rm_btn.setStyleSheet(self._remove_track_btn_style("#cc44ff"))
        rm_btn.clicked.connect(lambda checked=False, t=new_track: self._remove_effect_track(t))
        rm_btn.show()
        if len(self._effect_tracks) >= self._MAX_EFFECT_TRACKS:
            self._add_eff_btn.setEnabled(False)
        if self.track_waveform.waveform_data:
            new_track.waveform_data = self.track_waveform.waveform_data
        new_track.update()

    def _remove_effect_track(self, track):
        """Supprime une piste Effet supplémentaire (la première ne peut pas être supprimée)."""
        if track not in self._effect_tracks or self._effect_tracks.index(track) == 0:
            return
        if track.name in self._eff_clips_active:
            del self._eff_clips_active[track.name]
        self._effect_tracks.remove(track)
        self.track_map.pop(track.name, None)
        if track in self.tracks:
            self.tracks.remove(track)
        self._tracks_layout.removeWidget(track)
        track.deleteLater()
        self._add_eff_btn.setEnabled(True)

    # ── REC séquence (poussoir) ────────────────────────────────────────────────

    def _rec_capture_block(self):
        """Poussoir REC : capture le look live (composé sur le plan 2D) en une
        mémoire REC, l'insère comme bloc dans la piste Séquence à la position du
        curseur, puis avance le curseur d'un bloc (durée BLOC)."""
        mw = self.main_window
        seq_track = self.track_map.get("Séquence")
        if seq_track is None or mw is None:
            return
        # Jamais pendant la lecture (le bouton est déjà grisé, garde défensive).
        if self._is_playing():
            return

        # ── Rien envoyé au plan 2D → guider l'utilisateur (proposer un noir) ────
        # Le rig est-il allumé ? (état affiché, source indifférente : plan 2D OU
        # bloc de timeline sous le curseur). Sinon → proposer un blackout.
        force_black = False
        if not self._rig_is_lit():
            box = QMessageBox(self)
            box.setWindowTitle(tr("te2_rec_sequence"))
            box.setIcon(QMessageBox.Information)
            box.setText(tr("te2_nothing_sent"))
            box.setInformativeText(
                tr("tle_rec_dialog_hint"))
            box.setStyleSheet("background:#1e1e1e; color:white;")
            b_black = box.addButton(tr("tle_rec_blackout"), QMessageBox.AcceptRole)
            box.addButton(tr("tle_cancel"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not b_black:
                return
            # On est ici car le rig est déjà tout noir (_rig_is_lit() faux) → le
            # snapshot capturera bien un blackout, rien à forcer.
            force_black = True

        t0  = max(0.0, float(self.playback_position))
        dur = seq_track._default_block_dur_ms()

        # ── Écrasement : blocs de séquence chevauchant [t0, t1) ────────────────
        # Coupe « rasoir » : on conserve la 1ère partie du bloc (avant le curseur)
        # et sa queue éventuelle (après le nouveau bloc) ; seul le milieu couvert
        # par la capture est remplacé.
        t1 = t0 + dur
        overlap = [c for c in seq_track.clips
                   if c.start_time < t1 and c.start_time + c.duration > t0]
        if overlap:
            ret = QMessageBox.question(
                self, tr("tle_rec_seq"),
                tr("tle_f_overlap", a0=len(overlap)),
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if ret != QMessageBox.Yes:
                return
            for c in list(overlap):
                a = c.start_time
                b = c.start_time + c.duration
                keep_left  = a < t0 - 1     # tolérance 1 ms
                keep_right = b > t1 + 1
                if keep_left and keep_right:
                    # Le nouveau bloc coupe c en deux → tête tronquée + queue clonée.
                    c.duration = t0 - a
                    tail = seq_track._clone_clip(c, seq_track)
                    tail.start_time = t1
                    tail.duration   = b - t1
                    seq_track.clips.append(tail)
                elif keep_left:
                    c.duration = t0 - a          # garder la 1ère partie
                elif keep_right:
                    c.start_time = t1            # garder la queue
                    c.duration   = b - t1
                else:
                    if c in seq_track.clips:
                        seq_track.clips.remove(c)
                    if c in getattr(seq_track, 'selected_clips', []):
                        seq_track.selected_clips.remove(c)

        # ── Allouer un slot mémoire REC (colonnes réservées, hors AKAI) ────────
        slot = self._alloc_rec_memory_slot()
        if slot is None:
            QMessageBox.warning(
                self, tr("tle_rec_seq"),
                tr("tle_no_rec_slot"))
            return
        col, row = slot
        name = self._next_rec_name()

        # ── Snapshot du look courant (couleur + lyres + canaux bruts/strobe) ───
        try:
            snap = mw._build_snapshot()
        except Exception:
            snap = {"projectors": [], "effect": {}, "duration": 0}
        snap["label"] = "Cue 1"
        mw.memories[col][row] = {"cues": [snap], "loop": True, "name": name, "_rec": True}
        try:
            mw._save_akai_config_auto()
        except Exception:
            pass

        # ── Bloc dans la piste Séquence, calé exactement au curseur ────────────
        # Couleur dominante calculée sur le cue (les projecteurs sont imbriqués
        # dans cues[0], pas au niveau haut de la mémoire).
        color = QColor("#0a0a0a") if force_black \
            else PalettePanel._dominant_color(snap, mw, col, row)
        clip = seq_track.add_clip_direct(t0, dur, color, 100)
        clip.memory_ref   = (col, row)
        clip.memory_label = name
        seq_track.update()

        # ── Rafraîchir la biblio (la mémoire REC apparaît dans la section REC) ─
        if getattr(self, '_library', None):
            try:
                self._library.refresh()
            except Exception:
                pass

        if hasattr(self, 'save_state'):
            self.save_state()

        # ── Avancer le curseur d'un bloc ───────────────────────────────────────
        self._advance_playhead(dur)

    def _rec_clear(self):
        """CLEAR : efface la compo MANUELLE envoyée au plan 2D, mais CONSERVE ce
        que la timeline pilote au curseur. On ré-applique l'état timeline à la
        position (reset complet des projos puis application des seuls clips actifs
        → pousse le DMX + rafraîchit le plan). S'il n'y a rien sur la timeline au
        curseur, ça revient à un blackout."""
        try:
            self._apply_preview_to_projectors(self.playback_position)
        except Exception:
            pass

    def _mem_col_mapped_anywhere(self, col):
        """Vrai si cette colonne mémoire est mappée à un fader AKAI (dans n'importe
        quelle page de layout ou le fader_map courant) → à éviter pour les REC."""
        mw = self.main_window
        pages = getattr(mw, '_bank_pages', None) or []
        for page in pages:
            for s in (page or []):
                if isinstance(s, dict) and s.get('type') == 'memory' and s.get('mem_col') == col:
                    return True
        for s in (getattr(mw, '_fader_map', None) or []):
            if isinstance(s, dict) and s.get('type') == 'memory' and s.get('mem_col') == col:
                return True
        return False

    def _alloc_rec_memory_slot(self):
        """Premier slot libre dans la plage réservée au REC, en sautant les
        colonnes mappées sur l'AKAI (pour rester invisible sur le contrôleur)."""
        mems = getattr(self.main_window, 'memories', None)
        if not mems:
            return None
        for col in range(REC_MEM_COL_START, REC_MEM_COL_END + 1):
            if col >= len(mems):
                break
            if self._mem_col_mapped_anywhere(col):
                continue
            for row in range(len(mems[col])):
                if mems[col][row] is None:
                    return (col, row)
        return None

    def _next_rec_name(self):
        """Nom auto « REC n » (n = plus grand indice « REC n » existant + 1).
        Compte TOUTES les mémoires nommées REC (taguées ou anciennes) pour ne
        jamais réutiliser un numéro."""
        import re
        mems = getattr(self.main_window, 'memories', None) or []
        mx = 0
        for col_mems in mems:
            for mem in (col_mems or []):
                if isinstance(mem, dict):
                    m = re.match(r'REC\s+(\d+)', mem.get('name', '') or '')
                    if m:
                        mx = max(mx, int(m.group(1)))
        return f"REC {mx + 1}"

    def _advance_playhead(self, delta_ms):
        """Avance le curseur de delta_ms (borné à la durée du média) et rafraîchit."""
        new_pos = min(self.playback_position + delta_ms, self.media_duration)
        self.playback_position = new_pos
        self._prev_playback_position = new_pos
        if self.preview_player is not None:
            try:
                self.preview_player.setPosition(int(new_pos))
            except Exception:
                pass
        pos_sec = int(new_pos / 1000)
        self._playhead_time_str = f"{pos_sec // 60}:{pos_sec % 60:02d}"
        self.ruler.update()
        for track in self.tracks:
            track.update()
        self.track_waveform.update()
        self.ensure_playhead_visible()

    # ── Armement du poussoir REC (guard lecture) ───────────────────────────────

    def _is_playing(self):
        """Vrai si la preview, le player principal, OU une pause temporisée jouent."""
        if getattr(self, '_tempo_playing', False):
            return True
        if self.preview_player is not None and \
                self.preview_player.playbackState() == QMediaPlayer.PlayingState:
            return True
        try:
            return self.main_window.player.playbackState() == QMediaPlayer.PlayingState
        except Exception:
            return False

    def _rig_is_lit(self):
        """Vrai si au moins un projecteur est allumé (état actuellement affiché,
        quelle qu'en soit la source : plan 2D ou bloc de timeline sous le curseur)."""
        try:
            return any(getattr(p, 'level', 0) > 0 for p in self.main_window.projectors)
        except Exception:
            return False

    def _update_rec_btn_state(self):
        """REC cliquable à l'arrêt (grisé seulement pendant la lecture)."""
        if not hasattr(self, '_rec_btn'):
            return
        self._rec_btn.setEnabled(not self._is_playing())

    _MAX_SEQUENCE_TRACKS = 8

    def _add_sequence_track(self):
        """Ajoute une piste Séquence supplémentaire (superposition HTP)."""
        if len(self._sequence_tracks) >= self._MAX_SEQUENCE_TRACKS:
            return
        existing = {t.name for t in self._sequence_tracks}
        n = 2
        while f"Séquence {n}" in existing:
            n += 1
        self._add_sequence_track_named(f"Séquence {n}")

    def _add_sequence_track_named(self, name):
        """Crée une piste Séquence et l'insère juste avant le bouton +."""
        if len(self._sequence_tracks) >= self._MAX_SEQUENCE_TRACKS:
            return
        new_track = LightTrack(name, self.media_duration, self, "#aa77ff")
        new_track.is_sequence_track = True
        new_track.setMinimumHeight(50)
        idx = self._tracks_layout.indexOf(self._add_seq_btn_row)
        self._tracks_layout.insertWidget(idx, new_track)
        last_idx = self.tracks.index(self._sequence_tracks[-1])
        self.tracks.insert(last_idx + 1, new_track)
        self.track_map[name] = new_track
        self._sequence_tracks.append(new_track)
        rm_btn = QPushButton("×", new_track)
        rm_btn.setFixedSize(16, 16)
        rm_btn.move(118, 2)
        rm_btn.setCursor(Qt.PointingHandCursor)
        rm_btn.setToolTip(tr("te2_del_track"))
        rm_btn.setStyleSheet(self._remove_track_btn_style("#aa77ff"))
        rm_btn.clicked.connect(lambda checked=False, t=new_track: self._remove_sequence_track(t))
        rm_btn.show()
        if len(self._sequence_tracks) >= self._MAX_SEQUENCE_TRACKS:
            self._add_seq_btn.setEnabled(False)
        if self.track_waveform.waveform_data:
            new_track.waveform_data = self.track_waveform.waveform_data
        new_track.update()

    def _remove_sequence_track(self, track):
        """Supprime une piste Séquence supplémentaire (la première reste)."""
        if track not in self._sequence_tracks or self._sequence_tracks.index(track) == 0:
            return
        self._sequence_tracks.remove(track)
        self.track_map.pop(track.name, None)
        if track in self.tracks:
            self.tracks.remove(track)
        self._tracks_layout.removeWidget(track)
        track.deleteLater()
        self._add_seq_btn.setEnabled(True)

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

        # Bloquer Sauvegarder et Fermer pendant l'extraction
        if hasattr(self, 'save_btn'):
            self.save_btn.setEnabled(False)
        if hasattr(self, 'close_btn'):
            self.close_btn.setEnabled(False)

        def _unlock_buttons():
            if hasattr(self, 'save_btn'):
                self.save_btn.setEnabled(True)
            if hasattr(self, 'close_btn'):
                self.close_btn.setEnabled(True)

        loading = QDialog(self)
        loading.setWindowTitle(tr("te_loading_title"))
        loading.setFixedSize(380, 248)
        loading.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        loading.setStyleSheet("""
            QDialog { background: #1a1a1a; border: 2px solid #00d4ff; border-radius: 10px; }
            QLabel { color: white; border: none; }
            QProgressBar { background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 5px; text-align: center; color: white; }
            QProgressBar::chunk { background: #00d4ff; border-radius: 4px; }
        """)
        lay = QVBoxLayout(loading)
        lay.setContentsMargins(20, 15, 20, 15)
        lay.setSpacing(8)
        is_vid = hasattr(self, 'is_video_file') and self.is_video_file
        status = QLabel(tr("te_extract_pct", pct=0) if is_vid else tr("te_analyse_pct", pct=0))
        status.setAlignment(Qt.AlignCenter)
        status.setStyleSheet("font-size: 14px; font-weight: bold;")
        lay.addWidget(status)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        lay.addWidget(bar)

        # Estimation du temps restant (mise a jour fluide, meme entre 2 callbacks)
        remaining = QLabel("")
        remaining.setAlignment(Qt.AlignCenter)
        remaining.setStyleSheet("font-size: 12px; color: #00d4ff; border: none;")
        lay.addWidget(remaining)

        # Info : le résultat est mis en cache → la prochaine ouverture sera instantanée.
        # (Cette branche ne s'exécute qu'au 1er passage — cache miss — donc toujours vrai ici.)
        next_hint = QLabel(tr("te_next_instant"))
        next_hint.setAlignment(Qt.AlignCenter)
        next_hint.setWordWrap(True)
        next_hint.setStyleSheet("font-size: 10px; color: #777; border: none;")
        lay.addWidget(next_hint)

        import time as _time
        _start_ts = [0.0]   # rempli au 1er pct > 0
        _last_pct = [0]

        def _fmt_eta(secs):
            secs = int(secs + 0.5)
            if secs >= 60:
                return f"{secs // 60} min {secs % 60:02d} s"
            return f"{secs} s"

        def _update_remaining():
            # Le timer continue de tourner sur un dialog ferme : on le coupe.
            if not loading.isVisible():
                elapsed_timer.stop()
                return
            pct = _last_pct[0]
            if _start_ts[0] <= 0 or pct <= 0:
                return
            elapsed = _time.monotonic() - _start_ts[0]
            # Trop tot pour une estimation fiable
            if pct < 2 or elapsed < 0.4:
                remaining.setText(tr("te_remaining_calc"))
                return
            total_est = elapsed * 100.0 / pct
            remaining.setText(tr("te_remaining", time=_fmt_eta(max(0.0, total_est - elapsed))))

        elapsed_timer = QTimer(loading)
        elapsed_timer.timeout.connect(_update_remaining)
        elapsed_timer.start(500)

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

        # Crédit discret : l'analyse audio s'appuie sur ffmpeg (licence libre).
        ffmpeg_credit = QLabel(tr("te2_ffmpeg"))
        ffmpeg_credit.setAlignment(Qt.AlignCenter)
        ffmpeg_credit.setStyleSheet("font-size: 9px; color: #444; border: none;")
        lay.addWidget(ffmpeg_credit)

        loading.show()
        QApplication.processEvents()

        def on_progress(pct):
            if self._analysis_cancelled:
                raise _AnalysisCancelled()
            if _start_ts[0] <= 0 and pct > 0:
                _start_ts[0] = _time.monotonic()
            _last_pct[0] = pct
            # Le décodeur Qt rapporte une vraie progression → quitter le mode
            # « occupé » (barre animée) et repasser en barre déterminée 0–100.
            if bar.maximum() == 0:
                bar.setRange(0, 100)
            bar.setValue(pct)
            prefix = tr("te_extract_prefix") if is_vid else tr("te_analyse_prefix")
            status.setText(f"{prefix}... {pct}%")
            _update_remaining()
            QApplication.processEvents()
            if self._analysis_cancelled:
                raise _AnalysisCancelled()

        # Les décodeurs ffmpeg / miniaudio ne rapportent PAS de progression : sans
        # ça la barre resterait bloquée à 0% pendant tout le décodage (impression de
        # figé). On démarre donc en mode « occupé » (barre animée) ; on_progress
        # repasse en 0–100 si un décodeur (Qt) fournit une vraie progression.
        bar.setRange(0, 0)
        status.setText(tr("te_analyse_prefix") + "…")

        try:
            waveform = self.track_waveform.generate_waveform(
                self.media_path, max_samples=5000, progress_callback=on_progress,
                cancel_check=lambda: self._analysis_cancelled
            )
            elapsed_timer.stop()
            remaining.setVisible(False)
            if self._analysis_cancelled:
                loading.close()
                _unlock_buttons()
                print("Analyse annulee - editeur reste ouvert sans forme d'onde")
                return
            if waveform:
                self._apply_waveform(waveform)
                self._save_waveform_cache(waveform)
                if self.media_row in self.main_window.seq.sequences:
                    self.main_window.seq.sequences[self.media_row]['waveform'] = [round(x, 3) for x in waveform]
                bar.setRange(0, 100)
                bar.setValue(100)
                status.setText(tr("te_points_analysed", n=len(waveform)))
                QApplication.processEvents()
                loading.close()
            else:
                status.setText(tr("te_audio_failed"))
                status.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff8800;")
                bar.setVisible(False)
                cancel_btn.setVisible(False)
                QApplication.processEvents()
                QTimer.singleShot(1800, loading.close)
        except _AnalysisCancelled:
            elapsed_timer.stop()
            print("Analyse annulee par l'utilisateur")
            loading.close()
        except Exception as e:
            elapsed_timer.stop()
            remaining.setVisible(False)
            status.setText(tr("tle_audio_failed"))
            status.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff8800;")
            bar.setVisible(False)
            cancel_btn.setVisible(False)
            print(f"Erreur forme d'onde: {e}")
            QApplication.processEvents()
            QTimer.singleShot(1800, loading.close)

        _unlock_buttons()

        # Forcer le rafraichissement
        self.track_waveform.update()
        for track in self.tracks:
            track.update()

    def reanalyze_audio(self):
        """Relance l'analyse audio (forme d'onde) en ignorant le cache.
        Utile si le fichier a changé ou si l'analyse précédente était partielle."""
        if not self.media_path or not getattr(self, '_has_audio_track', False):
            QMessageBox.information(self, tr("te_reanalyze_title"), tr("te_reanalyze_no_audio"))
            return

        ret = QMessageBox.question(
            self, tr("te_reanalyze_title"), tr("te_reanalyze_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ret != QMessageBox.Yes:
            return

        # 1. Supprimer le cache disque de cette forme d'onde
        cache_path = self._get_waveform_cache_path()
        if cache_path and os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except OSError as e:
                print(f"   Warning: cache waveform non supprimé: {e}")

        # 2. Vider la waveform en mémoire (sinon _load_waveform_async ressort de suite)
        self.track_waveform.waveform_data = None
        for track in self.tracks:
            track.waveform_data = None

        # 3. Vider la copie mémorisée dans la séquence
        try:
            seq = self.main_window.seq.sequences.get(self.media_row)
            if seq and 'waveform' in seq:
                del seq['waveform']
        except Exception:
            pass

        # 4. Relancer la génération (barre de progression + re-cache)
        self._load_waveform_async()

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

        edit_menu.addSeparator()

        dup_track_action = edit_menu.addAction(tr("tle_dup_track"))
        dup_track_action.triggered.connect(self.duplicate_group_track)

        # === TOOLS ===
        effect_menu = menubar.addMenu(tr("te_menu_effect"))
        fade_in_action = effect_menu.addAction(tr("tle_fade_in"))
        fade_in_action.triggered.connect(self.apply_fade_in_to_selection)
        fade_out_action = effect_menu.addAction(tr("tle_fade_out"))
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

        reanalyze_action = tools_menu.addAction(tr("te_menu_reanalyze"))
        reanalyze_action.triggered.connect(self.reanalyze_audio)

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
        self._playhead_time_str = "0:00"  # mis à jour par update_playhead / update_cursor

        header_layout.addStretch()

        # Style unifié, aligné sur les boutons de la page d'accueil (toolbar plan de
        # feu) : rectangle arrondi, fond sombre, bordure 1px, survol accent bleu.
        _BTN = 42   # taille unique de tous les boutons du header
        btn_style = """
            QPushButton {
                background: #1e1e1e;
                color: #ddd;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                font-size: 18px;
            }
            QPushButton:hover { background: #2a2a2a; color: #fff; border-color: #0077bb; }
            QPushButton:pressed { background: #333; }
        """
        # Variante d'état « activé » (toggles) : accent bleu discret, même famille.
        _checked_accent = "QPushButton:checked { background:#0a2436; color:#00d4ff; border-color:#0077bb; }"

        # Undo
        undo_btn = QPushButton()
        undo_btn.setIcon(self._icon_undo())
        undo_btn.setIconSize(QSize(23, 23))
        undo_btn.setToolTip(tr("te_tooltip_undo"))
        undo_btn.clicked.connect(self.undo)
        undo_btn.setFixedSize(_BTN, _BTN)
        undo_btn.setStyleSheet(btn_style)
        header_layout.addWidget(undo_btn)

        # Cut
        self.cut_btn = QPushButton()
        self.cut_btn.setIcon(self._icon_cut())
        self.cut_btn.setIconSize(QSize(23, 23))
        self.cut_btn.setToolTip(tr("te_tooltip_cut_tool"))
        self.cut_btn.clicked.connect(self.toggle_cut_mode)
        self.cut_btn.setFixedSize(_BTN, _BTN)
        self.cut_btn.setCheckable(True)
        self.cut_btn.setStyleSheet(btn_style + _checked_accent)
        header_layout.addWidget(self.cut_btn)

        self.paint_btn = QPushButton(header)  # parent obligatoire — sans parent = fenetre fantome top-level
        self.paint_btn.setCheckable(True)
        self.paint_btn.setVisible(False)
        self.paint_btn.clicked.connect(self.toggle_paint_mode)
        self.paint_btn.setToolTip(tr("te2_paint"))

        # Info-bulle « <nom> bloqué » — visible seulement en mode peinture.
        self._paint_hint = QLabel("")
        self._paint_hint.setStyleSheet(
            "color:#00d4ff; font-size:11px; font-weight:600; padding:3px 12px;"
            " background:#0a2a36; border:1px solid #00d4ff66; border-radius:6px;"
        )
        self._paint_hint.setVisible(False)
        header_layout.addWidget(self._paint_hint)

        header_layout.addSpacing(12)

        # ── Décaler les blocs vers la gauche / droite ─────────────────────────
        # Icône façon Premiere : bord de bloc en pointillés + flèche pleine.
        # Cible = blocs sélectionnés s'il y en a, sinon tous. (clic = 100 ms, Ctrl = 1 s, Shift = 10 ms)
        _shift_tip = "Décaler les blocs sélectionnés {dir}\n(ou TOUS si aucun bloc sélectionné)\nClic = 100 ms · Ctrl = 1 s · Shift = 10 ms"
        shift_left_btn = QPushButton()
        shift_left_btn.setIcon(self._make_shift_icon('left'))
        shift_left_btn.setIconSize(QSize(24, 24))
        shift_left_btn.setToolTip(_shift_tip.format(dir="vers la gauche"))
        shift_left_btn.setFixedSize(_BTN, _BTN)
        shift_left_btn.setFocusPolicy(Qt.NoFocus)
        shift_left_btn.setStyleSheet(btn_style)
        shift_left_btn.clicked.connect(self._shift_all_left)
        header_layout.addWidget(shift_left_btn)

        shift_right_btn = QPushButton()
        shift_right_btn.setIcon(self._make_shift_icon('right'))
        shift_right_btn.setIconSize(QSize(24, 24))
        shift_right_btn.setToolTip(_shift_tip.format(dir="vers la droite"))
        shift_right_btn.setFixedSize(_BTN, _BTN)
        shift_right_btn.setFocusPolicy(Qt.NoFocus)
        shift_right_btn.setStyleSheet(btn_style)
        shift_right_btn.clicked.connect(self._shift_all_right)
        header_layout.addWidget(shift_right_btn)

        header_layout.addSpacing(20)

        # Zoom : pavé [−  100%  +] avec libellé « ZOOM » au-dessus
        zoom_col, self.zoom_label = self._make_labeled_stepper(
            "ZOOM", self.zoom_out, self.zoom_in, val_width=52,
            tip="Niveau de zoom  —  Shift + Molette pour zoomer")
        self.zoom_label.setText("100%")
        header_layout.addWidget(zoom_col)

        header_layout.addSpacing(8)

        # ── Toggle preview vidéo (désactivé par défaut) ───────────────────────
        self._video_toggle_btn = QPushButton("🎬")
        self._video_toggle_btn.setToolTip(tr("te2_video_preview"))
        self._video_toggle_btn.setFixedSize(_BTN, _BTN)
        self._video_toggle_btn.setCheckable(True)
        self._video_toggle_btn.setChecked(False)
        self._video_toggle_btn.setVisible(False)   # visible seulement si media vidéo
        self._video_toggle_btn.setStyleSheet(btn_style + """
            QPushButton:checked { background: #0d2a14; color: #44cc44; border-color: #2a7a2a; }
        """)
        self._video_toggle_btn.toggled.connect(self._toggle_video_preview)
        header_layout.addWidget(self._video_toggle_btn)

        header_layout.addSpacing(8)

        # ── Durée par défaut des blocs ────────────────────────────────────────
        # Le QDoubleSpinBox reste le MODÈLE (valeur/plage/pas) mais est caché : l'UI
        # visible est un pavé [−  5 s  +] avec libellé « BLOC » au-dessus.
        # _default_block_dur_ms() lit .value().
        from PySide6.QtWidgets import QDoubleSpinBox as _DSB
        self._default_block_dur_spin = _DSB(header)
        self._default_block_dur_spin.setRange(0.5, 120.0)
        self._default_block_dur_spin.setSingleStep(0.5)
        self._default_block_dur_spin.setValue(5.0)
        self._default_block_dur_spin.setVisible(False)

        bloc_col, self._dur_val_lbl = self._make_labeled_stepper(
            "BLOC",
            lambda: self._default_block_dur_spin.stepBy(-1),
            lambda: self._default_block_dur_spin.stepBy(1),
            val_width=48,
            tip="Durée par défaut des blocs déposés / peints")
        header_layout.addWidget(bloc_col)

        # ── Bouton ● REC : capture le look 2D live en un bloc de séquence ──────
        header_layout.addSpacing(8)
        self._rec_btn = QPushButton(tr("tle_rec"))
        self._rec_btn.setToolTip(
            tr("tle_rec_hint"))
        self._rec_btn.setFixedHeight(_BTN)
        self._rec_btn.setCursor(Qt.PointingHandCursor)
        self._rec_btn.setFocusPolicy(Qt.NoFocus)
        # Style discret : base neutre (comme CLEAR) avec un rouge atténué qui ne
        # ressort qu'au survol — le bouton reste identifiable sans être criard.
        self._rec_btn.setStyleSheet(
            "QPushButton { background:#1e1e1e; color:#b85a5a; border:1px solid #3a3a3a;"
            " border-radius:6px; font-size:12px; font-weight:bold; padding:0 12px; }"
            "QPushButton:hover { background:#2a1414; color:#ff6b6b; border-color:#7a3a3a; }"
            "QPushButton:pressed { background:#3a1010; color:#ffffff; }"
        )
        self._rec_btn.clicked.connect(self._rec_capture_block)
        header_layout.addWidget(self._rec_btn)

        # ── Bouton CLEAR : coupe le look en cours sur le plan 2D (blackout) ────
        self._rec_clear_btn = QPushButton("CLEAR")
        self._rec_clear_btn.setToolTip(
            tr("tle_clear_hint"))
        self._rec_clear_btn.setFixedHeight(_BTN)
        self._rec_clear_btn.setCursor(Qt.PointingHandCursor)
        self._rec_clear_btn.setFocusPolicy(Qt.NoFocus)
        self._rec_clear_btn.setStyleSheet(
            "QPushButton { background:#1e1e1e; color:#bbb; border:1px solid #3a3a3a;"
            " border-radius:6px; font-size:11px; font-weight:bold; padding:0 12px; }"
            "QPushButton:hover { background:#2a2a2a; color:#fff; border-color:#777; }"
            "QPushButton:pressed { background:#333; }"
        )
        self._rec_clear_btn.clicked.connect(self._rec_clear)
        header_layout.addWidget(self._rec_clear_btn)

        def _upd_dur_lbl(v):
            txt = (f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}") + " s"
            self._dur_val_lbl.setText(txt)
        self._default_block_dur_spin.valueChanged.connect(_upd_dur_lbl)
        _upd_dur_lbl(self._default_block_dur_spin.value())

        header_layout.addSpacing(8)

        # Bouton bascule 2D / 3D
        is_3d_open = hasattr(self.main_window, '_plan3d') and self.main_window._plan3d.isVisible()
        self._btn_vue_3d = QPushButton("3D")
        self._btn_vue_3d.setToolTip(tr("tle_toggle_3d"))
        self._btn_vue_3d.setFixedSize(_BTN, _BTN)
        self._btn_vue_3d.setCheckable(True)
        self._btn_vue_3d.setChecked(is_3d_open)
        self._btn_vue_3d.setStyleSheet(btn_style + _checked_accent + """
            QPushButton { font-size: 14px; font-weight: bold; }
        """)
        self._btn_vue_3d.clicked.connect(self._toggle_vue_3d)
        header_layout.addWidget(self._btn_vue_3d)

        return header

    def _toggle_video_preview(self, enabled: bool):
        """Active/désactive la preview vidéo pour préserver les performances."""
        if not self.is_video_file or self.preview_video_widget is None:
            return
        if enabled:
            self._video_preview_container.show()
            self._top_splitter.setSizes([
                self._top_splitter.width() * 2 // 3,
                self._top_splitter.width() // 3,
            ])
            # Connecter la sortie vidéo seulement maintenant
            if self.preview_player is not None:
                self.preview_player.setVideoOutput(self.preview_video_widget)
        else:
            self._video_preview_container.hide()
            if self.preview_player is not None:
                self.preview_player.setVideoOutput(None)

    def _toggle_vue_3d(self):
        if hasattr(self.main_window, 'toggle_3d_window'):
            self.main_window.toggle_3d_window()
        is_visible = hasattr(self.main_window, '_plan3d') and self.main_window._plan3d.isVisible()
        self._btn_vue_3d.setChecked(is_visible)

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
        start_btn.setToolTip(tr("te2_go_start"))
        start_btn.clicked.connect(self._go_to_start)

        # Play / Pause
        self.play_pause_btn = QToolButton()
        self.play_pause_btn.setIcon(create_icon("play", "#ffffff"))
        self.play_pause_btn.setIconSize(QSize(36, 36))
        self.play_pause_btn.setFixedSize(72, 72)
        self.play_pause_btn.setStyleSheet(play_style)
        self.play_pause_btn.setToolTip(tr("tle_play_pause"))
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)

        # Aller à la fin
        end_btn = QToolButton()
        end_btn.setIcon(create_icon("to_end", "#cccccc"))
        end_btn.setIconSize(QSize(28, 28))
        end_btn.setFixedSize(52, 52)
        end_btn.setStyleSheet(side_style)
        end_btn.setToolTip(tr("te2_go_end"))
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
        self.save_btn = QPushButton(tr("te_btn_save"))
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #2a5a2a;
                color: white;
                padding: 10px 30px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background: #3a6a3a; }
            QPushButton:disabled { background: #1a3a1a; color: #555; }
        """)
        self.save_btn.clicked.connect(self.save_sequence)
        footer_layout.addWidget(self.save_btn)

        # Fermer
        self.close_btn = QPushButton(tr("te_btn_close"))
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: #4a2a2a;
                color: white;
                padding: 10px 30px;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover { background: #5a3a3a; }
            QPushButton:disabled { background: #2a1a1a; color: #555; }
        """)
        self.close_btn.clicked.connect(self.close_editor)
        footer_layout.addWidget(self.close_btn)

        return footer

    def get_media_duration(self):
        """Recupere la duree reelle du media (audio et video), avec cache en session."""
        # TEMPO/PAUSE: utiliser la duree definie
        if hasattr(self, 'media_duration_override') and self.media_duration_override > 0:
            return self.media_duration_override

        # Image: utiliser la duree definie dans image_durations
        if self.media_path and media_icon(self.media_path) == "image":
            image_dur = self.main_window.seq.image_durations.get(self.media_row)
            if image_dur:
                return image_dur * 1000
            return 30000  # 30s par defaut

        if not self.media_path or not os.path.exists(self.media_path):
            return 180000

        # Cache en session (path + mtime) — evite de re-sonder le media a chaque
        # ouverture de l'editeur (le sondage video peut bloquer plusieurs secondes).
        cache = getattr(self.main_window, '_media_duration_cache', None)
        if cache is None:
            cache = self.main_window._media_duration_cache = {}
        try:
            key = (self.media_path, os.path.getmtime(self.media_path))
        except OSError:
            key = None
        if key is not None and key in cache:
            return cache[key]

        dur_ms = self._probe_media_duration()

        # On ne met en cache qu'un resultat fiable (pas le defaut 180000), pour
        # laisser une nouvelle chance au sondage la prochaine fois.
        if key is not None and dur_ms and dur_ms != 180000:
            cache[key] = dur_ms
        return dur_ms

    def _probe_media_duration(self):
        """Sonde la duree du media via les decodeurs disponibles (en ms)."""
        import subprocess as _sp, sys as _sys

        is_video = media_icon(self.media_path) == "video"

        # 1+2. Decodeurs audio (miniaudio/mutagen): inutiles et parfois trompeurs
        #      sur un conteneur video (MKV/AVI/MOV) -> on les saute pour la video.
        if not is_video:
            # 1. miniaudio (MP3, WAV, FLAC, OGG) — pas d'event loop, pas de fenetre WMF
            try:
                import miniaudio
                info = miniaudio.get_file_info(self.media_path)
                if info.duration > 0:
                    return int(info.duration * 1000)
            except Exception:
                pass

            # 2. mutagen (MP3, M4A, AAC, FLAC, OGG, WAV, WMA...)
            try:
                import mutagen
                audio = mutagen.File(self.media_path)
                if audio is not None and audio.info.length > 0:
                    return int(audio.info.length * 1000)
            except Exception:
                pass

        # 3. ffprobe (video ou echec mutagen) — subprocess sans fenetre
        try:
            _kwargs = {}
            if _sys.platform == "win32":
                _kwargs["creationflags"] = _sp.CREATE_NO_WINDOW
            result = _sp.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", self.media_path],
                capture_output=True, text=True, timeout=10, **_kwargs
            )
            dur = float(result.stdout.strip())
            if dur > 0:
                return int(dur * 1000)
        except Exception:
            pass

        # 4. Fallback QMediaPlayer (video type MKV/AVI/MOV sans ffprobe installe)
        #    Qt decode le conteneur et emet durationChanged; fonctionne sans binaire externe.
        temp_player = None
        try:
            import time as _time

            temp_player = QMediaPlayer()
            temp_audio = QAudioOutput()
            temp_player.setAudioOutput(temp_audio)

            # Sans output video, Qt ne parse pas correctement certains conteneurs video
            if is_video and QVideoWidget is not None:
                temp_video = QVideoWidget()
                temp_video.setFixedSize(1, 1)
                temp_video.hide()
                temp_player.setVideoOutput(temp_video)

            duration_ms = [0]

            def _on_duration_changed(dur):
                if dur > 0:
                    duration_ms[0] = dur

            temp_player.durationChanged.connect(_on_duration_changed)
            temp_player.setSource(QUrl.fromLocalFile(self.media_path))

            timeout = 10 if is_video else 5
            start = _time.time()
            while duration_ms[0] == 0 and (_time.time() - start) < timeout:
                QApplication.processEvents()
                _time.sleep(0.05)

            if duration_ms[0] > 0:
                return duration_ms[0]
        except Exception:
            pass
        finally:
            if temp_player is not None:
                try:
                    temp_player.setSource(QUrl())
                except Exception:
                    pass

        return 180000  # 3 minutes par defaut

    def setup_audio_player(self):
        """Configure le player audio/video pour preview (pas pour images/pauses)"""
        self.preview_player = QMediaPlayer(self)
        self.preview_audio = QAudioOutput(self)
        self.preview_player.setAudioOutput(self.preview_audio)

        is_image = self.media_path and media_icon(self.media_path) == "image"

        self.is_video_file = self.media_path and media_icon(self.media_path) == "video"
        _show_video_btn = bool(self.is_video_file and QVideoWidget is not None)
        if _show_video_btn:
            self.preview_video_widget = QVideoWidget()
            self.preview_video_widget.setStyleSheet("background: #000;")
            self._video_preview_container.layout().addWidget(self.preview_video_widget)
            # Vidéo désactivée par défaut — activer via le bouton 🎬 dans le header
            self._video_preview_container.hide()
            # Ne PAS connecter setVideoOutput tant que la preview est cachée
        # Le bouton 🎬 n'est disponible QUE pour un média vidéo : sur un fichier
        # audio (ou image), on le cache et on coupe toute preview résiduelle
        # (couvre aussi la réutilisation de l'éditeur avec un autre média).
        if hasattr(self, '_video_toggle_btn'):
            self._video_toggle_btn.setVisible(_show_video_btn)
            if not _show_video_btn:
                self._video_toggle_btn.setChecked(False)
                self._video_preview_container.hide()

        if self.media_path and not is_image and not self.is_tempo:
            self.preview_player.setSource(QUrl.fromLocalFile(self.media_path))

    def _position_centers(self, pos_clip):
        """{id(lyre): (pan, tilt)} imposé par le clip Position actif, {} sinon.

        Même source que le rappel manuel d'une position (`position_preset_values`)
        pour que l'effet tourne autour du point exact où le rappel aurait posé
        la lyre.
        """
        if pos_clip is None:
            return {}
        try:
            from core import position_preset_values, find_position_preset
            presets = getattr(self.main_window, 'position_presets', []) or []
            preset = find_position_preset(
                presets,
                getattr(pos_clip, 'position_preset_idx', None),
                getattr(pos_clip, 'position_preset_name', ''))
            if not preset:
                return {}
            lyres = [p for p in self.main_window.projectors
                     if getattr(p, 'fixture_type', '') in ('Moving Head', 'Lyre')]
            return position_preset_values(preset, lyres)
        except Exception as e:
            print(f"[REC] centre de position indisponible : {e}")
            return {}

    def _reset_before_play(self):
        """Remet les projecteurs à plat avant de lancer l'aperçu.

        Pan/Tilt volontairement PRÉSERVÉS : les recentrer ferait bouger les
        lyres à chaque Play, y compris sans clip Position. Quand une piste
        Position existe, elle les repositionne de toute façon.
        """
        try:
            for proj in self.main_window.projectors:
                # Rend la main aux mémoires et à la timeline.
                proj._manual_color = False
                proj._manual_move  = False
                proj.level = 0
                proj.base_color = QColor(0, 0, 0)
                proj.color      = QColor(0, 0, 0)
                proj.uv = proj.white_boost = 0
                proj.amber_boost = proj.orange_boost = 0
                proj.gobo = proj.gobo_rotation = 0
                proj.zoom = 0
                proj.shutter = 255
                proj.color_wheel = 0
                proj.prism = proj.prism_rotation = 0
                proj.effects = 0
                proj.strobe_speed = 0
                # Canaux bruts : prioritaires dans le moteur DMX, un « Mode » ou
                # un Reset posé à la main resterait actif tout l'aperçu.
                proj.channel_extras = {}

            # État interne de l'aperçu : sans ça un effet du passage précédent
            # continue de tourner par-dessus (strobe résiduel déjà constaté).
            self._seq_clip_active  = None
            self._eff_clips_active = {}
            self._pos_clip_active  = None
            self.main_window.active_effect        = None
            self.main_window.active_effect_config = {}
            if hasattr(self.main_window, 'stop_effect'):
                self.main_window.stop_effect()
        except Exception as e:
            # Un aperçu doit démarrer même si le nettoyage échoue.
            print(f"[REC] reset avant lecture ignoré : {e}")

    def toggle_play_pause(self):
        """Toggle play/pause avec timer - synchro preview et player principal"""
        if self.preview_player is None:
            return
        main_playing = self.main_window.player.playbackState() == QMediaPlayer.PlayingState
        preview_playing = self.preview_player.playbackState() == QMediaPlayer.PlayingState
        tempo_playing = getattr(self, '_tempo_playing', False)

        if preview_playing or main_playing or tempo_playing:
            # Arreter tout
            self.preview_player.pause()
            self.main_window.player.pause()
            self._tempo_playing = False
            self.play_pause_btn.setIcon(create_icon("play", "#ffffff"))
            self.playback_timer.stop()
            # Arrêter les effets actifs (séquence et effet track)
            if self._seq_clip_active is not None or self._eff_clips_active:
                self.main_window.active_effect        = None
                self.main_window.active_effect_config = {}
                if hasattr(self.main_window, 'stop_effect'):
                    self.main_window.stop_effect()
                self._seq_clip_active  = None
                self._eff_clips_active = {}
        else:
            # Repartir d'un état propre : sans ça l'aperçu démarre sur ce qui
            # traîne d'une édition manuelle au plan de feu 2D, et ne montre pas
            # ce que donnera le show. Le drapeau `_manual_color` est le vrai
            # coupable : posé dès qu'on touche un projecteur à la main, il lui
            # fait IGNORER les mémoires ensuite, et il survivait au Play.
            self._reset_before_play()
            pos = int(self.playback_position)
            if self.is_tempo or not self.media_path:
                # Pause / tempo : pas de média → horloge manuelle.
                if pos >= self.media_duration:
                    pos = 0                       # au bout → repartir du début
                    self.playback_position = 0
                self._tempo_playing    = True
                self._tempo_start_wall = time.monotonic()
                self._tempo_start_pos  = pos
            else:
                # Lancer le preview a la position actuelle du curseur
                if pos > 0:
                    self.preview_player.setPosition(pos)
                self.preview_player.play()
            self.play_pause_btn.setIcon(create_icon("pause", "#ffffff"))
            self.playback_timer.start(40)

    def seek_relative(self, delta_ms):
        """Seek relatif avec recentrage de la vue sur le curseur."""
        if self.preview_player is None:
            return
        current = self.preview_player.position()
        new_pos = max(0, min(current + delta_ms, self.media_duration))
        self.preview_player.setPosition(int(new_pos))
        self.playback_position = new_pos
        # Recentrer la vue sur le nouveau curseur
        pixels_per_ms = 0.05 * self.current_zoom
        cursor_x = int(145 + new_pos * pixels_per_ms)
        viewport_w = self.tracks_scroll.viewport().width()
        sb = self.tracks_scroll.horizontalScrollBar()
        target_scroll = cursor_x - viewport_w // 2
        sb.setValue(max(0, target_scroll))
        self.ruler.update()
        for track in self.tracks:
            track.update()
        self.track_waveform.update()

    def _go_to_start(self):
        """Aller au début de la timeline"""
        if self.preview_player is None:
            return
        self.preview_player.setPosition(0)
        self.playback_position = 0
        self.ruler.update()
        for track in self.tracks:
            track.update()

    def _go_to_end(self):
        """Aller à la fin de la timeline"""
        if self.preview_player is None:
            return
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
        if event.position().x() < 145:
            return  # zone label gelée, ignorer
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
        """Met a jour le ruler quand on scroll et gele la colonne label gauche"""
        self.ruler.update()
        # Maintenir les labels de piste collés au bord gauche du viewport
        for track in self.tracks + [self.track_waveform]:
            if hasattr(track, 'label'):
                track.label.move(value + 11, track.label.y())
            if hasattr(track, '_collapse_btn'):
                track._collapse_btn.move(value + 119, track._collapse_btn.y())
            track.update()
        self._pin_add_track_buttons(value)

    def _pin_add_track_buttons(self, value=None):
        """Colle les boutons « ＋ Effet » / « ＋ Séquence » au bord gauche du viewport.

        Ils vivent dans le conteneur qui défile horizontalement : sans ça, ajouter
        une piste obligeait à revenir tout au début de la timeline pour retrouver
        le bouton. Les libellés de piste étaient déjà épinglés, pas eux.

        On décale la MARGE du layout plutôt que de déplacer le bouton : un
        simple move() serait annulé au premier recalcul de layout.
        """
        if value is None:
            value = self.tracks_scroll.horizontalScrollBar().value()
        for lay in (getattr(self, '_add_eff_btn_lay', None),
                    getattr(self, '_add_seq_btn_lay', None)):
            if lay is None:
                continue
            m = lay.contentsMargins()
            if m.left() != value + 11:
                lay.setContentsMargins(value + 11, m.top(), m.right(), m.bottom())

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
        if self.preview_player is not None:
            self.preview_player.setPosition(int(time_ms))

        # Rafraichir l'affichage (le temps est dessiné dans le ruler)
        pos_sec = int(time_ms / 1000)
        self._playhead_time_str = f"{pos_sec // 60}:{pos_sec % 60:02d}"
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
        w = self.ruler.width()
        h = self.ruler.height()
        painter.fillRect(0, 0, w, h, QColor("#1a1a1a"))

        # Zone label (colonne gauche gelée)
        painter.fillRect(0, 0, 145, h, QColor("#141414"))
        painter.setPen(QPen(QColor("#2a2a2a"), 1))
        painter.drawLine(145, 0, 145, h)

        # Afficher la position courante dans la zone label
        pos_str = getattr(self, '_playhead_time_str', '0:00')
        total_str = getattr(self, 'total_time_str', '0:00')
        font = painter.font()
        font.setPixelSize(13)
        font.setBold(True)
        font.setFamily("Segoe UI")
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRect(0, 0, 145, h), Qt.AlignCenter, f"{pos_str} / {total_str}")

        # Recuperer le scroll horizontal pour synchroniser
        scroll_offset = self.tracks_scroll.horizontalScrollBar().value()

        pixels_per_ms = 0.05 * self.current_zoom

        # Espacement minimum entre labels : 55px
        min_step_s = 55.0 / (pixels_per_ms * 1000)
        step = 1
        for s in [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]:
            if s >= min_step_s:
                step = s
                break
        else:
            step = 3600

        # Clipper les marqueurs à droite de la zone label
        painter.setClipRect(145, 0, w - 145, h)

        font2 = painter.font()
        font2.setPixelSize(10)
        font2.setBold(False)
        painter.setFont(font2)
        painter.setPen(QColor("#888"))

        for sec in range(0, int(self.media_duration / 1000) + 1, step):
            x = 145 + int(sec * 1000 * pixels_per_ms) - scroll_offset
            if x < 145 or x > w + 50:
                continue
            painter.setPen(QColor("#888"))
            painter.drawLine(x, 25, x, h)

            if sec >= 3600:
                time_str = f"{sec // 3600}h{(sec % 3600) // 60:02d}"
            elif sec >= 60:
                time_str = f"{sec // 60}:{sec % 60:02d}"
            else:
                time_str = f"{sec}s"

            painter.drawText(x - 18, 18, time_str)

        painter.setClipping(False)

        # Curseur de lecture (rouge) - aussi decale par le scroll
        cursor_x = 145 + int(self.playback_position * pixels_per_ms) - scroll_offset
        if cursor_x >= 145 and cursor_x < w + 10:
            painter.setPen(QPen(QColor("#ff0000"), 3))
            painter.drawLine(cursor_x, 0, cursor_x, h)

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
            preview_playing = (self.preview_player is not None and
                               self.preview_player.playbackState() == QMediaPlayer.PlayingState)
            if not preview_playing:
                self.playback_timer.stop()

    def update_playhead(self):
        """Met a jour la position du curseur pendant lecture (preview, player principal, ou pause)"""
        playing = False
        tempo_end = False

        if getattr(self, '_tempo_playing', False):
            # Pause / tempo : pas de média → horloge manuelle (temps mural).
            elapsed = (time.monotonic() - self._tempo_start_wall) * 1000.0
            self.playback_position = self._tempo_start_pos + elapsed
            if self.playback_position >= self.media_duration:
                self.playback_position = self.media_duration
                tempo_end = True
            playing = True
        elif self.preview_player is not None and self.preview_player.playbackState() == QMediaPlayer.PlayingState:
            self.playback_position = self.preview_player.position()
            playing = True
        elif self.main_window.player.playbackState() == QMediaPlayer.PlayingState:
            self.playback_position = self.main_window.player.position()
            playing = True

        if playing:
            # Auto-scroll pour suivre le curseur pendant la lecture
            self.ensure_playhead_visible()

            # Mettre a jour le compteur de position (affiché dans le ruler)
            pos_sec = int(self.playback_position / 1000)
            self._playhead_time_str = f"{pos_sec // 60}:{pos_sec % 60:02d}"

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

            # Fin d'une pause temporisée → stopper proprement.
            if tempo_end:
                self._tempo_playing = False
                self.playback_timer.stop()
                if hasattr(self, 'play_pause_btn'):
                    self.play_pause_btn.setIcon(create_icon("play", "#ffffff"))

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
            p.strobe_speed = 0
            p.color_wheel = 0
            # Canaux bruts (Mode…) remis à zéro chaque frame — parité restitution
            p.channel_extras = {}
            # Canaux dédiés (UV, Blanc, Ambre, Orange) : sans ce reset, une valeur
            # posée avant la lecture (curseur du plan de feu, rappel mémoire,
            # effet) restait collée toute la séquence, et un bloc UV ne
            # s'éteignait jamais à sa fin.
            p.uv = p.white_boost = p.amber_boost = p.orange_boost = 0

        # Projecteurs sous un clip couleur/séquence actif ce frame : l'effet
        # (qui s'applique après) devra suivre leur couleur + leur fade in/out
        # au lieu d'imposer sa propre couleur (blanc) à pleine intensité.
        self.main_window._fx_clip_ids = set()

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
                            # Forcer le cue fixé si expansion multi-cue
                            cue_idx = getattr(new_seq_clip, 'cue_index', None)
                            if cue_idx is not None:
                                self.main_window._mem_cue_idx[mem_ref] = cue_idx
                                self.main_window._apply_memory_to_projectors(mem_col, row)
                            # Déclencher l'effet du cue courant
                            if hasattr(self.main_window, '_mem_ensure_cues'):
                                self.main_window._mem_ensure_cues(mem)
                            cue = self.main_window._mem_active_cue(mem_col, row) if cue_idx is not None else mem.get("cues", [{}])[0]
                            eff_cfg = cue.get("effect") or {}
                            if eff_cfg.get("layers") and hasattr(self.main_window, 'start_effect'):
                                self.main_window.active_effect = eff_cfg.get("name", "")
                                self.main_window.active_effect_config = eff_cfg
                                self.main_window.start_effect(eff_cfg.get("name", ""))

        # ── Détecter les clips d'effet actifs (toutes les pistes Effet) ─────
        new_eff_clips = {}
        for et in getattr(self, '_effect_tracks', []):
            for clip in et.clips:
                if clip.start_time <= current_time <= clip.start_time + clip.duration:
                    new_eff_clips[et.name] = clip
                    break

        if new_eff_clips != self._eff_clips_active:
            self._eff_clips_active = new_eff_clips
            if not new_eff_clips:
                self.main_window.active_effect        = None
                self.main_window.active_effect_config = {}
                if hasattr(self.main_window, 'stop_effect'):
                    self.main_window.stop_effect()
            else:
                # Fusionner les couches de tous les clips actifs
                merged_layers = []
                merged_names  = []
                merged_type   = ''
                merged_target_groups = []
                _has_all_groups = False
                merged_no_color = False
                # Catalogue chargé une seule fois (ce bloc ne s'exécute qu'au
                # changement de clips d'effet, pas à chaque frame).
                try:
                    from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
                    _catalog = BUILTIN_EFFECTS + _load_custom_effects()
                except Exception:
                    _catalog = []
                for clip in new_eff_clips.values():
                    eff_name   = getattr(clip, 'effect_name', '')
                    eff_layers = list(getattr(clip, 'effect_layers', []))
                    eff_type   = getattr(clip, 'effect_type', '')
                    eff_tg     = list(getattr(clip, 'effect_target_groups', []))
                    # Résoudre depuis le catalogue : couches manquantes + flag no_color
                    # (no_color = l'effet doit hériter de la couleur assignée).
                    _cat_def = next((_e for _e in _catalog if _e.get('name') == eff_name), None)
                    if _cat_def:
                        if not eff_layers:
                            eff_layers = [dict(l) for l in _cat_def.get('layers', [])]
                            eff_type   = _cat_def.get('type', '')
                        if _cat_def.get('no_color'):
                            merged_no_color = True
                    # Cloisonner les couches par groupe du clip (parité restitution) :
                    # évite qu'une couche couleur "Tous" d'un effet A/B déborde sur
                    # la lyre (D) quand 2 effets fusionnent (superposition).
                    eff_layers = scope_layers_to_groups(eff_layers, eff_tg)
                    merged_layers.extend(eff_layers)
                    if eff_name:
                        merged_names.append(eff_name)
                    if not merged_type:
                        merged_type = eff_type
                    if not eff_tg:
                        _has_all_groups = True
                    else:
                        for g in eff_tg:
                            if g not in merged_target_groups:
                                merged_target_groups.append(g)
                combined_name = " + ".join(merged_names) if merged_names else ''
                cfg = {
                    'name': combined_name, 'type': merged_type,
                    'layers': merged_layers, 'play_mode': 'loop',
                    'target_groups': [] if _has_all_groups else merged_target_groups,
                    'speed_override': 50,
                    'no_color': merged_no_color,
                }
                self.main_window.active_effect        = combined_name
                self.main_window.active_effect_config = cfg
                if hasattr(self.main_window, 'start_effect') and merged_layers:
                    self.main_window.start_effect(combined_name)

        # Sécurité (hors garde par changement) : aucune ligne d'effet active ce
        # frame → aucun effet ne doit tourner dans l'aperçu. La garde ci-dessus ne
        # coupe l'effet QUE lorsque l'ensemble des clips d'effet CHANGE ; quand il
        # n'y en a jamais eu (empty → empty, `{} != {}` faux), elle ne s'exécute
        # pas et un effet RÉSIDUEL laissé actif par la fenêtre principale (pad
        # effet, cue mémoire à effet…) survit et repeint les clips couleur en
        # fondu → strobe. « Pas de clip d'effet » ⇒ l'effet actif n'appartient pas
        # à l'aperçu, on peut donc le stopper sans risque.
        if not new_eff_clips and getattr(self.main_window, 'active_effect', None):
            self.main_window.active_effect        = None
            self.main_window.active_effect_config = {}
            if hasattr(self.main_window, 'stop_effect'):
                self.main_window.stop_effect()

        # ── Détecter le clip de position actif ───────────────────────────────
        pos_track = self.track_map.get("Position")
        new_pos_clip = None
        if pos_track:
            for clip in pos_track.clips:
                if clip.start_time <= current_time <= clip.start_time + clip.duration:
                    new_pos_clip = clip
                    break
        # Publier le centre imposé par le clip Position pour le moteur d'effets.
        # Sans ça, une couche Pan/Tilt sans colonne POSITION se recentre sur
        # l'état capturé au DÉMARRAGE de l'effet — périmé dès que la position
        # change — voire sur le milieu de course : les lyres dérivaient de la
        # position choisie dès qu'un effet tournait. Recalculé à chaque image.
        self.main_window._timeline_pos_centers = self._position_centers(new_pos_clip)

        if new_pos_clip is not self._pos_clip_active:
            self._pos_clip_active = new_pos_clip
            if new_pos_clip is not None:
                idx = getattr(new_pos_clip, 'position_preset_idx', None)
                presets = getattr(self.main_window, 'position_presets', [])
                if idx is not None and idx < len(presets):
                    preset = presets[idx]
                    lyres_cur = [p for p in self.main_window.projectors
                                 if getattr(p, 'fixture_type', '') in ('Moving Head', 'Lyre')]
                    lyre_by_name: dict = {}
                    for p in lyres_cur:
                        if p.name and p.name not in lyre_by_name:
                            lyre_by_name[p.name] = p
                    lyre_by_group: dict = {}
                    for p in lyres_cur:
                        lyre_by_group.setdefault(p.group, []).append(p)
                    for i, proj_state in enumerate(preset.get("projectors", [])):
                        p = lyres_cur[i] if i < len(lyres_cur) else None
                        if p is None:
                            p = lyre_by_name.get(proj_state.get("name"))
                        if p is None:
                            candidates = lyre_by_group.get(proj_state.get("group"), [])
                            p = candidates[0] if candidates else None
                        if p and hasattr(self.main_window, '_start_pan_tilt_transition'):
                            self.main_window._start_pan_tilt_transition(
                                p, proj_state.get("pan", 32768), proj_state.get("tilt", 32768), 500)

        # ── Piste Gobo ────────────────────────────────────────────────────────
        # Appliqué à CHAQUE passage et non au seul changement de clip : un autre
        # émetteur (mémoire, effet) peut avoir repositionné la roue entre-temps,
        # et le gobo resterait alors figé sur la mauvaise valeur.
        gobo_track = self.track_map.get("Gobo")
        if gobo_track:
            g_clip = None
            for clip in gobo_track.clips:
                if clip.start_time <= current_time <= clip.start_time + clip.duration:
                    g_clip = clip
                    break
            if g_clip is not None and getattr(g_clip, 'gobo_dmx', None) is not None:
                g_val = max(0, min(255, int(g_clip.gobo_dmx)))
                g_rot = max(0, min(255, int(getattr(g_clip, 'gobo_rotation', 0) or 0)))
                for p in self.main_window.projectors:
                    if 'Gobo1' in (getattr(p, 'dmx_profile', None) or []):
                        p.gobo = g_val
                        p.gobo_rotation = g_rot

        # ── 1) Appliquer les clips de couleur par groupe (priorité basse) ─────
        for track in self.tracks:
            if (getattr(track, 'is_sequence_track', False) or
                    getattr(track, 'is_effect_track', False) or
                    getattr(track, 'is_position_track', False) or
                    getattr(track, 'is_gobo_track', False)):
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

                    c1 = clip.color
                    c2 = getattr(clip, 'color2', None)
                    # Fondu enchaîné couleur CENTRÉ sur la jointure : morphe
                    # couleur + intensité entre les 2 blocs (sans passer par le
                    # noir). Le bloc actif peut être en TÊTE (jointure gauche) ou
                    # en QUEUE (jointure droite) du fondu. Parité show.
                    _prev = _next = None
                    for _c in track.clips:
                        if _c is clip:
                            continue
                        if abs((_c.start_time + _c.duration) - start) <= 5:
                            _prev = _c
                        if abs(_c.start_time - end) <= 5:
                            _next = _c
                    _xr = xfade_resolve(clip, _prev, _next, current_time, _clip_obj_get)
                    if _xr:
                        _xc, _xc2, _xi = _xr
                        c1 = _xc
                        if _xc2 is not None:
                            c2 = _xc2
                        intensity = _xi
                    brightness = intensity / 100.0
                    # Interpolation pan/tilt (lyres)
                    pan_s  = getattr(clip, 'pan_start',  128)
                    pan_e  = getattr(clip, 'pan_end',    128)
                    tilt_s = getattr(clip, 'tilt_start', 128)
                    tilt_e = getattr(clip, 'tilt_end',   128)
                    _has_move = (pan_s != 128 or pan_e != 128 or
                                 tilt_s != 128 or tilt_e != 128)
                    if _has_move:
                        t = min(1.0, elapsed / max(1, clip.duration))
                        _pan_val  = int((pan_s  + (pan_e  - pan_s)  * t) * 256)
                        _tilt_val = int((tilt_s + (tilt_e - tilt_s) * t) * 256)
                    _clip_strobe = getattr(clip, 'strobe_speed', 0)
                    for pos, idx in enumerate(track_to_indices.get(track.name, [])):
                        if idx < len(projectors):
                            p = projectors[idx]
                            color = c1 if (c2 is None or pos % 2 == 0) else c2
                            self.main_window._fx_clip_ids.add(id(p))
                            # Bloc « canal dédié » (Black Light / Ambre) : pilote
                            # la LED dédiée seule, RVB à zéro. Sur une fixture qui
                            # n'a pas ce canal, retombe sur le rendu RVB ci-dessous.
                            _special = apply_special_block(p, color, intensity)
                            if not _special:
                                p.level = intensity
                                p.base_color = color
                                p.color = QColor(
                                    int(color.red()   * brightness),
                                    int(color.green() * brightness),
                                    int(color.blue()  * brightness),
                                )
                            p.strobe_speed = _clip_strobe
                            if _has_move:
                                p.pan  = _pan_val
                                p.tilt = _tilt_val
                            if not _special and hasattr(self.main_window, '_update_color_wheel'):
                                self.main_window._update_color_wheel(p, color)
                    break

        # ── 2) Appliquer les séquences par-dessus les groupes (HTP) ───────────
        # Toutes les pistes Séquence, fusionnées en HTP via la MÊME fonction que
        # la restitution → l'aperçu montre exactement ce que jouera le show.
        from light_timeline import apply_seq_memories_htp

        def _faded_brightness(clip):
            _seq_i = clip.intensity
            _dur = clip.duration
            _fi = getattr(clip, 'fade_in_duration', 0)
            _fo = getattr(clip, 'fade_out_duration', 0)
            if _dur > 0:
                _rel = (current_time - clip.start_time) / _dur
                if _fi > 0 and _rel < (_fi / _dur):
                    _seq_i *= _rel / (_fi / _dur)
                if _fo > 0 and _rel > (1 - _fo / _dur):
                    _seq_i *= (1 - _rel) / (_fo / _dur)
            return max(0.0, _seq_i) / 100.0

        _seq_entries = []
        for _t in self.tracks:
            if not getattr(_t, 'is_sequence_track', False):
                continue
            for _c in _t.clips:
                if not getattr(_c, 'memory_ref', None):
                    continue
                if _c.start_time <= current_time <= _c.start_time + _c.duration:
                    _seq_entries.append({
                        'memory_ref': _c.memory_ref,
                        'cue_index': getattr(_c, 'cue_index', None),
                        'brightness': _faded_brightness(_c),
                    })
        if _seq_entries:
            # Un clip de la piste Position actif verrouille le pan/tilt des lyres :
            # les séquences ne doivent pas l'écraser (la piste Position prime).
            _pos_locked_idxs = set()
            if new_pos_clip is not None:
                _pos_locked_idxs = {i for i, p in enumerate(projectors)
                                    if getattr(p, 'fixture_type', '') in ('Moving Head', 'Lyre')}
            apply_seq_memories_htp(
                _seq_entries, getattr(self.main_window, 'memories', None),
                projectors, self.main_window, lock_pantilt_idxs=_pos_locked_idxs)

        # ── 3) Appliquer l'effet courant (priorité maximale) ─────────────────
        # La preview pilote l'effet elle-même, frame par frame, au rythme du
        # playhead (update_effect ci-dessous). Or start_effect a lancé en plus
        # le timer autonome de l'effet : on le neutralise, sinon les deux
        # drivers déphasés écrivent les projecteurs en parallèle et la sortie
        # DMX strobe (le compteur d'effet avance ~2× de façon irrégulière).
        if getattr(self.main_window, 'active_effect', None) and hasattr(self.main_window, 'update_effect'):
            _eff_timer = getattr(self.main_window, 'effect_timer', None)
            if _eff_timer is not None and _eff_timer.isActive():
                _eff_timer.stop()
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

            # Durée nécessaire = max(durée sauvegardée, fin du dernier clip)
            # Gère le cas où saved_duration == 180000 mais les clips dépassent
            saved_duration = seq.get('duration', 0)
            clips_max_end = 0
            for c in clips_data:
                end = c.get('start', 0) + c.get('duration', 0)
                if end > clips_max_end:
                    clips_max_end = end
            needed_duration = max(saved_duration, clips_max_end)
            if needed_duration > self.media_duration:
                self.media_duration = needed_duration
                for track in self.tracks + [self.track_waveform]:
                    track.total_duration = needed_duration
                    track.setMinimumWidth(145 + int(needed_duration * track.pixels_per_ms) + 50)
                # Mettre à jour la durée totale (affichée dans le ruler)
                dur_s = int(self.media_duration / 1000)
                self.total_time_str = f"{dur_s // 60}:{dur_s % 60:02d}"

            # Créer les pistes Effet supplémentaires présentes dans la sauvegarde
            for clip_data in clips_data:
                tname = clip_data.get('track', '')
                if tname.startswith('Effet') and tname != 'Effet' and tname not in self.track_map:
                    self._add_effect_track_named(tname)
                elif tname.startswith('Séquence') and tname != 'Séquence' and tname not in self.track_map:
                    self._add_sequence_track_named(tname)

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
                    clip.xfade = clip_data.get('xfade', 0)
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
                    clip.strobe_speed   = clip_data.get('strobe_speed', 0)
                    if clip_data.get('memory_ref'):
                        clip.memory_ref   = tuple(clip_data['memory_ref'])
                        clip.memory_label = clip_data.get('memory_label', '')
                        if 'cue_index' in clip_data:
                            clip.cue_index = clip_data['cue_index']
                    if clip_data.get('position_preset_idx') is not None:
                        clip.position_preset_idx  = clip_data['position_preset_idx']
                        clip.position_preset_name = clip_data.get('position_preset_name', '')
                    if clip_data.get('gobo_dmx') is not None:
                        clip.gobo_dmx      = clip_data['gobo_dmx']
                        clip.gobo_name     = clip_data.get('gobo_name', '')
                        clip.gobo_rotation = clip_data.get('gobo_rotation', 0)

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

    @staticmethod
    def _clip_to_dict(clip, track) -> dict:
        """Sérialise UN clip en dict JSON — source unique pour la sauvegarde .tui,
        l'autosave .lrec ET l'export manuel .lrec.

        Avant, l'export manuel avait sa propre version appauvrie (sans memory_ref /
        position_preset_idx / mouvement) : un clip de séquence ou de position
        exporté puis réimporté retombait en simple bloc couleur (souvent noir).
        Un seul writer garantit qu'export/import préserve TOUS les types de clip.
        """
        d = {
            'track': track.name,
            'start': clip.start_time,
            'duration': clip.duration,
            'color': clip.color.name(),
            'intensity': clip.intensity,
            'fade_in': getattr(clip, 'fade_in_duration', 0),
            'fade_out': getattr(clip, 'fade_out_duration', 0),
            'xfade': getattr(clip, 'xfade', 0),
            'effect': getattr(clip, 'effect', None),
            'effect_speed': getattr(clip, 'effect_speed', 50),
            'effect_layers': getattr(clip, 'effect_layers', []),
            'effect_play_mode': getattr(clip, 'effect_play_mode', 'loop'),
            'effect_duration': getattr(clip, 'effect_duration', 0),
            'effect_name': getattr(clip, 'effect_name', ''),
            'effect_type': getattr(clip, 'effect_type', ''),
            'effect_target_groups': getattr(clip, 'effect_target_groups', []),
            'strobe_speed': getattr(clip, 'strobe_speed', 0),
        }
        if getattr(clip, 'color2', None):
            d['color2'] = clip.color2.name()
        # Clip de séquence AKAI (mémoire)
        if getattr(clip, 'memory_ref', None):
            d['memory_ref'] = list(clip.memory_ref)
            d['memory_label'] = getattr(clip, 'memory_label', '')
            if getattr(clip, 'cue_index', None) is not None:
                d['cue_index'] = clip.cue_index
        # Clip de position lyre
        if getattr(clip, 'position_preset_idx', None) is not None:
            d['position_preset_idx']  = clip.position_preset_idx
            d['position_preset_name'] = getattr(clip, 'position_preset_name', '')
        # Clip de gobo
        if getattr(clip, 'gobo_dmx', None) is not None:
            d['gobo_dmx']      = clip.gobo_dmx
            d['gobo_name']     = getattr(clip, 'gobo_name', '')
            d['gobo_rotation'] = getattr(clip, 'gobo_rotation', 0)
        # Mouvement Pan/Tilt
        if (getattr(clip, 'move_effect', None) or
                getattr(clip, 'pan_start', 128) != 128 or getattr(clip, 'pan_end', 128) != 128 or
                getattr(clip, 'tilt_start', 128) != 128 or getattr(clip, 'tilt_end', 128) != 128):
            d.update({
                'pan_start':      getattr(clip, 'pan_start', 128),
                'tilt_start':     getattr(clip, 'tilt_start', 128),
                'pan_end':        getattr(clip, 'pan_end', 128),
                'tilt_end':       getattr(clip, 'tilt_end', 128),
                'move_effect':    getattr(clip, 'move_effect', None),
                'move_speed':     getattr(clip, 'move_speed', 0.5),
                'move_amplitude': getattr(clip, 'move_amplitude', 60),
            })
        return d

    def _save_sequence_no_close(self):
        """Sauvegarde seq.sequences sans fermer l'éditeur (modif inline d'un clip)."""
        all_clips = [self._clip_to_dict(clip, track)
                     for track in self.tracks for clip in track.clips]
        self.main_window.seq.sequences[self.media_row] = {
            'clips': all_clips,
            'duration': self.media_duration,
            'waveform': [round(x, 3) for x in self.track_waveform.waveform_data] if self.track_waveform.waveform_data else None
        }
        self.main_window.seq.is_dirty = True

    def save_sequence(self):
        """Sauvegarde la sequence au format .tui avec effets et bicolore"""
        all_clips = [self._clip_to_dict(clip, track)
                     for track in self.tracks for clip in track.clips]

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
                combo.addItem(tr("tle_play_light"))
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

        # MÊME writer que la sauvegarde .tui/autosave (_clip_to_dict) : sinon les
        # clips de séquence (memory_ref) et de position (position_preset_idx)
        # perdaient leur nature à l'export et revenaient en blocs couleur noirs.
        all_clips = [self._clip_to_dict(clip, track)
                     for track in self.tracks for clip in track.clips]

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
            clip.xfade             = clip_data.get('xfade', 0)
            clip.effect            = clip_data.get('effect')
            clip.effect_speed      = clip_data.get('effect_speed', 50)
            clip.effect_layers     = clip_data.get('effect_layers', [])
            clip.effect_play_mode  = clip_data.get('effect_play_mode', 'loop')
            clip.effect_duration   = clip_data.get('effect_duration', 0)
            clip.effect_name       = clip_data.get('effect_name', '')
            clip.effect_type       = clip_data.get('effect_type', '')
            # ⚠️ effect_target_groups était OUBLIÉ ici → les groupes cible des
            # effets étaient perdus à l'import, et tous les effets retombaient sur
            # « tous les groupes » (couleur qui déborde sur les lyres, etc.).
            clip.effect_target_groups = clip_data.get('effect_target_groups', [])
            clip.strobe_speed      = clip_data.get('strobe_speed', 0)
            if clip_data.get('color2'):
                clip.color2 = QColor(clip_data['color2'])
            # Clip de séquence mémoire / position lyre / mouvement pan-tilt
            if clip_data.get('memory_ref'):
                clip.memory_ref   = tuple(clip_data['memory_ref'])
                clip.memory_label = clip_data.get('memory_label', '')
                clip.cue_index    = clip_data.get('cue_index')
            if clip_data.get('position_preset_idx') is not None:
                clip.position_preset_idx  = clip_data['position_preset_idx']
                clip.position_preset_name = clip_data.get('position_preset_name', '')
            if clip_data.get('gobo_dmx') is not None:
                clip.gobo_dmx      = clip_data['gobo_dmx']
                clip.gobo_name     = clip_data.get('gobo_name', '')
                clip.gobo_rotation = clip_data.get('gobo_rotation', 0)
            for _a in ('pan_start', 'tilt_start', 'pan_end', 'tilt_end',
                       'move_effect', 'move_speed', 'move_amplitude'):
                if _a in clip_data:
                    setattr(clip, _a, clip_data[_a])

        for track in self.tracks:
            track.update()

        self.save_state()
        self._save_sequence_no_close()   # persiste dans seq.sequences (restitution)
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
            self.save_state()

    def duplicate_group_track(self):
        """Outil Édition : dupliquer TOUT le contenu d'une piste de groupe sur
        une autre (ex. copier tout ce qui est sur A vers B)."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                       QLabel, QComboBox, QPushButton)
        group_tracks = [t for t in self.tracks
                        if not (getattr(t, 'is_effect_track', False)
                                or getattr(t, 'is_sequence_track', False)
                                or getattr(t, 'is_position_track', False)
                                or getattr(t, 'is_gobo_track', False)
                                or t.name == "Audio")]
        names = [t.name for t in group_tracks]
        if len(names) < 2:
            QMessageBox.information(self, tr("tle_duplicate"),
                tr("tle_need_two_tracks"))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("te2_dup_track"))
        dlg.setStyleSheet(
            "QDialog{background:#1a1a1a;} QLabel{color:#ddd;font-size:13px;} "
            "QComboBox{background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:5px;padding:6px 10px;} "
            "QComboBox QAbstractItemView{background:#2a2a2a;color:#fff;selection-background-color:#00d4ff;} "
            "QPushButton{background:#2a2a2a;color:#fff;border:1px solid #444;border-radius:6px;padding:8px 18px;} "
            "QPushButton:hover{border-color:#00d4ff;}")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(22, 20, 22, 18); v.setSpacing(10)
        v.addWidget(QLabel(tr("te2_copy_from")))
        src_cb = ComboSansMolette(); src_cb.addItems(names); v.addWidget(src_cb)
        v.addWidget(QLabel(tr("te2_copy_to")))
        dst_cb = ComboSansMolette(); dst_cb.addItems(names)
        dst_cb.setCurrentIndex(1)
        v.addWidget(dst_cb)
        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton(tr("tle_cancel")); ok = QPushButton(tr("tle_duplicate"))
        cancel.clicked.connect(dlg.reject); ok.clicked.connect(dlg.accept)
        row.addWidget(cancel); row.addWidget(ok); v.addLayout(row)

        if dlg.exec() != QDialog.Accepted:
            return
        self._do_duplicate_track(src_cb.currentText(), dst_cb.currentText())

    def _do_duplicate_track(self, src_name, dst_name):
        """Copie tous les clips de la piste src_name vers dst_name (remplace)."""
        if src_name == dst_name:
            QMessageBox.information(self, tr("tle_duplicate"), tr("tle_pick_two_tracks"))
            return
        src = self.track_map.get(src_name)
        dst = self.track_map.get(dst_name)
        if not src or not dst:
            return
        if dst.clips:
            if QMessageBox.question(self, tr("tle_replace_q"),
                    tr("tle_f_track_not_empty", dst_name=dst_name, a0=len(dst.clips), src_name=src_name),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        self.save_state()
        dst.clips.clear()
        dst.selected_clips.clear()
        for c in src.clips:
            dst.clips.append(src._clone_clip(c, dst))
        dst.update()

    # Couleur claire commune à toutes les icônes SVG du header
    _ICON_COL = "#e0e0e0"

    def _svg_icon(self, inner):
        """Rend un fragment SVG (repère viewBox 0 0 24 24) en QIcon net.
        Rendu robuste : pixmap simple 48px + rectangle cible explicite. PAS de
        setDevicePixelRatio (sinon l'icône n'occupe qu'un quart et s'affiche mutilée)."""
        from PySide6.QtGui import QIcon
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QByteArray, QRectF
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{inner}</svg>'
        pix = QPixmap(48, 48)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p, QRectF(0, 0, 48, 48))
        p.end()
        return QIcon(pix)

    def _make_shift_icon(self, direction):
        """Icône de décalage façon Premiere Pro : un bord de bloc en pointillés
        + une flèche pleine dans le sens du décalage. direction = 'left' | 'right'."""
        col = self._ICON_COL
        if direction == 'right':
            inner = (
                f'<line x1="4.5" y1="5.5" x2="4.5" y2="18.5" stroke="{col}" stroke-width="2.8" '
                f'stroke-dasharray="3 3.2" stroke-linecap="round"/>'
                f'<line x1="9" y1="12" x2="15.5" y2="12" stroke="{col}" stroke-width="3" stroke-linecap="round"/>'
                f'<path d="M14 6.5 L22 12 L14 17.5 Z" fill="{col}"/>'
            )
        else:
            inner = (
                f'<line x1="19.5" y1="5.5" x2="19.5" y2="18.5" stroke="{col}" stroke-width="2.8" '
                f'stroke-dasharray="3 3.2" stroke-linecap="round"/>'
                f'<line x1="15" y1="12" x2="8.5" y2="12" stroke="{col}" stroke-width="3" stroke-linecap="round"/>'
                f'<path d="M10 6.5 L2 12 L10 17.5 Z" fill="{col}"/>'
            )
        return self._svg_icon(inner)

    def _icon_undo(self):
        """Flèche de retour arrière (undo)."""
        c = self._ICON_COL
        return self._svg_icon(
            f'<path fill="{c}" d="M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62'
            f'c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78'
            f'C21.08 11.03 17.15 8 12.5 8z"/>'
        )

    def _icon_cut(self):
        """Ciseaux (outil couper)."""
        c = self._ICON_COL
        return self._svg_icon(
            f'<path fill="{c}" d="M9.64 7.64c.23-.5.36-1.05.36-1.64 0-2.21-1.79-4-4-4'
            f'S2 3.79 2 6s1.79 4 4 4c.59 0 1.14-.13 1.64-.36L10 12l-2.36 2.36'
            f'C7.14 14.13 6.59 14 6 14c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4'
            f'c0-.59-.13-1.14-.36-1.64L12 14l7 7h3v-1L9.64 7.64zM6 8c-1.1 0-2-.89-2-2'
            f's.9-2 2-2 2 .89 2 2-.9 2-2 2zm0 12c-1.1 0-2-.89-2-2s.9-2 2-2 2 .89 2 2'
            f'-.9 2-2 2zm6-7.5c-.28 0-.5-.22-.5-.5s.22-.5.5-.5.5.22.5.5-.22.5-.5.5z'
            f'M19 3l-6 6 2 2 7-7V3z"/>'
        )

    # Loupe Material (base commune) — seul le dernier sous-tracé (+ ou −) diffère
    _ZOOM_BASE = ('M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3'
                  'S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99'
                  'L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5'
                  ' 11.99 14 9.5 14z')

    def _icon_zoom(self, plus):
        """Loupe avec + (zoom avant) ou − (zoom arrière)."""
        c = self._ICON_COL
        sign = 'M9.5 7H9v2H7v1h2v2h1v-2h2V9h-2z' if plus else 'M7 9h5v1H7z'
        return self._svg_icon(f'<path fill="{c}" d="{self._ZOOM_BASE}{sign}"/>')

    def _make_labeled_stepper(self, caption, on_minus, on_plus, val_width=52, tip=""):
        """Colonne verticale : petit libellé au-dessus + pavé arrondi [−  valeur  +].
        Cohérent avec les boutons du header. Renvoie (colonne_widget, value_label)."""
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame
        PILL_H = 30
        col = QWidget()
        cv = QVBoxLayout(col)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(2)

        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignCenter)
        cap.setStyleSheet("color:#888; font-size:9px; font-weight:bold; letter-spacing:1.5px; border:none;")
        cv.addWidget(cap)

        pill = QFrame()
        pill.setFixedHeight(PILL_H)
        if tip:
            pill.setToolTip(tip)
        pill.setStyleSheet("QFrame { background:#1e1e1e; border:1px solid #3a3a3a; border-radius:6px; }")
        pl = QHBoxLayout(pill)
        pl.setContentsMargins(3, 0, 3, 0)
        pl.setSpacing(0)

        step_ss = (
            "QPushButton { background:transparent; color:#bbb; border:none;"
            " font-size:18px; font-weight:bold; }"
            "QPushButton:hover { color:#00d4ff; }"
            "QPushButton:pressed { color:#0077bb; }"
        )
        bm = QPushButton("−")
        bm.setFixedSize(24, PILL_H - 2)
        bm.setFocusPolicy(Qt.NoFocus)
        bm.setAutoRepeat(True)
        bm.setStyleSheet(step_ss)
        bm.clicked.connect(on_minus)
        pl.addWidget(bm)

        val = QLabel()
        val.setAlignment(Qt.AlignCenter)
        val.setFixedWidth(val_width)
        val.setStyleSheet("color:#e0e0e0; font-size:13px; font-weight:bold;"
                          " border:none; background:transparent;")
        pl.addWidget(val)

        bp = QPushButton("+")
        bp.setFixedSize(24, PILL_H - 2)
        bp.setFocusPolicy(Qt.NoFocus)
        bp.setAutoRepeat(True)
        bp.setStyleSheet(step_ss)
        bp.clicked.connect(on_plus)
        pl.addWidget(bp)

        cv.addWidget(pill)
        return col, val

    def _shift_step_ms(self):
        """Pas de décalage selon les modificateurs : Ctrl=1s, Shift=10ms, sinon 100ms."""
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ControlModifier:
            return 1000
        if mods & Qt.ShiftModifier:
            return 10
        return 100

    def _shift_all_left(self):
        self.shift_all_clips(-self._shift_step_ms())

    def _shift_all_right(self):
        self.shift_all_clips(self._shift_step_ms())

    def shift_all_clips(self, delta_ms):
        """Décale des clips de delta_ms (gauche<0 / droite>0).
        Cible : les clips SÉLECTIONNÉS s'il y en a, sinon TOUS les clips.
        Préserve l'espacement relatif et borne le résultat dans [0, durée totale]."""
        selected = [c for t in self.tracks for c in getattr(t, 'selected_clips', [])]
        target_clips = selected if selected else [c for t in self.tracks for c in t.clips]
        if not target_clips:
            return
        total       = self.tracks[0].total_duration if self.tracks else 0
        earliest    = min(c.start_time for c in target_clips)
        latest_end  = max(c.start_time + c.duration for c in target_clips)
        if delta_ms < 0:
            # Ne pas passer sous 0 : on limite au décalage gauche possible
            delta_ms = -min(-delta_ms, earliest)
        else:
            # Ne pas dépasser la fin du média
            delta_ms = min(delta_ms, max(0, total - latest_end))
        if delta_ms == 0:
            return
        for clip in target_clips:
            clip.start_time += delta_ms
        for track in self.tracks:
            track.update()
        self.save_state()
        _scope = "sélection" if selected else "global"
        print(f"↔️ Décalage {_scope} de {delta_ms} ms ({len(target_clips)} clips)")

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

        color_combo = ComboSansMolette()
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
            if (getattr(track, 'is_sequence_track', False) or getattr(track, 'is_position_track', False)
                    or getattr(track, 'is_gobo_track', False)):
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

    def eventFilter(self, obj, event):
        """Intercepte wheel et touches flèches sur le QScrollArea."""
        from PySide6.QtCore import QEvent
        if obj in (self.tracks_scroll, self.tracks_scroll.viewport()):
            if event.type() == QEvent.Wheel:
                self._handle_wheel(event)
                return True
            if event.type() == QEvent.KeyPress:
                self.keyPressEvent(event)
                return True
        return super().eventFilter(obj, event)

    def _handle_wheel(self, event):
        """Scroll adapté trackpad ET souris :
        - Shift            → zoom
        - Ctrl             → scroll horizontal (temps) — secours molette souris
        - geste vertical   → scroll vertical (pistes)   [angleDelta().y()]
        - geste horizontal → scroll horizontal (temps)  [angleDelta().x()]
        """
        dx = event.angleDelta().x()
        dy = event.angleDelta().y()

        if event.modifiers() & Qt.ShiftModifier:
            if dy > 0:
                self.zoom_in()
            elif dy < 0:
                self.zoom_out()
            return

        if event.modifiers() & Qt.ControlModifier:
            # Molette souris (axe Y seul) → défiler le temps volontairement
            sbh = self.tracks_scroll.horizontalScrollBar()
            sbh.setValue(sbh.value() - (dy or dx))
            return

        # Sans modificateur : axes naturels (le trackpad fournit x ET/OU y)
        if dx:
            sbh = self.tracks_scroll.horizontalScrollBar()
            sbh.setValue(sbh.value() - dx)
        if dy:
            sbv = self.tracks_scroll.verticalScrollBar()
            sbv.setValue(sbv.value() - dy)

    def wheelEvent(self, event):
        """Shift=Zoom | Ctrl=horizontal | geste vertical=vertical | horizontal=temps"""
        self._handle_wheel(event)
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
            pdf = PlanDeFeu(self.main_window.projectors, main_window=self.main_window,
                            show_toolbar=False, interactive=True)
            pdf._menu_at_cursor = True   # menu contextuel au curseur (plan embarqué)
            pdf._allow_quick_effects = False   # pas d'effets rapides en REC Lumière
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
        elif event.key() == Qt.Key_P:
            # Touche P = Mode PAINT
            self.paint_btn.setChecked(not self.paint_btn.isChecked())
            self.toggle_paint_mode()
            event.accept()
            return
        elif event.key() == Qt.Key_Escape:
            # Echap = Desactiver mode cut/paint et deselectionner
            if self.cut_mode:
                self.cut_btn.setChecked(False)
                self.toggle_cut_mode()
            if self.paint_mode:
                self.paint_btn.setChecked(False)
                self.toggle_paint_mode()
            self.clear_all_selections()
            event.accept()
            return
        elif event.key() == Qt.Key_Left:
            # Ctrl+← = -30s, ← = -5s
            delta = -30000 if event.modifiers() & Qt.ControlModifier else -5000
            self.seek_relative(delta)
            event.accept()
            return
        elif event.key() == Qt.Key_Right:
            # Ctrl+→ = +30s, → = +5s
            delta = 30000 if event.modifiers() & Qt.ControlModifier else 5000
            self.seek_relative(delta)
            event.accept()
            return
        elif event.key() == Qt.Key_Up:
            sb = self.tracks_scroll.verticalScrollBar()
            sb.setValue(sb.value() - 80)
            event.accept()
            return
        elif event.key() == Qt.Key_Down:
            sb = self.tracks_scroll.verticalScrollBar()
            sb.setValue(sb.value() + 80)
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
                    'xfade': getattr(clip, 'xfade', 0),
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
            clip.xfade = item.get('xfade', 0)
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
                    'xfade': getattr(clip, 'xfade', 0),
                    'effect': clip.effect,
                    'effect_speed': clip.effect_speed,
                    'effect_layers': getattr(clip, 'effect_layers', []),
                    'effect_play_mode': getattr(clip, 'effect_play_mode', 'loop'),
                    'effect_duration':  getattr(clip, 'effect_duration', 0),
                    'effect_name':         getattr(clip, 'effect_name', ''),
                    'effect_type':         getattr(clip, 'effect_type', ''),
                    'effect_target_groups': getattr(clip, 'effect_target_groups', []),
                    # Pan/Tilt + mouvement (lyres)
                    'pan_start':  getattr(clip, 'pan_start', 128),
                    'tilt_start': getattr(clip, 'tilt_start', 128),
                    'pan_end':    getattr(clip, 'pan_end', 128),
                    'tilt_end':   getattr(clip, 'tilt_end', 128),
                    'move_effect':    getattr(clip, 'move_effect', None),
                    'move_speed':     getattr(clip, 'move_speed', 0.5),
                    'move_amplitude': getattr(clip, 'move_amplitude', 60),
                    # Stroboscope
                    'strobe_speed': getattr(clip, 'strobe_speed', 0),
                    # Mémoire AKAI (cue) — sinon l'undo la transforme en couleur neutre
                    'memory_ref':   list(clip.memory_ref) if getattr(clip, 'memory_ref', None) else None,
                    'memory_label': getattr(clip, 'memory_label', ''),
                    'cue_index':    getattr(clip, 'cue_index', None),
                    # Position lyre
                    'position_preset_idx':  getattr(clip, 'position_preset_idx', None),
                    'position_preset_name': getattr(clip, 'position_preset_name', ''),
                    # Gobo
                    'gobo_dmx':      getattr(clip, 'gobo_dmx', None),
                    'gobo_name':     getattr(clip, 'gobo_name', ''),
                    'gobo_rotation': getattr(clip, 'gobo_rotation', 0),
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
                clip.xfade = clip_data.get('xfade', 0)
                clip.effect = clip_data.get('effect')
                clip.effect_speed = clip_data.get('effect_speed', 50)
                clip.effect_layers    = clip_data.get('effect_layers', [])
                clip.effect_play_mode = clip_data.get('effect_play_mode', 'loop')
                clip.effect_duration  = clip_data.get('effect_duration', 0)
                clip.effect_name      = clip_data.get('effect_name', '')
                clip.effect_type      = clip_data.get('effect_type', '')
                clip.effect_target_groups = clip_data.get('effect_target_groups', [])
                # Pan/Tilt + mouvement (lyres)
                clip.pan_start  = clip_data.get('pan_start', 128)
                clip.tilt_start = clip_data.get('tilt_start', 128)
                clip.pan_end    = clip_data.get('pan_end', 128)
                clip.tilt_end   = clip_data.get('tilt_end', 128)
                clip.move_effect    = clip_data.get('move_effect', None)
                clip.move_speed     = clip_data.get('move_speed', 0.5)
                clip.move_amplitude = clip_data.get('move_amplitude', 60)
                # Stroboscope
                clip.strobe_speed = clip_data.get('strobe_speed', 0)
                # Mémoire AKAI (cue) — restaure l'identité du clip mémoire
                if clip_data.get('memory_ref'):
                    clip.memory_ref   = tuple(clip_data['memory_ref'])
                    clip.memory_label = clip_data.get('memory_label', '')
                    clip.cue_index    = clip_data.get('cue_index', None)
                # Position lyre
                if clip_data.get('position_preset_idx') is not None:
                    clip.position_preset_idx  = clip_data['position_preset_idx']
                    clip.position_preset_name = clip_data.get('position_preset_name', '')
                if clip_data.get('gobo_dmx') is not None:
                    clip.gobo_dmx      = clip_data['gobo_dmx']
                    clip.gobo_name     = clip_data.get('gobo_name', '')
                    clip.gobo_rotation = clip_data.get('gobo_rotation', 0)

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
            if (not getattr(track, 'is_sequence_track', False)
                    and not getattr(track, 'is_position_track', False)
                    and not getattr(track, 'is_gobo_track', False)):
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

    def toggle_paint_mode(self):
        """Active/desactive le mode PAINT (pinceau sur la timeline)"""
        self.paint_mode = not self.paint_mode

        self._update_paint_hint()

        if self.paint_mode:
            self.setCursor(Qt.CrossCursor)
            for track in self.tracks:
                track.setCursor(Qt.CrossCursor)
            self.track_waveform.setCursor(Qt.CrossCursor)
            # Desactiver cut si actif
            if self.cut_mode:
                self.cut_btn.setChecked(False)
                self.cut_mode = False
                for track in self.tracks:
                    track.setCursor(Qt.CrossCursor)
        else:
            self.paint_brush = None
            self.setCursor(Qt.ArrowCursor)
            for track in self.tracks:
                track.setCursor(Qt.ArrowCursor)
            self.track_waveform.setCursor(Qt.ArrowCursor)
            for item in self._library._safe_items():
                item._is_paint_active = False
                try: item.update()
                except RuntimeError: pass

    @staticmethod
    def _paint_brush_name(brush):
        """Nom lisible du pinceau actif (pour l'info-bulle « bloqué »)."""
        if not brush:
            return ""
        t = brush.get("type")
        if t == "mem":
            return brush.get("label") or "Mémoire"
        if t == "effect":
            return (brush.get("eff") or {}).get("name") or "Effet"
        if t == "bicolor":
            return "Bicouleur"
        return "Couleur"

    def _update_paint_hint(self):
        """Affiche/masque l'info-bulle de statut du mode « bloquer » (peinture)."""
        if not hasattr(self, '_paint_hint'):
            return
        brush = getattr(self, 'paint_brush', None)
        if getattr(self, 'paint_mode', False) and brush:
            name = self._paint_brush_name(brush)
            fem = brush.get("type") in ("color", "bicolor")   # accord grammatical
            bloq = "bloquée" if fem else "bloqué"
            self._paint_hint.setText(
                tr("tle_f_locked_track", name=name, bloq=bloq))
            self._paint_hint.setVisible(True)
        else:
            self._paint_hint.setVisible(False)

    def _on_escape(self):
        """Échap : sort du mode « bloquer » (peinture) / coupe, puis déselectionne.
        Ne ferme jamais l'éditeur (comportement historique)."""
        if getattr(self, 'cut_mode', False):
            if hasattr(self, 'cut_btn'):
                self.cut_btn.setChecked(False)
            self.toggle_cut_mode()
        if getattr(self, 'paint_mode', False):
            if hasattr(self, 'paint_btn'):
                self.paint_btn.setChecked(False)
            self.toggle_paint_mode()
        self.clear_all_selections()

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
            if (not getattr(track, 'is_sequence_track', False)
                    and not getattr(track, 'is_position_track', False)
                    and not getattr(track, 'is_gobo_track', False)):
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
            if (not getattr(track, 'is_sequence_track', False)
                    and not getattr(track, 'is_position_track', False)
                    and not getattr(track, 'is_gobo_track', False)):
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

    def _restore_original_sequence(self):
        """Remet seq.sequences dans l'état d'avant l'ouverture de l'éditeur.

        Contrepartie des écritures inline de _save_sequence_no_close : sans ça,
        « Fermer sans sauvegarder » laissait la modification en place, et un
        enregistrement ultérieur du show l'écrivait dans le .tui.
        """
        seq = self.main_window.seq
        cur = seq.sequences.get(self.media_row)
        wf = cur.get('waveform') if isinstance(cur, dict) else None

        if self._orig_sequence is None:
            # Aucune séquence avant l'ouverture : tout ce qui a été créé pendant
            # la session est abandonné, le média redevient sans REC Lumière.
            seq.sequences.pop(self.media_row, None)
        else:
            restored = dict(self._orig_sequence)
            if wf and not restored.get('waveform'):
                restored['waveform'] = wf   # analyse faite pendant la session
            seq.sequences[self.media_row] = restored

        # Ne pas « nettoyer » un show qui était déjà modifié avant l'ouverture
        if not self._orig_is_dirty:
            seq.is_dirty = False

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
            self._restore_original_sequence()   # abandonner les écritures inline

        self.playback_timer.stop()
        if self.preview_player is not None:
            self.preview_player.stop()
        # Deconnecter tous les signaux du player principal pour eviter
        # que le timer de preview continue de s'activer apres fermeture
        try:
            self.main_window.player.playbackStateChanged.disconnect(self._on_main_player_state_changed)
        except Exception:
            pass
        self.reject()
