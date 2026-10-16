import { useEffect, useRef, useState } from "react";
import { IconRefresh, IconChevronDown, IconArrowUpRight, IconDots } from "@tabler/icons-react";
import { Link } from "react-router-dom";
import { AppHeader } from "../components/Layout";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import { ApiRequestError, formatDateTime, getAnalysisStatus, getSyncStatus, getUserFacingErrorMessage, runSync } from "../lib/api";
import {
  ANALYSIS_RUNNING_LABEL,
  APPLIANCE_BUSY_MESSAGE,
  APPLIANCE_BUSY_LABEL,
  APPLIANCE_CLEAR_MESSAGE,
  SYNC_FAILED_LABEL,
  SYNC_LOCK_HELP_TEXT,
  SYNC_RUNNING_LABEL,
  getVisibleSyncErrorMessage,
  isLockBusyError,
} from "../lib/applianceStatus";
import { sortProjectsByActivity, type ProjectViewModel } from "../lib/projects";
import { useAppData } from "../context/AppDataContext";
import { StatusPill } from "../components/StatusPill";
import { CopyLinkButton } from "../components/CopyLinkButton";
import type { AnalysisStatusResponse, HealthResponse, SyncStatusResponse } from "../types";

export { getVisibleSyncErrorMessage as getSyncLastErrorMessage, isLockBusyError as isSyncBusyLockError } from "../lib/applianceStatus";

const SYNC_START_DESCRIPTION = "Starter en trygg OneDrive-sync uten rapportgenerering.";

export function resolveDashboardLastSyncedAt(syncStatus: SyncStatusResponse | null, health: HealthResponse | null): string | null {
  return syncStatus?.last_completed_at ?? health?.last_synced_at ?? null;
}

export function isSyncStatusForCurrentJob(status: SyncStatusResponse, currentJobId: string | null): boolean {
  return currentJobId === null || status.job_id === currentJobId;
}

