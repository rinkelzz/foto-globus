"""Aufnahmeort und -zeit aus Fotos lesen – reines Python, ohne Pillow oder andere C-Erweiterungen.

Unterstützt:
- JPEG (APP1-„Exif“-Block)
- HEIC/HEIF (iPhone, viele Android-Geräte): ISO-Mediendatei, Exif-Eintrag über „iinf“/„iloc“
- TIFF und TIFF-basierte RAW-Formate (DNG, NEF, ARW, CR2)
- PNG mit „eXIf“-Block

Gelesen wird nur, was die Karte braucht: GPS (Breite, Länge, Höhe), Aufnahmezeit, Kamera,
Ausrichtung und – als Notlösung für fehlende Vorschaubilder – das eingebettete Mini-JPEG.
Alle Zugriffe sind begrenzt (Größen, Anzahl Einträge, Verschachtelung), damit kaputte oder
manipulierte Dateien den Scan nicht aufhalten oder Speicher fressen.
"""
import os
import struct
from datetime import datetime, timedelta, timezone
from typing import BinaryIO, Dict, Optional, Tuple

MAX_EXIF = 512 * 1024          # größer ist kein echter Exif-Block
MAX_IFD_ENTRIES = 1000
MAX_BOXES = 2000
JPEG_SCAN_LIMIT = 4 * 1024 * 1024   # so weit suchen wir in einer JPEG-Datei nach dem Exif-Block

PHOTO_EXTS = {".jpg", ".jpeg", ".jpe", ".heic", ".heif", ".hif", ".png", ".tif", ".tiff",
              ".dng", ".nef", ".arw", ".cr2"}


class ExifError(ValueError):
    pass


# ---------------------------------------------------------------------------
# TIFF-Struktur (Kern von Exif)
# ---------------------------------------------------------------------------

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 11: 4, 12: 8}


class _Tiff:
    def __init__(self, data: bytes):
        if len(data) < 8:
            raise ExifError("Exif zu kurz")
        if data[:2] == b"II":
            self.e = "<"
        elif data[:2] == b"MM":
            self.e = ">"
        else:
            raise ExifError("kein TIFF-Kopf")
        if struct.unpack(self.e + "H", data[2:4])[0] != 42:
            raise ExifError("kein TIFF-Kopf")
        self.d = data
        self.first_ifd = struct.unpack(self.e + "I", data[4:8])[0]

    def u16(self, off: int) -> int:
        return struct.unpack_from(self.e + "H", self.d, off)[0]

    def u32(self, off: int) -> int:
        return struct.unpack_from(self.e + "I", self.d, off)[0]

    def ifd(self, off: int) -> Tuple[Dict[int, Tuple[int, int, int]], int]:
        """Einträge {tag: (typ, anzahl, wert_offset)} und Offset der nächsten IFD."""
        if off <= 0 or off + 2 > len(self.d):
            return {}, 0
        n = self.u16(off)
        if n > MAX_IFD_ENTRIES or off + 2 + n * 12 > len(self.d):
            return {}, 0
        out = {}
        for i in range(n):
            p = off + 2 + i * 12
            tag, typ, count = struct.unpack_from(self.e + "HHI", self.d, p)
            size = _TYPE_SIZES.get(typ, 0) * count
            if size == 0:
                continue
            voff = p + 8 if size <= 4 else self.u32(p + 8)
            if voff + size > len(self.d):
                continue
            out[tag] = (typ, count, voff)
        nxt_pos = off + 2 + n * 12
        nxt = self.u32(nxt_pos) if nxt_pos + 4 <= len(self.d) else 0
        return out, nxt

    def value(self, entry):
        typ, count, off = entry
        e = self.e
        if typ == 2:
            raw = self.d[off:off + count]
            return raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
        if typ in (1, 7):
            return self.d[off:off + count]
        if typ == 3:
            vals = struct.unpack_from(e + "%dH" % count, self.d, off)
        elif typ == 4:
            vals = struct.unpack_from(e + "%dI" % count, self.d, off)
        elif typ == 9:
            vals = struct.unpack_from(e + "%di" % count, self.d, off)
        elif typ in (5, 10):
            fmt = "I" if typ == 5 else "i"
            raw = struct.unpack_from(e + "%d%s" % (count * 2, fmt), self.d, off)
            vals = tuple((raw[i] / raw[i + 1]) if raw[i + 1] else None for i in range(0, len(raw), 2))
        else:
            return None
        return vals[0] if count == 1 else vals


