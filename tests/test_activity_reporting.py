"""Reporting regressions using isolated histories, never operational writes."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.config import ApplianceSettings
from backend.app.main import create_app
from backend.app.services.appliance import ApplianceService, SyncJobState
from backend.app.services.activity_reporting import sync_evidence


def service_at(tmp_path, rows=()):
    history = tmp_path / "history.jsonl"
    history.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return ApplianceService(
        ApplianceSettings(appliance_root=tmp_path, activity_history_paths=[history])
    )


@pytest.mark.parametrize(
    "result,exitcode,expected",
    [
        (
            {
                "sync_status": "incomplete",
                "enumeration_complete": False,
                "downloaded": 0,
            },
            0,
            "incomplete",
        ),
        ({"sync_status": "failed", "downloaded": 0}, 0, "failed"),
        ({"status": "skipped_no_changes", "downloaded": 0}, 0, "unknown"),
        ({}, 1, "failed"),
        (
            {"sync_status": "complete", "enumeration_complete": True, "changed": 0},
            0,
            "complete",
        ),
        (
            {"sync_status": "complete", "enumeration_complete": False, "changed": 0},
            0,
            "incomplete",
        ),
        (
            {
                "sync_status": "complete",
                "per_root_results": [{"sync_status": "incomplete", "changed": 0}],
            },
            0,
            "incomplete",
        ),
        (
            {
                "sync_status": "complete",
                "per_root_results": [
                    {"sync_status": "complete", "changed": 0},
                    {"status": "completed"},
                ],
            },
            0,
            "unknown",
        ),
        (
            {
                "sync_status": "complete",
                "changed": 0,
                "status": "failed",
                "pipeline_status": "failed",
            },
            1,
            "complete",
        ),
    ],
)
def test_terminal_sync_requires_authoritative_result(
    tmp_path, result, exitcode, expected
):
    service = service_at(tmp_path)

    class Process:
        returncode = exitcode

        def communicate(self):
            return json.dumps(result), ""

    service._sync_state = SyncJobState(
        job_id="nexus-job", running=True, status="running"
    )
    service._monitor_sync_process("nexus-job", Process())
    state = service.sync_status()
    assert state.sync_status == expected
    assert (state.status == "completed") == (expected == "complete")
    journal = service._read_activity_journal_payloads()[-1]
    assert (journal["event_code"] == "sync_completed_no_changes") == (
        expected == "complete" and result.get("changed") == 0
    )
    if expected != "complete":
        assert state.progress is None
        assert journal["level"] != "SUCCESS"


def test_zero_downloads_does_not_prove_no_changes():
    assert not sync_evidence({"sync_status": "complete", "downloaded": 0})[
        "changes_known"
    ]
    assert (
        sync_evidence(
            {"sync_status": "complete", "downloaded": 0, "deleted": 1, "renamed": 0}
        )["changes"]
        == 1
    )


def test_completed_history_never_fabricates_processing(tmp_path):
    service = service_at(
        tmp_path,
        [
            {
                "status": "completed",
                "reports_generated": 1,
                "uploaded_reports": [{}],
                "email_mode": "immediate",
                "files_changed": 3,
            }
        ],
    )
    logs = service.activity_logs().entries
    assert len(logs) == 1
    assert logs[0].sync_status == "unknown"
    assert not any(
        term in logs[0].message
        for term in ["OCR", "Generated report", "Upload completed", "Email sent"]
    )


def test_polling_keeps_undated_and_old_occurrences_stable(tmp_path):
    service = service_at(
        tmp_path,
        [
            {"message": "old", "timestamp": "2020-01-02T03:04:05Z"},
            {"message": "undated"},
            {"message": "undated"},
        ],
    )
    first = service.activity_logs().model_dump()["entries"]
    service._invalidate_activity_cache()
    second = service.activity_logs().model_dump()["entries"]
    assert first == second
    assert len(first) == 3
    assert first[0]["timestamp"].year == 2020
    assert all(row["timestamp"] is None for row in first[1:])
    assert first[1]["event_id"] != first[2]["event_id"]
    with (tmp_path / "history.jsonl").open("a") as handle:
        handle.write(json.dumps({"message": "new"}) + "\n")
    service._invalidate_activity_cache()
    after = service.activity_logs().entries
    assert {r.event_id for r in after if r.message == "undated"} == {
        r["event_id"] for r in first[1:]
    }


def test_structured_identity_severity_and_provenance_are_preserved(tmp_path):
    base = dict(
        schema="appliance.activity.event/2",
        timestamp="2026-07-01T01:00:00Z",
        event_code="pagination_warning",
        source="onedrive_sync",
        severity="warning",
        message="Repeated Graph page",
        run_id="run-a",
        project_name="Testprosjekt",
    )
    rows = [
        dict(base, event_id="a", environment="production"),
        dict(base, event_id="a", environment="production"),
        dict(base, event_id="b", environment="production"),
        dict(base, event_id="test", environment="test", transport="test_transport"),
        dict(base, event_id="unknown"),
        dict(
            base,
            event_id="legacy-test",
            local_project_root="/tmp/pytest-of-user/pytest-1/Testprosjekt",
        ),
    ]
    service = service_at(tmp_path, rows)
    logs = {r.event_id: r for r in service.activity_logs().entries}
    assert len(logs) == 5
    assert logs["a"].origin == "operational"
    assert logs["b"].message == logs["a"].message
    assert logs["test"].origin == logs["legacy-test"].origin == "test"
    assert logs["unknown"].origin == "unknown"
    assert logs["a"].source == "onedrive_sync"
    assert logs["a"].severity == "warning" and logs["a"].level == "WARNING"
    assert logs["a"].run_id == logs["a"].job_id == "run-a"
    assert logs["a"].raw["timestamp"] == base["timestamp"]


def test_configured_feed_does_not_scan_other_histories(tmp_path):
    service = service_at(
        tmp_path, [{"message": "operational warning", "environment": "production"}]
    )
    fixture = tmp_path / "outputs" / "fixtures" / "history.jsonl"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(json.dumps({"message": "fixture failure"}))
    assert [r.message for r in service.activity_logs().entries] == [
        "operational warning"
    ]


def test_test_volume_cannot_evict_operational_warnings(tmp_path):
    rows = [
        {
            "event_id": "operational",
            "message": "Graph warning",
            "severity": "warning",
            "environment": "production",
            "timestamp": "2020-01-01T00:00:00Z",
        }
    ]
    rows += [
        dict(
            event_id=str(i),
            message="test failure",
            environment="test",
            timestamp="2026-01-01T00:00:00Z",
        )
        for i in range(60)
    ]
    service = service_at(tmp_path, rows)
    assert any(r.event_id == "operational" for r in service.activity_events().events)


def test_coverage_exclusions_survive_later_unchanged_history(tmp_path):
    service = service_at(
        tmp_path,
        [
            dict(
                project_name="Bryn Skole",
                sync_status="complete",
                enumeration_complete=True,
                timestamp="2026-07-01T00:00:00Z",
                analysis_exclusions=[
                    dict(
                        relative_path="Tegninger/modell.smc",
                        reason="unsupported_format",
                        download_selected=False,
                    )
                ],
            ),
            dict(
                project_name="Bryn Skole",
                sync_status="complete",
                changed=0,
                timestamp="2026-07-02T00:00:00Z",
            ),
            dict(
                project_name="Other",
                sync_status="failed",
                timestamp="2026-07-03T00:00:00Z",
            ),
        ],
    )
    coverage = service.project_sync_coverage("Bryn Skole")
    assert coverage["sync_status"] == "complete"
    assert (
        coverage["historical_analysis_exclusions"][0]["relative_path"]
        == "Tegninger/modell.smc"
    )
    assert coverage["historical_analysis_exclusions"][0]["download_selected"] is False


def test_archived_project_does_not_become_current(tmp_path):
    service = service_at(
        tmp_path,
        [
            dict(
                project_name="Old project",
                status="completed",
                phase="ocr",
                timestamp=datetime.now(timezone.utc).isoformat(),
                job_id="old",
            )
        ],
    )
    status = service.activity_status()
    assert status.state == "Klar"
    assert status.job_id is None and status.project_name is None


def test_active_memory_job_uses_durable_identity_across_refresh(tmp_path, monkeypatch):
    service = service_at(tmp_path)
    monkeypatch.setattr(
        service.memory,
        "activity_snapshot",
        lambda: (
            [
                dict(
                    job_id="persisted-job",
                    project_name="Correct project",
                    stage="ocr",
                    updated_at="2026-01-01T00:00:00Z",
                )
            ],
            [],
        ),
    )
    first = service.activity_status()
    service._invalidate_activity_cache()
    second = service.activity_status()
    assert first.job_id == second.job_id == "persisted-job"
    assert first.project_name == second.project_name == "Correct project"
    assert first.current_phase == "ocr"


def test_api_retains_null_timestamp_and_raw_evidence(tmp_path):
    history = tmp_path / "activity.jsonl"
    history.write_text(
        json.dumps(
            dict(
                event_id="source-id",
                message="actual OCR record",
                operation="ocr",
                environment="production",
                job_id="real-job",
            )
        )
        + "\n"
    )
    app = create_app(
        ApplianceSettings(appliance_root=tmp_path, activity_history_paths=[history])
    )
    with TestClient(app) as client:
        row = client.get("/api/activity/logs").json()["entries"][0]
        assert row["event_id"] == "source-id" and row["timestamp"] is None
        assert row["raw"]["operation"] == "ocr" and row["job_id"] == "real-job"


def test_explicit_nested_processing_event_preserves_own_time_and_identity(tmp_path):
    service = service_at(
        tmp_path,
        [
            dict(
                status="completed",
                timestamp="2026-01-01T00:00:00Z",
                event_records=[
                    dict(
                        schema="appliance.activity.event/2",
                        event_id="real-ocr",
                        message="OCR finished",
                        timestamp="2020-01-01T01:00:00Z",
                        job_id="actual-job",
                        severity="info",
                        environment="production",
                    ),
                    dict(event_id="undated-ocr", message="Actual OCR record"),
                ],
            )
        ],
    )
    logs = {r.event_id: r for r in service.activity_logs().entries}
    assert (
        logs["real-ocr"].timestamp.year == 2020
        and logs["real-ocr"].job_id == "actual-job"
    )
    assert logs["undated-ocr"].timestamp is None


def test_naive_clock_does_not_acquire_an_invented_timezone(tmp_path):
    service = service_at(
        tmp_path, [dict(message="old local clock", timestamp="2020-01-01T12:00:00")]
    )
    assert service.activity_logs().entries[0].timestamp is None
    assert service.activity_logs().entries[0].raw["timestamp"] == "2020-01-01T12:00:00"


def test_deleted_files_prevent_no_changes_label():
    evidence = sync_evidence(
        dict(sync_status="complete", changed=0, downloaded=0, deleted=2)
    )
    assert evidence["changes_known"] and evidence["changes"] > 0


def test_legacy_completion_claim_keeps_original_evidence_without_claiming_success(
    tmp_path,
):
    service = service_at(
        tmp_path,
        [
            dict(
                event_id="old",
                event_code="sync_completed_no_changes",
                message="Synchronization completed. No file changes detected.",
                environment="production",
            )
        ],
    )
    row = service.activity_logs().entries[0]
    assert row.sync_status == "unknown"
    assert "completeness unknown" in row.message
    assert row.raw["message"] == "Synchronization completed. No file changes detected."
    assert row.event_id == row.source_event_id == "old"


def test_terminal_event_does_not_override_unknown_project_evidence():
    result = sync_evidence(
        dict(
            schema="appliance.activity.event/2",
            event_code="sync_completed",
            sync_status="complete",
            per_root_results=[dict(project_name="P")],
        )
    )
    assert result["sync_status"] == "unknown"


def test_positive_mutation_evidence_cannot_be_overridden_by_zero_aggregate():
    result = sync_evidence(
        dict(
            sync_status="complete",
            changed=0,
            per_root_results=[
                dict(sync_status="complete", changed=1),
                dict(sync_status="complete"),
            ],
        )
    )
    assert result["changes_known"] and result["changes"] > 0


def test_nested_test_transport_and_unidentified_temporary_origin(tmp_path):
    service = service_at(
        tmp_path,
        [
            dict(
                transport="test_transport",
                environment="production",
                event_records=[
                    dict(message="test transport warning", event_id="child")
                ],
            ),
            dict(
                event_id="temporary",
                message="unknown origin",
                local_project_root="/tmp/tmpordinary/Project",
            ),
        ],
    )
    rows = {r.event_id: r for r in service.activity_logs().entries}
    assert rows["child"].origin == "test"
    assert rows["temporary"].origin == "unknown"
