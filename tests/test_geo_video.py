"""Ortsnamen (offline) und Videos (MP4/MOV)."""
import datetime as dt
import sqlite3

import pytest

from app import exif, geo

from .photofiles import make_video, write


@pytest.mark.parametrize("lat,lon,expected", [
    (39.5696, 2.6502, "Palma, Spanien"),
    (48.137, 11.575, "München, Deutschland"),
    (41.8902, 12.4922, "Rom, Italien"),
    (40.758, -73.9855, "New York, USA"),          # Großstadt statt Stadtteil
    (-33.8568, 151.2153, "Sydney, Australien"),
    (52.43, 10.58, "Isenbüttel, Deutschland"),    # Dorf behält seinen Namen gegen die Kreisstadt
    (64.0784, -16.2306, "Island"),                # abgelegen: nur das Land
])
def test_place_names(lat, lon, expected):
    hit = geo.nearest(lat, lon)
    assert geo.label(hit[0], hit[1]) == expected


def test_open_sea_and_dateline():
    assert geo.nearest(0, -30) is None
    assert geo.nearest(-18.14, 178.44)[1] == "FJ"       # Suva, Fidschi
    assert geo.nearest(-16.5, 179.95)[1] == "FJ"        # Suche über die Datumsgrenze hinweg
    geo.unload()


def test_country_names():
    assert geo.country_name("DE") == "Deutschland" and geo.country_name("US") == "USA"
    assert geo.country_name(None) is None and geo.label(None, None) is None


def test_apple_mov(tmp_path):
    p = write(str(tmp_path / "IMG_0001.MOV"), make_video(lat=39.5696, lon=2.6502))
    info = exif.read_media(p)
    assert info["media"] == "video" and info["kind"] == "video"
    assert info["lat"] == pytest.approx(39.5696) and info["lon"] == pytest.approx(2.6502) and info["alt"] == 12.0
    assert info["taken_at"] == "2024-07-14T18:22:05+02:00" and info["duration"] == 12.5
    assert info["model"] == "iPhone 15 Pro"


def test_android_mp4_with_moov_at_end(tmp_path):
    created = dt.datetime(2023, 5, 1, 10, 0, 0, tzinfo=dt.timezone.utc)
    p = write(str(tmp_path / "VID.mp4"), make_video(lat=-22.95, lon=-43.21, apple=False, created_utc=created,
                                                     faststart=False))
    info = exif.read_media(p)
    assert info["lat"] == pytest.approx(-22.95) and info["lon"] == pytest.approx(-43.21)
    assert info["taken_at"] == "2023-05-01T12:00:00+02:00"   # UTC aus mvhd → Ortszeit


def test_video_without_location_and_broken(tmp_path):
    p = write(str(tmp_path / "a.mp4"), make_video(apple=False))
    assert "lat" not in exif.read_media(p)
    full = make_video(lat=1, lon=1)
    for cut in range(0, len(full), 11):
        q = write(str(tmp_path / "t.mov"), full[:cut])
        exif.read_media(q)  # darf nie werfen
    assert exif.parse_iso6709("+00.0000+000.0000/") is None
    assert exif.parse_iso6709("Unsinn") is None


def test_migration_from_0_1(tmp_path, monkeypatch):
    """Eine Datenbank von 0.1.0 wird ohne Datenverlust auf das neue Schema gebracht."""
    from app import db
    path = tmp_path / "alt.db"
    old = sqlite3.connect(str(path))
    old.executescript(db.SCHEMA.split("-- Ein Eintrag pro Bilddatei")[0])
    old.execute("""CREATE TABLE photos (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE, scope TEXT NOT NULL,
        owner TEXT, folder TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL, mtime INTEGER NOT NULL, kind TEXT,
        taken_at TEXT, year INTEGER, lat REAL, lon REAL, alt REAL, make TEXT, model TEXT, width INTEGER, height INTEGER,
        orientation INTEGER, seen_scan INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL)""")
    old.execute("INSERT INTO photos(path, scope, folder, name, size, mtime, lat, lon, added_at) "
                "VALUES ('/v/photo/a.jpg', 'shared', '/v/photo', 'a.jpg', 1, 1, 39.57, 2.65, 'x')")
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.row_factory = sqlite3.Row
    db.migrate(old)
    row = old.execute("SELECT * FROM photos").fetchone()
    assert row["name"] == "a.jpg" and row["media"] == "photo" and row["geocoded"] == 0 and row["place"] is None
    assert old.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    db.migrate(old)  # zweimal schadet nicht
    old.close()


def test_3gpp_loci_box(tmp_path):
    """ffmpeg und manche Kameras schreiben den Ort als „loci“ (16.16-Festkomma, Länge vor Breite)."""
    import struct
    from .photofiles import _box, _full
    loci = _full(b"loci", 0, struct.pack(">H", 0x15C7) + b"\x00" + b"\x00"
                 + struct.pack(">iii", int(-16.2306 * 65536), int(64.0784 * 65536), int(25 * 65536)) + b"earth\x00\x00")
    mvhd = _full(b"mvhd", 0, struct.pack(">IIII", 0, 0, 1000, 4000) + b"\x00" * 80)
    data = _box(b"ftyp", b"isom\x00\x00\x00\x00isom") + _box(b"moov", mvhd + _box(b"udta", loci)) + _box(b"mdat", b"\x00" * 8)
    info = exif.read_media(write(str(tmp_path / "f.mp4"), data))
    assert info["lat"] == pytest.approx(64.0784, abs=1e-3) and info["lon"] == pytest.approx(-16.2306, abs=1e-3)
    assert info["alt"] == pytest.approx(25) and info["duration"] == 4.0
