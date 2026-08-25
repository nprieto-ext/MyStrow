"""
test_patch_import.py — Import d'un patch QLC+ / tableau, sans interface.

    python test_patch_import.py

Couvre ce qui se trompe en silence : la NUMEROTATION (QLC+ compte adresses et
univers a partir de 0, un tableau ecrit par un humain a partir de 1 — une erreur
d'un cran decale tout le patch sans qu'aucun message ne le dise), la fixture
introuvable qui doit garder le bon encombrement, et les controles qui empechent
d'importer un patch impossible (univers au-dela des 4, debordement du canal 512).
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import patch_import as pi
from i18n import tr

ECHECS = []


def verifie(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  ECHEC {message}")
        ECHECS.append(message)


def ecrire(nom, contenu):
    chemin = os.path.join(tempfile.gettempdir(), nom)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(contenu)
    return chemin


QXW = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE Workspace>
<Workspace xmlns="http://www.qlcplus.org/Workspace">
 <Engine>
  <Fixture>
   <Manufacturer>Chauvet</Manufacturer><Model>4Bar</Model>
   <Mode>3 Channels Mode</Mode><ID>0</ID><Name>Projo face</Name>
   <Universe>0</Universe><Address>0</Address><Channels>3</Channels>
  </Fixture>
  <Fixture>
   <Manufacturer>Marque Inconnue</Manufacturer><Model>Zzzz 9000</Model>
   <Mode>Standard</Mode><ID>1</ID><Name>Contre 1</Name>
   <Universe>1</Universe><Address>19</Address><Channels>7</Channels>
  </Fixture>
  <Fixture>
   <Manufacturer>Generic</Manufacturer><Model>Generic</Model>
   <Mode>Generic</Mode><ID>2</ID><Name>Bloc</Name>
   <Universe>0</Universe><Address>99</Address><Channels>4</Channels>
  </Fixture>
  <Fixture>
   <Manufacturer>Chauvet</Manufacturer><Model>4Bar</Model>
   <Mode>15 Channels Mode</Mode><ID>3</ID><Name>Trop loin</Name>
   <Universe>9</Universe><Address>505</Address><Channels>15</Channels>
  </Fixture>
 </Engine>
</Workspace>
"""

CSV = """Patch du spectacle - 24/08/2026;;;;;;;
Nom;Marque;Modele;Mode;Univers;Adresse DMX;Canaux;Groupe
Face 1;Chauvet;4Bar;3 Channels Mode;1;1;3;Face
Douche 2 SL;;Zzzz 9000;;2;20;7;Douche 2
Combine;;;;;2.100;6;lateral
Ligne vide sans adresse;;;;;;;
"""


def test_qlcplus():
    print("\n[QLC+ (.qxw)]")
    entrees, avertissements = pi.parse_qlcplus_workspace(ecrire("t_pi.qxw", QXW))
    par_nom = {e["name"]: e for e in entrees}

    # Le piege numero un : <Address>0</Address> veut dire canal 1.
    verifie(par_nom["Projo face"]["address"] == 1,
            "adresse QLC+ base 0 ramenee en base 1")
    verifie(par_nom["Projo face"]["universe"] == 0,
            "univers QLC+ deja en base 0, laisse tel quel")
    verifie(par_nom["Contre 1"]["address"] == 20 and par_nom["Contre 1"]["universe"] == 1,
            "deuxieme appareil : univers 2 (index 1), adresse 20")

    # Un gradateur generique de 4 canaux, ce sont 4 gradateurs independants.
    blocs = [e for e in entrees if e["name"].startswith("Bloc ")]
    verifie(len(blocs) == 4, "gradateur generique deplie en 4 appareils")
    verifie([b["address"] for b in blocs] == [100, 101, 102, 103],
            "les 4 gradateurs se suivent a partir du canal 100")
    verifie(any("Bloc" in a for a in avertissements),
            "le depliage est annonce dans les avertissements")

    # Le groupe MyStrow n'existe nulle part ailleurs : il se devine du libelle.
    verifie(par_nom["Projo face"]["group"] == "face",
            "groupe devine depuis le nom (« Projo face »)")
    verifie(par_nom["Contre 1"]["group"] == "contre",
            "groupe devine depuis le nom (« Contre 1 »)")


