"""Fotos und Videos für den Globus: Punkte, Details, Vorschauen, Originale, Videos, Statistik und Suche –
immer nach den Rechten des DSM-Kontos."""
import hashlib
import hmac
import os
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import access, geo, scanner, thumbs
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


def visible_rows(conn: sqlite3.Connection, user: str, sql_cols: str, where: str = "1=1", params=(),
                 dedupe: bool = True) -> List[sqlite3.Row]:
    """Fotos, die user sehen darf. Mit dedupe zählt jede exakte Kopie (gleiche Größe + Prüfsumme) nur einmal."""
    rows = conn.execute(
        f"SELECT {sql_cols}, scope, owner, folder, size AS _size, hash AS _hash, mtime AS _mtime, id AS _id FROM photos "
        f"WHERE ({where}) AND (scope = 'shared' OR (scope = 'personal' AND owner = ? COLLATE NOCASE))",
        tuple(params) + (user,),
    ).fetchall()
    shared = {r["folder"] for r in rows if r["scope"] == "shared"}
    allowed = shared_folders_allowed(conn, user, shared) if shared else set()
    rows = [r for r in rows if r["scope"] == "personal" or r["folder"] in allowed]
    return without_duplicates(rows) if dedupe else rows


def without_duplicates(rows) -> list:
    """Von mehreren exakten Kopien bleibt eine: die eigene (persönlicher Bereich) zuerst, sonst die älteste Datei."""
    best: Dict[tuple, sqlite3.Row] = {}
    for r in rows:
        if not r["_hash"]:
            continue
        key = (r["_size"], r["_hash"])
        cur = best.get(key)
        rank = (0 if r["scope"] == "personal" else 1, r["_mtime"], r["_id"])
        if cur is None or rank < (0 if cur["scope"] == "personal" else 1, cur["_mtime"], cur["_id"]):
            best[key] = r
    keep = {id(r) for r in best.values()}
    return [r for r in rows if not r["_hash"] or id(r) in keep]


def _filtered(rows, year_from: Optional[int], year_to: Optional[int], scope: str):
    out = []
    for r in rows:
        if year_from and (r["year"] or 0) < year_from:
            continue
        if year_to and (r["year"] or 9999) > year_to:
            continue
        if scope == "p" and r["scope"] != "personal" or scope == "s" and r["scope"] != "shared":
            continue
        out.append(r)
    return out


def _photo(conn: sqlite3.Connection, user: str, photo_id: int) -> sqlite3.Row:
    rows = visible_rows(conn, user, "id, path, name, kind, media", "id = ?", (photo_id,), dedupe=False)
    if not rows:
        raise HTTPException(404, "Foto nicht gefunden")
    return rows[0]


def _area(conn: sqlite3.Connection, r) -> str:
    """Bereich, in dem die Datei liegen muss: gemeinsamer Fotoordner oder Photos-Ordner des Besitzers."""
    if r["scope"] == "shared":
        return scanner.shared_root(conn) or "/nirgends"
    homes = scanner.homes_root(conn)
    return os.path.join(homes, r["owner"], "Photos") if homes and r["owner"] else "/nirgends"


YearFrom = Query(None, ge=1900, le=2100)
YearTo = Query(None, ge=1900, le=2100)
Scope = Query("all", pattern="^(all|p|s)$")


