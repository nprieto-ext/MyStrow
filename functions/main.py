"""
Firebase Cloud Function — Webhook Stripe pour MyStrow.

Gère :
  - checkout.session.completed    → crée compte + active licence + facture Axonaut
  - invoice.payment_succeeded     → renouvelle licence + facture Axonaut
  - customer.subscription.deleted → révoque la licence
  - invoice.payment_failed        → email d'avertissement

Déploiement :
  firebase deploy --only functions

Variables d'environnement à configurer (firebase functions:secrets:set ou .env.local) :
  STRIPE_SECRET_KEY       – sk_live_...
  STRIPE_WEBHOOK_SECRET   – whsec_...
  STRIPE_PRICE_MONTHLY    – price_...
  STRIPE_PRICE_ANNUAL     – price_...
  STRIPE_PRICE_LIFETIME   – price_...
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM
  AXONAUT_API_KEY
"""

import hashlib
import hmac
import json
import os
import random
import smtplib
import ssl
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import firebase_admin
from firebase_admin import auth, firestore
from firebase_functions import https_fn

# ---------------------------------------------------------------------------
# Init Firebase Admin — lazy pour éviter le timeout au démarrage
# ---------------------------------------------------------------------------
_db = None

def _get_db():
    global _db
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    if _db is None:
        _db = firestore.client()
    return _db

