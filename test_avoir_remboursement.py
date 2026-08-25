# -*- coding: utf-8 -*-
"""Tests de l'avoir Axonaut automatique (webhook Stripe charge.refunded).

Aucun appel reseau : Axonaut et Firestore sont remplaces par des doublures qui
enregistrent ce qu'on leur envoie. On verifie la FORME exacte de l'avoir
(quantite negative, HT deduit du taux, mention « Avoir sur facture : #... »,
paiement negatif qui le solde), et surtout qu'un rejeu du meme evenement
Stripe ne cree pas un second avoir.

    python test_avoir_remboursement.py
"""
import importlib.util
import os
import sys
import types

FUNCTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "functions")


# ---------------------------------------------------------------------------
# Import de functions/main.py sans Firebase installe (et sans confondre avec
# le main.py de l'application, qui porte le meme nom).
# ---------------------------------------------------------------------------
def _stub_firebase():
    fa = types.ModuleType("firebase_admin")
    fa._apps = {"default": object()}
    fa.initialize_app = lambda *a, **k: None
    fa.auth = types.ModuleType("firebase_admin.auth")
    fa.auth.get_user = lambda uid: types.SimpleNamespace(email="")
    fa.firestore = types.ModuleType("firebase_admin.firestore")
    fa.firestore.client = lambda: None
    sys.modules["firebase_admin"] = fa
    sys.modules["firebase_admin.auth"] = fa.auth
    sys.modules["firebase_admin.firestore"] = fa.firestore

    ff = types.ModuleType("firebase_functions")
    https_fn = types.ModuleType("firebase_functions.https_fn")

    def _on_request(**kwargs):
        return lambda fn: fn

    https_fn.on_request = _on_request
    https_fn.Request = object
    https_fn.Response = object
    ff.https_fn = https_fn
    sys.modules["firebase_functions"] = ff
    sys.modules["firebase_functions.https_fn"] = https_fn


