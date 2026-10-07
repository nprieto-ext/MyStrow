# -*- coding: utf-8 -*-
"""Pousse les numeros de serie des boitiers USB-DMX dans Firestore.

Sources (colonne B) :
  - Numeros_de_Serie_MyStrow_200ex.xlsx : MS-DMX-0001-B9ER, autocollants des
    boitiers Electroconcept (OPTO) ; la duree de licence est portee par le code
    de la carte ;
  - Numeros_de_Serie_MyStrow_DMY_30ex.xlsx : MS-DMY-XXXX-XXXX, graves sous les
    boitiers maison, SANS carte : le numero seul active, la duree est donc
    ecrite ici sur le boitier (--months, obligatoire pour un lot DMY).

C'est cette collection que la fonction `activate_code` interroge : un numero
absent d'ici = activation refusee. Sans ce push, aucune activation ne passe.

Le fichier est lu sans openpyxl (un .xlsx est un zip de XML) pour que le script
tourne tel quel dans un environnement nu.

Usage
-----
    python tools/push_boitier_serials.py              # lecture seule, controle
    python tools/push_boitier_serials.py --push       # ecrit dans Firestore
    python tools/push_boitier_serials.py --xlsx .../Numeros_de_Serie_MyStrow_DMY_30ex.xlsx         --batch DMY1 --months 12 [--push]

--push s'authentifie avec le service_account.json a la racine du depot.
"""
from __future__ import annotations

import argparse
import re
import time
import zipfile
from pathlib import Path

DEFAULT_XLSX = (Path.home() / "Desktop" / "MyStrow" / "Medias" / "Boitier"
                / "Numeros_de_Serie_MyStrow_200ex.xlsx")

# MS-DMX-0001-B9ER : index a 4 chiffres, puis 4 caracteres de controle.
# MS-DMY-9JQF-Y7ZY : 8 caracteres tires au sort, ni I, ni O, ni 0 (meme
# alphabet que _DMY_ALPHABET dans functions/main.py).
SERIAL_RE = re.compile(r"^MS-DMX-\d{4}-[0-9A-Z]{4}$"
                       r"|^MS-DMY-[1-9A-HJ-NP-Z]{4}-[1-9A-HJ-NP-Z]{4}$")


def read_serials(xlsx: Path) -> list[str]:
    """Extrait la colonne B, en-tete exclu.

    Chaines en ligne (<is>) ou partagees (t="s" : <v> est alors un index dans
    sharedStrings.xml, ce qu'ecrit openpyxl)."""
    with zipfile.ZipFile(xlsx) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        try:
            sst = z.read("xl/sharedStrings.xml").decode("utf-8")
        except KeyError:
            sst = ""
    shared = [re.sub(r"<[^>]+>", "", si)
              for si in re.findall(r"<si>(.*?)</si>", sst, re.S)]
    out: list[str] = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        val = None
        m = re.search(r'<c r="B\d+"[^>]*>\s*<is><t[^>]*>(.*?)</t></is>', row, re.S)
        if m:
            val = m.group(1)
        else:
            m = re.search(r'<c r="B\d+"([^>]*)>\s*<v>(.*?)</v>', row, re.S)
            if m:
                val = (shared[int(m.group(2))] if 't="s"' in m.group(1)
                       else m.group(2))
        if val and val.strip() not in ("Numero_Serie", "Serial Number"):
            out.append(val.strip().upper())
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    ap.add_argument("--batch", default="B1", help="identifiant du lot")
    ap.add_argument("--months", type=int, default=0,
                    help="duree de licence ecrite sur chaque boitier "
                         "(obligatoire pour un lot MS-DMY, sans carte)")
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
    if any(x.startswith("MS-DMY-") for x in serials) and args.months <= 0:
        raise SystemExit("lot MS-DMY : --months obligatoire (le numero seul "
                         "active la licence, sa duree est sur le boitier)")
    if args.months:
        print(f"  duree ecrite sur chaque boitier : {args.months} mois")

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
        doc = {
            "serial":      s,
            "index":       i,
            "batch":       args.batch,
            "created_utc": now,
        }
        if args.months:
            doc["months"] = args.months
        batch.set(db.collection("boitiers").document(s), doc, merge=True)
        if i % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"\n{len(serials)} numeros ecrits dans Firestore (/boitiers)")


if __name__ == "__main__":
    main()
