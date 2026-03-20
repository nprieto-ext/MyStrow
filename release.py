import subprocess
import sys
import re
import shutil
import hashlib
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "core.py"
ISS_FILE = BASE_DIR / "installer" / "maestro.iss"
DESKTOP = Path.home() / "Desktop"

# ------------------------------------------------------------------
# UTIL
# ------------------------------------------------------------------

def run(cmd, allow_fail=False):
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0 and not allow_fail:
        print("Erreur detectee. Arret.")
        sys.exit(1)

def get_current_version():
    content = CONFIG_FILE.read_text(encoding="utf-8")
    match = re.search(r'VERSION\s*=\s*"(.*?)"', content)
    return match.group(1) if match else None

def bump_version(current):
    """Auto-increment patch version: 2.5.3 -> 2.5.4"""
    parts = current.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)

def update_version(new_version):
    # Update core.py
    content = CONFIG_FILE.read_text(encoding="utf-8")
    content = re.sub(
        r'VERSION\s*=\s*"(.*?)"',
        f'VERSION = "{new_version}"',
        content,
    )
    CONFIG_FILE.write_text(content, encoding="utf-8")

    # Update installer .iss
    iss_content = ISS_FILE.read_text(encoding="utf-8")
    iss_content = re.sub(
        r'AppVersion=.*',
        f'AppVersion={new_version}',
        iss_content,
    )
    ISS_FILE.write_text(iss_content, encoding="utf-8")

# ------------------------------------------------------------------
# BUILD LOCAL EXE
# ------------------------------------------------------------------

def generate_sig_file(exe_path):
    """Genere MyStrow.exe.sig (hash SHA256 + signature Ed25519)"""
    sha256 = hashlib.sha256()
    with open(exe_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    exe_hash = sha256.hexdigest()

    signature = ""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        _KS = b"MC4CAQAwBQYDK2VwBCIEIO4dq7bapt3BQlEKe5aYxrP0aH9KbiN/Xdc/oij6uMQm"
        pem = b"-----BEGIN PRIVATE KEY-----\n" + _KS + b"\n-----END PRIVATE KEY-----\n"
        private_key = load_pem_private_key(pem, password=None)
        signature = private_key.sign(exe_hash.encode()).hex()
    except Exception as e:
        print(f"Avertissement: signature .sig non generee ({e})")

    sig_path = Path(str(exe_path) + ".sig")
    sig_path.write_text(json.dumps({"hash": exe_hash, "signature": signature}))
    print(f"Fichier .sig genere : {sig_path}")
    return sig_path


def build_local_installer(version):
    print("\n========== BUILD INSTALLEUR LOCAL ==========")
    dist_exe = BASE_DIR / "dist" / "MyStrow" / "MyStrow.exe"
    installer_out = BASE_DIR / "installer" / "installer_output" / "MyStrow_Setup.exe"

    # 1) Nettoyage des anciens builds
    for d in ["dist", "build"]:
        p = BASE_DIR / d
        if p.exists():
            shutil.rmtree(p)

    # 2) Build EXE via un .bat execute par cmd.exe (contourne MINGW64)
    print("\n--- PyInstaller ---")
    python_win = sys.executable.replace("/", "\\")
    base_win = str(BASE_DIR).replace("/", "\\")

    bat_path = BASE_DIR / "_build_tmp.bat"
    bat_path.write_text(
        f"@echo off\n"
        f"cd /d \"{base_win}\"\n"
        f"\"{python_win}\" -m PyInstaller "
        f"--onedir --windowed "
        f"--icon=mystrow.ico "
        f"--add-data \"logo.png;.\" "
        f"--add-data \"mystrow.ico;.\" "
        f"--name=MyStrow "
        f"--paths=\"{base_win}\" "
        f"--hidden-import=rtmidi "
        f"--hidden-import=rtmidi._rtmidi "
        f"--collect-all rtmidi "
        f"--hidden-import=node_connection "
        f"--hidden-import=brad_diagnostic "
        f"--hidden-import=streamdeck_api "
        f"--hidden-import=artnet_dmx "
        f"--hidden-import=firebase_config "
        f"--collect-all certifi "
        f"--collect-all cryptography "
        f"--collect-all serial "
        f"--hidden-import=serial.tools.list_ports "
        f"--noupx "
        f"--noconfirm main.py\n"
    )

    result = subprocess.run(
        ["cmd.exe", "/c", str(bat_path).replace("/", "\\")],
        cwd=str(BASE_DIR),
    )
    bat_path.unlink(missing_ok=True)

    if result.returncode != 0:
        print("ERREUR PyInstaller. Arret.")
        sys.exit(1)

    if not dist_exe.exists():
        print("ERREUR: MyStrow.exe non trouve apres PyInstaller.")
        sys.exit(1)

    # Generer le fichier .sig (requis par check_exe_integrity)
    generate_sig_file(dist_exe)

    # 3) Build installeur avec Inno Setup
    print("\n--- Inno Setup ---")
    iscc_paths = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        "ISCC",  # si dans le PATH
    ]
    iscc = next((p for p in iscc_paths if Path(p).exists() or p == "ISCC"), None)
    if not iscc:
        print("ERREUR: Inno Setup (ISCC.exe) introuvable.")
        sys.exit(1)

    result = subprocess.run(
        f'"{iscc}" installer\\maestro.iss',
        shell=True, cwd=BASE_DIR
    )
    if result.returncode != 0:
        print("ERREUR Inno Setup. Arret.")
        sys.exit(1)

    if not installer_out.exists():
        print("ERREUR: MyStrow_Setup.exe non trouve apres Inno Setup.")
        sys.exit(1)

    # 4) Copie de l'installeur sur le Bureau
    dest = DESKTOP / f"MyStrow_Setup_{version}.exe"
    shutil.copy2(installer_out, dest)
    print(f"\nInstalleur copie sur le bureau : {dest}")


