import type {
  ActivityEventsResponse,
  ActivityLogsResponse,
  ActivityStatusResponse,
  AnalysisRunRequest,
  AnalysisRunResponse,
  AnalysisStatusResponse,
  HealthResponse,
  FileUploadResponse,
  FolderCreateRequest,
  FolderCreateResponse,
  ProjectCreateRequest,
  ProjectCreateResponse,
  ProjectDeleteResponse,
  ProjectDetailResponse,
  ProjectFilesResponse,
  ProjectListResponse,
  ProjectReportsResponse,
  ReadinessResponse,
  SyncRunResponse,
  SyncStatusResponse,
  ErrorCategory,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";
const REQUEST_TIMEOUT_MS = 20_000;

function joinPath(base: string, path: string): string {
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`;
}

interface ApiErrorDetails {
  code: string | null;
  message: string;
}

async function readJsonError(response: Response): Promise<ApiErrorDetails> {
  try {
    const payload = (await response.json()) as Record<string, unknown>;
    const message = typeof payload.detail === "string" && payload.detail.trim()
      ? payload.detail
      : typeof payload.message === "string" && payload.message.trim()
        ? payload.message
        : `${response.status} ${response.statusText}`;
    return {
      code: typeof payload.code === "string" && payload.code.trim() ? payload.code : null,
      message,
    };
  } catch {
    // fall through to generic message
  }
  return { code: null, message: `${response.status} ${response.statusText}` };
}

function logApiFailure(method: string, path: string, error: unknown): void {
  if (!import.meta.env.DEV) {
    return;
  }
  console.error(`[API] ${method} ${joinPath(API_BASE, path)} failed`, error);
}

export class ApiRequestError extends Error {
  status: number;
  code: string | null;
  rawMessage: string;
  category: ErrorCategory;

  constructor(status: number, message: string, code: string | null = null, category?: ErrorCategory) {
    super(message);
    this.status = status;
    this.code = code;
    this.rawMessage = message;
    this.category = category ?? classifyErrorCategory({ status, code, message });
    this.name = "ApiRequestError";
  }
}

export class StartupError extends Error {
  category: "Startup" = "Startup";
  code: string;

  constructor(message: string, code = "startup_timeout") {
    super(message);
    this.code = code;
    this.name = "StartupError";
  }
}

export function classifyErrorCategory(error: unknown): ErrorCategory {
  const candidate = error && typeof error === "object"
    ? error as { status?: number; code?: string | null; message?: string; category?: ErrorCategory }
    : {};
  if (candidate.category === "Startup") return "Startup";
  const code = String(candidate.code ?? "").toLowerCase();
  const message = String(candidate.message ?? "").toLowerCase();
  if (code.includes("graph") || code.includes("auth") || /invalid_grant|token expired|unauthorized/.test(message)) return "Graph Authentication";
  if (code.includes("sync") || /onedrive sync|sync failed|synkronisering/.test(message)) return "Synchronization";
  if (code.includes("appliance")) return "Appliance";
  if (code.includes("onedrive")) return "OneDrive";
  if (code.includes("analysis") || code.includes("analyse")) return "Analysis";
  if (candidate.status === 0 || candidate.status === 408 || code.includes("backend")) return "Backend";
  if (candidate.status && candidate.status >= 500) return "Backend";
  return "Unknown";
}

function createNetworkError(error: unknown): ApiRequestError {
  const detail = error instanceof Error ? error.message : "Backend unavailable";
  return new ApiRequestError(0, detail, "backend_unavailable");
}

/** Map backend/transport details to stable Norwegian UI copy. */
export function getUserFacingErrorMessage(error: unknown, fallback = "Status kunne ikke hentes."): string {
  const status = error instanceof ApiRequestError ? error.status : null;
  const candidate = error && typeof error === "object" ? error as { code?: string | null; rawMessage?: string } : null;
  const code = (error instanceof ApiRequestError ? error.code : candidate?.code)?.toLowerCase() ?? "";
  const rawSource = error instanceof ApiRequestError
    ? error.rawMessage
    : candidate?.rawMessage ?? (error instanceof Error ? error.message : "");
  const raw = rawSource.toLowerCase();
  if (code.startsWith("memory_")) return rawSource || fallback;

  if (code === "appliance_busy" || raw === "appliance arbeider. synk kan startes når aktiv jobb er ferdig.") {
    return "Appliance arbeider. Synk kan startes når aktiv jobb er ferdig.";
  }
  if (code === "graph_auth_failed" || code === "graph_permission_denied" || code === "auth_failed" || /invalid_grant|graph auth|authentication failed|token expired|unauthorized/.test(raw)) {
    return "OneDrive krever ny innlogging.";
  }
  if (code === "sync_failed" || code === "project_sync_failed" || code === "onedrive_sync_failed" || /onedrive sync failed|sync failed|synkronisering.*feil/.test(raw)) {
    return "Synkroniseringen kunne ikke fullføres.";
  }
  if (code === "backend_configuration_error") {
    return "NEXUS mangler backend-konfigurasjon.";
  }
  if (code === "appliance_unreachable" || code === "backend_unavailable" || code === "connection_refused") {
    return "Kunne ikke koble til Appliance.";
  }
  if (code === "timeout" || status === 408 || status === 500 || status === 502 || status === 503 || status === 504 || code === "internal_error") {
    return fallback;
  }
  return fallback;
}

export function isRetryableStartupError(error: unknown): boolean {
  if (!(error instanceof ApiRequestError)) {
    return true;
  }
  return !["graph_auth_failed", "graph_permission_denied", "auth_failed", "sync_failed", "backend_configuration_error", "appliance_unreachable", "appliance_unavailable"].includes(error.code ?? "");
}

export async function fetchJson<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(joinPath(API_BASE, path), {
      headers: {
        Accept: "application/json",
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      const details = await readJsonError(response);
      const error = new ApiRequestError(response.status, details.message, details.code);
      logApiFailure("GET", path, error);
      throw error;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      const timeoutError = new ApiRequestError(408, "API-kallet tok for lang tid.", "timeout");
      logApiFailure("GET", path, timeoutError);
      throw timeoutError;
    }
    if (!(error instanceof ApiRequestError)) {
      const networkError = createNetworkError(error);
      logApiFailure("GET", path, networkError);
      throw networkError;
    }
    logApiFailure("GET", path, error);
    throw error;
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

export async function sendJson<T>(path: string, payload?: unknown): Promise<T> {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(joinPath(API_BASE, path), {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Nexus-Action": "project-memory",
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      const details = await readJsonError(response);
      const error = new ApiRequestError(response.status, details.message, details.code);
      logApiFailure("POST", path, error);
      throw error;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      const timeoutError = new ApiRequestError(408, "API-kallet tok for lang tid.", "timeout");
      logApiFailure("POST", path, timeoutError);
      throw timeoutError;
    }
    if (!(error instanceof ApiRequestError)) {
      const networkError = createNetworkError(error);
      logApiFailure("POST", path, networkError);
      throw networkError;
    }
    logApiFailure("POST", path, error);
    throw error;
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

async function deleteJson<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(joinPath(API_BASE, path), {
      method: "DELETE",
      headers: {
        Accept: "application/json",
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      const details = await readJsonError(response);
      const error = new ApiRequestError(response.status, details.message, details.code);
      logApiFailure("DELETE", path, error);
      throw error;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      const timeoutError = new ApiRequestError(408, "API-kallet tok for lang tid.", "timeout");
      logApiFailure("DELETE", path, timeoutError);
      throw timeoutError;
    }
    if (!(error instanceof ApiRequestError)) {
      const networkError = createNetworkError(error);
      logApiFailure("DELETE", path, networkError);
      throw networkError;
    }
    logApiFailure("DELETE", path, error);
    throw error;
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

async function sendForm<T>(path: string, formData: FormData, options: { timeoutMs?: number } = {}): Promise<T> {
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timeoutId = controller ? globalThis.setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(joinPath(API_BASE, path), {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
      body: formData,
      signal: controller?.signal,
    });

    if (!response.ok) {
      const details = await readJsonError(response);
      const error = new ApiRequestError(response.status, details.message, details.code);
      logApiFailure("POST", path, error);
      throw error;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      const timeoutError = new ApiRequestError(408, "API-kallet tok for lang tid.", "timeout");
      logApiFailure("POST", path, timeoutError);
      throw timeoutError;
    }
    if (!(error instanceof ApiRequestError)) {
      const networkError = createNetworkError(error);
      logApiFailure("POST", path, networkError);
      throw networkError;
    }
    logApiFailure("POST", path, error);
    throw error;
  } finally {
    if (timeoutId) {
      globalThis.clearTimeout(timeoutId);
    }
  }
}

export function projectUrl(projectName: string, suffix = ""): string {
  const encoded = encodeURIComponent(projectName);
  const normalizedSuffix = suffix.startsWith("/") ? suffix : suffix ? `/${suffix}` : "";
  return `/projects/${encoded}${normalizedSuffix}`;
}

function withQuery(path: string, params: Record<string, string | boolean | undefined>): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) {
      continue;
    }
    searchParams.set(key, String(value));
  }
  const query = searchParams.toString();
  return query ? `${path}?${query}` : path;
}

export function safeDecodeProjectName(projectName: string | undefined): string {
  if (!projectName) {
    return "";
  }
  try {
    return decodeURIComponent(projectName);
  } catch {
    return projectName;
  }
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) {
    return "—";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 100 ? value.toFixed(0) : value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${units[unitIndex]}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("nb-NO", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatTimeOfDay(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("nb-NO", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "—";
  }
  const rounded = Math.floor(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const secs = rounded % 60;
  if (hours > 0) {
    return `${hours}t ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  }
  return `${secs}s`;
}

