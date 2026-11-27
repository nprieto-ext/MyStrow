"""MyStrow Light — relais entre MyStrow (le PC) et les téléphones du public.

Le public flashe un QR code → page web → WebSocket vers CE serveur.
MyStrow se connecte aussi ici (WebSocket « contrôleur ») et pousse l'état des
zones (R, G, B, Dim, Strobe). Le serveur le rediffuse à tous les téléphones
avec une HEURE D'EXÉCUTION (horloge du serveur + DELAI_MS) : chaque téléphone
cale son horloge sur celle du serveur et applique l'état pile à cette heure.
Résultat : les téléphones changent ensemble malgré une latence 4G de 50 à
300 ms qui varie d'un appareil à l'autre.

LIMITES (c'est le serveur qui compte, pas le QR code) :
  - plafond de téléphones par session : celui du TICKET signé par la Cloud
    Function up_ticket (licence payée → 50, compte en essai → 1 = aperçu) ; SANS ticket
    valide, la session est refusée (403) : pas de compte = pas de MyStrow Light ;
    le suivant reçoit « full » ;
  - 1 session ouverte max par compte (licence : toujours celle de son QR permanent) ;
  - reprendre une session exige le jeton contrôleur (le sid du QR est public) ;
  - un téléphone garde sa place 60 s après une coupure (jeton en localStorage) ;
  - une session meurt si MyStrow est absent 10 min, et au bout de 6 h ;
  - débit contrôleur plafonné (MAX_CTL_MSG_S).

Lancement (prototype, en local) :
    python crowd/relay_server.py            → http://0.0.0.0:8765
Variables : CROWD_HOST, CROWD_PORT, CROWD_CAP (plafond absolu), CROWD_CAP_ESSAI,
UP_TICKET_SECRET (même valeur que dans functions/.env).
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from aiohttp import web, WSMsgType

PORT = int(os.environ.get("CROWD_PORT", "8765"))
# En prod : 127.0.0.1, derrière Caddy (HTTPS). En local : 0.0.0.0 pour les téléphones du Wi-Fi.
HOST = os.environ.get("CROWD_HOST", "0.0.0.0")
CAP_MAX = int(os.environ.get("CROWD_CAP", "50"))          # plafond absolu, même avec ticket
CAP_ESSAI = int(os.environ.get("CROWD_CAP_ESSAI", "1"))  # ticket sans « cap » (ne devrait pas arriver)
# Ticket signé par la Cloud Function up_ticket (licence vérifiée dans Firestore).
TICKET_SECRET = os.environ.get("UP_TICKET_SECRET", "")
MAX_SESSIONS_PAR_PROPRIO = 1   # par compte (25/11/2026 : une licence = une salle)
DELAI_MS = 250              # marge pour que l'ordre arrive partout avant son heure
GARDE_PLACE_S = 60          # place réservée après déconnexion d'un téléphone
SESSION_ORPHELINE_S = 600   # MyStrow absent depuis 10 min → session fermée
SESSION_MAX_S = 6 * 3600
MAX_CTL_MSG_S = 40
MAX_ZONES = 8

FICHIER_PAGE = Path(__file__).with_name("phone.html")

# Historique des sessions (une ligne JSON par session terminée) : lu par l'onglet
# « MyStrow Light » du panneau admin via /stats. Le service tourne en ProtectSystem=strict :
# seul le dossier STATE_DIRECTORY (StateDirectory=mystrow-live → /var/lib/mystrow-live)
# est inscriptible. En local : à côté du script.
FICHIER_STATS = Path(os.environ.get("CROWD_STATS") or
                     (Path(os.environ["STATE_DIRECTORY"]) / "sessions.jsonl"
                      if os.environ.get("STATE_DIRECTORY") else Path(__file__).with_name("sessions.jsonl")))
HISTORIQUE_MAX = 2000      # lignes renvoyées par /stats (les plus récentes)


def cle_stats() -> str:
    """Clé d'accès à /stats, dérivée du secret des tickets : l'admin la recalcule
    depuis sa copie du secret, sans que le secret lui-même voyage."""
    return hmac.new(TICKET_SECRET.encode(), b"mystrow-up-stats", hashlib.sha256).hexdigest()


def page_telephone() -> str:
    # Relue à chaque visite (quelques Ko) : on peut mettre la page à jour
    # SANS redémarrer le relais, donc sans couper les shows en cours.
    return FICHIER_PAGE.read_text(encoding="utf-8")


def now_ms() -> int:
    return int(time.time() * 1000)


class Session:
    def __init__(self, sid: str, cap: int):
        self.sid = sid
        self.cap = cap
        self.proprio = ""               # "uid:…" du ticket
        self.ctl_tok = secrets.token_urlsafe(16)   # pour reprendre la session après coupure
        self.cree = time.time()
        self.ctl = None                 # WebSocket de MyStrow
        self.ctl_vu = time.time()
        self.phones = {}                # jeton → WebSocket (None si déconnecté)
        self.vu = {}                    # jeton → dernière déconnexion
        self.zone_of = {}               # jeton → zone
        self.nz = 1
        self.last = None                # dernier message d'état (pour les arrivants)
        self._fenetre = (0.0, 0)        # anti-spam contrôleur
        self.total = 0                  # téléphones différents venus pendant la session
        self.pic = 0                    # maximum connectés en même temps
        self.archivee = False

    def resume(self, fin: float | None = None, raison: str = "") -> dict:
        d = {"sid": self.sid, "uid": self.proprio.removeprefix("uid:"), "cap": self.cap,
             "permanent": len(self.sid) == 10, "debut": round(self.cree),
             "pic": self.pic, "total": self.total}
        if fin is None:
            d["connectes"] = self.connectes()
            d["mystrow"] = self.ctl is not None
        else:
            d.update(fin=round(fin), duree_s=round(fin - self.cree), raison=raison)
        return d

    def archiver(self, raison: str):
        """Note la session terminée dans l'historique (une seule fois)."""
        if self.archivee:
            return
        self.archivee = True
        try:
            FICHIER_STATS.parent.mkdir(parents=True, exist_ok=True)
            with FICHIER_STATS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(self.resume(time.time(), raison), ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"[stats] historique impossible à écrire ({e})")

    def connectes(self) -> int:
        return sum(1 for w in self.phones.values() if w is not None)

    def places_prises(self) -> int:
        t = time.time()
        return sum(1 for k, w in self.phones.items()
                   if w is not None or t - self.vu.get(k, 0) < GARDE_PLACE_S)

    def zone_libre(self) -> int:
        compte = [0] * self.nz
        for k, w in self.phones.items():
            z = self.zone_of.get(k, 0)
            if w is not None and z < self.nz:
                compte[z] += 1
        return compte.index(min(compte))

    async def diffuser(self, msg: dict):
        data = json.dumps(msg, separators=(",", ":"))
        morts = []
        for k, w in self.phones.items():
            if w is None:
                continue
            try:
                await w.send_str(data)
            except Exception:
                morts.append(k)
        for k in morts:
            self.phones[k] = None
            self.vu[k] = time.time()

    async def compte_au_ctl(self):
        if self.ctl is not None:
            try:
                await self.ctl.send_json({"t": "n", "n": self.connectes(), "cap": self.cap})
            except Exception:
                pass


