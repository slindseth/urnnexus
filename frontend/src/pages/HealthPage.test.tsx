import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import { describe, expect, it } from "vitest";
import { AppDataContext } from "../context/AppDataContext";
import { createProjectViewModel } from "../lib/projects";
import type { HealthResponse, ProjectSummary } from "../types";
import { HealthPage } from "./HealthPage";

function makeProject(projectName: string): ProjectSummary {
  return {
    project_name: projectName,
    display_name: projectName,
    source_label: "OneDrive",
    relative_project_path: `Urban_Reuse_Norway/${projectName}`,
    hidden_internal_path: `/home/anbudklient/appliance/runtime/${projectName}`,
    last_synced_at: "2026-06-08T08:00:00+02:00",
    latest_comment_document: null,
    latest_comment_document_open_url: null,
    latest_comment_created_at: null,
    latest_comment_modified_at: null,
    comment_document_count: 0,
    is_sample_project: false,
    is_local_cache_only: false,
    project_path: `/home/anbudklient/appliance/${projectName}`,
    last_analyzed_at: "2026-06-08T08:15:00+02:00",
    status: "completed",
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
  discovered_projects: 2,
  last_synced_at: "2026-06-09T08:49:00+02:00",
  last_analyzed_at: "2026-06-08T08:15:00+02:00",
  latest_report_generated_at: "2026-06-08T08:15:00+02:00",
  project_count: 2,
  file_count: 12,
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

describe("HealthPage", () => {
  it("renders the Norwegian health title, tooltips, and compact health cards", () => {
    const markup = renderToStaticMarkup(
      <StaticRouter location="/health">
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
          <HealthPage />
        </AppDataContext.Provider>
      </StaticRouter>,
    );

    expect(markup).toContain("Helse");
    expect(markup).toContain("0.1.9");
    expect(markup).toContain("Oppetid");
    expect(markup).toContain("Prosjekter totalt");
    expect(markup).toContain("Feil/varsler siste 24t");
    expect(markup).toContain("Viser om Nexus-backend svarer på API-kall.");
    expect(markup).toContain("Antall prosjekter som faktisk er synlige i denne visningen akkurat nå.");
    expect(markup).toContain("Totalt antall prosjekter backend har funnet i datagrunnlaget.");
    expect(markup).toContain("Innlogging, tillatelser og ekstern opplasting er ikke dermed verifisert.");
    expect(markup.match(/Ikke verifisert/g)).toHaveLength(3);
    expect(markup).toContain('role="tooltip"');
    expect(markup).toContain('tabindex="0"');
    expect(markup).toContain("status-badge__label");
    const expectedCardOrder = [
      "Tilgjengelig",
      "Oppetid",
      "Versjon",
      "Prosjekter i visning",
      "Prosjekter totalt",
      "Antall filer",
      "Rapporter",
      "Siste synk",
      "Siste analyse",
      "Siste rapport opprettet",
      "OneDrive-status",
      "Graph-write",
      "Diskbruk",
      "Ledig disk",
      "Cache-størrelse",
      "Feil/varsler siste 24t",
    ];

    let lastIndex = -1;
    for (const label of expectedCardOrder) {
      const index = markup.indexOf(label);
      expect(index, `Expected to find ${label}`).toBeGreaterThan(lastIndex);
      lastIndex = index;
    }
    expect(markup).not.toContain("OpenAI-status");
    expect(markup).not.toContain("SMTP-status");
    expect(markup).not.toContain("OPENAI_API_KEY");
    expect(markup).not.toContain("SMTP_HOST");
    expect(markup).not.toContain("Microsoft Graph-write er konfigurert for direkte OneDrive-opprettelse.");
    expect(markup).not.toContain("2 prosjekter funnet i lokal OneDrive-cache.");
    expect(markup).not.toContain("Feil siste 24 timer");
    expect(markup).not.toContain("Varsler siste 24 timer");
    expect(markup).not.toContain("page-header__eyebrow");
    expect(markup).not.toContain("URN Nexus");
  });

  it("shows the backend version directly", () => {
    const markup = renderToStaticMarkup(
      <StaticRouter location="/health">
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
          <HealthPage />
        </AppDataContext.Provider>
      </StaticRouter>,
    );

    expect(markup).toContain("0.1.9");
    expect(markup).not.toContain("0.1.5");
  });
});
