"""
test_couche_canal.py — Editeur d'effets : la couche « Canal ».

Une couche d'effet ne savait piloter que des NOTIONS (Dimmer, R/V/B, Pan/Tilt,
Zoom, Gobo) : impossible de faire tourner le prisme d'une lyre, d'animer un
canal quelconque d'un laser, ou de declencher une machine a etincelles depuis
un effet. La couche « Canal » vise directement un canal du patch.

Ce qui est verrouille ici :
  * la liste des canaux vient du PATCH (par type, et par numero pour ce qu'un
    type ne suffit pas a designer : Unused d'un laser, types repetes, reglages
    d'une machine) ;
  * une machine n'est atteinte que par son canal de SORTIE — une couche
    « Speed » reglee pour des lyres ne touche pas la duree des etincelles ;
  * un canal designe par numero ne vise que CE modele (signature de profil) ;
  * la sortie DMX lit `effect_channels` avant les canaux forces, mais le mute
    passe devant — y compris sur une machine ;
  * le moteur du show remplit la table, meme sans aucun projecteur « lumiere » ;
  * la sortie live de l'editeur pose ses canaux le temps d'une frame puis rend
    l'etat d'avant ;
  * le combo CANAL de l'editeur propose ces canaux et ecrit la couche.
"""

import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from projector import Projector
from artnet_dmx import ArtNetDMX
from core import (channel_layer_outputs, patch_channel_choices, profile_signature,
                  channel_layer_key, effect_channel_value)

LYRE  = ["Pan", "Tilt", "Dim", "ColorWheel", "Gobo1", "Prism", "PrismRot", "Speed"]
PAR   = ["R", "G", "B", "Dim"]
LASER = ["Mode", "Unused", "Unused", "Speed", "Unused"]
SPARK = ["Spark", "Speed"]


def _appareil(profile, group="face", name="App 1", ftype="PAR LED", labels=None):
    p = Projector(group, name=name, fixture_type=ftype)
    p.dmx_profile = list(profile)
    if labels:
        p.channel_labels = list(labels)
    return p


def _couche(**kw):
    d = {"attribute": "Canal", "forme": "Fixe", "speed": 50, "size": 100,
         "min_val": 0, "max_val": 100, "target_preset": "Tous"}
    d.update(kw)
    return d


class ListeDesCanaux(unittest.TestCase):

    def setUp(self):
        self.lyre  = _appareil(LYRE, name="Lyre 1", ftype="Moving Head")
        self.laser = _appareil(LASER, name="Laser 1", ftype="Laser",
                               labels=["Mode", "Rotation Z", "Taille", "Speed", "Couleur"])
        self.spark = _appareil(SPARK, group="fumee", name="Etincelles 1",
                               ftype="Machine a etincelles")
        self.choix = patch_channel_choices([self.lyre, self.laser, self.spark])
        self.cles  = {c["key"]: c for c in self.choix}

    def test_types_du_patch(self):
        for t in ("Prism", "PrismRot", "Gobo1", "Spark"):
            self.assertIn(f"T:{t}", self.cles)
        self.assertNotIn("T:Unused", self.cles)

    def test_canaux_du_laser_par_numero_avec_leur_nom(self):
        sig = profile_signature(LASER)
        c = self.cles.get(f"N:{sig}:2")
        self.assertIsNotNone(c)
        self.assertIn("Rotation Z", c["label"])
        self.assertIn("Laser", c["label"])

    def test_machine_reglages_par_numero_seulement(self):
        # « Speed » par type existe (lyre, laser) mais ne compte pas la machine
        self.assertEqual(self.cles["T:Speed"]["count"], 2)
        self.assertIn(f"N:{profile_signature(SPARK)}:2", self.cles)

    def test_pyro_signale(self):
        self.assertTrue(self.cles["T:Spark"]["pyro"])
        self.assertFalse(self.cles["T:Prism"]["pyro"])

    def test_canal_de_commande_signale(self):
        # « Mode » d'un laser : hors de sa plage DMX, l'appareil passe au noir
        self.assertTrue(self.cles["T:Mode"]["sensible"])
        self.assertFalse(self.cles["T:Prism"]["sensible"])


