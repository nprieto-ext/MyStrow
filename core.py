"""
Configuration globale et constantes pour MyStrow - Controleur Lumiere DMX
"""
import sys
import os
import json
import random
import socket
import struct
import wave
import array
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QFrame, QPushButton, QToolButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QSplitter, QSlider, QScrollArea, QStyle, QMenu, QWidgetAction,
    QMessageBox, QHeaderView, QComboBox, QDialog, QTabWidget
)
from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QPoint, QRect, QObject, Signal
from PySide6.QtGui import (
    QColor, QPainter, QBrush, QIcon, QPixmap, QCloseEvent, QFont,
    QPen, QPolygon, QCursor, QPalette, QLinearGradient
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
try:
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:
    # Fallback si le backend multimedia n'est pas disponible (ex: Mac sans dylibs)
    QVideoWidget = None

# === EXTENSIONS MEDIA ===
# SOURCE UNIQUE. La liste était recopiée dans cinq filtres de fichiers qui ont
# divergé avec le temps : un ALAC (.m4a) ou un AIFF (.aif) n'apparaissait pas
# dans la moitié des dialogues, alors que le lecteur les décode très bien
# (backend Qt/FFmpeg embarqué). L'utilisateur en concluait « format non
# supporté » — il ne l'était que dans la boîte d'ouverture.
# Toutes ces extensions ont été vérifiées : QMediaPlayer les charge et rend
# leur durée correctement.
AUDIO_EXTENSIONS = (
    ".mp3", ".wav", ".flac", ".aac", ".m4a", ".m4b",
    ".aif", ".aiff", ".aifc", ".caf",          # AIFF / Apple (ALAC en .m4a et .caf)
    ".ogg", ".oga", ".opus", ".wma", ".wv",
)
VIDEO_EXTENSIONS = (
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg",
)
IMAGE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tiff",
)


def _ext_filter(label, *groups):
    """« Medias (*.mp3 *.wav …) » à partir des tuples d'extensions."""
    exts = " ".join(f"*{e}" for group in groups for e in group)
    return f"{label} ({exts})"


# === FILTRES FICHIERS ===
MEDIA_EXTENSIONS_FILTER = _ext_filter(
    "Medias", AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, IMAGE_EXTENSIONS)
# Cartouches et localisation de média : audio + vidéo, sans les images.
AV_EXTENSIONS_FILTER = _ext_filter("Medias", AUDIO_EXTENSIONS, VIDEO_EXTENSIONS)

# === CONFIGURATION GLOBALE ===
APP_NAME = "MyStrow"
VERSION = "3.1.87"

# Période du timer d'envoi DMX, en millisecondes (25 ms = 40 fps).
# Constante partagée et non valeur recopiée : le timer était relancé à 40 ms
# après un passage dans le testeur DMX, et le parc restait à 25 fps pour tout
# le reste de la session — « le DMX rame, un redémarrage corrige ».
DMX_FRAME_MS = 25

# === FIREBASE (clé publique Web — identique à compte.html) ===
FIREBASE_API_KEY    = "AIzaSyAQjGJXGCSWzOE-wvKXh6sbZy6JDhL8tqA"
FIREBASE_PROJECT_ID = "mystrow-907be"

# === BREVO (email marketing + transactionnel) ===
# Récupérer la clé API dans Brevo > SMTP & API > API Keys
BREVO_API_KEY      = ""  # Clé stockée dans brevo_config.py (ignoré par git)
BREVO_SENDER_EMAIL = "hello@mystrow.io"  # Domaine à vérifier dans Brevo
BREVO_SENDER_NAME  = "MyStrow"
BREVO_LIST_ID      = 3                  # ID de la liste newsletter (entier, 0 = sans liste)
try:
    # Surcharge locale optionnelle (dev only) — ignorée si la clé est vide
    import firebase_config as _fc
    if getattr(_fc, "FIREBASE_API_KEY", ""):
        FIREBASE_API_KEY = _fc.FIREBASE_API_KEY
    if getattr(_fc, "FIREBASE_PROJECT_ID", ""):
        FIREBASE_PROJECT_ID = _fc.FIREBASE_PROJECT_ID
except ImportError:
    pass
try:
    import brevo_config as _bc
    if getattr(_bc, "BREVO_API_KEY", ""):
        BREVO_API_KEY = _bc.BREVO_API_KEY
except ImportError:
    pass

# === MIDI SUPPORT ===
# Détection via find_spec (sans importer le module — évite le scan MIDI au démarrage)
import importlib.util as _iutil
from i18n import tr
MIDI_AVAILABLE = False
midi_lib = None
if _iutil.find_spec("rtmidi") is not None:
    MIDI_AVAILABLE = True
    midi_lib = "rtmidi"
elif _iutil.find_spec("rtmidi2") is not None:
    MIDI_AVAILABLE = True
    midi_lib = "rtmidi2"

# === MAPPING COULEURS AKAI ===
AKAI_COLOR_MAP = {
    "white": 5,      # Jaune vif (le plus proche du blanc)
    "red": 3,        # Rouge vif
    "orange": 9,     # Orange vif
    "yellow": 13,    # Jaune-vert vif
    "green": 25,     # Vert lime vif
    "cyan": 37,      # Cyan
    "blue": 45,      # Bleu
    "violet": 53,    # Violet vif
    "magenta": 49,   # Rose/Magenta vif
}