# ---------------------------------------------------------------------------
# Config (variables d'environnement)
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MONTHLY   = os.environ.get("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_ANNUAL    = os.environ.get("STRIPE_PRICE_ANNUAL", "")
STRIPE_PRICE_LIFETIME  = os.environ.get("STRIPE_PRICE_LIFETIME", "")

SMTP_HOST     = os.environ.get("SMTP_HOST", "")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM     = os.environ.get("SMTP_FROM", "")

AXONAUT_API_KEY = os.environ.get("AXONAUT_API_KEY", "")
AXONAUT_BASE    = "https://app.axonaut.com/api/v2"

GDTF_SYNC_SECRET = os.environ.get("GDTF_SYNC_SECRET", "")

# Durée des plans en jours
_PLAN_DAYS = {
    "monthly":  31,
    "annual":   366,
    "lifetime": 36500,  # ~100 ans
}


# ===========================================================================
# STRIPE HELPERS
# ===========================================================================

def _stripe_get(path: str) -> dict:
    """GET vers l'API Stripe."""
    import base64
    url = f"https://api.stripe.com/v1{path}"
    token = base64.b64encode(f"{STRIPE_SECRET_KEY}:".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _verify_stripe_signature(payload: bytes, sig_header: str) -> bool:
    """Vérifie la signature HMAC-SHA256 du webhook Stripe."""
    try:
        parts = dict(item.split("=", 1) for item in sig_header.split(","))
        timestamp = parts.get("t", "")
        v1        = parts.get("v1", "")
        signed    = timestamp.encode() + b"." + payload
        expected  = hmac.new(
            STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False


def _get_plan_type(price_id: str) -> str:
    if price_id == STRIPE_PRICE_MONTHLY:
        return "monthly"
    if price_id == STRIPE_PRICE_ANNUAL:
        return "annual"
    if price_id == STRIPE_PRICE_LIFETIME:
        return "lifetime"
    return "monthly"


def _plan_label(plan_type: str) -> str:
    return {
        "monthly":  "Licence MyStrow — Mensuel",
        "annual":   "Licence MyStrow — Annuel",
        "lifetime": "Licence MyStrow — À vie",
    }.get(plan_type, "Licence MyStrow")


def _compute_expiry(plan_type: str) -> float:
    return time.time() + _PLAN_DAYS.get(plan_type, 31) * 86400


def _fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")


# ===========================================================================
# FIREBASE HELPERS
# ===========================================================================

def _get_or_create_user(email: str, password: str) -> tuple[str, bool]:
    """
    Retourne (uid, is_new).
    Crée l'utilisateur Firebase Auth si inexistant.
    """
    try:
        user = auth.get_user_by_email(email)
        return user.uid, False
    except auth.UserNotFoundError:
        user = auth.create_user(email=email, password=password)
        return user.uid, True


def _set_license(
    uid: str,
    email: str,
    plan_type: str,
    expiry_ts: float,
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
) -> None:
    """Crée ou met à jour le document Firestore /licenses/{uid}."""
    ref = _get_db().collection("licenses").document(uid)
    doc = ref.get()

    data = {
        "plan":                   "license",
        "expiry_utc":             expiry_ts,
        "plan_type":              plan_type,
        "stripe_customer_id":     stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
    }

    # Lifetime : licence permanente mais mises à jour limitées à 1 an
    if plan_type == "lifetime":
        # N'écraser updates_until_utc que si c'est un nouveau document
        if not doc.exists:
            data["updates_until_utc"] = time.time() + 365 * 86400

    if doc.exists:
        ref.update(data)
    else:
        ref.set({
            **data,
            "email":       email,
            "created_utc": time.time(),
            "machines":    [],
        })


def _revoke_license(uid: str) -> None:
    """Passe le plan à 'expired' et vide l'ID abonnement."""
    _get_db().collection("licenses").document(uid).update({
        "plan":                   "expired",
        "expiry_utc":             time.time(),
        "stripe_subscription_id": "",
    })


def _find_uid_by_customer(customer_id: str) -> str | None:
    """Retrouve l'UID Firebase depuis un stripe_customer_id."""
    docs = (
        _get_db().collection("licenses")
        .where("stripe_customer_id", "==", customer_id)
        .limit(1)
        .get()
    )
    for doc in docs:
        return doc.id
    return None


def _generate_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(random.choices(chars, k=length))


# ===========================================================================
# AXONAUT HELPERS
# ===========================================================================

def _axonaut(method: str, path: str, payload: dict | None = None):
    """Appel générique API Axonaut."""
    if not AXONAUT_API_KEY:
        return None
    url  = f"{AXONAUT_BASE}{path}"
    data = json.dumps(payload).encode() if payload else None
    headers = {"userApiKey": AXONAUT_API_KEY}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[Axonaut] HTTP {e.code} — {path}")
        return None
    except Exception as e:
        print(f"[Axonaut] Erreur — {e}")
        return None


def _axonaut_get_or_create_company(email: str, name: str) -> int | None:
    """Retourne l'ID Axonaut du prospect, le crée si inexistant."""
    # Recherche par email
    result = _axonaut("GET", f"/prospects?email={urllib.parse.quote(email)}")
    if result:
        items = result if isinstance(result, list) else result.get("data", [])
        if items:
            return items[0].get("id")

    # Création
    created = _axonaut("POST", "/prospects", {
        "name":  name or email.split("@")[0],
        "email": email,
    })
    if created:
        return created.get("id")
    return None


def _axonaut_create_invoice(
    company_id: int,
    plan_type: str,
    amount_eur: float,
    stripe_ref: str,
) -> None:
    """Crée une facture dans Axonaut."""
    if not company_id:
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _axonaut("POST", "/invoices", {
        "prospect_id":    company_id,
        "reference":      stripe_ref[:30] if stripe_ref else "",
        "reference_date": today,
        "items": [{
            "name":       _plan_label(plan_type),
            "quantity":   1,
            "unit_amount": round(amount_eur, 2),
            "tax_rate":   20,
        }],
    })


# ===========================================================================
# EMAIL HELPERS
# ===========================================================================

_EMAIL_BASE = """\
<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<style>
  body{{margin:0;padding:0;background:#f4f4f4;font-family:'Segoe UI',Arial,sans-serif;}}
  .wrap{{max-width:560px;margin:32px auto;background:#1a1a1a;border-radius:8px;overflow:hidden;}}
  .hdr{{background:#111;padding:24px 32px;border-bottom:2px solid #00d4ff;}}
  .hdr h1{{margin:0;color:#00d4ff;font-size:22px;letter-spacing:1px;}}
  .body{{padding:28px 32px;color:#ddd;font-size:14px;line-height:1.7;}}
  .body h2{{color:#fff;font-size:16px;margin-top:0;}}
  .box{{background:#2a2a2a;border-left:3px solid #00d4ff;padding:12px 16px;
        border-radius:4px;margin:16px 0;color:#fff;font-size:13px;}}
  .btn{{display:inline-block;margin:20px 0;padding:12px 28px;background:#00d4ff;
        color:#000;font-weight:bold;text-decoration:none;border-radius:4px;font-size:14px;}}
  .ftr{{background:#111;padding:14px 32px;color:#555;font-size:11px;
        border-top:1px solid #2a2a2a;}}
</style></head><body>
<div class="wrap">
  <div class="hdr"><h1>MyStrow</h1></div>
  <div class="body">{content}</div>
  <div class="ftr">MyStrow · Logiciel de contrôle lumière professionnel<br>
  Cet email est envoyé automatiquement, merci de ne pas y répondre.</div>
</div></body></html>"""


def _send_email(to: str, subject: str, content: str, raise_on_error: bool = False) -> None:
    if not SMTP_HOST:
        print(f"[Email] SMTP non configuré — ignoré ({to})")
        return
    html = _EMAIL_BASE.format(content=content)
    msg  = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = to
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, to, msg.as_string())
        print(f"[Email] Envoyé → {to} ({subject})")
    except Exception as e:
        print(f"[Email] Erreur envoi → {to} : {e}")
        if raise_on_error:
            raise


def _email_welcome(email: str, password: str, expiry_ts: float, plan_type: str) -> None:
    _send_email(
        email,
        "Bienvenue sur MyStrow — Vos identifiants de connexion",
        f"""
<h2>Bienvenue sur MyStrow !</h2>
<p>Votre licence <b>{_plan_label(plan_type)}</b> vient d'être activée.
Voici vos identifiants :</p>
<div class="box">
  ✉️ &nbsp;<b>Email :</b> {email}<br>
  🔑 &nbsp;<b>Mot de passe temporaire :</b>
  <span style="font-family:monospace;font-size:14px;">{password}</span><br>
  📅 &nbsp;<b>Licence valide jusqu'au :</b> {_fmt_date(expiry_ts)}
</div>
<p>Lancez MyStrow, cliquez sur <b>Se connecter</b> et entrez ces identifiants.</p>
<p>Vous pourrez changer votre mot de passe depuis votre espace compte.</p>
<a class="btn" href="https://github.com/nprieto-ext/MAESTRO/releases/latest/download/MyStrow_Setup.exe">
  Télécharger MyStrow
</a>
""",
    )


def _email_renewal(email: str, expiry_ts: float) -> None:
    _send_email(
        email,
        "MyStrow — Licence renouvelée",
        f"""
<h2>Votre licence a été renouvelée</h2>
<p>Votre paiement a bien été traité. Votre licence MyStrow est prolongée.</p>
<div class="box">📅 &nbsp;<b>Nouvelle date d'expiration :</b> {_fmt_date(expiry_ts)}</div>
<p>Aucune action de votre part n'est requise. Continuez à utiliser MyStrow normalement.</p>
""",
    )


def _email_cancelled(email: str) -> None:
    _send_email(
        email,
        "MyStrow — Abonnement annulé",
        """
<h2>Votre abonnement a été annulé</h2>
<p>Votre abonnement MyStrow a bien été résilié.</p>
<p>Votre licence reste active jusqu'à la fin de la période en cours,
puis l'accès sera désactivé automatiquement.</p>
<p>Si vous souhaitez reprendre un abonnement, contactez-nous.</p>
""",
    )


def _email_payment_failed(email: str) -> None:
    _send_email(
        email,
        "MyStrow — Échec du paiement",
        """
<h2>Problème de paiement</h2>
<p>Nous n'avons pas pu encaisser votre paiement MyStrow.</p>
<p>Veuillez mettre à jour votre moyen de paiement pour éviter
l'interruption de votre licence.</p>
<p>Stripe effectuera automatiquement une nouvelle tentative dans les prochains jours.</p>
""",
    )


# ===========================================================================
# EVENT HANDLERS
# ===========================================================================

def _on_checkout_completed(session: dict) -> None:
    """Premier paiement — crée le compte et active la licence."""
    email       = (session.get("customer_details") or {}).get("email") or session.get("customer_email", "")
    customer_id = session.get("customer", "")
    sub_id      = session.get("subscription", "")
    amount_eur  = session.get("amount_total", 0) / 100.0
    cust_name   = (session.get("customer_details") or {}).get("name") or ""

    # Détermine le plan depuis l'abonnement Stripe
    plan_type = "lifetime"
    if sub_id:
        try:
            sub       = _stripe_get(f"/subscriptions/{sub_id}")
            price_id  = sub["items"]["data"][0]["price"]["id"]
            plan_type = _get_plan_type(price_id)
        except Exception as e:
            print(f"[Handler] Impossible de lire le plan Stripe : {e}")

    # Crée / récupère le compte Firebase
    temp_pwd        = _generate_password()
    uid, is_new     = _get_or_create_user(email, temp_pwd)
    expiry_ts       = _compute_expiry(plan_type)

    _set_license(uid, email, plan_type, expiry_ts,
                 stripe_customer_id=customer_id,
                 stripe_subscription_id=sub_id or "")

    # Stocke le mot de passe pour la récupération future
    if is_new:
        _get_db().collection("licenses").document(uid).set(
            {"password": temp_pwd}, merge=True
        )

    # Email
    if is_new:
        _email_welcome(email, temp_pwd, expiry_ts, plan_type)
    else:
        _email_renewal(email, expiry_ts)

    # Axonaut
    company_id = _axonaut_get_or_create_company(email, cust_name)
    _axonaut_create_invoice(company_id, plan_type, amount_eur,
                            stripe_ref=session.get("payment_intent", ""))

    print(f"[checkout.completed] {email} — {plan_type} — expire {_fmt_date(expiry_ts)}")


def _on_invoice_paid(invoice: dict) -> None:
    """Renouvellement mensuel / annuel."""
    # On ignore la 1ère facture (déjà gérée par checkout.session.completed)
    if invoice.get("billing_reason") == "subscription_create":
        return

    customer_id = invoice.get("customer", "")
    sub_id      = invoice.get("subscription", "")
    email       = invoice.get("customer_email", "")
    amount_eur  = invoice.get("amount_paid", 0) / 100.0
    stripe_ref  = invoice.get("id", "")
    cust_name   = invoice.get("customer_name") or ""

    uid = _find_uid_by_customer(customer_id)
    if not uid:
        print(f"[invoice.paid] UID introuvable pour customer {customer_id}")
        return

    plan_type = "monthly"
    try:
        sub      = _stripe_get(f"/subscriptions/{sub_id}")
        price_id = sub["items"]["data"][0]["price"]["id"]
        plan_type = _get_plan_type(price_id)
    except Exception:
        pass

    expiry_ts = _compute_expiry(plan_type)
    _set_license(uid, email, plan_type, expiry_ts,
                 stripe_customer_id=customer_id,
                 stripe_subscription_id=sub_id)

    _email_renewal(email, expiry_ts)

    company_id = _axonaut_get_or_create_company(email, cust_name)
    _axonaut_create_invoice(company_id, plan_type, amount_eur, stripe_ref=stripe_ref)

    print(f"[invoice.paid] {email} — expire {_fmt_date(expiry_ts)}")


def _on_subscription_deleted(subscription: dict) -> None:
    """Abonnement annulé — révoque la licence."""
    customer_id = subscription.get("customer", "")
    uid         = _find_uid_by_customer(customer_id)
    if not uid:
        print(f"[subscription.deleted] UID introuvable pour customer {customer_id}")
        return

    _revoke_license(uid)

    email = subscription.get("customer_email", "")
    if not email:
        try:
            email = auth.get_user(uid).email
        except Exception:
            pass
    if email:
        _email_cancelled(email)

    print(f"[subscription.deleted] uid={uid} — licence révoquée")


def _on_payment_failed(invoice: dict) -> None:
    """Échec de paiement — avertit le client."""
    email = invoice.get("customer_email", "")
    if email:
        _email_payment_failed(email)
    print(f"[invoice.payment_failed] {email}")


# ===========================================================================
# CLOUD FUNCTION: create_portal_session (Stripe Customer Portal)
# ===========================================================================

@https_fn.on_request(max_instances=5)
def create_portal_session(req: https_fn.Request) -> https_fn.Response:
    """
    Endpoint HTTPS : POST /create_portal_session
    Body: {"id_token": "<Firebase ID token>"}
    Retourne: {"ok": true, "url": "<Stripe Portal URL>"}
    """
    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405)

    try:
        body     = json.loads(req.get_data() or b"{}")
        id_token = (body.get("id_token") or "").strip()
    except Exception:
        return https_fn.Response("JSON invalide", status=400)

    if not id_token:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "id_token manquant"}),
            status=400, headers={"Content-Type": "application/json"},
        )

    try:
        _get_db()

        # Vérifie le token Firebase et récupère l'UID
        decoded = auth.verify_id_token(id_token)
        uid     = decoded["uid"]

        # Récupère le stripe_customer_id depuis Firestore
        doc = _get_db().collection("licenses").document(uid).get()
        if not doc.exists:
            return https_fn.Response(
                json.dumps({"ok": False, "error": "Licence introuvable"}),
                status=200, headers={"Content-Type": "application/json"},
            )

        customer_id = (doc.to_dict() or {}).get("stripe_customer_id", "")
        if not customer_id:
            return https_fn.Response(
                json.dumps({"ok": False, "error": "Aucun abonnement Stripe associé à ce compte"}),
                status=200, headers={"Content-Type": "application/json"},
            )

        # Crée une session Stripe Customer Portal
        import base64 as _b64
        token  = _b64.b64encode(f"{STRIPE_SECRET_KEY}:".encode()).decode()
        params = urllib.parse.urlencode({
            "customer":   customer_id,
            "return_url": "https://mystrow.fr",
        }).encode()
        portal_req = urllib.request.Request(
            "https://api.stripe.com/v1/billing_portal/sessions",
            data=params,
            headers={"Authorization": f"Basic {token}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(portal_req, timeout=10) as resp:
            session = json.loads(resp.read().decode())

        print(f"[create_portal_session] Session créée pour uid={uid}")
        return https_fn.Response(
            json.dumps({"ok": True, "url": session["url"]}),
            status=200, headers={"Content-Type": "application/json"},
        )

    except Exception as e:
        print(f"[create_portal_session] Erreur : {e}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": str(e)}),
            status=500, headers={"Content-Type": "application/json"},
        )


