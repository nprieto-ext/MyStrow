"""
Pixel map — effets spatiaux sur le plan de feu 2D.

Principe d'un LED mapper : on peint une « toile » qui défile et chaque
projecteur prend la couleur de l'endroit où il est posé sur le plan. On ne
programme plus fixture par fixture, on dessine un rendu.

Ce module est PUR (aucune dépendance Qt) :
  1. `spatial_positions` convertit des positions de plan (`canvas_x` /
     `canvas_y`, normalisées 0-1) en un scalaire 0..1 par fixture, selon le
     SENS choisi (gauche→droite, centre→bords, aléatoire…) ;
  2. `color_for` lit la couleur à ce scalaire, décalé du défilement, selon le
     MOTIF choisi (dégradé, vague, chenillard, bloc, rampe).

Le plan de feu (aperçu live) et le moteur d'effets du show (`core.
gradient_layer_outputs`, couche « Dégradé ») appellent les mêmes fonctions.

Les positions sont RAMENÉES à la boîte englobante de la sélection : six PAR
serrés au centre du plan parcourent tout l'effet, pas un vingtième.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict


# ─────────────────────────────────────────────────────────────────────────────
# Spécification
# ─────────────────────────────────────────────────────────────────────────────

SHAPES = ("linear", "radial", "radial_in", "random")

# Motifs : comment la couleur varie le long d'un cycle.
#   degrade     les couleurs défilent en continu (bouclé)
#   vague       une bosse douce de couleur sur le fond
#   chenillard  un bloc étroit qui court
#   bloc        un bloc large (moitié du cycle) — « carré »
#   rampe       une comète : tête vive, traîne qui s'éteint derrière
MOTIFS = ("degrade", "vague", "chenillard", "bloc", "rampe")


@dataclass
class GradientSpec:
    """Réglages d'un effet pixel.

    stops    Couleurs, "#rrggbb". Motif « degrade » : elles défilent en
             boucle. Autres motifs : la première est la couleur allumée, la
             dernière le FOND, les autres s'intercalent entre les deux.
    motif    Voir MOTIFS.
    shape    Géométrie du sens : "linear" (selon `angle`), "radial" (centre →
             bords), "radial_in" (bords → centre), "random" (chaque fixture à
             une place tirée au hasard, mais stable).
    angle    Degrés, 0 = gauche → droite, 90 = haut → bas (sens écran).
    gap      0..0.9 — « Noir » : part du cycle passée sur le fond. Plus il
             est haut, plus le noir traîne entre deux passages.
    repeat   Nombre de motifs visibles sur la sélection.
    speed    Tours par seconde du défilement. 0 = figé.
    reverse  Inverse le sens de défilement.
    """

    stops: list = field(default_factory=lambda: ["#ff0000", "#0000ff"])
    shape: str = "linear"
    angle: float = 0.0
    repeat: float = 1.0
    speed: float = 0.25
    reverse: bool = False
    motif: str = "degrade"
    gap: float = 0.0
    # Intensité générale de l'effet, 0..1 (curseur DIM).
    dim: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GradientSpec":
        d = dict(d or {})
        spec = cls()
        for k in ("stops", "shape", "angle", "repeat", "speed", "reverse",
                  "motif", "gap", "dim"):
            if k in d:
                setattr(spec, k, d[k])
        spec.stops = [s for s in (spec.stops or []) if _parse_hex(s)] or ["#ffffff"]
        if spec.shape not in SHAPES:
            spec.shape = "linear"
        if spec.motif not in MOTIFS:
            spec.motif = "degrade"
        try:
            spec.gap = max(0.0, min(0.9, float(spec.gap or 0.0)))
        except (TypeError, ValueError):
            spec.gap = 0.0
        try:
            spec.dim = max(0.0, min(1.0, float(1.0 if spec.dim is None else spec.dim)))
        except (TypeError, ValueError):
            spec.dim = 1.0
        return spec


# Palettes. Les paires « X/Noir » sont faites pour les motifs (couleur sur
# fond noir) ; les palettes multicolores pour le dégradé.
PRESETS = {
    "Rouge/Noir":   ["#ff0000", "#000000"],
    "Blanc/Noir":   ["#ffffff", "#000000"],
    "Bleu/Noir":    ["#0030ff", "#000000"],
    "Ambre/Noir":   ["#ff8c00", "#000000"],
    "Vert/Noir":    ["#00ff30", "#000000"],
    "Rose/Noir":    ["#ff0080", "#000000"],
    "Cyan/Noir":    ["#00e0ff", "#000000"],
    "Violet/Noir":  ["#8000ff", "#000000"],
    "Rouge/Bleu":   ["#ff0000", "#0000ff"],
    "Cyan/Rose":    ["#00ffff", "#ff00ff"],
    "Ambre/Blanc":  ["#ff8c00", "#ffffff"],
    "Police":       ["#ff0000", "#000000", "#0000ff", "#000000"],   # gyrophare
    "Arc-en-ciel":  ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff"],
    "Feu":          ["#ff0000", "#ff6000", "#ffb000", "#ff3000"],
    "Océan":        ["#0010ff", "#00a0ff", "#00ffd0", "#0040ff"],
    "Coucher":      ["#ff2060", "#ff8000", "#8000ff"],
    "Forêt":        ["#00ff20", "#a0ff00", "#00ff90"],
    "Glace":        ["#ffffff", "#80d0ff", "#0060ff"],
    "Néon":         ["#ff00ff", "#00ffff"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Couleurs
# ─────────────────────────────────────────────────────────────────────────────

def _parse_hex(s):
    """'#rrggbb' → (r, g, b) ou None."""
    if not isinstance(s, str):
        return None
    s = s.strip().lstrip("#")
    if len(s) == 8:            # #AARRGGBB façon Qt : on garde RGB
        s = s[2:]
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _cols(stops):
    return [c for c in (_parse_hex(s) for s in stops) if c] or [(255, 255, 255)]


def _mix(a, b, f):
    return (int(round(a[0] + (b[0] - a[0]) * f)),
            int(round(a[1] + (b[1] - a[1]) * f)),
            int(round(a[2] + (b[2] - a[2]) * f)))


def _mix_wheel(a, b, f):
    """Mélange pour une lyre à ROUE : pas de teinte intermédiaire (la roue
    irait chercher le violet entre rouge et bleu). Couleur ↔ noir = même
    teinte, luminosité au prorata (le dim fera le reste) ; deux couleurs =
    bascule franche à mi-chemin."""
    ma, mb = max(a), max(b)
    if mb == 0:
        return _mix(a, (0, 0, 0), f)
    if ma == 0:
        return _mix((0, 0, 0), b, f)
    return a if f < 0.5 else b


def is_wheel_fixture(proj):
    """Fixture dont la teinte vient d'une roue (pas de R/G/B)."""
    prof = getattr(proj, 'dmx_profile', None) or []
    return 'ColorWheel' in prof and not ('R' in prof and 'G' in prof and 'B' in prof)


