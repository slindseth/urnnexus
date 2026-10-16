import json
from pathlib import Path

import pytest

from backend.app.config import ApplianceSettings
from backend.app.services.appliance import ApplianceService


@pytest.mark.parametrize("event_code", ["sync_completed", "sync_completed_no_changes"])
def test_last_successful_sync_survives_restart_and_ignores_failed_jobs(tmp_path: Path, monkeypatch, event_code: str) -> None:
    journal = tmp_path / "cache" / "urn_nexus_activity.jsonl"
    journal.parent.mkdir()
    entries = [
        {"timestamp": "2026-06-12T09:00:00+02:00", "event_code": event_code, "sync_status": "complete"},
        {"timestamp": "2026-06-13T09:00:00+02:00", "event_code": "sync_failed"},
        {"timestamp": "2026-06-14T09:00:00+02:00", "event_code": "analysis_completed"},
    ]
    journal.write_text("\n".join(json.dumps(row) for row in entries) + "\n", encoding="utf-8")
    service = ApplianceService(ApplianceSettings(appliance_root=tmp_path))
    monkeypatch.setattr(service, "discover_projects", lambda: [])

    health = service.health()

    assert health.last_synced_at.isoformat() == "2026-06-12T09:00:00+02:00"
    assert service.sync_status().running is False