def _dms(vals) -> Optional[float]:
    if not isinstance(vals, tuple) or len(vals) < 3 or any(v is None for v in vals[:3]):
        if isinstance(vals, float):
            return vals
        return None
    return vals[0] + vals[1] / 60.0 + vals[2] / 3600.0


def _parse_dt(text: str, offset: str = "") -> Optional[str]:
    """'2024:07:14 18:22:05' (+ '+02:00') → ISO-Zeit. Ohne Offset: lokale Uhrzeit der Kamera (naiv)."""
    text = (text or "").strip().replace("\x00", "")
    if len(text) < 19 or text.startswith("0000"):
        return None
    try:
        dt = datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if not 1900 <= dt.year <= 2100:
        return None
    off = (offset or "").strip()
    if len(off) == 6 and off[0] in "+-" and off[3] == ":":
        try:
            h, m = int(off[1:3]), int(off[4:6])
            delta = timedelta(hours=h, minutes=m)
            dt = dt.replace(tzinfo=timezone(delta if off[0] == "+" else -delta))
        except ValueError:
            pass
    return dt.isoformat()


def parse_tiff(data: bytes) -> Dict:
    """Wertet einen TIFF/Exif-Block aus. Liefert nur gefundene Felder."""
    t = _Tiff(data)
    info: Dict = {}
    ifd0, ifd1_off = t.ifd(t.first_ifd)
    for tag, key in ((0x010F, "make"), (0x0110, "model")):
        if tag in ifd0:
            v = t.value(ifd0[tag])
            if isinstance(v, str) and v:
                info[key] = v[:64]
    if 0x0112 in ifd0:
        v = t.value(ifd0[0x0112])
        if isinstance(v, int) and 1 <= v <= 8:
            info["orientation"] = v
    dt_text = t.value(ifd0[0x0132]) if 0x0132 in ifd0 else ""

    # Exif-Unter-IFD: Aufnahmezeit, Bildgröße
    if 0x8769 in ifd0:
        ex_off = t.value(ifd0[0x8769])
        if isinstance(ex_off, int):
            ex, _ = t.ifd(ex_off)
            orig = t.value(ex[0x9003]) if 0x9003 in ex else ""
            off = t.value(ex[0x9011]) if 0x9011 in ex else ""
            dt_text = orig or (t.value(ex[0x9004]) if 0x9004 in ex else "") or dt_text
            taken = _parse_dt(dt_text if isinstance(dt_text, str) else "", off if isinstance(off, str) else "")
            if taken:
                info["taken_at"] = taken
            for tag, key in ((0xA002, "width"), (0xA003, "height")):
                if tag in ex:
                    v = t.value(ex[tag])
                    if isinstance(v, int) and 0 < v < 1_000_000:
                        info[key] = v
    if "taken_at" not in info and isinstance(dt_text, str):
        taken = _parse_dt(dt_text)
        if taken:
            info["taken_at"] = taken

    # GPS-IFD
    if 0x8825 in ifd0:
        g_off = t.value(ifd0[0x8825])
        if isinstance(g_off, int):
            g, _ = t.ifd(g_off)
            lat = _dms(t.value(g[2])) if 2 in g else None
            lon = _dms(t.value(g[4])) if 4 in g else None
            if lat is not None and lon is not None:
                lat_ref = t.value(g[1]) if 1 in g else "N"
                lon_ref = t.value(g[3]) if 3 in g else "E"
                if isinstance(lat_ref, str) and lat_ref.upper().startswith("S"):
                    lat = -lat
                if isinstance(lon_ref, str) and lon_ref.upper().startswith("W"):
                    lon = -lon
                # 0/0 heißt bei vielen Kameras „kein Fix“
                if -90 <= lat <= 90 and -180 <= lon <= 180 and not (abs(lat) < 1e-6 and abs(lon) < 1e-6):
                    info["lat"] = round(lat, 6)
                    info["lon"] = round(lon, 6)
                    if 6 in g:
                        alt = t.value(g[6])
                        if isinstance(alt, float):
                            ref = t.value(g[5]) if 5 in g else b"\x00"
                            if isinstance(ref, bytes) and ref[:1] == b"\x01":
                                alt = -alt
                            info["alt"] = round(alt, 1)

    # IFD1: eingebettetes Vorschaubild (JPEG)
    if ifd1_off:
        ifd1, _ = t.ifd(ifd1_off)
        if 0x0201 in ifd1 and 0x0202 in ifd1:
            start, length = t.value(ifd1[0x0201]), t.value(ifd1[0x0202])
            if isinstance(start, int) and isinstance(length, int) and 0 < length <= 512 * 1024 \
                    and start + length <= len(data) and data[start:start + 2] == b"\xff\xd8":
                info["_thumb"] = (start, length)
    return info


