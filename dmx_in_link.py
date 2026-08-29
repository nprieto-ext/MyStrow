"""
dmx_in_link.py — Ce que MyStrow FAIT du DMX entrant, et son reglage.

artnet_input.py recoit les trames ; ce module decide de l'effet. Meme partage
que gamepad_client.py / gamepad_link.py, et pour la meme raison : toute la
logique se teste sans reseau ni pupitre branche.

UN PATCH, RIEN D'AUTRE
-----------------------
Une seule table : les 512 adresses de l'univers d'entree, et en face de chacune
ce qu'elle pilote — un groupe (A a H), une memoire (MEM 1 a 99), une colonne
d'effets (FX 1 a 8), le volume du lecteur, ou la vitesse des effets. C'est le
meme vocabulaire que le selecteur de slot de l'AKAI (`_AKAI_SLOT_OPTIONS`), et
c'est voulu : « MEM 3 » designe la meme chose des deux cotes.

Rien d'autre a regler. Pas de mode, pas d'adresse de depart, pas de priorite,
pas d'apprentissage : le numero du canal qui BOUGE passe en cyan dans la table,
donc bouger un fader du pupitre suffit a le reconnaitre — c'est ce que faisait
l'apprentissage, en moins de clics et sans suspendre le pilotage.

LA CIBLE NE DEPEND PAS DE LA PAGE
----------------------------------
Le patch designe une CIBLE (le groupe A, la memoire 12), et PAS une tranche de
la surface AKAI. C'est ce qui permet a un pupitre de piloter tout le rig alors
qu'une seule page de layout est a l'ecran : la cible d'une tranche ne depend
pas de la page, seuls les widgets — le fader affiche, le pad actif — sont lies
a la colonne visible. C'est la philosophie de `_sync_controls_to_state` : le
rig est la source de verite, l'AKAI n'en est qu'une vue.

Deux chemins, choisis cible par cible :

    - la cible est sur la page AFFICHEE  -> `on_midi_fader`, chemin inchange
    - sinon                              -> `apply_slot_level_offpage`
                                            (ou `apply_memory_level` pour MEM)

Les memoires ont leur propre porte parce que le mix des memoires etait indexe
par colonne VISIBLE : hors page, une MEM n'avait aucune cible definie. C'est
`MainWindow._mem_rows` (ligne active par MEM, independante de la page) et
`_mem_ext_levels` (niveau venu du pupitre) qui la lui donnent.

L'UNIVERS D'ENTREE EST LE 5e
-----------------------------
MyStrow emet jusqu'a QUATRE univers (`ArtNetDMX.universe` .. +3). Le cinquieme
est donc le premier qui ne peut pas entrer en collision avec notre propre
sortie — c'est la valeur par defaut, et il n'y a plus de reglage a comprendre.
Si le pupitre emet malgre tout ailleurs, l'etat le dit (« des donnees arrivent
sur l'univers 0 ») et un bouton bascule l'ecoute en un clic.

TROIS DECISIONS QUI NE SONT PAS EVIDENTES
------------------------------------------
1. **La premiere trame ne pilote RIEN.** Elle sert de reference. Sans ca,
   cocher « activer » pendant un show enverrait d'un coup tout le parc sur les
   valeurs du pupitre — c'est-a-dire au NOIR si ses faders sont en bas. On
   attend donc qu'un canal BOUGE pour lui obeir : le premier geste sur le
   pupitre prend la main, et la case a cocher ne casse jamais un show en cours.

2. **LTP, et rien d'autre.** Quand le pupitre et l'AKAI se disputent une
   cible, le dernier qui bouge gagne : c'est ce que fait n'importe quelle
   console, et c'est le seul comportement ou pousser un fader a un effet
   visible a coup sur. Le HTP a existe le temps d'une version, en reglage ; il
   ne servait qu'a melanger deux pupitres et coutait un choix a comprendre a
   tous les autres.

3. **On n'obeit qu'aux canaux qui CHANGENT.** Un pupitre emet 40 trames de 512
   octets par seconde, en continu, meme a l'arret. Reappliquer chaque canal a
   chaque trame ecraserait en permanence l'AKAI et l'interface, et le LTP
   n'aurait plus aucun sens : le pupitre gagnerait toujours, 40 fois par
   seconde.
"""

import json
import os

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from artnet_input import DMX_SLOTS, DEFAULT_PORT, ArtNetReceiver
from video_link import STYLE_DIALOGUE
from i18n import tr

try:
    from artnet_dmx import OUTPUT_INPUT
except ImportError:
    OUTPUT_INPUT = -2

CONFIG_FILE = os.path.expanduser("~/.mystrow_dmxin.json")

