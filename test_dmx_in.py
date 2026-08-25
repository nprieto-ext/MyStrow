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

NB_PAGES_TEST = 3


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
    """Mouchard : enregistre ce que la liaison appelle, sans rien faire."""

    def __init__(self, page_active=0):
        self.faders = {i: FauxFader(0) for i in range(9)}
        self._bank_pages = [_page("P1-"), _page("P2-"), _page("P3-")]
        # La page 2 porte une tranche MEM et une tranche FX, pour verifier
        # qu'on route bien vers apply_slot_level_offpage sans les interpreter.
        self._bank_pages[1][0] = {"type": "memory", "mem_col": 0, "label": "MEM 1"}
        self._bank_pages[1][1] = {"type": "fx", "fx_col": 0, "label": "FX 1"}
        self._bank_page_idx = page_active

        self.faders_recus = []      # (index, velocite 0-127)
        self.offpage_recus = []     # (label du slot, niveau 0-100)

    def on_midi_fader(self, index, velocite):
        self.faders_recus.append((index, velocite))
        # On imite le vrai comportement : le fader a l'ecran suit.
        self.faders[index].value = int(velocite / 127.0 * 100)

    def apply_slot_level_offpage(self, slot, value):
        self.offpage_recus.append((slot.get("label"), value))
        return slot.get("type") in ("group", "fx", "play")


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


# ── adressage : 8 canaux par page ───────────────────────────────────────────

class TestAdressage(unittest.TestCase):

    def test_une_page_fait_huit_canaux(self):
        self.assertEqual(dil.TRANCHES_PAR_PAGE, 8)
        self.assertEqual(dil.offset_for(0, 0), 0)
        self.assertEqual(dil.offset_for(0, 7), 7)
        self.assertEqual(dil.offset_for(1, 0), 8, "la page 2 commence au 9e canal")
        self.assertEqual(dil.offset_for(19, 7), 159)

    def test_page_tranche_est_l_inverse(self):
        for page in range(20):
            for tranche in range(8):
                offset = dil.offset_for(page, tranche)
                self.assertEqual(dil.page_tranche_for(offset, 20), (page, tranche))

    def test_le_dernier_canal_est_la_vitesse(self):
        """Le fader 9 est en DERNIER, pas en 9e : c'est ce qui garde les pages
        sur des multiples de 8."""
        self.assertIsNone(dil.page_tranche_for(160, 20))
        self.assertIsNotNone(dil.page_tranche_for(159, 20))

    def test_taille_du_patch(self):
        self.assertEqual(dil.patch_size(20), 161)   # 20 x 8 + vitesse
        self.assertEqual(dil.patch_size(3), 25)

    def test_adresse_bornee_pour_que_le_patch_tienne(self):
        self.assertEqual(dil.max_start(20), 512 - 161 + 1)
        self.assertEqual(dil.clamp_start(9999, 20), dil.max_start(20))
        self.assertEqual(dil.clamp_start(0, 20), 1)
        self.assertEqual(dil.clamp_start("bof", 20), 1)


