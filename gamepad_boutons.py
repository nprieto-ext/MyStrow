"""
gamepad_boutons.py — Les BOUTONS de la manette : dessin, assignation, action.

`gamepad_client` lit le peripherique et publie des fronts appui/relache ;
`gamepad_link` cable le tout. Ici on repond a trois questions : a quoi
ressemble une manette a l'ecran, quelle action porte chaque touche, et que
faire quand elle est pressee.

POURQUOI UN DESSIN, ET PAS UNE LISTE DEROULANTE
------------------------------------------------
Une liste « bouton A → MEM 3.2 » est illisible manette en main : personne ne
sait ou est « A » sur sa manette, et surtout personne ne relit une liste en
plein show. Le dessin repond a la seule question qui se pose reellement —
« qu'est-ce que je declenche si j'appuie LA ? ». C'est le principe des ecrans
d'assignation des jeux de sport, et il vaut ici pour la meme raison.

Le dessin est VECTORIEL, pas une photo : il doit se teinter selon l'etat
(assigne, presse, selectionne) et suivre le theme sombre de MyStrow. Une photo
serait figee, et il en faudrait une par modele de manette.

L'IDENTIFIANT D'UN BOUTON EST CELUI DE SDL, PAS SON DESSIN
----------------------------------------------------------
`a` est la croix sur PlayStation et A sur Xbox : meme bouton physique, meme
place sous le pouce. On enregistre donc l'identifiant SDL et on n'adapte que
l'affichage — un mapping fait avec une DualSense reste juste si on branche une
Xbox le lendemain. C'est aussi ce qui permet de ne dessiner qu'une geometrie.

LE MODIFICATEUR
---------------
L2 maintenue donne une 2e page d'assignations, comme la touche de tactique
d'un jeu de sport : 15 touches deviennent 30 raccourcis sans rien changer au
geste. L2 ne porte donc jamais d'action a elle seule — c'est marque sur le
dessin, sinon l'utilisateur essaierait de lui en donner une et croirait a un
bug quand rien ne se declenche.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QPolygonF, QTransform,
)
from PySide6.QtWidgets import QMenu, QWidget

from i18n import tr

# Bouton qui sert de modificateur (2e page). Fixe : le dessin l'annonce, et
# une gachette est le seul endroit ou le pouce ne sert a rien d'autre.
MODIFICATEUR = "l2"
NB_PAGES = 2

# Actions de la colonne PLAY, reprises telles quelles de `_PLAY_ROWS` dans
# main_window : la manette passe par `_activate_play_pad`, exactement comme les
# pads de l'AKAI. Un seul chemin, donc un seul comportement a corriger le jour
# ou le transport change — et pas de deuxieme writer sur le lecteur.
ACTIONS_TRANSPORT = ("playpause", "prev", "next", "stop")
NB_CARTOUCHES = 4
ACTIONS_PLAY = ACTIONS_TRANSPORT + tuple("cart%d" % i for i in range(NB_CARTOUCHES))

# Grille des pads FX (les « carres verts ») : 8 colonnes x 8 lignes.
FX_COLONNES, FX_LIGNES = 8, 8

# Espace de dessin. Tout est exprime dedans puis mis a l'echelle d'un coup :
# une seule multiplication a maintenir, et le dessin reste net a toute taille.
CANVAS_W, CANVAS_H = 1000.0, 600.0

# Colonnes d'etiquettes, de part et d'autre de la manette.
LARGEUR_ETIQ = 182.0
HAUTEUR_ETIQ = 54.0
X_ETIQ_G = 14.0
X_ETIQ_D = CANVAS_W - X_ETIQ_G - LARGEUR_ETIQ
LIGNES_Y = (56.0, 124.0, 192.0, 260.0, 328.0, 396.0, 464.0, 532.0)

# ── Geometrie des boutons ───────────────────────────────────────────────────
# (identifiant, cote, ligne, zone cliquable, point d'ancrage du trait de rappel)
# zone : ("rect", x, y, w, h) ou ("circle", cx, cy, r)
BOUTONS = (
    ("l2",     "g", 0, ("rect",   300,  66, 110, 34), (300,  83)),
    ("l1",     "g", 1, ("rect",   300, 106, 110, 32), (300, 122)),
    ("up",     "g", 2, ("rect",   356, 198,  32, 32), (356, 214)),
    ("left",   "g", 3, ("rect",   324, 230,  32, 32), (324, 246)),
    ("right",  "g", 4, ("rect",   388, 230,  32, 32), (388, 262)),
    ("down",   "g", 5, ("rect",   356, 262,  32, 32), (356, 278)),
    ("l3",     "g", 6, ("circle", 445, 332,  40),     (405, 332)),
    ("select", "g", 7, ("rect",   408, 158,  26, 20), (408, 168)),
    ("r2",     "d", 0, ("rect",   590,  66, 110, 34), (700,  83)),
    ("r1",     "d", 1, ("rect",   590, 106, 110, 32), (700, 122)),
    ("y",      "d", 2, ("circle", 628, 198,  25),     (653, 198)),
    ("b",      "d", 3, ("circle", 676, 246,  25),     (701, 246)),
    ("a",      "d", 4, ("circle", 628, 294,  25),     (653, 294)),
    ("x",      "d", 5, ("circle", 580, 246,  25),     (605, 262)),
    ("r3",     "d", 6, ("circle", 555, 332,  40),     (595, 332)),
    ("start",  "d", 7, ("rect",   566, 158,  26, 20), (592, 168)),
)

# Identifiants assignables : tous sauf le modificateur.
ASSIGNABLES = tuple(b[0] for b in BOUTONS if b[0] != MODIFICATEUR)

# Couleurs des symboles PlayStation — c'est a elles qu'on reconnait la manette
# au premier coup d'oeil, bien avant la forme des boutons.
_COULEURS_PS = {
    "y": "#4ad991",   # triangle
    "b": "#f2607a",   # rond
    "a": "#6aa9ff",   # croix
    "x": "#e56ee5",   # carre
}

# Theme (aligne sur le reste des dialogues MyStrow).
_C_FOND_CORPS   = "#1b1b22"
_C_BORD_CORPS   = "#33333f"
_C_CREUX        = "#101014"
_C_BOUTON       = "#15151c"
_C_BORD_BOUTON  = "#2c2c38"
_C_ASSIGNE      = "#00aaff"
_C_PRESSE       = "#00ff88"
_C_SELECTION    = "#ffb84d"
_C_TEXTE        = "#cccccc"
_C_TEXTE_VIDE   = "#555560"
_C_TRAIT        = "#2a2a34"


def style_manette(nom: str) -> str:
    """« ps » ou « xbox » — quels symboles dessiner.

    Deduit du nom SDL et de rien d'autre : une DualShock 4 passee par DS4Windows
    se presente en manette Xbox, et c'est bien les libelles Xbox qu'il faut
    alors afficher puisque c'est ce que le systeme fait croire a tout le monde.
    """
    n = (nom or "").lower()
    if "xbox" in n or "xinput" in n:
        return "xbox"
    return "ps"


def libelle_bouton(bid: str, style: str = "ps") -> str:
    """Nom affiche d'une touche, dans le vocabulaire de la manette branchee."""
    if bid in ("a", "b", "x", "y"):
        if style == "xbox":
            return bid.upper()
        return tr({"a": "gpb_cross", "b": "gpb_circle",
                   "x": "gpb_square", "y": "gpb_triangle"}[bid])
    if bid in ("up", "down", "left", "right"):
        return tr("gpb_dpad_" + bid)
    if bid in ("l1", "l2", "r1", "r2", "l3", "r3"):
        if style == "xbox":
            return {"l1": "LB", "l2": "LT", "r1": "RB", "r2": "RT",
                    "l3": "LS", "r3": "RS"}[bid]
        return bid.upper()
    if bid == "select":
        return "View" if style == "xbox" else "Share"
    if bid == "start":
        return "Menu" if style == "xbox" else "Options"
    return bid


