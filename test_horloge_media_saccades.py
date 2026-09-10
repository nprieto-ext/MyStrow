# -*- coding: utf-8 -*-
"""Horloge lumiere lissee + parite du mouvement aperçu / restitution.

Contexte (08/09/2026) : « en montage tout est fluide, en playlist les lyres
saccadent ». Deux causes mesurees :
  - `QMediaPlayer.position()` avance par bonds (0 a 116 ms sur une image de
    46,9 ms), et TOUT le mouvement se calculait dessus ;
  - l'aperçu de l'editeur ne jouait pas du tout `move_effect`.
"""
import math
import sys
import time

from core import MediaClock, TIMELINE_FRAME_MS
from light_timeline import movement_pan_tilt, clip_has_movement

_ok, _ko = 0, 0


def check(label, cond, detail=""):
    global _ok, _ko
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _ko += 1
        print(f"  ECHEC {label} {detail}")


# ── 1. L'horloge lisse les bonds de position() ────────────────────────────────
print("\n1. Horloge media lissee")

# Sequence relevee sur une vraie lecture video : le temps reel avance d'un pas
# constant, la position du lecteur fait des bonds de 0, 40 ou 116 ms.
BONDS = [40, 0, 116, 46, 46, 0, 93, 40, 47, 47, 0, 116, 40, 46, 47]
PAS_REEL = 0.0469   # 46,9 ms d'image, comme mesure

clk = MediaClock()
raw, brut, lisse = 0, [], []
t_faux = [0.0]
_vrai_monotonic = time.monotonic
time.monotonic = lambda: t_faux[0]          # horloge deterministe
try:
    clk.update(0)
    for d in BONDS:
        t_faux[0] += PAS_REEL
        raw += d
        brut.append(d)
        lisse.append(clk.update(raw))
finally:
    time.monotonic = _vrai_monotonic

pas_lisses = [lisse[i + 1] - lisse[i] for i in range(len(lisse) - 1)]


def ecart_type(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


et_brut, et_lisse = ecart_type(brut), ecart_type(pas_lisses)
print(f"     ecart-type des pas : brut {et_brut:.1f} ms -> lisse {et_lisse:.1f} ms")
check("l'horloge lissee est bien plus reguliere que la brute",
      et_lisse < et_brut / 5, f"(brut {et_brut:.1f}, lisse {et_lisse:.1f})")
check("aucune image ne recule", all(p >= 0 for p in pas_lisses), str(pas_lisses))
check("aucune image ne fige (0 ms)", all(p > 0 for p in pas_lisses), str(pas_lisses))
check("pas de derive : l'horloge reste collee au lecteur",
      abs(lisse[-1] - raw) < 60, f"(lisse {lisse[-1]}, brut {raw})")

# Temoin : sans lissage, le calcul saute bien — sinon le test ne prouve rien.
check("TEMOIN : la position brute, elle, fige et bondit",
      0 in brut and max(brut) > 2 * PAS_REEL * 1000)

# Un seek doit etre suivi immediatement, pas rattrape en douceur.
clk2 = MediaClock()
clk2.update(10000)
check("un seek (> RESYNC_MS) est suivi tout de suite",
      abs(clk2.update(45000) - 45000) < 5)

# Une image en retard (freeze UI) ne doit pas propulser l'horloge.
clk3 = MediaClock()
t_faux[0] = 0.0
time.monotonic = lambda: t_faux[0]
try:
    clk3.update(1000)
    t_faux[0] += 30.0            # 30 s de gel
    pos = clk3.update(1000)
finally:
    time.monotonic = _vrai_monotonic
check("une image en retard ne propulse pas l'horloge", pos - 1000 <= 600, f"(+{pos-1000} ms)")


# ── 2. Parite du mouvement : meme calcul des deux cotes ───────────────────────
print("\n2. Parite du mouvement aperçu / restitution")


class ClipObjet:
    """Ce que manipule l'aperçu de l'editeur (attributs)."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


for eff in ('cercle', 'figure8', 'balayage_h', 'balayage_v', 'aleatoire', None):
    d = {'move_effect': eff, 'move_speed': 0.7, 'move_amplitude': 80,
         'pan_start': 100, 'tilt_start': 140, 'pan_end': 200, 'tilt_end': 60}
    o = ClipObjet(**d)
    for el, pr in ((0.0, 0.0), (1.37, 0.25), (4.2, 0.9)):
        a = movement_pan_tilt(d.get, el, pr)
        b = movement_pan_tilt(lambda k, dv=None: getattr(o, k, dv), el, pr)
        check(f"{eff or 'trajectoire'} @ {el}s : dict == objet", a == b, f"{a} != {b}")

# Un mouvement automatique doit reellement bouger dans le temps.
for eff in ('cercle', 'figure8', 'balayage_h', 'balayage_v', 'aleatoire'):
    g = {'move_effect': eff, 'move_speed': 0.5, 'move_amplitude': 60,
         'pan_start': 128, 'tilt_start': 128}.get
    vals = {movement_pan_tilt(g, t / 4.0, 0.0) for t in range(8)}
    check(f"{eff} balaie vraiment", len(vals) > 3, f"({len(vals)} positions distinctes)")

check("clip_has_movement voit un move_effect",
      clip_has_movement({'move_effect': 'cercle'}.get))
check("clip_has_movement voit une trajectoire",
      clip_has_movement({'pan_start': 40, 'pan_end': 200}.get))
check("clip_has_movement ignore un clip sans mouvement",
      not clip_has_movement({'pan_start': 128, 'tilt_end': 128}.get))

# Bornes DMX 16 bits, meme a amplitude et centre extremes.
g = {'move_effect': 'cercle', 'move_speed': 2.0, 'move_amplitude': 120,
     'pan_start': 255, 'tilt_start': 0}.get
bornes = [movement_pan_tilt(g, t / 10.0, 0.0) for t in range(40)]
check("pan/tilt restent dans 0-65535",
      all(0 <= p <= 65535 and 0 <= t <= 65535 for p, t in bornes))


# ── 3. Cadence commune ────────────────────────────────────────────────────────
print("\n3. Cadence")
import io
src_seq = io.open('sequencer.py', encoding='utf-8').read()
src_ed  = io.open('timeline_editor.py', encoding='utf-8').read()
check("la restitution demarre sur TIMELINE_FRAME_MS",
      'timeline_playback_timer.start(TIMELINE_FRAME_MS)' in src_seq)
check("l'aperçu demarre sur TIMELINE_FRAME_MS",
      'playback_timer.start(TIMELINE_FRAME_MS)' in src_ed)
check("plus aucun start(50) sur la restitution",
      'timeline_playback_timer.start(50)' not in src_seq)
check("les deux moteurs utilisent make_precise_timer",
      'make_precise_timer()' in src_seq and 'make_precise_timer()' in src_ed)
check("l'aperçu appelle bien movement_pan_tilt",
      'movement_pan_tilt' in src_ed)
check("la restitution n'a plus sa copie du calcul",
      "move_effect == 'figure8'" not in src_seq)
check("TIMELINE_FRAME_MS vaut 40", TIMELINE_FRAME_MS == 40)

print(f"\n{_ok} OK, {_ko} echec(s)")
sys.exit(1 if _ko else 0)