# ---------------------------------------------------------------------------
# Container: JPEG, HEIC, PNG, TIFF → Exif-Block finden
# ---------------------------------------------------------------------------

def _read(f: BinaryIO, off: int, n: int) -> bytes:
    f.seek(off)
    return f.read(n)


def _exif_from_jpeg(f: BinaryIO) -> Optional[bytes]:
    if _read(f, 0, 2) != b"\xff\xd8":
        return None
    pos = 2
    while pos < JPEG_SCAN_LIMIT:
        hdr = _read(f, pos, 4)
        if len(hdr) < 4 or hdr[0] != 0xFF:
            return None
        marker = hdr[1]
        if marker == 0xFF:          # Füllbyte
            pos += 1
            continue
        if marker in (0xD9, 0xDA):  # Ende oder Bilddaten – kein Exif mehr zu erwarten
            return None
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            pos += 2
            continue
        length = struct.unpack(">H", hdr[2:4])[0]
        if length < 2:
            return None
        if marker == 0xE1:
            body = _read(f, pos + 4, min(length - 2, MAX_EXIF))
            if body[:6] == b"Exif\x00\x00":
                return body[6:]
        pos += 2 + length
    return None


def _exif_from_png(f: BinaryIO) -> Optional[bytes]:
    if _read(f, 0, 8) != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    for _ in range(MAX_BOXES):
        hdr = _read(f, pos, 8)
        if len(hdr) < 8:
            return None
        length, typ = struct.unpack(">I4s", hdr)
        if typ == b"eXIf":
            if length > MAX_EXIF:
                return None
            data = _read(f, pos + 8, length)
            return data[6:] if data[:6] == b"Exif\x00\x00" else data
        if typ in (b"IDAT", b"IEND"):
            return None
        pos += 12 + length
    return None


