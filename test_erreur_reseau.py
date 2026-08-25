"""
test_erreur_reseau.py — Aucun message technique brut ne doit atteindre l'ecran.

    python test_erreur_reseau.py

Le cas qui a declenche ce test : un utilisateur a vu
« <urlopen error [Errno 11001] getaddrinfo failed> » sur l'ecran de connexion.
C'est de l'anglais, un numero, et surtout ca ne dit pas quoi faire — alors que
la cause est tres concrete : le nom de domaine ne se resout pas.

Le piege structurel qui produit ca : un `try` qui ne rattrape que
`urllib.error.HTTPError`. Une reponse du serveur est alors traduite, mais une
panne de reseau (qui n'est PAS une HTTPError) passe a travers et ressort telle
quelle. Les tests ci-dessous forcent la panne DNS dans les vrais chemins.
"""

import socket
import ssl
import sys
import urllib.error

ECHECS = []


def verifie(condition, message):
    print(("  ok   " if condition else "  ECHEC ") + message)
    if not condition:
        ECHECS.append(message)


def _casse_le_dns():
    """Rend toute resolution de nom impossible, comme un portail Wi-Fi non
    valide ou un DNS injoignable."""
    def faux(*a, **k):
        raise socket.gaierror(11001, "getaddrinfo failed")
    socket.getaddrinfo = faux


def _est_brut(texte: str) -> bool:
    """Le message porte-t-il encore de la tuyauterie ?"""
    t = (texte or "").lower()
    return any(m in t for m in ("urlopen", "getaddrinfo", "errno", "11001",
                                "traceback", "gaierror"))


def test_traduction():
    print("\n[1] Chaque panne a son message")
    from core import message_erreur_reseau

    dns = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
    msg_dns = message_erreur_reseau(dns)
    verifie(not _est_brut(msg_dns), "DNS : plus rien de technique")
    verifie(msg_dns != message_erreur_reseau(urllib.error.URLError("autre")),
            "DNS a son propre message, pas le generique")

    # La meme panne arrive nue ou emballee selon la couche qui echoue.
    verifie(message_erreur_reseau(socket.gaierror(11001, "getaddrinfo failed"))
            == msg_dns, "gaierror nue reconnue comme la version emballee")
    verifie(message_erreur_reseau(
        urllib.error.URLError(socket.gaierror(-2, "Name or service not known")))
        == msg_dns, "meme panne sous macOS/Linux reconnue aussi")

    distincts = {
        message_erreur_reseau(urllib.error.URLError(socket.timeout("timed out"))),
        message_erreur_reseau(urllib.error.URLError(ssl.SSLError("certificate verify failed"))),
        message_erreur_reseau(urllib.error.URLError(ConnectionRefusedError(10061, "refused"))),
        msg_dns,
    }
    verifie(len(distincts) == 4,
            "timeout, SSL, refus et DNS ne disent pas la meme chose")
    for m in distincts:
        verifie(not _est_brut(m), f"message propre : {m[:38]}...")


def test_chemins():
    print("\n[2] Les vrais chemins, DNS coupe")
    _casse_le_dns()

    import license_manager as lm
    ok, msg = lm.login_account("test@example.com", "motdepasse")
    verifie(not ok, "connexion refusee sans reseau")
    verifie(not _est_brut(msg), "ecran de connexion : message lisible")

    ok, msg = lm.register_account("test@example.com", "MotDePasse123")
    verifie(not _est_brut(msg), "creation de compte : message lisible")

    # Passe par brevo_client, qui ne rattrapait que les HTTPError.
    ok, msg = lm.subscribe_newsletter("test@example.com")
    verifie(not _est_brut(msg), "newsletter : message lisible")

    import firebase_client as fc
    try:
        fc.send_credentials_email("test@example.com")
        verifie(False, "l'envoi des identifiants aurait du echouer")
    except Exception as e:
        verifie(isinstance(e, fc.CloudFunctionUnreachable),
                "Cloud Function injoignable : le type permet le repli")
        verifie(not _est_brut(str(e)), "envoi des identifiants : message lisible")

    try:
        fc.send_password_reset("test@example.com")
        verifie(False, "la reinitialisation aurait du echouer")
    except Exception as e:
        verifie(not _est_brut(str(e)), "reinitialisation : message lisible")


def test_pas_de_faux_positif():
    print("\n[3] Les refus du serveur restent des refus")
    # Un mot de passe faux n'est PAS une panne reseau : le message metier doit
    # survivre. C'est ce que garantit le tri par type dans `_post_json`, et ce
    # que casserait un `except Exception` trop large.
    import license_manager as lm
    src = open(lm.__file__, encoding="utf-8").read()
    for mot in ("2 appareils", "désactivé", "Session expirée"):
        verifie(mot in src,
                f"le tri sur « {mot} » est toujours en place")

    from core import message_erreur_reseau
    reseau = message_erreur_reseau(
        urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")))
    verifie(not any(m in reseau for m in ("2 appareils", "désactivé",
                                          "Session expirée")),
            "un message reseau ne peut pas etre pris pour un refus de licence")


if __name__ == "__main__":
    test_traduction()
    test_chemins()
    test_pas_de_faux_positif()

    print("\n" + "-" * 60)
    if ECHECS:
        print(f"{len(ECHECS)} ECHEC(S) :")
        for e in ECHECS:
            print("  -", e)
        sys.exit(1)
    print("Tout passe.")
