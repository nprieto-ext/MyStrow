"""
Serveur local HTTP pour le contrôleur tablette MyStrow.
Protocole : Flask + Server-Sent Events (SSE) — aucune dépendance JS externe.

La tablette se connecte via : http://<IP_LOCAL>:5000
"""
import hashlib
import hmac
import os
import secrets
import threading
import time
import queue
import socket
import json
from pathlib import Path

# ── Dépendances optionnelles (auto-install si absent) ────────────────────────
_flask_available = False
Flask = None
Response = None
request_ctx = None
send_file_fn = None

def _try_import() -> bool:
    global _flask_available, Flask, Response, request_ctx, send_file_fn
    try:
        from flask import Flask as _F, Response as _R, request as _req, send_file as _sf
        Flask        = _F
        Response     = _R
        request_ctx  = _req
        send_file_fn = _sf
        _flask_available = True
        return True
    except ImportError:
        return False

def _auto_install() -> bool:
    import sys
    if getattr(sys, 'frozen', False):
        # App PyInstaller : pip non disponible, Flask doit être bundlé dans le .spec
        return _try_import()
    import subprocess
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "flask", "qrcode", "waitress"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return _try_import()
    except Exception:
        return False

_try_import()

TABLET_PORT = 5000

# Version du protocole tablette <-> PC. L'app des stores la lit dans /whoami
# pour reconnaître un MyStrow trop ancien ou trop récent. À incrémenter à chaque
# changement incompatible des messages SSE ou des routes /api/*.
PROTOCOL_VERSION = 1

# ── Appairage ────────────────────────────────────────────────────────────────
# Sans appairage, n'importe quel appareil du réseau pilotait les lumières. Un
# code à 6 chiffres (affiché dans « Entrée externe » et inclus dans le QR code)
# s'échange UNE fois contre un jeton permanent propre à l'appareil ; seul le
# hash du jeton est stocké sur le PC. Les requêtes venues du PC lui-même
# (diagnostic tablette) restent libres.
_DEVICES_FILE = Path.home() / ".mystrow_tablet_devices.json"
_pair_lock = threading.Lock()
_pair_code = ""
_pair_fails = 0
_pair_locked_until = 0.0
_PAIR_MAX_FAILS = 5   # codes faux d'affilée avant blocage
_PAIR_LOCK_S = 30     # durée du blocage → au plus ~10 essais/min sur 1 000 000 codes


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_devices() -> list:
    try:
        data = json.loads(_DEVICES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[Tablet] Lecture des appareils appairés impossible : {e}")
        return []
    devs = data.get("devices", []) if isinstance(data, dict) else []
    return [d for d in devs if isinstance(d, dict) and d.get("token_sha256")]


def _save_devices(devices: list):
    tmp = _DEVICES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"devices": devices}, indent=1), encoding="utf-8")
    os.replace(tmp, _DEVICES_FILE)


_devices: list = _load_devices()


def pairing_code() -> str:
    """Code en cours (stable tant qu'on ne le change pas : le QR affiché reste valable)."""
    global _pair_code
    with _pair_lock:
        if not _pair_code:
            _pair_code = f"{secrets.randbelow(1_000_000):06d}"
        return _pair_code


def new_pairing_code() -> str:
    global _pair_code
    with _pair_lock:
        _pair_code = ""
    return pairing_code()


def paired_devices() -> list:
    with _pair_lock:
        return [{k: d.get(k) for k in ("id", "name", "created", "last_seen")}
                for d in _devices]


def forget_devices():
    """Révoque TOUS les appareils (chacun devra saisir le nouveau code) et
    coupe les flux ouverts, sinon une tablette déjà connectée garderait la main."""
    global _devices
    with _pair_lock:
        _devices = []
        try:
            _save_devices(_devices)
        except Exception as e:
            print(f"[Tablet] Enregistrement des appareils impossible : {e}")
    new_pairing_code()
    with _clients_lock:
        for q in list(_clients):
            try:
                q.put_nowait(None)
            except Exception:
                pass


