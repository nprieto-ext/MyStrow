"""
Firebase Cloud Function — Webhook Stripe pour MyStrow.

Gère :
  - checkout.session.completed    → crée compte + active licence + facture Axonaut
  - invoice.payment_succeeded     → renouvelle licence + facture Axonaut
  - customer.subscription.deleted → révoque la licence
  - customer.subscription.updated → révoque si statut 'unpaid'/'canceled' (filet)
  - invoice.payment_failed        → email d'avertissement + grâce de 7 jours
  - charge.refunded               → avoir Axonaut du montant remboursé

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
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

import firebase_admin
from firebase_admin import auth, firestore
from firebase_functions import https_fn
# « Le document existait déjà » : réponse NORMALE du verrou anti-rejeu
# (_claim_stripe_event), pas une panne. On attrape `Conflict` et non
# `AlreadyExists` : la doc de `DocumentReference.create()` promet
# `google.cloud.exceptions.Conflict`, dont `AlreadyExists` n'est qu'une
# sous-classe — attraper la fille seule laisserait passer l'autre cas.
# google-api-core est une dépendance déclarée dans requirements.txt.
from google.api_core.exceptions import Conflict

_db = None


def _ensure_init():
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def _get_db():
    global _db
    if _db is None:
        _ensure_init()
        _db = firestore.client()
    return _db

# ---------------------------------------------------------------------------
# Config — lue à la demande pour que Firebase ait injecté les secrets
# ---------------------------------------------------------------------------
def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

def _stripe_secret_key()     -> str: return _cfg("STRIPE_SECRET_KEY")
def _stripe_webhook_secret() -> str: return _cfg("STRIPE_WEBHOOK_SECRET")
def _stripe_price_monthly()  -> str: return _cfg("STRIPE_PRICE_MONTHLY")
def _stripe_price_annual()   -> str: return _cfg("STRIPE_PRICE_ANNUAL")
def _stripe_price_lifetime() -> str: return _cfg("STRIPE_PRICE_LIFETIME")
def _smtp_host()     -> str: return _cfg("SMTP_HOST")
def _smtp_port()     -> int: return int(_cfg("SMTP_PORT", "465"))
def _smtp_user()     -> str: return _cfg("SMTP_USER")
def _smtp_password() -> str: return _cfg("SMTP_PASSWORD")
def _smtp_from()     -> str: return _cfg("SMTP_FROM")
def _axonaut_key()   -> str: return _cfg("AXONAUT_API_KEY")
def _brevo_key()     -> str: return _cfg("BREVO_API_KEY").strip()
def _sender_token()  -> str: return _cfg("SENDER_API_TOKEN").strip()

# Groupe Sender.net qui recevait les inscrits de la newsletter (« MYSTROW »).
# Conserve pour la reprise des contacts historiques ; l'inscription passe
# desormais par Brevo (cf. _brevo_list_newsletter).
SENDER_GROUP_NEWSLETTER = "bkgJBE"

# Liste Brevo qui recoit les inscrits de la newsletter. En variable et non en
# constante : l'identifiant est cree dans l'interface Brevo, il n'a aucune
# raison d'etre fige dans le code.
def _brevo_list_newsletter() -> int:
    try:
        return int(_cfg("BREVO_LIST_NEWSLETTER", "0"))
    except ValueError:
        return 0


# Liste Brevo des CLIENTS, volontairement distincte de la newsletter.
#
# Acheter une licence n'est pas consentir a recevoir du marketing : cette liste
# ne sert qu'aux messages de service (relance d'expiration, information produit
# liee au contrat). Le passage vers la newsletter reste soumis au consentement
# explicite (`newsletter_consent`), et ne se fait jamais ici.
def _brevo_list_clients() -> int:
    try:
        return int(_cfg("BREVO_LIST_CLIENTS", "0"))
    except ValueError:
        return 0


# Domaines exclus de toute synchronisation Brevo (cf. _brevo_sync_client).
_BREVO_DOMAINES_EXCLUS = {"tuifrance.com"}


def _brevo_statut(plan_type: str, sub_id: str) -> str:
    """Categorie commerciale envoyee a Brevo. C'est elle qui autorise ou non une relance.

    ⚠️ `expiry_utc` n'est PAS une expiration pour un abonne Stripe : c'est la fin
    de la periode courante, repoussee a chaque paiement par `_on_invoice_paid`.
    Un « votre licence expire dans 15 jours » envoye a un abonne dont tout se
    renouvelle seul est le message qui declenche une resiliation.

    Meme regle que `license_manager._is_auto_renew` : recurrent ET identifiant
    d'abonnement present. La condition sur l'identifiant compte — une activation
    manuelle (`admin_activate_user.py`) pose `plan_type="monthly"` sans
    abonnement Stripe et a, elle, une vraie echeance.
    """
    if plan_type == "lifetime":
        return "a_vie"
    if plan_type in ("monthly", "annual") and (sub_id or "").strip():
        return "abonne"
    return "echeance_fixe"


def _brevo_sync_client(email: str, uid: str, plan_type: str, expiry_ts: float,
                       lang: str = "fr", sub_id: str = "") -> None:
    """Cree ou met a jour le contact client dans Brevo. N'echoue JAMAIS bruyamment.

    Appele depuis les gestionnaires de webhook Stripe : une erreur Brevo ne doit
    pas faire echouer le webhook. Stripe rejouerait alors la notification, et on
    reglerait deux fois une licence deja reglee pour un simple probleme de
    synchronisation marketing. On journalise et on continue.
    """
    key, list_id = _brevo_key(), _brevo_list_clients()
    if not key or not list_id:
        print("[Brevo] BREVO_LIST_CLIENTS non configure — synchro client ignoree")
        return

    # Domaines qui n'entrent JAMAIS dans Brevo. tuifrance.com est un contrat
    # B2B : une soixantaine de boites d'hotels a la meme echeance, gerees par un
    # interlocuteur unique. Les relancer une par une n'a aucun sens — au pire
    # soixante messages arrivent le meme jour chez le meme groupe. Le
    # renouvellement se traite comme un marche, pas comme un cycle de vie client.
    if (email or "").strip().lower().rsplit("@", 1)[-1] in _BREVO_DOMAINES_EXCLUS:
        print(f"[Brevo] {email} — domaine exclu, synchro ignoree")
        return
    payload = json.dumps({
        "email":      email,
        "listIds":    [list_id],
        "attributes": {
            "PLAN":   plan_type or "",
            # Brevo attend une date, pas un horodatage.
            "EXPIRY": _fmt_date_iso(expiry_ts),
            "LANG":   (lang or "fr").upper(),
            "UID":    uid or "",
            "STATUT": _brevo_statut(plan_type, sub_id),
        },
        # Un renouvellement doit METTRE A JOUR l'expiration, pas echouer sur un
        # « duplicate_parameter » parce que le client existe deja.
        "updateEnabled": True,
    }).encode()
    req = urllib.request.Request("https://api.brevo.com/v3/contacts",
                                 data=payload, method="POST")
    req.add_header("api-key", key)
    req.add_header("content-type", "application/json")
    req.add_header("accept", "application/json")
    # Cf. _send_email_brevo_api : sans User-Agent de navigateur, Cloudflare
    # repond « Error 1010: Access denied » en 403.
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; MyStrow/1.0; "
                                 "+https://mystrow.fr)")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
        print(f"[Brevo] client synchronise → {email} ({plan_type}, "
              f"expire {_fmt_date_iso(expiry_ts)})")
    except Exception as e:
        detail = e.read().decode("utf-8", "replace")[:200] if hasattr(e, "read") else e
        print(f"[Brevo] synchro client echouee → {email} : {detail}")

AXONAUT_BASE = "https://axonaut.com/api/v2"

# Taux de TVA de REPLI, en pourcentage.
# Les montants Stripe sont des montants TTC (prix affiché au client) ; Axonaut
# attend un prix unitaire HT et rajoute la TVA. Ce taux sert donc DEUX fois —
# pour déduire le HT et pour le champ `tax_rate` — et les deux doivent rester
# cohérents, d'où la constante unique.
#
# ⚠️ Ce taux n'est utilisé QUE lorsque Stripe ne calcule pas la TVA lui-même
# (`automatic_tax.enabled` faux). Dès que Stripe Tax est activé dans le
# Dashboard, la TVA réelle vient de Stripe : 21 % en Belgique, 19 % en
# Allemagne, 0 % en autoliquidation B2B intra-UE ou hors UE. Appliquer 20 %
# en dur à ces cas produirait des factures Axonaut fausses.
TVA_RATE = 20

# Nom du champ « numéro de TVA intracommunautaire » sur une société Axonaut.
# ⚠️ Axonaut ignore SILENCIEUSEMENT les champs qu'il ne connaît pas — c'est ce
# qui avait fait disparaître l'adresse client pendant des mois (cf.
# _axonaut_get_or_create_company). Le nom exact n'étant pas documenté
# publiquement, `_axonaut_verify_vat()` relit la fiche après écriture et log le
# vrai nom du champ si celui-ci est faux. Corriger ici le cas échéant.
#
# Valeur vérifiée sur l'API le 26/08/2026 (GET /companies, 176 fiches) : le
# champ s'appelle bien `intracommunity_number`. `vat_number`, la valeur posée
# ici jusque-là, n'existe dans AUCUNE fiche — tout numéro de TVA envoyé sous ce
# nom était accepté « 200 OK » puis jeté. Le garde-fou `_axonaut_verify_vat()`
# ne l'a jamais signalé parce qu'aucun acheteur ne fournissait de numéro : la
# collecte des identifiants fiscaux n'était pas activée sur les Payment Links.
AXONAUT_VAT_FIELD = "intracommunity_number"

# Durée des plans en jours
_PLAN_DAYS = {
    "monthly":  31,
    "annual":   366,
    "lifetime": 36500,  # ~100 ans
}

# Jours de grâce accordés après un échec de paiement (le temps que Stripe
# relance et que le client mette sa carte à jour) avant coupure de la licence.
_GRACE_DAYS = 7


# ===========================================================================
# STRIPE HELPERS
# ===========================================================================

def _stripe_get(path: str) -> dict:
    """GET vers l'API Stripe."""
    import base64
    url = f"https://api.stripe.com/v1{path}"
    token = base64.b64encode(f"{_stripe_secret_key()}:".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _stripe_post(path: str, params: dict) -> dict:
    """POST vers l'API Stripe (x-www-form-urlencoded)."""
    import base64
    url = f"https://api.stripe.com/v1{path}"
    token = base64.b64encode(f"{_stripe_secret_key()}:".encode()).decode()
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _verify_stripe_signature(payload: bytes, sig_header: str) -> bool:
    """Vérifie la signature HMAC-SHA256 du webhook Stripe."""
    secret = _stripe_webhook_secret()
    if not secret:
        print("[Webhook] STRIPE_WEBHOOK_SECRET non configuré — vérification ignorée (DANGER)")
        return True   # permet de déboguer sans bloquer ; à remettre à False en prod
    try:
        parts = dict(item.split("=", 1) for item in sig_header.split(","))
        timestamp = parts.get("t", "")
        v1        = parts.get("v1", "")
        signed    = timestamp.encode() + b"." + payload
        expected  = hmac.new(
            secret.encode(), signed, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception as e:
        print(f"[Webhook] Erreur vérification signature : {e}")
        return False


def _get_plan_type(price_id: str) -> str:
    if price_id == _stripe_price_monthly():
        return "monthly"
    if price_id == _stripe_price_annual():
        return "annual"
    if price_id == _stripe_price_lifetime():
        return "lifetime"
    return "monthly"


def _get_plan_price_ttc(plan_type: str) -> float:
    """Montant TTC depuis le price Stripe configuré — fallback quand le montant
    encaissé est absent de l'événement.

    C'est bien du TTC : les prix Stripe sont les montants affichés au client
    (23,99 € = ce qu'il paie), aucune taxe n'est ajoutée au moment du paiement.
    L'ancien nom (`_get_plan_price_ht`) est à l'origine de la facturation
    erronée corrigée le 28/07/2026 — cf. TVA_RATE."""
    _map = {
        "monthly":  _stripe_price_monthly,
        "annual":   _stripe_price_annual,
        "lifetime": _stripe_price_lifetime,
    }
    fn = _map.get(plan_type)
    if not fn:
        return 0.0
    try:
        price = _stripe_get(f"/prices/{fn()}")
        cents = price.get("unit_amount") or 0
        return round(cents / 100.0, 2)
    except Exception as e:
        print(f"[_get_plan_price_ttc] {e}")
        return 0.0


def _plan_label(plan_type: str, lang: str = "fr") -> str:
    labels = {
        "fr": {
            "monthly":  "Licence MyStrow — Mensuel",
            "annual":   "Licence MyStrow — Annuel",
            "lifetime": "Licence MyStrow — À vie",
        },
        "en": {
            "monthly":  "MyStrow License — Monthly",
            "annual":   "MyStrow License — Annual",
            "lifetime": "MyStrow License — Lifetime",
        },
    }
    table   = labels.get(lang, labels["fr"])
    default = "MyStrow License" if lang == "en" else "Licence MyStrow"
    return table.get(plan_type, default)


def _compute_expiry(plan_type: str) -> float:
    return time.time() + _PLAN_DAYS.get(plan_type, 31) * 86400


def _fmt_date(ts: float, lang: str = "fr") -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if lang == "en":
        return dt.strftime("%B %d, %Y")
    return dt.strftime("%d/%m/%Y")


def _fmt_date_iso(ts: float) -> str:
    """AAAA-MM-JJ — format des attributs de type date chez Brevo.

    Distinct de `_fmt_date`, qui est destine a l'oeil du client et depend de sa
    langue. Envoyer un « 20/08/2026 » francais dans un attribut date de Brevo le
    fait rejeter en silence : l'attribut reste vide, la relance d'expiration ne
    part jamais et rien ne signale l'erreur.

    Rend "" au-dela de 2099, borne haute de Brevo. C'est le cas des licences A
    VIE, dont `expiry_utc` tombe vers 2126 : Brevo ecrete la valeur a
    2099-12-31 sur une mise a jour, mais l'ABANDONNE a la creation — deux
    comportements pour la meme donnee, aucun message. Une licence a vie n'ayant
    pas d'echeance, l'attribut vide est la bonne reponse : la relance
    d'expiration ne doit jamais viser ces clients, et `PLAN=lifetime` reste la
    pour les segmenter.
    """
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    return "" if dt.year > 2099 else dt.strftime("%Y-%m-%d")


# Locales du navigateur / pays considérés francophones (sinon → anglais).
_FR_COUNTRIES = {"FR", "BE", "CH", "LU", "MC"}


def _detect_lang(locales: list[str] | None = None, country: str | None = None) -> str:
    """Choisit la langue des emails : 'fr' ou 'en'.

    Priorité : locale du navigateur (Stripe Checkout `locale` / `preferred_locales`),
    puis pays de facturation. Défaut 'fr' (produit francophone) quand aucun
    signal n'est disponible — pour ne pas surprendre les clients existants.
    """
    for loc in (locales or []):
        if loc:
            return "fr" if loc.lower().startswith("fr") else "en"
    if country:
        return "fr" if country.upper() in _FR_COUNTRIES else "en"
    return "fr"


def _lang_for_uid(uid: str | None) -> str:
    """Relit la langue stockée sur la licence (events sans locale Stripe)."""
    if not uid:
        return "fr"
    try:
        doc = _get_db().collection("licenses").document(uid).get()
        if doc.exists:
            return (doc.to_dict() or {}).get("lang") or "fr"
    except Exception:
        pass
    return "fr"


# ===========================================================================
# FIREBASE HELPERS
# ===========================================================================

def _get_or_create_user(email: str, password: str) -> tuple[str, bool]:
    """
    Retourne (uid, is_new).
    Crée l'utilisateur Firebase Auth si inexistant.
    """
    _ensure_init()
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
    lang: str = "",
) -> None:
    """Crée ou met à jour le document Firestore /licenses/{uid}."""
    ref = _get_db().collection("licenses").document(uid)
    doc = ref.get()

    data = {
        "plan":       "license",
        "expiry_utc": expiry_ts,
        "plan_type":  plan_type,
    }

    # Les identifiants Stripe ne sont écrits QUE s'ils sont renseignés.
    #
    # Un champ absent de l'événement reçu ne doit jamais effacer une donnée
    # valide en base : c'est exactement ce qui s'est produit avec
    # `stripe_subscription_id`, vidé au fil des renouvellements pour 14 abonnés
    # actifs (constaté le 12/08/2026) parce que Stripe a sorti `subscription` de
    # la racine de l'objet invoice. La suppression *volontaire* de l'identifiant
    # reste possible, mais elle passe par _revoke_license().
    if stripe_customer_id:
        data["stripe_customer_id"] = stripe_customer_id
    if stripe_subscription_id:
        data["stripe_subscription_id"] = stripe_subscription_id

    # Langue des emails (détectée au checkout) — conservée pour les events suivants.
    if lang:
        data["lang"] = lang

    # Lifetime : licence permanente ET mises à jour à vie. On n'écrit donc plus
    # de updates_until_utc — la limite d'un an a été supprimée de l'offre.

    if doc.exists:
        ref.update(data)
    else:
        # Document neuf : aucune valeur à préserver, on pose les deux champs
        # même vides pour que le schéma reste homogène.
        ref.set({
            "stripe_customer_id":     stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
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


def _apply_payment_grace(uid: str, days: int = _GRACE_DAYS) -> None:
    """Échec de paiement : prolonge l'accès de `days` jours sans couper.

    On garde plan='license' et on repousse expiry_utc à maintenant + `days`,
    sans jamais raccourcir une expiration déjà plus lointaine (ex: annuel).
    """
    ref = _get_db().collection("licenses").document(uid)
    doc = ref.get()
    if not doc.exists:
        return
    current     = float((doc.to_dict() or {}).get("expiry_utc", 0) or 0)
    grace_until = time.time() + days * 86400
    ref.update({
        "plan":       "license",
        "expiry_utc": max(current, grace_until),
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

# Taux de TVA normaux des États membres, pour recaler un taux déduit.
# Une facture doit porter un taux LÉGAL : déduire le taux en divisant la TVA
# par le HT donne 20,01 % ou 18,95 % à cause des arrondis au centime, ce qui
# n'existe dans aucun barème. On recale donc sur le taux normal le plus proche
# (ils sont espacés d'au moins 1 point, la tolérance de 0,5 est sans risque).
_TAUX_TVA_UE = (0.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 27.0)


def _stripe_tax_details(obj: dict) -> tuple[float | None, bool]:
    """(taux de TVA en %, Stripe calcule-t-il la TVA ?) pour une session
    Checkout ou une facture Stripe.

    Le booléen est la clé : il distingue « 0 % parce que c'est une
    autoliquidation B2B » de « 0 % parce que Stripe Tax n'est pas activé ».
    Sans lui, on ne saurait pas s'il faut croire le taux ou retomber sur
    TVA_RATE — et on facturerait 0 % de TVA à toute la France.

    On renvoie un TAUX et non un montant : c'est lui qui doit figurer sur la
    facture, et le HT s'en déduit exactement. L'inverse (HT = TTC − TVA, puis
    taux = TVA / HT) fabrique des taux illégaux.
    """
    enabled = bool((obj.get("automatic_tax") or {}).get("enabled"))

    # 1) Taux annoncé par Stripe, quand la ventilation est présente dans le
    #    payload. C'est la source de vérité : aucun arrondi à recaler.
    for taxes in (((obj.get("total_details") or {}).get("breakdown") or {}).get("taxes"),
                  obj.get("total_taxes"),
                  obj.get("total_tax_amounts")):
        if not isinstance(taxes, list):
            continue
        for entry in taxes:
            if not isinstance(entry, dict):
                continue
            rate = entry.get("rate") or entry.get("tax_rate") or entry.get("tax_rate_details")
            if isinstance(rate, dict):
                pct = rate.get("percentage")
                if pct is None:
                    pct = rate.get("percentage_decimal")
                if pct is not None:
                    try:
                        return round(float(pct), 2), enabled
                    except (TypeError, ValueError):
                        pass

    # 2) Sinon, déduire des montants puis recaler sur un taux normal connu.
    amount_tax = None
    total_details = obj.get("total_details")
    if isinstance(total_details, dict) and total_details.get("amount_tax") is not None:
        amount_tax = total_details["amount_tax"] / 100.0         # Checkout Session
    elif obj.get("tax") is not None:
        amount_tax = obj["tax"] / 100.0                          # Facture, API historique
    elif isinstance(obj.get("total_taxes"), list):               # Facture, API récente
        amount_tax = sum((t.get("amount") or 0) for t in obj["total_taxes"]) / 100.0

    if amount_tax is None:
        return None, enabled

    total = obj.get("amount_total")
    if total is None:
        total = obj.get("amount_paid")
    if total is None:
        return None, enabled
    ttc = total / 100.0
    ht = ttc - amount_tax
    if ht <= 0:
        # TTC nul (promo 100 %) ou entièrement taxé : rien à déduire.
        return (0.0 if amount_tax == 0 else None), enabled

    brut = amount_tax / ht * 100.0
    proche = min(_TAUX_TVA_UE, key=lambda t: abs(t - brut))
    return (proche if abs(proche - brut) <= 0.5 else round(brut, 2)), enabled


def _stripe_vat_number(obj: dict) -> str:
    """Numéro de TVA intracommunautaire saisi par le client au paiement.

    Vide tant que la collecte des identifiants fiscaux n'est pas activée sur le
    Payment Link dans le Dashboard Stripe, ou si l'acheteur est un particulier.
    """
    tax_ids = ((obj.get("customer_details") or {}).get("tax_ids")
               or obj.get("customer_tax_ids") or [])
    if not isinstance(tax_ids, list):
        return ""
    for entry in tax_ids:
        if isinstance(entry, dict) and entry.get("value"):
            return str(entry["value"]).replace(" ", "").upper()
    return ""


def _siren_from_vat(vat_number: str) -> str:
    """SIREN déduit d'un numéro de TVA français (`FR` + 2 car. de clé + SIREN).

    Utile pour la facturation électronique : l'annuaire du Portail Public route
    les factures par SIREN, et le SIREN du client devient une mention
    obligatoire. Le collecter séparément est donc inutile pour les clients
    français — il est déjà dans le numéro de TVA.
    """
    value = (vat_number or "").replace(" ", "").upper()
    if value.startswith("FR") and len(value) == 13 and value[4:].isdigit():
        return value[4:]
    return ""


def _axonaut(method: str, path: str, payload: dict | None = None):
    """Appel générique API Axonaut."""
    key = _axonaut_key()
    if not key:
        return None
    url  = f"{AXONAUT_BASE}{path}"
    data = json.dumps(payload).encode() if payload else None
    headers = {"userApiKey": key}
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


def _axonaut_verify_vat(company_id: int, expected: str) -> None:
    """Relit la société et vérifie que le numéro de TVA a bien été enregistré.

    Axonaut répond « 200 OK » même quand il ignore un champ inconnu : un POST
    réussi ne prouve donc RIEN. On relit la fiche, et si la valeur n'en ressort
    pas on log les champs réellement disponibles, pour corriger
    AXONAUT_VAT_FIELD sans avoir à deviner.
    """
    if not company_id or not expected:
        return
    fresh = _axonaut("GET", f"/companies/{company_id}")
    if not isinstance(fresh, dict):
        return
    for key, value in fresh.items():
        if isinstance(value, str) and value.replace(" ", "").upper() == expected:
            if key != AXONAUT_VAT_FIELD:
                print(f"[Axonaut] TVA enregistree dans le champ « {key} » et non "
                      f"« {AXONAUT_VAT_FIELD} » — corriger AXONAUT_VAT_FIELD")
            else:
                print(f"[Axonaut] TVA client enregistree : {expected}")
            return
    print(f"[Axonaut] ⚠️ Numero de TVA « {expected} » NON enregistre : le champ "
          f"« {AXONAUT_VAT_FIELD} » est probablement inconnu d'Axonaut. "
          f"Champs disponibles : {sorted(fresh.keys())}")


def _axonaut_get_or_create_company(email: str, name: str, address: dict | None = None,
                                   uid: str | None = None,
                                   vat_number: str = "") -> int | None:
    """Retourne l'ID Axonaut de la société, la crée si inexistante.

    L'ID est mémorisé dans /licenses/{uid}.axonaut_company_id et réutilisé
    aux renouvellements : sans ça, `GET /companies` (paginé / email parfois
    absent du payload liste) ne retrouvait pas la société et en créait une
    NOUVELLE à chaque facture mensuelle.
    """
    # Champs d'adresse au format ATTENDU par Axonaut (address_street, etc.).
    # ⚠️ Bug historique : on envoyait address/zip/city/country → ignorés par
    # Axonaut → aucune facture n'avait l'adresse client.
    addr: dict = {}
    if address:
        if address.get("line1"):       addr["address_street"]   = address["line1"]
        if address.get("postal_code"): addr["address_zip_code"] = address["postal_code"]
        if address.get("city"):        addr["address_city"]     = address["city"]
        if address.get("country"):     addr["address_country"]  = address["country"]
    # Identifiants fiscaux — mentions obligatoires à l'émission des factures
    # électroniques (01/09/2027). L'annuaire du Portail Public route par
    # SIREN/SIRET : sans lui, une facture à un pro français n'est pas routable.
    # Axonaut accepte indifféremment un SIREN (9 chiffres) ou un SIRET (14)
    # dans `siret` — les deux formats coexistent déjà en base.
    if vat_number:
        addr[AXONAUT_VAT_FIELD] = vat_number
        siren = _siren_from_vat(vat_number)
        if siren:
            addr["siret"] = siren
    # ⚠️ Ne PAS tenter d'écrire `isB2C` ici : le champ apparaît en lecture sur
    # `GET /companies` mais l'API l'ignore en écriture, sous ce nom comme sous
    # `is_b2c`, `isb2c`, `b2c` ou `is_B2C` (testé le 26/08/2026 en POST et en
    # PATCH : la fiche revient toujours à `null`). C'est pourtant lui qui, en
    # 2027, sépare la facture électronique de l'e-reporting — il devra donc
    # être posé depuis l'interface Axonaut ou via un futur endpoint.

    # Le numéro de TVA (et le SIREN qu'il contient) est conservé côté licence :
    # il servira de mention obligatoire à l'émission des factures électroniques,
    # y compris pour les clients déjà en base au moment de la bascule.
    if uid and vat_number:
        try:
            _get_db().collection("licenses").document(uid).set(
                {"vat_number": vat_number, "siren": _siren_from_vat(vat_number)},
                merge=True,
            )
        except Exception as e:
            print(f"[Firebase] Sauvegarde du numero de TVA ignoree : {e}")

    def _patch_addr(cid) -> None:
        """Met à jour l'adresse (et la TVA) d'une société existante — backfill
        des clients créés avant la collecte du numéro."""
        if addr and cid:
            _axonaut("PATCH", f"/companies/{cid}", addr)
            _axonaut_verify_vat(cid, vat_number)

    # 1) ID déjà mémorisé pour cet utilisateur → réutilisation directe
    lic_ref = None
    if uid:
        try:
            lic_ref = _get_db().collection("licenses").document(uid)
            snap = lic_ref.get()
            if snap.exists:
                cached = (snap.to_dict() or {}).get("axonaut_company_id")
                if cached:
                    print(f"[Axonaut] Societe reutilisee (cache) : id={cached}")
                    _patch_addr(cached)
                    return int(cached)
        except Exception as e:
            print(f"[Axonaut] Lecture cache company_id ignoree : {e}")

    # 2) Recherche par email (best-effort, 1re page)
    company_id = None
    result = _axonaut("GET", "/companies")
    if isinstance(result, list):
        email_lower = email.lower()
        for company in result:
            contacts = company.get("contacts") or []
            if isinstance(contacts, list):
                for c in contacts:
                    if (c.get("email") or "").lower() == email_lower:
                        company_id = company["id"]
                        break
            if company_id is None and (company.get("email") or "").lower() == email_lower:
                company_id = company["id"]
            if company_id is not None:
                print(f"[Axonaut] Societe trouvee : id={company_id}")
                _patch_addr(company_id)
                break

    # 3) Création si rien trouvé
    if company_id is None:
        payload: dict = {
            "name":  name or email.split("@")[0],
            "email": email,
        }
        payload.update(addr)
        created = _axonaut("POST", "/companies", payload)
        if created:
            company_id = created.get("id")
            print(f"[Axonaut] Societe creee : id={company_id}")
            _axonaut_verify_vat(company_id, vat_number)

    # 4) Mémoriser l'ID pour les prochaines factures de cet utilisateur
    if company_id and lic_ref is not None:
        try:
            lic_ref.set({"axonaut_company_id": int(company_id)}, merge=True)
        except Exception as e:
            print(f"[Axonaut] Sauvegarde company_id ignoree : {e}")

    return company_id


def _axonaut_register_payment(invoice_id: int, amount_ttc: float, reference: str,
                              nature: int = 4) -> None:
    """Enregistre un paiement sur une facture Axonaut → la passe en « payée ».

    Endpoint : POST /payments (schéma invoicePayment.post).
    nature : 1=Prélèvement, 2=Virement, 3=Chèque, 4=Carte bancaire, 5=Espèces, 6=Autre.
    Stripe = carte bancaire → nature 4. Le montant est le TTC réellement encaissé,
    pour que la somme des paiements couvre le total TTC et solde la facture.
    """
    if not invoice_id or not amount_ttc:
        print(f"[Axonaut] Paiement non enregistré (invoice_id={invoice_id}, montant={amount_ttc})")
        return
    # Axonaut exige un ISO8601 complet (date + heure + fuseau) pour le champ
    # `date` du schéma invoicePayment.post — une date seule "YYYY-MM-DD" est
    # rejetée (HTTP 4xx) et la facture reste impayée.
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")  # 2026-06-02T12:34:56+00:00
    result = _axonaut("POST", "/payments", {
        "invoice_id": invoice_id,
        "amount":     round(amount_ttc, 2),
        "date":       now_iso,
        "nature":     nature,                  # 4 = CB (Stripe), 6 = Autre (avoir)
        "reference":  (reference or "Stripe")[:30],
    })
    if result:
        print(f"[Axonaut] Paiement enregistré : invoice_id={invoice_id} montant={round(amount_ttc, 2)} € TTC")
    else:
        print(f"[Axonaut] Échec enregistrement paiement (invoice_id={invoice_id})")


def _axonaut_invoice_exists(uid: str, stripe_ref: str) -> bool:
    """Une facture porte-t-elle déjà cette référence Stripe ?

    On ne regarde que les factures (`type == "invoice"`) : un avoir porte la
    référence de la charge remboursée et ne doit pas empêcher une refacturation.
    En cas d'erreur de lecture on répond False — bloquer une facture légitime
    coûte plus cher qu'un doublon, qui se voit et se corrige.
    """
    try:
        docs = (_get_db().collection("licenses").document(uid)
                .collection("invoices")
                .where("stripe_ref", "==", stripe_ref).limit(1).get())
        return any((d.to_dict() or {}).get("type", "invoice") == "invoice"
                   for d in docs)
    except Exception as e:
        print(f"[Axonaut] Controle anti-doublon impossible ({e}) — on continue")
        return False


def _axonaut_create_invoice(
    company_id: int,
    plan_type: str,
    amount_ttc: float | None,
    stripe_ref: str,
    uid: str = "",
    tax_rate_stripe: float | None = None,
    stripe_tax: bool = False,
) -> None:
    """Crée une facture dans Axonaut et stocke le lien dans Firestore.

    `amount_ttc` est le montant réellement encaissé par Stripe, donc du TTC :
    c'est le prix affiché au client (23,99 €). Axonaut, lui, attend un prix
    unitaire HORS TAXES et rajoute la TVA par-dessus. Passer le TTC tel quel
    dans `price` produisait « 23,99 € HT / 28,79 € TTC » — le client payait
    23,99 € et la facture en annonçait 28,79 €."""
    # Deuxième ligne de défense derrière `_claim_stripe_event` : une même
    # référence Stripe ne doit jamais produire deux factures. Le verrou
    # d'événement couvre le rejeu de webhook ; celui-ci couvre tout le reste
    # (renvoi manuel depuis le Dashboard, deux événements distincts portant le
    # même encaissement) et protège directement l'argent.
    if uid and stripe_ref and _axonaut_invoice_exists(uid, stripe_ref):
        print(f"[Axonaut] Facture deja emise pour {stripe_ref} — creation ignoree")
        return
    if not company_id:
        print("[Axonaut] company_id manquant — facture non creee")
        return
    # `None` seulement, jamais `not amount_ttc` : avec un code promo à 100 %,
    # le montant encaissé vaut légitimement 0 € et le repli sur le tarif du
    # plan facturerait le prix fort une commande offerte.
    if amount_ttc is None:
        amount_ttc = _get_plan_price_ttc(plan_type)
        # Le tarif de repli est un TTC catalogue français : le taux lu sur
        # Stripe se rapportait à un AUTRE encaissement. On repasse en TVA_RATE.
        tax_rate_stripe, stripe_tax = None, False
        print(f"[Axonaut] montant absent → fallback Stripe price : {amount_ttc} € TTC")

    if stripe_tax and tax_rate_stripe is not None:
        # Stripe Tax actif : le taux est celui du pays du client — 0 % en
        # autoliquidation B2B intra-UE ou hors UE.
        tax_rate = tax_rate_stripe
        tax_origin = "Stripe Tax"
    else:
        # Stripe ne calcule pas la TVA : comportement historique, tout est
        # réputé français et le prix affiché est TTC.
        tax_rate = float(TVA_RATE)
        tax_origin = f"defaut {TVA_RATE} %"

    # Le HT se DÉDUIT du taux, jamais l'inverse : c'est ce qui garantit que le
    # taux imprimé sur la facture est un taux légal et que le TTC retombe au
    # centime sur le montant encaissé.
    price_ht = round(amount_ttc / (1 + tax_rate / 100.0), 2)

    # Axonaut recalcule le TTC à partir de `price` et `tax_rate`. Si l'arrondi
    # le fait diverger du montant réellement encaissé, le paiement enregistré
    # ne solde pas la facture et elle reste « partiellement payée ».
    rebuilt_ttc = round(price_ht * (1 + tax_rate / 100.0), 2)
    if abs(rebuilt_ttc - round(amount_ttc, 2)) > 0.01:
        print(f"[Axonaut] ⚠️ Ecart d'arrondi TVA : facture reconstituee "
              f"{rebuilt_ttc} € vs encaisse {round(amount_ttc, 2)} €")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"[Axonaut] Création facture — plan={plan_type} "
          f"{price_ht} € HT + {tax_rate} % TVA ({tax_origin}) "
          f"= {round(amount_ttc, 2)} € TTC company_id={company_id}")
    result = _axonaut("POST", "/invoices", {
        "company_id":     company_id,
        "reference":      (stripe_ref or "")[:30],
        "reference_date": today,
        "theme_id":       339036,   # MYSTROW
        "products": [{
            "name":     _plan_label(plan_type),
            "quantity": 1,
            "price":    price_ht,
            "tax_rate": tax_rate,
        }],
    })
    if not result:
        print("[Axonaut] Facture non creee (voir erreur ci-dessus)")
        return

    invoice_id = result.get("id")
    invoice_url = (result.get("pdf_url")
                   or result.get("public_link")
                   or result.get("link")
                   or f"https://axonaut.com/invoice/{invoice_id}")
    print(f"[Axonaut] Facture creee : id={invoice_id}")

    # Encaisse la facture avec le montant RÉELLEMENT prélevé par Stripe.
    # Avant : amount * 1,20 — on enregistrait 28,79 € alors que la banque
    # n'avait encaissé que 23,99 €, soit 4,80 € d'écart par facture.
    _axonaut_register_payment(invoice_id, round(amount_ttc, 2), stripe_ref)

    if uid:
        try:
            _get_db().collection("licenses").document(uid) \
                .collection("invoices").add({
                    "date":        today,
                    "amount_eur":  round(amount_ttc, 2),   # TTC payé (inchangé)
                    "amount_ht":   price_ht,
                    "amount_tax":  round(round(amount_ttc, 2) - price_ht, 2),
                    "tax_rate":    tax_rate,
                    "plan":        plan_type,
                    "invoice_url": invoice_url,
                    "axonaut_id":  invoice_id,
                    # Refs Stripe + numero lisible : sans elles, un
                    # remboursement ne saurait PAS quelle facture crediter.
                    "stripe_ref":     stripe_ref or "",
                    "axonaut_number": (result or {}).get("number") or "",
                    "type":           "invoice",
                })
            print(f"[Firebase] Facture stockée pour uid={uid}")
        except Exception as e:
            print(f"[Firebase] Erreur stockage facture : {e}")


def _axonaut_invoice_number(invoice_id: int) -> str:
    """Numero lisible d'une facture Axonaut (« F20260824-10888 »)."""
    if not invoice_id:
        return ""
    data = _axonaut("GET", f"/invoices/{invoice_id}")
    return (data or {}).get("number") or ""


def _find_invoice_to_credit(uid: str, refs: set) -> dict:
    """Retrouve, parmi les factures du client, celle que le remboursement solde.

    On matche d'abord sur la reference Stripe (`stripe_ref`) : c'est le seul
    lien certain entre un encaissement et sa facture. Les factures emises avant
    l'ajout de ce champ n'en ont pas — on retombe alors sur la plus recente, de
    loin le cas le plus frequent (on rembourse ce qu'on vient de prelever),
    mais on le DIT dans les logs : un avoir adosse a la mauvaise facture se
    rattrape a la main, encore faut-il savoir qu'il faut le rattraper.
    """
    docs = list(_get_db().collection("licenses").document(uid)
                .collection("invoices").get())
    rows = []
    for d in docs:
        data = d.to_dict() or {}
        if (data.get("type") or "invoice") != "invoice":
            continue          # ne jamais crediter un avoir
        rows.append(data)
        if refs and (data.get("stripe_ref") or "") in refs:
            return data
    if not rows:
        return {}
    rows.sort(key=lambda r: (r.get("date") or ""), reverse=True)
    print(f"[Avoir] Aucune facture ne porte {sorted(refs)} — repli sur la plus "
          f"recente ({rows[0].get('axonaut_number') or rows[0].get('axonaut_id')})")
    return rows[0]


def _axonaut_create_credit_note(
    company_id: int,
    plan_type: str,
    amount_ttc: float,
    tax_rate: float,
    origin_number: str = "",
    uid: str = "",
    stripe_ref: str = "",
) -> dict:
    """Emet un AVOIR Axonaut apres un remboursement Stripe.

    L'API v2 n'expose AUCUN endpoint « avoir ». Dans ce compte, un avoir est
    une facture dont les lignes portent une quantite NEGATIVE, avec la mention
    « Avoir sur facture : #<numero> » et un paiement negatif qui la solde :
    c'est exactement ce que produit le bouton « Creer un avoir » de l'interface
    (releve sur les avoirs deja au dossier). On reproduit ce schema a
    l'identique pour que l'export comptable reste homogene.

    `amount_ttc` est le montant REMBOURSE — donc du TTC, remboursement partiel
    compris. Le HT se deduit du taux, jamais l'inverse, pour que le TTC
    reconstitue retombe au centime sur ce que Stripe a rendu au client.
    """
    if not company_id:
        print("[Avoir] company_id manquant — avoir non cree")
        return {}
    if not amount_ttc:
        print("[Avoir] montant nul — avoir non cree")
        return {}

    tax_rate = float(TVA_RATE if tax_rate is None else tax_rate)
    price_ht = round(abs(amount_ttc) / (1 + tax_rate / 100.0), 2)
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mention  = (f"Avoir sur facture : #{origin_number}" if origin_number
                else "Avoir — remboursement Stripe")

    print(f"[Avoir] Creation — {price_ht} EUR HT + {tax_rate} % TVA "
          f"= -{round(abs(amount_ttc), 2)} EUR TTC "
          f"company_id={company_id} origine={origin_number or '?'}")

    result = _axonaut("POST", "/invoices", {
        "company_id":         company_id,
        "reference":          (stripe_ref or "")[:30],
        "reference_date":     today,
        "theme_id":           339036,   # MYSTROW
        "mandatory_mentions": mention,
        "products": [{
            "name":     _plan_label(plan_type),
            # La quantite est negative, PAS le prix : c'est la forme qu'ont les
            # avoirs deja au dossier, et celle que l'export compta attend.
            "quantity": -1,
            "price":    price_ht,
            "tax_rate": tax_rate,
        }],
    })
    if not result or not result.get("id"):
        print("[Avoir] Echec creation (voir erreur ci-dessus)")
        return {}

    credit_id  = result.get("id")
    credit_num = result.get("number") or _axonaut_invoice_number(credit_id)
    credit_url = (result.get("public_path") or result.get("pdf_url")
                  or result.get("customer_portal_url")
                  or f"https://axonaut.com/invoice/{credit_id}")
    print(f"[Avoir] Cree : id={credit_id} numero={credit_num}")

    # Paiement NEGATIF : sans lui l'avoir reste « a payer » et le solde du
    # client ne revient jamais a zero.
    _axonaut_register_payment(
        credit_id, -round(abs(amount_ttc), 2),
        (f"Annule #{origin_number}" if origin_number else "Remboursement Stripe"),
        nature=6,                      # Autre — ce n'est pas un encaissement CB
    )

    if uid:
        try:
            _get_db().collection("licenses").document(uid) \
                .collection("invoices").add({
                    "date":        today,
                    # Negatif : la page « Mon compte » liste l'avoir sous la
                    # facture d'origine, montant en moins. Le client voit ce
                    # qu'on lui a rendu sans avoir a le demander.
                    "amount_eur":  -round(abs(amount_ttc), 2),
                    "amount_ht":   -price_ht,
                    "amount_tax":  -round(round(abs(amount_ttc), 2) - price_ht, 2),
                    "tax_rate":    tax_rate,
                    "plan":        plan_type,
                    "invoice_url": credit_url,
                    "axonaut_id":  credit_id,
                    "axonaut_number": credit_num,
                    "stripe_ref":  stripe_ref or "",
                    "type":        "credit_note",
                    "origin_number": origin_number or "",
                })
        except Exception as e:
            print(f"[Avoir] Erreur stockage Firestore : {e}")

    return {"id": credit_id, "number": credit_num, "url": credit_url}


def _already_credited(uid: str, charge_id: str) -> float:
    """Somme des remboursements deja passes en avoir pour cette charge Stripe.

    Les avoirs en echec (`status == "error"`) ne comptent PAS : ils n'existent
    dans aucune compta, et le prochain evenement Stripe doit pouvoir les
    rattraper.
    """
    if not charge_id:
        return 0.0
    total = 0.0
    for d in (_get_db().collection("licenses").document(uid)
              .collection("refunds").get()):
        data = d.to_dict() or {}
        if data.get("stripe_charge_id") != charge_id:
            continue
        if data.get("status") == "error":
            continue
        total += float(data.get("amount_eur") or 0)
    return round(total, 2)


def _on_charge_refunded(charge: dict) -> None:
    """Remboursement Stripe — emet l'avoir Axonaut correspondant.

    Ne touche PAS a la licence : un remboursement suit presque toujours une
    annulation deja traitee par _on_subscription_deleted, et couper l'acces sur
    un simple geste commercial (remboursement partiel, dedommagement) serait
    une mauvaise surprise pour un client qui paie toujours.

    Idempotent par remboursement : Stripe peut rejouer l'evenement, et deux
    avoirs pour un seul remboursement, ca se repare a la main dans la compta.
    Chaque `re_...` traite laisse une trace dans licenses/{uid}/refunds.
    """
    customer_id = _id_of(charge.get("customer"))
    uid = _find_uid_by_customer(customer_id)
    if not uid:
        print(f"[charge.refunded] UID introuvable pour customer {customer_id} "
              f"— AVOIR A CREER A LA MAIN")
        return

    db = _get_db()

    refunds = ((charge.get("refunds") or {}).get("data")) or []
    if not refunds:
        # `refunds` est « expandable » : sur les versions recentes de l'API,
        # l'objet Charge du webhook ne la contient PLUS (c'est ce que dit la
        # doc quand elle renvoie vers refund.created « for information about
        # the refund »). Il ne reste que le CUMUL rembourse — on credite donc
        # la difference avec ce qui est deja passe en avoir sur cette charge :
        # sans ca, un 2e remboursement partiel serait avale par la cle
        # d'idempotence, et un rejeu du meme evenement ferait un doublon.
        cumul = (charge.get("amount_refunded") or 0) / 100.0
        delta = round(cumul - _already_credited(uid, charge.get("id", "")), 2)
        if delta <= 0:
            print(f"[charge.refunded] {charge.get('id','')} — {cumul} EUR deja "
                  f"credites, rien a faire")
            return
        # La cle porte le cumul : deux remboursements partiels successifs sur
        # la meme charge donnent deux cles differentes, un rejeu la meme.
        refunds = [{"id": f"chg_{charge.get('id', '')}_"
                          f"{charge.get('amount_refunded') or 0}",
                    "amount": int(round(delta * 100))}]

    lic = (db.collection("licenses").document(uid).get().to_dict()) or {}
    company_id = int(lic.get("axonaut_company_id") or 0)

    refs = {r for r in (_id_of(charge.get("invoice")),
                        _id_of(charge.get("payment_intent"))) if r}
    inv  = _find_invoice_to_credit(uid, refs)
    origin_number = (inv.get("axonaut_number")
                     or _axonaut_invoice_number(int(inv.get("axonaut_id") or 0)))

    for r in refunds:
        rid    = r.get("id") or ""
        amount = (r.get("amount") or 0) / 100.0
        if not rid or not amount:
            continue
        if (r.get("status") or "succeeded") != "succeeded":
            print(f"[charge.refunded] {rid} statut={r.get('status')} — ignore")
            continue

        marker = (db.collection("licenses").document(uid)
                    .collection("refunds").document(rid))
        seen = marker.get()
        if seen.exists and (seen.to_dict() or {}).get("status") != "error":
            print(f"[charge.refunded] {rid} deja traite — pas de second avoir")
            continue
        # Marqueur pose AVANT l'appel Axonaut : en cas de rejeu simultane,
        # mieux vaut un avoir manquant (hurlant dans les logs) qu'un doublon
        # dans la comptabilite.
        marker.set({
            "stripe_refund_id": rid,
            "stripe_charge_id": charge.get("id", ""),
            "amount_eur":       round(amount, 2),
            "date":             datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "created_utc":      time.time(),
            "status":           "pending",
        })

        credit = _axonaut_create_credit_note(
            company_id,
            inv.get("plan") or lic.get("plan_type") or "monthly",
            amount,
            inv.get("tax_rate"),
            origin_number=origin_number,
            uid=uid,
            stripe_ref=(_id_of(charge.get("payment_intent"))
                        or _id_of(charge.get("invoice")) or ""),
        )
        marker.set({
            "status":         "done" if credit else "error",
            "axonaut_id":     credit.get("id") or 0,
            "axonaut_number": credit.get("number") or "",
            "origin_number":  origin_number or "",
        }, merge=True)
        if credit:
            print(f"[charge.refunded] {rid} — avoir {credit.get('number')} "
                  f"de -{round(amount, 2)} EUR sur #{origin_number or '?'}")
        else:
            print(f"[charge.refunded] {rid} — AVOIR NON CREE, a faire a la main "
                  f"(client {lic.get('email', '')}, {round(amount, 2)} EUR)")


# ===========================================================================
# EMAIL HELPERS
# ===========================================================================

_EMAIL_BASE = """\
<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">
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
  <div class="ftr">{footer}</div>
</div></body></html>"""

_EMAIL_FOOTER = {
    "fr": ("MyStrow · Logiciel de contrôle lumière professionnel<br>"
           "Cet email est envoyé automatiquement, merci de ne pas y répondre."),
    "en": ("MyStrow · Professional lighting control software<br>"
           "This email is sent automatically, please do not reply."),
}


def _send_email_brevo_api(to: str, subject: str, html: str,
                          raise_on_error: bool = False) -> None:
    """Envoi par l'API HTTP de Brevo (`POST /v3/smtp/email`).

    C'est la voie a privilegier depuis une Cloud Function. Le relais SMTP de
    Brevo refuse l'authentification depuis une IP non declaree — `525 5.7.1
    Unauthorized IP address` — et une Cloud Function n'a pas d'IP de sortie
    fixe : la liste blanche est donc intenable. L'API, elle, n'authentifie que
    sur la cle.

    Elle rend en prime un `messageId`, tracable dans les journaux de Brevo. Sans
    lui, un mail non recu ne laissait aucune trace exploitable — c'est ce qui a
    rendu le cas gg@ouiensemble.eu indiagnosticable.
    """
    nom, adresse = parseaddr(_smtp_from())
    payload = json.dumps({
        "sender":      {"email": adresse, "name": nom or "MyStrow"},
        "to":          [{"email": to}],
        "subject":     subject,
        "htmlContent": html,
    }).encode("utf-8")
    req = urllib.request.Request("https://api.brevo.com/v3/smtp/email",
                                 data=payload, method="POST")
    req.add_header("api-key", _brevo_key())
    req.add_header("content-type", "application/json")
    req.add_header("accept", "application/json")
    # Sans User-Agent de navigateur, Cloudflare protege l'API de Brevo et repond
    # « Error 1010: Access denied » en 403 : ca ressemble a une cle invalide.
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; MyStrow/1.0; "
                                 "+https://mystrow.fr)")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            rep = json.loads(r.read() or b"{}")
        print(f"[Email] Envoyé → {to} ({subject}) id={rep.get('messageId','?')}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"[Email] Erreur Brevo → {to} : HTTP {e.code} {detail}")
        if raise_on_error:
            raise Exception(f"Brevo HTTP {e.code} : {detail}")
    except Exception as e:
        print(f"[Email] Erreur envoi → {to} : {e}")
        if raise_on_error:
            raise


def _send_email(to: str, subject: str, content: str,
                lang: str = "fr", raise_on_error: bool = False) -> None:
    html = _EMAIL_BASE.format(
        lang=lang,
        content=content,
        footer=_EMAIL_FOOTER.get(lang, _EMAIL_FOOTER["fr"]),
    )

    # Aiguillage explicite plutot que devine : `MAIL_TRANSPORT=brevo_api` bascule
    # sur l'API, tout le reste (defaut) garde le SMTP. Une variable a changer
    # pour revenir en arriere, sans redeploiement de code.
    if _cfg("MAIL_TRANSPORT", "smtp").strip().lower() == "brevo_api":
        _send_email_brevo_api(to, subject, html, raise_on_error)
        return

    host = _smtp_host()
    if not host:
        print(f"[Email] SMTP_HOST non configuré — email ignoré ({to})")
        return
    msg  = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = _smtp_from()
    msg["To"]      = to
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        user = _smtp_user()
        port = _smtp_port()
        ctx  = ssl.create_default_context()

        # Expéditeur d'ENVELOPPE = l'adresse de `SMTP_FROM`, jamais le login.
        # Chez Hostinger les deux étaient la même chaîne, l'amalgame passait
        # inaperçu. Chez Brevo le login est un identifiant technique
        # (…@smtp-brevo.com) qui n'est pas une adresse validée du domaine :
        # l'utiliser comme enveloppe casse l'alignement SPF/DMARC et fait
        # refuser le message par le relais lui-même.
        envelope = parseaddr(_smtp_from())[1] or user

        # 465 = TLS d'emblée (Hostinger) ; 587 = STARTTLS (port recommandé par
        # Brevo). Les deux marchent, on choisit sur le port pour que le
        # changement de prestataire reste un changement de `.env`.
        if port == 465:
            conn = smtplib.SMTP_SSL(host, port, context=ctx, timeout=20)
        else:
            conn = smtplib.SMTP(host, port, timeout=20)
        with conn as smtp:
            if port != 465:
                smtp.starttls(context=ctx)
            smtp.login(user, _smtp_password())
            smtp.sendmail(envelope, to, msg.as_string())
        print(f"[Email] Envoyé → {to} ({subject})")
    except Exception as e:
        print(f"[Email] Erreur envoi → {to} : {e}")
        if raise_on_error:
            raise


_DOWNLOAD_URL = "https://github.com/nprieto-ext/MAESTRO/releases/latest/download/MyStrow_Setup.exe"


def _email_welcome(email: str, password: str, expiry_ts: float,
                   plan_type: str, lang: str = "fr") -> None:
    plan = _plan_label(plan_type, lang)
    date = _fmt_date(expiry_ts, lang)
    if lang == "en":
        subject = "Welcome to MyStrow — Your login credentials"
        content = f"""
<h2>Welcome to MyStrow!</h2>
<p>Your <b>{plan}</b> license has just been activated.
Here are your credentials:</p>
<div class="box">
  ✉️ &nbsp;<b>Email:</b> {email}<br>
  🔑 &nbsp;<b>Temporary password:</b>
  <span style="font-family:monospace;font-size:14px;">{password}</span><br>
  📅 &nbsp;<b>License valid until:</b> {date}
</div>
<p>Launch MyStrow, click <b>Log in</b> and enter these credentials.</p>
<p>You can change your password from your account area.</p>
<a class="btn" href="{_DOWNLOAD_URL}">Download MyStrow</a>
"""
    else:
        subject = "Bienvenue sur MyStrow — Vos identifiants de connexion"
        content = f"""
<h2>Bienvenue sur MyStrow !</h2>
<p>Votre licence <b>{plan}</b> vient d'être activée.
Voici vos identifiants :</p>
<div class="box">
  ✉️ &nbsp;<b>Email :</b> {email}<br>
  🔑 &nbsp;<b>Mot de passe temporaire :</b>
  <span style="font-family:monospace;font-size:14px;">{password}</span><br>
  📅 &nbsp;<b>Licence valide jusqu'au :</b> {date}
</div>
<p>Lancez MyStrow, cliquez sur <b>Se connecter</b> et entrez ces identifiants.</p>
<p>Vous pourrez changer votre mot de passe depuis votre espace compte.</p>
<a class="btn" href="{_DOWNLOAD_URL}">Télécharger MyStrow</a>
"""
    _send_email(email, subject, content, lang=lang)


def _email_renewal(email: str, expiry_ts: float, lang: str = "fr") -> None:
    date = _fmt_date(expiry_ts, lang)
    if lang == "en":
        subject = "MyStrow — License renewed"
        content = f"""
<h2>Your license has been renewed</h2>
<p>Your payment was processed successfully. Your MyStrow license has been extended.</p>
<div class="box">📅 &nbsp;<b>New expiry date:</b> {date}</div>
<p>No action is required on your part. Keep using MyStrow as usual.</p>
"""
    else:
        subject = "MyStrow — Licence renouvelée"
        content = f"""
<h2>Votre licence a été renouvelée</h2>
<p>Votre paiement a bien été traité. Votre licence MyStrow est prolongée.</p>
<div class="box">📅 &nbsp;<b>Nouvelle date d'expiration :</b> {date}</div>
<p>Aucune action de votre part n'est requise. Continuez à utiliser MyStrow normalement.</p>
"""
    _send_email(email, subject, content, lang=lang)


def _email_cancelled(email: str, lang: str = "fr") -> None:
    if lang == "en":
        subject = "MyStrow — Subscription cancelled"
        content = """
<h2>Your subscription has been cancelled</h2>
<p>Your MyStrow subscription has been cancelled.</p>
<p>Your license stays active until the end of the current period,
after which access will be disabled automatically.</p>
<p>If you would like to resume a subscription, please contact us.</p>
"""
    else:
        subject = "MyStrow — Abonnement annulé"
        content = """
<h2>Votre abonnement a été annulé</h2>
<p>Votre abonnement MyStrow a bien été résilié.</p>
<p>Votre licence reste active jusqu'à la fin de la période en cours,
puis l'accès sera désactivé automatiquement.</p>
<p>Si vous souhaitez reprendre un abonnement, contactez-nous.</p>
"""
    _send_email(email, subject, content, lang=lang)


def _email_payment_failed(email: str, lang: str = "fr") -> None:
    if lang == "en":
        subject = "MyStrow — Payment failed"
        content = """
<h2>Payment problem</h2>
<p>We were unable to collect your MyStrow payment.</p>
<p>Please update your payment method to avoid any interruption of your license.</p>
<p>Stripe will automatically retry the payment over the coming days.</p>
"""
    else:
        subject = "MyStrow — Échec du paiement"
        content = """
<h2>Problème de paiement</h2>
<p>Nous n'avons pas pu encaisser votre paiement MyStrow.</p>
<p>Veuillez mettre à jour votre moyen de paiement pour éviter
l'interruption de votre licence.</p>
<p>Stripe effectuera automatiquement une nouvelle tentative dans les prochains jours.</p>
"""
    _send_email(email, subject, content, lang=lang)


# ===========================================================================
# EVENT HANDLERS
# ===========================================================================

def _on_checkout_completed(session: dict) -> None:
    """Premier paiement — crée le compte et active la licence."""
    cust_details = session.get("customer_details") or {}
    email       = cust_details.get("email") or session.get("customer_email", "")
    customer_id = session.get("customer", "")
    sub_id      = _id_of(session.get("subscription"))   # nu ou objet étendu
    # TTC réellement débité, APRÈS remise éventuelle. `amount_total` et non
    # `amount_subtotal` : le subtotal ignore les codes promo, on facturerait
    # alors plus cher que ce que la carte a payé.
    # `None` (clé absente) = montant inconnu → repli sur le tarif du plan ;
    # 0 = commande réellement gratuite, qu'il ne faut PAS remplacer par le
    # tarif plein (cf. _axonaut_create_invoice).
    _amt        = session.get("amount_total")
    amount_ttc  = (_amt / 100.0) if _amt is not None else None
    cust_name   = cust_details.get("name") or ""
    cust_address = cust_details.get("address") or {}
    # Taux de TVA réellement appliqué par Stripe + numéro de TVA du client,
    # quand la collecte est activée sur le Payment Link.
    tax_rate, stripe_tax = _stripe_tax_details(session)
    vat_number = _stripe_vat_number(session)

    # Langue des emails : locale du Checkout (langue navigateur), sinon pays.
    sess_locale = (session.get("locale") or "").strip()
    lang = _detect_lang(
        locales=[sess_locale] if sess_locale and sess_locale != "auto" else None,
        country=cust_address.get("country"),
    )

    # Détermine le plan depuis l'abonnement Stripe
    plan_type = "lifetime"
    if sub_id:
        try:
            sub       = _stripe_get(f"/subscriptions/{sub_id}")
            price_id  = sub["items"]["data"][0]["price"]["id"]
            plan_type = _get_plan_type(price_id)
            # Pour les abonnements, amount_total est parfois 0 sur la session ;
            # le vrai montant encaissé (remise déduite) est sur la 1re facture.
            if not amount_ttc and sub.get("latest_invoice"):
                inv = _stripe_get(f"/invoices/{sub['latest_invoice']}")
                amount_ttc = (inv.get("amount_paid") or inv.get("amount_due") or 0) / 100.0
                # Le taux doit venir de la MÊME source que le montant encaissé.
                tax_rate, stripe_tax = _stripe_tax_details(inv)
                vat_number = vat_number or _stripe_vat_number(inv)
        except Exception as e:
            print(f"[Handler] Impossible de lire le plan Stripe : {e}")

    # Crée / récupère le compte Firebase
    temp_pwd        = _generate_password()
    uid, is_new     = _get_or_create_user(email, temp_pwd)
    expiry_ts       = _compute_expiry(plan_type)

    _set_license(uid, email, plan_type, expiry_ts,
                 stripe_customer_id=customer_id,
                 stripe_subscription_id=sub_id or "",
                 lang=lang)

    # Stocke le mot de passe pour la récupération future
    if is_new:
        _get_db().collection("licenses").document(uid).set(
            {"password": temp_pwd}, merge=True
        )

    # Email
    if is_new:
        _email_welcome(email, temp_pwd, expiry_ts, plan_type, lang)
    else:
        _email_renewal(email, expiry_ts, lang)

    # Brevo — liste Clients (messages de service, jamais la newsletter)
    _brevo_sync_client(email, uid, plan_type, expiry_ts, lang, sub_id or "")

    # Axonaut
    company_id = _axonaut_get_or_create_company(email, cust_name, address=cust_address,
                                                uid=uid, vat_number=vat_number)
    _axonaut_create_invoice(company_id, plan_type, amount_ttc,
                            # Un Checkout d'abonnement n'a PAS de payment_intent :
                            # la ref utile est la 1re facture, celle que
                            # portera charge.refunded en cas de remboursement.
                            stripe_ref=(session.get("payment_intent")
                                        or _id_of(session.get("invoice")) or ""),
                            uid=uid, tax_rate_stripe=tax_rate, stripe_tax=stripe_tax)

    print(f"[checkout.completed] {email} — {plan_type} — expire {_fmt_date(expiry_ts)}")


def _id_of(value) -> str:
    """Un champ Stripe peut arriver en identifiant nu ou en objet étendu."""
    if isinstance(value, dict):
        return value.get("id") or ""
    return value or ""


def _subscription_id_from_invoice(invoice: dict) -> str:
    """Identifiant d'abonnement d'une facture, quel que soit son emplacement.

    Stripe a sorti `subscription` de la racine de l'objet invoice : il vit
    maintenant sous `parent.subscription_details.subscription`. Comme
    `_stripe_get` n'épingle aucune version d'API, la forme reçue dépend de la
    version configurée sur le endpoint webhook — on lit donc les deux, plus les
    lignes de facture en dernier recours.
    """
    sub = _id_of(invoice.get("subscription"))
    if sub:
        return sub

    details = (invoice.get("parent") or {}).get("subscription_details") or {}
    sub = _id_of(details.get("subscription"))
    if sub:
        return sub

    for line in (invoice.get("lines") or {}).get("data") or []:
        sub = _id_of(line.get("subscription"))
        if sub:
            return sub
        item = (line.get("parent") or {}).get("subscription_item_details") or {}
        sub = _id_of(item.get("subscription"))
        if sub:
            return sub
    return ""


def _known_plan_from_price(price_id: str) -> str:
    """Plan correspondant à un price Stripe, ou "" s'il est inconnu.

    `_get_plan_type` retombe sur "monthly" pour tout price non reconnu : c'est
    tenable au checkout, jamais en repli sur un renouvellement (un annuel se
    verrait rétrogradé sans le moindre signe).
    """
    if not price_id:
        return ""
    for plan, getter in (("monthly",  _stripe_price_monthly),
                         ("annual",   _stripe_price_annual),
                         ("lifetime", _stripe_price_lifetime)):
        try:
            if price_id == getter():
                return plan
        except Exception:
            continue
    return ""


def _price_id_from_invoice(invoice: dict) -> str:
    """Prix facturé, lu sur la 1re ligne (ancien `price`, nouveau `pricing`)."""
    for line in (invoice.get("lines") or {}).get("data") or []:
        price = _id_of(line.get("price"))
        if price:
            return price
        details = (line.get("pricing") or {}).get("price_details") or {}
        price = _id_of(details.get("price"))
        if price:
            return price
    return ""


def _on_invoice_paid(invoice: dict) -> None:
    """Renouvellement mensuel / annuel."""
    # On ignore la 1ère facture (déjà gérée par checkout.session.completed)
    if invoice.get("billing_reason") == "subscription_create":
        return

    customer_id = invoice.get("customer", "")
    sub_id      = _subscription_id_from_invoice(invoice)
    email       = invoice.get("customer_email", "")
    # TTC encaissé, remise déduite (amount_paid est toujours net de promo).
    _amt        = invoice.get("amount_paid")
    amount_ttc  = (_amt / 100.0) if _amt is not None else None
    stripe_ref  = invoice.get("id", "")
    cust_name   = invoice.get("customer_name") or ""
    cust_address = invoice.get("customer_address") or {}
    tax_rate, stripe_tax = _stripe_tax_details(invoice)
    vat_number = _stripe_vat_number(invoice)

    uid = _find_uid_by_customer(customer_id)
    if not uid:
        print(f"[invoice.paid] UID introuvable pour customer {customer_id}")
        return

    # Plan facturé. On ne retombe JAMAIS en silence sur "monthly" : un annuel
    # renouvelé s'en trouverait rétrogradé, et _compute_expiry lui donnerait
    # 31 jours d'accès au lieu de 366 — client payant coupé au bout d'un mois.
    # (Dégât déjà constaté : cf. fix_annual_licenses.py.)
    plan_type = ""
    if sub_id:
        try:
            sub       = _stripe_get(f"/subscriptions/{sub_id}")
            price_id  = sub["items"]["data"][0]["price"]["id"]
            plan_type = _known_plan_from_price(price_id)
        except Exception as e:
            print(f"[invoice.paid] abonnement {sub_id} illisible : {e}")
    else:
        print("[invoice.paid] aucun subscription_id dans la facture "
              f"{invoice.get('id', '?')} — repli sur la ligne de facture")

    if not plan_type:
        plan_type = _known_plan_from_price(_price_id_from_invoice(invoice))
    if not plan_type:
        # Dernier recours : le plan déjà enregistré pour ce client.
        _doc = _get_db().collection("licenses").document(uid).get()
        plan_type = ((_doc.to_dict() or {}).get("plan_type") or "") if _doc.exists else ""
    if not plan_type:
        plan_type = "monthly"
        print(f"[invoice.paid] plan indéterminable pour {email} — defaut 'monthly'")

    lang      = _lang_for_uid(uid)
    expiry_ts = _compute_expiry(plan_type)
    _set_license(uid, email, plan_type, expiry_ts,
                 stripe_customer_id=customer_id,
                 stripe_subscription_id=sub_id,
                 lang=lang)

    _email_renewal(email, expiry_ts, lang)

    # Brevo — la nouvelle date d'expiration doit suivre, sinon la relance
    # partirait sur une echeance deja repoussee.
    _brevo_sync_client(email, uid, plan_type, expiry_ts, lang, sub_id or "")

    company_id = _axonaut_get_or_create_company(email, cust_name, address=cust_address,
                                                uid=uid, vat_number=vat_number)
    _axonaut_create_invoice(company_id, plan_type, amount_ttc, stripe_ref=stripe_ref,
                            uid=uid, tax_rate_stripe=tax_rate, stripe_tax=stripe_tax)

    print(f"[invoice.paid] {email} — expire {_fmt_date(expiry_ts)}")


def _on_subscription_deleted(subscription: dict) -> None:
    """Abonnement annulé — révoque la licence."""
    customer_id = subscription.get("customer", "")
    uid         = _find_uid_by_customer(customer_id)
    if not uid:
        print(f"[subscription.deleted] UID introuvable pour customer {customer_id}")
        return

    lang = _lang_for_uid(uid)
    _revoke_license(uid)

    email = subscription.get("customer_email", "")
    if not email:
        try:
            email = auth.get_user(uid).email
        except Exception:
            pass
    if email:
        _email_cancelled(email, lang)

    print(f"[subscription.deleted] uid={uid} — licence révoquée")


def _on_payment_failed(invoice: dict) -> None:
    """Échec de paiement — email + période de grâce.

    On ne coupe pas la licence tout de suite : Stripe va relancer le paiement
    et le client peut mettre sa carte à jour. La licence reste active encore
    _GRACE_DAYS jours. Si Stripe finit par annuler / passer en 'unpaid',
    elle sera révoquée par _on_subscription_deleted / _on_subscription_updated.

    On ignore l'échec de la 1ère facture (billing_reason == 'subscription_create') :
    c'est une inscription qui n'a jamais abouti, donc aucune licence n'existe —
    inutile d'envoyer un email « paiement échoué » à un non-client.
    """
    if invoice.get("billing_reason") == "subscription_create":
        print("[invoice.payment_failed] 1er paiement échoué (inscription non aboutie) — ignoré")
        return

    customer_id = invoice.get("customer", "")
    email       = invoice.get("customer_email", "")

    uid  = _find_uid_by_customer(customer_id)
    lang = _lang_for_uid(uid)
    if uid:
        _apply_payment_grace(uid)
        if not email:
            try:
                email = auth.get_user(uid).email
            except Exception:
                pass

    if email:
        _email_payment_failed(email, lang)
    print(f"[invoice.payment_failed] {email} — grâce {_GRACE_DAYS}j (uid={uid})")


def _on_subscription_updated(subscription: dict) -> None:
    """Abonnement modifié — révoque si Stripe l'a passé en 'unpaid' ou 'canceled'.

    Filet de sécurité : selon les réglages de relance Stripe, un abonnement
    impayé peut être marqué 'unpaid' (ou 'canceled') SANS déclencher
    customer.subscription.deleted. Sans ce handler, la licence resterait
    active indéfiniment. On ignore tous les autres changements de statut.
    """
    status = subscription.get("status", "")
    if status not in ("unpaid", "canceled"):
        return

    customer_id = subscription.get("customer", "")
    uid         = _find_uid_by_customer(customer_id)
    if not uid:
        print(f"[subscription.updated] UID introuvable pour customer {customer_id} (status={status})")
        return

    lang = _lang_for_uid(uid)
    _revoke_license(uid)

    email = subscription.get("customer_email", "")
    if not email:
        try:
            email = auth.get_user(uid).email
        except Exception:
            pass
    if email:
        _email_cancelled(email, lang)

    print(f"[subscription.updated] uid={uid} status={status} — licence révoquée")


# ===========================================================================
# CLOUD FUNCTION: send_reset_email (reset mot de passe custom)
# ===========================================================================

@https_fn.on_request(max_instances=5)
def send_reset_email(req: https_fn.Request) -> https_fn.Response:
    """
    Endpoint HTTPS : POST /send_reset_email
    Body: {"email": "user@example.com"}
    Renvoie au client les identifiants stockés (email + mot de passe).

    ⚠️ CORS obligatoire : l'espace client du site (compte.html) appelle cet
    endpoint depuis le navigateur. Sans les en-têtes, le préflight OPTIONS
    tombait sur le 405 « Method not allowed » et l'appel n'atteignait jamais la
    fonction — c'est pour ça que le site est resté sur le lien Firebase natif.
    """
    _H = {**_CORS_HEADERS, "Content-Type": "application/json"}

    if req.method == "OPTIONS":
        return _cors_preflight()
    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405,
                                 headers=_CORS_HEADERS)

    try:
        body  = json.loads(req.get_data() or b"{}")
        email = (body.get("email") or "").strip().lower()
    except Exception:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "JSON invalide"}),
            status=400, headers=_H,
        )

    if not email or "@" not in email:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Email invalide"}),
            status=400, headers=_H,
        )

    try:
        db = _get_db()

        # Vérifie que l'utilisateur existe. On répond `ok` sans rien envoyer :
        # ne jamais révéler si une adresse a un compte (anti-énumération).
        try:
            user = auth.get_user_by_email(email)
        except auth.UserNotFoundError:
            return https_fn.Response(
                json.dumps({"ok": True}),
                status=200, headers=_H,
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
                status=200, headers=_H,
            )

        # ── Récupère le mot de passe stocké, ou en génère un nouveau ─────
        pwd_to_send = lic_data.get("password")
        if not pwd_to_send:
            pwd_to_send = _generate_password(12)
            auth.update_user(uid, password=pwd_to_send)
            lic_ref.set({"password": pwd_to_send}, merge=True)

        # ── Envoi email ───────────────────────────────────────────────────
        lang = lic_data.get("lang") or "fr"
        pwd_box = f"""
  <div style="margin-bottom:10px;">
    ✉️ &nbsp;<b>{{email_label}}</b> <span style="color:#aaa;">{email}</span>
  </div>
  <div>
    🔑 &nbsp;<b>{{pwd_label}}</b><br>
    <span style="display:inline-block;margin-top:8px;padding:10px 20px;background:#0d0d0d;
      border:1px solid rgba(0,212,255,0.35);border-radius:8px;
      font-family:Consolas,monospace;font-size:20px;letter-spacing:5px;color:#00d4ff;
      box-shadow:0 0 12px rgba(0,212,255,0.15);">{pwd_to_send}</span>
  </div>"""
        if lang == "en":
            subject = "MyStrow — Your login credentials"
            content = f"""
<h2 style="color:#fff;margin-top:0;">Your MyStrow credentials</h2>
<p>Here are your credentials to access your MyStrow license:</p>
<div class="box">{pwd_box.format(email_label="Email:", pwd_label="Password:")}
</div>
<p style="margin-top:16px;">
  Open <b>MyStrow</b>, click <b>Log in</b> and enter these credentials.
</p>
<p style="color:#555;font-size:11px;border-top:1px solid #2a2a2a;padding-top:12px;margin-top:12px;">
  If you did not request this, please contact us: nicolas@mystrow.fr
</p>
"""
        else:
            subject = "MyStrow — Vos identifiants de connexion"
            content = f"""
<h2 style="color:#fff;margin-top:0;">Vos identifiants MyStrow</h2>
<p>Voici vos identifiants pour accéder à votre licence MyStrow :</p>
<div class="box">{pwd_box.format(email_label="Email :", pwd_label="Mot de passe :")}
</div>
<p style="margin-top:16px;">
  Ouvrez <b>MyStrow</b>, cliquez sur <b>Se connecter</b> et entrez ces identifiants.
</p>
<p style="color:#555;font-size:11px;border-top:1px solid #2a2a2a;padding-top:12px;margin-top:12px;">
  Si vous n'avez pas fait cette demande, contactez-nous : nicolas@mystrow.fr
</p>
"""
        _send_email(email, subject, content, lang=lang, raise_on_error=True)

        # Enregistre l'horodatage du reset
        resets.append(now)
        lic_ref.set({"reset_timestamps": resets}, merge=True)

        # Réponse volontairement IDENTIQUE à celle du compte inconnu : y
        # ajouter un « sent: true » donnerait un oracle pour savoir quelles
        # adresses ont un compte MyStrow.
        print(f"[send_reset_email] Email envoyé → {email}")
        return https_fn.Response(
            json.dumps({"ok": True}),
            status=200, headers=_H,
        )

    except Exception as e:
        # `_send_email` est appelé avec raise_on_error=True : un rejet SMTP
        # (destinataire qui bloque, boîte pleine, expéditeur en liste noire)
        # arrive ICI. On le remonte à l'appelant au lieu de le taire — c'est
        # exactement le cas qui laissait un client sans identifiants ET sans
        # aucun message d'erreur.
        print(f"[send_reset_email] Erreur : {e}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": str(e)}),
            status=500, headers=_H,
        )


