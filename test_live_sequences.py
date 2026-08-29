# -*- coding: utf-8 -*-
"""Onglet SEQUENCE du mode LIVE : jouer les memoires enregistrees sur les pads.

Trois volets :

  A. Le panneau  — un 7e onglet a cote de MOUVEMENT/DIMMER/COULEURS/GOBO/
     STROB/SPECIAL, une grille de memoires, un POOL (comme les mouvements),
     purge des references mortes.
  B. La source   — ce sont les memoires de PADS, pas les captures REC Lumiere.
  C. Le moteur   — enchainement a deux niveaux (cues d'une memoire, puis
     memoires du pool) et ordre d'ecriture d'une image LIVE :
        moteur IA -> memoire du pool -> restauration des groupes GELES
     Ce qui doit donner : la memoire prime sur l'IA, mais ne deborde jamais
     hors des groupes autorises au LIVE.
"""
import os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
app = QApplication.instance() or QApplication([])

from projector import Projector
from light_timeline import apply_seq_memories_htp, reset_beam_channels, _REPOS_FAISCEAU

echecs = []


def verifie(cond, message):
    if cond:
        print(f"  OK   {message}")
    else:
        print(f"  ECHEC {message}")
        echecs.append(message)


# ===========================================================================
# A. Le panneau LIVE : l'onglet SEQUENCE et son pool
# ===========================================================================
print("\n--- A. Panneau LIVE : onglet SEQUENCE ---")

import sequencer

# La config du panneau vit dans ~/.mystrow_live_panel.json : on la detourne
# vers un fichier temporaire AVANT toute instanciation, sinon le test lirait
# — et le timer de sauvegarde pourrait ecraser — les reglages reels de la
# machine.
_tmp_cfg = os.path.join(tempfile.gettempdir(), "test_live_panel_cfg.json")
sequencer.LiveModePanel._LIVE_PANEL_CFG = _tmp_cfg
if os.path.exists(_tmp_cfg):
    os.remove(_tmp_cfg)

panel = sequencer.LiveModePanel()

verifie(sequencer.LiveModePanel._EFFECT_TABS[-1] == "SÉQUENCE",
        "SEQUENCE est le dernier onglet du panneau d'effets")
verifie(len(panel._effect_tab_btns) == panel._effect_stack.count()
        == len(sequencer.LiveModePanel._EFFECT_TABS),
        "autant de boutons d'onglet que de pages (aucune divergence)")
panel._switch_effect_tab(len(sequencer.LiveModePanel._EFFECT_TABS) - 1)
verifie(panel._effect_stack.currentIndex() == 6,
        "cliquer l'onglet SEQUENCE affiche bien sa page")

# ── La barre d'onglets tient sur UNE ligne, sans deborder ─────────────────
# Le panneau LIVE vit dans un QScrollArea dont la barre horizontale est
# DESACTIVEE : ce qui depasse est coupe, pas atteignable. Un onglet hors champ
# serait un onglet mort, et rien ne le signalerait. D'ou ces deux gardes.
panel.resize(620, 1800)
panel.ensurePolished()
panel.layout().activate()
app.processEvents()
lignes = {b.y() for b in panel._effect_tab_btns.values()}
verifie(len(lignes) == 1,
        f"les {len(panel._effect_tab_btns)} onglets tiennent sur UNE ligne")
# 624 px = ce que le panneau exigeait a six onglets, avec le titre « EFFETS ».
# La police de secours du mode offscreen est PLUS large que la vraie : la
# mesure ici est donc le pire cas.
mini = panel.minimumSizeHint().width()
verifie(mini <= 624,
        f"largeur mini du panneau : {mini} px (plafond historique 624)")

MEMS = [
    {'ref': (0, 0), 'name': "MEM 1.1",  'color': QColor("#0000ff"), 'cues': 1},
    {'ref': (0, 1), 'name': "Intro",    'color': QColor("#ff0000"), 'cues': 3},
    {'ref': (1, 0), 'name': "Refrain",  'color': QColor("#00ff00"), 'cues': 1},
]
_dispo = list(MEMS)
panel.set_sequences_getter(lambda: _dispo)

