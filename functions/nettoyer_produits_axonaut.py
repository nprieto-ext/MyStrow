"""Désactive dans Axonaut les produits MyStrow en double créés par l'ancien
code de facturation (un produit par facture, jusqu'au 02/11/2026).

- DÉSACTIVE seulement (« disabled »), ne supprime rien : les anciennes
  factures restent intactes et c'est réversible (`--reactiver`).
- Ne touche qu'aux noms « Licence MyStrow… », « Pack MyStrow… » et
  « Interface USB-DMX MyStrow (sans licence) ». Gaspiz et les autres
  produits ne sont pas concernés.
- Garde les 2 produits fixes : 40429018 (Interface) et 40429022 (Licence).

Usage (depuis App/functions) :
    venv/Scripts/python.exe nettoyer_produits_axonaut.py            # aperçu
    venv/Scripts/python.exe nettoyer_produits_axonaut.py --go       # désactive
    venv/Scripts/python.exe nettoyer_produits_axonaut.py --reactiver
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://axonaut.com/api/v2"
KEEP = {40429018, 40429022}
PREFIXES = ("Licence MyStrow", "Pack MyStrow", "Interface USB-DMX MyStrow (sans licence)")
JOURNAL = Path(__file__).with_name("axonaut_produits_desactives.json")


def cle() -> str:
    for line in Path(__file__).with_name(".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("AXONAUT_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("AXONAUT_API_KEY introuvable dans .env")


def call(key, method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"userApiKey": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    key = cle()
    if "--reactiver" in sys.argv:
        ids = json.loads(JOURNAL.read_text())
        for pid in ids:
            call(key, "PATCH", f"/products/{pid}", {"disabled": False})
            time.sleep(0.6)
        print(f"{len(ids)} produit(s) réactivé(s).")
        return

    produits = call(key, "GET", "/products")
    cible = [p for p in produits
             if not p["disabled"] and p["id"] not in KEEP
             and p["name"].startswith(PREFIXES)]
    print(f"{len(produits)} produits, {len(cible)} doublon(s) MyStrow à désactiver.")
    if "--go" not in sys.argv:
        print("Aperçu seulement. Relancer avec --go pour désactiver.")
        return

    # Le journal CUMULE les passages : un 2e lancement (après des 429) ne doit
    # pas faire oublier les produits désactivés au 1er.
    faits = json.loads(JOURNAL.read_text()) if JOURNAL.exists() else []
    avant = len(faits)
    for n, p in enumerate(cible, 1):
        for essai in range(6):
            try:
                if call(key, "PATCH", f"/products/{p['id']}", {"disabled": True}).get("disabled"):
                    faits.append(p["id"])
                break
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    print(f"échec {p['id']} : {e}")
                    break
                time.sleep(5 * (essai + 1))   # Axonaut limite le débit (429)
        else:
            print(f"échec {p['id']} : toujours 429 après 6 essais")
        time.sleep(0.6)
        if n % 25 == 0:
            print(f"… {n}/{len(cible)}")
            JOURNAL.write_text(json.dumps(faits))
    JOURNAL.write_text(json.dumps(faits))
    print(f"{len(faits) - avant} produit(s) désactivé(s) à ce passage, {len(faits)} au total. "
          f"Liste gardée dans {JOURNAL.name} (pour --reactiver).")
    restants = [p["name"] for p in call(key, "GET", "/products") if not p["disabled"]]
    print(f"Produits encore actifs : {len(restants)}")


if __name__ == "__main__":
    main()
