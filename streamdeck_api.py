"""
streamdeck_api.py — Serveur HTTP local pour l'integration StreamDeck.

Permet au plugin Elgato StreamDeck de controler MyStrow via HTTP REST
sur http://127.0.0.1:8765/api/...

Endpoints:
  GET  /api/state                    → etat complet (JSON)
  GET  /api/cartouches               → liste des 4 cartouches
  GET  /api/memories                 → liste plate des memoires (MEM 1.1…8.8)
  GET  /api/effects                  → liste de tous les effets disponibles
  POST /api/play                     → toggle play/pause (lance le 1er media si rien)
  POST /api/next                     → media suivant
  POST /api/prev                     → media precedent
  POST /api/level/{fader_idx}/{val}  → niveau fader 0-8, valeur 0-100
  POST /api/effect/{idx|nom}         → toggle slot 0-7  OU  fire par nom d'effet
  POST /api/mute/{fader_idx}/{0|1}   → mute/unmute fader
  POST /api/scene/{col}/{row}        → (compat) declencher memoire col/row 0-7
  POST /api/memory/{id}              → declencher memoire par id "1.1"…"8.8"
  POST /api/goto/{row}               → aller a la ligne du sequenceur
  POST /api/cartouche/{idx}          → declencher cartouche 0-3
  POST /api/go                       → GO+ : avance à la mémoire suivante (mode GO)
  POST /api/goback                   → GO- : recule à la mémoire précédente (mode GO)

Ajouts pour l'assistant IA (serveur MCP, dossier mcp/) :
  POST /api/projectors               → {"events": [...]} au format tablette :
                                       proj_color / proj_level / proj_strobe / proj_mute
  POST /api/blackout                 → noir complet (faders, effets, strobe)
  POST /api/stop_effects             → coupe tous les effets en cours
  POST /api/speed/{0-100}            → vitesse des effets (fader Vit. FX)
  GET  /api/fixtures?q=texte         → recherche dans la bibliothèque locale
  GET  /api/fixture_format           → format JSON d'une fixture (prompt IA)
  POST /api/fixture_import           → {"fixture": {...}} : valide + enregistre
"""

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs

from PySide6.QtCore import QObject, Signal

# Port d'ecoute du serveur HTTP local
STREAMDECK_API_PORT = 8765


# ---------------------------------------------------------------------------
# Bridge Qt — assure que les appels arrivent dans le thread principal Qt
# ---------------------------------------------------------------------------

class _StreamDeckBridge(QObject):
    """Signaux Qt : emis depuis le thread HTTP, traites dans le thread Qt."""

    play_requested       = Signal()
    next_requested       = Signal()
    prev_requested       = Signal()
    level_requested      = Signal(int, int)   # (fader_idx, value 0-100)
    level_rel_requested  = Signal(int, int)   # (fader_idx, delta -100..+100)
    effect_requested     = Signal(int)        # effect_idx 0-7
    effect_name_requested= Signal(str)        # nom d'effet (fire direct)
    mute_requested       = Signal(int, bool)  # (fader_idx, active)
    scene_requested      = Signal(int, int)   # (mem_col 0-7, row 0-7)
    goto_seq_requested   = Signal(int)        # row index
    cartouche_requested  = Signal(int)        # cartouche idx 0-3
    go_advance_requested = Signal()           # GO+ : mémoire suivante
    go_back_requested    = Signal()           # GO- : mémoire précédente
    remote_event_requested = Signal(object)   # dict au format des events tablette
    blackout_requested   = Signal()
    stop_effects_requested = Signal()
    speed_requested      = Signal(int)        # vitesse effets 0-100
    fixture_save_requested = Signal(object)   # _FixtureJob (attendu par le thread HTTP)


class _FixtureJob:
    """Enregistrement d'une fixture fait dans le thread Qt (l'éditeur de
    fixtures écrit le même fichier) ; le thread HTTP attend le résultat."""

    def __init__(self, fx: dict):
        self.fx     = fx
        self.done   = threading.Event()
        self.name   = ""
        self.error  = ""


# Types d'events tablette acceptés depuis l'API (liste blanche : pas de
# « clear », « rec_toggle »… qui touchent à l'état de l'AKAI ou du REC).
_PROJECTOR_EVENTS = {"proj_color", "proj_level", "proj_strobe", "proj_mute"}

