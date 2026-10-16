// @vitest-environment jsdom
import { act, Fragment, StrictMode, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppLayout } from "../components/Layout";
import { DashboardPage } from "../pages/DashboardPage";
import { APPLIANCE_BUSY_MESSAGE } from "../lib/applianceStatus";
import * as api from "../lib/api";
import { AppDataProvider, useAppData } from "./AppDataContext";
import type { AnalysisStatusResponse, HealthResponse, ProjectListResponse, ReadinessResponse, SyncRunResponse, SyncStatusResponse } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const health: HealthResponse = {
  appliance_available: true,
  uptime_seconds: 120,
  uptime: "0:02:00",
  version: "0.1.9",
  appliance_root: "/home/anbudklient/appliance",
  discovered_projects: 0,
  last_synced_at: "2026-06-12T08:00:00+02:00",
  last_analyzed_at: null,
  latest_report_generated_at: null,
  project_count: 0,
  file_count: 0,
  report_count: 0,
  one_drive_status: "available",
  one_drive_detail: "OneDrive er tilgjengelig.",
  graph_write_status: "configured",
  graph_write_detail: "Graph-write er konfigurert.",
  openai_status: "configured",
  openai_detail: "OPENAI_API_KEY er satt.",
  smtp_status: "not_configured",
  smtp_detail: "SMTP_HOST mangler.",
  disk_total_bytes: 1000,
  disk_used_bytes: 500,
  disk_free_bytes: 500,
  cache_size_bytes: 250,
  errors_last_24h: 0,
  warnings_last_24h: 0,
};

let mountedRoot: Root | null = null;

function getLocalDayKey(date = new Date()): string {
  const year = String(date.getFullYear());
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function makeIdleAnalysisStatus(): AnalysisStatusResponse {
  return {
    running: false,
    process_alive: false,
    lock_exists: false,
    lock_stale: false,
    activity: "idle",
    job_id: null,
    start_requested_at: null,
    last_started_at: null,
    last_completed_at: null,
    startup_grace_active: false,
    process_spawned: false,
    auth_status: "unknown",
    last_error: null,
    last_start_error: null,
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
    reports_generated: 0,
    email_mode: null,
    project_name: null,
    status: "idle",
    analysis_started: false,
  };
}

function makeReadyResponse(): ReadinessResponse {
  return { ready: true, backend: true, appliance: true, graph: true, status: "ready" };
}

function renderApp(analysisStatus: AnalysisStatusResponse = makeIdleAnalysisStatus(), routeContent: ReactNode = <div>Body</div>, withStrictMode = false) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoot = root;
  const Wrapper = withStrictMode ? StrictMode : Fragment;

  vi.spyOn(api, "getAnalysisStatus").mockResolvedValue(analysisStatus);
  vi.spyOn(api, "getSystemReadiness").mockResolvedValue(makeReadyResponse());

  act(() => {
    root.render(
      <Wrapper>
        <MemoryRouter initialEntries={["/"]}>
          <AppDataProvider>
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={routeContent} />
              </Route>
            </Routes>
          </AppDataProvider>
        </MemoryRouter>
      </Wrapper>,
    );
  });

  return { container };
}

function makeProjectsResponse(): ProjectListResponse {
  return { count: 0, projects: [], warnings: [] };
}

function makeIdleSyncStatus(): SyncStatusResponse {
  return {
    running: false,
    process_alive: false,
    lock_exists: false,
    lock_stale: false,
    activity: "idle",
    job_id: null,
    last_started_at: null,
    last_completed_at: null,
    last_error: null,
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
    status: "idle",
  };
}

function makeRunningSyncStatus(): SyncStatusResponse {
  return {
    running: true,
    process_alive: true,
    lock_exists: true,
    lock_stale: false,
    activity: "sync",
    job_id: "sync-job",
    last_started_at: "2026-06-12T08:00:00+02:00",
    last_completed_at: null,
    last_error: null,
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
    status: "running",
  };
}

