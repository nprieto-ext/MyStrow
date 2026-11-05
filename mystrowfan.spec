# -*- mode: python ; coding: utf-8 -*-
# MyStrowFan : poste de preparation des boitiers (un seul .exe).
B = r'C:\Users\nikop\Desktop\MyStrow\Medias\Boitier'
a = Analysis(
    ['mystrowfan.py'],
    pathex=[r'C:\Users\nikop\Desktop\MyStrow\App'],
    binaries=[(B + r'\chaine\wchisp\wchisp-win-x64\wchisp.exe', 'outils')],
    datas=[
        (B + r'\firmware\build\mystrow_dmx.bin', 'outils'),
        (B + r'\chaine\zadig-2.9.exe', 'outils'),
        ('logo.png', '.'),
    ],
    hiddenimports=['serial', 'serial.tools.list_ports', 'boitier_init'],
    excludes=['firebase_admin', 'google', 'grpc', 'matplotlib', 'numpy', 'scipy',
              'PIL', 'tkinter', 'PySide6.QtWebEngineCore', 'PySide6.Qt3DCore'],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MyStrowFan',
          console=False, upx=False, icon='mystrow.ico')