# ===========================================================================
# CLOUD FUNCTION: send_reset_email (reset mot de passe custom)
# ===========================================================================

@https_fn.on_request(max_instances=5)
def send_reset_email(req: https_fn.Request) -> https_fn.Response:
    """
    Endpoint HTTPS : POST /send_reset_email
    Body: {"email": "user@example.com"}
    Génère un lien Firebase password reset et envoie un email stylisé.
    """
    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405)

    try:
        body  = json.loads(req.get_data() or b"{}")
        email = (body.get("email") or "").strip().lower()
    except Exception:
        return https_fn.Response("JSON invalide", status=400)

    if not email or "@" not in email:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Email invalide"}),
            status=400, headers={"Content-Type": "application/json"},
        )

    try:
        db = _get_db()

        # Vérifie que l'utilisateur existe
        try:
            user = auth.get_user_by_email(email)
        except auth.UserNotFoundError:
            return https_fn.Response(
                json.dumps({"ok": True}),
                status=200, headers={"Content-Type": "application/json"},
            )

        uid = user.uid
        lic_ref = db.collection("licenses").document(uid)
        lic_doc = lic_ref.get()
        lic_data = lic_doc.to_dict() if lic_doc.exists else {}

        # ── Rate limiting : 3 emails max par heure ────────────────────────
        now = time.time()
        resets = [t for t in lic_data.get("reset_timestamps", []) if now - t < 3600]
        if len(resets) >= 3:
            return https_fn.Response(
                json.dumps({
                    "ok": False,
                    "error": (
                        "Limite atteinte (3 envois/heure).\n"
                        "Si vous avez toujours un problème, contactez le support : nicolas@mystrow.fr"
                    ),
                }),
                status=200, headers={"Content-Type": "application/json"},
            )

        # ── Récupère le mot de passe stocké, ou en génère un nouveau ─────
        pwd_to_send = lic_data.get("password")
        if not pwd_to_send:
            pwd_to_send = _generate_password(12)
            auth.update_user(uid, password=pwd_to_send)
            lic_ref.set({"password": pwd_to_send}, merge=True)

        # ── Envoi email ───────────────────────────────────────────────────
        _send_email(
            email,
            "MyStrow — Vos identifiants de connexion",
            f"""
<h2 style="color:#fff;margin-top:0;">Vos identifiants MyStrow</h2>
<p>Voici vos identifiants pour accéder à votre licence MyStrow :</p>
<div class="box">
  <div style="margin-bottom:10px;">
    ✉️ &nbsp;<b>Email :</b> <span style="color:#aaa;">{email}</span>
  </div>
  <div>
    🔑 &nbsp;<b>Mot de passe :</b><br>
    <span style="display:inline-block;margin-top:8px;padding:10px 20px;background:#0d0d0d;
      border:1px solid rgba(0,212,255,0.35);border-radius:8px;
      font-family:Consolas,monospace;font-size:20px;letter-spacing:5px;color:#00d4ff;
      box-shadow:0 0 12px rgba(0,212,255,0.15);">{pwd_to_send}</span>
  </div>
</div>
<p style="margin-top:16px;">
  Ouvrez <b>MyStrow</b>, cliquez sur <b>Se connecter</b> et entrez ces identifiants.
</p>
<p style="color:#555;font-size:11px;border-top:1px solid #2a2a2a;padding-top:12px;margin-top:12px;">
  Si vous n'avez pas fait cette demande, contactez-nous : nicolas@mystrow.fr
</p>
""",
            raise_on_error=True,
        )

        # Enregistre l'horodatage du reset
        resets.append(now)
        lic_ref.set({"reset_timestamps": resets}, merge=True)

        print(f"[send_reset_email] Email envoyé → {email}")
        return https_fn.Response(
            json.dumps({"ok": True}),
            status=200, headers={"Content-Type": "application/json"},
        )

    except Exception as e:
        print(f"[send_reset_email] Erreur : {e}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": str(e)}),
            status=500, headers={"Content-Type": "application/json"},
        )


