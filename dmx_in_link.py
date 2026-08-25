"""
dmx_in_link.py — Ce que MyStrow FAIT du DMX entrant, et son reglage.

artnet_input.py recoit les trames ; ce module decide de l'effet. Meme partage
que gamepad_client.py / gamepad_link.py, et pour la meme raison : toute la
logique se teste sans reseau ni pupitre branche.

DEUX MODES, PARCE QUE DEUX BESOINS
-----------------------------------
**Patch** (par defaut) — MyStrow se patche comme une fixture : UNE adresse de
depart, et les canaux se deroulent dans l'ordre des tranches, PAGE PAR PAGE.
Le layout AKAI compte 8 colonnes par page et 20 pages navigables (◀ ▶) :

    adresse +   0 .. +  7   ->  page 1, tranches 1 a 8
    adresse +   8 .. + 15   ->  page 2, tranches 1 a 8
    ...
    adresse + 152 .. +159   ->  page 20, tranches 1 a 8
    adresse + 160           ->  fader 9 (vitesse des effets)

Le fader 9 est en DERNIER, et pas en neuvieme position, precisement pour que
les pages tombent sur des multiples de 8 : c'est ce qui rend l'adressage
calculable de tete (page N = adresse + (N-1) x 8). Rien a regler, mais l'ordre
est impose.

**Libre** — une table « ce canal DMX -> cette tranche », dans n'importe quel
ordre. Les 12 faders d'une console peuvent taper sur 12 tranches prises
n'importe ou dans les 20 pages. C'est le mode de qui a deja son pupitre range
a sa facon et ne veut pas s'aligner sur notre numerotation.

Les deux modes partagent TOUT le reste : reception, apprentissage du canal,
routage, LTP/HTP, anti-larsen, diagnostic. Seule change la facon de repondre a
la question « quel canal pilote quoi ».

UN PUPITRE PILOTE LES 20 PAGES A LA FOIS
-----------------------------------------
C'est tout l'interet : une seule page est a l'ecran, mais la console les
adresse toutes en meme temps. C'est possible parce que la CIBLE d'une tranche
(un groupe, une colonne FX, le volume) ne depend pas de la page ; seuls les
widgets — le fader affiche, le pad actif — sont lies a la colonne visible.
C'est exactement la philosophie de `_sync_controls_to_state` : le rig est la
source de verite, l'AKAI n'en est qu'une vue.

    - tranche de la page AFFICHEE  -> `on_midi_fader`, chemin inchange
    - tranche d'une AUTRE page     -> `MainWindow.apply_slot_level_offpage`

DEUX LIMITES ASSUMEES, DANS LES DEUX MODES
-------------------------------------------
- Les tranches **MEM et POS d'une autre page** ne sont pas pilotables : le mix
  des memoires est indexe par colonne VISIBLE (`active_memory_pads`, puis
  `_fader_to_mem_col` qui relit `_fader_map`), et le fader de position porte
  son axe dans le slot de sa colonne. Hors page, ces deux-la n'ont pas de cible
  definie — mieux vaut ne rien faire que piloter la mauvaise memoire. Sur la
  page affichee, elles marchent normalement.
- Le **HTP ne s'applique qu'a la page affichee**, faute de fader a l'ecran ou
  lire le niveau de l'autre source. Hors page, le pupitre a toujours la main.

TROIS DECISIONS QUI NE SONT PAS EVIDENTES
------------------------------------------
1. **La premiere trame ne pilote RIEN.** Elle sert de reference. Sans ca,
   cocher « activer » pendant un show enverrait d'un coup tout le parc sur les
   valeurs du pupitre — c'est-a-dire au NOIR si ses faders sont en bas. On
   attend donc qu'un canal BOUGE pour lui obeir : le premier geste sur le
   pupitre prend la main, et la case a cocher ne casse jamais un show en cours.

2. **LTP par defaut.** Quand le pupitre et l'AKAI se disputent une tranche, le
   dernier qui bouge gagne : c'est ce que fait n'importe quelle console, et
   c'est le seul comportement ou pousser un fader a un effet visible a coup
   sur. Le HTP reste disponible pour qui melange deux pupitres.

3. **On n'obeit qu'aux canaux qui CHANGENT.** Un pupitre emet 40 trames de 512
   octets par seconde, en continu, meme a l'arret. Reappliquer chaque canal a
   chaque trame ecraserait en permanence l'AKAI et l'interface, et le LTP
   n'aurait plus aucun sens : le pupitre gagnerait toujours, 40 fois par
   seconde.
"""

import json
import os

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
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

MODE_PATCH = "patch"
MODE_LIBRE = "libre"

MERGE_LTP = "ltp"
MERGE_HTP = "htp"

# Le layout AKAI : 8 colonnes par page, 20 pages (cf. _N_BANK_PAGES).
TRANCHES_PAR_PAGE = 8
PAGES_DEFAUT = 20

# Cibles possibles d'une assignation.
CIBLE_TRANCHE = "tranche"
CIBLE_VITESSE = "speed"

# Index du fader 9 (vitesse des effets) dans MainWindow.faders.
FADER_VITESSE = 8

