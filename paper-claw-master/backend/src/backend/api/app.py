from __future__ import annotations

import logging
import ssl
import time
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel
from sqlalchemy import text

from backend.api.errors import register_error_handlers
from backend.api.routers import agent, artifacts, human_loop, mentor_workflows, read_models, runs, tasks
from backend.db.session import engine
from backend.settings import get_settings
from backend.services.arxiv_task_scheduler import start_arxiv_task_scheduler, stop_arxiv_task_scheduler

logger = logging.getLogger(__name__)
_chat_probe_cache: tuple[float, bool, str | None] = (0.0, False, "not_checked")


class ChatReadinessRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


def _chat_probe_client(base_url: str) -> httpx.Client:
    # Keep readiness on the same transport profile as model-backed skills.
    # The USTC gateway may stall when Python negotiates TLS 1.3.
    if urlparse(base_url).hostname == "api.llm.ustc.edu.cn":
        tls_context = ssl.create_default_context()
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.maximum_version = ssl.TLSVersion.TLSv1_2
        return httpx.Client(verify=tls_context, trust_env=False, timeout=8.0)
    return httpx.Client(trust_env=False, timeout=8.0)


def _chat_readiness(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[bool, str | None]:
    """Probe the configured CHATAGENT gateway, not merely env presence."""
    global _chat_probe_cache
    settings = get_settings()
    has_override = any(value is not None for value in (api_key, base_url, model))
    effective_api_key = (api_key if has_override else settings.chat_api_key) or ""
    effective_base_url = (base_url if has_override else settings.chat_base_url) or ""
    effective_model = (model if has_override else settings.chat_model) or ""
    if not all(value.strip() for value in (effective_api_key, effective_base_url, effective_model)):
        return False, "not_configured"
    now = time.monotonic()
    if not has_override:
        checked_at, cached_ok, cached_error = _chat_probe_cache
        if now - checked_at < 20:
            return cached_ok, cached_error
    try:
        with _chat_probe_client(effective_base_url) as client:
            response = client.get(
                f"{effective_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {effective_api_key}"},
            )
            response.raise_for_status()
            model_ids = {
                str(item.get("id"))
                for item in response.json().get("data", [])
                if isinstance(item, dict)
            }
        result = (True, None) if effective_model in model_ids else (False, "configured_model_unavailable")
    except Exception as exc:  # readiness returns a compact dependency error
        result = (False, type(exc).__name__)
    if not has_override:
        _chat_probe_cache = (now, result[0], result[1])
    return result


def _readiness_payload() -> dict[str, object]:
    database_ok = False
    database_error: str | None = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # readiness must never turn into a 500 traceback
        database_error = type(exc).__name__

    settings = get_settings()
    chat_configured = bool(
        settings.chat_api_key and settings.chat_base_url and settings.chat_model
    )
    # Deterministic local RAG is the default deployment mode and does not need
    # a chat gateway. Only model-backed reasoning makes chat readiness a hard
    # dependency for the service.
    if settings.mentor_workflow_model_reasoning_enabled:
        chat_reachable, chat_error = _chat_readiness()
    else:
        chat_reachable, chat_error = True, None
    ready = database_ok and chat_reachable
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "dependencies": {
            "database": database_ok,
            "chat_configured": chat_configured,
            "chat_reachable": chat_reachable,
        },
        "database_error": database_error,
        "chat_error": chat_error,
    }


def _mentor_readiness_payload() -> dict[str, object]:
    """Readiness for the deterministic mentor workflow, not every AI feature."""
    database_ok = False
    database_error: str | None = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:
        database_error = type(exc).__name__

    settings = get_settings()
    model_reasoning = settings.mentor_workflow_model_reasoning_enabled
    if model_reasoning:
        chat_reachable, chat_error = _chat_readiness()
    else:
        chat_reachable, chat_error = True, None
    ready = database_ok and chat_reachable
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "mode": "model_reasoning" if model_reasoning else "deterministic",
        "dependencies": {
            "database": database_ok,
            "chat_required": model_reasoning,
            "chat_reachable": chat_reachable,
        },
        "database_error": database_error,
        "chat_error": chat_error,
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Paper Claw API")
    register_error_handlers(app)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        # Liveness only: this endpoint must stay cheap and must not claim that
        # database-backed business routes are ready.
        return {"status": "ok"}

    @app.get("/api/ready")
    def ready() -> JSONResponse:
        payload = _readiness_payload()
        return JSONResponse(
            status_code=200 if payload["ready"] else 503,
            content=payload,
        )

    @app.get("/api/mentor-ready")
    def mentor_ready() -> JSONResponse:
        payload = _mentor_readiness_payload()
        return JSONResponse(
            status_code=200 if payload["ready"] else 503,
            content=payload,
        )

    @app.post("/api/chat-ready")
    def chat_ready(request: ChatReadinessRequest) -> JSONResponse:
        """Check the actual model gateway, including a D-side user override."""
        ready, error = _chat_readiness(request.api_key, request.base_url, request.model)
        payload = {
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "error": error,
        }
        return JSONResponse(status_code=200 if ready else 503, content=payload)

    @app.on_event("startup")
    def start_background_services() -> None:
        readiness = _readiness_payload()
        if not readiness["ready"]:
            logger.warning("Paper Claw started but is not ready: %s", readiness)
        start_arxiv_task_scheduler()

    @app.on_event("shutdown")
    def stop_background_services() -> None:
        stop_arxiv_task_scheduler()

    app.include_router(human_loop.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(mentor_workflows.router, prefix="/api")
    # Harness `/runs/next-skill` 必须排在 read_models 的 `/runs/{run_id}` 前面，否则会被当成 int 路径参数打成 422。
    app.include_router(runs.router, prefix="/api")
    app.include_router(read_models.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    return app