# ===========================================================================
# CLOUD FUNCTION ENTRY POINT
# ===========================================================================

_HANDLERS = {
    "checkout.session.completed":    _on_checkout_completed,
    "invoice.payment_succeeded":     _on_invoice_paid,
    "customer.subscription.deleted": _on_subscription_deleted,
    "customer.subscription.updated": _on_subscription_updated,
    "invoice.payment_failed":        _on_payment_failed,
    "charge.refunded":               _on_charge_refunded,
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

            # Tracabilite juridique des profils issus d'une contribution
            # utilisateur : licence d'origine, mention d'attribution a afficher
            # et identifiant du contributeur. Champs optionnels : les imports
            # admin classiques ne les portent pas.
            for _k in ("license", "attribution", "contributor_uid",
                       "contributed_by", "declared_source"):
                if fx.get(_k):
                    doc_data[_k] = fx[_k]

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
# CLOUD FUNCTION: fixture_submit (contribution utilisateur -> moderation)
# ===========================================================================

# Provenances redistribuables, avec la licence imposee cote serveur.
# Toute source absente de ce tableau est refusee : fichier constructeur,
# GDTF Share ou origine inconnue restent en import local chez l'utilisateur.
_SHAREABLE_SOURCES = {
    "perso":   {"license": "MyStrow-Community", "attribution": ""},
    "ofl":     {"license": "CC0-1.0",     "attribution": "Open Fixture Library — CC0 1.0"},
    "qlcplus": {"license": "Apache-2.0",  "attribution": "QLC+ Fixture Library — Apache 2.0"},
}

# Quota anti-dump : nombre maximum de fixtures proposees par compte et par jour.
# Ecarte le scenario d'extraction substantielle d'une base tierce, ou
# l'accumulation d'extractions non substantielles finit par recopier la source.
_DAILY_SUBMIT_QUOTA = 20

# Nombre maximum de fixtures dans une seule requete.
_MAX_ITEMS_PER_CALL = 20


def _fixture_fingerprint(fixture: dict) -> str:
    """
    Empreinte deterministe (fabricant + nom + structure des canaux).
    Doit rester identique a fixture_share.fixture_fingerprint cote application.
    """
    mfr  = str(fixture.get("manufacturer", "")).strip().lower()
    name = str(fixture.get("name", "")).strip().lower()
    profile = fixture.get("profile") or []
    if not profile:
        modes = fixture.get("modes") or []
        if modes and isinstance(modes[0], dict):
            profile = modes[0].get("profile") or []
    chans = "|".join(str(c) for c in profile)
    key = f"{mfr}::{name}::{chans}".encode("utf-8", "replace")
    return hashlib.sha1(key).hexdigest()[:32]


def _consume_submit_quota(db, uid: str, wanted: int) -> int:
    """
    Reserve *wanted* unites du quota journalier de l'utilisateur.
    Retourne le nombre d'unites reellement accordees (0 si le quota est epuise).

    Implemente avec un compteur par utilisateur dans une transaction plutot
    qu'un comptage de documents : pas d'index composite a creer, une seule
    lecture, et pas de course entre deux envois simultanes.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref   = db.collection("fixture_quota").document(uid)

    @firestore.transactional
    def _txn(transaction):
        snap = ref.get(transaction=transaction)
        data = snap.to_dict() if snap.exists else {}
        used = int(data.get("count", 0) or 0) if data.get("day") == today else 0
        granted = max(0, min(wanted, _DAILY_SUBMIT_QUOTA - used))
        if granted:
            transaction.set(ref, {
                "day":       today,
                "count":     used + granted,
                "updatedAt": time.time(),
            }, merge=True)
        return granted

    return _txn(db.transaction())


def _refund_submit_quota(db, uid: str, amount: int) -> None:
    """
    Rend au compteur journalier les unites reservees mais non utilisees
    (doublons ecartes, entrees invalides). Sans cela, proposer 10 fois la meme
    fixture consommerait le quota de la journee sans rien deposer.
    """
    if amount <= 0:
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref   = db.collection("fixture_quota").document(uid)

    @firestore.transactional
    def _txn(transaction):
        snap = ref.get(transaction=transaction)
        data = snap.to_dict() if snap.exists else {}
        if data.get("day") != today:
            return
        used = int(data.get("count", 0) or 0)
        transaction.set(ref, {
            "day":       today,
            "count":     max(0, used - amount),
            "updatedAt": time.time(),
        }, merge=True)

    _txn(db.transaction())


@https_fn.on_request(max_instances=5, timeout_sec=120)
def fixture_submit(req: https_fn.Request) -> https_fn.Response:
    """
    Endpoint HTTPS : POST /fixture_submit

    Recoit des fixtures proposees par un utilisateur et les depose dans
    `fixture_submissions` avec le statut "pending". Rien n'est publie ici :
    seule la validation d'un administrateur ecrit dans `gdtf_fixtures`.

    Trois refus possibles, tous rejoues cote serveur car les controles de
    l'application cliente sont contournables :
      - provenance non redistribuable  -> 403
      - attestation non cochee         -> 400
      - quota journalier epuise        -> 429

    Body : {"items": [{"fingerprint": str, "fixture": {...}}],
            "source": str, "attestation": true}
    """
    _get_db()

    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Connectez-vous pour proposer une fixture."}),
            status=403, headers={"Content-Type": "application/json"})
    try:
        decoded = auth.verify_id_token(auth_header[len("Bearer "):])
        uid   = decoded.get("uid", "")
        email = decoded.get("email", "")
    except Exception as e:
        print(f"[fixture_submit] Token invalide : {e}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Session expiree — reconnectez-vous."}),
            status=403, headers={"Content-Type": "application/json"})

    try:
        body = json.loads(req.get_data() or b"{}")
    except Exception as e:
        return https_fn.Response(
            json.dumps({"ok": False, "error": f"JSON invalide : {e}"}),
            status=400, headers={"Content-Type": "application/json"})

    items  = body.get("items") or []
    source = str(body.get("source", "")).strip()

    # Garde-fou 2 : attestation explicite du contributeur.
    if body.get("attestation") is not True:
        return https_fn.Response(
            json.dumps({"ok": False,
                        "error": "Attestation de droit de partage manquante."}),
            status=400, headers={"Content-Type": "application/json"})

    # Garde-fou 3 : filtrage par licence de la source declaree.
    policy = _SHAREABLE_SOURCES.get(source)
    if policy is None:
        return https_fn.Response(
            json.dumps({"ok": False,
                        "error": "Cette provenance n'est pas redistribuable : "
                                 "la fixture reste dans votre bibliotheque locale."}),
            status=403, headers={"Content-Type": "application/json"})

    if not isinstance(items, list) or not items:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Aucune fixture dans la requete"}),
            status=400, headers={"Content-Type": "application/json"})
    if len(items) > _MAX_ITEMS_PER_CALL:
        return https_fn.Response(
            json.dumps({"ok": False,
                        "error": f"Au plus {_MAX_ITEMS_PER_CALL} fixtures par envoi."}),
            status=400, headers={"Content-Type": "application/json"})

    try:
        db = _get_db()

        # Garde-fou 4 : quota journalier, reserve avant toute ecriture.
        granted = _consume_submit_quota(db, uid, len(items))
        if granted == 0:
            return https_fn.Response(
                json.dumps({"ok": False, "quota_left": 0,
                            "error": f"Quota atteint : {_DAILY_SUBMIT_QUOTA} fixtures "
                                     f"par jour. Reessayez demain."}),
                status=429, headers={"Content-Type": "application/json"})

        submitted = 0
        skipped   = 0
        errors    = []
        now       = time.time()

        for item in items[:granted]:
            fixture = (item or {}).get("fixture") or {}
            name    = str(fixture.get("name", "")).strip()
            if not name:
                errors.append("Fixture sans nom ignoree")
                skipped += 1
                continue

            fingerprint = str((item or {}).get("fingerprint", "")).strip()
            if not fingerprint:
                fingerprint = _fixture_fingerprint(fixture)

            ref  = db.collection("fixture_submissions").document(fingerprint)
            snap = ref.get()
            if snap.exists:
                existing = snap.to_dict() or {}
                # Deja en file d'attente, deja publiee, ou deja refusee : ne pas
                # ecraser la decision (ni le contributeur d'origine).
                if existing.get("status") in ("pending", "approved", "rejected"):
                    skipped += 1
                    continue

            ref.set({
                "status":          "pending",
                "fingerprint":     fingerprint,
                "name":            name,
                "manufacturer":    str(fixture.get("manufacturer", "")).strip(),
                "fixture_type":    fixture.get("fixture_type", "PAR LED"),
                "modes":           fixture.get("modes", []),
                "declared_source": source,
                "license":         policy["license"],
                "attribution":     policy["attribution"],
                "attestation":     True,
                "contributor_uid": uid,
                "contributed_by":  email,
                "created_at":      now,
                "fixture":         fixture,
            })
            submitted += 1

        # Rendre le quota non consomme (doublons ecartes, entrees invalides).
        if skipped:
            try:
                _refund_submit_quota(db, uid, skipped)
            except Exception as e:
                print(f"[fixture_submit] restitution quota impossible : {e}")

        # Fixtures laissees de cote faute de quota suffisant sur cet envoi.
        deferred = max(0, len(items) - granted)
        if deferred:
            errors.append(f"{deferred} fixture(s) non envoyee(s) : quota journalier atteint.")

        try:
            snap  = db.collection("fixture_quota").document(uid).get()
            data  = snap.to_dict() if snap.exists else {}
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            used  = int(data.get("count", 0) or 0) if data.get("day") == today else 0
            quota_left = max(0, _DAILY_SUBMIT_QUOTA - used)
        except Exception:
            quota_left = 0

        print(f"[fixture_submit] {email} : {submitted} en attente, {skipped} ignoree(s), "
              f"{deferred} differee(s)")
        return https_fn.Response(
            json.dumps({"ok": True, "submitted": submitted, "skipped": skipped,
                        "deferred": deferred, "quota_left": quota_left,
                        "errors": errors}),
            status=200, headers={"Content-Type": "application/json"})

    except Exception as exc:
        print(f"[fixture_submit] ERREUR: {exc}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": str(exc)}),
            status=500, headers={"Content-Type": "application/json"})


# ===========================================================================
# CLOUD FUNCTION: controller_submit (profil de controleur MIDI -> moderation)
# ===========================================================================

# Quota journalier. Bien plus bas que celui des fixtures : un regisseur possede
# deux ou trois controleurs, pas vingt. Un compte qui en propose dix dans la
# journee n'alimente pas une bibliotheque, il la pollue.
_DAILY_CONTROLLER_QUOTA = 5

# Un profil 8x8 complet pese ~6 Ko. Au-dela de 64 Ko ce n'est plus un mapping.
_MAX_PROFILE_BYTES = 64 * 1024

_JSON = {"Content-Type": "application/json"}


def _controller_fingerprint(profile: dict) -> str:
    """
    Empreinte deterministe d'un MODELE de controleur : mots-cles de detection
    normalises + geometrie. Aveugle au contenu du mapping, pour que deux
    mappings differents du meme appareil entrent en collision.

    Doit rester identique a controller_share.controller_fingerprint cote app.
    """
    kws = sorted({
        str(k).strip().upper()
        for k in (profile.get("keywords") or [])
        if str(k).strip()
    })

    def _int(field):
        try:
            return int(profile.get(field) or 0)
        except (TypeError, ValueError):
            return 0

    geom = "{}x{}:{}:{}".format(
        _int("grid_rows"), _int("grid_cols"),
        _int("fader_count"), _int("effect_count"),
    )
    key = ("|".join(kws) + "::" + geom).encode("utf-8", "replace")
    return hashlib.sha1(key).hexdigest()[:32]


def _validate_controller_profile(data) -> tuple:
    """
    (ok, raison) — portage de controller_profile.validate_profile.

    Un profil accepte ici sera installe chez d'autres utilisateurs : un JSON
    malforme ne casserait pas l'installation mais la connexion du controleur,
    bien plus tard et sans rapport visible avec le fichier fautif.
    """
    if not isinstance(data, dict):
        return False, "le profil n'est pas un objet JSON"
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return False, "champ « name » absent ou vide"
    if len(name) > 80:
        return False, "nom de profil trop long"
    keywords = data.get("keywords", [])
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        return False, "champ « keywords » invalide (liste de textes attendue)"
    if not keywords or not any(k.strip() for k in keywords):
        return False, "aucun mot-cle de detection : le controleur ne serait jamais reconnu"
    for section, field in (("pad_map", "note"), ("mute_map", "note"),
                           ("effect_map", "note"), ("fader_map", "cc")):
        entries = data.get(section, {})
        if not isinstance(entries, dict):
            return False, f"section « {section} » invalide"
        for key, entry in entries.items():
            if not isinstance(entry, dict) or not isinstance(entry.get(field), int):
                return False, f"section « {section} », entree « {key} » : « {field} » manquant"
            channel = entry.get("channel", 0)
            if not isinstance(channel, int) or not 0 <= channel <= 15:
                return False, f"section « {section} », entree « {key} » : canal hors 0-15"
    if not any(data.get(s) for s in ("pad_map", "mute_map", "effect_map", "fader_map")):
        return False, "profil vide : aucun pad, fader ni bouton mappe"
    return True, ""


def _consume_controller_quota(db, uid: str) -> bool:
    """Reserve une unite du quota journalier. False si le quota est epuise."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref   = db.collection("controller_quota").document(uid)

    @firestore.transactional
    def _txn(transaction):
        snap = ref.get(transaction=transaction)
        data = snap.to_dict() if snap.exists else {}
        used = int(data.get("count", 0) or 0) if data.get("day") == today else 0
        if used >= _DAILY_CONTROLLER_QUOTA:
            return False
        transaction.set(ref, {
            "day":       today,
            "count":     used + 1,
            "updatedAt": time.time(),
        }, merge=True)
        return True

    return _txn(db.transaction())


def _refund_controller_quota(db, uid: str) -> None:
    """Rend l'unite reservee quand rien n'a ete depose (doublon)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ref   = db.collection("controller_quota").document(uid)

    @firestore.transactional
    def _txn(transaction):
        snap = ref.get(transaction=transaction)
        data = snap.to_dict() if snap.exists else {}
        if data.get("day") != today:
            return
        used = int(data.get("count", 0) or 0)
        transaction.set(ref, {
            "day":       today,
            "count":     max(0, used - 1),
            "updatedAt": time.time(),
        }, merge=True)

    _txn(db.transaction())


@https_fn.on_request(max_instances=5, timeout_sec=60)
def controller_submit(req: https_fn.Request) -> https_fn.Response:
    """
    Endpoint HTTPS : POST /controller_submit

    Recoit un profil de controleur MIDI mappe par un utilisateur et le depose
    dans `controller_submissions` au statut "pending". Rien n'est publie ici :
    seule la validation d'un administrateur ecrit dans `controller_profiles`.

    Remplace l'ancien envoi par mailto:, qui tronquait le profil au-dela de
    ~2000 caracteres d'URL sous Windows.

    Body : {"fingerprint": str, "profile": {...}}
    Reponse : {"ok", "status": "pending"|"duplicate", "quota_left"}
    """
    _get_db()

    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return https_fn.Response(
            json.dumps({"ok": False,
                        "error": "Connectez-vous pour partager un profil."}),
            status=403, headers=_JSON)
    try:
        decoded = auth.verify_id_token(auth_header[len("Bearer "):])
        uid   = decoded.get("uid", "")
        email = decoded.get("email", "")
    except Exception as e:
        print(f"[controller_submit] Token invalide : {e}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Session expiree - reconnectez-vous."}),
            status=403, headers=_JSON)

    raw = req.get_data() or b"{}"
    if len(raw) > _MAX_PROFILE_BYTES * 2:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Profil trop volumineux."}),
            status=413, headers=_JSON)
    try:
        body = json.loads(raw)
    except Exception as e:
        return https_fn.Response(
            json.dumps({"ok": False, "error": f"JSON invalide : {e}"}),
            status=400, headers=_JSON)

    profile = body.get("profile") or {}
    ok, reason = _validate_controller_profile(profile)
    if not ok:
        return https_fn.Response(
            json.dumps({"ok": False, "error": f"Profil refuse : {reason}"}),
            status=400, headers=_JSON)

    profile_json = json.dumps(profile, ensure_ascii=False)
    if len(profile_json.encode("utf-8")) > _MAX_PROFILE_BYTES:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Profil trop volumineux."}),
            status=413, headers=_JSON)

    # L'empreinte est TOUJOURS recalculee : celle du client ne sert qu'a lui
    # permettre d'anticiper un doublon, elle ne decide pas de l'ID du document.
    fingerprint = _controller_fingerprint(profile)

    try:
        db = _get_db()

        if not _consume_controller_quota(db, uid):
            return https_fn.Response(
                json.dumps({"ok": False, "quota_left": 0,
                            "error": f"Quota atteint : {_DAILY_CONTROLLER_QUOTA} profils "
                                     f"par jour. Reessayez demain."}),
                status=429, headers=_JSON)

        ref  = db.collection("controller_submissions").document(fingerprint)
        snap = ref.get()
        if snap.exists and (snap.to_dict() or {}).get("status") in (
                "pending", "approved", "rejected"):
            # Ce modele est deja couvert : ne pas ecraser la decision prise, ni
            # le contributeur d'origine. Une entree canonique par modele.
            _refund_controller_quota(db, uid)
            print(f"[controller_submit] {email} : doublon {fingerprint}")
            return https_fn.Response(
                json.dumps({"ok": True, "status": "duplicate"}),
                status=200, headers=_JSON)

        ref.set({
            "status":          "pending",
            "fingerprint":     fingerprint,
            "name":            str(profile.get("name", "")).strip(),
            "keywords":        [str(k).strip() for k in profile.get("keywords", []) if str(k).strip()],
            "grid_rows":       int(profile.get("grid_rows") or 0),
            "grid_cols":       int(profile.get("grid_cols") or 0),
            "fader_count":     int(profile.get("fader_count") or 0),
            "effect_count":    int(profile.get("effect_count") or 0),
            "pad_count":       len(profile.get("pad_map") or {}),
            "profile_json":    profile_json,
            "contributor_uid": uid,
            "contributed_by":  email,
            "created_at":      time.time(),
        })
        print(f"[controller_submit] {email} : {profile.get('name')} en attente ({fingerprint})")

        try:
            snap_q = db.collection("controller_quota").document(uid).get()
            data_q = snap_q.to_dict() if snap_q.exists else {}
            today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            used   = int(data_q.get("count", 0) or 0) if data_q.get("day") == today else 0
            quota_left = max(0, _DAILY_CONTROLLER_QUOTA - used)
        except Exception:
            quota_left = 0

        return https_fn.Response(
            json.dumps({"ok": True, "status": "pending", "quota_left": quota_left}),
            status=200, headers=_JSON)

    except Exception as exc:
        print(f"[controller_submit] ERREUR: {exc}")
        return https_fn.Response(
            json.dumps({"ok": False, "error": str(exc)}),
            status=500, headers=_JSON)


# ===========================================================================
# STRIPE CLOUD FUNCTION ENTRY POINT
# ===========================================================================

def _claim_stripe_event(event_id: str, event_type: str) -> bool:
    """Réserve un événement Stripe. Retourne False si on l'a déjà traité.

    Stripe REJOUE un événement quand l'endpoint ne répond pas 200 assez vite,
    et `_on_checkout_completed` enchaîne compte Firebase + email SMTP + Brevo +
    trois appels Axonaut (dont un `GET /companies` qui rapatrie toute la base) :
    dépasser le délai n'a rien d'exceptionnel. Sans verrou, le rejeu refait
    TOUT — deux sociétés Axonaut et deux factures pour un seul encaissement.
    Constaté 4 fois entre mai et août 2026 : ANTHONY MACOINE (14/05), billoux
    (02/06), SCHMIT Amaury (20/06), martial bulard (24/08, rattrapé par un
    avoir).

    `create()` échoue si le document existe déjà, et cet échec est atomique
    côté Firestore : deux exécutions simultanées ne peuvent pas passer toutes
    les deux. Si Firestore est indisponible on laisse passer — un doublon se
    rattrape avec un avoir, un paiement jamais traité laisse un client sans
    licence.
    """
    try:
        _get_db().collection("stripe_events").document(event_id).create({
            "type":          event_type,
            "processed_utc": time.time(),
        })
        return True
    except Conflict:
        return False
    except Exception as e:
        print(f"[Webhook] Verrou anti-rejeu indisponible ({e}) — traitement poursuivi")
        return True


@https_fn.on_request(max_instances=10)
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
        # Verrou AVANT le handler : c'est le traitement lui-même qui n'est pas
        # rejouable (il crée société, facture et encaissement côté Axonaut).
        event_id = event.get("id", "")
        if event_id and not _claim_stripe_event(event_id, event_type):
            print(f"[Webhook] Événement {event_id} déjà traité — rejeu ignoré")
            return https_fn.Response("OK (rejeu ignore)", status=200)
        try:
            handler(data_obj)
        except Exception as exc:
            # Log complet pour Firebase Cloud Logging
            print(f"[Webhook] ERREUR handler '{event_type}' : {exc}")
            print(traceback.format_exc())
            # On retourne 200 quand même : Stripe ne doit pas re-tenter
            # en boucle sur des erreurs internes (données manquantes, etc.)
    else:
        print(f"[Webhook] Événement ignoré : {event_type}")

    return https_fn.Response("OK", status=200)


# ===========================================================================
# COMPTE CLIENT — create_portal_session & revoke_machine_web
# ===========================================================================

_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "https://mystrow.fr",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _cors_preflight() -> https_fn.Response:
    return https_fn.Response("", status=204, headers=_CORS_HEADERS)


def _verify_token(req: https_fn.Request) -> str | None:
    """Vérifie le Bearer token Firebase et retourne l'uid, ou None si invalide."""
    _ensure_init()
    ah = req.headers.get("Authorization", "")
    if not ah.startswith("Bearer "):
        return None
    try:
        decoded = auth.verify_id_token(ah[7:])
        return decoded["uid"]
    except Exception:
        return None


def _admin_emails() -> set:
    """Liste blanche d'emails admin (env ADMIN_EMAILS, séparés par des virgules)."""
    raw = os.environ.get("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _verify_admin(req: https_fn.Request) -> str | None:
    """Vérifie le Bearer token ET que l'email est dans ADMIN_EMAILS. Retourne l'email ou None."""
    _ensure_init()
    ah = req.headers.get("Authorization", "")
    if not ah.startswith("Bearer "):
        return None
    try:
        decoded = auth.verify_id_token(ah[7:])
    except Exception:
        return None
    email = (decoded.get("email") or "").lower()
    allow = _admin_emails()
    return email if (email and email in allow) else None


@https_fn.on_request()
def admin_cancel_subscription(req: https_fn.Request) -> https_fn.Response:
    """Annule un abonnement Stripe — RÉSERVÉ aux admins (ADMIN_EMAILS).
    POST — Authorization: Bearer <firebase_id_token> — Body: {"subscription_id": "sub_..."}
    Utilise la clé Stripe SERVEUR (compte MyStrow) : plus aucune clé Stripe dans l'app."""
    if req.method == "OPTIONS":
        return _cors_preflight()
    if not _verify_admin(req):
        return https_fn.Response(json.dumps({"error": "Accès réservé aux administrateurs"}),
                                 status=403, headers=_CORS_HEADERS)
    try:
        body = json.loads(req.data or b"{}")
    except Exception:
        body = {}
    sub_id = (body.get("subscription_id") or "").strip()
    if not sub_id:
        return https_fn.Response(json.dumps({"error": "subscription_id manquant"}),
                                 status=400, headers=_CORS_HEADERS)
    try:
        result = _stripe_post(f"/subscriptions/{sub_id}", {"cancel_at_period_end": "true"})
        return https_fn.Response(
            json.dumps({"ok": True, "cancel_at_period_end": bool(result.get("cancel_at_period_end"))}),
            status=200, headers={**_CORS_HEADERS, "Content-Type": "application/json"})
    except Exception as exc:
        print(f"[AdminCancel] Erreur Stripe : {exc}")
        return https_fn.Response(json.dumps({"error": "Erreur Stripe"}),
                                 status=500, headers=_CORS_HEADERS)


@https_fn.on_request()
def create_portal_session(req: https_fn.Request) -> https_fn.Response:
    """
    Crée une session Stripe Customer Portal pour l'utilisateur connecté.
    POST — Authorization: Bearer <firebase_id_token>
    Retourne : {"url": "https://billing.stripe.com/..."}
    """
    if req.method == "OPTIONS":
        return _cors_preflight()

    uid = _verify_token(req)
    if not uid:
        return https_fn.Response(
            json.dumps({"error": "Non autorisé"}), status=401, headers=_CORS_HEADERS
        )

    db = _get_db()
    doc = db.collection("licenses").document(uid).get()
    if not doc.exists:
        return https_fn.Response(
            json.dumps({"error": "Licence introuvable"}), status=404, headers=_CORS_HEADERS
        )

    customer_id = doc.to_dict().get("stripe_customer_id", "")
    if not customer_id:
        return https_fn.Response(
            json.dumps({"error": "Pas de compte Stripe associé"}), status=404, headers=_CORS_HEADERS
        )

    try:
        session = _stripe_post("/billing_portal/sessions", {
            "customer":   customer_id,
            "return_url": "https://mystrow.fr/compte",
        })
        return https_fn.Response(
            json.dumps({"url": session["url"]}),
            status=200,
            headers={**_CORS_HEADERS, "Content-Type": "application/json"},
        )
    except Exception as exc:
        print(f"[Portal] Erreur Stripe : {exc}")
        return https_fn.Response(
            json.dumps({"error": "Erreur Stripe"}), status=500, headers=_CORS_HEADERS
        )


@https_fn.on_request()
def revoke_machine_web(req: https_fn.Request) -> https_fn.Response:
    """
    Révoque une machine depuis l'espace client web.
    POST — Authorization: Bearer <firebase_id_token>
    Body JSON : {"machine_id": "..."}
    """
    if req.method == "OPTIONS":
        return _cors_preflight()

    uid = _verify_token(req)
    if not uid:
        return https_fn.Response(
            json.dumps({"error": "Non autorisé"}), status=401, headers=_CORS_HEADERS
        )

    try:
        body = req.get_json(silent=True) or {}
        machine_id = body.get("machine_id", "").strip()
        if not machine_id:
            return https_fn.Response(
                json.dumps({"error": "machine_id manquant"}), status=400, headers=_CORS_HEADERS
            )

        db = _get_db()
        ref = db.collection("licenses").document(uid)
        doc = ref.get()
        if not doc.exists:
            return https_fn.Response(
                json.dumps({"error": "Licence introuvable"}), status=404, headers=_CORS_HEADERS
            )

        machines = doc.to_dict().get("machines", [])
        new_machines = [m for m in machines if m.get("id") != machine_id]

        if len(new_machines) == len(machines):
            return https_fn.Response(
                json.dumps({"error": "Machine non trouvée"}), status=404, headers=_CORS_HEADERS
            )

        ref.update({"machines": new_machines})
        return https_fn.Response(
            json.dumps({"ok": True}),
            status=200,
            headers={**_CORS_HEADERS, "Content-Type": "application/json"},
        )
    except Exception as exc:
        print(f"[RevokeWeb] Erreur : {exc}")
        return https_fn.Response(
            json.dumps({"error": str(exc)}), status=500, headers=_CORS_HEADERS
        )


# ===========================================================================
# CLOUD FUNCTION: subscribe_newsletter
# ===========================================================================

_NL_CORS = {
    "Access-Control-Allow-Origin":  "https://mystrow.fr",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _garder_en_attente(email: str, lang: str, motif: str) -> bool:
    """Filet de sécurité : conserve une inscription que Sender a refusée.

    Quand le compte Sender est en revue anti-spam, l'API rend 401 sur les
    abonnés. Sans ce filet, chaque personne qui s'inscrit pendant ce temps est
    perdue pour de bon : elle voit une erreur, ne recommence pas, et son adresse
    n'existe nulle part. Ici elle est ecrite dans Firestore, et on lui repond
    que tout va bien — ce qui est vrai de son point de vue, elle est inscrite.

    Les adresses en attente se rejouent ensuite avec :
        collection « newsletter_pending », champ `synced` a False.

    Rend True si l'adresse a bien ete conservee.
    """
    try:
        _get_db().collection("newsletter_pending").document(email).set({
            "email":   email,
            "lang":    lang,
            "motif":   motif,
            "synced":  False,
            "created": datetime.now(timezone.utc).isoformat(),
        })
        print(f"[subscribe_newsletter] {email} garde en attente ({motif})")
        return True
    except Exception as exc:
        print(f"[subscribe_newsletter] echec du filet Firestore: {exc}")
        return False


@https_fn.on_request(max_instances=5)
def subscribe_newsletter(req: https_fn.Request) -> https_fn.Response:
    """
    Endpoint HTTPS : POST /subscribe_newsletter
    Body: {"email": "user@example.com", "lang": "fr"}
    Abonne le contact au groupe newsletter de Sender.net.
    Secret : SENDER_API_TOKEN (firebase functions:secrets:set SENDER_API_TOKEN)

    Le jeton reste ICI, cote serveur : le site est statique, une cle posee
    dans son JavaScript serait lisible par n'importe quel visiteur.
    """
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204, headers=_NL_CORS)

    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405, headers=_NL_CORS)

    try:
        body  = json.loads(req.get_data() or b"{}")
        email = (body.get("email") or "").strip().lower()
        lang  = (body.get("lang") or "fr").strip().lower()
        # Les CINQ langues de MyStrow, alignees sur i18n.py et sur les dossiers
        # du site (/de, /en, /es, /pt + la racine en francais).
        #
        # La liste s'arretait a ("fr", "en") : les 30 pages espagnoles,
        # allemandes et portugaises envoyaient bien leur langue, et elle etait
        # silencieusement ecrasee en « fr » ici. Tous ces inscrits etaient donc
        # enregistres comme francophones — invisible, puisque rien n'echoue.
        if lang not in ("fr", "en", "es", "de", "pt"):
            lang = "fr"
    except Exception:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "JSON invalide"}),
            status=400, headers={"Content-Type": "application/json", **_NL_CORS},
        )

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Adresse email invalide."}),
            status=400, headers={"Content-Type": "application/json", **_NL_CORS},
        )

    # ── Choix du prestataire ─────────────────────────────────────────────────
    # Brevo dès qu'il est configuré, Sender tant qu'il ne l'est pas. Cette
    # bascule automatique est ce qui rend le déploiement SANS ORDRE IMPOSÉ :
    # on peut livrer cette fonction avant d'avoir créé la liste Brevo sans que
    # la moindre inscription tombe dans le filet Firestore. Le jour où
    # BREVO_LIST_NEWSLETTER est renseigné, la bascule se fait toute seule.
    # À nettoyer — avec `_sender_token` et `SENDER_GROUP_NEWSLETTER` — une fois
    # les contacts historiques repris dans Brevo.
    brevo_token = _brevo_key()
    list_id     = _brevo_list_newsletter()
    sender_tok  = _sender_token()

    if brevo_token and list_id:
        fournisseur = "brevo"
        url = "https://api.brevo.com/v3/contacts"
        payload = json.dumps({
            "email":      email,
            "listIds":    [list_id],
            "attributes": {"LANG": lang.upper()},
            # Une adresse déjà connue est mise à jour et rattachée à la liste
            # au lieu de renvoyer une erreur « duplicate_parameter ». Se
            # réinscrire depuis une autre page du site est un geste normal, ce
            # n'est pas un échec à afficher au visiteur.
            "updateEnabled": True,
        }).encode()
        entetes = {"api-key": brevo_token}
    elif sender_tok:
        fournisseur = "sender"
        url = "https://api.sender.net/v2/subscribers"
        payload = json.dumps({
            "email":  email,
            "groups": [SENDER_GROUP_NEWSLETTER],
            "fields": {"lang": lang},
        }).encode()
        entetes = {"Authorization": "Bearer " + sender_tok}
    else:
        print("[subscribe_newsletter] aucun prestataire configuré")
        # Filet Firestore plutôt qu'une erreur sèche : une inscription perdue
        # ne se rattrape pas, le visiteur ne revient pas une deuxième fois.
        if _garder_en_attente(email, lang, "config-absente"):
            return https_fn.Response(
                json.dumps({"ok": True}),
                status=200, headers={"Content-Type": "application/json", **_NL_CORS},
            )
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Service indisponible."}),
            status=503, headers={"Content-Type": "application/json", **_NL_CORS},
        )

    try:
        import ssl as _ssl
        req_brevo = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Accept":       "application/json",
                "Content-Type": "application/json",
                # Indispensable pour Sender : sans User-Agent explicite, son
                # pare-feu répond une page HTML « Access blocked » en 403, ce
                # qui se lit à tort comme un jeton invalide.
                "User-Agent":   "MyStrow-Site/1.0 (+https://mystrow.fr)",
                **entetes,
            },
            method="POST",
        )
        ctx = _ssl.create_default_context()
        with urllib.request.urlopen(req_brevo, timeout=8, context=ctx):
            pass

        print(f"[subscribe_newsletter] {email} ({lang}) ajouté à {fournisseur}")
        return https_fn.Response(
            json.dumps({"ok": True}),
            status=200, headers={"Content-Type": "application/json", **_NL_CORS},
        )

    except urllib.error.HTTPError as e:
        if e.code in (204, 201):
            return https_fn.Response(
                json.dumps({"ok": True}),
                status=200, headers={"Content-Type": "application/json", **_NL_CORS},
            )
        print(f"[subscribe_newsletter] {fournisseur} error {e.code}: {e.read().decode()[:500]}")
        if _garder_en_attente(email, lang, f"{fournisseur}-{e.code}"):
            return https_fn.Response(
                json.dumps({"ok": True}),
                status=200, headers={"Content-Type": "application/json", **_NL_CORS},
            )
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Erreur lors de l'abonnement."}),
            status=502, headers={"Content-Type": "application/json", **_NL_CORS},
        )
    except Exception as exc:
        print(f"[subscribe_newsletter] Exception: {exc}")
        if _garder_en_attente(email, lang, "exception"):
            return https_fn.Response(
                json.dumps({"ok": True}),
                status=200, headers={"Content-Type": "application/json", **_NL_CORS},
            )
        return https_fn.Response(
            json.dumps({"ok": False, "error": "Erreur serveur."}),
            status=500, headers={"Content-Type": "application/json", **_NL_CORS},
        )


