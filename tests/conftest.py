"""Gemeinsame Testumgebung – wird vor allen Testdateien geladen."""
import os
import tempfile

os.environ["FG_DATA_DIR"] = tempfile.mkdtemp()
os.environ["FG_ADMIN_PASSWORD"] = "admin-passwort"
os.environ["FG_PUBLIC_URL"] = "https://fotos.example.de"
os.environ["FG_SCHEDULER"] = "0"
os.environ["FG_UPDATE_CHECK"] = "0"
# Leerer „NAS-Wurzelordner“: Tests legen darunter volume1/photo und volume1/homes an
os.environ["FG_VOLUME_ROOT"] = tempfile.mkdtemp()
os.environ["FG_ACL_TOOL"] = "/nicht/vorhanden/synoacltool"

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    from app.db import init_db
    init_db()


@pytest.fixture(autouse=True)
def _wait_for_background_scan():
    """Eine im Hintergrund gestartete Suche (z. B. nach dem Wiederherstellen) darf nicht in den nächsten Test laufen."""
    yield
    import time
    from app import scanner
    for _ in range(600):
        if not scanner._lock.locked():
            return
        time.sleep(0.05)
