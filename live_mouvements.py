"""
Mouvements de lyres du moteur IA (LIVE et IA Lumière) — calcul pur, sans Qt.

── Pourquoi ce module (retour client, 20/10/2026) ──────────────────────────────
« Les motifs de lyres se répètent trop vite et ne se calent pas sur le beat. »
Deux causes, toutes deux dans `MainWindow._apply_live_state_inner` :

  1. La rotation avançait à une vitesse en tours/seconde tirée de la section et
     de l'énergie, sans jamais lire le BPM : un cercle durait ~8 s quel que soit
     le tempo et ne retombait jamais sur une mesure.
  2. La réserve de mouvements par défaut ne contenait que `cercle` : un client
     « plug and play » voyait le même cercle tout le show. Et quand plusieurs
     motifs étaient cochés, ils défilaient dans l'ordre, au chronomètre.

D'où :
  · un cycle de motif = un nombre ENTIER de temps, fixé par la section
    (`CYCLE_TEMPS`) ; la phase est recalée sur chaque beat ;
  · le curseur VITESSE devient un multiplicateur par puissances de 2, pour que
    le cycle reste un multiple ou un diviseur de la mesure ;
  · le motif change sur une phrase musicale ou un changement de section,
    jamais au milieu d'une mesure, avec un fondu d'un temps ;
  · la tuile AUTO : le moteur choisit lui-même le motif selon la section.

Tout ce qui est ici est déterministe à graine près et testable sans fenêtre
(`test_live_mouvements.py`).
"""

import math
import random

# Clé de la tuile « le moteur choisit ». Exclusive des motifs : cochée, elle
# est seule dans la réserve.
AUTO = 'auto'

# Motifs concrets connus du moteur. `random` n'a pas de tuile : il n'est joué
# que par AUTO, sur les drops.
MOTIFS = ('vague', 'cercle', 'diagonale', 'spirale', 'bounce', 'huit', 'random')

# Durée d'un cycle de motif, en temps, à VITESSE 50 %. Puissances de 2 :
# 32 = 8 mesures, 16 = 4, 8 = 2, 4 = 1.
CYCLE_TEMPS = {
    'quiet': 32,
    'verse': 16,
    'build': 8,
    'high':  8,
    'drop':  4,
}

# Familles de motifs proposées par AUTO, de la plus calme à la plus nerveuse.
FAMILLES_AUTO = {
    'quiet': ('vague', 'cercle'),
    'verse': ('cercle', 'huit', 'vague', 'diagonale'),
    'build': ('spirale', 'huit', 'diagonale'),
    'high':  ('huit', 'diagonale', 'cercle', 'bounce'),
    'drop':  ('bounce', 'random', 'diagonale'),
}

# Un changement de section ne relance pas un motif avant ce nombre de temps :
# l'analyse peut hésiter entre deux sections, et un motif qui change à chaque
# temps se lit comme un bug, pas comme une intention.
TENUE_MIN_TEMPS = 8

# Correction de phase appliquée à chaque beat (fraction de l'écart).
RECALAGE = 0.35


def cycle_temps(section: str) -> int:
    return CYCLE_TEMPS.get(section, 16)


def multiplicateur_vitesse(vitesse: int) -> float:
    """Curseur VITESSE (0-100) → multiplicateur de cadence.

    0 = lyres arrêtées (comportement existant du curseur). Sinon 25 → ×0,5,
    50 → ×1, 75 → ×2, 100 → ×4. Arrondi à la puissance de 2 la plus proche :
    un ×1,3 décalerait le cycle de la mesure à chaque tour.
    """
    if vitesse < 2:
        return 0.0
    return 2.0 ** max(-2, min(2, round((vitesse - 50) / 25.0)))


def temps_par_phrase(duree: int) -> int:
    """Curseur DURÉE (0-100) → nombre de temps avant de changer de motif.

    8 / 16 / 32 / 64 temps : toujours une phrase musicale entière.
    Défaut 40 % → 16 temps (4 mesures).
    """
    return 8 * 2 ** max(0, min(3, round(duree / 100.0 * 3)))


