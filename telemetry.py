"""
telemetry.py — Télémétrie anonyme et opt-in de MyStrow.

Principe :
  - Aucune donnée personnelle : juste un identifiant machine ALÉATOIRE
    (pas l'email, pas le contenu des shows), la version, l'OS et des
    noms d'événements (« app_launch », « dmx_connected »…).
  - Désactivée par défaut : ne s'active que si l'utilisateur accepte
    (opt-in au premier lancement) → conforme RGPD.
  - Envoi via GA4 Measurement Protocol (réutilise Google Analytics).
    Fire-and-forget en thread : n'allonge pas le démarrage et ne fait
    jamais planter l'app en cas de coupure réseau.

Pour activer côté Google Analytics :
  1. GA4 → Admin → Flux de données → créer (ou réutiliser) un flux,
     récupérer son MEASUREMENT_ID (format « G-XXXXXXXXXX »).
  2. Dans ce flux → « Protocole de mesure » → créer un secret d'API.
  3. Renseigner GA4_MEASUREMENT_ID et GA4_API_SECRET ci-dessous.
Tant qu'ils contiennent « XXXX », la télémétrie reste inerte.
"""
import os
import json
import uuid
import platform
import threading
import urllib.request

# ── À renseigner (cf. docstring) ───────────────────────────────────────
GA4_MEASUREMENT_ID = "G-4G9MXM0ENS"
GA4_API_SECRET     = "6tsMfvuPSJm6uAuN54Sxcw"

_CONFIG_FILE = os.path.expanduser("~/.mystrow_telemetry.json")
_ENDPOINT = "https://www.google-analytics.com/mp/collect"

_state = {"enabled": False, "choice_made": False, "client_id": None}
_session_id = uuid.uuid4().hex


def _app_version():
    try:
        from core import VERSION
        return VERSION
    except Exception:
        return "?"


def _os_label():
    s = platform.system()
    return {"Darwin": "macOS", "Windows": "Windows"}.get(s, s or "?")


def _load():
    data = {}
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        pass
    _state["client_id"]   = data.get("client_id") or uuid.uuid4().hex
    _state["enabled"]     = bool(data.get("enabled", False))
    _state["choice_made"] = bool(data.get("choice_made", False))
    _save()   # persiste l'identifiant machine (stable) dès le 1er lancement


def _save():
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "client_id":   _state["client_id"],
                "enabled":     _state["enabled"],
                "choice_made": _state["choice_made"],
            }, f, indent=2)
    except Exception:
        pass


def init():
    """À appeler une fois au démarrage."""
    _load()


def choice_made() -> bool:
    """True si l'utilisateur a déjà répondu à la question opt-in."""
    return _state["choice_made"]


def set_choice(enabled: bool):
    """Enregistre le choix de l'utilisateur (opt-in/opt-out)."""
    _state["enabled"] = bool(enabled)
    _state["choice_made"] = True
    _save()


def is_enabled() -> bool:
    return _state["enabled"]


def _configured() -> bool:
    return "XXXX" not in GA4_MEASUREMENT_ID and "XXXX" not in GA4_API_SECRET


def track(event: str, params: dict = None):
    """Envoie un événement anonyme (sans bloquer ni jamais lever d'exception)."""
    if not _state["enabled"] or not _state["client_id"] or not _configured():
        return
    p = dict(params or {})
    p.setdefault("app_version", _app_version())
    p.setdefault("os", _os_label())
    p.setdefault("session_id", _session_id)
    p.setdefault("engagement_time_msec", "100")   # pour que GA4 compte l'event
    payload = {"client_id": _state["client_id"], "events": [{"name": event, "params": p}]}
    threading.Thread(target=_post, args=(payload,), daemon=True).start()


def _post(payload):
    try:
        url = f"{_ENDPOINT}?measurement_id={GA4_MEASUREMENT_ID}&api_secret={GA4_API_SECRET}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=4).read()
    except Exception:
        pass   # télémétrie best-effort : jamais bloquant
