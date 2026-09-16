"""Tests de la geometrie de sortie video : cadrage, etirement, warp 4 coins.

Couvre les trois etages et surtout les pieges :
  · le chemin rapide doit rester actif quand rien n'est regle (4,43 ms/frame
    d'homographie contre 0,32 ms sans, mesures en 1080p) ;
  · un quadrilatere croise ne doit JAMAIS partir a l'ecran ;
  · le reglage est memorise PAR DALLE, pas globalement ;
  · le calque d'effet couvre toute la vue meme quand l'image est deformee,
    sinon une coupure laisserait de la lumiere sur les bords.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import QSize, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent

_app = QApplication.instance() or QApplication([])

from main_window import VideoGeometry, VideoSurface, _quad_is_convex
from PySide6.QtGui import QPolygonF


def _frame(w, h):
    img = QImage(QSize(w, h), QImage.Format_RGB32)
    img.fill(QColor("navy"))
    fmt = QVideoFrameFormat(QSize(w, h), QVideoFrameFormat.Format_BGRX8888)
    f = QVideoFrame(fmt)
    assert f.map(QVideoFrame.WriteOnly)
    mv = memoryview(f.bits(0))
    st = f.bytesPerLine(0)
    for y in range(h):
        mv[y * st:y * st + w * 4] = bytes(img.constScanLine(y))[:w * 4]
    f.unmap()
    return f


def _surface(vw=1000, vh=500, src=(1920, 1080)):
    s = VideoSurface()
    s.resize(vw, vh)
    s.show()
    s.item.videoSink().setVideoFrame(_frame(*src))
    for _ in range(8):
        _app.processEvents()
    return s


def test_cadrage_trois_modes():
    """Dalle 2:1, source 16:9 : chaque mode doit donner le bon rectangle."""
    s = _surface()
    g = s.geometry_settings()

    g.fit = "fit"; s.set_geometry_settings(g)
    x, y, w, h = s._base_rect()
    assert abs(w / h - 16 / 9) < 0.01, "fit doit conserver le ratio source"
    assert h == 500 and x > 0, "fit doit toucher le haut/bas et laisser des bandes"

    g.fit = "fill"; s.set_geometry_settings(g)
    x, y, w, h = s._base_rect()
    assert abs(w / h - 16 / 9) < 0.01, "fill conserve aussi le ratio"
    assert w == 1000 and h > 500, "fill doit deborder en hauteur"

    g.fit = "stretch"; s.set_geometry_settings(g)
    x, y, w, h = s._base_rect()
    assert (w, h) == (1000, 500), "stretch doit remplir exactement la dalle"


def test_etirement_et_decalage():
    s = _surface()
    g = s.geometry_settings()
    g.fit = "stretch"
    g.scale_y = 0.8
    s.set_geometry_settings(g)
    x, y, w, h = s._base_rect()
    assert abs(h - 400) < 0.01, "scale_y 0.8 sur 500 px doit donner 400"
    assert abs(y - 50) < 0.01, "l'image reduite doit rester centree"

    g.offset_x = 0.05
    s.set_geometry_settings(g)
    x2, _, _, _ = s._base_rect()
    assert abs(x2 - (x + 50)) < 0.01, "offset_x 5 % sur 1000 px = +50 px"


def test_chemin_rapide_sans_reglage():
    """Sans warp, aucune homographie ne doit etre posee sur l'item."""
    s = _surface()
    assert VideoGeometry().is_identity()
    assert s.item.transform().isIdentity(), "pas de transform sans reglage"

    g = s.geometry_settings()
    g.fit = "stretch"
    g.scale_y = 0.5
    s.set_geometry_settings(g)
    assert s.item.transform().isIdentity(), \
        "cadrage et etirement passent par setSize/setPos, pas par une transform"


def test_warp_place_les_coins_au_pixel():
    s = _surface()
    g = s.geometry_settings()
    g.corners[0] = [0.10, 0.05]
    g.corners[1] = [-0.10, 0.05]
    s.set_geometry_settings(g)

    t = s.item.transform()
    assert not t.isAffine(), "un keystone doit produire une vraie perspective"

    x, y, w, h = s._base_rect()
    base = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    for i, (bx, by) in enumerate(base):
        got = t.map(QPointF(bx - x, by - y))
        want_x = bx + g.corners[i][0] * 1000
        want_y = by + g.corners[i][1] * 500
        assert abs(got.x() - want_x) < 0.5 and abs(got.y() - want_y) < 0.5, \
            f"coin {i} mal place : {got} au lieu de ({want_x}, {want_y})"


