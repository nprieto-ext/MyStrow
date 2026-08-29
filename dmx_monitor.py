"""
Moniteur DMX — fenêtre de LECTURE SEULE des valeurs réellement émises.

Le DMX Tester (dmx_tester.py) écrit dans l'univers : il coupe le rendu du show
le temps de son ouverture. Ce moniteur-ci ne fait que regarder. On peut donc le
laisser ouvert pendant tout le spectacle, sur un second écran, sans rien
perturber : aucun réglage, aucun bouton qui envoie quoi que ce soit.

Ce qui est affiché, c'est `ArtNetDMX.dmx_data` — exactement le tampon que les
transports (Art-Net, ENTTEC) recopient dans leurs trames. Pas une re-simulation
à partir des projecteurs : si l'écran et le parc divergent, c'est que le
problème est APRÈS le tampon (câble, boîtier, patch du Node), et cette
distinction est toute la valeur de la fenêtre.

SAUF quand la sortie est coupée. `send_dmx_update()` ne remplit le tampon que si
la sortie est connectée ET le bouton DMX du plan de feu enclenché ; sinon
dmx_data reste à zéro pour toujours. Un moniteur tout noir laisserait alors
croire que MyStrow ne calcule rien — alors qu'il calcule très bien, il n'émet
simplement pas. Dans ce cas seulement, la fenêtre refait le calcul elle-même,
dans un tampon FANTÔME (jamais le vrai : la trame de maintien ENTTEC le lit, et
enverrait des valeurs que l'utilisateur a justement coupées), et le dit en
en-tête.
"""

from contextlib import nullcontext

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QWidget, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QPixmap

from artnet_dmx import TRANSPORT_ARTNET
from core import DMX_FRAME_MS, channel_label
from i18n import tr
from video_link import STYLE_DIALOGUE


# ── Géométrie des cellules ────────────────────────────────────────────────────
# Seuls des diviseurs de 512 sont proposés : avec 12 ou 24 colonnes, la dernière
# ligne est tronquée et on ne peut plus lire une adresse « de tête » en comptant
# les lignes, ce qui est justement l'usage du quadrillage.
COLS_CHOICES = (8, 16, 32)
CELL_MIN_W   = 46
CELL_MAX_W   = 64
CELL_H       = 30

CYAN = QColor("#00d4ff")