recu = []
# Piege Qt : un Signal(list) convertit les tuples imbriques en LISTES a la
# traversee. Le recepteur cote main_window doit donc re-tupler avant de s'en
# servir comme cle — c'est ce que fait `_on_live_sequences_changed`.
panel.sequences_changed.connect(lambda refs: recu.append([tuple(r) for r in refs]))

verifie(len(panel._seq_tiles) == 3, "les 3 memoires de pads ont une tuile")
verifie(panel.sequence_pool == [] and panel.current_sequence is None,
        "pool vide au depart, aucune memoire en cours")

panel._on_seq_tile_clicked((0, 1))
panel._on_seq_tile_clicked((1, 0))
verifie(panel.sequence_pool == [(0, 1), (1, 0)],
        "pool multiple, dans l'ordre d'appui")
verifie(panel.current_sequence == (0, 1),
        "la 1re memoire cochee devient celle en cours")
verifie(panel._seq_tiles[(0, 1)].is_playing
        and panel._seq_tiles[(1, 0)].is_selected
        and not panel._seq_tiles[(1, 0)].is_playing,
        "3 etats distincts : en cours / dans le pool / hors pool")
verifie(recu[-1] == [(0, 1), (1, 0)], "le signal porte le pool complet")

panel.set_current_sequence((1, 0))
verifie(panel._seq_tiles[(1, 0)].is_playing
        and not panel._seq_tiles[(0, 1)].is_playing,
        "le moteur deplace la tuile « en cours » sans toucher au pool")
verifie(panel.sequence_pool == [(0, 1), (1, 0)], "le pool n'a pas bouge")

panel._on_seq_tile_clicked((1, 0))
verifie(panel.sequence_pool == [(0, 1)], "re-cliquer une tuile la sort du pool")
verifie(panel.current_sequence == (0, 1),
        "sortir la memoire en cours bascule sur une autre du pool")

# Une memoire effacee du pad ne doit pas rester une reference morte que le
# moteur resoudrait dans le vide a chaque image.
_dispo = [MEMS[0], MEMS[2]]
panel.refresh_sequences()
verifie(panel.sequence_pool == [] and panel.current_sequence is None,
        "une memoire effacee du pad sort du pool")
verifie(recu[-1] == [], "sa disparition est signalee au moteur")

panel._on_seq_tile_clicked((0, 0))
_dispo = []
panel.refresh_sequences()
verifie(len(panel._seq_tiles) == 0, "aucune memoire : grille vide, pas de plantage")
verifie(panel.sequence_pool == [] and recu[-1] == [],
        "un show sans memoire vide le pool ET previent le moteur")

panel.deleteLater()

# Un nom de memoire est libre. Sans garde-fou, sa largeur remonte jusqu'au
# panneau LIVE, qui reclamait alors 1026 px de large au lieu de 624 : le
# panneau deborde et le sequenceur avec.
long_nom = "Refrain chaud contre-jour lointain"
tuile = sequencer._SeqTile((0, 0), long_nom, QColor("#ff8800"), cues=4)
tuile.resize(103, 54)
tuile.show()
app.processEvents()
verifie(tuile._lbl.text() != long_nom and tuile._lbl.text().endswith("…"),
        "un nom trop long est ecourte dans la tuile")
verifie(long_nom in tuile.toolTip() and "4" in tuile.toolTip(),
        "l'infobulle donne le nom complet et le nombre de cues")
verifie(tuile._cues_lbl.text() == "×4",
        "une memoire a plusieurs cues affiche son compteur")
