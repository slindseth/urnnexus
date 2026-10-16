# Sync Status Flow

This note documents how Nexus decides whether Appliance is busy and how the UI should treat sync state.

## Source Of Truth

- `GET /api/system/readiness` is a lightweight startup probe. It only checks backend/Appliance availability and never starts synchronization.
- `GET /api/sync/status`
- `GET /api/analysis/status`

Both responses now expose:

- `running`
- `activity` (`sync`, `analysis`, `idle`)
- `lock_exists`
- `lock_stale`
- `process_alive`

## Busy Rules

- Sync is disabled when sync or analysis is actually running.
- A live history lock also counts as busy, even if the backend lost its in-memory process handle.
- Stale lock errors do not keep the UI disabled.

## Stale Lock Handling

- Nexus checks the history lock under the appliance runtime directory.
- If the lock file exists but the recorded PID is no longer alive, Nexus ignores the stale lock and logs a warning. Status reads leave appliance files intact.
- The appliance runner also removes stale locks when it acquires the history lock.

## UI Rules

- Show `OneDrive synkroniserer` when sync is active.
- Show `Analyse pågår` when analysis is active.
- Show `Klar` when neither job is active.
- Show `Forrige sync feilet` only for a real sync failure, not for a stale lock message.
- Never surface internal lock paths or SQLite filenames in the dashboard.

## Startup Flow

The frontend enters `starting` and then `connecting` while it probes readiness and both status endpoints. It retries at 0, 2, 4, 6, 8, and 10 seconds. HTTP 500, timeout, connection errors, unavailable Appliance responses, and empty status payloads are temporary startup conditions for this window.

The initialization screen closes as soon as a valid status round succeeds. A startup failure is shown only after the retry window expires or when the backend returns an explicit permanent code such as `graph_auth_failed`, `sync_failed`, `backend_configuration_error`, or `appliance_unreachable`. Raw backend details stay in diagnostics/logs; UI copy is mapped to user-friendly Norwegian messages.

## Completion evidence

Terminal process state and sync completeness are separate. `sync_status` is
`complete`, `incomplete`, `failed`, or `unknown`; `enumeration_complete` and
`project_results` carry the appliance evidence. Neither return code zero nor a
completion timestamp proves synchronization completed. The frontend accepts an
explicit `unknown` result as a reachable backend and requires `sync_status=complete`
before recording a successful daily synchronization. Substring matching of
`complete` must never match `incomplete`.

Current activity requires a live process/worker lock. Completed history stays in
the archive and never creates OCR/report/upload/email progress. See the activity
section in [project-memory integration](project-memory-integration.md) for source
selection, provenance, timestamps, identities, and coverage.