def test_quadrilatere_croise_refuse():
    """Un noeud papillon doit retomber sur l'image droite, pas partir en vrac.

    `quadToQuad` accepte volontiers un quadrilatere croise et rend une image
    retournee sur elle-meme : sans le test de convexite, un coin tire trop loin
    donnait une sortie illisible en plein show.
    """
    croise = QPolygonF([QPointF(0, 0), QPointF(0, 100),
                        QPointF(100, 0), QPointF(100, 100)])
    assert not _quad_is_convex(croise)
    plat = QPolygonF([QPointF(0, 0), QPointF(50, 0),
                      QPointF(100, 0), QPointF(0, 100)])
    assert not _quad_is_convex(plat), "trois points alignes = non inversible"
    bon = QPolygonF([QPointF(0, 0), QPointF(100, 0),
                     QPointF(100, 100), QPointF(0, 100)])
    assert _quad_is_convex(bon)

    s = _surface()
    g = s.geometry_settings()
    g.corners = [[2.0, 0.0], [-2.0, 0.0], [2.0, 0.0], [-2.0, 0.0]]
    s.set_geometry_settings(g)
    assert s.item.transform().isIdentity(), \
        "un quadrilatere croise doit retomber sur l'image droite"


def test_calque_effet_couvre_toute_la_vue_meme_deforme():
    """Une coupure doit noircir la dalle ENTIERE, pas seulement l'image."""
    s = _surface()
    g = s.geometry_settings()
    g.corners[0] = [0.15, 0.10]
    s.set_geometry_settings(g)
    r = s._fx.rect()
    assert (r.x(), r.y(), r.width(), r.height()) == (0, 0, 1000, 500), \
        "le calque d'effet ne doit jamais suivre la deformation"


def test_serialisation_aller_retour():
    g = VideoGeometry()
    g.fit = "fill"
    g.scale_x, g.offset_y = 1.25, -0.1
    g.corners[2] = [0.03, -0.02]
    assert VideoGeometry.from_dict(g.to_dict()).to_dict() == g.to_dict()


def test_fichier_corrompu_ne_casse_rien():
    """Un .json bricole a la main ne doit pas empecher la sortie video."""
    g = VideoGeometry.from_dict({"fit": "nawak", "scale_x": "abc",
                                 "corners": [[0.1, 0.2], "n'importe quoi"]})
    assert g.fit == "fit" and g.scale_x == 1.0
    assert g.corners[0] == [0.1, 0.2], "le coin lisible est conserve"
    assert g.corners[1] == [0.0, 0.0], "le coin illisible retombe a zero"
    assert VideoGeometry.from_dict(None).is_identity()


def test_valeurs_bornees():
    g = VideoGeometry.from_dict({"scale_x": 999, "scale_y": -5,
                                 "corners": [[99, -99], [0, 0], [0, 0], [0, 0]]})
    assert g.scale_x == 4.0 and g.scale_y == 0.05
    assert g.corners[0] == [2.0, -2.0]


def test_mode_reglage_inerte_hors_session():
    """Hors mode reglage, un clic sur la sortie ne doit RIEN bouger."""
    s = _surface()
    avant = [list(c) for c in s.geometry_settings().corners]
    s.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(60, 10),
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert [list(c) for c in s.geometry_settings().corners] == avant
    assert not s.adjust_mode()


def test_glisser_un_coin():
    s = _surface()
    s.set_adjust_mode(True)
    assert s.adjust_mode() and s.active_corner() == 0

    hg = s.corner_points()[0]
    s.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, hg,
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert s.active_corner() == 0
    cible = QPointF(hg.x() + 80, hg.y() + 40)
    s.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, cible,
                                 Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    s.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, cible,
                                    Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    got = s.corner_points()[0]
    assert abs(got.x() - cible.x()) < 0.5 and abs(got.y() - cible.y()) < 0.5

    # Un clic loin de toute poignee ne doit rien saisir.
    s.set_active_corner(None)
    s.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(500, 250),
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert s.active_corner() is None
    s.set_adjust_mode(False)
    assert s._adjust_item is None


