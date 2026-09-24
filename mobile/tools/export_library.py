"""Exporte la bibliothèque de fixtures du PC pour le patch de la tablette.

Mêmes sources que la bibliothèque de MyStrow sur PC :
  - builtin_fixtures.BUILTIN_FIXTURES   (fixtures natives)
  - fixtures_bundle.json.gz             (Open Fixture Library)
  - fixtures_bundle_custom.json.gz      (collection Firestore `gdtf_fixtures`,
                                          celle de l'admin panel)
  - fixtures_qlcplus.json               (QLC+ ; le PC en fait une entrée par
                                          mode, la tablette les range sous leur
                                          fixture)
La bibliothèque PERSO d'un PC (~/.mystrow_fixtures.json) n'en fait pas partie :
elle n'existe que sur ce poste.

La tablette ne lit JAMAIS de fichier MA / QLC+ / GDTF : elle reçoit des profils
déjà résolus (règle anti-divergence). Noms de canaux (core.canonical_profile) et
de fabricants (core.canonical_manufacturer) sont normalisés ici, avec les tables
du PC. Les tables elles-mêmes partent aussi dans le fichier : la tablette en a
besoin pour les fixtures qu'elle relit en direct dans Firestore.

    python mobile/tools/export_library.py     → mobile/src/library.js

À relancer avant chaque build de l'app (generate_custom_fixtures_bundle.py
d'abord, pour embarquer les dernières fixtures de l'admin).
"""
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

import core  # noqa: E402
from builtin_fixtures import BUILTIN_FIXTURES  # noqa: E402


def load_gz(name):
    path = os.path.join(REPO, name)
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def modes_of(fx):
    """[(nom du mode, profil canonique)] — même repli que le PC : `modes`, sinon `profile`."""
    out = []
    for m in fx.get("modes") or []:
        if isinstance(m, dict) and m.get("profile"):
            out.append([m.get("name") or f"{len(m['profile'])} canaux", core.canonical_profile(m["profile"])])
    if not out and fx.get("profile"):
        out.append([f"{len(fx['profile'])} canaux", core.canonical_profile(fx["profile"])])
    return out


def slim(fx, source):
    modes = modes_of(fx)
    if not modes:
        return None
    o = {"n": fx.get("name", "").strip(), "m": core.canonical_manufacturer(fx.get("manufacturer")),
         "t": fx.get("fixture_type") or "PAR LED", "s": source, "modes": modes}
    if fx.get("uuid"):
        o["u"] = fx["uuid"]
    if fx.get("color_wheel_slots"):
        o["cw"] = [{"dmx": int(s.get("dmx", 0)), "color": s.get("color", "#ffffff"), "name": s.get("name", "")}
                   for s in fx["color_wheel_slots"]]
    if fx.get("gobo_wheel_slots"):
        o["gb"] = [{"dmx": int(s.get("dmx", 0)), "name": s.get("name", "")} for s in fx["gobo_wheel_slots"]]
    return o


def main():
    fixtures = []
    for fx in BUILTIN_FIXTURES:
        s = slim(fx, "builtin")
        if s:
            fixtures.append(s)
    for fx in load_gz("fixtures_bundle.json.gz"):
        s = slim(fx, "ofl")
        if s:
            fixtures.append(s)
    for fx in load_gz("fixtures_bundle_custom.json.gz"):
        s = slim(fx, "firestore")
        if s:
            fixtures.append(s)
    # QLC+ en dernier, comme sur le PC : une fixture déjà présente sous le même
    # nom et le même fabricant n'est pas doublée.
    seen = {(f["n"].lower(), core._mfr_key(f["m"])) for f in fixtures}
    with open(os.path.join(REPO, "fixtures_qlcplus.json"), encoding="utf-8") as fh:
        for q in json.load(fh):
            key = ((q.get("model") or "").strip().lower(), core._mfr_key(core.canonical_manufacturer(q.get("manufacturer"))))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            s = slim({"name": q.get("model"), "manufacturer": q.get("manufacturer"),
                      "fixture_type": q.get("fixture_type"),
                      "modes": [{"name": m.get("name"), "profile": m.get("channels")} for m in q.get("modes") or []]},
                     "qlcplus")
            if s:
                fixtures.append(s)
    fixtures.sort(key=lambda f: (f["m"].lower(), f["n"].lower()))

    data = {
        "fixtures": fixtures,
        # Tables du PC, pour les fixtures relues en direct dans Firestore.
        "aliases": core.CHANNEL_ALIASES,
        "mfr": core._MFR_MAP,
        "wheelDefault": core.CW_DEFAULT_SLOTS,
    }
    out = os.path.join(REPO, "mobile", "src", "library.js")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("// GÉNÉRÉ par mobile/tools/export_library.py (bibliothèque de fixtures du PC).\n"
                 "// Ne pas modifier à la main : relancer le script.\n")
        fh.write("(function (root) {\n  const api = ")
        fh.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        fh.write(";\n  if (typeof module !== \"undefined\" && module.exports) module.exports = api;\n"
                 "  else root.MystrowLibrary = api;\n"
                 "})(typeof window !== \"undefined\" ? window : globalThis);\n")
    n_modes = sum(len(f["modes"]) for f in fixtures)
    print(f"{len(fixtures)} fixtures, {n_modes} modes → {os.path.relpath(out, REPO)} "
          f"({os.path.getsize(out) // 1024} Ko)")


if __name__ == "__main__":
    main()
