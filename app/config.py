"""Konfiguration über Umgebungsvariablen.

Alle Werte haben sinnvolle Defaults, damit die App lokal ohne weitere
Einrichtung startet. Im Synology-Paket werden sie vom Start-Skript gesetzt.
"""
import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "ja", "on")


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("FG_DATA_DIR", "./data")).resolve()
        self.db_path = self.data_dir / "fotoglobus.db"
        self.timezone = os.environ.get("FG_TIMEZONE", "Europe/Berlin")
        # Öffentliche Adresse (Reverse Proxy); leer = aus dem Aufruf abgeleitet
        self.public_url = os.environ.get("FG_PUBLIC_URL", "").strip().rstrip("/")
        self.root_path = os.environ.get("FG_ROOT_PATH", "").rstrip("/")
        self.host = os.environ.get("FG_HOST", "0.0.0.0")
        self.port = int(os.environ.get("FG_PORT", "8790"))
        self.cookie_secure = _bool("FG_COOKIE_SECURE", False)
        self.session_days = int(os.environ.get("FG_SESSION_DAYS", "30"))
        # Ordner der DSM-Oberfläche (ui/), dort liegt app.json fürs DSM-Fenster
        self.ui_dir = os.environ.get("FG_UI_DIR", "")
        # Hintergrund-Aufgaben (nächtlicher Scan, Sicherung); in Tests aus
        self.scheduler = _bool("FG_SCHEDULER", True)
        self.update_check = _bool("FG_UPDATE_CHECK", True)
        self.initial_admin_password = os.environ.get("FG_ADMIN_PASSWORD")
        # Wurzel, unter der nach /volume*/photo und /volume*/homes gesucht wird (Tests: Testordner)
        self.volume_root = os.environ.get("FG_VOLUME_ROOT", "/")
        # Programm für die Rechteprüfung (DSM); in Tests ein Platzhalter
        self.acl_tool = os.environ.get("FG_ACL_TOOL", "/usr/syno/bin/synoacltool")


settings = Settings()

THEMES = {
    "classic": "Klassisch",
    "dsm": "Synology DSM",
    "dark": "Nacht (dunkel)",
    "warm": "Warm & groß",
}
