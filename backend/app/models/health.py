from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .common import ApiModel


class ReadinessResponse(ApiModel):
    """Cheap liveness/readiness snapshot used during frontend startup."""

    ready: bool
    backend: bool = True
    appliance: bool = False
    graph: bool = False
    status: str = "starting"
    code: str | None = None
    detail: str | None = None


class HealthResponse(ApiModel):
    appliance_available: bool
    uptime_seconds: float
    uptime: str
    version: str | None = None
    appliance_root: Path
    discovered_projects: int = 0
    last_synced_at: datetime | None = None
    last_analyzed_at: datetime | None = None
    latest_report_generated_at: datetime | None = None
    project_count: int = 0
    file_count: int = 0
    report_count: int = 0
    one_drive_status: str = "unknown"
    one_drive_detail: str | None = None
    graph_write_status: str = "unknown"
    graph_write_detail: str | None = None
    openai_status: str = "unknown"
    openai_detail: str | None = None
    smtp_status: str = "unknown"
    smtp_detail: str | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    disk_free_bytes: int | None = None
    cache_size_bytes: int | None = None
    errors_last_24h: int = 0
    warnings_last_24h: int = 0
