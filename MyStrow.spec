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

datas = [('logo.png', '.'), ('mystrow.ico', '.'), ('plan_3d_web.html', '.'), ('AKAIAPCMINI.png', '.'), ('Novation.png', '.')]
if os.path.exists('fixtures_bundle_custom.json.gz'):
    datas += [('fixtures_bundle_custom.json.gz', '.')]
if os.path.exists('fixtures_qlcplus.json'):
    datas += [('fixtures_qlcplus.json', '.')]
binaries = []
hiddenimports = ['rtmidi', 'rtmidi._rtmidi', 'miniaudio', 'sounddevice', '_sounddevice', '_sounddevice_data', 'pyaudiowpatch', '_pyaudio']
tmp_ret = collect_all('rtmidi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# sounddevice + DLLs PortAudio
for _pkg in ('sounddevice', '_sounddevice_data'):
    try:
        _r = collect_all(_pkg)
        datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]
    except Exception:
        pass
# Inclure les DLLs PortAudio manuellement (au cas où collect_all ne les attrape pas)
try:
    import _sounddevice_data, os as _os
    _pa_dir = _os.path.join(_os.path.dirname(_sounddevice_data.__file__), 'portaudio-binaries')
    for _dll in _os.listdir(_pa_dir):
        if _dll.endswith('.dll'):
            binaries += [(_os.path.join(_pa_dir, _dll), '_sounddevice_data/portaudio-binaries')]
except Exception:
    pass
for _pkg in ('pyaudiowpatch',):
    try:
        _r = collect_all(_pkg)
        datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]
    except Exception:
        pass
for _pkg in ('serial', 'flask', 'flask_socketio', 'qrcode', 'waitress', 'werkzeug', 'jinja2', 'click', 'itsdangerous', 'markupsafe'):
    try:
        _r = collect_all(_pkg)
        datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]
    except Exception:
        pass
# ftd2xx : wrapper Python du driver FTDI D2XX (ENTTEC Open DMX USB en direct,
# comme QLC+). La DLL ftd2xx elle-même provient du driver FTDI installé sur le
# poste (chargée par ctypes au runtime) — on n'embarque que le module Python.
if sys.platform == 'win32':
    try:
        _r = collect_all('ftd2xx')
        datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]
    except Exception:
        pass

# ------------------------------------------------------------------
# BACKEND VIDÉO FFmpeg (décodage matériel) — CRUCIAL pour les longues
# vidéos (spectacles 40 min). Sans le plugin multimedia ffmpeg ET ses DLL
# codec, l'exe retombe sur le backend Windows (WMF) qui sature le thread UI
# (lecture saccadée, lumière décalée). On embarque explicitement le plugin
# + les DLL FFmpeg pour garantir le décodage GPU dans l'app packagée.
# ------------------------------------------------------------------
try:
    import PySide6 as _PS, glob as _glob
    _ps_dir = os.path.dirname(_PS.__file__)
    _mm_dir = os.path.join(_ps_dir, 'plugins', 'multimedia')
    if os.path.isdir(_mm_dir):
        for _f in os.listdir(_mm_dir):
            if _f.lower().endswith('.dll'):
                binaries += [(os.path.join(_mm_dir, _f), os.path.join('PySide6', 'plugins', 'multimedia'))]
    # DLL FFmpeg requises par ffmpegmediaplugin (avcodec/avformat/avutil/sw*).
    for _pat in ('avcodec*', 'avformat*', 'avutil*', 'swscale*', 'swresample*', 'avdevice*', 'avfilter*'):
        for _dll in _glob.glob(os.path.join(_ps_dir, _pat + '.dll')):
            binaries += [(_dll, 'PySide6')]
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
        target_arch=None,           # natif du runner (arm64 sur macos-15, x86_64 sur macos-13)
        codesign_identity=None,
        entitlements_file='entitlements.plist',   # réseau, audio-input, USB MIDI, disable-library-validation
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
            # Capture audio (mode LIVE / IA Lumière) — SANS cette clé, macOS bloque
            # silencieusement l'accès micro/ligne/BlackHole → aucun signal capté.
            'NSMicrophoneUsageDescription':
                "MyStrow capte le son pour synchroniser vos lumières en temps réel "
                "(mode LIVE / IA Lumière).",
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
