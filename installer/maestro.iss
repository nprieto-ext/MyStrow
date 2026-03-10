[Setup]
AppName=MyStrow
AppVersion=3.0.11
AppPublisher=MyStrow
AppPublisherURL=https://mystrow.fr
DefaultDirName={autopf}\MyStrow
DefaultGroupName=MyStrow
OutputDir=installer_output
OutputBaseFilename=MyStrow_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\MyStrow.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\MyStrow.exe.sig"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\MyStrow"; Filename: "{app}\MyStrow.exe"
Name: "{commondesktop}\MyStrow"; Filename: "{app}\MyStrow.exe"

[Run]
Filename: "{app}\MyStrow.exe"; Description: "Lancer MyStrow"; Flags: nowait postinstall