class CalculDesValeurs(unittest.TestCase):

    def test_prisme_sur_les_seules_lyres(self):
        lyre, par = _appareil(LYRE, ftype="Moving Head"), _appareil(PAR)
        out = channel_layer_outputs([_couche(channel_type="Prism", max_val=50)],
                                    [lyre, par], t=0.0)
        self.assertEqual(out[id(lyre)], {LYRE.index("Prism") + 1: 128})
        self.assertNotIn(id(par), out)

    def test_speed_ne_touche_pas_la_machine(self):
        lyre  = _appareil(LYRE, ftype="Moving Head")
        spark = _appareil(SPARK, ftype="Machine a etincelles")
        out = channel_layer_outputs([_couche(channel_type="Speed")], [lyre, spark], 0.0)
        self.assertIn(id(lyre), out)
        self.assertNotIn(id(spark), out)

    def test_spark_declenche_la_machine(self):
        spark = _appareil(SPARK, ftype="Machine a etincelles")
        out = channel_layer_outputs([_couche(channel_type="Spark")], [spark], 0.0)
        self.assertEqual(out[id(spark)], {1: 255})

    def test_numero_vise_un_seul_modele(self):
        laser = _appareil(LASER, ftype="Laser")
        autre = _appareil(["Mode", "Unused", "Dim"], ftype="Laser")
        couche = _couche(channel_num=2, channel_sig=profile_signature(LASER))
        out = channel_layer_outputs([couche], [laser, autre], 0.0)
        self.assertEqual(out, {id(laser): {2: 255}})

    def test_chenillard_compte_parmi_ceux_qui_ont_le_canal(self):
        lyres = [_appareil(LYRE, ftype="Moving Head") for _ in range(3)]
        pars  = [_appareil(PAR) for _ in range(2)]
        rig = [pars[0], lyres[0], pars[1], lyres[1], lyres[2]]
        out = channel_layer_outputs([_couche(channel_type="Prism", forme="Un par un")],
                                    rig, t=0.0)
        n = LYRE.index("Prism") + 1
        self.assertEqual([out[id(l)][n] for l in lyres], [255, 0, 0])

    def test_cible_groupe(self):
        a = _appareil(LYRE, group="face", ftype="Moving Head")
        b = _appareil(LYRE, group="contre", ftype="Moving Head")
        out = channel_layer_outputs([_couche(channel_type="Prism", target_preset="C")],
                                    [a, b], 0.0)
        self.assertEqual(list(out), [id(b)])

    def test_htp_entre_deux_couches(self):
        lyre = _appareil(LYRE, ftype="Moving Head")
        out = channel_layer_outputs([_couche(channel_type="Prism", max_val=20),
                                     _couche(channel_type="Prism", max_val=60)],
                                    [lyre], 0.0)
        self.assertEqual(out[id(lyre)][LYRE.index("Prism") + 1], 153)

    def test_cle_de_couche(self):
        self.assertEqual(channel_layer_key({"channel_type": "Prism"}), "T:Prism")
        self.assertEqual(channel_layer_key({"channel_num": 3, "channel_sig": "ab"}), "N:ab:3")


class SortieDMX(unittest.TestCase):

    def _sortie(self, proj):
        nb = len(proj.dmx_profile)
        dmx = ArtNetDMX()
        dmx.set_projector_patch(f"{proj.group}_0", list(range(1, nb + 1)), 0,
                                profile=list(proj.dmx_profile))
        dmx.update_from_projectors([proj])
        return [dmx.get_channel(i) for i in range(1, nb + 1)]

    def test_effet_prime_sur_canal_force(self):
        lyre = _appareil(LYRE, ftype="Moving Head")
        n = LYRE.index("Prism") + 1
        lyre.channel_extras = {n: 40}
        lyre.effect_channels = {n: 200}
        self.assertEqual(self._sortie(lyre)[n - 1], 200)
        lyre.effect_channels = {}
        self.assertEqual(self._sortie(lyre)[n - 1], 40)

    def test_machine_suit_l_effet(self):
        spark = _appareil(SPARK, ftype="Machine a etincelles")
        spark.effect_channels = {1: 255, 2: 90}
        self.assertEqual(self._sortie(spark), [255, 90])

    def test_mute_passe_devant(self):
        spark = _appareil(SPARK, ftype="Machine a etincelles")
        spark.effect_channels = {1: 255}
        spark.muted = True
        self.assertEqual(self._sortie(spark)[0], 0)
        lyre = _appareil(LYRE, ftype="Moving Head")
        lyre.effect_channels = {LYRE.index("Prism") + 1: 255}
        lyre.muted = True
        self.assertEqual(self._sortie(lyre)[LYRE.index("Prism")], 0)

    def test_valeur_par_type_pour_la_3d(self):
        lyre = _appareil(LYRE, ftype="Moving Head")
        lyre.prism = 12
        self.assertEqual(effect_channel_value(lyre, "Prism", lyre.prism), 12)
        lyre.effect_channels = {LYRE.index("Prism") + 1: 99}
        self.assertEqual(effect_channel_value(lyre, "Prism", lyre.prism), 99)


