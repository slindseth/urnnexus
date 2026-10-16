"""Nexus transport for the appliance memory contract. No analysis or job database.

Read operations use documented CLI commands. Short read-only SQLite queries
resolve registered project/job identities, immutable files, and persisted views
that have no CLI listing. Only an explicit POST launches a worker or cancels it.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field


class MemoryError(RuntimeError):
    def __init__(self, detail: str, code="memory_unavailable", status=503):
        self.detail, self.code, self.status = detail, code, status
        super().__init__(detail)


class ProjectDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=250)
    project_root: Path
    state_root: Path | None = None
    project_id: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)


class MemoryAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["incremental", "full", "resume"] = "incremental"
    job_id: str | None = Field(default=None, max_length=120)


@dataclass(frozen=True)
class Binding:
    name: str
    root: Path
    state: Path
    project_id: str | None
    environment: dict[str, str]


def identity(kind, *parts):
    # Documented local-state path/lock identity, never a substitute for DB IDs.
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return kind + ":" + hashlib.sha256(raw.encode()).hexdigest()[:32]


class ProjectMemoryGateway:
    def __init__(self, service):
        self.service, self.settings = service, service.settings
        self.cli_root = (
            self.settings.memory_cli_root or self.settings.resolved_appliance_root()
        ).resolve()
        self._cache: dict[tuple, tuple[float, Any]] = {}

    def definitions(self) -> list[ProjectDefinition]:
        path = self.settings.memory_projects_file
        if path is None:
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            definitions = [
                ProjectDefinition.model_validate(row) for row in payload["projects"]
            ]
            if len({d.name.casefold() for d in definitions}) != len(definitions):
                raise ValueError("Duplicate project names")
            for definition in definitions:
                if any(c in definition.name for c in ("/", "\\", "\0")):
                    raise ValueError("Invalid project name")
                if any(
                    not k.startswith("APPLIANCE_MEMORY_")
                    for k in definition.environment
                ):
                    raise ValueError(
                        "Only server-side APPLIANCE_MEMORY_* settings are supported"
                    )
            return definitions
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise MemoryError(
                "Prosjektminnets prosjektregister kan ikke leses. Kontroller serverkonfigurasjonen.",
                "memory_configuration_error",
            ) from exc

    @contextmanager
    def database(self, binding):
        path = binding.state / "memory.sqlite3"
        if not path.is_file():
            raise MemoryError(
                "Ingen gjennomgang er lagret for dette prosjektet ennå.",
                "memory_not_initialized",
                404,
            )
        try:
            connection = sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            yield connection
        except sqlite3.Error as exc:
            raise MemoryError(
                "Prosjektminnet kan ikke leses. Kontroller database og tilgang."
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()

    def binding(self, name, record=None):
        definition = next(
            (d for d in self.definitions() if d.name.casefold() == name.casefold()),
            None,
        )
        if definition:
            root = definition.project_root.expanduser().resolve()
            state = (
                (definition.state_root or root / ".appliance-memory")
                .expanduser()
                .resolve()
            )
            binding = Binding(
                definition.name,
                root,
                state,
                definition.project_id,
                definition.environment,
            )
        else:
            record = record or self.service._get_project_record(
                name, load_files=False, load_reports=False
            )
            root = record.project_path.resolve()
            candidates = [root / ".appliance-memory"]
            if record.state_path and "onedrive_sync" in record.state_path.parts:
                parts = record.state_path.parts
                state_base = Path(*parts[: parts.index("onedrive_sync")])
                candidates.append(
                    state_base
                    / "project-memory"
                    / identity("project", str(root)).split(":")[1]
                )
            if not any((p / "memory.sqlite3").is_file() for p in candidates):
                for database in self.service._state_database_paths():
                    candidates.append(
                        database.parent
                        / "project-memory"
                        / identity("project", str(root)).split(":")[1]
                    )
            state = next(
                (p for p in candidates if (p / "memory.sqlite3").is_file()),
                candidates[0],
            )
            binding = Binding(record.project_name, root, state, None, {})
        if not root.is_dir():
            raise MemoryError(
                "Prosjektmappen er ikke tilgjengelig lokalt.",
                "memory_project_unavailable",
            )
        if (state / "memory.sqlite3").is_file():
            with self.database(binding) as db:
                schema = db.execute("PRAGMA user_version").fetchone()[0]
                if schema != 2:
                    raise MemoryError(
                        "Prosjektminnets databaseversjon støttes ikke. Bruk appliance sin dokumenterte migrering.",
                        "memory_schema_unsupported",
                    )
                project = db.execute(
                    "SELECT id FROM projects WHERE root=?", (str(root),)
                ).fetchone()
                if not project or (
                    binding.project_id and project["id"] != binding.project_id
                ):
                    raise MemoryError(
                        "Prosjektidentiteten samsvarer ikke med registrert mappe.",
                        "memory_project_mismatch",
                        409,
                    )
                binding = Binding(
                    binding.name, root, state, project["id"], binding.environment
                )
        return binding

    def latest_summary(self, record):
        """Small persisted summary for existing dashboard cards; no CLI/model."""
        try:
            binding = self.binding(record.project_name, record)
            if not (binding.state / "memory.sqlite3").is_file():
                return {}
            with self.database(binding) as db:
                row = db.execute(
                    "SELECT status,created_at FROM jobs WHERE project=? ORDER BY created_at DESC,id DESC LIMIT 1",
                    (binding.project_id,),
                ).fetchone()
            return (
                dict(
                    status=row["status"],
                    last_analyzed_at=datetime.fromisoformat(row["created_at"]),
                )
                if row
                else {}
            )
        except (MemoryError, ValueError):
            # The project remains accessible with legacy data; the memory panel
            # supplies the actionable configuration/schema error separately.
            return {}

    def command(
        self,
        binding,
        operation,
        *,
        job_id=None,
        after=None,
        evidence_id=None,
        full=False,
    ):
        script = self.cli_root / "scripts/review_project.py"
        python = self.cli_root / ".venv/bin/python"
        if not script.is_file() or not python.is_file():
            raise MemoryError(
                "Appliance sin prosjektarbeider er ikke tilgjengelig. Kontroller CLI-sti og Python-miljø.",
                "memory_cli_unavailable",
            )
        command = [
            str(python),
            str(script),
            operation,
            str(binding.root),
            "--state-root",
            str(binding.state),
        ]
        if binding.project_id:
            command += ["--project-id", binding.project_id]
        if job_id:
            command += ["--job-id", job_id]
        if after is not None:
            command += ["--after", str(after)]
        if evidence_id:
            command += ["--evidence-id", evidence_id]
        if operation == "run":
            command += ["--progress", "--provider", self.settings.memory_provider]
        if full:
            command.append("--full")
        return command

    def environment(self, binding):
        return dict(os.environ, **binding.environment, PYTHONDONTWRITEBYTECODE="1")

    def read(self, binding, operation, **arguments):
        key = (
            binding.name,
            binding.project_id,
            operation,
            json.dumps(arguments, sort_keys=True),
        )
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < 1:
            return cached[1]
        try:
            process = subprocess.run(
                self.command(binding, operation, **arguments),
                cwd=self.cli_root,
                env=self.environment(binding),
                capture_output=True,
                text=True,
                timeout=8,
            )
            if process.returncode:
                raise MemoryError(
                    "Appliance kunne ikke lese gjennomgangen. Kontroller jobb og prosjektkonfigurasjon.",
                    "memory_cli_failed",
                )
            result = json.loads(process.stdout)
        except subprocess.TimeoutExpired as exc:
            raise MemoryError(
                "Appliance svarte ikke i tide. Prøv igjen.", "memory_timeout", 504
            ) from exc
        except (OSError, ValueError) as exc:
            raise MemoryError(
                "Ugyldig eller utilgjengelig svar fra appliance.", "memory_cli_failed"
            ) from exc
        self._cache[key] = (time.monotonic(), result)
        if len(self._cache) > 256:
            self._cache = {key: self._cache[key]}
        return result

    def require_job(self, binding, job_id):
        with self.database(binding) as db:
            job = db.execute(
                "SELECT * FROM jobs WHERE project=? AND id=?",
                (binding.project_id, job_id),
            ).fetchone()
            if job is None:
                raise MemoryError(
                    "Jobben finnes ikke i dette prosjektet.",
                    "memory_job_not_found",
                    404,
                )
            return dict(job)

    def jobs(self, name, after=0):
        binding = self.binding(name)
        if not (binding.state / "memory.sqlite3").is_file():
            return dict(
                jobs=[],
                next_after=None,
                actions_enabled=self.settings.memory_actions_enabled,
                worker_active=self.active(binding),
            )
        with self.database(binding) as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT id,snapshot,stage,status,created_at,updated_at FROM jobs WHERE project=? ORDER BY created_at DESC,id DESC LIMIT 51 OFFSET ?",
                    (binding.project_id, after),
                )
            ]
        return dict(
            project_id=binding.project_id,
            jobs=rows[:50],
            next_after=after + 50 if len(rows) > 50 else None,
            actions_enabled=self.settings.memory_actions_enabled,
            worker_active=self.active(binding),
        )

    def lock_path(self, binding):
        return self.settings.memory_runtime_root.resolve() / (
            identity("launch", str(binding.root)).split(":")[1] + ".lock"
        )

    def _locked(self, path):
        if not path.is_file():
            return False
        try:
            with path.open("rb") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
        except OSError:
            raise MemoryError(
                "Arbeiderlåsen kan ikke kontrolleres.", "memory_lock_unavailable"
            )
        return False

    def active(self, binding):
        return self._locked(self.lock_path(binding)) or bool(
            binding.project_id
            and self._locked(
                binding.state
                / (identity("lock", binding.project_id).replace(":", "-") + ".lock")
            )
        )

    def launch_active(self):
        return any(
            self._locked(path)
            for path in self.settings.memory_runtime_root.glob("*.lock")
        )

    def status(self, name, job_id):
        binding = self.binding(name)
        row = self.require_job(binding, job_id)
        job = self.read(binding, "status", job_id=job_id).copy()
        job.pop("report_path", None)
        latest = self.jobs(name)["jobs"][0]
        active = self.active(binding)
        return dict(
            job=job,
            worker_active=active,
            cancellation_requested=bool(row["cancelled"]),
            actions_enabled=self.settings.memory_actions_enabled,
            historical=latest["id"] != job_id and latest["snapshot"] != row["snapshot"],
            freshness=self.freshness(binding, row),
            can_resume=not active
            and row["status"] in {"failed", "cancelled", "running"},
        )

    def freshness(self, binding, job):
        # Read-only integrity check of known snapshot sources, not a new inventory
        # or analysis. Missing cache files remain unknown, not absence claims.
        key = ("freshness", binding.project_id, job["snapshot"])
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        changed = []
        unavailable = []
        budget = 16 * 1024 * 1024
        with self.database(binding) as db:
            rows = db.execute(
                "SELECT f.path,v.hash FROM snapshot_files f JOIN versions v ON v.id=f.version AND v.project=f.project WHERE f.project=? AND f.snapshot=?",
                (binding.project_id, job["snapshot"]),
            )
            for index, row in enumerate(rows):
                if index >= 100:
                    unavailable.append(
                        "Flere enn 100 kilder; resten er ikke kontrollert."
                    )
                    break
                file = (binding.root / row["path"]).resolve()
                if not file.is_relative_to(binding.root) or not file.is_file():
                    unavailable.append(row["path"])
                    continue
                try:
                    size = file.stat().st_size
                    if size > budget:
                        unavailable.append(row["path"])
                        continue
                    budget -= size
                    digest = hashlib.sha256()
                    with file.open("rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(block)
                    if digest.hexdigest() != row["hash"]:
                        changed.append(row["path"])
                except OSError:
                    unavailable.append(row["path"])
        result = dict(
            state="changed"
            if changed
            else "unknown"
            if unavailable
            else "known_sources_match",
            changed=changed,
            unavailable=unavailable,
            scope="Kontrollerte kilder i valgt snapshot (inntil 100 filer / 16 MiB). Nye filer og fjernendringer krever ny synk/inventar fra appliance.",
        )
        self._cache[key] = (time.monotonic(), result)
        return result

    def page(self, name, job_id, operation, after=0):
        if operation not in {
            "findings",
            "events",
            "manual-review",
            "references",
            "inventory",
            "cache-events",
            "retrieval-audit",
        }:
            raise MemoryError("Ukjent leseoperasjon.", status=400)
        binding = self.binding(name)
        self.require_job(binding, job_id)
        result = self.read(binding, operation, job_id=job_id, after=after)
        if operation == "manual-review":
            return dict(
                result,
                units=[
                    dict(
                        row,
                        source_url=self.url(
                            name, job_id, f"units/{quote(row['id'], safe='')}/source"
                        ),
                    )
                    for row in result["units"]
                ],
            )
        return result

    def evidence(self, name, job_id, evidence_id):
        binding = self.binding(name)
        self.require_job(binding, job_id)
        with self.database(binding) as db:
            row = db.execute(
                "SELECT e.id FROM evidence e JOIN job_work jw ON jw.work=e.work JOIN jobs j ON j.id=jw.job JOIN snapshot_files f ON f.version=e.version AND f.project=e.project AND f.snapshot=j.snapshot WHERE e.project=? AND j.project=? AND j.id=? AND e.id=?",
                (binding.project_id, binding.project_id, job_id, evidence_id),
            ).fetchone()
            if not row:
                raise MemoryError(
                    "Kilden finnes ikke i denne jobben og dette prosjektet.",
                    "memory_evidence_not_found",
                    404,
                )
        result = self.read(
            binding, "evidence", job_id=job_id, evidence_id=evidence_id
        ).copy()
        result["source_url"] = self.url(
            name, job_id, f"evidence/{quote(evidence_id, safe='')}/source"
        )
        return result

    def url(self, name, job_id, suffix):
        return f"/api/projects/{quote(name, safe='')}/memory/jobs/{quote(job_id, safe='')}/{suffix}"

    def reports(self, name, job_id, after=0):
        binding = self.binding(name)
        job = self.require_job(binding, job_id)
        response = self.read(binding, "reports", job_id=job_id, after=after)
        rows = []
        for row in response["reports"]:
            rows.append(
                dict(
                    report_id=row["id"],
                    job_id=job_id,
                    snapshot_id=job["snapshot"],
                    created_at=row["created_at"],
                    hash=row["hash"],
                    status=job["status"],
                    name=binding.root.name + " - Kommentardokument.docx",
                    download_url=self.url(
                        name, job_id, f"reports/{quote(row['id'], safe='')}/download"
                    ),
                    preview_url=self.url(
                        name, job_id, f"reports/{quote(row['id'], safe='')}/preview"
                    ),
                )
            )
        return dict(reports=rows, next_after=response["next_after"])

    def immutable_file(self, binding, path, expected_hash):
        try:
            resolved = Path(path).resolve(strict=True)
            objects = (binding.state / "objects").resolve(strict=True)
            if not resolved.is_relative_to(objects) or not resolved.is_file():
                raise ValueError()
            digest = hashlib.sha256()
            with resolved.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected_hash:
                raise ValueError()
            return resolved
        except (OSError, ValueError) as exc:
            raise MemoryError(
                "Den lagrede filversjonen mangler eller besto ikke integritetskontrollen.",
                "memory_file_unavailable",
                404,
            ) from exc

    def report_file(self, name, job_id, report_id):
        binding = self.binding(name)
        self.require_job(binding, job_id)
        with self.database(binding) as db:
            row = db.execute(
                "SELECT path,hash FROM reports WHERE project=? AND job=? AND id=?",
                (binding.project_id, job_id, report_id),
            ).fetchone()
            if not row:
                raise MemoryError(
                    "Rapporten finnes ikke i denne jobben og dette prosjektet.",
                    "memory_report_not_found",
                    404,
                )
            path = self.immutable_file(binding, row["path"], row["hash"])
        if path.suffix.lower() != ".docx":
            raise MemoryError("Rapportformatet støttes ikke.", status=404)
        return path, binding.root.name + " - Kommentardokument.docx"

    def source_file(self, name, job_id, evidence_id):
        evidence = self.evidence(name, job_id, evidence_id)
        binding = self.binding(name)
        with self.database(binding) as db:
            row = db.execute(
                "SELECT object_path,hash FROM versions WHERE project=? AND id=?",
                (binding.project_id, evidence["document_version_id"]),
            ).fetchone()
            if not row:
                raise MemoryError("Kildeversjonen finnes ikke.", status=404)
            return self.immutable_file(binding, row["object_path"], row["hash"]), Path(
                evidence["path"]
            ).name

    def unit_source_file(self, name, job_id, unit_id):
        binding = self.binding(name)
        job = self.require_job(binding, job_id)
        with self.database(binding) as db:
            row = db.execute(
                "SELECT v.object_path,v.hash,f.path FROM units u JOIN versions v ON v.id=u.version AND v.project=u.project JOIN snapshot_files f ON f.version=v.id AND f.project=v.project WHERE u.id=? AND u.project=? AND f.snapshot=?",
                (unit_id, binding.project_id, job["snapshot"]),
            ).fetchone()
            if not row:
                raise MemoryError(
                    "Kildeenheten finnes ikke i denne jobben.",
                    "memory_unit_not_found",
                    404,
                )
            return self.immutable_file(binding, row["object_path"], row["hash"]), Path(
                row["path"]
            ).name

    def views(self, name, job_id, after=0):
        binding = self.binding(name)
        job = self.require_job(binding, job_id)
        status = json.loads(job["result"] or "{}")
        with self.database(binding) as db:
            overview = None
            if status.get("overview_id"):
                row = db.execute(
                    "SELECT id,payload FROM views WHERE project=? AND job=? AND id=?",
                    (binding.project_id, job_id, status["overview_id"]),
                ).fetchone()
                if row:
                    overview = dict(
                        id=row["id"],
                        **json.loads(row["payload"]),
                        verified=bool(status.get("overview_verified")),
                    )
            rows = list(
                db.execute(
                    "SELECT v.id,v.payload,w.payload context FROM views v LEFT JOIN work w ON w.id=json_extract(v.payload,'$.work_id') AND w.project=v.project WHERE v.project=? AND v.job=? AND v.kind='topic' ORDER BY v.id LIMIT 21 OFFSET ?",
                    (binding.project_id, job_id, after),
                )
            )
        topics = [
            dict(
                id=r["id"],
                label=json.loads(r["context"] or "{}").get("key", "Tema"),
                **json.loads(r["payload"]),
            )
            for r in rows[:20]
        ]
        return dict(
            overview=overview,
            topics=topics,
            next_after=after + 20 if len(rows) > 20 else None,
            snapshot_id=job["snapshot"],
        )

    def start(self, name, action):
        # Serialize with the existing Nexus sync/start controls. The child-held
        # launch flock preserves exclusion after a backend restart.
        with self.service._sync_lock, self.service._analysis_lock:
            return self._start_locked(name, action)

    def _start_locked(self, name, action):
        if not self.settings.memory_actions_enabled:
            raise MemoryError(
                "Analysestart er slått av på denne Nexus-serveren.",
                "memory_actions_disabled",
                403,
            )
        binding = self.binding(name)
        snapshot = self.service._runtime_activity_snapshot_locked()
        if snapshot.sync_running or snapshot.analysis_running or snapshot.lock_exists:
            raise MemoryError(
                "Appliance arbeider allerede. Vent til aktiv jobb er ferdig.",
                "memory_busy",
                409,
            )
        if action.mode == "resume":
            if not action.job_id:
                raise MemoryError("Velg jobben som skal gjenopptas.", status=400)
            job = self.require_job(binding, action.job_id)
            if job["status"] not in {"failed", "cancelled", "running"}:
                raise MemoryError(
                    "Velg oppdatering for en ferdig jobb.", "memory_not_resumable", 409
                )
        elif action.job_id:
            raise MemoryError("Jobb-ID brukes bare ved gjenopptak.", status=400)
        if self.active(binding):
            raise MemoryError(
                "En arbeider kjører allerede for prosjektet. Følg den eksisterende jobben.",
                "memory_busy",
                409,
            )
        command = self.command(
            binding, "run", job_id=action.job_id, full=action.mode == "full"
        )
        runtime = self.settings.memory_runtime_root.resolve()
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = os.open(
            self.lock_path(binding), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise MemoryError(
                    "En oppstart er allerede i gang.", "memory_busy", 409
                ) from exc
            key = self.lock_path(binding).stem
            handles = []
            try:
                for suffix in ("stdout", "stderr"):
                    fd = os.open(
                        runtime / (key + "." + suffix),
                        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                        0o600,
                    )
                    handles.append(os.fdopen(fd, "w"))
                process = subprocess.Popen(
                    command,
                    cwd=self.cli_root,
                    env=self.environment(binding),
                    stdout=handles[0],
                    stderr=handles[1],
                    pass_fds=(lock,),
                    start_new_session=True,
                    text=True,
                )
                threading.Thread(target=process.wait, daemon=True).start()
                # No job is invented by Nexus. The appliance writes its durable
                # ID before review; the browser reconnects through the job list.
                return dict(accepted=True, job_id=action.job_id, launch_pending=True)
            except OSError as exc:
                raise MemoryError(
                    "Appliance-arbeideren kunne ikke startes.", "memory_launch_failed"
                ) from exc
            finally:
                for handle in handles:
                    handle.close()
        finally:
            os.close(lock)

    def cancel(self, name, job_id):
        if not self.settings.memory_actions_enabled:
            raise MemoryError("Jobbkontroll er slått av.", status=403)
        binding = self.binding(name)
        job = self.require_job(binding, job_id)
        if job["status"] != "running" or not self.active(binding):
            raise MemoryError(
                "Jobben kjører ikke. Ingen stopp ble sendt.", "memory_not_running", 409
            )
        result = self.read(binding, "cancel", job_id=job_id)
        self._cache.clear()
        return result