# Variation minimale pour qu'un canal soit considere comme « bouge » pendant
# l'apprentissage. Un pupitre analogique bruite de ±2 en permanence : sans ce
# plancher, l'apprentissage attraperait un canal au hasard.
LEARN_DELTA = 12


# ── fonctions pures (testables sans Qt) ─────────────────────────────────────

def nb_pages(window):
    """Nombre de pages de layout. Tolerant : une fenetre factice ou un layout
    pas encore construit retombe sur la valeur nominale."""
    try:
        pages = getattr(window, "_bank_pages", None)
        if pages:
            return max(1, len(pages))
    except Exception:
        pass
    return PAGES_DEFAUT


def patch_size(pages):
    """Nombre de canaux occupes par le mode Patch : 8 par page, plus la vitesse."""
    return max(1, int(pages)) * TRANCHES_PAR_PAGE + 1


def max_start(pages):
    """Derniere adresse de depart ou tout le patch tient dans l'univers."""
    return max(1, DMX_SLOTS - patch_size(pages) + 1)


def clamp_start(value, pages=PAGES_DEFAUT):
    try:
        return max(1, min(max_start(pages), int(value)))
    except (TypeError, ValueError):
        return 1


def offset_for(page, tranche):
    """Decalage d'une tranche depuis l'adresse de depart (page et tranche 0-based)."""
    return int(page) * TRANCHES_PAR_PAGE + int(tranche)


def page_tranche_for(offset, pages):
    """Inverse d'`offset_for`. Renvoie (page, tranche), ou None pour le fader
    de vitesse, qui occupe le dernier canal du patch."""
    offset = int(offset)
    if offset >= int(pages) * TRANCHES_PAR_PAGE:
        return None
    return divmod(offset, TRANCHES_PAR_PAGE)


def normalize_assignments(raw, pages=PAGES_DEFAUT):
    """Nettoie une table d'assignations venue du disque.

    Tolerant a dessein : une config abimee ne doit pas empecher l'entree DMX de
    fonctionner, ni faire planter l'ouverture du dialogue. Les entrees
    illisibles sont jetees une par une, et un canal ne peut piloter qu'UNE
    cible — deux cibles sur le meme canal, c'est le doublon garanti a l'usage.
    """
    out = []
    vus = set()
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            canal = int(item.get("channel", 0))
        except (TypeError, ValueError):
            continue
        if not (1 <= canal <= DMX_SLOTS) or canal in vus:
            continue
        if item.get("type") == CIBLE_VITESSE:
            out.append({"channel": canal, "type": CIBLE_VITESSE})
            vus.add(canal)
            continue
        try:
            page = int(item.get("page", -1))
            tranche = int(item.get("tranche", -1))
        except (TypeError, ValueError):
            continue
        if not (0 <= page < int(pages) and 0 <= tranche < TRANCHES_PAR_PAGE):
            continue
        out.append({"channel": canal, "type": CIBLE_TRANCHE,
                    "page": page, "tranche": tranche})
        vus.add(canal)
    return out


def merge_level(mode, console, local):
    """Niveau retenu quand le pupitre et une source locale se disputent une tranche."""
    if mode == MERGE_HTP:
        return max(int(console), int(local))
    return int(console)


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


def page_slots(window, page):
    """Les 8 slots de la page demandee, ou [] si elle n'existe pas."""
    try:
        pages = list(getattr(window, "_bank_pages", None) or [])
        if 0 <= int(page) < len(pages):
            return list(pages[int(page)] or [])
    except Exception:
        pass
    return []


def tranche_labels(window, page):
    """Les 8 libelles de la page (« A », « MEM 1 »…).

    Ils viennent du layout : c'est ce qui permet a l'utilisateur de savoir ce
    que fait reellement le fader 5 de son pupitre. Tolerant — un layout absent
    retombe sur des numeros plutot que de vider la fenetre de reglage.
    """
    slots = page_slots(window, page)
    libelles = []
    for i in range(TRANCHES_PAR_PAGE):
        slot = slots[i] if i < len(slots) else None
        libelle = (slot or {}).get("label") if isinstance(slot, dict) else None
        libelles.append(str(libelle) if libelle else str(i + 1))
    return libelles


def assignment_label(window, assign):
    """Libelle lisible d'une assignation (« Page 4 · Tranche 2 — MEM 2 »)."""
    if assign.get("type") == CIBLE_VITESSE:
        return tr("dmxin_tranche_speed")
    page = int(assign.get("page", 0))
    tranche = int(assign.get("tranche", 0))
    libelles = tranche_labels(window, page)
    etiquette = libelles[tranche] if tranche < len(libelles) else str(tranche + 1)
    return tr("dmxin_assign_label", p=page + 1, n=tranche + 1, label=etiquette)


def find_moved_channel(baseline, frame, delta=LEARN_DELTA):
    """Canal (1-512) qui a le plus bouge depuis la reference, ou None.

    On prend le MAXIMUM et pas le premier depassement : bouger un fader d'un
    pupitre remue souvent plusieurs canaux a la fois (diaphonie analogique,
    canal de dimmer master qui suit). Le bon canal est celui qui bouge le plus.
    """
    if not baseline or not frame:
        return None
    best_ch, best_delta = None, delta - 1
    for i in range(min(len(baseline), len(frame), DMX_SLOTS)):
        ecart = abs(int(frame[i]) - int(baseline[i]))
        if ecart > best_delta:
            best_ch, best_delta = i + 1, ecart
    return best_ch