_NO_BROWSER_ACTIONS = {"projectors", "blackout", "stop_effects", "speed", "fixture_import"}


def _all_effects() -> list:
    from light_actions import all_effects
    return all_effects()


def _search_fixtures(query: str, limit: int = 30) -> list:
    """Recherche par mots dans la bibliothèque locale (intégrées + utilisateur,
    packs téléchargés compris : ils sont fusionnés dans le fichier utilisateur)."""
    from builtin_fixtures import BUILTIN_FIXTURES
    from fixture_editor import FIXTURE_FILE
    user = []
    try:
        if FIXTURE_FILE.exists():
            data = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                user = data
    except Exception:
        pass
    words = [w for w in (query or "").lower().split() if w]
    out = []
    for origin, lib in (("user", user), ("builtin", BUILTIN_FIXTURES)):
        for fx in lib:
            if not isinstance(fx, dict):
                continue
            hay = f'{fx.get("manufacturer", "")} {fx.get("name", "")} {fx.get("fixture_type", "")}'.lower()
            if words and not all(w in hay for w in words):
                continue
            modes = fx.get("modes") or [{"name": fx.get("mode_name", ""),
                                         "channelCount": len(fx.get("profile") or [])}]
            out.append({
                "name":         fx.get("name", ""),
                "manufacturer": fx.get("manufacturer", ""),
                "fixture_type": fx.get("fixture_type", ""),
                "modes":        [{"name": m.get("name", ""),
                                  "channels": m.get("channelCount") or len(m.get("profile") or [])}
                                 for m in modes if isinstance(m, dict)],
                "library":      origin,
            })
            if len(out) >= limit:
                return out
    return out


# ---------------------------------------------------------------------------
# Handler HTTP
# ---------------------------------------------------------------------------

