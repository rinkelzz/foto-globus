"""Verwaltung (nur Admins): Einstellungen, Scan, Rechte testen, Benutzer, Änderungsprotokoll."""
import os
import re
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import access, scanner
from ..config import THEMES, settings
from ..db import audit, get_db, get_setting, set_setting
from ..dsm import write_ui_config
from ..dsm_auth import local_dsm_url
from ..security import admin_user
from ..timeutil import local_iso

router = APIRouter(prefix="/api/v1", tags=["Verwaltung (Admin)"])

EDITABLE = ("public_url", "dsm_login", "dsm_auto_create", "dsm_admins", "dsm_url", "shared_root", "homes_root",
            "scan_shared", "scan_personal", "scan_enabled", "scan_hour", "share_access", "map_style", "theme_default",
            "satellite", "maptiler_key", "photos_url")


CONFIG_ENV = "config.env"  # liegt im Datenordner des Pakets (/var/packages/fotoglobus/var), liest das Start-Skript


def configured_port() -> int:
    """Port laut config.env (gilt nach dem nächsten Paket-Neustart) – sonst der laufende."""
    try:
        text = (settings.data_dir / CONFIG_ENV).read_text(encoding="utf-8")
    except OSError:
        return settings.port
    m = re.search(r'^FG_PORT="?(\d+)"?\s*$', text, re.M)
    return int(m.group(1)) if m else settings.port


