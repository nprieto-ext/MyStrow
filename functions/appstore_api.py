"""App Store Server API : envoi des infos d'usage (« Send Consumption Information »).

Quand un client demande un remboursement, Apple envoie une notification
CONSUMPTION_REQUEST et nous laisse 12 h pour donner notre version via
PUT /inApps/v2/transactions/consumption/{transactionId}.

⚠ Apple : « Only respond if the customer consented ». customerConsented doit
valoir true, sinon HTTP 400. On n'envoie donc rien tant que l'appli ne recueille
pas ce consentement (variable APPSTORE_CONSUMPTION_CONSENT=1, cf. main.py).

Clé requise : App Store Connect › Utilisateurs et accès › Intégrations ›
« Achat intégré » (une clé API App Store Connect « Équipe » ne marche PAS).
Variables (.env des functions) :
  APPSTORE_IAP_KEY_ID       – identifiant de la clé (10 caractères)
  APPSTORE_IAP_ISSUER_ID    – ID de l'émetteur (UUID, en haut de la page des clés)
  APPSTORE_IAP_PRIVATE_KEY  – contenu du .p8, retours à la ligne écrits \\n
  APPSTORE_REFUND_PREFERENCE – DECLINE (défaut) | GRANT_FULL | vide = pas d'avis

Usage manuel (depuis App/functions) :
  python appstore_api.py <transactionId> [--sandbox] [--grant] [--dry-run]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BUNDLE_ID = "com.happlysas.mystrow"
_HOSTS = {"Production": "https://api.storekit.apple.com",
          "Sandbox": "https://api.storekit-sandbox.apple.com"}


def _jwt() -> str:
    import jwt as pyjwt
    key_id = os.environ.get("APPSTORE_IAP_KEY_ID", "").strip()
    issuer = os.environ.get("APPSTORE_IAP_ISSUER_ID", "").strip()
    pem = os.environ.get("APPSTORE_IAP_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    if not (key_id and issuer and pem):
        raise RuntimeError("clé App Store Server API absente (APPSTORE_IAP_*)")
    now = int(time.time())
    return pyjwt.encode(
        {"iss": issuer, "iat": now, "exp": now + 20 * 60,
         "aud": "appstoreconnect-v1", "bid": BUNDLE_ID},
        pem, algorithm="ES256", headers={"kid": key_id, "typ": "JWT"})


def consumption_body(refund_preference: str | None = None) -> dict:
    """Ce qu'on peut affirmer honnêtement pour l'achat « MyStrow Tablette » :
    - le déblocage est immédiat et local ⇒ DELIVERED ;
    - l'appli s'essaie gratuitement avant achat (10 min de DMX par lancement)
      ⇒ sampleContentProvided ;
    - on ne mesure pas l'usage côté serveur ⇒ pas de consumptionPercentage."""
    body = {"customerConsented": True,
            "deliveryStatus": "DELIVERED",
            "sampleContentProvided": True}
    pref = (refund_preference if refund_preference is not None
            else os.environ.get("APPSTORE_REFUND_PREFERENCE", "DECLINE")).strip().upper()
    if pref:
        body["refundPreference"] = pref
    return body


def send_consumption(transaction_id: str, env: str = "Production",
                     refund_preference: str | None = None) -> tuple[int, str]:
    """Renvoie (statut HTTP, texte). 202 = reçu par Apple."""
    url = f"{_HOSTS.get(env, _HOSTS['Production'])}/inApps/v2/transactions/consumption/{transaction_id}"
    req = urllib.request.Request(
        url, method="PUT",
        data=json.dumps(consumption_body(refund_preference)).encode(),
        headers={"Authorization": f"Bearer {_jwt()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    here = os.path.dirname(os.path.abspath(__file__))
    _load_dotenv(os.path.join(here, ".env.local"))
    _load_dotenv(os.path.join(here, ".env"))
    pref = "GRANT_FULL" if "--grant" in sys.argv else None
    env = "Sandbox" if "--sandbox" in sys.argv else "Production"
    print(f"{env} · transaction {args[0]}")
    print(json.dumps(consumption_body(pref), indent=2))
    if "--dry-run" in sys.argv:
        sys.exit(0)
    code, txt = send_consumption(args[0], env, pref)
    print(f"HTTP {code} {txt}")
    sys.exit(0 if code == 202 else 1)
