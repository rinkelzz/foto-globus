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


def test_proxy_secret_file_only_for_package_user(tmp_path, monkeypatch):
    from app.config import settings
    ui = tmp_path / "ui"
    ui.mkdir()
    monkeypatch.setattr(settings, "ui_dir", str(ui))
    assert dsm_auth.publish_proxy_files()
    assert oct((tmp_path / ".proxy_secret").stat().st_mode & 0o777) == "0o600"
    assert oct((tmp_path / ".port").stat().st_mode & 0o777) == "0o644"


def test_csrf_ignores_forwarded_host():
    with TestClient(app) as c:
        _admin(c)
        r = c.patch("/api/v1/settings", json={"scan_hour": 4},
                    headers={"Origin": "https://boese.example.org", "X-Forwarded-Host": "boese.example.org"})
        assert r.status_code == 403


def test_defaults_bind_local_and_short_sessions():
    from app.config import Settings
    s = Settings()
    assert s.host == "127.0.0.1" and s.session_days == 7
    from app import access
    assert access.CACHE_SECONDS <= 5 * 60


def test_lan_access_setting_writes_config_env():
    from app.config import settings
    from app.routers.admin import CONFIG_ENV
    path = settings.data_dir / CONFIG_ENV
    path.write_text("FG_PORT=8790\n", encoding="utf-8")
    with TestClient(app) as c:
        _admin(c)
        assert c.get("/api/v1/settings").json()["lan_access_configured"] is False
        r = c.patch("/api/v1/settings", json={"lan_access": True}).json()
        assert r["lan_access_configured"] is True and "FG_HOST=0.0.0.0" in path.read_text()
        c.patch("/api/v1/settings", json={"lan_access": False})
        assert "FG_HOST=127.0.0.1" in path.read_text()
    path.unlink()


def test_backup_without_sessions_and_photo_index():
    import gzip
    import sqlite3
    import tempfile
    from app import backup
    from app.db import connect
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO photos(path, scope, owner, folder, name, size, mtime, lat, lon, added_at) "
                     "VALUES ('/x/homes/anna/Photos/geheim.jpg', 'personal', 'anna', '/x', 'geheim.jpg', 1, 1, 52.4, 10.5, 'x')")
    with TestClient(app) as c:
        _admin(c)
        name = c.post("/api/v1/backups").json()["name"]
        raw = c.get(f"/api/v1/backups/{name}/download").content
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            f.write(gzip.decompress(raw))
            f.flush()
            db = sqlite3.connect(f.name)
            assert db.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
            assert b"geheim.jpg" not in gzip.decompress(raw)
            db.close()
        # Wiederherstellen: man bleibt angemeldet, die Suche startet von selbst
        r = c.post(f"/api/v1/backups/{name}/restore", json={"confirm": name}).json()
        assert r["scan_started"] is True
        assert c.get("/api/v1/me").status_code == 200
    with connect() as conn:
        conn.execute("DELETE FROM photos WHERE name = 'geheim.jpg'")
