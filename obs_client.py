"""
obs_client.py — Liaison OBS Studio → MyStrow (obs-websocket v5, port 4455).

Meme parti pris que vmix_client.py, et pour les memes raisons : le sens est A
SENS UNIQUE. C'est la regie video qui mene le direct, l'eclairage suit la scene
a l'antenne. Une liaison bidirectionnelle ouvrirait une boucle de retour
(MyStrow change une memoire, OBS renvoie un evenement, MyStrow rejoue l'action)
qu'il faudrait ensuite garder.

L'equivalence avec vMix est directe :
    entree vMix qui passe au PROGRAMME  ==  scene OBS qui devient active
d'ou le meme vocabulaire d'actions et le meme dialogue de reglage (video_link).

POURQUOI UN WEBSOCKET ECRIT A LA MAIN
-------------------------------------
OBS n'expose pas d'API TCP en clair comme vMix : obs-websocket v5 est le seul
protocole disponible, et il impose un vrai WebSocket (RFC 6455). Or le projet
n'embarque aucune bibliotheque WebSocket, et en ajouter une obligerait a la
declarer dans les quatre configurations de build (Windows, macOS ARM, macOS
Intel, admin_panel) puis a la faire passer par la signature de code. On ecrit
donc les ~200 lignes necessaires, dans la meme logique que firebase_client.py
qui parle a Firebase en urllib brut plutot qu'avec le SDK.

Ce qu'on implemente du RFC 6455, et rien de plus :
  - la poignee de main HTTP Upgrade avec verification de Sec-WebSocket-Accept
  - les trames texte, y compris fragmentees (continuation)
  - le MASQUAGE des trames sortantes, qui est OBLIGATOIRE pour un client : un
    serveur conforme coupe la connexion si on l'omet
  - ping/pong, sinon OBS ferme la session au bout de quelques dizaines de
    secondes de silence
Pas de TLS (obs-websocket ecoute en ws:// non chiffre), pas de compression
(permessage-deflate n'est pas negocie, donc jamais actif), pas de role serveur.

Protocole obs-websocket v5 (docs : github.com/obsproject/obs-websocket) :
  - a la connexion, OBS pousse Hello (op 0) avec, si l'authentification est
    activee, un couple {challenge, salt}
  - le client repond Identify (op 1) ; OBS confirme par Identified (op 2)
  - ensuite : evenements en op 5, requetes en op 6, reponses en op 7
"""

import base64
import errno
import hashlib
import json
import os
import socket
import struct
import threading

from PySide6.QtCore import QObject, Signal

OBS_WS_PORT = 4455

# ── Codes d'operation WebSocket (RFC 6455) ──────────────────────────────────
# Prefixes WS_ pour ne pas les confondre avec les op-codes d'obs-websocket,
# qui vivent dans le CORPS des messages et forment une numerotation distincte.
WS_CONT, WS_TEXT, WS_BINARY = 0x0, 0x1, 0x2
WS_CLOSE, WS_PING, WS_PONG  = 0x8, 0x9, 0xA

# ── Codes d'operation obs-websocket v5 ──────────────────────────────────────
OBS_HELLO, OBS_IDENTIFY, OBS_IDENTIFIED = 0, 1, 2
OBS_EVENT, OBS_REQUEST, OBS_RESPONSE    = 5, 6, 7

# Abonnement aux evenements : General (1<<0) pour savoir qu'OBS se ferme,
# Scenes (1<<2) pour le changement de scene programme. On ne s'abonne pas au
# reste : chaque categorie inutile, ce sont des messages a decoder pendant le
# direct pour les jeter ensuite.
OBS_SUB_GENERAL = 1 << 0
OBS_SUB_SCENES  = 1 << 2
OBS_SUBSCRIPTIONS = OBS_SUB_GENERAL | OBS_SUB_SCENES

