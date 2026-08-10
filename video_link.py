"""
video_link.py — Base commune aux liaisons « regie video → lumiere ».

vMix et OBS posent exactement le meme probleme : un logiciel de regie signale
qu'une source vient de passer A L'ANTENNE, et MyStrow doit declencher l'action
lumiere que l'utilisateur a associee a cette source. Seuls changent le
protocole et le nom du declencheur :

    vMix : une ENTREE passe au programme   (declencheur = numero d'entree)
    OBS  : une SCENE devient active        (declencheur = nom de scene)

Tout le reste — vocabulaire d'actions, execution, persistance, dialogue de
reglage — est identique. Ce module le porte une fois ; vmix_link.py et
obs_link.py ne fournissent que leur client et la facon de nommer leurs
declencheurs.

Le sens reste A SENS UNIQUE dans les deux cas : la regie pilote MyStrow, jamais
l'inverse. C'est le realisateur qui mene le direct, et une liaison
bidirectionnelle ouvrirait une boucle de retour (MyStrow change une memoire, la
regie renvoie un evenement, MyStrow rejoue l'action) qu'il faudrait ensuite
garder.

UN DECLENCHEUR EST UN DICTIONNAIRE {'key', 'label'}
---------------------------------------------------
`key` est ce qui est enregistre dans la configuration et compare a l'evenement
recu ; `label` est ce qu'on affiche. Les deux clients normalisent vers cette
forme, ce qui permet au dialogue d'ignorer completement le fait qu'une clef
vMix est un entier et une clef OBS une chaine.
"""

import socket
import threading

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from core import guide_banner_encart
from i18n import tr

# Types d'action declenchables par la regie video.
# Vocabulaire repris du Stream Deck : l'utilisateur qui a deja regle ses
# boutons retrouve les memes mots ici.
ACTION_NONE      = "none"
ACTION_MEMORY    = "memory"
ACTION_EFFECT    = "effect"
ACTION_CARTOUCHE = "cartouche"

ACTION_LABELS = [
    (ACTION_NONE,      "— Rien —"),
    (ACTION_MEMORY,    "Memoire"),
    (ACTION_EFFECT,    "Effet"),
    (ACTION_CARTOUCHE, "Cartouche"),
]


# ---------------------------------------------------------------------------
# Liaison
# ---------------------------------------------------------------------------

