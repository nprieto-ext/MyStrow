# -*- coding: utf-8 -*-
"""Publie / met a jour le guide "materiel compatible" sur le Discord MyStrow.

Le contenu est celui du shop (https://mystrow.fr/shop), remis en forme en embeds
Discord. Rien n'est envoye tant qu'aucune URL de webhook n'est fournie.

  URL du webhook : variable d'env MYSTROW_DISCORD_WEBHOOK
                   ou fichier ~/.mystrow_discord_webhook.txt
  (jamais en dur ici : ce depot est public)

Usage
-----
  python tools/discord_materiel.py --dry-run   # affiche, n'envoie rien
  python tools/discord_materiel.py --post      # premiere publication
  python tools/discord_materiel.py --update    # re-edite les messages deja postes

--update reprend les IDs enregistres dans ~/.mystrow_discord_materiel.json :
les messages sont modifies sur place, pas repostes. C'est ce qui permet de
corriger un prix sans repolluer le canal.
"""
import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request

WEBHOOK_ENV = "MYSTROW_DISCORD_WEBHOOK"
WEBHOOK_FILE = os.path.expanduser("~/.mystrow_discord_webhook.txt")
STATE_FILE = os.path.expanduser("~/.mystrow_discord_materiel.json")

SHOP = "https://mystrow.fr/shop"
DL = "https://mystrow.fr/telecharger"
IMG = "https://mystrow.fr/shop/"
YELLOW = 0xE2CE16

USERNAME = "MyStrow"
AVATAR = "https://mystrow.fr/og-image.webp"


def field(name, value, inline=True):
    return {"name": name, "value": value, "inline": inline}


# --- Le contenu -------------------------------------------------------------

MESSAGES = [
    # 1. Intro
    [{
        "title": "🎛️  Le matériel compatible MyStrow",
        "url": SHOP,
        "color": YELLOW,
        "description": (
            "Pour piloter une scène entière avec MyStrow, il te faut **deux choses** :\n\n"
            "**1. Une interface DMX** — obligatoire. C'est elle qui transmet le signal "
            "à tes projecteurs.\n"
            "**2. Un contrôleur MIDI** — optionnel. Pour jouer tes lumières au doigt "
            "plutôt qu'à la souris.\n\n"
            "MyStrow parle l'**Art-Net** et le **DMX512** standard : tout matériel ouvert "
            "fonctionne. Les modèles ci-dessous sont ceux qu'on a vérifiés."
        ),
        "footer": {"text": "Tous les détails, prix et liens d'achat sur mystrow.fr/shop"},
    }],

    # 2. Les deux interfaces recommandées
    [
        {
            "author": {"name": "1 · Interface DMX — au choix (une seule suffit)"},
            "title": "📡  Node ArtNet DMX — 59 €",
            "url": SHOP,
            "color": YELLOW,
            "description": (
                "Passe par le réseau RJ45. Plus stable sur scène, zéro latence. "
                "Le choix pour les clubs, salles de spectacle et installations permanentes."
            ),
            "thumbnail": {"url": IMG + "Node.jpg"},
            "fields": [
                field("Connexion", "Réseau RJ45"),
                field("Sortie", "XLR DMX512"),
                field("Profil", "Installation fixe · Pro"),
            ],
        },
        {
            "title": "🔌  USB Node DMX ArtNet — 59 €",
            "url": SHOP,
            "color": YELLOW,
            "description": (
                "Un vrai node ArtNet, mais en USB : pilote le DMX512 sans carte réseau "
                "Ethernet. Plug & play, config automatique et sortie opto-isolée. "
                "Parfait pour les PC qui n'ont qu'un port USB et les shows itinérants."
            ),
            "thumbnail": {"url": IMG + "UsbDmx.jpg"},
            "fields": [
                field("Connexion", "USB direct"),
                field("Sortie", "XLR DMX512 opto-isolée"),
                field("Profil", "Itinérant · sans réseau"),
            ],
        },
    ],

    # 3. Les autres modèles compatibles
    [
        {
            "author": {"name": "Autres interfaces compatibles"},
            "title": "🌐  Nodes ArtNet",
            "color": YELLOW,
            "description": "Compatible avec tout node DMX ouvert parlant l'Art-Net standard.",
            "fields": [
                field("ENTTEC ODE Mk2", "~200 € · la référence"),
                field("DMXking eDMX1 PRO", "~130 € · compact"),
                field("DMXking eDMX2 PRO", "~200 € · 2 univers"),
                field("Node ArtNet 4 univers", "129 €"),
                field("Luminex Ethernet-DMX", "~300 €+ · multi-univers"),
            ],
        },
        {
            "title": "🔌  Interfaces USB/DMX",
            "color": YELLOW,
            "fields": [
                field("ENTTEC DMX USB PRO", "la référence · 22 fps stables"),
                field("DMXking ultraDMX Micro", "compact"),
                field("Eurolite USB-DMX512 PRO MK2", "150 €"),
                field("ENTTEC Open DMX USB (70303)", "104,74 €"),
                field("Adaptateur USB DMX512", "16,14 € · l'entrée de gamme"),
            ],
            "footer": {"text": "Open DMX USB : nécessite le driver D2XX de FTDI, "
                               "pas le driver VCP installé par défaut."},
        },
    ],

    # 4. Contrôleurs MIDI
    [
        {
            "author": {"name": "2 · Contrôleur MIDI — optionnel"},
            "title": "⭐  AKAI APC mini mk2 — 89 €",
            "url": SHOP,
            "color": YELLOW,
            "description": (
                "**Recommandé — MyStrow est conçu autour.** Plug & play, aucun driver : "
                "MyStrow le détecte au démarrage. Chaque pad et chaque fader a sa "
                "correspondance directe, avec retour LED en temps réel."
            ),
            "thumbnail": {"url": IMG + "AKAIAPCMINI.png"},
            "fields": [
                field("Pads", "8×8 LED"),
                field("Faders", "9"),
                field("Branchement", "USB plug & play"),
            ],
        },
        {
            "title": "🎹  Novation Launchpad Mini MK3 — 89 €",
            "url": SHOP,
            "color": YELLOW,
            "description": (
                "Alternative compacte, reconnue plug & play. Grille 8×8 de pads RGB au "
                "retour LED éclatant.\n\n"
                "**À noter : pas de faders physiques** — l'intensité se règle via les pads, "
                "la tablette ou le plan de scène."
            ),
            "thumbnail": {"url": IMG + "Novation.png"},
            "fields": [
                field("Pads", "8×8 RGB"),
                field("Branchement", "USB-C"),
                field("Faders", "aucun"),
            ],
        },
    ],

    # 5. Le logiciel
    [{
        "title": "💻  Et le logiciel : MyStrow",
        "url": DL,
        "color": YELLOW,
        "description": (
            "Gratuit pour démarrer, aucune carte bancaire. **14 jours d'accès complet** : "
            "contrôle temps réel, IA Lumière, timeline et player audio/vidéo.\n\n"
            "🪟 **Windows 10 / 11**  ·  🍎 **macOS 11+**\n\n"
            f"→ Télécharger : {DL}\n"
            f"→ Le matériel : {SHOP}"
        ),
        "footer": {"text": "La sortie DMX est activée avec une licence Pro ou Lifetime."},
    }],
]


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