# Cadence de lecture. Inutile d'aller plus vite que la sortie DMX : personne ne
# verra la difference, et on evite de repeindre l'interface 40 fois par seconde.
POLL_MS = 40

# Le 5e univers : MyStrow en emet quatre (universe .. universe+3), celui-la est
# donc libre par construction. Cf. l'en-tete du module.
DEFAULT_UNIVERSE = 5

# ── Le vocabulaire des cibles ───────────────────────────────────────────────
# Volontairement identique a `_AKAI_SLOT_OPTIONS` de main_window : « MEM 3 »
# veut dire la meme chose dans le patch DMX et dans le selecteur de slot.
GROUPES = ["A", "B", "C", "D", "E", "F", "G", "H"]
MEM_MAX = 99
FX_MAX = 8
CIBLE_AUCUNE = ""
CIBLE_PLAY = "PLAY"
CIBLE_VITESSE = "VITESSE"

# Miroir d'AKAI_GROUP_MAP (main_window) : sert a relire les vieux slots au
# format {"groups": ["face"]}. Duplique plutot qu'importe pour que ce module
# reste testable sans charger main_window.
_LETTRE_PAR_GROUPE = {
    "face": "A", "lat": "B", "contre": "C", "douche1": "D",
    "douche2": "E", "douche3": "F", "groupe_g": "G", "groupe_h": "H",
}

# Index du fader 9 (vitesse des effets) dans MainWindow.faders.
FADER_VITESSE = 8

# Sentinelle : « cette ligne n'a jamais eu de valeur », a distinguer d'un canal
# absent (—) pour ne pas allumer toute la table au premier rafraichissement.
_MANQUANT = object()


# ── fonctions pures (testables sans Qt) ─────────────────────────────────────

def cibles():
    """Toutes les cibles patchables, dans l'ordre ou on les propose."""
    return (list(GROUPES)
            + [f"MEM {i}" for i in range(1, MEM_MAX + 1)]
            + [f"FX {i}" for i in range(1, FX_MAX + 1)]
            + [CIBLE_PLAY, CIBLE_VITESSE])


_CIBLES = set(cibles())


def is_cible(option):
    return option in _CIBLES


def cible_label(option):
    """Libelle affiche pour une cible ; « MEM 3 » et « FX 2 » parlent d'eux-memes."""
    if not option:
        return tr("dmxin_cible_aucune")
    if option == CIBLE_PLAY:
        return tr("dmxin_cible_play")
    if option == CIBLE_VITESSE:
        return tr("dmxin_cible_vitesse")
    if option in GROUPES:
        return tr("dmxin_cible_groupe", g=option)
    return option


# Groupes places d'office en tete du patch d'usine. A..G : le 8e (H) reste
# libre, c'est le decoupage du parc, pas une limite technique.
GROUPES_DEFAUT = 7


def default_patch():
    """Le patch d'usine : les groupes A a G, puis les memoires.

        canal   1 ..   7   ->  groupes A a G
        canal   8 .. 106   ->  MEM 1 a MEM 99

    Un pupitre branche pour la premiere fois doit faire quelque chose tout de
    suite, sans 106 clics prealables. Les groupes viennent en premier parce que
    ce sont les premiers faders qu'on monte en show ; les memoires suivent, dans
    l'ordre, comme les faders d'une console. Le reste (FX, PLAY, vitesse) se
    patche a la main — et « Tout effacer » repart d'une table vide.
    """
    patch = {i + 1: GROUPES[i] for i in range(GROUPES_DEFAUT)}
    patch.update({GROUPES_DEFAUT + i: f"MEM {i}" for i in range(1, MEM_MAX + 1)})
    return patch


def mem_col_for(option):
    """« MEM 3 » -> 2 (colonne memoire 0-based), sinon None."""
    if not isinstance(option, str) or not option.startswith("MEM "):
        return None
    try:
        col = int(option.split()[1]) - 1
    except (IndexError, ValueError):
        return None
    return col if 0 <= col < MEM_MAX else None


def option_for_slot(slot):
    """Cible designee par un slot de layout AKAI, ou "" si on ne sait pas.

    C'est ce qui relie le patch a la page affichee : si un slot de la page
    porte la meme cible, le canal passe par le chemin MIDI normal.
    """
    if not isinstance(slot, dict):
        return CIBLE_AUCUNE
    stype = slot.get("type")
    if stype == "memory":
        try:
            return f"MEM {int(slot.get('mem_col', 0)) + 1}"
        except (TypeError, ValueError):
            return CIBLE_AUCUNE
    if stype == "fx":
        try:
            return f"FX {int(slot.get('fx_col', 0)) + 1}"
        except (TypeError, ValueError):
            return CIBLE_AUCUNE
    if stype == "play":
        return CIBLE_PLAY
    if stype == "group":
        lettre = slot.get("group")
        if lettre in GROUPES:
            return lettre
        for nom in (slot.get("groups") or []):      # ancien format
            if nom in _LETTRE_PAR_GROUPE:
                return _LETTRE_PAR_GROUPE[nom]
    return CIBLE_AUCUNE


