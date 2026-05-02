"""
Script admin — Active manuellement une licence pour un client Stripe.
Usage : python admin_activate_user.py
"""
import json
import time
import random
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
EMAIL      = input("Email du client : ").strip()
PLAN       = input("Plan (monthly/annual/lifetime) [monthly] : ").strip() or "monthly"
DAYS_MAP   = {"monthly": 31, "annual": 366, "lifetime": 36500}

if PLAN not in DAYS_MAP:
    print(f"Plan inconnu : {PLAN}"); sys.exit(1)

# ── Firebase Admin (doit être installé : pip install firebase-admin) ──────────
try:
    import firebase_admin
    from firebase_admin import auth, firestore, credentials
except ImportError:
    print("❌  firebase-admin non installé. Lancez : pip install firebase-admin")
    sys.exit(1)

# Cherche le service account dans le dossier courant ou functions/
SA_PATHS = [
    Path(__file__).parent / "service_account.json",
    Path(__file__).parent / "functions" / "service_account.json",
]
sa_path = next((p for p in SA_PATHS if p.exists()), None)
if not sa_path:
    print("❌  service_account.json introuvable (cherché dans . et functions/)")
    sys.exit(1)

cred = credentials.Certificate(str(sa_path))
firebase_admin.initialize_app(cred)
db = firestore.client()

# ── Génère un mot de passe temporaire ────────────────────────────────────────
def gen_password(n=12):
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(random.choices(chars, k=n))

# ── Crée ou récupère l'utilisateur Firebase Auth ─────────────────────────────
temp_pwd = gen_password()
try:
    user = auth.get_user_by_email(EMAIL)
    is_new = False
    print(f"✓ Compte Firebase existant — uid={user.uid}")
except auth.UserNotFoundError:
    user = auth.create_user(email=EMAIL, password=temp_pwd)
    is_new = True
    print(f"✓ Compte Firebase créé — uid={user.uid}")

uid = user.uid

# ── Crée / met à jour le document Firestore /licenses/{uid} ──────────────────
now       = time.time()
expiry_ts = now + DAYS_MAP[PLAN] * 86400
expiry_str = datetime.fromtimestamp(expiry_ts, tz=timezone.utc).strftime("%d/%m/%Y")

ref = db.collection("licenses").document(uid)
doc = ref.get()

data = {
    "plan":       "license",
    "plan_type":  PLAN,
    "expiry_utc": expiry_ts,
    "email":      EMAIL,
}
if PLAN == "lifetime":
    data["updates_until_utc"] = now + 365 * 86400

if doc.exists:
    ref.update(data)
    print(f"✓ Document licenses/{uid} mis à jour")
else:
    ref.set({**data, "created_utc": now, "machines": [], "password": temp_pwd})
    print(f"✓ Document licenses/{uid} créé")

print(f"\n{'='*50}")
print(f"  Client  : {EMAIL}")
print(f"  Plan    : {PLAN}")
print(f"  Expire  : {expiry_str}")
if is_new:
    print(f"  Mot de passe temporaire : {temp_pwd}")
    print(f"\n  ⚠  Transmets ces identifiants au client manuellement.")
    print(f"     Il pourra changer son mot de passe depuis l'app.")
else:
    print(f"  Compte existant — le client peut utiliser 'Mot de passe oublié'.")
print(f"{'='*50}\n")