# Mapping hex exact des couleurs du simulateur
HEX_COLOR_MAP = {
    "#ffffff": 3,   # Blanc -> Rouge vif (interverti avec ligne 2)
    "#ff0000": 5,   # Rouge -> Jaune (interverti avec ligne 1)
    "#ff8800": 9,   # Orange -> Orange vif (9)
    "#ffdd00": 13,  # Jaune -> Jaune vif (13)
    "#00ff00": 21,  # Vert -> Vert vif (21)
    "#00dddd": 37,  # Cyan -> Cyan (37)
    "#0000ff": 45,  # Bleu -> Bleu (45)
    "#ff00ff": 53,  # Magenta/Violet -> Violet (53)
}


def rgb_to_akai_velocity(qcolor):
    """Convertit une QColor RGB en velocite AKAI (approximation)"""
    r, g, b = qcolor.red(), qcolor.green(), qcolor.blue()

    # Detection par couleur HTML (plus precis)
    hex_color = qcolor.name().lower()

    # Chercher la couleur exacte
    if hex_color in HEX_COLOR_MAP:
        return HEX_COLOR_MAP[hex_color]

    # Sinon, approximation par dominante
    # Blanc (toutes composantes elevees)
    if r > 200 and g > 200 and b > 200:
        return 5  # Jaune vif (proche du blanc)

    # Rouge dominant
    if r > 150 and g < 150 and b < 150:
        return 3  # Rouge pur

    # Orange (rouge + vert moyen)
    if r > 200 and g > 100 and g < 200 and b < 100:
        return 9  # Orange

    # Jaune (rouge + vert)
    if r > 200 and g > 200 and b < 100:
        return 13  # Jaune

    # Vert dominant
    if g > 150 and r < 150 and b < 150:
        return 21  # Vert

    # Cyan (vert + bleu)
    if g > 150 and b > 150 and r < 100:
        return 37  # Cyan

    # Bleu dominant
    if b > 150 and r < 150 and g < 150:
        return 45  # Bleu

    # Magenta (rouge + bleu)
    if r > 150 and b > 150 and g < 100:
        return 53  # Violet/Magenta

    # Par defaut
    return 5


def resource_path(filename):
    """Retourne le chemin absolu d'une ressource embarquee.
    Compatible mode dev et PyInstaller --onefile (sys._MEIPASS)."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def ffmpeg_exe():
    """Chemin de l'exécutable ffmpeg.

    Priorité au binaire EMBARQUÉ (bundlé dans l'exe via PyInstaller → transparent
    pour l'utilisateur, aucune installation ni ffmpeg dans le PATH requis). Repli
    sur « ffmpeg » du PATH (utile en dev ou si un ffmpeg système est présent).

    Vit ici et non dans light_timeline : c'est le SEUL décodeur capable de lire
    l'ALAC, l'AIFF ou l'Opus (miniaudio s'arrête à wav/mp3/flac/ogg), donc la
    forme d'onde ET l'IA Lumière en dépendent toutes les deux.
    """
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    try:
        p = resource_path(name)
        if os.path.exists(p):
            return p
    except Exception:
        pass
    return "ffmpeg"


def fmt_time(ms):
    """Formate un temps en ms : MM:SS, ou H:MM:SS au-delà d'une heure."""
    if ms <= 0:
        return "00:00"
    s = ms // 1000
    h = s // 3600
    if h > 0:
        return f"{h}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s//60:02d}:{s%60:02d}"


def media_icon(path):
    """Retourne un emoji selon le type de fichier media"""
    ext = Path(path).suffix.lower()
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "file"


