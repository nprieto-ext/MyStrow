"""up_panel.py - onglet « MyStrow Up » du panneau admin.

Lit https://live.mystrow.fr/stats (relais crowd/relay_server.py) : sessions EN
DIRECT (téléphones connectés maintenant) et HISTORIQUE (une ligne par session
terminée : client, durée, pic de téléphones, total venus, raison de fin).

Accès : en-tête X-Stats-Key = HMAC(secret des tickets, "mystrow-up-stats"),
calculé depuis la copie locale du secret (~/.mystrow_up_ticket_secret, PC de
l'admin seulement). Les clients sont identifiés par leur uid ; le panneau
admin fournit la correspondance uid → email (`resoudre_clients`).
"""
import hashlib
import hmac
import json
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

URL_STATS = "https://live.mystrow.fr/stats"
FICHIER_SECRET = Path.home() / ".mystrow_up_ticket_secret"
RAFRAICHIR_MS = 10_000          # direct relu toutes les 10 s tant que l'onglet est affiché

BG_MAIN, BG_PANEL, TEXT, TEXT_DIM = "#121212", "#181818", "#e0e0e0", "#888888"
VERT, ORANGE = "#00cc66", "#ffb347"
_BTN = ("QPushButton { background:#252525; color:#ccc; border:1px solid #3a3a3a; border-radius:4px;"
        " font-size:12px; padding:0 12px; } QPushButton:hover { background:#303030; color:white; }")


def cle_stats() -> str:
    secret = FICHIER_SECRET.read_text(encoding="utf-8").strip()
    return hmac.new(secret.encode(), b"mystrow-up-stats", hashlib.sha256).hexdigest()