def _device_for_token(token: str):
    if not token:
        return None
    h = _hash_token(token)
    with _pair_lock:
        for d in _devices:
            if hmac.compare_digest(str(d.get("token_sha256", "")), h):
                return d
    return None


def _try_pair(code, name):
    """→ (jeton, None) si le code est bon, sinon (None, (statut HTTP, erreur, attente s))."""
    global _pair_fails, _pair_locked_until
    expected = pairing_code()
    now = time.time()
    with _pair_lock:
        if now < _pair_locked_until:
            return None, (429, "locked", int(_pair_locked_until - now) + 1)
        digits = "".join(ch for ch in str(code or "") if ch in "0123456789")
        if not hmac.compare_digest(digits, expected):
            _pair_fails += 1
            if _pair_fails >= _PAIR_MAX_FAILS:
                _pair_fails = 0
                _pair_locked_until = now + _PAIR_LOCK_S
                return None, (429, "locked", _PAIR_LOCK_S)
            return None, (403, "bad_code", 0)
        _pair_fails = 0
        token = secrets.token_urlsafe(32)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        _devices.append({"id": secrets.token_hex(4),
                         "name": str(name or "").strip()[:60] or "Tablette",
                         "token_sha256": _hash_token(token),
                         "created": stamp, "last_seen": stamp})
        try:
            _save_devices(_devices)
        except Exception as e:
            print(f"[Tablet] Enregistrement des appareils impossible : {e}")
        return token, None


_local_ip_cache = ["", 0.0]


def _is_local_request(addr: str) -> bool:
    """La requête vient-elle de CE PC ? (IP réseau mise en cache 30 s : un fader
    envoie des dizaines d'events par seconde)."""
    addr = (addr or "").replace("::ffff:", "")
    if addr in ("127.0.0.1", "::1"):
        return True
    if time.time() - _local_ip_cache[1] > 30:
        _local_ip_cache[0] = get_local_ip()
        _local_ip_cache[1] = time.time()
    return bool(_local_ip_cache[0]) and addr == _local_ip_cache[0]

# ── Queue thread-safe : events tablette → Qt ─────────────────────────────────
event_queue: queue.Queue = queue.Queue()

# ── État courant ──────────────────────────────────────────────────────────────
_state: dict = {
    "pads":    {},   # "{r}_{c}" → {"color": "#rrggbb", "bright": 100}
    "faders":  {},   # "0"–"8"  → int 0-100
    "effects": {},   # "0"–"7"  → bool
    "seq": {
        "current_row": -1,
        "playing": False,
        "items": [],   # [{"title": str, "type": "media"|"pause"|"tempo"}]
    },
    "carts": [
        {"title": "", "state": 0},   # 0=idle 1=playing 2=stopped
        {"title": "", "state": 0},
        {"title": "", "state": 0},
        {"title": "", "state": 0},
    ],
    "projectors": [],  # [{"name","group","color","level","muted","x","y"}]
    "layout": [],       # [{"label": "A", "type": "group"}, ...]  — 8 colonnes AKAI
    "rec_active": False,
    # Surface d'exécuteurs (fenêtre EXT « surface pad ») reflétée sur la tablette.
    "surface": {"blocks": [], "cols": 0, "rows": 0},
}

# ── Clients SSE connectés ─────────────────────────────────────────────────────
# Taille max de la file d'un client SSE. ~200 events = quelques secondes de
# retard tolerees ; au-dela le client est considere mort et evince.
_CLIENT_QUEUE_MAX = 200
_clients: list = []
_clients_lock = threading.Lock()

_app    = None
_thread = None
_running = False
last_error = ""   # derniere erreur du serveur (bind refuse, crash...)
_bound_port = None  # port reellement ouvert par le thread serveur


