# -*- coding: utf-8 -*-
"""Le strobe doit sortir sur le canal Shutter des fixtures sans canal Strobe.

Symptome client (02/09/2026, Niko) : « j'ai enregistre une sequence avec juste
du strob sur mes lyres, a la restitution je ne peux pas faire strober mes
projecteurs ». Cause : la branche `Shutter` de `ArtNetDMX` ne lisait QUE
`proj.shutter` (255 au repos) et ignorait completement `strobe_speed`, alors
que 57 profils integres (lyres generiques, ADJ, Chauvet, stroboscopes 2CH...)
portent un `Shutter` sans `Strobe`. Le plan 2D, lui, faisait clignoter la
pastille : l'interface affirmait un strobe que le fil ne portait pas.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from artnet_dmx import ArtNetDMX
from projector import Projector

# Profil reel du patch de Niko (« Lyre TEST », 13 canaux) : Shutter, pas Strobe.
LYRE      = ['Pan', 'PanFine', 'Tilt', 'TiltFine', 'Speed', 'ColorWheel',
             'Gobo1', 'Gobo1Rot', 'Prism', 'Shutter', 'Dim', 'Focus', 'Mode']
PAR       = ['Dim', 'R', 'G', 'B', 'Strobe', 'Mode', 'Mode']
LYRE_DEUX = ['Pan', 'Tilt', 'Shutter', 'Strobe', 'Dim']   # les DEUX canaux


def rig(profile, start, group):
    dmx = ArtNetDMX()
    p = Projector(group, "test", "Moving Head")
    p.dmx_profile = list(profile)
    p.level = 100
    p.base_color = QColor("#ffffff")
    p.color = QColor("#ffffff")
    p.muted = False
    chans = list(range(start, start + len(profile)))
    dmx.set_projector_patch(f"{group}_0", chans, 0, profile=profile)
    return dmx, p, chans


def val(dmx, chans, profile, ch_type):
    return dmx.dmx_data[0][chans[profile.index(ch_type)] - 1]


# ── 1) La lyre strobe, et la vitesse tombe dans la bande ─────────────────────
dmx, lyre, ch = rig(LYRE, 1, 'douche1')
dmx.update_from_projectors([lyre])
assert val(dmx, ch, LYRE, 'Shutter') == 255, "au repos le shutter reste OUVERT"

sorties = []
for spd in (1, 17, 58, 100):
    lyre.strobe_speed = spd
    dmx.update_from_projectors([lyre])
    sorties.append(val(dmx, ch, LYRE, 'Shutter'))
print("bande par defaut 64-95 :", sorties)
assert all(64 <= v <= 95 for v in sorties), f"hors bande : {sorties}"
assert sorties == sorted(sorties) and sorties[0] < sorties[-1], "pas monotone"
assert sorties[-1] == 95, "100 % doit atteindre le haut de la bande"

# Le dimmer reste plein : le hachage est fait par la fixture, pas par le Dim.
assert val(dmx, ch, LYRE, 'Dim') == 255, "le Dim ne doit pas etre hache en plus"

# ── 2) Retour a 0 : le shutter se rouvre ─────────────────────────────────────
lyre.strobe_speed = 0
dmx.update_from_projectors([lyre])
assert val(dmx, ch, LYRE, 'Shutter') == 255, "strobe coupe => shutter rouvert"

# ── 3) Bande reglable par fixture ────────────────────────────────────────────
lyre.shutter_strobe_min, lyre.shutter_strobe_max = 8, 215
for spd, attendu in ((1, 8), (100, 215)):
    lyre.strobe_speed = spd
    dmx.update_from_projectors([lyre])
    v = val(dmx, ch, LYRE, 'Shutter')
    assert abs(v - attendu) <= 3, f"bande 8-215, spd={spd} -> {v}"
print("bande personnalisee 8-215 : OK")

# Bornes saisies a l'envers : on ne sort pas de la plage pour autant.
lyre.shutter_strobe_min, lyre.shutter_strobe_max = 215, 8
lyre.strobe_speed = 50
dmx.update_from_projectors([lyre])
v = val(dmx, ch, LYRE, 'Shutter')
assert 8 <= v <= 215, f"bornes inversees : {v}"

# ── 4) `shutter_inverted` ne MIROITE PAS la bande ────────────────────────────
# Cette bascule ne decrit que la convention ouvert/ferme. Miroiter la vitesse
# enverrait le strobe dans une plage de macros de la fixture.
lyre.shutter_strobe_min, lyre.shutter_strobe_max = 64, 95
lyre.shutter_inverted = True
lyre.strobe_speed = 100
dmx.update_from_projectors([lyre])
v = val(dmx, ch, LYRE, 'Shutter')
assert v == 95, f"la bande est du DMX brut, pas d'inversion : {v}"
lyre.shutter_inverted = False

# ── 5) Un canal brut sur le Shutter prime toujours ───────────────────────────
lyre.strobe_speed = 100
lyre.channel_extras = {'Shutter': 42}
dmx.update_from_projectors([lyre])
assert val(dmx, ch, LYRE, 'Shutter') == 42, "le curseur brut doit primer"
lyre.channel_extras = {}

# ── 6) Fixture a canal Strobe DEDIE : le Shutter ne double pas le hachage ────
# Deux mecanismes de strobe sur la meme fixture se soustraient au lieu de
# s'ajouter (cf. la regression LIVE 3.1.85 « ca strobe tres leger »).
dmx2, lyre2, ch2 = rig(LYRE_DEUX, 100, 'face')
lyre2.strobe_speed = 100
dmx2.update_from_projectors([lyre2])
assert val(dmx2, ch2, LYRE_DEUX, 'Strobe') == 250, "le canal dedie porte le strobe"
assert val(dmx2, ch2, LYRE_DEUX, 'Shutter') == 255, \
    "avec un canal Strobe dedie, le Shutter reste OUVERT"
print("fixture Shutter + Strobe : un seul mecanisme, OK")

# ── 7) Non-regression PAR LED (canal Strobe) ─────────────────────────────────
dmx3, par, ch3 = rig(PAR, 209, 'douche2')
for spd, attendu in ((0, 0), (17, 55), (58, 151), (100, 250)):
    par.strobe_speed = spd
    dmx3.update_from_projectors([par])
    v = val(dmx3, ch3, PAR, 'Strobe')
    assert v == attendu, f"PAR LED spd={spd} -> {v}, attendu {attendu}"
print("PAR LED a canal Strobe : inchange, OK")

# ── 8) Stroboscope 2CH : c'est bien le Shutter qui porte la vitesse ──────────
STROBO = ['Shutter', 'Dim']
dmx4, sb, ch4 = rig(STROBO, 300, 'lat')
sb.shutter_strobe_min, sb.shutter_strobe_max = 16, 250   # rampe pleine
sb.strobe_speed = 100
dmx4.update_from_projectors([sb])
assert val(dmx4, ch4, STROBO, 'Shutter') == 250, "stroboscope 2CH muet"
print("stroboscope 2CH : OK")

print("\nOK - le strobe atteint le fil sur les fixtures a canal Shutter.")