def sample_gradient(stops, t):
    """Couleur (r, g, b) du dégradé BOUCLÉ à la position t (tout réel).

    Les couleurs sont réparties sur [0, 1[ ; entre la dernière et 1 on
    revient vers la première, ce qui rend le défilement continu.
    """
    cols = _cols(stops)
    n = len(cols)
    if n == 1:
        return cols[0]
    t = t - math.floor(t)            # [0, 1[
    x = t * n
    i = int(x) % n
    f = x - math.floor(x)
    return _mix(cols[i], cols[(i + 1) % n], f)


def sample_linear(stops, t, mix=_mix):
    """Couleur du dégradé NON bouclé : t=0 → première, t=1 → dernière."""
    cols = _cols(stops)
    n = len(cols)
    if n == 1:
        return cols[0]
    t = max(0.0, min(1.0, t))
    x = t * (n - 1)
    i = min(n - 2, int(x))
    return mix(cols[i], cols[i + 1], x - i)


# ─────────────────────────────────────────────────────────────────────────────
# Positions
# ─────────────────────────────────────────────────────────────────────────────

def _hash01(x, y):
    """Nombre pseudo-aléatoire STABLE (0..1) tiré de la position : le sens
    « aléatoire » ne doit pas changer d'une image à l'autre."""
    v = math.sin(x * 12.9898 + y * 78.233) * 43758.5453
    return v - math.floor(v)