function makeCompletedSyncStatus(): SyncStatusResponse {
  return {
    running: false,
    process_alive: false,
    lock_exists: false,
    lock_stale: false,
    activity: "idle",
    job_id: "sync-job",
    last_started_at: "2026-06-12T08:00:00+02:00",
    last_completed_at: "2026-06-12T08:03:00+02:00",
    last_error: null,
    projects_synced: 2,
    files_changed: 4,
    reports_found: 1,
    status: "completed",
  };
}

function makeFailedSyncStatus(): SyncStatusResponse {
  return {
    running: false,
    process_alive: false,
    lock_exists: false,
    lock_stale: false,
    activity: "idle",
    job_id: "sync-job",
    last_started_at: "2026-06-12T08:00:00+02:00",
    last_completed_at: "2026-06-12T08:05:00+02:00",
    last_error: "OneDrive sync failed.",
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
    status: "failed",
    error_code: "sync_failed",
  };
}

function makeSyncRunResponse(): SyncRunResponse {
  return {
    job_id: "sync-job",
    running: true,
    started_at: "2026-06-12T08:00:00+02:00",
    status: "started",
    sync_only: true,
    analysis_started: false,
    reports_generated: 0,
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  act(() => {
    mountedRoot?.unmount();
  });
  vi.useRealTimers();
  mountedRoot = null;
  document.body.innerHTML = "";
  window.localStorage.clear();
});

function RetryStartupButton() {
  const { retryStartup } = useAppData();
  return <button onClick={retryStartup}>Retry startup</button>;
}

describe("AppDataProvider startup lifecycle", () => {
  it("recovers startup after StrictMode effect cleanup and loads dashboard data", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T09:00:00+02:00"));
    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    const getHealthSpy = vi.spyOn(api, "getHealth").mockResolvedValue(health);
    vi.spyOn(api, "getSyncStatus").mockResolvedValue(makeCompletedSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp(makeIdleAnalysisStatus(), <div>Body</div>, true);
    await act(async () => {
      for (let index = 0; index < 8; index += 1) {
        await Promise.resolve();
      }
    });

    expect(container.textContent).not.toContain("Starter NEXUS");
    expect(container.textContent).not.toContain("NEXUS kunne ikke starte");
    expect(getProjectsSpy).toHaveBeenCalledTimes(1);
    expect(getHealthSpy).toHaveBeenCalledTimes(1);
    expect(runSyncSpy).not.toHaveBeenCalled();
  });

  it("resumes daily sync polling after startup is retried without duplicating the job", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T09:00:00+02:00"));
    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi.spyOn(api, "getSyncStatus").mockResolvedValue(makeRunningSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());
    const { container } = renderApp(makeIdleAnalysisStatus(), <RetryStartupButton />, true);

    await act(async () => {
      for (let index = 0; index < 8; index += 1) await Promise.resolve();
    });
    expect(container.textContent).toContain("Vent et øyeblikk mens OneDrive synkroniseres");

    await act(async () => {
      const retryButton = Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent === "Retry startup",
      );
      if (!retryButton) throw new Error("Missing startup retry button");
      retryButton.click();
      for (let index = 0; index < 8; index += 1) await Promise.resolve();
    });
    expect(container.textContent).toContain("Vent et øyeblikk mens OneDrive synkroniseres");

    getSyncStatusSpy.mockResolvedValue(makeCompletedSyncStatus());
    await act(async () => {
      vi.advanceTimersByTime(3000);
      for (let index = 0; index < 8; index += 1) await Promise.resolve();
    });
    expect(container.textContent).not.toContain("Vent et øyeblikk mens OneDrive synkroniseres");
    expect(getProjectsSpy).toHaveBeenCalledTimes(3);
    expect(runSyncSpy).not.toHaveBeenCalled();
  });
});

