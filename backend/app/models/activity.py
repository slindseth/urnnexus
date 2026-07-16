from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ApiModel
from .operations import SyncPerformance

ActivityCategory = Literal["Sync", "Analysis", "System", "OneDrive", "Report", "Error"]
ActivityState = Literal[
    "Klar",
    "Starter",
    "Starter synkronisering",
    "Kobler til OneDrive",
    "Henter endringer",
    "Synkroniserer prosjekt",
    "Laster ned filer",
    "Oppdaterer lokal status",
    "Fullfører synkronisering",
    "Synkronisering fullført",
    "Synkronisering fullført uten endringer",
    "Synkronisering feilet",
    "Synkroniserer",
    "Analyserer",
    "Genererer rapport",
    "Sender e-post",
    "Feilet",
]
ActivityLevel = Literal["INFO", "SUCCESS", "WARNING", "ERROR"]


class ActivityStatusResponse(ApiModel):
    state: ActivityState
    activity: str | None = None
    status: str | None = None
    project_name: str | None = None
    uptime: str
    uptime_seconds: float
    backend_version: str | None = None
    appliance_available: bool = False
    last_synced_at: datetime | None = None
    last_analyzed_at: datetime | None = None
    updated_at: datetime
    job_type: Literal["sync", "analysis"] | None = None
    job_id: str | None = None
    run_mode: Literal["sync_only", "analysis", "unknown"] = "unknown"
    event_code: str | None = None
    current_phase: str | None = None
    current_project: str | None = None
    progress: float | None = None
    sync_strategy: Literal["delta", "full", "fallback_full", "unknown"] = "unknown"
    sync_strategy_reason: str | None = None
    performance: SyncPerformance | None = None


class ActivityEvent(ApiModel):
    timestamp: datetime
    level: ActivityLevel
    project_name: str | None = None
    component: str | None = None
    message: str
    category: ActivityCategory = "System"
    source: str | None = None
    event_code: str | None = None
    phase: str | None = None
    run_mode: Literal["sync_only", "analysis", "unknown"] = "unknown"
    job_type: Literal["sync", "analysis"] | None = None
    job_id: str | None = None


class ActivityError(ApiModel):
    timestamp: datetime
    project_name: str | None = None
    component: str | None = None
    message: str
    category: Literal["Error"] = "Error"
    source: str | None = None
    event_code: str | None = None
    phase: str | None = None
    run_mode: Literal["sync_only", "analysis", "unknown"] = "unknown"
    job_type: Literal["sync", "analysis"] | None = None
    job_id: str | None = None


class ActivityEventsResponse(ApiModel):
    updated_at: datetime
    events: list[ActivityEvent] = Field(default_factory=list)
    errors: list[ActivityError] = Field(default_factory=list)


class ActivityLogEntry(ApiModel):
    timestamp: datetime
    level: ActivityLevel
    project_name: str | None = None
    component: str | None = None
    message: str
    category: ActivityCategory = "System"
    source: str | None = None
    event_code: str | None = None
    phase: str | None = None
    run_mode: Literal["sync_only", "analysis", "unknown"] = "unknown"
    job_type: Literal["sync", "analysis"] | None = None
    job_id: str | None = None


class ActivityLogsResponse(ApiModel):
    updated_at: datetime
    entries: list[ActivityLogEntry] = Field(default_factory=list)