# ── Construction Flask ────────────────────────────────────────────────────────
def _build_app():
    global _app
    _app = Flask(__name__, static_folder=None)

    # Base des fichiers statiques. En exe PyInstaller (onefile), les datas sont
    # extraites dans sys._MEIPASS ; en dev, c'est le dossier du module.
    import sys as _sys
    if getattr(_sys, 'frozen', False) and hasattr(_sys, '_MEIPASS'):
        _BASE = Path(_sys._MEIPASS)
    else:
        _BASE = Path(__file__).parent

    def _serve_bytes(relpath, mimetype):
        """Sert un fichier statique en lisant ses octets directement.

        On N'UTILISE PAS send_file : sous waitress (serveur de prod par défaut),
        son wrapper de fichier WSGI (wsgi.file_wrapper) échoue de façon fiable sur
        les fichiers du sous-dossier tablet/ → « Internal Server Error » (500) côté
        tablette, alors que test_client/Flask-dev passaient. Lire les octets et les
        renvoyer dans une Response est robuste sur les deux serveurs. Les assets
        sont petits (HTML/JSON/JS), le coût mémoire est négligeable."""
        try:
            data = (_BASE / relpath).read_bytes()
        except Exception as e:
            print(f"[Tablet] Fichier introuvable: {relpath} ({e})")
            return Response(f"Not found: {relpath}", status=404)
        return Response(data, mimetype=mimetype)

    @_app.route("/")
    def index():
        # mimetype "text/html" seul : Flask ajoute automatiquement "; charset=utf-8".
        return _serve_bytes("tablet/index.html", "text/html")

    @_app.route("/manifest.json")
    def manifest():
        return _serve_bytes("tablet/manifest.json", "application/manifest+json")

    @_app.route("/sw.js")
    def service_worker():
        resp = _serve_bytes("tablet/sw.js", "application/javascript")
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # Polices du site (Bebas Neue, Barlow Condensed) EMBARQUÉES : la tablette est
    # souvent sur un réseau lumière sans Internet → Google Fonts injoignable.
    # Liste blanche : pas de chemin arbitraire lu sur le disque.
    _FONT_FILES = ("bebas-neue.woff2", "barlow-condensed-600.woff2", "barlow-condensed-700.woff2")

    @_app.route("/fonts/<name>")
    def fonts(name):
        if name not in _FONT_FILES:
            return Response("Not found", status=404)
        resp = _serve_bytes(f"tablet/fonts/{name}", "font/woff2")
        resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp

    @_app.route("/icon.png")
    def icon():
        return _serve_bytes("logo.png", "image/png")

    # ── Accès : appairage + CORS ──────────────────────────────────────────────
    def _request_token() -> str:
        auth = request_ctx.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        # EventSource ne sait pas poser d'en-tête : le jeton passe en paramètre.
        return request_ctx.args.get("t", "")

    def _authorized() -> bool:
        return (_is_local_request(request_ctx.remote_addr)
                or _device_for_token(_request_token()) is not None)

    def _json(obj, status=200):
        return Response(json.dumps(obj), status=status, mimetype="application/json")

    def _unauthorized():
        return _json({"error": "pairing_required"}, 401)

    @_app.after_request
    def _cors(resp):
        # L'app des stores charge l'interface depuis sa propre origine
        # (https://localhost, capacitor://localhost) : sans ces en-têtes, la
        # WebView refuse ses appels vers le PC. Aucun cookie : l'accès repose sur
        # le jeton, « * » n'ouvre donc rien de plus.
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp

    @_app.route("/api/pair", methods=["POST"])
    def api_pair():
        data = request_ctx.get_json(force=True, silent=True) or {}
        token, err = _try_pair(data.get("code", ""), data.get("name", ""))
        if token:
            return _json({"token": token, "proto": PROTOCOL_VERSION})
        status, code, wait = err
        return _json({"error": code, "retry_in": wait}, status)

    @_app.route("/api/session")
    def api_session():
        if not _authorized():
            return _unauthorized()
        return _json({"ok": True, "proto": PROTOCOL_VERSION})

    @_app.route("/whoami")
    def whoami():
        """Signature du serveur — permet de verifier que c'est bien MyStrow qui
        repond sur ce port, et pas un autre logiciel qui l'occupait deja (sur
        Mac, le « Recepteur AirPlay » squatte le port 5000 et renvoie 403/401)."""
        return Response(
            json.dumps({"app": "MyStrow", "role": "tablet", "port": TABLET_PORT,
                        "proto": PROTOCOL_VERSION, "name": socket.gethostname(),
                        "pairing": True}),
            mimetype="application/json",
        )

    @_app.route("/stream")
    def stream():
        """Server-Sent Events : pousse les mises à jour en temps réel."""
        if not _authorized():
            return _unauthorized()
        # File BORNEE : un client qui ne consomme plus (tablette en veille,
        # Wi-Fi coupe, connexion de test laissee ouverte par le diagnostic)
        # faisait gonfler sa file sans aucune limite, alimentee par les
        # pushs continus de l'appli. Memoire en croissance permanente
        # jusqu'au plantage. Plein = client mort, on l'evince (_broadcast).
        client_q: queue.Queue = queue.Queue(maxsize=_CLIENT_QUEUE_MAX)
        with _clients_lock:
            _clients.append(client_q)

        def generate():
            # Sync d'état initial
            yield f"data: {json.dumps({'type': 'state', 'data': _state})}\n\n"
            while True:
                try:
                    event = client_q.get(timeout=5)
                    if event is None:       # signal de fermeture
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"    # garde la connexion vivante
                except GeneratorExit:
                    break

        def cleanup(resp):
            # Signaler au générateur de s'arrêter + retirer de la liste
            client_q.put(None)
            with _clients_lock:
                if client_q in _clients:
                    _clients.remove(client_q)
            return resp

        resp = Response(
            generate(),
            content_type="text/event-stream",
            headers={
                "Cache-Control":    "no-cache",
                "X-Accel-Buffering":"no",
                # NE PAS poser "Connection": c'est un header « hop-by-hop »
                # interdit à une app WSGI (PEP 3333). Waitress (serveur utilisé
                # dans l'exe gelé) applique la règle strictement et lève une
                # AssertionError → /stream renvoie 500 → tout le flux SSE
                # desktop→tablette meurt (projos/playlist/surface/couleurs muets)
                # alors que /api/event (POST) marche encore. Le serveur de dev de
                # Flask, lui, tolère ce header — d'où « OK en Python, KO en exe ».
                # Le serveur gère la persistance de connexion lui-même.
            },
        )
        resp.call_on_close(lambda: cleanup(None))
        return resp

    @_app.route("/api/event", methods=["POST"])
    def api_event():
        """Reçoit les actions de la tablette (pad, fader, effect)."""
        if not _authorized():
            return _unauthorized()
        try:
            data = request_ctx.get_json(force=True) or {}
            event_queue.put(data)
        except Exception:
            pass
        return "", 204

    @_app.route("/ping")
    def ping():
        return "OK", 200


