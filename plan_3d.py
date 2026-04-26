"""
Plan de feu 3D — rendu QPainter, aucune dépendance externe.
Fenêtre flottante avec projection perspective et orbite souris.

Interactions :
  • Drag gauche      → orbite caméra
  • Clic gauche MH   → sélectionne la lyre (anneau cyan)
  • Clic sol (lyre sélectionnée) → pointe la lyre sur ce point
  • Clic droit / Echap → désélectionne
  • Scroll            → zoom
"""

import math
import time as _time
from PySide6.QtWidgets import (QMainWindow, QWidget, QMenu, QWidgetAction,
                                QSlider, QLabel, QHBoxLayout, QVBoxLayout,
                                QFrame, QPushButton, QDoubleSpinBox)
from PySide6.QtCore    import Qt, QPoint, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui     import (QPainter, QPen, QBrush, QColor, QPolygonF,
                                QFont, QLinearGradient, QRadialGradient,
                                QPainterPath)

# ─────────────────────────────────────────────────────────────────────────────
# Math helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mat_mul(a, b):
    r = [0.0] * 16
    for i in range(4):
        for j in range(4):
            for k in range(4):
                r[i*4+j] += a[i*4+k] * b[k*4+j]
    return r

def _look_at(eye, center, up):
    ex,ey,ez = eye; cx,cy,cz = center; ux,uy,uz = up
    fx,fy,fz = cx-ex, cy-ey, cz-ez
    fl = math.sqrt(fx*fx+fy*fy+fz*fz)
    fx,fy,fz = fx/fl, fy/fl, fz/fl
    rx = fy*uz - fz*uy; ry = fz*ux - fx*uz; rz = fx*uy - fy*ux
    rl = math.sqrt(rx*rx+ry*ry+rz*rz) or 1e-9
    rx,ry,rz = rx/rl, ry/rl, rz/rl
    ux2 = ry*fz - rz*fy; uy2 = rz*fx - rx*fz; uz2 = rx*fy - ry*fx
    return [
        rx,  ry,  rz,  -(rx*ex+ry*ey+rz*ez),
        ux2, uy2, uz2, -(ux2*ex+uy2*ey+uz2*ez),
       -fx, -fy, -fz,  (fx*ex+fy*ey+fz*ez),
        0,   0,   0,   1,
    ]

def _perspective(fov_deg, aspect, near, far):
    f  = 1.0 / math.tan(math.radians(fov_deg) * 0.5)
    nf = 1.0 / (near - far)
    return [
        f/aspect, 0, 0,              0,
        0,        f, 0,              0,
        0,        0, (far+near)*nf,  2*far*near*nf,
        0,        0, -1,             0,
    ]

def _transform(mat, x, y, z):
    w  = mat[12]*x + mat[13]*y + mat[14]*z + mat[15]
    xo = mat[0]*x  + mat[1]*y  + mat[2]*z  + mat[3]
    yo = mat[4]*x  + mat[5]*y  + mat[6]*z  + mat[7]
    zo = mat[8]*x  + mat[9]*y  + mat[10]*z + mat[11]
    return xo, yo, zo, w


# ─────────────────────────────────────────────────────────────────────────────
# Gobo patterns
# ─────────────────────────────────────────────────────────────────────────────

_GOBO_PATTERNS = [
    "spokes4", "spokes6", "spokes3", "donut",
    "star5",   "stripes", "breakup",
]

def _draw_gobo_on_beam(painter, tip_pt, base_l, base_r, slot_idx, rot_deg, lvl):
    clip = QPainterPath()
    clip.addPolygon(QPolygonF([tip_pt, base_l, base_r]))
    painter.setClipPath(clip)
    cx = tip_pt.x()*0.3 + base_l.x()*0.35 + base_r.x()*0.35
    cy = tip_pt.y()*0.3 + base_l.y()*0.35 + base_r.y()*0.35
    bw  = abs(base_r.x()-base_l.x()); bh = abs(base_l.y()-tip_pt.y())
    rad = max(bw, bh) * 0.45
    shadow = QColor(0,0,0, int(min(200, 120+80*lvl)))
    pattern = _GOBO_PATTERNS[(slot_idx-1) % len(_GOBO_PATTERNS)]
    painter.save()
    painter.translate(cx, cy); painter.rotate(rot_deg)
    painter.setPen(Qt.NoPen); painter.setBrush(QBrush(shadow))
    if pattern == "spokes4":   _gobo_spokes(painter, rad, 4)
    elif pattern == "spokes6": _gobo_spokes(painter, rad, 6)
    elif pattern == "spokes3": _gobo_spokes(painter, rad, 3)
    elif pattern == "donut":   _gobo_donut(painter, rad)
    elif pattern == "star5":   _gobo_star(painter, rad, 5)
    elif pattern == "stripes": _gobo_stripes(painter, rad)
    elif pattern == "breakup": _gobo_breakup(painter, rad)
    painter.restore(); painter.setClipping(False)

def _gobo_spokes(painter, rad, n):
    sw = math.radians(360/n*0.32)
    for k in range(n):
        a = math.radians(k*360/n); a0,a1 = a-sw/2, a+sw/2
        path = QPainterPath(); path.moveTo(0,0)
        path.lineTo(rad*math.cos(a0), rad*math.sin(a0))
        for s in range(1,9):
            t = a0+(a1-a0)*s/8; path.lineTo(rad*math.cos(t), rad*math.sin(t))
        path.closeSubpath(); painter.drawPath(path)
    painter.drawEllipse(QPointF(0,0), rad*0.12, rad*0.12)

def _gobo_donut(painter, rad):
    p = QPainterPath(); p.addEllipse(QPointF(0,0),rad*.92,rad*.92)
    h = QPainterPath(); h.addEllipse(QPointF(0,0),rad*.38,rad*.38)
    painter.drawPath(p.subtracted(h))

def _gobo_star(painter, rad, n):
    outer,inner = rad*.88, rad*.38
    pts = [QPointF((outer if k%2==0 else inner)*math.cos(math.radians(k*180/n-90)),
                   (outer if k%2==0 else inner)*math.sin(math.radians(k*180/n-90)))
           for k in range(n*2)]
    path = QPainterPath(); path.addPolygon(QPolygonF(pts)); path.closeSubpath()
    full = QPainterPath(); full.addEllipse(QPointF(0,0),outer,outer)
    painter.drawPath(full.subtracted(path))

def _gobo_stripes(painter, rad):
    sw = rad*0.18
    for k in range(-4,5):
        off = k*rad*0.44; p = QPainterPath()
        p.addRect(QRectF(off-sw/2,-rad,sw,rad*2)); painter.drawPath(p)

def _gobo_breakup(painter, rad):
    for ox,oy,rw,rh in [
        (0.55,0.10,0.20,0.12),(-0.50,0.30,0.22,0.14),(0.15,-0.55,0.18,0.10),
        (-0.20,-0.40,0.25,0.16),(0.60,-0.30,0.16,0.10),(-0.60,-0.20,0.20,0.12),
        (0.00,0.65,0.22,0.13),(0.35,0.50,0.15,0.09),(-0.35,0.55,0.18,0.11),
        (0.70,0.00,0.14,0.09),(-0.70,0.10,0.16,0.10),(0.10,-0.70,0.20,0.12),
    ]:
        painter.drawEllipse(QPointF(ox*rad,oy*rad), rw*rad, rh*rad)


# ─────────────────────────────────────────────────────────────────────────────
# Moving head geometry
# ─────────────────────────────────────────────────────────────────────────────

