"""Reisen automatisch erkennen.

Regel (mit Tim abgestimmt):
- **Zuhause** ist der Ort, an dem man an den meisten verschiedenen Tagen fotografiert hat (Raster ~11 km).
  Jeder kann es selbst setzen; dann gilt das gesetzte.
- **Reise** = Fotos mehr als 100 km von Zuhause entfernt, zeitlich zusammenhängend: zwischen zwei Fototagen
  liegen höchstens 2 Tage ohne Fotos. Mindestens 3 Fotos.

Bearbeitete Reisen (umbenannt, geteilt, zusammengeführt, ausgeblendet) bleiben bei jeder Neuberechnung erhalten;
automatische Reisen, die sich mit ihnen überschneiden, entfallen. Zu einer Reise gehören alle Fotos außerhalb des
Zuhause-Umkreises, deren Aufnahmetag im Zeitraum der Reise liegt.
"""
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from . import geo
from .timeutil import now_utc_str

AWAY_KM = 100.0
MAX_GAP_DAYS = 2
MIN_PHOTOS = 3
HOME_CELL = 0.1      # Grad (~11 km)
STOP_KM = 3.0        # Fotos innerhalb von 3 km zählen als ein Halt auf der Route

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]


def km(la1, lo1, la2, lo2) -> float:
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def _day(row) -> Optional[str]:
    t = row["taken_at"]
    return t[:10] if t and len(t) >= 10 else None


def auto_home(rows) -> Optional[Tuple[float, float]]:
    """Ort mit den meisten verschiedenen Fototagen (nicht den meisten Fotos – Urlaube erzeugen viele Fotos am Tag)."""
    days: Dict[Tuple[int, int], set] = defaultdict(set)
    pts: Dict[Tuple[int, int], List[Tuple[float, float]]] = defaultdict(list)
    for r in rows:
        d = _day(r)
        if not d:
            continue
        cell = (int(math.floor(r["lat"] / HOME_CELL)), int(math.floor(r["lon"] / HOME_CELL)))
        days[cell].add(d)
        pts[cell].append((r["lat"], r["lon"]))
    if not days:
        return None
    best = max(days, key=lambda c: (len(days[c]), len(pts[c])))
    la = sum(p[0] for p in pts[best]) / len(pts[best])
    lo = sum(p[1] for p in pts[best]) / len(pts[best])
    return round(la, 5), round(lo, 5)


def home_of(conn: sqlite3.Connection, owner: str, rows) -> Optional[Dict]:
    r = conn.execute("SELECT lat, lon FROM homes WHERE owner = ?", (owner,)).fetchone()
    if r:
        lat, lon, source = r["lat"], r["lon"], "manual"
    else:
        h = auto_home(rows)
        if not h:
            return None
        (lat, lon), source = h, "auto"
    hit = geo.nearest(lat, lon)
    return {"lat": lat, "lon": lon, "source": source, "label": geo.label(hit[0], hit[1]) if hit else None}


def away_rows(rows, home: Optional[Dict]):
    if not home:
        return []
    out = [r for r in rows if _day(r) and km(home["lat"], home["lon"], r["lat"], r["lon"]) > AWAY_KM]
    out.sort(key=lambda r: (r["taken_at"], r["id"]))
    return out


def detect(away) -> List[Tuple[str, str]]:
    """Zeiträume (erster Tag, letzter Tag) aus den Fotos außerhalb von Zuhause."""
    groups: List[List] = []
    last = None
    for r in away:
        d = date.fromisoformat(_day(r))
        if last is None or (d - last).days > MAX_GAP_DAYS + 1:
            groups.append([])
        groups[-1].append(r)
        last = d
    return [(_day(g[0]), _day(g[-1])) for g in groups if len(g) >= MIN_PHOTOS]


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start <= b_end and b_start <= a_end