export async function getHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>("/health");
}

export async function getSystemReadiness(): Promise<ReadinessResponse> {
  return fetchJson<ReadinessResponse>("/system/readiness");
}

export async function getActivityStatus(): Promise<ActivityStatusResponse> {
  return fetchJson<ActivityStatusResponse>("/activity/status");
}

export async function getActivityEvents(): Promise<ActivityEventsResponse> {
  return fetchJson<ActivityEventsResponse>("/activity/events");
}

export async function getActivityLogs(): Promise<ActivityLogsResponse> {
  return fetchJson<ActivityLogsResponse>("/activity/logs");
}

export async function getProjects(options?: { includeSampleProjects?: boolean }): Promise<ProjectListResponse> {
  return fetchJson<ProjectListResponse>(
    withQuery("/projects", {
      include_sample_projects: options?.includeSampleProjects,
    }),
  );
}

export async function getProject(projectName: string): Promise<ProjectDetailResponse> {
  return fetchJson<ProjectDetailResponse>(projectUrl(projectName));
}

export async function getProjectReports(projectName: string): Promise<ProjectReportsResponse> {
  return fetchJson<ProjectReportsResponse>(projectUrl(projectName, "reports"));
}

export async function getProjectFiles(projectName: string): Promise<ProjectFilesResponse> {
  return fetchJson<ProjectFilesResponse>(projectUrl(projectName, "files"));
}

