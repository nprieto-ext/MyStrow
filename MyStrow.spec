# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_all

is_mac = sys.platform == "darwin"

# Lire la version depuis core.py
_ver = "3.0.0"
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("core", os.path.join(os.path.dirname(os.path.abspath(SPECPATH)), "core.py"))
    _mod = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_mod)
    _ver = _mod.VERSION
except Exception:
    pass

datas = [('logo.png', '.')]
if is_mac:
    if os.path.exists('mystrow.icns'):
        datas.append(('mystrow.icns', '.'))
else:
    if os.path.exists('mystrow.ico'):
        datas.append(('mystrow.ico', '.'))

binaries = []
hiddenimports = [
    'rtmidi', 'rtmidi._rtmidi', 'miniaudio',
    'serial', 'serial.tools', 'serial.tools.list_ports',
    'main_window', 'license_manager', 'license_ui',
    'node_connection', 'brad_diagnostic', 'artnet_dmx',
    'firebase_client', 'firebase_config', 'core',
    'sequencer', 'plan_de_feu', 'light_timeline',
    'timeline_editor', 'effect_editor', 'midi_handler',
    'ui_components', 'projector', 'audio_ai',
    'recording_waveform', 'updater',
]
tmp_ret = collect_all('rtmidi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('serial')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[SPECPATH],
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

# ── EXE en mode --onedir (exclude_binaries=True) ──────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MyStrow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='entitlements.plist' if is_mac else None,
    icon=['mystrow.icns'] if (is_mac and os.path.exists('mystrow.icns')) else (
        ['mystrow.ico'] if os.path.exists('mystrow.ico') else []
    ),
)

# ── COLLECT regroupe l'exe + bibliothèques + données ──────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MyStrow',
)

# ── macOS : bundle .app autour du dossier COLLECT ─────────────────────────────
if is_mac:
    app = BUNDLE(
        coll,
        name='MyStrow.app',
        icon='mystrow.icns' if os.path.exists('mystrow.icns') else None,
        bundle_identifier='fr.mystrow.app',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'LSApplicationCategoryType': 'public.app-category.music',
            'NSMicrophoneUsageDescription': 'MyStrow utilise le microphone pour la detection audio.',
            'NSBluetoothAlwaysUsageDescription': 'MyStrow peut se connecter a un controleur MIDI Bluetooth.',
            'NSBluetoothPeripheralUsageDescription': 'MyStrow peut se connecter a un controleur MIDI Bluetooth.',
            'CFBundleShortVersionString': _ver,
            'CFBundleVersion': _ver,
            'NSHighResolutionCapable': True,
        },
        entitlements_file='entitlements.plist',
    )
