"""Reisen: Zuhause, Erkennung, Bearbeiten (Umbenennen, Teilen, Zusammenführen, Ausblenden), Route."""
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from app import dsm_auth, scanner
from app import trips as T
from app.config import settings
from app.db import connect
from app.main import app

from .photofiles import make_jpeg, write

VOL = os.path.join(settings.volume_root, "volume1")
HOME_DIR = os.path.join(VOL, "homes", "tom", "Photos")
HOME = (52.432, 10.583)  # bei Gifhorn


def sso(user="tom"):
    return {"X-FG-Proxy-Secret": dsm_auth.proxy_secret(), "X-FG-Proxy-Base": "app.cgi", "X-DSM-User": user, "X-DSM-Admin": "0"}


def shot(name, lat, lon, day, hour=12):
    write(f"{HOME_DIR}/{day[:4]}/{name}.jpg", make_jpeg(lat=lat, lon=lon, taken=f"{day.replace('-', ':')} {hour:02d}:00:00",
                                                       offset=None))


@pytest.fixture()
def library():
    shutil.rmtree(VOL, ignore_errors=True)
    # Zuhause: an vielen verschiedenen Tagen ein paar Fotos
    for i in range(1, 21):
        shot(f"home{i}", HOME[0] + (i % 3) * 0.01, HOME[1], f"2024-0{1 + i % 6}-{10 + i % 9:02d}")
    # Mallorca 3.–8. Juli 2024 (am 5. ein Tag ohne Fotos), viele Fotos
    for i, (d, lat, lon) in enumerate([("2024-07-03", 39.57, 2.65), ("2024-07-03", 39.571, 2.651), ("2024-07-04", 39.57, 2.65),
                                       ("2024-07-06", 39.71, 3.46), ("2024-07-07", 39.712, 3.462), ("2024-07-08", 39.57, 2.65)]):
        shot(f"mallorca{i}", lat, lon, d, 10 + i)
    # Island 10.–12. August 2024
    for i, d in enumerate(["2024-08-10", "2024-08-11", "2024-08-11", "2024-08-12"]):
        shot(f"island{i}", 64.14, -21.94, d, 9 + i)
    # Tagesausflug 60 km weit (Hannover) – keine Reise
    for i in range(4):
        shot(f"ausflug{i}", 52.37, 9.73, "2024-05-01", 10 + i)
    # Zwei Fotos in Paris – zu wenig für eine Reise
    shot("paris0", 48.86, 2.35, "2024-09-01")
    shot("paris1", 48.86, 2.35, "2024-09-02")
    with connect() as conn:
        for t in ("photos", "scan_runs", "trips", "homes"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("UPDATE app_settings SET value = 'all' WHERE key = 'share_access'")
    scanner.run("manuell")
    yield
    shutil.rmtree(VOL, ignore_errors=True)
    with connect() as conn:
        conn.execute("UPDATE app_settings SET value = 'acl' WHERE key = 'share_access'")


def _titles(c):
    return [(t["title"], t["start"], t["end"], t["count"]) for t in c.get("/api/v1/trips", headers=sso()).json()["trips"]]


def test_detect_trips_and_home(library):
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        r = c.get("/api/v1/trips", headers=sso()).json()
        assert r["home"]["source"] == "auto" and r["home"]["label"].endswith("Deutschland")
        assert abs(r["home"]["lat"] - HOME[0]) < 0.05
        assert _titles(c) == [("Reykjavík, August 2024", "2024-08-10", "2024-08-12", 4),
                              ("Spanien, Juli 2024", "2024-07-03", "2024-07-08", 6)]   # Palma nur 4 von 6 → Land
        mallorca = r["trips"][1]
        assert mallorca["days"] == 6 and mallorca["countries"] == [{"cc": "ES", "name": "Spanien"}]
        # Detail mit Route: Palma → Cala Ratjada → Palma
        d = c.get(f"/api/v1/trips/{mallorca['id']}", headers=sso()).json()
        assert [s["label"] for s in d["route"]] == ["Palma, Spanien", "Cala Rajada, Spanien", "Palma, Spanien"]
        assert d["route"][0]["count"] == 3 and len(d["ids"]) == 6 and d["prev"] is None and d["next"] == r["trips"][0]["id"]
        # andere sehen tom's Reisen nicht
        assert c.get(f"/api/v1/trips/{mallorca['id']}", headers=sso("eve")).status_code == 404
        assert c.get("/api/v1/trips", headers=sso("eve")).json()["trips"] == []


def test_edit_rename_hide_split_merge_and_survive_recompute(library):
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        h = sso()
        trips = c.get("/api/v1/trips", headers=h).json()["trips"]
        island, mallorca = trips[0]["id"], trips[1]["id"]
        # umbenennen
        r = c.patch(f"/api/v1/trips/{mallorca}", json={"title": "Sommer auf Malle"}, headers=h).json()
        assert r["title"] == "Sommer auf Malle" and r["renamed"] and r["auto_title"] == "Spanien, Juli 2024"
        # teilen am 6. Juli
        sp = c.post(f"/api/v1/trips/{mallorca}/split", json={"day": "2024-07-06"}, headers=h).json()
        assert c.post(f"/api/v1/trips/{mallorca}/split", json={"day": "2024-07-03"}, headers=h).status_code == 400
        titles = _titles(c)
        assert ("Sommer auf Malle", "2024-07-03", "2024-07-05", 3) in titles
        assert ("Spanien, Juli 2024", "2024-07-06", "2024-07-08", 3) in titles
        # neu scannen ändert nichts an bearbeiteten Reisen
        scanner.run("manuell")
        assert ("Sommer auf Malle", "2024-07-03", "2024-07-05", 3) in _titles(c)
        # wieder zusammenführen (nimmt den Namen der früheren)
        m = c.post(f"/api/v1/trips/{sp['second']}/merge", json={"other": mallorca}, headers=h).json()
        assert m["title"] == "Sommer auf Malle" and m["start"] == "2024-07-03" and m["end"] == "2024-07-08" and m["count"] == 6
        assert len(c.get("/api/v1/trips", headers=h).json()["trips"]) == 2
        # ausblenden
        c.patch(f"/api/v1/trips/{island}", json={"hidden": True}, headers=h)
        r = c.get("/api/v1/trips", headers=h).json()
        assert r["hidden"] == 1 and [t["hidden"] for t in r["trips"] if t["id"] == island] == [True]
        # Name zurück auf automatisch
        assert c.patch(f"/api/v1/trips/{m['id']}", json={"title": ""}, headers=h).json()["title"] == "Spanien, Juli 2024"
        # fremde Reisen kann man nicht bearbeiten
        assert c.patch(f"/api/v1/trips/{island}", json={"title": "x"}, headers=sso("eve")).status_code == 404
        assert c.post(f"/api/v1/trips/{island}/merge", json={"other": island}, headers=h).status_code == 400
        # alles zurücksetzen
        assert [t["title"] for t in c.post("/api/v1/trips/reset", headers=h).json()["trips"]] == \
            ["Reykjavík, August 2024", "Spanien, Juli 2024"]


def test_manual_home_changes_trips(library):
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        h = sso()
        # Zuhause nach Palma verlegt: Mallorca ist keine Reise mehr, dafür der Ausflug nach Hannover
        r = c.put("/api/v1/home", json={"lat": 39.57, "lon": 2.65}, headers=h).json()
        assert r["home"]["source"] == "manual" and r["home"]["label"] == "Palma, Spanien"
        assert all(t["start"] != "2024-07-03" for t in r["trips"])
        assert any(t["start"] == "2024-05-01" and t["title"] == "Hannover, Mai 2024" for t in r["trips"])
        assert c.put("/api/v1/home", json={}, headers=h).status_code == 400
        r = c.put("/api/v1/home", json={"auto": True}, headers=h).json()
        assert r["home"]["source"] == "auto" and len(r["trips"]) == 2


def test_detect_rules():
    def row(i, day, lat=40.0, lon=0.0):
        return {"id": i, "taken_at": f"{day}T12:00:00", "lat": lat, "lon": lon}
    away = [row(1, "2024-01-01"), row(2, "2024-01-01"), row(3, "2024-01-04"),   # 2 Tage Lücke → noch dieselbe Reise
            row(4, "2024-01-09"), row(5, "2024-01-09"), row(6, "2024-01-10")]   # 4 Tage Lücke → neue Reise
    assert T.detect(away) == [("2024-01-01", "2024-01-04"), ("2024-01-09", "2024-01-10")]
    assert T.detect(away[:2]) == []   # zu wenig Fotos
    assert T._month_range("2024-07-28", "2024-08-03") == "Juli–August 2024"
    assert T._month_range("2024-12-28", "2025-01-03") == "Dezember 2024 – Januar 2025"