# ===========================================================================
# DOWNLOAD REDIRECT — compteur de téléchargements
# ===========================================================================

_DOWNLOAD_URLS = {
    "win":       "https://github.com/nprieto-ext/MAESTRO/releases/latest/download/MyStrow_Setup.exe",
    "mac":       "https://github.com/nprieto-ext/MAESTRO/releases/latest/download/MyStrow_arm64.dmg",
    "mac_intel": "https://github.com/nprieto-ext/MAESTRO/releases/latest/download/MyStrow_intel.dmg",
}

_DL_CORS = {"Access-Control-Allow-Origin": "*"}


@https_fn.on_request(max_instances=10)
def download_redirect(req: https_fn.Request) -> https_fn.Response:
    """Redirige vers le téléchargement GitHub et logue date/heure/lieu dans Firestore."""
    platform = req.args.get("p", "win")
    redirect_url = _DOWNLOAD_URLS.get(platform, _DOWNLOAD_URLS["win"])

    # IP réelle (derrière proxy/CDN)
    ip = (req.headers.get("X-Forwarded-For", "") or "").split(",")[0].strip()
    if not ip:
        ip = getattr(req, "remote_addr", None) or "unknown"

    # Géolocalisation via ip-api.com (gratuit, sans clé)
    geo: dict = {}
    try:
        geo_url = f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,city,regionName&lang=fr"
        geo_req = urllib.request.Request(geo_url, headers={"User-Agent": "MyStrow/1.0"})
        with urllib.request.urlopen(geo_req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                geo = data
    except Exception as e:
        print(f"[download_redirect] géoloc échouée pour {ip}: {e}")

    # Log dans Firestore
    try:
        _get_db().collection("downloads").add({
            "ts":          datetime.now(timezone.utc),
            "platform":    platform,
            "ip":          ip,
            "country":     geo.get("country", "?"),
            "countryCode": geo.get("countryCode", "?"),
            "city":        geo.get("city", "?"),
            "region":      geo.get("regionName", "?"),
        })
    except Exception as e:
        print(f"[download_redirect] Firestore write error: {e}")

    return https_fn.Response("", status=302, headers={"Location": redirect_url, **_DL_CORS})


# ---------------------------------------------------------------------------
# GA4 — visites du site par jour (réservé aux admins)
# ---------------------------------------------------------------------------

_GA4_PROPERTY_ID  = "530160506"
_GA4_ADMIN_EMAILS = {"nicop421@gmail.com"}
_GA4_CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
}


