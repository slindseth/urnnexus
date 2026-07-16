// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { StaticRouter } from "react-router-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppDataContext } from "../context/AppDataContext";
import * as api from "../lib/api";
import { createProjectViewModel } from "../lib/projects";
import type { AnalysisRunResponse, AnalysisStatusResponse, HealthResponse, ProjectSummary, SyncStatusResponse } from "../types";
import { AnalysisPage, AnalysisRunDialog } from "./AnalysisPage";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let mountedRoot: Root | null = null;

function makeProject(projectName: string): ProjectSummary {
  return {
    project_name: projectName,
    display_name: projectName,
    source_label: "OneDrive",
    relative_project_path: `AnbudAppliance/Urban_Reuse_Norway/${projectName}`,
    hidden_internal_path: `/home/anbudklient/appliance/.riveanbud_runtime/rive-anbud-appliance/Urban_Reuse_Norway/${projectName}`,
    last_synced_at: "2026-06-04T08:00:00+02:00",
    latest_comment_document: "Bryn Skole - Kommentardokument.docx",
    latest_comment_document_open_url: "/api/projects/Bryn%20Skole/reports/latest/open",
    latest_comment_created_at: "2026-06-04T08:15:00+02:00",
    latest_comment_modified_at: "2026-06-04T08:15:00+02:00",
    comment_document_count: 1,
    is_sample_project: false,
    project_path: `/home/anbudklient/appliance/.riveanbud_runtime/rive-anbud-appliance/Urban_Reuse_Norway/${projectName}`,
    last_analyzed_at: "2026-06-04T08:15:00+02:00",
    status: "completed_with_warnings",
    file_count: 12,
    report_count: 1,
    warnings: [],
    errors: [],
  };
}

