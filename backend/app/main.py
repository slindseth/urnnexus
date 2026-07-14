from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.api.routes import router
from backend.app.config import ApplianceSettings
from backend.app.models.common import ApiError
from backend.app.version import APP_VERSION
from backend.app.services.appliance import (
    ApplianceService,
    ApplianceBusyError,
    ApplianceUnavailableError,
    AnalysisUnavailableError,
    OneDriveGraphWriteUnavailableError,
    OneDriveProjectWriter,
    ProjectAmbiguousError,
    ProjectFileNotFoundError,
    ProjectNotFoundError,
    ProjectReportNotFoundError,
    ProjectSyncError,
    ProjectWriteError,
    SyncOnlyUnavailableError,
)


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    level_name = os.getenv("LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app(settings: ApplianceSettings | None = None, *, onedrive_writer: OneDriveProjectWriter | None = None) -> FastAPI:
    _configure_logging()
    app = FastAPI(title="URN Nexus Web", version=APP_VERSION)
    resolved_settings = settings or ApplianceSettings()
    app.state.appliance_service = ApplianceService(resolved_settings, onedrive_writer=onedrive_writer)

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "status": "ok",
            "product": "URN Nexus Web",
            "api_base": "/api",
        }

    @app.exception_handler(ProjectNotFoundError)
    async def project_not_found_handler(_: Request, exc: ProjectNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=ApiError(code="project_not_found", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(ProjectAmbiguousError)
    async def project_ambiguous_handler(_: Request, exc: ProjectAmbiguousError) -> JSONResponse:
        return JSONResponse(status_code=409, content=ApiError(code="project_ambiguous", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(ProjectReportNotFoundError)
    async def project_report_not_found_handler(_: Request, exc: ProjectReportNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=ApiError(code="report_not_found", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(ProjectFileNotFoundError)
    async def project_file_not_found_handler(_: Request, exc: ProjectFileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content=ApiError(code="file_not_found", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(ProjectWriteError)
    async def project_write_error_handler(_: Request, exc: ProjectWriteError) -> JSONResponse:
        return JSONResponse(status_code=400, content=ApiError(code="write_error", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(OneDriveGraphWriteUnavailableError)
    async def graph_write_unavailable_handler(_: Request, exc: OneDriveGraphWriteUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content=ApiError(code="graph_write_unavailable", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(ApplianceBusyError)
    async def appliance_busy_handler(_: Request, exc: ApplianceBusyError) -> JSONResponse:
        return JSONResponse(status_code=503, content=ApiError(code="appliance_busy", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(ProjectSyncError)
    async def project_sync_error_handler(_: Request, exc: ProjectSyncError) -> JSONResponse:
        return JSONResponse(status_code=503, content=ApiError(code="project_sync_failed", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(SyncOnlyUnavailableError)
    async def sync_only_unavailable_handler(_: Request, exc: SyncOnlyUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content=ApiError(code="sync_only_unavailable", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(AnalysisUnavailableError)
    async def analysis_unavailable_handler(_: Request, exc: AnalysisUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content=ApiError(code="analysis_unavailable", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content=ApiError(code="bad_request", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(ApplianceUnavailableError)
    async def appliance_unavailable_handler(_: Request, exc: ApplianceUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content=ApiError(code="appliance_unreachable", detail=str(exc)).model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def generic_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("Unhandled API error: %s", exc)
        return JSONResponse(status_code=500, content=ApiError(code="internal_error", detail="Internal server error").model_dump(mode="json"))

    app.include_router(router)
    return app


app = create_app()
