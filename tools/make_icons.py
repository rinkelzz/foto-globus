"""Paket- und Menü-Icons zeichnen (Globus mit Pinnadel). Nur beim Entwickeln nötig (Pillow).

    python tools/make_icons.py
"""
import math
import os

from PIL import Image, ImageDraw

ROOT = os.path.join(os.path.dirname(__file__), "..", "synology")


def icon(size: int) -> Image.Image:
    s = 4  # Überabtastung für glatte Kanten
    n = size * s
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Hintergrund: abgerundetes Quadrat, Verlauf Petrol → Dunkelblau
    bg = Image.new("RGBA", (n, n))
    bd = ImageDraw.Draw(bg)
    for y in range(n):
        t = y / n
        bd.line([(0, y), (n, y)], fill=(int(15 + 10 * t), int(118 - 60 * t), int(110 + 20 * t), 255))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.22), fill=255)
    img.paste(bg, (0, 0), mask)
    # Globus
    cx, cy, r = n * 0.47, n * 0.55, n * 0.33
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(201, 228, 245, 255), outline=(255, 255, 255, 255), width=max(2, n // 40))
    lw = max(1, n // 70)
    for k in (-0.6, 0, 0.6):  # Längengrade
        w = r * math.cos(math.asin(abs(k))) if k else r
        d.ellipse([cx - r * abs(math.cos(k * 1.2)) * 0.95, cy - r, cx + r * abs(math.cos(k * 1.2)) * 0.95, cy + r],
                  outline=(120, 170, 200, 255), width=lw)
        del w
    for k in (-0.5, 0, 0.5):  # Breitengrade
        yy = cy + k * r
        half = r * math.sqrt(1 - k * k)
        d.line([(cx - half, yy), (cx + half, yy)], fill=(120, 170, 200, 255), width=lw)
    # Pinnadel
    px, py, pr = n * 0.64, n * 0.36, n * 0.16
    d.polygon([(px - pr * 0.82, py + pr * 0.55), (px + pr * 0.82, py + pr * 0.55), (px, py + pr * 2.1)], fill=(225, 29, 72, 255))
    d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(225, 29, 72, 255), outline=(255, 255, 255, 255), width=max(2, n // 45))
    d.ellipse([px - pr * 0.38, py - pr * 0.38, px + pr * 0.38, py + pr * 0.38], fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    icon(64).save(os.path.join(ROOT, "PACKAGE_ICON.PNG"))
    icon(256).save(os.path.join(ROOT, "PACKAGE_ICON_256.PNG"))
    os.makedirs(os.path.join(ROOT, "ui", "images"), exist_ok=True)
    for sz in (16, 24, 32, 48, 64, 72, 256):
        icon(sz).save(os.path.join(ROOT, "ui", "images", f"icon_{sz}.png"))
    icon(180).save(os.path.join(ROOT, "..", "app", "static", "icon.png"))
    print("Icons geschrieben")