def create_icon(icon_type, color="#ffffff"):
    """Cree des icones elegantes type console pro"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    if icon_type == "play":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        points = [QPoint(18, 12), QPoint(18, 52), QPoint(52, 32)]
        painter.drawPolygon(QPolygon(points))
    elif icon_type == "pause":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(18, 12, 10, 40, 2, 2)
        painter.drawRoundedRect(36, 12, 10, 40, 2, 2)
    elif icon_type == "prev":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(16, 18, 4, 28, 2, 2)
        points = [QPoint(48, 18), QPoint(48, 46), QPoint(22, 32)]
        painter.drawPolygon(QPolygon(points))
    elif icon_type == "next":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(44, 18, 4, 28, 2, 2)
        points = [QPoint(16, 18), QPoint(16, 46), QPoint(42, 32)]
        painter.drawPolygon(QPolygon(points))
    elif icon_type == "tap":
        # Cercle plein centré — représente un tap/impulsion
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(16, 16, 32, 32)
    elif icon_type == "to_start":
        # |◀  aller au début
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(14, 16, 5, 32, 2, 2)
        points = [QPoint(48, 16), QPoint(48, 48), QPoint(21, 32)]
        painter.drawPolygon(QPolygon(points))
    elif icon_type == "to_end":
        # ▶|  aller à la fin
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        points = [QPoint(16, 16), QPoint(16, 48), QPoint(43, 32)]
        painter.drawPolygon(QPolygon(points))
        painter.drawRoundedRect(45, 16, 5, 32, 2, 2)

    painter.end()
    return QIcon(pixmap)


# ─── Répartition des effets entre fixtures ────────────────────────────────────
# Partagé par le moteur (main_window) et l'éditeur d'effets : une seule source
# de vérité, sinon les deux divergeraient et l'aperçu mentirait sur le rendu.

SPREAD_MODES = [
    ("lineaire",    "Linéaire",         "1, 2, 3, 4… — chenillard classique"),
    ("miroir",      "Miroir (centre)",  "Part du centre vers les extrémités"),
    ("miroir_in",   "Miroir (bords)",   "1&8, puis 2&7, puis 3&6 — paires symétriques"),
    ("pair_impair", "Pair / impair",    "Une fixture sur deux, en alternance"),
    ("aleatoire",   "Aléatoire",        "Ordre dispersé, mais reproductible"),
]


def spread_rank(i, n, mode="lineaire"):
    """
    Rang normalisé (0..1) d'une fixture pour la répartition d'un effet.

    C'est ce rang que le « Décalage » transforme en déphasage. En linéaire il
    suit l'ordre de patch (1, 2, 3…), d'où le chenillard classique. Les autres
    modes rendent le même rang à plusieurs fixtures, qui s'allument alors
    ensemble — « miroir (bords) » donne 1&8, puis 2&7, puis 3&6.

    Vaut pour des projecteurs classiques comme pour les pixels d'une barre :
    un pixel est une fixture parmi les autres.
    """
    n = max(1, int(n))
    if n == 1:
        return 0.0
    # Distance au centre, 0 au milieu → 1 aux extrémités.
    # Rang le plus BAS = fixture qui passe en premier.
    dist = abs(i - (n - 1) / 2.0) / ((n - 1) / 2.0)
    if mode == "miroir":
        return dist            # centre d'abord, puis vers les bords
    if mode == "miroir_in":
        return 1.0 - dist      # bords d'abord : 1&8, puis 2&7, puis 3&6
    if mode == "pair_impair":
        return 0.0 if i % 2 == 0 else 0.5
    if mode == "aleatoire":
        # Déterministe : un show rejoué doit donner exactement la même figure.
        # Mélange type Knuth : un simple i*K % M reste monotone sur de petits
        # index et ne disperserait rien du tout.
        h = (i + 1) * 2654435761 % 4294967296
        h ^= h >> 13
        h = (h * 1274126177) % 4294967296
        h ^= h >> 16
        return (h % 10000) / 10000.0
    return i / n


def position_preset_values(preset, lyres):
    """{id(lyre): (pan, tilt)} d'un preset de position, apparié aux lyres présentes.

    Appariement en trois passes — adresse DMX (clé la plus sûre : unique par
    fixture et insensible aux renommages), puis nom, puis rang dans la liste.
    Trois passes et non un test à trois branches par lyre : sinon une lyre
    appariée par nom pouvait manger l'entrée qu'une lyre suivante réclamait par
    son adresse.

    Une entrée déjà attribuée est **consommée** : deux lyres ne peuvent pas
    hériter du même état. Sans ça, deux lyres homonymes dont la seconde a été
    repatchée recevaient toutes les deux la position de la première (elle
    n'avait pas consommé son entrée en s'appariant par adresse), et deux lyres
    à la même adresse tombaient toutes les deux sur la dernière entrée.

    Une lyre sans correspondance est absente du résultat : à l'appelant de lui
    laisser la position qu'elle a déjà — et de prévenir l'utilisateur, car un
    preset enregistré quand le rig comptait moins de lyres laisse sinon les
    nouvelles immobiles, sans le moindre message.

    Source unique pour le rappel manuel d'une position ET pour le centre d'un
    effet Pan/Tilt : un cercle doit tourner autour du point où le rappel aurait
    posé la lyre, pas ailleurs.
    """
    out = {}
    etats = (preset or {}).get("projectors", []) or []

    par_addr, par_nom = {}, {}
    for j, s in enumerate(etats):
        addr = str(s.get("start_address") or "")
        if addr:
            par_addr.setdefault(addr, []).append(j)
        nom = s.get("name")
        if nom:
            par_nom.setdefault(nom, []).append(j)

    pris = set()          # index des entrées déjà attribuées
    apparie = {}          # index de lyre -> index d'entrée

    def _libre(indices):
        for j in indices:
            if j not in pris:
                return j
        return None

    # Passe 1 : adresse DMX
    for i, p in enumerate(lyres):
        addr = str(getattr(p, 'start_address', '') or '')
        j = _libre(par_addr.get(addr, [])) if addr else None
        if j is not None:
            apparie[i] = j
            pris.add(j)

    # Passe 2 : nom
    for i, p in enumerate(lyres):
        if i in apparie:
            continue
        nom = getattr(p, 'name', '')
        j = _libre(par_nom.get(nom, [])) if nom else None
        if j is not None:
            apparie[i] = j
            pris.add(j)

    # Passe 3 : rang dans la liste
    for i, p in enumerate(lyres):
        if i in apparie or i >= len(etats) or i in pris:
            continue
        apparie[i] = i
        pris.add(i)

    for i, p in enumerate(lyres):
        j = apparie.get(i)
        if j is None:
            continue
        etat = etats[j]
        out[id(p)] = (int(etat.get("pan", 32768)),
                      int(etat.get("tilt", 32768)))
    return out


def find_position_preset(presets, idx, name=""):
    """Retrouve un preset de position par index, en se rattrapant sur le nom.

    Les couches d'effet stockent l'index (convention des clips de position),
    mais un preset renommé, inséré ou supprimé décalerait la liste : le nom
    sert alors de filet. Rend None si rien ne correspond.
    """
    presets = presets or []
    if idx is not None and 0 <= int(idx) < len(presets):
        trouve = presets[int(idx)]
        if not name or trouve.get("name") == name:
            return trouve
    if name:
        return next((p for p in presets if p.get("name") == name), None)
    return None


def chase_slot(pos_cycles, n, direction=1):
    """Rang allumé à un instant donné d'un chenillard exclusif (forme « Un par un »).

    `pos_cycles` = position exprimée en NOMBRE DE CYCLES (`freq*t` + départ) :
    un cycle entier fait défiler la cible une fois de bout en bout. La fonction
    ne rend qu'UN seul rang — c'est là toute l'exclusivité : les autres fixtures
    sont éteintes, sans dépendre du DÉCALAGE ni de la largeur d'une forme d'onde.

    Les formes classiques ne peuvent pas donner ça : « Flash » est allumé la
    moitié du cycle, donc la moitié du rig est toujours allumée, quel que soit
    le décalage.

    Sens : 1 = 1,2,3… · -1 = 1, puis n, n-1… · 0 = aller-retour sans redoubler
    les extrémités (1,2,3,4,5,4,3,2).
    """
    n = max(1, int(n))
    if n == 1:
        return 0
    # `// 1` plutôt qu'int() : il faut un plancher, y compris sur un départ
    # négatif — int() tronquerait vers zéro et ferait bégayer le rang 0.
    p = int((float(pos_cycles) * n) // 1)
    if direction == 0:
        m = 2 * n - 2
        q = p % m
        return q if q < n else m - q
    if direction == -1:
        return (-p) % n
    return p % n


def block_index(i, n, block):
    """Replie l'index d'une fixture sur des paquets de `block` fixtures.

    C'est la colonne GROUPER de l'éditeur d'effets : au lieu d'une phase par
    fixture, une phase par PAQUET. Avec 25 projecteurs et block=5, les 5
    premiers partagent l'index 0, les 5 suivants l'index 1… soit 5 phases —
    la rangée entière s'allume d'un coup et c'est la rangée qui défile.

    Retourne (index de paquet, nombre de paquets), à passer tels quels à
    `spread_rank`. block ≤ 1 rend l'index inchangé : les effets existants,
    enregistrés sans cette clé, gardent exactement leur figure.

    Le dernier paquet peut être incomplet (25 fixtures par 4 → 6 paquets dont
    un de 1) : c'est voulu, plutôt que de refuser les tailles non divisibles.
    """
    n = max(1, int(n))
    b = max(1, int(block or 1))
    if b <= 1:
        return int(i), n
    return int(i) // b, max(1, (n + b - 1) // b)


def layer_frequency(speed, mult=1.0, fader_mult=1.0):
    """Cycles par seconde d'une couche d'effet, depuis sa VITESSE 0-100.

    La formule `0.05 + speed/100 * 7` portait un plancher de 0.05 Hz qui ne
    disparaissait JAMAIS : vitesse 0 laissait tourner l'effet à un cycle toutes
    les 20 secondes. Le curseur descend bien à 0 (cf. _NUM_FIELDS), et un
    utilisateur qui pose 0 attend un arrêt, pas un rampement invisible qu'on
    finit par prendre pour une dérive de l'application.

    Vitesse 0 rend donc 0.0 : la couche est FIGÉE. Elle n'est pas éteinte pour
    autant — la forme reste évaluée à sa position de départ, décalage et
    RÉPARTITION compris, ce qui donne une pose statique étalée sur les
    fixtures. C'est la seule lecture cohérente de « vitesse nulle ».

    `mult` est le multiplicateur de vitesse d'un axe (trajectoires Pan/Tilt),
    appliqué à la VITESSE, donc avant le plancher — comme dans le code d'origine.
    `fader_mult` est le fader FX général, appliqué à la fréquence finale : à 0
    il gelait déjà tout, ce comportement est conservé.

    ⚠️ Point UNIQUE : sept endroits recopiaient cette formule (l'aperçu de
    l'éditeur, sa vignette de courbe, les deux axes d'une trajectoire, et les
    trois équivalents du moteur de restitution). Toute divergence entre eux
    rejoue « l'aperçu ne ressemble pas au show ». Passer par ici.
    """
    s = max(0.0, float(speed or 0.0)) * float(mult if mult is not None else 1.0)
    if s <= 0.0:
        return 0.0
    return (0.05 + s / 100.0 * 7.0) * float(fader_mult if fader_mult is not None else 1.0)


def random_wave(freq, t, index):
    """Valeur 0-1 de la forme « Aléatoire », renouvelée une fois par cycle.

    « Aléatoire » était la seule forme dont la VITESSE ne servait à rien : les
    trois moteurs tiraient un nombre au hasard à une cadence codée en dur —
    à chaque frame DMX en live (25 Hz), 15 Hz dans l'aperçu, 12 Hz dans la
    vignette de courbe. VIT restait réglable dans le tableau mais n'agissait
    sur rien, VIT 0 ne figeait pas, et le show scintillait plus vite et plus
    dur que son propre aperçu.

    La graine est ici le NUMÉRO DE CYCLE (`int(freq*t)`) : la couche tire une
    nouvelle valeur une fois par cycle, exactement comme les autres formes
    parcourent leur courbe une fois par cycle. VIT reprend donc son sens
    habituel, et freq=0 (VIT 0, ou fader FX à 0) fige le motif au lieu de le
    laisser grésiller.

    `index` est le rang de la fixture (ou le pixel, dans la vignette) : les
    fixtures changent ensemble mais chacune vers sa propre valeur — c'est ce
    qui fait le scintillement plutôt qu'un flash commun.

    ⚠️ Point UNIQUE, au même titre que `layer_frequency` : le live, l'aperçu de
    l'éditeur et la vignette doivent tirer le MÊME nombre, sinon on rejoue
    « l'aperçu ne ressemble pas au show ».
    """
    return random.Random(int(float(freq) * float(t)) * 1000 + int(index)).random()


def effect_dim_base_color(proj, current):
    """Couleur que module un effet DIMMER SEUL sur cette fixture.

    Une couche Dimmer sans couche couleur ne fait qu'atténuer la couleur déjà
    posée sur le projecteur. Sur un spot dont la couleur vient de sa ROUE — un
    profil sans canal R/G/B — cette couleur RGB est une fiction : le faisceau
    sort blanc dès que le Dim s'ouvre, quelle que soit la valeur RGB gardée
    côté application.

    Or `base_color` est remis à NOIR par tous les chemins d'extinction
    (blackout, rappel de mémoire sans projecteur actif, reset de cue). Noir ×
    dimmer restait noir : la lyre s'affichait éteinte dans le plan de feu, la
    3D et l'aperçu de l'éditeur — alors que le canal Dim sortait bien et que le
    vrai projecteur pulsait. D'où le réflexe d'ajouter une couche RGB blanche
    qui ne servait qu'à réparer l'image.

    Rend donc BLANC pour ces fixtures, et `current` inchangé partout ailleurs :
    un profil vide (fixture non patchée) compte comme « ailleurs », faute de
    quoi on repeindrait en blanc des projecteurs dont on ne sait rien.

    ⚠️ Point UNIQUE : le moteur de restitution et l'aperçu de l'éditeur ont
    chacun leur branche « Dimmer seul ». Les faire diverger ici, c'est rejouer
    « l'aperçu ne ressemble pas au show ». Passer par ici.
    """
    profile = getattr(proj, 'dmx_profile', None) or []
    if not profile or 'R' in profile or 'G' in profile or 'B' in profile:
        return current
    return QColor(255, 255, 255)


def cw_full_value(r, g, b):
    """Ramene une couleur a pleine valeur (composante max = 255).

    Une roue de couleurs ne porte qu'une TEINTE : l'intensite est portee par le
    dimmer/shutter, jamais par la position de la roue. Toute comparaison de
    couleur destinee a choisir un slot doit donc se faire a pleine valeur des
    deux cotes, sinon la distance RVB est dominee par la luminosite et le choix
    part sur le slot le plus SOMBRE des que la couleur baisse.
    """
    m = max(r, g, b)
    if m == 0:
        return (r, g, b)
    return (r * 255 // m, g * 255 // m, b * 255 // m)


def cw_slot_for_color(slots, color):
    """Slot de roue dont la TEINTE est la plus proche de `color`.

    Renvoie None si la couleur est noire : le noir n'a pas de teinte, il n'y a
    donc rien a choisir et la roue doit rester ou elle est. C'est ce cas qui
    faisait osciller une lyre a roue entre vert et blanc : les moteurs d'effets
    rappellent le mapping a chaque frame avec `proj.color`, noir une frame sur
    deux en Strobe/Flash, et le noir « ressemblait » au slot vert de la table
    generique (distance a #00cc44 plus courte qu'a #ffffff).

    Metrique unique de l'app : `MainWindow._update_color_wheel` (pads, memoires,
    timeline, tablette) et le selecteur de couleur du plan 2D passent tous ici.
    """
    if not slots:
        return None
    cr, cg, cb = color.red(), color.green(), color.blue()
    if max(cr, cg, cb) == 0:
        return None
    cr, cg, cb = cw_full_value(cr, cg, cb)

    def _dist(s):
        sc = QColor(s.get('color', '#ffffff'))
        sr, sg, sb = cw_full_value(sc.red(), sc.green(), sc.blue())
        return (sr - cr) ** 2 + (sg - cg) ** 2 + (sb - cb) ** 2

    return min(slots, key=_dist)


def projector_selection_keys(projectors):
    """Clé (groupe, index_local) de chaque projecteur, dans l'ordre de la liste.

    Même convention que le plan de feu (PlanDeFeu._local_idx_for) : un compteur
    par groupe. C'est l'identité utilisée par la cible « Sélection » d'un effet
    pour viser des projecteurs PRÉCIS, indépendamment de leur groupe. Doit rester
    identique entre l'aperçu de l'éditeur (_compute_preview) et le moteur de
    restitution (_update_effect_from_layers) — sinon l'aperçu diverge du show.
    """
    keys = []
    counters = {}
    for p in projectors:
        g = getattr(p, 'group', '')
        li = counters.get(g, 0)
        counters[g] = li + 1
        keys.append((g, li))
    return keys


def layer_selection_ranks(layer):
    """Rang de chaque projecteur d'une couche « Sélection », dans l'ordre choisi.

    Retourne {(groupe, index_local): rang}, rang partant de 0. L'ORDRE de la
    liste `target_selection` est celui des clics sur le plan de feu : c'est lui
    que les moteurs donnent à `spread_rank`, pour qu'un chenillard parte dans le
    sens voulu (1, 2, 3…) au lieu de l'ordre du patch. Un doublon garde son
    premier rang.

    Accepte un dict (moteur) ou un objet EffectLayer (éditeur) ; vide si la
    couche ne cible pas une sélection.
    """
    if isinstance(layer, dict):
        sel = layer.get('target_selection') or []
    else:
        sel = getattr(layer, 'target_selection', None) or []
    out = {}
    for pair in sel:
        try:
            g, li = pair
            key = (g, int(li))
        except Exception:
            continue
        if key not in out:
            out[key] = len(out)
    return out


def layer_selection_set(layer):
    """Ensemble {(groupe, index_local)} ciblé par une couche « Sélection ».

    Conservé pour un simple test d'appartenance : les moteurs, eux, utilisent
    `layer_selection_ranks` car ils ont aussi besoin de l'ordre.
    """
    return set(layer_selection_ranks(layer))


# ─── Libellés courts de canaux ────────────────────────────────────────────────
# Le TYPE stocké reste inchangé (« Ambre ») : seul l'affichage est raccourci,
# pour tenir dans les pastilles et les blocs de profil.
CH_SHORT = {
    "Ambre": "A",
}


def channel_label(ch):
    """Libellé d'affichage d'un type de canal."""
    return CH_SHORT.get(ch, ch)


# ─── Noms de canaux : un seul vocabulaire ─────────────────────────────────────
# Deux bibliothèques alimentent les profils, et elles ne nommaient pas les mêmes
# canaux pareil. Les 194 fixtures natives emploient le vocabulaire du moteur
# (« Ambre ») ; les 1710 fixtures QLC+ étaient recopiées telles quelles avec le
# leur (« A »). Résultat : le moteur cherchait « Ambre » dans un profil qui
# disait « A », et la branche correspondante ne s'exécutait JAMAIS.
#
# `Effects` et `Gobo1Rot` étaient les plus touchés : aucune des deux
# bibliothèques ne les écrivait sous ce nom, donc ces deux branches de
# `artnet_dmx` étaient du code mort — 3654 canaux « Effect » et 56 « GoboRot »
# dans la base, tous muets.
CHANNEL_ALIASES = {
    "A":        "Ambre",     # QLC+ : LED ambre
    "Amber":    "Ambre",
    "Effect":   "Effects",   # QLC+ : canal macro/effet interne
    "GoboRot":  "Gobo1Rot",  # QLC+ : rotation/indexation du gobo
    "Gobo1Rotation": "Gobo1Rot",
    "PrismRotation": "PrismRot",
}


def canonical_channel(ch):
    """Nom de canal ramené au vocabulaire du moteur DMX."""
    return CHANNEL_ALIASES.get(ch, ch) if isinstance(ch, str) else ch


def canonical_profile(profile):
    """Profil complet canonicalisé. Tolère None et les valeurs non-texte."""
    if not profile:
        return []
    return [canonical_channel(c) for c in profile]


# ─── TLS : un seul contexte pour tout le réseau sortant ───────────────────────

_SSL_CTX_CACHE = None


def make_ssl_context():
    """Contexte SSL compatible Mac / Windows / PyInstaller.

    On fait confiance à l'UNION des racines :
      1. magasin système — sur Windows il inclut les racines injectées par les
         antivirus à scan HTTPS (Avast, Kaspersky, ESET…) et les proxys
         d'entreprise. Sans elles, leur MITM TLS casse la vérification (alors
         que le navigateur, lui, passe par le magasin système) ;
      2. bundle certifi — indispensable sur macOS où Python n'embarque pas de
         racines système, et complément utile sur Windows.
    La vérification reste ACTIVE : aucun downgrade de sécurité.

    ⚠️ Ne JAMAIS écrire `ssl.create_default_context(cafile=certifi.where())` :
    passer un `cafile` empêche CPython de charger les racines système
    (`create_default_context` ne fait `load_default_certs()` que si aucun
    cafile/capath/cadata n'est fourni). On obtient alors certifi SEUL, ce qui
    a laissé les écrans de licence en erreur SSL derrière un antivirus bien
    après que la mise à jour, elle, ait été réparée (remontée du 12/08/2026).
    """
    global _SSL_CTX_CACHE
    if _SSL_CTX_CACHE is not None:
        return _SSL_CTX_CACHE
    import ssl
    ctx = None
    try:
        ctx = ssl.create_default_context()        # racines système
    except Exception:
        ctx = None
    try:
        import certifi
        if ctx is not None:
            ctx.load_verify_locations(cafile=certifi.where())   # + certifi
        else:
            ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    if ctx is None:
        ctx = ssl.create_default_context()
    _SSL_CTX_CACHE = ctx
    return ctx


# ─── Téléchargement officiel ──────────────────────────────────────────────────

SITE_URL = "https://mystrow.fr/"

# Point d'entrée officiel du téléchargement : la Cloud Function du site, qui
# redirige vers l'asset GitHub de la dernière version ET enregistre la
# statistique de téléchargement. On ne code donc PAS l'URL GitHub en dur — le
# dialogue d'erreur d'intégrité pointait ainsi sur « MyStrow_Installer.dmg »,
# un nom d'asset qui n'existe plus : bouton en 404 pour tous les utilisateurs
# Mac, précisément au moment où l'application refuse de démarrer.
_DOWNLOAD_REDIRECT = ("https://us-central1-mystrow-907be.cloudfunctions.net"
                      "/download_redirect?p=")


def download_url() -> str:
    """URL de téléchargement de l'installeur pour la plateforme courante."""
    if sys.platform == "darwin":
        import platform as _pf
        return _DOWNLOAD_REDIRECT + ("mac" if _pf.machine() == "arm64" else "mac_intel")
    return _DOWNLOAD_REDIRECT + "win"


def fit_button(btn, marge: int = 30):
    """Donne à un bouton une largeur minimale suffisante pour SON texte.

    Les libellés sont traduits (fr/en/es) et souvent préfixés d'un emoji : une
    largeur figée finit toujours par tronquer dans une langue ou une autre, ou
    dès qu'on ajoute un bouton dans la rangée. Mesuré : « 📁 Joindre les logs »
    réclame 242 px et n'en recevait que 120 dans la fenêtre « Soumettre une
    idée » (3 boutons dans 420 px fixes).

    `marge` couvre le rembourrage de la feuille de style et la bordure.
    """
    texte = btn.text()
    if texte:
        btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(texte) + marge)
    return btn