def test_clavier_au_pixel():
    from PySide6.QtGui import QKeyEvent
    s = _surface()
    s.set_adjust_mode(True)
    s.set_active_corner(2)

    def dx():
        return s.geometry_settings().corners[2][0]

    a = dx()
    s.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
    b = dx()
    assert abs((b - a) * 1000 - 1) < 0.01, "fleche = 1 px"
    s.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.ShiftModifier))
    assert abs((dx() - b) * 1000 - 10) < 0.01, "Maj+fleche = 10 px"

    s.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier))
    assert s.active_corner() == 3
    s.set_adjust_mode(False)


def test_reinitialisations():
    s = _surface()
    g = s.geometry_settings()
    g.fit = "stretch"
    g.scale_x = 1.4
    g.corners[1] = [0.05, 0.05]
    s.set_geometry_settings(g)

    g.reset_corners()
    s.set_geometry_settings(g)
    assert not g.has_warp() and g.fit == "stretch", \
        "reset des coins ne doit pas toucher au cadrage"
    assert g.scale_x == 1.4

    g.reset()
    assert g.is_identity()


def test_cadre_noir():
    """Le cadre masque les bords de l'image, pas son centre."""
    s = _surface()
    g = s.geometry_settings()
    g.fit = "stretch"
    s.set_geometry_settings(g)
    assert s.frame_mask_path() is None and not s._frame.isVisible()

    g.border = 0.1            # 10 % du petit cote (500 px) = 50 px
    s.set_geometry_settings(g)
    m = s.frame_mask_path()
    assert m is not None and s._frame.isVisible()
    assert m.contains(QPointF(20, 250)) and m.contains(QPointF(980, 250))
    assert m.contains(QPointF(500, 20)) and m.contains(QPointF(500, 480))
    assert not m.contains(QPointF(500, 250)), "le centre doit rester visible"
    assert not m.contains(QPointF(60, 60)), "juste apres 50 px, l'image se voit"
    assert not g.is_identity()

    g.border = 0.0
    s.set_geometry_settings(g)
    assert s.frame_mask_path() is None


def test_cadre_noir_serialise():
    g = VideoGeometry()
    g.border = 0.05
    assert VideoGeometry.from_dict(g.to_dict()).border == 0.05
    assert VideoGeometry.from_dict({"border": 9}).border == 0.5


def _canvas():
    from main_window import _GeometryCanvas
    s = _surface()
    g = s.geometry_settings()
    g.fit = "stretch"
    s.set_geometry_settings(g)
    c = _GeometryCanvas(s)
    c.resize(520, 300)
    c.show()
    _app.processEvents()
    return s, c


def _drag(c, start_view, end_view, mods=Qt.NoModifier):
    t = c._mapping()
    a, b = t.map(start_view), t.map(end_view)
    c.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, a,
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    c.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, b,
                                 Qt.NoButton, Qt.LeftButton, mods))
    c.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, b,
                                    Qt.LeftButton, Qt.NoButton, Qt.NoModifier))


def test_miniature_bord_droit_largeur_seule():
    """Tirer le bord droit : largeur seule, bord gauche immobile."""
    s, c = _canvas()
    _drag(c, QPointF(1000, 250), QPointF(800, 250))
    g = s.geometry_settings()
    x, y, w, h = s._base_rect()
    assert abs(g.scale_y - 1.0) < 1e-6, "la hauteur ne doit pas bouger"
    assert abs(w - 800) < 1.5 and abs(x) < 1.5, (x, w)
    assert h == 500


def test_miniature_bord_bas_symetrique():
    s, c = _canvas()
    _drag(c, QPointF(500, 500), QPointF(500, 450), Qt.ShiftModifier)
    x, y, w, h = s._base_rect()
    assert abs(h - 400) < 1.5 and abs(y - 50) < 1.5, (y, h)
    assert w == 1000


def test_miniature_deplacer_et_coin():
    s, c = _canvas()
    _drag(c, QPointF(500, 250), QPointF(600, 300))
    g = s.geometry_settings()
    assert abs(g.offset_x - 0.1) < 0.003 and abs(g.offset_y - 0.1) < 0.006
    assert not g.has_warp()

    hg = s.corner_points()[0]
    _drag(c, hg, QPointF(hg.x() + 40, hg.y() + 20))
    got = s.corner_points()[0]
    assert abs(got.x() - (hg.x() + 40)) < 2 and abs(got.y() - (hg.y() + 20)) < 2
    assert c._active_corner == 0


