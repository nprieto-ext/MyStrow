[Setup]
AppName=MyStrow
AppVersion=3.1.88
AppPublisher=MyStrow
AppPublisherURL=https://mystrow.fr
DefaultDirName={autopf}\MyStrow
DefaultGroupName=MyStrow
OutputDir=installer_output
OutputBaseFilename=MyStrow_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

; --- Applications ouvertes -------------------------------------------------
; L'updater ferme MyStrow lui-meme et attend sa sortie avant de lancer Setup.
; Restart Manager reste le filet de secours si le processus tarde a mourir :
; il demande a MyStrow de se fermer au lieu d'afficher une page d'erreur.
CloseApplications=yes
; Ne PAS relancer nous-memes ce que Restart Manager a ferme : l'entree [Run]
; en fin de script relance deja MyStrow, on aurait deux instances.
RestartApplications=no

; --- Langues ---------------------------------------------------------------
; Sans section [Languages], Inno n'embarque que l'anglais : un utilisateur
; francais voyait donc les messages de Setup — dont celui des applications
; ouvertes — en anglais. L'updater passe /LANG= pour choisir la meme langue
; que l'application ; ShowLanguageDialog=no evite de la demander a quelqu'un
; qui lance l'installeur a la main.
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "..\dist\MyStrow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\streamdeck_plugin\com.mystrow.streamdeck.sdPlugin\*"; DestDir: "{userappdata}\Elgato\StreamDeck\Plugins\com.mystrow.streamdeck.sdPlugin"; Flags: ignoreversion recursesubdirs createallsubdirs

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
