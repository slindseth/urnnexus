// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { StaticRouter } from "react-router-dom/server";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppDataContext } from "../context/AppDataContext";
import {
  ANALYSIS_RUNNING_LABEL,
  APPLIANCE_BUSY_MESSAGE,
  APPLIANCE_CLEAR_MESSAGE,
  SYNC_LOCK_HELP_TEXT,
  SYNC_RUNNING_LABEL,
  SYNC_STALE_LOCK_WARNING,
} from "../lib/applianceStatus";
import * as api from "../lib/api";
import { formatDateTime } from "../lib/api";
import { createProjectViewModel } from "../lib/projects";
import type { AnalysisStatusResponse, HealthResponse, ProjectSummary, SyncStatusResponse } from "../types";
import {
  DashboardPage,
  getSyncLastErrorMessage,
  isSyncStatusForCurrentJob,
  isSyncBusyLockError,
  resolveDashboardLastSyncedAt,
} from "./DashboardPage";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeProject(overrides: Partial<ProjectSummary>): ProjectSummary {
  return {
    project_name: "Bryn Skole",
    display_name: "Bryn Skole",
    source_label: "OneDrive",
    relative_project_path: "AnbudAppliance/Urban_Reuse_Norway/Bryn Skole",
    hidden_internal_path: "/home/anbudklient/appliance/.riveanbud_runtime/Bryn Skole",
    last_synced_at: "2026-06-04T08:00:00+02:00",
    latest_comment_document: "Bryn Skole - Kommentardokument.docx",
    latest_comment_document_open_url: "/api/projects/Bryn%20Skole/reports/latest/open",
    latest_comment_created_at: "2026-06-04T08:15:00+02:00",
    latest_comment_modified_at: "2026-06-04T08:15:00+02:00",
    comment_document_count: 1,
    is_sample_project: false,
    project_path: "/home/anbudklient/appliance/.riveanbud_runtime/Bryn Skole",
    last_analyzed_at: "2026-06-04T08:15:00+02:00",
    status: "completed_with_warnings",
    file_count: 395,
    report_count: 1,
    warnings: [],
    errors: [],
    ...overrides,
  };
}

const health: HealthResponse = {
  appliance_available: true,
  uptime_seconds: 120,
  uptime: "0:02:00",
  version: "0.1.9",
  appliance_root: "/home/anbudklient/appliance",
  discovered_projects: 2,
  last_synced_at: "2026-06-08T18:03:00+02:00",
  last_analyzed_at: "2026-06-04T08:15:00+02:00",
  latest_report_generated_at: "2026-06-04T08:15:00+02:00",
  project_count: 2,
  file_count: 395,
  report_count: 1,
  one_drive_status: "available",
  one_drive_detail: "2 prosjekter funnet i lokal OneDrive-cache.",
  graph_write_status: "configured",
  graph_write_detail: "Microsoft Graph-write er konfigurert for direkte OneDrive-opprettelse.",
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

function makeSyncStatus(overrides: Partial<SyncStatusResponse> = {}): SyncStatusResponse {
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
    ...overrides,
  };
}

function makeAnalysisStatus(overrides: Partial<AnalysisStatusResponse> = {}): AnalysisStatusResponse {
  return {
    running: false,
    process_alive: false,
    lock_exists: false,
    lock_stale: false,
    activity: "idle",
    job_id: "analysis-job",
    start_requested_at: null,
    last_started_at: "2026-06-12T08:00:00+02:00",
    last_completed_at: "2026-06-12T08:03:00+02:00",
    startup_grace_active: false,
    process_spawned: false,
    auth_status: "ok",
    last_error: null,
    last_start_error: null,
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
    reports_generated: 0,
    email_mode: "daily_digest",
    project_name: null,
    status: "idle",
    analysis_started: false,
    ...overrides,
  };
}

function renderDashboard(
  syncStatus: SyncStatusResponse,
  projectSummaries: ProjectSummary[] = [makeProject({})],
  analysisStatus: AnalysisStatusResponse = makeAnalysisStatus(),
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoot = root;
  const refreshSpy = vi.fn();
  const projects = projectSummaries.map((project) => createProjectViewModel(project));

  vi.spyOn(api, "getSyncStatus").mockResolvedValue(syncStatus);
  vi.spyOn(api, "getAnalysisStatus").mockResolvedValue(analysisStatus);

  act(() => {
    root.render(
      <MemoryRouter initialEntries={["/"]}>
        <AppDataContext.Provider
          value={{
            projects,
            projectsLoading: false,
            projectsError: null,
            projectWarnings: [],
            health,
            healthLoading: false,
            healthError: null,
            refresh: refreshSpy,
            removeProjectByName: () => undefined,
          }}
        >
          <DashboardPage />
        </AppDataContext.Provider>
      </MemoryRouter>,
    );
  });

  return { container, refreshSpy };
}

