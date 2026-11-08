"""Hintergrund-Aufgaben: nächtlicher Scan, Datensicherung, Update-Prüfung (einmal pro Minute nachsehen)."""
import threading
import traceback

from .config import settings

_stop = threading.Event()
_thread = None


def _tick() -> None:
    from . import backup, scanner, updates
    for name, job in (("Sicherung", backup.run_due), ("Scan", scanner.run_due)):
        try:
            job()
        except Exception:  # noqa: BLE001 – ein Fehler darf die anderen Aufgaben nicht stoppen
            print(f"[fotoglobus] {name} fehlgeschlagen:\n{traceback.format_exc()}")
    if settings.update_check:
        updates.check_in_background()


def _loop() -> None:
    _stop.wait(5)  # App erst fertig starten lassen
    while not _stop.is_set():
        _tick()
        _stop.wait(60)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
