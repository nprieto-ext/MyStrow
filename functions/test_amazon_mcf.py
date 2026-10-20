"""Test de connexion SP-API en LECTURE SEULE : stock FBA vendable des 2 packs.

    python test_amazon_mcf.py

Lit les identifiants AMZ_* dans functions/.env. Ne crée aucune commande.
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(here, ".env"), encoding="utf-8"):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

import amazon_mcf

if not amazon_mcf.configured():
    sys.exit("AMZ_LWA_CLIENT_ID / AMZ_LWA_CLIENT_SECRET / AMZ_REFRESH_TOKEN vides dans .env")
try:
    stock = amazon_mcf.get_inventory(["MS-DMX-2M", "MS-DMX-1A"])
except amazon_mcf.SpApiError as e:
    sys.exit(f"ÉCHEC : {e}")
for sku, qty in sorted(stock.items()):
    print(f"{sku} : {qty} vendable(s) en FBA")
print("Connexion SP-API OK")
