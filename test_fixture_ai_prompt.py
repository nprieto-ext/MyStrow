"""
« Créer votre fixture via IA » : la réponse collée depuis ChatGPT / Gemini /
Claude doit donner une fixture de bibliothèque valide, même quand l'IA n'a pas
suivi le format à la lettre (texte autour, virgules finales, types inventés).
"""
import json

from fixture_ai_prompt import build_prompt, parse_ai_response, VALID_TYPES
from fixture_editor import ALL_CHANNEL_TYPES, FIXTURE_TYPES
import fixture_ai_prompt as fap


SPOT = {
    "format": "mystrow-fixture", "version": "1",
    "name": "Spot 60W", "manufacturer": "Shehds", "fixture_type": "Moving Head",
    "modes": [
        {"name": "11CH",
         "profile": ["Pan", "PanFine", "Tilt", "TiltFine", "Speed", "Dim",
                     "Shutter", "ColorWheel", "Gobo1", "Gobo1Rot", "Preset1"],
         "labels": ["Pan", "Pan fin", "Tilt", "Tilt fin", "Vitesse", "Gradateur",
                    "Strobe", "Couleur", "Gobo", "Rotation gobo", "Programmes"]},
        {"name": "9CH",
         "profile": ["Pan", "Tilt", "Speed", "Dim", "Shutter", "ColorWheel",
                     "Gobo1", "Gobo1Rot", "Preset1"]},
    ],
    "color_wheel_slots": [{"name": "Blanc", "color": "#FFFFFF", "dmx": 5},
                          {"name": "Rouge", "color": "#ff0000", "dmx": 15}],
    "gobo_wheel_slots": [{"name": "Gobo 1", "color": "#123456", "dmx": 12}],
    "preset_slots": {"Preset1": [{"name": "Son", "color": "#00cc99", "dmx": 220}]},
    "channel_ranges": {"Pan": [0, 255], "Tilt": [0, 127]},
}


def test_prompt_liste_exactement_les_types_de_l_editeur():
    # Un type absent du prompt ne serait jamais choisi par l'IA ; un type que
    # l'éditeur ne connaît pas casserait la fixture.
    assert set(VALID_TYPES) == set(ALL_CHANNEL_TYPES)
    assert fap._FIXTURE_TYPES == FIXTURE_TYPES
    p = build_prompt("fr")
    for t in ALL_CHANNEL_TYPES + FIXTURE_TYPES:
        assert t in p
    assert "French" in p


def test_reponse_propre():
    fx = parse_ai_response("```json\n" + json.dumps(SPOT) + "\n```")
    assert fx["name"] == "Spot 60W"
    assert fx["fixture_type"] == "Moving Head"
    assert fx["profile"] == SPOT["modes"][0]["profile"]
    assert fx["labels"][6] == "Strobe"
    assert len(fx["modes"]) == 2 and "labels" not in fx["modes"][1]
    assert fx["color_wheel_slots"][0]["color"] == "#ffffff"
    assert fx["gobo_wheel_slots"][0]["color"] == "#888888"
    assert fx["preset_slots"]["Preset1"][0]["dmx"] == 220
    # 0-255 = pas de bride : ne doit pas être enregistré.
    assert fx["channel_ranges"] == {"Tilt": [0, 127]}
    assert fx["source"] == "user" and fx["group"] == "face"


def test_reponse_sale_texte_autour_virgules_types_inventes():
    txt = ("Voici le fichier pour votre PAR :\n\n```\n{\n"
           '  "name": "Par 7x10",\n  "fixture_type": "par",\n'
           '  "modes": [{"name": "8CH", "profile": ["Dimmer", "Red", "green", "Blue",'
           ' "White", "Strobe", "Macro", "Bidule"],},],\n}\n```\nBon show !')
    fx = parse_ai_response(txt)
    assert fx["fixture_type"] == "PAR LED"
    assert fx["profile"] == ["Dim", "R", "G", "B", "W", "Strobe", "Preset1", "Unused"]
    assert fx["manufacturer"] == "Générique"
    # Labels de longueur différente du profil : ignorés plutôt que décalés.
    assert "labels" not in fx


def test_doublon_de_type_passe_en_unused():
    obj = {"name": "X", "modes": [{"profile": ["Dim", "R", "G", "B", "Dim"]}]}
    fx = parse_ai_response(json.dumps(obj))
    assert fx["profile"] == ["Dim", "R", "G", "B", "Unused"]
    assert fx["modes"][0]["channelCount"] == 5


def test_machine_a_fumee_garde_son_debit():
    obj = {"name": "Fog 900", "fixture_type": "Machine a fumee",
           "modes": [{"profile": ["Smoke"], "labels": ["Débit"]}]}
    fx = parse_ai_response(json.dumps(obj))
    assert fx["profile"] == ["Smoke"]


def test_reponse_inexploitable_message_clair():
    for txt in ["", "   ", "Désolé, je ne peux pas.", '{"name": "X", "modes": []}']:
        try:
            parse_ai_response(txt)
        except ValueError:
            continue
        raise AssertionError(f"accepté à tort : {txt!r}")


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("OK ", _n)