def _mh_geometry(p):
    x, z   = p['x'], p['z']
    hang_y = p.get('fixture_height', 7.0)
    pan    = p.get('pan',  32768)
    tilt   = p.get('tilt', 32768)
    pan_angle = (pan  - 32768) / 32768.0 * math.pi
    theta     = (tilt - 32768) / 32768.0 * math.pi * 0.75
    # Beam direction: tilt forward then pan around Y
    # (0,-1,0) → tilt → (0,-cos θ, sin θ) → rotate Y by pan_angle
    beam_dx = math.sin(pan_angle) * math.sin(theta)
    beam_dy = -math.cos(theta)
    beam_dz = math.cos(pan_angle) * math.sin(theta)
    arm_y  = hang_y - 0.52
    lens_y = arm_y - 0.20
    # Floor intersection — capped to visible area
    if abs(beam_dy) > 0.05:
        t = min(lens_y / (-beam_dy), 8.0)
    else:
        t = 8.0
    floor_x = max(-11.0, min(11.0, x + beam_dx * t))
    floor_z = max(-8.0,  min(13.0, z + beam_dz * t))
    return {
        'hang_y': hang_y, 'arm_y': arm_y, 'lens_y': lens_y,
        'lens_x': x, 'lens_z': z,
        'beam_dir': (beam_dx, beam_dy, beam_dz),
        'floor': (floor_x, floor_z),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Human silhouettes
# ─────────────────────────────────────────────────────────────────────────────

def _draw_human(painter, pt_fn, x, z, tint=None):
    """
    Silhouette humaine haute qualité : contour anatomique projeté en 3D,
    gradient rim-light côté scène, ombre au sol.
    """
    p_top  = pt_fn(x, 1.84, z)
    p_foot = pt_fn(x, 0.00, z)
    if not (p_top and p_foot):
        return
    total_h = abs(p_foot.y() - p_top.y())
    if total_h < 7:          # trop petit pour être lisible
        return

    # ── Contour du corps (dx en m, y en m) — sens horaire depuis tête ──
    # Côté droit d'abord, puis côté gauche en remontant
    _O = [
        # Tête
        ( 0.000, 1.840), ( 0.092, 1.820), ( 0.128, 1.754),
        ( 0.128, 1.660), ( 0.088, 1.575),
        # Cou → épaule droite
        ( 0.064, 1.552), ( 0.235, 1.458),
        # Bras droit — extérieur
        ( 0.408, 1.278), ( 0.434, 1.038), ( 0.398, 0.848),
        # Bras droit — intérieur (remontée du poignet)
        ( 0.272, 0.828), ( 0.210, 0.948),
        # Flanc droit + hanche
        ( 0.190, 0.928),
        # Jambe droite — extérieur
        ( 0.208, 0.524), ( 0.198, 0.008),
        # Jambe droite — intérieur
        ( 0.076, 0.008), ( 0.054, 0.504),
        # Entrejambe
        ( 0.000, 0.868),
        # Jambe gauche — intérieur
        (-0.054, 0.504), (-0.076, 0.008),
        # Jambe gauche — extérieur
        (-0.198, 0.008), (-0.208, 0.524),
        # Flanc gauche + hanche
        (-0.190, 0.928), (-0.210, 0.948),
        # Bras gauche — intérieur
        (-0.272, 0.828), (-0.398, 0.848),
        # Bras gauche — extérieur
        (-0.434, 1.038), (-0.408, 1.278),
        # Épaule gauche → cou
        (-0.235, 1.458), (-0.064, 1.552),
        # Tête gauche
        (-0.088, 1.575), (-0.128, 1.660),
        (-0.128, 1.754), (-0.092, 1.820),
    ]

    pts = [pt_fn(x + dx, y, z) for dx, y in _O]
    if any(p is None for p in pts):
        return

    # Centre tête pour le dessin de la tête séparée
    p_hc   = pt_fn(x, 1.700, z)
    head_r = total_h * 0.072

    painter.save()

    # ── 1. Ombre au sol (ellipse dégradée) ──────────────────────────────
    p_sh = pt_fn(x, 0.006, z)
    if p_sh:
        sw = total_h * 0.21
        sg = QRadialGradient(p_sh, sw)
        sg.setColorAt(0.0, QColor(0, 0, 0, 130))
        sg.setColorAt(1.0, QColor(0, 0, 0,   0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(sg))
        painter.drawEllipse(p_sh, sw, sw * 0.20)

    # ── 2. Corps — path rempli ───────────────────────────────────────────
    body = QPainterPath()
    body.moveTo(pts[0])
    for p in pts[1:]:
        body.lineTo(p)
    body.closeSubpath()

    # Dégradé horizontal : rim-light violet côté cour → noir côté jardin
    p_r = pts[6]   # épaule droite
    p_l = pts[29]  # épaule gauche
    rim = QLinearGradient(p_r, p_l)
    rim.setColorAt(0.00, QColor( 98,  86, 148, 255))
    rim.setColorAt(0.20, QColor( 50,  44,  78, 255))
    rim.setColorAt(0.55, QColor( 22,  19,  34, 255))
    rim.setColorAt(1.00, QColor( 13,  11,  20, 255))

    painter.setBrush(QBrush(rim))
    painter.setPen(Qt.NoPen)
    painter.drawPath(body)

    # ── 3. Liseré lumineux (contour fin) ────────────────────────────────
    ew = max(0.6, total_h * 0.010)
    painter.setPen(QPen(QColor(112, 96, 168, 150), ew,
                        Qt.SolidLine, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(body)

    # ── 4. Tête — sphère séparée plus lumineuse ──────────────────────────
    if p_hc and head_r > 2.5:
        hg = QRadialGradient(
            QPointF(p_hc.x() - head_r * 0.22,
                    p_hc.y() - head_r * 0.28),
            head_r * 1.40)
        hg.setColorAt(0.0, QColor( 75,  66, 112))
        hg.setColorAt(0.5, QColor( 38,  34,  60))
        hg.setColorAt(1.0, QColor( 20,  17,  30))
        painter.setBrush(QBrush(hg))
        painter.setPen(QPen(QColor(90, 78, 138, 120),
                            max(0.5, head_r * 0.09)))
        painter.drawEllipse(p_hc, head_r, head_r * 1.10)

        # Point lumineux spéculaire (highlight de scène)
        if head_r > 5:
            hl_r = max(1.0, head_r * 0.18)
            painter.setBrush(QBrush(QColor(180, 165, 230, 140)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(
                QPointF(p_hc.x() - head_r * 0.26,
                        p_hc.y() - head_r * 0.30),
                hl_r, hl_r * 0.70)

    painter.restore()


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

TRUSS_Y = 7.0


# ─────────────────────────────────────────────────────────────────────────────
# 3D Canvas
# ─────────────────────────────────────────────────────────────────────────────

class _Canvas3D(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self._theta   = 0.30
        self._phi     = 0.55
        self._radius  = 22.0
        # Drag state
        self._drag       = False
        self._drag_moved = False
        self._last       = QPoint()
        self._press_pos  = QPoint()
        # Data
        self._projectors     = []
        self._sel            = set()   # set of int indices (stables entre refreshes)
        self._move_callback  = None    # callable(selected_indices)
        # Gobo animation timer
        self._rot_timer = QTimer(self)
        self._rot_timer.timeout.connect(self.update)

    def set_projectors(self, data):
        self._projectors = data
        has_rot = any(p.get('gobo_slot_idx', 0) > 0 and p.get('gobo_rotation', 0) != 0
                      for p in data)
        if has_rot and not self._rot_timer.isActive():
            self._rot_timer.start(40)
        elif not has_rot and self._rot_timer.isActive():
            self._rot_timer.stop()
        self.update()

    # ── Camera helpers ────────────────────────────────────────────────────────

    def _camera_pos(self):
        return (
            self._radius * math.sin(self._phi) * math.sin(self._theta),
            self._radius * math.cos(self._phi),
            self._radius * math.sin(self._phi) * math.cos(self._theta),
        )

    def _camera_frame(self):
        """Returns (forward, right, up) unit vectors for the current camera."""
        ex, ey, ez = self._camera_pos()
        tx, ty, tz = 0.0, 3.0, 0.0
        fx, fy, fz = tx-ex, ty-ey, tz-ez
        fl = math.sqrt(fx*fx+fy*fy+fz*fz)
        fx, fy, fz = fx/fl, fy/fl, fz/fl
        # right = forward × (0,1,0)
        rx, ry, rz = -fz, 0.0, fx
        rl = math.sqrt(rx*rx+rz*rz) or 1e-9
        rx /= rl; rz /= rl
        # up = right × forward
        ux = ry*fz - rz*fy; uy = rz*fx - rx*fz; uz = rx*fy - ry*fx
        return (fx,fy,fz), (rx,ry,rz), (ux,uy,uz)

    # ── Inverse projection ────────────────────────────────────────────────────

    def _screen_to_floor(self, sx, sy):
        """Return (world_x, world_z) for a screen point projected onto y=0, or None."""
        W = max(self.width(), 1); H = max(self.height(), 1)
        ex, ey, ez = self._camera_pos()
        (fx,fy,fz), (rx,ry,rz), (ux,uy,uz) = self._camera_frame()
        ndx = sx/W*2 - 1
        ndy = 1 - sy/H*2
        tan_h = math.tan(math.radians(52)*0.5)
        asp   = W / H
        dx = fx + ndx*tan_h*asp*rx + ndy*tan_h*ux
        dy = fy + ndx*tan_h*asp*ry + ndy*tan_h*uy
        dz = fz + ndx*tan_h*asp*rz + ndy*tan_h*uz
        if abs(dy) < 1e-6: return None
        t = -ey / dy
        if t < 0: return None
        return ex + dx*t, ez + dz*t

    def _fixture_at_screen(self, sx, sy):
        """Return index of fixture body closest to (sx, sy) within 28px, or None."""
        mvp, W, H = self._make_mvp()
        best_d, best_i = 28.0, None
        for i, p in enumerate(self._projectors):
            hy = p.get('fixture_height', TRUSS_Y)
            ftype = p.get('fixture_type', '')
            if ftype == 'Moving Head':
                check_y = hy - 0.35
            else:
                check_y = hy - 0.52   # lentille PAR / wash
            sp = self._pt(mvp, W, H, p['x'], check_y, p['z'])
            if not sp: continue
            d = math.hypot(sx - sp.x(), sy - sp.y())
            if d < best_d:
                best_d = d; best_i = i
        return best_i

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos  = e.pos()
            self._drag_moved = False
            self._drag       = False
            self._last       = e.pos()
        elif e.button() == Qt.RightButton:
            pass  # handled in contextMenuEvent

    def mouseMoveEvent(self, e):
        if not (e.buttons() & Qt.LeftButton):
            return
        dx = e.pos().x() - self._last.x()
        dy = e.pos().y() - self._last.y()
        total_dx = e.pos().x() - self._press_pos.x()
        total_dy = e.pos().y() - self._press_pos.y()
        if not self._drag_moved and (abs(total_dx) > 4 or abs(total_dy) > 4):
            self._drag_moved = True
            self._drag = True
        if self._drag:
            self._theta -= dx * 0.007
            self._phi    = max(0.08, min(1.45, self._phi + dy * 0.007))
            self._last   = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if not self._drag_moved:
                sx, sy = e.pos().x(), e.pos().y()
                fix_i  = self._fixture_at_screen(sx, sy)
                ctrl   = bool(e.modifiers() & Qt.ControlModifier)
                if fix_i is not None:
                    if ctrl:
                        if fix_i in self._sel:
                            self._sel.discard(fix_i)
                        else:
                            self._sel.add(fix_i)
                    else:
                        self._sel = set() if self._sel == {fix_i} else {fix_i}
                else:
                    if not ctrl:
                        self._sel.clear()
                self.update()
                if self._move_callback:
                    self._move_callback(self._selected_indices())
            self._drag = False
            self._drag_moved = False

    def contextMenuEvent(self, e):
        e.accept()

    def wheelEvent(self, e):
        self._radius = max(8, min(60, self._radius - e.angleDelta().y() * 0.02))
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._sel.clear()
            self.update()
            if self._move_callback:
                self._move_callback([])

    def _selected_indices(self):
        """Return sorted list of valid selected indices."""
        n = len(self._projectors)
        self._sel = {i for i in self._sel if i < n}
        return sorted(self._sel)

    # ── Projection ────────────────────────────────────────────────────────────

    def _make_mvp(self):
        W, H = max(self.width(), 1), max(self.height(), 1)
        ex, ey, ez = self._camera_pos()
        view = _look_at((ex, ey, ez), (0, 3, 0), (0, 1, 0))
        proj = _perspective(52, W/H, 0.5, 200)
        return _mat_mul(proj, view), W, H

    def _pt(self, mvp, W, H, x, y, z):
        xc, yc, zc, w = _transform(mvp, x, y, z)
        if abs(w) < 1e-6: return None
        ndx, ndy = xc/w, yc/w
        if abs(ndx) > 2.5 or abs(ndy) > 2.5: return None
        return QPointF((ndx*0.5+0.5)*W, (1-(ndy*0.5+0.5))*H)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()

        bg = QLinearGradient(0, 0, 0, H)
        bg.setColorAt(0, QColor("#0d0d14")); bg.setColorAt(1, QColor("#080810"))
        painter.fillRect(0, 0, W, H, QBrush(bg))

        mvp, W, H = self._make_mvp()
        def pt(x, y, z): return self._pt(mvp, W, H, x, y, z)
        def line(p1, p2, col, w=1.0):
            if p1 and p2:
                painter.setPen(QPen(QColor(col), w)); painter.drawLine(p1, p2)

        # ── Stage cyc — fond de scène ─────────────────────────────────────
        _cyc = [pt(-10,0,-5), pt(10,0,-5), pt(10,9.5,-5), pt(-10,9.5,-5)]
        if all(_cyc):
            _gc = QLinearGradient(_cyc[0], _cyc[2])
            _gc.setColorAt(0.0, QColor(16,12,24)); _gc.setColorAt(0.5, QColor(24,19,38))
            _gc.setColorAt(1.0, QColor(10,8,16))
            painter.setBrush(QBrush(_gc)); painter.setPen(Qt.NoPen)
            painter.drawPolygon(QPolygonF(_cyc))
            # Plis verticaux de rideau
            painter.setPen(QPen(QColor(9,7,14), 1))
            for _xi in range(-9, 10):
                _c1 = pt(float(_xi), 0.0, -5.); _c2 = pt(float(_xi), 9.5, -5.)
                if _c1 and _c2: painter.drawLine(_c1, _c2)
            # Bord supérieur de la pendrille
            _top_l = pt(-10, 9.5, -5.); _top_r = pt(10, 9.5, -5.)
            if _top_l and _top_r:
                painter.setPen(QPen(QColor(35,28,52), 1.5)); painter.drawLine(_top_l, _top_r)

        # ── Sol scène — parquet bois chaud ────────────────────────────────
        _sf = [pt(-9,0,-5), pt(9,0,-5), pt(9,0,6), pt(-9,0,6)]
        if all(_sf):
            _gf = QLinearGradient(_sf[0], _sf[2])
            _gf.setColorAt(0.0, QColor(22,14,8)); _gf.setColorAt(0.45, QColor(30,19,11))
            _gf.setColorAt(1.0, QColor(18,12,7))
            painter.setBrush(QBrush(_gf)); painter.setPen(Qt.NoPen)
            painter.drawPolygon(QPolygonF(_sf))

        # ── Floor grid ────────────────────────────────────────────────────
        painter.setPen(QPen(QColor("#1a1208"), 1))
        for gx in range(-10, 11):
            p1, p2 = pt(gx,0,-7), pt(gx,0,13)
            if p1 and p2: painter.drawLine(p1, p2)
        for gz in range(-7, 14):
            p1, p2 = pt(-10,0,gz), pt(10,0,gz)
            if p1 and p2: painter.drawLine(p1, p2)
        for a,b in [((-9,0,-5),(9,0,-5)),((9,0,-5),(9,0,5.2)),
                    ((9,0,5.2),(-9,0,5.2)),((-9,0,5.2),(-9,0,-5))]:
            line(pt(*a), pt(*b), "#2a1e12", 1.5)
        line(pt(-9,0,5.2), pt(9,0,5.2), "#8866aa", 2.5)

        # ── Jambes de scène (wing curtains) ──────────────────────────────
        for _lx, _lx2 in ((-9.0, -8.5), (9.0, 8.5)):
            for _za, _zb in ((-4.5, -1.5), (-0.5, 2.5)):
                _leg = [pt(_lx, 0, _za), pt(_lx2, 0, _za),
                        pt(_lx2, 7.0, _za), pt(_lx, 7.0, _za)]
                if not all(_leg): continue
                _gleg = QLinearGradient(_leg[0], _leg[2])
                _gleg.setColorAt(0, QColor(6, 5, 8))
                _gleg.setColorAt(1, QColor(12, 10, 16))
                painter.setBrush(QBrush(_gleg))
                painter.setPen(QPen(QColor(18, 16, 24), 0.8))
                # face avant de la jambe (rectangle plat en profondeur)
                _legf = [pt(_lx, 0, _za), pt(_lx, 0, _zb),
                         pt(_lx, 7.0, _zb), pt(_lx, 7.0, _za)]
                if all(_legf):
                    painter.drawPolygon(QPolygonF(_legf))

        # ── Truss ─────────────────────────────────────────────────────────
        def _draw_truss_bar(xa, za, xb, zb, thick=2.5, thin=0.8, n=6):
            DY = 0.38
            CT, CB, CD = "#9090b8", "#5858a0", "#353558"
            p_tl=pt(xa,TRUSS_Y,za); p_tr=pt(xb,TRUSS_Y,zb)
            p_bl=pt(xa,TRUSS_Y-DY,za); p_br=pt(xb,TRUSS_Y-DY,zb)
            # Ombre portée des tubes principaux
            line(p_tl,p_tr,"#0e0e1c",thick+3.5); line(p_bl,p_br,"#0e0e1c",thin+2.0)
            # Diagonales entretoise
            for k in range(n):
                t0,t1 = k/n, (k+1)/n
                def lp(t, top):
                    lxa=xa+(xb-xa)*t; lza=za+(zb-za)*t
                    return pt(lxa, TRUSS_Y+(0 if top else -DY), lza)
                line(lp(t0,True),lp(t1,False),CD,thin)
                line(lp(t1,True),lp(t0,False),CD,thin)
            # Montants verticaux + tubes principaux
            line(p_tl,p_bl,CT,thin*1.5); line(p_tr,p_br,CT,thin*1.5)
            line(p_tl,p_tr,CT,thick);    line(p_bl,p_br,CB,thin+0.5)
            # Reflet aluminium sur le tube supérieur
            line(p_tl,p_tr,"#c8d0ec",max(0.5,thick*0.22))
        cc = "#6868a8"
        for sx in (-9.0, 9.0):
            line(pt(sx,0,-3.8),pt(sx,TRUSS_Y,-3.8),"#0e0e1c",5)
            line(pt(sx,0,-3.8),pt(sx,TRUSS_Y,-3.8),cc,2.2)
            line(pt(sx,0,-3.8),pt(sx,TRUSS_Y,-3.8),"#aab0d0",0.8)
            line(pt(sx,0, 4.0),pt(sx,TRUSS_Y, 4.0),"#0e0e1c",4)
            line(pt(sx,0, 4.0),pt(sx,TRUSS_Y, 4.0),cc,1.8)
            line(pt(sx,0, 4.0),pt(sx,TRUSS_Y, 4.0),"#aab0d0",0.7)
        _draw_truss_bar(-9,-3.8, 9,-3.8, thick=2.5)
        _draw_truss_bar(-9, 4.0, 9, 4.0, thick=2.0)
        line(pt(-9,TRUSS_Y,-3.8),pt(-9,TRUSS_Y,4.0),cc,1.2)
        line(pt( 9,TRUSS_Y,-3.8),pt( 9,TRUSS_Y,4.0),cc,1.2)

        # ── Precompute ────────────────────────────────────────────────────
        prjs = self._projectors
        # Tri back-to-front par distance caméra (algorithme du peintre correct
        # quelle que soit l'orientation de la caméra).
        _ex, _ey, _ez = self._camera_pos()
        def _cam_dist_sq(p):
            py = p.get('fixture_height', TRUSS_Y) * 0.5
            return (p['x']-_ex)**2 + (py-_ey)**2 + (p['z']-_ez)**2
        sorted_prjs = sorted(prjs, key=_cam_dist_sq, reverse=True)
        mh_geos    = {id(p): _mh_geometry(p)
                      for p in prjs if p.get('fixture_type','') == 'Moving Head'}
        sel_set  = self._sel
        proj_idx = {id(p): i for i, p in enumerate(prjs)}

        def _src(p):
            """(src_y, src_x, src_z, (floor_x, floor_z))"""
            if p.get('fixture_type','') == 'Moving Head':
                g = mh_geos.get(id(p))
                if g: return g['lens_y'], g['lens_x'], g['lens_z'], g['floor']
            hy = p.get('fixture_height', TRUSS_Y)
            x, z = p['x'], p['z']
            fx = max(-11.0,min(11.0, x+(p.get('pan',32768)-32768)/32768.0*4.0))
            fz = max(-8.0, min(13.0, z+(p.get('tilt',32768)-32768)/32768.0*3.0))
            return hy-0.25, x, z, (fx, fz)

        # ── Pass A — floor pools ───────────────────────────────────────────
        for p in sorted_prjs:
            lvl = max(0.0, min(1.0, p['level']/100.0))
            if lvl < 0.03: continue
            r,g,b = p['r'],p['g'],p['b']
            _,_,_, (fx,fz) = _src(p)
            pool_r = 0.5 + 2.2*lvl
            pool_pts = [pp for pp in
                        (pt(fx+pool_r*math.cos(math.radians(a)), 0.01,
                            fz+pool_r*math.sin(math.radians(a)))
                         for a in range(0,360,24)) if pp]
            cp = pt(fx, 0.01, fz)
            if cp and len(pool_pts) >= 3:
                rs = max((math.hypot(p2.x()-cp.x(), p2.y()-cp.y()) for p2 in pool_pts), default=10)
                rg = QRadialGradient(cp, max(rs,4))
                rg.setColorAt(0.0, QColor(r,g,b,int(170*lvl)))
                rg.setColorAt(0.5, QColor(r,g,b,int(70*lvl)))
                rg.setColorAt(1.0, QColor(r,g,b,0))
                painter.setBrush(QBrush(rg)); painter.setPen(Qt.NoPen)
                painter.drawPolygon(QPolygonF(pool_pts))

        # ── Pass B — halo volumétrique ─────────────────────────────────────
        for p in sorted_prjs:
            lvl = max(0.0, min(1.0, p['level']/100.0))
            if lvl < 0.03: continue
            r,g,b = p['r'],p['g'],p['b']
            sy, sx2, sz, (fx,fz) = _src(p)
            tip = pt(sx2, sy, sz)
            if not tip: continue
            sh = (0.12+1.6*lvl)*2.2
            bc = pt(fx,0.02,fz); bl = pt(fx-sh,0.02,fz); br = pt(fx+sh,0.02,fz)
            if bl and br and bc:
                gh = QLinearGradient(tip, bc)
                gh.setColorAt(0.0, QColor(r,g,b,int(40*lvl))); gh.setColorAt(1.0, QColor(r,g,b,0))
                painter.setBrush(QBrush(gh)); painter.setPen(Qt.NoPen)
                painter.drawPolygon(QPolygonF([tip,bl,br]))

        # ── Pass C — faisceau principal + gobo ────────────────────────────
        now = _time.time()
        for p in sorted_prjs:
            lvl = max(0.0, min(1.0, p['level']/100.0))
            r,g,b = p['r'],p['g'],p['b']
            sy, sx2, sz, (fx,fz) = _src(p)
            tip  = pt(sx2, sy, sz)
            sp   = 0.12 + 1.6*lvl
            bc   = pt(fx, 0.02, fz)
            bl   = pt(fx-sp, 0.02, fz)
            br_  = pt(fx+sp, 0.02, fz)
            if not (tip and bl and br_ and bc): continue
            grad = QLinearGradient(tip, bc)
            grad.setColorAt(0.0, QColor(r,g,b,int(220*lvl)))
            grad.setColorAt(0.6, QColor(r,g,b,int(80*lvl)))
            grad.setColorAt(1.0, QColor(r,g,b,int(15*lvl)))
            painter.setBrush(QBrush(grad)); painter.setPen(Qt.NoPen)
            painter.drawPolygon(QPolygonF([tip,bl,br_]))
            if lvl > 0.04:
                ea = min(255,int(180*lvl))
                painter.setPen(QPen(QColor(r,g,b,ea),1.0))
                painter.drawLine(tip,bl); painter.drawLine(tip,br_)
            slot_idx = p.get('gobo_slot_idx',0)
            if slot_idx > 0 and lvl > 0.04:
                gdmx = p.get('gobo_rotation',0)
                spd  = (gdmx-128)/128.0*120.0 if gdmx else 0.0
                _draw_gobo_on_beam(painter, tip, bl, br_, slot_idx, (now*spd)%360.0, lvl)
            # Rayon central lumineux — cœur du faisceau
            if lvl > 0.06 and tip and bc:
                _ca = int(min(255, 195*lvl))
                painter.setPen(QPen(QColor(min(255,r+85),min(255,g+85),min(255,b+85),_ca),
                                    max(0.6, lvl*1.8), Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(tip, bc)

        # ── Pass D — corps de fixture ──────────────────────────────────────
        for p in sorted_prjs:
            x, z = p['x'], p['z']
            lvl  = max(0.0, min(1.0, p['level']/100.0))
            r,g,b = p['r'],p['g'],p['b']
            is_mh  = p.get('fixture_type','') == 'Moving Head'
            hang_y = p.get('fixture_height', TRUSS_Y)
            is_sel = proj_idx.get(id(p), -1) in sel_set

            if is_mh:
                geo      = mh_geos.get(id(p))
                arm_y_w  = geo['arm_y']   if geo else hang_y - 0.52
                bd       = geo['beam_dir'] if geo else (0, -1, 0)

                _GC = {'face':'#ff8844','contre':'#4488ff','douche1':'#44cc88',
                       'douche2':'#ffcc44','douche3':'#ff4488','lat':'#aa55ff',
                       'lyre':'#ee44bb','barre':'#44aaff'}
                gc = QColor(_GC.get(p.get('group',''), '#5577aa'))

                pan_a  = (p.get('pan',  32768) - 32768) / 32768.0 * math.pi
                cp, sp2 = math.cos(pan_a), math.sin(pan_a)

                BAR_W  = 0.40   # mounting bar half-width (m)
                BAR_H  = 0.11   # bar height (m)
                YW     = 0.27   # yoke half-width  (centre → arm)
                YAL    = 0.38   # yoke arm length  (vertical drop)
                HEAD_OFF = 0.22 # head offset from pivot along beam

                bar_attach_y = hang_y - BAR_H
                pivot_y      = bar_attach_y - YAL

                # Bar corners — rotated by body_rotation around vertical axis
                _br  = math.radians(p.get('body_rotation', 0.0))
                _bdx = math.cos(_br) * BAR_W
                _bdz = math.sin(_br) * BAR_W
                bar_tl = pt(x - _bdx, hang_y,       z - _bdz)
                bar_tr = pt(x + _bdx, hang_y,       z + _bdz)
                bar_bl = pt(x - _bdx, bar_attach_y, z - _bdz)
                bar_br = pt(x + _bdx, bar_attach_y, z + _bdz)

                # Yoke arm 3-D positions — rotate with pan around Y axis
                lx = x - YW * cp;  lz = z - YW * sp2
                rx = x + YW * cp;  rz = z + YW * sp2

                arm_l_top = pt(lx, bar_attach_y, lz)
                arm_l_bot = pt(lx, pivot_y,      lz)
                arm_r_top = pt(rx, bar_attach_y, rz)
                arm_r_bot = pt(rx, pivot_y,      rz)

                # Head: offset from pivot centre along beam direction
                hx = x  + bd[0] * HEAD_OFF
                hy = pivot_y + bd[1] * HEAD_OFF
                hz = z  + bd[2] * HEAD_OFF
                hp       = pt(hx, hy, hz)
                pivot_pt = pt(x,  pivot_y, z)

                scale_px = 12.0
                if bar_tl and bar_tr:
                    scale_px = max(6.0, abs(bar_tr.x() - bar_tl.x()) / (2 * BAR_W))

                # ── Mounting bar ──────────────────────────────────────────────
                if bar_tl and bar_tr and bar_bl and bar_br:
                    g_bar = QLinearGradient(bar_tl, bar_bl)
                    g_bar.setColorAt(0.0, gc.lighter(175))
                    g_bar.setColorAt(0.5, gc)
                    g_bar.setColorAt(1.0, gc.darker(145))
                    painter.setBrush(QBrush(g_bar))
                    painter.setPen(QPen(gc.darker(175), 0.8))
                    painter.drawPolygon(QPolygonF([bar_tl, bar_tr, bar_br, bar_bl]))

                # ── Yoke arms — shadow then colour pass ───────────────────────
                arm_w  = max(3.5, scale_px * 0.10)
                for at, ab in [(arm_l_top, arm_l_bot), (arm_r_top, arm_r_bot)]:
                    if at and ab:
                        painter.setPen(QPen(gc.darker(220), arm_w + 2.0,
                                            Qt.SolidLine, Qt.RoundCap))
                        painter.drawLine(at, ab)
                for at, ab in [(arm_l_top, arm_l_bot), (arm_r_top, arm_r_bot)]:
                    if at and ab:
                        g_arm = QLinearGradient(at, ab)
                        g_arm.setColorAt(0.0, gc.darker(130))
                        g_arm.setColorAt(0.5, gc.lighter(135))
                        g_arm.setColorAt(1.0, gc.darker(115))
                        painter.setPen(QPen(QBrush(g_arm), arm_w,
                                            Qt.SolidLine, Qt.RoundCap))
                        painter.drawLine(at, ab)

                # ── Cross-bar between pivot points ────────────────────────────
                if arm_l_bot and arm_r_bot:
                    painter.setPen(QPen(gc.darker(160),
                                        max(2.0, scale_px * 0.07),
                                        Qt.SolidLine, Qt.RoundCap))
                    painter.drawLine(arm_l_bot, arm_r_bot)

                # ── Pivot screws ──────────────────────────────────────────────
                for ab in (arm_l_bot, arm_r_bot):
                    if ab:
                        pr = max(2.5, scale_px * 0.058)
                        painter.setBrush(QBrush(gc.darker(148)))
                        painter.setPen(QPen(gc.darker(195), 0.7))
                        painter.drawEllipse(ab, pr, pr)

                # ── Connecting rod pivot → head ───────────────────────────────
                if pivot_pt and hp:
                    painter.setPen(QPen(gc.darker(170),
                                        max(1.5, scale_px * 0.042),
                                        Qt.SolidLine, Qt.RoundCap))
                    painter.drawLine(pivot_pt, hp)

                # ── Head ──────────────────────────────────────────────────────
                if hp:
                    head_r = max(6.0, scale_px * 0.14)

                    if is_sel:
                        painter.setBrush(Qt.NoBrush)
                        painter.setPen(QPen(QColor(0, 212, 255, 220), 2.5))
                        painter.drawEllipse(hp, head_r * 1.60, head_r * 1.60)

                    fill_col = QColor(r, g, b) if lvl > 0.04 else gc
                    rg_head  = QRadialGradient(
                        QPointF(hp.x() - head_r * 0.30, hp.y() - head_r * 0.30),
                        head_r * 1.45)
                    rg_head.setColorAt(0.0, fill_col.lighter(172))
                    rg_head.setColorAt(0.5, fill_col)
                    rg_head.setColorAt(1.0, fill_col.darker(162))
                    painter.setBrush(QBrush(rg_head))
                    painter.setPen(QPen(gc.darker(180), 1.0))
                    painter.drawEllipse(hp, head_r, head_r)

                    # Reflector ring
                    painter.setBrush(Qt.NoBrush)
                    painter.setPen(QPen(gc.lighter(148), 1.0))
                    painter.drawEllipse(hp, head_r * 0.70, head_r * 0.70)

                    # Lens
                    lens_r = head_r * 0.46
                    if lvl > 0.04:
                        rg_l = QRadialGradient(
                            QPointF(hp.x() - lens_r * 0.35, hp.y() - lens_r * 0.35),
                            lens_r * 1.6)
                        rg_l.setColorAt(0.0, QColor(min(255,r+160), min(255,g+160), min(255,b+160), 255))
                        rg_l.setColorAt(0.4, QColor(r, g, b, 240))
                        rg_l.setColorAt(1.0, QColor(max(0,r-60), max(0,g-60), max(0,b-60), 180))
                    else:
                        rg_l = QRadialGradient(hp, lens_r * 1.2)
                        rg_l.setColorAt(0.0, QColor(40, 40, 65, 255))
                        rg_l.setColorAt(1.0, QColor(20, 20, 35, 255))
                    painter.setBrush(QBrush(rg_l))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(hp, lens_r, lens_r)

                    # Highlight dot
                    dot_r = max(1.0, head_r * 0.14)
                    painter.setBrush(QBrush(QColor(255, 255, 255, 190)))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(
                        QPointF(hp.x() - lens_r * 0.28, hp.y() - lens_r * 0.28),
                        dot_r, dot_r)

            else:
                # PAR / wash — boîtier cylindrique avec joug (yoke)
                HW = 0.20; HTOP = hang_y - 0.01; HBOT = hang_y - 0.46; LY = hang_y - 0.52
                _br  = math.radians(p.get('body_rotation', 0.0))
                _ydx = math.cos(_br) * HW
                _ydz = math.sin(_br) * HW
                btl = pt(x - _ydx,       HTOP, z - _ydz)
                btr = pt(x + _ydx,       HTOP, z + _ydz)
                bbl = pt(x - _ydx * 0.82, HBOT, z - _ydz * 0.82)
                bbr = pt(x + _ydx * 0.82, HBOT, z + _ydz * 0.82)
                if not (btl and btr and bbl and bbr): continue
                bw_px = max(8.0, abs(btr.x()-btl.x()))
                # Corps métallique — dégradé cylindrique
                _gb = QLinearGradient(btl, btr)
                _gc3 = QColor(52,52,82)
                _gb.setColorAt(0.00, _gc3.darker(162)); _gb.setColorAt(0.12, _gc3.lighter(134))
                _gb.setColorAt(0.42, _gc3);             _gb.setColorAt(0.58, _gc3.darker(112))
                _gb.setColorAt(0.88, _gc3.lighter(120)); _gb.setColorAt(1.00, _gc3.darker(158))
                painter.setBrush(QBrush(_gb)); painter.setPen(QPen(QColor(14,14,24),0.9))
                painter.drawPolygon(QPolygonF([btl,btr,bbr,bbl]))
                # Ligne de jointure centrale
                _cmx = (btl.x()+btr.x())/2
                painter.setPen(QPen(QColor(30,30,50,130),0.7))
                painter.drawLine(QPointF(_cmx,btl.y()), QPointF(_cmx,bbl.y()))
                # Bras du joug (yoke) — U-bracket reliant le collier au corps
                _yoke_col = QColor(58, 58, 90)
                _yw = max(1.8, bw_px * 0.048)
                _ya_l = pt(x - _ydx * 1.05, hang_y - 0.04, z - _ydz * 1.05)
                _ya_r = pt(x + _ydx * 1.05, hang_y - 0.04, z + _ydz * 1.05)
                _yb_l = pt(x - _ydx * 0.92, HBOT + 0.05, z - _ydz * 0.92)
                _yb_r = pt(x + _ydx * 0.92, HBOT + 0.05, z + _ydz * 0.92)
                for _ya, _yb in ((_ya_l, _yb_l), (_ya_r, _yb_r)):
                    if _ya and _yb:
                        painter.setPen(QPen(_yoke_col.darker(130), _yw + 1.5,
                                            Qt.SolidLine, Qt.RoundCap))
                        painter.drawLine(_ya, _yb)
                        painter.setPen(QPen(_yoke_col.lighter(130), _yw,
                                            Qt.SolidLine, Qt.RoundCap))
                        painter.drawLine(_ya, _yb)
                # Collier de fixation omega
                _cpt = pt(x, hang_y+0.06, z)
                if _cpt:
                    painter.setPen(QPen(QColor(62,62,94), max(1.5, bw_px*0.055), Qt.SolidLine, Qt.RoundCap))
                    painter.drawLine(QPointF((btl.x()+btr.x())/2, btl.y()), _cpt)
                    painter.setBrush(QBrush(QColor(74,74,112)))
                    painter.setPen(QPen(QColor(36,36,58),0.8))
                    painter.drawEllipse(_cpt, max(2.5, bw_px*0.085), max(2.5, bw_px*0.085))
                # Face optique — lentille fresnel
                _lpt = pt(x, LY, z)
                if _lpt:
                    _lr = max(4.5, bw_px*0.43); _lry = _lr*0.62
                    if lvl > 0.04:
                        _rgl = QRadialGradient(QPointF(_lpt.x()-_lr*0.26, _lpt.y()-_lr*0.26), _lr*1.5)
                        _rgl.setColorAt(0.0,  QColor(min(255,r+188),min(255,g+188),min(255,b+188),255))
                        _rgl.setColorAt(0.22, QColor(min(255,r+95), min(255,g+95), min(255,b+95),245))
                        _rgl.setColorAt(0.62, QColor(r,g,b,220))
                        _rgl.setColorAt(1.0,  QColor(max(0,r-55),max(0,g-55),max(0,b-55),185))
                    else:
                        _rgl = QRadialGradient(_lpt, _lr*1.1)
                        _rgl.setColorAt(0.0, QColor(50,50,80,255))
                        _rgl.setColorAt(0.5, QColor(32,32,54,255))
                        _rgl.setColorAt(1.0, QColor(16,16,30,255))
                    painter.setBrush(QBrush(_rgl)); painter.setPen(QPen(QColor(12,12,22),0.9))
                    painter.drawEllipse(_lpt, _lr, _lry)
                    # Anneaux fresnel
                    painter.setBrush(Qt.NoBrush)
                    for _rs in (0.74, 0.51):
                        painter.setPen(QPen(QColor(72,72,108,92),0.7))
                        painter.drawEllipse(_lpt, _lr*_rs, _lry*_rs)
                    # Point spéculaire
                    if lvl > 0.04:
                        _hl = max(1.2, _lr*0.18)
                        painter.setBrush(QBrush(QColor(255,255,255,215)))
                        painter.setPen(Qt.NoPen)
                        painter.drawEllipse(QPointF(_lpt.x()-_lr*0.30, _lpt.y()-_lry*0.28), _hl, _hl*0.68)

        # ── HUD ───────────────────────────────────────────────────────────
        painter.setFont(QFont("monospace", 7))
        sel_i = self._selected_indices()
        if sel_i:
            names = [self._projectors[i].get('name') or self._projectors[i].get('group', '?')
                     for i in sel_i]
            label = ', '.join(names[:3]) + ('…' if len(names) > 3 else '')
            painter.setPen(QPen(QColor("#00d4ff"), 1))
            painter.drawText(6, H-18,
                f"  {label}  —  Ctrl+clic: multi-sélection  |  Échap: désélectionner")
        painter.setPen(QPen(QColor("#33334a"), 1))
        painter.drawText(6, H-6, "drag: orbiter  |  scroll: zoom  |  clic fixture: sélectionner")
        painter.end()


# ─────────────────────────────────────────────────────────────────────────────
# Panneau de déplacement de fixtures
# ─────────────────────────────────────────────────────────────────────────────

class _MovePanel(QWidget):
    move_requested = Signal(float, float, float)   # Δx, Δheight, Δz
    deselect_all   = Signal()

    _SPIN_STYLE = """
        QDoubleSpinBox {
            background: #1e1e36; color: #ccccff;
            border: 1px solid #444466; border-radius: 4px;
            padding: 2px 4px; font-size: 12px; min-width: 80px;
        }
        QDoubleSpinBox:focus { border-color: #7777cc; }
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
            width: 18px; background: #252545;
            border-left: 1px solid #444466;
        }
        QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
            background: #353565;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QWidget#movePanel {
                background: rgba(18,18,32,235);
                border: 1px solid #444466;
                border-radius: 8px;
            }
            QPushButton {
                background: #252540; color: #9999cc;
                border: 1px solid #333355; border-radius: 4px;
                font-size: 11px; padding: 4px 10px;
            }
            QPushButton:hover   { background: #303060; color: #ffffff; }
            QPushButton:pressed { background: #1a1a36; }
            QLabel       { color: #8888bb; font-size: 11px; }
            QLabel#title { color: #00d4ff; font-size: 12px; font-weight: bold; }
        """ + self._SPIN_STYLE)
        self.setObjectName("movePanel")

        self._title = QLabel("0 sélectionné")
        self._title.setObjectName("title")
        self._title.setAlignment(Qt.AlignCenter)

        self._updating = False
        self._ref = {'x': 0.0, 'h': TRUSS_Y, 'z': 0.0}

        def spin(lo, hi, suffix):
            s = QDoubleSpinBox()
            s.setRange(lo, hi); s.setSingleStep(0.25)
            s.setDecimals(2);   s.setSuffix(suffix)
            return s

        self._spin_x = spin(-9.0,  9.0, " m")
        self._spin_z = spin(-5.0,  5.0, " m")
        self._spin_h = spin( 1.0, 12.0, " m")

        self._spin_x.valueChanged.connect(self._on_x)
        self._spin_z.valueChanged.connect(self._on_z)
        self._spin_h.valueChanged.connect(self._on_h)

        def row(label, widget):
            hl = QHBoxLayout(); hl.setSpacing(8)
            lbl = QLabel(label); lbl.setFixedWidth(80)
            hl.addWidget(lbl); hl.addWidget(widget)
            return hl

        sep1 = QFrame(); sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color:#333355;")
        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color:#333355;")

        desel = QPushButton("✕  Désélectionner")
        desel.clicked.connect(self.deselect_all)

        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(12, 10, 12, 10)
        vlay.setSpacing(6)
        vlay.addWidget(self._title)
        vlay.addWidget(sep1)
        vlay.addLayout(row("X (scène) :", self._spin_x))
        vlay.addLayout(row("Profondeur :", self._spin_z))
        vlay.addLayout(row("Hauteur :",   self._spin_h))
        vlay.addWidget(sep2)
        vlay.addWidget(desel)
        self.adjustSize()

    def _on_x(self, v):
        if self._updating: return
        self.move_requested.emit(v - self._ref['x'], 0.0, 0.0)
        self._ref['x'] = v

    def _on_z(self, v):
        if self._updating: return
        self.move_requested.emit(0.0, 0.0, v - self._ref['z'])
        self._ref['z'] = v

    def _on_h(self, v):
        if self._updating: return
        self.move_requested.emit(0.0, v - self._ref['h'], 0.0)
        self._ref['h'] = v

    def set_position(self, x_world, height, z_world):
        self._updating = True
        self._spin_x.setValue(round(x_world, 2))
        self._spin_z.setValue(round(z_world, 2))
        self._spin_h.setValue(round(height,  2))
        self._ref = {'x': x_world, 'h': height, 'z': z_world}
        self._updating = False

    def set_count(self, n):
        txt = "1 projecteur sélectionné" if n == 1 else f"{n} projecteurs sélectionnés"
        self._title.setText(txt)


# ─────────────────────────────────────────────────────────────────────────────
# Fenêtre flottante
# ─────────────────────────────────────────────────────────────────────────────

class Plan3DWindow(QMainWindow):
    """Fenêtre flottante 3D du plan de feu (rendu Python/Qt pur)."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Plan de feu 3D")
        self.resize(900, 580)
        self.setStyleSheet("background:#0d0d14;")
        self._canvas = _Canvas3D()
        self._canvas._move_callback = self._on_selection_changed
        self.setCentralWidget(self._canvas)
        self._move_panel = _MovePanel(self)
        self._move_panel.move_requested.connect(self._move_selected)
        self._move_panel.deselect_all.connect(self._deselect_all)
        self._move_panel.hide()


    # ── Selection / movement ─────────────────────────────────────────────────

    def _on_selection_changed(self, indices):
        if indices:
            self._move_panel.set_count(len(indices))
            self._update_panel_values(indices)
            self._move_panel.show()
            self._move_panel.raise_()
            self._reposition_panel()
        else:
            self._move_panel.hide()

    def _update_panel_values(self, indices):
        mw = self.parent()
        if not mw or not indices: return
        projs = getattr(mw, 'projectors', [])
        i = indices[0]
        if i >= len(projs): return
        p    = projs[i]
        p3x  = getattr(p, 'pos_3d_x', None)
        p3z  = getattr(p, 'pos_3d_z', None)
        if p3x is None:
            cx, cy = self._norm_pos(projs, i)
            p3x = (cx - 0.5) * 18.0
        if p3z is None:
            cx, cy = self._norm_pos(projs, i)
            p3z = (cy - 0.5) * 10.0
        fh = getattr(p, 'fixture_height', TRUSS_Y) or TRUSS_Y
        self._move_panel.set_position(p3x, fh, p3z)

    def _reposition_panel(self):
        self._move_panel.adjustSize()
        pw = self._move_panel
        pw.move(self.width() - pw.width() - 16, 16)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._move_panel.isHidden():
            self._reposition_panel()

    def _deselect_all(self):
        self._canvas._sel.clear()
        self._canvas.update()
        self._move_panel.hide()

    def _move_selected(self, dx, dheight, dz):
        mw = self.parent()
        if not mw:
            return
        projs = getattr(mw, 'projectors', [])
        for i in self._canvas._selected_indices():
            if i >= len(projs):
                continue
            p = projs[i]
            # Initialise pos_3d depuis le plan 2D au premier déplacement
            if getattr(p, 'pos_3d_x', None) is None:
                cx, cy = self._norm_pos(projs, i)
                p.pos_3d_x = (cx - 0.5) * 18.0
            if getattr(p, 'pos_3d_z', None) is None:
                cx, cy = self._norm_pos(projs, i)
                p.pos_3d_z = (cy - 0.5) * 10.0
            if dx != 0.0:
                p.pos_3d_x = max(-9.0, min(9.0, p.pos_3d_x + dx))
            if dz != 0.0:
                p.pos_3d_z = max(-5.0, min(5.0, p.pos_3d_z + dz))
            if dheight != 0.0:
                fh = getattr(p, 'fixture_height', TRUSS_Y) + dheight
                p.fixture_height = max(1.0, min(12.0, fh))
        if hasattr(mw, 'dmx') and mw.dmx:
            mw.dmx.update_from_projectors(projs)
        self.refresh(projs)
        self._update_panel_values(self._canvas._selected_indices())
        if hasattr(mw, 'save_dmx_patch_config'):
            mw.save_dmx_patch_config()

    # ── Right-click fixture menu (conservé pour usage futur) ─────────────────

    def _show_fixture_menu(self, proj_idx, global_pos):
        mw = self.parent()
        if not mw or proj_idx >= len(getattr(mw, 'projectors', [])):
            return
        proj = mw.projectors[proj_idx]
        name = getattr(proj, 'name', '') or getattr(proj, 'group', '?')

        def _set(attr, val):
            setattr(proj, attr, val)
            if hasattr(mw, 'dmx') and mw.dmx:
                mw.dmx.update_from_projectors(mw.projectors)
            self.refresh(mw.projectors)

        menu = QMenu(self._canvas)
        menu.setStyleSheet("""
            QMenu { background:#1a1a2a; color:#ccccff; border:1px solid #5555aa;
                    border-radius:6px; padding:4px; }
            QMenu::item { padding:4px 20px; }
            QMenu::item:selected { background:#2a2a4a; border-radius:3px; }
            QMenu::separator { height:1px; background:#333355; margin:3px 0; }
            QMenu::item:disabled { color:#666688; }
        """)

        title = menu.addAction(f"  {name}  —  Moving Head")
        title.setEnabled(False)
        menu.addSeparator()

        # Prism toggle
        prism_val = getattr(proj, 'prism', 0)
        a_prism   = menu.addAction(("✦  Prisme  ●  ON" if prism_val > 0 else "✦  Prisme  ○  OFF"))
        a_prism.setCheckable(True); a_prism.setChecked(prism_val > 0)
        a_prism.triggered.connect(lambda chk: _set('prism', 128 if chk else 0))

        def _slider_action(label_text, attr):
            w = QWidget(); w.setStyleSheet("background:#1a1a2a; padding:0px;")
            hl = QHBoxLayout(w); hl.setContentsMargins(14,3,14,3); hl.setSpacing(8)
            lbl = QLabel(label_text); lbl.setFixedWidth(116)
            lbl.setStyleSheet("color:#9999cc; font-size:11px;")
            sl  = QSlider(Qt.Horizontal); sl.setRange(0,255)
            sl.setValue(int(getattr(proj, attr, 0)))
            sl.setFixedWidth(130)
            sl.setStyleSheet(
                "QSlider::groove:horizontal{background:#2a2a44;height:4px;border-radius:2px;}"
                "QSlider::sub-page:horizontal{background:#5566cc;border-radius:2px;}"
                "QSlider::handle:horizontal{background:#8899ff;width:12px;height:12px;"
                "margin:-4px 0;border-radius:6px;}")
            vl  = QLabel(str(int(getattr(proj, attr, 0)))); vl.setFixedWidth(26)
            vl.setStyleSheet("color:#aaaaee; font-size:10px;")
            def on_change(v, _a=attr, _vl=vl): _vl.setText(str(v)); _set(_a, v)
            sl.valueChanged.connect(on_change)
            hl.addWidget(lbl); hl.addWidget(sl); hl.addWidget(vl)
            wa = QWidgetAction(menu); wa.setDefaultWidget(w)
            return wa

        menu.addAction(_slider_action("Rot. prisme", 'prism_rotation'))
        menu.addSeparator()
        menu.addAction(_slider_action("Rot. gobo",   'gobo_rotation'))
        menu.addSeparator()
        menu.addAction(_slider_action("Zoom",        'zoom'))
        menu.addAction(_slider_action("Shutter/Iris",'shutter'))
        menu.addAction(_slider_action("UV",          'uv'))
        menu.addSeparator()

        a_close = menu.addAction("✕  Fermer")
        a_close.triggered.connect(menu.close)

        menu.exec(global_pos)

    # ── Aim at floor ──────────────────────────────────────────────────────────

    def _aim_at_floor(self, proj_idx, floor_x, floor_z):
        """Compute pan/tilt so that MH fixture[proj_idx] aims at (floor_x, floor_z)."""
        mw = self.parent()
        if not mw or proj_idx >= len(getattr(mw, 'projectors', [])):
            return
        proj = mw.projectors[proj_idx]
        if getattr(proj, 'fixture_type', '') != 'Moving Head':
            return

        data   = self._canvas._projectors[proj_idx]
        fx, fz = data['x'], data['z']
        fh     = data.get('fixture_height', TRUSS_Y)
        lens_y = fh - 0.72   # approximate lens height

        # Beam direction from lens to floor target
        dx = floor_x - fx
        dy = -lens_y           # floor at y=0
        dz = floor_z - fz
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 1e-6:
            return
        dx /= dist; dy /= dist; dz /= dist

        # Invert: beam=(sin(pan)*sin(θ), -cos(θ), cos(pan)*sin(θ))
        theta     = math.acos(max(-1.0, min(1.0, -dy)))
        sin_theta = math.sin(theta)
        pan_angle = math.atan2(dx, dz) if abs(sin_theta) > 1e-6 else 0.0

        # Clamp to physical range
        theta     = max(0.0, min(math.pi * 0.75, theta))
        pan_angle = max(-math.pi, min(math.pi, pan_angle))

        proj.pan  = max(0, min(65535, int(pan_angle / math.pi * 32768 + 32768)))
        proj.tilt = max(0, min(65535, int(theta / (math.pi * 0.75) * 32768 + 32768)))

        # Flush DMX
        if hasattr(mw, 'dmx') and mw.dmx:
            mw.dmx.update_from_projectors(mw.projectors)

        # Refresh 3D
        self.refresh(mw.projectors)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _norm_pos(self, projectors, i):
        from plan_de_feu import _DEFAULT_POSITIONS
        p  = projectors[i]
        cx = getattr(p, 'canvas_x', None)
        cy = getattr(p, 'canvas_y', None)
        if cx is not None and cy is not None:
            return cx, cy
        group = getattr(p, 'group', '')
        gi    = [j for j,q in enumerate(projectors) if getattr(q,'group','') == group]
        li    = gi.index(i) if i in gi else 0
        fn    = _DEFAULT_POSITIONS.get(group, lambda li,n: (0.5,0.5))
        return fn(li, len(gi))

    def _gobo_slot_idx(self, p):
        slots    = getattr(p, 'gobo_wheel_slots', [])
        gobo_val = getattr(p, 'gobo', 0)
        if not slots or gobo_val == 0: return 0
        return slots.index(min(slots, key=lambda s: abs(s.get('dmx',0)-gobo_val))) + 1

    def _to_data(self, projectors):
        out = []
        for i, p in enumerate(projectors):
            col = getattr(p, 'color', None)
            r = col.red() if col else 0; g = col.green() if col else 0; b = col.blue() if col else 0
            cx, cy = self._norm_pos(projectors, i)
            fh = getattr(p, 'fixture_height', None)
            # Positions 3D indépendantes — fallback sur coordonnées du plan 2D
            p3x = getattr(p, 'pos_3d_x', None)
            p3z = getattr(p, 'pos_3d_z', None)
            x_world = p3x if p3x is not None else (cx - 0.5) * 18.0
            z_world = p3z if p3z is not None else (cy - 0.5) * 10.0
            out.append({
                'level':          int(getattr(p,'level',0)),
                'r': r, 'g': g, 'b': b,
                'x':              x_world,
                'z':              z_world,
                'pan':            getattr(p,'pan', 32768),
                'tilt':           getattr(p,'tilt',32768),
                'fixture_type':   getattr(p,'fixture_type','PAR LED'),
                'fixture_height': fh if fh is not None else TRUSS_Y,
                'body_rotation':  getattr(p,'body_rotation',0.0),
                'gobo_slot_idx':  self._gobo_slot_idx(p),
                'gobo_rotation':  getattr(p,'gobo_rotation',0),
                'name':           getattr(p,'name',''),
                'group':          getattr(p,'group',''),
            })
        return out

    # ── Public API ────────────────────────────────────────────────────────────

    def init_scene(self, projectors):
        self._canvas.set_projectors(self._to_data(projectors))

    def refresh(self, projectors):
        self._canvas.set_projectors(self._to_data(projectors))

    def closeEvent(self, event):
        event.ignore()
        self.hide()