# ─── Listes déroulantes insensibles à la molette ──────────────────────────────

class ComboSansMolette(QComboBox):
    """QComboBox qui IGNORE la molette.

    Presque toutes nos listes vivent dans une fenêtre défilante. Avec un
    QComboBox standard, faire défiler la page en passant au-dessus d'une liste
    en change la valeur au lieu de scroller — et la liste avale en plus le
    défilement, donc la page ne bouge pas : l'utilisateur insiste, et modifie un
    réglage à chaque cran, sans le moindre retour visuel. Sur l'aiguillage des
    sorties DMX ça réaffecte un univers, sur le patch ça change le profil d'une
    fixture, en pleine prestation.

    `ignore()` laisse l'événement remonter à la zone défilante : la page scrolle
    normalement. La valeur reste réglable au clic et au clavier.

    À utiliser pour TOUTE nouvelle liste déroulante — le seul cas où un
    QComboBox nu se justifie est une liste hors de toute zone défilante, et ça
    ne coûte rien de prendre celle-ci quand même.
    """

    def wheelEvent(self, event):
        event.ignore()


# ─── Blocs « canal dédié » (UV / Ambre) ───────────────────────────────────────
# Deux couleurs de la palette REC Lumière ne désignent pas une teinte à
# reconstituer en RVB mais une LED DÉDIÉE de la fixture : « Black Light » = la
# LED UV, « Ambre » = la LED ambre. Poser ces blocs doit piloter CE canal seul,
# à 100 %, et laisser le RVB à zéro — un violet RVB n'excite aucun pigment
# fluorescent, et l'ambre reconstitué en RVB donne un jaune sale à côté de la
# vraie LED. Même logique que les curseurs du plan de feu : ces canaux ne sont
# jamais dérivés du RVB (cf. artnet_dmx, Ambre/Orange pilotés au boost seul).
#
# Chaque bloc liste PLUSIEURS canaux candidats, par ordre de préférence : une
# même LED physique n'a pas le même nom d'un patch à l'autre. La LED ambre d'un
# par 6-en-1 (RVB + Blanc + Ambre + UV) s'appelle « Ambre » dans un profil
# custom, mais « Orange » dans le profil intégré RGBWOUV — et l'import de
# bibliothèque range aussi les emitters ambrés sous « Orange » quand leur teinte
# déclarée penche vers #ff8800. Ne chercher que « Ambre » faisait échouer le
# bloc sur ces fixtures : il retombait sur l'approximation RVB, et le moteur DMX
# extrait alors min(R,V,B) vers le canal W — la LED ambre restait éteinte et
# c'est la BLANCHE qui s'allumait (« l'ambre sort du blanc », remonté en 3.1.79,
# la version qui a introduit ces blocs).
SPECIAL_BLOCK_COLORS = {
    (100,   0, 255): (("UV",    "uv"),),                                # « Black Light »
    (255, 180,  30): (("Ambre", "amber_boost"), ("Orange", "orange_boost")),  # « Ambre »
}