courte = sequencer._SeqTile((0, 1), "MEM 1.2", QColor("#ff2200"), cues=1)
courte.resize(103, 54)
courte.show()
app.processEvents()
verifie(courte._lbl.text() == "MEM 1.2", "un nom court n'est pas touche")
verifie(courte._cues_lbl.text() == "", "un simple look n'affiche pas de compteur")
tuile.deleteLater()
courte.deleteLater()


# ===========================================================================
# B. La source : memoires de PADS, pas captures REC Lumiere
# ===========================================================================
print("\n--- B. Source : les memoires des pads ---")

from main_window import MainWindow


class FauxPanel:
    sequence_intensity = 100
    sequence_duration  = 7      # SECONDES
    sequence_positions = False

    def __init__(self, pool=()):
        self.sequence_pool = list(pool)
        self.courante = None
        self.overrides = set()

    def set_current_sequence(self, ref):
        self.courante = ref

    def set_sequence_overrides(self, cles):
        self.overrides = set(cles or ())


class FauxSeq:
    def __init__(self, panel):
        self.live_panel = panel


class FauxEngine:
    _bpm = 120.0


class FauxFxSrc:
    def __init__(self, groupes):
        self.allowed_groups = groupes
        self.active_special = None      # 'strobe', 'fixe_blanc'...
        self.ia_mode        = 'musical'


class FauxMW:
    """Le strict minimum touche par les methodes testees."""
    _fx_clip_ids = set()
    # Empruntees telles quelles a MainWindow : c'est bien le code de production
    # qu'on teste, pas une reecriture.
    _LIVE_SEQ_FROZEN_ATTRS = MainWindow._LIVE_SEQ_FROZEN_ATTRS
    _live_seq_scope        = MainWindow._live_seq_scope
    _live_seq_cues         = MainWindow._live_seq_cues
    _live_seq_len          = MainWindow._live_seq_len
    _live_seq_state        = MainWindow._live_seq_state
    _live_seq_overrides    = MainWindow._live_seq_overrides
    _SEQ_GOBO_ATTRS        = MainWindow._SEQ_GOBO_ATTRS

    def __init__(self, memoires, projecteurs, pool=(), groupes_live=None):
        self.memories    = memoires
        self.projectors  = projecteurs
        self.seq         = FauxSeq(FauxPanel(pool))
        self.live_engine = FauxEngine()
        self._fx_src     = FauxFxSrc(groupes_live or set())


look = {"level": 90, "base_color": "#0000ff", "pan": 32768, "tilt": 32768,
        "gobo": 40, "channel_extras": {7: 200}}
vert = dict(look, base_color="#00ff00", gobo=0)
bleu = dict(look, base_color="#0000ff")
jaune = dict(look, base_color="#ffff00")

# Colonne 0 : une memoire simple et une SEQUENCE de 3 cues minutee.
# Colonne 50 : une capture REC Lumiere — elle ne vit pas sur les pads.
memoires = [
    [{"cues": [{"projectors": [look, look, look], "duration": 0}],
      "name": "Ambiance salle"},
     {"cues": [{"projectors": [vert,  vert,  vert],  "duration": 2, "label": "Cue 1"},
               {"projectors": [bleu,  bleu,  bleu],  "duration": 3, "label": "Cue 2"},
               {"projectors": [jaune, jaune, jaune], "duration": 1, "label": "Cue 3"}],
      "loop": True, "name": "Intro"}],
    [{"cues": [{"projectors": [look, look, look]}], "name": "REC 1", "_rec": True}],
]

projs = [Projector("face", "Face 1"),
         Projector("face", "Face 2"),
         Projector("contre", "Contre 1")]

faux = FauxMW(memoires, projs)
listees = MainWindow._get_live_sequences(faux)
verifie([e['name'] for e in listees] == ["Ambiance salle", "Intro"],
        "les memoires de pads sont listees, la capture REC Lumiere est ecartee")
verifie([e['ref'] for e in listees] == [(0, 0), (0, 1)],
        "chaque entree porte sa reference (colonne, ligne)")
verifie([e['cues'] for e in listees] == [1, 3],
        "le nombre de cues distingue un look d'une vraie sequence")
