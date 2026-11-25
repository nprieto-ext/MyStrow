@echo off
rem Signe UN fichier avec SSL.com eSigner (CodeSignTool). Appele par Inno
rem Setup (directive SignTool, cf. maestro.iss) pour CHAQUE fichier qu'il
rem signe : l'installeur ET sa copie temporaire setup.tmp (= le
rem desinstalleur). Signer l'installeur APRES Inno laissait setup.tmp non
rem signe -> bloque par le Controle intelligent des applications (Erreur 4551).
rem
rem Secrets lus dans l'environnement (jamais sur la ligne de commande, que
rem ISCC affiche dans le journal) : ES_USERNAME, ES_PASSWORD,
rem ES_CREDENTIAL_ID, ES_TOTP_SECRET. CST_ROOT = dossier de CodeSignTool.bat.
rem Code retour 1 si la signature echoue : Inno reessaie (SignToolRetryCount)
rem puis fait echouer la compilation.

if "%~1"=="" exit /b 2
rem CodeSignTool refuse les extensions qu'il ne connait pas (Inno lui passe
rem uninst.e32.tmp -> " Unsupported file format for signing - tmp ", 3.2.22) :
rem on signe une copie en .exe puis on la remet a la place de l'original.
set "MS_WORK=%TEMP%\mystrow_sign_%RANDOM%%RANDOM%.exe"
copy /y "%~1" "%MS_WORK%" >nul || exit /b 1
pushd "%CST_ROOT%" || exit /b 1
call "%CST_ROOT%\CodeSignTool.bat" sign -username="%ES_USERNAME%" -password="%ES_PASSWORD%" -credential_id="%ES_CREDENTIAL_ID%" -totp_secret="%ES_TOTP_SECRET%" -input_file_path="%MS_WORK%" -override=true > "%TEMP%\mystrow_cst.log" 2>&1
popd
type "%TEMP%\mystrow_cst.log"
rem CodeSignTool peut rendre 0 meme en cas d'echec : on exige son message de succes.
findstr /C:"Code signed successfully" "%TEMP%\mystrow_cst.log" >nul || (del "%MS_WORK%" 2>nul & exit /b 1)
copy /y "%MS_WORK%" "%~1" >nul || (del "%MS_WORK%" 2>nul & exit /b 1)
del "%MS_WORK%" 2>nul
exit /b 0