# Teinte d'AFFICHAGE des canaux dédiés (plan de feu). Uniquement du rendu :
# proj.color doit rester la vraie valeur RVB envoyée en DMX, sinon la LED
# rouge/bleue s'allumerait en même temps que la LED dédiée.
SPECIAL_TINTS = {
    "uv":           (136,  68, 255),
    "amber_boost":  (255, 153,   0),
    "orange_boost": (255, 136,   0),
}


def special_block_channel(color, profile=None):
    """(canal_du_profil, attribut_projecteur) si `color` est un bloc dédié.

    Reconnaissance par valeur RVB EXACTE. C'est ce qui fait marcher les shows
    déjà enregistrés : un bloc couleur n'est sérialisé que par sa couleur, il
    n'y a donc aucun drapeau à migrer dans les .tui/.lrec existants. Une teinte
    voisine choisie à la main (violet, orange…) reste du RVB normal.

    `profile` : liste des canaux de la fixture. Le premier candidat qu'elle
    possède gagne. Sans profil, on renvoie le candidat préféré (usage hors
    fixture, comme l'extinction de tous les canaux dédiés).
    """
    if color is None:
        return None
    try:
        key = (color.red(), color.green(), color.blue())
    except AttributeError:
        return None
    candidats = SPECIAL_BLOCK_COLORS.get(key)
    if not candidats:
        return None
    if profile is None:
        return candidats[0]
    for ch_name, attr in candidats:
        if ch_name in profile:
            return (ch_name, attr)
    return None


