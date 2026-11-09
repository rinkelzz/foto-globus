"""Fotoordner durchsuchen und Aufnahmeorte in die Datenbank schreiben.

- Gemeinsame Fotos: /volumeX/photo (Synology Photos „Geteilter Bereich“)
- Persönliche Fotos: /volumeX/homes/<benutzer>/Photos (Synology Photos „Persönlicher Bereich“)

Beim zweiten Durchlauf werden nur neue oder geänderte Dateien (Größe/Änderungszeit) gelesen.
Verschwundene Dateien fliegen raus – aber nur, wenn ihr Ordner vollständig durchsucht werden konnte.
Ist ein Volume gerade nicht da, bleibt alles stehen.
"""
import glob
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from . import exif
from .config import settings
from .db import audit, connect, get_setting, set_setting
from .timeutil import now_utc, now_utc_str, to_local

SKIP_PREFIXES = ("@", "#", ".")      # @eaDir, @Recycle, #recycle, #snapshot, .versteckt
BATCH = 400

_lock = threading.Lock()
_cancel = threading.Event()
_state: Dict = {"running": False, "run_id": None, "root": None, "done": 0, "started": None}


class Root:
    def __init__(self, scope: str, path: str, owner: Optional[str] = None):
        self.scope, self.path, self.owner = scope, path.rstrip("/"), owner

    def __repr__(self) -> str:  # für Tests/Logs
        return f"Root({self.scope}, {self.path}, {self.owner})"


def _vol(pattern: str) -> List[str]:
    base = settings.volume_root.rstrip("/")
    return sorted(p for p in glob.glob(base + pattern) if os.path.isdir(p))


def shared_root(conn: sqlite3.Connection) -> Optional[str]:
    configured = (get_setting(conn, "shared_root") or "").strip()
    if configured:
        return configured.rstrip("/")
    found = _vol("/volume*/photo")
    return found[0] if found else None


def homes_root(conn: sqlite3.Connection) -> Optional[str]:
    configured = (get_setting(conn, "homes_root") or "").strip()
    if configured:
        return configured.rstrip("/")
    found = _vol("/volume*/homes")
    return found[0] if found else None


def roots(conn: sqlite3.Connection) -> List[Root]:
    out = []
    if get_setting(conn, "scan_shared") == "1":
        s = shared_root(conn)
        if s:
            out.append(Root("shared", s))
    if get_setting(conn, "scan_personal") == "1":
        h = homes_root(conn)
        if h:
            try:
                names = sorted(os.listdir(h))
            except OSError:
                names = []
            for name in names:
                if name.startswith(SKIP_PREFIXES):
                    continue
                p = os.path.join(h, name, "Photos")
                if os.path.isdir(p):
                    out.append(Root("personal", p, owner=name))
    return out


def _walk(top: str, errors: List[str]):
    """Alle Bilddateien unter top: (ordner, name, size, mtime). Fehler landen in errors."""
    stack = [top]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError as e:
            errors.append(f"{d}: {e.strerror or e}")
            if d == top:
                raise
            continue
        for ent in entries:
            if ent.name.startswith(SKIP_PREFIXES):
                continue
            try:
                if ent.is_dir(follow_symlinks=False):
                    stack.append(ent.path)
                elif ent.is_file(follow_symlinks=False):
                    if os.path.splitext(ent.name)[1].lower() in exif.MEDIA_EXTS:
                        st = ent.stat(follow_symlinks=False)
                        yield d, ent.name, st.st_size, int(st.st_mtime)
            except OSError as e:
                errors.append(f"{ent.path}: {e.strerror or e}")


def _year_of(taken: Optional[str], mtime: int) -> int:
    if taken and taken[:4].isdigit():
        return int(taken[:4])
    return datetime.fromtimestamp(mtime).year