def test_resolution():
    print("\n[Correspondance et controles]")
    entrees, _ = pi.parse_qlcplus_workspace(ecrire("t_pi.qxw", QXW))
    lignes = {r["name"]: r for r in pi.resolve(entrees)}

    face = lignes["Projo face"]
    verifie(face["confidence"] == "exact",
            "marque + modele + mode identiques -> correspondance exacte")
    verifie(len(face["profile"]) == 3, "profil trouve : 3 canaux")

    inconnu = lignes["Contre 1"]
    verifie(inconnu["confidence"] == "generic",
            "fixture absente de la bibliotheque -> profil generique")
    verifie(len(inconnu["profile"]) == 7,
            "le generique garde les 7 canaux : la fixture suivante ne se decale pas")

    verifie(lignes["Bloc 1"]["profile"] == ["Dim"]
            and lignes["Bloc 1"]["fixture_type"] == "Gradateur",
            "un appareil d'un canal est reconnu gradateur, sans alerte")

    loin = lignes["Trop loin"]
    verifie(loin["blocking"] and not loin["include"],
            "univers 10 + debordement 512 : ligne bloquante, decochee d'office")
    verifie(len(loin["issues"]) >= 2,
            "les deux raisons du blocage sont ecrites")


def test_chevauchement():
    print("\n[Chevauchement d'adresses]")
    entrees = [
        {"name": "A", "manufacturer": "", "model": "", "mode": "",
         "universe": 0, "address": 1, "channels": 6, "group": None},
        {"name": "B", "manufacturer": "", "model": "", "mode": "",
         "universe": 0, "address": 4, "channels": 6, "group": None},
        {"name": "C", "manufacturer": "", "model": "", "mode": "",
         "universe": 1, "address": 4, "channels": 6, "group": None},
    ]
    lignes = {r["name"]: r for r in pi.resolve(entrees)}
    # Message compare via tr() : le test doit passer quelle que soit la langue
    # configuree sur la machine qui le lance.
    attendu = tr("pimp_i_overlap", name="A")
    verifie(attendu in lignes["B"]["issues"], "B empiete sur A : signale")
    verifie(not any(i == attendu for i in lignes["C"]["issues"]),
            "C a la meme adresse mais dans un autre univers : rien a signaler")


def test_tableau():
    print("\n[Tableau CSV]")
    entrees, avertissements = pi.parse_table(ecrire("t_pi.csv", CSV))
    verifie(len(entrees) == 3, "3 lignes exploitables (le titre et la ligne "
                               "sans adresse sont ecartes)")
    par_nom = {e["name"]: e for e in entrees}

    # L'autre sens du piege : un tableau humain compte l'univers a partir de 1.
    verifie(par_nom["Face 1"]["universe"] == 0 and par_nom["Face 1"]["address"] == 1,
            "univers 1 du tableau -> index 0, adresse inchangee")
    verifie(par_nom["Douche 2 SL"]["universe"] == 1,
            "univers 2 du tableau -> index 1")
    verifie(par_nom["Combine"]["universe"] == 1 and par_nom["Combine"]["address"] == 100,
            "adresse combinee « 2.100 » relue en univers 2 / canal 100")
    verifie(par_nom["Douche 2 SL"]["group"] == "douche2",
            "colonne Groupe « Douche 2 » -> douche2")
    verifie(par_nom["Combine"]["group"] == "lat",
            "colonne Groupe « lateral » -> lat")
    verifie(pi.resolve(entrees)[0]["confidence"] == "exact",
            "la meme fixture qu'en QLC+ est retrouvee depuis le tableau")


