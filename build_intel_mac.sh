#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_intel_mac.sh  —  Build MyStrow_intel.dmg sur Mac Intel
#
# PREMIÈRE FOIS :
#   1. Cloner le dépôt sur le Mac Intel :
#        git clone https://github.com/nprieto-ext/MAESTRO.git MyStrow
#   2. Copier ce script dans le dossier MyStrow/ (ou il y est déjà)
#   3. Rendre exécutable :  chmod +x build_intel_mac.sh
#   4. Lancer :             bash build_intel_mac.sh
#
# FOIS SUIVANTES :
#   bash build_intel_mac.sh     ← pull auto + rebuild
#
# Résultat : ~/Desktop/MyStrow_intel.dmg
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="MyStrow"
DMG_NAME="MyStrow_intel.dmg"
DIST_DIR="$SCRIPT_DIR/dist"
DESKTOP="$HOME/Desktop"

# ── Couleurs terminales ───────────────────────────────────────────────────────
GRN="\033[0;32m"; YLW="\033[1;33m"; RED="\033[0;31m"; BLD="\033[1m"; NC="\033[0m"
step() { echo -e "\n${BLD}${GRN}=== $1 ===${NC}"; }
warn() { echo -e "${YLW}⚠   $1${NC}"; }
die()  { echo -e "${RED}✗   $1${NC}"; exit 1; }
ok()   { echo -e "${GRN}✓   $1${NC}"; }

# ── 0) Vérifications préalables ───────────────────────────────────────────────
step "Vérifications"

command -v python3 >/dev/null 2>&1 \
  || die "python3 introuvable. Installe Python 3.10+ : https://www.python.org/downloads/"
command -v git >/dev/null 2>&1 \
  || die "git introuvable. Lance : xcode-select --install"
command -v hdiutil >/dev/null 2>&1 \
  || die "hdiutil introuvable (devrait être présent nativement sur macOS)."

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ARCH=$(python3 -c "import platform; print(platform.machine())")
echo "Python $PY_VER  |  Arch : $ARCH"

[ "$ARCH" = "x86_64" ] || warn "Architecture détectée : $ARCH (attendu x86_64 pour un Mac Intel)"
[ -f "$SCRIPT_DIR/main.py" ] \
  || die "main.py introuvable. Lance ce script depuis la racine du projet MyStrow."

# ── 1) Git pull ───────────────────────────────────────────────────────────────
step "Récupération de la dernière version (git pull)"
cd "$SCRIPT_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  die "Ce dossier n'est pas un dépôt git. Clone d'abord le projet :\n  git clone https://github.com/nprieto-ext/MAESTRO.git MyStrow"
fi

git fetch origin 2>&1 | sed 's/^/    /'
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "")

if [ -z "$REMOTE" ]; then
  warn "Impossible de joindre origin/main — build avec la version locale."
elif [ "$LOCAL" = "$REMOTE" ]; then
  ok "Déjà à jour : $(git log -1 --pretty='%h — %s')"
else
  git pull origin main 2>&1 | sed 's/^/    /'
  ok "Mis à jour → $(git log -1 --pretty='%h — %s')"
fi

