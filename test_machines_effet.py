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
  * les hazers de la bibliotheque ont quitte « Machine a fumee » ;
  * les machines QLC+ ont un canal de sortie : QLC+ n'a pas de groupe
    « fumee », le debit arrivait en Effect/Intensity et AUCUNE des 57 machines
    n'avait de canal Smoke — debit mort (Stairville AFH-600, Discord
    16/10/2026). Un show deja patche est repris au patch ; une memoire pilote
    le debit d'une machine meme notee noire.

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
                  fixture_machine_kind, fixture_output_channel,
                  fix_machine_profile)
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


class CanalDeSortieRetrouve(unittest.TestCase):
    """Une machine sans Smoke/Spark/Flame a un debit mort : on le retrouve."""

    def test_canal_unique_sans_nom(self):
        self.assertEqual(fix_machine_profile("Machine a fumee", ["Effects"]),
                         ["Smoke"])
        self.assertEqual(fix_machine_profile("Machine a etincelles", ["Dim"]),
                         ["Spark"])

    def test_noms_de_canaux(self):
        self.assertEqual(fix_machine_profile(
            "Machine a brouillard", ["Effects", "Effects"],
            ["Fan speed", "Volume control"]), ["Fan", "Smoke"])
        # La LED d'une machine RGB garde son dimmer.
        self.assertEqual(fix_machine_profile(
            "Machine a fumee", ["Effects", "Dim", "R"], ["Fog", "Dimmer", "Red"]),
            ["Smoke", "Dim", "R"])

    def test_on_ne_devine_pas(self):
        # Plusieurs canaux sans nom : ambigu.
        self.assertEqual(fix_machine_profile("Machine a fumee",
                                             ["Effects", "Effects"]),
                         ["Effects", "Effects"])
        # Machine a minuterie : duree + intervalle, pas de debit.
        self.assertEqual(fix_machine_profile("Machine a fumee", ["Strobe", "Speed"],
                                             ["Duration", "Interval"]),
                         ["Strobe", "Speed"])
        self.assertEqual(fix_machine_profile("PAR LED", ["Dim"]), ["Dim"])
        self.assertEqual(fix_machine_profile("Machine a fumee", ["Smoke", "Fan"]),
                         ["Smoke", "Fan"])

    def test_bibliotheque_qlcplus(self):
        import json
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fixtures_qlcplus.json"), encoding="utf-8") as f:
            lib = json.load(f)
        sans = []
        for fx in lib:
            if fx["fixture_type"] not in FX_MACHINE_TYPES:
                continue
            for m in fx["modes"]:
                if not any(c in m["channels"] for c in ("Smoke", "Spark", "Flame")):
                    sans.append((fx["model"], m["name"]))
                if fx["model"] == "AFH-600":
                    self.assertEqual(m["channels"], ["Smoke"])
        # Seules restent les machines a minuterie / sans debit identifiable.
        self.assertLessEqual(len(sans), 3, sans)

    def test_import_qlcplus(self):
        from fixture_parser import parse_qlcplus_xml
        xml = b"""<?xml version="1.0"?>
<FixtureDefinition xmlns="http://www.qlcplus.org/FixtureDefinition">
 <Manufacturer>Stairville</Manufacturer><Model>AFH-600</Model><Type>Smoke</Type>
 <Channel Name="Haze Intensity"><Group Byte="0">Effect</Group></Channel>
 <Mode Name="DMX"><Channel Number="0">Haze Intensity</Channel></Mode>
</FixtureDefinition>"""
        fx = parse_qlcplus_xml(xml)
        self.assertEqual(fx["modes"][0]["profile"], ["Smoke"])

    def test_debit_en_sortie(self):
        p = _machine("Machine a fumee", ["Smoke"], level=60)
        dmx = ArtNetDMX()
        dmx.set_projector_patch("face_0", [1], 0, p.dmx_profile)
        dmx.update_from_projectors([p])
        self.assertEqual(dmx.get_channel(1), 153)

    def test_show_deja_patche_repris(self):
        import main_window as mw

        class Faux:
            _rebuild_dmx_patch = mw.MainWindow._rebuild_dmx_patch
            def save_dmx_patch_config(self):
                pass

        w = Faux()
        w.dmx = ArtNetDMX()
        p = _machine("Machine a fumee", ["Effects"])
        p.start_address = 1
        w.projectors = [p]
        w._rebuild_dmx_patch()
        self.assertEqual(p.dmx_profile, ["Smoke"])
        self.assertEqual(w.dmx.projector_profiles["face_0"], ["Smoke"])

    def test_memoire_pilote_le_debit_meme_notee_noire(self):
        import test_pad_memoire_comportement as t
        w = t.FauxWin(n_proj=2)
        m = w.projectors[0]
        m.dmx_profile = ["Smoke"]
        m.fixture_type = "Machine a fumee"
        w.memories[0][0] = {"cues": [{"label": "c", "projectors": [
            {"level": 80, "base_color": "#000000"},
            {"level": 0, "base_color": "#000000"}],
            "effect": {}, "duration": 0}], "loop": True}
        w.active_memory_pads = {0: 0}
        for fader, attendu in ((100, 80), (50, 40), (0, 0)):
            w.faders[0].value = fader
            w._recompute_memory_mix()
            self.assertEqual(m.level, attendu, fader)


if __name__ == "__main__":
    unittest.main(verbosity=2)
