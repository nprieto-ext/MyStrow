"""
test_dmx_in.py — Entree DMX (artnet_input.py + dmx_in_link.py).

Tout se teste sans reseau ni pupitre : les trames sont fabriquees a la main et
poussees dans `ArtNetReceiver.feed()`, et la fenetre MyStrow est remplacee par
un mouchard qui enregistre les appels. C'est exactement la raison d'etre de la
separation reception / liaison.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import artnet_input as ai
import dmx_in_link as dil

_app = QApplication.instance() or QApplication(sys.argv)


def artdmx(universe=0, values=None, seq=1, length=512):
    """Fabrique une trame ArtDmx, octet pour octet comme un vrai pupitre."""
    payload = bytearray(length)
    for canal, valeur in (values or {}).items():
        payload[canal - 1] = valeur
    return (b"Art-Net\x00"
            + b"\x00\x50"
            + b"\x00\x0e"
            + bytes([seq])
            + b"\x00"
            + bytes([universe & 0xFF, (universe >> 8) & 0x7F])
            + bytes([(length >> 8) & 0xFF, length & 0xFF])
            + bytes(payload))


class FauxFader:
    def __init__(self, value=0):
        self.value = value

    def update(self):
        pass


def _page(prefixe):
    """8 slots de layout, comme AKAI_BANK_PRESETS."""
    return [{"type": "group", "group": chr(ord("A") + i), "label": f"{prefixe}{i + 1}"}
            for i in range(8)]


class FausseFenetre:
    """Mouchard : enregistre ce que la liaison appelle, sans rien faire.

    Page 1 : les groupes A a H. Page 2 : MEM 1, FX 1, PLAY, puis D a H. C'est ce
    qui permet de verifier les deux chemins — la cible est a l'ecran, ou pas.
    """

    def __init__(self, page_active=0):
        self.faders = {i: FauxFader(0) for i in range(9)}
        self._bank_pages = [_page("P1-"), _page("P2-"), _page("P3-")]
        self._bank_pages[1][0] = {"type": "memory", "mem_col": 0, "label": "MEM 1"}
        self._bank_pages[1][1] = {"type": "fx", "fx_col": 0, "label": "FX 1"}
        self._bank_pages[1][2] = {"type": "play", "label": "PLAY"}
        self._bank_page_idx = page_active

        self.faders_recus = []      # (index, velocite 0-127)
        self.offpage_recus = []     # (label du slot, niveau 0-100)
        self.mem_recus = []         # (mem_col, niveau 0-100)

    @property
    def _fader_map(self):
        return self._bank_pages[self._bank_page_idx]

    def on_midi_fader(self, index, velocite):
        self.faders_recus.append((index, velocite))
        # On imite le vrai comportement : le fader a l'ecran suit.
        self.faders[index].value = int(velocite / 127.0 * 100)

    def apply_slot_level_offpage(self, slot, value):
        self.offpage_recus.append((slot.get("label"), value))
        return slot.get("type") in ("group", "fx", "play")

    def apply_memory_level(self, mem_col, value):
        self.mem_recus.append((mem_col, value))
        return True


# ── protocole ───────────────────────────────────────────────────────────────

class TestParseArtDmx(unittest.TestCase):

    def test_trame_valide(self):
        uni, payload = ai.parse_artdmx(artdmx(universe=3, values={1: 255, 12: 64}))
        self.assertEqual(uni, 3)
        self.assertEqual(payload[0], 255)
        self.assertEqual(payload[11], 64)

    def test_univers_au_dela_de_255_utilise_le_champ_net(self):
        uni, _ = ai.parse_artdmx(artdmx(universe=260))
        self.assertEqual(uni, 260)

    def test_compatible_avec_les_trames_emises_par_mystrow(self):
        """Le decodeur doit lire ce que notre propre encodeur produit —
        c'est ce qui garantit qu'un MyStrow peut en piloter un autre."""
        import artnet_dmx
        dmx = artnet_dmx.ArtNetDMX.__new__(artnet_dmx.ArtNetDMX)
        dmx.dmx_data = [bytearray(512) for _ in range(4)]
        dmx.dmx_data[0][0] = 200
        paquet = artnet_dmx.ArtNetDMX._build_artnet_packet(dmx, 5, 42, data_universe=0)
        uni, payload = ai.parse_artdmx(paquet)
        self.assertEqual(uni, 5)
        self.assertEqual(payload[0], 200)

    def test_rejette_ce_qui_n_est_pas_de_l_artdmx(self):
        # ArtPoll (0x2000), ArtPollReply (0x2100), bruit, trame tronquee
        artpoll = b"Art-Net\x00" + b"\x00\x20" + b"\x00\x0e" + bytes(6)
        self.assertIsNone(ai.parse_artdmx(artpoll))
        self.assertIsNone(ai.parse_artdmx(b"Art-Net\x00" + b"\x00\x21" + bytes(20)))
        self.assertIsNone(ai.parse_artdmx(b"n'importe quoi"))
        self.assertIsNone(ai.parse_artdmx(b""))
        self.assertIsNone(ai.parse_artdmx(artdmx()[:12]))

    def test_longueur_nulle_rejetee(self):
        self.assertIsNone(ai.parse_artdmx(artdmx(length=0)))


class TestSequence(unittest.TestCase):

    def test_sequence_zero_desactive_le_controle(self):
        self.assertTrue(ai.sequence_is_newer(0, 200))
        self.assertTrue(ai.sequence_is_newer(5, 0))

    def test_accepte_la_suivante_refuse_la_precedente(self):
        self.assertTrue(ai.sequence_is_newer(11, 10))
        self.assertFalse(ai.sequence_is_newer(9, 10))
        self.assertFalse(ai.sequence_is_newer(10, 10))

    def test_passage_par_zero(self):
        """255 -> 1 est une suite normale, pas un retour en arriere."""
        self.assertTrue(ai.sequence_is_newer(1, 255))
        self.assertFalse(ai.sequence_is_newer(250, 3))


class TestReceiver(unittest.TestCase):

    def setUp(self):
        self.rx = ai.ArtNetReceiver()

    def test_range_la_trame_et_compte(self):
        self.assertEqual(self.rx.feed(artdmx(values={5: 128}), "2.0.0.20"), 0)
        compteur, frame = self.rx.snapshot(0)
        self.assertEqual(compteur, 1)
        self.assertEqual(frame[4], 128)
        self.assertEqual(len(frame), 512)

    def test_univers_non_recu(self):
        self.assertEqual(self.rx.snapshot(7), (0, None))

    def test_ignore_nos_propres_ips(self):
        """Le larsen : notre sortie qui revient en entree."""
        self.rx.ignore_ips = {"192.168.1.10"}
        self.assertIsNone(self.rx.feed(artdmx(values={1: 255}), "192.168.1.10"))
        self.assertEqual(self.rx.snapshot(0), (0, None))
        self.assertEqual(self.rx.feed(artdmx(values={1: 255}), "2.0.0.20"), 0)

    def test_trame_en_retard_ignoree(self):
        self.rx.feed(artdmx(values={1: 200}, seq=10), "2.0.0.20")
        self.rx.feed(artdmx(values={1: 50}, seq=8), "2.0.0.20")
        _c, frame = self.rx.snapshot(0)
        self.assertEqual(frame[0], 200, "une trame plus ancienne ne doit pas ecraser")

    def test_trame_courte_completee_a_512(self):
        """Un pupitre peut n'emettre que ses 24 premiers canaux."""
        self.rx.feed(artdmx(values={3: 99}, length=24), "2.0.0.20")
        _c, frame = self.rx.snapshot(0)
        self.assertEqual(len(frame), 512)
        self.assertEqual(frame[2], 99)
        self.assertEqual(frame[400], 0)

    def test_univers_vus_et_sources(self):
        self.rx.feed(artdmx(universe=1), "2.0.0.20")
        self.rx.feed(artdmx(universe=4), "2.0.0.21")
        self.assertEqual(self.rx.universes_seen(), [1, 4])
        self.assertEqual(self.rx.sources(), ["2.0.0.20", "2.0.0.21"])
        self.assertTrue(self.rx.is_receiving())


