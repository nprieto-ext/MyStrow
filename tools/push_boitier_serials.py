# -*- coding: utf-8 -*-
"""Pousse les numeros de serie des boitiers USB-DMX dans Firestore.

Source : Numeros_de_Serie_MyStrow_200ex.xlsx (colonne Numero_Serie), le fichier
qui a servi a imprimer les autocollants colles sous les boitiers.

C'est cette collection que la fonction `activate_code` interroge : un numero
absent d'ici = activation refusee. Sans ce push, aucune activation ne passe.

Le fichier est lu sans openpyxl (un .xlsx est un zip de XML) pour que le script
tourne tel quel dans un environnement nu.

Usage
-----
    python tools/push_boitier_serials.py              # lecture seule, controle
    python tools/push_boitier_serials.py --push       # ecrit dans Firestore

--push s'authentifie avec le service_account.json a la racine du depot.
"""
from __future__ import annotations

import argparse
import re
import time
import zipfile
from pathlib import Path

DEFAULT_XLSX = (Path.home() / "Desktop" / "Mystrow2" / "Boitier"
                / "Numeros_de_Serie_MyStrow_200ex.xlsx")

# MS-DMX-0001-B9ER : index a 4 chiffres, puis 4 caracteres de controle.
SERIAL_RE = re.compile(r"^MS-DMX-\d{4}-[0-9A-Z]{4}$")


def read_serials(xlsx: Path) -> list[str]:
    """Extrait la colonne B (Numero_Serie), en-tete exclu."""
    with zipfile.ZipFile(xlsx) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    out: list[str] = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        m = re.search(r'<c r="B\d+"[^>]*>\s*<is><t[^>]*>(.*?)</t></is>', row, re.S)
        if not m:
            m = re.search(r'<c r="B\d+"[^>]*>\s*<v>(.*?)</v>', row, re.S)
        if m and m.group(1) != "Numero_Serie":
            out.append(m.group(1).strip().upper())
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    ap.add_argument("--batch", default="B1", help="identifiant du lot")
    ap.add_argument("--push", action="store_true",
                    help="ecrit dans Firestore (sinon : controle seul)")
    args = ap.parse_args()

    serials = read_serials(args.xlsx)
    bad = [s for s in serials if not SERIAL_RE.match(s)]
    dup = {s for s in serials if serials.count(s) > 1}

    print(f"{len(serials)} numeros lus dans {args.xlsx.name}")
    print(f"  format invalide : {bad or 'aucun'}")
    print(f"  doublons        : {sorted(dup) or 'aucun'}")
    if serials:
        print(f"  du {serials[0]} au {serials[-1]}")
    if bad or dup:
        raise SystemExit("correction necessaire avant le push")

    if not args.push:
        print("\n(--push absent : rien n'a ete ecrit)")
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
    for i, s in enumerate(serials, 1):
        # merge=True : relancer le script ne doit pas effacer l'activation
        # deja enregistree sur un boitier livre.
        batch.set(db.collection("boitiers").document(s), {
            "serial":      s,
            "index":       i,
            "batch":       args.batch,
            "created_utc": now,
        }, merge=True)
        if i % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"\n{len(serials)} numeros ecrits dans Firestore (/boitiers)")


if __name__ == "__main__":
    main()
