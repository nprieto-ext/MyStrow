"""Assistant intégré : compréhension des demandes, dans les 6 langues.

Lancer : python test_assistant_nlu.py
"""
import sys

from assistant_nlu import parse, normalize
from effect_editor import BUILTIN_EFFECTS

EFFECTS = list(BUILTIN_EFFECTS)


def first(text, lang="fr", aliases=None):
    p = parse(text, EFFECTS, lang, aliases)
    return p, p.actions[0]


def check(text, expect: dict, lang=None):
    p, a = first(text)
    for k, v in expect.items():
        assert a.get(k) == v, f"{text!r} → {a} (attendu {k}={v!r})"
    if lang:
        assert p.lang == lang, f"{text!r} → langue {p.lang}, attendu {lang}"


def test_couleurs_toutes_langues():
    check("allume mes projecteurs en rouge", {"do": "color", "hex": "#ff0000", "target": {"all": True}}, "fr")
    check("turn all the lights blue", {"do": "color", "color": "blue"}, "en")
    check("pon todo en verde", {"do": "color", "color": "green"}, "es")
    check("mach alles rot", {"do": "color", "color": "red"}, "de")
    check("liga tudo em vermelho", {"do": "color", "color": "red"}, "pt")
    check("全部赤にして", {"do": "color", "color": "red"}, "ja")


def test_cibles_et_niveau():
    check("passe la face en bleu à 60 %", {"do": "color", "target": {"group": "A"}, "level": 60})
    check("groupe C en violet", {"do": "color", "target": {"group": "C"}, "color": "purple"})
    check("les lyres en blanc chaud", {"do": "color", "target": {"kind": "lyre"}, "color": "warm"})
    check("mets la face à 40", {"do": "level", "target": {"group": "A"}, "level": 40})
    check("allume la face", {"do": "color", "color": "white", "target": {"group": "A"}})
    check("plus fort", {"do": "level_rel", "delta": 20})
    check("éteins les contres", {"do": "level", "target": {"group": "C"}, "level": 0})
    check("commence par le rouge", {"do": "color", "target": {"all": True}})   # « par » ≠ PAR LED


def test_noir():
    for t in ("noir", "blackout", "éteins tout", "apaga todo", "alles aus", "暗転"):
        check(t, {"do": "blackout"})


def test_effets():
    check("envoie un effet rapide", {"do": "effect", "name": "Chase Rapide", "speed": 85})
    check("un effet lent", {"do": "effect", "speed": 25})
    check("lance un strobe rouge", {"do": "effect", "name": "Strobe Rouge"})
    check("arc en ciel", {"do": "effect", "name": "Rainbow"})
    check("send a fast effect", {"do": "effect", "speed": 85}, "en")
    check("lance police", {"do": "effect", "name": "Police"})
    check("plus vite", {"do": "speed_rel", "delta": 20})
    check("ralentis", {"do": "speed_rel", "delta": -20})
    check("vitesse 80", {"do": "speed", "value": 80})
    check("arrête l'effet", {"do": "stop_effects"})
    check("stop", {"do": "stop_effects"})


def test_memoire_lecture_fenetres():
    check("lance la mémoire 2.3", {"do": "memory", "id": "2.3"})
    check("mémoire deux point trois", {"do": "memory", "id": "2.3"})
    check("memory 4 1", {"do": "memory", "id": "4.1"}, "en")
    check("morceau suivant", {"do": "playback", "what": "next"})
    check("pause", {"do": "playback", "what": "play_pause"})
    check("ouvre le patch", {"do": "open", "window": "patch"})
    check("ouvre l'éditeur d'effets", {"do": "open", "window": "effects"})
    check("open the 3d view", {"do": "open", "window": "3d"}, "en")
    check("connecte le boîtier", {"do": "connect"})
    check("verbinde die Box", {"do": "connect"}, "de")
    check("crée ma fixture", {"do": "fixture"})
    check("create a new fixture", {"do": "fixture"}, "en")
    check("aide", {"do": "help"})


def test_plusieurs_actions():
    p = parse("allume la face en rouge et envoie un effet rapide", EFFECTS, "fr")
    assert [a["do"] for a in p.actions] == ["color", "effect"], p.actions