def apply_special_block(proj, color, intensity):
    """Applique un bloc « canal dédié » (UV / Ambre) sur `proj`.

    Retourne True si le bloc a été traité comme canal dédié — l'appelant ne doit
    alors PAS poser la couleur RVB. Retourne False si la fixture n'a pas ce
    canal : on retombe sur le rendu RVB d'origine (approximation), sinon poser
    un bloc UV sur un PAR RVB l'éteindrait purement et simplement.

    Le niveau du bloc est conservé : sur une fixture à canal Dim, la LED dédiée
    passe DERRIÈRE le master (Dim = proj.level dans le moteur DMX) — la mettre à
    255 avec un dimmer fermé ne donnerait rien.
    """
    spec = special_block_channel(color, getattr(proj, 'dmx_profile', None) or [])
    if not spec:
        return False
    _ch_name, attr = spec
    lvl = max(0, min(100, int(intensity)))
    setattr(proj, attr, int(255 * lvl / 100.0))
    proj.level      = lvl
    proj.base_color = QColor(0, 0, 0)
    proj.color      = QColor(0, 0, 0)
    return True


def clear_special_blocks(proj):
    """Éteint les canaux dédiés qu'un bloc peut allumer (UV, Ambre).

    À appeler quand on pose une couleur NORMALE par un chemin exclusif (boutons
    couleur de la fenêtre EXT, raccourcis clavier) : ces boutons se remplacent
    l'un l'autre, et sans ça « BLACK LIGHT puis ROUGE » sortait rouge **avec**
    l'UV encore allumé. Couvre TOUS les canaux qu'un bloc peut viser, y compris
    `orange_boost` — sur les profils où la LED ambre s'appelle « Orange », c'est
    lui que le bloc Ambre a allumé. Le boost Blanc n'est jamais touché : aucun
    bloc ne le pilote, il reste purement additif.
    """
    for candidats in SPECIAL_BLOCK_COLORS.values():
        for _ch, attr in candidats:
            setattr(proj, attr, 0)


