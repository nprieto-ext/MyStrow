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

# === FILTRE FICHIERS MEDIA ===
MEDIA_EXTENSIONS_FILTER = "Medias (*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma *.aiff *.mp4 *.mov *.avi *.mkv *.wmv *.flv *.webm *.m4v *.mpg *.mpeg *.png *.jpg *.jpeg *.gif *.bmp *.svg *.webp *.tiff)"

# === CONFIGURATION GLOBALE ===
APP_NAME = "MyStrow"
VERSION = "3.1.78"

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
    if ext in [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".aiff"]:
        return "audio"
    if ext in [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"]:
        return "video"
    if ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tiff"]:
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

    Règle d'appariement, dans l'ordre : adresse DMX (unique par fixture, donc
    insensible aux renommages), puis nom — distribué séquentiellement, sinon
    deux lyres homonymes recevraient toutes les deux le premier état —, puis
    rang dans la liste. Une lyre sans correspondance est absente du résultat :
    à l'appelant de lui laisser la position qu'elle a déjà.

    Source unique pour le rappel manuel d'une position ET pour le centre d'un
    effet Pan/Tilt : un cercle doit tourner autour du point où le rappel aurait
    posé la lyre, pas ailleurs.
    """
    out = {}
    etats = (preset or {}).get("projectors", []) or []
    par_addr = {str(s["start_address"]): s for s in etats if s.get("start_address")}
    par_nom = {}
    for s in etats:
        nom = s.get("name")
        if nom:
            par_nom.setdefault(nom, []).append(s)
    curseur = {}

    for i, p in enumerate(lyres):
        etat = None
        addr = str(getattr(p, 'start_address', '') or '')
        if addr:
            etat = par_addr.get(addr)
        if etat is None and getattr(p, 'name', ''):
            entrees = par_nom.get(p.name, [])
            k = curseur.get(p.name, 0)
            if k < len(entrees):
                etat = entrees[k]
                curseur[p.name] = k + 1
        if etat is None and i < len(etats):
            etat = etats[i]
        if etat is not None:
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
            parent, "Envoyer le rapport",
            f"Impossible d'ouvrir votre logiciel de messagerie.\n\n"
            f"Le rapport a été copié dans le presse-papiers : collez-le dans un "
            f"mail à {SUPPORT_EMAIL}.")
    elif truncated:
        QMessageBox.information(
            parent, "Envoyer le rapport",
            "Votre mail est ouvert. Le rapport étant long, il a été raccourci "
            "dans le message — la version complète est dans le presse-papiers "
            "(Coller pour la joindre).")
    return ok