def _load_main():
    _stub_firebase()
    spec = importlib.util.spec_from_file_location(
        "cf_main", os.path.join(FUNCTIONS_DIR, "main.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cf_main"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Doublure Firestore minimale (juste ce que le handler utilise)
# ---------------------------------------------------------------------------
class FakeDoc:
    def __init__(self, store, path):
        self.store, self.path = store, path

    @property
    def exists(self):
        return self.path in self.store

    def to_dict(self):
        return dict(self.store.get(self.path) or {})


class FakeDocRef:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def collection(self, name):
        return FakeCollection(self.store, f"{self.path}/{name}")

    def get(self):
        return FakeDoc(self.store, self.path)

    def set(self, data, merge=False):
        if merge and self.path in self.store:
            self.store[self.path].update(data)
        else:
            self.store[self.path] = dict(data)

    def update(self, data):
        self.store.setdefault(self.path, {}).update(data)


class FakeCollection:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def document(self, doc_id):
        return FakeDocRef(self.store, f"{self.path}/{doc_id}")

    def add(self, data):
        n = len([k for k in self.store if k.startswith(self.path + "/")])
        self.store[f"{self.path}/auto{n}"] = dict(data)

    def get(self):
        return [FakeDoc(self.store, p) for p in sorted(self.store)
                if p.startswith(self.path + "/")
                and "/" not in p[len(self.path) + 1:]]


class FakeDb:
    def __init__(self, store):
        self.store = store

    def collection(self, name):
        return FakeCollection(self.store, name)


# ---------------------------------------------------------------------------
# Scenario commun : le client de la facture F20260824-10888 (23,99 EUR TTC)
# ---------------------------------------------------------------------------
UID = "sD4ZCL1LSITjjvUktyW187wZTcB2"

def _fresh_store():
    return {
        f"licenses/{UID}": {
            "email": "client@example.com",
            "plan": "license",
            "plan_type": "monthly",
            "axonaut_company_id": 50670608,
            "stripe_customer_id": "cus_TEST",
        },
        f"licenses/{UID}/invoices/inv1": {
            "date": "2026-08-24",
            "amount_eur": 23.99,
            "amount_ht": 19.99,
            "tax_rate": 20.0,
            "plan": "monthly",
            "axonaut_id": 35655186,
            "axonaut_number": "F20260824-10888",
            "stripe_ref": "in_1U80eT1gGkNcl6caFoAMLE13",
            "type": "invoice",
        },
    }


def _charge(amount_cents=2399, refund_id="re_TEST1", **over):
    charge = {
        "id": "ch_TEST",
        "customer": "cus_TEST",
        "invoice": "in_1U80eT1gGkNcl6caFoAMLE13",
        "payment_intent": "pi_TEST",
        "amount": 2399,
        "amount_refunded": amount_cents,
        "refunds": {"data": [{"id": refund_id, "amount": amount_cents,
                              "status": "succeeded"}]},
    }
    charge.update(over)
    return charge


def _install(m, store, axonaut_ok=True):
    """Branche les doublures et retourne la liste des appels Axonaut."""
    calls = []

    def fake_axonaut(method, path, payload=None):
        calls.append((method, path, payload))
        if method == "POST" and path == "/invoices":
            if not axonaut_ok:
                return None
            return {"id": 99999, "number": "F20260824-10890"}
        if method == "POST" and path == "/payments":
            return {"id": 12345}
        if method == "GET" and path.startswith("/invoices/"):
            return {"id": 35655186, "number": "F20260824-10888"}
        return {}

    m._axonaut = fake_axonaut
    m._get_db = lambda: FakeDb(store)
    m._find_uid_by_customer = lambda cid: UID if cid == "cus_TEST" else None
    return calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_avoir_total(m):
    store = _fresh_store()
    calls = _install(m, store)
    m._on_charge_refunded(_charge())

    posts = [c for c in calls if c[0] == "POST" and c[1] == "/invoices"]
    assert len(posts) == 1, f"un seul avoir attendu, {len(posts)} envoyes"
    body = posts[0][2]
    assert body["company_id"] == 50670608
    assert body["mandatory_mentions"] == "Avoir sur facture : #F20260824-10888", \
        body["mandatory_mentions"]
    line = body["products"][0]
    assert line["quantity"] == -1, "l'avoir se fait par une QUANTITE negative"
    assert line["price"] == 19.99, line["price"]
    assert line["tax_rate"] == 20.0
    # Le TTC reconstitue doit retomber au centime sur le montant rembourse.
    assert round(line["price"] * 1.20, 2) == 23.99

    pays = [c for c in calls if c[1] == "/payments"]
    assert len(pays) == 1, "l'avoir doit etre solde par un paiement"
    assert pays[0][2]["amount"] == -23.99, pays[0][2]
    assert pays[0][2]["nature"] == 6, "un avoir n'est pas un encaissement CB"
    assert pays[0][2]["reference"] == "Annule #F20260824-10888"

    marker = store[f"licenses/{UID}/refunds/re_TEST1"]
    assert marker["status"] == "done" and marker["axonaut_id"] == 99999, marker

    avoirs = [v for k, v in store.items()
              if k.startswith(f"licenses/{UID}/invoices/")
              and v.get("type") == "credit_note"]
    assert len(avoirs) == 1, "l'avoir doit apparaitre dans « Mon compte »"
    assert avoirs[0]["amount_eur"] == -23.99, avoirs[0]
    assert avoirs[0]["origin_number"] == "F20260824-10888"
    print("OK  avoir total : quantite -1, 19,99 HT + 20 %, paiement -23,99")


def test_rejeu_pas_de_doublon(m):
    store = _fresh_store()
    calls = _install(m, store)
    m._on_charge_refunded(_charge())
    n1 = len([c for c in calls if c[1] == "/invoices"])
    m._on_charge_refunded(_charge())          # Stripe rejoue le meme evenement
    n2 = len([c for c in calls if c[1] == "/invoices"])
    assert n1 == 1 and n2 == 1, f"{n2} avoirs pour un seul remboursement"
    print("OK  rejeu du webhook : aucun second avoir")


def test_remboursement_partiel(m):
    store = _fresh_store()
    calls = _install(m, store)
    m._on_charge_refunded(_charge(amount_cents=1000, refund_id="re_PART"))
    body = [c for c in calls if c[1] == "/invoices"][0][2]
    assert body["products"][0]["price"] == 8.33, body["products"][0]
    pay = [c for c in calls if c[1] == "/payments"][0][2]
    assert pay["amount"] == -10.0, pay
    print("OK  remboursement partiel : 10,00 TTC -> 8,33 HT")


def test_facture_sans_ref_stripe(m):
    """Facture d'avant le champ stripe_ref : repli sur la plus recente."""
    store = _fresh_store()
    store[f"licenses/{UID}/invoices/inv1"].pop("stripe_ref")
    store[f"licenses/{UID}/invoices/inv0"] = {
        "date": "2026-07-24", "amount_eur": 23.99, "tax_rate": 20.0,
        "plan": "monthly", "axonaut_id": 111, "axonaut_number": "F20260724-1",
        "type": "invoice",
    }
    calls = _install(m, store)
    m._on_charge_refunded(_charge(refund_id="re_OLD"))
    body = [c for c in calls if c[1] == "/invoices"][0][2]
    assert body["mandatory_mentions"] == "Avoir sur facture : #F20260824-10888", \
        body["mandatory_mentions"]
    print("OK  facture sans stripe_ref : repli sur la plus recente")


def test_jamais_crediter_un_avoir(m):
    """Un avoir deja au dossier ne doit jamais servir de facture d'origine."""
    store = _fresh_store()
    store[f"licenses/{UID}/invoices/zz_avoir"] = {
        "date": "2026-08-25", "amount_eur": -23.99, "tax_rate": 20.0,
        "plan": "monthly", "axonaut_id": 222, "axonaut_number": "F20260825-9",
        "type": "credit_note", "stripe_ref": "pi_TEST",
    }
    store[f"licenses/{UID}/invoices/inv1"].pop("stripe_ref")
    calls = _install(m, store)
    m._on_charge_refunded(_charge(refund_id="re_NOCRED"))
    body = [c for c in calls if c[1] == "/invoices"][0][2]
    assert "F20260825-9" not in body["mandatory_mentions"], body["mandatory_mentions"]
    print("OK  un avoir n'est jamais credite a son tour")


def test_echec_axonaut_laisse_une_trace(m):
    store = _fresh_store()
    _install(m, store, axonaut_ok=False)
    m._on_charge_refunded(_charge(refund_id="re_KO"))
    marker = store[f"licenses/{UID}/refunds/re_KO"]
    assert marker["status"] == "error", marker
    print("OK  echec Axonaut : marqueur 'error' (avoir a faire a la main)")


def test_client_inconnu_ne_plante_pas(m):
    store = _fresh_store()
    calls = _install(m, store)
    m._on_charge_refunded(_charge(customer="cus_AUTRE"))
    assert not [c for c in calls if c[1] == "/invoices"], "aucun avoir attendu"
    print("OK  customer inconnu : rien de cree, message dans les logs")


def test_sans_liste_refunds(m):
    """Cas reel : l'API recente n'inclut PAS `refunds` dans l'objet Charge."""
    store = _fresh_store()
    calls = _install(m, store)
    charge = _charge()
    charge.pop("refunds")
    m._on_charge_refunded(charge)

    posts = [c for c in calls if c[1] == "/invoices"]
    assert len(posts) == 1, f"{len(posts)} avoirs pour un remboursement"
    assert posts[0][2]["products"][0]["price"] == 19.99
    marker = store[f"licenses/{UID}/refunds/chg_ch_TEST_2399"]
    assert marker["status"] == "done" and marker["amount_eur"] == 23.99, marker
    print("OK  sans liste `refunds` : avoir du cumul rembourse")


def test_sans_liste_deux_partiels(m):
    """Deux partiels successifs : on credite le DELTA, pas le cumul."""
    store = _fresh_store()
    calls = _install(m, store)
    c1 = _charge(amount_cents=1000); c1.pop("refunds")
    m._on_charge_refunded(c1)
    c2 = _charge(amount_cents=2399); c2.pop("refunds")   # cumul apres le 2e
    m._on_charge_refunded(c2)

    montants = [c[2]["amount"] for c in calls if c[1] == "/payments"]
    assert montants == [-10.0, -13.99], montants
    print("OK  deux partiels : -10,00 puis -13,99 (le delta, pas le cumul)")


def test_sans_liste_rejeu(m):
    store = _fresh_store()
    calls = _install(m, store)
    for _ in range(2):
        c = _charge(); c.pop("refunds")
        m._on_charge_refunded(c)
    posts = [c for c in calls if c[1] == "/invoices"]
    assert len(posts) == 1, f"{len(posts)} avoirs pour un seul remboursement"
    print("OK  sans liste `refunds` : le rejeu ne cree pas de doublon")


def test_rattrapage_apres_echec(m):
    """Un avoir tombe en erreur doit pouvoir etre rattrape au rejeu suivant."""
    store = _fresh_store()
    _install(m, store, axonaut_ok=False)
    c = _charge(); c.pop("refunds")
    m._on_charge_refunded(c)
    assert store[f"licenses/{UID}/refunds/chg_ch_TEST_2399"]["status"] == "error"

    calls = _install(m, store)                    # Axonaut repond a nouveau
    c = _charge(); c.pop("refunds")
    m._on_charge_refunded(c)
    posts = [x for x in calls if x[1] == "/invoices"]
    assert len(posts) == 1, "l'avoir en echec doit etre rejoue"
    assert store[f"licenses/{UID}/refunds/chg_ch_TEST_2399"]["status"] == "done"
    print("OK  avoir en echec : rattrape au rejeu, sans doublon")


def test_licence_intacte(m):
    """Un remboursement ne coupe pas l'acces : c'est l'annulation qui le fait."""
    store = _fresh_store()
    _install(m, store)
    m._on_charge_refunded(_charge(refund_id="re_LIC"))
    assert store[f"licenses/{UID}"]["plan"] == "license", store[f"licenses/{UID}"]
    print("OK  la licence n'est pas touchee par le remboursement")


if __name__ == "__main__":
    m = _load_main()
    for fn in (test_avoir_total, test_rejeu_pas_de_doublon, test_remboursement_partiel,
               test_facture_sans_ref_stripe, test_jamais_crediter_un_avoir,
               test_echec_axonaut_laisse_une_trace, test_client_inconnu_ne_plante_pas,
               test_sans_liste_refunds, test_sans_liste_deux_partiels,
               test_sans_liste_rejeu, test_rattrapage_apres_echec,
               test_licence_intacte):
        fn(m)
    print("\nTous les tests passent.")
