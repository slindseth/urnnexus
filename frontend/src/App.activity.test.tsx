import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppDataContext } from "./context/AppDataContext";
import { App } from "./App";

const { useActivityDataMock } = vi.hoisted(() => ({
  useActivityDataMock: vi.fn(),
}));

vi.mock("./lib/useActivityData", () => ({
  useActivityData: useActivityDataMock,
}));

afterEach(() => {
  useActivityDataMock.mockReset();
});

function makeAppData() {
  return {
    projects: [],
    projectsLoading: false,
    projectsError: null,
    projectWarnings: [],
    health: null,
    healthLoading: false,
    healthError: null,
    refresh: () => undefined,
    removeProjectByName: () => undefined,
  };
}

function makeActivityData() {
  return {
    status: {
      state: "Analyserer",
      activity: "Analyse",
      status: "Analyserer dokumenter",
      project_name: "Bryn Skole",
      uptime: "01:23:41",
      uptime_seconds: 5021,
      backend_version: "0.1.9",
      appliance_available: true,
      last_synced_at: "2026-06-30T07:58:00+02:00",
      last_analyzed_at: "2026-06-30T08:12:00+02:00",
      updated_at: "2026-06-30T08:12:10+02:00",
    },
    statusLoading: false,
    statusError: null,
    events: {
      updated_at: "2026-06-30T08:12:10+02:00",
      events: [
        {
          origin: "operational",
          timestamp: "2026-06-30T08:11:30+02:00",
          level: "SUCCESS",
          project_name: "Bryn Skole",
          component: "Reports",
          message: "Generated report",
        },
        {
          origin: "operational",
          timestamp: "2026-06-30T08:10:10+02:00",
          level: "INFO",
          project_name: "Bryn Skole",
          component: "Analysis",
          message: "Started analysis",
        },
      ],
      errors: [
        {
          origin: "operational",
          timestamp: "2026-06-30T08:09:02+02:00",
          project_name: "Bryn Skole",
          component: "OpenAI",
          message: "Request timed out",
        },
      ],
    },
    eventsLoading: false,
    eventsError: null,
    logs: {
      updated_at: "2026-06-30T08:12:10+02:00",
      entries: [
        {
          origin: "operational",
          timestamp: "2026-06-30T08:12:00+02:00",
          level: "INFO",
          project_name: "Bryn Skole",
          component: "OneDrive",
          message: "Starting OneDrive sync",
        },
        {
          origin: "operational",
          timestamp: "2026-06-30T08:12:05+02:00",
          level: "SUCCESS",
          project_name: "Bryn Skole",
          component: "Analysis",
          message: "Downloaded 18 files",
        },
      ],
    },
    logsLoading: false,
    logsError: null,
    refresh: () => undefined,
  };
}

describe("Activity route", () => {
  it("renders the operations center with activity content", () => {
    useActivityDataMock.mockReturnValue(makeActivityData());

    const markup = renderToStaticMarkup(
      <StaticRouter location="/activity">
        <AppDataContext.Provider value={makeAppData()}>
          <App />
        </AppDataContext.Provider>
      </StaticRouter>,
    );

    expect(markup).toContain("Aktivitet");
    expect(markup).toContain("Siste hendelser");
    expect(markup).toContain("Feilmeldinger");
    expect(markup).toContain("Aktivitetslogg");
    expect(markup).toContain("Bryn Skole");
    expect(markup).toContain("Generated report");
    expect(markup).toContain("Request timed out");
    expect(markup).toContain("Kopier");
    expect(markup).toContain("Last ned logg");
    expect(markup).toContain("Aktivitet");
    expect(markup).toContain("Helse");
  });

  it("renders empty states when there are no actionable activity items", () => {
    useActivityDataMock.mockReturnValue({
      ...makeActivityData(),
      events: { updated_at: "2026-06-30T08:12:10+02:00", events: [], errors: [] },
      logs: { updated_at: "2026-06-30T08:12:10+02:00", entries: [] },
    });

    const markup = renderToStaticMarkup(
      <StaticRouter location="/activity">
        <AppDataContext.Provider value={makeAppData()}>
          <App />
        </AppDataContext.Provider>
      </StaticRouter>,
    );

    expect(markup).toContain("Ingen registrerte feil");
    expect(markup).toContain("Ingen hendelser ennå");
    expect(markup).toContain("Ingen logglinjer");
  });
});
