# -*- coding: utf-8 -*-
"""Import MA d'un laser : la famille d'attributs « objet video » (V_*).

GrandMA ne modelise pas un laser comme un projecteur mais comme un OBJET VIDEO :
son dessin est une image (V_OIMAGE) qu'on tourne (V_OR_*), deplace (V_OP_*) et
redimensionne (V_OS_*). Aucun de ces attributs n'etait connu -> 13 des 14 canaux
du Laserworld CS-12000 sortaient « Unused », et le seul canal reconnu l'etait A
TORT (une vitesse de clignotement prise pour une roue de couleurs).

Pire : le canal 1 (FixtureMode) sortait 0 = Blackout, donc le laser IGNORAIT ses
treize autres canaux. La fixture s'importait sans erreur et ne faisait rien.
"""
import sys
sys.path.insert(0, r"C:\Users\nikop\Desktop\MyStrow")
import fixture_parser as fp

XML = (r"C:\Users\nikop\Downloads\Laserworld@CS-12000_RGB_FX@14_ch"
       r"@Fixture_made_form_User_Manual_14_channel_mode_CS-12000_RGB_FX.xml")

res = fp.parse_ma_xml(open(XML, "rb").read())
mode = res["modes"][0]
profile = mode["profile"]
labels = mode["labels"]

assert len(profile) == 14, f"14 canaux attendus, {len(profile)} obtenus"

# ── Le canal de mode DOIT sortir 150 (« DMX control »), sinon laser muet ──
# Le fichier porte default="149.756" : tronque il donne 149, qui retombe dans
# la plage « Stand alone ». Il FAUT arrondir.
assert profile[0] == "Mode", f"CH1 devrait etre Mode, pas {profile[0]}"
assert res["channel_defaults"].get("Mode") == 150, \
    f"CH1 doit valoir 150 (DMX control), pas {res['channel_defaults'].get('Mode')}"

# ── La roue de couleur est sur le canal 12, PAS sur le 13 ────────────────────
assert profile[11] == "ColorWheel", "CH12 (COLORCOLOR) = la vraie selection"
assert profile[12] == "Unused", \
    "CH13 (COLOR1WHEELSELECTBLINK) est une vitesse de clignotement, pas une roue"

# ── Les canaux rendus pilotables par les mecaniques existantes ───────────────
attendu = {1: "Mode", 2: "Gobo1", 3: "Gobo1Rot", 6: "Pan", 7: "Tilt",
           8: "Zoom", 10: "Speed", 12: "ColorWheel", 14: "Effects"}
for ch, t in attendu.items():
    assert profile[ch-1] == t, f"CH{ch} : attendu {t}, obtenu {profile[ch-1]}"

# ── Les jumeaux restent Unused : le moteur gange les canaux de meme type ────
for ch in (4, 5, 9, 11, 13):
    assert profile[ch-1] == "Unused", \
        f"CH{ch} doit rester brut (gang), obtenu {profile[ch-1]}"

# ── Chaque canal porte un nom DISTINCT et lisible ────────────────────────────
assert len(labels) == 14
assert len(set(labels)) == 14, f"libelles ambigus : {labels}"
for mauvais in ("X", "Y", "Z", "Position", "Type", "Images", "Color"):
    assert mauvais not in labels, f"libelle non distinctif restant : {mauvais}"
assert labels[5] == "Position X" and labels[6] == "Position Y"

print("profil :")
for i, (t, lb) in enumerate(zip(profile, labels), start=1):
    print(f"  CH{i:>2}  {t:<12} {lb}")
print(f"\nchannel_defaults : {res['channel_defaults']}")
print(f"Unused : {profile.count('Unused')}/14 (etait 13/14)")
print("\nOK - le laser est pilotable, la roue est sur le bon canal, noms distincts.")

# ── Garde-fou : le moissonnage de `default=` reste CANTONNE au canal de mode ─
# Le fichier Betopper porte default="255" sur R1/G1/B1. Moissonne largement, il
# produisait {"R":255,"G":255,"B":255} -> tout canal qui devait sortir 0 etait
# remonte a 255 : un rouge pur virait au blanc et la fixture ne pouvait plus
# s'eteindre. `channel_defaults` doit rester VIDE pour elle.
BETOPPER = r"C:\Users\nikop\Downloads\betopper_lm120_23ch.xml"
import os
if os.path.isfile(BETOPPER):
    bet = fp.parse_ma_xml(open(BETOPPER, "rb").read())
    assert bet["channel_defaults"] == {}, (
        "REGRESSION : default= moissonne hors canal de mode -> "
        f"{bet['channel_defaults']}")
    print("OK - Betopper : channel_defaults vide, le noir reste possible.")
else:
    print("(Betopper absent, garde-fou non joue)")
