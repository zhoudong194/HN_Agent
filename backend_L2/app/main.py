"""
backend-L2/app/main.py — FastAPI application factory.

Discovers and mounts all biz_* modules automatically.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Resolve project root (backend-L2/app/main.py -> project root)
APP_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

_log_file = APP_DIR / "server.log"
_log_handler = logging.handlers.RotatingFileHandler(
    str(_log_file), maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
log = logging.getLogger("server")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Company Rules RAG API",
        version="4.0.0",
        description="RAG backend powered by PostgreSQL + pgvector.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    _discover_and_mount_biz_routers(app)

    @app.get("/", include_in_schema=False)
    async def user_app():
        return FileResponse(str(STATIC_DIR / "user_view.html"))

    @app.get("/admin", include_in_schema=False)
    async def admin_app():
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/api/health")
    async def health():
        from biz_rag.query.service import get_rag_service
        svc = get_rag_service()
        status = svc.get_status()
        if not status.get("initialized"):
            raise HTTPException(status_code=503, detail=status)
        return status

    @app.on_event("startup")
    async def _warmup():
        _ensure_rbac_schema()
        _init_rag_service()
        _init_mcp_registry()

    return app


def _discover_and_mount_biz_routers(app: FastAPI) -> None:
    """Discover biz_* packages and mount their api_routers."""
    import importlib

    backend_dir = Path(__file__).resolve().parent
    for item in backend_dir.iterdir():
        if not item.is_dir():
            continue
        if not item.name.startswith("biz_"):
            continue

        try:
            module = importlib.import_module(item.name)
            if hasattr(module, "api_router"):
                app.include_router(module.api_router, prefix="/api")
                log.info("Mounted %s/api_router", item.name)
        except Exception as e:
            log.warning("Failed to load %s: %s", item.name, e)


def _ensure_rbac_schema() -> None:
    """Ensure RBAC schema exists and admin password is set."""
    try:
        from pathlib import Path as P
        rbac_sql = P(__file__).resolve().parent.parent.parent / "_rbac_init.sql"
        if not rbac_sql.exists():
            log.warning("_rbac_init.sql not found at %s", rbac_sql)
            return

        import bcrypt
        from base_framework.base.db_engine import PooledConn

        sql_text = rbac_sql.read_text(encoding="utf-8")
        with PooledConn() as conn:
            cur = conn.cursor()
            cur.execute(sql_text)
            conn.commit()

        admin_email = "admin@example.com"
        admin_pw = "admin123"
        pw_hash = bcrypt.hashpw(
            admin_pw.encode("utf-8")[:72],
            bcrypt.gensalt(rounds=10)
        ).decode("ascii")

        with PooledConn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE rbac.users SET pw_hash=%s "
                "WHERE email=%s AND pw_hash='__SEED__PLACEHOLDER__'",
                (pw_hash, admin_email),
            )
            if cur.rowcount:
                log.info("[RBAC] Seeded admin user password (%s)", admin_email)
            conn.commit()

        log.info("RBAC schema ensured")
    except Exception as e:
        log.exception("RBAC schema bootstrap failed: %s", e)
        raise


def _init_mcp_registry() -> None:
    """Register built-in MCP Servers on startup."""
    try:
        from biz_mcp.init_data import register_builtin_mcp, seed_builtin_servers
        register_builtin_mcp()
        seed_builtin_servers()
        log.info("MCP registry initialised")
    except Exception as e:
        log.warning("MCP registry warmup failed: %s", e)


def _init_rag_service() -> None:
    """Initialise RAG service on startup."""
    try:
        from biz_rag.query.service import get_rag_service
        svc = get_rag_service()
        status = svc.initialize()
        log.info("RAG service ready: %s", status)
    except Exception as e:
        log.warning("RAG warmup failed: %s — will retry on first request", e)


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
