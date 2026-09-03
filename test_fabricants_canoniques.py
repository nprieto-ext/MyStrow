"""
test_fabricants_canoniques.py — Un fabricant, une rubrique.

`FIXTURE_LIBRARY` groupait sur la chaine BRUTE du champ `manufacturer`. Les
quatre bibliotheques qui l'alimentent (196 fixtures natives, la collection
locale, 627 fixtures OFL, 1710 fixtures QLC+) n'ecrivent pas les marques
pareil : 23 fabricants se retrouvaient eclates en 2 a 4 rubriques, dont
American DJ (274 fixtures, « ADJ » + « American DJ ») et Cameo (175, « cameo »
+ « Cameo »).

Le tri aggravait la chose : `sorted()` brut range TOUTES les majuscules avant
TOUTES les minuscules, si bien que « cameo » et « beamZ » atterrissaient a la
fin de la liste, apres « lightmaXX » — a l'oppose de leurs jumelles.

Ce qui est verrouille ici :

  * la normalisation ignore casse, accents, espaces et ponctuation ;
  * les alias explicites (abreviation, faute de frappe, gamme accolee) ;
  * un fabricant HORS table garde son orthographe exacte — on ne fusionne que
    ce qui a ete verifie a la main, jamais par ressemblance ;
  * « Generique » reste epingle en tete, le reste est trie sans tenir compte
    de la casse ;
  * la normalisation est faite a L'AFFICHAGE : `build_fixture_library` ne
    reecrit AUCUNE fixture. Reecrire le champ dans le fichier local ferait
    revenir les copies distantes en double, la cle de dedoublonnage du bouton
    Actualiser etant `(nom, fabricant)`.

    python test_fabricants_canoniques.py
"""
import unittest

from core import canonical_manufacturer, build_fixture_library


class TestNomCanonique(unittest.TestCase):

    def test_casse_et_ponctuation_ignorees(self):
        for variante, attendu in [
            ("cameo", "Cameo"), ("Cameo", "Cameo"),
            ("beamZ", "BeamZ"), ("BeamZ", "BeamZ"),
            ("EuroLite", "Eurolite"), ("Eurolite", "Eurolite"),
            ("MacMah", "Mac Mah"), ("Mac Mah", "Mac Mah"),
            ("BETOPPER", "Betopper"), ("Betopper", "Betopper"),
            ("Fun-Generation", "Fun Generation"),
            ("Pro-Lights", "Prolights"),
            ("IMG Stageline", "IMG Stage Line"),
            ("MEGA-Lite", "Mega Lite"), ("MegaLite", "Mega Lite"),
            ("PR LIGHTING", "PR Lighting"),
            ("Ledj", "LEDJ"), ("KAM", "Kam"),
        ]:
            self.assertEqual(canonical_manufacturer(variante), attendu, variante)

    def test_apostrophes_et_accents(self):
        # Trois apostrophes differentes pour la meme marque dans la collection.
        for v in ("UKing", "Uking", "U`King", "U'King", "U’King"):
            self.assertEqual(canonical_manufacturer(v), "UKing", v)
        self.assertEqual(canonical_manufacturer("Generic"), "Générique")
        self.assertEqual(canonical_manufacturer("Générique"), "Générique")

    def test_alias_explicites(self):
        for variante, attendu in [
            ("ADJ", "American DJ"),
            ("AFX", "AFX Light"),
            ("BETOPER", "Betopper"),            # faute de frappe, 3 fixtures
            ("Blizzard Lighting", "Blizzard"),
            ("BoomTone", "BoomTone DJ"),
            ("Chauvet DJ", "Chauvet"),
            ("Chauvet Professional", "Chauvet"),
            ("GLX Lighting", "GLX"),
            ("Ibiza", "Ibiza Light"),
            ("Martin Professional", "Martin"),
            ("Philips Selecon", "Philips"),
        ]:
            self.assertEqual(canonical_manufacturer(variante), attendu, variante)

    def test_marques_voisines_NON_fusionnees(self):
        """Un faux positif est pire qu'un doublon : il masque une vraie marque.

        Toutes ces paires se ressemblent assez pour tomber dans un
        rapprochement flou, et sont pourtant des fabricants differents.
        """
        for a in ("Showline", "Showlite", "Power Lighting", "Robert Juliat",
                  "Cinetec", "ETEC", "StageTech", "MARQ", "NO MARQUE",
                  "VR Stage Lighting", "STAGE LIGHTING", "Evolight",
                  "Evolite", "Mega LED Lighting"):
            self.assertEqual(canonical_manufacturer(a), a, a)

    def test_inconnu_garde_son_orthographe(self):
        self.assertEqual(canonical_manufacturer("Fabricant Inedit"),
                         "Fabricant Inedit")
        self.assertEqual(canonical_manufacturer("  Contest  "), "Contest")

    def test_vide_tombe_sur_generique(self):
        for v in (None, "", "   "):
            self.assertEqual(canonical_manufacturer(v), "Générique")


class TestBibliotheque(unittest.TestCase):

    FIXTURES = [
        {"name": "A", "manufacturer": "cameo"},
        {"name": "B", "manufacturer": "Cameo"},
        {"name": "C", "manufacturer": "ADJ"},
        {"name": "D", "manufacturer": "American DJ"},
        {"name": "E", "manufacturer": "lightmaXX"},
        {"name": "F", "manufacturer": "Generic"},
        {"name": "G", "manufacturer": "Générique"},
        {"name": "H", "manufacturer": "beamZ"},
        {"name": "I"},                              # sans fabricant
    ]

    def test_regroupement(self):
        lib = build_fixture_library(self.FIXTURES)
        self.assertEqual(len(lib["Cameo"]), 2)
        self.assertEqual(len(lib["American DJ"]), 2)
        self.assertEqual(len(lib["Générique"]), 3)   # Generic + Générique + sans
        self.assertNotIn("cameo", lib)
        self.assertNotIn("ADJ", lib)

    def test_generique_en_tete(self):
        self.assertEqual(list(build_fixture_library(self.FIXTURES))[0], "Générique")

    def test_tri_insensible_a_la_casse(self):
        """« lightmaXX » ne doit plus etre relegue apres les majuscules."""
        ordre = list(build_fixture_library(self.FIXTURES))
        self.assertEqual(ordre[0], "Générique")
        self.assertEqual([o.lower() for o in ordre[1:]],
                         sorted(o.lower() for o in ordre[1:]))

    def test_les_fixtures_ne_sont_pas_reecrites(self):
        """La normalisation est un habillage : les donnees restent intactes.

        C'est ce qui empeche le bouton Actualiser de faire revenir les copies
        distantes en double — sa cle de dedoublonnage est `(nom, fabricant)`.
        """
        src = [dict(f) for f in self.FIXTURES]
        lib = build_fixture_library(src)
        self.assertEqual(lib["Cameo"][0]["manufacturer"], "cameo")
        self.assertEqual([f.get("manufacturer") for f in src],
                         [f.get("manufacturer") for f in self.FIXTURES])


if __name__ == "__main__":
    unittest.main(verbosity=2)
