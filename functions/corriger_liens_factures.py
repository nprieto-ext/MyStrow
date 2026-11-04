"""Remplace les liens de facture privés (axonaut.com/invoice/{id}) de l'espace
client par le lien PDF public d'Axonaut (`public_path`).

Jusqu'au 04/11/2026, `_axonaut_create_invoice` stockait l'URL de l'interface
Axonaut : le bouton « Voir → » de compte.html menait le client à une page de
connexion Axonaut.

    python corriger_liens_factures.py            # simulation, n'écrit rien
    python corriger_liens_factures.py --ecrire   # corrige Firestore
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

ICI = Path(__file__).resolve().parent


def _cle_axonaut() -> str:
    for nom in (".env", ".env.local"):
        f = ICI / nom
        if f.exists():
            for ligne in f.read_text(encoding="utf-8").splitlines():
                m = re.match(r'\s*AXONAUT_API_KEY\s*=\s*"?([^"\s]+)', ligne)
                if m:
                    return m[1]
    raise SystemExit("AXONAUT_API_KEY introuvable")


def main() -> None:
    ecrire = "--ecrire" in sys.argv
    cle = _cle_axonaut()
    firebase_admin.initialize_app(credentials.Certificate(str(ICI.parent / "service_account.json")))
    db = firestore.client()

    a_faire = []
    for d in db.collection_group("invoices").stream():
        x = d.to_dict() or {}
        url = x.get("invoice_url") or ""
        if "/public/" in url:
            continue
        inv_id = x.get("axonaut_id") or (re.search(r"/invoice/(\d+)", url) or [None, None])[1]
        if inv_id:
            a_faire.append((d.reference, int(inv_id), url))
    print(f"{len(a_faire)} lien(s) privé(s) à corriger — {'ÉCRITURE' if ecrire else 'simulation'}")

    ok = ko = 0
    for ref, inv_id, ancien in a_faire:
        req = urllib.request.Request(f"https://axonaut.com/api/v2/invoices/{inv_id}",
                                     headers={"userApiKey": cle})
        try:
            pub = json.load(urllib.request.urlopen(req, timeout=30)).get("public_path") or ""
        except Exception as e:
            pub = ""
            print(f"  ✗ {inv_id} : {e}")
        if pub:
            if ecrire:
                ref.update({"invoice_url": pub})
            ok += 1
        else:
            ko += 1
        time.sleep(0.6)   # Axonaut renvoie 429 si on enchaîne trop vite
    print(f"Terminé : {ok} corrigé(s){'' if ecrire else ' (simulés)'}, {ko} sans lien public")


if __name__ == "__main__":
    main()
