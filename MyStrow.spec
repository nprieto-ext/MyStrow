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

if IS_MAC:
    app = BUNDLE(
        exe,
        name='MyStrow.app',
        icon=icon_file,
        bundle_identifier='com.mystrow.app',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': _get_version(),
        },
    )