verifie(listees[0]['color'].name() == "#0000ff",
        "la pastille prend la couleur dominante du cue")

sans_nom = [[{"cues": [{"projectors": []}]}]]
verifie(MainWindow._get_live_sequences(
            FauxMW(sans_nom, projs))[0]['name'] == "MEM 1.1",
        "une memoire sans nom retombe sur son numero de pad")


# ===========================================================================
# C. Le moteur : enchainement des cues puis du pool
# ===========================================================================
print("\n--- C. Moteur : enchainement cues -> pool ---")

def derouler(mw, duree_ms, pas=50):
    """Fait tourner le moteur comme le fait le LIVE : une image tous les 50 ms.

    Rend la liste des BASCULES (t, ref, cue). L'etat n'avance que d'un cran par
    image — c'est le meme principe que le cycle des mouvements — donc sauter
    dans le temps ne testerait rien de reel.
    """
    bascules, precedent = [], None
    for t in range(0, duree_ms, pas):
        etat = MainWindow._live_seq_state(mw, t)
        if etat != precedent:
            bascules.append((t, etat))
            precedent = etat
    return bascules


# Pool d'UNE memoire a 3 cues (2 s, 3 s, 1 s) : elle deroule et reboucle.
seule = FauxMW(memoires, projs, pool=[(0, 1)])
verifie(derouler(seule, 7000) == [(0,    ((0, 1), 0)),
                                  (2000, ((0, 1), 1)),
                                  (5000, ((0, 1), 2)),
                                  (6000, ((0, 1), 0))],
        "les cues s'enchainent sur LEURS durees (2 s, 3 s, 1 s), puis rebouclent")
verifie(seule.seq.live_panel.courante == (0, 1),
        "le panneau est tenu au courant de la memoire jouee")

# Pool de DEUX memoires : la sequence se deroule, puis la main passe au look —
# qui n'a aucune duree propre et tient donc le temps du curseur DUREE (7 s).
duo = FauxMW(memoires, projs, pool=[(0, 1), (0, 0)])
verifie(derouler(duo, 14000) == [(0,     ((0, 1), 0)),
                                 (2000,  ((0, 1), 1)),
                                 (5000,  ((0, 1), 2)),
                                 (6000,  ((0, 0), 0)),
                                 (13000, ((0, 1), 0))],
        "sequence deroulee -> look du pool (duree du curseur) -> retour")

# Le curseur DUREE est en SECONDES : deux looks sans minutage alternent
# exactement a cette cadence, quel que soit le BPM detecte — c'est tout
# l'interet du passage aux secondes.
looks = [[{"cues": [{"projectors": [vert]}],  "name": "Look A"},
          {"cues": [{"projectors": [jaune]}], "name": "Look B"}]]
for secondes in (1, 10, 30):
    court = FauxMW(looks, projs, pool=[(0, 0), (0, 1)])
    court.seq.live_panel.sequence_duration = secondes
    attendu = list(range(0, 31000, secondes * 1000))
    verifie([t for t, _ in derouler(court, 31000)] == attendu,
            f"curseur DUREE a {secondes} s : bascule toutes les {secondes} s")

# ... et cette cadence ne doit PAS dependre du BPM : sans musique, le moteur
# retombe a son plancher de 60 BPM, ce qui aurait double les durees si on
# comptait encore en mesures.
silence = FauxMW(looks, projs, pool=[(0, 0), (0, 1)])
silence.seq.live_panel.sequence_duration = 10
silence.live_engine._bpm = 0.0            # aucun tempo detecte
verifie([t for t, _ in derouler(silence, 31000)] == [0, 10000, 20000, 30000],
        "sans BPM detecte (silence), la cadence reste de 10 s")

vide = FauxMW(memoires, projs, pool=[])
verifie(MainWindow._live_seq_state(vide, 0) is None, "pool vide : rien a jouer")