def _ga4_is_admin(req) -> bool:
    """Vérifie le jeton Firebase de l'appelant et qu'il fait partie des admins."""
    authz = req.headers.get("Authorization", "") or ""
    if not authz.startswith("Bearer "):
        return False
    token = authz.split(" ", 1)[1].strip()
    try:
        _ensure_init()
        decoded = auth.verify_id_token(token)
    except Exception as e:
        print(f"[ga4_visits] jeton invalide : {e}")
        return False
    return (decoded.get("email") or "").lower() in _GA4_ADMIN_EMAILS


@https_fn.on_request(max_instances=3)
def ga4_visits(req: https_fn.Request) -> https_fn.Response:
    """Visites du site par jour via l'API GA4 Data. Réservé aux admins.
    Query params : days (défaut 90), metric (sessions|activeUsers, défaut sessions)."""
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204, headers=_GA4_CORS)

    if not _ga4_is_admin(req):
        return https_fn.Response(
            json.dumps({"error": "unauthorized"}),
            status=401, headers={"Content-Type": "application/json", **_GA4_CORS})

    try:
        days = int(req.args.get("days", "90"))
    except (TypeError, ValueError):
        days = 90
    days = max(1, min(days, 365))
    metric = req.args.get("metric", "sessions")
    if metric not in ("sessions", "activeUsers", "totalUsers", "screenPageViews"):
        metric = "sessions"

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest,
        )
        client = BetaAnalyticsDataClient()
        request = RunReportRequest(
            property=f"properties/{_GA4_PROPERTY_ID}",
            dimensions=[Dimension(name="date")],
            metrics=[Metric(name=metric)],
            date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
        )
        resp = client.run_report(request)
        out = []
        for row in resp.rows:
            d = row.dimension_values[0].value  # "YYYYMMDD"
            try:
                v = int(row.metric_values[0].value or 0)
            except (TypeError, ValueError):
                v = 0
            if len(d) == 8 and d.isdigit():
                out.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:8]}", "visits": v})
        out.sort(key=lambda r: r["date"])
        return https_fn.Response(
            json.dumps(out),
            status=200, headers={"Content-Type": "application/json", **_GA4_CORS})
    except Exception as e:
        print(f"[ga4_visits] erreur : {e}")
        return https_fn.Response(
            json.dumps({"error": str(e)}),
            status=500, headers={"Content-Type": "application/json", **_GA4_CORS})


