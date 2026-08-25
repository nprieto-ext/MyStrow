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

datas = [('logo.png', '.'), ('mystrow.ico', '.'), ('plan_3d_web.html', '.')]
# Three.js vendorisé (vendor/three) : la 3D l'importe par chemin RELATIF au
# HTML, donc l'arbre doit être reproduit tel quel à côté de plan_3d_web.html.
# SANS ces fichiers, la fenêtre 3D reste bloquée sur « Chargement Three.js… »
# et l'échec est totalement silencieux.
for _root, _dirs, _files in os.walk(os.path.join('vendor', 'three')):
    for _f in _files:
        if _f.endswith('.js'):
            datas += [(os.path.join(_root, _f), _root)]
# Décors 3D des scènes par défaut (scenes3d/*.glb). Chargés par
# plan_3d_webwindow._push_scene_glb depuis _MEIPASS : absents de l'exe, les
# scènes « Scène de concert » et « Sono mobile » s'affichent vides, sans erreur
# visible — seulement une ligne dans la console.
for _root, _dirs, _files in os.walk('scenes3d'):
    for _f in _files:
        if _f.lower().endswith(('.glb', '.gltf')):
            datas += [(os.path.join(_root, _f), _root)]
# Interface tablette (PWA statique servie par tablet_server.py). SANS ces fichiers
# dans l'exe, le serveur tablette renvoie 404/500 ("Internal Server Error").
for _tf in ('index.html', 'manifest.json', 'sw.js'):
    if os.path.exists(os.path.join('tablet', _tf)):
        datas += [(os.path.join('tablet', _tf), 'tablet')]
if os.path.exists('fixtures_bundle_custom.json.gz'):
    datas += [('fixtures_bundle_custom.json.gz', '.')]
if os.path.exists('fixtures_qlcplus.json'):
    datas += [('fixtures_qlcplus.json', '.')]
binaries = []
# ffmpeg embarqué (décodage audio robuste, transparent : pas de ffmpeg requis
# dans le PATH client). Optionnel : ajouté seulement si le binaire est présent.
# C'est LUI qui donne l'ALAC, l'AIFF, l'Opus et le WMA à la forme d'onde et à
# l'IA Lumière (miniaudio s'arrête à wav/mp3/flac/ogg). Le CI Windows le
# télécharge avant le build ; sur macOS il faut déposer le binaire « ffmpeg »
# à côté du .spec, sinon ces formats se lisent mais ne s'analysent pas.
if os.path.exists('ffmpeg.exe'):
    binaries += [('ffmpeg.exe', '.')]
elif os.path.exists('ffmpeg'):
    binaries += [('ffmpeg', '.')]
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
# pygame : utilisé UNIQUEMENT comme pilote de manette (gamepad_client.py), pour
# le pan/tilt des lyres au stick. collect_all est nécessaire pour embarquer les
# binaires SDL2, sans lesquels l'import de pygame._sdl2.controller échoue dans
# l'exe alors qu'il passe en développement.
try:
    _r = collect_all('pygame')
    datas += _r[0]; binaries += _r[1]; hiddenimports += _r[2]
    hiddenimports += ['pygame._sdl2', 'pygame._sdl2.controller']
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
            # Réseau local (macOS 14+) — MÊME PIÈGE que le micro : sans cette
            # clé, macOS bloque silencieusement le broadcast/multicast UDP, donc
            # l'ArtPoll ne trouve jamais le node et la sortie Art-Net reste
            # muette. Aucune erreur affichée, juste « le boîtier n'a pas répondu ».
            'NSLocalNetworkUsageDescription':
                "MyStrow dialogue avec votre boîtier DMX Art-Net sur le réseau "
                "local (recherche du node et envoi des univers DMX).",
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
