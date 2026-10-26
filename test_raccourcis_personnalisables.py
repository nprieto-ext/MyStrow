"""Raccourcis clavier personnalisables : registre, presets, dialogue, répartition.

Le fichier de config est redirigé vers un dossier temporaire : le test ne
touche jamais ~/.mystrow_shortcuts.json de l'utilisateur.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog, QMainWindow

import shortcuts

app = QApplication.instance() or QApplication(sys.argv)
_TMP = Path(tempfile.mkdtemp()) / "shortcuts.json"
shortcuts._FILE = _TMP


def test_defauts_et_ecarts_seuls():
    k = shortcuts.load()
    assert k["save_show"] == "Ctrl+S" and k["fx_1"] == "F5" and k["fx_8"] == "F12"
    k["save_show"] = "ctrl+alt+s"
    k["strobe"] = ""
    shortcuts.save(k)
    import json
    assert json.loads(_TMP.read_text())["keys"] == {"save_show": "Ctrl+Alt+S", "strobe": ""}
    k2 = shortcuts.load()
    assert k2["save_show"] == "Ctrl+Alt+S" and k2["strobe"] == "" and k2["color_red"] == "R"
    shortcuts.save(dict(shortcuts.DEFAULTS))
    assert shortcuts.load() == shortcuts.DEFAULTS


def test_conflits():
    k = dict(shortcuts.DEFAULTS)
    assert shortcuts.conflicts(k) == {}
    k["strobe"] = "R"
    c = shortcuts.conflicts(k)
    assert c == {"strobe": "color_red", "color_red": "strobe"}
    k["strobe"] = "Ctrl+A"
    assert shortcuts.conflicts(k) == {"strobe": "Ctrl+A"}
    k["strobe"] = ""
    k["color_red"] = ""
    assert shortcuts.conflicts(k) == {}


def test_presets():
    k = dict(shortcuts.DEFAULTS)
    k["color_red"] = "1"
    shortcuts.save_preset("Concert", k)
    assert "Concert" in shortcuts.presets()
    assert shortcuts.preset_keys("Concert")["color_red"] == "1"
    assert shortcuts.preset_keys("Concert")["color_blue"] == "B"
    shortcuts.delete_preset("Concert")
    assert shortcuts.presets() == {}


def test_dialogue():
    from shortcuts_dialog import ShortcutsDialog
    d = ShortcutsDialog(None, dict(shortcuts.DEFAULTS))
    assert d._ok.isEnabled()
    d._set_one("strobe", "R")
    assert not d._ok.isEnabled() and "2" in d._status.text()
    d._set_one("strobe", "Shift+S")
    assert d._ok.isEnabled() and d.keys()["strobe"] == "Shift+S"
    # Preset : enregistrer puis recharger depuis la liste
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Bar", True))
    d._save_preset()
    assert shortcuts.preset_keys("Bar")["strobe"] == "Shift+S"
    d._set_all(dict(shortcuts.DEFAULTS))
    assert d.keys()["strobe"] == "S"
    d._presets.setCurrentIndex(d._presets.findData("Bar"))
    d._load_preset()
    assert d.keys()["strobe"] == "Shift+S"
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    d._delete_preset()
    assert "Bar" not in shortcuts.presets()
    d.close()


def test_repartition_des_touches():
    import main_window as mw

    # Sous-classe sans le __init__ de MainWindow : on garde ses vraies
    # méthodes clavier (super() compris) sans construire toute la fenêtre.
    class Faux(mw.MainWindow):
        def __init__(self, keys):
            QMainWindow.__init__(self)
            self.log = []
            self.go_mode = False
            self.cartouches = [0, 1, 2, 3]
            self.effect_buttons = list(range(8))
            self.seq = type("S", (), {"live_mode_active": False})()
            self._shortcut_keys = keys
            self._apply_shortcuts()
        toggle_play = lambda s: s.log.append("play")
        next_media = lambda s: s.log.append("next")
        previous_media = lambda s: s.log.append("prev")
        _next_bank_page = lambda s: s.log.append("page+")
        _prev_bank_page = lambda s: s.log.append("page-")
        on_cartouche_clicked = lambda s, i: s.log.append(f"cart{i}")
        _on_effect_press = lambda s, i: s.log.append(f"fx{i}")
        _on_effect_release = lambda s, i: s.log.append(f"fx{i}-off")
        _flash_begin = lambda s: s.log.append("flash")
        _flash_end = lambda s: s.log.append("flash-off")
        _apply_strobe_shortcut = lambda s: s.log.append("strobe")
        _apply_color_shortcut = lambda s, c: s.log.append(c.name())

    w = Faux(dict(shortcuts.DEFAULTS))
    for k, mod in ((Qt.Key_Return, Qt.NoModifier), (Qt.Key_Enter, Qt.KeypadModifier),
                   (Qt.Key_PageDown, Qt.NoModifier), (Qt.Key_PageDown, Qt.ControlModifier),
                   (Qt.Key_F2, Qt.NoModifier), (Qt.Key_F7, Qt.NoModifier),
                   (Qt.Key_F, Qt.NoModifier), (Qt.Key_S, Qt.NoModifier),
                   (Qt.Key_R, Qt.NoModifier), (Qt.Key_R, Qt.ControlModifier)):
        QTest.keyClick(w, k, mod)
    assert w.log == ["play", "play", "next", "page+", "cart1", "fx2", "fx2-off",
                     "flash", "flash-off", "strobe", "#ff0000"], w.log
    assert w.COLOR_SHORTCUTS[Qt.Key_R] == QColor(255, 0, 0)

    # Touches personnalisées : R devient strobe, le rouge passe sur Shift+R,
    # le flash sur la touche 0. Les anciennes touches ne font plus rien.
    k = dict(shortcuts.DEFAULTS)
    k.update(strobe="R", color_red="Shift+R", flash="0")
    w2 = Faux(k)
    QTest.keyClick(w2, Qt.Key_R)
    QTest.keyClick(w2, Qt.Key_R, Qt.ShiftModifier)
    QTest.keyClick(w2, Qt.Key_S)
    QTest.keyPress(w2, Qt.Key_0)
    QTest.keyRelease(w2, Qt.Key_0)
    assert w2.log == ["strobe", "#ff0000", "flash", "flash-off"], w2.log
    assert Qt.Key_R not in w2.COLOR_SHORTCUTS      # Shift+R : pas une touche simple
    # Flèches hors mode GO : rendues au widget
    QTest.keyClick(w2, Qt.Key_Right)
    assert w2.log[-1] == "flash-off"


if __name__ == "__main__":
    for nom, f in list(globals().items()):
        if nom.startswith("test_"):
            f(); print("OK", nom)
