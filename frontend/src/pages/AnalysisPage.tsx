import { useEffect, useRef, useState, type ReactNode } from "react";
import { AppHeader } from "../components/Layout";
import { ErrorState } from "../components/ErrorState";
import { ProjectTable } from "../components/ProjectTable";
import { StatusPill } from "../components/StatusPill";
import { useAppData } from "../context/AppDataContext";
import { ApiRequestError, formatDateTime, getAnalysisStatus, getUserFacingErrorMessage, runAnalysis } from "../lib/api";
import {
  ANALYSIS_STARTING_LABEL,
  ANALYSIS_STARTUP_GRACE_MS,
  APPLIANCE_BUSY_MESSAGE,
  getVisibleAnalysisErrorMessage,
  isAnalysisStartupStatus,
  isAnalysisTerminalStatus,
  isLockBusyError,
} from "../lib/applianceStatus";
import type { ProjectViewModel } from "../lib/projects";
import type { AnalysisStatusResponse } from "../types";

type AnalysisEmailMode = "daily_digest" | "immediate";

const ANALYSIS_EMAIL_MODES: Array<{
  mode: AnalysisEmailMode;
  label: string;
  description: string;
}> = [
  {
    mode: "daily_digest",
    label: "Legg resultat i daglig digest (kl. 05:50)",
    description: " ",
  },
  {
    mode: "immediate",
    label: "Send e-post når rapportene er ferdige",
    description: " ",
  },
];

interface AnalysisStartupState {
  startedAt: number;
  jobId: string | null;
  scopeLabel: string;
  graceExpired: boolean;
}