# ── API publique : Qt → Tablette ──────────────────────────────────────────────
def _broadcast(event: dict):
    """Envoie un event SSE à tous les clients connectés.

    Un client dont la file est PLEINE ne consomme plus : il est evince. Sans
    ca, une connexion morte restait inscrite indefiniment — le diagnostic
    tablette en laissait justement une derriere lui a chaque execution — et
    chaque push de l'appli empilait un event de plus dans une file que
    personne ne vidait."""
    with _clients_lock:
        morts = []
        for q in _clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                morts.append(q)
        for q in morts:
            try:
                _clients.remove(q)
            except ValueError:
                pass
        if morts:
            print(f"[Tablet] {len(morts)} client(s) SSE inactif(s) evince(s)")


def push_pad(row: int, col: int, color_hex: str, bright: int):
    key = f"{row}_{col}"
    _state["pads"][key] = {"color": color_hex, "bright": bright}
    if _running:
        _broadcast({"type": "pad", "row": row, "col": col,
                    "color": color_hex, "bright": bright})


def push_fader(idx: int, value: int):
    _state["faders"][str(idx)] = value
    if _running:
        _broadcast({"type": "fader", "idx": idx, "value": value})


def push_effect(row: int, active: bool):
    _state["effects"][str(row)] = active
    if _running:
        _broadcast({"type": "effect", "row": row, "active": active})