# ---------------------------------------------------------------------------
# Modele d'action
# ---------------------------------------------------------------------------

def action_valide(action) -> bool:
    """Une action relue du fichier de config est-elle exploitable ?

    Le fichier est du JSON edite a la main de temps en temps, et une action
    bancale ne doit pas exploser au moment ou on appuie sur la touche, c'est-a-
    dire en plein show. On valide au chargement, une fois, et le declenchement
    n'a plus qu'a faire confiance.
    """
    if not isinstance(action, dict):
        return False
    t = action.get("type")
    if t == "memory":
        try:
            c, r = int(action["col"]), int(action["row"])
        except (KeyError, TypeError, ValueError):
            return False
        return 0 <= c <= 7 and 0 <= r <= 7
    if t == "effect":
        try:
            i = int(action["idx"])
        except (KeyError, TypeError, ValueError):
            return False
        return 0 <= i <= 7
    if t == "fx_pad":
        try:
            c, r = int(action["col"]), int(action["row"])
        except (KeyError, TypeError, ValueError):
            return False
        return 0 <= c < FX_COLONNES and 0 <= r < FX_LIGNES
    if t == "fx_name":
        return bool(action.get("name")) and isinstance(action.get("name"), str)
    if t == "play":
        return action.get("action") in ACTIONS_PLAY
    return False


