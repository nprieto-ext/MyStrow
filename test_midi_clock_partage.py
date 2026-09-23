"""Horloge MIDI partagee avec le controleur, et recherche du bon port.

Remontee client (22/09/2026, dossier RENAUT, DJM-2000 + CDJ-2000NXS2) :

  - « c'est l'un ou l'autre » : la DJM ne presente qu'UN port MIDI, qui porte
    ses pads/faders ET son horloge. Le MIDIHandler l'ouvrait pour le controleur,
    le moteur LIVE le rouvrait pour l'horloge ; sous Windows un port n'a qu'un
    client, la seconde ouverture etait refusee ;
  - le port de l'horloge etait le premier « non controleur » de la liste
    Windows, donc dependant de l'ordre de branchement (un CDJ muet) ;
  - la liste n'etait lue qu'au demarrage du LIVE : un hub branche ensuite
    obligeait a repasser LIVE -> Sequence -> LIVE.
"""
import threading
import unittest

from PySide6.QtCore import QCoreApplication

import live_audio
import midi_handler

_app = QCoreApplication.instance() or QCoreApplication([])


class _Monde:
    """Etat MIDI simule : ports presents, ports tenus par un autre logiciel."""

    def __init__(self, ports, occupes=()):
        self.ports = list(ports)
        self.occupes = set(occupes)
        self.ouverts = {}      # nom -> _FauxMidiIn


class _FauxRtmidi:
    def __init__(self, monde):
        monde_ = monde

        class MidiIn:
            def __init__(self):
                self.nom = None
                self.cb = None

            def get_ports(self):
                return list(monde_.ports)

            def open_port(self, i):
                nom = monde_.ports[i]
                if nom in monde_.occupes or nom in monde_.ouverts:
                    raise RuntimeError("port occupe")
                self.nom = nom
                monde_.ouverts[nom] = self

            def close_port(self):
                monde_.ouverts.pop(self.nom, None)

            def ignore_types(self, **kw):
                self.ignore = kw

            def set_callback(self, cb):
                self.cb = cb

        self.MidiIn = MidiIn


class _FauxControleur:
    def __init__(self, ports):
        self.ports = list(ports)
        self.clock_listener = None

    def open_input_names(self):
        return list(self.ports)


class _Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class _Base(unittest.TestCase):
    def setUp(self):
        self._orig = (live_audio._rtmidi, live_audio.time.monotonic,
                      live_audio.LiveAudioEngine._log_audio)
        self.horloge = _Horloge()
        live_audio.time.monotonic = self.horloge
        live_audio.LiveAudioEngine._log_audio = staticmethod(lambda m: None)

    def tearDown(self):
        live_audio._rtmidi, live_audio.time.monotonic, \
            live_audio.LiveAudioEngine._log_audio = self._orig

    def moteur(self, monde, controleur=None):
        live_audio._rtmidi = _FauxRtmidi(monde)
        eng = live_audio.LiveAudioEngine()
        self.labels = []
        eng.device_info.connect(self.labels.append)
        eng.set_controller_midi(controleur)
        eng._running = True
        eng._source_key = 'midi_clock'
        eng._open_midi_clock()
        self.addCleanup(eng.stop)
        return eng

    def tops(self, emettre, n=48, bpm=128.0):
        """n tops d'horloge a `bpm`, via la fonction `emettre(event)`."""
        pas = 60.0 / (bpm * 24)
        for _ in range(n):
            self.horloge.t += pas
            emettre(([0xF8], pas))

    def seconde(self, eng, n=1):
        for _ in range(n):
            self.horloge.t += 1.0
            eng._clock_hunt()


class TestPortPartageAvecLeControleur(_Base):
    def test_le_port_du_controleur_n_est_pas_rouvert(self):
        monde = _Monde(['CDJ-2000NXS2 MIDI 0', 'DJM-2000 1'])
        ctrl = _FauxControleur(['DJM-2000 1'])
        eng = self.moteur(monde, ctrl)
        self.assertNotIn('DJM-2000 1', eng._clock_tried)
        self.assertIs(ctrl.clock_listener.__func__,
                      live_audio.LiveAudioEngine._midi_clock_cb)

    def test_l_horloge_du_controleur_donne_le_bpm(self):
        monde = _Monde(['DJM-2000 0'])
        ctrl = _FauxControleur(['DJM-2000 0'])
        eng = self.moteur(monde, ctrl)
        self.assertIsNone(eng._midi_clock_in)   # rien d'autre a ouvrir
        self.tops(lambda ev: ctrl.clock_listener(ev, 'DJM-2000 0'))
        self.assertEqual(eng._clock_src, 'DJM-2000 0')
        self.assertAlmostEqual(eng._bpm, 128.0, places=1)

    def test_notre_port_est_rendu_quand_l_horloge_vient_du_controleur(self):
        monde = _Monde(['CDJ-2000NXS2 MIDI 0', 'DJM-2000 1'])
        ctrl = _FauxControleur(['DJM-2000 1'])
        eng = self.moteur(monde, ctrl)
        self.assertIn('CDJ-2000NXS2 MIDI 0', monde.ouverts)
        self.tops(lambda ev: ctrl.clock_listener(ev, 'DJM-2000 1'))
        self.seconde(eng)
        self.assertNotIn('CDJ-2000NXS2 MIDI 0', monde.ouverts)

    def test_une_seconde_source_est_ignoree(self):
        monde = _Monde(['CDJ-2000NXS2 MIDI 0', 'DJM-2000 1'])
        ctrl = _FauxControleur(['DJM-2000 1'])
        eng = self.moteur(monde, ctrl)
        self.tops(lambda ev: ctrl.clock_listener(ev, 'DJM-2000 1'), bpm=128)
        cdj = monde.ouverts['CDJ-2000NXS2 MIDI 0']
        self.tops(cdj.cb, bpm=90)
        self.assertEqual(eng._clock_src, 'DJM-2000 1')
        self.assertAlmostEqual(eng._bpm, 128.0, places=0)

    def test_stop_debranche_l_ecoute(self):
        ctrl = _FauxControleur(['DJM-2000 0'])
        eng = self.moteur(_Monde(['DJM-2000 0']), ctrl)
        eng.stop()
        self.assertIsNone(ctrl.clock_listener)


