"""Vorschaubilder – ohne eigene Bildverarbeitung.

Synology Photos legt zu jedem Foto Vorschauen in einem versteckten Ordner an:
    <ordner>/@eaDir/<dateiname>/SYNOFOTO_THUMB_SM.jpg   (klein, ~240 px)
                                SYNOFOTO_THUMB_M.jpg    (mittel, ~320 px)
                                SYNOFOTO_THUMB_XL.jpg   (groß, ~1280 px)
Ältere Photo-Station-Installationen nutzen SYNOPHOTO_THUMB_*. Fehlt alles, nehmen wir das kleine JPEG,
das die Kamera in die Exif-Daten einbettet – und für die Großansicht notfalls das Original (nur JPEG/PNG,
HEIC können die meisten Browser nicht anzeigen).
"""
import os
from typing import Optional, Tuple

from . import exif

SIZES = {
    "sm": ("SM", "S", "M"),
    "m": ("M", "SM", "B", "L", "XL"),
    "xl": ("XL", "L", "B", "M"),
}
PREFIXES = ("SYNOFOTO_THUMB_", "SYNOPHOTO_THUMB_")
BROWSER_SAFE = {".jpg", ".jpeg", ".jpe", ".png"}


def inside(path: str, root: str) -> bool:
    """Liegt path wirklich (nach Auflösen aller Links) unterhalb von root und ist selbst kein Link?

    Schützt davor, dass jemand mit Schreibrechten in einem Fotoordner einen Link auf eine fremde Datei legt
    (z. B. auf die persönlichen Fotos eines anderen Benutzers, die der Paketbenutzer lesen kann)."""
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False
        real = os.path.realpath(path)
        base = os.path.realpath(root)
    except OSError:
        return False
    return real.startswith(base.rstrip("/") + "/")


def synology_thumb(path: str, size: str) -> Optional[str]:
    folder, name = os.path.split(path)
    base = os.path.join(folder, "@eaDir", name)
    for s in SIZES.get(size, SIZES["m"]):
        for prefix in PREFIXES:
            p = os.path.join(base, f"{prefix}{s}.jpg")
            if inside(p, base):
                return p
    return None


def find(path: str, size: str, root: str) -> Tuple[Optional[str], Optional[bytes], str]:
    """(Datei, Bytes, Medientyp) – entweder ein Pfad zum Ausliefern oder fertige Bytes.

    root = Bereich, in dem das Foto liegen muss (gemeinsamer Ordner bzw. Photos-Ordner des Besitzers)."""
    if not inside(path, root):
        return None, None, ""
    p = synology_thumb(path, size)
    if p:
        return p, None, "image/jpeg"
    ext = os.path.splitext(path)[1].lower()
    if size == "xl" and ext in BROWSER_SAFE:
        return path, None, "image/png" if ext == ".png" else "image/jpeg"
    data = exif.embedded_thumbnail(path)
    if data:
        return None, data, "image/jpeg"
    if ext in BROWSER_SAFE and os.path.getsize(path) < 8 * 1024 * 1024:
        return path, None, "image/png" if ext == ".png" else "image/jpeg"
    return None, None, ""
