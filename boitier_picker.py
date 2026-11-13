"""
« Quel boîtier avez-vous ? » — en tête de la fenêtre Sortie DMX.

Les deux boîtiers MyStrow ont le même profilé noir : la seule différence qu'un
client voit au premier coup d'œil, c'est l'emplacement du logo.
- Logo MyStrow sur la FACE AVANT : USB NODE DMX (ElectroConcept), USB mais
  Art-Net → sortie Node, sans rien régler (pas d'adresse IP à toucher).
- Logo MyStrow sur le DESSUS : boîtier maison MS-DMY (CH32X035, ENTTEC Pro sur
  USB CDC) → sortie USB sur son port.
- Toute autre interface : l'écran complet habituel.

Les boîtiers sont dessinés (QPainter) plutôt que photographiés : sur photo ils
sont identiques, ici le logo jaune est mis en évidence là où il faut regarder.
"""

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QFont,
                           QPolygonF, QTransform, QCursor)
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame

from i18n import tr

FRONT = "front"     # USB NODE (logo sur la face avant)
TOP = "top"         # boîtier maison (logo sur le dessus)
OTHER = "other"     # autre interface

_JAUNE = QColor("#E2CE16")


class _BoxDrawing(QWidget):
    """Boîtier en perspective cavalière, logo sur la face avant ou le dessus."""

    def __init__(self, logo: str, parent=None):
        super().__init__(parent)
        self._logo = logo
        self.setFixedSize(132, 92)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._logo == OTHER:
            self._autre(p)
            return
        # Face avant carrée (XLR), corps qui fuit vers l'arrière-droite.
        fx, fy, fs = 14.0, 34.0, 50.0          # face avant
        dx, dy = 58.0, -24.0                   # profondeur
        front = QRectF(fx, fy, fs, fs)
        top = QPolygonF([QPointF(fx, fy), QPointF(fx + dx, fy + dy),
                         QPointF(fx + fs + dx, fy + dy), QPointF(fx + fs, fy)])
        side = QPolygonF([QPointF(fx + fs, fy), QPointF(fx + fs + dx, fy + dy),
                          QPointF(fx + fs + dx, fy + fs + dy), QPointF(fx + fs, fy + fs)])
        p.setPen(QPen(QColor("#4a4a4a"), 1.2))
        p.setBrush(QColor("#2b2b2b"))
        p.drawPolygon(top)
        p.setBrush(QColor("#1c1c1c"))
        p.drawPolygon(side)
        p.setBrush(QColor("#151515"))
        p.drawRoundedRect(front, 3, 3)
        # XLR + vis
        c = front.center() + QPointF(0, 5 if self._logo == FRONT else 0)
        p.setPen(QPen(QColor("#555"), 1.5))
        p.setBrush(QColor("#0b0b0b"))
        p.drawEllipse(c, 13, 13)
        p.setBrush(QColor("#333"))
        for ox, oy in ((-5, -3), (5, -3), (0, 5)):
            p.drawEllipse(c + QPointF(ox, oy), 1.8, 1.8)
        p.setBrush(QColor("#444"))
        p.setPen(Qt.NoPen)
        for ox, oy in ((5, 5), (fs - 5, 5), (5, fs - 5), (fs - 5, fs - 5)):
            p.drawEllipse(QPointF(fx + ox, fy + oy), 1.6, 1.6)

        f = QFont("Segoe UI", 7, QFont.Black)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        p.setFont(f)
        p.setPen(_JAUNE)
        if self._logo == FRONT:
            p.drawText(QRectF(fx, fy + 2, fs, 12), Qt.AlignCenter, "MYSTROW")
        else:
            # Texte posé sur le dessus, centré, dans l'axe de la profondeur.
            t = QTransform()
            t.translate(fx + fs / 2 + dx / 2, fy + dy / 2)
            t.rotate(-22.5)
            p.setTransform(t)
            f2 = QFont("Segoe UI", 8, QFont.Black)
            f2.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
            p.setFont(f2)
            p.drawText(QRectF(-34, -6, 68, 12), Qt.AlignCenter, "MYSTROW")
            p.resetTransform()
        # Flèche « regardez ici »
        p.setPen(QPen(_JAUNE, 1.6))
        if self._logo == FRONT:
            a, b = QPointF(fx + fs / 2, fy - 18), QPointF(fx + fs / 2, fy + 1)
        else:
            a, b = QPointF(fx + fs / 2 + dx / 2 - 30, 2), QPointF(fx + fs / 2 + dx / 2 - 14, fy + dy / 2 - 4)
        self._fleche(p, a, b)

    def _fleche(self, p, a, b):
        p.drawLine(a, b)
        v = b - a
        n = (v.x() ** 2 + v.y() ** 2) ** 0.5 or 1
        u = QPointF(v.x() / n, v.y() / n)
        w = QPointF(-u.y(), u.x())
        path = QPainterPath(b)
        path.lineTo(b - u * 6 + w * 3.5)
        path.lineTo(b - u * 6 - w * 3.5)
        path.closeSubpath()
        p.setBrush(_JAUNE)
        p.drawPath(path)

    def _autre(self, p):
        # Interface générique : petit boîtier + câble, sans logo.
        p.setPen(QPen(QColor("#4a4a4a"), 1.2))
        p.setBrush(QColor("#1c1c1c"))
        p.drawRoundedRect(QRectF(30, 30, 72, 36), 6, 6)
        p.setBrush(QColor("#0b0b0b"))
        p.drawEllipse(QPointF(84, 48), 10, 10)
        p.setPen(QPen(QColor("#666"), 3))
        p.drawLine(QPointF(30, 48), QPointF(10, 48))
        p.setPen(QColor("#888"))
        p.setFont(QFont("Segoe UI", 16, QFont.Bold))
        p.drawText(QRectF(36, 30, 36, 36), Qt.AlignCenter, "?")