def test_apprentissage():
    p, a = first("apprends ambiance club = mémoire 2.1")
    assert a == {"do": "learn", "phrase": "ambiance club", "command": "mémoire 2.1"}, a
    p, a = first("Ambiance club !", aliases={normalize("ambiance club"): "mémoire 2.1"})
    assert a == {"do": "memory", "id": "2.1"}, a
    p, a = first("oublie ambiance club")
    assert a == {"do": "forget", "phrase": "ambiance club"}, a


def test_fondu():
    check("allume progressivement les lumières", {"do": "color", "target": {"all": True}, "fade": 4.0}, "fr")
    check("allume la face en rouge en 10 secondes", {"do": "color", "target": {"group": "A"}, "fade": 10.0})
    check("éteins tout doucement", {"do": "level", "level": 0, "fade": 4.0})
    check("fade the lights in over 5 seconds", {"do": "level", "level": 100, "fade": 5.0}, "en")
    check("enciende las luces poco a poco", {"do": "color", "fade": 4.0}, "es")
    check("effet doux", {"do": "effect"})                  # « doux » reste un style d'effet
    check("plus doucement", {"do": "speed_rel"})


def test_alternance_numeros_sauf():
    red, purple = {"hex": "#ff0000", "color": "red"}, {"hex": "#8800ff", "color": "purple"}
    check("un projecteur sur 2 en rouge et l'autre en violet", {"do": "pattern", "slots": [red, purple]})
    check("rouge et violet en alternance", {"do": "pattern", "slots": [red, purple]})
    check("every other light red, the others purple", {"do": "pattern", "slots": [red, purple]}, "en")
    check("éteins un projecteur sur trois", {"do": "pattern", "slots": [{"level": 0}, None, None]})
    check("eteints tout sauf le 3", {"do": "level", "level": 0, "target": {"all": True, "except": {"nums": [3]}}})
    check("le projecteur 3 en bleu", {"do": "color", "target": {"nums": [3]}})
    check("tout en rouge sauf la face", {"target": {"all": True, "except": {"group": "A"}}})
    p, _ = first("les projecteurs 1 et 3 en vert et envoie un effet rapide")
    assert [a["do"] for a in p.actions] == ["color", "effect"] and p.actions[0]["target"] == {"nums": [1, 3]}, p.actions
    p, _ = first("les pairs en rouge et les impairs en bleu")
    assert [a["target"].get("parity") for a in p.actions] == ["even", "odd"], p.actions
    p, _ = first("la face à 50 et les contres à 20")
    assert [a["level"] for a in p.actions] == [50, 20], p.actions


def test_noir_sur_une_cible():
    check("mets la face en noir", {"do": "level", "target": {"group": "A"}, "level": 0})   # pas allumée en blanc
    check("tout en noir", {"do": "blackout"})
    check("fais le noir stp", {"do": "blackout"})


def test_panne_diagnostic():
    for t in ("pourquoi ça bug ?", "mes projecteurs s'allument pas", "rien ne se passe", "it does not work", "no se encienden las luces", "funktioniert nicht"):
        check(t, {"do": "diagnose"})
    # Boîtier : l'état réel de MyStrow d'abord, puis la fiche de dépannage.
    acts = parse("mon interface usb ne répond plus").actions
    assert [a["do"] for a in acts] == ["diagnose", "answer"] and acts[1]["topic"] == "s_usb_dmx", acts
    check("le boîtier ne marche plus, relance-le", {"do": "connect"})     # panne + « relance » = reconnecter
    check("allume la face en rouge", {"do": "color"})


def test_faders_et_questions():
    check("monte progressivement les 4 faders", {"do": "fader", "faders": [1, 2, 3, 4], "level": 100, "fade": 4.0})
    check("descends tous les faders", {"do": "fader", "faders": list(range(1, 9)), "level": 0})
    check("descends le fader 2 à zéro en 5 secondes", {"do": "fader", "faders": [2], "level": 0, "fade": 5.0})
    check("les quatre premiers faders à 80", {"do": "fader", "faders": [1, 2, 3, 4], "level": 80})
    check("PEUT-on brancher un controleur dmx ?", {"do": "answer", "topic": "controller"})
    p, a = first("PEUX-TON BRANCHER une tablette ?")
    assert a == {"do": "answer", "topic": "tablet"} and p.actions[1] == {"do": "open", "window": "tablet"}, p.actions
    check("branche la tablette", {"do": "open", "window": "tablet"})
    check("connecte le boîtier", {"do": "connect"})
    check("c'est quoi la différence entre une lyre spot et wash ?", {"do": "answer", "topic": "generic"})
    check("tu peux allumer la face en rouge ?", {"do": "color", "target": {"group": "A"}})   # demande polie = ordre