def effets_bibliotheque() -> list:
    """Noms de TOUS les effets disponibles, sans doublon.

    Meme source et meme ordre de resolution que vMix, OBS et le Stream Deck :
    les integres d'abord, les personnels ensuite. L'ordre compte — c'est le
    PREMIER nom trouve qui sera joue. On de-doublonne donc ici aussi, sinon le
    menu proposerait deux entrees identiques dont une injouable.
    """
    try:
        from effect_editor import BUILTIN_EFFECTS, _load_custom_effects
        tous = list(BUILTIN_EFFECTS) + _load_custom_effects()
    except Exception:
        return []
    noms, vus = [], set()
    for e in tous:
        nom = e.get("name") if isinstance(e, dict) else None
        if nom and nom not in vus:
            vus.add(nom)
            noms.append(str(nom))
    return noms


def label_action(window, action) -> str:
    """Texte affiche sous la touche. Suit le show : renommer une memoire ou
    changer l'effet d'un bouton FX se voit ici sans rien reassigner."""
    if not action_valide(action):
        return ""
    t = action.get("type")
    if t == "memory":
        c, r = int(action["col"]), int(action["row"])
        texte = "MEM %d.%d" % (c + 1, r + 1)
        try:
            mem = window.memories[c][r]
        except Exception:
            mem = None
        if isinstance(mem, dict) and mem.get("name"):
            texte += "  ·  " + str(mem["name"])
        return texte
    if t == "effect":
        i = int(action["idx"])
        texte = "FX %d" % (i + 1)
        try:
            nom = window.effect_buttons[i].current_effect
        except Exception:
            nom = ""
        if nom:
            texte += "  ·  " + str(nom)
        return texte
    if t == "fx_pad":
        c, r = int(action["col"]), int(action["row"])
        nom = _nom_fx_pad(window, c, r)
        texte = "FX %d.%d" % (c + 1, r + 1)
        return texte + "  ·  " + nom if nom else texte
    if t == "fx_name":
        return tr("gpb_fx_lib", n=action["name"])
    if t == "play":
        return libelle_play(window, action["action"])
    return ""


def _nom_fx_pad(window, col: int, row: int) -> str:
    """Nom de l'effet pose sur un pad FX, ou "" si le pad est vide."""
    try:
        cfg = window.fx_pads[col][row]
    except Exception:
        return ""
    return str(cfg.get("name", "")) if isinstance(cfg, dict) else ""


def _titre_cartouche(window, idx: int) -> str:
    try:
        return str(window.cartouches[idx].media_title or "")
    except Exception:
        return ""


def libelle_play(window, action: str) -> str:
    """Libelle d'une action de transport ou de cartouche, titre charge inclus."""
    if action in ACTIONS_TRANSPORT:
        return tr("gpb_play_" + action)
    if action.startswith("cart"):
        try:
            i = int(action[4:])
        except ValueError:
            return ""
        titre = _titre_cartouche(window, i)
        base = tr("gpb_play_cart", n=i + 1)
        return base + "  ·  " + titre if titre else base
    return ""


