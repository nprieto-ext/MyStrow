# -*- coding: utf-8 -*-
"""Le « + » (et le « x ») des pistes Effet / Sequence, dans l'en-tete de piste.

Contexte (02/09/2026) : la release 3.1.89 a supprime les deux lignes de boutons
« + Piste Effet » / « + Piste Sequence » posees sous les pistes (elles
meublaient la timeline en permanence). Les actions ont bien survecu au menu
Edition et au clic droit, mais plus personne ne les trouvait — « ya plus les
multi ligne » — et le « x » de suppression d'une piste ajoutee, lui, n'a ete
remplace par RIEN : on pouvait empiler des pistes sans jamais en enlever.

On teste la geometrie et le comportement, pas le pixel : qui porte quelle
icone, ou tape le clic, ce que fait l'action, et le garde-fou sur une piste
pleine.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import light_timeline as LT
from light_timeline import LightTrack

ECHECS = []


def check(nom, cond):
    print(("  OK   " if cond else "  ECHEC") + "  " + nom)
    if not cond:
        ECHECS.append(nom)


class FauxEditeur:
    """Assez d'editeur pour une piste : les deux familles et leurs actions."""

    _MAX_EFFECT_TRACKS = 8
    _MAX_SEQUENCE_TRACKS = 8
    tracks_scroll = None

    def __init__(self):
        self.tracks = []
        self._effect_tracks = []
        self._sequence_tracks = []
        self.retirees = []

    def _piste(self, nom, effet):
        t = LightTrack(nom, 60000, self, "#cc44ff" if effet else "#aa77ff")
        t.is_effect_track = effet
        t.is_sequence_track = not effet
        t.resize(900, 50)
        self.tracks.append(t)
        (self._effect_tracks if effet else self._sequence_tracks).append(t)
        return t

    def _add_effect_track(self):
        self._piste("Effet %d" % (len(self._effect_tracks) + 1), True)

    def _add_sequence_track(self):
        self._piste("Sequence %d" % (len(self._sequence_tracks) + 1), False)

    def _remove_effect_track(self, t):
        if self._effect_tracks.index(t) == 0:
            return
        self._effect_tracks.remove(t)
        self.tracks.remove(t)
        self.retirees.append(t.name)

    def _remove_sequence_track(self, t):
        if self._sequence_tracks.index(t) == 0:
            return
        self._sequence_tracks.remove(t)
        self.tracks.remove(t)
        self.retirees.append(t.name)


ed = FauxEditeur()
eff1 = ed._piste("Effet", True)
seq1 = ed._piste("Sequence", False)

# ── 1. Qui porte quelle icone ──────────────────────────────────────────────
print("\n1. Icones de l'en-tete")
check("la piste Effet seule porte un +", eff1._header_actions() == ['add'])
check("la piste Sequence seule aussi", seq1._header_actions() == ['add'])

pos = LightTrack("Position", 60000, ed, "#2255ee")
pos.is_position_track = True
pos.resize(900, 50)
check("une piste Position n'en porte pas (elle est unique par conception)",
      pos._header_actions() == [])

ed._add_effect_track()
eff2 = ed._effect_tracks[-1]
check("apres ajout, le + descend sur la nouvelle derniere piste",
      eff1._header_actions() == [] and eff2._header_actions() == ['add', 'del'])
check("la 1re piste Effet ne porte JAMAIS de x", 'del' not in eff1._header_actions())

for _ in range(6):
    ed._add_effect_track()
check("8 pistes Effet = plafond atteint", len(ed._effect_tracks) == 8)
check("au plafond, le + disparait",
      ed._effect_tracks[-1]._header_actions() == ['del'])


# ── 2. Le clic tape dans la bonne case ─────────────────────────────────────
print("\n2. Zones de clic")
r = seq1._header_rects(0)
check("la case + est reservee dans l'en-tete", 'add' in r)
check("elle tient dans la colonne gelee de 145 px",
      0 < r['add'].left() and r['add'].right() < LightTrack.HEADER_W)
check("le clic sur son centre est reconnu",
      seq1.header_hit(r['add'].center().x(), r['add'].center().y()) == 'add')
check("le cadenas reste atteignable",
      seq1.header_hit(r['lock'].center().x(), r['lock'].center().y()) == 'lock')
check("le milieu du nom ne declenche rien",
      seq1.header_hit(r['lock'].right() + 20, 25) is None)
check("hors de l'en-tete non plus", seq1.header_hit(400, 25) is None)

seq1.resize(900, 12)
check("ligne ecrasee : plus aucune icone (une tache de 3 px ne se vise pas)",
      seq1.header_hit(r['add'].center().x(), 6) is None)
seq1.resize(900, 50)


# ── 3. Les actions ─────────────────────────────────────────────────────────
print("\n3. Actions")
n0 = len(ed._sequence_tracks)
seq1.run_header_action('add')
check("le + ajoute une piste Sequence", len(ed._sequence_tracks) == n0 + 1)

seq2 = ed._sequence_tracks[-1]
check("le x d'une piste VIDE ne demande rien et retire la piste",
      seq2.run_header_action('del') is True and len(ed._sequence_tracks) == n0)

# Piste pleine : la confirmation est obligatoire, et un refus ne retire rien.
seq1.run_header_action('add')
seq3 = ed._sequence_tracks[-1]
seq3.clips = [object(), object()]

_demandes = []


class FauxQuestion:
    Yes = 1
    Cancel = 2
    _reponse = 2

    @staticmethod
    def question(*a, **k):
        _demandes.append(a[2] if len(a) > 2 else "")
        return FauxQuestion._reponse


_vrai = LT.QMessageBox
LT.QMessageBox = FauxQuestion
try:
    refus = seq3.run_header_action('del')
    FauxQuestion._reponse = FauxQuestion.Yes
    ok = seq3.run_header_action('del')
finally:
    LT.QMessageBox = _vrai

check("une piste PLEINE demande confirmation", len(_demandes) == 2)
check("annuler ne retire rien", refus is False)
check("confirmer retire la piste", ok is True and seq3.name not in
      [t.name for t in ed._sequence_tracks])
check("le nombre de blocs est annonce dans la question",
      "2" in _demandes[0])


# ── 4. Le rendu ne plante pas et laisse la place au nom ────────────────────
print("\n4. Rendu")
from PySide6.QtGui import QPixmap, QPainter

pm = QPixmap(900, 50)
p = QPainter(pm)
try:
    ed._effect_tracks[-1]._paint_header(p, 0)
    ok_paint = True
except Exception as e:  # noqa: BLE001
    ok_paint = False
    print("   ", e)
p.end()
check("l'en-tete d'une piste portant + et x se peint", ok_paint)

print("\n" + ("TOUT PASSE" if not ECHECS else "ECHECS: " + ", ".join(ECHECS)))
sys.exit(1 if ECHECS else 0)
