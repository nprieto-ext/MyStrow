#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# intel_watch.sh  —  Veilleur du build Mac Intel
#
# Lancé automatiquement toutes les 10 minutes par launchd (voir
# install_intel_watch.sh). À chaque passage :
#
#   1. demande à GitHub la dernière release publiée ;
#   2. si elle contient déjà MyStrow_intel.dmg → ne fait RIEN ;
#   3. sinon → lance build_intel_mac.sh sur le tag de cette release.
#      Le build compile, signe, notarise et uploade le DMG lui-même.
#
# Tu n'as donc plus rien à faire sur ce Mac : tu sors la version depuis le PC,
# et le DMG Intel apparaît sur la release quelques dizaines de minutes après.
#
# Installation : bash install_intel_watch.sh   (une seule fois)
#
# Fichiers créés (tous dans ~/.mystrow_intel_watch/) :
#   watch.log          journal court : une ligne par passage
#   logs/v3.1.96.log   sortie complète du build, une par version
#   intel_watch.sh     la copie qui tourne vraiment (voir REPO_DIR plus bas)
#   repo_dir           chemin du dépôt MyStrow, écrit à l'installation
#   state              dernière version tentée + nombre d'essais
#   lock/              verrou anti-double-build (contient le PID)
#
# Pour le lancer une fois à la main (utile pour tester) :
#   bash ~/.mystrow_intel_watch/intel_watch.sh
# Pour le forcer à rebuilder une version déjà abandonnée après 3 échecs :
#   rm ~/.mystrow_intel_watch/state && bash ~/.mystrow_intel_watch/intel_watch.sh
# ─────────────────────────────────────────────────────────────────────────────

# Pas de `set -e` : un échec doit être JOURNALISÉ et notifié, pas avaler le
# script en silence. Le veilleur ne doit jamais mourir sans laisser de trace.
set -uo pipefail

# launchd démarre les tâches avec un PATH minimal (/usr/bin:/bin:/usr/sbin:/sbin) :
# sans cette ligne, `gh`, `create-dmg` et le python3 de Homebrew sont introuvables
# alors qu'ils marchent parfaitement dans le Terminal.
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GITHUB_REPO="nprieto-ext/MyStrow"   # nom actuel du depot (l'ancien, MAESTRO, ne marche que par redirection)
ASSET_NAME="MyStrow_intel.dmg"
MAX_ATTEMPTS=3                       # au-delà, on arrête d'insister sur ce tag

STATE_DIR="$HOME/.mystrow_intel_watch"

# Où vit le dépôt MyStrow. Le veilleur, lui, tourne depuis une COPIE dans
# $STATE_DIR : `build_intel_mac.sh` fait `git reset --hard` sur le tag de la
# release, ce qui efface du dossier tout fichier absent de cette version — le
# veilleur se supprimerait lui-même en plein build, et launchd ne trouverait
# plus rien au passage suivant.
REPO_DIR="${MYSTROW_REPO_DIR:-}"
[ -n "$REPO_DIR" ] || REPO_DIR=$(cat "$STATE_DIR/repo_dir" 2>/dev/null || echo "")
[ -n "$REPO_DIR" ] || REPO_DIR="$SCRIPT_DIR"
LOG_DIR="$STATE_DIR/logs"
WATCH_LOG="$STATE_DIR/watch.log"
STATE_FILE="$STATE_DIR/state"
LOCK_DIR="$STATE_DIR/lock"

mkdir -p "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" >> "$WATCH_LOG"; }

notify() {
  # Notification macOS. Silencieuse si l'utilisateur ne l'a pas autorisée : ce
  # n'est qu'un confort, jamais une raison d'échouer.
  osascript -e "display notification \"$2\" with title \"MyStrow — build Intel\" subtitle \"$1\"" \
    >/dev/null 2>&1 || true
}

# Journal court : on le tronque au-delà de 1 Mo pour qu'il reste lisible.
if [ -f "$WATCH_LOG" ] && [ "$(wc -c < "$WATCH_LOG" | tr -d ' ')" -gt 1048576 ]; then
  tail -n 500 "$WATCH_LOG" > "$WATCH_LOG.tmp" && mv "$WATCH_LOG.tmp" "$WATCH_LOG"
fi

