# -*- coding: utf-8 -*-
"""Genere les codes d'activation imprimes sur les cartes (etiquette Dymo).

Un code = 12 caracteres en 3 groupes de 4 : XXXX-XXXX-XXXX
  - 11 caracteres tires au sort (secrets),
  - 1 caractere de controle en derniere position.

L'alphabet exclut 1, I, L, O et U : plus aucune paire ambigue a la lecture
sur une etiquette Dymo (le 0 reste, mais le O a disparu, donc pas de doute).
31 symboles ^ 11 tirages = 2,5e16 combinaisons pour 200 codes valides, soit une
chance sur 1e14 de tomber juste au hasard : le brute force est hors sujet, la
limitation de debit cote serveur reste la pour le principe.

Les codes ne sont JAMAIS calcules a partir du numero de serie : ils sont tires
au hasard une bonne fois ici, et la liste fait foi. Un code deductible du
numero de serie serait un code que n'importe qui peut deduire.

Usage
-----
    python tools/generate_activation_codes.py --count 200 --batch B1
    python tools/generate_activation_codes.py --count 200 --batch B1 --push

--push envoie le lot dans Firestore (/activation_codes/{code}, status=unused)
en s'authentifiant avec le service_account.json a la racine du depot. Sans
--push, seuls les fichiers sont produits : rien n'est activable tant que les
codes ne sont pas en base.

Un lot deja ecrit est FIGE : --push relit le CSV au lieu de retirer de
nouveaux codes. Il faut --regenerate, explicite, pour repartir de zero.
"""
from __future__ import annotations

import argparse
import csv
import secrets
import time
from pathlib import Path

# 31 symboles — sans 1, I, L, O, U.
ALPHABET = "023456789ABCDEFGHJKMNPQRSTVWXYZ"
BODY_LEN = 11                     # caracteres tires au sort
DEFAULT_OUT = Path.home() / "Desktop" / "Mystrow2" / "Boitier"


def check_char(body: str) -> str:
    """Caractere de controle : somme ponderee des positions, modulo 31.

    Attrape une faute de frappe isolee et toute inversion de deux caracteres
    voisins — soit l'essentiel des erreurs de saisie humaine. La page
    d'activation rejoue le meme calcul en JavaScript pour dire "code invalide"
    avant meme d'appeler le serveur.
    """
    total = sum((i + 1) * ALPHABET.index(c) for i, c in enumerate(body))
    return ALPHABET[total % len(ALPHABET)]


def make_code() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(BODY_LEN))
    return body + check_char(body)