def appliquer_action(window, action) -> bool:
    """Declenche l'action.

    Passe par les MEMES points d'entree que les pads de l'AKAI et que le Stream
    Deck (`trigger_memory`, `toggle_effect`). La manette ne doit surtout pas
    devenir un deuxieme chemin qui ecrit l'etat des projecteurs a sa facon :
    c'est l'anti-pattern des deux writers, et il se paie toujours par un etat
    qui diverge entre la surface et la sortie DMX.
    """
    if not action_valide(action):
        return False
    t = action.get("type")
    if t == "memory":
        window.trigger_memory(int(action["col"]), int(action["row"]))
        return True
    if t == "effect":
        window.toggle_effect(int(action["idx"]))
        return True
    if t == "fx_pad":
        window._toggle_fx_pad(int(action["col"]), int(action["row"]))
        return True
    if t == "fx_name":
        window.toggle_effect_by_name(str(action["name"]))
        return True
    if t == "play":
        window._activate_play_pad(action["action"])
        return True
    return False


def lire_pages(brut) -> list:
    """JSON → [{bouton: action}, ...], une entree par page. Tolerant : ce qui
    n'est pas compris est ignore, jamais une exception."""
    pages = [{} for _ in range(NB_PAGES)]
    if not isinstance(brut, dict):
        return pages
    for i in range(NB_PAGES):
        p = brut.get("page%d" % (i + 1))
        if not isinstance(p, dict):
            continue
        for bid, action in p.items():
            if bid in ASSIGNABLES and action_valide(action):
                pages[i][bid] = dict(action)
    return pages


def ecrire_pages(pages) -> dict:
    out = {}
    for i in range(NB_PAGES):
        page = pages[i] if i < len(pages) and isinstance(pages[i], dict) else {}
        out["page%d" % (i + 1)] = {bid: dict(a) for bid, a in page.items()}
    return out