def test_traduction_modele():
    """Réponses du modèle local (assistant_llm) → actions des règles. Sans le modèle."""
    from assistant_llm import to_nlu
    tr = lambda acts, text="x": to_nlu(acts, text, EFFECTS)
    a = tr([{"do": "light", "who": "all", "colors": ["red", "purple"], "level": 100}])[0]
    assert a["do"] == "pattern" and [s["color"] for s in a["slots"]] == ["red", "purple"], a
    a = tr([{"do": "light", "who": "all", "except_numbers": [3], "level": 0}])[0]
    assert a == {"do": "level", "target": {"all": True, "except": {"nums": [3]}}, "level": 0}, a
    a = tr([{"do": "light", "who": "front", "change": "down", "fade_seconds": 4}])[0]
    assert a == {"do": "level_rel", "target": {"group": "A"}, "delta": -20, "fade": 4.0}, a
    assert tr([{"do": "fader", "faders": [1, 2], "level": 100, "fade_seconds": 3}])[0]["fade"] == 3.0
    assert tr([{"do": "memory", "memory": "3,1"}])[0] == {"do": "memory", "id": "3.1"}
    assert tr([{"do": "memory", "memory": "9.9"}]) == [{"do": "unknown", "text": "x"}]     # hors grille
    assert tr([{"do": "playback", "playback": "previous"}])[0] == {"do": "playback", "what": "prev"}
    assert tr([{"do": "open", "window": "controller"}])[0] == {"do": "open", "window": "akai"}
    acts = tr([{"do": "question", "topic": "tablet"}])
    assert [x["do"] for x in acts] == ["answer", "open"], acts
    assert tr([{"do": "question", "topic": "other"}], "c'est quoi un gobo")[0]["topic"] == "generic"
    assert tr([{"do": "effect", "style": "fast"}], "effet rapide")[0]["speed"] == 85


def test_mouvements_themes_patch_rec():
    """v5 : lyres en mouvement, ambiances à thème, strobe un sur deux, patch, REC sur la musique."""
    check("fais tourner les lyres", {"do": "effect", "name": "Lyre Cercle"})
    check("un balancier sur les lyres", {"do": "effect", "name": "Lyre Balancier"})
    check("strobe un sur deux", {"do": "effect", "name": "Strobe Alternance"})
    _, a = first("une ambiance halloween sur la face")
    assert a["do"] == "pattern" and [s["color"] for s in a["slots"]] == ["orange", "purple"], a
    assert a["target"] == {"group": "A"}, a
    check("ajoute 4 PAR Betopper LM70", {"do": "patch_add", "query": "betopper lm70 par", "qty": 4})
    check("tu peux me patcher ma lyre sheilds ?", {"do": "patch_add", "query": "sheilds"})
    check("add two moving heads", {"do": "patch_add", "query": "moving head", "qty": 2})
    check("ouvre le patch", {"do": "open", "window": "patch"})          # « le patch » = la fenêtre
    check("ajoute du rouge", {"do": "color", "color": "red"})            # une couleur ne se patche pas
    check("turn the moving heads red", {"do": "color", "color": "red"})  # « moving » n'est pas un mouvement
    check("programme les lumières sur cette musique", {"do": "rec_generate", "color": None})
    check("fais un light show multicolore sur ce morceau", {"do": "rec_generate", "color": "rainbow"})
    check("program the lights to this song in blue", {"do": "rec_generate", "color": "blue"})
    check("tu peux me faire du chaud ?", {"do": "color", "color": "warm"})
    from assistant_llm import to_nlu
    a = to_nlu([{"do": "patch_add", "query": "Betopper LM70", "value": 4}], "x", EFFECTS)[0]
    assert a == {"do": "patch_add", "query": "betopper lm70", "qty": 4}, a
    a = to_nlu([{"do": "effect", "effect_kind": "movement"}], "fais tourner les lyres", EFFECTS)[0]
    assert a["name"] == "Lyre Cercle", a
    a = to_nlu([{"do": "rec_generate", "colors": ["red", "blue"]}], "programme cette chanson en rouge et bleu", EFFECTS)[0]
    assert a == {"do": "rec_generate", "color": "rainbow"}, a
    # « chanson d'après » ne programme rien : le REC ne s'ouvre pas.
    assert to_nlu([{"do": "rec_generate"}], "chanson d'après", EFFECTS)[0]["do"] == "unknown"


