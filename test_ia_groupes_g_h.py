# -*- coding: utf-8 -*-
"""Mode IA / LIVE : les groupes G et H sont enfin pilotes.

Avant le 10/09/2026, `audio_ai.get_state_at` ne renvoyait que SIX cles de
groupe (face, lat, contre, douche1-3). Le moteur LIVE saute les projecteurs
dont le groupe est absent de cet etat :

    if p.group not in state:
        continue          # main_window._apply_live_state_inner

Un PAR pose en groupe G ou H n'etait donc ni allume ni eteint : il restait
FIGE sur sa derniere couleur pendant tout le show. Seules les lyres s'en
sortaient, parce que le bloc lyres ramasse tous les Moving Head sans regarder
le groupe.

Trois volets :
  A. G et H sortent bien de l'IA, et l'accent tourne dessus.
  B. Non-regression stricte sur D/E/F : un plan de feu sans rien en G/H doit
     produire EXACTEMENT ce qu'il produisait avant.
  C. Le piege du bloc lyres (`_IA_BASE_COLOR_GROUPS`).
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow")

from PySide6.QtGui import QColor

from audio_ai import AudioColorAI, ACCENT_GROUPS

echecs = []


def verifie(cond, message):
    if cond:
        print(f"  OK   {message}")
    else:
        print(f"  ECHEC {message}")
        echecs.append(message)


def _ia():
    ai = AudioColorAI()
    ai.set_dominant_color(QColor("#ff0044"))
    ai.beats = list(range(0, 30000, 500))     # 120 BPM
    ai.energy_map = [0.6] * 600
    ai.analyzed = True
    return ai


# ===========================================================================
# A. G et H existent dans l'etat IA
# ===========================================================================
print("\nA. Les groupes G et H sortent de l'IA")

st = _ia().get_state_at(5000, 60000)
verifie('groupe_g' in st and 'groupe_h' in st,
        "get_state_at renvoie groupe_g et groupe_h")

attendus = {'face', 'lat', 'contre'} | set(ACCENT_GROUPS)
verifie(attendus <= set(st),
        f"les {len(attendus)} groupes A-H sont tous presents")

verifie(isinstance(st['groupe_g'], tuple) and len(st['groupe_g']) == 2
        and isinstance(st['groupe_g'][0], QColor),
        "la valeur de G a la meme forme que les autres : (QColor, niveau)")

# L'accent doit reellement passer sur G : sinon il serait allume mais plat.
ai = _ia()
niveaux_g = {ai.get_state_at(t, 60000)['groupe_g'][1]
             for t in range(0, 8000, 100)}
verifie(len(niveaux_g) > 1 and max(niveaux_g) > 60,
        f"l'accent monte bien sur G (niveaux {min(niveaux_g)} -> {max(niveaux_g)})")

ai = _ia()
st = ai.get_state_at(5000, 60000, max_dimmers={'groupe_g': 0})
verifie(st['groupe_g'][1] == 0,
        "le plafond `max_dimmers` s'applique a G comme aux autres")


# ===========================================================================
# B. Non-regression : un plan sans G/H ne bouge pas d'un poil
# ===========================================================================
print("\nB. Plan de feu sans G ni H : comportement d'avant, a l'identique")

POOL3 = ['douche1', 'douche2', 'douche3']

ai = _ia()
phases = {ai._def_chase_idx
          for t in range(0, 8000, 250)
          if ai.get_state_at(t, 60000, accent_groups=POOL3) or True}
verifie(phases == {0, 1, 2},
        f"le chenillard garde ses TROIS temps (vu : {sorted(phases)})")

ai = _ia()
st = ai.get_state_at(5000, 60000, accent_groups=POOL3)
verifie('groupe_g' not in st and 'groupe_h' not in st,
        "aucune cle parasite pour des groupes vides")

# Formule d'avant, recopiee telle quelle depuis l'ancien code.
ai = _ia()
ecarts = []
for t in range(0, 8000, 137):
    st = ai.get_state_at(t, 60000, accent_groups=POOL3)
    idx = ai._contre_color_idx
    pal = ai.palette
    attendu = {
        'douche1': pal[idx % len(pal)],
        'douche2': pal[(idx + 2) % len(pal)],
        'douche3': pal[(idx + 4) % len(pal)],
    }
    for g, coul in attendu.items():
        # En flash tous les groupes passent au blanc : hors sujet ici.
        if st[g][0] == QColor(255, 255, 255):
            continue
        if st[g][0] != coul:
            ecarts.append((t, g))
verifie(not ecarts,
        f"les couleurs de D/E/F suivent la meme formule qu'avant ({len(ecarts)} ecart(s))")


# ===========================================================================
# C. Le piege du bloc lyres
# ===========================================================================
print("\nC. Le bloc lyres ne doit PAS suivre les cles de `state`")

import main_window as mw

CIBLE = mw.MainWindow._IA_BASE_COLOR_GROUPS
verifie(CIBLE == frozenset(('face', 'lat', 'contre',
                            'douche1', 'douche2', 'douche3')),
        "_IA_BASE_COLOR_GROUPS reste fige sur les SIX groupes historiques")

verifie('groupe_g' not in CIBLE and 'groupe_h' not in CIBLE,
        "G et H en sont exclus : leurs lyres gardent leur couleur per-lyre")

# Le test du bloc lyres doit porter sur la constante, pas sur `state` : sinon
# il basculerait tout seul et volerait la couleur des lyres de G/H.
import io
src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'main_window.py'), encoding='utf-8').read()
verifie('if p.group not in self._IA_BASE_COLOR_GROUPS:' in src,
        "le bloc lyres teste la constante...")
verifie('if p.group not in state:' in src,
        "...et la boucle de base teste bien `state`, elle (inchangee)")


# ===========================================================================
print()
if echecs:
    print(f"{len(echecs)} ECHEC(S) :")
    for e in echecs:
        print(f"  - {e}")
    sys.exit(1)
print("Tout est vert.")
