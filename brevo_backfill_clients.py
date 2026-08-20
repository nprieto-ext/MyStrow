"""
Rattrapage : pousse les licences Firestore dans la liste Brevo « Clients ».

    python brevo_backfill_clients.py            # simulation, n'ecrit RIEN
    python brevo_backfill_clients.py --go       # ecrit pour de vrai

A n'executer qu'une fois. Les achats posterieurs au 20/08/2026 sont synchronises
automatiquement par `_brevo_sync_client()` dans le webhook Stripe : ce script ne
sert qu'a reprendre le parc anterieur.

Il est REJOUABLE sans dommage (`updateEnabled: true` chez Brevo met a jour au
lieu d'echouer), et ne touche jamais Firestore : lecture seule d'un cote,
ecriture de l'autre.

Identifiants : `service_account.json` a la racine du projet pour Firestore, et
BREVO_API_KEY lu dans `functions/.env`. Aucun n'est affiche.
"""

import argparse
import base64
import collections
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import FIREBASE_PROJECT_ID          # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
LISTE_CLIENTS = 4          # « Clients MyStrow » — PAS la newsletter (id 3)
UA = "Mozilla/5.0 (compatible; MyStrow-Backfill/1.0; +https://mystrow.fr)"

# Domaines qui n'entrent JAMAIS dans Brevo.
#
# tuifrance.com est un contrat B2B : une soixantaine de boites d'hotels, toutes
# a la meme echeance, gerees par un interlocuteur unique. Les relancer une par
# une n'a aucun sens — au mieux c'est du bruit, au pire soixante messages
# arrivent le meme jour chez le meme groupe. Le renouvellement se traite comme
# un marche, pas comme un cycle de vie client.
DOMAINES_EXCLUS = {"tuifrance.com"}


def exclu(email: str) -> bool:
    return (email or "").strip().lower().rsplit("@", 1)[-1] in DOMAINES_EXCLUS


def cle_brevo() -> str:
    """BREVO_API_KEY, depuis l'environnement ou functions/.env."""
    k = os.environ.get("BREVO_API_KEY", "").strip()
    if not k:
        chemin = os.path.join(ICI, "functions", ".env")
        if os.path.exists(chemin):
            with open(chemin, encoding="utf-8") as f:
                for ligne in f:
                    if ligne.strip().startswith("BREVO_API_KEY="):
                        k = ligne.split("=", 1)[1].strip()
    if not k:
        sys.exit("BREVO_API_KEY introuvable (environnement ou functions/.env).")
    return k


def jeton_firestore() -> str:
    """Jeton OAuth2 avec la portee `datastore`.

    ⚠️ Pas celui d'`admin_panel._get_service_account_token()`, qui n'a que la
    portee `identitytoolkit` : Firestore repondrait 403
    « Request had insufficient authentication scopes ».
    """
    chemin = os.path.join(ICI, "service_account.json")
    if not os.path.exists(chemin):
        sys.exit(f"service_account.json introuvable : {chemin}")
    sa = json.load(open(chemin, encoding="utf-8"))
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as ap
    iat = int(time.time())
    ent = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
    cor = base64.urlsafe_b64encode(json.dumps({
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/datastore",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": iat, "exp": iat + 3600}).encode()).rstrip(b"=")
    signe = ent + b"." + cor
    prv = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = base64.urlsafe_b64encode(
        prv.sign(signe, ap.PKCS1v15(), hashes.SHA256())).rstrip(b"=")
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": (signe + b"." + sig).decode()}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["access_token"]


def _val(v):
    """Deplie une valeur typee de l'API REST Firestore."""
    k, x = list(v.items())[0]
    if k == "arrayValue":
        return [_val(i) for i in (x.get("values") or [])]
    if k == "mapValue":
        return {a: _val(b) for a, b in (x.get("fields") or {}).items()}
    if k == "integerValue":
        return int(x)
    if k == "doubleValue":
        return float(x)
    if k == "nullValue":
        return None
    return x


def licences() -> list:
    tok = jeton_firestore()
    base = (f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
            f"/databases/(default)/documents/licenses")
    out, page = [], None
    while True:
        url = base + "?pageSize=300" + (f"&pageToken={page}" if page else "")
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {tok}")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        for doc in data.get("documents", []):
            f = {a: _val(b) for a, b in (doc.get("fields") or {}).items()}
            f["_uid"] = doc["name"].split("/")[-1]
            out.append(f)
        page = data.get("nextPageToken")
        if not page:
            break
    return out


def _iso(ts) -> str:
    """AAAA-MM-JJ pour Brevo, "" si absent ou au-dela de sa borne (2099)."""
    if not isinstance(ts, (int, float)):
        return ""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return ""
    return "" if dt.year > 2099 else dt.strftime("%Y-%m-%d")


