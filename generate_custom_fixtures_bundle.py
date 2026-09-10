"""
Génère fixtures_bundle_custom.json.gz — les fixtures de la bibliothèque MyStrow
(collection Firestore `gdtf_fixtures`), embarquées dans l'application.

Existait en trois exemplaires divergents : un heredoc PowerShell dans le job
Windows de release.yml, `release.py::_fetch_custom_fixtures_bundle()` pour le
build local… et RIEN côté macOS, où le `.spec` saute silencieusement le fichier
absent (`if os.path.exists`). Résultat : aucun build Mac n'a jamais embarqué les
fixtures ajoutées depuis l'admin panel.

`gdtf_fixtures` est en **lecture publique** (firestore.rules : `allow read: if
true`), au même titre que `controller_profiles` : aucun identifiant n'est
nécessaire. Le job Windows exigeait pourtant deux secrets et, s'ils manquaient,
écrivait un bundle VIDE sans faire échouer le build — une release amputée de
toute la bibliothèque, sans le moindre signal.

Usage :  python generate_custom_fixtures_bundle.py [chemin_de_sortie]
Sort TOUJOURS en code 0 et écrit TOUJOURS le fichier (bundle vide en cas
d'échec réseau) : les lignes `--add-data` du CI exigent qu'il existe.
"""

import gzip
import json
import sys
from pathlib import Path

OUT_FILE = Path(__file__).parent / "fixtures_bundle_custom.json.gz"


def _write(rows, out_path):
    data = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    with gzip.open(out_path, "wb") as gz:
        gz.write(data)


def build(out_path=OUT_FILE, token=None):
    """`token` reste facultatif : utile au build local, inutile en CI."""
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        import firebase_client as fc
        fixtures = fc.fetch_all_gdtf_fixtures(token)
    except Exception as e:
        print(f"AVERTISSEMENT: lecture de gdtf_fixtures échouée ({e}) — bundle vide généré.")
        _write([], out_path)
        return 0

    clean = []
    for fx in fixtures:
        f = {k: v for k, v in fx.items() if not k.startswith("_")}
        # Une fixture multi-modes ne porte pas toujours `profile` à la racine :
        # sans ce repli, le patch se retrouve sans canaux. Le heredoc du CI
        # Windows l'omettait, contrairement au build local.
        if not f.get("profile") and f.get("modes"):
            f["profile"] = f["modes"][0].get("profile", [])
        clean.append(f)

    _write(clean, out_path)
    print(f"OK {len(clean)} fixture(s) embarquee(s) dans {out_path.name} "
          f"({out_path.stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_FILE
    sys.exit(build(target))
