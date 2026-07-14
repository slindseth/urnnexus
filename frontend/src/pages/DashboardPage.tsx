import { useEffect, useState } from "react";
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

export function DashboardPage() {
  const { projects, projectsLoading, projectsError, health, healthLoading, healthError, refresh, startupState } = useAppData();
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatusResponse | null>(null);
  const [syncBusyLive, setSyncBusyLive] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const visibleProjects = sortProjectsByActivity(projects);
  const isInitialProjectsLoad = projectsLoading && visibleProjects.length === 0;
  const applianceStatus = startupState && startupState !== "ready" ? "loading" : healthLoading ? "loading" : health?.appliance_available ? "online" : "offline";
  const applianceLabel = startupState === "starting" ? "Starter …" : startupState === "connecting" ? "Kobler til …" : healthLoading ? "Laster" : health?.appliance_available ? "Klar" : "offline";
  const metrics = buildDashboardMetrics(visibleProjects);
  const analysisStartupBusy = analysisStatus?.status === "startup_pending" || analysisStatus?.startup_grace_active === true;
  const applianceActivity = syncStatus?.activity && syncStatus.activity !== "idle" ? syncStatus.activity : analysisStartupBusy ? "analysis" : analysisStatus?.activity ?? "idle";
  const syncHasStaleLock = Boolean(syncStatus?.last_error && isLockBusyError(syncStatus.last_error));
  const applianceBusy =
    syncBusyLive || syncStatus?.running === true || analysisStatus?.running === true || analysisStartupBusy || syncStatus?.lock_exists === true || analysisStatus?.lock_exists === true;
  const startupLabel = startupState === "starting" ? "Starter …" : startupState === "connecting" ? "Kobler til …" : null;
  const explicitSyncFailure = Boolean(syncStatus?.error_code && ["sync_failed", "project_sync_failed", "onedrive_sync_failed", "graph_auth_failed", "graph_permission_denied", "auth_failed"].includes(syncStatus.error_code));
  const syncPillStatus = startupLabel ? "RUNNING" : applianceBusy ? "RUNNING" : syncHasStaleLock ? "idle" : explicitSyncFailure ? "FAILED" : "idle";
  const syncPillLabel = startupLabel ?? (applianceBusy
    ? applianceActivity === "sync"
      ? SYNC_RUNNING_LABEL
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
  const syncLastErrorMessage = getVisibleSyncErrorMessage(syncStatus?.last_error, syncStatus?.error_code);
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
        latestSyncStatus = syncResult.value;
        setSyncStatus(syncResult.value);
        setSyncError(null);
      } else {
        setSyncError(getUserFacingErrorMessage(syncResult.reason, "Status kunne ikke hentes."));
      }

      if (analysisResult.status === "fulfilled") {
        latestAnalysisStatus = analysisResult.value;
        setAnalysisStatus(analysisResult.value);
      } else {
        console.error("[DashboardPage] getAnalysisStatus failed", analysisResult.reason);
      }

      const busyFromStatuses = Boolean(latestSyncStatus?.running || latestAnalysisStatus?.running);
      const busy = busyFromStatuses || syncBusyLive;
      if (!busyFromStatuses && syncBusyLive) {
        setSyncBusyLive(false);
      }
      timer = window.setTimeout(pollApplianceStatus, busy ? 600000 : 30000);
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
    setSyncMessage("Starter trygg OneDrive-sync uten rapportgenerering ...");
    let syncStarted = false;
    try {
      const response = await runSync();
      syncStarted = true;
      if (response.status === "already_running") {
        setSyncBusyLive(true);
      }
      setSyncMessage(response.status === "already_running" ? "OneDrive-sync kjører allerede." : "OneDrive-sync startet uten rapportgenerering.");
      try {
        setSyncStatus(await getSyncStatus());
        setSyncError(null);
      } catch (error) {
        setSyncError(getUserFacingErrorMessage(error, "Status kunne ikke hentes."));
      }
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 503 && error.message === APPLIANCE_BUSY_MESSAGE) {
        setSyncBusyLive(true);
        setSyncError(null);
        setSyncMessage(null);
        return;
      }
      setSyncMessage(getUserFacingErrorMessage(error, "Kunne ikke starte OneDrive-sync."));
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
    <div className="page-stack">
      <AppHeader
        title="Kontrollsenter"
        description=" "
        eyebrow={null}
      />

      <section className="surface surface--padded">
        <div className="dashboard-topline">
          <div className="dashboard-statusline__item">
            <span className="dashboard-statusline__label">Appliance</span>
            <StatusPill status={applianceStatus} label={applianceLabel} />
          </div>
          <div className="dashboard-statusline__item">
            <span className="dashboard-statusline__label">Sist synk fullført</span>
            <strong>{dashboardLastSyncedAt ? formatDateTime(dashboardLastSyncedAt) : "Ukjent"}</strong>
          </div>
          <div className="dashboard-statusline__item">
            <span className="dashboard-statusline__label">Siste analyse</span>
            <strong>{metrics.lastAnalyzedAt ? formatDateTime(metrics.lastAnalyzedAt) : "Ingen analyse"}</strong>
          </div>
          <div className="dashboard-statusline__item">
            <span className="dashboard-statusline__label">Siste rapport</span>
            <strong>{metrics.latestReportAt ? formatDateTime(metrics.latestReportAt) : "Ingen rapport"}</strong>
          </div>
          <div className="dashboard-statusline__item">
            <span className="dashboard-statusline__label">Sync</span>
            <StatusPill status={syncPillStatus} label={syncPillLabel} />
          </div>
          <div className="dashboard-actions">
            <div className="dashboard-actions__stack">
              <button
                type="button"
                className={`button${applianceBusy ? " button--muted" : ""}`}
                onClick={() => void handleRunSync()}
                disabled={syncButtonDisabled}
                title={syncButtonTitle}
                aria-label={`Synk OneDrive. ${syncButtonTitle}`}
              >
                Synk OneDrive
              </button>
              {busyActionNote ? <div className="dashboard-actions__note dashboard-actions__note--warning">{busyActionNote}</div> : null}
            </div>
          </div>
        </div>
        <div className="dashboard-sync-details">
          <span>Siste sync-start: {syncStatus?.last_started_at ? formatDateTime(syncStatus.last_started_at) : "Ikke kjørt fra portal"}</span>
          <span>Siste sync-ferdig: {syncStatus?.last_completed_at ? formatDateTime(syncStatus.last_completed_at) : "—"}</span>
          <span>Endrede filer siste sync: {syncStatus?.files_changed !== undefined ? syncStatus.files_changed.toLocaleString("nb-NO") : "0"}</span>
          <span>Rapporter funnet: {syncStatus?.reports_found !== undefined ? syncStatus.reports_found.toLocaleString("nb-NO") : "0"}</span>
        </div>
        {healthError ? <div className="inline-note inline-note--error">{healthError}</div> : null}
        {syncError ? <div className="inline-note inline-note--error">{syncError}</div> : null}
        {syncLastErrorMessage ? (
          <div className={syncLastErrorTone === "warning" ? "inline-note inline-note--warning" : "inline-note inline-note--error"}>{syncLastErrorMessage}</div>
        ) : null}
        {syncMessage ? <div className="inline-note">{syncMessage}</div> : null}
      </section>

      <section className="dashboard-metrics" aria-label="Dashboardnøkkeltall">
        <MetricCard label="Prosjekter totalt" value={metrics.totalProjects.toLocaleString("nb-NO")} />
        <MetricCard label="Med varsler" value={metrics.projectsWithWarnings.toLocaleString("nb-NO")} tone={metrics.projectsWithWarnings > 0 ? "warning" : "neutral"} />
        <MetricCard label="Uten rapport" value={metrics.projectsWithoutReport.toLocaleString("nb-NO")} tone={metrics.projectsWithoutReport > 0 ? "warning" : "neutral"} />
        <MetricCard label="Analysert siste 24t" value={metrics.analyzedLast24Hours.toLocaleString("nb-NO")} />
        <MetricCard label="Totalt antall filer" value={metrics.totalFiles.toLocaleString("nb-NO")} />
        <MetricCard label="Rapporter" value={metrics.totalReports.toLocaleString("nb-NO")} />
      </section>

      <section className="surface surface--padded">
        <div className="section-head">
          <div>
            <div className="section-kicker"> </div>
            <h2 className="section-title">Seneste rapporter</h2>
          </div>
          <div className="section-head__note">{projectsLoading ? "Laster …" : `${recentReports.length.toLocaleString("nb-NO")} nyeste`}</div>
        </div>

        {isInitialProjectsLoad ? (
          <div className="loading-copy">Laster prosjekter …</div>
        ) : recentReports.length > 0 ? (
          <div className="report-feed">
            {recentReports.map((project) => (
              <article className="report-feed__item" key={project.projectName}>
                <div className="report-feed__main">
                  <div className="report-feed__title">{project.latestReport?.name}</div>
                  <div className="report-feed__meta">
                    <span>{project.displayName}</span>
                    <span>{project.latestReport?.createdAt ? formatDateTime(project.latestReport.createdAt) : "Tidspunkt ukjent"}</span>
                    <StatusPill status={project.status.level} />
                  </div>
                </div>
                <div className="report-feed__actions">
                  {project.latestReport?.openUrl ? (
                    <>
                      <a className="button" href={project.latestReport.openUrl} target="_blank" rel="noreferrer">
                        Åpne rapport
                      </a>
                      <a className="button button--subtle" href={project.latestReport.openUrl} target="_blank" rel="noreferrer">
                        Åpne kommentardokument
                      </a>
                      <CopyLinkButton href={project.latestReport.openUrl} />
                    </>
                  ) : null}
                  <Link className="button button--secondary" to={project.projectHref}>
                    Åpne prosjekt
                  </Link>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="Ingen rapporter" description="Dashboardet har ingen rapporter å vise akkurat nå." />
        )}
      </section>
    </div>
  );
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
