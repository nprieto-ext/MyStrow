"""
Génère fixtures_bundle.json.gz - bundle compressé de TOUTES les fixtures OFL.
Usage : python generate_bundle.py
Produit : fixtures_bundle.json.gz (à inclure dans l'installeur)
"""
import json, gzip, zipfile, io, urllib.request, sys, time
from pathlib import Path
from ofl_parser import parse_ofl_json

OFL_ZIP_URL = "https://github.com/OpenLightingProject/open-fixture-library/archive/refs/heads/master.zip"
OUT_FILE    = Path(__file__).parent / "fixtures_bundle.json.gz"

def fetch_zip(url):
    print("Téléchargement OFL depuis GitHub...")
    req = urllib.request.Request(url, headers={"User-Agent": "MyStrow-bundler"})
    with urllib.request.urlopen(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length", 0))
        buf = b""
        downloaded = 0
        chunk = 65536
        t0 = time.time()
        while True:
            block = r.read(chunk)
            if not block:
                break
            buf += block
            downloaded += len(block)
            if total:
                pct = downloaded * 100 // total
                mb = downloaded / 1024 / 1024
                print(f"\r  {pct}% ({mb:.1f} MB)...", end="", flush=True)
    print(f"\r  Téléchargé {len(buf)/1024/1024:.1f} MB en {time.time()-t0:.1f}s       ")
    return buf

def main():
    raw = fetch_zip(OFL_ZIP_URL)
    zf  = zipfile.ZipFile(io.BytesIO(raw))

    # Lire manufacturers.json
    mfr_path = next(n for n in zf.namelist() if n.endswith("fixtures/manufacturers.json"))
    prefix   = mfr_path[: mfr_path.index("fixtures/manufacturers.json")]
    mfrs     = json.loads(zf.read(mfr_path).decode("utf-8"))

    # Lister tous les fichiers fixture
    fixture_paths = [
        n for n in zf.namelist()
        if n.startswith(prefix + "fixtures/")
        and n.endswith(".json")
        and not n.endswith("manufacturers.json")
        and n.count("/") == prefix.count("/") + 2  # prefix/fixtures/mfr/fixture.json
    ]

    print(f"Fixtures à parser : {len(fixture_paths)}")

    all_fixtures = []
    errors = 0

    for i, path in enumerate(fixture_paths):
        # path: prefix/fixtures/mfr_key/fixture_key.json
        parts        = path.split("/")
        fixture_key  = parts[-1].replace(".json", "")
        mfr_key      = parts[-2]
        mfr_name     = mfrs.get(mfr_key, {}).get("name", mfr_key)

        try:
            data = zf.read(path)
            fx   = parse_ofl_json(data, mfr_key, fixture_key, mfr_name)
            all_fixtures.append(fx)
        except Exception as e:
            errors += 1

        if (i + 1) % 50 == 0 or (i + 1) == len(fixture_paths):
            print(f"\r  Parsé {i+1}/{len(fixture_paths)} ({errors} erreurs)...", end="", flush=True)

    print(f"\n\nTotal : {len(all_fixtures)} fixtures parsées, {errors} erreurs ignorées.")

    # Trier par fabricant puis nom
    all_fixtures.sort(key=lambda f: (f["manufacturer"].lower(), f["name"].lower()))

    # Écrire bundle compressé
    payload = json.dumps(all_fixtures, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(OUT_FILE, "wb", compresslevel=9) as gz:
        gz.write(payload)

    raw_kb  = len(payload) // 1024
    gz_kb   = OUT_FILE.stat().st_size // 1024
    print(f"Bundle écrit : {OUT_FILE.name}")
    print(f"  JSON brut : {raw_kb} KB  →  compressé : {gz_kb} KB")

if __name__ == "__main__":
    main()
