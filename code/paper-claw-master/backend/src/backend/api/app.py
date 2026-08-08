from __future__ import annotations

from fastapi import FastAPI

from backend.api.errors import register_error_handlers
from backend.api.routers import agent, artifacts, human_loop, mentor_workflows, read_models, tasks
from backend.services.arxiv_task_scheduler import start_arxiv_task_scheduler, stop_arxiv_task_scheduler


def create_app() -> FastAPI:
    app = FastAPI(title="Paper Claw API")
    register_error_handlers(app)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.on_event("startup")
    def start_background_services() -> None:
        start_arxiv_task_scheduler()

    @app.on_event("shutdown")
    def stop_background_services() -> None:
        stop_arxiv_task_scheduler()

    app.include_router(read_models.router, prefix="/api")
    app.include_router(human_loop.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(mentor_workflows.router, prefix="/api")
    app.include_router(tasks.router, prefix="/api")
    return app
