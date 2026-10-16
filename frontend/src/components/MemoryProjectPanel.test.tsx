// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryProjectPanel } from "./MemoryProjectPanel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | null = null;
afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  root = null;
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});
const wait = () => new Promise((resolve) => setTimeout(resolve, 0));
async function mount() {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root!.render(
      <MemoryRouter initialEntries={["/?job=job:saved"]}>
        <MemoryProjectPanel projectName="Prosjekt Æ" />
      </MemoryRouter>,
    );
    await wait();
  });
  return host;
}
function button(host: HTMLElement, text: string) {
  const found = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes(text),
  );
  expect(found, text).toBeDefined();
  return found!;
}
async function expand(host: HTMLElement, text: string) {
  const summary = [...host.querySelectorAll("summary")].find((s) =>
    s.textContent?.includes(text),
  )!;
  expect(summary).toBeDefined();
  await act(async () => {
    const details = summary.parentElement as HTMLDetailsElement;
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    await wait();
  });
}
function mockApi({
  status = "partial",
  active = false,
  unavailable = false,
} = {}) {
  const requests: Array<{ url: string; method: string; body?: string }> = [];
  let updated = "2026-10-14T12:00:00Z";
  const job = {
    job_id: "job:saved",
    project_id: "project:fixture",
    snapshot_id: "snapshot:saved",
    processing_version: "processing:fixture",
    stage: "report_generation",
    status,
    created_at: updated,
    updated_at: updated,
    files_discovered: 3,
    files_supported: 3,
    unsupported_files: 0,
    unreadable_files: 0,
    native_units: 7,
    manual_review_units: 1,
    batches_reviewed: 4,
    batches_pending: 0,
    batches_failed: 0,
    batches: [],
    processing_errors: [],
    usage: { calls: 12, input_tokens: 800, output_tokens: 100, cost: null },
    report_id: "report:partial",
  };
  const fetch = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      requests.push({
        url,
        method: init?.method ?? "GET",
        body: init?.body as string | undefined,
      });
      if (unavailable && /\/jobs\?/.test(url))
        return new Response(
          JSON.stringify({
            code: "memory_cli_unavailable",
            detail: "Arbeideren mangler. Kontroller CLI-sti.",
          }),
          { status: 503 },
        );
      let value: unknown;
      if (url.endsWith("/run")) {
        updated = "2026-10-14T12:01:00Z";
        value = { accepted: true, job_id: job.job_id, launch_pending: true };
      } else if (/\/jobs\?/.test(url))
        value = {
          jobs: [
            {
              id: job.job_id,
              snapshot: job.snapshot_id,
              status,
              stage: job.stage,
              created_at: job.created_at,
              updated_at: updated,
            },
          ],
          next_after: null,
          actions_enabled: true,
          worker_active: active,
        };
      else if (url.includes("/findings?"))
        value = {
          findings: [
            {
              id: "finding-group:fixture",
              title: "Samlet avfallssak",
              category: "contradiction",
              conclusion: "Kontroller avfallskostnader.",
              evidence: Array.from(
                { length: 8 },
                (_, n) => `evidence:lazy-${n}`,
              ),
              uncertainty: "Ukjent rang",
              recommended_check: "Avklar internt.",
              verification: {
                supported: true,
                uncertainty: "",
                reason: "Kontrollert",
                evidence: [],
              },
              member_ids: ["finding:a", "finding:b"],
            },
          ],
          next_after: null,
        };
      else if (url.includes("/reports?"))
        value = {
          reports: [
            {
              report_id: "report:partial",
              name: "Kommentar.docx",
              hash: "hash",
              created_at: updated,
              download_url: "/api/word-download",
              preview_url: "/api/local-preview",
            },
          ],
          next_after: null,
        };
      else if (url.includes("/manual-review?"))
        value = {
          units: [
            {
              id: "unit:scan",
              path: "Skann.pdf",
              version: "version:scan",
              locator: '{"page":1}',
              state: "unreadable_scan_or_drawing",
              quality: "Manuell kontroll",
              source_url: "/api/saved-scan",
            },
          ],
          next_after: null,
        };
      else if (url.includes("/references?"))
        value = {
          references: [
            {
              work_id: "work:fixture",
              reference: "Se vedlegg B",
              state: "unresolved",
            },
          ],
          next_after: null,
        };
      else if (url.includes("/views?"))
        value = {
          overview: {
            id: "view:overview",
            overview: "Prosjektets oversikt",
            limitations: [],
            evidence: ["evidence:overview"],
            verified: true,
          },
          topics: [
            {
              id: "view:topic",
              label: "Avfall",
              overview: "Om avfall",
              limitations: [],
              evidence: ["evidence:topic"],
            },
          ],
          next_after: null,
        };
      else if (url.includes("/evidence/"))
        value = {
          evidence_id: url.split("/").pop(),
          document_version_id: "version:saved",
          source_location_id: "unit:saved",
          source_hash: "hash:saved",
          path: "Avtale.docx",
          locator: { paragraph: 3 },
          excerpt: "Eksakt utdrag",
          statement: "Kildeutsagn",
          uncertainty: "",
          source_url: "/api/immutable-source",
        };
      else
        value = {
          job: { ...job, updated_at: updated },
          worker_active: active,
          cancellation_requested: false,
          actions_enabled: true,
          historical: false,
          can_resume: status === "failed",
          freshness: {
            state: "changed",
            changed: ["Tillegg.docx"],
            unavailable: [],
            scope: "Bare kjente kilder kontrollert.",
          },
        };
      return new Response(JSON.stringify(value), { status: 200 });
    },
  );
  vi.stubGlobal("fetch", fetch);
  return { requests, fetch };
}
describe("MemoryProjectPanel appliance workflow", () => {
  it("reconnects to the requested job, preserves partial reports and loads every citation on demand", async () => {
    const { requests } = mockApi();
    const host = await mount();
    expect(host.textContent).toContain("snapshot:saved");
    expect(host.textContent).toContain("Delvis gjennomgått");
    expect(host.textContent).toContain("Kildegrunnlaget er endret");
    expect(host.querySelector('a[href="/api/word-download"]')).not.toBeNull();
    expect(requests.some((r) => r.url.includes("/evidence/"))).toBe(false);
    expect(requests.every((r) => r.method === "GET")).toBe(true);
    expect(requests.some((r) => r.url.endsWith("/jobs/job%3Asaved"))).toBe(
      true,
    );
    await expand(host, "Samlet avfallssak");
    expect(requests.filter((r) => r.url.includes("/evidence/")).length).toBe(6);
    await act(async () => {
      button(host, "Vis flere kilder").click();
      await wait();
    });
    expect(host.querySelectorAll(".memory-evidence")).toHaveLength(8);
    expect(requests.filter((r) => r.url.includes("/evidence/")).length).toBe(8);
    expect(host.textContent).toContain("Avsnitt 3");
    expect(host.textContent).toContain("version:saved");
    await expand(host, "Manuell kontroll og referanser");
    expect(host.textContent).toContain("Se vedlegg B");
    expect(host.querySelector('a[href="/api/saved-scan"]')).not.toBeNull();
    expect(requests.every((r) => r.method === "GET")).toBe(true);
  });
  it("defers overview and topic citations until their summary is expanded", async () => {
    const { requests } = mockApi();
    const host = await mount();
    await expand(host, "Prosjektoversikt og temaoppsummeringer");
    expect(requests.filter((r) => r.url.includes("/evidence/"))).toHaveLength(
      0,
    );
    await expand(host, "Tema: Avfall");
    expect(requests.filter((r) => r.url.includes("/evidence/"))).toHaveLength(
      1,
    );
  });
  it("resumes the same failed job and recognizes fast worker completion", async () => {
    const { requests } = mockApi({ status: "failed" });
    const host = await mount();
    expect(host.textContent).toContain("Gjennomgangen stoppet med feil");
    await act(async () => {
      button(host, "Gjenoppta samme jobb").click();
      await wait();
    });
    const actions = requests.filter((r) => r.method === "POST");
    expect(actions).toHaveLength(1);
    expect(JSON.parse(actions[0].body!)).toEqual({
      mode: "resume",
      job_id: "job:saved",
    });
    expect(host.textContent).not.toContain("Starter arbeider");
  });
  it("waits for a new durable ID when the launch lock is active before job creation", async () => {
    const api = mockApi();
    let launching = false;
    let reads = 0;
    vi.stubGlobal(
      "fetch",
      async (input: string | URL | Request, init?: RequestInit) => {
        const response = await api.fetch(input, init);
        const value = await response.json();
        const url = String(input);
        if (url.endsWith("/run")) launching = true;
        else if (launching && url.includes("/jobs?")) {
          reads += 1;
          value.worker_active = reads === 1;
          if (reads > 1) value.jobs[0].id = "job:new";
        } else if (launching && url.endsWith("/jobs/job%3Asaved"))
          value.worker_active = true;
        else if (url.endsWith("/jobs/job%3Anew")) value.job.job_id = "job:new";
        return new Response(JSON.stringify(value));
      },
    );
    const host = await mount();
    await act(async () => {
      button(host, "Oppdater analyse").click();
      await wait();
    });
    expect(host.textContent).toContain("Starter arbeider");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2200));
    });
    expect(host.textContent).toContain("Jobb job:new");
    expect(host.textContent).not.toContain("Starter arbeider");
  });
  it("shows a bounded error when the appliance is unavailable", async () => {
    mockApi({ unavailable: true });
    const host = await mount();
    expect(host.textContent).toContain(
      "Arbeideren mangler. Kontroller CLI-sti.",
    );
    expect(host.textContent).not.toContain("Laster lagret");
    expect(button(host, "Prøv igjen")).toBeDefined();
  });
  it("blocks duplicate starts and heavy result reads during an active job", async () => {
    const { requests } = mockApi({ status: "running", active: true });
    const host = await mount();
    expect(button(host, "Oppdater analyse").disabled).toBe(true);
    expect(button(host, "Full reanalyse").disabled).toBe(true);
    expect(button(host, "Be om stopp").disabled).toBe(false);
    expect(requests.some((r) => r.url.includes("/findings?"))).toBe(false);
    expect(requests.every((r) => r.method === "GET")).toBe(true);
  });
});
