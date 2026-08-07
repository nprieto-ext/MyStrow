"""diag_obs.py — Que repond vraiment le port sur lequel MyStrow cherche OBS ?

A lancer quand la connexion OBS echoue sans qu'on sache pourquoi :

    python diag_obs.py                          (127.0.0.1:4455, defaut)
    python diag_obs.py 192.168.1.20 4455
    python diag_obs.py 127.0.0.1 4455 MonMotDePasse   (teste l'authentification)

Le script n'utilise QUE la bibliotheque standard : il ne charge ni Qt ni le
reste de MyStrow, donc il tourne meme quand l'application ne demarre pas. Il
affiche la reponse HTTP BRUTE du serveur, ce qui est la seule facon de
distinguer les trois causes qui donnent toutes « poignee de main invalide » :
obs-websocket absent, autre logiciel sur le port, ou intermediaire (antivirus,
proxy) qui reecrit la negociation.
"""
import base64
import hashlib
import os
import socket
import subprocess
import sys

# Constante normative du RFC 6455. Le script la redefinit au lieu d'importer
# celle d'obs_client : c'est justement une erreur SUR cette constante qui a
# motive ce diagnostic, et un outil qui partage la valeur suspecte ne peut
# pas la mettre en cause.
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
assert base64.b64encode(hashlib.sha1(
    ("dGhlIHNhbXBsZSBub25jZQ==" + GUID).encode()).digest()
).decode() == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", "GUID corrompu"


