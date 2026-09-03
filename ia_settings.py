"""
Réglages IA Lumière par média — MyStrow

Le mode « IA Lumière » de la colonne DMX avait son propre moteur, plus ancien
que celui du mode LIVE : une seule couleur dominante, une palette dérivée
automatiquement, et un cercle codé en dur pour les lyres. Le mode LIVE, lui,
possède déjà un pool de couleurs, un pool de mouvements qui s'enchaînent, des
gobos, la nervosité — tout ce qu'on voulait dans la séquence.

Plutôt que de faire grossir l'ancien moteur, la séquence utilise désormais le
moteur LIVE (`MainWindow._apply_live_state`). Ce moteur lisait ses réglages
directement sur le panneau LIVE ; il lit maintenant une *source de réglages*,
qui est :

  · le panneau LIVE lui-même quand on est en mode LIVE (inchangé),
  · une instance d'`IASettings` attachée à la ligne quand la playlist joue.

D'où cette classe : elle expose EXACTEMENT la même API en lecture que
`LiveModePanel`, mais sans widget derrière. C'est ce qui permet à chaque média
de la playlist d'avoir son ambiance sans jamais toucher au panneau LIVE — le
panneau garde son état, on ne le pilote pas depuis la playlist.

⚠️ Toute propriété lue par le moteur DOIT exister ici avec la même sémantique
(et les mêmes unités : `nervosity` rend 0-1, pas 0-100). Un attribut manquant
ne lèverait pas d'erreur visible : `update_audio_ai` avale les exceptions dans
un `print`, et le show partirait en silence sur un rendu dégradé.
"""

from PySide6.QtGui import QColor


# Ordre de référence des tuiles couleur et des mouvements. Dupliqué depuis
# `sequencer.LiveModePanel` À DESSEIN : importer `sequencer` ici créerait un
# cycle d'imports (sequencer importe main_window qui importera ce module).
# Ces deux listes ne bougent qu'à l'ajout d'une couleur ou d'un mouvement.
COLOR_TILE_ORDER = [
    'rouge', 'orange', 'jaune', 'ambre', 'rose', 'rose_chaud',
    'vert', 'cyan', 'bleu', 'bleu_nuit', 'violet', 'lavande',
    'blanc', 'auto',
    'bi_rb', 'bi_vo', 'bi_vj', 'bi_rv', 'bi_cc', 'bi_bv',
]

# (clé, couleur 1, couleur 2) — `None` en couleur 1 = AUTO (palette de l'IA).
COLOR_TILE_DATA = {
    'rouge':      ('#ff1133', None),
    'orange':     ('#ff8800', None),
    'jaune':      ('#ffee00', None),
    'ambre':      ('#ffaa00', None),
    'rose':       ('#ff44aa', None),
    'rose_chaud': ('#ff2266', None),
    'vert':       ('#00ff55', None),
    'cyan':       ('#00eeff', None),
    'bleu':       ('#0055ff', None),
    'bleu_nuit':  ('#001aff', None),
    'violet':     ('#aa22ff', None),
    'lavande':    ('#cc88ff', None),
    'blanc':      ('#ffffff', None),
    'auto':       (None,      None),
    'bi_rb':      ('#ff1133', '#0055ff'),
    'bi_vo':      ('#aa22ff', '#ff8800'),
    'bi_vj':      ('#00ff55', '#ffee00'),
    'bi_rv':      ('#ff1133', '#aa22ff'),
    'bi_cc':      ('#ff8800', '#00eeff'),
    'bi_bv':      ('#0055ff', '#00ff55'),
}

MOVEMENT_ORDER = ['vague', 'cercle', 'diagonale', 'spirale', 'bounce', 'huit']


