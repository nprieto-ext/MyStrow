#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_intel_mac.sh  —  Build MyStrow_intel.dmg sur Mac Intel (signé + notarisé)
#
# PREMIÈRE FOIS :
#   1. Cloner le dépôt :  git clone https://github.com/nprieto-ext/MAESTRO.git MyStrow
#   2. Stocker les credentials de notarisation dans le trousseau (une seule fois) :
#        xcrun notarytool store-credentials "mystrow-notarize" \
#          --apple-id "ton@apple.id" \
#          --team-id "TONTEAMID" \
#          --password "xxxx-xxxx-xxxx-xxxx"   ← app-specific password
#   3. chmod +x build_intel_mac.sh
#   4. bash build_intel_mac.sh
#
# FOIS SUIVANTES : bash build_intel_mac.sh
#
# Le script se SYNCHRONISE d'abord sur origin/main (git reset --hard) : il est
# donc IMPOSSIBLE de builder une vieille version, et inutile de faire git pull
# avant. Il s'auto-localise (peut être lancé par chemin absolu depuis n'importe
# où) et UPLOADE automatiquement le DMG sur la GitHub Release (via gh).
#
# Astuce (une seule fois, pour le lancer de partout sans se tromper de dossier) :
#   echo "alias mystrow-release='bash \"$(pwd)/build_intel_mac.sh\"'" >> ~/.zshrc
#   source ~/.zshrc
#   → ensuite, taper simplement :  mystrow-release
#
# Résultat : ~/Desktop/MyStrow_intel.dmg  (signé + notarisé + uploadé)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="MyStrow"
DMG_NAME="MyStrow_intel.dmg"
DIST_DIR="$SCRIPT_DIR/dist"
DESKTOP="$HOME/Desktop"
NOTARY_PROFILE="mystrow-notarize"   # nom du profil créé avec notarytool store-credentials
GITHUB_REPO="nprieto-ext/MAESTRO"   # repo des releases (upload automatique du DMG)

# ── Couleurs terminales ───────────────────────────────────────────────────────
GRN="\033[0;32m"; YLW="\033[1;33m"; RED="\033[0;31m"; BLD="\033[1m"; NC="\033[0m"
step() { echo -e "\n${BLD}${GRN}=== $1 ===${NC}"; }
warn() { echo -e "${YLW}⚠   $1${NC}"; }
die()  { echo -e "${RED}✗   $1${NC}"; exit 1; }
ok()   { echo -e "${GRN}✓   $1${NC}"; }

# ── 0) Vérifications préalables ───────────────────────────────────────────────
step "Vérifications"

command -v python3  >/dev/null 2>&1 || die "python3 introuvable. Installe Python 3.10+ : https://www.python.org/downloads/"
command -v git      >/dev/null 2>&1 || die "git introuvable. Lance : xcode-select --install"
command -v codesign >/dev/null 2>&1 || die "codesign introuvable. Lance : xcode-select --install"

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ARCH=$(python3 -c "import platform; print(platform.machine())")
echo "Python $PY_VER  |  Arch : $ARCH"

[ "$ARCH" = "x86_64" ] || warn "Architecture détectée : $ARCH (attendu x86_64 pour un Mac Intel)"
[ -f "$SCRIPT_DIR/main.py" ] || die "main.py introuvable. Lance ce script depuis la racine du projet MyStrow."

# Détecter l'identité de signature Developer ID
IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null \
  | grep "Developer ID Application" | head -1 | awk '{print $2}' || true)
if [ -n "$IDENTITY" ]; then
  ok "Identité de signature : $IDENTITY"
else
  warn "Aucun certificat 'Developer ID Application' trouvé — le DMG ne sera PAS signé."
  warn "L'app affichera l'avertissement Gatekeeper à l'ouverture."
fi

# Vérifier si le profil de notarisation existe
NOTARY_OK=false
if xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
  NOTARY_OK=true
  ok "Profil notarisation '$NOTARY_PROFILE' trouvé"
else
  warn "Profil notarisation '$NOTARY_PROFILE' introuvable — l'app ne sera pas notarisée."
  warn "Pour configurer (une seule fois) :"
  warn "  xcrun notarytool store-credentials '$NOTARY_PROFILE' --apple-id TON@APPLE.ID --team-id TEAMID --password APP-PASSWORD"
