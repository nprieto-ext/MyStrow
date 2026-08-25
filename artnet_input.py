"""
artnet_input.py — Reception de DMX ENTRANT (ArtDmx) venant d'un pupitre.

Symetrique de artnet_dmx.py, qui ENVOIE. Ici on ECOUTE : un pupitre lumiere
branche sur un port du Node configure en entree (DMX -> Art-Net) diffuse ses
512 canaux sur le reseau, et MyStrow s'en sert comme d'un controleur.

Ce module ne connait ni Qt ni MyStrow : il recoit des trames et les range.
Ce qu'on en FAIT (quel canal pilote quel fader) est dans dmx_in_link.py, comme
gamepad_client.py / gamepad_link.py. Cette separation permet de tester tout le
protocole sans reseau, en appelant `feed()` a la main.

TROIS PIEGES QUI ONT DICTE LE CODE
-----------------------------------
1. **Le larsen.** MyStrow emet deja de l'ArtDmx vers le Node. Si on ecoute sur
   6454 sans filtrer, on peut recevoir sa PROPRE sortie (broadcast reboucle par
   la pile locale, ou renvoyee par un switch) et se la reinjecter en entree :
   les faders partent en oscillation et plus personne ne comprend pourquoi.
   D'ou `ignore_ips` : toute trame venant d'une IP de CE PC est jetee.

2. **Le port 6454 est deja pris.** Le scan ArtPoll (node_connection.py) s'y
   bind le temps d'une detection, et QLC+/Chataigne peuvent tourner a cote.
   Sans SO_REUSEADDR (+ SO_REUSEPORT sur macOS/BSD), l'un des deux meurt en
   silence. On ne retombe PAS sur un port ephemere ici : contrairement au scan,
   une entree DMX sur un port au hasard ne recevrait jamais rien — mieux vaut
   remonter l'erreur a l'utilisateur.

3. **Les paquets arrivent dans le desordre.** L'UDP ne garantit rien, et un
   pupitre emet a 40 Hz. Une trame en retard qui ecrase une trame recente fait
   sauter les faders en arriere. D'ou le controle du numero de sequence, avec
   sa comparaison circulaire (0 = sequencement desactive par l'emetteur).
"""

import socket
import threading
import time

ART_HEADER = b"Art-Net\x00"
OP_OUTPUT_DMX = 0x5000        # ArtDmx — les donnees DMX elles-memes
DEFAULT_PORT = 6454
DMX_SLOTS = 512

# Au-dela, on considere la source silencieuse (un pupitre emet en continu,
# meme a l'arret : 1 s sans rien, c'est que le lien est coupe).
SOURCE_TIMEOUT_S = 2.0


def parse_artdmx(data):
    """Decode une trame ArtDmx. Retourne (univers, payload) ou None.

    Tout ce qui n'est pas un ArtDmx exploitable renvoie None sans lever :
    sur le port 6454 transitent aussi des ArtPoll, ArtPollReply, ArtSync et le
    trafic d'autres logiciels. Le rejet doit etre silencieux et gratuit.
    """
    if not data or len(data) < 18 or data[:8] != ART_HEADER:
        return None
    # OpCode : little-endian (seul champ Art-Net qui l'est).
    if (data[8] | (data[9] << 8)) != OP_OUTPUT_DMX:
        return None
    universe = (data[15] << 8) | data[14]     # Net << 8 | SubUni
    length = (data[16] << 8) | data[17]       # Length : big-endian, lui
    if length <= 0:
        return None
    payload = data[18:18 + min(length, DMX_SLOTS)]
    if not payload:
        return None
    return universe, payload


def sequence_is_newer(seq, last_seq):
    """Faut-il accepter cette trame ? (comparaison circulaire sur 8 bits)

    Art-Net numerote de 1 a 255 et repasse a 1 ; 0 signifie « sequencement
    desactive », auquel cas on accepte tout. On accepte une trame dont l'ecart
    avec la precedente est inferieur a un demi-tour de compteur : au-dela, c'est
    une trame en retard, pas une nouvelle.
    """
    if seq == 0 or last_seq == 0:
        return True
    return 0 < ((seq - last_seq) & 0xFF) < 128


