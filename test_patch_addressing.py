import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_addressing as pa

def fx(name, n, addr, uni=0, **kw):
    d = {"name": name, "group": "A", "profile": ["X"] * n, "start_address": addr, "universe": uni}; d.update(kw); return d

def apply(fd_list, moves):
    for u, *rest in moves:
        uni, start = (rest if len(rest) == 2 else (u["uni"], rest[0]))
        d = start - u["start"]
        for i in u["members"]:
            fd_list[i]["universe"] = uni; fd_list[i]["start_address"] += d

def old_auto(fd_list):
    addr, uni = 1, 0
    for fd in fd_list:
        if addr + len(fd["profile"]) - 1 > 512: uni = min(uni + 1, 3); addr = 1
        fd["universe"], fd["start_address"] = uni, addr; addr += len(fd["profile"])

def conflicts(fd_list):
    occ = {}
    for i, fd in enumerate(fd_list):
        for c in range(fd["start_address"], fd["start_address"] + len(fd["profile"])):
            occ.setdefault((fd["universe"], c), []).append(i)
    return {i for l in occ.values() if len(l) > 1 for i in l}

ok = True
def check(label, cond):
    global ok; ok &= bool(cond); print(("OK  " if cond else "ÉCHEC ") + label)

# 1. Cas de Ronny : 3 lyres 9 canaux, une 4e insérée à l'adresse 10
P = [fx("Lyre 1", 9, 1), fx("Lyre 2", 9, 10), fx("Lyre 3", 9, 19), fx("Lyre 4", 9, 10)]
U = pa.patch_units(P); moves, err = pa.plan_shift_following(U, U[3]); apply(P, moves)
check("Ronny : Lyre 2 → 19, Lyre 3 → 28", [f["start_address"] for f in P] == [1, 19, 28, 10] and not conflicts(P))
# auto-adresse ensuite : garde l'ordre des adresses (la 4e reste en 2e position)
plan = pa.plan_auto_address(pa.patch_units(P)); apply(P, plan)
check("Auto Adresse suit l'ordre des adresses", [f["start_address"] for f in P] == [1, 19, 28, 10])

# 2. Un écart voulu plus loin est conservé
P = [fx("A", 10, 1), fx("B", 10, 11), fx("C", 10, 100), fx("N", 5, 11)]
U = pa.patch_units(P); moves, _ = pa.plan_shift_following(U, U[3]); apply(P, moves)
check("Écart conservé : B → 16, C reste à 100", P[1]["start_address"] == 16 and P[2]["start_address"] == 100)

# 3. Univers différents : le décalage ne touche que l'univers de l'appareil
P = [fx("A", 10, 1, 0), fx("B", 10, 5, 1), fx("N", 10, 1, 0)]
U = pa.patch_units(P); moves, _ = pa.plan_shift_following(U, U[2])
check("Décalage limité à l'univers", [u["name"] for u, _ in moves] == ["A"])

# 4. Plus de place : refus, rien ne bouge
P = [fx("A", 10, 500), fx("N", 10, 495)]
U = pa.patch_units(P); moves, err = pa.plan_shift_following(U, U[1])
check("Dépassement du canal 512 refusé", err == "no_room" and moves == [])

# 5. Barre de 49 canaux (bloc de contrôle APRÈS les pixels, créé en dernier) à cheval sur 512
def bar(addr, uni=0):
    m = [fx("Barre · Master", 4, addr, uni, matrix_id="b", matrix_role="master")]
    m += [fx(f"Barre · px{k+1}", 5, addr + 4 + 5 * k, uni, matrix_id="b", matrix_role="pixel") for k in range(8)]
    m += [fx("Barre · Master", 5, addr + 44, uni, matrix_id="b", matrix_role="master")]
    return m
P = [fx("PAR", 470, 1)] + bar(471)
old = [dict(f) for f in P]; old_auto(old)
check("ANCIEN : la barre est coupée entre U1 et U2", len({f["universe"] for f in old[1:]}) == 2)
plan = pa.plan_auto_address(pa.patch_units(P)); apply(P, plan)
offs = [f["start_address"] - P[1]["start_address"] for f in P[1:]]
check("NOUVEAU : barre entière en U2, canaux internes intacts",
      {f["universe"] for f in P[1:]} == {1} and P[1]["start_address"] == 1 and offs == [0] + [4 + 5 * k for k in range(8)] + [44])

# 6. Univers choisis par l'utilisateur (un node par côté de scène)
P = [fx("Jardin 1", 10, 1, 0), fx("Cour 1", 10, 1, 1), fx("Jardin 2", 10, 50, 0), fx("Cour 2", 10, 30, 1)]
old = [dict(f) for f in P]; old_auto(old)
check("ANCIEN : les appareils de U2 sont ramenés en U1", all(f["universe"] == 0 for f in old))
plan = pa.plan_auto_address(pa.patch_units(P)); apply(P, plan)
check("NOUVEAU : chacun garde son univers, adresses resserrées",
      [(f["universe"], f["start_address"]) for f in P] == [(0, 1), (1, 1), (0, 11), (1, 11)])

# 7. Débordement d'un univers plein vers le suivant
P = [fx(f"F{i}", 100, 1 + 100 * i) for i in range(6)] + [fx("G", 100, 1, 1)]
plan = pa.plan_auto_address(pa.patch_units(P)); apply(P, plan)
check("U1 plein : F5 passe en U2, avant G", [(f["universe"], f["start_address"]) for f in P][5:] == [(1, 1), (1, 101)])
check("…et aucun chevauchement", not conflicts(P))

# 8. Trop gros pour 4 univers
P = [fx(f"F{i}", 500, 1, 0) for i in range(5)]
old = [dict(f) for f in P]; old_auto(old)
check("ANCIEN : au-delà de U4, chevauchements", bool(conflicts(old)))
check("NOUVEAU : refus propre (rien modifié)", pa.plan_auto_address(pa.patch_units(P)) is None)

print("\nTOUT EST BON" if ok else "\nDES TESTS ÉCHOUENT")
