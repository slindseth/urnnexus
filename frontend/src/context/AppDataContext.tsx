import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getAnalysisStatus, getHealth, getProjects, getSystemReadiness, getSyncStatus, getUserFacingErrorMessage, isRetryableStartupError, runSync, StartupError } from "../lib/api";
import { APPLIANCE_BUSY_MESSAGE, SYNC_STALE_LOCK_WARNING, isLockBusyError } from "../lib/applianceStatus";
import { createProjectViewModels, filterVisibleProjects, showSampleProjectsInUi, type ProjectViewModel } from "../lib/projects";
import type { AnalysisStatusResponse, HealthResponse, ReadinessResponse, StartupState, SyncStatusResponse } from "../types";

const DAILY_SYNC_STORAGE_KEY = "urn-nexus:daily-onedrive-sync";
const DAILY_SYNC_TIMEOUT_MS = 25_000;
const DAILY_SYNC_POLL_INTERVAL_MS = 3000;
const DAILY_SYNC_ONBOARDING_TITLE = "Velkommen til Urban Reuse Norway's NEXUS verktøy";
const DAILY_SYNC_MESSAGE = "Vent et øyeblikk mens OneDrive synkroniseres";
const DAILY_SYNC_TIMEOUT_MESSAGE = "Synkronisering tar lengre tid enn forventet. Du kan fortsette med sist synkroniserte data.";
const DAILY_SYNC_FAILED_MESSAGE = "OneDrive-synkroniseringen feilet.";
const DAILY_SYNC_BACKGROUND_MESSAGE = "OneDrive synkroniseres i bakgrunnen.";
export const STARTUP_GRACE_PERIOD_MS = 10_000;
export const STARTUP_RETRY_DELAYS_MS = [0, 2_000, 4_000, 6_000, 8_000, 10_000] as const;
const STARTUP_REQUEST_TIMEOUT_MS = 1_500;

type DailySyncRecordStatus = "running" | "completed" | "failed" | "timeout";
export type DailySyncModalMode = "onboarding" | "warning" | "fatal";

interface DailySyncRecord {
  date: string;
  started_at: string | null;
  completed_at: string | null;
  status: DailySyncRecordStatus;
  last_error: string | null;
  error_code?: string | null;
}

interface ApplianceStatusSnapshot {
  syncStatus: SyncStatusResponse;
  analysisStatus: AnalysisStatusResponse;
}

export interface DailySyncState {
  mode: DailySyncModalMode;
  title: string;
  message: string;
  detail: string | null;
  errorCode?: string | null;
}

interface AppDataContextValue {
  projects: ProjectViewModel[];
  projectsLoading: boolean;
  projectsError: string | null;
  projectWarnings: string[];
  health: HealthResponse | null;
  healthLoading: boolean;
  healthError: string | null;
  dailySync?: DailySyncState | null;
  dismissDailySync?: () => void;
  retryDailySync?: () => void;
  startupState?: StartupState;
  startupError?: string | null;
  retryStartup?: () => void;
  refresh: () => void;
  removeProjectByName: (projectName: string) => void;
}

export const AppDataContext = createContext<AppDataContextValue | null>(null);

async function readApplianceStatus(): Promise<ApplianceStatusSnapshot> {
  const [syncStatus, analysisStatus] = await Promise.all([getSyncStatus(), getAnalysisStatus()]);
  return { syncStatus, analysisStatus };
}

function resolveLiveApplianceActivity(syncStatus: SyncStatusResponse, analysisStatus: AnalysisStatusResponse): {
  activity: "sync" | "analysis" | "idle";
  syncRunning: boolean;
  analysisRunning: boolean;
} {
  const analysisStartupBusy = analysisStatus.status === "startup_pending" || analysisStatus.startup_grace_active;
  const syncRunning = Boolean(
    syncStatus.running ||
      syncStatus.process_alive ||
      syncStatus.status === "startup_pending" ||
      (syncStatus.job_type === "sync" && syncStatus.activity === "sync"),
  );
  const analysisRunning = Boolean(
    analysisStatus.running ||
      analysisStatus.process_alive ||
      analysisStartupBusy ||
      (analysisStatus.job_type === "analysis" && analysisStatus.activity === "analysis"),
  );
  return {
    activity: syncRunning ? "sync" : analysisRunning ? "analysis" : "idle",
    syncRunning,
    analysisRunning,
  };
}

