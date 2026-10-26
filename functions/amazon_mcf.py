"""
Amazon SP-API — Expédié par Amazon multicanal (MCF).

Le pack boîtier USB-DMX vendu sur mystrow.fr part du stock FBA : le webhook
Stripe crée la commande MCF ici, et la tâche planifiée `mcf_suivi` vient
relire le numéro de suivi une fois le colis expédié.

Authentification : jeton LWA seul. Amazon a supprimé la signature AWS SigV4
(et donc tout besoin d'un compte AWS / rôle IAM) en octobre 2023.

Variables d'environnement (functions/.env) :
  AMZ_LWA_CLIENT_ID      – amzn1.application-oa2-client.…
  AMZ_LWA_CLIENT_SECRET  – expire tous les 180 jours : le renouveler dans le
                           Solution Provider Portal AVANT l'échéance, sinon
                           plus aucune commande du site ne part.
  AMZ_REFRESH_TOKEN      – Atzr|… (auto-autorisation de l'app privée)
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
SP_API_EU     = "https://sellingpartnerapi-eu.amazon.com"
MARKETPLACE_FR = "A13V1IB3VIYZZH"
_OUTBOUND = "/fba/outbound/2020-07-01"

# Jeton d'accès LWA : valable 1 h, gardé en mémoire de l'instance.
_token = {"value": "", "exp": 0.0}


class SpApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"SP-API HTTP {status} : {detail}")
        self.status = status
        self.detail = detail


def configured() -> bool:
    return all(os.environ.get(k, "").strip() for k in
               ("AMZ_LWA_CLIENT_ID", "AMZ_LWA_CLIENT_SECRET", "AMZ_REFRESH_TOKEN"))


def _access_token() -> str:
    if _token["value"] and time.time() < _token["exp"] - 60:
        return _token["value"]
    body = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": os.environ.get("AMZ_REFRESH_TOKEN", "").strip(),
        "client_id":     os.environ.get("AMZ_LWA_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("AMZ_LWA_CLIENT_SECRET", "").strip(),
    }).encode()
    req = urllib.request.Request(LWA_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            rep = json.loads(r.read())
    except urllib.error.HTTPError as e:
        # `invalid_client` ici = client secret expiré (rotation des 180 jours).
        raise SpApiError(e.code, "LWA " + e.read().decode("utf-8", "replace")[:300])
    _token["value"] = rep["access_token"]
    _token["exp"] = time.time() + int(rep.get("expires_in", 3600))
    return _token["value"]


def _call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(SP_API_EU + path, data=data, method=method)
    req.add_header("x-amz-access-token", _access_token())
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "MyStrow/1.0 (Language=Python; +https://mystrow.fr)")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise SpApiError(e.code, e.read().decode("utf-8", "replace")[:600])
    return json.loads(raw) if raw else {}


def order_id_for(stripe_ref: str) -> str:
    """Identifiant MCF stable dérivé du paiement Stripe.

    Amazon refuse un `sellerFulfillmentOrderId` déjà utilisé : en le dérivant
    du paiement, un rejeu du webhook ne peut PAS expédier deux colis. Limite
    Amazon : 40 caractères, lettres/chiffres/-/_ ; un id de session Stripe en
    fait ~66, d'où l'empreinte.
    """
    import hashlib
    return "MS-" + hashlib.sha1(stripe_ref.encode()).hexdigest()[:20].upper()


def create_order(order_id: str, sku: str, quantity: int, address: dict,
                 email: str, displayable_id: str,
                 comment: str = "Merci pour votre commande MyStrow !") -> None:
    """Crée la commande MCF (expédition immédiate, tout ou rien).

    `address` : clés Stripe (name, line1, line2, city, postal_code, country,
    state, phone). `FillOrKill` : si le stock FBA ne suffit pas, Amazon refuse
    la commande au lieu d'en expédier une partie — l'erreur remonte à
    l'appelant, qui prévient l'admin.
    """
    dest = {
        "name":          (address.get("name") or "")[:50],
        "addressLine1":  (address.get("line1") or "")[:60],
        "city":          (address.get("city") or "")[:50],
        # Champ obligatoire côté Amazon, sans équivalent en France : on y
        # met la ville quand Stripe n'a pas de région.
        "stateOrRegion": (address.get("state") or address.get("city") or "")[:50],
        "postalCode":    (address.get("postal_code") or "")[:20],
        "countryCode":   (address.get("country") or "FR").upper(),
    }
    if address.get("line2"):
        dest["addressLine2"] = address["line2"][:60]
    if address.get("phone"):
        dest["phone"] = address["phone"][:20]

    _call("POST", f"{_OUTBOUND}/fulfillmentOrders", {
        "marketplaceId":            MARKETPLACE_FR,
        "sellerFulfillmentOrderId": order_id,
        "displayableOrderId":       displayable_id[:40],
        "displayableOrderDate":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "displayableOrderComment":  comment[:250],
        "shippingSpeedCategory":    "Standard",
        "destinationAddress":       dest,
        "fulfillmentAction":        "Ship",
        "fulfillmentPolicy":        "FillOrKill",
        "notificationEmails":       [email] if email else [],
        "items": [{
            "sellerSku":                    sku,
            "sellerFulfillmentOrderItemId": "1",
            "quantity":                     int(quantity),
        }],
    })


def get_order(order_id: str) -> dict:
    """Statut + colis d'une commande MCF.

    Retourne {"status": …, "packages": [{"carrier", "tracking"}]}. Les colis
    n'apparaissent qu'une fois la commande expédiée (statut COMPLETE ou
    COMPLETE_PARTIALLED).
    """
    rep = _call("GET", f"{_OUTBOUND}/fulfillmentOrders/{urllib.parse.quote(order_id)}")
    payload = rep.get("payload") or {}
    status = (payload.get("fulfillmentOrder") or {}).get("fulfillmentOrderStatus", "")
    packages = []
    for shipment in payload.get("fulfillmentShipments") or []:
        for pkg in shipment.get("fulfillmentShipmentPackage") or []:
            if pkg.get("trackingNumber"):
                packages.append({"carrier":  pkg.get("carrierCode", ""),
                                 "tracking": pkg["trackingNumber"]})
    return {"status": status, "packages": packages}


def preview(postal_code: str, sku: str = "MS-DMX-2M", country: str = "FR") -> dict:
    """Fourchette de livraison Standard vers un code postal.

    Amazon n'a besoin que du code postal pour estimer : la ville et la rue
    sont des bouche-trous (vérifié le 20/10/2026, Marseille / Brest / Ajaccio
    / Strasbourg ; le 21/10 pour BE, LU, IT, ES, PT). Sauf aux Pays-Bas, où la
    rue et ville doivent correspondre au code postal : on estime alors sur Amsterdam,
    les délais y sont les mêmes partout (J+2 vérifié le 21/10/2026).
    Retourne {"fulfillable", "earliest", "latest"} (dates ISO).
    """
    line1, city = "-", "-"
    if country == "NL":
        postal_code, line1, city = "1012 AB", "Damrak 1", "Amsterdam"
    rep = _call("POST", f"{_OUTBOUND}/fulfillmentOrders/preview", {
        "marketplaceId": MARKETPLACE_FR,
        "address": {"name": "Client", "addressLine1": line1, "city": city,
                    "stateOrRegion": "-", "postalCode": postal_code,
                    "countryCode": country},
        "shippingSpeedCategories": ["Standard"],
        "items": [{"sellerSku": sku, "sellerFulfillmentOrderItemId": "1", "quantity": 1}],
    })
    for p in (rep.get("payload") or {}).get("fulfillmentPreviews") or []:
        ship = (p.get("fulfillmentPreviewShipments") or [{}])[0]
        return {"fulfillable": bool(p.get("isFulfillable")),
                "earliest": ship.get("earliestArrivalDate", ""),
                "latest": ship.get("latestArrivalDate", "")}
    return {"fulfillable": False, "earliest": "", "latest": ""}


def get_orders(created_after: str) -> list[dict]:
    """Commandes Amazon.fr créées après `created_after` (ISO, UTC).

    Rôle « Suivi des stocks et des commandes » : pas de données personnelles
    (ni nom ni adresse), ce qui suffit pour une alerte de vente. Amazon exige
    que `created_after` soit au moins 2 minutes dans le passé.
    """
    q = urllib.parse.urlencode({"MarketplaceIds": MARKETPLACE_FR,
                                "CreatedAfter": created_after})
    rep = _call("GET", f"/orders/v0/orders?{q}")
    return (rep.get("payload") or {}).get("Orders") or []


def get_order_items(amazon_order_id: str) -> list[dict]:
    rep = _call("GET", f"/orders/v0/orders/{urllib.parse.quote(amazon_order_id)}/orderItems")
    return (rep.get("payload") or {}).get("OrderItems") or []


def get_inventory(skus: list[str]) -> dict:
    """Stock FBA vendable par SKU (lecture seule — sert de test de connexion)."""
    q = urllib.parse.urlencode({
        "details":         "true",
        "granularityType": "Marketplace",
        "granularityId":   MARKETPLACE_FR,
        "marketplaceIds":  MARKETPLACE_FR,
        "sellerSkus":      ",".join(skus),
    })
    rep = _call("GET", f"/fba/inventory/v1/summaries?{q}")
    out = {}
    for s in (rep.get("payload") or {}).get("inventorySummaries") or []:
        out[s.get("sellerSku")] = (s.get("inventoryDetails") or {}).get("fulfillableQuantity", 0)
    return out
