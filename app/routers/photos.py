"""Fotos für den Globus: Punkte, Details, Vorschaubilder und Originale – immer nach den Rechten des DSM-Kontos."""
import os
import sqlite3
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import access, scanner, thumbs
from ..db import get_db, get_setting
from ..security import current_user, photo_user

router = APIRouter(prefix="/api/v1", tags=["Fotos"])


def _under(path: str, root: Optional[str]) -> bool:
    return bool(root) and (path == root or path.startswith(root.rstrip("/") + "/"))


def shared_folders_allowed(conn: sqlite3.Connection, user: str, folders: Set[str]) -> Set[str]:
    """Welche Ordner des gemeinsamen Bereichs darf user sehen?"""
    root = scanner.shared_root(conn)
    folders = {f for f in folders if _under(f, root)}
    if get_setting(conn, "share_access") == "all":
        return folders
    return access.readable_folders(folders, root, user)


def visible_rows(conn: sqlite3.Connection, user: str, sql_cols: str, where: str = "1=1", params=()) -> List[sqlite3.Row]:
    rows = conn.execute(
        f"SELECT {sql_cols}, scope, owner, folder FROM photos "
        f"WHERE ({where}) AND (scope = 'shared' OR (scope = 'personal' AND owner = ? COLLATE NOCASE))",
        tuple(params) + (user,),
    ).fetchall()
    shared = {r["folder"] for r in rows if r["scope"] == "shared"}
    allowed = shared_folders_allowed(conn, user, shared) if shared else set()
    return [r for r in rows if r["scope"] == "personal" or r["folder"] in allowed]


def _photo(conn: sqlite3.Connection, user: str, photo_id: int) -> sqlite3.Row:
    rows = visible_rows(conn, user, "id, path, name, kind", "id = ?", (photo_id,))
    if not rows:
        raise HTTPException(404, "Foto nicht gefunden")
    return rows[0]


def _area(conn: sqlite3.Connection, r) -> str:
    """Bereich, in dem die Datei liegen muss: gemeinsamer Fotoordner oder Photos-Ordner des Besitzers."""
    if r["scope"] == "shared":
        return scanner.shared_root(conn) or "/nirgends"
    homes = scanner.homes_root(conn)
    return os.path.join(homes, r["owner"], "Photos") if homes and r["owner"] else "/nirgends"


@router.get("/points")
def points(year_from: Optional[int] = Query(None, ge=1900, le=2100), year_to: Optional[int] = Query(None, ge=1900, le=2100),
           user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    """Alle sichtbaren Fotos mit Aufnahmeort, kompakt: [id, breite, länge, datum, bereich, jahr]."""
    rows = visible_rows(conn, user, "id, lat, lon, taken_at, year", "lat IS NOT NULL")
    years = sorted({r["year"] for r in rows if r["year"]})
    if year_from:
        rows = [r for r in rows if (r["year"] or 0) >= year_from]
    if year_to:
        rows = [r for r in rows if (r["year"] or 9999) <= year_to]
    no_gps = len(visible_rows(conn, user, "id", "lat IS NULL"))
    return {
        "points": [[r["id"], r["lat"], r["lon"], (r["taken_at"] or "")[:10] or None, "p" if r["scope"] == "personal" else "s", r["year"]]
                   for r in rows],
        "years": years,
        "count": len(rows),
        "without_gps": no_gps,
    }


class InfoIn(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=2000)


def _rel(conn, r) -> str:
    root = scanner.shared_root(conn) if r["scope"] == "shared" else None
    if root and _under(r["folder"], root):
        rel = os.path.relpath(r["folder"], root)
        return "" if rel == "." else rel
    # persönlich: Pfad unterhalb von Photos
    idx = r["folder"].find("/Photos")
    return r["folder"][idx + 8:] if idx >= 0 else ""


@router.post("/photos/info")
def photo_info(data: InfoIn, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    """Details zu mehreren Fotos (z. B. alle Fotos einer Pinnadel), nach Aufnahmezeit sortiert."""
    ids = list(dict.fromkeys(data.ids))
    out: Dict[int, dict] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in visible_rows(conn, user, "id, name, taken_at, lat, lon, alt, make, model, width, height, kind, size",
                              f"id IN ({','.join('?' * len(chunk))})", chunk):
            out[r["id"]] = {
                "id": r["id"], "name": r["name"], "taken_at": r["taken_at"], "lat": r["lat"], "lon": r["lon"],
                "alt": r["alt"], "camera": " ".join(x for x in (r["make"], r["model"]) if x) or None,
                "width": r["width"], "height": r["height"], "kind": r["kind"], "size": r["size"],
                "scope": r["scope"], "folder": _rel(conn, r),
            }
    return sorted(out.values(), key=lambda p: (p["taken_at"] or "", p["name"]))


@router.get("/photos/{photo_id}/thumb/{size}")
def thumb(photo_id: int, size: str, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    if size not in thumbs.SIZES:
        raise HTTPException(404, "Unbekannte Größe")
    r = _photo(conn, user, photo_id)
    path, data, media = thumbs.find(r["path"], size, _area(conn, r))
    headers = {"Cache-Control": "private, max-age=86400"}
    if path:
        return FileResponse(path, media_type=media, headers=headers)
    if data:
        return Response(data, media_type=media, headers=headers)
    raise HTTPException(404, "Keine Vorschau vorhanden")


@router.get("/photos/{photo_id}/original")
def original(photo_id: int, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    r = _photo(conn, user, photo_id)
    if not thumbs.inside(r["path"], _area(conn, r)):
        raise HTTPException(404, "Datei nicht mehr vorhanden")
    return FileResponse(r["path"], filename=r["name"], media_type="application/octet-stream",
                        headers={"Cache-Control": "private, no-store"})


@router.get("/map-config")
def map_config(conn: sqlite3.Connection = Depends(get_db), user=Depends(current_user)):
    """Kartenstil für den Browser (leer = nur die Offline-Kugel mit Ländergrenzen)."""
    return {"style": get_setting(conn, "map_style") or ""}
