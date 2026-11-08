"""Scan der Fotoordner, Rechte nach DSM, Punkte/Details/Vorschauen über die API."""
import os
import shutil
import stat
import time

import pytest
from fastapi.testclient import TestClient

from app import access, dsm_auth, scanner
from app.config import settings
from app.db import connect
from app.main import app

from .photofiles import TINY_JPEG, make_heic, make_jpeg, make_png, synology_thumb, write

VOL = os.path.join(settings.volume_root, "volume1")
PHOTO = os.path.join(VOL, "photo")
HOMES = os.path.join(VOL, "homes")


def sso(user, admin=False):
    return {"X-FG-Proxy-Secret": dsm_auth.proxy_secret(), "X-FG-Proxy-Base": "app.cgi",
            "X-DSM-User": user, "X-DSM-Admin": "1" if admin else "0"}


@pytest.fixture()
def acl(tmp_path, monkeypatch):
    """Ersatz für synoacltool: verboten ist, was in deny.txt steht („<ordner> <benutzer>“)."""
    deny = tmp_path / "deny.txt"
    deny.write_text("")
    tool = tmp_path / "synoacltool"
    tool.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "-get-perm" ] || exit 2\n'
        f'if grep -qxF "$2 $3" "{deny}"; then\n'
        '  echo "Final permission: [-------------] (deny)"\n'
        "else\n"
        '  echo "ACL version: 1"; echo "Final permission: [r-x---a-R-c--] (allow)"\n'
        "fi\n")
    tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(settings, "acl_tool", str(tool))
    access.clear_cache()
    yield deny
    access.clear_cache()


@pytest.fixture()
def library():
    shutil.rmtree(VOL, ignore_errors=True)
    files = {
        "mallorca": write(f"{PHOTO}/Urlaub/Mallorca/IMG_1.jpg", make_jpeg(lat=39.57, lon=2.65)),
        "rio": write(f"{PHOTO}/Urlaub/Rio/IMG_2.heic", make_heic(lat=-22.95, lon=-43.21, taken="2019:03:01 10:00:00")),
        "geheim": write(f"{PHOTO}/Familie/geheim/IMG_3.jpg", make_jpeg(lat=52.52, lon=13.40)),
        "nogps": write(f"{PHOTO}/Scans/scan.jpg", make_jpeg(lat=None)),
        "anna": write(f"{HOMES}/anna/Photos/2023/anna.png", make_png(lat=48.86, lon=2.35)),
        "ben": write(f"{HOMES}/ben/Photos/ben.jpg", make_jpeg(lat=40.71, lon=-74.0)),
        "skip": write(f"{PHOTO}/@eaDir/IMG_1.jpg/SYNOFOTO_THUMB_M.jpg", make_jpeg(lat=1, lon=1)),
        "txt": write(f"{PHOTO}/Urlaub/notiz.txt", b"hallo"),
    }
    os.makedirs(f"{HOMES}/@DH-DOMAIN", exist_ok=True)
    with connect() as conn:
        conn.execute("DELETE FROM photos")
        conn.execute("DELETE FROM scan_runs")
    yield files
    shutil.rmtree(VOL, ignore_errors=True)


def _count(where="1=1"):
    with connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM photos WHERE {where}").fetchone()[0]


def test_scan_finds_photos_and_is_incremental(library):
    r = scanner.run("manuell")
    assert r["status"] == "fertig" and r["files_seen"] == 6 and r["files_new"] == 6 and r["with_gps"] == 5
    assert _count("scope = 'personal'") == 2 and _count("owner = 'anna'") == 1
    assert _count("path LIKE '%@eaDir%'") == 0
    with connect() as conn:
        rio = conn.execute("SELECT * FROM photos WHERE name = 'IMG_2.heic'").fetchone()
        assert rio["year"] == 2019 and rio["kind"] == "heif" and rio["lat"] < 0

    # zweiter Lauf: nichts Neues
    r = scanner.run("manuell")
    assert (r["files_new"], r["files_changed"], r["files_removed"]) == (0, 0, 0)

    # geändert, gelöscht, neu
    write(library["mallorca"], make_jpeg(lat=39.6, lon=2.7), mtime=int(time.time()) + 100)
    os.remove(library["ben"])
    write(f"{PHOTO}/Urlaub/Neu/IMG_9.jpg", make_jpeg(lat=10, lon=10))
    r = scanner.run("manuell")
    assert (r["files_new"], r["files_changed"], r["files_removed"]) == (1, 1, 1)