describe("AppDataProvider daily sync", () => {
  it("starts the daily sync on first app open and closes the popup when it completes", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T08:30:00+02:00"));

    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    const getHealthSpy = vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi
      .spyOn(api, "getSyncStatus")
      .mockResolvedValueOnce(makeIdleSyncStatus())
      .mockResolvedValueOnce(makeCompletedSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      for (let index = 0; index < 5; index += 1) {
        await Promise.resolve();
      }
    });

    expect(container.textContent).toContain("Velkommen til Urban Reuse Norway's NEXUS verktøy");
    expect(container.textContent).toContain("Vent et øyeblikk mens OneDrive synkroniseres");
    expect(runSyncSpy).toHaveBeenCalledTimes(1);
    expect(getSyncStatusSpy).toHaveBeenCalledTimes(1);
    expect(JSON.parse(window.localStorage.getItem("urn-nexus:daily-onedrive-sync") ?? "null")).toMatchObject({
      status: "running",
      date: "2026-06-12",
    });

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).not.toContain("Vent et øyeblikk mens OneDrive synkroniseres");
    expect(getSyncStatusSpy).toHaveBeenCalledTimes(2);
    expect(getProjectsSpy).toHaveBeenCalledTimes(2);
    expect(getHealthSpy).toHaveBeenCalledTimes(2);
    expect(JSON.parse(window.localStorage.getItem("urn-nexus:daily-onedrive-sync") ?? "null")).toMatchObject({
      status: "completed",
      date: "2026-06-12",
    });
  });

  it("resumes an already running sync without starting a second job", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T09:00:00+02:00"));

    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    const getHealthSpy = vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi
      .spyOn(api, "getSyncStatus")
      .mockResolvedValueOnce(makeRunningSyncStatus())
      .mockResolvedValueOnce(makeCompletedSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Velkommen til Urban Reuse Norway's NEXUS verktøy");
    expect(container.textContent).toContain("Vent et øyeblikk mens OneDrive synkroniseres");
    expect(runSyncSpy).not.toHaveBeenCalled();
    expect(getSyncStatusSpy).toHaveBeenCalledTimes(1);
    expect(JSON.parse(window.localStorage.getItem("urn-nexus:daily-onedrive-sync") ?? "null")).toMatchObject({
      status: "running",
      date: "2026-06-12",
    });

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).not.toContain("Vent et øyeblikk mens OneDrive synkroniseres");
    expect(getSyncStatusSpy).toHaveBeenCalledTimes(2);
    expect(getProjectsSpy).toHaveBeenCalledTimes(2);
    expect(getHealthSpy).toHaveBeenCalledTimes(2);
  });

  it("switches to a recoverable warning with retry/details actions if sync takes too long", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T09:30:00+02:00"));

    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    const getHealthSpy = vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi
      .spyOn(api, "getSyncStatus")
      .mockResolvedValueOnce(makeIdleSyncStatus())
      .mockResolvedValue(makeRunningSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runSyncSpy).toHaveBeenCalledTimes(1);
    expect(getSyncStatusSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(25_000);
      for (let index = 0; index < 5; index += 1) {
        await Promise.resolve();
      }
    });

    expect(container.textContent).toContain("Synkronisering tar lengre tid enn forventet. Du kan fortsette med sist synkroniserte data.");
    expect(container.textContent).toContain("Prøv igjen");
    expect(container.textContent).toContain("Se detaljer");
    expect(container.textContent).not.toContain("Fortsett");

    await act(async () => {
      const detailsButton = Array.from(container.querySelectorAll("a, button")).find((button) => button.textContent?.trim() === "Se detaljer");
      if (!detailsButton) {
        throw new Error("Could not find Se detaljer button");
      }
      (detailsButton as HTMLElement).click();
      await Promise.resolve();
    });

    expect(container.textContent).not.toContain("Synkronisering tar lengre tid enn forventet. Du kan fortsette med sist synkroniserte data.");
    expect(getProjectsSpy).toHaveBeenCalledTimes(1);
    expect(getHealthSpy).toHaveBeenCalledTimes(1);
  });

  it("shows the fatal sync modal only for an explicit classified sync failure", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T10:00:00+02:00"));

    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    const getHealthSpy = vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi
      .spyOn(api, "getSyncStatus")
      .mockResolvedValueOnce(makeIdleSyncStatus())
      .mockResolvedValueOnce(makeFailedSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runSyncSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("OneDrive-synkroniseringen feilet.");
    expect(container.textContent).toContain("Synkroniseringen kunne ikke fullføres.");
    expect(container.textContent).toContain("Prøv synkronisering på nytt");
    expect(container.textContent).toContain("Gå til Aktivitet");
    expect(container.textContent).not.toContain("Fortsett");
    expect(container.textContent.match(/OneDrive-synkroniseringen feilet\./g)).toHaveLength(1);
    expect(getSyncStatusSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(getProjectsSpy).toHaveBeenCalledTimes(1);
    expect(getHealthSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      const retryButton = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Prøv synkronisering på nytt");
      if (!retryButton) {
        throw new Error("Could not find sync retry button");
      }
      retryButton.click();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Velkommen til Urban Reuse Norway's NEXUS verktøy");
  });

  it("clears stale lock failures from storage and restarts sync", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T11:00:00+02:00"));

    const todayKey = getLocalDayKey();
    window.localStorage.setItem(
      "urn-nexus:daily-onedrive-sync",
      JSON.stringify({
        date: todayKey,
        started_at: "2026-06-12T10:45:00+02:00",
        completed_at: "2026-06-12T10:46:00+02:00",
        status: "failed",
        last_error: "Awaiting history lock while waiting for onedrive_sync_history.lock to clear.",
      }),
    );

    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    const getHealthSpy = vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi.spyOn(api, "getSyncStatus").mockResolvedValue(makeIdleSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runSyncSpy).toHaveBeenCalledTimes(1);
    expect(getSyncStatusSpy).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Vent et øyeblikk mens OneDrive synkroniseres");
    expect(container.textContent).not.toContain("OneDrive-synkroniseringen feilet.");
    expect(container.textContent).not.toContain("Awaiting history lock");
    expect(container.textContent).not.toContain("onedrive_sync_history.lock");
    expect(JSON.parse(window.localStorage.getItem("urn-nexus:daily-onedrive-sync") ?? "null")).toMatchObject({
      status: "running",
      date: todayKey,
      last_error: null,
    });
    expect(getProjectsSpy).toHaveBeenCalledTimes(1);
    expect(getHealthSpy).toHaveBeenCalledTimes(1);
  });

  it("ignores a persisted generic failed record instead of resurrecting the old failure modal", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T11:30:00+02:00"));
    window.localStorage.setItem(
      "urn-nexus:daily-onedrive-sync",
      JSON.stringify({
        date: getLocalDayKey(),
        started_at: "2026-06-12T11:00:00+02:00",
        completed_at: "2026-06-12T11:01:00+02:00",
        status: "failed",
        last_error: "Internal server error",
      }),
    );

    vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    vi.spyOn(api, "getHealth").mockResolvedValue(health);
    vi.spyOn(api, "getSyncStatus").mockResolvedValue(makeIdleSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runSyncSpy).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Velkommen til Urban Reuse Norway's NEXUS verktøy");
    expect(container.textContent).not.toContain("OneDrive-synkroniseringen feilet.");
    expect(container.textContent).not.toContain("Internal server error");
  });

  it("shows the busy modal when analysis is already running", async () => {
    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    const getHealthSpy = vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi.spyOn(api, "getSyncStatus").mockResolvedValue(makeIdleSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp({
      ...makeIdleAnalysisStatus(),
      running: true,
      status: "running",
      last_started_at: "2026-06-12T10:59:00+02:00",
      last_completed_at: null,
    });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(runSyncSpy).not.toHaveBeenCalled();
    expect(getSyncStatusSpy).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain(APPLIANCE_BUSY_MESSAGE);
    expect(container.textContent).not.toContain("Awaiting history lock");
    expect(container.textContent).not.toContain("onedrive_sync_history.lock");
    expect(getProjectsSpy).toHaveBeenCalledTimes(1);
    expect(getHealthSpy).toHaveBeenCalledTimes(1);
  });

  it("skips the daily sync after it has already completed today", async () => {
    const todayKey = getLocalDayKey();
    window.localStorage.setItem(
      "urn-nexus:daily-onedrive-sync",
      JSON.stringify({
        date: todayKey,
        started_at: "2026-06-12T08:00:00+02:00",
        completed_at: "2026-06-12T08:03:00+02:00",
        status: "completed",
        last_error: null,
      }),
    );

    const getProjectsSpy = vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    const getHealthSpy = vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi.spyOn(api, "getSyncStatus").mockResolvedValue(makeIdleSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).not.toContain("Velkommen til Urban Reuse Norway's NEXUS verktøy");
    expect(container.textContent).not.toContain("Vent et øyeblikk mens OneDrive synkroniseres");
    expect(runSyncSpy).not.toHaveBeenCalled();
    expect(getSyncStatusSpy).toHaveBeenCalledTimes(1);
    expect(getProjectsSpy).toHaveBeenCalledTimes(1);
    expect(getHealthSpy).toHaveBeenCalledTimes(1);
  });

  it("keeps startup visible through temporary 500 responses and recovers on a later status response", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T12:00:00+02:00"));

    vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi
      .spyOn(api, "getSyncStatus")
      .mockRejectedValueOnce(new api.ApiRequestError(500, "Internal server error", "internal_error"))
      .mockRejectedValueOnce(new api.ApiRequestError(500, "Internal server error", "internal_error"))
      .mockResolvedValue(makeIdleSyncStatus());
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.textContent).toContain("Starter NEXUS");
    expect(container.textContent).not.toContain("Internal server error");

    await act(async () => {
      vi.advanceTimersByTime(4000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getSyncStatusSpy).toHaveBeenCalledTimes(3);
    expect(runSyncSpy).toHaveBeenCalledTimes(1);
    expect(container.textContent).not.toContain("NEXUS kunne ikke starte");
    expect(container.textContent).not.toContain("Internal server error");
  });

  it("reproduces the dashboard placeholder scenario without opening a OneDrive failure modal", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T12:15:00+02:00"));
    window.localStorage.setItem(
      "urn-nexus:daily-onedrive-sync",
      JSON.stringify({
        date: "2026-06-12",
        started_at: "2026-06-12T08:00:00+02:00",
        completed_at: "2026-06-12T08:03:00+02:00",
        status: "completed",
        last_error: null,
      }),
    );

    vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    vi.spyOn(api, "getHealth").mockResolvedValue(health);
    const getSyncStatusSpy = vi
      .spyOn(api, "getSyncStatus")
      .mockRejectedValueOnce(new api.ApiRequestError(500, "Internal server error", "internal_error"))
      .mockResolvedValue(makeIdleSyncStatus());

    const { container } = renderApp(makeIdleAnalysisStatus(), <DashboardPage />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Starter NEXUS");
    expect(container.textContent).toContain("Laster prosjekter …");
    expect(container.textContent).toContain("Ukjent");
    expect(container.textContent).toContain("Ingen analyse");
    expect(container.textContent).toContain("Ingen rapport");
    expect(container.textContent).not.toContain("OneDrive-synkroniseringen feilet.");
    expect(container.textContent).not.toContain("Internal server error");

    await act(async () => {
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(getSyncStatusSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(container.textContent).not.toContain("Starter NEXUS");
    expect(container.textContent).not.toContain("OneDrive-synkroniseringen feilet.");
    expect(container.textContent.match(/OneDrive-synkroniseringen feilet\./g)).toBeNull();
  });

  it("shows a friendly startup failure only after the retry window expires", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T12:30:00+02:00"));

    vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    vi.spyOn(api, "getHealth").mockResolvedValue(health);
    vi.spyOn(api, "getSyncStatus").mockRejectedValue(new api.ApiRequestError(500, "Internal server error", "internal_error"));
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      vi.advanceTimersByTime(10_000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("NEXUS kunne ikke starte");
    expect(container.textContent).toContain("Status kunne ikke hentes.");
    expect(container.textContent).not.toContain("Internal server error");
    expect(runSyncSpy).not.toHaveBeenCalled();
  });

  it("fails immediately for an explicit Graph authentication failure", async () => {
    vi.spyOn(api, "getProjects").mockResolvedValue(makeProjectsResponse());
    vi.spyOn(api, "getHealth").mockResolvedValue(health);
    vi.spyOn(api, "getSyncStatus").mockResolvedValue({ ...makeIdleSyncStatus(), error_code: "graph_auth_failed" });
    const runSyncSpy = vi.spyOn(api, "runSync").mockResolvedValue(makeSyncRunResponse());

    const { container } = renderApp();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("NEXUS kunne ikke starte");
    expect(container.textContent).toContain("OneDrive krever ny innlogging.");
    expect(runSyncSpy).not.toHaveBeenCalled();
  });
});
