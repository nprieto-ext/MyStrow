"""
Script de correction — passe les licences annuelles mal enregistrées en "monthly"
vers le bon plan "annual" avec la bonne date d'expiration.

Usage :
  python fix_annual_licenses.py          # dry-run (affiche sans modifier)
  python fix_annual_licenses.py --apply  # applique les corrections
"""

import sys
import time
import base64
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY  = ""  # rk_live_... — set via env var or directly before use
STRIPE_PRICE_ANNUAL = "price_1TPh4x1gGkNcl6cau8xipXnj"
ANNUAL_DAYS         = 366

APPLY = "--apply" in sys.argv

# ── Firebase Admin ────────────────────────────────────────────────────────────
try:
    import firebase_admin
    from firebase_admin import firestore, credentials
except ImportError:
    print("❌  firebase-admin non installé : pip install firebase-admin")
    sys.exit(1)

SA_PATHS = [
    Path(__file__).parent / "service_account.json",
    Path(__file__).parent / "functions" / "service_account.json",
]
sa_path = next((p for p in SA_PATHS if p.exists()), None)
if not sa_path:
    print("❌  service_account.json introuvable")
    sys.exit(1)

cred = credentials.Certificate(str(sa_path))
firebase_admin.initialize_app(cred)
db = firestore.client()

# ── Stripe helper ─────────────────────────────────────────────────────────────
def stripe_get(path: str) -> dict:
    url   = f"https://api.stripe.com/v1{path}"
    token = base64.b64encode(f"{STRIPE_SECRET_KEY}:".encode()).decode()
    req   = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")

# ── Récupère tous les docs "monthly" avec un abonnement Stripe ────────────────
print("Chargement des licences Firestore…")
docs = db.collection("licenses").where("plan_type", "==", "monthly").stream()

candidates = []
for doc in docs:
    d = doc.to_dict()
    sub_id = d.get("stripe_subscription_id", "")
    if sub_id:
        candidates.append((doc.id, d, sub_id))

print(f"{len(candidates)} licence(s) monthly avec abonnement Stripe trouvée(s)\n")

if not candidates:
    print("Rien à corriger.")
    sys.exit(0)

# ── Vérifie chaque abonnement Stripe ─────────────────────────────────────────
to_fix = []

for uid, doc, sub_id in candidates:
    email = doc.get("email", "?")
    try:
        sub      = stripe_get(f"/subscriptions/{sub_id}")
        price_id = sub["items"]["data"][0]["price"]["id"]
    except Exception as e:
        print(f"  !! {email} - impossible de lire l'abonnement {sub_id} : {e}")
        continue

    if price_id == STRIPE_PRICE_ANNUAL:
        created  = doc.get("created_utc", time.time())
        new_exp  = created + ANNUAL_DAYS * 86400
        to_fix.append((uid, email, doc, new_exp))
        print(f"  >> {email}  |  cree le {fmt(created)}  |  nouvelle expiration : {fmt(new_exp)}")
    else:
        print(f"  ok {email}  |  price_id={price_id} (pas annuel, ignore)")

print(f"\n{len(to_fix)} licence(s) à corriger.")

if not to_fix:
    sys.exit(0)

if not APPLY:
    print("\nMode DRY-RUN - aucune modification effectuee.")
    print("Relancez avec --apply pour appliquer les corrections.")
    sys.exit(0)

# ── Applique les corrections ──────────────────────────────────────────────────
print("\nApplication des corrections…")
ok = 0
for uid, email, doc, new_exp in to_fix:
    try:
        db.collection("licenses").document(uid).update({
            "plan_type":  "annual",
            "expiry_utc": new_exp,
        })
        print(f"  OK  {email}  ->  annual  |  expire {fmt(new_exp)}")
        ok += 1
    except Exception as e:
        print(f"  ERR {email}  ->  erreur : {e}")

print(f"\n{ok}/{len(to_fix)} licence(s) corrigée(s).")
