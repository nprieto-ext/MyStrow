"""
Fixtures à pixels (matrices & barres LED) — Phase 0 (fondation).

Un fixture à pixels (dalle 3x3, barre 1xN, panneau RxC…) est décrit par un
`PixelFixtureSpec` et « déplié » en projecteurs MyStrow classiques via
`generate_matrix_projectors()` :

    - 1 projecteur "master" (optionnel) pour les canaux globaux (Dim, Strobe…)
      placé à l'adresse de base.
    - N projecteurs "pixel", 1 par cellule, chacun avec son propre bloc de
      canaux (R,G,B,W…), adressés à la suite du master.

Chaque projecteur généré est un `Projector` standard avec `dmx_profile` et
`start_address` renseignés : le moteur DMX, les mémoires, la timeline et le
plan de feu les pilotent SANS aucune modification (design "pixels enfants").

La géométrie (lignes/colonnes, dimensions physiques, câblage) est conservée
sur chaque projecteur pour permettre au plan de feu 2D/3D de les regrouper et
aux effets de matrice de raisonner en coordonnées (ligne, colonne).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict

from projector import Projector


# ─────────────────────────────────────────────────────────────────────────────
# Spécification d'un fixture à pixels
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PixelFixtureSpec:
    """Décrit un fixture à pixels, indépendamment de son adresse DMX.

    Le profil DMX complet du fixture se lit :
        [ *global_head, (pixel_channels) × (rows*cols), *global_tail ]

    Attributs :
        name            Nom lisible ("Matrice 3×3 RGBW", "Barre 8 px"…).
        manufacturer    Fabricant (facultatif).
        rows, cols      Géométrie de la grille. Barre = 1 ligne × N colonnes.
        pixel_channels  Gabarit de canaux d'UN pixel, ex. ["R","G","B","W"].
        global_head     Canaux globaux AVANT les pixels, ex. ["Dim","Strobe"].
        global_tail     Canaux globaux APRÈS les pixels (rare).
        wiring          "row" (row-major) ou "serpentine" (lignes alternées).
        phys_w, phys_h  Dimensions physiques (mm) pour le plan 2D/3D (option).
        fixture_type    Catégorie MyStrow attribuée aux pixels.
    """

    name: str = "Matrice LED"
    manufacturer: str = ""
    rows: int = 1
    cols: int = 1
    pixel_channels: list = field(default_factory=lambda: ["R", "G", "B"])
    global_head: list = field(default_factory=list)
    global_tail: list = field(default_factory=list)
    wiring: str = "row"                 # "row" | "serpentine"
    phys_w: float | None = None         # mm
    phys_h: float | None = None         # mm
    fixture_type: str = "Matrice LED"

    # ── Dérivés ──────────────────────────────────────────────────────────────
    @property
    def pixel_count(self) -> int:
        return max(0, self.rows) * max(0, self.cols)

    @property
    def pixel_len(self) -> int:
        return len(self.pixel_channels)

    @property
    def total_channels(self) -> int:
        return (len(self.global_head)
                + self.pixel_count * self.pixel_len
                + len(self.global_tail))

    def full_profile(self) -> list:
        """Profil DMX complet (à titre indicatif / validation)."""
        prof = list(self.global_head)
        for _ in range(self.pixel_count):
            prof.extend(self.pixel_channels)
        prof.extend(self.global_tail)
        return prof

    # ── (dé)sérialisation ────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PixelFixtureSpec":
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)

    def describe(self) -> str:
        geo = f"{self.rows}×{self.cols}"
        chans = "".join(c[0] for c in self.pixel_channels)  # ex. RGBW
        head = ("+" + "".join(g[0] for g in self.global_head)) if self.global_head else ""
        return f"{self.name} — {geo} {chans}{head} ({self.total_channels} ch)"


# ─────────────────────────────────────────────────────────────────────────────
# Ordre de câblage : index DMX (0..N-1) → (ligne, colonne) physique
# ─────────────────────────────────────────────────────────────────────────────

def pixel_positions(rows: int, cols: int, wiring: str = "row") -> list:
    """Retourne la liste des (row, col) dans l'ordre où les pixels apparaissent
    sur le câblage DMX. `pixel_positions(...)[i]` = position du i-ème pixel.

    - "row"        : chaque ligne parcourue de gauche à droite.
    - "serpentine" : les lignes impaires sont inversées (câblage en zig-zag).
    """
    order = []
    for r in range(rows):
        col_range = range(cols)
        if wiring == "serpentine" and (r % 2 == 1):
            col_range = range(cols - 1, -1, -1)
        for c in col_range:
            order.append((r, c))
    return order


# ─────────────────────────────────────────────────────────────────────────────
# Génération des projecteurs (le cœur de la Phase 0)
# ─────────────────────────────────────────────────────────────────────────────

def generate_matrix_projectors(spec: PixelFixtureSpec,
                               base_address: int,
                               universe: int = 0,
                               group: str = "barre",
                               name: str | None = None,
                               matrix_id: str | None = None) -> list:
    """Déplie un `PixelFixtureSpec` en projecteurs MyStrow.

    Retourne une liste de `Projector` : [master?] + pixels, adressés en continu
    à partir de `base_address`. Chaque projecteur est prêt à être patché tel
    quel (il porte `dmx_profile` + `start_address`).

    Remarque : seuls les canaux globaux de TÊTE (`global_head`) sont pris en
    charge par le master (contigus depuis l'adresse de base). Les rares canaux
    globaux de fin (`global_tail`) ne sont pas encore gérés (ils tomberaient
    après les pixels) — à traiter en Phase ultérieure si un modèle réel l'exige.
    """
    if spec.pixel_count <= 0 or spec.pixel_len <= 0:
        raise ValueError("PixelFixtureSpec invalide : rows/cols/pixel_channels")

    mid = matrix_id or uuid.uuid4().hex[:12]
    base_name = name or spec.name
    projectors: list = []

    head_len = len(spec.global_head)
    pix_len = spec.pixel_len

    # ── Master (canaux globaux de tête) ──────────────────────────────────────
    if head_len > 0:
        master = Projector(group, name=f"{base_name} · Master",
                           fixture_type=spec.fixture_type)
        master.start_address = base_address
        master.universe = universe
        master.dmx_profile = list(spec.global_head)
        master.matrix_id = mid
        master.matrix_role = "master"
        master.matrix_rows = spec.rows
        master.matrix_cols = spec.cols
        master.matrix_phys_w = spec.phys_w
        master.matrix_phys_h = spec.phys_h
        # Dimmer global ouvert par défaut pour que les pixels soient visibles.
        # set_level() synchronise base_color/color/level (un level sans couleur
        # cohérente ferait croire au moteur qu'un effet est actif → Dim=0).
        if "Dim" in spec.global_head:
            master.set_level(100)
        projectors.append(master)

    # ── Pixels ───────────────────────────────────────────────────────────────
    positions = pixel_positions(spec.rows, spec.cols, spec.wiring)
    for i, (row, col) in enumerate(positions):
        addr = base_address + head_len + i * pix_len
        px = Projector(group, name=f"{base_name} · px{i + 1}",
                       fixture_type=spec.fixture_type)
        px.start_address = addr
        px.universe = universe
        px.dmx_profile = list(spec.pixel_channels)
        px.matrix_id = mid
        px.matrix_role = "pixel"
        px.pixel_index = i
        px.pixel_row = row
        px.pixel_col = col
        px.matrix_rows = spec.rows
        px.matrix_cols = spec.cols
        px.matrix_phys_w = spec.phys_w
        px.matrix_phys_h = spec.phys_h
        projectors.append(px)

    return projectors


def layout_pixels(pixels: list, cx: float, cy: float,
                  sx: float, sy: float, rot=0) -> None:
    """Place les pixels d'une matrice en bloc-grille sur le plan de feu.

    Écrit `canvas_x`/`canvas_y` (normalisés 0-1) de chaque pixel autour du
    centre (cx, cy), avec un espacement (sx, sy).

    `rot` = nombre de quarts de tour horaires (0..3). Accepte aussi "H"→0 et
    "V"→1 (compat orientation à la création). La rotation est une vraie
    rotation de la grille (cycle de 4), pour le clic droit « Pivoter 90° ».
    """
    if rot == "H":
        rot = 0
    elif rot == "V":
        rot = 1
    rot = int(rot) % 4

    def _clamp(v):
        return max(0.04, min(0.96, v))

    for p in pixels:
        r = p.pixel_row if p.pixel_row is not None else 0
        c = p.pixel_col if p.pixel_col is not None else 0
        R = max(1, p.matrix_rows)
        C = max(1, p.matrix_cols)
        # (gy, gx) = index sur l'axe Y (ligne) et X (colonne) après rotation ;
        # (GY, GX) = dimensions de la grille pour cette rotation.
        if rot == 0:      # 0°
            gy, gx, GY, GX = r,         c,         R, C
        elif rot == 1:    # 90° horaire
            gy, gx, GY, GX = c,         R - 1 - r, C, R
        elif rot == 2:    # 180°
            gy, gx, GY, GX = R - 1 - r, C - 1 - c, R, C
        else:             # 270°
            gy, gx, GY, GX = C - 1 - c, r,         C, R
        x = cx + (gx - (GX - 1) / 2.0) * sx
        y = cy + (gy - (GY - 1) / 2.0) * sy
        p.canvas_x, p.canvas_y = _clamp(x), _clamp(y)


def matrix_children(projectors: list, matrix_id: str) -> list:
    """Retourne les projecteurs (master + pixels) d'une matrice donnée."""
    return [p for p in projectors if getattr(p, "matrix_id", None) == matrix_id]


def matrix_pixels_grid(projectors: list, matrix_id: str) -> dict:
    """Retourne {(row, col): Projector} pour les pixels d'une matrice."""
    grid = {}
    for p in projectors:
        if getattr(p, "matrix_id", None) == matrix_id and p.matrix_role == "pixel":
            grid[(p.pixel_row, p.pixel_col)] = p
    return grid


# ─────────────────────────────────────────────────────────────────────────────
# Presets courants (à enrichir / à alimenter depuis la base OFL en Phase parser)
# ─────────────────────────────────────────────────────────────────────────────

PIXEL_FIXTURE_PRESETS: list = [
    PixelFixtureSpec(
        name="Matrice 3×3 RGBW (38ch)", rows=3, cols=3,
        pixel_channels=["R", "G", "B", "W"], global_head=["Dim", "Strobe"],
        wiring="row", fixture_type="Matrice LED",
    ),
    PixelFixtureSpec(
        name="Barre 8 px RGB (26ch)", rows=1, cols=8,
        pixel_channels=["R", "G", "B"], global_head=["Dim", "Strobe"],
        wiring="row", fixture_type="Barre LED",
    ),
    PixelFixtureSpec(
        name="Barre 8 px RGBW (34ch)", rows=1, cols=8,
        pixel_channels=["R", "G", "B", "W"], global_head=["Dim", "Strobe"],
        wiring="row", fixture_type="Barre LED",
    ),
    PixelFixtureSpec(
        name="Panneau 4×4 RGB (48ch)", rows=4, cols=4,
        pixel_channels=["R", "G", "B"], global_head=[],
        wiring="serpentine", fixture_type="Matrice LED",
    ),
]
