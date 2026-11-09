"""Demo-Fotobibliothek für Screenshots und zum Ausprobieren ohne NAS (braucht Pillow – nur beim Entwickeln).

    FG_DATA_DIR=/tmp/fg-demo/data FG_VOLUME_ROOT=/tmp/fg-demo python tools/demo.py
    FG_DATA_DIR=/tmp/fg-demo/data FG_VOLUME_ROOT=/tmp/fg-demo FG_SCHEDULER=0 python -m app.main

Gibt am Ende ein Session-Token für den DSM-Benutzer „anna“ aus (Cookie fg_session).
"""
import os
import random
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app import scanner  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import connect, init_db, set_setting  # noqa: E402
from app.security import create_session  # noqa: E402
from photofiles import make_jpeg  # noqa: E402

PLACES = [  # Name, Breite, Länge, Anzahl, erster Tag, persönlich?  (aufeinanderfolgende Tage, ~3 Fotos pro Tag)
    ("Braunschweig", 52.2647, 10.5231, 3, "2023-02-05", True),
    ("Palma de Mallorca", 39.5696, 2.6502, 9, "2024-07-03", False), ("Cala Ratjada", 39.7123, 3.4623, 6, "2024-07-06", False),
    ("Rom", 41.8902, 12.4922, 9, "2023-05-12", True), ("Florenz", 43.7731, 11.2560, 5, "2023-05-15", True),
    ("Venedig", 45.4380, 12.3358, 4, "2023-05-17", True),
    ("Hamburg", 53.5450, 9.9660, 7, "2025-03-21", False), ("München", 48.1374, 11.5755, 4, "2022-10-01", True),
    ("Reykjavík", 64.1466, -21.9426, 8, "2021-08-02", True), ("Jökulsárlón", 64.0784, -16.2306, 5, "2021-08-05", True),
    ("New York", 40.7580, -73.9855, 9, "2019-09-10", False), ("San Francisco", 37.8199, -122.4783, 6, "2019-09-14", False),
    ("Kapstadt", -33.9628, 18.4098, 5, "2018-02-10", True), ("Tokio", 35.6595, 139.7005, 7, "2025-04-01", True),
    ("Kyoto", 34.9671, 135.7727, 4, "2025-04-04", True), ("Sydney", -33.8568, 151.2153, 6, "2017-12-27", False),
    ("Bali", -8.4095, 115.1889, 5, "2022-06-11", False), ("Lissabon", 38.7071, -9.1355, 6, "2023-10-07", False),
    ("Wien", 48.2082, 16.3738, 3, "2020-08-20", True), ("Kopenhagen", 55.6761, 12.5683, 4, "2024-05-09", True),
]
HOME = ("Zuhause", 52.4310, 10.5830)  # Fotos an vielen einzelnen Tagen → wird automatisch „Zuhause“
COLORS = [((255, 179, 71), (220, 80, 60)), ((120, 200, 255), (30, 90, 170)), ((140, 220, 160), (30, 120, 90)),
          ((250, 220, 120), (200, 120, 40)), ((200, 160, 255), (90, 50, 160)), ((255, 160, 190), (170, 50, 90))]


