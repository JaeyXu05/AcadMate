from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.schemas import ProviderResolutionError


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProviderResolutionError)
    async def provider_resolution_error_handler(request: Request, exc: ProviderResolutionError) -> JSONResponse:
        return JSONResponse(status_code=400, content=exc.error.model_dump())

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"code": "bad_request", "message": str(exc), "detail": {}})
