# -*- mode: python ; coding: utf-8 -*-
import sys
import os
import re
from PyInstaller.utils.hooks import collect_all

def _get_version():
    try:
        txt = open('core.py', encoding='utf-8').read()
        m = re.search(r'VERSION\s*=\s*"(.*?)"', txt)
        return m.group(1) if m else '0.0.0'
    except Exception:
        return '0.0.0'

datas = [('logo.png', '.'), ('mystrow.ico', '.')]
if os.path.exists('fixtures_bundle_custom.json.gz'):
    datas += [('fixtures_bundle_custom.json.gz', '.')]
if os.path.exists('fixtures_qlcplus.json'):
    datas += [('fixtures_qlcplus.json', '.')]
binaries = []
hiddenimports = ['rtmidi', 'rtmidi._rtmidi', 'miniaudio']
tmp_ret = collect_all('rtmidi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
for _pkg in ('flask', 'flask_socketio', 'qrcode', 'waitress', 'werkzeug', 'jinja2', 'click', 'itsdangerous', 'markupsafe'):
    try:
        _r = collect_all(_pkg)
        datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]
    except Exception:
        pass

IS_MAC = sys.platform == 'darwin'
icon_file = 'mystrow.icns' if (IS_MAC and os.path.exists('mystrow.icns')) else 'mystrow.ico'

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if IS_MAC:
    # ── macOS : --onefile + BUNDLE ───────────────────────────────────────────
    # Sur macOS 26 Tahoe, le bootloader PyInstaller (onedir) ne trouve jamais
    # _internal/ à côté de l'exécutable et tombe en fallback $TMPDIR/_MEI.../Python.
    # En onefile le PKG est embarqué dans l'EXE → extraction dans $TMPDIR réussit.
    # cs.disable-library-validation (entitlements.plist) autorise le chargement
    # des dylibs non-signés extraits dans $TMPDIR.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,         # tout embarqué → onefile
        a.datas,
        [],
        name='MyStrow',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,          # UPX brise les headers Mach-O
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch='arm64',  # Apple Silicon natif (Rosetta 2 pour Intel)
        codesign_identity=None,
        entitlements_file=None,
        icon=[icon_file],
    )
    app = BUNDLE(
        exe,                # onefile : BUNDLE directement sur l'EXE, sans COLLECT
        name='MyStrow.app',
        icon=icon_file,
        bundle_identifier='com.mystrow.app',
        info_plist={
            # Identité du bundle
            'CFBundleName':                         'MyStrow',
            'CFBundleDisplayName':                  'MyStrow',
            'CFBundleExecutable':                   'MyStrow',
            'CFBundlePackageType':                  'APPL',
            'CFBundleInfoDictionaryVersion':        '6.0',
            'CFBundleShortVersionString':           _get_version(),
            'CFBundleVersion':                      _get_version(),
            # macOS minimum — évite le rejet silencieux sur Big Sur
            'LSMinimumSystemVersion':               '11.0',
            # Classe principale Qt — requis par macOS 26 Tahoe
            'NSPrincipalClass':                     'NSApplication',
            # Rendu & affichage
            'NSHighResolutionCapable':              True,
            'NSSupportsAutomaticGraphicsSwitching': True,
            'NSRequiresAquaSystemAppearance':       False,
            # Sécurité / état restaurable (macOS 12+)
            'NSApplicationSupportsSecureRestorableState': True,
        },
    )

else:
    # ── Windows / Linux : --onefile ──────────────────────────────────────────
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='MyStrow',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=[icon_file],
    )