def _qui_ecoute(port: int):
    """Nom du processus qui detient le port en ecoute (Windows), ou None.

    C'est le seul test qui separe vraiment « obs-websocket repond mal » de
    « un logiciel s'est mis devant » : un proxy qui s'intercale relaie le
    Server: du vrai serveur, donc cet en-tete ne prouve RIEN sur l'identite
    de ce qui repond. Le proprietaire de la socket, lui, ne ment pas.
    """
    if not sys.platform.startswith("win"):
        return None
    # Sortie lue en OCTETS puis decodee en latin-1 : netstat et tasklist
    # ecrivent dans la page de code OEM de la console, que le decodeur cp1252
    # par defaut de subprocess refuse. En texte, le script mourait avant meme
    # d'avoir teste la connexion.
    def _run(cmd):
        return subprocess.run(cmd, capture_output=True, timeout=15
                              ).stdout.decode("latin-1", "replace")

    try:
        sortie = _run(["netstat", "-ano", "-p", "TCP"])
    except Exception:
        return None
    pids = []
    for ligne in sortie.splitlines():
        ch = ligne.split()
        if len(ch) >= 5 and ch[3].upper() == "LISTENING" and ch[1].endswith(f":{port}"):
            pids.append(ch[4])
    if not pids:
        return None
    noms = []
    for pid in dict.fromkeys(pids):
        try:
            t = _run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"]).strip()
            nom = t.split(",")[0].strip('"') if "," in t else t
        except Exception:
            nom = "?"
        noms.append(f"{nom} (PID {pid})")
    return ", ".join(noms)


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 4455
    print(f"--- Cible : {host}:{port}\n")

    if host in ("127.0.0.1", "localhost", "::1"):
        proprio = _qui_ecoute(port)
        if proprio:
            print(f"[i] Processus qui ecoute sur le port {port} : {proprio}")
            if "obs" not in proprio.lower():
                print("    -> Ce n'est PAS OBS. Un autre logiciel occupe le port")
                print("       ou s'intercale devant lui.")
        else:
            print(f"[i] Aucun processus en ecoute sur le port {port} localement.")
        print()

    # 1. La socket s'ouvre-t-elle ?
    try:
        sock = socket.create_connection((host, port), timeout=5.0)
    except OSError as exc:
        code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
        print(f"[X] Connexion TCP impossible : {exc}")
        if code in (10061, 111):
            print("    -> Rien n'ecoute. OBS ferme, serveur WebSocket non active,")
            print("       ou mauvais port.")
        elif code in (10060, 110):
            print("    -> Pas de reponse. Machine injoignable ou pare-feu.")
        return 1
    print("[OK] Socket TCP ouverte.")

    # 2. Negociation WebSocket, en affichant la reponse telle quelle.
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
    sock.sendall(requete.encode("ascii"))

    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            bloc = sock.recv(65536)
            if not bloc:
                break
            buf += bloc
    except OSError as exc:
        print(f"[X] Rien recu : {exc}")
        return 1

    entete = buf.split(b"\r\n\r\n")[0].decode("latin-1", "replace")
    print("\n--- Reponse brute du serveur ---")
    print(entete or "(vide)")
    print("--- fin ---\n")

    if not entete:
        print("[X] Le serveur a accepte la socket puis n'a rien dit.")
        print("    -> Ce n'est pas obs-websocket.")
        return 1

    lignes = entete.split("\r\n")
    if "101" not in lignes[0]:
        print(f"[X] Statut inattendu : {lignes[0]}")
        print("    -> Le serveur WebSocket d'OBS n'est pas actif, ou un autre")
        print("       logiciel occupe ce port.")
        return 1

    attendu = base64.b64encode(
        hashlib.sha1((cle + GUID).encode("ascii")).digest()).decode("ascii")
    recu = ""
    for ligne in lignes[1:]:
        nom, sep, val = ligne.partition(":")
        if sep and nom.strip().lower() == "sec-websocket-accept":
            recu = val.strip()

    if not recu:
        print("[X] 101 mais AUCUN en-tete Sec-WebSocket-Accept.")
        print("    -> En face ce n'est pas un vrai serveur WebSocket, ou un")
        print("       antivirus / proxy a reecrit la reponse.")
        return 1
    if recu != attendu:
        print("[X] Sec-WebSocket-Accept incorrect.")
        print(f"    cle envoyee : {cle}")
        print(f"    recu        : {recu}")
        print(f"    attendu     : {attendu}")
        print("    -> La reponse a ete calculee a partir d'une AUTRE cle que la")
        print("       notre : quelque chose a rejoue la negociation entre")
        print("       MyStrow et OBS (antivirus a inspection reseau, proxy,")
        print("       pare-feu applicatif). L'en-tete Server: ne prouve rien,")
        print("       un relais recopie celui du vrai serveur.")
        print("       Verifiez la ligne [i] en haut : si le processus qui")
        print("       ecoute n'est pas obs64.exe, c'est lui le coupable.")
        return 1

    print("[OK] Poignee de main WebSocket valide — la couche reseau est saine.\n")

    # ── Etape 3 : Hello + authentification ──────────────────────────────────
    # Seuls les octets QUI SUIVENT les en-tetes : OBS envoie son Hello dans le
    # meme paquet TCP, il est donc deja dans `buf`. Repartir de `buf` entier
    # ferait lire « HTTP/1.1... » comme une trame WebSocket.
    reste = buf.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in buf else b""
    mdp = sys.argv[3] if len(sys.argv) > 3 else None
    code = _authentifier(sock, reste, mdp)
    sock.close()
    return code


def _trame_texte(charge: bytes) -> bytes:
    """Trame texte MASQUEE — un serveur conforme coupe si le client ne masque pas."""
    masque = os.urandom(4)
    corps = bytes(o ^ masque[i % 4] for i, o in enumerate(charge))
    n = len(charge)
    if n < 126:
        tete = bytes([0x81, 0x80 | n])
    elif n < 65536:
        tete = bytes([0x81, 0x80 | 126, n >> 8, n & 0xFF])
    else:
        tete = bytes([0x81, 0x80 | 127]) + n.to_bytes(8, "big")
    return tete + masque + corps


