# Construit le paquet Google Play (.aab signé) de l'app MyStrow.
#
#   powershell -ExecutionPolicy Bypass -File mobile\scripts\build-android-release.ps1
#
# Mêmes prérequis que build-android.ps1, plus la clé d'envoi Google Play
# dans %USERPROFILE%\.mystrow-android\ (keystore.properties + mystrow-upload.jks).
# ⚠ Chaque envoi sur Google Play exige un versionCode plus grand
# (android\app\build.gradle) que le précédent.
$ErrorActionPreference = 'Stop'
$mobile = Split-Path -Parent $PSScriptRoot

$env:JAVA_HOME = "$env:LOCALAPPDATA\MyStrowBuild\jdk21"
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
if (-not (Test-Path "$env:JAVA_HOME\bin\java.exe")) { throw "JDK 21 introuvable : $env:JAVA_HOME" }
if (-not (Test-Path $env:ANDROID_HOME)) { throw "SDK Android introuvable : $env:ANDROID_HOME" }
if (-not (Test-Path "$env:USERPROFILE\.mystrow-android\keystore.properties")) { throw "Clé d'envoi introuvable : $env:USERPROFILE\.mystrow-android\keystore.properties" }

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
        .\gradlew.bat bundleRelease --no-daemon --max-workers=2 "-Dorg.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=512m"
        if ($LASTEXITCODE) { throw "Échec de la compilation Gradle" }
    } finally { Pop-Location }
} finally { Pop-Location }

$aab = Join-Path $mobile 'android\app\build\outputs\bundle\release\app-release.aab'
Write-Host ""
Write-Host "AAB prêt : $aab"