class FauxShow:
    def __init__(self, projectors):
        from main_window import MainWindow
        self._run = MainWindow._update_effect_from_layers
        self.effect_speed     = 100
        self.effect_t0        = time.monotonic()
        self._effect_clock    = 0.0
        self._effect_clock_ts = None
        self.projectors       = projectors
        self._stacked_tick    = None

    def frame(self, cfg):
        self._run(self, cfg)


class MoteurDuShow(unittest.TestCase):

    def test_effet_qui_ne_vise_qu_une_machine(self):
        spark = _appareil(SPARK, ftype="Machine a etincelles")
        show = FauxShow([spark])
        show.frame({"name": "Tir", "layers": [_couche(channel_type="Spark")]})
        self.assertEqual(spark.effect_channels, {1: 255})


class SortieLiveEditeur(unittest.TestCase):

    def test_pose_puis_rend(self):
        from main_window import MainWindow
        lyre = _appareil(LYRE, ftype="Moving Head")
        lyre.effect_channels = {3: 10}

        class Faux:
            projectors = [lyre]
            _editor_live_overrides = None
            _editor_live_channels = {id(lyre): {6: 250}}

        saved = MainWindow._apply_editor_live_overrides(Faux)
        self.assertEqual(lyre.effect_channels, {3: 10, 6: 250})
        MainWindow._restore_editor_live_overrides(saved)
        self.assertEqual(lyre.effect_channels, {3: 10})


class ComboEditeur(unittest.TestCase):

    def test_choisir_un_canal_du_patch(self):
        from effect_editor import EffectLayer, LayerRow
        lyre = _appareil(LYRE, name="Lyre 1", ftype="Moving Head")
        layer = EffectLayer()
        row = LayerRow(layer, projectors=[lyre])
        cb = row._attr_cb
        i = next(i for i in range(cb.count())
                 if isinstance(cb.itemData(i), dict) and cb.itemData(i)["key"] == "T:Prism")
        cb.setCurrentIndex(i)
        self.assertEqual(layer.attribute, "Canal")
        self.assertEqual(layer.channel_type, "Prism")
        # aller-retour par le dict sauvegarde, puis nouvelle ligne
        relu = EffectLayer.from_dict(layer.to_dict())
        row2 = LayerRow(relu, projectors=[lyre])
        self.assertEqual(row2._attr_cb.itemData(row2._attr_cb.currentIndex())["key"], "T:Prism")
        # retour a un canal classique
        cb.setCurrentIndex(cb.findText("Dimmer"))
        self.assertEqual(layer.attribute, "Dimmer")

    def test_canal_absent_du_patch_conserve(self):
        from effect_editor import EffectLayer, LayerRow
        layer = EffectLayer.from_dict(_couche(channel_type="Prism"))
        row = LayerRow(layer, projectors=[_appareil(PAR)])
        d = row._attr_cb.itemData(row._attr_cb.currentIndex())
        self.assertEqual(d["key"], "T:Prism")


class StrobeAffichePlans(unittest.TestCase):
    """Couche « Canal » sur Strobe : le rig strobait, les plans 2D/3D non."""

    def test_couche_strobe_visible_par_les_plans(self):
        from core import displayed_strobe_speed
        par = _appareil(["R", "G", "B", "Dim", "Strobe"])
        lyre = _appareil(["Pan", "Tilt", "Dim", "Shutter"], name="Lyre")
        # le « Strobe Rapide » de la bibliotheque : Canal / Fixe / Strobe / 93 %
        out = channel_layer_outputs([_couche(channel_type="Strobe", size=93)],
                                    [par, lyre], 0.0)
        par.effect_channels = out[id(par)]
        self.assertNotIn(id(lyre), out)          # pas de canal Strobe : rien
        self.assertEqual(displayed_strobe_speed(lyre), 0)
        vitesse = displayed_strobe_speed(par)
        self.assertGreater(vitesse, 85)
        # meme valeur que ce qui part sur le fil, relue a l'envers
        self.assertAlmostEqual(16 + vitesse / 100 * 234, par.effect_channels[5], delta=2)

    def test_couche_prime_sur_strobe_manuel(self):
        from core import displayed_strobe_speed
        par = _appareil(["R", "G", "B", "Dim", "Strobe"])
        par.strobe_speed = 40
        self.assertEqual(displayed_strobe_speed(par), 40)
        par.effect_channels = {5: 0}             # la couche ferme le strobe
        self.assertEqual(displayed_strobe_speed(par), 0)


if __name__ == "__main__":
    unittest.main()
