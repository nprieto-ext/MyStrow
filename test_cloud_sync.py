"""
test_cloud_sync.py — patch et effets qui suivent le compte (façon iCloud).

Demande du 13/10/2026 : « à la Apple, pas de complication : j'ai fait un patch
sur mon compte, hop ça l'enregistre sur mon compte » — et « si y a pas de
connexion, faut pas que ça plante et que ça mouline ».

Le réseau est simulé : aucun appel réel, aucun fichier de l'utilisateur touché
(les fichiers synchronisés sont redirigés vers un dossier temporaire).

    python test_cloud_sync.py
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import cloud_sync as cs


def _entry(text, utc=1000.0):
    return {"content": text, "sha": cs._sha(text), "utc": utc}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._files, self._state = cs.FILES, cs.STATE_FILE
        cs.FILES = {k: self.tmp / p.name for k, p in self._files.items()}
        cs.STATE_FILE = self.tmp / "state.json"
        self._cache = cs.CACHE_FILE
        cs.CACHE_FILE = self.tmp / "cache.json"
        self._uid, self._fetch, self._push = cs.account_uid, cs.fetch_remote, cs.push
        self._tok = cs._token
        cs.account_uid = lambda: "u1"

    def tearDown(self):
        cs.FILES, cs.STATE_FILE, cs.CACHE_FILE = self._files, self._state, self._cache
        cs.account_uid, cs.fetch_remote, cs.push = self._uid, self._fetch, self._push
        cs._token = self._tok

    def ecrire(self, key, obj):
        cs.FILES[key].write_text(json.dumps(obj), encoding="utf-8")

    def lire(self, key):
        return json.loads(cs.FILES[key].read_text(encoding="utf-8"))

    def demarrer(self, remote, reponse=None):
        """Démarrage complet, lecture du compte simulée. Renvoie (écrits, questions)."""
        cs.fetch_remote = lambda uid, known=None, token=None: (
            None if remote is None else (remote, 1.0))
        questions = []

        def ask(conflits):
            questions.append(list(conflits))
            return reponse

        puller = cs.StartupPull().start()
        self.assertTrue(puller._done.wait(2))
        return cs.finish_startup_pull(puller, ask_first_time=ask), questions


class NouveauPC(Base):
    def test_pc_vide_prend_le_compte_sans_question(self):
        remote = {"patch": _entry('{"fixtures": [1, 2]}')}
        ecrits, questions = self.demarrer(remote)
        self.assertEqual(ecrits, ["patch"])
        self.assertEqual(questions, [])
        self.assertEqual(self.lire("patch"), {"fixtures": [1, 2]})

    def test_pc_avec_son_patch_une_seule_question(self):
        self.ecrire("patch", {"fixtures": ["local"]})
        remote = {"patch": _entry('{"fixtures": ["compte"]}')}
        ecrits, questions = self.demarrer(remote, reponse=True)
        self.assertEqual(questions, [["patch"]])
        self.assertEqual(self.lire("patch"), {"fixtures": ["compte"]})
        # Copie de sécurité de l'ancien patch du PC
        baks = list(self.tmp.glob(".maestro_dmx_patch.json.avant-synchro-*"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(json.loads(baks[0].read_text()), {"fixtures": ["local"]})

    def test_garder_ce_pc(self):
        self.ecrire("patch", {"fixtures": ["local"]})
        remote = {"patch": _entry('{"fixtures": ["compte"]}')}
        ecrits, _q = self.demarrer(remote, reponse=False)
        self.assertEqual(ecrits, [])
        self.assertEqual(self.lire("patch"), {"fixtures": ["local"]})
        # …et il est à envoyer
        self.assertIn("patch", cs.local_changes(cs.state_for("u1")))

    def test_la_question_n_est_posee_qu_une_fois(self):
        self.ecrire("patch", {"fixtures": ["local"]})
        self.demarrer({"patch": _entry('{"a": 1}')}, reponse=False)
        _e, questions = self.demarrer({"patch": _entry('{"a": 2}', utc=1.0)}, reponse=True)
        self.assertEqual(questions, [])

    def test_compte_vide_rien_ne_bouge(self):
        self.ecrire("patch", {"fixtures": ["local"]})
        ecrits, questions = self.demarrer({})
        self.assertEqual((ecrits, questions), ([], []))
        self.assertEqual(self.lire("patch"), {"fixtures": ["local"]})


class Suivi(Base):
    """Après la première fois : silencieux, le plus récent gagne."""

    def _synchro(self, key, obj):
        self.ecrire(key, obj)
        st = cs.state_for("u1")
        st["synced"][key] = cs.read_local(key)[1]
        st["asked"] = True
        cs.save_state(st)

    def test_le_compte_a_change_on_le_prend(self):
        self._synchro("patch", {"v": 1})
        ecrits, q = self.demarrer({"patch": _entry('{"v": 2}')})
        self.assertEqual((ecrits, q), (["patch"], []))
        self.assertEqual(self.lire("patch"), {"v": 2})

    def test_ce_pc_a_change_on_le_garde(self):
        self._synchro("patch", {"v": 1})
        sha_envoye = cs.state_for("u1")["synced"]["patch"]
        self.ecrire("patch", {"v": "local"})
        remote = {"patch": {"content": '{"v": 1}', "sha": sha_envoye, "utc": 5.0}}
        ecrits, _q = self.demarrer(remote)
        self.assertEqual(ecrits, [])
        self.assertEqual(self.lire("patch"), {"v": "local"})

    def test_les_deux_ont_change_le_plus_recent_gagne(self):
        self._synchro("patch", {"v": 1})
        self.ecrire("patch", {"v": "local"})
        futur = time.time() + 3600
        ecrits, q = self.demarrer({"patch": _entry('{"v": "compte"}', utc=futur)})
        self.assertEqual((ecrits, q), (["patch"], []))
        self.assertEqual(self.lire("patch"), {"v": "compte"})
        self._synchro("patch", {"v": 1})
        self.ecrire("patch", {"v": "local2"})
        ecrits, _q = self.demarrer({"patch": _entry('{"v": "vieux"}', utc=1.0)})
        self.assertEqual(ecrits, [])
        self.assertEqual(self.lire("patch"), {"v": "local2"})

    def test_contenu_du_compte_corrompu_jamais_ecrit(self):
        ecrits, _q = self.demarrer({"patch": _entry("{pas du json")})
        self.assertEqual(ecrits, [])
        self.assertFalse(cs.FILES["patch"].exists())

    def test_changer_de_compte_repart_de_zero(self):
        self._synchro("patch", {"v": 1})
        cs.account_uid = lambda: "u2"
        self.assertEqual(cs.state_for("u2")["synced"], {})


class HorsConnexion(Base):
    def test_compte_injoignable_au_demarrage(self):
        self.ecrire("patch", {"v": "local"})
        ecrits, q = self.demarrer(None)
        self.assertEqual((ecrits, q), ([], []))
        self.assertEqual(self.lire("patch"), {"v": "local"})

    def test_reseau_lent_le_demarrage_n_attend_pas(self):
        """Résultat arrivé après le splash : ignoré, rien n'est écrit."""
        lache = threading.Event()

        def lent(uid, known=None, token=None):
            lache.wait(5)
            return {"patch": _entry('{"v": "tard"}')}, 1.0

        cs.fetch_remote = lent
        self.ecrire("patch", {"v": "local"})
        puller = cs.StartupPull().start()
        t0 = time.time()
        ecrits = cs.finish_startup_pull(puller)
        self.assertLess(time.time() - t0, 0.2)
        self.assertEqual(ecrits, [])
        lache.set()
        time.sleep(0.05)
        self.assertEqual(self.lire("patch"), {"v": "local"}, "le thread tardif n'ecrit rien")

    def test_pas_de_compte_aucun_reseau(self):
        cs.account_uid = lambda: None
        appels = []
        cs.fetch_remote = lambda uid, known=None, token=None: appels.append(uid)
        puller = cs.StartupPull().start()
        self.assertEqual(cs.finish_startup_pull(puller), [])
        p = cs.Pusher()
        self.assertEqual(p.tick(), "off")
        self.assertEqual(appels, [])

    def test_envoi_qui_traine_ne_bloque_jamais_le_minuteur(self):
        lache = threading.Event()

        def lent(uid, local, known=None):
            lache.wait(5)
            return None                      # puis échec (hors ligne)

        cs.push = lent
        self.ecrire("patch", {"v": 1})
        p = cs.Pusher()
        for _ in range(20):
            t0 = time.time()
            p.tick()
            self.assertLess(time.time() - t0, 0.05, "tick ne doit jamais attendre")
        self.assertEqual(p.status, "sending")
        lache.set()
        p._thread.join(1)
        self.assertEqual(p.tick(), "offline")
        # Pause après l'échec : pas de nouvel envoi à chaque tick
        self.assertIsNone(p._thread)
        p.tick()
        self.assertIsNone(p._thread)

    def test_exception_dans_l_envoi_ne_remonte_pas(self):
        def casse(uid, local, known=None):
            raise RuntimeError("boum")

        cs.push = casse
        self.ecrire("patch", {"v": 1})
        p = cs.Pusher()
        p.tick()
        p._thread.join(1)
        self.assertEqual(p.tick(), "offline")