export function DashboardPage() {
  const { projects, projectsLoading, projectsError, health, healthLoading, healthError, refresh, startupState } = useAppData();
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatusResponse | null>(null);
  const [syncBusyLive, setSyncBusyLive] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const syncStartupAtRef = useRef<number | null>(null);
  const syncJobIdRef = useRef<string | null>(null);
  const visibleProjects = sortProjectsByActivity(projects);
  const isInitialProjectsLoad = projectsLoading && visibleProjects.length === 0;
  const applianceStatus = startupState && startupState !== "ready" ? "loading" : healthLoading ? "loading" : health?.appliance_available ? "online" : "offline";
  const applianceLabel = startupState === "starting" ? "Starter …" : startupState === "connecting" ? "Kobler til …" : healthLoading ? "Laster" : health?.appliance_available ? "Klar" : "offline";
  const metrics = buildDashboardMetrics(visibleProjects);
  const analysisStartupBusy = analysisStatus?.status === "startup_pending" || analysisStatus?.startup_grace_active === true;
  const syncRunningFromStatus = Boolean(
    syncStatus?.running ||
      syncStatus?.process_alive ||
      syncStatus?.status === "startup_pending" ||
      (syncStatus?.job_type === "sync" && syncStatus?.activity === "sync"),
  );
  const analysisRunningFromStatus = Boolean(analysisStatus?.running || analysisStatus?.process_alive || analysisStartupBusy);
  const applianceActivity = syncRunningFromStatus || syncBusyLive ? "sync" : analysisRunningFromStatus ? "analysis" : "idle";
  const syncHasStaleLock = Boolean(syncStatus?.last_error && isLockBusyError(syncStatus.last_error));
  const applianceBusy =
    syncBusyLive || syncRunningFromStatus || analysisRunningFromStatus || syncStatus?.lock_exists === true || analysisStatus?.lock_exists === true;
  const startupLabel = startupState === "starting" ? "Starter …" : startupState === "connecting" ? "Kobler til …" : null;
  const explicitSyncFailure = Boolean(syncStatus?.error_code && ["sync_failed", "project_sync_failed", "onedrive_sync_failed", "graph_auth_failed", "graph_permission_denied", "auth_failed"].includes(syncStatus.error_code));
  const syncPillStatus = startupLabel ? "RUNNING" : applianceBusy ? "RUNNING" : syncHasStaleLock ? "idle" : explicitSyncFailure ? "FAILED" : "idle";
  const syncPillLabel = startupLabel ?? (applianceBusy
    ? applianceActivity === "sync"
      ? syncStatus?.current_phase ?? SYNC_RUNNING_LABEL
      : applianceActivity === "analysis"
        ? ANALYSIS_RUNNING_LABEL
        : APPLIANCE_BUSY_LABEL
    : syncHasStaleLock
      ? APPLIANCE_CLEAR_MESSAGE
      : explicitSyncFailure
        ? SYNC_FAILED_LABEL
        : APPLIANCE_CLEAR_MESSAGE);
  const syncButtonDisabled = applianceBusy;
  const syncButtonTitle = applianceBusy ? SYNC_LOCK_HELP_TEXT : SYNC_START_DESCRIPTION;
  const syncLastErrorMessage = !syncBusyLive && (explicitSyncFailure || syncHasStaleLock)
    ? getVisibleSyncErrorMessage(syncStatus?.last_error, syncStatus?.error_code)
    : null;
  const syncLastErrorTone = syncStatus?.last_error && isLockBusyError(syncStatus.last_error) ? "warning" : "error";
  const busyActionNote = applianceBusy ? SYNC_LOCK_HELP_TEXT : null;
  const dashboardLastSyncedAt = resolveDashboardLastSyncedAt(syncStatus, health);
  const recentReports = visibleProjects
    .filter((project) => project.latestReport !== null)
    .sort((left, right) => {
      const leftTime = left.latestReport?.createdAt ? Date.parse(left.latestReport.createdAt) : 0;
      const rightTime = right.latestReport?.createdAt ? Date.parse(right.latestReport.createdAt) : 0;
      return rightTime - leftTime;
    })
    .slice(0, 8);

  useEffect(() => {
    if (startupState && startupState !== "ready") {
      return undefined;
    }
    let cancelled = false;
    let timer: number | undefined;
    let latestSyncStatus = syncStatus;
    let latestAnalysisStatus = analysisStatus;

    async function pollApplianceStatus() {
      const [syncResult, analysisResult] = await Promise.allSettled([getSyncStatus(), getAnalysisStatus()]);
      if (cancelled) {
        return;
      }

      if (syncResult.status === "fulfilled") {
        const belongsToCurrentJob = isSyncStatusForCurrentJob(syncResult.value, syncJobIdRef.current);
        if (belongsToCurrentJob) {
          latestSyncStatus = syncResult.value;
          setSyncStatus(syncResult.value);
          setSyncError(null);
        } else {
          latestSyncStatus = null;
        }
      } else {
        setSyncError(getUserFacingErrorMessage(syncResult.reason, "Status kunne ikke hentes."));
      }

      if (analysisResult.status === "fulfilled") {
        latestAnalysisStatus = analysisResult.value;
        setAnalysisStatus(analysisResult.value);
      } else {
        console.error("[DashboardPage] getAnalysisStatus failed", analysisResult.reason);
      }

      const busyFromStatuses = Boolean(
        latestSyncStatus?.running ||
          latestSyncStatus?.process_alive ||
          latestAnalysisStatus?.running ||
          latestAnalysisStatus?.process_alive ||
          latestAnalysisStatus?.status === "startup_pending" ||
          latestAnalysisStatus?.startup_grace_active,
      );
      const syncStartupGraceActive = Boolean(
        syncBusyLive &&
          syncStartupAtRef.current !== null &&
          Date.now() - syncStartupAtRef.current < 10_000,
      );
      const busy = busyFromStatuses || syncBusyLive;
      const currentJobStatusReceived = !syncJobIdRef.current || latestSyncStatus?.job_id === syncJobIdRef.current;
      if (!busyFromStatuses && syncBusyLive && currentJobStatusReceived && !syncStartupGraceActive) {
        setSyncBusyLive(false);
        syncStartupAtRef.current = null;
      }
      timer = window.setTimeout(pollApplianceStatus, busy ? 3000 : 30000);
    }

    void pollApplianceStatus();
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [startupState, syncBusyLive]);

  async function handleRunSync() {
    const idempotencyKey = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `sync-${Date.now()}`;
    syncStartupAtRef.current = Date.now();
    setSyncBusyLive(true);
    setSyncError(null);
    setSyncMessage("Starter synkronisering ...");
    let syncStarted = false;
    try {
      const response = await runSync({ idempotencyKey });
      syncStarted = true;
      syncJobIdRef.current = response.job_id;
      if (response.status === "already_running") {
        setSyncBusyLive(true);
      }
      setSyncMessage(response.status === "already_running" ? "OneDrive-synkronisering kjører allerede." : "Synkronisering startet. Venter på første status ...");
      try {
        setSyncStatus(await getSyncStatus());
        setSyncError(null);
      } catch (error) {
        setSyncError(getUserFacingErrorMessage(error, "Status kunne ikke hentes."));
      }
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 503 && error.message === APPLIANCE_BUSY_MESSAGE) {
        setSyncBusyLive(false);
        syncStartupAtRef.current = null;
        syncJobIdRef.current = null;
        setSyncError(null);
        setSyncMessage(APPLIANCE_BUSY_MESSAGE);
        return;
      }
      setSyncMessage(getUserFacingErrorMessage(error, "Kunne ikke starte OneDrive-sync."));
      setSyncBusyLive(false);
      syncStartupAtRef.current = null;
    } finally {
      if (syncStarted) {
        refresh();
      }
    }
  }

  if (projectsError) {
    return <ErrorState title="Kunne ikke laste dashboardet" description={projectsError} />;
  }

  return (
    <div className="page-stack dashboard-page">
      <AppHeader
        title="Kontrollsenter"
        description="Prosjekter, rapporter og drift — samlet på ett sted."
        eyebrow={null}
      />

      <section className="dashboard-connection" aria-label="Driftsstatus">
        <div className="dashboard-connection__main">
          <div className="dashboard-connection__service">
            <StatusPill status={applianceStatus} label={`Appliance ${applianceLabel.toLowerCase()}`} />
            <span className="dashboard-connection__caption">{applianceBusy ? "En jobb pågår" : "Klar for arbeid"}</span>
          </div>
          <div className="dashboard-connection__sync">
            <StatusPill status={syncPillStatus} label={syncPillLabel === "Klar" ? "OneDrive klar" : syncPillLabel} />
            <span className="dashboard-connection__caption">Sist synk fullført: {dashboardLastSyncedAt ? formatDateTime(dashboardLastSyncedAt) : "Ukjent"}</span>
          </div>
          <div className="dashboard-actions__stack">
            <button
              type="button"
              className={`button${applianceBusy ? " button--muted" : ""}`}
              onClick={() => void handleRunSync()}
              disabled={syncButtonDisabled}
              title={syncButtonTitle}
              aria-label={`Synk OneDrive. ${syncButtonTitle}`}
            >
              <IconRefresh size={18} stroke={1.7} aria-hidden="true" />
              Synk OneDrive
            </button>
            {busyActionNote ? <div className="dashboard-actions__note dashboard-actions__note--warning">{busyActionNote}</div> : null}
          </div>
        </div>
        <details className="dashboard-sync-disclosure">
          <summary>Synkroniseringsdetaljer <IconChevronDown size={14} stroke={1.7} aria-hidden="true" /></summary>
        <div className="dashboard-sync-details">
          <span>Siste analyse: {metrics.lastAnalyzedAt ? formatDateTime(metrics.lastAnalyzedAt) : "Ingen analyse"}</span>
          <span>Siste rapport: {metrics.latestReportAt ? formatDateTime(metrics.latestReportAt) : "Ingen rapport"}</span>
          <span>Siste sync-start: {syncStatus?.last_started_at ? formatDateTime(syncStatus.last_started_at) : "Ikke kjørt fra portal"}</span>
          <span>Siste sync-ferdig: {syncStatus?.last_completed_at ? formatDateTime(syncStatus.last_completed_at) : "—"}</span>
          {syncStatus?.current_phase ? <span>Fase: {syncStatus.current_phase}</span> : null}
          {syncStatus?.current_project ? <span>Prosjekt: {syncStatus.current_project}</span> : null}
          {syncStatus?.progress !== null && syncStatus?.progress !== undefined ? <span>Fremdrift: {Math.round(syncStatus.progress)}%</span> : null}
          {syncStatus?.sync_strategy && syncStatus.sync_strategy !== "unknown" ? <span>Strategi: {formatSyncStrategy(syncStatus.sync_strategy)}</span> : null}
          {syncStatus?.sync_strategy && syncStatus.sync_strategy !== "unknown" ? <span>{syncStrategyDescription(syncStatus.sync_strategy)}</span> : null}
          {syncStatus?.sync_strategy_reason ? <span>Strategiårsak: {syncStatus.sync_strategy_reason}</span> : null}
          <span>Endrede filer siste sync: {syncStatus?.files_changed !== undefined ? syncStatus.files_changed.toLocaleString("nb-NO") : "0"}</span>
          <span>Filer lastet ned: {syncStatus?.files_downloaded !== undefined ? syncStatus.files_downloaded.toLocaleString("nb-NO") : "0"}</span>
          <span>Filer slettet: {syncStatus?.files_deleted !== undefined ? syncStatus.files_deleted.toLocaleString("nb-NO") : "0"}</span>
          <span>Remote-elementer: {syncStatus?.remote_items_examined !== undefined ? syncStatus.remote_items_examined.toLocaleString("nb-NO") : "0"}</span>
          <span>Rapporter funnet: {syncStatus?.reports_found !== undefined ? syncStatus.reports_found.toLocaleString("nb-NO") : "0"}</span>
        </div>
        {syncStatus?.performance ? (
          <details className="dashboard-sync-performance">
            <summary>Vis sync-ytelse</summary>
            <div>
              {syncStatus.performance.total_duration_seconds !== null && syncStatus.performance.total_duration_seconds !== undefined
                ? `Total tid: ${syncStatus.performance.total_duration_seconds.toFixed(1)} s`
                : "Total tid: —"}
              {syncStatus.performance.authentication_seconds !== null && syncStatus.performance.authentication_seconds !== undefined
                ? ` · Auth: ${syncStatus.performance.authentication_seconds.toFixed(1)} s`
                : ""}
              {syncStatus.performance.graph_query_seconds !== null && syncStatus.performance.graph_query_seconds !== undefined
                ? ` · Graph: ${syncStatus.performance.graph_query_seconds.toFixed(1)} s`
                : ""}
              {syncStatus.performance.downloads_seconds !== null && syncStatus.performance.downloads_seconds !== undefined
                ? ` · Nedlasting: ${syncStatus.performance.downloads_seconds.toFixed(1)} s`
                : ""}
            </div>
          </details>
        ) : null}
        </details>
        {healthError ? <div className="inline-note inline-note--error">{healthError}</div> : null}
        {syncError ? <div className="inline-note inline-note--error">{syncError}</div> : null}
        {syncLastErrorMessage ? (
          <div className={syncLastErrorTone === "warning" ? "inline-note inline-note--warning" : "inline-note inline-note--error"}>{syncLastErrorMessage}</div>
        ) : null}
        {syncMessage ? <div className="inline-note">{syncMessage}</div> : null}
      </section>

      <section className="dashboard-overview" aria-label="Dashboardnøkkeltall">
        <div className="dashboard-metrics">
          <MetricCard label="Prosjekter totalt" value={metrics.totalProjects.toLocaleString("nb-NO")} />
          <MetricCard label="Filer" value={metrics.totalFiles.toLocaleString("nb-NO")} />
          <MetricCard label="Rapporter" value={metrics.totalReports.toLocaleString("nb-NO")} />
        </div>
        <div className="dashboard-overview__notes">
          <span className={metrics.projectsWithoutReport > 0 ? "dashboard-overview__warning" : ""}>Uten rapport: <strong>{metrics.projectsWithoutReport.toLocaleString("nb-NO")}</strong></span>
          <span>Med varsler: <strong>{metrics.projectsWithWarnings.toLocaleString("nb-NO")}</strong></span>
          <span>Analysert siste 24t: <strong>{metrics.analyzedLast24Hours.toLocaleString("nb-NO")}</strong></span>
        </div>
      </section>

      <section className="dashboard-reports">
        <div className="section-head">
          <div>
            <h2 className="section-title">Seneste rapporter</h2>
          </div>
          <Link className="text-link" to="/projects">Se alle prosjekter <IconArrowUpRight size={16} stroke={1.7} aria-hidden="true" /></Link>
        </div>

        {isInitialProjectsLoad ? (
          <div className="loading-copy">Laster prosjekter …</div>
        ) : recentReports.length > 0 ? (
          <div className="dashboard-reports__table-wrap">
            <table className="dashboard-reports__table" aria-label="Seneste rapporter">
              <thead><tr><th>Prosjekt</th><th>Dokument</th><th>Dato</th><th>Status</th><th>Handlinger</th></tr></thead>
              <tbody>
                {recentReports.map((project) => (
                  <tr key={project.projectName}>
                    <td><Link className="dashboard-reports__project" to={project.projectHref}>{project.displayName}</Link><span className="dashboard-reports__subline">{project.fileCountLabel}</span></td>
                    <td><span className="dashboard-reports__document" title={project.latestReport?.name}>{displayReportName(project)}</span><span className="dashboard-reports__subline">Kommentardokument</span></td>
                    <td className="dashboard-reports__date">{project.latestReport?.createdAt ? formatDateTime(project.latestReport.createdAt) : "Tidspunkt ukjent"}</td>
                    <td><StatusPill status={project.status.level} /></td>
                    <td>
                      <div className="dashboard-reports__actions">
                        {project.latestReport?.openUrl ? <a className="button button--subtle" aria-label={`Åpne kommentardokument for ${project.displayName}`} href={project.latestReport.openUrl} target="_blank" rel="noreferrer">Åpne rapport <IconArrowUpRight size={16} stroke={1.7} aria-hidden="true" /></a> : null}
                        <Link className="text-link dashboard-reports__project-action" to={project.projectHref}>Åpne prosjekt</Link>
                        {project.latestReport?.openUrl ? <details className="row-menu"><summary aria-label={`Flere valg for ${project.displayName}`}><IconDots size={18} aria-hidden="true" /></summary><div className="row-menu__panel"><CopyLinkButton href={project.latestReport.openUrl} /></div></details> : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Ingen rapporter" description="Dashboardet har ingen rapporter å vise akkurat nå." />
        )}
      </section>
      <footer className="workspace-footer"><span>Urban Reuse Norway</span><Link className="text-link" to="/activity">Se aktivitet <IconArrowUpRight size={14} stroke={1.7} aria-hidden="true" /></Link></footer>
    </div>
  );
}

function displayReportName(project: ProjectViewModel): string {
  const name = project.latestReport?.name ?? "Rapport";
  const prefix = `${project.projectName} - `;
  return name.startsWith(prefix) ? name.slice(prefix.length) : name;
}

function MetricCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "warning";
}) {
  return (
    <div className={`metric-card metric-card--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function buildDashboardMetrics(projects: ProjectViewModel[]) {
  const now = Date.now();
  const oneDay = 24 * 60 * 60 * 1000;
  const newest = (values: Array<string | null>) =>
    values.reduce<string | null>((latest, value) => {
      if (!value) {
        return latest;
      }
      if (!latest || Date.parse(value) > Date.parse(latest)) {
        return value;
      }
      return latest;
    }, null);

  return {
    totalProjects: projects.length,
    projectsWithWarnings: projects.filter((project) => project.hasWarnings || project.hasErrors).length,
    projectsWithoutReport: projects.filter((project) => project.reportCount === 0).length,
    analyzedLast24Hours: projects.filter((project) => project.lastAnalyzedAt && now - Date.parse(project.lastAnalyzedAt) <= oneDay).length,
    totalFiles: projects.reduce((sum, project) => sum + project.fileCount, 0),
    totalReports: projects.reduce((sum, project) => sum + project.reportCount, 0),
    lastAnalyzedAt: newest(projects.map((project) => project.lastAnalyzedAt)),
    latestReportAt: newest(projects.map((project) => project.latestReport?.createdAt ?? null)),
  };
}

function formatSyncStrategy(strategy: string): string {
  if (strategy === "delta") {
    return "Delta · kun endringer";
  }
  if (strategy === "fallback_full") {
    return "Fallback full";
  }
  if (strategy === "full") {
    return "Full";
  }
  return strategy;
}

function syncStrategyDescription(strategy: string): string {
  if (strategy === "delta") {
    return "Henter kun endringer siden forrige synkronisering.";
  }
  if (strategy === "full" || strategy === "fallback_full") {
    return "Full gjennomgang av OneDrive pågår. Dette tar lengre tid enn en vanlig endringssynkronisering.";
  }
  return "";
}