def bpm_depuis_beats(beats, idx: int) -> float:
    """BPM médian des 8 derniers intervalles jusqu'au beat `idx` ; 0 si inconnu.

    Médiane plutôt que moyenne : un beat manqué double un intervalle, un faux
    beat le coupe en deux, la moyenne en serait tirée et la lyre avec.
    """
    if idx < 2 or idx >= len(beats):
        return 0.0
    fen = beats[max(0, idx - 8): idx + 1]
    ivs = sorted(b - a for a, b in zip(fen, fen[1:]) if b > a)
    if not ivs:
        return 0.0
    med = ivs[len(ivs) // 2]
    bpm = 60000.0 / med if med > 0 else 0.0
    return bpm if 50.0 <= bpm <= 220.0 else 0.0


def vitesse_tours_s(bpm: float, section: str, mult: float) -> float:
    """Cadence cible en tours/seconde, calée sur le tempo."""
    if bpm <= 0 or mult <= 0:
        return 0.0
    return (bpm / 60.0) * mult / cycle_temps(section)


def recaler_phase(phase: float, section: str, mult: float,
                  force: float = RECALAGE) -> float:
    """Ramène la phase vers la grille des temps, à appeler sur chaque beat.

    Sur un beat, la phase « devrait » tomber sur un multiple du pas d'un temps.
    On ne la colle pas : un saut se verrait sur la lyre. On corrige une fraction
    de l'écart à chaque temps — en 3-4 temps le motif est calé.
    """
    if mult <= 0:
        return phase
    pas = 2.0 * math.pi * mult / cycle_temps(section)
    cible = round(phase / pas) * pas
    return (phase + force * (cible - phase)) % (2.0 * math.pi)


def choisir_auto(section: str, precedent: str, rnd: random.Random) -> str:
    """Motif suivant pour la tuile AUTO — jamais deux fois le même d'affilée."""
    famille = [m for m in FAMILLES_AUTO.get(section, FAMILLES_AUTO['verse'])
               if m != precedent]
    if not famille:
        famille = [m for m in MOTIFS if m != precedent and m != 'random']
    return rnd.choice(famille)


def motif_suivant(reserve, courant: str, section: str,
                  rnd: random.Random) -> str:
    """Motif à jouer au prochain changement : AUTO choisit, sinon on avance
    dans la réserve dans l'ordre des tuiles (comportement historique)."""
    if AUTO in reserve:
        return choisir_auto(section, courant, rnd)
    concrets = [m for m in reserve if m in MOTIFS]
    if not concrets:
        return courant
    try:
        i = concrets.index(courant)
    except ValueError:
        i = -1
    return concrets[(i + 1) % len(concrets)]


def doit_changer(temps_depuis: int, section: str, section_au_changement: str,
                 phrase: int) -> bool:
    """Faut-il changer de motif sur CE beat ?

    Oui sur une phrase entière, ou sur un changement de section — mais pas
    avant `TENUE_MIN_TEMPS` dans ce second cas.
    """
    if temps_depuis >= phrase:
        return True
    return section != section_au_changement and temps_depuis >= TENUE_MIN_TEMPS


def _alea(graine: int):
    """Point pseudo-aléatoire stable dans [-1, 1]² (même graine → même point)."""
    x = (((graine * 1664525 + 1013904223) & 0xFFFF) / 32767.5) - 1.0
    y = (((graine * 22695477 + 1) & 0xFFFF) / 32767.5) - 1.0
    return x, y


def motif_xy(motif: str, ph: float, temps: int = -1, frac: float = 1.0,
             lyre: int = 0):
    """Position normalisée (pan, tilt) dans [-1, 1] pour une lyre.

    `ph` : phase de la lyre (décalage inclus). `temps`/`frac` : index du beat
    courant et avancement dans ce temps (0-1), utilisés par `random` et
    `pixel` pour sauter SUR le temps plutôt qu'au gré de la phase.
    """
    if motif in ('cercle', 'circle'):
        return math.cos(ph), math.sin(ph)
    if motif in ('huit', 'eight'):
        return math.sin(ph), math.sin(2.0 * ph) * 0.5
    if motif == 'vague':
        return math.sin(ph), 0.0
    if motif == 'diagonale':
        t = math.sin(ph)
        return t, t
    if motif == 'bounce':
        return abs(math.sin(ph * 0.5)) * 2.0 - 1.0, 0.0
    if motif == 'spirale':
        r = (ph % (2 * math.pi)) / (2 * math.pi)
        return r * math.cos(ph * 3.0), r * math.sin(ph * 3.0)
    if motif in ('random', 'pixel'):
        if temps >= 0:
            # Un nouveau point par temps, rejoint en 40 % du temps (random) ou
            # sec (pixel). Graine décalée par lyre : elles ne visent pas toutes
            # le même point.
            g = temps * 7 + lyre * 131
            x1, y1 = _alea(g)
            if motif == 'pixel':
                return x1, y1
            x0, y0 = _alea(g - 7)
            k = min(1.0, max(0.0, frac / 0.4))
            k = k * k * (3.0 - 2.0 * k)          # smoothstep : départ et arrivée doux
            return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
        quantum = 0.5 if motif == 'random' else 0.15
        return _alea(int(ph / (quantum * math.pi)))
    # Lissajous (défaut historique)
    return math.cos(ph), math.sin(ph * 1.618)
