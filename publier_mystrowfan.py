"""Publie dist_fan/MyStrowFan.exe : MyStrowFan chez Fanny propose alors la mise à jour.

    python publier_mystrowfan.py "Ce qui change (affiché à Fanny)"
    python publier_mystrowfan.py --build "..."   # reconstruit l'exe avant

Le fichier va dans Firebase Storage (mystrowfan/MyStrowFan-<version>.exe) avec un
jeton de téléchargement ; meta/mystrowfan reçoit {version, url, sha256, taille,
notes}, que la Cloud Function boitier_expeditions transmet à MyStrowFan (clé de
poste exigée). La version est lue dans mystrowfan.py : penser à l'augmenter.
"""
import hashlib
import re
import subprocess
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

from google.cloud import firestore, storage
from google.oauth2 import service_account

ICI = Path(__file__).resolve().parent
EXE = ICI / "dist_fan" / "MyStrowFan.exe"
PROJET = "mystrow-907be"
BUCKET = "mystrow-907be.firebasestorage.app"


def main():
    args = sys.argv[1:]
    build = "--build" in args
    args = [a for a in args if a != "--build"]
    notes = " ".join(args).strip()

    version = re.search(r'^VERSION = "([\d.]+)"', (ICI / "mystrowfan.py").read_text(encoding="utf-8"),
                        re.M).group(1)
    if build:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", "dist_fan",
                        "--workpath", "build_fan", "mystrowfan.spec"], cwd=ICI, check=True)
    if not EXE.exists():
        sys.exit(f"Introuvable : {EXE} (lance avec --build)")

    cred = service_account.Credentials.from_service_account_file(ICI / "service_account.json")
    db = firestore.Client(project=PROJET, credentials=cred)
    actuelle = (db.collection("meta").document("mystrowfan").get().to_dict() or {}).get("version")
    if actuelle == version:
        sys.exit(f"La version {version} est déjà publiée : augmente VERSION dans mystrowfan.py.")

    data = EXE.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    chemin = f"mystrowfan/MyStrowFan-{version}.exe"
    jeton = str(uuid.uuid4())
    blob = storage.Client(project=PROJET, credentials=cred).bucket(BUCKET).blob(chemin)
    blob.metadata = {"firebaseStorageDownloadTokens": jeton}
    print(f"Envoi de {chemin} ({len(data) / 1e6:.1f} Mo)…")
    blob.upload_from_filename(str(EXE), content_type="application/octet-stream", timeout=600)
    url = (f"https://firebasestorage.googleapis.com/v0/b/{BUCKET}/o/"
           f"{urllib.parse.quote(chemin, safe='')}?alt=media&token={jeton}")

    db.collection("meta").document("mystrowfan").set({
        "version": version, "url": url, "sha256": sha, "taille": len(data),
        "notes": notes, "publie_utc": time.time()})
    print(f"OK : MyStrowFan {version} publiée (avant : {actuelle or 'rien'}).")
    print("   Fanny verra le bandeau jaune à l'ouverture (ou dans les 5 min).")


if __name__ == "__main__":
    main()
