# Met en ligne phone.html sur le serveur MyStrow Up (live.mystrow.fr).
# Pas de redémarrage : le relais relit la page à chaque visite, les shows en cours ne sont pas coupés.
#   Clic droit > Exécuter avec PowerShell, ou :  powershell -ExecutionPolicy Bypass -File mettre_en_ligne_phone.ps1

$ErrorActionPreference = "Stop"
$serveur = "root@37.27.153.144"
$cle     = "$env:USERPROFILE\.ssh\mystrow_live"
$local   = Join-Path $PSScriptRoot "phone.html"
$distant = "/opt/mystrow-live/phone.html"

if (-not (Test-Path $local)) { throw "phone.html introuvable à côté du script" }

# 1. Sauvegarde de la version en ligne
$date = Get-Date -Format "yyyyMMdd-HHmm"
Write-Host "1/3 Sauvegarde de la version en ligne -> phone.html.$date.bak"
ssh -i $cle $serveur "cp $distant $distant.$date.bak"
if ($LASTEXITCODE -ne 0) { throw "Sauvegarde impossible (connexion SSH ?)" }

# 2. Copie de la nouvelle version
Write-Host "2/3 Envoi de la nouvelle page"
scp -i $cle $local "${serveur}:$distant"
if ($LASTEXITCODE -ne 0) { throw "Envoi impossible" }
ssh -i $cle $serveur "chmod 644 $distant"

# 3. Vérification : la page servie doit être identique au fichier local
Write-Host "3/3 Vérification"
$attendu = (Get-FileHash $local -Algorithm SHA256).Hash.ToLower()
$enLigne = (ssh -i $cle $serveur "sha256sum $distant").Split(" ")[0]
$page    = (Invoke-WebRequest "https://live.mystrow.fr/live/testPAGE23" -UseBasicParsing).Content

if ($enLigne -eq $attendu -and $page -match "navigator\.languages") {
    Write-Host "OK : la nouvelle page est en ligne." -ForegroundColor Green
} else {
    Write-Host "ATTENTION : la page servie ne correspond pas au fichier envoyé." -ForegroundColor Red
    Write-Host "Pour revenir en arrière : ssh -i $cle $serveur `"cp $distant.$date.bak $distant`""
}