function isValidStatusSnapshot(snapshot: ApplianceStatusSnapshot): boolean {
  const syncStatus = snapshot.syncStatus?.status?.trim().toLowerCase();
  const analysisStatus = snapshot.analysisStatus?.status?.trim().toLowerCase();
  const validSyncStatuses = new Set(["idle", "running", "completed", "completed_with_warnings", "skipped_no_changes", "failed", "error", "success"]);
  const validAnalysisStatuses = new Set(["idle", "startup_pending", "running", "completed", "failed", "auth_failed", "sync_failed"]);
  const unclassifiedSyncFailure = ["failed", "error"].includes(syncStatus ?? "") && !snapshot.syncStatus?.error_code;
  const unclassifiedAnalysisFailure = ["failed", "auth_failed", "sync_failed"].includes(analysisStatus ?? "") && !snapshot.analysisStatus?.error_code;
  return Boolean(
    snapshot.syncStatus &&
      snapshot.analysisStatus &&
      typeof snapshot.syncStatus.status === "string" &&
      typeof snapshot.analysisStatus.status === "string" &&
      syncStatus &&
      analysisStatus &&
      syncStatus !== "unknown" &&
      analysisStatus !== "unknown" &&
      validSyncStatuses.has(syncStatus) &&
      validAnalysisStatuses.has(analysisStatus) &&
      !unclassifiedSyncFailure &&
      !unclassifiedAnalysisFailure,
  );
}

function getExplicitStartupFailureCode(readiness: ReadinessResponse | null, snapshot: ApplianceStatusSnapshot | null): string | null {
  const permanentCodes = new Set([
    "graph_auth_failed",
    "auth_failed",
    "sync_failed",
    "graph_permission_denied",
    "backend_configuration_error",
    "appliance_unreachable",
    "appliance_unavailable",
  ]);
  for (const code of [readiness?.code, snapshot?.syncStatus.error_code, snapshot?.analysisStatus.error_code]) {
    if (code && permanentCodes.has(code)) {
      return code;
    }
  }
  return null;
}

const EXPLICIT_SYNC_FAILURE_CODES = new Set([
  "sync_failed",
  "project_sync_failed",
  "onedrive_sync_failed",
  "graph_auth_failed",
  "graph_permission_denied",
  "auth_failed",
]);

function isExplicitSyncFailureCode(code: string | null | undefined): boolean {
  return Boolean(code && EXPLICIT_SYNC_FAILURE_CODES.has(code.toLowerCase()));
}

function getDiagnosticError(error: unknown): { httpResult: number | null; classifiedErrorCode: string | null } {
  if (!error || typeof error !== "object") {
    return { httpResult: null, classifiedErrorCode: null };
  }
  const candidate = error as { status?: number; code?: string | null };
  return {
    httpResult: typeof candidate.status === "number" ? candidate.status : null,
    classifiedErrorCode: typeof candidate.code === "string" ? candidate.code : null,
  };
}

function logStartupDiagnostic(event: {
  startupState: StartupState;
  attempt: number | null;
  httpResult: number | null;
  classifiedErrorCode: string | null;
  selectedModalMode: DailySyncModalMode | "startup" | "none";
  reason: string;
}): void {
  if (!import.meta.env.DEV) {
    return;
  }
  console.debug("[NEXUS startup]", event);
}

function getLocalDayKey(date = new Date()): string {
  const year = String(date.getFullYear());
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isSameLocalDay(timestamp: string | null | undefined, dayKey: string): boolean {
  if (!timestamp) {
    return false;
  }
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return false;
  }
  return getLocalDayKey(date) === dayKey;
}

function isSameLocalDayAsToday(timestamp: string | null | undefined): boolean {
  return isSameLocalDay(timestamp, getLocalDayKey());
}

