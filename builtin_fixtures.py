"""
Bibliothèque de fixtures DMX pré-définies — MyStrow
Organisées par fabricant pour un accès rapide sans requête réseau.

Format de chaque entrée :
    name          : str   — nom affiché
    manufacturer  : str   — marque / fabricant
    fixture_type  : str   — "PAR LED" | "Moving Head" | "Barre LED" | "Stroboscope" | "Machine a fumee" | "Gradateur"
    group         : str   — groupe DMX par défaut
    profile       : list  — séquence de types de canaux MyStrow
    builtin       : True  — flag indiquant un template intégré (non supprimable)
"""

_B = True  # builtin shorthand

BUILTIN_FIXTURES = [

    # ──────────────────────────────────────────────────────────────────────────
    # Générique  (profils de base, sans marque spécifique)
    # ──────────────────────────────────────────────────────────────────────────
    # ── PAR LED / Projecteur à LEDs ───────────────────────────────────────────
    {"name": "PAR LED · R, G, B (3ch)",              "manufacturer": "Générique", "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "PAR LED · R, G, B, Dim (4ch)",         "manufacturer": "Générique", "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Dim"],                                     "builtin": _B},
    {"name": "PAR LED · R, G, B, Dim, Strobe (5ch)", "manufacturer": "Générique", "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Dim","Strobe"],                            "builtin": _B},
    {"name": "PAR LED · Dim, R, G, B (4ch)",         "manufacturer": "Générique", "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B"],                                     "builtin": _B},
    {"name": "PAR LED · Dim, R, G, B, Strobe (5ch)", "manufacturer": "Générique", "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","Strobe"],                            "builtin": _B},
    {"name": "PAR LED · R, G, B, Blanc (4ch)",       "manufacturer": "Générique", "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "PAR LED · R, G, B, Blanc, Dim (5ch)",  "manufacturer": "Générique", "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Dim"],                                 "builtin": _B},
    {"name": "PAR LED · R, G, B, Blanc, Dim, Strobe (6ch)", "manufacturer": "Générique", "fixture_type": "PAR LED", "group": "face",   "profile": ["R","G","B","W","Dim","Strobe"],                        "builtin": _B},
    {"name": "PAR LED · R, G, B, Blanc, Ambre (5ch)","manufacturer": "Générique", "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Ambre"],                               "builtin": _B},
    {"name": "PAR LED · R, G, B, Blanc, Ambre, UV (6ch)", "manufacturer": "Générique", "fixture_type": "PAR LED",   "group": "face",   "profile": ["R","G","B","W","Ambre","UV"],                          "builtin": _B},
    # ── Gradateurs / Traditionnels (incandescence, halogène) ─────────────────
    {"name": "Gradateur 1 canal",                    "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "face",   "profile": ["Dim"],                                                 "builtin": _B},
    {"name": "PAR 64 Incandescent",                  "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "face",   "profile": ["Dim"],                                                 "builtin": _B},
    {"name": "PAR 56 Incandescent",                  "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "face",   "profile": ["Dim"],                                                 "builtin": _B},
    {"name": "PAR 36 Incandescent",                  "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "face",   "profile": ["Dim"],                                                 "builtin": _B},
    {"name": "Fresnel Incandescent",                 "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "face",   "profile": ["Dim"],                                                 "builtin": _B},
    {"name": "PC Incandescent",                      "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "face",   "profile": ["Dim"],                                                 "builtin": _B},
    {"name": "Profil / Leko Incandescent",           "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "face",   "profile": ["Dim"],                                                 "builtin": _B},
    {"name": "Cyclorama Incandescent",               "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "contre", "profile": ["Dim"],                                                 "builtin": _B},
    {"name": "Strip / Rampe Incandescent",           "manufacturer": "Générique", "fixture_type": "Gradateur",       "group": "face",   "profile": ["Dim"],                                                 "builtin": _B},
    # ── Lyres / Têtes mobiles ─────────────────────────────────────────────────
    {"name": "Lyre Spot · Basique (7ch)",            "manufacturer": "Générique", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Shutter","Dim","ColorWheel","Gobo1","Speed"], "builtin": _B},
    {"name": "Lyre Spot · Pan/Tilt (8ch)",           "manufacturer": "Générique", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Shutter","Dim","ColorWheel","Gobo1","Speed","Mode"], "builtin": _B},
    {"name": "Lyre Wash · R, G, B (8ch)",            "manufacturer": "Générique", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","R","G","B","Dim","Shutter","Speed"],       "builtin": _B},
    {"name": "Lyre Wash · R, G, B, Blanc (9ch)",     "manufacturer": "Générique", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","R","G","B","W","Dim","Shutter","Speed"],   "builtin": _B},
    {"name": "Lyre Beam · Pan/Tilt (7ch)",           "manufacturer": "Générique", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","ColorWheel","Gobo1","Shutter","Dim","Speed"], "builtin": _B},
    {"name": "Lyre Spot · Complet (12ch)",           "manufacturer": "Générique", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Prism","Shutter","Dim","Focus","Mode"], "builtin": _B},
    # ── Barres LED ────────────────────────────────────────────────────────────
    {"name": "Barre LED · R, G, B (3ch)",            "manufacturer": "Générique", "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "Barre LED · R, G, B, Dim, Strobe (5ch)","manufacturer": "Générique", "fixture_type": "Barre LED",      "group": "face",   "profile": ["R","G","B","Dim","Strobe"],                            "builtin": _B},
    {"name": "Barre LED · R, G, B, Blanc (4ch)",     "manufacturer": "Générique", "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "Barre LED · R, G, B, Blanc, Dim, Strobe (6ch)", "manufacturer": "Générique", "fixture_type": "Barre LED", "group": "face",  "profile": ["R","G","B","W","Dim","Strobe"],                     "builtin": _B},
    # ── Stroboscopes ─────────────────────────────────────────────────────────
    {"name": "Stroboscope · Intensité + Vitesse (2ch)", "manufacturer": "Générique", "fixture_type": "Stroboscope",  "group": "face",   "profile": ["Shutter","Dim"],                                       "builtin": _B},
    # ── Machines à effets ────────────────────────────────────────────────────
    {"name": "Machine à fumée · 2 canaux",           "manufacturer": "Générique", "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},
    {"name": "Hazer · 2 canaux",                     "manufacturer": "Générique", "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # ADJ (American DJ)
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Mega Tripar Profile 4ch",     "manufacturer": "ADJ",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Dim"],                                     "builtin": _B},
    {"name": "Mega Tripar Profile 7ch",     "manufacturer": "ADJ",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","Strobe","ColorWheel","Mode"],         "builtin": _B},
    {"name": "Mega HEX PAR 7ch",            "manufacturer": "ADJ",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Ambre","W","UV","Dim"],                     "builtin": _B},
    {"name": "Mega HEX PAR 12ch",           "manufacturer": "ADJ",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","Ambre","W","UV","Strobe","ColorWheel","Speed","Mode","Mode"], "builtin": _B},
    {"name": "12P HEX IP 7ch",              "manufacturer": "ADJ",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Ambre","W","UV","Dim"],                     "builtin": _B},
    {"name": "Ultra HEX PAR 3 7ch",         "manufacturer": "ADJ",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Ambre","W","UV","Dim"],                     "builtin": _B},
    {"name": "Inno Pocket Roll 6ch",        "manufacturer": "ADJ",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","ColorWheel","Gobo1","Speed","Strobe"],     "builtin": _B},
    {"name": "Vizi Beam 5RX 12ch",          "manufacturer": "ADJ",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Prism","Shutter","Dim","Focus","Mode"], "builtin": _B},
    {"name": "Focus Spot 4Z 9ch",           "manufacturer": "ADJ",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","ColorWheel","Gobo1","Shutter","Dim","Zoom"], "builtin": _B},
    {"name": "Vizi Wash Z19 7ch",           "manufacturer": "ADJ",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","R","G","B","W","Dim"],                     "builtin": _B},
    {"name": "Vizi Wash Z37 9ch",           "manufacturer": "ADJ",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","R","G","B","W","Dim"], "builtin": _B},
    {"name": "Inno Pocket Beam 4ch",        "manufacturer": "ADJ",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","ColorWheel"],                      "builtin": _B},
    {"name": "Nucleus Pro 8ch",             "manufacturer": "ADJ",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","R","G","B","W","Shutter","Speed"],         "builtin": _B},
    {"name": "Jolt 300 2ch",                "manufacturer": "ADJ",       "fixture_type": "Stroboscope",     "group": "face",   "profile": ["Shutter","Dim"],                                       "builtin": _B},
    {"name": "Dotz Bar 20 5ch",             "manufacturer": "ADJ",       "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B","Dim","Strobe"],                            "builtin": _B},
    {"name": "Fog Fury Jett 2ch",           "manufacturer": "ADJ",       "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Cameo
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "FLAT PRO 7 3ch",              "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "FLAT PRO 7 7ch",              "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W","Ambre","UV"],                     "builtin": _B},
    {"name": "FLAT PAR CAN RGBW 4ch",       "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "FLAT PAR CAN RGBW 5ch",       "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Dim"],                                 "builtin": _B},
    {"name": "FLAT PAR CAN RGBW 6ch",       "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Dim","Strobe"],                        "builtin": _B},
    {"name": "FLAT PAR TRI 3ch",            "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "FLAT PAR TRI 5ch",            "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Dim","Strobe"],                            "builtin": _B},
    {"name": "THUNDERWASH 600 RGBW 4ch",    "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "THUNDERWASH 600 RGBW 7ch",    "manufacturer": "Cameo",     "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W","Strobe","Mode"],                  "builtin": _B},
    {"name": "HYDRASPOT 300 10ch",          "manufacturer": "Cameo",     "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Shutter","Dim","Zoom"], "builtin": _B},
    {"name": "HYDRABEAM 4000 RGBW 9ch",     "manufacturer": "Cameo",     "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W"], "builtin": _B},
    {"name": "HYDRABEAM 400 RGBW 9ch",      "manufacturer": "Cameo",     "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W"], "builtin": _B},
    {"name": "PIXBAR 600 PRO 8ch",          "manufacturer": "Cameo",     "fixture_type": "Barre LED",       "group": "face",   "profile": ["Dim","R","G","B","W","Ambre","UV","Strobe"],            "builtin": _B},
    {"name": "PIXBAR 650 CPRO 8ch",         "manufacturer": "Cameo",     "fixture_type": "Barre LED",       "group": "face",   "profile": ["Dim","R","G","B","W","Ambre","UV","Strobe"],            "builtin": _B},
    {"name": "HYDRABAR 10 IP 9ch",          "manufacturer": "Cameo",     "fixture_type": "Barre LED",       "group": "face",   "profile": ["Dim","R","G","B","W","Ambre","UV","Strobe","Mode"],     "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Chauvet DJ
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "SlimPAR 56 3ch",              "manufacturer": "Chauvet DJ","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "SlimPAR 56 4ch",              "manufacturer": "Chauvet DJ","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Dim"],                                     "builtin": _B},
    {"name": "SlimPAR 56 7ch",              "manufacturer": "Chauvet DJ","fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","Strobe","ColorWheel","Mode"],         "builtin": _B},
    {"name": "SlimPAR 64 RGBA 4ch",         "manufacturer": "Chauvet DJ","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Ambre"],                                   "builtin": _B},
    {"name": "SlimPAR 64 RGBAW 6ch",        "manufacturer": "Chauvet DJ","fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","Ambre","W"],                         "builtin": _B},
    {"name": "Colorado 2 Solo 5ch",         "manufacturer": "Chauvet DJ","fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W"],                                 "builtin": _B},
    {"name": "Colorado 2 Solo 9ch",         "manufacturer": "Chauvet DJ","fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W","Strobe","ColorWheel","Zoom","Mode"], "builtin": _B},
    {"name": "Intimidator Spot 360 8ch",    "manufacturer": "Chauvet DJ","fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","ColorWheel","Gobo1","Shutter","Dim","Mode"], "builtin": _B},
    {"name": "Intimidator Wash 360 9ch",    "manufacturer": "Chauvet DJ","fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","R","G","B","W","Shutter","Dim"],   "builtin": _B},
    {"name": "Intimidator Beam 140SR 9ch",  "manufacturer": "Chauvet DJ","fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","Gobo1","ColorWheel","Shutter","Dim"], "builtin": _B},
    {"name": "Intimidator Hybrid 140SR 17ch","manufacturer": "Chauvet DJ","fixture_type": "Moving Head",    "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","R","G","B","W","Mode"], "builtin": _B},
    {"name": "Swarm 5 FX 4ch",              "manufacturer": "Chauvet DJ","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Strobe"],                                   "builtin": _B},
    {"name": "Hurricane 1000 2ch",          "manufacturer": "Chauvet DJ","fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},
    {"name": "Amhaze II 2ch",               "manufacturer": "Chauvet DJ","fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Chauvet Professional
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Ovation E-190WW 3ch",         "manufacturer": "Chauvet Professional","fixture_type": "PAR LED","group": "face",  "profile": ["Dim","Strobe","Mode"],                                 "builtin": _B},
    {"name": "Ovation P-56FC 3ch",          "manufacturer": "Chauvet Professional","fixture_type": "PAR LED","group": "face",  "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "Ovation P-56FC 6ch",          "manufacturer": "Chauvet Professional","fixture_type": "PAR LED","group": "face",  "profile": ["Dim","R","G","B","W","Ambre"],                         "builtin": _B},
    {"name": "Rogue R2 Spot 16ch",          "manufacturer": "Chauvet Professional","fixture_type": "Moving Head","group": "face", "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","R","G","B","Mode"], "builtin": _B},
    {"name": "Rogue R2 Wash 14ch",          "manufacturer": "Chauvet Professional","fixture_type": "Moving Head","group": "face", "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W","Dim","Shutter","Zoom","Mode","Mode"], "builtin": _B},
    {"name": "Rogue R3 Beam 16ch",          "manufacturer": "Chauvet Professional","fixture_type": "Moving Head","group": "face", "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Prism","Focus","Shutter","Dim","R","G","B","W","Mode"], "builtin": _B},
    {"name": "Nexus 4x4 3ch",               "manufacturer": "Chauvet Professional","fixture_type": "Barre LED","group": "face",  "profile": ["R","G","B"],                                        "builtin": _B},
    {"name": "Nexus 4x4 7ch",               "manufacturer": "Chauvet Professional","fixture_type": "Barre LED","group": "face",  "profile": ["Dim","R","G","B","W","Strobe","Mode"],              "builtin": _B},
    {"name": "Strike 4 4ch",                "manufacturer": "Chauvet Professional","fixture_type": "Stroboscope","group": "face",  "profile": ["Shutter","Dim","Mode","Strobe"],                  "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Eurolite
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "LED PAR-56 RGB 3ch",          "manufacturer": "Eurolite",  "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "LED PAR-56 QCL 4ch",          "manufacturer": "Eurolite",  "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "LED PAR-56 QCL 6ch",          "manufacturer": "Eurolite",  "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Strobe","Mode"],                       "builtin": _B},
    {"name": "LED PAR-64 RGBW 4ch",         "manufacturer": "Eurolite",  "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "LED PAR-64 RGBW 8ch",         "manufacturer": "Eurolite",  "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W","Strobe","ColorWheel","Mode"],     "builtin": _B},
    {"name": "LED T-36 RGB 3ch",            "manufacturer": "Eurolite",  "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "LED T-36 RGB 6ch",            "manufacturer": "Eurolite",  "fixture_type": "Barre LED",       "group": "face",   "profile": ["Dim","R","G","B","Strobe","Mode"],                     "builtin": _B},
    {"name": "LED T-36 QCL 6ch",            "manufacturer": "Eurolite",  "fixture_type": "Barre LED",       "group": "face",   "profile": ["Dim","R","G","B","W","Strobe"],                        "builtin": _B},
    {"name": "TMH-X12 Moving Wash 10ch",    "manufacturer": "Eurolite",  "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W","Dim"], "builtin": _B},
    {"name": "TMH-300 Spot 9ch",            "manufacturer": "Eurolite",  "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Shutter","Dim"], "builtin": _B},
    {"name": "TMH-H90 Hybrid 16ch",         "manufacturer": "Eurolite",  "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","R","G","B","Mode"], "builtin": _B},
    {"name": "NSF-250 Smoke 2ch",           "manufacturer": "Eurolite",  "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},
    {"name": "LED Strobe 2ch",              "manufacturer": "Eurolite",  "fixture_type": "Stroboscope",     "group": "face",   "profile": ["Shutter","Dim"],                                       "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # GLP (German Light Products)
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "impression X4 14ch",          "manufacturer": "GLP",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","R","G","B","W","Dim","Strobe","Zoom","Speed","Mode","Mode"], "builtin": _B},
    {"name": "impression X4 S 14ch",        "manufacturer": "GLP",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","R","G","B","W","Dim","Strobe","Zoom","Speed","Mode","Mode"], "builtin": _B},
    {"name": "impression FR10 Bar 8ch",     "manufacturer": "GLP",       "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B","W","Dim","Strobe","Mode","Mode"],           "builtin": _B},
    {"name": "JDC1 16ch",                   "manufacturer": "GLP",       "fixture_type": "Stroboscope",     "group": "face",   "profile": ["Dim","Strobe","R","G","B","W","Mode","Mode","Mode","Mode","Mode","Mode","Mode","Mode","Mode","Mode"], "builtin": _B},
    {"name": "X4 atom 5ch",                 "manufacturer": "GLP",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Dim"],                                 "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Clay Paky / Arri
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Sharpy 16ch",                 "manufacturer": "Clay Paky", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Prism","Focus","Shutter","Dim","Mode","Mode","Mode","Mode","Mode"], "builtin": _B},
    {"name": "Alpha Spot HPE 300 16ch",     "manufacturer": "Clay Paky", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B"],        "builtin": _B},
    {"name": "Axcor Spot 300 16ch",         "manufacturer": "Clay Paky", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B"],        "builtin": _B},
    {"name": "Axcor Wash 600 16ch",         "manufacturer": "Clay Paky", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","R","G","B","W","Ambre","UV","Dim","Shutter","Zoom","Speed","Mode","Mode"],                      "builtin": _B},
    {"name": "Aleda K20 HX 6ch",            "manufacturer": "Clay Paky", "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W","Ambre"],                         "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Martin Professional
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "MAC Aura 16ch",               "manufacturer": "Martin",    "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","ColorWheel","Dim","R","G","B","W","UV","Shutter","Speed","Zoom","Focus","Mode"], "builtin": _B},
    {"name": "MAC Quantum Wash 14ch",       "manufacturer": "Martin",    "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","ColorWheel","R","G","B","W","Dim","Strobe","Zoom","Speed","Mode"],            "builtin": _B},
    {"name": "MAC Encore Performance 26ch", "manufacturer": "Martin",    "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B","W","UV","Mode","Mode","Mode","Mode","Mode","Mode","Mode","Mode"], "builtin": _B},
    {"name": "MAC101 7ch",                  "manufacturer": "Martin",    "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","R","G","B","Dim","Strobe"],                "builtin": _B},
    {"name": "RUSH PAR 2 CT 3ch",           "manufacturer": "Martin",    "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "RUSH PAR 2 CT 5ch",           "manufacturer": "Martin",    "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","Strobe"],                            "builtin": _B},
    {"name": "RUSH MH 3 Beam 8ch",          "manufacturer": "Martin",    "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","ColorWheel","Shutter","Dim","Gobo1","Mode"],      "builtin": _B},
    {"name": "Atomic 3000 LED 3ch",         "manufacturer": "Martin",    "fixture_type": "Stroboscope",     "group": "face",   "profile": ["Shutter","Dim","Mode"],                                "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Robe
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Robin 100 LEDBeam 6ch",       "manufacturer": "Robe",      "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","R","G","B","Dim"],                        "builtin": _B},
    {"name": "Robin 100 LEDBeam 14ch",      "manufacturer": "Robe",      "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","ColorWheel","R","G","B","W","Dim","Shutter","Speed","Zoom","Mode"], "builtin": _B},
    {"name": "Robin 600E Spot 16ch",        "manufacturer": "Robe",      "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Speed","Mode","Mode","Mode","Mode"], "builtin": _B},
    {"name": "Pointe 16ch",                 "manufacturer": "Robe",      "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Shutter","Dim","Focus","Zoom","R","G","B","Mode"], "builtin": _B},  # noqa
    {"name": "T1 Profile 26ch",             "manufacturer": "Robe",      "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B","W","UV","Mode","Mode","Mode","Mode","Mode","Mode","Mode","Mode"], "builtin": _B},
    {"name": "MegaPointe 20ch",             "manufacturer": "Robe",      "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B","W","UV","Mode","Mode"], "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Elation Professional
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Fuze Wash Z 350 19ch",        "manufacturer": "Elation",   "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W","Ambre","UV","Dim","Shutter","Zoom","Mode","Mode","Mode","Mode","Mode"], "builtin": _B},
    {"name": "Fuze Spot 16ch",              "manufacturer": "Elation",   "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B"],        "builtin": _B},
    {"name": "Rayzor 760 18ch",             "manufacturer": "Elation",   "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W","Ambre","UV","Dim","Shutter","Zoom","Mode","Mode","Mode","Mode"],        "builtin": _B},
    {"name": "SixPar 200 7ch",              "manufacturer": "Elation",   "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Ambre","UV","Dim"],                     "builtin": _B},
    {"name": "SixPar 300 7ch",              "manufacturer": "Elation",   "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Ambre","UV","Dim"],                     "builtin": _B},
    {"name": "Cuepix Panel WW3 8ch",        "manufacturer": "Elation",   "fixture_type": "Barre LED",       "group": "face",   "profile": ["Dim","R","G","B","W","Strobe","Mode","Mode"],           "builtin": _B},
    {"name": "Protron 3K LED 2ch",          "manufacturer": "Elation",   "fixture_type": "Stroboscope",     "group": "face",   "profile": ["Shutter","Dim"],                                       "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Showtec
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Compact PAR 7 Tri 3ch",       "manufacturer": "Showtec",   "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "Compact PAR 7 Tri 5ch",       "manufacturer": "Showtec",   "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Dim","Strobe"],                            "builtin": _B},
    {"name": "Compact PAR QCL 4ch",         "manufacturer": "Showtec",   "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "Compact PAR QCL 7ch",         "manufacturer": "Showtec",   "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W","Strobe","Mode"],                  "builtin": _B},
    {"name": "Compact PAR 7 HEX IP 7ch",    "manufacturer": "Showtec",   "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Ambre","UV","Dim"],                     "builtin": _B},
    {"name": "Phantom 25 Spot 11ch",        "manufacturer": "Showtec",   "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Prism","Shutter","Dim","Mode"], "builtin": _B},
    {"name": "Phantom 65 Wash 9ch",         "manufacturer": "Showtec",   "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W"], "builtin": _B},
    {"name": "Phantom 120 Spot 16ch",       "manufacturer": "Showtec",   "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B"], "builtin": _B},
    {"name": "LED Bar 4 RGB 3ch",           "manufacturer": "Showtec",   "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "LED Bar 8 RGB 3ch",           "manufacturer": "Showtec",   "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "LED Strobe SQ 2ch",           "manufacturer": "Showtec",   "fixture_type": "Stroboscope",     "group": "face",   "profile": ["Shutter","Dim"],                                       "builtin": _B},
    {"name": "Stageflow Smoke 2ch",         "manufacturer": "Showtec",   "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Stairville (Thomann)
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "LED Par 56 RGB 3ch",          "manufacturer": "Stairville","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "LED Par 64 RGBA 4ch",         "manufacturer": "Stairville","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Ambre"],                                   "builtin": _B},
    {"name": "LED Par 64 RGBW 4ch",         "manufacturer": "Stairville","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "LED Par 64 RGBW 5ch",         "manufacturer": "Stairville","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Dim"],                                 "builtin": _B},
    {"name": "LED Par 64 HEX 6ch",          "manufacturer": "Stairville","fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Ambre","UV"],                          "builtin": _B},
    {"name": "MH-x25 Beam 7ch",             "manufacturer": "Stairville","fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","ColorWheel","Shutter","Dim","Mode"], "builtin": _B},
    {"name": "MH-x200 Beam 8ch",            "manufacturer": "Stairville","fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","ColorWheel","Gobo1","Shutter","Dim","Mode"], "builtin": _B},
    {"name": "Strobe SMD PRO 2ch",          "manufacturer": "Stairville","fixture_type": "Stroboscope",     "group": "face",   "profile": ["Shutter","Dim"],                                       "builtin": _B},
    {"name": "Smoke Fog 1500 2ch",          "manufacturer": "Stairville","fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Varytec (Thomann)
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Hero Spot Wash 100 RGBWa 15ch","manufacturer": "Varytec",  "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W","Ambre","Dim","Shutter","Zoom","Mode","Mode"], "builtin": _B},
    {"name": "Hero Wash 100 9ch",           "manufacturer": "Varytec",  "fixture_type": "Moving Head",      "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","R","G","B","W","Dim"], "builtin": _B},
    {"name": "LED PAR 64 RGBW 5ch",         "manufacturer": "Varytec",  "fixture_type": "PAR LED",          "group": "face",   "profile": ["R","G","B","W","Dim"],                                 "builtin": _B},
    {"name": "LED PAR 64 HEX 7ch",          "manufacturer": "Varytec",  "fixture_type": "PAR LED",          "group": "face",   "profile": ["R","G","B","W","Ambre","UV","Dim"],                     "builtin": _B},
    {"name": "Giga Bar 2 RGBW 6ch",         "manufacturer": "Varytec",  "fixture_type": "Barre LED",        "group": "face",   "profile": ["R","G","B","W","Dim","Strobe"],                        "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Contest (marque française)
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "iColor-Par 6ch",              "manufacturer": "Contest",   "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Dim","Strobe"],                        "builtin": _B},
    {"name": "iMoveP 7ch",                  "manufacturer": "Contest",   "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","ColorWheel","Shutter","Dim","Mode"], "builtin": _B},
    {"name": "iMoveW 9ch",                  "manufacturer": "Contest",   "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","R","G","B","W","Dim","Shutter"],   "builtin": _B},
    {"name": "iPixel-Bar4 5ch",             "manufacturer": "Contest",   "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B","Dim","Strobe"],                            "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Prolights
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Arcled 715CW 5ch",            "manufacturer": "Prolights", "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Dim"],                                 "builtin": _B},
    {"name": "Arcled 715CW 8ch",            "manufacturer": "Prolights", "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W","Ambre","UV","Strobe"],            "builtin": _B},
    {"name": "Studiocob FC 4ch",            "manufacturer": "Prolights", "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "EclStudio 12ch",              "manufacturer": "Prolights", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W","Dim","Shutter","Zoom"], "builtin": _B},
    {"name": "EclSpot Profile 13ch",        "manufacturer": "Prolights", "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Prism","Focus","Shutter","Dim","Zoom","Mode"], "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Briteq
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "BT-DYNAX 18ch",               "manufacturer": "Briteq",    "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B","W","Mode"], "builtin": _B},
    {"name": "BT-MOVING HEAD BEAM 7ch",     "manufacturer": "Briteq",    "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","ColorWheel","Gobo1","Shutter","Dim"], "builtin": _B},
    {"name": "BT-PIXEL PAR 7ch",            "manufacturer": "Briteq",    "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Ambre","UV","Dim"],                     "builtin": _B},
    {"name": "BT-LED BAR6 5ch",             "manufacturer": "Briteq",    "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B","Dim","Strobe"],                            "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Antari (machines fumée / haze)
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "X-310 Hazer 2ch",             "manufacturer": "Antari",    "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},
    {"name": "Z-1500 Fog 2ch",              "manufacturer": "Antari",    "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},
    {"name": "Z-3000 Fog 2ch",              "manufacturer": "Antari",    "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},
    {"name": "HZ-500 Hazer 2ch",            "manufacturer": "Antari",    "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Look Solutions
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Unique 2.1 Hazer 2ch",        "manufacturer": "Look Solutions","fixture_type": "Machine a fumee","group": "face",  "profile": ["Smoke","Fan"],                                      "builtin": _B},
    {"name": "Viper S Fog 2ch",             "manufacturer": "Look Solutions","fixture_type": "Machine a fumee","group": "face",  "profile": ["Smoke","Fan"],                                      "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # JB-Lighting
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "P12 Wash 16ch",               "manufacturer": "JB-Lighting","fixture_type": "Moving Head",    "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","R","G","B","W","Ambre","UV","Dim","Shutter","Zoom","Mode","Mode"], "builtin": _B},
    {"name": "Sparx10 16ch",                "manufacturer": "JB-Lighting","fixture_type": "Moving Head",    "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B"], "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # SGM
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "G-7 Spot 16ch",               "manufacturer": "SGM",       "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","PanFine","Tilt","TiltFine","Speed","ColorWheel","Gobo1","Gobo2","Prism","Focus","Shutter","Dim","Zoom","R","G","B"], "builtin": _B},
    {"name": "P-5 5ch",                     "manufacturer": "SGM",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Dim"],                                 "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # ETC
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Source 4 LED Series 3 5ch",   "manufacturer": "ETC",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["Dim","R","G","B","W"],                                 "builtin": _B},
    {"name": "Lustr X8 8ch",                "manufacturer": "ETC",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Ambre","UV","Dim","Mode"],              "builtin": _B},
    {"name": "ColorSource PAR 4ch",         "manufacturer": "ETC",       "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","Dim"],                                     "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Fun Generation (Thomann)
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "LED PAR 56 RGB 3ch",          "manufacturer": "Fun Generation","fixture_type": "PAR LED",     "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "LED PAR 56 RGBW 4ch",         "manufacturer": "Fun Generation","fixture_type": "PAR LED",     "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "LED Cameleon Bar 4 6ch",       "manufacturer": "Fun Generation","fixture_type": "Barre LED",  "group": "face",   "profile": ["R","G","B","W","Dim","Strobe"],                        "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Astera
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "AX1 PixelTube 8ch",           "manufacturer": "Astera",    "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B","W","Dim","Strobe","Mode","Mode"],           "builtin": _B},
    {"name": "AX3 LightDrop 4ch",           "manufacturer": "Astera",    "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W"],                                       "builtin": _B},
    {"name": "Titan Tube 8ch",              "manufacturer": "Astera",    "fixture_type": "Barre LED",       "group": "face",   "profile": ["R","G","B","W","Dim","Strobe","Mode","Mode"],           "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Sagitter
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "Bullet Wash 12 7ch",          "manufacturer": "Sagitter",  "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B","W","Ambre","UV","Dim"],                     "builtin": _B},
    {"name": "DigitalPar 3 3ch",            "manufacturer": "Sagitter",  "fixture_type": "PAR LED",         "group": "face",   "profile": ["R","G","B"],                                           "builtin": _B},
    {"name": "Moov 14 5ch",                 "manufacturer": "Sagitter",  "fixture_type": "Moving Head",     "group": "face",   "profile": ["Pan","Tilt","Speed","Shutter","Dim"],                   "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # LeMaitre
    # ──────────────────────────────────────────────────────────────────────────
    {"name": "G300 Fog 2ch",                "manufacturer": "LeMaitre",  "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},
    {"name": "Glaciator X Stream Hazer 2ch","manufacturer": "LeMaitre",  "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},
    {"name": "MVS Hazer 2ch",               "manufacturer": "LeMaitre",  "fixture_type": "Machine a fumee", "group": "face",   "profile": ["Smoke","Fan"],                                         "builtin": _B},

    # ──────────────────────────────────────────────────────────────────────────
    # Mac Mah
    # ──────────────────────────────────────────────────────────────────────────
    # LASER — un laser ne se decrit PAS comme un projecteur : il ne melange pas
    # de couleur, il DESSINE. Le motif est rendu par `Gobo1` (d'ou le
    # `fixture_type` « Moving Head », seul type que `core.fixture_projects_gobo`
    # autorise a projeter un motif) et se deplace par `Pan`/`Tilt` — ce qui
    # branche d'un coup les presets de position, la piste Position, les effets
    # pan/tilt et le stick de la manette sur l'appareil, sans une ligne de code
    # specifique. Choix opinione, cf. le Laserworld CS-12000.
    #
    # ⚠️ AUCUN canal n'est double : le moteur GANGE les canaux de meme type
    # (ils recoivent tous la meme valeur). Les fonctions secondaires prennent
    # donc des types MANUELS distincts (`Anim`, `AnimRot`, `Frost`, `Iris`) —
    # ils sortent 0 au repos, ce qui vaut « aucune rotation / aucune onde » sur
    # cet appareil, et se poussent au curseur des « canaux avances ».
    # Les canaux restants sont `Unused` mais NOMMES : ils restent joignables par
    # leur NUMERO dans la vue Curseurs.
    {"name": "MAC 1000 RGB · Laser 16ch", "manufacturer": "Mac Mah", "fixture_type": "Moving Head", "group": "face",
     "profile": ["Dim", "Speed", "Preset1", "Gobo1", "ColorWheel", "Preset2", "Preset3", "Zoom",
                 "Gobo1Rot", "Anim", "AnimRot", "Pan", "Tilt", "Iris", "Preset4", "Frost"],
     "channel_labels": ["Intensité", "Vitesse auto / sensibilité micro", "Bibliothèque de motifs",
                        "Choix du motif", "Couleur", "Vitesse de changement de couleur",
                        "Doublure / motif à pois", "Taille du motif", "Rotation du motif",
                        "Rotation horizontale", "Rotation verticale", "Mouvement horizontal",
                        "Mouvement vertical", "Zoom du motif", "Dessin progressif", "Onde X / Onde Y"],
     "preset_slots": {
         "Preset1": [{"name": "Motifs statiques", "color": "#00cc99", "dmx": 0},
                     {"name": "Motifs dynamiques", "color": "#00cc99", "dmx": 64}],
         "Preset2": [{"name": "Arrêt", "color": "#888888", "dmx": 0},
                     {"name": "Horaire, lent", "color": "#00b389", "dmx": 4},
                     {"name": "Horaire, rapide", "color": "#00b389", "dmx": 127},
                     {"name": "Antihoraire, lent", "color": "#00b389", "dmx": 128},
                     {"name": "Antihoraire, rapide", "color": "#00b389", "dmx": 255}],
         "Preset3": [{"name": "Arrêt", "color": "#888888", "dmx": 0},
                     {"name": "Doublure du motif", "color": "#009a78", "dmx": 64},
                     {"name": "Motif à pois", "color": "#009a78", "dmx": 128}],
         "Preset4": [{"name": "Arrêt", "color": "#888888", "dmx": 0},
                     {"name": "Dessin lent", "color": "#008168", "dmx": 1},
                     {"name": "Dessin rapide", "color": "#008168", "dmx": 255}],
     },
     "builtin": _B},

    # 36 canaux : DEUX dessins independants (motif A, canaux 1-19 ; motif B,
    # canaux 20-36) sur un seul appareil. Il n'existe pas 36 types distincts, et
    # doubler un type les gangerait : le motif A est entierement type, le motif B
    # garde `Gobo2` / `ColorWheel2` / `Gobo2Rot` et laisse le reste en `Unused`
    # NOMME, a pousser par numero de canal.
    # ⚠️ Le motif B ne s'affiche que si ses canaux 23 et 24 (position grossiere)
    # sont a 128 = milieu : c'est ce que dit la notice, et 0 fait sortir le
    # dessin du cadre. A monter a 50 % dans les canaux bruts avant de s'etonner
    # que B reste noir.
    {"name": "MAC 1000 RGB · Laser 36ch (motifs A+B)", "manufacturer": "Mac Mah", "fixture_type": "Moving Head", "group": "face",
     "profile": ["Dim", "Speed", "Preset1", "Gobo1", "Zoom", "Pan", "Tilt", "ColorWheel", "Preset2",
                 "Preset3", "Strobe", "Gobo1Rot", "Anim", "AnimRot", "Unused", "Unused", "Iris",
                 "Preset4", "Frost",
                 "Unused", "Gobo2", "Unused", "Unused", "Unused", "ColorWheel2", "Unused", "Unused",
                 "Unused", "Gobo2Rot", "Unused", "Unused", "Unused", "Unused", "Unused", "Unused",
                 "Unused"],
     "channel_labels": ["Intensité", "Vitesse auto / sensibilité micro",
                        "A · Bibliothèque de motifs", "A · Choix du motif", "A · Taille du motif",
                        "A · Position horizontale (128 = milieu)", "A · Position verticale (128 = milieu)",
                        "A · Couleur", "A · Vitesse de changement de couleur",
                        "A · Doublure / motif à pois", "A · Stroboscope", "A · Rotation du motif",
                        "A · Rotation horizontale", "A · Rotation verticale",
                        "A · Mouvement horizontal", "A · Mouvement vertical", "A · Zoom du motif",
                        "A · Dessin progressif", "A · Onde X / Onde Y",
                        "B · Bibliothèque de motifs", "B · Choix du motif", "B · Taille du motif",
                        "B · Position horizontale (128 = milieu)", "B · Position verticale (128 = milieu)",
                        "B · Couleur", "B · Vitesse de changement de couleur",
                        "B · Doublure / motif à pois", "B · Stroboscope", "B · Rotation du motif",
                        "B · Rotation horizontale", "B · Rotation verticale",
                        "B · Mouvement horizontal", "B · Mouvement vertical", "B · Zoom du motif",
                        "B · Dessin progressif", "B · Onde X / Onde Y"],
     "preset_slots": {
         "Preset1": [{"name": "Motifs statiques", "color": "#00cc99", "dmx": 0},
                     {"name": "Motifs dynamiques", "color": "#00cc99", "dmx": 64}],
         "Preset2": [{"name": "Arrêt", "color": "#888888", "dmx": 0},
                     {"name": "Horaire, lent", "color": "#00b389", "dmx": 4},
                     {"name": "Horaire, rapide", "color": "#00b389", "dmx": 127},
                     {"name": "Antihoraire, lent", "color": "#00b389", "dmx": 128},
                     {"name": "Antihoraire, rapide", "color": "#00b389", "dmx": 255}],
         "Preset3": [{"name": "Arrêt", "color": "#888888", "dmx": 0},
                     {"name": "Doublure du motif", "color": "#009a78", "dmx": 64},
                     {"name": "Motif à pois", "color": "#009a78", "dmx": 128}],
         "Preset4": [{"name": "Arrêt", "color": "#888888", "dmx": 0},
                     {"name": "Dessin lent", "color": "#008168", "dmx": 1},
                     {"name": "Dessin rapide", "color": "#008168", "dmx": 255}],
     },
     "builtin": _B},

]
