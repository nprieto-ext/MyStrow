# -*- coding: utf-8 -*-
"""Cree (ou revoque) une cle de poste MyStrowFan.

La cle donne le droit d'enregistrer des boitiers via la function
`boitier_enregistrer`, et rien d'autre. Elle n'est affichee qu'UNE fois :
seule son empreinte sha256 est gardee dans `postes_boitiers`.

Usage
-----
    python tools/creer_poste_boitiers.py "Soeur"          # nouvelle cle
    python tools/creer_poste_boitiers.py --liste
    python tools/creer_poste_boitiers.py --revoquer Soeur  # tous les postes de ce nom
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nom", nargs="?", help="nom du poste (apparait dans l'historique)")
    ap.add_argument("--liste", action="store_true")
    ap.add_argument("--revoquer", metavar="NOM")
    args = ap.parse_args()

    import firebase_admin
    from firebase_admin import credentials, firestore
    firebase_admin.initialize_app(
        credentials.Certificate(str(RACINE / "service_account.json")))
    col = firestore.client().collection("postes_boitiers")

    if args.liste or args.revoquer:
        for d in col.stream():
            p = d.to_dict() or {}
            if args.revoquer and p.get("nom") == args.revoquer and p.get("actif"):
                d.reference.set({"actif": False, "revoque_utc": time.time()}, merge=True)
                p["actif"] = False
                print("  revoque :", end=" ")
            print(f"{p.get('nom')!r:20} actif={p.get('actif')} "
                  f"total={p.get('total', 0)} id={d.id[:12]}…")
        return

    if not args.nom:
        ap.error("donner un nom de poste")
    cle = "MSF-" + secrets.token_urlsafe(24)
    col.document(hashlib.sha256(cle.encode()).hexdigest()).set(
        {"nom": args.nom[:40], "actif": True, "created_utc": time.time()})
    print(f"\nPoste « {args.nom} » cree. Cle (a coller UNE fois dans MyStrowFan) :\n")
    print(f"    {cle}\n")
    print("Elle n'est stockee nulle part ailleurs : si elle se perd, en creer une autre.")


if __name__ == "__main__":
    main()
