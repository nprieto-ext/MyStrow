"""Patch et effets synchronisés avec le compte MyStrow — façon iCloud.

Demande du 13/10/2026 : « encore plus intuitif, à la Apple — j'ai fait un
patch sur un compte, hop ça l'enregistre sur mon compte ». Aucun bouton :
connecté, le patch et les effets suivent le compte d'un PC à l'autre.

  - ENVOI : un minuteur de la fenêtre principale (`MainWindow`) regarde la
    date des fichiers ; ce qui a changé part en arrière-plan, après
    `QUIET_S` secondes sans nouvelle modification.
  - RÉCUPÉRATION : au démarrage, pendant le splash (comme la licence), AVANT
    que la fenêtre ne charge le patch. Pas de rechargement à chaud en plein
    spectacle : ce qu'un autre PC envoie pendant la session arrive au
    lancement suivant.
  - Une seule question, une seule fois par PC : à la première connexion d'un
    PC qui a déjà SON patch, différent de celui du compte (comme iCloud qui
    demande quoi faire des contacts déjà sur le Mac).

⚠️ HORS CONNEXION, RIEN NE DOIT BLOQUER NI MOULINER (exigence du 13/10) :
  - le réseau ne tourne QUE dans des threads ; le thread principal ne fait que
    des `stat` et de la lecture de petits fichiers locaux ;
  - au démarrage, le splash attend au plus `PULL_DEADLINE_S` ; trop tard, on
    démarre avec les fichiers locaux, et le résultat tardif est ignoré
    (c'est le thread principal qui écrit, jamais le thread réseau) ;
  - un envoi raté attend `RETRY_AFTER_S` avant le suivant ; les fichiers
    restent « à envoyer » et partiront au retour du réseau, même au lancement
    suivant.

SOBRIÉTÉ FIRESTORE (13/10/2026, « ça va pas coûter cher ? ») : le poste qui
grossit est la bande passante — chaque lecture rapatrie tout le document.
  - Lecture en deux temps : d'abord la seule date (`updated_utc`, quelques
    octets via `mask.fieldPaths`) ; le contenu n'est téléchargé que s'il a
    changé depuis la dernière fois. Le dernier contenu vu est gardé en cache
    local (`CACHE_FILE`). Un lancement sans changement ne coûte presque rien.
  - Contenu compressé (zlib + base64, préfixe `z1:`), ~5× plus petit.
  - Envoi groupé : `QUIET_S` secondes de calme avant d'envoyer — éditer un
    effet pendant dix minutes fait UN envoi, pas cent.

Ce qui est synchronisé : le patch (`~/.maestro_dmx_patch.json`, profils
complets de chaque projecteur inclus — pas besoin de la bibliothèque de
fixtures), les effets (éditeur, bibliothèque modifiée, boutons E1-E8) et,
depuis le 09/11/2026, les mémoires et pages AKAI. Celles-ci vivent dans
`~/.maestro_akai_config.json`, qui mélange contenu (mémoires, pages, pads FX,
positions) et réglages PROPRES AU PC (vMix/OBS, manette, décalage audio,
luminosité de l'APC…) : seules les clés de `PARTIAL` voyagent, le reste du
fichier n'est jamais touché. Les shows (.tui, médias) ne sont pas synchronisés.

Fiche du nuage, deux boutons :
  - « Synchroniser maintenant » : envoie tout de suite et regarde si un autre
    PC a envoyé du neuf (nuage ☁ ↓ jaune) ;
  - « Importer depuis le compte » : remplace ce PC par le contenu du compte,
    après confirmation. Mémoires/pages AKAI rechargées à chaud ; patch et
    effets → redémarrage (l'appli les garde en mémoire et les réécrirait).

Stockage : Firestore `user_sync/{uid}` {payload, updated_utc}. `payload` =
`{"files": {clé: {"content": texte, "sha": …, "utc": …}}}` en JSON, compressé.
Règle : chacun ne lit et n'écrit que le sien (firestore.rules).

Tablette : la copie au format tablette (`user_configs/{uid}`) n'est écrite
que pour les comptes qui utilisent l'app tablette. Celle-ci pose une marque
`tablet_utc` dans `user_sync/{uid}` (connexion, « Importer ») ; le PC la lit
avec la date, sans appel en plus, et copie dès qu'il la voit.
"""

