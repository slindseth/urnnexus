"""Transport tests against the appliance's real offline CLI and schema v2.

Only temporary Nexus-owned projects are written. Semantic rows are explicit
contract fixtures, not claims that FixtureAnalysis discovered an issue.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from backend.app.config import ApplianceSettings
from backend.app.main import create_app
from backend.app.services.project_memory import MemoryAction, MemoryError

CLI_ROOT = Path(
    os.getenv(
        "NEXUS_TEST_MEMORY_CLI_ROOT",
        str(Path(__file__).resolve().parents[2] / "appliance"),
    )
)
ACTION = {"X-Nexus-Action": "project-memory"}


def seed_workspace(base: Path, cli_root: Path = CLI_ROOT):
    root = base / "Prosjekt Æ"
    root.mkdir(parents=True)
    (root / "avtale.txt").write_text(
        "Bygg A: Avfall skal fjernes. Deponikostnader må avklares.\n"
    )
    (root / "skann.pdf").write_bytes(b"Unreadable synthetic PDF")
    (root / "modell.smc").write_bytes(b"Synthetic unsupported SMC")
    state = base / "state"
    environment = dict(
        APPLIANCE_MEMORY_EMBEDDING_MODE="disabled", APPLIANCE_MEMORY_MAX_REQUESTS="20"
    )
    command = [
        str(cli_root / ".venv/bin/python"),
        str(cli_root / "scripts/review_project.py"),
        "run",
        str(root),
        "--state-root",
        str(state),
        "--provider",
        "fixture",
        "--no-embeddings",
    ]
    result = subprocess.run(
        command,
        env=dict(
            os.environ, **environment, PYTHONDONTWRITEBYTECODE="1", OPENAI_API_KEY=""
        ),
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    job, project = status["job_id"], status["project_id"]
    # Minimal immutable fixture assertions, attached to actual section work.
    with sqlite3.connect(state / "memory.sqlite3") as db:
        db.row_factory = sqlite3.Row
        unit = db.execute(
            "SELECT * FROM units WHERE state='reviewable' LIMIT 1"
        ).fetchone()
        work = db.execute(
            "SELECT w.id FROM work w JOIN job_work jw ON jw.work=w.id WHERE jw.job=? AND w.operation='section_review' LIMIT 1",
            (job,),
        ).fetchone()[0]
        ids = ["evidence:fixture-a", "evidence:fixture-b"]
        for eid in ids:
            db.execute(
                "INSERT INTO evidence VALUES (?,?,?,?,?,?)",
                (
                    eid,
                    project,
                    work,
                    unit["version"],
                    unit["id"],
                    json.dumps(
                        dict(
                            excerpt="Avfall skal fjernes.",
                            statement="Avfallsansvar",
                            kind="stated_fact",
                            uncertainty="Kontroller omfang",
                        )
                    ),
                ),
            )
        finding = dict(
            id="finding-group:fixture",
            title="Avklar avfallsansvar",
            conclusion="Avklar kostnader internt.",
            category="contradiction",
            categories=["contradiction", "risk"],
            evidence=ids,
            uncertainty="Ingen dokumentrang oppgitt",
            recommended_check="Kontroller avtalegrunnlaget.",
            verification=dict(
                supported=True,
                evidence=ids,
                reason="Syntetisk kontraktsfixture",
                uncertainty="",
            ),
            member_ids=["finding:a", "finding:b"],
            member_findings=[
                dict(
                    id="finding:a",
                    title="Første utsagn",
                    conclusion="Avfall",
                    uncertainty="Omfang",
                    recommended_check="Kontroller",
                ),
                dict(
                    id="finding:b",
                    title="Andre utsagn",
                    conclusion="Kostnad",
                    uncertainty="Rang",
                    recommended_check="Avklar",
                ),
            ],
        )
        db.execute(
            "INSERT INTO views VALUES (?,?,?,?,?,?)",
            (
                "view:fixture-finding",
                project,
                job,
                "reported_finding",
                json.dumps(finding),
                status["created_at"],
            ),
        )
        stored = json.loads(
            db.execute("SELECT result FROM jobs WHERE id=?", (job,)).fetchone()[0]
        )
        stored["findings"] = 1
        db.execute("UPDATE jobs SET result=? WHERE id=?", (json.dumps(stored), job))
    legacy = base / "legacy"
    legacy.mkdir()
    other = base / "Andre prosjekt"
    other.mkdir()
    registry = base / "projects.json"
    registry.write_text(
        json.dumps(
            {
                "projects": [
                    dict(
                        name="Prosjekt Æ",
                        project_root=str(root),
                        state_root=str(state),
                        project_id=project,
                        environment=environment,
                    ),
                    dict(
                        name="Andre prosjekt",
                        project_root=str(other),
                        state_root=str(base / "other-state"),
                    ),
                ]
            }
        )
    )
    return dict(
        root=root,
        state=state,
        registry=registry,
        legacy=legacy,
        status=status,
        environment=environment,
        unit=dict(unit),
        finding=finding,
    )


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    if not (CLI_ROOT / "scripts/review_project.py").is_file():
        pytest.skip("Set NEXUS_TEST_MEMORY_CLI_ROOT to the completed appliance")
    return seed_workspace(tmp_path_factory.mktemp("nexus-memory-seed"))


@pytest.fixture
def workspace(seed, tmp_path):
    original = seed["root"].parent
    base = tmp_path / "workspace"
    shutil.copytree(original, base)
    root, state = base / seed["root"].name, base / "state"
    registry = base / "projects.json"
    registry.write_text(registry.read_text().replace(str(original), str(base)))
    with sqlite3.connect(state / "memory.sqlite3") as db:
        db.execute(
            "UPDATE projects SET root=replace(root,?,?)", (str(original), str(base))
        )
        db.execute(
            "UPDATE versions SET object_path=replace(object_path,?,?)",
            (str(original), str(base)),
        )
        db.execute(
            "UPDATE reports SET path=replace(path,?,?)", (str(original), str(base))
        )
    settings = ApplianceSettings(
        appliance_root=base / "legacy",
        memory_cli_root=CLI_ROOT,
        memory_projects_file=registry,
        memory_runtime_root=base / "runtime",
        memory_provider="fixture",
    )
    app = create_app(settings)
    return {
        **seed,
        "root": root,
        "state": state,
        "registry": registry,
        "app": app,
        "client": TestClient(app),
        "settings": settings,
        "gateway": app.state.appliance_service.memory,
    }


def path(workspace, suffix="", project="Prosjekt Æ", job=None):
    job = job or workspace["status"]["job_id"]
    return f"/api/projects/{quote(project, safe='')}/memory/jobs/{quote(job, safe='')}{suffix}"


def test_reads_preserve_durable_ids_and_do_not_launch_analysis(workspace, monkeypatch):
    w = workspace
    before = (
        sqlite3.connect(w["state"] / "memory.sqlite3")
        .execute("SELECT count(*) FROM usage")
        .fetchone()[0]
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("GET must not launch an analysis worker")

    # subprocess.run legitimately uses Popen for documented read commands.
    monkeypatch.setattr(w["gateway"], "start", forbidden)
    client = w["client"]
    response = client.get(path(w))
    assert response.status_code == 200
    body = response.json()
    assert body["job"]["job_id"] == w["status"]["job_id"]
    assert body["job"]["snapshot_id"] == w["status"]["snapshot_id"]
    assert body["job"]["manual_review_units"] > 0
    assert body["job"]["status"] == "partial"
    assert body["worker_active"] is False
    summary = client.get("/api/projects").json()["projects"]
    assert (
        next(p for p in summary if p["project_name"] == "Prosjekt Æ")["status"]
        == "partial"
    )
    assert "report_path" not in body["job"]
    restarted = TestClient(create_app(w["settings"]))
    assert restarted.get(path(w)).json()["job"]["job_id"] == body["job"]["job_id"]
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM usage").fetchone()[0] == before == 0


def test_consolidated_evidence_and_exact_source_versions(workspace):
    w = workspace
    response = w["client"].get(path(w, "/findings"))
    assert response.status_code == 200
    finding = next(
        f for f in response.json()["findings"] if f["id"] == w["finding"]["id"]
    )
    assert finding == w["finding"]
    original = (w["root"] / "avtale.txt").read_bytes()
    (w["root"] / "avtale.txt").write_text("Ny og annerledes versjon")
    for eid in finding["evidence"]:
        evidence = w["client"].get(path(w, f"/evidence/{eid}")).json()
        assert evidence["document_version_id"] == w["unit"]["version"]
        assert evidence["source_hash"] == hashlib.sha256(original).hexdigest()
        source = w["client"].get(evidence["source_url"])
        assert source.status_code == 200 and source.content == original
    assert w["client"].get(path(w)).json()["freshness"]["state"] == "changed"


def test_partial_reports_preview_manual_sources_and_legacy_download(workspace):
    w = workspace
    reports = w["client"].get(path(w, "/reports")).json()["reports"]
    assert reports
    report = reports[0]
    downloaded = w["client"].get(report["download_url"])
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == report["hash"]
    preview = w["client"].get(report["preview_url"])
    assert preview.status_code == 200 and "Tekstvisning" in preview.text
    assert (
        "officeapps" not in preview.text
        and "default-src 'none'" in preview.headers["content-security-policy"]
    )
    units = w["client"].get(path(w, "/manual-review")).json()["units"]
    assert units
    for unit in units:
        assert w["client"].get(unit["source_url"]).status_code == 200
    assert w["client"].get(path(w, "/manual-review")).json()["units"] == units
    # Existing report discovery/download remains usable for unverified legacy files.
    old = w["root"] / "Kommentarer" / "Prosjekt Æ - Kommentardokument - 0.1.docx"
    old.write_bytes(downloaded.content)
    rows = (
        w["client"]
        .get(f"/api/projects/{quote('Prosjekt Æ')}/reports")
        .json()["reports"]
    )
    legacy = next(
        r
        for r in rows
        if r["report_name"] == "Prosjekt Æ - Kommentardokument - 0.1.docx"
    )
    assert w["client"].get(legacy["download_url"]).content == downloaded.content


def test_project_job_and_object_boundaries(workspace):
    w = workspace
    client = w["client"]
    assert client.get(path(w, project="Andre prosjekt")).status_code == 404
    assert client.get(path(w, "/evidence/evidence:unknown")).status_code == 404
    assert client.get(path(w, "/reports/report:unknown/download")).status_code == 404
    # Another real project within the same database must still not cross scopes.
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        db.execute(
            "INSERT INTO projects VALUES ('project:other',?,?)",
            (str(w["root"].parent / "Andre prosjekt"), w["status"]["created_at"]),
        )
        db.execute(
            "INSERT INTO reports VALUES ('report:other','project:other',?,?,?,?)",
            (
                w["status"]["job_id"],
                "/etc/passwd",
                "irrelevant",
                w["status"]["created_at"],
            ),
        )
    assert client.get(path(w, "/reports/report:other/download")).status_code == 404
    report = client.get(path(w, "/reports")).json()["reports"][0]
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        db.execute(
            "UPDATE reports SET path='/etc/passwd' WHERE id=?", (report["report_id"],)
        )
    assert client.get(report["download_url"]).status_code == 404
    source = client.get(path(w, "/evidence/evidence:fixture-a")).json()
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        db.execute(
            "UPDATE versions SET hash='wrong' WHERE id=?",
            (source["document_version_id"],),
        )
    assert client.get(source["source_url"]).status_code == 404
    assert client.get(path(w, "/findings?after=-1")).status_code == 422
    assert client.get(path(w, "/decisions")).status_code == 400


def test_history_and_failed_or_unavailable_state(workspace):
    w = workspace
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        row = db.execute("SELECT * FROM jobs LIMIT 1").fetchone()
        db.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "job:new",
                row[1],
                "snapshot:new",
                row[3],
                "review",
                "failed",
                0,
                "2099-01-01",
                "2099-01-01",
                "{}",
            ),
        )
    old = w["client"].get(path(w)).json()
    assert old["historical"] is True
    failed = w["client"].get(path(w, job="job:new")).json()
    assert failed["job"]["status"] == "failed" and failed["can_resume"] is True
    w["gateway"].cli_root = w["root"] / "missing-cli"
    w["gateway"]._cache.clear()
    response = w["client"].get(path(w))
    assert (
        response.status_code == 503
        and response.json()["code"] == "memory_cli_unavailable"
    )
    assert str(w["root"]) not in response.text


def test_missing_state_does_not_create_database_and_schema_is_guarded(workspace):
    w = workspace
    response = w["client"].get("/api/projects/Andre%20prosjekt/memory/jobs")
    assert response.json()["jobs"] == []
    assert not (w["root"].parent / "other-state").exists()
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        db.execute("PRAGMA user_version=99")
    assert w["client"].get(path(w)).json()["code"] == "memory_schema_unsupported"


def test_start_full_resume_cancel_transport_and_cross_restart_lock(
    workspace, monkeypatch
):
    w = workspace
    commands = []

    class Process:
        def wait(self):
            return 0

    def launch(command, **kwargs):
        commands.append((command, kwargs))
        return Process()

    monkeypatch.setattr("backend.app.services.project_memory.subprocess.Popen", launch)
    gateway = w["gateway"]
    assert (
        w["client"]
        .post("/api/projects/Prosjekt%20%C3%86/memory/run", json={})
        .status_code
        == 403
    )
    assert gateway.start("Prosjekt Æ", MemoryAction(mode="full"))["job_id"] is None
    command, kwargs = commands[-1]
    assert "review_project.py" in command[1] and command[2] == "run"
    assert "--full" in command and "--progress" in command and "--provider" in command
    assert (
        "--email-mode" not in command
        and "run_onedrive_appliance.py" not in " ".join(command)
    )
    assert kwargs["pass_fds"] and kwargs["start_new_session"]
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        db.execute(
            "UPDATE jobs SET status='cancelled' WHERE id=?", (w["status"]["job_id"],)
        )
    gateway.start(
        "Prosjekt Æ", MemoryAction(mode="resume", job_id=w["status"]["job_id"])
    )
    assert (
        commands[-1][0][-2:] == ["--job-id", w["status"]["job_id"]]
        or "--job-id" in commands[-1][0]
    )
    import fcntl

    binding = gateway.binding("Prosjekt Æ")
    with gateway.lock_path(binding).open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        restarted = create_app(w["settings"]).state.appliance_service.memory
        assert restarted.active(restarted.binding("Prosjekt Æ"))
        with pytest.raises(MemoryError, match="arbeider allerede"):
            restarted.start("Prosjekt Æ", MemoryAction())
    # Cancel is explicit/cooperative and does not claim the process exited.
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        db.execute(
            "UPDATE jobs SET status='running' WHERE id=?", (w["status"]["job_id"],)
        )
    monkeypatch.setattr(gateway, "active", lambda binding: True)

    def read(binding, operation, **args):
        assert operation == "cancel" and args["job_id"] == w["status"]["job_id"]
        return dict(cancellation_requested=True)

    monkeypatch.setattr(gateway, "read", read)
    assert (
        gateway.cancel("Prosjekt Æ", w["status"]["job_id"])["cancellation_requested"]
        is True
    )


def test_real_cooperative_cancel_and_negative_scope(workspace):
    import fcntl

    w = workspace
    gateway = w["gateway"]
    binding = gateway.binding("Prosjekt Æ")
    lock_path = gateway.lock_path(binding)
    lock_path.parent.mkdir(parents=True)
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        db.execute(
            "UPDATE jobs SET status='running' WHERE id=?", (w["status"]["job_id"],)
        )
    # Simulate only the lock/liveness; execute the actual CLI cancel transport.
    with lock_path.open("wb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        response = w["client"].post(path(w, "/cancel"), headers=ACTION)
        assert response.status_code == 200 and response.json()["cancellation_requested"]
        status = w["client"].get(path(w)).json()
        assert status["cancellation_requested"] is True
        assert (
            status["job"]["status"] == "running"
        )  # A request is not a completed stop.
    assert w["client"].get(path(w, "/units/unit:foreign/source")).status_code == 404
    with sqlite3.connect(w["state"] / "memory.sqlite3") as db:
        db.execute(
            "INSERT INTO projects VALUES ('project:foreign','/synthetic-foreign','2026-01-01')"
        )
        row = db.execute("SELECT * FROM jobs LIMIT 1").fetchone()
        db.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "job:foreign",
                "project:foreign",
                row[2],
                row[3],
                "review",
                "running",
                0,
                row[7],
                row[8],
                "{}",
            ),
        )
        db.execute(
            "INSERT INTO evidence SELECT 'evidence:foreign','project:foreign',work,version,unit,payload FROM evidence LIMIT 1"
        )
    assert w["client"].get(path(w, job="job:foreign")).status_code == 404
    assert w["client"].get(path(w, "/evidence/evidence:foreign")).status_code == 404


def test_activity_uses_native_events_and_persisted_active_job(workspace):
    import fcntl
    w = workspace
    binding = w['gateway'].binding('Prosjekt Æ')
    lock = w['gateway'].lock_path(binding)
    lock.parent.mkdir(parents=True, exist_ok=True)
    job_id = w['status']['job_id']
    with sqlite3.connect(w['state'] / 'memory.sqlite3') as db:
        db.execute("UPDATE jobs SET status='running',stage='ocr' WHERE id=?", (job_id,))
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for client in [w['client'], TestClient(create_app(w['settings']))]:
            status = client.get('/api/activity/status').json()
            assert status['job_id'] == job_id
            assert status['project_name'] == 'Prosjekt Æ'
            assert status['current_phase'] == 'ocr'
            assert status['state'] == 'Analyserer'
    restarted = TestClient(create_app(w['settings']))
    assert restarted.get('/api/activity/status').json()['job_id'] is None
    events = restarted.get('/api/activity/logs').json()['entries']
    native = [r for r in events if r['source'] == 'project_memory']
    assert native and all(r['job_id'] == job_id for r in native)
    assert all('native_event' in r['raw'] and r['event_id'].startswith('memory:') for r in native)
    assert all(r['origin'] == 'unknown' for r in native)  # native schema has no environment
    assert not any(r['message'] == 'Running OCR' for r in native)


def test_coverage_retains_unreadable_manifest_and_unsupported_smc(workspace):
    w = workspace
    status = w['status']
    with sqlite3.connect(w['state'] / 'memory.sqlite3') as db:
        row = db.execute('SELECT manifest FROM snapshots WHERE id=?',(status['snapshot_id'],)).fetchone()
        manifest = json.loads(row[0])
        manifest.append(dict(path='unreadable.bin',version=None,disposition='manual_review',reason='unreadable_source'))
        db.execute('UPDATE snapshots SET manifest=? WHERE id=?',(json.dumps(manifest),status['snapshot_id']))
    response = w['client'].get(path(w)).json()
    assert response['coverage_unreadable'][0]['path'] == 'unreadable.bin'
    manual = w['client'].get(path(w, '/manual-review')).json()['units']
    assert any(unit['path'].endswith('.smc') and unit['state'] in {'unsupported', 'manual_review'} for unit in manual)
    assert response['job']['status']=='partial'
    reports = w['client'].get(path(w, '/reports')).json()['reports']
    assert reports and w['client'].get(reports[0]['download_url']).status_code == 200