class ArtNetReceiver:
    """Ecoute l'ArtDmx entrant et garde la derniere trame de chaque univers.

    On ne notifie personne : c'est l'appelant qui vient lire `snapshot()` a la
    cadence qui l'arrange. Un pupitre emet 40 trames/s de 512 octets ; publier
    un evenement par trame noierait la boucle Qt pour rien, puisque seule la
    DERNIERE valeur d'un canal a du sens.
    """

    def __init__(self):
        self._sock = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self._frames = {}          # univers -> bytes(512)
        self._seq = {}             # univers -> dernier numero de sequence
        self._counters = {}        # univers -> compteur de trames acceptees
        self._sources = {}         # ip source -> horodatage de la derniere trame
        self._last_rx = 0.0

        self.port = DEFAULT_PORT
        self.ignore_ips = set()    # cf. piege n°1
        self.error = None          # message d'erreur d'ouverture, ou None

    # ── cycle de vie ────────────────────────────────────────────────────────

    def start(self, port=DEFAULT_PORT, ignore_ips=None):
        """Ouvre la socket et lance le thread d'ecoute. True si l'ecoute tourne."""
        if self.is_running() and self.port == int(port):
            self.ignore_ips = set(ignore_ips or ())
            return True
        self.stop()

        self.port = int(port)
        self.ignore_ips = set(ignore_ips or ())
        self.error = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                # macOS/BSD : sans ca, cohabiter avec le scan ArtPoll ou une
                # autre appli DMX sur 6454 echoue malgre SO_REUSEADDR.
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            sock.bind(("", self.port))
            # Timeout court : c'est ce qui permet a stop() d'etre immediat
            # sans fermer la socket sous le thread.
            sock.settimeout(0.3)
        except OSError as exc:
            self.error = str(exc)
            return False

        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="artnet-in", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        with self._lock:
            self._sources.clear()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    # ── boucle d'ecoute ─────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, (sender, _port) = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                # Socket fermee sous nos pieds (stop) ou carte reseau retiree.
                break
            except Exception:
                continue
            self.feed(data, sender)

    def feed(self, data, sender=""):
        """Range une trame recue. Separee de la boucle pour etre testable.

        Retourne l'univers accepte, ou None si la trame a ete ecartee.
        """
        if sender and sender in self.ignore_ips:
            return None            # notre propre sortie — cf. piege n°1
        parsed = parse_artdmx(data)
        if parsed is None:
            return None
        universe, payload = parsed
        seq = data[12]

        with self._lock:
            if not sequence_is_newer(seq, self._seq.get(universe, 0)):
                return None        # trame en retard — cf. piege n°3
            self._seq[universe] = seq
            # Un pupitre peut n'emettre que les N premiers canaux : on complete
            # a 512 pour que l'appelant indexe sans se poser de question.
            frame = bytearray(DMX_SLOTS)
            frame[:len(payload)] = payload
            self._frames[universe] = bytes(frame)
            self._counters[universe] = self._counters.get(universe, 0) + 1
            now = time.time()
            self._last_rx = now
            if sender:
                self._sources[sender] = now
        return universe

    # ── lecture ─────────────────────────────────────────────────────────────

    def snapshot(self, universe):
        """(compteur, trame) pour cet univers, ou (0, None) si rien recu.

        Le compteur permet a l'appelant de sauter le travail quand rien n'a
        bouge depuis sa derniere lecture.
        """
        with self._lock:
            frame = self._frames.get(universe)
            if frame is None:
                return 0, None
            return self._counters.get(universe, 0), frame

    def universes_seen(self):
        """Univers reellement recus — sert a dire « vous ecoutez le 0, votre
        pupitre emet sur le 1 », qui est LA erreur de reglage la plus courante."""
        with self._lock:
            return sorted(self._frames.keys())

    def sources(self):
        """IPs qui emettent en ce moment (les silencieuses sont oubliees)."""
        now = time.time()
        with self._lock:
            return sorted(ip for ip, t in self._sources.items()
                          if now - t < SOURCE_TIMEOUT_S)

    def is_receiving(self):
        with self._lock:
            return bool(self._last_rx) and (time.time() - self._last_rx) < SOURCE_TIMEOUT_S
