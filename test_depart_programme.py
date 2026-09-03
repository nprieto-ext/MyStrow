# -*- coding: utf-8 -*-
"""Depart programme (v1) : lancer le show a une heure precise, chaque jour.

On teste la DECISION, pas le pixel : quand le tick d'horloge doit lancer la
playlist, quand il doit s'abstenir, et ce que le show emporte dans son .tui.

Deux regles voulues, et verifiees ici :
  - le depart vaut pour CHAQUE JOUR, il n'y a pas de mode « une seule fois » ;
  - une occurrence manquee est PERDUE (pas de rattrapage) — un show ne part
    pas avec dix minutes de retard sur son horaire.

L'heure n'est jamais figee : chaque cas pose `schedule_time` PAR RAPPORT a
l'heure reelle (maintenant - 3 min, maintenant + 2 min...). C'est plus fidele
que de patcher l'horloge, et ca verifie au passage que la comparaison se fait
bien sur l'horloge murale.

La fausse fenetre emprunte les methodes de MainWindow sans l'instancier : elle
herite de QObject parce que `_arm_schedule` cree un QTimer parente.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QObject, QTime
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer

app = QApplication.instance() or QApplication([])

from main_window import MainWindow

ECHECS = []


def check(nom, cond):
    print(("  OK   " if cond else "  ECHEC") + "  " + nom)
    if not cond:
        ECHECS.append(nom)


def heure_decalee(minutes: int) -> str:
    """"HH:MM" a `minutes` de maintenant (negatif = dans le passe)."""
    return QTime.currentTime().addSecs(minutes * 60).toString("HH:mm")


class FauxTable:
    def __init__(self, n):
        self._n = n

    def rowCount(self):
        return self._n


class FauxSeq:
    def __init__(self, lignes=3):
        self.table = FauxTable(lignes)
        self.tempo_running = False
        self.is_dirty = False
        self.lancements = []

    def play_row(self, row):
        self.lancements.append(row)


class FauxPlayer:
    def __init__(self, etat=QMediaPlayer.StoppedState):
        self._etat = etat

    def playbackState(self):
        return self._etat


class FauxWin(QObject):
    """Le strict necessaire pour faire tourner le planificateur."""

    _SCHEDULE_WINDOW_S = MainWindow._SCHEDULE_WINDOW_S

    _schedule_target_today        = MainWindow._schedule_target_today
    _schedule_state               = MainWindow._schedule_state
    _arm_schedule                 = MainWindow._arm_schedule
    _update_schedule_action_label = MainWindow._update_schedule_action_label
    _schedule_tick                = MainWindow._schedule_tick
    _do_schedule_tick             = MainWindow._do_schedule_tick
    _show_is_running              = MainWindow._show_is_running
    _schedule_fire                = MainWindow._schedule_fire
    _apply_show_schedule          = MainWindow._apply_show_schedule

    def __init__(self, lignes=3, etat_player=QMediaPlayer.StoppedState):
        super().__init__()
        self.schedule_enabled = True
        self.schedule_time    = "20:00"
        self._schedule_timer      = None
        self._schedule_fired_date = None
        self.seq    = FauxSeq(lignes)
        self.player = FauxPlayer(etat_player)
        self.journal = []

    def _log_message(self, text, level="info"):
        self.journal.append((level, text))

    @property
    def lancements(self):
        return self.seq.lancements

    def niveaux(self):
        return [lv for lv, _ in self.journal]


print("\n=== Depart programme ===\n")

# Garde : a moins de 10 min de minuit, « maintenant - 3 min » bascule la veille
# et les cas de retard n'ont plus de sens.
_now = QTime.currentTime()
if _now.hour() == 0 and _now.minute() < 10:
    print("  (test ignore : trop pres de minuit pour poser des heures relatives)")
    raise SystemExit(0)

# ── 1. Avant l'heure : on ne fait rien ─────────────────────────────────────
w = FauxWin()
w.schedule_time = heure_decalee(+2)
w._do_schedule_tick()
check("avant l'heure, le show ne part pas", w.lancements == [])
check("avant l'heure, l'occurrence n'est pas consommee",
      w._schedule_fired_date is None)

# ── 2. L'heure pile ────────────────────────────────────────────────────────
w = FauxWin()
w.schedule_time = QTime.currentTime().toString("HH:mm")
w._do_schedule_tick()
check("a l'heure, le show part depuis le debut", w.lancements == [0])
check("a l'heure, le journal marque le depart",
      any(lv == "go" for lv in w.niveaux()))

# ── 3. Le tick suivant ne relance pas ──────────────────────────────────────
w._do_schedule_tick()
w._do_schedule_tick()
check("un seul depart par jour, pas un par tick", w.lancements == [0])

# ── 4. Le depart reste arme pour les jours suivants ────────────────────────
# Pas de mode « une seule fois » : une salve ne doit rien desarmer.
w = FauxWin()
w.schedule_time = QTime.currentTime().toString("HH:mm")
w._arm_schedule()
w._do_schedule_tick()
check("depart quotidien : le show part", w.lancements == [0])
check("apres la salve, le depart reste actif", w.schedule_enabled is True)
check("apres la salve, le timer tourne toujours",
      w._schedule_timer is not None and w._schedule_timer.isActive())
w._schedule_fired_date = None          # lendemain
w._do_schedule_tick()
check("le lendemain, le show repart", w.lancements == [0, 0])

# ── 5. Aucun rattrapage : un retard de 3 min est perdu ────────────────────
w = FauxWin()
w.schedule_time = heure_decalee(-3)
w._do_schedule_tick()
check("retard de 3 min : le show ne part pas", w.lancements == [])
check("retard de 3 min : l'occurrence du jour est consommee",
      w._schedule_fired_date is not None)
check("retard de 3 min : le journal previent",
      any(lv == "warn" for lv in w.niveaux()))
w._do_schedule_tick()
check("retard de 3 min : aucun depart au tick suivant", w.lancements == [])

# ── 6. Idem au CHARGEMENT d'un show en retard ──────────────────────────────
w = FauxWin()
w._apply_show_schedule({"schedule": {"enabled": True, "time": heure_decalee(-3)}})
w._do_schedule_tick()
check("show ouvert en retard : le show ne part pas", w.lancements == [])

# ── 7. Une lecture en cours n'est jamais coupee ────────────────────────────
w = FauxWin(etat_player=QMediaPlayer.PlayingState)
w.schedule_time = QTime.currentTime().toString("HH:mm")
w._do_schedule_tick()
check("media deja en cours : pas d'interruption", w.lancements == [])
check("media deja en cours : le journal l'explique",
      any("cours" in t or "running" in t for _, t in w.journal))

w = FauxWin()
w.seq.tempo_running = True
w.schedule_time = QTime.currentTime().toString("HH:mm")
w._do_schedule_tick()
check("TEMPO en cours : pas d'interruption", w.lancements == [])

# ── 8. Playlist vide : on previent, on ne plante pas ───────────────────────
w = FauxWin(lignes=0)
w.schedule_time = QTime.currentTime().toString("HH:mm")
w._do_schedule_tick()
check("playlist vide : aucun lancement", w.lancements == [])
check("playlist vide : le journal previent", any(lv == "warn" for lv in w.niveaux()))

# ── 9. Desactive : le tick est inerte ──────────────────────────────────────
w = FauxWin()
w.schedule_enabled = False
w.schedule_time = QTime.currentTime().toString("HH:mm")
w._do_schedule_tick()
check("desactive : aucun lancement", w.lancements == [])

# ── 10. Heure illisible : pas de crash, pas de depart ──────────────────────
w = FauxWin()
w.schedule_time = "n'importe quoi"
w._schedule_tick()            # version protegee
check("heure illisible : aucun lancement", w.lancements == [])

# ── 11. Regler l'heure a la main ne lance pas le show dans la seconde ──────
# L'heure du jour est deja passee de quelques secondes : sans `consume_today`,
# elle tombe dans la fenetre anti-freeze et partirait aussitot.
w = FauxWin()
w.schedule_time = QTime.currentTime().toString("HH:mm")
w._arm_schedule(consume_today=True)      # ce que fait la fenetre de reglage
w._do_schedule_tick()
check("reglage manuel d'une heure passee : pas de depart surprise",
      w.lancements == [])

# ── 12. Serialisation : deux reglages, pas plus ────────────────────────────
w = FauxWin()
w.schedule_time = "19:45"
etat = w._schedule_state()
check("l'etat serialise ne porte que l'activation et l'heure",
      etat == {"enabled": True, "time": "19:45"})

w2 = FauxWin()
w2._apply_show_schedule({"version": 8, "schedule": etat})
check("relecture : l'heure revient", w2.schedule_time == "19:45")
check("relecture : le timer est arme",
      w2._schedule_timer is not None and w2._schedule_timer.isActive())

# Un .tui ecrit avant le retrait des options porte encore daily/catchup :
# les clefs inconnues sont ignorees, pas une exception.
w2b = FauxWin()
w2b._apply_show_schedule({"version": 8, "schedule": {
    "enabled": True, "time": "18:15", "daily": False, "catchup": True}})
check("clefs d'un ancien .tui v8 ignorees sans casse",
      w2b.schedule_time == "18:15" and w2b.schedule_enabled is True)

# ── 13. Un .tui d'avant la v8 desarme, il n'herite pas du show precedent ──
w3 = FauxWin()
w3.schedule_time = "19:45"
w3._arm_schedule()
w3._apply_show_schedule({"version": 7, "sequence": []})
check("show anterieur a la v8 : le depart est desarme",
      w3.schedule_enabled is False)
check("show anterieur a la v8 : le timer est arrete",
      w3._schedule_timer is None or not w3._schedule_timer.isActive())
w3._do_schedule_tick()
check("show anterieur a la v8 : aucun lancement", w3.lancements == [])

print()
if ECHECS:
    print("ECHECS : " + str(len(ECHECS)))
    for e in ECHECS:
        print("  - " + e)
    sys.exit(1)
print("Tout est vert.")