const health: HealthResponse = {
  appliance_available: true,
  uptime_seconds: 120,
  uptime: "0:02:00",
  version: "0.1.9",
  appliance_root: "/home/anbudklient/appliance",
  discovered_projects: 1,
  last_synced_at: "2026-06-04T08:00:00+02:00",
  last_analyzed_at: "2026-06-04T08:15:00+02:00",
  latest_report_generated_at: "2026-06-04T08:15:00+02:00",
  project_count: 1,
  file_count: 12,
  report_count: 1,
  one_drive_status: "available",
  one_drive_detail: "1 prosjekt funnet i lokal OneDrive-cache.",
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

function getLocalDayKey(date = new Date()): string {
  const year = String(date.getFullYear());
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function makeIdleAnalysisStatus(overrides: Partial<AnalysisStatusResponse> = {}): AnalysisStatusResponse {
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
    ...overrides,
  };
}

function makeRunningAnalysisStatus(overrides: Partial<AnalysisStatusResponse> = {}): AnalysisStatusResponse {
  return makeIdleAnalysisStatus({
    running: true,
    process_alive: true,
    lock_exists: true,
    activity: "analysis",
    job_id: "analysis-job",
    start_requested_at: "2026-06-12T12:00:00+02:00",
    last_started_at: "2026-06-12T12:00:00+02:00",
    startup_grace_active: false,
    process_spawned: true,
    auth_status: "ok",
    status: "running",
    analysis_started: true,
    ...overrides,
  });
}

function makeAuthFailedAnalysisStatus(overrides: Partial<AnalysisStatusResponse> = {}): AnalysisStatusResponse {
  return makeIdleAnalysisStatus({
    running: false,
    process_alive: false,
    lock_exists: false,
    activity: "analysis",
    job_id: "analysis-job",
    start_requested_at: "2026-06-12T12:00:00+02:00",
    last_started_at: "2026-06-12T12:00:00+02:00",
    startup_grace_active: false,
    process_spawned: false,
    auth_status: "auth_failed",
    last_error: "Microsoft Graph returned invalid_grant while requesting an access token.",
    last_start_error: null,
    status: "auth_failed",
    analysis_started: false,
    ...overrides,
  });
}

function makeStartupPendingAnalysisStatus(overrides: Partial<AnalysisStatusResponse> = {}): AnalysisStatusResponse {
  return makeIdleAnalysisStatus({
    running: false,
    process_alive: false,
    lock_exists: false,
    activity: "analysis",
    job_id: "analysis-job",
    start_requested_at: "2026-06-12T12:00:00+02:00",
    last_started_at: "2026-06-12T12:00:00+02:00",
    startup_grace_active: true,
    process_spawned: true,
    auth_status: "unknown",
    status: "startup_pending",
    analysis_started: false,
    ...overrides,
  });
}

function makeAnalysisRunResponse(overrides: Partial<AnalysisRunResponse> = {}): AnalysisRunResponse {
  return {
    job_id: "analysis-job",
    running: true,
    started_at: "2026-06-12T12:00:00+02:00",
    status: "started",
    analysis_started: true,
    reports_generated: 0,
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
    email_mode: "daily_digest",
    project_name: null,
    ...overrides,
  };
}

function makeIdleSyncStatus(overrides: Partial<SyncStatusResponse> = {}): SyncStatusResponse {
  return {
    running: false,
    process_alive: false,
    lock_exists: false,
    lock_stale: false,
    activity: "idle",
    job_id: "sync-job",
    last_started_at: null,
    last_completed_at: null,
    last_error: null,
    projects_synced: 0,
    files_changed: 0,
    reports_found: 0,
    status: "idle",
    job_type: "sync",
    run_mode: "sync_only",
    ...overrides,
  };
}

function renderAnalysisPage(
  analysisStatuses: AnalysisStatusResponse[] = [makeIdleAnalysisStatus()],
  runResponse: AnalysisRunResponse = makeAnalysisRunResponse(),
  syncStatus: SyncStatusResponse = makeIdleSyncStatus(),
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoot = root;

  const getAnalysisStatusSpy = vi.spyOn(api, "getAnalysisStatus");
  for (const status of analysisStatuses) {
    getAnalysisStatusSpy.mockResolvedValueOnce(status);
  }
  getAnalysisStatusSpy.mockResolvedValue(analysisStatuses[analysisStatuses.length - 1] ?? makeIdleAnalysisStatus());
  const getSyncStatusSpy = vi.spyOn(api, "getSyncStatus").mockResolvedValue(syncStatus);

  const runAnalysisSpy = vi.spyOn(api, "runAnalysis").mockResolvedValue(runResponse);
  const refreshSpy = vi.fn();

  act(() => {
    root.render(
      <MemoryRouter initialEntries={["/analysis"]}>
        <AppDataContext.Provider
          value={{
            projects: [createProjectViewModel(makeProject("Bryn Skole"))],
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
          <AnalysisPage />
        </AppDataContext.Provider>
      </MemoryRouter>,
    );
  });

  return { container, refreshSpy, runAnalysisSpy, getAnalysisStatusSpy, getSyncStatusSpy };
}

function clickButton(container: HTMLElement, label: string) {
  const button = Array.from(container.querySelectorAll("button")).find((candidate) => candidate.textContent?.trim() === label);
  if (!button) {
    throw new Error(`Finner ikke knappen: ${label}`);
  }
  act(() => {
    (button as HTMLButtonElement).click();
  });
}

async function flushMicrotasks(times = 2) {
  await act(async () => {
    for (let index = 0; index < times; index += 1) {
      await Promise.resolve();
    }
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  act(() => {
    mountedRoot?.unmount();
  });
  mountedRoot = null;
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("AnalysisPage", () => {
  it("renders analysis controls and per-project analysis buttons without local cache actions", () => {
    const markup = renderToStaticMarkup(
      <StaticRouter location="/analysis">
        <AppDataContext.Provider
          value={{
            projects: [createProjectViewModel(makeProject("Bryn Skole"))],
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
          <AnalysisPage />
        </AppDataContext.Provider>
      </StaticRouter>,
    );

    expect(markup).toContain("Analyse");
    expect(markup).toContain("Analyser alle prosjekter");
    expect(markup).toContain("Analyser");
    expect(markup).not.toContain("Fjern fra Nexus");
    expect(markup).not.toContain("OpenAI-status");
  });

  it("renders the analysis dialog with the expected email mode options", () => {
    const markup = renderToStaticMarkup(
      <StaticRouter location="/analysis">
        <AnalysisRunDialog
          project={createProjectViewModel(makeProject("Bryn Skole"))}
          selectedEmailMode="daily_digest"
          isSubmitting={false}
          onEmailModeChange={() => undefined}
          onCancel={() => undefined}
          onConfirm={() => undefined}
        />
      </StaticRouter>,
    );

    expect(markup).toContain("Analyser Bryn Skole");
    expect(markup).toContain("Legg resultat i daglig digest");
    expect(markup).toContain("Send e-post når rapportene er ferdige");
    expect(markup).toContain("Start analyse");
  });

  it("disables analysis while a sync job is active", async () => {
    const { container, runAnalysisSpy } = renderAnalysisPage(
      [makeIdleAnalysisStatus()],
      makeAnalysisRunResponse(),
      makeIdleSyncStatus({
        running: true,
        process_alive: true,
        lock_exists: true,
        activity: "sync",
        status: "running",
        current_phase: "Henter endringer",
        run_mode: "sync_only",
      }),
    );

    await flushMicrotasks(3);

    const analyzeAllButton = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Analyser alle prosjekter");
    expect(analyzeAllButton).toBeDefined();
    expect((analyzeAllButton as HTMLButtonElement).disabled).toBe(true);
    expect(container.textContent).toContain("Synkronisering pågår");
    expect(container.textContent).toContain("Analyse kan startes når synkronisering er ferdig");
    expect(runAnalysisSpy).not.toHaveBeenCalled();
  });

  it("keeps the startup state visible when the first status poll returns a stale idle response", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T12:00:00+02:00"));

    const { container } = renderAnalysisPage([
      makeIdleAnalysisStatus({
        job_id: "old-job",
        last_started_at: "2026-06-12T11:45:00+02:00",
        last_error: "Graph auth feilet fra en tidligere kjøring.",
        status: "failed",
      }),
      makeRunningAnalysisStatus(),
    ]);

    clickButton(container, "Analyser alle prosjekter");
    expect(container.textContent).toContain("Analyser alle prosjekter");
    clickButton(container, "Start analyse");

    expect(container.textContent).toContain("Starter analyse");
    expect(container.textContent).toContain("Kobler til OneDrive og klargjør prosjektliste for alle prosjekter");
    expect(container.textContent).not.toContain("Graph auth feilet fra en tidligere kjøring.");
    expect(container.textContent).not.toContain("Analyse feilet");

    await act(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Analyse pågår");
    expect(container.textContent).not.toContain("Starter analyse");
    expect(container.textContent).not.toContain("Graph auth feilet fra en tidligere kjøring.");
  });

  it("shows a Graph auth failure when the backend reports auth_failed for the current run", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T12:00:00+02:00"));

    const { container } = renderAnalysisPage([makeAuthFailedAnalysisStatus()]);

    clickButton(container, "Analyser alle prosjekter");
    await flushMicrotasks();
    clickButton(container, "Start analyse");
    await flushMicrotasks(3);

    expect(container.textContent).toContain("Graph auth feilet");
    expect(container.textContent).toContain("Microsoft Graph-autentiseringen feilet");
    expect(container.textContent).not.toContain("Starter analyse");
  });

  it("keeps the startup warning visible after the grace period when the backend still reports startup_pending", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-12T12:00:00+02:00"));

    const { container } = renderAnalysisPage([makeStartupPendingAnalysisStatus()]);

    clickButton(container, "Analyser alle prosjekter");
    await flushMicrotasks();
    clickButton(container, "Start analyse");
    await flushMicrotasks(3);

    expect(container.textContent).toContain("Starter analyse");
    expect(container.textContent).not.toContain("Analyse tar lenger tid enn forventet");

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Analyse tar lenger tid enn forventet");
    expect(container.textContent).toContain("Vi venter fortsatt på første status fra appliance.");
    expect(container.textContent).not.toContain("Graph auth feilet");
  });
});