import base64
import hashlib
import json
import os
import shutil
import threading
import time
import zlib
from pathlib import Path

_HOME = Path.home()

# Clé de synchro → fichier local. Les clés sont figées : elles sont stockées
# dans le compte, les renommer orphelinerait les sauvegardes existantes.
FILES = {
    "patch":          _HOME / ".maestro_dmx_patch.json",
    "fx_custom":      _HOME / ".mystrow_custom_effects.json",
    "fx_library":     _HOME / ".mystrow_effect_library.json",
    "fx_assignments": _HOME / ".mystrow_effect_assignments.json",
    "akai":           _HOME / ".maestro_akai_config.json",
}

# Fichiers dont seule une partie des clés JSON voyage (le reste est propre au PC).
PARTIAL = {
    "akai": ("memories", "memory_custom_colors", "bank_pages",
             "fx_pads", "position_presets", "position_pads"),
}

STATE_FILE = _HOME / ".mystrow_cloud_sync.json"
CACHE_FILE = _HOME / ".mystrow_cloud_sync_cache.json"
COLLECTION = "user_sync"
PAYLOAD_MAX = 900_000          # un document Firestore plafonne à 1 Mio
PULL_DEADLINE_S = 4.0          # attente max au splash
RETRY_AFTER_S = 120.0          # après un échec réseau
QUIET_S = 30.0                 # calme avant d'envoyer une modification
NET_TIMEOUT_S = 6              # par requête, dans les threads