SESSIONS: dict[str, Session] = {}


def nouvel_id() -> str:
    # 8 caractères sans ambiguïté (pas de 0/O/1/l) : ~10^13 combinaisons.
    alpha = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        sid = "".join(secrets.choice(alpha) for _ in range(8))
        if sid not in SESSIONS:
            return sid


# ── Pages ────────────────────────────────────────────────────────────────────

_ALPHA_SID = set("abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def sid_valide(sid: str) -> bool:
    # 8 car. = session d'essai (aléatoire) ; 10 car. = QR permanent d'une licence.
    return len(sid) in (8, 10) and set(sid) <= _ALPHA_SID


async def page_live(request):
    sid = request.match_info["sid"]
    # Un QR permanent (10 car.) est imprimé à l'avance : la page s'affiche même
    # si le spectacle n'a pas commencé, et le téléphone attend la session.
    if sid not in SESSIONS and not (len(sid) == 10 and sid_valide(sid)):
        return web.Response(text="Session terminée ou inconnue.", status=404,
                            content_type="text/plain", charset="utf-8")
    return web.Response(text=page_telephone(), content_type="text/html", charset="utf-8",
                        headers={"Cache-Control": "no-store"})


async def sante(request):
    return web.json_response({"ok": True, "sessions": len(SESSIONS),
                              "telephones": sum(s.connectes() for s in SESSIONS.values())})


def lire_historique(n: int = HISTORIQUE_MAX) -> list:
    try:
        lignes = FICHIER_STATS.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for l in lignes:
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


async def stats(request):
    """Direct + historique, pour le panneau admin (clé dérivée du secret)."""
    cle = request.headers.get("X-Stats-Key", "")
    if not (TICKET_SECRET and hmac.compare_digest(cle, cle_stats())):
        return web.Response(status=403, text="interdit")
    return web.json_response({"maintenant": round(time.time()),
                              "direct": [s.resume() for s in SESSIONS.values()],
                              "historique": lire_historique()},
                             headers={"Cache-Control": "no-store"})


# ── WebSocket MyStrow (contrôleur) ──────────────────────────────────────────

def lire_ticket(ticket: str) -> dict | None:
    """{"uid", "cap", "exp"} si la signature est bonne et le ticket pas expiré."""
    if not (TICKET_SECRET and ticket and "." in ticket):
        return None
    corps, sig = ticket.rsplit(".", 1)
    attendu = hmac.new(TICKET_SECRET.encode(), corps.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, attendu):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(corps + "=" * (-len(corps) % 4)))
    except ValueError:
        return None
    return data if float(data.get("exp", 0)) > time.time() else None


