"""
Classe Projector pour la gestion des projecteurs DMX
"""
from PySide6.QtGui import QColor


class Projector:
    """Represente un projecteur avec son etat (niveau, couleur, mute)"""

    def __init__(self, group, name="", fixture_type="PAR LED"):
        self.group = group
        self.name = name              # Nom affiche ("Face 1", "Lyre SL"...)
        self.fixture_type = fixture_type  # Categorie ("PAR LED", "Moving Head"...)
        self.start_address = 1        # Adresse DMX de depart (1-512)
        self.universe = 0             # Univers Art-Net (0-3)
        self.level = 0
        self.base_color = QColor("white")
        self.color = QColor("black")
        self.dmx_mode = "Manuel"
        self.muted = False
        self.pan = 32768              # Pan  16-bit (0-65535, centre=32768)
        self.tilt = 32768             # Tilt 16-bit (0-65535, centre=32768)
        self.fixture_height = None    # Hauteur de suspension (m), None = auto (7m truss)
        # Position sur le plan de feu 2D, normalisee 0-1. None = jamais placee :
        # le canvas la posera d'office a l'affichage. Initialisee ICI et pas
        # seulement par `load_dmx_patch_config` : au tout premier lancement il
        # n'y a aucun `.maestro_dmx_patch.json`, les fixtures par defaut
        # arrivaient donc sans l'attribut et le premier `paintEvent` du plan de
        # feu levait un AttributeError a chaque rafraichissement — jusqu'au
        # segfault, le QPainter du paint interrompu restant actif.
        self.canvas_x = None
        self.canvas_y = None
        self.pos_3d_x = None          # Position 3D indépendante X (m), None = dérivé du plan 2D
        self.pos_3d_z = None          # Position 3D indépendante Z (m), None = dérivé du plan 2D
        self.body_rotation = 0.0     # Rotation du corps sur la truss (degrés, 0-360)
        self.gobo = 0                 # Gobo wheel (0-255)
        self.zoom = 0                 # Zoom (0-255)
        self.shutter = 255            # Shutter/Iris (0-255)
        self.shutter_inverted = False  # True si convention inversée (0=ouvert, 255=fermé)
        self.color_wheel = 0          # Color wheel (0-255)
        self.prism = 0                # Prism (0=off, >0=actif)
        self.gobo_rotation = 0        # Rotation gobo (0-255)
        self.prism_rotation = 0       # Rotation prisme (0-255)
        self.effects          = 0   # Effects/Macro channel (0-255) — programme interne fixture
        # Canaux longtemps declares mais jamais pilotes : ils sortaient 0 en dur
        # et n'etaient atteignables qu'au curseur brut. Ils ont desormais un etat
        # propre, donc sauvegarde dans le show et rejouable dans un cue.
        self.focus            = 0   # Nettete du gobo (0-255)
        self.gobo2            = 0   # 2e roue de gobos (0-255)
        self.speed            = 0   # Vitesse de deplacement pan/tilt (0-255)
        # Canal macro/controle de la fixture. 0 = repos : NE PAS le piloter tout
        # seul, ces plages declenchent reset, extinction de lampe, calibrations.
        self.mode_value       = 0
        self.channel_defaults = {}    # {ch_type: 0-255} valeurs par défaut par canal
        # Contrôle brut prioritaire, à DEUX formes de clé :
        #   - str non numérique : un TYPE de canal ("Mode", "Reset"…). Tous les
        #     canaux de ce type reçoivent la valeur — c'est la forme historique.
        #   - int (ou son écriture décimale, après un aller-retour JSON) : le
        #     NUMÉRO du canal dans la fixture, 1 = son premier canal. Une seule
        #     sortie visée, donc des canaux réglables indépendamment même quand
        #     MyStrow ne sait pas les nommer (lasers, machines à effets…).
        # Le numéro l'emporte sur le type. Voir `ArtNetDMX.update_from_projectors`.
        self.channel_extras   = {}    # {ch_type | n° de canal: 0-255}
        # Nom lisible de chaque canal, aligné sur `dmx_profile`. Vient du
        # fichier constructeur à l'import (« LaserGroupSelect », « Rotation Z »)
        # et se règle à la main dans l'éditeur de fixtures. C'est souvent la
        # SEULE chose qui distingue deux canaux ramenés au même type — et sur un
        # laser, la seule information tout court, la moitié des canaux n'ayant
        # aucun type connu. Purement informatif : n'entre jamais dans le calcul
        # de la trame DMX.
        self.channel_labels   = []    # [str] parallèle à dmx_profile
        # Canaux spéciaux — contrôle manuel indépendant
        self.uv           = 0   # UV (0-255, direct)
        self.white_boost  = 0   # Blanc extra au-dessus du RGB-dérivé (0-255)
        self.amber_boost  = 0   # Ambre extra (0-255)
        self.orange_boost = 0   # Orange extra (0-255)
        self.color_wheel_slots = []   # [{"name": str, "color": "#rrggbb", "dmx": int}] depuis OFL
        self.gobo_wheel_slots  = []   # [{"name": str, "color": "#rrggbb", "dmx": int}] depuis OFL
        # ── Presets / programmes internes ────────────────────────────────────
        # Valeur courante des canaux `Preset1..4` (macros de l'appareil : « Auto
        # 1 », « Sound active »…). Etat dedie, comme `mode_value` : c'est ce qui
        # les rend capturables dans une memoire. 0 = repos, l'appareil ne lance
        # rien tant que l'utilisateur n'a pas choisi un bloc.
        self.preset1 = 0
        self.preset2 = 0
        self.preset3 = 0
        self.preset4 = 0
        # Blocs nommes de chaque canal de preset, calibres par l'utilisateur :
        # {"Preset1": [{"name": str, "dmx": int}, ...], ...}
        # Un dict et non quatre listes : une seule chose a sauvegarder, a
        # partager et a recopier au patch.
        self.preset_slots = {}
        # Limites de mouvement pan/tilt (16-bit, 0–65535 ; 0/65535 = aucune limite)
        self.pan_min  = 0
        self.pan_max  = 65535
        self.tilt_min = 0
        self.tilt_max = 65535
        self.pan_invert    = False  # Inverser le sens du pan (65535 - valeur)
        self.tilt_invert   = False  # Inverser le sens du tilt (65535 - valeur)
        self.pan_tilt_swap = False  # Permuter pan ↔ tilt
        # ── Couronne LED (« ring ») ──────────────────────────────────────────
        # True : la couronne suit le show — même couleur, même niveau et même
        # strobe que le faisceau (voir `artnet_dmx`, bloc « Couronne »). C'est
        # la deuxième source de l'appareil, et la laisser noire pendant que la
        # tête joue n'a de sens pour personne.
        # False : elle redevient manuelle, à piloter au curseur des « canaux
        # avancés ». Les canaux RingFX / RingSpeed (programmes internes de la
        # couronne) restent manuels dans les DEUX cas.
        self.ring_follow   = True
        # ── Fixture à pixels (matrice / barre LED) ───────────────────────────
        # Un fixture "matrice" est patché comme N projecteurs enfants (1 par
        # pixel) + éventuellement 1 projecteur "master" pour les canaux globaux
        # (Dim/Strobe). Ces champs relient les enfants entre eux et portent la
        # géométrie (pour le plan de feu 2D/3D). None/0 = projecteur classique.
        self.matrix_id    = None    # identifiant partagé par les pixels d'une même matrice
        self.matrix_role  = None    # "master" | "pixel" | None
        self.pixel_index  = None    # index du pixel dans l'ordre DMX (0-based)
        self.pixel_row    = None    # ligne physique (0-based)
        self.pixel_col    = None    # colonne physique (0-based)
        self.matrix_rows  = 0       # nb de lignes de la matrice
        self.matrix_cols  = 0       # nb de colonnes de la matrice
        self.matrix_phys_w = None   # largeur physique (mm), None = inconnu
        self.matrix_phys_h = None   # hauteur physique (mm), None = inconnu
        self.matrix_rot   = 0       # rotation du bloc sur le plan (0..3 quarts de tour)
        # Puissance du faisceau dans le plan 3D, en % (100 = rendu d'origine).
        # Purement visuel : n'entre jamais dans les niveaux DMX envoyés.
        self.beam_gain    = 100.0
        # Ouverture du faisceau dans le plan 3D, en % (100 = rendu d'origine).
        # Permet de resserrer un beam ou d'élargir un wash pour coller à
        # l'optique réelle de l'appareil. Purement visuel lui aussi : le canal
        # Zoom DMX, lui, reste piloté par `zoom` et sort bien en DMX.
        self.beam_angle   = 100.0
        # Taille du CORPS de l'appareil dans le plan 3D, en % (100 = modèle
        # d'origine). Les modèles 3D sont dessinés à une taille moyenne : sur
        # une scène étroite ils paraissent énormes, sur un grand plateau
        # minuscules. Purement visuel — la position d'accroche, elle, ne bouge
        # pas : seule la lentille suit le corps, et le faisceau part d'elle.
        self.fixture_scale = 100.0
        self._dmx_profile = []

    # ── Profil DMX ───────────────────────────────────────────────────────────
    # Propriete et non simple attribut : c'est le SEUL passage oblige des noms
    # de canaux. Ils arrivent d'une douzaine d'endroits (bibliotheque QLC+,
    # fixtures natives, .tui d'un show, presets, import de patch, pixels...) et
    # canonicaliser a chacun aurait laisse passer le prochain. Ici, un profil
    # enregistre avec l'ancien vocabulaire est aussi rattrape au chargement.

    @property
    def dmx_profile(self):
        return self._dmx_profile

    @dmx_profile.setter
    def dmx_profile(self, value):
        from core import canonical_profile
        self._dmx_profile = canonical_profile(value)

    def set_color(self, color, brightness=None):
        """Definit la couleur de base et recalcule la couleur effective"""
        self.base_color = color
        if brightness is not None:
            self.level = brightness

        if self.level > 0:
            factor = self.level / 100.0
            self.color = QColor(
                int(self.base_color.red() * factor),
                int(self.base_color.green() * factor),
                int(self.base_color.blue() * factor)
            )
        else:
            self.color = QColor(0, 0, 0)

    def set_level(self, level):
        """Definit le niveau de luminosite"""
        self.level = max(0, min(100, level))
        self.set_color(self.base_color)

    # Canaux qu'un choix de couleur pilote. Le blanc en fait partie : sur une
    # fixture a LED blanche, le moteur le FABRIQUE en extrayant min(R,G,B) de
    # la couleur — il n'est pas un canal a part.
    COLOR_CHANNEL_TYPES = ("R", "G", "B", "W")

    def forced_channel_value(self, ctype):
        """Valeur reprise a la main pour ce type de canal, ou None.

        Cherche les DEUX formes de cle de `channel_extras` : le type, et le
        NUMERO du canal dans le profil (entier ou chaine apres un aller-retour
        JSON), le numero l'emportant comme dans le moteur DMX.
        """
        extras = getattr(self, 'channel_extras', None)
        if not extras:
            return None
        for num, t in enumerate(self.dmx_profile or [], start=1):
            if t != ctype:
                continue
            for cle in (num, str(num)):
                if cle in extras:
                    return int(extras[cle])
        return int(extras[ctype]) if ctype in extras else None

    def display_color_override(self):
        """Couleur a AFFICHER quand les canaux couleur sont repris a la main.

        La 2D et la 3D dessinent depuis `color`/`level` — c'est le modele, et
        un canal repris ne passe justement plus par lui : la fixture sortait du
        rouge en restant noire a l'ecran. On recompose donc ici ce que la rampe
        emet vraiment : les canaux repris pour ceux qui le sont, la couleur du
        modele pour les autres, plus la LED blanche qui delave le tout.

        Renvoie None si aucun canal couleur n'est repris — l'affichage suit
        alors le modele, comme avant.
        """
        forces = {t: self.forced_channel_value(t) for t in self.COLOR_CHANNEL_TYPES}
        if all(v is None for v in forces.values()):
            return None
        base = getattr(self, 'color', None) or QColor(0, 0, 0)
        modele = {"R": base.red(), "G": base.green(), "B": base.blue(), "W": 0}
        v = {t: (forces[t] if forces[t] is not None else modele[t])
             for t in ("R", "G", "B", "W")}
        return QColor(min(255, v["R"] + v["W"]),
                      min(255, v["G"] + v["W"]),
                      min(255, v["B"] + v["W"]))

    def release_color_overrides(self):
        """Rend au moteur les canaux couleur repris a la main.

        Les curseurs bruts de la vue « Curseurs » ecrivent R/G/B/W dans
        `channel_extras` sur les fixtures a LED blanche : le moteur y recompose
        ces canaux (extraction du blanc) et aucune couleur de base ne peut les
        demander un par un. Or `channel_extras` gagne TOUJOURS contre le
        modele — sans cette purge, choisir une couleur ensuite n'aurait plus
        aucun effet sur ces canaux et la fixture resterait sur la teinte reglee
        au curseur, sans que rien ne le dise.

        Ne touche qu'aux canaux couleur : un CTO, un gobo ou un canal sans nom
        regle a la main n'a aucune raison de sauter parce qu'on change de
        couleur. Renvoie True si quelque chose a ete libere.
        """
        extras = getattr(self, 'channel_extras', None)
        if not extras:
            return False
        # Les deux formes de cle du moteur : le TYPE, et le NUMERO du canal
        # (entier, ou son ecriture decimale apres un aller-retour JSON).
        cles = set(self.COLOR_CHANNEL_TYPES)
        for num, ctype in enumerate(self.dmx_profile or [], start=1):
            if ctype in self.COLOR_CHANNEL_TYPES:
                cles.update((num, str(num)))
        restant = {k: v for k, v in extras.items() if k not in cles}
        if len(restant) == len(extras):
            return False
        self.channel_extras = restant
        return True

    def toggle_mute(self):
        """Bascule l'etat mute"""
        self.muted = not self.muted
        return self.muted

    def get_dmx_rgb(self):
        """Retourne les valeurs RGB pour DMX (0-255)"""
        if self.muted or self.level == 0:
            return (0, 0, 0)
        return (self.color.red(), self.color.green(), self.color.blue())

    def __repr__(self):
        return f"Projector({self.group}, level={self.level}, muted={self.muted})"