# ── Verrou ────────────────────────────────────────────────────────────────────
# Un build dure 15 à 30 min, le veilleur repasse toutes les 10 : sans verrou,
# trois builds tourneraient en parallèle sur le même dossier dist/.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  RUNNING_PID=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
  if [ -n "$RUNNING_PID" ] && kill -0 "$RUNNING_PID" 2>/dev/null; then
    log "build déjà en cours (pid $RUNNING_PID) — passage ignoré"
    exit 0
  fi
  # Pas de PID lisible ET verrou tout frais : l'autre passage vient de créer le
  # dossier et n'a pas encore écrit son PID. On lui laisse la place.
  if [ -z "$RUNNING_PID" ] && [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin -2 2>/dev/null)" ]; then
    log "verrou en cours de création par un autre passage — ignoré"
    exit 0
  fi
  # Sinon : processus mort (build tué, Mac redémarré en pleine notarisation…).
  log "verrou orphelin supprimé (pid ${RUNNING_PID:-inconnu})"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" 2>/dev/null || { log "impossible de créer le verrou"; exit 1; }
fi
echo "$$" > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

# ── Prérequis ─────────────────────────────────────────────────────────────────
if ! command -v gh >/dev/null 2>&1; then
  log "gh introuvable — installe-le : brew install gh && gh auth login"
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  log "gh non authentifié — lance : gh auth login"
  exit 1
fi
if [ ! -f "$REPO_DIR/build_intel_mac.sh" ]; then
  log "build_intel_mac.sh introuvable dans $REPO_DIR"
  exit 1
fi

# Auto-mise à jour : la copie lancée par launchd suit le dépôt, sans
# réinstallation. On vise toujours $STATE_DIR/intel_watch.sh, même quand c'est la
# copie du dépôt qui tourne (lancement à la main) : sinon une correction
# n'atteindrait jamais la copie automatique.
INSTALLED="$STATE_DIR/intel_watch.sh"
if [ -f "$REPO_DIR/intel_watch.sh" ] && ! cmp -s "$REPO_DIR/intel_watch.sh" "$INSTALLED"; then
  # Via un fichier temporaire + mv : bash lit son script au fur et à mesure de
  # l'exécution. Écrire par-dessus le fichier en cours (cp) le couperait en
  # plein milieu ; `mv` ne fait que remplacer le nom, le script qui tourne garde
  # son contenu d'origine jusqu'à la fin.
  if cp "$REPO_DIR/intel_watch.sh" "$INSTALLED.new" 2>/dev/null \
     && mv "$INSTALLED.new" "$INSTALLED" 2>/dev/null; then
    chmod +x "$INSTALLED" 2>/dev/null || true
    log "veilleur mis à jour depuis le dépôt (actif au prochain passage)"
  fi
fi

# ── Dernière release publiée ──────────────────────────────────────────────────
RELEASE_JSON=$(gh api "repos/$GITHUB_REPO/releases/latest" 2>/dev/null || echo "")
if [ -z "$RELEASE_JSON" ]; then
  log "GitHub injoignable (ou aucune release) — on réessaiera au prochain passage"
  exit 0
fi

