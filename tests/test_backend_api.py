from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest
import httpx

from backend.app.config import ApplianceSettings
from backend.app.main import create_app
from backend.app.services.appliance import APPLIANCE_BUSY_MESSAGE, AnalysisJobState, SyncJobState


class _AsyncAppClient:
    def __init__(self, app) -> None:
        self._app = app

    def get(self, path: str) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get(path)

        return asyncio.run(_request())

    def post(
        self,
        path: str,
        *,
        json: object | None = None,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.post(path, json=json, headers=headers, data=data, files=files)

        return asyncio.run(_request())

    def delete(self, path: str) -> httpx.Response:
        async def _request() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.delete(path)

        return asyncio.run(_request())


def _client(settings: ApplianceSettings | None = None) -> _AsyncAppClient:
    return _AsyncAppClient(create_app(settings))


def _project_path(name: str) -> str:
    return quote(name, safe="")


def _is_numeric_app_version(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def _write_file(path: Path, content: bytes, *, modified_at: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if modified_at is not None:
        timestamp = modified_at.timestamp()
        os.utime(path, (timestamp, timestamp))


def _build_custom_appliance_root(tmp_path: Path) -> Path:
    appliance_root = tmp_path / "appliance"
    runtime_root = appliance_root / ".riveanbud_runtime" / "rive-anbud-appliance" / "Urban_Reuse_Norway"
    project_root = (
        runtime_root
        / "cache"
        / "onedrive_sync"
        / "test-sync-id"
        / "post@example.com"
        / "test-drive-id"
        / "Alpha Project"
    )
    comments_root = project_root / "Kommentarer"
    outputs_root = appliance_root / "outputs" / "Urban_Reuse_Norway" / "Alpha Project" / "2026-06-02" / "enterprise_review"

    for folder in [
        "Anbud",
        "Bakgrunnsdokumenter",
        "Tegninger",
        "Tidligere kommunikasjon",
        "Kommentarer",
    ]:
        (project_root / folder).mkdir(parents=True, exist_ok=True)

    _write_file(project_root / "Anbud" / "tilbud.txt", b"Alpha tender", modified_at=datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc))
    _write_file(project_root / "Bakgrunnsdokumenter" / "bakgrunn.pdf", b"pdf-bytes", modified_at=datetime(2026, 6, 2, 8, 5, tzinfo=timezone.utc))
    _write_file(comments_root / "Alpha Project - Kommentardokument.docx", b"older-docx", modified_at=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc))
    _write_file(
        comments_root / "Alpha Project - Kommentardokument - 1.0.docx",
        b"newer-docx",
        modified_at=datetime(2026, 6, 2, 8, 30, tzinfo=timezone.utc),
    )
    _write_file(outputs_root / "Alpha Project - Vedlegg.docx", b"newer-docx", modified_at=datetime(2026, 6, 2, 8, 30, tzinfo=timezone.utc))
    (outputs_root / "run_summary.json").write_text(
        json.dumps(
            {
                "project_name": "Alpha Project",
                "status": "completed_with_warnings",
                "started_at": "2026-06-02T08:00:00+00:00",
                "finished_at": "2026-06-02T08:45:00+00:00",
                "provider": "fake",
                "model": None,
                "documents_seen": 2,
                "chunks_created": 2,
                "report_items_count": 2,
                "output_docx_path": str(outputs_root / "Alpha Project - Vedlegg.docx"),
                "warnings": [],
                "errors": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    state_db = runtime_root / "state" / "onedrive_lightweight_state.sqlite3"
    state_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state_db) as connection:
        connection.execute(
            """
            CREATE TABLE projects (
                project_name TEXT,
                remote_root_path TEXT,
                local_project_root TEXT,
                analysis_status TEXT,
                last_sync_at TEXT,
                last_analyzed_at TEXT,
                updated_at TEXT,
                report_path TEXT,
                report_url TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO projects (
                project_name,
                remote_root_path,
                local_project_root,
                analysis_status,
                last_sync_at,
                last_analyzed_at,
                updated_at,
                report_path,
                report_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Alpha Project",
                "AnbudAppliance/Urban_Reuse_Norway/Alpha Project",
                str(project_root),
                "completed_with_warnings",
                "2026-06-02T08:50:00+00:00",
                None,
                "2026-06-02T08:55:00+00:00",
                "",
                "",
            ),
        )
        connection.commit()

    return appliance_root


def _write_sync_state(
    state_path: Path,
    *,
    project_name: str,
    project_root: Path,
    source_relative_paths: list[str],
) -> None:
    root_folder_name = "OneDrive_1_21.5.2026 (1)"
    root_local_path = project_root / root_folder_name
    items_by_id: dict[str, dict[str, object]] = {
        "root-folder": {
            "remote_item_id": "root-folder",
            "remote_parent_id": "project-root",
            "parent_path": "",
            "name": root_folder_name,
            "relative_path": root_folder_name,
            "local_path": str(root_local_path),
            "local_cache_path": str(root_local_path),
            "is_folder": True,
            "e_tag": "\"root-folder\"",
            "last_modified_date_time": "2026-05-21T11:17:02Z",
            "sha256": None,
            "size": 0,
        }
    }

    for index, relative_path in enumerate(source_relative_paths, start=1):
        local_path = root_local_path / relative_path
        items_by_id[f"file-{index}"] = {
            "remote_item_id": f"file-{index}",
            "remote_parent_id": "root-folder",
            "parent_path": root_folder_name,
            "name": Path(relative_path).name,
            "relative_path": f"{root_folder_name}/{relative_path}",
            "local_path": str(local_path),
            "local_cache_path": str(local_path),
            "is_folder": False,
            "e_tag": f"\"file-{index}\"",
            "last_modified_date_time": f"2026-05-21T11:17:{index:02d}Z",
            "sha256": None,
            "size": 10_000 + index,
        }

    state_payload = {
        "sync_key": f"{project_name.lower().replace(' ', '-')}-sync",
        "tenant_id": "tenant-id",
        "client_id": "client-id",
        "onedrive_user": "user@example.com",
        "remote_root_item_id": "project-root",
        "remote_root_name": project_name,
        "remote_root_path": f"AnbudAppliance/Urban_Reuse_Norway/{project_name}",
        "local_sync_base": str(project_root.parent),
        "state_storage_base": str(state_path.parent),
        "local_project_root": str(project_root),
        "delta_link": None,
        "items_by_id": items_by_id,
        "last_synced_at": "2026-06-04T16:01:09.714689+00:00",
        "total_downloaded_files": len(source_relative_paths),
        "total_changed_files": 0,
        "total_skipped_files": 0,
        "total_moved_files": 0,
        "total_deleted_files": 0,
        "total_renamed_files": 0,
        "total_failed_files": 0,
        "total_bytes_transferred": 0,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_state_only_appliance_root(
    tmp_path: Path,
    *,
    project_name: str,
    source_relative_paths: list[str],
    sample_source_relative_paths: list[str] | None = None,
) -> Path:
    appliance_root = tmp_path / "appliance"
    runtime_root = appliance_root / ".riveanbud_runtime" / "rive-anbud-appliance" / "Urban_Reuse_Norway"
    project_root = (
        runtime_root
        / "cache"
        / "onedrive_sync"
        / "test-sync-id"
        / "post@example.com"
        / "test-drive-id"
        / project_name
    )
    project_comment_root = project_root / "Kommentarer"
    outputs_root = appliance_root / "outputs" / "Urban_Reuse_Norway" / project_name / "2026-06-02" / "enterprise_review"
    sample_root = appliance_root / "sample_projects" / project_name

    sample_comment_root = sample_root / "Kommentarer"
    _write_file(
        project_comment_root / f"{project_name} - Kommentardokument.docx",
        b"output-comment-docx",
        modified_at=datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc),
    )
    _write_file(
        sample_comment_root / f"{project_name} - Kommentardokument.docx",
        b"sample-comment-docx",
        modified_at=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
    )

    for index, relative_path in enumerate(sample_source_relative_paths or [], start=1):
        _write_file(
            sample_root / relative_path,
            f"sample-source-{index}".encode("utf-8"),
            modified_at=datetime(2026, 6, 1, 7, index, tzinfo=timezone.utc),
        )

    outputs_root.mkdir(parents=True, exist_ok=True)
    (outputs_root / "run_summary.json").write_text(
        json.dumps(
            {
                "project_name": project_name,
                "status": "completed_with_warnings",
                "started_at": "2026-06-02T08:00:00+00:00",
                "finished_at": "2026-06-02T08:45:00+00:00",
                "provider": "fake",
                "model": None,
                "documents_seen": len(source_relative_paths),
                "chunks_created": len(source_relative_paths),
                "report_items_count": len(source_relative_paths),
                "output_docx_path": str(outputs_root / f"{project_name} - Kommentardokument.docx"),
                "warnings": [],
                "errors": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _write_sync_state(
        runtime_root / "state" / "onedrive_sync" / "test-sync-id" / "post@example.com" / "test-drive-id" / "sync_state.json",
        project_name=project_name,
        project_root=project_root,
        source_relative_paths=source_relative_paths,
    )

    state_db = runtime_root / "state" / "onedrive_lightweight_state.sqlite3"
    state_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state_db) as connection:
        connection.execute(
            """
            CREATE TABLE projects (
                project_name TEXT,
                remote_root_path TEXT,
                local_project_root TEXT,
                analysis_status TEXT,
                last_sync_at TEXT,
                last_analyzed_at TEXT,
                updated_at TEXT,
                report_path TEXT,
                report_url TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO projects (
                project_name,
                remote_root_path,
                local_project_root,
                analysis_status,
                last_sync_at,
                last_analyzed_at,
                updated_at,
                report_path,
                report_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_name,
                f"AnbudAppliance/Urban_Reuse_Norway/{project_name}",
                str(project_root),
                "completed_with_warnings",
                "2026-06-02T08:50:00+00:00",
                None,
                "2026-06-02T08:55:00+00:00",
                "",
                "",
            ),
        )
        connection.commit()

    return appliance_root


def _build_versioned_comment_appliance_root(
    tmp_path: Path,
    *,
    project_name: str,
    versions: list[str],
    history_versions: list[str] | None = None,
    include_output_report: bool = False,
    include_comment_base_report: bool = False,
    extra_source_files: dict[str, bytes] | None = None,
) -> Path:
    appliance_root = tmp_path / "appliance"
    runtime_root = appliance_root / ".riveanbud_runtime" / "rive-anbud-appliance" / "Urban_Reuse_Norway"
    project_root = (
        runtime_root
        / "cache"
        / "onedrive_sync"
        / "test-sync-id"
        / "post@example.com"
        / "test-drive-id"
        / project_name
    )
    comments_root = project_root / "Kommentarer"
    for folder in [
        "Anbud",
        "Bakgrunnsdokumenter",
        "Tegninger",
        "Tidligere kommunikasjon",
        "Kommentarer",
    ]:
        (project_root / folder).mkdir(parents=True, exist_ok=True)

    base_time = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    _write_file(project_root / "Anbud" / "tilbud.txt", b"tender", modified_at=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc))
    _write_file(project_root / "Bakgrunnsdokumenter" / "bakgrunn.pdf", b"background", modified_at=datetime(2026, 6, 1, 8, 5, tzinfo=timezone.utc))
    for index, (relative_path, content) in enumerate((extra_source_files or {}).items(), start=1):
        _write_file(
            project_root / relative_path,
            content,
            modified_at=base_time + timedelta(minutes=30 + index),
        )
    for index, version in enumerate(versions):
        _write_file(
            comments_root / f"{project_name} - Kommentardokument - {version}.docx",
            f"version-{version}".encode("utf-8"),
            modified_at=base_time + timedelta(minutes=len(versions) - index),
        )
        time.sleep(0.01)

    if include_comment_base_report:
        _write_file(
            comments_root / f"{project_name} - Kommentardokument.docx",
            b"base-docx",
            modified_at=base_time + timedelta(minutes=len(versions) + 20),
        )

    if include_output_report or history_versions:
        output_generated_at = base_time + timedelta(minutes=len(versions) + 10)
        outputs_root = appliance_root / "outputs" / "Urban_Reuse_Norway" / project_name / output_generated_at.strftime("%Y-%m-%d") / "enterprise_review"
        outputs_root.mkdir(parents=True, exist_ok=True)
        output_docx_path = outputs_root / f"{project_name} - Kommentardokument.docx"
        _write_file(output_docx_path, b"output-docx", modified_at=output_generated_at)
        (outputs_root / "run_summary.json").write_text(
            json.dumps(
                {
                    "project_name": project_name,
                    "status": "completed_with_warnings",
                    "started_at": output_generated_at.isoformat(),
                    "finished_at": (output_generated_at + timedelta(minutes=5)).isoformat(),
                    "provider": "fake",
                    "model": None,
                    "documents_seen": len(versions),
                    "chunks_created": len(versions),
                    "report_items_count": len(versions),
                    "output_docx_path": str(output_docx_path),
                    "warnings": [],
                    "errors": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    if history_versions:
        history_path = runtime_root / "onedrive_sync_history.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_entries: list[str] = []
        for index, version in enumerate(history_versions):
            generated_at = base_time + timedelta(days=index + 1)
            output_docx_path = appliance_root / "outputs" / "Urban_Reuse_Norway" / project_name / generated_at.strftime("%Y-%m-%d") / "enterprise_review" / f"{project_name} - Kommentardokument.docx"
            _write_file(output_docx_path, f"history-{version}".encode("utf-8"), modified_at=generated_at)
            history_entries.append(
                json.dumps(
                    {
                        "timestamp": generated_at.isoformat(),
                        "duration_seconds": 3.0,
                        "project_name": project_name,
                        "remote_root_path": f"AnbudAppliance/Urban_Reuse_Norway/{project_name}",
                        "local_output_mode": "history",
                        "status": "completed_with_warnings",
                        "report_snapshot": {
                            "project_name": project_name,
                            "report_type": "enterprise_review",
                            "generated_at": generated_at.isoformat(),
                        },
                        "uploaded_reports": [
                            {
                                "local_path": str(output_docx_path),
                                "local_output_path": str(output_docx_path.parent),
                                "remote_path": f"AnbudAppliance/Urban_Reuse_Norway/{project_name}/Kommentarer/{project_name} - Kommentardokument - {version}.docx",
                                "status": "uploaded",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        history_path.write_text("\n".join(history_entries), encoding="utf-8")

    state_db = runtime_root / "state" / "onedrive_lightweight_state.sqlite3"
    state_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state_db) as connection:
        connection.execute(
            """
            CREATE TABLE projects (
                project_name TEXT,
                remote_root_path TEXT,
                local_project_root TEXT,
                analysis_status TEXT,
                last_sync_at TEXT,
                last_analyzed_at TEXT,
                updated_at TEXT,
                report_path TEXT,
                report_url TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO projects (
                project_name,
                remote_root_path,
                local_project_root,
                analysis_status,
                last_sync_at,
                last_analyzed_at,
                updated_at,
                report_path,
                report_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_name,
                f"AnbudAppliance/Urban_Reuse_Norway/{project_name}",
                str(project_root),
                "completed_with_warnings",
                "2026-06-02T08:50:00+00:00",
                None,
                "2026-06-02T08:55:00+00:00",
                "",
                "",
            ),
        )
        connection.commit()

    return appliance_root


def _write_activity_journal(appliance_root: Path, entries: list[dict[str, object]]) -> Path:
    journal_path = appliance_root / "cache" / "urn_nexus_activity.jsonl"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries),
        encoding="utf-8",
    )
    return journal_path


def test_health_reports_appliance_availability_and_version() -> None:
    client = _client()

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["appliance_available"] is True
    assert _is_numeric_app_version(payload["version"])
    assert payload["discovered_projects"] >= 6
    assert payload["uptime_seconds"] >= 0
    assert payload["appliance_root"].endswith("/home/anbudklient/appliance")


def test_system_readiness_is_lightweight_and_does_not_start_sync(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    appliance_root.mkdir()
    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    client = _AsyncAppClient(app)

    response = client.get("/api/system/readiness")

    assert response.status_code == 200
    assert response.json() == {
        "ready": True,
        "backend": True,
        "appliance": True,
        "graph": True,
        "status": "ready",
        "code": None,
        "detail": None,
    }
    assert app.state.appliance_service._sync_state.status == "idle"
    assert app.state.appliance_service._analysis_state.status == "idle"


def test_system_readiness_reports_starting_when_appliance_root_is_not_available(tmp_path: Path) -> None:
    app = create_app(ApplianceSettings(appliance_root=tmp_path / "not-started"))
    response = _AsyncAppClient(app).get("/api/system/readiness")

    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert response.json()["status"] == "starting"
    assert response.json()["code"] == "appliance_starting"


def test_projects_endpoint_lists_discovered_projects() -> None:
    client = _client()

    response = client.get("/api/projects")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 6

    names = {project["project_name"] for project in payload["projects"]}
    assert names == {
        "Testprosjekt",
        "TE_Demo",
        "Bryn Skole",
        "Citypassasjen",
        "Sørkedalsveien 6",
        "Olav Tryggvasons gt 17",
    }

    testprosjekt = next(project for project in payload["projects"] if project["project_name"] == "Testprosjekt")
    assert testprosjekt["display_name"] == "Testprosjekt"
    assert testprosjekt["source_label"] == "OneDrive"
    assert testprosjekt["relative_project_path"] == "sample_projects/Testprosjekt"
    assert testprosjekt["is_sample_project"] is True
    assert testprosjekt["latest_comment_document"] == "Testprosjekt - Kommentardokument.docx"
    assert testprosjekt["latest_comment_modified_at"] is not None
    assert testprosjekt["status"] == "completed_with_warnings"
    assert testprosjekt["file_count"] == 7
    assert testprosjekt["report_count"] == 1
    assert testprosjekt["comment_document_count"] == 1

    bryn = next(project for project in payload["projects"] if project["project_name"] == "Bryn Skole")
    assert bryn["display_name"] == "Bryn Skole"
    assert bryn["source_label"] == "OneDrive"
    assert bryn["is_sample_project"] is False
    assert bryn["hidden_internal_path"]
    assert bryn["status"]
    assert bryn["file_count"] == 395
    assert bryn["report_count"] == 2
    assert bryn["comment_document_count"] == 2
    assert bryn["latest_comment_document"] == "Bryn Skole - Kommentardokument - 6.0.docx"
    assert bryn["latest_comment_document_open_url"] == "/api/projects/Bryn%20Skole/reports/latest/open"


def test_sample_project_detail_reports_and_files() -> None:
    client = _client()
    project = _project_path("Testprosjekt")

    detail_response = client.get(f"/api/projects/{project}")
    reports_response = client.get(f"/api/projects/{project}/reports")
    files_response = client.get(f"/api/projects/{project}/files")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["project_name"] == "Testprosjekt"
    assert detail["display_name"] == "Testprosjekt"
    assert detail["source_label"] == "OneDrive"
    assert detail["relative_project_path"] == "sample_projects/Testprosjekt"
    assert detail["is_sample_project"] is True
    assert detail["hidden_internal_path"]
    assert detail["latest_comment_document"] == "Testprosjekt - Kommentardokument.docx"
    assert detail["status"] == "completed_with_warnings"
    assert detail["file_count"] == 7
    assert detail["report_count"] == 1
    assert detail["comment_document_count"] == 1
    assert detail["analysis"]["status"] == "completed_with_warnings"
    assert detail["analysis"]["output_docx_path"].endswith("Testprosjekt - Kommentardokument.docx")

    assert reports_response.status_code == 200
    reports = reports_response.json()
    assert reports["count"] == 1
    assert reports["display_name"] == "Testprosjekt"
    assert reports["source_label"] == "OneDrive"
    assert reports["relative_project_path"] == "sample_projects/Testprosjekt"
    assert reports["is_sample_project"] is True
    assert reports["latest_comment_document"] == "Testprosjekt - Kommentardokument.docx"
    assert reports["comment_document_count"] == 1
    assert [item["report_name"] for item in reports["reports"]] == ["Testprosjekt - Kommentardokument.docx"]
    assert reports["reports"][0]["is_latest"] is True

    assert files_response.status_code == 200
    files = files_response.json()
    assert files["total_files"] == 7
    assert files["display_name"] == "Testprosjekt"
    assert files["source_label"] == "OneDrive"
    assert files["relative_project_path"] == "sample_projects/Testprosjekt"
    assert files["is_sample_project"] is True
    assert files["latest_comment_document"] == "Testprosjekt - Kommentardokument.docx"
    assert files["comment_document_count"] == 1
    assert [child["name"] for child in files["file_tree"]["children"]] == [
        "Anbud",
        "Bakgrunnsdokumenter",
        "Tegninger",
        "Tidligere kommunikasjon",
    ]


def test_state_projects_discover_comment_documents_from_history_without_outputs_root_mixing() -> None:
    client = _client()
    for project_name, expected_file_count, expected_report_count, expected_latest, expected_children in [
        ("Bryn Skole", 395, 2, "Bryn Skole - Kommentardokument - 6.0.docx", ["OneDrive_1_21.5.2026 (1)"]),
        (
            "Olav Tryggvasons gt 17",
            180,
            4,
            "Olav Tryggvasons gt 17 - Kommentardokument - 4.0.docx",
            [
                "01 HENT",
                "03 Consto",
            ],
        ),
    ]:
        project = _project_path(project_name)

        detail_response = client.get(f"/api/projects/{project}")
        reports_response = client.get(f"/api/projects/{project}/reports")
        files_response = client.get(f"/api/projects/{project}/files")
        debug_response = client.get(f"/api/projects/{project}/debug-paths")

        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["project_name"] == project_name
        assert detail["display_name"] == project_name
        assert detail["source_label"] == "OneDrive"
        assert not detail["relative_project_path"].startswith("AnbudAppliance/")
        assert detail["is_sample_project"] is False
        assert detail["latest_comment_document"] == expected_latest
        assert detail["latest_comment_document_open_url"] == f"/api/projects/{project}/reports/latest/open"
        assert detail["status"]
        assert detail["file_count"] == expected_file_count
        assert detail["report_count"] == expected_report_count
        assert detail["comment_document_count"] == expected_report_count
        assert detail["last_analyzed_at"] is not None

        assert reports_response.status_code == 200
        reports = reports_response.json()
        assert reports["count"] == expected_report_count
        assert reports["display_name"] == project_name
        assert reports["source_label"] == "OneDrive"
        assert not reports["relative_project_path"].startswith("AnbudAppliance/")
        assert reports["is_sample_project"] is False
        assert reports["latest_comment_document"] == expected_latest
        assert reports["latest_comment_document_open_url"] == f"/api/projects/{project}/reports/latest/open"
        assert reports["comment_document_count"] == expected_report_count
        if project_name == "Olav Tryggvasons gt 17":
            assert [item["report_name"] for item in reports["reports"]] == [
                "Olav Tryggvasons gt 17 - Kommentardokument - 4.0.docx",
                "Olav Tryggvasons gt 17 - Kommentardokument - 3.0.docx",
                "Olav Tryggvasons gt 17 - Kommentardokument - 2.0.docx",
                "Olav Tryggvasons gt 17 - Kommentardokument - 1.0.docx",
            ]
            assert [item["version"] for item in reports["reports"]] == ["4.0", "3.0", "2.0", "1.0"]
        elif project_name == "Bryn Skole":
            assert [item["report_name"] for item in reports["reports"]] == [
                "Bryn Skole - Kommentardokument - 6.0.docx",
                "Bryn Skole - Kommentardokument - 5.0.docx",
            ]
            assert [item["version"] for item in reports["reports"]] == ["6.0", "5.0"]
        else:
            assert [item["report_name"] for item in reports["reports"]] == [expected_latest] * expected_report_count
        assert reports["reports"][0]["is_latest"] is True
        assert reports["reports"][0]["report_id"] == "0"
        assert reports["reports"][0]["open_url"] == f"/api/projects/{project}/reports/0/open"
        assert reports["reports"][0]["download_url"] == f"/api/projects/{project}/reports/0/download"
        if project_name == "Olav Tryggvasons gt 17":
            assert reports["reports"][0]["version"] == "4.0"
            latest_open = client.get(f"/api/projects/{project}/reports/latest/open")
            assert latest_open.status_code == 200
            assert f"Forhåndsvisning av {expected_latest}" in latest_open.text
        elif project_name == "Bryn Skole":
            assert reports["reports"][0]["version"] == "6.0"

        assert files_response.status_code == 200
        files = files_response.json()
        assert files["total_files"] == expected_file_count
        assert files["display_name"] == project_name
        assert files["source_label"] == "OneDrive"
        assert files["is_sample_project"] is False
        assert files["comment_document_count"] == expected_report_count
        assert files["file_tree"]["file_count"] == expected_file_count
        assert [child["name"] for child in files["file_tree"]["children"]] == expected_children

        assert debug_response.status_code == 200
        debug = debug_response.json()
        assert debug["project_name"] == project_name
        assert isinstance(debug["project_path_exists"], bool)
        assert debug["resolved_project_path"]
        assert debug["total_files_on_disk"] >= expected_file_count
        assert debug["counted_source_files"] == expected_file_count
        assert debug["comment_documents_found"] == expected_report_count
        if project_name == "Bryn Skole":
            assert debug["ignored_file_count"] == 1
            assert debug["ignored_reasons"] == ["Kommentarer folders are excluded from source file counts."]
        else:
            assert debug["ignored_file_count"] == 0
            assert debug["ignored_reasons"] == []
        assert len(debug["candidates"]) == 1
        assert debug["candidates"][0]["selected"] is True
        if not debug["project_path_exists"]:
            assert debug["candidates"][0]["source_inventory_mode"] == "sync_state"
        assert debug["candidates"][0]["candidate_path"] == debug["resolved_project_path"]
        assert debug["candidates"][0]["source_file_count"] == expected_file_count
        assert debug["candidates"][0]["source_inventory_mode"] in {"sync_state", "filesystem"}


def test_sample_comment_only_candidate_does_not_override_source_cache(tmp_path: Path) -> None:
    appliance_root = _build_state_only_appliance_root(
        tmp_path,
        project_name="Gamma Project",
        source_relative_paths=[
            "Anbud/tilbud.txt",
            "Bakgrunnsdokumenter/bakgrunn.pdf",
        ],
    )
    client = _client(ApplianceSettings(appliance_root=appliance_root))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["discovered_projects"] == 1

    projects = client.get("/api/projects")
    assert projects.status_code == 200
    payload = projects.json()
    assert payload["count"] == 1
    project = payload["projects"][0]
    assert project["project_name"] == "Gamma Project"
    assert project["is_sample_project"] is False
    assert project["file_count"] == 2
    assert project["report_count"] == 1
    assert project["comment_document_count"] == 1
    assert project["latest_comment_document"] == "Gamma Project - Kommentardokument.docx"
    assert project["latest_comment_document_open_url"] == "/api/projects/Gamma%20Project/reports/latest/open"

    detail = client.get("/api/projects/Gamma%20Project")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["file_count"] == 2
    assert detail_payload["report_count"] == 1
    assert detail_payload["comment_document_count"] == 1
    assert detail_payload["latest_comment_document"] == "Gamma Project - Kommentardokument.docx"

    reports = client.get("/api/projects/Gamma%20Project/reports")
    assert reports.status_code == 200
    reports_payload = reports.json()
    assert reports_payload["count"] == 1
    assert reports_payload["latest_comment_document"] == "Gamma Project - Kommentardokument.docx"
    assert reports_payload["is_sample_project"] is False

    files = client.get("/api/projects/Gamma%20Project/files")
    assert files.status_code == 200
    files_payload = files.json()
    assert files_payload["total_files"] == 2
    assert [child["name"] for child in files_payload["file_tree"]["children"]] == [
        "OneDrive_1_21.5.2026 (1)",
    ]
    assert [child["name"] for child in files_payload["file_tree"]["children"][0]["children"]] == [
        "Anbud",
        "Bakgrunnsdokumenter",
    ]

    debug = client.get("/api/projects/Gamma%20Project/debug-paths")
    assert debug.status_code == 200
    debug_payload = debug.json()
    assert debug_payload["project_name"] == "Gamma Project"
    assert debug_payload["counted_source_files"] == 2
    assert debug_payload["comment_documents_found"] == 1
    assert len(debug_payload["candidates"]) == 2
    selected = next(candidate for candidate in debug_payload["candidates"] if candidate["selected"])
    sample_candidate = next(candidate for candidate in debug_payload["candidates"] if not candidate["selected"])
    assert selected["candidate_path"] == debug_payload["resolved_project_path"]
    assert selected["source_file_count"] == 2
    assert selected["report_count"] == 1
    assert selected["source_inventory_mode"] == "sync_state"
    assert sample_candidate["is_sample_project"] is True
    assert sample_candidate["source_file_count"] == 0
    assert sample_candidate["report_count"] == 1


def test_real_candidate_beats_sample_even_if_sample_has_more_source_files(tmp_path: Path) -> None:
    appliance_root = _build_state_only_appliance_root(
        tmp_path,
        project_name="Delta Project",
        source_relative_paths=[
            "Anbud/tilbud.txt",
            "Bakgrunnsdokumenter/bakgrunn.pdf",
        ],
        sample_source_relative_paths=[
            "Anbud/sample-tilbud.txt",
            "Bakgrunnsdokumenter/sample-bakgrunn.pdf",
            "Tegninger/sample-tegning.dwg",
        ],
    )
    client = _client(ApplianceSettings(appliance_root=appliance_root))

    detail = client.get("/api/projects/Delta%20Project")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["is_sample_project"] is False
    assert detail_payload["file_count"] == 2

    debug = client.get("/api/projects/Delta%20Project/debug-paths")
    assert debug.status_code == 200
    debug_payload = debug.json()
    assert len(debug_payload["candidates"]) == 2
    selected = next(candidate for candidate in debug_payload["candidates"] if candidate["selected"])
    sample_candidate = next(candidate for candidate in debug_payload["candidates"] if not candidate["selected"])
    assert selected["is_sample_project"] is False
    assert selected["source_file_count"] == 2
    assert sample_candidate["is_sample_project"] is True
    assert sample_candidate["source_file_count"] == 3


def test_custom_root_discovery_is_not_hardcoded_to_existing_project_names(tmp_path: Path) -> None:
    appliance_root = _build_custom_appliance_root(tmp_path)
    client = _client(ApplianceSettings(appliance_root=appliance_root))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert _is_numeric_app_version(health.json()["version"])
    assert health.json()["discovered_projects"] == 1

    projects = client.get("/api/projects")
    assert projects.status_code == 200
    payload = projects.json()
    assert payload["count"] == 1
    assert payload["projects"][0]["project_name"] == "Alpha Project"
    assert payload["projects"][0]["display_name"] == "Alpha Project"
    assert payload["projects"][0]["relative_project_path"] == "Urban_Reuse_Norway/Alpha Project"
    assert payload["projects"][0]["source_label"] == "OneDrive"
    assert payload["projects"][0]["is_sample_project"] is False
    assert payload["projects"][0]["file_count"] == 2
    assert payload["projects"][0]["report_count"] == 2
    assert payload["projects"][0]["comment_document_count"] == 2
    assert payload["projects"][0]["latest_comment_document"] == "Alpha Project - Kommentardokument - 1.0.docx"
    assert payload["projects"][0]["latest_comment_document_open_url"] == "/api/projects/Alpha%20Project/reports/latest/open"
    assert payload["projects"][0]["status"] == "completed_with_warnings"

    detail = client.get("/api/projects/Alpha%20Project")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["analysis"]["status"] == "completed_with_warnings"
    assert detail_payload["analysis"]["output_docx_path"].endswith("Alpha Project - Vedlegg.docx")
    assert detail_payload["last_analyzed_at"] is not None
    assert detail_payload["report_count"] == 2
    assert detail_payload["file_count"] == 2
    assert detail_payload["comment_document_count"] == 2
    assert detail_payload["latest_comment_document"] == "Alpha Project - Kommentardokument - 1.0.docx"
    assert detail_payload["latest_comment_created_at"] is not None

    reports = client.get("/api/projects/Alpha%20Project/reports")
    assert reports.status_code == 200
    report_payload = reports.json()
    assert report_payload["count"] == 2
    assert report_payload["display_name"] == "Alpha Project"
    assert report_payload["relative_project_path"] == "Urban_Reuse_Norway/Alpha Project"
    assert report_payload["source_label"] == "OneDrive"
    assert report_payload["is_sample_project"] is False
    assert report_payload["latest_comment_document"] == "Alpha Project - Kommentardokument - 1.0.docx"
    assert report_payload["comment_document_count"] == 2
    assert [item["report_name"] for item in report_payload["reports"]] == [
        "Alpha Project - Kommentardokument - 1.0.docx",
        "Alpha Project - Kommentardokument.docx",
    ]
    assert report_payload["reports"][0]["is_latest"] is True
    assert report_payload["reports"][0]["report_id"] == "0"
    assert report_payload["reports"][0]["open_url"] == "/api/projects/Alpha%20Project/reports/0/open"
    assert report_payload["reports"][0]["download_url"] == "/api/projects/Alpha%20Project/reports/0/download"
    assert report_payload["reports"][1]["report_id"] == "1"
    assert report_payload["reports"][1]["open_url"] == "/api/projects/Alpha%20Project/reports/1/open"
    assert report_payload["reports"][1]["download_url"] == "/api/projects/Alpha%20Project/reports/1/download"
    assert report_payload["reports"][0]["version"] == "1.0"
    assert report_payload["reports"][0]["created_at"] is not None
    assert report_payload["reports"][1]["version"] is None

    latest_open = client.get("/api/projects/Alpha%20Project/reports/latest/open")
    assert latest_open.status_code == 200
    assert latest_open.headers["content-type"].startswith("text/html")
    assert "view.officeapps.live.com/op/embed.aspx?src=" in latest_open.text
    assert "Last ned" in latest_open.text
    assert "Alpha Project - Kommentardokument - 1.0.docx" in latest_open.text

    invalid_open = client.get("/api/projects/Alpha%20Project/reports/99/open")
    assert invalid_open.status_code == 404
    assert invalid_open.json()["code"] == "report_not_found"

    files = client.get("/api/projects/Alpha%20Project/files")
    assert files.status_code == 200
    file_payload = files.json()
    assert file_payload["total_files"] == 2
    assert file_payload["display_name"] == "Alpha Project"
    assert file_payload["relative_project_path"] == "Urban_Reuse_Norway/Alpha Project"
    assert file_payload["source_label"] == "OneDrive"
    assert file_payload["is_sample_project"] is False
    assert file_payload["comment_document_count"] == 2
    assert [child["name"] for child in file_payload["file_tree"]["children"]] == [
        "Anbud",
        "Bakgrunnsdokumenter",
    ]
    anbud_folder = file_payload["file_tree"]["children"][0]
    tilbud_file = anbud_folder["children"][0]
    assert anbud_folder["relative_path"] == "Anbud"
    assert tilbud_file["name"] == "tilbud.txt"
    assert tilbud_file["relative_path"] == "Anbud/tilbud.txt"
    assert tilbud_file["display_name"] == "tilbud.txt"
    assert tilbud_file["open_url"] == "/api/projects/Alpha%20Project/files/open?path=Anbud%2Ftilbud.txt"
    assert tilbud_file["download_url"] == "/api/projects/Alpha%20Project/files/download?path=Anbud%2Ftilbud.txt"

    file_open = client.get("/api/projects/Alpha%20Project/files/open?path=Anbud%2Ftilbud.txt")
    assert file_open.status_code == 200
    assert file_open.content == b"Alpha tender"
    assert "tilbud.txt" in file_open.headers["content-disposition"]

    file_download = client.get("/api/projects/Alpha%20Project/files/download?path=Bakgrunnsdokumenter%2Fbakgrunn.pdf")
    assert file_download.status_code == 200
    assert file_download.content == b"pdf-bytes"
    assert "attachment" in file_download.headers["content-disposition"]

    traversal = client.get("/api/projects/Alpha%20Project/files/open?path=..%2F..%2F.env")
    assert traversal.status_code == 404
    assert traversal.json()["code"] == "file_not_found"

    debug = client.get("/api/projects/Alpha%20Project/debug-paths")
    assert debug.status_code == 200
    debug_payload = debug.json()
    assert debug_payload["project_name"] == "Alpha Project"
    assert debug_payload["project_path_exists"] is True
    assert debug_payload["counted_source_files"] == 2
    assert debug_payload["total_files_on_disk"] == 4
    assert debug_payload["comment_documents_found"] == 2
    assert debug_payload["ignored_file_count"] == 2
    assert "Kommentarer folders are excluded from source file counts." in debug_payload["ignored_reasons"]


@pytest.mark.parametrize(
    ("relative_path", "expected_mode"),
    [
        ("Dokumenter/rapport.docx", "office"),
        ("Dokumenter/ark.xlsx", "office"),
        ("Dokumenter/ark.xls", "office"),
        ("Dokumenter/slides.pptx", "office"),
        ("Dokumenter/slides.ppt", "office"),
        ("Dokumenter/oversikt.pdf", "pdf"),
    ],
)
def test_open_file_uses_preview_for_office_documents_and_keeps_download(tmp_path: Path, relative_path: str, expected_mode: str) -> None:
    appliance_root = _build_versioned_comment_appliance_root(
        tmp_path,
        project_name="Preview Prosjekt",
        versions=["1.0"],
        extra_source_files={
            "Dokumenter/rapport.docx": b"docx-bytes",
            "Dokumenter/ark.xlsx": b"xlsx-bytes",
            "Dokumenter/ark.xls": b"xls-bytes",
            "Dokumenter/slides.pptx": b"pptx-bytes",
            "Dokumenter/slides.ppt": b"ppt-bytes",
            "Dokumenter/oversikt.pdf": b"pdf-bytes",
        },
    )
    client = _client(ApplianceSettings(appliance_root=appliance_root))
    project = _project_path("Preview Prosjekt")
    encoded_path = quote(relative_path, safe="")

    open_response = client.get(f"/api/projects/{project}/files/open?path={encoded_path}")
    download_response = client.get(f"/api/projects/{project}/files/download?path={encoded_path}")

    assert download_response.status_code == 200
    assert "attachment" in download_response.headers["content-disposition"]

    assert open_response.status_code == 200
    if expected_mode == "office":
        assert open_response.headers["content-type"].startswith("text/html")
        assert "view.officeapps.live.com/op/embed.aspx?src=" in open_response.text
        assert "Last ned" in open_response.text
        assert "Åpne nedlasting" in open_response.text
    else:
        assert open_response.headers["content-type"].startswith("application/pdf")
        assert "inline" in open_response.headers["content-disposition"]


def test_versioned_comment_documents_are_all_detected_and_sorted_by_created_at(tmp_path: Path) -> None:
    appliance_root = _build_versioned_comment_appliance_root(
        tmp_path,
        project_name="Bryn Skole",
        versions=["1.0", "2.0", "3.0", "4.0", "5.0", "6.0"],
    )
    client = _client(ApplianceSettings(appliance_root=appliance_root))
    project = _project_path("Bryn Skole")

    detail_response = client.get(f"/api/projects/{project}")
    reports_response = client.get(f"/api/projects/{project}/reports")
    projects_response = client.get("/api/projects")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["project_name"] == "Bryn Skole"
    assert detail["report_count"] == 6
    assert detail["comment_document_count"] == 6
    assert detail["latest_comment_document"] == "Bryn Skole - Kommentardokument - 6.0.docx"
    assert detail["latest_comment_document_open_url"] == "/api/projects/Bryn%20Skole/reports/latest/open"

    assert reports_response.status_code == 200
    reports = reports_response.json()
    assert reports["count"] == 6
    assert [item["report_name"] for item in reports["reports"]] == [
        "Bryn Skole - Kommentardokument - 6.0.docx",
        "Bryn Skole - Kommentardokument - 5.0.docx",
        "Bryn Skole - Kommentardokument - 4.0.docx",
        "Bryn Skole - Kommentardokument - 3.0.docx",
        "Bryn Skole - Kommentardokument - 2.0.docx",
        "Bryn Skole - Kommentardokument - 1.0.docx",
    ]
    assert [item["version"] for item in reports["reports"]] == ["6.0", "5.0", "4.0", "3.0", "2.0", "1.0"]
    assert reports["reports"][0]["is_latest"] is True
    assert reports["reports"][0]["created_at"] is not None
    assert reports["reports"][0]["open_url"] == "/api/projects/Bryn%20Skole/reports/0/open"
    assert reports["reports"][0]["download_url"] == "/api/projects/Bryn%20Skole/reports/0/download"

    assert projects_response.status_code == 200
    projects = projects_response.json()
    bryn = next(project for project in projects["projects"] if project["project_name"] == "Bryn Skole")
    assert bryn["report_count"] == 6
    assert bryn["comment_document_count"] == 6


def test_versioned_comment_documents_ignore_history_and_outputs_duplicates(tmp_path: Path) -> None:
    appliance_root = _build_versioned_comment_appliance_root(
        tmp_path,
        project_name="TestProsjekt#1",
        versions=["1.0", "2.0", "3.0", "4.0", "5.0", "6.0"],
        history_versions=["3.0", "4.0", "5.0", "6.0"],
        include_output_report=True,
        include_comment_base_report=True,
    )
    client = _client(ApplianceSettings(appliance_root=appliance_root))
    project = _project_path("TestProsjekt#1")

    detail_response = client.get(f"/api/projects/{project}")
    reports_response = client.get(f"/api/projects/{project}/reports")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["report_count"] == 7
    assert detail["comment_document_count"] == 7
    assert detail["latest_comment_document"] == "TestProsjekt#1 - Kommentardokument - 6.0.docx"
    assert detail["latest_comment_document_open_url"] == "/api/projects/TestProsjekt%231/reports/latest/open"

    assert reports_response.status_code == 200
    reports = reports_response.json()
    assert reports["count"] == 7
    assert [item["report_name"] for item in reports["reports"]] == [
        "TestProsjekt#1 - Kommentardokument - 6.0.docx",
        "TestProsjekt#1 - Kommentardokument - 5.0.docx",
        "TestProsjekt#1 - Kommentardokument - 4.0.docx",
        "TestProsjekt#1 - Kommentardokument - 3.0.docx",
        "TestProsjekt#1 - Kommentardokument - 2.0.docx",
        "TestProsjekt#1 - Kommentardokument - 1.0.docx",
        "TestProsjekt#1 - Kommentardokument.docx",
    ]
    assert [item["version"] for item in reports["reports"]] == ["6.0", "5.0", "4.0", "3.0", "2.0", "1.0", None]
    assert all(item["size_bytes"] > 0 for item in reports["reports"])
    assert reports["reports"][0]["is_latest"] is True
    assert reports["reports"][0]["open_url"] == "/api/projects/TestProsjekt%231/reports/0/open"
    assert reports["reports"][0]["download_url"] == "/api/projects/TestProsjekt%231/reports/0/download"

    latest_open = client.get("/api/projects/TestProsjekt%231/reports/latest/open")
    assert latest_open.status_code == 200
    assert latest_open.headers["content-type"].startswith("text/html")
    assert "view.officeapps.live.com/op/embed.aspx?src=" in latest_open.text
    assert "Last ned" in latest_open.text
    assert "TestProsjekt#1 - Kommentardokument - 6.0.docx" in latest_open.text


def test_project_write_operations_use_project_relative_paths(tmp_path: Path) -> None:
    appliance_root = _build_custom_appliance_root(tmp_path)
    folder_calls: list[dict[str, object]] = []
    upload_calls: list[dict[str, object]] = []

    class FakeOneDriveWriter:
        def create_project(self, project_name: str, *, folders: list[str], parent_remote_path: str) -> list[str]:
            return folders

        def create_project_folder(
            self,
            project_name: str,
            folder_name: str,
            *,
            parent_remote_path: str,
            target_folder: str | None = None,
        ) -> dict[str, object]:
            folder_calls.append(
                {
                    "project_name": project_name,
                    "folder_name": folder_name,
                    "parent_remote_path": parent_remote_path,
                    "target_folder": target_folder,
                }
            )
            return {"id": "folder-id", "name": folder_name, "webUrl": "https://example.com/folder"}

        def upload_file(
            self,
            project_name: str,
            filename: str,
            content: bytes,
            *,
            parent_remote_path: str,
            target_folder: str | None = None,
        ) -> dict[str, object]:
            upload_calls.append(
                {
                    "project_name": project_name,
                    "filename": filename,
                    "content": content,
                    "parent_remote_path": parent_remote_path,
                    "target_folder": target_folder,
                }
            )
            return {"id": "file-id", "name": filename, "webUrl": "https://example.com/file"}

        def delete_project(self, project_name: str, *, parent_remote_path: str) -> str:
            return f"{parent_remote_path}/{project_name}"

    client = _AsyncAppClient(create_app(ApplianceSettings(appliance_root=appliance_root), onedrive_writer=FakeOneDriveWriter()))

    folder_response = client.post(
        "/api/projects/Alpha%20Project/files/folders",
        json={"folder_name": "Ny mappe", "target_folder": "Anbud"},
    )
    assert folder_response.status_code == 200
    folder_payload = folder_response.json()
    assert folder_payload["project_name"] == "Alpha Project"
    assert folder_payload["relative_path"] == "Anbud/Ny mappe"
    assert folder_payload["mode"] == "onedrive"
    assert folder_payload["warning"] is None

    upload_response = client.post(
        "/api/projects/Alpha%20Project/files/upload",
        data={"target_folder": "Anbud/Ny mappe"},
        files={"file": ("notat.txt", b"uploaded-note", "text/plain")},
    )
    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["filename"] == "notat.txt"
    assert upload_payload["relative_path"] == "Anbud/Ny mappe/notat.txt"
    assert upload_payload["size_bytes"] == len(b"uploaded-note")
    assert upload_payload["mode"] == "onedrive"

    uploaded_open = client.get("/api/projects/Alpha%20Project/files/open?path=Anbud%2FNy%20mappe%2Fnotat.txt")
    assert uploaded_open.status_code == 404
    assert uploaded_open.json()["code"] == "file_not_found"

    assert folder_calls == [
        {
            "project_name": "Alpha Project",
            "folder_name": "Ny mappe",
            "parent_remote_path": "AnbudAppliance/Urban_Reuse_Norway",
            "target_folder": "Anbud",
        }
    ]
    assert upload_calls == [
        {
            "project_name": "Alpha Project",
            "filename": "notat.txt",
            "content": b"uploaded-note",
            "parent_remote_path": "AnbudAppliance/Urban_Reuse_Norway",
            "target_folder": "Anbud/Ny mappe",
        }
    ]

    invalid_upload = client.post(
        "/api/projects/Alpha%20Project/files/upload",
        data={"target_folder": "Anbud"},
        files={"file": ("../evil.txt", b"nope", "text/plain")},
    )
    assert invalid_upload.status_code == 400
    assert invalid_upload.json()["code"] == "write_error"


def test_create_project_fails_when_graph_write_is_not_configured(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    appliance_root.mkdir()
    client = _client(ApplianceSettings(appliance_root=appliance_root))

    create_response = client.post("/api/projects", json={"project_name": "Portal Prosjekt"})

    assert create_response.status_code == 503
    assert create_response.json()["code"] == "graph_write_unavailable"
    assert not (appliance_root / "cache" / "urn_nexus_local_projects" / "Urban_Reuse_Norway" / "Portal Prosjekt").exists()


def test_create_project_uses_onedrive_writer_and_sync_before_visible(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    appliance_root.mkdir()
    writer_calls: list[tuple[str, list[str], str]] = []

    class FakeOneDriveWriter:
        def create_project(self, project_name: str, *, folders: list[str], parent_remote_path: str) -> list[str]:
            writer_calls.append((project_name, folders, parent_remote_path))
            return folders

    app = create_app(ApplianceSettings(appliance_root=appliance_root), onedrive_writer=FakeOneDriveWriter())
    service = app.state.appliance_service

    def fake_sync(project_name: str) -> None:
        runtime_root = appliance_root / ".riveanbud_runtime" / "rive-anbud-appliance" / "Urban_Reuse_Norway"
        project_root = (
            runtime_root
            / "cache"
            / "onedrive_sync"
            / "test-sync-id"
            / "post@example.com"
            / "test-drive-id"
            / project_name
        )
        for folder in [
            "Anbud",
            "Bakgrunnsdokumenter",
            "Tegninger",
            "Tidligere kommunikasjon",
            "Kommentarer",
        ]:
            (project_root / folder).mkdir(parents=True, exist_ok=True)
        state_db = runtime_root / "state" / "onedrive_lightweight_state.sqlite3"
        state_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(state_db) as connection:
            connection.execute(
                """
                CREATE TABLE projects (
                    project_name TEXT,
                    remote_root_path TEXT,
                    local_project_root TEXT,
                    analysis_status TEXT,
                    last_sync_at TEXT,
                    last_analyzed_at TEXT,
                    updated_at TEXT,
                    report_path TEXT,
                    report_url TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO projects (
                    project_name,
                    remote_root_path,
                    local_project_root,
                    analysis_status,
                    last_sync_at,
                    last_analyzed_at,
                    updated_at,
                    report_path,
                    report_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_name,
                    f"AnbudAppliance/Urban_Reuse_Norway/{project_name}",
                    str(project_root),
                    "pending",
                    "2026-06-02T08:50:00+00:00",
                    None,
                    "2026-06-02T08:55:00+00:00",
                    "",
                    "",
                ),
            )
            connection.commit()

    monkeypatch.setattr(service, "_require_sync_only_available", lambda: None)
    monkeypatch.setattr(service, "_run_sync_for_project", fake_sync)
    client = _AsyncAppClient(app)

    create_response = client.post("/api/projects", json={"project_name": "Portal Prosjekt"})

    assert create_response.status_code == 200
    create_payload = create_response.json()
    assert create_payload["project_name"] == "Portal Prosjekt"
    assert create_payload["relative_project_path"] == "Urban_Reuse_Norway/Portal Prosjekt"
    assert create_payload["mode"] == "onedrive"
    assert create_payload["folders_created"] == [
        "Anbud",
        "Bakgrunnsdokumenter",
        "Tegninger",
        "Tidligere kommunikasjon",
        "Kommentarer",
    ]
    assert create_payload["warning"] is None
    assert writer_calls == [
        (
            "Portal Prosjekt",
            [
                "Anbud",
                "Bakgrunnsdokumenter",
                "Tegninger",
                "Tidligere kommunikasjon",
                "Kommentarer",
            ],
            "AnbudAppliance/Urban_Reuse_Norway",
        )
    ]
    assert not (appliance_root / "cache" / "urn_nexus_local_projects" / "Urban_Reuse_Norway" / "Portal Prosjekt").exists()

    projects_response = client.get("/api/projects")
    assert projects_response.status_code == 200
    projects_payload = projects_response.json()
    portal_project = next(project for project in projects_payload["projects"] if project["project_name"] == "Portal Prosjekt")
    assert portal_project["source_label"] == "OneDrive"
    assert portal_project["is_local_cache_only"] is False
    assert portal_project["relative_project_path"] == "Urban_Reuse_Norway/Portal Prosjekt"
    assert portal_project["status"] == "pending"


def test_local_only_project_is_hidden_from_standard_project_list(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    local_project = appliance_root / "cache" / "urn_nexus_local_projects" / "Urban_Reuse_Norway" / "Kun Lokal"
    (local_project / "Anbud").mkdir(parents=True)
    client = _client(ApplianceSettings(appliance_root=appliance_root))

    projects_response = client.get("/api/projects")
    assert projects_response.status_code == 200
    projects_payload = projects_response.json()
    assert projects_payload["projects"] == []

    debug_response = client.get("/api/projects?include_local_cache=true")
    assert debug_response.status_code == 200
    debug_payload = debug_response.json()
    assert debug_payload["count"] == 1
    assert debug_payload["projects"][0]["project_name"] == "Kun Lokal"
    assert debug_payload["projects"][0]["source_label"] == "Kun lokal cache"
    assert debug_payload["projects"][0]["is_local_cache_only"] is True


def test_delete_project_local_cache_hides_without_deleting_onedrive(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    project_name = "Rydd Meg"
    local_project = appliance_root / "cache" / "urn_nexus_local_projects" / "Urban_Reuse_Norway" / project_name
    local_upload = appliance_root / "cache" / "urn_nexus_uploads" / "Urban_Reuse_Norway" / project_name
    output_project = appliance_root / "outputs" / "Urban_Reuse_Norway" / project_name
    remote_onedrive_project = tmp_path / "OneDrive" / "AnbudAppliance" / "Urban_Reuse_Norway" / project_name
    for path in [local_project / "Anbud", local_upload / "Anbud", output_project / "Kommentarer", remote_onedrive_project]:
        path.mkdir(parents=True, exist_ok=True)

    runtime_root = appliance_root / ".riveanbud_runtime" / "rive-anbud-appliance" / "Urban_Reuse_Norway"
    synced_project = runtime_root / "cache" / "onedrive_sync" / "test-sync-id" / "post@example.com" / "test-drive-id" / project_name
    (synced_project / "Anbud").mkdir(parents=True)
    state_db = runtime_root / "state" / "onedrive_lightweight_state.sqlite3"
    state_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state_db) as connection:
        connection.execute(
            """
            CREATE TABLE projects (
                project_name TEXT,
                remote_root_path TEXT,
                local_project_root TEXT,
                analysis_status TEXT,
                last_sync_at TEXT,
                last_analyzed_at TEXT,
                updated_at TEXT,
                report_path TEXT,
                report_url TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO projects (
                project_name,
                remote_root_path,
                local_project_root,
                analysis_status,
                last_sync_at,
                last_analyzed_at,
                updated_at,
                report_path,
                report_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_name,
                f"AnbudAppliance/Urban_Reuse_Norway/{project_name}",
                str(synced_project),
                "pending",
                "2026-06-02T08:50:00+00:00",
                None,
                "2026-06-02T08:55:00+00:00",
                "",
                "",
            ),
        )
        connection.commit()

    client = _client(ApplianceSettings(appliance_root=appliance_root))

    response = client.delete(f"/api/projects/{_project_path(project_name)}/local-cache")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_name"] == project_name
    assert payload["hidden"] is True
    assert payload["removed_state_rows"] == 1
    assert not local_project.exists()
    assert not local_upload.exists()
    assert not output_project.exists()
    assert not synced_project.exists()
    assert remote_onedrive_project.exists()

    with sqlite3.connect(state_db) as connection:
        remaining = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    assert remaining == 0

    projects_response = client.get("/api/projects?include_local_cache=true")
    assert projects_response.status_code == 200
    assert projects_response.json()["projects"] == []


def test_delete_project_removes_project_from_nexus_and_calls_onedrive_delete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appliance_root = _build_custom_appliance_root(tmp_path)
    delete_calls: list[tuple[str, str]] = []

    class FakeOneDriveWriter:
        def create_project(self, project_name: str, *, folders: list[str], parent_remote_path: str) -> list[str]:
            return folders

        def create_project_folder(
            self,
            project_name: str,
            folder_name: str,
            *,
            parent_remote_path: str,
            target_folder: str | None = None,
        ) -> dict[str, object]:
            return {"id": "folder-id", "name": folder_name}

        def upload_file(
            self,
            project_name: str,
            filename: str,
            content: bytes,
            *,
            parent_remote_path: str,
            target_folder: str | None = None,
        ) -> dict[str, object]:
            return {"id": "file-id", "name": filename}

        def delete_project(self, project_name: str, *, parent_remote_path: str) -> str:
            delete_calls.append((project_name, parent_remote_path))
            return f"{parent_remote_path}/{project_name}"

    app = create_app(ApplianceSettings(appliance_root=appliance_root), onedrive_writer=FakeOneDriveWriter())
    service = app.state.appliance_service
    monkeypatch.setattr(service, "_require_sync_only_available", lambda: None)
    monkeypatch.setattr(service, "_run_sync_for_project", lambda project_name: None)
    client = _AsyncAppClient(app)

    response = client.delete("/api/projects/Alpha%20Project")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_name"] == "Alpha Project"
    assert payload["deleted_remote_path"] == "AnbudAppliance/Urban_Reuse_Norway/Alpha Project"
    assert payload["deleted"] is True
    assert payload["existed"] is True
    assert payload["synced"] is True
    assert payload["message"] == "Prosjektet ble slettet fra OneDrive."
    assert delete_calls == [("Alpha Project", "AnbudAppliance/Urban_Reuse_Norway")]

    projects_response = client.get("/api/projects")
    assert projects_response.status_code == 200
    assert projects_response.json()["projects"] == []


def test_delete_project_missing_remote_returns_idempotent_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appliance_root = _build_custom_appliance_root(tmp_path)
    delete_calls: list[tuple[str, str]] = []

    class FakeOneDriveWriter:
        def create_project(self, project_name: str, *, folders: list[str], parent_remote_path: str) -> list[str]:
            return folders

        def create_project_folder(
            self,
            project_name: str,
            folder_name: str,
            *,
            parent_remote_path: str,
            target_folder: str | None = None,
        ) -> dict[str, object]:
            return {"id": "folder-id", "name": folder_name}

        def upload_file(
            self,
            project_name: str,
            filename: str,
            content: bytes,
            *,
            parent_remote_path: str,
            target_folder: str | None = None,
        ) -> dict[str, object]:
            return {"id": "file-id", "name": filename}

        def delete_project(self, project_name: str, *, parent_remote_path: str) -> tuple[str, bool]:
            delete_calls.append((project_name, parent_remote_path))
            return f"{parent_remote_path}/{project_name}", False

    app = create_app(ApplianceSettings(appliance_root=appliance_root), onedrive_writer=FakeOneDriveWriter())
    service = app.state.appliance_service
    monkeypatch.setattr(service, "_require_sync_only_available", lambda: None)
    monkeypatch.setattr(service, "_run_sync_for_project", lambda project_name: None)
    client = _AsyncAppClient(app)

    response = client.delete("/api/projects/Alpha%20Project")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_name"] == "Alpha Project"
    assert payload["deleted_remote_path"] == "AnbudAppliance/Urban_Reuse_Norway/Alpha Project"
    assert payload["deleted"] is True
    assert payload["existed"] is False
    assert payload["synced"] is True
    assert payload["message"] == "Prosjektet finnes ikke lenger i OneDrive."
    assert delete_calls == [("Alpha Project", "AnbudAppliance/Urban_Reuse_Norway")]

    projects_response = client.get("/api/projects")
    assert projects_response.status_code == 200
    assert projects_response.json()["projects"] == []


def test_delete_project_graph_write_failure_returns_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appliance_root = _build_custom_appliance_root(tmp_path)

    class FakeOneDriveWriter:
        def create_project(self, project_name: str, *, folders: list[str], parent_remote_path: str) -> list[str]:
            return folders

        def create_project_folder(
            self,
            project_name: str,
            folder_name: str,
            *,
            parent_remote_path: str,
            target_folder: str | None = None,
        ) -> dict[str, object]:
            return {"id": "folder-id", "name": folder_name}

        def upload_file(
            self,
            project_name: str,
            filename: str,
            content: bytes,
            *,
            parent_remote_path: str,
            target_folder: str | None = None,
        ) -> dict[str, object]:
            return {"id": "file-id", "name": filename}

        def delete_project(self, project_name: str, *, parent_remote_path: str) -> str:
            raise RuntimeError("Microsoft Graph permission denied")

    app = create_app(ApplianceSettings(appliance_root=appliance_root), onedrive_writer=FakeOneDriveWriter())
    service = app.state.appliance_service
    monkeypatch.setattr(service, "_require_sync_only_available", lambda: None)
    monkeypatch.setattr(service, "_run_sync_for_project", lambda project_name: None)
    client = _AsyncAppClient(app)

    response = client.delete("/api/projects/Alpha%20Project")

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "write_error"
    assert "Microsoft Graph permission denied" in payload["detail"]


def test_sync_endpoint_starts_sync_only_nonblocking_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    script_path = appliance_root / "scripts" / "run_onedrive_appliance.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("# supports --sync-only\n", encoding="utf-8")
    started_commands: list[list[str]] = []

    class DummyProcess:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def communicate(self) -> tuple[str, str]:
            self.returncode = 0
            return (
                json.dumps(
                    {
                        "per_root_results": [
                            {
                                "status": "completed",
                                "sync_status": "complete",
                                "enumeration_complete": True,
                                "root_name": "Bryn Skole",
                                "project_name": "Bryn Skole",
                                "run_id": "appliance-run-1",
                                "changed": 2,
                                "downloaded": 2,
                                "deleted": 1,
                                "sync_strategy": "delta",
                                "sync_metrics": {
                                    "remote_items_examined": 12,
                                    "files_downloaded": 2,
                                    "files_deleted": 1,
                                    "graph_requests": 3,
                                    "bytes_downloaded": 2048,
                                    "duration_seconds": 4.5,
                                },
                                "timings": {
                                    "authentication": 0.4,
                                    "graph_delta": 1.2,
                                    "downloads": 2.1,
                                    "finalization": 0.8,
                                },
                            }
                        ],
                    }
                ),
                "",
            )

    def fake_popen(command: list[str], **_: object) -> DummyProcess:
        started_commands.append(command)
        return DummyProcess()

    monkeypatch.setattr("backend.app.services.appliance.subprocess.Popen", fake_popen)
    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    client = _AsyncAppClient(app)

    response = client.post("/api/sync/run")
    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is True
    assert payload["status"] == "started"
    assert payload["sync_only"] is True
    assert payload["analysis_started"] is False
    assert payload["reports_generated"] == 0
    assert payload["projects_synced"] == 0
    assert payload["files_changed"] == 0
    assert payload["reports_found"] == 0
    assert payload["job_type"] == "sync"
    assert payload["run_mode"] == "sync_only"
    assert payload["event_code"] == "sync_started"
    assert started_commands
    assert "run_onedrive_appliance.py" in started_commands[0][1]
    assert "--once" in started_commands[0]
    assert "--all-roots" in started_commands[0]
    assert "--sync-only" in started_commands[0]
    assert "--force-analyze" not in started_commands[0]
    assert "--provider" not in started_commands[0]
    assert "openai" not in started_commands[0]
    assert "--email-mode" not in started_commands[0]
    assert "immediate" not in started_commands[0]
    assert "daily_digest" not in started_commands[0]
    assert "--local-output-mode" not in started_commands[0]
    trigger_index = started_commands[0].index("--trigger-source")
    assert started_commands[0][trigger_index + 1] == "nexus_sync"
    started_by_index = started_commands[0].index("--started-by")
    assert started_commands[0][started_by_index + 1] == "nexus-web"

    status_payload = None
    for _ in range(50):
        status_response = client.get("/api/sync/status")
        assert status_response.status_code == 200
        status_payload = status_response.json()
        if status_payload["status"] == "completed":
            break
        time.sleep(0.01)
    assert status_payload["job_id"] == payload["job_id"]
    assert status_payload["status"] in {"running", "completed"}
    assert status_payload["job_type"] == "sync"
    assert status_payload["run_mode"] == "sync_only"
    assert status_payload["event_code"] == "sync_completed"
    assert status_payload["current_project"] == "Bryn Skole"
    assert status_payload["progress"] == 100.0
    assert status_payload["appliance_run_id"] == "appliance-run-1"
    assert status_payload["projects_synced"] == 1
    assert status_payload["sync_strategy"] == "delta"
    assert status_payload["sync_strategy_reason"] is None
    assert status_payload["remote_items_examined"] == 12
    assert status_payload["files_downloaded"] == 2
    assert status_payload["files_deleted"] == 1
    assert status_payload["performance"]["graph_requests"] == 3
    assert status_payload["performance"]["total_duration_seconds"] == 4.5
    assert status_payload["performance"]["downloaded_bytes"] == 2048


def test_sync_start_idempotency_key_does_not_spawn_a_second_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service

    class DummyProcess:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

    service._sync_state = SyncJobState(
        running=True,
        process=DummyProcess(),
        job_id="sync-job",
        requested_at=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc),
        last_started_at=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc),
        status="running",
        current_phase="Henter endringer",
        run_mode="sync_only",
        event_code="sync_started",
    )
    service._last_sync_idempotency_key = "same-request"
    monkeypatch.setattr("backend.app.services.appliance.subprocess.Popen", lambda *_args, **_kwargs: pytest.fail("duplicate sync spawned"))

    client = _AsyncAppClient(app)
    response = client.post("/api/sync/start", json={"idempotency_key": "same-request"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "already_running"
    assert payload["job_id"] == "sync-job"
    assert payload["run_mode"] == "sync_only"


def test_sync_endpoint_returns_busy_when_analysis_is_active(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service

    class DummyProcess:
        def poll(self) -> int | None:
            return None

    service._analysis_state = AnalysisJobState(
        running=True,
        job_id="analysis-job",
        process=DummyProcess(),
        last_started_at=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc),
        last_completed_at=None,
        last_error=None,
        projects_synced=0,
        files_changed=0,
        reports_found=0,
        reports_generated=0,
        email_mode="daily_digest",
        project_name="Bryn Skole",
        status="running",
    )
    client = _AsyncAppClient(app)

    response = client.post("/api/sync/run")

    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "appliance_busy"
    assert payload["detail"] == APPLIANCE_BUSY_MESSAGE


def test_sync_endpoint_returns_busy_when_history_lock_is_live(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    runtime_root = appliance_root / ".riveanbud_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_root / "onedrive_sync_history.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": 424242,
                "created_at": datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc).isoformat(),
                "lock_path": str(lock_path),
            }
        ),
        encoding="utf-8",
    )

    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    monkeypatch.setattr(service, "_is_pid_alive", lambda pid: True)
    monkeypatch.setattr(service, "_process_cmdline", lambda pid: "/home/anbudklient/appliance/.venv/bin/python /home/anbudklient/appliance/scripts/run_onedrive_appliance.py --once --all-roots --sync-only --company-root AnbudAppliance/Urban_Reuse_Norway")
    client = _AsyncAppClient(app)

    response = client.post("/api/sync/run")

    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "appliance_busy"
    assert payload["detail"] == APPLIANCE_BUSY_MESSAGE


def test_sync_status_clears_stale_lock_error_when_process_is_not_running(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    service._sync_state = SyncJobState(
        running=False,
        job_id="sync-job",
        last_started_at=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc),
        last_completed_at=datetime(2026, 6, 12, 8, 5, tzinfo=timezone.utc),
        last_error="Awaiting history lock while waiting for onedrive_sync_history.lock to clear.",
        projects_synced=3,
        files_changed=2,
        reports_found=1,
        status="failed",
    )
    client = _AsyncAppClient(app)

    response = client.get("/api/sync/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is False
    assert payload["status"] == "idle"
    assert payload["last_error"] is None
    assert payload["job_id"] == "sync-job"
    assert payload["process_alive"] is False
    assert payload["lock_exists"] is False
    assert payload["lock_stale"] is False
    assert payload["activity"] == "idle"


def test_sync_status_preserves_and_ignores_stale_history_lock_file(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    runtime_root = appliance_root / ".riveanbud_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_root / "onedrive_sync_history.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": 999999,
                "created_at": datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc).isoformat(),
                "lock_path": str(lock_path),
            }
        ),
        encoding="utf-8",
    )

    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    service._sync_state = SyncJobState(
        running=False,
        job_id="sync-job",
        last_started_at=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc),
        last_completed_at=datetime(2026, 6, 12, 8, 5, tzinfo=timezone.utc),
        last_error="Awaiting history lock while waiting for onedrive_sync_history.lock to clear.",
        projects_synced=3,
        files_changed=2,
        reports_found=1,
        status="failed",
    )
    client = _AsyncAppClient(app)

    response = client.get("/api/sync/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is False
    assert payload["status"] == "idle"
    assert payload["last_error"] is None
    assert payload["lock_stale"] is True
    assert payload["lock_exists"] is False
    assert payload["activity"] == "idle"
    assert lock_path.exists()


def test_sync_endpoint_fails_safely_when_sync_only_is_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    script_path = appliance_root / "scripts" / "run_onedrive_appliance.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("# no safe sync flag here\n", encoding="utf-8")
    started_commands: list[list[str]] = []

    def fake_popen(command: list[str], **_: object) -> object:
        started_commands.append(command)
        raise AssertionError("Nexus must not start full appliance pipeline when sync-only is unavailable.")

    monkeypatch.setattr("backend.app.services.appliance.subprocess.Popen", fake_popen)
    client = _client(ApplianceSettings(appliance_root=appliance_root))

    response = client.post("/api/sync/run")

    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "sync_only_unavailable"
    assert payload["detail"] == (
        "Nexus kan ikke synkronisere trygt før appliance støtter sync-only. Full analysepipeline er blokkert fra Nexus."
    )
    assert started_commands == []


def test_analysis_endpoint_delegates_selected_project_to_memory_without_delivery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = create_app(ApplianceSettings(appliance_root=tmp_path))
    calls = []
    def start(name, action):
        calls.append((name, action.mode))
        return dict(accepted=True, job_id=None, launch_pending=True)
    monkeypatch.setattr(app.state.appliance_service.memory, "start", start)
    response = _AsyncAppClient(app).post("/api/analysis/run", json={"project_name": "Bryn Skole", "email_mode": "immediate"}, headers={"X-Nexus-Action": "project-memory"})
    assert response.status_code == 202
    assert response.json() == dict(accepted=True, job_id=None, launch_pending=True)
    assert calls == [("Bryn Skole", "incremental")]


def test_analysis_status_clears_stale_lock_error_when_process_is_not_running(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    service._analysis_state = AnalysisJobState(
        running=False,
        job_id="analysis-job",
        last_started_at=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc),
        last_completed_at=datetime(2026, 6, 12, 8, 5, tzinfo=timezone.utc),
        last_error="Waiting for history lock while onedrive_lightweight_state.sqlite3 clears.",
        projects_synced=4,
        files_changed=6,
        reports_found=3,
        reports_generated=2,
        email_mode="daily_digest",
        project_name="Bryn Skole",
        status="failed",
    )
    client = _AsyncAppClient(app)

    response = client.get("/api/analysis/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is False
    assert payload["status"] == "idle"
    assert payload["last_error"] is None
    assert payload["job_id"] == "analysis-job"
    assert payload["process_alive"] is False
    assert payload["lock_exists"] is False
    assert payload["lock_stale"] is False
    assert payload["activity"] == "idle"


def test_analysis_status_reports_startup_pending_and_grace_window(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    started_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    service._analysis_state = AnalysisJobState(
        running=True,
        job_id="analysis-job",
        start_requested_at=started_at,
        last_started_at=started_at,
        process_spawned=True,
        auth_status="unknown",
        projects_synced=0,
        files_changed=0,
        reports_found=0,
        reports_generated=0,
        email_mode="daily_digest",
        project_name="Bryn Skole",
        status="startup_pending",
    )
    client = _AsyncAppClient(app)

    response = client.get("/api/analysis/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "startup_pending"
    assert payload["running"] is False
    assert payload["process_alive"] is False
    assert payload["process_spawned"] is True
    assert payload["startup_grace_active"] is True
    assert payload["auth_status"] == "unknown"
    assert datetime.fromisoformat(payload["start_requested_at"].replace("Z", "+00:00")) == started_at
    assert payload["analysis_started"] is True
    assert payload["activity"] == "analysis"


@pytest.mark.parametrize(
    ("last_error", "expected_status", "expected_auth_status"),
    [
        ("Microsoft Graph returned invalid_grant while requesting an access token.", "auth_failed", "auth_failed"),
        ("OneDrive sync failed while preparing the analysis workspace.", "sync_failed", "sync_failed"),
    ],
)
def test_analysis_status_classifies_terminal_failures(tmp_path: Path, last_error: str, expected_status: str, expected_auth_status: str) -> None:
    appliance_root = tmp_path / "appliance"
    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    service._analysis_state = AnalysisJobState(
        running=False,
        job_id="analysis-job",
        start_requested_at=started_at,
        last_started_at=started_at,
        last_completed_at=started_at + timedelta(minutes=1),
        last_error=last_error,
        process_spawned=False,
        auth_status="unknown",
        projects_synced=0,
        files_changed=0,
        reports_found=0,
        reports_generated=0,
        email_mode="daily_digest",
        project_name="Bryn Skole",
        status="failed",
    )
    client = _AsyncAppClient(app)

    response = client.get("/api/analysis/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == expected_status
    assert payload["auth_status"] == expected_auth_status
    assert payload["startup_grace_active"] is False
    assert payload["last_error"] == last_error


def test_analysis_endpoint_requires_explicit_action_and_selected_project(tmp_path: Path) -> None:
    client = _client(ApplianceSettings(appliance_root=tmp_path))
    assert client.post("/api/analysis/run", json={}).status_code == 403
    response = client.post("/api/analysis/run", json={}, headers={"X-Nexus-Action": "project-memory"})
    assert response.status_code == 400
    assert "prosjekt" in response.json()["detail"]


def test_activity_endpoints_return_empty_state(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    appliance_root.mkdir(parents=True, exist_ok=True)
    client = _client(ApplianceSettings(appliance_root=appliance_root))

    status_response = client.get("/api/activity/status")
    events_response = client.get("/api/activity/events")
    logs_response = client.get("/api/activity/logs")

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["state"] == "Klar"
    assert status["activity"] == "Ingen aktiv jobb"
    assert status["status"] == "Ingen aktiv jobb"
    assert status["project_name"] is None
    assert status["appliance_available"] is True

    assert events_response.status_code == 200
    events = events_response.json()
    assert events["events"] == []
    assert events["errors"] == []

    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert logs["entries"] == []


def test_activity_endpoints_report_running_state_and_ordered_events(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    appliance_root.mkdir(parents=True, exist_ok=True)
    _write_activity_journal(
        appliance_root,
        [
            {
                "timestamp": "2026-06-30T08:10:00+02:00",
                "level": "INFO",
                "message": "Started analysis",
                "project_name": "Bryn Skole",
                "component": "Analysis",
                "kind": "event",
            },
            {
                "timestamp": "2026-06-30T08:11:00+02:00",
                "level": "SUCCESS",
                "message": "Generated report",
                "project_name": "Bryn Skole",
                "component": "Reports",
                "kind": "event",
            },
            {
                "timestamp": "2026-06-30T08:12:00+02:00",
                "level": "SUCCESS",
                "message": "Uploaded report",
                "project_name": "Bryn Skole",
                "component": "OneDrive",
                "kind": "log",
            },
            {
                "timestamp": "2026-06-30T08:13:00+02:00",
                "level": "INFO",
                "message": "Waiting for history lock",
                "project_name": "Bryn Skole",
                "component": "OneDrive",
                "kind": "log",
            },
        ],
    )

    class DummyProcess:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    service._sync_state = SyncJobState(
        running=True,
        job_id="sync-job",
        process=DummyProcess(),
        last_started_at=datetime(2026, 6, 30, 8, 9, tzinfo=timezone.utc),
        project_name="Bryn Skole",
        status="running",
    )
    client = _AsyncAppClient(app)

    status_response = client.get("/api/activity/status")
    events_response = client.get("/api/activity/events")
    logs_response = client.get("/api/activity/logs")

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["state"] == "Synkroniserer"
    assert status["activity"] == "OneDrive Sync"
    assert status["status"] == "Synkroniserer dokumenter"
    assert status["project_name"] == "Bryn Skole"
    assert status["job_type"] == "sync"
    assert status["run_mode"] == "sync_only"

    assert events_response.status_code == 200
    events = events_response.json()
    assert [entry["message"] for entry in events["events"]] == [
        "Uploaded report",
        "Generated report",
        "Started analysis",
    ]
    assert [entry["category"] for entry in events["events"]] == ["OneDrive", "Report", "Analysis"]
    assert [entry["source"] for entry in events["events"]] == ["OneDrive", "Report", "Analysis"]
    assert events["errors"] == []

    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert [entry["message"] for entry in logs["entries"]] == [
        "Uploaded report",
        "Generated report",
        "Started analysis",
    ]
    assert all(entry["message"] != "Waiting for history lock" for entry in logs["entries"])


def test_activity_does_not_report_stale_analysis_while_sync_is_active(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    appliance_root.mkdir(parents=True, exist_ok=True)

    class DummyProcess:
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    service._sync_state = SyncJobState(
        running=True,
        process=DummyProcess(),
        job_id="sync-job",
        status="running",
        current_phase="Henter endringer",
        current_project="Bryn Skole",
        run_mode="sync_only",
        event_code="sync_started",
    )
    service._analysis_state = AnalysisJobState(
        running=True,
        process=DummyProcess(),
        job_id="old-analysis-job",
        status="running",
        current_phase="Analyserer dokumenter",
        last_error="Stale analysis error",
    )

    response = _AsyncAppClient(app).get("/api/activity/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "sync"
    assert payload["run_mode"] == "sync_only"
    assert payload["event_code"] == "sync_started"
    assert payload["state"] == "Henter endringer"
    assert payload["activity"] == "OneDrive Sync"
    assert payload["status"] == "Henter endringer"
    assert payload["project_name"] == "Bryn Skole"


def test_activity_endpoints_report_failed_state_and_meaningful_errors(tmp_path: Path) -> None:
    appliance_root = tmp_path / "appliance"
    appliance_root.mkdir(parents=True, exist_ok=True)
    _write_activity_journal(
        appliance_root,
        [
            {
                "timestamp": "2026-06-30T09:00:00+02:00",
                "level": "INFO",
                "message": "Starting analysis",
                "project_name": "Bryn Skole",
                "component": "Analysis",
                "kind": "log",
            },
            {
                "timestamp": "2026-06-30T09:01:00+02:00",
                "level": "ERROR",
                "message": "Request timed out",
                "project_name": "Bryn Skole",
                "component": "OpenAI",
                "kind": "error",
            },
        ],
    )

    app = create_app(ApplianceSettings(appliance_root=appliance_root))
    service = app.state.appliance_service
    service._analysis_state = AnalysisJobState(
        running=False,
        job_id="analysis-job",
        last_started_at=datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc),
        last_completed_at=datetime(2026, 6, 30, 9, 2, tzinfo=timezone.utc),
        last_error="Request timed out",
        process_spawned=False,
        auth_status="unknown",
        projects_synced=0,
        files_changed=0,
        reports_found=0,
        reports_generated=0,
        email_mode="daily_digest",
        project_name="Bryn Skole",
        status="failed",
    )
    client = _AsyncAppClient(app)

    status_response = client.get("/api/activity/status")
    events_response = client.get("/api/activity/events")
    logs_response = client.get("/api/activity/logs")

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["state"] == "Feilet"
    assert status["activity"] == "Ingen aktiv jobb"
    assert status["status"] == "Request timed out"
    assert status["project_name"] is None  # completed jobs belong to history

    assert events_response.status_code == 200
    events = events_response.json()
    assert [entry["message"] for entry in events["errors"]] == ["Request timed out"]
    assert events["errors"][0]["component"] == "OpenAI"

    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert logs["entries"][0]["level"] == "ERROR"
    assert logs["entries"][0]["message"] == "Request timed out"
