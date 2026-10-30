# -*- coding: utf-8 -*-
"""Initialise les boitiers maison a la chaine, en ligne de commande.

Le moteur est boitier_init.py (partage avec l'onglet « Boitiers » de
l'admin) : voir sa documentation pour le detail des etapes et du suivi.

Usage
-----
    python tools/initialiser_boitier.py --push                  # demande : 2 mois ou 1 an ?
    python tools/initialiser_boitier.py --months 2 --push       # sans la question
    python tools/initialiser_boitier.py                         # essai : flashe, n'ecrit pas Firestore
    python tools/initialiser_boitier.py --push --sans-flash
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from boitier_init import OFFRES, Initialiseur  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--months", type=int, default=0,
                    help="duree de licence offerte par chaque boitier de la "
                         "serie (sans lui : question au lancement)")
    ap.add_argument("--batch", default="",
                    help="identifiant du lot (defaut : DMY-2M, DMY-12M...)")
    ap.add_argument("--push", action="store_true",
                    help="ecrit dans Firestore (sinon : essai, rien n'y est ecrit)")
    ap.add_argument("--sans-flash", action="store_true",
                    help="ne flashe pas : boitiers deja a jour")
    args = ap.parse_args()

    choix = list(OFFRES.items())
    while args.months <= 0:
        print("Quels boitiers initialiser a la suite ?")
        for i, (nom, _) in enumerate(choix, 1):
            print(f"  {i}) offre {nom}")
        rep = input("Choix : ").strip()
        if rep.isdigit() and 1 <= int(rep) <= len(choix):
            args.months = choix[int(rep) - 1][1]

    import firebase_admin
    from firebase_admin import credentials, firestore

    sa = RACINE / "service_account.json"
    if sa.exists():
        firebase_admin.initialize_app(credentials.Certificate(str(sa)))
    else:
        firebase_admin.initialize_app()

    init = Initialiseur(firestore.client(), args.months, args.batch,
                        push=args.push, flash=not args.sans_flash)
    try:
        init.run()
    except KeyboardInterrupt:
        print(f"\nFin. {init.n} boitier(s) initialise(s).")


if __name__ == "__main__":
    main()