def periodic_positions(pos):
    """Scalaires d'un MOTIF (chenillard, vague, bloc, rampe) : ramenés à [0, 1[.

    Le motif boucle tous les 1.0 : avec s de 0 à 1, le premier et le dernier
    appareil tombaient au même point du cycle et s'allumaient ENSEMBLE — le
    chenillard « sautait » la fin (remontée de Nico, 04/11/26 : barres aux deux
    bouts du plan). On réserve un pas pour le retour : N positions distinctes
    → s × (N-1)/N, le dernier allumé juste avant que le premier reparte.
    Le dégradé n'est PAS concerné (il doit finir sur sa dernière couleur).
    """
    vals = sorted(v for v in pos if v is not None)
    if len(vals) < 2:
        return list(pos)
    n = 1 + sum(1 for a, b in zip(vals, vals[1:]) if b - a > 0.02)
    if n < 2:
        return list(pos)
    k = (n - 1) / n
    return [v * k for v in pos]


def spec_positions(points, spec):
    """Scalaires des fixtures pour ce dégradé/motif (point unique pour le
    moteur, le plan 2D et les vignettes)."""
    pos = spatial_positions(points, spec.shape, spec.angle)
    if spec.motif != "degrade" and spec.shape != "random":
        pos = periodic_positions(pos)
    return pos


def spatial_positions(points, shape="linear", angle=0.0):
    """Scalaire 0..1 de chaque point selon la géométrie du sens.

    `points` = liste de (x, y) en coordonnées de plan (0-1), None accepté
    (repli au centre). Retourne une liste de floats, même ordre.

    Linéaire : projection sur l'axe `angle`, ramenée à l'étendue réelle de
    la sélection — le premier projecteur rencontré vaut 0, le dernier 1.
    Radial : distance au centre de la sélection, le plus éloigné vaut 1.
    Aléatoire : une place fixe par fixture, tirée de sa position.
    """
    pts = [(0.5, 0.5) if (p is None or p[0] is None or p[1] is None)
           else (float(p[0]), float(p[1])) for p in points]
    if not pts:
        return []
    if shape == "random":
        return [_hash01(x, y) for x, y in pts]
    if len(pts) == 1:
        return [0.0]

    if shape in ("radial", "radial_in"):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        d = [math.hypot(x - cx, y - cy) for x, y in pts]
        m = max(d) or 1.0
        out = [v / m for v in d]
        return [1.0 - v for v in out] if shape == "radial_in" else out

    a = math.radians(angle or 0.0)
    ux, uy = math.cos(a), math.sin(a)
    proj = [x * ux + y * uy for x, y in pts]
    lo, hi = min(proj), max(proj)
    span = hi - lo
    if span < 1e-6:
        # Tous alignés perpendiculairement à l'axe : même couleur pour tous,
        # c'est ce que montrerait un vrai dégradé dans cette direction.
        return [0.0 for _ in proj]
    return [(v - lo) / span for v in proj]


# ─────────────────────────────────────────────────────────────────────────────
# Motifs
# ─────────────────────────────────────────────────────────────────────────────