# ── le vocabulaire des cibles ───────────────────────────────────────────────

class TestCibles(unittest.TestCase):

    def test_toutes_les_cibles(self):
        toutes = dil.cibles()
        self.assertEqual(toutes[:8], list("ABCDEFGH"))
        self.assertIn("MEM 1", toutes)
        self.assertIn("MEM 99", toutes)
        self.assertNotIn("MEM 100", toutes)
        self.assertIn("FX 8", toutes)
        self.assertEqual(toutes[-2:], [dil.CIBLE_PLAY, dil.CIBLE_VITESSE])
        self.assertEqual(len(toutes), 8 + 99 + 8 + 2)

    def test_est_une_cible(self):
        self.assertTrue(dil.is_cible("A"))
        self.assertTrue(dil.is_cible("MEM 99"))
        self.assertFalse(dil.is_cible("MEM 0"))
        self.assertFalse(dil.is_cible("POS 1"), "une position n'est pas pilotable")
        self.assertFalse(dil.is_cible(""))

    def test_colonne_memoire(self):
        self.assertEqual(dil.mem_col_for("MEM 1"), 0)
        self.assertEqual(dil.mem_col_for("MEM 99"), 98)
        self.assertIsNone(dil.mem_col_for("MEM 0"))
        self.assertIsNone(dil.mem_col_for("A"))
        self.assertIsNone(dil.mem_col_for(dil.CIBLE_VITESSE))
        self.assertIsNone(dil.mem_col_for("MEM x"))

    def test_cible_d_un_slot_de_layout(self):
        self.assertEqual(dil.option_for_slot({"type": "group", "group": "C"}), "C")
        self.assertEqual(dil.option_for_slot({"type": "memory", "mem_col": 11}), "MEM 12")
        self.assertEqual(dil.option_for_slot({"type": "fx", "fx_col": 0}), "FX 1")
        self.assertEqual(dil.option_for_slot({"type": "play"}), "PLAY")
        self.assertEqual(dil.option_for_slot({"type": "pos", "pos_col": 0}), "")
        self.assertEqual(dil.option_for_slot(None), "")

    def test_cible_d_un_vieux_slot_par_nom_de_groupe(self):
        """Ancien format {"groups": ["face"]} : la lettre doit se retrouver."""
        self.assertEqual(dil.option_for_slot({"type": "group", "groups": ["face"]}), "A")
        self.assertEqual(dil.option_for_slot({"type": "group", "groups": ["douche2"]}), "E")

    def test_slot_synthetique_pour_le_hors_page(self):
        self.assertEqual(dil.slot_for_option("B"),
                         {"type": "group", "group": "B", "label": "B"})
        self.assertEqual(dil.slot_for_option("FX 3")["fx_col"], 2)
        self.assertEqual(dil.slot_for_option("PLAY")["type"], "play")
        self.assertIsNone(dil.slot_for_option("MEM 1"), "les memoires ont leur porte")
        self.assertIsNone(dil.slot_for_option(dil.CIBLE_VITESSE))


