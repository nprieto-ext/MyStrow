"""
gamepad_link.py — Ce que MyStrow FAIT des sticks de la manette, et son reglage.

gamepad_client.py lit le peripherique ; ce module decide de l'effet. Comme pour
les regies video, la separation permet de tester toute la logique de mouvement
sans manette branchee.

LE STICK COMMANDE UNE VITESSE, PAS UNE POSITION
-----------------------------------------------
C'est LE choix structurant. Un stick est rappele au centre par un ressort : si
sa position commandait la position absolue de la lyre, lacher le stick
ramenerait le faisceau au centre du plateau. Inutilisable.

La deflexion commande donc une VITESSE : on pousse pour deplacer, on relache
pour s'arreter la ou on est. C'est exactement le comportement d'une trackball
ou d'un encodeur de console.

DEUX PIEGES QUI ONT DICTE LE CODE
----------------------------------
1. **La zone morte est obligatoire.** Un stick use ne revient jamais exactement
   a zero. Sans zone morte, les lyres deriveraient lentement toute la soiree
   sans que personne ne touche a rien — et le temps qu'on comprenne d'ou ca
   vient, le show est fini.
2. **Il faut accumuler les fractions.** `p.pan` est un entier sur 16 bits. Au
   sondage (50 Hz) et en poussant doucement, le deplacement d'une image vaut
   moins d'une unite : tronque a l'entier, il vaut zero, et la lyre ne bouge
   JAMAIS tant qu'on ne pousse pas fort. On garde donc le reste fractionnaire
   d'une image sur l'autre.
"""

import math
import time

from PySide6.QtCore import QObject
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

import gamepad_boutons as gb
from gamepad_client import GamepadClient, lister_manettes
from video_link import STYLE_DIALOGUE
from core import guide_banner_encart
from i18n import tr

# Guide en ligne : manettes compatibles, reglages et cas de la manette PS3.
URL_GUIDE = "https://mystrow.fr/manette-jeu-lyres-mystrow"

# Course complete d'un axe pan/tilt (16 bits).
COURSE = 65535

# Reglages par defaut.
ZONE_MORTE_DEFAUT = 0.12      # 12 % — au-dela d'une usure normale de stick
BALAYAGE_DEFAUT_S = 3.0       # secondes pour parcourir toute la course a fond
RATIO_FIN = 8.0               # le stick droit est 8x plus lent que le gauche

# Au-dela, on considere qu'il y a eu un gel (chargement de media, fenetre
# deplacee...) : integrer un dt enorme ferait sauter la lyre a l'autre bout du
# plateau d'un seul coup.
DT_MAX = 0.10

CIBLE_SELECTION = "selection"
CIBLE_TOUTES    = "toutes"
# Cible « un groupe » : « group:douche1 ». Le prefixe evite toute collision avec
# les deux valeurs ci-dessus si un jour quelqu'un nomme un groupe « toutes ».
CIBLE_GROUPE    = "group:"

_TYPES_LYRE = ("Moving Head", "Lyre")


# ---------------------------------------------------------------------------
# Logique de mouvement (pure, donc testable sans manette)
# ---------------------------------------------------------------------------

def courbe(v: float, zone_morte: float) -> float:
    """Axe brut (-1..1) → commande utile (-1..1).

    Deux effets :
      - sous la zone morte, la sortie est nulle ;
      - au-dela, la reponse est QUADRATIQUE, ce qui donne du doigte pres du
        centre (pointer une face a 20 m) tout en gardant de la vitesse a fond
        de course (traverser le plateau).

    La renormalisation `(a - zm) / (1 - zm)` est indispensable : sans elle, la
    sortie sauterait d'un coup a la valeur correspondant a la zone morte des
    qu'on la franchit, et la lyre partirait par a-coups.
    """
    zone_morte = max(0.0, min(0.9, zone_morte))
    a = abs(v)
    if a <= zone_morte:
        return 0.0
    u = (a - zone_morte) / (1.0 - zone_morte)
    return math.copysign(u * u, v)


def commande_axe(principal: float, fin: float, zone_morte: float,
                 ratio_fin: float = RATIO_FIN) -> float:
    """Combine le stick gauche (grossier) et le stick droit (fin) sur un axe."""
    return courbe(principal, zone_morte) + courbe(fin, zone_morte) / max(1.0, ratio_fin)