# ── liaison ─────────────────────────────────────────────────────────────────

class DmxInLink(QObject):
    """Applique le DMX entrant aux tranches de l'AKAI, sur toutes les pages."""

    # (recoit, message d'etat pret a afficher)
    status_changed = Signal(bool, str)
    # Canal detecte pendant un apprentissage (1-512). En mode Patch, la liaison
    # en fait deja l'adresse de depart ; le dialogue n'a qu'a suivre.
    channel_learned = Signal(int)

    def __init__(self, window=None):
        # `window` sert de parent Qt quand c'en est un — mais les tests passent
        # une fenetre factice, et QObject refuserait un parent non-QObject.
        super().__init__(window if isinstance(window, QObject) else None)
        self._window = window
        self.receiver = ArtNetReceiver()

        self.enabled = False
        self.port = DEFAULT_PORT
        self.universe = 0
        self.mode = MODE_PATCH
        self.start_channel = 1
        self.assignments = []
        self.merge = MERGE_LTP

        # Vrai pendant un apprentissage : on ne pilote rien, sinon designer un
        # canal ferait bouger le parc en plein reglage.
        self.suspendu = False

        self._last_counter = -1
        self._last_raw = {}        # canal -> derniere valeur brute obeie
        self._applied = {}         # index de fader visible -> niveau ECRIT par nous
        self._local = {}           # index de fader visible -> niveau de l'autre source
        self._learn_baseline = None
        self._last_status = None

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)

    # ── patch ───────────────────────────────────────────────────────────────

    @property
    def pages(self):
        return nb_pages(self._window)

    @property
    def patch_size(self):
        return patch_size(self.pages)

    @property
    def last_channel(self):
        return self.start_channel + self.patch_size - 1

    def channel_for(self, page, tranche):
        """Canal DMX (1-512) qui pilote cette tranche, en mode Patch."""
        return self.start_channel + offset_for(page, tranche)

    def speed_channel(self):
        """Canal du fader 9 en mode Patch — le dernier du patch."""
        return self.start_channel + self.pages * TRANCHES_PAR_PAGE

    def active_page(self):
        try:
            return int(getattr(self._window, "_bank_page_idx", 0) or 0)
        except Exception:
            return 0

    def patch_rows(self, page):
        """[(canal, libelle, valeur brute ou None)] pour les 8 tranches d'une page."""
        libelles = tranche_labels(self._window, page)
        _counter, frame = self.receiver.snapshot(self.universe)

        def brut_de(canal):
            if frame is None or not (1 <= canal <= DMX_SLOTS):
                return None
            return frame[canal - 1]

        lignes = [(self.channel_for(page, t), libelles[t],
                   brut_de(self.channel_for(page, t)))
                  for t in range(TRANCHES_PAR_PAGE)]
        canal = self.speed_channel()
        lignes.append((canal, tr("dmxin_tranche_speed"), brut_de(canal)))
        return lignes

    def assignment_rows(self):
        """[(canal, libelle, valeur brute ou None)] du mode Libre, canal croissant."""
        _counter, frame = self.receiver.snapshot(self.universe)
        lignes = []
        for assign in sorted(self.assignments, key=lambda a: a["channel"]):
            canal = assign["channel"]
            brut = frame[canal - 1] if frame is not None else None
            lignes.append((canal, assignment_label(self._window, assign), brut))
        return lignes

    # ── ce qu'on surveille dans la trame ────────────────────────────────────

    def watched(self):
        """[(canal, cible, page, tranche)] — le mapping effectif du mode courant.

        C'est le SEUL endroit qui differencie les deux modes : tout ce qui suit
        (detection de changement, routage, melange) est commun. Ajouter un
        troisieme mode un jour ne demanderait que d'etendre cette fonction.
        """
        if self.mode == MODE_LIBRE:
            for assign in self.assignments:
                if assign.get("type") == CIBLE_VITESSE:
                    yield assign["channel"], CIBLE_VITESSE, 0, 0
                else:
                    yield (assign["channel"], CIBLE_TRANCHE,
                           assign["page"], assign["tranche"])
            return
        pages = self.pages
        for offset in range(patch_size(pages)):
            canal = self.start_channel + offset
            cible = page_tranche_for(offset, pages)
            if cible is None:
                yield canal, CIBLE_VITESSE, 0, 0
            else:
                yield canal, CIBLE_TRANCHE, cible[0], cible[1]

    # ── persistance ─────────────────────────────────────────────────────────

    def to_config(self):
        return {
            "enabled": bool(self.enabled),
            "port": int(self.port),
            "universe": int(self.universe),
            "mode": self.mode if self.mode in (MODE_PATCH, MODE_LIBRE) else MODE_PATCH,
            "start_channel": int(self.start_channel),
            "assignments": list(self.assignments),
            "merge": self.merge if self.merge in (MERGE_LTP, MERGE_HTP) else MERGE_LTP,
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
            self.universe = max(0, min(32767, int(cfg.get("universe", 0))))
        except (TypeError, ValueError):
            self.universe = 0
        mode = cfg.get("mode", MODE_PATCH)
        self.mode = mode if mode in (MODE_PATCH, MODE_LIBRE) else MODE_PATCH
        self.start_channel = clamp_start(cfg.get("start_channel", 1), self.pages)
        self.assignments = normalize_assignments(cfg.get("assignments"), self.pages)
        merge = cfg.get("merge", MERGE_LTP)
        self.merge = merge if merge in (MERGE_LTP, MERGE_HTP) else MERGE_LTP

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

        L'ecoute tourne des que l'entree est activee, meme sans assignation :
        le dialogue en a besoin pour l'apprentissage et pour dire a
        l'utilisateur si quelque chose arrive.
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
        changement de mapping — adresse, mode, assignations — puisque les canaux
        ne designent plus les memes tranches."""
        self._last_counter = -1
        self._last_raw.clear()
        self._applied.clear()
        self._local.clear()

    @staticmethod
    def _local_ips():
        """IPs de ce PC — pour ne jamais rejouer notre propre sortie (larsen)."""
        try:
            from node_connection import _get_all_local_ips
            return _get_all_local_ips()
        except Exception:
            return set()

    # ── mapping ─────────────────────────────────────────────────────────────

    def set_mode(self, mode):
        nouveau = mode if mode in (MODE_PATCH, MODE_LIBRE) else MODE_PATCH
        if nouveau != self.mode:
            self.mode = nouveau
            self._reset_state()
        return self.mode

    def set_start_channel(self, value):
        """Change l'adresse de depart et oublie l'etat : les canaux precedents
        ne designent plus les memes tranches."""
        nouvelle = clamp_start(value, self.pages)
        if nouvelle != self.start_channel:
            self.start_channel = nouvelle
            self._reset_state()
        return self.start_channel

    def add_assignment(self, canal, page=None, tranche=None, vitesse=False):
        """Ajoute (ou remplace) l'assignation d'un canal.

        La nouvelle est placee EN TETE : `normalize_assignments` jette les
        doublons de canal, donc c'est l'ancienne qui saute. Reassigner un canal
        deja pris devient un simple remplacement, sans message d'erreur a lire
        ni suppression manuelle prealable.
        """
        if vitesse:
            nouvelle = {"channel": int(canal), "type": CIBLE_VITESSE}
        else:
            nouvelle = {"channel": int(canal), "type": CIBLE_TRANCHE,
                        "page": int(page or 0), "tranche": int(tranche or 0)}
        self.assignments = normalize_assignments(
            [nouvelle] + list(self.assignments), self.pages)
        self._reset_state()
        return self.assignments

    def remove_assignment(self, canal):
        self.assignments = [a for a in self.assignments if a["channel"] != int(canal)]
        self._reset_state()
        return self.assignments

    # ── apprentissage ───────────────────────────────────────────────────────

    def start_learn(self):
        """Memorise l'etat courant ; le prochain canal qui bouge sera annonce.

        En mode Patch, l'utilisateur bouge le fader de SA premiere tranche : le
        canal detecte est donc l'adresse de depart, et tout s'aligne dessus. En
        mode Libre, il bouge le fader qu'il veut assigner, et le dialogue s'en
        sert pour remplir le numero de canal.
        """
        self.suspendu = True
        _counter, frame = self.receiver.snapshot(self.universe)
        self._learn_baseline = frame
        # Sans trame de reference (pupitre pas encore vu), on prend la premiere
        # qui arrive : c'est `_tick` qui s'en charge.

    def cancel_learn(self):
        self._learn_baseline = None
        self.suspendu = False

    def is_learning(self):
        return self.suspendu

    # ── boucle ──────────────────────────────────────────────────────────────

    def _tick(self):
        counter, frame = self.receiver.snapshot(self.universe)
        self._emit_status()
        if frame is None:
            return

        if self.suspendu:
            if self._learn_baseline is None:
                self._learn_baseline = frame
                return
            canal = find_moved_channel(self._learn_baseline, frame)
            if canal is not None:
                self._learn_baseline = None
                self.suspendu = False
                if self.mode == MODE_PATCH:
                    self.set_start_channel(canal)
                    canal = self.start_channel
                self.channel_learned.emit(canal)
            return

        if counter == self._last_counter:
            return
        premiere = self._last_counter < 0
        self._last_counter = counter

        for canal, cible, page, tranche in self.watched():
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
            if cible == CIBLE_VITESSE:
                # Le fader 9 est global : toujours le chemin normal, quelle que
                # soit la page affichee.
                self._apply_visible(FADER_VITESSE, brut)
            else:
                self._route_tranche(page, tranche, brut)

    # ── application ─────────────────────────────────────────────────────────

    def _route_tranche(self, page, tranche, brut):
        if page == self.active_page():
            self._apply_visible(tranche, brut)
        else:
            self._apply_offpage(page, tranche, brut)

    def _apply_visible(self, index, brut):
        """Tranche de la page affichee : chemin MIDI normal, rien de special."""
        console = dmx_to_level(brut)
        niveau = merge_level(self.merge, console, self._current_local(index))
        self._applied[index] = niveau
        window = self._window
        if window is None:
            return
        try:
            window.on_midi_fader(index, level_to_velocity(niveau))
        except Exception:
            pass

    def _apply_offpage(self, page, tranche, brut):
        """Tranche d'une autre page : on applique la cible sans toucher a la
        surface de controle. MEM et POS renvoient False et sont ignorees."""
        window = self._window
        if window is None:
            return
        slots = page_slots(window, page)
        if tranche >= len(slots):
            return
        slot = slots[tranche]
        if not isinstance(slot, dict):
            return
        try:
            window.apply_slot_level_offpage(slot, dmx_to_level(brut))
        except Exception:
            pass

    def _current_local(self, index):
        """Niveau attribue a l'AUTRE source (AKAI, souris, memoire).

        On ne peut pas le lire directement : le fader a l'ecran porte le
        resultat du melange, que nous avons nous-memes ecrit. L'astuce est de
        comparer a ce qu'on a ecrit en dernier — si la valeur affichee a change
        sans nous, c'est que quelqu'un d'autre y a touche.
        """
        window = self._window
        faders = getattr(window, "faders", None) if window is not None else None
        if not faders:
            return 0
        fader = faders.get(index)
        if fader is None:
            return 0
        try:
            courant = int(getattr(fader, "value", 0))
        except (TypeError, ValueError):
            return 0
        if courant != self._applied.get(index):
            self._local[index] = courant
        return self._local.get(index, 0)

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

    def emitted_universes(self):
        """Univers sur lesquels MyStrow emet REELLEMENT.

        Un port du Node bascule en entree dans l'aiguillage des sorties
        (OUTPUT_INPUT) n'en fait pas partie : on s'y tait exprès, donc il n'y a
        aucun conflit a l'ecouter. C'est toute la raison d'etre de ce reglage.
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

    def node_input_universes(self):
        """Univers des ports du Node declares en ENTREE dans l'aiguillage."""
        window = self._window
        dmx = getattr(window, "dmx", None) if window is not None else None
        try:
            return list(dmx.input_universes())
        except Exception:
            return []

    def echo_risk(self):
        """L'univers ecoute est-il un de ceux que MyStrow EMET ?

        C'est la boucle de retour : notre propre sortie revient en entree et
        les faders se mettent a osciller. Le filtre par IP couvre le cas normal,
        mais pas un Node qui rediffuse ce qu'on lui envoie.
        """
        return self.universe in self.emitted_universes()

    def routing_hint(self):
        """Message sur l'aiguillage des sorties, ou None si tout est coherent.

        C'est LE reglage qu'on oublie : tant qu'aucun port du boitier n'est
        declare en entree, MyStrow continue d'emettre sur cet univers-la et se
        bat avec le pupitre. Le dire ici evite de chercher dans l'autre fenetre.
        """
        window = self._window
        dmx = getattr(window, "dmx", None) if window is not None else None
        if dmx is None or getattr(dmx, "transport", "") != "artnet":
            return None            # en USB, l'aiguillage du Node ne s'applique pas
        entrees = self.node_input_universes()
        if not entrees:
            return tr("dmxin_hint_no_input_port")
        if self.universe not in entrees:
            return tr("dmxin_hint_wrong_input_uni",
                      uni=self.universe,
                      seen=", ".join(str(u) for u in entrees))
        return None


# ── dialogue de reglage ─────────────────────────────────────────────────────

class DmxInDialog(QDialog):
    """Reglage de l'entree DMX : mode Patch (une adresse) ou Libre (une table)."""

    def __init__(self, window, link: DmxInLink):
        super().__init__(window)
        self._window = window
        self._link = link
        self._learning = False

        self.setWindowTitle(tr("dmxin_title"))
        self.setMinimumWidth(600)
        self.setStyleSheet(STYLE_DIALOGUE)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

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

        # ── Choix du mode ───────────────────────────────────────────────────
        bascule = QHBoxLayout()
        bascule.setSpacing(8)
        self._btn_patch = QPushButton(tr("dmxin_mode_patch"))
        self._btn_patch.setFixedHeight(36)
        self._btn_patch.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_patch.clicked.connect(lambda: self._set_mode(MODE_PATCH))
        bascule.addWidget(self._btn_patch)

        self._btn_libre = QPushButton(tr("dmxin_mode_libre"))
        self._btn_libre.setFixedHeight(36)
        self._btn_libre.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_libre.clicked.connect(lambda: self._set_mode(MODE_LIBRE))
        bascule.addWidget(self._btn_libre)
        root.addLayout(bascule)

        self._aide_mode = QLabel("")
        self._aide_mode.setWordWrap(True)
        self._aide_mode.setStyleSheet("color:#00d4ff; font-size:11px;")
        root.addWidget(self._aide_mode)

        # ── Reseau (commun aux deux modes) ──────────────────────────────────
        reseau = QHBoxLayout()
        reseau.setSpacing(10)

        reseau.addWidget(self._petit_titre(tr("dmxin_universe")))
        self._uni = QSpinBox()
        self._uni.setRange(0, 32767)
        self._uni.setValue(link.universe)
        self._uni.setFixedWidth(75)
        self._uni.valueChanged.connect(self._on_reglage)
        reseau.addWidget(self._uni)

        reseau.addSpacing(10)
        reseau.addWidget(self._petit_titre(tr("dmxin_port")))
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(link.port)
        self._port.setFixedWidth(75)
        self._port.valueChanged.connect(self._on_reglage)
        reseau.addWidget(self._port)

        reseau.addSpacing(10)
        reseau.addWidget(self._petit_titre(tr("dmxin_merge")))
        self._merge = QComboBox()
        self._merge.addItem(tr("dmxin_merge_ltp"), MERGE_LTP)
        self._merge.addItem(tr("dmxin_merge_htp"), MERGE_HTP)
        self._merge.setCurrentIndex(1 if link.merge == MERGE_HTP else 0)
        self._merge.currentIndexChanged.connect(self._on_reglage)
        reseau.addWidget(self._merge, 1)

        root.addLayout(reseau)

        # ── Etat en direct ──────────────────────────────────────────────────
        self._etat = QLabel("")
        self._etat.setWordWrap(True)
        self._etat.setStyleSheet("color:#888; font-size:11px;")
        root.addWidget(self._etat)

        # Une entree DMX peut etre parfaitement configuree et ne rien recevoir
        # pour deux raisons qu'aucun libelle de cette fenetre ne peut deviner :
        # le port du boitier reste en SORTIE, ou le pare-feu Windows jette l'UDP
        # entrant. Sans cette ligne, l'utilisateur fixe un ecran muet.
        self._alerte = QLabel("")
        self._alerte.setWordWrap(True)
        self._alerte.setStyleSheet("color:#ffb84d; font-size:11px;")
        self._alerte.setVisible(False)
        root.addWidget(self._alerte)

        root.addWidget(self._separateur())

        # ── Les deux pages de reglage ───────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_patch())
        self._stack.addWidget(self._page_libre())
        root.addWidget(self._stack)

        note = QLabel(tr("dmxin_offpage_note"))
        note.setWordWrap(True)
        note.setStyleSheet("color:#777; font-size:11px;")
        root.addWidget(note)

        # ── Pied ────────────────────────────────────────────────────────────
        pied = QHBoxLayout()
        pied.addStretch(1)
        fermer = QPushButton(tr("dmxin_close"))
        fermer.setCursor(QCursor(Qt.PointingHandCursor))
        fermer.clicked.connect(self.accept)
        pied.addWidget(fermer)
        root.addLayout(pied)

        # L'ecoute doit tourner pendant le reglage : sans trame, pas
        # d'apprentissage possible.
        link.channel_learned.connect(self._on_channel_learned)
        link.apply()

        self._appliquer_mode_ui()
        self._rafraichir()

        self._refresh = QTimer(self)
        self._refresh.setInterval(300)
        self._refresh.timeout.connect(self._rafraichir)
        self._refresh.start()

    # ── construction des deux pages ─────────────────────────────────────────

    def _page_patch(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        adresse = QHBoxLayout()
        adresse.setSpacing(8)
        adresse.addWidget(self._petit_titre(tr("dmxin_start")))
        self._start = QSpinBox()
        self._start.setRange(1, max_start(self._link.pages))
        self._start.setValue(self._link.start_channel)
        self._start.setFixedWidth(80)
        self._start.valueChanged.connect(self._on_reglage)
        adresse.addWidget(self._start)

        self._btn_learn_patch = QPushButton(tr("dmxin_learn"))
        self._btn_learn_patch.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_learn_patch.setToolTip(tr("dmxin_learn_tip"))
        self._btn_learn_patch.clicked.connect(self._toggle_learn)
        adresse.addWidget(self._btn_learn_patch)
        adresse.addStretch(1)
        lay.addLayout(adresse)

        self._resume = QLabel("")
        self._resume.setWordWrap(True)
        self._resume.setStyleSheet("color:#888; font-size:11px;")
        lay.addWidget(self._resume)

        entete = QHBoxLayout()
        entete.setSpacing(8)
        entete.addWidget(self._petit_titre(tr("dmxin_patch_title")))
        entete.addSpacing(8)
        entete.addWidget(self._petit_titre(tr("dmxin_page")))
        self._page_vue = QComboBox()
        for p in range(self._link.pages):
            self._page_vue.addItem(str(p + 1), p)
        self._page_vue.setCurrentIndex(min(self._link.active_page(),
                                           self._link.pages - 1))
        self._page_vue.setFixedWidth(70)
        self._page_vue.currentIndexChanged.connect(self._rafraichir)
        entete.addWidget(self._page_vue)
        entete.addStretch(1)
        lay.addLayout(entete)

        self._table_patch = self._table_3col(TRANCHES_PAR_PAGE + 1,
                                             tr("dmxin_col_tranche"))
        lay.addWidget(self._table_patch)
        return page

    def _page_libre(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        lay.addWidget(self._petit_titre(tr("dmxin_assign_title")))

        self._table_libre = self._table_3col(0, tr("dmxin_col_target"),
                                             supprimable=True)
        lay.addWidget(self._table_libre)

        self._vide = QLabel(tr("dmxin_empty"))
        self._vide.setWordWrap(True)
        self._vide.setStyleSheet("color:#777; font-size:11px;")
        lay.addWidget(self._vide)

        # Cible en deux temps : page, puis tranche. Un combo unique ferait 161
        # entrees, illisible et impossible a parcourir en show.
        ajout = QHBoxLayout()
        ajout.setSpacing(8)
        ajout.addWidget(self._petit_titre(tr("dmxin_page")))
        self._page_cible = QComboBox()
        for p in range(self._link.pages):
            self._page_cible.addItem(str(p + 1), p)
        self._page_cible.setCurrentIndex(min(self._link.active_page(),
                                             self._link.pages - 1))
        self._page_cible.setFixedWidth(65)
        self._page_cible.currentIndexChanged.connect(self._remplir_tranches)
        ajout.addWidget(self._page_cible)

        self._tranche_cible = QComboBox()
        ajout.addWidget(self._tranche_cible, 1)

        ajout.addWidget(self._petit_titre(tr("dmxin_col_channel")))
        self._canal = QSpinBox()
        self._canal.setRange(1, DMX_SLOTS)
        self._canal.setFixedWidth(70)
        ajout.addWidget(self._canal)

        self._btn_learn_libre = QPushButton(tr("dmxin_learn"))
        self._btn_learn_libre.setCursor(QCursor(Qt.PointingHandCursor))
        self._btn_learn_libre.setToolTip(tr("dmxin_learn_tip_libre"))
        self._btn_learn_libre.clicked.connect(self._toggle_learn)
        ajout.addWidget(self._btn_learn_libre)

        btn_add = QPushButton(tr("dmxin_add"))
        btn_add.setCursor(QCursor(Qt.PointingHandCursor))
        btn_add.clicked.connect(self._ajouter)
        ajout.addWidget(btn_add)

        lay.addLayout(ajout)
        self._remplir_tranches()
        return page

    # ── petits helpers d'apparence ──────────────────────────────────────────

    def _table_3col(self, lignes, titre_cible, supprimable=False):
        colonnes = 4 if supprimable else 3
        table = QTableWidget(lignes, colonnes)
        entetes = [tr("dmxin_col_channel"), titre_cible, tr("dmxin_col_value")]
        if supprimable:
            entetes.append("")
        table.setHorizontalHeaderLabels(entetes)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setMinimumHeight(230)
        tetes = table.horizontalHeader()
        tetes.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tetes.setSectionResizeMode(1, QHeaderView.Stretch)
        tetes.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        if supprimable:
            tetes.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        for ligne in range(lignes):
            for col in range(3):
                table.setItem(ligne, col, QTableWidgetItem(""))
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

    # ── mode ────────────────────────────────────────────────────────────────

    def _set_mode(self, mode):
        self._link.set_mode(mode)
        self._link.save()
        self._appliquer_mode_ui()
        self._rafraichir()

    def _appliquer_mode_ui(self):
        patch = self._link.mode == MODE_PATCH
        self._stack.setCurrentIndex(0 if patch else 1)
        self._aide_mode.setText(tr("dmxin_mode_patch_help") if patch
                                else tr("dmxin_mode_libre_help"))
        actif = ("background:#1d4f2a; border:1px solid #3ba55d; color:#eaffea;"
                 " border-radius:6px; font-weight:bold;")
        neutre = ("background:#1e1e1e; border:1px solid #333; color:#aaa;"
                  " border-radius:6px;")
        self._btn_patch.setStyleSheet(f"QPushButton{{{actif if patch else neutre}}}")
        self._btn_libre.setStyleSheet(f"QPushButton{{{neutre if patch else actif}}}")

    # ── reglages ────────────────────────────────────────────────────────────

    def _on_toggle(self, coche):
        self._link.enabled = bool(coche)
        self._appliquer()

    def _on_reglage(self, *_):
        self._link.set_start_channel(self._start.value())
        self._link.universe = self._uni.value()
        self._link.port = self._port.value()
        self._link.merge = self._merge.currentData()
        self._appliquer()

    def _appliquer(self):
        self._link.apply()
        self._link.save()
        self._rafraichir()

    # ── mode Libre : cible et table ─────────────────────────────────────────

    def _remplir_tranches(self, *_):
        """Recharge les 8 libelles de la page choisie, plus le fader 9."""
        page = self._page_cible.currentData() or 0
        garde = self._tranche_cible.currentData()
        self._tranche_cible.blockSignals(True)
        self._tranche_cible.clear()
        for i, libelle in enumerate(tranche_labels(self._window, page)):
            self._tranche_cible.addItem(
                tr("dmxin_tranche_n", n=i + 1, label=libelle), i)
        self._tranche_cible.addItem(tr("dmxin_tranche_speed"), -1)
        if garde is not None:
            index = self._tranche_cible.findData(garde)
            if index >= 0:
                self._tranche_cible.setCurrentIndex(index)
        self._tranche_cible.blockSignals(False)

    def _ajouter(self):
        tranche = self._tranche_cible.currentData()
        if tranche is None:
            return
        if tranche < 0:
            self._link.add_assignment(self._canal.value(), vitesse=True)
        else:
            self._link.add_assignment(self._canal.value(),
                                      page=self._page_cible.currentData() or 0,
                                      tranche=tranche)
        self._link.save()
        self._rafraichir()

    def _supprimer(self, canal):
        self._link.remove_assignment(canal)
        self._link.save()
        self._rafraichir()

    # ── apprentissage ───────────────────────────────────────────────────────

    def _toggle_learn(self):
        if self._learning:
            self._link.cancel_learn()
            self._learning = False
            self._maj_boutons_learn()
            self._rafraichir()
            return
        if not self._link.enabled:
            # Apprendre sans ecouter n'a aucun sens : on active pour
            # l'utilisateur plutot que de lui renvoyer un message d'erreur.
            self._actif.setChecked(True)
        self._link.start_learn()
        self._learning = True
        self._maj_boutons_learn()
        self._rafraichir()

    def _maj_boutons_learn(self):
        texte = tr("dmxin_learn_cancel") if self._learning else tr("dmxin_learn")
        self._btn_learn_patch.setText(texte)
        self._btn_learn_libre.setText(texte)

    def _on_channel_learned(self, canal):
        self._learning = False
        self._maj_boutons_learn()
        if self._link.mode == MODE_PATCH:
            # La liaison a deja pose l'adresse : on suit sans relancer
            # `_on_reglage`, qui reinitialiserait son etat pour rien.
            self._start.blockSignals(True)
            self._start.setValue(int(canal))
            self._start.blockSignals(False)
        else:
            self._canal.setValue(int(canal))
        self._link.save()
        self._rafraichir()

    # ── affichage ───────────────────────────────────────────────────────────

    def _rafraichir(self, *_):
        link = self._link

        if self._learning:
            attente = ("dmxin_learn_wait" if link.mode == MODE_PATCH
                       else "dmxin_learn_wait_libre")
            self._etat.setText(f"◉  {tr(attente)}")
            self._etat.setStyleSheet("color:#00d4ff; font-size:11px;")
        else:
            recoit, message = link.status()
            puce = "●" if recoit else "○"
            couleur = "#5f5" if recoit else "#888"
            self._etat.setText(f"{puce}  {message}")
            self._etat.setStyleSheet(f"color:{couleur}; font-size:11px;")

        alertes = []
        # Un diagnostic PRECIS vaut mieux que le rappel general : quand
        # l'aiguillage explique deja pourquoi rien n'arrive, repeter « verifiez
        # le port et le pare-feu » par-dessus ne fait que noyer la vraie cause.
        routage = link.routing_hint()
        if routage:
            alertes.append(routage)
        elif link.enabled and not link.receiver.is_receiving():
            alertes.append(tr("dmxin_hint_no_data"))
        if link.echo_risk():
            alertes.append(tr("dmxin_warn_echo"))
        self._alerte.setText("\n".join(alertes))
        self._alerte.setVisible(bool(alertes))

        if link.mode == MODE_PATCH:
            self._rafraichir_patch()
        else:
            self._rafraichir_libre()

    def _rafraichir_patch(self):
        link = self._link
        self._resume.setText(tr("dmxin_patch_summary",
                                a=link.start_channel, b=link.last_channel,
                                p=link.pages, n=link.patch_size))
        page = self._page_vue.currentData() or 0
        for ligne, (canal, libelle, brut) in enumerate(link.patch_rows(page)):
            self._table_patch.item(ligne, 0).setText(
                str(canal) if canal <= DMX_SLOTS else "—")
            self._table_patch.item(ligne, 1).setText(
                tr("dmxin_tranche_n", n=ligne + 1, label=libelle)
                if ligne < TRANCHES_PAR_PAGE else libelle)
            self._table_patch.item(ligne, 2).setText(
                "—" if brut is None else str(brut))

    def _rafraichir_libre(self):
        lignes = self._link.assignment_rows()
        table = self._table_libre
        if table.rowCount() != len(lignes):
            table.setRowCount(len(lignes))
            for ligne, (canal, _libelle, _brut) in enumerate(lignes):
                for col in range(3):
                    if table.item(ligne, col) is None:
                        table.setItem(ligne, col, QTableWidgetItem(""))
                supprimer = QPushButton("✖")
                supprimer.setFixedWidth(32)
                supprimer.setCursor(QCursor(Qt.PointingHandCursor))
                supprimer.setToolTip(tr("dmxin_remove"))
                supprimer.clicked.connect(lambda _c, ch=canal: self._supprimer(ch))
                enveloppe = QWidget()
                boite = QHBoxLayout(enveloppe)
                boite.setContentsMargins(0, 0, 0, 0)
                boite.addWidget(supprimer)
                table.setCellWidget(ligne, 3, enveloppe)

        for ligne, (canal, libelle, brut) in enumerate(lignes):
            table.item(ligne, 0).setText(str(canal))
            table.item(ligne, 1).setText(libelle)
            table.item(ligne, 2).setText("—" if brut is None else str(brut))

        self._vide.setVisible(not lignes)

    def done(self, code):
        # Rendre la main AVANT tout le reste : une liaison laissee suspendue
        # serait une entree DMX definitivement muette jusqu'au redemarrage.
        try:
            self._link.cancel_learn()
        except Exception:
            pass
        try:
            self._refresh.stop()
            self._link.channel_learned.disconnect(self._on_channel_learned)
        except Exception:
            pass
        try:
            self._link.save()
            self._link.apply()
        except Exception:
            pass
        super().done(code)