def construire_menu(window, parent, courante) -> QMenu:
    """Menu d'assignation d'une touche.

    Les memoires ENREGISTREES seulement : proposer les 64 cases dont 60 vides
    obligerait a chercher, et assigner une case vide donnerait une touche qui
    ne fait rien sans dire pourquoi.
    """
    menu = QMenu(parent)

    act = menu.addAction(tr("gpb_menu_none"))
    act.setData(None)
    act.setCheckable(True)
    act.setChecked(not action_valide(courante))

    menu.addSeparator()

    sous_mem = menu.addMenu(tr("gpb_menu_memory"))
    n_mem = 0
    for c in range(8):
        colonne = None
        for r in range(8):
            try:
                mem = window.memories[c][r]
            except Exception:
                mem = None
            if mem is None:
                continue
            if colonne is None:
                colonne = sous_mem.addMenu(tr("gpb_menu_memcol", n=c + 1))
            etiq = "MEM %d.%d" % (c + 1, r + 1)
            if isinstance(mem, dict) and mem.get("name"):
                etiq += "  ·  " + str(mem["name"])
            a = colonne.addAction(etiq)
            a.setData({"type": "memory", "col": c, "row": r})
            a.setCheckable(True)
            a.setChecked(isinstance(courante, dict)
                         and courante.get("type") == "memory"
                         and courante.get("col") == c
                         and courante.get("row") == r)
            n_mem += 1
    if not n_mem:
        sous_mem.setEnabled(False)
        sous_mem.setTitle(tr("gpb_menu_memory_empty"))

    sous_fx = menu.addMenu(tr("gpb_menu_effect"))
    for i in range(8):
        try:
            nom = window.effect_buttons[i].current_effect
        except Exception:
            nom = ""
        etiq = ("FX %d  ·  %s" % (i + 1, nom)) if nom else tr("gpb_menu_fx_empty", n=i + 1)
        a = sous_fx.addAction(etiq)
        a.setData({"type": "effect", "idx": i})
        a.setCheckable(True)
        a.setChecked(isinstance(courante, dict)
                     and courante.get("type") == "effect"
                     and courante.get("idx") == i)

    # Les pads FX (« carres verts ») : 64 emplacements de plus que les 8
    # boutons, et c'est la que vit reellement la bibliotheque d'effets d'un
    # show. Meme regle que les memoires : on ne propose que ceux qui portent
    # un effet, sinon la liste serait 90 % de vide.
    sous_pad = menu.addMenu(tr("gpb_menu_fxpad"))
    n_pad = 0
    for c in range(FX_COLONNES):
        colonne = None
        for r in range(FX_LIGNES):
            nom = _nom_fx_pad(window, c, r)
            if not nom:
                continue
            if colonne is None:
                colonne = sous_pad.addMenu(tr("gpb_menu_memcol", n=c + 1))
            a = colonne.addAction("FX %d.%d  ·  %s" % (c + 1, r + 1, nom))
            a.setData({"type": "fx_pad", "col": c, "row": r})
            a.setCheckable(True)
            a.setChecked(isinstance(courante, dict)
                         and courante.get("type") == "fx_pad"
                         and courante.get("col") == c
                         and courante.get("row") == r)
            n_pad += 1
    if not n_pad:
        sous_pad.setEnabled(False)
        sous_pad.setTitle(tr("gpb_menu_fxpad_empty"))

    # Toute la bibliotheque, comme vMix et OBS la proposent. Decoupee par
    # initiale : plus de cent effets a plat, ca ne se parcourt pas — alors
    # qu'on sait toujours par quelle lettre commence celui qu'on cherche.
    sous_lib = menu.addMenu(tr("gpb_menu_library"))
    lettres = {}
    for nom in effets_bibliotheque():
        lettres.setdefault(nom[0].upper(), []).append(nom)
    for lettre in sorted(lettres):
        groupe = sous_lib.addMenu(lettre)
        for nom in lettres[lettre]:
            a = groupe.addAction(nom)
            a.setData({"type": "fx_name", "name": nom})
            a.setCheckable(True)
            a.setChecked(isinstance(courante, dict)
                         and courante.get("type") == "fx_name"
                         and courante.get("name") == nom)
    if not lettres:
        sous_lib.setEnabled(False)

    menu.addSeparator()

    # Transport du sequenceur et cartouches : les memes actions que la colonne
    # PLAY de l'AKAI. Lancer le media suivant depuis la manette est justement
    # ce qu'on veut quand on est au milieu de la salle, loin du clavier.
    sous_play = menu.addMenu(tr("gpb_menu_transport"))
    for act in ACTIONS_TRANSPORT:
        a = sous_play.addAction(libelle_play(window, act))
        a.setData({"type": "play", "action": act})
        a.setCheckable(True)
        a.setChecked(isinstance(courante, dict)
                     and courante.get("type") == "play"
                     and courante.get("action") == act)

    sous_cart = menu.addMenu(tr("gpb_menu_slots"))
    for i in range(NB_CARTOUCHES):
        act = "cart%d" % i
        etiq = libelle_play(window, act)
        a = sous_cart.addAction(etiq)
        # Un slot vide reste proposable : on prepare souvent le mapping avant
        # d'y charger le son, et la touche marchera des que le son sera la.
        a.setData({"type": "play", "action": act})
        a.setCheckable(True)
        a.setChecked(isinstance(courante, dict)
                     and courante.get("type") == "play"
                     and courante.get("action") == act)
    return menu


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class ManetteWidget(QWidget):
    """Dessin de la manette, cliquable, avec retour en direct des appuis."""

    # Une touche a ete choisie a la souris (il faut ouvrir le menu)
    demande_assignation = Signal(str)
    # Une touche a ete designee (souris ou appui physique)
    selection_changee   = Signal(str)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._pages = [{} for _ in range(NB_PAGES)]
        self._page = 0
        self._style = "ps"
        self._enfonces = set()
        self._selection = None
        # Taille plancher : en dessous, le nom de la memoire sous chaque
        # touche devient illisible. Le dessin s'agrandit ensuite tout seul.
        self.setMinimumSize(780, 468)

    # ── etat ────────────────────────────────────────────────────────────────

    def set_pages(self, pages):
        self._pages = [dict(p or {}) for p in list(pages)[:NB_PAGES]]
        while len(self._pages) < NB_PAGES:
            self._pages.append({})
        self.update()

    def pages(self) -> list:
        return [dict(p) for p in self._pages]

    def page(self) -> int:
        return self._page

    def set_page(self, index: int):
        index = max(0, min(NB_PAGES - 1, int(index)))
        if index != self._page:
            self._page = index
            self.update()

    def set_style(self, style: str):
        if style != self._style:
            self._style = style
            self.update()

    def set_presse(self, bid: str, presse: bool):
        avant = set(self._enfonces)
        if presse:
            self._enfonces.add(bid)
        else:
            self._enfonces.discard(bid)
        if avant != self._enfonces:
            self.update()

    def vider_presses(self):
        if self._enfonces:
            self._enfonces.clear()
            self.update()

    def selection(self):
        return self._selection

    def set_selection(self, bid):
        if bid != self._selection:
            self._selection = bid
            self.update()
            self.selection_changee.emit(bid or "")

    def action_de(self, bid, page=None):
        p = self._page if page is None else page
        return self._pages[p].get(bid)

    def assigner(self, bid, action, page=None):
        p = self._page if page is None else page
        if action is None:
            self._pages[p].pop(bid, None)
        else:
            self._pages[p][bid] = dict(action)
        self.update()

    def tout_effacer(self, page=None):
        if page is None:
            self._pages = [{} for _ in range(NB_PAGES)]
        else:
            self._pages[page] = {}
        self.update()

    # ── souris ──────────────────────────────────────────────────────────────

    def _echelle(self):
        s = min(self.width() / CANVAS_W, self.height() / CANVAS_H)
        return (s,
                (self.width() - CANVAS_W * s) / 2,
                (self.height() - CANVAS_H * s) / 2)

    def mousePressEvent(self, ev):
        s, dx, dy = self._echelle()
        if s <= 0:
            return
        x = (ev.position().x() - dx) / s
        y = (ev.position().y() - dy) / s
        bid = touche_sous(x, y)
        if bid is None:
            return
        self.set_selection(bid)
        if bid != MODIFICATEUR:
            self.demande_assignation.emit(bid)

    # ── dessin ──────────────────────────────────────────────────────────────

    def paintEvent(self, _ev):
        s, dx, dy = self._echelle()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.translate(dx, dy)
        p.scale(s, s)

        self._dessiner_traits(p)
        self._dessiner_corps(p)
        self._dessiner_boutons(p)
        self._dessiner_etiquettes(p)
        p.end()

    def _etat(self, bid):
        """(couleur d'accent, epaisseur) selon l'etat de la touche."""
        if bid in self._enfonces:
            return QColor(_C_PRESSE), 3.0
        if bid == self._selection:
            return QColor(_C_SELECTION), 2.4
        if bid == MODIFICATEUR:
            return QColor(_C_SELECTION).darker(150), 1.6
        if self._pages[self._page].get(bid):
            return QColor(_C_ASSIGNE), 1.8
        return QColor(_C_BORD_BOUTON), 1.4

    def _dessiner_traits(self, p):
        p.setPen(QPen(QColor(_C_TRAIT), 1.0))
        for bid, cote, ligne, _zone, ancre in BOUTONS:
            r = rect_etiquette(cote, ligne)
            depart = (QPointF(r.right(), r.center().y()) if cote == "g"
                      else QPointF(r.left(), r.center().y()))
            gouttiere = 240.0 if cote == "g" else CANVAS_W - 240.0
            p.drawLine(depart, QPointF(gouttiere, depart.y()))
            p.drawLine(QPointF(gouttiere, depart.y()),
                       QPointF(float(ancre[0]), float(ancre[1])))

    def _dessiner_corps(self, p):
        corps = QPainterPath()
        corps.addRoundedRect(QRectF(290, 140, 420, 215), 55, 55)
        for cx, angle in ((352, -16), (648, 16)):
            poignee = QPainterPath()
            poignee.addRoundedRect(QRectF(-56, -20, 112, 190), 55, 55)
            t = QTransform()
            t.translate(cx, 300)
            t.rotate(angle)
            corps = corps.united(t.map(poignee))

        degrade = QLinearGradient(0, 120, 0, 480)
        degrade.setColorAt(0.0, QColor("#25252e"))
        degrade.setColorAt(1.0, QColor(_C_FOND_CORPS))
        p.setBrush(QBrush(degrade))
        p.setPen(QPen(QColor(_C_BORD_CORPS), 2.0))
        p.drawPath(corps)

        # Pave tactile — aucune action possible dessus (SDL n'expose pas son
        # clic comme un bouton de manette), il est la pour la ressemblance.
        p.setBrush(QColor(_C_CREUX))
        p.setPen(QPen(QColor(_C_BORD_BOUTON), 1.2))
        p.drawRoundedRect(QRectF(440, 150, 120, 62), 8, 8)

    def _dessiner_boutons(self, p):
        page = self._pages[self._page]

        # Croix directionnelle : une seule forme continue, mais quatre zones
        # qui s'allument separement.
        croix = QPainterPath()
        croix.addRoundedRect(QRectF(324, 230, 96, 32), 6, 6)
        croix.addRoundedRect(QRectF(356, 198, 32, 96), 6, 6)
        p.setBrush(QColor(_C_BOUTON))
        p.setPen(QPen(QColor(_C_BORD_BOUTON), 1.4))
        p.drawPath(croix.simplified())

        for bid, _cote, _ligne, zone, _ancre in BOUTONS:
            couleur, epaisseur = self._etat(bid)
            assigne = bool(page.get(bid))
            remplissage = QColor(couleur)
            remplissage.setAlpha(70 if bid in self._enfonces else (28 if assigne else 0))
            plein = remplissage.alpha() > 0

            if zone[0] == "rect":
                _, x, y, w, h = zone
                r = QRectF(x, y, w, h)
                if bid in ("up", "down", "left", "right"):
                    # La croix est deja dessinee d'un bloc : on ne repeint que
                    # l'interieur du bras concerne, sinon on redessinerait des
                    # bords a l'interieur de la forme.
                    interieur = r.adjusted(2, 2, -2, -2)
                    p.setPen(Qt.NoPen)
                    p.setBrush(remplissage if plein else Qt.NoBrush)
                    if plein:
                        p.drawRoundedRect(interieur, 4, 4)
                    if epaisseur > 1.4:
                        p.setBrush(Qt.NoBrush)
                        p.setPen(QPen(couleur, epaisseur))
                        p.drawRoundedRect(interieur, 4, 4)
                    continue
                p.setBrush(remplissage if plein else QColor(_C_BOUTON))
                p.setPen(QPen(couleur, epaisseur))
                p.drawRoundedRect(r, 8, 8)
                if bid in ("l1", "l2", "r1", "r2"):
                    self._texte(p, r, libelle_bouton(bid, self._style), 13,
                                QColor(_C_TEXTE), gras=True)
            else:
                _, cx, cy, rr = zone
                centre = QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr)
                if bid in ("l3", "r3"):
                    # Stick : un creux puis le champignon, sinon il se lit
                    # comme un gros bouton rond de plus.
                    p.setBrush(QColor(_C_CREUX))
                    p.setPen(QPen(QColor(_C_BORD_BOUTON), 1.2))
                    p.drawEllipse(centre)
                    p.setBrush(remplissage if plein else QColor("#20202a"))
                    p.setPen(QPen(couleur, epaisseur))
                    p.drawEllipse(centre.adjusted(9, 9, -9, -9))
                else:
                    p.setBrush(remplissage if plein else QColor(_C_BOUTON))
                    p.setPen(QPen(couleur, epaisseur))
                    p.drawEllipse(centre)
                    self._symbole(p, bid, cx, cy)

    def _symbole(self, p, bid, cx, cy):
        """Les symboles PlayStation sont DESSINES, pas ecrits.

        Un caractere comme la croix ou le triangle depend de la police
        installee : sur un poste ou elle manque, l'utilisateur verrait un carre
        vide au milieu du bouton — impossible a diagnostiquer a distance. Un
        trace geometrique, lui, ne depend de rien.
        """
        if self._style == "xbox":
            self._texte(p, QRectF(cx - 25, cy - 25, 50, 50), bid.upper(), 17,
                        QColor(_C_TEXTE), gras=True)
            return
        couleur = QColor(_COULEURS_PS.get(bid, _C_TEXTE))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(couleur, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        d = 9.0
        if bid == "a":       # croix
            p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
            p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
        elif bid == "b":     # rond
            p.drawEllipse(QRectF(cx - d, cy - d, 2 * d, 2 * d))
        elif bid == "x":     # carre
            p.drawRect(QRectF(cx - d, cy - d, 2 * d, 2 * d))
        elif bid == "y":     # triangle
            p.drawPolygon(QPolygonF([QPointF(cx, cy - d - 1),
                                     QPointF(cx + d + 1, cy + d),
                                     QPointF(cx - d - 1, cy + d)]))

    def _dessiner_etiquettes(self, p):
        page = self._pages[self._page]
        for bid, cote, ligne, _zone, _ancre in BOUTONS:
            r = rect_etiquette(cote, ligne)
            couleur, epaisseur = self._etat(bid)
            p.setBrush(QColor("#0e0e12"))
            p.setPen(QPen(couleur, epaisseur))
            p.drawRoundedRect(r, 8, 8)

            haut = QRectF(r.left() + 10, r.top() + 5, r.width() - 20, 18)
            self._texte(p, haut, libelle_bouton(bid, self._style), 11, couleur,
                        gras=True, gauche=True)

            if bid == MODIFICATEUR:
                texte, teinte = tr("gpb_modifier"), QColor(_C_SELECTION)
            else:
                texte = label_action(self._window, page.get(bid))
                teinte = QColor(_C_TEXTE) if texte else QColor(_C_TEXTE_VIDE)
                if not texte:
                    texte = tr("gpb_unassigned")
            bas = QRectF(r.left() + 10, r.top() + 25, r.width() - 20, 22)
            self._texte(p, bas, texte, 12, teinte, gauche=True, elider=True)

    def _texte(self, p, rect, texte, taille, couleur, gras=False, gauche=False,
               elider=False):
        f = QFont("Segoe UI")
        f.setPixelSize(int(taille))
        f.setBold(gras)
        p.setFont(f)
        p.setPen(QPen(couleur))
        if elider:
            texte = p.fontMetrics().elidedText(texte, Qt.ElideRight,
                                               int(rect.width()))
        p.drawText(rect, (Qt.AlignLeft if gauche else Qt.AlignHCenter)
                   | Qt.AlignVCenter, texte)


# ---------------------------------------------------------------------------
# Geometrie (hors classe : testable sans widget ni QApplication)
# ---------------------------------------------------------------------------

def rect_etiquette(cote: str, ligne: int) -> QRectF:
    x = X_ETIQ_G if cote == "g" else X_ETIQ_D
    y = LIGNES_Y[ligne] - HAUTEUR_ETIQ / 2
    return QRectF(x, y, LARGEUR_ETIQ, HAUTEUR_ETIQ)


def zone_contient(zone, x, y) -> bool:
    if zone[0] == "rect":
        _, zx, zy, zw, zh = zone
        return zx <= x <= zx + zw and zy <= y <= zy + zh
    _, cx, cy, r = zone
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def touche_sous(x, y):
    """Touche sous un point de l'espace de dessin, ou None.

    Les etiquettes sont testees EN PREMIER : ce sont les plus grandes cibles et
    c'est ce qu'on vise naturellement pour changer une assignation. Elles ne
    peuvent pas chevaucher un bouton (deux colonnes reservees sur les bords),
    donc l'ordre ne cache jamais rien.
    """
    for bid, cote, ligne, _zone, _ancre in BOUTONS:
        if rect_etiquette(cote, ligne).contains(x, y):
            return bid
    for bid, _cote, _ligne, zone, _ancre in BOUTONS:
        if zone_contient(zone, x, y):
            return bid
    return None
