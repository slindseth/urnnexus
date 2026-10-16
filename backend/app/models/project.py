from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from .common import ApiModel


class ProjectReport(ApiModel):
    report_id: str = ""
    report_name: str
    report_path: Path
    report_type: str
    version: str | None = None
    created_at: datetime | None = None
    generated_at: datetime | None = None
    modified_at: datetime
    size_bytes: int
    is_latest: bool = False
    open_url: str = ""
    download_url: str = ""


class ProjectUiFields(ApiModel):
    display_name: str
    source_label: str = "OneDrive"
    relative_project_path: str
    hidden_internal_path: Path
    last_synced_at: datetime | None = None
    latest_comment_document: str | None = None
    latest_comment_document_open_url: str | None = None
    latest_comment_created_at: datetime | None = None
    latest_comment_modified_at: datetime | None = None
    comment_document_count: int = 0
    is_sample_project: bool = False
    is_local_cache_only: bool = False


class ProjectSummary(ProjectUiFields):
    project_name: str
    project_path: Path
    last_analyzed_at: datetime | None = None
    status: str
    file_count: int = 0
    report_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ProjectAnalysisInfo(ApiModel):
    status: str
    last_analyzed_at: datetime | None = None
    provider: str | None = None
    model: str | None = None
    documents_seen: int | None = None
    chunks_created: int | None = None
    report_items_count: int | None = None
    output_docx_path: Path | None = None
    run_summary_path: Path | None = None
    warnings_count: int = 0
    errors_count: int = 0


class ProjectDetailResponse(ProjectSummary):
    sync_coverage: dict[str, Any] = Field(default_factory=dict)
    analysis: ProjectAnalysisInfo | None = None
    reports: list[ProjectReport] = Field(default_factory=list)


class ProjectListResponse(ApiModel):
    count: int
    projects: list[ProjectSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProjectReportsResponse(ProjectUiFields):
    project_name: str
    project_path: Path
    count: int
    reports: list[ProjectReport] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ProjectDebugPathCandidate(ApiModel):
    candidate_path: Path
    source_file_count: int
    report_count: int
    comment_document_count: int
    source_inventory_mode: str
    is_sample_project: bool = False
    selected: bool = False
    latest_comment_document: str | None = None
    latest_comment_modified_at: datetime | None = None


class ProjectDebugPathsResponse(ApiModel):
    project_name: str
    resolved_project_path: Path
    project_path_exists: bool
    total_files_on_disk: int
    counted_source_files: int
    comment_documents_found: int
    first_20_files_on_disk: list[str] = Field(default_factory=list)
    ignored_file_count: int = 0
    ignored_reasons: list[str] = Field(default_factory=list)
    candidates: list[ProjectDebugPathCandidate] = Field(default_factory=list)