class TestNormalisationDuPatch(unittest.TestCase):

    def test_jette_l_invalide(self):
        patch = dil.normalize_patch([
            {"channel": 1, "slot": "A"},
            {"channel": 0, "slot": "B"},            # canal hors univers
            {"channel": 513, "slot": "C"},          # idem
            {"channel": 4, "slot": "POS 1"},        # cible non pilotable
            {"channel": 5, "slot": "n'importe quoi"},
            {"channel": "x", "slot": "A"},
            "pas un dictionnaire",
        ])
        self.assertEqual(patch, {1: "A"})

    def test_accepte_les_minuscules(self):
        self.assertEqual(dil.normalize_patch([{"channel": 3, "slot": "mem 2"}]),
                         {3: "MEM 2"})

    def test_un_canal_ne_pilote_qu_une_cible(self):
        patch = dil.normalize_patch([{"channel": 7, "slot": "A"},
                                     {"channel": 7, "slot": "MEM 4"}])
        self.assertEqual(patch, {7: "MEM 4"})

    def test_accepte_un_dictionnaire(self):
        self.assertEqual(dil.normalize_patch({"12": "A"}), {12: "A"})

    def test_config_absente_ou_abimee(self):
        self.assertEqual(dil.normalize_patch(None), {})
        self.assertEqual(dil.normalize_patch("abime"), {})