class _Card(QFrame):
    clicked = Signal()

    def __init__(self, logo: str, title: str, sub: str, parent=None):
        super().__init__(parent)
        self.setObjectName("bxcard")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(4)
        dessin = _BoxDrawing(logo)
        lay.addWidget(dessin, 0, Qt.AlignHCenter)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setWordWrap(True)
        t.setStyleSheet("color:#f0f0f0; font-size:11px; font-weight:700; background:transparent; border:none;")
        lay.addWidget(t)
        s = QLabel(sub)
        s.setAlignment(Qt.AlignCenter)
        s.setWordWrap(True)
        s.setStyleSheet("color:#888; font-size:9px; background:transparent; border:none;")
        lay.addWidget(s)
        self.set_selected(False)

    def set_selected(self, on: bool):
        self.setStyleSheet(
            "#bxcard { background:%s; border:%s; border-radius:10px; }"
            % (("#1d1a05", "2px solid #E2CE16") if on else ("#1a1a1a", "1px solid #2a2a2a")))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class BoitierPicker(QWidget):
    """Trois cartes ; `chosen(mode)` au clic (FRONT, TOP ou OTHER)."""

    chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        titre = QLabel(tr("nc_bx_question"))
        titre.setStyleSheet("color:#ccc; font-size:12px; font-weight:700;")
        lay.addWidget(titre)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._cards = {}
        for mode, t, s in ((FRONT, "nc_bx_front", "nc_bx_front_sub"),
                           (TOP, "nc_bx_top", "nc_bx_top_sub"),
                           (OTHER, "nc_bx_other", "nc_bx_other_sub")):
            c = _Card(mode, tr(t), tr(s))
            c.clicked.connect(lambda m=mode: self.chosen.emit(m))
            row.addWidget(c, 1)
            self._cards[mode] = c
        lay.addLayout(row)

    def set_selected(self, mode):
        for m, c in self._cards.items():
            c.set_selected(m == mode)