class TestFonctionsPures(unittest.TestCase):

    def test_conversion_dmx_vers_niveau(self):
        self.assertEqual(dil.dmx_to_level(0), 0)
        self.assertEqual(dil.dmx_to_level(255), 100)
        self.assertEqual(dil.dmx_to_level(128), 50)

    def test_aller_retour_niveau_velocite_sans_perte(self):
        """C'est ce qui autorise a passer par la porte du MIDI."""
        for niveau in range(101):
            velocite = dil.level_to_velocity(niveau)
            self.assertEqual(int((velocite / 127.0) * 100), niveau,
                             f"niveau {niveau} abime par l'aller-retour")

    def test_merge(self):
        self.assertEqual(dil.merge_level(dil.MERGE_LTP, 20, 90), 20)
        self.assertEqual(dil.merge_level(dil.MERGE_HTP, 20, 90), 90)
        self.assertEqual(dil.merge_level(dil.MERGE_HTP, 95, 90), 95)

    def test_libelles_pris_sur_la_bonne_page(self):
        fenetre = FausseFenetre()
        self.assertEqual(dil.tranche_labels(fenetre, 0)[0], "P1-1")
        self.assertEqual(dil.tranche_labels(fenetre, 1)[0], "MEM 1")
        self.assertEqual(dil.tranche_labels(fenetre, 2)[7], "P3-8")

    def test_libelles_tolerants_a_une_fenetre_sans_layout(self):
        self.assertEqual(dil.tranche_labels(None, 0), [str(i + 1) for i in range(8)])

    def test_nb_pages_par_defaut(self):
        self.assertEqual(dil.nb_pages(None), dil.PAGES_DEFAUT)
        self.assertEqual(dil.nb_pages(FausseFenetre()), NB_PAGES_TEST)

    def test_apprentissage_prend_le_canal_qui_bouge_le_plus(self):
        base = bytearray(512)
        frame = bytearray(512)
        frame[9] = 3       # bruit analogique
        frame[20] = 200    # le vrai fader
        frame[30] = 40     # diaphonie
        self.assertEqual(dil.find_moved_channel(base, frame), 21)

    def test_apprentissage_ignore_le_bruit(self):
        base = bytearray(512)
        frame = bytearray(512)
        frame[5] = 4
        self.assertIsNone(dil.find_moved_channel(base, frame))


# ── liaison ─────────────────────────────────────────────────────────────────

