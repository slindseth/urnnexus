from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ApiModel

JobType = Literal["sync", "analysis"]
RunMode = Literal["sync_only", "analysis", "unknown"]
SyncStrategy = Literal["delta", "full", "fallback_full", "unknown"]


class SyncPerformance(ApiModel):
    total_duration_seconds: float | None = None
    authentication_seconds: float | None = None
    graph_query_seconds: float | None = None
    downloads_seconds: float | None = None
    local_state_update_seconds: float | None = None
    finalization_seconds: float | None = None
    graph_requests: int | None = None
    downloaded_bytes: int | None = None


class ProjectCreateRequest(ApiModel):
    project_name: str
    template: str | None = None
    folders: list[str] = Field(default_factory=list)


class ProjectCreateResponse(ApiModel):
    project_name: str
    relative_project_path: str
    mode: Literal["onedrive"]
    folders_created: list[str] = Field(default_factory=list)
    warning: str | None = None


class ProjectLocalCacheDeleteResponse(ApiModel):
    project_name: str
    hidden: bool = True
    removed_paths: list[str] = Field(default_factory=list)
    removed_state_rows: int = 0
    message: str = "Dette fjerner prosjektet fra Nexus-visningen og lokal cache. Det sletter ikke prosjektet i OneDrive."


class ProjectDeleteResponse(ApiModel):
    project_name: str
    deleted_remote_path: str
    deleted: bool = True
    existed: bool = True
    synced: bool = True
    message: str = "Prosjektet ble slettet fra OneDrive."


class AnalysisRunRequest(ApiModel):
    project_name: str | None = None
    email_mode: Literal["daily_digest", "immediate"] = "daily_digest"


class SyncRunRequest(ApiModel):
    project_name: str | None = None
    idempotency_key: str | None = None


class AnalysisRunResponse(ApiModel):
    job_id: str
    running: bool
    started_at: datetime
    status: str
    analysis_started: bool = True
    reports_generated: int = 0
    projects_synced: int = 0
    files_changed: int = 0
    reports_found: int = 0
    email_mode: Literal["daily_digest", "immediate"] = "daily_digest"
    project_name: str | None = None
    job_type: Literal["analysis"] = "analysis"
    requested_by: str = "nexus-web"
    requested_at: datetime | None = None
    current_phase: str | None = None
    current_project: str | None = None
    progress: float | None = None
    process_id: int | None = None
    appliance_run_id: str | None = None
    run_mode: RunMode = "analysis"
    event_code: str | None = None


class FileUploadResponse(ApiModel):
    project_name: str
    filename: str
    target_folder: str
    relative_path: str
    size_bytes: int
    mode: Literal["onedrive", "local_cache_only"]
    warning: str | None = None


class FolderCreateRequest(ApiModel):
    folder_name: str
    target_folder: str | None = None


class FolderCreateResponse(ApiModel):
    project_name: str
    folder_name: str
    target_folder: str
    relative_path: str
    mode: Literal["onedrive", "local_cache_only"]
    warning: str | None = None


class SyncRunResponse(ApiModel):
    job_id: str
    running: bool
    started_at: datetime
    status: str
    sync_only: bool = True
    analysis_started: bool = False
    reports_generated: int = 0
    projects_synced: int = 0
    files_changed: int = 0
    reports_found: int = 0
    job_type: Literal["sync"] = "sync"
    requested_by: str = "nexus-web"
    requested_at: datetime | None = None
    current_phase: str | None = None
    current_project: str | None = None
    progress: float | None = None
    process_id: int | None = None
    appliance_run_id: str | None = None
    run_mode: RunMode = "sync_only"
    event_code: str | None = None
    sync_strategy: SyncStrategy = "unknown"
    sync_strategy_reason: str | None = None
    remote_items_examined: int = 0
    files_downloaded: int = 0
    files_deleted: int = 0
    elapsed_seconds: float | None = None
    performance: SyncPerformance | None = None


class SyncStatusResponse(ApiModel):
    running: bool
    process_alive: bool = False
    lock_exists: bool = False
    lock_stale: bool = False
    activity: Literal["sync", "analysis", "idle"] = "idle"
    job_id: str | None = None
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_error: str | None = None
    error_code: str | None = None
    projects_synced: int = 0
    files_changed: int = 0
    reports_found: int = 0
    status: str = "idle"
    job_type: Literal["sync"] = "sync"
    requested_by: str = "nexus-web"
    requested_at: datetime | None = None
    current_phase: str | None = None
    current_project: str | None = None
    progress: float | None = None
    process_id: int | None = None
    appliance_run_id: str | None = None
    run_mode: RunMode = "sync_only"
    event_code: str | None = None
    sync_strategy: SyncStrategy = "unknown"
    sync_strategy_reason: str | None = None
    remote_items_examined: int = 0
    files_downloaded: int = 0
    files_deleted: int = 0
    elapsed_seconds: float | None = None
    performance: SyncPerformance | None = None


class AnalysisStatusResponse(ApiModel):
    running: bool
    process_alive: bool = False
    lock_exists: bool = False
    lock_stale: bool = False
    activity: Literal["sync", "analysis", "idle"] = "idle"
    job_id: str | None = None
    start_requested_at: datetime | None = None
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    startup_grace_active: bool = False
    process_spawned: bool = False
    auth_status: Literal["unknown", "ok", "auth_failed", "sync_failed"] = "unknown"
    last_error: str | None = None
    last_start_error: str | None = None
    error_code: str | None = None
    projects_synced: int = 0
    files_changed: int = 0
    reports_found: int = 0
    reports_generated: int = 0
    email_mode: Literal["daily_digest", "immediate"] | None = None
    project_name: str | None = None
    status: Literal["idle", "startup_pending", "running", "completed", "failed", "auth_failed", "sync_failed"] = "idle"
    analysis_started: bool = False
    job_type: Literal["analysis"] = "analysis"
    requested_by: str = "nexus-web"
    requested_at: datetime | None = None
    current_phase: str | None = None
    current_project: str | None = None
    progress: float | None = None
    process_id: int | None = None
    appliance_run_id: str | None = None
    run_mode: RunMode = "analysis"
    event_code: str | None = None
