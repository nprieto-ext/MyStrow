# -*- coding: utf-8 -*-
"""REC MEM : une capture sans niveau est une SURCOUCHE, pas une erreur.

Historique : le 02/09/2026, mem 2.1 de Niko contenait `strobe_speed 58` sur
ses 16 lyres et `level 0` PARTOUT. Rappelee d'un pad, elle imposait tout son
faisceau et eteignait le plateau : on avait donc ajoute une alerte au REC.

18/09/2026 : « je ne peux toujours pas enregistrer juste un strobe », puis
« l'idee c'est que je puisse enregistrer n'importe quel parametre ». Une
memoire n'impose plus que ce qu'elle porte hors repos (cf.
test_memoire_parametres_seuls.py) : plus d'alerte, juste une ligne au journal.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow\App")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

import main_window as MW


class FauxMW:
    _note_snapshot_sans_niveau = MW.MainWindow._note_snapshot_sans_niveau

    def __init__(self):
        self.logs = []

    def _log_message(self, text, level="info"):
        self.logs.append((level, text))


def cue(*etats):
    return {"projectors": list(etats)}


def etat(**kw):
    base = {"level": 0, "base_color": "#000000", "strobe_speed": 0,
            "pan": 32768, "tilt": 32768, "shutter": 255, "channel_extras": {}}
    base.update(kw)
    return base


import PySide6.QtWidgets as _QtW
_vrai_box = _QtW.QMessageBox


class InterditBox:
    def __init__(self, *a, **k):
        raise AssertionError("le REC ne doit plus poser de question")


_QtW.QMessageBox = InterditBox
try:
    mw = FauxMW()
    # Look allume : rien a dire.
    mw._note_snapshot_sans_niveau(cue(etat(level=80, base_color="#fff"), etat()))
    # Noir complet : un noir se memorise, rien a dire.
    mw._note_snapshot_sans_niveau(cue(etat(), etat()))
    mw._note_snapshot_sans_niveau(cue())
    assert not mw.logs, mw.logs

    # Juste un strobe / un gobo / de l'UV / une position / un canal brut.
    for reglage in (dict(strobe_speed=58), dict(gobo=77), dict(uv=200),
                    dict(pan=10000), dict(channel_extras={5: 210})):
        mw.logs.clear()
        mw._note_snapshot_sans_niveau(cue(etat(**reglage), etat()))
        assert mw.logs and mw.logs[-1][0] == "rec", f"pas de note pour {reglage}"

    # Une note ne doit JAMAIS casser un REC.
    mw._note_snapshot_sans_niveau({"projectors": "casse"})
    mw._note_snapshot_sans_niveau(None)
finally:
    _QtW.QMessageBox = _vrai_box

print("OK - le REC enregistre une capture sans niveau sans poser de question.")
