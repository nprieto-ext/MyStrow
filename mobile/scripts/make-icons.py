"""Icônes et écrans de lancement de l'app MyStrow (Android + iOS) depuis logo.png.

    python mobile/scripts/make-icons.py

Le symbole jaune est extrait du logo (masque antialiasé) puis agrandi : le logo
source ne fait que 512 px et l'icône iOS en demande 1024. Chaque image existante
des projets natifs est régénérée À SA TAILLE, sans toucher aux noms ni aux
Contents.json : relancer après un `npx cap add` suffit.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

MOBILE = Path(__file__).resolve().parent.parent
REPO = MOBILE.parent
APP_BG = (8, 8, 7)                     # fond de l'app (#080807)
FONT = Path(r"C:\Windows\Fonts\BebasNeue-Regular.otf")

logo = np.asarray(Image.open(REPO / "logo.png").convert("RGBA")).astype(np.float32)
r, g, b, a = (logo[..., i] for i in range(4))

# Couleurs du logo : fond du carré et jaune du symbole.
inside = (a > 250) & (g - b < 20)
LOGO_BG = tuple(int(v) for v in np.median(logo[inside][:, :3], axis=0))
yellow_px = (a > 250) & (g - b > 200)
YELLOW = tuple(int(v) for v in np.median(logo[yellow_px][:, :3], axis=0))

# Masque du symbole : l'écart vert-bleu passe de ~0 (fond) à ~230 (jaune).
bg_gb = LOGO_BG[1] - LOGO_BG[2]
y_gb = YELLOW[1] - YELLOW[2]
mask = np.clip(((g - b) - bg_gb) / (y_gb - bg_gb), 0, 1) * (a / 255.0)
mask_img = Image.fromarray((mask * 255).astype(np.uint8), "L")
mask_img = mask_img.crop(mask_img.getbbox())


def symbol(size_px):
    """Symbole jaune (RGBA) inscrit dans un carré de size_px."""
    w, h = mask_img.size
    scale = size_px / max(w, h)
    m = mask_img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    out = Image.new("RGBA", m.size, YELLOW + (0,))
    out.putalpha(m)
    return out


def paste_center(canvas, img, dy=0):
    x = (canvas.width - img.width) // 2
    y = (canvas.height - img.height) // 2 + dy
    canvas.alpha_composite(img, (x, y))


def icon_square(size, bg=LOGO_BG, ratio=0.62):
    """Icône pleine (iOS masque lui-même les coins ; aucune transparence admise)."""
    im = Image.new("RGBA", (size, size), bg + (255,))
    paste_center(im, symbol(round(size * ratio)))
    return im


def icon_legacy(size, round_shape=False):
    """Icône Android < 8 : carré arrondi ou rond, avec marge transparente."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    m = round(size * 0.04)
    box = [m, m, size - 1 - m, size - 1 - m]
    if round_shape:
        d.ellipse(box, fill=LOGO_BG + (255,))
    else:
        d.rounded_rectangle(box, radius=round(size * 0.18), fill=LOGO_BG + (255,))
    paste_center(im, symbol(round(size * 0.56)))
    return im


def icon_foreground(size):
    """Calque avant de l'icône adaptative : symbole dans la zone sûre (66/108)."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    paste_center(im, symbol(round(size * 0.46)))
    return im


def splash(w, h):
    im = Image.new("RGBA", (w, h), APP_BG + (255,))
    base = min(w, h)
    sym = symbol(round(base * 0.26))
    font_px = round(base * 0.075)
    gap = round(base * 0.05)
    if FONT.exists():
        font = ImageFont.truetype(str(FONT), font_px)
        d = ImageDraw.Draw(im)
        wm_w = d.textlength("MYSTROW", font=font)
        total_h = sym.height + gap + font_px
        top = (h - total_h) // 2
        im.alpha_composite(sym, ((w - sym.width) // 2, top))
        x = (w - wm_w) / 2
        y = top + sym.height + gap
        d.text((x, y), "MY", font=font, fill=(244, 241, 232, 255))
        d.text((x + d.textlength("MY", font=font), y), "STROW", font=font, fill=YELLOW + (255,))
    else:
        paste_center(im, sym)
    return im


def save(img, path, opaque=False):
    if opaque:
        img = img.convert("RGB")
    img.save(path, optimize=True)
    print("  ", path.relative_to(MOBILE), img.size)


print("fond logo", LOGO_BG, "jaune", YELLOW)

res = MOBILE / "android" / "app" / "src" / "main" / "res"
for p in sorted(res.glob("mipmap-*/ic_launcher.png")):
    save(icon_legacy(Image.open(p).width), p)
for p in sorted(res.glob("mipmap-*/ic_launcher_round.png")):
    save(icon_legacy(Image.open(p).width, round_shape=True), p)
for p in sorted(res.glob("mipmap-*/ic_launcher_foreground.png")):
    save(icon_foreground(Image.open(p).width), p)
for p in sorted(res.glob("drawable*/splash.png")):
    w, h = Image.open(p).size
    save(splash(w, h), p, opaque=True)
bg_xml = res / "values" / "ic_launcher_background.xml"
bg_xml.write_text(
    '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
    '    <color name="ic_launcher_background">#%02X%02X%02X</color>\n</resources>\n' % LOGO_BG,
    encoding="utf-8")
print("  ", bg_xml.relative_to(MOBILE))

assets = MOBILE / "ios" / "App" / "App" / "Assets.xcassets"
for p in sorted((assets / "AppIcon.appiconset").glob("*.png")):
    save(icon_square(Image.open(p).width), p, opaque=True)
for p in sorted((assets / "Splash.imageset").glob("*.png")):
    w, h = Image.open(p).size
    save(splash(w, h), p, opaque=True)
