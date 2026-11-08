"""Einstiegspunkt des Foto-Globus."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, csrf, scheduler
from .config import settings
from .db import connect, init_db
from .dsm import write_ui_config
from .dsm_auth import proxy_info, publish_proxy_files
from .routers import admin, auth, backup, branding, photos, updates


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    conn = connect()
    try:
        write_ui_config(conn)
        publish_proxy_files()
    finally:
        conn.close()
    if settings.scheduler:
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(
    title="Foto-Globus",
    version=__version__,
    description="Fotos aus Synology Photos als Pinnadeln auf einer Weltkugel.",
    root_path=settings.root_path,
    lifespan=lifespan,
)

# Echte Absenderadresse hinter dem Reverse Proxy nur übernehmen, wenn die Anfrage von der NAS selbst kommt
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # noqa: E402

TRUSTED_PROXIES = ["127.0.0.1", "::1"]
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=TRUSTED_PROXIES)
# Punkte-Liste und Länderkarte sind groß, aber gut komprimierbar
app.add_middleware(GZipMiddleware, minimum_size=2048)


class _RememberPeer:
    """Merkt sich die echte TCP-Gegenstelle, bevor X-Forwarded-For sie umschreibt
    (für die Prüfung, ob eine Anfrage wirklich von ui/app.cgi auf der NAS kommt)."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            scope["fg_peer"] = client[0] if client else ""
        await self.app(scope, receive, send)


app.add_middleware(_RememberPeer)  # zuletzt hinzugefügt = läuft zuerst

for r in (auth.router, admin.router, backup.router, branding.router, photos.router, updates.router):
    app.include_router(r)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    reason = csrf.blocked(request.method, request.url.path, request.headers)
    if reason:
        return JSONResponse({"detail": reason}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index(request: Request):
    # Versionsnummer an CSS/JS hängen, damit nach einem Update nichts Altes aus dem Cache kommt.
    # Im DSM-Fenster laufen alle Adressen über app.cgi?p=… (gleicher Ursprung wie DSM).
    proxied = proxy_info(request)
    base = (proxied["base"] + "?p=/") if proxied else ""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("{{v}}", __version__)
    html = html.replace('"static/', '"' + base + "static/")
    html = html.replace("<head>", "<head>\n<script>window.FG_PROXY=" + ("\"" + proxied["base"] + "\"" if proxied else "null") + ";</script>", 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/v1/health", tags=["System"])
def health():
    """Ohne Login – für DSM-Statusprüfung und Reverse-Proxy-Checks."""
    return {"status": "ok", "version": __version__}


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, proxy_headers=False)


if __name__ == "__main__":
    run()