class TestMigrationDepuisLesPages(unittest.TestCase):
    """Un reglage de la version a pages doit se retrouver dans la table plate."""

    def setUp(self):
        self.fenetre = FausseFenetre()

    def test_mode_libre_resout_la_tranche_en_cible(self):
        cfg = {"mode": "libre", "assignments": [
            {"channel": 5, "type": "tranche", "page": 1, "tranche": 0},   # MEM 1
            {"channel": 6, "type": "tranche", "page": 0, "tranche": 2},   # groupe C
            {"channel": 7, "type": "speed"},
        ]}
        self.assertEqual(dil.patch_from_legacy(cfg, self.fenetre),
                         {5: "MEM 1", 6: "C", 7: dil.CIBLE_VITESSE})

    def test_mode_patch_reprend_la_premiere_page(self):
        patch = dil.patch_from_legacy({"mode": "patch", "start_channel": 10},
                                      self.fenetre)
        self.assertEqual(patch[10], "A")
        self.assertEqual(patch[17], "H")
        self.assertEqual(patch[10 + 8 * 3], dil.CIBLE_VITESSE,
                         "la vitesse etait le dernier canal du patch")
        self.assertEqual(len(patch), 9)

    def test_reglage_illisible(self):
        self.assertEqual(dil.patch_from_legacy(None, self.fenetre), {})
        self.assertEqual(dil.patch_from_legacy({"mode": "patch"}, self.fenetre), {})


class TestPatchParDefaut(unittest.TestCase):
    """Un pupitre branche pour la premiere fois doit faire quelque chose."""

    def test_les_groupes_d_abord_puis_les_memoires(self):
        patch = dil.default_patch()
        self.assertEqual(patch[1], "A")
        self.assertEqual(patch[7], "G")
        self.assertNotIn("H", patch.values(), "le 8e groupe reste libre")
        self.assertEqual(patch[8], "MEM 1")
        self.assertEqual(patch[106], "MEM 99")
        self.assertEqual(len(patch), 7 + 99)
        self.assertNotIn(107, patch)

    def test_une_liaison_neuve_est_deja_patchee(self):
        link = dil.DmxInLink(FausseFenetre())
        self.assertEqual(link.patch, dil.default_patch())
        link.stop()

    def test_le_disque_gagne_toujours_meme_vide(self):
        """« Tout effacer » doit tenir apres fermeture : sinon le patch d'usine
        reviendrait a chaque ouverture, et le bouton ne servirait a rien."""
        link = dil.DmxInLink(FausseFenetre())
        link.from_config({"enabled": False, "patch": []})
        self.assertEqual(link.patch, {})
        link.stop()

    def test_retour_au_patch_d_usine(self):
        link = dil.DmxInLink(FausseFenetre())
        link.clear_patch()
        link.reset_patch()
        self.assertEqual(link.patch, dil.default_patch())
        link.stop()

    def test_vieille_config_sans_rien_a_recuperer(self):
        link = dil.DmxInLink(FausseFenetre())
        link.from_config({"mode": "patch"})      # pas d'adresse de depart
        self.assertEqual(link.patch, dil.default_patch(),
                         "mieux vaut le patch d'usine qu'une table vide")
        link.stop()


class TestFonctionsPures(unittest.TestCase):

    def test_conversion_dmx_vers_niveau(self):
        self.assertEqual(dil.dmx_to_level(0), 0)
        self.assertEqual(dil.dmx_to_level(255), 100)
        self.assertEqual(dil.dmx_to_level(128), 50)
        self.assertEqual(dil.dmx_to_level(999), 100)

    def test_aller_retour_niveau_velocite_sans_perte(self):
        """`on_midi_fader` retronque avec int() : l'arrondi doit etre AU-DESSUS."""
        for niveau in range(101):
            velocite = dil.level_to_velocity(niveau)
            self.assertLessEqual(velocite, 127)
            self.assertGreaterEqual(int(velocite / 127 * 100), niveau - 1)
        self.assertGreater(dil.level_to_velocity(1), 1,
                           "1 % ne doit pas retomber a 0 apres troncature")


