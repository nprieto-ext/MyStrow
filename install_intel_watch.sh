#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# install_intel_watch.sh  —  Installe le veilleur du build Mac Intel
#
# À lancer UNE SEULE FOIS sur le Mac Intel, depuis le dossier du projet :
#   bash install_intel_watch.sh
#
# Ensuite, ce Mac construit et publie MyStrow_intel.dmg tout seul dès qu'une
# nouvelle release sort. Plus rien à lancer à la main.
#
# Conditions pour que ça marche :
#   • le Mac est allumé et la session ouverte (le certificat de signature vit
#     dans le trousseau de session : un Mac au login n'y a pas accès) ;
#   • le trousseau n'est pas verrouillé ;
#   • `gh` est installé et connecté.
# Le Mac peut dormir : launchd rattrape le passage manqué au réveil.
#
# Pour désinstaller :
#   launchctl unload -w ~/Library/LaunchAgents/com.mystrow.intelwatch.plist
#   rm ~/Library/LaunchAgents/com.mystrow.intelwatch.plist
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.mystrow.intelwatch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
STATE_DIR="$HOME/.mystrow_intel_watch"
INTERVAL=600           # secondes entre deux vérifications (10 min)
NOTARY_PROFILE="mystrow-notarize"

GRN="\033[0;32m"; YLW="\033[1;33m"; RED="\033[0;31m"; BLD="\033[1m"; NC="\033[0m"
step() { echo -e "\n${BLD}${GRN}=== $1 ===${NC}"; }
warn() { echo -e "${YLW}⚠   $1${NC}"; }
die()  { echo -e "${RED}✗   $1${NC}"; exit 1; }
ok()   { echo -e "${GRN}✓   $1${NC}"; }

# ── Vérifications ─────────────────────────────────────────────────────────────
step "Vérifications"

[ "$(uname)" = "Darwin" ] || die "Ce script s'installe sur un Mac."
[ -f "$SCRIPT_DIR/intel_watch.sh" ]     || die "intel_watch.sh introuvable dans $SCRIPT_DIR"
[ -f "$SCRIPT_DIR/build_intel_mac.sh" ] || die "build_intel_mac.sh introuvable dans $SCRIPT_DIR"
ok "Scripts trouvés dans $SCRIPT_DIR"

ARCH=$(uname -m)
[ "$ARCH" = "x86_64" ] || warn "Architecture $ARCH (attendu x86_64 : c'est le Mac INTEL qui doit héberger ce veilleur)"

# gh : indispensable, c'est lui qui lit les releases ET qui envoie le DMG.
if ! command -v gh >/dev/null 2>&1; then
  die "GitHub CLI absent. Lance : brew install gh && gh auth login   puis relance ce script."
elif ! gh auth status >/dev/null 2>&1; then
  die "GitHub CLI non connecté. Lance : gh auth login   puis relance ce script."
else
  ok "GitHub CLI connecté"
fi

# Signature / notarisation : sans elles le build marche quand même, mais le DMG
# publié déclencherait l'avertissement Gatekeeper chez les clients. On prévient
# maintenant plutôt qu'au premier build automatique, à 2 h du matin.
if security find-identity -v -p codesigning 2>/dev/null | grep -q "Developer ID Application"; then
  ok "Certificat Developer ID présent"
else
  warn "Aucun certificat 'Developer ID Application' — les DMG publiés ne seront PAS signés."
fi

if xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
  ok "Profil de notarisation '$NOTARY_PROFILE' présent"
else
  warn "Profil de notarisation '$NOTARY_PROFILE' absent — les DMG ne seront PAS notarisés."
  warn "  xcrun notarytool store-credentials '$NOTARY_PROFILE' --apple-id TON@APPLE.ID --team-id TEAMID --password APP-PASSWORD"
fi

command -v create-dmg >/dev/null 2>&1 || warn "create-dmg absent (brew install create-dmg) — repli sur hdiutil, DMG moins joli"

chmod +x "$SCRIPT_DIR/intel_watch.sh" "$SCRIPT_DIR/build_intel_mac.sh" 2>/dev/null || true
mkdir -p "$STATE_DIR/logs" "$HOME/Library/LaunchAgents"

# ── Copie du veilleur hors du dépôt ───────────────────────────────────────────
# Le build fait `git reset --hard` sur le tag de la release : tout fichier absent
# de cette version disparaît du dossier. Lancé depuis le dépôt, le veilleur
# s'effacerait donc lui-même au premier build et launchd ne trouverait plus rien.
# Il tourne depuis $STATE_DIR et se remet à jour tout seul depuis le dépôt.
echo "$SCRIPT_DIR" > "$STATE_DIR/repo_dir"
cp "$SCRIPT_DIR/intel_watch.sh" "$STATE_DIR/intel_watch.sh"
chmod +x "$STATE_DIR/intel_watch.sh"
ok "Veilleur copié hors du dépôt : $STATE_DIR/intel_watch.sh"
ok "Dépôt surveillé : $SCRIPT_DIR"

# ── Tâche de fond launchd ─────────────────────────────────────────────────────
step "Installation de la tâche de fond"

# Déchargement d'abord : réinstaller par-dessus une tâche active la laisserait
# tourner avec l'ancien chemin.
launchctl unload -w "$PLIST" >/dev/null 2>&1 || true

cat > "$PLIST" <<EOPLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$STATE_DIR/intel_watch.sh</string>
    </array>

    <!-- Toutes les 10 minutes. Si le Mac dormait, launchd rattrape au réveil. -->
    <key>StartInterval</key>
    <integer>$INTERVAL</integer>

    <!-- Un passage dès l'ouverture de session : une release sortie pendant que
         le Mac était éteint est rattrapée sans attendre. -->
    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$STATE_DIR/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$STATE_DIR/launchd.err.log</string>

    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
</dict>
</plist>
EOPLIST

ok "Tâche écrite : $PLIST"

launchctl load -w "$PLIST" 2>&1 | sed 's/^/    /'
if launchctl list | grep -q "$LABEL"; then
  ok "Veilleur actif (vérification toutes les $((INTERVAL / 60)) min)"
else
  die "launchctl n'a pas chargé la tâche — regarde $STATE_DIR/launchd.err.log"
fi

# ── Résumé ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLD}${GRN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLD}${GRN}║  ✅  Veilleur installé — ce Mac se débrouille tout seul   ║${NC}"
echo -e "${BLD}${GRN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Il vérifie GitHub toutes les $((INTERVAL / 60)) minutes et construit le DMG Intel"
echo "  dès qu'une release n'en a pas encore."
echo ""
echo "  Suivre en direct   : tail -f $STATE_DIR/watch.log"
echo "  Journal d'un build : ls -lt $STATE_DIR/logs/"
echo "  Forcer un passage  : bash $STATE_DIR/intel_watch.sh"
echo "  Désactiver         : launchctl unload -w $PLIST"
echo ""
