"""Testbilder bauen – Exif-Blöcke in JPEG, HEIC, PNG und TIFF, ganz ohne Bildbibliothek."""
import os
import struct
from typing import Optional


def _rational(v: float, denom: int = 10000) -> bytes:
    return struct.pack("<II", int(round(v * denom)), denom)


def _dms(deg: float) -> bytes:
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = (deg - d - m / 60) * 3600
    return _rational(d, 1) + _rational(m, 1) + _rational(s)


def _ifd(entries, start: int, next_ifd: int = 0) -> bytes:
    """entries: [(tag, typ, count, bytes)] – Werte > 4 Byte landen hinter der IFD."""
    entries = sorted(entries)
    head = struct.pack("<H", len(entries))
    data_off = start + 2 + 12 * len(entries) + 4
    body, extra = b"", b""
    for tag, typ, count, val in entries:
        if len(val) <= 4:
            body += struct.pack("<HHI", tag, typ, count) + val.ljust(4, b"\x00")
        else:
            body += struct.pack("<HHII", tag, typ, count, data_off + len(extra))
            extra += val + (b"\x00" if len(val) % 2 else b"")
    return head + body + struct.pack("<I", next_ifd) + extra


def _ascii(s: str) -> bytes:
    return s.encode() + b"\x00"


def make_tiff(lat: Optional[float] = None, lon: Optional[float] = None, taken: Optional[str] = "2024:07:14 18:22:05",
              offset: Optional[str] = "+02:00", make: str = "Apple", model: str = "iPhone 15",
              alt: Optional[float] = None, thumb: Optional[bytes] = None) -> bytes:
    # Aufbau: Kopf(8) | IFD0 | Exif-IFD | GPS-IFD | IFD1 | Vorschaubild
    def build(exif_off, gps_off, ifd1_off):
        e0 = [(0x010F, 2, len(make) + 1, _ascii(make)), (0x0110, 2, len(model) + 1, _ascii(model)),
              (0x0112, 3, 1, struct.pack("<H", 1)), (0x8769, 4, 1, struct.pack("<I", exif_off))]
        if lat is not None:
            e0.append((0x8825, 4, 1, struct.pack("<I", gps_off)))
        ifd0 = _ifd(e0, 8, ifd1_off if thumb else 0)
        ex = []
        if taken:
            ex.append((0x9003, 2, 20, _ascii(taken)))
        if offset:
            ex.append((0x9011, 2, 7, _ascii(offset)))
        ex += [(0xA002, 4, 1, struct.pack("<I", 4032)), (0xA003, 4, 1, struct.pack("<I", 3024))]
        exif_ifd = _ifd(ex, exif_off)
        gps = b""
        if lat is not None:
            g = [(1, 2, 2, _ascii("N" if lat >= 0 else "S")), (2, 5, 3, _dms(lat)),
                 (3, 2, 2, _ascii("E" if lon >= 0 else "W")), (4, 5, 3, _dms(lon))]
            if alt is not None:
                g += [(5, 1, 1, b"\x00" if alt >= 0 else b"\x01"), (6, 5, 1, _rational(abs(alt), 10))]
            gps = _ifd(g, gps_off)
        return ifd0, exif_ifd, gps

    ifd0, exif_ifd, gps = build(0, 0, 0)
    exif_off = 8 + len(ifd0)
    gps_off = exif_off + len(exif_ifd)
    ifd1_off = gps_off + len(gps)
    ifd0, exif_ifd, gps = build(exif_off, gps_off, ifd1_off)
    out = b"II*\x00" + struct.pack("<I", 8) + ifd0 + exif_ifd + gps
    if thumb:
        thumb_off = ifd1_off + 2 + 12 * 2 + 4
        ifd1 = _ifd([(0x0201, 4, 1, struct.pack("<I", thumb_off)), (0x0202, 4, 1, struct.pack("<I", len(thumb)))], ifd1_off)
        out += ifd1 + thumb
    return out


TINY_JPEG = b"\xff\xd8\xff\xdb\x00\x04\x00\x00\xff\xd9"  # gültiger Anfang/Ende, reicht für Tests