def build_admin_panel_exe():
    print("\n========== BUILD ADMIN PANEL EXE ==========")
    dist_exe = BASE_DIR / "dist" / "MyStrow_Admin.exe"

    # Nettoyage partiel (garder dist si MyStrow.exe deja build)
    build_dir = BASE_DIR / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)

    print("\n--- PyInstaller (admin_panel) ---")
    python_win = sys.executable.replace("/", "\\")
    base_win = str(BASE_DIR).replace("/", "\\")

    bat_path = BASE_DIR / "_build_admin_tmp.bat"
    bat_path.write_text(
        f"@echo off\n"
        f"cd /d \"{base_win}\"\n"
        f"\"{python_win}\" -m PyInstaller "
        f"--onefile --windowed "
        f"--icon=mystrow.ico "
        f"--add-data \"logo.png;.\" "
        f"--add-data \"mystrow.ico;.\" "
        f"--name=MyStrow_Admin "
        f"--paths=\"{base_win}\" "
        f"--hidden-import=firebase_admin "
        f"--hidden-import=firebase_admin.credentials "
        f"--hidden-import=firebase_admin.auth "
        f"--hidden-import=firebase_admin._auth_utils "
        f"--hidden-import=firebase_admin._http_client "
        f"--hidden-import=google.auth "
        f"--hidden-import=google.auth.transport.requests "
        f"--hidden-import=google.oauth2 "
        f"--hidden-import=google.oauth2.service_account "
        f"--hidden-import=smtp_config "
        f"--hidden-import=_socket "
        f"--hidden-import=socket "
        f"--collect-all firebase_admin "
        f"--collect-all google.auth "
        f"--noconfirm admin_panel.py\n"
    )

    result = subprocess.run(
        ["cmd.exe", "/c", str(bat_path).replace("/", "\\")],
        cwd=str(BASE_DIR),
    )
    bat_path.unlink(missing_ok=True)

    if result.returncode != 0:
        print("ERREUR PyInstaller admin_panel. Arret.")
        sys.exit(1)

    if not dist_exe.exists():
        print("ERREUR: MyStrow_Admin.exe non trouve apres PyInstaller.")
        sys.exit(1)

    # Copie sur le Bureau
    dest = DESKTOP / "MyStrow_Admin.exe"
    shutil.copy2(dist_exe, dest)
    print(f"\nAdmin panel copie sur le bureau : {dest}")
    print("IMPORTANT: Placer service_account.json dans le meme dossier que l'exe.")


# ------------------------------------------------------------------
# SUIVI GITHUB ACTIONS
# ------------------------------------------------------------------

GITHUB_REPO = "nprieto-ext/MAESTRO"