@router.get("/points")
def points(year_from: Optional[int] = YearFrom, year_to: Optional[int] = YearTo,
           user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    """Alle sichtbaren Fotos/Videos mit Aufnahmeort, kompakt: [id, breite, länge, datum, bereich, jahr, art, land]."""
    rows = visible_rows(conn, user, "id, lat, lon, taken_at, year, media, cc", "lat IS NOT NULL")
    years = sorted({r["year"] for r in rows if r["year"]})
    rows = _filtered(rows, year_from, year_to, "all")
    no_gps = len(visible_rows(conn, user, "id", "lat IS NULL"))
    return {
        "points": [[r["id"], r["lat"], r["lon"], (r["taken_at"] or "")[:10] or None,
                    "p" if r["scope"] == "personal" else "s", r["year"], "v" if r["media"] == "video" else "f", r["cc"]]
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
    idx = r["folder"].find("/Photos")
    return r["folder"][idx + 8:] if idx >= 0 else ""


@router.post("/photos/info")
def photo_info(data: InfoIn, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    """Details zu mehreren Fotos (z. B. alle Fotos einer Pinnadel), nach Aufnahmezeit sortiert."""
    ids = list(dict.fromkeys(data.ids))
    out: Dict[int, dict] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in visible_rows(conn, user, "id, name, taken_at, lat, lon, alt, make, model, width, height, kind, size, "
                                          "media, duration, place, cc",
                              f"id IN ({','.join('?' * len(chunk))})", chunk, dedupe=False):
            out[r["id"]] = {
                "id": r["id"], "name": r["name"], "taken_at": r["taken_at"], "lat": r["lat"], "lon": r["lon"],
                "alt": r["alt"], "camera": " ".join(x for x in (r["make"], r["model"]) if x) or None,
                "width": r["width"], "height": r["height"], "kind": r["kind"], "size": r["size"],
                "media": r["media"], "duration": r["duration"],
                "place": r["place"], "cc": r["cc"], "country": geo.country_name(r["cc"]),
                "place_label": geo.label(r["place"], r["cc"]),
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


# --- Videos -------------------------------------------------------------------------------------------
# Ein <video>-Element kann keine eigenen Header mitschicken. Damit Abspielen auch dort klappt, wo der
# Login-Cookie nicht mitgeht (DSM-Fenster über eine andere Adresse), gibt es einen kurzlebigen, signierten
# Schlüssel nur für genau dieses Video und genau diesen Benutzer.

VIDEO_TOKEN_SECONDS = 4 * 3600


def _video_sig(user: str, photo_id: int, exp: int) -> str:
    from ..dsm_auth import proxy_secret
    msg = f"video|{user.lower()}|{photo_id}|{exp}".encode()
    return hmac.new(proxy_secret().encode(), msg, hashlib.sha256).hexdigest()[:40]


def make_video_token(user: str, photo_id: int, now: Optional[float] = None) -> str:
    exp = int((now or time.time()) + VIDEO_TOKEN_SECONDS)
    return f"{exp}.{user}.{_video_sig(user, photo_id, exp)}"


def check_video_token(token: str, photo_id: int, now: Optional[float] = None) -> Optional[str]:
    try:
        exp_s, rest = token.split(".", 1)
        user, sig = rest.rsplit(".", 1)
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < (now or time.time()) or not access.USER_RE.match(user):
        return None
    return user if hmac.compare_digest(sig, _video_sig(user, photo_id, exp)) else None


@router.get("/photos/{photo_id}/video-token")
def video_token(photo_id: int, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    r = _photo(conn, user, photo_id)
    if r["media"] != "video":
        raise HTTPException(404, "Kein Video")
    path, source = thumbs.video_file(r["path"], _area(conn, r))
    return {"token": make_video_token(user, photo_id), "playable": bool(path), "source": source}


@router.get("/photos/{photo_id}/video")
def video(photo_id: int, request: Request, vt: str = Query("", max_length=200),
          conn: sqlite3.Connection = Depends(get_db)):
    """Video zum Abspielen (mit Range, also spulbar). Anmeldung per Session/DSM oder per Video-Schlüssel."""
    user = check_video_token(vt, photo_id) if vt else None
    if not user:
        try:
            user = photo_user(request, current_user(request, conn))
        except HTTPException:
            raise HTTPException(404, "Video nicht gefunden")
    r = _photo(conn, user, photo_id)
    path, _source = thumbs.video_file(r["path"], _area(conn, r))
    if not path:
        raise HTTPException(404, "Dieses Video kann der Browser nicht abspielen – bitte herunterladen")
    return FileResponse(path, media_type="video/quicktime" if path.lower().endswith(".mov") else "video/mp4",
                        headers={"Cache-Control": "private, max-age=3600"})


# --- Statistik, Suche, Auswahl ------------------------------------------------------------------------

def _geo_rows(conn, user, year_from, year_to, scope):
    rows = visible_rows(conn, user, "id, lat, lon, year, place, cc, media", "lat IS NOT NULL")
    return _filtered(rows, year_from, year_to, scope)


def _bbox(rows) -> List[float]:
    lons = [r["lon"] for r in rows]
    lats = [r["lat"] for r in rows]
    w, e = min(lons), max(lons)
    # über die Datumsgrenze (z. B. Fidschi, Alaska): kleinere Ausdehnung wählen
    shifted = [x + 360 if x < 0 else x for x in lons]
    if max(shifted) - min(shifted) < e - w:
        w, e = min(shifted), max(shifted)
        w = w - 360 if w > 180 else w
        e = e - 360 if e > 180 else e
    return [round(w, 4), round(min(lats), 4), round(e, 4), round(max(lats), 4)]


@router.get("/stats")
def stats(year_from: Optional[int] = YearFrom, year_to: Optional[int] = YearTo, scope: str = Scope,
          user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    """Länder, Orte, Fotos pro Jahr und die meistbesuchten Orte – passend zum gesetzten Filter."""
    rows = _geo_rows(conn, user, year_from, year_to, scope)
    by_cc: Dict[str, list] = defaultdict(list)
    by_place: Dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r["cc"]:
            by_cc[r["cc"]].append(r)
            if r["place"]:
                by_place[(r["place"], r["cc"])].append(r)
    countries = sorted(({"cc": cc, "name": geo.country_name(cc), "count": len(rs),
                         "places": len({r["place"] for r in rs if r["place"]}), "bbox": _bbox(rs)}
                        for cc, rs in by_cc.items()), key=lambda c: (-c["count"], c["name"]))
    top = sorted(by_place.items(), key=lambda kv: (-len(kv[1]), kv[0][0]))[:10]
    all_years = Counter(r["year"] for r in _filtered(
        visible_rows(conn, user, "id, year", "1=1"), None, None, scope) if r["year"])
    return {
        "photos": len(rows),
        "videos": sum(1 for r in rows if r["media"] == "video"),
        "countries": countries,
        "places": len(by_place),
        "top_places": [{"place": p, "cc": cc, "label": geo.label(p, cc), "count": len(rs), "bbox": _bbox(rs)}
                       for (p, cc), rs in top],
        "years": [{"year": y, "count": n} for y, n in sorted(all_years.items())],
        "visited": sorted(by_cc),
    }


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(t.replace("-", " ").split())


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=80), year_from: Optional[int] = YearFrom,
           year_to: Optional[int] = YearTo, scope: str = Scope,
           user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    """Orte und Länder mit eigenen Fotos, die zum Suchbegriff passen (beginnt-mit vor enthält)."""
    needle = _norm(q)
    if not needle:
        return []
    rows = _geo_rows(conn, user, year_from, year_to, scope)
    by_cc: Dict[str, list] = defaultdict(list)
    by_place: Dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r["cc"]:
            by_cc[r["cc"]].append(r)
            if r["place"]:
                by_place[(r["place"], r["cc"])].append(r)
    hits = []
    for cc, rs in by_cc.items():
        names = {_norm(geo.country_name(cc)), cc.lower()}
        rank = 0 if any(n.startswith(needle) for n in names) else 1 if any(needle in n for n in names) else None
        if rank is not None:
            hits.append((rank, -len(rs), {"type": "country", "cc": cc, "label": geo.country_name(cc),
                                          "count": len(rs), "bbox": _bbox(rs)}))
    for (place, cc), rs in by_place.items():
        n = _norm(place)
        rank = 0 if n.startswith(needle) else 1 if needle in n else None
        if rank is not None:
            hits.append((rank, -len(rs), {"type": "place", "cc": cc, "place": place, "label": geo.label(place, cc),
                                          "count": len(rs), "bbox": _bbox(rs)}))
    hits.sort(key=lambda h: (h[0], h[1], h[2]["label"]))
    return [h[2] for h in hits[:12]]


@router.get("/photos/where")
def photos_where(cc: str = Query(..., pattern="^[A-Z]{2}$"), place: Optional[str] = Query(None, max_length=200),
                 year_from: Optional[int] = YearFrom, year_to: Optional[int] = YearTo, scope: str = Scope,
                 user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    """IDs aller sichtbaren Fotos eines Landes oder Orts (für die Galerie nach Suche oder Statistik)."""
    rows = [r for r in _geo_rows(conn, user, year_from, year_to, scope)
            if r["cc"] == cc and (place is None or r["place"] == place)]
    if not rows:
        raise HTTPException(404, "Keine Fotos gefunden")
    return {"ids": [r["id"] for r in rows], "count": len(rows), "bbox": _bbox(rows),
            "label": geo.label(place, cc) if place else geo.country_name(cc)}


@router.get("/map-config")
def map_config(conn: sqlite3.Connection = Depends(get_db), user=Depends(current_user)):
    """Kartenstil für den Browser (leer = nur die Offline-Kugel mit Ländergrenzen), Satellit, Synology Photos."""
    sat = get_setting(conn, "satellite")
    key = get_setting(conn, "maptiler_key")
    satellite = None
    if sat == "esri":
        satellite = {"type": "esri"}
    elif sat == "maptiler" and key:
        # Der Schlüssel landet zwangsläufig im Browser – bei MapTiler auf die eigene Adresse beschränken
        satellite = {"type": "maptiler", "style": f"https://api.maptiler.com/maps/hybrid/style.json?key={key}"}
    return {"style": get_setting(conn, "map_style") or "", "satellite": satellite,
            "photos_url": get_setting(conn, "photos_url") or ""}