class Envoi(Base):
    def test_modif_envoyee_puis_plus_rien(self):
        envois = []

        def ok(uid, local, known=None):
            envois.append(sorted(local))
            return {k: v["sha"] for k, v in local.items()}, dict(local), 5.0

        cs.push = ok
        self.ecrire("patch", {"v": 1})
        self.ecrire("fx_custom", [])
        p = cs.Pusher()
        p.tick(); p._thread.join(1)
        self.assertEqual(p.tick(), "ok")
        self.assertEqual(envois, [["fx_custom", "patch"]])
        p.tick()                              # rien n'a changé
        self.assertIsNone(p._thread)
        time.sleep(0.02)
        self.ecrire("patch", {"v": 2})       # une modif
        t = time.time()
        self.assertEqual(p.tick(now=t), "pending")
        self.assertIsNone(p._thread, "pas d'envoi avant 30 s de calme")
        p.tick(now=t + cs.QUIET_S + 1); p._thread.join(1); p.tick()
        self.assertEqual(envois[-1], ["patch"])
        # Le cache garde le contenu du compte pour la prochaine lecture
        self.assertEqual(cs.load_cache("u1")[0], 5.0)

    def test_dix_modifs_d_affilee_un_seul_envoi(self):
        envois = []
        cs.push = lambda uid, local, known=None: (
            envois.append(1) or ({k: v["sha"] for k, v in local.items()}, dict(local), 5.0))
        self.ecrire("patch", {"v": 0})
        p = cs.Pusher()
        p.tick(); p._thread.join(1); p.tick()
        t = time.time()
        for i in range(10):
            self.ecrire("patch", {"v": i + 1})
            import os
            os.utime(cs.FILES["patch"], (t + i, t + i))
            p.tick(now=t + i * 5)
        self.assertEqual(len(envois), 1, "rien pendant l'edition")
        p.tick(now=t + 45 + cs.QUIET_S); p._thread.join(1); p.tick()
        self.assertEqual(len(envois), 2)

    def test_fusion_le_plus_recent_gagne(self):
        """Un autre PC a envoyé un fichier plus récent : on ne l'écrase pas."""
        ecrit = {}
        cs.fetch_remote = lambda uid, known=None, token=None: (
            {"patch": _entry('{"v": "autre PC"}', utc=time.time() + 60),
             "fx_custom": _entry("[]", utc=1.0)}, 3.0)
        import urllib.request as ur
        vrai = ur.urlopen

        class _Rep:
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def faux(req, timeout=None, context=None):
            texte = json.loads(req.data)["fields"]["payload"]["stringValue"]
            ecrit["brut"] = texte
            ecrit["payload"] = {"files": cs.decode_payload(texte)}
            return _Rep()

        ur.urlopen = faux
        cs._token = lambda: "jeton"
        try:
            local = {"patch": _entry('{"v": "ce PC"}', utc=10.0),
                     "fx_custom": _entry('[{"name": "x"}]', utc=50.0)}
            pris, _files, _utc = self._push("u1", local)
        finally:
            ur.urlopen = vrai
        self.assertEqual(set(pris), {"fx_custom"})
        self.assertTrue(ecrit["brut"].startswith("z1:"), "contenu compresse")
        files = ecrit["payload"]["files"]
        self.assertEqual(files["patch"]["content"], '{"v": "autre PC"}')
        self.assertEqual(files["fx_custom"]["content"], '[{"name": "x"}]')


