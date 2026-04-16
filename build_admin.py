"""
Build script pour AdminPanel MyStrow.
Génère un exe autonome dans dist/AdminPanel/

Usage :
    python build_admin.py
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DIST_DIR = BASE_DIR / "dist" / "AdminPanel"
BUILD_DIR = BASE_DIR / "build" / "AdminPanel"
SPEC_FILE = BASE_DIR / "admin_panel.spec"

# ── Fichiers de données à copier à côté de l'exe ──────────────────────────────
DATA_FILES = [
    "service_account.json",
    "gdtf_config.py",     # secret GDTF sync
    "smtp_config.py",     # identifiants SMTP
]

# ── Dépendances cachées que PyInstaller ne détecte pas seul ──────────────────
HIDDEN_IMPORTS = [
    "firebase_admin",
    "firebase_admin.auth",
    "firebase_admin.credentials",
    "firebase_admin.firestore",
    "firebase_admin._auth_utils",
    "firebase_admin._token_gen",
    "firebase_admin._http_client",
    "firebase_admin.exceptions",
    "google.auth",
    "google.auth.transport",
    "google.auth.transport.requests",
    "google.oauth2",
    "google.oauth2.credentials",
    "google.oauth2.service_account",
    "google.cloud.firestore",
    "google.cloud.firestore_v1",
    "google.api_core",
    "google.protobuf",
    "grpc",
    "certifi",
    "email_sender",
    "firebase_client",
    "blog_panel",
    "admin_pack_editor",
    "gdtf_config",
    "smtp_config",
    "core",
]

# ── Modules locaux à ajouter explicitement ───────────────────────────────────
LOCAL_MODULES = [
    "firebase_client.py",
    "core.py",
    "email_sender.py",
    "blog_panel.py",
    "admin_pack_editor.py",
    "gdtf_config.py",
    "smtp_config.py",
]

# ── Données à embarquer dans le bundle ───────────────────────────────────────
def get_datas():
    import certifi
    datas = [
        # Certificats SSL (requis pour HTTPS / Firebase)
        (certifi.where(), "certifi"),
        # service_account Firebase Admin SDK
        (str(BASE_DIR / "service_account.json"), "."),
        # Logo
        (str(BASE_DIR / "logo.png"), "."),
    ]
    # Modules locaux embarqués comme données ET comme modules
    for m in LOCAL_MODULES:
        p = BASE_DIR / m
        if p.exists():
            datas.append((str(p), "."))
    return datas


def write_spec():
    datas_str = ",\n        ".join(
        f"({repr(src)}, {repr(dst)})" for src, dst in get_datas()
    )
    hidden_str = ", ".join(repr(h) for h in HIDDEN_IMPORTS)

    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
# Généré par build_admin.py

block_cipher = None

a = Analysis(
    [{repr(str(BASE_DIR / "admin_panel.py"))}],
    pathex=[{repr(str(BASE_DIR))}],
    binaries=[],
    datas=[
        {datas_str}
    ],
    hiddenimports=[{hidden_str}],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "scipy", "PIL", "tkinter",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AdminPanel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon={repr(str(BASE_DIR / "mystrow.ico"))},
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AdminPanel",
)
"""
    SPEC_FILE.write_text(spec_content, encoding="utf-8")
    print(f"[OK] Spec ecrit : {SPEC_FILE}")


def build():
    print("[BUILD] Build AdminPanel en cours...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller",
         "--clean",
         "--noconfirm",
         str(SPEC_FILE)],
        cwd=str(BASE_DIR),
    )
    if result.returncode != 0:
        print("[ERREUR] Build echoue.")
        sys.exit(1)
    print(f"\n[OK] Build termine -> {DIST_DIR}")


def post_build():
    """Copie les fichiers sensibles à côté de l'exe (non embarqués dans le bundle)."""
    if not DIST_DIR.exists():
        return
    for fname in DATA_FILES:
        src = BASE_DIR / fname
        if src.exists():
            shutil.copy2(src, DIST_DIR / fname)
            print(f"   [+] Copie : {fname}")


if __name__ == "__main__":
    write_spec()
    build()
    post_build()
    print(f"\n[DONE] Lance : {DIST_DIR / 'AdminPanel.exe'}")
