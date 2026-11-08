"""Exif lesen: JPEG, HEIC, PNG, TIFF, kaputte Dateien."""
import os

import pytest

from app import exif

from .photofiles import TINY_JPEG, make_heic, make_jpeg, make_png, make_tiff, write

MALLORCA = (39.5696, 2.6502)
RIO = (-22.9519, -43.2105)


@pytest.mark.parametrize("maker,ext,kind", [(make_jpeg, ".jpg", "jpeg"), (make_heic, ".heic", "heif"),
                                            (make_png, ".png", "png"), (make_tiff, ".dng", "tiff")])
def test_gps_and_time_from_all_containers(tmp_path, maker, ext, kind):
    p = write(str(tmp_path / ("bild" + ext)), maker(lat=MALLORCA[0], lon=MALLORCA[1], alt=12.5))
    info = exif.read_photo(p)
    assert info["kind"] == kind
    assert info["lat"] == pytest.approx(MALLORCA[0], abs=1e-4)
    assert info["lon"] == pytest.approx(MALLORCA[1], abs=1e-4)
    assert info["alt"] == pytest.approx(12.5, abs=0.1)
    assert info["taken_at"] == "2024-07-14T18:22:05+02:00"
    assert info["make"] == "Apple" and info["model"] == "iPhone 15"
    assert info["width"] == 4032 and info["height"] == 3024


def test_southern_and_western_hemisphere(tmp_path):
    p = write(str(tmp_path / "rio.jpg"), make_jpeg(lat=RIO[0], lon=RIO[1], alt=-3))
    info = exif.read_photo(p)
    assert info["lat"] == pytest.approx(RIO[0], abs=1e-4) and info["lon"] == pytest.approx(RIO[1], abs=1e-4)
    assert info["alt"] == pytest.approx(-3, abs=0.1)


def test_without_gps_and_without_offset(tmp_path):
    p = write(str(tmp_path / "x.jpg"), make_jpeg(lat=None, offset=None))
    info = exif.read_photo(p)
    assert "lat" not in info and info["taken_at"] == "2024-07-14T18:22:05"


def test_zero_zero_is_no_fix(tmp_path):
    p = write(str(tmp_path / "x.jpg"), make_jpeg(lat=0.0, lon=0.0))
    assert "lat" not in exif.read_photo(p)


def test_invalid_date_ignored(tmp_path):
    p = write(str(tmp_path / "x.jpg"), make_jpeg(lat=1, lon=1, taken="0000:00:00 00:00:00"))
    info = exif.read_photo(p)
    assert "taken_at" not in info and info["lat"] == pytest.approx(1)


def test_embedded_thumbnail(tmp_path):
    p = write(str(tmp_path / "x.jpg"), make_jpeg(lat=1, lon=1, thumb=TINY_JPEG))
    assert exif.embedded_thumbnail(p) == TINY_JPEG
    q = write(str(tmp_path / "y.jpg"), make_jpeg(lat=1, lon=1))
    assert exif.embedded_thumbnail(q) is None


@pytest.mark.parametrize("data", [
    b"", b"\xff\xd8", b"\xff\xd8\xff\xe1\x00\x02", b"\xff\xd8\xff\xe1\xff\xffExif\x00\x00II*\x00\xff\xff\xff\xff",
    b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100, b"II*\x00\x08\x00\x00\x00\xff\xff" + b"\x00" * 20,
    b"MM\x00*\x00\x00\x00\x08\x00\x01\x88\x25\x00\x04\x00\x00\x00\x01\x7f\xff\xff\xff",
    os.urandom(3000), b"\x89PNG\r\n\x1a\n" + os.urandom(200),
])
def test_broken_files_do_not_crash(tmp_path, data):
    p = write(str(tmp_path / "kaputt.jpg"), data)
    info = exif.read_photo(p)
    assert "lat" not in info


def test_truncated_real_structures(tmp_path):
    for maker in (make_jpeg, make_heic, make_png):
        full = maker(lat=MALLORCA[0], lon=MALLORCA[1])
        for cut in range(0, len(full), 7):
            p = write(str(tmp_path / "t.bin"), full[:cut])
            exif.read_photo(p)  # darf nie werfen
