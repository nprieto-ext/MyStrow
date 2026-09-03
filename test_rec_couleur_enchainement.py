# -*- coding: utf-8 -*-
"""REC Lumiere : enchainer les touches couleur sans bouger la souris.

Contexte (02/09/2026) : on survole une piste, on tape R -> un bloc rouge. Le
geste naturel est d'enchainer B juste apres. Mais la souris est alors DANS le
bloc rouge qu'on vient de poser, et le garde-fou anti-empilement rendait False :
il fallait deplacer la souris a chaque couleur.

La regle est SANS ETAT : survoler un bloc pose la couleur au bout de lui (et au
bout de ses voisins colles). Rien n'est memorise entre deux touches, donc un
undo, un deplacement de bloc ou une piste reconstruite n'invalident rien.

On teste cette regle, pas le survol : `_piste_couleur_survolee` est remplace par
une position posee a la main, le reste est le code reel de l'editeur sur une
vraie LightTrack.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from light_timeline import LightTrack
from timeline_editor import LightTimelineEditor

ECHECS = []


def check(nom, cond):
    print(("  OK   " if cond else "  ECHEC") + "  " + nom)
    if not cond:
        ECHECS.append(nom)


class FauxMW:
    COLOR_SHORTCUTS = {
        Qt.Key_R: QColor(255, 0, 0),
        Qt.Key_G: QColor(0, 255, 0),
        Qt.Key_B: QColor(0, 0, 255),
        Qt.Key_C: QColor(0, 255, 255),
    }


class FauxSpin:
    def __init__(self, sec):
        self.sec = sec

    def value(self):
        return self.sec


class FauxEditeur:
    """L'editeur reduit a ce dont la pose de bloc a besoin."""

    _COULEURS_RESERVEES = LightTimelineEditor._COULEURS_RESERVEES
    _editable           = staticmethod(LightTimelineEditor._editable)
    _fin_de_suite       = LightTimelineEditor._fin_de_suite
    _poser_bloc_couleur = LightTimelineEditor._poser_bloc_couleur

    def __init__(self, duree_totale=120000, bloc_sec=5):
        self.main_window = FauxMW()
        self._default_block_dur_spin = FauxSpin(bloc_sec)
        self.piste = LightTrack("A", duree_totale, self)
        self.tracks = [self.piste]
        self.souris_x = 145          # x local ; 145 px = etiquette de piste
        self.sauvegardes = 0

    # Survol simule : c'est le test qui decide de la position, pas le curseur.
    def _piste_couleur_survolee(self):
        return self.piste, self.souris_x

    def viser_ms(self, ms):
        self.souris_x = 145 + ms * self.piste.pixels_per_ms

    def save_state(self):
        self.sauvegardes += 1

    def taper(self, key):
        return self._poser_bloc_couleur(key)

    def blocs(self):
        return sorted(self.piste.clips, key=lambda c: c.start_time)

    def chevauchement(self):
        b = self.blocs()
        return any(b[i].start_time + b[i].duration > b[i + 1].start_time + 1
                   for i in range(len(b) - 1))


print("\n=== Enchainement des touches couleur ===")

ed = FauxEditeur()
ed.viser_ms(10000)
check("R pose un bloc a l'endroit vise", ed.taper(Qt.Key_R) and
      abs(ed.blocs()[0].start_time - 10000) < 1)

check("B sans bouger la souris pose un 2e bloc", ed.taper(Qt.Key_B))
check("...colle au bout du premier", len(ed.blocs()) == 2 and
      abs(ed.blocs()[1].start_time - 15000) < 1)
check("...et de la bonne couleur", ed.blocs()[1].color.name() == "#0000ff")

check("G enchaine un 3e bloc", ed.taper(Qt.Key_G) and len(ed.blocs()) == 3 and
      abs(ed.blocs()[2].start_time - 20000) < 1)
check("R enchaine un 4e bloc de la meme couleur", ed.taper(Qt.Key_R) and
      abs(ed.blocs()[3].start_time - 25000) < 1)
check("chaque bloc est annulable", ed.sauvegardes == 4)
check("aucun chevauchement", not ed.chevauchement())

# La souris peut bouger n'importe ou dans la file : c'est le bloc survole qui
# donne le point de depart, et la marche saute les blocs colles.
ed.viser_ms(21000)
check("bouger dans la file enchaine toujours au bout", ed.taper(Qt.Key_B) and
      abs(ed.blocs()[4].start_time - 30000) < 1)

# Sur du vide : le bloc revient sous la souris.
ed.viser_ms(60000)
check("sur du vide, le bloc revient sous la souris", ed.taper(Qt.Key_R) and
      abs(ed.blocs()[5].start_time - 60000) < 1)


print("\n=== Aucun etat retenu entre deux touches ===")

# Un bloc pose bien avant enchaine pareil : c'est le survol qui decide.
ed2 = FauxEditeur()
ed2.viser_ms(30000)
ed2.taper(Qt.Key_R)
ed2.viser_ms(80000)
ed2.taper(Qt.Key_G)
ed2.viser_ms(32000)          # retour sur le tout premier bloc
check("survoler un bloc ancien enchaine au bout de lui",
      ed2.taper(Qt.Key_B) and
      any(abs(c.start_time - 35000) < 1 for c in ed2.piste.clips))
check("...sans empiler", not ed2.chevauchement())

# Undo du dernier maillon : rien a invalider, on repart du bloc survole.
ed3 = FauxEditeur()
ed3.viser_ms(10000)
ed3.taper(Qt.Key_R)
ed3.taper(Qt.Key_B)
ed3.piste.clips.remove(ed3.blocs()[1])       # comme un undo
check("apres un undo, la suite repart du bloc restant",
      ed3.taper(Qt.Key_G) and len(ed3.piste.clips) == 2 and
      abs(ed3.blocs()[1].start_time - 15000) < 1)

# Bout de la timeline : pas de bloc de duree nulle.
ed4 = FauxEditeur(duree_totale=12000)
ed4.viser_ms(1000)
ed4.taper(Qt.Key_R)                          # 1000 -> 6000
ed4.taper(Qt.Key_B)                          # 6000 -> 11000
check("le dernier bloc est rogne par la fin de timeline",
      len(ed4.blocs()) == 2 and ed4.blocs()[1].duration <= 5000)
ed4.taper(Qt.Key_G)                          # il ne reste que 1 s
plein = len(ed4.piste.clips)
check("aucun bloc de duree nulle",
      all(c.duration > 0 for c in ed4.piste.clips))
check("plus de place : la touche retombe sur les autres raccourcis",
      ed4.taper(Qt.Key_R) is False and len(ed4.piste.clips) == plein)

# Les touches reservees restent les modes de l'editeur.
ed5 = FauxEditeur()
ed5.viser_ms(5000)
check("C reste le mode Coupe", ed5.taper(Qt.Key_C) is False and
      not ed5.piste.clips)

print("\n%s" % ("TOUT PASSE" if not ECHECS else "ECHECS : %s" % ECHECS))
sys.exit(1 if ECHECS else 0)