fi

# ── 1) Synchronisation Git — GARANTIT la dernière version ─────────────────────
# On force le working tree à correspondre EXACTEMENT à origin/main (reset --hard).
# → impossible de builder une vieille version, et plus besoin de `git pull` ni de
#   `git checkout MyStrow.spec` avant : toute modif locale (spec, etc.) est écrasée.
#   Ce Mac est une machine de build dédiée, l'écrasement est voulu.
step "Synchronisation sur origin/main (dernière version)"
cd "$SCRIPT_DIR"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || die "Ce dossier n'est pas un dépôt git : $SCRIPT_DIR"

git fetch origin 2>&1 | sed 's/^/    /'
REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "")

if [ -z "$REMOTE" ]; then
  warn "Impossible de joindre origin/main — build avec la version locale."
else
  git reset --hard origin/main 2>&1 | sed 's/^/    /'
  ok "Synchronisé sur origin/main → $(git log -1 --pretty='%h — %s')"
fi

VERSION=$(python3 -c "
import re
m = re.search(r'VERSION\s*=\s*\"(.*?)\"', open('core.py').read())
print(m.group(1) if m else '?')
" 2>/dev/null || echo "?")
echo "Version MyStrow : $VERSION"

# ── 2) Certificats SSL macOS ──────────────────────────────────────────────────
step "Certificats SSL"
CERT_CMD=$(find /Applications/Python* -name "Install Certificates.command" 2>/dev/null | sort -V | tail -1)
if [ -n "$CERT_CMD" ]; then
  bash "$CERT_CMD" 2>&1 | sed 's/^/    /' || true
  ok "Certificats installés"
else
  warn "Install Certificates.command introuvable (Python Homebrew ou déjà configuré)"
fi

python3 -m pip install certifi --quiet \
  --trusted-host pypi.org --trusted-host files.pythonhosted.org \
  --trusted-host pypi.python.org 2>/dev/null || true

SSL_CERT_FILE=$(python3 -m certifi 2>/dev/null || true)
[ -n "$SSL_CERT_FILE" ] && export SSL_CERT_FILE && export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE" && ok "CA bundle : $SSL_CERT_FILE"

# ── 3) Dépendances Python ─────────────────────────────────────────────────────
step "Installation / mise à jour des dépendances"
python3 -m pip install --upgrade pip --quiet
python3 -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
python3 -m pip install pyinstaller --upgrade --quiet
ok "Dépendances prêtes"

# ── 4) Icône ──────────────────────────────────────────────────────────────────
step "Préparation de l'icône"
if [ ! -f "$SCRIPT_DIR/mystrow.icns" ] && [ -f "$SCRIPT_DIR/logo.png" ]; then
  echo "Génération mystrow.icns depuis logo.png…"
  _ICONSET="$SCRIPT_DIR/MyStrow.iconset"
  mkdir -p "$_ICONSET"
  for sz in 16 32 64 128 256 512; do
    sips -z $sz $sz "$SCRIPT_DIR/logo.png" --out "$_ICONSET/icon_${sz}x${sz}.png"   >/dev/null 2>&1 || true
    sips -z $((sz*2)) $((sz*2)) "$SCRIPT_DIR/logo.png" --out "$_ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1 || true
  done
  iconutil -c icns "$_ICONSET" -o "$SCRIPT_DIR/mystrow.icns" 2>/dev/null && ok "mystrow.icns généré" || warn "iconutil échoué"
  rm -rf "$_ICONSET"
fi
[ -f "$SCRIPT_DIR/mystrow.icns" ] && ok "Icône : mystrow.icns" || warn "Pas d'icône"

# ── 5) PyInstaller ────────────────────────────────────────────────────────────
step "PyInstaller — génération de l'app"
cd "$SCRIPT_DIR"
rm -rf "$DIST_DIR" "$SCRIPT_DIR/build"

# Utiliser le .spec si disponible (identique au CI), sinon fallback ligne de commande
if [ -f "$SCRIPT_DIR/MyStrow.spec" ]; then
  echo "Utilisation de MyStrow.spec"
  python3 -m PyInstaller --noconfirm "$SCRIPT_DIR/MyStrow.spec"
else
  ARGS=(
    --onefile --windowed
    --add-data "logo.png:." --add-data "fixtures_qlcplus.json:." --add-data "plan_3d_web.html:."
    --add-data "vendor/three:vendor/three"
    # Decors 3D des scenes par defaut : sans eux les presets a modele retombent
    # sur une scene vide, sans message visible.
    --add-data "scenes3d:scenes3d"
    --add-data "AKAIAPCMINI.png:." --add-data "Novation.png:."
    "--name=$APP_NAME" "--paths=$SCRIPT_DIR"
    --hidden-import=rtmidi --hidden-import=rtmidi._rtmidi --collect-all rtmidi
    --hidden-import=node_connection --hidden-import=brad_diagnostic
    --hidden-import=streamdeck_api --hidden-import=artnet_dmx --hidden-import=firebase_config
    --collect-all certifi --collect-all cryptography --collect-all serial
    --hidden-import=serial.tools.list_ports --noupx --noconfirm main.py
  )
  [ -f "$SCRIPT_DIR/mystrow.icns" ] && ARGS=("--icon=$SCRIPT_DIR/mystrow.icns" "${ARGS[@]}")
  [ -f "$SCRIPT_DIR/fixtures_bundle_custom.json.gz" ] && \
    ARGS=("--add-data" "fixtures_bundle_custom.json.gz:." "${ARGS[@]}")
  python3 -m PyInstaller "${ARGS[@]}"
fi

APP_PATH="$DIST_DIR/$APP_NAME.app"
[ -d "$APP_PATH" ] || die "$APP_NAME.app non trouvé après PyInstaller."
ok "App générée : $APP_PATH  ($(du -sh "$APP_PATH" | cut -f1))"

# Supprimer le binaire brut dist/MyStrow (onefile EXE hors bundle)
# create-dmg emballe tout dist/ — ce fichier non-signé ferait échouer la notarisation
if [ -f "$DIST_DIR/$APP_NAME" ]; then
  rm -f "$DIST_DIR/$APP_NAME"
  ok "Binaire brut dist/$APP_NAME supprimé (hors bundle)"
fi

# ── 6) Signature codesign ─────────────────────────────────────────────────────
if [ -n "$IDENTITY" ]; then
  step "Signature de l'app"

  # Entitlements PyInstaller : nécessaires pour le chargement dynamique de code
  ENTS="$SCRIPT_DIR/entitlements.plist"
  if [ ! -f "$ENTS" ]; then
    cat > "$ENTS" <<'EOPLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
</dict>
</plist>
EOPLIST
    ok "entitlements.plist généré"
  fi

  # Signer tous les binaires et frameworks internes individuellement
  find "$APP_PATH/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm +111 \) | while read f; do
    codesign --sign "$IDENTITY" --force --options runtime --timestamp \
      --entitlements "$ENTS" "$f" 2>/dev/null || true
  done

  # Signer le bundle complet
  codesign --sign "$IDENTITY" --force --options runtime --timestamp \
    --entitlements "$ENTS" "$APP_PATH"

  codesign --verify --verbose "$APP_PATH" 2>&1 | sed 's/^/    /'
  ok "App signée"
fi

# ── 7) Création du DMG ────────────────────────────────────────────────────────
step "Création du DMG"
DMG_OUT="$DESKTOP/$DMG_NAME"
rm -f "$DMG_OUT"

if command -v create-dmg >/dev/null 2>&1; then
  create-dmg \
    --volname "$APP_NAME $VERSION" \
    --window-pos 200 120 --window-size 600 400 \
    --icon-size 100 \
    --icon "$APP_NAME.app" 150 190 \
    --app-drop-link 450 190 \
    "$DMG_OUT" "$DIST_DIR/"
else
  # Fallback hdiutil si create-dmg absent
  warn "create-dmg absent — utilisation de hdiutil (installe avec : brew install create-dmg)"
  STAGING=$(mktemp -d)
  trap "rm -rf '$STAGING'" EXIT
  cp -r "$APP_PATH" "$STAGING/"
  ln -s /Applications "$STAGING/Applications"
  hdiutil create -volname "$APP_NAME $VERSION" -srcfolder "$STAGING" -ov -format UDZO "$DMG_OUT"
fi

ok "DMG créé : $DMG_OUT"

# ── 8) Signature du DMG ───────────────────────────────────────────────────────
if [ -n "$IDENTITY" ]; then
  step "Signature du DMG"
  if codesign --sign "$IDENTITY" --timestamp "$DMG_OUT" 2>/dev/null; then
    ok "DMG signé"
  else
    warn "Signature du DMG ignorée (trousseau verrouillé) — l'app intérieure est signée, la notarisation fonctionnera quand même"
  fi
fi

# ── 9) Notarisation ───────────────────────────────────────────────────────────
if [ "$NOTARY_OK" = true ]; then
  step "Notarisation (envoi à Apple — peut prendre 1-5 min)"
  NOTARY_JSON=$(xcrun notarytool submit "$DMG_OUT" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait --output-format json)
  echo "$NOTARY_JSON" | sed 's/^/    /'

  STATUS=$(echo "$NOTARY_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
  if [ "$STATUS" = "Accepted" ]; then
    xcrun stapler staple "$DMG_OUT"
    ok "Notarisé et agrafé ✓"
  else
    SUBMISSION_ID=$(echo "$NOTARY_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
    [ -n "$SUBMISSION_ID" ] && \
      xcrun notarytool log "$SUBMISSION_ID" --keychain-profile "$NOTARY_PROFILE" 2>&1 | sed 's/^/    /'
    die "Notarisation refusée par Apple (status: $STATUS)"
  fi
fi

# ── 9b) Upload automatique sur la GitHub Release ──────────────────────────────
step "Upload sur la GitHub Release (v$VERSION)"
TAG="v$VERSION"
UPLOAD_OK=false
if [ "$VERSION" = "?" ]; then
  warn "Version inconnue (core.py illisible) — upload ignoré, upload le DMG à la main."
elif ! command -v gh >/dev/null 2>&1; then
  warn "GitHub CLI 'gh' introuvable — upload ignoré."
  warn "  Installe-le une fois : brew install gh && gh auth login"
elif ! gh auth status >/dev/null 2>&1; then
  warn "'gh' non authentifié — upload ignoré. Lance : gh auth login  puis relance."
else
  # La release est créée par le CI au moment de la sortie. Comme on lance ce
  # script APRÈS, elle existe en général déjà ; on laisse quand même quelques
  # tentatives au cas où le CI finirait juste.
  for attempt in 1 2 3 4 5 6; do
    if gh release view "$TAG" --repo "$GITHUB_REPO" >/dev/null 2>&1; then
      if gh release upload "$TAG" "$DMG_OUT" --repo "$GITHUB_REPO" --clobber 2>&1 | sed 's/^/    /'; then
        UPLOAD_OK=true
        ok "DMG uploadé sur la release $TAG"
        echo "  https://github.com/$GITHUB_REPO/releases/tag/$TAG"
      fi
      break
    fi
    warn "Release $TAG pas encore publiée — nouvelle tentative dans 20 s ($attempt/6)…"
    sleep 20
  done
  [ "$UPLOAD_OK" = true ] || \
    warn "Upload non effectué (release $TAG absente ?) — vérifie que la version est bien sortie, puis relance ou upload le DMG à la main."
fi

# ── 10) Résumé ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLD}${GRN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLD}${GRN}║  ✅  MyStrow_intel.dmg prêt !                            ║${NC}"
echo -e "${BLD}${GRN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Fichier  : $DMG_OUT"
echo "  Taille   : $(du -sh "$DMG_OUT" | cut -f1)"
echo "  Version  : $VERSION  |  Arch : $ARCH"
[ -n "$IDENTITY" ]    && echo "  Signé    : ✓" || echo "  Signé    : ✗ (certificat manquant)"
[ "$NOTARY_OK" = true ] && echo "  Notarisé : ✓" || echo "  Notarisé : ✗ (profil '$NOTARY_PROFILE' non configuré)"
[ "$UPLOAD_OK" = true ] && echo "  Upload   : ✓ release $TAG" || echo "  Upload   : ✗ (à faire à la main)"
echo ""

open "$DESKTOP"