def deplacement(commande: float, balayage_s: float, dt: float) -> float:
    """Commande (-1..1) → deplacement en unites DMX 16 bits pour cette image."""
    if not commande:
        return 0.0
    balayage_s = max(0.1, balayage_s)
    return commande * (COURSE / balayage_s) * dt


def cible_valide(brut) -> str:
    """Valeur de cible relue du fichier de config → cible exploitable.

    Un groupe supprime depuis le dernier enregistrement reste accepte ici :
    `cibles()` renverra simplement une liste vide, ce qui est exactement le
    comportement d'une selection vide. L'effacer d'office ferait pire — on
    rouvrirait un show sur « sélection » sans que rien ne le dise.
    """
    if isinstance(brut, str):
        if brut in (CIBLE_SELECTION, CIBLE_TOUTES):
            return brut
        if brut.startswith(CIBLE_GROUPE) and len(brut) > len(CIBLE_GROUPE):
            return brut
    return CIBLE_SELECTION


def bornes(lo, hi) -> tuple:
    """Limites effectives d'un axe : celles de la lyre, ramenees dans la course.

    Les deux bornages comptent : `pan_min`/`pan_max` sont les limites reglees
    par l'utilisateur (eviter le public, un mur), la course 0..65535 est la
    limite du materiel. Une limite mal reglee ne doit pas permettre de sortir
    de la seconde.
    """
    lo = max(0, min(COURSE, int(lo)))
    hi = max(0, min(COURSE, int(hi)))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def borner(valeur: float, lo, hi) -> int:
    b, h = bornes(lo, hi)
    return int(max(b, min(h, valeur)))


def avancer(position: int, reste: float, delta: float, lo, hi) -> tuple:
    """Avance un axe d'un `delta` fractionnaire. Renvoie (position, reste).

    C'est ici que se joue le piege n°2 decrit en tete de module. Deux cas se
    ressemblent mais demandent l'inverse l'un de l'autre :

      - le deplacement de l'image vaut moins d'une unite DMX : la position ne
        change pas, mais il FAUT garder le reste, sinon la lyre reste figee
        pour toujours des qu'on pousse doucement ;
      - la lyre est en butee et on pousse encore dessus : la position ne change
        pas non plus, mais il faut JETER le reste, sinon il grossit sans fin et
        la lyre refuse de repartir quand on inverse le stick — il faudrait
        d'abord « rembourser » tout ce qu'on a pousse dans le vide.

    Les distinguer sur « la position a-t-elle bouge ? » les confond, justement
    parce que dans les deux cas elle n'a pas bouge. Le bon critere est : est-on
    colle a une limite ET pousse-t-on encore dans cette direction.
    """
    lo, hi = bornes(lo, hi)
    total = position + reste + delta
    nouvelle = int(max(lo, min(hi, total)))
    r = total - nouvelle
    if (nouvelle >= hi and r > 0) or (nouvelle <= lo and r < 0):
        r = 0.0
    return nouvelle, r


# ---------------------------------------------------------------------------
# Liaison
# ---------------------------------------------------------------------------