def _make_handler(bridge: _StreamDeckBridge, window_ref: list):
    """Fabrique le handler HTTP avec acces au bridge et a la fenetre."""

    class _Handler(BaseHTTPRequestHandler):

        def log_message(self, fmt, *args):  # silence les logs HTTP
            pass

        # ── helpers ────────────────────────────────────────────────────────

        def _send_json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, msg, status=400):
            self._send_json({"error": msg}, status)

        def _read_json(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("corps JSON attendu : un objet")
            return data

        def _parts(self):
            """Retourne les segments du path, URL-decodés."""
            return [unquote(p) for p in urlparse(self.path).path.split("/") if p]

        # ── CORS pre-flight ─────────────────────────────────────────────────

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        # ── GET ─────────────────────────────────────────────────────────────

        def do_GET(self):
            parts = self._parts()
            if parts == ["api", "state"]:
                self._handle_state()
            elif parts == ["api", "scenes"]:
                self._handle_scenes()
            elif parts == ["api", "sequences"]:
                self._handle_sequences()
            elif parts == ["api", "cartouches"]:
                self._handle_cartouches()
            elif parts == ["api", "memories"]:
                self._handle_memories()
            elif parts == ["api", "effects"]:
                self._handle_effects()
            elif parts == ["api", "fixtures"]:
                q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
                try:
                    self._send_json({"fixtures": _search_fixtures(q)})
                except Exception as exc:
                    self._send_json({"error": str(exc)}, 500)
            elif parts == ["api", "fixture_format"]:
                try:
                    from fixture_ai_prompt import build_prompt
                    self._send_json({"format": build_prompt()})
                except Exception as exc:
                    self._send_json({"error": str(exc)}, 500)
            else:
                self._send_error("Not found", 404)

        # ── GET /api/memories ────────────────────────────────────────────────

        def _handle_memories(self):
            """Liste plate de toutes les memoires : MEM 1.1 … MEM 8.8."""
            w = window_ref[0]
            if w is None:
                self._send_json({"error": "not ready"}, 503)
                return
            try:
                items = []
                for mc in range(8):
                    col_akai = w._mem_col_to_fader(mc)
                    for r in range(8):
                        mem    = w.memories[mc][r]
                        active = w.active_memory_pads.get(col_akai) == r
                        color  = w._get_memory_pad_color(mc, r)
                        items.append({
                            "id":     f"{mc + 1}.{r + 1}",
                            "label":  f"MEM {mc + 1}.{r + 1}",
                            "stored": mem is not None,
                            "active": active,
                            "color":  color.name() if color else "#000000",
                        })
                self._send_json({"memories": items})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        # ── GET /api/effects ─────────────────────────────────────────────────

        def _handle_effects(self):
            """Liste de tous les effets disponibles (builtin + custom)."""
            try:
                from effect_editor import BUILTIN_EFFECTS
                all_effects = _all_effects()
                items = [
                    {
                        "name":     e.get("name", ""),
                        "category": e.get("category", ""),
                        "emoji":    e.get("emoji", ""),
                        "type":     e.get("type", ""),
                        "custom":   e not in BUILTIN_EFFECTS,
                    }
                    for e in all_effects
                ]
                self._send_json({"effects": items})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        # ── GET /api/cartouches ──────────────────────────────────────────────

        def _handle_cartouches(self):
            w = window_ref[0]
            if w is None:
                self._send_json({"error": "not ready"}, 503)
                return
            try:
                carts = []
                for i, cart in enumerate(w.cartouches):
                    carts.append({
                        "index":  i,
                        "title":  cart.media_title or "",
                        "icon":   cart.media_icon  or "",
                        "state":  cart.state,
                        "volume": cart.volume,
                        "loaded": bool(cart.media_path),
                    })
                self._send_json({"cartouches": carts})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        # ── GET /api/sequences ───────────────────────────────────────────────

        def _handle_sequences(self):
            w = window_ref[0]
            if w is None:
                self._send_json({"error": "not ready"}, 503)
                return
            try:
                items = []
                tbl = w.seq.table
                for r in range(tbl.rowCount()):
                    title_item = tbl.item(r, 1)
                    type_item  = tbl.item(r, 0)
                    items.append({
                        "index": r,
                        "title": title_item.text() if title_item else "",
                        "type":  type_item.text()  if type_item  else "media",
                    })
                self._send_json({"sequences": items, "current_row": w.seq.current_row})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        # ── GET /api/scenes ──────────────────────────────────────────────────

        def _handle_scenes(self):
            w = window_ref[0]
            if w is None:
                self._send_json({"error": "not ready"}, 503)
                return
            try:
                scenes = []
                for mc in range(8):
                    col = []
                    col_akai = w._mem_col_to_fader(mc)
                    for r in range(8):
                        mem = w.memories[mc][r]
                        active = w.active_memory_pads.get(col_akai) == r
                        color = w._get_memory_pad_color(mc, r)
                        col.append({
                            "stored": mem is not None,
                            "active": active,
                            "color":  color.name() if color else "#000000",
                        })
                    scenes.append(col)
                self._send_json({"scenes": scenes})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        # ── GET /api/state ───────────────────────────────────────────────────

        def _handle_state(self):
            w = window_ref[0]
            if w is None:
                self._send_json({"error": "not ready"}, 503)
                return
            try:
                from PySide6.QtMultimedia import QMediaPlayer

                is_playing = w.player.playbackState() == QMediaPlayer.PlayingState

                # Media courant
                current_row  = getattr(w.seq, "current_row", -1)
                current_media = ""
                if current_row >= 0:
                    item = w.seq.table.item(current_row, 1)
                    current_media = item.text() if item else ""

                # Niveaux faders (sliders Qt)
                fader_levels = [
                    w.faders[i].value()
                    for i in sorted(w.faders.keys())
                    if i in w.faders
                ]

                # Effets boutons (slots 0-7)
                active_effects = [
                    {
                        "index": i,
                        "name": btn.current_effect or "",
                        "active": bool(btn.active),
                    }
                    for i, btn in enumerate(w.effect_buttons)
                ]

                # Projecteurs
                projectors = [
                    {
                        "index":  i,
                        "name":   p.name,
                        "group":  p.group,
                        "type":   getattr(p, "fixture_type", ""),
                        "level":  p.level,
                        "color":  p.color.name(),
                        "muted":  p.muted,
                    }
                    for i, p in enumerate(w.projectors)
                ]

                # Memoires — liste plate
                memories = []
                for mc in range(8):
                    col_akai = w._mem_col_to_fader(mc)
                    for r in range(8):
                        mem   = w.memories[mc][r]
                        act   = w.active_memory_pads.get(col_akai) == r
                        color = w._get_memory_pad_color(mc, r)
                        memories.append({
                            "id":     f"{mc + 1}.{r + 1}",
                            "label":  f"MEM {mc + 1}.{r + 1}",
                            "stored": mem is not None,
                            "active": act,
                            "color":  color.name() if color else "#000000",
                        })

                # Scenes (compat — format matriciel 8×8)
                scenes = []
                for mc in range(8):
                    col_akai = w._mem_col_to_fader(mc)
                    col = []
                    for r in range(8):
                        mem   = w.memories[mc][r]
                        act   = w.active_memory_pads.get(col_akai) == r
                        color = w._get_memory_pad_color(mc, r)
                        col.append({
                            "stored": mem is not None,
                            "active": act,
                            "color":  color.name() if color else "#000000",
                        })
                    scenes.append(col)

                # Entrées du séquenceur
                tbl = w.seq.table
                seq_items = []
                for r in range(tbl.rowCount()):
                    ti = tbl.item(r, 1)
                    seq_items.append({"index": r, "title": ti.text() if ti else ""})

                # Cartouches
                cartouches = []
                for i, cart in enumerate(w.cartouches):
                    cartouches.append({
                        "index":  i,
                        "title":  cart.media_title or "",
                        "icon":   cart.media_icon  or "",
                        "state":  cart.state,
                        "volume": cart.volume,
                        "loaded": bool(cart.media_path),
                    })

                # Effet courant
                active_effect_name = getattr(w, "active_effect", None) or ""

                self._send_json({
                    "playing":            is_playing,
                    "pause_mode":         w.pause_mode,
                    "current_media":      current_media,
                    "current_row":        current_row,
                    "fader_levels":       fader_levels,
                    "active_effects":     active_effects,
                    "active_effect_name": active_effect_name,
                    "effect_speed":       getattr(w, "effect_speed", 0),
                    "projectors":         projectors,
                    "memories":           memories,
                    "scenes":             scenes,
                    "seq_items":          seq_items,
                    "cartouches":         cartouches,
                })
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        # ── POST /api/* ──────────────────────────────────────────────────────

        def do_POST(self):
            parts = self._parts()

            if len(parts) < 2 or parts[0] != "api":
                self._send_error("Not found", 404)
                return

            action = parts[1]

            # Les commandes ajoutées pour l'assistant IA ne sont pas faites pour
            # un navigateur : avec le CORS ouvert, n'importe quelle page web
            # pourrait sinon envoyer un noir en plein show. Un client local
            # (serveur MCP, curl) n'envoie pas d'en-tête Origin.
            if action in _NO_BROWSER_ACTIONS and self.headers.get("Origin"):
                self._send_error("Commande refusée depuis un navigateur", 403)
                return

            if action == "play":
                bridge.play_requested.emit()
                self._send_json({"ok": True})

            elif action == "next":
                bridge.next_requested.emit()
                self._send_json({"ok": True})

            elif action == "prev":
                bridge.prev_requested.emit()
                self._send_json({"ok": True})

            elif action == "level":
                # POST /api/level/{fader_idx 0-8}/{value 0-100}
                # POST /api/level/{fader_idx 0-8}/+N or -N  (relatif, encodeur rotatif)
                try:
                    idx = int(parts[2])
                    raw = parts[3]
                    if not (0 <= idx <= 8):
                        raise ValueError("fader_idx hors plage 0-8")
                    if raw.startswith("+") or (raw.startswith("-") and raw != "-0"):
                        delta = int(raw)
                        bridge.level_rel_requested.emit(idx, delta)
                    else:
                        val = int(raw)
                        if not (0 <= val <= 100):
                            raise ValueError("value hors plage 0-100")
                        bridge.level_requested.emit(idx, val)
                    self._send_json({"ok": True})
                except (IndexError, ValueError) as exc:
                    self._send_error(f"Usage: /api/level/{{0-8}}/{{0-100}} — {exc}")

            elif action == "effect":
                # POST /api/effect/{idx 0-7}  → toggle slot bouton
                # POST /api/effect/{nom}       → fire l'effet directement par nom
                try:
                    raw = parts[2]
                except IndexError:
                    self._send_error("Usage: /api/effect/{0-7 ou nom}")
                    return
                try:
                    idx = int(raw)
                    if not (0 <= idx <= 7):
                        raise ValueError("idx hors plage 0-7")
                    bridge.effect_requested.emit(idx)
                    self._send_json({"ok": True})
                except ValueError:
                    # Pas un entier → traiter comme un nom d'effet. Résolu ici,
                    # sans tenir compte de la casse : un nom inconnu doit revenir
                    # en erreur, sinon l'appelant (une IA) croit avoir réussi.
                    name = raw.strip()
                    if not name:
                        self._send_error("Nom d'effet vide")
                        return
                    try:
                        names = [e.get("name", "") for e in _all_effects()]
                    except Exception as exc:
                        self._send_json({"error": str(exc)}, 500)
                        return
                    match = next((n for n in names if n == name), None) or \
                        next((n for n in names if n.lower() == name.lower()), None)
                    if match is None:
                        self._send_error(f"Effet inconnu : {name} (voir GET /api/effects)", 404)
                        return
                    bridge.effect_name_requested.emit(match)
                    self._send_json({"ok": True, "effect": match})

            elif action == "mute":
                # POST /api/mute/{fader_idx 0-7}/{0|1}
                try:
                    idx    = int(parts[2])
                    active = bool(int(parts[3]))
                    if not (0 <= idx <= 7):
                        raise ValueError("fader_idx hors plage 0-7")
                    bridge.mute_requested.emit(idx, active)
                    self._send_json({"ok": True})
                except (IndexError, ValueError) as exc:
                    self._send_error(f"Usage: /api/mute/{{0-7}}/{{0|1}} — {exc}")

            elif action == "scene":
                # POST /api/scene/{mem_col 0-7}/{row 0-7}  (compatibilite)
                try:
                    mc  = int(parts[2])
                    row = int(parts[3])
                    if not (0 <= mc  <= 7):
                        raise ValueError("mem_col hors plage 0-7")
                    if not (0 <= row <= 7):
                        raise ValueError("row hors plage 0-7")
                    bridge.scene_requested.emit(mc, row)
                    self._send_json({"ok": True})
                except (IndexError, ValueError) as exc:
                    self._send_error(f"Usage: /api/scene/{{0-7}}/{{0-7}} — {exc}")

            elif action == "memory":
                # POST /api/memory/{id}  où id = "1.1" … "8.8"
                try:
                    mem_id = parts[2]
                    col_s, row_s = mem_id.split(".")
                    mc  = int(col_s) - 1   # 1-based → 0-based
                    row = int(row_s) - 1
                    if not (0 <= mc  <= 7):
                        raise ValueError("colonne hors plage 1-8")
                    if not (0 <= row <= 7):
                        raise ValueError("rangee hors plage 1-8")
                    bridge.scene_requested.emit(mc, row)
                    self._send_json({"ok": True})
                except (IndexError, ValueError, AttributeError) as exc:
                    self._send_error(f'Usage: /api/memory/1.1 … /api/memory/8.8 — {exc}')

            elif action == "goto":
                # POST /api/goto/{row}
                try:
                    row = int(parts[2])
                    bridge.goto_seq_requested.emit(row)
                    self._send_json({"ok": True})
                except (IndexError, ValueError) as exc:
                    self._send_error(f"Usage: /api/goto/{{row}} — {exc}")

            elif action == "cartouche":
                # POST /api/cartouche/{idx 0-3}
                try:
                    idx = int(parts[2])
                    if not (0 <= idx <= 3):
                        raise ValueError("idx hors plage 0-3")
                    bridge.cartouche_requested.emit(idx)
                    self._send_json({"ok": True})
                except (IndexError, ValueError) as exc:
                    self._send_error(f"Usage: /api/cartouche/{{0-3}} — {exc}")

            elif action == "go":
                # POST /api/go → GO+ mémoire suivante
                bridge.go_advance_requested.emit()
                self._send_json({"ok": True})

            elif action == "goback":
                # POST /api/goback → GO- mémoire précédente
                bridge.go_back_requested.emit()
                self._send_json({"ok": True})

            elif action == "projectors":
                # POST /api/projectors  {"events": [{"type": "proj_color", "idxs": [0, 1], "color": "#ff0000"}, ...]}
                try:
                    events = self._read_json().get("events")
                    if not isinstance(events, list) or not events:
                        raise ValueError('"events" doit être une liste non vide')
                    for ev in events:
                        if not isinstance(ev, dict) or ev.get("type") not in _PROJECTOR_EVENTS:
                            raise ValueError(f"type d'event refusé : {ev!r}")
                        if not isinstance(ev.get("idxs"), list):
                            raise ValueError('"idxs" (liste d\'indices de projecteurs) manquant')
                        ev["idxs"] = [int(i) for i in ev["idxs"]]
                    for ev in events:
                        bridge.remote_event_requested.emit(ev)
                    self._send_json({"ok": True})
                except (ValueError, TypeError) as exc:
                    self._send_error(str(exc))

            elif action == "blackout":
                bridge.blackout_requested.emit()
                self._send_json({"ok": True})

            elif action == "stop_effects":
                bridge.stop_effects_requested.emit()
                self._send_json({"ok": True})

            elif action == "speed":
                # POST /api/speed/{0-100}
                try:
                    val = int(parts[2])
                    if not (0 <= val <= 100):
                        raise ValueError("valeur hors plage 0-100")
                    bridge.speed_requested.emit(val)
                    self._send_json({"ok": True})
                except (IndexError, ValueError) as exc:
                    self._send_error(f"Usage: /api/speed/{{0-100}} — {exc}")

            elif action == "fixture_import":
                # POST /api/fixture_import  {"fixture": {...format mystrow-fixture...}}
                # Même lecture que « Créer votre fixture via IA » : mêmes
                # corrections (doublons de canaux, machines à effet…).
                try:
                    raw = self._read_json().get("fixture")
                    if raw is None:
                        raise ValueError('"fixture" manquant')
                    from fixture_ai_prompt import parse_ai_response
                    fx = parse_ai_response(raw if isinstance(raw, str) else json.dumps(raw))
                except (ValueError, TypeError) as exc:
                    self._send_error(str(exc))
                    return
                job = _FixtureJob(fx)
                bridge.fixture_save_requested.emit(job)
                if not job.done.wait(10):
                    self._send_json({"error": "MyStrow occupé, réessayer"}, 503)
                    return
                if job.error:
                    self._send_json({"error": job.error}, 500)
                    return
                self._send_json({
                    "ok":       True,
                    "name":     job.name,
                    "fixture_type": fx.get("fixture_type", ""),
                    "modes":    [{"name": m["name"], "channels": m["channelCount"],
                                  "profile": m["profile"]} for m in fx.get("modes", [])],
                    "unused_channels": fx.get("profile", []).count("Unused"),
                })

            else:
                self._send_error(f"Action inconnue : {action}", 404)

    return _Handler


# ---------------------------------------------------------------------------
# Classe principale — instanciee par MainWindow
# ---------------------------------------------------------------------------

class StreamDeckAPIServer:
    """
    Serveur HTTP local pour le plugin StreamDeck.

    Usage dans MainWindow.__init__ :
        self._streamdeck_server = StreamDeckAPIServer(self)
        self._streamdeck_server.start()

    Usage dans MainWindow.closeEvent :
        self._streamdeck_server.stop()
    """

    def __init__(self, window):
        self._window_ref = [window]
        self._bridge     = _StreamDeckBridge(window)  # parent Qt pour la duree de vie
        self._server     = None
        self._thread     = None
        self._port       = STREAMDECK_API_PORT
        self._connect_signals(window)

    # ── connexion signaux → slots MainWindow ────────────────────────────────

    def _connect_signals(self, window):
        b = self._bridge
        b.play_requested.connect(self._on_play)
        b.next_requested.connect(window.next_media)
        b.prev_requested.connect(window.previous_media)
        b.level_requested.connect(self._on_set_level)
        b.level_rel_requested.connect(self._on_level_rel)
        b.effect_requested.connect(window.toggle_effect)
        b.effect_name_requested.connect(self._on_fire_effect_name)
        b.mute_requested.connect(self._on_toggle_mute)
        b.scene_requested.connect(window.trigger_memory)
        b.goto_seq_requested.connect(window.seq.play_row)
        b.cartouche_requested.connect(window.on_cartouche_clicked)
        b.go_advance_requested.connect(window._go_advance)
        b.go_back_requested.connect(window._go_back)
        b.remote_event_requested.connect(self._on_remote_event)
        b.blackout_requested.connect(window.full_blackout)
        b.stop_effects_requested.connect(self._on_stop_effects)
        b.speed_requested.connect(self._on_speed)
        b.fixture_save_requested.connect(self._on_fixture_save)

    def _on_remote_event(self, ev: dict):
        w = self._window_ref[0]
        if w is None:
            return
        try:
            w._apply_tablet_event(ev)
        except Exception as exc:
            print(f"[StreamDeck API] event {ev.get('type')} échec : {exc}")

    def _on_stop_effects(self):
        w = self._window_ref[0]
        if w is not None:
            import light_actions
            light_actions.stop_effects(w)

    def _on_speed(self, value: int):
        w = self._window_ref[0]
        if w is not None:
            import light_actions
            light_actions.set_speed(w, value)

    def _on_fixture_save(self, job):
        try:
            from fixture_ai_prompt import save_to_library
            job.name = save_to_library(job.fx)
            w = self._window_ref[0]
            if w is not None:
                w._log_message(f"Fixture « {job.name} » ajoutée à la bibliothèque par l'assistant IA")
        except Exception as exc:
            job.error = str(exc)
        finally:
            job.done.set()

    def _on_play(self):
        """Play/pause depuis StreamDeck.
        Si aucun media n'est charge, lance le premier item du sequenceur."""
        w = self._window_ref[0]
        if w is None:
            return
        has_source = bool(w.player.source().toString())
        no_media = (not has_source) and (getattr(w.seq, "current_row", -1) < 0)
        if no_media:
            if w.seq.table.rowCount() > 0:
                w.seq.play_row(0)
            return
        w.toggle_play()

    def _on_set_level(self, idx: int, value: int):
        """Niveau fader depuis StreamDeck : met a jour projectors + widget simulateur."""
        w = self._window_ref[0]
        if w is None:
            return
        # Mettre a jour le widget fader dans le simulateur AKAI
        if idx in w.faders:
            w.faders[idx].value = value
            w.faders[idx].update()
        # Mettre a jour les projecteurs et envoyer le DMX
        w.set_proj_level(idx, value)

    def _on_level_rel(self, idx: int, delta: int):
        """Ajuste un fader de façon relative (pour l'encodeur rotatif)."""
        w = self._window_ref[0]
        if w is None or idx not in w.faders:
            return
        current = w.faders[idx].value
        new_val = max(0, min(100, current + delta))
        self._on_set_level(idx, new_val)

    def _on_toggle_mute(self, idx: int, active: bool):
        """Mute depuis StreamDeck : met a jour projectors + widget simulateur + LED AKAI."""
        w = self._window_ref[0]
        if w is None:
            return
        # Mettre a jour le bouton mute dans le simulateur AKAI
        if 0 <= idx < len(w.fader_buttons):
            btn = w.fader_buttons[idx]
            btn.active = active
            btn.update_style()
        # Mettre a jour les projecteurs
        w.toggle_mute(idx, active)
        # Envoyer le retour LED vers l'AKAI physique (note 100+idx, velocity 3=actif 0=inactif)
        try:
            from main_window import MIDI_AVAILABLE
            if MIDI_AVAILABLE and w.midi_handler.midi_out:
                note = 100 + idx
                velocity = 3 if active else 0
                w.midi_handler.midi_out.send_message([0x90, note, velocity])
        except Exception:
            pass

    def _on_fire_effect_name(self, name: str):
        """Demarre un effet directement par son nom (builtin ou custom)."""
        w = self._window_ref[0]
        if w is None:
            return
        try:
            import light_actions
            light_actions.fire_effect(w, name)
        except Exception:
            pass

    # ── cycle de vie ────────────────────────────────────────────────────────

    def start(self, port: int = STREAMDECK_API_PORT) -> bool:
        self._port = port
        handler = _make_handler(self._bridge, self._window_ref)
        try:
            self._server = HTTPServer(("127.0.0.1", port), handler)
        except OSError as exc:
            print(f"[StreamDeck API] Impossible de demarrer sur le port {port} : {exc}")
            return False

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="streamdeck-api",
        )
        self._thread.start()
        print(f"[StreamDeck API] Serveur demarre — http://127.0.0.1:{port}/api/")
        return True

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
            print("[StreamDeck API] Serveur arrete")
