# Construit l'APK de test Android de l'app MyStrow.
#
#   powershell -ExecutionPolicy Bypass -File mobile\scripts\build-android.ps1
#
# Prérequis (une fois) :
#   - Node.js + `npm install` dans mobile\
#   - SDK Android dans %LOCALAPPDATA%\Android\Sdk (installé avec Android Studio)
#   - JDK 21 dans %LOCALAPPDATA%\MyStrowBuild\jdk21 : Gradle 8.14 (Capacitor 8)
#     ne tourne pas sur le Java 25 fourni avec Android Studio.
$ErrorActionPreference = 'Stop'
$mobile = Split-Path -Parent $PSScriptRoot

$env:JAVA_HOME = "$env:LOCALAPPDATA\MyStrowBuild\jdk21"
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
if (-not (Test-Path "$env:JAVA_HOME\bin\java.exe")) { throw "JDK 21 introuvable : $env:JAVA_HOME" }
if (-not (Test-Path $env:ANDROID_HOME)) { throw "SDK Android introuvable : $env:ANDROID_HOME" }

# Chemin du SDK pour Gradle (fichier propre à ce PC, ignoré par git).
$sdkDir = $env:ANDROID_HOME -replace '\\', '\\' -replace ':', '\:'
[System.IO.File]::WriteAllText((Join-Path $mobile 'android\local.properties'), "sdk.dir=$sdkDir`n")

Push-Location $mobile
try {
    npm run build
    if ($LASTEXITCODE) { throw "Échec de la copie de l'interface (npm run build)" }
    npx cap sync android
    if ($LASTEXITCODE) { throw "Échec de cap sync android" }
    Push-Location android
    try {
        # Mémoire bornée : sur un PC déjà chargé (MyStrow, navigateurs, Teams…),
        # les 1,5 Go + tâches parallèles par défaut faisaient tuer la compilation.
        .\gradlew.bat assembleDebug --no-daemon --max-workers=2 "-Dorg.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=512m"
        if ($LASTEXITCODE) { throw "Échec de la compilation Gradle" }
    } finally { Pop-Location }
} finally { Pop-Location }

$apk = Join-Path $mobile 'android\app\build\outputs\apk\debug\app-debug.apk'
Write-Host ""
Write-Host "APK prêt : $apk"