def pretty(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def normalize(raw: str) -> str:
    """Saisie utilisateur -> code canonique. Ce que fera aussi le serveur.

    Aucun code ne contient 1, I, L, O ni U : un O tape est forcement un 0 mal
    lu, on le corrige. Tirets, espaces et minuscules sont sans importance.
    """
    up = raw.strip().upper().replace("O", "0")
    return "".join(c for c in up if c in ALPHABET)


def is_valid(code: str) -> bool:
    return (len(code) == BODY_LEN + 1
            and all(c in ALPHABET for c in code)
            and code[-1] == check_char(code[:-1]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=200, help="nombre de codes")
    ap.add_argument("--batch", default="B1", help="identifiant du lot")
    ap.add_argument("--months", type=int, default=None,
                    help="duree de licence offerte par le code, en mois "
                         "(12 par defaut ; un lot existant garde celle de son CSV)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="dossier de sortie des fichiers")
    ap.add_argument("--push", action="store_true",
                    help="envoie le lot du CSV dans Firestore")
    ap.add_argument("--regenerate", action="store_true",
                    help="retire un lot neuf en ECRASANT les fichiers existants")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    stem     = f"Codes_Activation_MyStrow_{args.batch}_{args.count}ex"
    csv_path = args.out / f"{stem}.csv"
    txt_path = args.out / f"{stem}_DYMO.txt"

    # Un lot ecrit est FIGE. Le retirer au hasard a chaque appel invaliderait
    # les etiquettes deja imprimees et les codes deja poses en base : --push
    # relit donc le CSV au lieu de generer, et il faut --regenerate, explicite,
    # pour repartir de zero.
    if csv_path.exists() and not args.regenerate:
        with csv_path.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        codes = [row["Code_Brut"] for row in rows]
        bad = [c for c in codes if not is_valid(c)]
        if bad:
            raise SystemExit(f"CSV corrompu, codes invalides : {bad[:3]}")
        # La duree fait partie du lot, comme les codes : c'est celle du CSV qui
        # part en base. Sinon un --push oublieux mettrait 12 mois sur un lot a 2.
        csv_months = {int(row["Mois"]) for row in rows}
        if len(csv_months) != 1:
            raise SystemExit(f"CSV incoherent, plusieurs durees : {sorted(csv_months)}")
        csv_months = csv_months.pop()
        if args.months is not None and args.months != csv_months:
            raise SystemExit(f"--months {args.months} contredit le lot "
                             f"{args.batch}, ecrit a {csv_months} mois")
        args.months = csv_months
        print(f"lot {args.batch} relu depuis {csv_path.name} — "
              f"{len(codes)} codes, {args.months} mois")
        if not args.push:
            print("\nCe lot existe deja. Options :")
            print("  --push        l'envoyer dans Firestore (le rend activable)")
            print("  --regenerate  en retirer un neuf — les etiquettes deja")
            print("                imprimees deviendraient invalides")
            return
    else:
        if args.months is None:
            args.months = 12
        if csv_path.exists():
            print(f"!! {csv_path.name} ECRASE — les etiquettes deja imprimees "
                  "avec l'ancien lot ne fonctionneront plus")
        codes = []
        seen: set[str] = set()
        while len(codes) < args.count:
            c = make_code()
            if c in seen:             # collision quasi impossible, mais gratuite a exclure
                continue
            seen.add(c)
            codes.append(c)

        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Index", "Code", "Code_Brut", "Lot", "Mois"])
            for i, c in enumerate(codes, 1):
                w.writerow([i, pretty(c), c, args.batch, args.months])

        # Un code par ligne, deja formate : c'est ce fichier qu'on donne a Dymo
        # Connect en source de donnees (une etiquette par ligne).
        txt_path.write_text("\n".join(pretty(c) for c in codes) + "\n",
                            encoding="utf-8")

        print(f"{len(codes)} codes generes")
        print(f"  {csv_path}")
        print(f"  {txt_path}   <- source de donnees Dymo")
        print("\nApercu :")
        for c in codes[:5]:
            print("   ", pretty(c))

    if not args.push:
        print("\n(--push absent : rien n'a ete ecrit dans Firestore, "
              "les codes ne sont donc pas encore activables)")
        return

    import firebase_admin
    from firebase_admin import credentials, firestore

    # La cle de service vit a la racine du depot (celle qu'utilise deja
    # admin_panel.py). On retombe sur les identifiants d'ambiance seulement si
    # elle manque, pour que le script tourne aussi ailleurs.
    sa = Path(__file__).resolve().parent.parent / "service_account.json"
    if sa.exists():
        firebase_admin.initialize_app(credentials.Certificate(str(sa)))
    else:
        firebase_admin.initialize_app()
    db = firestore.client()
    now = time.time()

    batch = db.batch()
    n = 0
    for i, c in enumerate(codes, 1):
        ref = db.collection("activation_codes").document(c)
        batch.set(ref, {
            "status":      "unused",
            "batch":       args.batch,
            "index":       i,
            "months":      args.months,
            "created_utc": now,
            "used_by":     "",
            "used_email":  "",
            "used_serial": "",
            "used_utc":    0,
        })
        n += 1
        if n % 400 == 0:              # Firestore : 500 ecritures max par lot
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"\n{len(codes)} codes ecrits dans Firestore (/activation_codes)")


if __name__ == "__main__":
    main()
