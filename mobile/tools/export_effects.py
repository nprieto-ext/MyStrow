"""Exporte la bibliothèque d'effets du PC vers le mode autonome de la tablette.

Source unique : effect_editor.BUILTIN_EFFECTS. On n'en garde que les effets que
le moteur de la tablette (mobile/src/engine.js) sait jouer à l'identique :
couches lumière (RGB, Dimmer, Strobe, R, V, B, Permut) et mouvement (Pan,
Tilt, Pan/Tilt). Les couches Gobo et roue de couleurs ne sont pas portées.
Les trajectoires Pan/Tilt (PAN_TILT_SHAPES) sont exportées avec.

    python mobile/tools/export_effects.py     → mobile/src/effects.js

À relancer après toute modification de BUILTIN_EFFECTS, puis
test_engine_parity.py.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

from effect_editor import BUILTIN_EFFECTS, PAN_TILT_SHAPES  # noqa: E402

SUPPORTED = {"RGB", "Dimmer", "Strobe", "R", "V", "B", "Permut", "Pan", "Tilt", "Pan/Tilt"}

# Boutons d'effet par défaut : ceux de « Charger les effets par défaut » du PC
# (main_window, DEFAULT_EFFECTS), sauf Bascule — un échange de couleurs
# ponctuel, pas une couche — remplacé par Vague.
DEFAULT_BUTTONS = ["Strobe Classique", "Chase Doux", "Pulse Doux", "Rainbow",
                   "Comète", "Vague", "Ping Pong", "Police"]


def playable(effects):
    # Deux effets portent le même nom (Comète, Explosion) : comme le PC, qui
    # les range dans un dict par nom, le dernier défini l'emporte.
    # « Bascule » est exclu : sur le PC, ce NOM déclenche un échange de
    # couleurs ponctuel (toggle_effect → _bascule), pas ses couches.
    by_name = {}
    for e in effects:
        if (e["name"] != "Bascule" and e.get("layers")
                and all(l.get("attribute") in SUPPORTED for l in e["layers"])):
            by_name.pop(e["name"], None)
            by_name[e["name"]] = e
    # Regroupés par catégorie (ordre de première apparition), pour la liste de choix.
    cats = list(dict.fromkeys(e.get("category", "") for e in by_name.values()))
    ordered = sorted(by_name.values(), key=lambda e: cats.index(e.get("category", "")))
    return [{"name": e["name"], "category": e.get("category", ""),
             "no_color": bool(e.get("no_color")), "layers": e["layers"]}
            for e in ordered]


def main():
    effects = playable(BUILTIN_EFFECTS)
    names = {e["name"] for e in effects}
    missing = [n for n in DEFAULT_BUTTONS if n not in names]
    if missing:
        sys.exit(f"Effets par défaut introuvables : {missing}")
    out = os.path.join(REPO, "mobile", "src", "effects.js")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("// GÉNÉRÉ par mobile/tools/export_effects.py depuis effect_editor.BUILTIN_EFFECTS.\n"
                 "// Ne pas modifier à la main : relancer le script.\n")
        fh.write("(function (root) {\n  const api = ")
        shapes = {k: {"pan": list(v["pan"]), "tilt": list(v["tilt"])} for k, v in PAN_TILT_SHAPES.items()}
        fh.write(json.dumps({"effects": effects, "defaults": DEFAULT_BUTTONS, "shapes": shapes},
                            ensure_ascii=False, indent=1))
        fh.write(";\n  if (typeof module !== \"undefined\" && module.exports) module.exports = api;\n"
                 "  else root.MystrowEffects = api;\n"
                 "})(typeof window !== \"undefined\" ? window : globalThis);\n")
    print(f"{len(effects)} effets exportés → {os.path.relpath(out, REPO)}")


if __name__ == "__main__":
    main()