def motif_value(motif, u, gap=0.0):
    """Intensité 0..1 du motif à la position de cycle u ∈ [0, 1[.

    La partie « allumée » occupe (1 - gap) du cycle ; le reste est sur le
    fond. C'est le curseur Noir : plus de gap = un noir qui traîne plus.
    """
    u = u - math.floor(u)
    w = max(0.04, 1.0 - max(0.0, min(0.9, gap)))
    if motif == "chenillard":
        w = max(0.04, w * 0.35)
    elif motif == "bloc":
        w = max(0.04, w * 0.5)
    if u >= w:
        return 0.0
    v = u / w
    if motif == "vague":
        return (1.0 - math.cos(2 * math.pi * v)) / 2.0
    if motif == "rampe":
        # Le motif avance vers les s croissants : la tête (vive) est devant,
        # la traîne s'éteint derrière — une comète.
        return v
    return 1.0                         # bloc, chenillard


def _degrade_color(stops, x, gap, mix=_mix):
    """Dégradé bouclé, avec un temps d'arrêt sur la DERNIÈRE couleur.

    Sans gap : c0 → … → c_last → retour à c0, chaque étape 1/n du cycle.
    Avec gap : les étapes sont comprimées et la dernière couleur (le noir
    d'un « Rouge/Noir ») est tenue pendant `gap` avant le retour. Continu
    en gap = 0 : on retombe exactement sur le dégradé historique.
    """
    cols = _cols(stops)
    n = len(cols)
    if n == 1:
        return cols[0]
    t = x - math.floor(x)
    L = 1.0 - max(0.0, min(0.9, gap))
    step = L / n
    fwd = step * (n - 1)
    if t < fwd:
        y = t / step
        i = int(y)
        return mix(cols[i], cols[i + 1], y - i)
    if t < fwd + (1.0 - L):
        return cols[-1]
    f = (t - fwd - (1.0 - L)) / step
    return mix(cols[-1], cols[0], min(1.0, f))


def selection_span(spec: GradientSpec):
    """Part du cycle étalée sur la sélection (à repeat = 1).

    Dégradé : c0 → c_last (+ la tenue du noir), pas le retour, sinon la
    première couleur reviendrait aux DEUX extrémités. Motifs : un cycle
    complet, pour qu'un chenillard traverse toute la sélection.
    """
    if spec.motif != "degrade":
        return 1.0
    n = max(1, len(spec.stops or []))
    if n == 1:
        return 1.0
    L = 1.0 - max(0.0, min(0.9, spec.gap or 0.0))
    return L * (n - 1) / n + (1.0 - L)


def color_for(spec: GradientSpec, s: float, phase: float, wheel=False):
    """Couleur d'une fixture de scalaire `s` à la phase de défilement `phase`
    (en tours : 1.0 = le motif a défilé d'une longueur complète)."""
    rep = max(0.05, float(spec.repeat or 1.0))
    sign = 1.0 if spec.reverse else -1.0
    x = s * rep * selection_span(spec) + sign * phase
    if spec.motif == "degrade":
        return _degrade_color(spec.stops, x, spec.gap or 0.0,
                              _mix_wheel if wheel else _mix)
    # Le motif avance vers les s croissants : u = s - phase. La couleur va
    # de la première (allumée) à la dernière (fond) selon l'intensité.
    f = motif_value(spec.motif, x, spec.gap or 0.0)
    # Le motif parcourt TOUTE la palette : intensité pleine = première
    # couleur, repos = dernière (le fond). Feu, Coucher… gardent donc leurs
    # couleurs ; le noir n'apparaît que si la palette en contient.
    return sample_linear(spec.stops, 1.0 - f, _mix_wheel if wheel else _mix)



def output_for(spec: GradientSpec, s: float, phase: float, wheel=False):
    """Couleur (r, g, b) 0-255 d'une fixture, DIM général appliqué.

    Point UNIQUE pour le plan 2D, le moteur du show et les vignettes.
    """
    k = max(0.0, min(1.0, spec.dim))
    r, g, b = color_for(spec, s, phase, wheel)
    return (int(round(r * k)), int(round(g * k)), int(round(b * k)))
