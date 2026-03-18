[Setup]
AppName=MyStrow
AppVersion=3.0.45
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
; Règle firewall Windows — autorise MyStrow à envoyer/recevoir UDP Art-Net (port 6454)
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""MyStrow Art-Net"""; \
    Flags: runhidden waituntilterminated
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""MyStrow Art-Net"" dir=in action=allow protocol=UDP localport=6454 program=""{app}\MyStrow.exe"" enable=yes"; \
    Flags: runhidden waituntilterminated
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""MyStrow Art-Net Out"" dir=out action=allow protocol=UDP remoteport=6454 program=""{app}\MyStrow.exe"" enable=yes"; \
    Flags: runhidden waituntilterminated
Filename: "{app}\MyStrow.exe"; Description: "Lancer MyStrow"; Flags: nowait postinstall