# ===========================================================================
# D. Ordre d'ecriture d'une image LIVE et gel des groupes exclus
# ===========================================================================
print("\n--- D. Image LIVE : IA -> memoire -> degel ---")

riche = {"level": 90, "base_color": "#0000ff", "pan": 32768, "tilt": 32768,
         "gobo": 40, "prism": 200, "zoom": 77, "focus": 33, "shutter": 128,
         "color_wheel": 64, "effects": 55, "mode_value": 22, "iris": 99,
         "uv": 111, "amber_boost": 88, "channel_extras": {7: 200}}
MEM_RICHE = [[{"cues": [{"projectors": [riche, riche, riche]}], "name": "Riche"}]]

ALLOWED = {"face"}          # « Groupe Eclairage » du panneau LIVE


def image_live(mw, brightness_ok=True):
    """Une image de `_apply_live_state`, dans son ordre reel."""
    gel = [(p, p.level, QColor(p.color), QColor(p.base_color), p.gobo)
           for p in projs if p.group not in ALLOWED]
    for p in projs:                       # le moteur IA peint le perimetre
        if p.group in ALLOWED:
            p.level, p.base_color, p.color = 60, QColor("#ff0000"), QColor("#990000")
    MainWindow._apply_live_sequences(mw, 0)
    for (p, lv, col, base, gobo) in gel:  # degel de `_apply_live_state`
        p.level, p.color, p.base_color, p.gobo = lv, col, base, gobo


hors = projs[2]                      # groupe « contre », exclu du LIVE
hors.level = 44
hors.base_color = QColor("#00ff00")
hors.color = QColor("#009900")
hors.prism, hors.zoom, hors.color_wheel, hors.iris, hors.uv = 7, 12, 3, 5, 6
hors.channel_extras = {2: 9}
# `strobe_speed` n'est PAS declare sur Projector : il n'existe que si quelqu'un
# l'a ecrit. Le gel doit donc savoir SUPPRIMER un attribut que la memoire aurait
# cree, pas seulement restaurer une ancienne valeur.
_MANQUANT = object()
verifie(not hasattr(hors, 'strobe_speed'),
        "au depart, le projecteur hors perimetre n'a pas de canal strobe")
avant = {a: getattr(hors, a, _MANQUANT) for a in MainWindow._LIVE_SEQ_FROZEN_ATTRS}

mw_gel = FauxMW(MEM_RICHE, projs, pool=[(0, 0)], groupes_live=ALLOWED)
image_live(mw_gel)
verifie(projs[0].base_color.name() == "#0000ff" and projs[0].level == 90,
        "la memoire prime sur ce que l'IA vient d'ecrire")
verifie(projs[0].prism == 200 and projs[0].uv == 111 and projs[0].channel_extras == {7: 200},
        "elle pose tout son faisceau et ses canaux bruts")
bouges = [a for a in MainWindow._LIVE_SEQ_FROZEN_ATTRS
          if getattr(hors, a, _MANQUANT) != avant[a]]
verifie(bouges == [],
        "hors perimetre, RIEN ne bouge (prisme, roue, iris, UV, canaux bruts...)")
verifie(not hasattr(hors, 'strobe_speed'),
        "et la memoire ne lui a pas CREE de canal strobe au passage")

# Le gel de `_apply_live_state` ne couvre QUE level/couleur/pan/tilt/gobo/strobe :
# sans le gel propre a la sequence, le prisme et les canaux bruts fuiraient.
verifie('prism' in MainWindow._LIVE_SEQ_FROZEN_ATTRS
        and 'channel_extras' in MainWindow._LIVE_SEQ_FROZEN_ATTRS,
        "le gel de la sequence couvre bien plus que celui du moteur IA")

# Curseur INTENS.
mw_gel.seq.live_panel.sequence_intensity = 50
image_live(mw_gel)
verifie(projs[0].level == 45, "le curseur INTENS. module le niveau de la memoire")

