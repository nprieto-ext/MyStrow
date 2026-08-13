"""
Script de reparation — restaure `stripe_subscription_id` sur les licences
recurrentes actives qui l'ont perdu.

Contexte (12/08/2026) : `_on_invoice_paid` lisait `invoice["subscription"]`, un
champ que Stripe a deplace sous `parent.subscription_details.subscription`. Le
renouvellement ecrivait donc une chaine vide, et `_set_license` ecrasait la
valeur en base. Consequences : KPI « Abonnements actifs » sous-evalue, bouton
« Annuler l'abonnement » inoperant, et alerte d'expiration renvoyee a des
abonnes payants (`license_manager._is_auto_renew`).

Le correctif est deja en place dans functions/main.py ; ce script repare
l'existant. Il ne touche QUE le champ `stripe_subscription_id`, et seulement
quand il est vide : ni expiry, ni plan, ni plan_type ne sont modifies. Les
divergences de plan_type sont signalees, pas corrigees (voir
fix_annual_licenses.py).

Usage :
  python fix_subscription_ids.py            # dry-run (affiche, ne modifie rien)
  python fix_subscription_ids.py --apply    # applique

Acces : jeton admin (~/.maestro_admin.json, cree par admin_panel) pour Firestore,
cle Stripe lue dans functions/.env ou dans la variable STRIPE_SECRET_KEY.
"""

import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

APPLY = "--apply" in sys.argv

from firebase_client import refresh_id_token          # noqa: E402
import admin_panel as ap                              # noqa: E402


# ── Cle Stripe ────────────────────────────────────────────────────────────────

def stripe_secret_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if key:
        return key
    env = BASE_DIR / "functions" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("STRIPE_SECRET_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def stripe_get(path: str, params: dict = None) -> dict:
    url = f"https://api.stripe.com/v1{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    token = base64.b64encode(f"{STRIPE_KEY}:".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ── Selection des documents a reparer ─────────────────────────────────────────

def anomalies(clients: list) -> list:
    """Licence recurrente encore valide, non resiliee, sans identifiant."""
    now = datetime.now(timezone.utc).timestamp()
    out = []
    for c in clients:
        if c.get("plan_type") not in ("monthly", "annual"):
            continue
        if c.get("plan") == "expired":
            continue        # resiliation : identifiant vide par conception
        if c.get("stripe_subscription_id"):
            continue
        if float(c.get("expiry_utc", 0) or 0) <= now:
            continue
        if not c.get("stripe_customer_id"):
            continue        # sans client Stripe, rien a retrouver
        out.append(c)
    return out


def active_subscription(customer_id: str) -> dict | None:
    """Abonnement en cours du client, ou None. `status=all` puis filtrage :
    une souscription en `past_due` ou `trialing` reste un abonnement vivant."""
    data = stripe_get("/subscriptions",
                      {"customer": customer_id, "status": "all", "limit": 10})
    vivants = [s for s in data.get("data", [])
               if s.get("status") in ("active", "trialing", "past_due", "unpaid")]
    if not vivants:
        return None
    vivants.sort(key=lambda s: s.get("created", 0), reverse=True)
    return vivants[0]


def plan_from_price(price_id: str, prices: dict) -> str:
    for plan, pid in prices.items():
        if pid and price_id == pid:
            return plan
    return "?"


def main() -> int:
    if not STRIPE_KEY:
        print("Cle Stripe introuvable : renseignez STRIPE_SECRET_KEY ou functions/.env")
        return 1

    cache_path = Path.home() / ".maestro_admin.json"
    if not cache_path.exists():
        print("~/.maestro_admin.json introuvable : connectez-vous d'abord a l'admin panel")
        return 1
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    id_token = refresh_id_token(cache["refresh_token"])["id_token"]

    print("Chargement des licences…")
    clients = ap._query_all_licenses(id_token)
    cibles = anomalies(clients)
    print(f"{len(clients)} licences — {len(cibles)} a reparer\n")
    if not cibles:
        print("Rien a faire.")
        return 0

    env_prices = {}
    for plan, var in (("monthly", "STRIPE_PRICE_MONTHLY"),
                      ("annual", "STRIPE_PRICE_ANNUAL"),
                      ("lifetime", "STRIPE_PRICE_LIFETIME")):
        val = os.environ.get(var, "")
        if not val and (BASE_DIR / "functions" / ".env").exists():
            for line in (BASE_DIR / "functions" / ".env").read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{var}="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
        env_prices[plan] = val

    a_ecrire, introuvables, desaccords = [], [], []

    for c in cibles:
        email = c.get("email", "?")
        uid   = c.get("_uid", "")
        try:
            sub = active_subscription(c["stripe_customer_id"])
        except Exception as e:
            print(f"  !! {email} — Stripe illisible : {e}")
            continue
        if not sub:
            introuvables.append(email)
            print(f"  -- {email} — aucun abonnement vivant cote Stripe (a verifier)")
            continue

        price_id = ""
        try:
            price_id = sub["items"]["data"][0]["price"]["id"]
        except Exception:
            pass
        plan_stripe = plan_from_price(price_id, env_prices)
        plan_base   = c.get("plan_type", "")
        marque = ""
        if plan_stripe != "?" and plan_stripe != plan_base:
            desaccords.append((email, plan_base, plan_stripe))
            marque = f"   /!\\ plan base={plan_base} mais Stripe={plan_stripe}"

        print(f"  >> {email:<38} {sub['id']}  ({sub.get('status')}){marque}")
        a_ecrire.append((uid, email, sub["id"]))

    print(f"\n{len(a_ecrire)} document(s) a mettre a jour.")
    if introuvables:
        print(f"{len(introuvables)} sans abonnement vivant — probablement resilies "
              f"sans que le webhook l'ait enregistre : {', '.join(introuvables)}")
    if desaccords:
        print(f"{len(desaccords)} plan_type en desaccord avec Stripe (NON corrige ici) :")
        for email, base, stripe in desaccords:
            print(f"   {email} : base={base} Stripe={stripe}")

    if not APPLY:
        print("\nMode DRY-RUN — aucune modification. Relancez avec --apply.")
        return 0

    print("\nApplication…")
    ok = 0
    for uid, email, sub_id in a_ecrire:
        try:
            ap._patch_firestore(
                f"licenses/{uid}",
                {"stripe_subscription_id": {"stringValue": sub_id}},
                id_token,
                mask=["stripe_subscription_id"],
            )
            ok += 1
        except Exception as e:
            print(f"  !! {email} : {e}")
    print(f"{ok}/{len(a_ecrire)} document(s) repare(s).")
    return 0


STRIPE_KEY = stripe_secret_key()

if __name__ == "__main__":
    sys.exit(main())