# Afficher la version de l'app
VERSION=$(python3 -c "
import re, sys
m = re.search(r'VERSION\s*=\s*\"(.*?)\"', open('core.py').read())
print(m.group(1) if m else '?')
" 2>/dev/null || echo "?")
echo "Version MyStrow : $VERSION"

# ── 2) Certificats SSL macOS ──────────────────────────────────────────────────
step "Certificats SSL"
# Sur macOS, Python (python.org) nécessite l'exécution de Install Certificates.command
# pour que pip et urllib puissent valider les certificats HTTPS.
CERT_CMD=$(find /Applications/Python* -name "Install Certificates.command" 2>/dev/null | sort -V | tail -1)
if [ -n "$CERT_CMD" ]; then
  echo "Exécution de : $CERT_CMD"
  bash "$CERT_CMD" 2>&1 | sed 's/^/    /' || true
  ok "Certificats installés"
else
  warn "Install Certificates.command introuvable (Python Homebrew ou déjà configuré)"
fi

# Installer certifi en premier avec --trusted-host pour amorcer si les certs manquent encore
python3 -m pip install certifi --quiet \
  --trusted-host pypi.org \
  --trusted-host files.pythonhosted.org \
  --trusted-host pypi.python.org 2>/dev/null || true

# Forcer le CA bundle certifi pour tous les appels SSL de ce script
SSL_CERT_FILE=$(python3 -m certifi 2>/dev/null || true)
if [ -n "$SSL_CERT_FILE" ]; then
  export SSL_CERT_FILE
  export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
  ok "CA bundle : $SSL_CERT_FILE"
fi

# ── 3) Dépendances Python ─────────────────────────────────────────────────────
step "Installation / mise à jour des dépendances"
python3 -m pip install --upgrade pip --quiet
python3 -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
python3 -m pip install pyinstaller --upgrade --quiet
ok "Dépendances prêtes"

# ── 4) Icône ──────────────────────────────────────────────────────────────────
step "Préparation de l'icône"
ICON_ARG=""

if [ -f "$SCRIPT_DIR/mystrow.icns" ]; then
  ICON_ARG="--icon=$SCRIPT_DIR/mystrow.icns"
  ok "mystrow.icns trouvé"
elif [ -f "$SCRIPT_DIR/mystrow.ico" ]; then
  echo "Conversion mystrow.ico → mystrow.icns…"
  _TMP_PNG="$SCRIPT_DIR/_icon_tmp.png"
  _ICONSET="$SCRIPT_DIR/MyStrow.iconset"
  # sips peut lire les .ico sur macOS
  if sips -s format png "$SCRIPT_DIR/mystrow.ico" --out "$_TMP_PNG" >/dev/null 2>&1 \
     && [ -f "$_TMP_PNG" ]; then
    mkdir -p "$_ICONSET"
    for sz in 16 32 64 128 256 512; do
      sips -z $sz $sz "$_TMP_PNG" --out "$_ICONSET/icon_${sz}x${sz}.png" >/dev/null 2>&1 || true
      [ $sz -le 256 ] && \
        sips -z $((sz*2)) $((sz*2)) "$_TMP_PNG" --out "$_ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1 || true
    done
    if iconutil -c icns "$_ICONSET" -o "$SCRIPT_DIR/mystrow.icns" 2>/dev/null; then
      ICON_ARG="--icon=$SCRIPT_DIR/mystrow.icns"
      ok "Icône convertie → mystrow.icns"
    else
      warn "iconutil a échoué — le build continuera sans icône"
    fi
    rm -f "$_TMP_PNG"; rm -rf "$_ICONSET"
  else
    warn "sips n'a pas pu lire mystrow.ico — build sans icône"
  fi
else
  warn "Aucune icône trouvée (mystrow.icns / mystrow.ico) — build sans icône"
fi

# ── 5) PyInstaller ────────────────────────────────────────────────────────────
step "PyInstaller — génération de l'app"
cd "$SCRIPT_DIR"
rm -rf "$DIST_DIR" "$SCRIPT_DIR/build"

# Construction des arguments PyInstaller
ARGS=(
  --onefile
  --windowed
  --add-data "logo.png:."
  --add-data "fixtures_qlcplus.json:."
  --add-data "plan_3d_web.html:."
  "--name=$APP_NAME"
  "--paths=$SCRIPT_DIR"
  --hidden-import=rtmidi
  --hidden-import=rtmidi._rtmidi
  --collect-all rtmidi
  --hidden-import=node_connection
  --hidden-import=brad_diagnostic
  --hidden-import=streamdeck_api
  --hidden-import=artnet_dmx
  --hidden-import=firebase_config
  --collect-all certifi
  --collect-all cryptography
  --collect-all serial
  --hidden-import=serial.tools.list_ports
  --noupx
  --noconfirm
  main.py
)

# Icône (optionnelle)
[ -n "$ICON_ARG" ] && ARGS=("$ICON_ARG" "${ARGS[@]}")

# Bundle fixtures custom si présent
[ -f "$SCRIPT_DIR/fixtures_bundle_custom.json.gz" ] && \
  ARGS=(--add-data "fixtures_bundle_custom.json.gz:." "${ARGS[@]}")

echo "Commande : python3 -m PyInstaller ${ARGS[*]}"
python3 -m PyInstaller "${ARGS[@]}"

APP_PATH="$DIST_DIR/$APP_NAME.app"
[ -d "$APP_PATH" ] || die "$APP_NAME.app non trouvé après PyInstaller."
ok "App générée : $APP_PATH"
echo "   Taille : $(du -sh "$APP_PATH" | cut -f1)"

# ── 6) Création du DMG ────────────────────────────────────────────────────────
step "Création du DMG"

# Dossier de staging : .app + raccourci Applications
STAGING=$(mktemp -d)
trap "rm -rf '$STAGING'" EXIT

cp -r "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

DMG_OUT="$DESKTOP/$DMG_NAME"
rm -f "$DMG_OUT"

hdiutil create \
  -volname "$APP_NAME $VERSION" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$DMG_OUT"

# ── 7) Résumé ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLD}${GRN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLD}${GRN}║  ✅  MyStrow_intel.dmg généré avec succès !      ║${NC}"
echo -e "${BLD}${GRN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Fichier : $DMG_OUT"
echo "  Taille  : $(du -sh "$DMG_OUT" | cut -f1)"
echo "  Version : $VERSION  |  Arch : $ARCH"
echo ""

# Ouvre le Bureau pour montrer le DMG
open "$DESKTOP"