def push_seq(current_row: int, items: list, playing: bool):
    _state["seq"]["current_row"] = current_row
    _state["seq"]["playing"]     = playing
    _state["seq"]["items"]       = items
    if _running:
        _broadcast({"type": "seq", "current_row": current_row,
                    "playing": playing, "items": items})


def push_seq_row(current_row: int, playing: bool):
    _state["seq"]["current_row"] = current_row
    _state["seq"]["playing"]     = playing
    if _running:
        _broadcast({"type": "seq_row", "current_row": current_row,
                    "playing": playing})


def push_layout(slots: list):
    """Pousse les labels des 8 colonnes AKAI (après changement de layout)."""
    labels = [{"label": s.get("label", f"G{i+1}"), "type": s.get("type", "group")}
              for i, s in enumerate(slots)]
    _state["layout"] = labels
    if _running:
        _broadcast({"type": "layout", "labels": labels})


def push_bank_pages(count: int, index: int):
    """Pousse le nombre de pages de layout et l'index courant (navigateur ◀ ▶)."""
    _state["bank_pages"] = {"count": count, "index": index}
    if _running:
        _broadcast({"type": "bank_pages", "count": count, "index": index})


def push_rec_state(active: bool):
    """Pousse l'état du mode REC mémoire."""
    _state["rec_active"] = active
    if _running:
        _broadcast({"type": "rec_state", "active": active})


def push_surface(data: dict):
    """Pousse le layout de la surface d'exécuteurs (blocs + dimensions de grille)."""
    _state["surface"] = data or {"blocks": [], "cols": 0, "rows": 0}
    if _running:
        _broadcast({"type": "surface", "data": _state["surface"]})


def push_projectors(projectors: list):
    _state["projectors"] = projectors
    if _running:
        _broadcast({"type": "projectors", "data": projectors})


def push_projectors_colors(projectors: list):
    """Mise à jour légère : uniquement les couleurs/niveaux/strobe."""
    for i, p in enumerate(projectors):
        if i < len(_state["projectors"]):
            _state["projectors"][i]["color"]      = p["color"]
            _state["projectors"][i]["base_color"] = p.get("base_color", "#ffffff")
            _state["projectors"][i]["level"]      = p["level"]
            _state["projectors"][i]["muted"]      = p["muted"]
            # Allumage réel (overrides HTP inclus) : sans lui, un client qui se
            # (re)connecte en pleine mémoire lumière recevrait une scène éteinte.
            _state["projectors"][i]["lit"]        = p.get("lit", False)
            _state["projectors"][i]["strobe"]     = p.get("strobe", 0)
            _state["projectors"][i]["pan"]        = p.get("pan", 32768)
            _state["projectors"][i]["tilt"]       = p.get("tilt", 32768)
            _state["projectors"][i]["gobo"]        = p.get("gobo", 0)
            _state["projectors"][i]["color_wheel"] = p.get("color_wheel", 0)
    if _running:
        _broadcast({"type": "proj_colors", "data": projectors})


def push_cart(idx: int, title: str, state: int):
    _state["carts"][idx] = {"title": title, "state": state}
    if _running:
        _broadcast({"type": "cart", "idx": idx, "title": title, "state": state})


# ── Utilitaires ───────────────────────────────────────────────────────────────
def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def make_qr_png_path(url: str) -> str | None:
    """Génère un QR code PNG dans un fichier temporaire. Retourne le chemin."""
    try:
        import qrcode as _qr, tempfile, os
        img = _qr.make(url)
        path = os.path.join(tempfile.gettempdir(), "mystrow_tablet_qr.png")
        img.save(path)
        return path
    except Exception as e:
        print(f"[Tablet] QR error: {e}")
        return None


def is_available() -> bool:
    return _flask_available


def is_running() -> bool:
    return _running


# ── Démarrage ─────────────────────────────────────────────────────────────────
# ── Découverte Bonjour (mDNS) ────────────────────────────────────────────────
# L'app des stores trouve le PC sans QR code ni IP à taper. Bonjour plutôt
# qu'une diffusion UDP maison : l'iPad le parcourt avec la seule autorisation
# « réseau local », sans l'entitlement multicast qu'Apple doit accorder.
MDNS_SERVICE_TYPE = "_mystrow._tcp.local."
_zc = None
_zc_info = None