def statut(doc: dict, maintenant: float) -> str:
    """Categorie commerciale du client. C'est ELLE qui dit si on peut relancer.

    ⚠️ `expiry_utc` n'est PAS une date d'expiration pour un abonne Stripe : c'est
    la fin de la periode courante, repoussee a chaque paiement par
    `_on_invoice_paid`. Segmenter sur la date seule ferait envoyer « votre
    licence expire dans 15 jours » a des clients dont l'abonnement se renouvelle
    tout seul — le message qui declenche une resiliation.

    Meme regle que `license_manager._is_auto_renew` : recurrent ET identifiant
    d'abonnement present. La condition sur l'identifiant est essentielle, une
    activation manuelle (`admin_activate_user.py`) pose `plan_type="monthly"`
    sans abonnement Stripe et a, elle, une vraie echeance.
    """
    if doc.get("plan") == "expired":
        return "resilie"                      # reconquete
    if doc.get("plan_type") == "lifetime":
        return "a_vie"                        # jamais de relance
    if (doc.get("plan_type") in ("monthly", "annual")
            and (doc.get("stripe_subscription_id") or "").strip()):
        return "abonne"                       # se renouvelle seul : JAMAIS de relance
    exp = doc.get("expiry_utc")
    if isinstance(exp, (int, float)) and exp < maintenant:
        return "echu"                         # fin reelle, deja passee
    return "echeance_fixe"                    # vraie echeance a venir : relancable


def contact(doc: dict, maintenant: float) -> dict | None:
    """Traduit un document de licence en contact Brevo, ou None s'il est inexploitable."""
    email = (doc.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return None
    if exclu(email):
        return None
    exp = doc.get("expiry_utc")
    exp = float(exp) if isinstance(exp, (int, float)) else None
    return {
        "email": email,
        "listIds": [LISTE_CLIENTS],
        "attributes": {
            # `plan_type` manque sur les licences les plus anciennes : on retombe
            # sur `plan`, qui vaut au moins « license » ou « expired ». Mieux
            # qu'un champ vide, sur lequel aucune segmentation n'est possible.
            "PLAN": doc.get("plan_type") or doc.get("plan") or "",
            # AAAA-MM-JJ : seul format accepte par un attribut date de Brevo.
            # Vide au-dela de 2099, borne haute de Brevo — c'est le cas des
            # licences A VIE (expiry_utc vers 2126). Brevo ecrete a 2099-12-31
            # sur une mise a jour mais ABANDONNE la valeur a la creation, sans
            # rien dire. Une licence a vie n'ayant pas d'echeance, l'attribut
            # vide est correct : la relance d'expiration ne doit pas les viser.
            "EXPIRY": _iso(exp),
            "STATUT": statut(doc, maintenant),
            "LANG": (doc.get("lang") or "fr").upper(),
            "UID": doc.get("_uid", ""),
        },
        "updateEnabled": True,
    }


def pousser(c: dict, key: str) -> tuple[bool, str]:
    req = urllib.request.Request("https://api.brevo.com/v3/contacts",
                                 data=json.dumps(c).encode(), method="POST")
    req.add_header("api-key", key)
    req.add_header("content-type", "application/json")
    req.add_header("accept", "application/json")
    req.add_header("User-Agent", UA)          # sinon Cloudflare repond 403
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True, "ok"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.read().decode('utf-8', 'replace')[:120]}"
    except Exception as e:
        return False, str(e)[:120]


if __name__ == "__main__":
    ap_ = argparse.ArgumentParser(description=__doc__)
    ap_.add_argument("--go", action="store_true",
                     help="ecrit reellement dans Brevo (sinon : simulation)")
    a = ap_.parse_args()

    maintenant = time.time()
    docs = licences()
    prets = [c for c in (contact(d, maintenant) for d in docs) if c]
    # Deux motifs de rejet bien distincts : compter les exclusions de domaine
    # comme des « emails invalides » ferait chercher un probleme de donnees la
    # ou il n'y a qu'une decision commerciale.
    exclus = sum(1 for d in docs if exclu(d.get("email") or ""))
    invalides = len(docs) - len(prets) - exclus

    stats = collections.Counter(c["attributes"]["STATUT"] for c in prets)
    plans = collections.Counter(c["attributes"]["PLAN"] for c in prets)
    print(f"{len(docs)} licence(s) lue(s), {len(prets)} poussee(s), "
          f"{exclus} exclue(s) par domaine ({', '.join(sorted(DOMAINES_EXCLUS))}), "
          f"{invalides} sans email exploitable")
    print(f"  statut : {dict(stats)}")
    print(f"  plan   : {dict(plans)}")

    if not a.go:
        print("\nSIMULATION — rien n'a ete ecrit. Relancer avec --go pour appliquer.")
        for c in prets[:5]:
            print("   ", c["email"], c["attributes"])
        if len(prets) > 5:
            print(f"    … et {len(prets) - 5} autre(s)")
        sys.exit(0)

    key = cle_brevo()
    ok = 0
    echecs = []
    for i, c in enumerate(prets, 1):
        bon, detail = pousser(c, key)
        ok += bon
        if not bon:
            echecs.append((c["email"], detail))
        if i % 25 == 0:
            print(f"  … {i}/{len(prets)}")
        time.sleep(0.12)        # ~8 requetes/s, sous la limite de Brevo
    print(f"\n{ok}/{len(prets)} contact(s) pousse(s) dans la liste {LISTE_CLIENTS}")
    for mail, d in echecs:
        print(f"  ECHEC {mail} : {d}")