class VideoLink(QObject):
    """Detient le client, la table de correspondance, et applique les actions."""

    #: Port par defaut, fourni par la sous-classe.
    DEFAULT_PORT = 0
    #: Type des clefs de correspondance (`int` pour vMix, `str` pour OBS).
    KEY_TYPE = str

    def __init__(self, window, client):
        super().__init__(window)
        self._window = window
        self.client = client
        self.enabled = False
        self.host = "127.0.0.1"
        self.port = self.DEFAULT_PORT
        # {clef de declencheur: {"type": ..., "value": ...}}
        self.mappings = {}

    # ── persistance (dans ~/.maestro_akai_config.json) ──────────────────────

    def to_config(self) -> dict:
        cfg = {
            "enabled": bool(self.enabled),
            "host": self.host,
            "port": int(self.port),
            # Les clefs JSON sont forcement des chaines
            "mappings": {str(k): dict(v) for k, v in self.mappings.items()},
        }
        cfg.update(self._extra_to_config())
        return cfg

    def from_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        self.enabled = bool(cfg.get("enabled", False))
        self.host = str(cfg.get("host", "127.0.0.1") or "127.0.0.1")
        try:
            self.port = int(cfg.get("port", self.DEFAULT_PORT) or self.DEFAULT_PORT)
        except (TypeError, ValueError):
            self.port = self.DEFAULT_PORT
        self.mappings = {}
        for k, v in (cfg.get("mappings") or {}).items():
            try:
                self.mappings[self.KEY_TYPE(k)] = dict(v)
            except (TypeError, ValueError):
                continue
        self._extra_from_config(cfg)

    def _extra_to_config(self) -> dict:
        """Champs propres a l'integration (mot de passe OBS, par exemple)."""
        return {}

    def _extra_from_config(self, cfg: dict):
        pass

    # ── cycle de vie ────────────────────────────────────────────────────────

    def apply(self):
        """Demarre ou arrete la liaison selon `enabled`."""
        if self.enabled:
            self._demarrer_client()
        else:
            self.client.stop()

    def _demarrer_client(self):
        """Sous-classe : appelle client.start(...) avec ses propres arguments."""
        raise NotImplementedError

    def stop(self):
        self.client.stop()

    # ── declenchement ───────────────────────────────────────────────────────

    def _on_trigger(self, clef):
        """Slot Qt appele dans le thread principal (signal emis par le reseau).

        Enveloppe try/except de bout en bout : une exception non rattrapee dans
        un slot Qt fait tomber tout le processus sous PySide6. Un nom de scene
        exotique ou une memoire effacee entre-temps ne doit pas emporter la
        console d'eclairage en plein direct.
        """
        try:
            self._declencher(self.mappings.get(self.KEY_TYPE(clef)))
        except Exception as exc:
            print(f"[{self.__class__.__name__}] action ignoree pour {clef!r} : {exc}")

    def _declencher(self, action):
        if not action:
            return
        w = self._window
        t = action.get("type", ACTION_NONE)
        val = action.get("value")

        if t == ACTION_MEMORY:
            col_s, _, row_s = str(val).partition(".")
            col, row = int(col_s) - 1, int(row_s) - 1     # 1-based → 0-based
            if 0 <= col <= 7 and 0 <= row <= 7:
                w.trigger_memory(col, row)

        elif t == ACTION_CARTOUCHE:
            idx = int(val)
            if 0 <= idx <= 3:
                w.on_cartouche_clicked(idx)

        elif t == ACTION_EFFECT:
            from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
            tous = list(BUILTIN_EFFECTS) + _load_custom_effects()
            cfg = next((e for e in tous if e.get("name") == val), None)
            if cfg is None:
                return                       # effet renomme ou supprime
            w.active_effect = val
            w.active_effect_config = cfg
            w.start_effect(val)


# ---------------------------------------------------------------------------
# Interrogation non bloquante des declencheurs
# ---------------------------------------------------------------------------

class _Sonde(QObject):
    """Execute une fonction reseau dans un thread : jusqu'a 4 s d'attente.

    Dans le thread Qt, cette attente gelerait la fenetre — et surtout la trame
    DMX a 25 fps, qui tourne sur le meme timer.
    """

    done   = Signal(list)
    failed = Signal(str)

    def run(self, fonction):
        """`fonction` ne prend aucun argument : les valeurs des widgets ont
        deja ete lues dans le thread Qt par l'appelant. Lire un QLineEdit
        depuis le thread reseau serait un acces concurrent a l'interface."""
        def _travail():
            try:
                self.done.emit(list(fonction()))
            except Exception as exc:
                self.failed.emit(str(exc))
        threading.Thread(target=_travail, daemon=True, name="video-probe").start()


# ---------------------------------------------------------------------------
# Recherche de la regie sur le reseau
# ---------------------------------------------------------------------------