def sync(conn: sqlite3.Connection, owner: str, away) -> None:
    """Automatische Reisen neu berechnen; bearbeitete bleiben, wie sie sind."""
    found = detect(away)
    existing = conn.execute("SELECT * FROM trips WHERE owner = ?", (owner,)).fetchall()
    manual = [t for t in existing if not t["auto"]]
    autos = {t["start_day"]: t for t in existing if t["auto"]}
    keep = set()
    conn.execute("BEGIN")
    try:
        for start, end in found:
            if any(_overlaps(start, end, m["start_day"], m["end_day"]) for m in manual):
                continue
            old = autos.get(start)
            if old:
                keep.add(old["id"])
                if old["end_day"] != end:
                    conn.execute("UPDATE trips SET end_day = ? WHERE id = ?", (end, old["id"]))
            else:
                conn.execute("INSERT INTO trips(owner, start_day, end_day, auto, created_at) VALUES (?, ?, ?, 1, ?)",
                             (owner, start, end, now_utc_str()))
        for t in autos.values():
            if t["id"] not in keep:
                conn.execute("DELETE FROM trips WHERE id = ?", (t["id"],))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def members(trip, away) -> list:
    return [r for r in away if trip["start_day"] <= _day(r) <= trip["end_day"]]


def _month_range(start: str, end: str) -> str:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if (a.year, a.month) == (b.year, b.month):
        return f"{MONTHS[a.month - 1]} {a.year}"
    if a.year == b.year:
        return f"{MONTHS[a.month - 1]}–{MONTHS[b.month - 1]} {a.year}"
    return f"{MONTHS[a.month - 1]} {a.year} – {MONTHS[b.month - 1]} {b.year}"


def auto_title(trip, rows) -> str:
    """Ein Ort mit mindestens 75 % der Fotos → Ort („Hamburg“); sonst das Land („Island“); mehrere → „Italien & Österreich“."""
    when = _month_range(trip["start_day"], trip["end_day"])
    ccs = Counter(r["cc"] for r in rows if r["cc"])
    if not ccs:
        return f"Reise, {when}"
    if len(ccs) == 1:
        cc = next(iter(ccs))
        places = Counter(r["place"] for r in rows if r["place"])
        top = places.most_common(1)
        if top and top[0][1] >= 0.75 * len(rows):
            return f"{top[0][0]}, {when}"
        return f"{geo.country_name(cc)}, {when}"
    names = [geo.country_name(c) for c, _ in ccs.most_common()]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}, {when}"
    return f"{names[0]}, {names[1]} & {len(names) - 2} weitere, {when}"


def route(rows) -> List[Dict]:
    """Halte in zeitlicher Reihenfolge: aufeinanderfolgende Fotos innerhalb von STOP_KM werden zusammengefasst."""
    stops: List[Dict] = []
    for r in sorted(rows, key=lambda r: (r["taken_at"], r["id"])):
        if stops and km(stops[-1]["lat"], stops[-1]["lon"], r["lat"], r["lon"]) <= STOP_KM:
            s = stops[-1]
            s["n"] += 1
            s["_lat"] += r["lat"]
            s["_lon"] += r["lon"]
            s["lat"], s["lon"] = s["_lat"] / s["n"], s["_lon"] / s["n"]
            s["last"] = r["taken_at"]
            if r["place"]:
                s["_places"][(r["place"], r["cc"])] += 1
            continue
        places = Counter()
        if r["place"]:
            places[(r["place"], r["cc"])] += 1
        stops.append({"lat": r["lat"], "lon": r["lon"], "_lat": r["lat"], "_lon": r["lon"], "n": 1,
                      "first": r["taken_at"], "last": r["taken_at"], "_places": places, "cc": r["cc"]})
    out = []
    for s in stops:
        top = s["_places"].most_common(1)
        out.append({"lat": round(s["lat"], 5), "lon": round(s["lon"], 5), "count": s["n"], "first": s["first"],
                    "last": s["last"], "label": geo.label(*top[0][0]) if top else geo.country_name(s["cc"])})
    return out


def split_days(start: str, end: str) -> List[str]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