function readStoredSyncRecord(): DailySyncRecord | null {
  try {
    const raw = window.localStorage.getItem(DAILY_SYNC_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<DailySyncRecord> & { status?: string };
    if (
      typeof parsed.date !== "string" ||
      typeof parsed.status !== "string" ||
      !["running", "completed", "failed", "timeout"].includes(parsed.status)
    ) {
      return null;
    }
    return {
      date: parsed.date,
      started_at: typeof parsed.started_at === "string" ? parsed.started_at : null,
      completed_at: typeof parsed.completed_at === "string" ? parsed.completed_at : null,
      status: parsed.status as DailySyncRecordStatus,
      last_error: typeof parsed.last_error === "string" ? parsed.last_error : null,
      error_code: typeof parsed.error_code === "string" ? parsed.error_code : null,
    };
  } catch {
    return null;
  }
}

function storeSyncRecord(record: DailySyncRecord): void {
  try {
    window.localStorage.setItem(DAILY_SYNC_STORAGE_KEY, JSON.stringify(record));
  } catch {
    // Ignore storage failures and fall back to in-memory behavior for this session.
  }
}

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<ProjectViewModel[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [dailySync, setDailySync] = useState<DailySyncState | null>(null);
  const [startupState, setStartupState] = useState<StartupState>("starting");
  const [startupError, setStartupError] = useState<string | null>(null);
  const [refreshIndex, setRefreshIndex] = useState(0);
  const [startupRetryIndex, setStartupRetryIndex] = useState(0);
  const startupSnapshotRef = useRef<ApplianceStatusSnapshot | null>(null);
  const dailySyncDismissedRef = useRef(false);
  const retryDailySyncRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    // Effect cleanup cancels this attempt. Allow a fresh setup for StrictMode
    // replay and explicit retries instead of keeping a one-time ref guard.
    let cancelled = false;
    let settled = false;
    const timers: number[] = [];

    const markFailed = (error: unknown) => {
      if (cancelled || settled) {
        return;
      }
      settled = true;
      setStartupState("failed");
      setStartupError(getUserFacingErrorMessage(error, "Status kunne ikke hentes."));
    };

    const attemptStartup = async (attemptIndex: number) => {
      if (cancelled || settled) {
        return;
      }
      const nextState = attemptIndex === 0 ? "starting" : "connecting";
      setStartupState(nextState);
      logStartupDiagnostic({
        startupState: nextState,
        attempt: attemptIndex + 1,
        httpResult: null,
        classifiedErrorCode: null,
        selectedModalMode: "startup",
        reason: "request_started",
      });

      const timeoutPromise = new Promise<"timeout">((resolve) => {
        timers.push(window.setTimeout(() => resolve("timeout"), STARTUP_REQUEST_TIMEOUT_MS));
      });
      const result = await Promise.race([
        Promise.allSettled([getSystemReadiness(), readApplianceStatus()]),
        timeoutPromise,
      ]);
      if (cancelled || settled) {
        return;
      }

      if (result !== "timeout") {
        const [readinessResult, statusResult] = result;
        const readiness = readinessResult.status === "fulfilled" ? readinessResult.value : null;
        const snapshot = statusResult.status === "fulfilled" && isValidStatusSnapshot(statusResult.value) ? statusResult.value : null;
        const permanentError = readinessResult.status === "rejected" && !isRetryableStartupError(readinessResult.reason)
          ? readinessResult.reason
          : statusResult.status === "rejected" && !isRetryableStartupError(statusResult.reason)
            ? statusResult.reason
            : null;
        const explicitFailureCode = getExplicitStartupFailureCode(readiness, snapshot);

        const readinessError = readinessResult.status === "rejected" ? getDiagnosticError(readinessResult.reason) : null;
        const statusError = statusResult.status === "rejected" ? getDiagnosticError(statusResult.reason) : null;
        logStartupDiagnostic({
          startupState: attemptIndex === 0 ? "starting" : "connecting",
          attempt: attemptIndex + 1,
          httpResult: readinessError?.httpResult ?? statusError?.httpResult ?? (readiness && snapshot ? 200 : null),
          classifiedErrorCode: readinessError?.classifiedErrorCode ?? statusError?.classifiedErrorCode ?? null,
          selectedModalMode: "startup",
          reason: permanentError || explicitFailureCode ? "explicit_startup_failure" : snapshot ? "status_received" : "retryable_startup_error",
        });
        if (permanentError || explicitFailureCode) {
          markFailed(permanentError ?? new StartupError("NEXUS startup failed.", explicitFailureCode ?? "startup_failed"));
          return;
        }

        // A successful status round is the signal that the service is usable.
        // Readiness may be unavailable on older backends, so it is advisory.
        if (snapshot && (readiness === null || readiness.ready)) {
          settled = true;
          startupSnapshotRef.current = snapshot;
          setStartupError(null);
          setStartupState("ready");
          logStartupDiagnostic({
            startupState: "ready",
            attempt: attemptIndex + 1,
            httpResult: 200,
            classifiedErrorCode: null,
            selectedModalMode: "none",
            reason: "startup_ready",
          });
          return;
        }
      } else {
        logStartupDiagnostic({
          startupState: attemptIndex === 0 ? "starting" : "connecting",
          attempt: attemptIndex + 1,
          httpResult: 408,
          classifiedErrorCode: "timeout",
          selectedModalMode: "startup",
          reason: "startup_request_timeout",
        });
      }

      if (attemptIndex === STARTUP_RETRY_DELAYS_MS.length - 1) {
        markFailed(new StartupError("NEXUS startup timed out."));
        logStartupDiagnostic({
          startupState: "failed",
          attempt: attemptIndex + 1,
          httpResult: 408,
          classifiedErrorCode: "startup_timeout",
          selectedModalMode: "startup",
          reason: "startup_grace_period_expired",
        });
      }
    };

    STARTUP_RETRY_DELAYS_MS.forEach((delay, attemptIndex) => {
      if (delay === 0) {
        void attemptStartup(attemptIndex);
        return;
      }
      timers.push(window.setTimeout(() => void attemptStartup(attemptIndex), delay));
    });

    return () => {
      cancelled = true;
      settled = true;
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [startupRetryIndex]);

  useEffect(() => {
    if (startupState !== "ready") {
      return undefined;
    }
    const controller = new AbortController();
    setProjectsLoading(true);
    setProjectsError(null);
    setHealthLoading(true);
    setHealthError(null);

    async function loadAppData() {
      try {
        const [projectsResult, healthResult] = await Promise.allSettled([
          Promise.resolve().then(() => getProjects({ includeSampleProjects: showSampleProjectsInUi })),
          Promise.resolve().then(() => getHealth()),
        ]);

        if (controller.signal.aborted) {
          return;
        }

        if (projectsResult.status === "fulfilled") {
          const visibleProjects = filterVisibleProjects(projectsResult.value.projects, showSampleProjectsInUi);
          const viewModels = createProjectViewModels(visibleProjects);
          setProjects(viewModels);
        } else {
          setProjects([]);
          setProjectsError(getUserFacingErrorMessage(projectsResult.reason, "Kunne ikke laste prosjekter."));
        }

        if (healthResult.status === "fulfilled") {
          setHealth(healthResult.value);
        } else {
          setHealth(null);
          setHealthError(getUserFacingErrorMessage(healthResult.reason, "Kunne ikke lese helsestatus."));
        }
      } finally {
        if (!controller.signal.aborted) {
          setProjectsLoading(false);
          setHealthLoading(false);
        }
      }
    }

    void loadAppData();
    return () => {
      controller.abort();
    };
  }, [refreshIndex, startupState]);

  useEffect(() => {
    if (startupState !== "ready") {
      return undefined;
    }
    // Resume polling after a fresh startup setup or development refresh.

    let cancelled = false;
    let pollTimerId: number | undefined;
    let timeoutTimerId: number | undefined;
    let currentRecord: DailySyncRecord | null = readStoredSyncRecord();

    const clearPollTimer = () => {
      if (pollTimerId !== undefined) {
        window.clearTimeout(pollTimerId);
        pollTimerId = undefined;
      }
    };

    const clearTimeoutTimer = () => {
      if (timeoutTimerId !== undefined) {
        window.clearTimeout(timeoutTimerId);
        timeoutTimerId = undefined;
      }
    };

    const clearTimers = () => {
      clearPollTimer();
      clearTimeoutTimer();
    };

    const setModal = (state: DailySyncState | null, reason = state ? `modal_${state.mode}` : "modal_closed") => {
      if (dailySyncDismissedRef.current && state !== null) {
        return;
      }
      setDailySync(state);
      logStartupDiagnostic({
        startupState: "ready",
        attempt: null,
        httpResult: null,
        classifiedErrorCode: state?.errorCode ?? null,
        selectedModalMode: state?.mode ?? "none",
        reason,
      });
    };

    const persistRecord = (record: DailySyncRecord) => {
      currentRecord = record;
      storeSyncRecord(record);
    };

    const clearStoredRecord = () => {
      currentRecord = null;
      try {
        window.localStorage.removeItem(DAILY_SYNC_STORAGE_KEY);
      } catch {
        // Ignore storage failures and fall back to in-memory behavior for this session.
      }
    };

    const showRunningModal = (detail: string | null = DAILY_SYNC_BACKGROUND_MESSAGE, message = DAILY_SYNC_MESSAGE) => {
      setModal({
        mode: "onboarding",
        title: DAILY_SYNC_ONBOARDING_TITLE,
        message,
        detail,
      }, "sync_running");
    };

    const showBusyModal = () => {
      showRunningModal(null, APPLIANCE_BUSY_MESSAGE);
    };

    const showTimeoutModal = (detail = "OneDrive synkroniserer fortsatt i bakgrunnen.") => {
      setModal({
        mode: "warning",
        title: "OneDrive-synkronisering tar tid",
        message: DAILY_SYNC_TIMEOUT_MESSAGE,
        detail,
      }, "sync_timeout_warning");
    };

    const showFailureModal = (detail: string, errorCode: string) => {
      if (!isExplicitSyncFailureCode(errorCode)) {
        return;
      }
      const safeMessage = getUserFacingErrorMessage(
        { code: errorCode, rawMessage: detail },
        "Synkroniseringen kunne ikke fullføres.",
      );
      setModal({
        mode: "fatal",
        title: DAILY_SYNC_FAILED_MESSAGE,
        message: safeMessage,
        detail: null,
        errorCode,
      }, "explicit_sync_failure");
    };

    const schedulePoll = (delayMs = DAILY_SYNC_POLL_INTERVAL_MS) => {
      clearPollTimer();
      pollTimerId = window.setTimeout(() => {
        pollTimerId = undefined;
        void pollSyncStatus();
      }, delayMs);
    };

    const scheduleTimeout = () => {
      if (timeoutTimerId !== undefined || currentRecord?.status !== "running") {
        return;
      }
      timeoutTimerId = window.setTimeout(() => {
        timeoutTimerId = undefined;
        if (cancelled || !currentRecord || currentRecord.status !== "running") {
          return;
        }
        persistRecord({
          ...currentRecord,
          status: "timeout",
          completed_at: null,
        });
        showTimeoutModal();
      }, DAILY_SYNC_TIMEOUT_MS);
    };

    async function pollSyncStatus() {
      if (cancelled) {
        return;
      }

      try {
        const { syncStatus, analysisStatus } = await readApplianceStatus();
        if (cancelled) {
          return;
        }

        const { syncRunning, analysisRunning } = resolveLiveApplianceActivity(syncStatus, analysisStatus);
        const analysisStartupBusy = analysisStatus.status === "startup_pending" || analysisStatus.startup_grace_active;
        const anyLiveLock = syncStatus.lock_exists || analysisStatus.lock_exists || analysisStartupBusy;

        if (syncRunning) {
          const startedAt = syncStatus.last_started_at ?? currentRecord?.started_at ?? new Date().toISOString();
          const nextRecord: DailySyncRecord = {
            date: currentRecord?.date ?? getLocalDayKey(new Date(startedAt)),
            started_at: startedAt,
            completed_at: null,
            status: currentRecord?.status === "timeout" ? "timeout" : "running",
            last_error: null,
          };
          if (
            !currentRecord ||
            currentRecord.started_at !== nextRecord.started_at ||
            currentRecord.status !== nextRecord.status ||
            currentRecord.date !== nextRecord.date
          ) {
            persistRecord(nextRecord);
          }
          if (nextRecord.status === "timeout") {
            showTimeoutModal();
          } else {
            showRunningModal();
            scheduleTimeout();
          }
          schedulePoll();
          return;
        }

        if (analysisRunning || anyLiveLock) {
          if (currentRecord?.status === "failed" && isLockBusyError(currentRecord.last_error)) {
            clearStoredRecord();
          }
          showBusyModal();
          schedulePoll();
          return;
        }

        const normalizedStatus = syncStatus.status.trim().toLowerCase();
        const startedAt = syncStatus.last_started_at ?? currentRecord?.started_at ?? null;
        const completedAt = syncStatus.last_completed_at ?? new Date().toISOString();
        const backendLockError = isLockBusyError(syncStatus.last_error);
        const storedLockError = isLockBusyError(currentRecord?.last_error);

        if (backendLockError || storedLockError) {
          clearStoredRecord();
          clearTimers();
          setDailySync(null);
          return;
        }

        const explicitFailureCode = syncStatus.error_code ?? analysisStatus.error_code ?? null;
        if (isExplicitSyncFailureCode(explicitFailureCode)) {
          const detail = syncStatus.last_error ?? currentRecord?.last_error ?? "Kunne ikke fullføre OneDrive-synkronisering.";
          persistRecord({
            date: currentRecord?.date ?? getLocalDayKey(),
            started_at: startedAt,
            completed_at: completedAt,
            status: "failed",
            last_error: detail,
            error_code: explicitFailureCode,
          });
          clearTimers();
          showFailureModal(detail, explicitFailureCode ?? "sync_failed");
          return;
        }

        // A status string or last_error without a classified code is not enough
        // to tell the user that synchronization failed. Treat it as stale or
        // incomplete backend state and let the next explicit status decide.
        if (normalizedStatus.includes("fail") || normalizedStatus.includes("error") || syncStatus.last_error) {
          clearStoredRecord();
          clearTimers();
          setModal(null, "unclassified_sync_status_ignored");
          return;
        }

        if (normalizedStatus.includes("complete") || normalizedStatus.includes("skipped") || Boolean(syncStatus.last_completed_at)) {
          persistRecord({
            date: currentRecord?.date ?? getLocalDayKey(),
            started_at: startedAt,
            completed_at: completedAt,
            status: "completed",
            last_error: null,
          });
          clearTimers();
          if (!dailySyncDismissedRef.current) {
            setDailySync(null);
          }
          setRefreshIndex((value) => value + 1);
          return;
        }

        if (currentRecord?.status === "timeout") {
          showTimeoutModal();
          schedulePoll(DAILY_SYNC_POLL_INTERVAL_MS);
          return;
        }

        if (currentRecord?.status === "running") {
          clearStoredRecord();
          clearTimers();
          setModal(null, "sync_stopped_without_explicit_error");
          return;
        }

        clearTimers();
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (currentRecord?.status === "timeout") {
          showTimeoutModal(getUserFacingErrorMessage(error, "Status kunne ikke hentes."));
        } else {
          // Keep the running spinner visible. Transport errors are not sync
          // failures and must not become a blocking error modal.
          showRunningModal();
        }
        schedulePoll(DAILY_SYNC_POLL_INTERVAL_MS);
      }
    }

    async function startNewDailySync(todayKey: string) {
      dailySyncDismissedRef.current = false;
      setModal({
        mode: "onboarding",
        title: DAILY_SYNC_ONBOARDING_TITLE,
        message: DAILY_SYNC_MESSAGE,
        detail: "Klargjør OneDrive-synkronisering ...",
      }, "sync_start_requested");

      try {
        const response = await runSync();
        if (cancelled) {
          return;
        }

        const startedAt = response.started_at;
        const runningRecord: DailySyncRecord = {
          date: todayKey,
          started_at: startedAt,
          completed_at: null,
          status: "running",
          last_error: null,
        };
        persistRecord(runningRecord);
        showRunningModal(response.status === "already_running" ? "OneDrive synkroniseres allerede ..." : DAILY_SYNC_BACKGROUND_MESSAGE);
        scheduleTimeout();
        schedulePoll();
      } catch (error) {
        if (cancelled) {
          return;
        }

        try {
          const { syncStatus, analysisStatus } = await readApplianceStatus();
          if (cancelled) {
            return;
          }

          const { syncRunning, analysisRunning } = resolveLiveApplianceActivity(syncStatus, analysisStatus);
          const anyLiveLock = syncStatus.lock_exists || analysisStatus.lock_exists;
          const explicitFailureCode = syncStatus.error_code ?? analysisStatus.error_code ?? null;

          if (isExplicitSyncFailureCode(explicitFailureCode)) {
            showFailureModal(syncStatus.last_error ?? analysisStatus.last_error ?? "Kunne ikke fullføre OneDrive-synkronisering.", explicitFailureCode ?? "sync_failed");
            return;
          }

          if (syncRunning) {
            const startedAt = syncStatus.last_started_at ?? new Date().toISOString();
            persistRecord({
              date: todayKey,
              started_at: startedAt,
              completed_at: null,
              status: "running",
              last_error: null,
            });
            showRunningModal();
            scheduleTimeout();
            schedulePoll();
            return;
          }

          if (analysisRunning || anyLiveLock) {
            showBusyModal();
            schedulePoll();
            return;
          }
        } catch {
          // fall through to error handling below
        }

        if (error instanceof Error && error.message === APPLIANCE_BUSY_MESSAGE) {
          clearStoredRecord();
          showBusyModal();
          schedulePoll();
          return;
        }

        if (error instanceof Error && isLockBusyError(error.message)) {
          clearStoredRecord();
          setModal({
            mode: "warning",
            title: "Synkronisering ikke fullført",
            message: "OneDrive-synkroniseringen ble ikke fullført.",
            detail: SYNC_STALE_LOCK_WARNING,
          }, "stale_lock_warning");
          return;
        }

        const errorCode = error && typeof error === "object" && "code" in error && typeof error.code === "string" ? error.code : null;
        if (isExplicitSyncFailureCode(errorCode)) {
          const rawMessage = error instanceof Error ? error.message : "Kunne ikke starte OneDrive-synkronisering.";
          showFailureModal(rawMessage, errorCode ?? "sync_failed");
          return;
        }

        // A generic 500/timeout/connection failure is recoverable. It must not
        // be presented as a OneDrive sync failure after startup is ready.
        clearStoredRecord();
        clearTimers();
        setModal(null, "generic_sync_start_error_ignored");
      }
    }

    async function bootstrapDailySync(initialSnapshot: ApplianceStatusSnapshot | null) {
      const todayKey = getLocalDayKey();
      const storedRecord = currentRecord;

      try {
        const { syncStatus, analysisStatus } = initialSnapshot ?? await readApplianceStatus();
        if (cancelled) {
          return;
        }

        const backendLockError = isLockBusyError(syncStatus.last_error);
        const storedLockError = isLockBusyError(storedRecord?.last_error);
        const activeStoredRecord = backendLockError || storedLockError ? null : storedRecord;
        const { syncRunning, analysisRunning } = resolveLiveApplianceActivity(syncStatus, analysisStatus);
        const anyLiveLock = syncStatus.lock_exists || analysisStatus.lock_exists;

        if (syncRunning) {
          const record: DailySyncRecord = activeStoredRecord?.date === todayKey && activeStoredRecord.status === "timeout"
            ? activeStoredRecord
            : {
                date: todayKey,
                started_at: syncStatus.last_started_at ?? activeStoredRecord?.started_at ?? new Date().toISOString(),
                completed_at: null,
                status: activeStoredRecord?.status === "timeout" ? "timeout" : "running",
                last_error: null,
              };
          persistRecord(record);
          if (record.status === "timeout") {
            showTimeoutModal();
          } else {
            showRunningModal();
            scheduleTimeout();
          }
          schedulePoll();
          return;
        }

        if (analysisRunning || anyLiveLock) {
          if (storedRecord?.status === "failed" && storedLockError) {
            clearStoredRecord();
          }
          showBusyModal();
          schedulePoll();
          return;
        }

        if (backendLockError || storedLockError) {
          clearStoredRecord();
        }

        const normalizedStatus = syncStatus.status.trim().toLowerCase();
        const backendVisibleError = backendLockError ? null : syncStatus.last_error;
        const backendCompletedToday = Boolean(syncStatus.last_completed_at && isSameLocalDayAsToday(syncStatus.last_completed_at));
        const backendStartedToday = Boolean(syncStatus.last_started_at && isSameLocalDayAsToday(syncStatus.last_started_at));
        const explicitFailureCode = syncStatus.error_code ?? analysisStatus.error_code ?? null;
        const backendFailed = !backendLockError && isExplicitSyncFailureCode(explicitFailureCode);

        if (backendFailed) {
          const detail = backendVisibleError ?? "Kunne ikke fullføre OneDrive-synkroniseringen.";
          persistRecord({
            date: todayKey,
            started_at: syncStatus.last_started_at ?? activeStoredRecord?.started_at ?? null,
            completed_at: syncStatus.last_completed_at ?? new Date().toISOString(),
            status: "failed",
            last_error: detail,
            error_code: explicitFailureCode,
          });
          showFailureModal(detail, explicitFailureCode ?? "sync_failed");
          return;
        }

        if (normalizedStatus.includes("fail") || normalizedStatus.includes("error") || backendVisibleError) {
          // Older backends persisted a failed status without an error code. It
          // is not evidence of a current sync failure and must not resurrect a
          // stale blocking modal on the next page load.
          clearStoredRecord();
        }

        if (backendCompletedToday) {
          persistRecord({
            date: todayKey,
            started_at: syncStatus.last_started_at ?? activeStoredRecord?.started_at ?? null,
            completed_at: syncStatus.last_completed_at ?? new Date().toISOString(),
            status: "completed",
            last_error: null,
          });
          if (activeStoredRecord?.status === "running" || activeStoredRecord?.status === "timeout") {
            setRefreshIndex((value) => value + 1);
          }
          return;
        }

        if (activeStoredRecord?.date === todayKey) {
          if (activeStoredRecord.status === "completed") {
            return;
          }
          if (activeStoredRecord.status === "failed") {
            if (isExplicitSyncFailureCode(activeStoredRecord.error_code)) {
              showFailureModal(activeStoredRecord.last_error ?? "Kunne ikke fullføre OneDrive-synkroniseringen.", activeStoredRecord.error_code ?? "sync_failed");
              return;
            }
            clearStoredRecord();
          }
          if (activeStoredRecord.status === "timeout") {
            showTimeoutModal();
            schedulePoll();
            return;
          }
          if (activeStoredRecord.status === "running") {
            showRunningModal();
            scheduleTimeout();
            schedulePoll();
            return;
          }
        }

        if (backendStartedToday && !backendLockError && !storedLockError) {
          return;
        }

        await startNewDailySync(todayKey);
      } catch (error) {
        if (cancelled) {
          return;
        }
        const errorCode = error && typeof error === "object" && "code" in error && typeof error.code === "string" ? error.code : null;
        if (isExplicitSyncFailureCode(errorCode)) {
          showFailureModal(error instanceof Error ? error.message : "Kunne ikke fullføre OneDrive-synkroniseringen.", errorCode ?? "sync_failed");
          return;
        }
        clearStoredRecord();
        setModal(null, "generic_sync_status_error_ignored");
      }
    }

    retryDailySyncRef.current = () => {
      if (cancelled) {
        return;
      }
      dailySyncDismissedRef.current = false;
      clearTimers();
      clearStoredRecord();
      void startNewDailySync(getLocalDayKey());
    };

    const initialSnapshot = startupSnapshotRef.current;
    startupSnapshotRef.current = null;
    if (import.meta.env.VITE_NEXUS_AUTO_SYNC !== "false") void bootstrapDailySync(initialSnapshot);
    return () => {
      cancelled = true;
      clearTimers();
      retryDailySyncRef.current = null;
    };
  }, [startupState]);

  const projectWarnings = useMemo(
    () =>
      Array.from(new Set(projects.flatMap((project) => project.issues.map((issue) => issue.message)).filter((message) => message.trim().length > 0))),
    [projects],
  );

  const dismissDailySync = () => {
    dailySyncDismissedRef.current = true;
    setDailySync(null);
  };

  const retryDailySync = () => {
    retryDailySyncRef.current?.();
  };

  const retryStartup = () => {
    startupSnapshotRef.current = null;
    setDailySync(null);
    setStartupError(null);
    setStartupState("starting");
    setStartupRetryIndex((value) => value + 1);
  };

  const value: AppDataContextValue = {
    projects,
    projectsLoading,
    projectsError,
    projectWarnings,
    health,
    healthLoading,
    healthError,
    dailySync,
    dismissDailySync,
    retryDailySync,
    startupState,
    startupError,
    retryStartup,
    refresh: () => setRefreshIndex((value) => value + 1),
    removeProjectByName: (projectName: string) =>
      setProjects((current) => current.filter((project) => project.projectName !== projectName)),
  };

  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>;
}

export function useAppData(): AppDataContextValue {
  const context = useContext(AppDataContext);
  if (context === null) {
    throw new Error("useAppData must be used within AppDataProvider");
  }
  return context;
}