# ── Fichiers locaux ──────────────────────────────────────────────────────────

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canon(sub: dict) -> str:
    """Texte stable d'une partie de fichier : même contenu → même sha."""
    return json.dumps(sub, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_local(key: str):
    """(texte, sha, mtime) du fichier local, ou (None, None, 0) s'il manque.

    Fichier partiel (`PARTIAL`) : le texte est la seule partie synchronisée.
    """
    path = FILES[key]
    try:
        text = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
    except (OSError, UnicodeDecodeError):
        return None, None, 0.0
    keys = PARTIAL.get(key)
    if keys is not None:
        try:
            full = json.loads(text)
        except ValueError:
            return None, None, 0.0
        if not isinstance(full, dict):
            return None, None, 0.0
        sub = {k: full[k] for k in keys if k in full}
        if not sub:
            return None, None, 0.0
        text = _canon(sub)
    return text, _sha(text), mtime


def _is_valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (TypeError, ValueError):
        return False


def write_local(key: str, text: str) -> bool:
    """Remplace un fichier local par la version du compte.

    Copie de sécurité d'abord (`.avant-synchro-AAAAMMJJ-HHMMSS`), puis écriture
    atomique (fichier temporaire + `os.replace`) : une coupure au mauvais
    moment ne laisse jamais un patch à moitié écrit.
    """
    if not _is_valid_json(text):
        return False
    path = FILES[key]
    keys = PARTIAL.get(key)
    if keys is not None:
        # Partiel : on ne remplace QUE les clés synchronisées, le reste du
        # fichier (réglages de ce PC) est conservé tel quel.
        sub = json.loads(text)
        if not isinstance(sub, dict):
            return False
        full = {}
        try:
            cur = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                full = cur
        except (OSError, ValueError, UnicodeDecodeError):
            pass
        for k in keys:
            full.pop(k, None)
        full.update({k: v for k, v in sub.items() if k in keys})
        text = json.dumps(full, indent=2)
    try:
        if path.exists():
            bak = path.with_name(path.name + time.strftime(".avant-synchro-%Y%m%d-%H%M%S"))
            shutil.copy2(path, bak)
        tmp = path.with_name(path.name + ".synchro-tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as e:
        print(f"[CloudSync] écriture {path.name} impossible : {e}")
        return False


# ── Format du contenu dans le compte ─────────────────────────────────────────

def encode_payload(files: dict) -> str:
    raw = json.dumps({"files": files}, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    return "z1:" + base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def decode_payload(text: str) -> dict:
    """{clé: entrée} lisible ; lève ValueError si le contenu est illisible."""
    if text.startswith("z1:"):
        text = zlib.decompress(base64.b64decode(text[3:])).decode("utf-8")
    files = (json.loads(text or "{}") or {}).get("files") or {}
    # Les clés inconnues sont GARDÉES : une version plus récente de l'appli a
    # pu en ajouter, et les jeter ici les effacerait du compte au prochain envoi.
    return {k: v for k, v in files.items()
            if isinstance(v, dict) and isinstance(v.get("content"), str)}


# ── État de synchro et cache (par PC) ────────────────────────────────────────

def load_state() -> dict:
    """{"uid": …, "synced": {clé: sha envoyé/reçu}, "asked": bool}."""
    try:
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(st, dict):
            st.setdefault("synced", {})
            return st
    except (OSError, ValueError):
        pass
    return {"uid": None, "synced": {}, "asked": False}


def save_state(state: dict):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError as e:
        print(f"[CloudSync] état non enregistré : {e}")


def state_for(uid: str) -> dict:
    """État de ce PC pour CE compte : changer de compte repart de zéro."""
    st = load_state()
    if st.get("uid") != uid:
        st = {"uid": uid, "synced": {}, "asked": False}
    return st


def load_cache(uid: str):
    """Dernier contenu du compte vu par ce PC : (updated_utc, files) ou None."""
    try:
        c = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if c.get("uid") == uid:
            return float(c["utc"]), decode_payload(c["payload"])
    except (OSError, ValueError, KeyError, TypeError, zlib.error):
        pass
    return None


def summary() -> dict:
    """Pour la fiche du nuage (thread principal, sans réseau) :
    {"email": compte connecté, "last_utc": dernière sauvegarde connue du compte}."""
    out = {"email": None, "last_utc": None}
    try:
        import license_manager as lm
        acc = lm._load_account(lm.get_machine_id()) or {}
        out["email"] = acc.get("email")
        uid = acc.get("uid")
    except Exception:
        uid = None
    if uid:
        try:
            c = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if c.get("uid") == uid:
                out["last_utc"] = float(c["utc"]) or None
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def save_cache(uid: str, utc: float, files: dict):
    """Thread principal uniquement (les threads réseau ne font que lire)."""
    try:
        CACHE_FILE.write_text(json.dumps({"uid": uid, "utc": utc,
                                          "payload": encode_payload(files)}),
                              encoding="utf-8")
    except OSError as e:
        print(f"[CloudSync] cache non enregistré : {e}")


# ── Compte et réseau (threads seulement) ─────────────────────────────────────

def account_uid():
    """uid du compte connecté sur ce PC, sans réseau (fichier local)."""
    try:
        import license_manager as lm
        acc = lm._load_account(lm.get_machine_id())
        return (acc or {}).get("uid") or None
    except Exception:
        return None


def _token():
    """Jeton frais — RÉSEAU : à n'appeler que depuis un thread."""
    import license_manager as lm
    return lm.get_current_id_token()


def _doc_url(uid: str) -> str:
    import firebase_client as fc
    return f"{fc._FS_BASE}/{COLLECTION}/{uid}"


def _get_doc(uid: str, token: str, mask: str = None):
    """Document Firestore → dict, {} s'il n'existe pas, None si injoignable."""
    import urllib.error
    import urllib.request
    import firebase_client as fc
    if isinstance(mask, str):
        mask = (mask,)
    url = _doc_url(uid) + ("?" + "&".join(f"mask.fieldPaths={m}" for m in mask) if mask else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT_S,
                                    context=fc._SSL_CTX) as resp:
            return fc._doc_to_dict(json.loads(resp.read().decode()))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        print(f"[CloudSync] lecture refusée : {e.code}")
        return None
    except Exception as e:
        print(f"[CloudSync] compte injoignable : {e}")
        return None


def fetch_remote(uid: str, known=None, token=None):
    """Contenu du compte : (files, updated_utc). RÉSEAU (thread).

    `known` = cache (updated_utc, files) : si la date du compte n'a pas
    bougé, on le renvoie sans télécharger le contenu. Renvoie ({}, 0.0) si le
    compte n'a encore rien, None si injoignable ou illisible.
    """
    token = token or _token()
    if not token:
        return None
    head = _get_doc(uid, token, mask=("updated_utc", "tablet_utc"))
    if head is None:
        return None
    if head.get("tablet_utc"):
        _TABLET_SEEN[uid] = float(head["tablet_utc"])
    if not head.get("updated_utc"):
        return {}, 0.0
    utc = float(head.get("updated_utc") or 0)
    if known is not None and known[0] == utc:
        return known[1], utc
    doc = _get_doc(uid, token)
    if doc is None:
        return None
    try:
        return decode_payload(doc.get("payload") or "{}"), float(doc.get("updated_utc") or 0)
    except Exception as e:
        print(f"[CloudSync] contenu du compte illisible : {e}")
        return None


def push(uid: str, local: dict, known=None):
    """Envoie les fichiers locaux, fusionnés avec ce que le compte a déjà.

    `local` : {clé: {content, sha, utc}}. RÉSEAU (thread). Fusion fichier par
    fichier, le plus récent gagne : un autre PC a pu envoyer entre-temps.
    Renvoie (pris, files, updated_utc) — `pris` = {clé: sha} des fichiers
    locaux désormais dans le compte, `files`/`updated_utc` = nouveau contenu
    du compte (pour le cache) — ou None en cas d'échec.
    """
    import urllib.request
    import firebase_client as fc
    token = _token()
    if not token:
        return None
    res = fetch_remote(uid, known=known, token=token)
    if res is None:
        return None
    remote, _utc = res
    merged = dict(remote)
    pris = {}
    for k, ent in local.items():
        r = remote.get(k)
        if r is None or r.get("sha") == ent["sha"] or ent["utc"] >= float(r.get("utc") or 0):
            merged[k] = ent
            pris[k] = ent["sha"]
    # Un fichier absent du compte alors que ce PC l'a : une ancienne version
    # de l'appli sur un autre PC a pu l'effacer en ne le connaissant pas.
    # On le remet (lecture seule des fichiers locaux, sans risque en thread).
    for k in FILES:
        if k not in merged:
            t, sha, mtime = read_local(k)
            if t is not None and _is_valid_json(t):
                merged[k] = {"content": t, "sha": sha, "utc": mtime}
                pris[k] = sha
    text = encode_payload(merged)
    if len(text) > PAYLOAD_MAX:
        print("[CloudSync] contenu trop gros pour le compte (> 900 Ko)")
        return None
    now = time.time()
    body = json.dumps({"fields": fc._dict_to_fields({
        "payload": text, "updated_utc": now})}).encode("utf-8")
    # updateMask : ne réécrit que ces deux champs, la marque `tablet_utc`
    # posée par la tablette reste.
    req = urllib.request.Request(
        _doc_url(uid) + "?updateMask.fieldPaths=payload&updateMask.fieldPaths=updated_utc",
        data=body, method="PATCH",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT_S, context=fc._SSL_CTX):
            pass
    except Exception as e:
        print(f"[CloudSync] envoi impossible : {e}")
        return None
    return pris, merged, now


# Comptes dont la tablette a laissé sa marque (`tablet_utc` dans user_sync,
# posée par l'app tablette à la connexion et à chaque « Importer »). Rempli
# par `fetch_remote` (même lecture que la date : aucun appel en plus).
_TABLET_SEEN = {}


def tablet_seen(uid: str, state: dict) -> float:
    """Date de la dernière marque de la tablette (0 : jamais vue)."""
    return max(float(state.get("tablet_utc") or 0), _TABLET_SEEN.get(uid, 0.0))


def mirror_to_tablet() -> bool:
    """Recopie la config au format de la tablette (`user_configs/{uid}`, lu
    par le bouton « Importer depuis mon compte » de l'app). RÉSEAU (thread).
    Seulement pour les comptes qui utilisent la tablette (`tablet_seen`) :
    rien d'écrit sur le serveur pour les autres. Un échec ici ne touche pas
    à la synchro du PC."""
    try:
        import socket
        import tablet_cloud
        tablet_cloud.upload(label=socket.gethostname())
        return True
    except Exception as e:
        print(f"[CloudSync] copie pour la tablette impossible : {e}")
        return False


# ── Décision au démarrage (pure : aucun réseau, aucune écriture) ─────────────

def plan_pull(remote: dict, state: dict) -> dict:
    """Que faire de chaque fichier au démarrage ?

    Renvoie {"take": [clés à prendre du compte], "conflicts": [clés où ce PC
    ET le compte ont changé sans s'être vus], "synced": {clé: sha déjà
    identique des deux côtés}}.

    Règles, par fichier (L = local, R = compte, S = dernier sha échangé) :
      - rien au compte : rien à prendre (l'envoi s'en chargera) ;
      - L == R : déjà à jour ;
      - pas de fichier local, ou L == S (ce PC n'a rien changé) : on prend R ;
      - R == S (le compte n'a pas bougé) : on garde L, il partira ;
      - les deux ont bougé : conflit.
    """
    take, conflicts, synced = [], [], {}
    S = state.get("synced") or {}
    for k in FILES:
        r = remote.get(k)
        if not r:
            continue
        text, L, _m = read_local(k)
        R = r.get("sha")
        if L == R:
            synced[k] = L
        elif text is None or not text.strip() or L == S.get(k):
            take.append(k)
        elif R == S.get(k):
            continue
        else:
            conflicts.append(k)
    return {"take": take, "conflicts": conflicts, "synced": synced}


def resolve_conflicts_by_date(remote: dict, conflicts: list) -> list:
    """Hors première fois : le plus récent gagne. Renvoie les clés à prendre."""
    take = []
    for k in conflicts:
        _t, _s, mtime = read_local(k)
        if float(remote[k].get("utc") or 0) > mtime:
            take.append(k)
    return take


def apply_take(remote: dict, keys: list, state: dict) -> list:
    """Écrit les fichiers du compte retenus. Renvoie ceux réellement écrits."""
    ok = []
    for k in keys:
        if write_local(k, remote[k]["content"]):
            state["synced"][k] = remote[k].get("sha") or _sha(remote[k]["content"])
            ok.append(k)
    return ok


def remote_news(remote: dict, state: dict) -> list:
    """Fichiers que le compte a en plus récent que ce PC (envoyés par un autre
    PC), à récupérer au prochain démarrage. Thread principal (lit le disque)."""
    S = state.get("synced") or {}
    out = []
    for k in FILES:
        r = remote.get(k)
        if not r or r.get("sha") == S.get(k):
            continue
        _t, L, _m = read_local(k)
        if r.get("sha") != L:
            out.append(k)
    return out


def import_plan(remote: dict) -> list:
    """« Importer depuis le compte » : fichiers dont la version du compte
    diffère de ce PC. Thread principal (lit le disque, pas le réseau)."""
    out = []
    for k in FILES:
        r = remote.get(k)
        if r and r.get("sha") != read_local(k)[1]:
            out.append(k)
    return out


def import_apply(uid: str, remote: dict, utc: float, keys: list) -> list:
    """Écrit les fichiers du compte choisis (copie de sécurité avant chacun).
    Thread principal. Renvoie les clés réellement écrites."""
    state = state_for(uid)
    written = apply_take(remote, keys, state)
    state["asked"] = True
    asked_keys = state.setdefault("asked_keys", [])
    asked_keys.extend(k for k in written if k not in asked_keys)
    save_state(state)
    if utc:
        save_cache(uid, utc, remote)
    if written:
        print(f"[CloudSync] importé depuis le compte : {', '.join(written)}")
    return written


def local_changes(state: dict) -> dict:
    """Fichiers locaux différents de ce que le compte a reçu : à envoyer."""
    out = {}
    S = state.get("synced") or {}
    for k in FILES:
        text, sha, mtime = read_local(k)
        if text is None or sha == S.get(k) or not _is_valid_json(text):
            continue
        out[k] = {"content": text, "sha": sha, "utc": mtime}
    return out


# ── Démarrage : téléchargement en thread, décision sur le thread principal ──

class StartupPull:
    """Lance la lecture du compte en arrière-plan dès le splash.

    `start()` n'attend rien. `result()` renvoie (files, updated_utc) si la
    lecture a fini, sinon None — l'appelant (le splash) décide combien de
    temps il attend, jamais plus de `PULL_DEADLINE_S`.
    """

    def __init__(self):
        self.uid = account_uid()
        self._box = [None]
        self._done = threading.Event()

    def start(self):
        if not self.uid:
            self._done.set()
            return self
        known = load_cache(self.uid)     # lu ici, sur le thread principal

        def _run():
            try:
                self._box[0] = fetch_remote(self.uid, known=known)
            except Exception as e:
                print(f"[CloudSync] démarrage : {e}")
            finally:
                self._done.set()

        threading.Thread(target=_run, daemon=True, name="cloud-pull").start()
        return self

    def done(self) -> bool:
        return self._done.is_set()

    def result(self):
        return self._box[0] if self._done.is_set() else None


def finish_startup_pull(puller: StartupPull, ask_first_time=None) -> list:
    """À appeler sur le thread principal, AVANT de créer la fenêtre.

    `ask_first_time(conflicts)` → True pour prendre le compte, False pour
    garder ce PC ; appelée au plus une fois par PC et par compte. Renvoie les
    clés écrites depuis le compte.
    """
    res = puller.result()
    if not puller.uid or not res:
        return []
    remote, utc = res
    if utc:
        save_cache(puller.uid, utc, remote)
    if not remote:
        return []
    state = state_for(puller.uid)
    plan = plan_pull(remote, state)
    state["synced"].update(plan["synced"])
    take = list(plan["take"])
    if plan["conflicts"]:
        # La question est posée une fois par PC… et à nouveau pour un fichier
        # que ce PC n'a JAMAIS échangé (ex. mémoires ajoutées le 09/11) : le
        # « plus récent gagne » y serait faux — la config AKAI est réécrite à
        # chaque fermeture, sa date ne dit rien des mémoires.
        S = state.get("synced") or {}
        asked_keys = state.setdefault("asked_keys", [])
        new_keys = [k for k in plan["conflicts"]
                    if not S.get(k) and k not in asked_keys]
        if (not state.get("asked") or new_keys) and ask_first_time is not None:
            if ask_first_time(plan["conflicts"]):
                take += plan["conflicts"]
            # Garder ce PC : rien à prendre, ses fichiers partiront à l'envoi.
            asked_keys.extend(k for k in plan["conflicts"] if k not in asked_keys)
        else:
            take += resolve_conflicts_by_date(remote, plan["conflicts"])
    state["asked"] = True
    written = apply_take(remote, take, state)
    save_state(state)
    if written:
        print(f"[CloudSync] récupéré depuis le compte : {', '.join(written)}")
    return written


# ── Envoi pendant la session ─────────────────────────────────────────────────

class Pusher:
    """Envoi en arrière-plan, piloté par un minuteur Qt (`tick`).

    `tick()` est appelé sur le thread principal toutes les quelques secondes :
    il ne fait que des `stat` tant que rien ne change. Une modification part
    après `QUIET_S` secondes de calme ; un seul envoi à la fois, et une pause
    de `RETRY_AFTER_S` après un échec (hors ligne).
    """

    def __init__(self):
        self._mtimes = None        # None : premier passage, rien n'a « changé »
        self._last_change = 0.0
        self._thread = None
        self._result = None
        self._retry_at = 0.0
        self._force = False
        self.news = []         # fichiers plus récents dans le compte (autre PC)
        self._imp_thread = None
        self._imp_box = None
        self.status = "idle"   # idle | pending | sending | ok | offline | off

    def sync_now(self):
        """« Synchroniser maintenant » : envoi immédiat (sans attendre le calme
        ni la pause hors ligne) + vérification de ce que le compte a de neuf.
        Le travail se fait au prochain `tick`, réseau en thread comme toujours."""
        self._force = True
        self._retry_at = 0.0
        self._last_change = 0.0

    def _mtimes_now(self) -> dict:
        out = {}
        for k, p in FILES.items():
            try:
                out[k] = p.stat().st_mtime
            except OSError:
                out[k] = 0.0
        return out

    def request_import(self) -> bool:
        """Lit le compte en arrière-plan pour « Importer ». Résultat via
        `take_import_result()`. False si pas de compte ou déjà en cours."""
        if self._imp_thread is not None:
            return False
        uid = account_uid()
        if not uid:
            return False
        known = load_cache(uid)
        box = self._imp_box = [uid, None]

        def _run():
            try:
                box[1] = fetch_remote(uid, known=known)
            except Exception as e:
                print(f"[CloudSync] import : {e}")

        self._imp_thread = threading.Thread(target=_run, daemon=True, name="cloud-import")
        self._imp_thread.start()
        return True

    def take_import_result(self):
        """(uid, (files, utc) ou None si injoignable) une fois la lecture
        finie ; None tant qu'elle tourne ou si rien n'a été demandé."""
        if self._imp_thread is None or self._imp_thread.is_alive():
            return None
        self._imp_thread = None
        return tuple(self._imp_box)

    def tick(self, now: float = None) -> str:
        """État affiché : comme `status`, mais « news » quand tout est envoyé
        et qu'un autre PC a mis du neuf dans le compte."""
        st = self._tick(now)
        return "news" if (st == "ok" and self.news) else st

    def _tick(self, now: float = None) -> str:
        now = time.time() if now is None else now
        # Résultat d'un envoi terminé : enregistré ici, sur le thread principal
        # (état et cache ne sont écrits que d'un seul fil).
        if self._thread is not None and not self._thread.is_alive():
            uid, sent, res, remote, tab, mirrored = self._result
            self._thread = None
            if tab or mirrored:
                st = state_for(uid)
                if tab:
                    st["tablet_utc"] = tab
                if mirrored:
                    st["tablet_mirrored"] = mirrored
                save_state(st)
            if (sent and res is None) or (not sent and remote is None):
                self.status = "offline"
                self._retry_at = now + RETRY_AFTER_S
            else:
                st = state_for(uid)
                if res is not None:
                    pris, files, utc = res
                    st["synced"].update(pris)
                    save_state(st)
                    save_cache(uid, utc, files)
                elif remote is not None and remote[1]:
                    save_cache(uid, remote[1], remote[0])
                if remote is not None:
                    self.news = remote_news(remote[0], st)
                self.status = "ok"
                self._retry_at = 0.0
        if self._thread is not None:
            return self.status

        uid = account_uid()
        if not uid:
            self.status = "off"
            return self.status
        mt = self._mtimes_now()
        if self._mtimes is not None and mt != self._mtimes:
            # La config AKAI est réécrite pour un rien (luminosité, vue…) :
            # « en attente » seulement si une partie synchronisée a bougé.
            if local_changes(state_for(uid)):
                self._last_change = now
                if self.status != "offline":
                    self.status = "pending"
        first = self._mtimes is None
        self._mtimes = mt
        force = self._force
        if not (first or force or self.status in ("idle", "pending", "offline")):
            return self.status
        if not force and (now < self._retry_at or now - self._last_change < QUIET_S):
            return self.status
        self._force = False
        state = state_for(uid)
        local = local_changes(state)
        tab = tablet_seen(uid, state)
        mirrored = float(state.get("tablet_mirrored") or 0)
        # Tablette vue depuis la dernière copie (ex. « Importer » n'a rien
        # trouvé) : la copie part même sans rien de neuf sur ce PC.
        mirror_due = bool(tab) and tab > mirrored
        if not local and not force and not mirror_due:
            if self.status in ("idle", "pending"):
                self.status = "ok"
            return self.status

        self.status = "sending"
        known = load_cache(uid)
        sent = bool(local)
        self._result = (uid, sent, None, None, 0.0, 0.0)

        def _run():
            res = remote = None
            tab_now = done = 0.0
            try:
                if sent:
                    res = push(uid, local, known=known)
                    if res is not None:
                        remote = (res[1], res[2])
                else:
                    remote = fetch_remote(uid, known=known)
                # La lecture vient peut-être de découvrir la tablette.
                tab_now = max(tab, _TABLET_SEEN.get(uid, 0.0))
                if remote is not None and tab_now and (res is not None or tab_now > mirrored):
                    if mirror_to_tablet():
                        done = time.time()
            except Exception as e:
                print(f"[CloudSync] envoi : {e}")
            finally:
                self._result = (uid, sent, res, remote, tab_now, done)

        self._thread = threading.Thread(target=_run, daemon=True, name="cloud-push")
        self._thread.start()
        return self.status