# Sans restriction de groupe, la memoire s'applique partout.
mw_tout = FauxMW(MEM_RICHE, projs, pool=[(0, 0)], groupes_live=set())
MainWindow._apply_live_sequences(mw_tout, 0)
verifie(hors.prism == 200 and hors.level == 90,
        "sans « Groupe Eclairage » defini, le LIVE couvre tout le rig")

# Extinction : `apply_seq_memories_htp` POSE sans effacer, il faut relacher.
restes = {a: getattr(projs[0], a) for a in ("gobo", "prism", "zoom")
          if getattr(projs[0], a) != _REPOS_FAISCEAU[a]}
verifie(restes != {}, "sans nettoyage, le faisceau reste colle (comportement connu)")
reset_beam_channels(projs, blackout=False)
restes = {a: getattr(projs[0], a) for a in _REPOS_FAISCEAU
          if getattr(projs[0], a) != _REPOS_FAISCEAU[a]}
verifie(restes == {} and projs[0].channel_extras == {},
        "le nettoyage de sortie relache faisceau et canaux bruts")


# ===========================================================================
# E. Ce qui prime sur quoi : la memoire POSE, elle n'EFFACE pas
# ===========================================================================
print("\n--- E. Priorite : memoire vs reglages des autres onglets ---")

# La memoire n'allume QUE le projecteur 0 et ne regle NI strobe NI canal brut.
# Le projecteur 1, elle ne le vise pas : le moteur LIVE doit garder la main.
allume = {"level": 90, "base_color": "#0000ff", "pan": 32768, "tilt": 32768,
          "strobe_speed": 0, "channel_extras": {}}
noir   = {"level": 0, "base_color": "#000000", "pan": 32768, "tilt": 32768,
          "strobe_speed": 0, "channel_extras": {}}
MEM_PARTIELLE = [[{"cues": [{"projectors": [allume, noir, noir]}], "name": "Look"}]]

mw_prio = FauxMW(MEM_PARTIELLE, projs, pool=[(0, 0)])
for p in projs:                       # ce que les autres onglets ont ecrit
    p.level, p.base_color, p.color = 60, QColor("#ff0000"), QColor("#990000")
    p.gobo = 12                       # onglet GOBO
    p.strobe_speed = 180              # onglet STROB
    p.channel_extras = {5: 200}       # canaux bruts
MainWindow._apply_live_sequences(mw_prio, 0)

vise, libre = projs[0], projs[1]
verifie(vise.base_color.name() == "#0000ff" and vise.level == 90,
        "projo VISE : la memoire prime sur les onglets COULEURS et DIMMER")
verifie(libre.base_color.name() == "#ff0000" and libre.level == 60,
        "projo NON vise : le moteur LIVE garde couleur et niveau")
verifie(vise.gobo == 12 and libre.gobo == 12,
        "gobo au repos dans la memoire : l'onglet GOBO reste vivant")
verifie(vise.strobe_speed == 180 and libre.strobe_speed == 180,
        "strobe au repos dans la memoire : l'onglet STROB reste vivant")
verifie(vise.channel_extras == {5: 200} and libre.channel_extras == {5: 200},
        "canaux bruts au repos dans la memoire : ils ne sont pas vides")

# ... mais quand la memoire REGLE ces canaux, c'est bien elle qui mene.
strob = dict(allume, strobe_speed=60, channel_extras={9: 77})
MEM_STROB = [[{"cues": [{"projectors": [strob, noir, noir]}], "name": "Strob"}]]
mw_s = FauxMW(MEM_STROB, projs, pool=[(0, 0)])
for p in projs:
    p.strobe_speed = 180
    p.channel_extras = {5: 200}
MainWindow._apply_live_sequences(mw_s, 0)
verifie(projs[0].strobe_speed == 60 and projs[0].channel_extras == {9: 77},
        "une memoire qui REGLE strobe et canaux bruts prime bien")
verifie(projs[1].strobe_speed == 180 and projs[1].channel_extras == {5: 200},
        "et seulement sur le projecteur concerne")


