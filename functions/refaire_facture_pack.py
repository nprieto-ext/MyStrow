"""Annule et remplace une facture de pack émise AVANT la ventilation
marchandise/service (02/11/2026) : une seule ligne « Pack MyStrow — … ».

Une facture émise ne se modifie pas : on émet
  1. un AVOIR qui reprend la ligne d'origine en quantité −1, soldé par un
     paiement négatif (forme des avoirs déjà au dossier, cf. _axonaut_create_credit_note) ;
  2. une NOUVELLE facture en 2 lignes (interface = marchandise, licence =
     service, via _invoice_lines), mention « Annule et remplace », payée.
Effet sur le CA : nul (−HT puis +HT le même jour) ; la déclaration URSSAF
coupait déjà l'ancienne ligne au même prorata.

    python refaire_facture_pack.py F20261028-11109 pack_vie            # simulation
    python refaire_facture_pack.py F20261028-11109 pack_vie --ecrire
"""
import os
import re
import sys
import urllib.request
from pathlib import Path

import firebase_admin
from firebase_admin import credentials

ICI = Path(__file__).resolve().parent
# En local, main.py lit sa config dans os.environ (injectée par Firebase en prod).
for _nom in (".env", ".env.local"):
    _f = ICI / _nom
    if _f.exists():
        for _l in _f.read_text(encoding="utf-8").splitlines():
            _m = re.match(r'\s*([A-Z_][A-Z0-9_]*)\s*=\s*"?([^"\n]*)"?', _l)
            if _m:
                os.environ.setdefault(_m[1], _m[2])
if not firebase_admin._apps:
    firebase_admin.initialize_app(credentials.Certificate(str(ICI.parent / "service_account.json")))
sys.path.insert(0, str(ICI))
import main as m  # noqa: E402


def _trouver(numero: str, company_id: int | None = None) -> dict:
    for c in ([{"id": company_id}] if company_id else m._axonaut("GET", "/companies") or []):
        for inv in m._axonaut("GET", f"/companies/{c['id']}/invoices") or []:
            if inv.get("number") == numero:
                return m._axonaut("GET", f"/invoices/{inv['id']}") or {}
    raise SystemExit(f"Facture {numero} introuvable")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2 or args[1] not in m._PACK_PRIX_TTC:
        raise SystemExit(__doc__)
    numero, plan = args
    ecrire = "--ecrire" in sys.argv

    inv = _trouver(numero)
    cid = inv["company"]["id"]
    lignes = inv.get("invoice_lines") or []
    if len(lignes) != 1 or not (lignes[0].get("name") or "").startswith("Pack MyStrow"):
        raise SystemExit(f"{numero} n'est pas une facture de pack à ligne unique — rien à faire")
    l0 = lignes[0]
    ht, ttc = float(inv["pre_tax_amount"]), float(inv["total"])
    taux = float((l0.get("tax_rates") or [{}])[0].get("rate", m.TVA_RATE))

    # Anti-doublon : un avoir sur ce numéro existe-t-il déjà ?
    mention_avoir = f"Avoir sur facture : #{numero}"
    for x in m._axonaut("GET", f"/companies/{cid}/invoices") or []:
        full = m._axonaut("GET", f"/invoices/{x['id']}") or {}
        if (full.get("mandatory_mentions") or "").strip() == mention_avoir:
            raise SystemExit(f"Avoir déjà émis ({full.get('number')}) — arrêt")

    avoir_lignes = [{"id": l0.get("product_id"), "name": l0.get("name"),
                     "price": float(l0["price"]), "tax_rate": taux, "quantity": -1}]
    nouv_lignes = m._invoice_lines(plan, ht, taux)
    print(f"{numero} — {inv['company']['name']} — {ht} € HT / {ttc} € TTC ({taux} %)")
    print("  Avoir      :", [(l["name"], -l["price"]) for l in avoir_lignes])
    print("  Nouvelle   :", [(l["name"], l["price"]) for l in nouv_lignes],
          "=", round(sum(l["price"] for l in nouv_lignes), 2), "€ HT")
    if not ecrire:
        print("Simulation : rien n'est écrit. Relancer avec --ecrire.")
        return

    ref = (inv.get("reference") or "")[:30]
    today = m.datetime.now(m.timezone.utc).strftime("%Y-%m-%d")

    av = m._axonaut("POST", "/invoices", {
        "company_id": cid, "reference": ref, "reference_date": today,
        "theme_id": 339036, "mandatory_mentions": mention_avoir, "products": avoir_lignes})
    if not av or not av.get("id"):
        raise SystemExit("Échec création de l'avoir")
    m._axonaut_register_payment(av["id"], -ttc, f"Annule #{numero}", nature=6)
    av_num = av.get("number") or m._axonaut_invoice_number(av["id"])
    print(f"✓ Avoir {av_num} (id {av['id']})")

    nv = m._axonaut("POST", "/invoices", {
        "company_id": cid, "reference": ref, "reference_date": today,
        "theme_id": 339036, "mandatory_mentions": f"Annule et remplace la facture {numero}",
        "products": nouv_lignes})
    if not nv or not nv.get("id"):
        raise SystemExit("Échec création de la nouvelle facture (l'avoir, lui, est émis)")
    m._axonaut_check_lines(nv["id"], nouv_lignes)
    m._axonaut_register_payment(nv["id"], ttc, ref or "Stripe")
    nv_full = m._axonaut("GET", f"/invoices/{nv['id']}") or {}
    nv_num, nv_url = nv_full.get("number"), nv_full.get("public_path")
    print(f"✓ Nouvelle facture {nv_num} (id {nv['id']}) — {nv_full.get('total')} € TTC, "
          f"reste dû {nv_full.get('outstanding_amount')}")

    # Espace client : on ajoute l'avoir et la nouvelle facture à côté de l'ancienne.
    db = m._get_db()
    lic = next(iter(db.collection("licenses").where("axonaut_company_id", "==", cid)
                    .limit(1).get()), None)
    if lic:
        col = lic.reference.collection("invoices")
        base = {"plan": plan, "tax_rate": taux, "stripe_ref": inv.get("reference") or ""}
        col.add({**base, "date": today, "type": "credit", "amount_eur": -ttc,
                 "amount_ht": -ht, "amount_tax": round(-(ttc - ht), 2),
                 "invoice_url": m._axonaut_public_pdf_url(av["id"]),
                 "axonaut_id": av["id"], "axonaut_number": av_num})
        col.add({**base, "date": today, "type": "invoice", "amount_eur": ttc,
                 "amount_ht": ht, "amount_tax": round(ttc - ht, 2), "invoice_url": nv_url,
                 "axonaut_id": nv["id"], "axonaut_number": nv_num})
        print(f"✓ Espace client mis à jour (uid {lic.id})")
    else:
        print("⚠ Aucun compte relié à cette société : espace client non mis à jour")

    if nv_url:
        pdf = ICI / f"Facture_{nv_num}.pdf"
        pdf.write_bytes(urllib.request.urlopen(nv_url, timeout=60).read())
        print(f"✓ PDF : {pdf}")


if __name__ == "__main__":
    main()