class Sobriete(Base):
    """« Ça va pas coûter cher ? » — lire la date seule, compresser."""

    def test_compression_aller_retour_et_gain(self):
        vrai_patch = Path.home() / ".maestro_dmx_patch.json"
        texte = vrai_patch.read_text(encoding="utf-8") if vrai_patch.exists()             else json.dumps({"fixtures": [{"name": "Lyre %d" % i, "profile": ["Pan", "Tilt"] * 8}
                                          for i in range(40)]})
        files = {"patch": _entry(texte)}
        enc = cs.encode_payload(files)
        self.assertEqual(cs.decode_payload(enc), files)
        self.assertLess(len(enc), len(texte) / 2.5, "au moins 2,5x plus petit")

    def test_ancien_format_non_compresse_lisible(self):
        files = {"patch": _entry('{"v": 1}')}
        self.assertEqual(cs.decode_payload(json.dumps({"files": files})), files)

    def _faux_get(self, docs):
        appels = []

        def get(uid, token, mask=None):
            appels.append(mask)
            return docs(mask)

        self._vrai_get = cs._get_doc
        cs._get_doc = get
        self.addCleanup(lambda: setattr(cs, "_get_doc", self._vrai_get))
        return appels

    def test_date_inchangee_rien_n_est_telecharge(self):
        files = {"patch": _entry('{"v": 1}')}
        appels = self._faux_get(lambda m: {"updated_utc": 42.0})
        res = cs.fetch_remote("u1", known=(42.0, files), token="t")
        self.assertEqual(res, (files, 42.0))
        self.assertEqual(appels, ["updated_utc"], "seule la date est lue")

    def test_date_changee_contenu_telecharge(self):
        files = {"patch": _entry('{"v": 2}')}
        appels = self._faux_get(lambda m: {"updated_utc": 43.0} if m else
                                {"updated_utc": 43.0, "payload": cs.encode_payload(files)})
        res = cs.fetch_remote("u1", known=(42.0, {}), token="t")
        self.assertEqual(res, (files, 43.0))
        self.assertEqual(appels, ["updated_utc", None])

    def test_compte_vide(self):
        self._faux_get(lambda m: {})
        self.assertEqual(cs.fetch_remote("u1", token="t"), ({}, 0.0))

    def test_injoignable(self):
        self._faux_get(lambda m: None)
        self.assertIsNone(cs.fetch_remote("u1", token="t"))

    def test_le_demarrage_remplit_le_cache(self):
        files = {"patch": _entry('{"v": 1}')}
        cs.fetch_remote = lambda uid, known=None, token=None: (files, 77.0)
        puller = cs.StartupPull().start()
        puller._done.wait(2)
        cs.finish_startup_pull(puller)
        self.assertEqual(cs.load_cache("u1"), (77.0, files))
        self.assertIsNone(cs.load_cache("autre"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