def lire_stats() -> dict:
    req = urllib.request.Request(URL_STATS, headers={"X-Stats-Key": cle_stats()})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def duree(s) -> str:
    s = int(s or 0)
    h, m = divmod(s // 60, 60)
    return f"{h} h {m:02d}" if h else f"{m} min" if m else f"{s} s"


def date_courte(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%y %H:%M") if ts else ""


def totaux(historique: list, direct: list) -> dict:
    """Compteurs cumulés (sessions terminées + en cours)."""
    toutes = historique + direct
    mois = datetime.now().strftime("%Y-%m")
    return {
        "sessions": len(toutes),
        "telephones": sum(int(x.get("total", 0)) for x in toutes),
        "clients": len({x.get("uid") for x in toutes if x.get("uid")}),
        "pic": max((int(x.get("pic", 0)) for x in toutes), default=0),
        "mois": sum(1 for x in toutes
                    if datetime.fromtimestamp(x.get("debut", 0)).strftime("%Y-%m") == mois),
        "heures": sum(int(x.get("duree_s", 0)) for x in historique) / 3600,
    }


class _Pont(QObject):
    recu = Signal(object, object)      # données, erreur (depuis le fil réseau)


class UpPanel(QWidget):
    def __init__(self, resoudre_clients=None, parent=None):
        """`resoudre_clients(uids) -> {uid: email}` : appelé dans un fil."""
        super().__init__(parent)
        self._resoudre = resoudre_clients or (lambda uids: {})
        self._noms = {}
        self._en_cours = False
        self._pont = _Pont()
        self._pont.recu.connect(self._sur_donnees)
        self.setStyleSheet(f"background:{BG_MAIN};")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(46)
        hdr.setStyleSheet(f"background:{BG_PANEL}; border-bottom:1px solid #1e1e1e;")
        h = QHBoxLayout(hdr)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(10)
        titre = QLabel("MyStrow Up")
        titre.setFont(QFont("Segoe UI", 12, QFont.Bold))
        titre.setStyleSheet(f"color:{TEXT}; background:transparent;")
        h.addWidget(titre)
        self._direct_lbl = QLabel("")
        self._direct_lbl.setStyleSheet(f"color:{VERT}; font-weight:bold; background:transparent;")
        h.addWidget(self._direct_lbl)
        h.addStretch()
        self._etat = QLabel("…")
        self._etat.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px; background:transparent;")
        h.addWidget(self._etat)
        btn = QPushButton("↺  Actualiser")
        btn.setFixedHeight(28)
        btn.setStyleSheet(_BTN)
        btn.clicked.connect(self.charger)
        h.addWidget(btn)
        root.addWidget(hdr)

        # Compteurs
        bande = QFrame()
        bande.setStyleSheet(f"background:{BG_MAIN};")
        b = QHBoxLayout(bande)
        b.setContentsMargins(20, 14, 20, 6)
        b.setSpacing(12)
        self._tuiles = {}
        for cle, libelle in (("sessions", "Sessions"), ("mois", "Ce mois-ci"),
                             ("telephones", "Téléphones venus"), ("clients", "Clients"),
                             ("pic", "Record simultané"), ("heures", "Heures de show")):
            t = QFrame()
            t.setStyleSheet("QFrame { background:#1a1a1a; border:1px solid #262626; border-radius:6px; }")
            v = QVBoxLayout(t)
            v.setContentsMargins(14, 8, 14, 8)
            v.setSpacing(0)
            val = QLabel("-")
            val.setFont(QFont("Segoe UI", 18, QFont.Bold))
            val.setStyleSheet(f"color:{TEXT}; border:none; background:transparent;")
            lib = QLabel(libelle)
            lib.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px; border:none; background:transparent;")
            v.addWidget(val)
            v.addWidget(lib)
            b.addWidget(t, 1)
            self._tuiles[cle] = val
        root.addWidget(bande)

        split = QSplitter(Qt.Vertical)
        self._t_direct = self._table(["Client", "Début", "Depuis", "Connectés", "Pic", "Venus",
                                      "Type", "MyStrow"])
        self._t_hist = self._table(["Date", "Client", "Durée", "Pic", "Venus", "Type", "Fin"])
        split.addWidget(self._bloc("EN DIRECT", self._t_direct))
        split.addWidget(self._bloc("HISTORIQUE", self._t_hist))
        split.setSizes([180, 520])
        root.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(RAFRAICHIR_MS)
        self._timer.timeout.connect(self._auto)

    @staticmethod
    def _table(cols):
        t = QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        hh = t.horizontalHeader()
        for c in range(len(cols)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setStyleSheet(
            f"QTableWidget {{ background:#161616; alternate-background-color:#1c1c1c; color:{TEXT};"
            " gridline-color:#262626; border:1px solid #262626; font-size:12px; }"
            " QTableWidget::item:selected { background:#0d3a4a; color:white; }"
            f" QHeaderView::section {{ background:#1e1e1e; color:{TEXT_DIM}; border:none;"
            " border-bottom:1px solid #2a2a2a; padding:4px 8px; font-size:11px; }")
        return t

    @staticmethod
    def _bloc(titre, table):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(20, 8, 20, 8)
        v.setSpacing(4)
        l = QLabel(titre)
        l.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px; font-weight:bold; letter-spacing:2px;")
        v.addWidget(l)
        v.addWidget(table, 1)
        return w

    # ── Chargement ──────────────────────────────────────────────────────────
    def on_show(self):
        self.charger()
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _auto(self):
        if self.isVisible():
            self.charger(silencieux=True)
        else:
            self._timer.stop()

    def charger(self, silencieux=False):
        if self._en_cours:
            return
        if not FICHIER_SECRET.exists():
            self._etat.setText(f"⚠ secret absent : {FICHIER_SECRET}")
            return
        self._en_cours = True
        if not silencieux:
            self._etat.setText("Chargement…")

        def fil():
            try:
                d = lire_stats()
                uids = {x.get("uid") for x in d.get("direct", []) + d.get("historique", [])}
                inconnus = {u for u in uids if u and u not in self._noms}
                if inconnus:
                    try:
                        self._noms.update(self._resoudre(inconnus) or {})
                    except Exception as e:
                        print(f"[Up admin] noms clients indisponibles ({e})")
                self._pont.recu.emit(d, None)
            except Exception as e:
                msg = str(e)
                if "403" in msg:
                    msg = "accès refusé : secret local différent de celui du serveur ?"
                self._pont.recu.emit(None, msg)

        threading.Thread(target=fil, name="up-stats", daemon=True).start()

    def _client(self, uid):
        return self._noms.get(uid) or (uid[:10] + "…" if uid else "?")

    def _sur_donnees(self, d, err):
        self._en_cours = False
        if err:
            self._etat.setText(f"⚠ {err}")
            return
        direct, hist = d.get("direct", []), d.get("historique", [])
        maintenant = d.get("maintenant") or datetime.now().timestamp()
        n_tel = sum(int(x.get("connectes", 0)) for x in direct)
        self._direct_lbl.setText(f"● {len(direct)} session(s) · {n_tel} téléphone(s) en ce moment"
                                 if direct else "")
        for cle, v in totaux(hist, direct).items():
            self._tuiles[cle].setText(f"{v:.1f}" if cle == "heures" else str(v))

        t = self._t_direct
        t.setRowCount(0)
        for x in sorted(direct, key=lambda x: -x.get("debut", 0)):
            self._ligne(t, [
                self._client(x.get("uid")), date_courte(x.get("debut")),
                duree(maintenant - x.get("debut", maintenant)),
                f"{x.get('connectes', 0)} / {x.get('cap', 0)}", x.get("pic", 0), x.get("total", 0),
                self._type(x), "✔ connecté" if x.get("mystrow") else "✖ absent",
            ], {7: VERT if x.get("mystrow") else ORANGE})

        t = self._t_hist
        t.setRowCount(0)
        for x in sorted(hist, key=lambda x: -x.get("debut", 0)):
            self._ligne(t, [
                date_courte(x.get("debut")), self._client(x.get("uid")), duree(x.get("duree_s")),
                f"{x.get('pic', 0)} / {x.get('cap', 0)}", x.get("total", 0), self._type(x),
                x.get("raison", ""),
            ], {3: ORANGE} if x.get("pic", 0) >= x.get("cap", 1) else {})
        self._etat.setText(f"{len(hist)} session(s) terminée(s) · mis à jour "
                           f"{datetime.now().strftime('%H:%M:%S')}")

    @staticmethod
    def _type(x):
        return ("Licence" if int(x.get("cap", 0)) > 1 else "Essai (aperçu)") + (" · QR permanent" if x.get("permanent") else "")

    @staticmethod
    def _ligne(t, cells, couleurs):
        i = t.rowCount()
        t.insertRow(i)
        for c, v in enumerate(cells):
            it = QTableWidgetItem(str(v))
            if c in couleurs:
                it.setForeground(QColor(couleurs[c]))
            t.setItem(i, c, it)
