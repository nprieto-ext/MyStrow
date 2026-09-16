"""Régénère les miniatures des cartes Vue / Scène du plan 3D.

Photographie chaque scène de `_SCENE_PRESETS` sous les 4 angles de caméra avec
le vrai moteur (plan_3d_web.html) — sans projecteur ni retour vidéo — et écrit
scenes3d/vignettes/<scène>_<vue>.png en 320 × 180.

À relancer après toute retouche d'un décor ou l'ajout d'une scène : une
miniature absente retombe sur le croquis QPainter, mais une miniature
périmée, elle, reste affichée telle quelle.

    python generer_vignettes_3d.py              # toutes les scènes
    python generer_vignettes_3d.py sapin_noel   # seulement celles-là

Le patch de l'utilisateur n'est jamais écrit (`_save_patch` neutralisé).
"""
import base64
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

VUES = ('iso', 'front', 'top', 'side')
TAILLE = (320, 180)
# Ambiance de référence des décors : curseur « Ambiance salle » à 2000 %.
# Les teintes des scènes sont réglées pour rester lisibles à ce niveau.
AMBIANCE = 20.0
ECLAIRCIR = 0.8             # force de l'éclaircissement « écran » (0 = aucun)
ATTENTE_SCENE_MS = 3000     # décor GLB chargé en asynchrone par la page
ATTENTE_VUE_MS = 900


def main():
    app = QApplication(sys.argv)
    import plan_3d_webwindow as m

    sortie = m._DOSSIER_VIGNETTES
    sortie.mkdir(parents=True, exist_ok=True)

    w = m.Plan3DWebWindow(None)
    w._save_patch = lambda *a, **k: None
    w.resize(1440, 900)
    w.show()

    # « Aucun décor » : sol éteint, la photo n'est qu'un rectangle noir. Sa carte
    # garde le croquis (contour pointillé du plateau), plus parlant.
    for vue in VUES:
        (sortie / f"vide_{vue}.png").unlink(missing_ok=True)
    choix = set(sys.argv[1:])
    taches = [(code, vue) for code in m._SCENE_PRESETS if code != 'vide'
              and (not choix or code in choix) for vue in VUES]
    echecs = []

    def attendre_page():
        if not w._ready:
            QTimer.singleShot(300, attendre_page)
            return
        QTimer.singleShot(1500, lambda: suivante(0, None))

    def suivante(i, scene_courante):
        if i >= len(taches):
            print(f"{len(taches) - len(echecs)} miniatures écrites dans {sortie}")
            for e in echecs:
                print("  ÉCHEC", e)
            app.exit(1 if echecs else 0)
            return
        code, _vue = taches[i]
        if code != scene_courante:
            w._apply_preset(code)
            w._js(f'window.setVideoReturn && window.setVideoReturn(false);'
                  f'window.setRoomAmbience && window.setRoomAmbience({AMBIANCE})')
            QTimer.singleShot(ATTENTE_SCENE_MS, lambda: photographier(i))
        else:
            photographier(i)

    def photographier(i):
        code, vue = taches[i]
        w._js(f"window.setCam('{vue}')")
        QTimer.singleShot(ATTENTE_VUE_MS, lambda: w._view.page().runJavaScript(
            "window.snapshot && window.snapshot()",
            lambda data: enregistrer(i, data)))

    def enregistrer(i, data):
        code, vue = taches[i]
        if not isinstance(data, str) or not data.startswith('data:image'):
            echecs.append(f"{code}_{vue} : {str(data)[:80]}")
        else:
            img = QImage.fromData(base64.b64decode(data.split(',', 1)[1]))
            iw, ih = img.width(), img.height()
            # Recadrage 16:9 centré, puis réduction
            if iw / ih > 16 / 9:
                cw, ch = int(ih * 16 / 9), ih
            else:
                cw, ch = iw, int(iw * 9 / 16)
            img = img.copy((iw - cw) // 2, (ih - ch) // 2, cw, ch).scaled(
                TAILLE[0], TAILLE[1], Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            img = img.convertToFormat(QImage.Format_RGB32)
            # Éclaircissement en fusion « écran » : remonte surtout les tons
            # sombres. Les scènes de nuit, lisibles en grand, se réduisaient à
            # une tache noire à la taille d'une carte.
            copie = QImage(img)
            p = QPainter(img)
            p.setCompositionMode(QPainter.CompositionMode_Screen)
            p.setOpacity(ECLAIRCIR)
            p.drawImage(0, 0, copie)
            p.end()
            img.save(str(sortie / f"{code}_{vue}.png"))
            print("ok", code, vue)
        suivante(i + 1, code)

    QTimer.singleShot(500, attendre_page)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
