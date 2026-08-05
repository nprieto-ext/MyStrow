"""
vmix_client.py — Liaison vMix → MyStrow (API TCP, port 8099).

Le sens est volontairement A SENS UNIQUE : vMix pilote MyStrow, jamais
l'inverse. C'est le realisateur video qui mene le direct ; l'eclairage suit la
camera a l'antenne, pas le contraire. Une liaison bidirectionnelle ouvrirait en
prime une boucle de retour (MyStrow change une scene, vMix renvoie le tally,
MyStrow rejoue l'action...) qu'il faudrait garder — probleme qu'on s'evite en
ne l'introduisant pas.

Meme ossature que streamdeck_api.py : un thread fait l'entree/sortie reseau, un
QObject porte des Signals Qt. Emis depuis le thread, ils sont mis en file et
delivres dans le thread Qt : aucun widget, aucun projecteur n'est touche depuis
le reseau. C'est la seule facon de ne pas voler des images a la trame DMX.

Protocole (doc vMix « TCP API », verifie sur vmix.com/help28/TCPAPI.html) :
  - port 8099, messages UTF-8 termines par \\r\\n
  - `SUBSCRIBE TALLY\\r\\n` puis vMix pousse `TALLY OK 0121...` a chaque
    changement : un chiffre par entree, 0 = eteinte, 1 = programme, 2 = preview
  - `XML\\r\\n` repond `XML <nb_octets>\\r\\n` SUIVI des octets — cette
    reponse-la n'est donc pas delimitee par une fin de ligne, d'ou le lecteur
    a deux modes ci-dessous.

On passe par le TCP et non par l'API HTTP (8088) y compris pour lire la liste
des entrees : le port 8099 est toujours actif, alors que le port 8088 depend du
Web Controller, que l'utilisateur peut avoir desactive. Une dependance de moins
a expliquer quand ca ne marche pas.
"""

import socket
import threading
import xml.etree.ElementTree as ET

from PySide6.QtCore import QObject, Signal

VMIX_TCP_PORT = 8099

# Etats de tally renvoyes par vMix
TALLY_OFF     = 0
TALLY_PROGRAM = 1
TALLY_PREVIEW = 2


# ---------------------------------------------------------------------------
# Lecture du flux
# ---------------------------------------------------------------------------

class _Reader:
    """Decoupe le flux vMix.

    Deux modes, imposes par le protocole : la plupart des reponses sont des
    lignes \\r\\n, mais `XML` est precede de sa longueur en octets et peut
    evidemment CONTENIR des \\r\\n. Lire betement ligne par ligne couperait le
    XML en morceaux et desynchroniserait tout ce qui suit.
    """

    def __init__(self, sock):
        self._sock = sock
        self._buf = b""

    def _fill(self):
        chunk = self._sock.recv(65536)
        if not chunk:
            raise ConnectionError("connexion fermee par vMix")
        self._buf += chunk

    def read_line(self) -> str:
        while b"\r\n" not in self._buf:
            self._fill()
        line, self._buf = self._buf.split(b"\r\n", 1)
        return line.decode("utf-8", "replace")

    def read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            self._fill()
        data, self._buf = self._buf[:n], self._buf[n:]
        return data