def make_jpeg(**kw) -> bytes:
    tiff = make_tiff(**kw)
    app1 = b"Exif\x00\x00" + tiff
    # ein APP0 (JFIF) davor, wie bei echten Kameras
    app0 = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    return (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0
            + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9")


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def _full(typ: bytes, version: int, payload: bytes) -> bytes:
    return _box(typ, bytes([version, 0, 0, 0]) + payload)


def make_heic(**kw) -> bytes:
    tiff = make_tiff(**kw)
    exif_item = struct.pack(">I", 6) + b"Exif\x00\x00" + tiff
    ftyp = _box(b"ftyp", b"heic" + struct.pack(">I", 0) + b"mif1heic")
    hdlr = _full(b"hdlr", 0, b"\x00" * 4 + b"pict" + b"\x00" * 12 + b"\x00")
    pitm = _full(b"pitm", 0, struct.pack(">H", 1))
    infe1 = _full(b"infe", 2, struct.pack(">HH", 1, 0) + b"hvc1" + b"\x00")
    infe2 = _full(b"infe", 2, struct.pack(">HH", 2, 0) + b"Exif" + b"\x00")
    iinf = _full(b"iinf", 0, struct.pack(">H", 2) + infe1 + infe2)

    def iloc(exif_off):
        # Version 1, offset/length 4 Byte, base 0, index 0
        items = struct.pack(">H", 2)
        items += struct.pack(">HHH", 1, 0, 0) + struct.pack(">H", 1) + struct.pack(">II", 0, 0)
        items += struct.pack(">HHH", 2, 0, 0) + struct.pack(">H", 1) + struct.pack(">II", exif_off, len(exif_item))
        return _full(b"iloc", 1, bytes([0x44, 0x00]) + items)

    meta = _full(b"meta", 0, hdlr + pitm + iloc(0) + iinf)
    exif_off = len(ftyp) + len(meta) + 8 + 16  # 16 Byte „Bilddaten“ vorneweg im mdat
    meta = _full(b"meta", 0, hdlr + pitm + iloc(exif_off) + iinf)
    mdat = _box(b"mdat", b"\x00" * 16 + exif_item)
    return ftyp + meta + mdat


def make_png(**kw) -> bytes:
    import zlib
    tiff = make_tiff(**kw)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"eXIf", tiff)
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b""))


def write(path: str, data: bytes, mtime: Optional[int] = None) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def synology_thumb(photo_path: str, size: str = "M", data: bytes = TINY_JPEG) -> str:
    folder, name = os.path.split(photo_path)
    return write(os.path.join(folder, "@eaDir", name, f"SYNOFOTO_THUMB_{size}.jpg"), data)


def make_video(lat=None, lon=None, apple=True, created_utc=None, duration_s=12.5, faststart=True,
               apple_date="2024-07-14T18:22:05+0200", model="iPhone 15 Pro") -> bytes:
    """Minimales MP4/MOV mit moov (mvhd, udta/©xyz bzw. Apple-meta keys/ilst) und einem mdat."""
    import datetime as _dt
    epoch = _dt.datetime(1904, 1, 1, tzinfo=_dt.timezone.utc)
    created = int(((created_utc or _dt.datetime(2024, 7, 14, 16, 22, 5, tzinfo=_dt.timezone.utc)) - epoch).total_seconds())
    scale = 600
    mvhd = _full(b"mvhd", 0, struct.pack(">IIII", created, created, scale, int(duration_s * scale)) + b"\x00" * 80)
    loc = f"{lat:+08.4f}{lon:+09.4f}+012.000/" if lat is not None else None
    parts = [mvhd]
    if apple:
        entries = []
        values = []
        if loc:
            entries.append(b"com.apple.quicktime.location.ISO6709")
            values.append(loc.encode())
        if apple_date:
            entries.append(b"com.apple.quicktime.creationdate")
            values.append(apple_date.encode())
        entries.append(b"com.apple.quicktime.model")
        values.append(model.encode())
        keys = _full(b"keys", 0, struct.pack(">I", len(entries)) + b"".join(
            struct.pack(">I", 8 + len(k)) + b"mdta" + k for k in entries))
        ilst = _box(b"ilst", b"".join(
            _box(struct.pack(">I", i + 1), _box(b"data", struct.pack(">II", 1, 0) + v)) for i, v in enumerate(values)))
        hdlr = _full(b"hdlr", 0, b"\x00" * 4 + b"mdta" + b"\x00" * 12 + b"\x00")
        parts.append(_box(b"meta", hdlr + keys + ilst))   # QuickTime: keine FullBox
    elif loc:
        xyz = loc.encode()
        parts.append(_box(b"udta", _box(b"\xa9xyz", struct.pack(">HH", len(xyz), 0x15C7) + xyz)))
    moov = _box(b"moov", b"".join(parts))
    ftyp = _box(b"ftyp", (b"qt  " if apple else b"isom") + struct.pack(">I", 0) + b"isomiso2mp41")
    mdat = _box(b"mdat", b"\x00" * 64)
    return ftyp + (moov + mdat if faststart else mdat + moov)
