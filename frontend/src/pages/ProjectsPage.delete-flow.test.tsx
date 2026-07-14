// @vitest-environment jsdom
import { useMemo, useState } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppDataContext } from "../context/AppDataContext";
import * as api from "../lib/api";
import { createProjectViewModel } from "../lib/projects";
import type { HealthResponse, ProjectSummary } from "../types";
import { ProjectsPage } from "./ProjectsPage";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeProject(projectName: string): ProjectSummary {
  return {
    project_name: projectName,
    display_name: projectName,
    source_label: "OneDrive",
    relative_project_path: `AnbudAppliance/Urban_Reuse_Norway/${projectName}`,
    hidden_internal_path: `/home/anbudklient/appliance/.riveanbud_runtime/rive-anbud-appliance/Urban_Reuse_Norway/${projectName}`,
    last_synced_at: "2026-06-04T08:00:00+02:00",
    latest_comment_document: null,
    latest_comment_document_open_url: null,
    latest_comment_created_at: null,
    latest_comment_modified_at: null,
    comment_document_count: 0,
    is_sample_project: false,
    project_path: `/home/anbudklient/appliance/.riveanbud_runtime/rive-anbud-appliance/Urban_Reuse_Norway/${projectName}`,
    last_analyzed_at: null,
    status: "pending",
    file_count: 0,
    report_count: 0,
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
  discovered_projects: 2,
  last_synced_at: "2026-06-04T08:00:00+02:00",
  last_analyzed_at: null,
  latest_report_generated_at: null,
  project_count: 2,
  file_count: 0,
  report_count: 0,
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

afterEach(() => {
  vi.restoreAllMocks();
  if (mountedRoot) {
    act(() => {
      mountedRoot?.unmount();
    });
    mountedRoot = null;
  }
  document.body.innerHTML = "";
});

function projectWarningsFromProjects(projects: ReturnType<typeof createProjectViewModel>[]): string[] {
  return Array.from(new Set(projects.flatMap((project) => project.issues.map((issue) => issue.message)).filter((message) => message.trim().length > 0)));
}

function renderProjectsPage(initialProjects: ProjectSummary[]) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoot = root;
  const refreshSpy = vi.fn();

  function Harness() {
    const [projects, setProjects] = useState(initialProjects.map(createProjectViewModel));
    const value = useMemo(
      () => ({
        projects,
        projectsLoading: false,
        projectsError: null,
        projectWarnings: projectWarningsFromProjects(projects),
        health,
        healthLoading: false,
        healthError: null,
        refresh: refreshSpy,
        removeProjectByName: (projectName: string) =>
          setProjects((current) => current.filter((project) => project.projectName !== projectName)),
      }),
      [projects],
    );

    return (
      <AppDataContext.Provider value={value}>
        <ProjectsPage />
      </AppDataContext.Provider>
    );
  }

  act(() => {
    root.render(
      <MemoryRouter initialEntries={["/projects"]}>
        <Harness />
      </MemoryRouter>,
    );
  });

  return { container, refreshSpy };
}

function clickButton(container: HTMLElement, label: string, withinSelector?: string): HTMLButtonElement {
  const scope = withinSelector ? container.querySelector(withinSelector) : container;
  if (!scope) {
    throw new Error(`Missing scope for ${label}`);
  }
  const buttons = Array.from(scope.querySelectorAll("button"));
  const button = buttons.find((candidate) => candidate.textContent?.trim() === label);
  if (!button) {
    throw new Error(`Could not find button "${label}"`);
  }
  return button as HTMLButtonElement;
}

describe("ProjectsPage delete flow", () => {
  it("removes a deleted project immediately and shows a success toast", async () => {
    const deleteMock = vi.spyOn(api, "deleteProject").mockResolvedValue({
      project_name: "Bryn Skole",
      deleted_remote_path: "AnbudAppliance/Urban_Reuse_Norway/Bryn Skole",
      deleted: true,
      existed: true,
      synced: true,
      message: "Prosjektet ble slettet fra OneDrive.",
    });

    const { container, refreshSpy } = renderProjectsPage([makeProject("Bryn Skole")]);

    await act(async () => {
      clickButton(container, "Slett prosjekt").click();
      await Promise.resolve();
    });
    await act(async () => {
      clickButton(container, "Slett prosjekt", '[aria-labelledby="delete-project-title"]').click();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Prosjektet ble slettet fra OneDrive.");
    expect(container.textContent).toContain("Ingen prosjekter å vise.");
    expect(container.textContent).not.toContain("Bryn Skole");
    expect(container.textContent).not.toContain("Kunne ikke slette prosjektet i OneDrive.");
    expect(deleteMock).toHaveBeenCalledTimes(1);
    expect(refreshSpy).toHaveBeenCalledTimes(1);
  });

  it("treats itemNotFound delete responses as success and clears any previous error banner", async () => {
    const deleteMock = vi.spyOn(api, "deleteProject");
    deleteMock
      .mockRejectedValueOnce(new Error("Microsoft Graph-write feilet: permission denied"))
      .mockRejectedValueOnce(new api.ApiRequestError(404, "Configured OneDrive folder not found: AnbudAppliance/Urban_Reuse_Norway/Bryn Skole"));

    const { container, refreshSpy } = renderProjectsPage([makeProject("Bryn Skole")]);

    await act(async () => {
      clickButton(container, "Slett prosjekt").click();
      await Promise.resolve();
    });
    await act(async () => {
      clickButton(container, "Slett prosjekt", '[aria-labelledby="delete-project-title"]').click();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Kunne ikke slette prosjektet i OneDrive.");
    expect(container.textContent).not.toContain("Prosjektet finnes ikke lenger i OneDrive.");

    await act(async () => {
      clickButton(container, "Slett prosjekt", '[aria-labelledby="delete-project-title"]').click();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Prosjektet finnes ikke lenger i OneDrive.");
    expect(container.textContent).not.toContain("Microsoft Graph-write feilet: permission denied");
    expect(container.textContent).not.toContain("Bryn Skole");
    expect(refreshSpy).toHaveBeenCalledTimes(1);
    expect(deleteMock).toHaveBeenCalledTimes(2);
  });
});
