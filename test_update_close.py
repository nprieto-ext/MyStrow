"""
test_update_close.py — La fermeture pour mise a jour sort-elle VRAIMENT ?

    python test_update_close.py

Ce que ce test protege : l'installeur Inno remplace `MyStrow.exe`, un fichier
que Windows verrouille tant que le processus vit. Si MyStrow ne sort pas,
Setup s'arrete sur sa page « applications ouvertes » et la mise a jour reste
bloquee. Le symptome est cote installeur, la cause est ici.

`QApplication.quit()` seul ne suffisait pas : il sort de la boucle
d'evenements sans jamais declencher le moindre `closeEvent` — donc sans sauver
la config ni arreter les serveurs. Le scenario est rejoue dans un VRAI
sous-processus, seule facon de verifier qu'il se termine.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ECHECS = []


def verifie(condition, message):
    print(("  ok   " if condition else "  ECHEC ") + message)
    if not condition:
        ECHECS.append(message)


# Le scenario joue dans le sous-processus. `parent` est la fenetre principale,
# comme `download_update` la recoit depuis le dialogue « A propos ».
SCENARIO = '''
import os, sys, threading, time
sys.path.insert(0, {racine!r})
trace = open({trace!r}, "w", encoding="utf-8")

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import QTimer

app = QApplication(sys.argv)


class FausseFenetre(QMainWindow):
    def __init__(self):
        super().__init__()
        self.seq = type("Seq", (), {{"is_dirty": False}})()
        self.config_sauvee = False

    def closeEvent(self, e):
        # Ce que fait le vrai closeEvent : sauver la config, arreter les
        # serveurs. C'est tout cela que `quit()` seul sautait.
        trace.write("closeEvent\\n")
        self.config_sauvee = True
        e.accept()


# Un serveur en tache de fond, comme le serveur tablette ou Stream Deck.
threading.Thread(target=lambda: time.sleep(300), daemon=True,
                 name="faux-serveur").start()

fenetre = FausseFenetre()
fenetre.show()

import updater
QTimer.singleShot(200, lambda: updater._quitter_pour_installer(fenetre))

code = app.exec()
trace.write("boucle terminee\\n")
trace.write("drapeau=%s\\n" % getattr(fenetre, "_fermeture_pour_maj", False))
trace.flush()
trace.close()
sys.exit(code)
'''


def test_sortie():
    print("\n[1] MyStrow sort-il de lui-meme ?")
    racine = str(Path(__file__).resolve().parent)
    dossier = Path(tempfile.gettempdir())
    trace = dossier / "mystrow_test_fermeture.txt"
    script = dossier / "mystrow_test_fermeture.py"
    trace.unlink(missing_ok=True)
    script.write_text(SCENARIO.format(racine=racine, trace=str(trace)),
                      encoding="utf-8")

    try:
        # Le filet de securite de `_quitter_pour_installer` tire a 8 s : un
        # delai de 25 s laisse la place aux deux issues, la propre et le filet.
        proc = subprocess.run([sys.executable, str(script)], timeout=25,
                              capture_output=True, text=True)
        sorti = True
    except subprocess.TimeoutExpired:
        sorti = False
        proc = None

    verifie(sorti, "le processus se termine (sinon l'installeur reste bloque)")
    if not sorti:
        return

    lignes = trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []
    verifie("closeEvent" in lignes,
            "closeEvent a bien tourne (config sauvee, serveurs arretes)")
    verifie("boucle terminee" in lignes, "la boucle d'evenements a rendu la main")
    verifie("drapeau=True" in lignes,
            "closeEvent sait qu'on ferme pour une mise a jour")


def test_langue():
    print("\n[2] Langue passee a l'installeur")
    import updater

    attendu = {"fr": "french", "en": "english", "es": "spanish",
               "de": "german", "pt": "brazilianportuguese"}
    # On remplace la LECTURE de la langue, jamais `set_language()` : celui-ci
    # ecrirait dans la config reelle de l'utilisateur, qu'un test ne doit pas
    # toucher.
    avant = updater.get_language
    try:
        for code, nom in attendu.items():
            updater.get_language = lambda c=code: c
            verifie(updater._langue_installeur() == nom,
                    f"{code} -> /LANG={nom}")
        updater.get_language = lambda: "xx"
        verifie(updater._langue_installeur() == "english",
                "langue inconnue -> anglais")
    finally:
        updater.get_language = avant

    # Les noms doivent exister dans le .iss, sinon Setup refuse de demarrer.
    iss = (Path(__file__).resolve().parent / "installer" / "maestro.iss") \
        .read_text(encoding="utf-8")
    for nom in attendu.values():
        verifie(f'Name: "{nom}"' in iss,
                f"« {nom} » est declare dans maestro.iss")

    bat = updater._create_installer_batch("C:/x/S.exe", 4242, "french")
    contenu = Path(bat).read_text(encoding="utf-8")
    verifie("/LANG=french" in contenu, "le batch passe /LANG")
    verifie("/CLOSEAPPLICATIONS" in contenu,
            "le batch garde /CLOSEAPPLICATIONS en dernier recours")
    verifie("Wait-Process -Id 4242" in contenu,
            "le batch attend toujours la sortie du processus")
    Path(bat).unlink(missing_ok=True)


if __name__ == "__main__":
    test_sortie()
    test_langue()

    print("\n" + "-" * 60)
    if ECHECS:
        print(f"{len(ECHECS)} ECHEC(S) :")
        for e in ECHECS:
            print("  -", e)
        sys.exit(1)
    print("Tout passe.")
