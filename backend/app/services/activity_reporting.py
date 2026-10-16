"""Read-only projections of appliance evidence. No inference from process success."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


def stable_id(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def sync_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    roots = payload.get("per_root_results")
    projects = (
        [sync_evidence(row) for row in roots if isinstance(row, Mapping)]
        if isinstance(roots, list)
        else []
    )
    status = payload.get("sync_status", "unknown")
    if status not in {"complete", "incomplete", "failed"}:
        status = "unknown"
    enumeration = payload.get("enumeration_complete")
    if enumeration is False or payload.get("skip_reason") == "sync_incomplete":
        status = "failed" if status == "failed" else "incomplete"
    if projects:
        states = {row["sync_status"] for row in projects}
        if "failed" in states:
            status = "failed"
        elif "incomplete" in states:
            status = "incomplete"
        elif "unknown" in states and status == "complete":
            status = "unknown"
        elif states == {"complete"} and status == "unknown":
            status = "complete"
        if any(row["enumeration_complete"] is False for row in projects):
            enumeration = False
        elif all(row["enumeration_complete"] is True for row in projects):
            enumeration = True
    # Zero downloads says nothing about changed, deleted or renamed files.
    changes = next(
        (
            payload[k]
            for k in ("files_changed", "total_changed_files", "changed")
            if k in payload
        ),
        None,
    )
    counters = [payload.get(k) for k in ("downloaded", "deleted", "renamed")]
    if changes is None and all(isinstance(v, (int, float)) for v in counters):
        changes = sum(counters)
    # Any explicit mutation contradicts a zero change total, even if a legacy
    # producer counted only content changes in `changed`.
    mutation_counts = [
        payload.get(k)
        for k in (
            "downloaded",
            "files_downloaded",
            "deleted",
            "files_deleted",
            "renamed",
        )
    ]
    if isinstance(changes, (int, float)) and any(
        isinstance(v, (int, float)) and v > 0 for v in mutation_counts
    ):
        changes = max(
            changes, max(v for v in mutation_counts if isinstance(v, (int, float)))
        )
    if projects:
        known_changes = sum(row["changes"] for row in projects if row["changes_known"])
        if all(row["changes_known"] for row in projects) or known_changes > 0:
            changes = max(
                changes if isinstance(changes, (int, float)) else 0, known_changes
            )
    # A terminal v2 event is an explicit assertion by the producer, unlike legacy status.
    if payload.get("schema") == "appliance.activity.event/2":
        code = payload.get("event_code")
        if (
            status == "unknown"
            and "sync_status" not in payload
            and not projects
            and code
            in {
                "sync_completed",
                "sync_completed_no_changes",
                "sync_root_completed",
            }
        ):
            status = "complete"
        if code == "sync_incomplete":
            status = "incomplete"
        if code == "sync_failed":
            status = "failed"
        if code == "sync_completed_no_changes" and changes is None:
            changes = 0
    return {
        "sync_status": status,
        "enumeration_complete": enumeration if isinstance(enumeration, bool) else None,
        "changes_known": isinstance(changes, (int, float)),
        "changes": changes if isinstance(changes, (int, float)) else 0,
        "project_name": payload.get("project_name")
        or payload.get("root_name")
        or payload.get("root_folder_name"),
        "sync_run_id": payload.get("sync_run_id") or payload.get("run_id"),
        "analysis_run_id": payload.get("analysis_run_id"),
        "analysis_status": (payload.get("project_memory") or {}).get("status")
        if isinstance(payload.get("project_memory"), Mapping)
        else payload.get("pipeline_status"),
        **{
            key: payload.get(key)
            for key in (
                "source_snapshot_id",
                "source_snapshot_status",
                "source_snapshot_at",
                "source_inventory_count",
            )
        },
        "analysis_exclusions": payload.get("analysis_exclusions") or [],
        "project_results": projects,
    }


def provenance(payload: Mapping[str, Any]) -> tuple[str, str]:
    environment = str(payload.get("environment") or "").casefold()
    if environment == "test" or payload.get("transport") == "test_transport":
        return "test", "explicit environment/transport"
    # Legacy fixture provenance is established by temporary source paths, never names/messages.
    paths = [
        str(payload.get(k) or "")
        for k in (
            "project_root",
            "local_project_root",
            "source_root",
            "source_path",
            "input_dir",
            "project_path",
        )
    ]
    if any(re.search(r"/(?:tmp|var/tmp)/(?:pytest-[^/]+)/", path) for path in paths):
        return "test", "legacy temporary source path"
    if environment == "production":
        return "operational", "explicit environment=production"
    return "unknown", "source has no reliable operational/test metadata"


def record_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    origin, basis = provenance(payload)
    raw = {k: v for k, v in payload.items() if not k.startswith("_nexus_")}
    return dict(
        event_id=str(
            payload.get("event_id")
            or payload.get("_nexus_record_id")
            or "legacy:" + stable_id(raw)
        ),
        source_event_id=payload.get("event_id"),
        run_id=payload.get("run_id"),
        environment=payload.get("environment"),
        origin=origin,
        provenance_basis=basis,
        severity=str(payload.get("severity") or payload.get("level"))
        if payload.get("severity") or payload.get("level")
        else None,
        transport=payload.get("transport"),
        user_visible=payload.get("user_visible"),
        technical_only=payload.get("technical_only"),
        sync_status=sync_evidence(payload)["sync_status"],
        raw=raw,
    )