def _boxes(f: BinaryIO, start: int, end: int):
    """ISO-Boxen zwischen start und end: (typ, inhalt_start, inhalt_ende)."""
    pos = start
    count = 0
    while pos + 8 <= end and count < MAX_BOXES:
        hdr = _read(f, pos, 8)
        if len(hdr) < 8:
            return
        size, typ = struct.unpack(">I4s", hdr)
        head = 8
        if size == 1:
            ext = _read(f, pos + 8, 8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            return
        yield typ, pos + head, pos + size
        pos += size
        count += 1


def _uint(b: bytes, off: int, n: int) -> int:
    if n == 0:
        return 0
    return int.from_bytes(b[off:off + n], "big")


def _exif_from_heif(f: BinaryIO, file_size: int) -> Optional[bytes]:
    ftyp = _read(f, 4, 4)
    if ftyp != b"ftyp":
        return None
    meta = None
    for typ, s, e in _boxes(f, 0, file_size):
        if typ == b"meta":
            meta = (s + 4, e)  # FullBox: Version/Flags überspringen
            break
    if not meta:
        return None
    exif_ids = set()
    iloc = idat = None
    for typ, s, e in _boxes(f, meta[0], meta[1]):
        if typ == b"iinf" and e - s < 1024 * 1024:
            b = _read(f, s, e - s)
            ver = b[0]
            cnt_size = 2 if ver == 0 else 4
            p = 4 + cnt_size
            while p + 8 <= len(b):
                size, btyp = struct.unpack_from(">I4s", b, p)
                if size < 8 or p + size > len(b):
                    break
                if btyp == b"infe":
                    iv = b[p + 8]
                    q = p + 12
                    if iv >= 2:
                        id_len = 2 if iv == 2 else 4
                        item_id = _uint(b, q, id_len)
                        item_type = b[q + id_len + 2:q + id_len + 6]
                        if item_type == b"Exif":
                            exif_ids.add(item_id)
                p += size
        elif typ == b"iloc" and e - s < 4 * 1024 * 1024:
            iloc = _read(f, s, e - s)
        elif typ == b"idat":
            idat = (s, e)
    if not exif_ids or not iloc:
        return None
    ver = iloc[0]
    sizes = iloc[4:6]
    off_size, len_size = sizes[0] >> 4, sizes[0] & 0xF
    base_size = sizes[1] >> 4
    idx_size = sizes[1] & 0xF if ver in (1, 2) else 0
    p = 6
    if ver < 2:
        count = _uint(iloc, p, 2)
        p += 2
    else:
        count = _uint(iloc, p, 4)
        p += 4
    for _ in range(min(count, 100000)):
        if p >= len(iloc):
            break
        id_len = 2 if ver < 2 else 4
        item_id = _uint(iloc, p, id_len)
        p += id_len
        method = 0
        if ver in (1, 2):
            method = _uint(iloc, p, 2) & 0xF
            p += 2
        p += 2  # data_reference_index
        base = _uint(iloc, p, base_size)
        p += base_size
        ext_count = _uint(iloc, p, 2)
        p += 2
        extents = []
        for _ in range(min(ext_count, 64)):
            p += idx_size
            ext_off = _uint(iloc, p, off_size)
            p += off_size
            ext_len = _uint(iloc, p, len_size)
            p += len_size
            extents.append((ext_off, ext_len))
        if item_id not in exif_ids:
            continue
        data = b""
        for ext_off, ext_len in extents:
            if ext_len > MAX_EXIF or len(data) > MAX_EXIF:
                return None
            if method == 0:
                data += _read(f, base + ext_off, ext_len)
            elif method == 1 and idat:
                data += _read(f, idat[0] + base + ext_off, ext_len)
        if len(data) < 4:
            return None
        start = 4 + struct.unpack(">I", data[:4])[0]
        block = data[start:]
        if block[:6] == b"Exif\x00\x00":
            block = block[6:]
        return block
    return None


def open_nofollow(path: str) -> BinaryIO:
    """Datei lesen, aber keinem symbolischen Link folgen (sonst ließe sich über einen Link eine fremde Datei unterschieben)."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    return os.fdopen(fd, "rb")


def read_exif_block(path: str) -> Tuple[Optional[bytes], str]:
    """(TIFF-Daten des Exif-Blocks, Containerart) – oder (None, Art), wenn keiner da ist."""
    with open_nofollow(path) as f:
        size = os.fstat(f.fileno()).st_size
        head = f.read(16)
        if head[:2] == b"\xff\xd8":
            return _exif_from_jpeg(f), "jpeg"
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return _exif_from_png(f), "png"
        if head[4:8] == b"ftyp":
            return _exif_from_heif(f, size), "heif"
        if head[:4] in (b"II*\x00", b"MM\x00*"):
            f.seek(0)
            return f.read(min(size, MAX_EXIF * 8)), "tiff"
    return None, "unbekannt"


def read_photo(path: str) -> Dict:
    """Metadaten eines Fotos. Felder fehlen, wenn nichts da ist. Wirft OSError bei Lesefehlern."""
    block, kind = read_exif_block(path)
    if not block:
        return {"kind": kind}
    try:
        info = parse_tiff(block)
    except (ExifError, struct.error, IndexError, ValueError):
        return {"kind": kind}
    info.pop("_thumb", None)
    info["kind"] = kind
    return info


def embedded_thumbnail(path: str) -> Optional[bytes]:
    """Das in Exif eingebettete Mini-JPEG (meist 160×120) – Notlösung, wenn DSM noch keine Vorschau hat."""
    try:
        block, _ = read_exif_block(path)
        if not block:
            return None
        info = parse_tiff(block)
    except (OSError, ExifError, struct.error, IndexError, ValueError):
        return None
    th = info.get("_thumb")
    if not th:
        return None
    return block[th[0]:th[0] + th[1]]
