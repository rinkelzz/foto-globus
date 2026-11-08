"""SQLite-Datenbank: Schema, Migrationen (PRAGMA user_version) und Verbindung pro Request."""
import secrets
import sqlite3
from typing import Iterator

from .config import settings
from .timeutil import now_utc_str

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT,                       -- nur das lokale Admin-Konto; DSM-Konten haben keins
    is_admin      INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    is_dsm        INTEGER NOT NULL DEFAULT 0, -- 1 = DSM-Konto (sieht Fotos nach DSM-Rechten)
    theme         TEXT,
    created_at    TEXT NOT NULL,
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    dsm_user    TEXT                          -- bei DSM bestätigter Kontoname (Anmeldung mit DSM-Passwort)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    actor_id  INTEGER,
    action    TEXT NOT NULL,
    target    TEXT,
    details   TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS app_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Ein Eintrag pro Bilddatei (auch ohne GPS, damit sie beim nächsten Scan nicht neu gelesen wird)
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,         -- absoluter Pfad auf der NAS
    scope       TEXT NOT NULL,                -- personal | shared
    owner       TEXT,                         -- DSM-Benutzer bei personal
    folder      TEXT NOT NULL,                -- Ordner (absolut), für die Rechteprüfung
    name        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime       INTEGER NOT NULL,
    kind        TEXT,                         -- jpeg | heif | png | tiff
    taken_at    TEXT,                         -- ISO, Ortszeit der Kamera (ggf. mit Offset)
    year        INTEGER,
    lat         REAL,
    lon         REAL,
    alt         REAL,
    make        TEXT,
    model       TEXT,
    width       INTEGER,
    height      INTEGER,
    orientation INTEGER,
    seen_scan   INTEGER NOT NULL DEFAULT 0,
    added_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_photos_geo ON photos(scope, owner) WHERE lat IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos(folder);

CREATE TABLE IF NOT EXISTS scan_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    status         TEXT NOT NULL DEFAULT 'läuft',   -- läuft | fertig | abgebrochen | fehler
    trigger        TEXT,                            -- nacht | manuell | start
    files_seen     INTEGER NOT NULL DEFAULT 0,
    files_new      INTEGER NOT NULL DEFAULT 0,
    files_changed  INTEGER NOT NULL DEFAULT 0,
    files_removed  INTEGER NOT NULL DEFAULT 0,
    with_gps       INTEGER NOT NULL DEFAULT 0,
    errors         INTEGER NOT NULL DEFAULT 0,
    error_text     TEXT
);
"""

DEFAULT_SETTINGS = {
    "public_url": "",
    # Anmeldung mit DSM-Konten
    "dsm_login": "1",
    "dsm_auto_create": "1",
    "dsm_admins": "1",
    "dsm_url": "http://127.0.0.1:5000",
    # Fotoordner – leer = automatisch (/volume*/photo und /volume*/homes)
    "shared_root": "",
    "homes_root": "",
    "scan_shared": "1",
    "scan_personal": "1",
    # Nächtlicher Scan
    "scan_enabled": "1",
    "scan_hour": "3",
    # Gemeinsame Fotos: acl = nach den Ordnerrechten in DSM, all = alle angemeldeten DSM-Benutzer
    "share_access": "acl",
    # Karte
    "map_style": "https://tiles.openfreemap.org/styles/liberty",
    # Datensicherung
    "backup_enabled": "1",
    "backup_hour": "2",
    "backup_keep_days": "30",
    "backup_dir": "",
    # Darstellung
    "theme_default": "classic",
    "company_name": "",
}


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection) -> None:
    """Bringt ältere Datenbanken schrittweise auf den aktuellen Stand (Daten bleiben erhalten).

    Neue Schritte immer unten anhängen: if version < N: …
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        pass  # Ausgangsschema (0.1.0) – steht vollständig in SCHEMA
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def connect() -> sqlite3.Connection:
    # Autocommit, check_same_thread=False: siehe Zeiterfassung – eine Verbindung gehört einem Request.
    conn = sqlite3.connect(str(settings.db_path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Legt Datenordner, Schema und (beim ersten Start) den lokalen Admin an."""
    from .security import hash_password

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        migrate(conn)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO app_settings(key, value) VALUES (?, ?)", (key, value))
        # Ein beim Stromausfall „laufender“ Scan ist vorbei
        conn.execute("UPDATE scan_runs SET status = 'abgebrochen', finished_at = ? WHERE status = 'läuft'",
                     (now_utc_str(),))
        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            password = settings.initial_admin_password or secrets.token_urlsafe(12)
            conn.execute(
                "INSERT INTO users(username, display_name, password_hash, is_admin, created_at) "
                "VALUES ('admin', 'Administrator', ?, 1, ?)",
                (hash_password(password), now_utc_str()),
            )
            if not settings.initial_admin_password:
                cred = settings.data_dir / "ERSTES_ADMIN_PASSWORT.txt"
                cred.write_text("Benutzer: admin\nPasswort: " + password + "\n\n"
                                "Bitte nach dem ersten Login ändern und diese Datei löschen.\n", encoding="utf-8")
                print(f"[fotoglobus] Admin angelegt, Passwort steht in {cred}")
    finally:
        conn.close()


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO app_settings(key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def audit(conn: sqlite3.Connection, actor_id, action: str, target: str = "", details: str = "") -> None:
    conn.execute("INSERT INTO audit_log(ts, actor_id, action, target, details) VALUES (?, ?, ?, ?, ?)",
                 (now_utc_str(), actor_id, action, target, (details or "")[:1000]))
