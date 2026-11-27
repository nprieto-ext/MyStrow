"""Blackout MAINTENU (client Chris, 26/11/2026) : le noir doit tenir même quand
un moteur (Live IA) repeint les projecteurs à chaque tick, et le rallumage doit
rendre l'état courant du moteur. Machines à effets épargnées."""
import sys, time, types
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
app = QApplication.instance() or QApplication(sys.argv)
import main_window as mw

MW = mw.MainWindow
ok = True
def check(cond, msg):
    global ok
    print(("OK  " if cond else "ÉCHEC ") + msg); ok &= bool(cond)

class P:
    def __init__(self, ftype="PAR LED"):
        self.fixture_type = ftype; self.level = 100; self.group = "A"
        self.color = QColor(255, 0, 0); self.base_color = QColor(255, 0, 0)
        self.uv = 0; self.white_boost = 0; self.amber_boost = 0; self.orange_boost = 0
        self.strobe_speed = 50; self.effect_channels = {"prism": 128}

w = types.SimpleNamespace(blackout_active=False, _bo_t0=None, _bo_from=1.0,
                          projectors=[P(), P("Machine a fumee")])
for n in ("toggle_blackout", "_blackout_factor", "_apply_blackout_gate",
          "_restore_flash_kill_gate", "BLACKOUT_FADE_S", "_KILL_EXTRA_CHANNELS"):
    a = getattr(MW, n)
    setattr(w, n, types.MethodType(a, w) if callable(a) else a)
w._refresh_blackout_display = lambda: None
w._log_message = lambda *a, **k: None

def frame():
    """Tick IA (repeint) puis porte puis « envoi » (capture) puis restauration."""
    for p in w.projectors:
        p.level = 100; p.color = QColor(255, 0, 0); p.base_color = QColor(255, 0, 0)
    saved = w._apply_blackout_gate()
    out = [(p.level, p.color.red(), p.strobe_speed, dict(p.effect_channels)) for p in w.projectors]
    w._restore_flash_kill_gate(saved)
    return out

check(frame()[0] == (100, 255, 50, {"prism": 128}), "hors blackout : sortie intacte")
check(w.toggle_blackout() is True, "toggle → ON")
mid = frame()[0]
check(0 <= mid[0] <= 100 and mid[2] == 0, f"fondu en cours, strobe coupé net {mid}")
time.sleep(w.BLACKOUT_FADE_S + 0.05)
for _ in range(5):
    o = frame()
check(o[0] == (0, 0, 0, {}), f"noir TENU malgré le moteur qui repeint {o[0]}")
check(o[1][0] == 100, "machine à fumée épargnée")
check(w.projectors[0].level == 100 and w.projectors[0].strobe_speed == 50
      and w.projectors[0].effect_channels == {"prism": 128}, "état du show non modifié")
check(w.toggle_blackout(True) is True, "forcer ON quand déjà ON : rien ne change")
check(w.toggle_blackout() is False, "toggle → OFF")
time.sleep(w.BLACKOUT_FADE_S + 0.05)
check(frame()[0] == (100, 255, 50, {"prism": 128}), "rallumé : le moteur reprend la main")
sys.exit(0 if ok else 1)
