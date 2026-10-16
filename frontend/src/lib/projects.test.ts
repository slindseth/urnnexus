import { describe, expect, it } from "vitest";
import { createProjectViewModel, displayProjectPath, filterVisibleProjects } from "./projects";
import type { ProjectSummary } from "../types";

function makeProject(project_name: string, is_sample_project: boolean): ProjectSummary {
  return {
    project_name,
    display_name: project_name,
    source_label: "OneDrive",
    relative_project_path: is_sample_project ? `sample_projects/${project_name}` : `Urban_Reuse_Norway/${project_name}`,
    hidden_internal_path: is_sample_project ? `/home/anbudklient/appliance/sample_projects/${project_name}` : `/home/anbudklient/appliance/runtime/${project_name}`,
    last_synced_at: "2026-06-04T08:00:00+02:00",
    latest_comment_document: `${project_name} - Kommentardokument.docx`,
    latest_comment_document_open_url: `/api/projects/${encodeURIComponent(project_name)}/reports/latest/open`,
    latest_comment_created_at: "2026-06-04T08:15:00+02:00",
    latest_comment_modified_at: "2026-06-04T08:15:00+02:00",
    comment_document_count: 1,
    is_sample_project,
    project_path: `/home/anbudklient/appliance/${project_name}`,
    last_analyzed_at: "2026-06-04T08:15:00+02:00",
    status: "completed",
    file_count: 12,
    report_count: 1,
    warnings: [],
    errors: [],
  };
}

describe("project visibility helpers", () => {
  it("filters sample projects out of the standard view", () => {
    const visible = filterVisibleProjects([makeProject("Bryn Skole", false), makeProject("Testprosjekt", true)]);

    expect(visible).toHaveLength(1);
    expect(visible[0].project_name).toBe("Bryn Skole");
  });

  it("filters local-only cache projects out of the standard view", () => {
    const localOnlyProject = {
      ...makeProject("Dette er bare en test", false),
      source_label: "Kun lokal cache",
      is_local_cache_only: true,
    };
    const visible = filterVisibleProjects([makeProject("Bryn Skole", false), localOnlyProject]);

    expect(visible).toHaveLength(1);
    expect(visible[0].project_name).toBe("Bryn Skole");
  });

  it("can keep sample projects in dev mode", () => {
    const visible = filterVisibleProjects([makeProject("Bryn Skole", false), makeProject("Testprosjekt", true)], true);

    expect(visible).toHaveLength(2);
  });

  it("removes the appliance folder prefix from display paths", () => {
    expect(displayProjectPath("AnbudAppliance/Urban_Reuse_Norway/Bryn Skole")).toBe("Urban_Reuse_Norway/Bryn Skole");
    expect(displayProjectPath("sample_projects/Testprosjekt")).toBe("sample_projects/Testprosjekt");
  });

  it("labels sample projects as demo/local samples instead of OneDrive", () => {
    expect(createProjectViewModel(makeProject("Testprosjekt", true)).sourceLabel).toBe("Demo/lokal sample");
  });

  it.each([
    ["partial", "Delvis gjennomgått"],
    ["stale", "Utdatert snapshot"],
    ["cancelled", "Stoppet"],
  ])("keeps appliance status %s visible even when a report exists", (status, label) => {
    const project = { ...makeProject("Prosjektminne", false), status };
    expect(createProjectViewModel(project).status.label).toBe(label);
  });

  it("maps raw API status and report counts into one shared status model", () => {
    expect(createProjectViewModel(makeProject("Ferdig", false)).status.level).toBe("SUCCESS");
    expect(createProjectViewModel({ ...makeProject("Varsel", false), status: "completed_with_warnings" }).status.level).toBe("SUCCESS_WITH_WARNINGS");
    expect(createProjectViewModel({ ...makeProject("Kjører", false), status: "running" }).status.level).toBe("RUNNING");
    expect(createProjectViewModel({ ...makeProject("Venter", false), status: "pending", report_count: 0, comment_document_count: 0 }).status.level).toBe("PENDING");
    expect(createProjectViewModel({ ...makeProject("Ingen rapport", false), status: "unknown", report_count: 0, comment_document_count: 0 }).status.level).toBe("NO_REPORT");
    expect(createProjectViewModel({ ...makeProject("Feil", false), status: "failed" }).status.level).toBe("FAILED");
  });

  it("translates technical warnings but keeps details available", () => {
    const viewModel = createProjectViewModel({
      ...makeProject("Bryn Skole", false),
      file_count: 0,
      report_count: 0,
      comment_document_count: 0,
      latest_comment_document: null,
      latest_comment_document_open_url: null,
      latest_comment_created_at: null,
      latest_comment_modified_at: null,
      warnings: [
        "Project root is missing on disk.",
        "Referenced report path is missing on disk.",
        "Remote report URL recorded in appliance state.",
      ],
    });

    expect(viewModel.warnings.map((warning) => warning.message)).toEqual([
      "Lokal cache mangler prosjektmappe.",
      "Rapport finnes i OneDrive men lokal kopi er ikke tilgjengelig.",
      "Rapport finnes kun som ekstern URL.",
    ]);
    expect(viewModel.warnings[0].technicalDetails).toEqual(["Project root is missing on disk."]);
  });

  it("keeps cache-only technical warnings out of the user-facing issue list when content is available", () => {
    const viewModel = createProjectViewModel({
      ...makeProject("Bryn Skole", false),
      status: "completed_with_warnings",
      warnings: [
        "Project root is missing on disk.",
        "Referenced report path is missing on disk.",
        "Remote report URL recorded in appliance state.",
      ],
    });

    expect(viewModel.status.level).toBe("SUCCESS_WITH_WARNINGS");
    expect(viewModel.warnings).toEqual([]);
    expect(viewModel.technicalWarnings).toEqual([
      "Project root is missing on disk.",
      "Referenced report path is missing on disk.",
      "Remote report URL recorded in appliance state.",
    ]);
  });
});
