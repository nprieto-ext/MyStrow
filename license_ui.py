"""
Interface utilisateur pour le systeme de licence MyStrow (Firebase)
Widgets Qt : banniere, dialogue login/register, avertissement
"""

import webbrowser

from i18n import tr
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QDialog, QLineEdit, QProgressBar, QApplication, QStackedWidget,
    QCheckBox, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QCursor

from license_manager import (
    LicenseState, LicenseResult,
    login_account, verify_license,
    deactivate_machine, get_license_info,
    subscribe_newsletter, unsubscribe_newsletter,
)


# ============================================================
# LIENS STRIPE
# ============================================================

STRIPE_LINKS = {
    "monthly":  "https://buy.stripe.com/5kQcMXeNn7FeaxabN208g03",
    "lifetime": "https://buy.stripe.com/7sY6ozgVve3CfRu9EU08g01",
    "annual":   "https://buy.stripe.com/3cI3cngVvf7G34IcR608g04",
}


# ============================================================
# STYLE COMMUN
# ============================================================

_DIALOG_STYLE = """
    QDialog { background: #1a1a1a; }
    QLabel { color: white; border: none; }
    QLineEdit {
        background: #2a2a2a; color: white;
        border: 1px solid #3a3a3a; border-radius: 4px;
        padding: 8px; font-size: 12px;
    }
    QLineEdit:focus { border: 1px solid #00d4ff; }
    QCheckBox { color: #aaa; font-size: 10px; }
    QCheckBox::indicator { width: 14px; height: 14px; }
"""

_DIALOG_STYLE = """
    QDialog   { background: #111111; color: #e0e0e0; }
    QWidget   { background: #111111; color: #e0e0e0; }
    QLabel    { background: transparent; color: #e0e0e0; }
    QLineEdit {
        background: #1e1e1e; color: #ffffff; border: 1px solid #333;
        border-radius: 6px; padding: 8px 12px; font-size: 13px;
    }
    QLineEdit:focus { border-color: #00d4ff; }
"""


class ForgotPasswordDialog(QDialog):
    """Popup de réinitialisation de mot de passe."""

    def __init__(self, prefill_email: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("forgot_pwd_title"))
        self.setFixedSize(400, 280)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)

        # Icône + titre
        title = QLabel(tr("forgot_pwd_title"))
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet("color: #00d4ff;")
        layout.addWidget(title)

        desc = QLabel(tr("forgot_pwd_desc"))
        desc.setFont(QFont("Segoe UI", 9))
        desc.setStyleSheet("color: #666;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Champ email
        self._email = QLineEdit(prefill_email)
        self._email.setPlaceholderText(tr("email_placeholder"))
        self._email.setFixedHeight(42)
        layout.addWidget(self._email)

        # Statut
        self._status = QLabel()
        self._status.setFont(QFont("Segoe UI", 10))
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setFixedHeight(32)
        layout.addWidget(self._status)

        # Boutons
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton(tr("btn_cancel"))
        btn_cancel.setFixedHeight(38)
        btn_cancel.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cancel.setStyleSheet("""
            QPushButton { background:#1e1e1e; color:#aaa; border:1px solid #333;
                border-radius:6px; font-size:12px; }
            QPushButton:hover { background:#2a2a2a; color:#fff; }
        """)
        btn_cancel.clicked.connect(self.reject)

        self._btn_send = QPushButton(tr("btn_send_password"))
        self._btn_send.setFixedHeight(38)
        self._btn_send.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_send.setStyleSheet("""
            QPushButton { background:#00d4ff; color:#000; border:none;
                border-radius:6px; font-size:12px; font-weight:bold; }
            QPushButton:hover { background:#33e0ff; }
            QPushButton:disabled { background:#555; color:#888; }
        """)
        self._btn_send.clicked.connect(self._send)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_send)
        layout.addLayout(btn_row)

        self._email.returnPressed.connect(self._send)

    def _send(self):
        email = self._email.text().strip()
        if not email or "@" not in email:
            self._status.setStyleSheet("color: #e67e22;")
            self._status.setText(tr("err_invalid_email"))
            return

        self._btn_send.setEnabled(False)
        self._btn_send.setText(tr("sending"))
        self._status.setStyleSheet("color: #888;")
        self._status.setText(tr("connecting"))
        QApplication.processEvents()

        try:
            import firebase_client as fc
            fc.send_password_reset(email)
            self._status.setStyleSheet("color: #27ae60;")
            self._status.setText(tr("email_sent", email=email))
            self._btn_send.setText(tr("btn_sent"))
            QTimer.singleShot(2500, self.accept)
        except Exception as e:
            self._status.setStyleSheet("color: #e74c3c;")
            self._status.setText(f"❌  {e}")
            self._btn_send.setEnabled(True)
            self._btn_send.setText(tr("btn_send_short"))