export async function createProject(payload: ProjectCreateRequest): Promise<ProjectCreateResponse> {
  return sendJson<ProjectCreateResponse>("/projects", payload);
}

export async function deleteProject(projectName: string): Promise<ProjectDeleteResponse> {
  return deleteJson<ProjectDeleteResponse>(projectUrl(projectName));
}

export async function uploadProjectFile(projectName: string, file: File, targetFolder: string): Promise<FileUploadResponse> {
  const formData = new FormData();
  formData.set("file", file);
  formData.set("target_folder", targetFolder);
  return sendForm<FileUploadResponse>(projectUrl(projectName, "files/upload"), formData, { timeoutMs: 0 });
}

export async function createProjectFolder(projectName: string, payload: FolderCreateRequest): Promise<FolderCreateResponse> {
  return sendJson<FolderCreateResponse>(projectUrl(projectName, "files/folders"), payload);
}

export async function runSync(options: { projectName?: string | null; idempotencyKey?: string | null } = {}): Promise<SyncRunResponse> {
  return sendJson<SyncRunResponse>("/sync/start", {
    project_name: options.projectName ?? null,
    idempotency_key: options.idempotencyKey ?? null,
  });
}

export async function getSyncStatus(): Promise<SyncStatusResponse> {
  return fetchJson<SyncStatusResponse>("/sync/status");
}

export async function runAnalysis(payload: AnalysisRunRequest): Promise<AnalysisRunResponse> {
  return sendJson<AnalysisRunResponse>("/analysis/start", payload);
}

export async function getAnalysisStatus(): Promise<AnalysisStatusResponse> {
  return fetchJson<AnalysisStatusResponse>("/analysis/status");
}