# ===========================================================================
# CLOUD FUNCTION ENTRY POINT
# ===========================================================================

_HANDLERS = {
    "checkout.session.completed":    _on_checkout_completed,
    "invoice.payment_succeeded":     _on_invoice_paid,
    "customer.subscription.deleted": _on_subscription_deleted,
    "invoice.payment_failed":        _on_payment_failed,
}


def _make_fixture_uuid(name: str, manufacturer: str) -> str:
    """Genere un UUID stable et deterministe depuis name + manufacturer."""
    key = f"{manufacturer.lower().strip()}:{name.lower().strip()}".encode()
    h   = hashlib.md5(key).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ===========================================================================
# CLOUD FUNCTION: gdtf_upload (admin — import profils complets)
# ===========================================================================

@https_fn.on_request(max_instances=5, timeout_sec=300)
def gdtf_upload(req: https_fn.Request) -> https_fn.Response:
    """
    Endpoint HTTPS : POST /gdtf_upload
    Recoit des fixtures deja parsees (depuis admin panel) et les ecrit dans
    Firestore gdtf_fixtures avec leur profil complet (modes[].profile).
    Protege par Firebase ID token (Authorization: Bearer <token>).
    Body: {"fixtures": [{name, manufacturer, fixture_type, source, uuid, modes: [{name, channelCount, profile: [...]}]}]}
    """
    # Initialiser Firebase Admin avant toute vérification de token
    _get_db()

    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Token manquant — reconnectez-vous à l'admin panel"}),
            status=403,
            headers={"Content-Type": "application/json"},
        )
    id_token = auth_header[len("Bearer "):]
    try:
        decoded = auth.verify_id_token(id_token)
        print(f"[gdtf_upload] Accès autorisé pour {decoded.get('email', decoded.get('uid'))}")
    except Exception as e:
        print(f"[gdtf_upload] Token invalide : {e}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Token invalide ou expiré — reconnectez-vous"}),
            status=403,
            headers={"Content-Type": "application/json"},
        )

    try:
        body     = json.loads(req.get_data() or b"{}")
        fixtures = body.get("fixtures", [])
    except Exception as e:
        return https_fn.Response(
            json.dumps({"ok": False, "error": f"JSON invalide : {e}"}),
            status=400,
            headers={"Content-Type": "application/json"},
        )

    if not fixtures:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Aucune fixture dans la requete"}),
            status=400,
            headers={"Content-Type": "application/json"},
        )

    try:
        db = _get_db()

        meta_ref    = db.collection("gdtf_library").document("meta")
        meta_doc    = meta_ref.get()
        current_ver = meta_doc.get("libraryVersion") if meta_doc.exists else 0
        new_ver     = (current_ver or 0) + 1

        batch   = db.batch()
        ops     = 0
        written = 0
        errors  = []

        def _commit_if_full():
            nonlocal batch, ops
            if ops >= 450:
                batch.commit()
                batch = db.batch()
                ops   = 0

        for fx in fixtures:
            name = fx.get("name", "").strip()
            mfr  = fx.get("manufacturer", "").strip()
            if not name:
                errors.append("Fixture sans nom ignoree")
                continue

            # UUID : genere de facon deterministe si absent
            uuid = (fx.get("uuid") or "").strip()
            if not uuid:
                uuid = _make_fixture_uuid(name, mfr)

            # Firestore doc IDs ne peuvent pas contenir '/' (ex: uuid OFL = "ofl:mfr/fixture")
            doc_id = uuid.replace("/", "_")

            doc_data = {
                "uuid":         uuid,
                "name":         name,
                "manufacturer": mfr,
                "fixture_type": fx.get("fixture_type", "PAR LED"),
                "source":       fx.get("source", "custom"),
                "modes":        fx.get("modes", []),
                "has_profile":  True,
                "updatedAtVersion": new_ver,
            }

            ref      = db.collection("gdtf_fixtures").document(doc_id)
            existing = ref.get()
            if existing.exists:
                batch.update(ref, doc_data)
            else:
                doc_data["addedAtVersion"] = new_ver
                batch.set(ref, doc_data)
            written += 1
            ops += 1
            _commit_if_full()

        if ops > 0:
            batch.commit()

        # Mise a jour meta
        meta_ref.set({"libraryVersion": new_ver, "lastSync": time.time()}, merge=True)

        result = {
            "ok":         True,
            "written":    written,
            "errors":     errors,
            "newVersion": new_ver,
        }
        print(f"[gdtf_upload] {written} fixture(s) ecrites en Firestore")
        return https_fn.Response(
            json.dumps(result),
            status=200,
            headers={"Content-Type": "application/json"},
        )

    except Exception as exc:
        print(f"[gdtf_upload] ERREUR: {exc}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": str(exc)}),
            status=500,
            headers={"Content-Type": "application/json"},
        )


