"""
Carte « Boîtier MyStrow détecté », façon AirPods sur iPhone.

Une fenêtre modale SANS bordure, posée exactement sur la fenêtre MyStrow :
fond assombri, carte qui monte du bas. Elle reste sur le même écran que l'app,
et tant qu'on n'a pas répondu rien d'autre n'est cliquable (raccourcis clavier
compris : Espace = Play ne doit pas partir pendant qu'on tape son email).

Le détecteur (boitier_detect.py) pilote les étapes :
  question → show_busy() → show_success() / show_error(final=True)
"""

from PySide6.QtCore import (Qt, Signal, QTimer, QPoint, QPropertyAnimation,
                            QEasingCurve, QParallelAnimationGroup)
from PySide6.QtGui import QPainter, QColor, QPixmap, QKeySequence
from PySide6.QtWidgets import (QDialog, QFrame, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton, QLineEdit,
                               QGraphicsDropShadowEffect)

from core import resource_path
from i18n import tr

_CARD_W = 420
_ACCENT = "#FFD60A"


class BoitierCard(QDialog):
    activate = Signal(str)      # clic « Activer » (email saisi, ou "")
    done = Signal(dict)         # réponse du serveur (émise depuis un thread)

    def __init__(self, window, serial: str, months: int, ask: str,
                 email_field: bool, can_dismiss: bool = True):
        super().__init__(window)
        self._mail = ""
        self.dismissed = False      # « Ne plus me le proposer pour ce boîtier »
        self._closing = False
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        # Pile sur la fenêtre MyStrow (zone cliente, coordonnées écran).
        top_left = window.mapToGlobal(QPoint(0, 0))
        self.setGeometry(top_left.x(), top_left.y(),
                         window.width(), window.height())

        self._card = QFrame(self)
        self._card.setObjectName("card")
        self._card.setFixedWidth(_CARD_W)
        self._card.setStyleSheet(f"""
            #card {{ background: #1c1c1e; border-radius: 22px; }}
            QLabel {{ color: #f2f2f7; background: transparent; }}
            #title {{ font-size: 20px; font-weight: 700; }}
            #serial {{ color: #8e8e93; font-size: 12px; }}
            #months {{ color: {_ACCENT}; font-size: 15px; font-weight: 600; }}
            #ask {{ color: #d1d1d6; font-size: 13px; }}
            #msg {{ font-size: 14px; }}
            #err {{ color: #ff6b6b; font-size: 13px; }}
            #check {{ color: #30d158; font-size: 54px; font-weight: 700; }}
            QLineEdit {{ background: #2c2c2e; color: #f2f2f7; border: 1px solid #3a3a3c;
                         border-radius: 10px; padding: 9px 12px; font-size: 14px; }}
            QLineEdit:focus {{ border-color: {_ACCENT}; }}
            QPushButton {{ border-radius: 12px; padding: 11px 0; font-size: 15px;
                           font-weight: 600; }}
            #primary {{ background: {_ACCENT}; color: #000; border: none; }}
            #primary:hover {{ background: #ffe14d; }}
            #primary:disabled {{ background: #5c5220; color: #2a2a2a; }}
            #secondary {{ background: transparent; color: #aeaeb2; border: none; }}
            #secondary:hover {{ color: #f2f2f7; }}
            #never {{ background: transparent; color: #636366; border: none;
                      font-size: 11px; font-weight: 400; padding: 2px 0; }}
            #never:hover {{ color: #aeaeb2; text-decoration: underline; }}
        """)
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(60)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 200))
        self._card.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self._card)
        lay.setContentsMargins(30, 26, 30, 22)
        lay.setSpacing(8)

        self._img = QLabel(alignment=Qt.AlignCenter)
        pix = QPixmap(resource_path("boitier_1an.png" if months >= 12
                                    else "boitier_2mois.png"))
        if not pix.isNull():
            self._img.setPixmap(pix.scaledToWidth(
                230, Qt.SmoothTransformation))
        lay.addWidget(self._img)

        self._check = QLabel("✓", objectName="check", alignment=Qt.AlignCenter)
        self._check.hide()
        lay.addWidget(self._check)

        self._title = QLabel(tr("bx_title"), objectName="title",
                             alignment=Qt.AlignCenter)
        lay.addWidget(self._title)
        self._serial = QLabel(serial, objectName="serial", alignment=Qt.AlignCenter)
        lay.addWidget(self._serial)
        self._months = QLabel(tr("bx_months", months=months), objectName="months",
                              alignment=Qt.AlignCenter)
        lay.addWidget(self._months)
        lay.addSpacing(6)

        self._ask = QLabel(ask, objectName="ask", alignment=Qt.AlignCenter,
                           wordWrap=True)
        lay.addWidget(self._ask)

        self._email = QLineEdit()
        self._email.setPlaceholderText("email@exemple.com")
        self._email.setVisible(email_field)
        lay.addWidget(self._email)

        self._msg = QLabel(objectName="msg", alignment=Qt.AlignCenter, wordWrap=True)
        self._msg.hide()
        lay.addWidget(self._msg)
        self._err = QLabel(objectName="err", alignment=Qt.AlignCenter, wordWrap=True)
        self._err.hide()
        lay.addWidget(self._err)

        lay.addSpacing(8)
        self._primary = QPushButton(tr("bx_btn_activate"), objectName="primary",
                                    cursor=Qt.PointingHandCursor)
        self._primary.clicked.connect(self._on_primary)
        self._primary.setDefault(True)          # Entrée = Activer
        lay.addWidget(self._primary)
        self._secondary = QPushButton(tr("bx_btn_later"), objectName="secondary",
                                      cursor=Qt.PointingHandCursor)
        self._secondary.clicked.connect(self.close_animated)
        self._secondary.setAutoDefault(False)
        lay.addWidget(self._secondary)
        self._never = QPushButton(tr("bx_never"), objectName="never",
                                  cursor=Qt.PointingHandCursor)
        self._never.setAutoDefault(False)
        self._never.clicked.connect(self._on_never)
        self._never.setVisible(can_dismiss)
        lay.addWidget(self._never)

        self._state = "ask"
        self._card.adjustSize()

    # ------------------------------------------------------------ étapes
    def _on_primary(self):
        if self._state == "ask":
            self._err.hide()
            self.activate.emit(self._email.text())
        elif self._state in ("success", "error"):
            self.close_animated()

    def _on_never(self):
        self.dismissed = True
        self.close_animated()

    def show_busy(self, text: str):
        self._state = "busy"
        self._err.hide()
        self._email.setEnabled(False)
        self._primary.setEnabled(False)
        self._primary.setText(text)
        self._secondary.hide()
        self._never.hide()
        self._recenter()

    def show_error(self, text: str, final: bool = False):
        self._err.setText(text)
        self._err.show()
        if final:
            self._state = "error"
            self._ask.hide()
            self._email.hide()
            self._primary.setEnabled(True)
            self._primary.setText(tr("bx_btn_ok"))
            self._secondary.hide()
            self._never.hide()
        else:
            self._email.setFocus()
        self._recenter()

    def show_success(self, text: str):
        self._state = "success"
        self._img.hide()
        self._check.show()
        self._title.setText(tr("bx_done"))
        self._months.hide()
        self._ask.hide()
        self._email.hide()
        self._msg.setText(text)
        self._msg.show()
        self._primary.setEnabled(True)
        self._primary.setText(tr("bx_btn_ok"))
        self._secondary.hide()
        self._never.hide()
        self._recenter()
        # Connecté : simple confirmation, elle part seule. Sinon le texte dit
        # comment se connecter : on le laisse lire.
        if "\n" not in text:
            QTimer.singleShot(2600, self.close_animated)

    # ------------------------------------------------------------ rendu
    def _recenter(self):
        self._card.adjustSize()
        self._card.move(self._target_pos())

    def _target_pos(self) -> QPoint:
        return QPoint((self.width() - self._card.width()) // 2,
                      (self.height() - self._card.height()) // 2)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 150))

    def showEvent(self, e):
        super().showEvent(e)
        self._card.adjustSize()
        end = self._target_pos()
        self._card.move(end.x(), self.height())
        self.setWindowOpacity(0.0)
        slide = QPropertyAnimation(self._card, b"pos", self)
        slide.setDuration(420)
        slide.setStartValue(QPoint(end.x(), self.height()))
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.OutCubic)
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(260)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        self._anim = QParallelAnimationGroup(self)
        self._anim.addAnimation(slide)
        self._anim.addAnimation(fade)
        self._anim.start()
        if self._email.isVisible():
            self._email.setFocus()
        else:
            self._primary.setFocus()

    def close_animated(self):
        if self._closing:
            return
        self._closing = True
        start = self._card.pos()
        slide = QPropertyAnimation(self._card, b"pos", self)
        slide.setDuration(300)
        slide.setStartValue(start)
        slide.setEndValue(QPoint(start.x(), self.height()))
        slide.setEasingCurve(QEasingCurve.InCubic)
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(300)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        self._anim = QParallelAnimationGroup(self)
        self._anim.addAnimation(slide)
        self._anim.addAnimation(fade)
        self._anim.finished.connect(self.accept)
        self._anim.start()

    def keyPressEvent(self, e):
        # Échap = « Plus tard » ; pendant l'activation, on ne ferme pas.
        if e.matches(QKeySequence.Cancel):
            if self._state != "busy":
                self.close_animated()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        # Clic sur le fond assombri : on ne ferme pas (choix explicite exigé).
        e.accept()