def _parse_inputs(xml_text: str) -> list:
    """Extrait [{'number': 1, 'title': 'Cam 1'}, ...] du XML d'etat vMix."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for node in root.findall("./inputs/input"):
        try:
            num = int(node.get("number", "0"))
        except ValueError:
            continue
        if num <= 0:
            continue
        titre = (node.get("shortTitle") or node.get("title") or f"Entree {num}").strip()
        out.append({"number": num, "title": titre})
    out.sort(key=lambda d: d["number"])
    return out


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class VmixClient(QObject):
    """Connexion persistante a vMix, avec reconnexion automatique.

    Les Signals sont emis depuis le thread reseau ; Qt les delivre dans le
    thread principal (connexion auto = Queued des que les threads different).
    """

    # (connecte, message affichable)
    connection_changed = Signal(bool, str)
    # Liste d'etats, index 0 = entree 1 : [1, 0, 2, 0...]
    tally_changed      = Signal(list)
    # Numero d'entree (1-based) qui VIENT de passer au programme
    program_entered    = Signal(int)
    # [{'number', 'title'}, ...]
    inputs_changed     = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = "127.0.0.1"
        self._port = VMIX_TCP_PORT
        self._thread = None
        self._stop = threading.Event()
        self._sock = None
        self._last_tally = []
        self._inputs = []
        self._connected = False

    # ── cycle de vie ────────────────────────────────────────────────────────

    def start(self, host: str = "127.0.0.1", port: int = VMIX_TCP_PORT):
        self.stop()
        self._host, self._port = host, int(port)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="vmix-tally")
        self._thread.start()

    def stop(self):
        self._stop.set()
        # Fermer la socket sous le thread : sans ca, recv() bloque jusqu'au
        # prochain octet envoye par vMix, c'est-a-dire potentiellement jamais.
        # La fenetre principale attendrait la fin du thread a la fermeture.
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        t, self._thread = self._thread, None
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        if self._connected:
            self._connected = False
            self.connection_changed.emit(False, "Deconnecte")

    def is_connected(self) -> bool:
        return self._connected

    def inputs(self) -> list:
        return list(self._inputs)

    # ── boucle reseau ───────────────────────────────────────────────────────

    def _run(self):
        attente = 1.0
        while not self._stop.is_set():
            try:
                self._session()
                attente = 1.0          # une session reussie remet le delai a plat
            except Exception as exc:
                if self._stop.is_set():
                    break
                if self._connected:
                    self._connected = False
                    self.connection_changed.emit(False, f"Connexion perdue : {exc}")
                else:
                    self.connection_changed.emit(False, str(exc))
            # Reconnexion a delai croissant, plafonnee : vMix ferme pendant le
            # montage ne doit pas marteler le reseau pendant des heures.
            if self._stop.wait(attente):
                break
            attente = min(attente * 2, 15.0)

    def _session(self):
        sock = socket.create_connection((self._host, self._port), timeout=5)
        sock.settimeout(None)          # ensuite on attend les evenements sans limite
        self._sock = sock
        try:
            reader = _Reader(sock)
            sock.sendall(b"SUBSCRIBE TALLY\r\n")
            sock.sendall(b"XML\r\n")

            self._connected = True
            self._last_tally = []
            self.connection_changed.emit(True, f"Connecte a {self._host}:{self._port}")

            while not self._stop.is_set():
                ligne = reader.read_line()
                if not ligne:
                    continue           # ligne vide = fin de charge XML, sans interet
                bouts = ligne.split(" ", 2)
                cmd = bouts[0].upper()
                arg = bouts[1] if len(bouts) > 1 else ""

                if arg.isdigit():
                    # Reponse a longueur prefixee (XML)
                    charge = reader.read_exact(int(arg)).decode("utf-8", "replace")
                    if cmd == "XML":
                        self._on_xml(charge)
                    continue

                if cmd == "TALLY" and arg == "OK":
                    self._on_tally(bouts[2].strip() if len(bouts) > 2 else "")
        finally:
            self._sock = None
            try:
                sock.close()
            except OSError:
                pass

    # ── traitement des evenements ───────────────────────────────────────────

    def _on_xml(self, texte: str):
        entrees = _parse_inputs(texte)
        if entrees and entrees != self._inputs:
            self._inputs = entrees
            self.inputs_changed.emit(list(entrees))

    def _on_tally(self, etats: str):
        """`etats` = un chiffre par entree, ex. « 0121 »."""
        courant = [int(c) if c.isdigit() else 0 for c in etats]
        if courant == self._last_tally:
            return
        precedent, self._last_tally = self._last_tally, courant
        self.tally_changed.emit(list(courant))

        # FRONT MONTANT uniquement. vMix renvoie l'etat COMPLET a chaque
        # changement : declencher sur « est au programme » au lieu de « vient
        # d'y passer » rejouerait l'action a chaque mouvement d'une AUTRE
        # entree — une memoire relancee en boucle pendant tout le direct.
        for i, etat in enumerate(courant):
            avant = precedent[i] if i < len(precedent) else TALLY_OFF
            if etat == TALLY_PROGRAM and avant != TALLY_PROGRAM:
                self.program_entered.emit(i + 1)


# ---------------------------------------------------------------------------
# Interrogation ponctuelle (dialogue de configuration)
# ---------------------------------------------------------------------------

def query_inputs(host: str, port: int = VMIX_TCP_PORT, timeout: float = 4.0) -> list:
    """Ouvre une connexion courte et renvoie la liste des entrees.

    Utilise par le bouton « Tester la connexion » : on veut une reponse
    immediate et un echec franc, pas la boucle de reconnexion du client.
    Leve une exception explicite en cas d'echec.
    """
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        reader = _Reader(sock)
        sock.sendall(b"XML\r\n")
        # Quelques lignes de tolerance : vMix peut intercaler une banniere ou
        # un evenement avant de repondre.
        for _ in range(10):
            ligne = reader.read_line()
            bouts = ligne.split(" ", 2)
            if len(bouts) > 1 and bouts[1].isdigit():
                charge = reader.read_exact(int(bouts[1])).decode("utf-8", "replace")
                if bouts[0].upper() == "XML":
                    return _parse_inputs(charge)
            elif bouts[0].upper() == "XML" and len(bouts) > 1 and bouts[1] == "ER":
                raise ConnectionError(bouts[2] if len(bouts) > 2 else "vMix a refuse la requete")
        raise ConnectionError("vMix n'a pas renvoye son etat XML")
