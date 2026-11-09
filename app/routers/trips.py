"""Reisen und Zuhause – pro DSM-Benutzer, berechnet aus den Fotos, die er sehen darf."""
import sqlite3
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import geo, trips as T
from ..db import audit, get_db
from ..security import photo_user
from ..timeutil import now_utc_str
from .photos import _bbox, visible_rows

router = APIRouter(prefix="/api/v1", tags=["Reisen"])

COLS = "id, lat, lon, taken_at, year, place, cc, media"


def _load(conn: sqlite3.Connection, user: str):
    rows = visible_rows(conn, user, COLS, "lat IS NOT NULL")
    home = T.home_of(conn, user, rows)
    away = T.away_rows(rows, home)
    T.sync(conn, user, away)
    return rows, home, away


def _trip_out(trip, mem) -> dict:
    ccs = []
    for r in mem:
        if r["cc"] and r["cc"] not in ccs:
            ccs.append(r["cc"])
    start, end = trip["start_day"], trip["end_day"]
    return {
        "id": trip["id"], "title": trip["title"] or T.auto_title(trip, mem), "auto_title": T.auto_title(trip, mem),
        "renamed": bool(trip["title"]), "edited": not trip["auto"], "hidden": bool(trip["hidden"]),
        "start": start, "end": end, "days": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1,
        "count": len(mem), "videos": sum(1 for r in mem if r["media"] == "video"),
        "countries": [{"cc": c, "name": geo.country_name(c)} for c in ccs],
        "cover": mem[len(mem) // 2]["id"] if mem else None,
        "bbox": _bbox(mem) if mem else None,
    }


def _own(conn, user, trip_id):
    t = conn.execute("SELECT * FROM trips WHERE id = ? AND owner = ?", (trip_id, user)).fetchone()
    if not t:
        raise HTTPException(404, "Reise nicht gefunden")
    return t


@router.get("/trips")
def list_trips(year_from: Optional[int] = Query(None, ge=1900, le=2100), year_to: Optional[int] = Query(None, ge=1900, le=2100),
               user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    rows, home, away = _load(conn, user)
    out, hidden = [], 0
    for t in conn.execute("SELECT * FROM trips WHERE owner = ? ORDER BY start_day DESC", (user,)).fetchall():
        if year_from and int(t["end_day"][:4]) < year_from or year_to and int(t["start_day"][:4]) > year_to:
            continue
        mem = T.members(t, away)
        if not mem:
            continue  # z. B. nach geänderten Rechten keine Fotos mehr sichtbar
        if t["hidden"]:
            hidden += 1
        out.append(_trip_out(t, mem))
    return {"home": home, "trips": out, "hidden": hidden, "away_km": T.AWAY_KM}


@router.get("/trips/{trip_id}")
def get_trip(trip_id: int, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    rows, home, away = _load(conn, user)
    t = _own(conn, user, trip_id)
    mem = T.members(t, away)
    if not mem:
        raise HTTPException(404, "Keine Fotos in dieser Reise")
    others = conn.execute("SELECT id, start_day FROM trips WHERE owner = ? AND hidden = 0 ORDER BY start_day",
                          (user,)).fetchall()
    ids = [o["id"] for o in others]
    idx = ids.index(t["id"]) if t["id"] in ids else -1
    return {**_trip_out(t, mem),
            "ids": [r["id"] for r in sorted(mem, key=lambda r: (r["taken_at"], r["id"]))],
            "route": T.route(mem),
            "photo_days": sorted({r["taken_at"][:10] for r in mem}),
            "prev": ids[idx - 1] if idx > 0 else None,
            "next": ids[idx + 1] if 0 <= idx < len(ids) - 1 else None}


class TripIn(BaseModel):
    title: Optional[str] = Field(None, max_length=120, description="leer = automatischer Name")
    hidden: Optional[bool] = None


@router.patch("/trips/{trip_id}")
def update_trip(trip_id: int, data: TripIn, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    t = _own(conn, user, trip_id)
    changes = data.model_dump(exclude_unset=True)
    if "title" in changes:
        title = (changes["title"] or "").strip() or None
        conn.execute("UPDATE trips SET title = ?, auto = 0 WHERE id = ?", (title, t["id"]))
    if changes.get("hidden") is not None:
        conn.execute("UPDATE trips SET hidden = ?, auto = 0 WHERE id = ?", (int(changes["hidden"]), t["id"]))
    audit(conn, None, "trip_updated", f"trip:{t['id']}", f"{user}: {', '.join(sorted(changes))}")
    return get_trip(t["id"], user, conn)


class SplitIn(BaseModel):
    day: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="erster Tag der zweiten Reise")


@router.post("/trips/{trip_id}/split")
def split_trip(trip_id: int, data: SplitIn, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    t = _own(conn, user, trip_id)
    if not t["start_day"] < data.day <= t["end_day"]:
        raise HTTPException(400, "Der Tag muss nach dem ersten und spätestens am letzten Reisetag liegen")
    first_end = (date.fromisoformat(data.day) - timedelta(days=1)).isoformat()
    conn.execute("UPDATE trips SET end_day = ?, auto = 0 WHERE id = ?", (first_end, t["id"]))
    new_id = conn.execute("INSERT INTO trips(owner, start_day, end_day, title, auto, hidden, created_at) "
                          "VALUES (?, ?, ?, NULL, 0, ?, ?)",
                          (user, data.day, t["end_day"], t["hidden"], now_utc_str())).lastrowid
    audit(conn, None, "trip_split", f"trip:{t['id']}", f"{user}: ab {data.day} → trip:{new_id}")
    return {"first": t["id"], "second": new_id}


class MergeIn(BaseModel):
    other: int


@router.post("/trips/{trip_id}/merge")
def merge_trip(trip_id: int, data: MergeIn, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    a, b = _own(conn, user, trip_id), _own(conn, user, data.other)
    if a["id"] == b["id"]:
        raise HTTPException(400, "Eine Reise lässt sich nicht mit sich selbst zusammenführen")
    first = a if a["start_day"] <= b["start_day"] else b
    start, end = min(a["start_day"], b["start_day"]), max(a["end_day"], b["end_day"])
    # dazwischen liegende Reisen gehen mit auf
    conn.execute("DELETE FROM trips WHERE owner = ? AND id NOT IN (?, ?) AND start_day >= ? AND end_day <= ?",
                 (user, a["id"], b["id"], start, end))
    conn.execute("UPDATE trips SET start_day = ?, end_day = ?, title = ?, auto = 0, hidden = 0 WHERE id = ?",
                 (start, end, first["title"], a["id"]))
    conn.execute("DELETE FROM trips WHERE id = ?", (b["id"],))
    audit(conn, None, "trip_merged", f"trip:{a['id']}", f"{user}: mit trip:{b['id']}")
    return get_trip(a["id"], user, conn)


@router.post("/trips/reset")
def reset_trips(user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    """Alle eigenen Änderungen an Reisen verwerfen – danach wird neu erkannt."""
    n = conn.execute("DELETE FROM trips WHERE owner = ?", (user,)).rowcount
    audit(conn, None, "trips_reset", "trips", f"{user}: {n} Reisen")
    return list_trips(None, None, user, conn)


class HomeIn(BaseModel):
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    auto: bool = False


@router.put("/home")
def set_home(data: HomeIn, user: str = Depends(photo_user), conn: sqlite3.Connection = Depends(get_db)):
    if data.auto:
        conn.execute("DELETE FROM homes WHERE owner = ?", (user,))
    else:
        if data.lat is None or data.lon is None:
            raise HTTPException(400, "Bitte einen Ort angeben")
        conn.execute("INSERT INTO homes(owner, lat, lon, updated_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(owner) DO UPDATE SET lat = excluded.lat, lon = excluded.lon, updated_at = excluded.updated_at",
                     (user, round(data.lat, 5), round(data.lon, 5), now_utc_str()))
    # Zuhause bestimmt, was „unterwegs“ ist – automatische Reisen neu erkennen
    conn.execute("DELETE FROM trips WHERE owner = ? AND auto = 1", (user,))
    audit(conn, None, "home_set", "home", f"{user}: {'automatisch' if data.auto else 'gesetzt'}")
    return list_trips(None, None, user, conn)
