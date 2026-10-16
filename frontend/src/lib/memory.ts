import { fetchJson, sendJson } from "./api";

export interface MemoryJob {
  job_id: string;
  project_id: string;
  snapshot_id: string;
  processing_version: string;
  stage: string;
  status: string;
  created_at: string;
  updated_at: string;
  files_discovered: number;
  files_supported: number;
  unsupported_files: number;
  unreadable_files: number;
  native_units: number;
  manual_review_units: number;
  batches_reviewed: number;
  batches_pending: number;
  batches_failed: number;
  findings?: number;
  unverified_findings?: number;
  report_id?: string;
  overview_verified?: boolean;
  stale?: boolean;
  provider?: string;
  batches: Array<{ operation: string; status: string; count: number }>;
  processing_errors: Array<{
    id: string;
    operation: string;
    status: string;
    error: string;
  }>;
  usage: {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cost: number | null;
  };
  consolidation?: {
    raw_verified: number;
    reported_verified: number;
    duplicates_consolidated: number;
    repaired_merges?: number;
  };
  retrieval?: { mode: string; model: string | null; dimension: number | null };
}
export interface MemoryJobRef {
  id: string;
  snapshot: string;
  stage: string;
  status: string;
  created_at: string;
  updated_at: string;
}
export interface MemoryJobs {
  jobs: MemoryJobRef[];
  next_after: number | null;
  actions_enabled: boolean;
  worker_active: boolean;
}
export interface MemoryStatus {
  job: MemoryJob;
  worker_active: boolean;
  cancellation_requested: boolean;
  actions_enabled: boolean;
  historical: boolean;
  can_resume: boolean;
  freshness: {
    state: string;
    changed: string[];
    unavailable: string[];
    scope: string;
  };
}
export interface MemoryFinding {
  id: string;
  title: string;
  conclusion: string;
  category: string;
  categories?: string[];
  evidence: string[];
  uncertainty: string;
  recommended_check: string;
  verification: {
    supported: boolean;
    reason: string;
    uncertainty: string;
    evidence: string[];
  };
  member_ids?: string[];
  member_findings?: MemoryFinding[];
  source_versions?: string[];
  consolidation?: { reason: string; scope: string; corrected?: boolean };
}
export interface MemoryEvidence {
  evidence_id: string;
  document_version_id: string;
  source_location_id: string;
  source_hash: string;
  path: string;
  locator: Record<string, unknown>;
  excerpt: string;
  statement: string;
  kind: string;
  uncertainty: string;
  source_url: string;
}
export interface MemoryReport {
  report_id: string;
  job_id: string;
  snapshot_id: string;
  name: string;
  status: string;
  hash: string;
  created_at: string;
  download_url: string;
  preview_url: string;
  is_current?: boolean;
}
export interface MemoryView {
  id: string;
  overview: string;
  evidence: string[];
  limitations: string[];
  verified?: boolean;
  label?: string;
  snapshot?: string;
}
export interface ManualUnit {
  id: string;
  path: string;
  version: string;
  locator: string | Record<string, unknown>;
  state: string;
  quality: string | Record<string, unknown>;
  source_url?: string;
}
export interface MemoryReference {
  reference: string;
  state: string;
  work_id: string;
  unit_id?: string;
}

export const memoryPath = (project: string, job?: string, operation = "") =>
  `/projects/${encodeURIComponent(project)}/memory${job ? `/jobs/${encodeURIComponent(job)}` : ""}${operation ? `/${operation}` : ""}`;
export const memoryJobs = (project: string, after = 0) =>
  fetchJson<MemoryJobs>(`${memoryPath(project)}/jobs?after=${after}`);
export const memoryStatus = (project: string, job: string) =>
  fetchJson<MemoryStatus>(memoryPath(project, job));
export const memoryFindings = (project: string, job: string, after = 0) =>
  fetchJson<{ findings: MemoryFinding[]; next_after: number | null }>(
    `${memoryPath(project, job, "findings")}?after=${after}`,
  );
export const memoryReports = (project: string, job: string, after = 0) =>
  fetchJson<{ reports: MemoryReport[]; next_after: number | null }>(
    `${memoryPath(project, job, "reports")}?after=${after}`,
  );
export const memoryViews = (project: string, job: string, after = 0) =>
  fetchJson<{
    overview: MemoryView | null;
    topics: MemoryView[];
    next_after: number | null;
  }>(`${memoryPath(project, job, "views")}?after=${after}`);
export const memoryManual = (project: string, job: string, after = 0) =>
  fetchJson<{ units: ManualUnit[]; next_after: number | null }>(
    `${memoryPath(project, job, "manual-review")}?after=${after}`,
  );
export const memoryReferences = (project: string, job: string, after = 0) =>
  fetchJson<{ references: MemoryReference[]; next_after: number | null }>(
    `${memoryPath(project, job, "references")}?after=${after}`,
  );
export const memoryEvents = (project: string, job: string, after = 0) =>
  fetchJson<{
    events: Array<{
      sequence: number;
      stage: string;
      status: string;
      created_at: string;
    }>;
    next_after: number;
  }>(`${memoryPath(project, job, "events")}?after=${after}`);
export const startMemory = (
  project: string,
  mode: "incremental" | "full" | "resume",
  job_id?: string,
) =>
  sendJson<{
    accepted: boolean;
    job_id: string | null;
    launch_pending: boolean;
  }>(memoryPath(project, undefined, "run"), { mode, job_id });
export const cancelMemory = (project: string, job: string) =>
  sendJson<{ cancellation_requested: boolean }>(
    memoryPath(project, job, "cancel"),
    {},
  );

const evidenceCache = new Map<string, Promise<MemoryEvidence>>();
export function memoryEvidence(project: string, job: string, id: string) {
  const key = memoryPath(project, job, `evidence/${encodeURIComponent(id)}`);
  if (!evidenceCache.has(key)) {
    if (evidenceCache.size > 500) evidenceCache.clear();
    evidenceCache.set(
      key,
      fetchJson<MemoryEvidence>(key).catch((error) => {
        evidenceCache.delete(key);
        throw error;
      }),
    );
  }
  return evidenceCache.get(key)!;
}

export const stageLabels: Record<string, string> = {
  inventory: "Inventar",
  extraction: "Tekstuttrekk og OCR",
  indexing: "Lokal indeksering",
  review: "Seksjonsgjennomgang",
  reconciliation: "Sammenstilling",
  verification: "Evidenskontroll",
  consolidation: "Samling av like funn",
  report_generation: "Oversikter og Word-rapport",
};
export const jobLabels: Record<string, string> = {
  running: "Pågår",
  completed: "Fullført",
  partial: "Delvis gjennomgått",
  stale: "Utdatert snapshot",
  failed: "Feilet",
  cancelled: "Stoppet",
};
export function locationLabel(locator: string | Record<string, unknown>) {
  let value: Record<string, unknown>;
  try {
    value =
      typeof locator === "string"
        ? (JSON.parse(locator) as Record<string, unknown>)
        : locator;
  } catch {
    return String(locator);
  }
  const labels: Record<string, string> = {
    page: "Side",
    paragraph: "Avsnitt",
    table: "Tabell",
    row: "Rad",
    sheet: "Ark",
    cells: "Celler",
    part: "Del",
    line: "Linje",
  };
  return Object.entries(value)
    .map(
      ([key, item]) =>
        `${labels[key] ?? key} ${typeof item === "object" ? JSON.stringify(item) : String(item)}`,
    )
    .join(" · ");
}
