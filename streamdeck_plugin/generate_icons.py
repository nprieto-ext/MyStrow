"""
Génère les icônes PNG pour le plugin Stream Deck MyStrow.
Nécessite : pip install Pillow

Usage : python generate_icons.py
"""
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "com.mystrow.streamdeck.sdPlugin" / "images"
OUT.mkdir(exist_ok=True)

BG      = (20, 20, 20, 255)
YELLOW  = (226, 206, 22, 255)
WHITE   = (255, 255, 255, 255)
RED     = (220, 50, 50, 255)
BLUE    = (50, 120, 220, 255)
GREEN   = (50, 200, 80, 255)
PURPLE  = (150, 50, 220, 255)
ORANGE  = (220, 140, 30, 255)
GREY    = (120, 120, 120, 255)

ICONS = [
    # (filename_without_ext, label_line1, label_line2, accent_color, shape)
    ("plugin",  "MY",      "STROW",   YELLOW,  "logo"),
    ("play",    ">",       "PLAY",    GREEN,   "circle"),
    ("next",    ">>",      "NEXT",    YELLOW,  "circle"),
    ("prev",    "<<",      "PREV",    YELLOW,  "circle"),
    ("blackout","X",       "BLKOUT",  RED,     "circle"),
    ("effect",  "*",       "EFFECT",  PURPLE,  "circle"),
    ("level",   "^",       "LEVEL",   BLUE,    "circle"),
    ("mute",    "M",       "MUTE",    ORANGE,  "circle"),
    ("scene",   "S",       "SCENE",   GREEN,   "circle"),
]

SIZES = [72, 144]   # @1x et @2x

def _try_font(size):
    """Essaie de charger une police système, fallback sur default."""
    candidates = [
        "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
        "Helvetica.ttc", "calibrib.ttf",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()

def make_icon(name, line1, line2, color, shape, size):
    img  = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(img)

    pad = size // 8

    if shape == "circle":
        draw.ellipse([pad, pad, size - pad, size - pad], outline=color, width=max(2, size // 20))
    elif shape == "logo":
        r = size // 6
        draw.rounded_rectangle([pad, pad, size - pad, size - pad],
                                radius=r, outline=color, width=max(2, size // 20))

    # Ligne 1 (emoji ou grand symbole)
    f1 = _try_font(size // 3)
    f2 = _try_font(size // 6)

    # Centre vertical : ligne1 en haut du centre, ligne2 en bas
    y1 = size * 0.20
    y2 = size * 0.62

    try:
        draw.text((size / 2, y1), line1, font=f1, fill=color, anchor="mm")
        draw.text((size / 2, y2), line2, font=f2, fill=WHITE, anchor="mm")
    except TypeError:
        # Versions PIL sans anchor
        w1, h1 = draw.textsize(line1, font=f1)
        w2, h2 = draw.textsize(line2, font=f2)
        draw.text(((size - w1) / 2, y1 - h1 / 2), line1, font=f1, fill=color)
        draw.text(((size - w2) / 2, y2 - h2 / 2), line2, font=f2, fill=WHITE)

    return img

for (fname, l1, l2, col, sh) in ICONS:
    for sz in SIZES:
        suffix = "" if sz == 72 else "@2x"
        out_path = OUT / f"{fname}{suffix}.png"
        img = make_icon(fname, l1, l2, col, sh, sz)
        img.save(out_path, "PNG")
        print(f"  OK {out_path.name}")

print(f"\nDone: {len(ICONS) * len(SIZES)} icones generees dans : {OUT}")
