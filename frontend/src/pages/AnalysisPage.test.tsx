// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisPage } from "./AnalysisPage";
import { createProjectViewModel } from "../lib/projects";
import type { ProjectSummary } from "../types";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const data = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("../context/AppDataContext", () => ({ useAppData: () => data.value }));
let root: Root | null = null;
afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  root = null;
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});
function Location() {
  const location = useLocation();
  return <output>{location.pathname}</output>;
}
async function mount(error: string | null = null) {
  const project = {
    project_name: "Bryn Skole",
    display_name: "Bryn Skole",
    source_label: "OneDrive",
    relative_project_path: "Firma/Bryn Skole",
    hidden_internal_path: "/private/project",
    project_path: "/private/project",
    last_synced_at: null,
    last_analyzed_at: null,
    latest_comment_document: null,
    latest_comment_document_open_url: null,
    latest_comment_created_at: null,
    latest_comment_modified_at: null,
    comment_document_count: 0,
    is_sample_project: false,
    status: "unknown",
    file_count: 4,
    report_count: 0,
    warnings: [],
    errors: [],
  } satisfies ProjectSummary;
  const refresh = vi.fn();
  data.value = {
    projects: [createProjectViewModel(project)],
    projectsLoading: false,
    projectsError: error,
    refresh,
    health: { graph_write_status: "not_configured" },
  };
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root!.render(
      <MemoryRouter>
        <AnalysisPage />
        <Location />
      </MemoryRouter>,
    ),
  );
  return { host, refresh };
}
describe("AnalysisPage project memory workflow", () => {
  it("opens saved project review without starting analysis or requiring Graph-write", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const { host } = await mount();
    expect(host.textContent).toContain("Velg prosjekt");
    expect(host.textContent).not.toContain("Analyser alle prosjekter");
    const button = Array.from(host.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === "Analyser",
    )!;
    expect(button.disabled).toBe(false);
    await act(async () => button.click());
    expect(host.querySelector("output")?.textContent).toBe(
      "/projects/Bryn%20Skole/review",
    );
    expect(fetch).not.toHaveBeenCalled();
  });
  it("reports a project-loading error and offers retry", async () => {
    const { host, refresh } = await mount("Lokal tilkobling mangler");
    expect(host.textContent).toContain("Lokal tilkobling mangler");
    const button = Array.from(host.querySelectorAll("button")).find(
      (b) => b.textContent === "Prøv igjen",
    )!;
    await act(async () => button.click());
    expect(refresh).toHaveBeenCalledOnce();
  });
});