class TestRechercheDuPort(_Base):
    def test_un_port_muet_cede_la_place_au_suivant(self):
        monde = _Monde(['CDJ-2000NXS2 MIDI 0', 'DJM-2000 1'])
        eng = self.moteur(monde)
        self.assertEqual(eng._clock_port_name, 'CDJ-2000NXS2 MIDI 0')
        self.seconde(eng, 3)
        self.assertEqual(eng._clock_port_name, 'DJM-2000 1')
        self.assertNotIn('CDJ-2000NXS2 MIDI 0', monde.ouverts)
        self.tops(monde.ouverts['DJM-2000 1'].cb)
        self.assertEqual(eng._clock_src, 'DJM-2000 1')
        self.seconde(eng, 10)
        self.assertEqual(eng._clock_port_name, 'DJM-2000 1')   # on y reste

    def test_un_port_occupe_est_saute(self):
        monde = _Monde(['CDJ-2000NXS2 MIDI 0', 'DJM-2000 1'],
                       occupes={'CDJ-2000NXS2 MIDI 0'})
        eng = self.moteur(monde)
        self.assertEqual(eng._clock_port_name, 'DJM-2000 1')

    def test_tout_muet_on_se_repose_sur_le_meilleur(self):
        monde = _Monde(['CDJ-2000NXS2 MIDI 0', 'DJM-2000 1'])
        eng = self.moteur(monde)
        self.seconde(eng, 20)
        self.assertEqual(eng._clock_port_name, 'CDJ-2000NXS2 MIDI 0')
        self.assertTrue(eng._clock_exhausted)

    def test_appareil_branche_apres_le_lancement(self):
        monde = _Monde([])
        eng = self.moteur(monde)
        self.assertIsNone(eng._midi_clock_in)
        monde.ports = ['DJM-2000 0']
        self.seconde(eng)
        self.assertEqual(eng._clock_port_name, 'DJM-2000 0')

    def test_source_debranchee_relance_la_recherche(self):
        monde = _Monde(['DJM-2000 0'])
        eng = self.moteur(monde)
        self.tops(monde.ouverts['DJM-2000 0'].cb)
        monde.ports = []
        monde.ouverts.clear()
        self.seconde(eng)
        self.assertIsNone(eng._clock_src)
        monde.ports = ['DJM-2000 0']
        self.seconde(eng)
        self.assertEqual(eng._clock_port_name, 'DJM-2000 0')

    def test_priorite_mystrow_conservee(self):
        monde = _Monde(['DJM-2000 0', 'MyStrow 1'])
        eng = self.moteur(monde)
        self.assertEqual(eng._clock_port_name, 'MyStrow 1')

    def test_pas_de_faux_120_bpm_sans_port(self):
        eng = self.moteur(_Monde([]))
        eng._midi_beat_tick()
        self.assertEqual(eng._bpm, 0.0)


class TestMidiHandlerRelaieLHorloge(unittest.TestCase):
    def handler(self):
        h = midi_handler.MIDIHandler.__new__(midi_handler.MIDIHandler)
        h._midi_lock = threading.Lock()
        h._midi_queue = []
        h._last_msg, h._last_msg_t = None, 0.0
        h.rx_count, h.last_raw = 0, None
        h.clock_listener = None
        return h

    def test_temps_reel_vers_l_ecoute_jamais_vers_les_pads(self):
        h = self.handler()
        recu = []
        h.clock_listener = lambda ev, port: recu.append((ev[0][0], port))
        for b in (0xFA, 0xF8, 0xFC):
            h._midi_callback(([b], 0.0), 'DJM-2000 1')
        self.assertEqual(recu, [(0xFA, 'DJM-2000 1'), (0xF8, 'DJM-2000 1'),
                                (0xFC, 'DJM-2000 1')])
        self.assertEqual(h._midi_queue, [])
        self.assertEqual(h.rx_count, 0)

    def test_sans_ecoute_l_horloge_est_ignoree(self):
        h = self.handler()
        h._midi_callback(([0xF8], 0.0), 'X')
        self.assertEqual(h._midi_queue, [])

    def test_les_pads_passent_toujours(self):
        h = self.handler()
        h.clock_listener = lambda ev, port: None
        h._midi_callback(([0x90, 36, 127], 0.0), 'DJM-2000 1')
        self.assertEqual(h._midi_queue, [[0x90, 36, 127]])

    def test_les_entrees_laissent_passer_l_horloge(self):
        h = self.handler()

        class Port:
            def set_callback(self, cb):
                self.cb = cb

            def ignore_types(self, **kw):
                self.kw = kw
        p = Port()
        recu = []
        h.clock_listener = lambda ev, port: recu.append(port)
        h._bind_input(p, 'DJM-2000 1')
        self.assertFalse(p.kw['timing'])
        p.cb(([0xF8], 0.0), None)
        self.assertEqual(recu, ['DJM-2000 1'])


if __name__ == '__main__':
    unittest.main()