# Constante figee par le RFC : concatenee a la cle du client, son SHA-1 doit
# revenir dans Sec-WebSocket-Accept. C'est ce qui prouve qu'en face on a bien
# un serveur WebSocket et non un serveur HTTP qui repondrait 101 par hasard.
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Un seul caractere de travers ici et AUCUNE connexion OBS n'aboutit : le
# serveur repond correctement, mais notre verification refuse sa reponse et
# la liaison echoue sur « poignee de main invalide », sans que rien ne
# designe la vraie cause. C'est arrive : le dernier groupe avait ete saisi
# « 5AB0DC85B11C » au lieu de « C5AB0DC85B11 », un C deplace d'un bout a
# l'autre. Les deux font 36 caracteres et se ressemblent a la lecture.
# Le controle ci-dessous est l'exemple normatif du RFC 6455 (section 1.3) :
# il echoue au demarrage si la constante est de nouveau abimee.
assert base64.b64encode(hashlib.sha1(
    ("dGhlIHNhbXBsZSBub25jZQ==" + _WS_GUID).encode("ascii")).digest()
).decode("ascii") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", "_WS_GUID corrompu"

# Codes de fermeture propres a obs-websocket, pour transformer un « connexion
# fermee » opaque en message que l'utilisateur peut agir.
_OBS_CLOSE_MESSAGES = {
    4009: "mot de passe refuse par OBS",
    4010: "version de protocole non supportee par OBS",
    4011: "session invalidee par OBS",
}


# ---------------------------------------------------------------------------
# Couche WebSocket
# ---------------------------------------------------------------------------

def _erreur_reseau(exc: OSError, host: str, port: int) -> Exception:
    """Traduit un echec de socket en message sur lequel l'utilisateur peut agir.

    Le message brut du systeme est remonte tel quel jusqu'au dialogue :
    « [WinError 10061] Aucune connexion n'a pu etre etablie car l'ordinateur
    cible l'a expressement refusee » decrit l'etat de la socket, pas ce qu'il
    faut faire. Or ce cas est de tres loin le plus frequent, et sa cause est
    presque toujours la meme : le serveur WebSocket d'OBS n'est PAS actif par
    defaut, il faut aller le cocher une fois. Le refus est d'ailleurs le seul
    diagnostic fiable qu'on ait — rien n'ecoute sur le port — alors qu'un
    pare-feu, lui, laisse expirer sans refuser.
    """
    cible = f"{host}:{port}"
    if isinstance(exc, socket.gaierror):
        return ConnectionError(f"hote « {host} » introuvable")

    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    if isinstance(exc, ConnectionRefusedError) or code in (10061, errno.ECONNREFUSED):
        return ConnectionError(
            f"rien n'ecoute sur {cible}. Lancez OBS, puis Outils > Parametres "
            f"du serveur WebSocket > cochez « Activer le serveur WebSocket » "
            f"(port {OBS_WS_PORT}, OBS 28 minimum).")
    if isinstance(exc, (socket.timeout, TimeoutError)) or code in (10060, errno.ETIMEDOUT):
        return ConnectionError(
            f"aucune reponse de {cible} — machine injoignable, ou pare-feu qui "
            f"bloque le port.")
    if isinstance(exc, ConnectionResetError) or code in (10054, errno.ECONNRESET):
        return ConnectionError(f"connexion coupee par {cible} en cours d'etablissement")
    return ConnectionError(f"connexion a {cible} impossible : {exc}")


