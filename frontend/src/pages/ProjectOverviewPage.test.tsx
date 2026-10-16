import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { createProjectViewModel } from "../lib/projects";
import type { ProjectPageContext } from "./ProjectPage";
import { ProjectOverviewPage } from "./ProjectOverviewPage";
import type { ProjectDetailResponse, ProjectSummary } from "../types";

const mocks = vi.hoisted(() => ({
  projectContext: undefined as ProjectPageContext | undefined,
}));

vi.mock("./ProjectPage", async () => {
  const actual = await vi.importActual<typeof import("./ProjectPage")>("./ProjectPage");
  return {
    ...actual,
    useProjectPageContext: () => mocks.projectContext,
  };
});

const projectSummary: ProjectSummary = {
  project_name: "Bryn Skole",
  display_name: "Bryn Skole",
  source_label: "OneDrive",
  relative_project_path: "Urban_Reuse_Norway/Bryn Skole",
  hidden_internal_path: "/home/anbudklient/appliance/runtime/Bryn Skole",
  last_synced_at: "2026-06-08T08:00:00+02:00",
  latest_comment_document: "Bryn Skole - Kommentardokument - 6.0.docx",
  latest_comment_document_open_url: "/api/projects/Bryn%20Skole/reports/latest/open",
  latest_comment_created_at: "2026-06-08T08:15:00+02:00",
  latest_comment_modified_at: "2026-06-08T08:15:00+02:00",
  comment_document_count: 6,
  is_sample_project: false,
  project_path: "/home/anbudklient/appliance/runtime/Bryn Skole",
  last_analyzed_at: "2026-06-08T08:15:00+02:00",
  status: "completed",
  file_count: 12,
  report_count: 6,
  warnings: [],
  errors: [],
};

mocks.projectContext = {
  project: createProjectViewModel(projectSummary),
  projectDetail: {
    ...projectSummary,
    analysis: {
      status: "completed",
      last_analyzed_at: "2026-06-08T08:15:00+02:00",
      provider: null,
      model: null,
      documents_seen: 42,
      chunks_created: 0,
      report_items_count: 0,
      output_docx_path: null,
      run_summary_path: null,
      warnings_count: 0,
      errors_count: 0,
    },
    reports: [],
  } satisfies ProjectDetailResponse,
  reloadProject: vi.fn(),
};

describe("ProjectOverviewPage", () => {
  it("keeps the useful cards and removes status and analysis basis metadata", () => {
    const markup = renderToStaticMarkup(<MemoryRouter><ProjectOverviewPage /></MemoryRouter>);

    expect(markup).toContain("Prosjektdetaljer");
    expect(markup).toContain("Prosjekt");
    expect(markup).toContain("Kilde");
    expect(markup).toContain("Sti");
    expect(markup).toContain("Siste rapport opprettet");
    expect(markup).not.toContain("Status");
    expect(markup).not.toContain("Analysegrunnlag");
    expect((markup.match(/detail-card/g) ?? []).length).toBe(9);
  });
});