def slot_for_option(option):
    """Slot synthetique a passer a `apply_slot_level_offpage`.

    None pour les memoires et la vitesse : elles ont leur propre chemin, l'une
    parce qu'un mix de memoires ne se resume pas a un niveau de groupe, l'autre
    parce que le fader 9 est global et toujours visible.
    """
    if option in GROUPES:
        return {"type": "group", "group": option, "label": option}
    if option == CIBLE_PLAY:
        return {"type": "play", "label": "PLAY"}
    if isinstance(option, str) and option.startswith("FX "):
        try:
            return {"type": "fx", "fx_col": int(option.split()[1]) - 1,
                    "label": option}
        except (IndexError, ValueError):
            return None
    return None


def normalize_patch(raw):
    """Nettoie un patch venu du disque -> {canal: cible}.

    Tolerant a dessein : une config abimee ne doit pas empecher l'entree DMX de
    fonctionner ni l'ouverture du dialogue. Les lignes illisibles sont jetees
    une par une, et un canal ne pilote qu'UNE cible — le dictionnaire s'en
    charge tout seul.
    """
    out = {}
    if isinstance(raw, dict):
        items = [{"channel": k, "slot": v} for k, v in raw.items()]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            canal = int(item.get("channel", 0))
        except (TypeError, ValueError):
            continue
        if not (1 <= canal <= DMX_SLOTS):
            continue
        option = str(item.get("slot", "") or "").strip().upper()
        if is_cible(option):
            out[canal] = option
    return out


def page_slots(window, page):
    """Les 8 slots d'une page de layout, ou [] si elle n'existe pas."""
    try:
        pages = list(getattr(window, "_bank_pages", None) or [])
        if 0 <= int(page) < len(pages):
            return list(pages[int(page)] or [])
    except Exception:
        pass
    return []


def patch_from_legacy(cfg, window=None):
    """Convertit un reglage 3.1.88 (modes Patch / Libre, pages) en patch plat.

    La version precedente designait une TRANCHE (page + colonne) ; on relit donc
    le layout pour retrouver ce que cette tranche pilotait, et on garde la
    cible. Le mode Patch deroulait 20 pages : on ne reprend que la premiere,
    c'est-a-dire les 8 premiers faders du pupitre, plus la vitesse — reproduire
    160 canaux dont la plupart pointent sur les memes cibles ne rendrait service
    a personne.
    """
    patch = {}
    if not isinstance(cfg, dict):
        return patch
    assignations = cfg.get("assignments")
    if cfg.get("mode") == "libre" and isinstance(assignations, (list, tuple)):
        for item in assignations:
            if not isinstance(item, dict):
                continue
            try:
                canal = int(item.get("channel", 0))
            except (TypeError, ValueError):
                continue
            if not (1 <= canal <= DMX_SLOTS):
                continue
            if item.get("type") == "speed":
                patch[canal] = CIBLE_VITESSE
                continue
            slots = page_slots(window, item.get("page", 0))
            try:
                tranche = int(item.get("tranche", -1))
            except (TypeError, ValueError):
                continue
            if 0 <= tranche < len(slots):
                option = option_for_slot(slots[tranche])
                if option:
                    patch[canal] = option
        return patch

    try:
        depart = int(cfg.get("start_channel", 0))
    except (TypeError, ValueError):
        return patch
    if not (1 <= depart <= DMX_SLOTS):
        return patch
    for i, slot in enumerate(page_slots(window, 0)[:8]):
        option = option_for_slot(slot)
        if option and depart + i <= DMX_SLOTS:
            patch[depart + i] = option
    vitesse = depart + 8 * max(1, len(getattr(window, "_bank_pages", None) or [1]))
    if vitesse <= DMX_SLOTS:
        patch[vitesse] = CIBLE_VITESSE
    return patch


def dmx_to_level(value):
    """0-255 (DMX) -> 0-100 (niveau MyStrow)."""
    return int(round(max(0, min(255, int(value))) * 100 / 255))