# ── Interrupteur POSITIONS ────────────────────────────────────────────────
# L'onglet MOUVEMENT refuse de rester vide : un mouvement tourne TOUJOURS en
# LIVE. Une memoire enregistree hors du centre figerait donc les lyres en
# permanence. L'interrupteur decide qui tient le pan/tilt.
print()
# L'invariant qui justifie tout l'interrupteur : si l'onglet MOUVEMENT pouvait
# etre vide, il suffirait de tout decocher pour rendre les positions a la
# memoire. Il ne peut pas — ce test le verifie sur le vrai panneau.
mov = sequencer.LiveModePanel()
for cle, _icone, _lbl in sequencer.LiveModePanel._MOVEMENTS:
    mov._on_movement_selected(cle)      # tout decocher
verifie(len(mov._movement_patterns) >= 1,
        "l'onglet MOUVEMENT refuse de rester vide : un mouvement tourne toujours")
mov.deleteLater()

pointe = {"level": 90, "base_color": "#0000ff", "pan": 12000, "tilt": 48000,
          "strobe_speed": 0, "channel_extras": {}}
MEM_POS = [[{"cues": [{"projectors": [pointe, pointe, pointe]}], "name": "Pointe"}]]

for impose, attendu_pan, message in (
        (False, 40000, "POSITIONS decoche : le mouvement garde les lyres"),
        (True,  12000, "POSITIONS coche : la memoire pointe les lyres")):
    mw_pos = FauxMW(MEM_POS, projs, pool=[(0, 0)])
    mw_pos.seq.live_panel.sequence_positions = impose
    for p in projs:                    # ce que l'onglet MOUVEMENT vient d'ecrire
        p.pan, p.tilt = 40000, 20000
    MainWindow._apply_live_sequences(mw_pos, 0)
    verifie(projs[0].pan == attendu_pan, message)


# ── SPECIAL garde la priorite absolue ─────────────────────────────────────
# Stroboscope / Strobe couleur / Fixe blanc sont le bouton panique du live. Le
# moteur les declare « priorite absolue » : une sequence ne doit PAS repasser
# par-dessus, sinon on appuie sur STROBE et une partie de la salle ne strobe pas.
# ===========================================================================
# F. Marquage des onglets repris par la memoire en cours
# ===========================================================================
print("\n--- F. Marquage des onglets repris ---")

# Cinq memoires aux contenus differents : le marquage doit suivre le CONTENU,
# pas se contenter de « une sequence tourne, donc tout est repris ».
base_on = {"level": 90, "base_color": "#0000ff", "pan": 32768, "tilt": 32768,
           "gobo": 0, "strobe_speed": 0, "channel_extras": {}}
rien    = {"level": 0, "base_color": "#000000", "pan": 32768, "tilt": 32768,
           "gobo": 0, "strobe_speed": 0, "channel_extras": {}}

MEM_MARQ = [[
    {"cues": [{"projectors": [base_on, rien]}], "name": "Couleur seule"},
    {"cues": [{"projectors": [dict(base_on, gobo=48), rien]}], "name": "Avec gobo"},
    {"cues": [{"projectors": [dict(base_on, strobe_speed=120), rien]}], "name": "Avec strobe"},
    {"cues": [{"projectors": [dict(base_on, pan=12000, tilt=48000), rien]}], "name": "Pointee"},
    {"cues": [{"projectors": [rien, rien]}], "name": "Bloc noir"},
]]

mq = FauxMW(MEM_MARQ, projs)
verifie(MainWindow._live_seq_overrides(mq, (0, 0), 0) == {"couleurs", "dimmer"},
        "memoire qui allume seulement : COULEURS + DIMMER marques")
verifie(MainWindow._live_seq_overrides(mq, (0, 1), 0) == {"couleurs", "dimmer", "gobo"},
        "memoire avec gobo : GOBO marque en plus")