class _UniverseGrid(QWidget):
    """Les 512 canaux d'un univers, en quadrillage.

    Le fond (cadres + numéros de canal) est peint une fois pour toutes dans un
    QPixmap : à 40 images/seconde, redessiner 512 numéros de canal à chaque
    trame coûterait plus cher que tout le reste de l'application réunie. Seule
    la valeur, elle, est repeinte — et uniquement sur les cellules qui bougent.
    """

    def __init__(self, patch_lookup):
        super().__init__()
        self._values  = [0] * 512
        self._patched = set()          # canaux (1-512) appartenant au patch
        self._lookup  = patch_lookup   # ch (1-512) -> (nom, type) ou None
        self._hover   = -1
        self._cols    = 16
        self._cell_w  = CELL_MIN_W
        self._x0      = 0
        self._bg      = None

        self.setMouseTracking(True)
        self.setMinimumWidth(COLS_CHOICES[0] * CELL_MIN_W)
        self._relayout()

    # ── Données ──────────────────────────────────────────────────────────────

    def set_values(self, values):
        """Nouvelle trame : ne repeint que les cellules dont la valeur change."""
        prev = self._values
        for i in range(512):
            v = values[i]
            if v != prev[i]:
                prev[i] = v
                self.update(self._cell_rect(i))

    def set_patched(self, channels):
        """Canaux occupés par un projecteur — leur numéro s'affiche en cyan."""
        channels = set(channels)
        if channels != self._patched:
            self._patched = channels
            self._rebuild_bg()
            self.update()

    # ── Géométrie ────────────────────────────────────────────────────────────

    def _relayout(self):
        avail = max(1, self.width())
        cols = COLS_CHOICES[0]
        for c in COLS_CHOICES:
            if c * CELL_MIN_W <= avail:
                cols = c
        cell_w = max(CELL_MIN_W, min(CELL_MAX_W, avail // cols))
        rows = 512 // cols

        self._cols   = cols
        self._cell_w = cell_w
        # Centré : à 16 colonnes de 64 px dans une fenêtre large, le quadrillage
        # collé à gauche laisse une bande vide qu'on prend pour un bug d'affichage.
        self._x0 = max(0, (avail - cols * cell_w) // 2)
        self.setFixedHeight(rows * CELL_H)
        self._rebuild_bg()

    def _cell_rect(self, i):
        col = i % self._cols
        row = i // self._cols
        return QRect(self._x0 + col * self._cell_w, row * CELL_H,
                     self._cell_w, CELL_H)

    def _index_at(self, pos):
        col = (pos.x() - self._x0) // self._cell_w if self._cell_w else -1
        row = pos.y() // CELL_H
        if 0 <= col < self._cols and 0 <= row < 512 // self._cols:
            return int(row * self._cols + col)
        return -1

    # ── Fond figé ────────────────────────────────────────────────────────────

    def _rebuild_bg(self):
        w = max(1, self.width())
        h = max(1, 512 // self._cols * CELL_H)
        pm = QPixmap(w, h)
        pm.fill(QColor("#0f0f0f"))
        p = QPainter(pm)
        f_num = QFont("Segoe UI", 6)
        for i in range(512):
            r = self._cell_rect(i)
            p.fillRect(r.adjusted(1, 1, -1, -1), QColor("#161616"))
            p.setFont(f_num)
            p.setPen(QColor("#4d95ab") if (i + 1) in self._patched else QColor("#3a3a3a"))
            p.drawText(r.adjusted(5, 2, -4, 0), Qt.AlignLeft | Qt.AlignTop, str(i + 1))
        p.end()
        self._bg = pm

    # ── Rendu ────────────────────────────────────────────────────────────────

    def resizeEvent(self, _):
        self._relayout()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        if self._bg is not None:
            p.drawPixmap(ev.rect(), self._bg, ev.rect())

        f_val = QFont("Segoe UI", 9)
        f_val.setBold(True)
        region = ev.rect()
        for i in range(512):
            r = self._cell_rect(i)
            if not region.intersects(r):
                continue
            val = self._values[i]
            inner = r.adjusted(1, 1, -1, -1)

            if val:
                t = val / 255.0
                tint = QColor(CYAN)
                tint.setAlpha(int(18 + t * 72))
                p.fillRect(inner, tint)
                # Jauge en pied de cellule : à valeur proche, la teinte seule ne
                # se départage pas à l'œil ; la longueur, si.
                bar_w = max(1, int(t * (inner.width() - 4)))
                p.fillRect(inner.x() + 2, inner.bottom() - 2, bar_w, 2, CYAN)

            p.setFont(f_val)
            p.setPen(QColor("#ffffff") if val else QColor("#3d3d3d"))
            p.drawText(r.adjusted(0, 0, -5, -3), Qt.AlignRight | Qt.AlignBottom, str(val))

            if i == self._hover:
                pen = QPen(CYAN)
                pen.setWidth(1)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(inner.adjusted(0, 0, -1, -1))

    # ── Survol ───────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position().toPoint())
        if i == self._hover:
            return
        old, self._hover = self._hover, i
        if old >= 0:
            self.update(self._cell_rect(old))
        if i >= 0:
            self.update(self._cell_rect(i))
            info = self._lookup(i + 1)
            if info:
                nom, typ = info
                self.setToolTip(f"{tr('dmxmon_channel')} {i + 1} — {nom} · {typ}")
            else:
                self.setToolTip(f"{tr('dmxmon_channel')} {i + 1} — {tr('dmxmon_free')}")
        else:
            self.setToolTip("")

    def leaveEvent(self, _):
        if self._hover >= 0:
            old, self._hover = self._hover, -1
            self.update(self._cell_rect(old))


class DmxMonitorWindow(QDialog):
    """Fenêtre de lecture des valeurs DMX émises. Aucun réglage, par principe."""

    def __init__(self, dmx, projectors_provider, output_active_provider=None,
                 effect_speed_provider=None, parent=None):
        super().__init__(parent)
        self._dmx     = dmx
        self._projs   = projectors_provider
        # Dit si le show alimente réellement le tampon (sortie connectée ET
        # bouton DMX du plan de feu). Sans lui on ne saurait pas distinguer un
        # blackout d'une sortie coupée : les deux donnent 512 zéros.
        self._out_on  = output_active_provider
        self._fx_speed = effect_speed_provider
        self._vals    = [[0] * 512 for _ in range(4)]
        self._live    = False
        self._grids   = {}      # univers -> _UniverseGrid
        self._shown   = []      # univers actuellement affichés, dans l'ordre
        self._notes   = {}      # univers -> QLabel « où sort cet univers »
        self._patch   = {u: {} for u in range(4)}
        self._patch_tick = 0

        # Fenêtre à part entière (barre des tâches, minimisation) : elle est
        # faite pour vivre sur un second écran pendant tout le spectacle.
        self.setWindowFlag(Qt.Window, True)
        self.setWindowTitle(tr("dmxmon_title"))
        # La zone de defilement n'est pas un QDialog : sans regle explicite elle
        # sort BLANCHE au milieu du theme sombre, et les titres d'univers avec.
        self.setStyleSheet(STYLE_DIALOGUE + """
QScrollArea { background: #0f0f0f; border: none; }
QWidget#dmxmon_corps { background: #0f0f0f; }
QScrollBar:vertical { background: #0d0d0d; width: 8px; border-radius: 4px; }
QScrollBar::handle:vertical { background: #252525; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #0d0d0d; height: 8px; border-radius: 4px; }
QScrollBar::handle:horizontal { background: #252525; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
""")
        self.resize(1020, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        titre = QLabel(tr("dmxmon_header"))
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        titre.setFont(f)
        root.addWidget(titre)

        self._lbl_etat = QLabel("")
        self._lbl_etat.setWordWrap(True)
        root.addWidget(self._lbl_etat)

        self._lbl_stats = QLabel("")
        self._lbl_stats.setStyleSheet("color:#888; font-size:11px;")
        root.addWidget(self._lbl_stats)

        self._zone = QScrollArea()
        self._zone.setWidgetResizable(True)
        self._zone.setFrameShape(QFrame.NoFrame)
        self._corps = QWidget()
        self._corps.setObjectName("dmxmon_corps")
        self._corps_lay = QVBoxLayout(self._corps)
        self._corps_lay.setContentsMargins(0, 4, 0, 4)
        self._corps_lay.setSpacing(10)
        self._corps_lay.addStretch(1)
        self._zone.setWidget(self._corps)
        root.addWidget(self._zone, 1)

        # Cadence d'affichage indexée sur celle de l'envoi : rafraîchir plus
        # vite ne montrerait rien de plus, et plus lentement raterait les flashs.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._rebuild_patch()
        self._sync_universes()

    # ── Cycle de vie ─────────────────────────────────────────────────────────

    def showEvent(self, e):
        super().showEvent(e)
        self._rebuild_patch()
        self._timer.start(max(20, DMX_FRAME_MS))

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    # ── Patch ────────────────────────────────────────────────────────────────

    def _rebuild_patch(self):
        """Table canal -> (nom du projecteur, type de canal), par univers.

        Relue périodiquement : le patch peut changer pendant que la fenêtre est
        ouverte (chargement d'un show, ajout d'un appareil).
        """
        maps = {u: {} for u in range(4)}
        try:
            projs = self._projs() or []
        except Exception:
            projs = []
        for i, proj in enumerate(projs):
            key = f"{getattr(proj, 'group', '')}_{i}"
            chans = self._dmx.projector_channels.get(key)
            if not chans:
                continue
            uni = max(0, min(3, int(self._dmx.projector_universes.get(key, 0))))
            profile = self._dmx.projector_profiles.get(key) or []
            nom = getattr(proj, 'name', '') or key
            for idx, ch in enumerate(chans):
                try:
                    ch = int(ch)
                except Exception:
                    continue
                typ = channel_label(profile[idx]) if idx < len(profile) else "?"
                maps[uni][ch] = (nom, typ)
        self._patch = maps
        for uni, grid in self._grids.items():
            grid.set_patched(maps[uni].keys())

    def _lookup(self, uni, ch):
        return self._patch.get(uni, {}).get(ch)

    # ── Trame affichée ───────────────────────────────────────────────────────

    def _output_is_live(self):
        """La sortie alimente-t-elle vraiment `dmx_data` ?"""
        if not getattr(self._dmx, 'connected', False):
            return False
        try:
            return self._out_on() if self._out_on else True
        except Exception:
            return True

    def _read_frame(self):
        """Les 4 univers à afficher, plus le fait qu'ils soient émis ou non.

        Sortie active : on recopie le tampon réel — c'est la raison d'être de la
        fenêtre. Sortie coupée : le tampon est figé à zéro, on refait donc le
        calcul dans un tampon fantôme, en gardant le vrai intact.
        """
        live = self._output_is_live()
        lock = getattr(self._dmx, '_dmx_lock', None)

        if live:
            # Copie sous verrou : le tampon est écrit par le thread Qt et lu par
            # les threads ENTTEC. On travaille sur un instantané, pas sur la
            # liste vive.
            if lock is not None:
                with lock:
                    return True, [list(u) for u in self._dmx.dmx_data]
            return True, [list(u) for u in self._dmx.dmx_data]

        try:
            projs = self._projs() or []
        except Exception:
            projs = []
        try:
            speed = self._fx_speed() if self._fx_speed else 0
        except Exception:
            speed = 0

        shadow = [[0] * 512 for _ in range(4)]
        try:
            with (lock if lock is not None else nullcontext()):
                reel = self._dmx.dmx_data
                self._dmx.dmx_data = shadow
                try:
                    self._dmx._update_from_projectors_locked(projs, speed)
                finally:
                    self._dmx.dmx_data = reel
        except Exception:
            pass
        return False, shadow

    # ── Univers affichés ─────────────────────────────────────────────────────

    def _universes_in_use(self):
        """Univers qui méritent une place à l'écran.

        Toujours le premier (une fenêtre vide n'apprend rien), plus tout univers
        patché ou qui porte une valeur non nulle. On ne montre pas les quatre
        d'office : trois quadrillages de zéros noieraient le seul qui parle.
        """
        used = {0}
        for u in self._dmx.projector_universes.values():
            used.add(max(0, min(3, int(u))))
        for u in range(4):
            if any(self._vals[u]):
                used.add(u)
        return sorted(used)

    def _sortie_note(self, uni):
        """Ce que devient cet univers une fois sorti de MyStrow."""
        if self._dmx.transport != TRANSPORT_ARTNET:
            # Les boîtiers USB n'ont qu'une seule ligne DMX : seul l'univers 1
            # part réellement. Le dire évite de chercher pendant une heure
            # pourquoi le deuxième univers ne fait rien.
            return "" if uni == 0 else tr("dmxmon_usb_only")
        ports = [n + 1 for n, src in enumerate(self._dmx.output_map)
                 if src == uni]
        if not ports:
            return tr("dmxmon_not_sent")
        base = self._dmx.universe
        return tr("dmxmon_out_port").format(
            ports=", ".join(str(p) for p in ports),
            art=", ".join(str(base + p - 1) for p in ports))

    def _sync_universes(self):
        wanted = self._universes_in_use()
        if wanted == self._shown:
            for uni in wanted:
                self._notes[uni].setText(self._sortie_note(uni))
            return

        # Reconstruction complète : cela n'arrive qu'au chargement d'un show ou
        # quand un univers s'allume, pas en régime établi.
        while self._corps_lay.count():
            item = self._corps_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._grids.clear()
        self._notes = {}

        for uni in wanted:
            titre = QLabel(tr("dmxmon_universe").format(n=uni + 1))
            f = QFont()
            f.setPointSize(10)
            f.setBold(True)
            titre.setFont(f)
            titre.setStyleSheet("color:#00d4ff;")
            self._corps_lay.addWidget(titre)

            note = QLabel(self._sortie_note(uni))
            note.setStyleSheet("color:#888; font-size:11px;")
            self._corps_lay.addWidget(note)
            self._notes[uni] = note

            grid = _UniverseGrid(lambda ch, u=uni: self._lookup(u, ch))
            grid.set_patched(self._patch[uni].keys())
            self._corps_lay.addWidget(grid)
            self._grids[uni] = grid

        self._corps_lay.addStretch(1)
        self._shown = wanted

    # ── Rafraîchissement ─────────────────────────────────────────────────────

    def _tick(self):
        self._patch_tick += 1
        if self._patch_tick % 80 == 0:      # ~2 s
            self._rebuild_patch()

        self._live, self._vals = self._read_frame()
        self._sync_universes()

        actifs = 0
        for uni, grid in self._grids.items():
            vals = self._vals[uni]
            grid.set_values(vals)
            actifs += sum(1 for v in vals if v)

        # Le bandeau ne s'affiche QUE lorsque la sortie est active. L'avertir de
        # l'inverse en toutes lettres occupait deux lignes en permanence pendant
        # les réglages, alors que le titre de chaque univers dit déjà où il part.
        self._lbl_etat.setVisible(self._live)
        if self._live:
            self._lbl_etat.setStyleSheet("color:#7fdc8f; font-size:12px;")
            cible = getattr(self._dmx, 'target_ip', None) if self._dmx.transport == TRANSPORT_ARTNET \
                else getattr(self._dmx, 'com_port', None)
            self._lbl_etat.setText(tr("dmxmon_state_on").format(
                produit=self._dmx.product_name,
                cible=cible or "—"))

        self._lbl_stats.setText(tr("dmxmon_stats").format(
            actifs=actifs, fps=max(1, round(1000 / max(1, DMX_FRAME_MS)))))
