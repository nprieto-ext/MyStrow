"""
Client Firebase HTTP pour MyStrow.
Wrapper urllib uniquement (pas de SDK Firebase).
Couvre : Auth (email/password) + Firestore REST API.
"""

import json
import time
import socket
import urllib.request
import urllib.error
from datetime import datetime, timezone

# Importé depuis core pour éviter la circularité
from core import FIREBASE_API_KEY, FIREBASE_PROJECT_ID

# ---------------------------------------------------------------
# URLs de base
# ---------------------------------------------------------------
_AUTH_BASE = "https://identitytoolkit.googleapis.com/v1"
_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
_FS_BASE = (
    f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
    f"/databases/(default)/documents"
)

_TIMEOUT = 5  # secondes (réduit de 10 à 5)


def has_internet(timeout: float = 1.5) -> bool:
    """Test rapide de connectivité avant d'essayer Firebase (DNS Google)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)  # timeout local uniquement, pas global
        s.connect(("8.8.8.8", 53))
        s.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------

def _post_json(url, payload: dict, id_token: str = None) -> dict:
    """POST JSON vers une URL, retourne le dict réponse ou lève une exception."""
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _get_json(url, id_token: str) -> dict:
    """GET JSON avec Bearer token."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {id_token}"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _patch_json(url, payload: dict, id_token: str) -> dict:
    """PATCH JSON (Firestore update partiel)."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {id_token}",
        },
        method="PATCH"
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _firebase_error(e: urllib.error.HTTPError) -> str:
    """Extrait le message d'erreur Firebase d'une HTTPError."""
    try:
        body = json.loads(e.read().decode())
        return body.get("error", {}).get("message", str(e))
    except Exception:
        return str(e)


# ---------------------------------------------------------------
# Conversion Firestore ↔ Python
# ---------------------------------------------------------------

def _to_firestore(value) -> dict:
    """Convertit une valeur Python en champ Firestore."""
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_to_firestore(v) for v in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {k: _to_firestore(v) for k, v in value.items()}}}
    return {"nullValue": None}


def _from_firestore(field: dict):
    """Convertit un champ Firestore en valeur Python."""
    if "stringValue" in field:
        return field["stringValue"]
    if "integerValue" in field:
        return int(field["integerValue"])
    if "doubleValue" in field:
        return float(field["doubleValue"])
    if "booleanValue" in field:
        return field["booleanValue"]
    if "nullValue" in field:
        return None
    if "arrayValue" in field:
        return [_from_firestore(v) for v in field["arrayValue"].get("values", [])]
    if "mapValue" in field:
        return {k: _from_firestore(v) for k, v in field["mapValue"].get("fields", {}).items()}
    return None


def _doc_to_dict(doc: dict) -> dict:
    """Convertit un document Firestore complet en dict Python."""
    fields = doc.get("fields", {})
    return {k: _from_firestore(v) for k, v in fields.items()}


def _dict_to_fields(d: dict) -> dict:
    """Convertit un dict Python en champ 'fields' Firestore."""
    return {k: _to_firestore(v) for k, v in d.items()}


# ---------------------------------------------------------------
# Auth Firebase
# ---------------------------------------------------------------

def sign_up(email: str, password: str) -> dict:
    """
    Crée un compte Firebase avec email + mot de passe.
    Retourne {"uid": ..., "id_token": ..., "refresh_token": ...}
    ou lève une Exception avec un message lisible.
    """
    url = f"{_AUTH_BASE}/accounts:signUp?key={FIREBASE_API_KEY}"
    try:
        resp = _post_json(url, {
            "email": email,
            "password": password,
            "returnSecureToken": True,
        })
        return {
            "uid": resp["localId"],
            "id_token": resp["idToken"],
            "refresh_token": resp["refreshToken"],
            "email": resp.get("email", email),
        }
    except urllib.error.HTTPError as e:
        msg = _firebase_error(e)
        if "EMAIL_EXISTS" in msg:
            raise Exception("Un compte existe déjà avec cet email.")
        if "WEAK_PASSWORD" in msg:
            raise Exception("Mot de passe trop faible (6 caractères minimum).")
        if "INVALID_EMAIL" in msg:
            raise Exception("Adresse email invalide.")
        raise Exception(f"Erreur création compte : {msg}")


def sign_in(email: str, password: str) -> dict:
    """
    Connecte un compte Firebase.
    Retourne {"uid": ..., "id_token": ..., "refresh_token": ...}
    """
    url = f"{_AUTH_BASE}/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    try:
        resp = _post_json(url, {
            "email": email,
            "password": password,
            "returnSecureToken": True,
        })
        return {
            "uid": resp["localId"],
            "id_token": resp["idToken"],
            "refresh_token": resp["refreshToken"],
            "email": resp.get("email", email),
        }
    except urllib.error.HTTPError as e:
        msg = _firebase_error(e)
        if "EMAIL_NOT_FOUND" in msg or "INVALID_LOGIN_CREDENTIALS" in msg:
            raise Exception("Email ou mot de passe incorrect.")
        if "INVALID_PASSWORD" in msg:
            raise Exception("Mot de passe incorrect.")
        if "USER_DISABLED" in msg:
            raise Exception("Ce compte a été désactivé.")
        raise Exception(f"Erreur connexion : {msg}")


def refresh_id_token(refresh_token: str) -> dict:
    """
    Renouvelle l'ID token depuis un refresh token.
    Retourne {"uid": ..., "id_token": ...}
    """
    url = f"{_TOKEN_URL}?key={FIREBASE_API_KEY}"
    try:
        resp = _post_json(url, {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        return {
            "uid": resp["user_id"],
            "id_token": resp["id_token"],
            "refresh_token": resp.get("refresh_token", refresh_token),
        }
    except urllib.error.HTTPError as e:
        msg = _firebase_error(e)
        if "TOKEN_EXPIRED" in msg or "INVALID_REFRESH_TOKEN" in msg:
            raise Exception("Session expirée. Reconnectez-vous.")
        raise Exception(f"Erreur renouvellement token : {msg}")


def get_stripe_portal_url(id_token: str) -> str:
    """
    Crée une session Stripe Customer Portal et retourne l'URL.
    Lève une Exception en cas d'erreur.
    """
    url  = "https://us-central1-mystrow-907be.cloudfunctions.net/create_portal_session"
    data = json.dumps({"id_token": id_token}).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if not result.get("ok"):
                raise Exception(result.get("error", "Erreur inconnue"))
            return result["url"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"Erreur portail : {body}")


def send_password_reset(email: str) -> bool:
    """
    Envoie un email de réinitialisation stylisé via la Cloud Function MyStrow.
    """
    url  = "https://send-reset-email-2gdol7vjca-uc.a.run.app"
    data = json.dumps({"email": email}).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            if not result.get("ok"):
                raise Exception(result.get("error", "Erreur inconnue"))
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"Erreur envoi email : {body}")


# ---------------------------------------------------------------
# Firestore : document licence
# ---------------------------------------------------------------

def get_license_doc(uid: str, id_token: str) -> dict | None:
    """
    Lit le document /licenses/{uid} depuis Firestore.
    Retourne le dict Python du document, ou None si absent.
    """
    url = f"{_FS_BASE}/licenses/{uid}"
    try:
        doc = _get_json(url, id_token)
        return _doc_to_dict(doc)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise Exception(f"Erreur lecture Firestore : {_firebase_error(e)}")


def create_license_doc(uid: str, id_token: str, email: str) -> bool:
    """
    Crée le document /licenses/{uid} avec plan 'trial'.
    Appelé lors de la création de compte (register_account).
    Retourne True si succès.
    """
    now = datetime.now(timezone.utc).timestamp()
    doc_data = {
        "email": email,
        "plan": "trial",
        "expiry_utc": now + (15 * 86400),  # 15 jours d'essai
        "created_utc": now,
        "machines": [],
    }

    url = f"{_FS_BASE}/licenses/{uid}"
    payload = {"fields": _dict_to_fields(doc_data)}
    try:
        _patch_json(url, payload, id_token)
        return True
    except urllib.error.HTTPError as e:
        raise Exception(f"Erreur création document : {_firebase_error(e)}")


def add_machine(uid: str, id_token: str, machine_id: str, label: str = "") -> bool:
    """
    Ajoute machine_id dans /licenses/{uid}/machines si count < 2.
    - Si la machine est déjà présente : retourne True (rien à faire).
    - Si count >= 2 : lève Exception("2 appareils max atteint").
    - Sinon : ajoute et retourne True.
    """
    doc = get_license_doc(uid, id_token)
    if doc is None:
        raise Exception("Document de licence introuvable.")

    machines: list = doc.get("machines", [])

    # Déjà enregistrée ?
    for m in machines:
        if isinstance(m, dict) and m.get("id") == machine_id:
            return True

    # Limite atteinte ?
    if len(machines) >= 2:
        raise Exception(
            "2 appareils maximum autorisés pour ce compte.\n"
            "Déconnectez-vous d'un autre appareil pour continuer."
        )

    # Ajouter la machine
    machines.append({
        "id": machine_id,
        "label": label or machine_id[:16],
        "activated_at": datetime.now(timezone.utc).timestamp(),
    })

    # Mettre à jour uniquement le champ machines
    url = f"{_FS_BASE}/licenses/{uid}?updateMask.fieldPaths=machines"
    payload = {
        "fields": {
            "machines": _to_firestore(machines)
        }
    }
    try:
        _patch_json(url, payload, id_token)
        return True
    except urllib.error.HTTPError as e:
        raise Exception(f"Erreur mise à jour machines : {_firebase_error(e)}")


def remove_machine(uid: str, id_token: str, machine_id: str) -> bool:
    """
    Retire machine_id de /licenses/{uid}/machines.
    Utilisé lors du logout (deactivate_machine).
    """
    doc = get_license_doc(uid, id_token)
    if doc is None:
        return True  # Rien à faire

    machines: list = doc.get("machines", [])
    new_machines = [m for m in machines if not (isinstance(m, dict) and m.get("id") == machine_id)]

    url = f"{_FS_BASE}/licenses/{uid}?updateMask.fieldPaths=machines"
    payload = {"fields": {"machines": _to_firestore(new_machines)}}
    try:
        _patch_json(url, payload, id_token)
        return True
    except urllib.error.HTTPError as e:
        raise Exception(f"Erreur suppression machine : {_firebase_error(e)}")


# ---------------------------------------------------------------
# Token service account (admin — bypass les règles Firestore)
# ---------------------------------------------------------------

def get_admin_token(sa_path: str) -> str:
    """
    Génère un access token Google OAuth2 depuis le service_account.json.
    Ce token a un accès complet à Firestore et bypass les security rules.
    Lève une Exception si le fichier est absent ou invalide.
    """
    import os
    if not os.path.exists(sa_path):
        raise Exception(f"service_account.json introuvable : {sa_path}")
    try:
        from firebase_admin import credentials as fa_cred
        cred = fa_cred.Certificate(sa_path)
        tok  = cred.get_access_token()
        return tok.access_token
    except Exception as e:
        raise Exception(f"Impossible d'obtenir le token admin : {e}")


# ---------------------------------------------------------------
# Firestore : packs de fixtures distants
# ---------------------------------------------------------------

def _post_json_opt_auth(url: str, payload: dict, id_token: str = None) -> object:
    """POST JSON avec ou sans Bearer token. Retourne la réponse décodée."""
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise Exception(f"Erreur Firestore : {_firebase_error(e)}")


def write_fixture_pack(pack_id: str, pack_data: dict, id_token: str) -> dict:
    """
    Crée ou met à jour un pack de fixtures dans /fixture_packs/{pack_id}.
    Lit la version courante, l'incrémente, puis écrit le document complet.
    Retourne le document Firestore mis à jour (dict Python).
    """
    url = f"{_FS_BASE}/fixture_packs/{pack_id}"

    # Récupérer la version courante (404 → premier envoi → version 0)
    current_version = 0
    try:
        existing_doc = _get_json(url, id_token)
        current_version = _from_firestore(
            existing_doc.get("fields", {}).get("version", {"integerValue": "0"})
        ) or 0
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise Exception(f"Erreur lecture version existante : {_firebase_error(e)}")

    # Incrémenter la version et mettre à jour les timestamps
    import time as _time
    pack_data = dict(pack_data)
    pack_data["version"]    = int(current_version) + 1
    pack_data["updated_at"] = int(_time.time())
    pack_data["fixture_count"] = len(pack_data.get("fixtures", []))

    payload = {"fields": _dict_to_fields(pack_data)}
    try:
        result = _patch_json(url, payload, id_token)
        return _doc_to_dict(result)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise Exception(
                "Accès refusé (403) — ajoutez la règle Firestore pour fixture_packs :\n\n"
                "  match /fixture_packs/{packId} {\n"
                "    allow read: if true;\n"
                "    allow write: if request.auth != null;\n"
                "  }"
            )
        raise Exception(f"Erreur publication pack : {_firebase_error(e)}")


def delete_fixture_pack(pack_id: str, id_token: str) -> bool:
    """Supprime le document /fixture_packs/{pack_id} dans Firestore."""
    url = f"{_FS_BASE}/fixture_packs/{pack_id}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {id_token}"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT):
            return True
    except urllib.error.HTTPError as e:
        raise Exception(f"Erreur suppression pack : {_firebase_error(e)}")


def fetch_fixture_packs_index(id_token: str = None) -> list:
    """
    Liste tous les packs de fixtures disponibles sur Firestore (métadonnées uniquement,
    sans le champ 'fixtures' pour rester léger).

    Retourne une liste de dicts :
        [{"id", "name", "description", "version", "fixture_count", "updated_at", "tags"}, ...]

    Fonctionne sans authentification si les règles Firestore autorisent la lecture publique.
    """
    url = f"{_FS_BASE}:runQuery"
    query = {
        "from":    [{"collectionId": "fixture_packs"}],
        "orderBy": [{"field": {"fieldPath": "updated_at"}, "direction": "DESCENDING"}],
        "select":  {
            "fields": [
                {"fieldPath": "name"},
                {"fieldPath": "description"},
                {"fieldPath": "version"},
                {"fieldPath": "fixture_count"},
                {"fieldPath": "updated_at"},
                {"fieldPath": "tags"},
            ]
        },
    }
    try:
        resp_list = _post_json_opt_auth(url, {"structuredQuery": query}, id_token)
    except Exception as e:
        msg = str(e)
        if "403" in msg or "PERMISSION_DENIED" in msg:
            raise Exception(
                "Accès refusé (403) — ajoutez la règle Firestore pour fixture_packs :\n\n"
                "  match /fixture_packs/{packId} {\n"
                "    allow read: if true;\n"
                "    allow write: if request.auth != null;\n"
                "  }"
            )
        raise Exception(f"Erreur lecture packs : {e}")

    packs = []
    for entry in resp_list:
        doc = entry.get("document")
        if not doc:
            continue
        d = _doc_to_dict(doc)
        if not d.get("name"):
            continue
        # Extraire l'ID depuis le chemin Firestore
        d["id"] = doc.get("name", "").split("/")[-1]
        packs.append(d)
    return packs


def fetch_fixture_pack(pack_id: str, id_token: str = None) -> dict:
    """
    Télécharge le document complet d'un pack (incluant le tableau 'fixtures').

    Retourne : {"id", "name", "version", "fixture_count", "fixtures": [...]}
    Lève une Exception en cas d'erreur.
    """
    url = f"{_FS_BASE}/fixture_packs/{pack_id}"
    headers = {}
    if id_token:
        headers["Authorization"] = f"Bearer {id_token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            doc = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Exception(f"Pack '{pack_id}' introuvable.")
        raise Exception(f"Erreur téléchargement pack : {_firebase_error(e)}")

    d = _doc_to_dict(doc)
    d["id"] = pack_id
    return d


# ---------------------------------------------------------------
# Firestore : bibliothèque de fixtures OFL
# ---------------------------------------------------------------

def fetch_gdtf_fixtures(
    id_token: str,
    fixture_type: str = "",
    page_size: int = 100,
    cursor_manufacturer: str = None,
    cursor_name: str = None,
) -> dict:
    """
    Requête la collection gdtf_fixtures (fixtures OFL).
    Filtre optionnel par fixture_type.
    Pagination via cursor_manufacturer + cursor_name (valeurs du dernier doc).

    Retourne :
        {
          "fixtures": [{"name", "manufacturer", "fixture_type", "modes": [...], ...}],
          "next_cursor": {"manufacturer": str, "name": str} | None
        }
    """
    url = f"{_FS_BASE}:runQuery"

    filters = []
    if fixture_type:
        filters.append({
            "fieldFilter": {
                "field": {"fieldPath": "fixture_type"},
                "op": "EQUAL",
                "value": {"stringValue": fixture_type},
            }
        })

    query: dict = {
        "from": [{"collectionId": "gdtf_fixtures"}],
        "orderBy": [
            {"field": {"fieldPath": "manufacturer"}, "direction": "ASCENDING"},
            {"field": {"fieldPath": "name"}, "direction": "ASCENDING"},
        ],
        "limit": page_size,
    }

    if len(filters) == 1:
        query["where"] = filters[0]
    elif len(filters) > 1:
        query["where"] = {"compositeFilter": {"op": "AND", "filters": filters}}

    if cursor_manufacturer is not None and cursor_name is not None:
        query["startAfter"] = {
            "values": [
                {"stringValue": cursor_manufacturer},
                {"stringValue": cursor_name},
            ]
        }

    try:
        resp_list = _post_json(url, {"structuredQuery": query}, id_token)
    except urllib.error.HTTPError as e:
        raise Exception(f"Erreur recherche fixtures : {_firebase_error(e)}")

    fixtures = []
    for entry in resp_list:
        doc = entry.get("document")
        if not doc:
            continue
        d = _doc_to_dict(doc)
        if not d.get("name"):
            continue
        fixtures.append(d)

    next_cursor = None
    if len(fixtures) == page_size:
        last = fixtures[-1]
        next_cursor = {
            "manufacturer": last.get("manufacturer", ""),
            "name": last.get("name", ""),
        }

    return {"fixtures": fixtures, "next_cursor": next_cursor}