def _lire_trame_texte(sock, buf: bytes):
    """Renvoie (charge_utile, reste_du_tampon). Trames serveur : jamais masquees."""
    def rempli(b, n):
        while len(b) < n:
            bloc = sock.recv(65536)
            if not bloc:
                raise ConnectionError("connexion fermee par OBS")
            b += bloc
        return b

    buf = rempli(buf, 2)
    opcode = buf[0] & 0x0F
    taille = buf[1] & 0x7F
    pos = 2
    if taille == 126:
        buf = rempli(buf, 4)
        taille = int.from_bytes(buf[2:4], "big"); pos = 4
    elif taille == 127:
        buf = rempli(buf, 10)
        taille = int.from_bytes(buf[2:10], "big"); pos = 10
    buf = rempli(buf, pos + taille)
    return opcode, buf[pos:pos + taille], buf[pos + taille:]


def _authentifier(sock, buf: bytes, mdp):
    import json

    opcode, charge, buf = _lire_trame_texte(sock, buf)
    if opcode == 0x8:
        code = int.from_bytes(charge[:2], "big") if len(charge) >= 2 else 0
        print(f"[X] OBS a ferme aussitot (code {code}).")
        return 1
    hello = json.loads(charge.decode("utf-8"))
    d = hello.get("d") or {}
    print(f"[OK] Hello recu — obs-websocket {d.get('obsWebSocketVersion', '?')}, "
          f"rpc {d.get('rpcVersion', '?')}")

    auth = d.get("authentication")
    if not auth:
        print("[i] OBS ne demande AUCUN mot de passe (authentification decochee).")
        print("    -> Laissez le champ vide dans MyStrow. S'il contient quelque")
        print("       chose, ce n'est pas la cause de l'echec.")
        return 0

    print("[i] OBS exige un mot de passe.")
    if mdp is None:
        print("    Relancez avec le mot de passe pour le tester :")
        print("       python diag_obs.py 127.0.0.1 4455 VotreMotDePasse")
        return 1

    # Les deux pieges de copier-coller, verifies AVANT de conclure « refuse » :
    # un espace ou un saut de ligne accroche a la selection change le hachage,
    # et rien a l'ecran ne le montre puisque le champ affiche des points.
    if mdp != mdp.strip():
        print(f"    /!\\ Le mot de passe fourni a des espaces au debut ou a la fin "
              f"({len(mdp) - len(mdp.strip())} caractere(s)).")
    if any(ord(c) > 126 for c in mdp):
        print("    /!\\ Le mot de passe contient des caracteres non ASCII.")
    print(f"    Longueur : {len(mdp)} caracteres.")

    secret = base64.b64encode(
        hashlib.sha256((mdp + auth.get("salt", "")).encode("utf-8")).digest()).decode()
    reponse = base64.b64encode(
        hashlib.sha256((secret + auth.get("challenge", "")).encode("utf-8")).digest()).decode()

    sock.sendall(_trame_texte(json.dumps({
        "op": 1, "d": {"rpcVersion": 1, "eventSubscriptions": 5,
                       "authentication": reponse}}).encode("utf-8")))

    try:
        opcode, charge, buf = _lire_trame_texte(sock, buf)
    except ConnectionError as exc:
        print(f"[X] {exc}")
        return 1

    if opcode == 0x8:
        code = int.from_bytes(charge[:2], "big") if len(charge) >= 2 else 0
        raison = charge[2:].decode("utf-8", "replace")
        if code == 4009:
            print(f"[X] Mot de passe REFUSE par OBS (code 4009 {raison}).")
            print("    -> Le protocole est bon, c'est bien la valeur qui ne")
            print("       correspond pas. Dans OBS : Outils > Parametres du")
            print("       serveur WebSocket > Afficher les informations de")
            print("       connexion, et recopiez le mot de passe SANS espace.")
            print("       Si vous venez de le changer, cliquez Appliquer : OBS")
            print("       garde l'ancien tant que ce n'est pas valide.")
        else:
            print(f"[X] OBS a ferme la session (code {code} {raison}).")
        return 1

    msg = json.loads(charge.decode("utf-8"))
    if msg.get("op") == 2:
        print("[OK] MOT DE PASSE ACCEPTE — session identifiee.")
        print("     La liaison OBS de MyStrow doit fonctionner avec ces valeurs.")
        return 0
    print(f"[?] Reponse inattendue : {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