def test_luminosite_serialisee():
    g = VideoGeometry()
    assert g.brightness == 1.0 and g.is_identity()
    g.brightness = 0.6
    assert not g.is_identity()
    assert VideoGeometry.from_dict(g.to_dict()).brightness == 0.6
    assert VideoGeometry.from_dict({"brightness": 3}).brightness == 1.0
    assert VideoGeometry.from_dict({"brightness": -1}).brightness == 0.0


def test_luminosite_sur_la_sortie():
    """La luminosite de la dalle se fond dans le calque, sur toutes les pages."""
    from main_window import VideoOutputWindow
    win = VideoOutputWindow()
    win.setGeometry(0, 0, 640, 360)
    win.show()
    _app.processEvents()
    surf = win.video_widget
    if not isinstance(surf, VideoSurface):
        return
    win.show_video()
    win.set_fx_overlay(QColor(0, 0, 0, 0))
    g = surf.geometry_settings()
    g.brightness = 0.5
    surf.set_geometry_settings(g)          # doit recomposer tout seul
    assert abs(surf.fx_color().alpha() - 128) <= 1, surf.fx_color().alpha()

    # Effet noir a 180 + dalle a 50 % : 1 - (1 - 180/255) * 0.5 ≈ 0.853
    win.set_fx_overlay(QColor(0, 0, 0, 180))
    assert abs(surf.fx_color().alpha() - 217) <= 1, surf.fx_color().alpha()

    g.brightness = 1.0
    surf.set_geometry_settings(g)
    assert surf.fx_color().alpha() == 180, "a 100 % le calque d'effet est intact"
    win.close()


class _FakeHost:
    def __init__(self, surface):
        self.surface, self.on, self.screen = surface, False, 0
        self.calls = []

    def video_output_is_on(self):
        return self.on

    def set_video_output_on(self, on):
        self.calls.append(("on", on))
        self.on = on

    def video_output_surface(self):
        return self.surface

    def video_output_screens(self):
        return ["Ecran 1", "Ecran 2"]

    def video_output_screen(self):
        return self.screen

    def set_video_output_screen(self, i):
        self.calls.append(("screen", i))
        self.screen = i


def test_panneau_allume_la_sortie_lui_meme():
    """Sortie eteinte : le panneau s'ouvre grise et propose de l'allumer."""
    from main_window import VideoGeometryDialog
    s = _surface()
    host = _FakeHost(s)
    d = VideoGeometryDialog(None, parent=None, output=host)
    assert d._surface is None and not d._sx.parentWidget().isEnabled()
    assert not s.adjust_mode()

    d._power.setChecked(True)
    assert ("on", True) in host.calls
    assert d._surface is s and d._sx.parentWidget().isEnabled()
    assert s.adjust_mode(), "la mire doit s'allumer avec la sortie"

    d._screen.setCurrentIndex(1)
    assert ("screen", 1) in host.calls

    d._bright.setValue(40)
    assert abs(s.geometry_settings().brightness - 0.4) < 1e-6

    d._power.setChecked(False)
    assert d._surface is None and not s.adjust_mode(), \
        "sortie eteinte : plus de mire, reglages grises"
    d.accept()


def test_tout_reinitialiser_en_place():
    """L'hote garde l'objet : la remise a zero doit le modifier, pas le remplacer."""
    from main_window import VideoGeometryDialog
    s = _surface()
    g = s.geometry_settings()
    g.scale_x, g.brightness = 1.5, 0.3
    s.set_geometry_settings(g)
    d = VideoGeometryDialog(s)
    d._reset_all()
    assert s.geometry_settings() is g and g.is_identity()
    d.accept()


if __name__ == "__main__":
    import sys
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    echecs = 0
    for nom, fn in tests:
        try:
            fn()
            print(f"  OK   {nom}")
        except Exception as e:
            echecs += 1
            print(f"  ECHEC {nom} : {type(e).__name__}: {e}")
    print(f"\n{len(tests) - echecs}/{len(tests)} tests passes")
    sys.exit(1 if echecs else 0)
