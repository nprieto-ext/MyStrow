@echo off
echo ============================================
echo  MyStrow — Installation plugin Stream Deck
echo ============================================
echo.

REM 1. Generer les icones
echo [1/3] Generation des icones...
python generate_icons.py
if errorlevel 1 (
    echo ERREUR : Python non trouve ou erreur Pillow.
    pause
    exit /b 1
)

REM 2. Copier le plugin dans le dossier Elgato
set PLUGIN_SRC=%~dp0com.mystrow.streamdeck.sdPlugin
set PLUGIN_DST=%APPDATA%\Elgato\StreamDeck\Plugins\com.mystrow.streamdeck.sdPlugin

echo.
echo [2/3] Installation du plugin...
if exist "%PLUGIN_DST%" (
    echo   Suppression ancienne version...
    rmdir /s /q "%PLUGIN_DST%"
)
xcopy /E /I /Q "%PLUGIN_SRC%" "%PLUGIN_DST%"
if errorlevel 1 (
    echo ERREUR : Impossible de copier le plugin.
    pause
    exit /b 1
)

echo.
echo [3/3] Plugin installe avec succes !
echo.
echo  Emplacement : %PLUGIN_DST%
echo.
echo  -> Redemarrez le logiciel Stream Deck
echo  -> MyStrow apparait dans la liste des actions
echo  -> Lancez MyStrow avant d'utiliser les boutons
echo.
pause