class IASettings:
    """Réglages IA Lumière d'un média — même API en lecture que le panneau LIVE."""

    def __init__(self):
        self._ia_mode           = 'musical'

        # Mouvements de lyres
        self._movement_patterns = {'cercle'}
        self._current_movement  = 'cercle'
        self._movement_speed    = 50
        self._movement_size     = 70
        self._movement_duration = 40

        # Couleurs
        # Meme defaut contraste que le panneau LIVE (cf. `sequencer.py`).
        self._color_tile_pool   = {'rouge', 'vert', 'bleu', 'rose'}
        self._current_color     = 'rouge'
        self._color_duration    = 40
        self._color_restrict    = True
        self._color_max         = 4

        # Gobos
        self._gobo_pool         = {0}
        self._current_gobo      = 0
        self._gobo_duration     = 40
        self._gobo_rotation     = False
        self._gobo_rot_speed    = 50

        # Strobe AUTOMATIQUE : autorise (ou non) les strobes que l'IA declenche
        # elle-meme sur les drops et les montees. Ne declenche rien tout seul.
        self._strob_fast        = True
        self._strob_slow        = False
        self._strob_none        = False

        # Effet SPECIAL, tenu pendant tout le media : None | 'strobe'
        # | 'strobe_couleur' | 'fixe_blanc' | 'passage_blanc'. Contrairement aux
        # drapeaux ci-dessus, celui-ci joue en permanence des qu'il est pose.
        self._active_special    = None

        # Divers
        self._nervosity         = 50      # 0-100 côté stockage, 0-1 en lecture
        self._passage_speed     = 50
        self._allowed_groups    = set()
        self._allowed_effects   = set()
        self._lyre_presets      = []
        self._live_palette      = []
        self._dimmer_values     = {}

    # ── Mode ─────────────────────────────────────────────────────────────────

    @property
    def ia_mode(self) -> str:
        return self._ia_mode

    # ── Mouvements ───────────────────────────────────────────────────────────

    @property
    def movement_pattern(self) -> str:
        return self._current_movement

    @property
    def movement_patterns(self) -> list:
        return [k for k in MOVEMENT_ORDER if k in self._movement_patterns]

    @property
    def movement_speed(self) -> int:
        return self._movement_speed

    @property
    def movement_size(self) -> int:
        return self._movement_size

    @property
    def movement_duration(self) -> int:
        return self._movement_duration

    def set_current_movement(self, key: str):
        """Appelé par le moteur quand il enchaîne sur le mouvement suivant."""
        if key in self._movement_patterns:
            self._current_movement = key

    # ── Couleurs ─────────────────────────────────────────────────────────────

    @property
    def color_restrict(self) -> bool:
        return self._color_restrict

    @property
    def color_max(self) -> int:
        return self._color_max

    @property
    def color_cycle(self) -> bool:
        """Le moteur doit-il faire défiler le pool de couleurs ?

        Non à 1 couleur : le dialogue annonce « une seule couleur, tenue tout
        le morceau — cliquez celle qui joue ». Le panneau LIVE donne l'autre
        sens à son « 1 » (une couleur à la fois, qui défile au rythme du
        curseur DURÉE) et rend donc toujours `True`.
        """
        return self._color_max > 1

    @property
    def color_tile_pool(self) -> list:
        return [k for k in COLOR_TILE_ORDER if k in self._color_tile_pool]

    @property
    def current_color_tile(self) -> str:
        return self._current_color

    @property
    def color_duration(self) -> int:
        return self._color_duration

    def get_color_data(self, key: str):
        """(QColor|None, QColor|None) — couleur 1 à None = AUTO (palette IA)."""
        c1, c2 = COLOR_TILE_DATA.get(key, (None, None))
        return (QColor(c1) if c1 else None,
                QColor(c2) if c2 else None)

    def set_current_color_tile(self, key: str):
        """Appelé par le moteur quand il bascule vers la prochaine couleur."""
        if key in self._color_tile_pool:
            self._current_color = key

    # ── Gobos ────────────────────────────────────────────────────────────────

    @property
    def gobo_pool(self) -> list:
        return sorted(self._gobo_pool)

    @property
    def current_gobo(self) -> int:
        return self._current_gobo

    @property
    def gobo_duration(self) -> int:
        return self._gobo_duration

    @property
    def gobo_rotation(self) -> bool:
        return self._gobo_rotation

    @property
    def gobo_rot_speed(self) -> int:
        return self._gobo_rot_speed

    def _refresh_gobo_tiles(self):
        """Sans objet hors panneau — le moteur l'appelle après avoir changé de
        gobo pour rafraîchir les tuiles. Ici il n'y a pas de tuile à peindre."""
        pass

    # ── Strobe ───────────────────────────────────────────────────────────────

    @property
    def strob_fast(self) -> bool:
        return self._strob_fast

    @property
    def strob_slow(self) -> bool:
        return self._strob_slow

    @property
    def strob_none(self) -> bool:
        return self._strob_none

    @property
    def active_special(self):
        """Effet special tenu (None si aucun) — priorite absolue dans le moteur."""
        return self._active_special

    # ── Divers ───────────────────────────────────────────────────────────────

    @property
    def nervosity(self) -> float:
        """0.0-1.0 — le panneau rend `slider/100`, on garde la même unité."""
        return self._nervosity / 100.0

    @property
    def passage_speed(self) -> int:
        return self._passage_speed

    @property
    def allowed_groups(self) -> set:
        return self._allowed_groups

    @property
    def allowed_effects(self) -> set:
        return self._allowed_effects

    @property
    def lyre_presets(self) -> list:
        return self._lyre_presets

    @property
    def live_palette(self) -> list:
        return self._live_palette

    @property
    def no_auto_strobe(self) -> bool:
        return False

    @property
    def dimmer_values(self) -> dict:
        return self._dimmer_values

    def is_tile_active(self, tile_id: str) -> bool:
        """Les tuiles d'effet au beat (flash/strobe/gobo/auto) n'existent plus
        dans le panneau — sa propre implémentation rend False sans condition.
        Même réponse ici, pour que séquence et LIVE restent identiques."""
        return False

    # ── Retours visuels du moteur (sans objet hors panneau) ──────────────────

    def flash_beat(self):
        pass

    def set_status(self, *args, **kwargs):
        pass

    def set_vu(self, *args, **kwargs):
        pass

    # ── Sérialisation (.tui) ─────────────────────────────────────────────────

    # Les sets sont stockés en listes triées : JSON n'a pas de set, et une
    # liste ordonnée garde les diffs de show lisibles d'une sauvegarde à l'autre.
    def to_dict(self) -> dict:
        return {
            'ia_mode':          self._ia_mode,
            'mov_pool':         sorted(self._movement_patterns),
            'mov_current':      self._current_movement,
            'mov_speed':        self._movement_speed,
            'mov_size':         self._movement_size,
            'mov_duration':     self._movement_duration,
            'color_pool':       sorted(self._color_tile_pool),
            'color_current':    self._current_color,
            'color_duration':   self._color_duration,
            'color_restrict':   self._color_restrict,
            'color_max':        self._color_max,
            'gobo_pool':        sorted(self._gobo_pool),
            'gobo_duration':    self._gobo_duration,
            'gobo_rotation':    self._gobo_rotation,
            'gobo_rot_speed':   self._gobo_rot_speed,
            'strob_fast':       self._strob_fast,
            'strob_slow':       self._strob_slow,
            'strob_none':       self._strob_none,
            'active_special':   self._active_special,
            'nervosity':        self._nervosity,
            'passage_speed':    self._passage_speed,
            'allowed_groups':   sorted(self._allowed_groups),
            'allowed_effects':  sorted(self._allowed_effects),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IASettings":
        s = cls()
        if not isinstance(d, dict):
            return s
        # Chaque clé retombe sur le défaut si elle manque : un show enregistré
        # par une version antérieure doit rester jouable après ajout d'un réglage.
        s._ia_mode           = d.get('ia_mode', s._ia_mode)
        s._movement_patterns = set(d.get('mov_pool', s._movement_patterns)) or {'cercle'}
        s._current_movement  = d.get('mov_current', s._current_movement)
        s._movement_speed    = int(d.get('mov_speed', s._movement_speed))
        s._movement_size     = int(d.get('mov_size', s._movement_size))
        s._movement_duration = int(d.get('mov_duration', s._movement_duration))
        s._color_tile_pool   = set(d.get('color_pool', s._color_tile_pool)) or {'rouge'}
        s._current_color     = d.get('color_current', s._current_color)
        s._color_duration    = int(d.get('color_duration', s._color_duration))
        s._color_restrict    = bool(d.get('color_restrict', s._color_restrict))
        s._color_max         = int(d.get('color_max', s._color_max))
        s._gobo_pool         = set(d.get('gobo_pool', s._gobo_pool)) or {0}
        s._gobo_duration     = int(d.get('gobo_duration', s._gobo_duration))
        s._gobo_rotation     = bool(d.get('gobo_rotation', s._gobo_rotation))
        s._gobo_rot_speed    = int(d.get('gobo_rot_speed', s._gobo_rot_speed))
        s._strob_fast        = bool(d.get('strob_fast', s._strob_fast))
        s._strob_slow        = bool(d.get('strob_slow', s._strob_slow))
        s._strob_none        = bool(d.get('strob_none', s._strob_none))
        s._active_special    = d.get('active_special', s._active_special) or None
        s._nervosity         = int(d.get('nervosity', s._nervosity))
        s._passage_speed     = int(d.get('passage_speed', s._passage_speed))
        s._allowed_groups    = set(d.get('allowed_groups', s._allowed_groups))
        s._allowed_effects   = set(d.get('allowed_effects', s._allowed_effects))
        # Le mouvement/la couleur « en cours » doivent appartenir à leur pool,
        # sinon le moteur démarre sur une valeur qu'il n'enchaînera jamais.
        if s._current_movement not in s._movement_patterns:
            s._current_movement = s.movement_patterns[0] if s.movement_patterns else 'cercle'
        if s._current_color not in s._color_tile_pool:
            s._current_color = s.color_tile_pool[0] if s.color_tile_pool else 'rouge'
        if s._current_gobo not in s._gobo_pool:
            s._current_gobo = s.gobo_pool[0] if s.gobo_pool else 0
        return s

    @classmethod
    def from_dominant_color(cls, color: QColor) -> "IASettings":
        """Préréglage de reprise pour un show enregistré à l'ancien format.

        Avant, une ligne « IA Lumière » ne portait qu'une couleur dominante
        (`ia_color`) et le moteur en dérivait 8 teintes. On repart de la tuile
        la plus proche de cette couleur, plus ses deux voisines dans l'ordre des
        tuiles : c'est ce qui ressemble le plus à l'ancienne palette générée,
        sans laisser le média sur les couleurs par défaut (rouge/orange/jaune)
        qui n'auraient rien à voir avec le show d'origine.
        """
        s = cls()
        if color is None or not color.isValid():
            return s

        # Un blanc ou un gris n'a pas de teinte (`hue()` rend -1) : le classer
        # par distance de teinte le rapprocherait du rouge (|-1 - 0| = 1), ce
        # qui est faux. Il n'a qu'une seule tuile qui lui corresponde.
        if color.hue() < 0 or color.saturation() < 40:
            s._color_tile_pool = {'blanc'}
            s._current_color   = 'blanc'
            return s

        # Tuiles unies et colorées seulement : ni AUTO (pas de couleur), ni les
        # bicouleurs (deux teintes, donc pas de distance unique), ni le blanc
        # (achromatique — il sortirait gagnant de toutes les comparaisons).
        def _dist(key):
            c1, c2 = COLOR_TILE_DATA.get(key, (None, None))
            if not c1 or c2:
                return None
            h = QColor(c1).hue()
            if h < 0:
                return None
            d = abs(h - color.hue())
            return min(d, 360 - d)        # la teinte est circulaire

        classees = sorted(
            ((d, k) for k in COLOR_TILE_ORDER
             for d in [_dist(k)] if d is not None))
        if not classees:
            return s
        # Les trois teintes les plus proches — voisines EN TEINTE, pas voisines
        # dans la liste : l'ordre des tuiles range par familles (chaud puis
        # froid), donc « la tuile d'à côté » du vert y est le rose.
        proches = [k for _, k in classees[:3]]
        s._color_tile_pool = set(proches)
        s._current_color   = proches[0]
        return s

    @classmethod
    def from_panel(cls, panel) -> "IASettings":
        """Copie l'état courant du panneau LIVE — point de départ d'un nouveau
        média : l'utilisateur retrouve l'ambiance qu'il vient de régler en LIVE.

        Copie profonde des ensembles : le préréglage ne doit plus jamais bouger
        quand le panneau change, c'est tout l'intérêt du réglage par média.
        """
        s = cls()
        if panel is None:
            return s
        try:
            s._ia_mode           = panel.ia_mode
            s._movement_patterns = set(panel.movement_patterns) or {'cercle'}
            s._current_movement  = panel.movement_pattern
            s._movement_speed    = panel.movement_speed
            s._movement_size     = panel.movement_size
            s._movement_duration = panel.movement_duration
            s._color_tile_pool   = set(panel.color_tile_pool) or {'rouge'}
            s._current_color     = panel.current_color_tile
            s._color_duration    = panel.color_duration
            s._color_restrict    = panel.color_restrict
            s._color_max         = panel.color_max
            s._gobo_pool         = set(panel.gobo_pool) or {0}
            s._current_gobo      = panel.current_gobo
            s._gobo_duration     = panel.gobo_duration
            s._gobo_rotation     = panel.gobo_rotation
            s._gobo_rot_speed    = panel.gobo_rot_speed
            s._strob_fast        = panel.strob_fast
            s._strob_slow        = panel.strob_slow
            s._strob_none        = panel.strob_none
            # `active_special` n'est PAS repris du panneau : c'est un effet
            # qu'on declenche a la main pendant un live, pas un reglage de
            # depart. Un media neuf ne doit pas hériter d'un strobe reste
            # arme dans le panneau — il partirait des la premiere lecture.
            s._nervosity         = int(round(panel.nervosity * 100))
            s._passage_speed     = panel.passage_speed
            s._allowed_groups    = set(panel.allowed_groups)
            s._allowed_effects   = set(panel.allowed_effects)
            s._lyre_presets      = list(panel.lyre_presets)
            s._live_palette      = list(panel.live_palette)
        except Exception as e:
            # Un panneau incomplet (construit à moitié) ne doit pas empêcher de
            # créer un préréglage : on garde ce qui a été copié jusque-là.
            print(f"IASettings.from_panel: {e}")
        return s

    def copy(self) -> "IASettings":
        s = IASettings.from_dict(self.to_dict())
        s._lyre_presets = list(self._lyre_presets)
        s._live_palette = list(self._live_palette)
        s._dimmer_values = dict(self._dimmer_values)
        return s
