from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import threading
import re
import shutil
import sqlite3
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol
from uuid import uuid4
from urllib.parse import quote
from zoneinfo import ZoneInfo

from backend.app.config import ApplianceSettings
from backend.app.models.common import CountFacet
from backend.app.models.files import ProjectFileFilters, ProjectFileNode, ProjectFilesResponse
from backend.app.models.health import HealthResponse, ReadinessResponse
from backend.app.models.activity import (
    ActivityError,
    ActivityEvent,
    ActivityEventsResponse,
    ActivityLevel,
    ActivityLogEntry,
    ActivityLogsResponse,
    ActivityState,
    ActivityStatusResponse,
)
from backend.app.models.operations import (
    AnalysisRunResponse,
    AnalysisStatusResponse,
    FileUploadResponse,
    FolderCreateResponse,
    ProjectCreateResponse,
    ProjectDeleteResponse,
    ProjectLocalCacheDeleteResponse,
    SyncPerformance,
    SyncRunResponse,
    SyncStatusResponse,
)
from backend.app.models.project import (
    ProjectAnalysisInfo,
    ProjectDebugPathCandidate,
    ProjectDebugPathsResponse,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectReport,
    ProjectReportsResponse,
    ProjectSummary,
)
from backend.app.version import get_app_version

logger = logging.getLogger(__name__)

OSLO_TIMEZONE = ZoneInfo("Europe/Oslo")
LIGHTWEIGHT_STATE_DB_FILENAME = "onedrive_lightweight_state.sqlite3"
REPORT_SUFFIXES = {".docx", ".pdf"}
OPENABLE_REPORT_SUFFIXES = {".docx", ".pdf"}
COMMENT_ROOT_NAMES = {"kommentarer", "enterprise_review"}
REPORT_ROOT_NAMES = {"kommentarer"}
DISPLAY_PATH_PREFIX = "AnbudAppliance/"
DEFAULT_PROJECT_FOLDERS = (
    "Anbud",
    "Bakgrunnsdokumenter",
    "Tegninger",
    "Tidligere kommunikasjon",
    "Kommentarer",
)
HIDDEN_PROJECTS_STATE_RELATIVE_PATH = Path("cache") / "urn_nexus_hidden_projects.json"
LOCAL_PROJECTS_RELATIVE_ROOT = Path("cache") / "urn_nexus_local_projects" / "Urban_Reuse_Norway"
LOCAL_UPLOADS_RELATIVE_ROOT = Path("cache") / "urn_nexus_uploads" / "Urban_Reuse_Norway"
SOURCE_CATEGORY_LABELS: dict[str, str] = {
    "background_documents": "Bakgrunnsdokumenter",
    "tender": "Anbud",
    "drawings": "Tegninger",
    "previous_communication": "Tidligere kommunikasjon",
    "comments": "Kommentarer",
    "other": "Andre filer",
}
SOURCE_CATEGORY_BY_FOLDER: dict[str, str] = {
    "bakgrunnsdokumenter": "background_documents",
    "anbud": "tender",
    "tegninger": "drawings",
    "tidligere kommunikasjon": "previous_communication",
    "kommentarer": "comments",
}
_REPORT_VERSION_SUFFIX_RE = re.compile(r"(?:^|[\s_-])(?:v|versjon|version|rev|r)?\s*(\d+(?:\.\d+)*)\s*$", re.IGNORECASE)
_COMMENT_DOCUMENT_REPORT_RE = re.compile(r"(?i)\bkommentardokument\b(?:\s*[-_]\s*\d+(?:\.\d+)*)?\s*$")
_LOCK_BUSY_ERROR_PATTERNS = (
    "awaiting history lock",
    "waiting for history lock",
    "onedrive_sync_history.lock",
    "onedrive_lightweight_state.sqlite3",
)
_ANALYSIS_AUTH_ERROR_PATTERNS = (
    "aadsts",
    "invalid_grant",
    "authentication failed",
    "graph auth",
    "graph authentication",
    "invalid client",
    "unauthorized",
    "access token",
    "token expired",
    "permission denied",
    "forbidden",
)
_ANALYSIS_SYNC_ERROR_PATTERNS = (
    "sync failed",
    "sync error",
    "onedrive sync failed",
    "waiting for history lock",
    "awaiting history lock",
    "onedrive_sync_history.lock",
    "onedrive_lightweight_state.sqlite3",
)
ANALYSIS_STARTUP_GRACE_SECONDS = 5.0
APPLIANCE_BUSY_MESSAGE = "Appliance arbeider. Synk kan startes når aktiv jobb er ferdig."
ACTIVITY_JOURNAL_FILENAME = "urn_nexus_activity.jsonl"
ACTIVITY_CACHE_TTL_SECONDS = 3.0
HEALTH_CACHE_TTL_SECONDS = 5.0
REPORT_HISTORY_CACHE_MAX_FILES = 16
_REPORT_HISTORY_FIELDS = (
    "project_name", "remote_root_path", "local_project_root", "local_report_path",
    "output_docx_path", "local_output_path", "report_type", "timestamp",
    "uploaded_reports", "report_snapshot", "analysis_snapshot",
)
_REPORT_HISTORY_SNAPSHOT_FIELDS = (
    "project_name", "generated_at", "finished_at", "created_at",
    "local_report_path", "output_docx_path",
)
_REPORT_HISTORY_UPLOAD_FIELDS = (
    "remote_path", "local_path", "local_report_path", "local_output_path",
)
ACTIVITY_EVENT_LIMIT = 40
ACTIVITY_ERROR_LIMIT = 10
ACTIVITY_LOG_LIMIT = 160
ACTIVITY_HISTORY_LINES_LIMIT = 120
ACTIVITY_JOURNAL_LINES_LIMIT = 120
ACTIVITY_LOG_NOISE_PATTERNS = (
    "waiting for application startup",
    "application startup complete",
    "started server process",
    "waiting for application shutdown",
    "application shutdown complete",
    "address already in use",
    "error while attempting to bind on address",
)
ACTIVITY_LOCK_NOISE_PATTERNS = (
    "awaiting history lock",
    "waiting for history lock",
    "onedrive_sync_history.lock",
)


class ApplianceServiceError(RuntimeError):
    """Base error for read-only appliance access failures."""


class ApplianceUnavailableError(ApplianceServiceError):
    """Raised when the appliance root is missing."""


class ProjectNotFoundError(ApplianceServiceError):
    """Raised when a project cannot be matched."""


class ProjectAmbiguousError(ApplianceServiceError):
    """Raised when multiple projects match the same requested name."""


class ProjectReportNotFoundError(ApplianceServiceError):
    """Raised when a project report cannot be opened safely."""


class ProjectFileNotFoundError(ApplianceServiceError):
    """Raised when a project file cannot be opened safely."""


class ProjectWriteError(ApplianceServiceError):
    """Raised when a project write operation cannot be completed."""


class ApplianceBusyError(ApplianceServiceError):
    """Raised when a live sync or analysis job is already active."""


class OneDriveGraphWriteUnavailableError(ApplianceServiceError):
    """Raised when Microsoft Graph write access is not configured."""


class ProjectSyncError(ApplianceServiceError):
    """Raised when Nexus cannot refresh the OneDrive cache after a write."""


class SyncOnlyUnavailableError(ApplianceServiceError):
    """Raised when appliance cannot provide a sync-only mode."""


class AnalysisUnavailableError(ApplianceServiceError):
    """Raised when appliance cannot provide a full analysis mode."""