def special_tint_color(proj):
    """Couleur d'affichage d'une fixture allumée uniquement sur un canal dédié.

    Sans ça, un bloc UV affiche la fixture ÉTEINTE dans le plan de feu (son RVB
    est à zéro) alors qu'elle éclaire pour de vrai.
    """
    r = g = b = 0.0
    for attr, (tr, tg, tb) in SPECIAL_TINTS.items():
        f = max(0, min(255, int(getattr(proj, attr, 0) or 0))) / 255.0
        if f <= 0:
            continue
        r += tr * f
        g += tg * f
        b += tb * f
    return QColor(min(255, int(r)), min(255, int(g)), min(255, int(b)))


# === BANDEAU « CONSULTER LE GUIDE » ===

# Bandeau discret en pied de fenêtre renvoyant vers un guide du site.
# Centralisé ici pour que toutes les fenêtres gardent EXACTEMENT la même
# présentation : le style était recopié à la main d'une fenêtre à l'autre, et
# rien n'empêchait une couleur ou une taille de dériver au fil des ajouts.
GUIDE_BANNER_HEIGHT = 20
GUIDE_BANNER_BG     = "#060606"
GUIDE_BANNER_BORDER = "#101010"
GUIDE_BANNER_FG     = "#333"
GUIDE_BANNER_SIZE   = "10px"