def test_entete_absente():
    print("\n[Tableau sans en-tete reconnaissable]")
    chemin = ecrire("t_pi_bad.csv", "un;deux;trois\n1;2;3\n")
    try:
        pi.parse_table(chemin)
        verifie(False, "un tableau sans en-tete doit lever une erreur explicite")
    except ValueError as e:
        verifie(str(e) == tr("pimp_i_no_header"),
                "l'erreur est traduite, pas un plantage brut")
    # Le detail des colonnes attendues est ajoute par l'interface, sous
    # l'erreur : c'est la seule chose qui permette de corriger le fichier.
    verifie("Adresse" in tr("pimp_table_hint")
            and "Profil DMX" in tr("pimp_table_hint"),
            "l'aide affichee sous l'erreur liste les colonnes attendues")


def test_alias_canaux():
    print("\n[Noms de canaux recales]")
    idx = pi.build_index()
    tous = {c for recs in idx["by_model"].values() for r in recs for c in r["profile"]}
    for mort in ("Effect", "A", "GoboRot"):
        verifie(mort not in tous,
                f"« {mort} » (inconnu du moteur DMX) n'atteint plus les profils")
    verifie("Effects" in tous and "Ambre" in tous,
            "leurs equivalents MyStrow sont bien presents")


def test_aller_retour_xlsx():
    """Le classeur exporte par MyStrow doit se relire a l'identique.

    C'est le chemin que suivra un regisseur qui reprend le patch d'un autre PC,
    et le seul qui soit exact au canal pres : la colonne « Profil DMX » decrit
    chaque appareil, il n'y a plus rien a deviner.
    """
    print("\n[Aller-retour avec l'export XLSX de MyStrow]")
    try:
        import patch_export
        from openpyxl import load_workbook  # noqa: F401
    except Exception as e:
        print(f"  (ignore : {e})")
        return

    class FauxProjo:
        def __init__(self, name, group, ftype, addr, uni, prof):
            self.name, self.group, self.fixture_type = name, group, ftype
            self.start_address, self.universe = addr, uni
            self.canvas_x = self.canvas_y = None
            self._prof = prof

    projos = [
        FauxProjo("Face 1", "face", "PAR LED", 1, 0, ["R", "G", "B", "Dim"]),
        FauxProjo("Lyre SL", "contre", "Moving Head", 21, 1,
                  ["Pan", "PanFine", "Tilt", "TiltFine", "Dim", "ColorWheel"]),
        FauxProjo("Bloc 1", "douche2", "Gradateur", 100, 0, ["Dim"]),
    ]
    chemin = os.path.join(tempfile.gettempdir(), "t_pi_export.xlsx")
    patch_export.export_patch_xlsx(chemin, projos,
                                   lambda i, p: p._prof, "Test")

    entrees, _ = pi.parse_table(chemin)
    verifie(len(entrees) == 3, "les 3 appareils sont relus")
    lignes = pi.resolve(entrees)
    for origine, relu in zip(projos, lignes):
        verifie(relu["name"] == origine.name
                and relu["group"] == origine.group
                and relu["address"] == origine.start_address
                and relu["universe"] == origine.universe
                and relu["profile"] == origine._prof,
                f"« {origine.name} » revient identique (groupe, univers, "
                f"adresse, profil)")
    verifie(all(r["confidence"] == "exact" for r in lignes),
            "aucune deduction : le profil vient du fichier")


if __name__ == "__main__":
    print("=" * 62)
    print("  Import d'un patch (QLC+ / tableau)")
    print("=" * 62)
    test_qlcplus()
    test_resolution()
    test_chevauchement()
    test_tableau()
    test_entete_absente()
    test_alias_canaux()
    test_aller_retour_xlsx()
    print("\n" + "=" * 62)
    if ECHECS:
        print(f"  {len(ECHECS)} ECHEC(S)")
        for m in ECHECS:
            print(f"   - {m}")
        sys.exit(1)
    print("  Tout est vert.")
