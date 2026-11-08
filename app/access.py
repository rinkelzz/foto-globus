"""Wer darf welche Fotos sehen?

- **Persönliche Fotos** (/volumeX/homes/<benutzer>/Photos) sieht nur der Besitzer – wie in Synology Photos.
- **Gemeinsame Fotos** (/volumeX/photo) richten sich nach den Ordnerrechten in DSM: Für jeden Ordner mit Fotos
  fragen wir DSM per `synoacltool -get-perm <ordner> <benutzer>`, ob der Benutzer lesen darf. Das Ergebnis wird
  eine Weile zwischengespeichert. Wer einen übergeordneten Ordner nicht lesen darf, sieht auch darunter nichts.
- Lässt sich ein Recht nicht ermitteln (Programm fehlt, unbekannte Ausgabe), gilt „kein Zugriff“ – sicher vor
  bequem. Admins können in den Einstellungen auf „alle angemeldeten DSM-Benutzer“ umstellen.
"""
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

from .config import settings

CACHE_SECONDS = 30 * 60
USER_RE = re.compile(r"^[A-Za-z0-9._@\-\\ ]{1,64}$")

_cache: Dict[Tuple[str, str], Tuple[bool, float]] = {}
_lock = threading.Lock()
_last_raw: Dict[str, str] = {}  # letzte Rohausgabe je Ordner – für „Rechte testen“ in den Einstellungen


# synoacltool gibt die Rechte im Windows-Stil aus, z. B. „rwxpdDaARWcCo“ (13 Stellen, „-“ = nicht erlaubt).
# Das erste Zeichen ist „r“ = Daten lesen. Ohne ACL kommen Linux-Rechte wie „r-x“.
_WIN_PERM = re.compile(r"(?<![A-Za-z-])([r-][w-][x-][p-][d-][D-][a-][A-][R-][W-][c-][C-][o-])(?![A-Za-z-])")
_LINUX_PERM = re.compile(r"(?<![A-Za-z-])([r-][w-][x-])(?![A-Za-z-])")


def parse_perm(output: str) -> Optional[bool]:
    """True/False, ob „lesen“ erlaubt ist – None, wenn die Ausgabe nicht zu deuten ist.

    Bevorzugt wird die Zeile mit dem Endergebnis („Final permission“ o. ä.), sonst die letzte Rechte-Angabe."""
    lines = [ln for ln in (output or "").splitlines() if ln.strip()]
    if not lines:
        return None
    final = [ln for ln in lines if re.search(r"final|result|effective|permission", ln, re.I)]
    for group in (final, lines):
        for ln in reversed(group):
            m = _WIN_PERM.search(ln)
            if m:
                return m.group(1)[0] == "r"
        for ln in reversed(group):
            m = _LINUX_PERM.search(ln)
            if m:
                return m.group(1)[0] == "r"
    return None


def _ask_dsm(folder: str, user: str) -> bool:
    try:
        res = subprocess.run([settings.acl_tool, "-get-perm", folder, user], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=10)
        raw = res.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError) as e:
        raw = f"Fehler: {e}"
        _last_raw[folder] = raw
        return False
    _last_raw[folder] = raw[-2000:]
    ok = parse_perm(raw)
    return bool(ok) and res.returncode == 0


def can_read(folder: str, user: str, now: Optional[float] = None) -> bool:
    """Darf user den Ordner lesen? (zwischengespeichert)"""
    if not USER_RE.match(user or ""):
        return False
    now = now or time.time()
    key = (user.lower(), folder)
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[1] < CACHE_SECONDS:
            return hit[0]
    ok = _ask_dsm(folder, user)
    with _lock:
        _cache[key] = (ok, now)
    return ok


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _chain(folder: str, root: str):
    """Alle Ordner von root bis folder (einschließlich)."""
    root = root.rstrip("/")
    rel = os.path.relpath(folder, root)
    parts = [] if rel == "." else rel.split(os.sep)
    cur = root
    yield cur
    for p in parts:
        cur = os.path.join(cur, p)
        yield cur


def readable_folders(folders: Iterable[str], root: str, user: str,
                     check: Callable[[str, str], bool] = None) -> Set[str]:
    """Welche der Ordner (alle unterhalb von root) darf user lesen?

    Ein Ordner zählt nur, wenn auch alle Ordner darüber bis zur Freigabe lesbar sind. Geprüft wird von oben
    nach unten und parallel (DSM-Aufrufe dauern je ein paar Millisekunden)."""
    check = check or can_read
    folders = sorted(set(folders))
    if not folders:
        return set()
    verdict: Dict[str, bool] = {}
    # nach Tiefe gruppieren, damit Eltern vor Kindern feststehen
    by_depth: Dict[int, Set[str]] = {}
    for f in folders:
        for d, c in enumerate(_chain(f, root)):
            by_depth.setdefault(d, set()).add(c)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for depth in sorted(by_depth):
            todo = []
            for c in sorted(by_depth[depth]):
                parent = os.path.dirname(c) if depth else None
                if parent is not None and not verdict.get(parent, False):
                    verdict[c] = False
                else:
                    todo.append(c)
            for c, ok in zip(todo, pool.map(lambda x: check(x, user), todo)):
                verdict[c] = ok
    return {f for f in folders if verdict.get(f)}


def last_output(folder: str) -> str:
    return _last_raw.get(folder, "")
