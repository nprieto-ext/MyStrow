# -*- coding: utf-8 -*-
"""Publie les versions de MyStrow sur le canal #telechargement_MyStrow.

Deux usages complementaires :

  --latest    LE message "derniere version". Cree la premiere fois, puis
              re-edite sur place a chaque release. Toujours exact, a epingler
              en haut du canal.

  --announce  UN nouveau message par version. Sert d'historique et notifie
              les membres. Accepte --notes "quoi de neuf".

La version n'est jamais saisie a la main : elle est lue dans core.py, seule
source de verite (le meme numero que celui embarque dans l'exe).

  URL du webhook : variable d'env MYSTROW_DISCORD_WEBHOOK_RELEASE
                   ou fichier ~/.mystrow_discord_webhook_release.txt

Usage
-----
  python tools/discord_release.py --latest --dry-run
  python tools/discord_release.py --latest
  python tools/discord_release.py --announce --notes "Correction du DMX sur macOS."
"""
import argparse
import datetime
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, "core.py")

# Le coeur de --latest vit dans release.py : c'est le seul fichier que
# PyInstaller embarque dans MyStrow_Admin.exe (admin_panel l'importe deja).
# On le reutilise ici plutot que d'en tenir une seconde copie.
sys.path.insert(0, ROOT)
from release import notify_discord_latest, discord_embed_latest  # noqa: E402

WEBHOOK_ENV = "MYSTROW_DISCORD_WEBHOOK_RELEASE"
WEBHOOK_FILE = os.path.expanduser("~/.mystrow_discord_webhook_release.txt")
STATE_FILE = os.path.expanduser("~/.mystrow_discord_release.json")

SITE = "https://mystrow.fr"
DL = "https://mystrow.fr/telecharger"
# Redirections Cloud Function : elles pointent toujours vers la derniere
# release publiee. L'URL ne change donc jamais d'une version a l'autre.
CF = "https://us-central1-mystrow-907be.cloudfunctions.net/download_redirect?p="
DL_WIN = CF + "win"
DL_MAC = CF + "mac"
DL_MAC_INTEL = CF + "mac_intel"

YELLOW = 0xE2CE16
USERNAME = "MyStrow"
AVATAR = "https://mystrow.fr/og-image.webp"

MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre")


def get_version():
    """Lit VERSION dans core.py — jamais de numero saisi a la main."""
    src = io.open(CORE, encoding="utf-8").read()
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', src, re.M)
    if not m:
        sys.exit("VERSION introuvable dans %s" % CORE)
    return m.group(1)


def today_fr():
    d = datetime.date.today()
    return "%d %s %d" % (d.day, MOIS[d.month - 1], d.year)


def links_block():
    return (
        f"🪟  **Windows 10 / 11** — [télécharger l'installeur]({DL_WIN})\n"
        f"🍎  **macOS Apple Silicon** (M1 → M4) — [télécharger le .dmg]({DL_MAC})\n"
        f"🍏  **macOS Intel** — [télécharger le .dmg]({DL_MAC_INTEL})"
    )


def embed_announce(version, notes):
    desc = ""
    if notes:
        desc += notes.strip() + "\n\n"
    desc += links_block()
    return {
        "author": {"name": "Nouvelle version"},
        "title": f"🚀  MyStrow {version} est disponible",
        "url": DL,
        "color": YELLOW,
        "description": desc,
        "footer": {"text": f"Publié le {today_fr()} · mise à jour automatique "
                           "au démarrage de l'app"},
    }


# --- Envoi ------------------------------------------------------------------

def load_webhook():
    url = os.environ.get(WEBHOOK_ENV, "").strip()
    if not url and os.path.exists(WEBHOOK_FILE):
        url = io.open(WEBHOOK_FILE, encoding="utf-8").read().strip()
    if not url:
        sys.exit(
            "Aucune URL de webhook.\n"
            "  set %s=https://discord.com/api/webhooks/...\n"
            "  ou ecris-la dans %s" % (WEBHOOK_ENV, WEBHOOK_FILE)
        )
    if "discord.com/api/webhooks/" not in url:
        sys.exit("URL de webhook Discord invalide : %r" % url[:60])
    return url.rstrip("/")


def request(url, payload, method="POST"):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "User-Agent": "MyStrow/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        sys.exit("Discord a refuse (%s) : %s" % (e.code, e.read().decode("utf-8")[:500]))


def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(io.open(STATE_FILE, encoding="utf-8"))
    return {}


def save_state(state):
    json.dump(state, io.open(STATE_FILE, "w", encoding="utf-8"), indent=2)


def send(webhook, embed):
    return request(webhook + "?wait=true",
                   {"username": USERNAME, "avatar_url": AVATAR, "embeds": [embed]})


def do_latest(version):
    """Delegue a release.notify_discord_latest — implementation unique."""
    ok, msg = notify_discord_latest(version)
    print("  " + msg)
    if not ok:
        sys.exit(1)


def do_announce(webhook, version, notes):
    res = send(webhook, embed_announce(version, notes))
    state = load_state()
    state.setdefault("announced", []).append({"version": version, "id": res.get("id")})
    save_state(state)
    print("  annonce %s publiee (id %s)" % (version, res.get("id")))


def show(embed):
    print("=" * 62)
    if embed.get("author"):
        print("  [%s]" % embed["author"]["name"])
    print("  %s" % embed["title"])
    for line in embed["description"].split("\n"):
        print("    " + line)
    for f in embed.get("fields", []):
        print("    - %s : %s" % (f["name"], f["value"]))
    print("    _%s_" % embed["footer"]["text"])
    print("=" * 62)


def main():
    # La console Windows est en cp1252 : les fleches et emoji la font planter.
    # Sans ca, un simple print ferait sortir le script en erreur — et release.py
    # croirait a un echec alors que le message est parti.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--latest", action="store_true",
                   help="cree ou met a jour LE message 'derniere version'")
    g.add_argument("--announce", action="store_true",
                   help="poste une nouvelle annonce de version")
    ap.add_argument("--notes", default="", help="quoi de neuf (avec --announce)")
    ap.add_argument("--version", default=None, help="force le numero (defaut : core.py)")
    ap.add_argument("--dry-run", action="store_true", help="affiche sans rien envoyer")
    a = ap.parse_args()

    version = a.version or get_version()

    if a.dry_run:
        show(discord_embed_latest(version) if a.latest
             else embed_announce(version, a.notes))
        return

    if a.latest:
        do_latest(version)
    else:
        do_announce(load_webhook(), version, a.notes)


if __name__ == "__main__":
    main()
