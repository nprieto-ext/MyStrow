"""Génère les icônes StreamDeck pour MyStrow."""
from PIL import Image, ImageDraw, ImageFont
import math, os

OUT = r'C:\Users\nikop\Desktop\MyStrow\streamdeck_plugin\com.mystrow.streamdeck.sdPlugin\images'

F_BEBAS = r'C:\Windows\Fonts\BebasNeue-Regular.otf'
F_INTER = r'C:\Windows\Fonts\Inter-Bold-slnt=0.ttf'

BG     = (13, 13, 18)
CORNER = 14

def hex2rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def make_base(size=72, bg=BG):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size-1, size-1], radius=CORNER, fill=bg)
    return img, d

def draw_label(d, text, color, size=72, yoff=0, font_size=18):
    font = ImageFont.truetype(F_BEBAS, font_size)
    col  = hex2rgb(color) + (255,)
    bb   = d.textbbox((0, 0), text, font=font)
    w    = bb[2] - bb[0]
    x    = (size - w) // 2
    y    = size - 21 + yoff
    d.text((x, y), text, font=font, fill=col)


# ── PLAY ─────────────────────────────────────────────────────────────────
def make_play(size=72):
    img, d = make_base(size, (8, 22, 14))
    col = hex2rgb('#00E87A') + (255,)
    cx, cy = size // 2 + 2, size // 2 - 5
    r = size * 0.27
    pts = [
        (cx - r * 0.65, cy - r * 0.85),
        (cx - r * 0.65, cy + r * 0.85),
        (cx + r * 0.90, cy),
    ]
    d.polygon(pts, fill=col)
    # Halo
    for i in range(3, 0, -1):
        d.polygon(pts, outline=hex2rgb('#00E87A') + (20 * i,), width=i)
    draw_label(d, 'PLAY', '#00E87A', size)
    return img


# ── NEXT ─────────────────────────────────────────────────────────────────
def make_next(size=72):
    img, d = make_base(size, (20, 17, 0))
    col = hex2rgb('#FFE000') + (230,)
    cx, cy = size // 2, size // 2 - 5
    h = size * 0.24
    for off in (-11, 4):
        pts = [
            (cx + off,              cy - h),
            (cx + off + h * 1.05,   cy),
            (cx + off,              cy + h),
            (cx + off + 5,          cy + h),
            (cx + off + h * 1.05 + 5, cy),
            (cx + off + 5,          cy - h),
        ]
        d.polygon(pts, fill=col)
    draw_label(d, 'NEXT', '#FFE000', size)
    return img


# ── PREV ─────────────────────────────────────────────────────────────────
def make_prev(size=72):
    img, d = make_base(size, (20, 17, 0))
    col = hex2rgb('#FFE000') + (230,)
    cx, cy = size // 2, size // 2 - 5
    h = size * 0.24
    for off in (11, -4):
        pts = [
            (cx + off,               cy - h),
            (cx + off - h * 1.05,    cy),
            (cx + off,               cy + h),
            (cx + off - 5,           cy + h),
            (cx + off - h * 1.05 - 5, cy),
            (cx + off - 5,           cy - h),
        ]
        d.polygon(pts, fill=col)
    draw_label(d, 'PREV', '#FFE000', size)
    return img


# ── BLACKOUT ─────────────────────────────────────────────────────────────
def make_blackout(size=72):
    img, d = make_base(size, (22, 5, 5))
    col = hex2rgb('#FF3B3B') + (255,)
    cx, cy = size // 2, size // 2 - 5
    r = size * 0.22
    # Cercle
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=3)
    # Barre diagonale
    ang = math.radians(45)
    dx, dy = r * math.cos(ang), r * math.sin(ang)
    d.line([(cx - dx, cy - dy), (cx + dx, cy + dy)], fill=col, width=4)
    # Halo rouge
    for i in range(3, 0, -1):
        d.ellipse([cx - r - i*2, cy - r - i*2, cx + r + i*2, cy + r + i*2],
                  outline=hex2rgb('#FF3B3B') + (25 * i,), width=1)
    draw_label(d, 'BLACKOUT', '#FF3B3B', size, font_size=15)
    return img


# ── EFFECT ───────────────────────────────────────────────────────────────
def make_effect(size=72):
    img, d = make_base(size, (14, 5, 22))
    col = hex2rgb('#CC44FF') + (210,)
    cx, cy = size // 2, size // 2 - 5
    R, r = size * 0.26, size * 0.11
    pts = []
    for i in range(12):
        angle  = math.radians(i * 30 - 90)
        radius = R if i % 2 == 0 else r
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    d.polygon(pts, fill=col)
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 255, 255, 200))
    draw_label(d, 'EFFECT', '#CC44FF', size)
    return img


