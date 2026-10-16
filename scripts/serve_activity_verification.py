"""Read-only browser harness with a separate, temporary structured-event fixture.

Run via uvicorn scripts.serve_activity_verification:create_verification_app --factory.
Only the isolated fixture is written. The appliance supplies CLI code and history.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from starlette.responses import JSONResponse

from backend.app.config import ApplianceSettings
from backend.app.main import create_app


def create_verification_app():
    appliance = Path(
        os.getenv(
            "URN_NEXUS_APPLIANCE_ROOT",
            str(Path(__file__).resolve().parents[2] / "appliance"),
        )
    )
    root = Path(tempfile.mkdtemp(prefix="nexus-activity-browser-"))
    project, state = root / "Prosjekt Æ", root / "state"
    project.mkdir()
    (project / "avtale.txt").write_text(
        "Syntetisk dokument for offline nettleserkontroll.\n"
    )
    (project / "modell.smc").write_bytes(b"Synthetic unparsed SMC")
    (project / "skann.pdf").write_bytes(b"Synthetic unreadable PDF")
    process = subprocess.run(
        [
            str(appliance / ".venv/bin/python"),
            str(appliance / "scripts/review_project.py"),
            "run",
            str(project),
            "--state-root",
            str(state),
            "--provider",
            "fixture",
            "--no-embeddings",
        ],
        env={
            **os.environ,
            "OPENAI_API_KEY": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "APPLIANCE_MEMORY_EMBEDDING_MODE": "disabled",
            "RIVEANBUD_ENVIRONMENT": "test",
        },
        text=True,
        capture_output=True,
        check=True,
        timeout=40,
    )
    job = json.loads(process.stdout)
    registry = root / "projects.json"
    registry.write_text(
        json.dumps(
            {
                "projects": [
                    {
                        "name": "Prosjekt Æ",
                        "project_root": str(project),
                        "state_root": str(state),
                    }
                ]
            }
        )
    )
    history = root / "activity.jsonl"
    base = dict(
        schema="appliance.activity.event/2",
        project_name="Prosjekt Æ",
        source="onedrive_sync",
        run_id="sync-fixture",
        environment="production",
    )
    rows = [
        dict(
            base,
            event_id="incomplete",
            timestamp="2026-10-01T10:00:00Z",
            sync_status="incomplete",
            enumeration_complete=False,
            event_code="sync_incomplete",
            severity="warning",
            message="Sync incomplete; zero downloads",
        ),
        dict(
            base,
            event_id="warn-1",
            timestamp="2026-09-01T10:00:00Z",
            severity="warning",
            message="Repeated Graph pagination warning",
        ),
        dict(
            base,
            event_id="warn-2",
            timestamp="2026-09-02T10:00:00Z",
            severity="warning",
            message="Repeated Graph pagination warning",
        ),
        dict(
            base,
            event_id="test-failure",
            timestamp="2026-10-02T10:00:00Z",
            severity="error",
            message="Explicit test failure",
            environment="test",
            transport="test_transport",
            technical_only=True,
            user_visible=False,
        ),
        dict(
            event_id="undated",
            project_name="Testprosjekt",
            message="Undated historical evidence",
            source="legacy",
        ),
        dict(
            base,
            event_id="complete-unchanged",
            project_name="Unchanged project",
            timestamp="2026-08-01T10:00:00Z",
            sync_status="complete",
            enumeration_complete=True,
            changed=0,
            status="skipped_no_changes",
        ),
        dict(
            base,
            timestamp="2026-07-01T10:00:00Z",
            sync_status="complete",
            enumeration_complete=True,
            status="completed_with_warnings",
            analysis_exclusions=[
                dict(
                    relative_path="Tegninger/modell.smc",
                    reason="unsupported_smc",
                    download_selected=False,
                )
            ],
        ),
    ]
    history.write_text("".join(json.dumps(row) + "\n" for row in rows))
    appliance_stub = root / "isolated-appliance"
    appliance_stub.mkdir()
    fixture = create_app(
        ApplianceSettings(
            appliance_root=appliance_stub,
            activity_history_paths=[history],
            memory_projects_file=registry,
            memory_cli_root=appliance,
            memory_runtime_root=root / "runtime",
            memory_actions_enabled=False,
        )
    )
    gateway = fixture.state.appliance_service.memory
    lock = gateway.lock_path(gateway.binding("Prosjekt Æ"))
    lock.parent.mkdir(parents=True, exist_ok=True)
    held = lock.open("a")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Explicit test simulation of active persisted processing, with its durable ID.
    with sqlite3.connect(state / "memory.sqlite3") as db:
        db.execute(
            "UPDATE jobs SET status='running',stage='section_review' WHERE id=?",
            (job["job_id"],),
        )
    app = create_app(
        ApplianceSettings(appliance_root=appliance, memory_actions_enabled=False)
    )
    app.state.verification_worker_lock = held
    app.state.verification_root = root
    app.mount("/representative", fixture)

    @app.middleware("http")
    async def read_only(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            return JSONResponse({"detail": "Read-only verification"}, status_code=405)
        return await call_next(request)

    return app
