import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { createProjectViewModel } from "../lib/projects";
import type { ProjectPageContext } from "./ProjectPage";
import { ProjectReportsPage } from "./ProjectReportsPage";
import type { ProjectDetailResponse, ProjectReport, ProjectSummary } from "../types";

const mocks = vi.hoisted(() => ({
  reloadReports: vi.fn(),
  projectContext: undefined as ProjectPageContext | undefined,
  reportsResponse: undefined as { reports: ProjectReport[] } | undefined,
}));

vi.mock("../lib/useResource", () => ({
  useResource: () => ({
    data: mocks.reportsResponse,
    loading: false,
    error: null,
    reload: mocks.reloadReports,
  }),
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

const project = createProjectViewModel(projectSummary);

const reportRows: ProjectReport[] = [
  {
    report_id: "0",
    report_name: "Bryn Skole - Kommentardokument - 6.0.docx",
    report_path: "/home/anbudklient/appliance/runtime/Bryn Skole/Kommentarer/Bryn Skole - Kommentardokument - 6.0.docx",
    report_type: "docx",
    version: "6.0",
    created_at: "2026-06-08T08:15:00+02:00",
    generated_at: "2026-06-08T08:15:00+02:00",
    modified_at: "2026-06-08T08:16:00+02:00",
    size_bytes: 12345,
    is_latest: true,
    open_url: "/api/projects/Bryn%20Skole/reports/0/open",
    download_url: "/api/projects/Bryn%20Skole/reports/0/download",
  },
];

mocks.projectContext = {
  project,
  projectDetail: {
    ...projectSummary,
    analysis: null,
    reports: [],
  } satisfies ProjectDetailResponse,
  reloadProject: mocks.reloadReports,
};

mocks.reportsResponse = {
  reports: reportRows,
};

describe("ProjectReportsPage", () => {
  it("shows only the project and latest report metadata cards above the report table", () => {
    const markup = renderToStaticMarkup(<MemoryRouter><ProjectReportsPage /></MemoryRouter>);

    expect(markup).toContain("Andre rapportfiler og eldre rapporter");
    expect(markup).toContain("Prosjekt");
    expect(markup).toContain("Siste rapport opprettet");
    expect(markup).not.toContain("Sti");
    expect(markup).not.toContain("Status");
    expect((markup.match(/detail-card/g) ?? []).length).toBe(2);
  });
});