class OneDriveProjectWriter(Protocol):
    def create_project(self, project_name: str, *, folders: list[str], parent_remote_path: str) -> list[str]:
        """Create a project folder and subfolders in OneDrive."""

    def create_project_folder(
        self,
        project_name: str,
        folder_name: str,
        *,
        parent_remote_path: str,
        target_folder: str | None = None,
    ) -> dict[str, Any]:
        """Create a nested project folder in OneDrive."""

    def upload_file(
        self,
        project_name: str,
        filename: str,
        content: bytes,
        *,
        parent_remote_path: str,
        target_folder: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file directly to OneDrive."""

    def delete_project(self, project_name: str, *, parent_remote_path: str) -> tuple[str, bool]:
        """Delete a project folder from OneDrive."""


class ApplianceOneDriveProjectWriter:
    def __init__(self, appliance_root: Path, *, env: Mapping[str, str] | None = None) -> None:
        self.appliance_root = appliance_root.expanduser().resolve(strict=False)
        self.env = dict(env or {})

    @classmethod
    def from_settings(cls, settings: ApplianceSettings) -> "ApplianceOneDriveProjectWriter":
        env = dict(os.environ)
        env.update(_read_env_file(settings.resolved_appliance_root() / ".env"))
        missing = _missing_graph_write_env(env)
        if missing:
            raise OneDriveGraphWriteUnavailableError(
                "Microsoft Graph-write er ikke konfigurert. Mangler: " + ", ".join(missing)
            )
        return cls(settings.resolved_appliance_root(), env=env)

    def create_project(self, project_name: str, *, folders: list[str], parent_remote_path: str) -> list[str]:
        self._ensure_appliance_import_path()
        previous_env: dict[str, str | None] = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)
        try:
            from app.integrations.onedrive.client import OneDriveClient, OneDriveClientError

            client = OneDriveClient.from_env(env=self.env)
            parent = client.get_item_by_path(parent_remote_path)
            parent_id = str(parent.get("id") or "").strip()
            if not parent_id:
                raise OneDriveGraphWriteUnavailableError("Microsoft Graph returnerte ikke id for OneDrive-prosjektroten.")

            project = client.ensure_child_folder(parent_id, project_name)
            project_id = str(project.get("id") or "").strip()
            if not project_id:
                raise ProjectWriteError("Microsoft Graph opprettet prosjektmappen, men returnerte ikke mappe-id.")

            created: list[str] = []
            for folder_name in folders:
                client.ensure_child_folder(project_id, folder_name)
                created.append(folder_name)
            return created
        except OneDriveClientError as exc:
            raise ProjectWriteError(f"Microsoft Graph-write feilet: {exc}") from exc
        except OneDriveGraphWriteUnavailableError:
            raise
        except ProjectWriteError:
            raise
        except Exception as exc:
            raise ProjectWriteError(f"Kunne ikke opprette prosjekt i OneDrive via Microsoft Graph: {exc}") from exc
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def create_project_folder(
        self,
        project_name: str,
        folder_name: str,
        *,
        parent_remote_path: str,
        target_folder: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_appliance_import_path()
        previous_env: dict[str, str | None] = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)
        try:
            from app.integrations.onedrive.client import OneDriveClient, OneDriveClientError

            client = OneDriveClient.from_env(env=self.env)
            project_item = client.get_item_by_path(self._project_remote_path(parent_remote_path, project_name))
            project_id = str(project_item.get("id") or "").strip()
            if not project_id:
                raise ProjectWriteError("Microsoft Graph returnerte ikke id for prosjektmappen.")

            parent_id = project_id
            if target_folder:
                parent_id = self._ensure_project_folder_path(client, project_id, target_folder)

            created = client.ensure_child_folder(parent_id, self._clean_remote_folder_name(folder_name))
            return created
        except OneDriveClientError as exc:
            raise ProjectWriteError(f"Microsoft Graph-write feilet: {exc}") from exc
        except ProjectWriteError:
            raise
        except Exception as exc:
            raise ProjectWriteError(f"Kunne ikke opprette mappe i OneDrive via Microsoft Graph: {exc}") from exc
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def upload_file(
        self,
        project_name: str,
        filename: str,
        content: bytes,
        *,
        parent_remote_path: str,
        target_folder: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_appliance_import_path()
        previous_env: dict[str, str | None] = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)
        try:
            from app.integrations.onedrive.client import (
                GRAPH_ITEM_CONTENT_URL_TEMPLATE,
                OneDriveClient,
                OneDriveClientError,
                _load_requests_module,
                _select_content_type,
            )

            client = OneDriveClient.from_env(env=self.env)
            project_item = client.get_item_by_path(self._project_remote_path(parent_remote_path, project_name))
            project_id = str(project_item.get("id") or "").strip()
            if not project_id:
                raise ProjectWriteError("Microsoft Graph returnerte ikke id for prosjektmappen.")

            parent_id = project_id
            if target_folder:
                parent_id = self._ensure_project_folder_path(client, project_id, target_folder)

            requests = _load_requests_module()
            access_token = client.get_access_token()
            content_type = _select_content_type(Path(filename))
            upload_url = GRAPH_ITEM_CONTENT_URL_TEMPLATE.format(
                onedrive_user=client.config.onedrive_user,
                parent_item_id=parent_id,
                filename=quote(filename, safe=""),
            )
            response = requests.put(
                upload_url,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": content_type},
                data=content,
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProjectWriteError("Microsoft Graph upload did not return an item object.")
            return payload
        except OneDriveClientError as exc:
            raise ProjectWriteError(f"Microsoft Graph-write feilet: {exc}") from exc
        except ProjectWriteError:
            raise
        except Exception as exc:
            raise ProjectWriteError(f"Kunne ikke laste opp fil til OneDrive via Microsoft Graph: {exc}") from exc
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def delete_project(self, project_name: str, *, parent_remote_path: str) -> tuple[str, bool]:
        self._ensure_appliance_import_path()
        previous_env: dict[str, str | None] = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)
        try:
            from app.integrations.onedrive.client import OneDriveClient, OneDriveClientError, _format_graph_error_response, _load_requests_module

            client = OneDriveClient.from_env(env=self.env)
            parent_item = client.get_item_by_path(parent_remote_path)
            parent_id = str(parent_item.get("id") or "").strip()
            if not parent_id:
                raise ProjectWriteError("Microsoft Graph returnerte ikke id for OneDrive-prosjektroten.")

            project_path = self._project_remote_path(parent_remote_path, project_name)
            try:
                project_item = client.get_item_by_path(project_path)
            except OneDriveClientError as exc:
                if "Configured OneDrive folder not found" in str(exc):
                    return project_path, False
                raise

            requests = _load_requests_module()
            access_token = client.get_access_token()
            project_id = str(project_item.get("id") or "").strip()
            if not project_id:
                raise ProjectWriteError("Microsoft Graph returnerte ikke id for prosjektmappen.")

            delete_url = f"https://graph.microsoft.com/v1.0/users/{client.config.onedrive_user}/drive/items/{project_id}"
            response = requests.delete(delete_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=60)
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code == 404:
                    return project_path, True
                graph_response = _format_graph_error_response(getattr(exc, "response", None))
                if graph_response:
                    raise ProjectWriteError(f"Microsoft Graph-delete feilet ({graph_response}): {exc}") from exc
                raise ProjectWriteError(f"Microsoft Graph-delete feilet: {exc}") from exc
            return project_path, True
        except OneDriveClientError as exc:
            raise ProjectWriteError(f"Microsoft Graph-write feilet: {exc}") from exc
        except ProjectWriteError:
            raise
        except Exception as exc:
            raise ProjectWriteError(f"Kunne ikke slette prosjekt i OneDrive via Microsoft Graph: {exc}") from exc
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def _ensure_appliance_import_path(self) -> None:
        appliance_path = str(self.appliance_root)
        if appliance_path not in sys.path:
            sys.path.insert(0, appliance_path)

    def _project_remote_path(self, parent_remote_path: str, project_name: str) -> str:
        parent = str(parent_remote_path or "").strip().strip("/")
        project = self._clean_remote_folder_name(project_name)
        if not parent:
            return project
        return f"{parent}/{project}"

    def _ensure_project_folder_path(self, client: Any, parent_item_id: str, folder_path: str) -> str:
        segments = [segment.strip() for segment in str(folder_path or "").replace("\\", "/").split("/") if segment.strip() and segment.strip() != "."]
        if any(segment == ".." for segment in segments):
            raise ProjectWriteError("Invalid target folder.")
        current_parent_id = parent_item_id
        for segment in segments:
            created = client.ensure_child_folder(current_parent_id, self._clean_remote_folder_name(segment))
            current_parent_id = str(created.get("id") or "").strip()
            if not current_parent_id:
                raise ProjectWriteError("Microsoft Graph opprettet en mappe, men returnerte ikke mappe-id.")
        return current_parent_id

    def _clean_remote_folder_name(self, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ProjectWriteError("Folder name is required.")
        if cleaned in {".", ".."}:
            raise ProjectWriteError("Invalid folder name.")
        if any(char in cleaned for char in "\0"):
            raise ProjectWriteError("Folder name contains invalid characters.")
        return cleaned


@dataclass(slots=True)
class SourceFileRecord:
    relative_path: str
    absolute_path: Path
    folder_category: str
    size_bytes: int
    modified_at: datetime
    remote_item_id: str | None = None
    remote_parent_id: str | None = None

    @property
    def extension(self) -> str:
        return self.absolute_path.suffix.lower()


@dataclass(slots=True)
class SourceScanResult:
    source_files: list[SourceFileRecord]
    total_files_on_disk: int
    ignored_file_count: int
    ignored_reasons: list[str]
    first_20_files_on_disk: list[str]
    warnings: list[str]
    errors: list[str]
    source_inventory_mode: str = "filesystem"
    filesystem_total_files_on_disk: int = 0
    state_total_files_on_disk: int = 0
    state_path: Path | None = None


@dataclass(slots=True)
class StateProjectRecord:
    project_name: str
    project_path: Path
    remote_root_path: str | None
    source_label: str
    status: str
    last_synced_at: datetime | None
    last_analyzed_at: datetime | None
    updated_at: datetime | None
    report_path: Path | None
    report_url: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProjectRecord:
    project_name: str
    display_name: str
    source_label: str
    relative_project_path: str
    hidden_internal_path: Path
    state_path: Path | None
    last_synced_at: datetime | None
    latest_comment_document: str | None
    latest_comment_document_open_url: str | None
    latest_comment_created_at: datetime | None
    latest_comment_modified_at: datetime | None
    comment_document_count: int
    is_sample_project: bool
    is_local_cache_only: bool
    project_path: Path
    status: str
    last_analyzed_at: datetime | None
    file_count: int
    report_count: int
    analysis: ProjectAnalysisInfo | None
    reports: list[ProjectReport]
    file_tree: ProjectFileNode
    filters: ProjectFileFilters
    source_scan: SourceScanResult | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sort_timestamp: datetime | None = None


@dataclass(slots=True)
class NexusJobState:
    job_type: str = "sync"
    job_id: str | None = None
    requested_by: str = "nexus-web"
    requested_at: datetime | None = None
    status: str = "idle"
    current_phase: str | None = None
    current_project: str | None = None
    progress: float | None = None
    process: subprocess.Popen[str] | None = None
    process_id: int | None = None
    appliance_run_id: str | None = None
    run_mode: str = "unknown"
    event_code: str | None = None


@dataclass(slots=True)
class SyncJobState(NexusJobState):
    job_type: str = "sync"
    run_mode: str = "sync_only"
    running: bool = False
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_error: str | None = None
    projects_synced: int = 0
    files_changed: int = 0
    reports_found: int = 0
    project_name: str | None = None
    sync_strategy: str = "unknown"
    sync_strategy_reason: str | None = None
    remote_items_examined: int = 0
    files_downloaded: int = 0
    files_deleted: int = 0
    elapsed_seconds: float | None = None
    performance: SyncPerformance | None = None


@dataclass(slots=True)
class AnalysisJobState(NexusJobState):
    job_type: str = "analysis"
    run_mode: str = "analysis"
    running: bool = False
    start_requested_at: datetime | None = None
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    process_spawned: bool = False
    auth_status: str = "unknown"
    last_error: str | None = None
    last_start_error: str | None = None
    projects_synced: int = 0
    files_changed: int = 0
    reports_found: int = 0
    reports_generated: int = 0
    email_mode: str | None = None
    project_name: str | None = None


@dataclass(slots=True)
class RuntimeActivitySnapshot:
    sync_running: bool = False
    analysis_running: bool = False
    lock_exists: bool = False
    lock_stale: bool = False

    @property
    def activity(self) -> str:
        if self.sync_running:
            return "sync"
        if self.analysis_running:
            return "analysis"
        return "idle"


@dataclass(slots=True)
class ActivityEntryCandidate:
    timestamp: datetime
    level: ActivityLevel
    message: str
    project_name: str | None = None
    component: str | None = None
    order: int = 0
    kind: str = "log"
    category: str = "System"
    source: str = "System"
    event_code: str | None = None
    phase: str | None = None
    run_mode: str = "unknown"
    job_type: str | None = None
    job_id: str | None = None


@dataclass(slots=True)
class ActivityFeedSnapshot:
    captured_at: datetime
    status: ActivityStatusResponse
    events: list[ActivityEvent]
    errors: list[ActivityError]
    logs: list[ActivityLogEntry]


def _normalize_name(value: str) -> str:
    return value.strip().casefold()


def _display_relative_project_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text.casefold().startswith(DISPLAY_PATH_PREFIX.casefold()):
        return text[len(DISPLAY_PATH_PREFIX) :]
    return text


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc).astimezone(OSLO_TIMEZONE)
    return parsed.astimezone(OSLO_TIMEZONE)


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        keys = row.keys()
    except Exception:
        return default
    if key not in keys:
        return default
    try:
        value = row[key]
    except Exception:
        return default
    if value is None:
        return default
    return value


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        logger.warning("Unable to read appliance env file %s: %s", path, exc)
        return values

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key.startswith("#"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _env_first_value(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _missing_graph_write_env(env: Mapping[str, str]) -> list[str]:
    missing: list[str] = []
    if not _env_first_value(env, "MICROSOFT_TENANT_ID", "MS_TENANT_ID"):
        missing.append("MICROSOFT_TENANT_ID")
    if not _env_first_value(env, "MICROSOFT_CLIENT_ID", "MS_CLIENT_ID"):
        missing.append("MICROSOFT_CLIENT_ID")
    if not _env_first_value(env, "MICROSOFT_CLIENT_SECRET", "MS_CLIENT_SECRET"):
        missing.append("MICROSOFT_CLIENT_SECRET")
    if not _env_first_value(env, "ONEDRIVE_USER"):
        missing.append("ONEDRIVE_USER")
    auth_mode = _env_first_value(env, "ONEDRIVE_AUTH_MODE")
    if not auth_mode:
        missing.append("ONEDRIVE_AUTH_MODE=app_only")
    elif auth_mode != "app_only":
        missing.append("ONEDRIVE_AUTH_MODE=app_only")
    return missing


def _select_analysis_status(payload_status: str | None, state_status: str | None) -> str:
    state_clean = (state_status or "").strip()
    payload_clean = (payload_status or "").strip()

    if state_clean and state_clean.casefold() not in {"unknown", "success", "ok"}:
        return state_clean
    if payload_clean:
        if payload_clean.casefold() in {"success", "ok"}:
            return state_clean or "completed"
        return payload_clean
    if state_clean:
        return state_clean
    return "unknown"


def _status_key(status: str | None) -> str:
    return str(status or "").strip().casefold()


def _status_is_error(status: str | None) -> bool:
    return _status_key(status) in {"failed", "failure", "error", "errored"}


def _status_is_warning(status: str | None) -> bool:
    return _status_key(status) in {"completed_with_warnings", "success_with_warnings", "warning", "warnings"}


def _project_folder_category(relative_path: Path) -> str:
    if not relative_path.parts:
        return "other"
    first_segment = relative_path.parts[0].strip().casefold()
    return SOURCE_CATEGORY_BY_FOLDER.get(first_segment, "other")


def _is_ignored_name(name: str) -> bool:
    lowered = name.casefold().strip()
    if not lowered:
        return True
    if lowered.startswith("."):
        return True
    if lowered.startswith("~$"):
        return True
    return lowered in {"thumbs.db"}


def _source_file_ignore_reason_from_relative(relative_path: Path) -> str | None:
    if not relative_path.parts:
        return "Unreadable files are excluded from source file counts."

    if any(part.casefold() == "kommentarer" for part in relative_path.parts):
        return "Kommentarer folders are excluded from source file counts."

    if any(_is_ignored_name(part) for part in relative_path.parts[:-1]):
        return "Hidden or temporary directories are excluded from source file counts."

    if _is_ignored_name(relative_path.name):
        return "Hidden or temporary files are excluded from source file counts."

    return None


def _infer_sync_state_path(project_path: Path) -> Path | None:
    resolved = project_path.expanduser().resolve(strict=False)
    parts = resolved.parts
    for index in range(len(parts) - 2):
        if parts[index].casefold() == "cache" and parts[index + 1].casefold() == "onedrive_sync":
            if len(parts) - index < 4:
                return None
            state_parts = list(parts[:index]) + ["state", "onedrive_sync"] + list(parts[index + 2 : -1])
            return Path(*state_parts) / "sync_state.json"
    return None


def _is_project_root_candidate(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False

    markers = (
        "Anbud",
        "Bakgrunnsdokumenter",
        "Tegninger",
        "Tidligere kommunikasjon",
        "Kommentarer",
        ".riveanbud_state",
        ".riveanbud_cache",
    )
    for marker in markers:
        if (path / marker).exists():
            return True
    kommentarer = path / "Kommentarer"
    if kommentarer.exists() and any(child.suffix.lower() == ".docx" for child in kommentarer.rglob("*") if child.is_file()):
        return True
    return False


def _sort_comment_documents_key(report: ProjectReport) -> tuple[Any, ...]:
    created_at = report.created_at or datetime.min.replace(tzinfo=timezone.utc)
    generated_at = report.generated_at or datetime.min.replace(tzinfo=timezone.utc)
    version_key = _report_version_sort_key(report.version)
    return (
        1 if report.version else 0,
        version_key,
        created_at,
        generated_at,
        report.report_name.casefold(),
    )


def _report_sort_timestamp(report: ProjectReport) -> datetime:
    return report.created_at or report.generated_at or report.modified_at


def _report_version_sort_key(version: str | None) -> tuple[int, ...]:
    if not version:
        return (-1,)
    parts: list[int] = []
    for part in str(version).strip().split("."):
        if not part.strip().isdigit():
            return (-1,)
        parts.append(int(part))
    return tuple(parts) if parts else (-1,)


def _report_version_label(report_name: str) -> str | None:
    stem = Path(report_name).stem.strip()
    match = _REPORT_VERSION_SUFFIX_RE.search(stem)
    if match is None:
        return None
    raw_version = match.group(1).strip()
    return raw_version or None


def _is_comment_document_report_name(report_name: str) -> bool:
    stem = Path(report_name).stem.strip()
    if not stem:
        return False
    return bool(_COMMENT_DOCUMENT_REPORT_RE.search(stem))


def _file_created_at(stat_result: os.stat_result) -> datetime:
    birthtime = getattr(stat_result, "st_birthtime", None)
    if birthtime is not None:
        return datetime.fromtimestamp(birthtime, tz=OSLO_TIMEZONE)

    ctime = getattr(stat_result, "st_ctime", None)
    if ctime is not None:
        return datetime.fromtimestamp(ctime, tz=OSLO_TIMEZONE)

    return datetime.fromtimestamp(getattr(stat_result, "st_mtime", 0), tz=OSLO_TIMEZONE)


def _is_lock_busy_error(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.casefold()
    return any(pattern in lowered for pattern in _LOCK_BUSY_ERROR_PATTERNS)


def _classify_analysis_error(message: str | None) -> tuple[str, str]:
    if not message:
        return "failed", "unknown"
    lowered = message.casefold()
    if any(pattern in lowered for pattern in _ANALYSIS_AUTH_ERROR_PATTERNS):
        return "auth_failed", "auth_failed"
    if any(pattern in lowered for pattern in _ANALYSIS_SYNC_ERROR_PATTERNS):
        return "sync_failed", "sync_failed"
    return "failed", "unknown"


class ApplianceService:
    def __init__(
        self,
        settings: ApplianceSettings,
        *,
        started_at: datetime | None = None,
        onedrive_writer: OneDriveProjectWriter | None = None,
    ) -> None:
        self.settings = settings
        self.started_at = started_at or datetime.now(timezone.utc)
        self._onedrive_writer_override = onedrive_writer
        self._sync_lock = threading.Lock()
        self._sync_state = SyncJobState()
        self._analysis_lock = threading.Lock()
        self._analysis_state = AnalysisJobState()
        self._job_history: list[NexusJobState] = []
        self._last_sync_idempotency_key: str | None = None
        self._health_cache_lock = threading.Lock()
        self._health_cache_timestamp = 0.0
        self._health_cache: HealthResponse | None = None
        self._activity_cache_lock = threading.Lock()
        self._activity_cache_timestamp = 0.0
        self._activity_cache: ActivityFeedSnapshot | None = None
        self._activity_journal_lock = threading.Lock()
        self._health_build_lock = threading.Lock()
        self._activity_build_lock = threading.Lock()
        self._report_history_cache_lock = threading.Lock()
        self._report_history_cache: dict[
            Path, tuple[tuple[int, ...], tuple[dict[str, Any], ...]]
        ] = {}
        from .project_memory import ProjectMemoryGateway
        self.memory = ProjectMemoryGateway(self)

    def health(self) -> HealthResponse:
        return self._cached_health()

    def readiness(self) -> ReadinessResponse:
        """Return a lightweight readiness snapshot without touching sync state."""
        appliance_root = self.settings.resolved_appliance_root()
        appliance_available = appliance_root.exists() and appliance_root.is_dir()
        if not appliance_available:
            return ReadinessResponse(
                ready=False,
                backend=True,
                appliance=False,
                graph=False,
                status="starting",
                code="appliance_starting",
                detail="Appliance-root er ikke tilgjengelig ennå.",
            )

        # Graph is intentionally a capability flag here. Authentication and sync
        # are verified by their own status endpoints, never by readiness.
        return ReadinessResponse(
            ready=True,
            backend=True,
            appliance=True,
            graph=True,
            status="ready",
        )

    def _invalidate_health_cache(self) -> None:
        with self._health_cache_lock:
            self._health_cache_timestamp = 0.0
            self._health_cache = None

    def _cached_health(self) -> HealthResponse:
        now = time.monotonic()
        with self._health_cache_lock:
            if self._health_cache is not None and now - self._health_cache_timestamp < HEALTH_CACHE_TTL_SECONDS:
                return self._health_cache

        # Concurrent API calls share one refresh instead of repeating the scan.
        with self._health_build_lock:
            with self._health_cache_lock:
                if self._health_cache is not None and time.monotonic() - self._health_cache_timestamp < HEALTH_CACHE_TTL_SECONDS:
                    return self._health_cache
            health = self._calculate_health()
            with self._health_cache_lock:
                self._health_cache_timestamp = time.monotonic()
                self._health_cache = health
            return health

    def _calculate_health(self) -> HealthResponse:
        appliance_root = self.settings.resolved_appliance_root()
        available = appliance_root.exists() and appliance_root.is_dir()
        records = self.discover_projects() if available else []
        discovered_projects = len(records)
        uptime_seconds = max(0.0, (datetime.now(timezone.utc) - self.started_at).total_seconds())
        disk_total_bytes, disk_used_bytes, disk_free_bytes = self._disk_usage(appliance_root)
        latest_report_generated_at = self._latest_datetime(
            report.created_at or report.generated_at or report.modified_at for record in records for report in record.reports
        )
        now = datetime.now(OSLO_TIMEZONE)
        cutoff = now - timedelta(hours=24)
        return HealthResponse(
            appliance_available=available,
            uptime_seconds=uptime_seconds,
            uptime=str(timedelta(seconds=uptime_seconds)),
            version=get_app_version(),
            appliance_root=appliance_root,
            discovered_projects=discovered_projects,
            last_synced_at=self._latest_datetime([
                *(record.last_synced_at for record in records),
                self._last_successful_sync_at(),
            ]),
            last_analyzed_at=self._latest_datetime(record.last_analyzed_at for record in records),
            latest_report_generated_at=latest_report_generated_at,
            project_count=discovered_projects,
            file_count=sum(record.file_count for record in records),
            report_count=sum(record.report_count for record in records),
            one_drive_status=self._onedrive_status(appliance_root, records),
            one_drive_detail=self._onedrive_detail(appliance_root, records),
            graph_write_status=self._graph_write_status(),
            graph_write_detail=self._graph_write_detail(),
            openai_status="configured" if os.getenv("OPENAI_API_KEY") else "not_configured",
            openai_detail="OPENAI_API_KEY er satt." if os.getenv("OPENAI_API_KEY") else "OPENAI_API_KEY mangler.",
            smtp_status="configured" if os.getenv("SMTP_HOST") else "not_configured",
            smtp_detail="SMTP_HOST er satt." if os.getenv("SMTP_HOST") else "SMTP_HOST mangler.",
            disk_total_bytes=disk_total_bytes,
            disk_used_bytes=disk_used_bytes,
            disk_free_bytes=disk_free_bytes,
            cache_size_bytes=self._cache_size_bytes(appliance_root),
            errors_last_24h=sum(self._record_error_count_since(record, cutoff) for record in records),
            warnings_last_24h=sum(self._record_warning_count_since(record, cutoff) for record in records),
        )

    def _last_successful_sync_at(self) -> datetime | None:
        # A no-change sync may leave project timestamps unchanged. The journal
        # preserves successful completion times across backend restarts.
        return self._latest_datetime(
            _parse_datetime(str(payload.get("timestamp") or ""))
            for payload in self._read_activity_journal_payloads()
            if payload.get("event_code") in {"sync_completed", "sync_completed_no_changes"}
        )

    def activity_status(self) -> ActivityStatusResponse:
        return self._cached_activity_feed().status

    def activity_events(self) -> ActivityEventsResponse:
        feed = self._cached_activity_feed()
        return ActivityEventsResponse(updated_at=feed.captured_at, events=feed.events, errors=feed.errors)

    def activity_logs(self) -> ActivityLogsResponse:
        feed = self._cached_activity_feed()
        return ActivityLogsResponse(updated_at=feed.captured_at, entries=feed.logs)

    def _invalidate_activity_cache(self) -> None:
        with self._activity_cache_lock:
            self._activity_cache_timestamp = 0.0
            self._activity_cache = None

    def _cached_activity_feed(self) -> ActivityFeedSnapshot:
        now = time.monotonic()
        with self._activity_cache_lock:
            if self._activity_cache is not None and now - self._activity_cache_timestamp < ACTIVITY_CACHE_TTL_SECONDS:
                return self._activity_cache

        # Status, events and logs are requested together by the activity page.
        with self._activity_build_lock:
            with self._activity_cache_lock:
                if self._activity_cache is not None and time.monotonic() - self._activity_cache_timestamp < ACTIVITY_CACHE_TTL_SECONDS:
                    return self._activity_cache
            feed = self._calculate_activity_feed()
            with self._activity_cache_lock:
                self._activity_cache_timestamp = time.monotonic()
                self._activity_cache = feed
            return feed

    def _calculate_activity_feed(self) -> ActivityFeedSnapshot:
        health = self._cached_health()
        sync_status = self.sync_status()
        analysis_status = self.analysis_status()
        captured_at = datetime.now(OSLO_TIMEZONE)
        payloads = self._activity_payloads(sync_status=sync_status, analysis_status=analysis_status, health=health, captured_at=captured_at)

        event_candidates = self._activity_candidates_from_payloads(payloads, verbose=False)
        log_candidates = self._activity_candidates_from_payloads(payloads, verbose=True)
        events = self._activity_candidates_to_events(event_candidates, limit=ACTIVITY_EVENT_LIMIT)
        errors = self._activity_candidates_to_errors(event_candidates, limit=ACTIVITY_ERROR_LIMIT)
        logs = self._activity_candidates_to_logs(log_candidates, limit=ACTIVITY_LOG_LIMIT)
        status = self._activity_status_response(health=health, sync_status=sync_status, analysis_status=analysis_status, payloads=payloads, captured_at=captured_at)

        return ActivityFeedSnapshot(
            captured_at=captured_at,
            status=status,
            events=events,
            errors=errors,
            logs=logs,
        )

    def _activity_status_response(
        self,
        *,
        health: HealthResponse,
        sync_status: SyncStatusResponse,
        analysis_status: AnalysisStatusResponse,
        payloads: list[dict[str, Any]],
        captured_at: datetime,
    ) -> ActivityStatusResponse:
        current_payload = next((payload for payload in payloads if payload.get("source") == "current"), {})
        project_name = self._activity_current_project_name(sync_status=sync_status, analysis_status=analysis_status, payloads=payloads)
        state, activity, status, component = self._activity_state(sync_status=sync_status, analysis_status=analysis_status, payloads=payloads)
        active_job = self._activity_active_job(sync_status=sync_status, analysis_status=analysis_status)
        if not activity:
            activity = "Ingen aktiv jobb"
        if not status:
            status = "Ingen aktiv jobb" if state == "Klar" else state
        backend_version = health.version
        return ActivityStatusResponse(
            state=state,
            activity=activity,
            status=status,
            project_name=project_name,
            uptime=health.uptime,
            uptime_seconds=health.uptime_seconds,
            backend_version=backend_version,
            appliance_available=health.appliance_available,
            last_synced_at=health.last_synced_at,
            last_analyzed_at=health.last_analyzed_at,
            updated_at=captured_at,
            job_type=active_job.job_type if active_job else None,
            job_id=active_job.job_id if active_job else None,
            run_mode=active_job.run_mode if active_job else "unknown",  # type: ignore[arg-type]
            event_code=active_job.event_code if active_job else None,
            current_phase=active_job.current_phase if active_job else None,
            current_project=active_job.current_project if active_job else project_name,
            progress=active_job.progress if active_job else None,
            sync_strategy=active_job.sync_strategy if isinstance(active_job, SyncStatusResponse) else "unknown",  # type: ignore[arg-type]
            sync_strategy_reason=active_job.sync_strategy_reason if isinstance(active_job, SyncStatusResponse) else None,
            performance=active_job.performance if isinstance(active_job, SyncStatusResponse) else None,
        )

    def _activity_state(
        self,
        *,
        sync_status: SyncStatusResponse,
        analysis_status: AnalysisStatusResponse,
        payloads: list[dict[str, Any]],
    ) -> tuple[ActivityState, str | None, str | None, str | None]:
        active_job = self._activity_active_job(sync_status=sync_status, analysis_status=analysis_status)
        if isinstance(active_job, SyncStatusResponse):
            state = self._sync_activity_state(active_job, payloads)
            return state, "OneDrive Sync", active_job.current_phase or self._sync_activity_status(active_job, state), "OneDrive"
        if isinstance(active_job, AnalysisStatusResponse):
            if active_job.status == "startup_pending" or active_job.startup_grace_active:
                return "Starter", "Analysis", active_job.current_phase or "Starter analyse", "Analysis"
            if active_job.status in {"failed", "auth_failed", "sync_failed"}:
                return "Feilet", "Analysis", active_job.current_phase or "Analyse feilet", "Analysis"
            return "Analyserer", "Analysis", active_job.current_phase or "Analyserer dokumenter", "Analysis"

        if analysis_status.status in {"failed", "auth_failed", "sync_failed"} and analysis_status.last_error:
            return "Feilet", self._activity_latest_component(payloads) or "Analysis", analysis_status.last_error, "Analysis"
        if sync_status.status in {"failed", "error"} and sync_status.last_error:
            return "Synkronisering feilet", "Sync", "Synkronisering feilet", "OneDrive"
        return "Klar", None, "Ingen aktiv jobb", None

    def _activity_active_job(
        self,
        *,
        sync_status: SyncStatusResponse,
        analysis_status: AnalysisStatusResponse,
    ) -> SyncStatusResponse | AnalysisStatusResponse | None:
        sync_active = sync_status.running or sync_status.process_alive or sync_status.status == "startup_pending" or sync_status.activity == "sync"
        analysis_active = analysis_status.running or analysis_status.process_alive or analysis_status.status == "startup_pending" or analysis_status.startup_grace_active or analysis_status.activity == "analysis"
        if sync_active:
            return sync_status
        if analysis_active:
            return analysis_status
        return None

    def _sync_activity_state(self, status: SyncStatusResponse, payloads: list[dict[str, Any]]) -> ActivityState:
        event_code = status.event_code or self._latest_structured_value(payloads, status.job_id, "event_code")
        if status.status in {"failed", "error"} or event_code == "sync_failed":
            return "Synkronisering feilet"
        if event_code == "sync_completed_no_changes":
            return "Synkronisering fullført uten endringer"
        if event_code == "sync_completed" or status.status in {"completed", "skipped_no_changes", "success"}:
            return "Synkronisering fullført"
        phase = status.current_phase or self._latest_structured_value(payloads, status.job_id, "phase")
        allowed_phases = {
            "Starter synkronisering",
            "Kobler til OneDrive",
            "Henter endringer",
            "Synkroniserer prosjekt",
            "Laster ned filer",
            "Oppdaterer lokal status",
            "Fullfører synkronisering",
        }
        if phase in allowed_phases:
            return phase  # type: ignore[return-value]
        return "Starter synkronisering" if status.status == "startup_pending" else "Synkroniserer"

    def _sync_activity_status(self, status: SyncStatusResponse, state: ActivityState) -> str:
        if state == "Starter synkronisering":
            return "Starter synkronisering"
        if state == "Synkroniserer":
            return "Synkroniserer dokumenter"
        return state

    def _latest_structured_value(self, payloads: list[dict[str, Any]], job_id: str | None, key: str) -> str | None:
        for payload in reversed(payloads):
            payload_job_id = str(payload.get("job_id") or "").strip() or None
            if job_id and payload_job_id and payload_job_id != job_id:
                continue
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return None

    def _activity_stage_from_payloads(self, payloads: list[dict[str, Any]]) -> ActivityState | None:
        for payload in reversed(payloads):
            phase = str(payload.get("phase") or payload.get("current_phase") or "").strip()
            if phase in {
                "Starter analyse",
                "Analyserer dokumenter",
                "Genererer rapport",
                "Sender e-post",
            }:
                return phase  # type: ignore[return-value]
        return None

    def _activity_activity_label(self, state: ActivityState | str, component: str | None) -> str | None:
        lowered = str(state).casefold()
        if lowered == "feilet":
            return component or "Feil"
        if lowered == "klar":
            return component or "Ingen aktiv jobb"
        if lowered == "starter":
            return "Analyse"
        if lowered == "synkroniserer":
            return "OneDrive Sync"
        if lowered == "analyserer":
            return "Analyse"
        if lowered == "genererer rapport":
            return "Rapportgenerering"
        if lowered == "sender e-post":
            return "E-post"
        return component

    def _activity_default_status_for_state(self, state: ActivityState | str) -> str:
        lowered = str(state).casefold()
        if lowered == "starter":
            return "Starter analyse"
        if lowered == "synkroniserer":
            return "Synkroniserer dokumenter"
        if lowered == "analyserer":
            return "Analyserer dokumenter"
        if lowered == "genererer rapport":
            return "Genererer rapport"
        if lowered == "sender e-post":
            return "Sender e-post"
        if lowered == "feilet":
            return "Feilet"
        return "Ingen aktiv jobb"

    def _activity_component_for_state(self, state: ActivityState | str) -> str | None:
        lowered = str(state).casefold()
        if lowered == "starter":
            return "Analysis"
        if lowered == "synkroniserer":
            return "OneDrive"
        if lowered == "analyserer":
            return "Analysis"
        if lowered == "genererer rapport":
            return "Reports"
        if lowered == "sender e-post":
            return "Email"
        if lowered == "feilet":
            return "Backend"
        return None

    def _activity_current_project_name(
        self,
        *,
        sync_status: SyncStatusResponse,
        analysis_status: AnalysisStatusResponse,
        payloads: list[dict[str, Any]],
    ) -> str | None:
        active_job = self._activity_active_job(sync_status=sync_status, analysis_status=analysis_status)
        active_project = active_job.current_project if active_job else None
        candidates = (
            active_project,
            sync_status.current_project if isinstance(active_job, SyncStatusResponse) else None,
            analysis_status.current_project if isinstance(active_job, AnalysisStatusResponse) else None,
            self._activity_latest_project_name(payloads),
        )
        for candidate in candidates:
            if candidate and str(candidate).strip():
                return str(candidate).strip()
        return None

    def _activity_latest_project_name(self, payloads: list[dict[str, Any]]) -> str | None:
        for payload in reversed(payloads):
            if payload.get("project_name"):
                text = str(payload.get("project_name") or "").strip()
                if text:
                    return text
            if payload.get("source") == "history":
                uploaded_reports = payload.get("uploaded_reports")
                if isinstance(uploaded_reports, list):
                    for uploaded_report in uploaded_reports:
                        if not isinstance(uploaded_report, Mapping):
                            continue
                        project_name = str(uploaded_report.get("project_name") or "").strip()
                        if project_name:
                            return project_name
        return None

    def _activity_latest_message(self, payloads: list[dict[str, Any]]) -> str | None:
        for payload in reversed(payloads):
            message = str(payload.get("message") or "").strip()
            if message and not self._is_activity_noise(message):
                return message
        return None

    def _activity_latest_component(self, payloads: list[dict[str, Any]]) -> str | None:
        for payload in reversed(payloads):
            message = str(payload.get("message") or "").strip()
            if message and self._is_activity_noise(message):
                continue
            component = str(payload.get("component") or "").strip()
            if component:
                return component
        return None

    def _activity_has_meaningful_error(
        self,
        *,
        sync_status: SyncStatusResponse,
        analysis_status: AnalysisStatusResponse,
        payloads: list[dict[str, Any]],
    ) -> bool:
        return self._activity_primary_error_message(sync_status=sync_status, analysis_status=analysis_status, payloads=payloads) is not None

    def _activity_primary_error_message(
        self,
        *,
        sync_status: SyncStatusResponse,
        analysis_status: AnalysisStatusResponse,
        payloads: list[dict[str, Any]],
    ) -> str | None:
        for value in (
            analysis_status.last_error,
            analysis_status.last_start_error,
            sync_status.last_error,
            *[str(payload.get("message") or "").strip() for payload in payloads if str(payload.get("level") or "").upper() == "ERROR"],
        ):
            if self._is_meaningful_activity_error(value):
                return str(value).strip()
        return None

    def _recent_activity_is_current(self, payloads: list[dict[str, Any]]) -> bool:
        for payload in payloads:
            if payload.get("source") != "history":
                continue
            timestamp = self._activity_payload_timestamp(payload)
            if timestamp is None:
                continue
            if (datetime.now(OSLO_TIMEZONE) - timestamp).total_seconds() <= 600:
                return True
        return False

    def _activity_payloads(
        self,
        *,
        sync_status: SyncStatusResponse,
        analysis_status: AnalysisStatusResponse,
        health: HealthResponse,
        captured_at: datetime,
    ) -> list[dict[str, Any]]:
        active_job = self._activity_active_job(sync_status=sync_status, analysis_status=analysis_status)
        payloads: list[dict[str, Any]] = [
            {
                "source": "current",
                "timestamp": captured_at.isoformat(),
                "project_name": self._activity_current_project_name(
                    sync_status=sync_status,
                    analysis_status=analysis_status,
                    payloads=[],
                ),
                "component": None,
                "message": self._activity_default_status_for_state(
                    self._activity_state(sync_status=sync_status, analysis_status=analysis_status, payloads=[])[0]
                ),
                "state": self._activity_state(sync_status=sync_status, analysis_status=analysis_status, payloads=[])[0],
                "level": "INFO",
                "sync_status": sync_status.status,
                "analysis_status": analysis_status.status,
                "status": analysis_status.status,
                "job_type": active_job.job_type if active_job else None,
                "job_id": active_job.job_id if active_job else None,
                "run_mode": active_job.run_mode if active_job else "unknown",
                "event_code": active_job.event_code if active_job else None,
                "current_phase": active_job.current_phase if active_job else None,
                "current_project": active_job.current_project if active_job else None,
                "progress": active_job.progress if active_job else None,
                "sync_strategy": active_job.sync_strategy if isinstance(active_job, SyncStatusResponse) else "unknown",
                "sync_strategy_reason": active_job.sync_strategy_reason if isinstance(active_job, SyncStatusResponse) else None,
                "category": "Sync" if isinstance(active_job, SyncStatusResponse) else "Analysis" if isinstance(active_job, AnalysisStatusResponse) else "System",
                "semantic_source": "Sync" if isinstance(active_job, SyncStatusResponse) else "Analysis" if isinstance(active_job, AnalysisStatusResponse) else "System",
                "health": {
                    "appliance_available": health.appliance_available,
                    "backend_version": health.version,
                },
            }
        ]
        payloads.extend(self._read_activity_journal_payloads())
        payloads.extend(self._read_activity_history_payloads())
        return payloads

    def _read_activity_journal_payloads(self) -> list[dict[str, Any]]:
        path = self._activity_journal_path()
        if not path.exists() or not path.is_file():
            return []
        payloads: list[dict[str, Any]] = []
        for raw_line in self._tail_lines(path, ACTIVITY_JOURNAL_LINES_LIMIT):
            try:
                payload = json.loads(raw_line)
            except Exception:
                continue
            if isinstance(payload, dict):
                payload.setdefault("source", "journal")
                payloads.append(payload)
        return payloads

    def _read_activity_history_payloads(self) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for history_path in self._report_history_paths():
            for raw_line in self._tail_lines(history_path, ACTIVITY_HISTORY_LINES_LIMIT):
                try:
                    payload = json.loads(raw_line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    payload.setdefault("source", "history")
                    payloads.append(payload)
        return payloads

    def _activity_candidates_from_payloads(self, payloads: list[dict[str, Any]], *, verbose: bool) -> list[ActivityEntryCandidate]:
        candidates: list[ActivityEntryCandidate] = []
        order = 0
        for payload in payloads:
            payload_candidates = self._activity_candidates_from_payload(payload, verbose=verbose, order_start=order)
            candidates.extend(payload_candidates)
            order += len(payload_candidates) + 1
        return self._dedupe_activity_candidates(candidates)

    def _activity_candidates_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        verbose: bool,
        order_start: int,
    ) -> list[ActivityEntryCandidate]:
        details = payload.get("details")
        if isinstance(details, Mapping):
            payload = {**details, **payload}
        source = str(payload.get("source") or "history").casefold()
        timestamp = self._activity_payload_timestamp(payload) or datetime.now(OSLO_TIMEZONE)
        project_name = self._activity_payload_project_name(payload)
        component = self._activity_payload_component(payload)
        level = str(payload.get("level") or "INFO").upper()
        structured = self._activity_structured_fields(payload, level=level)
        candidates: list[ActivityEntryCandidate] = []

        if source == "current":
            return candidates

        if source == "journal":
            message = str(payload.get("message") or "").strip()
            if not message:
                return candidates
            if not verbose and str(payload.get("kind") or "").strip().lower() == "log":
                level = str(payload.get("level") or "INFO").upper()
            candidates.append(
                ActivityEntryCandidate(
                    timestamp=timestamp,
                    level=level if level in {"INFO", "SUCCESS", "WARNING", "ERROR"} else "INFO",
                    message=message,
                    project_name=project_name,
                    component=component,
                    order=order_start,
                    kind=str(payload.get("kind") or ("log" if verbose else "event")),
                    **structured,
                )
            )
            return candidates

        return self._activity_candidates_from_history_payload(payload, verbose=verbose, order_start=order_start)

    def _activity_candidates_from_history_payload(
        self,
        payload: Mapping[str, Any],
        *,
        verbose: bool,
        order_start: int,
    ) -> list[ActivityEntryCandidate]:
        details = payload.get("details")
        if isinstance(details, Mapping):
            payload = {**details, **payload}
        timestamp = self._activity_payload_timestamp(payload) or datetime.now(OSLO_TIMEZONE)
        project_name = self._activity_payload_project_name(payload)
        component = self._activity_payload_component(payload)
        status = str(payload.get("status") or "").casefold()
        structured = self._activity_structured_fields(payload, level=str(payload.get("level") or "INFO").upper())
        warnings = self._dedupe_messages(self._payload_messages(payload, "warnings"))
        errors = self._dedupe_messages(self._payload_messages(payload, "errors"))
        uploaded_reports = payload.get("uploaded_reports") if isinstance(payload.get("uploaded_reports"), list) else []
        reports_generated = _parse_int(payload.get("reports_generated"), len(uploaded_reports))
        files_changed = _parse_int(
            payload.get("files_changed"),
            _parse_int(payload.get("total_changed_files"), _parse_int(payload.get("downloaded_files"), 0)),
        )

        candidates: list[ActivityEntryCandidate] = []

        def add(level: ActivityLevel, message: str, *, offset: int, kind: str = "event", component_override: str | None = None) -> None:
            if not message.strip():
                return
            candidate_fields = dict(structured)
            if level == "ERROR":
                candidate_fields["category"] = "Error"
                candidate_fields["source"] = "Error"
            elif component_override in {"OneDrive", "Microsoft Graph"}:
                candidate_fields["category"] = "OneDrive"
                candidate_fields["source"] = "OneDrive"
            elif component_override in {"Reports", "Report"}:
                candidate_fields["category"] = "Report"
                candidate_fields["source"] = "Report"
            candidates.append(
                ActivityEntryCandidate(
                    timestamp=timestamp,
                    level=level,
                    message=message.strip(),
                    project_name=project_name,
                    component=component_override or component,
                    order=order_start + offset,
                    kind=kind,
                    **candidate_fields,
                )
            )

        if status in {"failed", "error"}:
            error_message = self._payload_error_message(payload) or "Operasjonen feilet."
            add("ERROR", error_message, offset=0, kind="error", component_override=component or structured["source"])
            return candidates

        if verbose:
            if files_changed > 0:
                add("SUCCESS", f"Downloaded {files_changed} files", offset=0, kind="log", component_override="OneDrive")
            if status in {"completed", "completed_with_warnings", "success"} or reports_generated > 0 or uploaded_reports:
                add("INFO", "Running OCR", offset=1, kind="log", component_override="Analysis")
            if reports_generated > 0 or uploaded_reports:
                add("SUCCESS", "Generated report", offset=2, kind="log", component_override="Reports")
                if uploaded_reports:
                    add("INFO", "Upload completed", offset=3, kind="log", component_override="OneDrive")
            if self._payload_has_email_signal(payload):
                add("SUCCESS", "Email sent", offset=4, kind="log", component_override="E-post")
        else:
            if files_changed > 0:
                add("SUCCESS", f"Finished sync ({files_changed} files changed)", offset=0, component_override="OneDrive")
            if reports_generated > 0 or uploaded_reports:
                add("SUCCESS", "Generated report", offset=1, component_override="Reports")
            elif status in {"completed", "completed_with_warnings", "success"}:
                add("SUCCESS", "Finished sync", offset=1, component_override="OneDrive")
            if self._payload_has_email_signal(payload):
                add("INFO", "Email sent", offset=2, component_override="E-post")

        for index, warning in enumerate(warnings, start=10):
            add("WARNING", warning, offset=index, kind="warning", component_override=component or structured["source"])
        for index, error in enumerate(errors, start=20):
            add("ERROR", error, offset=index, kind="error", component_override=component or structured["source"])

        return candidates

    def _activity_candidates_to_events(self, candidates: list[ActivityEntryCandidate], *, limit: int) -> list[ActivityEvent]:
        events: list[ActivityEvent] = []
        for candidate in self._sort_activity_candidates(candidates, limit=limit):
            if self._is_activity_noise(candidate.message):
                continue
            events.append(
                ActivityEvent(
                    timestamp=candidate.timestamp,
                    level=candidate.level,
                    project_name=candidate.project_name,
                    component=candidate.component,
                    message=candidate.message,
                    category=candidate.category,  # type: ignore[arg-type]
                    source=candidate.source,
                    event_code=candidate.event_code,
                    phase=candidate.phase,
                    run_mode=candidate.run_mode,  # type: ignore[arg-type]
                    job_type=candidate.job_type,  # type: ignore[arg-type]
                    job_id=candidate.job_id,
                )
            )
        return events

    def _activity_candidates_to_errors(self, candidates: list[ActivityEntryCandidate], *, limit: int) -> list[ActivityError]:
        errors: list[ActivityError] = []
        for candidate in self._sort_activity_candidates(candidates, limit=limit):
            if candidate.level != "ERROR":
                continue
            if not self._is_meaningful_activity_error(candidate.message):
                continue
            errors.append(
                ActivityError(
                    timestamp=candidate.timestamp,
                    project_name=candidate.project_name,
                    component=candidate.component,
                    message=candidate.message,
                    source=candidate.source,
                    event_code=candidate.event_code,
                    phase=candidate.phase,
                    run_mode=candidate.run_mode,  # type: ignore[arg-type]
                    job_type=candidate.job_type,  # type: ignore[arg-type]
                    job_id=candidate.job_id,
                )
            )
        return errors

    def _activity_candidates_to_logs(self, candidates: list[ActivityEntryCandidate], *, limit: int) -> list[ActivityLogEntry]:
        logs: list[ActivityLogEntry] = []
        for candidate in self._sort_activity_candidates(candidates, limit=limit):
            if self._is_activity_noise(candidate.message):
                continue
            logs.append(
                ActivityLogEntry(
                    timestamp=candidate.timestamp,
                    level=candidate.level,
                    project_name=candidate.project_name,
                    component=candidate.component,
                    message=candidate.message,
                    category=candidate.category,  # type: ignore[arg-type]
                    source=candidate.source,
                    event_code=candidate.event_code,
                    phase=candidate.phase,
                    run_mode=candidate.run_mode,  # type: ignore[arg-type]
                    job_type=candidate.job_type,  # type: ignore[arg-type]
                    job_id=candidate.job_id,
                )
            )
        return logs

    def _sort_activity_candidates(self, candidates: list[ActivityEntryCandidate], *, limit: int) -> list[ActivityEntryCandidate]:
        deduped = self._dedupe_activity_candidates(candidates)
        deduped.sort(key=lambda candidate: (candidate.timestamp, candidate.order), reverse=True)
        return deduped[:limit]

    def _dedupe_activity_candidates(self, candidates: list[ActivityEntryCandidate]) -> list[ActivityEntryCandidate]:
        deduped: list[ActivityEntryCandidate] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for candidate in candidates:
            key = (
                candidate.timestamp.isoformat(),
                candidate.level,
                (candidate.project_name or "").casefold(),
                (candidate.component or "").casefold(),
                candidate.message.casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _activity_journal_path(self) -> Path:
        return self.settings.resolved_appliance_root() / "cache" / ACTIVITY_JOURNAL_FILENAME

    def _write_activity_journal(
        self,
        *,
        level: ActivityLevel,
        message: str,
        project_name: str | None = None,
        component: str | None = None,
        kind: str = "log",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(OSLO_TIMEZONE).isoformat(),
            "level": level,
            "message": message,
            "project_name": project_name,
            "component": component,
            "kind": kind,
        }
        if details:
            normalized_details = dict(details)
            payload["details"] = normalized_details
            for key in (
                "job_id",
                "job_type",
                "requested_by",
                "requested_at",
                "current_phase",
                "current_project",
                "progress",
                "process_id",
                "appliance_run_id",
                "run_mode",
                "event_code",
                "sync_strategy",
                "phase",
                "category",
                "semantic_source",
            ):
                if key in normalized_details:
                    payload[key] = normalized_details[key]

        path = self._activity_journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False)
        with self._activity_journal_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.write("\n")
        self._invalidate_activity_cache()

    def _tail_lines(self, path: Path, limit: int) -> list[str]:
        if limit <= 0 or not path.exists() or not path.is_file():
            return []
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                remaining = handle.tell()
                chunks: list[bytes] = []
                newline_count = 0
                while remaining > 0 and newline_count <= limit:
                    read_size = min(4096, remaining)
                    remaining -= read_size
                    handle.seek(remaining)
                    chunk = handle.read(read_size)
                    chunks.append(chunk)
                    newline_count += chunk.count(b"\n")
                data = b"".join(reversed(chunks))
            return data.decode("utf-8", errors="replace").splitlines()[-limit:]
        except Exception as exc:
            logger.warning("Unable to tail file %s: %s", path, exc)
            return []

    def _payload_messages(self, payload: Mapping[str, Any], key: str) -> list[str]:
        values = payload.get(key)
        if not isinstance(values, list):
            return []
        messages: list[str] = []
        for value in values:
            if isinstance(value, str):
                messages.append(value)
            elif isinstance(value, Mapping):
                message = str(value.get("message") or value.get("detail") or value.get("text") or "").strip()
                if message:
                    messages.append(message)
        return messages

    def _payload_error_message(self, payload: Mapping[str, Any]) -> str | None:
        for key in ("last_error", "error", "message", "detail"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        errors = self._payload_messages(payload, "errors")
        if errors:
            return errors[-1]
        warnings = self._payload_messages(payload, "warnings")
        if warnings:
            return warnings[-1]
        return None

    def _payload_has_email_signal(self, payload: Mapping[str, Any]) -> bool:
        values = (
            str(payload.get("email_mode") or "").strip(),
            str(payload.get("email_status") or "").strip(),
            str(payload.get("message") or "").strip(),
        )
        lowered = " ".join(values).casefold()
        return "email" in lowered or "e-post" in lowered

    def _activity_payload_timestamp(self, payload: Mapping[str, Any]) -> datetime | None:
        for key in (
            "timestamp",
            "started_at",
            "start_requested_at",
            "last_started_at",
            "last_completed_at",
            "finished_at",
            "completed_at",
            "generated_at",
            "created_at",
            "updated_at",
        ):
            timestamp = _parse_datetime(str(payload.get(key) or "").strip())
            if timestamp is not None:
                return timestamp
        report_snapshot = payload.get("report_snapshot")
        if isinstance(report_snapshot, Mapping):
            for key in ("generated_at", "finished_at", "created_at"):
                timestamp = _parse_datetime(str(report_snapshot.get(key) or "").strip())
                if timestamp is not None:
                    return timestamp
        analysis_snapshot = payload.get("analysis_snapshot")
        if isinstance(analysis_snapshot, Mapping):
            for key in ("generated_at", "finished_at", "created_at"):
                timestamp = _parse_datetime(str(analysis_snapshot.get(key) or "").strip())
                if timestamp is not None:
                    return timestamp
        return None

    def _activity_payload_project_name(self, payload: Mapping[str, Any]) -> str | None:
        for key in ("project_name", "project", "root_folder_name"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        report_snapshot = payload.get("report_snapshot")
        if isinstance(report_snapshot, Mapping):
            value = str(report_snapshot.get("project_name") or "").strip()
            if value:
                return value
        analysis_snapshot = payload.get("analysis_snapshot")
        if isinstance(analysis_snapshot, Mapping):
            value = str(analysis_snapshot.get("project_name") or "").strip()
            if value:
                return value
        return None

    def _activity_payload_component(self, payload: Mapping[str, Any]) -> str | None:
        for key in ("component", "stage"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return None

    def _activity_structured_fields(self, payload: Mapping[str, Any], *, level: str) -> dict[str, Any]:
        details = payload.get("details")
        if isinstance(details, Mapping):
            payload = {**details, **payload}
        raw_run_mode = str(payload.get("run_mode") or payload.get("activity") or "").strip().casefold()
        if raw_run_mode in {"sync_only", "sync", "synchronization", "synchronisation"}:
            run_mode = "sync_only"
            job_type = "sync"
        elif raw_run_mode in {"analysis", "analyse"}:
            run_mode = "analysis"
            job_type = "analysis"
        else:
            run_mode = "unknown"
            job_type_value = str(payload.get("job_type") or "").strip().casefold()
            job_type = job_type_value if job_type_value in {"sync", "analysis"} else None

        explicit_category = str(payload.get("category") or "").strip()
        component = self._activity_payload_component(payload)
        if level == "ERROR":
            category = "Error"
        elif explicit_category in {"Sync", "Analysis", "System", "OneDrive", "Report", "Error"}:
            category = explicit_category
        elif job_type == "sync":
            category = "Sync"
        elif job_type == "analysis":
            category = "Analysis"
        elif component in {"OneDrive", "Microsoft Graph"}:
            category = "OneDrive"
        elif component in {"Analysis", "Analyse", "OCR"}:
            category = "Analysis"
        elif component in {"Reports", "Report"}:
            category = "Report"
        else:
            category = "System"

        semantic_source = str(
            payload.get("semantic_source")
            or payload.get("source_label")
            or payload.get("event_source")
            or ""
        ).strip()
        allowed_sources = {"Sync", "Analysis", "System", "OneDrive", "Report", "Nexus", "Error"}
        if semantic_source not in allowed_sources:
            semantic_source = "Nexus" if str(payload.get("source") or "").strip() == "journal" and category == "System" else category

        return {
            "category": category,
            "source": semantic_source,
            "event_code": self._payload_text(payload, "event_code", "code"),
            "phase": self._payload_text(payload, "phase", "current_phase", "stage"),
            "run_mode": run_mode,
            "job_type": job_type,
            "job_id": self._payload_text(payload, "job_id"),
        }

    def _infer_component(self, message: str | None) -> str | None:
        lowered = str(message or "").casefold()
        if not lowered:
            return None
        if "openai" in lowered or "gpt" in lowered or "llm" in lowered:
            return "OpenAI"
        if "graph" in lowered or "microsoft" in lowered:
            return "Microsoft Graph"
        if "smtp" in lowered or "email" in lowered or "e-post" in lowered:
            return "E-post"
        if "ocr" in lowered or "analysis" in lowered or "analyse" in lowered or "rapport" in lowered:
            return "Analyse"
        if "onedrive" in lowered or "sync" in lowered:
            return "OneDrive"
        if "backend" in lowered or "nexus" in lowered:
            return "Backend"
        return None

    def _is_activity_noise(self, message: str | None) -> bool:
        lowered = str(message or "").casefold()
        if not lowered.strip():
            return True
        return any(pattern in lowered for pattern in (*ACTIVITY_LOG_NOISE_PATTERNS, *ACTIVITY_LOCK_NOISE_PATTERNS))

    def _is_meaningful_activity_error(self, message: str | None) -> bool:
        lowered = str(message or "").casefold()
        if not lowered.strip():
            return False
        if any(pattern in lowered for pattern in ACTIVITY_LOCK_NOISE_PATTERNS):
            return False
        if any(pattern in lowered for pattern in ACTIVITY_LOG_NOISE_PATTERNS):
            return False
        return True

    def _activity_latest_message_from_payloads(self, payloads: list[dict[str, Any]]) -> str | None:
        for payload in reversed(payloads):
            message = str(payload.get("message") or "").strip()
            if message and not self._is_activity_noise(message):
                return message
            error_message = self._payload_error_message(payload)
            if error_message:
                return error_message
        return None

    def list_projects(self, *, include_local_cache: bool = False) -> ProjectListResponse:
        records = self.discover_projects(include_local_cache=include_local_cache)
        projects = [
            ProjectSummary(
                display_name=record.display_name,
                source_label=record.source_label,
                relative_project_path=record.relative_project_path,
                hidden_internal_path=record.hidden_internal_path,
                last_synced_at=record.last_synced_at,
                latest_comment_document=record.latest_comment_document,
                latest_comment_document_open_url=record.latest_comment_document_open_url,
                latest_comment_created_at=record.latest_comment_created_at,
                latest_comment_modified_at=record.latest_comment_modified_at,
                comment_document_count=record.comment_document_count,
                is_sample_project=record.is_sample_project,
                is_local_cache_only=record.is_local_cache_only,
                project_name=record.project_name,
                project_path=record.project_path,
                last_analyzed_at=record.last_analyzed_at,
                status=record.status,
                file_count=record.file_count,
                report_count=record.report_count,
                warnings=record.warnings,
                errors=record.errors,
            )
            for record in records
        ]
        warnings = self._collect_global_warnings(records)
        projects = [item.model_copy(update=self.memory.latest_summary(record)) for item, record in zip(projects, records)]
        return ProjectListResponse(count=len(projects), projects=projects, warnings=warnings)

    def get_project(self, project_name: str) -> ProjectDetailResponse:
        record = self._get_project_record(project_name)
        detail = ProjectDetailResponse(
            display_name=record.display_name,
            source_label=record.source_label,
            relative_project_path=record.relative_project_path,
            hidden_internal_path=record.hidden_internal_path,
            last_synced_at=record.last_synced_at,
            latest_comment_document=record.latest_comment_document,
            latest_comment_document_open_url=record.latest_comment_document_open_url,
            latest_comment_created_at=record.latest_comment_created_at,
            latest_comment_modified_at=record.latest_comment_modified_at,
            comment_document_count=record.comment_document_count,
            is_sample_project=record.is_sample_project,
            is_local_cache_only=record.is_local_cache_only,
            project_name=record.project_name,
            project_path=record.project_path,
            last_analyzed_at=record.last_analyzed_at,
            status=record.status,
            file_count=record.file_count,
            report_count=record.report_count,
            warnings=record.warnings,
            errors=record.errors,
            analysis=record.analysis,
            reports=record.reports,
        )
        return detail.model_copy(update=self.memory.latest_summary(record))

    def list_reports(self, project_name: str) -> ProjectReportsResponse:
        record = self._get_project_record(project_name, load_files=False)
        reports, warnings, errors = self._load_reports(
            record.project_path,
            project_name=record.project_name,
            relative_project_path=record.relative_project_path,
            is_sample_project=record.is_sample_project,
        )
        return ProjectReportsResponse(
            display_name=record.display_name,
            source_label=record.source_label,
            relative_project_path=record.relative_project_path,
            hidden_internal_path=record.hidden_internal_path,
            last_synced_at=record.last_synced_at,
            latest_comment_document=record.latest_comment_document,
            latest_comment_document_open_url=record.latest_comment_document_open_url,
            latest_comment_created_at=record.latest_comment_created_at,
            latest_comment_modified_at=record.latest_comment_modified_at,
            comment_document_count=record.comment_document_count,
            is_sample_project=record.is_sample_project,
            is_local_cache_only=record.is_local_cache_only,
            project_name=record.project_name,
            project_path=record.project_path,
            count=len(reports),
            reports=reports,
            warnings=warnings or record.warnings,
            errors=errors or record.errors,
        )

    def open_report(self, project_name: str, report_id: str) -> ProjectReport:
        record = self._get_project_record(project_name, load_files=False)
        report = self._select_report(record.reports, report_id)
        report_path = report.report_path.expanduser().resolve(strict=True)

        if report_path.suffix.lower() not in OPENABLE_REPORT_SUFFIXES:
            raise ProjectReportNotFoundError(f"Report not found: {report_id}")

        allowed_roots = self._allowed_report_roots(record)
        if not allowed_roots or not any(report_path.is_relative_to(root) for root in allowed_roots):
            raise ProjectReportNotFoundError(f"Report not found: {report_id}")

        return report.model_copy(update={"report_path": report_path})

    def resolve_project_file(self, project_name: str, relative_path: str) -> tuple[Path, str]:
        record = self._get_project_record(project_name, load_files=True, load_reports=False)
        normalized_path = self._normalize_project_relative_path(relative_path)
        source_scan = record.source_scan or self._inspect_source_files(record.project_path, state_path=record.state_path)
        candidate_files = list(source_scan.source_files)
        matching_file = next((item for item in candidate_files if self._normalize_project_relative_path(item.relative_path) == normalized_path), None)
        if matching_file is None:
            raise ProjectFileNotFoundError(f"File not found: {relative_path}")

        try:
            resolved_file = matching_file.absolute_path.expanduser().resolve(strict=True)
        except Exception:
            resolved_file = self._download_project_file_to_temporary_cache(record, matching_file, normalized_path)

        allowed_roots = self._allowed_file_roots(record) + [self._temporary_file_cache_root()]
        if not allowed_roots or not any(resolved_file.is_relative_to(root) for root in allowed_roots):
            raise ProjectFileNotFoundError(f"File not found: {relative_path}")

        return resolved_file, Path(normalized_path).name

    def _temporary_file_cache_root(self) -> Path:
        return self.settings.resolved_appliance_root() / ".riveanbud_runtime" / "urn-nexus-temp-files"

    def _cleanup_temporary_file_cache(self, *, ttl_seconds: int = 1800) -> None:
        from time import time

        root = self._temporary_file_cache_root()
        if not root.exists():
            return

        cutoff = time() - ttl_seconds
        for candidate in root.rglob("*"):
            try:
                if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                    candidate.unlink(missing_ok=True)
            except Exception:
                logger.warning("Unable to remove expired temporary Nexus file: %s", candidate)

        for folder in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass

    def _download_project_file_to_temporary_cache(self, record: ProjectRecord, file_record: SourceFileRecord, normalized_path: str) -> Path:
        remote_item_id = (file_record.remote_item_id or "").strip()
        if not remote_item_id:
            raise ProjectFileNotFoundError(f"File is not available in local cache and has no OneDrive item id: {normalized_path}")

        self._cleanup_temporary_file_cache()

        cache_root = self._temporary_file_cache_root()
        safe_project = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in record.project_name)
        target = (cache_root / safe_project / normalized_path).expanduser().resolve(strict=False)

        cache_root_resolved = cache_root.expanduser().resolve(strict=False)
        if not target.is_relative_to(cache_root_resolved):
            raise ProjectFileNotFoundError(f"Invalid temporary cache path: {normalized_path}")

        if target.exists():
            return target.resolve(strict=True)

        target.parent.mkdir(parents=True, exist_ok=True)

        env = self._graph_write_env()
        missing = _missing_graph_write_env(env)
        if missing:
            raise ProjectFileNotFoundError("Microsoft Graph is not configured for file download. Missing: " + ", ".join(missing))

        appliance_root = self.settings.resolved_appliance_root()
        previous_env: dict[str, str | None] = {key: os.environ.get(key) for key in env}
        os.environ.update(env)

        try:
            if str(appliance_root) not in sys.path:
                sys.path.insert(0, str(appliance_root))

            from app.integrations.onedrive.client import OneDriveClient, OneDriveClientError, _load_requests_module

            client = OneDriveClient.from_env(env=env)
            requests = _load_requests_module()
            access_token = client.get_access_token()
            download_url = f"https://graph.microsoft.com/v1.0/users/{client.config.onedrive_user}/drive/items/{remote_item_id}/content"

            response = requests.get(
                download_url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=180,
                stream=True,
            )
            response.raise_for_status()

            temporary_target = target.with_suffix(target.suffix + ".download")
            with temporary_target.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
            temporary_target.replace(target)
            return target.resolve(strict=True)
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise ProjectFileNotFoundError(f"Could not download file from OneDrive: {normalized_path}") from exc
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


    def list_files(self, project_name: str) -> ProjectFilesResponse:
        record = self._get_project_record(project_name, load_reports=False)
        source_files, warnings, errors = self._scan_source_files(record.project_path, state_path=record.state_path)
        tree = self._build_file_tree(record.project_name, source_files)
        filters = self._build_file_filters(source_files)
        return ProjectFilesResponse(
            display_name=record.display_name,
            source_label=record.source_label,
            relative_project_path=record.relative_project_path,
            hidden_internal_path=record.hidden_internal_path,
            last_synced_at=record.last_synced_at,
            latest_comment_document=record.latest_comment_document,
            latest_comment_document_open_url=record.latest_comment_document_open_url,
            latest_comment_created_at=record.latest_comment_created_at,
            latest_comment_modified_at=record.latest_comment_modified_at,
            comment_document_count=record.comment_document_count,
            is_sample_project=record.is_sample_project,
            is_local_cache_only=record.is_local_cache_only,
            project_name=record.project_name,
            project_path=record.project_path,
            total_files=len(source_files),
            file_tree=tree,
            filters=filters,
            warnings=record.warnings + warnings,
            errors=record.errors + errors,
        )

    def upload_file(self, project_name: str, filename: str, content: bytes, *, target_folder: str | None = None) -> FileUploadResponse:
        if not filename or Path(filename).name != filename:
            raise ProjectWriteError("Invalid upload filename.")
        target_folder_normalized = self._normalize_project_relative_path(target_folder or "")
        record = self._get_project_record(project_name, load_files=False, load_reports=False)
        writer = self._onedrive_project_writer()
        writer.upload_file(
            record.project_name,
            filename,
            content,
            parent_remote_path=self.settings.onedrive_project_root(),
            target_folder=target_folder_normalized or None,
        )
        relative_path = Path(target_folder_normalized, filename).as_posix() if target_folder_normalized else filename
        return FileUploadResponse(
            project_name=record.project_name,
            filename=filename,
            target_folder=target_folder_normalized,
            relative_path=relative_path,
            size_bytes=len(content),
            mode="onedrive",
            warning=None,
        )

    def create_project_folder(self, project_name: str, folder_name: str, *, target_folder: str | None = None) -> FolderCreateResponse:
        cleaned_folder_name = self._clean_folder_name(folder_name)
        target_folder_normalized = self._normalize_project_relative_path(target_folder or "")
        record = self._get_project_record(project_name, load_files=False, load_reports=False)
        writer = self._onedrive_project_writer()
        writer.create_project_folder(
            record.project_name,
            cleaned_folder_name,
            parent_remote_path=self.settings.onedrive_project_root(),
            target_folder=target_folder_normalized or None,
        )
        relative_path = Path(target_folder_normalized, cleaned_folder_name).as_posix() if target_folder_normalized else cleaned_folder_name
        return FolderCreateResponse(
            project_name=record.project_name,
            folder_name=cleaned_folder_name,
            target_folder=target_folder_normalized,
            relative_path=relative_path,
            mode="onedrive",
            warning=None,
        )

    def create_project(self, project_name: str, *, folders: list[str] | None = None) -> ProjectCreateResponse:
        cleaned_name = self._clean_project_name(project_name)
        folder_names = self._project_template_folders(folders)
        writer = self._onedrive_project_writer()
        self._require_sync_only_available()
        created = writer.create_project(
            cleaned_name,
            folders=folder_names,
            parent_remote_path=self.settings.onedrive_project_root(),
        )
        self._unhide_project(cleaned_name)
        self._run_sync_for_project(cleaned_name)
        refreshed = self.discover_projects()
        if not any(_normalize_name(record.project_name) == _normalize_name(cleaned_name) for record in refreshed):
            raise ProjectSyncError(
                f"Prosjektet '{cleaned_name}' ble opprettet i OneDrive, men Nexus fant det ikke i lokal OneDrive-cache etter sync."
            )

        return ProjectCreateResponse(
            project_name=cleaned_name,
            relative_project_path=f"Urban_Reuse_Norway/{cleaned_name}",
            mode="onedrive",
            folders_created=created,
            warning=None,
        )

    def delete_project(self, project_name: str) -> ProjectDeleteResponse:
        cleaned_name = self._clean_project_name(project_name)
        self._require_sync_only_available()
        writer = self._onedrive_project_writer()
        try:
            deleted_result = writer.delete_project(
                cleaned_name,
                parent_remote_path=self.settings.onedrive_project_root(),
            )
        except ProjectWriteError:
            raise
        except Exception as exc:
            raise ProjectWriteError(f"Microsoft Graph-delete feilet: {exc}") from exc
        if isinstance(deleted_result, tuple):
            deleted_remote_path, existed = deleted_result
        else:
            deleted_remote_path = str(deleted_result)
            existed = True
        self._hide_project(cleaned_name)
        self._run_sync_for_project(None)
        refreshed = self.discover_projects()
        if any(_normalize_name(record.project_name) == _normalize_name(cleaned_name) for record in refreshed):
            raise ProjectSyncError(
                f"Prosjektet '{cleaned_name}' ble slettet i OneDrive, men Nexus fant det fortsatt i lokal OneDrive-cache etter sync."
            )
        return ProjectDeleteResponse(
            project_name=cleaned_name,
            deleted_remote_path=deleted_remote_path,
            deleted=True,
            existed=existed,
            synced=True,
            message="Prosjektet finnes ikke lenger i OneDrive." if not existed else "Prosjektet ble slettet fra OneDrive.",
        )

    def delete_project_local_cache(self, project_name: str) -> ProjectLocalCacheDeleteResponse:
        cleaned_name = self._clean_project_name(project_name)
        normalized = _normalize_name(cleaned_name)
        self._hide_project(cleaned_name)

        removed_paths: list[str] = []
        removed_state_rows = 0
        appliance_root = self.settings.resolved_appliance_root()
        candidate_paths: list[Path] = [
            appliance_root / LOCAL_PROJECTS_RELATIVE_ROOT / cleaned_name,
            appliance_root / LOCAL_UPLOADS_RELATIVE_ROOT / cleaned_name,
            appliance_root / "outputs" / "Urban_Reuse_Norway" / cleaned_name,
        ]

        for database_path in self._state_database_paths():
            deleted_rows, row_paths = self._delete_project_state_rows(database_path, normalized)
            removed_state_rows += deleted_rows
            candidate_paths.extend(row_paths)

        allowed_roots = self._local_cache_delete_roots()
        for candidate_path in candidate_paths:
            removed = self._remove_local_cache_path(candidate_path, allowed_roots=allowed_roots)
            if removed is not None and removed not in removed_paths:
                removed_paths.append(removed)

        return ProjectLocalCacheDeleteResponse(
            project_name=cleaned_name,
            hidden=True,
            removed_paths=removed_paths,
            removed_state_rows=removed_state_rows,
        )

    def _onedrive_project_writer(self) -> OneDriveProjectWriter:
        if self._onedrive_writer_override is not None:
            return self._onedrive_writer_override
        return ApplianceOneDriveProjectWriter.from_settings(self.settings)

    def _run_sync_for_project(self, project_name: str | None) -> None:
        self._require_sync_only_available()
        command = self._sync_command(project_name=project_name)
        self._validate_nexus_sync_command(command)
        try:
            result = subprocess.run(
                command,
                cwd=self._appliance_repo_root(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=float(os.getenv("URN_NEXUS_PROJECT_CREATE_SYNC_TIMEOUT_SECONDS", "900")),
            )
        except subprocess.TimeoutExpired as exc:
            raise ProjectSyncError(f"OneDrive-sync brukte for lang tid etter prosjektopprettelse: {exc}") from exc
        except Exception as exc:
            raise ProjectSyncError(f"Kunne ikke kjøre OneDrive-sync etter prosjektopprettelse: {exc}") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "OneDrive-sync feilet.").strip()[-2000:]
            raise ProjectSyncError(f"OneDrive-sync feilet etter prosjektopprettelse: {detail}")

    def _job_details(self, state: NexusJobState) -> dict[str, Any]:
        return {
            "job_id": state.job_id,
            "job_type": state.job_type,
            "requested_by": state.requested_by,
            "requested_at": state.requested_at.isoformat() if state.requested_at else None,
            "status": state.status,
            "current_phase": state.current_phase,
            "current_project": state.current_project,
            "progress": state.progress,
            "process_id": state.process_id,
            "appliance_run_id": state.appliance_run_id,
            "run_mode": state.run_mode,
            "event_code": state.event_code,
            "sync_strategy_reason": state.sync_strategy_reason if isinstance(state, SyncJobState) else None,
        }

    def _sync_run_response(self, *, status: str | None = None, started_at: datetime | None = None) -> SyncRunResponse:
        state = self._sync_state
        return SyncRunResponse(
            job_id=state.job_id or "",
            running=state.running or state.status in {"startup_pending", "running"},
            started_at=started_at or state.last_started_at or state.requested_at or datetime.now(OSLO_TIMEZONE),
            status=status or state.status,
            sync_only=True,
            analysis_started=False,
            reports_generated=0,
            projects_synced=state.projects_synced,
            files_changed=state.files_changed,
            reports_found=state.reports_found,
            requested_by=state.requested_by,
            requested_at=state.requested_at,
            current_phase=state.current_phase,
            current_project=state.current_project,
            progress=state.progress,
            process_id=state.process_id,
            appliance_run_id=state.appliance_run_id,
            run_mode="sync_only",
            event_code=state.event_code,
            sync_strategy=state.sync_strategy,  # type: ignore[arg-type]
            sync_strategy_reason=state.sync_strategy_reason,
            remote_items_examined=state.remote_items_examined,
            files_downloaded=state.files_downloaded,
            files_deleted=state.files_deleted,
            elapsed_seconds=state.elapsed_seconds,
            performance=state.performance,
        )

    def start_sync(
        self,
        *,
        project_name: str | None = None,
        requested_by: str = "nexus-web",
        idempotency_key: str | None = None,
    ) -> SyncRunResponse:
        with self._sync_lock, self._analysis_lock:
            snapshot = self._runtime_activity_snapshot_locked()
            self._refresh_sync_state_locked(snapshot=snapshot)
            self._refresh_analysis_state_locked(snapshot=snapshot)
            if (
                idempotency_key
                and self._last_sync_idempotency_key == idempotency_key
                and self._sync_state.job_id
                and self._sync_state.status in {"startup_pending", "running"}
            ):
                return self._sync_run_response(status="already_running")
            if snapshot.sync_running or snapshot.analysis_running or snapshot.lock_exists:
                raise ApplianceBusyError(APPLIANCE_BUSY_MESSAGE)
            self._require_sync_only_available()

            normalized_project_name = self._clean_project_name(project_name) if project_name else None
            command = self._sync_command(project_name=normalized_project_name)
            self._validate_nexus_sync_command(command)
            started_at = datetime.now(OSLO_TIMEZONE)
            job_id = uuid4().hex
            self._sync_state = SyncJobState(
                job_id=job_id,
                requested_by=requested_by,
                requested_at=started_at,
                status="startup_pending",
                current_phase="Starter synkronisering",
                current_project=normalized_project_name,
                project_name=normalized_project_name,
                progress=0.0,
                event_code="sync_started",
                run_mode="sync_only",
            )
            self._last_sync_idempotency_key = idempotency_key
            try:
                process = subprocess.Popen(
                    command,
                    cwd=self._appliance_repo_root(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except Exception as exc:
                self._sync_state.last_error = str(exc)
                self._sync_state.status = "failed"
                self._sync_state.event_code = "sync_failed"
                self._sync_state.current_phase = "Synkronisering feilet"
                self._sync_state.last_completed_at = datetime.now(OSLO_TIMEZONE)
                self._write_activity_journal(
                    level="ERROR",
                    message=str(exc),
                    project_name=None,
                    component="OneDrive",
                    kind="error",
                    details=self._job_details(self._sync_state),
                )
                raise ProjectWriteError(f"Unable to start OneDrive sync: {exc}") from exc

            self._sync_state.running = True
            self._sync_state.process = process
            self._sync_state.process_id = getattr(process, "pid", None)
            self._sync_state.last_started_at = started_at
            self._sync_state.status = "running"
            self._sync_state.current_phase = "Kobler til OneDrive"
            self._write_activity_journal(
                level="INFO",
                message="Starting OneDrive sync",
                project_name=normalized_project_name,
                component="OneDrive",
                kind="log",
                details=self._job_details(self._sync_state),
            )
            threading.Thread(target=self._monitor_sync_process, args=(job_id, process), daemon=True).start()
            return self._sync_run_response(status="started", started_at=started_at)

    def start_analysis(self, project_name: str | None, *, email_mode: str = "daily_digest") -> AnalysisRunResponse:
        normalized_email_mode = self._normalize_email_mode(email_mode)
        normalized_project_name = self._clean_project_name(project_name) if project_name is not None else None

        with self._sync_lock, self._analysis_lock:
            snapshot = self._runtime_activity_snapshot_locked()
            self._refresh_sync_state_locked(snapshot=snapshot)
            self._refresh_analysis_state_locked(snapshot=snapshot)
            if snapshot.sync_running or snapshot.analysis_running or snapshot.lock_exists:
                raise ApplianceBusyError(APPLIANCE_BUSY_MESSAGE)
            self._require_analysis_available()

            command = self._analysis_command(project_name=normalized_project_name, email_mode=normalized_email_mode)
            self._validate_nexus_analysis_command(command)
            started_at = datetime.now(OSLO_TIMEZONE)
            job_id = uuid4().hex
            self._analysis_state = AnalysisJobState(
                job_id=job_id,
                requested_by="nexus-web",
                requested_at=started_at,
                start_requested_at=started_at,
                last_started_at=started_at,
                process_spawned=False,
                auth_status="unknown",
                last_error=None,
                last_start_error=None,
                status="startup_pending",
                current_phase="Starter analyse",
                current_project=normalized_project_name,
                progress=0.0,
                event_code="analysis_started",
                email_mode=normalized_email_mode,
                project_name=normalized_project_name,
            )
            self._write_activity_journal(
                level="INFO",
                message="Starting analysis",
                project_name=normalized_project_name,
                component="Analysis",
                kind="log",
                details=self._job_details(self._analysis_state) | {"email_mode": normalized_email_mode},
            )
            try:
                process = subprocess.Popen(
                    command,
                    cwd=self._appliance_repo_root(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except Exception as exc:
                error_text = str(exc)
                status, auth_status = _classify_analysis_error(error_text)
                self._analysis_state.running = False
                self._analysis_state.process_spawned = False
                self._analysis_state.last_error = error_text
                self._analysis_state.last_start_error = error_text
                self._analysis_state.last_completed_at = datetime.now(OSLO_TIMEZONE)
                self._analysis_state.auth_status = auth_status
                self._analysis_state.status = status
                self._analysis_state.event_code = "analysis_failed"
                self._write_activity_journal(
                    level="ERROR",
                    message=error_text,
                    project_name=normalized_project_name,
                    component="Analysis",
                    kind="error",
                    details=self._job_details(self._analysis_state),
                )
                raise AnalysisUnavailableError(f"Unable to start appliance analysis: {exc}") from exc

            self._analysis_state.process = process
            self._analysis_state.process_id = getattr(process, "pid", None)
            self._analysis_state.process_spawned = True
            threading.Thread(target=self._monitor_analysis_process, args=(job_id, process), daemon=True).start()
            return AnalysisRunResponse(
                job_id=job_id,
                running=True,
                started_at=started_at,
                status="started",
                analysis_started=True,
                reports_generated=0,
                projects_synced=0,
                files_changed=0,
                reports_found=0,
                email_mode=normalized_email_mode,
                project_name=normalized_project_name,
                requested_at=started_at,
                current_phase="Starter analyse",
                current_project=normalized_project_name,
                progress=0.0,
                process_id=getattr(process, "pid", None),
                run_mode="analysis",
                event_code="analysis_started",
            )

    def sync_status(self) -> SyncStatusResponse:
        with self._sync_lock, self._analysis_lock:
            snapshot = self._runtime_activity_snapshot_locked()
            self._refresh_sync_state_locked(snapshot=snapshot)
            self._clear_stale_lock_error(self._sync_state, label="sync")
            error_code = "sync_failed" if self._sync_state.status in {"failed", "error"} and self._sync_state.last_error else None
            sync_active = self._sync_state.status in {"startup_pending", "running"} or snapshot.sync_running
            return SyncStatusResponse(
                running=sync_active,
                process_alive=sync_active,
                lock_exists=snapshot.lock_exists,
                lock_stale=snapshot.lock_stale,
                activity="sync" if sync_active else "idle",
                job_id=self._sync_state.job_id,
                last_started_at=self._sync_state.last_started_at,
                last_completed_at=self._sync_state.last_completed_at,
                last_error=self._sync_state.last_error,
                error_code=error_code,
                projects_synced=self._sync_state.projects_synced,
                files_changed=self._sync_state.files_changed,
                reports_found=self._sync_state.reports_found,
                status=self._sync_state.status,
                requested_by=self._sync_state.requested_by,
                requested_at=self._sync_state.requested_at,
                current_phase=self._sync_state.current_phase,
                current_project=self._sync_state.current_project,
                progress=self._sync_state.progress,
                process_id=self._sync_state.process_id,
                appliance_run_id=self._sync_state.appliance_run_id,
                run_mode="sync_only",
                event_code=self._sync_state.event_code,
                sync_strategy=self._sync_state.sync_strategy,  # type: ignore[arg-type]
                sync_strategy_reason=self._sync_state.sync_strategy_reason,
                remote_items_examined=self._sync_state.remote_items_examined,
                files_downloaded=self._sync_state.files_downloaded,
                files_deleted=self._sync_state.files_deleted,
                elapsed_seconds=self._sync_state.elapsed_seconds,
                performance=self._sync_state.performance,
            )

    def analysis_status(self) -> AnalysisStatusResponse:
        with self._sync_lock, self._analysis_lock:
            snapshot = self._runtime_activity_snapshot_locked()
            self._refresh_analysis_state_locked(snapshot=snapshot)
            self._clear_stale_lock_error(self._analysis_state, label="analysis")
            now = datetime.now(OSLO_TIMEZONE)
            startup_grace_active = bool(
                self._analysis_state.start_requested_at
                and self._analysis_state.status == "startup_pending"
                and now < self._analysis_state.start_requested_at + timedelta(seconds=ANALYSIS_STARTUP_GRACE_SECONDS)
            )
            effective_running = self._analysis_state.running or snapshot.analysis_running
            effective_process_alive = self._is_process_active(self._analysis_state.process) or snapshot.analysis_running
            effective_activity = "analysis" if effective_running or self._analysis_state.status == "startup_pending" else "idle"
            if self._analysis_state.status == "startup_pending" or effective_running:
                effective_activity = "analysis"

            effective_status = self._analysis_state.status
            effective_auth_status = self._analysis_state.auth_status
            error_source = self._analysis_state.last_error or self._analysis_state.last_start_error
            if effective_status in {"failed", "auth_failed", "sync_failed"} and effective_auth_status == "unknown" and error_source:
                effective_status, effective_auth_status = _classify_analysis_error(error_source)
            elif effective_status == "completed":
                effective_auth_status = "ok"
            elif effective_status == "startup_pending":
                effective_auth_status = "unknown"
            elif effective_status == "running" and effective_auth_status == "unknown":
                effective_auth_status = "ok"

            error_code = None
            if effective_status == "auth_failed" or effective_auth_status == "auth_failed":
                error_code = "graph_auth_failed"
            elif effective_status == "sync_failed" or effective_auth_status == "sync_failed":
                error_code = "sync_failed"

            return AnalysisStatusResponse(
                running=effective_running,
                process_alive=effective_process_alive,
                lock_exists=snapshot.lock_exists,
                lock_stale=snapshot.lock_stale,
                activity=effective_activity,
                job_id=self._analysis_state.job_id,
                start_requested_at=self._analysis_state.start_requested_at,
                last_started_at=self._analysis_state.last_started_at,
                last_completed_at=self._analysis_state.last_completed_at,
                startup_grace_active=startup_grace_active,
                process_spawned=self._analysis_state.process_spawned,
                auth_status=effective_auth_status,  # type: ignore[arg-type]
                last_error=self._analysis_state.last_error,
                last_start_error=self._analysis_state.last_start_error,
                error_code=error_code,
                projects_synced=self._analysis_state.projects_synced,
                files_changed=self._analysis_state.files_changed,
                reports_found=self._analysis_state.reports_found,
                reports_generated=self._analysis_state.reports_generated,
                email_mode=self._analysis_state.email_mode,
                project_name=self._analysis_state.project_name,
                status=effective_status,  # type: ignore[arg-type]
                analysis_started=bool(self._analysis_state.start_requested_at or effective_running),
                requested_by=self._analysis_state.requested_by,
                requested_at=self._analysis_state.requested_at,
                current_phase=self._analysis_state.current_phase,
                current_project=self._analysis_state.current_project,
                progress=self._analysis_state.progress,
                process_id=self._analysis_state.process_id,
                appliance_run_id=self._analysis_state.appliance_run_id,
                run_mode="analysis",
                event_code=self._analysis_state.event_code,
            )

    def _clear_stale_lock_error(self, state: SyncJobState | AnalysisJobState, *, label: str) -> None:
        if state.running or not _is_lock_busy_error(state.last_error):
            return
        logger.warning("Clearing stale %s lock error from status: %s", label, state.last_error)
        state.last_error = None
        state.status = "idle"

    def _runtime_history_lock_paths(self) -> list[Path]:
        return list(
            dict.fromkeys(
                runtime_root / "onedrive_sync_history.lock"
                for runtime_root in self.settings.runtime_roots()
            )
        )

    def _runtime_lock_pid(self, lock_path: Path) -> int | None:
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        pid_value = payload.get("pid") if isinstance(payload, dict) else None
        try:
            pid = int(pid_value)
        except Exception:
            return None
        return pid if pid > 0 else None

    def _process_cmdline(self, pid: int) -> str | None:
        cmdline_path = Path("/proc") / str(pid) / "cmdline"
        try:
            raw = cmdline_path.read_bytes()
        except Exception:
            return None
        text = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        return text or None

    def _activity_from_cmdline(self, cmdline: str | None) -> str:
        if not cmdline:
            return "idle"
        lowered = cmdline.casefold()
        if "--sync-only" in lowered:
            return "sync"
        if "--force-analyze" in lowered or "analyze_project.py" in lowered:
            return "analysis"
        if "run_onedrive_appliance.py" in lowered:
            return "sync" if "--sync-only" in lowered else "idle"
        return "idle"

    def _runtime_activity_snapshot_locked(self) -> RuntimeActivitySnapshot:
        snapshot = RuntimeActivitySnapshot(
            sync_running=self._is_process_active(self._sync_state.process),
            analysis_running=self._is_process_active(self._analysis_state.process),
        )
        snapshot.analysis_running = snapshot.analysis_running or self.memory.launch_active()

        for lock_path in self._runtime_history_lock_paths():
            if not lock_path.exists():
                continue

            pid = self._runtime_lock_pid(lock_path)
            if pid is not None and self._is_pid_alive(pid):
                snapshot.lock_exists = True
                if not snapshot.sync_running and not snapshot.analysis_running:
                    inferred_activity = self._activity_from_cmdline(self._process_cmdline(pid))
                    if inferred_activity == "sync":
                        snapshot.sync_running = True
                    elif inferred_activity == "analysis":
                        snapshot.analysis_running = True
                continue

            snapshot.lock_stale = True
            logger.warning("Removing stale history lock: %s", lock_path)
            try:
                lock_path.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Unable to remove stale history lock %s: %s", lock_path, exc)

        snapshot.lock_exists = snapshot.lock_exists or snapshot.sync_running or snapshot.analysis_running
        return snapshot

    def _is_pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False
        return True

    def _is_process_active(self, process: subprocess.Popen[str] | None) -> bool:
        if process is None:
            return False
        try:
            return process.poll() is None
        except Exception:
            return False

    def debug_paths(self, project_name: str) -> ProjectDebugPathsResponse:
        normalized = _normalize_name(project_name)
        candidates = [
            record
            for record in self._discover_project_candidates(include_local_cache=True, include_hidden=True)
            if _normalize_name(record.project_name) == normalized
        ]
        if not candidates:
            raise ProjectNotFoundError(f"Project not found: {project_name}")

        selected = self._select_best_candidate(candidates)
        selected_inspection = selected.source_scan or self._inspect_source_files(selected.project_path, state_path=selected.state_path)
        selected_reports, _, _ = self._load_reports(
            selected.project_path,
            project_name=selected.project_name,
            relative_project_path=selected.relative_project_path,
            is_sample_project=selected.is_sample_project,
        )

        debug_candidates: list[ProjectDebugPathCandidate] = []
        for candidate in sorted(candidates, key=self._project_selection_key, reverse=True):
            inspection = candidate.source_scan or self._inspect_source_files(candidate.project_path, state_path=candidate.state_path)
            reports, _, _ = self._load_reports(
                candidate.project_path,
                project_name=candidate.project_name,
                relative_project_path=candidate.relative_project_path,
                is_sample_project=candidate.is_sample_project,
            )
            debug_candidates.append(
                ProjectDebugPathCandidate(
                    candidate_path=candidate.hidden_internal_path,
                    source_file_count=len(inspection.source_files),
                    report_count=len(reports),
                    comment_document_count=candidate.comment_document_count,
                    source_inventory_mode=inspection.source_inventory_mode,
                    is_sample_project=candidate.is_sample_project,
                    selected=candidate.project_path == selected.project_path,
                    latest_comment_document=candidate.latest_comment_document,
                    latest_comment_modified_at=candidate.latest_comment_modified_at,
                )
            )

        ignored_reasons = list(selected_inspection.ignored_reasons)
        if not selected_inspection.source_files and selected_reports:
            ignored_note = "Only comment documents were found for this project; no source files were counted."
            if ignored_note not in ignored_reasons:
                ignored_reasons.append(ignored_note)

        return ProjectDebugPathsResponse(
            project_name=selected.project_name,
            resolved_project_path=selected.hidden_internal_path,
            project_path_exists=selected.hidden_internal_path.exists() and selected.hidden_internal_path.is_dir(),
            total_files_on_disk=selected_inspection.total_files_on_disk,
            counted_source_files=len(selected_inspection.source_files),
            comment_documents_found=len(selected_reports),
            first_20_files_on_disk=selected_inspection.first_20_files_on_disk,
            ignored_file_count=selected_inspection.ignored_file_count,
            ignored_reasons=self._dedupe_messages(ignored_reasons),
            candidates=debug_candidates,
        )

    def discover_projects(self, *, include_local_cache: bool = False, include_hidden: bool = False) -> list[ProjectRecord]:
        appliance_root = self.settings.resolved_appliance_root()
        if not appliance_root.exists() or not appliance_root.is_dir():
            return []

        candidates: dict[str, ProjectRecord] = {}
        hidden_names = self._hidden_project_names()
        for record in self._discover_project_candidates(include_local_cache=include_local_cache, include_hidden=include_hidden):
            if not include_hidden and _normalize_name(record.project_name) in hidden_names:
                continue
            if not include_local_cache and record.is_local_cache_only:
                continue
            self._insert_candidate(candidates, record)

        return sorted(
            candidates.values(),
            key=lambda record: (
                record.sort_timestamp or datetime.min.replace(tzinfo=timezone.utc),
                record.project_name.casefold(),
            ),
            reverse=True,
        )

    def _discover_project_candidates(self, *, include_local_cache: bool = False, include_hidden: bool = False) -> list[ProjectRecord]:
        records: list[ProjectRecord] = []
        records.extend(self._discover_state_projects())
        if include_local_cache:
            records.extend(self._discover_local_portal_projects())
        records.extend(self._discover_sample_projects())
        definitions = self.memory.definitions()
        configured_names = {item.name.casefold() for item in definitions}
        records = [record for record in records if record.project_name.casefold() not in configured_names]
        for item in definitions:
            if item.project_root.is_dir():
                record = self._build_project_record(item.project_root, source="project_memory", explicit_project_name=item.name)
                records.append(replace(record, source_label="Lokalt prosjektminne", last_synced_at=None))
        if not include_hidden:
            hidden_names = self._hidden_project_names()
            records = [record for record in records if _normalize_name(record.project_name) not in hidden_names]
        return records

    def _collect_global_warnings(self, records: Iterable[ProjectRecord]) -> list[str]:
        warnings: list[str] = []
        for record in records:
            for warning in record.warnings:
                if warning not in warnings:
                    warnings.append(warning)
        return warnings

    def _project_selection_key(self, record: ProjectRecord) -> tuple[int, int, int, datetime, int, str]:
        timestamp = record.sort_timestamp or datetime.min.replace(tzinfo=timezone.utc)
        inventory_score = 1 if record.source_scan is not None and record.source_scan.source_inventory_mode == "filesystem" else 0
        return (
            0 if record.is_local_cache_only else 1,
            0 if record.is_sample_project else 1,
            record.file_count,
            timestamp,
            inventory_score,
            record.project_path.as_posix(),
        )

    def _select_best_candidate(self, records: list[ProjectRecord]) -> ProjectRecord:
        return sorted(records, key=self._project_selection_key, reverse=True)[0]

    def _insert_candidate(self, candidates: dict[str, ProjectRecord], record: ProjectRecord) -> None:
        key = _normalize_name(record.project_name)
        existing = candidates.get(key)
        if existing is None:
            candidates[key] = record
            return
        if self._project_selection_key(record) > self._project_selection_key(existing):
            candidates[key] = record

    def _get_project_record(self, project_name: str, *, load_files: bool = True, load_reports: bool = True) -> ProjectRecord:
        normalized = _normalize_name(project_name)
        matches = [record for record in self.discover_projects() if _normalize_name(record.project_name) == normalized]
        if not matches:
            raise ProjectNotFoundError(f"Project not found: {project_name}")
        if len(matches) > 1:
            raise ProjectAmbiguousError(f"Project name matches multiple projects: {project_name}")

        record = matches[0]
        if load_files or load_reports:
            updated = self._refresh_project_details(record, load_files=load_files, load_reports=load_reports)
            return updated
        return record

    def _refresh_project_details(self, record: ProjectRecord, *, load_files: bool, load_reports: bool) -> ProjectRecord:
        warnings = list(record.warnings)
        errors = list(record.errors)
        reports = record.reports
        file_tree = record.file_tree
        filters = record.filters
        file_count = record.file_count
        report_count = record.report_count
        comment_document_count = record.comment_document_count
        analysis = record.analysis
        last_analyzed_at = record.last_analyzed_at
        status = record.status
        sort_timestamp = record.sort_timestamp

        if load_reports:
            reports, report_warnings, report_errors = self._load_reports(
                record.project_path,
                project_name=record.project_name,
                relative_project_path=record.relative_project_path,
                is_sample_project=record.is_sample_project,
            )
            warnings.extend(report_warnings)
            errors.extend(report_errors)
            report_count = len(reports)
            comment_document_count = len(reports)

        if load_files:
            source_inspection = self._inspect_source_files(record.project_path, state_path=record.state_path)
            source_files = source_inspection.source_files
            warnings.extend(source_inspection.warnings)
            errors.extend(source_inspection.errors)
            file_tree = self._build_file_tree(record.project_name, source_files)
            filters = self._build_file_filters(source_files)
            file_count = len(source_files)
            record_scan = source_inspection
        else:
            record_scan = record.source_scan

        summary_analysis = self._load_analysis_metadata(
            record.project_path,
            state_status=status,
            relative_project_path=record.relative_project_path,
            is_sample_project=record.is_sample_project,
        )
        if summary_analysis is not None:
            analysis = summary_analysis
            if summary_analysis.last_analyzed_at is not None:
                last_analyzed_at = summary_analysis.last_analyzed_at
                sort_timestamp = summary_analysis.last_analyzed_at
            status = summary_analysis.status

        latest_comment_document = record.latest_comment_document
        latest_comment_document_open_url = record.latest_comment_document_open_url
        latest_comment_created_at = record.latest_comment_created_at
        latest_comment_modified_at = record.latest_comment_modified_at
        if load_reports:
            latest_comment_document = reports[0].report_name if reports else latest_comment_document
            if reports:
                latest_comment_document_open_url = self._report_open_url(record.project_name, "latest") if reports[0].open_url else None
            latest_comment_created_at = reports[0].created_at if reports else latest_comment_created_at
            latest_comment_modified_at = reports[0].modified_at if reports else latest_comment_modified_at

        return ProjectRecord(
            project_name=record.project_name,
            display_name=record.display_name,
            source_label=record.source_label,
            relative_project_path=record.relative_project_path,
            hidden_internal_path=record.hidden_internal_path,
            state_path=record.state_path,
            last_synced_at=record.last_synced_at,
            latest_comment_document=latest_comment_document,
            latest_comment_document_open_url=latest_comment_document_open_url,
            latest_comment_created_at=latest_comment_created_at,
            latest_comment_modified_at=latest_comment_modified_at,
            comment_document_count=comment_document_count,
            is_sample_project=record.is_sample_project,
            is_local_cache_only=record.is_local_cache_only,
            project_path=record.project_path,
            status=status,
            last_analyzed_at=last_analyzed_at,
            file_count=file_count,
            report_count=report_count,
            analysis=analysis,
            reports=reports,
            file_tree=file_tree,
            filters=filters,
            source_scan=record_scan,
            warnings=self._dedupe_messages(warnings),
            errors=self._dedupe_messages(errors),
            sort_timestamp=sort_timestamp,
        )

    def _discover_sample_projects(self) -> list[ProjectRecord]:
        sample_root = self.settings.sample_projects_root()
        if not sample_root.exists() or not sample_root.is_dir():
            return []

        records: list[ProjectRecord] = []
        for candidate in sorted(sample_root.iterdir(), key=lambda item: item.name.casefold()):
            if not candidate.is_dir():
                continue
            records.extend(self._collect_project_roots(candidate))
        return records

    def _collect_project_roots(self, candidate: Path) -> list[ProjectRecord]:
        if _is_project_root_candidate(candidate):
            return [self._build_project_record(candidate, source="sample_project")]

        records: list[ProjectRecord] = []
        try:
            children = sorted((child for child in candidate.iterdir() if child.is_dir()), key=lambda item: item.name.casefold())
        except Exception as exc:
            logger.warning("Unable to inspect sample project container %s: %s", candidate, exc)
            return records

        for child in children:
            records.extend(self._collect_project_roots(child))
        return records

    def _discover_local_portal_projects(self) -> list[ProjectRecord]:
        local_root = self.settings.resolved_appliance_root() / LOCAL_PROJECTS_RELATIVE_ROOT
        if not local_root.exists() or not local_root.is_dir():
            return []

        records: list[ProjectRecord] = []
        for candidate in sorted(local_root.iterdir(), key=lambda item: item.name.casefold()):
            if not candidate.is_dir():
                continue
            records.append(
                self._build_project_record(
                    candidate,
                    source="local_portal_project",
                    explicit_project_name=candidate.name,
                    explicit_relative_project_path=f"Urban_Reuse_Norway/{candidate.name}",
                    explicit_status="pending",
                )
            )
        return records

    def _discover_state_projects(self) -> list[ProjectRecord]:
        records: list[ProjectRecord] = []
        for runtime_root in self.settings.runtime_roots():
            if not runtime_root.exists() or not runtime_root.is_dir():
                continue
            for database_path in runtime_root.rglob(LIGHTWEIGHT_STATE_DB_FILENAME):
                records.extend(self._load_state_db_projects(database_path))
        return records

    def _load_state_db_projects(self, database_path: Path) -> list[ProjectRecord]:
        records: list[ProjectRecord] = []
        try:
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
        except Exception as exc:
            logger.warning("Unable to open runtime state database %s: %s", database_path, exc)
            return records

        try:
            rows = connection.execute("SELECT * FROM projects").fetchall()
        except Exception as exc:
            logger.warning("Unable to read runtime state database %s: %s", database_path, exc)
            connection.close()
            return records

        for row in rows:
            project_name = str(_row_value(row, "project_name", "") or "").strip()
            remote_root_path = str(_row_value(row, "remote_root_path", "") or "").strip()
            local_project_root = str(_row_value(row, "local_project_root", "") or "").strip()
            if not project_name or not local_project_root:
                continue

            project_path = Path(local_project_root).expanduser()
            analysis_status = str(_row_value(row, "analysis_status", "") or "").strip() or "unknown"
            last_synced_at = _parse_datetime(str(_row_value(row, "last_sync_at", "") or "").strip())
            last_analyzed_at = _parse_datetime(str(_row_value(row, "last_analyzed_at", "") or "").strip())
            updated_at = _parse_datetime(str(_row_value(row, "updated_at", "") or "").strip())
            report_path_value = str(_row_value(row, "report_path", "") or "").strip()
            report_url = str(_row_value(row, "report_url", "") or "").strip() or None
            report_path = Path(report_path_value).expanduser() if report_path_value else None
            state_path_text = str(_row_value(row, "state_path", "") or "").strip()
            state_path = Path(state_path_text).expanduser() if state_path_text else _infer_sync_state_path(project_path)
            warnings: list[str] = []
            if not project_path.exists():
                logger.warning("Project root is missing on disk: %s", project_path)
                warnings.append("Project root is missing on disk.")

            record = self._build_project_record(
                project_path,
                source="state_db",
                explicit_project_name=project_name,
                explicit_relative_project_path=remote_root_path or None,
                explicit_last_synced_at=last_synced_at or updated_at,
                explicit_status=analysis_status,
                explicit_last_analyzed_at=last_analyzed_at,
                explicit_sort_timestamp=updated_at or last_analyzed_at,
                explicit_report_path=report_path,
                explicit_report_url=report_url,
                explicit_state_path=state_path,
                extra_warnings=warnings,
            )
            records.append(record)

        connection.close()
        return records

    def _build_project_record(
        self,
        project_path: Path,
        *,
        source: str,
        explicit_project_name: str | None = None,
        explicit_relative_project_path: str | None = None,
        explicit_last_synced_at: datetime | None = None,
        explicit_status: str | None = None,
        explicit_last_analyzed_at: datetime | None = None,
        explicit_sort_timestamp: datetime | None = None,
        explicit_report_path: Path | None = None,
        explicit_report_url: str | None = None,
        explicit_state_path: Path | None = None,
        extra_warnings: list[str] | None = None,
    ) -> ProjectRecord:
        project_path = project_path.expanduser().resolve(strict=False)
        warnings = list(extra_warnings or [])
        errors: list[str] = []
        project_name = explicit_project_name or project_path.name
        is_sample_project = source == "sample_project"
        is_local_cache_only = source == "local_portal_project" or (source == "state_db" and not explicit_relative_project_path)
        display_name = project_name
        source_label = "Kun lokal cache" if is_local_cache_only else "OneDrive"
        relative_project_path = explicit_relative_project_path or (
            f"sample_projects/{project_name}" if is_sample_project else project_name
        )
        relative_project_path = _display_relative_project_path(relative_project_path)
        state_path = explicit_state_path or _infer_sync_state_path(project_path)

        analysis = self._load_analysis_metadata(
            project_path,
            state_status=explicit_status,
            relative_project_path=relative_project_path,
            is_sample_project=is_sample_project,
        )
        if analysis is not None:
            status = analysis.status
            last_analyzed_at = analysis.last_analyzed_at or explicit_last_analyzed_at
            sort_timestamp = analysis.last_analyzed_at or explicit_sort_timestamp or explicit_last_analyzed_at
        else:
            status = explicit_status or "unknown"
            last_analyzed_at = explicit_last_analyzed_at
            sort_timestamp = explicit_sort_timestamp or explicit_last_analyzed_at

        reports, report_warnings, report_errors = self._load_reports(
            project_path,
            project_name=project_name,
            relative_project_path=relative_project_path,
            is_sample_project=is_sample_project,
        )
        warnings.extend(report_warnings)
        errors.extend(report_errors)
        latest_comment_document = reports[0].report_name if reports else None
        latest_comment_document_open_url = self._report_open_url(project_name, "latest") if reports and reports[0].open_url else None
        latest_comment_created_at = reports[0].created_at if reports else None
        latest_comment_modified_at = reports[0].modified_at if reports else None
        comment_document_count = len(reports)

        source_inspection = self._inspect_source_files(project_path, state_path=state_path)
        source_files = source_inspection.source_files
        warnings.extend(source_inspection.warnings)
        errors.extend(source_inspection.errors)

        # If the state database references a report that is not currently in the
        # comments folder, keep the on-disk listing authoritative but log the hint.
        if explicit_report_path is not None and not explicit_report_path.exists():
            logger.warning("Referenced report path is missing on disk: %s", explicit_report_path)
            warnings.append("Referenced report path is missing on disk.")
        if explicit_report_url:
            warnings.append("Remote report URL recorded in appliance state.")

        if explicit_last_synced_at is not None:
            last_synced_at = explicit_last_synced_at
        elif analysis is not None and analysis.last_analyzed_at is not None:
            last_synced_at = analysis.last_analyzed_at
        else:
            last_synced_at = latest_comment_created_at or latest_comment_modified_at or sort_timestamp

        if sort_timestamp is None:
            sort_timestamp = last_synced_at or latest_comment_created_at or latest_comment_modified_at

        return ProjectRecord(
            project_name=project_name,
            display_name=display_name,
            source_label=source_label,
            relative_project_path=relative_project_path,
            hidden_internal_path=project_path,
            state_path=state_path,
            last_synced_at=last_synced_at,
            latest_comment_document=latest_comment_document,
            latest_comment_document_open_url=latest_comment_document_open_url,
            latest_comment_created_at=latest_comment_created_at,
            latest_comment_modified_at=latest_comment_modified_at,
            comment_document_count=comment_document_count,
            is_sample_project=is_sample_project,
            is_local_cache_only=is_local_cache_only,
            project_path=project_path,
            status=status,
            last_analyzed_at=last_analyzed_at,
            file_count=len(source_files),
            report_count=comment_document_count,
            analysis=analysis,
            reports=reports,
            file_tree=self._build_file_tree(project_name, source_files),
            filters=self._build_file_filters(source_files),
            source_scan=source_inspection,
            warnings=self._dedupe_messages(warnings),
            errors=self._dedupe_messages(errors),
            sort_timestamp=sort_timestamp,
        )

    def _analysis_summary_candidates(
        self,
        project_path: Path,
        *,
        relative_project_path: str | None,
        is_sample_project: bool,
    ) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()

        def add(path: Path) -> None:
            resolved = path.expanduser().resolve(strict=False)
            key = resolved.as_posix()
            if key in seen or not resolved.exists() or not resolved.is_file():
                return
            seen.add(key)
            candidates.append(resolved)

        for root in self._comment_root_candidates(
            project_path,
            relative_project_path=relative_project_path,
            is_sample_project=is_sample_project,
        ):
            if root.name.casefold() in COMMENT_ROOT_NAMES:
                add(root / "run_summary.json")
                continue

            for summary_path in sorted(root.rglob("run_summary.json"), key=lambda item: item.as_posix().casefold()):
                if summary_path.parent.name.casefold() in COMMENT_ROOT_NAMES:
                    add(summary_path)

        output_relative_path = self._output_relative_path(relative_project_path)
        if output_relative_path is not None:
            outputs_root = self.settings.resolved_appliance_root() / "outputs" / output_relative_path
            add(outputs_root / "run_summary.json")
            for summary_path in sorted(outputs_root.rglob("run_summary.json"), key=lambda item: item.as_posix().casefold()):
                add(summary_path)

        return candidates

    def _load_analysis_metadata(
        self,
        project_path: Path,
        *,
        state_status: str | None = None,
        relative_project_path: str | None = None,
        is_sample_project: bool = False,
    ) -> ProjectAnalysisInfo | None:
        project_path = project_path.expanduser().resolve(strict=False)
        candidate_paths = self._analysis_summary_candidates(
            project_path,
            relative_project_path=relative_project_path,
            is_sample_project=is_sample_project,
        )
        best_info: ProjectAnalysisInfo | None = None
        best_timestamp: datetime | None = None

        for summary_path in candidate_paths:
            try:
                payload = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Unable to read run summary %s: %s", summary_path, exc)
                continue

            finished_at = _parse_datetime(str(payload.get("finished_at", "") or ""))
            started_at = _parse_datetime(str(payload.get("started_at", "") or ""))
            last_analyzed_at = finished_at or started_at
            warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
            errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
            output_docx_path_value = str(payload.get("output_docx_path", "") or "").strip()
            output_docx_path = Path(output_docx_path_value).expanduser() if output_docx_path_value else None

            info = ProjectAnalysisInfo(
                status=_select_analysis_status(str(payload.get("status") or ""), state_status),
                last_analyzed_at=last_analyzed_at,
                provider=str(payload.get("provider") or "") or None,
                model=str(payload.get("model") or "") or None,
                documents_seen=_parse_int(payload.get("documents_seen"), 0) if payload.get("documents_seen") is not None else None,
                chunks_created=_parse_int(payload.get("chunks_created"), 0) if payload.get("chunks_created") is not None else None,
                report_items_count=_parse_int(payload.get("report_items_count"), 0) if payload.get("report_items_count") is not None else None,
                output_docx_path=output_docx_path,
                run_summary_path=summary_path,
                warnings_count=len(warnings),
                errors_count=len(errors),
            )
            timestamp = last_analyzed_at
            if timestamp is None:
                try:
                    timestamp = datetime.fromtimestamp(summary_path.stat().st_mtime, tz=OSLO_TIMEZONE)
                except Exception:
                    timestamp = None

            if best_info is None:
                best_info = info
                best_timestamp = timestamp
                continue

            if timestamp is not None and (best_timestamp is None or timestamp > best_timestamp):
                best_info = info
                best_timestamp = timestamp

        if best_info is not None:
            return best_info

        if state_status is not None:
            return ProjectAnalysisInfo(status=state_status)
        return None

    def _output_relative_path(self, relative_project_path: str | None) -> Path | None:
        if not relative_project_path:
            return None

        parts = Path(relative_project_path).parts
        if not parts:
            return None
        if parts[0].casefold() == "anbudappliance":
            parts = parts[1:]
        if not parts:
            return None
        return Path(*parts)

    def _comment_root_candidates(self, project_path: Path, *, relative_project_path: str | None, is_sample_project: bool) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()

        def add(path: Path) -> None:
            resolved = path.expanduser().resolve(strict=False)
            key = resolved.as_posix()
            if key in seen:
                return
            if resolved.exists() and resolved.is_dir():
                candidates.append(resolved)
                seen.add(key)

        if project_path.name.casefold() in COMMENT_ROOT_NAMES:
            add(project_path)

        try:
            for candidate in sorted(project_path.rglob("*"), key=lambda item: item.as_posix().casefold()):
                if candidate.is_dir() and candidate.name.casefold() in COMMENT_ROOT_NAMES:
                    add(candidate)
        except Exception as exc:
            logger.warning("Unable to inspect report roots in %s: %s", project_path, exc)
        return candidates

    def _report_search_roots(self, root: Path) -> list[Path]:
        if root.name.casefold() in COMMENT_ROOT_NAMES:
            return [root]
        search_roots: list[Path] = []
        for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if candidate.is_dir() and candidate.name.casefold() in COMMENT_ROOT_NAMES:
                search_roots.append(candidate)
        return search_roots

    def _allowed_report_roots(self, record: ProjectRecord) -> list[Path]:
        roots: list[Path] = []
        for root in self._comment_root_candidates(
            record.project_path,
            relative_project_path=record.relative_project_path,
            is_sample_project=record.is_sample_project,
        ):
            for report_root in self._report_search_roots(root):
                try:
                    roots.append(report_root.expanduser().resolve(strict=True))
                except Exception as exc:
                    logger.warning("Unable to resolve report root %s: %s", report_root, exc)
        output_relative_path = self._output_relative_path(record.relative_project_path)
        if output_relative_path is not None:
            outputs_root = self.settings.resolved_appliance_root() / "outputs" / output_relative_path
            try:
                resolved_outputs_root = outputs_root.expanduser().resolve(strict=True)
            except Exception:
                resolved_outputs_root = outputs_root.expanduser().resolve(strict=False)
            if resolved_outputs_root.exists() and resolved_outputs_root.is_dir():
                roots.append(resolved_outputs_root)
                for report_root in self._report_search_roots(resolved_outputs_root):
                    try:
                        roots.append(report_root.expanduser().resolve(strict=True))
                    except Exception as exc:
                        logger.warning("Unable to resolve report root %s: %s", report_root, exc)
        return roots

    def _select_report(self, reports: list[ProjectReport], report_id: str) -> ProjectReport:
        normalized = str(report_id or "").strip().casefold()
        if normalized == "latest":
            index = 0
        elif normalized.isdecimal():
            index = int(normalized)
        else:
            raise ProjectReportNotFoundError(f"Report not found: {report_id}")

        if index < 0 or index >= len(reports):
            raise ProjectReportNotFoundError(f"Report not found: {report_id}")
        return reports[index]

    def _report_open_url(self, project_name: str, report_id: str) -> str:
        return f"/api/projects/{quote(project_name, safe='')}/reports/{quote(report_id, safe='')}/open"

    def _report_download_url(self, project_name: str, report_id: str) -> str:
        return f"/api/projects/{quote(project_name, safe='')}/reports/{quote(report_id, safe='')}/download"

    def _report_file_metadata(self, candidate: Path) -> tuple[datetime, datetime | None, str | None]:
        try:
            stat_result = candidate.stat()
            created_at = _file_created_at(stat_result)
        except Exception:
            created_at = datetime.fromtimestamp(0, tz=OSLO_TIMEZONE)

        generated_at = self._report_generated_at(candidate)
        version = _report_version_label(candidate.name)
        return created_at, generated_at, version

    def _report_generated_at(self, candidate: Path) -> datetime | None:
        search_roots = [candidate.parent, *candidate.parents[1:4]]
        seen: set[str] = set()
        for root in search_roots:
            resolved = root.expanduser().resolve(strict=False)
            key = resolved.as_posix()
            if key in seen:
                continue
            seen.add(key)
            summary_path = resolved / "run_summary.json"
            if not summary_path.exists() or not summary_path.is_file():
                continue
            try:
                payload = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            generated_at = _parse_datetime(str(payload.get("generated_at") or payload.get("finished_at") or payload.get("created_at") or ""))
            if generated_at is not None:
                return generated_at
        return None

    def _history_generated_at(self, payload: Mapping[str, Any]) -> datetime | None:
        snapshot = payload.get("report_snapshot")
        if not isinstance(snapshot, Mapping):
            snapshot = payload.get("analysis_snapshot")

        timestamp_text = ""
        if isinstance(snapshot, Mapping):
            timestamp_text = str(
                snapshot.get("generated_at")
                or snapshot.get("finished_at")
                or snapshot.get("created_at")
                or ""
            ).strip()
        if not timestamp_text:
            timestamp_text = str(payload.get("timestamp") or "").strip()
        return _parse_datetime(timestamp_text)

    def _history_report_file_path(
        self,
        payload: Mapping[str, Any],
        *,
        uploaded_report: Mapping[str, Any] | None = None,
    ) -> Path | None:
        candidates: list[Path] = []
        seen: set[str] = set()

        def add_candidate(value: Any) -> None:
            text = str(value or "").strip()
            if not text:
                return
            candidate = Path(text).expanduser()
            key = candidate.as_posix()
            if key in seen:
                return
            seen.add(key)
            candidates.append(candidate)

        if uploaded_report is not None:
            add_candidate(uploaded_report.get("local_path"))
            add_candidate(uploaded_report.get("local_report_path"))

        add_candidate(payload.get("output_docx_path"))
        add_candidate(payload.get("local_report_path"))

        output_dir_text = str(
            (uploaded_report.get("local_output_path") if uploaded_report is not None else payload.get("local_output_path")) or ""
        ).strip()
        if output_dir_text:
            output_dir = Path(output_dir_text).expanduser()
            for source in (
                uploaded_report.get("local_path") if uploaded_report is not None else None,
                uploaded_report.get("local_report_path") if uploaded_report is not None else None,
                payload.get("output_docx_path"),
                payload.get("local_report_path"),
            ):
                name = Path(str(source or "").strip()).name
                if name:
                    add_candidate(output_dir / name)

        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    return candidate
            except Exception:
                continue

        return candidates[0] if candidates else None

    def _project_report_from_history_record(
        self,
        payload: Mapping[str, Any],
        project_name: str,
        *,
        report_name: str,
        report_path: Path | None,
    ) -> ProjectReport | None:
        del project_name

        generated_at = self._history_generated_at(payload)
        if generated_at is None:
            return None

        report_name = Path(report_name).name.strip()
        if not report_name or not _is_comment_document_report_name(report_name):
            return None

        report_path = report_path.expanduser() if report_path is not None else Path(report_name)
        report_type = report_path.suffix.lower().lstrip(".") or str(payload.get("report_type") or "").strip() or "unknown"
        version = _report_version_label(report_name)

        try:
            stat_result = report_path.stat()
            created_at = _file_created_at(stat_result)
            modified_at = datetime.fromtimestamp(stat_result.st_mtime, tz=OSLO_TIMEZONE)
            size_bytes = stat_result.st_size
            openable = report_path.suffix.lower() in OPENABLE_REPORT_SUFFIXES
        except Exception:
            created_at = generated_at
            modified_at = generated_at
            size_bytes = 0
            openable = False

        return ProjectReport(
            report_name=report_name,
            report_path=report_path,
            report_type=report_type,
            version=version,
            created_at=created_at,
            generated_at=generated_at,
            modified_at=modified_at,
            size_bytes=size_bytes,
            is_latest=False,
            open_url="filesystem" if openable else "",
            download_url="filesystem" if openable else "",
        )

    def _project_reports_from_history_records(
        self,
        payload: Mapping[str, Any],
        project_name: str,
    ) -> list[ProjectReport]:
        uploaded_reports = payload.get("uploaded_reports")
        if isinstance(uploaded_reports, list) and uploaded_reports:
            reports: list[ProjectReport] = []
            for uploaded_report in uploaded_reports:
                if not isinstance(uploaded_report, Mapping):
                    continue
                remote_path = str(uploaded_report.get("remote_path") or "").strip()
                report_name_source = (
                    remote_path
                    or str(uploaded_report.get("local_path") or "").strip()
                    or str(uploaded_report.get("local_report_path") or "").strip()
                    or str(payload.get("output_docx_path") or "").strip()
                    or str(payload.get("local_report_path") or "").strip()
                )
                if not report_name_source:
                    continue

                report = self._project_report_from_history_record(
                    payload,
                    project_name,
                    report_name=report_name_source,
                    report_path=self._history_report_file_path(payload, uploaded_report=uploaded_report),
                )
                if report is not None:
                    reports.append(report)

            return reports

        return []

    def _project_report_from_history_record_single(
        self,
        payload: Mapping[str, Any],
        project_name: str,
    ) -> ProjectReport | None:
        report_name_source = (
            str(payload.get("local_report_path") or "").strip()
            or str(payload.get("output_docx_path") or "").strip()
        )
        if not report_name_source:
            snapshot = payload.get("report_snapshot")
            if not isinstance(snapshot, Mapping):
                snapshot = payload.get("analysis_snapshot")
            if isinstance(snapshot, Mapping):
                report_name_source = (
                    str(snapshot.get("local_report_path") or "").strip()
                    or str(snapshot.get("output_docx_path") or "").strip()
                )
        if not report_name_source:
            return None

        return self._project_report_from_history_record(
            payload,
            project_name,
            report_name=report_name_source,
            report_path=self._history_report_file_path(payload),
        )

    def _history_report_candidates(
        self,
        project_name: str,
        *,
        relative_project_path: str | None = None,
        is_sample_project: bool = False,
    ) -> list[ProjectReport]:
        if is_sample_project:
            return []

        project_name_normalized = _normalize_name(project_name)
        uploaded_reports: list[ProjectReport] = []
        fallback_reports: list[ProjectReport] = []
        seen_keys: set[str] = set()

        for history_path in self._report_history_paths():
            try:
                payloads = self._read_report_history(history_path)
            except Exception as exc:
                logger.warning("Unable to read report history %s: %s", history_path, exc)
                continue

            for payload in payloads:
                if not self._history_entry_matches_project(payload, project_name_normalized):
                    continue

                history_reports = self._project_reports_from_history_records(payload, project_name)
                if history_reports:
                    target_reports = uploaded_reports
                else:
                    fallback_report = self._project_report_from_history_record_single(payload, project_name)
                    if fallback_report is None:
                        continue
                    target_reports = fallback_reports
                    history_reports = [fallback_report]

                for report in history_reports:
                    key = f"{report.report_name.casefold()}|{report.created_at.isoformat()}|{report.report_path.as_posix().casefold()}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    target_reports.append(report)

        if uploaded_reports:
            uploaded_reports.sort(key=_sort_comment_documents_key, reverse=True)
            return uploaded_reports

        fallback_reports.sort(key=_sort_comment_documents_key, reverse=True)
        return fallback_reports

    def _read_report_history(self, history_path: Path) -> tuple[dict[str, Any], ...]:
        """Share parsed report metadata across projects, refreshing on file changes."""

        def file_signature() -> tuple[int, ...]:
            stat = history_path.stat()
            return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)

        # Health and project requests arrive together. Only one may parse a
        # changed history file; the others reuse its completed snapshot.
        with self._report_history_cache_lock:
            signature = file_signature()
            cached = self._report_history_cache.get(history_path)
            if cached is not None and cached[0] == signature:
                return cached[1]

            self._report_history_cache.pop(history_path, None)
            payloads: list[dict[str, Any]] = []
            # Stream large JSONL files and retain only report metadata. Source
            # documents and analysis details are not needed for report listings.
            with history_path.open(encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        parsed = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(parsed, Mapping):
                        continue
                    payload = {key: parsed[key] for key in _REPORT_HISTORY_FIELDS if key in parsed}
                    for key in ("report_snapshot", "analysis_snapshot"):
                        snapshot = payload.get(key)
                        if isinstance(snapshot, Mapping):
                            payload[key] = {
                                field: snapshot[field]
                                for field in _REPORT_HISTORY_SNAPSHOT_FIELDS if field in snapshot
                            }
                    uploaded = payload.get("uploaded_reports")
                    if isinstance(uploaded, list):
                        payload["uploaded_reports"] = [
                            {field: report[field] for field in _REPORT_HISTORY_UPLOAD_FIELDS if field in report}
                            for report in uploaded if isinstance(report, Mapping)
                        ]
                    payloads.append(payload)

            result = tuple(payloads)
            try:
                unchanged = file_signature() == signature
            except OSError:
                unchanged = False
            if unchanged:
                if len(self._report_history_cache) >= REPORT_HISTORY_CACHE_MAX_FILES:
                    self._report_history_cache.pop(next(iter(self._report_history_cache)))
                self._report_history_cache[history_path] = (signature, result)
            return result

    def _report_history_paths(self) -> list[Path]:
        candidates: list[Path] = []
        outputs_root = self.settings.resolved_appliance_root() / "outputs"
        if outputs_root.exists() and outputs_root.is_dir():
            candidates.extend(sorted(outputs_root.rglob("history.jsonl"), key=lambda item: item.as_posix().casefold()))

        for runtime_root in self.settings.runtime_roots():
            if not runtime_root.exists() or not runtime_root.is_dir():
                continue
            candidates.extend(sorted(runtime_root.rglob("onedrive_sync_history.jsonl"), key=lambda item: item.as_posix().casefold()))

        unique_candidates: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            resolved = candidate.expanduser().resolve(strict=False)
            key = resolved.as_posix()
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(resolved)
        return unique_candidates

    def _history_entry_matches_project(self, payload: Mapping[str, Any], project_name_normalized: str) -> bool:
        for value in (
            payload.get("project_name"),
            payload.get("remote_root_path"),
            payload.get("local_project_root"),
            payload.get("local_report_path"),
        ):
            text = str(value or "").strip()
            if not text:
                continue
            normalized = _normalize_name(Path(text.replace("\\", "/")).name)
            if normalized == project_name_normalized:
                return True
            normalized_text = _normalize_name(text)
            if project_name_normalized in normalized_text:
                return True

        uploaded_reports = payload.get("uploaded_reports")
        if isinstance(uploaded_reports, list):
            for uploaded_report in uploaded_reports:
                if not isinstance(uploaded_report, Mapping):
                    continue
                for value in (
                    uploaded_report.get("remote_path"),
                    uploaded_report.get("local_path"),
                    uploaded_report.get("local_report_path"),
                    uploaded_report.get("local_output_path"),
                ):
                    text = str(value or "").strip()
                    if not text:
                        continue
                    normalized = _normalize_name(Path(text.replace("\\", "/")).name)
                    if normalized == project_name_normalized:
                        return True
                    normalized_text = _normalize_name(text)
                    if project_name_normalized in normalized_text:
                        return True

        for key in ("report_snapshot", "analysis_snapshot"):
            snapshot = payload.get(key)
            if not isinstance(snapshot, Mapping):
                continue
            snapshot_project = str(snapshot.get("project_name") or "").strip()
            if snapshot_project and _normalize_name(snapshot_project) == project_name_normalized:
                return True
        return False

    def _load_reports(
        self,
        project_path: Path,
        *,
        project_name: str,
        relative_project_path: str | None = None,
        is_sample_project: bool = False,
    ) -> tuple[list[ProjectReport], list[str], list[str]]:
        project_path = project_path.expanduser().resolve(strict=False)
        warnings: list[str] = []
        errors: list[str] = []
        reports: list[ProjectReport] = []
        seen_paths: set[str] = set()

        def collect_from_root(root: Path) -> None:
            for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
                if not candidate.is_file():
                    continue
                if candidate.name.casefold() == "run_summary.json":
                    continue
                if candidate.suffix.lower() not in REPORT_SUFFIXES:
                    continue
                if not _is_comment_document_report_name(candidate.name):
                    continue

                candidate_key = candidate.expanduser().resolve(strict=False).as_posix()
                if candidate_key in seen_paths:
                    continue
                seen_paths.add(candidate_key)

                try:
                    stat_result = candidate.stat()
                except Exception as exc:
                    relative_candidate = candidate.relative_to(project_path).as_posix() if candidate.is_relative_to(project_path) else candidate.name
                    logger.warning("Unable to inspect report file %s: %s", relative_candidate, exc)
                    warnings.append("Unable to inspect one of the comment documents.")
                    continue

                created_at, generated_at, version = self._report_file_metadata(candidate)

                reports.append(
                    ProjectReport(
                        report_name=candidate.name,
                        report_path=candidate,
                        report_type=candidate.suffix.lower().lstrip(".") or "unknown",
                        version=version,
                        created_at=created_at,
                        generated_at=generated_at,
                        modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=OSLO_TIMEZONE),
                        size_bytes=stat_result.st_size,
                        is_latest=False,
                        open_url="filesystem",
                        download_url="filesystem",
                    )
                )

        comment_roots = self._comment_root_candidates(
            project_path,
            relative_project_path=relative_project_path,
            is_sample_project=is_sample_project,
        )
        for root in comment_roots:
            if root.name.casefold() not in REPORT_ROOT_NAMES:
                continue
            for comment_root in self._report_search_roots(root):
                collect_from_root(comment_root)

        if not reports:
            history_reports = self._history_report_candidates(
                project_name,
                relative_project_path=relative_project_path,
                is_sample_project=is_sample_project,
            )
            reports.extend(history_reports)

        if not reports:
            output_relative_path = self._output_relative_path(relative_project_path)
            if output_relative_path is not None:
                outputs_root = self.settings.resolved_appliance_root() / "outputs" / output_relative_path
                if outputs_root.exists() and outputs_root.is_dir():
                    collect_from_root(outputs_root)

        reports.sort(key=_sort_comment_documents_key, reverse=True)
        reports = [
            report.model_copy(
                update={
                    "report_id": str(index),
                    "is_latest": index == 0,
                    "open_url": self._report_open_url(project_name, str(index)) if report.open_url else "",
                    "download_url": self._report_download_url(project_name, str(index)) if report.download_url else "",
                }
            )
            for index, report in enumerate(reports)
        ]
        return reports, warnings, errors

    def _source_file_ignore_reason(self, file_path: Path, project_root_resolved: Path) -> str | None:
        if file_path.is_symlink():
            return "Symlinks are excluded from source file counts."
        try:
            relative_path = file_path.relative_to(project_root_resolved)
        except Exception:
            return "Files outside the resolved project root are excluded from source file counts."

        reason = _source_file_ignore_reason_from_relative(relative_path)
        if reason is not None:
            return reason

        try:
            resolved_path = file_path.resolve(strict=True)
        except Exception:
            return "Unreadable files are excluded from source file counts."

        if not resolved_path.is_relative_to(project_root_resolved):
            return "Files outside the resolved project root are excluded from source file counts."

        return None

    def _inspect_source_files_from_filesystem(self, project_path: Path) -> SourceScanResult:
        project_path = project_path.expanduser().resolve(strict=False)
        if not project_path.exists() or not project_path.is_dir():
            logger.warning("Project root is missing or not a directory: %s", project_path)
            warning = "Project root is missing or not a directory."
            return SourceScanResult(
                source_files=[],
                total_files_on_disk=0,
                ignored_file_count=0,
                ignored_reasons=[warning],
                first_20_files_on_disk=[],
                warnings=[warning],
                errors=[warning],
                source_inventory_mode="filesystem",
                filesystem_total_files_on_disk=0,
                state_total_files_on_disk=0,
            )

        source_files: list[SourceFileRecord] = []
        warnings: list[str] = []
        errors: list[str] = []
        first_20_files_on_disk: list[str] = []
        ignored_reasons: list[str] = []
        total_files_on_disk = 0
        ignored_file_count = 0
        project_root_resolved = project_path.resolve(strict=False)

        for candidate in sorted(project_path.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not candidate.is_file():
                continue

            total_files_on_disk += 1
            relative_path = candidate.relative_to(project_path).as_posix()
            if len(first_20_files_on_disk) < 20:
                first_20_files_on_disk.append(relative_path)

            reason = self._source_file_ignore_reason(candidate, project_root_resolved)
            if reason is not None:
                ignored_file_count += 1
                if reason not in ignored_reasons:
                    ignored_reasons.append(reason)
                continue

            try:
                resolved_path = candidate.resolve(strict=True)
                stat_result = resolved_path.stat()
            except Exception as exc:
                logger.warning("Unable to inspect file %s: %s", relative_path, exc)
                warnings.append(f"Unable to inspect file '{relative_path}'.")
                errors.append(f"Unable to inspect file '{relative_path}'.")
                ignored_file_count += 1
                if "Unreadable files are excluded from source file counts." not in ignored_reasons:
                    ignored_reasons.append("Unreadable files are excluded from source file counts.")
                continue

            if not resolved_path.is_relative_to(project_root_resolved):
                ignored_file_count += 1
                if "Files outside the resolved project root are excluded from source file counts." not in ignored_reasons:
                    ignored_reasons.append("Files outside the resolved project root are excluded from source file counts.")
                continue

            source_files.append(
                SourceFileRecord(
                    relative_path=relative_path,
                    absolute_path=resolved_path,
                    folder_category=_project_folder_category(Path(relative_path)),
                    size_bytes=stat_result.st_size,
                    modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=OSLO_TIMEZONE),
                )
            )

        source_files.sort(key=lambda item: item.relative_path.casefold())

        if total_files_on_disk == 0:
            ignored_reasons.append("No source files were found in the local appliance cache.")
        elif not source_files and ignored_file_count == total_files_on_disk and ignored_file_count > 0:
            ignored_reasons.append("Only generated comment documents or cache files were found.")

        deduped_reasons = self._dedupe_messages(ignored_reasons)
        return SourceScanResult(
            source_files=source_files,
            total_files_on_disk=total_files_on_disk,
            ignored_file_count=ignored_file_count,
            ignored_reasons=deduped_reasons,
            first_20_files_on_disk=first_20_files_on_disk,
            warnings=warnings,
            errors=errors,
            source_inventory_mode="filesystem",
            filesystem_total_files_on_disk=total_files_on_disk,
            state_total_files_on_disk=0,
        )

    def _inspect_source_files_from_state(self, project_path: Path, state_path: Path) -> SourceScanResult | None:
        project_path = project_path.expanduser().resolve(strict=False)
        state_path = state_path.expanduser().resolve(strict=False)
        if not state_path.exists() or not state_path.is_file():
            return None

        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Unable to read sync state %s: %s", state_path, exc)
            warning = "Unable to read the OneDrive sync state cache."
            return SourceScanResult(
                source_files=[],
                total_files_on_disk=0,
                ignored_file_count=0,
                ignored_reasons=[warning],
                first_20_files_on_disk=[],
                warnings=[warning],
                errors=[warning],
                source_inventory_mode="sync_state",
                filesystem_total_files_on_disk=0,
                state_total_files_on_disk=0,
                state_path=state_path,
            )

        items_by_id = payload.get("items_by_id")
        if not isinstance(items_by_id, dict) or not items_by_id:
            return SourceScanResult(
                source_files=[],
                total_files_on_disk=0,
                ignored_file_count=0,
                ignored_reasons=["No source files were found in the OneDrive sync state."],
                first_20_files_on_disk=[],
                warnings=[],
                errors=[],
                source_inventory_mode="sync_state",
                filesystem_total_files_on_disk=0,
                state_total_files_on_disk=0,
                state_path=state_path,
            )

        source_files: list[SourceFileRecord] = []
        warnings: list[str] = []
        errors: list[str] = []
        first_20_files_on_disk: list[str] = []
        ignored_reasons: list[str] = []
        total_files_on_disk = 0
        ignored_file_count = 0

        ordered_items = sorted(
            (item for item in items_by_id.values() if isinstance(item, dict)),
            key=lambda item: str(item.get("relative_path") or "").casefold(),
        )

        for item in ordered_items:
            if bool(item.get("is_folder")):
                continue

            relative_path_text = str(item.get("relative_path") or "").strip()
            if not relative_path_text:
                continue

            total_files_on_disk += 1
            if len(first_20_files_on_disk) < 20:
                first_20_files_on_disk.append(relative_path_text)

            relative_path = Path(relative_path_text)
            reason = _source_file_ignore_reason_from_relative(relative_path)
            if reason is not None:
                ignored_file_count += 1
                if reason not in ignored_reasons:
                    ignored_reasons.append(reason)
                continue

            local_path_text = str(item.get("local_path") or item.get("local_cache_path") or "").strip()
            absolute_path = Path(local_path_text).expanduser() if local_path_text else project_path / relative_path
            resolved_path = absolute_path.expanduser().resolve(strict=False)
            if not resolved_path.is_relative_to(project_path):
                ignored_file_count += 1
                reason = "Files outside the resolved project root are excluded from source file counts."
                if reason not in ignored_reasons:
                    ignored_reasons.append(reason)
                continue

            size_bytes = _parse_int(item.get("size"), 0)
            modified_at = _parse_datetime(str(item.get("last_modified_date_time") or "").strip())
            if resolved_path.exists():
                try:
                    stat_result = resolved_path.stat()
                    size_bytes = stat_result.st_size
                    modified_at = datetime.fromtimestamp(stat_result.st_mtime, tz=OSLO_TIMEZONE)
                except Exception as exc:
                    logger.warning("Unable to inspect cached source file %s: %s", relative_path_text, exc)
                    warning = f"Unable to inspect file '{relative_path_text}'."
                    warnings.append(warning)
                    errors.append(warning)
                    ignored_file_count += 1
                    if "Unreadable files are excluded from source file counts." not in ignored_reasons:
                        ignored_reasons.append("Unreadable files are excluded from source file counts.")
                    continue

            if modified_at is None:
                modified_at = datetime.fromtimestamp(0, tz=OSLO_TIMEZONE)

            source_files.append(
                SourceFileRecord(
                    relative_path=relative_path_text,
                    absolute_path=resolved_path,
                    folder_category=_project_folder_category(relative_path),
                    size_bytes=size_bytes,
                    modified_at=modified_at,
                    remote_item_id=str(item.get("remote_item_id") or "").strip() or None,
                    remote_parent_id=str(item.get("remote_parent_id") or "").strip() or None,
                )
            )

        source_files.sort(key=lambda item: item.relative_path.casefold())

        if total_files_on_disk == 0:
            ignored_reasons.append("No source files were found in the local appliance cache.")
        elif not source_files and ignored_file_count == total_files_on_disk and ignored_file_count > 0:
            ignored_reasons.append("Only generated comment documents or cache files were found.")

        deduped_reasons = self._dedupe_messages(ignored_reasons)
        return SourceScanResult(
            source_files=source_files,
            total_files_on_disk=total_files_on_disk,
            ignored_file_count=ignored_file_count,
            ignored_reasons=deduped_reasons,
            first_20_files_on_disk=first_20_files_on_disk,
            warnings=warnings,
            errors=errors,
            source_inventory_mode="sync_state",
            filesystem_total_files_on_disk=0,
            state_total_files_on_disk=total_files_on_disk,
            state_path=state_path,
        )

    def _inspect_source_files(self, project_path: Path, *, state_path: Path | None = None) -> SourceScanResult:
        filesystem_inspection = self._inspect_source_files_from_filesystem(project_path)
        inferred_state_path = state_path or _infer_sync_state_path(project_path)
        state_inspection = self._inspect_source_files_from_state(project_path, inferred_state_path) if inferred_state_path is not None else None

        if state_inspection is None:
            filesystem_inspection.state_total_files_on_disk = 0
            filesystem_inspection.state_path = inferred_state_path
            return filesystem_inspection

        filesystem_inspection.state_total_files_on_disk = state_inspection.total_files_on_disk
        filesystem_inspection.state_path = inferred_state_path
        state_inspection.filesystem_total_files_on_disk = filesystem_inspection.total_files_on_disk

        filesystem_count = len(filesystem_inspection.source_files)
        state_count = len(state_inspection.source_files)
        if state_count > filesystem_count:
            state_inspection.filesystem_total_files_on_disk = filesystem_inspection.total_files_on_disk
            return state_inspection

        filesystem_inspection.source_inventory_mode = "filesystem"
        return filesystem_inspection

    def _scan_source_files(self, project_path: Path, *, state_path: Path | None = None) -> tuple[list[SourceFileRecord], list[str], list[str]]:
        inspection = self._inspect_source_files(project_path, state_path=state_path)
        return inspection.source_files, inspection.warnings, inspection.errors

    def _file_open_url(self, project_name: str, relative_path: str) -> str:
        return f"/api/projects/{quote(project_name, safe='')}/files/open?path={quote(relative_path, safe='')}"

    def _file_download_url(self, project_name: str, relative_path: str) -> str:
        return f"/api/projects/{quote(project_name, safe='')}/files/download?path={quote(relative_path, safe='')}"

    def _normalize_project_relative_path(self, value: str) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw:
            return ""
        if raw.startswith("/") or Path(raw).is_absolute():
            raise ProjectFileNotFoundError("Absolute paths are not allowed.")
        text = raw.strip("/")
        if not text:
            return ""
        path = Path(text)
        parts = [part for part in path.parts if part not in {"", "."}]
        if any(part == ".." for part in parts):
            raise ProjectFileNotFoundError("Parent path traversal is not allowed.")
        return Path(*parts).as_posix() if parts else ""

    def _allowed_file_roots(self, record: ProjectRecord) -> list[Path]:
        roots: list[Path] = []
        for candidate in [record.project_path]:
            try:
                roots.append(candidate.expanduser().resolve(strict=False))
            except Exception as exc:
                logger.warning("Unable to resolve allowed file root %s: %s", candidate, exc)
        return roots

    def _project_write_root(self, record: ProjectRecord) -> Path:
        if record.project_path.exists() and record.project_path.is_dir():
            return record.project_path.expanduser().resolve(strict=False)
        return (self.settings.resolved_appliance_root() / LOCAL_UPLOADS_RELATIVE_ROOT / record.project_name).resolve(strict=False)

    def _local_upload_source_files(self, record: ProjectRecord) -> list[SourceFileRecord]:
        upload_root = self.settings.resolved_appliance_root() / LOCAL_UPLOADS_RELATIVE_ROOT / record.project_name
        if not upload_root.exists() or not upload_root.is_dir():
            return []
        inspection = self._inspect_source_files_from_filesystem(upload_root)
        return inspection.source_files

    def _clean_project_name(self, value: str) -> str:
        cleaned = str(value or "").strip().replace("\\", " ").replace("/", " ")
        if not cleaned or cleaned in {".", ".."}:
            raise ProjectWriteError("Project name is required.")
        if any(char in cleaned for char in "\0"):
            raise ProjectWriteError("Project name contains invalid characters.")
        return cleaned

    def _clean_folder_name(self, value: str) -> str:
        cleaned = str(value or "").strip().replace("\\", " ").replace("/", " ")
        if not cleaned or cleaned in {".", ".."}:
            raise ProjectWriteError("Folder name is required.")
        if any(char in cleaned for char in "\0"):
            raise ProjectWriteError("Folder name contains invalid characters.")
        return cleaned

    def _project_template_folders(self, folders: list[str] | None) -> list[str]:
        requested = [folder for folder in folders or [] if str(folder).strip()]
        values = requested or list(DEFAULT_PROJECT_FOLDERS)
        deduped: list[str] = []
        seen: set[str] = set()
        for folder in values:
            normalized = self._normalize_project_relative_path(folder)
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped

    def _hidden_projects_path(self) -> Path:
        return self.settings.resolved_appliance_root() / HIDDEN_PROJECTS_STATE_RELATIVE_PATH

    def _hidden_project_names(self) -> set[str]:
        path = self._hidden_projects_path()
        if not path.exists() or not path.is_file():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Unable to read hidden projects state %s: %s", path, exc)
            return set()
        raw_projects = payload.get("projects") if isinstance(payload, dict) else payload
        names: set[str] = set()
        if isinstance(raw_projects, list):
            for item in raw_projects:
                if isinstance(item, str):
                    names.add(_normalize_name(item))
                elif isinstance(item, dict):
                    name = str(item.get("name") or item.get("normalized_name") or "").strip()
                    if name:
                        names.add(_normalize_name(name))
        return names

    def _write_hidden_project_names(self, names: set[str]) -> None:
        path = self._hidden_projects_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"projects": sorted(name for name in names if name)}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _hide_project(self, project_name: str) -> None:
        names = self._hidden_project_names()
        names.add(_normalize_name(project_name))
        self._write_hidden_project_names(names)

    def _unhide_project(self, project_name: str) -> None:
        names = self._hidden_project_names()
        normalized = _normalize_name(project_name)
        if normalized not in names:
            return
        names.remove(normalized)
        self._write_hidden_project_names(names)

    def _state_database_paths(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        for runtime_root in self.settings.runtime_roots():
            if not runtime_root.exists() or not runtime_root.is_dir():
                continue
            for database_path in runtime_root.rglob(LIGHTWEIGHT_STATE_DB_FILENAME):
                resolved = database_path.expanduser().resolve(strict=False)
                key = resolved.as_posix()
                if key in seen:
                    continue
                seen.add(key)
                paths.append(resolved)
        return paths

    def _state_row_matches_project(self, row: sqlite3.Row, normalized_project_name: str) -> bool:
        values = [
            str(_row_value(row, "project_name", "") or "").strip(),
            Path(str(_row_value(row, "remote_root_path", "") or "").strip()).name,
            Path(str(_row_value(row, "local_project_root", "") or "").strip()).name,
        ]
        return any(_normalize_name(value) == normalized_project_name for value in values if value)

    def _delete_project_state_rows(self, database_path: Path, normalized_project_name: str) -> tuple[int, list[Path]]:
        try:
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
        except Exception as exc:
            logger.warning("Unable to open runtime state database %s for cleanup: %s", database_path, exc)
            return 0, []

        removed_paths: list[Path] = []
        rowids: list[int] = []
        try:
            rows = connection.execute("SELECT rowid, * FROM projects").fetchall()
        except Exception as exc:
            logger.warning("Unable to read runtime state database %s for cleanup: %s", database_path, exc)
            connection.close()
            return 0, []

        for row in rows:
            if not self._state_row_matches_project(row, normalized_project_name):
                continue
            rowid = _parse_int(_row_value(row, "rowid"), -1)
            if rowid >= 0:
                rowids.append(rowid)
            local_project_root = str(_row_value(row, "local_project_root", "") or "").strip()
            if local_project_root:
                removed_paths.append(Path(local_project_root).expanduser())
                inferred_state_path = _infer_sync_state_path(Path(local_project_root).expanduser())
                if inferred_state_path is not None:
                    removed_paths.append(inferred_state_path)
            state_path = str(_row_value(row, "state_path", "") or "").strip()
            if state_path:
                removed_paths.append(Path(state_path).expanduser())

        for rowid in rowids:
            try:
                connection.execute("DELETE FROM projects WHERE rowid = ?", (rowid,))
            except Exception as exc:
                logger.warning("Unable to delete project state row %s from %s: %s", rowid, database_path, exc)
        if rowids:
            connection.commit()
        connection.close()
        return len(rowids), removed_paths

    def _local_cache_delete_roots(self) -> list[Path]:
        appliance_root = self.settings.resolved_appliance_root()
        roots = [
            appliance_root / "cache",
            appliance_root / "outputs",
            *self.settings.runtime_roots(),
        ]
        return [root.expanduser().resolve(strict=False) for root in roots]

    def _remove_local_cache_path(self, path: Path, *, allowed_roots: list[Path]) -> str | None:
        resolved = path.expanduser().resolve(strict=False)
        if not resolved.exists():
            return None
        if not any(resolved != root and resolved.is_relative_to(root) for root in allowed_roots):
            logger.warning("Refusing to remove local cache path outside allowed roots: %s", resolved)
            return None
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        return resolved.as_posix()

    def _build_file_tree(self, project_name: str, files: list[SourceFileRecord]) -> ProjectFileNode:
        root = ProjectFileNode(name=project_name, path=".", relative_path="", display_name=project_name, kind="folder")
        folder_nodes: dict[str, ProjectFileNode] = {".": root}

        for source_file in files:
            relative_path = Path(source_file.relative_path)
            parent = root
            accumulated_parts: list[str] = []

            for segment in relative_path.parts[:-1]:
                accumulated_parts.append(segment)
                node_path = "/".join(accumulated_parts)
                if node_path not in folder_nodes:
                    folder_node = ProjectFileNode(
                        name=segment,
                        path=node_path,
                        relative_path=node_path,
                        display_name=segment,
                        kind="folder",
                        folder_category=_project_folder_category(Path(node_path)),
                    )
                    folder_nodes[node_path] = folder_node
                    parent.children.append(folder_node)
                parent = folder_nodes[node_path]

            file_node = ProjectFileNode(
                name=relative_path.name,
                path=source_file.relative_path,
                relative_path=source_file.relative_path,
                display_name=relative_path.name,
                kind="file",
                folder_category=source_file.folder_category,
                extension=source_file.extension,
                size_bytes=source_file.size_bytes,
                modified_at=source_file.modified_at,
                open_url=self._file_open_url(project_name, source_file.relative_path),
                download_url=self._file_download_url(project_name, source_file.relative_path),
                file_count=1,
            )
            parent.children.append(file_node)

        self._finalize_tree_node(root)
        return root

    def _finalize_tree_node(self, node: ProjectFileNode) -> int:
        if node.kind == "file":
            node.file_count = 1
            return 1

        node.children.sort(
            key=lambda child: (
                0 if child.kind == "folder" else 1,
                child.name.casefold(),
            )
        )
        total = 0
        for child in node.children:
            total += self._finalize_tree_node(child)
        node.file_count = total
        return total

    def _build_file_filters(self, files: list[SourceFileRecord]) -> ProjectFileFilters:
        category_counts: Counter[str] = Counter()
        extension_counts: Counter[str] = Counter()
        for file_record in files:
            category_counts[file_record.folder_category] += 1
            extension = file_record.extension or ""
            extension_counts[extension] += 1

        folder_categories = [
            CountFacet(value=value, label=SOURCE_CATEGORY_LABELS[value], count=count)
            for value, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        extensions = [
            CountFacet(value=value or "(no extension)", label=value or "(no extension)", count=count)
            for value, count in sorted(extension_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        return ProjectFileFilters(folder_categories=folder_categories, extensions=extensions)

    def _dedupe_messages(self, messages: Iterable[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for message in messages:
            text = str(message).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    def _latest_datetime(self, values: Iterable[datetime | None]) -> datetime | None:
        latest: datetime | None = None
        for value in values:
            if value is None:
                continue
            if latest is None or value > latest:
                latest = value
        return latest

    def _record_happened_since(self, record: ProjectRecord, cutoff: datetime) -> bool:
        timestamp = self._latest_datetime(
            [
                record.last_synced_at,
                record.latest_comment_created_at,
                record.latest_comment_modified_at,
                record.sort_timestamp,
            ]
        )
        return timestamp is not None and timestamp >= cutoff

    def _record_analysis_happened_since(self, record: ProjectRecord, cutoff: datetime) -> bool:
        timestamp = (
            (record.analysis.last_analyzed_at if record.analysis is not None else None)
            or record.last_analyzed_at
            or record.sort_timestamp
        )
        return timestamp is not None and timestamp >= cutoff

    def _record_error_count_since(self, record: ProjectRecord, cutoff: datetime) -> int:
        count = len(record.errors) if self._record_happened_since(record, cutoff) else 0
        if self._record_analysis_happened_since(record, cutoff):
            analysis_count = record.analysis.errors_count if record.analysis is not None else 0
            count += max(analysis_count, 1 if _status_is_error(record.status) else 0)
        return count

    def _record_warning_count_since(self, record: ProjectRecord, cutoff: datetime) -> int:
        count = len(record.warnings) if self._record_happened_since(record, cutoff) else 0
        if self._record_analysis_happened_since(record, cutoff):
            analysis_count = record.analysis.warnings_count if record.analysis is not None else 0
            count += max(analysis_count, 1 if _status_is_warning(record.status) else 0)
        return count

    def _disk_usage(self, appliance_root: Path) -> tuple[int | None, int | None, int | None]:
        target = appliance_root if appliance_root.exists() else appliance_root.parent
        try:
            usage = shutil.disk_usage(target)
        except Exception as exc:
            logger.warning("Unable to inspect disk usage for %s: %s", target, exc)
            return None, None, None
        return usage.total, usage.used, usage.free

    def _directory_size_bytes(self, root: Path) -> int:
        if not root.exists():
            return 0

        total = 0
        try:
            iterator = root.rglob("*")
            for path in iterator:
                if not path.is_file():
                    continue
                try:
                    total += path.stat().st_size
                except Exception as exc:
                    logger.warning("Unable to inspect cache file %s: %s", path, exc)
        except Exception as exc:
            logger.warning("Unable to inspect cache directory %s: %s", root, exc)
        return total

    def _cache_size_bytes(self, appliance_root: Path) -> int:
        cache_roots = [appliance_root / "cache", *self.settings.runtime_roots()]
        seen: set[str] = set()
        total = 0
        for root in cache_roots:
            resolved = root.expanduser().resolve(strict=False)
            key = resolved.as_posix()
            if key in seen:
                continue
            seen.add(key)
            total += self._directory_size_bytes(resolved)
        return total

    def _onedrive_status(self, appliance_root: Path, records: list[ProjectRecord]) -> str:
        if not appliance_root.exists() or not appliance_root.is_dir():
            return "unavailable"
        if records:
            return "available"
        return "warning"

    def _onedrive_detail(self, appliance_root: Path, records: list[ProjectRecord]) -> str:
        if not appliance_root.exists() or not appliance_root.is_dir():
            return "Appliance-root finnes ikke på disk."
        if records:
            return f"{len(records)} prosjekter funnet i lokal OneDrive-cache."
        return "Ingen prosjekter funnet i lokal OneDrive-cache."

    def _graph_write_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(_read_env_file(self.settings.resolved_appliance_root() / ".env"))
        return env

    def _graph_write_status(self) -> str:
        return "not_configured" if _missing_graph_write_env(self._graph_write_env()) else "configured"

    def _graph_write_detail(self) -> str:
        missing = _missing_graph_write_env(self._graph_write_env())
        if missing:
            return "Microsoft Graph-write mangler konfigurasjon: " + ", ".join(missing)
        return "Microsoft Graph-write er konfigurert for direkte OneDrive-opprettelse."

    def _appliance_repo_root(self) -> Path:
        return self.settings.resolved_appliance_root()

    def _sync_python(self) -> Path:
        appliance_python = self._appliance_repo_root() / ".venv" / "bin" / "python"
        if appliance_python.exists():
            return appliance_python
        return Path(sys.executable)

    def _sync_script_path(self) -> Path:
        return self._appliance_repo_root() / "scripts" / "run_onedrive_appliance.py"

    def _sync_only_supported(self) -> bool:
        script_path = self._sync_script_path()
        if not script_path.exists() or not script_path.is_file():
            return False
        try:
            script_text = script_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Unable to inspect appliance sync script %s: %s", script_path, exc)
            return False
        return "--sync-only" in script_text

    def _require_sync_only_available(self) -> None:
        if self._sync_only_supported():
            return
        raise SyncOnlyUnavailableError(
            "Nexus kan ikke synkronisere trygt før appliance støtter sync-only. Full analysepipeline er blokkert fra Nexus."
        )

    def _analysis_supported(self) -> bool:
        script_path = self._sync_script_path()
        if not script_path.exists() or not script_path.is_file():
            return False
        try:
            script_text = script_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Unable to inspect appliance analysis script %s: %s", script_path, exc)
            return False
        required_flags = ("--force-analyze", "--provider", "--email-mode")
        return all(flag in script_text for flag in required_flags)

    def _require_analysis_available(self) -> None:
        if self._analysis_supported():
            return
        raise AnalysisUnavailableError(
            "Nexus kan ikke starte analyse før appliance støtter full analysepipeline."
        )

    def _sync_command(self, *, project_name: str | None = None) -> list[str]:
        script_path = self._sync_script_path()
        command = [
            str(self._sync_python()),
            str(script_path),
            "--once",
            "--all-roots",
            "--sync-only",
            "--trigger-source",
            "nexus_sync",
            "--started-by",
            "nexus-web",
            "--company-root",
            self.settings.onedrive_project_root(),
        ]
        if project_name:
            command.extend(["--include-root-folder", project_name])
        return command

    def _validate_nexus_sync_command(self, command: list[str]) -> None:
        command_values = [str(value) for value in command]
        if "--sync-only" not in command_values:
            raise SyncOnlyUnavailableError(
                "Nexus kan ikke synkronisere trygt før appliance støtter sync-only. Full analysepipeline er blokkert fra Nexus."
            )

        forbidden_flags = {"--force-analyze", "--report-type", "--model", "--create-missing-folders", "--local-output-mode"}
        for flag in forbidden_flags:
            if flag in command_values:
                raise ProjectSyncError(f"Nexus sync-kommando inneholder forbudt analyseargument: {flag}")

        if "--provider" in command_values:
            provider_index = command_values.index("--provider")
            provider_value = command_values[provider_index + 1] if provider_index + 1 < len(command_values) else ""
            raise ProjectSyncError(f"Nexus sync-kommando inneholder forbudt provider-argument: --provider {provider_value}".strip())

        if "--email-mode" in command_values:
            email_index = command_values.index("--email-mode")
            email_mode = command_values[email_index + 1] if email_index + 1 < len(command_values) else ""
            if email_mode in {"immediate", "daily_digest"}:
                raise ProjectSyncError(f"Nexus sync-kommando inneholder forbudt email-mode: {email_mode}")

        trigger_index = command_values.index("--trigger-source") if "--trigger-source" in command_values else -1
        if trigger_index < 0 or trigger_index + 1 >= len(command_values) or command_values[trigger_index + 1] != "nexus_sync":
            raise ProjectSyncError("Nexus sync-kommando mangler strukturert trigger-source nexus_sync")
        started_by_index = command_values.index("--started-by") if "--started-by" in command_values else -1
        if started_by_index < 0 or started_by_index + 1 >= len(command_values) or command_values[started_by_index + 1] != "nexus-web":
            raise ProjectSyncError("Nexus sync-kommando mangler strukturert started-by nexus-web")

    def _normalize_email_mode(self, email_mode: str | None) -> str:
        normalized = str(email_mode or "").strip().casefold()
        if normalized not in {"daily_digest", "immediate"}:
            raise AnalysisUnavailableError(f"Ugyldig email-mode for analyse: {email_mode}")
        return normalized

    def _analysis_command(self, *, project_name: str | None, email_mode: str) -> list[str]:
        script_path = self._sync_script_path()
        command = [
            str(self._sync_python()),
            str(script_path),
            "--once",
            "--all-roots",
            "--force-analyze",
            "--provider",
            "openai",
            "--analysis-profile",
            "enterprise_review",
            "--report-type",
            "enterprise_review",
            "--email-mode",
            email_mode,
            "--trigger-source",
            "nexus_analysis",
            "--started-by",
            "nexus-web",
            "--company-root",
            self.settings.onedrive_project_root(),
        ]
        if project_name:
            command.extend(["--include-root-folder", project_name])
        return command

    def _validate_nexus_analysis_command(self, command: list[str]) -> None:
        command_values = [str(value) for value in command]
        if "--force-analyze" not in command_values:
            raise AnalysisUnavailableError(
                "Nexus kan ikke starte analyse før appliance støtter full analysepipeline."
            )
        if "--provider" not in command_values:
            raise AnalysisUnavailableError("Nexus analysekommando mangler Microsoft Graph/LLM-provider.")
        provider_index = command_values.index("--provider")
        provider_value = command_values[provider_index + 1] if provider_index + 1 < len(command_values) else ""
        if provider_value != "openai":
            raise AnalysisUnavailableError(f"Nexus analysekommando må bruke OpenAI, ikke {provider_value!r}.")
        if "--email-mode" not in command_values:
            raise AnalysisUnavailableError("Nexus analysekommando mangler email-mode.")
        email_index = command_values.index("--email-mode")
        email_mode = command_values[email_index + 1] if email_index + 1 < len(command_values) else ""
        if email_mode not in {"daily_digest", "immediate"}:
            raise AnalysisUnavailableError(f"Nexus analysekommando bruker ugyldig email-mode: {email_mode}")
        trigger_index = command_values.index("--trigger-source") if "--trigger-source" in command_values else -1
        if trigger_index < 0 or trigger_index + 1 >= len(command_values) or command_values[trigger_index + 1] != "nexus_analysis":
            raise AnalysisUnavailableError("Nexus analysekommando mangler strukturert trigger-source nexus_analysis")
        forbidden_flags = {"--sync-only"}
        for flag in forbidden_flags:
            if flag in command_values:
                raise AnalysisUnavailableError(f"Nexus analysekommando inneholder forbudt flagg: {flag}")

    def _refresh_sync_state_locked(self, *, snapshot: RuntimeActivitySnapshot | None = None) -> None:
        snapshot = snapshot or self._runtime_activity_snapshot_locked()
        process = self._sync_state.process
        self._sync_state.running = snapshot.sync_running
        if snapshot.sync_running:
            self._sync_state.status = "running"
            return
        if process is None:
            if self._sync_state.status == "running":
                self._sync_state.status = "idle"
            return
        self._sync_state.running = False
        if self._sync_state.status == "running":
            self._sync_state.status = "completed" if process.returncode == 0 else "failed"

    def _refresh_analysis_state_locked(self, *, snapshot: RuntimeActivitySnapshot | None = None) -> None:
        snapshot = snapshot or self._runtime_activity_snapshot_locked()
        process = self._analysis_state.process
        self._analysis_state.running = snapshot.analysis_running
        if snapshot.analysis_running:
            self._analysis_state.status = "running"
            return
        if process is None:
            if self._analysis_state.status == "running":
                self._analysis_state.status = "idle"
            return
        self._analysis_state.running = False
        if self._analysis_state.status == "running":
            self._analysis_state.status = "completed" if process.returncode == 0 else "failed"

    def _monitor_sync_process(self, job_id: str, process: subprocess.Popen[str]) -> None:
        stdout, stderr = process.communicate()
        completed_at = datetime.now(OSLO_TIMEZONE)
        summary = self._parse_sync_summary(stdout)
        with self._sync_lock:
            if self._sync_state.job_id != job_id:
                return
            self._sync_state.running = False
            self._sync_state.process = process
            self._sync_state.last_completed_at = completed_at
            self._sync_state.projects_synced = summary.get("projects_synced", 0)
            self._sync_state.files_changed = summary.get("files_changed", 0)
            self._sync_state.reports_found = summary.get("reports_found", 0)
            self._sync_state.current_project = summary.get("current_project") or self._sync_state.current_project
            self._sync_state.project_name = self._sync_state.current_project
            self._sync_state.current_phase = summary.get("current_phase") or "Fullfører synkronisering"
            self._sync_state.progress = summary.get("progress")
            self._sync_state.appliance_run_id = summary.get("appliance_run_id") or self._sync_state.appliance_run_id
            self._sync_state.sync_strategy = summary.get("sync_strategy", "unknown")
            self._sync_state.sync_strategy_reason = summary.get("sync_strategy_reason")
            self._sync_state.remote_items_examined = summary.get("remote_items_examined", 0)
            self._sync_state.files_downloaded = summary.get("files_downloaded", 0)
            self._sync_state.files_deleted = summary.get("files_deleted", 0)
            self._sync_state.elapsed_seconds = summary.get("elapsed_seconds")
            self._sync_state.performance = summary.get("performance")
            if process.returncode == 0:
                self._sync_state.status = "completed"
                self._sync_state.last_error = None
                self._sync_state.progress = 100.0
                self._sync_state.event_code = "sync_completed_no_changes" if self._sync_state.files_changed == 0 else "sync_completed"
                self._sync_state.current_phase = (
                    "Synkronisering fullført uten endringer"
                    if self._sync_state.files_changed == 0
                    else "Synkronisering fullført"
                )
                self._write_activity_journal(
                    level="SUCCESS",
                    message=(
                        "Sync completed with no changes"
                        if self._sync_state.files_changed == 0
                        else f"Finished sync ({summary.get('files_changed', 0)} files changed)"
                    ),
                    project_name=self._sync_state.project_name,
                    component="OneDrive",
                    kind="log",
                    details=self._job_details(self._sync_state) | self._sync_summary_details(summary),
                )
            else:
                self._sync_state.status = "failed"
                self._sync_state.last_error = (stderr or stdout or "OneDrive sync failed.").strip()[-2000:]
                self._sync_state.event_code = "sync_failed"
                self._sync_state.current_phase = "Synkronisering feilet"
                self._write_activity_journal(
                    level="ERROR",
                    message=self._sync_state.last_error,
                    project_name=self._sync_state.project_name,
                    component="OneDrive",
                    kind="error",
                    details=self._job_details(self._sync_state) | self._sync_summary_details(summary),
                )
            self._job_history.append(replace(self._sync_state, process=None))
        self._invalidate_health_cache()
        self._invalidate_activity_cache()

    def _monitor_analysis_process(self, job_id: str, process: subprocess.Popen[str]) -> None:
        stdout, stderr = process.communicate()
        completed_at = datetime.now(OSLO_TIMEZONE)
        summary = self._parse_cycle_summary(stdout)
        error_text = (stderr or stdout or "").strip() or None
        with self._analysis_lock:
            if self._analysis_state.job_id != job_id:
                return
            self._analysis_state.running = False
            self._analysis_state.process = process
            self._analysis_state.process_spawned = False
            self._analysis_state.last_completed_at = completed_at
            self._analysis_state.projects_synced = summary.get("projects_synced", 0)
            self._analysis_state.files_changed = summary.get("files_changed", 0)
            self._analysis_state.reports_found = summary.get("reports_found", 0)
            self._analysis_state.reports_generated = summary.get("reports_generated", 0)
            self._analysis_state.email_mode = summary.get("email_mode") or self._analysis_state.email_mode
            self._analysis_state.project_name = summary.get("project_name") or self._analysis_state.project_name
            self._analysis_state.current_project = self._analysis_state.project_name
            self._analysis_state.current_phase = summary.get("current_phase") or self._analysis_state.current_phase
            self._analysis_state.progress = summary.get("progress")
            self._analysis_state.appliance_run_id = summary.get("appliance_run_id") or self._analysis_state.appliance_run_id
            if process.returncode == 0:
                self._analysis_state.status = "completed"
                self._analysis_state.auth_status = "ok"
                self._analysis_state.last_error = None
                self._analysis_state.last_start_error = None
                self._analysis_state.progress = 100.0
                self._analysis_state.event_code = "analysis_completed"
                self._analysis_state.current_phase = "Analyse fullført"
                success_message = "Generated report" if summary.get("reports_generated", 0) > 0 else "Finished analysis"
                if summary.get("email_mode"):
                    success_message = "Email sent" if summary.get("reports_generated", 0) > 0 else success_message
                self._write_activity_journal(
                    level="SUCCESS",
                    message=success_message,
                    project_name=self._analysis_state.project_name,
                    component="Analysis",
                    kind="log",
                    details=self._job_details(self._analysis_state) | summary,
                )
            else:
                status, auth_status = _classify_analysis_error(error_text or "Appliance analysis failed.")
                self._analysis_state.status = status
                self._analysis_state.auth_status = auth_status
                self._analysis_state.last_error = (error_text or "Appliance analysis failed.")[-2000:]
                self._analysis_state.event_code = "analysis_failed"
                self._analysis_state.current_phase = "Analyse feilet"
                self._write_activity_journal(
                    level="ERROR",
                    message=self._analysis_state.last_error,
                    project_name=self._analysis_state.project_name,
                    component="Analysis",
                    kind="error",
                    details=self._job_details(self._analysis_state),
                )
            self._job_history.append(replace(self._analysis_state, process=None))
        self._invalidate_health_cache()
        self._invalidate_activity_cache()

    def _parse_sync_summary(self, stdout: str) -> dict[str, Any]:
        parsed = self._parse_cycle_summary(stdout)
        return {
            "projects_synced": parsed.get("projects_synced", 0),
            "files_changed": parsed.get("files_changed", 0),
            "reports_found": parsed.get("reports_found", 0),
            "current_project": parsed.get("current_project"),
            "current_phase": parsed.get("current_phase"),
            "progress": parsed.get("progress"),
            "appliance_run_id": parsed.get("appliance_run_id"),
            "sync_strategy": parsed.get("sync_strategy", "unknown"),
            "sync_strategy_reason": parsed.get("sync_strategy_reason"),
            "remote_items_examined": parsed.get("remote_items_examined", 0),
            "files_downloaded": parsed.get("files_downloaded", 0),
            "files_deleted": parsed.get("files_deleted", 0),
            "elapsed_seconds": parsed.get("elapsed_seconds"),
            "performance": parsed.get("performance"),
        }

    def _parse_cycle_summary(self, stdout: str) -> dict[str, Any]:
        payload = self._last_json_object(stdout)
        per_root_results = payload.get("per_root_results") if isinstance(payload, dict) else None
        summary: dict[str, Any] = {
            "projects_synced": 0,
            "files_changed": 0,
            "reports_found": 0,
            "reports_generated": 0,
            "email_mode": None,
            "project_name": None,
            "status": "unknown",
            "current_project": None,
            "current_phase": None,
            "progress": None,
            "appliance_run_id": None,
            "sync_strategy": "unknown",
            "sync_strategy_reason": None,
            "remote_items_examined": 0,
            "files_downloaded": 0,
            "files_deleted": 0,
            "elapsed_seconds": None,
            "performance": None,
        }
        if not isinstance(payload, dict):
            return summary

        uploaded_reports = payload.get("uploaded_reports")
        reports_generated_explicit = payload.get("reports_generated")
        if reports_generated_explicit is not None:
            summary["reports_generated"] = _parse_int(reports_generated_explicit, 0)
        elif isinstance(uploaded_reports, list):
            summary["reports_generated"] = len(uploaded_reports)

        email_mode = str(payload.get("email_mode") or "").strip() or None
        project_name = str(payload.get("project_name") or "").strip() or None
        status = str(payload.get("email_status") or payload.get("status") or "").strip() or "unknown"
        summary["email_mode"] = email_mode
        summary["project_name"] = project_name
        summary["status"] = status
        summary["current_project"] = self._payload_text(payload, "current_project", "project_name")
        summary["current_phase"] = self._payload_text(payload, "current_phase", "phase")
        summary["appliance_run_id"] = self._payload_text(payload, "appliance_run_id", "run_id")
        summary["progress"] = self._payload_progress(payload)
        summary["sync_strategy"] = self._normalize_sync_strategy(payload.get("sync_strategy"))
        summary["sync_strategy_reason"] = self._payload_text(payload, "sync_strategy_reason", "strategy_reason", "fallback_reason")
        summary["remote_items_examined"] = _parse_int(payload.get("remote_items_examined"), 0)
        summary["files_downloaded"] = _parse_int(payload.get("files_downloaded"), 0)
        summary["files_deleted"] = _parse_int(payload.get("files_deleted"), 0)
        summary["elapsed_seconds"] = self._payload_float(payload.get("elapsed_seconds") or payload.get("duration_seconds"))
        summary["performance"] = self._parse_sync_performance(payload)

        if not isinstance(per_root_results, list):
            summary["projects_synced"] = _parse_int(payload.get("projects_synced"), 0)
            summary["files_changed"] = _parse_int(
                payload.get("files_changed"),
                _parse_int(payload.get("total_changed_files"), _parse_int(payload.get("downloaded_files"), 0)),
            )
            summary["reports_found"] = _parse_int(payload.get("reports_found"), 0)
            return summary

        projects_synced = 0
        files_changed = 0
        reports_found = 0
        reports_generated = summary["reports_generated"]
        explicit_reports_generated = reports_generated_explicit is not None
        root_metric_totals = {
            "remote_items_examined": 0,
            "files_downloaded": 0,
            "files_deleted": 0,
        }
        root_metric_seen = {key: False for key in root_metric_totals}
        root_performance_totals: dict[str, float | int] = {}
        root_performance_seen = False
        root_strategies: list[str] = []
        root_strategy_reasons: list[str] = []
        root_project_names: list[str] = []
        root_run_ids: list[str] = []
        for item in per_root_results:
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "") or "").casefold() != "failed":
                projects_synced += 1
            item_project = self._payload_text(item, "current_project", "project_name", "root_name")
            if item_project:
                root_project_names.append(item_project)
            item_run_id = self._payload_text(item, "appliance_run_id", "run_id")
            if item_run_id:
                root_run_ids.append(item_run_id)

            sync_metrics = item.get("sync_metrics")
            sync_metrics = sync_metrics if isinstance(sync_metrics, Mapping) else {}
            changed_value = next(
                (
                    item.get(key)
                    for key in ("files_changed", "changed_files", "total_changed_files", "changed")
                    if item.get(key) is not None
                ),
                None,
            )
            if changed_value is not None:
                files_changed += _parse_int(changed_value, 0)

            metric_values = {
                "remote_items_examined": next(
                    (value for value in (item.get("remote_items_examined"), sync_metrics.get("remote_items_examined")) if value is not None),
                    None,
                ),
                "files_downloaded": next(
                    (
                        value
                        for value in (item.get("files_downloaded"), item.get("downloaded_files"), item.get("downloaded"), sync_metrics.get("files_downloaded"))
                        if value is not None
                    ),
                    None,
                ),
                "files_deleted": next(
                    (
                        value
                        for value in (item.get("files_deleted"), item.get("deleted_files"), item.get("deleted"), sync_metrics.get("files_deleted"))
                        if value is not None
                    ),
                    None,
                ),
            }
            for key, value in metric_values.items():
                if value is not None:
                    root_metric_seen[key] = True
                    root_metric_totals[key] += _parse_int(value, 0)

            item_strategy = self._normalize_sync_strategy(item.get("sync_strategy") or sync_metrics.get("sync_strategy"))
            if item_strategy != "unknown":
                root_strategies.append(item_strategy)
                item_reason = self._sync_strategy_reason_from_payload(item, strategy=item_strategy)
                if item_reason:
                    root_strategy_reasons.append(item_reason)
            item_performance = self._parse_sync_performance(item)
            if item_performance is not None:
                root_performance_seen = True
                for key in (
                    "total_duration_seconds",
                    "authentication_seconds",
                    "graph_query_seconds",
                    "downloads_seconds",
                    "local_state_update_seconds",
                    "finalization_seconds",
                ):
                    value = getattr(item_performance, key)
                    if value is not None:
                        root_performance_totals[key] = float(root_performance_totals.get(key, 0.0)) + value
                for key in ("graph_requests", "downloaded_bytes"):
                    value = getattr(item_performance, key)
                    if value is not None:
                        root_performance_totals[key] = int(root_performance_totals.get(key, 0)) + value
            if item.get("reports_found") is not None:
                reports_found += _parse_int(item.get("reports_found"), 0)
            else:
                uploaded_reports = item.get("uploaded_reports")
                if isinstance(uploaded_reports, list):
                    reports_found += len(uploaded_reports)
            if not explicit_reports_generated and item.get("reports_generated") is not None:
                reports_generated += _parse_int(item.get("reports_generated"), 0)

        summary["projects_synced"] = projects_synced
        summary["files_changed"] = files_changed
        summary["reports_found"] = reports_found
        summary["reports_generated"] = reports_generated
        for key, value in root_metric_totals.items():
            if root_metric_seen[key]:
                summary[key] = value
        if root_strategies:
            summary["sync_strategy"] = (
                "fallback_full"
                if "fallback_full" in root_strategies
                else "full"
                if "full" in root_strategies
                else "delta"
            )
        if not summary.get("sync_strategy_reason") and root_strategy_reasons:
            summary["sync_strategy_reason"] = root_strategy_reasons[0]
        if not summary.get("current_project") and root_project_names:
            summary["current_project"] = root_project_names[-1]
        if not summary.get("appliance_run_id") and root_run_ids:
            summary["appliance_run_id"] = root_run_ids[-1]
        if root_performance_seen:
            summary["performance"] = SyncPerformance(**root_performance_totals)
        if summary["progress"] is None:
            total_projects = _parse_int(payload.get("total_projects"), _parse_int(payload.get("roots_attempted"), _parse_int(payload.get("total_roots_seen"), 0)))
            completed_projects = _parse_int(
                payload.get("completed_projects"),
                _parse_int(payload.get("roots_synced"), 0) + _parse_int(payload.get("roots_failed"), 0),
            )
            if total_projects <= 0:
                total_projects = len(per_root_results)
            if completed_projects <= 0:
                completed_projects = projects_synced
            if total_projects > 0:
                summary["progress"] = min(100.0, max(0.0, completed_projects / total_projects * 100))
        return summary

    def _payload_text(self, payload: Mapping[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return None

    def _payload_float(self, value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    def _payload_progress(self, payload: Mapping[str, Any]) -> float | None:
        value = payload.get("progress")
        if isinstance(value, Mapping):
            value = next((value.get(key) for key in ("percent", "percentage", "progress") if value.get(key) is not None), None)
        parsed = self._payload_float(value)
        if parsed is None:
            return None
        return min(100.0, parsed if parsed > 1 else parsed * 100)

    def _normalize_sync_strategy(self, value: Any) -> str:
        normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized in {"delta", "delta_sync"}:
            return "delta"
        if normalized in {"full", "full_sync"}:
            return "full"
        if normalized in {"fallback_full", "fallback_full_sync"}:
            return "fallback_full"
        return "unknown"

    def _parse_sync_performance(self, payload: Mapping[str, Any]) -> SyncPerformance | None:
        candidate = payload.get("performance")
        metrics = payload.get("sync_metrics")
        timings = payload.get("timings")
        candidate = candidate if isinstance(candidate, Mapping) else {}
        metrics = metrics if isinstance(metrics, Mapping) else {}
        timings = timings if isinstance(timings, Mapping) else {}
        values: dict[str, Any] = {}
        timing_aliases = {
            "authentication_seconds": ("authentication",),
            "graph_query_seconds": ("graph_query", "graph_traversal", "graph_delta"),
            "downloads_seconds": ("downloads",),
            "local_state_update_seconds": ("local_state_update", "state_persist"),
            "finalization_seconds": ("finalization",),
        }
        for key, aliases in timing_aliases.items():
            direct = candidate.get(key)
            if direct is not None:
                values[key] = self._payload_float(direct)
                continue
            alias_values = [self._payload_float(timings.get(alias)) for alias in aliases]
            numeric_alias_values = [value for value in alias_values if value is not None]
            if numeric_alias_values:
                values[key] = sum(numeric_alias_values)

        total_duration = next(
            (
                self._payload_float(value)
                for value in (
                    candidate.get("total_duration_seconds"),
                    payload.get("elapsed_seconds"),
                    payload.get("duration_seconds"),
                    metrics.get("duration_seconds"),
                )
                if value is not None
            ),
            None,
        )
        if total_duration is not None:
            values["total_duration_seconds"] = total_duration
        graph_requests = next((value for value in (candidate.get("graph_requests"), metrics.get("graph_requests")) if value is not None), None)
        downloaded_bytes = next(
            (
                value
                for value in (candidate.get("downloaded_bytes"), metrics.get("bytes_downloaded"), payload.get("bytes_transferred"))
                if value is not None
            ),
            None,
        )
        if graph_requests is not None:
            values["graph_requests"] = _parse_int(graph_requests, 0)
        if downloaded_bytes is not None:
            values["downloaded_bytes"] = _parse_int(downloaded_bytes, 0)
        return SyncPerformance(**values) if values else None

    def _sync_strategy_reason_from_payload(self, payload: Mapping[str, Any], *, strategy: str) -> str | None:
        reason = self._payload_text(payload, "sync_strategy_reason", "strategy_reason", "fallback_reason", "reason")
        if reason:
            return reason
        event_records = payload.get("event_records")
        if isinstance(event_records, list):
            for event in event_records:
                if not isinstance(event, Mapping):
                    continue
                event_code = str(event.get("event_code") or "").casefold()
                if strategy == "fallback_full" or "fallback" in event_code:
                    reason = self._payload_text(event, "reason", "message")
                    if reason:
                        return reason
        if strategy == "fallback_full":
            return "Delta-synkronisering var ikke tilgjengelig; full gjennomgang ble brukt."
        return None

    def _sync_summary_details(self, summary: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "current_phase": summary.get("current_phase"),
            "current_project": summary.get("current_project"),
            "progress": summary.get("progress"),
            "appliance_run_id": summary.get("appliance_run_id"),
            "sync_strategy": summary.get("sync_strategy", "unknown"),
            "sync_strategy_reason": summary.get("sync_strategy_reason"),
            "remote_items_examined": summary.get("remote_items_examined", 0),
            "files_downloaded": summary.get("files_downloaded", 0),
            "files_deleted": summary.get("files_deleted", 0),
            "elapsed_seconds": summary.get("elapsed_seconds"),
            "performance": summary.get("performance").model_dump(mode="json") if isinstance(summary.get("performance"), SyncPerformance) else summary.get("performance"),
        }

    def _last_json_object(self, text: str) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        best: dict[str, Any] = {}
        best_length = -1
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, end = decoder.raw_decode(text[index:])
            except Exception:
                continue
            if isinstance(value, dict):
                if end > best_length:
                    best = value
                    best_length = end
        return best