def level_to_velocity(level):
    """0-100 -> 0-127, l'unite attendue par `on_midi_fader`.

    Passer par la meme porte que le MIDI vaut bien cet aller-retour, mais il
    faut l'ARRONDIR AU-DESSUS : `on_midi_fader` reconvertit avec un `int()`,
    qui tronque. Avec un arrondi au plus proche, le niveau 1 donnait une
    velocite de 1, retronquee en 0 — le premier point de chaque fader etait
    perdu, et un pupitre a 1 % laissait le projecteur eteint.
    """
    borne = max(0, min(100, int(level)))
    return -(-borne * 127 // 100)      # ceil(borne * 127 / 100)


# ── liaison ─────────────────────────────────────────────────────────────────

class DmxInLink(QObject):
    """Applique le DMX entrant aux cibles patchees, page affichee ou non."""

    # (recoit, message d'etat pret a afficher)
    status_changed = Signal(bool, str)

    def __init__(self, window=None):
        # `window` sert de parent Qt quand c'en est un — mais les tests passent
        # une fenetre factice, et QObject refuserait un parent non-QObject.
        super().__init__(window if isinstance(window, QObject) else None)
        self._window = window
        self.receiver = ArtNetReceiver()

        self.enabled = False
        self.port = DEFAULT_PORT
        self.universe = DEFAULT_UNIVERSE
        # Patch d'usine, remplace par celui du disque des qu'il y en a un — y
        # compris un patch VIDE : « Tout effacer » doit tenir apres fermeture.
        self.patch = default_patch()      # canal (1-512) -> cible

        self._last_counter = -1
        self._last_raw = {}        # canal -> derniere valeur brute obeie
        self._last_status = None

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)

    # ── patch ───────────────────────────────────────────────────────────────

    def set_target(self, canal, option):
        """Patche (ou depatche, avec une cible vide) un canal DMX."""
        try:
            canal = int(canal)
        except (TypeError, ValueError):
            return self.patch
        if not (1 <= canal <= DMX_SLOTS):
            return self.patch
        option = str(option or "").strip().upper()
        if is_cible(option):
            self.patch[canal] = option
        else:
            self.patch.pop(canal, None)
        self._reset_state()
        return self.patch

    def clear_patch(self):
        self.patch = {}
        self._reset_state()
        return self.patch

    def reset_patch(self):
        """Revient au patch d'usine (canal N -> MEM N)."""
        self.patch = default_patch()
        self._reset_state()
        return self.patch

    def target_for(self, canal):
        return self.patch.get(int(canal), CIBLE_AUCUNE)

    def frame(self):
        """Derniere trame recue sur l'univers ecoute, ou None."""
        _counter, frame = self.receiver.snapshot(self.universe)
        return frame

    def visible_fader_for(self, option):
        """Index du fader de la page AFFICHEE qui porte cette cible, ou None.

        La vitesse des effets est un cas a part : le fader 9 n'appartient a
        aucune page, il est toujours la.
        """
        if option == CIBLE_VITESSE:
            return FADER_VITESSE
        try:
            slots = list(getattr(self._window, "_fader_map", None) or [])
        except Exception:
            return None
        for i, slot in enumerate(slots[:8]):
            if option_for_slot(slot) == option:
                return i
        return None

    def watched(self):
        """[(canal, cible)] — le patch, canal croissant."""
        for canal in sorted(self.patch):
            yield canal, self.patch[canal]

    # ── persistance ─────────────────────────────────────────────────────────

    def to_config(self):
        return {
            "enabled": bool(self.enabled),
            "port": int(self.port),
            "universe": int(self.universe),
            "patch": [{"channel": c, "slot": self.patch[c]} for c in sorted(self.patch)],
        }

    def from_config(self, cfg):
        if not isinstance(cfg, dict):
            return
        self.enabled = bool(cfg.get("enabled", False))
        try:
            self.port = int(cfg.get("port", DEFAULT_PORT))
        except (TypeError, ValueError):
            self.port = DEFAULT_PORT
        try:
            self.universe = max(0, min(32767, int(cfg.get("universe",
                                                         DEFAULT_UNIVERSE))))
        except (TypeError, ValueError):
            self.universe = DEFAULT_UNIVERSE
        if "patch" in cfg:
            self.patch = normalize_patch(cfg.get("patch"))
        else:
            # Reglage d'avant la table plate : on recupere ce qu'on peut, et a
            # defaut on retombe sur le patch d'usine plutot que sur une table
            # vide — l'utilisateur avait bien configure quelque chose.
            self.patch = patch_from_legacy(cfg, self._window) or default_patch()

    def load(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.from_config(json.load(f))
        except Exception:
            pass
        return self

    def save(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.to_config(), f, indent=2)
        except Exception:
            pass

    # ── cycle de vie ────────────────────────────────────────────────────────

    def apply(self):
        """Aligne l'ecoute reseau sur la configuration courante.

        L'ecoute tourne des que l'entree est activee, meme sans patch : le
        dialogue en a besoin pour afficher les niveaux en direct, qui sont la
        seule facon de reconnaitre le canal d'un fader.
        """
        if self.enabled:
            self.receiver.start(self.port, ignore_ips=self._local_ips())
            self._reset_state()
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self.receiver.stop()
        self._emit_status()

    def stop(self):
        self._timer.stop()
        self.receiver.stop()

    def _reset_state(self):
        """Repart d'une page blanche : la prochaine trame redevient une simple
        reference (cf. decision n°1 en tete de module). Indispensable apres tout
        changement de patch, puisque les canaux ne designent plus les memes
        cibles."""
        self._last_counter = -1
        self._last_raw.clear()

    @staticmethod
    def _local_ips():
        """IPs de ce PC — pour ne jamais rejouer notre propre sortie (larsen)."""
        try:
            from node_connection import _get_all_local_ips
            return _get_all_local_ips()
        except Exception:
            return set()

    # ── boucle ──────────────────────────────────────────────────────────────

    def _tick(self):
        counter, frame = self.receiver.snapshot(self.universe)
        self._emit_status()
        if frame is None:
            return

        if counter == self._last_counter:
            return
        premiere = self._last_counter < 0
        self._last_counter = counter

        for canal, cible in self.watched():
            if not (1 <= canal <= DMX_SLOTS):
                continue
            brut = frame[canal - 1]
            if premiere:
                # Trame de reference : on retient, on n'obeit pas.
                self._last_raw[canal] = brut
                continue
            if self._last_raw.get(canal) == brut:
                continue          # cf. decision n°3
            self._last_raw[canal] = brut
            self._route(cible, brut)

    # ── application ─────────────────────────────────────────────────────────

    def _route(self, cible, brut):
        """Envoie un canal sur sa cible, par le chemin qui lui correspond."""
        index = self.visible_fader_for(cible)
        niveau = dmx_to_level(brut)
        col = mem_col_for(cible)
        if col is not None:
            # Les memoires ont leur porte a elles, page affichee ou non :
            # `apply_memory_level` tient le niveau ET remet la surface d'accord.
            # Repasser par `on_midi_fader` quand la colonne est visible ferait
            # deux writers pour la meme memoire.
            self._appeler("apply_memory_level", col, niveau)
        elif index is not None:
            self._appeler("on_midi_fader", index, level_to_velocity(niveau))
        else:
            slot = slot_for_option(cible)
            if slot is not None:
                self._appeler("apply_slot_level_offpage", slot, niveau)

    def _appeler(self, methode, *args):
        """Appelle la fenetre sans jamais laisser une exception tuer le tick.

        La liaison tourne 25 fois par seconde : un timer Qt qui leve arrete la
        restitution pour de bon (cf. les gardes des autres timers).
        """
        window = self._window
        if window is None:
            return
        try:
            getattr(window, methode)(*args)
        except Exception:
            pass

    # ── etat ────────────────────────────────────────────────────────────────

    def status(self):
        """(recoit, message) — la phrase que le dialogue affiche."""
        if not self.enabled:
            return False, tr("dmxin_status_off")
        if self.receiver.error:
            return False, tr("dmxin_status_error", port=self.port,
                             err=self.receiver.error)
        if not self.receiver.is_receiving():
            return False, tr("dmxin_status_wait", port=self.port)
        vus = self.receiver.universes_seen()
        if self.universe not in vus:
            return False, tr("dmxin_status_wrong_uni",
                             uni=self.universe,
                             seen=", ".join(str(u) for u in vus) or "?")
        _counter, frame = self.receiver.snapshot(self.universe)
        actifs = sum(1 for v in (frame or b"") if v)
        sources = self.receiver.sources()
        return True, tr("dmxin_status_rx", uni=self.universe, n=actifs,
                        ip=", ".join(sources) or "?")

    def _emit_status(self):
        etat = self.status()
        if etat != self._last_status:
            self._last_status = etat
            self.status_changed.emit(etat[0], etat[1])

    def other_universe_seen(self):
        """Univers sur lequel des donnees arrivent alors qu'on ecoute ailleurs.

        Remplace le reglage d'univers : plutot qu'un champ a comprendre, on
        constate et on propose de basculer.
        """
        if not self.enabled or not self.receiver.is_receiving():
            return None
        vus = self.receiver.universes_seen()
        if self.universe in vus:
            return None
        return vus[0] if vus else None

    def emitted_universes(self):
        """Univers sur lesquels MyStrow emet REELLEMENT.

        Un port du Node bascule en entree dans l'aiguillage des sorties
        (OUTPUT_INPUT) n'en fait pas partie : on s'y tait expres, donc il n'y a
        aucun conflit a l'ecouter.
        """
        window = self._window
        dmx = getattr(window, "dmx", None) if window is not None else None
        if dmx is None or getattr(dmx, "transport", "") != "artnet":
            return []
        try:
            base = int(getattr(dmx, "universe", 0))
            mapping = list(getattr(dmx, "output_map", None) or [])
        except (TypeError, ValueError):
            return []
        if not mapping:
            return [base + n for n in range(4)]
        return [base + n for n, v in enumerate(mapping) if v != OUTPUT_INPUT]

    def echo_risk(self):
        """L'univers ecoute est-il un de ceux que MyStrow EMET ?

        C'est la boucle de retour : notre propre sortie revient en entree et les
        faders se mettent a osciller. Le filtre par IP couvre le cas normal,
        mais pas un Node qui rediffuse ce qu'on lui envoie. Avec l'univers 5 par
        defaut ca n'arrive plus, mais l'utilisateur peut avoir bascule.
        """
        return self.universe in self.emitted_universes()


# ── dialogue de reglage ─────────────────────────────────────────────────────

class _CibleDelegate(QStyledItemDelegate):
    """Editeur de la colonne « Tranche » : un combo, cree au clic.

    Un combo par ligne serait 512 widgets portant chacun 117 entrees : plusieurs
    secondes a l'ouverture et autant de memoire pour rien. Le delegue n'en cree
    qu'un, celui de la cellule qu'on edite.
    """

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setMaxVisibleItems(18)
        combo.addItem(cible_label(CIBLE_AUCUNE), CIBLE_AUCUNE)
        combo.insertSeparator(combo.count())
        for g in GROUPES:
            combo.addItem(cible_label(g), g)
        combo.insertSeparator(combo.count())
        for i in range(1, MEM_MAX + 1):
            combo.addItem(f"MEM {i}", f"MEM {i}")
        combo.insertSeparator(combo.count())
        for i in range(1, FX_MAX + 1):
            combo.addItem(f"FX {i}", f"FX {i}")
        combo.insertSeparator(combo.count())
        combo.addItem(cible_label(CIBLE_PLAY), CIBLE_PLAY)
        combo.addItem(cible_label(CIBLE_VITESSE), CIBLE_VITESSE)
        return combo

    def setEditorData(self, editor, index):
        courant = index.data(Qt.UserRole) or CIBLE_AUCUNE
        pos = editor.findData(courant)
        editor.setCurrentIndex(max(0, pos))
        # Derouler tout de suite : un clic dans la colonne = la liste ouverte,
        # sinon il en faut deux. Differe, sinon le popup s'ouvre avant que
        # l'editeur ne soit place et se dessine au mauvais endroit.
        QTimer.singleShot(0, editor.showPopup)

    def setModelData(self, editor, model, index):
        cible = editor.currentData() or CIBLE_AUCUNE
        model.setData(index, cible, Qt.UserRole)
        model.setData(index, cible_label(cible), Qt.DisplayRole)


class DmxInDialog(QDialog):
    """Reglage de l'entree DMX : une table de 512 canaux, et c'est tout."""

    def __init__(self, window, link: DmxInLink):
        super().__init__(window)
        self._window = window
        self._link = link
        self._silence = True        # remplissage en cours : ne pas enregistrer
        self._valeurs = {}          # ligne -> derniere valeur brute affichee
        self._chauds = set()        # lignes qui viennent de bouger (en cyan)

        self.setWindowTitle(tr("dmxin_title"))
        self.setMinimumSize(620, 660)
        self.setStyleSheet(STYLE_DIALOGUE)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        titre = QLabel(tr("dmxin_header"))
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        titre.setFont(f)
        root.addWidget(titre)

        intro = QLabel(tr("dmxin_intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#888; font-size:11px;")
        root.addWidget(intro)

        self._actif = QCheckBox(tr("dmxin_enable"))
        self._actif.setChecked(link.enabled)
        self._actif.toggled.connect(self._on_toggle)
        root.addWidget(self._actif)

        # ── Branchement : la seule chose a faire avant de patcher ──────────
        # Le bouton mene a l'autre fenetre plutot que de decrire le chemin de
        # menu : c'est LE reglage qu'on oublie, et personne ne lit un itineraire.
        branchement = QHBoxLayout()
        branchement.setSpacing(8)
        lbl = QLabel(tr("dmxin_branchement"))
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#888; font-size:11px;")
        branchement.addWidget(lbl, 1)
        self._btn_sortie = QPushButton(tr("dmxin_open_output"))
        self._btn_sortie.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_sortie.clicked.connect(self._ouvrir_sortie_dmx)
        self._btn_sortie.setVisible(hasattr(window, "open_node_connection"))
        branchement.addWidget(self._btn_sortie)
        root.addLayout(branchement)

        # ── Etat en direct ──────────────────────────────────────────────────
        self._etat = QLabel("")
        self._etat.setWordWrap(True)
        self._etat.setStyleSheet("color:#888; font-size:11px;")
        root.addWidget(self._etat)

        # Une entree DMX peut etre parfaitement patchee et ne rien recevoir pour
        # deux raisons qu'aucun libelle de cette fenetre ne peut deviner : le
        # port du boitier reste en SORTIE, ou le pare-feu Windows jette l'UDP
        # entrant. Sans cette ligne, l'utilisateur fixe un ecran muet.
        alerte_ligne = QHBoxLayout()
        alerte_ligne.setSpacing(8)
        self._alerte = QLabel("")
        self._alerte.setWordWrap(True)
        self._alerte.setStyleSheet("color:#ffb84d; font-size:11px;")
        alerte_ligne.addWidget(self._alerte, 1)
        self._btn_uni = QPushButton("")
        self._btn_uni.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_uni.clicked.connect(self._basculer_univers)
        self._btn_uni.setVisible(False)
        alerte_ligne.addWidget(self._btn_uni)
        root.addLayout(alerte_ligne)

        root.addWidget(self._separateur())

        aide = QLabel(tr("dmxin_help"))
        aide.setWordWrap(True)
        aide.setStyleSheet("color:#00d4ff; font-size:11px;")
        root.addWidget(aide)

        root.addWidget(self._table())

        # ── Pied ────────────────────────────────────────────────────────────
        pied = QHBoxLayout()
        self._compte = QLabel("")
        self._compte.setStyleSheet("color:#888; font-size:11px;")
        pied.addWidget(self._compte)
        pied.addStretch(1)
        defaut = QPushButton(tr("dmxin_default"))
        defaut.setCursor(QCursor(Qt.PointingHandCursor))
        defaut.setToolTip(tr("dmxin_default_tip"))
        defaut.clicked.connect(self._patch_defaut)
        pied.addWidget(defaut)
        vider = QPushButton(tr("dmxin_clear"))
        vider.setCursor(QCursor(Qt.PointingHandCursor))
        vider.clicked.connect(self._vider)
        pied.addWidget(vider)
        fermer = QPushButton(tr("dmxin_close"))
        fermer.setCursor(QCursor(Qt.PointingHandCursor))
        fermer.clicked.connect(self.accept)
        pied.addWidget(fermer)
        root.addLayout(pied)

        # L'ecoute doit tourner pendant le reglage : sans trame, pas de niveaux
        # en direct, donc aucun moyen de reconnaitre le canal d'un fader.
        link.apply()

        self._remplir_cibles()
        self._silence = False
        self._rafraichir()
        self._aller_au_premier_canal()

        self._refresh = QTimer(self)
        self._refresh.setInterval(300)
        self._refresh.timeout.connect(self._rafraichir)
        self._refresh.start()

    # ── construction ────────────────────────────────────────────────────────

    def _table(self):
        table = QTableWidget(DMX_SLOTS, 2)
        table.setHorizontalHeaderLabels([tr("dmxin_col_channel"),
                                         tr("dmxin_col_tranche")])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        # Un seul clic ouvre le combo : chercher le canal 137 dans 512 lignes
        # est deja assez long sans avoir a double-cliquer.
        table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        table.setItemDelegateForColumn(1, _CibleDelegate(table))
        tetes = table.horizontalHeader()
        tetes.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tetes.setSectionResizeMode(1, QHeaderView.Stretch)

        fige = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        for ligne in range(DMX_SLOTS):
            canal = QTableWidgetItem(str(ligne + 1))
            canal.setFlags(fige)
            canal.setForeground(QColor("#999"))
            table.setItem(ligne, 0, canal)

            cible = QTableWidgetItem("")
            cible.setFlags(fige | Qt.ItemIsEditable)
            table.setItem(ligne, 1, cible)

        table.itemChanged.connect(self._on_cible_changee)
        self._table_widget = table
        return table

    def _petit_titre(self, texte):
        lbl = QLabel(texte)
        lbl.setStyleSheet("color:#aaa; font-size:11px; font-weight:bold;")
        return lbl

    def _separateur(self):
        trait = QFrame()
        trait.setFrameShape(QFrame.HLine)
        trait.setStyleSheet("color:#2a2a2a;")
        return trait

    # ── patch ───────────────────────────────────────────────────────────────

    def _remplir_cibles(self):
        """Recopie le patch de la liaison dans la table."""
        etait = self._silence
        self._silence = True
        for ligne in range(DMX_SLOTS):
            cible = self._link.target_for(ligne + 1)
            item = self._table_widget.item(ligne, 1)
            item.setData(Qt.UserRole, cible)
            item.setText(cible_label(cible))
            item.setForeground(QColor("#eee" if cible else "#555"))
        self._silence = etait

    def _on_cible_changee(self, item):
        if self._silence or item.column() != 1:
            return
        canal = item.row() + 1
        cible = item.data(Qt.UserRole) or CIBLE_AUCUNE
        item.setForeground(QColor("#eee" if cible else "#555"))
        self._link.set_target(canal, cible)
        self._link.save()
        self._maj_compte()

    def _vider(self):
        self._link.clear_patch()
        self._link.save()
        self._remplir_cibles()
        self._maj_compte()

    def _patch_defaut(self):
        """Remet canal N -> MEM N. Ecrase ce qui est la, sans confirmation :
        la table entiere est sous les yeux, et « Tout effacer » est a cote."""
        self._link.reset_patch()
        self._link.save()
        self._remplir_cibles()
        self._maj_compte()

    def _aller_au_premier_canal(self):
        """Ouvre la table sur le premier canal patche plutot que sur le canal 1."""
        if not self._link.patch:
            return
        ligne = min(self._link.patch) - 1
        self._table_widget.setCurrentCell(ligne, 1)
        self._table_widget.scrollToItem(self._table_widget.item(ligne, 1),
                                        QAbstractItemView.PositionAtCenter)

    def _maj_compte(self):
        self._compte.setText(tr("dmxin_count", n=len(self._link.patch)))

    # ── reglages ────────────────────────────────────────────────────────────

    def _on_toggle(self, coche):
        self._link.enabled = bool(coche)
        self._appliquer()

    def _ouvrir_sortie_dmx(self):
        """Ouvre la fenetre « Sortie DMX » — c'est la qu'un port se bascule en
        entree, et sans ca rien n'arrivera jamais ici."""
        try:
            self._window.open_node_connection()
        except Exception:
            pass

    def _basculer_univers(self):
        uni = self._btn_uni.property("univers")
        if uni is None:
            return
        self._link.universe = int(uni)
        self._appliquer()

    def _appliquer(self):
        self._link.apply()
        self._link.save()
        self._rafraichir()

    # ── affichage ───────────────────────────────────────────────────────────

    def _rafraichir(self, *_):
        link = self._link

        self._maj_compte()

        recoit, message = link.status()
        puce = "●" if recoit else "○"
        couleur = "#5f5" if recoit else "#888"
        self._etat.setText(f"{puce}  {message}")
        self._etat.setStyleSheet(f"color:{couleur}; font-size:11px;")

        alertes = []
        if link.enabled and not link.receiver.is_receiving():
            alertes.append(tr("dmxin_hint_no_data"))
        if link.echo_risk():
            alertes.append(tr("dmxin_warn_echo"))
        self._alerte.setText("\n".join(alertes))
        self._alerte.setVisible(bool(alertes))

        autre = link.other_universe_seen()
        self._btn_uni.setVisible(autre is not None)
        if autre is not None:
            self._btn_uni.setProperty("univers", int(autre))
            self._btn_uni.setText(tr("dmxin_listen", uni=int(autre)))

        self._marquer_ce_qui_bouge(link.frame())

    def _marquer_ce_qui_bouge(self, frame):
        """Passe en cyan le NUMERO des canaux qui bougent, puis les regrise.

        C'est tout ce qui reste de l'apprentissage, et ca suffit : on bouge un
        fader du pupitre, son numero s'allume dans la table. Pas de colonne de
        valeurs a lire, pas de mode a lancer. On ne repeint que ce qui change,
        sinon 512 lignes clignoteraient trois fois par seconde.
        """
        table = self._table_widget
        chauds = set()
        for ligne in range(DMX_SLOTS):
            brut = None if frame is None else frame[ligne]
            ancien = self._valeurs.get(ligne, _MANQUANT)
            if brut == ancien:
                continue
            if ancien is not _MANQUANT:
                chauds.add(ligne)          # a bouge depuis le dernier passage
            self._valeurs[ligne] = brut
        for ligne in self._chauds - chauds:
            table.item(ligne, 0).setForeground(QColor("#999"))
        for ligne in chauds - self._chauds:
            table.item(ligne, 0).setForeground(QColor("#00d4ff"))
        self._chauds = chauds

    def done(self, code):
        try:
            self._refresh.stop()
        except Exception:
            pass
        try:
            self._link.save()
            self._link.apply()
        except Exception:
            pass
        super().done(code)
