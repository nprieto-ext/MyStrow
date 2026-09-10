"""
test_machines_effet.py — Etincelles, flamme, brouillard : les machines a effet.

MyStrow ne connaissait qu'UNE machine, la machine a fumee, et son exclusion des
effets etait ecrite SEIZE fois en dur sous la forme `p.group != "fumee"`. Trois
machines de plus arrivent (brouillard/hazer, etincelles, lance-flamme) et deux
d'entre elles crachent du FEU : le groupe ne pouvait plus servir de preuve, rien
n'empechant de ranger un lance-flamme dans le groupe « face ».

Ce qui est verrouille ici :

  * le canal de sortie (`Smoke`, `Spark`, `Flame`) est pilote par le NIVEAU, pas
    par un dimmer, et tombe a 0 en mute ;
  * les canaux voisins (duree, mode) sortent enfin leur valeur — la branche
    s'arretait au debit et au ventilateur, la duree d'une machine a etincelles
    2 canaux etait donc morte ;
  * ces canaux-la GARDENT leur valeur en mute : sur beaucoup de machines,
    « Mode » a 0 vaut « automatique / sound-active », soit exactement ce qu'un
    mute doit empecher ;
  * `fixture_is_fx_machine` tranche sur le TYPE et non sur le groupe : une
    machine rangee dans « face » reste hors des effets et de l'IA ;
  * `fixture_is_pyro` distingue l'ATMOSPHERE (fumee, brume) du DECLENCHEMENT
    (etincelles, flamme) — le noir general epargne la premiere, coupe la
    seconde ;
  * le genre envoye a la 3D ('fog', 'haze', 'spark', 'flame') ;
  * la detection de type a l'import d'un patch ;
  * les hazers de la bibliotheque ont quitte « Machine a fumee ».

    python test_machines_effet.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from projector import Projector
from artnet_dmx import ArtNetDMX, DMX_PROFILES, CHANNEL_TYPES
from core import (FX_MACHINE_TYPES, FX_MACHINE_PYRO_TYPES,
                  fixture_is_fx_machine, fixture_is_pyro,
                  fixture_machine_kind, fixture_output_channel)
import builtin_fixtures
import patch_import


def _machine(ftype, profile, level=0, group="face"):
    p = Projector(group, name=ftype, fixture_type=ftype)
    p.dmx_profile = list(profile)
    p.set_level(level)
    p.fan_speed = 0
    return p


class SortieDMX(unittest.TestCase):
    """Le canal de debit suit le niveau, et rien d'autre ne bouge."""

    def _trame(self, proj, nb):
        dmx = ArtNetDMX()
        dmx.set_projector_patch("face_0", list(range(1, nb + 1)), 0,
                                proj.dmx_profile)
        dmx.update_from_projectors([proj])
        return [dmx.get_channel(i) for i in range(1, nb + 1)]

    def test_etincelles_le_niveau_est_le_debit(self):
        p = _machine("Machine a etincelles", ["Spark"], level=60)
        self.assertEqual(self._trame(p, 1), [153],
                         "le debit d'etincelles doit suivre le niveau")

    def test_flamme_le_niveau_est_la_hauteur(self):
        p = _machine("Lance-flamme", ["Flame"], level=100)
        self.assertEqual(self._trame(p, 1), [255])

    def test_brouillard_partage_le_canal_fumee(self):
        p = _machine("Machine a brouillard", ["Smoke", "Fan"], level=50)
        p.fan_speed = 80
        self.assertEqual(self._trame(p, 2), [127, 80],
                         "un hazer se pilote comme une machine a fumee")

    def test_mute_coupe_la_sortie(self):
        p = _machine("Lance-flamme", ["Flame"], level=100)
        p.muted = True
        self.assertEqual(self._trame(p, 1), [0],
                         "une flamme mutee qui sort encore, c'est un accident")

    def test_les_canaux_voisins_sortent_leur_valeur(self):
        # Machine a etincelles 2 canaux : CH2 = duree. Il sortait 0 quoi qu'on
        # fasse, la branche s'arretait au debit.
        p = _machine("Machine a etincelles", ["Spark", "Speed"], level=40)
        p.channel_extras = {"Speed": 190}
        self.assertEqual(self._trame(p, 2), [102, 190])

    def test_canal_voisin_par_numero(self):
        p = _machine("Machine a etincelles", ["Spark", "Speed", "Mode"], level=0)
        p.channel_extras = {3: 77}
        self.assertEqual(self._trame(p, 3)[2], 77,
                         "le curseur par NUMERO doit atteindre le canal")

    def test_valeur_fixe_du_profil(self):
        p = _machine("Lance-flamme", ["Flame", "Speed"], level=0)
        p.channel_defaults = {"Speed": 200}
        self.assertEqual(self._trame(p, 2), [0, 200],
                         "une securite a valeur fixe se pose en channel_defaults")

    def test_le_mode_garde_sa_valeur_en_mute(self):
        # « Mode » a 0 vaut « automatique / sound-active » sur beaucoup de
        # machines : le remettre a zero en mute ferait partir l'appareil tout
        # seul, soit l'inverse de ce qu'on demande.
        p = _machine("Machine a etincelles", ["Spark", "Mode"], level=100)
        p.channel_extras = {"Mode": 130}
        p.muted = True
        self.assertEqual(self._trame(p, 2), [0, 130])

    def test_aucune_couleur_sur_une_machine(self):
        # La branche machine court-circuite toute la mecanique de couleur : un
        # canal R sur une machine ne doit pas se mettre a vivre sa vie.
        p = _machine("Machine a etincelles", ["Spark", "Speed"], level=100)
        from PySide6.QtGui import QColor
        p.set_color(QColor(255, 0, 0))
        self.assertEqual(self._trame(p, 2), [255, 0])