@https_fn.on_request(max_instances=3)
def ga4_insights(req: https_fn.Request) -> https_fn.Response:
    """Comportement des visiteurs (GA4) : pages les plus vues, sources de trafic,
    tunnel de conversion. Réservé aux admins. Query param : days (défaut 90)."""
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204, headers=_GA4_CORS)

    if not _ga4_is_admin(req):
        return https_fn.Response(
            json.dumps({"error": "unauthorized"}),
            status=401, headers={"Content-Type": "application/json", **_GA4_CORS})

    try:
        days = int(req.args.get("days", "90"))
    except (TypeError, ValueError):
        days = 90
    days = max(1, min(days, 365))

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest, OrderBy,
        )
        client = BetaAnalyticsDataClient()
        dr   = DateRange(start_date=f"{days}daysAgo", end_date="today")
        prop = f"properties/{_GA4_PROPERTY_ID}"

        def _run(dims, mets, order=None, limit=None):
            kw = dict(
                property=prop, date_ranges=[dr],
                dimensions=[Dimension(name=d) for d in dims],
                metrics=[Metric(name=m) for m in mets],
            )
            if order:
                kw["order_bys"] = [OrderBy(
                    metric=OrderBy.MetricOrderBy(metric_name=order), desc=True)]
            if limit:
                kw["limit"] = limit
            return client.run_report(RunReportRequest(**kw))

        # Pages les plus vues
        top_pages = []
        for row in _run(["pagePath"], ["screenPageViews", "activeUsers"],
                        order="screenPageViews", limit=15).rows:
            top_pages.append({
                "page":  row.dimension_values[0].value,
                "views": int(row.metric_values[0].value or 0),
                "users": int(row.metric_values[1].value or 0),
            })

        # Sources de trafic
        sources = []
        for row in _run(["sessionDefaultChannelGroup"], ["sessions"],
                        order="sessions", limit=10).rows:
            sources.append({
                "channel":  row.dimension_values[0].value,
                "sessions": int(row.metric_values[0].value or 0),
            })

        # Événements (pour le tunnel)
        events = {}
        for row in _run(["eventName"], ["eventCount"]).rows:
            events[row.dimension_values[0].value] = int(row.metric_values[0].value or 0)

        # Totaux
        totals = {"sessions": 0, "activeUsers": 0}
        tr = _run([], ["sessions", "activeUsers"])
        if tr.rows:
            totals["sessions"]    = int(tr.rows[0].metric_values[0].value or 0)
            totals["activeUsers"] = int(tr.rows[0].metric_values[1].value or 0)

        funnel = {
            "visiteurs":      totals["activeUsers"],
            "sessions":       totals["sessions"],
            "download_click": events.get("download_click", 0),
            "begin_checkout": events.get("begin_checkout", 0),
            "contact_click":  events.get("contact_click", 0),
        }

        return https_fn.Response(
            json.dumps({"top_pages": top_pages, "sources": sources, "funnel": funnel}),
            status=200, headers={"Content-Type": "application/json", **_GA4_CORS})
    except Exception as e:
        print(f"[ga4_insights] erreur : {e}")
        return https_fn.Response(
            json.dumps({"error": str(e)}),
            status=500, headers={"Content-Type": "application/json", **_GA4_CORS})