def _scan_root(conn: sqlite3.Connection, root: Root, run_id: int, stats: Dict, errors: List[str]) -> bool:
    """Einen Ordner durchsuchen. True, wenn er vollständig gelesen werden konnte."""
    known: Dict[str, Tuple[int, int, int]] = {}
    for r in conn.execute("SELECT id, path, size, mtime FROM photos WHERE path >= ? AND path < ?",
                          (root.path + "/", root.path + "0")):
        known[r["path"]] = (r["id"], r["size"], r["mtime"])
    seen_ids: List[int] = []
    pending = 0
    conn.execute("BEGIN")
    try:
        for folder, name, size, mtime in _walk(root.path, errors):
            if _cancel.is_set():
                conn.execute("COMMIT")
                return False
            path = os.path.join(folder, name)
            stats["files_seen"] += 1
            _state["done"] = stats["files_seen"]
            old = known.get(path)
            if old and old[1] == size and old[2] == mtime:
                seen_ids.append(old[0])
            else:
                try:
                    info = exif.read_media(path)
                except OSError as e:
                    errors.append(f"{path}: {e.strerror or e}")
                    if old:
                        seen_ids.append(old[0])  # lieber alten Stand behalten
                    continue
                taken = info.get("taken_at")
                vals = (root.scope, root.owner, folder, name, size, mtime, info.get("kind"), taken,
                        _year_of(taken, mtime), info.get("lat"), info.get("lon"), info.get("alt"),
                        info.get("make"), info.get("model"), info.get("width"), info.get("height"),
                        info.get("orientation"), info.get("media", "photo"), info.get("duration"), run_id)
                if old:
                    conn.execute(
                        "UPDATE photos SET scope=?, owner=?, folder=?, name=?, size=?, mtime=?, kind=?, taken_at=?, year=?,"
                        " lat=?, lon=?, alt=?, make=?, model=?, width=?, height=?, orientation=?, media=?, duration=?,"
                        " seen_scan=?, place=NULL, cc=NULL, geocoded=0, hash=NULL WHERE id=?",
                        vals + (old[0],))
                    stats["files_changed"] += 1
                else:
                    conn.execute(
                        "INSERT INTO photos(scope, owner, folder, name, size, mtime, kind, taken_at, year, lat, lon, alt,"
                        " make, model, width, height, orientation, media, duration, seen_scan, path, added_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        vals + (path, now_utc_str()))
                    stats["files_new"] += 1
                pending += 1
            if pending >= BATCH:
                conn.execute("COMMIT")
                conn.execute("BEGIN")
                pending = 0
        # gesehen markieren (in Blöcken, SQLite kennt max. 999 Parameter auf alten Versionen)
        for i in range(0, len(seen_ids), 500):
            chunk = seen_ids[i:i + 500]
            conn.execute(f"UPDATE photos SET seen_scan = ? WHERE id IN ({','.join('?' * len(chunk))})",
                         [run_id] + chunk)
        removed = conn.execute("DELETE FROM photos WHERE path >= ? AND path < ? AND seen_scan != ?",
                               (root.path + "/", root.path + "0", run_id)).rowcount
        stats["files_removed"] += removed
        conn.execute("COMMIT")
        return True
    except OSError as e:
        conn.execute("ROLLBACK")
        errors.append(f"{root.path}: {e.strerror or e}")
        return False
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _forget_vanished_roots(conn: sqlite3.Connection, current: List[Root]) -> int:
    """Persönliche Bereiche, die es nicht mehr gibt (Benutzer gelöscht), und abgeschaltete Bereiche entfernen."""
    removed = 0
    home = homes_root(conn)
    if get_setting(conn, "scan_personal") != "1":
        removed += conn.execute("DELETE FROM photos WHERE scope = 'personal'").rowcount
    elif home and os.path.isdir(home):
        keep = {r.owner for r in current if r.scope == "personal"}
        for row in conn.execute("SELECT DISTINCT owner FROM photos WHERE scope = 'personal'").fetchall():
            if row["owner"] not in keep and not os.path.isdir(os.path.join(home, row["owner"] or "", "Photos")):
                removed += conn.execute("DELETE FROM photos WHERE scope = 'personal' AND owner = ?",
                                        (row["owner"],)).rowcount
    if get_setting(conn, "scan_shared") != "1":
        removed += conn.execute("DELETE FROM photos WHERE scope = 'shared'").rowcount
    else:
        s = shared_root(conn)
        if s:  # anderer Ordner eingestellt → alte Einträge weg
            removed += conn.execute("DELETE FROM photos WHERE scope = 'shared' AND NOT (path >= ? AND path < ?)",
                                    (s + "/", s + "0")).rowcount
    return removed


def run(trigger: str = "manuell", actor_id: Optional[int] = None, _locked: bool = False) -> Optional[Dict]:
    """Kompletter Scan. Liefert die Zusammenfassung – oder None, wenn schon einer läuft."""
    if not _locked and not _lock.acquire(blocking=False):
        return None
    _cancel.clear()
    conn = connect()
    try:
        run_id = conn.execute("INSERT INTO scan_runs(started_at, trigger) VALUES (?, ?)",
                              (now_utc_str(), trigger)).lastrowid
        _state.update(running=True, run_id=run_id, done=0, started=time.time(), root=None)
        stats = {"files_seen": 0, "files_new": 0, "files_changed": 0, "files_removed": 0}
        errors: List[str] = []
        status = "fertig"
        all_roots = roots(conn)
        if not all_roots:
            errors.append("Keine Fotoordner gefunden (photo bzw. homes/<benutzer>/Photos). "
                          "Pfade und Berechtigungen in den Einstellungen prüfen.")
        try:
            for root in all_roots:
                _state["root"] = root.path
                if not _scan_root(conn, root, run_id, stats, errors) and _cancel.is_set():
                    status = "abgebrochen"
                    break
            if status == "fertig":
                stats["files_removed"] += _forget_vanished_roots(conn, all_roots)
                _state["root"] = "Ortsnamen"
                geocode_pending(conn)
                _state["root"] = "Doppelte Fotos"
                hash_candidates(conn, errors)
        except Exception as e:  # noqa: BLE001 – Scan-Fehler dürfen die App nicht stören
            status = "fehler"
            errors.append(f"{type(e).__name__}: {e}")
        with_gps = conn.execute("SELECT COUNT(*) FROM photos WHERE lat IS NOT NULL").fetchone()[0]
        conn.execute(
            "UPDATE scan_runs SET finished_at=?, status=?, files_seen=?, files_new=?, files_changed=?, files_removed=?,"
            " with_gps=?, errors=?, error_text=? WHERE id=?",
            (now_utc_str(), status, stats["files_seen"], stats["files_new"], stats["files_changed"],
             stats["files_removed"], with_gps, len(errors), "\n".join(errors[:50])[:8000] or None, run_id))
        audit(conn, actor_id, "scan", f"scan:{run_id}",
              f"{trigger}: {status}, {stats['files_seen']} Dateien, {stats['files_new']} neu, "
              f"{stats['files_changed']} geändert, {stats['files_removed']} entfernt, {len(errors)} Fehler")
        if trigger in ("nacht", "start"):
            set_setting(conn, "scan_last_auto", to_local(now_utc()).isoformat(timespec="minutes"))
        from . import access
        access.clear_cache()  # neue Ordner → Rechte neu ermitteln
        return last_run(conn)
    finally:
        conn.close()
        _state.update(running=False, root=None)
        _lock.release()


FULL_HASH_LIMIT = 64 * 1024 * 1024   # größere Dateien (Videos): Stichproben statt ganz lesen
SAMPLE = 1024 * 1024


def file_hash(path: str) -> str:
    """Prüfsumme für den Vergleich exakter Kopien. Bis 64 MB über die ganze Datei, darüber über Größe + Anfang,
    Mitte und Ende (je 1 MB) – zwei verschiedene Videos stimmen darin praktisch nie überein."""
    import hashlib
    h = hashlib.sha256()
    with exif.open_nofollow(path) as f:
        size = os.fstat(f.fileno()).st_size
        if size <= FULL_HASH_LIMIT:
            for chunk in iter(lambda: f.read(SAMPLE), b""):
                h.update(chunk)
            return "f" + h.hexdigest()[:40]
        h.update(str(size).encode())
        for off in (0, size // 2, size - SAMPLE):
            f.seek(off)
            h.update(f.read(SAMPLE))
        return "s" + h.hexdigest()[:40]


def hash_candidates(conn: sqlite3.Connection, errors: Optional[List[str]] = None) -> int:
    """Prüfsummen nur für Dateien, deren Größe mehrfach vorkommt – nur die können exakte Kopien sein."""
    rows = conn.execute(
        "SELECT id, path FROM photos WHERE hash IS NULL AND size IN "
        "(SELECT size FROM photos GROUP BY size HAVING COUNT(*) > 1) ORDER BY size").fetchall()
    done = 0
    for i in range(0, len(rows), 200):
        if _cancel.is_set():
            break
        updates = []
        for r in rows[i:i + 200]:
            try:
                updates.append((file_hash(r["path"]), r["id"]))
            except OSError as e:
                if errors is not None:
                    errors.append(f"{r['path']}: {e.strerror or e}")
            _state["done"] = done + len(updates)
        conn.execute("BEGIN")
        conn.executemany("UPDATE photos SET hash = ? WHERE id = ?", updates)
        conn.execute("COMMIT")
        done += len(updates)
    return done


def duplicate_count(conn: sqlite3.Connection) -> int:
    """Wie viele Dateien sind überzählige Kopien (bei 3 gleichen Dateien: 2)?"""
    return conn.execute("SELECT COALESCE(SUM(c - 1), 0) FROM (SELECT COUNT(*) AS c FROM photos WHERE hash IS NOT NULL "
                        "GROUP BY size, hash HAVING c > 1)").fetchone()[0]


def geocode_pending(conn: sqlite3.Connection) -> int:
    """Ortsnamen für alle Fotos mit Koordinaten nachtragen, die noch keinen haben (offline, GeoNames)."""
    from . import geo
    done = 0
    try:
        while not _cancel.is_set():
            rows = conn.execute("SELECT id, lat, lon FROM photos WHERE geocoded = 0 AND lat IS NOT NULL LIMIT 2000").fetchall()
            if not rows:
                break
            conn.execute("BEGIN")
            for r in rows:
                hit = geo.nearest(r["lat"], r["lon"])
                place, cc = (hit[0], hit[1]) if hit else (None, None)
                conn.execute("UPDATE photos SET place = ?, cc = ?, geocoded = 1 WHERE id = ?", (place, cc, r["id"]))
            conn.execute("COMMIT")
            done += len(rows)
        # Fotos ohne Koordinaten brauchen keinen Ortsnamen
        conn.execute("UPDATE photos SET geocoded = 1 WHERE geocoded = 0 AND lat IS NULL")
    finally:
        geo.unload()  # Ortsliste nur während der Arbeit im Speicher halten
    return done


def geocode_due() -> None:
    """Nach einem Update: vorhandene Fotos bekommen Ortsnamen (0.2) und Prüfsummen für doppelte (0.5),
    ohne auf die nächste nächtliche Suche zu warten."""
    if _lock.locked():
        return
    conn = connect()
    try:
        pending = conn.execute("SELECT 1 FROM photos WHERE geocoded = 0 AND lat IS NOT NULL LIMIT 1").fetchone()
        unhashed = conn.execute("SELECT 1 FROM photos WHERE hash IS NULL AND size IN "
                                "(SELECT size FROM photos GROUP BY size HAVING COUNT(*) > 1) LIMIT 1").fetchone()
    finally:
        conn.close()
    if not (pending or unhashed) or not _lock.acquire(blocking=False):
        return
    _cancel.clear()
    conn = connect()
    try:
        _state.update(running=True, root="Ortsnamen", done=0, started=time.time())
        n = geocode_pending(conn) if pending else 0
        if n:
            audit(conn, None, "geocode", "scan", f"{n} Fotos mit Ortsnamen versehen")
        _state.update(root="Doppelte Fotos", done=0)
        h = hash_candidates(conn) if unhashed else 0
        if h:
            audit(conn, None, "duplicates", "scan", f"{h} Dateien geprüft, {duplicate_count(conn)} doppelt")
    finally:
        conn.close()
        _state.update(running=False, root=None)
        _lock.release()


def start_background(trigger: str = "manuell", actor_id: Optional[int] = None) -> bool:
    # Sperre und Status schon hier setzen: Fragt die Oberfläche direkt danach nach, soll sie „läuft“ sehen
    if not _lock.acquire(blocking=False):
        return False
    _state.update(running=True, done=0, started=time.time(), root=None)
    threading.Thread(target=run, args=(trigger, actor_id, True), name="scan", daemon=True).start()
    return True


def cancel() -> None:
    _cancel.set()


def status() -> Dict:
    return {"running": _state["running"], "files_done": _state["done"] if _state["running"] else None,
            "root": _state["root"],
            "seconds": int(time.time() - _state["started"]) if _state["running"] and _state["started"] else None}


def last_run(conn: sqlite3.Connection) -> Optional[Dict]:
    r = conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def due(conn: sqlite3.Connection, now_local: datetime) -> bool:
    if get_setting(conn, "scan_enabled") != "1":
        return False
    if not conn.execute("SELECT 1 FROM scan_runs LIMIT 1").fetchone():
        return True  # direkt nach der Installation einmal durchsuchen
    if now_local.hour < int(get_setting(conn, "scan_hour") or 3):
        return False
    return (get_setting(conn, "scan_last_auto") or "")[:10] != now_local.strftime("%Y-%m-%d")


def run_due() -> None:
    conn = connect()
    try:
        is_due = due(conn, to_local(now_utc()))
        first = not conn.execute("SELECT 1 FROM scan_runs LIMIT 1").fetchone()
    finally:
        conn.close()
    if is_due:
        run("start" if first else "nacht")