class Classement(unittest.TestCase):
    """Type contre groupe : c'est le type qui decide."""

    def test_les_quatre_types_sont_des_machines(self):
        for t in ("Machine a fumee", "Machine a brouillard",
                  "Machine a etincelles", "Lance-flamme"):
            self.assertIn(t, FX_MACHINE_TYPES)
            self.assertTrue(fixture_is_fx_machine(_machine(t, ["Smoke"])))

    def test_une_machine_rangee_dans_face_reste_une_machine(self):
        p = _machine("Lance-flamme", ["Flame"], group="face")
        self.assertTrue(fixture_is_fx_machine(p),
                        "le groupe n'est pas une preuve : une flamme partie sur "
                        "un effet de couleur ne se rattrape pas")

    def test_le_groupe_fumee_reste_un_second_filet(self):
        # Les plans d'avant ces types rangent leurs machines dans « fumee ».
        p = Projector("fumee", name="vieille machine", fixture_type="PAR LED")
        self.assertTrue(fixture_is_fx_machine(p))

    def test_un_par_led_n_est_pas_une_machine(self):
        p = Projector("face", name="PAR", fixture_type="PAR LED")
        self.assertFalse(fixture_is_fx_machine(p))
        self.assertFalse(fixture_is_pyro(p))

    def test_pyro_contre_atmosphere(self):
        self.assertEqual(
            FX_MACHINE_PYRO_TYPES,
            frozenset({"Machine a etincelles", "Lance-flamme"}),
            "le noir general epargne l'atmosphere et coupe le pyro")
        self.assertTrue(fixture_is_pyro(_machine("Lance-flamme", ["Flame"])))
        self.assertFalse(fixture_is_pyro(_machine("Machine a fumee", ["Smoke"])))

    def test_genre_envoye_a_la_3d(self):
        attendu = {"Machine a fumee": "fog", "Machine a brouillard": "haze",
                   "Machine a etincelles": "spark", "Lance-flamme": "flame"}
        for t, k in attendu.items():
            self.assertEqual(fixture_machine_kind(_machine(t, ["Smoke"])), k)
        self.assertIsNone(fixture_machine_kind(
            Projector("face", name="PAR", fixture_type="PAR LED")))

    def test_canal_de_sortie_lu_dans_le_profil(self):
        self.assertEqual(
            fixture_output_channel(_machine("Lance-flamme", ["Flame", "Speed"])),
            "Flame")
        self.assertIsNone(fixture_output_channel(
            _machine("PAR LED", ["R", "G", "B"])))


class ProfilsEtBibliotheque(unittest.TestCase):

    def test_les_canaux_existent(self):
        for c in ("Spark", "Flame"):
            self.assertIn(c, CHANNEL_TYPES)

    def test_profils_generiques(self):
        attendu = {
            "1CH_ETINCELLE": 1, "2CH_ETINCELLE": 2, "3CH_ETINCELLE": 3,
            "1CH_FLAMME": 1, "2CH_FLAMME": 2, "3CH_FLAMME": 3,
            "1CH_BROUILLARD": 1, "2CH_BROUILLARD": 2,
        }
        for nom, n in attendu.items():
            self.assertIn(nom, DMX_PROFILES)
            self.assertEqual(len(DMX_PROFILES[nom]), n)

    def test_aucune_machine_nommee_dans_la_bibliotheque(self):
        # Choix assume : les fabricants n'ont aucune convention commune sur ces
        # machines. Une fixture nommee dont les canaux sont faux est pire que
        # pas de fixture du tout.
        for f in builtin_fixtures.BUILTIN_FIXTURES:
            if f["fixture_type"] in ("Machine a etincelles", "Lance-flamme"):
                self.assertEqual(f["manufacturer"], "Générique", f["name"])

    def test_les_hazers_ont_quitte_la_machine_a_fumee(self):
        hazers = [f for f in builtin_fixtures.BUILTIN_FIXTURES
                  if "Hazer" in f["name"] or "Amhaze" in f["name"]]
        self.assertTrue(hazers, "la bibliotheque doit contenir des hazers")
        for f in hazers:
            self.assertEqual(f["fixture_type"], "Machine a brouillard", f["name"])


class ImportDePatch(unittest.TestCase):

    def test_type_devine_depuis_les_canaux(self):
        self.assertEqual(patch_import.type_from_profile(["Spark"]),
                         "Machine a etincelles")
        self.assertEqual(patch_import.type_from_profile(["Flame", "Speed"]),
                         "Lance-flamme")

    def test_les_nouveaux_types_sont_acceptes(self):
        for t in ("Machine a brouillard", "Machine a etincelles", "Lance-flamme"):
            self.assertIn(t, patch_import.FIXTURE_TYPES)

    def test_alias_courants(self):
        for brut, attendu in (("hazer", "Machine a brouillard"),
                              ("Sparkular", "Machine a etincelles"),
                              ("flamme", "Lance-flamme"),
                              ("smoke", "Machine a fumee")):
            self.assertEqual(patch_import.normalize_type(brut), attendu, brut)


if __name__ == "__main__":
    unittest.main(verbosity=2)