# ── LEVEL ────────────────────────────────────────────────────────────────
def make_level(size=72):
    img, d = make_base(size, (0, 12, 22))
    col = hex2rgb('#00B8FF')
    tops    = [18, 12, 24]
    bar_bot = size - 22
    x0      = (size - 42) // 2
    gaps    = [0, 16, 32]
    w       = 10
    for gap, top_off in zip(gaps, tops):
        x     = x0 + gap
        bar_h = bar_bot - (size // 2 - 8 + top_off)
        d.rounded_rectangle([x, size // 2 - 8, x + w, bar_bot],
                             radius=3, fill=(40, 60, 80))
        y_top = min(bar_bot - bar_h, bar_bot - 4)
        d.rounded_rectangle([x, y_top, x + w, bar_bot],
                             radius=3, fill=col + (220,))
    draw_label(d, 'LEVEL', '#00B8FF', size)
    return img


# ── MUTE ─────────────────────────────────────────────────────────────────
def make_mute(size=72):
    img, d = make_base(size, (22, 11, 0))
    col = hex2rgb('#FF8C00')
    cx, cy = size // 2 - 5, size // 2 - 5
    sw = size * 0.11
    # Corps haut-parleur
    d.rectangle([cx - sw * 1.4, cy - sw * 1.1, cx, cy + sw * 1.1],
                fill=col + (220,))
    pts = [
        (cx,          cy - sw * 1.1),
        (cx,          cy + sw * 1.1),
        (cx + sw * 2.1, cy + sw * 2.1),
        (cx + sw * 2.1, cy - sw * 2.1),
    ]
    d.polygon(pts, fill=col + (220,))
    # Croix
    xc, yc = cx + size * 0.26, cy
    r2 = size * 0.11
    red = (255, 55, 55, 255)
    d.line([(xc - r2, yc - r2), (xc + r2, yc + r2)], fill=red, width=3)
    d.line([(xc + r2, yc - r2), (xc - r2, yc + r2)], fill=red, width=3)
    draw_label(d, 'MUTE', '#FF8C00', size)
    return img


# ── SCENE ────────────────────────────────────────────────────────────────
def make_scene(size=72):
    img, d = make_base(size, (0, 16, 16))
    col = hex2rgb('#00D4C8')
    cx, cy = size // 2, size // 2 - 8
    r = size * 0.13
    # Ampoule spot
    d.ellipse([cx - r, cy - r - 2, cx + r, cy + r - 2], fill=col + (240,))
    # Faisceau
    pts = [
        (cx - r * 0.7, cy + r - 2),
        (cx + r * 0.7, cy + r - 2),
        (cx + r * 2.4, cy + r + size * 0.22),
        (cx - r * 2.4, cy + r + size * 0.22),
    ]
    d.polygon(pts, fill=col + (55,))
    # Sol de scène
    y_floor = cy + r + size * 0.24
    d.line([(size * 0.14, y_floor), (size * 0.86, y_floor)],
           fill=col + (180,), width=3)
    draw_label(d, 'SCENE', '#00D4C8', size)
    return img


# ── SEQ ──────────────────────────────────────────────────────────────────
def make_seq(size=72):
    img, d = make_base(size, (8, 9, 22))
    col = hex2rgb('#7B8CFF')
    x1, x2 = size * 0.18, size * 0.84
    ys      = [15, 24, 33, 42]
    heights = [0.65, 1.0, 0.45, 0.75]
    for i, (y, h) in enumerate(zip(ys, heights)):
        alpha  = 255 if i == 1 else 130
        bar_w  = (x2 - x1) * h
        d.rounded_rectangle([x1, y, x1 + bar_w, y + 6],
                             radius=3, fill=col + (alpha,))
        if i == 1:
            # Triangle indicateur
            d.polygon([(x1 - 9, y), (x1 - 9, y + 6), (x1 - 2, y + 3)],
                      fill=(255, 245, 80, 255))
    draw_label(d, 'SEQ', '#7B8CFF', size)
    return img


# ── PLUGIN ───────────────────────────────────────────────────────────────
def make_plugin(size=72):
    img, d = make_base(size, (10, 10, 16))
    f_big = ImageFont.truetype(F_BEBAS, int(size * 0.30))
    f_sub = ImageFont.truetype(F_INTER, int(size * 0.11))
    # MY + STROW — centré
    bb_my  = d.textbbox((0, 0), 'MY',    font=f_big)
    bb_str = d.textbbox((0, 0), 'STROW', font=f_big)
    w_my   = bb_my[2]  - bb_my[0]
    w_str  = bb_str[2] - bb_str[0]
    total  = w_my + w_str
    x      = (size - total) // 2
    y      = size // 2 - int(size * 0.24)
    d.text((x,        y), 'MY',    font=f_big, fill=(255, 255, 255, 255))
    d.text((x + w_my, y), 'STROW', font=f_big, fill=(255, 224, 0,   255))
    # Ligne décorative
    ly = y + int(size * 0.30) + 2
    d.line([(size * 0.18, ly), (size * 0.82, ly)], fill=(255, 224, 0, 90), width=1)
    # Sous-titre
    sub  = 'LIGHTING CTRL'
    bb_s = d.textbbox((0, 0), sub, font=f_sub)
    xs   = (size - (bb_s[2] - bb_s[0])) // 2
    d.text((xs, ly + 4), sub, font=f_sub, fill=(130, 130, 165, 190))
    return img


GENERATORS = {
    'play':     make_play,
    'next':     make_next,
    'prev':     make_prev,
    'blackout': make_blackout,
    'effect':   make_effect,
    'level':    make_level,
    'mute':     make_mute,
    'scene':    make_scene,
    'seq':      make_seq,
    'plugin':   make_plugin,
}

for name, fn in GENERATORS.items():
    img_72  = fn(72)
    img_144 = fn(144)
    img_72.save(os.path.join(OUT, f'{name}.png'))
    img_144.save(os.path.join(OUT, f'{name}@2x.png'))
    print(f'  {name}.png + @2x  OK')

print('Tous les icones generes !')