async def ws_ctl(request):
    t = lire_ticket(request.query.get("ticket", ""))
    if not t:
        # Pas de compte MyStrow (ou ticket faux / expiré) = pas de session.
        return web.Response(status=403, text="compte MyStrow requis")
    proprio, cap = f"uid:{t.get('uid')}", max(1, min(CAP_MAX, int(t.get("cap", CAP_ESSAI))))

    sid_fixe = str(t.get("sid") or "") if t else ""
    if sid_fixe and not (len(sid_fixe) == 10 and sid_valide(sid_fixe)):
        sid_fixe = ""
    if sid_fixe:
        # QR permanent : le ticket signé désigne le code ET son propriétaire.
        # Session déjà ouverte (même compte) → on la reprend, sinon on la crée.
        s = SESSIONS.get(sid_fixe)
        if s is not None and s.proprio != proprio:
            return web.Response(status=409, text="code utilisé par un autre compte")
        if s is None:
            s = Session(sid_fixe, cap)
            s.proprio = proprio
            SESSIONS[s.sid] = s
        s.cap = cap
    else:
        # Reprise d'une session (coupure réseau du PC) : il faut le jeton contrôleur
        # remis à la création. Le sid seul ne suffit pas : il est public (dans le QR).
        s = SESSIONS.get(request.query.get("sid", ""))
        if s is not None and not hmac.compare_digest(request.query.get("ctok", ""), s.ctl_tok):
            s = None
        if s is None:
            actives = sum(1 for x in SESSIONS.values() if x.proprio == proprio)
            if actives >= MAX_SESSIONS_PAR_PROPRIO:
                return web.Response(status=429, text="trop de sessions ouvertes")
            s = Session(nouvel_id(), cap)
            s.proprio = proprio
            SESSIONS[s.sid] = s

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    if s.ctl is not None and not s.ctl.closed:
        await s.ctl.close()
    s.ctl, s.ctl_vu = ws, time.time()
    await ws.send_json({"t": "session", "sid": s.sid, "cap": s.cap, "ctok": s.ctl_tok})
    await s.compte_au_ctl()
    print(f"[ctl] session {s.sid} ouverte ({len(SESSIONS)} au total)")

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            s.ctl_vu = time.time()
            debut, n = s._fenetre
            if time.time() - debut > 1:
                s._fenetre = (time.time(), 1)
            elif n >= MAX_CTL_MSG_S:
                continue
            else:
                s._fenetre = (debut, n + 1)
            try:
                m = json.loads(msg.data)
            except ValueError:
                continue
            if m.get("t") == "s":
                zones = [[max(0, min(255, int(v))) for v in z[:5]]
                         for z in (m.get("z") or [])[:MAX_ZONES] if len(z) >= 5]
                if not zones:
                    continue
                s.nz = len(zones)
                out = {"t": "s", "at": now_ms() + DELAI_MS, "z": zones}
                s.last = out
                await s.diffuser(out)
            elif m.get("t") == "stop":
                await s.diffuser({"t": "end"})
                for w in list(s.phones.values()):
                    if w is not None:
                        await w.close()
                SESSIONS.pop(s.sid, None)
                s.archiver("arrêtée")
                print(f"[ctl] session {s.sid} terminée par MyStrow")
                break
    finally:
        if s.ctl is ws:
            s.ctl = None
            s.ctl_vu = time.time()
    return ws