_BTN_PRIMARY = """
    QPushButton {
        background: #00d4ff; color: #000; border: none;
        border-radius: 4px; font-weight: bold; font-size: 12px;
    }
    QPushButton:hover { background: #33e0ff; }
    QPushButton:disabled { background: #555; color: #888; }
"""

_BTN_SECONDARY = """
    QPushButton {
        background: #2a2a2a; color: #aaa; border: 1px solid #444;
        border-radius: 4px; font-size: 11px;
    }
    QPushButton:hover { background: #3a3a3a; color: white; }
    QPushButton:disabled { color: #555; }
"""

_BTN_GREEN = """
    QPushButton {
        background: #2d7a3a; color: white; border: none;
        border-radius: 4px; font-weight: bold; font-size: 12px;
    }
    QPushButton:hover { background: #3a9a4a; }
    QPushButton:disabled { background: #555; color: #888; }
"""


# ============================================================
# BANNIERE DE LICENCE (barre horizontale coloree)
# ============================================================

class LicenseBanner(QWidget):
    """
    Banniere licence sous les cartouches — design soigné avec icône et dégradé.
    """

    activate_clicked = Signal()
    dismissed        = Signal()

    # (bg_color, border_color, icon)
    THEMES = {
        "green":  ("#1a5c35", "#27ae60", "#27ae60", "✓"),
        "orange": ("#6b3a10", "#e67e22", "#e67e22", "⏳"),
        "red":    ("#6b1414", "#e74c3c", "#e74c3c", "⚠"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hide()

        self._theme = "green"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(8)

        # Icône
        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedWidth(18)
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setStyleSheet("background: transparent; border: none;")
        self._icon_lbl.setFont(QFont("Segoe UI", 11))
        layout.addWidget(self._icon_lbl)

        # Séparateur vertical
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setFixedHeight(20)
        self._sep = sep
        layout.addWidget(sep)

        # Texte principal
        self.label = QLabel()
        self.label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.label.setStyleSheet("color: #fff; background: transparent; border: none;")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label, 1)

        # Bouton action
        self.action_btn = QPushButton()
        self.action_btn.setFixedHeight(24)
        self.action_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.action_btn.hide()
        layout.addWidget(self.action_btn)

        # Bouton fermer
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._close_btn.setStyleSheet("""
            QPushButton {
                color: rgba(255,255,255,0.45); background: transparent;
                border: none; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { color: white; }
        """)
        self._close_btn.clicked.connect(self.dismissed)
        self._close_btn.hide()
        layout.addWidget(self._close_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.activate_clicked.emit()

    def _refresh_style(self):
        bg, border, accent, _ = self.THEMES[self._theme]
        self.setStyleSheet(f"""
            LicenseBanner {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {bg}, stop:1 #1a1a1a
                );
                border: 1px solid {border};
                border-radius: 5px;
            }}
        """)
        self._sep.setStyleSheet(f"background: {accent}; border: none;")
        self.action_btn.setStyleSheet(f"""
            QPushButton {{
                color: #000; background: {accent};
                border: none; border-radius: 3px;
                padding: 2px 12px; font-size: 9px; font-weight: bold;
            }}
            QPushButton:hover {{ background: white; }}
        """)

    def apply_license(self, result: LicenseResult, dismissible: bool = True):
        state = result.state

        if state == LicenseState.TRIAL_ACTIVE and not result.show_warning:
            self._theme = "green"
        elif state in (LicenseState.TRIAL_ACTIVE, LicenseState.LICENSE_ACTIVE):
            self._theme = "orange"
        else:
            self._theme = "red"

        self._refresh_style()

        _, _, _, icon = self.THEMES[self._theme]
        self._icon_lbl.setText(icon)
        self.label.setText(result.message)

        if result.action_label:
            self.action_btn.setText(result.action_label)
            try:
                self.action_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self.action_btn.clicked.connect(self.activate_clicked)
            self.action_btn.show()
        else:
            self.action_btn.hide()

        self._close_btn.setVisible(dismissible)


# ============================================================
# DIALOGUE LOGIN / COMPTE / ACHAT
# ============================================================

class ActivationDialog(QDialog):
    """
    Dialogue de connexion / gestion compte / achat MyStrow.

    Pages :
      0 — Formulaire login (email + mdp)
      1 — Succes connexion
      2 — Compte connecte
      3 — Acheter une licence (3 plans Stripe)
    """

    activation_success = Signal()

    def __init__(self, parent=None, license_result=None, start_purchase=False):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_login_title"))
        self.setFixedSize(420, 380)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            | Qt.WindowCloseButtonHint
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._stack.addWidget(self._build_page_login())    # 0
        self._stack.addWidget(self._build_page_success())  # 1
        self._stack.addWidget(self._build_page_account())  # 2
        self._stack.addWidget(self._build_page_purchase()) # 3

        # Page compte uniquement si un vrai compte Firebase est connecté (email présent)
        _info = get_license_info()
        already_logged = (
            license_result is not None
            and license_result.state not in (LicenseState.NOT_ACTIVATED, LicenseState.INVALID,
                                             LicenseState.TRIAL_ACTIVE, LicenseState.TRIAL_EXPIRED)
            and bool(_info.get("email"))
        )

        if start_purchase:
            self._stack.setCurrentIndex(3)
            self.setWindowTitle(tr("dlg_choose_plan_title"))
        elif already_logged:
            self._refresh_account_page(license_result)
            self._stack.setCurrentIndex(2)
            self.setWindowTitle(tr("dlg_account_title"))
        else:
            self._stack.setCurrentIndex(0)

    # ----------------------------------------------------------
    # Constructeurs de pages
    # ----------------------------------------------------------

    def _page_frame(self, title_text, subtitle=""):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 20)
        layout.setSpacing(12)

        title = QLabel(title_text)
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet("color: #00d4ff;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setFont(QFont("Segoe UI", 10))
            sub.setStyleSheet("color: #aaa;")
            sub.setAlignment(Qt.AlignCenter)
            sub.setWordWrap(True)
            layout.addWidget(sub)

        return page, layout

    def _build_page_login(self):
        page, layout = self._page_frame(
            tr("page_login_heading"),
            tr("page_login_subtitle")
        )

        self._email_edit = QLineEdit()
        self._email_edit.setPlaceholderText(tr("placeholder_email"))
        self._email_edit.setFixedHeight(36)
        self._email_edit.returnPressed.connect(self._do_login)
        layout.addWidget(self._email_edit)

        self._pwd_edit = QLineEdit()
        self._pwd_edit.setPlaceholderText(tr("placeholder_password"))
        self._pwd_edit.setEchoMode(QLineEdit.Password)
        self._pwd_edit.setFixedHeight(36)
        self._pwd_edit.returnPressed.connect(self._do_login)
        layout.addWidget(self._pwd_edit)

        self._login_progress = QProgressBar()
        self._login_progress.setRange(0, 0)
        self._login_progress.setFixedHeight(3)
        self._login_progress.setTextVisible(False)
        self._login_progress.setStyleSheet(
            "QProgressBar{background:#333;border:none;border-radius:1px;}"
            "QProgressBar::chunk{background:#00d4ff;border-radius:1px;}"
        )
        self._login_progress.hide()
        layout.addWidget(self._login_progress)

        self._login_status = QLabel()
        self._login_status.setAlignment(Qt.AlignCenter)
        self._login_status.setFont(QFont("Segoe UI", 10))
        self._login_status.setWordWrap(True)
        layout.addWidget(self._login_status)

        self._btn_send_pwd = QPushButton(tr("btn_recv_password"))
        self._btn_send_pwd.setFixedHeight(32)
        self._btn_send_pwd.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_send_pwd.setStyleSheet("""
            QPushButton {
                background: #3a1a00; color: #ff9800;
                border: 1px solid #ff980055; border-radius: 6px; font-size: 11px;
            }
            QPushButton:hover { background: #4a2500; color: #ffb74d; border-color: #ff9800; }
        """)
        self._btn_send_pwd.clicked.connect(self._do_forgot_password)
        self._btn_send_pwd.hide()
        layout.addWidget(self._btn_send_pwd)

        layout.addStretch()

        btn_forgot = QPushButton(tr("btn_forgot_password"))
        btn_forgot.setFixedHeight(32)
        btn_forgot.setCursor(QCursor(Qt.PointingHandCursor))
        btn_forgot.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(0, 212, 255, 0.5);
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: 6px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(0, 212, 255, 0.08);
                color: #00d4ff;
                border-color: rgba(0, 212, 255, 0.45);
            }
        """)
        btn_forgot.clicked.connect(self._do_forgot_password)
        layout.addWidget(btn_forgot)

        btn_buy = QPushButton(tr("btn_no_account"))
        btn_buy.setFixedHeight(30)
        btn_buy.setCursor(QCursor(Qt.PointingHandCursor))
        btn_buy.setStyleSheet("""
            QPushButton {
                background: transparent; color: #00d4ff;
                border: none; font-size: 10px;
            }
            QPushButton:hover { color: #33e0ff; text-decoration: underline; }
        """)
        btn_buy.clicked.connect(lambda: self._go_to_purchase())
        layout.addWidget(btn_buy, alignment=Qt.AlignCenter)

        btn_row = QHBoxLayout()

        btn_close = QPushButton(tr("btn_close"))
        btn_close.setFixedHeight(36)
        btn_close.setCursor(QCursor(Qt.PointingHandCursor))
        btn_close.setStyleSheet(_BTN_SECONDARY)
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)

        self._btn_login = QPushButton(tr("btn_login"))
        self._btn_login.setFixedHeight(36)
        self._btn_login.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_login.setStyleSheet(_BTN_PRIMARY)
        self._btn_login.clicked.connect(self._do_login)
        btn_row.addWidget(self._btn_login)

        layout.addLayout(btn_row)

        return page

    def _build_page_success(self):
        page, layout = self._page_frame(tr("page_success_heading"))

        self._success_label = QLabel()
        self._success_label.setFont(QFont("Segoe UI", 11))
        self._success_label.setStyleSheet("color: #4CAF50;")
        self._success_label.setAlignment(Qt.AlignCenter)
        self._success_label.setWordWrap(True)
        layout.addWidget(self._success_label)

        layout.addStretch()

        btn_ok = QPushButton(tr("btn_start_mystrow"))
        btn_ok.setFixedHeight(36)
        btn_ok.setCursor(QCursor(Qt.PointingHandCursor))
        btn_ok.setStyleSheet(_BTN_PRIMARY)
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)
        return page

    def _build_page_account(self):
        page, layout = self._page_frame(tr("page_account_heading"))

        self._acct_plan = QLabel()
        self._acct_plan.setFont(QFont("Segoe UI", 11))
        self._acct_plan.setAlignment(Qt.AlignCenter)
        self._acct_plan.setWordWrap(True)
        layout.addWidget(self._acct_plan)

        self._acct_machine_label = QLabel(tr("acct_label"))
        self._acct_machine_label.setFont(QFont("Segoe UI", 9))
        self._acct_machine_label.setStyleSheet("color: #666;")
        self._acct_machine_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._acct_machine_label)

        self._acct_machine = QLabel()
        self._acct_machine.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._acct_machine.setStyleSheet("color: #aaa;")
        self._acct_machine.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._acct_machine)

        # ── Compteur PC activés ───────────────────────────────────────────
        layout.addSpacing(6)
        machines_row = QHBoxLayout()
        machines_row.setSpacing(10)

        self._acct_machines_bar = QWidget()
        self._acct_machines_bar.setFixedSize(120, 20)
        bar_lay = QHBoxLayout(self._acct_machines_bar)
        bar_lay.setContentsMargins(0, 0, 0, 0)
        bar_lay.setSpacing(4)
        self._machine_dots = []
        for _ in range(2):  # max_machines par défaut 2, on redimensionne dans refresh
            dot = QLabel("●")
            dot.setFixedSize(18, 18)
            dot.setAlignment(Qt.AlignCenter)
            dot.setFont(QFont("Segoe UI", 12))
            dot.setStyleSheet("color: #333; background: transparent; border: none;")
            bar_lay.addWidget(dot)
            self._machine_dots.append(dot)
        bar_lay.addStretch()

        self._acct_machines_lbl = QLabel("— / — PC")
        self._acct_machines_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._acct_machines_lbl.setStyleSheet("color: #aaa; background: transparent; border: none;")

        machines_row.addStretch()
        machines_row.addWidget(self._acct_machines_bar)
        machines_row.addWidget(self._acct_machines_lbl)
        machines_row.addStretch()
        layout.addLayout(machines_row)

        # Liste des noms de machines activées
        self._acct_machines_detail = QLabel("")
        self._acct_machines_detail.setAlignment(Qt.AlignCenter)
        self._acct_machines_detail.setFont(QFont("Segoe UI", 9))
        self._acct_machines_detail.setStyleSheet(
            "color: #666; background: transparent; border: none;"
        )
        self._acct_machines_detail.setWordWrap(True)
        layout.addSpacing(2)
        layout.addWidget(self._acct_machines_detail)

        # ── Newsletter ────────────────────────────────────────────────────
        layout.addSpacing(10)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background: #222; border: none; max-height: 1px;")
        layout.addWidget(sep)
        layout.addSpacing(6)

        self._newsletter_checkbox = QCheckBox(tr("newsletter_subscribe"))
        self._newsletter_checkbox.setFont(QFont("Segoe UI", 10))
        self._newsletter_checkbox.setStyleSheet("""
            QCheckBox { color: #888; background: transparent; }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                border: 1px solid #444; border-radius: 3px; background: #1e1e1e;
            }
            QCheckBox::indicator:checked {
                background: #00d4ff; border-color: #00d4ff;
            }
        """)
        self._newsletter_checkbox.stateChanged.connect(self._do_toggle_newsletter)
        layout.addWidget(self._newsletter_checkbox)

        self._newsletter_status = QLabel()
        self._newsletter_status.setFont(QFont("Segoe UI", 9))
        self._newsletter_status.setFixedHeight(18)
        layout.addWidget(self._newsletter_status)

        layout.addStretch()

        self._acct_logout_status = QLabel()
        self._acct_logout_status.setAlignment(Qt.AlignCenter)
        self._acct_logout_status.setFont(QFont("Segoe UI", 10))
        self._acct_logout_status.setWordWrap(True)
        layout.addWidget(self._acct_logout_status)

        self._btn_renew = QPushButton(tr("btn_renew_plan"))
        self._btn_renew.setFixedHeight(34)
        self._btn_renew.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_renew.setStyleSheet(_BTN_GREEN)
        self._btn_renew.clicked.connect(self._go_to_purchase)
        self._btn_renew.hide()
        layout.addWidget(self._btn_renew)

        self._btn_portal = QPushButton(tr("btn_manage_sub"))
        self._btn_portal.setFixedHeight(34)
        self._btn_portal.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_portal.setStyleSheet("""
            QPushButton {
                background: #1a1a2e; color: #00d4ff;
                border: 1px solid #00d4ff44; border-radius: 6px;
                font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background: #0d0d1f; border-color: #00d4ff99; }
            QPushButton:disabled { color: #444; border-color: #333; }
        """)
        self._btn_portal.clicked.connect(self._do_open_portal)
        self._btn_portal.hide()
        layout.addWidget(self._btn_portal)

        btn_row = QHBoxLayout()

        btn_close = QPushButton(tr("btn_close"))
        btn_close.setFixedHeight(32)
        btn_close.setStyleSheet(_BTN_SECONDARY)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        btn_logout = QPushButton(tr("btn_logout"))
        btn_logout.setFixedHeight(32)
        btn_logout.setStyleSheet("""
            QPushButton {
                background: #5a1a1a; color: #ff8888; border: 1px solid #8a3a3a;
                border-radius: 4px; font-size: 11px;
            }
            QPushButton:hover { background: #7a2a2a; color: white; }
        """)
        btn_logout.setCursor(QCursor(Qt.PointingHandCursor))
        btn_logout.clicked.connect(self._do_logout)
        self._btn_logout = btn_logout
        btn_row.addWidget(btn_logout)

        layout.addLayout(btn_row)
        return page

    def _build_page_purchase(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(22, 16, 22, 14)
        root.setSpacing(8)

        # ── Titre ────────────────────────────────────────────────────────
        title = QLabel(tr("page_purchase_title"))
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setStyleSheet("color: #00d4ff; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        sub = QLabel(tr("page_purchase_sub"))
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet("color: #555; background: transparent;")
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(sub)

        root.addSpacing(6)

        # ── Card helper ──────────────────────────────────────────────────
        def _plan_card(icon, plan_title, price, billing, features, link_key, accent="#00d4ff", badge=""):
            card = QFrame()
            card.setAttribute(Qt.WA_StyledBackground, True)
            card.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 #1e1e1e, stop:1 #171717);
                    border: 1px solid #2a2a2a;
                    border-left: 3px solid {accent};
                    border-radius: 8px;
                }}
                QFrame:hover {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 #252525, stop:1 #1c1c1c);
                    border-color: #3a3a3a;
                    border-left-color: {accent};
                }}
            """)
            card.setCursor(QCursor(Qt.PointingHandCursor))

            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 10, 12, 10)
            cl.setSpacing(10)

            # Icône
            icon_lbl = QLabel(icon)
            icon_lbl.setFont(QFont("Segoe UI", 20))
            icon_lbl.setStyleSheet("background:transparent;border:none;")
            icon_lbl.setFixedWidth(32)
            icon_lbl.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            cl.addWidget(icon_lbl)

            # Infos centre
            info = QVBoxLayout()
            info.setSpacing(3)

            title_row = QHBoxLayout()
            title_row.setSpacing(6)
            t = QLabel(plan_title)
            t.setFont(QFont("Segoe UI", 11, QFont.Bold))
            t.setStyleSheet("color:#fff;background:transparent;border:none;")
            title_row.addWidget(t)
            if badge:
                b = QLabel(badge)
                b.setFont(QFont("Segoe UI", 7, QFont.Bold))
                b.setStyleSheet(f"""
                    color:#000; background:{accent}; border:none;
                    border-radius:3px; padding:1px 5px;
                """)
                b.setFixedHeight(14)
                title_row.addWidget(b)
            title_row.addStretch()
            info.addLayout(title_row)

            for feat in features:
                f = QLabel(f"✓  {feat}")
                f.setFont(QFont("Segoe UI", 8))
                f.setStyleSheet("color:#666;background:transparent;border:none;")
                f.setWordWrap(True)
                info.addWidget(f)

            cl.addLayout(info, 1)

            # Prix + bouton
            right = QVBoxLayout()
            right.setSpacing(2)
            right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            p = QLabel(price)
            p.setFont(QFont("Segoe UI", 13, QFont.Bold))
            p.setStyleSheet(f"color:{accent};background:transparent;border:none;")
            p.setAlignment(Qt.AlignRight)
            right.addWidget(p)

            bl = QLabel(billing)
            bl.setFont(QFont("Segoe UI", 7))
            bl.setStyleSheet("color:#555;background:transparent;border:none;")
            bl.setAlignment(Qt.AlignRight)
            right.addWidget(bl)

            right.addSpacing(4)

            btn = QPushButton(tr("btn_choose"))
            btn.setFixedHeight(26)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{accent};color:#000;border:none;
                    border-radius:5px;font-size:10px;font-weight:bold;
                    padding:0 10px;
                }}
                QPushButton:hover {{ background:#fff; }}
            """)
            btn.clicked.connect(lambda checked=False, k=link_key: webbrowser.open(STRIPE_LINKS[k]))
            right.addWidget(btn)

            cl.addLayout(right)
            card.mousePressEvent = lambda e, k=link_key: webbrowser.open(STRIPE_LINKS[k])
            return card

        root.addWidget(_plan_card(
            "📅", tr("plan_monthly_name"), "21,69 €", tr("plan_monthly_billing"),
            [tr("plan_monthly_f1"), tr("plan_monthly_f2"), tr("plan_monthly_f3")],
            "monthly", accent="#4a9eff",
        ))
        root.addWidget(_plan_card(
            "📆", tr("plan_annual_name"), "216,99 €", tr("plan_annual_billing"),
            [tr("plan_monthly_f1"), tr("plan_monthly_f2"), tr("plan_annual_f3")],
            "annual", accent="#00d4ff", badge="−17%",
        ))
        root.addWidget(_plan_card(
            "♾️", tr("plan_lifetime_name"), "378,67 €", tr("plan_lifetime_billing"),
            [tr("plan_monthly_f1"), tr("plan_lifetime_f2"), tr("plan_lifetime_f3")],
            "lifetime", accent="#a78bfa",
        ))

        root.addSpacing(4)

        # ── Stripe badge ──────────────────────────────────────────────────
        stripe_row = QHBoxLayout()
        stripe_row.setAlignment(Qt.AlignCenter)
        stripe_lbl = QLabel(tr("stripe_secure"))
        stripe_lbl.setFont(QFont("Segoe UI", 8))
        stripe_lbl.setStyleSheet("color: #3a3a3a; background: transparent;")
        stripe_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(stripe_lbl)

        # ── Boutons bas ───────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_back = QPushButton(tr("btn_back_account"))
        btn_back.setFixedHeight(28)
        btn_back.setCursor(QCursor(Qt.PointingHandCursor))
        btn_back.setStyleSheet(_BTN_SECONDARY)
        btn_back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        btn_row.addWidget(btn_back)

        btn_close = QPushButton(tr("btn_close"))
        btn_close.setFixedHeight(28)
        btn_close.setCursor(QCursor(Qt.PointingHandCursor))
        btn_close.setStyleSheet(_BTN_SECONDARY)
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)

        root.addLayout(btn_row)
        return page

    # ----------------------------------------------------------
    # Navigation
    # ----------------------------------------------------------

    def _go_to_purchase(self):
        self._stack.setCurrentIndex(3)
        self.setWindowTitle(tr("dlg_choose_plan_title"))
        self.setFixedSize(460, 480)

    # ----------------------------------------------------------
    # Logique compte
    # ----------------------------------------------------------

    def _refresh_account_page(self, license_result: LicenseResult):
        info = get_license_info()
        email = info.get("email", "—")

        # Newsletter : initialiser la checkbox sans déclencher le signal
        self._newsletter_checkbox.blockSignals(True)
        self._newsletter_checkbox.setChecked(info.get("newsletter_consent", False))
        self._newsletter_checkbox.blockSignals(False)
        self._newsletter_status.clear()

        if license_result.state == LicenseState.LICENSE_ACTIVE:
            if license_result.days_remaining:
                plan_text = tr("plan_active_days", days=license_result.days_remaining)
            else:
                plan_text = tr("plan_active")
            self._acct_plan.setStyleSheet("color: #4CAF50;")
            self._btn_renew.hide()
            self._btn_portal.show()
        elif license_result.state == LicenseState.TRIAL_ACTIVE:
            plan_text = tr("plan_trial", days=license_result.days_remaining)
            self._acct_plan.setStyleSheet("color: #c47f17;")
            self._btn_renew.show()
            self._btn_portal.hide()
        elif license_result.state == LicenseState.TRIAL_EXPIRED:
            plan_text = tr("plan_trial_expired")
            self._acct_plan.setStyleSheet("color: #ff5555;")
            self._btn_renew.show()
        elif license_result.state == LicenseState.LICENSE_EXPIRED:
            plan_text = tr("plan_license_expired")
            self._acct_plan.setStyleSheet("color: #ff5555;")
            self._btn_renew.show()
        else:
            plan_text = license_result.message or tr("plan_unknown")
            self._acct_plan.setStyleSheet("color: #aaa;")
            self._btn_renew.hide()

        self._acct_plan.setText(plan_text)
        self._acct_machine.setText(email)
        self._acct_logout_status.clear()

        # ── Mise à jour compteur PC ───────────────────────────────────────
        used = getattr(license_result, "machines_used", 0)
        maxm = getattr(license_result, "machines_max", 2)
        # Redimensionner les dots si max_machines a changé
        bar_lay = self._acct_machines_bar.layout()
        while len(self._machine_dots) < maxm:
            dot = QLabel("●")
            dot.setFixedSize(18, 18)
            dot.setAlignment(Qt.AlignCenter)
            from PySide6.QtGui import QFont as _QFont
            dot.setFont(_QFont("Segoe UI", 12))
            dot.setStyleSheet("color: #333; background: transparent; border: none;")
            bar_lay.insertWidget(bar_lay.count() - 1, dot)
            self._machine_dots.append(dot)
        while len(self._machine_dots) > maxm:
            dot = self._machine_dots.pop()
            bar_lay.removeWidget(dot)
            dot.deleteLater()
        # Colorier les dots
        full_color  = "#4CAF50" if used < maxm else "#f44336"
        empty_color = "#333"
        for i, dot in enumerate(self._machine_dots):
            dot.setStyleSheet(
                f"color: {full_color if i < used else empty_color};"
                " background: transparent; border: none;"
            )
        lbl_color = "#4CAF50" if used < maxm else "#f44336"
        self._acct_machines_lbl.setStyleSheet(
            f"color: {lbl_color}; background: transparent; border: none; font-weight: bold;"
        )
        pc_word = tr("pc_unit") if maxm <= 2 else tr("devices_unit")
        plural = "s" if used > 1 else ""
        self._acct_machines_lbl.setText(f"{used} / {maxm} {pc_word} {tr('pc_activated_label')}{plural}")

        # Noms des machines activées
        mlist = getattr(license_result, "machines_list", [])
        if mlist:
            names = [m.get("label") or m.get("id", "?")[:20] for m in mlist]
            self._acct_machines_detail.setText("  ·  ".join(names))
        else:
            self._acct_machines_detail.setText("")

    def _do_toggle_newsletter(self, state):
        """Abonne ou désabonne l'utilisateur à la newsletter Brevo."""
        info  = get_license_info()
        email = info.get("email", "")
        if not email or "@" not in email:
            return

        self._newsletter_checkbox.setEnabled(False)
        QApplication.processEvents()

        if state == Qt.Checked:
            success, msg = subscribe_newsletter(email)
        else:
            success, msg = unsubscribe_newsletter(email)

        self._newsletter_checkbox.setEnabled(True)
        self._newsletter_status.setStyleSheet(
            "color: #4CAF50;" if success else "color: #ff5555;"
        )
        self._newsletter_status.setText(msg)
        QTimer.singleShot(3000, self._newsletter_status.clear)

    def _do_open_portal(self):
        """Ouvre le Stripe Customer Portal pour gérer l'abonnement."""
        webbrowser.open("https://billing.stripe.com/p/login/00w3cneNnbVudJm8AQ08g00")
        self._acct_logout_status.setStyleSheet("color: #4CAF50;")
        self._acct_logout_status.setText(tr("portal_opened"))

    def _do_logout(self):
        self._btn_logout.setEnabled(False)
        self._acct_logout_status.setStyleSheet("color: #aaa;")
        self._acct_logout_status.setText(tr("logging_out"))
        QApplication.processEvents()

        success, message = deactivate_machine()

        if success:
            self._acct_logout_status.setStyleSheet("color: #4CAF50;")
            self._acct_logout_status.setText(tr("logged_out_restart"))
            self._btn_logout.hide()
        else:
            self._acct_logout_status.setStyleSheet("color: #ff5555;")
            self._acct_logout_status.setText(message)
            self._btn_logout.setEnabled(True)

    # ----------------------------------------------------------
    # Logique login
    # ----------------------------------------------------------

    def _do_forgot_password(self):
        prefill = self._email_edit.text().strip()
        dlg = ForgotPasswordDialog(prefill_email=prefill, parent=self)
        dlg.exec()

    def _do_login(self):
        email = self._email_edit.text().strip()
        pwd   = self._pwd_edit.text()

        if not email or "@" not in email:
            self._login_status.setStyleSheet("color: #ff5555;")
            self._login_status.setText(tr("err_login_email"))
            return
        if not pwd:
            self._login_status.setStyleSheet("color: #ff5555;")
            self._login_status.setText(tr("err_login_password"))
            return

        self._btn_login.setEnabled(False)
        self._login_progress.show()
        self._login_status.setStyleSheet("color: #aaa;")
        self._login_status.setText(tr("logging_in"))
        QApplication.processEvents()

        success, message = login_account(email, pwd)

        self._login_progress.hide()
        self._btn_login.setEnabled(True)

        if success:
            self._btn_send_pwd.hide()
            self._success_label.setText(tr("welcome_msg", message=message))
            self._stack.setCurrentIndex(1)
            self.activation_success.emit()
            QTimer.singleShot(2000, self.accept)
        else:
            self._login_status.setStyleSheet("color: #ff5555;")
            self._login_status.setText(message)
            # Afficher le bouton de réception par mail si mauvais mot de passe
            wrong_creds = any(w in message.lower() for w in
                              ("incorrect", "mot de passe", "invalid", "password"))
            self._btn_send_pwd.setVisible(wrong_creds)


# ============================================================
# DIALOGUE D'AVERTISSEMENT (expire bientot)
# ============================================================

class LicenseWarningDialog(QDialog):
    """
    Dialogue affiche au demarrage quand l'essai ou la licence
    arrive bientot a expiration.
    """

    def __init__(self, result: LicenseResult, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_account_ttl"))
        self.setFixedSize(380, 190)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            | Qt.WindowCloseButtonHint
        )

        self.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QLabel { color: white; border: none; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(12)

        if result.state == LicenseState.TRIAL_ACTIVE:
            title_text = tr("warn_trial_soon")
            color = "#c47f17"
        else:
            title_text = tr("warn_lic_soon")
            color = "#c47f17"

        title = QLabel(title_text)
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet(f"color: {color};")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        msg = QLabel(result.message)
        msg.setFont(QFont("Segoe UI", 11))
        msg.setAlignment(Qt.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        layout.addStretch()

        btn_layout = QHBoxLayout()

        btn_later = QPushButton(tr("btn_continue"))
        btn_later.setFixedHeight(32)
        btn_later.setCursor(QCursor(Qt.PointingHandCursor))
        btn_later.setStyleSheet(_BTN_SECONDARY)
        btn_later.clicked.connect(self.accept)
        btn_layout.addWidget(btn_later)

        btn_activate = QPushButton(result.action_label or tr("btn_my_account"))
        btn_activate.setFixedHeight(32)
        btn_activate.setCursor(QCursor(Qt.PointingHandCursor))
        btn_activate.setStyleSheet(_BTN_PRIMARY)
        btn_activate.clicked.connect(lambda: self.done(2))
        btn_layout.addWidget(btn_activate)

        layout.addLayout(btn_layout)


class LoginSuccessDialog(QDialog):
    """
    Popup affiche apres une reconnexion reussie.
    Propose d'activer la sortie DMX si la licence le permet.
    """

    ACTIVATE_DMX = 2

    def __init__(self, dmx_allowed: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_account_ttl"))
        self.setFixedSize(340, 175 if dmx_allowed else 140)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setStyleSheet("QDialog { background: #1a1a1a; } QLabel { color: white; border: none; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(10)

        title = QLabel(tr("login_success_title"))
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setStyleSheet("color: #4caf50;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        sub = QLabel(tr("login_success_sub"))
        sub.setFont(QFont("Segoe UI", 10))
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        layout.addStretch()

        btn_row = QHBoxLayout()

        btn_close = QPushButton(tr("btn_continue"))
        btn_close.setFixedHeight(32)
        btn_close.setCursor(QCursor(Qt.PointingHandCursor))
        btn_close.setStyleSheet(_BTN_SECONDARY)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        if dmx_allowed:
            btn_dmx = QPushButton(tr("btn_activate_dmx"))
            btn_dmx.setFixedHeight(32)
            btn_dmx.setCursor(QCursor(Qt.PointingHandCursor))
            btn_dmx.setStyleSheet(_BTN_PRIMARY)
            btn_dmx.clicked.connect(lambda: self.done(self.ACTIVATE_DMX))
            btn_row.addWidget(btn_dmx)

        layout.addLayout(btn_row)