class GamepadLink(QObject):
    """Applique les sticks au pan/tilt des lyres visees."""

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self.client = GamepadClient(window)

        self.enabled     = False
        self.zone_morte  = ZONE_MORTE_DEFAUT
        self.balayage_s  = BALAYAGE_DEFAUT_S
        self.invert_pan  = False
        self.invert_tilt = False
        self.cible       = CIBLE_SELECTION

        # Boutons : voir gamepad_boutons.py. Volontairement independant des
        # sticks — on peut vouloir les raccourcis sans jamais bouger une lyre,
        # et l'inverse est vrai aussi.
        self.boutons_enabled = True
        self.pages = [{} for _ in range(gb.NB_PAGES)]
        # Vrai pendant que le dialogue de reglage est ouvert : on y designe les
        # touches en appuyant dessus, il ne faut donc RIEN declencher. Sans ca,
        # regler la manette pendant un show rappellerait des memoires en direct.
        self.suspendu = False

        self._dernier_t = None
        # {id(projecteur): [reste_pan, reste_tilt]} — voir le piege n°2 en tete
        # de module.
        self._restes = {}

        self.client.axes_changed.connect(self._on_axes)
        self.client.bouton_presse.connect(self._on_bouton)

    # ── persistance (dans ~/.maestro_akai_config.json) ──────────────────────

    def to_config(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "deadzone": float(self.zone_morte),
            "sweep_s": float(self.balayage_s),
            "invert_pan": bool(self.invert_pan),
            "invert_tilt": bool(self.invert_tilt),
            "target": self.cible,
            "buttons_enabled": bool(self.boutons_enabled),
            "buttons": gb.ecrire_pages(self.pages),
        }

    def from_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        self.enabled = bool(cfg.get("enabled", False))
        try:
            self.zone_morte = max(0.0, min(0.9, float(cfg.get("deadzone", ZONE_MORTE_DEFAUT))))
        except (TypeError, ValueError):
            self.zone_morte = ZONE_MORTE_DEFAUT
        try:
            self.balayage_s = max(0.1, float(cfg.get("sweep_s", BALAYAGE_DEFAUT_S)))
        except (TypeError, ValueError):
            self.balayage_s = BALAYAGE_DEFAUT_S
        self.invert_pan  = bool(cfg.get("invert_pan", False))
        self.invert_tilt = bool(cfg.get("invert_tilt", False))
        self.cible = cible_valide(cfg.get("target"))
        self.boutons_enabled = bool(cfg.get("buttons_enabled", True))
        self.pages = gb.lire_pages(cfg.get("buttons"))

    def a_des_assignations(self) -> bool:
        return any(bool(p) for p in self.pages)

    # ── cycle de vie ────────────────────────────────────────────────────────

    def apply(self):
        """Le client tourne des que la liaison sert a quelque chose. Le
        mouvement, lui, est en plus conditionne a `enabled` dans `_on_axes` —
        ce qui permet au dialogue d'afficher les sticks en direct sans bouger
        les lyres.

        Les deux usages comptent : quelqu'un qui n'assigne que des boutons ne
        cochera jamais « pan/tilt au stick », et sa manette doit quand meme
        etre lue."""
        if self.enabled or (self.boutons_enabled and self.a_des_assignations()):
            self.client.start()
        else:
            self.client.stop()

    def stop(self):
        self.client.stop()

    # ── cibles ──────────────────────────────────────────────────────────────

    def groupes_de_lyres(self) -> list:
        """[(nom_du_groupe, nombre_de_lyres)] — groupes proposables comme cible.

        Seuls les groupes qui contiennent AU MOINS UNE lyre : proposer « face »
        quand il n'y a que des PAR LED dedans donnerait une cible qui ne bouge
        jamais, sans rien pour dire pourquoi. L'ordre est celui du patch, donc
        celui du plan de feu.
        """
        ordre, compte = [], {}
        for p in (getattr(self._window, "projectors", None) or []):
            if getattr(p, "fixture_type", "") not in _TYPES_LYRE:
                continue
            g = getattr(p, "group", "") or ""
            if not g:
                continue
            if g not in compte:
                ordre.append(g)
            compte[g] = compte.get(g, 0) + 1
        return [(g, compte[g]) for g in ordre]

    def cibles(self) -> list:
        """Lyres a piloter. Jamais autre chose qu'une lyre : deplacer le
        « pan » d'un PAR LED n'a aucun sens."""
        projos = getattr(self._window, "projectors", None) or []
        lyres = [p for p in projos
                 if getattr(p, "fixture_type", "") in _TYPES_LYRE]
        if self.cible == CIBLE_TOUTES:
            return lyres

        if self.cible.startswith(CIBLE_GROUPE):
            groupe = self.cible[len(CIBLE_GROUPE):]
            return [p for p in lyres if getattr(p, "group", "") == groupe]

        pdf = getattr(self._window, "plan_de_feu", None)
        selection = getattr(pdf, "selected_lamps", None)
        if not selection:
            return []
        # Meme convention d'identite que le plan de feu : un compteur par
        # groupe (cf. core.projector_selection_keys).
        compteurs, par_cle = {}, {}
        for p in projos:
            g = getattr(p, "group", "")
            li = compteurs.get(g, 0)
            compteurs[g] = li + 1
            par_cle[(g, li)] = p
        ordre = getattr(pdf, "selected_lamps_ordered", None) or list(selection)
        out, vus = [], set()
        for cle in ordre:
            if cle not in selection or cle in vus:
                continue
            p = par_cle.get(cle)
            if p is not None and getattr(p, "fixture_type", "") in _TYPES_LYRE:
                out.append(p)
                vus.add(cle)
        return out

    # ── application ─────────────────────────────────────────────────────────

    def _on_axes(self, lx: float, ly: float, rx: float, ry: float):
        """Slot Qt appele 50x/s. Enveloppe try/except : une exception non
        rattrapee dans un slot fait tomber tout le processus sous PySide6."""
        try:
            self._do_axes(lx, ly, rx, ry)
        except Exception as exc:
            print(f"[Manette] mouvement ignore : {exc}")

    def _do_axes(self, lx, ly, rx, ry):
        maintenant = time.monotonic()
        precedent, self._dernier_t = self._dernier_t, maintenant
        dt = min(DT_MAX, maintenant - precedent) if precedent is not None else 0.02

        if not self.enabled:
            return

        cmd_pan  = commande_axe(lx, rx, self.zone_morte)
        # L'axe Y de SDL est NEGATIF vers le haut. On le retourne pour que
        # pousser le stick en avant leve le faisceau : c'est le sens attendu,
        # et `invert_tilt` reste la pour les lyres montees a l'envers.
        cmd_tilt = -commande_axe(ly, ry, self.zone_morte)

        if self.invert_pan:
            cmd_pan = -cmd_pan
        if self.invert_tilt:
            cmd_tilt = -cmd_tilt

        # Sticks au repos : on ne touche a RIEN. Important — ecrire pan/tilt
        # 50x/s sans raison entrerait en concurrence avec les effets, les
        # memoires et le REC Lumiere, qui ecrivent les memes attributs.
        if cmd_pan == 0.0 and cmd_tilt == 0.0:
            return

        d_pan  = deplacement(cmd_pan,  self.balayage_s, dt)
        d_tilt = deplacement(cmd_tilt, self.balayage_s, dt)
        self.appliquer(d_pan, d_tilt)

    def appliquer(self, d_pan: float, d_tilt: float):
        cibles = self.cibles()
        if not cibles:
            return

        # Couper toute transition pan/tilt en cours sur ces lyres. Sans ca, le
        # timer d'animation et la manette ecrivent tous les deux `p.pan` :
        # l'anti-pattern des deux writers, qui se voit a l'ecran comme un
        # faisceau qui tremble ou revient en arriere.
        transitions = getattr(self._window, "_pan_tilt_transitions", None)

        for p in cibles:
            if transitions is not None:
                transitions.pop(id(p), None)

            reste = self._restes.get(id(p))
            if reste is None:
                reste = self._restes[id(p)] = [0.0, 0.0]

            if d_pan:
                p.pan, reste[0] = avancer(
                    getattr(p, "pan", COURSE // 2), reste[0], d_pan,
                    getattr(p, "pan_min", 0), getattr(p, "pan_max", COURSE))
            if d_tilt:
                p.tilt, reste[1] = avancer(
                    getattr(p, "tilt", COURSE // 2), reste[1], d_tilt,
                    getattr(p, "tilt_min", 0), getattr(p, "tilt_max", COURSE))

        maj = getattr(self._window, "send_dmx_update", None)
        if callable(maj):
            maj()

    # ── boutons ─────────────────────────────────────────────────────────────

    def page_courante(self) -> int:
        """Page d'assignations active — 2e page tant que le modificateur est
        tenu. On lit l'etat du modificateur AU MOMENT DE L'APPUI de l'autre
        touche, jamais un souvenir : c'est ce qui rend le geste « L2 + croix »
        insensible a l'ordre exact des deux fronts."""
        return 1 if self.client.est_enfonce(gb.MODIFICATEUR) else 0

    def _on_bouton(self, bid: str):
        """Slot Qt. Enveloppe try/except : une exception non rattrapee dans un
        slot fait tomber tout le processus sous PySide6, et une memoire mal
        formee ne doit pas emporter la console en plein show."""
        try:
            self._do_bouton(bid)
        except Exception as exc:
            print(f"[Manette] action ignoree ({bid}) : {exc}")

    def _do_bouton(self, bid: str):
        if bid == gb.MODIFICATEUR:
            return  # il ne fait que changer de page
        if not self.boutons_enabled or self.suspendu:
            return
        action = self.pages[self.page_courante()].get(bid)
        if action:
            gb.appliquer_action(self._window, action)


# ---------------------------------------------------------------------------
# Dialogue de configuration
# ---------------------------------------------------------------------------

class GamepadDialog(QDialog):
    """Reglage de la manette, avec apercu en direct des sticks."""

    def __init__(self, window, link: GamepadLink):
        super().__init__(window)
        self._window = window
        self._link = link

        self.setWindowTitle(tr("gp_title"))
        self.setMinimumWidth(560)
        self.setStyleSheet(STYLE_DIALOGUE)

        # `racine` porte ce qui vaut pour les DEUX onglets : le peripherique et
        # son etat. `root` sera le contenu de l'onglet « sticks ».
        racine = QVBoxLayout(self)
        racine.setContentsMargins(18, 16, 18, 16)
        racine.setSpacing(12)

        titre = QLabel(tr("gp_header"))
        f = QFont(); f.setPointSize(13); f.setBold(True)
        titre.setFont(f)
        racine.addWidget(titre)

        # Encart vers le guide, en HAUT comme pour la regie video : le sujet
        # deborde de cette fenetre — quelle manette acheter, et le cas de la
        # PS3 qui demande un pilote Windows. Aucun libelle d'ici ne peut le dire.
        racine.addWidget(guide_banner_encart(
            tr("gp_guide_teaser"), URL_GUIDE, tr("vlink_guide_link")))

        # ── Peripherique ────────────────────────────────────────────────────
        self._etat = QLabel("")
        self._etat.setStyleSheet("color:#888; font-size:11px;")
        racine.addWidget(self._etat)

        # Une manette peut etre parfaitement reconnue et n'envoyer strictement
        # rien (DualShock 3 sous Windows). Sans cette ligne, l'utilisateur voit
        # une pastille verte et des barres qui ne bougent pas, sans rien pour
        # lui dire ou chercher.
        self._alerte = QLabel("")
        self._alerte.setWordWrap(True)
        self._alerte.setStyleSheet("color:#ffb84d; font-size:11px;")
        self._alerte.setVisible(False)
        racine.addWidget(self._alerte)

        ligne_dev = QHBoxLayout()
        self._btn_detect = QPushButton(tr("gp_detect"))
        self._btn_detect.clicked.connect(self._detecter)
        ligne_dev.addWidget(self._btn_detect)
        ligne_dev.addStretch()
        racine.addLayout(ligne_dev)

        # ── Onglets ─────────────────────────────────────────────────────────
        # Pas de `setDocumentMode` : il ecrase la bordure et le soulignement de
        # l'onglet actif, et les deux onglets deviennent alors indiscernables.
        onglets = QTabWidget()
        racine.addWidget(onglets, 1)

        # « Boutons » EN PREMIER : c'est l'onglet qu'on ouvre pour preparer un
        # show (assigner ses memoires), alors que les reglages de stick se font
        # une fois pour toutes le jour ou on branche la manette.
        onglets.addTab(self._construire_onglet_boutons(), tr("gpb_tab_buttons"))

        page_sticks = QWidget()
        root = QVBoxLayout(page_sticks)
        root.setContentsMargins(4, 12, 4, 4)
        root.setSpacing(12)
        onglets.addTab(page_sticks, tr("gpb_tab_sticks"))

        # L'explication du stick vit DANS son onglet : au niveau du dialogue,
        # elle laisserait croire que la fenetre ne parle que de pan/tilt.
        intro = QLabel(tr("gp_intro"))
        intro.setStyleSheet("color:#888; font-size:11px;")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # ── Apercu en direct ────────────────────────────────────────────────
        # Affiche la commande APRES zone morte et courbe : on voit donc
        # directement l'effet du reglage, ce qu'une valeur brute ne montrerait
        # pas. Une barre qui reste a zero quand on effleure le stick, c'est la
        # zone morte qui fait son travail.
        root.addWidget(self._petit_titre(tr("gp_preview")))
        self._barre_pan  = self._barre()
        self._barre_tilt = self._barre()
        for lib, barre in ((tr("gp_pan"), self._barre_pan), (tr("gp_tilt"), self._barre_tilt)):
            l = QHBoxLayout()
            e = QLabel(lib); e.setFixedWidth(50)
            l.addWidget(e); l.addWidget(barre)
            root.addLayout(l)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color:#222;")
        root.addWidget(sep2)

        # ── Reglages ────────────────────────────────────────────────────────
        l_zm = QHBoxLayout()
        l_zm.addWidget(QLabel(tr("gp_deadzone")))
        self._zm = QSlider(Qt.Horizontal)
        self._zm.setRange(0, 40)
        self._zm.setValue(int(round(link.zone_morte * 100)))
        self._zm.valueChanged.connect(
            lambda v: self._lbl_zm.setText(f"{v} %"))
        l_zm.addWidget(self._zm)
        self._lbl_zm = QLabel(f"{self._zm.value()} %")
        self._lbl_zm.setFixedWidth(46)
        l_zm.addWidget(self._lbl_zm)
        root.addLayout(l_zm)

        l_v = QHBoxLayout()
        l_v.addWidget(QLabel(tr("gp_sweep")))
        self._sweep = QDoubleSpinBox()
        self._sweep.setRange(0.5, 15.0)
        self._sweep.setSingleStep(0.5)
        self._sweep.setDecimals(1)
        self._sweep.setSuffix(" s")
        self._sweep.setValue(float(link.balayage_s))
        self._sweep.setFixedWidth(90)
        l_v.addWidget(self._sweep)
        l_v.addStretch()
        root.addLayout(l_v)

        l_c = QHBoxLayout()
        l_c.addWidget(QLabel(tr("gp_target")))
        self._cible = QComboBox()
        self._cible.addItem(tr("gp_target_selection"), CIBLE_SELECTION)
        self._cible.addItem(tr("gp_target_all"), CIBLE_TOUTES)
        # Un groupe par entree : c'est le cas le plus courant en vrai — « les
        # deux lyres de contre au stick, et je ne veux surtout pas toucher aux
        # autres » — et ca evite d'avoir a re-selectionner dans le plan de feu
        # a chaque fois qu'on a cliqué ailleurs.
        for nom, n in link.groupes_de_lyres():
            self._cible.addItem(tr("gp_target_group", g=nom, n=n), CIBLE_GROUPE + nom)
        i = self._cible.findData(link.cible)
        if i < 0 and link.cible.startswith(CIBLE_GROUPE):
            # Groupe enregistre mais absent du show ouvert (autre patch) : on le
            # garde visible plutot que de retomber en silence sur « sélection ».
            self._cible.addItem(tr("gp_target_group_missing",
                                   g=link.cible[len(CIBLE_GROUPE):]), link.cible)
            i = self._cible.count() - 1
        self._cible.setCurrentIndex(max(0, i))
        l_c.addWidget(self._cible)
        l_c.addStretch()
        root.addLayout(l_c)

        l_i = QHBoxLayout()
        self._inv_pan = QCheckBox(tr("gp_invert_pan"))
        self._inv_pan.setChecked(link.invert_pan)
        self._inv_pan.setStyleSheet("color:#ddd;")
        self._inv_tilt = QCheckBox(tr("gp_invert_tilt"))
        self._inv_tilt.setChecked(link.invert_tilt)
        self._inv_tilt.setStyleSheet("color:#ddd;")
        l_i.addWidget(self._inv_pan); l_i.addWidget(self._inv_tilt); l_i.addStretch()
        root.addLayout(l_i)

        self._actif = QCheckBox(tr("gp_enable"))
        self._actif.setChecked(link.enabled)
        self._actif.setStyleSheet("color:#ddd;")
        root.addWidget(self._actif)
        root.addStretch()

        # ── Boutons du dialogue ─────────────────────────────────────────────
        bas = QHBoxLayout()
        bas.addStretch()
        annuler = QPushButton(tr("vlink_cancel"))
        annuler.clicked.connect(self.reject)
        bas.addWidget(annuler)
        ok = QPushButton(tr("vlink_save"))
        ok.setObjectName("primary")
        ok.clicked.connect(self._enregistrer)
        bas.addWidget(ok)
        racine.addLayout(bas)

        link.client.connection_changed.connect(self._maj_etat)
        link.client.avertissement.connect(self._maj_alerte)
        link.client.axes_changed.connect(self._maj_apercu)
        link.client.bouton_presse.connect(self._on_bouton_presse)
        link.client.bouton_relache.connect(self._on_bouton_relache)
        self._maj_etat(link.client.is_connected(),
                       link.client.name() or tr("gp_none"))

        # Rien ne doit se declencher tant que ce dialogue est ouvert : on y
        # designe les touches en appuyant dessus, et regler sa manette pendant
        # un show rappellerait sinon des memoires en direct.
        link.suspendu = True

        # Le client tourne pendant que le dialogue est ouvert, pour que
        # l'apercu vive meme si la liaison est desactivee. `_on_axes` ne bouge
        # aucune lyre tant que `enabled` est faux, donc c'est sans risque.
        self._client_demarre_ici = not link.client.is_connected()
        link.client.start()

    # ── onglet boutons ──────────────────────────────────────────────────────

    def _construire_onglet_boutons(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 10, 4, 4)
        lay.setSpacing(8)

        haut = QHBoxLayout()
        aide = QLabel(tr("gpb_hint"))
        aide.setStyleSheet("color:#888; font-size:11px;")
        aide.setWordWrap(True)
        haut.addWidget(aide, 1)

        # Deux boutons de page, en plus du modificateur physique : on doit
        # pouvoir preparer la 2e page sans tenir la gachette d'une main pendant
        # qu'on clique de l'autre.
        self._btn_pages = []
        for i in range(gb.NB_PAGES):
            b = QPushButton(tr("gpb_page1") if i == 0 else tr("gpb_page2"))
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setFixedHeight(26)
            b.clicked.connect(lambda _c=False, n=i: self._choisir_page(n))
            haut.addWidget(b)
            self._btn_pages.append(b)
        lay.addLayout(haut)

        self._manette = gb.ManetteWidget(self._window, page)
        self._manette.set_pages(self._link.pages)
        self._manette.set_style(gb.style_manette(self._link.client.name()))
        self._manette.demande_assignation.connect(self._assigner)
        self._manette.selection_changee.connect(self._maj_info_bouton)
        lay.addWidget(self._manette, 1)

        # Le dessin colore la touche pressee, mais la couleur seule ne dit pas
        # CE QU'ELLE FAIT : sur une manette tenue a deux mains, on ne lit pas
        # l'etiquette qui se trouve a l'autre bout de l'ecran. Cette ligne
        # repond en toutes lettres, et c'est elle qu'on regarde en appuyant.
        self._info = QLabel("")
        self._info.setWordWrap(True)
        self._info.setMinimumHeight(30)
        self._maj_info_bouton("")
        lay.addWidget(self._info)

        bas = QHBoxLayout()
        self._btn_actifs = QCheckBox(tr("gpb_enable"))
        self._btn_actifs.setChecked(self._link.boutons_enabled)
        self._btn_actifs.setStyleSheet("color:#ddd;")
        bas.addWidget(self._btn_actifs)
        bas.addStretch()
        effacer = QPushButton(tr("gpb_clear"))
        effacer.clicked.connect(self._effacer_page)
        bas.addWidget(effacer)
        lay.addLayout(bas)
        return page

    def _maj_info_bouton(self, bid: str):
        """Ecrit en clair l'action de la touche designee (souris ou appui)."""
        info = getattr(self, "_info", None)
        if info is None:
            return
        if not bid:
            info.setText(tr("gpb_press_hint"))
            info.setStyleSheet("color:#666; font-size:12px;")
            return
        nom = gb.libelle_bouton(bid, gb.style_manette(self._link.client.name()))
        page = tr("gpb_page1") if self._manette.page() == 0 else tr("gpb_page2")
        action = gb.label_action(self._window, self._manette.action_de(bid))
        if action:
            # Pastille pleine et pas un glyphe de transport (▶, ⏭…) : ces
            # derniers sortent en carre vide dans la police de l'interface.
            info.setText(f"●  {nom}  ({page})  →  {action}")
            info.setStyleSheet("color:#00ff88; font-size:12px; font-weight:bold;")
        else:
            info.setText(tr("gpb_press_empty", b=nom, p=page))
            info.setStyleSheet("color:#ffb84d; font-size:12px;")

    def _choisir_page(self, index: int):
        self._manette.set_page(index)
        for i, b in enumerate(self._btn_pages):
            b.setChecked(i == index)
        # La meme touche ne fait pas la meme chose selon la page : l'info doit
        # suivre le changement de page, sinon elle ment tant qu'on tient L2.
        self._maj_info_bouton(self._manette.selection() or "")

    def _effacer_page(self):
        self._manette.tout_effacer(self._manette.page())

    def _assigner(self, bid: str):
        menu = gb.construire_menu(self._window, self, self._manette.action_de(bid))
        choisi = menu.exec(QCursor.pos())
        if choisi is None:
            return  # menu ferme sans rien choisir : on ne touche a rien
        self._manette.assigner(bid, choisi.data())
        self._maj_info_bouton(bid)

    def _on_bouton_presse(self, bid: str):
        """Un appui physique DESIGNE la touche dans le dessin.

        C'est le geste naturel — « celle-la, la, sous mon pouce » — et il evite
        d'avoir a reconnaitre L1 de R1 sur une image. Il n'ouvre pas le menu :
        un menu qui s'ouvre tout seul volerait le clavier et la souris."""
        self._manette.set_presse(bid, True)
        if bid == gb.MODIFICATEUR:
            self._choisir_page(1)
        else:
            self._manette.set_selection(bid)

    def _on_bouton_relache(self, bid: str):
        self._manette.set_presse(bid, False)
        if bid == gb.MODIFICATEUR:
            self._choisir_page(0)

    def _petit_titre(self, texte):
        l = QLabel(texte)
        l.setStyleSheet("color:#aaa; font-size:11px; font-weight:bold;")
        return l

    def _barre(self):
        b = QProgressBar()
        b.setRange(-100, 100)
        b.setValue(0)
        b.setTextVisible(False)
        b.setFixedHeight(14)
        b.setStyleSheet(
            "QProgressBar{background:#151515;border:1px solid #2a2a2a;border-radius:3px;}"
            "QProgressBar::chunk{background:#00d4ff;}")
        return b

    # ── etat / apercu ───────────────────────────────────────────────────────

    def _maj_etat(self, connecte: bool, message: str):
        couleur = "#5f5" if connecte else "#888"
        puce = "●" if connecte else "○"
        self._etat.setText(f"{puce}  {message}")
        self._etat.setStyleSheet(f"color:{couleur}; font-size:11px;")
        if not connecte:
            self._maj_alerte("")
        # Le dessin suit la manette branchee : symboles PlayStation ou lettres
        # Xbox. `_maj_etat` peut partir avant que l'onglet existe (detection au
        # tout premier sondage), d'ou le getattr.
        manette = getattr(self, "_manette", None)
        if manette is not None:
            manette.set_style(gb.style_manette(self._link.client.name()))
            if not connecte:
                # Une manette debranchee ne relache aucune touche d'elle-meme
                # dans le dessin : sans ca, la derniere touche tenue resterait
                # allumee en vert, ce qui se lit comme un bouton bloque.
                manette.vider_presses()
                self._choisir_page(0)

    def _maj_alerte(self, message: str):
        self._alerte.setText(f"⚠  {message}" if message else "")
        self._alerte.setVisible(bool(message))

    def _maj_apercu(self, lx, ly, rx, ry):
        zm = self._zm.value() / 100.0
        self._barre_pan.setValue(int(round(commande_axe(lx, rx, zm) * 100)))
        self._barre_tilt.setValue(int(round(-commande_axe(ly, ry, zm) * 100)))

    def _detecter(self):
        try:
            manettes = lister_manettes()
        except Exception as exc:
            self._maj_etat(False, tr("gp_no_pygame", err=str(exc)))
            return
        if not manettes:
            self._maj_etat(False, tr("gp_none"))
            from gamepad_client import avertissement_aucune
            self._maj_alerte(avertissement_aucune())
            return
        self._maj_etat(True, ", ".join(nom for _, nom in manettes))
        # Le bouton « Détecter » doit dire la même chose que l'attache
        # automatique : une manette listée n'est pas une manette qui parle.
        from gamepad_client import avertissement_pour
        for i, _ in manettes:
            avert = avertissement_pour(i)
            if avert:
                self._maj_alerte(avert)
                break

    # ── validation ──────────────────────────────────────────────────────────

    def _enregistrer(self):
        self._link.zone_morte  = self._zm.value() / 100.0
        self._link.balayage_s  = self._sweep.value()
        self._link.invert_pan  = self._inv_pan.isChecked()
        self._link.invert_tilt = self._inv_tilt.isChecked()
        self._link.cible       = self._cible.currentData()
        self._link.enabled     = self._actif.isChecked()
        self._link.boutons_enabled = self._btn_actifs.isChecked()
        self._link.pages       = self._manette.pages()
        self._link.apply()
        try:
            self._window._save_akai_config_auto()
        except Exception:
            pass
        self.accept()

    def done(self, code):
        # Rendre la main AVANT tout le reste : si la suite echouait, une
        # liaison laissee suspendue serait une manette definitivement muette
        # jusqu'au prochain redemarrage.
        try:
            self._link.suspendu = False
        except Exception:
            pass
        # Si le dialogue avait demarre le client juste pour l'apercu et que
        # plus rien ne s'en sert, on le rearrete : sinon un timer 50 Hz
        # tournerait pour rien jusqu'a la fermeture de MyStrow.
        try:
            utile = self._link.enabled or (self._link.boutons_enabled
                                           and self._link.a_des_assignations())
            if self._client_demarre_ici and not utile:
                self._link.client.stop()
        except Exception:
            pass
        super().done(code)
