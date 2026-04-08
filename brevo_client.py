"""
Client Brevo (ex-Sendinblue) pour MyStrow.
Wrapper urllib uniquement — zéro dépendance externe.
Usage: emails transactionnels (rappels licence) + newsletter (contacts).
"""

import json
import ssl
import urllib.request
import urllib.error

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

from core import BREVO_API_KEY, BREVO_SENDER_EMAIL, BREVO_SENDER_NAME, BREVO_LIST_ID

_API_BASE = "https://api.brevo.com/v3"
_TIMEOUT  = 8


def _request(method: str, endpoint: str, payload: dict = None) -> dict:
    """Requête JSON vers l'API Brevo. Lève une Exception en cas d'erreur."""
    url  = f"{_API_BASE}{endpoint}"
    data = json.dumps(payload).encode() if payload is not None else None
    req  = urllib.request.Request(
        url, data=data,
        headers={
            "accept":       "application/json",
            "content-type": "application/json",
            "api-key":      BREVO_API_KEY,
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CTX) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            msg = json.loads(body).get("message", body)
        except Exception:
            msg = body
        raise Exception(f"Brevo {e.code}: {msg}")


# ---------------------------------------------------------------
# Emails transactionnels
# ---------------------------------------------------------------

def send_email(to_email: str, to_name: str, subject: str, html_content: str) -> bool:
    """
    Envoie un email transactionnel via Brevo.
    Utilise l'expéditeur configuré dans core.py (BREVO_SENDER_*).
    Retourne True si succès, lève Exception sinon.
    """
    _request("POST", "/smtp/email", {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html_content,
    })
    return True


# ---------------------------------------------------------------
# Gestion des contacts / newsletter
# ---------------------------------------------------------------

def subscribe_contact(email: str, name: str = "", lang: str = "fr") -> bool:
    """
    Ajoute ou met à jour un contact dans la liste newsletter Brevo (BREVO_LIST_ID).
    Si le contact existe déjà, il est mis à jour (updateEnabled=True).
    lang : 'fr' ou 'en' — stocké dans l'attribut Brevo LANGUAGE pour segmenter les campagnes.
    Retourne True si succès, lève Exception sinon.

    Prérequis Brevo : créer l'attribut LANGUAGE (texte) dans
    Contacts > Paramètres > Attributs des contacts.
    """
    attributes: dict = {"LANGUAGE": lang.lower()}
    if name:
        attributes["FIRSTNAME"] = name

    payload: dict = {
        "email":         email,
        "updateEnabled": True,
        "attributes":    attributes,
    }
    if BREVO_LIST_ID:
        payload["listIds"] = [int(BREVO_LIST_ID)]

    _request("POST", "/contacts", payload)
    return True


def unsubscribe_contact(email: str) -> bool:
    """
    Met le contact en liste noire Brevo (équivalent désabonnement global).
    Retourne True si succès, lève Exception sinon.
    """
    _request("PUT", "/contacts/blocklist", {
        "emails": [email],
        "action": "blockContacts",
    })
    return True
