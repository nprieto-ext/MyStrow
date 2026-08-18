"""
Fenêtre de réglage IA Lumière d'un média — MyStrow

Ouverte depuis la colonne DMX (choix « IA Lumière ») ou par un clic sur le carré
de couleur de la ligne. Elle règle l'`IASettings` de CETTE ligne.

── Sur l'aspect ──────────────────────────────────────────────────────────────
La première version réutilisait les tuiles du panneau LIVE (`_ColorTile`,
`_MovTile`). Elles peignent leur violet EN DUR (#cc88ff, #6633bb, halo
180,100,255), et comme le panneau LIVE ne doit pas bouger, il n'y avait pas
moyen de les calmer sans le toucher. D'où des tuiles réécrites ici : même
principe, mais une seule couleur d'accent — le bleu du badge « IA » de la
colonne DMX (`Sequencer._SS_BTN`), pour qu'on retrouve la même identité entre
le bouton sur lequel on clique et la fenêtre qui s'ouvre.

── Sur ce qui a été retiré ───────────────────────────────────────────────────
Le panneau portait douze réglages ; il en porte sept.
  · « Passage » ne servait qu'à un effet spécial qui n'est plus proposé ici.
  · Les deux « Tenue » (couleur et mouvement) portaient le même nom pour deux
    choses différentes dans la même fenêtre. Fusionnés en un seul CHANGEMENT
    qui pilote les deux : c'est de toute façon le même geste musical.
  · Le stroboscope se réglait en deux endroits — trois boutons pour le strobe
    automatique, cinq pour l'effet tenu — alors que l'un conditionnait l'autre.
    Un seul choix à quatre entrées les remplace.
"""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor, QRadialGradient
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QSlider, QFrame, QWidget,
)


# ── Palette ──────────────────────────────────────────────────────────────────
# Un seul accent, repris du badge « IA » de la colonne DMX. Tout le reste est
# neutre : c'est ce qui permet de lire la fenêtre d'un coup d'œil au lieu de
# chercher l'information au milieu du violet.
_FOND      = "#141414"
_ACCENT    = "#6aadff"
_ACCENT_BG = "#0d1f3a"
_ACCENT_BD = "#2a5090"
_TEXTE     = "#dcdcdc"
_TEXTE_DIM = "#8a8a8a"
_TITRE     = "#9a9a9a"
_BORDURE   = "#282828"

_DIALOG_CSS = f"""
    QDialog {{ background: {_FOND}; }}
    QLabel  {{ color: {_TEXTE}; border: none; background: transparent; }}
    QSlider::groove:horizontal {{
        background: #202020; height: 4px; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{ background: {_ACCENT_BD}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {_ACCENT}; width: 12px; height: 12px;
        margin: -5px 0; border-radius: 6px;
    }}
    QSlider::handle:horizontal:hover {{ background: #9ac8ff; }}
"""

_BTN_ON = (f"QPushButton {{ background:{_ACCENT_BG}; color:{_ACCENT};"
           f" border:1px solid {_ACCENT_BD}; border-radius:4px;"
           f" font-size:11px; font-weight:bold; padding:5px 10px; }}")
_BTN_OFF = (f"QPushButton {{ background:#1a1a1a; color:{_TEXTE_DIM};"
            f" border:1px solid {_BORDURE}; border-radius:4px;"
            f" font-size:11px; padding:5px 10px; }}"
            f"QPushButton:hover {{ color:{_TEXTE}; border-color:#3a3a3a; }}")


