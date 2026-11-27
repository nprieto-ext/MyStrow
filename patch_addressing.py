"""Calculs d'adressage du Patch DMX (19/11/2026), sans Qt pour être testables.

Un « appareil » (unit) = une fixture seule, ou une barre/matrice entière (tous
les membres d'un même matrix_id). Une barre se déplace d'un bloc, avec ses
écarts internes : la couper entre deux univers, ou remettre ses membres dans
l'ordre de création, décalerait ses têtes.
"""

N_UNIVERSES = 4      # U1 à U4, comme le sélecteur d'univers du patch
UNIVERSE_SIZE = 512


def patch_units(fixture_data, display_name=None):
    """Liste des appareils : {"members", "uni", "start", "end", "name"}."""
    units, by_mid = [], {}
    for i, fd in enumerate(fixture_data):
        s = fd.get('start_address', 1)
        e = s + max(1, len(fd.get('profile') or [])) - 1
        mid = fd.get('matrix_id')
        u = by_mid.get(mid) if mid is not None else None
        if u is None:
            name = str(fd.get('name') or '').split(" · ")[0]
            if not name and display_name:
                name = display_name(fd)
            u = {"members": [], "uni": fd.get('universe', 0), "start": s, "end": e, "name": name}
            units.append(u)
            if mid is not None:
                by_mid[mid] = u
        u["members"].append(i)
        u["start"], u["end"] = min(u["start"], s), max(u["end"], e)
    return units


def plan_auto_address(units):
    """Adresses continues, univers par univers, dans l'ordre actuel des adresses.

    Chaque appareil garde son univers ; un univers plein déborde dans le
    suivant (le reste de la file, dans l'ordre). Renvoie [(unit, uni, start)],
    ou None si tout ne tient pas dans N_UNIVERSES.
    """
    units = sorted(units, key=lambda u: (u["uni"], u["start"], u["members"][0]))
    plan, carry = [], []
    for uni in range(N_UNIVERSES):
        queue = carry + [u for u in units if u["uni"] == uni]
        carry, addr = [], 1
        for k, u in enumerate(queue):
            size = u["end"] - u["start"] + 1
            if addr + size - 1 > UNIVERSE_SIZE:
                carry = queue[k:]
                break
            plan.append((u, uni, addr))
            addr += size
    # Un appareil dans un univers au-delà de U4 (fichier ancien) : jamais placé.
    placed = {id(u) for u, _, _ in plan}
    if carry or any(id(u) not in placed for u in units):
        return None
    return plan


def plan_shift_following(units, anchor):
    """Pousse les appareils qui suivent `anchor` dans son univers, juste assez
    pour qu'ils ne se chevauchent plus ; les écarts voulus plus loin restent.

    Renvoie (moves, erreur) : moves = [(unit, nouvelle_adresse)], erreur =
    "no_room" si la chaîne dépasserait le canal 512 (rien n'est déplacé).
    """
    others = sorted((u for u in units if u is not anchor
                     and u["uni"] == anchor["uni"] and u["start"] >= anchor["start"]),
                    key=lambda u: (u["start"], u["members"][0]))
    cursor, moves = anchor["end"] + 1, []
    for u in others:
        size = u["end"] - u["start"] + 1
        if u["start"] < cursor:
            if cursor + size - 1 > UNIVERSE_SIZE:
                return [], "no_room"
            moves.append((u, cursor))
            cursor += size
        else:
            cursor = u["end"] + 1
    return moves, None


def next_free_slot(spans, size, uni=0):
    """Première adresse libre pour un appareil de `size` canaux (26/11/2026).

    spans = [(univers, début, fin)] des fixtures déjà patchées. On se place à
    la suite du dernier appareil de l'univers `uni` ; s'il n'y tient plus
    (fin > 512), on passe à l'univers suivant. Avant, l'ajout et la
    duplication continuaient à compter dans U1 : « U1 · CH 567–580 ».
    Renvoie (univers, adresse) ou None si U4 est plein lui aussi.
    """
    size = max(1, int(size))
    for u in range(max(0, uni), N_UNIVERSES):
        ends = [e for (uu, _s, e) in spans if uu == u]
        start = (max(ends) + 1) if ends else 1
        if start + size - 1 <= UNIVERSE_SIZE:
            return u, start
    return None
