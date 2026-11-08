"""Passwörter und Sessions – nur Standardbibliothek.

Wichtig für die Fotos: Welche Bilder jemand sieht, hängt am **DSM-Konto**, das DSM selbst bestätigt hat –
entweder per Single Sign-on im DSM-Fenster (app.cgi) oder per Anmeldung mit dem DSM-Passwort.
Das lokale Admin-Konto der App sieht keine Fotos, es ist nur für die Einrichtung da.
"""
import hashlib
import hmac
import secrets
import sqlite3
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from .config import settings
from .db import get_db
from .timeutil import now_utc, now_utc_str, to_utc_str

SESSION_COOKIE = "fg_session"
SESSION_HEADER = "x-session-token"  # für das DSM-Fenster (iframe), wo Browser Cookies oft blocken
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        _algo, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except ValueError:
        return False


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int, dsm_user: Optional[str] = None) -> str:
    token = secrets.token_urlsafe(32)
    expires = now_utc() + timedelta(days=settings.session_days)
    conn.execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, dsm_user) VALUES (?, ?, ?, ?, ?)",
        (_sha256(token), user_id, now_utc_str(), to_utc_str(expires), dsm_user),
    )
    return token


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_sha256(token),))


def _session(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT u.*, s.dsm_user AS session_dsm_user FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1",
        (_sha256(token), now_utc_str()),
    ).fetchone()


def current_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row:
    """Login per DSM-Fenster (Single Sign-on) oder Session (Cookie / X-Session-Token).

    Setzt request.state.dsm_user auf das von DSM bestätigte Konto (oder None)."""
    from .dsm_auth import dsm_user_row, proxy_info  # spät importiert, vermeidet Zyklus
    request.state.via_dsm = False
    request.state.dsm_user = None
    proxied = proxy_info(request)
    if proxied and proxied["user"]:
        user, error = dsm_user_row(conn, proxied["user"], proxied["admin"])
        if not user:
            raise HTTPException(status.HTTP_403_FORBIDDEN, error)
        request.state.via_dsm = True
        request.state.dsm_user = proxied["user"]
        return user
    token = request.headers.get(SESSION_HEADER) or request.cookies.get(SESSION_COOKIE)
    user = _session(conn, token) if token else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    dsm = user["session_dsm_user"]
    if dsm and user["is_dsm"] and dsm.lower() == user["username"].lower():
        request.state.dsm_user = dsm
    return user


def admin_user(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    if not user["is_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur für Administratoren")
    return user


def photo_user(request: Request, user: sqlite3.Row = Depends(current_user)) -> str:
    """Das DSM-Konto, nach dessen Rechten Fotos gezeigt werden."""
    dsm = getattr(request.state, "dsm_user", None)
    if not dsm:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Fotos sieht man nur mit einem DSM-Konto. Bitte mit dem DSM-Benutzer anmelden.")
    return dsm