def guide_banner(texte: str, url: str) -> QLabel:
    """Bandeau « <texte> → Consulter le guide » cliquable, en pied de fenêtre.

    `texte` est l'accroche, sans la flèche ni la mention du guide : elles sont
    ajoutées ici pour que la formulation reste homogène partout.
    """
    lbl = QLabel(
        f'<a href="{url}"'
        f' style="color:{GUIDE_BANNER_FG};text-decoration:none;'
        f'font-size:{GUIDE_BANNER_SIZE};">'
        f'{texte} → Consulter le guide</a>'
    )
    lbl.setStyleSheet(
        f"background:{GUIDE_BANNER_BG}; padding:0 14px; "
        f"border-top:1px solid {GUIDE_BANNER_BORDER};"
    )
    lbl.setOpenExternalLinks(True)
    lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    lbl.setFixedHeight(GUIDE_BANNER_HEIGHT)
    return lbl


# Variante encadrée verte, à poser EN HAUT de la fenêtre. Le bandeau discret
# ci-dessus se fait oublier — précisément ce qu'on ne veut pas quand le réglage
# se joue pour moitié dans un AUTRE logiciel (le node DMX, OBS, vMix) et que
# rien dans la fenêtre ne peut le montrer. En pied de fenêtre il passait en
# prime sous la barre des tâches sur certaines configurations.
GUIDE_ENCART_BG     = "#161f16"
GUIDE_ENCART_BORDER = "#2a3a2a"
GUIDE_ENCART_FG     = "#888"
GUIDE_ENCART_LINK   = "#44cc88"


def guide_banner_encart(texte: str, url: str, lien: str = "Consulter le guide →") -> QLabel:
    """Encart vert « 💡 <texte>  <lien> », centré, à placer en tête de fenêtre.

    `texte` est l'accroche seule ; l'ampoule et le libellé du lien sont ajoutés
    ici pour que les fenêtres qui renvoient vers le site restent identiques.
    """
    lbl = QLabel(
        f'💡  {texte}  '
        f'<a href="{url}" style="color:{GUIDE_ENCART_LINK};'
        f'text-decoration:underline;">{lien}</a>'
    )
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setOpenExternalLinks(True)
    lbl.setStyleSheet(
        f"color:{GUIDE_ENCART_FG}; font-size:11px; background:{GUIDE_ENCART_BG};"
        f" border:1px solid {GUIDE_ENCART_BORDER}; border-radius:5px;"
        f" padding:5px 10px;"
    )
    return lbl


# === RAPPORTS DE DIAGNOSTIC ===

SUPPORT_EMAIL = "nicolas@mystrow.fr"

# Les clients mail tronquent les URL mailto trop longues (et Outlook refuse
# carrément au-delà de ~2000 caractères). On coupe le rapport et on invite à
# coller la version complète, déjà placée dans le presse-papiers.
_MAILTO_BODY_MAX = 1500


def copy_report(text):
    """Place un rapport dans le presse-papiers. Retourne True si non vide."""
    if not text or not text.strip():
        return False
    QApplication.clipboard().setText(text)
    return True


def send_report_email(parent, subject, report, intro=""):
    """Ouvre le client mail de l'utilisateur avec le rapport pré-rempli.

    Le rapport est TOUJOURS copié dans le presse-papiers d'abord : si le client
    mail tronque le corps du message (ou ne s'ouvre pas du tout), l'utilisateur
    a de quoi coller le rapport complet à la main.
    """
    import urllib.parse
    from PySide6.QtGui import QDesktopServices

    report = (report or "").strip()
    copy_report(report)

    body = report
    truncated = len(body) > _MAILTO_BODY_MAX
    if truncated:
        body = body[:_MAILTO_BODY_MAX] + "\n\n[…rapport tronqué — le rapport complet est dans votre presse-papiers, faites Coller ici…]"

    head = intro or "Bonjour,\n\nVoici le rapport de diagnostic généré par MyStrow."
    full = f"{head}\n\nMyStrow {VERSION} — {sys.platform}\n\n--- RAPPORT ---\n{body}\n"

    url = QUrl("mailto:{}?subject={}&body={}".format(
        SUPPORT_EMAIL,
        urllib.parse.quote(f"[MyStrow {VERSION}] {subject}"),
        urllib.parse.quote(full),
    ))
    ok = QDesktopServices.openUrl(url)
    if not ok:
        QMessageBox.information(
            parent, tr("core_send_report"),
            tr("core_mail_failed", mail=SUPPORT_EMAIL))
    elif truncated:
        QMessageBox.information(
            parent, tr("core_send_report"),
            tr("core_report_shortened"))
    return ok
