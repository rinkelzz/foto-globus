"""CSRF, Proxy-Schlüssel nur von der NAS selbst, Sicherheits-Header."""
import os

from fastapi.testclient import TestClient

from app import dsm_auth
from app.main import app


def _admin(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["FG_ADMIN_PASSWORD"]})
    assert r.status_code == 200
    return r


def test_csrf_cross_site_blocked():
    with TestClient(app) as c:
        _admin(c)
        r = c.patch("/api/v1/settings", json={"scan_hour": 4}, headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 403
        r = c.patch("/api/v1/settings", json={"scan_hour": 4}, headers={"Origin": "https://boese.example.org"})
        assert r.status_code == 403
        r = c.patch("/api/v1/settings", json={"scan_hour": 4}, headers={"Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 200
        c.patch("/api/v1/settings", json={"scan_hour": 3})


def test_proxy_secret_only_from_loopback():
    h = {"X-FG-Proxy-Secret": dsm_auth.proxy_secret(), "X-DSM-User": "eve", "X-DSM-Admin": "1"}
    with TestClient(app, client=("192.168.1.50", 40000)) as c:
        assert c.get("/api/v1/me", headers=h).status_code == 401
    with TestClient(app, client=("127.0.0.1", 40000)) as c:
        # über den Reverse Proxy weitergereicht (X-Forwarded-For) zählt der Schlüssel nicht
        assert c.get("/api/v1/me", headers={**h, "X-Forwarded-For": "8.8.8.8"}).status_code == 401
        assert c.get("/api/v1/me", headers={**h, "X-FG-Proxy-Secret": "falsch"}).status_code == 401
        assert c.get("/api/v1/me", headers=h).json()["dsm_user"] == "eve"


def test_security_headers_and_no_cache():
    with TestClient(app) as c:
        r = c.get("/api/v1/health")
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
        assert c.get("/").headers["cache-control"] == "no-cache"


def test_dsm_session_cannot_be_forged_by_local_account():
    """Ein lokales Konto mit dem Namen eines DSM-Benutzers sieht trotzdem keine Fotos."""
    from app.db import connect
    from app.security import hash_password
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO users(username, display_name, password_hash, is_admin, created_at) "
                     "VALUES ('lokal_anna', 'x', ?, 0, '2026-01-01T00:00:00+00:00')", (hash_password("geheim123"),))
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"username": "lokal_anna", "password": "geheim123"})
        assert r.status_code == 200
        assert c.get("/api/v1/me").json()["dsm_user"] is None
        assert c.get("/api/v1/points").status_code == 403