def test_suite_de_conversation():
    """Phrases qui dépendent de la précédente (essai réel du 29/10)."""
    from assistant_nlu import followup
    faders = {"kind": "fader", "faders": [1, 2, 3, 4, 5, 6, 7, 8], "effect": "Chase Blanc"}
    acts, _ = followup("parfait baisse les, mais doucement", faders)
    assert acts == [{"do": "fader_rel", "faders": faders["faders"], "delta": -20, "fade": 4.0}], acts
    acts, _ = followup("baisse-les à 20", faders)
    assert acts[0]["do"] == "fader" and acts[0]["level"] == 20, acts
    acts, _ = followup("coupe-les", {"kind": "target", "target": {"group": "A"}})
    assert acts == [{"do": "level", "target": {"group": "A"}, "level": 0}], acts
    effect = {"kind": "effect", "effect": "Chase Blanc"}
    acts, _ = followup("QUE ça prenne sur tous les projos", effect)
    assert acts == [{"do": "effect", "name": "Chase Blanc", "all": True}], acts
    # « non » n'est jamais un stop : précision, ou relance de l'effet.
    assert followup("non, je parlais de l'effet !", effect)[0] == [{"do": "clarify", "about": "effect"}]
    acts, _ = followup("mais non, remet les effets mais sur tous les groupes", faders)
    assert acts == [{"do": "effect", "name": "Chase Blanc", "all": True}], acts
    acts, txt = followup("non, en bleu", {})
    assert acts is None and parse(txt, EFFECTS).actions[0]["color"] == "blue", txt
    # Couleur refusée : retirée, même redite autrement (« chaude »).
    acts, txt = followup("non pas blanc chaud, je veux une ambiance un peu type chaude rouge et blanc tu me suis ?", {})
    a = parse(txt, EFFECTS).actions[0]
    assert a["do"] == "pattern" and [s["color"] for s in a["slots"]] == ["red", "white"], (txt, a)
    assert followup("allume la face en rouge", faders)[0] is None          # phrase autonome : rien à reprendre
    _, a = first("lance un effet")
    assert "strobe" not in normalize(a["name"]), a                         # un effet sans précision n'est pas un strobe


def test_depannage_clients():
    import assistant_support
    for t, key, lang in (("mes lyres bougent toutes seules", "fixture_mode", "fr"),
                         ("trend micro a mis MyStrow en quarantaine", "antivirus", "fr"),
                         ("I never received my license email", "licence_mail", "en"),
                         ("los focos se mueven solos", "fixture_mode", "es"),
                         ("o strobe não funciona", "strobe", "pt")):
        p = parse(t)
        assert p.actions[-1] == {"do": "answer", "topic": "s_" + key}, (t, p.actions)
        assert p.lang == lang, (t, p.lang)
    for t in ("mets un strobe mais pas trop vite", "met la face en orange au lieu du rouge", "connecte le boîtier",
              "y a plus rien qui sort en DMX, reconnecte", "est-ce qu'on peut brancher une tablette ?"):
        assert not any(str(a.get("topic", "")).startswith("s_") for a in parse(t).actions), t
    # Chaque sujet a sa réponse dans les 6 langues, avec l'adresse du support.
    for key, *_ in assistant_support.TOPICS:
        for lang in ("fr", "en", "es", "de", "pt", "ja"):
            assert lang in assistant_support.ANSWERS[key], (key, lang)
        assert assistant_support.SUPPORT_EMAIL in assistant_support.answer(key, "fr")