def do_post(webhook):
    ids = []
    for i, embeds in enumerate(MESSAGES, 1):
        res = request(
            webhook + "?wait=true",
            {"username": USERNAME, "avatar_url": AVATAR, "embeds": embeds},
        )
        ids.append(res.get("id"))
        print("  message %d/%d publie (id %s)" % (i, len(MESSAGES), res.get("id")))
    save_state({"webhook_tail": webhook[-12:], "message_ids": ids})
    print("\nIDs enregistres dans %s — utilise --update pour corriger sans reposter."
          % STATE_FILE)


def do_update(webhook):
    state = load_state()
    ids = state.get("message_ids") or []
    if len(ids) != len(MESSAGES):
        sys.exit("Etat incoherent : %d IDs enregistres pour %d messages. "
                 "Supprime les messages a la main puis relance --post."
                 % (len(ids), len(MESSAGES)))
    for i, (mid, embeds) in enumerate(zip(ids, MESSAGES), 1):
        request("%s/messages/%s" % (webhook, mid), {"embeds": embeds}, method="PATCH")
        print("  message %d/%d mis a jour (id %s)" % (i, len(MESSAGES), mid))


def do_dry_run():
    for i, embeds in enumerate(MESSAGES, 1):
        print("\n" + "=" * 62)
        print("MESSAGE %d  (%d embed%s)" % (i, len(embeds), "s" if len(embeds) > 1 else ""))
        print("=" * 62)
        for e in embeds:
            if e.get("author"):
                print("  [%s]" % e["author"]["name"])
            print("  %s" % e.get("title", ""))
            if e.get("description"):
                for line in e["description"].split("\n"):
                    print("    " + line)
            for f in e.get("fields", []):
                print("    - %s : %s" % (f["name"], f["value"]))
            if e.get("thumbnail"):
                print("    [img] %s" % e["thumbnail"]["url"])
            if e.get("footer"):
                print("    _%s_" % e["footer"]["text"])
            print()


def main():
    # La console Windows est en cp1252 : les fleches et emoji la font planter.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="affiche sans rien envoyer")
    g.add_argument("--post", action="store_true", help="publie les messages")
    g.add_argument("--update", action="store_true", help="met a jour les messages existants")
    a = ap.parse_args()

    if a.dry_run:
        do_dry_run()
        return
    webhook = load_webhook()
    (do_post if a.post else do_update)(webhook)


if __name__ == "__main__":
    main()
