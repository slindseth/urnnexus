import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, deleteProject, getActivityEvents, getActivityLogs, getActivityStatus, getAnalysisStatus, getSystemReadiness, getUserFacingErrorMessage, runAnalysis, runSync, StartupError, uploadProjectFile } from "./api";

describe("api sync", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls the sync endpoint for the OneDrive sync button flow", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          job_id: "sync-job",
          running: true,
          process_alive: true,
          lock_exists: true,
          lock_stale: false,
          activity: "sync",
          started_at: "2026-06-08T08:00:00+02:00",
          status: "started",
          sync_only: true,
          analysis_started: false,
          reports_generated: 0,
          projects_synced: 0,
          files_changed: 0,
          reports_found: 0,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const response = await runSync();

    expect(fetchMock).toHaveBeenCalledWith("/api/sync/run", expect.objectContaining({ method: "POST" }));
    expect(response.sync_only).toBe(true);
    expect(response.analysis_started).toBe(false);
    expect(response.reports_generated).toBe(0);
  });

  it("calls the delete endpoint for OneDrive project deletion", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project_name: "Bryn Skole",
          deleted_remote_path: "AnbudAppliance/Urban_Reuse_Norway/Bryn Skole",
          deleted: true,
          existed: true,
          synced: true,
          message: "Prosjektet ble slettet i OneDrive og fjernet fra Nexus.",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const response = await deleteProject("Bryn Skole");

    expect(fetchMock).toHaveBeenCalledWith("/api/projects/Bryn%20Skole", expect.objectContaining({ method: "DELETE" }));
    expect(response.deleted_remote_path).toBe("AnbudAppliance/Urban_Reuse_Norway/Bryn Skole");
    expect(response.deleted).toBe(true);
    expect(response.existed).toBe(true);
    expect(response.synced).toBe(true);
  });

  it("calls the activity endpoints for the operations center", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(
        JSON.stringify({
          updated_at: "2026-06-30T08:12:10+02:00",
          state: "Klar",
          activity: "Ingen aktiv jobb",
          status: "Ingen aktiv jobb",
          project_name: null,
          uptime: "01:23:41",
          uptime_seconds: 5021,
          backend_version: "0.1.9",
          appliance_available: true,
          last_synced_at: null,
          last_analyzed_at: null,
          events: [],
          errors: [],
          entries: [],
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      );
    });

    const statusResponse = await getActivityStatus();
    const eventsResponse = await getActivityEvents();
    const logsResponse = await getActivityLogs();

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/activity/status", expect.objectContaining({ headers: { Accept: "application/json" } }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/activity/events", expect.objectContaining({ headers: { Accept: "application/json" } }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/activity/logs", expect.objectContaining({ headers: { Accept: "application/json" } }));
    expect(statusResponse.state).toBe("Klar");
    expect(eventsResponse.events).toEqual([]);
    expect(logsResponse.entries).toEqual([]);
  });

  it("calls the analysis endpoint for the Analysis page flow", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          job_id: "analysis-job",
          running: true,
          started_at: "2026-06-09T09:00:00+02:00",
          status: "started",
          analysis_started: true,
          reports_generated: 0,
          projects_synced: 0,
          files_changed: 0,
          reports_found: 0,
          email_mode: "daily_digest",
          project_name: "Bryn Skole",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const response = await runAnalysis({ project_name: "Bryn Skole", email_mode: "daily_digest" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/analysis/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          project_name: "Bryn Skole",
          email_mode: "daily_digest",
        }),
      }),
    );
    expect(response.analysis_started).toBe(true);
    expect(response.reports_generated).toBe(0);
    expect(response.email_mode).toBe("daily_digest");
  });

  it("reads the analysis status endpoint for progress refresh", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          running: false,
          process_alive: false,
          lock_exists: false,
          lock_stale: false,
          activity: "idle",
          job_id: "analysis-job",
          start_requested_at: null,
          last_started_at: "2026-06-09T09:00:00+02:00",
          last_completed_at: "2026-06-09T09:15:00+02:00",
          startup_grace_active: false,
          process_spawned: false,
          auth_status: "ok",
          last_error: null,
          last_start_error: null,
          projects_synced: 1,
          files_changed: 2,
          reports_found: 1,
          reports_generated: 1,
          email_mode: "immediate",
          project_name: "Bryn Skole",
          status: "completed",
          analysis_started: false,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const response = await getAnalysisStatus();

    expect(fetchMock).toHaveBeenCalledWith("/api/analysis/status", expect.objectContaining({ headers: { Accept: "application/json" } }));
    expect(response.running).toBe(false);
    expect(response.reports_generated).toBe(1);
    expect(response.email_mode).toBe("immediate");
  });

  it("preserves the relative folder path in file upload payloads without a frontend timeout", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project_name: "Bryn Skole",
          filename: "tilbud.pdf",
          target_folder: "Anbud/Konkurranse/Vedlegg",
          relative_path: "Anbud/Konkurranse/Vedlegg/tilbud.pdf",
          size_bytes: 6,
          mode: "onedrive",
          warning: null,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const file = new File(["tilbud"], "tilbud.pdf", { type: "application/pdf" });
    const response = await uploadProjectFile("Bryn Skole", file, "Anbud/Konkurranse/Vedlegg");
    const [, init] = fetchMock.mock.calls[0];
    const body = init?.body as FormData;

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/Bryn%20Skole/files/upload",
      expect.objectContaining({
        method: "POST",
        signal: undefined,
      }),
    );
    expect(body.get("target_folder")).toBe("Anbud/Konkurranse/Vedlegg");
    expect((body.get("file") as File).name).toBe("tilbud.pdf");
    expect(response.relative_path).toBe("Anbud/Konkurranse/Vedlegg/tilbud.pdf");
  });
});

describe("startup error boundary", () => {
  it("reads the lightweight readiness endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ready: true, backend: true, appliance: true, graph: true, status: "ready" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(getSystemReadiness()).resolves.toMatchObject({ ready: true, status: "ready" });
    expect(fetchMock).toHaveBeenCalledWith("/api/system/readiness", expect.objectContaining({ headers: { Accept: "application/json" } }));
  });

  it("never maps a raw internal server error to end-user copy", () => {
    const error = new ApiRequestError(500, "Internal server error", "internal_error");
    const authError = new ApiRequestError(401, "invalid_grant", "graph_auth_failed");
    const startupError = new StartupError("startup timed out");
    expect(getUserFacingErrorMessage(error)).toBe("Status kunne ikke hentes.");
    expect(getUserFacingErrorMessage(error)).not.toContain("Internal server error");
    expect(error.category).toBe("Backend");
    expect(authError.category).toBe("Graph Authentication");
    expect(startupError.category).toBe("Startup");
  });
});
