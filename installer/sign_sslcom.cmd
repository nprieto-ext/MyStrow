@echo off
rem Signe UN fichier avec SSL.com eSigner (CodeSignTool). Appelé par Inno
rem Setup (directive SignTool, cf. maestro.iss) pour CHAQUE fichier qu'il
rem signe : l'installeur ET sa copie temporaire setup.tmp (= le
rem désinstalleur). Signer l'installeur APRÈS Inno laissait setup.tmp non
rem signé → bloqué par le Contrôle intelligent des applications (Erreur 4551).
rem
rem Secrets lus dans l'environnement (jamais sur la ligne de commande, que
rem ISCC affiche dans le journal) : ES_USERNAME, ES_PASSWORD,
rem ES_CREDENTIAL_ID, ES_TOTP_SECRET. CST_ROOT = dossier de CodeSignTool.bat.
rem Code retour 1 si la signature échoue : Inno réessaie (SignToolRetryCount)
rem puis fait échouer la compilation.

if "%~1"=="" exit /b 2
pushd "%CST_ROOT%" || exit /b 1
call CodeSignTool.bat sign -username="%ES_USERNAME%" -password="%ES_PASSWORD%" -credential_id="%ES_CREDENTIAL_ID%" -totp_secret="%ES_TOTP_SECRET%" -input_file_path="%~1" -override=true > "%TEMP%\mystrow_cst.log" 2>&1
popd
type "%TEMP%\mystrow_cst.log"
rem CodeSignTool peut rendre 0 même en cas d'échec : on exige son message de succès.
findstr /C:"Code signed successfully" "%TEMP%\mystrow_cst.log" >nul || exit /b 1
exit /b 0
