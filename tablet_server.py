"""
Serveur local HTTP pour le contrôleur tablette MyStrow.
Protocole : Flask + Server-Sent Events (SSE) — aucune dépendance JS externe.

La tablette se connecte via : http://<IP_LOCAL>:5000
"""
import threading
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
    import subprocess, sys
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
}

# ── Clients SSE connectés ─────────────────────────────────────────────────────
_clients: list = []
_clients_lock = threading.Lock()

_app    = None
_thread = None
_running = False


# ── Construction Flask ────────────────────────────────────────────────────────
def _build_app():
    global _app
    _app = Flask(__name__, static_folder=None)

    @_app.route("/")
    def index():
        return send_file_fn(str(Path(__file__).parent / "tablet" / "index.html"))

    @_app.route("/manifest.json")
    def manifest():
        return send_file_fn(str(Path(__file__).parent / "tablet" / "manifest.json"),
                            mimetype="application/manifest+json")

    @_app.route("/sw.js")
    def service_worker():
        resp = send_file_fn(str(Path(__file__).parent / "tablet" / "sw.js"),
                            mimetype="application/javascript")
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @_app.route("/icon.png")
    def icon():
        return send_file_fn(str(Path(__file__).parent / "logo.png"),
                            mimetype="image/png")

    @_app.route("/stream")
    def stream():
        """Server-Sent Events : pousse les mises à jour en temps réel."""
        client_q: queue.Queue = queue.Queue()
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
                "Connection":       "keep-alive",
            },
        )
        resp.call_on_close(lambda: cleanup(None))
        return resp

    @_app.route("/api/event", methods=["POST"])
    def api_event():
        """Reçoit les actions de la tablette (pad, fader, effect)."""
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
    """Envoie un event SSE à tous les clients connectés."""
    with _clients_lock:
        for q in _clients:
            q.put(event)


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


def push_rec_state(active: bool):
    """Pousse l'état du mode REC mémoire."""
    _state["rec_active"] = active
    if _running:
        _broadcast({"type": "rec_state", "active": active})


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
            _state["projectors"][i]["strobe"]     = p.get("strobe", 0)
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
def _open_firewall(port: int):
    import sys, subprocess
    if sys.platform != "win32":
        return
    name = f"MyStrow Tablet {port}"
    cmd = (f'netsh advfirewall firewall add rule name="{name}" '
           f'dir=in action=allow protocol=TCP localport={port} profile=any')
    try:
        subprocess.run(cmd, shell=True, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def start(port: int = TABLET_PORT):
    global _thread, _running
    if not _flask_available:
        raise RuntimeError("Flask non installé. Exécutez : pip install flask")
    if _running:
        return
    _open_firewall(port)
    _build_app()
    _running = True

    def _run():
        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        try:
            from waitress import serve
            print(f"[Tablet] Serveur waitress sur 0.0.0.0:{port}")
            serve(_app, host="0.0.0.0", port=port,
                  threads=8, connection_limit=20,
                  channel_timeout=60, cleanup_interval=10)
        except ImportError:
            # Fallback Flask si waitress absent
            print(f"[Tablet] Serveur Flask sur 0.0.0.0:{port}")
            _app.run(host="0.0.0.0", port=port, threaded=True,
                     use_reloader=False, debug=False)

    _thread = threading.Thread(target=_run, daemon=True, name="TabletServer")
    _thread.start()
