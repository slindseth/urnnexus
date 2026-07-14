import type { AnalysisStatusResponse } from "../types";

const LOCK_BUSY_PATTERNS = [
  "awaiting history lock",
  "waiting for history lock",
  "onedrive_sync_history.lock",
  "onedrive_lightweight_state.sqlite3",
] as const;

const ANALYSIS_TERMINAL_STATUSES: Array<AnalysisStatusResponse["status"]> = [
  "completed",
  "failed",
  "auth_failed",
  "sync_failed",
];

export const APPLIANCE_BUSY_MESSAGE = "Appliance arbeider. Synk kan startes når aktiv jobb er ferdig.";
export const APPLIANCE_BUSY_LABEL = "Appliance arbeider";
export const SYNC_LOCK_HELP_TEXT = "Synk er midlertidig deaktivert fordi Appliance er opptatt med analyse eller OneDrive-state.";
export const SYNC_BUSY_INLINE_MESSAGE = APPLIANCE_BUSY_MESSAGE;
export const SYNC_RUNNING_LABEL = "OneDrive synkroniserer";
export const ANALYSIS_RUNNING_LABEL = "Analyse pågår";
export const ANALYSIS_STARTING_LABEL = "Starter analyse";
export const ANALYSIS_STARTUP_GRACE_MS = 5000;
export const SYNC_FAILED_LABEL = "Forrige sync feilet";
export const APPLIANCE_CLEAR_MESSAGE = "Klar";
export const SYNC_STALE_LOCK_WARNING = "Tidligere sync stoppet på lock. Prøv igjen.";
export const ANALYSIS_STALE_LOCK_WARNING = "Tidligere analyse stoppet på lock. Prøv igjen.";

export interface AnalysisErrorContext {
  status?: AnalysisStatusResponse["status"] | null;
  authStatus?: AnalysisStatusResponse["auth_status"] | null;
  startupGraceActive?: boolean;
}

function normalize(value: string | null | undefined): string {
  return value?.toLowerCase() ?? "";
}

export function isLockBusyError(value: string | null | undefined): boolean {
  const normalized = normalize(value);
  return LOCK_BUSY_PATTERNS.some((pattern) => normalized.includes(pattern));
}

export function isAnalysisStartupStatus(status: string | null | undefined): boolean {
  return status === "startup_pending";
}

export function isAnalysisTerminalStatus(status: string | null | undefined): status is AnalysisStatusResponse["status"] {
  return ANALYSIS_TERMINAL_STATUSES.includes(status as AnalysisStatusResponse["status"]);
}

export function getVisibleSyncErrorMessage(lastError: string | null | undefined, errorCode?: string | null): string | null {
  if (!lastError) {
    return null;
  }
  if (isLockBusyError(lastError)) {
    return SYNC_STALE_LOCK_WARNING;
  }
  return errorCode && ["sync_failed", "project_sync_failed", "onedrive_sync_failed", "graph_auth_failed", "graph_permission_denied", "auth_failed"].includes(errorCode)
    ? "Synkroniseringen kunne ikke fullføres."
    : null;
}

export function getVisibleAnalysisErrorMessage(lastError: string | null | undefined, context: AnalysisErrorContext = {}): string | null {
  if (!lastError) {
    return null;
  }
  if (context.startupGraceActive && (context.status === "idle" || context.status === "startup_pending" || context.status === undefined)) {
    return null;
  }
  if (context.status === "auth_failed" || context.authStatus === "auth_failed") {
    return "Microsoft Graph-autentiseringen feilet. OneDrive krever ny innlogging.";
  }
  if (context.status === "sync_failed" || context.authStatus === "sync_failed") {
    return "Synkroniseringen kunne ikke fullføres.";
  }
  if (isLockBusyError(lastError)) {
    return ANALYSIS_STALE_LOCK_WARNING;
  }
  return "Analysen kunne ikke fullføres.";
}