verifie(MainWindow._live_seq_overrides(mq, (0, 2), 0) == {"couleurs", "dimmer", "strob"},
        "memoire avec strobe : STROB marque en plus")
verifie(MainWindow._live_seq_overrides(mq, (0, 4), 0) == set(),
        "memoire qui n'allume rien : aucun onglet marque")

# MOUVEMENT n'est marque que si l'interrupteur POSITIONS l'autorise.
verifie("mouvement" not in MainWindow._live_seq_overrides(mq, (0, 3), 0),
        "POSITIONS decoche : MOUVEMENT non marque, meme sur une memoire pointee")
mq.seq.live_panel.sequence_positions = True
verifie("mouvement" in MainWindow._live_seq_overrides(mq, (0, 3), 0),
        "POSITIONS coche : MOUVEMENT est marque")
mq.seq.live_panel.sequence_positions = False

# Hors perimetre LIVE, la memoire ne touche a rien : rien a marquer.
hors_perim = FauxMW(MEM_MARQ, projs, groupes_live={"contre"})
verifie(MainWindow._live_seq_overrides(hors_perim, (0, 1), 0) == set(),
        "projo hors du Groupe Eclairage : son contenu ne marque aucun onglet")

# Le marquage remonte bien au panneau.
vivant = FauxMW(MEM_MARQ, projs, pool=[(0, 1)])
MainWindow._live_seq_state(vivant, 0)
verifie(vivant.seq.live_panel.overrides == {"couleurs", "dimmer", "gobo"},
        "le panneau recoit le marquage de la memoire jouee")
vide2 = FauxMW(MEM_MARQ, projs, pool=[])
vide2.seq.live_panel.overrides = {"couleurs"}
MainWindow._live_seq_state(vide2, 0)
verifie(vide2.seq.live_panel.overrides == set(),
        "pool vide : le marquage est efface")

# Cote panneau : le marquage passe par la COULEUR, jamais par le libelle —
# sinon la barre s'allonge et deborde du QScrollArea sans defilement.
pan2 = sequencer.LiveModePanel()
libelles_avant = {l: b.text() for l, b in pan2._effect_tab_btns.items()}
larg_avant = pan2.minimumSizeHint().width()
pan2.set_sequence_overrides({"couleurs", "dimmer", "gobo"})
verifie({l: b.text() for l, b in pan2._effect_tab_btns.items()} == libelles_avant,
        "les libelles d'onglets ne changent pas (aucun caractere ajoute)")
verifie(pan2.minimumSizeHint().width() == larg_avant,
        "et la largeur du panneau ne bouge pas d'un pixel")
verifie("#aa7733" in pan2._effect_tab_btns["COULEURS"].styleSheet(),
        "l'onglet repris passe en ambre")
verifie("#aa7733" not in pan2._effect_tab_btns["STROB"].styleSheet(),
        "un onglet non repris garde son style")
verifie(pan2._effect_tab_btns["COULEURS"].toolTip() != "",
        "l'infobulle rappelle que l'onglet agit toujours ailleurs")
pan2.deleteLater()


print("\n--- G. SPECIAL prime sur la sequence ---")

verifie(MainWindow._live_special_actif(FauxMW(MEM_PARTIELLE, projs)) is False,
        "sans effet special, la sequence a le champ libre")

mw_sp = FauxMW(MEM_PARTIELLE, projs, pool=[(0, 0)])
mw_sp._fx_src.active_special = 'strobe'
verifie(MainWindow._live_special_actif(mw_sp) is True,
        "un effet special en cours est bien detecte")
mw_sp._fx_src.ia_mode = 'ambiance'
verifie(MainWindow._live_special_actif(mw_sp) is False,
        "sauf en Ambiance, ou le moteur n'applique aucun special")

print()
if echecs:
    print(f"{len(echecs)} echec(s) :")
    for m in echecs:
        print(f"  - {m}")
    sys.exit(1)
print("Tout est vert.")
