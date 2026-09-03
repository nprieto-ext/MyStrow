# -*- coding: utf-8 -*-
"""REC MEM : prevenir quand la capture ne porte que des reglages, rien d'allume.

Contexte (02/09/2026) : mem 2.1 de Niko contenait `strobe_speed 58` sur ses
16 lyres et `level 0` PARTOUT. `_build_snapshot` capture `level` tel quel :
regler le strobe sur un rig eteint donne donc une memoire qui, rappelee d'un
pad, repose noir sur tout le plateau (« mes projecteurs s'eteignent ») au lieu
de faire ce qu'on croyait y avoir mis.

On teste le PREDICAT, pas la fenetre : les deux chemins silencieux doivent
laisser passer, le troisieme doit ouvrir un dialogue.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

import main_window as MW


class FauxMW:
    """Emprunte la methode a MainWindow sans instancier la fenetre."""
    _SNAP_BEAM_ONLY = MW.MainWindow._SNAP_BEAM_ONLY
    _confirm_dark_snapshot = MW.MainWindow._confirm_dark_snapshot


def cue(*etats):
    return {"projectors": list(etats)}


def etat(**kw):
    base = {"level": 0, "base_color": "#000000", "strobe_speed": 0,
            "channel_extras": {}}
    base.update(kw)
    return base


mw = FauxMW()
_dialogues = []


class FauxBox:
    """QMessageBox de remplacement : compte les ouvertures, repond ce qu'on veut."""
    AcceptRole = 0
    RejectRole = 1
    _reponse = "ok"

    def __init__(self, parent=None):
        _dialogues.append(self)
        self._ok = object()
        self._cancel = object()
        self._n = 0

    def setWindowTitle(self, *_): pass
    def setText(self, *_): pass
    def setInformativeText(self, *_): pass
    def setStyleSheet(self, *_): pass

    def addButton(self, _label, role):
        return self._ok if role == self.AcceptRole else self._cancel

    def exec(self): pass

    def clickedButton(self):
        return self._ok if FauxBox._reponse == "ok" else self._cancel


import PySide6.QtWidgets as _QtW
_vrai_box = _QtW.QMessageBox
_QtW.QMessageBox = FauxBox

try:
    # ── 1) Au moins une fixture allumee : aucun avertissement ────────────────
    assert mw._confirm_dark_snapshot(
        cue(etat(level=80, base_color="#ffffff"), etat()), 1, 0) is True
    assert not _dialogues, "une capture qui allume ne doit rien demander"

    # ── 2) Capture entierement vide : c'est un NOIR, geste legitime ──────────
    assert mw._confirm_dark_snapshot(cue(etat(), etat()), 1, 0) is True
    assert not _dialogues, "memoriser un noir ne doit rien demander"
    assert mw._confirm_dark_snapshot(cue(), 1, 0) is True

    # `shutter` au repos vaut 255 : il ne doit pas compter comme un reglage.
    assert mw._confirm_dark_snapshot(cue(etat(shutter=255)), 1, 0) is True
    assert not _dialogues, "le shutter ouvert n'est pas un reglage"

    # ── 3) Le cas mem 2.1 : du strobe, rien d'allume -> on previent ──────────
    FauxBox._reponse = "ok"
    assert mw._confirm_dark_snapshot(
        cue(etat(strobe_speed=58), etat(strobe_speed=58)), 1, 0) is True
    assert len(_dialogues) == 1, "un strobe sans niveau doit alerter"

    # Annuler doit vraiment annuler le REC.
    FauxBox._reponse = "cancel"
    assert mw._confirm_dark_snapshot(cue(etat(strobe_speed=58)), 1, 0) is False
    assert len(_dialogues) == 2

    # Meme regle pour un gobo, un canal special et un canal brut.
    FauxBox._reponse = "ok"
    for reglage in (dict(gobo=77), dict(uv=200), dict(prism=180),
                    dict(channel_extras={5: 210})):
        _dialogues.clear()
        assert mw._confirm_dark_snapshot(cue(etat(**reglage)), 1, 0) is True
        assert len(_dialogues) == 1, f"pas d'alerte pour {reglage}"

    # ── 4) Un garde-fou ne doit JAMAIS bloquer un REC ────────────────────────
    _dialogues.clear()
    assert mw._confirm_dark_snapshot({"projectors": "casse"}, 1, 0) is True
    assert mw._confirm_dark_snapshot(None, 1, 0) is True
finally:
    _QtW.QMessageBox = _vrai_box

print("OK - le REC previent quand la capture ne porte que des reglages.")