TAG=$(echo "$RELEASE_JSON" | python3 -c \
  "import json,sys; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null || echo "")
HAS_DMG=$(echo "$RELEASE_JSON" | python3 -c \
  "import json,sys; print('oui' if '$ASSET_NAME' in [a['name'] for a in json.load(sys.stdin).get('assets',[])] else 'non')" \
  2>/dev/null || echo "?")

if [ -z "$TAG" ] || [ "$HAS_DMG" = "?" ]; then
  log "réponse GitHub illisible — passage ignoré"
  exit 0
fi

if [ "$HAS_DMG" = "oui" ]; then
  log "$TAG : DMG Intel déjà en ligne — rien à faire"
  exit 0
fi

# ── Compteur d'essais ─────────────────────────────────────────────────────────
# Sans ça, une release qui échoue systématiquement (certificat expiré, Apple qui
# refuse la notarisation…) relancerait un build toutes les 10 minutes, nuit et
# jour. On s'arrête après MAX_ATTEMPTS et on le dit clairement.
PREV_TAG=""; ATTEMPTS=0
if [ -f "$STATE_FILE" ]; then
  read -r PREV_TAG ATTEMPTS < "$STATE_FILE" 2>/dev/null || true
  # Le compteur doit rester un nombre : un fichier abîmé ne doit pas casser le
  # veilleur, il doit juste le faire repartir de zéro.
  case "${ATTEMPTS:-}" in (*[!0-9]*|"") ATTEMPTS=0 ;; esac
fi
[ "$PREV_TAG" = "$TAG" ] || ATTEMPTS=0

if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
  log "$TAG : $ATTEMPTS échecs — abandon. Voir $LOG_DIR/$TAG.log, puis : rm $STATE_FILE"
  exit 0
fi

ATTEMPTS=$((ATTEMPTS + 1))
echo "$TAG $ATTEMPTS" > "$STATE_FILE"

# ── main doit bien être la version de cette release ───────────────────────────
# On build origin/main, pas le tag : `git reset --hard <tag>` remettrait le dépôt
# du Mac sur une version ANCIENNE des scripts de build, relancée telle quelle au
# passage suivant — toute correction serait perdue à chaque build. En échange, il
# faut vérifier que main est bien resté sur cette version : si la suivante est
# déjà en préparation, le DMG produit ne correspondrait à aucune release.
MAIN_VERSION=$(gh api "repos/$GITHUB_REPO/contents/core.py?ref=main" --jq '.content' 2>/dev/null \
  | python3 -c "import sys, base64, re
src = base64.b64decode(sys.stdin.read()).decode('utf-8', 'replace')
m = re.search(r'VERSION\s*=\s*.(.*?).\s*$', src, re.M)
print(m.group(1) if m else '')" 2>/dev/null || echo "")

if [ -n "$MAIN_VERSION" ] && [ "v$MAIN_VERSION" != "$TAG" ]; then
  log "$TAG : main est déjà en $MAIN_VERSION — DMG Intel de $TAG à faire à la main, on n'insiste pas"
  notify "$TAG" "main est en $MAIN_VERSION : DMG Intel à construire à la main"
  echo "$TAG $MAX_ATTEMPTS" > "$STATE_FILE"
  exit 0
fi

# ── Build ─────────────────────────────────────────────────────────────────────
BUILD_LOG="$LOG_DIR/$TAG.log"
log "$TAG : DMG Intel absent → build (essai $ATTEMPTS/$MAX_ATTEMPTS), journal : $BUILD_LOG"
notify "$TAG" "Build du DMG Intel démarré (essai $ATTEMPTS/$MAX_ATTEMPTS)"

# `caffeinate -i` empêche la mise en veille pendant le build : un Mac qui
# s'endort au milieu de la notarisation laisse un verrou et un DMG à moitié fait.
# MYSTROW_OUT_DIR : surtout PAS le Bureau. macOS interdit Bureau/Documents/
# Téléchargements aux processus lancés par launchd — le build allait jusqu'au
# bout puis mourait sur « rm: ~/Desktop/MyStrow_intel.dmg: Operation not
# permitted », alors qu'il passait très bien depuis le Terminal.
MYSTROW_AUTO=1 MYSTROW_OUT_DIR="$STATE_DIR/out" \
  caffeinate -i bash "$REPO_DIR/build_intel_mac.sh" > "$BUILD_LOG" 2>&1
RC=$?

# ── Résultat ──────────────────────────────────────────────────────────────────
# On ne se fie pas au seul code retour : la vérité, c'est la présence du DMG sur
# la release (le build peut réussir et l'upload échouer).
UPLOADED=$(gh api "repos/$GITHUB_REPO/releases/tags/$TAG" 2>/dev/null | python3 -c \
  "import json,sys; print('oui' if '$ASSET_NAME' in [a['name'] for a in json.load(sys.stdin).get('assets',[])] else 'non')" \
  2>/dev/null || echo "non")

if [ "$RC" -eq 0 ] && [ "$UPLOADED" = "oui" ]; then
  log "$TAG : ✅ DMG Intel construit et publié"
  notify "$TAG" "DMG Intel publié sur la release ✅"
  echo "$TAG 0" > "$STATE_FILE"
elif [ "$RC" -eq 0 ]; then
  log "$TAG : build OK mais DMG absent de la release — upload à vérifier ($BUILD_LOG)"
  notify "$TAG" "Build OK, upload échoué — à vérifier"
else
  log "$TAG : ❌ build en échec (code $RC) — voir $BUILD_LOG"
  notify "$TAG" "Build en échec (essai $ATTEMPTS/$MAX_ATTEMPTS)"
fi

# Ne garder que les 20 derniers journaux de build.
ls -1t "$LOG_DIR"/*.log 2>/dev/null | tail -n +21 | while read -r old; do rm -f "$old"; done

exit 0