def _lan_ipv4s() -> list:
    ips = []
    try:
        import ifaddr
        for adapter in ifaddr.get_adapters():
            for a in adapter.ips:
                if isinstance(a.ip, str) and not a.ip.startswith(("127.", "169.254.")):
                    if a.ip not in ips:
                        ips.append(a.ip)
    except Exception:
        pass
    ip = get_local_ip()
    if ip and ip != "127.0.0.1":
        if ip in ips:
            ips.remove(ip)
        ips.insert(0, ip)          # l'IP de la route par défaut en premier
    return ips


def _mdns_start(port: int):
    _mdns_stop()
    try:
        from zeroconf import Zeroconf, ServiceInfo
    except ImportError:
        print("[Tablet] zeroconf absent : pas d'annonce Bonjour (saisie de l'IP dans l'app)")
        return

    def _run():
        global _zc, _zc_info
        try:
            import re
            host = socket.gethostname() or "PC"
            label = re.sub(r"[^A-Za-z0-9-]", "-", host.split(".")[0]).strip("-") or "mystrow"
            ips = _lan_ipv4s()
            if not ips:
                print("[Tablet] Annonce Bonjour : aucune adresse réseau")
                return
            info = ServiceInfo(
                MDNS_SERVICE_TYPE, f"MyStrow {host}.{MDNS_SERVICE_TYPE}",
                port=port, parsed_addresses=ips, server=f"{label}.local.",
                properties={"proto": str(PROTOCOL_VERSION), "name": host})
            zc = Zeroconf()
            zc.register_service(info, allow_name_change=True)
            _zc, _zc_info = zc, info
            print(f"[Tablet] Annonce Bonjour « {info.name} » sur {', '.join(ips)} port {port}")
        except Exception as e:
            print(f"[Tablet] Annonce Bonjour impossible : {e}")

    threading.Thread(target=_run, daemon=True, name="TabletMDNS").start()


def _mdns_stop():
    global _zc, _zc_info
    zc, info = _zc, _zc_info
    _zc = _zc_info = None
    if zc is None:
        return
    try:
        if info is not None:
            zc.unregister_service(info)
    except Exception:
        pass
    try:
        zc.close()
    except Exception:
        pass


def stop():
    """Coupe l'accès tablette. Le socket waitress reste ouvert (cf. start()),
    mais le PC cesse de s'annoncer sur le réseau."""
    global _running
    _running = False
    _mdns_stop()