# ── WebSocket téléphone ─────────────────────────────────────────────────────

async def ws_phone(request):
    sid = request.match_info["sid"]
    s = SESSIONS.get(sid)
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    if s is None:
        # QR permanent scanné avant le début : le téléphone patiente et réessaie.
        await ws.send_json({"t": "wait"} if len(sid) == 10 and sid_valide(sid) else {"t": "end"})
        await ws.close()
        return ws

    tok = request.query.get("tok", "")
    revenant = tok in s.phones
    if not revenant:
        if s.places_prises() >= s.cap:
            await ws.send_json({"t": "full", "cap": s.cap})
            await ws.close()
            return ws
        tok = secrets.token_urlsafe(12)
        s.zone_of[tok] = s.zone_libre()
        s.total += 1
    elif s.phones.get(tok) is not None:
        try:
            await s.phones[tok].close()   # même téléphone, ancien onglet
        except Exception:
            pass
    s.phones[tok] = ws
    s.pic = max(s.pic, s.connectes())
    zone = s.zone_of.get(tok, 0) % max(1, s.nz)
    await ws.send_json({"t": "hello", "tok": tok, "zone": zone, "srv": now_ms()})
    if s.last:
        await ws.send_json({**s.last, "at": now_ms()})
    await s.compte_au_ctl()

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            # Seul message accepté d'un téléphone : le ping de synchro d'horloge.
            try:
                m = json.loads(msg.data)
            except ValueError:
                continue
            if m.get("t") == "p":
                await ws.send_json({"t": "p", "c": m.get("c"), "s": now_ms()})
            elif m.get("t") == "bye":
                # « Quitter » sur le téléphone : place libérée tout de suite
                # (pas de garde de 60 s, réservée aux coupures réseau).
                s.phones.pop(tok, None)
                s.vu.pop(tok, None)
                s.zone_of.pop(tok, None)
                await s.compte_au_ctl()
                break
    finally:
        if s.phones.get(tok) is ws:
            s.phones[tok] = None
            s.vu[tok] = time.time()
            await s.compte_au_ctl()
    return ws


# ── Ménage ──────────────────────────────────────────────────────────────────

async def menage(app):
    async def boucle():
        while True:
            await asyncio.sleep(30)
            t = time.time()
            for sid, s in list(SESSIONS.items()):
                orpheline = s.ctl is None and t - s.ctl_vu > SESSION_ORPHELINE_S
                if orpheline or t - s.cree > SESSION_MAX_S:
                    await s.diffuser({"t": "end"})
                    SESSIONS.pop(sid, None)
                    s.archiver("MyStrow absent 10 min" if orpheline else "durée max (6 h)")
                    print(f"[ménage] session {sid} fermée")
                    continue
                for k in [k for k, w in s.phones.items()
                          if w is None and t - s.vu.get(k, 0) > GARDE_PLACE_S]:
                    s.phones.pop(k, None)
                    s.vu.pop(k, None)
                    s.zone_of.pop(k, None)
    tache = asyncio.create_task(boucle())
    yield
    tache.cancel()
    # Arrêt / redémarrage du service : les sessions en cours sont perdues, on
    # les note quand même pour que l'historique reste complet.
    for s in list(SESSIONS.values()):
        s.archiver("redémarrage du serveur")


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/live/{sid}", page_live)
    app.router.add_get("/ws/ctl", ws_ctl)
    app.router.add_get("/ws/p/{sid}", ws_phone)
    app.router.add_get("/health", sante)
    app.router.add_get("/stats", stats)
    app.cleanup_ctx.append(menage)
    return app


if __name__ == "__main__":
    print(f"MyStrow Light — relais sur le port {PORT} (licence {CAP_MAX} / essai {CAP_ESSAI} téléphones)"
          + ("" if TICKET_SECRET else " ⚠ UP_TICKET_SECRET absent : tout le monde en essai"))
    # Arrêt rapide : sans ça, un redémarrage attendait 30 s la fin des
    # WebSockets ouverts (téléphones + MyStrow restent reconnectés tout seuls).
    web.run_app(make_app(), host=HOST, port=PORT, print=None, shutdown_timeout=2)