def picture(text: str, sub: str, size, seed: int) -> bytes:
    rnd = random.Random(seed)
    top, bottom = rnd.choice(COLORS)
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    # „Landschaft“: Sonne und Hügel
    d.ellipse([w * .62, h * .14, w * .82, h * .14 + w * .2], fill=(255, 245, 210))
    for k in range(3):
        base = h * (0.62 + k * 0.1)
        pts = [(0, h)] + [(x, base - rnd.random() * h * 0.12) for x in range(0, w + 40, max(40, w // 8))] + [(w, h)]
        shade = 40 + k * 25
        d.polygon(pts, fill=(shade, shade + 30, shade + 20))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(14, w // 14))
        small = ImageFont.truetype("DejaVuSans.ttf", max(10, w // 24))
    except OSError:
        font = small = ImageFont.load_default()
    d.text((w * 0.06, h * 0.06), text, fill=(255, 255, 255), font=font)
    d.text((w * 0.06, h * 0.06 + max(18, w // 11)), sub, fill=(255, 255, 255), font=small)
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def main():
    vol = os.path.join(settings.volume_root, "volume1")
    init_db()
    n = 0
    import datetime as _dt
    home_days = [(_dt.date(2023, 1, 3) + _dt.timedelta(days=11 * k)).isoformat() for k in range(60)]
    series = [(name, lat, lon, count, first, personal) for name, lat, lon, count, first, personal in PLACES]
    series += [(HOME[0], HOME[1], HOME[2], 1, d, True) for d in home_days]
    for name, lat, lon, count, first, personal in series:
        year = first[:4]
        base = os.path.join(vol, "homes", "anna", "Photos", year, name) if personal else os.path.join(vol, "photo", "Reisen", year, name)
        os.makedirs(base, exist_ok=True)
        for i in range(count):
            n += 1
            rnd = random.Random(n)
            spread = 0.004 if name == HOME[0] else 0.02
            la, lo = lat + rnd.uniform(-spread, spread), lon + rnd.uniform(-spread, spread)
            day = _dt.date.fromisoformat(first) + _dt.timedelta(days=i // 3)
            taken = f"{day:%Y:%m:%d} {9 + (i % 3) * 3:02d}:{rnd.randint(0, 59):02d}:00"
            fname = f"IMG_{4000 + n}.jpg"
            path = os.path.join(base, fname)
            with open(path, "wb") as f:
                f.write(make_jpeg(lat=la, lon=lo, taken=taken, model=rnd.choice(["iPhone 15 Pro", "Pixel 8", "EOS R6"]),
                                  make=rnd.choice(["Apple", "Google", "Canon"])))
            eadir = os.path.join(base, "@eaDir", fname)
            os.makedirs(eadir, exist_ok=True)
            label = f"{taken[8:10]}.{taken[5:7]}.{taken[:4]}"
            for size, dims in (("SM", (240, 180)), ("M", (320, 240)), ("XL", (1280, 960))):
                with open(os.path.join(eadir, f"SYNOFOTO_THUMB_{size}.jpg"), "wb") as f:
                    f.write(picture(name, label, dims, n))
    # ein paar Videos (braucht ffmpeg; ohne ffmpeg geht es auch ohne Videos)
    import shutil
    import subprocess
    if shutil.which("ffmpeg"):
        for k, (name, lat, lon, year, personal) in enumerate([("Reykjavík", 64.1466, -21.9426, 2021, True),
                                                            ("Palma de Mallorca", 39.5696, 2.6502, 2024, False),
                                                            ("Tokio", 35.6595, 139.7005, 2025, True)]):
            month_day = {"Reykjavík": "08-03", "Palma de Mallorca": "07-04", "Tokio": "04-02"}[name]
            base = os.path.join(vol, "homes", "anna", "Photos", str(year), name) if personal else os.path.join(vol, "photo", "Reisen", str(year), name)
            fname = f"VID_{k + 1:04d}.mp4"
            path = os.path.join(base, fname)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=6",
                            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                            "-metadata", f"location={lat:+08.4f}{lon:+09.4f}/", "-metadata", f"creation_time={year}-{month_day}T12:00:00Z",
                            "-movflags", "+faststart", path], check=True)
            eadir = os.path.join(base, "@eaDir", fname)
            os.makedirs(eadir, exist_ok=True)
            for size, dims in (("SM", (240, 135)), ("M", (320, 180)), ("XL", (1280, 720))):
                with open(os.path.join(eadir, f"SYNOFOTO_THUMB_{size}.jpg"), "wb") as f:
                    f.write(picture(name, "Video", dims, 900 + k))
    conn = connect()
    try:
        set_setting(conn, "share_access", "all")
    finally:
        conn.close()
    print(scanner.run("manuell"))
    conn = connect()
    try:
        conn.execute("INSERT OR IGNORE INTO users(username, display_name, is_dsm, created_at) VALUES ('anna', 'Anna', 1, '2026-01-01T00:00:00+00:00')")
        uid = conn.execute("SELECT id FROM users WHERE username = 'anna'").fetchone()[0]
        token = create_session(conn, uid, "anna")
        admin_token = create_session(conn, 1, None)
    finally:
        conn.close()
    print("ANNA_TOKEN=" + token)
    print("ADMIN_TOKEN=" + admin_token)


if __name__ == "__main__":
    main()