class _WebSocket:
    """Client WebSocket minimal, synchrone, au-dessus d'une socket TCP."""

    def __init__(self, sock):
        self._sock = sock
        self._buf = b""
        # Les envois peuvent partir du thread reseau (requetes, pong) et du
        # thread Qt (arret) : deux sendall() entrelaces produiraient une trame
        # corrompue, que le serveur interprete comme un cadrage casse.
        self._verrou = threading.Lock()

    # ── etablissement ───────────────────────────────────────────────────────

    @classmethod
    def connect(cls, host: str, port: int, timeout: float = 5.0):
        try:
            sock = socket.create_connection((host, int(port)), timeout=timeout)
        except OSError as exc:
            raise _erreur_reseau(exc, host, int(port)) from exc
        ws = cls(sock)
        try:
            ws._poignee_de_main(host, port)
        except Exception:
            try:
                sock.close()
            except OSError:
                pass
            raise
        return ws

    def _poignee_de_main(self, host: str, port: int):
        cle = base64.b64encode(os.urandom(16)).decode("ascii")
        requete = (
            "GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {cle}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(requete.encode("ascii"))

        entete = self._lire_jusqu_a(b"\r\n\r\n").decode("latin-1", "replace")
        premiere = entete.split("\r\n", 1)[0]
        if "101" not in premiere:
            # Cas le plus frequent : on a tape sur un port qui n'est pas
            # obs-websocket (serveur HTTP quelconque, ou OBS avec le serveur
            # WebSocket desactive).
            raise ConnectionError(
                f"reponse inattendue du serveur ({premiere.strip() or 'vide'}) — "
                "le serveur WebSocket d'OBS est-il active ?")

        attendu = base64.b64encode(
            hashlib.sha1((cle + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        recu = ""
        entetes = []
        for ligne in entete.split("\r\n")[1:]:
            nom, sep, valeur = ligne.partition(":")
            if not sep:
                continue
            entetes.append(nom.strip().lower())
            if nom.strip().lower() == "sec-websocket-accept":
                recu = valeur.strip()
        if recu != attendu:
            # « poignee de main invalide » tout court est un cul-de-sac : le
            # serveur a bien repondu 101, donc ni le port ni l'activation ne
            # sont en cause, et l'utilisateur n'a plus rien a regarder. Les
            # deux cas se soignent differemment, on les distingue donc :
            #   - en-tete ABSENT   -> en face ce n'est pas un vrai serveur
            #     WebSocket (autre logiciel sur le port, ou un intermediaire —
            #     antivirus, proxy — qui a reecrit la reponse) ;
            #   - en-tete PRESENT mais faux -> la reponse a bien ete fabriquee
            #     a partir d'une AUTRE cle que la notre, signature d'un
            #     intermediaire qui a rejoue la negociation pour son compte.
            if not recu:
                raise ConnectionError(
                    f"reponse 101 sans en-tete Sec-WebSocket-Accept (recu : "
                    f"{', '.join(entetes) or 'aucun en-tete'}) — ce n'est pas "
                    f"obs-websocket qui repond sur {host}:{port}, ou un "
                    f"antivirus/proxy s'intercale.")
            raise ConnectionError(
                f"Sec-WebSocket-Accept incorrect (recu {recu}, attendu "
                f"{attendu}) — un intermediaire (antivirus, proxy) a renegocie "
                f"la connexion a {host}:{port}.")

    def _lire_jusqu_a(self, marqueur: bytes) -> bytes:
        """Lit jusqu'au marqueur inclus ; le reste est CONSERVE dans le tampon.

        Indispensable : OBS envoie son Hello immediatement, et ces octets
        arrivent souvent dans le meme paquet TCP que la fin des en-tetes. Les
        jeter ferait perdre le premier message a chaque connexion — de facon
        intermittente, selon le decoupage reseau.
        """
        while marqueur not in self._buf:
            self._remplir()
        avant, _, apres = self._buf.partition(marqueur)
        self._buf = apres
        return avant + marqueur

    def _remplir(self):
        bloc = self._sock.recv(65536)
        if not bloc:
            raise ConnectionError("connexion fermee par OBS")
        self._buf += bloc

    def _lire_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            self._remplir()
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    # ── trames ──────────────────────────────────────────────────────────────

    def _lire_trame(self):
        tete = self._lire_exact(2)
        fin     = bool(tete[0] & 0x80)
        opcode  = tete[0] & 0x0F
        masquee = bool(tete[1] & 0x80)
        taille  = tete[1] & 0x7F
        if taille == 126:
            taille = struct.unpack(">H", self._lire_exact(2))[0]
        elif taille == 127:
            taille = struct.unpack(">Q", self._lire_exact(8))[0]
        # Un serveur ne masque jamais ses trames, mais on sait les demasquer :
        # ca ne coute rien et evite un decodage silencieusement faux.
        masque = self._lire_exact(4) if masquee else None
        charge = self._lire_exact(taille) if taille else b""
        if masque:
            charge = bytes(o ^ masque[i % 4] for i, o in enumerate(charge))
        return fin, opcode, charge

    def recevoir(self) -> str:
        """Prochain message texte applicatif, trames de controle absorbees.

        Les messages fragmentes sont recolles ici : obs-websocket n'en produit
        pas aujourd'hui, mais rien dans le protocole ne l'interdit et une
        longue liste de scenes est exactement le genre de charge qu'un serveur
        peut decider de couper. Une implementation qui ignore la continuation
        casse alors sans prevenir, sur la seule configuration d'un client.
        """
        morceaux, opcode_msg = [], None
        while True:
            fin, opcode, charge = self._lire_trame()

            if opcode == WS_CLOSE:
                code = struct.unpack(">H", charge[:2])[0] if len(charge) >= 2 else 0
                raison = charge[2:].decode("utf-8", "replace").strip()
                detail = _OBS_CLOSE_MESSAGES.get(code) or raison or f"code {code}"
                raise ConnectionError(f"OBS a ferme la connexion ({detail})")
            if opcode == WS_PING:
                self.envoyer_trame(WS_PONG, charge)
                continue
            if opcode == WS_PONG:
                continue

            if opcode == WS_CONT:
                if opcode_msg is None:
                    continue                      # continuation orpheline
                morceaux.append(charge)
            else:
                opcode_msg, morceaux = opcode, [charge]

            if fin:
                complet = b"".join(morceaux)
                termine, opcode_msg, morceaux = opcode_msg, None, []
                if termine == WS_TEXT:
                    return complet.decode("utf-8", "replace")
                # Trame binaire : obs-websocket n'en emet pas, on l'ignore.

    def envoyer_trame(self, opcode: int, charge: bytes):
        n = len(charge)
        tete = bytearray()
        tete.append(0x80 | opcode)               # FIN, jamais de fragmentation
        # Le bit de masque est TOUJOURS mis : c'est une obligation cote client,
        # un serveur conforme ferme la connexion sur une trame non masquee.
        if n < 126:
            tete.append(0x80 | n)
        elif n < 65536:
            tete.append(0x80 | 126)
            tete += struct.pack(">H", n)
        else:
            tete.append(0x80 | 127)
            tete += struct.pack(">Q", n)
        masque = os.urandom(4)
        tete += masque
        corps = bytes(o ^ masque[i % 4] for i, o in enumerate(charge))
        with self._verrou:
            self._sock.sendall(bytes(tete) + corps)

    def envoyer_texte(self, texte: str):
        self.envoyer_trame(WS_TEXT, texte.encode("utf-8"))

    def envoyer_json(self, op: int, donnees: dict):
        self.envoyer_texte(json.dumps({"op": op, "d": donnees}))

    def fermer(self):
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def regler_timeout(self, valeur):
        self._sock.settimeout(valeur)


# ---------------------------------------------------------------------------
# Authentification obs-websocket
# ---------------------------------------------------------------------------

def _chaine_auth(mot_de_passe: str, sel: str, defi: str) -> str:
    """base64(sha256(base64(sha256(mdp + sel)) + defi)), comme specifie."""
    secret = base64.b64encode(
        hashlib.sha256((mot_de_passe + sel).encode("utf-8")).digest()).decode("ascii")
    return base64.b64encode(
        hashlib.sha256((secret + defi).encode("utf-8")).digest()).decode("ascii")


def _identifier(ws: _WebSocket, mot_de_passe: str):
    """Attend Hello, repond Identify, attend Identified."""
    while True:
        msg = json.loads(ws.recevoir())
        if msg.get("op") == OBS_HELLO:
            break

    d = msg.get("d") or {}
    donnees = {"rpcVersion": 1, "eventSubscriptions": OBS_SUBSCRIPTIONS}
    auth = d.get("authentication")
    if auth:
        if not mot_de_passe:
            # Message actionnable : sans ca l'utilisateur voit une connexion qui
            # echoue en boucle sans savoir qu'il lui manque juste le mot de passe.
            raise ConnectionError(
                "OBS demande un mot de passe (Outils ▸ Parametres du serveur WebSocket)")
        donnees["authentication"] = _chaine_auth(
            mot_de_passe, auth.get("salt", ""), auth.get("challenge", ""))

    ws.envoyer_json(OBS_IDENTIFY, donnees)

    while True:
        msg = json.loads(ws.recevoir())
        if msg.get("op") == OBS_IDENTIFIED:
            return


def _scenes_depuis(charge: dict) -> list:
    """Normalise une liste de scenes OBS en [{'name', 'index'}, ...].

    Triees par index DECROISSANT : obs-websocket numerote la scene du bas de la
    liste a 0, donc l'ordre decroissant est celui que l'utilisateur a sous les
    yeux dans OBS. Retrouver ses scenes dans le meme ordre des deux cotes evite
    de patcher la mauvaise ligne.
    """
    out = []
    for s in (charge.get("scenes") or []):
        nom = s.get("sceneName")
        if not nom:
            continue
        try:
            idx = int(s.get("sceneIndex", 0))
        except (TypeError, ValueError):
            idx = 0
        out.append({"name": str(nom), "index": idx})
    out.sort(key=lambda d: -d["index"])
    return out


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class ObsClient(QObject):
    """Connexion persistante a OBS, avec reconnexion automatique.

    Les Signals sont emis depuis le thread reseau ; Qt les delivre dans le
    thread principal (connexion automatique = Queued des que les threads
    different). Aucun widget, aucun projecteur n'est donc touche depuis le
    reseau — c'est la seule facon de ne pas voler d'images a la trame DMX.
    """

    # (connecte, message affichable)
    connection_changed = Signal(bool, str)
    # [{'name', 'index'}, ...]
    scenes_changed     = Signal(list)
    # Nom de la scene qui VIENT de passer au programme
    program_scene      = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = "127.0.0.1"
        self._port = OBS_WS_PORT
        self._mdp = ""
        self._thread = None
        self._stop = threading.Event()
        self._ws = None
        self._scenes = []
        self._derniere_scene = None
        self._connected = False

    # ── cycle de vie ────────────────────────────────────────────────────────

    def start(self, host: str = "127.0.0.1", port: int = OBS_WS_PORT, password: str = ""):
        self.stop()
        self._host, self._port, self._mdp = host, int(port), password or ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="obs-ws")
        self._thread.start()

    def stop(self):
        self._stop.set()
        # Fermer la socket SOUS le thread : recevoir() est bloquant sans delai,
        # sans ca la fermeture de MyStrow attendrait le prochain evenement OBS,
        # c'est-a-dire potentiellement jamais.
        ws, self._ws = self._ws, None
        if ws is not None:
            ws.fermer()
        t, self._thread = self._thread, None
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        if self._connected:
            self._connected = False
            self.connection_changed.emit(False, "Deconnecte")

    def is_connected(self) -> bool:
        return self._connected

    def scenes(self) -> list:
        return list(self._scenes)

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
            # Reconnexion a delai croissant, plafonnee : OBS ferme pendant le
            # montage ne doit pas marteler le reseau pendant des heures.
            if self._stop.wait(attente):
                break
            attente = min(attente * 2, 15.0)

    def _session(self):
        ws = _WebSocket.connect(self._host, self._port, timeout=5.0)
        self._ws = ws
        try:
            # Delai pendant la negociation : un serveur qui accepte la socket
            # sans jamais parler ne doit pas retenir le thread indefiniment.
            _identifier(ws, self._mdp)
            ws.regler_timeout(None)    # ensuite on attend les evenements sans limite

            self._connected = True
            self._derniere_scene = None
            self.connection_changed.emit(True, f"Connecte a {self._host}:{self._port}")

            ws.envoyer_json(OBS_REQUEST, {
                "requestType": "GetSceneList", "requestId": "scenes"})

            while not self._stop.is_set():
                self._traiter(json.loads(ws.recevoir()))
        finally:
            self._ws = None
            ws.fermer()

    # ── traitement des messages ─────────────────────────────────────────────

    def _traiter(self, msg: dict):
        op, d = msg.get("op"), (msg.get("d") or {})

        if op == OBS_RESPONSE:
            if d.get("requestType") == "GetSceneList":
                self._on_scenes(_scenes_depuis(d.get("responseData") or {}))
                courante = (d.get("responseData") or {}).get("currentProgramSceneName")
                if courante:
                    # Etat initial memorise SANS declencher : se connecter en
                    # plein direct ne doit pas rejouer la memoire de la scene
                    # deja a l'antenne, ce qui ecraserait l'etat en cours.
                    self._derniere_scene = str(courante)

        elif op == OBS_EVENT:
            t = d.get("eventType")
            ed = d.get("eventData") or {}
            if t == "CurrentProgramSceneChanged":
                self._on_program(ed.get("sceneName"))
            elif t == "SceneListChanged":
                self._on_scenes(_scenes_depuis(ed))
            elif t == "SceneNameChanged":
                # Renommer une scene change la CLE de correspondance : on
                # rafraichit la liste pour que le dialogue le refletent.
                ws = self._ws
                if ws is not None:
                    ws.envoyer_json(OBS_REQUEST, {
                        "requestType": "GetSceneList", "requestId": "scenes"})

    def _on_scenes(self, scenes: list):
        if scenes and scenes != self._scenes:
            self._scenes = scenes
            self.scenes_changed.emit(list(scenes))

    def _on_program(self, nom):
        """Front montant. OBS n'emet cet evenement que sur changement reel,
        mais on garde la garde : une reconnexion, ou un futur evenement de
        rafraichissement, republierait la scene courante — et rejouerait la
        memoire lumiere en plein milieu d'un plan."""
        if not nom:
            return
        nom = str(nom)
        if nom == self._derniere_scene:
            return
        self._derniere_scene = nom
        self.program_scene.emit(nom)


# ---------------------------------------------------------------------------
# Interrogation ponctuelle (dialogue de configuration)
# ---------------------------------------------------------------------------

def query_scenes(host: str, port: int = OBS_WS_PORT, password: str = "",
                 timeout: float = 4.0) -> list:
    """Ouvre une connexion courte et renvoie la liste des scenes.

    Utilise par le bouton « Tester la connexion » : on veut une reponse
    immediate et un echec franc, pas la boucle de reconnexion du client.
    Leve une exception explicite en cas d'echec.
    """
    ws = _WebSocket.connect(host, port, timeout=timeout)
    try:
        ws.regler_timeout(timeout)
        _identifier(ws, password or "")
        ws.envoyer_json(OBS_REQUEST, {"requestType": "GetSceneList", "requestId": "test"})
        # Quelques messages de tolerance : des evenements peuvent s'intercaler
        # entre notre requete et sa reponse.
        for _ in range(20):
            msg = json.loads(ws.recevoir())
            d = msg.get("d") or {}
            if msg.get("op") == OBS_RESPONSE and d.get("requestType") == "GetSceneList":
                etat = d.get("requestStatus") or {}
                if not etat.get("result", False):
                    raise ConnectionError(
                        etat.get("comment") or "OBS a refuse la requete")
                return _scenes_depuis(d.get("responseData") or {})
        raise ConnectionError("OBS n'a pas renvoye sa liste de scenes")
    finally:
        ws.fermer()