def test_position_lyres():
    check("place mes lyres en l'air", {"do": "position", "where": "up", "target": {"kind": "lyre"}}, "fr")
    check("place mes lyres au sol", {"do": "position", "where": "down", "target": {"kind": "lyre"}})
    check("lève les lyres", {"do": "position", "where": "up"})
    check("mets les lyres vers le public", {"do": "position", "where": "public", "target": {"kind": "lyre"}})
    check("recentre les lyres", {"do": "position", "where": "center"})
    check("les faisceaux vers le ciel", {"do": "position", "where": "up", "target": {"kind": "lyre"}})
    check("pointe la face au sol", {"do": "position", "where": "down", "target": {"group": "A"}})
    check("point the moving heads at the ceiling", {"do": "position", "where": "up"}, "en")
    check("pon las cabezas moviles hacia arriba", {"do": "position", "where": "up"}, "es")
    check("richte die moving heads nach oben", {"do": "position", "where": "up"}, "de")
    check("coloca as cabeças móveis para o chão", {"do": "position", "where": "down"}, "pt")
    check("ムービングを天井に向けて", {"do": "position", "where": "up"}, "ja")
    # « mets » seul n'allume pas en blanc ; une couleur ou un niveau dits, si.
    assert [a["do"] for a in parse("mets les lyres en l'air", EFFECTS).actions] == ["position"]
    acts = parse("mets les lyres au sol en rouge", EFFECTS).actions
    assert [a["do"] for a in acts] == ["position", "color"] and acts[1]["color"] == "red", acts
    acts = parse("envoie les lyres sur le public à 50 %", EFFECTS).actions
    assert [a["do"] for a in acts] == ["position", "level"] and acts[1]["level"] == 50, acts
    # « baisse » dit le mouvement quand il y a une visée, le niveau sinon.
    assert [a["do"] for a in parse("baisse les lyres vers le sol", EFFECTS).actions] == ["position"]
    check("baisse les lyres", {"do": "level_rel", "delta": -20})
    acts = parse("les lyres impaires en l'air, les paires au sol", EFFECTS).actions
    assert [(a["where"], a["target"].get("parity")) for a in acts] == [("up", "odd"), ("down", "even")], acts
    # Pas de visée : la face au centre, un constat, une question « comment ».
    check("mets la face au centre", {"do": "color"})
    check("ils sont encore au sol", {"do": "chat"})
    check("comment je mets mes lyres en l'air ?", {"do": "answer"})
    import assistant_llm
    tr = assistant_llm.to_nlu([{"do": "effect", "effect_kind": "movement"}], "place mes lyres en l'air", EFFECTS)
    assert tr[0]["do"] == "position", tr          # le modèle v6 ne connaît pas la visée : les règles l'emportent


def test_visee_geometrie():
    import types
    import light_actions as la

    def lyre(**kw):
        p = types.SimpleNamespace(group="lyre", fixture_type="Moving Head", pan=32768, tilt=32768, name="L",
                                  start_address=1, pan_min=0, pan_max=65535, tilt_min=0, tilt_max=65535,
                                  pan_range=540.0, tilt_range=270.0, rot3d_x=0.0, rot3d_z=0.0, body_rotation=0.0)
        p.__dict__.update(kw)
        return p

    def aims(p, where):
        return la.beam_dir(p, *la.aim_values(p, where))

    hung, floor = lyre(), lyre(rot3d_x=180.0)
    assert la.aim_values(hung, "down") == (32768, 32768)       # accrochée : droit en bas au centre
    assert la.aim_values(floor, "up") == (32768, 32768)        # posée : droit en haut au centre
    d = aims(hung, "up")
    assert d[1] > 0.7 and d[2] > 0, d                          # monte, côté scène (pas dans les yeux du public)
    d = aims(hung, "public")
    assert d[2] < -0.9 and d[1] < 0, d                         # vers la salle (Z négatifs), un peu plongeant
    assert aims(floor, "down")[1] < -0.7
    bride = lyre(tilt_min=20000, tilt_max=45000)
    pan, tilt = la.aim_values(bride, "public")
    assert 20000 <= tilt <= 45000 and pan == 32768, (pan, tilt)  # limites respectées, pas de demi-tour de pan

    # Une position enregistrée « Sol » passe avant le calcul.
    moved = []
    w = types.SimpleNamespace(projectors=[hung, lyre(fixture_type="PAR LED", group="face")],
                              position_presets=[{"name": "Sol", "projectors": [{"start_address": 1, "pan": 1000,
                                                                                 "tilt": 2000}]}],
                              _start_pan_tilt_transition=lambda p, pan, tilt, ms: moved.append((pan, tilt)))
    assert la.aim(w, [0, 1], "down") == (1, "Sol") and moved == [(1000, 2000)], moved
    assert hung._manual_move
    moved.clear()
    assert la.aim(w, [0], "up") == (1, None) and moved == [la.aim_values(hung, "up")]


def test_incompris():
    p, a = first("raconte-moi une blague")
    assert a["do"] == "unknown" and not p.understood


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK  {name}")
            except AssertionError as e:
                fails += 1
                print(f"ÉCHEC {name} : {e}")
    sys.exit(1 if fails else 0)