def test_missing_volume_keeps_index(library):
    scanner.run("manuell")
    before = _count()
    os.rename(PHOTO, PHOTO + "_weg")
    try:
        with connect() as conn:  # Ordner fest eingestellt, aber gerade nicht da (z. B. Volume ausgehängt)
            conn.execute("UPDATE app_settings SET value = ? WHERE key = 'shared_root'", (PHOTO,))
        r = scanner.run("manuell")
        assert r["errors"] >= 1 and _count() == before
    finally:
        os.rename(PHOTO + "_weg", PHOTO)
        with connect() as conn:
            conn.execute("UPDATE app_settings SET value = '' WHERE key = 'shared_root'")


def test_removed_user_home_disappears(library):
    scanner.run("manuell")
    shutil.rmtree(f"{HOMES}/ben")
    scanner.run("manuell")
    assert _count("owner = 'ben'") == 0 and _count("owner = 'anna'") == 1


def test_visibility_follows_owner_and_acl(library, acl):
    scanner.run("manuell")
    acl.write_text(f"{PHOTO}/Familie/geheim anna\n")
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        pts = c.get("/api/v1/points", headers=sso("anna")).json()
        names = {p["name"] for p in c.post("/api/v1/photos/info", json={"ids": [p[0] for p in pts["points"]]},
                                            headers=sso("anna")).json()}
        assert names == {"IMG_1.jpg", "IMG_2.heic", "anna.png"}
        assert pts["without_gps"] == 1 and set(pts["years"]) >= {2019, 2024}
        assert {p[4] for p in pts["points"]} == {"s", "p"}

        ben = c.get("/api/v1/points", headers=sso("ben")).json()
        assert ben["count"] == 4  # alle gemeinsamen + eigenes, nicht das von anna

        # fremdes Foto direkt abrufen → 404 (nicht 403, damit nichts über die Existenz verraten wird)
        with connect() as conn:
            ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM photos")}
        assert c.get(f"/api/v1/photos/{ids['IMG_3.jpg']}/original", headers=sso("anna")).status_code == 404
        assert c.get(f"/api/v1/photos/{ids['ben.jpg']}/thumb/m", headers=sso("anna")).status_code == 404
        assert c.post("/api/v1/photos/info", json={"ids": [ids["ben.jpg"]]}, headers=sso("anna")).json() == []
        r = c.get(f"/api/v1/photos/{ids['anna.png']}/original", headers=sso("anna"))
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
        assert "anna.png" in r.headers["content-disposition"]

        # Zeitfilter
        only19 = c.get("/api/v1/points", params={"year_from": 2019, "year_to": 2019}, headers=sso("anna")).json()
        assert only19["count"] == 1


def test_parent_folder_denies_children(library, acl):
    scanner.run("manuell")
    acl.write_text(f"{PHOTO}/Urlaub anna\n")
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        n = c.get("/api/v1/points", headers=sso("anna")).json()["count"]
        assert n == 2  # Familie/geheim + eigenes; Urlaub/* fehlt


def test_unknown_acl_output_means_no_access(library, tmp_path, monkeypatch):
    scanner.run("manuell")
    tool = tmp_path / "komisch"
    tool.write_text("#!/bin/sh\necho 'irgendwas Unerwartetes'\n")
    tool.chmod(0o755)
    monkeypatch.setattr(settings, "acl_tool", str(tool))
    access.clear_cache()
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        assert c.get("/api/v1/points", headers=sso("anna")).json()["count"] == 1  # nur das eigene
    access.clear_cache()


def test_share_access_all(library, acl):
    scanner.run("manuell")
    acl.write_text(f"{PHOTO}/Familie/geheim anna\n")
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["FG_ADMIN_PASSWORD"]})
        assert c.patch("/api/v1/settings", json={"share_access": "all"}).status_code == 200
        try:
            assert c.get("/api/v1/points", headers=sso("anna")).json()["count"] == 4
        finally:
            c.patch("/api/v1/settings", json={"share_access": "acl"})


def test_local_admin_sees_no_photos_but_can_scan(library, acl):
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["FG_ADMIN_PASSWORD"]})
        assert c.get("/api/v1/points").status_code == 403
        assert c.post("/api/v1/scan").status_code == 200
        for _ in range(100):
            st = c.get("/api/v1/scan").json()
            if not st["running"]:
                break
            time.sleep(0.05)
        assert st["runs"][0]["status"] == "fertig" and st["totals"]["with_gps"] == 5
        s = c.get("/api/v1/settings").json()
        assert s["detected"]["shared_root"] == PHOTO and {r["owner"] for r in s["roots"] if r["owner"]} == {"anna", "ben"}
        t = c.get("/api/v1/access-test", params={"user": "anna", "folder": "Urlaub/Mallorca"}).json()
        assert t["allowed"] and len(t["chain"]) == 3 and "Final permission" in t["chain"][0]["output"]
        assert c.get("/api/v1/access-test", params={"user": "anna", "folder": "../../etc"}).status_code == 400
        # Pfade prüfen
        assert c.patch("/api/v1/settings", json={"shared_root": "/gibt/es/nicht"}).status_code == 400
        assert c.patch("/api/v1/settings", json={"map_style": "http://unsicher"}).status_code == 400
    # Normale DSM-Benutzer dürfen nicht verwalten
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        assert c.post("/api/v1/scan", headers=sso("anna")).status_code == 403
        assert c.get("/api/v1/settings", headers=sso("anna")).status_code == 403