class _Pastille(QWidget):
    """Pastille de couleur — pleine, bicolore, ou « AUTO » (l'IA choisit).

    Deux états seulement : dans la palette, ou hors palette. La tuile du panneau
    LIVE en distinguait un troisième (« en cours de lecture ») avec un halo — ici
    la fenêtre sert à préparer, pas à suivre le direct, et ce troisième état
    n'apportait qu'une couleur de plus à l'écran.
    """

    D = 30   # diamètre du disque

    def __init__(self, cle, c1, c2, libelle, on_clic, parent=None):
        super().__init__(parent)
        self._cle   = cle
        self._c1    = QColor(c1) if c1 else None
        self._c2    = QColor(c2) if c2 else None
        self._lbl   = libelle
        self._actif = False
        self._joue  = False
        self._clic  = on_clic
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.D + 12, self.D + 18)
        self.setToolTip(libelle)

    def set_etat(self, actif, joue=False):
        if (actif, joue) != (self._actif, self._joue):
            self._actif, self._joue = actif, joue
            self.update()

    def mousePressEvent(self, _):
        self._clic(self._cle)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, r = self.width() // 2, self.D // 2
        cy = r + 3

        if self._joue:
            halo = QRadialGradient(cx, cy, r + 5)
            halo.setColorAt(0.0, QColor(106, 173, 255, 70))
            halo.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(halo); p.setPen(Qt.NoPen)
            p.drawEllipse(cx - r - 5, cy - r - 5, (r + 5) * 2, (r + 5) * 2)

        disque = QPainterPath()
        disque.addEllipse(cx - r, cy - r, self.D, self.D)
        p.setClipPath(disque)
        if self._c1 is None:
            p.fillPath(disque, QColor("#101820"))
        elif self._c2 is None:
            p.fillPath(disque, self._c1)
        else:
            gauche = QPainterPath(); gauche.addRect(cx - r, cy - r, r, self.D)
            p.fillPath(gauche.intersected(disque), self._c1)
            droite = QPainterPath(); droite.addRect(cx, cy - r, r, self.D)
            p.fillPath(droite.intersected(disque), self._c2)
        p.setClipping(False)

        if self._joue:
            anneau = QPen(QColor(_ACCENT), 2.0)
        elif self._actif:
            anneau = QPen(QColor("#e8e8e8"), 2.0)
        elif self._c1 is None:
            anneau = QPen(QColor(_ACCENT_BD), 1.0)
        else:
            anneau = QPen(QColor("#303030"), 1.0)
        p.setPen(anneau); p.setBrush(Qt.NoBrush)
        p.drawEllipse(cx - r + 1, cy - r + 1, self.D - 2, self.D - 2)

        if self._c1 is None:
            p.setPen(QPen(QColor(_ACCENT if (self._actif or self._joue) else _TEXTE_DIM)))
            f = p.font(); f.setPointSize(7); f.setBold(True); p.setFont(f)
            p.drawText(QPoint(cx - 11, cy + 3), "AUTO")
        elif self._actif or self._joue:
            # Coche : lisible sur une pastille claire comme sur une sombre.
            clair = self._c1.lightness() > 130
            p.setPen(QPen(QColor("#101010" if clair else "#ffffff"), 2.0,
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            ox, oy = cx - 5, cy - 2
            p.drawLine(ox, oy + 4, ox + 3, oy + 7)
            p.drawLine(ox + 3, oy + 7, ox + 9, oy)


class _Figure(QFrame):
    """Tuile de figure de mouvement — glyphe + nom, deux états."""

    def __init__(self, cle, glyphe, libelle, on_clic, parent=None):
        super().__init__(parent)
        self._cle, self._clic = cle, on_clic
        self._actif = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(46)

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 5, 4, 5)
        v.setSpacing(1)
        self._g = QLabel(glyphe); self._g.setAlignment(Qt.AlignCenter)
        self._t = QLabel(libelle); self._t.setAlignment(Qt.AlignCenter)
        v.addWidget(self._g); v.addWidget(self._t)
        self.set_etat(False)

    def mousePressEvent(self, _):
        self._clic(self._cle)

    def set_etat(self, actif):
        self._actif = actif
        if actif:
            self.setStyleSheet(f"_Figure {{ background:{_ACCENT_BG};"
                               f" border:1px solid {_ACCENT_BD}; border-radius:5px; }}")
            self._g.setStyleSheet(f"font-size:14px; color:{_ACCENT};"
                                  " background:transparent; border:none;")
            self._t.setStyleSheet(f"font-size:8px; font-weight:bold; color:{_ACCENT};"
                                  " background:transparent; border:none;")
        else:
            self.setStyleSheet(f"_Figure {{ background:#1a1a1a;"
                               f" border:1px solid {_BORDURE}; border-radius:5px; }}")
            self._g.setStyleSheet(f"font-size:14px; color:{_TEXTE_DIM};"
                                  " background:transparent; border:none;")
            self._t.setStyleSheet(f"font-size:8px; font-weight:bold; color:#6a6a6a;"
                                  " background:transparent; border:none;")


class IASettingsDialog(QDialog):
    """Réglages IA d'un média. Modifie une COPIE : annuler ne laisse aucune trace."""

    # Quatre entrées qui remplacent les deux anciens réglages de strobe.
    # (libellé, strob_none, active_special)
    _STROBES = (
        ("Aucun",           True,  None),
        ("Auto",            False, None),
        ("Continu",         False, 'strobe'),
        ("Continu couleur", False, 'strobe_couleur'),
    )

    def __init__(self, settings, titre_media="", parent=None):
        super().__init__(parent)
        # On édite une copie et on ne la recopie dans l'original qu'à
        # « Appliquer » : le moteur lit le préréglage en direct pendant la
        # lecture, donc une modification annulée s'entendrait quand même.
        self._s = settings.copy()
        self.setWindowTitle("IA Lumière — réglages du média")
        self.setMinimumSize(720, 470)
        self.setStyleSheet(_DIALOG_CSS)

        from sequencer import LiveModePanel
        self._COULEURS = LiveModePanel._COLOR_TILES
        self._FIGURES  = LiveModePanel._MOVEMENTS

        racine = QVBoxLayout(self)
        racine.setContentsMargins(22, 16, 22, 16)
        racine.setSpacing(0)

        entete = QLabel(titre_media or "Réglages IA de ce média")
        entete.setStyleSheet(f"font-size:13px; font-weight:bold; color:{_TEXTE};")
        entete.setWordWrap(True)
        racine.addWidget(entete)
        sous = QLabel("Ne vaut que pour ce média.")
        sous.setStyleSheet(f"color:{_TEXTE_DIM}; font-size:10px; padding-bottom:12px;")
        racine.addWidget(sous)

        colonnes = QHBoxLayout()
        colonnes.setSpacing(26)
        gauche = QVBoxLayout(); gauche.setSpacing(4)
        droite = QVBoxLayout(); droite.setSpacing(4)
        self._couleurs(gauche);   gauche.addStretch(1)
        self._lyres(droite)
        droite.addSpacing(10)
        self._ambiance(droite);   droite.addStretch(1)
        colonnes.addLayout(gauche, 0)
        colonnes.addLayout(droite, 1)
        racine.addLayout(colonnes, 1)

        racine.addSpacing(14)
        racine.addLayout(self._boutons())

    # ── Briques ──────────────────────────────────────────────────────────────

    @staticmethod
    def _titre(texte):
        lbl = QLabel(texte)
        lbl.setStyleSheet(f"font-size:9px; font-weight:bold; color:{_TITRE};"
                          " letter-spacing:1.2px; padding:2px 0 6px 0;")
        return lbl

    def _curseur(self, parent, libelle, attrs, gauche="", droite=""):
        """Curseur relié à un ou plusieurs attributs du préréglage.

        `attrs` accepte plusieurs noms : le CHANGEMENT pilote d'un seul geste la
        tenue des couleurs et celle des figures, qui n'avaient aucune raison
        d'être réglées séparément.
        """
        if isinstance(attrs, str):
            attrs = (attrs,)
        ligne = QHBoxLayout(); ligne.setSpacing(10)
        lbl = QLabel(libelle); lbl.setMinimumWidth(72)
        lbl.setStyleSheet(f"font-size:11px; color:{_TEXTE};")
        ligne.addWidget(lbl)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 100)
        sl.setValue(int(getattr(self._s, attrs[0])))
        ligne.addWidget(sl, 1)
        val = QLabel(str(sl.value())); val.setMinimumWidth(26)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val.setStyleSheet(f"font-size:11px; font-weight:bold; color:{_ACCENT};")
        ligne.addWidget(val)

        def _maj(v):
            for a in attrs:
                setattr(self._s, a, v)
            val.setText(str(v))
        sl.valueChanged.connect(_maj)
        parent.addLayout(ligne)

        if gauche or droite:
            reperes = QHBoxLayout()
            g = QLabel(gauche); d = QLabel(droite)
            for x, al in ((g, Qt.AlignLeft), (d, Qt.AlignRight)):
                x.setStyleSheet(f"color:#5e5e5e; font-size:9px;")
                x.setAlignment(al)
            reperes.addSpacing(82)
            reperes.addWidget(g); reperes.addStretch(); reperes.addWidget(d)
            reperes.addSpacing(30)
            parent.addLayout(reperes)
        parent.addSpacing(6)

    # ── Couleurs ─────────────────────────────────────────────────────────────

    def _couleurs(self, boite):
        boite.addWidget(self._titre("COULEURS"))
        self._pastilles = {}
        grille = QGridLayout(); grille.setSpacing(2)
        for i, tdef in enumerate(self._COULEURS):
            cle, c1, c2, lib = tdef[0], tdef[1], tdef[2], tdef[3]
            t = _Pastille(cle, c1, c2, lib, self._clic_couleur, self)
            t.set_etat(cle in self._s._color_tile_pool,
                       cle == self._s.current_color_tile)
            self._pastilles[cle] = t
            grille.addWidget(t, i // 5, i % 5)
        boite.addLayout(grille)
        boite.addSpacing(10)

        ligne = QHBoxLayout(); ligne.setSpacing(4)
        lbl = QLabel("À la fois")
        lbl.setStyleSheet(f"font-size:11px; color:{_TEXTE};")
        ligne.addWidget(lbl); ligne.addStretch()
        self._btn_max = {}
        for n in (1, 2, 3, 4):
            b = QPushButton(str(n)); b.setFixedSize(26, 24)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _, v=n: self._set_max(v))
            self._btn_max[n] = b
            ligne.addWidget(b)
        boite.addLayout(ligne)
        self._maj_max()
        self._aide_max = QLabel("")
        self._aide_max.setStyleSheet(f"color:#5e5e5e; font-size:9px; padding-top:2px;")
        self._aide_max.setWordWrap(True)
        boite.addWidget(self._aide_max)
        self._maj_aide_max()

    def _clic_couleur(self, cle):
        pool = self._s._color_tile_pool
        # À 1 couleur, seule la couleur « en cours » sort : le clic sert donc à
        # DÉSIGNER laquelle, pas à cocher un pool qui ne joue plus.
        if self._s._color_max == 1:
            pool.add(cle)
            self._s._current_color = cle
        elif cle in pool:
            if len(pool) <= 1:
                return          # jamais zéro couleur : le moteur n'aurait rien à jouer
            pool.discard(cle)
            if self._s._current_color == cle:
                reste = self._s.color_tile_pool
                self._s._current_color = reste[0] if reste else 'rouge'
        else:
            pool.add(cle)
            self._s._current_color = cle
        self._rafraichir_pastilles()

    def _rafraichir_pastilles(self):
        un_seul = self._s._color_max == 1
        for cle, t in self._pastilles.items():
            joue = cle == self._s._current_color
            t.set_etat(cle in self._s._color_tile_pool, joue and un_seul)

    def _set_max(self, n):
        self._s._color_max = n
        # À 1, on ramène la couleur tenue sur la PREMIÈRE du pool : sinon c'est
        # la dernière cliquée qui resterait, ce qui n'a rien d'évident quand on
        # vient de passer de 4 à 1.
        if n == 1:
            pool = self._s.color_tile_pool
            if pool:
                self._s._current_color = pool[0]
        self._maj_max()
        self._maj_aide_max()
        self._rafraichir_pastilles()

    def _maj_max(self):
        for n, b in self._btn_max.items():
            b.setStyleSheet(_BTN_ON if n == self._s._color_max else _BTN_OFF)

    def _maj_aide_max(self):
        self._aide_max.setText(
            "Une seule couleur, tenue tout le morceau — cliquez celle qui joue."
            if self._s._color_max == 1 else
            "L'IA pioche dans la palette et change au fil du morceau.")

    # ── Lyres ────────────────────────────────────────────────────────────────

    def _lyres(self, boite):
        boite.addWidget(self._titre("LYRES"))
        self._figures = {}
        grille = QGridLayout(); grille.setSpacing(4)
        for i, (cle, glyphe, lib) in enumerate(self._FIGURES):
            t = _Figure(cle, glyphe, lib, self._clic_figure, self)
            t.set_etat(cle in self._s._movement_patterns)
            self._figures[cle] = t
            grille.addWidget(t, i // 3, i % 3)
        boite.addLayout(grille)
        boite.addSpacing(10)
        self._curseur(boite, "Vitesse",   '_movement_speed', "lent", "rapide")
        self._curseur(boite, "Amplitude", '_movement_size',  "serré", "large")

    def _clic_figure(self, cle):
        pool = self._s._movement_patterns
        if cle in pool:
            if len(pool) <= 1:
                return          # jamais zéro figure : les lyres se figeraient
            pool.discard(cle)
            if self._s._current_movement == cle:
                reste = self._s.movement_patterns
                self._s._current_movement = reste[0] if reste else 'cercle'
        else:
            pool.add(cle)
            self._s._current_movement = cle
        for k, t in self._figures.items():
            t.set_etat(k in pool)

    # ── Ambiance ─────────────────────────────────────────────────────────────

    def _ambiance(self, boite):
        boite.addWidget(self._titre("AMBIANCE"))
        self._curseur(boite, "Nervosité", '_nervosity', "posé", "nerveux")
        # Un seul CHANGEMENT pour les couleurs ET les figures : deux curseurs
        # nommés « Tenue » dans la même fenêtre ne disaient pas lequel faisait quoi.
        self._curseur(boite, "Changement", ('_color_duration', '_movement_duration'),
                      "souvent", "rarement")

        ligne = QHBoxLayout(); ligne.setSpacing(4)
        lbl = QLabel("Strobe"); lbl.setMinimumWidth(72)
        lbl.setStyleSheet(f"font-size:11px; color:{_TEXTE};")
        ligne.addWidget(lbl)
        self._btn_strobe = {}
        for libelle, _none, _spec in self._STROBES:
            b = QPushButton(libelle); b.setFixedHeight(24)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _, l=libelle: self._set_strobe(l))
            self._btn_strobe[libelle] = b
            ligne.addWidget(b, 1)
        boite.addLayout(ligne)
        aide = QLabel("Auto : l'IA strobe sur les drops. Continu : toute la durée.")
        aide.setStyleSheet(f"color:#5e5e5e; font-size:9px; padding:3px 0 0 82px;")
        aide.setWordWrap(True)
        boite.addWidget(aide)
        self._maj_strobe()

    def _set_strobe(self, libelle):
        for lib, none, spec in self._STROBES:
            if lib == libelle:
                self._s._strob_none  = none
                self._s._strob_fast  = not none
                self._s._strob_slow  = False
                self._s._active_special = spec
                break
        self._maj_strobe()

    def _strobe_courant(self) -> str:
        spec = self._s._active_special
        for lib, none, s in self._STROBES:
            if s is not None and s == spec:
                return lib
        # Un effet spécial qu'on ne propose plus (fixe blanc, passage) : on le
        # neutralise plutôt que de laisser la fenêtre afficher autre chose que
        # ce que le média va réellement jouer.
        if spec is not None:
            self._s._active_special = None
        return "Aucun" if self._s._strob_none else "Auto"

    def _maj_strobe(self):
        courant = self._strobe_courant()
        for lib, b in self._btn_strobe.items():
            b.setStyleSheet(_BTN_ON if lib == courant else _BTN_OFF)

    # ── Boutons ──────────────────────────────────────────────────────────────

    def _boutons(self):
        ligne = QHBoxLayout(); ligne.setSpacing(8)
        ligne.addStretch()
        annuler = QPushButton("Annuler")
        # ⚠️ Toutes les portions doivent être des f-strings : dans un morceau non
        # préfixé, `}}` reste littéralement `}}` et Qt rejette la feuille entière
        # (« Could not parse stylesheet ») — le bouton s'affiche alors sans style.
        annuler.setStyleSheet(
            f"QPushButton {{ background:#242424; color:{_TEXTE_DIM}; border:none;"
            f" border-radius:5px; padding:8px 20px; font-size:12px; }}"
            f"QPushButton:hover {{ background:#2e2e2e; color:{_TEXTE}; }}")
        annuler.clicked.connect(self.reject)
        ligne.addWidget(annuler)
        valider = QPushButton("Appliquer")
        valider.setStyleSheet(
            f"QPushButton {{ background:{_ACCENT_BD}; color:#fff; border:none;"
            f" border-radius:5px; padding:8px 20px; font-size:12px; font-weight:bold; }}"
            f"QPushButton:hover {{ background:#3a68b8; }}")
        valider.clicked.connect(self.accept)
        ligne.addWidget(valider)
        return ligne

    def resultat(self):
        """Préréglage édité — à ne lire qu'après un exec() accepté."""
        return self._s