def _ip_locales() -> list:
    """Adresses IPv4 de cette machine, la principale d'abord.

    Le connect() UDP n'envoie AUCUN paquet : il se contente de demander au
    systeme quelle interface servirait a joindre l'exterieur, ce qui designe
    la carte reellement utilisee. `gethostbyname` seul renvoie souvent
    127.0.0.1, ou l'adresse d'une carte virtuelle (VirtualBox, VPN, Hyper-V)
    qui n'est pas celle du reseau du spectacle.
    """
    trouvees = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("203.0.113.1", 9))   # reseau reserve a la documentation (RFC 5737)
        trouvees.append(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in trouvees and not ip.startswith("127."):
                trouvees.append(ip)
    except OSError:
        pass
    return trouvees


def _port_ouvert(hote: str, port: int, delai: float) -> bool:
    try:
        with socket.create_connection((hote, port), timeout=delai):
            return True
    except OSError:
        return False


def detecter_regie(port: int, delai_scan: float = 0.35) -> str:
    """Cherche qui ecoute sur `port` et renvoie son adresse. Leve si personne.

    Dans l'ordre : cette machine (boucle locale, puis ses adresses reseau),
    ensuite le reste du sous-reseau /24. Le sondage du sous-reseau est
    parallelise — en serie, 254 adresses a 0,35 s feraient 90 s d'attente.

    On teste 127.0.0.1 EN PREMIER a dessein : quand la regie tourne sur le
    meme PC, c'est l'adresse qui restera juste apres un changement de reseau
    ou un bail DHCP renouvele, alors que l'adresse locale du moment, elle,
    sera perimee.
    """
    for hote in ["127.0.0.1"] + _ip_locales():
        if _port_ouvert(hote, port, 0.6):
            return hote

    bases = {ip.rsplit(".", 1)[0] for ip in _ip_locales()}
    if not bases:
        raise ConnectionError(f"aucun reseau detecte sur cette machine")

    resultats = []
    verrou = threading.Lock()

    def _tester(adresse):
        if _port_ouvert(adresse, port, delai_scan):
            with verrou:
                resultats.append(adresse)

    fils = []
    for base in bases:
        for n in range(1, 255):
            adresse = f"{base}.{n}"
            t = threading.Thread(target=_tester, args=(adresse,), daemon=True)
            t.start()
            fils.append(t)
    for t in fils:
        t.join(timeout=delai_scan + 1.0)

    if not resultats:
        raise ConnectionError(
            f"personne n'ecoute sur le port {port}, ni sur ce PC ni sur le "
            f"reseau local. La regie est-elle lancee, serveur active ?")
    resultats.sort(key=lambda ip: [int(x) for x in ip.split(".")])
    return resultats[0]


# ---------------------------------------------------------------------------
# Dialogue de configuration
# ---------------------------------------------------------------------------

# Partage par les dialogues vMix et OBS, mais aussi par celui de la manette :
# ce sont tous des reglages de controle externe, ils doivent se ressembler.
STYLE_DIALOGUE = """
QDialog { background: #0f0f0f; }
QLabel { color: #ddd; background: transparent; border: none; }
QLineEdit, QSpinBox, QComboBox {
    background: #1a1a1a; color: #ddd; border: 1px solid #2a2a2a;
    border-radius: 4px; padding: 5px;
}
QPushButton {
    background: #1f1f1f; color: #ddd; border: 1px solid #2f2f2f;
    border-radius: 5px; padding: 7px 16px;
}
QPushButton:hover { background: #2a2a2a; }
QPushButton#primary { background: #00d4ff; color: #000; font-weight: bold; border: none; }
QPushButton#primary:hover { background: #33ddff; }
QTableWidget {
    background: #141414; color: #ddd; border: 1px solid #2a2a2a;
    gridline-color: #222;
}
QHeaderView::section {
    background: #1a1a1a; color: #999; border: none; padding: 6px;
}
"""


class _ComboSansMolette(QComboBox):
    """Liste deroulante qui laisse passer la molette au lieu de changer de valeur.

    Ces combos vivent dans les cellules d'un tableau qui defile. Avec le
    comportement Qt par defaut, faire defiler la liste des declencheurs modifiait
    silencieusement l'action de la ligne survolee — on croyait avoir juste fait
    defiler, et le reglage avait change sans un mot. `ignore()` fait remonter
    l'evenement au tableau, qui defile normalement ; la valeur ne se change plus
    qu'au clic ou au clavier, deliberement.

    `StrongFocus` complete la manoeuvre : sans lui la combo prend le focus au
    simple passage de la molette (`WheelFocus` par defaut) et le piege revient
    des le deuxieme cran.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class VideoDialog(QDialog):
    """Connexion a la regie + correspondance declencheur → action lumiere."""

    # ── a fournir par la sous-classe ────────────────────────────────────────
    CLE_TITRE   = ""      # cle i18n du titre de fenetre
    CLE_ENTETE  = ""      # cle i18n du gros titre
    CLE_INTRO   = ""      # cle i18n du paragraphe d'explication
    CLE_ASTUCE  = ""      # cle i18n affichee quand la liste est vide
    CLE_ACTIVER = ""      # cle i18n de la case « activer la liaison »
    CLE_TEASER  = "vlink_guide_teaser"  # cle i18n de l'encart guide (nomme la regie)
    COL_DECLENCHEUR = ""  # en-tete de la 1re colonne (« Entree vMix », « Scene OBS »)
    # Un seul guide pour les deux regies : la marche a suivre est la meme des
    # deux cotes (activer le serveur, relever l'adresse, associer les sources),
    # et l'article traite OBS et vMix l'un apres l'autre.
    URL_GUIDE = "https://mystrow.fr/regie-video-obs-vmix-mystrow"

    def __init__(self, window, link: VideoLink):
        super().__init__(window)
        self._window = window
        self._link = link
        self._declencheurs = list(self._declencheurs_du_client())

        self.setWindowTitle(tr(self.CLE_TITRE))
        self.setMinimumWidth(640)
        self.setStyleSheet(STYLE_DIALOGUE)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        titre = QLabel(tr(self.CLE_ENTETE))
        f = QFont(); f.setPointSize(13); f.setBold(True)
        titre.setFont(f)
        root.addWidget(titre)

        sous = QLabel(tr(self.CLE_INTRO))
        sous.setStyleSheet("color:#888; font-size:11px;")
        sous.setWordWrap(True)
        root.addWidget(sous)

        # Encart vers le guide, en HAUT comme celui de la sortie DMX : la moitie
        # du reglage se joue dans OBS ou vMix — activer le serveur, relever le
        # mot de passe — et aucun libelle de cette fenetre ne peut le montrer.
        root.addWidget(guide_banner_encart(
            tr(self.CLE_TEASER), self.URL_GUIDE, tr("vlink_guide_link")))

        # ── Connexion ───────────────────────────────────────────────────────
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel(tr("vlink_host")))
        self._hote = QLineEdit(link.host)
        self._hote.setFixedWidth(150)
        ligne.addWidget(self._hote)
        # « Detecter » plutot qu'une adresse en dur : celle qu'affiche la regie
        # est valable aujourd'hui, sur ce reseau, avec ce bail DHCP. Chercher
        # qui ecoute vraiment reste juste apres un changement de box, et
        # fonctionne aussi quand la regie tourne sur un AUTRE poste.
        self._btn_detect = QPushButton(tr("vlink_detect"))
        self._btn_detect.setToolTip(tr("vlink_detect_hint"))
        self._btn_detect.clicked.connect(self._detecter)
        ligne.addWidget(self._btn_detect)
        ligne.addWidget(QLabel(tr("vlink_port")))
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(int(link.port))
        self._port.setFixedWidth(90)
        ligne.addWidget(self._port)
        self._champs_supplementaires(ligne)
        self._btn_test = QPushButton(tr("vlink_test_conn"))
        self._btn_test.clicked.connect(self._tester)
        ligne.addWidget(self._btn_test)
        ligne.addStretch()
        root.addLayout(ligne)

        self._etat = QLabel("")
        self._etat.setStyleSheet("color:#888; font-size:11px;")
        # Un echec de connexion explique quoi faire (« lancez OBS, puis Outils >
        # ... »), ce qui ne tient pas sur une ligne. Sans retour a la ligne, la
        # consigne etait coupee net et le dialogue s'elargissait pour rien.
        self._etat.setWordWrap(True)
        root.addWidget(self._etat)
        connecte = link.client.is_connected()
        self._maj_etat(connecte, "Connecte" if connecte else "Non connecte")

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#222;")
        root.addWidget(sep)

        # ── Table de correspondance ─────────────────────────────────────────
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(
            [self.COL_DECLENCHEUR, tr("vlink_col_action"), tr("vlink_col_target")])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(1, 130)
        self._table.setColumnWidth(2, 200)
        root.addWidget(self._table)

        self._vide = QLabel(tr(self.CLE_ASTUCE))
        self._vide.setStyleSheet("color:#666; font-size:11px;")
        self._vide.setWordWrap(True)
        root.addWidget(self._vide)

        # ── Activation + boutons ────────────────────────────────────────────
        bas = QHBoxLayout()
        self._actif = QCheckBox(tr(self.CLE_ACTIVER))
        self._actif.setChecked(link.enabled)
        self._actif.setStyleSheet("color:#ddd;")
        bas.addWidget(self._actif)
        bas.addStretch()
        annuler = QPushButton(tr("vlink_cancel"))
        annuler.clicked.connect(self.reject)
        bas.addWidget(annuler)
        ok = QPushButton(tr("vlink_save"))
        ok.setObjectName("primary")
        ok.clicked.connect(self._enregistrer)
        bas.addWidget(ok)
        root.addLayout(bas)

        # Etat de connexion en direct pendant que le dialogue est ouvert
        link.client.connection_changed.connect(self._maj_etat)
        self._connecter_declencheurs()

        self._sonde = _Sonde(self)
        self._sonde.done.connect(self._sonde_ok)
        self._sonde.failed.connect(self._sonde_ko)

        # Sonde distincte : la recherche reseau peut durer plusieurs secondes
        # et ne doit pas etre confondue avec un test de connexion en cours.
        self._sonde_detect = _Sonde(self)
        self._sonde_detect.done.connect(self._detect_ok)
        self._sonde_detect.failed.connect(self._detect_ko)

        if self._declencheurs:
            self._peupler(self._declencheurs)

    # ── detection de l'adresse ──────────────────────────────────────────────

    def _detecter(self):
        port = self._port.value()          # lu dans le thread Qt
        self._btn_detect.setEnabled(False)
        self._btn_test.setEnabled(False)
        self._maj_etat(False, tr("vlink_detecting", port=port))
        # `_Sonde` attend une liste : on emballe l'adresse trouvee.
        self._sonde_detect.run(lambda: [detecter_regie(port)])

    def _detect_ok(self, resultat: list):
        self._btn_detect.setEnabled(True)
        self._btn_test.setEnabled(True)
        adresse = resultat[0]
        self._hote.setText(adresse)
        self._maj_etat(True, tr("vlink_detect_ok", host=adresse))

    def _detect_ko(self, message: str):
        self._btn_detect.setEnabled(True)
        self._btn_test.setEnabled(True)
        self._maj_etat(False, tr("vlink_detect_ko", err=message))

    # ── points d'extension ──────────────────────────────────────────────────

    def _champs_supplementaires(self, ligne):
        """Widgets propres a l'integration, inseres dans la ligne de connexion."""
        pass

    def _declencheurs_du_client(self) -> list:
        """[{'key', 'label'}] connus du client (liste eventuellement vide)."""
        raise NotImplementedError

    def _connecter_declencheurs(self):
        """Branche le signal du client qui publie la liste des declencheurs."""
        raise NotImplementedError

    def _fabriquer_sonde(self):
        """Renvoie une fonction SANS argument qui interroge la regie.

        Les valeurs des widgets doivent etre lues MAINTENANT (thread Qt) et
        capturees dans la fermeture : la fonction, elle, tournera dans un
        thread reseau.
        """
        raise NotImplementedError

    def _enregistrer_extras(self):
        """Recopie les champs supplementaires dans la liaison, a la validation."""
        pass

    # ── etat ────────────────────────────────────────────────────────────────

    def _maj_etat(self, connecte: bool, message: str):
        couleur = "#5f5" if connecte else "#888"
        puce = "●" if connecte else "○"
        self._etat.setText(f"{puce}  {message}")
        self._etat.setStyleSheet(f"color:{couleur}; font-size:11px;")

    def _tester(self):
        self._btn_test.setEnabled(False)
        self._maj_etat(False, tr("vlink_connecting"))
        self._sonde.run(self._fabriquer_sonde())

    def _sonde_ok(self, declencheurs: list):
        self._btn_test.setEnabled(True)
        self._maj_etat(True, tr("vlink_probe_ok", n=len(declencheurs)))
        self._peupler(declencheurs)

    def _sonde_ko(self, message: str):
        self._btn_test.setEnabled(True)
        self._maj_etat(False, tr("vlink_probe_ko", err=message))

    # ── table ───────────────────────────────────────────────────────────────

    def _memoires_disponibles(self) -> list:
        """[(identifiant « 1.1 », libelle affiche)] pour les memoires definies."""
        out = []
        mems = getattr(self._window, "memories", []) or []
        for col in range(min(8, len(mems))):
            for row in range(min(8, len(mems[col]))):
                mem = mems[col][row]
                if mem is None:
                    continue
                ident = f"{col + 1}.{row + 1}"
                nom = mem.get("name") if isinstance(mem, dict) else None
                out.append((ident, f"MEM {ident}" + (f" — {nom}" if nom else "")))
        return out

    def _effets_disponibles(self) -> list:
        try:
            from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
            return [e.get("name", "") for e in list(BUILTIN_EFFECTS) + _load_custom_effects()
                    if e.get("name")]
        except Exception:
            return []

    def _peupler(self, declencheurs: list):
        self._declencheurs = list(declencheurs)
        self._vide.setVisible(not declencheurs)
        self._table.setRowCount(0)
        for d in declencheurs:
            clef = d["key"]
            ligne = self._table.rowCount()
            self._table.insertRow(ligne)

            item = QTableWidgetItem(d["label"])
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, clef)
            self._table.setItem(ligne, 0, item)

            combo = _ComboSansMolette()
            for code, libelle in ACTION_LABELS:
                combo.addItem(libelle, code)
            cible = _ComboSansMolette()
            self._table.setCellWidget(ligne, 1, combo)
            self._table.setCellWidget(ligne, 2, cible)

            actuel = self._link.mappings.get(clef, {})
            idx = combo.findData(actuel.get("type", ACTION_NONE))
            combo.setCurrentIndex(max(0, idx))
            self._remplir_cible(cible, combo.currentData(), actuel.get("value"))
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, t=cible: self._remplir_cible(t, c.currentData(), None))

    def _remplir_cible(self, cible: QComboBox, type_action: str, valeur):
        cible.clear()
        if type_action == ACTION_MEMORY:
            for ident, libelle in self._memoires_disponibles():
                cible.addItem(libelle, ident)
        elif type_action == ACTION_EFFECT:
            for nom in self._effets_disponibles():
                cible.addItem(nom, nom)
        elif type_action == ACTION_CARTOUCHE:
            for i in range(4):
                cible.addItem(tr("vlink_cartouche", n=i + 1), i)
        cible.setEnabled(cible.count() > 0)
        if valeur is not None:
            i = cible.findData(valeur)
            if i >= 0:
                cible.setCurrentIndex(i)

    # ── validation ──────────────────────────────────────────────────────────

    def _enregistrer(self):
        mappings = {}
        for ligne in range(self._table.rowCount()):
            clef = self._table.item(ligne, 0).data(Qt.UserRole)
            combo = self._table.cellWidget(ligne, 1)
            cible = self._table.cellWidget(ligne, 2)
            code = combo.currentData()
            if code == ACTION_NONE or cible.count() == 0:
                continue
            mappings[self._link.KEY_TYPE(clef)] = {"type": code, "value": cible.currentData()}

        # Les declencheurs non listes (regie fermee au moment du reglage)
        # gardent leur correspondance : effacer la table entiere parce qu'on
        # n'a pas pu joindre la regie ferait perdre le patch d'un show deja
        # regle.
        if self._declencheurs:
            connus = {self._link.KEY_TYPE(d["key"]) for d in self._declencheurs}
            for clef, act in self._link.mappings.items():
                if clef not in connus:
                    mappings[clef] = act
        else:
            mappings = dict(self._link.mappings)

        self._link.mappings = mappings
        self._link.host = self._hote.text().strip() or "127.0.0.1"
        self._link.port = self._port.value()
        self._link.enabled = self._actif.isChecked()
        self._enregistrer_extras()
        self._link.apply()
        try:
            self._window._save_akai_config_auto()
        except Exception:
            pass
        self.accept()