# ── la liaison ──────────────────────────────────────────────────────────────

class TestLink(unittest.TestCase):

    def setUp(self):
        self.fenetre = FausseFenetre(page_active=0)
        self.link = dil.DmxInLink(self.fenetre)
        self.link.enabled = True
        self.link.universe = 0        # les trames de test partent sur 0
        # Table vide : le patch d'usine (canal N -> MEM N) a sa classe a lui.
        self.link.clear_patch()

    def tearDown(self):
        self.link.stop()

    def pousser(self, values, seq=1):
        self.link.receiver.feed(artdmx(values=values, seq=seq), "2.0.0.20")
        self.link._tick()

    # ── patch ───────────────────────────────────────────────────────────────

    def test_patcher_et_depatcher(self):
        self.link.set_target(3, "MEM 4")
        self.assertEqual(self.link.target_for(3), "MEM 4")
        self.link.set_target(3, "")
        self.assertEqual(self.link.target_for(3), "")
        self.assertEqual(self.link.patch, {})

    def test_canal_hors_univers_refuse(self):
        self.link.set_target(0, "A")
        self.link.set_target(513, "A")
        self.assertEqual(self.link.patch, {})

    def test_watched_est_trie_par_canal(self):
        self.link.set_target(12, "B")
        self.link.set_target(3, "A")
        self.assertEqual(list(self.link.watched()), [(3, "A"), (12, "B")])

    def test_tout_effacer(self):
        self.link.set_target(3, "A")
        self.link.clear_patch()
        self.assertEqual(self.link.patch, {})

    # ── ou est la cible ─────────────────────────────────────────────────────

    def test_cible_de_la_page_affichee(self):
        self.assertEqual(self.link.visible_fader_for("A"), 0)
        self.assertEqual(self.link.visible_fader_for("H"), 7)
        self.assertIsNone(self.link.visible_fader_for("MEM 1"),
                          "MEM 1 est sur la page 2")

    def test_la_vitesse_n_appartient_a_aucune_page(self):
        self.assertEqual(self.link.visible_fader_for(dil.CIBLE_VITESSE),
                         dil.FADER_VITESSE)

    # ── premiere trame ──────────────────────────────────────────────────────

    def test_premiere_trame_ne_pilote_rien(self):
        self.link.set_target(1, "A")
        self.pousser({1: 255})
        self.assertEqual(self.fenetre.faders_recus, [],
                         "la premiere trame sert de reference")
        self.pousser({1: 128}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(0, 64)])

    # ── routage ─────────────────────────────────────────────────────────────

    def test_groupe_de_la_page_affichee_passe_par_le_midi(self):
        self.link.set_target(1, "A")
        self.pousser({1: 0})
        self.pousser({1: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(0, 127)])
        self.assertEqual(self.fenetre.offpage_recus, [])

    def test_groupe_absent_de_la_page_passe_hors_page(self):
        self.fenetre._bank_page_idx = 1      # page 2 : A, B, C n'y sont plus
        self.link.set_target(1, "A")
        self.pousser({1: 0})
        self.pousser({1: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [])
        self.assertEqual(self.fenetre.offpage_recus, [("A", 100)])

    def test_memoire_toujours_par_sa_propre_porte(self):
        """Visible ou non, une MEM passe par `apply_memory_level` : un seul writer."""
        self.link.set_target(1, "MEM 1")
        self.pousser({1: 0})
        self.pousser({1: 255}, seq=2)
        self.assertEqual(self.fenetre.mem_recus, [(0, 100)])
        self.assertEqual(self.fenetre.faders_recus, [])

        self.fenetre._bank_page_idx = 1      # MEM 1 est maintenant a l'ecran
        self.link._reset_state()
        self.fenetre.mem_recus.clear()
        self.pousser({1: 0}, seq=3)
        self.pousser({1: 128}, seq=4)
        self.assertEqual(self.fenetre.mem_recus, [(0, 50)])
        self.assertEqual(self.fenetre.faders_recus, [],
                         "meme a l'ecran, pas de second chemin")

    def test_memoire_hors_des_99_colonnes_ignoree(self):
        self.link.set_target(1, "MEM 99")
        self.pousser({1: 0})
        self.pousser({1: 255}, seq=2)
        self.assertEqual(self.fenetre.mem_recus, [(98, 100)])

    def test_colonne_fx(self):
        self.link.set_target(2, "FX 1")
        self.pousser({2: 0})
        self.pousser({2: 255}, seq=2)
        self.assertEqual(self.fenetre.offpage_recus, [("FX 1", 100)],
                         "FX 1 est sur la page 2")

    def test_volume_du_lecteur(self):
        self.link.set_target(2, dil.CIBLE_PLAY)
        self.pousser({2: 0})
        self.pousser({2: 128}, seq=2)
        self.assertEqual(self.fenetre.offpage_recus, [("PLAY", 50)])

    def test_canal_de_vitesse_pilote_le_fader_9(self):
        self.link.set_target(30, dil.CIBLE_VITESSE)
        self.pousser({30: 0})
        self.pousser({30: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(dil.FADER_VITESSE, 127)])

    def test_les_deux_chemins_coexistent_dans_la_meme_trame(self):
        self.link.set_target(1, "A")          # a l'ecran
        self.link.set_target(2, "MEM 3")      # pas a l'ecran
        self.pousser({1: 0, 2: 0})
        self.pousser({1: 255, 2: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(0, 127)])
        self.assertEqual(self.fenetre.mem_recus, [(2, 100)])

    def test_changer_de_page_change_le_routage(self):
        self.link.set_target(1, "A")
        self.pousser({1: 0})
        self.pousser({1: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(0, 127)])
        self.fenetre._bank_page_idx = 1
        self.pousser({1: 128}, seq=3)
        self.assertEqual(self.fenetre.offpage_recus, [("A", 50)],
                         "la meme cible, par l'autre chemin")

    def test_canal_immobile_ne_renvoie_rien(self):
        """40 trames/s : sans ce filtre le pupitre ecraserait l'AKAI en permanence."""
        self.link.set_target(1, "A")
        self.pousser({1: 0})
        self.pousser({1: 255}, seq=2)
        self.pousser({1: 255}, seq=3)
        self.assertEqual(self.fenetre.faders_recus, [(0, 127)])

    def test_canal_non_patche_ignore(self):
        self.link.set_target(1, "A")
        self.pousser({1: 0, 2: 0})
        self.pousser({1: 0, 2: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [])
        self.assertEqual(self.fenetre.offpage_recus, [])

    def test_canal_512_sans_debordement(self):
        self.link.set_target(512, "A")
        self.pousser({512: 0})
        self.pousser({512: 255}, seq=2)      # ne doit pas lever IndexError
        self.assertEqual(self.fenetre.faders_recus, [(0, 127)])

    def test_changer_le_patch_oublie_l_etat(self):
        self.link.set_target(1, "A")
        self.pousser({1: 0})
        self.link.set_target(2, "B")         # le patch a change
        self.pousser({1: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [],
                         "la trame suivante redevient une reference")

    # ── LTP ─────────────────────────────────────────────────────────────────

    def test_le_pupitre_gagne_toujours(self):
        """LTP, sans reglage : le dernier qui bouge gagne, meme vers le bas."""
        self.link.set_target(1, "A")
        self.fenetre.faders[0].value = 60      # l'AKAI etait a 60 %
        self.pousser({1: 0})
        self.pousser({1: 64}, seq=2)           # 25 % cote pupitre
        self.assertEqual(self.fenetre.faders_recus,
                         [(0, dil.level_to_velocity(25))])

    def test_le_pupitre_gagne_aussi_sur_une_memoire(self):
        self.fenetre._bank_page_idx = 1        # MEM 1 sur le fader 1
        self.link.set_target(1, "MEM 1")
        self.fenetre.faders[0].value = 60
        self.pousser({1: 0})
        self.pousser({1: 64}, seq=2)
        self.assertEqual(self.fenetre.mem_recus, [(0, 25)])

    # ── reception ───────────────────────────────────────────────────────────

    def test_mauvais_univers_ignore(self):
        self.link.set_target(1, "A")
        self.link.receiver.feed(artdmx(universe=7, values={1: 0}), "2.0.0.20")
        self.link._tick()
        self.link.receiver.feed(artdmx(universe=7, values={1: 255}, seq=2), "2.0.0.20")
        self.link._tick()
        self.assertEqual(self.fenetre.faders_recus, [])

    def test_univers_vu_ailleurs(self):
        """Remplace le reglage d'univers : on constate, et on propose de basculer."""
        self.link.universe = 5
        self.assertIsNone(self.link.other_universe_seen())
        self.link.receiver.feed(artdmx(universe=0, values={1: 10}), "2.0.0.20")
        self.assertEqual(self.link.other_universe_seen(), 0)
        self.link.universe = 0
        self.assertIsNone(self.link.other_universe_seen())

    def test_etat_lisible_sans_reception(self):
        recoit, message = self.link.status()
        self.assertFalse(recoit)
        self.assertTrue(message)

    def test_etat_signale_le_mauvais_univers(self):
        self.link.universe = 5
        self.link.receiver.feed(artdmx(universe=0, values={1: 10}), "2.0.0.20")
        recoit, message = self.link.status()
        self.assertFalse(recoit)
        self.assertIn("0", message)

    # ── persistance ─────────────────────────────────────────────────────────

    def test_config_aller_retour(self):
        self.link.set_target(4, "MEM 7")
        self.link.set_target(9, dil.CIBLE_VITESSE)
        cfg = self.link.to_config()

        autre = dil.DmxInLink(self.fenetre)
        autre.from_config(cfg)
        self.assertEqual(autre.patch, {4: "MEM 7", 9: dil.CIBLE_VITESSE})
        autre.stop()

    def test_univers_par_defaut_si_absent_de_la_config(self):
        autre = dil.DmxInLink(self.fenetre)
        autre.from_config({"enabled": True, "patch": []})
        self.assertEqual(autre.universe, dil.DEFAULT_UNIVERSE)
        autre.stop()

    def test_config_abimee_ne_plante_pas(self):
        autre = dil.DmxInLink(self.fenetre)
        autre.from_config({"universe": "x", "port": None, "merge": 42,
                           "patch": "abime"})
        self.assertEqual(autre.patch, {})
        self.assertEqual(autre.universe, dil.DEFAULT_UNIVERSE)
        autre.stop()

    def test_vieille_config_migree_a_la_relecture(self):
        autre = dil.DmxInLink(self.fenetre)
        autre.from_config({"mode": "libre", "start_channel": 1, "assignments": [
            {"channel": 2, "type": "tranche", "page": 0, "tranche": 1}]})
        self.assertEqual(autre.patch, {2: "B"})
        autre.stop()



class TestAiguillageEntree(unittest.TestCase):
    """Un port du Node bascule en ENTREE : MyStrow doit se TAIRE dessus.

    C'est la difference avec une sortie desactivee, qui continue d'emettre 512
    zeros pour que le boitier ne rejoue pas sa derniere trame.
    """

    def _dmx(self, output_map, universe=0):
        import artnet_dmx
        dmx = artnet_dmx.ArtNetDMX.__new__(artnet_dmx.ArtNetDMX)
        dmx.dmx_data = [bytearray(512) for _ in range(4)]
        dmx.universe = universe
        dmx.output_map = list(output_map)
        return dmx

    def test_set_output_map_accepte_l_entree(self):
        import artnet_dmx
        dmx = self._dmx([0, 1, 2, 3])
        artnet_dmx.ArtNetDMX.set_output_map(dmx, [0, 1, artnet_dmx.OUTPUT_INPUT,
                                                  artnet_dmx.OUTPUT_OFF])
        self.assertEqual(dmx.output_map,
                         [0, 1, artnet_dmx.OUTPUT_INPUT, artnet_dmx.OUTPUT_OFF])

    def test_input_universes(self):
        import artnet_dmx
        dmx = self._dmx([0, 1, artnet_dmx.OUTPUT_INPUT, 3], universe=4)
        self.assertEqual(artnet_dmx.ArtNetDMX.input_universes(dmx), [6])

    def test_rien_n_est_emis_sur_un_port_d_entree(self):
        import artnet_dmx
        envois = []

        class FauxSocket:
            def sendto(self, data, addr):
                envois.append(artnet_dmx.ArtNetDMX._build_artnet_packet.__name__
                              and (data[15] << 8) | data[14])

        dmx = self._dmx([0, 1, artnet_dmx.OUTPUT_INPUT, 3])
        dmx._socket = FauxSocket()
        dmx.target_ip, dmx.target_port = "2.0.0.15", 6454
        dmx._artnet_seq = 0
        dmx._last_artnet_error = None
        artnet_dmx.ArtNetDMX._send_artnet(dmx)
        self.assertEqual(envois, [0, 1, 3],
                         "l'univers 2 ne doit PAS partir : son port est une entree")

    def test_une_sortie_desactivee_emet_toujours_des_zeros(self):
        """Le contraire d'une entree — et c'est voulu."""
        import artnet_dmx
        envois = []

        class FauxSocket:
            def sendto(self, data, addr):
                envois.append(((data[15] << 8) | data[14], bytes(data[18:])))

        dmx = self._dmx([0, 1, artnet_dmx.OUTPUT_OFF, 3])
        dmx.dmx_data[2][0] = 255
        dmx._socket = FauxSocket()
        dmx.target_ip, dmx.target_port = "2.0.0.15", 6454
        dmx._artnet_seq = 0
        dmx._last_artnet_error = None
        artnet_dmx.ArtNetDMX._send_artnet(dmx)
        self.assertEqual([u for u, _p in envois], [0, 1, 2, 3])
        self.assertEqual(envois[2][1], bytes(512), "sortie OFF = 512 zeros emis")


class TestRisqueDeLarsen(unittest.TestCase):

    def _fenetre(self, transport, universe=0, output_map=None):
        dmx = type("FauxDmx", (), {})()
        dmx.transport = transport
        dmx.universe = universe
        dmx.output_map = list(output_map if output_map is not None else [0, 1, 2, 3])
        fenetre = FausseFenetre()
        fenetre.dmx = dmx
        return fenetre

    def test_l_univers_par_defaut_est_hors_de_notre_sortie(self):
        """La raison d'etre du 5e univers : MyStrow en emet quatre (0 a 3)."""
        link = dil.DmxInLink(self._fenetre("artnet"))
        self.assertEqual(link.universe, 5)
        self.assertNotIn(link.universe, link.emitted_universes())
        self.assertFalse(link.echo_risk())
        link.stop()

    def test_alerte_si_l_univers_ecoute_est_emis(self):
        link = dil.DmxInLink(self._fenetre("artnet"))
        link.universe = 2          # dans la plage 0..3 emise par le Node
        self.assertTrue(link.echo_risk())
        link.universe = 9
        self.assertFalse(link.echo_risk())
        link.stop()

    def test_pas_d_alerte_si_le_port_est_declare_en_entree(self):
        """Un port bascule en entree ne compte plus comme une sortie."""
        fenetre = self._fenetre("artnet", output_map=[0, 1, dil.OUTPUT_INPUT, 3])
        link = dil.DmxInLink(fenetre)
        link.universe = 2
        self.assertNotIn(2, link.emitted_universes())
        self.assertFalse(link.echo_risk())
        link.stop()

    def test_pas_d_alerte_en_usb(self):
        link = dil.DmxInLink(self._fenetre("enttec"))
        link.universe = 0
        self.assertFalse(link.echo_risk())
        link.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