def test_thumbnails(library, acl):
    synology_thumb(library["mallorca"], "SM", TINY_JPEG + b"sm")
    synology_thumb(library["mallorca"], "XL", TINY_JPEG + b"xl")
    write(library["rio"], make_heic(lat=-22.95, lon=-43.21, thumb=TINY_JPEG + b"exif"))
    scanner.run("manuell")
    with connect() as conn:
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM photos")}
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        h = sso("anna")
        assert c.get(f"/api/v1/photos/{ids['IMG_1.jpg']}/thumb/sm", headers=h).content.endswith(b"sm")
        assert c.get(f"/api/v1/photos/{ids['IMG_1.jpg']}/thumb/m", headers=h).content.endswith(b"sm")   # Ersatzgröße
        assert c.get(f"/api/v1/photos/{ids['IMG_1.jpg']}/thumb/xl", headers=h).content.endswith(b"xl")
        assert c.get(f"/api/v1/photos/{ids['IMG_2.heic']}/thumb/m", headers=h).content.endswith(b"exif")  # aus Exif
        assert c.get(f"/api/v1/photos/{ids['IMG_2.heic']}/thumb/xl", headers=h).content.endswith(b"exif")
        assert c.get(f"/api/v1/photos/{ids['IMG_1.jpg']}/thumb/riesig", headers=h).status_code == 404


def test_parse_perm():
    assert access.parse_perm("Final permission: [rwxpdDaARWcCo] (allow)") is True
    assert access.parse_perm("Final permission: [-wxpdDaARWcCo]") is False
    assert access.parse_perm("[0] user:anna:allow:rwxpdDaARWc--:fd--\nFinal permission: [-------------]") is False
    assert access.parse_perm("Linux mode: r-x") is True
    assert access.parse_perm("") is None and access.parse_perm("Fehler") is None


def test_readable_folders_checks_each_level_once():
    calls = []

    def check(folder, user):
        calls.append(folder)
        return not folder.endswith("/b")

    got = access.readable_folders(["/r/a/x", "/r/a/y", "/r/b/z", "/r"], "/r", "u", check=check)
    assert got == {"/r/a/x", "/r/a/y", "/r"}
    assert sorted(calls) == sorted(["/r", "/r/a", "/r/b", "/r/a/x", "/r/a/y"])  # /r/b/z gar nicht erst gefragt


def test_port_setting_writes_config_env():
    from app.routers.admin import CONFIG_ENV
    path = settings.data_dir / CONFIG_ENV
    path.write_text('# Kommentar\nFG_PORT=8790\nFG_PUBLIC_URL=""\n', encoding="utf-8")
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["FG_ADMIN_PASSWORD"]})
        r = c.patch("/api/v1/settings", json={"port": 8899})
        assert r.status_code == 200 and r.json()["port_configured"] == 8899 and r.json()["port"] == settings.port
        assert path.read_text() == '# Kommentar\nFG_PORT=8899\nFG_PUBLIC_URL=""\n'
        assert c.patch("/api/v1/settings", json={"port": 80}).status_code == 422
    path.unlink()


def test_symlinks_are_never_served(library, acl):
    """Wer Schreibrechte in einem Fotoordner hat, kann per Link keine fremden Dateien abgreifen."""
    scanner.run("manuell")
    with connect() as conn:
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM photos")}
    # ben legt in seinem Ordner eine „Vorschau“ an, die auf annas privates Foto zeigt
    ben_photo = library["ben"]
    eadir = os.path.join(os.path.dirname(ben_photo), "@eaDir", os.path.basename(ben_photo))
    os.makedirs(eadir)
    os.symlink(library["anna"], os.path.join(eadir, "SYNOFOTO_THUMB_M.jpg"))
    # und tauscht sein Foto nachträglich gegen einen Link auf annas Foto
    os.remove(ben_photo)
    os.symlink(library["anna"], ben_photo)
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        h = sso("ben")
        assert c.get(f"/api/v1/photos/{ids['ben.jpg']}/thumb/m", headers=h).status_code == 404
        assert c.get(f"/api/v1/photos/{ids['ben.jpg']}/original", headers=h).status_code == 404
    # neuer Scan: Links werden gar nicht erst aufgenommen
    scanner.run("manuell")
    assert _count("owner = 'ben'") == 0
    # auch direkt beim Lesen wird keinem Link gefolgt
    from app import exif
    with pytest.raises(OSError):
        exif.read_photo(ben_photo)