# ===========================================================================
# STRIPE CLOUD FUNCTION ENTRY POINT
# ===========================================================================

@https_fn.on_request(cors=False, max_instances=10)
def stripe_webhook(req: https_fn.Request) -> https_fn.Response:
    """
    Endpoint HTTPS : POST /stripe_webhook
    URL à renseigner dans Stripe → Developers → Webhooks.
    """
    payload    = req.get_data()
    sig_header = req.headers.get("Stripe-Signature", "")

    if not _verify_stripe_signature(payload, sig_header):
        print("[Webhook] Signature invalide — requête rejetée")
        return https_fn.Response("Signature invalide", status=400)

    try:
        event = json.loads(payload)
    except Exception:
        return https_fn.Response("JSON invalide", status=400)

    event_type = event.get("type", "")
    data_obj   = event.get("data", {}).get("object", {})

    handler = _HANDLERS.get(event_type)
    if handler:
        try:
            handler(data_obj)
        except Exception as exc:
            # On log l'erreur mais on retourne 200 pour éviter
            # que Stripe ne re-tente en boucle sur des erreurs non-critiques.
            print(f"[Webhook] Erreur dans handler '{event_type}' : {exc}")
    else:
        print(f"[Webhook] Événement ignoré : {event_type}")

    return https_fn.Response("OK", status=200)