class TestLink(unittest.TestCase):

    def setUp(self):
        self.fenetre = FausseFenetre(page_active=0)
        self.link = dil.DmxInLink(self.fenetre)
        self.link.enabled = True
        self.link.start_channel = 10

    def tearDown(self):
        self.link.stop()

    def pousser(self, values, seq=1):
        self.link.receiver.feed(artdmx(values=values, seq=seq), "2.0.0.20")
        self.link._tick()

    # ── patch ───────────────────────────────────────────────────────────────

    def test_canaux_du_patch(self):
        self.assertEqual(self.link.channel_for(0, 0), 10)
        self.assertEqual(self.link.channel_for(0, 7), 17)
        self.assertEqual(self.link.channel_for(1, 0), 18, "page 2 = adresse + 8")
        self.assertEqual(self.link.channel_for(2, 7), 33)
        self.assertEqual(self.link.speed_channel(), 34)
        self.assertEqual(self.link.last_channel, 34)

    def test_resume_du_patch(self):
        self.assertEqual(self.link.pages, NB_PAGES_TEST)
        self.assertEqual(self.link.patch_size, 25)

    def test_lignes_de_patch_affichables(self):
        lignes = self.link.patch_rows(1)
        self.assertEqual(len(lignes), 9, "8 tranches + la vitesse")
        self.assertEqual(lignes[0][0], 18)
        self.assertEqual(lignes[0][1], "MEM 1")
        self.assertEqual(lignes[8][0], self.link.speed_channel())

    # ── premiere trame ──────────────────────────────────────────────────────

    def test_premiere_trame_ne_pilote_rien(self):
        """Cocher « activer » en plein show ne doit RIEN changer au parc."""
        self.pousser({10: 255, 18: 255}, seq=1)
        self.assertEqual(self.fenetre.faders_recus, [])
        self.assertEqual(self.fenetre.offpage_recus, [])

    # ── page affichee ───────────────────────────────────────────────────────

    def test_tranche_de_la_page_affichee_passe_par_le_midi(self):
        self.pousser({10: 0}, seq=1)
        self.pousser({10: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(0, 127)])
        self.assertEqual(self.fenetre.offpage_recus, [])

    def test_huitieme_tranche_de_la_page_affichee(self):
        self.pousser({17: 0}, seq=1)
        self.pousser({17: 128}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(7, dil.level_to_velocity(50))])

    def test_canal_de_vitesse_pilote_le_fader_9(self):
        self.pousser({34: 0}, seq=1)
        self.pousser({34: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(dil.FADER_VITESSE, 127)])

    # ── autres pages ────────────────────────────────────────────────────────

    def test_tranche_d_une_autre_page_passe_par_le_chemin_hors_page(self):
        """Tout l'interet : le pupitre pilote les pages non affichees."""
        self.pousser({19: 0}, seq=1)          # page 2, tranche 2 (FX 1)
        self.pousser({19: 255}, seq=2)
        self.assertEqual(self.fenetre.offpage_recus, [("FX 1", 100)])
        self.assertEqual(self.fenetre.faders_recus, [],
                         "une tranche hors page ne doit PAS toucher les faders visibles")

    def test_troisieme_page(self):
        self.pousser({26: 0}, seq=1)          # page 3, tranche 1
        self.pousser({26: 128}, seq=2)
        self.assertEqual(self.fenetre.offpage_recus, [("P3-1", 50)])

    def test_changer_de_page_affichee_change_le_routage(self):
        """La page 2 devient la page affichee : ses canaux passent au MIDI."""
        self.fenetre._bank_page_idx = 1
        self.pousser({19: 0}, seq=1)
        self.pousser({19: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(1, 127)])
        self.assertEqual(self.fenetre.offpage_recus, [])

    def test_les_deux_chemins_coexistent_dans_la_meme_trame(self):
        self.pousser({10: 0, 26: 0}, seq=1)
        self.pousser({10: 255, 26: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(0, 127)])
        self.assertEqual(self.fenetre.offpage_recus, [("P3-1", 100)])

    # ── economie de trafic ──────────────────────────────────────────────────

    def test_canal_immobile_ne_renvoie_rien(self):
        """40 trames/s : sans ce filtre, le pupitre ecraserait tout en continu."""
        self.pousser({10: 100}, seq=1)
        self.pousser({10: 200}, seq=2)
        self.fenetre.faders_recus.clear()
        for seq in range(3, 10):
            self.pousser({10: 200}, seq=seq)
        self.assertEqual(self.fenetre.faders_recus, [])

    def test_canal_hors_du_patch_ignore(self):
        self.pousser({200: 0}, seq=1)
        self.pousser({200: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [])
        self.assertEqual(self.fenetre.offpage_recus, [])

    # ── melange ─────────────────────────────────────────────────────────────

    def test_htp_le_niveau_local_gagne(self):
        self.link.merge = dil.MERGE_HTP
        self.fenetre.faders[0].value = 80      # l'AKAI est a 80
        self.pousser({10: 0}, seq=1)
        self.pousser({10: 26}, seq=2)          # le pupitre monte a ~10
        self.assertEqual(self.fenetre.faders_recus, [(0, dil.level_to_velocity(80))])

    def test_ltp_le_pupitre_gagne_toujours(self):
        self.fenetre.faders[0].value = 80
        self.pousser({10: 0}, seq=1)
        self.pousser({10: 26}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(0, dil.level_to_velocity(10))])

    # ── adresse ─────────────────────────────────────────────────────────────

    def test_changer_d_adresse_oublie_l_etat(self):
        """Sinon les anciennes valeurs designeraient les mauvaises tranches."""
        self.pousser({10: 100}, seq=1)
        self.link.set_start_channel(50)
        self.assertEqual(self.link._last_counter, -1)
        self.assertEqual(self.link._last_raw, {})

    def test_apprentissage_fixe_l_adresse_de_depart(self):
        """En mode Patch, le canal appris EST l'adresse de depart."""
        self.pousser({10: 0, 77: 0}, seq=1)
        self.link.start_learn()
        appris = []
        self.link.channel_learned.connect(appris.append)
        self.pousser({77: 255}, seq=2)
        self.assertEqual(appris, [77])
        self.assertEqual(self.link.start_channel, 77)
        self.assertFalse(self.link.is_learning())

    def test_apprentissage_ne_pilote_rien(self):
        """Designer l'adresse ne doit pas faire bouger le parc en plein reglage."""
        self.pousser({10: 0}, seq=1)
        self.link.start_learn()
        self.pousser({10: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [])
        self.assertEqual(self.fenetre.offpage_recus, [])

    def test_mauvais_univers_ignore(self):
        self.link.universe = 2
        self.link.receiver.feed(artdmx(universe=0, values={10: 255}), "2.0.0.20")
        self.link._tick()
        self.assertEqual(self.fenetre.faders_recus, [])

    # ── config ──────────────────────────────────────────────────────────────

    def test_config_aller_retour(self):
        self.link.start_channel = 33
        self.link.merge = dil.MERGE_HTP
        autre = dil.DmxInLink(self.fenetre)
        autre.from_config(self.link.to_config())
        self.assertEqual(autre.start_channel, 33)
        self.assertEqual(autre.merge, dil.MERGE_HTP)
        autre.stop()

    def test_config_abimee_ne_plante_pas(self):
        autre = dil.DmxInLink(None)
        autre.from_config({"port": "bof", "universe": None, "merge": "n'importe",
                           "start_channel": -5})
        self.assertEqual(autre.port, ai.DEFAULT_PORT)
        self.assertEqual(autre.universe, 0)
        self.assertEqual(autre.merge, dil.MERGE_LTP)
        self.assertEqual(autre.start_channel, 1)
        autre.stop()

    def test_etat_lisible_sans_reception(self):
        recoit, message = self.link.status()
        self.assertFalse(recoit)
        self.assertTrue(message)

    def test_etat_signale_le_mauvais_univers(self):
        self.link.universe = 5
        self.link.receiver.feed(artdmx(universe=0), "2.0.0.20")
        recoit, message = self.link.status()
        self.assertFalse(recoit)
        self.assertIn("0", message)


class TestNormalisationAssignations(unittest.TestCase):

    def test_jette_l_invalide(self):
        propre = dil.normalize_assignments([
            {"channel": 1, "type": "tranche", "page": 0, "tranche": 0},
            {"channel": 0, "type": "tranche", "page": 0, "tranche": 0},    # canal hors bornes
            {"channel": 999, "type": "tranche", "page": 0, "tranche": 0},  # canal hors bornes
            {"channel": 5, "type": "tranche", "page": 0, "tranche": 9},    # tranche inexistante
            {"channel": 6, "type": "tranche", "page": 99, "tranche": 0},   # page inexistante
            {"channel": 7, "type": "speed"},
            "pas un dictionnaire",
        ], pages=NB_PAGES_TEST)
        self.assertEqual([a["channel"] for a in propre], [1, 7])
        self.assertEqual(propre[1]["type"], dil.CIBLE_VITESSE)

    def test_un_canal_ne_pilote_qu_une_cible(self):
        propre = dil.normalize_assignments([
            {"channel": 3, "type": "tranche", "page": 0, "tranche": 1},
            {"channel": 3, "type": "tranche", "page": 1, "tranche": 4},
        ], pages=NB_PAGES_TEST)
        self.assertEqual(len(propre), 1)
        self.assertEqual(propre[0]["tranche"], 1, "la premiere gagne")

    def test_config_absente_ou_abimee(self):
        self.assertEqual(dil.normalize_assignments(None), [])
        self.assertEqual(dil.normalize_assignments("bof"), [])


class TestModeLibre(unittest.TestCase):

    def setUp(self):
        self.fenetre = FausseFenetre(page_active=0)
        self.link = dil.DmxInLink(self.fenetre)
        self.link.enabled = True
        self.link.set_mode(dil.MODE_LIBRE)

    def tearDown(self):
        self.link.stop()

    def pousser(self, values, seq=1):
        self.link.receiver.feed(artdmx(values=values, seq=seq), "2.0.0.20")
        self.link._tick()

    def test_sans_assignation_rien_ne_bouge(self):
        self.pousser({1: 0}, seq=1)
        self.pousser({1: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [])
        self.assertEqual(self.fenetre.offpage_recus, [])

    def test_n_importe_quel_canal_vers_n_importe_quelle_tranche(self):
        """Tout l'interet du mode : aucun ordre impose."""
        self.link.add_assignment(40, page=0, tranche=2)
        self.pousser({40: 0}, seq=1)
        self.pousser({40: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(2, 127)])

    def test_ordre_inverse_accepte(self):
        self.link.add_assignment(1, page=0, tranche=7)
        self.link.add_assignment(2, page=0, tranche=0)
        self.pousser({1: 0, 2: 0}, seq=1)
        self.pousser({1: 255, 2: 128}, seq=2)
        self.assertEqual(sorted(self.fenetre.faders_recus),
                         sorted([(7, 127), (0, dil.level_to_velocity(50))]))

    def test_cible_hors_page(self):
        self.link.add_assignment(100, page=2, tranche=0)
        self.pousser({100: 0}, seq=1)
        self.pousser({100: 255}, seq=2)
        self.assertEqual(self.fenetre.offpage_recus, [("P3-1", 100)])
        self.assertEqual(self.fenetre.faders_recus, [])

    def test_cible_vitesse(self):
        self.link.add_assignment(200, vitesse=True)
        self.pousser({200: 0}, seq=1)
        self.pousser({200: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(dil.FADER_VITESSE, 127)])

    def test_canal_non_assigne_ignore(self):
        self.link.add_assignment(40, page=0, tranche=2)
        self.pousser({41: 0}, seq=1)
        self.pousser({41: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [])

    def test_reassigner_un_canal_remplace_sans_doublon(self):
        self.link.add_assignment(40, page=0, tranche=2)
        self.link.add_assignment(40, page=0, tranche=5)
        self.assertEqual(len(self.link.assignments), 1)
        self.pousser({40: 0}, seq=1)
        self.pousser({40: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [(5, 127)])

    def test_supprimer_une_assignation(self):
        self.link.add_assignment(40, page=0, tranche=2)
        self.link.remove_assignment(40)
        self.assertEqual(self.link.assignments, [])
        self.pousser({40: 0}, seq=1)
        self.pousser({40: 255}, seq=2)
        self.assertEqual(self.fenetre.faders_recus, [])

    def test_premiere_trame_ne_pilote_rien(self):
        self.link.add_assignment(40, page=0, tranche=2)
        self.pousser({40: 255}, seq=1)
        self.assertEqual(self.fenetre.faders_recus, [])

    def test_apprentissage_donne_le_canal_brut(self):
        """En mode Libre, apprendre ne touche PAS a l'adresse de depart."""
        self.link.start_channel = 1
        self.link.add_assignment(40, page=0, tranche=2)
        self.pousser({40: 0, 88: 0}, seq=1)
        self.link.start_learn()
        appris = []
        self.link.channel_learned.connect(appris.append)
        self.pousser({88: 255}, seq=2)
        self.assertEqual(appris, [88])
        self.assertEqual(self.link.start_channel, 1, "l'adresse ne bouge pas ici")

    def test_libelle_d_assignation(self):
        self.link.add_assignment(40, page=1, tranche=0)
        lignes = self.link.assignment_rows()
        self.assertEqual(lignes[0][0], 40)
        self.assertIn("MEM 1", lignes[0][1])

    def test_changer_de_mode_oublie_l_etat(self):
        self.link.add_assignment(40, page=0, tranche=2)
        self.pousser({40: 100}, seq=1)
        self.link.set_mode(dil.MODE_PATCH)
        self.assertEqual(self.link._last_counter, -1)
        self.assertEqual(self.link._last_raw, {})

    def test_config_aller_retour(self):
        self.link.add_assignment(40, page=1, tranche=3)
        self.link.add_assignment(41, vitesse=True)
        autre = dil.DmxInLink(self.fenetre)
        autre.from_config(self.link.to_config())
        self.assertEqual(autre.mode, dil.MODE_LIBRE)
        self.assertEqual(autre.assignments, self.link.assignments)
        autre.stop()

    def test_watched_reflete_le_mode(self):
        self.link.add_assignment(40, page=0, tranche=2)
        self.assertEqual(list(self.link.watched()),
                         [(40, dil.CIBLE_TRANCHE, 0, 2)])
        self.link.set_mode(dil.MODE_PATCH)
        self.assertEqual(len(list(self.link.watched())), self.link.patch_size)


class TestPatchEnBoutDUnivers(unittest.TestCase):
    """Une adresse haute ne doit pas lire au-dela du 512e canal."""

    def test_pas_de_debordement(self):
        fenetre = FausseFenetre()
        link = dil.DmxInLink(fenetre)
        link.enabled = True
        link.start_channel = dil.max_start(NB_PAGES_TEST)
        self.assertEqual(link.last_channel, 512)
        link.receiver.feed(artdmx(values={512: 0}, seq=1), "2.0.0.20")
        link._tick()
        link.receiver.feed(artdmx(values={512: 255}, seq=2), "2.0.0.20")
        link._tick()   # ne doit pas lever IndexError
        self.assertEqual(fenetre.faders_recus, [(dil.FADER_VITESSE, 127)])
        link.stop()


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
        class FauxDmx:
            def input_universes(self):
                return [self.universe + n for n, v in enumerate(self.output_map)
                        if v == dil.OUTPUT_INPUT]
        dmx = FauxDmx()
        dmx.transport = transport
        dmx.universe = universe
        dmx.output_map = list(output_map if output_map is not None else [0, 1, 2, 3])
        fenetre = FausseFenetre()
        fenetre.dmx = dmx
        return fenetre

    def test_alerte_si_l_univers_ecoute_est_emis(self):
        link = dil.DmxInLink(self._fenetre("artnet"))
        link.universe = 2          # dans la plage 0..3 emise par le Node
        self.assertTrue(link.echo_risk())
        link.universe = 9
        self.assertFalse(link.echo_risk())
        link.stop()

    def test_pas_d_alerte_si_le_port_est_declare_en_entree(self):
        """Tout l'interet du reglage : on ne s'y bat plus avec nous-memes."""
        fenetre = self._fenetre("artnet", output_map=[0, 1, dil.OUTPUT_INPUT, 3])
        link = dil.DmxInLink(fenetre)
        link.universe = 2
        self.assertNotIn(2, link.emitted_universes())
        self.assertFalse(link.echo_risk())
        self.assertIsNone(link.routing_hint(), "univers coherent : rien a signaler")
        link.stop()

    def test_rappel_si_aucun_port_n_est_en_entree(self):
        link = dil.DmxInLink(self._fenetre("artnet"))
        link.universe = 2
        self.assertTrue(link.routing_hint())
        link.stop()

    def test_rappel_si_on_ecoute_le_mauvais_univers(self):
        fenetre = self._fenetre("artnet", output_map=[0, 1, dil.OUTPUT_INPUT, 3])
        link = dil.DmxInLink(fenetre)
        link.universe = 0
        message = link.routing_hint()
        self.assertTrue(message)
        self.assertIn("2", message)
        link.stop()

    def test_pas_d_alerte_en_usb(self):
        link = dil.DmxInLink(self._fenetre("enttec"))
        link.universe = 0
        self.assertFalse(link.echo_risk())
        self.assertIsNone(link.routing_hint(),
                          "l'aiguillage du Node ne s'applique pas en USB")
        link.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
