"""Remise d'usine des effets prédéfinis (retour client FuraxX, 16/11/2026)."""
import copy
from types import SimpleNamespace as NS

import effect_editor as ee


class _FauxMW:
    def __init__(self, nom, couches_modifiees):
        cfg = lambda: {"name": nom, "layers": copy.deepcopy(couches_modifiees),
                       "play_mode": "once", "duration": 4}
        self._effect_library_configs = {nom: cfg(), "Mon perso": cfg() | {"name": "Mon perso"}}
        self._button_effect_configs = {0: cfg()}
        self.fx_pads = [[cfg(), None]]
        self.memories = [[{"effect": cfg(), "cues": [{"effect": cfg()}]}]]
        self.active_effect_config = cfg()
        self.sauvegardes = []

    def _save_effect_library(self):     self.sauvegardes.append("lib")
    def _save_effect_assignments(self): self.sauvegardes.append("btn")
    def _save_akai_config_auto(self):   self.sauvegardes.append("akai")


def test_remise_usine_partout():
    eff = next(e for e in ee.BUILTIN_EFFECTS if e["name"] == "Lyre Cercle")
    mw = _FauxMW(eff["name"], [{"attribute": "Tilt", "size": 400}])
    ed = NS(_main_window=mw, _selected_card="autre", _layers=[])
    cls = next(c for c in vars(ee).values()
               if isinstance(c, type) and hasattr(c, "_reset_builtin_effects"))
    cls._reset_builtin_effects(ed, [eff["name"]], confirm=False)

    usine = eff["layers"]
    assert eff["name"] not in mw._effect_library_configs
    assert "Mon perso" in mw._effect_library_configs          # Mes Effets intacts
    assert mw._button_effect_configs[0]["layers"] == usine
    assert mw._button_effect_configs[0]["play_mode"] == "once"  # affectation gardée
    assert mw.fx_pads[0][0]["layers"] == usine
    assert mw.memories[0][0]["effect"]["layers"] == usine
    assert mw.memories[0][0]["cues"][0]["effect"]["layers"] == usine
    assert mw.active_effect_config["layers"] == usine
    assert mw.fx_pads[0][0]["layers"] is not usine             # copie, pas l'original
    assert {"lib", "btn", "akai"} <= set(mw.sauvegardes)


if __name__ == "__main__":
    test_remise_usine_partout(); print("OK")
