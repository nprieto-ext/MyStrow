"""
test_gamepad_boutons.py — Verifications sans manette ni AKAI branches.

    python test_gamepad_boutons.py

Couvre ce qui casse en silence : la geometrie cliquable (une touche
inatteignable ne se voit qu'a l'usage), les fronts appui/relache, et la
relecture d'une config abimee. Rend aussi le dessin en PNG pour l'oeil.
"""

import os
import sys

# `offscreen` n'a aucune police installee : les etiquettes sortiraient en
# carres vides et l'apercu ne dirait rien de leur lisibilite. On ne bascule
# donc dessus que si aucun affichage n'est disponible.
if not os.environ.get("DISPLAY") and sys.platform not in ("win32", "darwin"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ECHECS = []


def verifie(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  ECHEC {message}")
        ECHECS.append(message)


# ---------------------------------------------------------------------------
# Doublures
# ---------------------------------------------------------------------------

class FauxBoutonFX:
    def __init__(self, nom=""):
        self.current_effect = nom


class FauxCartouche:
    def __init__(self, titre=""):
        self.media_title = titre


class FauxProjecteur:
    def __init__(self, groupe, type_="Moving Head"):
        self.group = groupe
        self.fixture_type = type_
        self.pan = self.tilt = 32767
        self.pan_min = self.tilt_min = 0
        self.pan_max = self.tilt_max = 65535


class FausseFenetre:
    """Le strict necessaire pour les etiquettes et le declenchement."""

    def __init__(self):
        self.memories = [[None] * 8 for _ in range(8)]
        self.memories[0][0] = {"name": "Intro"}
        self.memories[2][5] = {}                      # enregistree, sans nom
        self.effect_buttons = [FauxBoutonFX("Chenillard" if i == 3 else "")
                               for i in range(8)]
        self.fx_pads = [[None] * 8 for _ in range(8)]
        self.fx_pads[1][4] = {"name": "Strobe lent"}
        self.cartouches = [FauxCartouche("Applaudissements" if i == 0 else "")
                           for i in range(4)]
        # Deux groupes de lyres + un groupe de PAR, qui ne doit JAMAIS etre
        # propose comme cible pan/tilt.
        self.projectors = [FauxProjecteur("contre"), FauxProjecteur("contre"),
                           FauxProjecteur("douche1"),
                           FauxProjecteur("face", "PAR LED")]
        self.appels = []

    def trigger_memory(self, col, row):
        self.appels.append(("memory", col, row))

    def toggle_effect(self, idx):
        self.appels.append(("effect", idx))

    def _toggle_fx_pad(self, col, row):
        self.appels.append(("fx_pad", col, row))

    def _activate_play_pad(self, action):
        self.appels.append(("play", action))

    def toggle_effect_by_name(self, nom):
        self.appels.append(("fx_name", nom))


class FauxControleur:
    """Manette simulee : on lui dicte les boutons tenus et les gachettes."""

    def __init__(self):
        self.boutons = set()
        self.gachettes = {}

    def get_button(self, code):
        return code in self.boutons

    def get_axis(self, code):
        return self.gachettes.get(code, 0)


class FauxPygame:
    """Porte les constantes SDL, comme le vrai module."""


def faux_pygame():
    import gamepad_client as gc
    p = FauxPygame()
    for i, (_bid, const) in enumerate(gc._BOUTONS):
        setattr(p, const, 100 + i)
    for i, (_bid, const) in enumerate(gc._GACHETTES):
        setattr(p, const, 200 + i)
    return p


# ---------------------------------------------------------------------------
# 1. Geometrie
# ---------------------------------------------------------------------------

def test_geometrie():
    print("\n[1] Geometrie du dessin")
    import gamepad_boutons as gb

    verifie(len(gb.BOUTONS) == 16, "16 touches decrites")
    verifie(len(gb.ASSIGNABLES) == 15,
            "15 touches assignables (le modificateur est exclu)")
    verifie(gb.MODIFICATEUR not in gb.ASSIGNABLES,
            "le modificateur n'est pas assignable")

    ids = [b[0] for b in gb.BOUTONS]
    verifie(len(set(ids)) == len(ids), "aucun identifiant en double")

    # Chaque zone doit se retrouver depuis son propre centre : une touche que le
    # clic ne retrouve pas est invisible a l'usage, alors qu'elle est dessinee.
    for bid, _cote, _ligne, zone, _ancre in gb.BOUTONS:
        if zone[0] == "rect":
            _, x, y, w, h = zone
            cx, cy = x + w / 2, y + h / 2
        else:
            _, cx, cy, _r = zone
        verifie(gb.touche_sous(cx, cy) == bid, f"clic au centre de {bid}")

    # Idem pour les etiquettes, qui sont la vraie cible de la souris.
    for bid, cote, ligne, _zone, _ancre in gb.BOUTONS:
        r = gb.rect_etiquette(cote, ligne)
        verifie(gb.touche_sous(r.center().x(), r.center().y()) == bid,
                f"clic sur l'etiquette de {bid}")

    # Les etiquettes ne doivent recouvrir aucune zone de bouton, sinon l'ordre
    # de test masquerait des touches.
    conflits = []
    for bid, cote, ligne, _z, _a in gb.BOUTONS:
        r = gb.rect_etiquette(cote, ligne)
        for autre, _c2, _l2, zone, _a2 in gb.BOUTONS:
            if zone[0] == "rect":
                _, x, y, w, h = zone
                coins = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
            else:
                _, cx, cy, rr = zone
                coins = [(cx - rr, cy), (cx + rr, cy), (cx, cy - rr), (cx, cy + rr)]
            if any(r.contains(px, py) for px, py in coins):
                conflits.append((bid, autre))
    verifie(not conflits, f"aucun chevauchement etiquette/bouton {conflits or ''}")

    # Deux zones de boutons ne doivent pas se chevaucher non plus.
    doublons = []
    for i, (bid, _c, _l, z1, _a) in enumerate(gb.BOUTONS):
        for autre, _c2, _l2, z2, _a2 in gb.BOUTONS[i + 1:]:
            if z1[0] == "rect":
                _, x, y, w, h = z1
                pts = [(x + 1, y + 1), (x + w - 1, y + h - 1),
                       (x + w / 2, y + h / 2)]
            else:
                _, cx, cy, r = z1
                pts = [(cx, cy), (cx + r - 1, cy), (cx, cy + r - 1)]
            if any(gb.zone_contient(z2, px, py) for px, py in pts):
                doublons.append((bid, autre))
    verifie(not doublons, f"aucun chevauchement entre boutons {doublons or ''}")

    # Tout doit tenir dans l'espace de dessin, sinon c'est rogne a l'ecran.
    dehors = []
    for bid, cote, ligne, zone, _a in gb.BOUTONS:
        r = gb.rect_etiquette(cote, ligne)
        if r.left() < 0 or r.right() > gb.CANVAS_W or r.bottom() > gb.CANVAS_H:
            dehors.append(bid)
        if zone[0] == "rect":
            _, x, y, w, h = zone
            if x < 0 or x + w > gb.CANVAS_W or y < 0 or y + h > gb.CANVAS_H:
                dehors.append(bid)
    verifie(not dehors, f"tout tient dans le cadre {dehors or ''}")


# ---------------------------------------------------------------------------
# 2. Actions
# ---------------------------------------------------------------------------

def test_actions():
    print("\n[2] Actions et etiquettes")
    import gamepad_boutons as gb
    w = FausseFenetre()

    verifie(gb.action_valide({"type": "memory", "col": 0, "row": 0}),
            "memoire valide acceptee")
    verifie(not gb.action_valide({"type": "memory", "col": 9, "row": 0}),
            "colonne hors plage refusee")
    verifie(not gb.action_valide({"type": "memory", "row": 0}),
            "champ manquant refuse")
    verifie(not gb.action_valide({"type": "inconnu"}), "type inconnu refuse")
    verifie(not gb.action_valide(None), "None refuse")
    verifie(not gb.action_valide("MEM 1.1"), "chaine refusee")
    verifie(gb.action_valide({"type": "effect", "idx": 7}), "FX 8 accepte")
    verifie(not gb.action_valide({"type": "effect", "idx": 8}), "FX 9 refuse")

    verifie(gb.label_action(w, {"type": "memory", "col": 0, "row": 0})
            .startswith("MEM 1.1"), "etiquette memoire numerotee a partir de 1")
    verifie("Intro" in gb.label_action(w, {"type": "memory", "col": 0, "row": 0}),
            "le nom de la memoire apparait")
    verifie(gb.label_action(w, {"type": "memory", "col": 2, "row": 5}) == "MEM 3.6",
            "memoire sans nom : juste son numero")
    verifie("Chenillard" in gb.label_action(w, {"type": "effect", "idx": 3}),
            "le nom de l'effet apparait")
    verifie(gb.label_action(w, {"type": "effect", "idx": 0}) == "FX 1",
            "bouton FX vide : juste son numero")
    verifie(gb.label_action(w, None) == "", "aucune action : etiquette vide")

    # Une memoire supprimee apres l'assignation ne doit pas casser l'affichage.
    verifie(gb.label_action(w, {"type": "memory", "col": 7, "row": 7}) == "MEM 8.8",
            "memoire effacee depuis : etiquette encore lisible")

    # ── Pads FX, transport et slots ─────────────────────────────────────────
    verifie(gb.action_valide({"type": "fx_pad", "col": 7, "row": 7}),
            "pad FX 8.8 accepte")
    verifie(not gb.action_valide({"type": "fx_pad", "col": 8, "row": 0}),
            "pad FX hors grille refuse")
    verifie(gb.action_valide({"type": "play", "action": "next"}),
            "transport valide accepte")
    verifie(gb.action_valide({"type": "play", "action": "cart3"}),
            "slot 4 accepte")
    verifie(not gb.action_valide({"type": "play", "action": "cart9"}),
            "slot inexistant refuse")
    verifie(not gb.action_valide({"type": "play"}), "transport sans action refuse")

    verifie("Strobe lent" in gb.label_action(w, {"type": "fx_pad", "col": 1, "row": 4}),
            "le nom de l'effet du pad FX apparait")
    verifie(gb.label_action(w, {"type": "fx_pad", "col": 0, "row": 0}) == "FX 1.1",
            "pad FX vide : juste son numero")
    verifie("Applaudissements" in gb.label_action(w, {"type": "play", "action": "cart0"}),
            "le titre charge dans le slot apparait")
    verifie(gb.label_action(w, {"type": "play", "action": "cart1"}) == "SLOT 2",
            "slot vide : juste son numero")
    verifie(gb.label_action(w, {"type": "play", "action": "next"}) != "",
            "le transport a une etiquette")

    verifie(gb.action_valide({"type": "fx_name", "name": "Rainbow"}),
            "effet de bibliotheque accepte")
    verifie(not gb.action_valide({"type": "fx_name", "name": ""}),
            "nom d'effet vide refuse")
    verifie(not gb.action_valide({"type": "fx_name", "name": 3}),
            "nom d'effet non textuel refuse")
    verifie("Rainbow" in gb.label_action(w, {"type": "fx_name", "name": "Rainbow"}),
            "le nom de l'effet de bibliotheque apparait")

    # La bibliotheque est la meme que celle de vMix/OBS, et sans doublon : un
    # nom en double rendrait la 2e entree du menu injouable (c'est toujours le
    # premier trouve qui part).
    noms = gb.effets_bibliotheque()
    verifie(len(noms) == len(set(noms)), "aucun nom d'effet en double")
    verifie(len(noms) > 8, "la bibliotheque depasse les 8 boutons FX")

    w.appels.clear()
    gb.appliquer_action(w, {"type": "memory", "col": 4, "row": 2})
    gb.appliquer_action(w, {"type": "effect", "idx": 6})
    gb.appliquer_action(w, {"type": "fx_pad", "col": 1, "row": 4})
    gb.appliquer_action(w, {"type": "play", "action": "playpause"})
    gb.appliquer_action(w, {"type": "play", "action": "cart2"})
    gb.appliquer_action(w, {"type": "fx_name", "name": "Rainbow"})
    gb.appliquer_action(w, {"type": "nawak"})
    verifie(w.appels == [("memory", 4, 2), ("effect", 6), ("fx_pad", 1, 4),
                         ("play", "playpause"), ("play", "cart2"),
                         ("fx_name", "Rainbow")],
            "les actions passent par les points d'entree du show")


# ---------------------------------------------------------------------------
# 3. Persistance
# ---------------------------------------------------------------------------

def test_persistance():
    print("\n[3] Lecture/ecriture de la config")
    import gamepad_boutons as gb

    pages = [{"a": {"type": "memory", "col": 1, "row": 2}},
             {"b": {"type": "effect", "idx": 4}}]
    relu = gb.lire_pages(gb.ecrire_pages(pages))
    verifie(relu == pages, "aller-retour sans perte")

    verifie(gb.lire_pages(None) == [{}, {}], "config absente : pages vides")
    verifie(gb.lire_pages("nawak") == [{}, {}], "config du mauvais type ignoree")
    verifie(gb.lire_pages({"page1": "nawak"}) == [{}, {}], "page invalide ignoree")

    abime = {"page1": {"a": {"type": "memory", "col": 99, "row": 0},
                       "b": {"type": "effect", "idx": 2},
                       "inconnu": {"type": "effect", "idx": 1},
                       "l2": {"type": "effect", "idx": 1}}}
    relu = gb.lire_pages(abime)
    verifie(relu[0] == {"b": {"type": "effect", "idx": 2}},
            "seules les entrees valides survivent (le modificateur est exclu)")

    verifie(len(gb.lire_pages({})) == gb.NB_PAGES,
            "toujours autant de pages que declare")


# ---------------------------------------------------------------------------
# 4. Fronts appui/relache
# ---------------------------------------------------------------------------

def test_fronts():
    print("\n[4] Fronts appui/relache")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)

    import gamepad_client as gc
    pg = faux_pygame()
    ctrl = FauxControleur()

    client = gc.GamepadClient()
    client._ctrl = ctrl
    presses, relaches = [], []
    client.bouton_presse.connect(presses.append)
    client.bouton_relache.connect(relaches.append)

    codes = {bid: getattr(pg, const) for bid, const in gc._BOUTONS}
    ga = {bid: getattr(pg, const) for bid, const in gc._GACHETTES}

    client._sonder_boutons(pg)
    verifie(presses == [] and relaches == [], "rien au repos")

    ctrl.boutons.add(codes["a"])
    client._sonder_boutons(pg)
    verifie(presses == ["a"], "un appui donne un seul front")

    client._sonder_boutons(pg)
    verifie(presses == ["a"], "maintenir n'en donne pas d'autre (pas de repetition)")

    ctrl.boutons.discard(codes["a"])
    client._sonder_boutons(pg)
    verifie(relaches == ["a"], "le relachement est publie")

    # Gachette : hysteresis.
    presses.clear(); relaches.clear()
    ctrl.gachettes[ga["l2"]] = int(0.50 * 32767)
    client._sonder_boutons(pg)
    verifie(presses == [], "gachette a mi-course : pas d'appui")

    ctrl.gachettes[ga["l2"]] = int(0.70 * 32767)
    client._sonder_boutons(pg)
    verifie(presses == ["l2"], "au-dela du seuil haut : appui")

    ctrl.gachettes[ga["l2"]] = int(0.50 * 32767)
    client._sonder_boutons(pg)
    verifie(relaches == [],
            "redescendue entre les deux seuils : toujours tenue (pas de rafale)")

    ctrl.gachettes[ga["l2"]] = int(0.30 * 32767)
    client._sonder_boutons(pg)
    verifie(relaches == ["l2"], "sous le seuil bas : relachee")

    # Le debranchement relache tout : sinon le modificateur reste tenu a vie.
    presses.clear(); relaches.clear()
    ctrl.boutons.add(codes["b"])
    ctrl.gachettes[ga["l2"]] = 32767
    client._sonder_boutons(pg)
    verifie(client.est_enfonce("l2") and client.est_enfonce("b"),
            "deux touches tenues en meme temps")
    relaches.clear()
    client._detacher()
    verifie(sorted(relaches) == ["b", "l2"],
            "le debranchement relache tout ce qui etait tenu")
    verifie(not client.est_enfonce("l2"),
            "plus rien n'est tenu apres un debranchement")


# ---------------------------------------------------------------------------
# 5. Page modificateur + declenchement
# ---------------------------------------------------------------------------

def test_liaison():
    print("\n[5] Liaison : pages et declenchement")
    from PySide6.QtWidgets import QApplication, QWidget
    QApplication.instance() or QApplication(sys.argv)

    import gamepad_link as gl

    hote = QWidget()
    faux = FausseFenetre()
    # GamepadLink veut un QObject comme parent, mais lit son etat sur la
    # fenetre : on greffe les deux sur le meme objet.
    for nom in ("memories", "effect_buttons", "fx_pads", "cartouches",
                "projectors", "appels"):
        setattr(hote, nom, getattr(faux, nom))
    hote.trigger_memory = faux.trigger_memory
    hote.toggle_effect = faux.toggle_effect
    hote._toggle_fx_pad = faux._toggle_fx_pad
    hote._activate_play_pad = faux._activate_play_pad

    link = gl.GamepadLink(hote)
    link.pages = [{"a": {"type": "memory", "col": 0, "row": 0}},
                  {"a": {"type": "effect", "idx": 2}}]

    verifie(link.page_courante() == 0, "page 1 par defaut")
    link._do_bouton("a")
    verifie(faux.appels == [("memory", 0, 0)], "page 1 : la memoire part")

    link.client._enfonces.add(gl.gb.MODIFICATEUR)
    verifie(link.page_courante() == 1, "modificateur tenu : page 2")
    link._do_bouton("a")
    verifie(faux.appels[-1] == ("effect", 2),
            "meme touche, autre page : l'effet part")

    faux.appels.clear()
    link._do_bouton(gl.gb.MODIFICATEUR)
    verifie(faux.appels == [], "le modificateur ne declenche rien lui-meme")

    link.suspendu = True
    link._do_bouton("a")
    verifie(faux.appels == [], "dialogue ouvert : rien ne part")
    link.suspendu = False

    link.boutons_enabled = False
    link._do_bouton("a")
    verifie(faux.appels == [], "raccourcis desactives : rien ne part")
    link.boutons_enabled = True

    faux.appels.clear()
    link._do_bouton("start")
    verifie(faux.appels == [], "touche non assignee : rien ne part")

    # Une action abimee arrivee dans les pages ne doit pas remonter d'exception
    # jusqu'au slot Qt (sinon le processus tombe).
    link.pages[0]["b"] = {"type": "memory", "col": "?", "row": 0}
    link._on_bouton("b")
    verifie(True, "action abimee : aucune exception")

    # La manette doit tourner meme si seuls les boutons servent.
    link.enabled = False
    link.pages = [{"a": {"type": "effect", "idx": 0}}, {}]
    verifie(link.a_des_assignations(), "des assignations sont vues")
    link.pages = [{}, {}]
    verifie(not link.a_des_assignations(), "aucune assignation : vu aussi")

    # ── Cibles ──────────────────────────────────────────────────────────────
    print("\n[5b] Cibles pan/tilt")
    verifie([g for g, _ in link.groupes_de_lyres()] == ["contre", "douche1"],
            "seuls les groupes qui contiennent des lyres sont proposes")
    verifie(dict(link.groupes_de_lyres())["contre"] == 2,
            "le nombre de lyres du groupe est compte")

    link.cible = gl.CIBLE_TOUTES
    verifie(len(link.cibles()) == 3, "« toutes » : les 3 lyres, pas le PAR")

    link.cible = gl.CIBLE_GROUPE + "contre"
    cibles = link.cibles()
    verifie(len(cibles) == 2 and all(p.group == "contre" for p in cibles),
            "cible groupe : seules les lyres de ce groupe")

    link.cible = gl.CIBLE_GROUPE + "groupe_disparu"
    verifie(link.cibles() == [], "groupe absent du show : aucune lyre, aucune erreur")

    verifie(gl.cible_valide("group:contre") == "group:contre",
            "un groupe enregistre est relu tel quel")
    verifie(gl.cible_valide("group:") == gl.CIBLE_SELECTION,
            "prefixe sans nom : retour a la selection")
    verifie(gl.cible_valide("nawak") == gl.CIBLE_SELECTION,
            "valeur inconnue : retour a la selection")
    verifie(gl.cible_valide(None) == gl.CIBLE_SELECTION, "None : retour a la selection")

    # La cible doit survivre a un aller-retour dans le fichier de config.
    link.cible = gl.CIBLE_GROUPE + "douche1"
    relu = gl.GamepadLink(hote)
    relu.from_config(link.to_config())
    verifie(relu.cible == gl.CIBLE_GROUPE + "douche1",
            "la cible groupe survit a l'enregistrement")


# ---------------------------------------------------------------------------
# 6. Rendu
# ---------------------------------------------------------------------------

def test_rendu():
    print("\n[6] Rendu du dessin")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter, QRegion
    QApplication.instance() or QApplication(sys.argv)

    import gamepad_boutons as gb
    w = FausseFenetre()

    widget = gb.ManetteWidget(w)
    widget.resize(1000, 600)
    widget.set_pages([
        {"a": {"type": "memory", "col": 0, "row": 0},
         "b": {"type": "effect", "idx": 3},
         "up": {"type": "memory", "col": 2, "row": 5},
         "r1": {"type": "effect", "idx": 0}},
        {},
    ])
    widget.set_presse("y", True)
    widget.set_selection("l1")

    # Les apercus vont dans le dossier temporaire : un test ne doit pas semer
    # de fichiers dans le depot.
    import tempfile
    dossier = tempfile.gettempdir()
    for style, nom in (("ps", "apercu_manette_ps.png"),
                       ("xbox", "apercu_manette_xbox.png")):
        fichier = os.path.join(dossier, nom)
        widget.set_style(style)
        image = QImage(1000, 600, QImage.Format_ARGB32)
        image.fill(0xFF080808)
        p = QPainter(image)
        # DrawChildren seul : sans lui, `render` repeindrait par-dessus le
        # fond sombre avec le fond par defaut du widget, et l'apercu ne
        # montrerait pas ce que l'utilisateur verra dans le dialogue.
        widget.render(p, QPoint(0, 0), QRegion(),
                      widget.RenderFlag.DrawChildren)
        p.end()
        image.save(fichier)
        print(f"  ->   {fichier}")
    verifie(True, "les deux styles se dessinent sans exception")


if __name__ == "__main__":
    test_geometrie()
    test_actions()
    test_persistance()
    test_fronts()
    test_liaison()
    test_rendu()

    print("\n" + "-" * 60)
    if ECHECS:
        print(f"{len(ECHECS)} ECHEC(S) :")
        for e in ECHECS:
            print("  -", e)
        sys.exit(1)
    print("Tout passe.")