def _open_firewall(port: int):
    import sys, subprocess
    if sys.platform != "win32":
        return
    name = f"MyStrow Tablet {port}"
    cmds = [
        (f'netsh advfirewall firewall add rule name="{name}" '
         f'dir=in action=allow protocol=TCP localport={port} profile=any'),
        # Bonjour : les requêtes de découverte de l'app arrivent en UDP 5353.
        ('netsh advfirewall firewall add rule name="MyStrow Tablet mDNS" '
         'dir=in action=allow protocol=UDP localport=5353 profile=any'),
    ]
    for cmd in cmds:
        try:
            subprocess.run(cmd, shell=True, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def port_is_free(port: int) -> bool:
    """Le port est-il libre pour un bind sur 0.0.0.0 ?

    Test par bind REEL, sans SO_REUSEADDR : c'est le seul verdict fiable.
    Un simple « connect qui reussit » dit qu'un serveur repond, pas que c'est
    le notre — sur Mac, le « Recepteur AirPlay » (Reglages ▸ General ▸ AirDrop
    et Handoff) ecoute en permanence sur le port 5000 et renvoie 403/401 a
    tout le monde, tablette comprise."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def someone_answers(port: int) -> bool:
    """Quelqu'un repond-il deja sur ce port ? (127.0.0.1 ET l'IP du reseau)

    Complement du bind : un service lie a UNE adresse precise (127.0.0.1 seul,
    par exemple) laisse le bind sur 0.0.0.0 reussir tout en captant les requetes
    de la tablette. Deux tests valent mieux qu'un.
    """
    hosts = ["127.0.0.1"]
    ip = get_local_ip()
    if ip and ip not in hosts:
        hosts.append(ip)
    for host in hosts:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            pass
    return False


def _pick_port(wanted: int) -> int | None:
    """Retourne le premier port libre a partir de `wanted` (10 essais)."""
    for p in range(wanted, wanted + 10):
        if port_is_free(p) and not someone_answers(p):
            return p
    return None


def who_holds_port(port: int) -> str:
    """Nom du logiciel qui occupe le port, quand on peut le savoir (Mac/Linux)."""
    import sys, subprocess
    if sys.platform == "win32":
        return ""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=4).stdout
    except Exception:
        return ""
    for line in out.splitlines()[1:]:
        name = line.split()[0] if line.split() else ""
        if name:
            if name.startswith("ControlCe") or name == "AirPlayXPCHelper":
                return "Recepteur AirPlay (macOS)"
            return name
    return ""


def start(port: int = None):
    global _thread, _running, TABLET_PORT, last_error, _bound_port
    if not _flask_available:
        raise RuntimeError("Flask non installé. Exécutez : pip install flask")
    if _running:
        return

    # Le bouton « Desactiver » ne fait que baisser le drapeau : le thread
    # waitress, lui, garde son socket ouvert jusqu'a la fermeture de l'appli.
    # Sans ce raccourci, une reactivation trouverait SON PROPRE port occupe et
    # se replierait sur le suivant (5001, 5002...) a chaque aller-retour.
    if _thread is not None and _thread.is_alive() and _bound_port:
        TABLET_PORT = _bound_port
        _running = True
        _mdns_start(_bound_port)
        return

    wanted = int(port or TABLET_PORT)
    chosen = _pick_port(wanted)
    if chosen is None:
        qui = who_holds_port(wanted)
        raise RuntimeError(
            f"Aucun port libre entre {wanted} et {wanted + 9}."
            + (f"\nLe port {wanted} est occupé par : {qui}" if qui else ""))
    if chosen != wanted:
        qui = who_holds_port(wanted)
        print(f"[Tablet] Port {wanted} occupé"
              + (f" par {qui}" if qui else "") + f" -> repli sur {chosen}")
    TABLET_PORT = chosen
    last_error = ""
    _open_firewall(chosen)
    _build_app()
    _running = True

    def _run():
        global _running, last_error, _bound_port
        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        try:
            try:
                from waitress import serve
            except ImportError:
                serve = None
            _bound_port = chosen
            if serve is not None:
                print(f"[Tablet] Serveur waitress sur 0.0.0.0:{chosen}")
                serve(_app, host="0.0.0.0", port=chosen,
                      threads=8, connection_limit=20,
                      channel_timeout=60, cleanup_interval=10)
            else:
                # Fallback Flask si waitress absent
                print(f"[Tablet] Serveur Flask sur 0.0.0.0:{chosen}")
                _app.run(host="0.0.0.0", port=chosen, threaded=True,
                         use_reloader=False, debug=False)
        except Exception as e:
            # Sans ce garde, un echec de bind mourait en silence dans le thread :
            # l'appli affichait « ACTIF » et un QR code vers un port que MyStrow
            # n'a jamais ouvert.
            last_error = f"{type(e).__name__}: {e}"
            _running = False
            _bound_port = None
            print(f"[Tablet] Serveur arrêté : {last_error}")

    _thread = threading.Thread(target=_run, daemon=True, name="TabletServer")
    _thread.start()

    # Attendre que le socket reponde VRAIMENT avant de dire « demarre ».
    import time as _t
    deadline = _t.time() + 3.0
    while _t.time() < deadline:
        if not _running:
            break
        try:
            with socket.create_connection(("127.0.0.1", chosen), timeout=0.3):
                _mdns_start(chosen)
                return
        except OSError:
            _t.sleep(0.1)
    _running = False
    raise RuntimeError(
        f"Le serveur tablette n'a pas pu ouvrir le port {chosen}."
        + (f"\n{last_error}" if last_error else ""))