def _gh_api(path):
    """Appel API GitHub (sans auth, limite 60 req/h)"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}{path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MyStrow-Release"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _watch_github_actions(version):
    from datetime import datetime
    tag = f"v{version}"
    ICONS = {"queued": "⏳", "in_progress": "🔄"}
    CONCLUSION_ICONS = {"success": "✅", "failure": "❌", "cancelled": "⚠️",
                        "skipped": "⏭️", None: "🔄"}

    print("\nAttente du démarrage de GitHub Actions", end="", flush=True)

    # Attendre que le workflow apparaisse (max 60s)
    run_id = None
    for _ in range(30):
        time.sleep(2)
        data = _gh_api("/actions/runs?event=push&per_page=10")
        if data:
            for wr in data.get("workflow_runs", []):
                commit_msg = wr.get("head_commit", {}).get("message", "")
                if wr.get("name") == "Build & Release" and version in commit_msg:
                    run_id = wr["id"]
                    break
            if not run_id:
                for wr in data.get("workflow_runs", []):
                    if wr.get("name") == "Build & Release" and wr.get("status") in ("queued", "in_progress"):
                        run_id = wr["id"]
                        break
        if run_id:
            break
        print(".", end="", flush=True)

    if not run_id:
        print(f"\n\nImpossible de trouver le workflow. Suivi manuel :")
        print(f"  https://github.com/{GITHUB_REPO}/actions")
        return

    print(f"\n\nWorkflow démarré → https://github.com/{GITHUB_REPO}/actions/runs/{run_id}\n")

    last_jobs_state = {}
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spin_i = 0

    while True:
        time.sleep(5)

        run_data = _gh_api(f"/actions/runs/{run_id}")
        if not run_data:
            continue

        status     = run_data.get("status", "")
        conclusion = run_data.get("conclusion")

        jobs_data = _gh_api(f"/actions/runs/{run_id}/jobs")
        jobs = jobs_data.get("jobs", []) if jobs_data else []

        jobs_state = {j["name"]: (j["status"], j.get("conclusion")) for j in jobs}
        if jobs_state != last_jobs_state:
            print(f"  Build & Release  {spinner[spin_i % len(spinner)]}")
            for job in jobs:
                name    = job["name"]
                jstatus = job["status"]
                jconc   = job.get("conclusion")
                if jstatus == "completed":
                    icon = CONCLUSION_ICONS.get(jconc, "❓")
                else:
                    icon = ICONS.get(jstatus, "⏳")
                duration = ""
                if jstatus == "completed" and job.get("started_at") and job.get("completed_at"):
                    t1 = datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
                    secs = int((t2 - t1).total_seconds())
                    duration = f"  ({secs//60}m{secs%60:02d}s)"
                print(f"    {icon}  {name}{duration}")
            last_jobs_state = jobs_state

        spin_i += 1

        if status == "completed":
            print()
            if conclusion == "success":
                print(f"✅  Release v{version} créée avec succès !")
                print(f"    https://github.com/{GITHUB_REPO}/releases/tag/{tag}")
            else:
                print(f"❌  Build échoué (conclusion: {conclusion})")
                print(f"    https://github.com/{GITHUB_REPO}/actions/runs/{run_id}")
            break


# ------------------------------------------------------------------
# RELEASE
# ------------------------------------------------------------------

def main():
    print("========== RELEASE MYSTROW ==========")

    current_version = get_current_version()
    print(f"Version actuelle : {current_version}")

    new_version = input(f"Nouvelle version ? [{bump_version(current_version)}] : ").strip()
    if not new_version:
        new_version = bump_version(current_version)

    print("\nQue veux-tu faire ?")
    print("  1) Installeur local seulement (Bureau)")
    print("  2) Push GitHub seulement (CI build)")
    print("  3) Les deux")
    print("  4) Admin panel exe seulement (Bureau)")
    choix = input("Choix [3] : ").strip() or "3"

    if choix not in ("1", "2", "3", "4"):
        print("Choix invalide. Arret.")
        sys.exit(1)

    if choix == "4":
        build_admin_panel_exe()
        return

    print(f"\nMise a jour vers {new_version}...")
    update_version(new_version)

    if choix in ("1", "3"):
        build_local_installer(new_version)

    if choix in ("2", "3"):
        run("git add -A")
        run(f'git commit -m "Release {new_version}"', allow_fail=True)
        run(f"git tag v{new_version}")
        run("git push origin main")
        run(f"git push origin v{new_version}")
        print(f"\n========== TAG v{new_version} POUSSE ==========")
        _watch_github_actions(new_version)


if __name__ == "__main__":
    main()