async function flushDashboardEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function getSyncButton(container: HTMLElement): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find((candidate) => candidate.textContent?.trim() === "Synk OneDrive");
  if (!button) {
    throw new Error("Finner ikke Synk OneDrive-knappen.");
  }
  return button as HTMLButtonElement;
}

afterEach(() => {
  vi.restoreAllMocks();
  act(() => {
    mountedRoot?.unmount();
  });
  mountedRoot = null;
  document.body.innerHTML = "";
});

describe("DashboardPage", () => {
  it("accepts status only from the current sync job once a job id is known", () => {
    expect(isSyncStatusForCurrentJob(makeSyncStatus({ job_id: "sync-job" }), "sync-job")).toBe(true);
    expect(isSyncStatusForCurrentJob(makeSyncStatus({ job_id: "old-sync-job" }), "sync-job")).toBe(false);
    expect(isSyncStatusForCurrentJob(makeSyncStatus({ job_id: null }), "sync-job")).toBe(false);
    expect(isSyncStatusForCurrentJob(makeSyncStatus({ job_id: "old-sync-job" }), null)).toBe(true);
  });

  it("prefers the completed sync timestamp over health for the top sync display", () => {
    const syncStatus: SyncStatusResponse = {
      running: false,
      process_alive: false,
      lock_exists: false,
      lock_stale: false,
      activity: "idle",
      job_id: "sync-job",
      last_started_at: "2026-06-09T08:45:00+02:00",
      last_completed_at: "2026-06-09T08:49:00+02:00",
      last_error: null,
      projects_synced: 2,
      files_changed: 4,
      reports_found: 1,
      status: "completed",
    };

    expect(resolveDashboardLastSyncedAt(syncStatus, health)).toBe("2026-06-09T08:49:00+02:00");
    expect(formatDateTime(resolveDashboardLastSyncedAt(syncStatus, health))).toBe(formatDateTime("2026-06-09T08:49:00+02:00"));
  });

  it.each([
    "Awaiting history lock",
    "Waiting for history lock",
    "onedrive_sync_history.lock",
    "onedrive_lightweight_state.sqlite3",
  ])("detects %s as a lock/busy sync error", (fragment) => {
    expect(isSyncBusyLockError(`Sync failed: ${fragment}`)).toBe(true);
    expect(getSyncLastErrorMessage(`Sync failed: ${fragment}`)).toBe(SYNC_STALE_LOCK_WARNING);
  });

  it("shows dashboard metrics and direct latest report actions without internal paths", () => {
    const projectWithReport = createProjectViewModel(makeProject({}));
    const projectWithoutReport = createProjectViewModel(
      makeProject({
        project_name: "No Comment",
        display_name: "No Comment",
        relative_project_path: "AnbudAppliance/Urban_Reuse_Norway/No Comment",
        latest_comment_document: null,
        latest_comment_document_open_url: null,
        latest_comment_created_at: null,
        latest_comment_modified_at: null,
        comment_document_count: 0,
        report_count: 0,
        status: "pending",
      }),
    );

    const markup = renderToStaticMarkup(
      <StaticRouter location="/">
        <AppDataContext.Provider
          value={{
            projects: [projectWithReport, projectWithoutReport],
            projectsLoading: false,
            projectsError: null,
            projectWarnings: [],
            health,
            healthLoading: false,
            healthError: null,
            refresh: () => undefined,
            removeProjectByName: () => undefined,
          }}
        >
          <DashboardPage />
        </AppDataContext.Provider>
      </StaticRouter>,
    );

    expect(markup).toContain("Prosjekter totalt");
    expect(markup).toContain("Uten rapport");
    expect(markup).toContain("Synk OneDrive");
    expect(markup).toContain("Kontrollsenter");
    expect(markup).not.toContain("page-header__eyebrow");
    expect(markup).not.toContain("URN Nexus");
    expect(markup).toContain(APPLIANCE_CLEAR_MESSAGE);
    expect(markup).toContain(formatDateTime(health.last_synced_at));
    expect(markup).not.toContain("Generer rapport");
    expect(markup).toContain("Seneste rapporter");
    expect(markup).not.toContain("AnbudAppliance/Urban_Reuse_Norway");
    expect(markup).not.toContain("/home/anbudklient");
    expect(markup).toContain("Åpne rapport");
    expect(markup).toContain("Åpne kommentardokument");
    expect(markup).toContain("Åpne prosjekt");
    expect(markup).toContain('href="/api/projects/Bryn%20Skole/reports/latest/open"');
    expect((markup.match(/Åpne kommentardokument/g) ?? []).length).toBe(1);
  });

  it("shows a warning instead of locking the sync button when the last error is a stale lock", async () => {
    const { container } = renderDashboard(
      makeSyncStatus({
        status: "failed",
        last_error:
          "Awaiting history lock while waiting for onedrive_sync_history.lock and onedrive_lightweight_state.sqlite3 to clear.",
      }),
    );

    await flushDashboardEffects();

    const syncButton = getSyncButton(container);
    expect(syncButton.disabled).toBe(false);
    expect(container.textContent).toContain(APPLIANCE_CLEAR_MESSAGE);
    expect(container.textContent).not.toContain(SYNC_LOCK_HELP_TEXT);
    expect(container.textContent).toContain(SYNC_STALE_LOCK_WARNING);
    expect(container.textContent).not.toContain("Awaiting history lock");
    expect(container.textContent).not.toContain("Waiting for history lock");
    expect(container.textContent).not.toContain("onedrive_sync_history.lock");
    expect(container.textContent).not.toContain("onedrive_lightweight_state.sqlite3");
  });

  it("shows OneDrive synkroniserer and disables the button when sync is running", async () => {
    const { container } = renderDashboard(
      makeSyncStatus({
        running: true,
        status: "running",
        last_completed_at: null,
        activity: "sync",
      }),
    );

    await flushDashboardEffects();

    const syncButton = getSyncButton(container);
    expect(syncButton.disabled).toBe(true);
    expect(container.textContent).toContain(SYNC_RUNNING_LABEL);
    expect(container.textContent).toContain(SYNC_LOCK_HELP_TEXT);
    expect(container.textContent).not.toContain("Appliance arbeider");
  });

  it("disables the sync button when analysis is running even if sync looks idle", async () => {
    const { container } = renderDashboard(
      makeSyncStatus({
        status: "completed",
        last_error: null,
      }),
      [makeProject({})],
      makeAnalysisStatus({
        running: true,
        status: "running",
        last_completed_at: null,
        activity: "analysis",
      }),
    );

    await flushDashboardEffects();

    const syncButton = getSyncButton(container);
    expect(syncButton.disabled).toBe(true);
    expect(container.textContent).toContain(SYNC_LOCK_HELP_TEXT);
    expect(container.textContent).toContain(ANALYSIS_RUNNING_LABEL);
    expect(container.textContent).not.toContain("Awaiting history lock");
    expect(container.textContent).not.toContain("onedrive_sync_history.lock");
  });

  it("disables the sync button while analysis is still starting", async () => {
    const { container } = renderDashboard(
      makeSyncStatus({
        status: "completed",
        last_error: null,
      }),
      [makeProject({})],
      makeAnalysisStatus({
        running: false,
        process_alive: false,
        lock_exists: false,
        status: "startup_pending",
        activity: "analysis",
        startup_grace_active: true,
        process_spawned: true,
      }),
    );

    await flushDashboardEffects();

    const syncButton = getSyncButton(container);
    expect(syncButton.disabled).toBe(true);
    expect(container.textContent).toContain(SYNC_LOCK_HELP_TEXT);
    expect(container.textContent).toContain(ANALYSIS_RUNNING_LABEL);
  });

  it("re-enables the sync button after a busy response once the live poll says Appliance is idle", async () => {
    vi.spyOn(api, "runSync").mockRejectedValue(new api.ApiRequestError(503, APPLIANCE_BUSY_MESSAGE));

    const { container } = renderDashboard(
      makeSyncStatus({
        status: "completed",
        last_error: null,
      }),
    );

    await flushDashboardEffects();

    const syncButton = getSyncButton(container);
    expect(syncButton.disabled).toBe(false);

    await act(async () => {
      syncButton.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(syncButton.disabled).toBe(false);
    expect(container.textContent).not.toContain("Awaiting history lock");
    expect(container.textContent).not.toContain("onedrive_sync_history.lock");
    expect(container.textContent).not.toContain(SYNC_LOCK_HELP_TEXT);
  });

  it("keeps the sync button enabled when the last error is not a lock/busy signal", async () => {
    const { container } = renderDashboard(
      makeSyncStatus({
        status: "failed",
        error_code: "sync_failed",
        last_error: "OneDrive sync failed.",
      }),
    );

    await flushDashboardEffects();

    const syncButton = getSyncButton(container);
    expect(syncButton.disabled).toBe(false);
    expect(container.textContent).toContain("Synkroniseringen kunne ikke fullføres.");
    expect(container.textContent).not.toContain("Synk er midlertidig deaktivert fordi Appliance er opptatt med analyse eller OneDrive-state.");
  });
});