def write_port(port: int) -> None:
    path = settings.data_dir / CONFIG_ENV
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = "# Foto-Globus – Einstellungen. Nach Änderungen das Paket neu starten.\n"
    if re.search(r"^FG_PORT=.*$", text, re.M):
        text = re.sub(r"^FG_PORT=.*$", f"FG_PORT={port}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\nFG_PORT={port}\n"
    tmp = path.with_name(CONFIG_ENV + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _settings_out(conn: sqlite3.Connection) -> dict:
    out = {k: get_setting(conn, k) for k in EDITABLE}
    out["port"] = settings.port
    out["port_configured"] = configured_port()
    out["detected"] = {"shared_root": scanner.shared_root(conn), "homes_root": scanner.homes_root(conn)}
    out["roots"] = [{"scope": r.scope, "path": r.path, "owner": r.owner} for r in scanner.roots(conn)]
    return out


@router.get("/settings")
def get_settings(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    return _settings_out(conn)


class SettingsIn(BaseModel):
    public_url: Optional[str] = Field(None, max_length=300)
    dsm_login: Optional[bool] = None
    dsm_auto_create: Optional[bool] = None
    dsm_admins: Optional[bool] = None
    dsm_url: Optional[str] = Field(None, max_length=100)
    shared_root: Optional[str] = Field(None, max_length=300)
    homes_root: Optional[str] = Field(None, max_length=300)
    scan_shared: Optional[bool] = None
    scan_personal: Optional[bool] = None
    scan_enabled: Optional[bool] = None
    scan_hour: Optional[int] = Field(None, ge=0, le=23)
    share_access: Optional[str] = Field(None, pattern="^(acl|all)$")
    map_style: Optional[str] = Field(None, max_length=300)
    theme_default: Optional[str] = None
    port: Optional[int] = Field(None, ge=1024, le=65535, description="gilt nach Neustart des Pakets")
    satellite: Optional[str] = Field(None, pattern="^(esri|maptiler|off)$")
    maptiler_key: Optional[str] = Field(None, max_length=64)
    photos_url: Optional[str] = Field(None, max_length=300)


def _check_dir(value: str, label: str) -> str:
    v = (value or "").strip().rstrip("/")
    if not v:
        return ""
    if not v.startswith("/") or ".." in v.split("/"):
        raise HTTPException(400, f"{label}: bitte einen vollständigen Pfad angeben, z. B. /volume1/photo")
    if not os.path.isdir(v):
        raise HTTPException(400, f"{label}: Ordner {v} nicht gefunden oder keine Leserechte für den Paketbenutzer")
    return v


@router.patch("/settings")
def update_settings(data: SettingsIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    changes = data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is None:
            continue
        if key == "port":
            if value != configured_port():
                try:
                    write_port(value)
                except OSError as e:
                    raise HTTPException(500, f"config.env nicht schreibbar: {e}")
            continue
        if isinstance(value, bool):
            value = "1" if value else "0"
        elif key in ("shared_root", "homes_root"):
            value = _check_dir(value, "Gemeinsame Fotos" if key == "shared_root" else "Benutzer-Ordner (homes)")
        elif key == "dsm_url":
            clean = local_dsm_url(value)
            if not clean:
                raise HTTPException(400, "DSM-Adresse muss auf die NAS selbst zeigen (127.0.0.1, localhost oder ::1)")
            value = clean
        elif key == "public_url":
            value = value.strip().rstrip("/")
            if value and not value.startswith(("http://", "https://")):
                raise HTTPException(400, "Öffentliche Adresse bitte mit http:// oder https:// angeben")
        elif key == "map_style":
            value = value.strip()
            if value and not value.startswith("https://"):
                raise HTTPException(400, "Kartenstil bitte als https-Adresse angeben (leer = Offline-Kugel)")
        elif key == "maptiler_key":
            value = value.strip()
            if value and not re.match(r"^[A-Za-z0-9_-]{8,64}$", value):
                raise HTTPException(400, "Der MapTiler-Schlüssel sieht nicht richtig aus (nur Buchstaben und Ziffern)")
        elif key == "photos_url":
            value = value.strip().rstrip("/")
            if value and not re.match(r"^https?://[^\s/]+(/[^\s]*)?$", value):
                raise HTTPException(400, "Adresse von Synology Photos bitte mit http:// oder https:// angeben")
        elif key == "theme_default" and value not in THEMES:
            raise HTTPException(400, "Unbekanntes Design")
        set_setting(conn, key, str(value))
    if changes:
        if "share_access" in changes or "shared_root" in changes:
            access.clear_cache()
        if "public_url" in changes:
            write_ui_config(conn)
        audit(conn, admin["id"], "settings_updated", "settings", ", ".join(sorted(changes)))
    return _settings_out(conn)


# --- Scan ---------------------------------------------------------------------------

def _scan_out(conn: sqlite3.Connection) -> dict:
    runs = [dict(r) for r in conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 10")]
    for r in runs:
        r["started_at"], r["finished_at"] = local_iso(r["started_at"]), local_iso(r["finished_at"])
    totals = conn.execute("SELECT COUNT(*) AS n, SUM(lat IS NOT NULL) AS gps, "
                          "SUM(scope = 'shared') AS shared, SUM(scope = 'personal') AS personal FROM photos").fetchone()
    return {**scanner.status(), "runs": runs,
            "totals": {"photos": totals["n"] or 0, "with_gps": totals["gps"] or 0,
                       "shared": totals["shared"] or 0, "personal": totals["personal"] or 0,
                       "duplicates": scanner.duplicate_count(conn)}}


@router.get("/scan")
def scan_status(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    return _scan_out(conn)


@router.post("/scan")
def scan_start(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    if not scanner.start_background("manuell", admin["id"]):
        raise HTTPException(409, "Es läuft bereits eine Suche")
    return {**_scan_out(conn), "running": True}


@router.delete("/scan")
def scan_cancel(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    scanner.cancel()
    audit(conn, admin["id"], "scan_cancelled", "scan")
    return _scan_out(conn)


# --- Rechte testen -----------------------------------------------------------------

@router.get("/access-test")
def access_test(user: str = Query(..., max_length=64), folder: str = Query("", max_length=500),
                admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    """Zeigt, was DSM zu den Rechten eines Benutzers auf einen Ordner sagt (inkl. Rohausgabe)."""
    root = scanner.shared_root(conn)
    if not root:
        raise HTTPException(400, "Kein Ordner für gemeinsame Fotos gefunden")
    target = os.path.normpath(os.path.join(root, folder.strip("/"))) if folder else root
    if not (target == root or target.startswith(root + "/")):
        raise HTTPException(400, "Ordner muss unterhalb der gemeinsamen Fotos liegen")
    access.clear_cache()
    chain = []
    allowed = True
    for c in access._chain(target, root):
        ok = access.can_read(c, user)
        chain.append({"folder": c, "read": ok, "output": access.last_output(c)})
        allowed = allowed and ok
    return {"user": user, "folder": target, "allowed": allowed, "mode": get_setting(conn, "share_access"), "chain": chain}


# --- Benutzer ------------------------------------------------------------------------

@router.get("/users")
def list_users(admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("SELECT id, username, display_name, is_admin, is_dsm, active, last_login, created_at "
                        "FROM users ORDER BY is_dsm, username COLLATE NOCASE").fetchall()
    return [{**dict(r), "is_admin": bool(r["is_admin"]), "is_dsm": bool(r["is_dsm"]), "active": bool(r["active"]),
             "last_login": local_iso(r["last_login"]), "created_at": local_iso(r["created_at"])} for r in rows]


class UserIn(BaseModel):
    is_admin: Optional[bool] = None
    active: Optional[bool] = None


@router.patch("/users/{user_id}")
def update_user(user_id: int, data: UserIn, admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Benutzer nicht gefunden")
    if row["id"] == admin["id"] and (data.is_admin is False or data.active is False):
        raise HTTPException(400, "Du kannst dir nicht selbst die Admin-Rechte nehmen oder dich sperren")
    if data.is_admin is False and row["is_admin"]:
        others = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND active = 1 AND id != ?", (user_id,)).fetchone()[0]
        if not others:
            raise HTTPException(400, "Es muss mindestens ein Admin bleiben")
    if data.is_admin is not None:
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(data.is_admin), user_id))
    if data.active is not None:
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (int(data.active), user_id))
        if not data.active:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    audit(conn, admin["id"], "user_updated", f"user:{user_id}",
          ", ".join(f"{k}={v}" for k, v in data.model_dump(exclude_unset=True).items()))
    return list_users(admin, conn)


# --- Änderungsprotokoll -----------------------------------------------------------------

@router.get("/audit")
def audit_log(limit: int = Query(200, ge=1, le=2000), admin=Depends(admin_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id ORDER BY a.id DESC LIMIT ?",
        (limit,)).fetchall()
    return [{"id": r["id"], "ts": local_iso(r["ts"]), "user": r["username"], "action": r["action"],
             "target": r["target"], "details": r["details"]} for r in rows]
