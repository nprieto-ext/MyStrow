# -*- coding: utf-8 -*-
"""« Contenu sequence » : une memoire de faisceau seul doit se voir, et s'editer.

Contexte (02/09/2026) : mem 2.1 de Niko contenait `gobo 64` sur 16 lyres avec
`level 0` partout (CLEAR puis envoi d'un gobo). La fenetre filtrait ses lignes
sur niveau/pan/tilt/strobe/canaux bruts UNIQUEMENT : elle affichait « cette
memoire n'allume ni ne bouge aucun projecteur » alors que le gobo etait bien
enregistre ET bien rejoue par un clip Sequence. On en concluait que le REC
n'avait rien pris.

On teste le PREDICAT et le tableau, pas le pixel : filtrage, colonnes, edition
en ligne, suppression. Aucune ecriture disque : la fausse MainWindow n'a ni
`_save_akai_config_auto` ni `_refresh_memory_pad`.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from light_timeline import SequenceInfoDialog, memory_state_is_set, mem_ch_repos
from projector import Projector

ECHECS = []


def check(nom, cond):
    print(("  OK   " if cond else "  ECHEC") + "  " + nom)
    if not cond:
        ECHECS.append(nom)


def etat(**kw):
    """Un etat projecteur au format `_build_snapshot` : tout present, au repos."""
    base = {"group": "lat", "base_color": "#000000", "level": 0,
            "pan": 32768, "tilt": 32768, "uv": 0, "amber_boost": 0,
            "white_boost": 0, "orange_boost": 0, "gobo": 0, "gobo_rotation": 0,
            "zoom": 0, "strobe_speed": 0, "focus": 0, "gobo2": 0, "speed": 0,
            "mode_value": 0, "color_wheel": 0, "prism": 0, "prism_rotation": 0,
            "effects": 0, "iris": 0, "fan_speed": 0, "shutter": 255,
            "channel_extras": {}}
    base.update(kw)
    return base


class FauxMW:
    GROUP_DISPLAY = {"lat": "Lateraux"}

    def __init__(self, etats):
        self.projectors = []
        for i in range(len(etats)):
            p = Projector("lat", name="Lyre %d" % (i + 1))
            p.start_address = 1 + i * 10
            self.projectors.append(p)
        self.memories = [[None] for _ in range(2)]
        self.memories[1][0] = {"cues": [{"label": "Cue 1", "projectors": etats}],
                               "loop": True}


# ── 1. Le predicat ─────────────────────────────────────────────────────────
print("\n1. memory_state_is_set")
check("rig eteint et tout au repos = rien a montrer",
      not memory_state_is_set(etat()))
check("gobo seul (rig eteint) = la memoire regle quelque chose",
      memory_state_is_set(etat(gobo=64)))
check("roue de couleur seule = idem",
      memory_state_is_set(etat(color_wheel=42)))
check("strobe seul = idem", memory_state_is_set(etat(strobe_speed=58)))
check("niveau seul = idem", memory_state_is_set(etat(level=80)))
check("pan hors centre = idem", memory_state_is_set(etat(pan=47676)))
check("canal brut seul = idem",
      memory_state_is_set(etat(channel_extras={"12": 200})))
check("shutter ouvert (255) n'est PAS un reglage",
      not memory_state_is_set(etat(shutter=255)))
check("shutter ferme (0) en est un", memory_state_is_set(etat(shutter=0)))
check("repos du shutter = 255, celui du gobo = 0",
      mem_ch_repos("shutter") == 255 and mem_ch_repos("gobo") == 0)


# ── 2. Le tableau : mem 2.1 (gobo seul sur 16 lyres) ───────────────────────
print("\n2. Tableau d'une memoire « juste un gobo »")
etats = [etat(gobo=64, color_wheel=64) for _ in range(16)] + [etat() for _ in range(8)]
mw = FauxMW(etats)
dlg = SequenceInfoDialog(None, mw, memory_ref=(1, 0), cue_index=0,
                         label="MEM 2.1", intensity=100)
check("les 16 lyres reglees sont listees (et pas les 8 autres)",
      dlg._table.rowCount() == 16)
beam = dlg._table.item(0, dlg.C_BEAM).text()
check("la colonne Faisceau montre le gobo : " + repr(beam), "Gobo 64" in beam)
check("elle montre aussi la roue", "Roue 64" in beam)
check("le pied de fenetre ne dit plus « aucun projecteur »",
      "16" in dlg._foot.text())

dlg._chk_all.setChecked(True)
check("« tout le rig » revele les 24 projecteurs", dlg._table.rowCount() == 24)
dlg._chk_all.setChecked(False)


# ── 3. Edition en ligne ────────────────────────────────────────────────────
print("\n3. Edition")
dlg._table.item(0, dlg.C_LEVEL).setText("75")
check("le niveau saisi part dans la memoire", etats[0]["level"] == 75)
check("rallumer un projecteur noir repart du blanc, pas du noir",
      etats[0]["base_color"] == "#ffffff")

dlg._table.item(0, dlg.C_PAN).setText("100")
check("pan 100 % = 65535", etats[0]["pan"] == 65535)
dlg._table.item(0, dlg.C_PAN).setText("")
check("pan vide SUPPRIME la cle (sinon le pad AKAI recentre la lyre)",
      "pan" not in etats[0])

dlg._table.item(1, dlg.C_LEVEL).setText("n'importe quoi")
check("une saisie illisible ne casse rien", etats[1]["level"] == 0)

dlg._table.item(2, dlg.C_LEVEL).setText("250")
check("le niveau est borne a 100", etats[2]["level"] == 100)


# ── 4. Suppression ─────────────────────────────────────────────────────────
print("\n4. Suppression (confirmation neutralisee)")
import light_timeline as LT

_vus = []


class FauxQuestion:
    Yes = 1
    Cancel = 2

    @staticmethod
    def question(*a, **k):
        _vus.append(a[1] if len(a) > 1 else "")
        return FauxQuestion.Yes


_vrai_box = LT.QMessageBox
LT.QMessageBox = FauxQuestion
try:
    dlg._delete_projectors([3, 4])
finally:
    LT.QMessageBox = _vrai_box

check("le gobo est ramene au repos", etats[3]["gobo"] == 0)
check("la roue aussi", etats[3]["color_wheel"] == 0)
check("le shutter revient a 255, pas a 0 (sinon faisceau ferme)",
      etats[3]["shutter"] == 255)
check("pan/tilt sont SUPPRIMES, pas recentres",
      "pan" not in etats[4] and "tilt" not in etats[4])
check("la liste garde ses 24 entrees (jamais de pop : elle est indexee par n° de projecteur)",
      len(etats) == 24)
check("une seule confirmation pour une selection multiple", len(_vus) == 1)
check("les lignes videes disparaissent du tableau", dlg._table.rowCount() == 14)

# ⚠️ Les 16 lyres du depart : 0,1,2 restent (niveau saisi plus haut), 3 et 4
# sont neutralisees, 5..15 gardent leur gobo → 14 lignes.

print("\n" + ("TOUT PASSE" if not ECHECS else "ECHECS: " + ", ".join(ECHECS)))
sys.exit(1 if ECHECS else 0)
