#!/usr/bin/env python3
"""
Mail de suivi du build Mac Intel — appele par intel_watch.sh.

    python3 intel_watch_mail.py debut  v3.1.96 --essai 2/3
    python3 intel_watch_mail.py ok     v3.1.96 --taille 238
    python3 intel_watch_mail.py echec  v3.1.96 --essai 2/3 --log /chemin/v3.1.96.log

Ne leve JAMAIS : un mail qui ne part pas ne doit pas faire echouer un build.
Le script imprime une ligne de statut, que le veilleur ecrit dans son journal.

CONFIGURATION (une seule fois sur le Mac) — ~/.mystrow_intel_watch/mail.conf :

    TO=ton@mail.fr
    SMTP_HOST=smtp.hostinger.com
    SMTP_PORT=465
    SMTP_USER=nepasrepondre@mystrow.fr
    SMTP_PASSWORD=...
    SMTP_FROM=MyStrow <nepasrepondre@mystrow.fr>

Ce fichier vit HORS du depot : `git reset --hard` ne doit pas pouvoir
l'effacer, et les identifiants n'ont rien a faire sur GitHub (c'est aussi
pourquoi on ne reutilise pas smtp_config.py, qui est gitignore et donc absent
du Mac). A proteger : chmod 600.
"""

import argparse
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

CONF = Path.home() / ".mystrow_intel_watch" / "mail.conf"
REPO_URL = "https://github.com/nprieto-ext/MyStrow/releases/tag/"


def lire_config():
    """Lit mail.conf (KEY=VALUE, # pour commenter). {} si absent ou illisible."""
    conf = {}
    try:
        for ligne in CONF.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, _, valeur = ligne.partition("=")
            conf[cle.strip()] = valeur.strip()
    except Exception:
        return {}
    return conf


def fin_du_log(chemin, lignes=25):
    """Les dernieres lignes du journal de build — c'est ce qu'on veut lire dans
    le mail d'echec, sans avoir a ouvrir le Mac."""
    try:
        contenu = Path(chemin).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return "\n".join(contenu.splitlines()[-lignes:])


def corps(evenement, tag, args):
    """(sujet, texte) selon l'evenement."""
    lien = REPO_URL + tag

    if evenement == "debut":
        sujet = f"MyStrow {tag} — build Mac Intel demarre"
        texte = [f"Le Mac Intel construit le DMG de {tag}."]
        if args.essai:
            texte.append(f"Essai {args.essai}.")
        texte.append("")
        texte.append("Compter 15 a 30 minutes (notarisation Apple comprise).")
        texte.append("Un second mail suivra, succes ou echec.")

    elif evenement == "ok":
        sujet = f"MyStrow {tag} — DMG Intel publie"
        texte = [f"MyStrow_intel.dmg est en ligne sur la release {tag}."]
        if args.taille:
            texte.append(f"Taille : {args.taille} Mo.")
        texte.append("")
        texte.append(lien)
        texte.append("")
        texte.append("Rien a faire : il est signe, notarise et deja uploade.")

    else:  # echec
        sujet = f"MyStrow {tag} — build Mac Intel EN ECHEC"
        texte = [f"Le build du DMG Intel de {tag} a echoue."]
        if args.essai:
            texte.append(f"Essai {args.essai}.")
        texte.append("")
        fin = fin_du_log(args.log) if args.log else ""
        if fin:
            texte.append("Fin du journal :")
            texte.append("")
            texte.append(fin)
            texte.append("")
        if args.log:
            texte.append(f"Journal complet sur le Mac : {args.log}")

    return sujet, "\n".join(texte) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("evenement", choices=["debut", "ok", "echec"])
    p.add_argument("tag")
    p.add_argument("--essai", default="")
    p.add_argument("--taille", default="")
    p.add_argument("--log", default="")
    args = p.parse_args()

    conf = lire_config()
    manquant = [c for c in ("TO", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD") if not conf.get(c)]
    if manquant:
        print(f"mail non envoye — {CONF} absent ou incomplet ({', '.join(manquant)})")
        return 0

    sujet, texte = corps(args.evenement, args.tag, args)

    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = conf.get("SMTP_FROM") or conf["SMTP_USER"]
    msg["To"] = conf["TO"]
    msg.set_content(texte)

    try:
        port = int(conf.get("SMTP_PORT", "465"))
        ctx = ssl.create_default_context()
        # 465 = SSL implicite, 587 = STARTTLS : les deux hebergeurs courants.
        if port == 587:
            with smtplib.SMTP(conf["SMTP_HOST"], port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(conf["SMTP_USER"], conf["SMTP_PASSWORD"])
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(conf["SMTP_HOST"], port, context=ctx, timeout=30) as s:
                s.login(conf["SMTP_USER"], conf["SMTP_PASSWORD"])
                s.send_message(msg)
    except Exception as e:
        print(f"mail non envoye — {type(e).__name__}: {e}")
        return 0

    print(f"mail '{args.evenement}' envoye a {conf['TO']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