function parseAnalysisTimestamp(value: string | null | undefined): number | null {
  if (!value) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function isAnalysisCurrentRun(status: AnalysisStatusResponse | null, startup: AnalysisStartupState | null): boolean {
  if (!status || !startup) {
    return false;
  }
  if (status.job_id && startup.jobId && status.job_id === startup.jobId) {
    return true;
  }
  const startedAt = parseAnalysisTimestamp(status.last_started_at ?? status.start_requested_at);
  return startedAt !== null && startedAt >= startup.startedAt - 1000;
}

function isAnalysisActive(status: AnalysisStatusResponse | null): boolean {
  if (!status) {
    return false;
  }
  return Boolean(status.running || status.process_alive || status.lock_exists || status.status === "running");
}

function resolveAnalysisPhase(status: AnalysisStatusResponse | null, startup: AnalysisStartupState | null): "idle" | "starting" | "delayed" | "running" | "failed" | "completed" {
  if (!status && !startup) {
    return "idle";
  }
  if (status?.status === "completed") {
    return "completed";
  }
  const currentRun = isAnalysisCurrentRun(status, startup);
  if (status && isAnalysisTerminalStatus(status.status) && (currentRun || !startup)) {
    return "failed";
  }
  if (startup || isAnalysisStartupStatus(status?.status) || status?.startup_grace_active) {
    if (isAnalysisActive(status)) {
      return "running";
    }
    return startup?.graceExpired || status?.startup_grace_active === false ? "delayed" : "starting";
  }
  if (isAnalysisActive(status)) {
    return "running";
  }
  return "idle";
}

export function AnalysisPage() {
  const { projects, projectsLoading, projectsError, health, healthLoading, healthError, refresh } = useAppData();
  const [analysisTarget, setAnalysisTarget] = useState<ProjectViewModel | null | undefined>(undefined);
  const [selectedEmailMode, setSelectedEmailMode] = useState<AnalysisEmailMode>("daily_digest");
  const [analysisMessage, setAnalysisMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatusResponse | null>(null);
  const [analysisStatusError, setAnalysisStatusError] = useState<string | null>(null);
  const [analysisStatusLoading, setAnalysisStatusLoading] = useState(true);
  const [analysisStartup, setAnalysisStartup] = useState<AnalysisStartupState | null>(null);
  const previousRunningRef = useRef(false);
  const analysisStartupRef = useRef<AnalysisStartupState | null>(null);
  const analysisStartupTimerRef = useRef<number | undefined>(undefined);

  const graphWriteReady = health?.graph_write_status === "configured";
  const analysisDisabledReason = healthLoading
    ? "Kontrollerer Microsoft Graph-write ..."
    : graphWriteReady
      ? null
      : health?.graph_write_detail ?? "Microsoft Graph-write er ikke konfigurert.";
  const analysisStartupActive = Boolean(analysisStartup || analysisStatus?.startup_grace_active || isAnalysisStartupStatus(analysisStatus?.status));
  const analysisPhase = resolveAnalysisPhase(analysisStatus, analysisStartup);
  const analysisStartupNoticeVisible = analysisPhase === "starting" || analysisPhase === "delayed";
  const analysisStartupScopeLabel = analysisStartup?.scopeLabel ?? "for alle prosjekter";
  const analysisStartupTitle =
    analysisPhase === "delayed"
      ? "Analyse tar lenger tid enn forventet"
      : analysisPhase === "running"
        ? "Analyse er i gang"
        : "Starter analyse";
  const analysisStartupMessage =
    analysisPhase === "delayed"
      ? "Vi venter fortsatt på første status fra appliance."
      : `Kobler til OneDrive og klargjør prosjektliste ${analysisStartupScopeLabel} …`;
  const analysisPillStatus =
    analysisStatusLoading && !analysisStatus
      ? "loading"
      : analysisPhase === "starting" || analysisPhase === "delayed"
        ? "loading"
        : analysisPhase === "running"
          ? "RUNNING"
          : analysisPhase === "failed"
            ? "failed"
            : analysisPhase === "completed"
              ? "completed"
              : "idle";
  const analysisPillLabel =
    analysisStatusLoading && !analysisStatus
      ? "Laster"
      : analysisPhase === "starting"
        ? ANALYSIS_STARTING_LABEL
        : analysisPhase === "delayed"
          ? "Venter"
          : analysisPhase === "running"
            ? "Analyse pågår"
            : analysisPhase === "failed"
              ? analysisStatus?.status === "auth_failed"
                ? "Graph auth feilet"
                : analysisStatus?.status === "sync_failed"
                  ? "OneDrive sync feilet"
                  : "Analyse feilet"
              : analysisPhase === "completed"
                ? "Analyse fullført"
                : "Klar";
  const analysisVisibleErrorSource = analysisStatus?.last_error ?? analysisStatus?.last_start_error;
  const analysisFailureMessage =
    analysisPhase === "failed"
      ? getVisibleAnalysisErrorMessage(analysisVisibleErrorSource, {
          status: analysisStatus?.status,
          authStatus: analysisStatus?.auth_status,
          startupGraceActive: analysisStartupActive && !analysisStartup?.graceExpired,
        }) ?? "Siste analyse endte med feil."
      : null;
  const analysisFailureTone =
    analysisStatus?.status === "auth_failed"
      ? "danger"
      : analysisStatus?.status === "sync_failed"
        ? "danger"
        : analysisStatus?.status === "failed" && analysisVisibleErrorSource && isLockBusyError(analysisVisibleErrorSource)
          ? "warning"
          : "danger";
  const analysisStatusDetail =
    analysisVisibleErrorSource ?? (analysisStatus && isAnalysisTerminalStatus(analysisStatus.status) ? "Ingen tekniske detaljer registrert." : null);
  const analysisMessageTone =
    analysisMessage === APPLIANCE_BUSY_MESSAGE
      ? "warning"
      : analysisMessage?.toLowerCase().includes("kunne ikke") || analysisMessage?.toLowerCase().includes("feil")
        ? "danger"
        : "info";
  const visibleProjects = projects;

  useEffect(() => {
    analysisStartupRef.current = analysisStartup;
  }, [analysisStartup]);

  useEffect(() => {
    if (analysisStartupTimerRef.current !== undefined) {
      window.clearTimeout(analysisStartupTimerRef.current);
      analysisStartupTimerRef.current = undefined;
    }
    if (!analysisStartup || analysisStartup.graceExpired) {
      return;
    }
    const remainingMs = Math.max(0, analysisStartup.startedAt + ANALYSIS_STARTUP_GRACE_MS - Date.now());
    analysisStartupTimerRef.current = window.setTimeout(() => {
      const current = analysisStartupRef.current;
      if (!current || current.graceExpired) {
        return;
      }
      const next = { ...current, graceExpired: true };
      analysisStartupRef.current = next;
      setAnalysisStartup(next);
    }, remainingMs);
    return () => {
      if (analysisStartupTimerRef.current !== undefined) {
        window.clearTimeout(analysisStartupTimerRef.current);
        analysisStartupTimerRef.current = undefined;
      }
    };
  }, [analysisStartup?.graceExpired, analysisStartup?.startedAt]);

  useEffect(() => {
    if (!analysisStartup) {
      return;
    }
    if (analysisPhase === "starting" || analysisPhase === "delayed") {
      return;
    }
    analysisStartupRef.current = null;
    setAnalysisStartup(null);
    if (analysisStartupTimerRef.current !== undefined) {
      window.clearTimeout(analysisStartupTimerRef.current);
      analysisStartupTimerRef.current = undefined;
    }
  }, [analysisPhase, analysisStartup]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function pollAnalysisStatus() {
      try {
        const status = await getAnalysisStatus();
        if (cancelled) {
          return;
        }
        const startup = analysisStartupRef.current;
        const isCurrentRun = isAnalysisCurrentRun(status, startup);
        const isStaleStartupStatus =
          Boolean(startup) &&
          !isCurrentRun &&
          !status.running &&
          !status.process_alive &&
          !status.lock_exists;
        if (isStaleStartupStatus) {
          timer = window.setTimeout(pollAnalysisStatus, startup?.graceExpired ? 1000 : ANALYSIS_STARTUP_GRACE_MS / 5);
          return;
        }
        setAnalysisStatus(status);
        setAnalysisStatusError(null);
        if ((startup || isAnalysisStartupStatus(status.status)) && !isAnalysisActive(status)) {
          timer = window.setTimeout(pollAnalysisStatus, 1000);
        } else if (isAnalysisActive(status) || status.startup_grace_active) {
          timer = window.setTimeout(pollAnalysisStatus, status.startup_grace_active ? 1000 : 5000);
        } else {
          timer = window.setTimeout(pollAnalysisStatus, 30000);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        console.error("[AnalysisPage] getAnalysisStatus failed", error);
        const startup = analysisStartupRef.current;
        if (!startup || startup.graceExpired) {
          setAnalysisStatusError(getUserFacingErrorMessage(error, "Status kunne ikke hentes."));
        }
        timer = window.setTimeout(pollAnalysisStatus, startup ? 1000 : 30000);
      } finally {
        if (!cancelled) {
          setAnalysisStatusLoading(false);
        }
      }
    }

    void pollAnalysisStatus();
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [analysisStartup?.startedAt, analysisStartup?.graceExpired]);

  useEffect(() => {
    const wasRunning = previousRunningRef.current;
    const isRunning = Boolean(analysisStatus?.running);
    previousRunningRef.current = isRunning;
    if (wasRunning && !isRunning) {
      refresh();
    }
  }, [analysisStatus, refresh]);

  async function handleStartAnalysis(target: ProjectViewModel | null) {
    if (isSubmitting || analysisDisabledReason) {
      return;
    }
    const previousAnalysisStatus = analysisStatus;
    const startedAt = Date.now();
    const scopeLabel = target ? `for ${target.displayName}` : "for alle prosjekter";
    const optimisticStartup: AnalysisStartupState = {
      startedAt,
      jobId: null,
      scopeLabel,
      graceExpired: false,
    };
    setIsSubmitting(true);
    setAnalysisMessage(null);
    setAnalysisStatusError(null);
    if (analysisStartupTimerRef.current !== undefined) {
      window.clearTimeout(analysisStartupTimerRef.current);
      analysisStartupTimerRef.current = undefined;
    }
    analysisStartupRef.current = optimisticStartup;
    setAnalysisStartup(optimisticStartup);
    setAnalysisStatus((current) => ({
      running: false,
      process_alive: false,
      lock_exists: false,
      lock_stale: false,
      activity: "analysis",
      job_id: null,
      start_requested_at: new Date(startedAt).toISOString(),
      last_started_at: new Date(startedAt).toISOString(),
      last_completed_at: current?.last_completed_at ?? null,
      startup_grace_active: true,
      process_spawned: false,
      auth_status: "unknown",
      last_error: null,
      last_start_error: null,
      projects_synced: current?.projects_synced ?? 0,
      files_changed: current?.files_changed ?? 0,
      reports_found: current?.reports_found ?? 0,
      reports_generated: current?.reports_generated ?? 0,
      email_mode: selectedEmailMode,
      project_name: target?.projectName ?? null,
      status: "startup_pending",
      analysis_started: false,
    }));
    try {
      const response = await runAnalysis({
        project_name: target?.projectName ?? null,
        email_mode: selectedEmailMode,
      });
      const nextStartup: AnalysisStartupState = {
        ...(analysisStartupRef.current ?? optimisticStartup),
        jobId: response.job_id,
      };
      analysisStartupRef.current = nextStartup;
      setAnalysisStartup(nextStartup);
      setAnalysisStatus((current) => ({
        running: false,
        process_alive: false,
        lock_exists: false,
        lock_stale: false,
        activity: "analysis",
        job_id: response.job_id,
        start_requested_at: new Date(response.started_at).toISOString(),
        last_started_at: response.started_at,
        last_completed_at: current?.last_completed_at ?? null,
        startup_grace_active: true,
        process_spawned: false,
        auth_status: "unknown",
        last_error: null,
        last_start_error: null,
        projects_synced: response.projects_synced,
        files_changed: response.files_changed,
        reports_found: response.reports_found,
        reports_generated: response.reports_generated,
        email_mode: response.email_mode,
        project_name: response.project_name,
        status: "startup_pending",
        analysis_started: false,
      }));
      setAnalysisTarget(undefined);
      refresh();
    } catch (error) {
      analysisStartupRef.current = null;
      setAnalysisStartup(null);
      setAnalysisStatus(previousAnalysisStatus ?? null);
      if (analysisStartupTimerRef.current !== undefined) {
        window.clearTimeout(analysisStartupTimerRef.current);
        analysisStartupTimerRef.current = undefined;
      }
      if (error instanceof ApiRequestError && error.status === 503) {
        setAnalysisMessage(error.message === APPLIANCE_BUSY_MESSAGE ? APPLIANCE_BUSY_MESSAGE : getUserFacingErrorMessage(error, "Kunne ikke starte analyse."));
      } else {
        setAnalysisMessage(getUserFacingErrorMessage(error, "Kunne ikke starte analyse."));
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  if (projectsError) {
    return <ErrorState title="Kunne ikke laste analysevisningen" description={projectsError} />;
  }

  if (projectsLoading && visibleProjects.length === 0) {
    return (
      <div className="page-stack">
        <AppHeader
          title="Analyse"
          description=""
        />
        <section className="dashboard-card dashboard-card--padded">
          <div className="loading-copy">Laster prosjekter ...</div>
        </section>
      </div>
    );
  }

  const analysisLastStartedAt = analysisStatus?.last_started_at ?? analysisStatus?.start_requested_at;
  const analysisKpis = [
    {
      label: "Status",
      value: <StatusPill status={analysisPillStatus} label={analysisPillLabel} />,
      hint: analysisStatusLoading && !analysisStatus
        ? "Henter status fra appliance."
        : analysisPhase === "starting"
          ? "Starter analyse og venter på første status."
          : analysisPhase === "delayed"
            ? "Analyse har ikke rapportert status ennå."
            : analysisPhase === "running"
              ? "Analyse kjører akkurat nå."
              : analysisPhase === "failed"
                ? "Siste kjøring feilet."
                : analysisPhase === "completed"
                  ? "Siste kjøring er ferdig."
                  : "Ingen registrert kjøring.",
    },
    {
      label: "Sist startet",
      value: analysisLastStartedAt
        ? formatDateTime(analysisLastStartedAt)
        : "—",
      hint: analysisLastStartedAt ? "Siste registrerte starttidspunkt." : "Ingen starttidspunkt ennå.",
    },
    {
      label: "Sist fullført",
      value: analysisStatus?.last_completed_at ? formatDateTime(analysisStatus.last_completed_at) : "—",
      hint: analysisStatus?.last_completed_at ? "Siste registrerte fullføring." : "Ingen fullføring ennå.",
    },
    {
      label: "Rapporter generert",
      value: analysisStatus ? analysisStatus.reports_generated.toLocaleString("nb-NO") : "—",
      hint: analysisStatus ? "Generert av siste analysekjøring." : "Ingen rapporter registrert ennå.",
    },
  ];

  return (
    <div className="page-stack analysis-page">
      <AppHeader
        title="Analyse"
        description=" "
      />

      <section className="dashboard-card dashboard-card--padded analysis-hero">
        <div className="analysis-hero__header">
          <div>
            <div className="section-kicker">Kjøring</div>
            <h2 className="section-title">Start analyse</h2>
          </div>
          <div className="analysis-hero__actions">
            <button
              type="button"
              className="button button--danger action-button action-button--danger"
              onClick={() => setAnalysisTarget(null)}
              disabled={Boolean(analysisDisabledReason) || visibleProjects.length === 0}
              title={analysisDisabledReason ?? "Start analyse for alle prosjekter"}
            >
              Analyser alle prosjekter
            </button>
          </div>
        </div>

        <div className="analysis-kpi-grid">
          {analysisKpis.map((item) => (
            <AnalysisKpiCard key={item.label} label={item.label} value={item.value} hint={item.hint} />
          ))}
        </div>

        <div className="analysis-hero__body">
          <p className="analysis-hero__note">Velg e-postflyt i dialogen før vi sender jobben til appliance. Analyse kan kun startes herfra.</p>
          <div className="analysis-alert-stack">
            {analysisDisabledReason ? (
              <AnalysisAlert tone="warning" title="Analyse kan ikke startes" message={analysisDisabledReason} />
            ) : null}
            {healthError ? <AnalysisAlert tone="danger" title="Helsedata kunne ikke lastes" message={healthError} /> : null}
            {analysisStartupNoticeVisible ? (
              <AnalysisStartupNotice
                tone={analysisPhase === "delayed" ? "warning" : "info"}
                title={analysisStartupTitle}
                message={analysisStartupMessage}
              />
            ) : null}
            {analysisStatusLoading && !analysisStartupNoticeVisible ? <div className="inline-note inline-note--muted">Laster analyse-status ...</div> : null}
            {analysisStatusError && !analysisStartupNoticeVisible ? (
              <AnalysisAlert
                tone="warning"
                title="Analyse-status er midlertidig utilgjengelig"
                message="Vi fikk ikke lest status akkurat nå. Prøver igjen automatisk."
                detail={analysisStatusError}
              />
            ) : null}
            {analysisFailureMessage ? (
              <AnalysisAlert
                tone={analysisFailureTone}
                title={
                  analysisStatus?.status === "auth_failed"
                    ? "Graph auth feilet"
                    : analysisStatus?.status === "sync_failed"
                      ? "OneDrive sync feilet"
                      : analysisFailureTone === "warning"
                        ? "Analyse trenger oppmerksomhet"
                        : "Analyse feilet"
                }
                message={analysisFailureMessage}
                detail={analysisStatusDetail}
              />
            ) : null}
            {analysisMessage ? (
              <AnalysisAlert
                tone={analysisMessageTone}
                title={analysisMessageTone === "danger" ? "Analyse kunne ikke startes" : analysisMessage === APPLIANCE_BUSY_MESSAGE ? "Analyse er opptatt" : "Analyse startet"}
                message={analysisMessage}
              />
            ) : null}
          </div>
        </div>
      </section>

      <section className="dashboard-card dashboard-card--padded analysis-projects">
        <div className="analysis-projects__head">
          <div>
            <div className="section-kicker">Prosjekter</div>
            <h2 className="section-title">Velg prosjekt</h2>
          </div>
          <div className="analysis-projects__count">
            {visibleProjects.length.toLocaleString("nb-NO")} prosjekter
          </div>
        </div>

        <ProjectTable
          projects={visibleProjects}
          emptyLabel="Ingen prosjekter å analysere."
          onAnalyzeProject={(project) => setAnalysisTarget(project)}
        />
      </section>

      {analysisTarget !== undefined ? (
        <AnalysisRunDialog
          project={analysisTarget}
          selectedEmailMode={selectedEmailMode}
          isSubmitting={isSubmitting}
          onEmailModeChange={setSelectedEmailMode}
          onCancel={() => setAnalysisTarget(undefined)}
          onConfirm={() => void handleStartAnalysis(analysisTarget)}
        />
      ) : null}
    </div>
  );
}

function AnalysisKpiCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint: string;
}) {
  const isTextValue = typeof value === "string";

  return (
    <div className="kpi-card">
      <div className="kpi-card__label">{label}</div>
      <div className={`kpi-card__value ${isTextValue ? "kpi-card__value--muted" : ""}`}>{value}</div>
      <div className="kpi-card__hint">{hint}</div>
    </div>
  );
}

function AnalysisAlert({
  tone,
  title,
  message,
  detail,
}: {
  tone: "info" | "warning" | "danger";
  title: string;
  message: string;
  detail?: string | null;
}) {
  return (
    <article className={`analysis-alert analysis-alert--${tone}`}>
      <div className="analysis-alert__title">{title}</div>
      <p className="analysis-alert__message">{message}</p>
      {detail ? (
        <details className="analysis-alert__details">
          <summary className="analysis-alert__summary">Vis tekniske detaljer</summary>
          <div className="analysis-alert__details-content">
            <pre className="analysis-alert__code">{detail}</pre>
          </div>
        </details>
      ) : null}
    </article>
  );
}

function AnalysisStartupNotice({
  tone,
  title,
  message,
}: {
  tone: "info" | "warning";
  title: string;
  message: string;
}) {
  return (
    <article className={`analysis-startup analysis-startup--${tone}`} role="status" aria-live="polite">
      <div className="sync-loader analysis-startup__spinner" aria-hidden="true" />
      <div className="analysis-startup__content">
        <div className="analysis-startup__title">{title}</div>
        <p className="analysis-startup__message">{message}</p>
      </div>
    </article>
  );
}

export function AnalysisRunDialog({
  project,
  selectedEmailMode,
  isSubmitting,
  onEmailModeChange,
  onCancel,
  onConfirm,
}: {
  project: ProjectViewModel | null;
  selectedEmailMode: AnalysisEmailMode;
  isSubmitting: boolean;
  onEmailModeChange: (value: AnalysisEmailMode) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const title = project ? `Analyser ${project.displayName}` : "Analyser alle prosjekter";
  const description = project
    ? "Denne analysen starter appliance-pipelinen for det valgte prosjektet og kan sende e-post når rapportene er ferdige."
    : "Denne analysen starter appliance-pipelinen for alle synlige prosjekter og kan samle resultatet i digest eller sende e-post når rapportene er ferdige.";

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="analysis-dialog-title">
        <div className="section-head">
          <div>
            <div className="section-kicker"> </div>
            <h2 className="section-title" id="analysis-dialog-title">
              {title}
            </h2>
          </div>
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={isSubmitting}>
            Lukk
          </button>
        </div>

        <p className="modal-copy">{description}</p>

        <div className="analysis-mode-list" role="radiogroup" aria-label="E-postflyt">
          {ANALYSIS_EMAIL_MODES.map((option) => (
            <label key={option.mode} className={`analysis-mode-option ${selectedEmailMode === option.mode ? "analysis-mode-option--active" : ""}`}>
              <input
                type="radio"
                name="analysis-email-mode"
                value={option.mode}
                checked={selectedEmailMode === option.mode}
                onChange={() => onEmailModeChange(option.mode)}
                disabled={isSubmitting}
              />
              <span>
                <strong>{option.label}</strong>
                <small>{option.description}</small>
              </span>
            </label>
          ))}
        </div>

        <div className="modal-panel__actions">
          <button type="button" className="button button--secondary" onClick={onCancel} disabled={isSubmitting}>
            Avbryt
          </button>
          <button type="button" className="button" onClick={onConfirm} disabled={isSubmitting}>
            Start analyse
          </button>
        </div>
      </section>
    </div>
  );
}
